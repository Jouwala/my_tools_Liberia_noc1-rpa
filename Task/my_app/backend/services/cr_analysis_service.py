# -*- coding: utf-8 -*-
"""CR（变更请求）按 change_category 的计划与完成情况分析服务。

数据源：`eflow_cr`（eFlow 同步的动态建表，列集合由 API 返回字段决定，
见 `backend/services/sync_from_eflow_api.py:552` 的 `_sync_generic(df, c, "eflow_cr")`）。
表结构动态演进，故本模块**不做静态 ORM 建模**，一律走 `get_raw_connection` 的
raw SQL（与 `routers/portal_qc.py` 同一套做法）。

## 口径

**全部口径（表名、时间字段、终态词表、按时/延期判定、窗口规整）
集中在 `backend/services/cr_caliber.py`** —— 那里是唯一真相源，改口径只改那里。
本模块只负责把这些表达式拼成聚合与下钻查询。

一句话概括：时间字段用 `request_registration_time`（CR 登记时间），
「已排期」= `planned_start_time` 非空，「已执行」= `actual_start_time` 非空，
「按时/延期」比较这两个字段；比率的分母见 `cr_caliber` 的说明，
分母为 0 时返回 `None`（前端渲染 `—`，不是 0）。

## 下钻口径一致性（AGENTS.md 第三节 1b 的铁律）

`build_overview` 与 `build_drilldown` **共用** `cr_caliber.base_where()` 与
`cr_caliber.bucket_expr()`：前者用在 `SUM(CASE ...)`，后者直接当 `WHERE` 谓词。
概览里每个类别的计数，与点开该类别的明细行数，必须严格相等。
新增筛选条件时只加在 `base_where()` 一处，不要在两边各写一遍。
"""
from __future__ import annotations

import logging

from backend.database import get_raw_connection
from backend.services import cr_caliber as cal

logger = logging.getLogger(__name__)

# 对外沿用旧名，避免调用方（routers/cr_analysis.py）改动 —— 真相源仍是 cr_caliber
TABLE = cal.TABLE
MAX_DETAIL_ROWS = cal.MAX_DETAIL_ROWS
DRILL_METRICS = cal.DRILL_METRICS
UNCATEGORIZED = cal.UNCATEGORIZED

# 计数类字段（各行相加得汇总，与 cr_caliber 的 bucket 键一致）
_COUNT_FIELDS = ("total", "planned", "executed", "unexecuted", "on_time",
                 "delayed", "closed", "open", "canceled")


def default_window(days: int = 240) -> tuple[str, str]:
    """默认统计窗口（转发 cr_caliber，保留本模块的旧调用面）"""
    return cal.default_window(days)


# ---------------- 内部工具 ----------------


def _fetch_dicts(conn, sql: str, params: list) -> list[dict]:
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _num(v) -> int:
    """SUM() 在无行时返回 None，统一成 0。"""
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _rate(num: int, den: int):
    """比率；分母为 0 时返回 None（前端渲染 '—'，不是 0）。"""
    if not den:
        return None
    return round(num / den * 100.0, 1)


def _case(field: str) -> str:
    """SUM(CASE WHEN <谓词> THEN 1 ELSE 0 END) AS <field>"""
    return f"SUM(CASE WHEN {cal.bucket_expr(field)} THEN 1 ELSE 0 END) AS {field}"


def _empty_overview(start_ts: str, end_ts: str, warnings: list[str]) -> dict:
    """出错时的空壳 —— 结构与成功路径完全一致，前端不必判 null。"""
    zero = {f: 0 for f in _COUNT_FIELDS}
    zero.update({"completion_rate": None, "on_time_rate": None,
                 "closure_rate": None, "categories": 0})
    return {
        "meta": {"start": start_ts, "end": end_ts, "table": cal.TABLE,
                 "time_col": cal.TIME_COL, "warnings": warnings},
        "summary": zero, "rows": [], "status_rows": [], "months": [], "sub_categories": [],
    }


# ---------------- 概览 ----------------


def build_overview(start: str, end: str) -> dict:
    """按 change_category 的计划 / 完成情况总览。"""
    start_ts, end_ts = cal.normalize_window(start, end)
    where, params = cal.base_where(start_ts, end_ts)

    # 一条 SQL 拿到每个类别的全部计数，避免 N 个类别打 N 次库
    agg_sql = f"""
        SELECT
            TRIM(COALESCE({cal.CATEGORY_COL}, ''))  AS category,
            COUNT(*)                                AS total,
            {_case("planned")},
            {_case("executed")},
            {_case("unexecuted")},
            {_case("on_time")},
            {_case("delayed")},
            {_case("closed")},
            {_case("open")},
            {_case("canceled")}
        FROM {cal.TABLE}
        WHERE {where}
        GROUP BY 1
        ORDER BY total DESC
    """
    # 状态分布（全量，不分类别）—— 环形图用
    status_sql = f"""
        SELECT TRIM(COALESCE(status, '')) AS status, COUNT(*) AS cnt
        FROM {cal.TABLE} WHERE {where}
        GROUP BY 1 ORDER BY cnt DESC
    """
    # 月度趋势：按登记月分组，看计划量与执行量是否同步
    month_sql = f"""
        SELECT SUBSTR({cal.TIME_COL}, 1, 7)             AS month,
               COUNT(*)                                 AS total,
               {_case("planned")},
               {_case("executed")},
               {_case("closed")}
        FROM {cal.TABLE} WHERE {where}
        GROUP BY 1 ORDER BY 1
    """
    # 子类别 TOP（维度下钻的第二层）
    sub_sql = f"""
        SELECT TRIM(COALESCE({cal.CATEGORY_COL}, ''))   AS category,
               TRIM(COALESCE(sub_category, ''))         AS sub_category,
               COUNT(*)                                 AS total,
               {_case("executed")}
        FROM {cal.TABLE} WHERE {where}
        GROUP BY 1, 2 ORDER BY total DESC
    """

    try:
        conn = get_raw_connection()
    except Exception as exc:  # noqa: BLE001 - 取不到连接要让页面看到原因
        logger.exception("[cr-analysis] 连接失败: %s", exc)
        return _empty_overview(start_ts, end_ts, [f"数据库连接失败: {exc}"])

    try:
        rows = _merge_categories(_fetch_dicts(conn, agg_sql, params))
        status_rows = _fetch_dicts(conn, status_sql, params)
        for r in status_rows:
            r["status"] = r.get("status") or "(空)"
            r["cnt"] = _num(r.get("cnt"))

        months = _fetch_dicts(conn, month_sql, params)
        for r in months:
            r["month"] = r.get("month") or ""
            for f in ("total", "planned", "executed", "closed"):
                r[f] = _num(r.get(f))

        subs = _fetch_dicts(conn, sub_sql, params)
        for r in subs:
            r["category"] = r.get("category") or cal.UNCATEGORIZED
            r["sub_category"] = r.get("sub_category") or "(未分类)"
            r["total"] = _num(r.get("total"))
            r["executed"] = _num(r.get("executed"))
    except Exception as exc:  # noqa: BLE001
        logger.exception("[cr-analysis] 聚合失败: %s", exc)
        return _empty_overview(start_ts, end_ts, [f"数据查询失败: {exc}"])
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - 关闭失败不影响结果
            pass

    # 汇总：各类别按字段相加，比再打一次库更一致（同一份行数据算出来）
    summary = {f: sum(r[f] for r in rows) for f in _COUNT_FIELDS}
    summary["completion_rate"] = _rate(summary["executed"], summary["planned"])
    summary["on_time_rate"] = _rate(summary["on_time"], summary["executed"])
    summary["closure_rate"] = _rate(summary["closed"], summary["total"])
    summary["categories"] = len(rows)

    warnings: list[str] = []
    if not rows:
        warnings.append("所选时间窗口内没有 CR 记录，请放宽时间范围。")

    return {
        "meta": {
            "start": start_ts, "end": end_ts,
            "table": cal.TABLE, "time_col": cal.TIME_COL,
            "warnings": warnings,
        },
        "summary": summary,
        "rows": rows,
        "status_rows": status_rows,
        "months": months,
        "sub_categories": subs,
    }


def _merge_categories(raw_rows: list[dict]) -> list[dict]:
    """把空类别归一后**二次合并**，再算比率。

    为什么需要这一步：`''` 与 `NULL` 在 GROUP BY 里是两类（PG 中 NULL 自成一类），
    归一到 UNCATEGORIZED 后可能出现两行同名；不合并会让同一个类别出现两行，
    且比率分别用各自的分母算，与下钻（按归一后的名字精确匹配）对不上。
    """
    merged: dict[str, dict] = {}
    for r in raw_rows:
        key = r.get("category") or cal.UNCATEGORIZED
        tgt = merged.setdefault(key, {"category": key, **{f: 0 for f in _COUNT_FIELDS}})
        for f in _COUNT_FIELDS:
            tgt[f] += _num(r.get(f))

    out = []
    for r in merged.values():
        r["completion_rate"] = _rate(r["executed"], r["planned"])
        r["on_time_rate"] = _rate(r["on_time"], r["executed"])
        r["closure_rate"] = _rate(r["closed"], r["total"])
        out.append(r)
    out.sort(key=lambda r: (-r["total"], r["category"]))
    return out


# ---------------- 下钻 ----------------


def build_drilldown(start: str, end: str, metric: str, category: str = "",
                    sub_category: str = "", month: str = "",
                    limit: int = MAX_DETAIL_ROWS) -> dict:
    """下钻明细。

    metric 决定筛选哪一批（见 `cr_caliber.bucket_expr`），category /
    sub_category / month 是**叠加**在上面的维度过滤，与被点的那张卡片的
    维度完全对应。

    ⚠️ metric 的谓词与 `build_overview` 的 SUM(CASE ...) 是同一份表达式 ——
    这是「卡片数字 == 明细行数」的唯一保证。
    """
    start_ts, end_ts = cal.normalize_window(start, end)

    def _shell(warnings: list[str], total: int = 0) -> dict:
        return {
            "meta": {"start": start_ts, "end": end_ts, "metric": metric,
                     "category": category, "sub_category": sub_category,
                     "month": month, "warnings": warnings},
            "metric": metric, "category": category, "sub_category": sub_category,
            "month": month, "total": total, "truncated": False,
            "rows": [], "columns": list(cal.DETAIL_COLUMNS),
        }

    where, params = cal.base_where(start_ts, end_ts, category)

    predicate = cal.bucket_expr(metric)
    if predicate is None:
        return _shell([f"未知的下钻指标: {metric}"])
    if predicate != "1=1":
        where = f"{where} AND {predicate}"

    if sub_category:
        where = f"{where} AND TRIM(COALESCE(sub_category,'')) = ?"
        params.append(sub_category)

    if month:
        # month 是 'YYYY-MM'，与 TIME_COL 的 'YYYY-MM-DD HH:MM:SS' 做前缀匹配。
        # 用 >= / < 而不是 LIKE：LIKE 必须把通配符放进参数值（PG 包装层会转义 %），
        # 而范围比较更直白且能用上索引。
        if len(month) != 7 or month[4] != "-":
            return _shell([f"月份格式非法: {month}"])
        where = f"{where} AND {cal.TIME_COL} >= ? AND {cal.TIME_COL} < ?"
        params.extend([f"{month}-01 00:00:00", f"{month}-32 00:00:00"])

    limit = max(1, min(int(limit or MAX_DETAIL_ROWS), MAX_DETAIL_ROWS))

    count_sql = f"SELECT COUNT(*) FROM {cal.TABLE} WHERE {where}"
    detail_sql = (
        f"SELECT {', '.join(cal.DETAIL_COLUMNS)} FROM {cal.TABLE} WHERE {where} "
        f"ORDER BY {cal.TIME_COL} DESC, change_request_id DESC LIMIT ?"
    )

    try:
        conn = get_raw_connection()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[cr-analysis] 下钻连接失败: %s", exc)
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
        logger.exception("[cr-analysis] 下钻查询失败: %s", exc)
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
    """筛选项：可选类别、子类别与数据时间范围。

    类别与子类别从**全表**取（不受时间窗口限制），否则用户缩小窗口后
    下拉框会跟着变空，无法再把范围改回去。
    """
    default_start, default_end = cal.default_window()
    out = {
        "categories": [], "sub_categories": [], "statuses": [],
        "default_start": default_start, "default_end": default_end,
        "min_time": "", "max_time": "", "row_count": 0,
    }
    try:
        conn = get_raw_connection()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cr-analysis] filters 连接失败: %s", exc)
        return out

    def _distinct(sql: str) -> list[str]:
        cur = conn.cursor()
        cur.execute(sql)
        return [r[0] for r in cur.fetchall()]

    try:
        not_blank = cal.not_blank
        out["categories"] = _distinct(f"""
            SELECT DISTINCT TRIM(COALESCE({cal.CATEGORY_COL}, '')) FROM {cal.TABLE}
            WHERE {not_blank(cal.CATEGORY_COL)} ORDER BY 1
        """)
        out["sub_categories"] = _distinct(f"""
            SELECT DISTINCT TRIM(COALESCE(sub_category, '')) FROM {cal.TABLE}
            WHERE {not_blank('sub_category')} ORDER BY 1
        """)
        out["statuses"] = _distinct(f"""
            SELECT DISTINCT TRIM(COALESCE(status, '')) FROM {cal.TABLE}
            WHERE {not_blank('status')} ORDER BY 1
        """)

        cur = conn.cursor()
        cur.execute(f"""
            SELECT COUNT(*), MIN({cal.TIME_COL}), MAX({cal.TIME_COL}) FROM {cal.TABLE}
            WHERE {not_blank(cal.TIME_COL)}
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
        logger.warning("[cr-analysis] filters 查询失败: %s", exc)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    return out
