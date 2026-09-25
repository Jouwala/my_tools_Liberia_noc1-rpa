"""GIS 几何计算模块 —— 从 gis.py 拆分出的 Voronoi 分区 / 边界裁剪 / 平滑逻辑

职责边界：
- 本模块只做几何计算（shapely / scipy / numpy），不访问数据库、不依赖 FastAPI。
- gis.py 负责 SQL 查询与接口组装，调用本模块完成边界几何生成。

P2#8 重构（2026-08-03）：原 get_region_boundaries (CC=48, 254 行) 的几何部分
全部下沉至此，拆分为多个单一职责函数。
"""
import os
import json
import logging

import numpy as np
from scipy.spatial import Voronoi
from shapely.geometry import Polygon, MultiPolygon, box, Point
from shapely.ops import unary_union

logger = logging.getLogger(__name__)

# ========== 利比里亚国界（89点，来源: Natural Earth GeoJSON，lat, lng） ==========
LIBERIA_BOUNDARY_COORDS = [
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

# Region 配色（循环使用）
REGION_COLORS = ['#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4', '#ffeaa7', '#dda0dd']

# 县（County）边界静态资源目录（2026-09-25 新增）
# 数据来源：用户提供的「利比里亚地图文件_国家边界含州名.txt」，
# 由一次性脚本 TMP/_gen_county_geojson.py 转为 GeoJSON 后入库。
GEOJSON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "gis")
COUNTIES_FILE = "liberia_counties.geojson"
COUNTRY_FILE = "liberia_country.geojson"


# ========== 基础几何工具 ==========

def fix_coords(lat: float, lng: float):
    """自动修正明显交换的经纬度，返回 (lat, lng)"""
    if lat < 0 and 0 < lng < 10:
        return lng, lat
    return lat, lng


def load_boundary_file(filename: str):
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
        logger.warning("[SILENT-EXCEPT] load_boundary_file: exception swallowed", exc_info=True)
        return None


def determine_valid_bounds(all_lats: list, all_lngs: list):
    """根据站点坐标范围确定项目区域与有效边界。

    Returns:
        (is_liberia, is_gauteng, VALID_LAT, VALID_LNG)
    """
    center_lat = sum(all_lats) / len(all_lats)
    center_lng = sum(all_lngs) / len(all_lngs)

    # 检测是否为利比里亚项目（站点中心在利比里亚范围内）
    is_liberia = 4.0 <= center_lat <= 9.0 and -12.0 <= center_lng <= -7.0
    # 检测是否为南非 Gauteng 项目
    is_gauteng = -28.0 <= center_lat <= -24.0 and 26.0 <= center_lng <= 30.0

    if is_liberia:
        valid_lat = (4.0, 9.0)
        valid_lng = (-12.0, -7.0)
    elif is_gauteng:
        valid_lat = (-27.5, -25.0)
        valid_lng = (27.0, 29.0)
    else:
        # 通用方案：根据站点实际分布确定有效范围
        lat_margin = (max(all_lats) - min(all_lats)) * 0.1 + 0.01
        lng_margin = (max(all_lngs) - min(all_lngs)) * 0.1 + 0.01
        valid_lat = (min(all_lats) - lat_margin, max(all_lats) + lat_margin)
        valid_lng = (min(all_lngs) - lng_margin, max(all_lngs) + lng_margin)
    return is_liberia, is_gauteng, valid_lat, valid_lng


def filter_valid_sites(sites, valid_lat, valid_lng):
    """过滤并修正坐标，返回 [(site_id, region, lat, lng), ...]"""
    valid_sites = []
    for s in sites:
        lat, lng = fix_coords(float(s[2]), float(s[3]))
        if valid_lat[0] <= lat <= valid_lat[1] and valid_lng[0] <= lng <= valid_lng[1]:
            valid_sites.append((str(s[0]), str(s[1]), lat, lng))
    return valid_sites


def build_clip_boundary(is_liberia: bool, is_gauteng: bool, valid_sites: list):
    """构建 Voronoi 裁剪边界：利比里亚国界 / Gauteng 省界 / 站点凸包兜底"""
    if is_liberia:
        clip_boundary = Polygon(LIBERIA_BOUNDARY_COORDS)
        if not clip_boundary.is_valid:
            clip_boundary = clip_boundary.buffer(0)
        return clip_boundary.buffer(0.03)

    if is_gauteng:
        # 南非 Gauteng 省边界（从 GeoJSON 文件加载）
        gauteng_poly = load_boundary_file('gauteng_zaf.geojson')
        if gauteng_poly:
            return gauteng_poly.buffer(0.02)

    # 通用方案（含 Gauteng 文件缺失回退）：站点凸包 + buffer
    site_points = [Point(s[2], s[3]) for s in valid_sites]
    return unary_union(site_points).convex_hull.buffer(0.05)


# ========== Voronoi 计算 ==========

def voronoi_cell_polygon(vor, region_idx: int, clip_box, clip_boundary):
    """获取第 region_idx 个站点的 Voronoi cell 多边形（已裁剪）"""
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


def group_region_cells(vor, valid_sites, clip_box, clip_boundary):
    """按 region 分组收集各站点的 Voronoi cell，返回 {region_name: [geom, ...]}"""
    region_cells = {}
    for i, (sid, region_name, lat, lng) in enumerate(valid_sites):
        cell = voronoi_cell_polygon(vor, i, clip_box, clip_boundary)
        if cell is not None and not cell.is_empty:
            region_cells.setdefault(region_name, []).append(cell)
    return region_cells


def merge_region_polygons(region_cells: dict, clip_boundary):
    """合并每个区域的 cells：平滑 → 扩展 → 与国界相交裁剪，返回 {region_name: geom}"""
    # 根据 clip_boundary 面积自适应 buffer（小区域用较小扩展）
    expand_buffer = 0.08 if clip_boundary.area < 1.0 else 0.25
    region_polygons = {}
    for region_name, cells in region_cells.items():
        merged = unary_union(cells)
        # 先平滑边界（减少锯齿），再扩展确保边缘站点覆盖，最后与国界相交裁剪
        smoothed = merged.simplify(0.02, preserve_topology=True)
        expanded = smoothed.buffer(expand_buffer)
        clipped = expanded.intersection(clip_boundary)
        if not clipped.is_empty:
            region_polygons[region_name] = clipped
    return region_polygons


# ========== 平滑与序列化 ==========

def smooth_polygon_ring(ring_coords, steps: int = 4):
    """对闭合环做 Catmull-Rom 平滑（纯视觉平滑，不影响覆盖范围）"""
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
        return list(geom.exterior.coords)
    return []


def build_region_payload(region_polygons: dict, valid_sites: list):
    """将合并后的 region 几何体转为接口返回结构（含 Catmull-Rom 平滑）"""
    # 统计每个区域的站点数
    region_site_counts = {}
    for sid, region_name, lat, lng in valid_sites:
        region_site_counts[region_name] = region_site_counts.get(region_name, 0) + 1

    result = []
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
            "color": REGION_COLORS[idx % len(REGION_COLORS)],
            "site_count": region_site_counts.get(region_name, 0),
        })
    return result


def compute_region_boundaries(sites: list) -> dict:
    """Region Voronoi 边界计算主流程（纯几何，输入为 DB 查询结果行）。

    Args:
        sites: [(site_id, region, lat, lng), ...] 原始 DB 行

    Returns:
        {"regions": [...]}；站点不足时返回 {"regions": []}
    """
    if len(sites) < 3:
        return {"regions": []}

    all_lats = [float(s[2]) for s in sites if s[2]]
    all_lngs = [float(s[3]) for s in sites if s[3]]
    if not all_lats:
        return {"regions": []}

    is_liberia, is_gauteng, valid_lat, valid_lng = determine_valid_bounds(all_lats, all_lngs)
    valid_sites = filter_valid_sites(sites, valid_lat, valid_lng)
    if len(valid_sites) < 3:
        return {"regions": []}

    # 计算 Voronoi 图
    coords = np.array([(s[2], s[3]) for s in valid_sites])
    vor = Voronoi(coords)

    clip_boundary = build_clip_boundary(is_liberia, is_gauteng, valid_sites)
    clip_box = box(valid_lat[0] - 1, valid_lng[0] - 1, valid_lat[1] + 1, valid_lng[1] + 1)

    region_cells = group_region_cells(vor, valid_sites, clip_box, clip_boundary)
    region_polygons = merge_region_polygons(region_cells, clip_boundary)
    return {"regions": build_region_payload(region_polygons, valid_sites)}


# ========== 真实县（County）行政边界（2026-09-25 新增） ==========

def _merge_multipolygon_payload(geojson_path: str) -> list:
    """读取 GeoJSON → [{name, db_name, polygons: [[[lat,lng],...], ...]}]

    容错：文件不存在 / 解析失败 / 无 features 时返回 []，由调用方降级为空结果。
    GeoJSON 存的是 [lng, lat]，此处**不**再交换 —— 生成脚本已按 Leaflet 约定
    写成 [lat, lng]，重复交换会把地图画到南极洲。
    """
    if not os.path.exists(geojson_path):
        logger.warning("[gis_geometry] 县界文件不存在: %s", geojson_path)
        return []
    try:
        with open(geojson_path, "r", encoding="utf-8") as f:
            gj = json.load(f)
    except (OSError, ValueError):
        logger.warning("[gis_geometry] 县界文件解析失败: %s", geojson_path, exc_info=True)
        return []

    out = []
    for idx, ft in enumerate(gj.get("features") or []):
        geom = ft.get("geometry") or {}
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        coords = geom.get("coordinates") or []
        polygons = []
        # Polygon: [[[lng,lat],...]] -> 单多边形；MultiPolygon: 多多边形
        raw_polys = [coords] if geom["type"] == "Polygon" else coords
        for poly in raw_polys:
            if not poly:
                continue
            ring = poly[0]
            if ring and len(ring) >= 3:
                polygons.append([[round(float(p[0]), 6), round(float(p[1]), 6)] for p in ring])
        if not polygons:
            continue
        props = ft.get("properties") or {}
        # name 允许为空：国界文件（liberia_country.geojson）的 feature 无任何属性，
        # 只有县界文件才要求带 name。是否必须有 name 由各 load_* 自行决定。
        name = str(props.get("name") or "").strip()
        out.append({
            "name": name,
            "db_name": str(props.get("db_name") or name).strip(),
            "polygons": polygons,
        })
    return out


def load_county_boundaries() -> list:
    """加载 15 个县的真实行政边界。

    Returns:
        [{name, db_name, color, polygons, site_count}]；文件缺失时返回 []。
        site_count 由调用方（gis.py）按与 /gis/sites 相同的口径回填。
    """
    # 县界必须带 name（前端要显示县名、并与 province_county 对齐），无名的丢弃
    counties = [c for c in _merge_multipolygon_payload(
        os.path.join(GEOJSON_DIR, COUNTIES_FILE)) if c["name"]]
    for idx, c in enumerate(sorted(counties, key=lambda x: x["name"])):
        c["color"] = REGION_COLORS[idx % len(REGION_COLORS)]
        c["site_count"] = 0
    return sorted(counties, key=lambda x: x["name"])


def load_country_boundary() -> list:
    """加载国界（16 个 MultiPolygon，feature 无属性），返回 [[ [lat,lng], ... ], ...]。"""
    rings = []
    for ft in _merge_multipolygon_payload(os.path.join(GEOJSON_DIR, COUNTRY_FILE)):
        rings.extend(ft["polygons"])
    return rings
