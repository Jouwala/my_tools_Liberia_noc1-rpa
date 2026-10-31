# -*- coding: utf-8 -*-
"""SOC 多维趋势看板的指标定义与字典（与计算逻辑分离，见 soc_trend_service）。

这里集中维护三类事实，改口径只动本文件：
* 类目清单与可用维度（数据面实测结论的固化，来源见各常量注释）；
* 指标定义（名称/单位/口径来源计数器/告警不利方向）与各类目的指标清单；
* 告警规则参数（双基线阈值、规模地板、绝对百分点门槛）与指标字典 payload。
"""
from __future__ import annotations

from typing import Any, Dict, List

GIB = 1024.0 ** 3

# --------------------------------------------------------------------------
# 类目与维度（2026-10-30 数仓实测）
# --------------------------------------------------------------------------
CATS = ["flow", "video", "web", "game", "ottvoice", "ottvideo", "tcp", "control"]
# spservice 的 area_id 实测恒为 0（业务侧无区域归属），分业务类目只有全网维度；
# 区域/网元维度仅 flow 有（tcp 读 flow 行，见 SRC_CAT 别名）；
# app 维度 = 每类目流量 Top-N APP（spservice 的 subservice_id，dim=app，仅 5 个业务类目可用）。
CAT_DIMS: Dict[str, List[str]] = {
    "flow": ["total", "area", "ne"], "tcp": ["total", "area", "ne"],
    "video": ["total", "app"], "web": ["total", "app"], "game": ["total", "app"],
    "ottvoice": ["total", "app"], "ottvideo": ["total", "app"], "control": [],
}
# 类目 -> 落盘行来源（tcp 复用 flow 的 ciservice 行，指标清单不同）
SRC_CAT: Dict[str, str] = {"tcp": "flow"}
NEUTRAL_MEMBER = "0"                     # area=0 未归类成员

# --------------------------------------------------------------------------
# 指标定义：kind=sum 体积 / ratio 比率 / rate 推导速率；adverse=告警不利方向
# --------------------------------------------------------------------------
METRICS: Dict[str, Dict[str, Any]] = {
    "total_gb":  {"zh": "数据业务总流量", "en": "Total Data Traffic", "unit": "GB", "digits": 1,
                  "kind": "sum", "adverse": "drop", "source": "ppb400401001+ppb400401002"},
    "ul_gb":     {"zh": "上行流量", "en": "UL Traffic", "unit": "GB", "digits": 1,
                  "kind": "sum", "adverse": "drop", "source": "ppb400401001"},
    "dl_gb":     {"zh": "下行流量", "en": "DL Traffic", "unit": "GB", "digits": 1,
                  "kind": "sum", "adverse": "drop", "source": "ppb400401002"},
    "tput_mbps": {"zh": "平均下行速率", "en": "Avg DL Throughput", "unit": "Mbps", "digits": 0,
                  "kind": "rate", "adverse": "drop", "source": "ppb400401002 / 时长"},
    "video_tput_mbps": {"zh": "视频有效下载速率", "en": "Valid Video Throughput", "unit": "Mbps",
                        "digits": 1, "kind": "ratio", "adverse": "drop",
                        "source": "ppb400464018*8000 / (ppb400464051*1024*1024)"},
    "conn_rate": {"zh": "TCP连接成功率", "en": "TCP Conn Success Rate", "unit": "%", "digits": 2,
                  "kind": "ratio", "adverse": "drop", "source": "ppb400403021 / ppb400403020"},
    "rt_rate_ul": {"zh": "TCP重传率(上行)", "en": "TCP UL Retrans Rate", "unit": "%", "digits": 2,
                   "kind": "ratio", "adverse": "rise", "source": "ppb400403015 / ppb400403007"},
    "rt_rate_dl": {"zh": "TCP重传率(下行)", "en": "TCP DL Retrans Rate", "unit": "%", "digits": 2,
                   "kind": "ratio", "adverse": "rise", "source": "ppb400403016 / ppb400403008"},
    "dis_rate_ul": {"zh": "TCP乱序率(上行)", "en": "TCP UL Disorder Rate", "unit": "%", "digits": 2,
                    "kind": "ratio", "adverse": "rise", "source": "ppb400403013 / ppb400403007"},
    "dis_rate_dl": {"zh": "TCP乱序率(下行)", "en": "TCP DL Disorder Rate", "unit": "%", "digits": 2,
                    "kind": "ratio", "adverse": "rise", "source": "ppb400403014 / ppb400403008"},
    "loss_rate_ul": {"zh": "TCP丢包率(上行)", "en": "TCP UL Loss Rate", "unit": "%", "digits": 2,
                     "kind": "ratio", "adverse": "rise", "source": "ppb400403041 / ppb400403007"},
    "loss_rate_dl": {"zh": "TCP丢包率(下行)", "en": "TCP DL Loss Rate", "unit": "%", "digits": 2,
                     "kind": "ratio", "adverse": "rise", "source": "ppb400403042 / ppb400403008"},
    "rtt_ul": {"zh": "TCP RTT(上行)", "en": "TCP UL RTT", "unit": "ms", "digits": 1,
               "kind": "ratio", "adverse": "rise", "source": "ppb400403044 / ppb400403038"},
    "rtt_dl": {"zh": "TCP RTT(下行)", "en": "TCP DL RTT", "unit": "ms", "digits": 1,
               "kind": "ratio", "adverse": "rise", "source": "ppb400403045 / ppb400403039"},
}
# 每类目的指标清单（前端指标选择器与告警扫描共用）
CAT_METRICS: Dict[str, List[str]] = {
    "flow": ["total_gb", "ul_gb", "dl_gb", "tput_mbps", "conn_rate", "rt_rate_ul", "rt_rate_dl",
             "dis_rate_ul", "dis_rate_dl", "loss_rate_ul", "loss_rate_dl", "rtt_ul", "rtt_dl"],
    "tcp": ["total_gb", "conn_rate", "rt_rate_ul", "rt_rate_dl", "dis_rate_ul", "dis_rate_dl",
            "loss_rate_ul", "loss_rate_dl", "rtt_ul", "rtt_dl"],
    "video": ["total_gb", "ul_gb", "dl_gb", "video_tput_mbps", "conn_rate", "rt_rate_ul",
              "rt_rate_dl", "rtt_ul", "rtt_dl"],
    "web": ["total_gb", "ul_gb", "dl_gb", "conn_rate", "rt_rate_ul", "rt_rate_dl",
            "rtt_ul", "rtt_dl"],
    "game": ["total_gb", "ul_gb", "dl_gb", "conn_rate", "rt_rate_ul", "rt_rate_dl",
             "rtt_ul", "rtt_dl"],
    "ottvoice": ["total_gb", "ul_gb", "dl_gb", "conn_rate", "rt_rate_ul", "rt_rate_dl",
                 "rtt_ul", "rtt_dl"],
    "ottvideo": ["total_gb", "ul_gb", "dl_gb", "conn_rate", "rt_rate_ul", "rt_rate_dl",
                 "rtt_ul", "rtt_dl"],
    "control": [],
}
# 重大告警扫描的指标范围（其余指标只在趋势图可选）
ALARM_METRICS: Dict[str, List[str]] = {
    "flow": ["total_gb", "ul_gb", "dl_gb", "tput_mbps"],
    "tcp": ["conn_rate", "rt_rate_ul", "rt_rate_dl", "loss_rate_ul", "loss_rate_dl",
            "dis_rate_ul", "dis_rate_dl", "rtt_ul", "rtt_dl"],
    "video": ["total_gb", "ul_gb", "dl_gb", "video_tput_mbps"],
    "web": ["total_gb", "ul_gb", "dl_gb"], "game": ["total_gb", "ul_gb", "dl_gb"],
    "ottvoice": ["total_gb", "ul_gb", "dl_gb"], "ottvideo": ["total_gb", "ul_gb", "dl_gb"],
    "control": [],
}
# 体量类指标（可跨维度切片算贡献）；比率类不可加，不给贡献占比
VOLUME_METRICS = ("total_gb", "ul_gb", "dl_gb")

# --------------------------------------------------------------------------
# 告警规则参数（对齐原型看板：D-1 与 D-7 双基线同时越限）
# --------------------------------------------------------------------------
THRESH_CRIT = 20.0                       # Critical 阈值（%）
THRESH_MAJOR = 10.0                      # Major 阈值（%）
MIN_BASE_GB = 1.0                        # 体量类指标触发告警的基线规模地板（防长尾抖动）
MIN_DEN = 1000.0                         # 比率类指标的分母地板（包数/次数）
RATE_MIN_DELTA_PP = 0.2                  # % 类指标的绝对变化门槛（百分点），防小基数相对放大
DAY_TREND_DAYS = 30                      # 天粒度趋势图的回看天数

# 类目显示名与数据源说明（指标字典用）
_CAT_ZH = {"flow": "流量", "video": "视频", "web": "网页", "game": "游戏",
           "ottvoice": "OTT语音", "ottvideo": "OTT视频", "tcp": "TCP指标", "control": "控制面"}
_CAT_EN = {"flow": "Traffic", "video": "Video", "web": "Web", "game": "Game",
           "ottvoice": "OTT Voice", "ottvideo": "OTT Video", "tcp": "TCP KPI", "control": "Control Plane"}
_CAT_SERVICE = {"flow": "aggr_5gsa_flow_ciservice（全部业务）", "tcp": "aggr_5gsa_flow_ciservice",
                "video": "flow_spservice service_id=5 + video_spservice",
                "ottvideo": "flow_spservice service_id=23 (Video Live)",
                "web": "flow_spservice service_id=15 (Web Browse)",
                "game": "flow_spservice service_id=8 (Game)",
                "ottvoice": "flow_spservice service_id=13 (VoIP)", "control": "（数仓暂无数据）"}


def dict_payload() -> Dict[str, Any]:
    """指标字典：口径、来源计数器、适用类目、告警规则（前端「指标字典」弹窗数据源）。"""
    entries = []
    for mid, spec in METRICS.items():
        entries.append({
            "id": mid, "zh": spec["zh"], "en": spec["en"], "unit": spec["unit"],
            "digits": spec["digits"], "kind": spec["kind"], "adverse": spec["adverse"],
            "source": spec["source"],
            "cats": [c for c, ms in CAT_METRICS.items() if mid in ms],
        })
    return {
        "metrics": entries,
        "rules": {
            "alarm": "Critical ≥ ±20%，Major ≥ ±10%%；需 D-1 与 D-7 双基线同时越限；"
                     "体量/速率/成功率取下降、重传/乱序/丢包/RTT 取上升为不利方向",
            "contribution": "贡献按同一维度互斥切片计算，不同维度不累加；比率类指标不可加，不给贡献占比",
            "min_scale": "体量类基线 ≥ %.1f GB、比率类分母 ≥ %.0f、%% 类绝对变化 ≥ %.1f 个百分点"
                         % (MIN_BASE_GB, MIN_DEN, RATE_MIN_DELTA_PP),
            "granularity": "小时视图告警窗口 = 当日 00:00 至最后一个完整小时，与 D-1/D-7 同时段对比",
        },
        "cats": {c: {"zh": _CAT_ZH[c], "en": _CAT_EN[c], "service": _CAT_SERVICE[c]}
                 for c in CATS},
    }
