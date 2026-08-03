# gis_geometry.py — GIS 几何计算模块

> P2#8 重构（2026-08-03）：从 `gis.py` 的 `get_region_boundaries`（CC=48, 254 行）拆分出的纯几何计算模块。

## 职责边界

- **只做几何计算**（shapely / scipy / numpy），不访问数据库、不依赖 FastAPI。
- `gis.py` 负责 SQL 查询与接口组装，调用本模块完成区域边界几何生成。

## 主要函数

| 函数 | 职责 |
| --- | --- |
| `fix_coords(lat, lng)` | 修正明显交换的经纬度 |
| `load_boundary_file(filename)` | 从 `backend/boundaries/` 加载 GeoJSON 边界 |
| `determine_valid_bounds(lats, lngs)` | 判定项目区域（利比里亚/Gauteng/通用）与有效边界 |
| `filter_valid_sites(sites, ...)` | 过滤并修正站点坐标 |
| `build_clip_boundary(...)` | 构建 Voronoi 裁剪边界（国界/省界/凸包兜底） |
| `voronoi_cell_polygon(...)` | 计算单站点 Voronoi cell（已裁剪） |
| `group_region_cells(...)` | 按 region 分组收集 cells |
| `merge_region_polygons(...)` | 合并 cells：平滑→扩展→国界裁剪 |
| `smooth_polygon_ring(...)` | Catmull-Rom 视觉平滑 |
| `polygon_to_coords(geom)` | shapely 几何体 → 坐标列表 |
| `build_region_payload(...)` | 生成接口返回结构 |
| `compute_region_boundaries(sites)` | **主入口**：站点列表 → region 边界 payload |

## 依赖

见同目录 `requirements.txt`（numpy / scipy / shapely）。
