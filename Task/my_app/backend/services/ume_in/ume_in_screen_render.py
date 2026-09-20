# -*- coding: utf-8 -*-
"""UME 割接大屏「一模一样」离线还原（ume_in）

输入：ume_in_screen_service 抓到的 **大屏配置 + 组件数据 + 背景图**，
输出：一个可离线打开的自包含页面（1920x1080 画布，按视口等比/拉伸缩放），
      与原页面 https://172.17.208.1:28808/iui/guard-imonitor-iui/#/screen/screen-view?screen_id=1
      的布局、配色、字体、图表样式一致。

还原依据（全部来自 UME 前端 bundle ``9-es2015.c1c11013f2a6a61c13df.js`` 的实测反查）：

1. 画布与定位（``app-screen-view``）::

       width_percent  = window.innerWidth  / template.width
       height_percent = window.innerHeight / template.height
       style = {top:y*height_percent, left:x*width_percent,
                width:width*width_percent, height:height*height_percent, z-index:z_index}
       .big-screen{position:relative}  .big-controls{position:absolute}

   即 X/Y **独立拉伸**（不保持宽高比），与原页面一致。

2. 字号（``setFontSize(initWidth, initHeight)``）::

       n = t > e ? e / control.width * font_size : t / control.height * font_size
       (e = initWidth, t = initHeight)

3. 组件分派：``current``/``date4other``、``label``/``latest4kpi*``、
   ``line4multi``/``line4multi2``/``line4yesterday``/``double_domain``、``png``。

4. 图表选项（``setBasicOptions`` + ``pushOption``）逐字段照搬：
   tooltip/grid(25,25)/xAxis(category, HH:mm)/yAxis(#979797, #FFFFFF)/
   legend(top,scroll,itemStyle.opacity=0)/series(line,smooth,symbolSize=2,
   lineStyle.width=2, lineStyle.type=line_type, lineStyle.color=line_color)/
   animationEasing=elasticOut。
   y 轴 min/max 与 ``niceNum`` 取整、``is_adaptive``/``is_connectNulls``/``is_percent``
   分支逻辑均按原码实现。

5. ``line4yesterday`` 的配色由前端**硬编码覆盖**为
   Actual ``#0191F2`` 实线 / Last N days ``#00E3EA`` 虚线，
   且序列名由 ``series_type`` 推导（``target`` → Actual）。

6. 背景图：``GET /largescreen/blob?_id={attributes.src}``（PNG）。
   时间元素 ``current`` 用 ``GET /largescreen/current`` 的服务器毫秒时间对齐，
   格式 ``yyyy/MM/dd HH:mm:ss``（en）/ ``yyyy年MM月dd日 HH:mm:ss``（zh），每秒自增。

用法：
    # 还原 screen_id=1 的 OLib_OSG_CAPs 子模板（抓包那一屏）
    python -m backend.services.ume_in.ume_in_screen_render \
        --screen-id 1 --template OLib_OSG_CAPs --out outputs/ume_screen_caps

    # 还原全部 4 个子模板（每屏一个 html）
    python -m backend.services.ume_in.ume_in_screen_render --screen-id 1 --all-templates

    # 覆盖时间窗（服务端认数字）
    python -m backend.services.ume_in.ume_in_screen_render --template OLib_OSG_CAPs --last-hours 12

产物：
    <out>/index.html          还原页面
    <out>/assets/*.png        背景图（bg_base / bg_box / bg_label）
    <out>/vendor/echarts.min.js
    <out>/data.json           组件原始数据快照（可复现）
"""

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time

from backend.services.ume_in.ume_in_kpi_service import UMEPortalClient, _runtime_credentials
from backend.services.ume_in.ume_in_screen_service import (
    DEFAULT_SCREEN_ID,
    IUI_REFERER,
    fetch_component,
    fetch_screen_config,
    parse_screen_config,
    pick_template,
)

logger = logging.getLogger("ume_in_screen_render")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

BLOB_PATH = os.environ.get(
    "UME_IN_SCREEN_BLOB_PATH", "/api/guard-imonitor-service/v1/largescreen/blob"
)
CURRENT_PATH = os.environ.get(
    "UME_IN_SCREEN_CURRENT_PATH", "/api/guard-imonitor-service/v1/largescreen/current"
)

DEFAULT_OUT = os.environ.get("UME_IN_SCREEN_OUT", "outputs/ume_screen")

# 项目自带 echarts（离线可用，不依赖外网 CDN）
ECHARTS_CANDIDATES = [
    os.environ.get("UME_IN_ECHARTS", ""),
    "frontend/node_modules/echarts/dist/echarts.min.js",
]

# 需要渲染的元素 class
RENDERABLE = {"png", "label", "current", "line4multi", "line4multi2",
              "line4yesterday", "double_domain"}


# ============================================================
# 抓取：配置 + 数据 + 背景图 + 服务器时间
# ============================================================
def fetch_blob(client, src):
    """GET /largescreen/blob?_id={src}，返回 (文件名, bytes)。"""
    path = f"{BLOB_PATH}?_id={src}"
    status, hdrs, _raw, resp = client._request_retry(
        "GET", path, headers_extra=client._auth_headers(extra={"Referer": IUI_REFERER})
    )
    if "200" not in status:
        raise Exception(f"背景图失败: src={src} {status} {resp[:120]!r}")
    cd = hdrs.get("content-disposition", "") or ""
    m = re.search(r"filename=([^;]+)", cd)
    name = m.group(1).strip().strip('"') if m else f"blob_{src}.png"
    name = re.sub(r"[^A-Za-z0-9_.\-]", "_", name) or f"blob_{src}.png"
    return name, resp


def fetch_server_now(client):
    """GET /largescreen/current → 服务器毫秒时间戳（current 元素用它对齐）。"""
    try:
        status, _h, _r, resp = client._request_retry(
            "GET", CURRENT_PATH,
            headers_extra=client._auth_headers(extra={"Referer": IUI_REFERER}))
        data = json.loads(resp.decode("utf-8", errors="replace"))
        arr = (data.get("result") or {}).get("data") or []
        return int(arr[0]) if arr else None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[RENDER] /largescreen/current 取不到（{e}），改用本地时间")
        return None


def fetch_layout(client, screen_id=DEFAULT_SCREEN_ID, template_name=None):
    """只抓「布局」：画布尺寸 + 全部元素 + 大屏参数 + 背景图。

    背景图直接返回 bytes（路由层再决定是落盘还是直接吐给浏览器）。
    """
    templates = parse_screen_config(fetch_screen_config(client, screen_id))
    tpl = pick_template(templates, template_name)
    elements = [e for e in tpl["elements"] if e.get("class") in RENDERABLE]

    assets = {}
    src_ids = sorted({(e.get("attributes") or {}).get("src")
                      for e in elements if e.get("class") == "png"})
    for src in src_ids:
        if src is None:
            continue
        try:
            name, blob = fetch_blob(client, src)
            assets[str(src)] = {"file": name, "bytes": blob}
        except Exception as e:  # noqa: BLE001
            logger.error(f"[RENDER] 背景图 src={src} 失败: {e}")

    return {
        "screen_id": int(screen_id),
        "template": {"name": tpl["name"], "template_name": tpl["template_name"],
                     "template_id": tpl["template_id"]},
        "width": tpl["width"] or 1920,
        "height": tpl["height"] or 1080,
        "params": tpl["param_values"],
        "elements": elements,
        "assets": assets,
    }


def fetch_data(client, screen_id=DEFAULT_SCREEN_ID, template_name=None, last_hours=None,
               components=None):
    """只抓「数据」：各组件 originData（data4component 的 result.data[0]）。

    组件并行抓取——单个约 1.3s，10 个串行要 13s，并行后 ~2s，实时刷新才可用。
    """
    from concurrent.futures import ThreadPoolExecutor

    templates = parse_screen_config(fetch_screen_config(client, screen_id))
    tpl = pick_template(templates, template_name)
    picked = [c for c in tpl["components"]
              if not components or str(c["name"]) in {str(x) for x in components}]

    def one(comp):
        try:
            raw = fetch_component(client, comp, screen_id, last_hours)
            blocks = (raw.get("result") or {}).get("data") or []
            return comp["name"], (blocks[0] if blocks else None), None
        except Exception as e:  # noqa: BLE001
            logger.error(f"[RENDER] {comp['name']} 取数失败: {e}")
            return comp["name"], None, str(e)

    data, errors = {}, {}
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(picked)))) as ex:
        for name, val, err in ex.map(one, picked):
            if err:
                errors[name] = err
            data[name] = val

    return {
        "screen_id": int(screen_id),
        "template": tpl["name"],
        "data": data,
        "errors": errors,
        "server_now": fetch_server_now(client),
        "last_hours": last_hours if last_hours is not None
                      else tpl["param_values"].get("lasthours"),
    }


def fetch_bundle(client, screen_id=DEFAULT_SCREEN_ID, template_name=None, last_hours=None):
    """抓一个子模板的完整还原素材（布局 + 数据），供离线落盘使用。"""
    layout = fetch_layout(client, screen_id, template_name)
    logger.info(f"[RENDER] 子模板 {layout['template']['name']} "
                f"({layout['template']['template_name']}) "
                f"{layout['width']}x{layout['height']}，{len(layout['elements'])} 个元素")

    d = fetch_data(client, screen_id, layout["template"]["name"], last_hours)
    for name, err in d["errors"].items():
        logger.error(f"[RENDER] {name}: {err}")

    return {
        "screen_id": layout["screen_id"],
        "template": layout["template"],
        "width": layout["width"],
        "height": layout["height"],
        "params": layout["params"],
        "elements": layout["elements"],
        "data": d["data"],
        "assets": layout["assets"],
        "server_now": d["server_now"],
        "last_hours": d["last_hours"],
    }


# ============================================================
# 渲染：HTML + JS（逐条对应原前端逻辑）
# ============================================================
_PAGE_CSS = """
  html, body { margin:0; padding:0; width:100%; height:100%; overflow:hidden; background:#000; }
  .big-screen { position:relative; background:#000; overflow:hidden; }
  .big-controls { position:absolute; }
  .ctrl-img { display:block; }
  .ctrl-label { white-space:nowrap; display:flex; overflow:hidden;
                font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
                            "Helvetica Neue",Arial,"Noto Sans",sans-serif,
                            "Apple Color Emoji","Segoe UI Emoji"; }
  .ctrl-chart { display:block; }
  .echart { width:100%; height:100%; }
  .live-status { position:fixed; right:6px; bottom:4px; z-index:99999;
                 font:12px/1.6 -apple-system,"Segoe UI",Arial,sans-serif;
                 color:#7f8ea3; background:rgba(0,0,0,.35); padding:1px 8px;
                 border-radius:9px; pointer-events:none; }
  .live-status.ok { color:#5fd0a0; }
  .live-status.err { color:#ff7b7b; }
"""

_PAGE_JS = r"""
// ============ 大屏还原引擎（离线快照 / 实时拉取共用同一套渲染逻辑） ============
const CHART_CLASSES = ["line4multi", "line4multi2", "line4yesterday", "double_domain"];
let SCREEN = null, DATA = {}, ASSETS = {}, PARAMS = {}, LANG = "en";
let SERVER_NOW = null, clockOffset = 0, REFRESH_MS = 0, pullAndApply = null;
const charts = {};

// ---------- 工具（对应原 bundle 里的同名逻辑） ----------
function tsMs(s) {                      // "YYYY-MM-DD HH:mm:ss" → 本地毫秒
  if (s == null) return null;
  if (typeof s === "number") return s;
  const m = String(s).match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/);
  if (!m) return new Date(s).getTime();
  return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime();
}
function pad(n) { return n < 10 ? "0" + n : "" + n; }
function fmtDate(ms, f) {               // 支持 yyyy/MM/dd HH:mm:ss 与 yyyy年MM月dd日 HH:mm:ss
  const d = new Date(ms);
  return f.replace("yyyy", d.getFullYear()).replace("MM", pad(d.getMonth() + 1))
          .replace("dd", pad(d.getDate())).replace("HH", pad(d.getHours()))
          .replace("mm", pad(d.getMinutes())).replace("ss", pad(d.getSeconds()));
}
function fmtHHmm(ms) { const d = new Date(ms); return pad(d.getHours()) + ":" + pad(d.getMinutes()); }
function flag(v) { v = v == null ? "" : v.toString();
  return !!(v && v !== "false" && v !== "0" && (v === "true" || v === "1")); }
function getGr(g) {                     // 原码：只认 1min/5min/15min/60min，其余 0→15
  switch (g) { case "1min": return 1; case "5min": return 5;
               case "15min": return 15; case "60min": return 60; default: return 0; }
}
function niceNum(e) {                   // 原码：y 轴 min 取整
  if (e < 10) return 0;
  const t = Math.floor(Math.log10(e)) + 1, n = Math.pow(10, t - 1);
  return Math.floor(e / n) * n;
}
function subst(t) {                     // $title$ / $lasthours$ 等大屏参数替换
  if (t == null) return "";
  return String(t).replace(/\$([A-Za-z0-9_]+)\$/g, (m, k) => (k in PARAMS ? PARAMS[k] : m));
}
function daysName(n) {                  // 原码 getDaysName
  if (LANG === "zh-CN") return "最近" + n + "天";
  return n === 1 ? "The nearest day" : "Last " + n + " days";
}
function seriesNameFor(el, s) {         // 原码 getSeriesName（仅 line4yesterday 用）
  if (el.class !== "line4yesterday") return s.name;
  if (s.series_type === "target") return LANG === "zh-CN" ? "实际" : "Actual";
  const n = el.args ? el.args.days_ago : null;
  return (n !== undefined && n !== 0 && n !== null) ? daysName(n)
         : (LANG === "zh-CN" ? "最近1天" : "The nearest day");
}
function timeAxis(grMin, startMs, endMs) {   // 原码 Object(I.g)([], gr, start, end)
  const step = grMin * 60000, out = [];
  if (startMs == null || endMs == null) return out;
  for (let t = startMs; t <= endMs + 1; t += step) out.push(t);
  return out;
}

// ---------- 图表选项（原码 setBasicOptions + pushOption 逐字段对应） ----------
function buildOptions(el) {
  const od = DATA[el.name];
  if (!od) return null;
  const attrs = el.attributes || {};
  const isAdaptive = flag(od.is_adaptive), isConnectNulls = flag(od.is_connectNulls);
  const startMs = tsMs(od.begintime), endMs = tsMs(od.endtime);

  let grMin = getGr(od.gr); if (grMin === 0) grMin = 15;
  const grs = (od.series || []).filter(s => s.gr).map(s => getGr(s.gr)).filter(v => v > 0);
  if (grs.length) { const m = Math.min.apply(null, grs); if (m <= grMin) grMin = m; }
  const axis = timeAxis(grMin, startMs, endMs);

  const opts = {
    tooltip: { trigger: "axis",
               axisPointer: { type: "line", lineStyle: { color: "rgba(128, 128, 128, 0.5)" } },
               confine: true, backgroundColor: "rgba(33,66,121,.8)",
               borderColor: "rgba(33,66,121,.8)", textStyle: { color: "#fff" } },
    grid: { bottom: "3%", top: "20%", left: "25", right: "25", containLabel: true },
    xAxis: { type: "category", boundaryGap: false, data: axis.map(String),
             min: String(startMs), max: String(endMs),
             axisLine: { onZero: false, lineStyle: { color: "#979797" } },
             axisLabel: { color: "#FFFFFF", fontWeight: "normal",
                          formatter: v => fmtHHmm(parseInt(v, 10)), showMaxLabel: true },
             axisPointer: { label: { formatter: p => fmtDate(parseInt(p.value, 10), "yyyy-MM-dd HH:mm") } } },
    yAxis: [{ splitLine: { show: false },
              axisLine: { lineStyle: { color: "#979797" } },
              axisLabel: { formatter: (attrs.left_yAxis && attrs.left_yAxis.is_percent) ? "{value}%" : "{value}",
                           color: "#FFFFFF", fontWeight: "normal", showMaxLabel: true },
              axisTick: { show: false } }],
    series: [], color: [], animationEasing: "elasticOut",
    animationDelayUpdate: i => 5 * i
  };

  // legend
  const legend = { top: "0%", padding: [15, 15], textStyle: { color: "#FFFFFF" },
                   type: "scroll", pageIconColor: "#aaa", pageIconInactiveColor: "#2f4554",
                   pageTextStyle: { color: "#999999" }, itemStyle: { opacity: 0 },
                   lineStyle: { width: 1.5 }, data: [], width: "70%" };
  legend.show = !attrs.legend || !!(attrs.legend && attrs.legend.is_show);
  if (attrs.legend && attrs.legend.is_show) {
    legend.top = attrs.legend.vertical_position || "top";
    if (legend.top === "bottom") { opts.grid.bottom = "12%"; legend.padding = 5; }
    legend.left = attrs.legend.horizontal_position || "center";
    legend.width = attrs.legend.width || "70%";
  } else if (el.class === "line4yesterday") { legend.right = "5%"; }
  opts.legend = legend;

  if (el.is_percent) opts.yAxis.forEach(a => { a.min = 0; a.max = 100; });
  opts.yAxis.push({ splitLine: { show: false },
                    axisLine: { lineStyle: { color: "#979797" } },
                    axisLabel: { formatter: (attrs.right_yAxis && attrs.right_yAxis.is_percent) ? "{value} %" : "{value}",
                                 color: "#FFFFFF", fontWeight: "normal" },
                    axisTick: { show: false } });

  // series 配色：line4yesterday 由前端硬编码覆盖
  let seriesAttr = attrs.series;
  if (typeof seriesAttr === "string") { try { seriesAttr = JSON.parse(seriesAttr); } catch (e) { seriesAttr = []; } }
  if (el.class === "line4yesterday") {
    seriesAttr = [{ name: LANG === "zh-CN" ? "实际" : "Actual", line_type: "solid", line_color: "#0191F2" },
                  { name: daysName(el.args ? el.args.days_ago : null), line_type: "dashed", line_color: "#00E3EA" }];
  }
  seriesAttr = seriesAttr || [];

  (od.series || []).forEach(s => {
    const name0 = seriesNameFor(el, s);
    const cfg = seriesAttr.find(x => x.name === name0);
    if (!cfg) return;                       // 原码：只渲染 attributes.series 里匹配得上的

    const idx = cfg.yAxis ? (cfg.yAxis === "left" ? 0 : 1) : 0;
    let isPct = false;                      // 原码里的 s：该轴是否按百分比
    if (idx === 0) {
      if (attrs.left_yAxis && !attrs.left_yAxis.turn_on) return;
      isPct = !!(attrs.left_yAxis && attrs.left_yAxis.is_percent);
    } else {
      if (attrs.right_yAxis && !attrs.right_yAxis.turn_on) return;
      isPct = !!(attrs.right_yAxis && attrs.right_yAxis.is_percent);
    }

    let c = cfg.name;
    const same = opts.series.map(x => x.name).filter(n => n === c);
    if (same.length > 1) c = c + "(" + (same.length - 1) + ")";

    const pts = (s.data || []).map(p => {
      let v = p.value;
      v = (v === null || v === undefined || v === "null" || v === "NaN" || v === "") ? "" : Number(Number(v).toFixed(2));
      return { time: tsMs(p.timestamp), value: v };
    });

    if (pts.length <= 0) {                  // 原码：无数据也占位，保证图例存在
      opts.legend.data.push({ name: c });
      opts.series.push({ id: opts.series.length + 1, name: c, type: "line", smooth: true,
                         data: [], lineStyle: { width: 2, type: cfg.line_type, color: cfg.line_color } });
      return;
    }

    if (!el.is_percent) {                   // y 轴 min/max（原码顺序敏感）
      const vals = pts.filter(p => p.value !== null && p.value !== "").map(p => p.value)
                      .sort((a, b) => a - b);
      const mn = vals.length ? vals[0] : 0, mx = vals.length ? vals[vals.length - 1] : 0;
      const cur = opts.yAxis[idx];
      cur.min = (cur.min || cur.min === 0) && cur.min <= Math.floor(mn) ? cur.min : Math.floor(mn);
      cur.max = (cur.max || cur.max === 0) && cur.max >= Math.ceil(mx) ? cur.max : Math.ceil(mx);
      cur.min = niceNum(Math.floor(0.9 * cur.min));
      if (!isAdaptive) cur.min = cur.min < 0 ? cur.min : 0;
    }

    opts.legend.data.push({ name: c });
    const ser = {
      id: opts.series.length + 1, name: c, type: "line", smooth: true,
      data: pts.map(p => ({ name: String(p.time), value: [String(p.time), p.value],
                            itemStyle: { color: cfg.line_color }, line_type: cfg.line_type })),
      symbol: cfg.line_type === "dashed" ? "circle" : "emptyCircle",
      showAllSymbol: true, symbolSize: 2,
      lineStyle: { width: 2, type: cfg.line_type, color: cfg.line_color },
      tooltip: { show: true }, yAxisIndex: idx, connectNulls: false
    };
    if (isConnectNulls) ser.connectNulls = true;

    // line4yesterday 的 target 序列：最后一个有效点上打 markPoint 徽标（原码照搬）
    if (el.class === "line4yesterday" && s.series_type === "target") {
      const valid = pts.filter(p => p.value !== null && p.value !== "");
      if (valid.length) {
        const last = valid[valid.length - 1];
        const at = pts.findIndex(p => p.time === last.time);
        ser.markPoint = {
          symbolSize: [64, 45], symbolKeepAspect: true,
          data: [{ value: isPct ? last.value + "%" : last.value, xAxis: at, yAxis: last.value }],
          label: { fontWeight: "normal", color: "#fff" },
          itemStyle: { color: cfg.line_color },
          animation: true, animationEasingUpdate: "cubicInOut"
        };
      }
    }
    opts.series.push(ser);
    opts.color.push(cfg.line_color);
  });

  // tooltip：原码自定义 formatter（虚线用空心圆点，实线用默认 marker）
  if (opts.series.length) {
    opts.tooltip.formatter = function (params) {
      let out = params[0].axisValueLabel + " <br />";
      params.forEach(p => {
        out += '<div><div style="margin: 0 8px;">'
             + (p.data.line_type === "dashed"
                ? '<div style="display:inline-block;border-radius:50%;margin-right:3px;'
                  + 'width:10px;height:10px;border:2px solid ' + p.color
                  + ';background:rgba(33,66,121,.8);"></div>'
                : p.marker)
             + '<span>' + p.seriesName + '</span>'
             + '<span style="float:right;margin-left:20px;font-weight:bold;">'
             + p.value[1] + '</span></div></div>';
      });
      return out;
    };
  }

  return opts;
}

// ---------- DOM ----------
const screenEl = document.getElementById("bigScreen");

function buildDom() {
  SCREEN.elements.forEach(el => {
    let node = null;
    const a = el.attributes || {};
    if (el.class === "png") {
      node = document.createElement("img");
      node.className = "ctrl-img";
      node.src = assetUrl(a.src);
      node.alt = el.name;
    } else if (el.class === "label") {
      node = document.createElement("div");
      node.className = "ctrl-label";
      node.textContent = (a.prefix || "") + subst(a.text) + (a.suffix || "");
      node.style.color = a.font_color || "#FFFFFF";
      node.style.justifyContent = a.align === "left" ? "flex-start"
                                : a.align === "right" ? "flex-end" : "center";
      node.style.alignItems = a.vertical_align === "top" ? "flex-start"
                             : a.vertical_align === "bottom" ? "flex-end" : "center";
      node.dataset.fs = a.font_size || "14";
    } else if (el.class === "current") {
      node = document.createElement("div");
      node.className = "ctrl-label ctrl-current";
      node.style.color = a.font_color || "#FFFFFF";
      node.style.justifyContent = a.align === "left" ? "flex-start"
                                : a.align === "right" ? "flex-end" : "center";
      node.style.alignItems = "center";
      node.dataset.fs = a.font_size || "24";
    } else if (CHART_CLASSES.indexOf(el.class) >= 0) {
      node = document.createElement("div");
      node.className = "ctrl-chart";
      const inner = document.createElement("div");
      inner.className = "echart";
      inner.id = "echart_" + el.name;
      node.appendChild(inner);
    } else { return; }

    node.classList.add("big-controls");
    node.dataset.el = el.name;
    screenEl.appendChild(node);
    el._node = node;
  });
}

function layout() {
  const wPct = window.innerWidth / SCREEN.width;
  const hPct = window.innerHeight / SCREEN.height;
  screenEl.style.width = window.innerWidth + "px";
  screenEl.style.height = window.innerHeight + "px";

  SCREEN.elements.forEach(el => {
    const n = el._node; if (!n) return;
    const w = el.width * wPct, h = el.height * hPct;
    n.style.top = (el.y * hPct) + "px";
    n.style.left = (el.x * wPct) + "px";
    n.style.width = w + "px";
    n.style.height = h + "px";
    n.style.zIndex = el.z_index;
    if (n.dataset.fs) {                    // 原码 setFontSize(initWidth, initHeight)
      const fs = parseFloat(n.dataset.fs), e = w, t = h;
      const size = (t > e) ? (e / el.width * fs) : (t / el.height * fs);
      n.style.fontSize = size + "px";
    }
    const ch = charts[el.name];
    if (ch) { ch.resize(); }
  });
}

function renderCharts() {
  SCREEN.elements.forEach(el => {
    if (CHART_CLASSES.indexOf(el.class) < 0) return;
    const dom = document.getElementById("echart_" + el.name);
    if (!dom) return;
    const opts = buildOptions(el);
    if (!opts) return;
    const chart = charts[el.name] || echarts.init(dom);
    chart.clear();                         // 原码：myChart.clear(); setOption(options)
    chart.setOption(opts);
    charts[el.name] = chart;
  });
}

// ---------- 时间元素（原码 current：与服务器时间对齐，每秒自增） ----------
function startClock() {
  const nodes = SCREEN.elements.filter(e => e.class === "current");
  if (!nodes.length) return;
  const fmt = LANG === "zh-CN" ? "yyyy年MM月dd日 HH:mm:ss" : "yyyy/MM/dd HH:mm:ss";
  const tick = () => {
    const txt = fmtDate(Date.now() + clockOffset + 1000, fmt);
    nodes.forEach(e => { if (e._node) e._node.textContent = txt; });
  };
  tick();
  setInterval(tick, 1000);
}

// ================= 引擎 API =================
function assetUrl(src) {
  const a = ASSETS[String(src)];
  return a ? (a.url || ("assets/" + a.file)) : "";
}

function applyBundle(b) {
  if (b.lang) LANG = b.lang;
  if (b.screen) SCREEN = b.screen;
  if (b.assets) ASSETS = b.assets;
  if (b.params) PARAMS = b.params;
  if (b.data) DATA = b.data;
  if (b.server_now != null) { SERVER_NOW = b.server_now; clockOffset = SERVER_NOW - Date.now(); }
  if (b.refresh_ms) REFRESH_MS = b.refresh_ms;
}

function rebuild() {                       // 重建 DOM（布局/元素变化时用）
  Object.keys(charts).forEach(k => { try { charts[k].dispose(); } catch (e) {} delete charts[k]; });
  screenEl.innerHTML = "";
  SCREEN.elements.forEach(e => { delete e._node; });
  buildDom();
  layout();                                // 先定位/定尺寸，再 init 图表，避免 0x0
  renderCharts();
}

function setData(data, serverNow) {        // 只换数据，原地刷新图表（实时轮询用）
  DATA = data || {};
  if (serverNow != null) { SERVER_NOW = serverNow; clockOffset = SERVER_NOW - Date.now(); }
  renderCharts();
}

// 调试/排障出口（控制台可用 __SCREEN_DEBUG__.refreshCount 看刷新了几次）
let refreshCount = 0, lastError = null;
window.__SCREEN_DEBUG__ = {
  get refreshCount() { return refreshCount; },
  get lastError() { return lastError; },
  get data() { return DATA; },
  get screen() { return SCREEN; },
  get params() { return PARAMS; },
  charts: charts,
  refresh: () => (LIVE ? pullAndApply(true) : null)
};

// ================= 入口 =================
const LIVE = window.__LIVE__ || null;

async function pullOnce(url) {
  const r = await fetch(url + (url.indexOf("?") >= 0 ? "&" : "?") + "_=" + Date.now(),
                        { cache: "no-store" });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return await r.json();
}

function setStatus(text, cls) {
  const el = document.getElementById("liveStatus");
  if (!el) return;
  el.textContent = text;
  el.className = "live-status " + (cls || "");
}

function bootLive(cfg) {
  const qs = cfg.query || "";

  pullAndApply = async (first) => {
    try {
      const d = await pullOnce(cfg.data + qs);
      if (d.error) throw new Error(d.error);
      setData(d.data, d.server_now);
      if (first) startClock();
      refreshCount++; lastError = null;
      setStatus("更新于 " + fmtDate(Date.now(), "HH:mm:ss")
                + " · 窗口 " + (d.last_hours != null ? d.last_hours + "h" : "-")
                + (d.cached ? " · 缓存" : "") + " · 第 " + refreshCount + " 次", "ok");
    } catch (e) {
      lastError = e.message;
      setStatus("取数失败：" + e.message + "（将重试）", "err");
    }
  };

  (async () => {
    try {
      applyBundle(await pullOnce(cfg.layout + qs));
      rebuild();
      await pullAndApply(true);
    } catch (e) {
      lastError = e.message;
      setStatus("布局加载失败：" + e.message, "err");
      return;
    }
    const ms = Math.max(15000, cfg.intervalMs || REFRESH_MS || 180000);
    setInterval(() => pullAndApply(false), ms);
  })();
}

if (LIVE) {
  bootLive(LIVE);
} else {
  applyBundle(window.__BUNDLE__ || {});
  rebuild();
  startClock();
}
window.addEventListener("resize", layout);
"""


def _json_for_script(obj):
    """把对象塞进 <script>：转义 </script 与行分隔符。"""
    return (json.dumps(obj, ensure_ascii=False)
            .replace("</", "<\\/")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def layout_payload(bundle):
    """抽出「布局」部分（元素/参数/资源/画布尺寸），实时模式首次加载用。"""
    elements = []
    for e in bundle["elements"]:
        elements.append({k: e.get(k) for k in
                         ("name", "class", "x", "y", "width", "height", "z_index",
                          "attributes", "args", "refresh_ms")})
    return {
        "screen": {"width": bundle["width"], "height": bundle["height"],
                   "elements": elements},
        # 只留可序列化的字段（fetch_bundle 里的 bytes 是给离线落盘用的）
        "assets": {k: {kk: vv for kk, vv in (v or {}).items() if kk != "bytes"}
                   for k, v in (bundle.get("assets") or {}).items()},
        "params": bundle.get("params") or {},
        "refresh_ms": _refresh_ms(elements),
        "lang": None,          # 由页面决定，避免服务端覆盖
    }


def _refresh_ms(elements):
    """取数据组件的刷新间隔（原页面每个组件都带 refresh_ms，实测 180000）。"""
    vals = [int(e.get("refresh_ms") or 0) for e in elements
            if e.get("class") in ("line4multi", "line4multi2", "line4yesterday",
                                  "double_domain", "label")]
    vals = [v for v in vals if v > 0]
    return min(vals) if vals else 180000


def render_html(bundle, lang="en"):
    """生成**离线快照**页面（数据内嵌，不联网）。"""
    payload = layout_payload(bundle)
    payload["lang"] = lang
    payload["data"] = bundle["data"]
    payload["server_now"] = bundle["server_now"]

    title = (bundle["template"].get("template_name")
             or bundle["template"].get("name") or "UME Screen")
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{_PAGE_CSS}</style>
</head>
<body>
<div class="big-screen" id="bigScreen"></div>
<script src="vendor/echarts.min.js"></script>
<script>window.__BUNDLE__ = {_json_for_script(payload)};</script>
<script>{_PAGE_JS}</script>
</body>
</html>
"""


def render_live_html(screen_id=DEFAULT_SCREEN_ID, template_name=None, lang="en",
                     api_base="/api/ume-in/screen", last_hours=None, interval_ms=None,
                     echarts_url=None):
    """生成**实时**页面：数据从本机后端代理拉取，按 refresh_ms 自动刷新。

    页面本身不含任何 UME 凭据——鉴权全在后端（``routers/ume_in_screen.py``），
    所以任意时刻打开、或长时间挂着，看到的都是 UME 当前值。
    """
    qs = [f"screen_id={int(screen_id)}"]
    if template_name:
        qs.append("template=" + str(template_name))
    if last_hours is not None:
        qs.append("last_hours=" + str(int(last_hours)))
    query = "?" + "&".join(qs)

    live = {
        "layout": f"{api_base}/layout",
        "data": f"{api_base}/data",
        "query": query,
        "intervalMs": interval_ms or 0,
    }
    ech = echarts_url or f"{api_base}/vendor/echarts.min.js"
    title = f"UME Screen {screen_id}" + (f" · {template_name}" if template_name else "")
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{_PAGE_CSS}</style>
</head>
<body>
<div class="big-screen" id="bigScreen"></div>
<div class="live-status" id="liveStatus">连接中…</div>
<script src="{ech}"></script>
<script>window.__LIVE__ = {_json_for_script(live)};</script>
<script>{_PAGE_JS}</script>
</body>
</html>
"""


# ============================================================
# 落盘
# ============================================================
def _find_echarts():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    for c in ECHARTS_CANDIDATES:
        if not c:
            continue
        p = c if os.path.isabs(c) else os.path.join(root, c)
        if os.path.exists(p):
            return p
    return None


def write_replica(bundle, outdir, lang="en", echarts_src=None):
    """把 bundle 写成可离线打开的页面，返回产物路径 dict。"""
    os.makedirs(outdir, exist_ok=True)
    assets_dir = os.path.join(outdir, "assets")
    vendor_dir = os.path.join(outdir, "vendor")
    os.makedirs(assets_dir, exist_ok=True)
    os.makedirs(vendor_dir, exist_ok=True)

    for src, a in (bundle["assets"] or {}).items():
        with open(os.path.join(assets_dir, a["file"]), "wb") as f:
            f.write(a["bytes"])

    ech = echarts_src or _find_echarts()
    if ech and os.path.exists(ech):
        shutil.copyfile(ech, os.path.join(vendor_dir, "echarts.min.js"))
        logger.info(f"[RENDER] echarts <- {ech}")
    else:
        logger.warning("[RENDER] 未找到本地 echarts，页面将引用 CDN；离线环境请手动放入 vendor/echarts.min.js")

    html_path = os.path.join(outdir, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_html(bundle, lang=lang))

    data_path = os.path.join(outdir, "data.json")
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump({"screen_id": bundle["screen_id"], "template": bundle["template"],
                   "width": bundle["width"], "height": bundle["height"],
                   "params": bundle["params"], "last_hours": bundle["last_hours"],
                   "server_now": bundle["server_now"], "data": bundle["data"]},
                  f, ensure_ascii=False, indent=2)

    return {"html": html_path, "data": data_path, "assets": assets_dir,
            "vendor": os.path.join(vendor_dir, "echarts.min.js")}


def build_replica(screen_id=DEFAULT_SCREEN_ID, template_name=None, last_hours=None,
                  outdir=DEFAULT_OUT, lang="en", client=None):
    """登录（或复用 client）→ 抓素材 → 落盘还原页面。返回产物路径 dict。"""
    owns = client is None
    if client is None:
        user, pwd = _runtime_credentials()
        client = UMEPortalClient(username=user, password=pwd)
    if owns:
        client.login()
    bundle = fetch_bundle(client, screen_id, template_name, last_hours)
    return write_replica(bundle, outdir, lang=lang)


def build_all_templates(screen_id=DEFAULT_SCREEN_ID, last_hours=None, outdir=DEFAULT_OUT,
                        lang="en", client=None):
    """还原一个大屏下所有子模板，每个子模板一个子目录。"""
    owns = client is None
    if client is None:
        user, pwd = _runtime_credentials()
        client = UMEPortalClient(username=user, password=pwd)
    if owns:
        client.login()
    templates = parse_screen_config(fetch_screen_config(client, screen_id))
    out = {}
    for t in templates:
        sub = os.path.join(outdir, str(t["name"]))
        bundle = fetch_bundle(client, screen_id, t["name"], last_hours)
        out[t["name"]] = write_replica(bundle, sub, lang=lang)
    return out


# ============================================================
# CLI
# ============================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="UME 割接大屏离线还原（一模一样页面）")
    ap.add_argument("--screen-id", type=int, default=DEFAULT_SCREEN_ID)
    ap.add_argument("--template", help="子模板名，如 OLib_OSG_CAPs")
    ap.add_argument("--all-templates", action="store_true", help="还原全部子模板")
    ap.add_argument("--last-hours", type=int, help="覆盖时间窗小时数")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"输出目录（默认 {DEFAULT_OUT}）")
    ap.add_argument("--lang", default="en", choices=["en", "zh-CN"], help="界面语言")
    ap.add_argument("--echarts", help="自定义 echarts.min.js 路径")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    user, pwd = _runtime_credentials()
    client = UMEPortalClient(username=user, password=pwd).login()

    if args.all_templates:
        results = build_all_templates(args.screen_id, args.last_hours, args.out,
                                      args.lang, client)
        print(f"\n还原完成，共 {len(results)} 个子模板：")
        for name, paths in results.items():
            print(f"  · {name}: {paths['html']}")
        return results

    paths = build_replica(args.screen_id, args.template, args.last_hours,
                          args.out, args.lang, client)
    print(f"\n还原完成：\n  HTML  : {paths['html']}\n  数据  : {paths['data']}\n"
          f"  图片  : {paths['assets']}\n  echarts: {paths['vendor']}")
    return paths


if __name__ == "__main__":
    main()
