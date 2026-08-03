"""
WhatsApp 消息发送服务
集成 sent_whatsapp_v2.py - 通过 Playwright 自动发送图片/文件到 WhatsApp 群组
"""
import os
import sys
import time
import glob
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger("whatsapp_service")

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# ========== 配置（环境变量优先，便于 Windows 部署） ==========
# 图片/数据文件所在目录
DEFAULT_DIR = r"D:\01_RPA\Task\my_app\backend\services\data\site_outage"
SITE_OUTAGE_DIR = Path(os.environ.get("SITE_OUTAGE_DIR", DEFAULT_DIR))

# 群组：逗号分隔，例如 "test123,Test234"
_GROUPS_ENV = os.environ.get("WHATSAPP_GROUPS", "test123,Test234")
GROUPS = [g.strip() for g in _GROUPS_ENV.split(",") if g.strip()]

# 图片获取逻辑
_PHOTOS_ENV = os.environ.get("WHATSAPP_PHOTOS", "").strip()
if _PHOTOS_ENV:
    PHOTOS = [p.strip() for p in _PHOTOS_ENV.split(",") if p.strip()]
else:
    valid_extensions = ("*.png", "*.PNG", "*.jpg", "*.JPG", "*.jpeg", "*.JPEG")
    found_photos = set()  # 使用 set 自动去重，防止 Windows 环境重复匹配
    for ext in valid_extensions:
        found_photos.update(SITE_OUTAGE_DIR.glob(ext))
    
    PHOTOS = sorted(
        str(p) for p in found_photos
        if "debug" not in p.name.lower()
    )

# 备注：与 PHOTOS 一一对应；不足则用文件名（去扩展名）
_CAPTIONS_ENV = os.environ.get("WHATSAPP_CAPTIONS", "").strip()
if _CAPTIONS_ENV:
    CAPTIONS = [c.strip() for c in _CAPTIONS_ENV.split(",") if c.strip()]
else:
    CAPTIONS = [f"*{Path(p).stem}*" for p in PHOTOS]

HEADLESS = os.environ.get("WHATSAPP_HEADLESS", "false").lower() in ("1", "true", "yes")
MAX_RETRY = int(os.environ.get("WHATSAPP_MAX_RETRY", "3"))
WAIT_TIMEOUT = int(os.environ.get("WHATSAPP_WAIT_TIMEOUT", "180000"))
CLOSE_DELAY = float(os.environ.get("WHATSAPP_CLOSE_DELAY", "8"))

USER_DATA_DIR = os.environ.get(
    "WHATSAPP_SESSION",
    str(Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))) / "whatsapp_session"),
)
DEBUG_DIR = os.environ.get(
    "WHATSAPP_DEBUG_DIR",
    str(Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))) / "scheduler_logs"),
)
WHATSAPP_URL = "https://web.whatsapp.com"

CHROME_PATH = os.environ.get(
    "CHROME_PATH",
    r"D:\01_RPA\chrome-win\chrome-win\chrome.exe",
)

# 完整的 选择器 字典，保留了 ATTACH Key
SELECTORS = {
    "SEARCH_BOX": ['#side div[contenteditable="true"]', '#side [role="textbox"]'],
    "MAIN": ["#main"],
    "CAPTION_INPUT": [
        'div[aria-label="添加小标题"]',
        'div[aria-label="Add a caption"]',
        'div[contenteditable="true"][data-tab="10"]',
        'div._ak1r div[contenteditable="true"]',
    ],
    "ATTACH": [
        '[data-icon="plus"]',
        '[data-testid="attach-menu-plus"]',
        'span[data-icon="clip"]',
        'div[title*="Attach"]',
        'div[title*="附件"]',
        'span[data-icon="attach-menu-plus"]',
    ],
}


def _get_latest_site_outage():
    """获取最新的 site outage xlsx 文件"""
    pattern = os.path.join(SITE_OUTAGE_DIR, "*site_outage_*")
    files = [f for f in glob.glob(pattern) if f.endswith(('.xlsx', '.xls'))]
    if not files:
        return None
    return max(files, key=lambda f: os.path.getmtime(f))


def _copy_image_to_clipboard(image_path):
    abs_path = os.path.abspath(image_path)
    ps_cmd = (
        f"Add-Type -AssemblyName System.Windows.Forms; "
        f"$img = [System.Drawing.Image]::FromFile('{abs_path}'); "
        f"[System.Windows.Forms.Clipboard]::SetImage($img); "
        f"$img.Dispose()"
    )
    subprocess.run(["powershell", "-STA", "-Command", ps_cmd], check=True, creationflags=_SUBPROCESS_FLAGS)


def _copy_file_to_clipboard(file_path):
    abs_path = os.path.abspath(file_path)
    ps_cmd = (
        f"Add-Type -AssemblyName System.Windows.Forms; "
        f"$files = '{abs_path}'; "
        f"$col = New-Object System.Collections.Specialized.StringCollection; "
        f"$col.Add($files); "
        f"[System.Windows.Forms.Clipboard]::SetFileDropList($col)"
    )
    subprocess.run(["powershell", "-STA", "-Command", ps_cmd], check=True, creationflags=_SUBPROCESS_FLAGS)


# ==========================================================
# 辅助函数
# ==========================================================
def _info(msg): logger.info(f"[WhatsApp] {msg}")
def _success(msg): logger.info(f"[WhatsApp] {msg}")
def _warn(msg): logger.warning(f"[WhatsApp] {msg}")
def _error(msg): logger.error(f"[WhatsApp] {msg}")


def _retry(func):
    def wrapper(*args, **kwargs):
        last = None
        for i in range(MAX_RETRY):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last = e
                _warn(f"重试 {i+1}/{MAX_RETRY}: {e}")
        raise last
    return wrapper


def _find_first(page, key):
    for selector in SELECTORS[key]:
        try:
            loc = page.locator(selector)
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _find_first: exception swallowed", exc_info=True)
            pass
    return None


def _kill_stale_chrome(user_data_dir: str | None = None):
    """只杀可能锁住 WhatsApp profile 的 chrome，避免误杀用户浏览器。"""
    udd = (user_data_dir or USER_DATA_DIR).replace("'", "''")
    try:
        ps_cmd = (
            f"$p = '{udd}'; "
            "Get-CimInstance Win32_Process -Filter \"name='chrome.exe'\" | "
            "Where-Object { $_.CommandLine -and ($_.CommandLine -like ('*' + $p + '*')) } | "
            "ForEach-Object { "
            "  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; "
            "  Write-Output $_.ProcessId "
            "}"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15,
            creationflags=_SUBPROCESS_FLAGS,
        )
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _kill_stale_chrome: exception swallowed", exc_info=True)
        pass
    time.sleep(0.8)
    _info("已清理占用 session 的 chrome 进程（如有）")


def _is_logged_in(page) -> bool:
    """多选择器判断登录态：聊天列表/搜索框/#side 任一存在即认为已登录。"""
    for sel in ("#side", "[data-testid='chat-list']",
                "[data-testid='conversation-list']", "div[data-testid='search']"):
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                try:
                    if loc.first.is_visible(timeout=1500):
                        return True
                except Exception:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] _is_logged_in: exception swallowed", exc_info=True)
                    pass
                return True
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _is_logged_in: exception swallowed", exc_info=True)
            pass
    return False


def _is_qr_screen(page) -> bool:
    """判断是否停留在扫码登录页（会话过期）"""
    try:
        loc = page.locator("div[data-testid='intro-wrapper'], canvas[aria-label*='Scan'], [data-testid='qr-code']")
        return loc.count() > 0 and loc.first.is_visible(timeout=2000)
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _is_qr_screen: exception swallowed", exc_info=True)
        return False


def _click_reconnect_if_needed(page):
    """出现“连接断开，点击重连”横幅时自动点击"""
    try:
        reconnect = page.locator(
            "button:has-text('重连'), button:has-text('Reconnect'), "
            "div[role='button']:has-text('重新连接'), div[role='button']:has-text('Reconnect')"
        )
        if reconnect.count() > 0 and reconnect.first.is_visible(timeout=2000):
            reconnect.first.click(timeout=3000)
            _info("检测到连接断开，已自动点击重连")
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _click_reconnect_if_needed: exception swallowed", exc_info=True)
        pass


@_retry
def _search_and_open(page, contact_name):
    """搜索并打开联系人/群组聊天窗口"""
    _info(f"正在搜索: {contact_name}")
    search_box = _find_first(page, "SEARCH_BOX")
    if not search_box:
        raise Exception("找不到搜索框")

    search_box.click()
    page.keyboard.press("Control+a")
    page.keyboard.press("Backspace")
    search_box.fill(contact_name)
    time.sleep(2)
    page.keyboard.press("Enter")
    time.sleep(2)

    if not page.locator(SELECTORS["MAIN"][0]).is_visible():
        raise Exception("未能进入聊天窗口")
    _success(f"成功进入: {contact_name}")


def _find_attach_button(page):
    for sel in SELECTORS["ATTACH"]:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible(timeout=1500):
                return loc.first
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _find_attach_button: exception swallowed", exc_info=True)
            continue
    return None


def _send_one_photo_via_input(page, photo_path: str, caption: str) -> bool:
    """通过附件按钮 + input[type=file] 发送单图+备注。成功返回 True。"""
    attach = _find_attach_button(page)
    if not attach:
        return False
    try:
        attach.click(timeout=5000)
        page.wait_for_timeout(400)

        inputs = page.locator('input[type="file"]')
        if inputs.count() == 0:
            return False

        target = None
        for i in range(inputs.count()):
            el = inputs.nth(i)
            try:
                acc = (el.get_attribute("accept") or "").lower()
                if "image" in acc or acc == "" or "*/*" in acc:
                    target = el
                    break
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _send_one_photo_via_input: exception swallowed", exc_info=True)
                continue
        if target is None:
            target = inputs.last

        target.set_input_files(photo_path)

        page.wait_for_timeout(600)
        try:
            page.wait_for_selector(
                'div[contenteditable="true"][data-tab="10"], '
                'div[aria-label*="caption" i], div[aria-label*="小标题"], '
                'div[aria-label*="Add a caption"]',
                timeout=10000,
            )
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _send_one_photo_via_input: exception swallowed", exc_info=True)
            pass

        caption_box = _find_first(page, "CAPTION_INPUT")
        if caption_box:
            try:
                caption_box.click(timeout=2000)
                caption_box.fill("")
                caption_box.type(caption, delay=20)
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _send_one_photo_via_input: exception swallowed", exc_info=True)
                page.keyboard.type(caption)
        else:
            page.keyboard.type(caption)

        page.keyboard.press("Enter")
        page.wait_for_timeout(700)
        return True
    except Exception as e:
        _warn(f"file input 发送失败，将尝试剪贴板: {e}")
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _send_one_photo_via_input: exception swallowed", exc_info=True)
            pass
        return False


def _send_one_photo_via_clipboard(page, photo_path: str, caption: str) -> None:
    """剪贴板 fallback（Windows PowerShell）。"""
    _copy_image_to_clipboard(photo_path)
    page.locator("#main").click(force=True)
    page.keyboard.press("Control+v")
    page.wait_for_timeout(1200)
    page.keyboard.type(caption)
    page.keyboard.press("Enter")
    page.wait_for_timeout(700)


def _fast_send_photos(page, photo_caption_pairs):
    """单图单备注发送：优先 file input，失败再剪贴板。"""
    page.locator("#main").click(force=True)

    for i, (photo, cap) in enumerate(photo_caption_pairs):
        if not os.path.exists(photo):
            _warn(f"跳过不存在图片: {photo}")
            continue

        _info(f"发送图片 ({i+1}/{len(photo_caption_pairs)}): {os.path.basename(photo)} -> {cap}")

        ok = _send_one_photo_via_input(page, photo, cap)
        if not ok:
            _warn("改用剪贴板发送")
            _send_one_photo_via_clipboard(page, photo, cap)

        page.wait_for_timeout(500)


def _fast_send_file(page, file_path):
    """优先附件 input，失败再剪贴板。"""
    if not file_path or not os.path.exists(file_path):
        return

    _info(f"发送文件: {os.path.basename(file_path)}")
    page.locator("#main").click(force=True)

    sent = False
    attach = _find_attach_button(page)
    if attach:
        try:
            attach.click(timeout=5000)
            page.wait_for_timeout(400)
            inputs = page.locator('input[type="file"]')
            if inputs.count() > 0:
                inputs.last.set_input_files(file_path)
                page.wait_for_timeout(1000)
                page.keyboard.press("Enter")
                page.wait_for_timeout(800)
                sent = True
        except Exception as e:
            _warn(f"file input 发文件失败: {e}")
            try:
                page.keyboard.press("Escape")
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _fast_send_file: exception swallowed", exc_info=True)
                pass

    if not sent:
        _copy_file_to_clipboard(file_path)
        page.locator("#main").click(force=True)
        page.keyboard.press("Control+v")
        page.wait_for_timeout(1200)
        page.keyboard.press("Enter")
        page.wait_for_timeout(800)


def _wait_for_last_message_sent(page, timeout=60):
    """等待最终消息送达确认"""
    _info("正在等待服务器回执确认...")

    DBL_CHECK_SELECTOR = (
        "span[data-icon='msg-dblcheck'], "
        "span[aria-label*='已读'], span[aria-label*='Read'], span[aria-label*='Delivered'], "
        "svg:has(title:has-text('wds-ic-read'))"
    )
    SINGLE_CHECK_SELECTOR = (
        "span[data-icon='msg-check'], "
        "span[aria-label*='已发送'], span[aria-label*='Sent'], "
        "svg:has(title:has-text('wds-ic-sent'))"
    )

    start = time.time()
    while time.time() - start < timeout:
        msgs = page.locator("div[role='row'], div[data-testid='msg-container']")
        if msgs.count() > 0:
            last_msg = msgs.last
            if last_msg.locator(DBL_CHECK_SELECTOR).count() > 0:
                _success("最终确认：全套已送达/已读")
                return True
            if last_msg.locator(SINGLE_CHECK_SELECTOR).count() > 0:
                _success("最终确认：全套已发送至服务器")
                return True
        time.sleep(0.5)

    _warn("状态确认超时，请人工检查界面！")
    return False


# ==========================================================
# 主入口
# ==========================================================
def run_whatsapp_send() -> dict:
    start_time = time.time()
    result = {
        "success": False,
        "groups_sent": [],
        "errors": [],
        "elapsed_seconds": 0,
    }

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] run_whatsapp_send: exception swallowed", exc_info=True)
        result["errors"].append("缺少 playwright 依赖，请运行: pip install playwright && playwright install chromium")
        return result

    Path(DEBUG_DIR).mkdir(exist_ok=True)

    pw = None
    browser = None
    try:
        _kill_stale_chrome(USER_DATA_DIR)

        pw = sync_playwright().start()

        launch_kwargs = dict(
            executable_path=CHROME_PATH,
            headless=HEADLESS,
            args=["--start-maximized", "--prevent-first-run-default-browser-prompts"],
            no_viewport=True,
        )
        proxy = os.environ.get("WHATSAPP_PROXY", "").strip()
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}
            _info(f"使用代理: {proxy}")

        browser = pw.chromium.launch_persistent_context(USER_DATA_DIR, **launch_kwargs)
        page = browser.new_page()

        logged_in = False
        for attempt in range(1, 4):
            try:
                page.goto(WHATSAPP_URL, wait_until="domcontentloaded", timeout=180000)
            except Exception as e:
                err_msg = str(e)
                if "ERR_CONNECTION_RESET" in err_msg:
                    _warn("goto 报 ERR_CONNECTION_RESET，页面可能已渲染，继续检测登录态")
                else:
                    _warn(f"页面导航异常(第{attempt}/3次): {e}")

            for _ in range(20):
                if _is_logged_in(page):
                    logged_in = True
                    break
                if _is_qr_screen(page):
                    result["errors"].append("WhatsApp 会话已过期，停留在二维码页面，需要扫码登录")
                    return result
                _click_reconnect_if_needed(page)
                time.sleep(3)
            if logged_in:
                break
            _warn(f"第{attempt}次未检测到登录态，尝试刷新页面后重试")
            try:
                page.reload(wait_until="domcontentloaded", timeout=60000)
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] run_whatsapp_send: exception swallowed", exc_info=True)
                pass

        if not logged_in:
            result["errors"].append(
                "等待登录超时：#side/聊天列表 未出现（疑似页面加载失败或连接被重置）"
            )
            return result
        _success("登录成功（已检测到聊天列表）")

        site_outage_file = _get_latest_site_outage()
        files_to_send = [site_outage_file] if site_outage_file else []

        for group in GROUPS:
            try:
                _search_and_open(page, group)

                pairs = list(zip(PHOTOS, CAPTIONS))
                if len(PHOTOS) != len(CAPTIONS):
                    _warn(f"图片数({len(PHOTOS)})与备注数({len(CAPTIONS)})不一致，已按较短一方配对")
                _fast_send_photos(page, pairs)

                for file_path in files_to_send:
                    _fast_send_file(page, file_path)

                result["groups_sent"].append(group)
                _info(f"群 [{group}] 发送完毕")
                time.sleep(3.0)

            except Exception as e:
                err = f"群组 {group} 发送失败: {e}"
                _error(err)
                result["errors"].append(err)

        _wait_for_last_message_sent(page, timeout=30)

        result["success"] = len(result["errors"]) == 0

    except Exception as e:
        result["errors"].append(str(e))
        _error(f"Task failed: {e}")

    finally:
        if browser:
            time.sleep(CLOSE_DELAY)
            browser.close()
        if pw:
            pw.stop()

    elapsed = time.time() - start_time
    result["elapsed_seconds"] = round(elapsed, 2)
    _info(f"Done: {len(result['groups_sent'])} groups, {elapsed:.2f}s")
    return result


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:whatsapp_service>: exception swallowed", exc_info=True)
        pass
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')

    # 启动前日志辅助排查
    print(f"当前扫描目录: {SITE_OUTAGE_DIR.resolve()}")
    print(f"扫描到的图片列表: {PHOTOS}")

    result = run_whatsapp_send()
    print(f"\nWhatsApp 发送结果: {'成功' if result['success'] else '失败'}")
    print(f"已发送群组: {result['groups_sent']}")
    if result['errors']:
        print(f"错误: {result['errors']}")
    print(f"耗时: {result['elapsed_seconds']}s")