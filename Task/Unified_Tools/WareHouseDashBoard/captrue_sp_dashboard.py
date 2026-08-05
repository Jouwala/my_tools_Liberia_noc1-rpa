from playwright.sync_api import sync_playwright
from PIL import Image, ImageEnhance, ImageChops
import time
import os
import sys

# 解决控制台编码问题
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore


# ========= 图像处理模块：裁掉纯色边框 =========
def trim_uniform_border(img, tolerance=6):
    bg = img.crop((0, 0, 1, 1))
    diff = ImageChops.difference(img, bg)
    diff = diff.convert("L")
    diff = diff.point(lambda x: 255 if x > tolerance else 0)  # type: ignore
    bbox = diff.getbbox()
    if bbox:
        return img.crop(bbox)
    return img


# ========= 图像处理模块：PNG → JPG 自适应压缩 =========
def png_to_jpg_adaptive(png_path, jpg_path, target_kb=600, is_2k=False):
    img = Image.open(png_path)
    if img.mode == "RGBA":
        pixel = img.getpixel((5, 5))
        bg_color = pixel[:3] if isinstance(pixel, tuple) else (255, 255, 255)  # type: ignore
        bg = Image.new("RGB", img.size, bg_color)
        bg.paste(img, mask=img.split()[3])
        img = bg
    else:
        img = img.convert("RGB")

    # 裁剪白边/底边
    img = trim_uniform_border(img)
    # 轻度降色处理
    img = ImageEnhance.Color(img).enhance(0.8)

    actual_target = target_kb * 2 if is_2k else target_kb
    tmp = jpg_path + ".tmp"

    for q in range(85, 65, -3):
        img.save(
            tmp,
            "JPEG",
            quality=q,
            subsampling=0 if is_2k else 2,
            progressive=True,
            optimize=True
        )
        size = os.path.getsize(tmp) // 1024
        if size <= actual_target:
            break

    if os.path.exists(jpg_path):
        os.remove(jpg_path)
    os.replace(tmp, jpg_path)
    print(f"[压缩] {jpg_path} 完成 | 最终大小: {os.path.getsize(jpg_path) // 1024} KB")


# ========= 登录模块 =========
def try_fill(page, selectors, value, field_name):
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() > 0:
            try:
                locator.first.fill(value, timeout=3000)
                print(f"[登录] 已填写{field_name}: {selector}")
                return True
            except Exception:
                continue
    return False


def try_click(page, selectors, btn_name):
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() > 0:
            try:
                locator.first.click(timeout=3000)
                print(f"[登录] 已点击{btn_name}: {selector}")
                return True
            except Exception:
                continue
    return False


def login_if_needed(page, username="admin", password="admin123"):
    print("[登录] 检查是否需要登录...")

    # 等页面先初步稳定
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    time.sleep(1)  # 减少到1秒

    # 如果目标内容已经存在，说明可能已经登录
    if page.locator("#details-body").count() > 0:
        print("[登录] 检测到 #details-body，疑似已登录，跳过登录")
        return

    # 检查是否有强制登录遮罩层
    print("[登录] 检查是否有强制登录遮罩层...")
    login_overlay = page.locator("#login-required-overlay")
    if login_overlay.count() > 0 and login_overlay.is_visible():
        print("[登录] 检测到强制登录遮罩层，点击登录按钮...")
        try:
            # 点击遮罩层上的登录按钮
            login_overlay.locator("button:has-text('Login')").click()
            time.sleep(0.5)  # 减少等待时间
            print("[登录] 已点击遮罩层登录按钮")
        except Exception as e:
            print(f"[登录] 点击遮罩层登录按钮失败：{e}")

    # 等待登录模态框显示（index.html 使用 .show 类控制显示）
    print("[登录] 等待登录模态框显示...")
    try:
        # 等待登录模态框出现并有 .show 类
        page.wait_for_selector("#login-modal.show", timeout=5000)  # 减少到5秒
        print("[登录] 检测到登录模态框已显示")
    except Exception:
        print("[登录] 未检测到登录模态框，尝试等待输入框出现")
        # 如果模态框没有 .show 类，直接等待输入框
        try:
            page.wait_for_selector("#login-username", timeout=3000)  # 减少到3秒
            print("[登录] 检测到用户名输入框")
        except Exception:
            print("[登录] 超时未检测到登录表单，可能已登录或页面结构不同")
            print(f"[调试] 当前标题：{page.title()}")
            print(f"[调试] 当前地址：{page.url}")
            return

    # 针对 index.html 的登录表单选择器
    username_selectors = [
        'input[id="login-username"]',
        'input[name="username"]',
        'input[type="text"][placeholder*="username"]',
        'input[type="text"][placeholder*="Username"]'
    ]

    password_selectors = [
        'input[id="login-password"]',
        'input[name="password"]',
        'input[type="password"][placeholder*="password"]',
        'input[type="password"][placeholder*="Password"]'
    ]

    login_button_selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Login")',
        'button:has-text("登录")',
        '#login-form button'
    ]

    user_ok = try_fill(page, username_selectors, username, "用户名")
    pwd_ok = try_fill(page, password_selectors, password, "密码")

    if not user_ok:
        raise Exception("未找到用户名输入框，请检查登录页选择器")
    if not pwd_ok:
        raise Exception("未找到密码输入框，请检查登录页选择器")

    # 点击登录
    clicked = False
    try:
        # SPA 应用登录不会触发导航，直接点击
        clicked = try_click(page, login_button_selectors, "登录按钮")
    except Exception as e:
        print(f"[登录] 点击按钮失败：{e}")
        clicked = False

    if not clicked:
        # 尝试回车提交
        print("[登录] 未找到明显登录按钮，尝试按 Enter 提交")
        page.keyboard.press("Enter")

    # 等待登录后的页面稳定
    try:
        page.wait_for_load_state("networkidle", timeout=10000)  # 减少到10秒
    except Exception:
        pass

    time.sleep(1)  # 减少到1秒

    # 登录完成后再次确认
    if page.locator("#details-body").count() > 0:
        print("[登录] 登录成功，已进入业务页面")
    else:
        print("[登录] 登录后暂未检测到 #details-body，继续后续等待逻辑")
        # 尝试等待业务元素出现
        try:
            page.wait_for_selector("#details-body", timeout=5000)  # 减少到5秒
            print("[登录] 等待后检测到 #details-body，登录成功")
        except Exception:
            print("[登录] 超时未检测到 #details-body，可能登录失败")


# ========= 浏览器自动化模块：截图逻辑 =========
def capture_screenshot(p, url, output_path, scale_factor, headless):
    print(f"[启动] 浏览器采样率: {scale_factor}x | 正在等待页面加载...")

    browser = p.chromium.launch(
        headless=headless,
        args=['--disable-blink-features=AutomationControlled']
    )

    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        device_scale_factor=scale_factor
    )

    page = context.new_page()

    # 监听控制台日志
    page.on("console", lambda msg: print(f"[浏览器控制台] {msg.type}: {msg.text}"))

    # 1. 初始加载
    print(f"[调试] 正在访问: {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
    except Exception as e:
        print(f"[错误] 页面加载失败: {e}")
        browser.close()
        raise

    print(f"[调试] 页面标题: {page.title()}")

    # 2. 登录
    login_if_needed(page, username="admin", password="admin123")

    # 3. 等待业务容器加载
    print("[调试] 等待 #details-body 元素...")
    try:
        page.wait_for_selector("#details-body", timeout=10000)  # 减少到10秒
        print("[调试] #details-body 元素已找到")
    except Exception as e:
        print(f"[警告] 等待 #details-body 超时: {e}")
        # 不再打印 HTML，直接继续

    # 4. 等待地图渲染关键元素
    try:
        page.wait_for_selector("canvas", timeout=5000)  # 减少到5秒
        print("[调试] Canvas 元素已找到")
    except Exception:
        print("[警告] 未检测到 Canvas 元素，请检查地图组件是否正常触发")

    # 5. 注入样式并解除滚动限制
    page.evaluate("""
    () => {
        document.documentElement.style.background = '#0f172a';
        document.body.style.background = '#0f172a';
        const tbody = document.getElementById('details-body');
        if (tbody) {
            let el = tbody;
            while (el && el !== document.body) {
                el.style.overflow = 'visible';
                el.style.maxHeight = 'none';
                el = el.parentElement;
            }
        }
    }
    """)

    # 6. 额外渲染缓冲（减少到1秒）
    time.sleep(1)

    # 执行截图
    page.locator("body").screenshot(path=output_path)
    browser.close()


# ========= 主执行入口 =========
def main(headless=True):
    url = "http://localhost/sp_lbr/"

    png_1080 = "temp_1080.png"
    png_2k = "temp_2k.png"
    jpg_1080 = "sp_dashboard_1080.jpg"
    jpg_2k = "sp_dashboard_2k.jpg"

    with sync_playwright() as p:
        # 1. 生成 1080P 标准图
        print("\n--- 正在生成 1080P 版本 ---")
        capture_screenshot(p, url, png_1080, 1, headless)
        png_to_jpg_adaptive(png_1080, jpg_1080, target_kb=600, is_2k=False)

        # 2. 生成 2K 高清图
        print("\n--- 正在生成 2K 高清版本 ---")
        capture_screenshot(p, url, png_2k, 2, headless)
        png_to_jpg_adaptive(png_2k, jpg_2k, target_kb=1200, is_2k=True)

    # 清理临时文件
    for f in (png_1080, png_2k):
        if os.path.exists(f):
            os.remove(f)

    print("\n" + "=" * 30)
    print("🎉 全部完成！")
    print(f"标准版: {jpg_1080} | 高清版: {jpg_2k}")
    print("=" * 30)


if __name__ == "__main__":
    main(headless=False)
