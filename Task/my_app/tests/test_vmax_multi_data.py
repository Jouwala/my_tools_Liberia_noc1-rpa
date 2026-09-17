# -*- coding: utf-8 -*-
"""
tests/test_vmax_multi_data.py —— VMAX 多报表指标采集（vReport）离线自测
=====================================================================

覆盖范围（默认全部离线，不需要 VMAX 网络）：
  1. RSA encryptLong 分块（与前端 jsencrypt_ex.encryptData 等价，多字节字符不被劈开）
  2. report_query 条件构造（granularity 编码 / 时间窗对齐 / filters / paging）
  3. 响应解析（{"result": "..."} 包装、field/header/data、错误与 session 失效识别）
  4. 配置装载与报表选择（url.txt 里的两个 CIService 报表）
  5. 落盘（<key>_latest.json + SQLite kpi_rows 重跑覆盖）
  6. run_vmax_multi_data_sync 编排（用假客户端注入，不产生任何网络请求）

用法：
    cd D:/01_RPA/Task/my_app
    python tests/test_vmax_multi_data.py            # 离线单测
    python tests/test_vmax_multi_data.py --live     # 追加一次真实取数（需要能连 VMAX）
"""
import json
import os
import sqlite3
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.vmax_multi_data import vmax_report_client as vrc          # noqa: E402
from backend.services.vmax_multi_data import vmax_multi_data_service as svc     # noqa: E402

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


# ---------------------------------------------------------------- 1. RSA 分块
def test_encrypt():
    section("1. RSA encryptLong 分块（与前端 encryptLong 逐行对齐）")
    # 前端：byteNo%117>=114 或 ==0 且距上一刀>=114 时落刀 -> 首段 114B，其后每段 117B
    check("ASCII 300 字符 -> 114/117/69",
          [len(c) for c in vrc.split_js_chunks("a" * 300)] == [114, 117, 69],
          str([len(c) for c in vrc.split_js_chunks("a" * 300)]))
    check("ASCII 117 字符 -> 114/3",
          [len(c) for c in vrc.split_js_chunks("b" * 117)] == [114, 3],
          str([len(c) for c in vrc.split_js_chunks("b" * 117)]))
    check("ASCII 114 字符 -> 单块（正好一刀）",
          [len(c) for c in vrc.split_js_chunks("c" * 114)] == [114])
    check("ASCII 100 字符 -> 单块（<114 不切）", vrc.split_js_chunks("d" * 100) == ["d" * 100])
    check("每段明文 <= 117 字节（RSA-1024 + PKCS#1 v1.5 上限）",
          all(len(c.encode("utf-8")) <= 117 for c in vrc.split_js_chunks("e" * 1000)))

    mixed = ("x" * 113) + "中" + ("y" * 200)      # 中文 3 字节，正好跨 117 边界
    chunks = vrc.split_js_chunks(mixed)
    check("分块可无损拼回", "".join(chunks) == mixed, str([len(c) for c in chunks]))
    check("多字节字符不被劈开（每段可独立 UTF-8 解码）",
          all(c.encode("utf-8").decode("utf-8") == c for c in chunks),
          str([len(c) for c in chunks]))

    plain = json.dumps({"reportPart": "sys_5gsa_traffic_ciservice",
                        "condition": {"times": {"beginTime": "2026-09-16 00:00:00"}}},
                       ensure_ascii=False, separators=(",", ":"))
    enc = vrc.encrypt_long(plain)
    n_chunks = len(vrc.split_js_chunks(plain))
    import base64
    raw = base64.b64decode(enc)
    check("密文长度 = 128 字节/块", len(raw) == 128 * n_chunks,
          "len=%d chunks=%d" % (len(raw), n_chunks))
    check("encrypt_long 两次结果不同（PKCS#1 v1.5 随机填充）但等长",
          vrc.encrypt_long("same") != vrc.encrypt_long("same")
          and len(vrc.encrypt_long("same")) == len(vrc.encrypt_long("same")))
    envelope = vrc.encrypt_param({"a": 1})
    check("encrypt_param 返回 {'encryptedStr': ...}", list(envelope) == ["encryptedStr"]
          and isinstance(envelope["encryptedStr"], str))
    # 与线上已验证的 mars 实现（vmax_cxo_daily_cache._encrypt_param）语义一致：
    # 两者分块边界可能不同（114/117 对 117/117），但都能被服务端逐块解密后拼接，
    # 因此只校验「同为 128B 整数倍密文且非空」。
    from backend.services import vmax_cxo_daily_cache as cxo
    mars_raw = base64.b64decode(cxo._encrypt_param(plain))
    check("与 mars 历史实现同为 128B 分块密文",
          len(mars_raw) % 128 == 0 and len(raw) % 128 == 0 and mars_raw != raw)


# ---------------------------------------------------------- 2. 条件构造 / 时间窗
def test_condition():
    section("2. report_query 条件构造")
    for lit, code in vrc.GRANULARITY_CODE.items():
        cond = vrc.build_report_condition("sys_5gsa_traffic_ciservice", "2026-09-16", "2026-09-16",
                                          granularity=lit, show=["clttime", "ppb400401001"])
        got = cond["condition"]["times"]["granularity"]
        check("granularity %s -> %s" % (lit, code), got == code, "got=%s" % got)

    cond = vrc.build_report_condition("sys_5gsa_traffic_ciservice", "2026-09-16", "2026-09-16",
                                      granularity="date", show=["clttime"], top_n=200)
    times = cond["condition"]["times"]
    check("date 粒度补全天", times["beginTime"] == "2026-09-16 00:00:00"
          and times["endTime"] == "2026-09-16 23:59:59", json.dumps(times))
    check("topN/pageSize 透传", cond["condition"]["topN"] == "200"
          and cond["paging"]["pageSize"] == 200 and cond["paging"]["currentPage"] == 1)
    check("其它字段与前端一致",
          cond["reportPart"] == "sys_5gsa_traffic_ciservice" and cond["isDrill"] == 0
          and cond["area"] == [] and cond["show"] == ["clttime"]
          and cond["condition"]["filterList"] == {"filters": [], "filter_type": 0})

    cond2 = vrc.build_report_condition("sys_5gsa_video_ciservice", "2026-09-16 00:00",
                                       "2026-09-16 06:00", granularity="hour",
                                       filters=[{"fields": [{"name": "city_id", "data": ["1"],
                                                             "operator": 6}]}],
                                       session="JSESSIONID=abc", busy_hour=True)
    check("hour 粒度起始对齐", cond2["condition"]["times"]["beginTime"] == "2026-09-16 00:00:00")
    check("filters/session/bh 透传",
          cond2["condition"]["filterList"]["filters"][0]["fields"][0]["name"] == "city_id"
          and cond2["session"] == "JSESSIONID=abc" and cond2["condition"]["times"]["bh"] == "1")
    try:
        vrc.build_report_condition("x", "2026-09-16", "2026-09-16", granularity="nope")
        check("非法粒度抛错", False)
    except vrc.VmaxReportError:
        check("非法粒度抛错", True)

    b, e = vrc.time_window(1, "hour", now=datetime(2026, 9, 16, 15, 42))
    check("hour 窗口右闭到整点、跨 24 小时",
          (b, e) == (datetime(2026, 9, 15, 16), datetime(2026, 9, 16, 15)), str((b, e)))
    b2, e2 = vrc.time_window(3, "date", now=datetime(2026, 9, 16, 15, 42))
    check("date 窗口 3 天", (b2, e2) == (datetime(2026, 9, 14), datetime(2026, 9, 16)), str((b2, e2)))
    b3, e3 = vrc.time_window(1, "5min", now=datetime(2026, 9, 16, 15, 42))
    check("5min 窗口按 5 分钟对齐", e3.minute % 5 == 0 and e3 < datetime(2026, 9, 16, 15, 42))


def test_slices():
    section("2b. 时间分片 plan_time_slices / query_kpis_range")
    from datetime import datetime as dt

    sl = vrc.plan_time_slices("2026-09-01 00:00:00", "2026-09-10 23:00:00", "hour", 7)
    check("hour 10 天按 7 天切片 -> 2 片", len(sl) == 2, str([(str(a), str(b)) for a, b in sl]))
    check("分片首尾相接、无重叠",
          sl[0][1] + vrc.GRANULARITY_STEP["hour"] == sl[1][0]
          and sl[0][0] == dt(2026, 9, 1) and sl[-1][1] == dt(2026, 9, 10, 23),
          str(sl))
    sl_d = vrc.plan_time_slices("2026-06-19", "2026-09-16", "date", 30)
    check("date 90 天按 30 天切片 -> 3 片", len(sl_d) == 3, str([(str(a), str(b)) for a, b in sl_d]))
    check("date 分片覆盖 06-19 ~ 09-16",
          sl_d[0][0] == dt(2026, 6, 19) and sl_d[-1][1] == dt(2026, 9, 16), str(sl_d))
    check("单点窗口 -> 1 片",
          len(vrc.plan_time_slices("2026-09-16", "2026-09-16", "date")) == 1)
    check("chunk_days 支持按粒度给字典",
          len(vrc.plan_time_slices("2026-09-01", "2026-09-30", "date", {"date": 10})) == 3)

    # 合并/去重/截断标记（假 client：分片间给重复行）
    class _RangeStub(vrc.VmaxReportClient):
        def __init__(self, rows_per_slice, total_rows):
            self.calls = []
            self._rows = rows_per_slice
            self._total = total_rows

        def query_kpis(self, report_part, begin, end, **kw):
            self.calls.append((str(begin), str(end), kw.get("top_n")))
            recs = [dict(r) for r in self._rows]
            return {"fields": ["clttime", "city_name", "ppb400401001"],
                    "raw_fields": ["clttime", "city_name", "#ppb400401001"],
                    "headers": [], "columns": [], "records": recs, "total": len(recs),
                    "err_msg": "", "status": 0}

    dup = [{"clttime": "2026-09-01 00:00:00", "city_name": "Monrovia", "ppb400401001": "1"},
           {"clttime": "2026-09-01 01:00:00", "city_name": "Monrovia", "ppb400401001": "2"}]
    stub = _RangeStub(dup, 2)
    out = stub.query_kpis_range("sys_5gsa_traffic_ciservice", "2026-09-01", "2026-09-20",
                               granularity="hour", chunk_days=7, top_n=20000, kpis=["ppb400401001"])
    check("分片调用次数 = 片数", len(stub.calls) == len(out["slice_windows"]) == 3, str(stub.calls))
    check("跨片重复行被去重", len(out["records"]) == 2, str(len(out["records"])))
    check("记录按 clttime 排序",
          [r["clttime"] for r in out["records"]] == ["2026-09-01 00:00:00", "2026-09-01 01:00:00"])
    check("未达上限时 truncated=False", out["truncated"] is False)

    stub2 = _RangeStub(dup, 2)
    out2 = stub2.query_kpis_range("sys_5gsa_traffic_ciservice", "2026-09-01", "2026-09-02",
                                 granularity="hour", chunk_days=7, top_n=2)
    check("行数达 top_n 时标记 truncated（避免静默截断）", out2["truncated"] is True)

    # 分片失败不致命：其余分片仍然返回
    class _FlakyStub(_RangeStub):
        def query_kpis(self, report_part, begin, end, **kw):
            self.calls.append((str(begin), str(end)))
            if len(self.calls) == 1:
                raise vrc.VmaxUnavailable("boom")
            recs = [dict(r) for r in self._rows]
            return {"fields": ["clttime", "city_name", "ppb400401001"], "raw_fields": [],
                    "headers": [], "columns": [], "records": recs, "total": len(recs),
                    "err_msg": "", "status": 0}

    flaky = _FlakyStub(dup, 2)
    out3 = flaky.query_kpis_range("sys_5gsa_traffic_ciservice", "2026-09-01", "2026-09-20",
                                 granularity="hour", chunk_days=7)
    check("单分片失败被记录、其余分片照常返回",
          len(out3["errors"]) == 1 and len(out3["records"]) == 2, str(out3["errors"]))


# ---------------------------------------------------------------- 3. 响应解析
def test_parse():
    section("3. report_query 响应解析")
    inner = {"status": "0", "field": ["clttime", "city_name", "ppb400401001"],
             "header": ["Statistical Time", "City", "Traffic"],
             "data": [["2026-09-16 10:00:00", "Abidjan", "123.4"],
                      ["2026-09-16 10:00:00", "Bouake", "9.9"]],
             "total": 2}
    wrapped = {"result": json.dumps(inner)}
    parsed = vrc.parse_report_payload(wrapped)
    check("解包 {'result': json字符串}", parsed["status"] == 0 and len(parsed["records"]) == 2)
    check("field/header/data 对齐",
          parsed["fields"] == inner["field"] and parsed["headers"] == inner["header"]
          and parsed["records"][0] == {"clttime": "2026-09-16 10:00:00",
                                       "city_name": "Abidjan", "ppb400401001": "123.4"})
    check("裸 dict 兼容", vrc.parse_report_payload(inner)["total"] == 2)
    check("表内嵌一层兼容",
          len(vrc.parse_report_payload({"table": inner})["records"]) == 2)
    check("list 兼容", vrc.parse_report_payload([[1, 2]])["rows"] == [[1, 2]])

    # 实测：上游返回的指标列名带 '#' 前缀（请求里不带）
    hashed = {"status": "0",
              "field": ["clttime", "city_name", "#ppc400401001", "#ppb400401001"],
              "header": ["Statistical Time", "City", "Total Traffic", "Uplink Traffic"],
              "data": [["2026-09-16 10:00:00", "Monrovia", "7836322800716", "906622464924"]]}
    p = vrc.parse_report_payload(hashed)
    check("'#' 前缀默认去掉，可直接当列名",
          p["fields"] == ["clttime", "city_name", "ppc400401001", "ppb400401001"],
          str(p["fields"]))
    check("原始列名保留在 raw_fields",
          p["raw_fields"][2] == "#ppc400401001")
    check("records 键同步去前缀", p["records"][0]["ppc400401001"] == "7836322800716")
    check("columns 带表头标签",
          p["columns"][2] == {"id": "ppc400401001", "label": "Total Traffic"}, str(p["columns"][2]))
    check("strip_hash=False 时保留原样",
          vrc.parse_report_payload(hashed, strip_hash=False)["fields"][2] == "#ppc400401001")

    err = vrc.parse_report_payload({"status": "1", "errMsg": "Cannot read property \"times\""})
    check("错误状态可读", err["status"] == 1 and "times" in err["err_msg"])
    dead = vrc.parse_report_payload({"status": "1", "errMsg": "session invalid, please login"})
    check("session 失效可识别", dead["session_expired"] is True)
    check("非 JSON 文本不炸", "raw" in vrc.parse_report_payload("not-json"))


# ------------------------------------------------------------ 4. 配置装载
def test_config():
    section("4. 配置装载")
    cfg = svc.load_config()
    parts = [r["report_part"] for r in svc.enabled_reports(cfg)]
    check("url.txt 的 traffic 报表在配置里", "sys_5gsa_traffic_ciservice" in parts, str(parts))
    check("url.txt 的 video 报表在配置里", "sys_5gsa_video_ciservice" in parts, str(parts))
    check("两个报表默认启用", len(parts) == 2, str(parts))
    check("默认持久化开关", cfg["persist"]["write_json"] and cfg["persist"]["write_sqlite"]
          and cfg["persist"]["write_remote_db"] is False)
    check("top_n 默认给大（上游按 topN 截断，默认小了会静默丢行）",
          int(cfg["top_n"]) >= 20000 and int(cfg["page_size"]) >= 20000, str(cfg["top_n"]))
    check("chunk_days 默认按粒度配置",
          int(cfg["chunk_days"]["hour"]) >= 1 and int(cfg["chunk_days"]["date"]) >= 30,
          str(cfg["chunk_days"]))
    check("按 key 选择报表", [r["key"] for r in svc.select_reports(cfg, ["traffic"])] == ["traffic"])
    check("all 选择全部", len(svc.select_reports(cfg, ["all"])) == 2)
    check("未知 key 返回空", svc.select_reports(cfg, ["nope"]) == [])
    traffic = [r for r in cfg["reports"] if r["key"] == "traffic"][0]
    check("traffic 配了指标 id", traffic["kpis"] and all(k.startswith(("ppb", "ppc"))
                                                          for k in traffic["kpis"]), str(traffic["kpis"]))


def _sqlite_one(path, sql):
    """连接必须显式关闭（sqlite3 的 with 只提交事务，不关连接，Windows 下会锁文件）。"""
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(sql).fetchone()
    finally:
        conn.close()


# --------------------------------------------- 4b. 便捷接口 fetch_report_kpis
class _StubClient(vrc.VmaxReportClient):
    """跳过 __init__（不建 requests.Session），只验证条件拼装与结果包装。"""

    def __init__(self):
        self.seen = {}

    def default_show(self, report_part, dims=None, kpis=None):
        return ["clttime", "city_name"] + list(kpis or ["ppb400401001"])

    def query_report(self, report_part, condition, retry_on_session=True):
        self.seen["condition"] = condition
        return {"status": 0, "err_msg": "", "fields": ["clttime", "city_name", "ppb400401001"],
                "raw_fields": ["clttime", "city_name", "#ppb400401001"], "headers": [],
                "columns": [], "rows": [],
                "records": [{"clttime": "2026-09-16 10:00:00", "city_name": "Monrovia",
                             "ppb400401001": "5"}], "total": 1, "session_expired": False}


def test_convenience():
    section("4b. fetch_report_kpis 便捷接口")
    stub = _StubClient()
    old = vrc.get_client
    vrc.get_client = lambda **kw: stub
    try:
        out = vrc.fetch_report_kpis("sys_5gsa_traffic_ciservice", days_back=1,
                                    granularity="hour", kpis=["ppb400401001"])
    finally:
        vrc.get_client = old
    times = stub.seen["condition"]["condition"]["times"]
    check("实际窗口回填到结果里",
          out["window"] == [times["beginTime"], times["endTime"]] and out["window"][0] != "",
          str(out["window"]))
    check("show = 默认维度 + 指定指标",
          stub.seen["condition"]["show"] == ["clttime", "city_name", "ppb400401001"],
          str(stub.seen["condition"]["show"]))
    check("粒度回填", out["granularity"] == "hour")
    check("记录可直接使用", out["records"][0]["ppb400401001"] == "5"
          and out["raw_fields"][2] == "#ppb400401001")


# ---------------------------------------------------------------- 5. 落盘
def test_persist(tmp):
    section("5. 落盘（JSON + SQLite）")
    result = {"key": "unit", "title": "unit", "report_part": "sys_5gsa_traffic_ciservice",
              "table": "aggr_5gsa_flow_ciservice", "granularity": "hour",
              "window": {"begin": "2026-09-16 00:00:00", "end": "2026-09-16 01:00:00"},
              "fields": ["clttime", "ppb400401001"], "headers": ["t", "v"],
              "records": [{"clttime": "2026-09-16 00:00:00", "ppb400401001": "1"},
                          {"clttime": "2026-09-16 01:00:00", "ppb400401001": "2"}],
              "total": 2, "fetched_at": "2026-09-16 15:30:00"}

    old_dir, old_db = svc.DATA_DIR, svc.SQLITE_PATH
    svc.DATA_DIR = Path(tmp)
    svc.SQLITE_PATH = Path(tmp) / "test.sqlite3"
    try:
        path = svc.persist_json(result)
        check("JSON 快照写入", path.exists() and json.loads(
            path.read_text(encoding="utf-8"))["records"][1]["ppb400401001"] == "2", str(path))
        n = svc.persist_sqlite(result)
        check("SQLite 行数", n == 2)
        again = svc.persist_sqlite(result)                      # 重跑覆盖而不是追加
        cnt = _sqlite_one(svc.SQLITE_PATH, "SELECT COUNT(*) FROM kpi_rows")[0]
        one = _sqlite_one(svc.SQLITE_PATH, "SELECT row_json FROM kpi_rows WHERE row_no=1")[0]
        check("重跑覆盖（不重复累加）", again == 2 and cnt == 2, "cnt=%d" % cnt)
        check("row_json 可回读", json.loads(one)["ppb400401001"] == "2")

        svc.persist_run("sys_5gsa_traffic_ciservice", "unit", "hour", result["window"], 2, "ok")
        svc.persist_run("sys_5gsa_traffic_ciservice", "unit", "hour", result["window"], 0,
                        "failed", "connect timeout")
        runs = _sqlite_one(svc.SQLITE_PATH,
                           "SELECT COUNT(*) FROM sync_runs WHERE status='ok'")[0]
        failed = _sqlite_one(svc.SQLITE_PATH,
                             "SELECT error FROM sync_runs WHERE status='failed'")[0]
        check("sync_runs 记录成功/失败运行", runs == 1 and failed == "connect timeout",
              "ok=%s err=%s" % (runs, failed))
    finally:
        svc.DATA_DIR, svc.SQLITE_PATH = old_dir, old_db


# ------------------------------------------------------- 6. 编排（假客户端）
class _FakeClient(vrc.VmaxReportClient):
    """只替换网络与报表配置，query_kpis / query_kpis_range 走真实实现（不发请求）。"""

    def __init__(self, *a, **kw):
        pass

    def healthy(self):
        return {"transport": "fake", "ready": True, "detail": "ok"}

    def vreport_session(self, refresh=False):
        return "fakesession"

    def default_show(self, part, dims=None, kpis=None):
        return list(dims or []) + list(kpis or ["clttime", "ppb400401001"])

    def report_config(self, part, use_cache=True):
        return {"metadata": {"table": [{"id": "aggr_5gsa_flow_ciservice"}]}}

    def query_report(self, part, condition):
        return {"status": 0, "err_msg": "", "fields": ["clttime"] + condition["show"][1:],
                "headers": [], "rows": [], "records": [{"clttime": "2026-09-16 10:00:00",
                                                        "ppb400401001": "5"}],
                "total": 1, "session_expired": False}


def test_sync(tmp):
    section("6. run_vmax_multi_data_sync 编排（假客户端）")
    old_dir, old_db = svc.DATA_DIR, svc.SQLITE_PATH
    old_health = vrc.VmaxReportClient
    svc.DATA_DIR = Path(tmp)
    svc.SQLITE_PATH = Path(tmp) / "sync.sqlite3"
    svc.vrc.VmaxReportClient = _FakeClient
    try:
        summary = svc.run_vmax_multi_data_sync(reports=["traffic", "video"])
        check("状态 ok", summary["status"] == "ok", json.dumps(summary)[:200])
        check("两个报表都有结果", len(summary["reports"]) == 2, str(summary["reports"]))
        check("统计行数", summary["rows"] == 2, str(summary["rows"]))
        check("每个报表落了 json", all("json" in r for r in summary["reports"]))
        check("metadata 里的表名被带上",
              summary["reports"][0]["table"] == "aggr_5gsa_flow_ciservice")
        cnt = _sqlite_one(svc.SQLITE_PATH, "SELECT COUNT(*) FROM kpi_rows")[0]
        check("SQLite 落库 2 行", cnt == 2, "cnt=%d" % cnt)
        runs = _sqlite_one(svc.SQLITE_PATH,
                           "SELECT COUNT(*) FROM sync_runs WHERE status='ok'")[0]
        check("每次采集都写 sync_runs", runs == 2, "runs=%d" % runs)

        class _Down(_FakeClient):
            def healthy(self):
                return {"transport": "fake", "ready": False, "detail": "connect timeout"}

        svc.vrc.VmaxReportClient = _Down
        bad = svc.run_vmax_multi_data_sync(reports=["traffic"])
        check("上游不可达时返回 unavailable 而不是抛错",
              bad["status"] == "unavailable" and "connect timeout" in bad["error"])
    finally:
        svc.vrc.VmaxReportClient = old_health
        svc.DATA_DIR, svc.SQLITE_PATH = old_dir, old_db


# ---------------------------------------------------------------- 7. 真实取数
def test_live():
    section("7. 真实取数（--live）")
    client = vrc.VmaxReportClient(transport="auto")
    health = client.healthy()
    print("  health:", json.dumps(health, ensure_ascii=False)[:200])
    if not health.get("ready"):
        print("  [SKIP] VMAX 不可达，跳过真实取数")
        return
    cfg = svc.load_config()
    for report in svc.enabled_reports(cfg):
        res = svc.fetch_report(report, cfg, client=client)
        print("  %s rows=%d total=%s fields=%s" % (res["report_part"], len(res["records"]),
                                                   res["total"], res["fields"][:8]))
        for row in res["records"][:3]:
            print("    ", json.dumps(row, ensure_ascii=False)[:300])
        check("%s 取到数据" % res["report_part"], len(res["records"]) > 0)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("VMAX 多报表采集离线自测  root=%s" % ROOT)
    with tempfile.TemporaryDirectory(prefix="vmax_multi_") as tmp:
        test_encrypt()
        test_condition()
        test_slices()
        test_parse()
        test_config()
        test_convenience()
        test_persist(tmp)
        test_sync(tmp)
    if "--live" in sys.argv:
        test_live()

    print("\n================ 结果: %d passed, %d failed ================" % (PASS, FAIL))
    if FAILED_NAMES:
        print("失败用例:", ", ".join(FAILED_NAMES))
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
