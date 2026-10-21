# -*- coding: utf-8 -*-
"""回填 task_schedule_config.manually_stopped（主开关「跳过手动停止」标记）。

背景（2026-10-20）
-----------------
`manually_stopped` 列由 alembic `0006_manual_stop_flag` 加入，语义是
「用户手动关过这个任务」——主开关**双向**都跳过标记为 1 的任务
（见 `backend/services/task_runner.py: toggle_all_tasks`）。

加列时 `DEFAULT 0`，所以**存量数据一律是 0**：那些在加列之前就被用户手动关掉
的任务，在库里同样是 `enabled=0 / manually_stopped=0`，看起来与「被主开关关掉的」
一模一样。主开关一旦打开，就会把它们**全部重新打开** —— 这正是要修的问题。

为什么不做成自动迁移
--------------------
「哪些任务是用户有意关掉的」**没有可靠信号可自动推断**：
  * `enabled=0` 既可能是手动关的，也可能是主开关批量关的；
  * `updated_at` 只说得出「什么时候变的」，说不出「谁变的、为什么」；
  * 豁免名单里的任务（`MASTER_SWITCH_EXEMPT_IDS`）本来就是设计性关闭，
    不算「用户手动关」。

因此改为**人工确认 + 一次性回填**：由业务侧列出确实要长期保持关闭的 task_id，
再用本脚本写入。脚本**幂等**、只改 `manually_stopped`、**不动** `enabled` 与 `cron`。

用法
----
    python tools/backfill_manual_stop_flag.py --check
        # 只看当前状态，不写库（改动前先跑这个确认名单）

    python tools/backfill_manual_stop_flag.py --apply whatsapp_send whatsapp_send_ext
        # 把列出的 task_id 置为「用户手动关过」（manually_stopped=1）

    python tools/backfill_manual_stop_flag.py --clear whatsapp_send
        # 反向：清掉标记（交还给主开关管辖）

安全
----
* 默认 dry-run，**必须显式加 `--apply` 才写库**；
* 写入只碰 `manually_stopped` 一列，`enabled` / `cron` / `updated_at` 不动；
* 强制走原生 `sqlite3.connect`（与 `task_runner._save_schedule_config` 一致）：
  `DB_MODE=pg` 时 `get_raw_connection` 的 upsert 语法不兼容，静默失败过一次。
* 任务不在 `task_schedule_config` 表里时会**插入**一行（沿用注册表里的默认 cron），
  不会因为「表里没这行」就静默跳过。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

from backend.database import DB_PATH  # noqa: E402
from backend.task_registry import TASK_SPECS  # noqa: E402

# task_id → 注册表里的默认定义（供「表中无此行」时取默认 cron / enabled）。
# 只读声明式清单，不触发任何懒加载 import（与 backend.task_registry 的懒加载约定一致）。
_SPEC_BY_ID = {spec["task_id"]: spec for spec in TASK_SPECS}

# 默认回填名单（2026-10-20 由业务侧确认）：
#   whatsapp_send        —— WhatsApp 消息发送（Playwright 通道）
#   whatsapp_send_ext    —— WhatsApp 消息发送（扩展）—— 同一批产物的另一条通道，
#                           业务上只保留一条；原为豁免任务，2026-10-20 移出豁免名单
#   sp_whatsapp_report   —— Comsumables&SpareParts Report Whatsapp
# 三个都已在库里是 enabled=0 / manually_stopped=0 或 1（见下），这里做幂等回填。
DEFAULT_TASK_IDS = [
    "whatsapp_send",
    "whatsapp_send_ext",
    "sp_whatsapp_report",
]


def _connect():
    """原生 SQLite 连接（不走 get_raw_connection，理由见模块 docstring）。"""
    import sqlite3
    return sqlite3.connect(str(DB_PATH), timeout=30)


def _ensure_column(conn) -> None:
    """确保 manually_stopped 列存在（老库可能还没跑过 0006 迁移）。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(task_schedule_config)")}
    if "manually_stopped" not in cols:
        conn.execute(
            "ALTER TABLE task_schedule_config "
            "ADD COLUMN manually_stopped INTEGER NOT NULL DEFAULT 0"
        )
        logging.info("manually_stopped 列不存在，已就地补齐（等同 0006 迁移）")


def show(conn, task_ids: list[str]) -> None:
    """打印这些 task_id 当前的 enabled / manually_stopped。"""
    for tid in task_ids:
        row = conn.execute(
            "SELECT enabled, manually_stopped, cron FROM task_schedule_config WHERE task_id = ?",
            (tid,),
        ).fetchone()
        if row is None:
            spec = _SPEC_BY_ID.get(tid) or {}
            print(f"  {tid:28s} <表中无此行>  注册表默认 cron={spec.get('default_cron')!r} "
                  f"enabled={spec.get('enabled', True)}")
            continue
        print(f"  {tid:28s} enabled={row[0]}  manually_stopped={row[1]}  cron={row[2]!r}")


def apply(conn, task_ids: list[str], value: int) -> int:
    """把 task_ids 的 manually_stopped 置为 value；只改这一列。"""
    from datetime import datetime

    changed = 0
    now = datetime.now().isoformat()
    for tid in task_ids:
        spec = _SPEC_BY_ID.get(tid) or {}
        cron = spec.get("default_cron") or "0 3 * * *"
        row = conn.execute(
            "SELECT enabled, manually_stopped FROM task_schedule_config WHERE task_id = ?",
            (tid,),
        ).fetchone()
        if row is None:
            # 表里没这行 → 插入。enabled 取注册表默认值，manually_stopped 按目标值。
            conn.execute(
                "INSERT INTO task_schedule_config "
                "(task_id, cron, enabled, manually_stopped, updated_at) VALUES (?,?,?,?,?)",
                (tid, cron, 1 if spec.get("enabled", True) else 0, value, now),
            )
            logging.info("插入新行 %s cron=%s manually_stopped=%s", tid, cron, value)
            changed += 1
            continue
        enabled, current = row
        if int(current) == value:
            logging.info("跳过 %s：manually_stopped 已是 %s", tid, value)
            continue
        conn.execute(
            "UPDATE task_schedule_config SET manually_stopped = ?, updated_at = ? WHERE task_id = ?",
            (value, now, tid),
        )
        logging.info("更新 %s：manually_stopped %s → %s（enabled 保持 %s 不变）",
                    tid, current, value, enabled)
        changed += 1
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 task_schedule_config.manually_stopped")
    parser.add_argument("task_ids", nargs="*", default=None,
                        help=f"task_id 列表（缺省用内置确认名单：{', '.join(DEFAULT_TASK_IDS)}）")
    parser.add_argument("--apply", action="store_true", help="真正写库（缺省只读）")
    parser.add_argument("--clear", action="store_true", help="清掉标记（与 --apply 搭配使用）")
    parser.add_argument("--check", action="store_true", help="只看状态（默认行为）")
    args = parser.parse_args()

    task_ids = args.task_ids or DEFAULT_TASK_IDS
    value = 0 if args.clear else 1
    write = args.apply and not args.check

    conn = _connect()
    try:
        _ensure_column(conn)
        conn.commit()

        print(f"库文件：{DB_PATH}")
        print(f"目标 task_id：{', '.join(task_ids)}")
        print(f"目标值：manually_stopped = {value}")
        print("--- 改动前状态 ---")
        show(conn, task_ids)

        if not write:
            print("\n[dry-run] 未写库。确认无误后加 --apply 执行。")
            return 0

        print("\n--- 执行写入 ---")
        changed = apply(conn, task_ids, value)
        conn.commit()

        print("--- 改动后状态 ---")
        show(conn, task_ids)
        print(f"\n共改动 {changed} 行（表里没有的按插入处理）。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
