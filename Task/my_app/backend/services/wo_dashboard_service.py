"""WO 看板的数据计算（page=wo）。

**为什么单独一个模块而不是在 `tt_wo_dashboard.py` 里加分支**：
`page=wo` 要求「版式与 TT 页一模一样，只是数据源换成 eflow_wo」，而 TT&WO 看板
的 overview 是**一次请求同时算 TT 与 WO 两侧**（还要带 WO 的来源/状态/站点信息）。
把两种口径塞进同一个函数会让 `tt_wo_dashboard.py`（已 1135 行）继续膨胀，且
TT 侧的既有行为会被 WO 分支的改动波及 —— 而 TT 页是线上大屏在看的页面。

所以这里**独立计算 WO 侧**，只复用口径函数（`_time_filter` / `_safe_str` /
`_period_label` / `_advanced_site_filters` 等）保证「同一时间字段、同一剔除规则」，
不复制公式。

**与 TT 页的口径对应关系**（WO 页与 TT 页逐项对齐，这是需求）：
  | TT 页（eflow_tt）              | WO 页（eflow_wo）                        |
  | ---                            | ---                                      |
  | 汇总：TT 总数                  | 汇总：WO 总数                            |
  | 统计·严重度 = ticket_severity  | 统计·严重度 = w.ticket_severity          |
  | 统计·SLA 状态 = t.sla_status   | 统计·SLA 状态 = **关联 eflow_tt 的 sla_status**（WO 表本身没有该字段） |
  | 统计·状态 = t.status           | 统计·状态 = w.status                     |
  | MTTR = clear − occur           | MTTR = clear − occur（同一公式，取 WO 行） |

**SLA 为什么 JOIN eflow_tt**：`eflow_wo` 没有 `sla_status` 列（实测 341 列里无此列），
SLA 是 TT 侧的概念（由 TT 的时限规则算出）。业务确认按「从关联的 eflow_tt 取」处理。
JOIN 键是 `wo.tt_no = tt.tt_no`（实测 14111 行 WO 里 13572 行有 tt_no，
其中 13571 行能对上 TT，覆盖率 99.99%）。JOIN 不上的 WO 行不会丢 ——
用 LEFT JOIN，其 SLA 计入 `Unknown`，保证「统计卡片之和 = WO 总数」。
"""
from __future__ import annotations

import logging
from datetime import datetime

from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names
from backend.routers.tt_wo_dashboard import (
    _EXCLUDED_SLA_STATUSES,
    _MTTR_GRANULARITIES,
    _UNKNOWN_EXCLUDED_DIMENSIONS,
    _advanced_site_filters,
    _detect_schema,
    _is_excluded_ticket_severity,
    _mttr_series,
    _parse_adv,
    _period_label,
    _safe_str,
    _stat_key,
    _ticket_severity_key,
    _time_filter,
)

log = logging.getLogger(__name__)


def wo_overview(
    time_start: str | None = None,
    time_end: str | None = None,
    region: str | None = None,
    adv: str | None = None,
) -> dict:
    """WO 看板 overview：版式与 TT 页一致，数据全部来自 eflow_wo。

    过滤口径与 `page=tt` 逐条对应（同一 `alarm_occur_time`、同一站点 JOIN、
    同一高级过滤）。**没有 owner（ZTE/3rd）过滤** —— 该归属的定义就是
    「TT 的 wo_no 是否非空」，在 WO 表上没有意义（WO 表每行本身就是一个 WO）。
    """
    S = _detect_schema()
    adv_filters = _parse_adv(adv)

    with get_raw_connection() as conn:
        if not S["has_wo"]:
            # 没有 eflow_wo 表时返回空结构而不是 500，前端显示空态
            return _empty_payload(time_start, time_end, region, adv_filters)

        wo_tf, wo_tp = _time_filter("w", time_start, time_end)

        # 站点 JOIN（区域 + 高级过滤），与 TT 侧同一套白名单列校验
        region_join = region_where = ""
        region_params: list = []
        if S["site_table"] and (region or adv_filters):
            sjf = S["site_join_field"]
            region_join = f"JOIN {S['site_table']} ms ON w.{sjf} = CAST(ms.{sjf} AS TEXT)"
            if region:
                region_where += " AND ms.region = ?"
                region_params.append(region)
            adv_where, adv_params = _advanced_site_filters(adv_filters, S)
            region_where += adv_where
            region_params += adv_params

        where = f"WHERE {wo_tf}{region_where}" if wo_tf else f"WHERE 1=1{region_where}"
        params = wo_tp + region_params

        # 一次拉全所需列，避免对同一批行反复查库（TT 侧同思路）。
        # LEFT JOIN eflow_tt 只为取 sla_status；tt_no 是实测唯一可用的关联键。
        has_tt = "eflow_tt" in set(list_table_names(conn))
        sla_expr = "t.sla_status" if has_tt else "NULL"
        tt_join = "LEFT JOIN eflow_tt t ON t.tt_no = w.tt_no" if has_tt else ""

        rows = conn.execute(f"""
            SELECT w.ticket_severity, {sla_expr}, w.status, w.domain,
                   w.wo_no, w.alarm_occur_time, w.alarm_clear_time, w.{S['site_join_field']},
                   w.rc_main_category, w.rc_sub_category
            FROM eflow_wo w {tt_join} {region_join} {where}
        """, params).fetchall()

        wo_total = len(rows)
        wo_no_set = set()
        severity, sla_stats, status_stats, domain_stats = {}, {}, {}, {}
        rc_main, rc_sub = {}, {}
        # {粒度: {级别: {桶: [时长]}}} 与 {粒度: {级别: {桶: 单数}}}，与 TT 侧同名同义
        period_by_sev: dict[str, dict[str, dict[str, list]]] = {g: {} for g in _MTTR_GRANULARITIES}
        total_by_sev: dict[str, dict[str, dict[str, int]]] = {g: {} for g in _MTTR_GRANULARITIES}
        site_id_set = set()

        for r in rows:
            sev = _ticket_severity_key(r[0])
            if sev is not None:
                severity[sev] = severity.get(sev, 0) + 1
            # SLA 取自关联 TT。2026-09-29 业务要求：JOIN 不上或 TT 未算 SLA 的
            # 行不再归并为 'Unknown' 单独成类，直接不计入该维度统计
            # （与 Ticket Severity 的排除口径一致）。
            sla_val = _stat_key(r[1], _EXCLUDED_SLA_STATUSES, join_empty=True)
            if sla_val is not None:
                sla_stats[sla_val] = sla_stats.get(sla_val, 0) + 1
            st = _safe_str(r[2], "")
            if st:
                status_stats[st] = status_stats.get(st, 0) + 1
            domain_stats[_safe_str(r[3])] = domain_stats.get(_safe_str(r[3]), 0) + 1
            # 根因取自 WO 表自身的 rc_main_category / rc_sub_category
            # （TT 侧用的是 root_cause / sub_root_cause，字段名不同但语义对应）
            rc_main[_safe_str(r[8])] = rc_main.get(_safe_str(r[8]), 0) + 1
            rc_sub[_safe_str(r[9])] = rc_sub.get(_safe_str(r[9]), 0) + 1
            if r[4]:
                wo_no_set.add(r[4])

            if r[5]:
                ts_occ = str(r[5])
                # 与 TT 侧同规则：ticket_severity 为空的行不进任何级别序列
                sv = _ticket_severity_key(r[0]) or ""
                buckets = {}
                for gran in _MTTR_GRANULARITIES:
                    lbl = _period_label(ts_occ, gran)
                    if lbl:
                        buckets[gran] = lbl
                if buckets:
                    if sv:
                        for gran, lbl in buckets.items():
                            by_lbl = total_by_sev[gran].setdefault(sv, {})
                            by_lbl[lbl] = by_lbl.get(lbl, 0) + 1
                    # MTTR 有效区间与 TT 完全一致：0 < dur < 43200 分钟（30 天）
                    if r[6]:
                        try:
                            t1 = datetime.strptime(ts_occ[:19], "%Y-%m-%d %H:%M:%S")
                            t2 = datetime.strptime(str(r[6])[:19], "%Y-%m-%d %H:%M:%S")
                            dur_min = (t2 - t1).total_seconds() / 60
                        except Exception:
                            log.warning("[wo-dashboard] 时长解析失败，已跳过该行", exc_info=True)
                            dur_min = None
                        if dur_min is not None and 0 < dur_min < 43200:
                            for gran, lbl in buckets.items():
                                if sv:
                                    period_by_sev[gran].setdefault(sv, {}).setdefault(lbl, []).append(dur_min)
            if r[7]:
                site_id_set.add(r[7])

        status_stats = dict(sorted(status_stats.items(), key=lambda x: x[1], reverse=True))
        domain_stats = dict(sorted(domain_stats.items(), key=lambda x: x[1], reverse=True))
        # 三档粒度的分级 MTTR 序列（前端日/周/月三个页签各读一份）
        mttr_series = {g: _mttr_series(period_by_sev[g], total_by_sev[g]) for g in _MTTR_GRANULARITIES}
        # 兼容字段（前端 MTTR 图的兜底路径），与 mttr_series["week"] 同源不会分叉
        mttr_weekly_by_severity = {
            sv: [
                {"week": it["period"], "mttr": it["mttr"], "count": it["count"], "total": it["total"]}
                for it in items
            ]
            for sv, items in mttr_series["week"].items()
        }

        site_stats = _site_stats(conn, site_id_set, S)
        regions, filter_options = _filter_options(conn, S)
        conn.close()

        return {
            "filters": {
                "regions": regions,
                "time_start": time_start,
                "time_end": time_end,
                "region": region,
                "adv": adv_filters,
                "filter_fields": S["site_filter_fields"],
                "filter_options": filter_options,
            },
            "summary": {"wo_total": wo_total, "wo_no_count": len(wo_no_set)},
            # 键名沿用 tt_stats，前端 TT / WO 两页共用同一个渲染器 ——
            # 「严重度 / SLA 状态 / 状态」三维在 WO 侧就是这三个字段。
            "wo_stats_dims": {
                "ticket_severity": severity,
                "sla_status": sla_stats,
                "status": status_stats,
            },
            "mttr_series": mttr_series,
            "mttr_granularities": list(_MTTR_GRANULARITIES),
            "mttr_weekly_by_severity": mttr_weekly_by_severity,
            "domain_stats": domain_stats,
            "site_stats": site_stats,
            # 根因：WO 表里叫 rc_main_category / rc_sub_category。复用 TT 侧的
            # root_cause.main / .sub 结构，前端两张饼图不必分叉。
            "root_cause": {
                "main": dict(sorted(rc_main.items(), key=lambda x: x[1], reverse=True)),
                "sub": dict(sorted(rc_sub.items(), key=lambda x: x[1], reverse=True)),
            },
            # WO 页不出「按来源统计 / 按状态统计」区块（与页首统计卡片重复），
            # 但键保留为合法空值，前端逻辑无需特判
            "wo_stats": {},
        }


def _site_stats(conn, site_id_set: set, S: dict) -> dict:
    """站点维度统计：与 TT 侧同表同字段同 Top-15 截断。"""
    out: dict = {}
    if not site_id_set or not S["site_table"]:
        return out
    placeholders = ",".join("?" * len(site_id_set))
    select_fields = ", ".join(S["site_stat_fields"].values())
    if not select_fields:
        return out
    try:
        rows = conn.execute(f"""
            SELECT {select_fields}
            FROM {S['site_table']}
            WHERE CAST({S['site_join_field']} AS TEXT) IN ({placeholders})
        """, list(site_id_set)).fetchall()
    except Exception:
        log.warning("[wo-dashboard] 站点统计查询失败，返回空", exc_info=True)
        return out
    keys = list(S["site_stat_fields"].keys())
    for r in rows:
        for i, key in enumerate(keys):
            val = r[i]
            if val and str(val).strip() and str(val) != "None":
                out.setdefault(key, {})
                out[key][val] = out[key].get(val, 0) + 1
    for k in out:
        out[k] = dict(sorted(out[k].items(), key=lambda x: x[1], reverse=True)[:15])
    return out


def _filter_options(conn, S: dict) -> tuple[list, dict]:
    """区域下拉与高级过滤候选值；与 TT 侧同源同限（每列最多 200 个）。"""
    regions: list = []
    filter_options: dict = {}
    if not S["site_table"]:
        return regions, filter_options
    try:
        regions = [r[0] for r in conn.execute(
            f"SELECT DISTINCT region FROM {S['site_table']} "
            f"WHERE region IS NOT NULL AND region != '' ORDER BY region"
        ).fetchall()]
    except Exception:
        log.warning("[wo-dashboard] region 候选查询失败", exc_info=True)
    for col in S["site_filter_fields"]:
        try:
            rows = conn.execute(
                f"""SELECT DISTINCT {col} FROM {S['site_table']}
                    WHERE {col} IS NOT NULL AND {col} != '' AND {col} != 'None'
                    ORDER BY {col} LIMIT 200"""
            ).fetchall()
            vals = [str(r[0]) for r in rows]
            if vals:
                filter_options[col] = vals
        except Exception:
            log.warning("[wo-dashboard] 高级过滤候选列 %s 查询失败，已跳过", col, exc_info=True)
    return regions, filter_options


def wo_drilldown(
    dimension: str,
    value: str | None = None,
    time_start: str | None = None,
    time_end: str | None = None,
    region: str | None = None,
    adv: str | None = None,
) -> dict:
    """WO 明细下钻。

    **WHERE 必须与 :func:`wo_overview` 逐条一致**（同一 `alarm_occur_time`、
    同一站点 JOIN、同一高级过滤），否则「卡片上的数字」与「下钻的行数」对不上，
    用户会当成 bug（AGENTS.md 第三节第 1b 条）。
    """
    S = _detect_schema()
    adv_filters = _parse_adv(adv)

    with get_raw_connection() as conn:
        if not S["has_wo"]:
            conn.close()
            return {"title": f"WO - {dimension}", "count": 0, "data": []}

        wo_tf, wo_tp = _time_filter("w", time_start, time_end)
        sjf = S["site_join_field"]

        region_join = region_where = ""
        region_params: list = []
        if S["site_table"] and (region or adv_filters):
            region_join = f"JOIN {S['site_table']} ms ON w.{sjf} = CAST(ms.{sjf} AS TEXT)"
            if region:
                region_where += " AND ms.region = ?"
                region_params.append(region)
            adv_where, adv_params = _advanced_site_filters(adv_filters, S)
            region_where += adv_where
            region_params += adv_params

        where = f"WHERE {wo_tf}{region_where}" if wo_tf else f"WHERE 1=1{region_where}"
        params = wo_tp + region_params

        has_tt = "eflow_tt" in set(list_table_names(conn))
        tt_join = "LEFT JOIN eflow_tt t ON t.tt_no = w.tt_no" if has_tt else ""
        sla_expr = "t.sla_status" if has_tt else "NULL"

        # 时间粒度维度（day/week/month）：与 MTTR 图的三个页签同源同桶，
        # 否则点日图上的点会下钻出与该点对不上的行数
        if dimension in _MTTR_GRANULARITIES and value:
            rows = conn.execute(f"""
                SELECT w.wo_no, w.tt_no, w.title, w.status, {sla_expr}, w.ticket_severity,
                       w.alarm_occur_time, w.alarm_clear_time, w.source, w.domain,
                       w.creator, w.created_time
                FROM eflow_wo w {tt_join} {region_join}
                {where} AND w.alarm_occur_time IS NOT NULL
                ORDER BY w.alarm_occur_time DESC
            """, params).fetchall()
            cols = ["wo_no", "tt_no", "title", "status", "sla_status", "ticket_severity",
                    "alarm_occur_time", "alarm_clear_time", "source", "domain",
                    "creator", "created_time"]
            data = [
                dict(zip(cols, r)) for r in rows
                if _period_label(str(dict(zip(cols, r)).get("alarm_occur_time") or ""), dimension) == value
            ]
            conn.close()
            return {"title": f"WO - {dimension.title()}: {value}", "count": len(data), "data": data}

        # 站点维度：先在站点表里把该取值对应的站点 ID 找出来（与 TT 侧同写法，
        # 精确匹配不用 LIKE），再按下钻维度过滤 WO
        if dimension in S["site_stat_fields"] and value:
            site_field = S["site_stat_fields"][dimension]
            if S["site_table"]:
                site_ids = conn.execute(f"""
                    SELECT {sjf} FROM {S['site_table']}
                    WHERE {site_field} = ? AND {sjf} IS NOT NULL
                """, [value]).fetchall()
                id_list = [str(s[0]) for s in site_ids]
                if not id_list:
                    conn.close()
                    return {"title": f"WO - {dimension}: {value}", "count": 0, "data": []}
                placeholders = ",".join("?" * len(id_list))
                rows = conn.execute(f"""
                    SELECT w.wo_no, w.tt_no, w.title, w.status, {sla_expr}, w.ticket_severity,
                           w.alarm_occur_time, w.alarm_clear_time, w.source, w.domain,
                           w.creator, w.created_time
                    FROM eflow_wo w {tt_join} {region_join}
                    {where} AND w.{sjf} IN ({placeholders})
                    ORDER BY w.alarm_occur_time DESC
                """, params + id_list).fetchall()
                cols = ["wo_no", "tt_no", "title", "status", "sla_status", "ticket_severity",
                        "alarm_occur_time", "alarm_clear_time", "source", "domain",
                        "creator", "created_time"]
                data = [dict(zip(cols, r)) for r in rows]
                conn.close()
                return {"title": f"WO - {dimension}: {value}", "count": len(data), "data": data}

        # 通用维度：严重度 / SLA 状态 / 状态 / 领域 / 根因
        DIM_SQL = {
            "ticket_severity": "w.ticket_severity",
            "sla_status": "t.sla_status",
            "status": "w.status",
            "domain": "w.domain",
            "rc_main": "w.rc_main_category",
            "rc_sub": "w.rc_sub_category",
            "all_wo": None,
        }
        col = DIM_SQL.get(dimension)
        cond = ""
        extra: list = []
        if col and value:
            # 2026-09-29：ticket_severity / sla_status 的 Unknown 已从概览统计中剔除，
            # 下钻必须同步返回空集（口径一致性，见 AGENTS.md 第三节第 1b 条）。
            if dimension in _UNKNOWN_EXCLUDED_DIMENSIONS and _is_excluded_ticket_severity(value):
                conn.close()
                return {"title": f"WO - {dimension}: {value}", "count": 0, "data": []}
            if value == "Unknown":
                # Unknown 是本页对 NULL/空串的归并写法（与 overview 的 _safe_str 一致），
                # 下钻时必须还原成同一批行，否则卡片数字与行数不等
                cond = f" AND ({col} IS NULL OR {col} = '' OR {col} = 'None')"
            else:
                cond = f" AND {col} = ?"
                extra = [value]
        rows = conn.execute(f"""
            SELECT w.wo_no, w.tt_no, w.title, w.status, {sla_expr}, w.ticket_severity,
                   w.alarm_occur_time, w.alarm_clear_time, w.source, w.domain,
                   w.creator, w.created_time
            FROM eflow_wo w {tt_join} {region_join}
            {where}{cond}
            ORDER BY w.alarm_occur_time DESC
        """, params + extra).fetchall()
        cols = ["wo_no", "tt_no", "title", "status", "sla_status", "ticket_severity",
                "alarm_occur_time", "alarm_clear_time", "source", "domain",
                "creator", "created_time"]
        data = [dict(zip(cols, r)) for r in rows]
        conn.close()
        return {"title": f"WO - {dimension}{': ' + value if value else ''}", "count": len(data), "data": data}


def _empty_payload(time_start, time_end, region, adv_filters) -> dict:
    """无 eflow_wo 表时的空结构：让前端走空态而不是错误页。"""
    return {
        "filters": {
            "regions": [], "time_start": time_start, "time_end": time_end,
            "region": region, "adv": adv_filters or {},
            "filter_fields": [], "filter_options": {},
        },
        "summary": {"wo_total": 0, "wo_no_count": 0},
        "wo_stats_dims": {"ticket_severity": {}, "sla_status": {}, "status": {}},
        "mttr_series": {g: {} for g in _MTTR_GRANULARITIES},
        "mttr_granularities": list(_MTTR_GRANULARITIES),
        "mttr_weekly_by_severity": {},
        "domain_stats": {},
        "site_stats": {},
        "wo_stats": {},
        "root_cause": {"main": {}, "sub": {}},
    }
