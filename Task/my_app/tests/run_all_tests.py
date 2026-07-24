"""Unified test orchestrator for the 数据洞察 SaaS MVP.

What it does:
  1. Runs the backend API suite (in-process FastAPI TestClient) -> backend record.
  2. Starts the real backend (uvicorn :7038) which also serves the built SPA.
  3. Runs the Playwright frontend E2E against http://localhost:7038 -> frontend record + screenshots.
  4. Stops the backend.
  5. Merges both into one combined, timestamped test record
     (Markdown + JSON + Excel) under tests/reports/, and also keeps the
     individual backend/frontend reports.

Usage:
  python tests/run_all_tests.py                 # full run (auto-starts backend)
  python tests/run_all_tests.py --skip-start    # assume backend already on :7038
  python tests/run_all_tests.py --base-url http://host:7038
"""
from __future__ import annotations
import os
import sys
import time
import subprocess
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

VENV_PY = os.path.join(HERE, ".venv", "Scripts", "python.exe")
PORT = 7038
BASE_URL = f"http://localhost:{PORT}"

from report_utils import make_record, finalize_record, write_reports  # noqa: E402
from run_backend_tests import run_backend_tests as _run_backend  # noqa: E402
from test_frontend_e2e import run_frontend_tests as _run_frontend  # noqa: E402


def _wait_health(url: str, timeout: float = 40.0) -> bool:
    import requests
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(url + "/api/health", timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def _start_backend() -> subprocess.Popen | None:
    log = os.path.join(HERE, "reports", "backend_server.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    try:
        proc = subprocess.Popen(
            [VENV_PY, "-m", "uvicorn", "backend.main:app",
             "--host", "0.0.0.0", "--port", str(PORT)],
            cwd=PROJECT_ROOT, stdout=open(log, "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
    except Exception as e:
        print(f"[!] 无法启动后端服务: {e}")
        return None
    if not _wait_health(BASE_URL, timeout=40):
        print("[!] 后端服务在限定时间内未就绪，前端用例可能失败。")
        return proc  # still return; tests will report the failure
    print("[✓] 后端服务已就绪:", BASE_URL)
    return proc


def _stop_backend(proc: subprocess.Popen | None):
    if proc is None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-start", action="store_true", help="不启动后端，假设已在运行")
    ap.add_argument("--base-url", default=BASE_URL)
    args = ap.parse_args()
    base = args.base_url
    reports_dir = os.path.join(HERE, "reports")
    ts = time.strftime("%Y%m%d_%H%M%S")

    # 1) backend (in-process)
    print("==> 运行后端 API 测试 ...")
    backend_rec = _run_backend(os.path.join(reports_dir, f"backend_test_record_{ts}"))
    bs = backend_rec["summary"]
    print(f"    后端: 通过 {bs['passed']} / 失败 {bs['failed']} / 跳过 {bs['skipped']}")

    # 2) start backend + frontend E2E
    proc = None
    if not args.skip_start:
        print("==> 启动后端服务 (uvicorn :%d) ..." % PORT)
        proc = _start_backend()
    else:
        print("==> 跳过启动，使用已运行后端:", base)

    shot_dir = os.path.join(reports_dir, f"shots_{ts}")
    print("==> 运行前端 E2E (Playwright) ...")
    frontend_rec = _run_frontend(base, shot_dir)
    fs = frontend_rec["summary"]
    print(f"    前端: 通过 {fs['passed']} / 失败 {fs['failed']} / 跳过 {fs['skipped']}")

    _stop_backend(proc)

    # 3) merge into one combined record
    combined = make_record("数据洞察 SaaS MVP", "all", {**backend_rec["environment"],
                                                       "base_url": base})
    combined["cases"] = backend_rec["cases"] + frontend_rec["cases"]
    if frontend_rec.get("_diagnostics"):
        combined["_diagnostics"] = frontend_rec["_diagnostics"]
    finalize_record(combined)

    paths = write_reports(combined, reports_dir, f"test_record_{ts}")
    # also persist frontend individual report
    write_reports(frontend_rec, reports_dir, f"frontend_test_record_{ts}")

    s = combined["summary"]
    print("\n================ 测试汇总 ================")
    print(f"总计 {s['total']} | 通过 {s['passed']} | 失败 {s['failed']} | 跳过 {s['skipped']} | 通过率 {s.get('pass_rate')}%")
    print("合并测试记录:", paths)
    if frontend_rec.get("_diagnostics"):
        d = frontend_rec["_diagnostics"]
        print(f"前端诊断: 控制台错误 {d['console_errors_total']} | 未捕获JS异常 {d['page_errors_total']}")


if __name__ == "__main__":
    main()
