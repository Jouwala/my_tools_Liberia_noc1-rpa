#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vmax_flow_from_xdr.py —— 用 Talon XDR 用户面数据生成「按分类流量」
=============================================================================

## 为什么不用 CCA 的 query_flow

CCA「流量信息」（`vmax_cca_client.query_flow`）走的是 DPI 应用识别，
**实测绝大多数用户查不到**（`total_flux="--"`、`app_flux="[]"`）——
CCA 网页同样为空。这是采集侧的问题，不是查询侧的问题。

Talon XDR 的**用户面（User Plane）** XDR 则是另一条链路：
`fact_5gsa_psup_flow` 每条记录就是一段用户面话单，带

    service            业务大类（Web Browse / Video / Social / IM / …）
    subservice         子业务（YOUTUBEWEB / FACEBOOK / whatsapp / …）
    app_content_name   应用内容名（WHATSAPP_FILETRANSFER / …）
    ul_traffic/dl_traffic   上下行流量（KB）
    ul_pkt/dl_pkt           上下行包数
    tcp_resp_delay / tcp_ack_delay / ul_avg_rtt / dl_avg_rtt
    ul_retrans_pkt / dl_retrans_pkt / ul_disorder_pkt / dl_disorder_pkt
    ul_throughput_max / dl_throughput_max

这些字段足以算出「总流量 / 各应用流量 / TCP 指标 / 控制面指标」，
因此本模块用 XDR 用户面数据**自己算**出与参考面板同构的分类结果。

## 分类口径（2026-10-30 实测还原）

上游 `service` 的取值域（实测 1558 条样本，10 类）：

    Web Browse / Video / Social / IM / Shopping / eMail
    Network Storage / Public Traffic / Comm Traffic / Others

映射到面板页签（参考图的两级结构）：

    数据 | 语音                ← 一级
    流量 | 视频 | 网页 | 游戏 | OTT语音 | OTT视频 | TCP指标 | 控制面   ← 二级

- **视频 / 网页 / OTT语音 / OTT视频**：由 `service` 直接判定
  （Video / Web Browse / VoIP / OTT*）。
- **游戏**：`service` 里没有 Game 类，只能靠 `subservice`/`app_content_name`
  识别已知的游戏应用名（实测样本未命中，属正常）。
- **流量 / TCP指标 / 控制面**：不是应用分类，而是**指标口径**，
  由全部记录聚合而来（见 `aggregate_categories`）。

## 上游数据的三条硬约束（都踩过）

1. **窗口结束时刻不能落在 45 分整**：实测 `end=17:44` → 785 条，
   `end=17:45` → **0 条**，`end=17:46` → 785 条。上游按分区切，
   某些分区边界会整个查不到。取数时**把 end 往后挪 1 分钟**避开刻钟边界。
2. **`type="1"` 才是号码过滤类型**：页面组件用 `6`（SELECT_INPUT），
   上游既不报错也不过滤 —— 会把整窗别人的详单当成结果返回（越权风险）。
3. **5gsa 域只收 5G/4G-EUTRAN 用户面**：LTE 终端（`rat_name=(4G)EUTRAN`）
   在 `fact_5gsa_psup_flow` 里**有**数据（实测 `(4G)EUTRAN` 的 S1-U 记录）；
   但 RAN 域（32）只带 IMSI、不带 MSISDN，按号码查必然为空。

## 会话纪律

本模块**复用** `VmaxXdrClient`（它复用 CCA 的门户会话，不自行登录）。
上游按用户限并发，多进程各自登录会触发
"The maximum number of connections for the user is reached"（README 已记）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 页签口径
# ---------------------------------------------------------------------------
# 一级页签：数据 | 语音
FLOW_SVC_DATA = "data"
FLOW_SVC_VOICE = "voice"

# 二级页签 key（顺序即面板顺序）
CATEGORY_KEYS = [
    "all", "video", "web", "game", "ottvoice", "ottvideo", "tcp", "control",
]

# 上游 service（业务大类）-> 页签 key
#
# ⚠ 上游的 service 是**DPI 业务大类**，与面板的页签不是一一对应：
# 实测 1558 条样本的 service 取值有 10 类
#   Web Browse / Video / Social / IM / Shopping / eMail
#   Network Storage / Public Traffic / Comm Traffic / Others
# 其中只有 Video 与 Web Browse 能直接对上页签；Social / IM / Shopping / eMail
# 是**应用类业务**，面板里没有对应页签，落到「流量」页签的应用列表里
# （面板的「流量」页签 = 全量应用清单，本来就不按类过滤）。
#
# 只有「能明确对上页签」的才建分类页签，其余归入 "others"，
# 由「流量」页签统一承载 —— 不为了凑满页签而臆造分类。
SERVICE_TO_CATEGORY = {
    "VIDEO": "video",
    "WEB BROWSE": "web",
    "VOIP": "ottvoice",
    "OTT VOICE": "ottvoice",
    "OTT VIDEO": "ottvideo",
    "GAME": "game",
}

# 上游 service 的显示名（面板不展示原始大类名，改为按应用粒度展示，
# 这里保留原值只是给「分类」列做标签）
SERVICE_LABELS = {
    "WEB BROWSE": "网页浏览",
    "PUBLIC TRAFFIC": "公共流量",
    "COMM TRAFFIC": "信令流量",
    "NETWORK STORAGE": "云存储",
    "SHOPPING": "电商",
    "SOCIAL": "社交",
    "IM": "即时通讯",
    "EMAIL": "邮件",
    "VIDEO": "视频",
    "VOIP": "语音",
    "OTHERS": "其它",
}

# 上游 service -> 前端 i18n key 后缀（前端拼成 `vmaxq.flow.svc.<key>`）。
# 为什么不用中文名反查：中文名是**展示文案**，改名/加语言就对不上；
# key 是稳定的标识，前端两份字典各自翻译，服务端不需要知道目标语言。
# 与 SERVICE_LABELS 一一对应，新增一项两边都要加（下方 assert 会兜住漏改）。
SERVICE_KEYS = {
    "WEB BROWSE": "webBrowse",
    "PUBLIC TRAFFIC": "publicTraffic",
    "COMM TRAFFIC": "commTraffic",
    "NETWORK STORAGE": "cloudStorage",
    "SHOPPING": "shopping",
    "SOCIAL": "social",
    "IM": "im",
    "EMAIL": "email",
    "VIDEO": "video",
    "VOIP": "voip",
    "OTHERS": "others",
}

# 防漂移：两张表的键集必须完全一致，否则新增 service 时容易只改一张，
# 表现为「中文有标签、英文回退成原始 service 名」这种要上线才发现的 bug。
assert set(SERVICE_LABELS) == set(SERVICE_KEYS), (
    "SERVICE_LABELS / SERVICE_KEYS 键集不一致："
    f"差集 {set(SERVICE_LABELS) ^ set(SERVICE_KEYS)}"
)


def _service_key(service: str) -> str:
    """service 名 -> 前端 i18n key 后缀；未登记返回空串（前端回退中文原文）。"""
    return SERVICE_KEYS.get((service or "").upper(), "")

# 已知游戏应用名（小写匹配）。上游 service 里没有 Game 类，
# 只能靠应用名识别；实测样本未命中，属正常（不是缺陷）。
GAME_APP_KEYWORDS = (
    "pubg", "free fire", "garena", "mobile legends", "mlbb", "genshin",
    "honor of kings", "clash of clans", "coc", "point blank", "crossfire",
    "delta force", "game for peace", "和平精英", "王者荣耀", "原神",
)

# 「控制面 / 质量」指标关键词：这些是**用户体验质量**维度，
# 不是业务分类，所以从全量记录里挑出来单列一页签。
CONTROL_KPI_KEYWORDS = (
    "retrans", "disorder", "rtt", "jitter", "delay", "throughput",
)

# 单次查询取多少条上游记录做聚合。
# 上游分页上限 200；实测忙时号码 6 小时窗有 1558 条，滚动取 8 页足够覆盖
# 「每应用总量」的统计需求（再往后的记录对总量贡献递减）。
MAX_PAGES = 8
PAGE_SIZE = 200

# 上游单次查询的硬上限：合并表 1 万级记录实测要几十秒，
# 这里按 200/页 × 8 页 = 1600 条封顶，避免拖垮页面。
MAX_RECORDS = PAGE_SIZE * MAX_PAGES


def _num(value: Any) -> float:
    """上游数值可能是 '--' / '' / '1.0E7'，统一成 float（解析不了当 0）。"""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fmt_bytes_kb(total_kb: float) -> str:
    """KB -> 带单位的可读串（KB / MB / GB）。"""
    if total_kb <= 0:
        return "0 KB"
    if total_kb < 1024:
        return "%.2f KB" % total_kb
    if total_kb < 1024 * 1024:
        return "%.2f MB" % (total_kb / 1024)
    return "%.2f GB" % (total_kb / 1024 / 1024)


def _fmt_packets(n: float) -> str:
    if n >= 10000:
        return "%.2f 万" % (n / 10000)
    return "%d" % int(n)


class VmaxFlowFromXdr:
    """用 XDR 用户面记录算出「按分类流量」结果。

    构造只取 client，不做 IO；实际查询在 `query()` 里。
    """

    def __init__(self, xdr_client):
        self.xdr = xdr_client

    # ------------------------------------------------------------------
    # 取数
    # ------------------------------------------------------------------
    def _fetch_flow_rows(self, msisdn: str, start: str, end: str) -> List[Dict[str, str]]:
        """拉 `fact_5gsa_psup_flow` 的记录（滚动分页，最多 MAX_RECORDS 条）。

        时间格式用 Talon 的毫秒边界 "YYYY-MM-DD HH:MM:SS.000"。
        """
        fmt = "%Y-%m-%d %H:%M:%S.000"
        st = datetime.strptime(start, "%Y-%m-%d %H:%M:%S").strftime(fmt)
        # 上游按分区切，end 落在刻钟边界（如 :45）会整个分区查不到 ——
        # 实测 end=17:44 有 785 条、end=17:45 变 0 条、end=17:46 又回到 785 条。
        # 往后挪 1 分钟避开边界（多带 1 分钟数据不影响统计口径）。
        et_dt = datetime.strptime(end, "%Y-%m-%d %H:%M:%S") + timedelta(minutes=1)
        et = et_dt.strftime(fmt)

        rows: List[Dict[str, str]] = []
        page = 1
        while page <= MAX_PAGES and len(rows) < MAX_RECORDS:
            res = self.xdr.query_table(
                msisdn, "1300", "fact_5gsa_psup_flow", st, et, page=page, page_size=PAGE_SIZE)
            batch = res.get("rows") or []
            if not batch:
                break
            rows.extend(batch)
            total = int(res.get("records") or 0)
            if len(rows) >= total:
                break
            page += 1
        return rows[:MAX_RECORDS]

    def _fetch_video_rows(self, msisdn: str, start: str, end: str) -> List[Dict[str, str]]:
        """拉 `fact_5gsa_psup_video`（视频专表：带 vmos / resolution 等质量字段）。

        该表只覆盖部分视频会话，实测常常为空或远少于 flow 表 ——
        空是正常的（flow 表里的 Video 类记录仍会被计入「视频」分类）。
        """
        fmt = "%Y-%m-%d %H:%M:%S.000"
        st = datetime.strptime(start, "%Y-%m-%d %H:%M:%S").strftime(fmt)
        et = (datetime.strptime(end, "%Y-%m-%d %H:%M:%S")
              + timedelta(minutes=1)).strftime(fmt)
        try:
            res = self.xdr.query_table(
                msisdn, "1301", "fact_5gsa_psup_video", st, et, page=1, page_size=PAGE_SIZE)
        except Exception as exc:                                  # noqa: BLE001
            logger.warning("[vmax_flow_xdr] 视频专表查询失败（不影响主流程）: %s", exc)
            return []
        return list(res.get("rows") or [])

    # ------------------------------------------------------------------
    # 归一
    # ------------------------------------------------------------------
    @staticmethod
    def _categorize(row: Dict[str, str]) -> str:
        """单条记录 -> 页签 key。"""
        service = str(row.get("service") or "").strip().upper()
        cat = SERVICE_TO_CATEGORY.get(service)
        if cat:
            return cat
        # service 兜底：OTT / GAME 可能在不同版本的上游口径里混在别的类里，
        # 用子业务名再判一次（只在 service 未直接命中时生效）。
        sub = str(row.get("subservice") or "").strip().upper()
        app = str(row.get("app_content_name") or "").strip().upper()
        blob = "%s %s" % (sub, app)
        if "OTT" in blob:
            return "ottvideo" if "VIDEO" in blob else "ottvoice"
        low = blob.lower()
        if any(k in low for k in GAME_APP_KEYWORDS):
            return "game"
        return "others"

    @staticmethod
    def _app_name(row: Dict[str, str]) -> str:
        """应用名：优先 app_content_name，其次 subservice，最后 service。"""
        for key in ("app_content_name", "subservice", "service"):
            val = str(row.get(key) or "").strip()
            if val and val not in ("-", "--"):
                return val
        return "—"

    def _normalize(self, rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """记录列表 -> 应用聚合列表（按应用名合并）。

        每个应用：名称、分类、上下行流量与包数、以及可用于 TCP/控制面口径的
        质量指标聚合值。
        """
        agg: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            name = self._app_name(row)
            cat = self._categorize(row)
            key = "%s||%s" % (cat, name)
            item = agg.get(key)
            if item is None:
                item = {
                    "app_name": name,
                    "category": cat,
                    "service": str(row.get("service") or "").strip(),
                    "subservice": str(row.get("subservice") or "").strip(),
                    "records": 0,
                    "ul_traffic": 0.0, "dl_traffic": 0.0,
                    "ul_pkt": 0.0, "dl_pkt": 0.0,
                    "tcp_resp_delay_sum": 0.0, "tcp_resp_delay_n": 0,
                    "tcp_ack_delay_sum": 0.0, "tcp_ack_delay_n": 0,
                    "ul_rtt_sum": 0.0, "ul_rtt_n": 0,
                    "dl_rtt_sum": 0.0, "dl_rtt_n": 0,
                    "ul_retrans": 0.0, "dl_retrans": 0.0,
                    "ul_disorder": 0.0, "dl_disorder": 0.0,
                    "ul_thr_max": 0.0, "dl_thr_max": 0.0,
                    "duration_sum": 0.0,
                }
                agg[key] = item
            item["records"] += 1
            item["ul_traffic"] += _num(row.get("ul_traffic"))
            item["dl_traffic"] += _num(row.get("dl_traffic"))
            item["ul_pkt"] += _num(row.get("ul_pkt"))
            item["dl_pkt"] += _num(row.get("dl_pkt"))
            item["ul_retrans"] += _num(row.get("ul_retrans_pkt"))
            item["dl_retrans"] += _num(row.get("dl_retrans_pkt"))
            item["ul_disorder"] += _num(row.get("ul_disorder_pkt"))
            item["dl_disorder"] += _num(row.get("dl_disorder_pkt"))
            item["duration_sum"] += _num(row.get("duration"))
            item["ul_thr_max"] = max(item["ul_thr_max"], _num(row.get("ul_throughput_max")))
            item["dl_thr_max"] = max(item["dl_thr_max"], _num(row.get("dl_throughput_max")))
            for field, skey, nkey in (
                ("tcp_resp_delay", "tcp_resp_delay_sum", "tcp_resp_delay_n"),
                ("tcp_ack_delay", "tcp_ack_delay_sum", "tcp_ack_delay_n"),
                ("ul_avg_rtt", "ul_rtt_sum", "ul_rtt_n"),
                ("dl_avg_rtt", "dl_rtt_sum", "dl_rtt_n"),
            ):
                # P0'-1：诊断复用列裁剪后同时带 `$tcp_resp_delay` 与
                # `tcp_resp_delay` 两种写法（上游表版本差异），优先非 $ 列。
                val = _num(row.get(field))
                if not val:
                    val = _num(row.get("$" + field))
                if val > 0:
                    item[skey] += val
                    item[nkey] += 1
        return list(agg.values())

    def aggregate_from_rows(self, rows: List[Dict[str, Any]],
                            video_rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """已有 1300/1301 行 -> 分类流量结果（诊断复用入口，不再打上游）。

        P0'-1：诊断一次取 1300，流量聚合直接复用这批行，省掉第二遍
        6 页分页（单账号下约 12s）。口径与 `query()` 完全一致，
        只是跳过 `_fetch_flow_rows/_fetch_video_rows`。
        无数据返回 None（调用方按 found=false 处理）。
        """
        if not rows and not video_rows:
            return None
        items = self._normalize(rows)
        categories = self.aggregate_categories(items, video_rows)
        total_kb = sum(it["ul_traffic"] + it["dl_traffic"] for it in items)
        apps = self._app_rows(items, total_kb)
        return {
            "total_flux": _fmt_bytes_kb(total_kb),
            "total_flux_kb": round(total_kb, 2),
            "apps": apps,
            "categories": categories,
            "source": "xdr_user_plane",
            "records": len(rows),
        }

    # ------------------------------------------------------------------
    # 聚合
    # ------------------------------------------------------------------
    @staticmethod
    def _app_rows(items: List[Dict[str, Any]],
                  total_traffic: float) -> List[Dict[str, Any]]:
        """应用列表 -> 前端表格行（按总流量降序，带占比）。"""
        rows = []
        for it in items:
            traffic = it["ul_traffic"] + it["dl_traffic"]
            rows.append({
                "app_name": it["app_name"],
                "category": it["category"],
                # service_key：SERVICE_LABELS 的反查键（如 "video"/"voip"/"others"），
                # 前端用它去查 vmaxq.flow.svc.* 字典得到当前语言的标签。
                # category_label 保留中文原文作兜底 —— 未登记的 service
                # （如上游新增的 "GAMING"）没有 key，只能原样显示。
                "service_key": _service_key(it["service"]),
                "category_label": (SERVICE_LABELS.get(it["service"].upper())
                                   or it["service"] or it["subservice"] or ""),
                "service": it["service"],
                "subservice": it["subservice"],
                "records": it["records"],
                "ul_traffic": _fmt_bytes_kb(it["ul_traffic"]),
                "dl_traffic": _fmt_bytes_kb(it["dl_traffic"]),
                "total_traffic": _fmt_bytes_kb(traffic),
                "total_traffic_kb": round(traffic, 2),
                "ul_pkt": _fmt_packets(it["ul_pkt"]),
                "dl_pkt": _fmt_packets(it["dl_pkt"]),
                "ratio": ("%.1f%%" % (traffic / total_traffic * 100)) if total_traffic > 0 else "—",
            })
        rows.sort(key=lambda r: -float(r["total_traffic_kb"]))
        return rows

    @staticmethod
    def _quality_kpis(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从应用聚合里算出 TCP / 质量指标（前端「TCP指标」「控制面」两页签用）。

        这是**指标口径**而不是应用分类，所以由全量记录聚合而来。
        """
        def _avg(sum_key: str, n_key: str) -> float:
            total = sum(it.get(sum_key, 0.0) for it in items)
            n = sum(it.get(n_key, 0) for it in items)
            return (total / n) if n else 0.0

        ul_pkt = sum(it["ul_pkt"] for it in items)
        dl_pkt = sum(it["dl_pkt"] for it in items)
        ul_retrans = sum(it["ul_retrans"] for it in items)
        dl_retrans = sum(it["dl_retrans"] for it in items)
        ul_disorder = sum(it["ul_disorder"] for it in items)
        dl_disorder = sum(it["dl_disorder"] for it in items)
        pkt_total = ul_pkt + dl_pkt
        duration_ms = sum(it["duration_sum"] for it in items)

        # 每条都带 key：`name` 是中文兜底，`kpi_key` 才是前端翻译的依据。
        # 只给中文名会让英文界面必然冒中文（前端无法靠中文反查），
        # 只给英文名又会让中文界面变英文 —— 所以两份都给，由渲染层决定用哪个。
        # key 统一 kpi.* 前缀，与 vmaxq.flow.kpi.* 字典项一一对应。
        return [
            {"key": "tcpHandshake", "name": "TCP 握手响应时延(平均)",
             "value": "%.1f" % _avg("tcp_resp_delay_sum", "tcp_resp_delay_n"), "unit": "ms"},
            {"key": "tcpAck", "name": "TCP 应答时延(平均)",
             "value": "%.1f" % _avg("tcp_ack_delay_sum", "tcp_ack_delay_n"), "unit": "ms"},
            {"key": "ulRtt", "name": "上行 RTT(平均)",
             "value": "%.1f" % _avg("ul_rtt_sum", "ul_rtt_n"), "unit": "ms"},
            {"key": "dlRtt", "name": "下行 RTT(平均)",
             "value": "%.1f" % _avg("dl_rtt_sum", "dl_rtt_n"), "unit": "ms"},
            # 包数类带 `raw`：`_fmt_packets` 的「万」是中文数字单位，
            # 英文界面不该出现，交给前端按语言缩进（本接口无 lang 参数）。
            {"key": "ulRetransPkt", "name": "上行重传包数", "raw": int(ul_retrans),
             "value": _fmt_packets(ul_retrans), "unit": "pcs"},
            {"key": "dlRetransPkt", "name": "下行重传包数", "raw": int(dl_retrans),
             "value": _fmt_packets(dl_retrans), "unit": "pcs"},
            {"key": "ulDisorderPkt", "name": "上行乱序包数", "raw": int(ul_disorder),
             "value": _fmt_packets(ul_disorder), "unit": "pcs"},
            {"key": "dlDisorderPkt", "name": "下行乱序包数", "raw": int(dl_disorder),
             "value": _fmt_packets(dl_disorder), "unit": "pcs"},
            {"key": "retransRate", "name": "重传率",
             "value": ("%.3f%%" % ((ul_retrans + dl_retrans) / pkt_total * 100))
             if pkt_total > 0 else "—", "unit": ""},
            {"key": "disorderRate", "name": "乱序率",
             "value": ("%.3f%%" % ((ul_disorder + dl_disorder) / pkt_total * 100))
             if pkt_total > 0 else "—", "unit": ""},
            {"key": "ulPeak", "name": "上行峰值速率",
             "value": "%d" % max([it["ul_thr_max"] for it in items] or [0]), "unit": "Kbps"},
            {"key": "dlPeak", "name": "下行峰值速率",
             "value": "%d" % max([it["dl_thr_max"] for it in items] or [0]), "unit": "Kbps"},
            {"key": "sessionDur", "name": "会话总时长",
             "value": "%.1f" % (duration_ms / 1000.0), "unit": "s"},
        ]

    def aggregate_categories(self, items: List[Dict[str, Any]],
                             video_rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """应用聚合 -> 页签数据（前端二级页签结构）。

        每个分类返回 {key, apps, kpis, total_flux}：
          - apps：该分类的应用列表；
          - kpis：该分类的指标（TCP/控制面两类指标口径见 `_quality_kpis`）；
          - total_flux：该分类的流量合计。
        """
        total_traffic = sum(it["ul_traffic"] + it["dl_traffic"] for it in items)

        by_cat: Dict[str, List[Dict[str, Any]]] = {}
        for it in items:
            by_cat.setdefault(it["category"], []).append(it)

        # 视频专表带 vmos / resolution / result —— 补进「视频」分类的指标里
        video_kpis: List[Dict[str, Any]] = []
        if video_rows:
            vmos = [_num(r.get("vmos")) for r in video_rows]
            vmos_ok = [v for v in vmos if v > 0]
            resolutions: Dict[str, int] = {}
            for r in video_rows:
                res = str(r.get("resolution") or "").strip()
                if res and res not in ("-", "--", "Other"):
                    resolutions[res] = resolutions.get(res, 0) + 1
            if vmos_ok:
                video_kpis.append({
                    "name": "视频 MOS(平均)", "value": "%.4f" % (sum(vmos_ok) / len(vmos_ok)),
                    "unit": ""})
            if resolutions:
                top = sorted(resolutions.items(), key=lambda kv: -kv[1])[:3]
                video_kpis.append({
                    "name": "主要分辨率",
                    "value": "、".join("%s×%d" % (k, v) for k, v in top),
                    "unit": ""})
            succ = sum(1 for r in video_rows if str(r.get("result") or "").lower() == "succeed")
            video_kpis.append({
                "name": "视频会话成功率",
                "value": "%.1f%%" % (succ / len(video_rows) * 100), "unit": ""})

        out: List[Dict[str, Any]] = []
        for key in CATEGORY_KEYS:
            if key == "all":
                # 「流量」页签 = 全量应用 + 全量指标，
                # 合计必须用全部记录算（by_cat 里没有 "all" 这个键，
                # 直接取 by_cat.get("all") 会得到 0）。
                cat_items = items
                apps = self._app_rows(items, total_traffic)
                kpis = self._quality_kpis(items)
            elif key == "tcp":
                cat_items = []
                apps = []
                kpis = [k for k in self._quality_kpis(items)
                        if any(w in k["name"].lower() for w in ("tcp", "rtt", "重传", "乱序"))]
            elif key == "control":
                cat_items = []
                apps = []
                kpis = [k for k in self._quality_kpis(items)
                        if any(w in k["name"].lower() for w in ("速率", "时长", "峰值"))]
            else:
                cat_items = by_cat.get(key, [])
                apps = self._app_rows(cat_items, total_traffic)
                kpis = list(video_kpis) if key == "video" else []
            cat_traffic = sum(it["ul_traffic"] + it["dl_traffic"] for it in cat_items)
            out.append({
                "key": key,
                "apps": apps,
                "kpis": kpis,
                "total_flux": _fmt_bytes_kb(cat_traffic),
                "total_flux_kb": round(cat_traffic, 2),
            })
        return out

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def query(self, msisdn: str, start: str, end: str) -> Optional[Dict[str, Any]]:
        """号码 + 时间窗 -> 分类流量结果。无数据返回 None。

        返回结构与 CCA 的 flow 段同构（前端可复用同一套页签组件）：
            {total_flux, apps, categories, source}
        """
        rows = self._fetch_flow_rows(msisdn, start, end)
        video_rows = self._fetch_video_rows(msisdn, start, end)
        if not rows and not video_rows:
            return None

        items = self._normalize(rows)
        categories = self.aggregate_categories(items, video_rows)
        total_kb = sum(it["ul_traffic"] + it["dl_traffic"] for it in items)
        apps = self._app_rows(items, total_kb)
        return {
            "total_flux": _fmt_bytes_kb(total_kb),
            "total_flux_kb": round(total_kb, 2),
            "apps": apps,
            "categories": categories,
            "source": "xdr_user_plane",
            "records": len(rows),
        }
