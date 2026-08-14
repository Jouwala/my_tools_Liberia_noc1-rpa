"""GIS地理信息 API - Voronoi分区版（全自适应列名）"""
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

# ========== 列名变体映射 ==========
# 常见列名变体 → 标准名
_COL_VARIANTS = {
    "latitude":  ["latitude", "lat"],
    "longitude": ["longitude", "lng", "lon", "long"],
    "site_id":   ["site_id", "siteid", "site_code"],
    "site_name": ["site_name", "sitename", "site_name_new", "name"],
    "region":    ["region", "region_name"],
    "network_type": ["network_type", "network"],
    "site_type": ["site_type", "type"],
}


def _find_col(cols: set, standard_name: str) -> str | None:
    """在列集合中查找标准名或其变体，返回实际列名或None"""
    for variant in _COL_VARIANTS.get(standard_name, [standard_name]):
        if variant in cols:
            return variant
    return None


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

    # 核心列自适应映射
    lat_col = _find_col(site_cols, "latitude")
    lng_col = _find_col(site_cols, "longitude")
    site_id_col = _find_col(site_cols, "site_id")
    site_name_col = _find_col(site_cols, "site_name")
    region_col = _find_col(site_cols, "region")
    network_type_col = _find_col(site_cols, "network_type")
    site_type_col = _find_col(site_cols, "site_type")

    # 其他字段映射
    province_col = "province_county" if "province_county" in site_cols else "province" if "province" in site_cols else None
    vip_col = "vip_site" if "vip_site" in site_cols else "vipsite" if "vipsite" in site_cols else None
    hub_col = "hub_site" if "hub_site" in site_cols else "hubsite" if "hubsite" in site_cols else None

    # TT表关联字段
    tt_cols = set()
    if "eflow_tt" in tables:
        tt_cols = {r[1] for r in conn.execute("PRAGMA table_info(eflow_tt)").fetchall()}
    tt_site_key = "site_id" if "site_id" in tt_cols else "site_name" if "site_name" in tt_cols else None

    # TT表其他列
    tt_status_col = "status" if "status" in tt_cols else None
    tt_alarm_col = "alarm_occur_time" if "alarm_occur_time" in tt_cols else None
    tt_sla_col = "sla_status" if "sla_status" in tt_cols else None

    # WO表
    has_wo = "eflow_wo" in tables
    # topology表
    has_topology = "topology" in tables

    conn.close()

    _gis_schema_cache = {
        "site_table": site_table, "site_cols": site_cols,
        "lat_col": lat_col, "lng_col": lng_col,
        "site_id_col": site_id_col, "site_name_col": site_name_col,
        "region_col": region_col,
        "network_type_col": network_type_col, "site_type_col": site_type_col,
        "province_col": province_col, "vip_col": vip_col, "hub_col": hub_col,
        "tt_site_key": tt_site_key, "tt_status_col": tt_status_col,
        "tt_alarm_col": tt_alarm_col, "tt_sla_col": tt_sla_col,
        "has_wo": has_wo, "has_topology": has_topology,
        "tt_cols": tt_cols,
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
        if geom['type'] == 'Polygon':
            coords = [(p[1], p[0]) for p in geom['coordinates'][0]]
            poly = Polygon(coords)
        elif geom['type'] == 'MultiPolygon':
            polys = [Polygon([(p[1], p[0]) for p in ring[0]]) for ring in geom['coordinates']]
            poly = max(polys, key=lambda p: p.area)
        else:
            return None
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly
    except Exception:
        return None


@router.get("/sites")
def get_sites(
    region: str = Query(None),
    site_type: str = Query(None),
    network_type: str = Query(None),
    time_start: str = Query(None, description="时间窗口开始 YYYY-MM-DD"),
    time_end: str = Query(None, description="时间窗口结束 YYYY-MM-DD"),
):
    """获取站点GIS数据（全自适应列名）"""
    S = _detect_gis_schema()
    if not S["site_table"] or not S["lat_col"] or not S["lng_col"]:
        return {"sites": [], "total": 0, "regions": [],
                "_debug": {"site_table": S.get("site_table"), "lat_col": S.get("lat_col"),
                           "lng_col": S.get("lng_col"), "site_cols": list(S.get("site_cols", []))[:20]}}

    conn = get_raw_connection()
    st = S["site_table"]
    lat_c, lng_c = S["lat_col"], S["lng_col"]
    sid_c = S["site_id_col"] or "NULL"
    sname_c = S["site_name_col"] or "NULL"
    reg_c = S["region_col"]
    net_c = S["network_type_col"] or "NULL"
    stype_c = S["site_type_col"] or "NULL"
    prov_c = S["province_col"] or "NULL"
    vip_c = S["vip_col"] or "NULL"
    hub_c = S["hub_col"] or "NULL"

    where_parts = [
        f"{lat_c} IS NOT NULL",
        f"{lng_c} IS NOT NULL",
        f"CAST({lat_c} AS REAL) != 0",
        f"CAST({lng_c} AS REAL) != 0",
    ]
    params = []

    if region and reg_c:
        where_parts.append(f"{reg_c} = ?")
        params.append(region)
    if site_type and S["site_type_col"]:
        where_parts.append(f"{stype_c} = ?")
        params.append(site_type)
    if network_type and S["network_type_col"]:
        where_parts.append(f"{net_c} = ?")
        params.append(network_type)

    where_clause = " AND ".join(where_parts)

    # TT/WO时间过滤
    tt_time_where = ""
    wo_time_where = ""
    if S["tt_alarm_col"]:
        if time_start:
            tt_time_where += f" AND {S['tt_alarm_col']} >= '{time_start}'"
            wo_time_where += f" AND alarm_occur_time >= '{time_start}'"
        if time_end:
            from datetime import datetime, timedelta
            end_dt = datetime.strptime(time_end, "%Y-%m-%d") + timedelta(days=1)
            end_str = end_dt.strftime("%Y-%m-%d")
            tt_time_where += f" AND {S['tt_alarm_col']} < '{end_str}'"
            wo_time_where += f" AND alarm_occur_time < '{end_str}'"

    sql = f"""
        SELECT 
            {sid_c}, {sname_c},
            CAST({lat_c} AS REAL) as lat,
            CAST({lng_c} AS REAL) as lng,
            {reg_c}, {prov_c}, {net_c}, {stype_c},
            {vip_c}, {hub_c}
        FROM {st}
        WHERE {where_clause}
    """
    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()

    # region列表
    regions = []
    if reg_c:
        regions = [r[0] for r in conn.execute(
            f"SELECT DISTINCT {reg_c} FROM {st} WHERE {reg_c} IS NOT NULL AND {reg_c} != '' ORDER BY {reg_c}"
        ).fetchall()]

    # TT统计
    tt_stats = {}
    if S["tt_site_key"] and S["tt_status_col"]:
        try:
            tt_sql = f"""
                SELECT {S['tt_site_key']}, COUNT(*),
                       SUM(CASE WHEN {S['tt_status_col']} != 'Closed' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN {S['tt_status_col']} = 'Closed' THEN 1 ELSE 0 END)
                FROM eflow_tt WHERE 1=1 {tt_time_where}
                GROUP BY {S['tt_site_key']}
            """
            for sid, cnt, open_cnt, closed_cnt in conn.execute(tt_sql).fetchall():
                tt_stats[str(sid)] = (cnt or 0, open_cnt or 0, closed_cnt or 0)
        except Exception as e:
            pass

    wo_stats = {}
    if S["has_wo"] and S["tt_site_key"]:
        try:
            wo_sql = f"SELECT {S['tt_site_key']}, COUNT(*) FROM eflow_wo WHERE 1=1 {wo_time_where} GROUP BY {S['tt_site_key']}"
            for sid, cnt in conn.execute(wo_sql).fetchall():
                wo_stats[str(sid)] = cnt or 0
        except Exception:
            pass

    conn.close()

    site_list = []
    for row in rows:
        sid = str(row[0] or '')
        tt = tt_stats.get(sid, (0, 0, 0))
        if tt == (0, 0, 0) and row[1]:
            tt = tt_stats.get(str(row[1]), (0, 0, 0))
        lat = round(float(row[2]), 6) if row[2] else 0
        lng = round(float(row[3]), 6) if row[3] else 0
        if lat < 0 and 0 < lng < 10:
            lat, lng = lng, lat
        site_list.append({
            "site_id": sid,
            "site_name": str(row[1] or ''),
            "lat": lat, "lng": lng,
            "region": str(row[4] or ''),
            "province_county": str(row[5] or ''),
            "network_type": str(row[6] or ''),
            "site_type": str(row[7] or ''),
            "vip_site": str(row[8] or ''),
            "hub_site": str(row[9] or ''),
            "tt_count": tt[0], "open_tt": tt[1], "closed_tt": tt[2],
            "wo_count": wo_stats.get(sid, 0),
        })

    return {"sites": site_list, "total": len(site_list), "regions": regions}


@router.get("/drilldown/{site_id}")
def get_site_drilldown(site_id: str):
    """站点下钻（自适应列名）"""
    S = _detect_gis_schema()
    if not S["site_table"]:
        raise HTTPException(status_code=404, detail="站点表不存在")
    conn = get_raw_connection()
    st = S["site_table"]
    sid_c = S["site_id_col"]
    sname_c = S["site_name_col"]

    pragma = conn.execute(f'PRAGMA table_info({st})').fetchall()
    col_names = [c[1] for c in pragma]

    # site_id匹配
    site_match = ""
    site_params = ()
    if sid_c:
        try:
            site_id_int = int(site_id)
            site_match = f"({sid_c} = ? OR {sid_c} = ?)"
            site_params = (site_id, site_id_int)
        except (ValueError, TypeError):
            site_match = f"{sid_c} = ?"
            site_params = (site_id,)

    site_row = None
    if site_match:
        site_row = conn.execute(f'SELECT * FROM {st} WHERE {site_match}', site_params).fetchone()

    if not site_row and sname_c:
        site_match = f"{sname_c} = ?"
        site_params = (site_id,)
        site_row = conn.execute(f'SELECT * FROM {st} WHERE {site_match}', site_params).fetchone()

    if not site_row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"站点 {site_id} 不存在")

    site_detail = dict(zip(col_names, site_row))

    # TT关联
    tt_site_match = ""
    tt_site_params = ()
    if S["tt_site_key"] == "site_id" and sid_c:
        try:
            site_id_int = int(site_id)
            tt_site_match = f"(site_id = ? OR site_id = ?)"
            tt_site_params = (site_id, site_id_int)
        except (ValueError, TypeError):
            tt_site_match = "site_id = ?"
            tt_site_params = (site_id,)
    elif S["tt_site_key"] == "site_name" and sname_c:
        site_name = site_detail.get(sname_c, site_id)
        tt_site_match = "site_name = ?"
        tt_site_params = (site_name,)

    # TT列表
    tt_available_cols = [c for c in S["tt_cols"] if c not in ('_source_file', '_source_sheet', '_import_time')]
    tt_select = ", ".join(tt_available_cols) if tt_available_cols else "1"
    tt_list = []
    if tt_site_match and tt_available_cols:
        try:
            order_clause = f"ORDER BY alarm_occur_time DESC" if "alarm_occur_time" in S["tt_cols"] else ""
            tt_cursor = conn.execute(f"SELECT {tt_select} FROM eflow_tt WHERE {tt_site_match} {order_clause} LIMIT 50", tt_site_params)
            tt_cols_out = [desc[0] for desc in tt_cursor.description]
            tt_list = [dict(zip(tt_cols_out, row)) for row in tt_cursor.fetchall()]
        except Exception:
            pass

    # WO列表
    wo_list = []
    if S["has_wo"] and tt_site_match:
        try:
            wo_cursor = conn.execute(f"""
                SELECT wo_no, tt_no, title, status, creator, created_time,
                       alarm_occur_time, alarm_clear_time, source,
                       rc_main_category, rc_sub_category, ticket_severity
                FROM eflow_wo WHERE {tt_site_match} ORDER BY alarm_occur_time DESC LIMIT 50
            """, tt_site_params)
            wo_cols_out = [desc[0] for desc in wo_cursor.description]
            wo_list = [dict(zip(wo_cols_out, row)) for row in wo_cursor.fetchall()]
        except Exception:
            pass

    # SLA统计
    sla_stats = {"total_tt": 0, "closed_tt": 0, "sla_met": 0, "sla_violated": 0}
    if tt_site_match:
        try:
            status_expr = f"SUM(CASE WHEN {S['tt_status_col']} = 'Closed' THEN 1 ELSE 0 END)" if S["tt_status_col"] else "0"
            sla_expr = f"SUM(CASE WHEN {S['tt_sla_col']} IN ('Pass', 'Within SLA') THEN 1 ELSE 0 END)" if S["tt_sla_col"] else "0"
            sla_failed = f"SUM(CASE WHEN {S['tt_sla_col']} = 'Failed' THEN 1 ELSE 0 END)" if S["tt_sla_col"] else "0"
            sla_row = conn.execute(f"""
                SELECT COUNT(*), {status_expr}, {sla_expr}, {sla_failed}
                FROM eflow_tt WHERE {tt_site_match}
            """, tt_site_params).fetchone()
            sla_stats = {"total_tt": sla_row[0] or 0, "closed_tt": sla_row[1] or 0,
                         "sla_met": sla_row[2] or 0, "sla_violated": sla_row[3] or 0}
        except Exception:
            pass

    conn.close()
    return {
        "site_info": site_detail, "tt_list": tt_list, "tt_count": len(tt_list),
        "wo_list": wo_list, "wo_count": len(wo_list), "sla_stats": sla_stats,
    }


@router.get("/regions/summary")
def get_region_summary():
    """按Region汇总"""
    S = _detect_gis_schema()
    if not S["site_table"] or not S["region_col"]:
        return {"regions": []}
    conn = get_raw_connection()
    st = S["site_table"]
    reg_c = S["region_col"]
    vip_expr = f"SUM(CASE WHEN {S['vip_col']} = 'Yes' THEN 1 ELSE 0 END)" if S["vip_col"] else "0"
    cursor = conn.execute(f"""
        SELECT {reg_c}, COUNT(*) as site_count, {vip_expr} as vip_count
        FROM {st} WHERE {reg_c} IS NOT NULL AND {reg_c} != ''
        GROUP BY {reg_c} ORDER BY site_count DESC
    """)
    cols = [desc[0] for desc in cursor.description]
    result = [dict(zip(cols, row)) for row in cursor.fetchall()]
    conn.close()
    return {"regions": result}


@router.get("/topology")
def get_topology():
    """获取站点拓扑连线数据"""
    S = _detect_gis_schema()
    if not S["has_topology"] or not S["site_table"]:
        return {"links": [], "total": 0}
    conn = get_raw_connection()
    st = S["site_table"]
    lat_c = S["lat_col"] or "NULL"
    lng_c = S["lng_col"] or "NULL"
    sid_c = S["site_id_col"] or "site_id"
    rows = conn.execute(f"""
        SELECT t.site_a_id, t.site_a_name, t.site_b_id, t.site_b_name,
               t.hop_count, t.a_is_hub, t.b_is_hub,
               CAST(a.{lat_c} AS REAL) as lat_a, CAST(a.{lng_c} AS REAL) as lng_a,
               CAST(b.{lat_c} AS REAL) as lat_b, CAST(b.{lng_c} AS REAL) as lng_b
        FROM topology t
        LEFT JOIN {st} a ON CAST(t.site_a_id AS TEXT) = CAST(a.{sid_c} AS TEXT)
        LEFT JOIN {st} b ON CAST(t.site_b_id AS TEXT) = CAST(b.{sid_c} AS TEXT)
        WHERE a.{lat_c} IS NOT NULL AND b.{lat_c} IS NOT NULL
    """).fetchall()
    conn.close()
    links = []
    for r in rows:
        links.append({
            "site_a_id": r[0], "site_a_name": r[1], "site_b_id": r[2], "site_b_name": r[3],
            "hop_count": r[4], "is_hub_link": bool(r[5] and r[6]),
            "lat_a": r[7], "lng_a": r[8], "lat_b": r[9], "lng_b": r[10],
        })
    return {"links": links, "total": len(links)}


@router.get("/region-boundaries")
def get_region_boundaries():
    """获取各Region的Voronoi分区边界"""
    S = _detect_gis_schema()
    if not S["site_table"] or not S["lat_col"] or not S["lng_col"]:
        return {"regions": []}
    conn = get_raw_connection()
    st = S["site_table"]
    lat_c, lng_c = S["lat_col"], S["lng_col"]
    sid_c = S["site_id_col"] or "NULL"
    reg_c = S["region_col"] or "NULL"

    if reg_c == "NULL":
        conn.close()
        return {"regions": []}

    sites = conn.execute(f"""
        SELECT {sid_c}, {reg_c},
               CAST({lat_c} AS REAL) as lat,
               CAST({lng_c} AS REAL) as lng
        FROM {st}
        WHERE {reg_c} IS NOT NULL AND {reg_c} != ''
          AND {lat_c} IS NOT NULL AND {lng_c} IS NOT NULL
          AND CAST({lat_c} AS REAL) != 0
          AND CAST({lng_c} AS REAL) != 0
    """).fetchall()
    conn.close()

    if len(sites) < 3:
        return {"regions": []}

    def fix_coords(lat, lng):
        if lat < 0 and 0 < lng < 10:
            return lng, lat
        return lat, lng

    all_lats = [float(s[2]) for s in sites if s[2]]
    all_lngs = [float(s[3]) for s in sites if s[3]]
    if not all_lats:
        return {"regions": []}

    center_lat = sum(all_lats) / len(all_lats)
    center_lng = sum(all_lngs) / len(all_lngs)

    is_liberia = 4.0 <= center_lat <= 9.0 and -12.0 <= center_lng <= -7.0
    is_gauteng = -28.0 <= center_lat <= -24.0 and 26.0 <= center_lng <= 30.0

    if is_liberia:
        VALID_LAT, VALID_LNG = (4.0, 9.0), (-12.0, -7.0)
    elif is_gauteng:
        VALID_LAT, VALID_LNG = (-27.5, -25.0), (27.0, 29.0)
    else:
        lat_margin = (max(all_lats) - min(all_lats)) * 0.1 + 0.01
        lng_margin = (max(all_lngs) - min(all_lngs)) * 0.1 + 0.01
        VALID_LAT = (min(all_lats) - lat_margin, max(all_lats) + lat_margin)
        VALID_LNG = (min(all_lngs) - lng_margin, max(all_lngs) + lng_margin)

    valid_sites = []
    for s in sites:
        lat, lng = fix_coords(float(s[2]), float(s[3]))
        if VALID_LAT[0] <= lat <= VALID_LAT[1] and VALID_LNG[0] <= lng <= VALID_LNG[1]:
            valid_sites.append((str(s[0]), str(s[1]), lat, lng))

    if len(valid_sites) < 3:
        return {"regions": []}

    coords = np.array([(s[2], s[3]) for s in valid_sites])
    vor = Voronoi(coords)

    if is_liberia:
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
        gauteng_poly = _load_boundary_file('gauteng_zaf.geojson')
        if gauteng_poly:
            clip_boundary = gauteng_poly.buffer(0.02)
        else:
            site_points = [Point(s[2], s[3]) for s in valid_sites]
            clip_boundary = unary_union(site_points).convex_hull.buffer(0.05)
    else:
        site_points = [Point(s[2], s[3]) for s in valid_sites]
        clip_boundary = unary_union(site_points).convex_hull.buffer(0.05)

    clip_box = box(VALID_LAT[0] - 1, VALID_LNG[0] - 1, VALID_LAT[1] + 1, VALID_LNG[1] + 1)

    def voronoi_cell_polygon(region_idx):
        region = vor.regions[vor.point_region[region_idx]]
        if -1 in region or len(region) == 0:
            return None
        pts = vor.vertices[region]
        center = pts.mean(axis=0)
        angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
        order = np.argsort(angles)
        pts = pts[order]
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly.intersection(clip_box).intersection(clip_boundary)

    region_cells = {}
    for i, (sid, region_name, lat, lng) in enumerate(valid_sites):
        cell = voronoi_cell_polygon(i)
        if cell is not None and not cell.is_empty:
            region_cells.setdefault(region_name, []).append(cell)

    boundary_area = clip_boundary.area
    expand_buffer = 0.08 if boundary_area < 1.0 else 0.25

    region_polygons = {}
    for region_name, cells in region_cells.items():
        merged = unary_union(cells)
        smoothed = merged.simplify(0.02, preserve_topology=True)
        expanded = smoothed.buffer(expand_buffer)
        clipped = expanded.intersection(clip_boundary)
        if not clipped.is_empty:
            region_polygons[region_name] = clipped

    def smooth_polygon_ring(ring_coords, steps=4):
        pts = list(ring_coords)
        if len(pts) < 4:
            return pts
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        n = len(pts) - 1
        if n < 3:
            return pts
        result = []
        for i in range(n):
            p0, p1, p2, p3 = pts[(i-1)%n], pts[i], pts[(i+1)%n], pts[(i+2)%n]
            for t_idx in range(steps):
                t = t_idx / steps
                t2, t3 = t*t, t*t*t
                result.append((
                    0.5*((2*p1[0])+(-p0[0]+p2[0])*t+(2*p0[0]-5*p1[0]+4*p2[0]-p3[0])*t2+(-p0[0]+3*p1[0]-3*p2[0]+p3[0])*t3),
                    0.5*((2*p1[1])+(-p0[1]+p2[1])*t+(2*p0[1]-5*p1[1]+4*p2[1]-p3[1])*t2+(-p0[1]+3*p1[1]-3*p2[1]+p3[1])*t3),
                ))
        return result

    def polygon_to_coords(geom):
        if geom.is_empty:
            return []
        if isinstance(geom, MultiPolygon):
            geom = max(geom.geoms, key=lambda g: g.area)
        if isinstance(geom, Polygon):
            return list(geom.exterior.coords)
        return []

    colors = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4', '#ffeaa7', '#dda0dd']
    result = []
    region_site_counts = {}
    for sid, region_name, lat, lng in valid_sites:
        region_site_counts[region_name] = region_site_counts.get(region_name, 0) + 1

    for idx, (region_name, merged_geom) in enumerate(sorted(region_polygons.items())):
        coords = polygon_to_coords(merged_geom)
        if len(coords) < 3:
            continue
        smoothed = smooth_polygon_ring(coords, steps=6)
        if len(smoothed) < 3:
            smoothed = coords
        polygon = [[round(p[0], 6), round(p[1], 6)] for p in smoothed]
        result.append({
            "region": region_name, "polygon": polygon,
            "color": colors[idx % len(colors)],
            "site_count": region_site_counts.get(region_name, 0),
        })

    return {"regions": result}
