#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_new_group_history.py — 回补远程 ran_kpi_daily.sqlite3 新区域 Group 历史数据

背景：
    远程库 ran_kpi_daily.sqlite3 中新命名 Group（2G_NW / *_FME_Region-*）
    仅有 network_kpi_sync 2026-07-28 起的 14 天数据，FineBI 曲线只有几天。
    本地 d:\\01_RPA\\Task\\RAN\\ran_kpi_daily.sqlite3（旧采集库）存有同套新命名
    2025-12-01 ~ 2026-07-23 共 235 天历史，列结构与远程完全一致，
    因此无需重查 UME，直接把历史 upsert 到远程库即可。

处理逻辑（每张表）：
    1. 只读打开本地旧库，读取全部行
    2. 归一化 Begin Time / End Time 为空格格式 "YYYY-MM-DD HH:MM:SS"
       （本地库混有 ISO 格式 "2026-07-23T00:00:00+00:00"）
    3. 只回补远程缺失段：Begin Time 日期 <= CUTOFF_DATE（默认 2026-07-27）
    4. DbWriterClient upsert（pk=[Begin Time, Group]）写入远程库，
       按 BATCH_SIZE 分批，单批失败不影响其他批次

用法：
    python backfill_new_group_history.py            # 正式回补
    python backfill_new_group_history.py --dry-run  # 只统计不写入
"""
import sys
import os
import time
import sqlite3

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.services.db_writer_client import DbWriterClient
except ImportError:
    from db_writer_client import DbWriterClient

SOURCE_DB = r"d:\01_RPA\Task\RAN\ran_kpi_daily.sqlite3"
TARGET_DB = "ran_kpi_daily.sqlite3"
TABLES = ["2G_OLIB_Network_KPIs", "3G_OLIB_Network_KPIs",
          "FDD_OLIB_Network_KPIs", "TDD_OLIB_Network_KPIs"]
PK_COLUMNS = ["Begin Time", "Group"]
CUTOFF_DATE = "2026-07-27"   # 远程新命名自 07-28 起已有数据，只补之前的历史
BATCH_SIZE = 1000


def _norm_dt(v):
    """归一化时间字符串：去 T、去时区后缀 → 'YYYY-MM-DD HH:MM:SS'。"""
    if not v:
        return v
    s = str(v)
    if "T" in s:
        date_part, _, rest = s.partition("T")
        # 去 +00:00 / -HH:MM / Z 时区后缀
        for sep in ("+", "Z"):
            if sep in rest:
                rest = rest.split(sep, 1)[0]
        if "-" in rest[2:]:  # 负时区偏移
            rest = rest[:rest.index("-", 2)]
        s = f"{date_part} {rest}" if rest else date_part
    return s


def main():
    dry_run = "--dry-run" in sys.argv
    t0 = time.time()
    print(f"[Backfill] 开始 @ {time.strftime('%Y-%m-%d %H:%M:%S')}"
          f"{'（dry-run 只统计）' if dry_run else ''}")
    print("=" * 70)

    if not os.path.exists(SOURCE_DB):
        print(f"[ERROR] 源库不存在: {SOURCE_DB}")
        return 1

    client = None if dry_run else DbWriterClient()
    conn = sqlite3.connect(f"file:{SOURCE_DB}?mode=ro", uri=True)
    cur = conn.cursor()
    total_sent = total_skipped = 0
    failed_tables = []

    for table in TABLES:
        cols = [c[1] for c in cur.execute(f'PRAGMA table_info("{table}")')]
        bt_i = cols.index("Begin Time")
        et_i = cols.index("End Time") if "End Time" in cols else None
        sel = f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{table}"'
        rows = cur.execute(sel).fetchall()

        # 向量化清洗：list 推导一次完成归一化 + 窗口过滤
        clean = []
        for r in rows:
            r = list(r)
            r[bt_i] = _norm_dt(r[bt_i])
            if et_i is not None:
                r[et_i] = _norm_dt(r[et_i])
            if r[bt_i] and str(r[bt_i])[:10] <= CUTOFF_DATE:
                clean.append(r)
        skipped = len(rows) - len(clean)
        print(f"[{table}] 源 {len(rows)} 行，回补窗口内 {len(clean)} 行"
              f"（跳过 {skipped} 行晚于 {CUTOFF_DATE}）")

        if dry_run or not clean:
            total_sent += len(clean)
            continue

        ok_rows = 0
        for i in range(0, len(clean), BATCH_SIZE):
            batch = clean[i:i + BATCH_SIZE]
            try:
                res = client.write_data(db=TARGET_DB, table=table, columns=cols,
                                        rows=batch, mode="upsert",
                                        pk_columns=PK_COLUMNS, table_type="Group")
                if res.get("success"):
                    ok_rows += len(batch)
                else:
                    failed_tables.append(f"{table} batch@{i}: {res}")
                    print(f"  [FAIL] 批次 {i}-{i + len(batch)}: {res}")
            except Exception as e:
                failed_tables.append(f"{table} batch@{i}: {e}")
                print(f"  [FAIL] 批次 {i}-{i + len(batch)}: {e}")
        print(f"  写入成功 {ok_rows}/{len(clean)} 行")
        total_sent += ok_rows
        total_skipped += skipped

    conn.close()
    elapsed = time.time() - t0
    print("=" * 70)
    print(f"[Backfill] 完成：{'待写入' if dry_run else '已写入'} {total_sent} 行，"
          f"跳过 {total_skipped} 行，失败表 {len(failed_tables)} 张，耗时 {elapsed:.2f}s")
    if failed_tables:
        print("[Backfill] 失败明细:")
        for f in failed_tables:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
