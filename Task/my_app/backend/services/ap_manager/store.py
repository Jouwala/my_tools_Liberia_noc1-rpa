# -*- coding: utf-8 -*-
"""AP 模块存储层：建表、编号生成、行转换、状态机常量。

**为什么用「惰性建表」而不是 alembic 迁移**：
与 `routers/feedback.py` 的 `issue_reports` 一致 —— AP 是新增业务表，不涉及既有表
改造，惰性建表可以在「首次访问即建好」，不需要在生产机上单独跑一次迁移；同时
sqlite / pg 双模都能跑（生产是 pg，本地/回退是 sqlite）。

**时间口径**：与全项目一致，存 **naive 本地时间** 字符串 `YYYY-MM-DD HH:MM:SS`。
不要改成 UTC —— `task_execution_log`、`issue_reports` 等全是本地时间，AP 单独用
UTC 会让同一个页面里两个时间差 8 小时（`AP_Plan_Review.md` 第 4.5 条）。

**并发**：状态转换一律用乐观锁
``UPDATE ap_tasks SET status=? ... WHERE id=? AND status=?``，
受影响行数 = 0 即视为冲突。理由：sqlite 没有行锁，`SELECT ... FOR UPDATE`
在双模下无法统一（`dialect_helpers` 也没有行锁封装）。
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime

from backend.database import get_raw_connection
from backend.dialect_helpers import table_columns

logger = logging.getLogger("ap.store")

# ========== 状态机（方案第 3 节；值一律用下划线，不带空格） ==========
# 方案原文写作 `In Progress` / `Pending Review`，落库/拼 URL/做 i18n key 全是坑，
# 统一改成下划线，展示层再翻译。
DRAFT = "DRAFT"
ASSIGNED = "ASSIGNED"
ACKNOWLEDGED = "ACKNOWLEDGED"
IN_PROGRESS = "IN_PROGRESS"
PENDING_REVIEW = "PENDING_REVIEW"
COMPLETED = "COMPLETED"
REJECTED = "REJECTED"
CANCELLED = "CANCELLED"

STATUSES = (DRAFT, ASSIGNED, ACKNOWLEDGED, IN_PROGRESS,
            PENDING_REVIEW, COMPLETED, REJECTED, CANCELLED)
# 逾期只对"还没结束"的任务有意义
OPEN_STATUSES = (DRAFT, ASSIGNED, ACKNOWLEDGED, IN_PROGRESS, PENDING_REVIEW, REJECTED)

PRIORITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
CATEGORIES = ("SITE", "EQUIPMENT", "KPI", "NETWORK_OPT", "PROCESS", "OTHER")

# 状态转换白名单：动作 → (允许的当前状态, 目标状态)
TRANSITIONS = {
    "dispatch": ((DRAFT,), ASSIGNED),
    "accept": ((ASSIGNED,), ACKNOWLEDGED),
    "start": ((ACKNOWLEDGED, REJECTED), IN_PROGRESS),
    "progress": ((ASSIGNED, ACKNOWLEDGED, IN_PROGRESS, REJECTED), None),  # 不改状态
    "submit": ((IN_PROGRESS, ACKNOWLEDGED), PENDING_REVIEW),
    "approve": ((PENDING_REVIEW,), COMPLETED),
    "reject": ((PENDING_REVIEW,), REJECTED),
    "cancel": ((DRAFT, ASSIGNED, ACKNOWLEDGED, IN_PROGRESS, REJECTED), CANCELLED),
}

T_TASKS = "ap_tasks"
T_UPDATES = "ap_updates"
T_REVIEWS = "ap_reviews"
T_HISTORY = "ap_history"
T_PROFILE = "ap_user_profile"
T_ORG = "ap_org_people"


def _is_sqlite(conn) -> bool:
    return isinstance(conn, sqlite3.Connection)


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_ts(value) -> str | None:
    """把前端传来的时间归一成 `YYYY-MM-DD HH:MM:SS`。

    前端 DatePicker 可能给出 `2026-11-05T17:00:00Z` / `2026-11-05 17:00` /
    `2026-11-05`，统一裁成项目口径。无法识别时返回 None（由调用方决定是否必填）。
    """
    if value in (None, ""):
        return None
    s = str(value).strip().replace("T", " ")
    s = re.sub(r"(Z|[+-]\d{2}:?\d{2})$", "", s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19] if len(s) >= 19 else s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None


def row_to_dict(row) -> dict:
    """sqlite3.Row 与 _PsycopgRow 都支持 keys()，两者统一转 dict。"""
    if row is None:
        return {}
    return {k: row[k] for k in row.keys()}


# 需要按 `YYYY-MM-DD HH:MM:SS` 输出的时间列。
# PG 的 TIMESTAMP 读出来是 datetime（FastAPI 会序列化成带 `T` 的 ISO 串），
# 而 sqlite 读出来本来就是上面那个字符串 —— 不统一会让「前端展示的时间」和
# 「逾期比较用的时间」两套格式并存（`str(datetime)[:19]` 带 T，字符串比较会错）。
TS_FIELDS = ("due_at", "dispatched_at", "accepted_at", "submitted_at",
             "completed_at", "cancelled_at", "created_at", "updated_at")


def fmt_ts(value):
    """datetime / 字符串 → `YYYY-MM-DD HH:MM:SS`（None 原样返回）。"""
    if value is None or value == "":
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value).replace("T", " ")[:19]


def normalize_ts(task: dict) -> dict:
    """把一行 AP 的时间列统一成字符串（原地修改并返回）。"""
    for k in TS_FIELDS:
        if k in task:
            task[k] = fmt_ts(task[k])
    return task


# ========== 建表 ==========

def ensure_tables(conn=None) -> None:
    """幂等建表 + 索引。首次访问时调用，后续每次也是 O(1) 的 IF NOT EXISTS。"""
    own = conn is None
    conn = conn or get_raw_connection()
    try:
        if _is_sqlite(conn):
            ident = "INTEGER PRIMARY KEY AUTOINCREMENT"
            ts = "TEXT"
        else:
            ident = "INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
            ts = "TIMESTAMP"
        int_t = "INTEGER" if _is_sqlite(conn) else "INTEGER"

        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {T_TASKS} (
                id {ident},
                ap_no TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT,
                description TEXT,
                priority TEXT NOT NULL DEFAULT 'MEDIUM',
                status TEXT NOT NULL DEFAULT 'DRAFT',
                target_position TEXT,
                owner_username TEXT NOT NULL,
                reviewer_username TEXT,
                progress {int_t} NOT NULL DEFAULT 0,
                due_at {ts},
                notify_groups TEXT,
                notify_email TEXT,
                related_ticket_id TEXT,
                site_id TEXT,
                region TEXT,
                completion_note TEXT,
                reject_reason TEXT,
                attachments TEXT,
                created_by TEXT NOT NULL,
                created_at {ts} NOT NULL,
                updated_at {ts} NOT NULL,
                dispatched_at {ts},
                accepted_at {ts},
                submitted_at {ts},
                completed_at {ts},
                cancelled_at {ts}
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {T_UPDATES} (
                id {ident},
                ap_id {int_t} NOT NULL,
                username TEXT NOT NULL,
                progress {int_t},
                note TEXT,
                created_at {ts} NOT NULL
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {T_REVIEWS} (
                id {ident},
                ap_id {int_t} NOT NULL,
                reviewer_username TEXT NOT NULL,
                decision TEXT NOT NULL,
                comments TEXT,
                snapshot TEXT,
                created_at {ts} NOT NULL
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {T_HISTORY} (
                id {ident},
                ap_id {int_t} NOT NULL,
                actor TEXT,
                action TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                details TEXT,
                created_at {ts} NOT NULL
            )
        """)
        # 身份扩展表：以门户 username 为主键，**不是第二套用户库**（见模块 __init__）
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {T_PROFILE} (
                username TEXT PRIMARY KEY,
                display_name TEXT,
                email TEXT,
                org_name TEXT,
                org_position TEXT,
                org_level TEXT,
                ap_role TEXT NOT NULL DEFAULT 'MEMBER',
                created_at {ts},
                updated_at {ts}
            )
        """)
        # 组织架构：来自 Escalation Matrix（见 org.py 的 ORG_SEED）
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {T_ORG} (
                id {ident},
                level TEXT,
                position TEXT,
                name TEXT,
                name_key TEXT,
                orange TEXT,
                lonestar TEXT,
                email TEXT,
                username TEXT,
                sort_order {int_t} NOT NULL DEFAULT 0,
                active {int_t} NOT NULL DEFAULT 1,
                updated_at {ts}
            )
        """)

        conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS ux_ap_no ON {T_TASKS}(ap_no)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS ix_ap_status ON {T_TASKS}(status)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS ix_ap_owner ON {T_TASKS}(owner_username)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS ix_ap_reviewer ON {T_TASKS}(reviewer_username)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS ix_ap_due ON {T_TASKS}(due_at)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS ix_ap_updates ON {T_UPDATES}(ap_id)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS ix_ap_reviews ON {T_REVIEWS}(ap_id)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS ix_ap_history ON {T_HISTORY}(ap_id)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS ix_ap_org_key ON {T_ORG}(name_key)")
        conn.commit()
    finally:
        if own:
            conn.close()


def next_ap_no(conn) -> str:
    """生成 `AP-YYYYMMDD-NNN`。

    不用 `count+1` 做唯一来源 —— 并发下会重号。这里只是**取个起点**，
    真正的唯一性由 `ux_ap_no` 保证，插入冲突时由调用方重试（见 `routers/ap.py`）。
    """
    day = datetime.now().strftime("%Y%m%d")
    prefix = f"AP-{day}-"
    row = conn.execute(
        f"SELECT COUNT(*) FROM {T_TASKS} WHERE ap_no LIKE ?", (prefix + "%",)
    ).fetchone()
    n = (row[0] if row else 0) + 1
    return f"{prefix}{n:03d}"


def history(conn, ap_id: int, actor: str, action: str,
            from_status: str | None = None, to_status: str | None = None,
            details=None) -> None:
    """写一条操作历史。调用方负责与业务更新在同一事务里提交。"""
    conn.execute(
        f"INSERT INTO {T_HISTORY} (ap_id, actor, action, from_status, to_status, details, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ap_id, actor, action, from_status, to_status,
         json.dumps(details, ensure_ascii=False) if details else None, now()),
    )


def parse_json(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def columns_of(conn, table: str) -> set[str]:
    try:
        return set(table_columns(conn, table))
    except Exception:  # noqa: BLE001  表不存在等情况交给上层报错
        return set()
