# -*- coding: utf-8 -*-
"""
cs_ems_kpi_code.py — CS 域 KPI 模板 GUI 自动查询 (pywinauto 版)

替代 xbot RPA 平台依赖, 使用 pywinauto 直接操控 U31 EMS 客户端窗口,
逐个查询 7 个 CS KPI 模板并导出结果。

依赖:
  pip install pywinauto

用法:
  python cs_ems_kpi_code.py                          # 默认查上月
  python cs_ems_kpi_code.py --month 07 --date 31     # 指定月/日
  python cs_ems_kpi_code.py --inspect                # 检查窗口控件 (首次运行必做)
"""

import argparse
import datetime
import os
import sys
import time

# ---------------------------------------------------------------------------
# 控件定位
# ---------------------------------------------------------------------------
# xbot 的 selector 格式: "<类型提示>_<控件标识>"
#   - 下划线前为 xbot 内部类型标注 (文本框/按钮/制表项/单选按钮/信息标注)
#   - 下划线后为控件在 UI 中显示的英文文本 (title / automation_id)
#
# pywinauto 通过 UIA 后端递归搜索窗口树, 按以下优先级匹配:
#   1. automation_id 完全匹配
#   2. title 完全匹配
#   3. title 包含匹配 (关键字在控件 title 中)
#
# 如果自动匹配失败, 运行 --inspect 查看实际控件属性,
# 然后在 CONTROL_MAP 中添加精确映射:  {"xbot_selector": "实际控件title或automation_id"}
# ---------------------------------------------------------------------------

# 可选: 手动映射 (当自动搜索找不到控件时在此补充)
CONTROL_MAP = {
    # "xbot_selector": ("匹配方式", "匹配值"),
    # 示例:
    # "文本框_PM_Template": ("title_re", "PM_Template"),
    # "按钮_qURY_KPI":      ("title", "Query KPI"),
}


def _find_element(parent, selector, timeout=10):
    """在 parent 下递归查找控件, 返回 pywinauto 控件对象.

    搜索策略:
      1. 若 CONTROL_MAP 有映射, 按映射方式查找
      2. 取 selector 下划线后的英文部分, 依次尝试:
         a. automation_id 完全匹配
         b. title 完全匹配
         c. title 包含匹配
    """
    from pywinauto import findwindows

    # 1) 手动映射优先
    if selector in CONTROL_MAP:
        method, value = CONTROL_MAP[selector]
        kwargs = {}
        if method == "title":
            kwargs["title"] = value
        elif method == "title_re":
            kwargs["title_re"] = value
        elif method == "auto_id":
            kwargs["automation_id"] = value
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                return parent.child_window(**kwargs)
            except Exception:
                time.sleep(0.5)
        raise TimeoutError(f"控件超时 ({selector} -> {method}={value})")

    # 2) 自动推断: 取下划线后的英文部分作为关键字
    keyword = selector.split("_", 1)[-1] if "_" in selector else selector

    deadline = time.time() + timeout
    while time.time() < deadline:
        # 尝试 automation_id
        try:
            ctrl = parent.child_window(automation_id=keyword, found_index=0)
            if ctrl.exists():
                return ctrl
        except Exception:
            pass

        # 尝试 title 精确匹配
        try:
            ctrl = parent.child_window(title=keyword, found_index=0)
            if ctrl.exists():
                return ctrl
        except Exception:
            pass

        # 尝试 title 包含匹配 (递归搜索子控件)
        try:
            ctrls = parent.descendants(title=keyword)
            if ctrls:
                return ctrls[0]
        except Exception:
            pass

        # 尝试 title_re 模糊匹配
        try:
            ctrl = parent.child_window(title_re=f".*{keyword}.*", found_index=0)
            if ctrl.exists():
                return ctrl
        except Exception:
            pass

        time.sleep(0.5)

    raise TimeoutError(f"找不到控件: {selector} (keyword={keyword})")


def _find_filter_box(win, timeout=10):
    """定位 Template Management 工具栏上的过滤输入框。

    界面上有两个 "Enter the keyword to filter" 输入框 (左侧 NE Tree 一个,
    右侧工具栏一个)。优先按占位文本取最靠右者; 失败则以 "All NE Type"
    组合框为锚点, 取其右侧同一行的 Edit 控件。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        # 方式1: 按占位文本找, 取横坐标最大者
        try:
            boxes = [c for c in win.descendants(control_type="Edit")
                     if "keyword to filter" in (c.window_text() or "").lower()]
            if boxes:
                return max(boxes, key=lambda c: c.rectangle().left)
        except Exception:
            pass
        # 方式2: 以 NE Type 组合框为锚点, 取其右侧的 Edit
        try:
            ne = win.child_window(title_re=".*All NE Type.*", found_index=0)
            if ne.exists():
                nr = ne.rectangle()
                edits = win.descendants(control_type="Edit")
                cands = [c for c in edits
                         if c.rectangle().left >= nr.right - 5
                         and abs(c.rectangle().top - nr.top) < 30]
                if cands:
                    return min(cands, key=lambda c: c.rectangle().left)
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError("找不到过滤输入框 (Template Management 工具栏)")


def _click(ctrl, button="left"):
    """点击控件"""
    if button == "right":
        ctrl.click_input(button="right")
    else:
        ctrl.click_input()


def _input(ctrl, text):
    """向控件输入文本"""
    ctrl.set_edit_text(text)


def _send_keys(keys_str):
    """发送按键序列 (兼容 xbot send_keys 格式)

    xbot 格式: {ENTER}, {DOWN} 等 → pywinauto 格式: {ENTER}, {DOWN} (兼容)
    """
    from pywinauto.keyboard import send_keys
    send_keys(keys_str)


# ---------------------------------------------------------------------------
# 窗口检查工具
# ---------------------------------------------------------------------------

def inspect_window():
    """打印 U31 EMS 窗口的控件树, 用于首次运行时定位控件属性"""
    from pywinauto import Desktop

    title = "NetNumen U31 Unified Management System - Client - oss @ 10.100.2.240(EMS Core)"
    desktop = Desktop(backend="uia")
    try:
        win = desktop.window(title_re=".*NetNumen U31.*10\\.100\\.2\\.240.*")
    except Exception:
        print("[!] 未找到 U31 EMS 窗口, 请确保客户端已登录并处于开启状态。")
        print("    尝试模糊匹配所有顶层窗口...")
        for w in desktop.windows():
            t = w.window_text()
            if "U31" in t or "NetNumen" in t:
                print(f"  候选窗口: [{t}]")
        return

    print(f"[OK] 找到窗口: {win.window_text()}")
    print(f"     类名: {win.class_name()}")
    print()

    # 递归打印控件树 (限制深度)
    def _print_tree(ctrl, depth=0, max_depth=4):
        if depth > max_depth:
            return
        indent = "  " * depth
        try:
            name = ctrl.window_text()[:60]
            cls = ctrl.element_info.control_type or ctrl.class_name()
            auto_id = ctrl.element_info.automation_id or ""
            line = f"{indent}[{cls}] name={name!r}"
            if auto_id:
                line += f" auto_id={auto_id!r}"
            print(line)
        except Exception:
            pass
        try:
            for child in ctrl.children():
                _print_tree(child, depth + 1, max_depth)
        except Exception:
            pass

    print("=== 控件树 (depth=4) ===")
    _print_tree(win)
    print()
    print("提示: 根据输出中的 name / auto_id 更新 CONTROL_MAP 即可精确定位控件。")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

EMS_WINDOW_TITLE_RE = r".*NetNumen U31.*10\.100\.2\.240.*"

PM_TEMPLATE_LIST = [
    "VOICE_TRAFFIC_TEMPLATE_OSS",
    "VLR_SUBSCRIBERS_TEMPLATE_OSS",
    "USSD_RATIO_TEMPLATE_OSS",
    "TDD_DATA_TRAFFIC_TEMPLATE_OSS",
    "LOCATION_UPDATE_TEMPLATE_OSS",
    "LICENSE_OCCUPANCY_TEMPLATE_OSS",
    "DATA_SUBSCRIBERS_TEMPLATE_OSS",
]


def main(args=None):
    parser = argparse.ArgumentParser(description="CS EMS KPI GUI 自动查询")
    parser.add_argument("--month", default=None, help="查询月份 (MM), 默认上月")
    parser.add_argument("--date", default=None, help="查询日期 (dd), 默认上月最后一天")
    parser.add_argument("--inspect", action="store_true", help="检查 U31 窗口控件树")
    a = parser.parse_args(args)

    if a.inspect:
        inspect_window()
        return

    from pywinauto import Desktop

    # 1. 连接 U31 EMS 窗口
    desktop = Desktop(backend="uia")
    try:
        win = desktop.window(title_re=EMS_WINDOW_TITLE_RE)
        win.set_focus()
    except Exception:
        print("未发现网管系统主窗口，请确保客户端已登录并处于开启状态。")
        return

    # 2. 计算查询日期
    now = datetime.datetime.now()
    if a.month and a.date:
        month_str = a.month
        date_str = a.date
    else:
        last_month_end = now.replace(day=1) - datetime.timedelta(days=1)
        month_str = last_month_end.strftime("%m")
        date_str = last_month_end.strftime("%d")
    print(f"自动化设置查询日期为：{month_str}月 {date_str}日")

    # 3. 循环处理各个 KPI 模板
    for template_name in PM_TEMPLATE_LIST:
        print(f"正在处理模板：{template_name}")

        try:
            # 1. 在工具栏过滤框输入模板名并回车 (图1红框)
            filter_box = _find_filter_box(win)
            filter_box.click_input()
            try:
                filter_box.set_edit_text(template_name)
            except Exception:
                filter_box.type_keys(template_name, with_spaces=True)
            time.sleep(0.5)
            _send_keys("{ENTER}")
            time.sleep(1)

            # 2. 点击工具栏 "Query by Template" 按钮 (图2红框), 打开查询窗口
            _click(_find_element(win, "按钮_Query by Template"))

            # 等待并进入"时间选择"页签
            try:
                ts_tab = _find_element(win, "制表项_Time Selection", timeout=20)
                _click(ts_tab)
            except TimeoutError:
                print(f"  [!] 等待 Time Selection 超时, 跳过 {template_name}")
                continue

            # 设置查询维度为"月"和"自定义"
            _click(_find_element(win, "单选按钮_Month"))
            _click(_find_element(win, "单选按钮_Customize"))

            # 在弹出的日期选择窗口中输入日期
            active = desktop.active_window()
            _click(_find_element(active, "文本框_05"))
            _input(_find_element(active, "文本框_月份"), month_str)
            _click(_find_element(active, "文本框_date"))
            _input(_find_element(active, "文本框_date1"), date_str)

            # 确认查询条件
            _click(_find_element(active, "信息标注"))
            _click(_find_element(active, "按钮_OK_1"))

            # 等待数据加载
            time.sleep(3)

            # 处理导出流程
            try:
                browse_btn = _find_element(win, "按钮_Browse_1", timeout=10)
                _click(browse_btn)
                time.sleep(2)
                _send_keys("{ENTER}")  # 确认文件保存路径
            except TimeoutError:
                print("  [!] Browse 按钮未出现, 跳过导出")

            _click(_find_element(win, "按钮_OK_2"))
            _click(_find_element(win, "按钮_OK_3"))

            # 右键导出结果
            hp_tab = _find_element(win, "制表项_History Performance")
            _click(hp_tab, button="right")
            _send_keys("{DOWN}")
            _send_keys("{ENTER}")

            # 返回模板管理页，准备下一轮循环
            _click(_find_element(win, "制表项_Template Management"))

            print(f"  [OK] {template_name} 完成")

        except TimeoutError as e:
            print(f"  [!] {template_name} 失败: {e}")
            continue
        except Exception as e:
            print(f"  [!] {template_name} 异常: {e}")
            continue

    print("流程执行完毕，所有 KPI 模板已处理。")


if __name__ == "__main__":
    main()
