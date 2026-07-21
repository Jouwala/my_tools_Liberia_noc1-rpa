# ==========================================================
# Part 1A: 基础配置
# ==========================================================
from playwright.sync_api import sync_playwright, TimeoutError
from pathlib import Path
import traceback, time, os

# Configuration
GROUPS = ["15638281623"]
PHOTOS = [r"D:\Outage sharing\ERA.png", r"D:\Outage sharing\ALL.png"]
CAPTIONS = ["*ERA*", "*ALL*"]
FILES = [r"D:\Outage sharing\ERA.xlsx", r"D:\Outage sharing\ALL.xlsx"]
HEADLESS, MAX_RETRY, WAIT_TIMEOUT = False, 3, 30000
USER_DATA_DIR, DEBUG_DIR, WHATSAPP_URL = "whatsapp_session", "debug", "https://web.whatsapp.com"
Path(DEBUG_DIR).mkdir(exist_ok=True)

# Selectors
SELECTORS = {
    "SEARCH_BOX": ['#side div[contenteditable="true"]', '#side [role="textbox"]'],
   "ATTACH": [
        'div[data-icon="plus"]',
        'span[data-icon="plus"]',
        'button[aria-label="Attach"]',
        'button[aria-label="附加"]',
        'div[aria-label="Attach"]' # 新增：兼容 div 容器
    ],
    "IMAGE_INPUT": ['input[type=file][accept*="image"]', 'input[type=file]'],
    "FILE_INPUT": ['input[type=file]'],
    "CAPTION": ['div[data-testid="conversation-compose-box-input"]'],
    "PREVIEW": ['div[role="dialog"]', '[aria-label="Media preview"]'],
    "SEND": ['span[data-icon="send"]', 'div[aria-label="Send"]', 'div[aria-label="发送"]'],
    "MAIN": ["#main"]
}

# ==========================================================
# Part 1B: 公共工具
# ==========================================================
# ==========================================================
# Part 1B: 公共工具 (Corrected)
# ==========================================================
def info(msg): print(f"[INFO ] {msg}")
def success(msg): print(f"[ OK  ] {msg}")
def warn(msg): print(f"[WARN ] {msg}")
def error(msg): print(f"[ERROR] {msg}") # Added missing function

def save_debug(page, name):
    try: page.screenshot(path=f"{DEBUG_DIR}/{name}.png", full_page=True)
    except: pass

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

def in_preview(page):
    # Added missing function to detect Media Preview dialog
    selectors = ["div[role=dialog]", "[aria-label='Media preview']"]
    for s in selectors:
        try:
            page.locator(s).wait_for(timeout=500)
            return True
        except: pass
    return False

def start_browser():
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch_persistent_context(
        USER_DATA_DIR, headless=HEADLESS, args=["--start-maximized"], no_viewport=True
    )
    page = browser.new_page()
    page.goto(WHATSAPP_URL, wait_until="domcontentloaded")
    page.locator("#side").wait_for(timeout=60000)
    success("登录成功")
    return playwright, browser, page

def find_first(page, key):
    for selector in SELECTORS[key]:
        try:
            loc = page.locator(selector)
            if loc.count() > 0: return loc.first
        except: pass
    return None

def find_all(page, key):
    for selector in SELECTORS[key]:
        try:
            loc = page.locator(selector)
            if loc.count() > 0: return loc
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
    time.sleep(2)
    page.keyboard.press("Enter")
    time.sleep(2)
    
    # 确保进入了聊天窗口
    if not page.locator(SELECTORS["MAIN"][0]).is_visible():
        raise Exception("未能进入聊天窗口")
    success(f"成功进入: {contact_name}")

# ==========================================================


# Part 3: 图片与文字发送 (解耦版)
# ==========================================================

@retry
def send_image_only(page, image_path):
    """仅上传图片，不填写备注，直接点击发送"""
    info(f"上传图片: {os.path.basename(image_path)}")
    
    # 1. 点击附件
    btn = find_first(page, "ATTACH")
    if not btn: raise Exception("找不到附件按钮")
    btn.click(force=True)
    time.sleep(2)
    
    # 2. 上传
    input_el = find_first(page, "IMAGE_INPUT")
    if not input_el: raise Exception("找不到上传控件")
    input_el.set_input_files(image_path)
    time.sleep(4) # 等待加载
    
    # 3. 找发送按钮 (此时在预览界面)
    send_btn = page.locator('[data-testid="conversation-compose-btn-send"]')
    if send_btn.is_visible():
        send_btn.click(force=True)
    else:
        page.keyboard.press("Enter")
    
    time.sleep(3) # 等待发送动画完成
    success("图片发送成功")

@retry
def send_text_message(page, text):
    """直接发送文字，不需要点+号"""
    info(f"发送备注: {text}")
    
    # 直接定位聊天主界面的输入框
    chat_box = page.locator('#main div[contenteditable="true"][data-tab="10"]')
    if not chat_box.is_visible():
        chat_box = page.locator('div[title="输入消息"]') # 备用选择器
    
    chat_box.click()
    chat_box.fill(text)
    chat_box.press("Enter")
    time.sleep(1)
    success("文字发送成功")

# ==========================================================
# Part 5: Main

# ==========================================================
# Part 5: Main
# ==========================================================
def main():
    p, browser, page = start_browser()
    
    try:
        for group in GROUPS:
            search_and_open(page, group)
            
            # 发送图片和对应的备注
            for photo, cap in zip(PHOTOS, CAPTIONS):
                if os.path.exists(photo):
                    # 1. 先发图（不带备注）
                    send_image_only(page, photo)
                    # 2. 后发备注（作为独立消息）
                    send_text_message(page, cap)
                else: warn(f"找不到照片: {photo}")
            
            # 发送文件
            for file in FILES:
                if os.path.exists(file):
                    send_document(page, file)
                else: warn(f"找不到文件: {file}")
                
    except Exception as e:
        error(f"任务中断: {e}")
        traceback.print_exc()
    finally:
        browser.close()
        p.stop()
if __name__ == "__main__":
    main()