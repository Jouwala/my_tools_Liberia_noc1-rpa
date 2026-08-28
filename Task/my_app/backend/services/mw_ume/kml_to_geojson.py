# -*- coding: utf-8 -*-
"""
KML -> GeoJSON 转换器（MW 微波拓扑叠加图层用）

设计（与项目约定一致，零外部依赖）：
- 纯标准库 xml 解析，不引任何第三方包；输出标准 GeoJSON。
- 坐标：KML 为 "lon,lat,alt"，GeoJSON 亦为 [lon, lat]（经度在前），故**无需交换顺序**，
  直接丢弃海拔即可，L.geoJSON 原生消费。
- 站点(Point) -> GeoJSON Point 要素；微波链路(LineString) -> GeoJSON LineString 要素。
- 链路端点 A/B 名取自 <description> 表格的 "Site Name" 行（缺失则用链路名按 '-' 拆分）。
- 链路配色沿用 KML 的 styleUrl（Red/Yellow/Blue/GreenLink），站点统一橙色。
- 过滤非法坐标（越界/空），避免图层渲染报错或点堆在 (0,0)。
- 默认源：data/mw_data/MW LINKS.kml；默认输出：frontend/public/mw_ume_orange_links.geojson。

用法：
  python kml_to_geojson.py
  python kml_to_geojson.py --kml <path>.kml --out <path>.geojson
"""
import argparse
import json
import os
import re
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

STYLE_COLORS = {
    "RedLink": "#ff3b30",
    "YellowLink": "#ffcc00",
    "BlueLink": "#0a84ff",
    "GreenLink": "#34c759",
}
DEFAULT_SITE_COLOR = "#ff9500"
DEFAULT_LINK_COLOR = "#ff9500"


def qn(tag, ns):
    return f"{ns}{tag}"


def text_of(el):
    return (el.text or "").strip() if el is not None else ""


def parse_coord_points(coord_txt):
    """coordinates 文本 -> [(lon,lat), ...]，按逗号拆数字每 3 个一组。"""
    nums = []
    for part in coord_txt.replace("\n", " ").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nums.append(float(part))
        except ValueError:
            return None
    if len(nums) < 3 or len(nums) % 3 != 0:
        return None
    pts = []
    for i in range(0, len(nums), 3):
        lon, lat = nums[i], nums[i + 1]
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return None
        pts.append((lon, lat))
    return pts


def parse_endpoints(desc):
    """从 <description> 表格提取 'Site Name' 行的 A/B 站名。"""
    if not desc:
        return None, None
    try:
        d = ET.fromstring(f"<root>{desc}</root>")
    except ET.ParseError:
        return None, None
    for tr in d.iter("tr"):
        cells = [text_of(td).strip() for td in tr.findall("td")]
        if cells and cells[0].lower() == "site name" and len(cells) >= 3:
            return cells[1], cells[2]
    return None, None


def style_color(style_url):
    if not style_url:
        return None
    name = style_url.rsplit("#", 1)[-1]
    return STYLE_COLORS.get(name)


def convert(kml_path, out_path):
    raw = open(kml_path, "rb").read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("gbk", errors="replace")
    root = ET.fromstring(text)
    ns = ""
    m = re.match(r"\{.*\}", root.tag)
    if m:
        ns = m.group(0)

    features = []
    n_site = n_link = skipped = 0

    for pm in root.iter(qn("Placemark", ns)):
        name = text_of(pm.find(qn("name", ns)))
        desc = text_of(pm.find(qn("description", ns)))
        ls = pm.find(qn("LineString", ns))
        pt = pm.find(qn("Point", ns))

        if ls is not None:
            a_name, b_name = parse_endpoints(desc)
            if not (a_name and b_name) and "-" in name:
                a_name, b_name = name.split("-", 1)
            coord_txt = text_of(ls.find(qn("coordinates", ns)))
            pts = parse_coord_points(coord_txt)
            if not (pts and len(pts) >= 2 and a_name and b_name):
                skipped += 1
                continue
            A, B = pts[0], pts[-1]
            color = style_color(text_of(pm.find(qn("styleUrl", ns)))) or DEFAULT_LINK_COLOR
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[A[0], A[1]], [B[0], B[1]]],
                },
                "properties": {
                    "kind": "link",
                    "name": name.strip(),
                    "a": a_name.strip(),
                    "b": b_name.strip(),
                    "color": color,
                },
            })
            n_link += 1
        elif pt is not None:
            coord_txt = text_of(pt.find(qn("coordinates", ns)))
            pts = parse_coord_points(coord_txt)
            if not (pts and name):
                skipped += 1
                continue
            p = pts[0]
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [p[0], p[1]]},
                "properties": {
                    "kind": "site",
                    "name": name.strip(),
                    "color": DEFAULT_SITE_COLOR,
                },
            })
            n_site += 1

    fc = {"type": "FeatureCollection", "features": features}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[KML]   源: {kml_path}")
    print(f"        站点={n_site}  链路={n_link}  跳过(非法)={skipped}")
    print(f"[GeoJSON] 输出: {out_path}")
    print(f"        要素数={len(features)}  大小={os.path.getsize(out_path)} bytes")
    return fc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kml", default=os.path.join(ROOT, "data", "mw_data", "MW LINKS.kml"))
    ap.add_argument("--out", default=os.path.join(ROOT, "frontend", "public", "mw_ume_orange_links.geojson"))
    args = ap.parse_args()
    if not os.path.isfile(args.kml):
        raise SystemExit(f"KML 不存在: {args.kml}")
    convert(args.kml, args.out)


if __name__ == "__main__":
    main()
