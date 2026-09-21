# -*- coding: utf-8 -*-
"""对 native_catalog 里的每条 SQL 在远端只读 API 上做一次预检。

用法：
    python backend/services/_verify_native_catalog.py            # 全部
    python backend/services/_verify_native_catalog.py metro_ring # 指定 slug

只发 SELECT，失败明细按 dashboard 汇总。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8")

from backend.config.remote_host import get_api_base_url  # noqa: E402
from backend.services.native_catalog import DASHBOARDS  # noqa: E402

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TIMEOUT = 90


def query(db: str, sql: str, limit: int = 3000):
    url = f"{get_api_base_url()}/api/query"
    payload = json.dumps({"db": db, "sql": sql, "limit": limit},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with _OPENER.open(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def check_one(args):
    slug, w = args
    if w["chart"] == "text":
        return slug, w, True, "text(no sql)", 0, 0
    t0 = time.time()
    try:
        res = query(w["db"], w["sql"], w.get("limit") or 3000)
        ms = (time.time() - t0) * 1000
        if not res.get("success", True):
            return slug, w, False, str(res.get("error"))[:200], ms, 0
        return slug, w, True, "", ms, res.get("count", 0)
    except Exception as e:  # noqa: BLE001
        return slug, w, False, f"{type(e).__name__}: {str(e)[:200]}", (time.time() - t0) * 1000, 0


def main() -> int:
    targets = sys.argv[1:]
    boards = [d for d in DASHBOARDS if not targets or d["slug"] in targets]
    jobs = [(d["slug"], w) for d in boards for w in d["widgets"]]
    print(f"远端 {get_api_base_url()}  预检 {len(jobs)} 条 SQL\n")

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(check_one, jobs))

    by_board: dict[str, list] = {}
    for r in results:
        by_board.setdefault(r[0], []).append(r)

    total_ok = total_fail = 0
    for d in boards:
        rs = by_board.get(d["slug"], [])
        ok = sum(1 for r in rs if r[2])
        bad = [r for r in rs if not r[2]]
        total_ok += ok
        total_fail += len(bad)
        flag = "OK " if not bad else "FAIL"
        ms = max((r[4] for r in rs), default=0)
        print(f"[{flag}] {d['slug']:20} {ok:3}/{len(rs):3}  max={ms:7.0f}ms  ({d['category']})")
        for r in bad:
            print(f"        !! {r[1]['id']} {str(r[1]['title'])[:40]!r} db={r[1]['db']}")
            print(f"           {r[3]}")

    print(f"\n汇总: {total_ok} ok / {total_fail} failed / {len(jobs)} total")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
