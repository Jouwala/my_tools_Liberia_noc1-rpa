"""Backend API functional test suite + detailed record generator.

Runs entirely in-process via FastAPI TestClient (no running server required).
Covers every API endpoint and produces a structured test record
(Markdown + JSON + Excel) via report_utils.

Run directly:   python tests/run_backend_tests.py
Or via orchestrator: run_all_tests.py
"""
from __future__ import annotations
import io
import os
import sys
import time
import platform
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
PROJECT_ROOT = os.path.dirname(HERE)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# We intentionally let the app's scheduler start (so task registry + next_run_time
# behave like production). We stop it at the end so the process can exit cleanly.
import backend.services.task_runner as _tr  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from backend.main import app  # noqa: E402
from backend.database import DB_PATH  # noqa: E402

from report_utils import make_record, finalize_record, write_reports  # noqa: E402

PROJECT = "数据洞察 SaaS MVP"
APP_VERSION = "1.0.0"
UPLOAD_TEST_TABLE = "test_quality_sample"  # idempotent table name (to_sql replace)


def _env() -> dict:
    return {
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.release()}",
        "backend": "FastAPI (in-process TestClient)",
        "app_version": APP_VERSION,
        "db_path": str(DB_PATH),
        "db_exists": DB_PATH.exists(),
    }


def _summarize(body) -> str:
    if body is None:
        return "(无JSON响应体)"
    if isinstance(body, dict):
        return "keys=" + ",".join(list(body.keys())[:10])
    if isinstance(body, list):
        return f"list len={len(body)}"
    return str(body)[:80]


def _req_case(record, client, *, cid, module, name, method, path, params=None,
              json_body=None, files=None, headers=None, expect=200, check=None):
    """Perform a single HTTP request and append a case to the record."""
    t0 = time.perf_counter()
    try:
        resp = client.request(method, path, params=params, json=json_body,
                               files=files, headers=headers)
        dt = (time.perf_counter() - t0) * 1000
        status = resp.status_code
        try:
            body = resp.json()
        except Exception:
            body = None
        assertions = [f"HTTP {status} == 期望 {expect}" + ("" if status == expect else " ✗")]
        passed = status == expect
        if check is not None:
            ok, msgs = check(resp, body)
            passed = passed and ok
            assertions.extend(msgs)
        extra = {"response_summary": _summarize(body)}
        err = None
    except Exception as e:  # network / runtime error
        dt = (time.perf_counter() - t0) * 1000
        status = None
        passed = False
        assertions = [f"请求异常: {e}"]
        extra = {"response_summary": "-"}
        err = repr(e)
    record["cases"].append({
        "id": cid, "module": module, "name": name,
        "method": method, "path": path, "expected": str(expect),
        "actual_status": status, "latency_ms": round(dt, 1),
        "passed": passed, "skipped": False,
        "assertions": assertions, "error": err, "extra": extra,
    })
    return status, (body if "body" in dir() else None)


def _skip_case(record, *, cid, module, name, path, reason):
    record["cases"].append({
        "id": cid, "module": module, "name": name,
        "method": "—", "path": path, "expected": "需联网/凭据",
        "actual_status": None, "latency_ms": None,
        "passed": False, "skipped": True,
        "assertions": [reason], "error": None,
        "extra": {"note": "依赖外部 eFlow API / 网络，建议手动验证"},
    })


# ---------------------------------------------------------------------------
# Individual test groups
# ---------------------------------------------------------------------------

def _test_health(client, record):
    def check(r, b):
        ok = isinstance(b, dict) and b.get("status") == "ok"
        return ok, [f"响应含 status=='ok': {ok}"]
    _req_case(record, client, cid="BE-01", module="系统", name="健康检查",
              method="GET", path="/api/health", expect=200, check=check)


def _test_db_info(client, record):
    def check(r, b):
        msgs = []
        ok = isinstance(b, dict)
        total = b.get("total_tables") if ok else None
        msgs.append(f"total_tables 存在且为 int: {isinstance(total, int)}")
        ok = ok and isinstance(total, int)
        rows = b.get("total_rows") if isinstance(b, dict) else None
        msgs.append(f"total_rows 存在: {rows is not None}")
        ok = ok and rows is not None
        return ok, msgs
    _req_case(record, client, cid="BE-02", module="系统", name="数据库概览",
              method="GET", path="/api/db/info", expect=200, check=check)


def _test_data_source_ts(client, record):
    def check(r, b):
        ok = isinstance(b, dict) and "last_sync" in b and "latest_data_time" in b
        return ok, [f"含 last_sync/latest_data_time 字段: {ok}"]
    _req_case(record, client, cid="BE-03", module="系统", name="数据源时间戳",
              method="GET", path="/api/data-source/timestamps", expect=200, check=check)


def _test_table_browse(client, record):
    # 1) list tables
    _, body = _req_case(record, client, cid="BE-10", module="表浏览器",
                        name="列出数据表", method="GET", path="/api/tables", expect=200,
                        check=lambda r, b: (isinstance(b, dict) and "tables" in b,
                                            [f"返回 tables 列表: {isinstance(b, dict) and 'tables' in b}"]))
    tables = (body or {}).get("tables", []) if isinstance(body, dict) else []
    table = next((t for t in tables if t.get("row_count", 0) > 0), (tables[0] if tables else None))
    if not table:
        _skip_case(record, cid="BE-11", module="表浏览器", name="表数据/画像/统计",
                   path="/api/tables/{name}/data|profile|stats",
                   reason="未找到可用数据表，跳过后续表浏览用例")
        return
    tname = table["name"]

    # 2) table data
    _req_case(record, client, cid="BE-11", module="表浏览器", name=f"浏览表数据 [{tname}]",
              method="GET", path=f"/api/tables/{tname}/data", params={"page": 1, "page_size": 10},
              expect=200,
              check=lambda r, b: (isinstance(b, dict) and "data" in b and "total" in b,
                                  [f"返回 data/total: {isinstance(b, dict) and 'data' in b}"]))

    # 3) profile
    _, pbody = _req_case(record, client, cid="BE-12", module="表浏览器", name=f"字段画像 [{tname}]",
                         method="GET", path=f"/api/tables/{tname}/profile", expect=200,
                         check=lambda r, b: (isinstance(b, dict) and "profile" in b,
                                             [f"返回 profile: {isinstance(b, dict) and 'profile' in b}"]))
    cols = []
    if isinstance(pbody, dict) and isinstance(pbody.get("profile"), dict):
        cols = [c["name"] for c in pbody["profile"].get("columns", [])]
    col = cols[0] if cols else None
    if col:
        _req_case(record, client, cid="BE-13", module="表浏览器", name=f"列统计 [{tname}.{col}]",
                  method="GET", path=f"/api/tables/{tname}/stats/{col}", expect=200,
                  check=lambda r, b: (isinstance(b, dict) and b.get("column") == col,
                                      [f"返回该列统计: {isinstance(b, dict) and b.get('column') == col}"]))
    else:
        _skip_case(record, cid="BE-13", module="表浏览器", name="列统计", path=f"/api/tables/{tname}/stats/{{col}}",
                   reason="画像未返回字段，跳过列统计用例")


def _test_upload_analysis(client, record):
    csv_text = "id,region,amount,created_at\n1,North,100,2024-01-01\n2,South,200,2024-01-02\n" \
               "3,North,150,2024-01-03\n4,East,300,2024-01-04\n5,West,250,2024-01-05\n"
    files = {"file": ("test_quality_sample.csv", csv_text.encode("utf-8"), "text/csv")}
    _, ubody = _req_case(record, client, cid="BE-20", module="上传/分析", name="上传Excel并自动建表",
                         method="POST", path="/api/upload", files=files, expect=200,
                         check=lambda r, b: (isinstance(b, dict) and bool(b.get("tables")),
                                             [f"返回新建表信息: {isinstance(b, dict) and bool(b.get('tables'))}"]))

    table_name = None
    if isinstance(ubody, dict) and ubody.get("tables"):
        table_name = ubody["tables"][0].get("table_name")

    if not table_name:
        _skip_case(record, cid="BE-21", module="上传/分析", name="创建分析/归档", path="/api/analysis",
                   reason="上传未返回表名，跳过分析归档用例")
        _cleanup_upload()
        return

    # create analysis
    _, abody = _req_case(record, client, cid="BE-21", module="上传/分析", name=f"生成分析并归档 [{table_name}]",
                         method="POST", path="/api/analysis",
                         json_body={"name": "自动化测试分析", "description": "由测试套件创建",
                                    "table_name": table_name, "conclusions": ["测试结论A"]},
                         expect=200,
                         check=lambda r, b: (isinstance(b, dict) and b.get("id") is not None,
                                             [f"返回分析 id: {isinstance(b, dict) and b.get('id') is not None}"]))
    aid = abody.get("id") if isinstance(abody, dict) else None

    # list analyses
    _req_case(record, client, cid="BE-22", module="上传/分析", name="分析列表检索",
              method="GET", path="/api/analysis", params={"page": 1, "page_size": 10},
              expect=200,
              check=lambda r, b: (isinstance(b, dict) and "analyses" in b and "total" in b,
                                  [f"返回 analyses/total: {isinstance(b, dict) and 'analyses' in b}"]))

    if aid is not None:
        # get detail
        _req_case(record, client, cid="BE-23", module="上传/分析", name=f"分析详情 [{aid}]",
                  method="GET", path=f"/api/analysis/{aid}", expect=200,
                  check=lambda r, b: (isinstance(b, dict) and b.get("id") == aid,
                                      [f"返回匹配 id: {isinstance(b, dict) and b.get('id') == aid}"]))
        # delete
        _req_case(record, client, cid="BE-24", module="上传/分析", name=f"删除分析 [{aid}]",
                  method="DELETE", path=f"/api/analysis/{aid}", expect=200,
                  check=lambda r, b: (isinstance(b, dict) and b.get("deleted") is True,
                                      [f"返回 deleted==True: {isinstance(b, dict) and b.get('deleted') is True}"]))
    else:
        _skip_case(record, cid="BE-23", module="上传/分析", name="分析详情/删除", path="/api/analysis/{id}",
                   reason="未获取到分析 id，跳过详情与删除用例")

    # upload history
    _req_case(record, client, cid="BE-25", module="上传/分析", name="上传历史",
              method="GET", path="/api/upload/history", expect=200,
              check=lambda r, b: (isinstance(b, dict) and "uploads" in b,
                                  [f"返回 uploads 列表: {isinstance(b, dict) and 'uploads' in b}"]))

    _cleanup_upload()


def _cleanup_upload():
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(f'DROP TABLE IF EXISTS "{UPLOAD_TEST_TABLE}"')
        conn.execute("DELETE FROM uploaded_files WHERE original_name=?", ("test_quality_sample.csv",))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _test_gis(client, record):
    _, sbody = _req_case(record, client, cid="BE-30", module="GIS地图", name="站点分布列表",
                         method="GET", path="/api/gis/sites", expect=200,
                         check=lambda r, b: (isinstance(b, (dict, list)),
                                             [f"返回站点数据(dict/list): {isinstance(b, (dict, list))}"]))
    sites = sbody.get("sites") if isinstance(sbody, dict) else (sbody if isinstance(sbody, list) else [])
    site_id = None
    if sites:
        site = sites[0]
        site_id = site.get("id") or site.get("site_id")
    if site_id is not None:
        _req_case(record, client, cid="BE-31", module="GIS地图", name=f"站点下钻 [{site_id}]",
                  method="GET", path=f"/api/gis/drilldown/{site_id}", expect=200,
                  check=lambda r, b: (isinstance(b, dict), [f"返回站点下钻(dict): {isinstance(b, dict)}"]))
    else:
        _skip_case(record, cid="BE-31", module="GIS地图", name="站点下钻", path="/api/gis/drilldown/{site_id}",
                   reason="未获取到站点 id，跳过下钻用例")

    _req_case(record, client, cid="BE-32", module="GIS地图", name="区域汇总",
              method="GET", path="/api/gis/regions/summary", expect=200,
              check=lambda r, b: (isinstance(b, (dict, list)), [f"返回区域汇总: {isinstance(b, (dict, list))}"]))
    _req_case(record, client, cid="BE-33", module="GIS地图", name="拓扑连线",
              method="GET", path="/api/gis/topology", expect=200,
              check=lambda r, b: (isinstance(b, (dict, list)), [f"返回拓扑数据: {isinstance(b, (dict, list))}"]))
    _req_case(record, client, cid="BE-34", module="GIS地图", name="区域边界",
              method="GET", path="/api/gis/region-boundaries", expect=200,
              check=lambda r, b: (isinstance(b, (dict, list)), [f"返回区域边界: {isinstance(b, (dict, list))}"]))


def _test_tt_wo(client, record):
    _req_case(record, client, cid="BE-40", module="TT&WO", name="Dashboard 综合数据",
              method="GET", path="/api/tt-wo-dashboard/overview", expect=200,
              check=lambda r, b: (isinstance(b, dict), [f"返回 overview(dict): {isinstance(b, dict)}"]))
    _req_case(record, client, cid="BE-41", module="TT&WO", name="TT/WO 明细下钻",
              method="GET", path="/api/tt-wo-dashboard/drilldown",
              params={"type": "tt", "dimension": "all_tt"}, expect=200,
              check=lambda r, b: (isinstance(b, dict), [f"返回 drilldown(dict): {isinstance(b, dict)}"]))


def _test_tasks(client, record):
    def check(r, b):
        ok = isinstance(b, dict) and isinstance(b.get("tasks"), list) and len(b["tasks"]) > 0
        return ok, [f"返回非空 tasks 列表: {ok}"]
    _req_case(record, client, cid="BE-50", module="任务管理", name="列出定时任务",
              method="GET", path="/api/tasks", expect=200, check=check)

    def check_detail(r, b):
        ok = isinstance(b, dict) and ("task_id" in b or "id" in b or "name" in b)
        return ok, [f"返回任务详情: {ok}"]
    _req_case(record, client, cid="BE-51", module="任务管理", name="任务详情 [eflow_sync]",
              method="GET", path="/api/tasks/eflow_sync", expect=200, check=check_detail)

    def check_status(r, b):
        ok = isinstance(b, dict) and "scheduler_running" in b
        return ok, [f"含 scheduler_running 字段: {ok}"]
    _req_case(record, client, cid="BE-52", module="任务管理", name="eFlow 同步状态",
              method="GET", path="/api/eflow/status", expect=200, check=check_status)

    # Manual-trigger / schedule / toggle endpoints need live eFlow API + network → skip (documented)
    _skip_case(record, cid="BE-53", module="任务管理", name="手动触发同步 (POST /api/eflow/sync)",
               path="/api/eflow/sync",
               reason="触发真实 eFlow API 同步，依赖外部网络与凭据，建议联网后手动验证。")
    _skip_case(record, cid="BE-54", module="任务管理", name="立即执行任务 (POST /api/tasks/{id}/run)",
               path="/api/tasks/{id}/run",
               reason="执行真实后台任务（含外部 API/报表生成），依赖网络，建议手动验证。")
    _skip_case(record, cid="BE-55", module="任务管理", name="启停/改期任务",
               path="/api/tasks/{id}/toggle|schedule",
               reason="改变任务调度状态，建议手动验证避免影响生产调度。")


def run_backend_tests(out_dir: str | None = None) -> dict:
    record = make_record(PROJECT, "backend_api", _env())
    # Use TestClient as a context manager so the app's startup event runs
    # (registers scheduled tasks, creates tables) — required by /api/tasks/*.
    #
    # ⚠️ client=('127.0.0.1', 12345) 是必需的，不是可选参数（2026-10-15 修复）。
    # TestClient 默认把对端伪装成主机名 **"testclient"**（不是 IP），而
    # main.py:332 的「本机回环放行」判定走 security.client_is_local() → _is_loopback()，
    # 它要求 request.client.host 是回环 **IP**；"testclient" 解析失败 → 不放行
    # → 落到 :337 返回 401「未登录：请通过统一门户登录」。
    # 现象：鉴权中间件上线后，本套件 13 个 API 用例**全部**报 401，看起来像"权限问题"，
    # 实际与本机权限、与业务代码都无关，纯粹是测试客户端的身份没被认出是回环。
    # 显式指定回环 client 后与真实本机脚本（调度器/看门狗）身份一致，既修好 401，
    # 也比"关鉴权跑测试"更贴近生产语义 —— 请勿改回 TestClient(app)。
    try:
        with TestClient(app, client=("127.0.0.1", 12345)) as client:
            _run_all(client, record)
    finally:
        # stop the background scheduler so the process can exit
        try:
            _tr.stop_scheduler()
        except Exception:
            pass
    finalize_record(record)

    if out_dir:
        ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        paths = write_reports(record, out_dir, f"backend_test_record_{ts}")
        record["_report_paths"] = paths
    return record


def _run_all(client, record) -> None:
    _test_health(client, record)
    _test_db_info(client, record)
    _test_data_source_ts(client, record)
    _test_table_browse(client, record)
    _test_upload_analysis(client, record)
    _test_gis(client, record)
    _test_tt_wo(client, record)
    _test_tasks(client, record)


if __name__ == "__main__":
    out = os.path.join(HERE, "reports")
    rec = run_backend_tests(out)
    s = rec["summary"]
    print(f"后端测试完成: 总计 {s['total']} | 通过 {s['passed']} | 失败 {s['failed']} | 跳过 {s['skipped']}")
    for c in rec["cases"]:
        tag = "SKIP" if c.get("skipped") else ("PASS" if c["passed"] else "FAIL")
        print(f"  [{tag}] {c['id']} {c['name']} -> {c.get('actual_status')}")
    print("报告:", rec.get("_report_paths"))
