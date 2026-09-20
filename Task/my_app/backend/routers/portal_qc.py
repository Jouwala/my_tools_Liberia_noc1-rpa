# -*- coding: utf-8 -*-
"""MsPortal「Quality Control」面板数据接口（只读）。

供 http://localhost/MsPortal/ 静态门户的 QC 面板调用：经 nginx `/api/` 兜底转发
到本机 7038（见 nginx.conf 的 location /api/；MsPortal 的 Referer 不命中
$portal_ref 的 eflow 规则，故不会被误转给门户上游）。

只做聚合计数与明细分页，不写任何数据、不落库。

口径（与现有看板保持一致，勿在此处另立标准）：
- alarm：realtime_alarm 未清除且命中断站告警白名单。白名单直接复用
  eflow_alarm_service.ALARM_CODE_CONDS（与实时/历史告警同步同一份，保证口径唯一）。
- tt/wo（2026-09-20 按需求改口径）：**告警未清除** —— 即 eflow_tt / eflow_wo 的
  alarm_clear_time 为空（NULL 或空串）。原来用的是「未关闭 status <> 'Closed'」，
  那是工单流程状态，与「告警是否消除」并不等价：实测同一时刻 TT 未关闭 8133 条，
  而告警未清除只有 79 条 —— 面板上摆的是质量指标，看的应是告警本身还没消。
- cr/pmt：沿用 gis.py 的「只有 Closed 是终态」约定
  （eflow_cr 额外把 Canceled 视为终态）。
- spms：inband_details / outband_details 的未关闭单，closed 词表与
  get_sp_table._status_breakdown 一致；此外剔除 Status = WaitingForUpdate
  （尚未生效的出库单，见 SP_IGNORED_WORDS）—— 大数字与下钻明细共用同一份谓词。

下钻明细列（_COLUMNS 的 tt / wo 两项）必须与 my_app 的 TT&WO 看板
（frontend/src/pages/TTWODashboard.tsx，页面 http://<host>/myapp/?page=ttwo）
逐字一致：同样的字段、同样的顺序、同样的表头（表头由 _auto_label 按该页面前端
的同一条规则从字段名生成）。改这里就要同步改那边，反之亦然。

注意：本模块的 SQL 必须用 `?` 占位符 —— get_raw_connection 的 PG 包装层
（database._PsycopgRaw）在带参数时会把字面 '%' 转义成 '%%' 并把 '?' 转成 '%s'，
所以 LIKE 的通配符必须放进参数值（如 '%kw%'），不能写进 SQL 文本。
"""
from __future__ import annotations

import logging
import re
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
# 告警单项的独立缓存（2026-09-18 加，配合 only=alarm）。必须与全量分开：
# MsPortal 的 QC 面板对告警做 5 分钟级刷新、其余做每小时刷新，若共用一份缓存，
# 每 5 分钟一次的告警请求会把全量那份 60s 缓存顶掉 → 「其余每小时」白白多跑 6 条全表 COUNT。
_alarm_cache: dict = {"at": 0.0, "payload": None}

# 与 get_sp_table._status_breakdown 完全一致的「已关闭」词表
SP_CLOSED_WORDS = ("closed", "close", "done", "已关闭", "完成", "yes", "y", "1", "true")

# 额外「不算未关闭」的在途状态（2026-09-20 按需求加）：WaitingForUpdate 是**尚未生效**
# 的单（申请人还没提交更新，属在途态，见 sp_online_sync.STATUS_ALL），不是真正待处理的
# 出入库任务 —— 所以既不计入 SPMS 大数字，也不出现在下钻明细里。
# 与报表侧同一口径：sp_report_gen.gernarate_sp_report.OUTBOUND_DROP_STATUS 与
# sp_report_gen.generate_sp_online_report.EXCLUDED_STATUS 生成报表前也都剔除它。
# 只影响本面板：get_sp_table._status_breakdown 的 closed 口径不动（那边是仓库看板的
# 「已关闭/未关闭」拆分，语义不同，不能顺手改）。
SP_IGNORED_WORDS = ("waitingforupdate",)

# 「未关闭」= status 既不属已关闭词表、也不属被忽略词表。合并成一份，统计与下钻共用。
SP_NOT_OPEN_WORDS = SP_CLOSED_WORDS + SP_IGNORED_WORDS

# TT / WO 的口径 = 「告警未清除」：alarm_clear_time 为空（NULL 或空串）。
# 2026-09-20 由「未关闭 status <> 'Closed'」改来，见模块 docstring 的口径说明。
# 同时判 IS NULL 与 = ''：源表里空值既有 NULL 也有空串（导出链路两种都见过），
# 只判其中一种会漏（实测 TT 的 79 条全是 NULL，但 WO 侧空串出现过）。
_ALARM_UNCLEARED = (
    "(alarm_clear_time IS NULL OR TRIM(CAST(alarm_clear_time AS TEXT)) = '')"
)
_TT_UNCLEARED = _ALARM_UNCLEARED
_WO_UNCLEARED = _ALARM_UNCLEARED
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


def _sp_words_sql(words) -> str:
    """词表 → SQL 的 IN 列表字面量（值里的单引号做转义）。"""
    return ",".join("'" + w.replace("'", "''") + "'" for w in words)


def _sp_open_predicate(col_quoted: str) -> str:
    """SP 明细的「未关闭」谓词 —— 统计与下钻共用这一份，避免两处漂移。

    COALESCE 到 '' 与 _status_breakdown 把空值/NaN 计入 unclosed 的行为一致；
    WaitingForUpdate 随 SP_IGNORED_WORDS 一并排除（见常量注释）。
    """
    return (
        f"LOWER(TRIM(COALESCE(CAST({col_quoted} AS TEXT), ''))) "
        f"NOT IN ({_sp_words_sql(SP_NOT_OPEN_WORDS)})"
    )


def _sp_open_counts(conn):
    """inband_details / outband_details 的未关闭单数（已剔除 WaitingForUpdate）。"""
    total_unclosed = 0
    detail = {}
    for table in ("inband_details", "outband_details"):
        col = _sp_status_column(conn, table)
        if not col:
            raise RuntimeError(f"{table} 未找到 status 列")
        col_quoted = '"' + str(col).replace('"', '""') + '"'
        unclosed = _scalar(
            conn,
            f"SELECT COUNT(*) FROM {table} WHERE {_sp_open_predicate(col_quoted)}",
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
            return int(_scalar(conn, f"SELECT COUNT(*) FROM eflow_tt WHERE {_TT_UNCLEARED}") or 0)

        def wo():
            table_ok("eflow_wo")
            return int(_scalar(conn, f"SELECT COUNT(*) FROM eflow_wo WHERE {_WO_UNCLEARED}") or 0)

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


def _collect_alarm_only() -> dict:
    """只算「未清除的断站告警」（2026-09-18 加，配合 only=alarm）。

    口径必须与 _collect_summary 里的 alarm 完全一致（同一段 SQL、同一份 _ALARM_WHERE、
    同一个 clearstate='0' 判定），否则两个入口会给出不同的数字 —— 面板上同一张卡
    会因为走了哪条路径而变值。

    比全量那份多做一步：把「表正在被 DROP/CREATE 重建」这种瞬时错误也纳入重试。
    realtime_alarm 是整表重建写法的受害者（eflow_active_alarm 每 5 分钟 replace 一次），
    全量路径里 table_ok 是在重试之外抛的，重建窗口内那一轮只能报错；
    这条 5 分钟级的路径调用频率高，值得跨过窗口而不是把错误推给面板。
    """
    def run():
        with get_raw_connection() as conn:
            if "realtime_alarm" not in set(list_table_names(conn)):
                raise RuntimeError("表不存在: realtime_alarm")
            sql = (
                "SELECT COUNT(*) AS alarms, COUNT(DISTINCT site_id) AS sites "
                "FROM realtime_alarm WHERE TRIM(CAST(clearstate AS TEXT)) = '0' AND "
                + _ALARM_WHERE
            )
            return conn.execute(sql, _ALARM_PARAMS).fetchone()

    metrics: dict = {}
    try:
        row = _retry_missing_table(run, attempts=4, delay=0.8)
        metrics["alarm"] = {"value": int(row[0] or 0), "sites": int(row[1] or 0), "error": None}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[portal-qc] alarm 单项统计失败: %s", exc, exc_info=True)
        metrics["alarm"] = {"value": None, "error": f"{type(exc).__name__}: {exc}"[:200]}
    return {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "metrics": metrics,
    }


@router.get("/api/portal-qc/summary")
def portal_qc_summary(refresh: int = 0, only: str = ""):
    """QC 面板统计。

    - 不传 only：六项全量，默认 60s 缓存，refresh=1 强制刷新。
    - only=alarm（2026-09-18 加）：**只算断站告警一项**。MsPortal 的 QC 面板按
      「告警 5 分钟级 / 其余每小时」分频刷新，而六项里只有 realtime_alarm 是高频变化的
      （eflow_active_alarm 每 5 分钟同步；tt/wo/cr/pmt/spms/sla 的源 eflow_sync 每小时
      :00 起跑、约 :06 才跑完）。给告警单开一条，避免每 5 分钟把 6 条全表 COUNT 重跑一遍。
      只返回 metrics.alarm，前端只覆盖 alarm 那一格。
    """
    if only.strip().lower() == "alarm":
        now = time.time()
        with _summary_lock:
            cached = _alarm_cache["payload"]
            fresh = cached is not None and (now - _alarm_cache["at"]) < _SUMMARY_TTL_SEC
            if fresh and not refresh:
                return {**cached, "cached": True}
        payload = _collect_alarm_only()
        with _summary_lock:
            _alarm_cache["payload"] = payload
            _alarm_cache["at"] = time.time()
        return {**payload, "cached": False}

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


def _auto_label(key: str) -> str:
    """字段名 → 表头，规则与 my_app TT&WO 看板前端**逐字相同**。

    对应 TTWODashboard.tsx 里那段：
        k.replace(/_/g, ' ').replace(/\b\\w/g, c => c.toUpperCase())
    例：tt_no → 'Tt No'、alarm_clear_time → 'Alarm Clear Time'。
    放在这里（而不是各写一份表头）是为了让 QC 下钻的表头与
    http://<host>/myapp/?page=ttwo 的明细表永远一致 —— 那边是前端算的，
    两边一旦各写各的就会慢慢漂移。
    """
    return re.sub(r"\b\w", lambda m: m.group(0).upper(), key.replace("_", " "))


# tt / wo 的字段与顺序 = TTWODashboard.tsx 的 _build_tt_fields() / WO_FIELDS
# （site_join_field=site_id、creator_field=creator、sev_field=alarm_severity，
#  由 tt_wo_dashboard._detect_schema() 对当前库判定得出）。
_TT_DRILL_FIELDS = (
    "title", "tt_no", "wo_no", "site_id", "status", "creator",
    "ticket_severity", "alarm_severity", "sla_status",
    "alarm_occur_time", "alarm_clear_time", "domain", "root_cause", "sub_root_cause",
)
_WO_DRILL_FIELDS = (
    "wo_no", "tt_no", "title", "status", "creator", "created_time",
    "alarm_occur_time", "alarm_clear_time", "source",
    "rc_main_category", "rc_sub_category", "ticket_severity", "alarm_severity",
)

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
    "tt": [(f, f, _auto_label(f)) for f in _TT_DRILL_FIELDS],
    "wo": [(f, f, _auto_label(f)) for f in _WO_DRILL_FIELDS],
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
    # tt / wo 的排序 = TTWODashboard.tsx 下钻的 ORDER BY t.alarm_occur_time DESC /
    # w.alarm_occur_time DESC（那边也是按告警发生时间倒序，不是创建时间）。
    "tt": "alarm_occur_time DESC",
    "wo": "alarm_occur_time DESC",
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
    """下钻 UNION 里每张表的「未关闭」条件 —— 与 _sp_open_counts 同一份谓词。"""
    col = _sp_status_column(conn, table)
    if not col:
        raise RuntimeError(f"{table} 未找到 status 列")
    return _sp_open_predicate('"' + str(col).replace('"', '""') + '"')


def _detail_source(conn, metric: str):
    """返回 (from_sql, where_sql, params) —— where_sql 已含未关闭/断站口径。"""
    if metric == "alarm":
        return "realtime_alarm", "TRIM(CAST(clearstate AS TEXT)) = '0' AND " + _ALARM_WHERE, list(_ALARM_PARAMS)
    if metric == "tt":
        return "eflow_tt", _TT_UNCLEARED, []
    if metric == "wo":
        return "eflow_wo", _WO_UNCLEARED, []
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
