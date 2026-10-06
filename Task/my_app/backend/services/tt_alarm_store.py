"""TT 告警推送的**日志表**读写（`eflow_tt_whatsapp_alert_log`）。

从 `tt_alarm_whatsapp_service` 拆出：建表、按 tt_no 读历史记录、写回发送结果
三者共同维护同一份表结构，是一个内聚单元，且**不依赖任何配置常量**（表名由调用方
传入或取默认），因此可以独立单测。

## 为什么这是服务内建表（不进 Alembic）

沿用项目既有做法（`battery_kpi_service` / `ms_sla_dashboard` 等同类服务表一致）：
`CREATE TABLE IF NOT EXISTS` 幂等建表 + 建索引。列类型取 TEXT/INTEGER 这类
双方言通用写法；PG 下的 TOCTOU 竞态由 `database.py` 的 `_PsycopgRaw.executescript`
duplicate_table 重试兜住（`backend/database.py:344-369`）。

## 状态语义（2026-10-05 随触发机制切换一并明确）

`send_status` 只有 `'Y'` / `'N'`：**只有推送进程确认投递成功后**才写 `'Y'`，
超时/失败一律 `'N'` 并把原因写进 `last_error`。绝不伪造成功。
这两个字段就是「发没发过 / 发过几次」的权威答案：

  * `send_status`  —— 该单**发送没有**（Y=至少确认送达过一次；N=从未确认送达）
  * `send_count`   —— 该单**发送了几次**（只计确认成功；失败不计数）
  * `last_send_time` —— 最近一次确认成功的时间（重报冷却的基准）

## 跟踪列（触发机制切换新增，2026-10-05）

  * `first_seen_time`        —— 首次触发时间（realtime_alarm 里出现该单告警）
  * `last_alarm_seen_time`   —— 该单关联告警最近一次仍出现在 realtime_alarm 的时间
                                （消失 ≈ 告警清除，是将来「恢复通知」的数据基础）
  * `last_known_update_time` —— 最近一次（实时查单/镜像）见到的 TT last_modified_time
                                （「20 分钟未更新重报」的停滞时钟基准）
  * `last_check_time`        —— 最近一次实时/镜像查单时间

老库升级：`ensure_log_table` 对已存在的表做**幂等加列**（`_ensure_columns`，
sqlite 查 PRAGMA table_info、PG 查 information_schema，缺哪列 ALTER 哪列），
不需要 Alembic —— 与本表「服务内建表」的定位一致。
"""
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from backend.dialect_helpers import upsert

LOG_TABLE = "eflow_tt_whatsapp_alert_log"
LOG_TABLE_INDEX = f"idx_{LOG_TABLE}_status"

# 主键列（不参与补列，建表时即存在）
LOG_PK = ("tt_no",)

# 日志表列（upsert 与 SELECT 共用，避免两处列名分叉）
LOG_COLUMNS = (
    "tt_no", "alarm_occur_time", "ticket_severity", "alarm_code",
    "site_id", "site_name", "title",
    "send_status", "send_count", "last_send_time", "last_tt_modified",
    "first_seen_time", "last_error", "updated_time",
    "last_alarm_seen_time", "last_known_update_time", "last_check_time",
    "mail_notified_time", "mail_summary_time",
)

# ==========================================================
# 幂等补列的**单一事实来源**（2026-10-06 事故修复）
#
# 事故：PG 库里的 `eflow_tt_whatsapp_alert_log` 是**早期版本**建的，缺
# `last_error` 列。`CREATE TABLE IF NOT EXISTS` 对已存在的表是 no-op，不会加列；
# 而旧 `_ensure_columns` 的补列清单**漏了 `last_error`**（只覆盖 TRACK + MAIL），
# 于是每次 `record_result` upsert 都带 `last_error` → PG 报
# `UndefinedColumn: 字段 "last_error" 不存在`，任务整轮失败。
#
# 根因：补列清单与建表列集合**两处各写一份**，加列时容易只改建表、忘了改补列。
# 修复：补列集合 = 建表列全集（LOG_COLUMNS 去掉主键），从此「加列只需改
# LOG_COLUMNS 一处」，结构上杜绝再漏。
# ==========================================================

# 2026-10-05 新增的跟踪列：老库没有这些列，由 _ensure_columns 幂等补上
TRACK_COLUMNS = (
    "last_alarm_seen_time", "last_known_update_time", "last_check_time",
)

# 2026-10-06 新增的**邮件**幂等列：老库没有这些列，同样由 _ensure_columns 补上。
#
# 这两列是邮件「至多一封」的**唯一幂等键**（见 tt_alarm_whatsapp_service 的发信段）：
#   * mail_notified_time —— 首次通报邮件已发出的时间
#   * mail_summary_time  —— 结束汇总邮件已发出的时间
# 非空即视为已发，**永不重发**。没有它们，每 5 分钟一轮的扫描会把同一单的
# 汇总反复发出去（清除状态是持久事实，不会自己消失）。
MAIL_COLUMNS = (
    "mail_notified_time", "mail_summary_time",
)

# 需要向老表补齐的列全集：建表列 - 主键。老表缺哪列补哪列（幂等）。
ENSURE_COLUMNS = tuple(c for c in LOG_COLUMNS if c not in LOG_PK)

# 列类型映射（建表与补列共用；缺省 TEXT）。本表除 send_count(INTEGER) 外全 TEXT。
COLUMN_TYPES = {"send_count": "INTEGER"}


def _is_sqlite(conn) -> bool:
    import sqlite3
    return isinstance(conn, sqlite3.Connection)


def _existing_columns(conn, table: str) -> set:
    if _is_sqlite(conn):
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ? "
        "AND table_schema = ANY(current_schemas(false))",
        (table,),
    ).fetchall()
    return {r[0] for r in rows}


def _ensure_columns(conn, table: str) -> None:
    """给已存在的老表幂等补列（sqlite / PG 的 ADD COLUMN 语法在此场景一致）。

    补列集合 = **建表列全集去掉主键**（`ENSURE_COLUMNS`），不再是一份手写的
    局部清单 —— 2026-10-06 事故正是因为旧清单漏了 `last_error`，导致老库上
    upsert 报 `UndefinedColumn`。现在加列只需改 `LOG_COLUMNS` / CREATE TABLE 一处。

    类型按 `COLUMN_TYPES`（缺省 TEXT）——老库缺列按 TEXT 补对齐 sqlite 宽容语义。

    并发：PG 下两个进程同时补列会 TOCTOU（duplicate_column, 42701）。本函数逐列
    `try/except` 吞掉「已存在」类错误，保证幂等（另一进程刚补上就算成功）。
    """
    present = _existing_columns(conn, table)
    for col in ENSURE_COLUMNS:
        if col in present:
            continue
        col_type = COLUMN_TYPES.get(col, "TEXT")
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        except Exception as e:  # noqa: BLE001
            # 唯一可接受的失败：并发补列时本列已被别的进程加上（duplicate_column）。
            # 其余异常（权限/连接）应上抛，不能静默留下缺列的表。
            _code = getattr(getattr(e, "diag", None), "sqlstate", "") or ""
            _msg = str(e)
            if _code == "42701" or "already exists" in _msg.lower() or "duplicate" in _msg.lower():
                continue
            raise


def _build_create_sql(table: str) -> str:
    """按 `LOG_COLUMNS` / `COLUMN_TYPES` 生成建表 DDL（单一事实来源）。

    这样「加列」只需改 `LOG_COLUMNS` 一处，建表与补列（`_ensure_columns`）自动
    同步 —— 2026-10-06 事故即两处各写一份导致漏列，此生成法从结构上消除该类缺陷。
    """
    defs = []
    for col in LOG_COLUMNS:
        col_type = COLUMN_TYPES.get(col, "TEXT")
        if col in LOG_PK:
            defs.append(f"    {col} {col_type} PRIMARY KEY")
        else:
            defs.append(f"    {col} {col_type}")
    return f"CREATE TABLE IF NOT EXISTS {table} (\n" + ",\n".join(defs) + "\n)"


def ensure_log_table(conn, table: str = LOG_TABLE) -> None:
    """幂等建表 + 建索引 + 老表补列（双模：sqlite / PG）。"""
    conn.execute(_build_create_sql(table))
    _ensure_columns(conn, table)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{table}_status "
        f"ON {table} (send_status, last_send_time)"
    )


def load_records(conn, tt_nos: Iterable[str],
                 table: str = LOG_TABLE) -> Dict[str, Dict[str, Any]]:
    """按 tt_no 批量读历史记录 → {tt_no: {send_status, last_send_time, ...}}。

    分块查询（每块 200 个 tt_no），避免 IN 子句过长触发 SQLite 变量上限
    （默认 SQLITE_MAX_VARIABLE_NUMBER，PG 也有参数上限）。
    """
    nos = [n for n in tt_nos if n]
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(nos), 200):
        chunk = nos[i:i + 200]
        marks = ",".join("?" * len(chunk))
        cur = conn.execute(
            f"SELECT tt_no, send_status, send_count, last_send_time, "
            f"last_tt_modified, first_seen_time, last_error, "
            f"last_known_update_time, last_check_time, last_alarm_seen_time, "
            f"mail_notified_time, mail_summary_time "
            f"FROM {table} "
            f"WHERE tt_no IN ({marks})",
            tuple(chunk),
        )
        names = [d[0] for d in cur.description]
        for r in cur.fetchall():
            row = dict(zip(names, r))
            out[str(row["tt_no"])] = row
    return out


def base_record(row: Dict[str, Any],
                existing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """构造一条日志记录（保留已有的首见时间与发送计数）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tt_no = str(row.get("tt_no") or "")
    return {
        "tt_no": tt_no,
        "alarm_occur_time": row.get("alarm_occur_time"),
        "ticket_severity": row.get("ticket_severity"),
        "alarm_code": row.get("_alarm_code_norm") or row.get("alarm_code"),
        "site_id": row.get("site_id"),
        "site_name": row.get("site_name"),
        "title": row.get("title"),
        "send_status": (existing or {}).get("send_status") or "N",
        "send_count": int((existing or {}).get("send_count") or 0),
        "last_send_time": (existing or {}).get("last_send_time"),
        "last_tt_modified": row.get("last_modified_time"),
        # 首次写入的时间要留住，不能用本轮 now 覆盖
        "first_seen_time": (existing or {}).get("first_seen_time") or now,
        "last_error": (existing or {}).get("last_error"),
        "updated_time": now,
        # 跟踪列：保留已有值，调用方可用 overrides 覆盖（见 record_result）
        "last_alarm_seen_time": (existing or {}).get("last_alarm_seen_time"),
        "last_known_update_time": (existing or {}).get("last_known_update_time"),
        "last_check_time": (existing or {}).get("last_check_time"),
        # 邮件幂等列：必须原样带过来，否则 upsert 会把"已发过"抹成 NULL，
        # 下一轮扫描就会**重复发汇总**（本表 upsert 是整行覆盖，不是增量更新）。
        "mail_notified_time": (existing or {}).get("mail_notified_time"),
        "mail_summary_time": (existing or {}).get("mail_summary_time"),
    }


def _read_mail_state(conn, tt_no, table: str = LOG_TABLE) -> Dict[str, Any]:
    """只回查邮件幂等两列（`record_result` 未收到 existing 时的兜底）。

    查不到（新单）或查询异常一律返回空 dict —— 不能让一次读失败把发送结果写挂。
    """
    if not tt_no:
        return {}
    try:
        cur = conn.execute(
            f"SELECT mail_notified_time, mail_summary_time FROM {table} WHERE tt_no = ?",
            (str(tt_no),),
        )
        r = cur.fetchone()
        if not r:
            return {}
        return {"mail_notified_time": r[0], "mail_summary_time": r[1]}
    except Exception:  # noqa: BLE001
        return {}


def record_result(conn, row: Dict[str, Any], ok: bool, error: str = "",
                  existing: Optional[Dict[str, Any]] = None,
                  table: str = LOG_TABLE,
                  tracking: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """写回一条发送结果（upsert by tt_no），返回写入的记录。

    `ok=True` → `send_status='Y'`、`send_count`+1、`last_send_time=now`；
    `ok=False` → `send_status='N'`、`send_count` **不变**（失败不计入发送次数）、
    `last_error` 记原因（截断 500 字符，避免异常堆栈撑爆列）。

    `tracking` 是本轮已知的跟踪字段（last_known_update_time / last_check_time /
    last_alarm_seen_time），随发送结果一并落库；缺省键保留 existing 原值。

    ⚠️ **邮件幂等列（mail_*）不依赖调用方传 `existing`**：本表 upsert 是整行覆盖，
    若哪天调用方漏传 existing，`mail_summary_time` 会被写成 NULL，同一单的汇总就会
    被**反复重发**（清除是持久事实，不会自己消失）。故此处对未提供的 existing
    主动回查一次这两列 —— 2026-10-06 实测确认过该风险真实存在。
    """
    if existing is None:
        existing = _read_mail_state(conn, row.get("tt_no"), table)
    rec = base_record(row, existing)
    for k, v in (tracking or {}).items():
        if k in TRACK_COLUMNS:
            rec[k] = v
    if ok:
        rec["send_status"] = "Y"
        rec["send_count"] = int(rec["send_count"]) + 1
        rec["last_send_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rec["last_tt_modified"] = row.get("last_modified_time")
        rec["last_error"] = ""
    else:
        rec["send_status"] = "N"
        rec["last_error"] = str(error or "未确认投递")[:500]
    upsert(conn, table, [rec], ["tt_no"])
    return rec


def refresh_tracking(conn, tt_no: str, tracking: Dict[str, Any],
                     table: str = LOG_TABLE) -> bool:
    """只刷新跟踪列，**不触碰任何 send_* 字段**（本轮「不发送、只记录」用）。

    返回是否真的更新了行。记录不存在时**不创建** —— 跟踪信息只对已触发过的单
    有意义；没发过单的候选（级别不符/已清除等被过滤的）不该在日志表里留行，
    否则 `/api/whatsapp/tt-alert/log` 会被从未推送的单刷满。
    """
    if not tt_no:
        return False
    sets, vals = [], []
    for k in TRACK_COLUMNS:
        if k in tracking:
            sets.append(f"{k} = ?")
            vals.append(tracking[k])
    if not sets:
        return False
    sets.append("updated_time = ?")
    vals.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    vals.append(str(tt_no))
    cur = conn.execute(
        f"UPDATE {table} SET {', '.join(sets)} WHERE tt_no = ?", tuple(vals))
    return (cur.rowcount or 0) > 0


def mark_mail_sent(conn, tt_no: str, kind: str,
                   when: Optional[str] = None, table: str = LOG_TABLE) -> bool:
    """标记某单的某类邮件已发（`kind` ∈ {`notified`, `summary`}）。返回是否更新到行。

    **这是邮件幂等的核心**：置位后 `pending_summary_mail` 不再返回该单，
    且 `base_record` 会把该值原样带到后续 upsert，不会被后续写发送结果抹掉。
    """
    col = {"notified": "mail_notified_time", "summary": "mail_summary_time"}.get(kind)
    if not tt_no or not col:
        return False
    ts = when or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        f"UPDATE {table} SET {col} = ?, updated_time = ? WHERE tt_no = ?",
        (ts, ts, str(tt_no)),
    )
    return (cur.rowcount or 0) > 0


def pending_summary_mail(conn, limit: int = 200,
                         table: str = LOG_TABLE) -> list:
    """返回「需要发结束汇总」的单号列表。

    选取条件（三条同时满足）：
      1. `send_count > 0` —— **真发过 WhatsApp** 的单才发汇总。从未确认送达的单
         没有「进展」可言，给它发汇总只会制造噪音。
      2. `mail_summary_time` 为空 —— 还没发过汇总（幂等键）。
      3. `mail_notified_time` 非空 —— 发过首次通报。保证顺序：先有通报才有汇总，
         否则用户会先收到一封"结束汇总"，却从没见过这单的开始。

    ⚠️ **本查询刻意不碰 `realtime_alarm`**：告警清除后该单会从实时表消失
    （2026-10-06 实测：4 个已清除单在 realtime_alarm 里 0 命中，而 eflow_tt 里
    4/4 都在）。所以「是否已结束」由调用方回 `eflow_tt` 用 `alarm_clear_time`
    判断，本函数只负责把「在跟单且没发过汇总」的候选捞出来 —— 这是汇总邮件
    唯一能可靠触发的路径。
    """
    cur = conn.execute(
        f"SELECT tt_no FROM {table} "
        f"WHERE send_count > 0 "
        f"  AND (mail_summary_time IS NULL OR mail_summary_time = '') "
        f"  AND mail_notified_time IS NOT NULL AND mail_notified_time != '' "
        f"ORDER BY COALESCE(last_send_time, updated_time) ASC "
        f"LIMIT ?",
        (int(limit),),
    )
    return [str(r[0]) for r in cur.fetchall()]
