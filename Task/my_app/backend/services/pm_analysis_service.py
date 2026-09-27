# -*- coding: utf-8 -*-
"""PM（预防性维护工单 PMT）执行与超期情况分析服务。

数据源：`eflow_pm`（eFlow 同步的动态建表，1632 行 @2026-09-25）。
表结构动态演进且存在重复的大小写列，故**不做静态 ORM 建模**，
一律走 `get_raw_connection` 的 raw SQL（与 `routers/portal_qc.py`、
`services/cr_analysis_service.py` 同一套做法）。

## 口径

**全部口径集中在 `backend/services/pm_caliber.py`** —— 那里是唯一真相源。
字段语义、真实流程顺序、`pmt_overdue` 的含义都在那个文件里写清了
（⚠️ 该表的字段名有误导性：`last_accept_time` 早于 `last_process_time`，
`last_flm_leader_approve_time` 最晚）。本模块只负责拼查询。

一句话概括：时间字段用 `created_time`（工单生成），
「已完成」= `status='Closed'`，「超期」= 源表 `pmt_overdue='Yes'`（不自算），
「未开始」= `completed_items = 0`。比率分母为 0 时返回 `None`
（前端渲染 `—`，不是 0）。

## 下钻口径一致性（AGENTS.md 第三节 1b 的铁律）

`build_overview` 与 `build_drilldown` **共用** `pm_caliber.base_where()` 与
`pm_caliber.bucket_expr()`：前者用在 `SUM(CASE ...)`，后者直接当 `WHERE` 谓词。
主维度是 `pmp_no`（PM 计划），另有 status / site / handler / month 四个次级维度。
新增筛选条件时只加在 `base_where()` 一处。
"""
from __future__ import annotations

import logging

from backend.database import get_raw_connection
from backend.services import pm_caliber as cal

logger = logging.getLogger(__name__)

# 对外沿用旧名，避免调用方改动 —— 真相源仍是 pm_caliber
TABLE = cal.TABLE
MAX_DETAIL_ROWS = cal.MAX_DETAIL_ROWS
DRILL_METRICS = cal.DRILL_METRICS
# 路由层出错回空壳时要用列清单，这里转出一个别名（实际定义在 pm_caliber）
_DETAIL_COLUMNS = cal.DETAIL_COLUMNS

# 计数类字段（与 pm_caliber 的 bucket 键一致）
_COUNT_FIELDS = ("total", "closed", "open", "overdue", "on_time",
                 "not_started", "closed_overdue", "open_overdue", "open_on_time")


def default_window(days: int = 300) -> tuple[str, str]:
    """默认统计窗口（转发 pm_caliber）"""
    return cal.default_window(days)


# ---------------- 内部工具 ----------------


def _fetch_dicts(conn, sql: str, params: list) -> list[dict]:
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _num(v) -> int:
    """SUM() 无行时返回 None，统一成 0"""
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _rate(num: int, den: int):
    """比率；分母为 0 时返回 None（前端渲染 '—'，不是 0）"""
    if not den:
        return None
    return round(num / den * 100.0, 1)


def _case(field: str) -> str:
    """SUM(CASE WHEN <谓词> THEN 1 ELSE 0 END) AS <field>"""
    return f"SUM(CASE WHEN {cal.bucket_expr(field)} THEN 1 ELSE 0 END) AS {field}"


def _empty_overview(start_ts: str, end_ts: str, warnings: list[str]) -> dict:
    """出错时的空壳 —— 结构与成功路径完全一致，前端不必判 null。"""
    zero = {f: 0 for f in _COUNT_FIELDS}
    zero.update({"closure_rate": None, "overdue_rate": None, "start_rate": None, "plans": 0})
    return {
        "meta": {"start": start_ts, "end": end_ts, "table": cal.TABLE,
                 "time_col": cal.TIME_COL, "warnings": warnings},
        "summary": zero, "rows": [], "status_rows": [], "months": [],
        "sites": [], "steps": [],
    }


# ---------------- 概览 ----------------


def build_overview(start: str, end: str) -> dict:
    """按 PM 计划（pmp_no）看执行与超期情况总览。"""
    start_ts, end_ts = cal.normalize_window(start, end)
    where, params = cal.base_where(start_ts, end_ts)

    # 主维度：PM 计划。一条 SQL 拿到全部计数，避免 N 个计划打 N 次库
    agg_sql = f"""
        SELECT
            TRIM(COALESCE({cal.PMP_COL}, ''))       AS pmp_no,
            COUNT(*)                                AS total,
            {_case("closed")},
            {_case("open")},
            {_case("overdue")},
            {_case("on_time")},
            {_case("not_started")},
            {_case("closed_overdue")},
            {_case("open_overdue")},
            {_case("open_on_time")},
            SUM(CAST(COALESCE(NULLIF(TRIM(COALESCE({cal.COMPLETED_COL},'')),''),'0') AS INTEGER))
                                                    AS completed_items,
            SUM(CAST(COALESCE(NULLIF(TRIM(COALESCE({cal.TOTAL_COL},'')),''),'0') AS INTEGER))
                                                    AS total_items,
            COUNT(DISTINCT TRIM(COALESCE({cal.SITE_COL},'')))  AS sites,
            MIN(current_task_start_time)            AS window_start,
            MAX(current_task_end_time)              AS window_end
        FROM {cal.TABLE}
        WHERE {where}
        GROUP BY 1
        ORDER BY total DESC
    """
    # 状态分布（流程卡在哪一步）
    status_sql = f"""
        SELECT TRIM(COALESCE(status, '')) AS status, COUNT(*) AS cnt,
               SUM(CASE WHEN {cal.OVERDUE_SQL} THEN 1 ELSE 0 END) AS overdue
        FROM {cal.TABLE} WHERE {where}
        GROUP BY 1 ORDER BY cnt DESC
    """
    # 月度趋势：按工单生成月分组
    month_sql = f"""
        SELECT SUBSTR({cal.TIME_COL}, 1, 7) AS month,
               COUNT(*)                     AS total,
               {_case("closed")},
               {_case("overdue")}
        FROM {cal.TABLE} WHERE {where}
        GROUP BY 1 ORDER BY 1
    """
    # 站点维度：超期最多的站点（运维最关心的抓手）
    site_sql = f"""
        SELECT TRIM(COALESCE({cal.SITE_COL}, '')) AS site_name,
               COUNT(*)                           AS total,
               {_case("overdue")},
               {_case("open")}
        FROM {cal.TABLE} WHERE {where}
        GROUP BY 1 ORDER BY total DESC LIMIT 20
    """
    # 流程步骤漏斗：每一步走过多少工单（按**真实时序**，见 pm_caliber docstring）
    step_parts = []
    for step, col in cal.STEP_COLUMNS.items():
        step_parts.append(f"SUM(CASE WHEN {cal.not_blank(col)} THEN 1 ELSE 0 END) AS {step}")
    step_sql = f"SELECT {', '.join(step_parts)} FROM {cal.TABLE} WHERE {where}"

    try:
        conn = get_raw_connection()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[pm-analysis] 连接失败: %s", exc)
        return _empty_overview(start_ts, end_ts, [f"数据库连接失败: {exc}"])

    try:
        rows = _shape_plan_rows(_fetch_dicts(conn, agg_sql, params))

        status_rows = _fetch_dicts(conn, status_sql, params)
        for r in status_rows:
            r["status"] = r.get("status") or "(空)"
            r["cnt"] = _num(r.get("cnt"))
            r["overdue"] = _num(r.get("overdue"))

        months = _fetch_dicts(conn, month_sql, params)
        for r in months:
            r["month"] = r.get("month") or ""
            for f in ("total", "closed", "overdue"):
                r[f] = _num(r.get(f))

        sites = _fetch_dicts(conn, site_sql, params)
        for r in sites:
            r["site_name"] = r.get("site_name") or "(空)"
            for f in ("total", "overdue", "open"):
                r[f] = _num(r.get(f))

        step_row = _fetch_dicts(conn, step_sql, params)
        steps = []
        if step_row:
            for step in cal.STEP_COLUMNS:  # 保持 pm_caliber 里定义的真实时序
                steps.append({"step": step, "cnt": _num(step_row[0].get(step))})
    except Exception as exc:  # noqa: BLE001
        logger.exception("[pm-analysis] 聚合失败: %s", exc)
        return _empty_overview(start_ts, end_ts, [f"数据查询失败: {exc}"])
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    # 汇总：各计划按字段相加，比再打一次库更一致（同一份行数据算出来）
    summary = {f: sum(r[f] for r in rows) for f in _COUNT_FIELDS}
    summary["completed_items"] = sum(r["completed_items"] for r in rows)
    summary["total_items"] = sum(r["total_items"] for r in rows)
    summary["closure_rate"] = _rate(summary["closed"], summary["total"])
    summary["overdue_rate"] = _rate(summary["overdue"], summary["total"])
    summary["start_rate"] = _rate(summary["total"] - summary["not_started"], summary["total"])
    summary["plans"] = len(rows)

    warnings: list[str] = []
    if not rows:
        warnings.append("所选时间窗口内没有 PM 工单，请放宽时间范围。")

    return {
        "meta": {"start": start_ts, "end": end_ts,
                 "table": cal.TABLE, "time_col": cal.TIME_COL,
                 "warnings": warnings},
        "summary": summary,
        "rows": rows,
        "status_rows": status_rows,
        "months": months,
        "sites": sites,
        "steps": steps,
    }


def _shape_plan_rows(raw_rows: list[dict]) -> list[dict]:
    """归一计划号后**二次合并**，再算比率。

    为什么需要这一步：`''` 与 `NULL` 在 GROUP BY 里是两类（PG 中 NULL 自成一类），
    归一到同一个兜底名后可能出现两行同名；不合并会让同一计划出现两行，
    且比率各用各自分母算，与下钻（按归一后名字精确匹配）对不上。
    """
    merged: dict[str, dict] = {}
    for r in raw_rows:
        key = r.get("pmp_no") or "(无计划号)"
        tgt = merged.setdefault(key, {
            "pmp_no": key, **{f: 0 for f in _COUNT_FIELDS},
            "completed_items": 0, "total_items": 0, "sites": 0,
            "window_start": "", "window_end": "",
        })
        for f in _COUNT_FIELDS:
            tgt[f] += _num(r.get(f))
        tgt["completed_items"] += _num(r.get("completed_items"))
        tgt["total_items"] += _num(r.get("total_items"))
        # sites 取最大（同计划拆成两行时不能相加，否则站点数虚高）
        tgt["sites"] = max(tgt["sites"], _num(r.get("sites")))
        tgt["window_start"] = min(tgt["window_start"] or "9999", r.get("window_start") or "9999")
        tgt["window_end"] = max(tgt["window_end"] or "", r.get("window_end") or "")

    out = []
    for r in merged.values():
        if r["window_start"] == "9999":
            r["window_start"] = ""
        r["closure_rate"] = _rate(r["closed"], r["total"])
        r["overdue_rate"] = _rate(r["overdue"], r["total"])
        r["item_rate"] = _rate(r["completed_items"], r["total_items"]) if r["total_items"] else None
        out.append(r)
    out.sort(key=lambda r: (-r["total"], r["pmp_no"]))
    return out


# ---------------- 下钻 ----------------


def build_drilldown(start: str, end: str, metric: str, pmp_no: str = "",
                    status: str = "", site_name: str = "",
                    handler: str = "", month: str = "",
                    limit: int = MAX_DETAIL_ROWS) -> dict:
    """下钻明细。

    metric 决定筛哪一批（见 `pm_caliber.bucket_expr`），其余维度参数是
    **叠加**在上面的过滤，与被点的那张卡片的维度完全对应。
    """
    start_ts, end_ts = cal.normalize_window(start, end)

    def _shell(warnings: list[str], total: int = 0) -> dict:
        return {
            "meta": {"start": start_ts, "end": end_ts, "metric": metric,
                     "pmp_no": pmp_no, "status": status, "site_name": site_name,
                     "handler": handler, "month": month, "warnings": warnings},
            "metric": metric, "pmp_no": pmp_no, "status": status,
            "site_name": site_name, "handler": handler, "month": month,
            "total": total, "truncated": False,
            "rows": [], "columns": list(cal.DETAIL_COLUMNS),
        }

    where, params = cal.base_where(start_ts, end_ts, pmp_no)

    predicate = cal.bucket_expr(metric)
    if predicate is None:
        return _shell([f"未知的下钻指标: {metric}"])
    if predicate != "1=1":
        where = f"{where} AND {predicate}"

    if status:
        where = f"{where} AND TRIM(COALESCE(status,'')) = ?"
        params.append(status)
    if site_name:
        where = f"{where} AND TRIM(COALESCE({cal.SITE_COL},'')) = ?"
        params.append(site_name)
    if handler:
        where = f"{where} AND TRIM(COALESCE({cal.HANDLER_COL},'')) = ?"
        params.append(handler)

    if month:
        # month 是 'YYYY-MM'，与 TIME_COL 的 'YYYY-MM-DD HH:MM:SS' 做前缀范围匹配。
        # 用 >= / < 而不是 LIKE：LIKE 必须把通配符放进参数值（PG 包装层会转义 %），
        # 范围比较更直白且能用上索引。
        if len(month) != 7 or month[4] != "-":
            return _shell([f"月份格式非法: {month}"])
        where = f"{where} AND {cal.TIME_COL} >= ? AND {cal.TIME_COL} < ?"
        params.extend([f"{month}-01 00:00:00", f"{month}-32 00:00:00"])

    limit = max(1, min(int(limit or MAX_DETAIL_ROWS), MAX_DETAIL_ROWS))

    count_sql = f"SELECT COUNT(*) FROM {cal.TABLE} WHERE {where}"
    detail_sql = (
        f"SELECT {', '.join(cal.DETAIL_COLUMNS)} FROM {cal.TABLE} WHERE {where} "
        f"ORDER BY {cal.TIME_COL} DESC, pmt_no DESC LIMIT ?"
    )

    try:
        conn = get_raw_connection()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[pm-analysis] 下钻连接失败: %s", exc)
        return _shell([f"数据库连接失败: {exc}"])

    try:
        cur = conn.cursor()
        cur.execute(count_sql, params)
        total = _num(cur.fetchone()[0])

        cur = conn.cursor()
        cur.execute(detail_sql, params + [limit])
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        logger.exception("[pm-analysis] 下钻查询失败: %s", exc)
        return _shell([f"数据查询失败: {exc}"])
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    truncated = total > len(rows)
    warnings: list[str] = []
    if truncated:
        # 显式暴露截断，前端要弹告警条 —— 静默截断会让用户以为数据丢了
        warnings.append(f"结果共 {total} 条，仅返回最近 {len(rows)} 条，请缩小时间范围后重试。")

    out = _shell(warnings, total)
    out["truncated"] = truncated
    out["rows"] = rows
    return out


# ---------------- 筛选项 ----------------


def get_filters() -> dict:
    """筛选项：可选 PM 计划 / 状态 / 站点 / 处理人 + 数据时间范围。

    全部从**全表**取（不受时间窗口限制），否则用户缩小窗口后下拉框会跟着变空，
    无法再把范围改回去。站点有 775 个，只返回超期数最多的前若干，避免下拉框爆炸。
    """
    default_start, default_end = cal.default_window()
    out = {
        "pmp_nos": [], "statuses": [], "sites": [], "handlers": [],
        "default_start": default_start, "default_end": default_end,
        "min_time": "", "max_time": "", "row_count": 0,
    }
    try:
        conn = get_raw_connection()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[pm-analysis] filters 连接失败: %s", exc)
        return out

    def _distinct(sql: str) -> list[str]:
        cur = conn.cursor()
        cur.execute(sql)
        return [r[0] for r in cur.fetchall()]

    try:
        nb = cal.not_blank
        # 计划号按工单数倒序（用户关心大计划），不是字母序
        out["pmp_nos"] = _distinct(f"""
            SELECT TRIM(COALESCE({cal.PMP_COL}, '')) FROM {cal.TABLE}
            WHERE {nb(cal.PMP_COL)}
            GROUP BY 1 ORDER BY COUNT(*) DESC
        """)
        out["statuses"] = _distinct(f"""
            SELECT TRIM(COALESCE(status, '')) FROM {cal.TABLE}
            WHERE {nb('status')} GROUP BY 1 ORDER BY COUNT(*) DESC
        """)
        # 站点 775 个，只给超期最多的 60 个做下拉（其余仍可通过明细搜到）
        out["sites"] = _distinct(f"""
            SELECT TRIM(COALESCE({cal.SITE_COL}, '')) FROM {cal.TABLE}
            WHERE {nb(cal.SITE_COL)}
            GROUP BY 1 ORDER BY SUM(CASE WHEN {cal.OVERDUE_SQL} THEN 1 ELSE 0 END) DESC,
                                  COUNT(*) DESC
            LIMIT 60
        """)
        out["handlers"] = _distinct(f"""
            SELECT TRIM(COALESCE({cal.HANDLER_COL}, '')) FROM {cal.TABLE}
            WHERE {nb(cal.HANDLER_COL)} GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 40
        """)

        cur = conn.cursor()
        cur.execute(f"""
            SELECT COUNT(*), MIN({cal.TIME_COL}), MAX({cal.TIME_COL}) FROM {cal.TABLE}
            WHERE {nb(cal.TIME_COL)}
        """)
        row = cur.fetchone()
        if row:
            out["row_count"] = _num(row[0])
            out["min_time"] = (row[1] or "")[:10]
            out["max_time"] = (row[2] or "")[:10]
            # 全表时间范围比默认窗口更早时，把窗口撑到实际范围，避免默认视图空着
            if out["min_time"] and out["min_time"] < out["default_start"]:
                out["default_start"] = out["min_time"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[pm-analysis] filters 查询失败: %s", exc)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    return out
