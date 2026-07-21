# ==========================================================
# Part 1A: 基础配置
# ==========================================================
from playwright.sync_api import sync_playwright, TimeoutError, Page
from pathlib import Path
import traceback, time, os, subprocess, glob

# Configuration
GROUPS = ["15638281623"]
PHOTOS = [r"D:\01_RPA\Site_outage\screenshots\ERA.png","D:\01_RPA\Site_outage\screenshots\REGULAR.png", r"D:\01_RPA\Site_outage\screenshots\ALL.png"]
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
        USER_DATA_DIR,
        executable_path=r"D:\01_RPA\chrome-win\chrome-win\chrome.exe",
        headless=HEADLESS,
        args=["--start-maximized"],
        no_viewport=True
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
# Part 3: 剪贴板工具函数
# ==========================================================

def wait_for_message_sent11(page: Page):
    """
    等待消息发送完成：
    1. 等待时钟/loading图标消失
    2. 确认出现勾号图标
    如果检测失败则回退为固定等待，避免阻塞流程
    """
    try:
        # 找到聊天区域中最后一条消息的气泡
        last_message = page.locator("div[role='row']").last
        last_message.wait_for(state="visible", timeout=10000)

        # 1. 确保时钟图标消失 (loading 状态结束)
        clock_icon = last_message.locator(
            "span[data-icon='msg-time'], span[data-icon='clock'], "
            "span[data-icon='msg-clock']"
        )
        try:
            clock_icon.wait_for(state="hidden", timeout=30000)
        except Exception:
            pass  # 时钟图标可能本身不存在，忽略

        # 2. 确认出现了勾号 (表示已发送到服务器)
        check_mark = last_message.locator(
            "span[data-icon='msg-check'], span[data-icon='msg-dblcheck'], "
            "span[data-icon='msg-read'], span[data-icon='msg-delivered'], "
            "span[data-icon='check'], span[data-icon='dblcheck']"
        )
        check_mark.wait_for(state="visible", timeout=15000)
        info("消息发送确认成功")

    except Exception:
        # 回退方案：等待固定时间，避免阻塞流程
        warn("未检测到发送确认图标，等待 5 秒后继续")
        time.sleep(5)

def wait_for_message_sent(page: Page):
    # 1. 放宽选择器，直接寻找所有的 row 元素，不要限定 class
    # 如果页面里连 div[role='row'] 都找不到，说明聊天窗口都没加载出来
    last_message = page.locator("div[role='row']").last
    
    # 2. 防御性检查：检查是否找到了元素，避免直接调用 inner_html 导致的超时
    if last_message.count() == 0:
        print("[DEBUG] 未找到任何消息行，请检查聊天窗口是否已打开。")
        return

    # 3. 打印当前能抓到的最后一条消息，看看它到底长什么样
    # 这里使用 first 而不是 inner_html，避免直接读取大量 DOM 导致的超时
    try:
        # 获取该行的文本内容，用于确认是否是你要的那条消息
        text = last_message.inner_text(timeout=2000)
        print(f"[DEBUG] 识别到最后一条消息内容: {text[:50]}")
    except Exception as e:
        print(f"[DEBUG] 获取消息内容失败: {e}")
        return

    # 4. 尝试寻找发送状态图标
    # 在该行内搜索所有代表状态的图标
    success_icons = last_message.locator("span[data-icon='msg-check'], span[data-icon='msg-dblcheck']")
    
    # 轮询等待，不要直接 wait_for，改用 count 判断
    # 给 10 秒时间等待图标出现
    import time
    start_time = time.time()
    while time.time() - start_time < 4:
        if success_icons.count() > 0:
            print("图片发送完成 (检测到发送成功图标)。")
            return
        time.sleep(0.5)
        
    print("[WARN] 等待图标超时，可能发送状态未更新，跳过。")

def copy_image_to_clipboard(image_path):
    """用 PowerShell 将图片复制到系统剪贴板"""
    abs_path = os.path.abspath(image_path)
    ps_cmd = (
        f"Add-Type -AssemblyName System.Windows.Forms; "
        f"$img = [System.Drawing.Image]::FromFile('{abs_path}'); "
        f"[System.Windows.Forms.Clipboard]::SetImage($img)"
    )
    subprocess.run(["powershell", "-STA", "-Command", ps_cmd], check=True, timeout=10)

def copy_text_to_clipboard(text):
    """用 PowerShell 将文本复制到系统剪贴板"""
    ps_cmd = f"Set-Clipboard -Value '{text}'"
    subprocess.run(["powershell", "-Command", ps_cmd], check=True, timeout=10)

# ==========================================================
# Part 4: 逐组粘贴图片+备注，每组粘贴后立即回车发送
# ==========================================================

@retry
def paste_and_send_one_by_one(page, photo_caption_pairs):
    """
    逐组粘贴图片+备注，每组完成后按回车发送并等待发送确认
    photo_caption_pairs: [(image_path, caption), ...]
    """
    for i, (photo, cap) in enumerate(photo_caption_pairs):
        if not os.path.exists(photo):
            warn(f"找不到照片，跳过: {photo}")
            continue

        # 1. 点击聊天区域获取焦点
        page.locator('#main').click()
        time.sleep(0.5)

        # 2. 复制图片到剪贴板并粘贴
        info(f"[{i+1}] 粘贴图片: {os.path.basename(photo)}")
        copy_image_to_clipboard(photo)
        page.keyboard.press("Control+v")
        time.sleep(2)

        # 3. 复制备注文本到剪贴板并粘贴
        info(f"[{i+1}] 粘贴备注: {cap}")
        copy_text_to_clipboard(cap)
        page.keyboard.press("Control+v")
        time.sleep(1)

        # 4. 按回车发送当前这组
        page.keyboard.press("Enter")
        wait_for_message_sent(page)
        success(f"[{i+1}] 发送完成: {os.path.basename(photo)}")

    success(f"全部发送完成，共 {len(photo_caption_pairs)} 组")

@retry
def send_document(page, file_path):
    """通过剪贴板粘贴发送文件"""
    info(f"发送文件: {os.path.basename(file_path)}")
    abs_path = os.path.abspath(file_path)
    # 将文件路径复制到剪贴板（以文件对象形式）
    ps_cmd = (
        f"Add-Type -AssemblyName System.Windows.Forms; "
        f"$files = '{abs_path}'; "
        f"$collection = New-Object System.Collections.Specialized.StringCollection; "
        f"$collection.Add($files); "
        f"[System.Windows.Forms.Clipboard]::SetFileDropList($collection)"
    )
    subprocess.run(["powershell", "-STA", "-Command", ps_cmd], check=True, timeout=10)
    time.sleep(1)

    # 点击聊天区域并粘贴
    page.locator('#main').click()
    time.sleep(0.5)
    page.keyboard.press("Control+v")
    time.sleep(3)

    # 按回车发送
    page.keyboard.press("Enter")
    wait_for_message_sent(page)
    success(f"文件发送完成: {os.path.basename(file_path)}")

# ==========================================================
# Part 5: Main
# ==========================================================
def main():
    p, browser, page = start_browser()
    
    try:
        for group in GROUPS:
            search_and_open(page, group)
            
            # 逐组粘贴图片+备注并发送
            pairs = list(zip(PHOTOS, CAPTIONS))
            paste_and_send_one_by_one(page, pairs)
            
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