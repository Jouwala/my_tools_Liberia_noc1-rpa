# -*- coding: utf-8 -*-
"""
MW UME 微波网络拓扑数据服务（Topology NOC Dashboard 数据源）

数据源：my_app 主库表 mw_ume_bw_ultilazation（PG app schema / sqlite app.db 双模，
由 backend/services/mw_ume/mw_ume_kpi_service.py 每日 05:15 定时写入）。

模型转换（ME -> Neighbor ME 天然成图）：
- Node  = 唯一 ME（含 site / ip / ne / 经纬度[zte_mw_links IP优先匹配] / 状态 / 度数）
- Edge  = 唯一 ME<->Neighbor ME 对；按 zte_mw_links 锚定 a->b 单向，仅取该方向
          吞吐/利用率（b->a 完全排除，不再双向合并）+ 端口级 checkpoints
- KPI   = 全网汇总（节点/链路/分级计数/最高利用率）
- TopRisk = 按链路最大利用率降序（前端点击定位拓扑）

分级阈值（告警）：
  < 50%  healthy  🟢
  50-70% watch    🟡
  70-85% warning  🟠
  > 85%  critical 🔴
链路取 max(Tx, Rx? 不) — 取 max(Tx, Rx) 利用率定级；Tx/Rx 均按 zte_mw_links 锚定的
a->b 单向展示（底层 KPI 虽为双向指标，页面仅呈现 a->b 单方向吞吐与利用率，
b->a 方向数据排除、不再合并累加）。

站点经纬度匹配 zte_mw_links：ME IP 精确匹配优先，未命中再按站名
精确 -> 规范化 -> difflib 模糊(>=0.82)，尽力而为。
链路方向（a->b）同样依据 zte_mw_links 的 ip_address_a / ip_address_b（或站名兜底）判定。
"""

import difflib
import logging
import re
import threading
import time
from collections import Counter, defaultdict

from backend.database import get_raw_connection

logger = logging.getLogger("mw_ume_topology")

# 表名（与 mw_ume_kpi_service.TABLE_NAME 一致）
TABLE_NAME = "mw_ume_bw_ultilazation"

# 利用率分级阈值
THRESHOLDS = {"watch": 50.0, "warning": 70.0, "critical": 85.0}

# 链路聚合列（MW 微波以太口）
COL_CAP = "Max Ethernet Tx Capacity(Mbps)"
COL_TX_T = "Max Ethernet Tx Throughput(Mbps)"
COL_TX_U = "Max Ethernet Tx Utilization(%)"
COL_RX_T = "Max Ethernet Rx Throughput(Mbps)"
COL_RX_U = "Max Ethernet Rx Utilization(%)"

# 物理链路缓存（zte_mw_links 全表，启动后只加载一次）
_phys_cache_lock = threading.Lock()
_phys_cache = None  # [{a_ip, a_name, a_lat, a_lon, b_ip, b_name, b_lat, b_lon}, ...]

# 站点匹配缓存（zte_mw_links 链路两端站点，启动后只加载一次）
_site_cache_lock = threading.Lock()
_site_cache = None  # {"exact": {name: (lat,lon)}, "norm": {norm: (name,lat,lon)}, "list": [...], "ip": {ip: (name,lat,lon)}}


def level_of(u):
    """利用率 -> 分级字符串。u 为 None 时返回 'unknown'。"""
    if u is None:
        return "unknown"
    u = float(u)
    if u < THRESHOLDS["watch"]:
        return "healthy"
    if u < THRESHOLDS["warning"]:
        return "watch"
    if u < THRESHOLDS["critical"]:
        return "warning"
    return "critical"


def parse_me(me):
    """解析 ME 名：'4143_BaptistSeminary_NE4(192.168.173.114)' -> (site, ne, ip)。"""
    if not me:
        return None
    ip = ""
    m = re.search(r"\(([\d.]+)\)", me)
    if m:
        ip = m.group(1)
    core = re.sub(r"\([\d.]+\)$", "", me).strip()
    m2 = re.search(r"_NE\d*$", core, re.I)
    if m2:
        name_part = core[:m2.start()]
        ne = core[m2.start() + 1:]
    else:
        name_part = core
        ne = ""
    parts = name_part.split("_")
    if len(parts) > 1 and re.match(r"^[A-Za-z]*\d+$", parts[0]):
        site = "_".join(parts[1:])
    else:
        site = name_part
    return site.strip(), ne, ip


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _load_site_cache():
    """加载 zte_mw_links 站点经纬度（线程安全单次加载）。

    每行是一条微波链路：A/B 两端各有 ran_name / lat / lon / ip。
    同时构建站名索引（exact/norm/list）与 IP 索引（ip），
    同名/同 IP 多行时取首个有效坐标。
    """
    global _site_cache
    with _site_cache_lock:
        if _site_cache is not None:
            return _site_cache
        cache = {"exact": {}, "norm": {}, "list": [], "ip": {}}
        try:
            conn = get_raw_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT sit_a_ran_name, site_a_lat, site_a_lon, ip_address_a, "
                "site_b_ran_name, site_b_lat, site_b_lon, ip_address_b FROM zte_mw_links")
            for a_name, a_lat, a_lon, a_ip, b_name, b_lat, b_lon, b_ip in cur.fetchall():
                for name, lat, lon, ip in (
                        (a_name, a_lat, a_lon, a_ip),
                        (b_name, b_lat, b_lon, b_ip)):
                    try:
                        lat_f, lon_f = float(lat), float(lon)
                    except (TypeError, ValueError):
                        continue  # 脏坐标行跳过
                    if name:
                        key = str(name).strip().lower()
                        cache["exact"].setdefault(key, (lat_f, lon_f))
                        cache["norm"].setdefault(_norm(key), (name, lat_f, lon_f))
                        cache["list"].append((name, lat_f, lon_f))
                    if ip:
                        cache["ip"].setdefault(str(ip).strip(), (name, lat_f, lon_f))
            conn.close()
            logger.info(
                f"[SITE] loaded {len(cache['ip'])} endpoints "
                f"({len(cache['list'])} name entries) from zte_mw_links")
        except Exception as e:
            logger.warning(f"[SITE] zte_mw_links 加载失败: {e}")
        _site_cache = cache
        return cache


def match_site_by_ip(ip):
    """ME IP -> (name, lat, lon) 或 None（zte_mw_links ip_address_a/b 精确匹配）。"""
    if not ip:
        return None
    cache = _load_site_cache()
    return cache["ip"].get(ip.strip())


def _reset_site_cache():
    """清空站点缓存（配合 refresh=1 强制刷新）。

    zte_mw_links 坐标被人工修正后，点页面「刷新」即可生效，无需重启后端。
    """
    global _site_cache
    with _site_cache_lock:
        _site_cache = None


def match_site(site):
    """站点名 -> (zte_name, lat, lon) 或 None。精确 -> 规范化 -> 模糊(0.82)。"""
    if not site:
        return None
    cache = _load_site_cache()
    key = site.strip().lower()
    if key in cache["exact"]:
        lat, lon = cache["exact"][key]
        return (site, lat, lon)
    nk = _norm(key)
    if nk in cache["norm"]:
        name, lat, lon = cache["norm"][nk]
        return (name, lat, lon)
    # difflib 模糊（对规范化后的 key 匹配，cutoff 0.82）
    best = difflib.get_close_matches(nk, list(cache["norm"].keys()), n=1, cutoff=0.82)
    if best:
        name, lat, lon = cache["norm"][best[0]]
        return (name, lat, lon)
    return None


# 链路方向缓存（zte_mw_links 的 A/B 端定义 a->b 单向；一次性加载）
_link_orient_lock = threading.Lock()
_link_orient = None  # {"ip": {frozenset({ipa,ipb}): (ipa,ipb)}, "name": {frozenset({na,nb}): (na,nb)}}


def _load_link_orientation():
    """加载 zte_mw_links 的 A/B 方向定义，把无向链路锚定到 a->b 单向。

    每条 zte_mw_links 记录定义一处微波链路的 A 端(ip_address_a)与 B 端
    (ip_address_b)。返回两套索引：
      - ip:   frozenset({ip_a, ip_b}) -> (ip_a, ip_b)   （ME IP 精确匹配，主用）
      - name: frozenset({norm(a_name), norm(b_name)}) -> (a_name, b_name)（站名兜底）
    未命中任一索引的物理链路，回退为「双向合并」旧行为（页面仍有数据）。
    """
    global _link_orient
    with _link_orient_lock:
        if _link_orient is not None:
            return _link_orient
        orient = {"ip": {}, "name": {}}
        try:
            conn = get_raw_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT sit_a_ran_name, ip_address_a, site_b_ran_name, ip_address_b "
                "FROM zte_mw_links")
            for a_name, a_ip, b_name, b_ip in cur.fetchall():
                if a_ip and b_ip and a_ip.strip() != b_ip.strip():
                    orient["ip"][frozenset([a_ip.strip(), b_ip.strip()])] = (a_ip.strip(), b_ip.strip())
                if a_name and b_name and _norm(a_name) != _norm(b_name):
                    orient["name"][frozenset([_norm(a_name), _norm(b_name)])] = (a_name, b_name)
            conn.close()
            logger.info(
                f"[ORIENT] loaded {len(orient['ip'])} ip / {len(orient['name'])} name "
                f"link orientations from zte_mw_links")
        except Exception as e:
            logger.warning(f"[ORIENT] zte_mw_links 方向加载失败: {e}")
        _link_orient = orient
        return orient


def _reset_link_orientation():
    """清空链路方向缓存（配合 refresh=1 强制刷新）。"""
    global _link_orient
    with _link_orient_lock:
        _link_orient = None


def _orient_pair(a_full, b_full, ip_a, ip_b, name_a, name_b):
    """给定无向链路两端 (full ME, IP, 站名)，返回方向锚定结果：
      0   -> a_full 即 zte_mw_links 定义的 A 端（链路方向 a->b，保持原序）
      1   -> b_full 为 A 端（链路方向应为 b->a，需交换两端）
      None-> 未命中 zte_mw_links 方向记录（IP 精确匹配优先，站名兜底）
    """
    orient = _load_link_orientation()
    if ip_a and ip_b:
        key = frozenset([ip_a, ip_b])
        if key in orient["ip"]:
            a_ip, _ = orient["ip"][key]
            return 0 if ip_a == a_ip else 1
    if name_a and name_b:
        nkey = frozenset([_norm(name_a), _norm(name_b)])
        if nkey in orient["name"]:
            a_name, _ = orient["name"][nkey]
            return 0 if _norm(name_a) == _norm(a_name) else 1
    return None


def _choose_direction(rows, src, tgt, oriented):
    """链路择行（页面单向口径）：仅保留 src->tgt 方向的 KPI 行参与吞吐/利用率计算，
    反方向行排除、不双向合并累加；src->tgt 行缺失时退取反方向单行（仍为单向）。
    未命中 zte_mw_links 方向记录的链路回退全部行（旧双向口径，保证页面有数）。"""
    if not oriented:
        return rows
    ab = [x for x in rows if x["a_full"] == src and x["b_full"] == tgt]
    if ab:
        return ab
    ba = [x for x in rows if x["a_full"] == tgt and x["b_full"] == src]
    return ba or rows


def _pick_primary_dir(items, a_side, b_side):
    """链路主方向择行：比较 a_side->b_side 与 b_side->a_side 两个方向的累计 TX
    吞吐量，选择 TX 较大的一侧作为 source（主发送方向），保证页面 TX LINK 通常
    大于 RX LINK。任一方向缺失时退取另一方向（仍为单向）。"""
    ab = [x for x in items if x["a_full"] == a_side and x["b_full"] == b_side]
    ba = [x for x in items if x["a_full"] == b_side and x["b_full"] == a_side]
    ab_tx = sum(float(x["tx_t"] or 0) for x in ab) if ab else 0.0
    ba_tx = sum(float(x["tx_t"] or 0) for x in ba) if ba else 0.0
    if ab or ba:
        if ab_tx >= ba_tx:
            return a_side, b_side, (ab or ba)
        return b_side, a_side, (ba or ab)
    return a_side, b_side, items


def _ep_props(items, full):
    """从链路 items 中取端点 full 的 (ip, site, ne)（full 既可能作 ME 也可能作 Neighbor）。"""
    for it in items:
        if it["a_full"] == full:
            return it["a"][2], it["a"][0]
        if it["b_full"] == full:
            return it["b"][2], it["b"][0]
    return None, None


def _fetch_rows():
    """读主库全部链路行（双模：PG app schema / sqlite）。"""
    conn = get_raw_connection()
    cur = conn.cursor()
    cur.execute(f'SELECT * FROM "{TABLE_NAME}"')
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows


def _parse_rows(rows):
    """原始行 -> 解析行（ME/Neighbor ME 解析 + 关键列提取）。"""
    parsed = []
    for r in rows:
        a = parse_me(r.get("ME"))
        b = parse_me(r.get("Neighbor ME"))
        if not a or not b:
            continue
        parsed.append({
            "a": a, "a_full": r.get("ME"),
            "b": b, "b_full": r.get("Neighbor ME"),
            "a_cp": r.get("PM Checkpoint"), "b_cp": r.get("Neighbor PM Checkpoint"),
            "cap": r.get(COL_CAP),
            "tx_t": r.get(COL_TX_T), "tx_u": r.get(COL_TX_U),
            "rx_t": r.get(COL_RX_T), "rx_u": r.get(COL_RX_U),
            "bt": r.get("Begin Time"),
        })
    return parsed


def _is_backbone_row(r):
    """骨干网链路判定：ME 与 Neighbor ME 两端 IP 均以 "10." 开头（与前端口径一致）。"""
    a = parse_me(r.get("ME"))
    b = parse_me(r.get("Neighbor ME"))
    if not a or not b:
        return False
    return a[2].startswith("10.") and b[2].startswith("10.")


def _build_trends(hist_by_ip_pair):
    """全网逐日趋势（始终基于全部日期，供趋势图使用）。

    口径与链路一致：每条物理链路每日仅取主方向（TX 较大的一侧作为 source）
    的 KPI 行参与统计，反方向行排除、不双向合并累加。
    """
    by_day = defaultdict(list)
    for ent in hist_by_ip_pair.values():
        src_ip, tgt_ip = ent.get("src_ip"), ent.get("tgt_ip")
        if not src_ip or not tgt_ip:
            continue
        for day, day_rows in ent["days"].items():
            chosen = [x for x in day_rows
                      if x["a"][2] == src_ip and x["b"][2] == tgt_ip]
            if not chosen:
                chosen = [x for x in day_rows
                          if x["a"][2] == tgt_ip and x["b"][2] == src_ip]
            if not chosen:
                chosen = day_rows
            by_day[day].extend(chosen)
    trends = []
    for day in sorted(by_day):
        day_rows = by_day[day]
        if not day_rows:
            continue
        us = [max(float(x["tx_u"] or 0), float(x["rx_u"] or 0)) for x in day_rows]
        trends.append({
            "date": day,
            "rows": len(day_rows),
            "avg_util": round(sum(us) / len(us), 2) if us else 0,
            "max_util": round(max(us), 2) if us else 0,
            "critical": sum(1 for u in us if level_of(u) == "critical"),
        })
    return trends


def _load_physical_links():
    """从 zte_mw_links 加载全部物理链路（线程安全单次加载）。

    返回列表：[{a_ip, a_name, a_lat, a_lon, b_ip, b_name, b_lat, b_lon}, ...]
    每条记录是一条微波物理链路的 A/B 两端信息。
    """
    global _phys_cache
    with _phys_cache_lock:
        if _phys_cache is not None:
            return _phys_cache
        links = []
        try:
            conn = get_raw_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT sit_a_ran_name, site_a_lat, site_a_lon, ip_address_a, "
                "site_b_ran_name, site_b_lat, site_b_lon, ip_address_b FROM zte_mw_links")
            for a_name, a_lat, a_lon, a_ip, b_name, b_lat, b_lon, b_ip in cur.fetchall():
                try:
                    a_lat_f, a_lon_f = float(a_lat), float(a_lon)
                    b_lat_f, b_lon_f = float(b_lat), float(b_lon)
                except (TypeError, ValueError):
                    continue
                if not a_ip or not b_ip:
                    continue
                a_ip_s = str(a_ip).strip()
                b_ip_s = str(b_ip).strip()
                if a_ip_s == b_ip_s:
                    continue
                links.append({
                    "a_ip": a_ip_s, "a_name": str(a_name).strip() if a_name else "",
                    "a_lat": a_lat_f, "a_lon": a_lon_f,
                    "b_ip": b_ip_s, "b_name": str(b_name).strip() if b_name else "",
                    "b_lat": b_lat_f, "b_lon": b_lon_f,
                })
            conn.close()
            logger.info(f"[PHYS] loaded {len(links)} physical links from zte_mw_links")
        except Exception as e:
            logger.warning(f"[PHYS] zte_mw_links physical links load failed: {e}")
        _phys_cache = links
        return links


def _reset_phys_cache():
    """清空物理链路缓存（配合 refresh=1 强制刷新）。"""
    global _phys_cache
    with _phys_cache_lock:
        _phys_cache = None


def build_topology(top_n: int = 10, date: str = None, rows_all: list = None,
                   backbone: bool = False):
    """构建完整拓扑数据（Nodes / Edges / KPIs / TopRisks / Trends）。

    数据源：
    - 拓扑骨架：zte_mw_links（全部物理链路，作为 nodes/edges 基础）
    - KPI 数据：mw_ume_bw_ultilaztion（覆盖到物理链路上，无 KPI 的链路标记为 unknown）

    date 取值：
      None            -> 自动选择最新可用日期；
      "YYYY-MM-DD"    -> 仅用该日数据构建。
    backbone=True 时仅保留骨干网链路（两端 IP 均以 10. 开头）。
    """
    # ---- 1. 加载物理拓扑骨架 ----
    phys_links = _load_physical_links()

    # ---- 2. 加载 KPI 数据 ----
    if rows_all is None:
        rows_all = _fetch_rows()

    # 骨干网过滤：物理链路 + KPI 行 同时过滤
    if backbone:
        rows_all = [r for r in rows_all if _is_backbone_row(r)]
        phys_links = [l for l in phys_links
                      if l["a_ip"].startswith("10.") and l["b_ip"].startswith("10.")]

    # ---- 3. 可用日期 ----
    available_dates = sorted({str(r.get("Begin Time"))[:10]
                              for r in rows_all if r.get("Begin Time") is not None})

    # ---- 4. 日期筛选 ----
    if date is None:
        selected = available_dates[-1] if available_dates else None
        rows = [r for r in rows_all if str(r.get("Begin Time"))[:10] == selected] if selected else []
    elif date in available_dates:
        selected = date
        rows = [r for r in rows_all if str(r.get("Begin Time"))[:10] == date]
    else:
        selected = date
        rows = []

    # ---- 5. 解析 KPI 行 ----
    parsed = _parse_rows(rows)
    parsed_all = _parse_rows(rows_all)

    # ---- 6. 构建物理节点信息（IP 为 node id） ----
    node_info = {}
    for link in phys_links:
        for ip, name, lat, lon in [
            (link["a_ip"], link["a_name"], link["a_lat"], link["a_lon"]),
            (link["b_ip"], link["b_name"], link["b_lat"], link["b_lon"]),
        ]:
            if ip not in node_info:
                node_info[ip] = {
                    "site": name or ip, "ne": "", "ip": ip,
                    "degree": 0, "max_util": 0.0,
                    "lat": lat, "lon": lon,
                }

    # ---- 7. KPI 数据索引（按 IP 对聚合） ----
    # 全量历史：按 frozenset({ip_a, ip_b}) 聚合每日 KPI 行
    hist_by_ip_pair = defaultdict(lambda: {"days": {}, "src_ip": None, "tgt_ip": None})
    for p in parsed_all:
        if p["bt"] is None:
            continue
        a_ip = p["a"][2]
        b_ip = p["b"][2]
        if not a_ip or not b_ip:
            continue
        key = frozenset([a_ip, b_ip])
        day = str(p["bt"])[:10]
        hist_by_ip_pair[key]["days"].setdefault(day, []).append(p)

    # ---- 8. 为每条物理链路匹配 KPI 数据 ----
    # 确定物理链路方向：a_ip → b_ip（zte_mw_links 定义的 A→B 方向）
    # 若该方向无 KPI，取反方向，否则全部行
    edges = []
    for link in phys_links:
        src_ip = link["a_ip"]
        tgt_ip = link["b_ip"]
        key = frozenset([src_ip, tgt_ip])

        node_info[src_ip]["degree"] += 1
        node_info[tgt_ip]["degree"] += 1

        pair_ent = hist_by_ip_pair.get(key)

        if pair_ent and pair_ent["days"]:
            # 确定当日 KPI 行
            today_rows = []
            if selected:
                all_kpi_for_pair = [r for day_rows in pair_ent["days"].values() for r in day_rows]
                today_rows = [r for r in all_kpi_for_pair
                             if str(r["bt"])[:10] == selected]

            if today_rows:
                chosen = [r for r in today_rows
                          if r["a"][2] == src_ip and r["b"][2] == tgt_ip]
                if not chosen:
                    chosen = [r for r in today_rows
                              if r["a"][2] == tgt_ip and r["b"][2] == src_ip]
                    if chosen:
                        src_ip, tgt_ip = tgt_ip, src_ip
                if not chosen:
                    chosen = today_rows

                cap = max((float(x["cap"]) for x in chosen if x["cap"] is not None), default=None)
                tx_t = sum(float(x["tx_t"] or 0) for x in chosen) or None
                rx_t = sum(float(x["rx_t"] or 0) for x in chosen) or None
                tx_u = max((float(x["tx_u"] or 0) for x in chosen), default=0.0) or 0.0
                rx_u = max((float(x["rx_u"] or 0) for x in chosen), default=0.0) or 0.0
                max_u = max(tx_u, rx_u)
                status = level_of(max_u)

                for it in chosen:
                    u = max(float(it["tx_u"] or 0), float(it["rx_u"] or 0))
                    a_ip_kpi = it["a"][2]
                    b_ip_kpi = it["b"][2]
                    if a_ip_kpi in node_info and u > node_info[a_ip_kpi]["max_util"]:
                        node_info[a_ip_kpi]["max_util"] = u
                    if b_ip_kpi in node_info and u > node_info[b_ip_kpi]["max_util"]:
                        node_info[b_ip_kpi]["max_util"] = u

                cps = [{
                    "cp": x["a_cp"], "ncp": x["b_cp"],
                    "tx_t": x["tx_t"], "tx_u": x["tx_u"],
                    "rx_t": x["rx_t"], "rx_u": x["rx_u"],
                } for x in chosen]

                # 构建历史（按日聚合，供下钻曲线）
                history = []
                for day in sorted(pair_ent["days"]):
                    day_rows = [r for r in pair_ent["days"][day]
                               if r["a"][2] == src_ip and r["b"][2] == tgt_ip]
                    if not day_rows:
                        day_rows = [r for r in pair_ent["days"][day]
                                   if r["a"][2] == tgt_ip and r["b"][2] == src_ip]
                    if not day_rows:
                        day_rows = pair_ent["days"][day]
                    d_tx = max((float(x["tx_u"] or 0) for x in day_rows), default=0.0)
                    d_rx = max((float(x["rx_u"] or 0) for x in day_rows), default=0.0)
                    d_max = max(d_tx, d_rx)
                    history.append({
                        "date": day,
                        "tx_util": round(d_tx, 2),
                        "rx_util": round(d_rx, 2),
                        "max_util": round(d_max, 2),
                    })

                edges.append({
                    "source": src_ip, "target": tgt_ip,
                    "capacity": round(cap, 2) if cap is not None else None,
                    "tx_throughput": round(tx_t, 2) if tx_t is not None else None,
                    "rx_throughput": round(rx_t, 2) if rx_t is not None else None,
                    "tx_util": round(tx_u, 2), "rx_util": round(rx_u, 2),
                    "status": status, "max_util": round(max_u, 2),
                    "checkpoints": cps, "history": history,
                    "kpi_backed": True,
                })
                # 记录主方向，供趋势使用
                pair_ent["src_ip"] = src_ip
                pair_ent["tgt_ip"] = tgt_ip
            else:
                # KPI 数据存在但当日无记录
                edges.append({
                    "source": src_ip, "target": tgt_ip,
                    "capacity": None,
                    "tx_throughput": None, "rx_throughput": None,
                    "tx_util": 0.0, "rx_util": 0.0,
                    "status": "unknown", "max_util": 0.0,
                    "checkpoints": [], "history": [],
                    "kpi_backed": False,
                })
        else:
            # 无 KPI 数据
            edges.append({
                "source": src_ip, "target": tgt_ip,
                "capacity": None,
                "tx_throughput": None, "rx_throughput": None,
                "tx_util": 0.0, "rx_util": 0.0,
                "status": "unknown", "max_util": 0.0,
                "checkpoints": [], "history": [],
                "kpi_backed": False,
            })

    edges.sort(key=lambda e: -e["max_util"])

    # ---- 9. 构建节点列表 ----
    nodes = []
    for ip, info in sorted(node_info.items(), key=lambda kv: -kv[1]["degree"]):
        status = level_of(info["max_util"]) if info["max_util"] > 0 else "unknown"
        nodes.append({
            "id": ip,
            "name": info["site"],
            "site": info["site"],
            "ne": info["ne"],
            "ip": ip,
            "lat": info["lat"], "lon": info["lon"],
            "degree": info["degree"],
            "status": status,
            "max_util": round(info["max_util"], 2),
        })

    # ---- 10. KPI 统计（仅统计有 KPI 的链路） ----
    kpi_edges = [e for e in edges if e.get("kpi_backed", False)]
    lvl = Counter(e["status"] for e in kpi_edges)
    max_link = kpi_edges[0] if kpi_edges else None
    kpis = {
        "nodes": len(nodes),
        "links": len(kpi_edges),
        "physical_links": len(edges),
        "physical_nodes": len(node_info),
        "healthy": lvl.get("healthy", 0),
        "watch": lvl.get("watch", 0),
        "warning": lvl.get("warning", 0),
        "critical": lvl.get("critical", 0),
        "unknown": len(edges) - len(kpi_edges),
        "max_utilization": max_link["max_util"] if max_link else 0,
        "max_util_link": {"source": max_link["source"], "target": max_link["target"],
                          "source_site": node_info[max_link["source"]]["site"],
                          "target_site": node_info[max_link["target"]]["site"],
                          "tx_util": max_link["tx_util"], "rx_util": max_link["rx_util"]}
        if max_link else None,
    }

    # ---- 11. Top Risks（仅 KPI 有数据的 Critical 链路） ----
    top_risks = [{"source": e["source"], "target": e["target"],
                  "source_site": node_info[e["source"]]["site"],
                  "target_site": node_info[e["target"]]["site"],
                  "tx_util": e["tx_util"], "rx_util": e["rx_util"],
                  "max_util": e["max_util"], "status": e["status"],
                  "capacity": e["capacity"]}
                 for e in kpi_edges[:max(top_n, 1)]]

    # ---- 12. 趋势 ----
    trends = _build_trends(hist_by_ip_pair)

    # ---- 13. Meta ----
    meta = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "granularity": "1day",
        "thresholds": THRESHOLDS,
        "selected_date": selected,
        "available_dates": available_dates,
        "counts": {"rows": len(rows), "parsed": len(parsed),
                   "begin_times": len(available_dates), "total_rows": len(rows_all),
                   "physical_links": len(edges), "physical_nodes": len(node_info)},
    }
    return {"meta": meta, "kpis": kpis, "nodes": nodes,
            "edges": edges, "top_risks": top_risks, "trends": trends}


# ---- 轻量 TTL 缓存（数据每日更新一次，缓存 5 分钟足够） ----
# 行缓存：TTL 内复用同一次 DB 读取；结果缓存：按 (top_n, date) 复用构建结果
_rows_cache = {"ts": 0.0, "rows": None}
_result_cache = {}
CACHE_TTL = 300


def get_topology(top_n: int = 10, force: bool = False, date: str = None,
                 backbone: bool = False):
    """带 TTL 缓存的拓扑数据入口（date=None 时自动取最新日期）。"""
    now = time.time()
    if force or _rows_cache["rows"] is None or (now - _rows_cache["ts"]) >= CACHE_TTL:
        try:
            if force:
                _reset_site_cache()
                _reset_link_orientation()
                _reset_phys_cache()
            _rows_cache["rows"] = _fetch_rows()
            _rows_cache["ts"] = time.time()
            _result_cache.clear()
        except Exception as e:
            logger.error(f"[TOPOLOGY] fetch rows failed: {e}")
            if _rows_cache["rows"] is None:
                raise
    key = (top_n, date, backbone)
    cached = _result_cache.get(key)
    if cached is not None:
        return cached
    try:
        data = build_topology(top_n=top_n, date=date, rows_all=_rows_cache["rows"],
                              backbone=backbone)
    except Exception as e:
        logger.error(f"[TOPOLOGY] build failed: {e}")
        raise
    _result_cache[key] = data
    return data


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    d = get_topology(force=True)
    print("KPI:", d["kpis"])
    print("SELECTED:", d["meta"]["selected_date"])
    print("AVAILABLE:", d["meta"]["available_dates"])
    print("NODES:", len(d["nodes"]), "EDGES:", len(d["edges"]))
    print("PHYSICAL LINKS:", d["kpis"].get("physical_links"))
    print("KPI-BACKED LINKS:", d["kpis"].get("links"))
    print("UNKNOWN LINKS:", d["kpis"].get("unknown"))
    print("TOP_RISKS:", len(d["top_risks"]))
    print("TRENDS:", d["trends"])
