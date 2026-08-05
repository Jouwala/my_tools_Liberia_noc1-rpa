"""
Site Outage Dashboard 截图服务
集成 screenshot_site_outage.py - 使用 Playwright 自动登录 ZTE 网管系统，
打开 Site Down Dashboard，逐个截图保存

稳定性说明：
- 引入 _playwright_utils 公共模块，统一处理「显式等待 / 分级重试 / 现场留证 / 顶层恢复」
- iframe 定位失败立即抛 FatalError，不再 fallback 到 page（避免在错误上下文操作）
- 选项切换后用 loading 消失作为就绪信号 + 截图空白校验
- 单选项失败清理现场（Escape 关闭可能残留的下拉框），不阻断后续选项
- 整个任务顶层包一层重试（最多 2 次）
"""
import os
import sys
import time
import re
import logging
from pathlib import Path

# 同目录导入公共稳定模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _playwright_utils import (  # noqa: E402
    retry_transient,
    run_with_recovery,
    save_debug_snapshot,
    wait_for_loading_gone,
    is_screenshot_blank,
    TransientError,
    FatalError,
)

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
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _detect_selector: exception swallowed", exc_info=True)
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
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _zte_login: exception swallowed", exc_info=True)
        pass

    logger.info("填写用户名")
    _cred_user, _cred_pwd = _runtime_credentials()
    page.locator(username_sel).fill(_cred_user)

    if password_sel:
        logger.info(f"使用密码选择器：{password_sel}")
        try:
            page.locator(password_sel).fill(_cred_pwd)
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _zte_login: exception swallowed", exc_info=True)
            page.locator(password_sel).focus(force=True)
            page.keyboard.type(_cred_pwd, delay=50)
    else:
        logger.warning("未找到密码选择器")

    if login_sel:
        logger.info(f"使用登录按钮选择器：{login_sel}")
        try:
            page.locator(login_sel).click()
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _zte_login: exception swallowed", exc_info=True)
            try:
                page.locator(login_sel).click(force=True)
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _zte_login: exception swallowed", exc_info=True)
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


def _runtime_credentials():
    """运行时获取凭据（环境变量 > 数据库 > 模块默认值），支持页面改密后免重启生效。"""
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        from credential_store import get_credential
    return get_credential("eflow", USERNAME, PASSWORD,
                          env_user="EFLOW_USER", env_secret="EFLOW_PASS")

LOGIN_URL = (
    f"https://{HOST}:{PORT}/api/oauth2/v1/authorize"
    f"?scope=user.login&response_type=code"
    f"&redirect_uri=/uportal/framework/default.html"
)
DASHBOARD_URL = (
    f"https://{HOST}:{PORT}/uportal/framework/default.html"
    f"#/_fms-sitedown-dashboard"
)
# 静默运行配置（环境变量 SITE_OUTAGE_HEADLESS 优先）：
#   "true" (默认)  - 完全 headless，内部 ZTE 网管无反爬检测，安全可靠
#   "offscreen"    - 窗口移到屏幕外（兼容性更好，特殊场景用）
#   "false"        - 正常弹窗（调试用）
HEADLESS_MODE = os.environ.get("SITE_OUTAGE_HEADLESS", "true").lower()
HEADLESS = HEADLESS_MODE == "true"

# 脚本所在目录（用于派生相对路径）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 数据目录：脚本同级下的 data/site_outage（脚本相对路径，便于跨机器迁移）
SITE_OUTAGE_DATA_DIR = Path(_SCRIPT_DIR) / "data" / "site_outage"
OUTPUT_DIR = str(SITE_OUTAGE_DATA_DIR)
# 失败现场截图 + HTML dump 目录（与正常截图分开，便于排查）
DEBUG_DIR = str(SITE_OUTAGE_DATA_DIR / "debug_snapshots")
USER_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "Site_outage", "browser_session")
WAIT_TIMEOUT = 120000
# 顶层任务最大重试次数
MAX_TOTAL_RETRY = 2


def _sanitize_filename(name):
    name = name.strip()
    name = re.sub(r'[\\/*?:"<>|]', '_', name)
    name = re.sub(r'\s+', '_', name)
    return name


def _wait_for_network_idle(page_or_frame, timeout=10000):
    try:
        page_or_frame.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _wait_for_network_idle: exception swallowed", exc_info=True)
        pass


def _collapse_sidebar(page):
    """折叠左侧导航菜单，避免截图被遮挡。

    注意：
    - 只操作 page（顶层框架）的左侧导航，绝不碰 iframe 内部元素
    - 避免使用模糊 selector，防止误点 dashboard 内部按钮触发右侧面板
    """
    # 方案1: 精确查找左下角 Fold 折叠按钮（顶层页面）
    fold_selectors = [
        "button:has-text('Fold')",
        "div:has-text('Fold')",
        "span[title='Fold']",
        "i[class*='fold']",
    ]
    for sel in fold_selectors:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible(timeout=2000):
                # 额外校验：按钮必须在 viewport 左侧区域，避免误点 dashboard 内元素
                box = btn.bounding_box()
                if box and box["x"] < 200:
                    btn.click(timeout=3000)
                    logger.info("[SiteOutage] 已点击折叠左侧导航菜单")
                    page.wait_for_timeout(800)
                    return True
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _collapse_sidebar: exception swallowed", exc_info=True)
            continue

    # 方案2: 通过 evaluate 直接隐藏顶层左侧菜单
    try:
        collapsed = page.evaluate("""
            () => {
                // 只选择页面最左侧的导航栏（避开 iframe 内内容）
                const candidates = document.querySelectorAll(
                    '.sidebar, .ant-layout-sider, [class*="sidebar"], [class*="sider-"]'
                );
                for (const el of candidates) {
                    const rect = el.getBoundingClientRect();
                    // x < 10 且高度占满屏幕，才认为是左侧导航
                    if (rect.x < 10 && rect.height > window.innerHeight * 0.5) {
                        el.style.width = '0px';
                        el.style.minWidth = '0px';
                        el.style.maxWidth = '0px';
                        el.style.overflow = 'hidden';
                        el.style.display = 'none';
                        return true;
                    }
                }
                return false;
            }
        """)
        if collapsed:
            logger.info("[SiteOutage] 已通过样式强制隐藏左侧导航菜单")
            page.wait_for_timeout(500)
            return True
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _collapse_sidebar: exception swallowed", exc_info=True)
        pass

    return False


def _wait_for_charts_rendered(frame, timeout=30000):
    """等待右侧图表真正渲染完成（仅条件等待，无固定长 sleep）。"""
    deadline = time.time() + timeout / 1000

    # 1. loading 消失
    wait_for_loading_gone(frame, timeout=timeout)

    # 2. 核心指标文本
    try:
        frame.wait_for_selector("text=/Site Down:/i", timeout=min(timeout, 15000))
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _wait_for_charts_rendered: exception swallowed", exc_info=True)
        pass

    # 3. SVG/canvas 数量短暂稳定（最多约 3s，不再死等）
    last_svg_count = -1
    stable_count = 0
    while time.time() < deadline:
        try:
            svg_count = frame.locator("svg, canvas").count()
            if svg_count == last_svg_count and svg_count > 0:
                stable_count += 1
                if stable_count >= 2:
                    break
            else:
                stable_count = 0
            last_svg_count = svg_count
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _wait_for_charts_rendered: exception swallowed", exc_info=True)
            pass
        time.sleep(0.35)

    # 4. 图表区出现带数字的文本（最多约 6s）
    try:
        charts = frame.locator(
            "[class*='chart'], [class*='Chart'], .ant-card-body, [class*='dashboard']"
        )
        if charts.count() > 0:
            for _ in range(20):
                has_data = False
                for i in range(min(charts.count(), 8)):
                    try:
                        text = charts.nth(i).inner_text(timeout=400).strip()
                        if (len(text) > 5
                                and not text.lower().startswith("loading")
                                and any(c.isdigit() for c in text)):
                            has_data = True
                            break
                    except Exception:
                        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _wait_for_charts_rendered: exception swallowed", exc_info=True)
                        continue
                if has_data:
                    break
                time.sleep(0.25)
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _wait_for_charts_rendered: exception swallowed", exc_info=True)
        pass

    # 5. 极短缓冲（着色动画），替代原来的 2500ms
    frame.wait_for_timeout(400)

def _wait_for_data_refresh(frame, trigger_action, timeout=15000):
    """触发数据刷新后，等待网络空闲、loading 消失、图表渲染完成。"""
    trigger_action()
    try:
        frame.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _wait_for_data_refresh: exception swallowed", exc_info=True)
        pass
    # 等待图表真正渲染完成（替代简单的 loading 检测）
    _wait_for_charts_rendered(frame, timeout=timeout)


def _login(page):
    """使用内联 _zte_login 完成登录。

    改进点：
    - 包一层 retry_transient（最多 3 次），瞬时失败可恢复
    - 登录失败时保存现场截图 + HTML，便于事后复盘
    - 区分异常：凭据失效/凭据错误视为 TransientError；找不到登录表单视为 FatalError
    """
    logger.info("[SiteOutage] 正在打开登录页...")

    def _attempt():
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
        ok = _zte_login(page)
        if not ok:
            save_debug_snapshot(page, DEBUG_DIR, "login_fail")
            raise TransientError("ZTE 登录失败，可能凭据失效或登录表单结构变更")
        logger.info("[SiteOutage] 登录成功")
        return True

    try:
        retry_transient(_attempt, max_attempts=3, backoff_base=2.0, label="zte_login")
    except TransientError:
        save_debug_snapshot(page, DEBUG_DIR, "login_final_fail")
        raise


def _get_dashboard_frame(page, max_attempts=3):
    """定位 Dashboard iframe。

    改进点：
    - 旧实现找不到 iframe 时 fallback 返回 page，导致后续操作在错误上下文执行
    - 新实现找不到 iframe 直接抛 FatalError，避免静默失败
    """
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
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] _get_dashboard_frame: exception swallowed", exc_info=True)
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
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] _get_dashboard_frame: exception swallowed", exc_info=True)
                    pass
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _get_dashboard_frame: exception swallowed", exc_info=True)
                continue
        page.wait_for_timeout(1500)

    # 严格模式：不再 fallback 到 page，直接报错
    save_debug_snapshot(page, DEBUG_DIR, "iframe_not_found")
    raise FatalError(
        "Dashboard iframe 定位失败：可能页面未加载完成或登录态已失效"
    )


def _navigate_to_dashboard(page):
    """导航到 Dashboard 并返回 iframe 上下文。

    改进点：
    - iframe 定位失败抛 FatalError 后由调用方处理，不再返回错误上下文
    - 等待核心元素可见后返回，确保后续选项点击可执行
    - 进入 dashboard 后先折叠左侧导航菜单，避免截图被遮挡
    """
    page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
    _wait_for_network_idle(page, timeout=15000)

    if "_fms-sitedown-dashboard" not in page.url:
        page.evaluate("window.location.hash = '#/_fms-sitedown-dashboard'")
        page.wait_for_timeout(1000)
        page.reload(wait_until="domcontentloaded", timeout=WAIT_TIMEOUT)
        _wait_for_network_idle(page, timeout=15000)

    # 最大化窗口
    _maximize_and_fullscreen(page)

    # 折叠左侧导航菜单（page 级别，不在 iframe 内）
    _collapse_sidebar(page)

    frame = _get_dashboard_frame(page)

    # 尝试 dashboard 内部全屏（用户指定右上角全屏按钮），并验证是否触发右侧面板
    try:
        if _enter_dashboard_fullscreen(frame):
            tmp_path = os.path.join(DEBUG_DIR, "fullscreen_verify.png")
            if _take_iframe_screenshot(page, frame, tmp_path):
                if not _verify_screenshot(tmp_path):
                    logger.warning("[SiteOutage] 全屏后出现遮挡面板，回退到非全屏")
                    _exit_dashboard_fullscreen(frame)
                else:
                    logger.info("[SiteOutage] dashboard 全屏验证通过")
    except Exception as e:
        logger.warning(f"[SiteOutage] dashboard 全屏尝试失败: {e}")

    for wait_sel in ["text=RAN Site Type", "text=Alarm Management", "select", "[class*='select']"]:
        try:
            frame.wait_for_selector(wait_sel, timeout=15000)
            break
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _navigate_to_dashboard: exception swallowed", exc_info=True)
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
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] _get_dropdown_options: exception swallowed", exc_info=True)
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
                                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _get_dropdown_options: exception swallowed", exc_info=True)
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
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _get_dropdown_options: exception swallowed", exc_info=True)
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


def _verify_screenshot(screenshot_path: str) -> bool:
    """校验截图完整性：文件存在 + size > 0 + 非空白页 + 无菜单/面板遮挡。

    改进点：
    - 旧实现只检查 size > 0，截到空白页也算"成功"
    - 新实现增加像素方差校验（无 Pillow 时降级为 size > 0）
    - 新增左侧菜单遮挡检测：若最左侧 1/4 区域颜色过于均匀，
      说明导航菜单仍展开，返回 False 触发重试
    - 新增右侧面板遮挡检测：若最右侧 1/4 区域大面积白色/浅色，
      说明有抽屉/面板展开，返回 False 触发重试
    """
    if not os.path.exists(screenshot_path) or os.path.getsize(screenshot_path) <= 0:
        return False
    if is_screenshot_blank(screenshot_path):
        logger.warning(f"[SiteOutage] 截图疑似空白页: {screenshot_path}")
        return False

    try:
        from PIL import Image
        import statistics
        img = Image.open(screenshot_path)
        width, height = img.size

        # 检测左侧菜单是否展开遮挡 dashboard
        left_region = img.crop((0, 0, int(width * 0.25), height)).convert("L")
        left_pixels = list(left_region.resize((50, height)).getdata())
        left_var = statistics.pvariance(left_pixels)
        if left_var < 800.0:
            logger.warning(
                f"[SiteOutage] 截图左侧菜单仍展开（var={left_var:.1f}），判定为遮挡: {screenshot_path}"
            )
            return False

        # 检测右侧是否有白色抽屉/面板展开
        right_region = img.crop((int(width * 0.75), 0, width, height)).convert("L")
        right_pixels = list(right_region.resize((50, height)).getdata())
        right_var = statistics.pvariance(right_pixels)
        right_mean = statistics.mean(right_pixels)
        # 右侧大面积白色（均值高、方差小）→ 有面板展开
        if right_mean > 230 and right_var < 1500.0:
            logger.warning(
                f"[SiteOutage] 截图右侧有白色面板展开（mean={right_mean:.1f}, var={right_var:.1f}），"
                f"判定为遮挡: {screenshot_path}"
            )
            return False
    except ImportError:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _verify_screenshot: exception swallowed", exc_info=True)
        pass
    except Exception as e:
        logger.warning(f"[SiteOutage] 遮挡检测失败（跳过）: {e}")

    return True


def _cleanup_dropdown_state(frame):
    """失败后清场：关下拉 + 点空白，避免污染下一选项。"""
    try:
        frame.keyboard.press("Escape")
        frame.wait_for_timeout(200)
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _cleanup_dropdown_state: exception swallowed", exc_info=True)
        pass
    try:
        body = frame.locator("body").first
        if body.count() > 0:
            box = body.bounding_box()
            if box:
                # 点中央偏下，避开顶栏/右上角按钮
                frame.mouse.click(
                    box["x"] + box["width"] * 0.5,
                    box["y"] + box["height"] * 0.55,
                )
                frame.wait_for_timeout(200)
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _cleanup_dropdown_state: exception swallowed", exc_info=True)
        pass
    try:
        frame.keyboard.press("Escape")
        frame.wait_for_timeout(150)
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _cleanup_dropdown_state: exception swallowed", exc_info=True)
        pass

def _close_popups(frame):
    """关闭 iframe 内可能遮挡截图的弹窗、提示框、新手引导等。"""
    closed = False

    # 方案1: 点击常见关闭按钮（X 图标、关闭文字）
    close_selectors = [
        "button[class*='close']",
        "i[class*='close']",
        "span[class*='close']",
        "div[class*='close']",
        "[aria-label*='close' i]",
        "[aria-label*='关闭' i]",
        "[title*='close' i]",
        "[title*='关闭' i]",
        ".ant-modal-close",
        ".ant-tooltip-close",
        ".ant-popover-close",
        ".ant-notification-notice-close",
        ".ant-message-close",
        ".ant-tour-close",
        ".ant-tour-next",  # 新手引导的下一步/关闭
        ".ant-tour-finish",
        "button:has-text('关闭')",
        "button:has-text('Close')",
        "button:has-text('知道了')",
        "button:has-text('Got it')",
        "button:has-text('不再提示')",
    ]
    for sel in close_selectors:
        try:
            btns = frame.locator(sel)
            for i in range(btns.count()):
                btn = btns.nth(i)
                try:
                    if btn.is_visible(timeout=1000):
                        btn.click(timeout=2000)
                        logger.info(f"[SiteOutage] 已关闭弹窗: {sel}")
                        frame.wait_for_timeout(300)
                        closed = True
                except Exception:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] _close_popups: exception swallowed", exc_info=True)
                    continue
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _close_popups: exception swallowed", exc_info=True)
            continue

    # 方案2: 按 Escape 键关闭通用弹窗
    try:
        frame.keyboard.press("Escape")
        frame.wait_for_timeout(300)
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _close_popups: exception swallowed", exc_info=True)
        pass

    # 方案3: 点击 iframe 中央区域，让悬浮提示消失
    try:
        body = frame.locator("body").first
        if body.count() > 0:
            box = body.bounding_box()
            if box:
                # 点击中央偏右位置（避开左上角弹窗，防止重复触发）
                frame.mouse.click(box["x"] + box["width"] * 0.6, box["y"] + box["height"] * 0.4)
                frame.wait_for_timeout(300)
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _close_popups: exception swallowed", exc_info=True)
        pass

    return closed


def _remove_annoying_popups(frame):
    """通过 JS 直接移除已知会遮挡截图的弹窗/提示/新手引导 DOM 元素。

    这是最后一道保险：如果点击关闭按钮无法消除弹窗，直接把它从 DOM 里删掉。
    """
    try:
        removed = frame.evaluate("""
            () => {
                const selectors = [
                    // 导航菜单入口 / 新手引导
                    '[class*="navigation-menu"]',
                    '[class*="guide"]',
                    '[class*="tour"]',
                    '[class*="popover"]',
                    '[class*="tooltip"]',
                    '[class*="intro"]',
                    '[class*="hint"]',
                    '[class*="onboarding"]',
                    // Ant Design 系列
                    '.ant-tour',
                    '.ant-popover',
                    '.ant-tooltip',
                    '.ant-modal-mask',
                    '.ant-modal-wrap',
                    '.ant-message',
                    '.ant-notification',
                    // 通用遮罩 / 抽屉
                    '.mask',
                    '.overlay',
                    '[class*="overlay"]',
                    '[class*="mask"]',
                    '[class*="drawer"]',
                    // 顶部固定提示条
                    '[class*="banner"]',
                    '[class*="alert"]',
                ];
                let count = 0;
                selectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => {
                        // 只移除尺寸较小的浮层/提示，避免误删 dashboard 主体
                        const rect = el.getBoundingClientRect();
                        const area = rect.width * rect.height;
                        const viewportArea = window.innerWidth * window.innerHeight;
                        if (area < viewportArea * 0.5) {
                            el.remove();
                            count++;
                        }
                    });
                });

                // 按文本内容移除：包含"导航菜单入口"、"Navigation"等提示
                const textKeywords = ['导航菜单入口', 'Navigation Menu', '新手引导', 'New Feature', 'Got it'];
                const allEls = document.querySelectorAll('*');
                allEls.forEach(el => {
                    const text = (el.textContent || '').trim();
                    if (textKeywords.some(k => text.includes(k))) {
                        const rect = el.getBoundingClientRect();
                        const area = rect.width * rect.height;
                        const viewportArea = window.innerWidth * window.innerHeight;
                        if (area < viewportArea * 0.5) {
                            el.remove();
                            count++;
                        }
                    }
                });

                return count;
            }
        """)
        if removed and removed > 0:
            logger.info(f"[SiteOutage] 已通过 JS 移除 {removed} 个遮挡弹窗")
            frame.wait_for_timeout(300)
    except Exception as e:
        logger.debug(f"[SiteOutage] JS 移除弹窗失败: {e}")


def _enter_dashboard_fullscreen(frame):
    """点击 iframe 内部 dashboard 右上角的全屏按钮。

    安全策略：
    - 只在 iframe 右上角区域查找，避免误点其他按钮
    - 优先选择 class/data-icon 包含 full/expand/maximize 的元素
    - 若找不到精确全屏按钮，则尝试右上角最后一个可见图标按钮
    """
    viewport = {"w": 1280, "h": 800}
    try:
        viewport = frame.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _enter_dashboard_fullscreen: exception swallowed", exc_info=True)
        pass

    # 候选 selector：class / data-icon / svg title 包含全屏语义
    fullscreen_selectors = [
        "[class*='full-screen']",
        "[class*='fullscreen']",
        "[class*='full_screen']",
        "[class*='expand']",
        "[class*='maximize']",
        "[data-icon*='full']",
        "[data-icon*='expand']",
        "[data-icon*='maximize']",
        "svg:has(title:has-text('full'))",
        "svg:has(title:has-text('expand'))",
        "svg:has(title:has-text('maximize'))",
        "i[class*='full']",
        "i[class*='expand']",
        "i[class*='maximize']",
    ]

    def _is_top_right(box):
        if not box or box["width"] <= 0 or box["height"] <= 0:
            return False
        # 右上角区域：x 在右侧 30%，y 在顶部 150px 内
        return box["x"] > viewport["w"] * 0.65 and box["y"] < 150

    # 方案1: 精确 selector
    for sel in fullscreen_selectors:
        try:
            loc = frame.locator(sel).first
            if loc.count() > 0 and loc.is_visible(timeout=2000):
                box = loc.bounding_box()
                if _is_top_right(box):
                    loc.click(timeout=3000)
                    logger.info(f"[SiteOutage] 已点击 dashboard 全屏按钮: {sel}")
                    frame.wait_for_timeout(1500)
                    return True
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _enter_dashboard_fullscreen: exception swallowed", exc_info=True)
            continue

    # 方案2: 兜底，找右上角所有可见图标按钮，尝试点击最后一个
    try:
        icon_buttons = frame.locator(
            "button, div[role='button'], span[role='button'], i, svg"
        )
        candidates = []
        for i in range(icon_buttons.count()):
            try:
                btn = icon_buttons.nth(i)
                if btn.is_visible(timeout=500):
                    box = btn.bounding_box()
                    if _is_top_right(box):
                        candidates.append((box["x"], btn))
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _enter_dashboard_fullscreen: exception swallowed", exc_info=True)
                continue
        # 按 x 排序，最右边的优先
        candidates.sort(key=lambda x: x[0], reverse=True)
        for _, btn in candidates[:3]:
            try:
                btn.click(timeout=2000)
                logger.info("[SiteOutage] 已尝试点击右上角图标按钮（全屏兜底）")
                frame.wait_for_timeout(1500)
                return True
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _enter_dashboard_fullscreen: exception swallowed", exc_info=True)
                continue
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _enter_dashboard_fullscreen: exception swallowed", exc_info=True)
        pass

    return False


def _exit_dashboard_fullscreen(frame):
    """退出 dashboard 全屏（按 ESC 或再次点击全屏按钮）。"""
    try:
        frame.keyboard.press("Escape")
        frame.wait_for_timeout(500)
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _exit_dashboard_fullscreen: exception swallowed", exc_info=True)
        pass


def _maximize_and_fullscreen(page):
    """最大化窗口并设置 viewport（非浏览器 F11）。"""
    try:
        page.set_viewport_size({"width": 1920, "height": 1080})
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _maximize_and_fullscreen: exception swallowed", exc_info=True)
        pass


def _take_iframe_screenshot(page, frame, screenshot_path: str) -> bool:
    """截取 iframe 内容，避免页面级菜单/面板干扰。

    策略：
    1. 尝试直接对 iframe 元素截图（最干净，只含 dashboard）
    2. 失败则回退到 page.screenshot(full_page=True)

    Returns:
        True 截图成功；False 失败
    """
    # 先尝试找到 iframe 元素并截图
    try:
        iframe_loc = page.locator('iframe[class^="page-mainIframe"], iframe[src*="sitedown"], iframe').first
        if iframe_loc.count() > 0:
            handle = iframe_loc.element_handle(timeout=3000)
            if handle:
                handle.screenshot(path=screenshot_path)
                return True
    except Exception as e:
        logger.debug(f"[SiteOutage] iframe 元素截图失败，回退到 page 截图: {e}")

    # 回退：page 全页截图
    try:
        page.screenshot(path=screenshot_path, full_page=True)
        return True
    except Exception as e:
        logger.warning(f"[SiteOutage] page 截图也失败: {e}")
        return False


def _select_and_screenshot(page, frame, option, screenshot_dir):
    """选择选项并截图。

    改进点：
    - 选项切换后用 _wait_for_data_refresh（含 _wait_for_charts_rendered）替代 time.sleep(3) 硬等
    - 截图前折叠左侧导航菜单，避免遮挡
    - 改为截取 iframe 元素本身，避免页面级右侧面板/左侧菜单进入截图
    - 截图增加非空白校验（_verify_screenshot）
    - 失败时调用 _cleanup_dropdown_state 清场，避免污染下一个选项
    """
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
                _collapse_sidebar(page)
                _close_popups(frame)
                _remove_annoying_popups(frame)
                screenshot_path = os.path.join(screenshot_dir, f"{safe_name}.png")
                if not _take_iframe_screenshot(page, frame, screenshot_path):
                    continue
                if _verify_screenshot(screenshot_path):
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
                                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _do: exception swallowed", exc_info=True)
                                items = frame.locator("[role='option'], [class*='option'], option, li")
                                if idx < items.count():
                                    items.nth(idx).click()
                        _wait_for_data_refresh(frame, _do)
                        _collapse_sidebar(page)
                        _close_popups(frame)
                        screenshot_path = os.path.join(screenshot_dir, f"{safe_name}.png")
                        if not _take_iframe_screenshot(page, frame, screenshot_path):
                            continue
                        if _verify_screenshot(screenshot_path):
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
                _collapse_sidebar(page)
                _close_popups(frame)
                _remove_annoying_popups(frame)
                screenshot_path = os.path.join(screenshot_dir, f"{safe_name}.png")
                if not _take_iframe_screenshot(page, frame, screenshot_path):
                    continue
                if _verify_screenshot(screenshot_path):
                    logger.info(f"[SiteOutage] 截图: {safe_name}.png")
                    return screenshot_path
                continue

            logger.warning(f"[SiteOutage] 无法选择选项: {text}")
            return None

        except Exception as e:
            # 失败时清场：关闭可能残留的下拉框
            _cleanup_dropdown_state(frame)
            if attempt == 2:
                save_debug_snapshot(page, DEBUG_DIR, f"select_fail_{safe_name}")
                raise
            logger.warning(f"[SiteOutage] 重试 ({attempt}): {e}")

    # 两次重试都失败后，再清一次场
    _cleanup_dropdown_state(frame)
    return None


def _run_site_outage_once() -> dict:
    """单次完整的截图流程。

    若登录或 iframe 定位失败（瞬时/致命），抛异常给上层 run_with_recovery 重试。
    """
    start_time = time.time()
    result = {
        "success": False,
        "screenshots": [],
        "errors": [],
        "elapsed_seconds": 0,
    }

    from playwright.sync_api import sync_playwright

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    Path(DEBUG_DIR).mkdir(parents=True, exist_ok=True)
    logger.info(f"[SiteOutage] 截图目录: {OUTPUT_DIR}")

    pw = None
    browser = None
    page = None
    try:
        pw = sync_playwright().start()

        def _build_launch_kwargs(mode: str):
            """根据静默模式构造 launch 参数。"""
            if mode == "true":
                return dict(
                    headless=True,
                    args=["--no-sandbox", "--ignore-certificate-errors"],
                )
            elif mode == "offscreen":
                return dict(
                    headless=False,
                    args=[
                        "--start-maximized",
                        "--window-position=-32000,-32000",
                        "--ignore-certificate-errors",
                    ],
                )
            else:
                return dict(
                    headless=False,
                    args=["--start-maximized", "--ignore-certificate-errors"],
                )

        # 启动浏览器，带自动回退：headless 模式启动失败（如 headless shell 缺失）
        # 时自动切到 offscreen 模式重试，避免因浏览器缺失导致整个任务失败
        modes_to_try = [HEADLESS_MODE]
        if HEADLESS_MODE == "true":
            modes_to_try.append("offscreen")  # headless 失败时回退到 offscreen

        last_launch_err = None
        for mode in modes_to_try:
            kw = _build_launch_kwargs(mode)
            try:
                logger.info(f"[SiteOutage] 静默模式: {mode}")
                browser = pw.chromium.launch_persistent_context(
                    USER_DATA_DIR,
                    no_viewport=True,
                    ignore_https_errors=True,
                    **kw,
                )
                if mode != HEADLESS_MODE:
                    logger.warning(f"[SiteOutage] 已自动回退到 {mode} 模式")
                break
            except Exception as e:
                last_launch_err = e
                err_msg = str(e)
                if "Executable doesn't exist" in err_msg or "looks like Playwright" in err_msg.lower():
                    logger.warning(
                        f"[SiteOutage] {mode} 模式启动失败（浏览器缺失），尝试下一模式: {e}"
                    )
                    continue
                # 非浏览器缺失错误，直接抛
                raise

        if browser is None:
            raise FatalError(
                f"浏览器启动失败，已尝试所有模式 {modes_to_try}: {last_launch_err}"
            )

        page = browser.new_page()

        # Login（瞬时失败会抛 TransientError，由顶层重试）
        _login(page)

        # Navigate（iframe 找不到会抛 FatalError，不重试）
        frame = _navigate_to_dashboard(page)

        # Get options
        options = _get_dropdown_options(frame)
        if not options:
            save_debug_snapshot(page, DEBUG_DIR, "no_options")
            result["errors"].append("未找到 RAN Site Type 下拉选项")
            return result

        logger.info(f"[SiteOutage] 找到 {len(options)} 个选项: {[o['text'] for o in options]}")

        # 等待初始 dashboard 图表渲染完成（不再点击任何全屏按钮，避免触发右侧面板）
        _wait_for_charts_rendered(frame, timeout=20000)

        # 逐个选项截图：单选项失败不阻断后续
        for opt in options:
            try:
                # 每次切换选项前确保菜单折叠（防止页面自动展开）
                _collapse_sidebar(page)
                path = _select_and_screenshot(page, frame, opt, OUTPUT_DIR)
                if path:
                    result["screenshots"].append(path)
            except Exception as e:
                err = f"截图失败 [{opt['text']}]: {e}"
                logger.error(f"[SiteOutage] {err}")
                result["errors"].append(err)
                # _select_and_screenshot 内部已清场，这里再保险一次
                _cleanup_dropdown_state(frame)

        # 至少截到 1 张有效图才算成功
        result["success"] = len(result["screenshots"]) > 0 and len(result["errors"]) == 0

    except TransientError:
        # 上抛给 run_with_recovery 处理（瞬时失败可重试）
        if page is not None:
            save_debug_snapshot(page, DEBUG_DIR, "task_transient")
        raise
    except FatalError as e:
        # 致命错误，不重试
        if page is not None:
            save_debug_snapshot(page, DEBUG_DIR, "task_fatal")
        result["errors"].append(f"致命错误: {e}")
        logger.error(f"[SiteOutage] Task fatal: {e}")
    except Exception as e:
        if page is not None:
            save_debug_snapshot(page, DEBUG_DIR, "task_unknown")
        result["errors"].append(str(e))
        logger.error(f"[SiteOutage] Task failed: {e}")

    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _run_site_outage_once: exception swallowed", exc_info=True)
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _run_site_outage_once: exception swallowed", exc_info=True)
                pass

    elapsed = time.time() - start_time
    result["elapsed_seconds"] = round(elapsed, 2)
    logger.info(f"[SiteOutage] Done: {len(result['screenshots'])} screenshots, {elapsed:.2f}s")
    return result


def run_site_outage_screenshot() -> dict:
    """
    Site Outage Dashboard 截图任务（外层入口，带顶层重试）：

    策略：
    - 单次流程抛 TransientError → 最多重试 MAX_TOTAL_RETRY 次
    - 抛 FatalError → 不重试，直接返回带 errors 的 result

    Returns: dict
    """
    overall_start = time.time()
    final_result = {
        "success": False,
        "screenshots": [],
        "errors": [],
        "elapsed_seconds": 0,
    }

    try:
        # 瞬时失败重试，致命错误立即抛
        def _attempt():
            return _run_site_outage_once()

        result = run_with_recovery(
            _attempt,
            max_total_retry=MAX_TOTAL_RETRY,
            label="site_outage",
        )
        final_result["success"] = result.get("success", False)
        final_result["screenshots"] = result.get("screenshots", [])
        final_result["errors"] = result.get("errors", [])

    except FatalError as e:
        # 致命错误，不重试
        final_result["errors"].append(f"致命错误: {e}")
        logger.error(f"[SiteOutage] 顶层 FatalError: {e}")
    except TransientError as e:
        # 重试用尽仍失败
        final_result["errors"].append(f"重试 {MAX_TOTAL_RETRY} 次后仍失败: {e}")
        logger.error(f"[SiteOutage] 顶层 TransientError: {e}")
    except Exception as e:
        final_result["errors"].append(f"未分类异常: {e}")
        logger.error(f"[SiteOutage] 顶层未分类异常: {e}")

    final_result["elapsed_seconds"] = round(time.time() - overall_start, 2)
    logger.info(
        f"[SiteOutage][overall] Done: "
        f"{len(final_result['screenshots'])} screenshots, "
        f"{final_result['elapsed_seconds']}s"
    )
    return final_result


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:site_outage_service>: exception swallowed", exc_info=True)
        pass
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')

    result = run_site_outage_screenshot()
    print(f"\nSite Outage 截图结果: {'成功' if result['success'] else '失败'}")
    print(f"截图数: {len(result['screenshots'])}")
    if result['errors']:
        print(f"错误: {result['errors']}")
    print(f"耗时: {result['elapsed_seconds']}s")
