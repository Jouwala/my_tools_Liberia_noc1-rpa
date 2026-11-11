# -*- coding: utf-8 -*-
r"""UME 四层拓扑只读探层（校准 layers.py 口径用）。

用途
----
四层的设备型号、网元命名、链路带宽格式差异很大，`layers.py` 里的分层 / 站名清洗 /
带宽规则除 ipran 外都是按抓包 `moc` 推断的默认值。本脚本在内网跑一次，把每层的
**真实** moc 分布、网元命名、链路名样例和「当前口径跑出来的分层结果」打印出来，
据此只改 `layers.py` 的规则即可，不必动聚合逻辑。

用法（在 `Task/my_app` 目录下）
------------------------------
    python -m backend.services.ipran_topo.probe_layers
    python -m backend.services.ipran_topo.probe_layers --layer ipcore
    python -m backend.services.ipran_topo.probe_layers --out D:/tmp/topo_probe.json

约束
----
- **只读**：只发 GET / 查询类 POST，不向 UME 写任何东西。
- **不打印凭据**：鉴权走 `UmeSessionClient` 的共享会话（凭据组 `ipran_ume`），
  输出里不含 Cookie / Token / 请求头；人工布局端点只输出结构（键名与类型），不输出值。
- **默认不落盘**：结果打到 stdout；只有显式 `--out` 才写文件，避免运行时产物混进 git。
- 一次约 20~28 次上游调用，别频繁跑（UME 账号有锁号风险，见 05-security-and-credentials.md）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone

from backend.services.ipran_topo import layers

# 探层只取校准所需的字段，故意不用服务层的全量属性串：脚本因此不 import
# ipran_topo_service，不会连带拖进 database / pandas 等后端全套依赖。
PROBE_NODE_ATTRS = "displayName,moc,id,ipAddress,connectionState"
PROBE_LINK_ATTRS = "displayName,moc,id,connectionState,rate"

SAMPLE_MAX = 12
NAME_MAX = 80


def _call(client, method: str, path: str, payload=None, timeout: int = 60):
    """与服务的取数方式一致；不记录、不返回任何请求头。"""
    kwargs = {"timeout": timeout}
    if payload is not None:
        kwargs["json"] = payload
    return client.request_with_retry(method, path, **kwargs).json()


def _shape(value, depth: int = 0):
    """只输出结构（键名 + 类型），绝不输出值 —— 人工布局等未知响应不能泄露内容。"""
    if depth > 3:
        return "..."
    if isinstance(value, dict):
        return {k: _shape(v, depth + 1) for k, v in list(value.items())[:24]}
    if isinstance(value, list):
        return {"__len__": len(value), "__item__": _shape(value[0], depth + 1) if value else None}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _safe_err(exc: Exception) -> str:
    """异常文本可能带上游返回的片段，截断并抹掉疑似凭据字样。"""
    msg = str(exc)[:300]
    low = msg.lower()
    if any(k in low for k in ("cookie", "authorization", "z-auth-code", "forgerydefense", "token")):
        return "<已隐去：异常文本含疑似鉴权字段>"
    return msg


def _names(rows, key: str = "displayName") -> list[str]:
    out = []
    for row in rows or []:
        if isinstance(row, dict) and row.get(key):
            out.append(str(row[key])[:NAME_MAX])
    return out[:SAMPLE_MAX]


def _probe_one(client, spec: layers.LayerSpec, timeout: int) -> dict:
    lid = spec.lid
    result: dict = {
        "key": spec.key, "lid": lid, "nameZh": spec.name_zh,
        "configuredNote": spec.note, "ok": False,
    }
    children_qs = (
        f"/api/res/v1/tree/children/{lid}?function=topochart"
        f"&operation=operation.topo.viewlogicview&dataType=tree&expandDepth=1"
        f"&structureFlag=0&LogTracking=true&rm%3AresponseError=true&rm:aboveMe=0"
    )

    topo = _call(client, "POST",
                 f"/api/res/v1/statistic/topolayer?model=me&countDisconnect=true"
                 f"&function=topochart&lid={lid}", timeout=timeout)
    result["topolayer"] = _shape(topo)

    children = _call(client, "GET", children_qs, timeout=timeout)
    # 不同层的 children 可能是裸数组，也可能包在 data/children 里；探层要先看清形状
    if isinstance(children, dict):
        result["childrenShape"] = _shape(children)
        children = children.get("children") or children.get("data") or []
    if not isinstance(children, list):
        children = []
    node_ids = [str(n["id"]) for n in children if isinstance(n, dict) and n.get("id")]
    node_mocs = sorted({str(n["moc"]) for n in children if isinstance(n, dict) and n.get("moc")})
    result["children"] = {
        "count": len(children),
        "withId": len(node_ids),
        "withMoc": sum(1 for n in children if isinstance(n, dict) and n.get("moc")),
        "mocDist": dict(Counter(
            str(n.get("moc") or "<missing>") for n in children if isinstance(n, dict))),
        "idsInChildren": node_ids[:5],
    }

    nodes_attr = _call(
        client, "POST", f"/api/res/v1/common/query?includeAttr={PROBE_NODE_ATTRS}",
        {"id": node_ids, "moc": node_mocs}, timeout=timeout)
    if isinstance(nodes_attr, dict):
        nodes_attr = nodes_attr.get("data") or nodes_attr.get("result") or []
    if not isinstance(nodes_attr, list):
        nodes_attr = []
    names = _names(nodes_attr)
    result["nodes"] = {
        "count": len(nodes_attr),
        "displayNameSamples": names,
        "mocDist": dict(Counter(
            str(n.get("moc") or "") for n in nodes_attr if isinstance(n, dict))),
        "connectionStateDist": dict(Counter(
            str(n.get("connectionState")) for n in nodes_attr if isinstance(n, dict))),
        "withIpAddress": sum(1 for n in nodes_attr if isinstance(n, dict) and n.get("ipAddress")),
    }

    links_topo = _call(
        client, "POST",
        f"/api/res/v1/tree/children/{lid}/links?operation=operation.topo.viewlogicview",
        {"function": "topochart", "logicLevel": 2, "operation": "topochart",
         "layerNodeIds": {lid: node_ids}}, timeout=timeout)
    if isinstance(links_topo, dict):
        result["linksShape"] = _shape(links_topo)
        links_topo = links_topo.get("links") or links_topo.get("data") or []
    if not isinstance(links_topo, list):
        links_topo = []
    link_ids = [str(x["id"]) for x in links_topo if isinstance(x, dict) and x.get("id")]
    endpoints = {
        str(x.get(s)) for x in links_topo if isinstance(x, dict)
        for s in ("sourceId", "destId") if x.get(s)
    }
    result["links"] = {
        "count": len(links_topo),
        "withId": len(link_ids),
        "outOfLayerEndpoints": len(endpoints - set(node_ids)),
        "endpointIdsNotInChildren": sorted(endpoints - set(node_ids))[:SAMPLE_MAX],
        "nameSamples": _names(links_topo),
    }

    links_attr = _call(
        client, "POST", f"/api/res/v1/common/query?includeAttr={PROBE_LINK_ATTRS}",
        {"id": link_ids, "moc": ["wl.link"]}, timeout=timeout)
    if isinstance(links_attr, dict):
        links_attr = links_attr.get("data") or links_attr.get("result") or []
    if not isinstance(links_attr, list):
        links_attr = []
    link_names = [str(n.get("displayName") or "") for n in links_attr if isinstance(n, dict)]
    speeds = [layers.speed_gb(nm, spec) for nm in link_names]
    result["linkAttrs"] = {
        "count": len(links_attr),
        "nameSamples": [nm[:NAME_MAX] for nm in link_names[:SAMPLE_MAX]],
        "speedParsed": sum(1 for s in speeds if s is not None),
        "speedDist": dict(Counter(str(s) for s in speeds)),
        "rateFieldSamples": [str(n.get("rate")) for n in links_attr[:SAMPLE_MAX]
                             if isinstance(n, dict)],
    }

    # 当前口径跑出来的结果：分层是否塌成一层、站名清洗是否剥干净、带宽是否解析得出
    tiers = [layers.tier_of(n.get("displayName") or "", n.get("moc") or "", spec)
             for n in nodes_attr if isinstance(n, dict)]
    result["calibration"] = {
        "tierDist": dict(Counter(str(t) for t in tiers)),
        "tierLabels": list(spec.tier_labels),
        "siteSamples": [layers.site_of(nm, spec)[:NAME_MAX] for nm in names],
        "speedParsedRate": (
            round(result["linkAttrs"]["speedParsed"] / max(1, len(link_names)), 3)),
    }

    if spec.saved_layout:
        saved = {}
        for label, path in (
            ("globalTopoLayout", f"/api/topo/v1/layer/global-topo-layout/{lid}"),
            ("topoHeaderPath", f"/api/topo/v1/layer/topo-header-path/{lid}"),
        ):
            try:
                saved[label] = _shape(_call(client, "GET", path, timeout=timeout))
            except Exception as exc:
                saved[label] = {"error": _safe_err(exc)}
        result["savedLayout"] = saved

    alerts = []
    if result["children"]["withMoc"] < result["children"]["count"]:
        alerts.append("children 有节点缺 moc：服务层会跳过它们，需确认这是否影响属性查询")
    if len(set(tiers)) <= 1 and tiers:
        alerts.append("当前口径把整层判成同一个 tier：分层视图会塌成一条带，需按实测命名补 tier_rules")
    if result["calibration"]["speedParsedRate"] < 0.5:
        alerts.append("带宽解析命中率低于 50%：需按真实链路名补 speed_res")
    if not result["calibration"]["siteSamples"]:
        alerts.append("没有拿到 displayName 样例：站名清洗规则无法校准")
    result["alerts"] = alerts
    result["ok"] = True
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="UME 四层拓扑只读探层（校准 layers.py 口径）")
    ap.add_argument("--layer", choices=list(layers.LAYER_KEYS),
                    help="只探一层，减少上游调用；默认四层全探")
    ap.add_argument("--out", help="可选：把 JSON 结果写到指定路径（默认只打印到 stdout）")
    ap.add_argument("--timeout", type=int, default=60, help="单次请求超时秒数")
    args = ap.parse_args(argv)

    # 鉴权模块是重依赖（pandas / requests / database），延迟到真正要连 UME 时才导入：
    # 这样 --help 与口径纯逻辑检查在没有后端全套依赖的机器上也能跑。
    try:
        from backend.services.ipran_ume_kpi_service import HOST, PORT, UmeSessionClient
    except ImportError as exc:
        print(json.dumps({"error": "缺少运行依赖，请用项目 Python 环境执行",
                          "detail": _safe_err(exc)}, ensure_ascii=False, indent=2))
        return 2

    targets = [layers.LAYERS[args.layer]] if args.layer else list(layers.LAYERS.values())
    report = {
        "probeAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "umeHost": HOST,
        "layers": [],
    }

    client = UmeSessionClient(HOST, PORT)
    try:
        client.login()
    except Exception as exc:
        print(json.dumps({"error": "UME 登录失败", "detail": _safe_err(exc)},
                         ensure_ascii=False, indent=2))
        return 2

    for spec in targets:
        try:
            report["layers"].append(_probe_one(client, spec, args.timeout))
        except Exception as exc:
            # 单层失败不中断其余层，也不静默吞错
            report["layers"].append({
                "key": spec.key, "lid": spec.lid, "nameZh": spec.name_zh,
                "ok": False, "error": _safe_err(exc),
            })

    report["hint"] = (
        "据此核对 layers.py：tier_rules 是否把整层判成同一级、site_strip 是否剥掉型号前缀、"
        "speed_res 是否覆盖真实链路名。改配置即可，不要改聚合逻辑。"
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"已写入 {args.out}")
    else:
        print(text)
    return 0 if all(x.get("ok") for x in report["layers"]) else 1


if __name__ == "__main__":
    sys.exit(main())
