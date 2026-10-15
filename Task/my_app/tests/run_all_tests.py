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

# E2E 用的后端端口。默认沿用 7038，但**该端口常被线上正式后端占着**
# （本机就是这种情况：uvicorn :7038 常驻），此时 _start_backend() 会因端口被占而
# 绑定失败，前端 8 个用例随即全红 —— 而失败原因与业务代码毫无关系
# （2026-10-15 实测：报的是 [WinError 2] + 8/8 前端失败）。
# 故这里不再死磕 7038：先探测一个空闲端口，探测不到再退回 7038。
def _port_is_free(port: int) -> bool:
    """本机该端口是否可绑定（未被占用）。"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _pick_e2e_port(preferred: int = PORT) -> int:
    """挑一个能给测试后端用的端口：优先 preferred，被占则向上找。

    找不到空闲端口时仍返回 preferred —— 让后续流程照旧失败并如实报出来，
    而不是悄悄换一个不存在的端口把真实错误藏掉。
    """
    if _port_is_free(preferred):
        return preferred
    for p in range(preferred + 1, preferred + 20):
        if _port_is_free(p):
            print(f"[i] 端口 {preferred} 已被占用（可能是线上后端），E2E 测试后端改用 {p}")
            return p
    return preferred

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


def _start_backend(port: int = PORT) -> subprocess.Popen | None:
    log = os.path.join(HERE, "reports", "backend_server.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    # 独立 venv 不存在时给出可执行的提示，而不是抛一个 WinError 2 让人猜
    # （2026-10-15：本机 tests/.venv 缺失，报错只有 "[WinError 2] 系统找不到指定的文件"）
    if not os.path.exists(VENV_PY):
        print(f"[!] 测试专用虚拟环境不存在: {VENV_PY}")
        print("    前端 E2E 需要它来起测试后端。按 tests/README_tests.md 创建：")
        print("      python -m venv tests\\.venv")
        print("      tests\\.venv\\Scripts\\pip install -r requirements.txt")
        print("      tests\\.venv\\Scripts\\pip install fastapi \"uvicorn[standard]\" httpx pandas openpyxl numpy pydantic scipy shapely sqlalchemy requests pytest playwright")
        print("      tests\\.venv\\Scripts\\python -m playwright install chromium")
        return None
    try:
        proc = subprocess.Popen(
            [VENV_PY, "-m", "uvicorn", "backend.main:app",
             "--host", "0.0.0.0", "--port", str(port)],
            cwd=PROJECT_ROOT, stdout=open(log, "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
    except Exception as e:
        print(f"[!] 无法启动后端服务: {e}")
        return None
    if not _wait_health(f"http://localhost:{port}", timeout=40):
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
        # 若用户没显式指定 --base-url，则自己挑一个空闲端口起测试后端，
        # 避免撞上常驻的线上后端（见 _pick_e2e_port 注释）。
        explicit_base = args.base_url != BASE_URL
        if not explicit_base:
            port = _pick_e2e_port()
            base = f"http://localhost:{port}"
        else:
            port = PORT
        print("==> 启动后端服务 (uvicorn :%d) ..." % port)
        proc = _start_backend(port)
    else:
        print("==> 跳过启动，使用已运行后端:", base)

    shot_dir = os.path.join(reports_dir, f"shots_{ts}")
    if proc is None and not args.skip_start:
        # 起不来就不必再打一轮必然全红的 E2E，直接如实说明
        print("==> 后端未启动成功，跳过前端 E2E（原因见上方提示）")
        frontend_rec = make_record("数据洞察 SaaS MVP", "frontend_e2e",
                                   {"base_url": base, "skipped_reason": "backend_not_started"})
        finalize_record(frontend_rec)
    else:
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
