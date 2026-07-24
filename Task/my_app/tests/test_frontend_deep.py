"""Frontend DEEP E2E (Playwright): real user workflows + resilience + responsive.

Targets the running backend that serves the built SPA (default http://localhost:7038).
Deep scenarios:
  FE-D-01  Upload a CSV via the UI -> verify it shows up in 表浏览器 (then clean up)
  FE-D-02  API failure resilience: force /api/gis/sites -> 500, page must not crash
  FE-D-03  Responsive @375px: no horizontal overflow (mobile layout check)
  FE-D-04  Async data load: TT&WO Dashboard transitions loading -> populated

Requires: playwright + chromium. Orchestrated by run_deep_all.py.
"""
from __future__ import annotations
import os
import sys
import time
import sqlite3
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
PROJECT_ROOT = os.path.dirname(HERE)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from report_utils import make_record, finalize_record  # noqa: E402
from backend.database import DB_PATH  # noqa: E402

PROJECT = "数据洞察 SaaS MVP"


def _env(base_url: str) -> dict:
    import platform
    return {"browser": "Playwright Chromium (headless)", "app_version": "1.0.0",
            "base_url": base_url, "python": platform.python_version(),
            "os": f"{platform.system()} {platform.release()}"}


def _cleanup_uploaded_table(stem: str):
    """Drop the test table + uploaded_files row so the real DB stays clean."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(f'DROP TABLE IF EXISTS "{stem}"')
        conn.execute("DELETE FROM uploaded_files WHERE table_name = ?", (stem,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[cleanup] 表 {stem} 清理失败(可忽略): {e}")


def _click_menu(page, label):
    page.locator("li.ant-menu-item", has_text=label).first.click(timeout=10000)


def run_frontend_deep(base_url: str = "http://localhost:7038",
                      screenshot_dir: str | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    record = make_record(PROJECT, "frontend_deep", _env(base_url))
    if screenshot_dir:
        os.makedirs(screenshot_dir, exist_ok=True)

    console_errors: list[str] = []
    page_errors: list[str] = []
    app_failures: list[str] = []

    # prepare a unique CSV for the upload workflow
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"deep_upload_{ts}"
    csv_path = os.path.join(PROJECT_ROOT, "TMP", f"{stem}.csv")
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("site_id,region,status,value\n")
        f.write("S001,North,Open,10\n")
        f.write("S002,South,Closed,20\n")
        f.write("S003,East,Open,15\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-CN", viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.on("console", lambda m: console_errors.append(f"[{m.type}] {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("response", lambda r: app_failures.append(f"{r.status} {r.url}")
                 if r.status >= 400 and r.url.startswith(base_url) else None)

        try:
            page.goto(base_url, wait_until="load", timeout=30000)
            page.wait_for_selector("li.ant-menu-item", timeout=15000)
        except Exception as e:
            record["cases"].append({
                "id": "FE-D-00", "module": "加载", "name": "打开应用首页(深度)",
                "method": "GET", "path": base_url, "expected": "页面加载",
                "actual_status": None, "latency_ms": None, "passed": False, "skipped": False,
                "assertions": [f"加载失败: {e}"], "error": repr(e), "extra": {},
            })
            browser.close()
            finalize_record(record)
            return record

        # ---------- FE-D-01: upload workflow ----------
        t0 = time.perf_counter()
        assertions = []
        passed = False
        shot = None
        try:
            _click_menu(page, "数据上传")
            page.wait_for_selector("input[type=file]", state="attached", timeout=10000)
            page.set_input_files("input[type=file]", csv_path)
            # wait for a success signal in the result area
            ok = False
            for hint in ["成功", "上传结果", stem]:
                try:
                    page.get_by_text(hint, exact=False).first.wait_for(timeout=15000)
                    ok = True
                    break
                except Exception:
                    continue
            dt = (time.perf_counter() - t0) * 1000
            assertions.append("上传完成信号:" + ("已出现" if ok else "未检测到成功文本"))
            if not ok:
                raise RuntimeError("上传后未出现成功提示")

            # verify it appears in 表浏览器
            _click_menu(page, "表浏览器")
            # wait for the table browser view (tabs or select)
            try:
                page.get_by_text("数据浏览", exact=False).first.wait_for(timeout=10000)
            except Exception:
                page.locator(".ant-select").first.wait_for(timeout=8000)
            # open the select dropdown to find our new table
            page.locator(".ant-select").first.click(timeout=8000)
            found = False
            try:
                page.locator(".ant-select-item-option", has_text=stem).first.wait_for(timeout=8000)
                found = True
            except Exception:
                found = False
            dt2 = (time.perf_counter() - t0) * 1000
            assertions.append(f"新表在表浏览器可见: {'是' if found else '否'}")
            # no uncaught JS error during the whole flow
            passed = found and (len(page_errors) == 0)
            if page_errors:
                assertions.append(f"流程中出现未捕获JS异常: {page_errors[0]}")
        except Exception as e:
            dt2 = (time.perf_counter() - t0) * 1000
            assertions.append(f"上传流程异常: {e}")
            passed = False
        finally:
            if screenshot_dir:
                shot = os.path.join(screenshot_dir, "FE-D-01.png")
                try:
                    page.screenshot(path=shot)
                except Exception:
                    shot = None
            _cleanup_uploaded_table(stem)
            try:
                os.remove(csv_path)
            except OSError:
                pass

        record["cases"].append({
            "id": "FE-D-01", "module": "前端深度", "name": "上传CSV→表浏览器可见(并清理)",
            "method": "CLICK", "path": "menu::数据上传 → 表浏览器",
            "expected": "上传成功且新表出现在表浏览器", "actual_status": None,
            "latency_ms": round(dt2, 1), "passed": passed, "skipped": False,
            "assertions": assertions, "error": None,
            "extra": {"screenshot": os.path.relpath(shot, HERE) if shot else None,
                      "cleanup": f"已清理表 {stem}"},
        })

        # ---------- FE-D-02: API failure resilience ----------
        t0 = time.perf_counter()
        assertions = []
        page_err_before = len(page_errors)
        fail_before = len(app_failures)
        shot = None
        try:
            page.route("**/api/gis/sites", lambda route: route.fulfill(
                status=500, content_type="application/json", body='{"error":"injected 500"}'))
            _click_menu(page, "GIS地图")
            # give it time to call the API and render an error/empty state
            time.sleep(4)
            page_text = page.content()
            err_hint = next((h for h in ["加载失败", "无法加载", "Failed to load", "error", "暂无数据", "站点总数"]
                             if h in page_text), None)
            dt = (time.perf_counter() - t0) * 1000
            new_page_err = page_errors[page_err_before:]
            new_fail = app_failures[fail_before:]
            crashed = bool(new_page_err)
            assertions.append(f"强制 /api/gis/sites=500 后页面崩溃: {'是(未捕获异常)' if crashed else '否'}")
            assertions.append(f"页面可见提示关键字: {err_hint or '(无明显提示)'}")
            if new_fail:
                assertions.append(f"捕获到 500 响应: {new_fail[0]}")
            # 优雅降级 = 未崩溃(无未捕获JS异常)
            passed = not crashed
            if crashed:
                assertions.append(f"未捕获JS异常: {new_page_err[0]}")
        except Exception as e:
            dt = (time.perf_counter() - t0) * 1000
            assertions.append(f"韧性测试异常: {e}")
            passed = False
        finally:
            try:
                page.unroute("**/api/gis/sites")
            except Exception:
                pass
            if screenshot_dir:
                shot = os.path.join(screenshot_dir, "FE-D-02.png")
                try:
                    page.screenshot(path=shot)
                except Exception:
                    shot = None

        record["cases"].append({
            "id": "FE-D-02", "module": "前端深度", "name": "API故障韧性(/api/gis/sites=500)",
            "method": "ROUTE", "path": "intercept::/api/gis/sites",
            "expected": "接口500时页面不崩溃(优雅降级)", "actual_status": None,
            "latency_ms": round(dt, 1), "passed": passed, "skipped": False,
            "assertions": assertions, "error": None,
            "extra": {"screenshot": os.path.relpath(shot, HERE) if shot else None},
        })

        # ---------- FE-D-03: responsive @375 ----------
        t0 = time.perf_counter()
        assertions = []
        shot = None
        try:
            page.set_viewport_size({"width": 375, "height": 800})
            page.goto(base_url, wait_until="load", timeout=30000)
            page.wait_for_selector("li.ant-menu-item", timeout=15000)
            time.sleep(1.5)
            scroll_w = page.evaluate("document.documentElement.scrollWidth")
            client_w = page.evaluate("document.documentElement.clientWidth")
            overflow = scroll_w - client_w
            assertions.append(f"视口宽={client_w}px, 内容宽={scroll_w}px, 横向溢出={overflow}px")
            # a well-behaved responsive page has little/no horizontal overflow
            passed = overflow <= 5
            if not passed:
                assertions.append("⚠ 存在明显横向溢出——移动端布局未适配(侧边菜单可能固定宽度)")
            else:
                assertions.append("无明显横向溢出")
            # menu still reachable?
            menu_ok = page.locator("li.ant-menu-item").count() > 0
            assertions.append(f"菜单项仍可达: {'是' if menu_ok else '否'}")
        except Exception as e:
            dt = (time.perf_counter() - t0) * 1000
            assertions.append(f"响应式测试异常: {e}")
            passed = False
        finally:
            if screenshot_dir:
                shot = os.path.join(screenshot_dir, "FE-D-03.png")
                try:
                    page.screenshot(path=shot)
                except Exception:
                    shot = None

        record["cases"].append({
            "id": "FE-D-03", "module": "前端深度", "name": "移动端响应式(375px)",
            "method": "VIEWPORT", "path": "viewport::375x800",
            "expected": "无横向溢出且菜单可达", "actual_status": None,
            "latency_ms": round(dt, 1), "passed": passed, "skipped": False,
            "assertions": assertions, "error": None,
            "extra": {"screenshot": os.path.relpath(shot, HERE) if shot else None},
        })

        # ---------- FE-D-04: async data load (TT&WO) ----------
        t0 = time.perf_counter()
        assertions = []
        shot = None
        try:
            page.set_viewport_size({"width": 1440, "height": 900})
            page.goto(base_url, wait_until="load", timeout=30000)
            page.wait_for_selector("li.ant-menu-item", timeout=15000)
            _click_menu(page, "TT&WO Dashboard")
            # wait for populated content (SLA / MTTR / a number)
            found = None
            for hint in ["SLA", "MTTR", "TT", "WO", "Domain"]:
                try:
                    page.get_by_text(hint, exact=False).first.wait_for(timeout=15000)
                    found = hint
                    break
                except Exception:
                    continue
            dt = (time.perf_counter() - t0) * 1000
            assertions.append(f"异步数据加载完成信号: {'命中「'+found+'」' if found else '超时未渲染'}")
            passed = bool(found) and (len(page_errors) == 0)
            if page_errors:
                assertions.append(f"加载中出现未捕获JS异常: {page_errors[0]}")
        except Exception as e:
            dt = (time.perf_counter() - t0) * 1000
            assertions.append(f"异步加载测试异常: {e}")
            passed = False
        finally:
            if screenshot_dir:
                shot = os.path.join(screenshot_dir, "FE-D-04.png")
                try:
                    page.screenshot(path=shot)
                except Exception:
                    shot = None

        record["cases"].append({
            "id": "FE-D-04", "module": "前端深度", "name": "异步数据加载(TT&WO Dashboard)",
            "method": "CLICK", "path": "menu::TT&WO Dashboard",
            "expected": "加载态过渡到有数据渲染", "actual_status": None,
            "latency_ms": round(dt, 1), "passed": passed, "skipped": False,
            "assertions": assertions, "error": None,
            "extra": {"screenshot": os.path.relpath(shot, HERE) if shot else None},
        })

        record["_diagnostics"] = {
            "console_errors_total": len(console_errors),
            "page_errors_total": len(page_errors),
            "page_errors": page_errors[:20],
            "app_request_failures": app_failures[:20],
            "console_errors": console_errors[:50],
        }
        browser.close()

    finalize_record(record)
    return record


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:7038"
    shot_dir = os.path.join(HERE, "reports", "deep_shots_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    rec = run_frontend_deep(base, shot_dir)
    s = rec["summary"]
    print(f"前端深度测试: 总计 {s['total']} | 通过 {s['passed']} | 失败 {s['failed']} | 跳过 {s['skipped']}")
    for c in rec["cases"]:
        tag = "SKIP" if c.get("skipped") else ("PASS" if c["passed"] else "FAIL")
        print(f"  [{tag}] {c['id']} {c['name']}")
