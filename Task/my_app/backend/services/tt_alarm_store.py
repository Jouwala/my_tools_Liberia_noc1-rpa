"""TT 告警推送的**日志表**读写（`eflow_tt_whatsapp_alert_log`）。

从 `tt_alarm_whatsapp_service` 拆出：建表、按 tt_no 读历史记录、写回发送结果
三者共同维护同一份表结构，是一个内聚单元，且**不依赖任何配置常量**（表名由调用方
传入或取默认），因此可以独立单测。

## 为什么这是服务内建表（不进 Alembic）

沿用项目既有做法（`battery_kpi_service` / `ms_sla_dashboard` 等同类服务表一致）：
`CREATE TABLE IF NOT EXISTS` 幂等建表 + 建索引。列类型取 TEXT/INTEGER 这类
双方言通用写法；PG 下的 TOCTOU 竞态由 `database.py` 的 `_PsycopgRaw.executescript`
duplicate_table 重试兜住（`backend/database.py:344-369`）。

## 状态语义

`send_status` 只有 `'Y'` / `'N'`：**只有浏览器扩展确认投递成功后**才写 `'Y'`，
超时/失败一律 `'N'` 并把原因写进 `last_error`。绝不伪造成功 —— 见
`tt_alarm_whatsapp_service` 的重推语义。
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
)


def ensure_log_table(conn, table: str = LOG_TABLE) -> None:
    """幂等建表 + 建索引（双模：sqlite / PG）。"""
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
            updated_time     TEXT
        )
        """
    )
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
            f"last_tt_modified, first_seen_time FROM {table} "
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
    }


def record_result(conn, row: Dict[str, Any], ok: bool, error: str = "",
                  existing: Optional[Dict[str, Any]] = None,
                  table: str = LOG_TABLE) -> Dict[str, Any]:
    """写回一条发送结果（upsert by tt_no），返回写入的记录。

    `ok=True` → `send_status='Y'`、`send_count`+1、`last_send_time=now`；
    `ok=False` → `send_status='N'`、`send_count` **不变**（失败不计入发送次数）、
    `last_error` 记原因（截断 500 字符，避免异常堆栈撑爆列）。
    """
    rec = base_record(row, existing)
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
