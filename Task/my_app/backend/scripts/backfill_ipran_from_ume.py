# -*- coding: utf-8 -*-
"""从 UME 重新拉取指定 IP RAN 收藏的历史窗口，补齐**远端权威库 + 本机 PG** 的缺口。

与 ``backfill_ipran_pg.py`` 的分工
----------------------------------
``backfill_ipran_pg.py`` 是从**远端 SQLite** 往本机 PG 回填，前提是远端有数据。
当远端也没有时（典型：2026-11-05~11-16 的 ``Gbarnga_Buchanna_RIA_Kakata`` ——
增量水位原先按全表 MAX 取，而 BU 的 Begin Time 比另外 3 个 ME 快 8 小时，
RIA/Kakata/Gbarnga 每轮的新行都被判成"水位之前"丢掉），只能回到 UME 用一个
更大的窗口重新拉取，再写入两库。

写入复用 ``ipran_ume_kpi_service.save_data_to_db_or_api()``：远端 upsert +
本机镜像 + 按 ME 的水位裁剪（2026-11-16 已修复），所以只会补真正缺的行，
按「ME + 日期」分批，避免单个请求过大。

用法（生产 Python 3.12）::

    cd D:\\01_RPA\\Task\\my_app
    python -m backend.scripts.backfill_ipran_from_ume --key Gbarnga_Buchanna_RIA_Kakata --days 14 --dry-run
    python -m backend.scripts.backfill_ipran_from_ume --key Gbarnga_Buchanna_RIA_Kakata --days 14

``--days`` 只接受 3 / 7 / 14 / 30（对应 UME 查询窗口档位）。实测 14 天窗口
该收藏返回约 14.6 万行，可正常导出。
"""
from __future__ import annotations

import argparse
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.services.ipran_ume_kpi_service as svc  # noqa: E402

_RANGE_BY_DAYS = {3: "3days", 7: "7days", 14: "14days", 30: "1month"}


def _group_by_me_day(headers: list, rows: list) -> "OrderedDict[tuple, list]":
    """按 (ME, 日期) 分组并保持行序；缺 ME 列时按日期分组。"""
    mi = headers.index("ME") if "ME" in headers else -1
    bi = headers.index("Begin Time")
    groups: "OrderedDict[tuple, list]" = OrderedDict()
    for r in rows:
        me = str(r[mi]) if mi >= 0 and mi < len(r) else ""
        day = svc._norm_begin_time(r[bi] if bi < len(r) else "")[:10]
        groups.setdefault((me, day), []).append(r)
    return groups


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--key", required=True,
                    help="IPRAN_KPI_QUERY_CONFIGS 的 key，如 Gbarnga_Buchanna_RIA_Kakata")
    ap.add_argument("--days", type=int, default=14, choices=sorted(_RANGE_BY_DAYS),
                    help="回看天数（UME 窗口档位）")
    ap.add_argument("--dry-run", action="store_true", help="只拉取并统计，不写库")
    args = ap.parse_args()

    if args.key not in svc.IPRAN_KPI_QUERY_CONFIGS:
        print(f"ERROR: 未登记的 key: {args.key}；可选 {list(svc.IPRAN_KPI_QUERY_CONFIGS)}",
              file=sys.stderr)
        return 2

    cfg = svc.IPRAN_KPI_QUERY_CONFIGS[args.key]
    table = cfg.get("table_name") or svc.sanitize_table_name(svc.build_filename(cfg))
    svc.TIME_RANGE = _RANGE_BY_DAYS[args.days]
    payload = svc.build_ipran_kpi_payload(cfg)
    print(f"key={args.key} table={table} window={payload['timeinfo']['start']} -> "
          f"{payload['timeinfo']['end']} dry_run={args.dry_run}", flush=True)

    client = svc.UmeSessionClient(svc.HOST, svc.PORT)
    client.login()
    qid = svc.create_history_query(client, payload)
    print(f"queryid={qid}", flush=True)
    try:
        svc.adaptive_poll_history_ready(client, qid, args.key, timeout=2400)
        stream = svc.export_history_to_memory(
            client, qid, f"backfill_{args.key}_{datetime.now():%Y%m%d%H%M%S}")
        headers, rows = svc.parse_xlsx_in_memory(stream)
        stream.close()
        if not headers or not rows:
            print("ERROR: UME 返回空数据（表头或数据行缺失）", file=sys.stderr)
            return 1
        print(f"fetched rows={len(rows)} headers={headers}", flush=True)

        bi, mi = headers.index("Begin Time"), headers.index("ME")
        stats: dict = {}
        for r in rows:
            me = str(r[mi])
            t = svc._norm_begin_time(r[bi])
            s = stats.setdefault(me, {"n": 0, "min": t, "max": t})
            s["n"] += 1
            s["min"] = min(s["min"], t)
            s["max"] = max(s["max"], t)
        for me in sorted(stats):
            s = stats[me]
            print(f"  {me}: n={s['n']} min={s['min']} max={s['max']}", flush=True)

        if args.dry_run:
            print("dry-run：不写库", flush=True)
            return 0

        groups = _group_by_me_day(headers, rows)
        print(f"分批写入 {len(groups)} 个 (ME, 日期) 组 ...", flush=True)
        total_written = 0
        for (me, day), chunk in groups.items():
            n = svc.save_data_to_db_or_api(table, headers, chunk)
            total_written += n
            print(f"  {me} {day}: fetched={len(chunk)} written={n}", flush=True)
        print(f"完成：fetched={len(rows)} written={total_written}", flush=True)
        return 0
    finally:
        if qid:
            try:
                rr = client.session.delete(
                    f"{client.base_url}{svc.HISTORY_POLL_PATH}?queryid={qid}",
                    headers=client.session.headers, timeout=20,
                    verify=svc.tls_verify("ume"))
                print(f"release query -> {rr.status_code}", flush=True)
            except Exception as e:  # noqa: BLE001 - 释放失败不影响已写入数据
                print(f"release query failed: {e}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
