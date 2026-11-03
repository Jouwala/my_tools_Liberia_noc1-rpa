# -*- coding: utf-8 -*-
"""县（Province/County）维度可用率看板 —— **对外接口层**。

=========================== 对外接口 ===========================

    get_options()                 可选月份 / 县列表 / 阈值 / 数据截至
    build_matrix(month, period, value, threshold)
                                   县 × 制式矩阵 + 环比 + 汇总
    build_trend(month, period, value, county, threshold)
                                   某县（或全网）三制式走势
    get_drilldown(level, ...)     level=county_sites / site_daily / tt

=========================== 分层 ===========================

    avail_county_data.py       取数层：PG 只读 + 缓存 + 周期边界
    avail_county_aggregate.py  聚合层：纯计算，**口径都在这里**
    avail_county_service.py    本文件：编排（取数 -> 聚合 -> 拼装响应）
    routers/avail_county.py    HTTP 层

**口径不要在本文件里重写一遍** —— 聚合口径的唯一真相源是
`avail_county_aggregate.py` 顶部的说明。

=========================== 数据源（详见 avail_county_data.py）===========================

    站点主数据：主库 `eflow_site` 的 `province_county`（**县**，不是 `region` 大区）
    可用率：本地 PG 的 UME MS SLA 站点级日表三张（2G / 3G / 4G，只读）
    站点关联：**按站点名**（PG 侧 site_id 与主数据对不上）
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.database import get_raw_connection
from backend.services import avail_county_aggregate as agg
from backend.services import avail_county_data as data
from backend.services.site_availability_service import month_days, month_weeks

logger = logging.getLogger("avail_county")

# 单次下钻最多返回的行数（超出时 meta.truncated=True，绝不静默截断）
DRILL_LIMIT = 2000

# 便于外部（路由层）直接引用，不重复定义常量
TECHS = data.TECHS
PERIODS = data.PERIODS
UNMATCHED_KEY = data.UNMATCHED_KEY
DEFAULT_THRESHOLD = data.DEFAULT_THRESHOLD


def _tech_cells(cur: Dict[str, Dict[str, Any]],
                prv: Dict[str, Dict[str, Any]],
                county: str,
                techs: List[str],
                threshold: float) -> Dict[str, Any]:
    """某一行（一个县）的三制式单元格载荷。

    `cur` / `prv` 的形状是 {制式: {县: 单元格}}，所以必须按**县**取出该县那一格，
    整张映射直接传进去会拿到「所有县」而不是「这个县」——
    那样每行都会显示成 `—`，而汇总行却有数（口径自相矛盾）。
    """
    return {
        tech: agg.cell_payload(
            (cur.get(tech) or {}).get(county),
            (prv.get(tech) or {}).get(county),
            threshold,
        )
        for tech in techs
    }


def build_matrix(month: str, period: str = "day", value: str = "",
                 threshold: float = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """县 × 制式矩阵（页面的主表）。"""
    t0 = time.time()
    if period not in PERIODS:
        period = "day"
    days_all = month_days(month)
    latest_day = data.latest_day_with_data(month)
    start_day, end_day, days, resolved = data.period_bounds(
        month, period, value, latest_day)
    prev_days = data.prev_period_days(period, start_day, end_day)

    # 取数范围：覆盖本期 + 上一期（环比）
    loaded = data.load_month_data(data.load_start_day(start_day), end_day)

    warnings: List[str] = []
    if loaded.get("missing_tables"):
        warnings.append("kpi_tables_missing")

    counties = data.load_counties()
    county_order = [c["county"] for c in counties]

    # 各制式的县聚合（本期 / 上一期）
    cur: Dict[str, Dict[str, Dict[str, Any]]] = {}
    prv: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for tech in TECHS:
        cur[tech] = agg.county_cells(loaded, tech, days, threshold)
        prv[tech] = agg.county_cells(loaded, tech, prev_days, threshold)
        um = agg.unmatched_cell(loaded, tech, days, threshold)
        if um:
            cur[tech][UNMATCHED_KEY] = um
            ump = agg.unmatched_cell(loaded, tech, prev_days, threshold)
            if ump:
                prv[tech][UNMATCHED_KEY] = ump

    rows: List[Dict[str, Any]] = []
    for county in county_order:
        rows.append({
            "county": county,
            "region": agg.county_region(county, loaded),
            "site_total": next((c["site_count"] for c in counties
                                if c["county"] == county), 0),
            "cells": _tech_cells(cur, prv, county, list(TECHS), threshold),
        })

    # 未归属行（放最后）
    has_unmatched = any(UNMATCHED_KEY in cur.get(t, {}) for t in TECHS)
    if has_unmatched:
        rows.append({
            "county": UNMATCHED_KEY,
            "region": "",
            "site_total": sum((cur[t].get(UNMATCHED_KEY) or {}).get("sites", 0)
                              for t in TECHS),
            "cells": _tech_cells(cur, prv, UNMATCHED_KEY, list(TECHS), threshold),
        })

    summary = agg.summary_by_tech(cur, TECHS, county_order, threshold)

    # 覆盖天数（本期内有数据的日历天数，按制式取并集）
    covered = agg.covered_days(loaded, TECHS, days)
    # 本月一共有几天有数据（页面提示用：让「本月只同步了 1 天」看得见）
    month_covered = agg.covered_days(loaded, TECHS, days_all)

    # 口径类警告（黄色）：与失败类（红色）区分 —— 前端 warnKey/isErrorWarn 据此着色
    if has_unmatched:
        warnings.append("unmatched_sites")
    if len(month_covered) < len(days_all):
        warnings.append("limited_coverage")
    if not covered or all(
        (cur.get(t, {}).get(c, {}).get("availability") is None)
        for t in TECHS for c in county_order
    ):
        warnings.append("no_data_for_period")

    return {
        "meta": {
            "month": month,
            "period": period,
            "value": resolved,
            "start_day": start_day,
            "end_day": end_day,
            "prev_days": prev_days,
            "days": days,
            "threshold": threshold,
            "counties": county_order,
            "techs": list(TECHS),
            "data_through": loaded.get("data_through", ""),
            "covered_days": covered,
            "month_covered_days": month_covered,
            "month_covered_count": len(month_covered),
            "month_day_count": len(days_all),
            "latest_day": latest_day,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_ms": int((time.time() - t0) * 1000),
            "warnings": warnings,
            "has_unmatched": has_unmatched,
        },
        "summary": {
            "by_tech": summary,
            "county_count": len(county_order),
        },
        "rows": rows,
    }


def build_trend(month: str, period: str = "day", value: str = "",
                county: str = "",
                threshold: float = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """某县（或全网）在**本月**内的 2G/3G/4G 走势。

    曲线上的每个点都可下钻 —— 点开就是该点自己那一期的明细。
    """
    if period not in PERIODS:
        period = "day"
    days_all = month_days(month)
    loaded = data.load_month_data(
        data.load_start_day(days_all[0]), days_all[-1])

    # 本月内的期序列
    if period == "day":
        categories = list(days_all)
        buckets = [[d] for d in days_all]
    else:
        weeks = month_weeks(month)
        categories = [w["key"] for w in weeks]
        buckets = [list(w["days"]) for w in weeks]

    series: List[Dict[str, Any]] = []
    for tech in TECHS:
        vals: List[float | None] = []
        sites: List[int] = []
        below: List[int] = []
        for days in buckets:
            cells = agg.county_cells(loaded, tech, days, threshold)
            if county:
                c = cells.get(county) or {}
                vals.append(c.get("availability"))
                sites.append(c.get("sites", 0))
                below.append(c.get("below_sites", 0))
            else:
                # 全网：所有县的有值站点等权平均
                allv = [c["availability"] for c in cells.values()
                        if c.get("availability") is not None]
                vals.append(agg.avg(allv))
                sites.append(sum(c.get("sites", 0) for c in cells.values()))
                below.append(sum(c.get("below_sites", 0) for c in cells.values()))
        series.append({
            "key": tech,
            "values": vals,
            "numerators": sites,
            "denominators": sites,
            "overall": agg.avg([v for v in vals if v is not None]),
            "below_periods": sum(1 for v in vals if v is not None and v < threshold),
        })

    return {
        "meta": {
            "month": month,
            "period": period,
            "county": county,
            "threshold": threshold,
            "points": len(categories),
            "data_through": loaded.get("data_through", ""),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "warnings": ["kpi_tables_missing"] if loaded.get("missing_tables") else [],
        },
        "categories": categories,
        "series": series,
    }


def get_options() -> Dict[str, Any]:
    """页面选项：可选月份 / 县清单 / 阈值 / 数据截至。"""
    months = data.data_months()
    cur = data.current_month()
    if cur not in months:
        cur = months[-1] if months else cur
    counties = data.load_counties()
    warnings: List[str] = []
    data_through = ""
    latest_day = ""
    if months:
        try:
            latest_day = data.latest_day_with_data(cur)
            loaded = data.load_month_data(month_days(cur)[0], month_days(cur)[-1])
            data_through = loaded.get("data_through", "")
            if loaded.get("missing_tables"):
                warnings.append("kpi_tables_missing")
        except Exception as e:
            logger.warning("[avail-county] 读取选项失败: %s", e)
    else:
        warnings.append("kpi_tables_missing")
    return {
        "months": months or [cur],
        "current_month": cur,
        "counties": counties,
        "techs": list(TECHS),
        "threshold": DEFAULT_THRESHOLD,
        "data_through": data_through,
        "latest_day": latest_day,
        "warnings": warnings,
    }


# ============ 下钻 ============

def get_drilldown(level: str, month: str, period: str = "day", value: str = "",
                  county: str = "", tech: str = "",
                  threshold: float = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """下钻明细。

    level=county_sites  某县某制式在本期的**站点级**明细（含每日值）
    level=site_daily    某站点在本期内的**逐日**明细（2G/3G/4G 三列）
    level=tt            某县（或某站点）本期的 **TT 工单**明细

    WHERE 与概览端点**完全一致**：同一时间字段、同一精确匹配，
    否则「表格里的数字」与「下钻的行数」对不上（AGENTS.md 第三节 1b）。
    """
    if period not in PERIODS:
        period = "day"
    if tech and tech not in TECHS:
        tech = ""
    start_day, end_day, days, resolved = data.period_bounds(
        month, period, value, data.latest_day_with_data(month))
    loaded = data.load_month_data(data.load_start_day(start_day), end_day)
    sites = loaded["sites"]

    warnings: List[str] = []
    if loaded.get("missing_tables"):
        warnings.append("kpi_tables_missing")

    # ---- 站点明细 ----
    if level == "county_sites":
        by_site = loaded["by_tech"].get(tech) or {}
        rows: List[Dict[str, Any]] = []
        for key, meta in sites.items():
            if county and meta["county"] != county:
                continue
            sd = by_site.get(key) or {}
            vals = [sd[d] for d in days if d in sd]
            if not vals:
                continue
            av = agg.avg(vals)
            rows.append({
                "site_key": key,
                "site_id": meta["site_id"],
                "site_name": meta["site_name"],
                "county": meta["county"],
                "region": meta["region"],
                "site_type": meta["site_type"],
                "network_type": meta["network_type"],
                "availability": av,
                "days_with_data": len(vals),
                "daily": {d: sd[d] for d in days if d in sd},
                "below": av < threshold,
            })
        rows.sort(key=lambda r: r["availability"])
        total = len(rows)
        return {
            "meta": {
                "level": level, "period": period, "value": resolved,
                "county": county, "tech": tech, "start_day": start_day,
                "end_day": end_day, "total": total,
                "returned": min(total, DRILL_LIMIT),
                "truncated": total > DRILL_LIMIT,
                "threshold": threshold, "warnings": warnings,
            },
            "rows": rows[:DRILL_LIMIT],
        }

    # ---- 站点逐日明细 ----
    if level == "site_daily":
        meta = sites.get(county) or {}   # county 传的是 site_key
        if not meta:
            return {
                "meta": {"level": level, "period": period, "value": resolved,
                         "total": 0, "returned": 0, "truncated": False,
                         "warnings": warnings + ["site_not_found"]},
                "rows": [],
            }
        rows = []
        for d in days:
            row: Dict[str, Any] = {"day": d}
            any_val = False
            for tk in TECHS:
                v = (loaded["by_tech"].get(tk) or {}).get(county, {}).get(d)
                row[tk] = v
                if v is not None:
                    any_val = True
            if any_val:
                rows.append(row)
        return {
            "meta": {
                "level": level, "period": period, "value": resolved,
                "site_key": county, "site_id": meta["site_id"],
                "site_name": meta["site_name"], "county": meta["county"],
                "region": meta["region"],
                "start_day": start_day, "end_day": end_day,
                "total": len(rows), "returned": len(rows), "truncated": False,
                "threshold": threshold, "warnings": warnings,
            },
            "rows": rows,
        }

    # ---- TT 工单 ----
    if level == "tt":
        # `county` 可能是**县名**，也可能是**站点 key**（用户从站点明细点进来时）。
        # TT 侧按站点 id 关联站点主数据，所以先归一成「站点 id 集合」再查，
        # 否则把站点 key 当县名去匹配 province_county 会一条都查不到（表现是空表）。
        site_ids = _resolve_site_ids(sites, county)
        tt = _load_tt(month, start_day, end_day, county, site_ids)
        total = len(tt)
        return {
            "meta": {
                "level": level, "period": period, "value": resolved,
                "county": county, "start_day": start_day, "end_day": end_day,
                "total": total, "returned": min(total, DRILL_LIMIT),
                "truncated": total > DRILL_LIMIT,
                "warnings": warnings,
            },
            "rows": tt[:DRILL_LIMIT],
        }

    return {
        "meta": {"level": level, "period": period, "value": resolved,
                 "total": 0, "returned": 0, "truncated": False,
                 "warnings": warnings + ["unknown_level"]},
        "rows": [],
    }


TT_COLUMNS = [
    "tt_no", "title", "status", "ticket_severity", "site_id", "site_name",
    "site_outage", "current_handler", "root_cause", "alarm_occur_time",
    "created_time", "fault_duration_time", "whether_impacted_service",
    "impacted_service", "col_2g_down_site_count", "col_3g_down_site_count",
    "col_4g_down_site_count",
]


def _resolve_site_ids(sites: Dict[str, Any], selector: str) -> List[str]:
    """把下钻选择器解析成**站点 id 列表**。

    选择器可能是：
        · 县名（如 `Montserrado`）  -> 该县全部站点
        · 站点 key（规范化站点名） -> 该站点本身
        · 空（= 全网）              -> 空列表，表示「不按站点过滤」

    返回空列表有两种含义（全网 / 未匹配到），由调用方结合上下文区分：
    未匹配到时上层会给出空结果，但**不会**误把别的县的工单带出来。
    """
    if not selector:
        return []
    # 命中站点 key（用户从站点明细点进来）
    meta = sites.get(selector)
    if meta:
        return [meta["site_id"]] if meta.get("site_id") else []
    # 否则按县名展开
    out: List[str] = []
    for key, m in sites.items():
        if m.get("county") == selector and m.get("site_id"):
            out.append(m["site_id"])
    return out


def _load_tt(month: str, start_day: str, end_day: str,
             county: str = "",
             site_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """本期 TT 工单（按站点 id 关联 eflow_site 取县归属）。

    归属口径：`eflow_tt.site_id` 精确匹配 `eflow_site.site_id`
    （实测 2026-10 起 4001 条 TT **100% 命中**，比按名字匹配可靠）。

    `site_ids` 非空时按站点 id 精确过滤（从站点明细点进来时用）；
    否则按县名 `county` 过滤。
    """
    ck = f"avail_county:tt:{month}:{start_day}:{end_day}:{county}:{len(site_ids or [])}"
    cached = data.cache_get(ck)
    if cached is not None:
        return cached
    cols = ", ".join('t."%s"' % c for c in TT_COLUMNS)
    sql = (
        'SELECT {cols}, e.pc FROM eflow_tt t '
        'LEFT JOIN (SELECT CAST(site_id AS TEXT) AS sid, MIN(province_county) AS pc '
        'FROM eflow_site GROUP BY 1) e ON e.sid = CAST(t."site_id" AS TEXT) '
        'WHERE t."created_time" >= ? AND t."created_time" <= ?'
    ).format(cols=cols)
    params: List[Any] = [f"{start_day} 00:00:00", f"{end_day} 23:59:59"]
    if site_ids:
        ph = ", ".join("?" for _ in site_ids)
        sql += f' AND CAST(t."site_id" AS TEXT) IN ({ph})'
        params.extend(site_ids)
    elif county:
        sql += ' AND e.pc = ?'
        params.append(county)
    out: List[Dict[str, Any]] = []
    try:
        with get_raw_connection(timeout=60) as conn:
            for r in conn.execute(sql, tuple(params)).fetchall():
                row = {c: r[i] for i, c in enumerate(TT_COLUMNS)}
                row["county"] = r[len(TT_COLUMNS)]
                out.append(row)
    except Exception as e:
        logger.warning("[avail-county] 读取 TT 失败: %s", e)
        return out
    out.sort(key=lambda r: str(r.get("created_time") or ""), reverse=True)
    return data.cache_set(ck, out)
