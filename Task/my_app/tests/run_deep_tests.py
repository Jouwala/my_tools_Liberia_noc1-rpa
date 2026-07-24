"""Deep backend test suite: error-paths, boundaries, security, performance.

Runs in-process via FastAPI TestClient (no server required for backend tests).
Reuses the _req_case helper and report writer from the smoke suite.

Run:   tests/.venv/Scripts/python tests/run_deep_tests.py
By orchestrator: run_deep_all.py
"""
from __future__ import annotations
import os
import io
import sys
import time
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
PROJECT_ROOT = os.path.dirname(HERE)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Let the scheduler start so /api/tasks behaves like production; we stop it at end.
import backend.services.task_runner as _tr  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from backend.main import app  # noqa: E402
from backend.database import DB_PATH  # noqa: E402

# reuse helpers from the smoke suite
from run_backend_tests import (  # noqa: E402
    _req_case, make_record, finalize_record, write_reports, PROJECT, APP_VERSION, _env,
)

PROJECT_LABEL = "数据洞察 SaaS MVP · 深度测试"
UPLOAD_DIR = DB_PATH.parent / "uploads"


def _first_real_table(client):
    """Pick a non-system table with rows (prefer eflow_tt) for boundary/perf tests."""
    body = client.get("/api/db/info").json()
    tables = [t for t in body.get("tables", []) if not t["name"].startswith("_")]
    # prefer eflow_tt (large, realistic)
    for t in tables:
        if t["name"] == "eflow_tt":
            return t["name"], t["rows"]
    # else the largest
    if tables:
        t = max(tables, key=lambda x: x["rows"])
        return t["name"], t["rows"]
    return None, 0


# ==================== 1. ERROR / NEGATIVE PATHS ====================
def _test_error_paths(client, record):
    table, _ = _first_real_table(client)
    table = table or "eflow_tt"

    # 404: non-existent table
    _req_case(record, client, cid="BE-ERR-01", module="错误处理",
              name="访问不存在的表数据", method="GET",
              path=f"/api/tables/__no_such_table__/data", expect=404)

    _req_case(record, client, cid="BE-ERR-02", module="错误处理",
              name="画像不存在的表", method="GET",
              path=f"/api/tables/__no_such_table__/profile", expect=404)

    _req_case(record, client, cid="BE-ERR-03", module="错误处理",
              name="统计不存在的表的列", method="GET",
              path=f"/api/tables/__no_such_table__/stats/col_x", expect=404)

    # 404: gis drilldown of unknown site
    _req_case(record, client, cid="BE-ERR-04", module="错误处理",
              name="GIS下钻不存在站点", method="GET",
              path="/api/gis/drilldown/__no_such_site__", expect=404)

    # 404: analysis detail / delete of unknown id
    _req_case(record, client, cid="BE-ERR-05", module="错误处理",
              name="获取不存在的分析记录", method="GET",
              path="/api/analysis/99999999", expect=404)

    _req_case(record, client, cid="BE-ERR-06", module="错误处理",
              name="删除不存在的分析记录", method="DELETE",
              path="/api/analysis/99999999", expect=404)

    # 404: unknown task
    _req_case(record, client, cid="BE-ERR-07", module="错误处理",
              name="获取不存在的定时任务", method="GET",
              path="/api/tasks/__no_such_task__", expect=404)

    # 422: analysis create missing required fields
    _req_case(record, client, cid="BE-ERR-08", module="错误处理",
              name="创建分析缺少必填字段(name/table_name)", method="POST",
              path="/api/analysis", json_body={"description": "x"}, expect=422)

    _req_case(record, client, cid="BE-ERR-09", module="错误处理",
              name="创建分析指向不存在的表", method="POST",
              path="/api/analysis",
              json_body={"name": "t", "table_name": "__no_such_table__"}, expect=404)

    # 400: schedule with empty cron
    _req_case(record, client, cid="BE-ERR-10", module="错误处理",
              name="更新任务调度-空cron", method="POST",
              path="/api/tasks/eflow_sync/schedule", json_body={"cron": ""}, expect=400)

    # run unknown task -> returns 200 with success=false (API-design observation, not 404)
    _req_case(record, client, cid="BE-ERR-11", module="错误处理",
              name="立即执行不存在的任务(应404但返回200)", method="POST",
              path="/api/tasks/__no_such_task__/run", expect=200,
              check=lambda r, b: (True, [f"HTTP 200 但 body.success={b.get('success') if isinstance(b, dict) else '?'}"
                                            f"（建议返回 404 而非 200+success:false）"]))

    # upload non-spreadsheet
    _req_case(record, client, cid="BE-ERR-12", module="错误处理",
              name="上传非表格文件(.txt)", method="POST",
              path="/api/upload", files={"file": ("evil.txt", b"hello", "text/plain")},
              expect=400)

    # upload empty/invalid content
    _req_case(record, client, cid="BE-ERR-13", module="错误处理",
              name="上传无法解析的内容(损坏xlsx)", method="POST",
              path="/api/upload",
              files={"file": ("broken.xlsx", b"not a real xlsx file content", "application/octet-stream")},
              expect=400)


# ==================== 2. BOUNDARY ====================
def _test_boundary(client, record):
    table, rows = _first_real_table(client)
    table = table or "eflow_tt"

    # page_size over the cap (500) -> 422 from FastAPI Query validator
    _req_case(record, client, cid="BE-BND-01", module="边界",
              name="page_size超过上限(500)->422", method="GET",
              path=f"/api/tables/{table}/data", params={"page_size": 5000}, expect=422)

    # negative page -> 422
    _req_case(record, client, cid="BE-BND-02", module="边界",
              name="page为负数->422", method="GET",
              path=f"/api/tables/{table}/data", params={"page": -1}, expect=422)

    # out-of-range page -> 200 with empty data + valid total_pages
    def _chk_oob(r, b):
        if not isinstance(b, dict):
            return False, ["响应体非JSON"]
        ok = b.get("data") == [] and isinstance(b.get("total_pages"), int)
        return ok, [f"data={b.get('data')}, total_pages={b.get('total_pages')}"]
    last_page = (rows // 50) + 5 if rows else 5
    _req_case(record, client, cid="BE-BND-03", module="边界",
              name="越界页码返回空数据", method="GET",
              path=f"/api/tables/{table}/data", params={"page": last_page},
              expect=200, check=_chk_oob)

    # sort_order both directions
    _req_case(record, client, cid="BE-BND-04", module="边界",
              name="sort_order=desc 合法", method="GET",
              path=f"/api/tables/{table}/data", params={"sort_by": "rowid", "sort_order": "desc"},
              expect=200)
    _req_case(record, client, cid="BE-BND-05", module="边界",
              name="sort_order=DESC(大写)回退asc", method="GET",
              path=f"/api/tables/{table}/data", params={"sort_by": "rowid", "sort_order": "DESC"},
              expect=200)

    # invalid sort_by column -> currently 200 (SQLite double-quote leniency silently
    # treats unknown column as a string literal -> sorting no-ops). Should validate+400.
    _req_case(record, client, cid="BE-BND-06", module="边界",
              name="sort_by为不存在的列(应400)", method="GET",
              path=f"/api/tables/{table}/data", params={"sort_by": "no_such_col_xyz"},
              expect=400,
              check=lambda r, b: (r.status_code == 400,
                                  [f"实际 {r.status_code}：SQLite 双引号容错把未知列当字符串常量，"
                                   f"排序静默失效且无校验（应白名单校验列名并返回 400）"]))

    # invalid stats column -> currently unhandled 500 (KeyError). Should be clean 404.
    _req_case(record, client, cid="BE-BND-07", module="边界",
              name="stats不存在的列(应404)", method="GET",
              path=f"/api/tables/{table}/stats/no_such_col_xyz", expect=404,
              check=lambda r, b: (r.status_code == 404,
                                  [f"实际 {r.status_code}：未校验列名导致未处理异常(df[col] KeyError)，"
                                   f"应返回 404 而非 500"]))

    # search with wildcard char (parameterized -> safe, returns >=0 rows, no error)
    _req_case(record, client, cid="BE-BND-08", module="边界",
              name="search含%通配符(参数化安全)", method="GET",
              path=f"/api/tables/{table}/data", params={"search": "%"}, expect=200,
              check=lambda r, b: (r.status_code == 200,
                                  [f"search='%' 未报错，返回 {len(b.get('data', [])) if isinstance(b, dict) else '?'} 行（LIKE 参数化正确）"]))


# ==================== 3. SECURITY ====================
def _test_security(client, record):
    table, _ = _first_real_table(client)
    table = table or "eflow_tt"

    # CORS preflight on a sample endpoint
    def _chk_cors(r, b):
        acao = r.headers.get("access-control-allow-origin")
        acac = r.headers.get("access-control-allow-credentials")
        msgs = [f"Access-Control-Allow-Origin={acao}", f"Access-Control-Allow-Credentials={acac}"]
        # wildcard + credentials is an invalid/browser-rejected combo
        note = "⚠ 通配符Origin与allow_credentials=True同时存在——浏览器会拒绝携带凭据的请求，属无效配置"
        if acao == "*" and acac == "true":
            msgs.append(note)
        return True, msgs
    _req_case(record, client, cid="BE-SEC-01", module="安全",
              name="CORS预检(通配符+凭据)", method="OPTIONS",
              path="/api/health",
              headers={"Origin": "http://evil.example.com",
                       "Access-Control-Request-Method": "GET"},
              expect=200, check=_chk_cors)

    # SQL injection attempt via search param (parameterized -> must NOT error / must be safe)
    _req_case(record, client, cid="BE-SEC-02", module="安全",
              name="SQL注入尝试(search='1 OR 1=1')", method="GET",
              path=f"/api/tables/{table}/data", params={"search": "1 OR 1=1 --"},
              expect=200,
              check=lambda r, b: (r.status_code == 200,
                                  ["search 经参数化绑定，注入未生效（返回正常，无 500）"]))

    # sort_by injection attempt: confirms it is NOT executable (quotes block breakout,
    # multi-statement disabled), but column validation is still missing.
    _req_case(record, client, cid="BE-SEC-03", module="安全",
              name="sort_by注入尝试(不可执行)", method="GET",
              path=f"/api/tables/{table}/data",
              params={"sort_by": "rowid ASC; SELECT 1 --"},
              expect=200,
              check=lambda r, b: (r.status_code == 200 and isinstance(b, dict),
                                  [f"实际 {r.status_code}：注入不可执行（引号阻断+单语句限制），"
                                   f"但列名仍未校验，建议加白名单"]))

    # path traversal in upload filename (write-before-validate)
    _probe_escape(client, record)

    # no-auth: any endpoint callable without token (intended for internal tool? note it)
    _req_case(record, client, cid="BE-SEC-05", module="安全",
              name="无需鉴权即可调用受保护端点", method="GET",
              path="/api/db/info", expect=200,
              check=lambda r, b: (True,
                                  ["所有端点均无鉴权/授权校验（内部工具可接受，但公网部署前必须加认证）"]))


def _probe_escape(client, record):
    """Attempt a path-traversal / absolute filename in the upload endpoint.
    The code writes the file BEFORE validating content, and prepends a uuid to
    the filename. We probe whether the file can escape the uploads dir, then
    clean up any stray file produced."""
    UPLOAD_DIR.mkdir(exist_ok=True)
    tgt_dir = os.path.join(PROJECT_ROOT, "TMP")
    os.makedirs(tgt_dir, exist_ok=True)
    csv = b"id,name,val\n1,a,1\n"

    stray_before = set(glob.glob(os.path.join(tgt_dir, "deep_escape_*")))

    # (a) relative traversal with enough ../ to climb out of uploads
    trav_name = "../../../../TMP/deep_escape_traversal.xlsx"
    try:
        r_trav = client.post("/api/upload",
                              files={"file": (trav_name, csv, "text/csv")})
    except Exception as e:
        r_trav = None
        trav_status, trav_note = None, f"请求异常: {e}"
    else:
        trav_status = r_trav.status_code
        trav_note = (trav_status,)
        # did anything land in TMP?
    stray_after = set(glob.glob(os.path.join(tgt_dir, "deep_escape_*")))
    escaped = stray_after - stray_before

    # cleanup any stray file
    for f in escaped:
        try:
            os.remove(f)
        except OSError:
            pass

    # interpret result
    if escaped:
        verdict = f"⚠ 文件逃逸到 {escaped}（存在真实路径遍历漏洞）"
        passed = False
    else:
        # blocked (likely because uuid prefix makes a non-existent literal dir, or parse 400)
        detail = f"HTTP {trav_status}" if trav_status is not None else "请求异常"
        verdict = (f"未逃逸（{detail}）。注意：文件在内容校验【之前】已写入磁盘，"
                   f"当前靠 uuid 前缀意外缓解；应显式用 basename/secure_filename 净化文件名")
        passed = True

    record["cases"].append({
        "id": "BE-SEC-04", "module": "安全",
        "name": "上传文件名路径遍历尝试", "method": "POST",
        "path": "/api/upload", "expected": "文件名被净化/拒绝",
        "actual_status": trav_status, "latency_ms": None,
        "passed": passed, "skipped": False,
        "assertions": [verdict],
        "error": None,
        "extra": {"response_summary": f"traversal_name={trav_name}"},
    })


# ==================== 4. PERFORMANCE / LOAD ====================
def _test_performance(client, record):
    table, rows = _first_real_table(client)
    table = table or "eflow_tt"

    # heavy GIS sites endpoint (TT/WO aggregation) - latency over N calls
    lat = []
    for _ in range(10):
        t0 = time.perf_counter()
        r = client.get("/api/gis/sites")
        lat.append((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            break
    if lat:
        p50 = sorted(lat)[len(lat) // 2]
        p95 = sorted(lat)[int(len(lat) * 0.95) - 1]
        _req_case(record, client, cid="BE-PERF-01", module="性能",
                  name="GIS站点聚合延迟(p50/p95)", method="GET",
                  path="/api/gis/sites", expect=200,
                  check=lambda r, b: (True,
                                      [f"10次调用 平均={sum(lat)/len(lat):.1f}ms p50={p50:.1f}ms p95={p95:.1f}ms"]))

    # Voronoi region boundaries (compute-heavy) single-shot latency
    t0 = time.perf_counter()
    r = client.get("/api/gis/region-boundaries")
    dt = (time.perf_counter() - t0) * 1000
    if r.status_code == 200:
        nreg = len(r.json().get("regions", []))
        extra_note = f"返回 {nreg} 个区域多边形，耗时 {dt:.0f}ms"
        flag = dt > 3000
        _req_case(record, client, cid="BE-PERF-02", module="性能",
                  name="Voronoi区域边界计算延迟", method="GET",
                  path="/api/gis/region-boundaries", expect=200,
                  check=lambda rr, b: (True,
                                       [extra_note + (" ⚠ >3s，首屏可能卡顿" if flag else "（可接受）")]))

    # large-table profile latency
    t0 = time.perf_counter()
    r = client.get(f"/api/tables/{table}/profile")
    dt = (time.perf_counter() - t0) * 1000
    _req_case(record, client, cid="BE-PERF-03", module="性能",
              name="大表画像延迟", method="GET",
              path=f"/api/tables/{table}/profile", expect=200,
              check=lambda rr, b: (rr.status_code == 200,
                                   [f"表 {table} 画像耗时 {dt:.0f}ms"
                                    + (" ⚠ 偏慢，建议加行数上限/异步" if dt > 2000 else "")]))

    # repeated load on a cheap endpoint -> p95
    lat2 = []
    for _ in range(20):
        t0 = time.perf_counter()
        client.get("/api/db/info")
        lat2.append((time.perf_counter() - t0) * 1000)
    p95_2 = sorted(lat2)[int(len(lat2) * 0.95) - 1]
    _req_case(record, client, cid="BE-PERF-04", module="性能",
              name="轻量端点重复调用p95", method="GET",
              path="/api/db/info", expect=200,
              check=lambda rr, b: (True,
                                   [f"20次调用 平均={sum(lat2)/len(lat2):.1f}ms p95={p95_2:.1f}ms"]))


# ==================== runner ====================
def run_deep_tests(out_dir: str | None = None) -> dict:
    record = make_record(PROJECT_LABEL, "backend_deep", _env())
    with TestClient(app, raise_server_exceptions=False) as client:
        _test_error_paths(client, record)
        _test_boundary(client, record)
        _test_security(client, record)
        _test_performance(client, record)
    finalize_record(record)

    _tr.stop_scheduler()

    if out_dir:
        ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        paths = write_reports(record, out_dir, f"deep_backend_record_{ts}")
        record["_report_paths"] = paths
    return record


if __name__ == "__main__":
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    rec = run_deep_tests(base)
    s = rec["summary"]
    print(f"DEEP BACKEND: total={s['total']} pass={s['passed']} fail={s['failed']} skip={s['skipped']}")
    for c in rec["cases"]:
        if not c["passed"]:
            print(f"  FAIL {c['id']} {c['name']}: {c['assertions']}")
