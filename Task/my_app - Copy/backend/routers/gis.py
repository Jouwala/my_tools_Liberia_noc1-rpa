"""GIS地理信息 API - 优化版"""
import sqlite3
from fastapi import APIRouter, Query, HTTPException
from backend.database import get_raw_connection, DB_PATH

router = APIRouter(prefix="/api/gis", tags=["gis"])


@router.get("/sites")
def get_sites(
    region: str = Query(None),
    site_type: str = Query(None),
    network_type: str = Query(None),
    time_start: str = Query(None, description="时间窗口开始 YYYY-MM-DD"),
    time_end: str = Query(None, description="时间窗口结束 YYYY-MM-DD"),
):
    """获取站点GIS数据 - 含TT/WO统计，支持时间窗口过滤"""
    conn = get_raw_connection()

    where_parts = [
        "latitude IS NOT NULL",
        "longitude IS NOT NULL",
        "CAST(latitude AS REAL) != 0",
        "CAST(longitude AS REAL) != 0",
    ]
    params = []

    if region:
        where_parts.append("region = ?")
        params.append(region)
    if site_type:
        where_parts.append("site_type = ?")
        params.append(site_type)
    if network_type:
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
        # +1天包含结束日当天全天
        from datetime import datetime, timedelta
        end_dt = datetime.strptime(time_end, "%Y-%m-%d") + timedelta(days=1)
        end_str = end_dt.strftime("%Y-%m-%d")
        tt_time_where += f" AND alarm_occur_time < '{end_str}'"
        wo_time_where += f" AND alarm_occur_time < '{end_str}'"

    sql = f"""
        SELECT 
            site_id, site_name,
            CAST(latitude AS REAL) as lat,
            CAST(longitude AS REAL) as lng,
            region, province_county, network_type, site_type,
            vip_site, hub_site
        FROM master_site_db
        WHERE {where_clause}
    """

    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()

    # 获取region列表
    regions_cursor = conn.execute(
        "SELECT DISTINCT region FROM master_site_db WHERE region IS NOT NULL AND region != '' ORDER BY region"
    )
    regions = [r[0] for r in regions_cursor.fetchall()]

    # 预计算TT统计（用Python dict合并，避免SQLite JOIN慢）
    tt_stats = {}
    tt_sql = f"""
        SELECT site_id, COUNT(*),
               SUM(CASE WHEN status != 'Closed' THEN 1 ELSE 0 END),
               SUM(CASE WHEN status = 'Closed' THEN 1 ELSE 0 END)
        FROM eflow_tt WHERE 1=1 {tt_time_where}
        GROUP BY site_id
    """
    for sid, cnt, open_cnt, closed_cnt in conn.execute(tt_sql).fetchall():
        tt_stats[str(sid)] = (cnt or 0, open_cnt or 0, closed_cnt or 0)

    wo_stats = {}
    wo_sql = f"SELECT site_id, COUNT(*) FROM eflow_wo WHERE 1=1 {wo_time_where} GROUP BY site_id"
    for sid, cnt in conn.execute(wo_sql).fetchall():
        wo_stats[str(sid)] = cnt or 0

    conn.close()

    site_list = []
    for row in rows:
        sid = str(row[0] or '')
        tt = tt_stats.get(sid, (0, 0, 0))
        lat = round(float(row[2]), 6) if row[2] else 0
        lng = round(float(row[3]), 6) if row[3] else 0
        # 自动修夌明显交换的经纬度
        if lat < 0 and 0 < lng < 10:
            lat, lng = lng, lat
        site_list.append({
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
        })

    return {
        "sites": site_list,
        "total": len(site_list),
        "regions": regions,
    }


@router.get("/drilldown/{site_id}")
def get_site_drilldown(site_id: str):
    """站点下钻：基本信息 + 关联TT/WO列表 + SLA达成情况"""
    conn = get_raw_connection()

    # 站点基本信息
    pragma = conn.execute('PRAGMA table_info(master_site_db)').fetchall()
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
        f'SELECT * FROM master_site_db WHERE {site_match}',
        site_params
    ).fetchone()

    if not site_row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"站点 {site_id} 不存在")

    site_detail = dict(zip(col_names, site_row))

    # TT列表
    tt_cursor = conn.execute(f"""
        SELECT title, ticket_no, wo_no, site_id, site_name, site_class,
               status, creator, ticket_severity, sla_time, sla_status,
               region_id, created_time, alarm_occur_time,
               alarm_clear_time, root_cause, sub_root_cause,
               root_cause_description, sla_remain_time, fo_process_detail
        FROM eflow_tt 
        WHERE {site_match}
        ORDER BY alarm_occur_time DESC
        LIMIT 50
    """, site_params)
    tt_cols = [desc[0] for desc in tt_cursor.description]
    tt_list = [dict(zip(tt_cols, row)) for row in tt_cursor.fetchall()]

    # WO列表
    wo_cursor = conn.execute(f"""
        SELECT wo_no, tt_no, title, status, creator, created_time,
               last_modified_time, operation_step, ticket_severity,
               ne_type, vendor, alarm_occur_time, alarm_clear_time,
               source, project_name, template, description,
               alarm_severity, fault_duration_time, sla_time,
               expected_finish_time_e2e_sla_deadline_time,
               region_id, site_id, site_name, site_type,
               site_information, site_class, organization_id,
               vip_site, hub_site
        FROM eflow_wo 
        WHERE {site_match}
        ORDER BY alarm_occur_time DESC
        LIMIT 50
    """, site_params)
    wo_cols = [desc[0] for desc in wo_cursor.description]
    wo_list = [dict(zip(wo_cols, row)) for row in wo_cursor.fetchall()]

    # SLA统计
    sla_cursor = conn.execute(f"""
        SELECT COUNT(*),
               SUM(CASE WHEN status = 'Closed' THEN 1 ELSE 0 END),
               SUM(CASE WHEN sla_status IN ('Pass', 'Within SLA') THEN 1 ELSE 0 END),
               SUM(CASE WHEN sla_status = 'Failed' THEN 1 ELSE 0 END)
        FROM eflow_tt WHERE {site_match}
    """, site_params)
    sla_row = sla_cursor.fetchone()

    conn.close()

    return {
        "site_info": site_detail,
        "tt_list": tt_list,
        "tt_count": len(tt_list),
        "wo_list": wo_list,
        "wo_count": len(wo_list),
        "sla_stats": {
            "total_tt": sla_row[0] or 0,
            "closed_tt": sla_row[1] or 0,
            "sla_met": sla_row[2] or 0,
            "sla_violated": sla_row[3] or 0,
        },
    }


@router.get("/regions/summary")
def get_region_summary():
    """按Region汇总"""
    conn = get_raw_connection()
    cursor = conn.execute("""
        SELECT region, COUNT(*) as site_count,
               SUM(CASE WHEN vip_site = 'Yes' THEN 1 ELSE 0 END) as vip_count
        FROM master_site_db 
        WHERE region IS NOT NULL AND region != ''
        GROUP BY region ORDER BY site_count DESC
    """)
    cols = [desc[0] for desc in cursor.description]
    result = [dict(zip(cols, row)) for row in cursor.fetchall()]
    conn.close()
    return {"regions": result}


@router.get("/topology")
def get_topology():
    """获取站点拓扑连线数据（含经纬度）"""
    conn = get_raw_connection()
    rows = conn.execute("""
        SELECT t.site_a_id, t.site_a_name, t.site_b_id, t.site_b_name,
               t.hop_count, t.a_is_hub, t.b_is_hub,
               a.latitude as lat_a, a.longitude as lng_a,
               b.latitude as lat_b, b.longitude as lng_b
        FROM topology t
        LEFT JOIN master_site_db a ON CAST(t.site_a_id AS TEXT) = CAST(a.site_id AS TEXT)
        LEFT JOIN master_site_db b ON CAST(t.site_b_id AS TEXT) = CAST(b.site_id AS TEXT)
        WHERE a.latitude IS NOT NULL AND b.latitude IS NOT NULL
    """).fetchall()
    conn.close()
    links = []
    for r in rows:
        links.append({
            "site_a_id": r[0],
            "site_a_name": r[1],
            "site_b_id": r[2],
            "site_b_name": r[3],
            "hop_count": r[4],
            "is_hub_link": bool(r[5] and r[6]),
            "lat_a": r[7],
            "lng_a": r[8],
            "lat_b": r[9],
            "lng_b": r[10],
        })
    return {"links": links, "total": len(links)}


@router.get("/region-boundaries")
def get_region_boundaries():
    """获取各Region的站点凸包边界（用于地图蒙层）"""
    conn = get_raw_connection()
    regions = conn.execute(
        "SELECT DISTINCT region FROM master_site_db WHERE region IS NOT NULL AND region != ''"
    ).fetchall()

    result = []
    colors = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4', '#ffeaa7', '#dda0dd']

    # 利比里亚大致范围
    VALID_LAT = (4.0, 9.0)
    VALID_LNG = (-12.0, -7.0)

    def fix_coords(lat, lng):
        """自动修正明显交换的经纬度"""
        if lat < 0 and 0 < lng < 10:
            return lng, lat
        return lat, lng

    def convex_hull(points):
        """Andrew's monotone chain convex hull algorithm"""
        points = sorted(set(points))
        if len(points) <= 1:
            return points
        lower = []
        for p in points:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
                lower.pop()
            lower.append(p)
        upper = []
        for p in reversed(points):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
                upper.pop()
            upper.append(p)
        return lower[:-1] + upper[:-1]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def point_to_seg_dist(p, a, b):
        """点p到线段ab的距离"""
        dx, dy = b[0] - a[0], b[1] - a[1]
        if dx == 0 and dy == 0:
            return ((p[0] - a[0])**2 + (p[1] - a[1])**2) ** 0.5
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx*dx + dy*dy)))
        proj = (a[0] + t * dx, a[1] + t * dy)
        return ((p[0] - proj[0])**2 + (p[1] - proj[1])**2) ** 0.5

    def segments_intersect(a, b, c, d):
        """检查线段ab和cd是否相交"""
        d1 = cross(c, d, a)
        d2 = cross(c, d, b)
        d3 = cross(a, b, c)
        d4 = cross(a, b, d)
        if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
           ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
            return True
        return False

    def concave_hull(points, max_iter=80):
        """凹包算法：从凸包开始，迭代将最长边向内凹陷到内部点"""
        hull = convex_hull(points)
        if len(hull) < 3:
            return hull
        hull_set = set(hull)
        interior = [p for p in set(points) if p not in hull_set]
        if not interior:
            return hull

        # 计算平均边长作为阈值基准
        n = len(hull)
        edge_lens = []
        for i in range(n):
            a, b = hull[i], hull[(i+1) % n]
            edge_lens.append(((a[0]-b[0])**2 + (a[1]-b[1])**2) ** 0.5)
        avg_edge = sum(edge_lens) / len(edge_lens) if edge_lens else 0.01
        threshold = avg_edge * 0.6  # 边长超过平均值60%就尝试凹陷

        for _ in range(max_iter):
            n = len(hull)
            if n < 3:
                break
            # 找最长边
            max_len = 0
            max_idx = -1
            for i in range(n):
                a, b = hull[i], hull[(i+1) % n]
                d = ((a[0]-b[0])**2 + (a[1]-b[1])**2) ** 0.5
                if d > max_len:
                    max_len = d
                    max_idx = i
            if max_len < threshold or not interior:
                break

            a = hull[max_idx]
            b = hull[(max_idx + 1) % n]
            # 找距该边中点最近的内部点
            mid = ((a[0]+b[0])/2, (a[1]+b[1])/2)
            best_pt = None
            best_dist = float('inf')
            for p in interior:
                d = ((p[0]-mid[0])**2 + (p[1]-mid[1])**2) ** 0.5
                if d < best_dist:
                    # 确保点到边的距离不太小（避免共线的点）
                    seg_d = point_to_seg_dist(p, a, b)
                    if seg_d > avg_edge * 0.05:
                        best_dist = d
                        best_pt = p
            if best_pt is None:
                break

            # 检查新边(a->best_pt, best_pt->b)是否与其他边相交
            ok = True
            for i in range(n):
                if i == max_idx:
                    continue
                c, d = hull[i], hull[(i+1) % n]
                if segments_intersect(a, best_pt, c, d) or segments_intersect(best_pt, b, c, d):
                    ok = False
                    break
            if not ok:
                interior.remove(best_pt)
                continue

            # 插入凹点
            hull.insert(max_idx + 1, best_pt)
            interior.remove(best_pt)

        return hull

    for idx, (region_name,) in enumerate(regions):
        sites = conn.execute(
            "SELECT latitude, longitude FROM master_site_db WHERE region = ? AND latitude IS NOT NULL AND longitude IS NOT NULL",
            (region_name,)
        ).fetchall()

        if len(sites) < 3:
            continue

        # 校正坐标并过滤有效点
        raw_points = []
        for s in sites:
            lat, lng = float(s[0]), float(s[1])
            lat, lng = fix_coords(lat, lng)
            if VALID_LAT[0] <= lat <= VALID_LAT[1] and VALID_LNG[0] <= lng <= VALID_LNG[1]:
                raw_points.append((lat, lng))

        if len(raw_points) < 3:
            continue

        # 用IQR方法过滤离群点（对lat和lng分别过滤）
        def iqr_filter(values):
            s = sorted(values)
            n = len(s)
            q1 = s[n // 4]
            q3 = s[3 * n // 4]
            iqr = q3 - q1
            return q1 - 1.5 * iqr, q3 + 1.5 * iqr

        lats = [p[0] for p in raw_points]
        lngs = [p[1] for p in raw_points]
        lat_lo, lat_hi = iqr_filter(lats)
        lng_lo, lng_hi = iqr_filter(lngs)
        points = [p for p in raw_points
                  if lat_lo <= p[0] <= lat_hi and lng_lo <= p[1] <= lng_hi]

        if len(points) < 3:
            points = raw_points

        # 再用距离过滤：移除距中心最远的20%站点
        med_lat = sorted([p[0] for p in points])[len(points) // 2]
        med_lng = sorted([p[1] for p in points])[len(points) // 2]
        dists = sorted(
            [(((p[0] - med_lat)**2 + (p[1] - med_lng)**2)**0.5, p) for p in points],
            key=lambda x: x[0]
        )
        keep_count = max(3, int(len(dists) * 0.80))
        points = [d[1] for d in dists[:keep_count]]

        hull = concave_hull(points)
        if len(hull) < 3:
            continue

        # 微量扩展2%（仅视觉缓冲）
        center_lat = sum(p[0] for p in hull) / len(hull)
        center_lng = sum(p[1] for p in hull) / len(hull)
        expanded = []
        for lat, lng in hull:
            e_lat = center_lat + (lat - center_lat) * 1.02
            e_lng = center_lng + (lng - center_lng) * 1.02
            expanded.append([e_lat, e_lng])

        result.append({
            "region": region_name,
            "polygon": expanded,
            "color": colors[idx % len(colors)],
            "site_count": len(sites),
        })

    conn.close()
    return {"regions": result}
