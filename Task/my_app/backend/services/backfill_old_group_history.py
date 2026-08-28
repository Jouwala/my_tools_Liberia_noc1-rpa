#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backfill_old_group_history.py — 回补远程 ran_kpi_daily.sqlite3 旧命名 ZTE-OLR 系列 Group 历史

背景：
    远程库旧命名 Group（G_NW、*_ZTE-OLR-MS-Network、*_ZTE-OLR-Region，
    部署机手工导出流水线 05-08~07-27 写入）在 FineBI 与新命名区域并存。
    部署机 /01_RPA/LBR_Tools/KPI/RAN/ran_kpi_daily_2.sqlite3（已下载到
    d:\\01_RPA\\TMP\\ran_kpi_daily_2.sqlite3）存有 2025-07-26 ~ 2026-07-27
    一整年新旧两套命名历史，比远程旧命名现有起点 05-08 更早。

回补规则：
    - 旧命名组（G_NW 或含 ZTE-OLR）：日期 <= OLD_CUTOFF（2026-07-27，
      远程 07-28 起旧命名已无数据，全部为净增量）
    - 新命名组：仅日期 < NEW_CUTOFF（2025-12-01），把新命名历史向前
      延伸到 2025-07-26，不覆盖已有回补/任务数据

处理逻辑同 backfill_new_group_history.py：归一化时间格式（去 T/时区后缀）
→ DbWriterClient upsert（pk=[Begin Time, Group]）→ 1000 行/批。

用法：
    python backfill_old_group_history.py            # 正式回补
    python backfill_old_group_history.py --dry-run  # 只统计不写入
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

SOURCE_DB = r"d:\01_RPA\TMP\ran_kpi_daily_2.sqlite3"
TARGET_DB = "ran_kpi_daily.sqlite3"
TABLES = ["2G_OLIB_Network_KPIs", "3G_OLIB_Network_KPIs",
          "FDD_OLIB_Network_KPIs", "TDD_OLIB_Network_KPIs"]
PK_COLUMNS = ["Begin Time", "Group"]
OLD_CUTOFF = "2026-07-27"    # 旧命名组回补上限
NEW_CUTOFF = "2025-12-01"    # 新命名组仅补该日期之前（更早历史延伸）
BATCH_SIZE = 1000


def _is_old_naming(group) -> bool:
    """旧命名组：G_NW（NW 层）或含 ZTE-OLR（区域层）。"""
    g = str(group)
    return g == "G_NW" or "ZTE-OLR" in g


def _norm_dt(v):
    """归一化时间字符串：去 T、去时区后缀 → 'YYYY-MM-DD HH:MM:SS'。"""
    if not v:
        return v
    s = str(v)
    if "T" in s:
        date_part, _, rest = s.partition("T")
        for sep in ("+", "Z"):
            if sep in rest:
                rest = rest.split(sep, 1)[0]
        if len(rest) > 2 and "-" in rest[2:]:
            rest = rest[:rest.index("-", 2)]
        s = f"{date_part} {rest}" if rest else date_part
    return s


def main():
    dry_run = "--dry-run" in sys.argv
    t0 = time.time()
    print(f"[Backfill-Old] 开始 @ {time.strftime('%Y-%m-%d %H:%M:%S')}"
          f"{'（dry-run 只统计）' if dry_run else ''}")
    print("=" * 70)

    if not os.path.exists(SOURCE_DB):
        print(f"[ERROR] 源库不存在: {SOURCE_DB}")
        return 1

    client = None if dry_run else DbWriterClient()
    conn = sqlite3.connect(f"file:{SOURCE_DB}?mode=ro", uri=True)
    cur = conn.cursor()
    total_sent = total_skipped = 0
    failed = []

    for table in TABLES:
        cols = [c[1] for c in cur.execute(f'PRAGMA table_info("{table}")')]
        bt_i = cols.index("Begin Time")
        et_i = cols.index("End Time") if "End Time" in cols else None
        gr_i = cols.index("Group")
        sel = f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{table}"'
        rows = cur.execute(sel).fetchall()

        clean = []
        for r in rows:
            r = list(r)
            r[bt_i] = _norm_dt(r[bt_i])
            if et_i is not None:
                r[et_i] = _norm_dt(r[et_i])
            if not r[bt_i]:
                continue
            d = str(r[bt_i])[:10]
            if _is_old_naming(r[gr_i]):
                if d <= OLD_CUTOFF:
                    clean.append(r)
            else:
                if d < NEW_CUTOFF:
                    clean.append(r)
        skipped = len(rows) - len(clean)
        n_old = sum(1 for r in clean if _is_old_naming(r[gr_i]))
        print(f"[{table}] 源 {len(rows)} 行 → 回补 {len(clean)} 行"
              f"（旧命名 {n_old} / 新命名延伸 {len(clean) - n_old}，跳过 {skipped}）")

        if dry_run or not clean:
            total_sent += len(clean)
            total_skipped += skipped
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
                    failed.append(f"{table} batch@{i}: {res}")
                    print(f"  [FAIL] 批次 {i}-{i + len(batch)}: {res}")
            except Exception as e:
                failed.append(f"{table} batch@{i}: {e}")
                print(f"  [FAIL] 批次 {i}-{i + len(batch)}: {e}")
        print(f"  写入成功 {ok_rows}/{len(clean)} 行")
        total_sent += ok_rows
        total_skipped += skipped

    conn.close()
    elapsed = time.time() - t0
    print("=" * 70)
    print(f"[Backfill-Old] 完成：{'待写入' if dry_run else '已写入'} {total_sent} 行，"
          f"跳过 {total_skipped} 行，失败 {len(failed)} 批，耗时 {elapsed:.2f}s")
    for f in failed:
        print(f"  - {f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
