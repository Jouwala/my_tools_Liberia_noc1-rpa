"""GIS地理信息 API - Voronoi分区版"""
import os
import json
import sqlite3
import numpy as np
from scipy.spatial import Voronoi
from shapely.geometry import Polygon, MultiPolygon, box, Point
from shapely.ops import unary_union
from fastapi import APIRouter, Query, HTTPException
from backend.database import get_raw_connection, DB_PATH

router = APIRouter(prefix="/api/gis", tags=["gis"])

# ========== 自适应GIS数据库结构检测 ==========
_gis_schema_cache = None

def _detect_gis_schema() -> dict:
    """检测数据库结构，兼容 my_app 和 MTN_Comsal"""
    global _gis_schema_cache
    if _gis_schema_cache:
        return _gis_schema_cache

    conn = get_raw_connection()
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    # 站点表
    site_table = "master_site_db" if "master_site_db" in tables else "site_db" if "site_db" in tables else None

    site_cols = set()
    if site_table:
        site_cols = {r[1] for r in conn.execute(f"PRAGMA table_info({site_table})").fetchall()}

    # 字段映射
    province_col = "province_county" if "province_county" in site_cols else "province" if "province" in site_cols else None
    vip_col = "vip_site" if "vip_site" in site_cols else "vipsite" if "vipsite" in site_cols else None
    hub_col = "hub_site" if "hub_site" in site_cols else "hubsite" if "hubsite" in site_cols else None

    # TT表关联字段
    tt_cols = set()
    if "eflow_tt" in tables:
        tt_cols = {r[1] for r in conn.execute("PRAGMA table_info(eflow_tt)").fetchall()}
    tt_site_key = "site_id" if "site_id" in tt_cols else "site_name" if "site_name" in tt_cols else None

    # WO表
    has_wo = "eflow_wo" in tables
    # topology表
    has_topology = "topology" in tables
    # 告警表
    has_realtime_alarm = "realtime_alarm" in tables
    has_history_alarm = "history_alarm" in tables

    conn.close()

    _gis_schema_cache = {
        "site_table": site_table, "site_cols": site_cols,
        "province_col": province_col, "vip_col": vip_col, "hub_col": hub_col,
        "tt_site_key": tt_site_key, "has_wo": has_wo, "has_topology": has_topology,
        "tt_cols": tt_cols,
        "has_realtime_alarm": has_realtime_alarm, "has_history_alarm": has_history_alarm,
    }
    return _gis_schema_cache


def _load_boundary_file(filename: str):
    """从 boundaries/ 目录加载 GeoJSON 边界文件，返回 Shapely Polygon (lat, lng 格式)"""
    boundaries_dir = os.path.join(os.path.dirname(__file__), '..', 'boundaries')
    filepath = os.path.join(boundaries_dir, filename)
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            geojson = json.load(f)
        geom = geojson.get('geometry') or (geojson.get('features', [{}])[0].get('geometry'))
        if not geom:
            return None
        # GeoJSON 坐标为 [lng, lat]，转为 (lat, lng) 以匹配现有代码
        if geom['type'] == 'Polygon':
            coords = [(p[1], p[0]) for p in geom['coordinates'][0]]
            poly = Polygon(coords)
        elif geom['type'] == 'MultiPolygon':
            # 取面积最大的多边形
            polys = [Polygon([(p[1], p[0]) for p in ring[0]]) for ring in geom['coordinates']]
            poly = max(polys, key=lambda p: p.area)
        else:
            return None
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly
    except Exception:
        return None


# GIS 筛选列配置：(param_name, db_column, label)
_GIS_FILTER_COLS = [
    ("trm_type", "trm_type", "TRM Type"),
    ("site_type", "site_type", "Site Type"),
    ("area", "area", "Area"),
    ("hubsite", "hub_site", "Hub Site"),
    ("site_information", "site_information", "Site Information"),
    ("vip_site", "vip_site", "VIP Site"),
    ("supervisor", "supervisor", "Supervisor"),
    ("updated_fme_name_new", "updated_fme_name_new", "FME Name"),
]


@router.get("/sites")
def get_sites(
    region: str = Query(None),
    trm_type: str = Query(None),
    site_type: str = Query(None),
    area: str = Query(None),
    hubsite: str = Query(None),
    site_information: str = Query(None),
    vip_site: str = Query(None),
    supervisor: str = Query(None),
    updated_fme_name_new: str = Query(None),
    network_type: str = Query(None),
    time_start: str = Query(None, description="时间窗口开始 YYYY-MM-DD"),
    time_end: str = Query(None, description="时间窗口结束 YYYY-MM-DD"),
):
    """获取站点GIS数据 - 含TT/WO统计，支持时间窗口和多列筛选（自适应数据库结构）"""
    S = _detect_gis_schema()
    if not S["site_table"]:
        return {"sites": [], "total": 0, "regions": [], "filter_options": {}}

    conn = get_raw_connection()
    st = S["site_table"]

    where_parts = [
        "latitude IS NOT NULL",
        "longitude IS NOT NULL",
        "CAST(latitude AS REAL) != 0",
        "CAST(longitude AS REAL) != 0",
    ]
    params = []

    # 动态筛选参数
    filter_params = {
        "trm_type": trm_type, "site_type": site_type, "area": area,
        "hubsite": hubsite, "site_information": site_information,
        "vip_site": vip_site, "supervisor": supervisor,
        "updated_fme_name_new": updated_fme_name_new,
    }
    for param_name, db_col, _ in _GIS_FILTER_COLS:
        val = filter_params.get(param_name)
        if val and db_col in S["site_cols"]:
            where_parts.append(f"{db_col} = ?")
            params.append(val)
    if region:
        where_parts.append("region = ?")
        params.append(region)
    if network_type and "network_type" in S["site_cols"]:
        where_parts.append("network_type = ?")
        params.append(network_type)

    where_clause = " AND ".join(where_parts)

    # 构建TT/WO时间过滤条件（使用alarm_occur_time）
    tt_time_where = ""
    wo_time_where = ""
    if time_start:
        tt_time_where += f" AND alarm_occur_time >= '{time_start}'"
        wo_time_where += f" AND alarm_occur_time >= '{time_start}'"
    if time_end:
        from datetime import datetime, timedelta
        end_dt = datetime.strptime(time_end, "%Y-%m-%d") + timedelta(days=1)
        end_str = end_dt.strftime("%Y-%m-%d")
        tt_time_where += f" AND alarm_occur_time < '{end_str}'"
        wo_time_where += f" AND alarm_occur_time < '{end_str}'"

    # 动态构建 SELECT 字段
    prov_sel = S["province_col"] if S["province_col"] else "NULL"
    vip_sel = S["vip_col"] if S["vip_col"] else "NULL"
    hub_sel = S["hub_col"] if S["hub_col"] else "NULL"

    # 筛选列动态 SELECT
    filter_select_parts = []
    filter_col_indices = {}  # param_name -> index in row
    base_cols = 10  # site_id, site_name, lat, lng, region, prov, network, site_type, vip, hub
    for i, (param_name, db_col, _) in enumerate(_GIS_FILTER_COLS):
        if db_col in S["site_cols"]:
            filter_select_parts.append(db_col)
            filter_col_indices[param_name] = base_cols + len(filter_select_parts) - 1

    filter_select_sql = ", " + ", ".join(filter_select_parts) if filter_select_parts else ""

    sql = f"""
        SELECT 
            site_id, site_name,
            CAST(latitude AS REAL) as lat,
            CAST(longitude AS REAL) as lng,
            region, {prov_sel}, network_type, site_type,
            {vip_sel}, {hub_sel}{filter_select_sql}
        FROM {st}
        WHERE {where_clause}
    """
    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()

    # 获取region列表
    regions = [r[0] for r in conn.execute(
        f"SELECT DISTINCT region FROM {st} WHERE region IS NOT NULL AND region != '' ORDER BY region"
    ).fetchall()]

    # 获取筛选列的唯一值（用向量化 dict 操作，保证最快）
    filter_options = {}
    for param_name, db_col, _ in _GIS_FILTER_COLS:
        if db_col in S["site_cols"]:
            vals = [r[0] for r in conn.execute(
                f"SELECT DISTINCT {db_col} FROM {st} WHERE {db_col} IS NOT NULL AND {db_col} != '' ORDER BY {db_col}"
            ).fetchall()]
            filter_options[param_name] = vals

    # 预计算TT统计（自适应关联字段）
    tt_stats = {}
    if S["tt_site_key"]:
        tt_sql = f"""
            SELECT {S['tt_site_key']}, COUNT(*),
                   SUM(CASE WHEN status != 'Closed' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN status = 'Closed' THEN 1 ELSE 0 END)
            FROM eflow_tt WHERE 1=1 {tt_time_where}
            GROUP BY {S['tt_site_key']}
        """
        for sid, cnt, open_cnt, closed_cnt in conn.execute(tt_sql).fetchall():
            tt_stats[str(sid)] = (cnt or 0, open_cnt or 0, closed_cnt or 0)

    wo_stats = {}
    if S["has_wo"] and S["tt_site_key"]:
        wo_sql = f"SELECT {S['tt_site_key']}, COUNT(*) FROM eflow_wo WHERE 1=1 {wo_time_where} GROUP BY {S['tt_site_key']}"
        for sid, cnt in conn.execute(wo_sql).fetchall():
            wo_stats[str(sid)] = cnt or 0

    # 实时告警统计（按site_id分组）
    rt_alarm_stats = {}
    if S["has_realtime_alarm"]:
        for sid, cnt in conn.execute(
            "SELECT site_id, COUNT(*) FROM realtime_alarm WHERE site_id IS NOT NULL GROUP BY site_id"
        ).fetchall():
            rt_alarm_stats[str(sid)] = cnt or 0

    # 历史告警统计（按site_id分组，受时间窗口限制）
    his_alarm_stats = {}
    if S["has_history_alarm"]:
        his_time_where = ""
        if time_start:
            his_time_where += f" AND alarmraisedtime >= {int(__import__('datetime').datetime.strptime(time_start, '%Y-%m-%d').timestamp() * 1000)}"
        if time_end:
            from datetime import datetime as _dt, timedelta as _td
            end_dt2 = _dt.strptime(time_end, "%Y-%m-%d") + _td(days=1)
            his_time_where += f" AND alarmraisedtime < {int(end_dt2.timestamp() * 1000)}"
        for sid, cnt in conn.execute(
            f"SELECT site_id, COUNT(*) FROM history_alarm WHERE site_id IS NOT NULL{his_time_where} GROUP BY site_id"
        ).fetchall():
            his_alarm_stats[str(sid)] = cnt or 0

    conn.close()

    site_list = []
    for row in rows:
        sid = str(row[0] or '')
        # 尝试用 site_id 匹配 TT 统计，也尝试 site_name
        tt = tt_stats.get(sid, (0, 0, 0))
        if tt == (0, 0, 0) and row[1]:
            tt = tt_stats.get(str(row[1]), (0, 0, 0))
        lat = round(float(row[2]), 6) if row[2] else 0
        lng = round(float(row[3]), 6) if row[3] else 0
        # 自动修正明显交换的经纬度
        if lat < 0 and 0 < lng < 10:
            lat, lng = lng, lat
        site_dict = {
            "site_id": sid,
            "site_name": str(row[1] or ''),
            "lat": lat,
            "lng": lng,
            "region": str(row[4] or ''),
            "province_county": str(row[5] or ''),
            "network_type": str(row[6] or ''),
            "site_type": str(row[7] or ''),
            "vip_site": str(row[8] or ''),
            "hub_site": str(row[9] or ''),
            "tt_count": tt[0],
            "open_tt": tt[1],
            "closed_tt": tt[2],
            "wo_count": wo_stats.get(sid, 0),
            "rt_alarm_count": rt_alarm_stats.get(sid, 0),
            "his_alarm_count": his_alarm_stats.get(sid, 0),
        }
        # 添加筛选列值
        for param_name, idx in filter_col_indices.items():
            site_dict[param_name] = str(row[idx] or '') if idx < len(row) else ''
        site_list.append(site_dict)

    return {
        "sites": site_list,
        "total": len(site_list),
        "regions": regions,
        "filter_options": filter_options,
    }


@router.get("/drilldown/{site_id}")
def get_site_drilldown(site_id: str):
    """站点下钻：基本信息 + 关联TT/WO列表 + SLA达成情况（自适应数据库结构）"""
    S = _detect_gis_schema()
    if not S["site_table"]:
        raise HTTPException(status_code=404, detail="站点表不存在")
    conn = get_raw_connection()
    st = S["site_table"]

    # 站点基本信息
    pragma = conn.execute(f'PRAGMA table_info({st})').fetchall()
    col_names = [c[1] for c in pragma]

    # 构建site_id匹配条件（兼容整数和字符串）
    try:
        site_id_int = int(site_id)
        site_match = "(site_id = ? OR site_id = ?)"
        site_params = (site_id, site_id_int)
    except (ValueError, TypeError):
        site_match = "site_id = ?"
        site_params = (site_id,)

    site_row = conn.execute(
        f'SELECT * FROM {st} WHERE {site_match}',
        site_params
    ).fetchone()

    if not site_row:
        # 尝试用 site_name 匹配
        site_match = "site_name = ?"
        site_params = (site_id,)
        site_row = conn.execute(
            f'SELECT * FROM {st} WHERE {site_match}',
            site_params
        ).fetchone()

    if not site_row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"站点 {site_id} 不存在")

    site_detail = dict(zip(col_names, site_row))

    # 确定 TT 关联方式：优先用 site_id，其次 site_name
    tt_site_match = ""
    tt_site_params = ()
    if S["tt_site_key"] == "site_id":
        try:
            site_id_int = int(site_id)
            tt_site_match = "(site_id = ? OR site_id = ?)"
            tt_site_params = (site_id, site_id_int)
        except (ValueError, TypeError):
            tt_site_match = "site_id = ?"
            tt_site_params = (site_id,)
    elif S["tt_site_key"] == "site_name":
        # 用站点名匹配
        site_name = site_detail.get("site_name", site_id)
        tt_site_match = "site_name = ?"
        tt_site_params = (site_name,)

    # TT列表 - 动态选择存在的列
    tt_available_cols = []
    for col in ["title", "ticket_no", "wo_no", "site_id", "site_name", "site_class",
                "status", "creator", "owner", "ticket_severity", "sla_time", "sla_status",
                "region_id", "region_level1", "created_time", "alarm_occur_time",
                "alarm_clear_time", "root_cause", "sub_root_cause",
                "root_cause_description", "sla_remain_time", "fo_process_detail", "domain"]:
        if col in S["tt_cols"]:
            tt_available_cols.append(col)
    tt_select = ", ".join(tt_available_cols) if tt_available_cols else "*"

    tt_cursor = conn.execute(f"""
        SELECT {tt_select}
        FROM eflow_tt 
        WHERE {tt_site_match}
        ORDER BY alarm_occur_time DESC
        LIMIT 50
    """, tt_site_params)
    tt_cols = [desc[0] for desc in tt_cursor.description]
    tt_list = [dict(zip(tt_cols, row)) for row in tt_cursor.fetchall()]

    # WO列表（仅当表存在时）
    wo_list = []
    if S["has_wo"]:
        try:
            wo_cursor = conn.execute(f"""
                SELECT wo_no, tt_no, title, status, creator, created_time,
                       alarm_occur_time, alarm_clear_time, source,
                       rc_main_category, rc_sub_category, ticket_severity
                FROM eflow_wo 
                WHERE {tt_site_match}
                ORDER BY alarm_occur_time DESC
                LIMIT 50
            """, tt_site_params)
            wo_cols = [desc[0] for desc in wo_cursor.description]
            wo_list = [dict(zip(wo_cols, row)) for row in wo_cursor.fetchall()]
        except Exception:
            pass

    # SLA统计
    sla_cursor = conn.execute(f"""
        SELECT COUNT(*),
               SUM(CASE WHEN status = 'Closed' THEN 1 ELSE 0 END),
               SUM(CASE WHEN sla_status IN ('Pass', 'Within SLA') THEN 1 ELSE 0 END),
               SUM(CASE WHEN sla_status = 'Failed' THEN 1 ELSE 0 END)
        FROM eflow_tt WHERE {tt_site_match}
    """, tt_site_params)
    sla_row = sla_cursor.fetchone()

    # 实时告警列表
    rt_alarm_list = []
    if S["has_realtime_alarm"]:
        try:
            rt_site_match = "(site_id = ? OR site_id = ?)" if site_id.isdigit() else "site_id = ?"
            rt_site_params = (site_id, int(site_id)) if site_id.isdigit() else (site_id,)
            rt_cursor = conn.execute(f"""
                SELECT alarm_title, codename, perceivedseverity, durationname,
                       alarmraisedtime, servertime, site_name, region,
                       restypename, networktype, site_attribute, site_status,
                       transmission_type, ran_type, neip
                FROM realtime_alarm
                WHERE {rt_site_match}
                ORDER BY alarmraisedtime DESC
                LIMIT 100
            """, rt_site_params)
            rt_cols = [desc[0] for desc in rt_cursor.description]
            rt_alarm_list = [dict(zip(rt_cols, row)) for row in rt_cursor.fetchall()]
        except Exception:
            pass

    # 历史告警列表
    his_alarm_list = []
    if S["has_history_alarm"]:
        try:
            his_site_match = "(site_id = ? OR site_id = ?)" if site_id.isdigit() else "site_id = ?"
            his_site_params = (site_id, int(site_id)) if site_id.isdigit() else (site_id,)
            his_cursor = conn.execute(f"""
                SELECT alarm_title, codename, perceivedseverity, durationname,
                       alarmraisedtime, servertime, assigned_time, assign_delay,
                       tt_id, site_name, region, restypename, site_attribute
                FROM history_alarm
                WHERE {his_site_match}
                ORDER BY alarmraisedtime DESC
                LIMIT 100
            """, his_site_params)
            his_cols = [desc[0] for desc in his_cursor.description]
            his_alarm_list = [dict(zip(his_cols, row)) for row in his_cursor.fetchall()]
        except Exception:
            pass

    conn.close()

    return {
        "site_info": site_detail,
        "tt_list": tt_list,
        "tt_count": len(tt_list),
        "wo_list": wo_list,
        "wo_count": len(wo_list),
        "rt_alarm_list": rt_alarm_list,
        "rt_alarm_count": len(rt_alarm_list),
        "his_alarm_list": his_alarm_list,
        "his_alarm_count": len(his_alarm_list),
        "sla_stats": {
            "total_tt": sla_row[0] or 0,
            "closed_tt": sla_row[1] or 0,
            "sla_met": sla_row[2] or 0,
            "sla_violated": sla_row[3] or 0,
        },
    }


@router.get("/regions/summary")
def get_region_summary():
    """按Region汇总（自适应数据库结构）"""
    S = _detect_gis_schema()
    if not S["site_table"]:
        return {"regions": []}
    conn = get_raw_connection()
    st = S["site_table"]
    vip_expr = f"SUM(CASE WHEN {S['vip_col']} = 'Yes' THEN 1 ELSE 0 END)" if S["vip_col"] else "0"
    cursor = conn.execute(f"""
        SELECT region, COUNT(*) as site_count,
               {vip_expr} as vip_count
        FROM {st}
        WHERE region IS NOT NULL AND region != ''
        GROUP BY region ORDER BY site_count DESC
    """)
    cols = [desc[0] for desc in cursor.description]
    result = [dict(zip(cols, row)) for row in cursor.fetchall()]
    conn.close()
    return {"regions": result}


@router.get("/topology")
def get_topology():
    """获取站点拓扑连线数据（含经纬度，自适应数据库结构）"""
    S = _detect_gis_schema()
    if not S["has_topology"] or not S["site_table"]:
        return {"links": [], "total": 0}
    conn = get_raw_connection()
    st = S["site_table"]
    rows = conn.execute(f"""
        SELECT t.site_a_id, t.site_a_name, t.site_b_id, t.site_b_name,
               t.hop_count, t.a_is_hub, t.b_is_hub,
               a.latitude as lat_a, a.longitude as lng_a,
               b.latitude as lat_b, b.longitude as lng_b
        FROM topology t
        LEFT JOIN {st} a ON CAST(t.site_a_id AS TEXT) = CAST(a.site_id AS TEXT)
        LEFT JOIN {st} b ON CAST(t.site_b_id AS TEXT) = CAST(b.site_id AS TEXT)
        WHERE a.latitude IS NOT NULL AND b.latitude IS NOT NULL
    """).fetchall()
    conn.close()
    links = []
    for r in rows:
        links.append({
            "site_a_id": r[0], "site_a_name": r[1],
            "site_b_id": r[2], "site_b_name": r[3],
            "hop_count": r[4], "is_hub_link": bool(r[5] and r[6]),
            "lat_a": r[7], "lng_a": r[8],
            "lat_b": r[9], "lng_b": r[10],
        })
    return {"links": links, "total": len(links)}


@router.get("/region-boundaries")
def get_region_boundaries():
    """获取各Region的Voronoi分区边界（用于地图蒙层，自适应数据库结构）"""
    S = _detect_gis_schema()
    if not S["site_table"]:
        return {"regions": []}
    conn = get_raw_connection()
    st = S["site_table"]

    # 1. 获取所有站点坐标 + region
    sites = conn.execute(f"""
        SELECT site_id, region,
               CAST(latitude AS REAL) as lat,
               CAST(longitude AS REAL) as lng
        FROM {st}
        WHERE region IS NOT NULL AND region != ''
          AND latitude IS NOT NULL AND longitude IS NOT NULL
          AND CAST(latitude AS REAL) != 0
          AND CAST(longitude AS REAL) != 0
    """).fetchall()
    conn.close()

    if len(sites) < 3:
        return {"regions": []}

    # 修正坐标（交换的经纬度）
    def fix_coords(lat, lng):
        if lat < 0 and 0 < lng < 10:
            return lng, lat
        return lat, lng

    # 自适应：根据站点坐标范围确定有效区域和边界
    all_lats = [float(s[2]) for s in sites if s[2]]
    all_lngs = [float(s[3]) for s in sites if s[3]]
    if not all_lats:
        return {"regions": []}
    
    center_lat = sum(all_lats) / len(all_lats)
    center_lng = sum(all_lngs) / len(all_lngs)

    # 检测是否为利比里亚项目（站点中心在利比里亚范围内）
    is_liberia = 4.0 <= center_lat <= 9.0 and -12.0 <= center_lng <= -7.0
    # 检测是否为南非 Gauteng 项目
    is_gauteng = -28.0 <= center_lat <= -24.0 and 26.0 <= center_lng <= 30.0

    if is_liberia:
        VALID_LAT = (4.0, 9.0)
        VALID_LNG = (-12.0, -7.0)
    elif is_gauteng:
        VALID_LAT = (-27.5, -25.0)
        VALID_LNG = (27.0, 29.0)
    else:
        # 通用方案：根据站点实际分布确定有效范围
        lat_margin = (max(all_lats) - min(all_lats)) * 0.1 + 0.01
        lng_margin = (max(all_lngs) - min(all_lngs)) * 0.1 + 0.01
        VALID_LAT = (min(all_lats) - lat_margin, max(all_lats) + lat_margin)
        VALID_LNG = (min(all_lngs) - lng_margin, max(all_lngs) + lng_margin)

    # 过滤有效站点
    valid_sites = []
    for s in sites:
        lat, lng = fix_coords(float(s[2]), float(s[3]))
        if VALID_LAT[0] <= lat <= VALID_LAT[1] and VALID_LNG[0] <= lng <= VALID_LNG[1]:
            valid_sites.append((str(s[0]), str(s[1]), lat, lng))

    if len(valid_sites) < 3:
        return {"regions": []}

    # 2. 计算 Voronoi 图
    coords = np.array([(s[2], s[3]) for s in valid_sites])
    vor = Voronoi(coords)

    # 自适应裁剪边界
    if is_liberia:
        # 利比里亚精确国界多边形（89点，来源: Natural Earth GeoJSON）
        liberia_boundary_coords = [
            (6.9194, -11.4762), (7.0467, -11.3893), (7.1284, -11.3706),
            (7.3452, -11.1442), (7.7055, -10.7306), (8.0392, -10.6031),
            (8.1421, -10.3846), (8.3103, -10.3137), (8.5196, -10.1818),
            (8.4222, -10.0617), (8.4966, -9.8869), (8.5128, -9.8055),
            (8.5500, -9.7630), (8.4733, -9.7155), (8.4096, -9.6759),
            (8.4029, -9.6073), (8.3361, -9.5115), (8.2744, -9.5156),
            (8.1749, -9.5156), (8.0288, -9.4742), (7.9966, -9.4317),
            (7.7419, -9.3555), (7.5595, -9.3837), (7.4210, -9.4702),
            (7.4051, -9.4493), (7.4193, -9.3752), (7.3766, -9.2995),
            (7.2755, -9.1531), (7.2030, -9.1061), (7.2435, -9.0076),
            (7.2486, -8.9254), (7.3576, -8.8606), (7.4508, -8.7904),
            (7.5577, -8.7340), (7.6744, -8.6945), (7.5371, -8.4436),
            (7.2347, -8.3497), (7.1573, -8.3115), (6.9600, -8.3200),
            (6.8503, -8.3150), (6.5600, -8.5471), (6.5261, -8.5894),
            (6.4376, -8.5156), (6.4512, -8.4183), (6.3632, -8.4110),
            (6.3611, -8.3529), (6.3326, -8.2977), (6.2769, -8.1791),
            (6.2978, -8.0157), (6.2568, -7.9100), (6.0815, -7.8618),
            (6.0392, -7.8024), (5.9817, -7.8007), (5.9409, -7.6805),
            (5.8837, -7.5842), (5.8588, -7.5278), (5.8599, -7.4786),
            (5.5690, -7.3841), (5.5118, -7.4081), (5.4049, -7.4460),
            (5.3171, -7.3898), (5.2675, -7.4309), (5.2642, -7.4757),
            (5.0977, -7.5468), (4.9484, -7.5553), (4.8571, -7.5988),
            (4.7843, -7.5796), (4.4352, -7.5657), (4.3472, -7.5933),
            (4.3820, -7.7332), (4.4614, -7.8629), (4.5235, -8.0032),
            (4.6762, -8.4385), (4.9463, -8.9155), (4.9954, -9.0278),
            (5.1373, -9.2620), (5.3205, -9.4708), (5.4250, -9.5594),
            (5.6855, -9.8421), (5.8964, -10.0462), (6.0770, -10.2799),
            (6.1268, -10.3381), (6.2050, -10.4639), (6.2275, -10.6594),
            (6.3349, -10.7891), (6.4377, -10.8243), (6.7889, -11.3699),
            (6.8834, -11.4508), (6.9194, -11.4762),
        ]
        clip_boundary = Polygon(liberia_boundary_coords)
        if not clip_boundary.is_valid:
            clip_boundary = clip_boundary.buffer(0)
        clip_boundary = clip_boundary.buffer(0.03)
    elif is_gauteng:
        # 南非 Gauteng 省边界（从 GeoJSON 文件加载）
        gauteng_poly = _load_boundary_file('gauteng_zaf.geojson')
        if gauteng_poly:
            clip_boundary = gauteng_poly.buffer(0.02)
        else:
            # 文件不存在时回退到凸包
            site_points = [Point(s[2], s[3]) for s in valid_sites]
            clip_boundary = unary_union(site_points).convex_hull.buffer(0.05)
    else:
        # 通用方案：用站点凸包 + buffer 作为裁剪边界
        site_points = [Point(s[2], s[3]) for s in valid_sites]
        clip_boundary = unary_union(site_points).convex_hull.buffer(0.05)

    # 3. 构建每个站点的 Voronoi cell 多边形
    clip_box = box(VALID_LAT[0] - 1, VALID_LNG[0] - 1, VALID_LAT[1] + 1, VALID_LNG[1] + 1)

    def voronoi_cell_polygon(region_idx):
        """获取第 region_idx 个站点的 Voronoi cell 多边形"""
        region = vor.regions[vor.point_region[region_idx]]
        if -1 in region or len(region) == 0:
            return None
        pts = vor.vertices[region]
        # 按角度排序确保多边形正确
        center = pts.mean(axis=0)
        angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
        order = np.argsort(angles)
        pts = pts[order]
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly.intersection(clip_box).intersection(clip_boundary)

    # 4. 按 region 分组，合并同区域的 cells
    region_cells = {}
    for i, (sid, region_name, lat, lng) in enumerate(valid_sites):
        cell = voronoi_cell_polygon(i)
        if cell is not None and not cell.is_empty:
            if region_name not in region_cells:
                region_cells[region_name] = []
            region_cells[region_name].append(cell)

    # 5. 合并每个区域的 cells，平滑、扩展后与国界相交
    # 根据 clip_boundary 面积自适应 buffer（小区域用较小扩展）
    boundary_area = clip_boundary.area
    expand_buffer = 0.08 if boundary_area < 1.0 else 0.25

    region_polygons = {}
    for region_name, cells in region_cells.items():
        merged = unary_union(cells)
        # 先平滑边界（减少锯齿），再扩展确保边缘站点覆盖，最后与国界相交裁剪
        smoothed = merged.simplify(0.02, preserve_topology=True)
        expanded = smoothed.buffer(expand_buffer)
        clipped = expanded.intersection(clip_boundary)
        if not clipped.is_empty:
            region_polygons[region_name] = clipped

    # 6. Catmull-Rom 平滑（纯视觉平滑，不影响覆盖范围）
    def smooth_polygon_ring(ring_coords, steps=4):
        """对闭合环做 Catmull-Rom 平滑"""
        pts = list(ring_coords)
        if len(pts) < 4:
            return pts
        # 确保闭合
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        n = len(pts) - 1  # 不包括重复的终点
        if n < 3:
            return pts

        result = []
        for i in range(n):
            p0 = pts[(i - 1) % n]
            p1 = pts[i]
            p2 = pts[(i + 1) % n]
            p3 = pts[(i + 2) % n]

            for t_idx in range(steps):
                t = t_idx / steps
                # Catmull-Rom 公式
                t2 = t * t
                t3 = t2 * t
                lat = 0.5 * (
                    (2 * p1[0]) +
                    (-p0[0] + p2[0]) * t +
                    (2*p0[0] - 5*p1[0] + 4*p2[0] - p3[0]) * t2 +
                    (-p0[0] + 3*p1[0] - 3*p2[0] + p3[0]) * t3
                )
                lng = 0.5 * (
                    (2 * p1[1]) +
                    (-p0[1] + p2[1]) * t +
                    (2*p0[1] - 5*p1[1] + 4*p2[1] - p3[1]) * t2 +
                    (-p0[1] + 3*p1[1] - 3*p2[1] + p3[1]) * t3
                )
                result.append((lat, lng))
        return result

    def polygon_to_coords(geom):
        """将 shapely 几何体转为坐标列表（取最大外环）"""
        if geom.is_empty:
            return []
        if isinstance(geom, MultiPolygon):
            # 取面积最大的部分
            geom = max(geom.geoms, key=lambda g: g.area)
        if isinstance(geom, Polygon):
            exterior = list(geom.exterior.coords)
            return exterior
        return []

    # 7. 生成结果
    colors = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4', '#ffeaa7', '#dda0dd']
    result = []

    # 统计每个区域的站点数
    region_site_counts = {}
    for sid, region_name, lat, lng in valid_sites:
        region_site_counts[region_name] = region_site_counts.get(region_name, 0) + 1

    for idx, (region_name, merged_geom) in enumerate(sorted(region_polygons.items())):
        coords = polygon_to_coords(merged_geom)
        if len(coords) < 3:
            continue

        # Catmull-Rom 平滑
        smoothed = smooth_polygon_ring(coords, steps=6)
        if len(smoothed) < 3:
            smoothed = coords

        # 转为 [lat, lng] 格式
        polygon = [[round(p[0], 6), round(p[1], 6)] for p in smoothed]

        result.append({
            "region": region_name,
            "polygon": polygon,
            "color": colors[idx % len(colors)],
            "site_count": region_site_counts.get(region_name, 0),
        })

    return {"regions": result}
