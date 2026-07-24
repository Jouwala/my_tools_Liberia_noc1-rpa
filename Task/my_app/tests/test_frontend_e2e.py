"""Frontend E2E smoke test + detailed record generator (Playwright).

The backend serves the built SPA at http://<host>:<port>/ (default 7038),
so we point Playwright at the running backend. The SPA is a single page that
switches views via the Ant Design menu (no URL routing), so we click each
menu item and assert the view renders without JS errors.

Requires: playwright + chromium installed in the venv.
Run directly:   python tests/test_frontend_e2e.py [base_url]
Orchestrated by: run_all_tests.py (starts the backend, then runs this).
"""
from __future__ import annotations
import os
import sys
import time
import platform
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from report_utils import make_record, finalize_record  # noqa: E402

PROJECT = "数据洞察 SaaS MVP"

# (case_id, menu_label, [expected-texts-any], note)
PAGES = [
    ("FE-01", "数据总览", ["数据表总数", "数据总行数", "核心业务表"], "Overview"),
    ("FE-02", "TT&WO Dashboard", ["SLA", "MTTR", "Domain", "Alarm"], "TT&WO Dashboard"),
    ("FE-03", "GIS地图", ["站点总数", "区域筛选", "站点"], "GIS Map"),
    ("FE-04", "分析仪表盘", ["选择数据表", "生成分析", "分析名称"], "Dashboard"),
    ("FE-05", "表浏览器", ["选择数据表", "数据浏览", "字段画像"], "Table Browser"),
    ("FE-06", "数据上传", ["点击或拖拽", "上传Excel文件", "上传结果"], "Data Upload"),
    ("FE-07", "分析归档", ["搜索分析名称", "分析名称", "ID"], "Archive"),
    ("FE-08", "任务管理", ["任务管理", "立即同步", "调度时间"], "Task Manager"),
]

ERROR_TEXT_HINTS = ["加载失败", "无法加载", "Failed to load", "error"]


def _env(base_url: str) -> dict:
    return {
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.release()}",
        "browser": "Playwright Chromium (headless)",
        "app_version": "1.0.0",
        "base_url": base_url,
    }


def run_frontend_tests(base_url: str = "http://localhost:7038",
                       screenshot_dir: str | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    record = make_record(PROJECT, "frontend_e2e", _env(base_url))
    if screenshot_dir:
        os.makedirs(screenshot_dir, exist_ok=True)

    console_errors: list[str] = []
    page_errors: list[str] = []
    app_failures: list[str] = []  # same-origin 4xx/5xx

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-CN", viewport={"width": 1440, "height": 900})
        page = context.new_page()

        page.on("console", lambda m: console_errors.append(f"[{m.type}] {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("response", lambda r: (
            app_failures.append(f"{r.status} {r.url}")
            if r.status >= 400 and r.url.startswith(base_url) else None
        ))
        page.on("requestfailed", lambda r: (
            app_failures.append(f"REQFAIL {r.url} ({r.failure})")
            if r.url.startswith(base_url) else None
        ))

        # initial load
        try:
            page.goto(base_url, wait_until="load", timeout=30000)
        except Exception as e:
            record["cases"].append({
                "id": "FE-00", "module": "加载", "name": "打开应用首页",
                "method": "GET", "path": base_url, "expected": "页面加载",
                "actual_status": None, "latency_ms": None, "passed": False, "skipped": False,
                "assertions": [f"首页加载失败: {e}"], "error": repr(e),
                "extra": {"screenshot": None},
            })
            browser.close()
            finalize_record(record)
            return record

        # wait for the Ant Design menu to render
        try:
            page.wait_for_selector("li.ant-menu-item", timeout=15000)
        except Exception as e:
            record["cases"].append({
                "id": "FE-00", "module": "加载", "name": "菜单渲染",
                "method": "-", "path": base_url, "expected": "菜单出现",
                "actual_status": None, "latency_ms": None, "passed": False, "skipped": False,
                "assertions": [f"菜单未渲染: {e}"], "error": repr(e),
                "extra": {"screenshot": None},
            })
            browser.close()
            finalize_record(record)
            return record

        for cid, label, expected_texts, note in PAGES:
            t0 = time.perf_counter()
            before_console = len(console_errors)
            before_page = len(page_errors)
            before_fail = len(app_failures)
            shot = None
            assertions = []
            try:
                page.locator("li.ant-menu-item", has_text=label).first.click(timeout=10000)
                # wait for any expected text to appear
                found = None
                for txt in expected_texts:
                    try:
                        page.get_by_text(txt, exact=False).first.wait_for(timeout=12000)
                        found = txt
                        break
                    except Exception:
                        continue
                dt = (time.perf_counter() - t0) * 1000

                # detect visible error banners
                page_text = page.content()
                err_hint = next((h for h in ERROR_TEXT_HINTS if h in page_text), None)

                new_page_err = page_errors[before_page:]
                new_fail = app_failures[before_fail:]

                passed = bool(found) and not new_page_err and not new_fail
                if found:
                    assertions.append(f"渲染预期内容: 命中「{found}」")
                else:
                    assertions.append("未命中任何预期文本 (可能接口慢/报错)")
                if err_hint:
                    assertions.append(f"页面出现错误提示关键字: 「{err_hint}」")
                if new_page_err:
                    assertions.append(f"发生未捕获 JS 异常: {new_page_err[0]}")
                if new_fail:
                    assertions.append(f"同源请求失败: {new_fail[0]}")
                # note console errors (informational)
                new_console = console_errors[before_console:]
                if new_console:
                    assertions.append(f"控制台 error 日志 {len(new_console)} 条 (详见错误信息)")

                if screenshot_dir:
                    shot = os.path.join(screenshot_dir, f"{cid}.png")
                    try:
                        page.screenshot(path=shot, full_page=False)
                    except Exception:
                        shot = None
            except Exception as e:
                dt = (time.perf_counter() - t0) * 1000
                passed = False
                assertions = [f"交互异常: {e}"]
                if screenshot_dir:
                    shot = os.path.join(screenshot_dir, f"{cid}.png")
                    try:
                        page.screenshot(path=shot, full_page=False)
                    except Exception:
                        shot = None

            record["cases"].append({
                "id": cid, "module": "前端页面", "name": f"{note} ({label})",
                "method": "CLICK", "path": f"menu::{label}", "expected": "视图渲染且无JS错误",
                "actual_status": None, "latency_ms": round(dt, 1),
                "passed": passed, "skipped": False,
                "assertions": assertions, "error": None,
                "extra": {"screenshot": os.path.relpath(shot, HERE) if shot else None,
                          "note": note},
            })

        # capture global console/page errors for the record's environment section
        record["_diagnostics"] = {
            "console_errors_total": len(console_errors),
            "page_errors_total": len(page_errors),
            "app_request_failures": app_failures,
            "page_errors": page_errors[:20],
            "console_errors": console_errors[:50],
        }
        browser.close()

    finalize_record(record)
    return record


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:7038"
    shot_dir = os.path.join(HERE, "reports", "shots_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    rec = run_frontend_tests(base, shot_dir)
    s = rec["summary"]
    print(f"前端测试完成: 总计 {s['total']} | 通过 {s['passed']} | 失败 {s['failed']} | 跳过 {s['skipped']}")
    for c in rec["cases"]:
        tag = "SKIP" if c.get("skipped") else ("PASS" if c["passed"] else "FAIL")
        print(f"  [{tag}] {c['id']} {c['name']}")
    print("截图目录:", shot_dir)
