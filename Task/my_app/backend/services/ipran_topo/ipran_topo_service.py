# -*- coding: utf-8 -*-
r"""UME 拓扑图：取数 + 聚合成一次响应的图数据（四层共用的通用实现）。

数据源
------
UME（ZTE NetNumen，`https://10.100.2.99:28001`，自签 TLS）的四张逻辑拓扑层，
端点序列与请求体结构完全一致，只有 `lid` 不同；层清单、lid 与每层口径的
真相源是同目录 `layers.py`。每层 8 组 REST 调用：

| # | 端点 | 作用 |
| --- | --- | --- |
| 1 | `POST /api/res/v1/statistic/topolayer?model=me&function=topochart&lid=…` | 层统计（当前仅用于校验层存在） |
| 2 | `GET  /api/res/v1/tree/children/{lid}?function=topochart…` | 层内网元清单（id / moc） |
| 3 | `POST /api/res/v1/common/query?includeAttr=…`（nodes） | 网元属性（displayName / ipAddress / connectionState） |
| 4 | `POST /api/res/v1/tree/children/{lid}/links?operation=…` | 层内链路（sourceId / destId） |
| 5 | `POST /api/res/v1/common/query?includeAttr=…`（links） | 链路属性（displayName / connectionState） |
| 6 | `POST /api/fm-active/v1/north/statistic/me?visible=1&maintainstatus=0` | 网元活动告警计数 |
| 7 | `POST /api/fm-active/v1/north/statistic/links?visible=1&maintainstatus=0` | 链路活动告警计数 |
| 8 | `POST /api/res/v1/common/query?includeAttr=displayName,moc,id,ipAddress,connectionState` | 层外端点名称 |

调用方法原始记录见同目录四个 `url_*.txt`（含浏览器会话头，仅作参考，**代码不读它们**；
其凭据不得进入代码、日志或响应）。抓包对应的层：
`url_ipran_fiber.txt` / `url_ipcore.txt` / `url_metro_ring.txt` / `url_dwdm.txt`。
鉴权复用 `backend/services/ipran_ume_kpi_service.py::UmeSessionClient`（OAuth2 + RSA 登录、
跨进程共享鉴权缓存），凭据组 `ipran_ume`。两个实测坑：

1. `_apply_session_headers` 用的 `forgerydefense` 头**不带 `-28001` 后缀**，带后缀一律 403。
2. 探活共享会话**不能打 `LOGIN_PORTAL`**（那里恒 200，会有假绿），必须打真实业务端点。

聚合口径（均有实测依据，勿凭直觉改）
------------------------------------
- **折叠平行链路**：ME 对之间存在多条物理链路（实测 167 条 → 141 条唯一对，其中一对 9 条、
  一对 10 条）。按 `tuple(sorted((a, b)))` 折叠，边带宽取组内**最小**端口速率 —— 取最小值
  是因为「两个机框之间还有多少条 100G」看的是最窄那条，取最大值会虚报。
- **端口速率从链路名解析**（`(\d+)GE:` → 最小；裸 `GE:` → 1）。UME 的 `rate` 字段是枚举码，
  含义未获确认，**不要**当带宽用。
- **站点坐标取 `kml_mw_links`（`kind='site'`）**，不是 `zte_mw_links`：实测对 93 个网元站点名
  命中 77 / 50，前者正好是 `frontend/public/mw_ume_orange_links.geojson` 的源表。
  模糊匹配（difflib 0.88）**必须带数字守卫** —— `12th Street` 与 `18th Street` 相似度 0.94
  但是两条街。
- **告警只给徽标，不给节点填色**：实测 93 个网元里 74 个（80%）带 critical 告警，
  按最高级填色等于 80% 的节点一个颜色，颜色失去区分度。故 `sev` 只用于徽标与 Top-N 排行。
- **层外设备必须保留**：7 个层外设备（89MW01/89MW02 微波、HQ-RAN-SW5960-1/2 交换机、
  ODC-M6000-8S-DCW1、HQ-M6K-8S_Plus_PS01/02）是层内核心的上游，89MW02 的度达 10；
  丢掉它们会让核心节点看起来很「孤立」。
- **层外设备名从第 8 次查询取**，不从链路名切分：链路名形如
  `设备名-板卡:端口--设备名-板卡:端口`，而设备名自身含下划线、板卡名也用 `-`，
  字符串切分必错。

四层与口径
----------
`build_graph(layer)` / `fetch_raw(spec)` / `_aggregate(raw, spec)` 都按层工作，
进程内缓存也按 `layer` 分槽（**跨层仍共用一把 `_fetch_lock`**，避免四个页签同时
刷新把 NMS 打满）。分层、站名清洗、端口速率解析不在本文件里堆 if-else，一律读
`layers.LayerSpec` —— 除了 ipran 是实测口径，其余三层的口径都是按抓包 moc 推断的
合理默认，待 `probe_layers.py` 实测后只改 `layers.py` 即可校准。

注意：这是**只读**链路，不向 UME 写任何东西。
"""
from __future__ import annotations

import difflib
import logging
import re
import threading
import time
from datetime import datetime, timezone

from backend.database import get_raw_connection
from backend.services.ipran_ume_kpi_service import HOST, PORT, UmeSessionClient
from backend.services.ipran_topo import layers
from backend.services.ipran_topo.layers import DEFAULT_LAYER, TIER_EXT

logger = logging.getLogger("ipran_topo")

# 一次聚合约 1.5~3.0s，8 次调用。缓存 120s（页面建议刷新 300s），
# 避免每个用户每次刷新都把 NMS 打一遍。
CACHE_TTL_SEC = 120

# 站点名 -> 坐标的索引来源（由 services/mw_ume/mw_links_store.py 从 KML 写入）
SITE_TABLE = "kml_mw_links"

NODE_ATTRS = (
    "displayName,description,nbiId,subType,administrativeState,presid,id,maintainState,"
    "alarmColor,highestAlarmCount,acked,ackedHighestAlarmColor,ackedBubbleColor,longitude,"
    "latitude,configClock_moc,tunnel_rc_state,ifRootNode,moc,connectionState,"
    "config1588_nodeType,actual1588_passiveNode,actualClock_lockState,configClock_lockState,"
    "config1588_slave,operationalState,consistentState,userdefinedState,ifGateway,"
    "actualClock_switchState,tunnel_ends_state,timeoverrun,configClock_switchState,"
    "ncpDbEmpty,actual1588_lockState,ifOTDR,isAccessMeLabel,actualClock_moc,withCtrl,"
    "actual1588_timeSourceType,areaLocated,critical,major,minor,warning,ipAddress"
)
LINK_ATTRS = (
    "displayName,description,nbiId,moc,id,connectionState,alarmColor,linkText,direction,"
    "brokeDirection,ptview_type,ctview_direct,tunnel_rc_state,dcmStatus,tms_color,"
    "textColor,mode,textLabel,vbras_link_color,vbras_link_type_badge,rate,customStyle,"
    "destIP,destPortId,sourceIP,sourcePortId"
)

_req_lock = threading.Lock()
# 四层共用一把取数锁：全局串行化，避免用户连切页签时 4×8 次调用同时打向 NMS
_fetch_lock = threading.Lock()
# 每层独立缓存槽，键是 layers.LAYERS 的 key（切页签不会串数据）
_cache: dict[str, dict] = {}
_client: UmeSessionClient | None = None
_site_index: dict | None = None
_site_lock = threading.Lock()


def _cache_slot(layer: str) -> dict:
    return _cache.setdefault(layer, {"ts": 0.0, "data": None})


# ----------------------------------------------------------------------------
# UME 取数
# ----------------------------------------------------------------------------
def _client_instance() -> UmeSessionClient:
    global _client
    with _req_lock:
        if _client is None:
            _client = UmeSessionClient(HOST, PORT)
        return _client


def _call(client: UmeSessionClient, method: str, path: str, payload=None, timeout: int = 60):
    kwargs = {"timeout": timeout}
    if payload is not None:
        kwargs["json"] = payload
    resp = client.request_with_retry(method, path, **kwargs)
    return resp.json()


def fetch_raw(spec: layers.LayerSpec) -> dict:
    """跑完 8 组 UME 调用，返回原始响应（不落盘）。"""
    lid = spec.lid
    client = _client_instance()
    client.login()

    topo = _call(
        client, "POST",
        f"/api/res/v1/statistic/topolayer?model=me&countDisconnect=true&function=topochart&lid={lid}")
    children = _call(
        client, "GET",
        f"/api/res/v1/tree/children/{lid}?function=topochart&operation=operation.topo.viewlogicview"
        f"&dataType=tree&expandDepth=1&structureFlag=0&LogTracking=true"
        f"&rm%3AresponseError=true&rm:aboveMe=0")
    node_ids = [n["id"] for n in children]
    # 探层前不保证四层 children 都带 moc，缺 moc 的节点跳过而不是让整层取数失败
    node_mocs = sorted({n["moc"] for n in children if n.get("moc")})
    nodes_attr = _call(client, "POST", f"/api/res/v1/common/query?includeAttr={NODE_ATTRS}",
                       {"id": node_ids, "moc": node_mocs})
    links_topo = _call(
        client, "POST",
        f"/api/res/v1/tree/children/{lid}/links?operation=operation.topo.viewlogicview",
        {"function": "topochart", "logicLevel": 2, "operation": "topochart",
         "layerNodeIds": {lid: node_ids}})
    link_ids = [x["id"] for x in links_topo]
    links_attr = _call(client, "POST", f"/api/res/v1/common/query?includeAttr={LINK_ATTRS}",
                       {"id": link_ids, "moc": ["wl.link"]})
    alarm_me = _call(client, "POST", "/api/fm-active/v1/north/statistic/me?visible=1&maintainstatus=0",
                     [{"dn": "", "me": i} for i in node_ids])
    alarm_links = _call(client, "POST", "/api/fm-active/v1/north/statistic/links?visible=1&maintainstatus=0",
                        {"links": link_ids})

    ext_ids = sorted({e[s] for e in links_topo for s in ("sourceId", "destId")} - set(node_ids))
    ext_attr = []
    if ext_ids:
        ext_attr = _call(
            client, "POST",
            "/api/res/v1/common/query?includeAttr=displayName,moc,id,ipAddress,connectionState",
            {"id": ext_ids})

    return {
        "topo": topo, "children": children, "nodes_attr": nodes_attr,
        "links_topo": links_topo, "links_attr": links_attr,
        "alarm_me": alarm_me, "alarm_links": alarm_links, "ext_attr": ext_attr,
        "ext_ids": ext_ids,
    }


# ----------------------------------------------------------------------------
# 站点坐标
# ----------------------------------------------------------------------------
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _load_site_index(force: bool = False) -> dict:
    """`kml_mw_links` 站点点 -> {norm_name: (name, lat, lon)}（进程内缓存一次）。"""
    global _site_index
    with _site_lock:
        if _site_index is not None and not force:
            return _site_index
        idx: dict = {}
        t0 = time.time()
        try:
            conn = get_raw_connection()
            cur = conn.cursor()
            cur.execute(
                f"SELECT name, lat, lon FROM {SITE_TABLE} WHERE kind='site'")
            for name, lat, lon in cur.fetchall():
                if not name:
                    continue
                try:
                    lat_f, lon_f = float(lat), float(lon)
                except (TypeError, ValueError):
                    continue
                idx.setdefault(_norm(name), (str(name).strip(), lat_f, lon_f))
            conn.close()
            logger.info("[SITE] %s 站点 %d 个，用时 %.2fs", SITE_TABLE, len(idx), time.time() - t0)
        except Exception as e:
            logger.warning("[SITE] %s 加载失败: %s", SITE_TABLE, e)
        _site_index = idx
        return idx


def _match_site(name: str, index: dict):
    """站名 -> (原名, lat, lon, how)；how ∈ exact/fuzzy/miss。"""
    if not name or not index:
        return None, None, None, "miss"
    key = _norm(name)
    if key in index:
        nm, lat, lon = index[key]
        return nm, lat, lon, "exact"
    close = difflib.get_close_matches(key, list(index.keys()), n=1, cutoff=0.88)
    if close:
        nm, lat, lon = index[close[0]]
        # 数字不同的站点一律不认：12th Street 与 18th Street 相似度 0.94，但是两条街
        if layers.DIGITS_RE.findall(name) != layers.DIGITS_RE.findall(nm):
            return None, None, None, "miss"
        return nm, lat, lon, "fuzzy"
    return None, None, None, "miss"


# ----------------------------------------------------------------------------
# 聚合
# ----------------------------------------------------------------------------
def _sev(stat: dict) -> str:
    for level, key in (("crit", "criticalcount"), ("major", "majorcount"),
                       ("minor", "minorcount"), ("warn", "warningcount")):
        if stat.get(key):
            return level
    return "ok"


def _is_up(v) -> bool:
    return str(v) == "1"


def build_graph(layer: str = DEFAULT_LAYER, force: bool = False) -> dict:
    """返回指定层的完整图数据；每层独立缓存 CACHE_TTL_SEC 秒。

    `layer` 必须在 `layers.LAYERS` 白名单内（路由层已校验）。不带 layer 时仍是
    原来的 IP RAN 光纤层，现有页面与旧调用方式无需改动。
    """
    spec = layers.resolve_layer(layer)
    if spec is None:
        raise ValueError(f"未知拓扑层: {layer}")
    slot = _cache_slot(layer)
    now = time.time()
    if not force and slot["data"] is not None and now - slot["ts"] < CACHE_TTL_SEC:
        data = dict(slot["data"])
        data["meta"] = {**data["meta"], "cached": True}
        return data

    # 上游一次取数要 1.5~3.0s；四层共用一把锁串行化，后来者复用前者的结果
    with _fetch_lock:
        slot = _cache_slot(layer)
        now = time.time()
        if not force and slot["data"] is not None and now - slot["ts"] < CACHE_TTL_SEC:
            data = dict(slot["data"])
            data["meta"] = {**data["meta"], "cached": True}
            return data

        t0 = time.time()
        try:
            raw = fetch_raw(spec)
            payload = _aggregate(raw, spec)
        except Exception:
            if slot["data"] is not None:
                # 上游抖动时返回该层上一版可用数据，并在 meta 里显式标注，界面必须能看到
                logger.exception("[IPRAN-TOPO] layer=%s 取数失败，回退到 %.0fs 前的缓存",
                                 layer, time.time() - slot["ts"])
                data = dict(slot["data"])
                data["meta"] = {**data["meta"], "cached": True, "stale": True,
                                "warnings": list(data["meta"].get("warnings") or []),
                                }
                data["meta"]["warnings"].append("upstream_unreachable: 上游取数失败，当前为上次成功的数据")
                return data
            raise

        elapsed = time.time() - t0
        payload["meta"].update({"fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "elapsedSec": round(elapsed, 2), "cached": False})
        slot["ts"] = time.time()
        slot["data"] = payload
        logger.info("[IPRAN-TOPO] layer=%s 聚合完成 网元=%d 原始链路=%d 折叠边=%d 用时 %.2fs",
                    layer, payload["meta"]["ne"], payload["meta"]["rawLinks"],
                    payload["meta"]["foldedLinks"], elapsed)
        return payload


def _aggregate(raw: dict, spec: layers.LayerSpec) -> dict:
    nodes_attr = raw["nodes_attr"] or []
    links_topo = raw["links_topo"] or []
    links_attr = {x["id"]: x for x in (raw["links_attr"] or [])}
    alarm_me = {x.get("me"): x for x in (raw["alarm_me"] or []) if x.get("me")}
    alarm_links = {x.get("link"): x for x in (raw["alarm_links"] or []) if x.get("link")}
    nodes = {n["id"]: n for n in nodes_attr}
    ext_attr = {x["id"]: x for x in (raw["ext_attr"] or []) if x.get("id")}
    site_index = _load_site_index()

    # ---- 节点 ----
    out_nodes = []
    geo_stat = {"exact": 0, "fuzzy": 0, "miss": 0}
    fuzzy_pairs = []
    miss_sites = []
    for nid, n in nodes.items():
        display_name = n.get("displayName") or ""
        site = layers.site_of(display_name, spec)
        geo_name, lat, lon, how = _match_site(site, site_index)
        geo_stat[how] = geo_stat.get(how, 0) + 1
        if how == "fuzzy":
            fuzzy_pairs.append({"site": site, "matched": geo_name})
        elif how == "miss":
            miss_sites.append(site)
        stat = alarm_me.get(nid, {})
        out_nodes.append({
            "id": nid,
            "name": display_name,
            "site": site,
            "tier": layers.tier_of(display_name, n.get("moc") or "", spec),
            "model": (n.get("moc") or "").split(".")[-1],
            "ip": n.get("ipAddress") or "",
            "up": 1 if _is_up(n.get("connectionState")) else 0,
            "crit": stat.get("criticalcount", 0) or 0,
            "major": stat.get("majorcount", 0) or 0,
            "minor": stat.get("minorcount", 0) or 0,
            "warn": stat.get("warningcount", 0) or 0,
            "sev": _sev(stat),
            "lat": lat, "lon": lon, "geo": how, "geoName": geo_name or "",
        })

    # 层外设备名来自 UME（不靠链路名切分，见模块 docstring）
    ext_names = {}
    for fid in raw["ext_ids"]:
        xa = ext_attr.get(fid, {})
        nm = xa.get("displayName") or f"层外-{fid[:8]}"
        ext_names[fid] = nm
        out_nodes.append({
            "id": fid, "name": nm, "site": nm, "tier": TIER_EXT,
            "model": (xa.get("moc") or "").split(".")[-1] or "",
            "ip": xa.get("ipAddress") or "",
            "up": 1 if _is_up(xa.get("connectionState")) else 0,
            "crit": 0, "major": 0, "minor": 0, "warn": 0, "sev": "ok",
            "lat": None, "lon": None, "geo": "ext", "geoName": "",
        })

    known = {v["id"] for v in out_nodes}

    # ---- 折叠平行链路（同一 ME 对多条物理链路 -> 一条边）----
    by_pair: dict = {}
    for e in links_topo:
        a, b = e.get("sourceId"), e.get("destId")
        if not a or not b or a not in known or b not in known:
            continue
        by_pair.setdefault(tuple(sorted((a, b))), []).append(e)

    out_edges = []
    for (a, b), group in by_pair.items():
        speeds = [s for s in (layers.speed_gb(x.get("displayName") or "", spec) for x in group) if s]
        alarms = [alarm_links.get(x["id"], {}) for x in group]
        down = sum(1 for x in group if not _is_up(links_attr.get(x["id"], {}).get("connectionState")))
        out_edges.append({
            "s": a, "t": b, "n": len(group),
            # 取最小端口速率：看的是这对机框之间「最窄」的那条，取最大会虚报
            "gb": min(speeds) if speeds else None,
            "down": down,
            "crit": sum(x.get("criticalcount", 0) or 0 for x in alarms),
            "major": sum(x.get("majorcount", 0) or 0 for x in alarms),
            "ports": [x.get("displayName") or "" for x in group][:12],
        })

    deg: dict = {v["id"]: 0 for v in out_nodes}
    for e in out_edges:
        deg[e["s"]] += e["n"]
        deg[e["t"]] += e["n"]
    for v in out_nodes:
        v["deg"] = deg.get(v["id"], 0)

    ne_nodes = [v for v in out_nodes if v["tier"] != TIER_EXT]
    crit_ne = sum(1 for v in ne_nodes if v["crit"] > 0)
    tier_counts: dict = {}
    for v in out_nodes:
        k = str(v["tier"])
        tier_counts[k] = tier_counts.get(k, 0) + 1

    warnings = []
    if crit_ne and crit_ne / max(1, len(ne_nodes)) > 0.5:
        warnings.append(
            f"alarm_saturated: {crit_ne}/{len(ne_nodes)} 个网元带紧急告警"
            f"（{round(crit_ne * 100 / max(1, len(ne_nodes)))}%），按最高级填色会失去区分度，故只做徽标")
    if miss_sites:
        warnings.append(f"geo_miss: {len(miss_sites)} 个站点在 {SITE_TABLE} 里没有坐标")
    if fuzzy_pairs:
        warnings.append(f"geo_fuzzy: {len(fuzzy_pairs)} 个站点是近似匹配，需人工确认")

    meta_extra = raw.get("meta") or {}
    return {
        "nodes": out_nodes,
        "edges": out_edges,
        "meta": {
            **meta_extra,
            "layer": spec.key,
            "layerName": spec.name_zh,
            "ne": len(ne_nodes),
            "ext": len(ext_names),
            "rawLinks": len(links_topo),
            "foldedLinks": len(out_edges),
            "tierCounts": tier_counts,
            "geo": {**geo_stat, "ext": len(ext_names)},
            "geoMissSites": miss_sites,
            "geoFuzzyPairs": fuzzy_pairs,
            "critNe": crit_ne,
            "warnings": warnings,
        },
    }


def refresh_site_index() -> int:
    """强制重读站点坐标（KML 上传后调用，否则最多滞后一个缓存周期 + 进程寿命）。"""
    return len(_load_site_index(force=True))


def clear_cache(layer: str | None = None) -> None:
    """清图缓存；传 layer 只清该层，不传则清全部层（历史行为）。"""
    with _fetch_lock:
        targets = (_cache_slot(layer),) if layer else tuple(_cache.values())
        for slot in targets:
            slot["ts"] = 0.0
            slot["data"] = None
