"""
Site Outage Dashboard 截图服务
集成 screenshot_site_outage.py - 使用 Playwright 自动登录 ZTE 网管系统，
打开 Site Down Dashboard，逐个截图保存
"""
import os
import time
import re
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("site_outage_service")


# ========== 内联登录辅助函数（项目自包含，不依赖 my_app 外部） ==========

def _detect_selector(page, candidates):
    """从候选选择器中返回第一个在页面上可见的。"""
    for selector in candidates:
        if not selector:
            continue
        try:
            locator = page.locator(selector)
            if locator.count() > 0 and locator.first.is_visible(timeout=500):
                return selector
        except Exception:
            continue
    return None


def _zte_login(page):
    """在已打开的浏览器页面上执行 ZTE 网管登录。"""
    logger.info("检测登录表单元素是否可见...")

    if "default.html" in page.url and "authorize" not in page.url:
        logger.info("已自动登录（使用了缓存 session）")
        return True

    username_candidates = [
        "#inputUserName", "input[name='username']", "#username",
        "input[id='username']", "input[type='text']",
    ]
    password_candidates = [
        "#inputCiphercode", "input[name='cipher_code']", "#password",
        "input[name='password']", "input[id='password']", "input[type='password']",
    ]
    login_candidates = [
        "#loginBut", "button:has-text('Login')",
        "button:has-text('登录')", "input[type='submit']", "button[type='submit']",
    ]

    username_sel = _detect_selector(page, username_candidates)
    password_sel = _detect_selector(page, password_candidates)
    login_sel = _detect_selector(page, login_candidates)

    if not username_sel:
        logger.warning("未找到用户名输入框")
        return False
    logger.info(f"使用用户名选择器：{username_sel}")

    try:
        page.locator(username_sel).wait_for(state="visible", timeout=10000)
    except Exception:
        pass

    logger.info(f"填写用户名")
    page.locator(username_sel).fill(USERNAME)

    if password_sel:
        logger.info(f"使用密码选择器：{password_sel}")
        try:
            page.locator(password_sel).fill(PASSWORD)
        except Exception:
            page.locator(password_sel).focus(force=True)
            page.keyboard.type(PASSWORD, delay=50)
    else:
        logger.warning("未找到密码选择器")

    if login_sel:
        logger.info(f"使用登录按钮选择器：{login_sel}")
        try:
            page.locator(login_sel).click()
        except Exception:
            try:
                page.locator(login_sel).click(force=True)
            except Exception:
                page.evaluate(f"""() => {{
                    const btn = document.querySelector('{login_sel}');
                    if (btn) btn.click();
                }}""")

        import playwright
        try:
            page.wait_for_url(
                re.compile(r"https://[^/]+/uportal/framework/default\.html"),
                timeout=20000,
            )
            logger.info("页面已跳转至 default.html")
            return True
        except (playwright._impl._errors.Error, TimeoutError):
            logger.warning("未检测到 default.html 跳转，登录可能失败")
            return False
    else:
        logger.warning("未找到登录按钮")
        return False


# ========== 配置 ==========
USERNAME = os.environ.get("EFLOW_USER", "admin")
PASSWORD = os.environ.get("EFLOW_PASS", "Brysj*8*")
HOST = os.environ.get("EFLOW_HOST", "10.100.20.8")
PORT = os.environ.get("EFLOW_PORT", "28001")

LOGIN_URL = (
    f"https://{HOST}:{PORT}/api/oauth2/v1/authorize"
    f"?scope=user.login&response_type=code"
    f"&redirect_uri=/uportal/framework/default.html"
)
DASHBOARD_URL = (
    f"https://{HOST}:{PORT}/uportal/framework/default.html"
    f"#/_fms-sitedown-dashboard"
)
HEADLESS = False
SITE_OUTAGE_DATA_DIR = Path(r"d:\01_RPA\Task\my_app\data\site_outage")
OUTPUT_DIR = str(SITE_OUTAGE_DATA_DIR)
USER_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "Site_outage", "browser_session")
WAIT_TIMEOUT = 120000


def _sanitize_filename(name):
    name = name.strip()
    name = re.sub(r'[\\/*?:"<>|]', '_', name)
    name = re.sub(r'\s+', '_', name)
    return name


def _wait_for_network_idle(page_or_frame, timeout=10000):
    try:
        page_or_frame.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass


def _wait_for_data_refresh(frame, trigger_action, timeout=15000):
    trigger_action()
    try:
        frame.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    try:
        loading = frame.locator(".ant-spin-spinning, [class*='loading'], [class*='spinner']")
        if loading.count() > 0:
            loading.first.wait_for(state="hidden", timeout=5000)
    except Exception:
        pass


def _login(page):
    """使用内联 _zte_login 完成登录"""
    logger.info("[SiteOutage] 正在打开登录页...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
    ok = _zte_login(page)
    if ok:
        logger.info("[SiteOutage] 登录成功")
    else:
        logger.warning("[SiteOutage] 登录可能失败")
        page.screenshot(path=os.path.join(OUTPUT_DIR, "debug_login_result.png"))


def _get_dashboard_frame(page, max_attempts=3):
    """定位 Dashboard iframe"""
    iframe_selectors = [
        'iframe[class^="page-mainIframe"]',
        'iframe[src*="sitedown"]',
        'iframe[src*="fms"]',
        'iframe[src*="dashboard"]',
        "iframe",
    ]
    for attempt in range(1, max_attempts + 1):
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
                    body_text = frame.locator("body").inner_text(timeout=2000)
                    if len(body_text.strip()) > 50:
                        return frame
                except Exception:
                    pass
            except Exception:
                continue
        page.wait_for_timeout(1500)

    # 回退
    try:
        iframe = page.locator("iframe").first
        if iframe.count():
            if_elem = iframe.element_handle(timeout=3000)
            frame = if_elem.content_frame() if if_elem else None
            if frame:
                return frame
    except Exception:
        pass
    return page


def _navigate_to_dashboard(page):
    page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
    _wait_for_network_idle(page, timeout=15000)

    if "_fms-sitedown-dashboard" not in page.url:
        page.evaluate("window.location.hash = '#/_fms-sitedown-dashboard'")
        page.wait_for_timeout(1000)
        page.reload(wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
        _wait_for_network_idle(page, timeout=15000)

    frame = _get_dashboard_frame(page)

    for wait_sel in ["text=RAN Site Type", "text=Alarm Management", "select", "[class*='select']"]:
        try:
            frame.wait_for_selector(wait_sel, timeout=15000)
            break
        except Exception:
            continue

    return frame


def _get_dropdown_options(frame):
    """获取 RAN Site Type 下拉选项"""
    options = []

    # 方案1: 标准 <select>
    select_el = frame.locator("select").first
    if select_el.count() > 0:
        option_elements = select_el.locator("option")
        for i in range(option_elements.count()):
            opt = option_elements.nth(i)
            value = opt.get_attribute("value") or ""
            text = opt.inner_text().strip()
            if text:
                options.append({"value": value, "text": text, "index": i})
        if options:
            return options

    # 方案2: 通过 "RAN Site Type" 标签定位附近的下拉框
    logger.info("[SiteOutage] 尝试通过标签文本定位 RAN Site Type 下拉框...")
    label = frame.locator("text='RAN Site Type'").first
    if label.count() > 0:
        logger.info("[SiteOutage] 找到 'RAN Site Type' 标签")
        parent = label.locator("xpath=..").first
        for sel in ["select", "[class*='select']", "[class*='dropdown']", "[role='combobox']", "[class*='picker']"]:
            near = parent.locator(sel).first
            if near.count() > 0:
                logger.info(f"[SiteOutage] 在标签附近找到下拉框: {sel}")
                near.click()
                try:
                    frame.wait_for_selector("[role='option'], option, [class*='option'], li", timeout=5000)
                except Exception:
                    frame.wait_for_timeout(500)
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

    # 方案3: Ant Design 下拉
    custom_select = frame.locator(
        ".ant-select:not(.ant-select-disabled), "
        "[class*='dropdown-trigger'], "
        "[class*='select-container'], "
        "[role='combobox']"
    ).first

    if custom_select.count() > 0:
        logger.info("[SiteOutage] 检测到自定义下拉框，点击展开选项...")
        custom_select.click()
        try:
            frame.wait_for_selector(
                ".ant-select-item-option, [role='option'], [class*='option-item']",
                timeout=5000
            )
        except Exception:
            frame.wait_for_timeout(500)
        items = frame.locator(
            ".ant-select-item-option, "
            ".ant-select-dropdown .ant-select-item, "
            "[class*='option-item'], "
            "[role='option'], "
            "li[class*='option']"
        )
        for i in range(items.count()):
            text = items.nth(i).inner_text().strip()
            if text:
                options.append({"value": text, "text": text, "index": i})
        frame.keyboard.press("Escape")
        frame.wait_for_timeout(300)

    return options


def _select_and_screenshot(page, frame, option, screenshot_dir):
    """选择选项并截图"""
    text = option["text"]
    idx = option["index"]
    safe_name = _sanitize_filename(text)

    for attempt in range(1, 3):
        try:
            # 方案1: 标准 select
            select_el = frame.locator("select").first
            if select_el.count() > 0:
                def _do():
                    select_el.select_option(index=idx)
                _wait_for_data_refresh(frame, _do)
                time.sleep(3)
                screenshot_path = os.path.join(screenshot_dir, f"{safe_name}.png")
                page.screenshot(path=screenshot_path, full_page=True)
                time.sleep(3)
                if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 0:
                    logger.info(f"[SiteOutage] 截图: {safe_name}.png")
                    return screenshot_path
                continue

            # 方案2: 通过标签定位下拉框并点击选项
            label = frame.locator("text='RAN Site Type'").first
            if label.count() > 0:
                parent = label.locator("xpath=..").first
                for sel in ["select", "[class*='select']", "[class*='dropdown']", "[role='combobox']"]:
                    near = parent.locator(sel).first
                    if near.count() > 0:
                        def _do():
                            near.click()
                            frame.wait_for_timeout(500)
                            try:
                                frame.locator(f"text='{text}'").first.click(timeout=5000)
                            except Exception:
                                items = frame.locator("[role='option'], [class*='option'], option, li")
                                if idx < items.count():
                                    items.nth(idx).click()
                        _wait_for_data_refresh(frame, _do)
                        screenshot_path = os.path.join(screenshot_dir, f"{safe_name}.png")
                        page.screenshot(path=screenshot_path, full_page=True)
                        if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 0:
                            logger.info(f"[SiteOutage] 截图: {safe_name}.png")
                            return screenshot_path
                        continue
                continue

            # 方案3: Ant Design 自定义下拉框
            custom_select = frame.locator(
                ".ant-select:not(.ant-select-disabled), "
                "[class*='dropdown-trigger'], "
                "[role='combobox']"
            ).first
            if custom_select.count() > 0:
                def _do():
                    custom_select.click()
                    frame.wait_for_timeout(500)
                    items = frame.locator(".ant-select-item-option, [role='option'], [class*='option-item']")
                    if idx < items.count():
                        items.nth(idx).click()
                    else:
                        frame.locator(f"text='{text}'").first.click()
                _wait_for_data_refresh(frame, _do)
                screenshot_path = os.path.join(screenshot_dir, f"{safe_name}.png")
                page.screenshot(path=screenshot_path, full_page=True)
                if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 0:
                    logger.info(f"[SiteOutage] 截图: {safe_name}.png")
                    return screenshot_path
                continue

            logger.warning(f"[SiteOutage] 无法选择选项: {text}")
            return None

        except Exception as e:
            if attempt == 2:
                raise
            logger.warning(f"[SiteOutage] 重试 ({attempt}): {e}")

    return None


def run_site_outage_screenshot() -> dict:
    """
    Site Outage Dashboard 截图任务：
    1. 启动 Playwright 浏览器
    2. 登录 ZTE 网管系统
    3. 打开 Site Down Dashboard
    4. 逐个选择 RAN Site Type 并截图

    Returns: dict
    """
    start_time = time.time()
    result = {
        "success": False,
        "screenshots": [],
        "errors": [],
        "elapsed_seconds": 0,
    }

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        result["errors"].append("缺少 playwright 依赖")
        return result

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    logger.info(f"[SiteOutage] 截图目录: {OUTPUT_DIR}")

    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=HEADLESS,
            args=["--start-maximized", "--ignore-certificate-errors"],
            no_viewport=True,
            ignore_https_errors=True,
        )
        page = browser.new_page()

        # Login
        _login(page)

        # Navigate
        frame = _navigate_to_dashboard(page)

        # Get options
        options = _get_dropdown_options(frame)
        if not options:
            result["errors"].append("未找到 RAN Site Type 下拉选项")
            return result

        logger.info(f"[SiteOutage] 找到 {len(options)} 个选项: {[o['text'] for o in options]}")

        # Fullscreen + screenshot
        try:
            full_btn = frame.locator("#full, div.full-img").first
            if full_btn.count() > 0:
                full_btn.click()
                time.sleep(0.5)
        except Exception:
            pass
        time.sleep(3)

        for opt in options:
            try:
                path = _select_and_screenshot(page, frame, opt, OUTPUT_DIR)
                if path:
                    result["screenshots"].append(path)
            except Exception as e:
                err = f"截图失败 [{opt['text']}]: {e}"
                logger.error(f"[SiteOutage] {err}")
                result["errors"].append(err)

        result["success"] = len(result["errors"]) == 0

    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"[SiteOutage] Task failed: {e}")

    finally:
        if browser:
            browser.close()
        if pw:
            pw.stop()

    elapsed = time.time() - start_time
    result["elapsed_seconds"] = round(elapsed, 2)
    logger.info(f"[SiteOutage] Done: {len(result['screenshots'])} screenshots, {elapsed:.2f}s")
    return result


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')

    result = run_site_outage_screenshot()
    print(f"\nSite Outage 截图结果: {'成功' if result['success'] else '失败'}")
    print(f"截图数: {len(result['screenshots'])}")
    if result['errors']:
        print(f"错误: {result['errors']}")
    print(f"耗时: {result['elapsed_seconds']}s")
