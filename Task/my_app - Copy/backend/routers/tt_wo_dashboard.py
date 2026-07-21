"""TT&WO Dashboard API - 综合统计看板"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from backend.database import get_raw_connection, DB_PATH

router = APIRouter(prefix="/api/tt-wo-dashboard", tags=["tt-wo-dashboard"])


def _time_filter(prefix: str, time_start: str | None, time_end: str | None) -> tuple[str, list]:
    """构建时间过滤SQL片段, prefix为表别名如't'或'w'"""
    parts = []
    params = []
    f = f"{prefix}.alarm_occur_time"
    if time_start:
        parts.append(f"{f} >= ?")
        params.append(time_start)
    if time_end:
        end_dt = datetime.strptime(time_end, "%Y-%m-%d") + timedelta(days=1)
        parts.append(f"{f} < ?")
        params.append(end_dt.strftime("%Y-%m-%d"))
    return " AND ".join(parts), params


def _safe_str(val, default: str = "Unknown") -> str:
    """将NULL/空/'None'统一转为default"""
    if val is None or str(val).strip() == '' or str(val) == 'None':
        return default
    return str(val)


def _week_label(ts: str) -> str:
    """将时间戳转为 ISO周格式 2026-W26"""
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except Exception:
        return ""


@router.get("/overview")
def tt_wo_dashboard_overview(
    time_start: str = Query(None, description="时间窗口开始 YYYY-MM-DD"),
    time_end: str = Query(None, description="时间窗口结束 YYYY-MM-DD"),
    region: str = Query(None, description="区域筛选"),
):
    """TT&WO Dashboard 综合数据"""
    conn = get_raw_connection()

    # 构建TT/WO时间过滤（带表别名）
    tt_tf, tt_tp = _time_filter("t", time_start, time_end)
    wo_tf, wo_tp = _time_filter("w", time_start, time_end)

    # 区域过滤 JOIN 条件
    region_join = ""
    region_where = ""
    region_params = []
    if region:
        region_join = "JOIN master_site_db ms ON t.site_id = ms.site_id"
        region_where = " AND ms.region = ?"
        region_params = [region]

    region_join_wo = ""
    region_where_wo = ""
    if region:
        region_join_wo = "JOIN master_site_db ms ON w.site_id = ms.site_id"
        region_where_wo = " AND ms.region = ?"

    # TT公共WHERE
    tt_where = f"WHERE {tt_tf}{region_where}" if tt_tf else f"WHERE 1=1{region_where}"
    tt_params = tt_tp + region_params

    # WO公共WHERE
    wo_where = f"WHERE {wo_tf}{region_where_wo}" if wo_tf else f"WHERE 1=1{region_where_wo}"
    wo_params = wo_tp + (region_params if region else [])

    # ========== 1. TT 统计 (单次查询获取所有数据，Python端聚合) ==========
    tt_rows = conn.execute(f"""
        SELECT t.alarm_severity, t.ticket_severity, t.sla_status, t.status, t.domain,
               t.wo_no, t.alarm_occur_time, t.alarm_clear_time, t.site_id
        FROM eflow_tt t {region_join} {tt_where}
    """, tt_params).fetchall()

    tt_total = len(tt_rows)
    wo_no_set = set()
    alarm_sev = {}
    ticket_sev = {}
    sla_stats = {}
    status_stats = {}
    domain_stats = {}
    week_data = {}
    site_id_set = set()

    for r in tt_rows:
        alarm_sev_val = _safe_str(r[0])
        alarm_sev[alarm_sev_val] = alarm_sev.get(alarm_sev_val, 0) + 1

        ticket_sev_val = _safe_str(r[1])
        ticket_sev[ticket_sev_val] = ticket_sev.get(ticket_sev_val, 0) + 1

        sla_val = _safe_str(r[2])
        sla_stats[sla_val] = sla_stats.get(sla_val, 0) + 1

        status_val = _safe_str(r[3], "")
        if status_val:
            status_stats[status_val] = status_stats.get(status_val, 0) + 1

        domain_val = _safe_str(r[4])
        domain_stats[domain_val] = domain_stats.get(domain_val, 0) + 1

        if r[5]:
            wo_no_set.add(r[5])

        # MTTR
        if r[6] and r[7] and r[7] > r[6]:
            try:
                from datetime import datetime as _dt
                t1 = _dt.strptime(str(r[6])[:19], "%Y-%m-%d %H:%M:%S")
                t2 = _dt.strptime(str(r[7])[:19], "%Y-%m-%d %H:%M:%S")
                dur_min = (t2 - t1).total_seconds() / 60
                if 0 < dur_min < 43200:
                    wk = _week_label(str(r[6]))
                    if wk:
                        week_data.setdefault(wk, []).append(dur_min)
            except Exception:
                pass

        if r[8]:
            site_id_set.add(r[8])

    wo_no_stats = len(wo_no_set)
    status_stats = dict(sorted(status_stats.items(), key=lambda x: x[1], reverse=True))
    domain_stats = dict(sorted(domain_stats.items(), key=lambda x: x[1], reverse=True))

    # MTTR weekly
    mttr_weekly = []
    for week in sorted(week_data.keys()):
        vals = week_data[week]
        mttr_weekly.append({"week": week, "mttr": round(sum(vals) / len(vals), 1), "count": len(vals)})

    # ========== 2. WO 统计 (单次查询) ==========
    wo_rows = conn.execute(f"""
        SELECT w.rc_main_category, w.rc_sub_category, w.source, w.status
        FROM eflow_wo w {region_join_wo} {wo_where}
    """, wo_params).fetchall()

    wo_total = len(wo_rows)
    rc_main = {}
    rc_sub = {}
    wo_source_stats = {}
    wo_status_stats = {}

    for r in wo_rows:
        mc = _safe_str(r[0])
        rc_main[mc] = rc_main.get(mc, 0) + 1
        sc = _safe_str(r[1])
        rc_sub[sc] = rc_sub.get(sc, 0) + 1
        src = _safe_str(r[2])
        wo_source_stats[src] = wo_source_stats.get(src, 0) + 1
        st = _safe_str(r[3], "")
        if st:
            wo_status_stats[st] = wo_status_stats.get(st, 0) + 1

    wo_source_stats = dict(sorted(wo_source_stats.items(), key=lambda x: x[1], reverse=True))
    wo_status_stats = dict(sorted(wo_status_stats.items(), key=lambda x: x[1], reverse=True))

    # ========== 3. 站点信息统计 ==========
    power_source_stats = {}
    power_vendor_stats = {}
    fme_stats = {}

    if site_id_set:
        placeholders = ",".join("?" * len(site_id_set))
        site_params = list(site_id_set)
        for r in conn.execute(f"""
            SELECT power_sources, power_vendor, updated_fme_name_new
            FROM master_site_db
            WHERE site_id IN ({placeholders})
        """, site_params).fetchall():
            if r[0] and r[0].strip():
                power_source_stats[r[0]] = power_source_stats.get(r[0], 0) + 1
            if r[1] and r[1].strip():
                power_vendor_stats[r[1]] = power_vendor_stats.get(r[1], 0) + 1
            if r[2] and r[2].strip():
                fme_stats[r[2]] = fme_stats.get(r[2], 0) + 1

    power_source_stats = dict(sorted(power_source_stats.items(), key=lambda x: x[1], reverse=True)[:15])
    power_vendor_stats = dict(sorted(power_vendor_stats.items(), key=lambda x: x[1], reverse=True))
    fme_stats = dict(sorted(fme_stats.items(), key=lambda x: x[1], reverse=True)[:15])

    # ========== 4. 汇总 ==========
    regions = [r[0] for r in conn.execute(
        "SELECT DISTINCT region FROM master_site_db WHERE region IS NOT NULL AND region != '' ORDER BY region"
    ).fetchall()]

    conn.close()

    return {
        "filters": {
            "regions": regions,
            "time_start": time_start,
            "time_end": time_end,
            "region": region,
        },
        "summary": {
            "tt_total": tt_total,
            "wo_total": wo_total,
            "wo_no_count": wo_no_stats,
        },
        "tt_stats": {
            "alarm_severity": alarm_sev,
            "ticket_severity": ticket_sev,
            "sla_status": sla_stats,
            "status": status_stats,
        },
        "mttr_weekly": mttr_weekly,
        "domain_stats": domain_stats,
        "root_cause": {"main": rc_main, "sub": rc_sub},
        "wo_stats": {"source": wo_source_stats, "status": wo_status_stats},
        "site_stats": {
            "power_sources": power_source_stats,
            "power_vendor": power_vendor_stats,
            "maintenance_team": fme_stats,
        },
    }


# TT明细字段 (带表别名避免JOIN歧义)
TT_FIELDS = "t.title, t.ticket_no, t.wo_no, t.site_id, t.site_name, t.status, t.creator, t.ticket_severity, t.alarm_severity, t.sla_status, t.alarm_occur_time, t.alarm_clear_time, t.domain, t.root_cause, t.sub_root_cause"

# WO明细字段 (带表别名)
WO_FIELDS = "w.wo_no, w.tt_no, w.title, w.status, w.creator, w.created_time, w.alarm_occur_time, w.alarm_clear_time, w.source, w.rc_main_category, w.rc_sub_category, w.ticket_severity, w.alarm_severity"

# 维度 → (表类型, SQL条件片段, 字段名)
DIMENSION_MAP = {
    "alarm_severity":  ("tt", "t.alarm_severity = ?",  "alarm_severity"),
    "ticket_severity": ("tt", "t.ticket_severity = ?", "ticket_severity"),
    "sla_status":      ("tt", "t.sla_status = ?",      "sla_status"),
    "status":          ("tt", "t.status = ?",           "status"),
    "domain":          ("tt", "t.domain = ?",           "domain"),
    "rc_main":         ("wo", "w.rc_main_category = ?", "rc_main_category"),
    "rc_sub":          ("wo", "w.rc_sub_category = ?",  "rc_sub_category"),
    "wo_source":       ("wo", "w.source = ?",           "source"),
    "wo_status":       ("wo", "w.status = ?",           "status"),
    "power_sources":   ("site", "power_sources",        "power_sources"),
    "maintenance_team":("site", "updated_fme_name_new", "maintenance_team"),
    "power_vendor":    ("site", "power_vendor",         "power_vendor"),
    "all_tt":          ("tt", None, None),
    "all_wo":          ("wo", None, None),
}


@router.get("/drilldown")
def tt_wo_drilldown(
    type: str = Query("tt", description="tt 或 wo"),
    time_start: str = Query(None),
    time_end: str = Query(None),
    region: str = Query(None),
    dimension: str = Query("all_tt", description="下钻维度"),
    value: str = Query(None, description="维度值"),
):
    """TT/WO 明细下钻查询"""
    conn = get_raw_connection()

    # 时间过滤
    tt_tf, tt_tp = _time_filter("t", time_start, time_end)
    wo_tf, wo_tp = _time_filter("w", time_start, time_end)

    # 区域过滤
    region_join_tt = ""
    region_where_tt = ""
    region_params_tt: list = []
    if region:
        region_join_tt = "JOIN master_site_db ms ON t.site_id = ms.site_id"
        region_where_tt = " AND ms.region = ?"
        region_params_tt = [region]

    region_join_wo = ""
    region_where_wo = ""
    region_params_wo: list = []
    if region:
        region_join_wo = "JOIN master_site_db ms ON w.site_id = ms.site_id"
        region_where_wo = " AND ms.region = ?"
        region_params_wo = [region]

    dim_info = DIMENSION_MAP.get(dimension, ("tt", None, None))
    dim_type = dim_info[0]

    # week 维度特殊处理
    if dimension == "week" and value:
        # 按ISO周过滤: 找出属于该周的所有TT记录
        tt_where = f"WHERE {tt_tf}{region_where_tt}" if tt_tf else f"WHERE 1=1{region_where_tt}"
        tt_params = tt_tp + region_params_tt
        rows = conn.execute(f"""\
            SELECT {TT_FIELDS} FROM eflow_tt t {region_join_tt}
            {tt_where} AND t.alarm_occur_time IS NOT NULL
            ORDER BY t.alarm_occur_time DESC
        """, tt_params).fetchall()
        cols = [c.strip().split('.')[-1] for c in TT_FIELDS.split(",")]
        # 按周过滤
        data = []
        for row in rows:
            d = dict(zip(cols, row))
            w = _week_label(str(d.get("alarm_occur_time") or ""))
            if w == value:
                data.append(d)
        conn.close()
        return {"title": f"TT - Week: {value}", "count": len(data), "data": data}

    # 站点维度特殊处理: 通过 site_id 关联
    if dim_type == "site" and value:
        site_field = dim_info[1]
        # 找出符合条件的site_ids
        site_ids = conn.execute(f"""\
            SELECT site_id FROM master_site_db
            WHERE {site_field} = ? AND site_id IS NOT NULL
        """, [value]).fetchall()
        site_id_list = [str(s[0]) for s in site_ids]
        if not site_id_list:
            conn.close()
            return {"title": f"TT - {dimension}: {value}", "count": 0, "data": []}

        placeholders = ",".join("?" * len(site_id_list))
        tt_where = f"WHERE {tt_tf}{region_where_tt}" if tt_tf else f"WHERE 1=1{region_where_tt}"
        tt_params = tt_tp + region_params_tt
        rows = conn.execute(f"""\
            SELECT {TT_FIELDS} FROM eflow_tt t {region_join_tt}
            {tt_where} AND t.site_id IN ({placeholders})
            ORDER BY t.alarm_occur_time DESC
        """, tt_params + site_id_list).fetchall()
        cols = [c.strip().split('.')[-1] for c in TT_FIELDS.split(",")]
        data = [dict(zip(cols, row)) for row in rows]
        conn.close()
        return {"title": f"TT - {dimension}: {value}", "count": len(data), "data": data}

    # 通用维度
    if dim_type == "tt":
        tt_where = f"WHERE {tt_tf}{region_where_tt}" if tt_tf else f"WHERE 1=1{region_where_tt}"
        tt_params = tt_tp + region_params_tt
        dim_cond = dim_info[1]
        extra_params: list = []
        if dim_cond and value:
            if value == "Unknown":
                field_name = dim_info[2]
                tt_where += f" AND (t.{field_name} IS NULL OR t.{field_name} = '' OR t.{field_name} = 'None')"
            else:
                tt_where += f" AND {dim_cond}"
                extra_params = [value]
        rows = conn.execute(f"""\
            SELECT {TT_FIELDS} FROM eflow_tt t {region_join_tt}
            {tt_where}
            ORDER BY t.alarm_occur_time DESC
        """, tt_params + extra_params).fetchall()
        cols = [c.strip().split('.')[-1] for c in TT_FIELDS.split(",")]
        data = [dict(zip(cols, row)) for row in rows]
        title_val = f": {value}" if value else ""
        conn.close()
        return {"title": f"TT - {dimension}{title_val}", "count": len(data), "data": data}

    elif dim_type == "wo":
        wo_where = f"WHERE {wo_tf}{region_where_wo}" if wo_tf else f"WHERE 1=1{region_where_wo}"
        wo_params = wo_tp + region_params_wo
        dim_cond = dim_info[1]
        extra_params = []
        if dim_cond and value:
            if value == "Unknown":
                field_name = dim_info[2]
                wo_where += f" AND (w.{field_name} IS NULL OR w.{field_name} = '' OR w.{field_name} = 'None')"
            else:
                wo_where += f" AND {dim_cond}"
                extra_params = [value]
        rows = conn.execute(f"""\
            SELECT {WO_FIELDS} FROM eflow_wo w {region_join_wo}
            {wo_where}
            ORDER BY w.alarm_occur_time DESC
        """, wo_params + extra_params).fetchall()
        cols = [c.strip().split('.')[-1] for c in WO_FIELDS.split(",")]
        data = [dict(zip(cols, row)) for row in rows]
        title_val = f": {value}" if value else ""
        conn.close()
        return {"title": f"WO - {dimension}{title_val}", "count": len(data), "data": data}

    conn.close()
    return {"title": "Unknown", "count": 0, "data": []}
