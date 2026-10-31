# -*- coding: utf-8 -*-
"""OLIB SOC 看板 KPI 库（daily_kpi）离线测试 —— 不连 GBase、不连门户。

覆盖：
    1. 指标字典自检（唯一 id / 分组 / 单位 / 方向 / 聚合方式）
    2. 建表 + upsert 幂等 + 日期主键归一
    3. 单日派生口径（TB→GB、用户→K、占比现算）
    4. 周汇总口径（流量求和 / 比率按分子分母精确加权 / 速率按流量加权）
    5. 极值语义（max/min 恒为算术极值，better 只影响配色）
    6. 周同比 / 月同比（与 7 天前、28 天前比）
    7. 窗口口径（只看已完成日）与缺口清单
    8. 空库/无表时的友好空态
    9. extract_daily_kpi：从各块结果帧抽取日粒度 KPI
   10. run_olib_soc_kpi_sync：只补缺的天、无缺口零查询、自愈、force 重取
   11. 五个只读接口 /overview /status /days /app-offload /video-apps /game-apps
   12. 配置、任务注册、页面与前端接线
   13. 单位换算与库位置不变量
   14. 视频 / 游戏逐 APP 明细下钻（明细层 olib_soc_app_detail）

跑法：
    python tests/test_olib_soc_kpi_store.py             # 离线（默认）
    python tests/test_olib_soc_kpi_store.py --live      # 额外核对真实 KPI 库
"""
import json
import re
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                                        # noqa: BLE001
    pass

import pandas as pd                                                      # noqa: E402

from backend.services.olib_soc_report import olib_soc_app_detail as det              # noqa: E402
from backend.services.olib_soc_report import olib_soc_kpi_store as kpi          # noqa: E402
from backend.services.olib_soc_report import olib_soc_report_service as svc     # noqa: E402
from backend.services.vmax_gbase import vmax_gbase_client as vgc                # noqa: E402
from backend.routers import olib_soc_dashboard as dash                          # noqa: E402

LIVE = "--live" in sys.argv
ROOT = Path(__file__).resolve().parents[1]
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


def close(a, b, tol=1e-6):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def _tmp_db():
    return Path(tempfile.mkdtemp(prefix="olib_kpi_test_")) / "kpi.sqlite3"


def _row(day, **over):
    """一天的最小完整原始行（可覆盖任意列）。"""
    base = {
        "day": day, "traffic_tb": 200.0, "active_user": 500000, "video_tb": 140.0,
        "video_mbps": 13.0, "cache_tb": 70.0, "noncache_tb": 130.0, "tcp_tb": 200.0,
        "tcp_success_pct": 91.0, "tcp_ul_retrans_pct": 1.0, "tcp_dl_retrans_pct": 2.0,
        "tcp_ul_rtt_ms": 90.0, "tcp_dl_rtt_ms": 170.0, "game_tb": 5.0,
        "top_service": "Video", "top_service_tb": 140.0, "blocks_ok": 7,
        "suspect_json": None, "run_id": "test", "updated_at": "2026-09-16 02:20:00",
    }
    base.update(over)
    return base


def _cards(path, days=7, today=date(2026, 9, 16)):
    body = kpi.build_overview(days=days, path=path, today=today)
    return body, {c["id"]: c for c in body["cards"]}


# ==========================================================================
section("1. 指标字典自检")
# ==========================================================================
ids = [m["id"] for m in kpi.METRICS]
check("指标 id 唯一", len(ids) == len(set(ids)), str(ids))
check("指标数量 = 10（4 主 + 3 业务 + 3 质量）", len(kpi.METRICS) == 10, str(len(kpi.METRICS)))
check("CEO 主卡片 = 4 个", len(kpi.PRIMARY_IDS) == 4, str(kpi.PRIMARY_IDS))
check("主卡片含用户点名的三项",
      all(x in kpi.PRIMARY_IDS for x in ("traffic_gb", "active_user_k", "video_thr_kbps")),
      str(kpi.PRIMARY_IDS))
check("业务/质量分组完整（各 3 个）",
      len([m for m in kpi.METRICS if m["group"] == "business"]) == 3
      and len([m for m in kpi.METRICS if m["group"] == "quality"]) == 3)
check("better 取值合法", all(m["better"] in ("up", "down", "flat") for m in kpi.METRICS))
check("每个指标都有中英标题", all(m.get("title") and m.get("title_en") for m in kpi.METRICS))
check("聚合方式合法",
      all(str(m["agg_week"]).split(":")[0] in ("sum", "mean", "wavg", "ratio")
          for m in kpi.METRICS))
check("比率类指标都带分子分母",
      all(m.get("num") and m.get("den") for m in kpi.METRICS if m["agg_week"] == "ratio"))
check("加权指标的权重列在库内",
      all(m["agg_week"].split(":")[1] in kpi.RAW_COLUMNS
          for m in kpi.METRICS if str(m["agg_week"]).startswith("wavg:")))
check("卡片都带中英口径说明", all(m.get("note") and m.get("note_en") for m in kpi.METRICS))

# ==========================================================================
section("2. 建表 + upsert 幂等 + 日期归一")
# ==========================================================================
db = _tmp_db()
check("未建库时 table_exists=False", kpi.table_exists(db) is False)
check("首次写入 2 天", kpi.upsert_days([_row("2026-09-14"),
                                        _row("2026-09-15", traffic_tb=260.0)], path=db) == 2)
check("建表后 table_exists=True", kpi.table_exists(db) is True)
check("stored_days 升序", kpi.stored_days(db) == ["2026-09-14", "2026-09-15"],
      str(kpi.stored_days(db)))
check("重复写同一天不再新增行",
      kpi.upsert_days([_row("2026-09-15", traffic_tb=260.0, video_tb=182.0,
                            cache_tb=91.0, noncache_tb=169.0)], path=db) == 1
      and len(kpi.stored_days(db)) == 2)
check("同一天的值被覆盖（upsert 生效）",
      close(kpi.fetch_range("2026-09-15", "2026-09-15", path=db)[0]["traffic_tb"], 260.0))
check("空列表写入返回 0", kpi.upsert_days([], path=db) == 0)
check("缺 day 的行被忽略", kpi.upsert_days([{"traffic_tb": 1.0}], path=db) == 0)
check("fetch_range 闭区间", len(kpi.fetch_range("2026-09-14", "2026-09-15", path=db)) == 2)
check("写入 YYYYMMDD 自动归一（防范围查询漏天）",
      kpi.upsert_days([_row("20260913")], path=db) == 1
      and "2026-09-13" in kpi.stored_days(db), str(kpi.stored_days(db)))
check("归一后范围查询查得到", len(kpi.fetch_range("20260913", "20260913", path=db)) == 1)
_keep = kpi.fetch_range("2026-09-14", "2026-09-14", path=db)[0]
kpi.upsert_days([{"day": "2026-09-14", "game_tb": 9.0}], path=db)       # 只跑一个块的部分补数
_patched = kpi.fetch_range("2026-09-14", "2026-09-14", path=db)[0]
check("部分块补数不清空其它列（COALESCE 补丁式更新）",
      close(_patched["traffic_tb"], _keep["traffic_tb"]) and close(_patched["game_tb"], 9.0),
      "%s / %s" % (_patched["traffic_tb"], _patched["game_tb"]))
kpi.upsert_days([_row("2026-09-14")], path=db)                          # 显式给新值
check("显式给新值时照常覆盖",
      close(kpi.fetch_range("2026-09-14", "2026-09-14", path=db)[0]["game_tb"], 5.0))
check("iso_day 兼容多种写法",
      (kpi.iso_day("20260915"), kpi.iso_day("2026/09/15"), kpi.iso_day("2026.09.15T10:00:00"),
       kpi.iso_day(date(2026, 9, 15)), kpi.iso_day(datetime(2026, 9, 15, 8, 0))) ==
      ("2026-09-15",) * 5, str(kpi.iso_day("2026/09/15")))
kpi.upsert_days([_row("2026-09-13")], path=db)          # 还原成 3 天窗口

# ==========================================================================
section("3. 单日派生口径")
# ==========================================================================
body, cards = _cards(db)
check("状态 ok", body["status"] == "ok", str(body.get("status")))
check("卡片数与指标数一致", len(cards) == len(kpi.METRICS), str(len(cards)))
check("总流量 TB→GB（260×1024）",
      close(cards["traffic_gb"]["latest"]["value"], 260 * 1024),
      str(cards["traffic_gb"]["latest"]["value"]))
check("活跃用户→K（500000→500.0）",
      close(cards["active_user_k"]["latest"]["value"], 500.0))
check("视频占比现算（182/260=70%）",
      close(cards["video_share_pct"]["latest"]["value"], 70.0),
      str(cards["video_share_pct"]["latest"]["value"]))
check("缓存占比现算（91/260=35%）",
      close(cards["cache_ratio_pct"]["latest"]["value"], 35.0),
      str(cards["cache_ratio_pct"]["latest"]["value"]))
check("视频速率 Mbps→kbps（13→13000）",
      close(cards["video_thr_kbps"]["latest"]["value"], 13000.0))
check("零分母为 None", kpi._metric_day_value(
    kpi.METRIC_BY_ID["video_share_pct"], _row("2026-09-15", traffic_tb=0.0)) is None)
check("缺值为 None", kpi._metric_day_value(
    kpi.METRIC_BY_ID["cache_ratio_pct"], _row("2026-09-15", cache_tb=None)) is None)
check("游戏流量卡片有值", cards["game_tb"]["latest"]["value"] == 5.0)

# ==========================================================================
section("4. 周汇总口径")
# ==========================================================================
db2 = _tmp_db()
days9 = vgc.day_range("2026-09-07", "2026-09-15")       # 一整周(09-07~13) + 2 天(09-14~15)
kpi.upsert_days([_row(d, traffic_tb=100.0, video_tb=60.0, cache_tb=30.0, noncache_tb=70.0,
                      active_user=400000, video_mbps=10.0, tcp_tb=100.0,
                      tcp_success_pct=90.0, tcp_dl_retrans_pct=2.0, tcp_dl_rtt_ms=150.0)
                 for d in days9], path=db2)
body2 = kpi.build_overview(days=30, path=db2, today=date(2026, 9, 16))
wk = body2["series"]["week"]
check("周标签为 ISO 周", wk["labels"] == ["2026-W37", "2026-W38"], str(wk["labels"]))
check("周起始为周一", wk["mondays"] == ["2026-09-07", "2026-09-14"], str(wk["mondays"]))
check("最后一周天数被标注（7/2）", wk["days"] == [7, 2], str(wk["days"]))
check("流量周汇总=求和（7×102400）", close(wk["values"]["traffic_gb"][0], 7 * 100.0 * 1024))
check("活跃用户周汇总=均值", close(wk["values"]["active_user_k"][0], 400.0))
check("比率周汇总=分子分母精确加权（60/100）",
      close(wk["values"]["video_share_pct"][0], 60.0))
check("速率周汇总=按视频流量加权", close(wk["values"]["video_thr_kbps"][0], 10000.0))
db3 = _tmp_db()
kpi.upsert_days([_row("2026-09-14", video_mbps=10.0, video_tb=90.0),
                 _row("2026-09-15", video_mbps=20.0, video_tb=10.0)], path=db3)
w3 = kpi.build_overview(days=7, path=db3, today=date(2026, 9, 16))["series"]["week"]["values"]
check("加权平均=(10×90+20×10)/100=11000kbps", close(w3["video_thr_kbps"][0], 11000.0),
      str(w3["video_thr_kbps"][0]))
check("不是简单平均（否则 15000）", not close(w3["video_thr_kbps"][0], 15000.0))
check("空周不炸", kpi._metric_agg_value(kpi.METRIC_BY_ID["video_share_pct"], []) is None)
check("全零分母返回 None", kpi._metric_agg_value(
    kpi.METRIC_BY_ID["video_share_pct"], [_row("2026-09-15", traffic_tb=0.0)]) is None)

# ==========================================================================
section("5. 极值语义（max/min 恒为算术极值）")
# ==========================================================================
db4 = _tmp_db()
kpi.upsert_days([_row("2026-09-13", tcp_dl_retrans_pct=2.5),
                 _row("2026-09-14", tcp_dl_retrans_pct=1.2),
                 _row("2026-09-15", tcp_dl_retrans_pct=2.0)], path=db4)
_, c4 = _cards(db4)
r = c4["tcp_dl_retrans_pct"]
check("越小越好时 max 仍是最大重传率 2.5", close(r["max"]["value"], 2.5), str(r["max"]["value"]))
check("越小越好时 min 仍是最小重传率 1.2", close(r["min"]["value"], 1.2), str(r["min"]["value"]))
check("极值带日期", r["max"]["date"] == "2026-09-13" and r["min"]["date"] == "2026-09-14")
check("平均为算术平均（1.9）", close(r["avg"], 1.9), str(r["avg"]))
check("n = 参与统计天数", r["n"] == 3, str(r["n"]))
check("稀疏指标只统计有值的天", c4["game_tb"]["n"] == 3, str(c4["game_tb"]["n"]))
check("卡片带迷你走势", isinstance(c4["traffic_gb"]["spark"], list)
      and len(c4["traffic_gb"]["spark"]) == 3)
check("空库趋势序列为空", kpi.build_overview(
    days=90, path=_tmp_db(), today=date(2026, 9, 16))["series"]["day"] == {})

# ==========================================================================
section("6. 周同比 / 月同比")
# ==========================================================================
db5 = _tmp_db()
kpi.upsert_days([_row("2026-08-18", traffic_tb=100.0),               # 28 天前
                 _row("2026-09-08", traffic_tb=200.0, game_tb=None),  # 7 天前（缺游戏值）
                 _row("2026-09-15", traffic_tb=220.0)], path=db5)
_, c5 = _cards(db5, days=90)
t5 = c5["traffic_gb"]
check("周同比 +10%", close(t5["wow_pct"], 10.0), str(t5.get("wow_pct")))
check("月同比 +120%", close(t5["mom_pct"], 120.0), str(t5.get("mom_pct")))
check("同比基数日期正确", t5["wow_base"]["date"] == "2026-09-08"
      and t5["mom_base"]["date"] == "2026-08-18")
check("基数当天没有该指标值时不编造同比", c5["game_tb"].get("wow_pct") is None,
      str(c5["game_tb"].get("wow_pct")))

# ==========================================================================
section("7. 窗口口径与缺口清单")
# ==========================================================================
db6 = _tmp_db()
kpi.upsert_days([_row("2026-09-14"), _row("2026-09-15"),
                 _row("2026-09-16", traffic_tb=1.0)], path=db6)
b6 = kpi.build_overview(days=7, path=db6, today=date(2026, 9, 16))
check("窗口结束于昨天", b6["window"]["end"] == "2026-09-15", str(b6["window"]))
check("窗口起点=结束-6 天（窗口下限 7 天）", b6["window"]["begin"] == "2026-09-09",
      str(b6["window"]))
check("今天的数据不进卡片/趋势",
      all(d != "2026-09-16" for d in b6["series"]["day"]["dates"]))
check("缺口天数被列出", b6["coverage"]["missing_days"] ==
      ["2026-09-09", "2026-09-10", "2026-09-11", "2026-09-12", "2026-09-13"],
      str(b6["coverage"]["missing_days"]))
check("expected/stored 正确", b6["coverage"]["expected_days"] == 7
      and b6["coverage"]["stored_days"] == 2, json.dumps(b6["coverage"]))
check("as_of = 最新完整日", b6["as_of"] == "2026-09-15", str(b6.get("as_of")))
check("gap_days 只给缺的日期", kpi.gap_days(5, path=db6, today=date(2026, 9, 16)) ==
      ["2026-09-11", "2026-09-12", "2026-09-13"])
check("齐全时 gap_days 为空", kpi.gap_days(2, path=db6, today=date(2026, 9, 16)) == [])
# 事故回归（2026-09-24）：行在但关键指标为 NULL 的天，gap_days 看不见，必须靠
# incomplete_days 捞出来，否则 NULL 会永久残留（当时 active_user 连丢 6 天）。
db6c = _tmp_db()
kpi.upsert_days([_row("2026-09-12", active_user=None), _row("2026-09-14"),
                 _row("2026-09-15", active_user=None)], path=db6c)
check("残缺失格的天不算 gap_days 的缺口（这就是旧逻辑漏掉的原因）",
      kpi.gap_days(2, path=db6c, today=date(2026, 9, 16)) == [])
check("incomplete_days 能抓出关键指标为 NULL 的天",
      kpi.incomplete_days(2, path=db6c, today=date(2026, 9, 16)) == ["2026-09-15"],
      str(kpi.incomplete_days(2, path=db6c, today=date(2026, 9, 16))))
check("数据齐全时 incomplete_days 为空",
      kpi.incomplete_days(2, path=db6c, today=date(2026, 9, 15)) == [])
check("流量为 NULL 同样算残缺", kpi.incomplete_days(
    2, path=(lambda p: (kpi.upsert_days([_row("2026-09-15", traffic_tb=None)], path=p), p)[1])(
        _tmp_db()), today=date(2026, 9, 16)) == ["2026-09-15"])
# 09-12 那天也残缺，但 days_back=2 的窗口只覆盖 09-14~09-15，不该把它带出来
check("窗口外的残缺日不返回（09-12 在窗口外）",
      kpi.incomplete_days(2, path=db6c, today=date(2026, 9, 16)) == ["2026-09-15"]
      and "2026-09-12" in kpi.incomplete_days(6, path=db6c, today=date(2026, 9, 16)),
      str(kpi.incomplete_days(6, path=db6c, today=date(2026, 9, 16))))
check("days 上限 400", kpi.build_overview(
    days=9999, path=db6, today=date(2026, 9, 16))["window_days"] == 400)
check("days 下限 7", kpi.build_overview(
    days=1, path=db6, today=date(2026, 9, 16))["window_days"] == 7)
check("quality 列表结构正确", isinstance(b6["quality"], list))
db6b = _tmp_db()
kpi.upsert_days([_row("2026-09-15", suspect_json=[
    {"day": "20260915", "metric": "Active_user_cnt", "value": 401, "median": 480000,
     "ratio": 0.001, "block": "active_user"}])], path=db6b)
q6 = kpi.build_overview(days=7, path=db6b, today=date(2026, 9, 16))["quality"]
check("质量标记以 ISO 日期返回（不被条目自带的 YYYYMMDD 覆盖）",
      len(q6) == 1 and q6[0]["day"] == "2026-09-15", str(q6))
check("质量标记带块名与指标", bool(q6) and q6[0].get("block") == "active_user"
      and q6[0].get("metric") == "Active_user_cnt", str(q6))
check("suspect_json 解析失败也不炸", kpi.build_overview(
    days=7, path=(lambda p: (kpi.upsert_days([_row("2026-09-15", suspect_json="{坏JSON")], path=p),
                             p)[1])(_tmp_db()), today=date(2026, 9, 16))["quality"] == [])

# ==========================================================================
section("8. 空库/无表的友好空态")
# ==========================================================================
missing = Path(tempfile.mkdtemp(prefix="olib_kpi_none_")) / "nope.sqlite3"
empty = kpi.build_overview(days=90, path=missing, today=date(2026, 9, 16))
check("文件不存在 → empty（不是 error）", empty["status"] == "empty", str(empty["status"]))
check("空态带提示语", bool(empty.get("message")), str(empty.get("message")))
check("空态也带指标字典（前端可渲染骨架）", len(empty["metrics"]) == 10)
db7 = _tmp_db()
with sqlite3.connect(str(db7)) as conn:
    conn.execute("CREATE TABLE other(x int)")
    conn.commit()
check("库在但没表 → 也是 empty",
      kpi.build_overview(days=90, path=db7, today=date(2026, 9, 16))["status"] == "empty")
check("stored_days 对不存在的库返回空", kpi.stored_days(missing) == [])
check("fetch_range 对不存在的库返回空",
      kpi.fetch_range("2026-01-01", "2026-12-31", path=missing) == [])
check("只读连接开启 query_only",
      kpi.connect(db7, readonly=True).execute("PRAGMA query_only").fetchone()[0] == 1)

# ==========================================================================
section("9. extract_daily_kpi：从各块结果帧抽取日粒度 KPI")
# ==========================================================================
def _frames():
    """构造与真实 SQL 同列名的结果帧（两天，视频两家 APP）。"""
    d1, d2 = datetime(2026, 9, 14), datetime(2026, 9, 15)
    return {
        "traffic": {"frame": pd.DataFrame([
            {"clttime": d1, "Total_traffic_TB": 100.0},
            {"clttime": d2, "Total_traffic_TB": 200.0}])},
        "active_user": {"frame": pd.DataFrame([
            {"clttime": d1, "Active_user_cnt": 400000},
            {"clttime": d2, "Active_user_cnt": 500000}]),
            "suspect_days": [{"day": "20260915", "metric": "Active_user_cnt", "value": 401,
                              "median": 480000, "ratio": 0.001}]},
        "video": {"frame": pd.DataFrame([
            {"clttime": d1, "appname": "TIKTOK", "Total_traffic_TB": 30.0,
             "Valid_video_download_throughput_Mbps": 10.0},
            {"clttime": d1, "appname": "YOUTUBE", "Total_traffic_TB": 10.0,
             "Valid_video_download_throughput_Mbps": 30.0},
            {"clttime": d2, "appname": "TIKTOK", "Total_traffic_TB": 140.0,
             "Valid_video_download_throughput_Mbps": 12.0},
            {"clttime": d2, "appname": "YOUTUBE", "Total_traffic_TB": 20.0,
             "Valid_video_download_throughput_Mbps": 22.0}])},
        "cache": {"frame": pd.DataFrame([
            {"clttime": d1, "server_type": "Cache_server", "Total_traffic_TB": 40.0},
            {"clttime": d1, "server_type": "Non_Cache_server", "Total_traffic_TB": 60.0},
            {"clttime": d2, "server_type": "Cache_server", "Total_traffic_TB": 70.0},
            {"clttime": d2, "server_type": "Non_Cache_server", "Total_traffic_TB": 130.0}])},
        "tcp": {"frame": pd.DataFrame([
            {"clttime": d1, "TCP_Total_Traffic_TB": 100.0,
             "Avg_TCP_Connection_Successful_Rate": 90.0, "Avg_TCP_UL_Retrans_Rate": 1.0,
             "Avg_TCP_DL_Retrans_Rate": 2.0, "Avg_Tcp_UL_RTT_ms": 80.0,
             "Avg_Tcp_DL_RTT_ms": 160.0},
            {"clttime": d2, "TCP_Total_Traffic_TB": 200.0,
             "Avg_TCP_Connection_Successful_Rate": 92.0, "Avg_TCP_UL_Retrans_Rate": 1.5,
             "Avg_TCP_DL_Retrans_Rate": 2.5, "Avg_Tcp_UL_RTT_ms": 85.0,
             "Avg_Tcp_DL_RTT_ms": 170.0}])},
        "game": {"frame": pd.DataFrame([
            {"clttime": d1, "Total_traffic_TB": 3.0},
            {"clttime": d2, "Total_traffic_TB": 5.0}])},
        "top_service": {"frame": pd.DataFrame([
            {"clttime": d1, "servicename": "Video", "TrafficTB": 40.0},
            {"clttime": d1, "servicename": "Web", "TrafficTB": 60.0},
            {"clttime": d2, "servicename": "Video", "TrafficTB": 160.0},
            {"clttime": d2, "servicename": "Game", "TrafficTB": 5.0}])},
    }


extracted = svc.extract_daily_kpi(_frames(), "run_test", ["20260914", "20260915"])
check("抽出 2 天且按天升序",
      [x["day"] for x in extracted] == ["2026-09-14", "2026-09-15"],
      str([x["day"] for x in extracted]))
e1, e2 = extracted
check("流量按天求和", close(e1["traffic_tb"], 100.0) and close(e2["traffic_tb"], 200.0))
check("活跃用户取当日值", e1["active_user"] == 400000 and e2["active_user"] == 500000)
check("视频流量=各 APP 求和", close(e1["video_tb"], 40.0) and close(e2["video_tb"], 160.0))
check("视频速率按流量加权（日1=15）", close(e1["video_mbps"], 15.0), str(e1["video_mbps"]))
check("视频速率按流量加权（日2=13.25）", close(e2["video_mbps"], 13.25), str(e2["video_mbps"]))
check("缓存/非缓存按 server_type 拆开",
      close(e1["cache_tb"], 40.0) and close(e1["noncache_tb"], 60.0)
      and close(e2["cache_tb"], 70.0) and close(e2["noncache_tb"], 130.0))
check("TCP 指标取当日值", close(e2["tcp_success_pct"], 92.0)
      and close(e2["tcp_dl_retrans_pct"], 2.5) and close(e2["tcp_dl_rtt_ms"], 170.0))
check("游戏流量", close(e2["game_tb"], 5.0))
check("TOP 业务取当日流量最大行（日1=Web）",
      e1["top_service"] == "Web" and close(e1["top_service_tb"], 60.0),
      "%s/%s" % (e1["top_service"], e1["top_service_tb"]))
check("TOP 业务（日2=Video）", e2["top_service"] == "Video")
check("统计当天有几块有数据", e1["blocks_ok"] == 7, str(e1["blocks_ok"]))
check("可疑日带上块名并归一为 ISO",
      e2["suspect_json"] and e2["suspect_json"][0].get("block") == "active_user"
      and e1["suspect_json"] is None,
      str(e2["suspect_json"]))
check("run_id/updated_at 落库", e1["run_id"] == "run_test" and bool(e1["updated_at"]))
check("视频缺列时不炸", svc.extract_daily_kpi(
    {"video": {"frame": pd.DataFrame([{"clttime": datetime(2026, 9, 15),
                                       "Total_traffic_TB": 10.0}])}},
    "r", ["20260915"])[0]["video_mbps"] is None)
check("空结果帧不产生行", svc.extract_daily_kpi(
    {"traffic": {"frame": pd.DataFrame(columns=["clttime", "Total_traffic_TB"])}},
    "r", ["20260915"]) == [])
check("没有数据的日期不落库", len(svc.extract_daily_kpi(
    {"traffic": {"frame": pd.DataFrame([{"clttime": datetime(2026, 9, 15),
                                         "Total_traffic_TB": 1.0}])}},
    "r", ["20260914", "20260915"])) == 1)
db8 = _tmp_db()
kpi.upsert_days(svc.extract_daily_kpi(_frames(), "run_test", ["20260914", "20260915"]), path=db8)
_, c8 = _cards(db8)
check("端到端：昨日总流量 GB（200×1024）", close(c8["traffic_gb"]["latest"]["value"], 204800.0))
check("端到端：视频占比 80%（160/200）", close(c8["video_share_pct"]["latest"]["value"], 80.0))
check("端到端：缓存占比 35%（70/200）", close(c8["cache_ratio_pct"]["latest"]["value"], 35.0))
check("端到端：视频速率 13250kbps", close(c8["video_thr_kbps"]["latest"]["value"], 13250.0))
_d9, _dir9 = kpi.KPI_DB_PATH, svc.DATA_DIR
try:
    svc.DATA_DIR = Path(tempfile.mkdtemp(prefix="olib_kpi_p9_"))
    svc.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _b8_info = svc.persist_daily_kpi(_frames(), "run_test", ["20260914", "20260915"])
finally:
    svc.DATA_DIR = _dir9
check("persist_daily_kpi 报告天数与日期清单",
      _b8_info.get("days") == 2 and _b8_info.get("days_list") == ["2026-09-14", "2026-09-15"],
      json.dumps(_b8_info, ensure_ascii=False))

# ==========================================================================
section("10. run_olib_soc_kpi_sync：只补缺的天")
# ==========================================================================
class _FakeGbase:
    """最小假客户端：按天返回一行，供 KPI 增量同步使用。"""

    def __init__(self):
        self.queries = 0
        self.closed = False

    def partition_days(self, family, granularity="day"):
        return vgc.day_range("2026-09-01", "2026-09-15")

    def available_days(self, family, begin, end, granularity="day"):
        return vgc.available_days(self.partition_days(family), begin, end)

    def healthy(self):
        return True, "FAKE GBase 0.0 | gbase@% | db=zxvmax"

    def close(self):
        self.closed = True

    def query_df(self, sql, params=None):
        import re
        self.queries += 1
        day = ""
        for token in sql.replace("\n", " ").split():
            if token.startswith("aggr_") and token[-8:].isdigit():
                day = token[-8:]
        cols, seen = [], set()
        for alias in re.findall(r"\bas\s+([A-Za-z_][A-Za-z0-9_]*)", sql):
            if alias.lower() not in seen:
                seen.add(alias.lower())
                cols.append(alias)
        for extra in ("servicename", "appname", "server_type", "Target_NE"):
            if extra in sql and extra.lower() not in seen:
                seen.add(extra.lower())
                cols.append(extra)
        stamp = datetime.strptime(day, "%Y%m%d")

        def make(kind=None):
            row = {"clttime": stamp}
            for col in cols:
                if col == "server_type":
                    row[col] = kind
                elif col == "servicename":
                    row[col] = "Video"
                elif col == "appname":
                    row[col] = "FACEBOOK_VIDEO"
                elif col == "Target_NE":
                    row[col] = "SGW_HQ_122"
                else:
                    row[col] = 12.5 if "throughput" in col.lower() else 100.0
            return row

        # 缓存块按 server_type 分组：真实结果里两类服务器都有行
        if "server_type" in cols:
            return pd.DataFrame([make("Cache_server"), make("Non_Cache_server")])
        return pd.DataFrame([make()])


_orig_db = kpi.KPI_DB_PATH
_orig_dir = svc.DATA_DIR
try:
    kpi.KPI_DB_PATH = _tmp_db()
    svc.DATA_DIR = Path(tempfile.mkdtemp(prefix="olib_kpi_sync_"))   # KPI 库跟随 DATA_DIR
    svc.DATA_DIR.mkdir(parents=True, exist_ok=True)
    kpi.KPI_DB_PATH = svc.DATA_DIR / "olib_soc_report.sqlite3"
    db9 = kpi.KPI_DB_PATH
    kpi.DATA_DIR = svc.DATA_DIR
    cfg_none = svc.DATA_DIR / "_no_such_cfg.json"
    fake = _FakeGbase()
    out = svc.run_olib_soc_kpi_sync(days_back=3, client=fake, config_path=cfg_none,
                                   today=date(2026, 9, 16))
    check("首次同步状态 ok", out["status"] in ("ok", "partial"), str(out["status"]))
    check("首次同步请求 3 天缺口",
          out["requested_days"] == ["2026-09-13", "2026-09-14", "2026-09-15"],
          str(out["requested_days"]))
    check("入库 3 天",
          kpi.stored_days(db9) == ["2026-09-13", "2026-09-14", "2026-09-15"],
          str(kpi.stored_days(db9)))
    check("同步结果带 KPI 入库明细", (out.get("kpi") or {}).get("days") == 3,
          json.dumps(out.get("kpi"), ensure_ascii=False))
    check("只跑看板 7 个块、不出 Excel",
          out.get("excel") in (None, "") and out.get("blocks_ok") == 7,
          "%s/%s" % (out.get("excel"), out.get("blocks_ok")))
    check("未产生 still_missing", not out.get("still_missing"), str(out.get("still_missing")))
    check("同步结果可 JSON 序列化（任务上报用）",
          bool(json.dumps(out, ensure_ascii=False, default=str)))
    q1 = fake.queries
    out2 = svc.run_olib_soc_kpi_sync(days_back=3, client=fake, config_path=cfg_none,
                                    today=date(2026, 9, 16))
    check("第二次同步重取窗口最新 1 天（防数仓当晚未完成 / 任务漏跑）",
          out2["status"] in ("ok", "partial") and out2["requested_days"] == ["2026-09-15"],
          "%s %s" % (out2["status"], out2["requested_days"]))
    check("重取最新 1 天只查 7 条 SQL", fake.queries - q1 == 7, str(fake.queries - q1))
    q2 = fake.queries
    out2b = svc.run_olib_soc_kpi_sync(days_back=3, client=fake, config_path=cfg_none,
                                      today=date(2026, 9, 16), refresh_last=0)
    check("refresh_last=0 时无缺口直接 up_to_date", out2b["status"] == "up_to_date",
          str(out2b["status"]))
    check("refresh_last=0 零查询（纯 only_missing 语义，幂等不空跑）",
          fake.queries == q2 and out2b["requested_days"] == [],
          "%d->%d" % (q2, fake.queries))
    with sqlite3.connect(str(db9)) as conn:
        conn.execute("DELETE FROM daily_kpi WHERE day='2026-09-14'")
        conn.commit()
    q3 = fake.queries
    out3 = svc.run_olib_soc_kpi_sync(days_back=3, client=fake, config_path=cfg_none,
                                    today=date(2026, 9, 16))
    check("掉一天能自愈补回（并顺带刷新最新 1 天）",
          out3["requested_days"] == ["2026-09-14", "2026-09-15"]
          and kpi.stored_days(db9) == ["2026-09-13", "2026-09-14", "2026-09-15"],
          str(out3["requested_days"]))
    check("补一天 + 刷新最新 1 天 = 14 条 SQL", fake.queries - q3 == 14, str(fake.queries - q3))
    q4 = fake.queries
    out4 = svc.run_olib_soc_kpi_sync(days_back=3, only_missing=False, client=fake,
                                    config_path=cfg_none, today=date(2026, 9, 16))
    check("only_missing=False 整窗重取",
          out4["requested_days"] == ["2026-09-13", "2026-09-14", "2026-09-15"],
          str(out4["requested_days"]))
    check("整窗重取 = 3×7 条 SQL", fake.queries - q4 == 21, str(fake.queries - q4))
    check("窗口结束于昨天", out4["window"][1] == "20260915", str(out4["window"]))
    b9 = kpi.build_overview(days=7, today=date(2026, 9, 16))
    check("同步后看板立刻有数", b9["status"] == "ok" and len(b9["cards"]) == 10,
          str(b9["status"]))
    check("KPI 库跟随 DATA_DIR（测试不会写进生产库）",
          Path((out.get("kpi") or {}).get("db", "")) == db9, str((out.get("kpi") or {}).get("db")))
finally:
    kpi.KPI_DB_PATH = _orig_db
    svc.DATA_DIR = _orig_dir

# ==========================================================================
section("11. 只读接口 /overview /status /days")
# ==========================================================================
_orig_db2 = kpi.KPI_DB_PATH
try:
    db10 = _tmp_db()
    # 日期相对「今天」构造，避免测试写死日期后随时间失效
    _end10 = date.today() - timedelta(days=1)                 # 最新完整日
    _days10 = [_end10 - timedelta(days=i) for i in range(14, -1, -1)]   # 15 天
    kpi.upsert_days([_row(d.isoformat()) for d in _days10], path=db10)
    kpi.KPI_DB_PATH = db10
    resp = dash.get_overview(days=90)
    body10 = json.loads(resp.body.decode("utf-8"))
    check("/overview 200 + no-store", resp.status_code == 200
          and resp.headers.get("cache-control") == "no-store")
    check("/overview 含 cards/series/metrics/coverage",
          all(k in body10 for k in ("cards", "series", "metrics", "coverage")))
    check("/overview 10 张卡片", len(body10["cards"]) == 10, str(len(body10["cards"])))
    check("/overview 日/周序列都有",
          bool(body10["series"]["day"]["dates"]) and bool(body10["series"]["week"]["labels"]))
    check("/overview 明细表 14 天", isinstance(body10["table"], list)
          and len(body10["table"]) == 14, str(len(body10["table"])))
    check("/overview 指标字典带 better/digits/group",
          all(all(k in m for k in ("better", "digits", "group")) for m in body10["metrics"]))
    st = json.loads(dash.get_status().body.decode("utf-8"))
    check("/status 报最新日与天数", st["newest"] == _end10.isoformat()
          and st["db_exists"] is True and st["stored_days"] == 15,
          json.dumps(st, ensure_ascii=False))
    check("/status 报指标 id 与主卡片", len(st["metrics"]) == 10 and len(st["primary"]) == 4)
    dd = json.loads(dash.get_days(days=10).body.decode("utf-8"))
    check("/days 返回原始日值", dd["status"] == "ok" and dd["count"] == 10
          and all("traffic_tb" in r for r in dd["days"]), str(dd["count"]))
    check("/days 按天升序",
          [r["day"] for r in dd["days"]] == sorted(r["day"] for r in dd["days"]))
    check("路由前缀/路径符合约定", dash.router.prefix == "/api/olib-soc-dashboard"
          and {r.path for r in dash.router.routes} == {
              "/api/olib-soc-dashboard/overview", "/api/olib-soc-dashboard/status",
              "/api/olib-soc-dashboard/days", "/api/olib-soc-dashboard/app-offload",
              "/api/olib-soc-dashboard/video-apps", "/api/olib-soc-dashboard/game-apps"},
          str(sorted(r.path for r in dash.router.routes)))
    kpi.KPI_DB_PATH = Path(tempfile.mkdtemp(prefix="olib_kpi_e_")) / "nope.sqlite3"
    check("空库 /overview 不 500",
          json.loads(dash.get_overview(days=90).body.decode("utf-8"))["status"] == "empty")
    se = json.loads(dash.get_status().body.decode("utf-8"))
    check("空库 /status 不炸", se["db_exists"] is False and se["stored_days"] == 0)
    check("空库 /days 0 行",
          json.loads(dash.get_days(days=5).body.decode("utf-8"))["count"] == 0)
finally:
    kpi.KPI_DB_PATH = _orig_db2

# ==========================================================================
section("12. 配置、任务注册、页面与前端接线")


def _missing_ids(html):
    """页面里 getElementById('x') 引用、但 HTML 中没有对应 id="x" 的引用（拼写错误）。"""
    refs = set(re.findall(r"getElementById\('([^']+)'\)", html))
    declared = set(re.findall(r'id="([^"]+)"', html))
    return sorted(refs - declared)


def _innerhtml_hazards(html):
    """找出会把「带 id 的子元素」一起冲掉的 innerHTML 赋值。

    例：`<h2 id="hTrend"><em id="hTrendSub"></em></h2>` 若用
    `getElementById('hTrend').innerHTML = '标题 <em>副标题</em>'` 重写，
    原 `<em id="hTrendSub">` 元素被丢弃，之后 `getElementById('hTrendSub')` 返回 null
    → 渲染中途抛错（2026-09-16 线上就是这个现象：切粒度/刷新后图表不动）。
    """
    bad = []
    for m in re.finditer(r"<(\w+)\s+id=\"([^\"]+)\"[^>]*>", html):
        tag, eid = m.group(1), m.group(2)
        end = html.find("</%s>" % tag, m.end())
        if end < 0:
            continue
        child_ids = re.findall(r'id="([^"]+)"', html[m.end():end])
        if child_ids and re.search(r"getElementById\('%s'\)\.innerHTML\s*=" % re.escape(eid), html):
            bad.append((eid, child_ids[:3]))
    return bad

# ==========================================================================
cfg = svc.load_config()
check("配置含 kpi_sync 段", isinstance(cfg.get("kpi_sync"), dict), json.dumps(cfg.get("kpi_sync")))
check("kpi_sync.days_back 默认 7", int(cfg["kpi_sync"]["days_back"]) == 7)
check("kpi_sync.only_missing 默认 True", cfg["kpi_sync"]["only_missing"] is True)
check("kpi_sync.refresh_last_days 默认 1（防数仓晚到/漏跑）",
      int(cfg["kpi_sync"]["refresh_last_days"]) == 1)
check("persist.write_kpi 默认 True", cfg["persist"]["write_kpi"] is True)
check("KPI 块是全部块的子集", set(svc.KPI_BLOCKS) <= set(svc.BLOCKS), str(svc.KPI_BLOCKS))
check("KPI 块不含 top_video（省时间）", "top_video" not in svc.KPI_BLOCKS)
check("缺配置文件时用默认值（向后兼容）",
      svc.load_config(Path(tempfile.mkdtemp()) / "none.json")["kpi_sync"]["days_back"] == 7)
svc_text = Path(svc.__file__).read_text(encoding="utf-8")
check("CLI 参数齐备", all(x in svc_text for x in
                          ("--sync-kpi", "--kpi-only", "--no-excel", "--days-back", "--force",
                           "--details-only")))
reg_text = (ROOT / "backend" / "task_registry.py").read_text(encoding="utf-8")
check("任务 olib_soc_kpi_daily_sync 已注册",
      "olib_soc_kpi_daily_sync" in reg_text and "run_olib_soc_kpi_sync" in reg_text)
check("每日同步 cron 在早班低峰（留出数仓出数余量）", '"20 6 * * *"' in reg_text)
check("归入 olib_soc 分类", 'category="olib_soc"' in reg_text)
# 分组登记守卫（2026-09-18 事故）：只写 TASK_SPECS、漏登记 worker_watchdog.GROUP_TASK_MAP
# 的后果不是报错而是静默停摆 —— 队列 pending 无人认领，且陈旧 pending 占住单飞
# 名额把后续所有调度挡掉（task_execution_log 一条都没有，看板停在 09-16）。
try:
    from backend.worker_watchdog import GROUP_TASK_MAP as _GT_MAP                      # noqa: F401
    _grouped = {t.strip() for _v in _GT_MAP.values()
                for t in (_v or "").split(",") if t.strip()}
except Exception:                                                                      # noqa: BLE001
    _grouped = set()
check("两个 olib_soc 任务已登记 worker 分组（漏分组 = 无 worker 认领、永远 pending）",
      {"olib_soc_kpi_daily_sync", "olib_soc_vmax_report"} <= _grouped,
      str(sorted({"olib_soc_kpi_daily_sync", "olib_soc_vmax_report"} - _grouped)))
main_text = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
check("路由已在 main.py 挂载", "olib_soc_dashboard.router" in main_text
      and "olib_soc_dashboard," in main_text)
try:
    from backend.services import task_configs_registry as _tcr             # noqa: F401 (注册副作用)
    from backend.services.task_config_files import get_resource
    _res = get_resource("olib_soc_vmax_report")
except Exception:                                                        # noqa: BLE001
    _res = None
check("设置页配置资源仍在", _res is not None)
if _res is not None:
    check("设置页可编辑 kpi_sync（回看天数/只补缺口/重取最新 N 天）",
          set((_res.schema.get("kpi_sync") or {}).get("fields", {})) ==
          {"days_back", "only_missing", "refresh_last_days"}, str(_res.schema.get("kpi_sync")))
    check("设置页可编辑 persist.write_kpi",
          "write_kpi" in ((_res.schema.get("persist") or {}).get("fields") or {}))
    check("默认值工厂给出 kpi_sync 与 write_kpi",
          (_res.defaults_factory() or {}).get("kpi_sync", {}).get("days_back") == 7
          and (_res.defaults_factory() or {}).get("persist", {}).get("write_kpi") is True)
page = ROOT / "frontend" / "public" / "vmax_cxo_dashboard_90days.html"
check("看板页面文件存在", page.exists(), str(page))
if page.exists():
    html = page.read_text(encoding="utf-8")
    check("页面引用同源接口", "/api/olib-soc-dashboard/overview" in html)
    check("页面用项目自带 ECharts", "/myapp/lib/echarts.min.js" in html)
    check("页面沿用项目视觉基线", "legacy-glass-baseline.css" in html)
    check("页面遵循外壳主题/语言/刷新协议",
          all(x in html for x in ("myapp-theme", "myapp-locale", "myapp-refresh")))
    check("页面读同一套 localStorage 键", "myapp-theme" in html and "app-locale" in html)
    check("页面支持日/周粒度切换", 'data-gran="week"' in html and "GRAN" in html)
    check("页面有 4 个 CEO 主卡片位", 'id="cardsPrimary"' in html)
    check("页面区分业务与网络质量卡片区",
          'id="cardsBusiness"' in html and 'id="cardsQuality"' in html)
    check("页面卡片显示最大/平均/最低", all(x in html for x in ("t('max')", "t('avg')", "t('min')")))
    check("页面有数据说明折叠区", 'id="notesToggle"' in html and 'id="cover"' in html)
    check("页面表格 14 天明细", 'id="tbl"' in html)
    # --- 前端接线静态体检（2026-09-16 的真实故障：h2.innerHTML 把 <em id="hTrendSub"> 冲掉，
    #     后续 getElementById('hTrendSub') 拿到 null → renderAll 中途抛错，图表/表格停在旧内容，
    #     表现就是「刷新/切粒度后数据不变」。这里把这类错误固化成回归项。）---
    check("页面引用的 DOM id 全都存在", not _missing_ids(html), str(_missing_ids(html)))
    check("没有会把带 id 的子元素冲掉的内层 HTML 赋值",
          not _innerhtml_hazards(html), str(_innerhtml_hazards(html)))
    check("日/周切换后仍能取到标题副标题节点（不再用 innerHTML 重写 h2）",
          "setHead(" in html and "hTrendSub" in html)
    check("渲染入口有错误兜底（失败会写状态栏而不是静默停住）",
          "catch(function(e){ setStatus(t('failed')" in html)
    # 体检函数自身的自检：必须能抓出「旧写法」，且不会误报「新写法」
    _bad = ('<h2 id="hA"><em id="hB"></em></h2>'
            "<script>document.getElementById('hA').innerHTML='x <em>y</em>';</script>")
    _good = '<h2 id="hA"><em id="hB"></em></h2><script>document.getElementById("hB").textContent="y"</script>'
    check("体检函数能抓出 h2.innerHTML 冲掉子元素 id 的写法",
          _innerhtml_hazards(_bad) == [("hA", ["hB"])], str(_innerhtml_hazards(_bad)))
    check("体检函数对正确写法不误报", _innerhtml_hazards(_good) == [], str(_innerhtml_hazards(_good)))
    check("体检函数能抓出不存在的 id 引用",
          _missing_ids('<div id="a"></div>' + "getElementById('b')") == ["b"])
    # --- 图表卡片：最大/平均/最低放到右上角 + 时间坐标轴 ---
    check("图表卡片右上角有 最大/平均/最低 统计块",
          "panel-stats" in html and "function panelStats(" in html
          and "panelStats(id,digits)" in html)
    check("统计值不再画在图里（markPoint 只留锚点、不显示文字）",
          "label:{show:false}" in html)
    check("时间坐标轴标签简化为 月-日 / 周次",
          "interval:'auto'" in html and "hideOverlap:true" in html and "x.slice(5)" in html)
    check("日/周两种粒度的坐标轴标签都会被格式化", "replace(/^\\d{4}-/,'')" in html)
    # --- 自动刷新（按项目外壳的统一协议） ---
    check("页面接软刷新协议（收到 myapp-refresh 原地重拉）",
          "myapp-refresh" in html and "paintStatic(); load();" in html.replace("\n", " "))
    # 2026-10-10 起自刷改为常开的 MyAppRefresh 共享协议（嵌入外壳时也兜底），
    # 旧写法 if(!embedded()) window.__rt=setInterval 已删除 —— 断言跟着现状走。
    check("页面接 MyAppRefresh 共享自刷协议（间隔与外壳 AR_PAGE_DEFAULTS 对齐）",
          "MyAppRefresh.install({" in html and "defaultSec: 900" in html)
    check("页面读外壳的自动刷新间隔并在界面上显示",
          "myapp_auto_refresh_effective" in html and 'id="arLabel"' in html)
    check("中英文都补了自动刷新文案",
          "arOn:" in html and "arOff:" in html and html.count("arOn:") == 2)
    check("页面自报版本（HEAD 取 Last-Modified，便于排查缓存）",
          "function stampVersion(" in html and 'id="verLabel"' in html
          and "method:'HEAD'" in html)
    # --- 布局：两块并排同一行 + 不再有浮动遮挡 ---
    _mix = html.split('class="mixrow"', 1)[-1][:900] if 'class="mixrow"' in html else ""
    check("Service Mix 与 Network Quality 并排同一行（同一个 .mixrow 容器）",
          'class="mixrow"' in html and 'id="cardsBusiness"' in _mix
          and 'id="cardsQuality"' in _mix)
    check("并排布局有栅格样式与窄屏回退",
          ".mixrow{display:grid" in html.replace(" ", "") and "max-width:1200px" in html)
    check("状态条不再 position:fixed（原来会盖住右下角卡片）",
          ".status{position:fixed" not in html.replace(" ", "")
          and ".status{margin:8pxauto" in html.replace(" ", ""))
    # --- 卡片下钻（DRILLS 配置驱动，2026-10-30 泛化自「缓存占比」单卡实现） ---
    check("页面登记 6 张可下钻卡片（总流量/缓存占比/视频三卡/游戏流量）",
          all(x in html for x in ("traffic_gb:", "cache_ratio_pct:", "video_tb:",
                                  "video_thr_kbps:", "video_share_pct:", "game_tb:")),
          "DRILLS 配置缺卡")
    check("页面引用三个下钻接口",
          all(x in html for x in ("/app-offload", "/video-apps", "/game-apps")))
    check("手型光标只给可下钻卡片（不给全部 [data-mid]）",
          ".card.drill,.panel.drill{cursor:pointer}" in html.replace(" ", "")
          and ".panel[data-mid]{cursor:pointer}" not in html.replace(" ", ""))
    check("下钻弹窗的中英标题/说明/空态文案成对齐全",
          all(html.count(x) == 2 for x in ("vTitle:", "gTitle:", "trTitle:", "dEmpty:")),
          str({x: html.count(x) for x in ("vTitle:", "gTitle:", "trTitle:", "dEmpty:")}))
app_text = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
check("React 页面已注册（lazy/PageKey/VALID_PAGES/META/菜单/switch）",
      app_text.count("vmaxCxoDashboard_90Days") >= 5,
      str(app_text.count("vmaxCxoDashboard_90Days")))
# 外壳统一自动刷新：本页登记进「软刷新页」（原地重拉、不闪屏）并给出默认间隔
# AR_SOFT_REFRESH_PAGES 的声明在 App.tsx 里是多行数组，取声明行到收口的 ] 为整段再判
_ar_block = ""
_app_lines = app_text.splitlines()
for _i, ln in enumerate(_app_lines):
    if "AR_SOFT_REFRESH_PAGES" in ln and "=" in ln:
        _block = [ln]
        for _nxt in _app_lines[_i + 1:_i + 12]:
            _block.append(_nxt)
            if "]" in _nxt:
                break
        _ar_block = "\n".join(_block)
        break
check("已登记进外壳软刷新页清单（AR_SOFT_REFRESH_PAGES）",
      "'vmaxCxoDashboard_90Days'" in _ar_block, _ar_block.strip()[:200])
check("已给出该页默认自动刷新间隔（AR_PAGE_DEFAULTS）",
      "vmaxCxoDashboard_90Days: 900" in app_text)
check("外壳把生效间隔公开给 legacy 页面（单一事实来源，页面不硬编码默认值）",
      "AR_EFFECTIVE_KEY" in app_text and "myapp_auto_refresh_effective" in app_text)
wrapper = ROOT / "frontend" / "src" / "pages" / "VmaxCxoDashboard90Days.tsx"
check("React 包装页存在且指向页面文件",
      wrapper.exists() and "vmax_cxo_dashboard_90days.html" in wrapper.read_text(encoding="utf-8"))
i18n_text = (ROOT / "frontend" / "src" / "i18n.tsx").read_text(encoding="utf-8")
check("中英文导航文案都补了", i18n_text.count("nav.vmaxCxoDashboard90Days") == 2,
      str(i18n_text.count("nav.vmaxCxoDashboard90Days")))

# ==========================================================================
section("13. 单位换算与库位置不变量")
# ==========================================================================
check("窗口默认 90 天", kpi.build_overview(days=90, path=db10)["window_days"] == 90)
check("GB 换算 1024", kpi.METRIC_BY_ID["traffic_gb"]["scale"] == 1024.0)
check("kbps 换算 1000", kpi.METRIC_BY_ID["video_thr_kbps"]["scale"] == 1000.0)
check("K 换算 0.001", kpi.METRIC_BY_ID["active_user_k"]["scale"] == 0.001)
check("占比换算 100", all(kpi.METRIC_BY_ID[x]["scale"] == 100.0
                          for x in ("video_share_pct", "cache_ratio_pct")))
check("库文件在 data/olib_soc_report 下",
      kpi.KPI_DB_PATH.name == "olib_soc_report.sqlite3"
      and kpi.KPI_DB_PATH.parent.name == "olib_soc_report", str(kpi.KPI_DB_PATH))
check("WAL 模式（任务写 + 看板读并发）",
      kpi.connect(db10, readonly=True).execute("PRAGMA journal_mode").fetchone()[0] == "wal")
check("_spark 压缩到 30 点", len(kpi._spark(list(range(90)))) == 30)

# ==========================================================================
section("13b. 残缺日：跨窗口残留 + run_block days_empty（2026-10-11 加固）")
# ==========================================================================
# ① REQUIRED_COLUMNS 覆盖全部主数值列（不再只是 traffic/active_user/video）
for _col in ("video_mbps", "cache_tb", "noncache_tb", "tcp_tb", "tcp_success_pct",
             "tcp_ul_retrans_pct", "tcp_dl_retrans_pct", "tcp_ul_rtt_ms",
             "tcp_dl_rtt_ms", "game_tb"):
    check("REQUIRED_COLUMNS 覆盖 %s" % _col, _col in kpi.REQUIRED_COLUMNS)

# ② all_incomplete_days 能捞出**窗口外**的残缺日（历史残留，如 2026-09-07 的 traffic_tb）
_db_gap = _tmp_db()
kpi.upsert_days([
    _row("2026-09-07", traffic_tb=None),            # 一个月前的历史残留
    _row("2026-10-05"), _row("2026-10-06"), _row("2026-10-07", game_tb=None),
], path=_db_gap)
check("incomplete_days（7 天窗口）抓不到窗口外的 09-07",
      "2026-09-07" not in kpi.incomplete_days(7, path=_db_gap, today=date(2026, 10, 8)))
check("all_incomplete_days 能捞到窗口外的 09-07",
      "2026-09-07" in kpi.all_incomplete_days(path=_db_gap))
check("all_incomplete_days 也捞到窗口内的残缺列（game_tb 为 NULL）",
      "2026-10-07" in kpi.all_incomplete_days(path=_db_gap))
check("incomplete_days_in_window 只返回区间内的残缺日",
      kpi.incomplete_days_in_window("2026-10-01", "2026-10-31", path=_db_gap) == ["2026-10-07"])

# ③ build_overview.coverage.incomplete_days（行在但关键列为 NULL）
_ov = kpi.build_overview(days=40, path=_db_gap, today=date(2026, 10, 8))
check("coverage.incomplete_days 出现在载荷里", "incomplete_days" in _ov["coverage"])
check("coverage.incomplete_days 命中残缺日",
      "2026-10-07" in _ov["coverage"]["incomplete_days"], str(_ov["coverage"]["incomplete_days"]))
_tbl_inc = {t["date"]: t for t in _ov["table"]}
check("明细表行带 incomplete 标记",
      _tbl_inc.get("2026-10-07", {}).get("incomplete") is True
      and _tbl_inc.get("2026-10-06", {}).get("incomplete") is False)


# ④ run_block 把「分区在但查出空行」记入 days_empty 并降级 partial
class _EmptyDayGbase(_FakeGbase):
    """2026-09-02 分区在、但查出 0 行；其余天正常 —— 模拟「上游分区空」的过渡态。"""

    def query_df(self, sql, params=None):
        import re
        day = ""
        for token in sql.replace("\n", " ").split():
            if token.startswith("aggr_") and token[-8:].isdigit():
                day = token[-8:]
        if day == "20260902":
            self.queries += 1
            return pd.DataFrame()
        return super().query_df(sql, params)


class _PoolStub:
    """run_block 只用到 pool.get()；给个直接返回假客户端的壳。"""

    def __init__(self, client):
        self._c = client

    def get(self):
        return self._c


_cfg_rb = {"granularity": "day"}
_rb = svc.run_block(_PoolStub(_EmptyDayGbase()), "traffic",
                    ["20260901", "20260902", "20260903"], _cfg_rb)
check("run_block 返回 days_empty 字段", "days_empty" in _rb)
check("空行的那天进 days_empty", _rb["days_empty"] == ["2026-09-02"], str(_rb["days_empty"]))
check("有缺天的块降级为 partial", _rb["status"] == "partial", _rb["status"])

# 分区缺失的天（非今天/未来）也进 days_empty
class _MissingPartGbase(_FakeGbase):
    def partition_days(self, family, granularity="day"):
        return [d for d in vgc.day_range("2026-09-01", "2026-09-15") if d != "20260903"]


_rb2 = svc.run_block(_PoolStub(_MissingPartGbase()), "traffic",
                     ["20260901", "20260902", "20260903"], _cfg_rb)
check("分区缺失的天（非今天）进 days_empty",
      _rb2["days_empty"] == ["2026-09-03"], str(_rb2["days_empty"]))

# 首页块（top_service）空天不降级（BLOCKS_ALLOW_EMPTY_DAY 白名单）
_rb3 = svc.run_block(_PoolStub(_EmptyDayGbase()), "game",
                     ["20260901", "20260902", "20260903"], _cfg_rb)
check("白名单块（game）空天仍记录 days_empty",
      _rb3["days_empty"] == ["2026-09-02"], str(_rb3["days_empty"]))
check("白名单块（game）空天不降级，仍为 ok", _rb3["status"] == "ok", _rb3["status"])

# ==========================================================================
section("13c. 分业务「本地 / 海外」服务器分流下钻（看板点击「缓存占比」的数据源）")


class _OffloadStub:
    """假 GBase：只验 SQL 组装 / Decimal 转换 / 分区跳天，不连库。"""

    def __init__(self, rows):
        self.rows = rows
        self.sqls = []

    def partition_days(self, family, gran="day"):
        return ["20261018", "20261019"]

    def query_dicts(self, sql):
        self.sqls.append(sql)
        return [dict(r) for r in self.rows]


from decimal import Decimal as _D
_off_rows = [
    {"appname": "FACEBOOK_VIDEO", "total_tb": _D("50.2280"), "local_tb": _D("48.2190"),
     "abroad_tb": _D("2.0090"), "unknown_tb": _D("0.0000")},
    {"appname": "HTTPS", "total_tb": _D("5.7100"), "local_tb": _D("0.0000"),
     "abroad_tb": _D("0.0000"), "unknown_tb": _D("5.7100")},
]
_off_sql = svc.offload_sql("aggr_5gsa_flow_spservice_day_20261019")
check("分流 SQL 按国家判定本地，不再用 5 个 IP 白名单",
      "sp_country_id = %d" % svc.LOCAL_COUNTRY_ID in _off_sql
      and "41.191.107.211" not in _off_sql)
check("三桶互斥且完整：未识别 = server_ip 或 country 任一为 NULL",
      "server_ip is null or sp_country_id is null" in _off_sql
      and "sp_country_id is not null" in _off_sql)
check("先按 (serviceid, appid) 去重再左连 dim_service（否则 join 扇出把流量算重）",
      "group by serviceid, appid" in _off_sql)
_stub = _OffloadStub(_off_rows)
_got, _skip = svc.fetch_app_offload(_stub, {"granularity": "day"},
                                    ["20261019", "20991231"], "run_off")
check("上游分区已过期（超 90 天保留期）的天被跳过，不发起查询",
      _skip == ["2099-12-31"] and len(_stub.sqls) == 1, str(_skip))
check("GBase 的 Decimal 转成 float（直接绑给 sqlite 会 ProgrammingError）",
      len(_got) == 2 and all(isinstance(r[k], float) for r in _got
                             for k in ("total_tb", "local_tb", "abroad_tb", "unknown_tb")))
_db_off = Path(tempfile.mkdtemp(prefix="olib_off_")) / "o.sqlite3"
check("明细按 (day, appname) 落库且重跑幂等",
      det.upsert_app_offload(_got, path=_db_off) == 2
      and det.upsert_app_offload(_got, path=_db_off) == 2
      and det.detail_days(det.APP_OFFLOAD_TABLE, path=_db_off) == ["2026-10-19"])
_ob = det.build_app_offload(days=90, path=_db_off)
_orows = {r["appname"]: r for r in _ob["day"]["rows"]}
check("本地占的分母剔除未识别 IP：48.219/(48.219+2.009)=96.0%",
      _orows["FACEBOOK_VIDEO"]["local_pct"] == 96.0, str(_orows["FACEBOOK_VIDEO"]))
check("整行都没解析出服务器 IP 的业务给 None（界面显示 —，不能显示 0%）",
      _orows["HTTPS"]["local_pct"] is None and _orows["HTTPS"]["unknown_tb"] == 5.71,
      str(_orows["HTTPS"]))
check("合计行等于明细相加（表格合计要与 traffic 卡片对得上账）",
      _ob["day"]["totals"]["apps"] == 2
      and abs(_ob["day"]["totals"]["total_tb"] - sum(r["total_tb"] for r in _got)) < 0.01,
      str(_ob["day"]["totals"]))
_many = [{"day": "2026-10-19", "appname": "A%03d" % i, "total_tb": 100.0 - i,
          "local_tb": (100.0 - i) * 0.6, "abroad_tb": (100.0 - i) * 0.3,
          "unknown_tb": (100.0 - i) * 0.1} for i in range(45)]
_db_roll = Path(tempfile.mkdtemp(prefix="olib_roll_")) / "r.sqlite3"
det.upsert_app_offload(_many, path=_db_roll)
_roll = det.build_app_offload(days=90, top=40, path=_db_roll)["day"]
check("只展示 TOP40，其余并进「其它」，四桶相加仍等于合计",
      len(_roll["rows"]) == 40 and _roll["others"] is not None
      and all(abs(sum(r[c] for r in _roll["rows"]) + _roll["others"][c] - _roll["totals"][c])
              < 0.05 for c in det.APP_OFFLOAD_COLUMNS), str(_roll["totals"]))
_o_db = kpi.KPI_DB_PATH
kpi.KPI_DB_PATH = _db_off
try:
    check("as_of 非法直接 400，不静默改看最新一天",
          dash.get_app_offload(days=90, as_of="2026-13-99").status_code == 400)
    _api = json.loads(dash.get_app_offload(days=90).body.decode("utf-8"))
    check("接口给「最新一天」与「窗口累计」两套行 + 各自合计",
          _api["status"] == "ok" and _api["day"]["rows"] and _api["as_of"] == "2026-10-19"
          and _api["window_agg"]["totals"]["apps"] == 2, str(_api["window"]))
finally:
    kpi.KPI_DB_PATH = _o_db

# ==========================================================================
section("13d. 视频 / 游戏逐 APP 明细下钻（视频三卡与游戏卡的数据源）")

# video/game 块的 SQL 本来就按 appname 分组，结果帧里现成带着逐 APP 行：
# extract 只做 clttime→ISO day 与列名映射，零额外数仓查询
_vres = {"video": {"block": "video", "sheet": "Video", "status": "ok", "frame": pd.DataFrame({
    "clttime": pd.to_datetime(["2026-10-19", "2026-10-19", "2026-10-20"]),
    "appname": ["FACEBOOK_VIDEO", "TIKTOK", "FACEBOOK_VIDEO"],
    "Total_traffic_TB": [50.0, 30.0, 60.0],
    "Valid_video_download_throughput_Mbps": [10.0, 20.0, None]})}}
_vrows = svc.extract_app_detail_rows(_vres, "video")
check("video 块帧 → 逐 APP 明细行（clttime 归一 ISO，列名映射）",
      len(_vrows) == 3 and _vrows[0] == {"day": "2026-10-19", "appname": "FACEBOOK_VIDEO",
                                         "traffic_tb": 50.0, "thr_mbps": 10.0},
      str(_vrows[:1]))
check("空帧 / 没跑该块时提取为空（不炸）",
      svc.extract_app_detail_rows({"video": {"frame": pd.DataFrame()}}, "video") == []
      and svc.extract_app_detail_rows({}, "video") == [])
_grows = svc.extract_app_detail_rows(
    {"game": {"block": "game", "frame": pd.DataFrame({
        "clttime": pd.to_datetime(["2026-10-19", "2026-10-19"]),
        "appname": ["PUBG", "FREE_FIRE"],
        "Total_traffic_TB": [2.0, 3.0],
        "Avg_TCP_UL_RTT_ms": [80.0, None],
        "Avg_TCP_DL_RTT_ms": [150.0, 160.0]})}}, "game")
check("game 块帧提取带上/下行 RTT（缺失给 None）",
      len(_grows) == 2 and _grows[1]["ul_rtt_ms"] is None and _grows[1]["dl_rtt_ms"] == 160.0,
      str(_grows))

_db_det = Path(tempfile.mkdtemp(prefix="olib_vd_")) / "d.sqlite3"
kpi.upsert_days([_row("2026-10-19", traffic_tb=200.0), _row("2026-10-20", traffic_tb=100.0)],
                path=_db_det)
det.upsert_video_app(_vrows, path=_db_det)
det.upsert_video_app(_vrows, path=_db_det)                       # 同一天重跑幂等
det.upsert_game_app(_grows + [{"day": "2026-10-20", "appname": "PUBG",
                               "traffic_tb": 4.0, "ul_rtt_ms": None, "dl_rtt_ms": None}],
                    path=_db_det)
_vb = det.build_video_apps(days=90, path=_db_det)
check("video day 视图 = 最新一天（10-20 只有 FACEBOOK_VIDEO）",
      _vb["as_of"] == "2026-10-20"
      and [r["appname"] for r in _vb["day"]["rows"]] == ["FACEBOOK_VIDEO"], str(_vb["day"]))
check("video share 与「视频流量占比」卡片同口径（60/100=60%）",
      _vb["day"]["rows"][0]["share_pct"] == 60.0, str(_vb["day"]["rows"][0]))
check("速率缺失给 None（kbps 不显示 0）",
      _vb["day"]["rows"][0]["thr_kbps"] is None, str(_vb["day"]["rows"][0]))
_win = {r["appname"]: r for r in _vb["window_agg"]["rows"]}
check("video 窗口聚合：流量求和 + 速率按流量加权（只有 19 日有速率 → 10000kbps）",
      close(_win["FACEBOOK_VIDEO"]["traffic_tb"], 110.0)
      and _win["FACEBOOK_VIDEO"]["thr_kbps"] == 10000.0
      and _win["TIKTOK"]["thr_kbps"] == 20000.0, str(_win))
check("video 窗口 share 分母 = 有总流量的天之和（110/300=36.7%）",
      _win["FACEBOOK_VIDEO"]["share_pct"] == 36.7, str(_win["FACEBOOK_VIDEO"]))
check("video 合计行 = 卡片数值（140/300=46.7%，速率加权 12142.9kbps）",
      close(_vb["window_agg"]["totals"]["traffic_tb"], 140.0)
      and _vb["window_agg"]["totals"]["share_pct"] == 46.7
      and _vb["window_agg"]["totals"]["thr_kbps"] == 12142.9,
      str(_vb["window_agg"]["totals"]))
_gb = det.build_game_apps(days=90, path=_db_det)
check("game day 视图 RTT 全缺给 None（不显示 0）",
      _gb["day"]["rows"][0]["ul_rtt_ms"] is None and _gb["day"]["rows"][0]["dl_rtt_ms"] is None,
      str(_gb["day"]))
_gwin = {r["appname"]: r for r in _gb["window_agg"]["rows"]}
check("game 窗口 RTT 按流量加权（PUBG ul 只算有值的天 → 80ms）",
      close(_gwin["PUBG"]["traffic_tb"], 6.0) and _gwin["PUBG"]["ul_rtt_ms"] == 80.0
      and _gwin["PUBG"]["dl_rtt_ms"] == 150.0 and _gwin["FREE_FIRE"]["ul_rtt_ms"] is None,
      str(_gwin))
check("game 合计行 RTT 加权（dl=(150×6+160×3)/9=153.33）",
      close(_gb["window_agg"]["totals"]["traffic_tb"], 9.0)
      and _gb["window_agg"]["totals"]["dl_rtt_ms"] == 153.33,
      str(_gb["window_agg"]["totals"]))
_o_db3 = kpi.KPI_DB_PATH
kpi.KPI_DB_PATH = _db_det
try:
    check("video-apps 接口 as_of 非法直接 400",
          dash.get_video_apps(days=90, as_of="2026-13-99").status_code == 400)
    _vapi = json.loads(dash.get_video_apps(days=90).body.decode("utf-8"))
    check("video-apps 接口给两套行 + 合计",
          _vapi["status"] == "ok" and _vapi["day"]["rows"] and _vapi["window_agg"]["totals"],
          str(_vapi.get("message")))
    _gapi = json.loads(dash.get_game_apps(days=90).body.decode("utf-8"))
    check("game-apps 接口 ok", _gapi["status"] == "ok", str(_gapi.get("message")))
    kpi.KPI_DB_PATH = Path(tempfile.mkdtemp(prefix="olib_vd_empty_")) / "nope.sqlite3"
    check("空库 video-apps 给友好空态（不 500）",
          json.loads(dash.get_video_apps(days=90).body.decode("utf-8"))["status"] == "empty")
finally:
    kpi.KPI_DB_PATH = _o_db3

# 「只看已完成日」与卡片层同一约定：当天（仍在累积的半天分区）不进下钻
# （放在接口检查之后：插入「今天」的行会改变上面 day 视图的新袖日）
det.upsert_video_app([{"day": date.today().isoformat(), "appname": "TIKTOK",
                       "traffic_tb": 1.0, "thr_mbps": 5.0}], path=_db_det)
_vb_today = det.build_video_apps(days=90, path=_db_det)
check("当天（未完成日）不进下钻：as_of 夹到昨天、day 视图无当天行",
      _vb_today["as_of"] == (date.today() - timedelta(days=1)).isoformat()
      and not [r for r in _vb_today["day"]["rows"] if r["appname"] == "TIKTOK"],
      str(_vb_today["as_of"]))

# persist_app_detail：只处理这次真正跑过的块；库路径跟随 svc.DATA_DIR（测试可隔离）
_svc_dir = svc.DATA_DIR
try:
    svc.DATA_DIR = Path(tempfile.mkdtemp(prefix="olib_pd_"))
    _pd = svc.persist_app_detail({"video": _vres["video"]}, "run_det")
    check("persist_app_detail 只写跑过的块（video 写入 / game 跳过）",
          _pd.get("video", {}).get("rows") == 3 and "game" not in _pd, str(_pd))
    check("persist_app_detail 落的库能被 builder 读回",
          det.build_video_apps(days=90, path=svc.kpi_db_path())["day"]["rows"], "读回失败")
    check("没跑任何块时不写库（不碰明细表）", svc.persist_app_detail({}, "run_det") == {})
finally:
    svc.DATA_DIR = _svc_dir

# 明细缺口自愈（2026-10-31）：每日增量不再走 kpi_only=True，明细要跟着 daily_kpi 一起补。
# 守的是「明细表缺了某天 → 下次增量会把它捞回来」，否则下钻会永久缺这一天。
_db_gap = Path(tempfile.mkdtemp(prefix="olib_gap_")) / "g.sqlite3"
_gap_today = date(2026, 9, 20)
det.upsert_video_app([{"day": "2026-09-15", "appname": "TIKTOK", "traffic_tb": 1.0}],
                     path=_db_gap)
det.upsert_game_app([{"day": "2026-09-15", "appname": "PUBG", "traffic_tb": 0.1}], path=_db_gap)
_gaps = det.gap_days(7, path=_db_gap, today=_gap_today, refresh_last=1)
check("明细缺口 = 窗口内两张表都没有的天 + 最新 1 天重取",
      _gaps == ["2026-09-13", "2026-09-14", "2026-09-16", "2026-09-17", "2026-09-18",
                "2026-09-19"], str(_gaps))
check("明细缺口不含当天（未完成日不落库）",
      (date(2026, 9, 20).isoformat()) not in _gaps, "当天被误算进缺口")
# 只有一张表有那天也算缺口（历史遗留：daily_video_app 是后加的，game 可能先有）
det.upsert_game_app([{"day": "2026-09-16", "appname": "PUBG", "traffic_tb": 0.1}], path=_db_gap)
check("只一张明细表有那天 → 仍算缺口（两表必须都齐）",
      "2026-09-16" in det.gap_days(7, path=_db_gap, today=_gap_today, refresh_last=0),
      "单表覆盖被当成已齐")
check("明细缺口表不存在时安全返回全窗口",
      det.gap_days(3, path=_db_gap.with_name("none.sqlite3"), today=_gap_today,
                   refresh_last=0) == ["2026-09-17", "2026-09-18", "2026-09-19"],
      "空库未返回全窗口")

# ==========================================================================
if LIVE:
    section("14. 真实 KPI 库核对（--live）")
    real = kpi.KPI_DB_PATH
    check("真实库存在", real.exists(), str(real))
    if kpi.table_exists(real):
        stored = kpi.stored_days(real)
        rb = kpi.build_overview(days=90, today=date.today())
        check("真实库 overview 状态 ok", rb["status"] == "ok", str(rb["status"]))
        cov = rb["coverage"]
        print("  [INFO] 库中 %d 天：%s ~ %s | 窗口覆盖 %d 天，缺 %d 天"
              % (len(stored), stored[0], stored[-1], cov["stored_days"],
                 len(cov["missing_days"])))
        if rb["status"] == "ok":
            cc = {c["id"]: c for c in rb["cards"]}
            tv = cc["traffic_gb"]["latest"]["value"]
            au = cc["active_user_k"]["latest"]["value"]
            th = cc["video_thr_kbps"]["latest"]["value"]
            check("总流量量级合理（10 万~100 万 GB）", 100000 <= tv <= 1000000, str(tv))
            check("活跃用户量级合理（100K~2000K）", 100 <= au <= 2000, str(au))
            check("视频速率量级合理（1~100 Mbps）", 1000 <= th <= 100000, str(th))
            check("卡片都有极值与均值",
                  all(c.get("max") and c.get("min") and c.get("avg") is not None
                      for c in rb["cards"]))
            check("日趋势点数=覆盖天数",
                  len(rb["series"]["day"]["dates"]) == cov["stored_days"])
            check("周趋势点数合理", 1 <= len(rb["series"]["week"]["labels"]) <= 20,
                  str(len(rb["series"]["week"]["labels"])))
            for cid in ("traffic_gb", "active_user_k", "video_thr_kbps", "video_share_pct"):
                print("  [INFO] %-16s 最新 %-12s 均 %-12s 最大 %-12s 最小 %-12s"
                      % (cid, cc[cid]["latest"]["value"], round(cc[cid]["avg"], 1),
                         cc[cid]["max"]["value"], cc[cid]["min"]["value"]))
    if "--live-gbase" in sys.argv:
        with vgc.VmaxGbaseClient() as cli:
            ok, info = cli.healthy()
            check("GBase 健康", ok, info)
            present, _ = cli.available_days(vgc.FAMILY_FLOW_CISERVICE, "20260901", "20260915")
            check("数仓分区可用", len(present) >= 10, str(len(present)))

# ==========================================================================
print("\n" + "=" * 62)
print("PASS=%d  FAIL=%d" % (PASS, FAIL))
if FAILED_NAMES:
    print("失败项:")
    for name in FAILED_NAMES:
        print("  - %s" % name)
print("=" * 62)
sys.exit(1 if FAIL else 0)
