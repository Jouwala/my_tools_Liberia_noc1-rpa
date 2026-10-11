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


class WhatsAppSessionBlocked(Exception):
    """WhatsApp 会话层异常（弹窗拦截 / 登录态丢失），与普通业务异常区分开。

    2026-10-11：早间 05:55~08:25 连续 7 次发送失败，错误均为
    ``Locator.click: Timeout 30000ms exceeded``，Playwright 日志里可见
    ``<div role="dialog" aria-modal="true" ...> intercepts pointer events``
    —— 搜索框被一个模态层盖住，点击永远打不进去。这类失败**不是**业务数据问题，
    而是会话/UI 状态问题，重试前必须先自愈（见 auto_retry 的 SESSION_HEAL_KEYS）。
    单独建类是为了让上层（worker / auto_retry）能按类型分流，而不用去猜错误字符串。
    """


# 会话类失败的日志特征：命中即说明「页面在、但点不动 / 等不到登录态」。
# auto_retry 用同一组关键字识别并触发自愈重试（两处共用一套判断，避免分叉）。
SESSION_BLOCKED_KEYS = (
    "intercepts pointer events",
    "等待登录超时",
    "WhatsAppSessionBlocked",
)

# ========== 配置（环境变量优先，便于 Windows 部署） ==========
# 图片/数据文件所在目录
DEFAULT_DIR = r"D:\01_RPA\Task\my_app\backend\services\data\site_outage"
SITE_OUTAGE_DIR = Path(os.environ.get("SITE_OUTAGE_DIR", DEFAULT_DIR))

# 群组：逗号分隔，例如 "test123,Test234"
_GROUPS_ENV = os.environ.get("WHATSAPP_GROUPS", "test123,Test234")
GROUPS = [g.strip() for g in _GROUPS_ENV.split(",") if g.strip()]

# 图片获取逻辑（原规则不变，抽成函数：import 时算一次，任务每次执行时再算一次）
def _collect_photos_and_captions():
    """按原规则收集「图片清单 + 对应备注」。"""
    _photos_env = os.environ.get("WHATSAPP_PHOTOS", "").strip()
    if _photos_env:
        photos = [p.strip() for p in _photos_env.split(",") if p.strip()]
    else:
        valid_extensions = ("*.png", "*.PNG", "*.jpg", "*.JPG", "*.jpeg", "*.JPEG")
        found_photos = set()  # 使用 set 自动去重，防止 Windows 环境重复匹配
        for ext in valid_extensions:
            found_photos.update(SITE_OUTAGE_DIR.glob(ext))
    
        photos = sorted(
            str(p) for p in found_photos
            if "debug" not in p.name.lower()
        )

    # 备注：与 photos 一一对应；不足则用文件名（去扩展名）
    _captions_env = os.environ.get("WHATSAPP_CAPTIONS", "").strip()
    if _captions_env:
        captions = [c.strip() for c in _captions_env.split(",") if c.strip()]
    else:
        captions = [f"*{Path(p).stem}*" for p in photos]
    return photos, captions


PHOTOS, CAPTIONS = _collect_photos_and_captions()

HEADLESS = os.environ.get("WHATSAPP_HEADLESS", "false").lower() in ("1", "true", "yes")
MAX_RETRY = int(os.environ.get("WHATSAPP_MAX_RETRY", "3"))
WAIT_TIMEOUT = int(os.environ.get("WHATSAPP_WAIT_TIMEOUT", "180000"))
CLOSE_DELAY = float(os.environ.get("WHATSAPP_CLOSE_DELAY", "28"))

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


# 文档预览就绪 / 发送按钮候选（WhatsApp Web 各版本选择器可能不同，逐个尝试）
_DOC_PREVIEW_SELECTORS = (
    'div[aria-label="添加小标题"]',
    'div[aria-label="Add a caption"]',
    'div[contenteditable="true"][data-tab="10"]',
)
_SEND_BUTTON_SELECTORS = (
    "span[data-icon='send']",
    "span[data-icon='wds-ic-send-filled']",
    "span[data-testid='send']",
    "div[aria-label='Send']",
    "button[aria-label='Send']",
    "div[role='button'][aria-label*='Send' i]",
    # 中文界面（本机 WhatsApp Web 是中文）：aria-label 形如「发送 1 项所选内容」。
    # 缺这两条时旧代码一个都命中不了，只能退化成按回车——而文档预览页上回车无效
    # （2026-09-15 SP Details Report 1.5MB 因此没发出去，见 _fast_send_file 注释）。
    "div[role='button'][aria-label*='发送']",
    "button[aria-label*='发送']",
)


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
        # [System.Drawing.Image] 属于 System.Drawing，不是 System.Windows.Forms。
        # 缺这一句会报 "Unable to find type [System.Drawing.Image]" → $img 为 null
        # → SetImage 抛 "Value cannot be null" → exit 1，整个剪贴板/粘贴路径失效。
        f"Add-Type -AssemblyName System.Windows.Forms; "
        f"Add-Type -AssemblyName System.Drawing; "
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


def _snapshot_session(page, tag: str) -> str | None:
    """会话异常时落一张截图 + 一段 DOM 摘要，供事后定位「到底卡在哪个弹窗」。

    2026-10-11 的事故复盘只能靠 Playwright 的 retry 日志反推弹窗，看不到真实界面。
    这里把当时的界面固化成磁盘证据（PNG + 一段含 aria-modal 文案的 txt），
    下一次同类故障可直接肉眼确认，不必再猜。落盘失败不影响主流程。
    """
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = Path(DEBUG_DIR)
    shot = None
    try:
        base.mkdir(parents=True, exist_ok=True)
        img_path = base / f"wa_session_{tag}_{ts}.png"
        page.screenshot(path=str(img_path), timeout=8000)
        shot = str(img_path)
        _warn(f"会话异常快照已保存: {img_path}")
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _snapshot_session.screenshot: swallowed", exc_info=True)

    # DOM 摘要：把当前可见的 dialog / 遮罩层文案抓出来，PNG 之外再留文字证据
    try:
        dialogs = page.locator("div[role='dialog'], [aria-modal='true']")
        n = dialogs.count()
        if n > 0:
            lines = [f"# 会话异常 DOM 摘要 tag={tag} at={ts}", f"# 命中 {n} 个 dialog/aria-modal 节点"]
            for i in range(min(n, 5)):
                try:
                    txt = (dialogs.nth(i).inner_text(timeout=1500) or "").strip().replace("\n", " ")
                    lines.append(f"[{i}] {txt[:300]}")
                except Exception:
                    lines.append(f"[{i}] <读取超时>")
            txt_path = base / f"wa_session_{tag}_{ts}.txt"
            txt_path.write_text("\n".join(lines), encoding="utf-8")
            _warn(f"会话异常 DOM 摘要已保存: {txt_path}")
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _snapshot_session.dom: swallowed", exc_info=True)

    return shot


def _dismiss_blocking_dialog(page, max_rounds: int = 3) -> bool:
    """关闭盖在聊天列表/搜索框上的模态层。返回是否已无遮挡。

    检测 ``role=dialog[aria-modal=true]`` 或 Playwright 报的遮罩层，逐个尝试：
    点关闭按钮（X / 关闭 / Close）→ 按 Escape → 点遮罩外空白。
    每轮结束后复检，全部清掉才算成功。
    """
    for rnd in range(max_rounds):
        try:
            blockers = page.locator("div[role='dialog'][aria-modal='true'], [aria-modal='true']")
            n = blockers.count()
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _dismiss_blocking_dialog.count: swallowed", exc_info=True)
            return True
        if n == 0:
            return True

        _warn(f"检测到 {n} 个模态弹窗拦截（第 {rnd+1}/{max_rounds} 轮），尝试关闭")
        closed = False
        try:
            close_btn = page.locator(
                "div[role='dialog'] button[aria-label*='关闭'], "
                "div[role='dialog'] button[aria-label*='Close'], "
                "div[role='dialog'] [data-icon='x'], "
                "div[role='dialog'] [data-icon='exit']"
            )
            if close_btn.count() > 0 and close_btn.first.is_visible(timeout=1200):
                close_btn.first.click(timeout=2500)
                closed = True
                _info("已点击弹窗关闭按钮")
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _dismiss_blocking_dialog.close: swallowed", exc_info=True)

        if not closed:
            try:
                page.keyboard.press("Escape")
                closed = True
                _info("已按 Escape 尝试关闭弹窗")
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _dismiss_blocking_dialog.esc: swallowed", exc_info=True)

        if not closed:
            try:
                page.mouse.click(5, 5)  # 点左上角空白，避开弹窗主体
                _info("已点击遮罩外空白尝试关闭弹窗")
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _dismiss_blocking_dialog.blank: swallowed", exc_info=True)

        page.wait_for_timeout(600)

    # 复检：仍有模态层则判定未消除
    try:
        return page.locator("div[role='dialog'][aria-modal='true'], [aria-modal='true']").count() == 0
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _dismiss_blocking_dialog.recheck: swallowed", exc_info=True)
        return True


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

    # 2026-10-11：先清掉可能盖在搜索框上的模态层。此前直接 click，被遮罩挡住时
    # 会干等 30s×重试次数（Playwright 报 intercepts pointer events）。
    if not _dismiss_blocking_dialog(page):
        _snapshot_session(page, "search_blocked")
        raise WhatsAppSessionBlocked(
            "搜索框被模态弹窗遮挡，无法点击（intercepts pointer events）"
        )

    search_box = _find_first(page, "SEARCH_BOX")
    if not search_box:
        raise Exception("找不到搜索框")

    try:
        search_box.click(timeout=8000)
    except Exception as e:
        # 点击异常也可能是「点击瞬间又被弹窗盖上」，留证据再抛出会话类异常
        _snapshot_session(page, "search_click_fail")
        raise WhatsAppSessionBlocked(f"搜索框点击失败: {e}") from e

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


def _pick_file_input(page, want_image: bool):
    """在附件菜单展开后的 input[type=file] 中按 accept 挑选正确的那个。

    WhatsApp Web 同一时刻通常存在多个隐藏 input：一个 accept 含 ``image``
    （照片/视频），另一个 accept 为空或 ``*/*``（文档）。发 Excel 时若误选图片
    input，前端会**静默丢弃**该文件：既不出预览也不报错，随后的 Enter 打在空气上，
    表现为「只发出图片、文件没到群」。
    """
    inputs = page.locator('input[type="file"]')
    n = inputs.count()
    if n == 0:
        return None
    fallback = None
    for i in range(n):
        el = inputs.nth(i)
        try:
            acc = (el.get_attribute("accept") or "").lower()
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _pick_file_input: exception swallowed", exc_info=True)
            acc = ""
        _info(f"  file input[{i}] accept={acc!r}")
        if fallback is None:
            fallback = el
        is_image_input = "image" in acc
        if want_image and (is_image_input or acc == "" or "*/*" in acc):
            return el
        if (not want_image) and (not is_image_input):
            return el
    return inputs.last if want_image else fallback


def _msg_count(page) -> int:
    try:
        return page.locator("div[role='row'], div[data-testid='msg-container']").count()
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _msg_count: exception swallowed", exc_info=True)
        return -1


_MSG_ROW_SEL = "div[role='row'], div[data-testid='msg-container']"


def _verify_file_sent(page, file_name: str, timeout: int = 20) -> bool:
    """确认群里确实出现了该文档消息。

    WhatsApp 给文档消息的下载入口 title/aria-label 形如 ``下载"<文件名>"`` /
    ``Download "<file name>"``。用它做判据比「数消息条数」可靠——聊天列表是虚拟
    列表，DOM 节点数不随新消息线性增长（实测新增 2 条消息后计数仍是 42）。

    ⚠️ **必须限定在消息行内**（2026-09-15 修复）：粘贴文件后 WhatsApp 会弹出
    **文档预览页**，页眉同样带文件名；只按「页面上出现文件名」判断，会把还没发出去的
    预览页当成「已发出」——SP Details Report 1.5MB 就是这样被判成功、实际没进群。
    """
    safe = (file_name or "").replace('"', "").replace("\\", "")
    if not safe:
        return False
    js = """
    (args) => {
      const [needle, rowSel] = args;
      for (const s of ['div[title]', 'span[title]', 'div[aria-label]', 'a[title]']) {
        for (const el of document.querySelectorAll(s)) {
          const v = el.getAttribute('title') || el.getAttribute('aria-label') || '';
          if (v.includes(needle) && el.closest(rowSel)) return true;
        }
      }
      return false;
    }
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if page.evaluate(js, [safe, _MSG_ROW_SEL]):
                return True
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _verify_file_sent: exception swallowed", exc_info=True)
        page.wait_for_timeout(1000)
    return False


def _attachment_visible(page, file_name: str) -> bool:
    """输入框/预览页里是否已出现该文件的附件（文件名出现在 title/aria-label 上）。"""
    safe = (file_name or "").replace('"', "").replace("\\", "")
    if not safe:
        return False
    try:
        return bool(page.evaluate("""
        (needle) => {
          for (const s of ['div[title]', 'span[title]', 'div[aria-label]', 'a[title]']) {
            for (const el of document.querySelectorAll(s)) {
              const v = el.getAttribute('title') || el.getAttribute('aria-label') || '';
              if (v.includes(needle)) return true;
            }
          }
          return false;
        }
        """, safe))
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _attachment_visible: exception swallowed", exc_info=True)
        return False


def _wait_attachment_ready(page, file_name: str, timeout: int = 25) -> bool:
    """等「文件已挂上、可以发送」：附件预览出现 **且** 发送按钮可见。

    ⚠️ 2026-09-15 修复的根因就在这里：剪贴板路径原来 ``Ctrl+V`` 后固定等 2s 就回车。
    实测粘贴后 WhatsApp 弹出**文档预览页**，文件名元素出现时刻在 +0.4s ~ +2s 之间
    浮动（大文件更慢）——回车打空后附件留在预览页里没发出去，而当时的校验又把预览页
    上的文件名当成「已发出」，于是任务报成功、群里什么都没有。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _attachment_visible(page, file_name) and _find_send_button(page) is not None:
            return True
        page.wait_for_timeout(300)
    return False


def _find_send_button(page):
    """返回当前可见的发送按钮 Locator（中文界面靠 '发送' 选择器命中），找不到返回 None。"""
    for sel in _SEND_BUTTON_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible(timeout=500):
                return loc
        except Exception:
            continue
    return None


def _fast_send_file(page, file_path):
    """发送单个文件（Excel 等文档）：优先附件 input，失败再剪贴板。

    2026-09-09 修复「Excel 发不出去，群里只收到图片」：
      1) 按 accept 挑「文档 input」，不再盲取 ``inputs.last``——页面上那个
         唯一的 input 是 ``accept="image/*"``，xlsx 会被前端静默丢弃；
      2) set_input_files 后必须等到预览/发送按钮出现（大文件前端生成预览要时间），
         否则 Enter 打在空气上；
      3) **不再无条件 ``sent = True``**：原实现只要没抛异常就算成功，于是假成功后
         跳过剪贴板兜底，Excel 实际没发出却报 success。现在未确认发出就走兜底。

    发送后用 ``_verify_file_sent`` 核对群里是否真出现该文档（严格限定消息行内）。
    返回值 = 是否确认送达；**不会**因核对失败而自动重发（避免群里出现重复文件），
    但会把 False 交给调用方（run_whatsapp_send 会记进 errors，让失败在任务结果里可见）。
    """
    if not file_path or not os.path.exists(file_path):
        return False

    name = os.path.basename(file_path)
    _info(f"发送文件: {name}")
    page.locator("#main").click(force=True)

    sent = False
    attach = _find_attach_button(page)
    if attach:
        try:
            attach.click(timeout=5000)
            page.wait_for_timeout(400)
            target = _pick_file_input(page, want_image=False)
            if target is None:
                _warn("未找到任何 file input")
            else:
                target.set_input_files(file_path)
                # 等文档预览就绪：先等 caption 框，再等发送按钮（大文件可能要几秒）
                ready = None
                for sel in _DOC_PREVIEW_SELECTORS + _SEND_BUTTON_SELECTORS:
                    try:
                        loc = page.locator(sel).first
                        loc.wait_for(state="visible", timeout=15000)
                        ready = loc
                        _info(f"  文档预览就绪: {sel}")
                        break
                    except Exception:
                        continue
                if ready is None:
                    _warn("等不到文档预览/发送按钮，判定为未发送")
                else:
                    btn = None
                    for sel in _SEND_BUTTON_SELECTORS:
                        try:
                            loc = page.locator(sel).first
                            if loc.is_visible(timeout=2000):
                                btn = loc
                                break
                        except Exception:
                            continue
                    if btn is not None:
                        try:
                            btn.click(timeout=5000)
                        except Exception as e:
                            _warn(f"点击发送按钮失败({e})，改用 Enter")
                            page.keyboard.press("Enter")
                    else:
                        page.keyboard.press("Enter")
                    page.wait_for_timeout(2000)
                    if _verify_file_sent(page, os.path.basename(file_path)):
                        _success(f"文件已发出（群内已核对到）: {os.path.basename(file_path)}")
                        sent = True
                    else:
                        _warn(f"未在群内核对到 {os.path.basename(file_path)}，判定未发出")
        except Exception as e:
            _warn(f"file input 发文件失败: {e}")
            try:
                page.keyboard.press("Escape")
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _fast_send_file: exception swallowed", exc_info=True)
                pass

    if not sent:
        _info("改用剪贴板发送文件")
        _copy_file_to_clipboard(file_path)
        page.locator("#main").click(force=True)
        page.keyboard.press("Control+v")

        # 2026-09-15 修复：粘贴后 WhatsApp 弹出文档预览页，预览未就绪就回车会打空，
        # 附件留在预览页里没发出去（SP Details Report 1.5MB 就这么丢的）。
        # 改为：等附件预览 + 发送按钮就绪 → 点发送按钮（中文界面回车无效）→ 严格校验。
        if not _wait_attachment_ready(page, name, timeout=25):
            _warn(f"粘贴后等不到附件预览/发送按钮，未发送: {name}（请人工核对）")
            return False

        btn = _find_send_button(page)
        if btn is not None:
            try:
                btn.click(timeout=5000)
            except Exception as e:
                _warn(f"点击发送按钮失败({e})，改用 Enter")
                page.keyboard.press("Enter")
        else:
            page.keyboard.press("Enter")
        page.wait_for_timeout(2000)
        if _verify_file_sent(page, name):
            _success(f"剪贴板文件已发出（群内已核对到）: {name}")
            return True
        _warn(f"剪贴板发送后仍未在群内核对到 {name}（不重发，请人工核对）")
        return False

    return sent


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
def run_whatsapp_send(photos=None, captions=None, files=None, groups=None) -> dict:
    """发送图片/文件到 WhatsApp 群组。

    缺省行为与历史版本一致：扫 SITE_OUTAGE_DIR 图片 + 最新 Site Outage 文件，
    发送到 GROUPS。photos/captions/files/groups 显式传入时覆盖对应项
    （供其他报表任务复用同一套发送机制，如 sp_online_report_send）。
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
            # 2026-10-11：登录态超时同样是会话层问题，落快照后再退出，
            # 让 08:25 那种「等 3 分钟还是 #side 没出现」的场景有界面证据。
            _snapshot_session(page, "login_timeout")
            # 关键：把会话类失败标记出来，auto_retry 据此在重试前自愈（而非原样重跑）
            result["errors"].append(
                "WhatsAppSessionBlocked: 等待登录超时：#side/聊天列表 未出现"
                "（疑似页面加载失败或连接被重置）"
            )
            return result
        _success("登录成功（已检测到聊天列表）")

        # 每次执行重新收集图片清单：worker 是长驻进程，模块级 PHOTOS 只是 import 时的
        # 快照，截图任务（site_outage_screenshot）在 worker 启动之后新产出的图片会漏发
        # （2026-09-14 09:02 新增的 COOL.png 就因此整轮没发出去）。
        if photos is None:
            send_photos, send_captions = _collect_photos_and_captions()
        else:
            send_photos = [str(p) for p in photos]
            send_captions = list(captions) if captions is not None else CAPTIONS
        if files is None:
            site_outage_file = _get_latest_site_outage()
            files_to_send = [site_outage_file] if site_outage_file else []
        else:
            files_to_send = [str(f) for f in files]

        for group in (GROUPS if groups is None else groups):
            try:
                _search_and_open(page, group)

                pairs = list(zip(send_photos, send_captions))
                if len(send_photos) != len(send_captions):
                    _warn(f"图片数({len(send_photos)})与备注数({len(send_captions)})不一致，已按较短一方配对")
                _fast_send_photos(page, pairs)

                for file_path in files_to_send:
                    # 2026-09-15：文件发送改为「确认送达才算成功」。以前 _fast_send_file
                    # 只记日志不返回结果，文件没发出去时任务照样报成功（SP Details
                    # Report 1.5MB 就静默丢了一天）。
                    if not _fast_send_file(page, file_path):
                        result["errors"].append(
                            f"群 {group} 文件未确认送达: {os.path.basename(file_path)}"
                        )

                result["groups_sent"].append(group)
                _info(f"群 [{group}] 发送完毕")
                time.sleep(3.0)

            except Exception as e:
                # 会话类异常在错误串里显式带上标记，供 auto_retry 识别并自愈重试；
                # 其余业务异常维持原文，避免误判为会话问题。
                if isinstance(e, WhatsAppSessionBlocked):
                    err = f"WhatsAppSessionBlocked: 群组 {group} 发送失败: {e}"
                else:
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