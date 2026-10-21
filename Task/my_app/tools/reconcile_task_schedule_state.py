# -*- coding: utf-8 -*-
"""把 task_schedule_config 的启停状态对齐并**同时写回 SQLite 与 PG**（2026-10-21）。

## 为什么需要这个脚本

`_save_schedule_config` 自 2026-10-21 起双写两侧，但**存量数据不是**：
`pg_to_sqlite_sync` 按 PG 的陈旧值把 SQLite 整表覆盖，于是两侧一起停在
2026-10-20T12:03 的「主开关关闭」状态（73 行里只有 1 行 enabled）。后果分两层：

* 运行中的进程每次执行前重读库 → 24 个任务按「任务 xxx 已禁用」被跳过（16:15 起实测）；
* 一旦重启，`schedule_all_tasks` 照库里的旧值只调度 1 个任务。

本脚本把两侧一次性写回**目标状态**，之后双写负责维持。

## 目标状态怎么定的

不写死任务名，从表自身的 `manually_stopped` 推导 —— 语义就是「用户手动关过的保持停用，
其余一律受主开关管辖、当前主开关为 ON」：

    enabled = 0  若 manually_stopped = 1
    enabled = 1  其余

`cron` 沿用各表现有值（缺行时用另一侧的同名行兜底），本脚本不改 cron。

## 附带做的事

SQLite 侧先按 `updated_at` 最新去重、再补 `ux_task_schedule_config_task_id` 唯一索引 ——
和 `tools/fix_task_schedule_dupes.py` 同一套判据。缺唯一索引时 `INSERT OR REPLACE` 会
**追加重复行**，写进去的状态读不出来（这正是本次事故的第二个症状）。

## 用法

    python tools/reconcile_task_schedule_state.py            # 只读：报告两侧差异与将写入的值
    python tools/reconcile_task_schedule_state.py --apply     # 写两侧（SQLite 先整库备份）

## 安全性

* 默认 dry-run，必须显式 `--apply`；
* `--apply` 前把 `db/app.db` 复制为 `db/app.db.bak_tscfix_<时间戳>`（PG 侧无备份，
  回退靠本脚本打印的改动前后对照，或从 SQLite 备份反推）；
* 每个存储各自一个事务，失败回滚该存储、不影响另一个；
* 幂等：两侧已一致时不改写任何行（`updated_at` 也不动）。

⚠️ **执行时机**：请在 `SKIP_TABLES` 改动生效之后再跑（即重启跑 pg_to_sqlite_sync 的
worker 组）。否则下一次 :45 同步又会用 PG 旧值覆盖 —— 本脚本写完 PG 之后同步覆盖的
只是同样的值，不会回退，但同步的 DROP+CREATE 会再次抹掉刚补上的唯一索引。
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg2

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env", override=False)
except Exception:
    pass

TABLE = "task_schedule_config"
UNIQUE_INDEX = "ux_task_schedule_config_task_id"
COLS = ("task_id", "cron", "enabled", "manually_stopped", "updated_at")


def _sqlite_path() -> Path:
    return ROOT / "db" / "app.db"


def _read_sqlite(con: sqlite3.Connection) -> dict:
    rows = con.execute(
        f"SELECT {', '.join(COLS)} FROM {TABLE}"
    ).fetchall()
    return {r[0]: {"task_id": r[0], "cron": r[1], "enabled": int(r[2] or 0),
                   "manually_stopped": int(r[3] or 0), "updated_at": r[4]}
            for r in rows}


def _read_pg(cur) -> dict:
    cur.execute(f"SELECT {', '.join(COLS)} FROM app.{TABLE}")
    out = {}
    for r in cur.fetchall():
        out[r[0]] = {"task_id": r[0], "cron": r[1], "enabled": int(r[2] or 0),
                     "manually_stopped": int(r[3] or 0), "updated_at": r[4]}
    return out


def _has_unique_index(con: sqlite3.Connection) -> bool:
    for name, sql in con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=?", (TABLE,)
    ).fetchall():
        if sql and "UNIQUE" in sql.upper() and "task_id" in sql.lower():
            return True
    return False


def _dedup(con: sqlite3.Connection) -> int:
    """每个 task_id 只留 updated_at 最新（同秒按 rowid 最大兜底）的一行。"""
    cur = con.execute(f"""
        DELETE FROM {TABLE} WHERE rowid IN (
            SELECT s.rowid FROM {TABLE} s
            JOIN (
                SELECT task_id, MAX(updated_at) AS mx, MAX(rowid) AS mx_rid
                FROM {TABLE} GROUP BY task_id
            ) k ON s.task_id = k.task_id
            WHERE s.updated_at < k.mx
               OR (s.updated_at = k.mx AND s.rowid < k.mx_rid)
        )
    """)
    return cur.rowcount


def _target(row: dict) -> dict:
    enabled = 0 if row["manually_stopped"] else 1
    return {"task_id": row["task_id"], "cron": row["cron"], "enabled": enabled,
            "manually_stopped": row["manually_stopped"], "updated_at": row["updated_at"]}


def _plan(sqlite_rows: dict, pg_rows: dict, now: str):
    """返回 (计划写入的行, 两侧各自的改动数)。只在「任一侧与目标不一致」时才写。"""
    plan = []
    changed_sqlite = changed_pg = 0
    missing_sqlite = missing_pg = 0
    for tid in sorted(set(sqlite_rows) | set(pg_rows)):
        base = sqlite_rows.get(tid) or pg_rows.get(tid)
        want = dict(_target(base))
        want["updated_at"] = now          # 有改动才刷新时间戳，全一致时保留原值
        s, p = sqlite_rows.get(tid), pg_rows.get(tid)
        s_diff = s is None or (s["enabled"], s["manually_stopped"], s["cron"]) != (
            want["enabled"], want["manually_stopped"], want["cron"])
        p_diff = p is None or (p["enabled"], p["manually_stopped"], p["cron"]) != (
            want["enabled"], want["manually_stopped"], want["cron"])
        if s is None:
            missing_sqlite += 1
        if p is None:
            missing_pg += 1
        if s_diff:
            changed_sqlite += 1
        if p_diff:
            changed_pg += 1
        if not (s_diff or p_diff):
            want["updated_at"] = (s or p)["updated_at"]
            continue
        plan.append(want)
    return plan, changed_sqlite, changed_pg, missing_sqlite, missing_pg


def main() -> int:
    ap = argparse.ArgumentParser(description="对齐并双写 task_schedule_config 的启停状态")
    ap.add_argument("--apply", action="store_true", help="真正写两侧（缺省只读检查）")
    args = ap.parse_args()

    now = datetime.now().isoformat()
    db = _sqlite_path()
    print(f"SQLite：{db}")

    con = sqlite3.connect(str(db), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    sqlite_rows = _read_sqlite(con)
    print(f"  行数={len(sqlite_rows)}  enabled=1 有 {sum(r['enabled'] for r in sqlite_rows.values())}"
          f"  manually_stopped=1 有 {sum(r['manually_stopped'] for r in sqlite_rows.values())}"
          f"  唯一索引={'有' if _has_unique_index(con) else '无 ⚠️'}")

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL 未设置，无法连 PG")
        return 1
    pg = psycopg2.connect(url, connect_timeout=10)
    pgcur = pg.cursor()
    pg_rows = _read_pg(pgcur)
    print(f"PG：行数={len(pg_rows)}  enabled=1 有 {sum(r['enabled'] for r in pg_rows.values())}"
          f"  manually_stopped=1 有 {sum(r['manually_stopped'] for r in pg_rows.values())}")

    plan, ch_s, ch_p, miss_s, miss_p = _plan(sqlite_rows, pg_rows, now)
    print(f"\n目标（manually_stopped=1 停用，其余启用）：共 {len(set(sqlite_rows) | set(pg_rows))} 个任务")
    print(f"  需改动：SQLite {ch_s} 行 / PG {ch_p} 行；缺行：SQLite {miss_s} / PG {miss_p}")
    for tid in sorted(r["task_id"] for r in plan):
        s, p = sqlite_rows.get(tid), pg_rows.get(tid)
        want = _target(s or p)
        if want["enabled"]:
            print(f"    {tid:<28} enabled: SQLite={s and s['enabled']} PG={p and p['enabled']} → 1")
        else:
            print(f"    {tid:<28} 保持停用（manually_stopped）")

    if not plan:
        print("\n两侧已与目标一致，无需写入。")
        con.close()
        pg.close()
        return 0

    if not args.apply:
        print("\n[dry-run] 未写库。确认后加 --apply（SQLite 会先整库备份）。")
        con.close()
        pg.close()
        return 0

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    bak = db.with_name(f"{db.name}.bak_tscfix_{stamp}")
    con.close()
    shutil.copy2(db, bak)
    print(f"\n已备份整库 → {bak}")

    con = sqlite3.connect(str(db), timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    try:
        removed = _dedup(con)
        if not _has_unique_index(con):
            con.execute(f"CREATE UNIQUE INDEX {UNIQUE_INDEX} ON {TABLE}(task_id)")
        ph = ", ".join(["?"] * len(COLS))
        con.executemany(
            f"INSERT OR REPLACE INTO {TABLE} ({', '.join(COLS)}) VALUES ({ph})",
            [tuple(r[c] for c in COLS) for r in plan])
        con.commit()
        print(f"  SQLite：去重删除 {removed} 行，写入 {len(plan)} 行，唯一索引={'有' if _has_unique_index(con) else '无'}")
    except Exception:
        con.rollback()
        raise

    try:
        pgcur.executemany(
            f"INSERT INTO app.{TABLE} ({', '.join(COLS)}) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (task_id) DO UPDATE SET "
            "cron=EXCLUDED.cron, enabled=EXCLUDED.enabled, "
            "manually_stopped=EXCLUDED.manually_stopped, updated_at=EXCLUDED.updated_at",
            [tuple(r[c] for c in COLS) for r in plan])
        pg.commit()
        print(f"  PG：写入 {len(plan)} 行")
    except Exception:
        pg.rollback()
        raise

    print("\n--- 复核 ---")
    s2 = _read_sqlite(con)
    p2 = _read_pg(pgcur)
    for label, rows in (("SQLite", s2), ("PG", p2)):
        print(f"  {label}: 行数={len(rows)}  enabled=1 有 {sum(r['enabled'] for r in rows.values())}"
              f"  manually_stopped=1 有 {sum(r['manually_stopped'] for r in rows.values())}")
    same = {k: (v["enabled"], v["manually_stopped"], v["cron"]) for k, v in s2.items()} == \
           {k: (v["enabled"], v["manually_stopped"], v["cron"]) for k, v in p2.items()}
    print(f"  两侧启停/cron 完全一致：{'是' if same else '否 ⚠️'}")
    print(f"  SQLite 唯一索引：{'有' if _has_unique_index(con) else '无 ⚠️'}")
    con.close()
    pg.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
