# ==========================================================
# Part 1A: 基础配置
# ==========================================================
from playwright.sync_api import sync_playwright, TimeoutError, Page
from pathlib import Path
import traceback, time, os, subprocess, glob

# Configuration
GROUPS = ["15638281623"]
PHOTOS = [
    r"D:\01_RPA\Site_outage\screenshots\ERA.png",
    r"D:\01_RPA\Site_outage\screenshots\REGULAR.png",
    r"D:\01_RPA\Site_outage\screenshots\ALL.png",
]
CAPTIONS = ["*ERA*", "*REGULAR*", "*ALL*"]

SITE_OUTAGE_DIR = r"D:\01_RPA\Site_outage"
def get_latest_site_outage():
    pattern = os.path.join(SITE_OUTAGE_DIR, "*site_outage_*")
    files = [f for f in glob.glob(pattern) if f.endswith(('.xlsx', '.xls'))]
    if not files:
        return None
    return max(files, key=lambda f: os.path.getmtime(f))

FILES = [get_latest_site_outage()]
HEADLESS, MAX_RETRY, WAIT_TIMEOUT = False, 3, 30000
USER_DATA_DIR, DEBUG_DIR, WHATSAPP_URL = "whatsapp_session", "debug", "https://web.whatsapp.com"
Path(DEBUG_DIR).mkdir(exist_ok=True)

# Selectors
SELECTORS = {
    "SEARCH_BOX": ['#side div[contenteditable="true"]', '#side [role="textbox"]'],
    "MAIN": ["#main"]
}

# ==========================================================
# Part 1B: 公共工具
# ==========================================================
def info(msg): print(f"[INFO ] {msg}")
def success(msg): print(f"[ OK  ] {msg}")
def warn(msg): print(f"[WARN ] {msg}")
def error(msg): print(f"[ERROR] {msg}")

def retry(func):
    def wrapper(*args, **kwargs):
        last = None
        for i in range(MAX_RETRY):
            try: return func(*args, **kwargs)
            except Exception as e: 
                last = e
                warn(f"Retry {i+1}/{MAX_RETRY}")
        raise last
    return wrapper

def start_browser():
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch_persistent_context(
        USER_DATA_DIR,
        executable_path=r"D:\01_RPA\chrome-win\chrome-win\chrome.exe",
        headless=HEADLESS,
        args=["--start-maximized"],
        no_viewport=True
    )
    page = browser.new_page()
    page.goto(WHATSAPP_URL, wait_until="domcontentloaded")
    page.locator("#side").wait_for(timeout=180000)
    success("登录成功")
    return playwright, browser, page

def find_first(page, key):
    for selector in SELECTORS[key]:
        try:
            loc = page.locator(selector)
            if loc.count() > 0: return loc.first
        except: pass
    return None

# ==========================================================
# Part 2: 搜索联系人
# ==========================================================
@retry
def search_and_open(page, contact_name):
    info(f"正在搜索: {contact_name}")
    search_box = find_first(page, "SEARCH_BOX")
    if not search_box: raise Exception("找不到搜索框")
    
    search_box.click()
    search_box.fill("")
    search_box.fill(contact_name)
    time.sleep(0.5)
    page.keyboard.press("Enter")
    time.sleep(0.8)
    
    if not page.locator(SELECTORS["MAIN"][0]).is_visible():
        raise Exception("未能进入聊天窗口")
    success(f"成功进入: {contact_name}")

# ==========================================================
# Part 3: 高速剪贴板 API
# ==========================================================
def copy_image_to_clipboard(image_path):
    """极速写入图片到剪贴板"""
    abs_path = os.path.abspath(image_path)
    ps_cmd = (
        f"Add-Type -AssemblyName System.Windows.Forms; "
        f"$img = [System.Drawing.Image]::FromFile('{abs_path}'); "
        f"[System.Windows.Forms.Clipboard]::SetImage($img); "
        f"$img.Dispose()"
    )
    subprocess.run(["powershell", "-STA", "-Command", ps_cmd], check=True)

def copy_text_to_clipboard(text):
    """极速写入文本到剪贴板"""
    ps_cmd = f"Set-Clipboard -Value '{text}'"
    subprocess.run(["powershell", "-Command", ps_cmd], check=True)

def copy_file_to_clipboard(file_path):
    """极速写入文件句柄到剪贴板"""
    abs_path = os.path.abspath(file_path)
    ps_cmd = (
        f"Add-Type -AssemblyName System.Windows.Forms; "
        f"$files = '{abs_path}'; "
        f"$col = New-Object System.Collections.Specialized.StringCollection; "
        f"$col.Add($files); "
        f"[System.Windows.Forms.Clipboard]::SetFileDropList($col)"
    )
    subprocess.run(["powershell", "-STA", "-Command", ps_cmd], check=True)

# ==========================================================
# Part 4: 极限连击发送逻辑 (Copy -> Paste -> Enter 无缝衔接)
# ==========================================================
def fast_send_photos(page, photo_caption_pairs):
    """连发模式：贴图 -> 贴字 -> 回车，零顿挫"""
    page.locator('#main').click()
    
    for i, (photo, cap) in enumerate(photo_caption_pairs):
        if not os.path.exists(photo):
            warn(f"跳过不存在图片: {photo}")
            continue

        info(f"⚡ [爆发发送] ({i+1}/{len(photo_caption_pairs)}) {os.path.basename(photo)}")
        
        # 1. 贴图片
        copy_image_to_clipboard(photo)
        page.keyboard.press("Control+v")
        time.sleep(0.3) # 预留媒体弹窗生成时间

        # 2. 贴备注
        if cap:
            copy_text_to_clipboard(cap)
            page.keyboard.press("Control+v")
            time.sleep(0.1)

    # 3. 立即按回车发送
    page.keyboard.press("Enter")
    time.sleep(0.3) # 释放输入框焦点准备下一条

def fast_send_file(page, file_path):
    """极速发送文件"""
    if not file_path or not os.path.exists(file_path):
        return
        
    info(f"⚡ [爆发发送] 文件: {os.path.basename(file_path)}")
    copy_file_to_clipboard(file_path)
    
    page.locator('#main').click()
    page.keyboard.press("Control+v")
    time.sleep(0.5)
    #page.keyboard.press("Enter")
    #time.sleep(0.3)

# ==========================================================
# Part 5: 最终单次状态校验
# ==========================================================
def wait_for_last_message_sent(page: Page, timeout=120):
    """全自动校验最后一条消息是否被服务端接收/送达"""
    info("🔍 所有任务完成，正在等待服务器回执确认...")
    
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
                success("✓✓ 最终确认：全套已送达/已读")
                return True
            if last_msg.locator(SINGLE_CHECK_SELECTOR).count() > 0:
                success("✓ 最终确认：全套已发送至服务器")
                return True
        time.sleep(0.5)

    warn(f"⚠️ 状态确认超时，请人工检查界面！")
    return False

# ==========================================================
# Part 6: 主流程
# ==========================================================
def main():
    p, browser, page = start_browser()
    
    try:
        for group in GROUPS:
            # 1. 切换群聊
            search_and_open(page, group)
            
            # 2. 极限连击：发送所有图片+备注
            pairs = list(zip(PHOTOS, CAPTIONS))
            fast_send_photos(page, pairs)
            
            # 3. 极限连击：发送文件
            for file in FILES:
                fast_send_file(page, file)
            page.keyboard.press("Enter")
            print( "所有文件发送完成")
        time.sleep(5.0)    
        # 4. 全流程完成后，只在最后校验 1 次
        wait_for_last_message_sent(page, timeout=60)
                
    except Exception as e:
        error(f"任务中断: {e}")
        traceback.print_exc()
    finally:
        browser.close()
        p.stop()

if __name__ == "__main__":
    main()