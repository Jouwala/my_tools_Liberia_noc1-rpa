#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vmax_cxo_daily_cache.py — VMAX CXO 天粒度看板数据归档（worker 定时任务，独立于 cxo_dashboard_cache）

为什么单独建一个任务（不动现有 cxo_dashboard_cache_sync）：
    1. 上游 VMAX **没有天粒度**：`/query/v2/history` 的 Granularity 枚举实测只接受
       1min / 5min / 15min / 30min / 1hour（`1day`/`day`/`1week`/`24hour` 一律
       code=150 "does not exist in enum types: com.zte.common.model.design.Granularity"）。
       天粒度只能由本任务拉 1hour 明细自行聚合。
    2. 上游小时明细**只保留约 8 天**（2026-09-15 实测地板 = 2026-09-08，15min 同地板）。
       过期即永久不可回补 -> 必须每天稳定落盘累积，且失败要能在窗口内重试。
    3. 本任务只做「读上游 + 写自己的文件」，绝不写 data/cxo_dashboard/*，
       也不调用 ensure_proxy（避免把僵死检测/重启逻辑压到现有看板共用的 8790 代理上）：
       代理不健康就本轮跳过，下一轮补拉，8 天窗口内零丢失。

数据口径（实测与看板现有数字完全一致，误差 0）：
    小时行 = 该小时聚合值。量类（Traffic）是该小时内累加，率/仪表类（User/Mbps/ms/%）
    是该小时平均。故日聚合按 KPI 区分：sum / avg / max，一律先除 unitChange 换算成看板单位。
    验证：09-14 @1hour sum(91)/1024^3 = 286630.5 GB == 看板 day-1 96 桶求和 286630.5 GB
          09-14 @1hour max(92)/1000   = 196.1  K  == 看板 day-1 峰值 196.0  K

指标规模与取数（2026-09-16 扩到 50 个：6 汇总 + 14 网络 + 30 服务/OTT，页签与参考看板对齐）：
    - 按 (monitorid, 过滤配方) 多列合批：50 个指标 -> 8 个请求（实测 14 列一次返回 0.06s，
      整轮 ~5s；逐指标请求则要 50 次、~40s）。
    - **响应 field 的列顺序由服务端决定，与请求顺序不一致**（实测请求 ...022,021 返回
      021,022），因此 _fetch_batch 一律按列名映射，绝不能按位置取。
    - 服务/OTT 类（5112/5113/5114/5115/5116）全为率/时延/吞吐/MOS/频次口径 -> 日值取
      未加权小时均值；注意 ppc40046504x "Times of ... Reconnection" 上游实为**频次**(次/通话)，
      量级 0.0x，故用 avg 而非 sum。

产出（全部新增，路径独立）：
    data/vmax_cxo_daily/daily.json   —— 日值主存（GET /api/vmax-cxo-daily/daily 透传裁剪）

KPI 规格来源：last_known_good.json 里 trend_* 响应自带的 queryParam/kpiConfig
（monitorid + KPI 码 + 过滤条件），已固化在 KPI_SPECS，运行时不再依赖那个文件；
服务/OTT 类指标的标题与页签归属取自参考看板 vmaxCxoDashboard 的页签目录。
"""
import base64
import json
import logging
import os
import sys
import time
import urllib.parse
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from backend.services.atomic_write import atomic_replace_file

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent  # my_app/
DATA_DIR = _ROOT / "data" / "vmax_cxo_daily"
DAILY_FILE = DATA_DIR / "daily.json"

PROXY_BASE = "http://127.0.0.1:8790/proxy?url="
VMAX_HOST = "https://10.123.255.12:26180"
HISTORY_ENDPOINT = "/query/v2/history"

# 上游 1hour 明细保留期实测 8 天（含当天）；每天多回看 1 天做重叠补拉
GRANULARITY = "1hour"
RETENTION_DAYS = 8
LOOKBACK_DAYS = 8          # 每次向历史回看的天数（含今天）
HOURS_PER_DAY = 24
_REQ_TIMEOUT = (10, 90)

# mars 历史查询 param 的 RSA 公钥（从 VMAX mars 前端 encryptLong 复刻，服务端静态公钥）
_MARS_PUB_B64 = ("MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC/h5K+Yr5VRtCyeg3g85xbi91K4hc"
                 "XehTtkPOZaC19SGyrNGzq8WmvGLbbvcU7NcpJ0I/cdg0sAcbcPlt/Q/RofmYgpD0gCK"
                 "z2ZIpgcAszndY0DjKhOGbNPnoIRO9ln3giPqCIfdzF8MUCgIGVLWK1ha7STUwdAFZkb"
                 "z45X4KVkwIDAQAB")

# 过滤条件：全网（interfaceid=11 / rat=6），与 CXO 看板 Summary 完全一致
_FILTER_MODEL = {"filterType": "0", "filterGroupList": [{
    "filter_type": "0", "items": None, "filterType": "0",
    "filterModelList": [
        {"filed": "interfaceid", "operation": "0", "value": "11", "valueDesc": "", "id": "interfaceid"},
        {"filed": "rat", "operation": "0", "value": 6, "valueDesc": "", "id": "rat"},
    ]}]}

# 网络类监控（monitor 5132 等 RAN 指标）看板用的是【空过滤】：interfaceid/rat 在 RAN 维度里
# 根本不存在，套上反而会取空。实测同一指标空过滤与带过滤在视频/汇总监控上差 <0.01%（噪音），
# 但在 5132 上必须用空过滤。故过滤按 monitor 走看板原样，不再全局共用一条。
_EMPTY_FILTER = {"filterType": "0", "filterGroupList":
                 [{"filter_type": "0", "items": None, "filterType": "0", "filterModelList": []}]}

# CXO 趋势 KPI + 网络 KPI：id -> 规格（agg = 日聚合口径，页面 primary 取值）。
# group 供前端分组渲染；note 是取值口径提示（悬浮显示）。
# filter_model 省略即用 _FILTER_MODEL（汇总/视频类），网络类 5132 用 _EMPTY_FILTER。
KPI_SPECS = {
    "91": {"title": "Total Traffic", "unit": "(GB)", "monitorid": 250005, "code": "ppc400401001",
           "divisor": 1073741824.0, "agg": "sum", "digits": 2, "group": "summary", "note": ""},
    "92": {"title": "Active User", "unit": "(K)", "monitorid": 250005, "code": "ppb400499002",
           "divisor": 1000.0, "agg": "max", "digits": 2, "group": "summary", "note": ""},
    "93": {"title": "Video DL Valid Throughput", "unit": "(Mbps)", "monitorid": 5112, "code": "ppc400464046",
           "divisor": 1024.0, "agg": "avg", "digits": 2, "group": "summary", "note": ""},
    "94": {"title": "Average Cache Duration of Video Playing", "unit": "(ms)", "monitorid": 5112,
           "code": "ppc400464013", "divisor": None, "agg": "avg", "digits": 2, "group": "summary", "note": ""},
    "95": {"title": "Stalling Frequency Of Video Playing", "unit": "(times/min)", "monitorid": 5112,
           "code": "ppc400464049", "divisor": None, "agg": "avg", "digits": 3, "group": "summary", "note": ""},
    "99": {"title": "Stalling Duration Ratio of Video Playing", "unit": "(%)", "monitorid": 5112,
           "code": "ppc400464015", "divisor": None, "agg": "avg", "digits": 2, "group": "summary", "note": ""},
    # ---- 网络 KPI（monitor 5132，看板 Mobility/Voice/Data/Video 页共用同一监控，空过滤）----
    # 成功/接入/切换类全是「率」-> 日值取未加权小时均值（与 VMAX 官方按次数加权日口径可能略有差）。
    "101": {"title": "Attach Success Rate", "unit": "(%)", "monitorid": 5132, "code": "ppc300501005",
            "divisor": None, "agg": "avg", "digits": 2, "group": "network", "filter_model": _EMPTY_FILTER,
            "note": "unweighted"},
    "102": {"title": "Attach Success Rate (Non-User)", "unit": "(%)", "monitorid": 5132, "code": "ppc300501008",
            "divisor": None, "agg": "avg", "digits": 2, "group": "network", "filter_model": _EMPTY_FILTER,
            "note": "unweighted"},
    "103": {"title": "TAU Success Rate (Non-User)", "unit": "(%)", "monitorid": 5132, "code": "ppc300503001",
            "divisor": None, "agg": "avg", "digits": 2, "group": "network", "filter_model": _EMPTY_FILTER,
            "note": "unweighted"},
    "104": {"title": "Service Request Success Rate", "unit": "(%)", "monitorid": 5132, "code": "ppc300504126",
            "divisor": None, "agg": "avg", "digits": 2, "group": "network", "filter_model": _EMPTY_FILTER,
            "note": "unweighted"},
    "105": {"title": "Default Bearer Activation SR (Non-User)", "unit": "(%)", "monitorid": 5132,
            "code": "ppc300521001", "divisor": None, "agg": "avg", "digits": 2, "group": "network",
            "filter_model": _EMPTY_FILTER, "note": "unweighted"},
    "106": {"title": "Dedicated Bearer Activation SR", "unit": "(%)", "monitorid": 5132, "code": "ppc300522214",
            "divisor": None, "agg": "avg", "digits": 2, "group": "network", "filter_model": _EMPTY_FILTER,
            "note": "unweighted"},
    "107": {"title": "E-RAB Setup Success Rate", "unit": "(%)", "monitorid": 5132, "code": "ppc300541302",
            "divisor": None, "agg": "avg", "digits": 2, "group": "network", "filter_model": _EMPTY_FILTER,
            "note": "unweighted"},
    "108": {"title": "Wireless Call Drop Rate", "unit": "(%)", "monitorid": 5132, "code": "ppc300542580",
            "divisor": None, "agg": "avg", "digits": 3, "group": "network", "filter_model": _EMPTY_FILTER,
            "note": "unweighted_lower"},
    "109": {"title": "5G-to-4G Handover Success Rate", "unit": "(%)", "monitorid": 5132, "code": "ppc300543001",
            "divisor": None, "agg": "avg", "digits": 2, "group": "network", "filter_model": _EMPTY_FILTER,
            "note": "unweighted"},
    "110": {"title": "4G-to-5G Handover Success Rate", "unit": "(%)", "monitorid": 5132, "code": "ppc300543002",
            "divisor": None, "agg": "avg", "digits": 2, "group": "network", "filter_model": _EMPTY_FILTER,
            "note": "unweighted"},
    "111": {"title": "S1 HO Out Success Rate", "unit": "(%)", "monitorid": 5132, "code": "ppc300543357",
            "divisor": None, "agg": "avg", "digits": 2, "group": "network", "filter_model": _EMPTY_FILTER,
            "note": "unweighted"},
    "112": {"title": "S1 HO In Success Rate", "unit": "(%)", "monitorid": 5132, "code": "ppc300543368",
            "divisor": None, "agg": "avg", "digits": 2, "group": "network", "filter_model": _EMPTY_FILTER,
            "note": "unweighted"},
    "113": {"title": "Paging Success Rate", "unit": "(%)", "monitorid": 5132, "code": "ppc300544532",
            "divisor": None, "agg": "avg", "digits": 2, "group": "network", "filter_model": _EMPTY_FILTER,
            "note": "unweighted"},
    "114": {"title": "Call Drop to eNB L700 (times)", "unit": "(times)", "monitorid": 5132,
            "code": "ppb300542009", "divisor": None, "agg": "sum", "digits": 0, "group": "network",
            "filter_model": _EMPTY_FILTER, "note": "sum_hours"},
    # ---- 服务/OTT 类（monitor 5112/5113/5114/5115/5116，页签指标编号直接用看板自己的 id）----
    # 这些全是「率/时延/吞吐/MOS/频次」口径，日值一律取未加权小时均值；实测原始值与看板
    # 显示值量级一致（比值≈1.0），故 divisor 全部为 None。
    # 202/208 与上面 93/94 是同一 code 但看板页签口径不同（标题也不同），故独立建条目。
    "202": {"title": "Valid Throughput of Video Download", "unit": "(kbps)", "monitorid": 5112,
            "code": "ppc400464046", "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": "unweighted"},
    "208": {"title": "Video Initial Buffer Duration", "unit": "(ms)", "monitorid": 5112,
            "code": "ppc400464013", "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": "unweighted"},
    "204": {"title": "TCP Average Network Site RTT", "unit": '(ms)', "monitorid": 5112, "code": 'ppc400464050',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "205": {"title": "TCP Average Terminal Site RTT", "unit": '(ms)', "monitorid": 5112, "code": 'ppc400464051',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "206": {"title": "TCP UL Retransmission Rate", "unit": '(%)', "monitorid": 5112, "code": 'ppc400464030',
            "divisor": None, "agg": "avg", "digits": 3, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "207": {"title": "TCP DL Retransmission Rate", "unit": '(%)', "monitorid": 5112, "code": 'ppc400464031',
            "divisor": None, "agg": "avg", "digits": 3, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "221": {"title": "Web DL Tput(>500KB)", "unit": '(kbps)', "monitorid": 5113, "code": 'ppc400461018',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "223": {"title": "TCP Average Network Side RTT", "unit": '(ms)', "monitorid": 5113, "code": 'ppc400461040',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "224": {"title": "TCP Average Terminal Site RTT", "unit": '(ms)', "monitorid": 5113, "code": 'ppc400461041',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "225": {"title": "TCP UL Retransmission Rate", "unit": '(%)', "monitorid": 5113, "code": 'ppc400461044',
            "divisor": None, "agg": "avg", "digits": 3, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "226": {"title": "TCP DL Retransmission Rate", "unit": '(%)', "monitorid": 5113, "code": 'ppc400461045',
            "divisor": None, "agg": "avg", "digits": 3, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "227": {"title": "Success Response Delay", "unit": '(ms)', "monitorid": 5113, "code": 'ppc400461013',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "228": {"title": "Displaying Delay", "unit": '(ms)', "monitorid": 5113, "code": 'ppc400461014',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "242": {"title": "TCP Average Network Site RTT", "unit": '(ms)', "monitorid": 5114, "code": 'ppc400403047',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "243": {"title": "TCP Average Terminal Site RTT", "unit": '(ms)', "monitorid": 5114, "code": 'ppc400403048',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "244": {"title": "TCP UL Retransmission Rate", "unit": '(%)', "monitorid": 5114, "code": 'ppc400403018',
            "divisor": None, "agg": "avg", "digits": 3, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "245": {"title": "TCP DL Retransmission Rate", "unit": '(%)', "monitorid": 5114, "code": 'ppc400403019',
            "divisor": None, "agg": "avg", "digits": 3, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "262": {"title": "Local MOS", "unit": '', "monitorid": 5115, "code": 'ppc400465047',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "263": {"title": "Opposite MOS", "unit": '', "monitorid": 5115, "code": 'ppc400465048',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "264": {"title": "Proportion of Local MOS > 3.0", "unit": '(%)', "monitorid": 5115, "code": 'ppc400465045',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "265": {"title": "Proportion of Opposite MOS > 3.0", "unit": '(%)', "monitorid": 5115, "code": 'ppc400465046',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "266": {"title": "Times of Local Reconnection", "unit": '', "monitorid": 5115, "code": 'ppc400465041',
            "divisor": None, "agg": "avg", "digits": 3, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'frequency'},
    "267": {"title": "Times of Opposite Reconnection", "unit": '', "monitorid": 5115, "code": 'ppc400465042',
            "divisor": None, "agg": "avg", "digits": 3, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'frequency'},
    "268": {"title": "Call Duration", "unit": '(s)', "monitorid": 5115, "code": 'ppb400465067',
            "divisor": None, "agg": "avg", "digits": 0, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'counter_caution'},
    "269": {"title": "Call DL Tput", "unit": '(kbps)', "monitorid": 5115, "code": 'ppc400465022',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "270": {"title": "Call UL Tput", "unit": '(kbps)', "monitorid": 5115, "code": 'ppc400465021',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "271": {"title": "OTT UL Media Packet Loss Rate", "unit": '(%)', "monitorid": 5115, "code": 'ppc400465028',
            "divisor": None, "agg": "avg", "digits": 3, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "272": {"title": "OTT DL Media Packet Loss Rate", "unit": '(%)', "monitorid": 5115, "code": 'ppc400465029',
            "divisor": None, "agg": "avg", "digits": 3, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "282": {"title": "Local MOS", "unit": '', "monitorid": 5116, "code": 'ppc400465047',
            "divisor": None, "agg": "avg", "digits": 2, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'unweighted'},
    "283": {"title": "Times of Local Reconnection", "unit": '', "monitorid": 5116, "code": 'ppc400465041',
            "divisor": None, "agg": "avg", "digits": 3, "group": "service",
            "filter_model": _EMPTY_FILTER, "note": 'frequency'},
}

# ---------- 页签归属（与参考看板 vmaxCxoDashboard 的页签结构逐条对齐）----------
# 顶层页签顺序 + 各页签的子页签顺序；每个页签具体由哪些指标构成，见 KPI_TABS。
TAB_ORDER = [
    {"key": "summary", "subtabs": None},
    {"key": "network", "subtabs": ["Mobility", "Service Request", "Accessibility",
                                   "Retainability", "InterWorking"]},
    {"key": "service", "subtabs": ["Mobility", "Voice", "Data", "Video", "SMS",
                                   "Web Browse", "Game", "OTTVoice", "OTTVideo"]},
]

# KPI id -> 页签归属（"<scope>/<子页签>"）。一个指标可同时出现在 network 与 service 的对应页签下。
KPI_TABS = {
    "91": ["summary"], "92": ["summary"], "93": ["summary"],
    "94": ["summary"], "95": ["summary"], "99": ["summary"],
    # 5132 网络类 14 个（id 101-114）
    "101": ["network/Accessibility", "service/Data"],
    "102": ["network/Accessibility", "service/Data"],
    "103": ["network/Mobility", "service/Mobility"],
    "104": ["network/Service Request", "service/Voice"],
    "105": ["network/Service Request", "service/Voice"],
    "106": ["network/Service Request", "service/Voice"],
    "107": ["network/Accessibility", "service/Data"],
    "108": ["network/Retainability", "service/Video"],
    "109": ["network/InterWorking"],
    "110": ["network/InterWorking"],
    "111": ["network/Mobility", "service/Mobility"],
    "112": ["network/Mobility", "service/Mobility"],
    "113": ["network/Service Request"],
    "114": ["network/InterWorking"],
    # 服务/OTT 类 30 个（id 即看板页签指标编号）
    "202": ["service/SMS"], "204": ["service/SMS"], "205": ["service/SMS"],
    "206": ["service/SMS"], "207": ["service/SMS"], "208": ["service/SMS"],
    "221": ["service/Web Browse"], "223": ["service/Web Browse"], "224": ["service/Web Browse"],
    "225": ["service/Web Browse"], "226": ["service/Web Browse"], "227": ["service/Web Browse"],
    "228": ["service/Web Browse"],
    "242": ["service/Game"], "243": ["service/Game"], "244": ["service/Game"], "245": ["service/Game"],
    "262": ["service/OTTVoice"], "263": ["service/OTTVoice"], "264": ["service/OTTVoice"],
    "265": ["service/OTTVoice"], "266": ["service/OTTVoice"], "267": ["service/OTTVoice"],
    "268": ["service/OTTVoice"], "269": ["service/OTTVoice"], "270": ["service/OTTVoice"],
    "271": ["service/OTTVoice"], "272": ["service/OTTVoice"],
    "282": ["service/OTTVideo"], "283": ["service/OTTVideo"],
}


def build_tab_tree():
    """按 TAB_ORDER / KPI_TABS 组装页签树（只保留实际存在的 KPI）。"""
    tree = []
    for tab in TAB_ORDER:
        key = tab["key"]
        if not tab.get("subtabs"):
            kpis = [kid for kid, tabs in KPI_TABS.items() if key in tabs]
            tree.append({"key": key, "kpis": kpis, "subtabs": []})
            continue
        subs = []
        for sub in tab["subtabs"]:
            full = "%s/%s" % (key, sub)
            kpis = [kid for kid, tabs in KPI_TABS.items() if full in tabs]
            if kpis:
                subs.append({"key": sub, "kpis": kpis})
        tree.append({"key": key, "kpis": [], "subtabs": subs})
    return tree


# ---------- mars RSA encryptLong ----------
def _encrypt_param(text: str) -> str:
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.serialization import load_der_public_key
    key = load_der_public_key(base64.b64decode(_MARS_PUB_B64))
    data = text.encode("utf-8")
    hex_all = ""
    for i in range(0, len(data), 117):          # 117B/块 -> PKCS1v15 -> 128B -> 256 hex
        hex_all += key.encrypt(data[i:i + 117], padding.PKCS1v15()).hex()
    return base64.b64encode(bytes.fromhex(hex_all)).decode()


# ---------- 8790 代理：只读健康检查，绝不做重启/杀进程 ----------
def _proxy_health() -> dict:
    try:
        r = requests.get("http://127.0.0.1:8790/health", timeout=5)
        r.raise_for_status()
        j = r.json()
        if isinstance(j, dict) and j.get("status") == "ok" and j.get("proxy") == "ready":
            return {"ready": True, "user": j.get("user") or ""}
        return {"ready": False, "user": "", "detail": j}
    except Exception as exc:                                  # noqa: BLE001
        return {"ready": False, "user": "", "detail": "%s: %s" % (type(exc).__name__, exc)}


def _fetch_batch(session, monitorid, codes, filter_model, user_name, last_time, end_time, period):
    """一次请求多列（实测 11 列 0.06s），返回 {code: [[clttime, value], ...]}。

    响应 field 的列顺序由服务端决定、与请求顺序不一致（实测请求 022,021 返回 021,022），
    因此必须按列名映射，绝不能按位置取。
    """
    cond = {
        "condition": {
            "filterListModel": filter_model,
            "showColumns": ["clttime"] + list(codes),
            "times": {"lastTime": last_time, "endTime": end_time,
                      "granularity": GRANULARITY, "period": period, "type": 2},
            "size": 10000,
        },
        "uid": 0, "sceneid": "3", "monitorid": monitorid, "userName": user_name,
    }
    payload = {"param": _encrypt_param(json.dumps(cond, separators=(",", ":")))}
    target = urllib.parse.quote(VMAX_HOST + HISTORY_ENDPOINT, safe="")
    r = session.post(PROXY_BASE + target, json=payload, timeout=_REQ_TIMEOUT)
    r.raise_for_status()
    body = r.json()
    if not isinstance(body, dict):
        raise ValueError("非预期响应类型 %s" % type(body).__name__)
    code = body.get("code")
    if code not in (0, "0", None):
        raise RuntimeError("mars code=%s msg=%s" % (code, str(body.get("msg"))[:160]))
    inner = body.get("data") if isinstance(body.get("data"), dict) else {}
    field = inner.get("field") or []
    rows = inner.get("data") or []
    idx = {}
    for i, name in enumerate(field):
        if name != "clttime":
            idx.setdefault(name, i)
    out = {}
    for c in codes:
        i = idx.get(c)
        if i is None:
            out[c] = []
            continue
        out[c] = [[row[0], row[i]] for row in rows
                  if isinstance(row, (list, tuple)) and len(row) > i]
    return out


def _aggregate_rows(rows, spec, today_iso):
    """原始小时行 -> {日期: {sum,avg,max,min,n,complete}}（先按 unitChange 换算）。"""
    divisor = spec.get("divisor") or 1.0
    digits = int(spec.get("digits") if spec.get("digits") not in (None, "") else 2)
    per_day = defaultdict(list)
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        stamp = str(row[0] or "")
        day = stamp[:10]
        if len(day) != 10 or day > today_iso:                  # 丢弃未来/脏时间戳
            continue
        try:
            val = float(row[1])
        except (TypeError, ValueError):
            continue                                            # "--"/""/None 视为无数据
        per_day[day].append(val / divisor)

    out = {}
    for day, vals in per_day.items():
        n = len(vals)
        if not n:
            continue
        out[day] = {
            "sum": round(sum(vals), digits),
            "avg": round(sum(vals) / n, digits),
            "max": round(max(vals), digits),
            "min": round(min(vals), digits),
            "n": n,
            # 完整日：过去日需 24 个时点齐全；今天只要抓到就标 partial（in_progress）
            "complete": bool(n >= HOURS_PER_DAY and day < today_iso),
            "in_progress": bool(day == today_iso),
        }
    return out


# ---------- 日存读写 ----------
def _empty_store():
    return {"version": 1, "updated_at": None, "granularity": GRANULARITY,
            "retention_days": RETENTION_DAYS, "kpis": KPI_SPECS, "days": {}}


def _load_store() -> dict:
    try:
        with open(DAILY_FILE, "r", encoding="utf-8") as stream:
            store = json.load(stream)
        if isinstance(store, dict) and isinstance(store.get("days"), dict):
            store.setdefault("kpis", KPI_SPECS)
            store["kpis"] = KPI_SPECS            # 口径以代码为准，避免旧文件残留误导前端
            store.setdefault("granularity", GRANULARITY)
            store.setdefault("retention_days", RETENTION_DAYS)
            return store
    except FileNotFoundError:
        pass
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("[vmax_daily] 旧日存读取失败，重建: %s", exc)
    return _empty_store()


def _save_store(store):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_DIR / ("daily.%s.%s.tmp.json" % (os.getpid(), uuid.uuid4().hex))
    with open(tmp, "w", encoding="utf-8") as stream:
        json.dump(store, stream, ensure_ascii=False)
    atomic_replace_file(str(tmp), str(DAILY_FILE), max_retries=15, base_wait=1.0)


def _merge_days(store, fetched, now_iso):
    """新数据只在「更完整」时覆盖旧值；旧值永不被空结果冲掉。"""
    days = store["days"]
    written = 0
    touched = []
    for kpi_id, per_day in fetched.items():
        for day, stats in per_day.items():
            old = (days.get(day) or {}).get(kpi_id)
            if old and old.get("complete") and not stats.get("complete"):
                continue                                       # 已完整，不被部分数据覆盖
            if old and int(old.get("n") or 0) > int(stats.get("n") or 0):
                continue                                       # 新的点更少 -> 保留旧的
            days.setdefault(day, {})[kpi_id] = dict(stats, updated_at=now_iso)
            written += 1
            touched.append(day)
    # 超出保留期太久的日期清掉（上游已不可能再有，值也永不再变，留 120 天足够页面回看）
    cutoff = (date.today() - timedelta(days=120)).isoformat()
    for day in [d for d in list(days) if d < cutoff]:
        days.pop(day, None)
    return written, (max(touched) if touched else None)


# ---------- 主入口 ----------
def run_vmax_cxo_daily_sync(lookback_days: int = LOOKBACK_DAYS) -> dict:
    """拉取最近 lookback_days 的 1hour 明细并聚合成日值落盘。"""
    start = time.time()
    today = date.today()
    today_iso = today.isoformat()
    lookback = max(1, min(int(lookback_days or LOOKBACK_DAYS), RETENTION_DAYS))
    first_day = today - timedelta(days=lookback - 1)
    last_time = "%s 00:00:00" % first_day
    end_time = "%s 00:00:00" % (today + timedelta(days=1))
    period = lookback * HOURS_PER_DAY

    health = _proxy_health()
    if not health.get("ready"):
        msg = "VMAX 8790 代理未就绪（本任务不代为重启）: %s" % health.get("detail")
        logger.warning("[vmax_daily] %s", msg)
        return {"success": False, "error": msg, "window": [last_time, end_time],
                "elapsed_seconds": round(time.time() - start, 2)}

    session = requests.Session()
    session.trust_env = False                                   # 强制直连本机 8790
    user_name = health.get("user") or ""
    store = _load_store()
    now_iso = datetime.now().isoformat(timespec="seconds")
    # 按 (monitorid, 过滤配方) 合批：把 50 个指标压成 8 个请求（实测单请求 14 列 0.06s）。
    # 既避免每小时打 50 次代理，也把 n 组串行槽位占用从 ~40s 降到 ~6s。
    groups, spec_ids = {}, {}
    for kpi_id, spec in KPI_SPECS.items():
        fm = spec.get("filter_model") or _FILTER_MODEL
        gkey = (spec["monitorid"], json.dumps(fm, sort_keys=True))
        groups.setdefault(gkey, {"monitorid": spec["monitorid"], "filter": fm, "codes": []})
        groups[gkey]["codes"].append(spec["code"])
        spec_ids.setdefault((gkey, spec["code"]), []).append(kpi_id)

    fetched, errors = {}, []
    net_fails = 0
    for gkey, grp in groups.items():
        codes = sorted(set(grp["codes"]))
        try:
            by_code = _fetch_batch(session, grp["monitorid"], codes, grp["filter"],
                                   user_name, last_time, end_time, period)
            net_fails = 0
            for code, rows in by_code.items():
                for kpi_id in spec_ids.get((gkey, code), []):
                    fetched[kpi_id] = _aggregate_rows(rows, KPI_SPECS[kpi_id], today_iso)
        except Exception as exc:                                # noqa: BLE001
            errors.append("mon%s[%s]: %s: %s" % (grp["monitorid"], ",".join(codes)[:70],
                                                 type(exc).__name__, str(exc)[:180]))
            logger.warning("[vmax_daily] monitor %s 批量拉取失败: %s", grp["monitorid"], exc)
            # 各分组共用同一上游/代理，连续 2 次网络类失败即判定上游不可用：立刻收工，
            # 不再占着 n 组串行槽位干等超时（实测 VMAX 中断期每次可等 90s）。
            if isinstance(exc, (requests.RequestException, TimeoutError, ConnectionError)):
                net_fails += 1
                if net_fails >= 2:
                    errors.append("aborted: 连续 %d 次网络失败，跳过剩余分组（上游/代理不可用）" % net_fails)
                    logger.warning("[vmax_daily] 上游连续不可用，提前结束本轮（已完成 %d/%d KPI）",
                                   len(fetched), len(KPI_SPECS))
                    break
        time.sleep(0.4)                                         # 单会话代理，别打太猛

    written, newest = _merge_days(store, fetched, now_iso)
    store["updated_at"] = now_iso
    store["last_window"] = {"last_time": last_time, "end_time": end_time, "days": lookback}
    try:
        _save_store(store)
    except Exception as exc:                                    # noqa: BLE001
        logger.exception("[vmax_daily] 日存落盘失败")
        return {"success": False, "error": "日存落盘失败: %s" % exc,
                "elapsed_seconds": round(time.time() - start, 2)}

    elapsed = round(time.time() - start, 2)
    result = {
        "success": written > 0,
        "kpi_fetched": len(fetched),
        "kpi_total": len(KPI_SPECS),
        "request_groups": len(groups),
        "rows_written": written,
        "stored_days": len(store["days"]),
        "newest_day": newest or max(store["days"], default=None),
        "oldest_day": min(store["days"], default=None),
        "window": [last_time, end_time],
        "errors": errors[:20],
        "elapsed_seconds": elapsed,
    }
    if not written:
        result["error"] = "本次没有任何 KPI 拿到可用数据（保留旧日值）"
    print("[vmax_daily] done in %ss: kpis=%s/%s groups=%s written=%s days=%s newest=%s errors=%s"
          % (elapsed, len(fetched), len(KPI_SPECS), len(groups), written, len(store["days"]),
             result["newest_day"], len(errors)))
    return result


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(run_vmax_cxo_daily_sync(), ensure_ascii=False, indent=2))
