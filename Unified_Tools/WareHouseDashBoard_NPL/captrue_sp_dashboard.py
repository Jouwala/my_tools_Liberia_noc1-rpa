from playwright.sync_api import sync_playwright
from PIL import Image, ImageEnhance, ImageChops
import time
import os
import sys

# 解决控制台编码问题
sys.stdout.reconfigure(encoding="utf-8")


# ========= 图像处理模块：裁掉纯色边框 =========
def trim_uniform_border(img, tolerance=6):
    bg = img.crop((0, 0, 1, 1))
    diff = ImageChops.difference(img, bg)
    diff = diff.convert("L")
    diff = diff.point(lambda x: 255 if x > tolerance else 0)
    bbox = diff.getbbox()
    if bbox:
        return img.crop(bbox)
    return img


# ========= 图像处理模块：PNG → JPG 自适应压缩 =========
def png_to_jpg_adaptive(png_path, jpg_path, target_kb=600, is_2k=False):
    img = Image.open(png_path)
    if img.mode == "RGBA":
        bg_color = img.getpixel((5, 5))[:3]
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

    # 1. 初始加载，增加超时时间
    print(f"[调试] 正在访问: {url}")
    try:
        page.goto(url, wait_until="networkidle", timeout=90000)
    except Exception as e:
        print(f"[错误] 页面加载失败: {e}")
        # 尝试等待 domcontentloaded
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        print("[调试] 已使用 domcontentloaded 模式加载")

    # 打印页面标题用于调试
    print(f"[调试] 页面标题: {page.title()}")

    # 2. 等待业务容器加载，增加超时
    print("[调试] 等待 #details-body 元素...")
    try:
        page.wait_for_selector("#details-body", timeout=60000)
        print("[调试] #details-body 元素已找到")
    except Exception as e:
        print(f"[警告] 等待 #details-body 超时: {e}")
        # 打印页面当前 HTML 用于调试
        print(f"[调试] 页面 HTML 前2000字符: {page.content()[:2000]}")

    # 3. 核心改进：等待地图渲染关键元素 (Canvas)
    # 地图库通常会创建 canvas，确保它已出现在 DOM 中
    try:
        page.wait_for_selector("canvas", timeout=15000)
    except:
        print("[警告] 未检测到 Canvas 元素，请检查地图组件是否正常触发")

    # 4. 注入样式并解除滚动限制
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

    # 5. 额外渲染缓冲：地图动画（飞入、瓦片渐变）通常需要 2-3 秒
    time.sleep(3)

    # 执行截图
    page.locator("body").screenshot(path=output_path)
    browser.close()


# ========= 主执行入口 =========
def main(headless=True):
    url = "http://localhost/sp_dashboard/"

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
    print(f"🎉 全部完成！")
    print(f"标准版: {jpg_1080} | 高清版: {jpg_2k}")
    print("=" * 30)


if __name__ == "__main__":
    main(headless=True)
