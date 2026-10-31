# -*- coding: utf-8 -*-
"""
tests/test_vmax_flow_xdr.py —— 「按分类流量」（XDR 用户面）离线自测
===================================================================

覆盖范围（默认全部离线，不需要 VMAX 网络）：
  1. service -> 页签分类映射（只有 Video / Web Browse / VoIP / OTT* 对得上页签）
  2. 分类合计：每个页签的 total_flux 与「流量」页签（全量）一致
  3. 指标聚合：TCP 时延 / RTT / 重传率 / 乱序率 的算法（含除零保护）
  4. 应用聚合：同名应用合并、上下行流量求和、占比排序
  5. 视频专表指标：MOS 平均 / 分辨率分布 / 成功率
  6. 坏分区边界：end 往后挪 1 分钟（上游 end 落在 :45 会整段查不到）
  7. 取数上限：最多 8 页 × 200 条

用法：
    cd D:/01_RPA/Task/my_app
    python tests/test_vmax_flow_xdr.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.vmax_cca.vmax_flow_from_xdr import (   # noqa: E402
    CATEGORY_KEYS, VmaxFlowFromXdr, _fmt_bytes_kb, _fmt_packets,
)

PASS = 0
FAIL = 0
FAILED_NAMES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        FAILED_NAMES.append(name)
        print("  [FAIL] %s %s" % (name, detail))


def section(title):
    print("\n=== %s ===" % title)


def row(service, app="APP", subservice="SUB", **kw):
    """构造一条上游用户面话单（字段名与 fact_5gsa_psup_flow 一致）。"""
    base = {
        "service": service,
        "subservice": subservice,
        "app_content_name": app,
        "protocol": "TCP",
        "ul_traffic": "0",
        "dl_traffic": "0",
        "ul_pkt": "0",
        "dl_pkt": "0",
        "duration": "0",
        "tcp_resp_delay": "0",
        "tcp_ack_delay": "0",
        "ul_avg_rtt": "0",
        "dl_avg_rtt": "0",
        "ul_retrans_pkt": "0",
        "dl_retrans_pkt": "0",
        "ul_disorder_pkt": "0",
        "dl_disorder_pkt": "0",
        "ul_throughput_max": "0",
        "dl_throughput_max": "0",
    }
    base.update({k: str(v) for k, v in kw.items()})
    return base


svc = VmaxFlowFromXdr(None)

# ---------------------------------------------------------------------------
section("1. service -> 页签分类映射")
# ---------------------------------------------------------------------------
check("Video -> video",
      svc._categorize(row("Video")) == "video")
check("Web Browse -> web",
      svc._categorize(row("Web Browse")) == "web")
check("VoIP -> ottvoice",
      svc._categorize(row("VoIP")) == "ottvoice")
check("OTT VIDEO -> ottvideo",
      svc._categorize(row("OTT VIDEO")) == "ottvideo")
check("OTT VOICE -> ottvoice",
      svc._categorize(row("OTT VOICE")) == "ottvoice")
# 应用类业务不该硬塞进页签
for s in ("Social", "IM", "Shopping", "eMail", "Network Storage",
          "Public Traffic", "Comm Traffic", "Others"):
    check("%s -> others（应用类业务不臆造分类）" % s,
          svc._categorize(row(s)) == "others")
# service 为空时按 subservice 兜底
check("service 空 + subservice 含 OTT/VIDEO -> ottvideo",
      svc._categorize(row("", subservice="OTT_VIDEO")) == "ottvideo")
check("service 空 + 游戏应用名 -> game",
      svc._categorize(row("", subservice="PUBG_MOBILE")) == "game")

# ---------------------------------------------------------------------------
section("2. 应用聚合：同名合并 + 上下行求和 + 占比")
# ---------------------------------------------------------------------------
rows = [
    row("Video", app="FACEBOOK_VIDEO", ul_traffic=100, dl_traffic=900),
    row("Video", app="FACEBOOK_VIDEO", ul_traffic=50, dl_traffic=50),
    row("Web Browse", app="YOUTUBEWEB", ul_traffic=200, dl_traffic=800),
    row("Public Traffic", app="QUIC", ul_traffic=10, dl_traffic=10),
]
items = svc._normalize(rows)
check("同名应用合并成一项", len(items) == 3, "得到 %d 项" % len(items))
fb = next(i for i in items if i["app_name"] == "FACEBOOK_VIDEO")
check("合并后上行流量 = 150", fb["ul_traffic"] == 150.0, str(fb["ul_traffic"]))
check("合并后下行流量 = 950", fb["dl_traffic"] == 950.0, str(fb["dl_traffic"]))
check("合并后记录数 = 2", fb["records"] == 2, str(fb["records"]))

cats = svc.aggregate_categories(items, [])
all_cat = next(c for c in cats if c["key"] == "all")
check("「流量」页签含全部应用", len(all_cat["apps"]) == 3, str(len(all_cat["apps"])))
check("「流量」页签合计非零（曾因 by_cat 无 all 键而算成 0）",
      all_cat["total_flux_kb"] > 0, str(all_cat["total_flux_kb"]))
# 合计应等于各应用之和
manual = sum(a["total_traffic_kb"] for a in all_cat["apps"])
check("合计与逐应用之和一致",
      abs(all_cat["total_flux_kb"] - manual) < 0.01,
      "%s vs %s" % (all_cat["total_flux_kb"], manual))
# 按流量降序
traffics = [a["total_traffic_kb"] for a in all_cat["apps"]]
check("应用按流量降序", traffics == sorted(traffics, reverse=True), str(traffics))
# 占比
fb_row = next(a for a in all_cat["apps"] if a["app_name"] == "FACEBOOK_VIDEO")
check("占比在 0~100 之间",
      fb_row["ratio"].endswith("%") and 0 < float(fb_row["ratio"][:-1]) <= 100,
      fb_row["ratio"])

# ---------------------------------------------------------------------------
section("3. 分类页签合计 = 该类应用之和")
# ---------------------------------------------------------------------------
video_cat = next(c for c in cats if c["key"] == "video")
video_manual = sum(a["total_traffic_kb"] for a in video_cat["apps"])
check("「视频」页签合计 = 其应用之和",
      abs(video_cat["total_flux_kb"] - video_manual) < 0.01,
      "%s vs %s" % (video_cat["total_flux_kb"], video_manual))
check("「视频」页签只含 video 类应用",
      all(a["category"] == "video" for a in video_cat["apps"]))
web_cat = next(c for c in cats if c["key"] == "web")
check("「网页」页签只含 web 类应用",
      all(a["category"] == "web" for a in web_cat["apps"]))

# ---------------------------------------------------------------------------
section("4. 指标聚合（TCP / 控制面）")
# ---------------------------------------------------------------------------
kpi_rows = [
    row("Public Traffic", app="A", ul_traffic=100, dl_traffic=100,
        ul_pkt=100, dl_pkt=100, tcp_resp_delay=100, tcp_ack_delay=50,
        ul_avg_rtt=80, dl_avg_rtt=40, ul_retrans_pkt=10, dl_retrans_pkt=5,
        ul_disorder_pkt=2, dl_disorder_pkt=1, duration=1000,
        ul_throughput_max=5000, dl_throughput_max=9000),
    row("Public Traffic", app="A", ul_traffic=100, dl_traffic=100,
        ul_pkt=100, dl_pkt=100, tcp_resp_delay=300, tcp_ack_delay=150,
        ul_avg_rtt=120, dl_avg_rtt=80, ul_retrans_pkt=10, dl_retrans_pkt=5,
        ul_disorder_pkt=2, dl_disorder_pkt=1, duration=1000,
        ul_throughput_max=7000, dl_throughput_max=4000),
]
kpi_items = svc._normalize(kpi_rows)
kpi_cats = svc.aggregate_categories(kpi_items, [])
kpis = {k["name"]: k for k in next(c for c in kpi_cats if c["key"] == "all")["kpis"]}

check("TCP 握手响应时延 = (100+300)/2 = 200",
      kpis["TCP 握手响应时延(平均)"]["value"] == "200.0",
      kpis["TCP 握手响应时延(平均)"]["value"])
check("上行 RTT = (80+120)/2 = 100",
      kpis["上行 RTT(平均)"]["value"] == "100.0",
      kpis["上行 RTT(平均)"]["value"])
check("上行重传包数 = 20", kpis["上行重传包数"]["value"] == "20",
      kpis["上行重传包数"]["value"])
# 重传率 = (上行 20 + 下行 10) / 总包数 400 = 7.500%
check("重传率 = 7.500%",
      kpis["重传率"]["value"] == "7.500%", kpis["重传率"]["value"])
# 乱序率 = (上行 4 + 下行 2) / 400 = 1.500%
check("乱序率 = 1.500%",
      kpis["乱序率"]["value"] == "1.500%", kpis["乱序率"]["value"])
check("上行峰值速率取最大值 = 7000",
      kpis["上行峰值速率"]["value"] == "7000", kpis["上行峰值速率"]["value"])
check("会话总时长 = 2000ms = 2.0s",
      kpis["会话总时长"]["value"] == "2.0", kpis["会话总时长"]["value"])

# TCP 页签只给 TCP 相关指标、且无应用列表
tcp_cat = next(c for c in kpi_cats if c["key"] == "tcp")
check("「TCP指标」页签无应用列表", tcp_cat["apps"] == [])
check("「TCP指标」页签含重传率", any("重传率" in k["name"] for k in tcp_cat["kpis"]))
check("「TCP指标」页签不含峰值速率（那属控制面）",
      not any("峰值速率" in k["name"] for k in tcp_cat["kpis"]))
ctrl_cat = next(c for c in kpi_cats if c["key"] == "control")
check("「控制面」页签无应用列表", ctrl_cat["apps"] == [])
check("「控制面」页签含峰值速率", any("峰值速率" in k["name"] for k in ctrl_cat["kpis"]))

# ---------------------------------------------------------------------------
section("5. 除零保护（无包数时不应崩）")
# ---------------------------------------------------------------------------
empty_items = svc._normalize([row("Others", app="X")])
empty_cats = svc.aggregate_categories(empty_items, [])
empty_kpis = {k["name"]: k for k in empty_cats[0]["kpis"]}
check("无包数时重传率为 —", empty_kpis["重传率"]["value"] == "—",
      empty_kpis["重传率"]["value"])
check("无包数时乱序率为 —", empty_kpis["乱序率"]["value"] == "—")
check("无数据时总流量为 0 KB", empty_cats[0]["total_flux"] == "0 KB",
      empty_cats[0]["total_flux"])
check("空占比显示 —", empty_cats[0]["apps"][0]["ratio"] == "—",
      empty_cats[0]["apps"][0]["ratio"])

# ---------------------------------------------------------------------------
section("6. 视频专表指标")
# ---------------------------------------------------------------------------
video_rows = [
    row("Video", app="YOUTUBE", vmos="0.9000", resolution="1080P", result="succeed"),
    row("Video", app="YOUTUBE", vmos="0.7000", resolution="480P", result="fail"),
    row("Video", app="YOUTUBE", vmos="0", resolution="Other", result="succeed"),
]
v_cats = svc.aggregate_categories(svc._normalize([]), video_rows)
v_cat = next(c for c in v_cats if c["key"] == "video")
vk = {k["name"]: k for k in v_cat["kpis"]}
check("视频页签带 MOS 指标", "视频 MOS(平均)" in vk, str(list(vk)))
check("MOS 平均排除 0 值 = (0.9+0.7)/2 = 0.8000",
      vk["视频 MOS(平均)"]["value"] == "0.8000", vk["视频 MOS(平均)"]["value"])
check("会话成功率 = 2/3 = 66.7%",
      vk["视频会话成功率"]["value"] == "66.7%", vk["视频会话成功率"]["value"])
check("分辨率分布只统计已知分辨率",
      "1080P" in vk["主要分辨率"]["value"], vk["主要分辨率"]["value"])

# ---------------------------------------------------------------------------
section("7. 坏分区边界：end 往后挪 1 分钟")
# ---------------------------------------------------------------------------
class FakeXdr:
    """记录 query_table 收到的参数。"""

    def __init__(self):
        self.calls = []

    def query_table(self, msisdn, svc_type, table, start, end, page=1, page_size=20):
        self.calls.append({"msisdn": msisdn, "service_type": svc_type, "table": table,
                           "start": start, "end": end, "page": page, "page_size": page_size})
        return {"records": 0, "rows": []}


fake = FakeXdr()
VmaxFlowFromXdr(fake).query("231777777322", "2026-10-30 14:00:00", "2026-10-30 17:45:00")
flow_call = next(c for c in fake.calls if c["table"] == "fact_5gsa_psup_flow")
check("end 被挪到 17:46:00（避开 :45 坏分区）",
      flow_call["end"].startswith("2026-10-30 17:46:00"), flow_call["end"])
check("start 不变", flow_call["start"] == "2026-10-30 14:00:00.000", flow_call["start"])
check("查询的是用户面 flow 表",
      flow_call["table"] == "fact_5gsa_psup_flow", flow_call["table"])
check("serviceType 是 1300", flow_call["service_type"] == "1300",
      flow_call["service_type"])

# ---------------------------------------------------------------------------
section("8. 取数上限：最多 8 页")
# ---------------------------------------------------------------------------
class ManyRowsXdr(FakeXdr):
    def query_table(self, *a, **kw):
        self.calls.append(kw)
        # 每页都满，返回 200 条
        return {"records": 100000, "rows": [row("Others", app="X%d" % i) for i in range(200)]}


many = ManyRowsXdr()
VmaxFlowFromXdr(many).query("231777777322", "2026-10-30 14:00:00", "2026-10-30 18:00:00")
flow_pages = [c for c in many.calls if c.get("table") == "fact_5gsa_psup_flow"]
check("翻页不超过 8 页", len(flow_pages) <= 8, "翻了 %d 页" % len(flow_pages))

# ---------------------------------------------------------------------------
section("9. 单位格式化")
# ---------------------------------------------------------------------------
check("KB < 1024 显示 KB", _fmt_bytes_kb(512) == "512.00 KB", _fmt_bytes_kb(512))
check("MB 换算", _fmt_bytes_kb(2048) == "2.00 MB", _fmt_bytes_kb(2048))
check("GB 换算", _fmt_bytes_kb(2 * 1024 * 1024) == "2.00 GB",
      _fmt_bytes_kb(2 * 1024 * 1024))
check("0 显示 0 KB", _fmt_bytes_kb(0) == "0 KB")
check("包数过万显示万", _fmt_packets(25000) == "2.50 万", _fmt_packets(25000))
check("包数不足万显示整数", _fmt_packets(250) == "250", _fmt_packets(250))

# ---------------------------------------------------------------------------
section("10. 页签 key 集合")
# ---------------------------------------------------------------------------
check("8 个页签且顺序固定",
      CATEGORY_KEYS == ["all", "video", "web", "game", "ottvoice", "ottvideo",
                        "tcp", "control"], str(CATEGORY_KEYS))

# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("通过 %d / 失败 %d" % (PASS, FAIL))
if FAILED_NAMES:
    print("失败用例：")
    for n in FAILED_NAMES:
        print("  - %s" % n)
    sys.exit(1)
print("全部通过")
