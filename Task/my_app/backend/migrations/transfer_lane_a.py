"""Phase 5 Wave1 车道 A：battery / ms_sla / ran_ume 三域 SQLite -> PostgreSQL。

执行顺序（与计划 5.1/5.2/R0 对齐）：
1. R0：先把本次要迁的 sqlite（含 -wal/-shm）备份到 backup\\phase5_wave1_<时间戳>\\。
2. 5.1：确保 PG 中 battery / ms_sla / ran_ume schema 存在（已存在则不动其它 schema）。
3. 5.2：逐表 DROP+CREATE（PRAGMA 反推 DDL + 类型修正）+ 分批搬运 + 提交。
4. 校验：表清单、行数、全行 MD5 三方对账；结果写回备份目录 report.json。

约束：
- 只写 PG 的 battery / ms_sla / ran_ume 三个 schema，不碰 app/eflow/fw/lte_pl/public。
- SQLite 源只读（mode=ro），永不删除。
- 不修改 backend/.env、不改 MY_APP_DB_MODE（保持 sqlite 回退态）。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

import transfer_lib as tl  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("transfer_lane_a")

DEFAULT_BACKUP_ROOT = ROOT / "backup"

LANES = [
    {
        "name": "battery",
        "schema": "battery",
        "primary": ROOT / "data" / "battery" / "battery_kpi.sqlite3",
        "fallback": None,
    },
    {
        "name": "ms_sla",
        "schema": "ms_sla",
        "primary": ROOT / "data" / "ms_sla" / "lbr_ms_sla_kpi.sqlite3",
        "fallback": None,
    },
    {
        "name": "ran_ume",
        "schema": "ran_ume",
        "primary": ROOT / "backend" / "services" / "ran_kpi_daily.sqlite3",
        "fallback": ROOT / "data" / "ran_ume" / "ran_kpi_daily.sqlite3",
    },
]


def _usable(path):
    if not path or not Path(path).exists():
        return False
    try:
        info = tl.inspect_source(path)
        return bool(info) and sum(i["rows"] for i in info) > 0
    except Exception:  # noqa: BLE001
        return False


def choose_sources(ran_source=None):
    """按 lane 选择本次迁移的 sqlite 源；ran_ume 支持 backend|data 显式指定。"""
    chosen = []
    for lane in LANES:
        primary = lane["primary"]
        if lane["name"] == "ran_ume" and ran_source:
            if ran_source == "data":
                primary = lane["fallback"]
            elif ran_source == "backend":
                primary = lane["primary"]
            else:
                raise SystemExit(f"--ran-source 只支持 backend|data，收到 {ran_source!r}")
        if _usable(primary):
            chosen.append((lane, primary))
        elif lane["fallback"] and _usable(lane["fallback"]):
            logger.warning("%s 主源不可用，回退到 %s", lane["name"], lane["fallback"])
            chosen.append((lane, lane["fallback"]))
        else:
            raise SystemExit(
                f"{lane['name']} 无可用的 sqlite 源（主: {lane['primary']}，备: {lane['fallback']}）"
            )
    return chosen


def _mask_url(url):
    """日志/报告里隐藏密码。"""
    if "@" in url:
        scheme, rest = url.split("://", 1)
        host = rest.rsplit("@", 1)[-1]
        return f"{scheme}://***@{host}"
    return url


def main(argv=None):
    parser = argparse.ArgumentParser(description="Phase 5 Wave1 车道 A 迁移")
    parser.add_argument("--only", nargs="*", choices=[l["name"] for l in LANES],
                        help="migrate only these lanes (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="read-only inspect, no PG write")
    parser.add_argument("--skip-backup", action="store_true",
                        help="skip R0 sqlite file backup (not recommended)")
    parser.add_argument("--skip-verify", action="store_true",
                        help="skip row-count/MD5 verification")
    parser.add_argument("--batch-size", type=int, default=tl.DEFAULT_BATCH_SIZE,
                        help="rows per batch (default 5000)")
    parser.add_argument("--method", choices=["executemany", "pandas"], default="executemany",
                        help="copy method (executemany default, or pandas)")
    parser.add_argument("--ran-source", choices=["backend", "data"], default=None,
                        help="ran_ume source: backend (default) or data")
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_ROOT),
                        help="backup root (default <project>/backup)")
    parser.add_argument("--report-path", default=None,
                        help="write JSON report to this path (default: backup dir report.json)")
    args = parser.parse_args(argv)

    tl.load_env(ROOT / "backend" / ".env")
    pg_url = tl.get_pg_url()
    if not pg_url:
        raise SystemExit("未找到 DATABASE_URL（环境变量或 backend/.env）")

    names = args.only or [l["name"] for l in LANES]
    chosen = [(lane, src) for lane, src in choose_sources(args.ran_source) if lane["name"] in names]
    if not chosen:
        raise SystemExit("没有可迁移的域（--only 过滤后为空）")

    if args.dry_run:
        for lane, src in chosen:
            print(f"==== {lane['name']} -> PG schema {lane['schema']}  source: {src}")
            for t in tl.inspect_source(src):
                print(
                    f"  {t['table']}  rows={t['rows']}  "
                    f"cols={len(t['columns'])}  types={t['pg_types']}"
                )
        return

    if not args.skip_backup:
        backup_dir, copied = tl.backup_sqlite_files([src for _, src in chosen], args.backup_dir)
        logger.info("R0 backup done: %s (%d files)", backup_dir, len(copied))
    else:
        backup_dir = None

    import psycopg2

    conn = psycopg2.connect(pg_url, connect_timeout=15)
    engine = None
    try:
        if args.method == "pandas":
            from sqlalchemy import create_engine

            engine = create_engine(pg_url)

        report = {
            "task": "phase5_wave1_lane_a",
            "pg": _mask_url(pg_url),
            "backup_dir": str(backup_dir) if backup_dir else None,
            "batch_size": args.batch_size,
            "method": args.method,
            "lanes": [],
        }
        all_ok = True

        for lane, src in chosen:
            schema = lane["schema"]
            tl.ensure_schema(conn, schema)
            logger.info("[%s] schema=%s source=%s", lane["name"], schema, src)
            tables = tl.inspect_source(src)
            lane_report = {
                "lane": lane["name"],
                "schema": schema,
                "source": str(src),
                "tables": [],
            }
            for t in tables:
                table = t["table"]
                logger.info("[%s] copying %s (%d rows)", lane["name"], table, t["rows"])
                copied_rows = tl.copy_table(
                    src,
                    conn,
                    schema,
                    table,
                    batch_size=args.batch_size,
                    method=args.method,
                    engine=engine,
                    progress=lambda n, name=table: logger.info(
                        "[%s] %s copied %d rows", lane["name"], name, n
                    ),
                )
                lane_report["tables"].append(
                    {"table": table, "src_rows": t["rows"], "copied": copied_rows}
                )
                logger.info("[%s] %s done: %d rows", lane["name"], table, copied_rows)

            if not args.skip_verify:
                logger.info("[%s] verifying", lane["name"])
                results = tl.verify_migration(src, conn, schema, batch_size=args.batch_size)
                lane_report["verify"] = results
                for r in results:
                    status = "OK" if r["ok"] else "MISMATCH"
                    logger.info(
                        "[%s] %-48s %s  src=%s pg=%s md5=%s",
                        lane["name"], r["table"], status, r["src_rows"], r["pg_rows"],
                        "MATCH" if r["ok"] else "DIFF",
                    )
                    all_ok = all_ok and r["ok"]
            report["lanes"].append(lane_report)

        if args.report_path:
            report_path = Path(args.report_path)
        elif backup_dir:
            report_path = backup_dir / "report.json"
        else:
            report_path = None
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report["backup_dir"] = str(report_path.parent)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info("report written: %s", report_path)

        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not all_ok:
            raise SystemExit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    tl._force_utf8_stdio()
    main()
