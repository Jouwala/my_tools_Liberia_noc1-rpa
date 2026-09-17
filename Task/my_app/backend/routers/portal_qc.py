# -*- coding: utf-8 -*-
"""MsPortal「Quality Control」面板数据接口（只读）。

供 http://localhost/MsPortal/ 静态门户的 QC 面板调用：经 nginx `/api/` 兜底转发
到本机 7038（见 nginx.conf 的 location /api/；MsPortal 的 Referer 不命中
$portal_ref 的 eflow 规则，故不会被误转给门户上游）。

只做聚合计数与明细分页，不写任何数据、不落库。

口径（与现有看板保持一致，勿在此处另立标准）：
- alarm：realtime_alarm 未清除且命中断站告警白名单。白名单直接复用
  eflow_alarm_service.ALARM_CODE_CONDS（与实时/历史告警同步同一份，保证口径唯一）。
- tt/wo/cr/pmt：沿用 gis.py 的「只有 Closed 是终态」约定
  （eflow_cr 额外把 Canceled 视为终态）。
- spms：inband_details / outbound_details 的未关闭单，closed 词表与
  get_sp_table._status_breakdown 一致。

注意：本模块的 SQL 必须用 `?` 占位符 —— get_raw_connection 的 PG 包装层
（database._PsycopgRaw）在带参数时会把字面 '%' 转义成 '%%' 并把 '?' 转成 '%s'，
所以 LIKE 的通配符必须放进参数值（如 '%kw%'），不能写进 SQL 文本。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names, table_columns
from backend.services.eflow_alarm_service import ALARM_CODE_CONDS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["portal-qc"])

METRICS = ("alarm", "tt", "wo", "cr", "pmt", "spms")

_SUMMARY_TTL_SEC = 60
_summary_lock = threading.Lock()
_summary_cache: dict = {"at": 0.0, "payload": None}

# 与 get_sp_table._status_breakdown 完全一致的「已关闭」词表
SP_CLOSED_WORDS = ("closed", "close", "done", "已关闭", "完成", "yes", "y", "1", "true")

_TT_OPEN = "status <> 'Closed'"
_WO_OPEN = "status <> 'Closed'"
_CR_OPEN = "status NOT IN ('Closed','Canceled')"
_PM_OPEN = "status <> 'Closed'"

_MAX_PAGE_SIZE = 200

# 标题栏「达标率」的统计窗口（天）。按 eflow_tt.created_time 过滤。
_SLA_WINDOW_DAYS = 30


def _rows_as_dicts(cursor):
    """cursor -> [dict, ...]（双模：sqlite Row / PG 元组均兼容）"""
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


def _scalar(conn, sql, params=None):
    row = conn.execute(sql, params or []).fetchone()
    return row[0] if row else None


# 实时告警表是「整表重建」写法的受害者：eflow_active_alarm 任务每 30 分钟跑一次，
# _write_alarm_to_appdb 不传 upsert_key → pandas if_exists="replace" → DROP + CREATE + INSERT。
# 重建窗口内任何读该表的请求都会拿到 "relation ... does not exist"（不是我们的 SQL 有问题），
# 而且会同时打到 gis / alarm_dashboard 等所有读 realtime_alarm 的看板（后端日志里都能看到）。
# 窗口很短，退避重试几次即可跨过；非「表不存在」的错误立即上抛，不掩盖真问题。
_MISSING_TABLE_HINTS = ("UndefinedTable", "不存在", "does not exist", "no such table")


def _is_missing_table_error(exc) -> bool:
    text = f"{type(exc).__name__}: {exc}"
    return any(h in text for h in _MISSING_TABLE_HINTS)


def _retry_missing_table(fn, attempts=3, delay=0.6):
    """对「表正在被重建」这种瞬时错误做短退避重试。"""
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if not _is_missing_table_error(exc) or i == attempts - 1:
                raise
            time.sleep(delay)
    return None


def _norm_restype(value) -> str:
    """白名单 restype(zte.ran.nodeb) ↔ DB restypename(ZTE_RAN_NODEB) 的归一化。"""
    return str(value).replace("_", ".").lower()


def _alarm_predicate():
    """断站告警白名单谓词 + 参数。

    realtime_alarm.restypename 落库的是导出显示形式（ZTE_RAN_NODEB），而
    ALARM_CODE_CONDS 写的是接口形式（zte.ran.nodeb），故两侧都做同一套
    '_'→'.' + 小写归一化后再比较（否则命中恒为 0）。
    """
    expr = "LOWER(REPLACE(CAST(restypename AS TEXT), '_', '.')) = ?"
    conds, params = [], []
    for c in ALARM_CODE_CONDS:
        conds.append(f"({expr} AND CAST(alarmcode AS TEXT) = ?)")
        params.append(_norm_restype(c["restype"]))
        params.append(str(c["alarmcode"]))
    return "(" + " OR ".join(conds) + ")", params


_ALARM_WHERE, _ALARM_PARAMS = _alarm_predicate()


def _sp_status_column(conn, table: str):
    """探测 SP 表的 status 列（与 _status_breakdown 同一策略：首个含 status/closed 的列）。"""
    for col in table_columns(conn, table):
        low = str(col).lower()
        if "status" in low or "closed" in low:
            return col
    return None


def _sp_open_counts(conn):
    """inband_details / outband_details 的未关闭单数。"""
    total_unclosed = 0
    detail = {}
    words = ",".join("'" + w.replace("'", "''") + "'" for w in SP_CLOSED_WORDS)
    for table in ("inband_details", "outband_details"):
        col = _sp_status_column(conn, table)
        if not col:
            raise RuntimeError(f"{table} 未找到 status 列")
        col_quoted = '"' + str(col).replace('"', '""') + '"'
        # COALESCE 到 '' 与 _status_breakdown 把空值/NaN 计入 unclosed 的行为一致
        unclosed = _scalar(
            conn,
            f"SELECT COUNT(*) FROM {table} WHERE "
            f"LOWER(TRIM(COALESCE(CAST({col_quoted} AS TEXT), ''))) NOT IN ({words})",
        )
        unclosed = int(unclosed or 0)
        detail[table] = unclosed
        total_unclosed += unclosed
    return total_unclosed, detail


def _collect_summary() -> dict:
    """逐项独立容错：单项失败只让该项 value=None + error，绝不整体 500。"""
    metrics: dict = {}

    def guard(metric, fn, extras=None):
        try:
            result = fn()
            metrics[metric] = {"value": None, "error": None, **(extras or {})}
            if isinstance(result, dict):
                metrics[metric].update(result)
            else:
                metrics[metric]["value"] = result
        except Exception as exc:  # noqa: BLE001
            logger.warning("[portal-qc] %s 统计失败: %s", metric, exc, exc_info=True)
            metrics[metric] = {"value": None, "error": f"{type(exc).__name__}: {exc}"[:200]}

    with get_raw_connection() as conn:
        names = set(list_table_names(conn))

        def table_ok(name):
            if name not in names:
                raise RuntimeError(f"表不存在: {name}")

        def alarm():
            table_ok("realtime_alarm")
            sql = (
                "SELECT COUNT(*) AS alarms, COUNT(DISTINCT site_id) AS sites "
                "FROM realtime_alarm WHERE TRIM(CAST(clearstate AS TEXT)) = '0' AND "
                + _ALARM_WHERE
            )
            row = _retry_missing_table(lambda: conn.execute(sql, _ALARM_PARAMS).fetchone())
            return {"value": int(row[0] or 0), "sites": int(row[1] or 0)}

        def tt():
            table_ok("eflow_tt")
            return int(_scalar(conn, f"SELECT COUNT(*) FROM eflow_tt WHERE {_TT_OPEN}") or 0)

        def wo():
            table_ok("eflow_wo")
            return int(_scalar(conn, f"SELECT COUNT(*) FROM eflow_wo WHERE {_WO_OPEN}") or 0)

        def cr():
            table_ok("eflow_cr")
            return int(_scalar(conn, f"SELECT COUNT(*) FROM eflow_cr WHERE {_CR_OPEN}") or 0)

        def pmt():
            table_ok("eflow_pm")
            sql = (
                f"SELECT COUNT(*) AS c, SUM(CASE WHEN pmt_overdue = 'Yes' THEN 1 ELSE 0 END) AS o "
                f"FROM eflow_pm WHERE {_PM_OPEN}"
            )
            row = conn.execute(sql).fetchone()
            return {"value": int(row[0] or 0), "overdue": int(row[1] or 0)}

        def spms():
            total, detail = _sp_open_counts(conn)
            return {"value": total, "tables": detail}

        def sla():
            """标题栏「达标率」= 近 N 天创建的 TT 里 SLA 判定为 Pass 的占比。

            分母只取已有明确判定（Pass / Failed）的单：eFlow 里还会出现
            'Within SLA'（在途、尚未超期）与空值，把它们算进分母等于把在途单
            当成未达标，会系统性低估达标率。created_time 是 'YYYY-MM-DD HH:MM:SS'
            文本，字典序即时间序，故可直接用 >= 比较（PG/SQLite 双模一致）。
            """
            table_ok("eflow_tt")
            since = (datetime.now() - timedelta(days=_SLA_WINDOW_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
            row = conn.execute(
                "SELECT SUM(CASE WHEN sla_status = 'Pass' THEN 1 ELSE 0 END) AS passed, "
                "COUNT(*) AS total FROM eflow_tt "
                "WHERE created_time >= ? AND sla_status IN ('Pass','Failed')",
                [since],
            ).fetchone()
            passed, total = int(row[0] or 0), int(row[1] or 0)
            return {
                "value": round(passed / total * 100, 1) if total else None,
                "pass": passed,
                "total": total,
                "days": _SLA_WINDOW_DAYS,
            }

        guard("alarm", alarm)
        guard("tt", tt)
        guard("wo", wo)
        guard("cr", cr)
        guard("pmt", pmt)
        guard("spms", spms)
        guard("sla", sla)

    return {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "metrics": metrics,
    }


@router.get("/api/portal-qc/summary")
def portal_qc_summary(refresh: int = 0):
    """QC 面板 6 项统计。默认 60s 缓存；refresh=1 强制刷新。"""
    now = time.time()
    with _summary_lock:
        cached = _summary_cache["payload"]
        fresh = cached is not None and (now - _summary_cache["at"]) < _SUMMARY_TTL_SEC
        if fresh and not refresh:
            return {**cached, "cached": True}

    payload = _collect_summary()
    with _summary_lock:
        _summary_cache["payload"] = payload
        _summary_cache["at"] = time.time()
    return {**payload, "cached": False}


# ========== 明细下钻 ==========
# 每项一份列定义：(SQL 表达式, 输出 key, 表头)；SQL 表达式统一用原名，需要引号的自带引号。
_COLUMNS = {
    "alarm": [
        ("tt_id", "tt_id", "TT No."),
        ("site_name", "site_name", "Site Name"),
        ("site_id", "site_id", "Site ID"),
        ("codename", "codename", "Alarm Name"),
        ("alarmcode", "alarmcode", "Alarm Code"),
        ("perceivedseverityname", "severity", "Severity"),
        ("alarmraisedtime", "raised", "Raised Time"),
        ("durationname", "duration", "Duration"),
        ("auxiliarycount", "down_sites", "Down Sites"),
        ("assign_rulename", "assign_rule", "Assign Rule"),
        ("region", "region", "Region"),
    ],
    "tt": [
        ("tt_no", "tt_no", "TT No."),
        ("title", "title", "Title"),
        ("status", "status", "Status"),
        ("ticket_severity", "severity", "Severity"),
        ("sla_status", "sla", "SLA Status"),
        ("site_name", "site_name", "Site Name"),
        ("alarm_occur_time", "occur", "Occurrence Time"),
        ("created_time", "created", "Created Time"),
        ("fault_duration_time", "duration", "Fault Duration"),
        ("site_outage", "outage", "Site Outage"),
        ("last_processer_group", "group", "Last Processer Group"),
        ("last_processer", "processer", "Last Processer"),
    ],
    "wo": [
        ("wo_no", "wo_no", "WO No."),
        ("tt_no", "tt_no", "TT No."),
        ("status", "status", "Status"),
        ("ticket_severity", "severity", "Severity"),
        ("sla_status", "sla", "SLA Status"),
        ("site_name", "site_name", "Site Name"),
        ("created_time", "created", "Created Time"),
        ("expected_finish_time", "expected", "Expected Finish Time"),
        ("rc_main_category", "rc_main", "RCA Main Category"),
        ("rc_sub_category", "rc_sub", "RCA Sub Category"),
        ("source", "source", "Source"),
    ],
    "cr": [
        ("change_request_id", "cr_id", "CR ID"),
        ("cr_title", "title", "CR Title"),
        ("status", "status", "Status"),
        ("change_type", "change_type", "Change Type"),
        ("implementer", "implementer", "Implementer"),
        ("request_registration_time", "requested", "Request Time"),
        ("planned_start_time", "plan_start", "Planned Start"),
        ("planned_end_time", "plan_end", "Planned End"),
        ("closed_time", "closed", "Closed Time"),
        ("requester_user_name", "requester", "Requester"),
    ],
    "pmt": [
        ("pmt_no", "pmt_no", "PMT No."),
        ("title", "title", "Title"),
        ("status", "status", "Status"),
        ("pmt_overdue", "overdue", "Overdue"),
        ("service_classification", "service", "Service Classification"),
        ("site_name", "site_name", "Site Name"),
        ("current_task_start_time", "start", "Task Start"),
        ("current_task_end_time", "end", "Task End"),
        ("completed_items", "completed", "Completed Items"),
        ("total_items", "total", "Total Items"),
    ],
    "spms": [
        ("src", "src", "Type"),
        ("doc_no", "doc_no", "Doc No."),
        ("status", "status", "Status"),
        ("material_no", "material_no", "Material No."),
        ("material_name", "material_name", "Material Name"),
        ("qty", "qty", "Qty"),
        ("warehouse", "warehouse", "Warehouse"),
        ("create_time", "create_time", "Create Time"),
        ("closed_time", "closed_time", "Closed Time"),
    ],
}

_ORDER = {
    "alarm": "alarmraisedtime DESC",
    "tt": "created_time DESC",
    "wo": "created_time DESC",
    "cr": "request_registration_time DESC",
    "pmt": "created_time DESC",
    "spms": "create_time DESC",
}

_SP_UNION = (
    "SELECT 'Inbound' AS src, \"Inbound No.\" AS doc_no, \"Status\" AS status, "
    "\"Material No.\" AS material_no, \"Material Name\" AS material_name, "
    'CAST("Inbound Qty" AS TEXT) AS qty, "Warehouse Name" AS warehouse, '
    '"Create Time" AS create_time, "Closed Time" AS closed_time '
    "FROM inband_details WHERE {in_open} "
    "UNION ALL "
    "SELECT 'Outbound', \"Outbound No.\", \"Status\", \"Material No.\", \"Material Name\", "
    'CAST("Outbound Qty" AS TEXT), "Warehouse Name", "Create Time", "Closed Time" '
    "FROM outband_details WHERE {out_open}"
)


def _sp_open_expr(conn, table: str) -> str:
    col = _sp_status_column(conn, table)
    if not col:
        raise RuntimeError(f"{table} 未找到 status 列")
    col_quoted = '"' + str(col).replace('"', '""') + '"'
    words = ",".join("'" + w.replace("'", "''") + "'" for w in SP_CLOSED_WORDS)
    return f"LOWER(TRIM(COALESCE(CAST({col_quoted} AS TEXT), ''))) NOT IN ({words})"


def _detail_source(conn, metric: str):
    """返回 (from_sql, where_sql, params) —— where_sql 已含未关闭/断站口径。"""
    if metric == "alarm":
        return "realtime_alarm", "TRIM(CAST(clearstate AS TEXT)) = '0' AND " + _ALARM_WHERE, list(_ALARM_PARAMS)
    if metric == "tt":
        return "eflow_tt", _TT_OPEN, []
    if metric == "wo":
        return "eflow_wo", _WO_OPEN, []
    if metric == "cr":
        return "eflow_cr", _CR_OPEN, []
    if metric == "pmt":
        return "eflow_pm", _PM_OPEN, []
    if metric == "spms":
        return (
            "(" + _SP_UNION.format(
                in_open=_sp_open_expr(conn, "inband_details"),
                out_open=_sp_open_expr(conn, "outband_details"),
            ) + ") t",
            "1 = 1",
            [],
        )
    raise HTTPException(status_code=400, detail=f"未知 metric: {metric}")


@router.get("/api/portal-qc/detail")
def portal_qc_detail(
    metric: str = Query(..., description="alarm/tt/wo/cr/pmt/spms"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=_MAX_PAGE_SIZE),
    q: str = Query("", description="跨列模糊搜索"),
):
    """某项统计的明细列表（分页 + 模糊搜索）。"""
    metric = (metric or "").strip().lower()
    if metric not in METRICS:
        raise HTTPException(status_code=400, detail=f"未知 metric: {metric}")

    spec = _COLUMNS[metric]
    with get_raw_connection() as conn:
        src, where, params = _detail_source(conn, metric)
        if metric != "spms" and src not in set(list_table_names(conn)):
            raise HTTPException(status_code=503, detail=f"表不存在: {src}")

        select = ", ".join(f"{expr} AS {key}" for expr, key, _ in spec)

        keyword = (q or "").strip()
        if keyword:
            # 通配符必须放在参数值里：带参数时 SQL 文本中的 '%' 会被包装层转义成 '%%'
            like = f"%{keyword.lower()}%"
            ors = " OR ".join(
                f"LOWER(COALESCE(CAST(({expr}) AS TEXT), '')) LIKE ?" for expr, _, _ in spec
            )
            where = f"({where}) AND ({ors})"
            params = params + [like] * len(spec)

        total = int(_retry_missing_table(
            lambda: _scalar(conn, f"SELECT COUNT(*) FROM {src} WHERE {where}", params)) or 0)
        offset = (page - 1) * size
        rows = _retry_missing_table(lambda: _rows_as_dicts(conn.execute(
            f"SELECT {select} FROM {src} WHERE {where} ORDER BY {_ORDER[metric]} LIMIT ? OFFSET ?",
            params + [size, offset],
        )))

    return {
        "metric": metric,
        "total": total,
        "page": page,
        "size": size,
        "columns": [{"key": key, "label": label} for _, key, label in spec],
        "rows": rows,
    }
