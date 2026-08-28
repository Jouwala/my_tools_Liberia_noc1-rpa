# -*- coding: utf-8 -*-
"""
cs_ems_jab.py — 基于 Java Access Bridge (JAB) 的 U31 EMS 精准控件定位

前提（启用 JAB 的一次性准备，见 cs_ems_login.py / 部署说明）：
  1. U31 的 JDK6 的 jre/lib/ext/ 里放入标准 jaccess.jar（含
     com.sun.java.accessibility.AccessBridge，实现 AssistiveTechnology）
  2. client.exe 旁建 client.l4j.ini 注入
     -Djavax.accessibility.assistive_technologies=com.sun.java.accessibility.AccessBridge
  3. 重启用 U31 客户端，使其 JVM 加载 Access Bridge
  4. pip install pyjab（Python 侧 JAB 客户端，基于 JNA）

本脚本用途：
  --check      确认 JAB 桥已连通、能看到 U31 的 JVM 控件树
  --dump       导出 U31 主界面控件树到 jab_tree.txt（按 --filter 过滤，避免爆炸）
  --navigate   登录后自动 Performance → Query Template Management（按文本精准点击）

相比 cs_ems_login.py 里的坐标方案：JAB 按 name/role 找控件，不再依赖脆弱的
屏幕坐标与 Down×N 盲按，是 Swing 自动化的"正道"。
"""

import argparse
import re
import sys
import time

from pyjab.jabdriver import JABDriver, Service, JABException

MAIN_TITLE = "NetNumen U31 Unified Management System - Client"
LOGIN_TITLE = "Login - NetNumen U31"


def enable_bridge():
    """启用客户端侧 Windows Access Bridge（加载 WindowsAccessBridge DLL）。"""
    srv = Service()
    try:
        srv.enable_bridge()
        print(f"[*] bridge enabled = {srv.is_bridge_enabled()}")
    except Exception as e:
        print(f"[!] enable_bridge 异常（可忽略，init_jab 会再试）: {e}")


def connect(title, timeout=30):
    """连接并初始化到指定标题的 Java 窗口。"""
    enable_bridge()
    print(f"[*] 连接 Java 窗口: {title!r} (timeout={timeout}s)")
    d = JABDriver(title=title, timeout=timeout)
    d.init_jab()
    try:
        vi = d.get_version_info()
        print(f"[+] 桥版本: JVM={vi.get('VMVersion')} bridgeJava={vi.get('bridgeJavaClassVersion')} bridgeWin={vi.get('bridgeWinDLLVersion')}")
    except Exception as e:
        print(f"[!] 取版本信息失败: {e}")
    return d


def dump_tree(d, filter_re=None, max_depth=6, max_nodes=4000):
    """遍历控件树，按 filter 过滤后打印/写出。"""
    pat = re.compile(filter_re, re.IGNORECASE) if filter_re else None
    out = []
    counter = [0]

    def walk(el, depth):
        if depth > max_depth or counter[0] >= max_nodes:
            return
        try:
            info = el.get_element_information()
        except Exception as e:
            out.append(("  " * depth) + f"<err:{e}>")
            return
        name = info.get("name") or ""
        role = info.get("role_en_us") or info.get("role") or ""
        desc = info.get("description") or ""
        bounds = info.get("bounds") or ""
        if pat:
            hay = f"{name} {role} {desc}"
            if not pat.search(hay):
                # 仍递归（子树可能命中），但不打印本节点
                pass
            else:
                counter[0] += 1
                out.append(("  " * depth) + f"[{role}] name={name!r} desc={desc!r} bounds={bounds}")
        else:
            counter[0] += 1
            out.append(("  " * depth) + f"[{role}] name={name!r} desc={desc!r} bounds={bounds}")
        try:
            for child in el.get_child_jabelements():
                walk(child, depth + 1)
        except Exception:
            pass

    print("[*] 遍历控件树...")
    try:
        walk(d.root_element, 0)
    except Exception as e:
        print(f"[!] 遍历失败: {e}")
    text = "\n".join(out)
    with open("jab_tree.txt", "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[+] 控件树已写出 jab_tree.txt （共 {counter[0]} 个节点，filter={filter_re!r}）")
    # 控制台也打印前 200 行
    for line in text.splitlines()[:200]:
        print(line)
    return text


def navigate(d, top_menu="Performance", sub_item="Query Template Management"):
    """键盘打开顶层菜单 → JAB 按名查找子项 → 点击。"""
    import pyautogui
    print(f"[*] 导航: {top_menu} → {sub_item}")
    # 1) 键盘打开顶层菜单
    pyautogui.hotkey("alt", top_menu[0].lower())
    time.sleep(1.0)
    # 2) JAB 按名查找子菜单项
    try:
        el = d.find_element_by_name(sub_item)
    except JABException as e:
        print(f"[!] 未找到 {sub_item!r}: {e}")
        return False
    info = el.get_element_information()
    print(f"[+] 找到子项: name={info.get('name')!r} role={info.get('role_en_us')} bounds={info.get('bounds')}")
    # 3) 点击
    el.click()
    time.sleep(1.5)
    print(f"[+] 已点击 {sub_item}")
    return True


def main():
    ap = argparse.ArgumentParser(description="U31 EMS JAB 精准定位工具")
    ap.add_argument("--title", default=MAIN_TITLE, help="目标 Java 窗口标题")
    ap.add_argument("--check", action="store_true", help="仅确认 JAB 桥连通")
    ap.add_argument("--dump", action="store_true", help="导出控件树到 jab_tree.txt")
    ap.add_argument("--filter", default=None, help="dump 时按正则过滤 name/role/desc")
    ap.add_argument("--navigate", action="store_true", help="执行 Performance→Query Template Management")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()

    d = connect(args.title, timeout=args.timeout)
    if args.check:
        print("[+] check 完成：JAB 已连通目标 JVM。")
        return
    if args.dump:
        dump_tree(d, filter_re=args.filter)
        return
    if args.navigate:
        ok = navigate(d)
        print("[+] navigate 结果:", "成功" if ok else "失败")
        return
    print("请指定 --check / --dump / --navigate 之一。详见 -h。")


if __name__ == "__main__":
    main()
