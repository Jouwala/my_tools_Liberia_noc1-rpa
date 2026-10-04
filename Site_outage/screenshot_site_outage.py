"""
Site Outage Dashboard Screenshot
使用 Playwright 自动登录 ZTE 网管系统，打开 Site Down Dashboard，
逐个选择 RAN Site Type 下拉选项并截图保存。
"""

import sys
import os
import time
import re
import json
import base64
from pathlib import Path
from datetime import datetime


# --- 凭据引导（2026-10-04）：口令不写在源码里，统一走共享入口 ---
# 优先环境变量，其次「设置 → 凭据管理」页面（credential_store）。
import os as _os, sys as _sys
# 注意：判据是 credentials.py 这个**文件**，不是 shared/ 这个**目录**。
# Task/Unified_Tools/shared 也存在但里面没有 credentials.py，只判目录会
# 命中它、import 失败后被 except 吞掉 -> 静默降级为空口令（实测踩过）。
_ws = _os.path.dirname(_os.path.abspath(__file__))
_cand = None
while _ws:
    _try = _os.path.join(_ws, "Unified_Tools", "shared", "credentials.py")
    if _os.path.isfile(_try):
        _cand = _try
        break
    _p = _os.path.dirname(_ws)
    if _p == _ws:
        break
    _ws = _p
if _cand:
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_cand)))
try:
    from shared.credentials import get_credential as _get_credential
except Exception:  # 凭据库不可用时降级，不让脚本直接崩
    def _get_credential(_key, env=None, default=""):
        return (_os.environ.get(env, "") if env else "") or default

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ticket_export_rpa'))
from yingdao_to_python import zte_login, detect_selector

from playwright.sync_api import sync_playwright

# 修复终端中文输出编码问题
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# ==================== 配置 ====================
USERNAME = "admin"
PASSWORD = _get_credential("eflow", env="EFLOW_PASS")
LOGIN_URL = (
    "https://10.100.20.8:28001/api/oauth2/v1/authorize"
    "?scope=user.login&response_type=code"
    "&redirect_uri=/uportal/framework/default.html"
)
DASHBOARD_URL = (
    "https://10.100.20.8:28001/uportal/framework/default.html"
    "#/_fms-sitedown-dashboard"
)
HEADLESS = False
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
USER_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_session")
WAIT_TIMEOUT = 120000  # 60s


def info(msg): print(f"[INFO ] {msg}")
def success(msg): print(f"[ OK  ] {msg}")
def warn(msg): print(f"[WARN ] {msg}")
def error(msg): print(f"[ERROR] {msg}")


def sanitize_filename(name):
    """将下拉选项文本转为安全的文件名"""
    name = name.strip()
    name = re.sub(r'[\\/*?:"<>|]', '_', name)
    name = re.sub(r'\s+', '_', name)
    return name


def wait_for_network_idle(page_or_frame, timeout=10000):
    """等待网络空闲，超时则继续（不阻塞）"""
    try:
        page_or_frame.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass


def wait_for_data_refresh(frame, trigger_action, timeout=15000):
    """执行触发动作后，等待数据刷新完成。
    优先等待 networkidle，备选等待 loading 消失。
    """
    trigger_action()
    try:
        frame.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    # 备选：等待可能的 loading 遮罩消失
    try:
        loading = frame.locator(".ant-spin-spinning, [class*='loading'], [class*='spinner']")
        if loading.count() > 0:
            loading.first.wait_for(state="hidden", timeout=5000)
    except Exception:
        pass


def login(page):
    """使用 yingdao_to_python.py 的 zte_login 完成登录"""
    info(f"正在打开登录页...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
    # zte_login 内部已有元素等待逻辑，无需额外 sleep
    ok = zte_login(page)
    if ok:
        success("登录成功，已进入 portal")
        # 登录成功后最小化窗口
        #try:
            #cdp = page.context.new_cdp_session(page)
            #wid = cdp.send("Browser.getWindowForTarget")["windowId"]
            #cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "minimized"}})
            #info("已最小化窗口到任务栏")
        #except Exception:
            #pass
    else:
        warn("登录可能失败")
        page.screenshot(path=os.path.join(OUTPUT_DIR, "debug_login_result.png"))
        info("已保存调试截图 debug_login_result.png")


def get_dashboard_frame(page, max_attempts=3):
    """定位 Dashboard 页面所在的 iframe 并返回其 content frame。
    参考 yingdao_to_python.py 的 get_tt_frame 逻辑。
    """
    iframe_selectors = [
        'iframe[class^="page-mainIframe"]',
        'iframe[src*="sitedown"]',
        'iframe[src*="fms"]',
        'iframe[src*="dashboard"]',
        "iframe",
    ]
    for attempt in range(1, max_attempts + 1):
        info(f"尝试定位 Dashboard iframe（第 {attempt}/{max_attempts} 次）...")
        for sel in iframe_selectors:
            try:
                iframe = page.locator(sel).first
                if iframe.count() == 0:
                    continue
                iframe.wait_for(state="attached", timeout=3000)
                try:
                    if_elem = iframe.element_handle(timeout=3000)
                    frame = if_elem.content_frame()
                except Exception:
                    frame = None
                if frame is None:
                    continue
                try:
                    frame.wait_for_load_state("domcontentloaded", timeout=5000)
                    frame.wait_for_timeout(1000)
                except Exception:
                    pass
                try:
                    body_text = frame.locator("body").inner_text(timeout=2000)
                    if len(body_text.strip()) > 50:
                        info(f"发现 iframe（选择器: {sel}），含 {len(body_text.strip())} 字符内容")
                        return frame
                except Exception:
                    pass
            except Exception:
                continue
        page.wait_for_timeout(1500)

    # 备选：返回第一个 iframe
    try:
        iframe = page.locator("iframe").first
        if iframe.count():
            if_elem = iframe.element_handle(timeout=3000)
            frame = if_elem.content_frame() if if_elem else None
            if frame is not None:
                info("未找到有内容的 iframe，使用第一个 iframe")
                return frame
    except Exception:
        pass

    warn("未找到任何可用的 iframe，回退到顶层 page")
    return page


def navigate_to_dashboard(page):
    """导航到 Site Down Dashboard 页面，返回内容所在的 frame"""
    info(f"正在打开 Dashboard: {DASHBOARD_URL}")

    page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
    wait_for_network_idle(page, timeout=15000)

    # 检查是否跳转成功
    if "_fms-sitedown-dashboard" not in page.url:
        info(f"URL未到位: {page.url}，尝试 JS 修改 hash + reload...")
        page.evaluate("window.location.hash = '#/_fms-sitedown-dashboard'")
        page.wait_for_timeout(1000)
        page.reload(wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
        wait_for_network_idle(page, timeout=15000)

    info(f"当前URL: {page.url}")

    # 定位 iframe（业务页面可能渲染在 iframe 中）
    frame = get_dashboard_frame(page)
    if frame is not page:
        info("后续操作将在 iframe frame 中执行")
    else:
        info("未检测到 iframe，在顶层 page 上操作")

    # 等待关键元素出现（替代固定 sleep）
    for wait_sel in ["text=RAN Site Type", "text=Alarm Management", "select", "[class*='select']"]:
        try:
            frame.wait_for_selector(wait_sel, timeout=15000)
            info(f"检测到元素: {wait_sel}")
            break
        except Exception:
            continue

    return frame


def get_dropdown_options(frame):
    """获取 RAN Site Type 下拉框的所有选项（在 frame 中操作）"""
    options = []

    # 方案1: 标准 <select> 元素（截图显示是自定义样式的 select）
    select_el = frame.locator("select").first
    if select_el.count() > 0:
        info("检测到标准 <select> 下拉框")
        option_elements = select_el.locator("option")
        count = option_elements.count()
        for i in range(count):
            opt = option_elements.nth(i)
            value = opt.get_attribute("value") or ""
            text = opt.inner_text().strip()
            if text:
                options.append({"value": value, "text": text, "index": i})
        if options:
            return options

    # 方案2: 通过 "RAN Site Type" 标签定位附近的下拉框
    info("尝试通过标签文本定位 RAN Site Type 下拉框...")
    label = frame.locator("text='RAN Site Type'").first
    if label.count() > 0:
        info("找到 'RAN Site Type' 标签")
        # 在标签的父级/兄弟级中查找 select 或自定义下拉
        parent = label.locator("xpath=..").first
        # 尝试多种选择器
        for sel in ["select", "[class*='select']", "[class*='dropdown']", "[role='combobox']", "[class*='picker']"]:
            near = parent.locator(sel).first
            if near.count() > 0:
                info(f"在标签附近找到下拉框: {sel}")
                near.click()
                # 智能等待选项出现
                try:
                    frame.wait_for_selector("[role='option'], option, [class*='option'], li", timeout=5000)
                except Exception:
                    frame.wait_for_timeout(500)
                # 获取展开后的选项
                for opt_sel in ["option", "[role='option']", "[class*='option']", "li"]:
                    items = frame.locator(opt_sel)
                    cnt = items.count()
                    if cnt > 0:
                        for i in range(cnt):
                            item = items.nth(i)
                            try:
                                text = item.inner_text(timeout=2000).strip()
                            except Exception:
                                text = ""
                            if text and text not in [o["text"] for o in options]:
                                options.append({"value": text, "text": text, "index": i})
                        if options:
                            break
                frame.keyboard.press("Escape")
                frame.wait_for_timeout(300)
                if options:
                    return options

    # 方案3: 自定义下拉框（Ant Design 等）
    custom_select = frame.locator(
        ".ant-select:not(.ant-select-disabled), "
        "[class*='dropdown-trigger'], "
        "[class*='select-container'], "
        "[role='combobox']"
    ).first

    if custom_select.count() > 0:
        info("检测到自定义下拉框，点击展开选项...")
        custom_select.click()
        # 智能等待选项出现
        try:
            frame.wait_for_selector(
                ".ant-select-item-option, [role='option'], [class*='option-item']",
                timeout=5000
            )
        except Exception:
            frame.wait_for_timeout(500)
        option_items = frame.locator(
            ".ant-select-item-option, "
            ".ant-select-dropdown .ant-select-item, "
            "[class*='option-item'], "
            "[role='option'], "
            "li[class*='option']"
        )
        count = option_items.count()
        for i in range(count):
            item = option_items.nth(i)
            text = item.inner_text().strip()
            if text:
                options.append({"value": text, "text": text, "index": i})
        frame.keyboard.press("Escape")
        frame.wait_for_timeout(300)

    return options


def click_fullscreen(frame):
    """点击全屏按钮"""
    try:
        full_btn = frame.locator("#full, div.full-img").first
        if full_btn.count() > 0:
            full_btn.click()
            info("已点击全屏按钮")
            frame.wait_for_timeout(500)
            return True
    except Exception as e:
        warn(f"点击全屏按钮失败: {e}")
    return False


def select_and_screenshot(page, frame, option, screenshot_dir, max_retries=2):
    """选择某个下拉选项并截图（在 frame 中操作，用 page 截图）"""
    text = option["text"]
    idx = option["index"]
    safe_name = sanitize_filename(text)

    for attempt in range(1, max_retries + 1):
        try:
            info(f"正在选择: {text} (index={idx})" + (f" [重试 {attempt}/{max_retries}]" if attempt > 1 else ""))

            # 方案1: 标准 select
            select_el = frame.locator("select").first
            if select_el.count() > 0:
                def _do_select():
                    select_el.select_option(index=idx)
                wait_for_data_refresh(frame, _do_select)
                time.sleep(3)
                screenshot_path = os.path.join(screenshot_dir, f"{safe_name}.png")
                page.screenshot(path=screenshot_path, full_page=True)
                time.sleep(3)
                if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 0:
                    success(f"已截图: {safe_name}.png")
                    return
                warn(f"截图文件异常，重试 ({attempt}/{max_retries})")
                continue

            # 方案2: 通过标签定位下拉框并点击选项
            label = frame.locator("text='RAN Site Type'").first
            if label.count() > 0:
                parent = label.locator("xpath=..").first
                for sel in ["select", "[class*='select']", "[class*='dropdown']", "[role='combobox']"]:
                    near = parent.locator(sel).first
                    if near.count() > 0:
                        def _do_click_option():
                            near.click()
                            frame.wait_for_timeout(500)
                            try:
                                frame.locator(f"text='{text}'").first.click(timeout=5000)
                            except Exception:
                                items = frame.locator("[role='option'], [class*='option'], option, li")
                                if idx < items.count():
                                    items.nth(idx).click()
                        wait_for_data_refresh(frame, _do_click_option)
                        screenshot_path = os.path.join(screenshot_dir, f"{safe_name}.png")
                        page.screenshot(path=screenshot_path, full_page=True)
                        if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 0:
                            success(f"已截图: {safe_name}.png")
                            return
                        warn(f"截图文件异常，重试 ({attempt}/{max_retries})")
                        break
                else:
                    continue
                continue

            # 方案3: 自定义下拉框
            custom_select = frame.locator(
                ".ant-select:not(.ant-select-disabled), "
                "[class*='dropdown-trigger'], "
                "[role='combobox']"
            ).first

            if custom_select.count() > 0:
                def _do_custom_select():
                    custom_select.click()
                    frame.wait_for_timeout(500)
                    option_items = frame.locator(
                        ".ant-select-item-option, "
                        "[role='option'], "
                        "[class*='option-item']"
                    )
                    if idx < option_items.count():
                        option_items.nth(idx).click()
                    else:
                        frame.locator(f"text='{text}'").first.click()
                wait_for_data_refresh(frame, _do_custom_select)
                screenshot_path = os.path.join(screenshot_dir, f"{safe_name}.png")
                page.screenshot(path=screenshot_path, full_page=True)
                if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 0:
                    success(f"已截图: {safe_name}.png")
                    return
                warn(f"截图文件异常，重试 ({attempt}/{max_retries})")
                continue

            warn(f"无法选择选项: {text}")
            return

        except Exception as e:
            if attempt == max_retries:
                raise
            warn(f"选择失败，重试 ({attempt}/{max_retries}): {e}")


def main():
    start_time = time.time()
    print("=" * 60)
    print(f"Site Outage Dashboard Screenshot")
    print(f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 创建截图输出目录
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    info(f"截图保存目录: {OUTPUT_DIR}")

    pw = sync_playwright().start()

    try:
        # 启动浏览器（使用持久化上下文保留登录状态）
        browser = pw.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=HEADLESS,
            args=["--start-maximized", "--ignore-certificate-errors"],
            no_viewport=True,
            ignore_https_errors=True,
        )
        page = browser.new_page()

        # Step 1: 登录
        print("\n--- Step 1: Login ---")
        login(page)

        # Step 2: 打开 Dashboard（返回内容所在的 frame）
        print("\n--- Step 2: Navigate to Dashboard ---")
        frame = navigate_to_dashboard(page)

        # Step 3: 获取 RAN Site Type 下拉选项
        print("\n--- Step 3: Get RAN Site Type Options ---")
        options = get_dropdown_options(frame)

        if not options:
            error("未找到 RAN Site Type 下拉选项，请检查页面结构")
            page.screenshot(path=os.path.join(OUTPUT_DIR, "debug_no_options.png"))
            info("已保存调试截图 debug_no_options.png")
            return

        info(f"找到 {len(options)} 个选项: {[o['text'] for o in options]}")

        # Step 4: 点击全屏，然后逐个选择并截图
        print("\n--- Step 4: Screenshot Each Option ---")
        click_fullscreen(frame)
        time.sleep(3)
        for opt in options:
            try:
                select_and_screenshot(page, frame, opt, OUTPUT_DIR)
            except Exception as e:
                error(f"截图失败 [{opt['text']}]: {e}")
                page.screenshot(path=os.path.join(OUTPUT_DIR, f"error_{sanitize_filename(opt['text'])}.png"))

        success(f"\n全部完成！共截图 {len(options)} 张")

    except Exception as e:
        error(f"任务中断: {e}")
        import traceback
        traceback.print_exc()
    finally:
        browser.close()
        pw.stop()

    elapsed = time.time() - start_time
    print(f"\n[DONE] Completed in {elapsed:.2f}s")


if __name__ == "__main__":
    main()
