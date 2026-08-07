"""Phase 5 Wave2 车道 B：lte_pl / fw / eflow（另含 ran_ume_ro 只读快照）SQLite -> PostgreSQL。

复用 Wave1 交付的公共搬运框架 backend/migrations/transfer_lib.py（幂等 DROP+重建、
分批 executemany、行数+MD5 对账），本脚本只负责车道 B 的差异点：

1. R0 备份：四个源库拷贝到 backup\\phase5_wave2_<时间戳>\\；>=300MB 的大文件
   （lte_pl 194MB 不触发、eflow 425MB 触发）用硬链接，其余文件级拷贝（含
   -wal/-shm 副作用文件）；所有源文件迁移前后各算一次 SHA256，必须一致。
2. schema 护栏：只允许写 lte_pl / fw / eflow / ran_ume_ro 四个 schema，
   触碰其它 schema 立即退出（ran_ume schema 已被 Wave1 占用，绝不碰）。
3. 大表：packet_loss_data（75 万行）按 batch_size=20000 分块读 + executemany 批写。
4. eflow_tt 无主键、无唯一约束：纯搬运，transfer_lib 按 PRAGMA 反推 DDL，
   无 pk 即不建任何主键/唯一索引。
5. ran_ume_ro：读库 data/ran_ume/ran_kpi_daily.sqlite3（与写库
   backend/services/ran_kpi_daily.sqlite3 分离是代码现状），先
   CREATE SCHEMA IF NOT EXISTS ran_ume_ro 再搬 4 表。

约束：不改 backend/.env、不改 MY_APP_DB_MODE、不改 transfer_lib.py、源 sqlite 只读。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

import transfer_lib as tl  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("transfer_lane_b")

DEFAULT_BACKUP_ROOT = ROOT / "backup"
ALLOWED_SCHEMAS = {"lte_pl", "fw", "eflow", "ran_ume_ro"}
HARDLINK_MIN_BYTES = 300 * 1024 * 1024

LANES = [
    {
        "name": "lte_pl",
        "schema": "lte_pl",
        "source": ROOT / "data" / "packet_lost" / "lte_pl.sqlite3",
    },
    {
        "name": "fw",
        "schema": "fw",
        "source": ROOT / "backend" / "services" / "fw_kpi" / "fw_db.sqlite",
    },
    {
        "name": "eflow",
        "schema": "eflow",
        "source": ROOT / "data" / "eflow" / "eflow.sqlite3",
    },
    {
        "name": "ran_ume_ro",
        "schema": "ran_ume_ro",
        "source": ROOT / "data" / "ran_ume" / "ran_kpi_daily.sqlite3",
    },
]

# 2026-08-07 盘点行数（对账基准；源/目标行数须一致，与盘点不符仅告警）
EXPECTED_ROWS = {
    ("lte_pl", "packet_loss_data"): 750371,
    ("lte_pl", "pl_meta"): 5,
    ("lte_pl", "site_pl_summary"): 670,
    ("fw", "device_whole_throughput"): 42580,
    ("eflow", "eflow_cr"): 205,
    ("eflow", "eflow_pm"): 1632,
    ("eflow", "eflow_tt"): 28455,
    ("eflow", "eflow_wo"): 10000,
    ("eflow", "history_alarm"): 165,
    ("eflow", "person"): 133,
    ("eflow", "realtime_alarm"): 56,
    ("eflow", "site"): 808,
    ("ran_ume_ro", "2G_OLIB_Network_KPIs"): 768,
    ("ran_ume_ro", "3G_OLIB_Network_KPIs"): 480,
    ("ran_ume_ro", "FDD_OLIB_Network_KPIs"): 576,
    ("ran_ume_ro", "TDD_OLIB_Network_KPIs"): 480,
}

# 75 万行大表：分块读 chunksize<=2万 + executemany 批写
TABLE_BATCH_SIZE = {"packet_loss_data": 20000}


def _order_by_pg_nulls_first(cols):
    """PG 侧 ORDER BY：TEXT 加 COLLATE "C" 对齐 SQLite 字节序，全列 NULLS FIRST
    对齐 SQLite（SQLite ASC 时 NULL 视为最小值排最前，PG 默认 NULLS LAST，
    不一致会导致含 NULL 表的全行哈希对账假阳性）。"""
    parts = []
    for c in cols:
        col = tl.pg_quote(c["name"])
        if tl.map_pg_type(c["type"]) == "TEXT":
            col += ' COLLATE "C"'
        parts.append(col + " NULLS FIRST")
    return " ORDER BY " + ", ".join(parts)


def verify_table_nf(sqlite_path, pg_conn, schema, table, batch_size):
    """单表对账（NULLS FIRST 版）：源/目标行数 + 全行流式 MD5。"""
    src = tl.open_sqlite(sqlite_path)
    try:
        cols = tl.sqlite_table_info(src, table)
        select_sql = tl._sqlite_select_sql(table, cols) + tl._order_by_clause(cols, for_pg=False)
        src_count = src.execute(f"SELECT COUNT(*) FROM {tl.pg_quote(table)}").fetchone()[0]
        dst_count = tl.pg_count(pg_conn, schema, table)
        src_hash = tl._hash_select(src, select_sql, batch_size)
        dst_sql = (
            f"SELECT {', '.join(tl.pg_quote(c['name']) for c in cols)} "
            f"FROM {tl.pg_quote(schema)}.{tl.pg_quote(table)}"
            f"{_order_by_pg_nulls_first(cols)}"
        )
        dst_hash = tl._hash_select(pg_conn, dst_sql, batch_size)
        return {
            "schema": schema,
            "table": table,
            "src_rows": src_count,
            "pg_rows": dst_count,
            "src_md5": src_hash,
            "pg_md5": dst_hash,
            "ok": src_count == dst_count and src_hash == dst_hash,
        }
    finally:
        src.close()


def _mask_url(url):
    """日志/报告里隐藏密码。"""
    if "@" in url:
        scheme, rest = url.split("://", 1)
        host = rest.rsplit("@", 1)[-1]
        return f"{scheme}://***@{host}"
    return url


def sha256_file(path, chunk=8 * 1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def backup_lane_sources(paths, backup_root):
    """R0 备份：>=300MB 用硬链接（注明体积），其余文件级拷贝（含 -wal/-shm）。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = Path(backup_root) / f"phase5_wave2_{ts}"
    bdir.mkdir(parents=True, exist_ok=True)
    entries = []
    for p in paths:
        src = Path(p)
        if not src.exists():
            raise SystemExit(f"R0 备份失败：源文件不存在 {src}")
        size = src.stat().st_size
        dest = bdir / src.name
        if size >= HARDLINK_MIN_BYTES:
            try:
                os.link(src, dest)
                mode = "hardlink"
            except OSError:
                shutil.copy2(src, dest)
                mode = "copy(hardlink-fallback)"
            logger.info(
                "R0 backup (hardlink, %d MB): %s -> %s", size // (1024 * 1024), src, dest
            )
        else:
            shutil.copy2(src, dest)
            mode = "copy"
        entries.append({"file": str(src), "backup": str(dest), "mode": mode, "bytes": size})
        for suffix in ("-wal", "-shm"):
            side = Path(str(src) + suffix)
            if side.exists():
                shutil.copy2(side, bdir / side.name)
                entries.append(
                    {
                        "file": str(side),
                        "backup": str(bdir / side.name),
                        "mode": "copy",
                        "bytes": side.stat().st_size,
                    }
                )
    return bdir, entries


def main(argv=None):
    parser = argparse.ArgumentParser(description="Phase 5 Wave2 车道 B 迁移")
    parser.add_argument("--only", nargs="*", choices=[l["name"] for l in LANES],
                        help="migrate only these lanes (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="read-only inspect, no PG write")
    parser.add_argument("--skip-backup", action="store_true",
                        help="skip R0 sqlite file backup (not recommended)")
    parser.add_argument("--skip-verify", action="store_true",
                        help="skip row-count/MD5 verification")
    parser.add_argument("--verify-only", action="store_true",
                        help="only run verification against already-migrated PG data")
    parser.add_argument("--batch-size", type=int, default=tl.DEFAULT_BATCH_SIZE,
                        help="rows per batch (default 5000; packet_loss_data 固定 20000)")
    parser.add_argument("--method", choices=["executemany", "pandas"], default="executemany",
                        help="copy method (executemany default, or pandas)")
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_ROOT),
                        help="backup root (default <project>/backup)")
    parser.add_argument("--report-path", default=None,
                        help="write JSON report to this path (default: backup dir report.json)")
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    logger.info("开始时间: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    names = args.only or [l["name"] for l in LANES]
    chosen = [l for l in LANES if l["name"] in names]
    if not chosen:
        raise SystemExit("没有可迁移的域（--only 过滤后为空）")
    for lane in chosen:
        if lane["schema"] not in ALLOWED_SCHEMAS:
            raise SystemExit(f"红线：禁止写 schema {lane['schema']}（白名单 {sorted(ALLOWED_SCHEMAS)}）")

    tl.load_env(ROOT / "backend" / ".env")
    pg_url = tl.get_pg_url()
    if not pg_url:
        raise SystemExit("未找到 DATABASE_URL（环境变量或 backend/.env）")

    if args.dry_run:
        for lane in chosen:
            print(f"==== {lane['name']} -> PG schema {lane['schema']}  source: {lane['source']}")
            for t in tl.inspect_source(lane["source"]):
                print(
                    f"  {t['table']}  rows={t['rows']}  "
                    f"cols={len(t['columns'])}  types={t['pg_types'][:6]}..."
                )
        print(f"耗时 {time.perf_counter() - t0:.1f} 秒（dry-run）")
        return

    # R0 前置备份 + 迁移前 SHA256 基线
    if args.verify_only:
        args.skip_backup = True
    sha_before = {}
    for lane in chosen:
        sha_before[lane["name"]] = sha256_file(lane["source"])
    if not args.skip_backup:
        backup_dir, backup_entries = backup_lane_sources(
            [l["source"] for l in chosen], args.backup_dir
        )
        logger.info("R0 backup done: %s (%d files)", backup_dir, len(backup_entries))
    else:
        backup_dir, backup_entries = None, []

    import psycopg2

    conn = psycopg2.connect(pg_url, connect_timeout=15)
    engine = None
    try:
        if args.method == "pandas":
            from sqlalchemy import create_engine

            engine = create_engine(pg_url)

        report = {
            "task": "phase5_wave2_lane_b",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "pg": _mask_url(pg_url),
            "backup_dir": str(backup_dir) if backup_dir else None,
            "backup_entries": backup_entries,
            "sha256_before": sha_before,
            "batch_size": args.batch_size,
            "method": args.method,
            "lanes": [],
        }
        all_ok = True
        row_pairs = []

        for lane in chosen:
            schema = lane["schema"]
            src = lane["source"]
            tables = tl.inspect_source(src)
            lane_report = {
                "lane": lane["name"],
                "schema": schema,
                "source": str(src),
                "tables": [],
            }
            if not args.verify_only:
                tl.ensure_schema(conn, schema)
                logger.info("[%s] schema=%s source=%s", lane["name"], schema, src)
                for t in tables:
                    table = t["table"]
                    batch = TABLE_BATCH_SIZE.get(table, args.batch_size)
                    expected = EXPECTED_ROWS.get((schema, table))
                    if expected is not None and expected != t["rows"]:
                        logger.warning(
                            "[%s] %s 源行数 %d 与盘点 %d 不符（数据可能有更新，继续搬运）",
                            lane["name"], table, t["rows"], expected,
                        )
                    logger.info("[%s] copying %s (%d rows, batch=%d)", lane["name"], table, t["rows"], batch)
                    copied_rows = tl.copy_table(
                        src,
                        conn,
                        schema,
                        table,
                        batch_size=batch,
                        method=args.method,
                        engine=engine,
                        progress=lambda n, name=table, ln=lane["name"]: logger.info(
                            "[%s] %s copied %d rows", ln, name, n
                        ),
                    )
                    lane_report["tables"].append(
                        {
                            "table": table,
                            "src_rows": t["rows"],
                            "copied": copied_rows,
                            "expected_inventory": expected,
                        }
                    )
                    logger.info("[%s] %s done: %d rows", lane["name"], table, copied_rows)

            if not args.skip_verify:
                logger.info("[%s] verifying (NULLS FIRST)", lane["name"])
                results = [
                    verify_table_nf(src, conn, schema, t["table"], batch_size=args.batch_size)
                    for t in tables
                ]
                lane_report["verify"] = results
                for r in results:
                    status = "OK" if r["ok"] else "MISMATCH"
                    logger.info(
                        "[%s] %-48s %s  src=%s pg=%s md5=%s",
                        lane["name"], r["table"], status, r["src_rows"], r["pg_rows"],
                        "MATCH" if r["ok"] else "DIFF",
                    )
                    row_pairs.append(
                        {"schema": schema, "table": r["table"],
                         "src_rows": r["src_rows"], "pg_rows": r["pg_rows"], "ok": r["ok"]}
                    )
                    all_ok = all_ok and r["ok"]
            report["lanes"].append(lane_report)

        # 迁移后 SHA256：证明源 sqlite 未被改动
        sha_after = {lane["name"]: sha256_file(lane["source"]) for lane in chosen}
        sha_ok = all(sha_before[n] == sha_after[n] for n in sha_before)
        report["sha256_after"] = sha_after
        report["sha256_unchanged"] = sha_ok
        if not sha_ok:
            logger.error("源文件 SHA256 前后不一致！")
            all_ok = False

        report["elapsed_seconds"] = round(time.perf_counter() - t0, 1)
        report["row_pairs"] = row_pairs

        if args.report_path:
            report_path = Path(args.report_path)
        elif backup_dir:
            report_path = backup_dir / "report.json"
        else:
            report_path = None
        if report_path:
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

    elapsed = time.perf_counter() - t0
    logger.info("结束时间: %s，总耗时 %.1f 秒", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), elapsed)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    main()
