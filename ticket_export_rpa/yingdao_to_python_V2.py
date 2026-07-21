# -*- coding: utf-8 -*-
"""
影刀 RPA 流程 -> Python 实现

原流程关键点：
1. 打开网页：https://10.100.20.8:28001/api/oauth2/v1/authorize?...
2. 获取窗口对象并最大化
3. 若屏幕上出现指定图像，则依次点击两张图
4. 检测用户名输入框是否可见，若可见则输入 admin / Brysj*8* 并点击 Login
5. 登录后进入 Trouble Ticket 页面，查询并导出数据

使用到的库：
- playwright：网页自动化
- pyautogui + opencv-python：图像识别点击（可选）
- requests：下载 zip 文件

运行前请确保：
1. 将 TARGET_URL 替换为完整的授权 URL
2. 如果需要图像识别分支，准备 IMG_ADVANCED / IMG_CONTINUE 两张截图并配置路径
3. 根据实际页面调整 USERNAME_SELECTOR / PASSWORD_SELECTOR / LOGIN_SELECTOR
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# ---------------------------------------------------------------------------
# 配置区（请按需修改）
# ---------------------------------------------------------------------------

# 目标地址（完整授权URL）
TARGET_URL = "https://10.100.20.8:28001/api/oauth2/v1/authorize?scope=user.login&response_type=code&redirect_uri=/uportal/framework/default.html"

# 登录凭据
USERNAME = "admin"
PASSWORD = "Brysj*8*"

# 图像识别用截图路径（不需要该分支可留空）
IMG_ADVANCED = ""  # 对应原流程 "图像|高级"
IMG_CONTINUE = ""  # 对应原流程 "图像3|继续"

# 是否启用图像识别分支
ENABLE_IMAGE_BRANCH = True

# 是否以无头模式运行（测试环境无界面时用 True；正式桌面运行用 False）
# 也可通过环境变量覆盖：YD_HEADLESS=1 python yingdao_to_python.py
HEADLESS = os.environ.get("YD_HEADLESS", "0") == "1"

# 是否执行登录后的导出流程
ENABLE_EXPORT_FLOW = os.environ.get("YD_EXPORT", "1") == "1"

# Trouble Ticket / Work Order 页面地址
TT_URL = "https://10.100.20.8:28001/uportal/framework/default.html#/_troubleticket"
WO_URL = "https://10.100.20.8:28001/uportal/framework/default.html#/_wo"
# 查询日期配置（备用：如需改为"填指定日期"可启用下方 fill 分支）
QUERY_DATE_LABEL = "Alarm Clear Time"  # 备用的"填日期"字段标签（默认不启用）
QUERY_DATE_VALUE = "2025-12-01 00:00:00"

# 高级查询里需要清空预填时间的字段（按用户要求：去掉 Last Modified Time 里的时间）
CLEAR_TIME_FIELD_LABEL = "Last Modified Time"

# Status 多选面板中的"全选"文本（大小写容错）
STATUS_SELECT_ALL_TEXT = "Select All"

# 导出文件保存目录（保存在项目内的 downloads/ 子目录）
OUTPUT_DIR = Path(__file__).resolve().parent / "downloads"

# 登录元素选择器（根据页面实际 HTML 调整；脚本内置了自动探测候选列表）
USERNAME_SELECTOR = ""  # 例："#username" / "input[name='username']"
PASSWORD_SELECTOR = ""  # 例："#password" / "input[name='password']"
LOGIN_SELECTOR = ""  # 例："button:has-text('Login')" / "input[type='submit']"

# 浏览器可执行文件路径（优先使用项目目录下的 chrome-win/chrome.exe）
BASE_DIR = Path(__file__).resolve().parent


def _find_chrome_exe() -> Path | None:
    """自动查找 chrome.exe。

    查找顺序：
    1. 环境变量 YD_CHROME_EXE（显式指定）
    2. 项目目录下的 chrome-win/
    3. 项目上级目录（D:/01_RPA）下的 chrome-win/  ← Chromium 实际安装位置
    4. 绝对回退路径 D:/01_RPA/chrome-win/chrome-win/chrome.exe
    5. 上述目录树中递归搜索 chrome.exe
    """
    env = os.environ.get("YD_CHROME_EXE")
    if env and Path(env).exists():
        return Path(env)

    parent = BASE_DIR.parent  # 例如 D:/01_RPA
    candidates = [
        BASE_DIR / "chrome-win" / "chrome-win" / "chrome.exe",
        BASE_DIR / "chrome-win" / "chrome.exe",
        parent / "chrome-win" / "chrome-win" / "chrome.exe",
        parent / "chrome-win" / "chrome.exe",
        Path("D:/01_RPA/chrome-win/chrome-win/chrome.exe"),
    ]
    for cand in candidates:
        if cand.exists():
            return cand
    # 兜底：在目录树中递归搜索
    for base in (BASE_DIR / "chrome-win", parent / "chrome-win"):
        try:
            for exe in base.rglob("chrome.exe"):
                return exe
        except Exception:
            continue
    return None


CHROME_EXE = _find_chrome_exe()

# 日志开关
VERBOSE = True

# ---------------------------------------------------------------------------
# 依赖检查
# ---------------------------------------------------------------------------


def _check_dependencies() -> None:
    missing = []
    try:
        import cv2  # noqa: F401
    except ImportError:
        missing.append("opencv-python")
    try:
        import pyautogui  # noqa: F401
    except ImportError:
        missing.append("pyautogui")
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout  # noqa: F401
    except ImportError:
        missing.append("playwright")
    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")

    if missing:
        print("缺少以下依赖，请先安装：")
        print(f"  pip install {' '.join(missing)}")
        print("另外 playwright 还需要下载浏览器：")
        print("  playwright install chromium")
        sys.exit(1)


_check_dependencies()

import cv2
import numpy as np
import pyautogui
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    if VERBOSE:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def wait(seconds: int) -> None:
    """对应影刀流程中的 "等待 N 秒"。"""
    log(f"等待 {seconds} 秒...")
    time.sleep(seconds)


def click_image_if_found(image_path: str, confidence: float = 0.8) -> bool:
    """
    对应影刀流程中的 "IF 图像存在" + "点击图像"。
    在屏幕上查找指定图像，若找到则点击其中心点。
    """
    if not image_path or not Path(image_path).exists():
        log(f"图像路径无效或不存在：{image_path}")
        return False

    try:
        location = pyautogui.locateCenterOnScreen(
            image_path,
            confidence=confidence,
            grayscale=True,
        )
        if location:
            x, y = location
            log(f"找到图像 {image_path}，位置 ({x}, {y})，点击中心点")
            pyautogui.click(x, y)
            return True
        else:
            log(f"未在屏幕上找到图像 {image_path}")
    except Exception as exc:
        log(f"图像识别出错 {image_path}: {exc}")
    return False


def detect_selector(page, candidates: list[str]) -> str | None:
    """从候选选择器中返回第一个在页面上可见的（自动处理多匹配）。"""
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


def safe_screenshot(page_or_frame, name: str) -> None:
    """截图到项目内的 process/ 目录，方便调试。兼容 Page 和 Frame。"""
    try:
        shot_dir = BASE_DIR / "process"
        shot_dir.mkdir(parents=True, exist_ok=True)
        shot = shot_dir / f"{name}.png"
        if hasattr(page_or_frame, "screenshot") and callable(getattr(page_or_frame, "screenshot")):
            page_or_frame.screenshot(path=str(shot))
        else:
            page_or_frame.locator("body").first.screenshot(path=str(shot))
        log(f"已截图：{shot}")
    except Exception as exc:
        log(f"截图失败：{exc}")


def maximize_window(page) -> None:
    """尽力最大化浏览器窗口（仅桌面模式；无头模式跳过）。

    通过启动参数 --start-maximized 已能最大化；此处再用 JS 兜底一次，
    确保登录后的浏览器窗口确实处于最大化状态。
    """
    if HEADLESS:
        return
    try:
        page.evaluate(
            "() => { try { window.moveTo(0,0); "
            "window.resizeTo(window.screen.availWidth, window.screen.availHeight); } catch(e){} }"
        )
        log("已尝试通过 JS 最大化窗口")
    except Exception as exc:
        log(f"JS 最大化失败（不影响主流程）：{exc}")


def safe_click_by_text(page, text: str, exact: bool = False, timeout: int = 10000) -> bool:
    """安全点击包含指定文本的元素。优先点击第一个可见元素，避免点到隐藏的 DOM 节点。"""
    try:
        loc = page.get_by_text(text, exact=exact)
        count = loc.count()
        if count == 0:
            log(f"未找到文本：{text}")
            return False
        # 优先点击第一个可见元素
        for i in range(count):
            try:
                nth = loc.nth(i)
                if nth.is_visible(timeout=min(timeout, 1000)):
                    nth.click(timeout=timeout)
                    log(f"已点击：{text}")
                    return True
            except Exception:
                continue
        # 兜底 1：force click 第一个（元素存在但 Playwright 认为不可见）
        try:
            loc.first.click(timeout=timeout, force=True)
            log(f"已点击：{text}（force click）")
            return True
        except Exception:
            pass
        # 兜底 2：JS click
        try:
            page.evaluate(f"""() => {{
                const els = [...document.querySelectorAll('*')];
                const target = els.find(e => (e.innerText || e.textContent || '').trim().includes("{text}") && e.offsetHeight > 0);
                if (target) {{ target.click(); return true; }}
                return false;
            }}""")
            log(f"已点击：{text}（JS click）")
            return True
        except Exception:
            pass
        return False
    except Exception as exc:
        log(f"点击 '{text}' 失败：{exc}")
        return False


def click_by_text_or_selector(page, text: str, selectors: list[str] | None = None, timeout: int = 3000) -> bool:
    """
    优先按文本点击；若失败则尝试给定的选择器列表；最后尝试 JS 按 innerText 匹配。
    """
    if safe_click_by_text(page, text, exact=False, timeout=timeout):
        return True

    if selectors:
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if loc.count() == 0:
                    continue
                # 优先点击第一个可见元素
                for i in range(loc.count()):
                    try:
                        nth = loc.nth(i)
                        if nth.is_visible(timeout=500):
                            nth.click(timeout=timeout)
                            log(f"已使用选择器点击 '{text}'：{sel}")
                            return True
                    except Exception:
                        continue
            except Exception:
                continue

    # 等待页面渲染（给 SPA/Shadow DOM 组件挂载时间）
    try:
        page.wait_for_timeout(2000)
    except Exception:
        pass

    # JS 兜底：递归遍历主文档、所有 shadowRoot、所有 iframe contentDocument 查找文本并点击
    try:
        clicked = page.evaluate(f"""() => {{
            const targetText = "{text}";

            function deepClick(root) {{
                if (!root || !root.querySelectorAll) return false;
                // 遍历当前 root 下所有元素
                const els = [...root.querySelectorAll('*')];
                for (const el of els) {{
                    // 递归进入 shadowRoot
                    if (el.shadowRoot) {{
                        if (deepClick(el.shadowRoot)) return true;
                    }}
                }}
                for (const el of els) {{
                    const t = (el.innerText || '').trim();
                    if (t.includes(targetText) && el.click) {{
                        el.click();
                        return true;
                    }}
                }}
                return false;
            }}

            // 1. 搜索主文档
            if (deepClick(document)) return true;

            // 2. 搜索所有同源 iframe
            const iframes = document.querySelectorAll('iframe');
            for (const ifr of iframes) {{
                try {{
                    if (ifr.contentDocument && deepClick(ifr.contentDocument)) return true;
                }} catch(e) {{}}
            }}
            return false;
        }}""")
        if clicked:
            log(f"已使用深度学习 JS 点击文本：{text}")
            return True
    except Exception as exc:
        log(f"JS 点击 '{text}' 失败：{exc}")

    return False


def get_tt_frame11(page, max_attempts: int = 5) -> object:
    """定位 Trouble Ticket 页面所在的 iframe 并返回其 content frame。

    ZTE uSmartNet 把业务页面渲染在 iframe[class^="page-mainIframe"] 中，
    因此 All Tickets / Advanced Query / Export 等按钮都在 iframe 里，
    必须切到 iframe frame 再操作。

    这个过程会枚举页面所有 iframe，输出诊断日志。
    如果没有找到合适 iframe，则回退到顶层 page。
    """
    # Step 1: 枚举页面上所有 iframe（诊断日志）
    try:
        all_iframes = page.locator("iframe").all()
        log(f"页面上共有 {len(all_iframes)} 个 iframe:")
        for idx, ifr in enumerate(all_iframes):
            src = (ifr.get_attribute("src") or "(无 src)")[:120]
            cls = (ifr.get_attribute("class") or "(无 class)")[:80]
            try:
                vis = ifr.is_visible()
            except Exception:
                vis = "error"
            log(f"  iframe[{idx}]: class={cls}  src={src}  visible={vis}")
    except Exception as exc:
        log(f"枚举 iframe 时出错（可能是页面未加载完成）：{exc}")

    # Step 2: 尝试所有可能的 iframe，只要内容加载了就返回
    for attempt in range(1, max_attempts + 1):
        log(f"尝试定位 Trouble Ticket iframe（第 {attempt}/{max_attempts} 次）...")
        # 2a: 尝试各种 iframe 选择器
        iframe_selectors = [
            'iframe[class^="page-mainIframe"]',
            'iframe[src*="troubleticket"]',
            'iframe[src*="ticket"]',
            "iframe",
        ]
        for sel in iframe_selectors:
            try:
                iframe = page.locator(sel).first
                if iframe.count() == 0:
                    continue
                iframe.wait_for(state="attached", timeout=5000)
                # 注意：locator.content_frame 是 FrameLocator（不是 Frame），
                # 必须通过 element_handle().content_frame() 才能拿到真正的 Frame
                try:
                    if_elem = iframe.element_handle(timeout=5000)
                    frame = if_elem.content_frame()
                except Exception:
                    frame = None
                if frame is None:
                    continue
                # 等待 iframe 加载
                try:
                    frame.wait_for_load_state("domcontentloaded", timeout=10000)
                    frame.wait_for_timeout(2000)
                except Exception:
                    pass
                # 检查是否有内容
                try:
                    body_text = frame.locator("body").inner_text(timeout=3000)
                    if len(body_text.strip()) > 50:
                        log(f"发现 iframe（选择器: {sel}），含 {len(body_text.strip())} 字符内容，已使用")
                        return frame
                except Exception:
                    pass
            except Exception:
                continue
        page.wait_for_timeout(3000)

    # Step 3: 备选 — 如果有 iframe 但都无内容，返回第一个
    try:
        iframe = page.locator("iframe").first
        if iframe.count():
            frame = iframe.content_frame()
            if frame is not None:
                log("未找到有内容的 iframe，使用第一个 iframe 的 frame")
                return frame
    except Exception:
        pass

    log("未找到任何可用的 iframe，回退到顶层 page")
    return page

def get_tt_frame(page, max_attempts: int = 5) -> object:
    """定位 Trouble Ticket 页面所在的 iframe 并返回其 content frame。"""
    # Step 1: 枚举页面上所有 iframe（诊断日志）
    try:
        all_iframes = page.locator("iframe").all()
        log(f"页面上共有 {len(all_iframes)} 个 iframe:")
        for idx, ifr in enumerate(all_iframes):
            src = (ifr.get_attribute("src") or "(无 src)")[:120]
            cls = (ifr.get_attribute("class") or "(无 class)")[:80]
            try:
                vis = ifr.is_visible()
            except Exception:
                vis = "error"
            log(f"  iframe[{idx}]: class={cls}  src={src}  visible={vis}")
    except Exception as exc:
        log(f"枚举 iframe 时出错（可能是页面未加载完成）：{exc}")

    # Step 2: 尝试所有可能的 iframe，只要内容加载了就返回
    for attempt in range(1, max_attempts + 1):
        log(f"尝试定位 Trouble Ticket iframe（第 {attempt}/{max_attempts} 次）...")
        # 2a: 尝试各种 iframe 选择器
        iframe_selectors = [
            'iframe[class^="page-mainIframe"]',
            'iframe[src*="troubleticket"]',
            'iframe[src*="ticket"]',
            "iframe",
        ]
        for sel in iframe_selectors:
            try:
                iframe = page.locator(sel).first
                if iframe.count() == 0:
                    continue
                iframe.wait_for(state="attached", timeout=5000)
                
                # 【修复核心点】：先获取 ElementHandle，再获取 content_frame()
                handle = iframe.element_handle()
                frame = handle.content_frame() if handle else None
                
                if frame is None:
                    continue
                # 等待 iframe 加载
                try:
                    frame.wait_for_load_state("domcontentloaded", timeout=10000)
                    frame.wait_for_timeout(2000)
                except Exception:
                    pass
                # 检查是否有内容
                try:
                    body_text = frame.locator("body").inner_text(timeout=3000)
                    if len(body_text.strip()) > 50:
                        log(f"发现 iframe（选择器: {sel}），含 {len(body_text.strip())} 字符内容，已使用")
                        return frame
                except Exception:
                    pass
            except Exception as e:
                log(f"定位 iframe 失败：{e}")
                continue
        page.wait_for_timeout(3000)

    # Step 3: 备选 — 如果有 iframe 但都无内容，返回第一个
    try:
        iframe = page.locator("iframe").first
        if iframe.count():
            # 【修复核心点】：同样修改备选方案中的获取方式
            handle = iframe.element_handle()
            frame = handle.content_frame() if handle else None
            if frame is not None:
                log("未找到有内容的 iframe，使用第一个 iframe 的 frame")
                return frame
    except Exception:
        pass

    log("未找到任何可用的 iframe，回退到顶层 page")
    return page

# ---------------------------------------------------------------------------
# 导出流程
# ---------------------------------------------------------------------------


def run_export_flow(page, context, target_url=None, default_table_type="eflow-tt") -> None:
    """登录后执行：进入 Trouble Ticket / Work Order -> 高级查询 -> 输入日期 -> 查询 -> 导出 -> 下载。"""
    log("=== 开始导出流程 ===")

    # 确定页面标识（用于文本匹配的容错）
    PAGE_LABEL = "Work Order" if "_wo" in (target_url or "") else "Trouble Ticket"

    # 1. 进入目标页面
    url = target_url or "https://10.100.20.8:28001/uportal/framework/default.html#/_troubleticket"
    log(f"导航到：{url}")
    page.goto(url, timeout=60000)

    # 等待页面标题/核心元素出现（最长 30 秒）
    try:
        page.wait_for_selector(f"text={PAGE_LABEL}", timeout=15000)
        log(f"{PAGE_LABEL} 页面已出现")
    except PlaywrightTimeout:
        log(f"等待 {PAGE_LABEL} 文本超时（可能页面标题不同），继续执行")
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except PlaywrightTimeout:
        log("networkidle 等待超时，继续执行")

    # 尝试关闭常见的引导/提示弹窗（本机首次登录可能出现）
    for sel in [
        "text=Navigation Menu Access Path >> xpath=../button",
        "text=Navigation Menu Access Path >> xpath=.. >> button",
        "[class*='novice-guide'] .plx-ico-close",
        "[class*='novice-guide'] .plx-ico-close-16",
        "[class*='modal-close']",
        "[class*='dialog-close']",
    ]:
        try:
            page.locator(sel).first.click(timeout=500)
            log("已关闭弹窗")
            break
        except Exception:
            continue
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass

    page.wait_for_timeout(2000)
    safe_screenshot(page, "01_tt_page")

    # 关键：业务页面渲染在 iframe 中，必须切到 iframe frame 才能点击按钮
    frame = get_tt_frame(page)
    if frame is page:
        log("未能定位到 iframe，将尝试在顶层 page 上继续（大概率失败），继续执行")
    else:
        log("后续操作将在 iframe frame 中执行")

    # 1b. 显式点击 All Tickets 标签页（确保进入全部工单视图）
    if click_by_text_or_selector(frame, "All Tickets", selectors=[
        ".ant-tabs-tab:has-text('All Tickets')",
        "div[role='tab']:has-text('All Tickets')",
        "a:has-text('All Tickets')",
        "span:has-text('All Tickets')",
        "[class*='tab']:has-text('All Tickets')",
    ]):
        log("已点击 All Tickets 标签")
        frame.wait_for_timeout(2000)
    else:
        log("未找到 All Tickets 标签，继续执行")

    # 2. 点击 Advanced Query（高级查询）
    if not click_by_text_or_selector(frame, "Advanced Query", selectors=[
        "button:has-text('Advanced Query')",
        "a:has-text('Advanced Query')",
        "span:has-text('Advanced Query')",
        "[title='Advanced Query']",
        "[aria-label='Advanced Query']",
        "[class*='advanced-query']",
        "[class*='advancedQuery']",
        "[class*='AdvancedQuery']",
        "i[class*='query']",
    ]):
        log("未找到 Advanced Query 按钮，跳过")
        # 诊断：在当前上下文查找所有包含 "Advanced" 文字的可见元素
        try:
            diag = frame.evaluate("""() => {
                const els = [...document.querySelectorAll('*')].filter(e =>
                    e.innerText && e.innerText.includes('Advanced')
                );
                return els.slice(0, 15).map(e => ({
                    tag: e.tagName,
                    text: (e.innerText || '').substring(0, 80),
                    visible: e.offsetParent !== null,
                    dim: e.getBoundingClientRect() ?
                        Math.round(e.getBoundingClientRect().width)+'x'+Math.round(e.getBoundingClientRect().height) : 'none'
                }));
            }""")
            log(f"[诊断] 当前上下文中包含 'Advanced' 的元素 ({len(diag)} 个):")
            for d in diag:
                log(f"  {d['tag']} visible={d['visible']} dim={d['dim']} text=\"{d['text']}\"")
        except Exception as dex:
            log(f"[诊断] 查找 Advanced 元素失败：{dex}")
        safe_screenshot(page, "02_no_advanced_query")
        return

    frame.wait_for_timeout(2000)
    safe_screenshot(page, "02_advanced_query_form")

    # 3. 填写 Last Modified Time 的开始时间为 2025-12-01 00:00:00，结束时间保持默认
    fill_last_modified_start_time(frame, page, "2025-12-01 00:00:00")
    frame.wait_for_timeout(1000)
    safe_screenshot(page, "03_last_modified_start_set")

    # 4. 点击 Status 字段，并在多选面板中点击 Select All
    click_status_select_all(frame)
    safe_screenshot(page, "04_status_all")

    # 5. 点击 Query 查询
    if not click_by_text_or_selector(frame, "Query", selectors=[
        "button:has-text('Query')",
        "a:has-text('Query')",
        "span:has-text('Query')",
        "button[type='submit']",
        "[class*='query']",
        "[class*='search']",
    ]):
        log("未找到 Query 按钮，继续执行")
    frame.wait_for_load_state("networkidle", timeout=30000)
    # 等待查询结果表格渲染完成（确保查询已返回）
    try:
        frame.wait_for_selector(
            "table tbody tr, [class*='plx-body--row'], [class*='row']",
            timeout=30000,
        )
        log("查询结果已加载")
    except PlaywrightTimeout:
        log("等待查询结果表格超时，继续执行")
    frame.wait_for_timeout(2000)
    safe_screenshot(page, "05_query_result")

    # 6. 点击 Export -> Export Setting（Export 按钮和菜单可能在 page 或 frame 中）
    export_setting_opened = False
    for ctx_name, ctx, other in [("frame", frame, page), ("page", page, frame)]:
        if click_export_dropdown(ctx, "Export Setting", page=page, extra_ctx=other):
            log(f"已打开 Export Setting (在 {ctx_name} 中)")
            export_setting_opened = True
            break
    if not export_setting_opened:
        log("导出设置菜单未打开，跳过导出流程")
        return

    # 等待 Export Setting 弹窗出现（检测 plx-picklist 或 Clear/Confirm 按钮）
    dialog_found = False
    for _ in range(10):
        for ctx in [frame, page]:
            try:
                has_dialog = ctx.evaluate("""() => {
                    return !!(document.querySelector('button.plx-picklist-btn-clear') ||
                              document.querySelector('plx-picklist') ||
                              document.querySelector('[class*="picklist"]') ||
                              document.querySelector('button.plx-btn-primary'));
                }""")
                if has_dialog:
                    dialog_found = True
                    break
            except Exception:
                pass
        if dialog_found:
            break
        page.wait_for_timeout(1000)

    if dialog_found:
        log("Export Setting 弹窗已出现")
    else:
        log("等待 10 秒后仍未检测到 Export Setting 弹窗元素，继续尝试操作")

    frame.wait_for_timeout(1000)
    safe_screenshot(page, "06_export_setting_dialog")

    # 6a. 弹窗内：点击 Clear，再勾选 Available 前的复选框
    # Export Setting 弹窗使用 plx-picklist 自定义组件，需要精确选择器
    frame.wait_for_timeout(1500)

    # 点击 Clear 按钮（plx-picklist 组件内的清除按钮）
    clear_clicked = False
    for ctx_name, ctx in [("frame", frame), ("page", page)]:
        # 方案 1: Playwright locator force click
        try:
            clear_btn = ctx.locator("button.plx-picklist-btn-clear")
            if clear_btn.count() > 0:
                clear_btn.first.click(timeout=3000, force=True)
                log(f"已点击 plx-picklist Clear 按钮 (在 {ctx_name} 中)")
                clear_clicked = True
                break
        except Exception:
            pass
        # 方案 2: 坐标点击
        if not clear_clicked:
            try:
                clear_box = ctx.evaluate("""() => {
                    const btn = document.querySelector('button.plx-picklist-btn-clear');
                    if (btn) {
                        const rect = btn.getBoundingClientRect();
                        return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
                    }
                    // 兜底：找文本为 Clear 的按钮
                    const all = [...document.querySelectorAll('button, a, span')];
                    const target = all.find(e => (e.innerText || '').trim() === 'Clear' && e.offsetHeight > 0);
                    if (target) {
                        const rect = target.getBoundingClientRect();
                        return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
                    }
                    return null;
                }""")
                if clear_box:
                    offset = _get_iframe_offset(page, ctx)
                    page.mouse.click(offset['x'] + clear_box['x'], offset['y'] + clear_box['y'])
                    log(f"已通过坐标点击 Clear 按钮 (在 {ctx_name} 中)")
                    clear_clicked = True
                    break
            except Exception:
                pass
        # 方案 3: 通用选择器
        if not clear_clicked:
            if click_by_text_or_selector(ctx, "Clear", selectors=[
                "button.plx-picklist-btn-clear",
                "button:has-text('Clear')",
                "[class*='picklist'] button:has-text('Clear')",
            ]):
                log(f"已点击 Export Setting 弹窗内的 Clear (在 {ctx_name} 中)")
                clear_clicked = True
                break
    if not clear_clicked:
        log("未找到 Clear 按钮（可能无需清空），继续")
    frame.wait_for_timeout(1000)
    safe_screenshot(page, "06b_clear")

    # 勾选 Available 前的复选框（plx-picklist 左侧面板的全选复选框）
    available_checked = False
    for ctx_name, ctx in [("frame", frame), ("page", page)]:
        try:
            # 使用 JS 在 plx-picklist 左侧面板中找到 Available 旁的复选框并勾选
            checked = ctx.evaluate("""() => {
                // 查找 plx-picklist 组件
                const picklists = document.querySelectorAll('plx-picklist, [class*="picklist"]');
                for (const pl of picklists) {
                    // 查找左侧面板中包含 "Available" 文本的区域
                    const leftWrapper = pl.querySelector('[class*="picklist-left"], [class*="left-wrapper"]');
                    const searchRoot = leftWrapper || pl;
                    // 查找复选框：可能是 input[type=checkbox] 或自定义的 checkbox 元素
                    const checkboxes = searchRoot.querySelectorAll(
                        'input[type="checkbox"], [class*="checkbox"], [role="checkbox"], .plx-checkbox'
                    );
                    for (const cb of checkboxes) {
                        // 检查这个复选框是否在 Available 标题行附近
                        const parent = cb.closest('[class*="summary"], [class*="header"], [class*="title"]') || cb.parentElement;
                        if (parent) {
                            const text = parent.innerText || parent.textContent || '';
                            if (text.includes('Available') || text.includes('Avaiable')) {
                                // 点击勾选
                                if (cb.tagName === 'INPUT') {
                                    if (!cb.checked) cb.click();
                                } else {
                                    cb.click();
                                }
                                return true;
                            }
                        }
                    }
                    // 如果没找到带 Available 文本的，尝试点击左侧面板的第一个复选框（通常是全选）
                    const firstCb = searchRoot.querySelector(
                        'input[type="checkbox"], [class*="checkbox"], [role="checkbox"], .plx-checkbox'
                    );
                    if (firstCb) {
                        if (firstCb.tagName === 'INPUT') {
                            if (!firstCb.checked) firstCb.click();
                        } else {
                            firstCb.click();
                        }
                        return true;
                    }
                }
                return false;
            }""")
            if checked:
                log(f"已通过 JS 勾选 Available 复选框 (在 {ctx_name} 中)")
                available_checked = True
                break
        except Exception as e:
            log(f"JS 勾选 Available 异常 ({ctx_name})：{e}")
    if not available_checked:
        log("未找到 Available 复选框（可能已默认勾选），继续")
    frame.wait_for_timeout(1000)
    safe_screenshot(page, "06c_available_checked")

    # 6b. 点击 Confirm（确认导出）
    # 设置网络拦截，捕获导出生成返回的 fileName / ftpFilePath
    export_info = {}

    def handle_export_response(response):
        url = response.url
        if "/api/eflow-ticket/" not in url:
            return
        try:
            body_text = response.text()
        except Exception:
            return
        if "fileName" in body_text and "ftpFilePath" in body_text:
            try:
                data = json.loads(body_text)
                export_info.update(data)
                log(f"捕获导出生成响应：{url}")
            except Exception:
                pass

    page.on("response", handle_export_response)

    confirm_clicked = False
    for ctx_name, ctx in [("frame", frame), ("page", page)]:
        # 方案 1: Playwright locator force click
        try:
            confirm_btn = ctx.locator("button.plx-btn-primary:has-text('Confirm'), button.plx-btn--primary:has-text('Confirm')")
            if confirm_btn.count() > 0:
                confirm_btn.first.click(timeout=3000, force=True)
                log(f"已点击 plx Confirm 按钮 (在 {ctx_name} 中)")
                confirm_clicked = True
                break
        except Exception:
            pass
        # 方案 2: 坐标点击
        if not confirm_clicked:
            try:
                confirm_box = ctx.evaluate("""() => {
                    // 优先找 plx 主按钮
                    let btn = document.querySelector('button.plx-btn-primary');
                    if (!btn) {
                        // 兜底：找文本为 Confirm 的按钮
                        const all = [...document.querySelectorAll('button')];
                        btn = all.find(e => (e.innerText || '').trim() === 'Confirm' && e.offsetHeight > 0);
                    }
                    if (btn) {
                        const rect = btn.getBoundingClientRect();
                        return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
                    }
                    return null;
                }""")
                if confirm_box:
                    offset = _get_iframe_offset(page, ctx)
                    page.mouse.click(offset['x'] + confirm_box['x'], offset['y'] + confirm_box['y'])
                    log(f"已通过坐标点击 Confirm 按钮 (在 {ctx_name} 中)")
                    confirm_clicked = True
                    break
            except Exception:
                pass
        # 方案 3: 通用选择器
        if not confirm_clicked:
            try:
                for sel in [
                    "button:has-text('Confirm')",
                    "button.plx-btn-primary",
                    "button.ant-btn-primary",
                ]:
                    loc = ctx.locator(sel).first
                    if loc.count() > 0:
                        loc.click(timeout=3000, force=True)
                        log(f"已通过 force click 点击 Confirm 按钮 (在 {ctx_name} 中, sel={sel})")
                        confirm_clicked = True
                        break
            except Exception:
                pass
    if not confirm_clicked:
        log("未找到 Confirm 按钮，继续执行")
    frame.wait_for_timeout(3000)
    safe_screenshot(page, "07_export_confirmed")

    # 7. 点击 Export -> My Export
    my_export_opened = False
    for ctx_name, ctx, other in [("page", page, frame), ("frame", frame, page)]:
        if click_export_dropdown(ctx, "My Export", page=page, extra_ctx=other):
            log(f"已打开 My Export (在 {ctx_name} 中)")
            my_export_opened = True
            break
    if not my_export_opened:
        log("未能打开 My Export，尝试直接查找 My Export")
        for ctx in [page, frame]:
            if safe_click_by_text(ctx, "My Export"):
                break
    frame.wait_for_timeout(3000)
    safe_screenshot(page, "08_my_export_list")

    # 8. 轮询 My Export：每 5 秒刷新，等最新记录 Status=Success 后点击 Download
    download_request_info = {}

    def handle_download_request(request):
        if "/api/eflow-ticket/v1/attachment/download/" in request.url and request.method == "POST":
            download_request_info["url"] = request.url
            download_request_info["body"] = request.post_data
            log(f"捕获下载请求：{request.url}")

    page.on("request", handle_download_request)

    wait_my_export_and_download(frame, page, context, download_request_info, table_type=default_table_type)

    # 兜底：如果浏览器下载未成功，但 export_info 有数据，尝试用 requests 下载
    downloaded_files = list(OUTPUT_DIR.iterdir())
    recent_files = [f for f in downloaded_files if f.is_file() and not f.name.endswith((".crdownload", ".tmp", ".part"))]
    if not recent_files and export_info.get("fileName") and export_info.get("ftpFilePath"):
        log("浏览器下载未产生文件，使用 Confirm 响应信息兜底")
        download_export(page, context, export_info)


def fill_date_by_label(page, label: str, value: str) -> bool:
    """根据标签文本查找日期输入框并填写。"""
    try:
        # 方法 1：通过 label 元素的 for 属性
        label_loc = page.locator(f"label:has-text('{label}')")
        if label_loc.count() == 0:
            label_loc = page.get_by_text(label, exact=False)
        if label_loc.count() == 0:
            return False

        # 找到 label 的父级/兄弟 input
        # 通常结构：label + div > input 或者 div > label + div > input
        for i in range(min(label_loc.count(), 3)):
            try:
                lbl = label_loc.nth(i)
                # 向上找 3 层父级，然后找 input
                parent = lbl.locator("xpath=..")
                for _ in range(3):
                    inputs = parent.locator("input").all()
                    if inputs:
                        for inp in inputs:
                            try:
                                inp.fill(value)
                                log(f"已填写日期 {label} = {value}")
                                return True
                            except Exception:
                                continue
                    parent = parent.locator("xpath=..")
            except Exception:
                continue
    except Exception as exc:
        log(f"fill_date_by_label 异常：{exc}")
    return False


def fill_first_date_input(page, value: str) -> None:
    """兜底：填写页面上第一个可用的日期/时间输入框。"""
    try:
        inputs = page.locator("input").all()
        for inp in inputs:
            try:
                ph = inp.get_attribute("placeholder") or ""
                cls = inp.get_attribute("class") or ""
                if any(k in (ph + cls).lower() for k in ["date", "time", "yyyy", "mm", "dd"]):
                    inp.fill(value)
                    log(f"兜底填写日期输入框：{value}")
                    return
            except Exception:
                continue
        # 如果还没找到，尝试所有 input
        for inp in inputs[:10]:
            try:
                typ = inp.get_attribute("type") or "text"
                if typ in ("text", "input"):
                    inp.fill(value)
                    log(f"兜底填写第一个文本输入框：{value}")
                    return
            except Exception:
                continue
    except Exception as exc:
        log(f"fill_first_date_input 异常：{exc}")


def fill_last_modified_start_time(frame, page, value: str) -> bool:
    """填写 Last Modified Time 的开始时间（第一个输入框），结束时间保持默认。

    frame: iframe 的 Frame 对象（元素在 iframe 内）
    page: 主页面 Page 对象（用于 mouse/keyboard 操作）
    使用 Playwright 键盘输入以触发 Angular 响应式表单更新。
    """
    log(f"尝试填写 Last Modified Time 开始时间 = {value}")
    try:
        # 在 frame 中用 JS 定位开始时间 input，获取相对于 iframe 的坐标
        box = frame.evaluate("""() => {
            const allEls = [...document.querySelectorAll('label, span, td, th, div')];
            const labels = allEls.filter(e => {
                const t = (e.innerText || e.textContent || '').trim();
                return t === 'Last Modified Time' && e.children.length === 0;
            });
            for (const lbl of labels) {
                let p = lbl.parentElement;
                for (let i = 0; i < 6; i++) {
                    if (!p) break;
                    const inputs = p.querySelectorAll('input');
                    if (inputs.length >= 1) {
                        const rect = inputs[0].getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
                        }
                    }
                    p = p.parentElement;
                }
            }
            return null;
        }""")

        if box:
            # 获取 iframe 在主页面中的偏移量
            iframe_offset = page.evaluate("""() => {
                const iframes = document.querySelectorAll('iframe');
                for (const iframe of iframes) {
                    const rect = iframe.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        return {x: rect.x, y: rect.y};
                    }
                }
                return {x: 0, y: 0};
            }""")

            # 计算绝对坐标 = iframe偏移 + 元素在iframe内的坐标
            abs_x = iframe_offset['x'] + box['x']
            abs_y = iframe_offset['y'] + box['y']
            log(f"  Last Modified Time 输入框坐标: iframe内({box['x']:.0f},{box['y']:.0f}) + 偏移({iframe_offset['x']:.0f},{iframe_offset['y']:.0f}) = 绝对({abs_x:.0f},{abs_y:.0f})")

            # 用 page 的 mouse 点击（绝对坐标）
            page.mouse.click(abs_x, abs_y)
            page.wait_for_timeout(300)
            # 全选并删除现有内容
            page.keyboard.press("Control+a")
            page.keyboard.press("Backspace")
            page.wait_for_timeout(200)
            # 逐字输入新值
            page.keyboard.type(value, delay=50)
            page.wait_for_timeout(300)
            # 按 Tab 触发 blur/change
            page.keyboard.press("Tab")
            page.wait_for_timeout(500)
            log(f"已通过键盘输入填写 Last Modified Time 开始时间 = {value}")
            return True

        # 兜底：用 frame locator 点击 + page keyboard 输入
        label_loc = frame.locator("label:has-text('Last Modified Time'), span:text-is('Last Modified Time')")
        if label_loc.count() > 0:
            lbl = label_loc.first
            parent = lbl.locator("xpath=..")
            for _ in range(4):
                inputs = parent.locator("input").all()
                if inputs:
                    inp = inputs[0]
                    inp.click()
                    page.wait_for_timeout(200)
                    page.keyboard.press("Control+a")
                    page.keyboard.press("Backspace")
                    page.wait_for_timeout(200)
                    page.keyboard.type(value, delay=50)
                    page.keyboard.press("Tab")
                    log(f"已通过 locator 键盘输入填写 Last Modified Time 开始时间 = {value}")
                    return True
                parent = parent.locator("xpath=..")

        log("未找到 Last Modified Time 开始时间输入框")
        return False
    except Exception as e:
        log(f"填写 Last Modified Time 开始时间异常：{e}")
        return False


def clear_field_by_label(page, label: str) -> bool:
    """根据标签文本查找对应的输入框/选择器并清空其值（去掉预填的时间）。"""
    log(f"尝试清空字段：{label}")
    try:
        label_loc = page.locator(f"label:has-text('{label}')")
        if label_loc.count() == 0:
            label_loc = page.get_by_text(label, exact=False)
        if label_loc.count() == 0:
            log(f"未找到标签 {label}，跳过清空")
            return False

        found = False
        for i in range(min(label_loc.count(), 3)):
            lbl = label_loc.nth(i)
            parent = lbl.locator("xpath=..")
            for _ in range(3):
                inputs = parent.locator("input, select, textarea").all()
                if inputs:
                    for inp in inputs:
                        try:
                            tag = inp.evaluate("el => el.tagName").lower()
                            if tag == "select":
                                try:
                                    inp.select_option("", timeout=2000)
                                except Exception:
                                    pass
                            else:
                                inp.fill("", timeout=2000)
                            # 尝试点击字段内的清空（x）图标
                            try:
                                inp.locator(
                                    "xpath=../descendant::i[contains(@class,'close')]"
                                ).click(timeout=500)
                            except Exception:
                                pass
                            log(f"已清空字段 {label}")
                            found = True
                        except Exception:
                            continue
                    if found:
                        break
                parent = parent.locator("xpath=..")
            if found:
                break

        # JS 兜底：清除所有匹配 label 的相邻 input/select 的 value
        if not found:
            page.evaluate(f"""() => {{
                const text = "{label}";
                const labels = [...document.querySelectorAll('label')]
                    .filter(l => l.innerText && l.innerText.includes(text));
                for (const l of labels) {{
                    let el = l;
                    for (let d = 0; d < 4; d++) {{
                        el = el.parentElement;
                        if (!el) break;
                        const ctrls = el.querySelectorAll('input, select, textarea');
                        for (const c of ctrls) {{
                            try {{
                                c.value = '';
                                c.dispatchEvent(new Event('input', {{bubbles:true}}));
                                c.dispatchEvent(new Event('change', {{bubbles:true}}));
                            }} catch(e) {{}}
                        }}
                    }}
                }}
            }}""")
            log(f"已通过 JS 兜底清空字段 {label}")
        return True
    except Exception as exc:
        log(f"clear_field_by_label 异常：{exc}")
    return False


def check_checkbox_by_label(page, label: str) -> bool:
    """勾选某个标签（如 Available）前面的复选框。

    用户描述："点击 Avaiable 前的勾选" => 勾选 Available 字段前面的 checkbox。
    兼容 "Available" / "Avaiable" 拼写。
    """
    log(f"尝试勾选字段前的复选框：{label}")
    try:
        label_loc = page.locator(f"label:has-text('{label}')")
        if label_loc.count() == 0:
            label_loc = page.get_by_text(label, exact=False)
        if label_loc.count() == 0:
            log(f"未找到标签 {label}")
            return False

        # 相对 XPath：checkbox 可能在 label 之前（preceding-sibling）或同父级内
        xpath_candidates = [
            "xpath=./preceding-sibling::input[@type='checkbox']",
            "xpath=../input[@type='checkbox']",
            "xpath=../../input[@type='checkbox']",
            "xpath=./following-sibling::input[@type='checkbox']",
        ]
        for i in range(min(label_loc.count(), 5)):
            lbl = label_loc.nth(i)
            for xp in xpath_candidates:
                try:
                    cb = lbl.locator(xp).first
                    if cb.count() and cb.is_visible(timeout=500):
                        if not cb.is_checked():
                            cb.check(timeout=2000)
                        log(f"已勾选 {label} 前的复选框（XPath）")
                        return True
                except Exception:
                    continue

        # JS 兜底：在 label 所在行/父级中找 checkbox 并勾选
        checked = page.evaluate(f"""() => {{
            const text = "{label}";
            const labels = [...document.querySelectorAll('label, span, div')]
                .filter(l => l.innerText && l.innerText.trim().includes(text));
            for (const l of labels) {{
                const prev = l.previousElementSibling;
                if (prev && prev.tagName === 'INPUT' && prev.type === 'checkbox') {{
                    if (!prev.checked) prev.click(); return true;
                }}
                let el = l;
                for (let d = 0; d < 3; d++) {{
                    el = el.parentElement;
                    if (!el) break;
                    const cb = el.querySelector('input[type=checkbox]');
                    if (cb) {{ if (!cb.checked) cb.click(); return true; }}
                }}
            }}
            return false;
        }}""")
        if checked:
            log(f"已通过 JS 勾选 {label} 前的复选框")
            return True
        log(f"未能勾选 {label} 前的复选框")
        return False
    except Exception as exc:
        log(f"check_checkbox_by_label 异常：{exc}")
        return False


def click_status_select_all11(page) -> None:
    """点击 Status 字段，并在展开的多选面板中点击 Select All（大小写容错）。"""
    log("点击 Status 字段...")
    if not click_by_text_or_selector(page, "Status", selectors=[
        "label:has-text('Status')",
        "span:has-text('Status')",
        "div:has-text('Status')",
        "[title='Status']",
        "[aria-label='Status']",
    ]):
        log("未找到 Status 字段，尝试直接定位多选控件")
    page.wait_for_timeout(1500)
    safe_screenshot(page, "status_panel")

    targets = [
        STATUS_SELECT_ALL_TEXT,          # "Select All"
        STATUS_SELECT_ALL_TEXT.upper(),  # "SELECT ALL"
        STATUS_SELECT_ALL_TEXT.lower(),  # "select all"
        "select ALL",                    # 用户原文写法
    ]
    ok = False
    for t in targets:
        if click_by_text_or_selector(page, t, selectors=[
            f"a:has-text('{t}')",
            f"span:has-text('{t}')",
            f"li:has-text('{t}')",
            f"label:has-text('{t}')",
            f"[title='{t}']",
        ]):
            log(f"已点击 {t}")
            ok = True
            break

    if not ok:
        log("未找到 Select All 文本，尝试勾选面板内所有复选框（JS 兜底）")
        page.evaluate("""() => {
            const boxes = document.querySelectorAll('input[type=checkbox]');
            boxes.forEach(b => { if (!b.checked) { try { b.click(); } catch(e){} } });
            return true;
        }""")
    page.wait_for_timeout(1000)

def click_status_select_all(page) -> None:
    """定位并点击 Status 字段右侧的输入框，并在展开的多选面板中点击 Select All。"""
    log("尝试定位并点击 Status 右侧的下拉输入框...")
    
    clicked_input = False
    
    # 方案 1: 使用 XPath 相对定位查找 Status 标签同级或父级下的 input
    try:
        # 查找包含 Status 文本的 label 或 span
        label_loc = page.locator("label:has-text('Status'), span:has-text('Status')")
        if label_loc.count() > 0:
            for i in range(label_loc.count()):
                lbl = label_loc.nth(i)
                # 尝试点击同级后面的 input，或向上一级找 input，或找带有 select 类名的容器
                for xpath in [
                    "xpath=./following-sibling::*//input",
                    "xpath=..//input",
                    "xpath=../..//input",
                    "xpath=./following-sibling::*[contains(@class, 'select')]",
                    "xpath=..//*[contains(@class, 'select')]"
                ]:
                    try:
                        target = lbl.locator(xpath).first
                        if target.count() > 0 and target.is_visible(timeout=500):
                            target.click(timeout=2000)
                            log(f"已点击 Status 对应的输入框 (定位方式: {xpath})")
                            clicked_input = True
                            break
                    except Exception:
                        continue
                if clicked_input:
                    break
    except Exception as e:
        log(f"XPath定位下拉框异常：{e}")

    # 方案 2: JS 兜底定位 - 向上遍历父节点并查找输入框
    if not clicked_input:
        try:
            clicked_input = page.evaluate("""() => {
                const els = [...document.querySelectorAll('label, span')].filter(e => e.innerText && e.innerText.trim() === 'Status');
                for (const el of els) {
                    let p = el.parentElement;
                    // 向上找 4 层父级
                    for (let i = 0; i < 4; i++) {
                        if (!p) break;
                        const input = p.querySelector('input');
                        if (input && input.offsetHeight > 0) {
                            input.click();
                            return true;
                        }
                        // 兼容某些用 div 模拟的 select 组件
                        const selectDiv = p.querySelector('[class*="select"], [class*="dropdown"]');
                        if (selectDiv && selectDiv.offsetHeight > 0) {
                            selectDiv.click();
                            return true;
                        }
                        p = p.parentElement;
                    }
                }
                return false;
            }""")
            if clicked_input:
                log("已通过 JS 找到并点击 Status 对应的下拉输入框")
        except Exception as e:
            log(f"JS 定位下拉框异常：{e}")

    # 如果实在找不到输入框，只能回退点文本
    if not clicked_input:
        log("未精确找到输入框容器，回退到点击 Status 文本本身...")
        click_by_text_or_selector(page, "Status", selectors=["label:has-text('Status')"])

    # ---- 确保下拉面板展开：点击下拉箭头 / 触发器 ----
    page.wait_for_timeout(500)
    try:
        trigger_clicked = page.evaluate("""() => {
            const labels = [...document.querySelectorAll('label, span, td, th, div')]
                .filter(e => (e.innerText || e.textContent || '').trim() === 'Status' && e.children.length === 0);
            for (const lbl of labels) {
                let p = lbl.parentElement;
                for (let i = 0; i < 6; i++) {
                    if (!p) break;
                    // 查找箭头 / 后缀图标等可点击的触发元素
                    const icons = p.querySelectorAll('i, svg, [class*="arrow"], [class*="suffix"], [class*="caret"], [class*="trigger"], [class*="expand"]');
                    for (const ic of icons) {
                        if (ic.offsetHeight > 0 && ic.offsetWidth > 0) {
                            ic.click();
                            return true;
                        }
                    }
                    // 如果父元素本身是 select 组件容器，也尝试点击
                    const cls = (p.className || '').toString().toLowerCase();
                    if (cls.includes('select') && !cls.includes('selected')) {
                        p.click();
                        return true;
                    }
                    p = p.parentElement;
                }
            }
            return false;
        }""")
        if trigger_clicked:
            log("已点击 Status 下拉箭头/触发器以展开面板")
    except Exception as e:
        log(f"点击下拉箭头异常：{e}")

    # 键盘兜底：聚焦输入框后按方向键展开下拉
    try:
        page.keyboard.press("ArrowDown")
    except Exception:
        pass

    page.wait_for_timeout(1500)
    safe_screenshot(page, "status_panel")

    # ========= 下拉框已展开，接下来寻找 Select All 并点击 =========
    
    log("尝试点击 Select All...")
    targets = [
        STATUS_SELECT_ALL_TEXT,          # "Select All"
        STATUS_SELECT_ALL_TEXT.upper(),  # "SELECT ALL"
        STATUS_SELECT_ALL_TEXT.lower(),  # "select all"
        "select ALL",                    # 用户原文写法
    ]
    ok = False
    for t in targets:
        if click_by_text_or_selector(page, t, selectors=[
            f"a:has-text('{t}')",
            f"span:has-text('{t}')",
            f"li:has-text('{t}')",
            f"label:has-text('{t}')",
            f"[title='{t}']",
            f"div[class*='option']:has-text('{t}')"
        ]):
            log(f"已点击 {t}")
            ok = True
            break

    # JS 兜底：如果没找到 Select All 文字，则尝试勾选下拉面板里的所有复选框
    if not ok:
        log("未找到 Select All 文本，尝试勾选面板内所有复选框（JS 兜底）")
        page.evaluate("""() => {
            // 优先只在弹出的下拉面板 (dropdown) 中找复选框，防止勾选到背景页面上的其他内容
            let boxes = document.querySelectorAll('[class*="dropdown"] input[type=checkbox], [class*="select-panel"] input[type=checkbox]');
            if (boxes.length === 0) {
                // 如果没找到下拉面板的特征类名，则查找所有可见的 checkbox
                boxes = [...document.querySelectorAll('input[type=checkbox]')].filter(b => b.offsetHeight > 0);
            }
            boxes.forEach(b => { 
                if (!b.checked) { 
                    try { b.click(); } catch(e){} 
                } 
            });
            return true;
        }""")
    page.wait_for_timeout(1000)
def click_export_dropdown(ctx, menu_item: str, page=None, extra_ctx=None) -> bool:
    """点击 Export 下拉按钮，然后点击下拉菜单项。

    ctx: 操作上下文（Frame 或 Page，用于 evaluate/locator 查找元素）
    page: 真正的 Page 对象（用于 mouse.click 坐标点击）
    extra_ctx: 额外的上下文（用于查找下拉菜单项）
    """
    if page is None:
        page = ctx  # 如果 ctx 本身就是 Page
    log(f"尝试点击 Export -> {menu_item}...")
    # 收集所有需要搜索菜单项的上下文
    search_contexts = [ctx]
    if extra_ctx is not None and extra_ctx is not ctx:
        search_contexts.append(extra_ctx)

    # ---- 点击 Export 按钮 ----
    clicked = False

    # 方案 A: 获取 Export 按钮坐标，用 page.mouse.click 真实点击
    try:
        box = ctx.evaluate("""() => {
            const all = [...document.querySelectorAll('button, a, [role="button"], [class*="btn"]')];
            const exportEls = all.filter(el => {
                const t = (el.innerText || el.textContent || '').trim();
                return (t === 'Export' || t.match(/^Export\\s*$/)) && el.offsetHeight > 0 && el.offsetWidth > 0;
            });
            if (exportEls.length > 0) {
                const rect = exportEls[0].getBoundingClientRect();
                return {x: rect.x, y: rect.y, w: rect.width, h: rect.height};
            }
            return null;
        }""")
        if box:
            # 如果 ctx 是 frame，需要加上 iframe 偏移
            offset = _get_iframe_offset(page, ctx)
            # 点击按钮右侧 85% 处（下拉箭头区域）
            abs_x = offset['x'] + box['x'] + box['w'] * 0.85
            abs_y = offset['y'] + box['y'] + box['h'] / 2
            page.mouse.click(abs_x, abs_y)
            clicked = True
            log(f"已通过 page.mouse.click 点击 Export 按钮 ({abs_x:.0f}, {abs_y:.0f})")
    except Exception as e:
        log(f"坐标点击 Export 异常：{e}")

    # 方案 B: JS dispatchEvent 兜底
    if not clicked:
        try:
            clicked = ctx.evaluate("""() => {
                const all = [...document.querySelectorAll('button, a, [role="button"], [class*="btn"], [class*="dropdown"]')];
                const exportEls = all.filter(el => {
                    const t = (el.innerText || el.textContent || '').trim();
                    return (t === 'Export' || t.match(/^Export\\s*$/)) && el.offsetHeight > 0 && el.offsetWidth > 0;
                });
                for (const el of exportEls) {
                    const rect = el.getBoundingClientRect();
                    const clickX = rect.right - 10;
                    const clickY = rect.top + rect.height / 2;
                    el.dispatchEvent(new MouseEvent('click', {
                        bubbles: true, cancelable: true, view: window,
                        clientX: clickX, clientY: clickY
                    }));
                    return 'js_dispatch';
                }
                return false;
            }""")
            if clicked:
                log(f"已通过 JS dispatch 点击 Export 按钮")
        except Exception as e:
            log(f"JS 点击 Export 异常：{e}")

    if not clicked:
        log("未能点击 Export 按钮")
        return False

    # ---- 等待并点击菜单项（最多重试 2 次） ----
    for attempt in range(2):
        page.wait_for_timeout(1500)

        # 在所有上下文中查找并点击菜单项
        for search_ctx in search_contexts:
            # 先用 Playwright locator + force click
            for sel in [
                f"button:has-text('{menu_item}')",
                f"li:has-text('{menu_item}')",
                f"a:has-text('{menu_item}')",
                f"span:has-text('{menu_item}')",
                f"[class*='dropdown-item']:has-text('{menu_item}')",
                f"[class*='dropdown'] :has-text('{menu_item}')",
            ]:
                try:
                    loc = search_ctx.locator(sel).first
                    if loc.count() > 0 and loc.is_visible(timeout=1000):
                        loc.click(timeout=2000)
                        log(f"已通过选择器点击菜单项：{sel}")
                        return True
                except Exception:
                    continue

            # 用坐标点击菜单项
            try:
                menu_box = search_ctx.evaluate(f"""() => {{
                    const all = [...document.querySelectorAll('button, a, li, span, div')];
                    const target = all.find(el => {{
                        const t = (el.innerText || el.textContent || '').trim();
                        return t === '{menu_item}' && el.offsetHeight > 0 && el.offsetWidth > 0;
                    }});
                    if (target) {{
                        const rect = target.getBoundingClientRect();
                        return {{x: rect.x + rect.width / 2, y: rect.y + rect.height / 2}};
                    }}
                    return null;
                }}""")
                if menu_box:
                    offset = _get_iframe_offset(page, search_ctx)
                    abs_x = offset['x'] + menu_box['x']
                    abs_y = offset['y'] + menu_box['y']
                    page.mouse.click(abs_x, abs_y)
                    log(f"已通过坐标点击菜单项 '{menu_item}' ({abs_x:.0f}, {abs_y:.0f})")
                    return True
            except Exception:
                pass

            # JS click 兜底
            try:
                js_clicked = search_ctx.evaluate(f"""() => {{
                    const all = [...document.querySelectorAll('button, a, li, span, div')];
                    const target = all.find(el => {{
                        const t = (el.innerText || el.textContent || '').trim();
                        return t === '{menu_item}' && el.offsetHeight > 0 && el.offsetWidth > 0;
                    }});
                    if (target) {{ target.click(); return true; }}
                    return false;
                }}""")
                if js_clicked:
                    log(f"已通过 JS click 点击菜单项 '{menu_item}'")
                    return True
            except Exception:
                pass

        # 菜单项没找到，重试点击 Export
        if attempt == 0:
            log("菜单项未出现，重试点击 Export...")
            try:
                box2 = ctx.evaluate("""() => {
                    const all = [...document.querySelectorAll('button, a, [role="button"]')];
                    const el = all.find(e => (e.innerText || '').trim() === 'Export' && e.offsetHeight > 0);
                    if (el) {
                        const rect = el.getBoundingClientRect();
                        return {x: rect.x, y: rect.y, w: rect.width, h: rect.height};
                    }
                    return null;
                }""")
                if box2:
                    offset = _get_iframe_offset(page, ctx)
                    page.mouse.click(offset['x'] + box2['x'] + box2['w'] * 0.85, offset['y'] + box2['y'] + box2['h'] / 2)
            except Exception:
                pass

    log(f"未能在下拉菜单中找到 '{menu_item}'")
    return False


def _get_iframe_offset(page, ctx) -> dict:
    """如果 ctx 是 iframe 内的 Frame，返回该 iframe 在 page 中的精确偏移量；否则返回 {0,0}。

    使用 ctx.frame_element().bounding_box() 取得 *该 frame 对应* 的 iframe 矩形，
    避免页面存在多个 iframe 时取错对象导致坐标点偏。
    """
    if ctx is page:
        return {'x': 0, 'y': 0}
    # 精确方案：该 frame 对应的 iframe 元素在 page 坐标系下的矩形
    try:
        el = ctx.frame_element()
        box = el.bounding_box()
        if box:
            return {'x': box['x'], 'y': box['y']}
    except Exception:
        pass
    # 兜底：旧逻辑（仅在 frame_element 不可用时）
    try:
        return page.evaluate("""() => {
            const iframes = document.querySelectorAll('iframe');
            for (const iframe of iframes) {
                const rect = iframe.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    return {x: rect.x, y: rect.y};
                }
            }
            return {x: 0, y: 0};
        }""")
    except Exception:
        return {'x': 0, 'y': 0}


def download_export(page, context, export_info: dict) -> None:
    """使用已获取的 fileName / ftpFilePath 通过 requests 下载 zip。"""
    file_name = export_info.get("fileName")
    ftp_path = export_info.get("ftpFilePath")
    table_type = export_info.get("tableType", "eflow-tt")
    if not file_name or not ftp_path:
        log("导出信息不完整，跳过下载")
        return

    url = f"https://10.100.20.8:28001/api/eflow-ticket/v1/attachment/download/{table_type}"
    payload = {
        "fileName": file_name,
        "ftpFilePath": ftp_path,
        "tableType": table_type,
    }

    # 从浏览器上下文获取 cookies
    cookies = {c["name"]: c["value"] for c in context.cookies()}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://10.100.20.8:28001/iui/ticket-mgt/v1/",
    }

    log(f"开始下载：{file_name}")
    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            cookies=cookies,
            verify=False,
            timeout=120,
        )
        resp.raise_for_status()
        output_path = OUTPUT_DIR / file_name
        output_path.write_bytes(resp.content)
        log(f"下载完成，保存到：{output_path} ({len(resp.content)} bytes)")
    except Exception as exc:
        log(f"下载失败：{exc}")


def click_my_export_download(page, context) -> None:
    """兜底：点击 My Export 列表中的第一个 Download。"""
    # 等待列表中至少有一行
    try:
        page.wait_for_selector("text=Success", timeout=30000)
    except PlaywrightTimeout:
        log("等待导出成功超时")
        return

    # 拦截 Download 请求
    download_request_info = {}

    def handle_download_request(request):
        if "/api/eflow-ticket/v1/attachment/download/eflow-tt" in request.url and request.method == "POST":
            download_request_info["url"] = request.url
            download_request_info["body"] = request.post_data
            log(f"捕获下载请求：{request.url}")

    page.on("request", handle_download_request)

    # 点击第一个 Download
    if not safe_click_by_text(page, "Download", exact=False):
        # 兜底：点击第一个 Operation 列中的链接
        try:
            page.locator("a:has-text('Download')").first.click(timeout=5000)
        except Exception as exc:
            log(f"点击 Download 失败：{exc}")
            return

    page.wait_for_timeout(5000)

    if download_request_info.get("url") and download_request_info.get("body"):
        try:
            body = json.loads(download_request_info["body"])
            download_export(page, context, body)
        except Exception as exc:
            log(f"解析下载请求体失败：{exc}")
    else:
        log("未捕获到下载请求，无法自动下载")


def _wait_for_new_file(directory: Path, before_files: set, timeout_sec: int = 120) -> Path | None:
    """等待 directory 中出现 before_files 之外的新文件（排除 .crdownload 等临时文件）。"""
    import time
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        current = set()
        for f in directory.iterdir():
            if f.is_file() and not f.name.endswith((".crdownload", ".tmp", ".part")):
                current.add(f)
        new_files = current - before_files
        if new_files:
            # 取最新的文件
            newest = max(new_files, key=lambda p: p.stat().st_mtime)
            return newest
        time.sleep(1)
    return None


def wait_my_export_and_download(frame, page, context, download_request_info: dict, max_attempts: int = 60, interval: int = 5, table_type: str = "eflow-tt") -> None:
    """在 My Export 弹窗中：每隔 interval 秒点击刷新按钮，
    等待第一行（本次导出任务）的 Progress 变为 100% / Status 变为 Success，
    然后点击第一行的 Download。

    通过 page.on("download") 捕获下载并 save_as 到 OUTPUT_DIR。
    """
    log("等待 My Export 列表加载...")

    # 探测弹窗所在上下文：用刷新按钮 class / 表头组合 / 提示文本（避免误匹配下拉菜单项 "My Export"）
    dialog_ctx = None
    PROBE_DIALOG_JS = """() => {
        const vis = e => { const r=e.getBoundingClientRect(); return r.width>0 && r.height>0; };
        const hasRefresh = !![...document.querySelectorAll('button.plx-ico-refresh-16, [class*="plx-ico-refresh"], button.plx-icon-btn')].find(vis);
        const heads = [...document.querySelectorAll('th,div,span')].map(e=>(e.innerText||'').trim());
        const hasTable = heads.includes('File Name') && heads.includes('Progress') && heads.includes('Operation');
        const hasTip = [...document.querySelectorAll('div,span,p')].some(e=>(e.innerText||'').trim().startsWith('Offline export') && vis(e) && e.children.length<=2);
        return hasRefresh || hasTable || hasTip;
    }"""
    for ctx_name, ctx in [("frame", frame), ("page", page)]:
        try:
            if ctx.evaluate(PROBE_DIALOG_JS):
                dialog_ctx = ctx
                log(f"My Export 弹窗在 {ctx_name} 中")
                break
        except Exception:
            continue
    if dialog_ctx is None:
        log("未探测到弹窗特征，默认使用 frame")
        dialog_ctx = frame
    dialog_ctx.wait_for_timeout(1500)

    # 拦截 My Export 列表的 API 请求，用于后续重放刷新
    captured_api_requests = []
    EXPORT_API_PATTERN = "**/api/eflow-ticket/**/offlineExport/query**"

    def capture_export_api(route):
        """拦截导出列表 API 请求，记录信息并继续正常请求。"""
        request = route.request
        captured_api_requests.append({
            'url': request.url,
            'method': request.method,
            'headers': dict(request.headers) if request.headers else {},
            'post_data': request.post_data,
        })
        log(f"  [API拦截] {request.method} {request.url}")
        route.continue_()

    # 全量网络请求日志（诊断用：确认点击后是否有任何网络活动）
    _all_requests_log = []
    def _log_all_requests(request):
        if request.resource_type in ('xhr', 'fetch'):
            _all_requests_log.append({'url': request.url, 'method': request.method, 'ts': time.time()})
    page.on("request", _log_all_requests)

    try:
        page.route(EXPORT_API_PATTERN, capture_export_api)
        log("  [API拦截] 已设置 route 拦截: offlineExport/query")
    except Exception as e:
        log(f"  [API拦截] route 设置失败：{e}")

    # 种子请求：route 是在弹窗打开后才设置的，首次加载的请求未被捕获。
    # 主动发一次查询请求，确保 captured_api_requests 非空，API 兜底检查可用。
    try:
        dialog_ctx.evaluate("""async () => {
            try {
                await fetch('/api/eflow-ticket/v1/export/offlineExport/query', {
                    method: 'POST', credentials: 'include',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({})
                });
            } catch(e) {}
        }""")
        page.wait_for_timeout(1500)
        log(f"  [API拦截] 种子请求后已捕获 {len(captured_api_requests)} 个请求")
    except Exception as e:
        log(f"  [API拦截] 种子请求异常：{e}")

    page.wait_for_timeout(2000)

    # JS：以第一个 Download 链接锚定第一行，读取该行 Status / Progress
    READ_FIRST_ROW_JS = """() => {
        const dls = [...document.querySelectorAll('a,button,span')].filter(e=>/^\\s*download\\s*$/i.test((e.innerText||'').trim()));
        if(!dls.length) return null;
        const firstDl = dls[0];
        let row = firstDl.closest('tr') || firstDl.closest('[class*="row"]') || firstDl.parentElement;
        const rowText = (row?row.innerText:firstDl.innerText)||'';
        const pm = rowText.match(/(\\d+)\\s*%/);
        const progress = pm?parseInt(pm[1]):-1;
        const sm = rowText.match(/(Processing|Success|Failed|Completed|Running)/i);
        const status = sm?sm[1]:'';
        const ready = (progress===100) || /success|completed/i.test(status);
        const r = firstDl.getBoundingClientRect();
        const dlBox = (r.width>0 && r.height>0)?{x:r.x+r.width/2,y:r.y+r.height/2}:null;
        return {status, progress, ready, dlBox, snippet: rowText.replace(/\\s+/g,' ').slice(0,90)};
    }"""

    # JS：获取刷新按钮坐标并直接触发点击（图标按钮，无可见文本）
    REFRESH_BTN_JS = """() => {
        const vis = e => { const r=e.getBoundingClientRect(); return r.width>0 && r.height>0; };
        const attr = (e,n)=> (e.getAttribute? (e.getAttribute(n)||'') : '');
        const all=[...document.querySelectorAll('button,a,i,svg,span,[role=button]')].filter(vis);
        let t=null, method='none';
        // 策略0：精确 class（plx 框架刷新图标按钮，无 title/文本）
        t = [...document.querySelectorAll('button.plx-ico-refresh-16, [class*="plx-ico-refresh"], button.plx-icon-btn')].find(vis);
        if(t) method='exact';
        // 策略1：title / aria-label
        if(!t){ t = all.find(e=>/refresh|reload|sync|redo|rotate|update/i.test(attr(e,'title')+' '+attr(e,'aria-label'))); if(t) method='attr'; }
        // 策略2：className
        if(!t){ t = all.find(e=>/refresh|reload|sync|redo|rotate|update/i.test((e.className||'').toString())); if(t) method='class'; }
        // 策略3：位置启发式 —— 表格上方右侧的无文字小图标按钮中 y 最大者
        if(!t){
            const ths=all.filter(e=>(e.innerText||'').trim()==='Progress');
            const tableTop = ths.length? Math.min(...ths.map(e=>e.getBoundingClientRect().top)) : null;
            const winW=window.innerWidth;
            let cands=all.filter(e=>{
                const r=e.getBoundingClientRect(); const cx=r.x+r.width/2, cy=r.y+r.height/2;
                const txt=(e.innerText||'').trim();
                return txt.length<=2 && cx>winW*0.7 && (tableTop? cy<tableTop : cy<200);
            });
            if(cands.length){ cands.sort((a,b)=>b.getBoundingClientRect().y - a.getBoundingClientRect().y); t=cands[0]; method='heuristic'; }
        }
        if(!t){
            const winW=window.innerWidth;
            const dump=all.map(e=>{const r=e.getBoundingClientRect();return {tag:e.tagName,cls:(e.className||'').toString().slice(0,40),title:attr(e,'title'),text:(e.innerText||'').trim().slice(0,10),cx:Math.round(r.x+r.width/2),cy:Math.round(r.y+r.height/2)};}).filter(o=>o.cx>winW*0.6 && o.cy<300).slice(0,20);
            return {box:null,method:'none',dump:dump};
        }
        let target=t;
        if(t.tagName==='I'||t.tagName==='SVG'){ const b=t.closest('button,a,[role=button]'); if(b&&vis(b)) target=b; }
        const fire=el=>{ const r=el.getBoundingClientRect(); const x=r.x+r.width/2,y=r.y+r.height/2; ['mousedown','mouseup','click'].forEach(ev=>el.dispatchEvent(new MouseEvent(ev,{bubbles:true,cancelable:true,view:window,clientX:x,clientY:y}))); try{el.click();}catch(e){} };
        fire(target); if(target!==t) fire(t);
        const r=target.getBoundingClientRect();
        return {box:{x:r.x+r.width/2,y:r.y+r.height/2},method:method};
    }"""

    captured_downloads = []

    def on_download(download):
        log(f"捕获到下载事件：{download.suggested_filename}")
        captured_downloads.append(download)

    page.on("download", on_download)

    def _read_first_row():
        for ctx in [dialog_ctx, page, frame]:
            try:
                info = ctx.evaluate(READ_FIRST_ROW_JS)
                if info:
                    return ctx, info
            except Exception:
                continue
        return None, None

    def _click_first_download():
        # 方案1：locator.click 第一个可见的 Download（Playwright 自动处理 iframe）
        for c in [dialog_ctx, frame, page]:
            try:
                loc = c.get_by_text("Download", exact=True)
                cnt = loc.count()
                for i in range(cnt):
                    nth = loc.nth(i)
                    try:
                        if nth.is_visible(timeout=500):
                            nth.click(timeout=2000)
                            log("已通过 locator 点击第一行 Download")
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
        # 方案2：坐标点击兜底（offset 已用 frame_element 精确计算）
        ctx, info = _read_first_row()
        if ctx and info and info.get('dlBox'):
            offset = _get_iframe_offset(page, ctx)
            bx = offset['x'] + info['dlBox']['x']
            by = offset['y'] + info['dlBox']['y']
            page.mouse.click(bx, by)
            log(f"已通过坐标点击第一行 Download ({bx:.0f},{by:.0f})")
            return True
        return False

    # JS：获取刷新按钮的精确视口坐标（用于 CDP 底层点击）
    REFRESH_BOX_JS = """() => {
        const btn = document.querySelector('button.plx-ico-refresh-16, [class*="plx-ico-refresh"]');
        if (!btn) return null;
        const r = btn.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return null;
        return {x: r.x + r.width/2, y: r.y + r.height/2, w: r.width, h: r.height};
    }"""

    def _cdp_click(x, y):
        """通过 CDP Input.dispatchMouseEvent 注入操作系统级鼠标事件。"""
        cdp = page.context.new_cdp_session(page)
        try:
            cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseMoved", "x": x, "y": y
            })
            cdp.send("Input.dispatchMouseEvent", {
                "type": "mousePressed", "x": x, "y": y,
                "button": "left", "clickCount": 1
            })
            cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseReleased", "x": x, "y": y,
                "button": "left", "clickCount": 1
            })
        finally:
            cdp.detach()

    def _cdp_find_and_trigger_click():
        """通过 CDP DOM.getEventListenersForNode 查找刷新按钮及其祖先的 click 事件监听器，
        找到后通过 Runtime.callFunctionOn 触发。解决 Angular Ivy 内部事件绑定问题。"""
        cdp = page.context.new_cdp_session(page)
        try:
            # 在 dialog_ctx 中找到按钮的 DOM nodeId
            result = cdp.send("DOM.getDocument", {"depth": -1})
            root_id = result["root"]["nodeId"]

            # 用 CSS 选择器找到按钮
            search_result = cdp.send("DOM.querySelectorAll", {
                "nodeId": root_id,
                "selector": "button.plx-ico-refresh-16"
            })
            node_ids = search_result.get("nodeIds", [])
            if not node_ids:
                log("  [CDP查询] 未找到 button.plx-ico-refresh-16")
                return False

            log(f"  [CDP查询] 找到 {len(node_ids)} 个刷新按钮节点")

            for btn_id in node_ids:
                # 遍历按钮及其祖先，查找 click 事件监听器
                current_id = btn_id
                depth = 0
                while current_id and depth < 15:
                    try:
                        listeners = cdp.send("DOM.getEventListenersForNode", {
                            "objectId": None,
                            "nodeId": current_id,
                            "depth": 0
                        })
                        click_listeners = [
                            l for l in listeners.get("listeners", [])
                            if l.get("type") == "click"
                        ]
                        if click_listeners:
                            log(f"  [CDP查询] 祖先深度={depth} 找到 {len(click_listeners)} 个 click 监听器")
                            # 获取节点的 remote object 并触发 click
                            node_obj = cdp.send("DOM.resolveNode", {"nodeId": current_id})
                            obj_id = node_obj["object"]["objectId"]
                            cdp.send("Runtime.callFunctionOn", {
                                "objectId": obj_id,
                                "functionDeclaration": """function() {
                                    const r = this.getBoundingClientRect();
                                    const ev = new MouseEvent('click', {
                                        bubbles: true, cancelable: true, view: window,
                                        clientX: r.x + r.width/2, clientY: r.y + r.height/2
                                    });
                                    this.dispatchEvent(ev);
                                    return true;
                                }"""
                            })
                            log(f"  [CDP查询] 已在祖先节点(深度={depth})触发 click")
                            return True
                    except Exception:
                        pass

                    # 获取父节点
                    try:
                        parent_result = cdp.send("DOM.describeNode", {"nodeId": current_id})
                        parent_id = parent_result.get("node", {}).get("parentId")
                        if not parent_id or parent_id == current_id:
                            break
                        current_id = parent_id
                        depth += 1
                    except Exception:
                        break

            # 最后尝试：通过 Angular 内部机制触发
            log("  [CDP查询] 未找到 DOM click 监听器，尝试 Angular 内部触发...")
            result = cdp.send("Runtime.evaluate", {
                "expression": """(() => {
                    const btn = document.querySelector('button.plx-ico-refresh-16');
                    if (!btn) return 'no_btn';
                    // Angular Ivy: __ngContext__ 存储组件上下文
                    const keys = Object.keys(btn);
                    const ctxKey = keys.find(k => k.startsWith('__ngContext__') || k.startsWith('__ng'));
                    if (ctxKey) {
                        const ctx = btn[ctxKey];
                        if (Array.isArray(ctx)) {
                            // LView 数组，尝试找组件实例
                            for (let i = ctx.length - 1; i >= 0; i--) {
                                const node = ctx[i];
                                if (node && typeof node === 'object' && typeof node.refresh === 'function') {
                                    node.refresh();
                                    return 'angular_refresh';
                                }
                                if (node && typeof node === 'object' && typeof node.loadExports === 'function') {
                                    node.loadExports();
                                    return 'angular_loadExports';
                                }
                            }
                        }
                    }
                    // Angular: 找包含该按钮的组件并触发变更检测
                    const ngKeys = Object.keys(btn);
                    for (const k of ngKeys) {
                        if (k.startsWith('__ng')) {
                            return 'ng_key_found:' + k + ':' + typeof btn[k];
                        }
                    }
                    return 'no_ng_ctx';
                })()""",
                "returnByValue": True
            })
            angular_result = result.get("result", {}).get("value", "unknown")
            log(f"  [Angular检测] 结果: {angular_result}")
            return False
        except Exception as e:
            log(f"  CDP查询异常：{e}")
            return False
        finally:
            cdp.detach()

    def _reopen_export_dialog():
        """关闭并重新打开 My Export 弹窗，强制 Angular 重新加载数据。"""
        log("  [重新打开弹窗] 尝试关闭当前弹窗...")

        # 先尝试点击弹窗上的关闭按钮 (X)
        CLOSE_SELECTORS = [
            'button[class*="close"]',
            'button[class*="ico-close"]',
            '[class*="plx-ico-close"]',
            'button[aria-label="Close"]',
            'button[title*="lose"]',
            '.plx-dialog-close',
        ]
        for ctx in [dialog_ctx, frame, page]:
            for sel in CLOSE_SELECTORS:
                try:
                    loc = ctx.locator(sel).first
                    if loc.count() > 0 and loc.is_visible(timeout=500):
                        loc.click(timeout=2000)
                        log(f"  [重新打开弹窗] 已点击关闭按钮 '{sel}'")
                        page.wait_for_timeout(1500)
                        break
                except Exception:
                    continue

        # 检查弹窗是否已关闭
        try:
            cnt = dialog_ctx.locator('button.plx-ico-refresh-16').count()
            if cnt == 0:
                log("  [重新打开弹窗] 弹窗已关闭")
            else:
                # 尝试 Escape
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
        except Exception:
            pass

        # 重新打开 My Export 弹窗
        log("  [重新打开弹窗] 尝试重新打开 My Export...")
        MY_EXPORT_SELECTORS = [
            'text="My Export"',
            'a:has-text("My Export")',
            'button:has-text("My Export")',
            'span:has-text("My Export")',
        ]
        for ctx in [frame, page]:
            for sel in MY_EXPORT_SELECTORS:
                try:
                    loc = ctx.locator(sel).first
                    if loc.count() > 0 and loc.is_visible(timeout=1000):
                        loc.click(timeout=3000)
                        log(f"  [重新打开弹窗] 已点击 '{sel}'")
                        page.wait_for_timeout(3000)
                        # 确认弹窗已重新打开
                        for check_ctx in [dialog_ctx, frame, page]:
                            try:
                                cnt = check_ctx.locator('button.plx-ico-refresh-16').count()
                                if cnt > 0:
                                    log("  [重新打开弹窗] 弹窗已重新打开")
                                    return True
                            except Exception:
                                continue
                except Exception:
                    continue
        log("  [重新打开弹窗] 未能重新打开弹窗")
        return False

    # JS：精确定位 My Export 弹窗内的刷新按钮并打上唯一标记
    # 页面上有 38+ 个 plx-icon-btn，核心策略：
    #   以 Download 链接为锚点向上遍历，找「同时包含该锚点和刷新按钮的最小容器」
    #   → 这个容器只可能是弹窗本身，其中的刷新按钮必然是弹窗的
    MARK_DIALOG_REFRESH_JS = """() => {
        // 清除旧标记
        document.querySelectorAll('[data-rpa-refresh]').forEach(e => e.removeAttribute('data-rpa-refresh'));

        const isVisible = el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        };

        // 步骤1：找 Download 链接锚点（与 READ_FIRST_ROW_JS 相同，已验证可靠）
        const dls = [...document.querySelectorAll('a,button,span')].filter(e =>
            /^\\s*download\\s*$/i.test((e.innerText || '').trim()) && isVisible(e));
        let anchorEl = null;
        if (dls.length > 0) {
            anchorEl = dls[0].closest('tr') || dls[0].closest('[class*="row"]') || dls[0].parentElement;
        }
        // 备选锚点："File Name" 表头
        if (!anchorEl) {
            const fnHeaders = [...document.querySelectorAll('th,td,div,span')].filter(e => {
                const t = (e.innerText || '').trim();
                return (t === 'File Name' || t === 'FileName') && isVisible(e);
            });
            if (fnHeaders.length > 0) {
                fnHeaders.sort((a, b) => {
                    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
                    return (ra.width * ra.height) - (rb.width * rb.height);
                });
                anchorEl = fnHeaders[0].closest('table') || fnHeaders[0].parentElement;
            }
        }
        if (!anchorEl) return {found: false, reason: 'no_anchor_no_download_link'};

        // 步骤2：向上找「同时包含锚点 + 刷新按钮」的最小容器 = 弹窗容器
        let el = anchorEl;
        for (let depth = 0; depth < 30 && el; depth++) {
            const btns = [...el.querySelectorAll('button.plx-ico-refresh-16')].filter(isVisible);
            if (btns.length > 0 && el.contains(anchorEl)) {
                // 选离锚点最近的（通常只有1个）
                const aRect = anchorEl.getBoundingClientRect();
                const aCx = aRect.x + aRect.width/2, aCy = aRect.y + aRect.height/2;
                let best = btns[0], bestD = Infinity;
                for (const b of btns) {
                    const r = b.getBoundingClientRect();
                    const d = Math.hypot(r.x + r.width/2 - aCx, r.y + r.height/2 - aCy);
                    if (d < bestD) { bestD = d; best = b; }
                }
                best.setAttribute('data-rpa-refresh', '1');
                const br = best.getBoundingClientRect();
                return {found: true, strategy: 'dialog_container', depth,
                        btnsInContainer: btns.length, dist: Math.round(bestD),
                        disabled: best.disabled || best.getAttribute('aria-disabled') === 'true',
                        btn: {x: Math.round(br.x), y: Math.round(br.y), w: Math.round(br.width), h: Math.round(br.height)}};
            }
            el = el.parentElement;
        }

        // 步骤3 兆底：取最后一个可见刷新按钮（弹窗通常追加在 DOM 末尾）
        const allBtns = [...document.querySelectorAll('button.plx-ico-refresh-16')].filter(isVisible);
        if (allBtns.length === 0) return {found: false, reason: 'no_visible_refresh_btn'};
        const last = allBtns[allBtns.length - 1];
        last.setAttribute('data-rpa-refresh', '1');
        const lr = last.getBoundingClientRect();
        return {found: true, strategy: 'last_in_dom', btnCount: allBtns.length,
                disabled: last.disabled,
                btn: {x: Math.round(lr.x), y: Math.round(lr.y), w: Math.round(lr.width), h: Math.round(lr.height)}};
    }"""

    def _cdp_invoke_listener():
        """通过 CDP DOMDebugger.getEventListeners 找到按钮的 click 监听器并直接调用。
        完全绕过事件派发机制（dispatchEvent/mouse.click 全部无效时的终极方案）。"""
        cdp = page.context.new_cdp_session(page)
        try:
            # 在主页面上下文中遍历所有同源 iframe，找到标记的按钮并返回 RemoteObject
            eval_result = cdp.send("Runtime.evaluate", {
                "expression": """(() => {
                    const docs = [document];
                    const collect = (doc) => {
                        try {
                            const frames = doc.querySelectorAll('iframe, frame');
                            for (const f of frames) {
                                if (f.contentDocument) { docs.push(f.contentDocument); collect(f.contentDocument); }
                            }
                        } catch(e) {}
                    };
                    collect(document);
                    for (const d of docs) {
                        try {
                            const btn = d.querySelector('button[data-rpa-refresh="1"]');
                            if (btn) return btn;
                        } catch(e) {}
                    }
                    return null;
                })()""",
                "returnByValue": False
            })
            obj_id = eval_result.get("result", {}).get("objectId")
            if not obj_id:
                log("  [CDP监听器] 未找到标记的按钮元素")
                return False

            # 获取按钮及其祖先链的 click 监听器（Angular 可能委托绑定在祖先上）
            invoke_result = cdp.send("Runtime.callFunctionOn", {
                "objectId": obj_id,
                "functionDeclaration": """function() {
                    const btn = this;
                    const r = btn.getBoundingClientRect();
                    const x = r.x + r.width/2, y = r.y + r.height/2;
                    return {tag: btn.tagName, cls: (btn.className||'').slice(0,60), x: Math.round(x), y: Math.round(y)};
                }""",
                "returnByValue": True
            })
            btn_info = invoke_result.get("result", {}).get("value", {})

            # 用 DOMDebugger 获取按钮自身的监听器
            listeners_resp = cdp.send("DOMDebugger.getEventListeners", {
                "objectId": obj_id, "depth": 0, "pierce": True
            })
            all_listeners = listeners_resp.get("listeners", [])
            click_listeners = [l for l in all_listeners if l.get("type") == "click"]
            log(f"  [CDP监听器] 按钮 {btn_info.get('tag')}.{btn_info.get('cls','')} @({btn_info.get('x')},{btn_info.get('y')}) "
                f"监听器: 共{len(all_listeners)}个, click={len(click_listeners)}个")

            # 如果按钮自身没有 click 监听器，检查祖先链（最多10层）
            target_obj_id = obj_id
            if not click_listeners:
                ancestor_result = cdp.send("Runtime.callFunctionOn", {
                    "objectId": obj_id,
                    "functionDeclaration": """function() {
                        const chain = [];
                        let el = this.parentElement;
                        for (let i = 0; i < 10 && el; i++) { chain.push(el); el = el.parentElement; }
                        return chain;
                    }""",
                    "returnByValue": False
                })
                # callFunctionOn 返回数组时无法直接遍历，改用逐层查找
                for lvl in range(1, 11):
                    try:
                        ancestor_eval = cdp.send("Runtime.callFunctionOn", {
                            "objectId": obj_id,
                            "functionDeclaration": f"""function() {{
                                let el = this;
                                for (let i = 0; i < {lvl}; i++) {{ el = el ? el.parentElement : null; }}
                                return el;
                            }}""",
                            "returnByValue": False
                        })
                        anc_id = ancestor_eval.get("result", {}).get("objectId")
                        if not anc_id:
                            break
                        anc_listeners = cdp.send("DOMDebugger.getEventListeners", {
                            "objectId": anc_id, "depth": 0, "pierce": True
                        }).get("listeners", [])
                        anc_clicks = [l for l in anc_listeners if l.get("type") == "click"]
                        if anc_clicks:
                            click_listeners = anc_clicks
                            target_obj_id = anc_id
                            log(f"  [CDP监听器] 按钮自身无 click，在祖先第{lvl}层找到 {len(anc_clicks)} 个 click 监听器")
                            break
                    except Exception:
                        break

            if not click_listeners:
                log("  [CDP监听器] 按钮及祖先链均无 click 监听器（Angular 可能用全局事件委托）")
                return False

            # 直接调用 click 监听器函数（绕过所有事件派发机制）
            invoked = 0
            for listener in click_listeners[:3]:
                handler_id = listener.get("handler", {}).get("objectId")
                if not handler_id:
                    continue
                try:
                    call_resp = cdp.send("Runtime.callFunctionOn", {
                        "objectId": handler_id,
                        "functionDeclaration": """function() {
                            const btn = document.querySelector('button[data-rpa-refresh="1"]');
                            const target = btn || this;
                            let r;
                            try { r = target.getBoundingClientRect(); } catch(e) { r = {x:0,y:0,width:0,height:0}; }
                            const x = r.x + r.width/2, y = r.y + r.height/2;
                            const evt = new MouseEvent('click', {
                                bubbles: true, cancelable: true, view: window,
                                clientX: x, clientY: y, button: 0
                            });
                            return this.call(target, evt);
                        }""",
                        "returnByValue": True
                    })
                    invoked += 1
                    err_text = str(call_resp.get("exceptionDetails", {}).get("text", ""))
                    if err_text:
                        log(f"  [CDP监听器] 调用监听器#{invoked} 异常: {err_text[:100]}")
                except Exception as e:
                    log(f"  [CDP监听器] 调用监听器失败: {str(e)[:100]}")

            log(f"  [CDP监听器] 已直接调用 {invoked} 个 click 监听器函数")
            return invoked > 0
        except Exception as e:
            log(f"  [CDP监听器] 异常：{str(e)[:150]}")
            return False
        finally:
            try:
                cdp.detach()
            except Exception:
                pass

    def _ng_component_refresh():
        """通过 Angular __ngContext__ 找到 PLX 表格组件实例，直接调用其刷新/加载方法。
        完全绕过 DOM 事件系统，直接执行组件的数据加载逻辑。"""
        try:
            result = dialog_ctx.evaluate("""() => {
                const btn = document.querySelector('button[data-rpa-refresh="1"]');
                if (!btn) return {ok: false, err: 'no_marked_btn'};

                // 从按钮向上查找带 __ngContext__ 的元素
                let el = btn;
                let ngCtx = null;
                for (let i = 0; i < 15 && el; i++) {
                    const key = Object.keys(el).find(k => k.startsWith('__ngContext__'));
                    if (key) { ngCtx = el[key]; break; }
                    el = el.parentElement;
                }
                if (!ngCtx) return {ok: false, err: 'no_ng_context'};

                // 遍历 LView 链，收集所有组件实例
                const components = [];
                let view = ngCtx;
                for (let vi = 0; vi < 20 && view; vi++) {
                    if (Array.isArray(view)) {
                        for (let i = 0; i < Math.min(view.length, 60); i++) {
                            const v = view[i];
                            if (v && typeof v === 'object' && !Array.isArray(v)
                                && !(v instanceof HTMLElement) && !(v instanceof SVGElement)
                                && v.constructor && v.constructor.name
                                && !/^(TNode|TView|TContainer|TElement|TText|LContainer|LView|Object|Array|Map|Set)/.test(v.constructor.name)
                                && typeof Object.getOwnPropertyNames === 'function') {
                                const proto = Object.getPrototypeOf(v);
                                if (proto && proto !== Object.prototype) {
                                    const methods = Object.getOwnPropertyNames(proto).filter(n => typeof v[n] === 'function' && n !== 'constructor');
                                    if (methods.length > 0) components.push({inst: v, name: v.constructor.name, methods});
                                }
                            }
                        }
                    }
                    view = view[4] || null; // PARENT_LVIEW_INDEX = 4
                }

                if (components.length === 0) return {ok: false, err: 'no_components_found'};

                // 查找包含刷新/加载方法的组件
                const REFRESH_RE = /^(refresh|reload|reLoad|query|search|loadData|fetchData|getData|doQuery|onRefresh|handleRefresh|refreshData|refreshGrid|loadGrid|queryData|initData|getList|fetchList|loadList)$/i;
                for (const comp of components) {
                    const match = comp.methods.find(m => REFRESH_RE.test(m));
                    if (match) {
                        try {
                            comp.inst[match]();
                            return {ok: true, component: comp.name, method: match,
                                    allMethods: comp.methods.slice(0, 25), total: components.length};
                        } catch(e) {
                            return {ok: false, err: 'call_failed: ' + String(e).slice(0, 100),
                                    component: comp.name, method: match};
                        }
                    }
                }
                // 未找到精确匹配，列出所有组件方法供诊断
                return {ok: false, err: 'no_refresh_method',
                        components: components.slice(0, 6).map(c => c.name + ': ' + c.methods.slice(0, 12).join(','))};
            }""")
            if result and result.get('ok'):
                log(f"  [Angular组件] 已调用 {result.get('component')}.{result.get('method')}() "
                    f"(共{result.get('total')}个组件, 方法列表: {result.get('allMethods', [])[:10]})")
                page.wait_for_timeout(1500)
                return True
            else:
                comps = result.get('components', [])
                if comps:
                    log(f"  [Angular组件] {result.get('err')} | 组件: {'; '.join(str(c)[:80] for c in comps[:3])}")
                else:
                    log(f"  [Angular组件] {result.get('err', result)}")
                return False
        except Exception as e:
            log(f"  [Angular组件] 异常：{str(e)[:150]}")
            return False

    def _click_refresh():
        """精确点击 My Export 弹窗内的刷新按钮，并通过网络请求验证是否生效。"""
        req_before = len(_all_requests_log)

        for label, c in [("dialog_ctx", dialog_ctx), ("frame", frame)]:
            try:
                result = c.evaluate(MARK_DIALOG_REFRESH_JS)
                if result and result.get('found'):
                    btn = result['btn']
                    log(f"  [精确定位] {label} 策略={result.get('strategy')} depth={result.get('depth', '-')} "
                        f"容器内按钮数={result.get('btnsInContainer', result.get('btnCount', '-'))} "
                        f"目标=({btn['x']},{btn['y']}) {btn['w']}x{btn['h']} disabled={result.get('disabled')}")

                    # ====== 方式1：Angular 组件实例直接调用刷新方法（最可靠） ======
                    if _ng_component_refresh():
                        req_after = len(_all_requests_log)
                        if req_after > req_before:
                            new_reqs = _all_requests_log[req_before:]
                            log(f"  ★ Angular 组件刷新已生效（触发 {req_after - req_before} 个请求）")
                            for r in new_reqs[:3]:
                                log(f"    → {r['method']} {r['url'][:100]}")
                            return True

                    # ====== 方式2：CDP 直接调用按钮的 click 监听器函数 ======
                    if _cdp_invoke_listener():
                        page.wait_for_timeout(1500)
                        req_after = len(_all_requests_log)
                        if req_after > req_before:
                            log(f"  ★ CDP 监听器直接调用已生效（触发 {req_after - req_before} 个请求）")
                            return True
                        log("  CDP 监听器已调用但未触发新请求")

                    # ====== 方式3：Playwright locator 物理点击 ======
                    loc = c.locator('button[data-rpa-refresh="1"]')
                    loc.click(timeout=3000, force=True)
                    page.wait_for_timeout(1200)
                    req_after = len(_all_requests_log)
                    if req_after > req_before:
                        log(f"  locator.click 已生效（触发 {req_after - req_before} 个请求）")
                        return True

                    # ====== 方式4：page.mouse.click 可信输入事件（iframe 坐标转换） ======
                    try:
                        offset = _get_iframe_offset(page, c)
                        mx = offset['x'] + btn['x'] + btn['w'] / 2
                        my = offset['y'] + btn['y'] + btn['h'] / 2
                        page.mouse.click(mx, my)
                        log(f"  page.mouse.click ({mx:.0f},{my:.0f})")
                    except Exception:
                        pass
                    page.wait_for_timeout(1200)
                    req_after2 = len(_all_requests_log)
                    if req_after2 > req_before:
                        log(f"  page.mouse.click 已生效（触发 {req_after2 - req_before} 个请求）")
                        return True
                    log("  所有方式均未触发网络请求（不影响流程，API 直接查询仍在工作）")
                    return False
                else:
                    log(f"  [精确定位] {label} 未找到: {result.get('reason') if result else 'evaluate返回空'}")
            except Exception as e:
                log(f"  [精确定位] 异常({label})：{e}")

        log("未找到刷新按钮（不影响流程，API 直接查询仍在工作）")
        return False

    def _wait_download(timeout_sec=60):
        import time as _time
        deadline = _time.time() + timeout_sec
        while _time.time() < deadline and not captured_downloads:
            page.wait_for_timeout(1000)
        if captured_downloads:
            dl = captured_downloads[0]
            save_path = OUTPUT_DIR / dl.suggested_filename
            dl.save_as(str(save_path))
            log(f"下载完成，保存到：{save_path} ({os.path.getsize(save_path)} bytes)")
            return True
        # 兜底：从系统下载目录复制
        user_downloads = Path.home() / "Downloads"
        before_sys = {f for f in user_downloads.iterdir() if f.is_file()} if user_downloads.exists() else set()
        page.wait_for_timeout(3000)
        new_file = _wait_for_new_file(user_downloads, before_sys, timeout_sec=10)
        if new_file:
            import shutil
            dest = OUTPUT_DIR / new_file.name
            shutil.copy2(str(new_file), str(dest))
            log(f"从系统下载目录复制：{new_file} -> {dest}")
            return True
        log("未捕获到下载文件")
        return False

    success = False
    api_export_ready = False

    # 直接 API 查询（完全绕过 UI 刷新按钮）：每次轮询主动 fetch 最新状态
    DIRECT_QUERY_JS = """async (reqInfo) => {
        try {
            const opts = {method: 'POST', credentials: 'include',
                headers: {'Content-Type': 'application/json'}};
            if (reqInfo && reqInfo.post_data) {
                opts.body = reqInfo.post_data;
                if (reqInfo.headers) {
                    for (const k of ['authorization','cookie','x-xsrf-token','csrf-token']) {
                        if (reqInfo.headers[k]) opts.headers[k] = reqInfo.headers[k];
                    }
                }
            }
            const url = (reqInfo && reqInfo.url) ? reqInfo.url : '/api/eflow-ticket/v1/export/offlineExport/query';
            const resp = await fetch(url, opts);
            const data = await resp.json();
            // 兼容多种响应结构
            let records = data.data || data.result || data.rows || (Array.isArray(data) ? data : []);
            if (records.records) records = records.records;
            if (!Array.isArray(records) || records.length === 0) return {empty: true, raw: JSON.stringify(data).slice(0, 200)};
            // 返回所有记录（导出可能生成多个 ZIP 文件），逐个下载
            const parsed = records.map(r => ({
                status: String(r.status || r.Status || r.state || ''),
                progress: parseInt(r.progress || r.Progress || r.processProgress || r.process_progress || 0, 10),
                fileName: r.fileName || r.FileName || r.file_name || '',
                ftpFilePath: r.ftpFilePath || r.FtpFilePath || r.ftp_file_path || '',
                tableType: r.tableType || r.TableType || '',
                ready: (parseInt(r.progress || r.Progress || r.processProgress || r.process_progress || 0, 10) >= 100)
                    || /success|complete|done|finished/i.test(r.status || r.Status || r.state || '')
            }));
            return {
                records: parsed,
                all_ready: parsed.every(r => r.ready),
                total: parsed.length,
                ready_count: parsed.filter(r => r.ready).length
            };
        } catch(e) { return {error: String(e)}; }
    }"""

    for attempt in range(1, max_attempts + 1):
        # ====== 主要机制：直接 API 查询（不依赖 UI 刷新按钮） ======
        api_info = None
        try:
            last_req = captured_api_requests[-1] if captured_api_requests else None
            api_info = dialog_ctx.evaluate(DIRECT_QUERY_JS, last_req)
        except Exception as e:
            log(f"轮询第 {attempt}/{max_attempts} 次：API 直接查询异常：{e}")

        if api_info and not api_info.get('error') and not api_info.get('empty'):
            records = api_info.get('records', [])
            ready_count = api_info.get('ready_count', 0)
            total = api_info.get('total', len(records))
            log(f"轮询第 {attempt}/{max_attempts} 次：[API] {ready_count}/{total} 个文件就绪")

            # 下载所有已就绪的文件
            downloaded_any = False
            for rec in records:
                if rec.get('ready') and rec.get('fileName') and rec.get('ftpFilePath'):
                    try:
                        export_file_info = {
                            'fileName': rec['fileName'],
                            'ftpFilePath': rec['ftpFilePath'],
                            'tableType': rec.get('tableType') or table_type
                        }
                        download_export(page, context, export_file_info)
                        downloaded_any = True
                    except Exception as e:
                        log(f"  API 下载异常 ({rec['fileName']})：{e}")

            if api_info.get('all_ready'):
                log(f"API 确认所有 {total} 个文件已就绪并开始下载")
                api_export_ready = True
                if downloaded_any:
                    page.wait_for_timeout(3000)
                    downloaded_zips = [f for f in OUTPUT_DIR.iterdir() if f.is_file() and f.name.endswith('.zip')]
                    if downloaded_zips:
                        success = True
                        log(f"已下载 {len(downloaded_zips)} 个 ZIP 文件，等待后续合并")
                        break
                # 兜底：UI 逐个点击下载
                log("API 下载未全部完成，通过 UI 点击剩余 Download...")
                for _ in range(total):
                    captured_downloads.clear()
                    _click_first_download()
                    if _wait_download(30):
                        downloaded_any = True
                    page.wait_for_timeout(2000)
                if downloaded_any:
                    success = True
                    break
        elif api_info:
            log(f"轮询第 {attempt}/{max_attempts} 次：[API] {api_info.get('error') or api_info.get('raw', '无记录')}")

        # ====== 辅助机制：UI 读取（如果刷新生效了 UI 也会更新） ======
        ctx, info = _read_first_row()
        if ctx:
            dialog_ctx = ctx
        if info:
            log(f"  [UI] Status={info.get('status')!r} Progress={info.get('progress')}")
            if info.get('ready'):
                log("UI 显示已 100%，点击 Download...")
                captured_downloads.clear()
                _click_first_download()
                success = _wait_download(60)
                break

        # 尝试点击刷新按钮（尽力而为，不阻塞流程）
        _click_refresh()
        dialog_ctx.wait_for_timeout(interval * 1000)
    
    if not success:
        log("轮询超时，兆底点击第一行 Download")
        captured_downloads.clear()
        _click_first_download()
        success = _wait_download(60)

    try:
        page.remove_listener("download", on_download)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 合并下载 ZIP 文件到 Eflow_TT_FB.xlsx
# ---------------------------------------------------------------------------


def merge_downloads_to_excel(output_name: str = "Eflow_TT_FB.xlsx") -> None:
    """读取 downloads/ 目录中所有 ZIP 文件，解压其中的 xlsx 并合并写入指定 Excel，完成后删除 ZIP。"""
    import zipfile
    import io
    import glob
    import pandas as pd

    start_ts = time.time()
    zip_pattern = str(OUTPUT_DIR / "*.zip")
    zip_files = sorted(glob.glob(zip_pattern))

    if not zip_files:
        log("downloads/ 目录中没有找到任何 ZIP 文件，跳过合并")
        return

    log(f"找到 {len(zip_files)} 个 ZIP 文件，开始解压合并...")
    all_frames = []

    for zf_path in zip_files:
        zf_name = Path(zf_path).name
        try:
            with zipfile.ZipFile(zf_path, "r") as zf:
                # 记录 ZIP 内所有文件和 xlsx 文件
                all_names = zf.namelist()
                xlsx_names = [n for n in all_names if n.lower().endswith(".xlsx")]
                log(f"  ZIP [{zf_name}] 共 {len(all_names)} 个文件，其中 {len(xlsx_names)} 个 xlsx: {xlsx_names[:6]}{'...' if len(xlsx_names) > 6 else ''}")
                # 记录全部文件列表（排除非数据文件）
                non_xlsx = [n for n in all_names if not n.lower().endswith(".xlsx")]
                if non_xlsx:
                    log(f"    非 xlsx 文件: {non_xlsx[:5]}{'...' if len(non_xlsx) > 5 else ''}")

                for xlsx_name in sorted(xlsx_names):
                    try:
                        info = zf.getinfo(xlsx_name)
                        file_size_kb = info.file_size / 1024
                        data = zf.read(xlsx_name)
                        log(f"    读取 {xlsx_name} ({file_size_kb:.1f} KB)...")
                        
                        # 读取所有 sheet（防止数据在非第一个 sheet 中）
                        xls_data = pd.read_excel(io.BytesIO(data), sheet_name=None, engine="openpyxl")
                        file_row_count = 0
                        for sheet_name, sheet_df in xls_data.items():
                            if sheet_df.empty:
                                log(f"      sheet [{sheet_name}]: 空，跳过")
                                continue
                            all_frames.append(sheet_df)
                            file_row_count += len(sheet_df)
                            log(f"      sheet [{sheet_name}]: {len(sheet_df)} 行")
                        log(f"    {xlsx_name} 合计: {file_row_count} 行")
                    except Exception as exc:
                        log(f"    {xlsx_name}: 读取失败：{exc}")
                        import traceback
                        log(f"    {xlsx_name}: {traceback.format_exc()[:200]}")
        except Exception as exc:
            log(f"  处理 ZIP [{zf_name}] 失败：{exc}")
            import traceback
            log(f"  {traceback.format_exc()[:200]}")

    if not all_frames:
        log("未从 ZIP 中读取到任何数据，跳过写入")
        return

    # 向量化合并所有 DataFrame
    combined = pd.concat(all_frames, ignore_index=True)
    log(f"合并完成，共 {len(combined)} 行数据")

    # 写入指定 Excel（如被占用则自动加序号）
    output_xlsx = OUTPUT_DIR.parent / output_name
    seq = 1
    while True:
        try:
            combined.to_excel(str(output_xlsx), index=False, engine="openpyxl")
            break
        except PermissionError:
            stem = Path(output_name).stem
            ext = Path(output_name).suffix
            output_xlsx = OUTPUT_DIR.parent / f"{stem}_{seq}{ext}"
            seq += 1

    log(f"已写入：{output_xlsx}（{len(combined)} 行，耗时 {time.time() - start_ts:.1f}s）")

    # 删除所有已处理的 ZIP 文件
    deleted = 0
    for zf_path in zip_files:
        try:
            os.remove(zf_path)
            deleted += 1
        except Exception as exc:
            log(f"  删除 ZIP 失败 [{Path(zf_path).name}]：{exc}")
    log(f"已删除 {deleted}/{len(zip_files)} 个 ZIP 文件")


# ---------------------------------------------------------------------------
# 独立登录函数（供外部脚本 import 使用）
# ---------------------------------------------------------------------------


def zte_login(page) -> bool:
    """在已打开的浏览器页面上执行 ZTE 网管登录。

    Args:
        page: Playwright Page 对象（已打开 OAuth2 授权页）

    Returns:
        True 表示登录成功（已跳转至 portal）；False 表示失败
    """
    log("检测登录表单元素是否可见...")

    # 如果已经登录或被重定向，直接返回
    if "default.html" in page.url and "authorize" not in page.url:
        log("已自动登录（使用了缓存 session）")
        return True

    username_candidates = [
        USERNAME_SELECTOR,
        "#inputUserName",
        "input[name='username']",
        "#username",
        "input[id='username']",
        "input[type='text']",
    ]
    password_candidates = [
        PASSWORD_SELECTOR,
        "#inputCiphercode",
        "input[name='cipher_code']",
        "#password",
        "input[name='password']",
        "input[id='password']",
        "input[type='password']",
    ]
    login_candidates = [
        LOGIN_SELECTOR,
        "#loginBut",
        "button:has-text('Login')",
        "button:has-text('登录')",
        "input[type='submit']",
        "button[type='submit']",
    ]

    username_sel = detect_selector(page, username_candidates)
    password_sel = detect_selector(page, password_candidates)
    login_sel = detect_selector(page, login_candidates)

    if not username_sel:
        log("未找到用户名输入框，请检查页面是否已加载或调整 USERNAME_SELECTOR")
        return False
    log(f"使用用户名选择器：{username_sel}")
    username_input = page.locator(username_sel)
    try:
        username_input.wait_for(state="visible", timeout=10000)
    except Exception:
        log("用户名输入框等待 visible 超时，尝试 force fill")

    log(f"填写用户名：{USERNAME}")
    username_input.fill(USERNAME)

    if password_sel:
        log(f"使用密码选择器：{password_sel}")
        password_input = page.locator(password_sel)
        try:
            password_input.fill(PASSWORD)
        except Exception:
            log("password fill 失败，尝试 keyboard.type...")
            password_input.focus(force=True)
            page.keyboard.type(PASSWORD, delay=50)
    else:
        log("未找到密码选择器，跳过密码填写")

    if login_sel:
        log(f"使用登录按钮选择器：{login_sel}")
        try:
            page.locator(login_sel).click()
        except Exception:
            log("登录按钮 click 失败，尝试 force click")
            try:
                page.locator(login_sel).click(force=True)
            except Exception:
                log("force click 也失败，尝试 JS click")
                page.evaluate(f"""() => {{
                    const btn = document.querySelector('{login_sel}');
                    if (btn) btn.click();
                }}""")

        try:
            page.wait_for_url(
                re.compile(r"https://[^/]+/uportal/framework/default\.html"),
                timeout=20000,
            )
            log("页面已跳转至 default.html")
            return True
        except PlaywrightTimeout:
            log("未在 20 秒内检测到 default.html 跳转，登录可能失败")
            return False
    else:
        log("未找到登录按钮，请调整 LOGIN_SELECTOR")
        return False


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run() -> None:
    if TARGET_URL.endswith("...") or not TARGET_URL.startswith("http"):
        print("\n[错误] TARGET_URL 尚未配置完整，请先在脚本顶部补全 URL 后再运行。\n")
        sys.exit(1)

    # 确保输出目录存在（Chrome 启动参数需要该目录已存在）
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    launch_options = {
        "headless": HEADLESS,
        "args": [
            "--start-maximized",
            "--window-position=0,0",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
            f"--download-default-directory={OUTPUT_DIR}",
        ],
    }

    # 桌面模式下根据屏幕分辨率设置窗口大小，保证最大化效果
    if not HEADLESS:
        try:
            sw, sh = pyautogui.size()
            launch_options["args"].append(f"--window-size={sw},{sh}")
            log(f"设置窗口大小：{sw}x{sh}")
        except Exception as exc:
            log(f"获取屏幕分辨率失败：{exc}")

    if CHROME_EXE is not None and CHROME_EXE.exists():
        launch_options["executable_path"] = str(CHROME_EXE)
        log(f"使用本地 Chrome: {CHROME_EXE}")
    else:
        log("未找到项目目录下的 chrome-win/chrome.exe，将使用 Playwright 自带的 Chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_options)
        context_options = {
            "ignore_https_errors": True,
            "accept_downloads": True,
        }
        if HEADLESS:
            context_options["viewport"] = {"width": 1920, "height": 1080}
        else:
            context_options["no_viewport"] = True
        context = browser.new_context(**context_options)
        page = context.new_page()

        # 1. 打开网页
        log(f"打开网页：{TARGET_URL}")
        page.goto(TARGET_URL, timeout=60000)
        # 确保登录浏览器窗口最大化（桌面模式）
        maximize_window(page)

        # 2. 等待 1 秒
        wait(1)

        # 3. 获取已打开的网页对象（直接使用 page 变量）
        web_page = page
        log("已获取网页对象")

        # 4. 获取窗口对象（Playwright 中由浏览器上下文管理）
        # 5. 设置窗口状态为最大化（已通过 --start-maximized + no_viewport 实现）
        log("窗口已最大化")

        # 6. 等待 3 秒
        wait(3)

        # 7. IF 图像存在 -> 点击图像 -> 等待 -> 等待 -> 点击图像
        if ENABLE_IMAGE_BRANCH:
            log("检查图像分支...")
            if click_image_if_found(IMG_ADVANCED):
                wait(1)
                wait(1)
                click_image_if_found(IMG_CONTINUE)
            else:
                log("未找到第一张图像，跳过图像分支")
        else:
            log("图像识别分支已禁用")

        # 8. 获取已打开的网页对象（再次确认 page 引用）
        web_page = page
        log("重新获取网页对象")

        # 9. 等待 2 秒
        wait(2)

        # 10. IF 元素可见 -> 填写用户名 -> 填写密码 -> 点击 Login
        log("检测登录表单元素是否可见...")

        # 自动探测选择器（若未在配置区指定）
        # 针对 ZTE uSmartNet 登录页：inputUserName / inputCiphercode / loginBut
        username_candidates = [
            USERNAME_SELECTOR,
            "#inputUserName",
            "input[name='username']",
            "#username",
            "input[id='username']",
            "input[type='text']",
        ]
        password_candidates = [
            PASSWORD_SELECTOR,
            "#inputCiphercode",
            "input[name='cipher_code']",
            "#password",
            "input[name='password']",
            "input[id='password']",
            "input[type='password']",
        ]
        login_candidates = [
            LOGIN_SELECTOR,
            "#loginBut",
            "button:has-text('Login')",
            "button:has-text('登录')",
            "input[type='submit']",
            "button[type='submit']",
        ]

        username_sel = detect_selector(web_page, username_candidates)
        password_sel = detect_selector(web_page, password_candidates)
        login_sel = detect_selector(web_page, login_candidates)

        if not username_sel:
            log("未找到用户名输入框，请检查页面是否已加载或调整 USERNAME_SELECTOR")
            _safe_finish(browser, web_page, context)
            return
        log(f"使用用户名选择器：{username_sel}")
        username_input = web_page.locator(username_sel)
        username_input.wait_for(state="visible", timeout=10000)

        # 填写用户名（对应 "剪切板复制粘贴输入 admin"）
        log(f"填写用户名：{USERNAME}")
        username_input.fill(USERNAME)

        # 填写密码
        if password_sel:
            log(f"使用密码选择器：{password_sel}")
            password_input = web_page.locator(password_sel)
            password_input.fill(PASSWORD)
        else:
            log("未找到密码选择器，跳过密码填写")

        # 点击 Login
        if login_sel:
            log(f"使用登录按钮选择器：{login_sel}")
            web_page.locator(login_sel).click()
            # 等待登录后的跳转（ZTE uSmartNet 会跳转到 /uportal/framework/default.html#/home）
            try:
                web_page.wait_for_url(
                    re.compile(r"https://[^/]+/uportal/framework/default\.html"),
                    timeout=15000,
                )
                log("页面已跳转至 default.html")
            except PlaywrightTimeout:
                log("未在 15 秒内检测到 default.html 跳转")
        else:
            log("未找到登录按钮，请调整 LOGIN_SELECTOR")

        # 等待页面网络空闲
        try:
            web_page.wait_for_load_state("networkidle", timeout=15000)
            log("登录流程执行完成")
        except PlaywrightTimeout:
            log("networkidle 等待超时，但登录动作已执行")

        # 登录成功后再次确保窗口最大化（桌面模式）
        maximize_window(web_page)

        if ENABLE_EXPORT_FLOW:
            export_flow = [
                (TT_URL, "eflow-tt", "Eflow_TT_FB.xlsx", "TT"),
                (WO_URL, "eflow-wo", "Eflow_WO_FB.xlsx", "WO"),
            ]
            for url, tbl_type, out_name, label in export_flow:
                try:
                    log(f"=== 开始 {label} 导出流程 ===")
                    run_export_flow(web_page, context, target_url=url, default_table_type=tbl_type)
                    log(f"{label} 导出完成，开始合并...")
                    merge_downloads_to_excel(out_name)
                    log(f"{label} 处理完成：{out_name}")
                except Exception as exc:
                    log(f"{label} 导出流程异常：{exc}")
                    safe_screenshot(web_page, f"export_{label.lower()}_error")
                # 回到空白页清状态
                try:
                    web_page.goto("about:blank", timeout=15000)
                except Exception:
                    pass
                web_page.wait_for_timeout(2000)
        else:
            log("导出流程已禁用")

        _safe_finish(browser, web_page, context)


def _safe_finish(browser, page, context) -> None:
    """收尾：无头模式截图+输出最终URL后关闭；桌面模式保留浏览器等待回车。"""
    try:
        shot_dir = BASE_DIR / "process"
        shot_dir.mkdir(parents=True, exist_ok=True)
        shot = shot_dir / "login_result.png"
        page.screenshot(path=str(shot))
        log(f"已截图：{shot}")
    except Exception as exc:
        log(f"截图失败：{exc}")

    final_url = page.url
    log(f"最终页面 URL：{final_url}")
    # ZTE uSmartNet 登录成功后会跳转到 /uportal/framework/default.html#/home
    # OAuth 标准授权码流也可能在 ?code= 中返回授权码
    parsed = urlparse(final_url)
    qs = parse_qs(parsed.query)
    if parsed.path.endswith("/uportal/framework/default.html") or "#/home" in final_url:
        log(">>> 判定：登录成功（已跳转至 portal 首页）")
    elif "code" in qs:
        log(f">>> 判定：登录/授权成功（获得授权码，长度为 {len(qs['code'][0])}）")
    else:
        log(">>> 判定：未检测到成功跳转，登录可能失败或仍在登录页")

    if HEADLESS:
        browser.close()
    else:
        input("\n按回车键关闭浏览器...")
        browser.close()


if __name__ == "__main__":
    run()
