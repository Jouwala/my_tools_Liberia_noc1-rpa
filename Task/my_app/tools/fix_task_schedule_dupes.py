# -*- coding: utf-8 -*-
"""修复 SQLite task_schedule_config 缺主键导致的重复行（2026-10-21）。

## 现象

`task_schedule_config` 里 73 个任务共 146 行 —— 每个任务_id 平均 2 行。读
`WHERE task_id=?` 命中哪一行取决于插入顺序，于是**同一个任务的 enabled /
manually_stopped 读出来是随机的**：用户手动关掉的任务，主开关下一次就把
它打开（用户 2026-10-20 报告的原始现象）。

## 根因

`backend/services/task_runner.py::_save_schedule_config` 用
`dialect_helpers.upsert()`，SQLite 分支是 `INSERT OR REPLACE`
（`backend/dialect_helpers.py:126`）。`INSERT OR REPLACE` 依赖
**唯一约束**决定替换目标；表上没有约束时它**不报错**，而是直接追加新行。

生产 SQLite 的实际 DDL 与 alembic `0001_baseline.py:58-64` 不一致 ——
后者建表时带了 `PrimaryKeyConstraint('task_id')`，生产库里这行 DDL 是：

    CREATE TABLE "task_schedule_config" ("task_id" TEXT, "cron" TEXT,
        "enabled" INTEGER, "updated_at" TEXT, "manually_stopped" INTEGER)
    indexes: []          ← 无 PK、无 UNIQUE

PG 侧主键完好（`task_schedule_config_pkey PRIMARY KEY (task_id)`，73 行），
所以只有 SQLite 在漂移。

⚠️ **PK 何时丢的已无从追溯**（`updated_at` 与 alembic 版本都不足以定位），
本脚本只负责把现状修回一致，不追溯历史。

## 保留哪一行

按 `updated_at` **取最新**的一行。理由：这一列的语义就是「这条配置最后一次
被写入的时间」，最新行必然是最近一次用户/主开关操作的结果；旧行是
`INSERT OR REPLACE` 失效后遗留的化石。若某个 task_id 的各行 `updated_at`
完全相同（同一秒内多次写入），再按 `rowid` 取最大兜底。

⚠️ 合并时 `cron` / `enabled` / `manually_stopped` **一律取那一行的值**，
不做字段级"择优" —— 混搭不同时间点的字段会造出从未存在过的组合状态，
比保留一条完整的真实状态更危险。

## 用法

    python tools/fix_task_schedule_dupes.py --check
        # 只报告，不写库

    python tools tools/fix_task_schedule_dupes.py --apply
        # 去重 + 建唯一索引

## 安全性

* 默认 dry-run，必须显式 `--apply` 才写；
* 写库前自动备份到 `db/app.db.bak_dedup_<时间戳>`；
* **不重建表**：用 `DELETE` 删多余行 + `CREATE UNIQUE INDEX` 补约束，
  全程原地操作，表名/列名/其他表的引用都不受影响；
* 事务内执行，失败自动回滚；
* 幂等：重复执行不会二次删除（已无重复时直接跳过建索引前的清理）。

⚠️ **跑之前请确保没有正在写这张表的进程**：backend / worker 都在运行时
去重，可能与并发的 `INSERT OR REPLACE` 撞上。建议先停 worker 再跑。
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "db" / "app.db"
TABLE = "task_schedule_config"
UNIQUE_INDEX = "ux_task_schedule_config_task_id"


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH), timeout=60)
    con.execute("PRAGMA busy_timeout = 60000")
    return con


def backup() -> Path:
    """备份整库（1.5G，复制需要十几秒；失败则中止，不允许无备份动手）。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = DB_PATH.parent / f"app.db.bak_dedup_{ts}"
    print(f"备份整库 → {dst.name}（约 {DB_PATH.stat().st_size / 1e9:.2f} GB，稍等）...")
    shutil.copy2(str(DB_PATH), str(dst))
    print(f"  完成：{dst}")
    return dst


def report(con: sqlite3.Connection) -> tuple:
    """返回 (总行数, 去重后行数, 重复 task_id 数)。"""
    total = con.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    distinct = con.execute(f"SELECT COUNT(DISTINCT task_id) FROM {TABLE}").fetchone()[0]
    dups = con.execute(
        f"SELECT COUNT(*) FROM (SELECT task_id FROM {TABLE} "
        f"GROUP BY task_id HAVING COUNT(*) > 1)").fetchone()[0]
    return total, distinct, dups


def has_unique_index(con: sqlite3.Connection) -> bool:
    rows = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=?",
        (TABLE,)).fetchall()
    return any(r[0] and "UNIQUE" in r[0].upper() for r in rows)


def preview(con: sqlite3.Connection, limit: int = 15) -> None:
    """打印将被删除的行（保留 updated_at 最新的一行）。"""
    print("\n--- 计划删除的行（每个 task_id 保留 updated_at 最新的一条）---")
    sql = f"""
        SELECT s.rowid, s.task_id, s.cron, s.enabled, s.manually_stopped, s.updated_at
        FROM {TABLE} s
        JOIN (
            SELECT task_id, MAX(updated_at) AS mx, MAX(rowid) AS mx_rid
            FROM {TABLE} GROUP BY task_id
        ) k ON s.task_id = k.task_id
        WHERE s.updated_at < k.mx
           OR (s.updated_at = k.mx AND s.rowid < k.mx_rid)
        ORDER BY s.task_id, s.updated_at
    """
    rows = con.execute(sql).fetchall()
    if not rows:
        print("  （无重复行，无需清理）")
        return
    print(f"  共 {len(rows)} 行待删除")
    for r in rows[:limit]:
        print(f"    rowid={r[0]:<5} {r[1]:<26} cron={r[2]!r:<14} enabled={r[3]} "
              f"manually_stopped={r[4]} at={r[5]}")
    if len(rows) > limit:
        print(f"    ... 另有 {len(rows) - limit} 行")


def dedup(con: sqlite3.Connection) -> int:
    """删除每个 task_id 的陈旧行，只留 updated_at 最新（rowid 最大兜底）的一条。"""
    sql = f"""
        DELETE FROM {TABLE} WHERE rowid IN (
            SELECT s.rowid FROM {TABLE} s
            JOIN (
                SELECT task_id, MAX(updated_at) AS mx, MAX(rowid) AS mx_rid
                FROM {TABLE} GROUP BY task_id
            ) k ON s.task_id = k.task_id
            WHERE s.updated_at < k.mx
               OR (s.updated_at = k.mx AND s.rowid < k.mx_rid)
        )
    """
    cur = con.execute(sql)
    return cur.rowcount


def ensure_unique_index(con: sqlite3.Connection) -> None:
    """补唯一索引：让 INSERT OR REPLACE 重新具备「替换」语义（根因修复）。"""
    if has_unique_index(con):
        print(f"  唯一索引已存在，跳过")
        return
    # 必须先清理重复行，否则 CREATE UNIQUE INDEX 会因冲突失败
    con.execute(
        f"CREATE UNIQUE INDEX {UNIQUE_INDEX} ON {TABLE}(task_id)")
    print(f"  已建唯一索引 {UNIQUE_INDEX}")


def verify(con: sqlite3.Connection) -> bool:
    total, distinct, dups = report(con)
    print("\n--- 校验 ---")
    print(f"  总行数={total}  去重后={distinct}  仍有重复的 task_id={dups}")
    print(f"  唯一索引={'有' if has_unique_index(con) else '无'}")
    ok = total == distinct and dups == 0 and has_unique_index(con)
    print(f"  结果：{'✅ 一致' if ok else '❌ 仍不一致'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="修复 task_schedule_config 重复行并补唯一约束")
    ap.add_argument("--apply", action="store_true", help="真正写库（缺省只读检查）")
    ap.add_argument("--check", action="store_true", help="只报告")
    args = ap.parse_args()

    con = _connect()
    try:
        print(f"库文件：{DB_PATH}")
        total, distinct, dups = report(con)
        print(f"当前：总行数={total}  distinct task_id={distinct}  重复 task_id={dups}")
        print(f"唯一索引：{'有' if has_unique_index(con) else '无 ⚠️（INSERT OR REPLACE 会追加新行）'}")

        if not args.apply or args.check:
            preview(con)
            print("\n[dry-run] 未写库。确认无误后加 --apply 执行（会自动备份整库）。")
            return 0

        if dups == 0 and has_unique_index(con):
            print("\n无需处理：已无重复行且唯一索引存在。")
            return 0

        backup()
        print("\n--- 开始去重（事务内）---")
        try:
            removed = dedup(con)
            print(f"  删除陈旧重复行：{removed} 行")
            ensure_unique_index(con)
            con.commit()
        except Exception:
            con.rollback()
            print("  ❌ 失败，已回滚")
            raise

        verify(con)
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())