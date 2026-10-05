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

# 日志表列（upsert 与 SELECT 共用，避免两处列名分叉）
LOG_COLUMNS = (
    "tt_no", "alarm_occur_time", "ticket_severity", "alarm_code",
    "site_id", "site_name", "title",
    "send_status", "send_count", "last_send_time", "last_tt_modified",
    "first_seen_time", "last_error", "updated_time",
    "last_alarm_seen_time", "last_known_update_time", "last_check_time",
)

# 2026-10-05 新增的跟踪列：老库没有这些列，由 _ensure_columns 幂等补上
TRACK_COLUMNS = (
    "last_alarm_seen_time", "last_known_update_time", "last_check_time",
)


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
    """给已存在的老表幂等补列（sqlite / PG 的 ADD COLUMN 语法在此场景一致）。"""
    present = _existing_columns(conn, table)
    for col in TRACK_COLUMNS:
        if col not in present:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")


def ensure_log_table(conn, table: str = LOG_TABLE) -> None:
    """幂等建表 + 建索引 + 老表补列（双模：sqlite / PG）。"""
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            tt_no            TEXT PRIMARY KEY,
            alarm_occur_time TEXT,
            ticket_severity  TEXT,
            alarm_code       TEXT,
            site_id          TEXT,
            site_name        TEXT,
            title            TEXT,
            send_status      TEXT,
            send_count       INTEGER,
            last_send_time   TEXT,
            last_tt_modified TEXT,
            first_seen_time  TEXT,
            last_error       TEXT,
            updated_time     TEXT,
            last_alarm_seen_time   TEXT,
            last_known_update_time TEXT,
            last_check_time        TEXT
        )
        """
    )
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
            f"last_known_update_time, last_check_time, last_alarm_seen_time "
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
    }


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
    """
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
