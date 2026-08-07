"""TT&WO Dashboard API - 综合统计看板 (自适应版: 兼容 my_app 和 MTN_Comsal)"""
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Query
from backend.database import get_raw_connection, DB_PATH
from backend.dialect_helpers import list_table_names, table_columns

router = APIRouter(prefix="/api/tt-wo-dashboard", tags=["tt-wo-dashboard"])

# ========== 自适应数据库结构检测 ==========
_schema_cache = None


def _detect_schema() -> dict:
    """检测数据库结构，缓存后复用。兼容 my_app 和 MTN_Comsal"""
    global _schema_cache
    if _schema_cache:
        return _schema_cache

    with get_raw_connection() as conn:
        tables = set(list_table_names(conn))

        # 站点表
        if "master_site_db" in tables:
            site_table = "master_site_db"
        elif "site_db" in tables:
            site_table = "site_db"
        else:
            site_table = None

        # TT表字段检测
        tt_cols = set(table_columns(conn, "eflow_tt")) if "eflow_tt" in tables else set()

        # 严重性字段: alarm_severity 或 category
        has_alarm_severity = "alarm_severity" in tt_cols
        sev_field = "alarm_severity" if has_alarm_severity else "category" if "category" in tt_cols else None

        # 站点关联字段: site_id 或 site_name
        site_join_field = "site_id" if "site_id" in tt_cols else "site_name" if "site_name" in tt_cols else None

        # 创建者字段: creator 或 owner
        creator_field = "creator" if "creator" in tt_cols else "owner" if "owner" in tt_cols else None

        # WO表
        has_wo = "eflow_wo" in tables

        # 站点表字段检测
        site_cols = set()
        if site_table:
            site_cols = set(table_columns(conn, site_table))

        # 站点统计字段映射
        site_stat_fields = {}
        if "power_sources" in site_cols:
            site_stat_fields["power_sources"] = "power_sources"
        if "power_vendor" in site_cols:
            site_stat_fields["power_vendor"] = "power_vendor"
        if "vendor" in site_cols and "power_vendor" not in site_cols:
            site_stat_fields["vendor"] = "vendor"
        if "updated_fme_name_new" in site_cols:
            site_stat_fields["maintenance_team"] = "updated_fme_name_new"
        elif "site_maintainer" in site_cols:
            site_stat_fields["maintenance_team"] = "site_maintainer"
        if "site_class" in site_cols:
            site_stat_fields["site_class"] = "site_class"

        conn.close()

        _schema_cache = {
            "site_table": site_table,
            "site_join_field": site_join_field,
            "sev_field": sev_field,
            "has_alarm_severity": has_alarm_severity,
            "creator_field": creator_field,
            "has_wo": has_wo,
            "site_stat_fields": site_stat_fields,
            "tt_cols": tt_cols,
            "site_cols": site_cols,
        }
        return _schema_cache


def _time_filter(prefix: str, time_start: str | None, time_end: str | None) -> tuple[str, list]:
    """构建时间过滤SQL片段"""
    parts, params = [], []
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
    if val is None or str(val).strip() == '' or str(val) == 'None':
        return default
    return str(val)


def _week_label(ts: str) -> str:
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _week_label: exception swallowed", exc_info=True)
        return ""


@router.get("/overview")
def tt_wo_dashboard_overview(
    time_start: str = Query(None),
    time_end: str = Query(None),
    region: str = Query(None),
):
    """TT&WO Dashboard 综合数据（自适应数据库结构）"""
    S = _detect_schema()
    with get_raw_connection() as conn:

        tt_tf, tt_tp = _time_filter("t", time_start, time_end)
        wo_tf, wo_tp = _time_filter("w", time_start, time_end)

        # 区域过滤 JOIN（自适应站点表和关联字段）
        region_join = region_where = ""
        region_params = []
        if region and S["site_table"]:
            sjf = S["site_join_field"]
            region_join = f"JOIN {S['site_table']} ms ON t.{sjf} = CAST(ms.{sjf} AS TEXT)"
            region_where = " AND ms.region = ?"
            region_params = [region]

        region_join_wo = region_where_wo = ""
        if region and S["has_wo"] and S["site_table"]:
            sjf = S["site_join_field"]
            region_join_wo = f"JOIN {S['site_table']} ms ON w.{sjf} = CAST(ms.{sjf} AS TEXT)"
            region_where_wo = " AND ms.region = ?"

        tt_where = f"WHERE {tt_tf}{region_where}" if tt_tf else f"WHERE 1=1{region_where}"
        tt_params = tt_tp + region_params
        wo_where = f"WHERE {wo_tf}{region_where_wo}" if wo_tf else f"WHERE 1=1{region_where_wo}"
        wo_params = wo_tp + (region_params if region else [])

        # ========== 1. TT 统计 ==========
        # 动态构建 SELECT 字段（自适应 sev_field 和 site_join_field）
        sev_select = f"t.{S['sev_field']}" if S["sev_field"] else "NULL"
        tt_rows = conn.execute(f"""
            SELECT {sev_select}, t.ticket_severity, t.sla_status, t.status, t.domain,
                   t.wo_no, t.alarm_occur_time, t.alarm_clear_time, t.{S['site_join_field']}
            FROM eflow_tt t {region_join} {tt_where}
        """, tt_params).fetchall()

        tt_total = len(tt_rows)
        wo_no_set = set()
        sev_stats = {}
        ticket_sev = {}
        sla_stats = {}
        status_stats = {}
        domain_stats = {}
        week_data = {}
        site_id_set = set()

        for r in tt_rows:
            sev_val = _safe_str(r[0])
            sev_stats[sev_val] = sev_stats.get(sev_val, 0) + 1
            ticket_sev_val = _safe_str(r[1])
            ticket_sev[ticket_sev_val] = ticket_sev.get(ticket_sev_val, 0) + 1
            sla_stats[_safe_str(r[2])] = sla_stats.get(_safe_str(r[2]), 0) + 1
            status_val = _safe_str(r[3], "")
            if status_val:
                status_stats[status_val] = status_stats.get(status_val, 0) + 1
            domain_stats[_safe_str(r[4])] = domain_stats.get(_safe_str(r[4]), 0) + 1
            if r[5]:
                wo_no_set.add(r[5])
            if r[6] and r[7] and r[7] > r[6]:
                try:
                    t1 = datetime.strptime(str(r[6])[:19], "%Y-%m-%d %H:%M:%S")
                    t2 = datetime.strptime(str(r[7])[:19], "%Y-%m-%d %H:%M:%S")
                    dur_min = (t2 - t1).total_seconds() / 60
                    if 0 < dur_min < 43200:
                        wk = _week_label(str(r[6]))
                        if wk:
                            week_data.setdefault(wk, []).append(dur_min)
                except Exception:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] tt_wo_dashboard_overview: exception swallowed", exc_info=True)
                    pass
            if r[8]:
                site_id_set.add(r[8])

        status_stats = dict(sorted(status_stats.items(), key=lambda x: x[1], reverse=True))
        domain_stats = dict(sorted(domain_stats.items(), key=lambda x: x[1], reverse=True))
        mttr_weekly = [
            {"week": w, "mttr": round(sum(week_data[w]) / len(week_data[w]), 1), "count": len(week_data[w])}
            for w in sorted(week_data.keys())
        ]

        # ========== 2. WO 统计（表不存在时返回空）==========
        wo_total = 0
        rc_main, rc_sub, wo_source_stats, wo_status_stats = {}, {}, {}, {}
        if S["has_wo"]:
            wo_rows = conn.execute(f"""
                SELECT w.rc_main_category, w.rc_sub_category, w.source, w.status
                FROM eflow_wo w {region_join_wo} {wo_where}
            """, wo_params).fetchall()
            wo_total = len(wo_rows)
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
        else:
            # 无 eflow_wo 表时，从 eflow_tt 获取 root_cause
            rc_rows = conn.execute(f"""
                SELECT t.root_cause, t.sub_root_cause
                FROM eflow_tt t {region_join} {tt_where}
            """, tt_params).fetchall()
            for r in rc_rows:
                mc = _safe_str(r[0])
                rc_main[mc] = rc_main.get(mc, 0) + 1
                sc = _safe_str(r[1])
                rc_sub[sc] = rc_sub.get(sc, 0) + 1
        wo_source_stats = dict(sorted(wo_source_stats.items(), key=lambda x: x[1], reverse=True))
        wo_status_stats = dict(sorted(wo_status_stats.items(), key=lambda x: x[1], reverse=True))

        # ========== 3. 站点信息统计（自适应字段）==========
        site_stats = {}
        if site_id_set and S["site_table"]:
            placeholders = ",".join("?" * len(site_id_set))
            site_params = list(site_id_set)
            # 动态 SELECT 站点字段
            select_fields = ", ".join(S["site_stat_fields"].values())
            if select_fields:
                rows = conn.execute(f"""
                    SELECT {select_fields}
                    FROM {S['site_table']}
                    WHERE CAST({S['site_join_field']} AS TEXT) IN ({placeholders})
                """, site_params).fetchall()
                field_keys = list(S["site_stat_fields"].keys())
                for r in rows:
                    for i, key in enumerate(field_keys):
                        val = r[i]
                        if val and str(val).strip() and str(val) != 'None':
                            if key not in site_stats:
                                site_stats[key] = {}
                            site_stats[key][val] = site_stats[key].get(val, 0) + 1
                for key in site_stats:
                    site_stats[key] = dict(sorted(site_stats[key].items(), key=lambda x: x[1], reverse=True)[:15])

        # ========== 4. 汇总 ==========
        regions = []
        if S["site_table"]:
            regions = [r[0] for r in conn.execute(
                f"SELECT DISTINCT region FROM {S['site_table']} WHERE region IS NOT NULL AND region != '' ORDER BY region"
            ).fetchall()]

        conn.close()

        # 返回统一的 tt_stats 结构（同时包含 alarm_severity 和 category）
        tt_stats = {
            "alarm_severity": sev_stats if S["has_alarm_severity"] else {},
            "category": sev_stats if not S["has_alarm_severity"] else {},
            "ticket_severity": ticket_sev,
            "sla_status": sla_stats,
            "status": status_stats,
        }

        return {
            "filters": {"regions": regions, "time_start": time_start, "time_end": time_end, "region": region},
            "summary": {"tt_total": tt_total, "wo_total": wo_total, "wo_no_count": len(wo_no_set)},
            "tt_stats": tt_stats,
            "mttr_weekly": mttr_weekly,
            "domain_stats": domain_stats,
            "root_cause": {"main": rc_main, "sub": rc_sub},
            "wo_stats": {"source": wo_source_stats, "status": wo_status_stats},
            "site_stats": site_stats,
        }


# ========== 下钻查询 ==========

# 维度 → (表类型, SQL条件片段, 字段名)
def _get_dimension_map():
    """根据数据库结构动态构建维度映射"""
    S = _detect_schema()
    dim = {
        "ticket_severity": ("tt", "t.ticket_severity = ?", "ticket_severity"),
        "sla_status":      ("tt", "t.sla_status = ?",      "sla_status"),
        "status":          ("tt", "t.status = ?",           "status"),
        "domain":          ("tt", "t.domain = ?",           "domain"),
        "all_tt":          ("tt", None, None),
    }
    if S["sev_field"]:
        sev_dim = S["sev_field"]
        dim[sev_dim] = ("tt", f"t.{sev_dim} = ?", sev_dim)
    if S["has_wo"]:
        dim.update({
            "rc_main":   ("wo", "w.rc_main_category = ?", "rc_main_category"),
            "rc_sub":    ("wo", "w.rc_sub_category = ?",  "rc_sub_category"),
            "wo_source": ("wo", "w.source = ?",           "source"),
            "wo_status": ("wo", "w.status = ?",           "status"),
            "all_wo":    ("wo", None, None),
        })
    else:
        # 无eflow_wo时，root_cause从eflow_tt获取
        if "root_cause" in S["tt_cols"]:
            dim["rc_main"] = ("tt", "t.root_cause = ?", "root_cause")
        if "sub_root_cause" in S["tt_cols"]:
            dim["rc_sub"] = ("tt", "t.sub_root_cause = ?", "sub_root_cause")
    for key, col in S["site_stat_fields"].items():
        dim[key] = ("site", col, key)
    return dim


def _build_tt_fields():
    """动态构建 TT 明细字段"""
    S = _detect_schema()
    fields = ["t.title", "t.ticket_no", "t.wo_no", f"t.{S['site_join_field']}", "t.status"]
    if S["creator_field"]:
        fields.append(f"t.{S['creator_field']}")
    fields += ["t.ticket_severity"]
    if S["sev_field"]:
        fields.append(f"t.{S['sev_field']}")
    fields += ["t.sla_status", "t.alarm_occur_time", "t.alarm_clear_time", "t.domain", "t.root_cause", "t.sub_root_cause"]
    return ", ".join(fields)


@router.get("/drilldown")
def tt_wo_drilldown(
    type: str = Query("tt"),
    time_start: str = Query(None),
    time_end: str = Query(None),
    region: str = Query(None),
    dimension: str = Query("all_tt"),
    value: str = Query(None),
):
    """TT/WO 明细下钻查询（自适应数据库结构）"""
    S = _detect_schema()
    DIMENSION_MAP = _get_dimension_map()
    with get_raw_connection() as conn:

        tt_tf, tt_tp = _time_filter("t", time_start, time_end)
        wo_tf, wo_tp = _time_filter("w", time_start, time_end)

        sjf = S["site_join_field"]
        region_join_tt = region_where_tt = ""
        region_params_tt: list = []
        if region and S["site_table"]:
            region_join_tt = f"JOIN {S['site_table']} ms ON t.{sjf} = CAST(ms.{sjf} AS TEXT)"
            region_where_tt = " AND ms.region = ?"
            region_params_tt = [region]

        region_join_wo = region_where_wo = ""
        region_params_wo: list = []
        if region and S["has_wo"] and S["site_table"]:
            region_join_wo = f"JOIN {S['site_table']} ms ON w.{sjf} = CAST(ms.{sjf} AS TEXT)"
            region_where_wo = " AND ms.region = ?"
            region_params_wo = [region]

        dim_info = DIMENSION_MAP.get(dimension, ("tt", None, None))
        dim_type = dim_info[0]

        if dim_type == "wo" and not S["has_wo"]:
            conn.close()
            return {"title": f"WO - {dimension}", "count": 0, "data": []}

        TT_FIELDS = _build_tt_fields()

        # week 维度
        if dimension == "week" and value:
            tt_where = f"WHERE {tt_tf}{region_where_tt}" if tt_tf else f"WHERE 1=1{region_where_tt}"
            tt_params = tt_tp + region_params_tt
            rows = conn.execute(f"""
                SELECT {TT_FIELDS} FROM eflow_tt t {region_join_tt}
                {tt_where} AND t.alarm_occur_time IS NOT NULL
                ORDER BY t.alarm_occur_time DESC
            """, tt_params).fetchall()
            cols = [c.strip().split('.')[-1] for c in TT_FIELDS.split(",")]
            data = [dict(zip(cols, row)) for row in rows if _week_label(str(dict(zip(cols, row)).get("alarm_occur_time") or "")) == value]
            conn.close()
            return {"title": f"TT - Week: {value}", "count": len(data), "data": data}

        # 站点维度
        if dim_type == "site" and value:
            site_field = dim_info[1]
            if S["site_table"]:
                site_ids = conn.execute(f"""
                    SELECT {sjf} FROM {S['site_table']}
                    WHERE {site_field} = ? AND {sjf} IS NOT NULL
                """, [value]).fetchall()
                id_list = [str(s[0]) for s in site_ids]
                if not id_list:
                    conn.close()
                    return {"title": f"TT - {dimension}: {value}", "count": 0, "data": []}
                placeholders = ",".join("?" * len(id_list))
                tt_where = f"WHERE {tt_tf}{region_where_tt}" if tt_tf else f"WHERE 1=1{region_where_tt}"
                rows = conn.execute(f"""
                    SELECT {TT_FIELDS} FROM eflow_tt t {region_join_tt}
                    {tt_where} AND t.{sjf} IN ({placeholders})
                    ORDER BY t.alarm_occur_time DESC
                """, tt_tp + region_params_tt + id_list).fetchall()
                cols = [c.strip().split('.')[-1] for c in TT_FIELDS.split(",")]
                data = [dict(zip(cols, row)) for row in rows]
                conn.close()
                return {"title": f"TT - {dimension}: {value}", "count": len(data), "data": data}

        # 通用 TT 维度
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
            rows = conn.execute(f"""
                SELECT {TT_FIELDS} FROM eflow_tt t {region_join_tt}
                {tt_where} ORDER BY t.alarm_occur_time DESC
            """, tt_params + extra_params).fetchall()
            cols = [c.strip().split('.')[-1] for c in TT_FIELDS.split(",")]
            data = [dict(zip(cols, row)) for row in rows]
            conn.close()
            return {"title": f"TT - {dimension}{': ' + value if value else ''}", "count": len(data), "data": data}

        # WO 维度
        if dim_type == "wo" and S["has_wo"]:
            WO_FIELDS = "w.wo_no, w.tt_no, w.title, w.status, w.creator, w.created_time, w.alarm_occur_time, w.alarm_clear_time, w.source, w.rc_main_category, w.rc_sub_category, w.ticket_severity, w.alarm_severity"
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
            rows = conn.execute(f"""
                SELECT {WO_FIELDS} FROM eflow_wo w {region_join_wo}
                {wo_where} ORDER BY w.alarm_occur_time DESC
            """, wo_params + extra_params).fetchall()
            cols = [c.strip().split('.')[-1] for c in WO_FIELDS.split(",")]
            data = [dict(zip(cols, row)) for row in rows]
            conn.close()
            return {"title": f"WO - {dimension}{': ' + value if value else ''}", "count": len(data), "data": data}

        conn.close()
        return {"title": "Unknown", "count": 0, "data": []}
