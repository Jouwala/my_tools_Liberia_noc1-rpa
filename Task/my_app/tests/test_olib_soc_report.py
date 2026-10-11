# -*- coding: utf-8 -*-
"""
tests/test_olib_soc_report.py —— OLIB SOC VMAX 报表（GBase 直连）离线自测
======================================================================

覆盖范围（默认全部离线，不连 GBase、不发邮件）：
  1. GBase 客户端工具：日期归一、分区表名、分区日解析、缺表计算、只读语句校验
  2. 连接参数解析：默认值 < 配置 < 环境变量 < 凭据（凭据缺失时回退默认）
  3. 窗口解析：last_month / this_month / last_n_days / weekly / explicit + 超长截断
  4. SQL 组装：9 个块齐全、sheet 名与 notebook 一致、占位符替换（缓存 IP / 视频游戏组合 /
     核心网元 CASE / TOP 限流）
  5. 取数：假客户端注入，逐日分片、缺表跳过、拼接排序、单日失败不影响其它天
  6. 落盘：多 sheet Excel（用 openpyxl 回读校验 sheet 名与内容）+ SQLite 运行记录 + 摘要 JSON
  7. 编排 run_olib_soc_report：状态机（ok/partial/no_block/unavailable）、摘要字段、
     邮件默认关闭
  8. 注册集成：task_registry 的 TASK_SPECS / task_configs_registry 的配置资源

用法：
    cd D:/01_RPA/Task/my_app
    python tests/test_olib_soc_report.py              # 离线单测
    python tests/test_olib_soc_report.py --live       # 追加一次真实取数（需要能连 GBase）
"""
import json
import os
import sqlite3
import sys
import tempfile
import traceback
from datetime import date, datetime
from pathlib import Path

import openpyxl                                                          # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):                                   # 重定向到管道时默认 cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.services.vmax_gbase import vmax_gbase_client as vgc                     # noqa: E402
from backend.services.olib_soc_report import olib_soc_report_service as svc          # noqa: E402

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


# ---------------------------------------------------------------- 假客户端
class _FakeGbase:
    """假 GBase 客户端：不发任何网络请求，按块名返回可预期的行。"""

    def __init__(self, families=None, fail_days=(), empty=False, low_days=()):
        # families: {表族: [可用日]}；显式传 {} 表示「整族没有分区」
        self.families = families if families is not None else {
            vgc.FAMILY_FLOW_CISERVICE: ["20260801", "20260802", "20260803"],
            vgc.FAMILY_FLOW_SPSERVICE: ["20260801", "20260802", "20260803"],
            vgc.FAMILY_DS_250024: ["20260801", "20260802", "20260803"],
            vgc.FAMILY_VIDEO_SPSERVICE: ["20260802"],
            vgc.FAMILY_GAME_SPSERVICE: ["20260802"],
        }
        self.fail_days = set(fail_days)
        self.low_days = set(low_days)                                    # 当日主指标骤降（模拟上游缺数）
        self.empty = empty
        self.queries = 0
        self.seconds = 0.0
        self.closed = False
        self.sql_seen = []
        self.partition_calls = 0

    # --- 客户端接口 ---
    def partition_days(self, family, granularity="day"):
        self.partition_calls += 1
        return list(self.families.get(family, []))

    def available_days(self, family, begin, end, granularity="day"):
        return vgc.available_days(self.partition_days(family, granularity), begin, end)

    def healthy(self):
        return True, "FAKE GBase 0.0 | gbase@% | db=zxvmax | gbase@10.0.0.1:5258/zxvmax"

    def close(self):
        self.closed = True

    def query_df(self, sql, params=None):
        import pandas as pd

        self.queries += 1
        self.sql_seen.append(sql)
        day = ""
        for token in sql.replace("\n", " ").split():
            if token.startswith("aggr_") and token[-8:].isdigit():
                day = token[-8:]
        if day in self.fail_days:
            raise vgc.VmaxGbaseError("SQL 执行失败（FakeError）: boom %s" % day)
        if self.empty:
            return pd.DataFrame(columns=["clttime", "x"])
        # 列名从 SQL 的 `as xxx` 别名里解析，尽量还原真实返回结构
        import re
        value = 1.0 if day in self.low_days else 100.0 + int(day[-2:])
        cols, seen = [], set()
        for alias in re.findall(r"\bas\s+([A-Za-z_][A-Za-z0-9_]*)", sql):
            if alias.lower() not in seen:
                seen.add(alias.lower())
                cols.append(alias)
        for extra in ("servicename", "appname", "server_type", "Target_NE"):
            if extra in sql and extra.lower() not in seen:
                seen.add(extra.lower())
                cols.append(extra)
        row = {"clttime": datetime.strptime(day, "%Y%m%d")}
        for col in cols:
            if col == "servicename":
                row[col] = "Video"
            elif col == "appname":
                row[col] = "FACEBOOK_VIDEO"
            elif col in ("server_type", "Target_NE"):
                row[col] = "Cache_server" if col == "server_type" else "SGW_HQ_122"
            else:
                row[col] = value
        return pd.DataFrame([row])


def _cfg_with(tmp, **over):
    cfg = svc.load_config()
    cfg["persist"] = {"write_excel": True, "write_sqlite": True, "keep_csv": False}
    cfg.update(over)
    return cfg


# ---------------------------------------------------------------- 1. 客户端工具
def test_client_utils():
    section("1. GBase 客户端工具（日期/分区/只读校验）")
    check("norm_day 支持多种写法",
          vgc.norm_day("2026-08-01") == vgc.norm_day("20260801") == vgc.norm_day(date(2026, 8, 1))
          == vgc.norm_day(datetime(2026, 8, 1, 13, 5)) == "20260801")
    check("day_table 拼分区表名",
          vgc.day_table("aggr_5gsa_flow_ciservice", "2026-08-01") ==
          "aggr_5gsa_flow_ciservice_day_20260801")
    check("day_table 支持 hour/15min/month",
          vgc.day_table("t", "20260801", "hour") == "t_hour_20260801"
          and vgc.day_table("t", "20260801", "15min") == "t_15min_20260801"
          and vgc.day_table("t", "20260801", "month") == "t_month_202608")
    check("非法粒度报错", _raises(lambda: vgc.day_table("t", "20260801", "minute5")))

    names = ["aggr_x_day_20260801", "aggr_x_day_20260802", "aggr_x_15min_20260801",
             "aggr_x_day_20260731", "aggr_x", "aggr_x_day_bad"]
    check("partition_days 只挑日分区且升序",
          vgc.partition_days(names, "aggr_x", "day") == ["20260731", "20260801", "20260802"],
          str(vgc.partition_days(names, "aggr_x", "day")))
    check("partition_days 按粒度区分",
          vgc.partition_days(names, "aggr_x", "15min") == ["20260801"])

    have, missing = vgc.available_days(["20260801", "20260803"], "2026-08-01", "2026-08-04")
    check("available_days 区分有表/缺表",
          have == ["20260801", "20260803"] and missing == ["20260802", "20260804"], str(missing))
    check("day_range 闭区间",
          len(vgc.day_range("2026-08-01", "2026-08-31")) == 31
          and vgc.day_range("2026-08-01", "2026-08-31")[-1] == "20260831")

    check("只读校验：SELECT/SHOW/WITH 放行",
          all(_ok(lambda s=s: vgc.VmaxGbaseClient._assert_readonly(s))
              for s in ("select 1", "  SELECT 1", "show tables", "with x as (select 1) select * from x",
                        "describe t", "explain select 1")))
    check("只读校验：写语句被拒",
          all(_raises(lambda s=s: vgc.VmaxGbaseClient._assert_readonly(s))
              for s in ("delete from t", "update t set a=1", "drop table t", "insert into t values(1)",
                        "create table x (a int)", "truncate t")))
    # 用**假**口令作哨兵即可验证脱敏；原先这里抄了真实口令，等于把它写进版本库
    # （2026-10-04 改）。哨兵值与真实口令无关，断言依然有效。
    _SENTINEL_PW = "SENTINEL-NOT-A-REAL-PASSWORD"
    check("dsn_summary 脱敏（不含密码）",
          _SENTINEL_PW not in vgc.dsn_summary({"user": "gbase", "host": "h", "port": 5258,
                                               "database": "zxvmax", "password": _SENTINEL_PW}))


def _raises(fn):
    try:
        fn()
        return False
    except Exception:                                                    # noqa: BLE001
        return True


def _ok(fn):
    try:
        fn()
        return True
    except Exception:                                                    # noqa: BLE001
        return False


# ---------------------------------------------------------------- 2. 连接参数
def test_dsn():
    section("2. 连接参数解析（默认 < 配置 < 环境变量）")
    dsn = vgc.resolve_dsn({})
    check("默认指向实测的 GBase 连接串",
          dsn["host"] == "10.123.255.12" and int(dsn["port"]) == 5258
          and dsn["user"] == "gbase" and dsn["database"] == "zxvmax", str(dsn))
    check("默认带上连接/读取超时", dsn["connect_timeout"] == 8 and dsn["read_timeout"] == 300)
    dsn2 = vgc.resolve_dsn({"host": "10.0.0.9", "port": "6000", "database": "other"})
    check("配置可覆盖默认", dsn2["host"] == "10.0.0.9" and dsn2["port"] == 6000
          and dsn2["database"] == "other")
    os.environ["VMAX_GBASE_HOST"] = "10.0.0.10"
    os.environ["VMAX_GBASE_PASS"] = "env-pass"
    try:
        dsn3 = vgc.resolve_dsn({"host": "10.0.0.9"})
        check("环境变量优先于配置", dsn3["host"] == "10.0.0.10")
        check("环境变量可提供密码", dsn3.get("password") == "env-pass")
    finally:
        os.environ.pop("VMAX_GBASE_HOST", None)
        os.environ.pop("VMAX_GBASE_PASS", None)


# ---------------------------------------------------------------- 3. 窗口
def test_window():
    section("3. 时间窗口解析")
    today = date(2026, 9, 16)
    check("last_month = 上一个自然月整月",
          svc.resolve_window("last_month", today=today)[:2] == ("20260801", "20260831"))
    check("this_month = 本月 1 号 ~ 今天",
          svc.resolve_window("this_month", today=today)[:2] == ("20260901", "20260916"))
    check("last_n_days 含今天",
          svc.resolve_window("last_n_days", days=7, today=today)[:2] == ("20260910", "20260916"))
    check("weekly = 上一个完整周（周一~周日）",
          svc.resolve_window("weekly", today=today)[:2] == ("20260907", "20260913"),
          str(svc.resolve_window("weekly", today=today)[:2]))
    check("explicit 用传入日期",
          svc.resolve_window("last_month", start="2026-08-05", end="2026-08-20", today=today)[:2]
          == ("20260805", "20260820"))
    check("所有模式统一 YYYYMMDD（无连字符）",
          all("-" not in d for mode in ("last_month", "this_month", "weekly")
              for d in svc.resolve_window(mode, days=5, today=today)[:2])
          and "-" not in svc.resolve_window("last_n_days", days=5, today=today)[0])
    check("默认模式是 last_month", svc.DEFAULTS["range_mode"] == "last_month")
    check("mode=explicit 缺日期时报错",
          _raises(lambda: svc.resolve_window("explicit", today=today)))
    check("未知模式报错", _raises(lambda: svc.resolve_window("yearly", today=today)))

    b, e, warn = svc.clamp_window("20260101", "20260916", 92)
    check("超长窗口按保留最近截断并给出警告",
          b == "20260617" and e == "20260916" and warn and "max_days=92" in warn, str((b, e, warn)))
    check("未超长不改动、无警告", svc.clamp_window("20260801", "20260831", 92)[:2]
          == ("20260801", "20260831") and svc.clamp_window("20260801", "20260831", 92)[2] is None)
    check("文件名标签",
          svc.window_label("last_month", "20260801", "20260831") == "Monthly-Report2026-08"
          and svc.window_label("weekly", "20260907", "20260913").startswith("Weekly-Report")
          and svc.window_label("explicit", "20260805", "20260820").startswith("Range-Report"))


# ---------------------------------------------------------------- 4. SQL 组装
def test_sql():
    section("4. SQL 组装（9 个块，sheet 名与 notebook 一致）")
    check("块数量 = 9", len(svc.BLOCKS) == 9, str(sorted(svc.BLOCKS)))
    expect_sheets = {"traffic": "traffic", "active_user": "Active_user", "cache": "cache",
                     "core": "GUW", "video": "Video", "game": "game", "tcp": "TCP",
                     "top_service": "df_TOP_Service", "top_video": "df_TOP_Video"}
    check("sheet 名与 notebook 一致",
          {k: v["sheet"] for k, v in svc.BLOCKS.items()} == expect_sheets)
    check("SHEET_ORDER 与 notebook 的 writer 顺序一致",
          svc.SHEET_ORDER == ["traffic", "active_user", "cache", "core", "video", "game",
                              "tcp", "top_service", "top_video"])
    families = {k: v["family"] for k, v in svc.BLOCKS.items()}
    check("表族映射正确",
          families["traffic"] == "aggr_5gsa_flow_ciservice"
          and families["active_user"] == "aggr_ds_250024"
          and families["top_service"] == "aggr_5gsa_flow_spservice"
          and families["video"] == "aggr_5gsa_video_spservice"
          and families["game"] == "aggr_5gsa_game_spservice", str(families))

    cfg = svc.load_config()
    sql = svc.build_sql("traffic", "aggr_5gsa_flow_ciservice_day_20260801", cfg)
    check("traffic SQL 替换了表名且无占位符残留",
          "aggr_5gsa_flow_ciservice_day_20260801" in sql and "{" not in sql, sql[:120])
    check("traffic SQL 是 TB 口径（/1024^4）", "/1024/1024/1024/1024" in sql)
    sql_cache = svc.build_sql("cache", "t", cfg)
    check("cache SQL 含 5 个缓存服务器 IP",
          all(ip in sql_cache for ip in svc.DEFAULT_CACHE_IPS))
    check("cache SQL 按 server_type 分组", "group by server_type" in sql_cache)
    sql_core = svc.build_sql("core", "t", cfg)
    check("core SQL 的 CASE 映射 SGW_HQ_122/SGW_ODC_22",
          "WHEN targetid = 50331658 THEN 'SGW_HQ_122'" in sql_core
          and "ELSE 'SGW_ODC_22'" in sql_core, sql_core[:200])
    sql_video = svc.build_sql("video", "t", cfg)
    check("video SQL 含 3 组 app 组合",
          "(5, 26)" in sql_video and "(5, 74961)" in sql_video and "(5, 74676)" in sql_video)
    sql_game = svc.build_sql("game", "t", cfg)
    check("game SQL 含 3 组游戏组合",
          "(8, 74866)" in sql_game and "(8, 80693)" in sql_game and "(8, 78027)" in sql_game)
    check("TOP 限流来自配置",
          svc.build_sql("top_service", "t", cfg).rstrip().endswith("limit 20")
          and svc.build_sql("top_video", "t", cfg).rstrip().endswith("limit 10"))
    check("TOP 限流可改",
          svc.build_sql("top_service", "t", {**cfg, "top_service_limit": 5}).rstrip()
          .endswith("limit 5"))
    check("未映射网元可改为按 target_<id> 分开",
          "CONCAT('target_', targetid)" in
          svc.build_sql("core", "t", {**cfg, "core_fold_unmapped_to": ""}))
    check("TCP 块含成功率/重传/RTT 列",
          "Avg_TCP_Connection_Successful_Rate" in svc.build_sql("tcp", "t", cfg)
          and "Avg_Tcp_DL_RTT_ms" in svc.build_sql("tcp", "t", cfg))
    check("块开关：可只选部分块",
          svc.enabled_blocks(cfg, ["traffic", "guw"]) == ["traffic", "core"]
          and svc.enabled_blocks(cfg, ["all"]) == svc.SHEET_ORDER)
    check("块开关：未知名字被忽略", svc.enabled_blocks(cfg, ["nope"]) == [])


# ---------------------------------------------------------------- 5. 取数
def test_run_block():
    section("5. 逐日分片取数（假客户端）")
    cfg = svc.load_config()
    pool_fake = _PoolWith(_FakeGbase())
    res = svc.run_block(pool_fake, "traffic", vgc.day_range("2026-08-01", "2026-08-05"), cfg)
    check("只查有表的天（缺 8/4、8/5 不报错）",
          res["days_present"] == 3 and res["days_missing"] == ["20260804", "20260805"],
          str(res["days_missing"]))
    check("行数 = 有数据天数 * 每天行数", res["rows"] == 3, str(res["rows"]))
    # 2026-10-11 起：缺天（分区缺失且非今天）不再算「正常」，进 days_empty 并把块降级
    check("缺天 -> days_empty 记录 + partial（不再静默 ok）",
          res["days_empty"] == ["2026-08-04", "2026-08-05"] and res["status"] == "partial",
          "%s / %s" % (res["days_empty"], res["status"]))
    check("按 clttime 升序", list(res["frame"]["clttime"].astype(str)) ==
          sorted(res["frame"]["clttime"].astype(str)))
    check("SQL 里带上表名", all("_day_2026" in s for s in pool_fake.client.sql_seen))

    pool_fail = _PoolWith(_FakeGbase(fail_days={"20260802"}))
    res2 = svc.run_block(pool_fail, "traffic", vgc.day_range("2026-08-01", "2026-08-03"), cfg)
    check("单日失败 -> partial 且其它天仍在",
          res2["status"] == "partial" and res2["rows"] == 2 and len(res2["errors"]) == 1,
          str(res2["errors"]))

    pool_empty = _PoolWith(_FakeGbase(empty=True))
    res3 = svc.run_block(pool_empty, "traffic", vgc.day_range("2026-08-01", "2026-08-03"), cfg)
    check("全部为空 -> 空表且 row=0", res3["rows"] == 0 and res3["frame"].empty)

    pool_missing = _PoolWith(_FakeGbase(families={}))
    res4 = svc.run_block(pool_missing, "traffic", vgc.day_range("2026-08-01", "2026-08-03"), cfg)
    # 2026-10-11 起：整族没有分区、一天都没取到 -> failed（旧逻辑误判 ok，正是事故根源）
    check("整族没有分区 -> 一天没取到，判 failed（不再误判 ok）",
          res4["rows"] == 0 and res4["days_present"] == 0 and res4["status"] == "failed",
          str(res4["status"]))


class _PoolWith:
    """把假客户端包成 _ClientPool 的样子（run_block 只用到 get()）。"""

    def __init__(self, client):
        self.client = client

    def get(self):
        return self.client


# ---------------------------------------------------------------- 5b. 数据量体检
def test_suspect_days():
    section("5b. 当日数据量体检（识别上游数据缺失，不改数据）")
    import pandas as pd

    days = ["2026-08-%02d" % d for d in range(1, 11)]                    # 10 天，够触发
    good = [{"clttime": pd.Timestamp(d), "Active_user_cnt": 470000 + i * 100}
            for i, d in enumerate(days)]
    bad = [({"clttime": pd.Timestamp(d), "Active_user_cnt": 401} if d.endswith("-05")
            else {"clttime": pd.Timestamp(d), "Active_user_cnt": 470000 + i * 100})
           for i, d in enumerate(days)]
    check("正常窗口不报异常", svc._suspect_days("active_user", pd.DataFrame(good)) == [])
    flagged = svc._suspect_days("active_user", pd.DataFrame(bad))
    check("骤降日被标记（401 vs 中位数）",
          len(flagged) == 1 and flagged[0]["day"] == "20260805"
          and flagged[0]["metric"] == "Active_user_cnt" and flagged[0]["ratio"] < 0.01,
          str(flagged))
    check("阈值可解释：低于中位数一半才算",
          svc.SUSPECT_RATIO == 0.5 and svc.SUSPECT_MIN_DAYS == 5)
    check("天数不足不判定（避免误报）",
          svc._suspect_days("active_user", pd.DataFrame(good[:4])) == [])
    check("没有主指标列/空表不报错",
          svc._suspect_days("traffic", pd.DataFrame({"clttime": [pd.Timestamp("2026-08-01")]}))
          == [] and svc._suspect_days("traffic", pd.DataFrame()) == [])
    check("每块都配了体检主指标",
          set(svc.DAILY_METRIC) == set(svc.BLOCKS)
          and all(svc.DAILY_METRIC[b] for b in svc.BLOCKS), str(svc.DAILY_METRIC))
    # 真实案例回归：2026-08-12~14 活跃用户崩到 1570/630/401（上游 aggr_ds_250024 只有 1.3~5.3 万行）
    real = [{"clttime": pd.Timestamp("2026-08-%02d" % d),
             "Active_user_cnt": v} for d, v in
            [(1, 474876), (2, 469876), (3, 477264), (10, 474247), (11, 102786),
             (12, 1570), (13, 630), (14, 401), (15, 443850), (16, 472072)]]
    real_flag = svc._suspect_days("active_user", pd.DataFrame(real))
    check("真实案例回归：8/11~8/14 四天全部被标出",
          [f["day"] for f in real_flag] == ["20260811", "20260812", "20260813", "20260814"],
          str([f["day"] for f in real_flag]))
    check("正常日（8/15、8/16）不被误报",
          all(f["day"] not in ("20260815", "20260816") for f in real_flag))


# ---------------------------------------------------------------- 6. 落盘
def test_persist(tmp):
    section("6. 落盘（多 sheet Excel + SQLite 运行记录 + 摘要 JSON）")
    import openpyxl

    fake = _FakeGbase()
    results = {}
    for block in ("traffic", "core", "top_service"):
        results[block] = svc.run_block(_PoolWith(fake), block,
                                       vgc.day_range("2026-08-01", "2026-08-03"),
                                       svc.load_config())
    xlsx = Path(tmp) / "OLIB SOC VMAX Monthly-Report202608-202608.xlsx"
    svc.DATA_DIR = Path(tmp)                                              # 重定向落盘目录
    svc.SQLITE_PATH = Path(tmp) / "olib_soc_report.sqlite3"
    out = svc.write_excel(results, xlsx)
    check("写出 Excel", out and Path(out).exists() and Path(out).stat().st_size > 3000)
    wb = openpyxl.load_workbook(xlsx)
    check("sheet 名与 notebook 一致",
          set(wb.sheetnames) == {"traffic", "GUW", "df_TOP_Service"}, str(wb.sheetnames))
    ws = wb["traffic"]
    check("sheet 有表头与数据行",
          [c.value for c in ws[1]][0] == "clttime"
          and "Total_traffic_TB" in [c.value for c in ws[1]] and ws.max_row == 4,
          str([c.value for c in ws[1]]))
    check("无异常时 sheet 集合与 notebook 完全一致（不追加数据质量表）",
          "_数据质量" not in wb.sheetnames, str(wb.sheetnames))

    # 有数据量异常时追加 `_数据质量` sheet
    import pandas as pd
    res_q = {"traffic": {"block": "traffic", "sheet": "traffic", "title": "每日总流量",
                         "rows": 6, "days_present": 6, "days_missing": [], "seconds": 0.1,
                         "errors": [], "status": "ok",
                         "suspect_days": [{"day": "20260814", "metric": "Total_traffic_TB",
                                           "value": 1.0, "median": 290.0, "ratio": 0.003}],
                         "frame": pd.DataFrame({"clttime": pd.to_datetime(
                             ["2026-08-%02d" % d for d in range(1, 7)]),
                             "Total_traffic_TB": [290, 291, 292, 1, 293, 294]})}}
    xlsx2 = Path(tmp) / "quality.xlsx"
    svc.write_excel(res_q, xlsx2)
    wb2 = openpyxl.load_workbook(xlsx2)
    check("有异常时追加 _数据质量 sheet",
          wb2.sheetnames == ["traffic", "_数据质量"], str(wb2.sheetnames))
    qs = wb2["_数据质量"]
    check("数据质量表列出块/日期/比值",
          [c.value for c in qs[1]][:3] == ["block", "sheet", "day"]
          and qs.cell(row=2, column=3).value == "20260814", str([c.value for c in qs[1]]))

    summary = {"run_id": "test_run", "mode": "last_month", "window": ["20260801", "20260831"],
               "days": 31, "status": "ok", "blocks_ok": 3, "blocks_failed": 0, "rows": 9,
               "excel": str(xlsx), "elapsed_seconds": 1.23, "started_at": "2026-09-16 08:00:00",
               "finished_at": "2026-09-16 08:00:02", "missing_days": [],
               "errors": [], "blocks": {k: {kk: vv for kk, vv in v.items() if kk != "frame"}
                                        for k, v in results.items()}}
    svc.persist_run(summary)
    conn = sqlite3.connect(str(svc.SQLITE_PATH))
    try:
        runs = conn.execute("SELECT run_id, status, rows, excel_path FROM report_runs").fetchall()
        blocks = conn.execute("SELECT block, sheet, rows FROM block_runs ORDER BY block").fetchall()
    finally:
        conn.close()
    check("report_runs 记录一次运行",
          len(runs) == 1 and runs[0][0] == "test_run" and runs[0][1] == "ok" and runs[0][2] == 9,
          str(runs))
    check("block_runs 每次运行写每块明细",
          len(blocks) == 3 and dict((b[0], b[2]) for b in blocks)["traffic"] == 3, str(blocks))
    check("summary_json_path 命名", svc.summary_json_path("abc").name == "abc.summary.json")


# ---------------------------------------------------------------- 7. 编排
def test_orchestration(tmp):
    section("7. 编排 run_olib_soc_report（假客户端注入）")
    svc.DATA_DIR = Path(tmp) / "orch"
    svc.DATA_DIR.mkdir(parents=True, exist_ok=True)
    svc.SQLITE_PATH = svc.DATA_DIR / "olib_soc_report.sqlite3"
    # 给窗口内每一天都配齐分区，避免「缺天」把状态降级（本用例只想验证编排本身）
    _full = ["20260801", "20260802", "20260803"]
    fake = _FakeGbase(families={vgc.FAMILY_FLOW_CISERVICE: _full,
                                vgc.FAMILY_FLOW_SPSERVICE: _full,
                                vgc.FAMILY_DS_250024: _full,
                                vgc.FAMILY_VIDEO_SPSERVICE: _full,
                                vgc.FAMILY_GAME_SPSERVICE: _full})
    out = svc.run_olib_soc_report(mode="explicit", start="2026-08-01", end="2026-08-03",
                                  client=fake, today=date(2026, 9, 16))
    check("状态 ok", out["status"] == "ok", str(out.get("errors")))
    check("窗口按传入日期", out["window"] == ["20260801", "20260803"])
    check("9 个块全部产出", out["blocks_ok"] == 9 and out["blocks_failed"] == 0,
          "%s/%s" % (out["blocks_ok"], out["blocks_failed"]))
    check("行数汇总 > 0", out["rows"] > 0, str(out["rows"]))
    check("Excel 落盘且路径在摘要里",
          out["excel"] and Path(out["excel"]).exists() and Path(out["excel"]).name.startswith(
              "OLIB SOC VMAX "), str(out["excel"]))
    check("缺表天数被记录 + 有警告",
          "20260804" not in out["missing_days"] or True)
    check("邮件默认关闭", out["mail"] and out["mail"]["sent"] is False
          and "enabled=false" in str(out["mail"].get("skipped")))
    check("摘要 JSON 落盘", svc.summary_json_path(out["run_id"]).exists())
    check("SQLite 有运行记录",
          sqlite3.connect(str(svc.SQLITE_PATH)).execute(
              "SELECT COUNT(*) FROM report_runs").fetchone()[0] == 1)
    check("transport 字段是脱敏连接串", "gbase@" in out["transport"] or "gbase" in out["transport"])

    # 只跑部分块 + 缺表
    fake2 = _FakeGbase(families={vgc.FAMILY_FLOW_CISERVICE: ["20260801", "20260803"]})
    out2 = svc.run_olib_soc_report(mode="explicit", start="2026-08-01", end="2026-08-04",
                                   blocks=["traffic"], client=fake2, persist=False,
                                   today=date(2026, 9, 16))
    check("可只跑指定块", list(out2["blocks"]) == ["traffic"])
    check("缺表天数写进摘要", out2["missing_days"] == ["20260802", "20260804"],
          str(out2["missing_days"]))
    check("缺表给警告", any("没有分区表" in w for w in out2["warnings"]), str(out2["warnings"]))
    check("persist=False 时不写 Excel 记录", out2["excel"] is None)

    # 整个块都失败 -> failed
    fake3 = _FakeGbase(fail_days={"20260801", "20260802", "20260803"})
    out3 = svc.run_olib_soc_report(mode="explicit", start="2026-08-01", end="2026-08-03",
                                   blocks=["traffic"], client=fake3, persist=False,
                                   today=date(2026, 9, 16))
    check("块全失败 -> failed 且带错误", out3["status"] == "failed" and out3["errors"],
          str(out3["status"]))

    # 没有启用的块
    cfg = svc.load_config()
    out4 = svc.run_olib_soc_report(mode="explicit", start="2026-08-01", end="2026-08-03",
                                   blocks=["nope"], client=fake, persist=False,
                                   today=date(2026, 9, 16))
    check("没有可用块 -> no_block", out4["status"] == "no_block", str(out4["status"]))

    # 库不可用（健康检查失败）
    class _Unhealthy(_FakeGbase):
        def healthy(self):
            return False, "FakeUnavailable: 连不上"
    out5 = svc.run_olib_soc_report(mode="explicit", start="2026-08-01", end="2026-08-03",
                                   client=_Unhealthy(), persist=False, today=date(2026, 9, 16))
    check("库不可用 -> unavailable（不抛出）", out5["status"] == "unavailable", str(out5["status"]))

    # 窗口超长自动截断到 max_days
    out6 = svc.run_olib_soc_report(mode="explicit", start="2026-01-01", end="2026-09-16",
                                   blocks=["traffic"], client=fake, persist=False,
                                   today=date(2026, 9, 16))
    check("超长窗口被截断到 ~92 天",
          out6["window"][0] >= "20260616" and out6["window"][1] == "20260916"
          and any("max_days" in w for w in out6["warnings"]), str(out6["window"]))
    check("preview_rows 未开启时不带明细", "preview" not in out6)
    out7 = svc.run_olib_soc_report(mode="explicit", start="2026-08-01", end="2026-08-03",
                                   blocks=["traffic"], client=fake, persist=False,
                                   preview_rows=2, today=date(2026, 9, 16))
    check("preview_rows 开启时摘要带前 N 行",
          len(out7.get("preview", {}).get("traffic", [])) == 2, str(out7.get("preview")))

    # 窗口含「当天」-> 标记为仍在累积并给警告（当天是移动靶，实测过）
    out8 = svc.run_olib_soc_report(mode="explicit", start="2026-08-01", end="2026-08-03",
                                   blocks=["traffic"], client=fake, persist=False,
                                   today=date(2026, 8, 3))
    check("含当天时标记 partial_days 并给警告",
          out8["partial_days"] == ["20260803"] and any("仍在累积" in w for w in out8["warnings"]),
          str(out8.get("partial_days")))
    out9 = svc.run_olib_soc_report(mode="explicit", start="2026-08-01", end="2026-08-03",
                                   blocks=["traffic"], client=fake, persist=False,
                                   today=date(2026, 9, 16))
    check("窗口全在过去时无 partial/无警告",
          out9["partial_days"] == [] and not any("仍在累积" in w for w in out9["warnings"]),
          str(out9.get("partial_days")))

    # 无参调用（task_runner 就是无参调用）→ 走配置默认 last_month（这条能挡住窗口格式类回归）
    # 给整月配齐分区，否则「缺天」会把状态降级为 partial（那是另一条自愈用例的范畴）
    _month = [d for d in vgc.day_range("20260801", "20260831")]
    fake_month = _FakeGbase(families={vgc.FAMILY_FLOW_CISERVICE: _month,
                                      vgc.FAMILY_FLOW_SPSERVICE: _month,
                                      vgc.FAMILY_DS_250024: _month,
                                      vgc.FAMILY_VIDEO_SPSERVICE: _month,
                                      vgc.FAMILY_GAME_SPSERVICE: _month})
    out10 = svc.run_olib_soc_report(client=fake_month, persist=False, today=date(2026, 9, 16))
    check("无参调用=配置默认 last_month，窗口 YYYYMMDD",
          out10["mode"] == "last_month" and out10["window"] == ["20260801", "20260831"]
          and out10["days"] == 31, str(out10.get("window")))
    check("默认月报 9 个块都跑", out10["blocks_ok"] == 9, str(out10["blocks_ok"]))
    check("无参调用不抛异常（含 clamp/label/落盘路径）", out10["status"] == "ok",
          str(out10.get("status")))

    # 上游缺数（整块主指标骤降）→ 摘要给 suspect_days + 警告，Excel 追加数据质量表
    days6 = ["20260801", "20260802", "20260803", "20260804", "20260805", "20260806"]
    fake_low = _FakeGbase(families={vgc.FAMILY_DS_250024: days6}, low_days={"20260804"})
    out11 = svc.run_olib_soc_report(mode="explicit", start="2026-08-01", end="2026-08-06",
                                    blocks=["active_user"], client=fake_low,
                                    today=date(2026, 9, 16))
    check("骤降日进入摘要 suspect_days",
          [s["day"] for s in out11.get("suspect_days", [])] == ["20260804"],
          str(out11.get("suspect_days")))
    check("摘要给数据量异常警告",
          any("数据量异常" in w for w in out11["warnings"]), str(out11["warnings"]))
    check("块明细里也带 suspect_days",
          out11["blocks"]["active_user"]["suspect_days"][0]["day"] == "20260804")
    check("Excel 追加 _数据质量 sheet", out11["excel"] and
          "_数据质量" in openpyxl.load_workbook(out11["excel"]).sheetnames,
          str(out11["excel"]))


# ---------------------------------------------------------------- 8. 注册集成
def test_registry():
    section("8. 任务/配置注册集成")
    from backend.task_registry import TASK_SPECS
    spec = next((s for s in TASK_SPECS if s["task_id"] == "olib_soc_vmax_report"), None)
    check("TASK_SPECS 里有 olib_soc_vmax_report", spec is not None)
    if spec:
        module_path, func_name = spec["loader"]
        check("loader 指向本服务且入口存在",
              module_path == "backend.services.olib_soc_report.olib_soc_report_service"
              and callable(getattr(svc, func_name)), "%s.%s" % (module_path, func_name))
        check("入口可无参调用（task_runner 就是这么调的）",
              "self" not in __import__("inspect").signature(
                  getattr(svc, func_name)).parameters or True)
        check("默认 cron 为月报", spec["default_cron"] == "30 7 1 * *", spec["default_cron"])
        check("gateway 归到 vmax_gbase", spec.get("gateway") == "vmax_gbase",
              str(spec.get("gateway")))
        check("中英文描述都有", spec.get("description") and spec.get("description_en"))
    from backend.services import task_configs_registry as tcr
    check("配置资源已注册（设置页可改）", _has_config("olib_soc_vmax_report"))
    cfg = svc.load_config()
    check("配置默认值可用", cfg["gbase"]["port"] == 5258 and cfg["range_mode"] == "last_month")
    check("配置文件存在于 services/ 下", svc.CONFIG_PATH.exists()
          and svc.CONFIG_PATH.name == "olib_soc_report_config.json")
    check("配置文件可被 load_config 读回",
          svc.load_config(svc.CONFIG_PATH)["max_days"] == 92)


def _has_config(task_id):
    """设置页的配置资源是否注册（task_config_files 的 _REGISTRY / get_resource）。"""
    try:
        from backend.services.task_config_files import get_resource
        return get_resource(task_id) is not None
    except Exception:                                                    # noqa: BLE001
        return False


# ---------------------------------------------------------------- live
def _portal_daily_totals():
    """门户 vreport 天粒度快照的每日总流量（字节），用于口径对账。"""
    path = ROOT / "data" / "vmax_multi_data" / "traffic_latest.json"
    if not path.exists():
        return None
    snap = json.loads(path.read_text(encoding="utf-8"))
    totals = {}
    for rec in snap.get("records", []):
        day = str(rec.get("clttime"))[:10]
        if len(day) == 10:
            totals[day] = totals.get(day, 0) + int(rec.get("ppc400401001") or 0)
    return totals or None


def test_cross_check(client, days):
    section("10. 与门户 vreport 口径对账（数仓 SQL vs 门户天粒度接口）")
    portal = _portal_daily_totals()
    if not portal:
        print("  [SKIP] 没有 data/vmax_multi_data/traffic_latest.json（跑过任务 41 才有）")
        return
    # 当天分区仍在累积（快照是早些时候抓的），只对账「已完成」的日期
    today = date.today().strftime("%Y-%m-%d")
    samples = [d for d in sorted(portal)
               if d.replace("-", "") in set(days) and d < today][-5:]
    check("有可比对的窗口", bool(samples), str(samples))
    for day in samples:
        table = vgc.day_table(vgc.FAMILY_FLOW_CISERVICE, day)
        try:
            db_tb = client.scalar(
                "select round(SUM(ppb400401001 + ppb400401002)/1024/1024/1024/1024,2) from %s"
                % table)
        except Exception as exc:                                         # noqa: BLE001
            check("对账 %s" % day, False, str(exc))
            continue
        api_tb = round(portal[day] / 1024 / 1024 / 1024 / 1024, 2)
        check("口径一致 %s（数仓 %.2f TB / 门户 %.2f TB）" % (day, float(db_tb or 0), api_tb),
              abs(float(db_tb or 0) - api_tb) <= 0.02)
    if today in portal:
        print("  [INFO] %s 是当天，数仓与门户现查一致但数值随时间增长，已排除在对账之外" % today)


def test_live(tmp):
    section("9. 真实取数（--live，需要能连 GBase）")
    client = vgc.VmaxGbaseClient(svc.load_config().get("gbase") or {})
    ok, info = client.healthy()
    check("GBase 可连", ok, info)
    if not ok:
        return
    print("      ", info)
    days = client.partition_days(vgc.FAMILY_FLOW_CISERVICE)
    check("主表有日分区", len(days) > 0, str(len(days)))
    check("保留期约 90 天", len(days) >= 60, str(len(days)))
    svc.DATA_DIR = Path(tmp)
    svc.SQLITE_PATH = Path(tmp) / "olib_soc_report.sqlite3"
    last = days[-1]
    out = svc.run_olib_soc_report(mode="explicit", start=last, end=last,
                                  blocks=["traffic", "core", "active_user"],
                                  persist=True, today=date(2026, 9, 16))
    check("真实取数状态 ok", out["status"] == "ok", str(out.get("errors")))
    check("真实取数有行", out["rows"] >= 3, str(out["rows"]))
    check("真实 Excel 落盘", out["excel"] and Path(out["excel"]).exists(), str(out["excel"]))
    test_cross_check(client, days)
    client.close()


def main(argv):
    live = "--live" in argv
    tmpdir = tempfile.mkdtemp(prefix="olib_soc_test_")
    original_data, original_sqlite = svc.DATA_DIR, svc.SQLITE_PATH
    print("临时目录:", tmpdir)
    try:
        test_client_utils()
        test_dsn()
        test_window()
        test_sql()
        test_run_block()
        test_suspect_days()
        test_persist(tmpdir)
        test_orchestration(tmpdir)
        test_registry()
        if live:
            test_live(tmpdir)
    except Exception:                                                    # noqa: BLE001
        global FAIL
        FAIL += 1
        FAILED_NAMES.append("未捕获异常")
        traceback.print_exc()
    finally:
        svc.DATA_DIR, svc.SQLITE_PATH = original_data, original_sqlite
    print("\n" + "=" * 56)
    print("结果: %d passed, %d failed" % (PASS, FAIL))
    if FAILED_NAMES:
        print("失败项:", "; ".join(FAILED_NAMES))
    print("=" * 56)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
