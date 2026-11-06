# -*- coding: utf-8 -*-
"""SP Weekly Report 生成器（周一 → 周日，共 7 天）

背景
====
`data/sp_report/SP Weekly report Template.xlsx` 是备件组手工维护的周报。它其实
就是 `gernarate_sp_report.py` 产出报表的「周窗口 + 按天展开」版本，但存在多处
口径缺陷（G5:G11 循环引用、数量混写 2PCS/50m/40KG 文本、Daily report 表头写死
September-Week2 且星期与日期错位、仓库映射两份）。本脚本用本地明细重新生成，
把上述问题全部按「数值化 + 事实字段」修正。

硬口径（用户 2026-11-03 指定）
=============================
1. 周期：**一个完整的自然周，周一 00:00:00 → 周日 23:59:59**。
   默认 `end` = **最近一个已经结束的周日**，任务**每周一 07:00** 发送。
   周一 07:00 跑 → 窗口就是「上周一 → 上周日」；其它日子手动补跑取到的仍是同一个
   自然周，不会漂成「周二 → 周一」。
   （2026-11-03 如意两次收紧口径：先改「过去 7 天 + 周一 07:00」，再要求对齐自然周。）
2. Inbound time / Outbound time 取自明细里的 `Inbound Time` / `Outbound Time`，
   这两列正是与 WO/TT/PMT 关联工单的实际操作时间（`Related Ticket Type` ∈
   {WO, TT, PMT} 时同一条出库记录上就带着工单号与站点）。
3. SITE NAME & ID：优先用 `Related Ticket Title` 里 `[站点名]` 与
   `Related Ticket Site Id`；标题里没有方括号时用本地 `eflow_site` 表反查。
4. Daily report 的 7 个日期列**动态生成**（星期 + 日期，一一对应），不再写死
   也不允许出现「Sunday / Monday / 9/10 / Saturday」这种错位表头。

输入
====
`data/sp_email/data/{inband,outband,inventory}_details.xlsx`
（由 sp_report_generate 每天 05:15 从 SFTP 拉取并过滤后的明细）

输出
====
`data/sp_weekly/SP Weekly Report <start> to <end>.xlsx`
控制台最后一行打印 JSON（供 kpi_email_report 解析周期与合计）。

用法
====
    python generate_sp_weekly_report.py                    # 上一自然周（end = 最近一个已结束的周日）
    python generate_sp_weekly_report.py --week-end 2026-11-01   # 指定周日补发
    python generate_sp_weekly_report.py --days 7 --out-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 上游明细（SFTP 导出的 inband/outband/inventory_details.xlsx）不带默认样式，
# openpyxl 每次读取都会打一条 "Workbook contains no default style" UserWarning。
# 无害（openpyxl 会自动套用默认样式），但会混进任务结果尾部的 stderr，
# 常被当成错误排查（2026-11-03 周报失败通知里就带着它），故在此屏蔽。
warnings.filterwarnings("ignore", message="Workbook contains no default style")

_SCRIPT_DIR = Path(__file__).resolve().parent
_APP_ROOT = _SCRIPT_DIR.parent.parent.parent

DATA_DIR = _APP_ROOT / "data" / "sp_email" / "data"
DEFAULT_OUT_DIR = _APP_ROOT / "data" / "sp_weekly"
DB_PATH = _APP_ROOT / "db" / "app.db"

INB_FILE = DATA_DIR / "inband_details.xlsx"
OUTB_FILE = DATA_DIR / "outband_details.xlsx"
INV_FILE = DATA_DIR / "inventory_details.xlsx"

#: 非备件周转仓（物料仓），与 gernarate_sp_report.EXCLUDE_WAREHOUSE 同口径排除，
#: 否则同一份数据在两套报表里的「库存」对不上。
EXCLUDE_WAREHOUSE = "Liberia Monrovia material warehouse"

#: 明细仓名 -> (Warehouse Id, 报表短名)。短名与模板 Warehouse-info 一致。
WAREHOUSE_MAP: Dict[str, Tuple[str, str]] = {
    "Liberia Monrovia Entrusted Spare Parts Warehouse": ("Monrovia Warehouse_01", "Monrovia-WH1"),
    "Liberia Monrovia Entrusted Spare Parts Warehouse-2nd floor": ("Monrovia Warehouse_03", "Monrovia-WH2"),
    "Liberia Gbarnga Entrusted Spare Parts DOP": ("Gbarnga DOP_01", "Gbarnga DOP"),
    "Liberia Kweaken Entrusted Spare Parts DOP": ("Kweaken_DOP_01", "Kweaken DOP"),
    "Liberia Bomi Entrusted Spare Parts DOP": ("Bomi_DOP_01", "Bomi DOP"),
}

DOMAIN_ORDER = ["RAN", "MW", "DWDM", "IPRAN", "IPCORE", "CN", "POWER", "Material", "Satellite"]
TICKET_TYPES = ("WO", "TT", "PMT")
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# ---- 样式（与 gernarate_sp_report 的配色保持一致）----
_SIDE_THIN = Side(style="thin", color="B4C6E7")
BORDER_HEADER = Border(left=_SIDE_THIN, right=_SIDE_THIN, top=_SIDE_THIN, bottom=Side(style="medium", color="4472C4"))
BORDER_CELL = Border(left=_SIDE_THIN, right=_SIDE_THIN, top=_SIDE_THIN, bottom=_SIDE_THIN)
FONT_HEADER = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
FONT_CELL = Font(name="Calibri", size=10)
FONT_TOTAL = Font(name="Calibri", bold=True, size=11, color="1F3864")
FONT_TITLE = Font(name="Calibri", bold=True, size=14, color="1F3864")
FONT_SUBTITLE = Font(name="Calibri", size=9, color="808080")
FILL_HEADER = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
FILL_TOTAL = PatternFill(start_color="D6DCE4", end_color="D6DCE4", fill_type="solid")
ALIGN_HEADER = Alignment(horizontal="center", vertical="center", wrap_text=True)
ALIGN_CELL = Alignment(vertical="center")
ALIGN_NUM = Alignment(horizontal="right", vertical="center")
NUM_FMT_INT = "#,##0"


# ==============================================================================
# 基础工具
# ==============================================================================
def _norm_wh(name: Any) -> str:
    """仓库名归一：明细里有双空格，直接做字典匹配会漏。"""
    return re.sub(r"\s+", " ", str(name or "")).strip()


def _wh_short(name: Any) -> str:
    key = _norm_wh(name)
    if key in WAREHOUSE_MAP:
        return WAREHOUSE_MAP[key][1]
    return key or "Unknown"


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0)


# ------------------------------------------------------------------------------
# 数量 + 单位（模板要求：单位直接跟在数字上，如 2PCS / 75Meter / 250Meter）
# ------------------------------------------------------------------------------
# 单位排序：模板里是 `4PCS+50m+40KG`，器件在前、长度/重量在后
_UNIT_ORDER = ["PCS", "SET", "KIT", "BOX", "Meter", "M", "Kg", "KG", "VOL", "ML", "L"]


def _unit_rank(unit: str) -> Tuple[int, str]:
    try:
        return (_UNIT_ORDER.index(unit), unit)
    except ValueError:
        return (len(_UNIT_ORDER), unit)


def _fmt_num(q: float) -> str:
    """数量转文本：整数不带小数点，小数最多两位（用于「数量+单位」拼接）。"""
    if abs(q - round(q)) < 1e-9:
        return f"{int(round(q)):,}"
    return f"{q:,.2f}".rstrip("0").rstrip(".")


def _qty_fmt(unit: str) -> str:
    """数字格式：显示 `2PCS`，底层仍是数字（可求和/排序/画图）。

    必须用 `General"PCS"` 而不是 `#,##0.##"PCS"` —— 后者的 `.##` 会让整数显示成
    `4.PCS`（Excel 会保留小数点占位，2026-11-03 实测渲染确认）。
    """
    u = str(unit or "").strip().replace('"', "")
    return f'General"{u}"' if u else "General"


def _qty_cell(units: Dict[str, float]) -> Tuple[Any, Optional[str]]:
    """一个统计格 -> (值, 数字格式)。

    单单位：数值 + `#,##0.##"PCS"`（显示 7PCS，仍可被 SUM/排序）
    多单位：文本 `4PCS+50Meter+40KG`（与手工模板同款；跨单位本身无法求和）
    """
    items = [(str(u or "").strip(), float(q)) for u, q in units.items() if float(q or 0)]
    if not items:
        return 0.0, None
    if len(items) == 1:
        u, q = items[0]
        return float(q), _qty_fmt(u)
    items.sort(key=lambda x: _unit_rank(x[0]))
    return "+".join(f"{_fmt_num(q)}{u}" for u, q in items), None


def _agg_units(df: pd.DataFrame, qty_col: str, keys) -> Dict[Any, Dict[str, float]]:
    """按 keys 聚合成 {key: {unit: qty}}，供 _qty_cell 出「数量+单位」。"""
    out: Dict[Any, Dict[str, float]] = {}
    if df.empty:
        return out
    unit_series = df["Unit"] if "Unit" in df.columns else pd.Series([""] * len(df), index=df.index)
    work = df.assign(_unit=unit_series.fillna("").astype(str).str.strip())
    for k, g in work.groupby(keys):
        d: Dict[str, float] = {}
        for u, q in g.groupby("_unit")[qty_col].sum().items():
            d[str(u)] = d.get(str(u), 0.0) + float(q)
        out[k] = d
    return out


def _read_detail(path: Path, required: List[str]) -> pd.DataFrame:
    """读取明细 xlsx；缺列直接报错（宁失败不产出错报表）。"""
    if not path.is_file():
        raise FileNotFoundError(f"明细文件不存在: {path}")
    df = pd.read_excel(path)
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name} 缺列: {missing}")
    return df


def _domain_key(v: Any) -> str:
    s = str(v or "").strip()
    return s if s and s.lower() not in ("nan", "none") else "Unclassified"


def _ordered_domains(domains) -> List[str]:
    present = {d for d in domains if d}
    head = [d for d in DOMAIN_ORDER if d in present]
    return head + sorted(present - set(head))


def default_period_end(today: Optional[date] = None) -> date:
    """默认周期结束日 = **最近一个已经结束的周日**。

    窗口恒为「周一 00:00:00 → 周日 23:59:59」，与「每周一 07:00 发送」严格对齐：

    - 周一 07:00 跑：end = 昨天（周日），窗口 = 上周一 ~ 上周日；
    - 周二/周三手动补跑：end 仍是刚过去的那个周日，窗口不变；
    - 周日跑：end = 上一个周日，不会取到还没结束的今天。

    ⚠ 不要用「昨天往前 7 天」：周二跑就会变成「周二 ~ 周一」，与周报口径不符
    （2026-11-03 如意指出该问题后改为按自然周对齐）。
    """
    today = today or date.today()
    # weekday(): Monday=0 ... Sunday=6；减 (weekday+1) 天必落在最近一个已结束的周日
    return today - timedelta(days=today.weekday() + 1)


def _site_map() -> Dict[str, str]:
    """本地 eflow_site：Site ID -> Site Name（缺失则返回空表，不阻断报表）。"""
    if not DB_PATH.is_file():
        return {}
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
        try:
            rows = conn.execute('SELECT "Site ID", "Site Name" FROM eflow_site').fetchall()
        finally:
            conn.close()
        return {str(a).strip(): str(b).strip() for a, b in rows if a and b}
    except Exception as exc:  # 表不存在 / 库被锁 → 降级
        print(f"[warn] 读取 eflow_site 失败，站点名将仅取工单标题: {exc}", file=sys.stderr)
        return {}


_BRACKET_RE = re.compile(r"\[([^\]]+)\]")
_LEAD_ID_RE = re.compile(r"^\s*(\d{3,6})\s*[\.\t\s]+(.*)$", re.S)


def _parse_ticket(row: pd.Series, sites: Dict[str, str]) -> Dict[str, str]:
    """从出库行解析 站点 ID / 站点名 / 问题原因 / 工单号。

    样例：
      ' 4122.[Zekepa]3G CELL DOWN'      -> id=4122 name=Zekepa  reason=3G CELL DOWN
      '4583\\tQcell LMTI ... broken'    -> id=4583 name=<eflow_site 反查> reason=...
      'Bokessa'                          -> name=Bokessa reason=''
    """
    title = "" if pd.isna(row.get("Related Ticket Title")) else str(row.get("Related Ticket Title"))
    title = title.replace("\t", " ").strip()
    raw_id = row.get("Related Ticket Site Id")
    ticket_type = "" if pd.isna(row.get("Related Ticket Type")) else str(row.get("Related Ticket Type")).strip()
    ticket_no = "" if pd.isna(row.get("Related Ticket No.")) else str(row.get("Related Ticket No.")).strip()

    site_id = "" if pd.isna(raw_id) else str(raw_id).strip()
    multi = "," in site_id
    if multi:  # 批量工单挂多个站点：ID 原样保留，站点名留空避免误导
        site_id_out = site_id
        site_id = site_id.split(",")[0].strip()
    else:
        site_id_out = site_id

    reason = title
    site_name = ""
    m = _BRACKET_RE.search(title)
    if m:
        site_name = m.group(1).strip()
        reason = (title[: m.start()] + " " + title[m.end():]).strip()
    # 标题常以站号开头（'4122. 3G CELL DOWN' / '4583 Qcell ...'）：一律剥掉，
    # 站号缺失时顺便拿它补 ID —— 不论 ID 是否已由 Related Ticket Site Id 给出。
    lead = _LEAD_ID_RE.match(reason)
    if lead:
        if not site_id:
            site_id, site_id_out = lead.group(1), lead.group(1)
        reason = lead.group(2).strip()

    if not site_name:
        site_name = sites.get(site_id, "")
    if not site_name and not ticket_type and title and not lead:
        # 标题本身就是一个站点名（如 'Bokessa'）
        site_name = title
    # 原因与站名重复（标题只有站名）时清空原因，避免 Daily report 出现无意义重复
    if reason.strip() and reason.strip() == site_name.strip():
        reason = ""
    if not reason.strip():
        fallback = row.get("Outbound Type")
        reason = "" if pd.isna(fallback) else str(fallback).strip()

    if multi:
        site_name = site_name or "(multiple sites)"
    return {
        "site_id": site_id_out,
        "site_name": site_name,
        "reason": reason,
        "ticket_type": ticket_type,
        "ticket_no": ticket_no,
    }


# ==============================================================================
# 数据准备
# ==============================================================================
def load_frames() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    inb = _read_detail(INB_FILE, ["Inbound Time", "Material Name", "Inbound Qty", "Warehouse Name", "Domain"])
    outb = _read_detail(
        OUTB_FILE,
        ["Outbound Time", "Material Name", "Outbound Qty", "Warehouse Name", "Domain",
         "Related Ticket Type", "Related Ticket Site Id", "Related Ticket Title"],
    )
    inv = _read_detail(INV_FILE, ["Material Name", "Stock Qty", "Warehouse Name", "Domain"])

    for df, col in ((inb, "Inbound Time"), (outb, "Outbound Time")):
        df[col] = pd.to_datetime(df[col], errors="coerce")
        df["_wh"] = df["Warehouse Name"].map(_wh_short)
        df["_domain"] = df["Domain"].map(_domain_key)
        df["_excluded_wh"] = df["Warehouse Name"].map(_norm_wh).eq(EXCLUDE_WAREHOUSE)

    inv["_wh"] = inv["Warehouse Name"].map(_wh_short)
    inv["_domain"] = inv["Domain"].map(_domain_key)
    inv["_excluded_wh"] = inv["Warehouse Name"].map(_norm_wh).eq(EXCLUDE_WAREHOUSE)

    inb["Inbound Qty"] = _num(inb["Inbound Qty"])
    outb["Outbound Qty"] = _num(outb["Outbound Qty"])
    inv["Stock Qty"] = _num(inv["Stock Qty"])
    return inb, outb, inv


def slice_window(inb: pd.DataFrame, outb: pd.DataFrame, start: date, end: date):
    lo = pd.Timestamp(datetime.combine(start, datetime.min.time()))
    hi = pd.Timestamp(datetime.combine(end + timedelta(days=1), datetime.min.time()))
    inb_w = inb[(inb["Inbound Time"] >= lo) & (inb["Inbound Time"] < hi) & (~inb["_excluded_wh"])].copy()
    outb_w = outb[(outb["Outbound Time"] >= lo) & (outb["Outbound Time"] < hi) & (~outb["_excluded_wh"])].copy()
    return inb_w, outb_w


# ==============================================================================
# Sheet 写入
# ==============================================================================
def _write_title(ws, text: str, ncols: int, subtitle: str = "") -> int:
    ws.cell(1, 1, text).font = FONT_TITLE
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    ws.cell(1, 1).alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 24
    if subtitle:
        ws.cell(2, 1, subtitle).font = FONT_SUBTITLE
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
        return 3
    return 2


def _write_header(ws, row: int, headers: List[str], widths: Optional[List[int]] = None) -> None:
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row, i, h)
        c.font = FONT_HEADER
        c.fill = FILL_HEADER
        c.alignment = ALIGN_HEADER
        c.border = BORDER_HEADER
    ws.row_dimensions[row].height = 30
    if widths:
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row + 1, 1)


def _write_row(ws, row: int, values: List[Any], total: bool = False, num_from: int = 2) -> None:
    for i, v in enumerate(values, start=1):
        c = ws.cell(row, i, v)
        c.font = FONT_TOTAL if total else FONT_CELL
        c.border = BORDER_CELL
        if total:
            c.fill = FILL_TOTAL
        if isinstance(v, (int, float, np.integer, np.floating)) and i >= num_from:
            c.number_format = NUM_FMT_INT
            c.alignment = ALIGN_NUM
        else:
            c.alignment = ALIGN_CELL


def sheet_summary(wb: Workbook, ctx: Dict[str, Any], domains: List[str], inb_dom: Dict[str, float],
                  out_dom: Dict[str, float], inv_dom: Dict[str, float]) -> None:
    ws = wb.create_sheet("Summary")
    ws.sheet_properties.tabColor = "2F5496"
    nxt = _write_title(ws, "SP Weekly Report", 6, ctx["subtitle"])
    ws.column_dimensions["A"].width = 42
    for col in "BCDEF":
        ws.column_dimensions[col].width = 16

    r = nxt + 1
    _write_header(ws, r, ["Metric", "Value"])
    ws.freeze_panes = None
    metrics = [
        ("Period (Monday → Sunday)", f'{ctx["start"]:%Y-%m-%d} ~ {ctx["end"]:%Y-%m-%d}'),
        ("Days", ctx["days"]),
        ("Inbound Qty (week)", ctx["inbound"]),
        ("Outbound Qty (week)", ctx["outbound"]),
        ("Net change (Inbound - Outbound)", ctx["inbound"] - ctx["outbound"]),
        ("Materials moved (distinct)", ctx["materials"]),
        ("Sites involved", ctx["sites"]),
        ("Tickets involved (WO/TT/PMT)", ctx["tickets"]),
        ("Inventory Qty (current snapshot)", ctx["inventory"]),
        ("Materials in stock", ctx["stock_materials"]),
        ("Generated at", ctx["generated"]),
    ]
    for label, val in metrics:
        r += 1
        c1 = ws.cell(r, 1, label)
        c1.font = FONT_CELL
        c1.border = BORDER_CELL
        c2 = ws.cell(r, 2, val)
        c2.font = FONT_CELL
        c2.border = BORDER_CELL
        if isinstance(val, (int, float)):
            c2.number_format = NUM_FMT_INT
            c2.alignment = ALIGN_NUM

    r += 2
    ws.cell(r, 1, "Breakdown by Domain").font = FONT_TOTAL
    r += 1
    _write_header(ws, r, ["Domain", "Inbound Qty", "Outbound Qty", "Inventory Qty (current)"])
    ws.freeze_panes = None
    tot = [0.0, 0.0, 0.0]
    for d in domains:
        vals = [d, inb_dom.get(d, 0), out_dom.get(d, 0), inv_dom.get(d, 0)]
        tot[0] += vals[1]
        tot[1] += vals[2]
        tot[2] += vals[3]
        _write_row(ws, r + 1, vals)
        r += 1
    _write_row(ws, r + 1, ["Total"] + tot, total=True)
    r += 1

    r += 2
    ws.cell(r, 1, "Notes").font = FONT_TOTAL
    notes = [
        "1. Period is a full natural week, Monday 00:00:00 → Sunday 23:59:59. The task is sent every Monday 07:00, so the window is always the previous Monday → Sunday regardless of when it is regenerated.",
        "2. Inbound/Outbound time comes from the Inbound Time / Outbound Time of the records linked to WO/TT/PMT tickets.",
        "3. Site Name / Site ID come from Related Ticket Title ([site name]) and Related Ticket Site Id; missing names are looked up in eflow_site.",
        "4. Inventory is a live snapshot at generation time, not the week-end balance.",
        f"5. Warehouse '{EXCLUDE_WAREHOUSE}' (material warehouse, not spare-parts circulation) is excluded, same as the daily SP report.",
        "6. Every quantity shows its unit (7PCS / 50Meter) and stays numeric underneath; a cell that mixes units is listed per unit (4PCS+50Meter).",
    ]
    notes.extend(ctx.get("extra_notes", []))
    for n in notes:
        r += 1
        c = ws.cell(r, 1, n)
        c.font = FONT_SUBTITLE
        c.alignment = Alignment(vertical="center", wrap_text=False)


def sheet_inventory(wb: Workbook, inv: pd.DataFrame) -> None:
    ws = wb.create_sheet("Inventory")
    ws.sheet_properties.tabColor = "548235"
    df = inv[~inv["_excluded_wh"]]
    whs = sorted(df["_wh"].unique())
    doms = _ordered_domains(df["_domain"].unique())
    piv = df.pivot_table(index="_domain", columns="_wh", values="Stock Qty", aggfunc="sum", fill_value=0)

    headers = ["Domain"] + whs + ["Total"]
    nxt = _write_title(ws, "Inventory (current snapshot)", len(headers),
                       "Stock Qty by Domain x Warehouse. Snapshot at generation time.")
    _write_header(ws, nxt, headers, [18] + [16] * (len(headers) - 1))
    r = nxt
    col_tot = {w: 0.0 for w in whs}
    grand = 0.0
    for d in doms:
        vals = [d] + [float(piv.loc[d, w]) if d in piv.index and w in piv.columns else 0.0 for w in whs]
        vals.append(sum(vals[1:]))
        for i, w in enumerate(whs):
            col_tot[w] += vals[1 + i]
        grand += vals[-1]
        _write_row(ws, r + 1, vals)
        r += 1
    _write_row(ws, r + 1, ["Total"] + [col_tot[w] for w in whs] + [grand], total=True)
    r += 1

    if (df["OwnerShip"].notna()).any() if "OwnerShip" in df.columns else False:
        r += 2
        ws.cell(r, 1, "Ownership split").font = FONT_TOTAL
        r += 1
        _write_header(ws, r, ["OwnerShip", "Stock Qty"])
        ws.freeze_panes = None
        own = df.groupby(df["OwnerShip"].fillna("Unknown"))["Stock Qty"].sum().sort_values(ascending=False)
        for k, v in own.items():
            _write_row(ws, r + 1, [str(k), float(v)])
            r += 1


def sheet_inout(wb: Workbook, inb_w: pd.DataFrame, outb_w: pd.DataFrame) -> None:
    ws = wb.create_sheet("Inbound&Outbound Summary")
    ws.sheet_properties.tabColor = "BF8F00"
    whs = sorted(set(inb_w["_wh"].unique()) | set(outb_w["_wh"].unique()))
    doms = _ordered_domains(set(inb_w["_domain"].unique()) | set(outb_w["_domain"].unique()))
    in_map = _agg_units(inb_w, "Inbound Qty", "_domain")
    out_map = _agg_units(outb_w, "Outbound Qty", ["_domain", "_wh"])

    headers = ["Domain", "Inbound Qty"] + [f"Outbound - {w}" for w in whs] + ["Outbound Total"]
    nxt = _write_title(ws, "Inbound / Outbound Summary", len(headers),
                       "Quantities carry their unit (7PCS / 50Meter). A cell that mixes units is "
                       "listed per unit joined by '+' (4PCS+50Meter), same as the manual template. "
                       "Inbound = Inbound Time in period, Outbound = Outbound Time in period.")
    _write_header(ws, nxt, headers, [18] + [17] * (len(headers) - 1))

    def _put(row: int, col: int, units: Dict[str, float], total: bool = False) -> None:
        val, fmt = _qty_cell(units)
        c = ws.cell(row, col, val)
        c.font = FONT_TOTAL if total else FONT_CELL
        c.border = BORDER_CELL
        if total:
            c.fill = FILL_TOTAL
        if fmt and isinstance(val, (int, float)):
            c.number_format = fmt
            c.alignment = ALIGN_NUM
        elif isinstance(val, (int, float)):
            c.number_format = NUM_FMT_INT
            c.alignment = ALIGN_NUM
        else:
            c.alignment = ALIGN_CELL

    r = nxt
    t_in: Dict[str, float] = {}
    t_wh: Dict[str, Dict[str, float]] = {w: {} for w in whs}
    for d in doms:
        iv = in_map.get(d, {}) or {}
        for u, q in iv.items():
            t_in[u] = t_in.get(u, 0.0) + q

        row: int = r + 1
        c = ws.cell(row, 1, d)
        c.font = FONT_CELL
        c.border = BORDER_CELL
        c.alignment = ALIGN_CELL
        _put(row, 2, iv)

        row_total: Dict[str, float] = {}
        for i, w in enumerate(whs):
            od = out_map.get((d, w), {}) or {}
            _put(row, 3 + i, od)
            for u, q in od.items():
                row_total[u] = row_total.get(u, 0.0) + q
                t_wh[w][u] = t_wh[w].get(u, 0.0) + q
        _put(row, 3 + len(whs), row_total)
        r += 1

    total_row: int = r + 1
    c = ws.cell(total_row, 1, "Total")
    c.font = FONT_TOTAL
    c.border = BORDER_CELL
    c.fill = FILL_TOTAL
    c.alignment = ALIGN_CELL
    _put(total_row, 2, t_in, total=True)
    grand: Dict[str, float] = {}
    for i, w in enumerate(whs):
        _put(total_row, 3 + i, t_wh[w], total=True)
        for u, q in t_wh[w].items():
            grand[u] = grand.get(u, 0.0) + q
    _put(total_row, 3 + len(whs), grand, total=True)


def sheet_daily(wb: Workbook, outb_w: pd.DataFrame, days: List[date], sites: Dict[str, str]) -> Dict[str, int]:
    ws = wb.create_sheet("Daily report")
    ws.sheet_properties.tabColor = "C00000"
    headers = (["No.", "Materials Name", "Material No.", "Reason for materials Outbound"]
               + [f"{d.strftime('%A')}\n{d:%m/%d}" for d in days]
               + ["Site Name", "Site ID", "Ticket Type", "Ticket No.", "Outbound Type", "Unit"])
    nxt = _write_title(ws, "Spares Outbound Daily", len(headers),
                       "One row per outbound line; quantity sits under its own outbound date and "
                       "carries its unit (1PCS / 75Meter). Weekday and date in each column always match.")
    widths = [6, 40, 20, 38] + [10] * len(days) + [22, 12, 10, 26, 20, 8]
    _write_header(ws, nxt, headers, widths)

    day_idx = {d: i for i, d in enumerate(days)}
    rows = outb_w.dropna(subset=["Outbound Time"]).copy()
    rows["_d"] = rows["Outbound Time"].dt.date
    rows = rows[rows["_d"].isin(day_idx)].sort_values(["_d", "Material Name"])

    site_count = set()
    ticket_count = set()
    r = nxt
    for n, (_, row) in enumerate(rows.iterrows(), start=1):
        t = _parse_ticket(row, sites)
        if t["site_id"]:
            site_count.add(t["site_id"])
        elif t["site_name"]:
            site_count.add(t["site_name"])
        if t["ticket_no"]:
            ticket_count.add(t["ticket_no"])
        vals: List[Any] = [
            n,
            str(row.get("Material Name") or "").strip(),
            str(row.get("Material No.") or "").strip(),
            t["reason"],
        ]
        vals += [None] * len(days)
        qty = float(row.get("Outbound Qty") or 0)
        vals[4 + day_idx[row["_d"]]] = qty
        unit = str(row.get("Unit") or "").strip()
        vals += [
            t["site_name"],
            t["site_id"],
            t["ticket_type"],
            t["ticket_no"],
            str(row.get("Outbound Type") or "").strip(),
            unit,
        ]
        _write_row(ws, r + 1, vals, num_from=5)
        # 日期列是数量（列序号 5 起）；按本行物料的单位显示成 1PCS / 75Meter
        for i in range(5, 5 + len(days)):
            c = ws.cell(r + 1, i)
            if c.value is not None:
                c.number_format = _qty_fmt(unit)
                c.alignment = ALIGN_NUM
        r += 1

    if r == nxt:
        ws.cell(nxt + 1, 1, "No outbound record in this period.").font = FONT_SUBTITLE
    return {"sites": len(site_count), "tickets": len(ticket_count)}


def sheet_top(wb: Workbook, outb_w: pd.DataFrame, inv: pd.DataFrame, start: date, end: date, top_n: int = 10) -> None:
    ws = wb.create_sheet(f"Top {top_n} Consumed Spares")
    ws.sheet_properties.tabColor = "7030A0"
    valid_inv = inv[~inv["_excluded_wh"]]
    stock = valid_inv.groupby("Material Name")["Stock Qty"].sum()

    def _units(df: pd.DataFrame) -> Dict[str, str]:
        if "Unit" not in df.columns:
            return {}
        out: Dict[str, str] = {}
        for name, u in df.dropna(subset=["Unit"]).groupby("Material Name")["Unit"].first().items():
            u = str(u).strip()
            if u:
                out[str(name)] = u
        return out

    out_units = _units(outb_w)   # 消耗量单位
    inv_units = _units(valid_inv)  # 库存单位

    g = (outb_w.groupby(["Material No.", "Material Name"])["Outbound Qty"].sum()
         .reset_index().sort_values("Outbound Qty", ascending=False).head(top_n))
    period_label = f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d}"
    headers = ["No.", "PART NUMBER", "PART NAME", f"Consumed ({period_label})", "Unit", "Current Storage"]
    nxt = _write_title(ws, f"Top {top_n} Consumed Spares", len(headers),
                       "Ranked by outbound quantity inside the period; stock is the current snapshot. "
                       "Consumed and Current Storage both show the material unit (250Meter).")
    _write_header(ws, nxt, headers, [6, 22, 46, 26, 10, 16])
    r = nxt
    for i, row in enumerate(g.itertuples(index=False), start=1):
        name = str(row[1])
        unit = out_units.get(name, "") or inv_units.get(name, "")
        vals = [i, str(row[0]), name, float(row[2]), unit, float(stock.get(name, 0))]
        _write_row(ws, r + 1, vals, num_from=4)
        ws.cell(r + 1, 4).number_format = _qty_fmt(unit)
        ws.cell(r + 1, 6).number_format = _qty_fmt(unit)
        r += 1
    if r == nxt:
        ws.cell(nxt + 1, 1, "No consumption in this period.").font = FONT_SUBTITLE


def sheet_replenishment(wb: Workbook, outb: pd.DataFrame, inv: pd.DataFrame, as_of: date,
                        notes: List[str]) -> None:
    """补库/告警表：直接复用 gernarate_sp_report.build_replenishment，避免两套口径漂移。"""
    try:
        if str(_SCRIPT_DIR) not in sys.path:
            sys.path.insert(0, str(_SCRIPT_DIR))
        from gernarate_sp_report import build_replenishment  # noqa: WPS433 (懒导入)
    except Exception as exc:
        notes.append(f"Replenishment sheet skipped: cannot import build_replenishment ({exc}).")
        return

    try:
        rep = build_replenishment(outb[~outb["_excluded_wh"]], inv[~inv["_excluded_wh"]],
                                  as_of=datetime.combine(as_of, datetime.min.time()))
    except Exception as exc:
        notes.append(f"Replenishment sheet skipped: build_replenishment failed ({exc}).")
        return

    ws = wb.create_sheet("Replenishment")
    ws.sheet_properties.tabColor = "ED7D31"
    headers = ["Material No.", "Material Name", "Domain", "Inventory Qty", "Avg Monthly Consumption",
               "Safety Stock", "Replenishment Qty", "Remark", "Alert Level"]
    nxt = _write_title(ws, "Replenishment & Alert Level", len(headers),
                       "Safety Stock = ceil(6 x avg monthly consumption); Alert = Inventory / Safety.")
    _write_header(ws, nxt, headers, [20, 46, 12, 14, 22, 13, 18, 20, 20])

    # 物料元数据：库存表优先，出库表兜底（有消耗但已零库存的物料也能带上物料号/专业域）
    inv_ok = inv[~inv["_excluded_wh"]]
    out_ok = outb[~outb["_excluded_wh"]]
    frames = []
    for df in (inv_ok, out_ok):
        if df is not None and len(df):
            part = df.groupby("Material Name").agg({"Material No.": "first", "_domain": "first"})
            part["Stock Qty"] = (df.groupby("Material Name")["Stock Qty"].sum()
                                 if "Stock Qty" in df.columns else 0)
            frames.append(part)
    meta = pd.concat(frames).groupby(level=0).first() if frames else pd.DataFrame()

    r = nxt
    for _, row in rep.iterrows():
        name = row["Material Name"]
        m = meta.loc[name] if name in meta.index else None
        alert = row.get("Alert Level", "")
        vals = [
            "" if m is None else str(m["Material No."] or ""),
            str(name),
            "" if m is None else str(m["_domain"]),
            (0.0 if m is None else float(m["Stock Qty"] or 0)),
            float(row.get("Avg Monthly Consumption", 0) or 0),
            float(row.get("Safety Stock", 0) or 0),
            None if pd.isna(row.get("Replenishment Qty")) else float(row["Replenishment Qty"]),
            str(row.get("Remark", "") or ""),
            str(alert or ""),
        ]
        _write_row(ws, r + 1, vals, num_from=4)
        r += 1
    if r == nxt:
        ws.cell(nxt + 1, 1, "No data.").font = FONT_SUBTITLE


def sheet_details(wb: Workbook, inb_w: pd.DataFrame, outb_w: pd.DataFrame, sites: Dict[str, str]) -> None:
    ws = wb.create_sheet("Details")
    ws.sheet_properties.tabColor = "808080"
    headers = ["Type", "No.", "Time", "Material No.", "Material Name", "Qty", "Unit", "Warehouse",
               "Domain", "Ticket Type", "Ticket No.", "Site ID", "Site Name"]
    nxt = _write_title(ws, "Details (period)", len(headers),
                       "Raw inbound/outbound lines inside the period, for pivoting and audit.")
    _write_header(ws, nxt, headers, [10, 24, 20, 20, 44, 8, 8, 34, 12, 11, 26, 12, 24])
    r = nxt
    for _, row in inb_w.dropna(subset=["Inbound Time"]).sort_values("Inbound Time").iterrows():
        _write_row(ws, r + 1, ["Inbound", str(row.get("Inbound No.") or ""), row["Inbound Time"],
                               str(row.get("Material No.") or ""), str(row.get("Material Name") or ""),
                               float(row.get("Inbound Qty") or 0), str(row.get("Unit") or ""),
                               str(row.get("Warehouse Name") or ""), row["_domain"], "", "", "", ""], num_from=6)
        ws.cell(r + 1, 3).number_format = "yyyy-mm-dd hh:mm"
        r += 1
    for _, row in outb_w.dropna(subset=["Outbound Time"]).sort_values("Outbound Time").iterrows():
        t = _parse_ticket(row, sites)
        _write_row(ws, r + 1, ["Outbound", str(row.get("Outbound No.") or ""), row["Outbound Time"],
                               str(row.get("Material No.") or ""), str(row.get("Material Name") or ""),
                               float(row.get("Outbound Qty") or 0), str(row.get("Unit") or ""),
                               str(row.get("Warehouse Name") or ""), row["_domain"],
                               t["ticket_type"], t["ticket_no"], t["site_id"], t["site_name"]], num_from=6)
        ws.cell(r + 1, 3).number_format = "yyyy-mm-dd hh:mm"
        r += 1
    if r == nxt:
        ws.cell(nxt + 1, 1, "No records in this period.").font = FONT_SUBTITLE


def sheet_warehouse(wb: Workbook, inb: pd.DataFrame, outb: pd.DataFrame) -> None:
    ws = wb.create_sheet("Warehouse-info")
    ws.sheet_properties.tabColor = "00B0F0"
    nxt = _write_title(ws, "Warehouse mapping", 3, "Single source of truth for warehouse naming.")
    _write_header(ws, nxt, ["Warehouse Id", "Warehouse Name", "Report Name"], [24, 60, 20])
    r = nxt
    seen = set()
    for name, (wid, short) in WAREHOUSE_MAP.items():
        _write_row(ws, r + 1, [wid, name, short])
        seen.add(name)
        r += 1
    extra = sorted({_norm_wh(x) for x in pd.concat([inb["Warehouse Name"], outb["Warehouse Name"]]).dropna()}
                   - seen - {EXCLUDE_WAREHOUSE})
    for name in extra:
        _write_row(ws, r + 1, ["", name, _wh_short(name)])
        r += 1
    _write_row(ws, r + 1, ["", f"{EXCLUDE_WAREHOUSE} (excluded)", "(excluded)"])
    ws.cell(r + 1, 2).font = FONT_SUBTITLE


# ==============================================================================
# 主流程
# ==============================================================================
def _save_workbook(wb: Workbook, path: Path, attempts: int = 4, wait_seconds: float = 2.0) -> Path:
    """原子写报表；目标持续被 Excel/WPS 占用时改用 ``_序号`` 文件名。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        wb.save(tmp)
        for attempt in range(1, attempts + 1):
            try:
                os.replace(tmp, path)
                return path
            except PermissionError:
                if attempt < attempts:
                    time.sleep(wait_seconds)
        for idx in range(1, 100):
            candidate = path.with_name(f"{path.stem}_{idx}{path.suffix}")
            if candidate.exists():
                continue
            try:
                os.replace(tmp, candidate)
                print(f"[WARN] 原报表被占用，改存: {candidate.name}")
                return candidate
            except PermissionError:
                continue
        raise PermissionError(f"保存失败：原文件及 99 个备用文件名均不可用: {path}")
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def build(out_dir: Path, week_end: date, days: int = 7) -> Dict[str, Any]:
    if days != 7:
        raise ValueError("Weekly report always covers exactly 7 days (Monday → Sunday).")
    # 强约束：周期必须是一个完整的自然周（周一 → 周日）。
    # 这样无论谁在什么时候手动补跑，产出的都是同一口径，不会出现「周二 ~ 周一」。
    if week_end.weekday() != 6:
        raise ValueError(
            f"period must end on Sunday, got {week_end:%Y-%m-%d} "
            f"({DAY_NAMES[week_end.weekday()]}); weekly window is Monday → Sunday"
        )
    start = week_end - timedelta(days=days - 1)

    inb, outb, inv = load_frames()
    inb_w, outb_w = slice_window(inb, outb, start, week_end)
    sites = _site_map()

    day_list = [start + timedelta(days=i) for i in range(days)]
    subtitle = (f"Period: {start:%Y-%m-%d} ({DAY_NAMES[start.weekday()]}) ~ "
                f"{week_end:%Y-%m-%d} ({DAY_NAMES[week_end.weekday()]})   |   "
                f"Generated: {datetime.now():%Y-%m-%d %H:%M}   |   Source: {DATA_DIR.name} snapshot")

    inb_dom = inb_w.groupby("_domain")["Inbound Qty"].sum().to_dict()
    out_dom = outb_w.groupby("_domain")["Outbound Qty"].sum().to_dict()
    inv_ok = inv[~inv["_excluded_wh"]]
    inv_dom = inv_ok.groupby("_domain")["Stock Qty"].sum().to_dict()
    domains = _ordered_domains(set(inb_dom) | set(out_dom) | set(inv_dom))

    ctx = {
        "start": start,
        "end": week_end,
        "days": days,
        "subtitle": subtitle,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "inbound": float(inb_w["Inbound Qty"].sum()),
        "outbound": float(outb_w["Outbound Qty"].sum()),
        "inventory": float(inv_ok["Stock Qty"].sum()),
        "materials": int(outb_w["Material Name"].nunique()),
        "stock_materials": int(inv_ok["Material Name"].nunique()),
        "sites": 0,
        "tickets": 0,
        "extra_notes": [],
    }

    wb = Workbook()
    wb.remove(wb.active)

    # Summary 需要 sites/tickets，而这两个数在 Daily report 里算，先算一遍
    pre = outb_w.dropna(subset=["Outbound Time"]).copy()
    pre_sites, pre_tickets = set(), set()
    for _, row in pre.iterrows():
        t = _parse_ticket(row, sites)
        (pre_sites.add(t["site_id"]) if t["site_id"] else (pre_sites.add(t["site_name"]) if t["site_name"] else None))
        if t["ticket_no"]:
            pre_tickets.add(t["ticket_no"])
    ctx["sites"] = len(pre_sites)
    ctx["tickets"] = len(pre_tickets)

    # 数据新鲜度：明细没覆盖到周期最后一天时，报表会静默少数据 → 显式写进口径说明
    latest = None
    for df, col in ((outb, "Outbound Time"), (inb, "Inbound Time")):
        if len(df):
            m = df[col].max()
            if pd.notna(m) and (latest is None or m > latest):
                latest = m
    if latest is None or latest.date() < week_end:
        got = "无任何记录" if latest is None else f"{latest:%Y-%m-%d %H:%M}"
        ctx["extra_notes"].append(
            f"WARNING: detail data only reaches {got}, which does not cover {week_end:%Y-%m-%d}. "
            f"Numbers for the last day(s) may be incomplete — check that sp_report_generate has pulled the latest data.")

    sheet_summary(wb, ctx, domains, inb_dom, out_dom, inv_dom)
    sheet_inventory(wb, inv)
    sheet_inout(wb, inb_w, outb_w)
    sheet_daily(wb, outb_w, day_list, sites)
    sheet_top(wb, outb_w, inv, start, week_end)
    sheet_replenishment(wb, outb, inv, week_end, ctx["extra_notes"])
    sheet_details(wb, inb_w, outb_w, sites)
    sheet_warehouse(wb, inb, outb)

    path = out_dir / f"SP Weekly Report {start:%Y-%m-%d} to {week_end:%Y-%m-%d}.xlsx"
    path = _save_workbook(wb, path)

    return {
        "success": True,
        "path": str(path),
        "period_start": f"{start:%Y-%m-%d}",
        "period_end": f"{week_end:%Y-%m-%d}",
        "days": days,
        "inbound": ctx["inbound"],
        "outbound": ctx["outbound"],
        "inventory": ctx["inventory"],
        "materials": ctx["materials"],
        "sites": ctx["sites"],
        "tickets": ctx["tickets"],
        "sheets": wb.sheetnames,
        "notes": ctx["extra_notes"],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the SP Weekly Report (Monday → Sunday).")
    ap.add_argument("--week-end", help="period end date YYYY-MM-DD, must be a Sunday; default: last finished Sunday")
    ap.add_argument("--days", type=int, default=7, help="window length, fixed to 7")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="output directory")
    args = ap.parse_args(argv)

    if args.week_end:
        week_end = datetime.strptime(args.week_end, "%Y-%m-%d").date()
    else:
        week_end = default_period_end()

    try:
        result = build(Path(args.out_dir), week_end, args.days)
    except Exception as exc:
        print(json.dumps({"success": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
