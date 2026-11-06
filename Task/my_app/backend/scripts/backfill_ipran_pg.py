# -*- coding: utf-8 -*-
"""把远端 SQLite 的 IP RAN 数据一次性回填到本机 PG ``ipran_ume`` schema。

为什么需要
----------
本机 PG 的 ``ipran_ume`` 6 张表原本**没有同步任务**：``ipran_kpi_sync`` 只在
远端 DbWriter API 写入**失败**时才兜底写本机，远端一旦稳定，本机就冻结成孤儿
快照（2026-11-04 排查时落后 15.5 小时）。现已在该服务的
``WRITE_LOCAL_MIRROR`` 分支加入「远端成功后主动镜像」，从下一轮采集起本机
自动保持新鲜；本脚本负责把**当前这段历史缺口**一次补齐。

用法（必须用生产 Python 3.12，脚本间接依赖 pandas / psycopg2）::

    cd D:\\01_RPA\\Task\\my_app
    py -3.12 -m backend.scripts.backfill_ipran_pg --dry-run
    py -3.12 -m backend.scripts.backfill_ipran_pg
    py -3.12 -m backend.scripts.backfill_ipran_pg --since 2026-11-01

两种模式（差别在是否按本机水位裁行，见 backfill_table 的注释）
    不传 --since —— **追水位**：从「本机水位前一天」读，只写水位-2h 之后的行，
      用于日常把落后几个小时的本机库追平。
    传 --since  —— **补历史空洞**：从指定日期整段重写，不按水位裁行。
      本机镜像只追头部水位（``mirror_rows_to_local``），中间断过的日子**永远不会
      自动长回来**，只能靠这个模式补。例如 2026-11-05 补 10 月那段：
      ``--since 2026-10-05 --tables Metro_ring_me_15mins``

幂等：写入走 ``ON CONFLICT DO UPDATE``，重复执行不会产生重复行。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config.remote_host import get_api_base_url          # noqa: E402
from backend.database import DB_MODE, PG_DATABASE_URL, get_raw_connection  # noqa: E402
from backend.services.ipran_ume_kpi_service import (            # noqa: E402
    DB_PATH, _norm_begin_time, mirror_rows_to_local,
)

DB_NAME = "ipran_ume_kpi.sqlite3"
TABLES = (
    "HQ_M6K_FW_bnctp_15mins",
    "IPCORE_HQ_ODC_bnctp_15mins",
    "Metro_ring_me_15mins",
    "Gbarnga_Buchanna_RIA_Kakata_me_15mins",
    "Banjor_ELWA_me_15mins",
    "OLT_bnctp_15mins",
)
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def remote_query(sql: str, limit: int, timeout: int = 180):
    url = f"{get_api_base_url()}/api/query"
    payload = json.dumps({"db": DB_NAME, "sql": sql, "limit": limit},
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"},
        method="POST")
    with _OPENER.open(req, timeout=timeout) as resp:
        d = json.loads(resp.read().decode("utf-8", "replace"))
    if not d.get("success", True):
        raise RuntimeError(d.get("error") or "远端返回 success=false")
    return list(d.get("columns") or []), [list(r) for r in (d.get("rows") or [])]


def pg_max(table: str) -> str:
    """本机该表最新业务时间（归一化到 YYYY-MM-DD HH:MM:SS）。"""
    with get_raw_connection(DB_PATH, logical_name="ipran_ume", timeout=20.0) as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT MAX("Begin Time") FROM "{table}"')
        row = cur.fetchone()
        return _norm_begin_time(row[0] if row else None)


def remote_max(table: str, since: str) -> str:
    cols, rows = remote_query(
        f'SELECT MAX("Begin Time") FROM "{table}" '
        f'WHERE "Begin Time" >= \'{since}\'', 1)
    return str(rows[0][0]) if rows and rows[0] else ""


def backfill_table(table: str, since_arg: str, batch: int,
                   dry_run: bool) -> dict:
    t0 = time.time()
    water = pg_max(table)
    if since_arg:
        since = since_arg
    elif water:
        since = (datetime.strptime(water[:10], "%Y-%m-%d")
                 - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        since = "2026-01-01"
    rmax = remote_max(table, since)
    # 固定 cutoff（回填开始时算一次，不随写入推进）：只写「水位 - 2h」之后的
    # 缺口行。固定而非动态，是因为按 rowid 分批时业务时间未必单调，边写边
    # 抬高水位会把后面的批次误裁掉。留 2h 重叠以覆盖 UME 的少量历史回补。
    #
    # ⚠ 显式传 --since 补**历史空洞**时必须关掉这个过滤。否则 cutoff 仍按
    #   「当前水位 - 2h」算，比水位老的行被整段裁掉 —— 本机 PG 的 ipran_ume
    #   缺 2026-10-05~10-26（远端权威库齐全），照旧写法执行
    #   `--since 2026-10-05` 只会写进最近 2 小时，历史洞一个字节也补不上
    #   （2026-11-05 排查「IP RAN 看板默认窗口改 31 天」时抓到）。
    #   不传 --since 的追水位行为保持不变。
    cutoff = ""
    if water and not since_arg:
        try:
            cutoff = (datetime.strptime(water[:19], "%Y-%m-%d %H:%M:%S")
                      - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            cutoff = ""

    last_rid, total_fetch, total_write, pages = 0, 0, 0, 0
    while True:
        sql = (
            f'SELECT rowid AS "_rid", * FROM "{table}" '
            f'WHERE "Begin Time" >= \'{since}\' AND rowid > {last_rid} '
            f'ORDER BY rowid'
        )
        cols, rows = remote_query(sql, batch)
        if not rows:
            break
        last_rid = rows[-1][0]
        headers = cols[1:]
        body = [r[1:] for r in rows]
        total_fetch += len(body)
        if cutoff and "Begin Time" in headers:
            bi = headers.index("Begin Time")
            body = [r for r in body
                    if _norm_begin_time(r[bi] if bi < len(r) else "") >= cutoff]
        pages += 1
        if not dry_run and body:
            # 固定 cutoff 已裁好缺口，函数内不再做动态水位过滤。
            # upsert 幂等，重叠窗口里的重复行自动覆盖。
            total_write += mirror_rows_to_local(
                table, headers, body, apply_watermark=False)
        print(f"    page {pages:>3}: fetch={len(rows):>6} "
              f"write={len(body):>6} (rid<={last_rid})", flush=True)
        if len(rows) < batch:
            break

    return {
        "table": table, "water_before": water, "since": since,
        "cutoff": cutoff or "（历史回填模式，不按水位裁）",
        "remote_max": rmax, "fetched": total_fetch,
        "written": total_write, "pages": pages,
        "water_after": pg_max(table) if not dry_run else water,
        "seconds": round(time.time() - t0, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default="",
                    help="起始日期 YYYY-MM-DD；默认取本机水位前一天")
    ap.add_argument("--batch", type=int, default=20000,
                    help="每批从远端拉取的行数（默认 20000）")
    ap.add_argument("--tables", default="", help="只处理指定表，逗号分隔")
    ap.add_argument("--dry-run", action="store_true", help="只探测不写入")
    args = ap.parse_args()

    if DB_MODE != "pg" or not PG_DATABASE_URL:
        print("ERROR: 需要 MY_APP_DB_MODE=pg 且 DATABASE_URL 可用", file=sys.stderr)
        return 2

    tables = ([t.strip() for t in args.tables.split(",") if t.strip()]
              if args.tables else list(TABLES))
    print(f"源: {get_api_base_url()} / {DB_NAME}")
    print(f"目标: 本机 PG ipran_ume | dry_run={args.dry_run} | "
          f"batch={args.batch} | tables={len(tables)}\n")

    results = []
    for t in tables:
        print(f"=== {t} ===", flush=True)
        try:
            r = backfill_table(t, args.since, args.batch, args.dry_run)
            results.append(r)
            print(f"  before={r['water_before']!r} since={r['since']} "
                  f"remote_max={r['remote_max']!r}")
            print(f"  fetched={r['fetched']} written={r['written']} "
                  f"pages={r['pages']} after={r['water_after']!r} "
                  f"{r['seconds']}s\n", flush=True)
        except Exception as e:  # noqa: BLE001 - 单表失败不阻断其余表
            print(f"  FAILED: {e!r}\n", file=sys.stderr, flush=True)
            results.append({"table": t, "error": repr(e)})

    print("=== 汇总 ===")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if not any("error" in r for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
