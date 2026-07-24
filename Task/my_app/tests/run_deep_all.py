"""Deep test orchestrator: starts the real backend, runs backend-deep (in-process)
and frontend-deep (Playwright against the live server), merges into one record,
then stops the server.

Run:   tests/.venv/Scripts/python tests/run_deep_all.py
"""
from __future__ import annotations
import os
import sys
import time
import json
import signal
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
PROJECT_ROOT = os.path.dirname(HERE)
REPORTS = os.path.join(HERE, "reports")
VENV_PY = os.path.join(HERE, ".venv", "Scripts", "python.exe")
PORT = 7038
BASE = f"http://127.0.0.1:{PORT}"

import report_utils as ru  # noqa: E402


def _start_server():
    proc = subprocess.Popen(
        [VENV_PY, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    # wait until health is ready
    for _ in range(60):
        try:
            import urllib.request
            with urllib.request.urlopen(f"{BASE}/api/health", timeout=2) as r:
                if r.status == 200:
                    return proc
        except Exception:
            time.sleep(1)
    # give up
    try:
        proc.terminate()
    except Exception:
        pass
    raise RuntimeError("后端服务在 60s 内未能启动")


def _stop_server(proc):
    try:
        proc.send_signal(signal.CTRL_C_EVENT) if os.name == "nt" else proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_deep_all():
    os.makedirs(REPORTS, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")

    print("==> 启动后端服务 ...")
    proc = _start_server()
    print("==> 后端已就绪，开始深度测试")

    # backend deep (in-process TestClient)
    import run_deep_tests
    backend_rec = run_deep_tests.run_deep_tests(os.path.join(REPORTS, f"deep_backend_record_{ts}"))

    # frontend deep (Playwright vs live server)
    import test_frontend_deep
    shot_dir = os.path.join(REPORTS, f"deep_shots_{ts}")
    frontend_rec = test_frontend_deep.run_frontend_deep(BASE, shot_dir)

    print("==> 停止后端服务 ...")
    _stop_server(proc)

    # ---- merge into one combined record ----
    combined = ru.make_record("数据洞察 SaaS MVP · 深度测试", "deep_all", {
        "backend": "FastAPI TestClient (in-process) + uvicorn live server",
        "frontend": "Playwright Chromium (headless)", "base_url": BASE,
        "app_version": "1.0.0",
    })
    combined["cases"] = backend_rec["cases"] + frontend_rec["cases"]
    # carry diagnostics from frontend
    combined["_diagnostics"] = frontend_rec.get("_diagnostics", {})
    ru.finalize_record(combined)

    paths = ru.write_reports(combined, REPORTS, f"deep_test_record_{ts}")
    # also keep the per-suite reports (already written by each runner)
    paths["backend"] = backend_rec.get("_report_paths", {})
    paths["frontend"] = {
        "markdown": os.path.join(REPORTS, f"deep_frontend_record_{ts}.md"),
        "json": os.path.join(REPORTS, f"deep_frontend_record_{ts}.json"),
        "excel": os.path.join(REPORTS, f"deep_frontend_record_{ts}.xlsx"),
    }
    # write frontend report files too
    ru.write_reports(frontend_rec, REPORTS, f"deep_frontend_record_{ts}")

    s = combined["summary"]
    print(f"\n=== 深度测试汇总: 总计 {s['total']} | 通过 {s['passed']} | 失败 {s['failed']} | 跳过 {s['skipped']} ===")
    print("合并报告:", paths.get("markdown"))
    return combined, paths


if __name__ == "__main__":
    run_deep_all()
