# ==========================================================
# Part 1A: 基础配置
# ==========================================================
from playwright.sync_api import sync_playwright, TimeoutError, Page
from pathlib import Path
import traceback, time, os, subprocess, glob

# Configuration
GROUPS = ["*OLR ZTE Quality Control*", "*OLR ZTE Incidents Mgt*"]
#GROUPS = ["test123", "Test234"]
PHOTOS = [
    r"E:\01_RPA\Site_outage\screenshots\ERA.png",
    r"E:\01_RPA\Site_outage\screenshots\REGULAR.png",
    r"E:\01_RPA\Site_outage\screenshots\ALL.png",
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
HEADLESS, MAX_RETRY, WAIT_TIMEOUT = False, 3, 180000
USER_DATA_DIR, DEBUG_DIR, WHATSAPP_URL = "whatsapp_session", "debug", "https://web.whatsapp.com"
Path(DEBUG_DIR).mkdir(exist_ok=True)

# Selectors
SELECTORS = {
    "SEARCH_BOX": ['#side div[contenteditable="true"]', '#side [role="textbox"]'],
    "MAIN": ["#main"],
    # 媒体预览弹窗中的文字输入框选择器
    "CAPTION_INPUT": [
        'div[aria-label="添加小标题"]', 
        'div[aria-label="Add a caption"]',
        'div[contenteditable="true"][data-tab="10"]',
        'div._ak1r div[contenteditable="true"]'
    ]
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
        executable_path=r"E:\01_RPA\chrome-win\chrome-win\chrome.exe",
        headless=HEADLESS,
        args=["--start-maximized","--prevent-first-run-default-browser-prompts"],
        no_viewport=True
    )
    page = browser.new_page()
    page.goto(WHATSAPP_URL, wait_until="domcontentloaded")
    info("等待 WhatsApp Web 加载，请扫码登录（如有需要）...")
    page.locator("#side").wait_for(timeout=180000)
    success("登录成功")
    
    #try:
        #cdp = page.context.new_cdp_session(page)
        #wid = cdp.send("Browser.getWindowForTarget")["windowId"]
        #cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "minimized"}})
        #info("已最小化窗口到任务栏")
    #except Exception as e:
        #warn(f"最小化失败: {e}")
    return playwright, browser, page

def find_first(page, key):
    for selector in SELECTORS[key]:
        try:
            loc = page.locator(selector)
            if loc.count() > 0 and loc.first.is_visible(): 
                return loc.first
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
    page.keyboard.press("Control+a")
    page.keyboard.press("Backspace")
    search_box.fill(contact_name)
    time.sleep(2)
    page.keyboard.press("Enter")
    time.sleep(2)
    
    if not page.locator(SELECTORS["MAIN"][0]).is_visible():
        raise Exception("未能进入聊天窗口")
    success(f"成功进入: {contact_name}")

# ==========================================================
# Part 3: 剪贴板 API
# ==========================================================
def copy_image_to_clipboard(image_path):
    abs_path = os.path.abspath(image_path)
    ps_cmd = (
        f"Add-Type -AssemblyName System.Windows.Forms; "
        f"$img = [System.Drawing.Image]::FromFile('{abs_path}'); "
        f"[System.Windows.Forms.Clipboard]::SetImage($img); "
        f"$img.Dispose()"
    )
    subprocess.run(["powershell", "-STA", "-Command", ps_cmd], check=True)

def copy_file_to_clipboard(file_path):
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
# Part 4: 准确图片与备注匹配发送
# ==========================================================
def fast_send_photos(page, photo_caption_pairs):
    """确保单图单备注精准配对发送"""
    page.locator('#main').click(force=True)
    
    for i, (photo, cap) in enumerate(photo_caption_pairs):
        if not os.path.exists(photo):
            warn(f"跳过不存在图片: {photo}")
            continue

        info(f"⚡ [精确发送] ({i+1}/{len(photo_caption_pairs)}) {os.path.basename(photo)} -> {cap}")
        
        # 1. 写入图片到剪贴板并粘贴
        copy_image_to_clipboard(photo)
        page.keyboard.press("Control+v")
        
        # 2. 等待预览界面弹窗出现
        time.sleep(2)
        page.keyboard.type(cap)
        
        

    # 4. 按 Enter 发送当前单张图片+备注
    page.keyboard.press("Enter")
        
    # 5. 给系统留出发送并关闭预览层的时间，防止影响下一张
    time.sleep(2.0)

def fast_send_file(page, file_path):
    """极速发送文件"""
    if not file_path or not os.path.exists(file_path):
        return
        
    info(f"⚡ [发送文件] {os.path.basename(file_path)}")
    copy_file_to_clipboard(file_path)
    
    page.locator('#main').click(force=True)
    page.keyboard.press("Control+v")
    time.sleep(1.5)
    page.keyboard.press("Enter")
    time.sleep(1.5)

# ==========================================================
# Part 5: 最终状态校验
# ==========================================================
def wait_for_last_message_sent(page: Page, timeout=60):
    info("🔍 正在等待服务器回执确认...")
    
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
            
            # 2. 发送图片+备注 (单图单备注循环)
            pairs = list(zip(PHOTOS, CAPTIONS))
            fast_send_photos(page, pairs)
            
            # 3. 发送文件
            for file in FILES:
                fast_send_file(page, file)
                
            info(f"群 [{group}] 发送完毕")
            time.sleep(3.0)
            
        # 4. 全流程校验
        wait_for_last_message_sent(page, timeout=30)
                
    except Exception as e:
        error(f"任务中断: {e}")
        traceback.print_exc()
    finally:
        time.sleep(60.0)
        browser.close()
        p.stop()

if __name__ == "__main__":
    main()
