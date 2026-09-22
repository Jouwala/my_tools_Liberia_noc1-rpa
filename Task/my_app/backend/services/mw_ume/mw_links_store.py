# -*- coding: utf-8 -*-
"""MW LINKS KML 解析器 + kml_mw_links 表读写（数据库化 MW 叠加图层）

背景
----
`?page=mwUmeTopology` / `?page=mwRealTime` 两个页面除 KPI 表外，还叠加一层
「Orange KML 图层」，原先只能靠 `mw_links_sync.bat` + `kml_to_geojson.py`
把 `data/mw_data/MW LINKS.kml` 转成静态 `mw_ume_orange_links.geojson`。
本模块把这份数据落到数据库表 `kml_mw_links`，改由页面上传 KML 更新。

设计约束（严格遵守，勿改）
--------------------------
1. **只操作 `kml_mw_links` 一张表**。表名在本模块内硬编码常量，
   不接受外部传入，从代码层面杜绝误写 master_site_db / mw_ume_bw_* 等业务表。
2. KML 解析逻辑与 `kml_to_geojson.py` 保持同源（同样的坐标校验与端点提取规则），
   避免两处口径分叉。
3. 纯标准库 + 既有 dialect_helpers，不引入新依赖。
"""
import os
import re
import json
import time
import shutil
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from backend.database import get_raw_connection
from backend.dialect_helpers import write_df, list_table_names

logger = logging.getLogger("mw_links")

# ---- 唯一允许写入的表（硬编码，禁止参数化）----
TABLE_NAME = "kml_mw_links"

# ---- KML 样式 -> 颜色（与 kml_to_geojson.STYLE_COLORS 完全一致，勿单方面修改）----
STYLE_COLORS = {
    "RedLink": "#ff3b30",
    "YellowLink": "#ffcc00",
    "BlueLink": "#0a84ff",
    "GreenLink": "#34c759",
}
DEFAULT_SITE_COLOR = "#ff9500"

BACKUP_KEEP = 3


# ============================================================
# KML 解析
# ============================================================
def _qn(tag, ns):
    return f"{ns}{tag}"


def _text_of(el):
    return (el.text or "").strip() if el is not None else ""


def parse_coord_points(coord_txt):
    """coordinates 文本 -> [(lon,lat), ...]；非法返回 None（与 kml_to_geojson 同规则）。"""
    nums = []
    for part in (coord_txt or "").replace("\n", " ").split(","):
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


def parse_description_table(desc):
    """解析 <description> 里的 HTML 表格 -> {行名小写: [值, ...]}。

    KML 中链路描述形如：
        <br>
        <table border="1" padding="0">
          <tr><td>Site Name</td><td>Baypolu</td><td>Weala</td></tr>
          <tr><td>Antenna Height</td><td>40</td><td>54</td></tr>
          <tr><td>Link Remark</td><td>NEC IX</td></tr>
        </table>

    注意：描述以裸 `<br>` 开头（无根元素包裹），直接解析会 ParseError，
    故先剥掉表格之外的裸标签再解析；仍失败则退回正则抓 <tr>。
    """
    if not desc:
        return {}

    # 1) 剥掉首个 <table> 之前的裸标签（KML 里是 <br>），让片段成为合法 XML
    m = re.search(r"<table[\s>]", desc, re.I)
    frag = desc[m.start():] if m else desc
    try:
        d = ET.fromstring(f"<root>{frag}</root>")
        out = {}
        for tr in d.iter("tr"):
            cells = [_text_of(td).strip() for td in tr.findall("td")]
            if len(cells) >= 2 and cells[0]:
                out[cells[0].strip().lower()] = cells[1:]
        if out:
            return out
    except ET.ParseError:
        pass

    # 2) 正则兜底：直接抓 <tr>...</tr> 里的 <td>
    out = {}
    for tr_html in re.findall(r"<tr[^>]*>(.*?)</tr>", desc, re.I | re.S):
        cells = [_text_of_plain(td) for td in
                 re.findall(r"<td[^>]*>(.*?)</td>", tr_html, re.I | re.S)]
        if len(cells) >= 2 and cells[0]:
            out[cells[0].strip().lower()] = cells[1:]
    return out


def _text_of_plain(html):
    """去标签 + 反转义，得到纯文本单元格。"""
    import html as _html
    return _html.unescape(re.sub(r"<[^>]+>", "", html or "")).strip()


def _style_color(style_url):
    if not style_url:
        return None
    return STYLE_COLORS.get(style_url.rsplit("#", 1)[-1])


def read_kml_text(kml_path):
    """读取 KML（自动处理 UTF-8 / GBK；KML 头部常声明 Windows-936）。"""
    raw = open(kml_path, "rb").read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def parse_kml(kml_path):
    """解析 KML -> (rows, stats)。rows 为可直接写库的 dict 列表。

    每个 element 一行：
      kind='site'  点要素，lon/lat 为站点坐标
      kind='link'  线要素，lon/lat 为 A 端，lon2/lat2 为 B 端
    """
    text = read_kml_text(kml_path)
    # 去掉 XML 声明里的非标准编码名（ElementTree 不认 Windows-936）
    text = re.sub(r'encoding="[^"]*"', 'encoding="utf-8"', text, count=1)
    root = ET.fromstring(text)
    ns = ""
    m = re.match(r"\{.*\}", root.tag)
    if m:
        ns = m.group(0)

    rows = []
    n_site = n_link = skipped = 0

    for pm in root.iter(_qn("Placemark", ns)):
        name = _text_of(pm.find(_qn("name", ns)))
        desc = _text_of(pm.find(_qn("description", ns)))
        ls = pm.find(_qn("LineString", ns))
        pt = pm.find(_qn("Point", ns))
        style = _style_color(_text_of(pm.find(_qn("styleUrl", ns))))

        if ls is not None:
            tbl = parse_description_table(desc)
            names = tbl.get("site name") or []
            a_name = names[0].strip() if len(names) >= 1 and names[0].strip() else None
            b_name = names[1].strip() if len(names) >= 2 and names[1].strip() else None
            if not (a_name and b_name) and "-" in name:
                a_name, b_name = (x.strip() for x in name.split("-", 1))
            pts = parse_coord_points(_text_of(ls.find(_qn("coordinates", ns))))
            if not (pts and len(pts) >= 2 and a_name and b_name):
                skipped += 1
                continue
            height = tbl.get("antenna height") or []
            remark = tbl.get("link remark") or []
            A, B = pts[0], pts[-1]
            rows.append({
                "kind": "link",
                "name": name,
                "a": a_name,
                "b": b_name,
                "lon": A[0], "lat": A[1],
                "lon2": B[0], "lat2": B[1],
                "color": style or DEFAULT_SITE_COLOR,
                "antenna_a": (height[0].strip() if len(height) >= 1 else "") or "",
                "antenna_b": (height[1].strip() if len(height) >= 2 else "") or "",
                "remark": (remark[0].strip() if remark else "") or "",
                "_source_file": Path(kml_path).name,
                "_import_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            n_link += 1

        elif pt is not None:
            pts = parse_coord_points(_text_of(pt.find(_qn("coordinates", ns))))
            if not (pts and name):
                skipped += 1
                continue
            p = pts[0]
            rows.append({
                "kind": "site",
                "name": name,
                "a": "", "b": "",
                "lon": p[0], "lat": p[1],
                "lon2": None, "lat2": None,
                "color": DEFAULT_SITE_COLOR,
                "antenna_a": "", "antenna_b": "", "remark": "",
                "_source_file": Path(kml_path).name,
                "_import_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            n_site += 1

    stats = {"sites": n_site, "links": n_link, "skipped": skipped, "total": len(rows)}
    logger.info("[KML] 解析完成 %s: 站点=%d 链路=%d 跳过=%d",
                os.path.basename(kml_path), n_site, n_link, skipped)
    return rows, stats


# ============================================================
# 数据库读写（只碰 kml_mw_links）
# ============================================================
def _backup_table(conn):
    """导入前备份现有表（保留最近 BACKUP_KEEP 份）。

    双模：sqlite 用 sqlite_master，PG 用 list_table_names（information_schema）。
    ALTER TABLE ... RENAME TO 两方言通用。
    """
    try:
        existing = set(list_table_names(conn))
    except Exception as e:
        logger.warning("[KML] 枚举表失败，跳过备份: %s", e)
        return None
    if TABLE_NAME not in existing:
        return None
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = f"{TABLE_NAME}_bak_{ts}"
    try:
        conn.execute(f'ALTER TABLE "{TABLE_NAME}" RENAME TO "{bak}"')
        conn.commit()
        logger.info("[KML] 已备份旧表 -> %s", bak)
    except Exception as e:
        logger.warning("[KML] 备份失败（继续导入）: %s", e)
        return None
    _prune_backups(conn)
    return bak


def _prune_backups(conn):
    """只保留最近 BACKUP_KEEP 份备份表。"""
    try:
        names = [n for n in list_table_names(conn)
                 if n.startswith(f"{TABLE_NAME}_bak_")]
        for nm in sorted(names, reverse=True)[BACKUP_KEEP:]:
            conn.execute(f'DROP TABLE IF EXISTS "{nm}"')
            logger.info("[KML] 清理旧备份 %s", nm)
        conn.commit()
    except Exception as e:
        logger.warning("[KML] 清理备份失败: %s", e)


def import_kml(kml_path):
    """解析 KML 并写入 kml_mw_links（整表替换 + 自动备份）。"""
    rows, stats = parse_kml(kml_path)
    if not rows:
        raise ValueError("KML 未解析出任何有效站点/链路（坐标或站名可能缺失）")

    import pandas as pd
    df = pd.DataFrame(rows)
    # 固定列序，便于人工查看
    cols = ["kind", "name", "a", "b", "lon", "lat", "lon2", "lat2",
            "color", "antenna_a", "antenna_b", "remark",
            "_source_file", "_import_time"]
    df = df[[c for c in cols if c in df.columns]]

    with get_raw_connection() as conn:
        _backup_table(conn)
        write_df(df, TABLE_NAME, if_exists="replace")
        conn.execute(f'CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_kind ON "{TABLE_NAME}"(kind)')
        conn.execute(f'CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_name ON "{TABLE_NAME}"(name)')
        conn.commit()
    stats["backup"] = True
    logger.info("[KML] 已写入 %s: %d 行", TABLE_NAME, len(df))
    return stats


def _table_exists(conn):
    """双模表存在性判断（PG 无 sqlite_master）。"""
    try:
        return TABLE_NAME in set(list_table_names(conn))
    except Exception:
        return False


def table_status():
    """返回 kml_mw_links 当前状态（供接口/UI 展示）。"""
    with get_raw_connection() as conn:
        if not _table_exists(conn):
            return {"exists": False, "rows": 0, "sites": 0, "links": 0,
                    "import_time": None, "source_file": None}
        total = conn.execute(f'SELECT COUNT(*) FROM "{TABLE_NAME}"').fetchone()[0]
        sites = conn.execute(
            f"SELECT COUNT(*) FROM \"{TABLE_NAME}\" WHERE kind='site'").fetchone()[0]
        links = conn.execute(
            f"SELECT COUNT(*) FROM \"{TABLE_NAME}\" WHERE kind='link'").fetchone()[0]
        src = conn.execute(
            f'SELECT _source_file, _import_time FROM "{TABLE_NAME}" LIMIT 1').fetchone()
        return {
            "exists": True, "rows": total, "sites": sites, "links": links,
            "source_file": src[0] if src else None,
            "import_time": src[1] if src else None,
        }


def build_geojson():
    """从 kml_mw_links 生成 GeoJSON FeatureCollection（格式与旧静态文件一致）。

    字段契约（被 mw_ume_topology.html / mw_real_time.html 消费，勿改）：
      link: {name, a, b, color}  site: {name, color}
    """
    with get_raw_connection() as conn:
        if not _table_exists(conn):
            return None
        cur = conn.execute(
            f'SELECT kind, name, a, b, lon, lat, lon2, lat2, color FROM "{TABLE_NAME}"')
        rows = cur.fetchall()

    if not rows:
        return None

    features = []
    for kind, name, a, b, lon, lat, lon2, lat2, color in rows:
        try:
            lon = float(lon); lat = float(lat)
        except (TypeError, ValueError):
            continue
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            continue
        if kind == "link":
            try:
                lon2 = float(lon2); lat2 = float(lat2)
            except (TypeError, ValueError):
                continue
            if not (-180 <= lon2 <= 180 and -90 <= lat2 <= 90):
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString",
                             "coordinates": [[lon, lat], [lon2, lat2]]},
                "properties": {"kind": "link", "name": name or "",
                               "a": a or "", "b": b or "",
                               "color": color or DEFAULT_SITE_COLOR},
            })
        else:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {"kind": "site", "name": name or "",
                               "color": color or DEFAULT_SITE_COLOR},
            })

    return {"type": "FeatureCollection", "features": features}


def export_geojson_files():
    """把 GeoJSON 同步写到静态文件（public + _fe_dist），作为接口不可用时的回退副本。"""
    fc = build_geojson()
    if fc is None:
        return None
    payload = json.dumps(fc, ensure_ascii=False, separators=(",", ":"))
    root = Path(__file__).resolve().parents[3]
    targets = [
        root / "frontend" / "public" / "mw_ume_orange_links.geojson",
        Path("D:/01_RPA/Task/_fe_dist/mw_ume_orange_links.geojson"),
    ]
    written = []
    for t in targets:
        try:
            if t.parent.is_dir():
                t.write_text(payload, encoding="utf-8")
                written.append(str(t))
        except Exception as e:
            logger.warning("[KML] 写静态回退副本失败 %s: %s", t, e)
    logger.info("[KML] GeoJSON 静态副本已更新: %s", written)
    return {"features": len(fc["features"]), "written": written}
