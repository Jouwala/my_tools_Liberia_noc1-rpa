"""
WhatsApp 消息发送服务
集成 sent_whatsapp_v2.py - 通过 Playwright 自动发送图片/文件到 WhatsApp 群组
"""
import os
import sys
import time
import glob
import subprocess
import sys
import logging
from pathlib import Path

logger = logging.getLogger("whatsapp_service")

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# ========== 配置 ==========
#GROUPS = ["*OLR ZTE Quality Control*", "*OLR ZTE Incidents Mgt*"]
GROUPS = ["test123", "Test234"]

PHOTOS = [
    r"d:\01_RPA\Task\my_app\data\site_outage\ERA.png",
    r"d:\01_RPA\Task\my_app\data\site_outage\REGULAR.png",
    r"d:\01_RPA\Task\my_app\data\site_outage\ALL.png",
]
CAPTIONS = ["*ERA*", "*REGULAR*", "*ALL*"]

SITE_OUTAGE_DIR = r"d:\01_RPA\Task\my_app\data\site_outage"

HEADLESS = False
MAX_RETRY = 3
WAIT_TIMEOUT = 180000

USER_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "whatsapp_session")
DEBUG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "scheduler_logs")
WHATSAPP_URL = "https://web.whatsapp.com"

CHROME_PATH = r"D:\01_RPA\chrome-win\chrome-win\chrome.exe"

SELECTORS = {
    "SEARCH_BOX": ['#side div[contenteditable="true"]', '#side [role="textbox"]'],
    "MAIN": ["#main"],
    "CAPTION_INPUT": [
        'div[aria-label="添加小标题"]',
        'div[aria-label="Add a caption"]',
        'div[contenteditable="true"][data-tab="10"]',
        'div._ak1r div[contenteditable="true"]'
    ]
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
            pass
    return None


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


def _fast_send_photos(page, photo_caption_pairs):
    """确保单图单备注精准配对发送"""
    page.locator('#main').click(force=True)

    for i, (photo, cap) in enumerate(photo_caption_pairs):
        if not os.path.exists(photo):
            _warn(f"跳过不存在图片: {photo}")
            continue

        _info(f"发送图片 ({i+1}/{len(photo_caption_pairs)}): {os.path.basename(photo)} -> {cap}")

        # 1. 写入图片到剪贴板并粘贴
        _copy_image_to_clipboard(photo)
        page.keyboard.press("Control+v")

        # 2. 等待预览界面弹窗出现，然后直接键盘输入备注
        time.sleep(2)
        page.keyboard.type(cap)

    # 3. 按 Enter 发送所有图片+备注
    page.keyboard.press("Enter")

    # 4. 等待发送完成
    time.sleep(2.0)


def _fast_send_file(page, file_path):
    """极速发送文件"""
    if not file_path or not os.path.exists(file_path):
        return

    _info(f"发送文件: {os.path.basename(file_path)}")
    _copy_file_to_clipboard(file_path)

    page.locator('#main').click(force=True)
    page.keyboard.press("Control+v")
    time.sleep(1.5)
    page.keyboard.press("Enter")
    time.sleep(1.5)


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
    """
    WhatsApp 消息发送任务：
    1. 启动 Playwright 浏览器
    2. 登录 WhatsApp Web
    3. 逐个群组发送图片 + 文件

    Returns: dict
    """
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
        result["errors"].append("缺少 playwright 依赖，请运行: pip install playwright && playwright install chromium")
        return result

    Path(DEBUG_DIR).mkdir(exist_ok=True)

    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch_persistent_context(
            USER_DATA_DIR,
            executable_path=CHROME_PATH,
            headless=HEADLESS,
            args=["--start-maximized", "--prevent-first-run-default-browser-prompts"],
            no_viewport=True,
        )
        page = browser.new_page()
        page.goto(WHATSAPP_URL, wait_until="domcontentloaded", timeout=180000)
        _info("等待 WhatsApp Web 加载，请扫码登录（如有需要）...")
        page.locator("#side").wait_for(timeout=180000)
        _success("登录成功")

        # 获取文件列表
        site_outage_file = _get_latest_site_outage()
        files_to_send = [site_outage_file] if site_outage_file else []

        for group in GROUPS:
            try:
                # 1. 切换群聊
                _search_and_open(page, group)

                # 2. 发送图片+备注（单图单备注循环）
                pairs = list(zip(PHOTOS, CAPTIONS))
                _fast_send_photos(page, pairs)

                # 3. 发送文件
                for file_path in files_to_send:
                    _fast_send_file(page, file_path)

                result["groups_sent"].append(group)
                _info(f"群 [{group}] 发送完毕")
                time.sleep(3.0)

            except Exception as e:
                err = f"群组 {group} 发送失败: {e}"
                _error(err)
                result["errors"].append(err)

        # 4. 全流程校验
        _wait_for_last_message_sent(page, timeout=30)

        result["success"] = len(result["errors"]) == 0

    except Exception as e:
        result["errors"].append(str(e))
        _error(f"Task failed: {e}")

    finally:
        if browser:
            time.sleep(60.0)
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
        pass
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')

    result = run_whatsapp_send()
    print(f"\nWhatsApp 发送结果: {'成功' if result['success'] else '失败'}")
    print(f"已发送群组: {result['groups_sent']}")
    if result['errors']:
        print(f"错误: {result['errors']}")
    print(f"耗时: {result['elapsed_seconds']}s")
