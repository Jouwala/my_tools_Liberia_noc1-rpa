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
    # 优先使用 eflow_tt.tt_no (真实 TT 单号)，而非 ticket_no (可能是 WO 回退值)
    tt_no_field = "t.tt_no" if "tt_no" in S["tt_cols"] else "t.ticket_no"
    fields = ["t.title", tt_no_field, "t.wo_no", f"t.{S['site_join_field']}", "t.status"]
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


# ========== 根因一致性审计（Root Cause Audit）==========
# 背景：eflow_tt.root_cause / sub_root_cause / root_cause_description 为 NOC 人工填报，
# 存在系统性误填（详见复盘报告 §4）。本模块用告警链路（history_alarm）作为权威依据，
# 与人工填报做一致性比对，供 TT 详情页"系统判定根因 vs NOC 填写根因"对比展示。

# 告警码 → 系统语义（来自 history_alarm 实测权威映射，2026-09 校准）
ALARM_CODE_SEMANTICS = {
    "99933": {"name": "SITE DOWN DUE TO POWER OFF", "reason_type": "TRM"},
    "9995":  {"name": "MW LINK DOWN",               "reason_type": "TRM"},
    "9920":  {"name": "Complete site down (CSD)",   "reason_type": "TRM"},
    "9910":  {"name": "Partial site down (PSD)",    "reason_type": "TRM"},
    "9970":  {"name": "4G SITE DOWN",               "reason_type": "TRM"},
    "9980":  {"name": "2G SITE DOWN",               "reason_type": "TRM"},
    "9990":  {"name": "3G SITE DOWN",               "reason_type": "TRM"},
    "9981":  {"name": "2G CELL DOWN",               "reason_type": "OTHER"},
    "9991":  {"name": "3G CELL DOWN",               "reason_type": "OTHER"},
    "9971":  {"name": "4G CELL DOWN",               "reason_type": "OTHER"},
    "4758":  {"name": "Fiber Break",                "reason_type": None},
}

# 语义关键词：用于从 codename 推断真实故障域
_POWER_HINTS = ("POWER", "GENSET", "BATTERY", "FUEL", "ENERGY", "GRID", "MAINS", "COMMERCIAL")
_TRM_HINTS = ("MW LINK", "MICROWAVE", "FIBER", "LINK DOWN", "TRANSMISSION", "MW ")

# NOC 填报的根因归属（用于一致性判定）
_NOC_POWER_FAMILY = {"POWER"}

# 真实故障域 → 建议追溯方向
_SUGGESTED_ACTION = {
    "TRM": "建议追溯该站上联传输链路（MW 微波 / PTN / 光纤），核查是否为链路反复中断",
    "POWER": "建议核查站点供电（市电 / 油机 / 电池），确认是否为真实断电",
    "OTHER": "建议结合告警明细进一步定位（小区级 / 板件级）",
}


def _norm_alarm_id(val) -> str:
    """归一化 alarm_id：eflow_tt.alarm_id 可能存成 '1764213380772.0'（浮点串）"""
    if val is None:
        return ""
    s = str(val).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _infer_fault_domain(codename: str, reason_type: str, alarmcode: str) -> tuple[str, str]:
    """从告警链路推断真实故障域。

    返回 (fault_domain, basis)：basis 说明判定依据，便于前端展示可解释性。
    """
    cn = (codename or "").upper()

    # 1) codename 明确含供电语义 → POWER
    if any(h in cn for h in _POWER_HINTS):
        return "POWER", f"codename='{codename}' 含供电语义"

    # 2) codename 含传输语义 → TRM
    if any(h in cn for h in _TRM_HINTS):
        return "TRM", f"codename='{codename}' 含传输语义"

    # 3) 回落：用 reason_type 兜底
    if reason_type:
        return reason_type, f"reason_type='{reason_type}'"

    # 4) 再回落：查静态语义表
    sem = ALARM_CODE_SEMANTICS.get(_norm_alarm_id(alarmcode))
    if sem and sem.get("reason_type"):
        return sem["reason_type"], f"alarmcode={alarmcode} 静态语义表"
    if sem:
        return "UNKNOWN", f"alarmcode={alarmcode} 语义未知（{sem.get('name')}）"

    return "UNKNOWN", "无可用告警链路信息"


def _fetch_alarm_chain(conn, tt_no: str, alarm_id, site_id,
                       alarm_code=None, tt_reason_type=None) -> tuple[list, str]:
    """三级策略取告警链路，逐级降权，越靠前越可信。

    返回 (rows, linkage)：
    - exact                  : history_alarm.tt_id = tt_no（1 单对 1 告警，最强）
    - site_fallback          : 同站点且**告警码严格一致**
    - site_reason_fallback   : 同站点且 **reason_type 一致**（同一故障域，如 TRM）
    - site_fallback_unrelated: 同站点有告警但与本单不同域 → 属其它单子，丢弃
    - none                   : 无任何可用告警
    """
    cols = "alarmcode, codename, reason_type, alarm_source, restypename, alarmkey, site_name"

    # 一级：tt_id 精确
    try:
        rows = conn.execute(
            f"SELECT {cols} FROM history_alarm WHERE tt_id = ? LIMIT 20", (tt_no,)
        ).fetchall()
        if rows:
            return rows, "exact"
    except Exception:
        logging.getLogger(__name__).warning("[root-cause-audit] tt_id 精确关联失败", exc_info=True)

    # 二级：alarm_id（归一化后）
    nid = _norm_alarm_id(alarm_id)
    if nid:
        try:
            rows = conn.execute(
                f"SELECT {cols} FROM history_alarm WHERE CAST(id AS TEXT) = ? LIMIT 20", (nid,)
            ).fetchall()
            if rows:
                return rows, "exact"
        except Exception:
            logging.getLogger(__name__).warning("[root-cause-audit] alarm_id 关联失败", exc_info=True)

    # 三级：站点级降级 —— 按"故障域族"匹配（比严格码匹配更符合业务语义）
    # 实测：同站点断站类告警码（9970/9980/9990/9910/9920/9995/99933）的 reason_type
    # 全部为 TRM，属同一故障域族；严格码匹配会漏掉"本单码未入库但同族告警在库"的情况。
    if site_id is not None and str(site_id).strip() not in ("", "None"):
        try:
            rows = conn.execute(
                f"""SELECT {cols} FROM history_alarm WHERE CAST(site_id AS TEXT) = ?
                    ORDER BY alarmraisedtime DESC LIMIT 50""",
                (str(site_id),),
            ).fetchall()
            if rows:
                tt_code = _norm_alarm_id(alarm_code)
                # 1) 严格码匹配（最强）
                if tt_code:
                    matched = [r for r in rows
                               if _norm_alarm_id(dict(r).get("alarmcode")) == tt_code]
                    if matched:
                        return matched, "site_fallback"

                # 2) reason_type 匹配（同故障域，次强）
                # 实测依据：断站类码(9970/9980/9990/9910/9920/9995/99933)的 reason_type
                # 统一为 TRM，属同一故障域；本单码未入库但同域告警在库时仍可佐证。
                tt_reason = (tt_reason_type or "").strip().upper()
                if not tt_reason and tt_code:
                    sem = ALARM_CODE_SEMANTICS.get(tt_code)
                    tt_reason = ((sem or {}).get("reason_type") or "").strip().upper()
                if tt_reason:
                    same_reason = [r for r in rows
                                   if (dict(r).get("reason_type") or "").strip().upper() == tt_reason]
                    if same_reason:
                        return same_reason, "site_reason_fallback"

                # 同站点有告警但不同域 → 属其它单子，不可采纳
                return [], "site_fallback_unrelated"
        except Exception:
            logging.getLogger(__name__).warning("[root-cause-audit] site_id 降级关联失败", exc_info=True)

    return [], "none"


@router.get("/root-cause-audit/{tt_no}")
def tt_root_cause_audit(tt_no: str):
    """单张 TT 的「系统判定根因 vs NOC 填写根因」一致性审计。

    权威依据：history_alarm（告警链路）> eflow_tt.alarm_reason_type > NOC 人工填报。
    对应复盘报告 §6.4 最小可行版本。
    """
    S = _detect_schema()
    with get_raw_connection() as conn:
        row = conn.execute(
            """SELECT tt_no, site_id, site_name, alarm_code, alarm_id, ticket_severity,
                      alarm_severity, status, root_cause, sub_root_cause, root_cause_description,
                      alarm_reason_type, last_processer, last_processer_group,
                      last_modified_time, fo_process_detail, fo_accept_detail, create_detail
               FROM eflow_tt WHERE tt_no = ?""",
            (tt_no,),
        ).fetchone()

        if not row:
            conn.close()
            return {"tt_no": tt_no, "found": False, "message": "未找到该工单"}

        t = dict(row)
        alarm_rows, linkage = _fetch_alarm_chain(
            conn, tt_no, t.get("alarm_id"), t.get("site_id"),
            t.get("alarm_code"), t.get("alarm_reason_type"),
        )
        conn.close()

    # ---- NOC 人工填报层 ----
    filed_by = ""
    filed_at = ""
    detail = t.get("fo_process_detail") or ""
    if detail:
        import re
        m = re.search(r"Operator:([^(]+)\(([^)]*)\)", str(detail))
        if m:
            filed_by = f"{m.group(1).strip()}({m.group(2).strip()})"
        m2 = re.search(r"Operation Time:([0-9\-: ]+)", str(detail))
        if m2:
            filed_at = m2.group(1).strip()

    noc_filled = {
        "root_cause": t.get("root_cause"),
        "sub_root_cause": t.get("sub_root_cause"),
        "root_cause_description": t.get("root_cause_description"),
        "filed_by": filed_by or t.get("last_processer"),
        "filed_at": filed_at or t.get("last_modified_time"),
    }

    # ---- 系统判定层（取告警链路中语义最明确的一条）----
    system_judged = None
    if alarm_rows:
        # 优先选 codename 能推断出故障域的记录
        best, best_domain, best_basis = None, "UNKNOWN", ""
        for r in alarm_rows:
            d = dict(r)
            dom, basis = _infer_fault_domain(
                d.get("codename"), d.get("reason_type"), d.get("alarmcode")
            )
            if dom != "UNKNOWN":
                best, best_domain, best_basis = d, dom, basis
                break
            if best is None:
                best, best_domain, best_basis = d, dom, basis

        codes = [str(dict(r).get("alarmcode")) for r in alarm_rows]
        names = [str(dict(r).get("codename")) for r in alarm_rows]
        system_judged = {
            "fault_domain": best_domain,
            "basis": best_basis,
            "alarmcode": best.get("alarmcode") if best else None,
            "codename": best.get("codename") if best else None,
            "reason_type": best.get("reason_type") if best else None,
            "alarm_source": best.get("alarm_source") if best else None,
            "restypename": best.get("restypename") if best else None,
            "alarmkey": best.get("alarmkey") if best else None,
            "linkage": linkage,
            "alarm_count": len(alarm_rows),
            "distinct_codes": sorted(set(codes)),
            "distinct_names": sorted(set(names)),
            "history_match": f"站点历史 {len(alarm_rows)} 条告警，指纹 {sorted(set(names))[:3]}",
        }
    elif t.get("alarm_reason_type"):
        # 无告警链路时，退到 TT 表系统字段（confidence 会相应降级）
        system_judged = {
            "fault_domain": t.get("alarm_reason_type"),
            "basis": "eflow_tt.alarm_reason_type（系统字段，无告警链路佐证）",
            "alarmcode": t.get("alarm_code"),
            "codename": None,
            "reason_type": t.get("alarm_reason_type"),
            "linkage": linkage,
            "alarm_count": 0,
        }

    # ---- 一致性判定 ----
    consistency = None
    mismatch_type = ""
    confidence = "low"
    note = ""

    noc_rc = (t.get("root_cause") or "").strip().upper()
    if system_judged and noc_rc:
        sys_domain = system_judged["fault_domain"]
        if sys_domain in ("POWER", "TRM", "OTHER"):
            confidence = ("high" if linkage == "exact"
                          else "medium" if linkage in ("site_fallback", "site_reason_fallback")
                          else "low")

            if noc_rc in _NOC_POWER_FAMILY and sys_domain == "TRM":
                consistency = False
                mismatch_type = "POWER<-TRM"
                note = ("NOC 填报 POWER（供电类），但告警链路显示为传输类（TRM）故障；"
                        "该站告警指纹未含供电语义，疑似误填。")
            elif noc_rc in _NOC_POWER_FAMILY and sys_domain == "POWER":
                consistency = True
                note = "NOC 填报 POWER，告警链路同样指向供电类，一致。"
            elif noc_rc in ("MW", "FIBER", "RAN", "IP-DWDM NETWORK") and sys_domain == "TRM":
                consistency = True
                note = "NOC 填报传输类，与告警链路一致。"
            elif sys_domain == "POWER" and noc_rc not in _NOC_POWER_FAMILY:
                consistency = False
                mismatch_type = f"{noc_rc}<-POWER"
                note = "告警链路指向供电类，但 NOC 未填报 POWER。"
            else:
                consistency = None
                note = f"告警链路判定为 {sys_domain}，NOC 填报 {noc_rc}，规则未覆盖该组合，需人工复核。"
    elif not noc_rc:
        consistency = None
        note = "NOC 未填报根因（root_cause 为空），无法比对。"
    elif linkage == "site_fallback_unrelated":
        consistency = None
        note = ("该站 48h 窗口内有其它单子的告警，但告警码与本单不匹配，"
                "不能作为本单判据（告警可能已滚出窗口或本单告警未被采集）。")
    else:
        consistency = None
        note = "缺少可用告警链路，无法比对（告警可能已滚出 48h 窗口）。"

    return {
        "tt_no": tt_no,
        "found": True,
        "site": {"site_id": t.get("site_id"), "site_name": t.get("site_name")},
        "ticket": {
            "ticket_severity": t.get("ticket_severity"),
            "alarm_severity": t.get("alarm_severity"),
            "alarm_code": t.get("alarm_code"),
            "status": t.get("status"),
        },
        "noc_filled": noc_filled,
        "system_judged": system_judged,
        "consistency": consistency,
        "mismatch_type": mismatch_type,
        "confidence": confidence,
        "note": note,
        "suggested_action": _SUGGESTED_ACTION.get(
            (system_judged or {}).get("fault_domain"), "无建议"
        ),
    }


@router.get("/root-cause-audit-summary")
def tt_root_cause_audit_summary(
    limit: int = Query(50, ge=1, le=500),
    only_mismatch: bool = Query(True),
):
    """批量根因一致性审计摘要（供看板列表 / 月度报告使用）。

    扫描 root_cause 非空的近期 TT，逐条比对告警链路，返回不一致清单。
    注意：history_alarm 为 48h 滚动窗口，故只对窗口内有告警的单有效。
    """
    with get_raw_connection() as conn:
        rows = conn.execute(
            """SELECT tt_no, site_id, site_name, alarm_code, alarm_id, ticket_severity,
                      root_cause, sub_root_cause, alarm_reason_type, last_processer,
                      last_modified_time
               FROM eflow_tt
               WHERE root_cause IS NOT NULL AND root_cause <> ''
               ORDER BY last_modified_time DESC LIMIT ?""",
            (limit,),
        ).fetchall()

        items, checked, mismatch_cnt, no_alarm, unrelated = [], 0, 0, 0, 0
        for r in rows:
            t = dict(r)
            alarm_rows, linkage = _fetch_alarm_chain(
                conn, t["tt_no"], t.get("alarm_id"), t.get("site_id"),
                t.get("alarm_code"), t.get("alarm_reason_type"),
            )
            if not alarm_rows:
                if linkage == "site_fallback_unrelated":
                    unrelated += 1
                else:
                    no_alarm += 1
                continue

            checked += 1
            best, best_domain, best_basis = None, "UNKNOWN", ""
            for a in alarm_rows:
                d = dict(a)
                dom, basis = _infer_fault_domain(
                    d.get("codename"), d.get("reason_type"), d.get("alarmcode")
                )
                if best is None or (dom != "UNKNOWN" and best_domain == "UNKNOWN"):
                    best, best_domain, best_basis = d, dom, basis
                if dom != "UNKNOWN":
                    break

            noc_rc = (t.get("root_cause") or "").strip().upper()
            is_mismatch = noc_rc in _NOC_POWER_FAMILY and best_domain == "TRM"
            if is_mismatch:
                mismatch_cnt += 1
                items.append({
                    "tt_no": t["tt_no"],
                    "site_name": t.get("site_name"),
                    "site_id": t.get("site_id"),
                    "ticket_severity": t.get("ticket_severity"),
                    "noc_root_cause": t.get("root_cause"),
                    "noc_sub_root_cause": t.get("sub_root_cause"),
                    "system_codename": best.get("codename") if best else None,
                    "system_alarmcode": best.get("alarmcode") if best else None,
                    "system_reason_type": best.get("reason_type") if best else None,
                    "system_fault_domain": best_domain,
                    "basis": best_basis,
                    "linkage": linkage,
                    "last_processer": t.get("last_processer"),
                    "last_modified_time": t.get("last_modified_time"),
                    "mismatch_type": "POWER<-TRM",
                })

        conn.close()

    if only_mismatch:
        return {
            "scanned": len(rows),
            "checked": checked,
            "no_alarm_data": no_alarm,
            "site_unrelated_skipped": unrelated,
            "mismatch_count": mismatch_cnt,
            "mismatch_rate_pct": round(100.0 * mismatch_cnt / checked, 1) if checked else 0.0,
            "items": items,
        }

    return {
        "scanned": len(rows),
        "checked": checked,
        "no_alarm_data": no_alarm,
        "site_unrelated_skipped": unrelated,
        "mismatch_count": mismatch_cnt,
        "mismatch_rate_pct": round(100.0 * mismatch_cnt / checked, 1) if checked else 0.0,
        "items": items,
    }
