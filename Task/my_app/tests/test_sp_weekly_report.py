# -*- coding: utf-8 -*-
"""SP 周报生成器守卫测试（generate_sp_weekly_report）。

只测纯函数与落盘行为，不读真实 xlsx、不发邮件，可在任意环境秒级跑完：
  1. 周期必须落在「周日 → 周六」：生成器内部会拒绝非周日的窗口；
  2. 默认窗口 = 最近一个**已结束**的周日，且长度 7 天；
  3. 工单站点解析：`[站点名]` 优先、标题前导站号要剥掉、站点名与原因不得重复；
  4. 落盘：tmp + os.replace 原子替换；目标被 Excel 持续占用时按项目规则
     改用 ``_序号`` 文件名，不再让周报任务失败。
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.sp_report_gen import generate_sp_weekly_report as wk  # noqa: E402


# ---------------------------------------------------------------- 周期
# 口径（2026-11-03 如意最终确认）：周期 = 完整自然周「周一 → 周日」，
# 任务每周一 07:00 发送。默认 end = 最近一个已结束的周日，与执行日无关，
# 避免周二/周三手动补跑时漂成「周二 → 周一」。
@pytest.mark.parametrize(
    "today,expected",
    [
        (date(2026, 11, 2), date(2026, 11, 1)),    # 周一 07:00 跑 → 昨天(周日)
        (date(2026, 11, 3), date(2026, 11, 1)),    # 周二补跑 → 仍是刚过去的周日
        (date(2026, 11, 7), date(2026, 11, 1)),    # 周六补跑 → 同一个周日
        (date(2026, 11, 1), date(2026, 10, 25)),   # 周日跑 → 上一个周日（本周尚未结束）
        (date(2026, 3, 2), date(2026, 3, 1)),      # 跨月：2026-03-02 周一 → 3/1 周日
    ],
)
def test_default_period_end_is_last_finished_sunday(today, expected):
    assert wk.default_period_end(today) == expected


@pytest.mark.parametrize("today", [date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 7)])
def test_window_is_always_monday_to_sunday(today):
    """无论哪天跑，窗口都必须是完整的周一 → 周日 7 天。"""
    end = wk.default_period_end(today)
    start = end - timedelta(days=6)
    assert start.weekday() == 0, "period must start on Monday"
    assert end.weekday() == 6, "period must end on Sunday"
    assert (end - start).days == 6


def test_monday_run_covers_previous_monday_to_sunday():
    """周一 07:00 发送：里面的数据就是上周一 → 上周日。"""
    end = wk.default_period_end(date(2026, 11, 2))          # 周一
    start = end - timedelta(days=6)
    assert (start, end) == (date(2026, 10, 26), date(2026, 11, 1))


def test_build_rejects_non_sunday_end(tmp_path):
    """--week-end 落在非周日时必须拒绝，否则会产出「周二 ~ 周一」这种错位窗口。"""
    with pytest.raises(ValueError, match="Sunday"):
        wk.build(tmp_path, date(2026, 10, 30))              # 周五


@pytest.mark.skipif(
    not (PROJECT_ROOT / "data" / "sp_email" / "data" / "outband_details.xlsx").is_file(),
    reason="本地明细不存在（无数据的 CI 环境），跳过端到端周期测试",
)
def test_build_full_natural_week(tmp_path):
    """端到端：给定周日作为 end，产出的周期就是「上周一 → 上周日」。"""
    res = wk.build(tmp_path, date(2026, 11, 1))
    assert res["success"] is True
    assert res["period_start"] == "2026-10-26"
    assert res["period_end"] == "2026-11-01"


def test_build_rejects_non_seven_days(tmp_path):
    with pytest.raises(ValueError, match="7 days"):
        wk.build(tmp_path, date(2026, 10, 31), days=5)


# ---------------------------------------------------------------- 数量 + 单位
# 模板要求统计数字带单位（详见 generate_sp_weekly_report 的 _qty_cell 注释）：
#   单单位 → 数值 + 数字格式后缀，显示 7PCS，底层仍是数字（SUM/排序照常）
#   多单位 → 文本 '4PCS+50Meter'（跨单位无法求和，与手工模板一致）
def test_qty_cell_single_unit_keeps_number_and_shows_unit():
    val, fmt = wk._qty_cell({"PCS": 7})
    assert val == 7 and isinstance(val, float)
    # 必须是 General"PCS"：`#,##0.##"PCS"` 会让 Excel 把整数显示成 `7.PCS`
    assert fmt == 'General"PCS"'


def test_qty_cell_multi_unit_is_text_joined_like_template():
    val, fmt = wk._qty_cell({"Meter": 50, "PCS": 4, "KG": 40})
    assert fmt is None
    assert val == "4PCS+50Meter+40KG"


def test_qty_cell_zero_has_no_unit():
    val, fmt = wk._qty_cell({"PCS": 0})
    assert val == 0.0 and fmt is None


def test_qty_fmt_without_unit_is_plain_number():
    assert wk._qty_fmt("") == "General"


def test_summary_cells_carry_units_and_mixed_cells_are_split():
    """Inbound&Outbound Summary：单单位格是数值(带单位格式)，跨单位格是 '+' 拼接文本。"""
    from openpyxl import Workbook

    inb = pd.DataFrame({
        "_domain": ["MW", "MW"], "_wh": ["W1", "W1"], "Unit": ["PCS", "PCS"], "Inbound Qty": [3.0, 0.0],
    })
    outb = pd.DataFrame({
        "_domain": ["MW", "MW"], "_wh": ["W1", "W1"], "Unit": ["PCS", "Meter"], "Outbound Qty": [3.0, 50.0],
    })
    wb = Workbook()
    wb.remove(wb.active)
    wk.sheet_inout(wb, inb, outb)
    ws = wb["Inbound&Outbound Summary"]
    # 表头占 3 行，R4 = MW 行；B=Inbound，C=W1 出库，D=Outbound Total
    assert ws.cell(4, 2).value == 3 and '"PCS"' in ws.cell(4, 2).number_format
    assert ws.cell(4, 3).value == "3PCS+50Meter"      # 跨单位格 → 文本
    assert ws.cell(4, 4).value == "3PCS+50Meter"      # 合计同样按单位分解
    # Total 行
    assert ws.cell(5, 3).value == "3PCS+50Meter"


def test_daily_report_date_cells_show_row_unit():
    """Daily report：数量落在自己那天，并按本行物料单位显示（1PCS / 75Meter）。"""
    from openpyxl import Workbook

    days = [date(2026, 10, 25) + timedelta(days=i) for i in range(7)]
    outb = pd.DataFrame({
        "Outbound Time": pd.to_datetime(["2026-10-26 09:00", "2026-10-27 10:00"]),
        "Material Name": ["Ethernet Cable|", "Chassis|"],
        "Material No.": ["180000019045", "122630731000"],
        "Outbound Qty": [75.0, 1.0],
        "Unit": ["Meter", "PCS"],
        "Related Ticket Type": ["WO", "WO"],
        "Related Ticket Site Id": ["4024", "4122"],
        "Related Ticket Title": ["[Sinkor]4G CELL DOWN", "[Zekepa]3G CELL DOWN"],
        "Related Ticket No.": ["WO1", "WO2"],
        "Outbound Type": ["Install", "Install"],
    })
    wb = Workbook()
    wb.remove(wb.active)
    wk.sheet_daily(wb, outb, days, {})
    ws = wb["Daily report"]
    # 表头占 3 行；数据行 4 起；日期列 E..K
    assert ws.cell(4, 6).value == 75 and '"Meter"' in ws.cell(4, 6).number_format
    assert ws.cell(5, 7).value == 1 and '"PCS"' in ws.cell(5, 7).number_format


def test_top_consumed_carries_unit_on_both_columns():
    """Top 10：Consumed 与 Current Storage 都带单位（模板是 250m / 370m）。"""
    from openpyxl import Workbook

    outb_w = pd.DataFrame({
        "Material No.": ["180000002838"] * 2, "Material Name": ["IF cable(RG-8U)|"] * 2,
        "Outbound Qty": [200.0, 50.0], "Unit": ["Meter", "Meter"], "_excluded_wh": [False, False],
    })
    inv = pd.DataFrame({
        "Material No.": ["180000002838"], "Material Name": ["IF cable(RG-8U)|"],
        "Stock Qty": [370.0], "Unit": ["Meter"], "_excluded_wh": [False],
    })
    wb = Workbook()
    wb.remove(wb.active)
    wk.sheet_top(wb, outb_w, inv, date(2026, 10, 25), date(2026, 10, 31))
    ws = wb["Top 10 Consumed Spares"]
    assert ws.cell(4, 4).value == 250 and '"Meter"' in ws.cell(4, 4).number_format
    assert ws.cell(4, 6).value == 370 and '"Meter"' in ws.cell(4, 6).number_format


# ---------------------------------------------------------------- 站点解析
def _row(**kw):
    base = {
        "Related Ticket Type": None,
        "Related Ticket Site Id": None,
        "Related Ticket Title": None,
        "Related Ticket No.": None,
        "Outbound Type": None,
    }
    base.update(kw)
    return pd.Series(base)


def test_parse_bracket_site_and_strip_leading_id():
    r = _row(**{
        "Related Ticket Type": "WO",
        "Related Ticket Site Id": "4122",
        "Related Ticket Title": " 4122.[Zekepa]3G CELL DOWN",
        "Related Ticket No.": "WO202609010005",
    })
    t = wk._parse_ticket(r, {})
    assert t["site_id"] == "4122"
    assert t["site_name"] == "Zekepa"
    assert t["reason"] == "3G CELL DOWN", "标题前导站号必须剥掉"
    assert t["ticket_type"] == "WO"
    assert t["ticket_no"] == "WO202609010005"


def test_parse_site_name_from_master_when_title_has_only_name():
    r = _row(**{"Related Ticket Type": "WO", "Related Ticket Site Id": "3283",
                "Related Ticket Title": "Bokessa"})
    t = wk._parse_ticket(r, {"3283": "Bokessa"})
    assert t["site_name"] == "Bokessa"
    assert t["reason"] == "Install Outbound" or t["reason"] == "", "原因不得与站名重复"


def test_parse_leading_id_without_bracket():
    r = _row(**{"Related Ticket Type": "TT", "Related Ticket Site Id": "4583",
                "Related Ticket Title": "4583\tQcell LMTI The physical link is broken"})
    t = wk._parse_ticket(r, {"4583": "Qcell LMTI"})
    assert t["site_id"] == "4583"
    assert t["site_name"] == "Qcell LMTI"
    assert t["reason"].startswith("Qcell LMTI The physical")


def test_parse_multi_site_ticket_keeps_full_id_list():
    r = _row(**{"Related Ticket Type": "TT", "Related Ticket Site Id": "3586,4775,4465",
                "Related Ticket Title": "Bulk alarm"})
    t = wk._parse_ticket(r, {})
    assert t["site_id"] == "3586,4775,4465", "多站点工单禁止只保留其中一个 ID"
    assert t["site_name"] == "(multiple sites)"


def test_parse_falls_back_to_outbound_type_when_no_ticket():
    r = _row(**{"Outbound Type": "Repair Outbound"})
    t = wk._parse_ticket(r, {})
    assert t["reason"] == "Repair Outbound"
    assert t["site_id"] == "" and t["site_name"] == ""


# ---------------------------------------------------------------- 落盘
# 2026-11-03 16:54~16:55 两次任务失败：目标 xlsx 被人用 Excel 打开时
# wb.save(path) 直接 PermissionError[Errno 13]。这里守卫原子替换、瞬态锁重试，
# 以及持续占用时改用 _序号 文件并清 tmp。
def _tiny_wb():
    from openpyxl import Workbook

    wb = Workbook()
    wb.active["A1"] = 1
    return wb


def test_save_workbook_replaces_atomically_and_leaves_no_tmp(tmp_path):
    from openpyxl import load_workbook

    path = tmp_path / "SP Weekly Report 2026-10-26 to 2026-11-01.xlsx"
    wk._save_workbook(_tiny_wb(), path)
    assert path.is_file()
    assert load_workbook(path).active["A1"].value == 1
    assert list(tmp_path.iterdir()) == [path], "成功后不得残留临时文件"


def test_save_workbook_retries_then_succeeds_when_lock_released(tmp_path, monkeypatch):
    path = tmp_path / "rep.xlsx"
    real_replace = wk.os.replace
    state = {"n": 0}

    def flaky(src, dst):
        state["n"] += 1
        if state["n"] == 1:
            raise PermissionError(13, "Permission denied")
        return real_replace(src, dst)

    monkeypatch.setattr(wk.os, "replace", flaky)
    monkeypatch.setattr(wk.time, "sleep", lambda s: None)
    wk._save_workbook(_tiny_wb(), path, attempts=3, wait_seconds=0)
    assert path.is_file() and state["n"] == 2, "第一次撞锁后必须重试而不是直接失败"


def test_save_workbook_uses_numbered_file_when_target_stays_locked(tmp_path, monkeypatch):
    path = tmp_path / "rep.xlsx"
    real_replace = wk.os.replace
    calls = []

    def busy_original(src, dst):
        calls.append(dst)
        if Path(dst) == path:
            raise PermissionError(13, "Permission denied")
        return real_replace(src, dst)

    monkeypatch.setattr(wk.os, "replace", busy_original)
    monkeypatch.setattr(wk.time, "sleep", lambda s: None)
    saved = wk._save_workbook(_tiny_wb(), path, attempts=3, wait_seconds=0)
    assert saved == tmp_path / "rep_1.xlsx"
    assert saved.is_file()
    assert list(tmp_path.iterdir()) == [saved], "成功后不得清理或覆盖备用文件"
    assert len(calls) == 4, "原名重试用满后必须自动尝试 _1 文件"
