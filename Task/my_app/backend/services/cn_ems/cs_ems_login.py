# -*- coding: utf-8 -*-
"""
cs_ems_login.py — ZTE NetNumen U31 EMS 桌面客户端 通用登录脚本（零 RPA 依赖）

设计原则（来自反复踩坑后的结论）：
  * U31 是 Java Swing 应用（窗口类 SunAwtFrame），本机未装 Java Access Bridge，
    pywinauto 的 uia/win32 后端只能看到窗口外壳，看不到内部 JTextField/JPasswordField。
    => 因此「找窗口 + 激活」用 pywinauto，「内部点击/输入」必须用坐标 + 键鼠模拟。
  * 输入链路最可靠的组合：
      1) 登录窗默认焦点在密码框、用户名在上方带默认值；故直接填密码（无需点击），再 Shift+Tab 回上方用户名框填。完全不依赖坐标点击，规避焦点误落
      2) 强制切英文输入法（LoadKeyboardLayout 00000409），绕开中文 IME 拦截
      3) 清空用 Ctrl+A + Backspace×N（Java Swing 对 Home/Shift+End 响应不可靠，
         暴力退格 100% 清空，无论是否真的选中）
      4) 文本走剪贴板粘贴（pyperclip.copy + Ctrl+V），不逐字符打字，
         彻底消除中文 IME 把口令字符转成乱码（如把字母打成全角）
  * 密码框点击一次 Java 事件队列可能吞掉，故点两次 + 长等待确保焦点转移。
  * 提供 --calibrate（截图标注坐标点自检）与 --fill-only（只填不点 OK，肉眼确认后手动点），
    在不浪费登录尝试次数的前提下验证落点。

依赖安装（系统 Python 3.12）：
    C:/Users/ZTEEMS/AppData/Local/Programs/Python/Python312/python.exe -m pip install pywinauto pyautogui pyperclip

用法：
    python cs_ems_login.py                 # 启动客户端 + 登录 + 进主界面
    python cs_ems_login.py --no-launch     # 客户端已开，只登录
    python cs_ems_login.py --fill-only     # 只填用户名/密码，不点 OK（安全验证用）
    python cs_ems_login.py --calibrate     # 截图标注各坐标点，确认对准输入框
    python cs_ems_login.py --debug         # 每步操作后截图到 debug_shots/

凭据优先级：环境变量 EMS_USER / EMS_PASS > ems_config.json > 脚本内默认
"""

import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import time

import pyautogui
from pywinauto import Desktop

# ---------- 默认配置（可被 ems_config.json / 环境变量覆盖） ----------
# 2026-09-27：原先此处硬编码 "password": "Tool123"（明文，已入库）。
# 口令改为只用环境变量 EMS_PASS（或 ems_config.json 的 password 键，该文件同批已清空）。
DEFAULT_CONFIG = {
    "client_exe": r"D:\ems1\ems1\ums-client\client.exe",
    "user": "oss",
    "password": "",
    "login_title_re": "Login - NetNumen U31",
    "main_title_re": "NetNumen U31 Unified Management System - Client",
    "launch_wait": 3,            # 启动后等待秒数（仅作为初次兜底，真正等窗口靠 login_timeout 轮询）
    "login_timeout": 20,         # 等登录窗口出现的最长秒数
    "main_timeout": 20,          # 登录后等主界面的最长秒数
    "post_login_wait": 10,       # 点 OK 后等主界面加载的秒数
    "menu_path": ["Performance", "Query Template Management"],
    "backend": "uia",
    # 各控件在「登录窗口客户区」内的百分比坐标 (x%, y%)，自适应不同分辨率/DPI
    # 顺序（从上到下）：用户名 → 密码 → 服务器地址(下拉)
    "coords": {
        "username":  (0.35, 0.42),
        "password":  (0.35, 0.55),
        "btn_ok":    (0.70, 0.88),
        "btn_cancel":(0.88, 0.88),
    },
    # 菜单导航坐标（需通过 --menu-calibrate 校准）
    # top_menu_pct: "Performance" 顶菜单项在【主窗口客户区】内的百分比坐标 (x%, y%)
    # submenu_offset_px: 从 top_menu 点击点到目标子菜单项中心的像素偏移 (dx, dy)
    #   dy ≈ (item_index + 1) * item_height + item_height/2，典型 item_height=23px
    #   Query Template Management 是 Performance 下第 4 项 (index=3)，故 dy≈103
    "menu_coords": {
        "top_menu_pct": [0.30, 0.035],
        "submenu_offset_px": [5, 103],
    },
}

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ems_config.json")


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    # 合并文件配置
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                file_cfg = json.load(f)
            for k, v in file_cfg.items():
                cfg[k] = v
        except Exception as e:
            print(f"[!] 读取配置文件失败，使用内置默认: {e}", file=sys.stderr)
    # 环境变量覆盖凭据（不落盘明文）
    cfg["user"] = os.environ.get("EMS_USER", cfg["user"])
    cfg["password"] = os.environ.get("EMS_PASS", cfg["password"])
    return cfg


# ---------- 窗口查找 / 激活 ----------
def find_login_window(cfg, timeout=None):
    """按标题正则查找 U31 登录窗口。UIA 优先，失败回退 Win32。"""
    timeout = timeout or cfg["login_timeout"]
    title_re = cfg["login_title_re"]
    for backend in (cfg.get("backend", "uia"), "win32"):
        try:
            w = Desktop(backend=backend).window(title_re=title_re)
            if w.exists(timeout=timeout):
                return w
        except Exception:
            continue
    return None


def find_main_window(cfg):
    """查找 U31 主界面窗口。处理多窗口同名歧义（选可见的那个）。"""
    title_re = cfg["main_title_re"]
    for backend in (cfg.get("backend", "uia"), "win32"):
        try:
            # 加 active_only=True 避免匹配到不可见的残留窗口
            w = Desktop(backend=backend).window(title_re=title_re)
            if w.exists(timeout=cfg.get("main_timeout", 5) if backend == cfg.get("backend", "uia") else 3):
                return w
        except Exception as e:
            # ElementAmbiguousError：多个同名窗口，手动遍历挑可见的
            err_name = type(e).__name__
            if "Ambiguous" in err_name or "ambiguous" in str(e).lower():
                try:
                    for candidate in Desktop(backend=backend).windows():
                        t = (candidate.window_text() or "").strip()
                        if re.search(title_re, t, re.IGNORECASE) and candidate.is_visible():
                            return candidate
                except Exception:
                    pass
            continue
    return None


def activate_window(win):
    """将窗口置前并获得其客户区矩形。返回 (left, top, right, bottom)。"""
    try:
        # 仅当窗口最小化时才恢复；直接 SW_RESTORE 会把【已最大化】窗口还原成小窗，
        # 导致后续键盘导航时窗口状态被改变（用户反馈：登录后最大化窗口被改小）。
        if ctypes.windll.user32.IsIconic(win.handle):
            ctypes.windll.user32.ShowWindow(win.handle, 9)  # SW_RESTORE=9
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetForegroundWindow(win.handle)
    except Exception:
        pass
    try:
        win.set_focus()
    except Exception:
        pass
    time.sleep(0.5)
    r = win.rectangle()
    return (r.left, r.top, r.right, r.bottom)


def rect_to_pyautogui_region(rect):
    """pyautogui.screenshot(region=) 需要 (left, top, width, height)。"""
    left, top, right, bottom = rect
    return (left, top, right - left, bottom - top)


def pct_to_xy(px, py, rect):
    """把窗口内的百分比坐标换算成屏幕绝对坐标。"""
    left, top, right, bottom = rect
    w = right - left
    h = bottom - top
    return int(left + px * w), int(top + py * h)


def click_at(rect, key, cfg):
    """在窗口 rect 内按配置的百分比坐标点击。"""
    if key not in cfg["coords"]:
        raise KeyError(f"coords 缺少 {key}")
    px, py = cfg["coords"][key]
    sx, sy = pct_to_xy(px, py, rect)
    print(f"    click {key} -> screen ({sx}, {sy})  [窗口内 {px:.2f},{py:.2f}]")
    pyautogui.click(sx, sy)


# ---------- 输入相关 ----------
def _switch_to_english_ime():
    """强制切换到英文键盘布局，避免后续键鼠输入被中文 IME 拦截。"""
    try:
        user32 = ctypes.windll.user32
        # 00000409 = US English；KLF_ACTIVATE = 0x00000001
        hkl = user32.LoadKeyboardLayoutW("00000409", 0x00000001)
        if hkl:
            user32.ActivateKeyboardLayout(hkl, 0)
    except Exception:
        pass


def _brute_clear_field(max_chars=50):
    """暴力清空当前焦点输入框：Ctrl+A 全选 + Backspace×N 兜底。

    Java Swing 的 JTextField/JPasswordField 可能不响应 Ctrl+A 或 Home/Shift+End，
    所以用 Backspace 暴力删除作为 100% 可靠的兜底（删够次数就一定是空的）。
    """
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.15)
    for _ in range(max_chars):
        pyautogui.press("backspace")
        time.sleep(0.02)
    time.sleep(0.15)


def type_text(text, clear_first=True):
    """用剪贴板粘贴输入文本（绕过 IME），先暴力清空已有内容。"""
    _switch_to_english_ime()
    time.sleep(0.2)

    if clear_first:
        _brute_clear_field(max_chars=50)

    # 剪贴板粘贴（绕过中文 IME 转义）
    try:
        import pyperclip
        pyperclip.copy(text)
    except ImportError:
        # fallback: 直接写 Windows 剪贴板
        proc = subprocess.Popen(["clip"], stdin=subprocess.PIPE,
                                creationflags=0x08000000)  # CREATE_NO_WINDOW
        proc.communicate(input=text.encode("utf-8"))
    time.sleep(0.15)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.2)


# ---------- 核心流程 ----------
def do_login(cfg, debug_dir=None, click_ok=True):
    """找到登录窗口 → 激活 → 填用户名/密码 → (可选)点 OK。

    click_ok=False 时只填写不点 OK，用于验证落点正确性（节省登录尝试次数）。
    返回窗口对象。
    """
    print("[*] 查找登录窗口...")
    win = find_login_window(cfg)
    if not win:
        raise RuntimeError(
            f"未找到登录窗口(标题匹配: {cfg['login_title_re']})。"
            f" 请确认 U31 客户端已启动并停在登录界面。"
        )
    print(f"[*] 找到登录窗口: '{win.window_text()}'")

    rect = activate_window(win)
    region = rect_to_pyautogui_region(rect)
    print(f"[*] 窗口矩形: {rect}  (尺寸: {rect[2]-rect[0]}x{rect[3]-rect[1]})")

    def _debug_save(name):
        if debug_dir:
            path = os.path.join(debug_dir, f"debug_{name}.png")
            pyautogui.screenshot(region=region).save(path)
            print(f"    [DEBUG] 截图保存: {path}")

    # 初始状态截图
    _debug_save("00_before_input")

    # 关键背景（用户确认）：U31 登录窗口默认焦点就在【密码框】，用户名在上方且带
    # 上次输入的默认值。因此无需点击任何框即可直接填密码；填完用 Shift+Tab 回到
    # 上方相邻的用户名框再填。完全不依赖坐标点击，规避"用户名误填进密码框"。
    print(f"[*] 输入密码: {'*' * len(cfg['password'])}（窗口默认焦点已在密码框）")
    type_text(cfg["password"])
    time.sleep(0.3)
    _debug_save("01_after_password")

    print(f"[*] 输入用户名: {cfg['user']}（Shift+Tab 回到上方用户名框）")
    pyautogui.hotkey("shift", "tab")
    time.sleep(0.5)
    pyautogui.hotkey("shift", "tab")
    time.sleep(0.5)
    type_text(cfg["user"])
    time.sleep(0.3)
    _debug_save("02_after_username")

    # 第三步：(可选)坐标点 OK
    if click_ok:
        print("[*] 点击 OK 登录...")
        click_at(rect, "btn_ok", cfg)
    else:
        print("[*] --fill-only 模式：已填写用户名/密码，未点击 OK。请肉眼确认后手动点 OK。")

    return win


def calibrate(cfg):
    """截图登录窗口并标注各坐标点，用于自检坐标是否对准输入框。"""
    print("[*] 查找登录窗口（calibrate 模式）...")
    win = find_login_window(cfg)
    if not win:
        print(f"[!] 未找到登录窗口，请先打开 U31 客户端登录界面。", file=sys.stderr)
        sys.exit(1)
    rect = activate_window(win)
    region = rect_to_pyautogui_region(rect)

    from PIL import Image, ImageDraw
    shot = pyautogui.screenshot(region=region)
    draw = ImageDraw.Draw(shot)

    colors = {
        "username":   (255, 0, 0),     # 红
        "password":   (0, 0, 255),     # 蓝
        "btn_ok":     (0, 180, 0),     # 绿
        "btn_cancel": (255, 140, 0),   # 橙
    }
    left, top, w, h = region
    for key, (px, py) in cfg["coords"].items():
        x = int(px * w)
        y = int(py * h)
        color = colors.get(key, (0, 0, 0))
        r = 8
        draw.line([(x - r, y), (x + r, y)], fill=color, width=2)
        draw.line([(x, y - r), (x, y + r)], fill=color, width=2)
        draw.ellipse([(x - 3, y - 3), (x + 3, y + 3)], fill=color)
        draw.text((x + 10, y - 8), key, fill=color)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "cs_ems_login_calibrate.png")
    shot.save(out)
    print(f"[+] 校准截图已保存: {out}")
    print("    请确认红点落在用户名框、蓝点落在密码框、绿点落在 OK 按钮上。")


def navigate_menu(cfg, debug_dir=None):
    """登录成功后，在主界面精准打开目标菜单项（如 Performance → Query Template Management）。

    采用「键盘精准导航」而非脆弱的坐标偏移（坐标 dy 在不同分辨率/DPI/主题下会漂，
    实测 (773,152) 这种估算偏移会打空）：
      1) Alt+P 打开顶层菜单（可靠，不依赖坐标）
      2) Down 把焦点移入下拉项（规避 Swing 菜单焦点初始停在标题栏的坑）
      3) Down×N 把焦点移到目标子项（N = ems_config.json 的 submenu_down_count，默认 4）
      4) Enter 激活
    这样无论窗口怎么摆，都能精准命中目标项。仍保留 --menu-calibrate 做坐标诊断。

    cfg["menu_path"] = ["Performance", "Query Template Management"]
    """
    menu_path = cfg.get("menu_path", [])
    if not menu_path or len(menu_path) < 2:
        print("[*] 未配置 menu_path 或路径太短，跳过菜单导航。")
        return

    top_menu = menu_path[0]       # 如 "Performance"
    sub_item = menu_path[1]        # 如 "Query Template Management"
    print(f"[*] 导航菜单: {top_menu} → {sub_item}")

    # ---- 关键：先激活 U31 主窗口，否则键盘快捷键会发到别的窗口 ----
    print("[*] 激活 U31 主窗口...")
    main = find_main_window(cfg)
    if not main:
        print("[!] 找不到 U31 主窗口，无法导航菜单。", file=sys.stderr)
        return
    activate_window(main)
    time.sleep(0.5)

    _switch_to_english_ime()
    time.sleep(0.3)

    # ---- 步骤 1：键盘打开顶层菜单（Alt+P）----
    first_char = top_menu[0].lower()  # 'p' for Performance
    print(f"    按 Alt+{first_char.upper()} 打开 '{top_menu}' 菜单...")
    pyautogui.hotkey("alt", first_char)
    time.sleep(1.0)  # 等下拉菜单完全渲染
    if debug_dir:
        path = os.path.join(debug_dir, "debug_menu_opened.png")
        pyautogui.screenshot().save(path)
        print(f"    [DEBUG] 菜单展开截图: {path}")

    # ---- 步骤 2：Down × N 把焦点移到目标子项 ----
    # 本机 U31 的 L&F 不支持 type-ahead 按首字母跳转（实测键入 Q 无效），
    # 只能用方向键数到目标项。焦点初始在菜单栏标题（不在第一项），
    # 故 N = 目标项序号 + 1。"Query Template Management" 是 Performance 下
    # 第 4 项（index=3），默认 N=4。不准就改 ems_config.json 的
    # submenu_down_count，或用 --menu-probe 标定。
    n = int(cfg.get("submenu_down_count", 4))
    print(f"    按 Down × {n} 移到目标子项...")
    for _ in range(n):
        pyautogui.press("down")
        time.sleep(0.25)

    # ---- 步骤 3：截图确认高亮项（不虚假声明成功）----
    if debug_dir:
        path = os.path.join(debug_dir, "debug_menu_selected.png")
        pyautogui.screenshot().save(path)
        print(f"    [DEBUG] 选中项截图: {path}")

    # ---- 步骤 4：Enter 激活 ----
    pyautogui.press("enter")
    time.sleep(2.0)  # 等面板加载
    if debug_dir:
        path = os.path.join(debug_dir, "debug_menu_result.png")
        pyautogui.screenshot().save(path)
        print(f"    [DEBUG] 菜单激活结果截图: {path}")

    print(f"[+] 菜单导航已执行（{top_menu} → Down×{n} → Enter）。请确认 '{sub_item}' 面板已正确打开。")


def probe_menu(cfg, debug_dir=None, max_n=6):
    """安全标定：打开 Performance 菜单后，依次按 Down 1..max_n 次并各截一张图，
    不按 Enter（不触发面板）。运行后看 debug_shots/debug_menu_probe_<n>.png，
    找到高亮停在目标子项（如 Query Template Management）的那张，其 n 即为要写入
    ems_config.json 的 submenu_down_count。结束后按 Esc 关闭菜单，不残留。
    """
    print("[*] 菜单标定模式（只按 Down 截图，不激活）...")
    main = find_main_window(cfg)
    if not main:
        print("[!] 找不到 U31 主窗口，请先登录进入主界面。", file=sys.stderr)
        sys.exit(1)
    activate_window(main)
    time.sleep(0.5)
    _switch_to_english_ime()
    time.sleep(0.3)

    top_menu = (cfg.get("menu_path") or ["Performance"])[0]
    sub_item = (cfg.get("menu_path") or ["", "Query Template Management"])[1]
    first_char = top_menu[0].lower()
    pyautogui.hotkey("alt", first_char)
    time.sleep(1.0)

    out_dir = debug_dir or "debug_shots"
    os.makedirs(out_dir, exist_ok=True)

    for n in range(1, max_n + 1):
        pyautogui.press("down")
        time.sleep(0.3)
        path = os.path.join(out_dir, f"debug_menu_probe_{n}.png")
        pyautogui.screenshot().save(path)
        print(f"    [DEBUG] 按 Down×{n} 截图: {path}")

    pyautogui.press("escape")  # 关闭菜单，避免残留
    print(f"\n[+] 标定完成。查看 {out_dir}/debug_menu_probe_*.png：")
    print(f"    高亮项停在 '{sub_item}' 的那张，其 n 即为 submenu_down_count。")
    print(f"    然后把该值写进 ems_config.json 的 submenu_down_count，再跑正式导航。")


def calibrate_menu(cfg, debug_dir=None):
    """校准菜单坐标：打开 Performance 下拉菜单，截图并标注计算出的点击位置。

    此函数只打开菜单+截图，**不会点击子菜单项**（安全，不影响界面状态）。
    运行后请查看 debug_shots/debug_menu_calibrate.png 确认红点是否落在 'Query Template Management' 上。
    """
    print("[*] 菜单坐标校准模式（只截图不点击）...")

    main = find_main_window(cfg)
    if not main:
        print("[!] 找不到 U31 主窗口，无法校准菜单。", file=sys.stderr)
        print("    请先登录 U31 客户端进入主界面后再运行 --menu-calibrate。")
        sys.exit(1)

    rect = activate_window(main)
    time.sleep(0.5)
    _switch_to_english_ime()
    time.sleep(0.3)

    # 打开 Performance 菜单
    top_menu = (cfg.get("menu_path") or ["Performance"])[0]
    first_char = top_menu[0].upper()
    print(f"    按 Alt+{first_char} 打开 '{top_menu}' 菜单...")
    pyautogui.hotkey("alt", first_char.lower())
    time.sleep(1.0)

    # 全屏截图
    from PIL import Image, ImageDraw
    full_shot = pyautogui.screenshot()

    # 计算并标注点击目标
    menu_coords = cfg.get("menu_coords", {})
    top_pct = menu_coords.get("top_menu_pct", [0.30, 0.035])
    offset_px = menu_coords.get("submenu_offset_px", [5, 103])
    top_sx, top_sy = pct_to_xy(top_pct[0], top_pct[1], rect)
    target_x = top_sx + offset_px[0]
    target_y = top_sy + offset_px[1]

    draw = ImageDraw.Draw(full_shot)

    # 标注 1：顶菜单项位置（绿色方块）
    gs = 6
    draw.rectangle([(top_sx - gs, top_sy - gs), (top_sx + gs, top_sy + gs)],
                   outline=(0, 180, 0), width=2)
    draw.text((top_sx + 12, top_sy - 8), f"TopMenu ({top_sx},{top_sy})", fill=(0, 180, 0))

    # 标注 2：子菜单项点击目标（红色十字准星）
    r = 15
    draw.line([(target_x - r, target_y), (target_x + r, target_y)], fill=(255, 0, 0), width=3)
    draw.line([(target_x, target_y - r), (target_x, target_y + r)], fill=(255, 0, 0), width=3)
    draw.ellipse([(target_x - 5, target_y - 5), (target_x + 5, target_y + 5)], fill=(255, 0, 0))
    draw.text((target_x + 18, target_y - 12),
              f"TARGET: {cfg['menu_path'][1] if len(cfg.get('menu_path',[]))>1 else 'submenu'}\n({target_x},{target_y})",
              fill=(255, 0, 0))

    # 保存
    out_dir = debug_dir or "debug_shots"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "debug_menu_calibrate.png")
    full_shot.save(out_path)
    print(f"\n[+] 校准截图已保存: {out_path}")
    print(f"    主窗口矩形: {rect}")
    print(f"    顶菜单(绿): 窗口内 ({top_pct[0]:.3f},{top_pct[1]:.3f}) -> 屏幕 ({top_sx}, {top_sy})")
    print(f"    子菜单目标(红): 偏移 ({offset_px[0]},{offset_px[1]}px -> ({target_x}, {target_y})")
    print(f"\n    请确认：")
    print(f"      1. 绿色方块是否落在菜单栏的 '{top_menu}' 上？")
    print(f"      2. 红色十字是否落在下拉菜单的 '{cfg['menu_path'][1]}' 上？")
    print(f"    如果偏移不对，修改 ems_config.json 的 menu_coords.submenu_offset_px 的 dy 值。")
    print(f"    典型值：每项约 23px，第 N 项的 dy ≈ N * 23 + 11")


def main_flow(args, cfg):
    if args.calibrate:
        calibrate(cfg)
        return

    if args.menu_calibrate:
        debug_dir = "debug_shots" if args.debug else None
        calibrate_menu(cfg, debug_dir=debug_dir)
        return

    if args.menu_probe:
        probe_menu(cfg, debug_dir="debug_shots", max_n=args.count or 6)
        return

    # 启动客户端（如果需要）
    if not args.no_launch:
        exe = cfg["client_exe"]
        if not os.path.exists(exe):
            print(f"[!] 客户端不存在: {exe}", file=sys.stderr)
            sys.exit(1)
        print(f"[*] 启动客户端: {exe}")
        import subprocess
        subprocess.Popen([exe])
        # 轮询等待登录窗口真正出现（Java 客户端启动慢，固定 sleep 不可靠）
        print(f"[*] 等待登录窗口出现 (最长 {cfg['login_timeout']}s)...")
        w = find_login_window(cfg)
        if not w:
            print(f"[!] 超时未出现登录窗口。可改用手动打开客户端后加 --no-launch 重试。",
                  file=sys.stderr)
            sys.exit(2)

    # 登录
    debug_dir = "debug_shots" if args.debug else None
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
    do_login(cfg, debug_dir=debug_dir, click_ok=not args.fill_only)

    if args.fill_only:
        print("[+] 填写完成（fill-only）。请确认截图/屏幕上文字正确后手动点 OK。")
        return

    # 等待主界面
    print("[*] 等待主界面加载...")
    time.sleep(cfg["post_login_wait"])
    main = find_main_window(cfg)
    if main:
        print(f"[+] 登录成功，主窗口已出现: '{main.window_text()}'")
        activate_window(main)  # 激活主窗口，确保后续键盘操作发到 U31
    else:
        print("[!] 未检测到主窗口，可能登录失败（用户名/密码错误或被锁）。", file=sys.stderr)
        sys.exit(3)

    # 导航到目标菜单
    debug_dir = "debug_shots" if args.debug else None
    navigate_menu(cfg, debug_dir=debug_dir)


def main():
    parser = argparse.ArgumentParser(
        description="ZTE NetNumen U31 EMS 通用登录脚本（零 RPA 依赖）")
    parser.add_argument("--no-launch", action="store_true",
                        help="不启动客户端，假定 U31 登录界面已打开")
    parser.add_argument("--fill-only", action="store_true",
                        help="只填写用户名/密码，不点击 OK（安全验证用）")
    parser.add_argument("--calibrate", action="store_true",
                        help="截图标注各坐标点，自检坐标是否对准输入框")
    parser.add_argument("--debug", action="store_true",
                        help="登录每步操作后截图到 debug_shots/ 目录")
    parser.add_argument("--menu-calibrate", action="store_true",
                        help="菜单坐标校准：打开 Performance 菜单并截图标注点击位置（不实际点击）")
    parser.add_argument("--menu-probe", action="store_true",
                        help="菜单标定：打开菜单后依次 Down 1..N 截图（不激活），用于确定 submenu_down_count")
    parser.add_argument("--count", type=int, default=6,
                        help="--menu-probe 时最多按几次 Down（默认 6）")
    args = parser.parse_args()

    cfg = load_config()
    main_flow(args, cfg)


if __name__ == "__main__":
    main()
