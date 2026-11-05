# -*- coding: utf-8 -*-
"""
bot_data.py - 给机器人（群 + 网页助手）的数据域查询 API
=====================================================
前缀：/api/bot-data

为什么要有这个路由
------------------
2026-11-03 审计：生产库里 ``app`` schema 有 78 张表（另有 ``eflow`` / ``ms_sla`` /
``battery`` / ``ipran_ume`` / ``ran_ume`` / ``lte_pl`` / ``fw`` 共 7 个业务 schema，
最大表 ``ipran_ume.Metro_ring_me_15mins`` 有 195 万行），但机器人的 11 个工具里
**只有 5 个真正在查业务数据**（TT 统计、TT 单号、站点属性、实时告警、库存），
其余是规则字典与知识库检索。运维最常问的几类问题 —— 电源、历史告警、WO ——
**一个都没有对应工具**，模型只能拿规则文档硬编，或者干脆答不出。

这个路由提供五个**高频数据域**的精确查询：

=================  ==================================  ==========================
域                数据源                              典型问法
=================  ==================================  ==========================
power             ipt_power_sites / ipt_power_snapshots  「XX 站电源状态怎么样」
alarm-history     history_alarm（175 列 / 1.9 万行）    「XX 站最近有什么告警」
wo                eflow_wo（173 列 / 1.5 万行）        「XX 站有几个 WO」
site-availability ms_sla 系列（site_availability 口径）  「XX 站这个月可用率多少」
task-stats        task_runner.list_tasks（与任务管理页同源）  「task manager 多少任务成功」
=================  ==================================  ==========================

设计原则
--------
1. **为什么不用 NL2SQL 直接查？** NL2SQL 一次要跑两次 LLM（生成 SQL + 解读结果），
   慢（20~60 秒），且模型偶发写出语义偏差的 SQL —— 对「查无此站」这类需要精确
   结论的问题不可接受。高频问题必须有**固定 SQL**。NL2SQL 只作长尾兜底
   （见 ``/api/data-agent``），两条路各司其职。

2. **查无数据返回 ``count: 0`` 而不是 404。** 「查无此站」「该站本月没有告警」
   本身就是有效答案，机器人要能直接把它说给用户，���该被当成接口错误。

3. **列名方言差异照旧用候选列名探测**（PG 蛇形 vs SQLite 标题式），
   复用 ``site_attribute.py`` 已验证的 ``_resolve_cols`` 模式。

4. **只读。** 本路由只写 SELECT，不提供任何写接口。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.database import DB_MODE, get_raw_connection
from backend.dialect_helpers import list_table_names, table_columns

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bot-data", tags=["bot_data"])


# ---------------------------------------------------------------- 列名探测

def _resolve_cols(conn, table: str, spec: Dict[str, List[str]]) -> Dict[str, str]:
    """把「逻辑字段 → 实际列名」解析出来（PG 蛇形 / SQLite 标题式差异）。

    与 ``site_attribute.py`` 同一套模式：按候选列表逐个试，第一个命中的就用它。
    """
    try:
        have = set(table_columns(conn, table))
    except Exception:  # noqa: BLE001 - 表不存在/无权限都归为「取不到」
        logger.warning("[BOT-DATA] 读取 %s 列信息失败", table, exc_info=True)
        return {}
    out: Dict[str, str] = {}
    for logical, candidates in spec.items():
        for c in candidates:
            if c in have:
                out[logical] = c
                break
    return out


def _pick(row, cols: Dict[str, str], logical: str):
    col = cols.get(logical)
    if not col:
        return None
    try:
        return row[col]
    except (KeyError, IndexError, TypeError):
        return None


def _like_pattern(name: str) -> str:
    """站名模糊匹配 pattern。站点名大小写写法不统一，统一用 LOWER() 比较。"""
    escaped = str(name).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped.lower()}%"


def _prefer_exact(rows: List[Dict[str, Any]], key: str, target: str) -> List[Dict[str, Any]]:
    """把**完全相等**的命中行排到最前。

    模糊匹配会顺带命中「East Wood Camp」这类同后缀的站（问 "Wood Camp" 时），
    结论性回答必须优先用完全相等的站，否则会给错站的数据。
    """
    t = str(target or "").strip().lower()
    if not t:
        return rows
    exact = [r for r in rows if str(r.get(key) or "").strip().lower() == t]
    rest = [r for r in rows if str(r.get(key) or "").strip().lower() != t]
    return exact + rest


def _ms_col_expr(col: str) -> str:
    """把「毫秒时间戳（text 存数字）」转成可比较的数值表达式。

    ⚠️ **方言差异**：该列在 PG 里是 ``text``，存的是 13 位毫秒数字串。
    * PG：用 ``CASE WHEN ~ '^[0-9]+$' THEN ::bigint END`` —— **CASE 保证只求值
      命中的分支**，所以将来上游写进脏值也不会让整条查询报 500。
    * SQLite：``CAST(... AS INTEGER)``，对非数字得 0（不报错）。

    直接写 ``col >= ?`` 会在 PG 报「text >= bigint 不存在」，直接 CAST 遇脏值会中断查询。
    """
    if DB_MODE == "pg":
        return f'(CASE WHEN "{col}" ~ \'^[0-9]+$\' THEN "{col}"::bigint END)'
    return f'CAST("{col}" AS INTEGER)'


def _ms_to_dt(value) -> Optional[str]:
    """毫秒 epoch → 'YYYY-MM-DD HH:MM:SS'（UTC）。

    ``history_alarm`` 的时间字段是毫秒时间戳。**统一按 UTC 解读** —— 与
    ``alarm_dashboard._ms_to_str`` 保持一致，避免同一张表两种口径。
    """
    if value in (None, ""):
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return str(value)
    if ms <= 0:
        return None
    try:
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 列定义

_HISTORY_ALARM_COLS = {
    "site_name": ["site_name", "Site Name"],
    "alarmcode": ["alarmcode", "Alarm Code"],
    "codename": ["codename", "Code Name"],
    "alarm_title": ["alarm_title", "Alarm Title"],
    "severity_name": ["perceivedseverityname", "Perceived Severity Name"],
    "severity": ["perceivedseverity", "Perceived Severity"],
    "raised": ["alarmraisedtime", "Alarm Raised Time"],
    "server_time": ["servertime", "Server Time"],
    "cleared": ["alarmclearedtime", "Alarm Cleared Time"],
    "clearstate": ["clearstate", "Clear State"],
    "tt_id": ["tt_id", "TT Id"],
    "region": ["region", "Region"],
    "province": ["province", "Province"],
    "impact_site_list": ["impact_site_list", "Impact Site List"],
    "impact_site_number": ["impact_site_number", "Impact Site Number"],
    "down_site_count": ["downstream_site_count", "Downstream Site Count"],
    "hub_site": ["hub_site_flag", "Hub Site Flag"],
    "vip_level": ["site_vip_level", "Site Vip Level"],
    "cell_name": ["cell_name", "Cell Name"],
    "ack_state": ["ackstatename", "Ack State Name"],
    "ack_info": ["ackinfo", "Ack Info"],
}

_WO_COLS = {
    "wo_no": ["wo_no", "WO No"],
    "tt_no": ["tt_no", "TT No"],
    "title": ["title", "Title"],
    "status": ["status", "Status"],
    "severity": ["ticket_severity", "Ticket Severity"],
    "created_time": ["created_time", "Created Time"],
    "last_modified": ["last_modified_time", "Last Modified Time"],
    "alarm_occur_time": ["alarm_occur_time", "Alarm Occur Time"],
    "alarm_clear_time": ["alarm_clear_time", "Alarm Clear Time"],
    "site_name": ["site_name", "Site Name"],
    "site_id": ["site_id", "Site Id"],
    "vip_site": ["vip_site", "VIP Site"],
    "hub_site": ["hub_site", "Hub Site"],
    "impact_down_site_count": ["impact_down_site_count", "Impact Down Site Count"],
    "down_site_list": ["down_site_list", "Down Site List"],
    "vip_down_site_count": ["vip_down_site_count", "VIP Down Site Count"],
    "sla_status": ["sla_status", "SLA Status"],
    "sla_remain_time": ["sla_remain_time", "SLA Remain Time"],
    "current_handler": ["current_handler", "Current Handler"],
    "domain": ["domain", "Domain"],
    "ne_name": ["ne_name", "NE Name"],
    "diagnosis": ["diagnosis_result", "Diagnosis Result"],
    "fault_duration": ["fault_duration_time", "Fault Duration Time"],
    "fault_resolved": ["fault_resolved", "Fault Resolved"],
}

_POWER_SITES_COLS = {
    "site_id": ["site_id", "Site Id"],
    "name": ["name", "Name"],
    "internal_reference": ["internal_reference", "Internal Reference"],
    "organization": ["organization", "Organization"],
    "cluster": ["cluster", "Cluster"],
    "priority": ["priority", "Priority"],
    "configuration": ["configuration", "Configuration"],
    "connectivity": ["connectivity", "Connectivity"],
    "criticality": ["criticality", "Criticality"],
    "updated_at": ["updated_at", "Updated At"],
}

_POWER_SNAP_COLS = {
    "snap_time": ["snap_time", "Snap Time"],
    "connectivity": ["connectivity", "Connectivity"],
    "load_current": ["load_current", "Load Current"],
    "load_power": ["load_power", "Load Power"],
    "battery_voltage": ["battery_voltage", "Battery Voltage"],
    "battery_soc": ["battery_soc", "Battery SOC"],
    "battery_charging_state": ["battery_charging_state", "Battery Charging State"],
    "solar_power": ["solar_power", "Solar Power"],
    "generator_on": ["generator_on", "Generator On"],
    "fuel_level": ["fuel_level", "Fuel Level"],
    "fuel_ratio": ["fuel_ratio", "Fuel Ratio"],
    "grid_on": ["grid_on", "Grid On"],
}


def _tables(conn) -> set:
    try:
        return set(list_table_names(conn))
    except Exception:  # noqa: BLE001
        return set()


# ---------------------------------------------------------------- 电源

def _query_power(conn, site: Optional[str], limit: int):
    """电源状态：站点清单 + 最新一条快照。"""
    tabs = _tables(conn)
    if "ipt_power_sites" not in tabs:
        return [], "ipt_power_sites 表不存在"

    site_cols = _resolve_cols(conn, "ipt_power_sites", _POWER_SITES_COLS)
    snap_cols = _resolve_cols(conn, "ipt_power_snapshots", _POWER_SNAP_COLS)

    name_col = site_cols.get("name")
    if not name_col:
        return [], "ipt_power_sites 缺少 name 列"

    where = ""
    params: List[Any] = []
    if site:
        where = ' WHERE LOWER("{}") LIKE ?'.format(name_col)
        params.append(_like_pattern(site))

    # ⚠️ 必须**加别名**：站点主表与快照表都有 connectivity / criticality 等同名列，
    # 不加别名时按列名取值只会拿到最后一个（快照表的），站点主表的 'online'
    # 会被快照的 NULL 顶掉 —— 机器人就只回一句「关键度：major」，供电状态丢了。
    sel_site = ", ".join(
        f's."{c}" AS "site__{k}"' for k, c in site_cols.items()
    ) if site_cols else 's."site_id"'
    sel_snap = ", ".join(
        f'k."{c}" AS "snap__{k}"' for k, c in snap_cols.items()
    ) if snap_cols else "NULL"

    # 精确站名优先下推到 SQL（与 WO / 历史告警一致）。
    order_parts: List[str] = []
    if site and name_col:
        order_parts.append(f'CASE WHEN LOWER(s."{name_col}") = ? THEN 0 ELSE 1 END')
        params.append(str(site).strip().lower())
    order_parts.append(f's."{name_col}"')
    order = " ORDER BY " + ", ".join(order_parts)

    sql = (
        f'SELECT {sel_site}, {sel_snap}'
        f' FROM "ipt_power_sites" s'
        f' LEFT JOIN "ipt_power_snapshots" k'
        f'   ON k."site_id" = s."site_id"'
        f'  AND k."snap_time" = (SELECT MAX(w."snap_time") FROM "ipt_power_snapshots" w'
        f'                       WHERE w."site_id" = s."site_id")'
        f'{where}{order} LIMIT ?'
    )
    params.append(int(limit))

    rows = conn.execute(sql, tuple(params)).fetchall()
    out = []
    for r in rows:
        d: Dict[str, Any] = {}
        for logical, col in site_cols.items():
            d[logical] = _pick(r, {logical: f"site__{logical}"}, logical)
        for logical, col in snap_cols.items():
            v = _pick(r, {logical: f"snap__{logical}"}, logical)
            # 空快照**不得覆盖**站点主表的有效值（很多站根本没有快照行）。
            if v is None or v == '':
                continue
            d[logical] = v
        out.append(d)
    if site:
        out = _prefer_exact(out, "name", site)
    return out, None


# ---------------------------------------------------------------- 历史告警

def _query_history_alarm(conn, site: Optional[str], days: int,
                         severity: Optional[str], limit: int):
    """历史告警明细（history_alarm）。"""
    tabs = _tables(conn)
    if "history_alarm" not in tabs:
        return [], "history_alarm 表不存在"

    cols = _resolve_cols(conn, "history_alarm", _HISTORY_ALARM_COLS)
    name_col = cols.get("site_name")
    if not name_col:
        return [], "history_alarm 缺少 site_name 列"

    conds: List[str] = []
    params: List[Any] = []
    if site:
        conds.append(f'LOWER("{name_col}") LIKE ?')
        params.append(_like_pattern(site))

    raised_col = cols.get("raised")
    if raised_col and days > 0:
        cutoff = int((datetime.now(timezone.utc) - timedelta(days=int(days))).timestamp() * 1000)
        conds.append(f'{_ms_col_expr(raised_col)} >= ?')
        params.append(cutoff)

    sev_col = cols.get("severity_name") or cols.get("severity")
    if severity and sev_col:
        conds.append(f'LOWER(CAST("{sev_col}" AS TEXT)) LIKE ?')
        params.append(f"%{str(severity).lower()}%")

    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    # 同 WO：精确站名优先下推到 SQL，避免被同后缀站挤出 LIMIT 窗口。
    order_parts: List[str] = []
    if site and name_col:
        order_parts.append(f'CASE WHEN LOWER("{name_col}") = ? THEN 0 ELSE 1 END')
        params.append(str(site).strip().lower())
    if raised_col:
        order_parts.append(f'{_ms_col_expr(raised_col)} DESC')
    order = (" ORDER BY " + ", ".join(order_parts)) if order_parts else ""
    sql = f'SELECT * FROM "history_alarm"{where}{order} LIMIT ?'
    params.append(int(limit))

    rows = conn.execute(sql, tuple(params)).fetchall()
    out = []
    for r in rows:
        d: Dict[str, Any] = {}
        for logical, col in cols.items():
            v = _pick(r, cols, logical)
            if logical in ("raised", "server_time", "cleared"):
                v = _ms_to_dt(v)
            d[logical] = v
        out.append(d)
    if site:
        out = _prefer_exact(out, "site_name", site)
    return out, None


# ---------------------------------------------------------------- WO

def _query_wo(conn, site: Optional[str], start: Optional[str], end: Optional[str],
              severity: Optional[str], status: Optional[str], limit: int,
              wo_no: Optional[str] = None):
    """WO 工单明细（eflow_wo）。"""
    tabs = _tables(conn)
    if "eflow_wo" not in tabs:
        return [], "eflow_wo 表不存在"

    cols = _resolve_cols(conn, "eflow_wo", _WO_COLS)
    name_col = cols.get("site_name")
    wo_col = cols.get("wo_no")

    conds: List[str] = []
    params: List[Any] = []
    # 按 WO 单号查是**精确匹配**（单号唯一），优先于站名模糊匹配。
    if wo_no and wo_col:
        conds.append(f'UPPER("{wo_col}") = ?')
        params.append(str(wo_no).strip().upper())
    elif site and name_col:
        conds.append(f'LOWER("{name_col}") LIKE ?')
        params.append(_like_pattern(site))

    created_col = cols.get("created_time")
    if created_col and start:
        conds.append(f'"{created_col}" >= ?')
        params.append(str(start))
    if created_col and end:
        conds.append(f'"{created_col}" <= ?')
        params.append(str(end))

    sev_col = cols.get("severity")
    if severity and sev_col:
        conds.append(f'LOWER(CAST("{sev_col}" AS TEXT)) LIKE ?')
        params.append(f"%{str(severity).lower()}%")

    st_col = cols.get("status")
    if status and st_col:
        # ⚠️ **库里没有 "Open" 这个状态值**。eflow_wo.status 的实际取值是：
        #   Closed / Wait For Confirm / Waiting for Accept / Waiting for Process /
        #   Waiting for Leave Site / Waiting for Arrive Site / Waiting for Departure …
        # 所以运维口径的「未闭环 / 未关闭」必须表达成**排除 Closed**，而不是匹配 Open。
        # 后端因此支持两种写法：
        #   "!Closed" / "not:Closed"  → NOT LIKE（排除语义）
        #   "Closed,Wait For Confirm" → OR 多值
        raw = str(status).strip()
        neg = raw.startswith("!") or raw.lower().startswith("not:")
        if raw.lower().startswith("not:"):
            raw = raw[4:]
        else:
            raw = raw.lstrip("!").strip()
        vals = [v.strip() for v in raw.split(",") if v.strip()]
        if vals:
            op = "NOT LIKE" if neg else "LIKE"
            parts = []
            for v in vals:
                parts.append(f'LOWER(CAST("{st_col}" AS TEXT)) {op} ?')
                params.append(f"%{v.lower()}%")
            conds.append("(" + " AND ".join(parts) + ")"
                         if neg else "(" + " OR ".join(parts) + ")")

    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    # 精确站名优先**下推到 SQL**：只靠 Python 侧 _prefer_exact 是不够的 ——
    # LIMIT 先截断再重排，精确站可能已被同后缀站（East Wood Camp / Wood Camp2）挤出窗口。
    order_parts: List[str] = []
    if site and name_col:
        order_parts.append(f'CASE WHEN LOWER("{name_col}") = ? THEN 0 ELSE 1 END')
        params.append(str(site).strip().lower())
    if created_col:
        order_parts.append(f'"{created_col}" DESC')
    order = (" ORDER BY " + ", ".join(order_parts)) if order_parts else ""
    sql = f'SELECT * FROM "eflow_wo"{where}{order} LIMIT ?'
    params.append(int(limit))

    rows = conn.execute(sql, tuple(params)).fetchall()
    out = []
    for r in rows:
        d: Dict[str, Any] = {}
        for logical, col in cols.items():
            d[logical] = _pick(r, cols, logical)
        out.append(d)
    if site:
        out = _prefer_exact(out, "site_name", site)
    return out, None


# ---------------------------------------------------------------- 任务管理

def _query_task_stats(task_id: str, days: int, limit: int):
    """my_app 定时任务的执行统计 —— 口径与前端任务管理页**完全一致**。

    为什么不用 NL2SQL 直接查 ``task_execution_log``
    ----------------------------------------------
    2026-11-04 实测故障：问「my_app 的 task manager 有多少任务成功多少失败」，
    NL2SQL 模型把 ``my_app`` 当成**要过滤的字面量**，生成了
    ``WHERE task_id ILIKE '%my_app%' OR task_name ILIKE '%my_app%'``。
    而 ``task_execution_log.task_name`` 存的是中文任务名（「eFlow 数据同步」
    「Liberia 宕站 8小时报告邮件」），压根没有一条含 "my_app" → 命中 0 行 →
    机器人回「没有匹配到任何记录」。**数据明明在库里，答案却是空的。**

    而且即使过滤条件写对，NL2SQL 查的是 ``task_execution_log`` 的**执行流水条数**
    （32704 成功 / 263 失败），而页面口径是**按注册任务取最近一次执行**
    （83 个任务 → 成功 76 / 运行中 3 / 已停用 4）。两个数不是一回事，
    机器人答的也不是用户在页面上看到的那个数。

    所以这里直接复用 ``task_runner.list_tasks(include_runs=True)`` ——
    前端「数据同步」页面渲染的也是同一份数据、同一个 ``classifyTaskStatus``
    判定，天然同口径。

    判定顺序与前端 ``DataSync.tsx: classifyTaskStatus`` 严格一致：
      running  → running（正在跑，不算成功也不算失败）
      未启用   → disabled
      无执行记录 → unknown
      最近一次 success → success / 否则 failed

    ⚠️ 前端的「失败任务横幅」用的是**另一条**更宽的口径（不排除 disabled，
    只排除 running），见 ``failedTasks`` 过滤器。本函数两个都算，
    分别叫 ``counts``（与状态卡一致）和 ``failed_now``（与横幅一致），
    避免机器人给出的数与页面上任何一张卡都对不上。
    """
    try:
        from backend.services import task_runner
    except Exception as e:  # noqa: BLE001
        return None, f"任务服务不可用：{e}"

    try:
        tasks = task_runner.list_tasks(include_runs=True, lang="zh")
    except Exception as e:  # noqa: BLE001
        return None, f"任务列表读取失败：{e}"

    if task_id:
        tid = task_id.strip()
        tasks = [t for t in tasks if t.get("task_id") == tid]
        if not tasks:
            return None, f"没有名为「{tid}」的注册任务"

    counts = {"running": 0, "success": 0, "failed": 0, "disabled": 0, "unknown": 0}
    rows: List[Dict[str, Any]] = []
    failed_now: List[Dict[str, Any]] = []

    for t in tasks:
        running = bool(t.get("running"))
        enabled = bool(t.get("enabled"))
        runs = t.get("recent_runs") or []
        last = runs[0] if runs else None

        # ---- 与前端 classifyTaskStatus 同一判定顺序 ----
        if running:
            status = "running"
        elif not enabled:
            status = "disabled"
        elif last is None:
            status = "unknown"
        else:
            status = "success" if last.get("success") else "failed"
        counts[status] += 1

        row: Dict[str, Any] = {
            "task_id": t.get("task_id"),
            "name": t.get("name"),
            "category": t.get("category"),
            "status": status,
            "enabled": enabled,
            "last_success": bool(last.get("success")) if last else None,
            "last_started_at": last.get("started_at") if last else None,
            "last_completed_at": last.get("completed_at") if last else None,
            "last_elapsed_seconds": last.get("elapsed_seconds") if last else None,
            "last_error": (last.get("error") or "") if last else None,
            "next_run": t.get("next_run"),
        }
        ri = t.get("retry_info") or {}
        if ri.get("will_retry"):
            row["will_retry"] = True
            row["next_retry_at"] = ri.get("next_retry_at")
        rows.append(row)

        # ---- 失败横幅口径：只排除 running，不排除 disabled ----
        if not running and last is not None and not last.get("success"):
            failed_now.append(row)

    # 失败任务排在前面，其余按名称排 —— 机器人渲染时前 N 条就是最该看的
    rows.sort(key=lambda r: (0 if r["status"] == "failed" else 1, str(r.get("name") or "")))
    failed_now.sort(key=lambda r: str(r.get("last_started_at") or ""), reverse=True)

    payload: Dict[str, Any] = {
        "total": len(tasks),
        "counts": counts,
        "rows": rows[: max(limit, 1)],
        "failed_now": failed_now[: max(limit, 1)],
        "failed_now_total": len(failed_now),
        "days": days,
    }

    # ---- 失败根因聚类（复用页面「失败聚合」弹窗的同一实现）----
    try:
        from backend.services import task_stats
        agg = task_stats.get_recent_failures(days=days, limit=200)
        payload["failure_clusters"] = [
            {
                "status": c.get("status"),
                "count": c.get("count"),
                "error_first_line": c.get("error_first_line"),
                "last_seen": c.get("last_seen"),
                "task_ids": list((c.get("tasks") or {}).keys()),
            }
            for c in (agg.get("clusters") or [])[:10]
        ]
        payload["recent_failure_count"] = agg.get("total_failures")
    except Exception as e:  # noqa: BLE001
        logger.warning("[BOT-DATA] 失败聚类读取失败: %s", e)
        payload["failure_clusters"] = []
        payload["recent_failure_count"] = None

    return payload, None


@router.get("/task-stats")
def get_task_stats(
    task_id: str = Query("", max_length=120, description="任务 ID（精确匹配）"),
    days: int = Query(7, ge=1, le=90, description="失败统计回看天数"),
    limit: int = Query(20, ge=1, le=200, description="最多返回条数"),
):
    """my_app 任务管理执行统计（成功/失败/运行中/已停用 + 失败明细）。"""
    try:
        payload, err = _query_task_stats(task_id.strip(), days, limit)
    except Exception as e:  # noqa: BLE001
        logger.error("[BOT-DATA] 任务统计查询失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"任务统计查询失败：{e}")
    if err:
        return {"ok": False, "domain": "task-stats", "count": 0, "rows": [], "message": err}
    payload["ok"] = True
    payload["domain"] = "task-stats"
    payload["source"] = "live"
    payload["count"] = len(payload.get("rows") or [])
    return payload


# ---------------------------------------------------------------- 可用率

def _query_site_availability(site: str, month: str):
    """站点可用率（复用 site_availability_service 的月度口径）。

    该 service 返回 ``{tech: {(norm_site, day): ratio}}``，这里按站名取回
    该站当月各制式的每日可用率与均值 —— 与「站点可用率」看板同源同口径。
    """
    try:
        from backend.services import site_availability_service as svc
    except Exception as e:  # noqa: BLE001
        return None, f"可用率服务不可用：{e}"

    try:
        data = svc.load_month_availability(month)
    except Exception as e:  # noqa: BLE001
        return None, f"加载 {month} 可用率失败：{e}"

    target = svc.norm_name(site)
    by_tech: Dict[str, List[float]] = {}
    days: Dict[str, Dict[str, float]] = {}
    for tech, mapping in (data or {}).items():
        for (norm_site, day), ratio in mapping.items():
            if norm_site != target:
                continue
            by_tech.setdefault(tech, []).append(float(ratio))
            days.setdefault(str(day), {})[tech] = float(ratio)

    if not by_tech:
        return {
            "site": site, "month": month, "found": False,
            "by_tech": {}, "days": {}, "avg_by_tech": {},
        }, None

    avg = {t: round(sum(v) / len(v), 6) for t, v in by_tech.items()}
    return {
        "site": site, "month": month, "found": True,
        "by_tech": {t: len(v) for t, v in by_tech.items()},
        "avg_by_tech": avg,
        "days": {d: {t: round(v, 6) for t, v in techs.items()}
                 for d, techs in sorted(days.items())},
    }, None


# ---------------------------------------------------------------- 数据集目录

#: 数据集目录 —— 机器人据此知道「库里有什么、每个域怎么问」。
#: 这份目录同时暴露给前端与机器人，是「让机器人更聪明」的关键语义层。
DATASETS: List[Dict[str, Any]] = [
    {
        "domain": "power",
        "title_zh": "站点电源状态",
        "title_en": "Site power status",
        "desc_zh": "查询站点的供电状态：市电/柴发/太阳能/蓄电池的实时读数（负载电流、负载功率、"
                   "电池电压与 SOC、充电状态、发电机是否在用、燃油比例）。",
        "desc_en": "Site power supply status: grid/generator/solar/battery live readings.",
        "params": {"site": "站点名（模糊匹配）"},
        "example_zh": "Wood Camp 电源状态怎么样 / Palm Bay 电量还剩多少",
        "example_en": "what is the power status of Wood Camp",
    },
    {
        "domain": "alarm-history",
        "title_zh": "历史告警",
        "title_en": "Historical alarms",
        "desc_zh": "查询站点历史上发生过的告警：告警码、告警名称、级别、发生时间、是否已清除、"
                   "关联 TT、受影响站点数等。",
        "desc_en": "Historical alarms of a site: code, name, severity, time, cleared state, related TT.",
        "params": {"site": "站点名（模糊匹配）", "days": "回看天数（默认 7，最大 365）",
                   "severity": "级别关键字，如 Critical / Major", "limit": "最多返回条数"},
        "example_zh": "Wood Camp 最近 30 天有什么告警 / Lofa Bridge 上周的告警记录",
        "example_en": "what alarms did Wood Camp have in the last 30 days",
    },
    {
        "domain": "wo",
        "title_zh": "WO 工单",
        "title_en": "WO work orders",
        "desc_zh": "查询 Work Order：WO 号、关联 TT、状态、级别、站点、告警时间、"
                   "SLA 状态与剩余时间、当前处理人、影响站点数、根因与诊断结论。",
        "desc_en": "Work orders: WO no, related TT, status, severity, site, SLA, handler, RCA.",
        "params": {"site": "站点名（模糊匹配）", "start": "起始日期 YYYY-MM-DD",
                   "end": "截止日期 YYYY-MM-DD", "severity": "级别 P1~P4",
                   "status": "状态关键字，如 Closed / Open", "limit": "最多返回条数"},
        "example_zh": "Wood Camp 有几个未闭环的 WO / 这个月 P1 的 WO 有多少",
        "example_en": "how many open WOs does Wood Camp have",
    },
    {
        "domain": "task-stats",
        "title_zh": "任务管理执行统计",
        "title_en": "Task manager execution stats",
        "desc_zh": "查询 my_app 自身定时任务的执行情况：按**注册任务**统计最近一次执行的"
                   "成功/失败/运行中/已停用/未记录，以及失败任务明细与失败根因聚类。"
                   "口径与前端「数据同步」任务管理页面**完全一致**。",
        "desc_en": "Execution stats of my_app scheduled tasks: success/failed/running/disabled/"
                   "unknown per registered task (same caliber as the task manager page), "
                   "plus failed task details and failure root-cause clusters.",
        "params": {"task_id": "任务 ID（可选，精确查某一个任务）",
                   "days": "失败统计回看天数（默认 7，最大 90）",
                   "limit": "失败明细最多返回条数（默认 20）"},
        "example_zh": "my_app的task manager现在有多少任务成功，多少失败 / 有哪些任务执行失败了",
        "example_en": "how many my_app tasks succeeded and how many failed",
    },
    {
        "domain": "site-availability",
        "title_zh": "站点可用率",
        "title_en": "Site availability",
        "desc_zh": "查询站点在某月的可用率（2G/3G/4G/5G 各制式分别统计），"
                   "口径与「站点可用率」看板一致。",
        "desc_en": "Monthly site availability per technology (2G/3G/4G/5G).",
        "params": {"site": "站点名", "month": "月份 YYYY-MM（默认当月）"},
        "example_zh": "Wood Camp 这个月可用率多少 / Lofa Bridge 10 月的 4G 可用率",
        "example_en": "what is the availability of Wood Camp this month",
    },
]


def _collect_site_names(conn) -> List[str]:
    """站名并集：eflow_site / ipt_power_sites / eflow_wo / history_alarm。

    哪张表缺了或列名对不上就跳过那一张 —— 站名清单是**辅助**信息，
    不能因为某一张表异常就让整个接口 500。
    """
    sources = [
        ("eflow_site", "site_name"),
        ("ipt_power_sites", "name"),
        ("eflow_wo", "site_name"),
        ("history_alarm", "site_name"),
    ]
    out = set()
    for table, col in sources:
        try:
            cols = {c.lower() for c in table_columns(conn, table)}
        except Exception:  # noqa: BLE001
            continue
        if col.lower() not in cols:
            continue
        try:
            for (v,) in conn.execute(f'SELECT DISTINCT "{col}" FROM "{table}"').fetchall():
                n = str(v or "").strip()
                if n and n.lower() != "empty":
                    out.add(n)
        except Exception:  # noqa: BLE001
            logger.warning("[BOT-DATA] 读取 %s.%s 站名失败", table, col, exc_info=True)
            continue
    return sorted(out, key=lambda s: s.lower())


# ---------------------------------------------------------------- 路由

@router.get("/datasets")
def list_datasets():
    """数据集目录：有哪些域、每个域能问什么、要传什么参数。

    机器人靠这个知道**数据库里有什么**。没有它，模型只能靠猜，
    于是就会出现「明明库里有数据却答不出来」。
    """
    return {
        "ok": True,
        "count": len(DATASETS),
        "datasets": DATASETS,
        "note": "长尾问题走 NL2SQL（/api/data-agent），本页只列高频精确域。",
    }


@router.get("/sites")
def list_sites(
    prefix: str = Query("", max_length=60, description="按前缀过滤（模糊）"),
):
    """站名清单（多表并集），供机器人**校验抽出来的站名是否真实存在**。

    为什么需要这个接口
    ------------------
    机器人的站名抽取是**规则**驱动的：句子里的英文大写词会被当成站名候选。
    于是「最近7天全网有多少条 **Critical** 级别的告警」里的 Critical 会被抽成
    站名，机器人拿着 "Critical" 去查告警表，查不到就回一句
    「查到了 Critical，但历史告警没有记录」—— 那是**假答案**，库里明明有近两万行。

    有了站名清单，规则层就能把「Critical」这种明显不是站名的候选剔掉，
    整句改走 NL2SQL 去做跨站统计。

    为什么是**并集**而不是只取 eflow_site
    --------------------------------------
    各表覆盖的站不一样：实测 "Wood Camp 2" 只在 ipt_power_sites 里
    （eflow_site 没有），只查 eflow_site 会把真实站名误杀。
    """
    try:
        with get_raw_connection() as conn:
            names = _collect_site_names(conn)
    except Exception as e:  # noqa: BLE001
        logger.error("[BOT-DATA] 站名清单查询失败", exc_info=True)
        raise HTTPException(status_code=500, detail=f"站名清单查询失败：{e}")

    if prefix.strip():
        p = prefix.strip().lower()
        names = [n for n in names if p in n.lower()]
    return {
        "ok": True,
        "count": len(names),
        "sites": names,
        "note": "eflow_site / ipt_power_sites / eflow_wo / history_alarm 的站名并集。",
    }


@router.get("/power")
def get_power(
    site: str = Query("", max_length=120, description="站点名（模糊匹配，空=全部）"),
    limit: int = Query(20, ge=1, le=200),
):
    """站点电源状态（iot_power 快照）。"""
    try:
        with get_raw_connection() as conn:
            rows, err = _query_power(conn, site.strip() or None, limit)
    except Exception as e:  # noqa: BLE001
        logger.error("[BOT-DATA] 电源查询失败: %s", site, exc_info=True)
        raise HTTPException(status_code=500, detail=f"电源查询失败：{e}")
    if err:
        return {"ok": False, "domain": "power", "count": 0, "rows": [], "message": err}
    return {"ok": True, "domain": "power", "source": "live", "count": len(rows), "rows": rows}


@router.get("/alarm-history")
def get_alarm_history(
    site: str = Query("", max_length=120, description="站点名（模糊匹配）"),
    days: int = Query(7, ge=1, le=365, description="回看天数"),
    severity: str = Query("", max_length=40, description="级别关键字，如 Critical"),
    limit: int = Query(50, ge=1, le=500),
):
    """站点历史告警明细。"""
    try:
        with get_raw_connection() as conn:
            rows, err = _query_history_alarm(
                conn, site.strip() or None, days, severity.strip() or None, limit)
    except Exception as e:  # noqa: BLE001
        logger.error("[BOT-DATA] 历史告警查询失败: %s", site, exc_info=True)
        raise HTTPException(status_code=500, detail=f"历史告警查询失败：{e}")
    if err:
        return {"ok": False, "domain": "alarm-history", "count": 0, "rows": [], "message": err}
    return {
        "ok": True, "domain": "alarm-history", "source": "live",
        "params": {"site": site, "days": days, "severity": severity},
        "count": len(rows), "rows": rows,
    }


@router.get("/wo")
def get_wo(
    site: str = Query("", max_length=120, description="站点名（模糊匹配）"),
    wo_no: str = Query("", max_length=40, description="WO 单号（精确匹配，优先于 site）"),
    start: str = Query("", max_length=32, description="起始日期 YYYY-MM-DD"),
    end: str = Query("", max_length=32, description="截止日期 YYYY-MM-DD"),
    severity: str = Query("", max_length=20, description="级别 P1~P4"),
    status: str = Query("", max_length=40, description="状态关键字"),
    limit: int = Query(50, ge=1, le=500),
):
    """WO 工单明细。"""
    try:
        with get_raw_connection() as conn:
            rows, err = _query_wo(
                conn, site.strip() or None, start.strip() or None, end.strip() or None,
                severity.strip() or None, status.strip() or None, limit,
                wo_no.strip() or None)
    except Exception as e:  # noqa: BLE001
        logger.error("[BOT-DATA] WO 查询失败: %s", site, exc_info=True)
        raise HTTPException(status_code=500, detail=f"WO 查询失败：{e}")
    if err:
        return {"ok": False, "domain": "wo", "count": 0, "rows": [], "message": err}
    return {
        "ok": True, "domain": "wo", "source": "live",
        "params": {"site": site, "wo_no": wo_no, "start": start, "end": end,
                   "severity": severity, "status": status},
        "count": len(rows), "rows": rows,
    }


@router.get("/site-availability")
def get_site_availability(
    site: str = Query(..., min_length=1, max_length=120, description="站点名"),
    month: str = Query("", max_length=16, description="月份 YYYY-MM，默认当月"),
):
    """站点月度可用率（2G/3G/4G/5G 分制式）。"""
    m = month.strip() or datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        payload, err = _query_site_availability(site.strip(), m)
    except Exception as e:  # noqa: BLE001
        logger.error("[BOT-DATA] 可用率查询失败: %s", site, exc_info=True)
        raise HTTPException(status_code=500, detail=f"可用率查询失败：{e}")
    if err:
        return {"ok": False, "domain": "site-availability", "message": err}
    payload["ok"] = True
    payload["domain"] = "site-availability"
    payload["source"] = "live"
    return payload


@router.get("/health")
def bot_data_health():
    """自检：各数据域依赖的表在不在、各多少行。"""
    out: Dict[str, Any] = {"ok": True, "tables": {}}
    try:
        with get_raw_connection() as conn:
            names = _tables(conn)
            for t in ("ipt_power_sites", "ipt_power_snapshots",
                      "history_alarm", "eflow_wo", "eflow_tt", "eflow_site",
                      "task_execution_log"):
                if t not in names:
                    out["tables"][t] = {"present": False}
                    out["ok"] = False
                    continue
                try:
                    n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                except Exception:  # noqa: BLE001
                    n = None
                out["tables"][t] = {"present": True, "rows": n}
    except Exception as e:  # noqa: BLE001
        logger.error("[BOT-DATA] 健康检查失败", exc_info=True)
        return {"ok": False, "error": str(e), "tables": {}}
    out["datasets"] = len(DATASETS)
    return out
