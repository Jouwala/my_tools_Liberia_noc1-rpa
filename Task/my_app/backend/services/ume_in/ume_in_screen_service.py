# -*- coding: utf-8 -*-
"""UME 割接大屏（guard-imonitor-iui largescreen）数据抓取脚本（ume_in）

数据来源（见 backend/services/ume_in/url.txt）：
    https://172.17.208.1:28808/iui/guard-imonitor-iui/#/screen/screen-view?screen_id=1
    大屏配置  GET  /api/guard-imonitor-service/v1/largescreen/screen?screen_id=1
    组件数据  POST /api/guard-imonitor-service/v1/largescreen/data4component
    Body：{"class":"line4multi2","screen_id":1,"args":{...}}

与 ume_in_dashboard_service.py / ume_in_kpi_service.py 的关系：
- **鉴权完全复用** ``UMEPortalClient``（原始 socket + TLS 免证书校验 → OAuth2 authorize →
  RSA 公钥 → login_rsa → 拿 cookie/forgery_token，全程内存不落盘）。
- 本模块打的是**大屏（largescreen）服务**：先 GET 大屏配置拿到「子模板 + 组件清单」，
  再把组件的 ``args`` **原样** POST 给 data4component。

======================= 关键机制（实测结论）=======================
1. 一个 ``screen_id`` 对应**多个子模板**（screen_id=1 → 4 个）：
   OLib_OSG_CAPs(template_id=1) / OLib_OSG_SuccessRate(4) /
   OLib_OSG_Service_KPI(3) / OSG_Platform_KPI(2)。
   页面按子模板轮播，抓包里那个 ``line4multi2`` 的 caps 图属于 OLib_OSG_CAPs。

2. 配置里每个数据组件长这样（``templateJson.elements[]``）::

       {"name":"a.GS-echarts","class":"line4multi2","refresh_ms":180000,
        "args":{"group_level":"NE","series":[...],"gr":"5min","last_hours":"$lasthours$"}}

   ``args`` 里的 ``$NEID$`` / ``$lasthours$`` 是**服务端占位符**，
   必须**原样透传**，不要自己替换：
     - 传字面量 ``$NEID$`` → 返回真实数据（实测 144 点）
     - 换成 NE 的 uuid / label / moc / 空串 → 200 但 series 为空（0 点）
   也就是说 NE 解析在**服务端**按 ``screen_id`` 存的大屏参数完成。

3. 客户端**可以**覆盖的字段（实测）：
     - ``last_hours``：数字即生效（1 → 1 小时窗口，12 → 12 小时）。
     - ``gr``：命中服务端白名单才生效（``5min`` / ``15min`` / ``1h`` 生效；
       传 ``30min`` / ``60min`` / ``1hour`` / ``1day`` 等非法值会**静默回落 15min**）。
     - ``kpi_id`` / ``expression`` / ``decimal_digits``：按传入值生效。
   不能覆盖的：``ne_ids``（见第 2 点）。

4. 时间窗口是**本地时间**，由服务端按 ``last_hours`` 反推，请求里不带起止时间。
   响应里 ``result.data[0]`` = ``{"series":[...], "begintime", "endtime", "gr"}``，
   每个 series 的 ``data[]`` 点形如::

       {"begintime":"2026-09-18 11:05:00","endtime":"2026-09-18 11:10:00",
        "timestamp":"2026-09-18 11:10:00","value":"397"}

   ⚠️ **最后一个（未走完的）时间桶 value 是空串 ""**，解析时必须当 None 处理。

用法：
    # 列出 screen_id=1 的子模板与组件清单
    python -m backend.services.ume_in.ume_in_screen_service --list

    # 抓 OLib_OSG_CAPs 子模板全部 10 个组件，打印摘要
    python -m backend.services.ume_in.ume_in_screen_service --template OLib_OSG_CAPs

    # 抓单个组件、覆盖时间窗为 12 小时、原始 JSON 落文件
    python -m backend.services.ume_in.ume_in_screen_service \
        --template OLib_OSG_CAPs --component a.GS-echarts --last-hours 12 \
        --save TMP/screen1_caps_a.json --full
"""

import argparse
import copy
import json
import logging
import os
import sys
import time

from backend.services.ume_in.ume_in_kpi_service import UMEPortalClient, _runtime_credentials

logger = logging.getLogger("ume_in_screen_service")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - 非 Windows / 已被重定向时忽略
    pass

# ============================================================
# 接口配置（可用环境变量覆盖）
# ============================================================
SCREEN_PATH = os.environ.get(
    "UME_IN_SCREEN_PATH", "/api/guard-imonitor-service/v1/largescreen/screen"
)
COMPONENT_PATH = os.environ.get(
    "UME_IN_SCREEN_COMPONENT_PATH",
    "/api/guard-imonitor-service/v1/largescreen/data4component",
)

# 默认大屏（用户抓包的 screen-view?screen_id=1）
DEFAULT_SCREEN_ID = int(os.environ.get("UME_IN_SCREEN_ID", "1"))

# 大屏接口的 Referer 必须是 iui 页面，不是门户首页
IUI_REFERER = os.environ.get(
    "UME_IN_SCREEN_REFERER",
    "https://172.17.208.1:28808/iui/guard-imonitor-iui/",
)

# 组件刷新间隔兜底（配置里带 refresh_ms，缺失时用这个）
DEFAULT_REFRESH_MS = 180000

# templateJson.elements 里这些 class 是纯展示元素，没有数据接口
NON_DATA_CLASSES = {
    "png", "jpg", "jpeg", "gif", "svg", "image", "bg",
    "label", "text", "rect", "line", "current", "clock", "iframe", "video",
}


# ============================================================
# 数值工具
# ============================================================
def _num(v):
    """把响应里的字符串数值转 float；空串/None/不可解析 → None（未走完的时间桶是 ""）。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ============================================================
# 1) 大屏配置：子模板 + 组件清单
# ============================================================
def fetch_screen_config(client, screen_id=DEFAULT_SCREEN_ID):
    """GET 大屏配置，返回原始 JSON（result.data 是 [[子模板, ...]]）。"""
    path = f"{SCREEN_PATH}?screen_id={int(screen_id)}"
    logger.info(f"[SCREEN] GET {path}")
    status, _hdrs, _raw, resp = client._request_retry(
        "GET", path, headers_extra=client._auth_headers(extra={"Referer": IUI_REFERER})
    )
    text = resp.decode("utf-8", errors="replace")
    if "200" not in status:
        raise Exception(f"大屏配置请求失败: screen_id={screen_id} {status} {text[:300]}")
    return json.loads(text)


def parse_screen_config(data):
    """把大屏配置拆成 [{name, template_name, template_id, params, components}]。"""
    rows = (data.get("result") or {}).get("data") or []
    templates = []
    for row in rows:
        for t in (row if isinstance(row, list) else [row]):
            if not isinstance(t, dict):
                continue
            templates.append(parse_template(t))
    return templates


def parse_template(t):
    """解析单个子模板：参数（NEID/title/lasthours）+ 数据组件清单。

    同时保留 ``width``/``height``（画布尺寸，实测 1920x1080）与 ``elements``
    （**全部**元素，含 png/label/current），供 ume_in_screen_render 原样还原页面。
    """
    try:
        params = json.loads(t.get("params") or "[]")
    except json.JSONDecodeError:
        params = []
    try:
        tpl_json = json.loads(t.get("templateJson") or "{}") or {}
    except json.JSONDecodeError:
        tpl_json = {}
    elements = tpl_json.get("elements") or []

    components = []
    for e in elements:
        if not isinstance(e, dict):
            continue
        cls = e.get("class")
        if not cls or cls in NON_DATA_CLASSES:
            continue
        components.append({
            "name": e.get("name"),
            "class": cls,
            "args": e.get("args") or {},
            "refresh_ms": e.get("refresh_ms") or DEFAULT_REFRESH_MS,
            "position": {"x": e.get("x"), "y": e.get("y"),
                         "width": e.get("width"), "height": e.get("height")},
        })

    return {
        "name": t.get("name"),
        "template_name": t.get("templateName"),
        "template_id": t.get("template_id"),
        "id": t.get("_id"),
        "width": tpl_json.get("width"),
        "height": tpl_json.get("height"),
        "elements": elements,
        "params": params,
        "param_values": {p.get("name"): p.get("value") for p in params if p.get("name")},
        "ne_options": _ne_options(params),
        "components": components,
    }


def _ne_options(params):
    """把 MULTI-NE 参数的候选 NE 拉平，便于按名字/uuid 定位大屏绑定的 NE。"""
    out = []
    for p in params:
        if p.get("type") != "MULTI-NE":
            continue
        for nt in p.get("netype") or []:
            for ne in nt.get("nes") or []:
                out.append({"moc": nt.get("value"), "moc_label": nt.get("label"),
                            "label": ne.get("label"), "value": ne.get("value")})
    return out


def pick_template(templates, template_name=None):
    """按名字（或 name/template_name 模糊）挑子模板；不传则返回第一个。"""
    if not templates:
        raise Exception("大屏没有任何子模板")
    if not template_name:
        return templates[0]
    key = str(template_name).strip().lower()
    for t in templates:
        if key in (str(t.get("name") or "").lower(), str(t.get("template_name") or "").lower()):
            return t
    for t in templates:  # 退化成子串匹配
        if key in str(t.get("name") or "").lower() or key in str(t.get("template_name") or "").lower():
            return t
    raise Exception(f"未找到子模板 {template_name!r}，可选："
                    f"{[t.get('name') for t in templates]}")


# ============================================================
# 2) 组件数据
# ============================================================
def build_component_body(component, screen_id=DEFAULT_SCREEN_ID, last_hours=None):
    """组装 data4component 请求体。

    ``args`` **原样**透传（``$NEID$`` / ``$lasthours$`` 交给服务端解析）；
    仅当显式传 ``last_hours`` 时覆盖时间窗（服务端认数字，实测生效）。
    """
    args = copy.deepcopy(component.get("args") or {})
    if last_hours is not None and "last_hours" in args:
        args["last_hours"] = int(last_hours)
    return {"class": component.get("class"), "screen_id": int(screen_id), "args": args}


def fetch_component(client, component, screen_id=DEFAULT_SCREEN_ID, last_hours=None):
    """POST 单个组件，返回解析后的 JSON。"""
    payload = build_component_body(component, screen_id, last_hours)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    logger.info(f"[COMP] POST {COMPONENT_PATH} class={payload['class']} "
                f"name={component.get('name')} last_hours={payload['args'].get('last_hours')}")

    status, _hdrs, _raw, resp = client._request_retry(
        "POST", COMPONENT_PATH,
        headers_extra=client._auth_headers(extra={"Referer": IUI_REFERER}), body=body,
    )
    text = resp.decode("utf-8", errors="replace")
    if "200" not in status:
        raise Exception(f"组件请求失败: {component.get('name')} {status} {text[:300]}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("[COMP] 响应非 JSON，返回原文前 500 字符供排查")
        return {"_raw": text[:500], "_status": status}


def parse_component_result(data):
    """把 data4component 响应拆成结构化摘要（任一层缺失都容错，不抛异常）。

    响应结构（实测）::

        {"err_code":0,"err_message":"Success.",
         "result":{"data":[{"series":[{"name":"Actual","gr":"5min",
                                       "data":[{"begintime","endtime","timestamp","value"}]}],
                           "begintime":"...","endtime":"...","gr":"5min"}],
                   "map":{"total":1}}}
    """
    if not isinstance(data, dict):
        return {"ok": False, "error": "响应不是对象"}

    err_code = data.get("err_code")
    err_message = data.get("err_message")
    result = data.get("result") or {}
    blocks = result.get("data") or []
    block = blocks[0] if blocks and isinstance(blocks[0], dict) else {}

    series = []
    total_points = 0
    for s in block.get("series") or []:
        if not isinstance(s, dict):
            continue
        pts = s.get("data") or []
        vals = [v for v in (_num(p.get("value")) for p in pts) if v is not None]
        total_points += len(pts)
        series.append({
            "name": s.get("name"),
            "gr": s.get("gr") or block.get("gr"),
            "points": len(pts),
            "valid_points": len(vals),
            "first_time": pts[0].get("timestamp") if pts else None,
            "last_time": pts[-1].get("timestamp") if pts else None,
            # 最后一个桶常常没走完（value=""），所以取最后一个**有效**值
            "last_value": vals[-1] if vals else None,
            "min": min(vals) if vals else None,
            "max": max(vals) if vals else None,
            "avg": (sum(vals) / len(vals)) if vals else None,
            "data": [{"time": p.get("timestamp"), "begintime": p.get("begintime"),
                      "endtime": p.get("endtime"), "value": _num(p.get("value"))}
                     for p in pts],
        })

    return {
        "ok": err_code in (0, "0", None),
        "err_code": err_code,
        "err_message": err_message,
        "gr": block.get("gr"),
        "begintime": block.get("begintime"),
        "endtime": block.get("endtime"),
        "series_count": len(series),
        "total_points": total_points,
        "series": series,
    }


def fetch_screen(client, screen_id=DEFAULT_SCREEN_ID, template_name=None,
                 components=None, last_hours=None, include_raw=False):
    """抓一个大屏子模板下的全部（或指定）组件。

    返回 {"screen_id","template","last_hours","components":{name: {...}}}；
    单组件失败只记录 error，不影响其它组件。
    include_raw=True 时额外保留服务端原始响应（便于核对）。
    """
    cfg = fetch_screen_config(client, screen_id)
    templates = parse_screen_config(cfg)
    tpl = pick_template(templates, template_name)

    want = None
    if components:
        want = {str(c) for c in components}
    picked = [c for c in tpl["components"] if want is None or str(c["name"]) in want]
    if want is not None:
        missing = want - {str(c["name"]) for c in picked}
        if missing:
            raise Exception(f"子模板 {tpl['name']} 下没有组件 {sorted(missing)}，"
                            f"可选：{[c['name'] for c in tpl['components']]}")

    out = {}
    for c in picked:
        try:
            raw = fetch_component(client, c, screen_id, last_hours)
            parsed = parse_component_result(raw)
            out[c["name"]] = {
                "name": c["name"], "class": c["class"],
                "refresh_ms": c["refresh_ms"], "position": c["position"],
                "args": c["args"], "parsed": parsed,
                **({"raw": raw} if include_raw else {}),
            }
        except Exception as e:  # noqa: BLE001
            logger.error(f"[COMP] {c['name']} failed: {e}")
            out[c["name"]] = {"name": c["name"], "class": c["class"], "error": str(e)}
        time.sleep(0.2)  # 轻微限速，避免打爆大屏后端

    return {
        "screen_id": int(screen_id),
        "template": {"name": tpl["name"], "template_name": tpl["template_name"],
                     "template_id": tpl["template_id"],
                     "param_values": tpl["param_values"],
                     "ne_options": tpl["ne_options"]},
        "last_hours": last_hours if last_hours is not None
                      else tpl["param_values"].get("lasthours"),
        "components": out,
    }


def fetch_all_templates(client, screen_id=DEFAULT_SCREEN_ID, last_hours=None):
    """抓一个大屏下**所有子模板**的全部组件，返回 {子模板名: fetch_screen 结果}。"""
    templates = parse_screen_config(fetch_screen_config(client, screen_id))
    return {t["name"]: fetch_screen(client, screen_id, template_name=t["name"],
                                    last_hours=last_hours)
            for t in templates}


# ============================================================
# 便捷入口（可被定时任务/其它模块直接调用）
# ============================================================
def fetch_screen_data(screen_id=DEFAULT_SCREEN_ID, template_name=None,
                      components=None, last_hours=None, client=None):
    """登录（或复用传入 client）后抓大屏数据，返回 fetch_screen 的结果。"""
    owns_client = client is None
    if client is None:
        user, pwd = _runtime_credentials()
        client = UMEPortalClient(username=user, password=pwd)
    if owns_client:
        client.login()
    return fetch_screen(client, screen_id, template_name, components, last_hours)


def list_screen(client, screen_id=DEFAULT_SCREEN_ID):
    """列出子模板与组件清单（不请求数据）。"""
    templates = parse_screen_config(fetch_screen_config(client, screen_id))
    return {
        "screen_id": int(screen_id),
        "templates": [{"name": t["name"], "template_name": t["template_name"],
                       "template_id": t["template_id"],
                       "param_values": t["param_values"], "ne_options": t["ne_options"],
                       "components": [{"name": c["name"], "class": c["class"],
                                       "refresh_ms": c["refresh_ms"]}
                                      for c in t["components"]]}
                      for t in templates],
    }


# ============================================================
# CLI
# ============================================================
def _fmt(v):
    return "—" if v is None else f"{v:g}"


def _component_summary(name, item):
    """单组件摘要：窗口 / 粒度 / 各 series 的点数与最后有效值。"""
    if "error" in item:
        return f"失败 -> {item['error']}"
    p = item.get("parsed") or {}
    if not p.get("ok"):
        return (f"失败 err_code={p.get('err_code')} "
                f"msg={p.get('err_message') or p.get('error')}")
    lines = [f"gr={p['gr']} {p['begintime']} ~ {p['endtime']} "
             f"series={p['series_count']} points={p['total_points']}"]
    for s in p["series"]:
        lines.append(f"  · {s['name']}: pts={s['points']}(有效 {s['valid_points']}) "
                     f"last={_fmt(s['last_value'])}@{s['last_time']} "
                     f"min={_fmt(s['min'])} max={_fmt(s['max'])} avg={_fmt(s['avg'])}")
    return "\n    ".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="UME 割接大屏(largescreen)数据抓取")
    ap.add_argument("--screen-id", type=int, default=DEFAULT_SCREEN_ID)
    ap.add_argument("--list", action="store_true", help="只列出子模板与组件清单")
    ap.add_argument("--all-templates", action="store_true", help="抓所有子模板")
    ap.add_argument("--template", help="子模板名，如 OLib_OSG_CAPs（默认第一个）")
    ap.add_argument("--component", nargs="*", help="只抓指定组件名，如 a.GS-echarts")
    ap.add_argument("--last-hours", type=int, help="覆盖时间窗小时数（服务端认数字）")
    ap.add_argument("--save", help="把结果写到该文件路径")
    ap.add_argument("--full", action="store_true", help="打印每个 series 的完整点序列")
    ap.add_argument("--points", action="store_true", help="打印原始点（配合 --full）")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    user, pwd = _runtime_credentials()
    client = UMEPortalClient(username=user, password=pwd).login()

    if args.list:
        info = list_screen(client, args.screen_id)
        print(f"\n大屏 screen_id={info['screen_id']} 共 {len(info['templates'])} 个子模板")
        for t in info["templates"]:
            print(f"\n● {t['name']}  ({t['template_name']})  template_id={t['template_id']}")
            print(f"  参数: {json.dumps(t['param_values'], ensure_ascii=False)}")
            for ne in t["ne_options"]:
                print(f"  NE  : {ne['label']} moc={ne['moc']}")
            for c in t["components"]:
                print(f"  - {c['name']:16s} {c['class']:15s} refresh={c['refresh_ms']}ms")
        if args.save:
            _save(args.save, info)
        return info

    if args.all_templates:
        results = fetch_all_templates(client, args.screen_id, args.last_hours)
        for tname, res in results.items():
            print(f"\n■ 子模板 {tname}（{len(res['components'])} 个组件，"
                  f"窗口 {res['last_hours']}h）")
            for cname, item in res["components"].items():
                print(f"  {cname}:\n    {_component_summary(cname, item)}")
                if args.full:
                    _dump_series(item, args.points)
        if args.save:
            _save(args.save, results)
        return results

    res = fetch_screen(client, args.screen_id, args.template,
                       args.component, args.last_hours)
    print(f"\n大屏 screen_id={res['screen_id']} 子模板 {res['template']['name']}"
          f"（{res['template']['template_name']}）窗口 {res['last_hours']}h，"
          f"{len(res['components'])} 个组件")
    for cname, item in res["components"].items():
        print(f"  {cname}:\n    {_component_summary(cname, item)}")
        if args.full:
            _dump_series(item, args.points)
    if args.save:
        _save(args.save, res)
    return res


def _dump_series(item, with_points=False):
    p = item.get("parsed") or {}
    for s in p.get("series") or []:
        print(f"      [{s['name']}] {s['first_time']} ~ {s['last_time']}")
        if with_points:
            for pt in s["data"]:
                print(f"        {pt['time']}  {_fmt(pt['value'])}")


def _save(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"\n[saved] {path}")


if __name__ == "__main__":
    main()
