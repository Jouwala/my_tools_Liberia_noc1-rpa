# -*- coding: utf-8 -*-
"""GIS 页 MW 链路利用率叠加（把 mwRealTime 的最新 15 分钟粒度利用率贴到 kml_mw_links 上）

背景与问题
----------
`?page=gis` 画的线来自 `kml_mw_links`（844 条 KML 叠加图层），只有坐标与线色；
`?page=mwRealTime` 的利用率来自 `mw_ume_bw_ultilazation_rt`（373 条 KPI 链路），
以 **IP** 为主键（`192.168.171.117 -> 192.168.171.118`）。
两套数据的主键不同（站名 vs IP）、链路集合也不同，**不存在现成的 JOIN 键**。

实测覆盖度（2026-09-28，844 条 KML 线 / 373 条 KPI 链路）：
- 最终匹配 **360 条**（坐标 340 / 站名兜底 20），484 条无 KPI 数据
- 端点命中率：1149 命中 / 539 未命中（1688 = 844×2）
- mwRealTime 当期的 7 条 critical+major 链路 **全部** 能上色（含最严重的 98.93%），
  这是本叠加功能的核心价值：GIS 概览页不会漏掉最该关注的线。

⚠️ 迭代记录：初版索引「每个坐标格只保留第一个 NE」，实测只能匹配 146 条，
   且 7 条 critical+major 里的 3 条（含最严重的 LPRC->Chocolate City 98.93%）
   会因落在同站另一台 NE 上而查不到、被静默当作「无 KPI 数据」——
   「最该标红的线反而没颜色」是最危险的错法。改为保留站点全部 NE 并做笛卡尔积
   试查后，匹配数与严重链路覆盖同时修正（详见 `_build_node_index` 注释）。

因此本模块的核心设计约束是：**宁可少标，绝不猜标**。
匹配不上的链路一律返回 `util=None`，由前端保留 KML 原线色并标注「无 KPI 数据」——
把 A 站的利用率画到 B 站的线上，比不画这条线更糟（会直接误导排障方向）。

匹配策略（用户 2026-09-28 确认）
-------------------------------
1. **坐标优先**：KML 线端点与 MW 节点坐标在同一容差格内即视为同一站点。
   坐标是两套数据里唯一语义中立的字段，不受命名规范影响。
2. **站名兜底**：坐标未命中时，退回规范化站名精确匹配
   （复用 `mw_ume_topology._norm`：去非字母数字 + 转小写）。
3. 两者都不中 → 标记未匹配，不改色。

⚠️ 为什么不做模糊匹配（difflib）：
   `mw_ume_topology` 的站点经纬度匹配里确有 difflib(>=0.82) 兜底，但那是为了
   **补坐标**（错配的代价是地图上一个小点位置偏一点）。
   本模块若用模糊匹配，错配的代价是**把 90% 的严重告警画成正常链路**，
   风险等级完全不同。故此处只做「精确坐标格 + 精确站名」两级，不引入模糊。

算法复杂度：站点索引按坐标格建 hash（O(1) 查询），
整体 O(link 数 + node 数)，844 条线在毫秒级完成，无需缓存本函数自身。
"""
import logging

logger = logging.getLogger("gis_mw_overlay")

# 坐标匹配容差（度）。取 0.001 ≈ 111m：
# - 实测两套数据的同一站点坐标差通常 < 1e-4（都源自同一批勘察数据）
# - 取 0.001 既容忍浮点/精度差异，又远小于利比里亚站点间最小间距，不会跨站误配
COORD_TOL = 0.001


def _coord_key(lat, lng):
    """经纬度 -> 容差格 key。

    先按 COORD_TOL 量化再取整：同一格内的点视为同一站点。
    用 round 而非 floor，避免 -0.0004 与 +0.0004 被劈到相邻两格而错过。
    """
    if lat is None or lng is None:
        return None
    try:
        return (round(float(lat) / COORD_TOL), round(float(lng) / COORD_TOL))
    except (TypeError, ValueError):
        return None


def _build_node_index(mw_nodes):
    """MW 节点 -> (坐标格索引, 规范化站名索引)。

    返回 (by_coord, by_name)，两者都是 **站点 -> 该站全部 NE(IP) 列表**：
      by_coord: {(lat_grid, lng_grid): [{"ip":..., "name":...}, ...]}
      by_name : {规范化站名: [{"ip":..., "name":...}, ...]}

    ⚠️ 为什么每个站点要保留**全部** NE，而不是只留第一个（2026-09-28 实测踩过）：
      一个物理站点在 UME 里通常有多个 NE（多套微波设备），实测 844 条 KML 线对应
      的 414 个坐标格里，105 个格有多个 NE，平均 1.57 个/站，
      极端如 `Banjor` 有 9 个 IP、`Kebbah` 有 13 个。
      而 KPI 链路（edges）是**按 IP 对**给出的，落在哪个 NE 上是不确定的。
      若索引只留第一个 IP，`Chocolate City` 会被记成 192.168.171.99，
      于是 98.93% 的 `192.168.171.117 -> 192.168.171.118`（LPRC->Chocolate City，
      全网最严重的一条）就**查不到**，被静默当成「无 KPI 数据」——
      表现为「最该标红的线反而没颜色」，属最危险的错法。
      故这里保留全部 IP，由调用方对两端 IP 做**笛卡尔积**逐一试查。
    """
    from backend.services.mw_ume.mw_ume_topology import _norm

    by_coord, by_name = {}, {}
    for n in mw_nodes or []:
        if not n:
            continue
        ip = n.get("ip") or n.get("id")
        if not ip:
            continue
        ent = {"ip": str(ip), "name": n.get("name") or n.get("site") or ""}

        ck = _coord_key(n.get("lat"), n.get("lon"))
        if ck is not None:
            by_coord.setdefault(ck, []).append(ent)

        nk = _norm(ent["name"])
        if nk:
            by_name.setdefault(nk, []).append(ent)
    return by_coord, by_name


def _build_edge_index(mw_edges):
    """MW KPI 链路 -> {(ip_a, ip_b) 无序对: edge}。

    用 **无序对** 建索引：KML 的 a/b 方向与 MW 的主方向口径未必一致
    （mw_ume_topology 按 zte_mw_links 锚定 a->b，KML 由原作者标注），
    若按有序对查会漏掉方向相反但物理同一条的链路。
    同一条链路的正反两行都指向同一个 edge，命中哪行结果一致，故可安全覆盖。
    """
    by_pair = {}
    for e in mw_edges or []:
        if not e:
            continue
        a, b = e.get("source"), e.get("target")
        if not a or not b:
            continue
        by_pair[frozenset((str(a), str(b)))] = e
    return by_pair


def _resolve_endpoint(lat, lng, name, by_coord, by_name):
    """解析 KML 线的一个端点 -> (候选 NE 列表, matched_by)。

    两级回退：坐标优先（语义中立，不受命名规范影响），站名兜底。
    返回的是**该端点的全部候选 NE**（同一站点可能有多台设备，见 _build_node_index）。
    """
    from backend.services.mw_ume.mw_ume_topology import _norm

    ck = _coord_key(lat, lng)
    if ck is not None:
        ents = by_coord.get(ck)
        if ents:
            return ents, "coord"

    nk = _norm(name)
    if nk:
        ents = by_name.get(nk)
        if ents:
            return ents, "name"

    return None, None


def _find_edge(ents_a, ents_b, edge_by_pair):
    """在两端候选 NE 的笛卡尔积里找 KPI 链路。

    返回 (edge, a_ent, b_ent) 或 (None, None, None)。
    站点平均 1.57 个 NE、最多 13 个，笛卡尔积上限约 169 次 set 查询，
    对 844 条线可忽略不计，故不做更复杂的索引。
    同一对站点间若有多条 KPI 链路（不同 NE 对），取 max_util 最大的那条，
    与 mwRealTime「一条物理链路只呈现一个最严重值」的口径一致。
    """
    best = None
    best_a = best_b = None
    for ea in ents_a:
        for eb in ents_b:
            if ea["ip"] == eb["ip"]:
                continue
            e = edge_by_pair.get(frozenset((ea["ip"], eb["ip"])))
            if e is None:
                continue
            if best is None or (e.get("max_util") or 0) > (best.get("max_util") or 0):
                best, best_a, best_b = e, ea, eb
    return best, best_a, best_b


def match_links(gis_links, mw_nodes, mw_edges):
    """把 MW 利用率叠加到 KML 链路上。

    参数
    ----
    gis_links : /api/gis/topology 的 links（含 lat_a/lng_a/lat_b/lng_b/site_a_name/site_b_name/color）
    mw_nodes  : /api/mw-ume/realtime 的 nodes（含 ip/name/lat/lon）
    mw_edges  : /api/mw-ume/realtime 的 edges（含 source/target/tx_util/rx_util/max_util/status）

    返回
    ----
    (enriched_links, stats)

    enriched_links 为**原地复制**后的新列表，每条在原字段基础上按匹配结果新增：
      util       : float | None  —— max(tx_util, rx_util)，None = 未匹配到 KPI
      tx_util    : float | None
      rx_util    : float | None
      level      : str  —— 6 级分级；未匹配时为 'no_kpi'（**不是** 'healthy'，
                          前端据此区分「正常」与「没数据」，避免把无数据画成绿色）
      matched_by : 'coord' | 'name' | None
      source/target: 匹配到的 MW 端点站名（供悬浮提示显示，便于人工核对是否错配）

    stats：{"total","matched","matched_by_coord","matched_by_name","no_kpi",
            "endpoint_hit","endpoint_miss"}，用于接口返回与前端图例，
    让「为什么只有一半线有颜色」在界面上可解释，而不是看起来像 bug。
    """
    from backend.services.mw_ume.mw_ume_topology import level_of

    by_coord, by_name = _build_node_index(mw_nodes)
    edge_by_pair = _build_edge_index(mw_edges)

    out = []
    n_matched = n_coord = n_name = 0
    n_ep_hit = n_ep_miss = 0

    for lk in gis_links or []:
        item = dict(lk or {})
        item["util"] = None
        item["tx_util"] = None
        item["rx_util"] = None
        item["level"] = "no_kpi"
        item["matched_by"] = None
        item["source"] = ""
        item["target"] = ""

        a_ents, a_by = _resolve_endpoint(item.get("lat_a"), item.get("lng_a"),
                                         item.get("site_a_name"), by_coord, by_name)
        b_ents, b_by = _resolve_endpoint(item.get("lat_b"), item.get("lng_b"),
                                         item.get("site_b_name"), by_coord, by_name)

        n_ep_hit += int(a_ents is not None) + int(b_ents is not None)
        n_ep_miss += int(a_ents is None) + int(b_ents is None)

        if a_ents and b_ents:
            edge, a_ent, b_ent = _find_edge(a_ents, b_ents, edge_by_pair)
            if edge is not None:
                tx = edge.get("tx_util")
                rx = edge.get("rx_util")
                mx = edge.get("max_util")
                # 以两端各自命中的方式里「坐标优先」为准：任一为 coord 即记 coord
                by = "coord" if "coord" in (a_by, b_by) else "name"
                item["util"] = mx
                item["tx_util"] = tx
                item["rx_util"] = rx
                # level 用后端统一 level_of 重算，保证与 mwRealTime 页分级口径完全一致
                item["level"] = level_of(mx)
                item["matched_by"] = by
                item["source"] = a_ent["name"]
                item["target"] = b_ent["name"]
                n_matched += 1
                if by == "coord":
                    n_coord += 1
                else:
                    n_name += 1
                out.append(item)
                continue

        out.append(item)

    stats = {
        "total": len(out),
        "matched": n_matched,
        "matched_by_coord": n_coord,
        "matched_by_name": n_name,
        "no_kpi": len(out) - n_matched,
        "endpoint_hit": n_ep_hit,
        "endpoint_miss": n_ep_miss,
    }
    logger.info(
        "[MW-OVERLAY] 叠加完成: 总 %d 条, 匹配 %d (坐标 %d / 站名 %d), 无 KPI %d",
        stats["total"], stats["matched"], n_coord, n_name, stats["no_kpi"],
    )
    return out, stats
