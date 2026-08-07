"""Phase 5 Wave2：db/app.db -> PG app schema（insert-only）。

与 Wave1 的 DROP+CREATE 不同，Wave2 的 app schema 表结构由 Alembic
（0001/0002/5415704359dc）创建，因此本脚本：
1. 只读打开 db/app.db（URI mode=ro），绝不修改源文件；
2. 跳过 sqlite 自带的 alembic_version，只搬运 37 张业务表；
3. 对 PG 中已存在的表只做列校验 + INSERT，不 DROP、不 CREATE；
4. 对 PG 中缺失的动态表（如 eflow_*）才 CREATE（不带 DROP）后 INSERT；
5. 搬运后按表清单 + 行数 + 全行 MD5 对账。

约束：
- 不修改 backend/.env；连接串仅来自环境变量或 backend/.env 的 DATABASE_URL；
- 只写 PG app schema，不碰其它 schema；
- 默认拒绝向非空目标表追加，避免 insert-only 重跑造成重复数据（--force 可显式放行）。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

import transfer_lib as tl  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("transfer_app")

DEFAULT_BACKUP_ROOT = ROOT / "backup"
PG_SCHEMA = "app"
SKIP_TABLES = {"alembic_version"}


def _mask_url(url):
    """日志/报告里隐藏密码。"""
    if "@" in url:
        scheme, rest = url.split("://", 1)
        host = rest.rsplit("@", 1)[-1]
        return f"{scheme}://***@{host}"
    return url


def _source_tables(sqlite_path):
    conn = tl.open_sqlite(sqlite_path)
    try:
        return sorted(t for t in tl.sqlite_tables(conn) if t not in SKIP_TABLES)
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Phase 5 Wave2: app.db -> PG app schema (insert-only)")
    parser.add_argument("--dry-run", action="store_true", help="只读检查源与 PG 现状，不写 PG")
    parser.add_argument("--skip-backup", action="store_true", help="跳过 R0 sqlite 文件备份（不推荐）")
    parser.add_argument("--skip-verify", action="store_true", help="跳过行数/MD5 对账")
    parser.add_argument("--force", action="store_true", help="允许向非空目标表追加（默认拒绝）")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="先 DELETE 清空 app schema 目标表（保留表结构）再搬运，用于重跑/恢复",
    )
    parser.add_argument("--batch-size", type=int, default=tl.DEFAULT_BATCH_SIZE, help="每批行数（默认 5000）")
    parser.add_argument("--method", choices=["executemany", "pandas"], default="executemany")
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_ROOT), help="R0 备份根目录")
    parser.add_argument("--report-path", default=None, help="JSON 报告路径（默认写入备份目录或 TMP）")
    args = parser.parse_args(argv)

    tl.load_env(ROOT / "backend" / ".env")
    pg_url = tl.get_pg_url()
    if not pg_url:
        raise SystemExit("未找到 DATABASE_URL（环境变量或 backend/.env）")

    sqlite_path = ROOT / "db" / "app.db"
    tables = _source_tables(sqlite_path)
    logger.info("app.db 业务表 %d 张（已排除 alembic_version）", len(tables))

    if args.dry_run:
        for t in tables:
            info = next(i for i in tl.inspect_source(sqlite_path) if i["table"] == t)
            print(
                f"  {t:45s} rows={info['rows']:>8d} cols={len(info['columns'])} "
                f"types={info['pg_types']}"
            )
        return

    if not args.skip_backup:
        backup_dir, copied = tl.backup_sqlite_files(
            [sqlite_path], args.backup_dir, phase="phase5_wave2"
        )
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

        if args.reset:
            for table in tables:
                if tl.pg_table_exists(conn, PG_SCHEMA, table):
                    with conn.cursor() as cur:
                        cur.execute(
                            f"DELETE FROM {tl.pg_quote(PG_SCHEMA)}.{tl.pg_quote(table)}"
                        )
            conn.commit()
            logger.info("reset done: cleared %d target tables (schema kept)", len(tables))

        report = {
            "task": "phase5_wave2_app",
            "pg": _mask_url(pg_url),
            "pg_schema": PG_SCHEMA,
            "source": str(sqlite_path),
            "backup_dir": str(backup_dir) if backup_dir else None,
            "batch_size": args.batch_size,
            "method": args.method,
            "force": args.force,
            "reset": args.reset,
            "tables": [],
        }
        all_ok = True

        for table in tables:
            existed = tl.pg_table_exists(conn, PG_SCHEMA, table)
            if existed and not args.force:
                existing_rows = tl.pg_count(conn, PG_SCHEMA, table)
                if existing_rows:
                    raise SystemExit(
                        f"{PG_SCHEMA}.{table} 已有 {existing_rows} 行；"
                        "insert-only 重跑会重复，请先清理或用 --force 确认追加"
                    )
            logger.info(
                "[%s] %s (%s)", PG_SCHEMA, table,
                "existing -> insert only" if existed else "missing -> create + insert",
            )
            copied_rows = tl.copy_table(
                sqlite_path,
                conn,
                PG_SCHEMA,
                table,
                batch_size=args.batch_size,
                method=args.method,
                engine=engine,
                drop_existing=False,
                progress=lambda n, name=table: logger.info(
                    "[%s] %s copied %d rows", PG_SCHEMA, name, n
                ),
            )
            report["tables"].append(
                {"table": table, "existed": existed, "copied": copied_rows}
            )
            logger.info("[%s] %s done: %d rows", PG_SCHEMA, table, copied_rows)

        if not args.skip_verify:
            logger.info("verifying %d tables", len(tables))
            results = tl.verify_migration(
                sqlite_path,
                conn,
                PG_SCHEMA,
                exclude_tables=sorted(SKIP_TABLES),
                batch_size=args.batch_size,
            )
            report["verify"] = results
            for r in results:
                status = "OK" if r["ok"] else "MISMATCH"
                logger.info(
                    "[%s] %-48s %s  src=%s pg=%s md5=%s",
                    PG_SCHEMA, r["table"], status, r["src_rows"], r["pg_rows"],
                    "MATCH" if r["ok"] else "DIFF",
                )
                all_ok = all_ok and r["ok"]

        if args.report_path:
            report_path = Path(args.report_path)
        elif backup_dir:
            report_path = backup_dir / "report.json"
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_path = ROOT / "TMP" / f"transfer_app_report_{ts}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
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
