# -*- coding: utf-8 -*-
"""按 Customer Service KPI Sync（表 ume_in_customer_kpi）的数据填充
OSG Weekly QoS Analysis Report 模板。

策略：不动图表/条件格式/样式 —— 直接改写 xlsx 内部 sheet XML 的单元格。

公式列
------
当前模板 ``data/in_data/OSG Weekly QoS Analysis Report.xlsx`` 是**空壳模板**
（样式/图表在，数据与公式都被清掉），因此派生列必须由本脚本写入公式本身，
不能只刷新公式缓存值。公式取自用户提供的历史带公式文件
``data/in_data/old/OSG Weekly QoS Analysis Report - Copy.xlsx``（2026-09-18 核对：
该文件共 84 个公式单元格，全部落在下列 7 张表的数据行内，与本表 FORMULA_BUILDERS
一一对应；模板/汇总行没有其它公式）：

  sheet1 PPS   C=D+F+G          E=F+G+H          J=C/B
  sheet2 USSD  C=D+F+G          E=F+G+H          I=C/B
  sheet3 VC    H2=((F2+D2)-G2)/B2                H{r}=F/E (r>=3)
  sheet4 IVR   E=B/C
  sheet6 CAPS  J=B+C+D+E+F+G+H+I                 K=J/6000     （数据源未覆盖 → 见下）
  sheet9 SMS   C=B/1500                                       （数据源未覆盖 → 见下）
  sheet10 SMS  C=B/1500                                       （数据源未覆盖 → 见下）

写入时**同时写公式与缓存值**（``<f>公式</f><v>值</v>``），并用
``fullCalcOnLoad="1"`` 让 Excel 打开时整簿重算：用 Excel 打开看到的是公式，
用 pandas/openpyxl 按 data_only 读也能拿到值。
sheet6/9/10（CAPS / SMS Traffic）的数据源不在 Customer Service KPI Sync 覆盖范围内，
保持原脚本口径：数值与公式一律清空，只在表下补一行 N/A 说明。

映射口径已用模板与表在 2026-09-08~09-12 的 5 个重叠日逐格比对验证通过。

位置
----
2026-09-18 从 `TMP/t_osg_build.py` 迁入 `backend/services/ume_in/`（原脚本是临时
目录里的一次性验证脚本，现由定时任务 `ume_in_osg_report` 每天调用，必须与
`ume_in_kpi_service` 同目录、可 import）。

用法
----
    from backend.services.ume_in.t_osg_build import build_osg_report

    build_osg_report()                        # 默认取表里最新 7 天
    build_osg_report("2026-09-08", "2026-09-14")   # 显式窗口
    build_osg_report(win_end="2026-09-14")         # 只指定结束日（起点自动 -6 天）

命令行（与旧 TMP 脚本等价，仍支持位置参数）：
    python -m backend.services.ume_in.t_osg_build 2026-09-08 2026-09-14
"""
from __future__ import annotations

import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

# backend/services/ume_in/t_osg_build.py -> my_app（旧脚本硬编码 D:\01_RPA\Task\my_app，
# 换机器/换盘符即失效；改为按文件位置推导）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.database import get_raw_connection  # noqa: E402

SRC = str(_PROJECT_ROOT / "data" / "in_data" / "OSG Weekly QoS Analysis Report.xlsx")
OUTDIR = str(_PROJECT_ROOT / "data" / "in_data")
TABLE = os.environ.get("UME_IN_TABLE", "ume_in_customer_kpi")
# 每次生成带窗口日期的新文件，旧文件只保留最近 N 份（避免 data/in_data 无限增长）
KEEP_REPORTS = int(os.environ.get("OSG_KEEP_REPORTS", "10"))
_REPORT_RE = re.compile(r"^OSG Weekly QoS Analysis Report_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.xlsx$")

# ---------------- 1. 取数 ----------------
def _num(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f == int(f) else f


def _load_rows() -> list[dict]:
    """读取 ume_in_customer_kpi 全表，附加 _day（Begin Time 的日期部分）。"""
    conn = get_raw_connection()
    try:
        cur = conn.cursor()
        cur.execute(f'SELECT * FROM "{TABLE}"')
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    for r in rows:
        r["_day"] = str(r.get("Begin Time") or "")[:10]
    return rows


def _pick(rows, kpi, day, col, service=None):
    for r in rows:
        if r["KPI"] == kpi and r["_day"] == day and (service is None or r["SERVICE"] == service):
            return _num(r.get(col))
    return None


def _latest_day(rows) -> str | None:
    days = [r["_day"] for r in rows if r.get("_day")]
    return max(days) if days else None


def _resolve_window(rows, win_start=None, win_end=None):
    """解析报告窗口（固定 7 天）。都不传时取表里最新一天作为结束日。"""
    if not win_end:
        win_end = _latest_day(rows)
        if not win_end:
            raise ValueError(f"表 {TABLE} 无数据，无法确定报告窗口")
    end_dt = datetime.strptime(str(win_end)[:10], "%Y-%m-%d")
    if win_start:
        start_dt = datetime.strptime(str(win_start)[:10], "%Y-%m-%d")
        if (end_dt - start_dt).days != 6:
            raise ValueError(f"报告窗口必须为 7 天：{win_start} ~ {win_end}")
    else:
        start_dt = end_dt - timedelta(days=6)
    days = [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    return days, days[0], days[-1]


def _sum(*vals):
    """None 参与即整体 None（数据缺失时不伪造 0）。"""
    if any(v is None for v in vals):
        return None
    return sum(vals)


def _div(a, b):
    """比值：按 Excel 的 15 位有效数字序列化，缓存值与 Excel 自己写出的文件逐位一致。"""
    if a is None or b in (None, 0):
        return None
    return float(f"{a / b:.15g}")


def _build_daily(rows, days):
    """每日原始值：{sheet_xml: {col: [7 个值]}}"""
    daily = {}

    # PPS: B=Total Call Attempt, D=Total Number of Success, F=Balance Insufficent,
    #      G=User status, H=Network Failure(Other User Failed), I=System Failure
    daily["sheet1.xml"] = {
        "B": [_pick(rows, "PPS", d, "Call attempts") for d in days],
        "D": [_pick(rows, "PPS", d, "Success Times") for d in days],
        "F": [_pick(rows, "PPS", d, "Balance Insufficient Times") for d in days],
        "G": [_pick(rows, "PPS", d, "User Status Abnormal Times") for d in days],
        "H": [_pick(rows, "PPS", d, "Other User Failed Times") for d in days],
        "I": [_pick(rows, "PPS", d, "System Failed Times") for d in days],
    }
    # USSD: B=Total Call Attempt, D=Total Send Success, F=User Fail, G=Database error, H=System Fail
    daily["sheet2.xml"] = {
        "B": [_pick(rows, "USSD", d, "Call Attempts") for d in days],
        "D": [_pick(rows, "USSD", d, "Send Success Times") for d in days],
        "F": [_pick(rows, "USSD", d, "User Fail Times") for d in days],
        "G": [_pick(rows, "USSD", d, "DataBase result error Times") for d in days],
        "H": [_pick(rows, "USSD", d, "System Fail Times") for d in days],
    }
    # VC: 只取 Nzxin_ImpVcRecharge_0（与模板历史值一致；VcManage 小流量不计入）
    vc_svc = "Nzxin_ImpVcRecharge_0"
    daily["sheet3.xml"] = {
        "B": [_pick(rows, "VC", d, "Recharge received times", vc_svc) for d in days],
        "C": [_pick(rows, "VC", d, "Recharge success times", vc_svc) for d in days],
        "D": [_pick(rows, "VC", d, "Recharge failed times", vc_svc) for d in days],
        "E": [_pick(rows, "VC", d, "User recharge times", vc_svc) for d in days],
        "F": [_pick(rows, "VC", d, "User recharge success times", vc_svc) for d in days],
        "G": [_pick(rows, "VC", d, "User recharge failed times", vc_svc) for d in days],
    }
    # IVR: B=Total PA, C=PA Times（模板中二者恒等）, D=PA Failed Times
    daily["sheet4.xml"] = {
        "B": [_pick(rows, "IVR", d, "PA Times") for d in days],
        "C": [_pick(rows, "IVR", d, "PA Times") for d in days],
        "D": [_pick(rows, "IVR", d, "PA Failed Times") for d in days],
    }
    # P4M: B=Request, C=Subscribe, D=Black list, E=White list；F=Total P4M Users 同步不覆盖 → 清空
    daily["sheet5.xml"] = {
        "B": [_pick(rows, "P4M", d, "Request Times") for d in days],
        "C": [_pick(rows, "P4M", d, "Subscribe Times") for d in days],
        "D": [_pick(rows, "P4M", d, "Black list management Times") for d in days],
        "E": [_pick(rows, "P4M", d, "White list management Times") for d in days],
        "F": [None] * 7,
    }
    # CPU Resource: OSG 网元日均 CPU 利用率
    daily["sheet7.xml"] = {
        "B": [_pick(rows, "CPU", d, "Usage average ratio of CPU(%)", "CommonS_OSG_0") for d in days],
    }
    # Memory Resource: OSG 网元
    daily["sheet8.xml"] = {
        "B": [_pick(rows, "MEM", d, "Capacity of memory(KB)", "CommonS_OSG_0") for d in days],
        "C": [_pick(rows, "MEM", d, "Size of used memory(KB)", "CommonS_OSG_0") for d in days],
        "D": [_pick(rows, "MEM", d, "Size of free memory(KB)", "CommonS_OSG_0") for d in days],
        "E": [_pick(rows, "MEM", d, "Mean ratio of the memory usage(%)", "CommonS_OSG_0") for d in days],
    }
    # OSG CAPS / SMS Traffic：同步不覆盖 → 只保留日期，数值与公式全部清空
    daily["sheet6.xml"] = {c: [None] * 7 for c in "BCDEFGHIJK"}
    daily["sheet9.xml"] = {c: [None] * 7 for c in "BC"}
    daily["sheet10.xml"] = {c: [None] * 7 for c in "BC"}
    return daily


def _build_derived(daily, days):
    """公式单元格的缓存值（Excel 打开时会重算，这里同步写正确值）。"""

    def g(sheet, col, i):
        return daily[sheet][col][i]

    derived = {}
    # PPS: C=D+F+G, E=F+G+H, J=C/B
    derived["sheet1.xml"] = {}
    for i in range(7):
        c = _sum(g("sheet1.xml", "D", i), g("sheet1.xml", "F", i), g("sheet1.xml", "G", i))
        e = _sum(g("sheet1.xml", "F", i), g("sheet1.xml", "G", i), g("sheet1.xml", "H", i))
        r = 4 + i
        derived["sheet1.xml"][f"C{r}"] = c
        derived["sheet1.xml"][f"E{r}"] = e
        derived["sheet1.xml"][f"J{r}"] = _div(c, g("sheet1.xml", "B", i))
    # USSD: C=D+F+G, E=F+G+H, I=C/B
    derived["sheet2.xml"] = {}
    for i in range(7):
        c = _sum(g("sheet2.xml", "D", i), g("sheet2.xml", "F", i), g("sheet2.xml", "G", i))
        e = _sum(g("sheet2.xml", "F", i), g("sheet2.xml", "G", i), g("sheet2.xml", "H", i))
        r = 3 + i
        derived["sheet2.xml"][f"C{r}"] = c
        derived["sheet2.xml"][f"E{r}"] = e
        derived["sheet2.xml"][f"I{r}"] = _div(c, g("sheet2.xml", "B", i))
    # VC: 第 2 行 ((F+D)-G)/B，其余行 F/E
    derived["sheet3.xml"] = {}
    for i in range(7):
        r = 2 + i
        if r == 2:
            num = _sum(g("sheet3.xml", "F", i), g("sheet3.xml", "D", i))
            num = None if (num is None or g("sheet3.xml", "G", i) is None) else num - g("sheet3.xml", "G", i)
            derived["sheet3.xml"][f"H{r}"] = _div(num, g("sheet3.xml", "B", i))
        else:
            derived["sheet3.xml"][f"H{r}"] = _div(g("sheet3.xml", "F", i), g("sheet3.xml", "E", i))
    # IVR: E=B/C
    derived["sheet4.xml"] = {}
    for i in range(7):
        derived["sheet4.xml"][f"E{2 + i}"] = _div(g("sheet4.xml", "B", i), g("sheet4.xml", "C", i))
    return derived


# 各表数据起始行 + 需要写日期的列
LAYOUT = {
    "sheet1.xml": (4, "A"), "sheet2.xml": (3, "A"), "sheet3.xml": (2, "A"),
    "sheet4.xml": (2, "A"), "sheet5.xml": (2, "A"), "sheet6.xml": (3, "A"),
    "sheet7.xml": (2, "A"), "sheet8.xml": (2, "A"), "sheet9.xml": (3, "A"),
    "sheet10.xml": (3, "A"),
}

# 公式列：{sheet: {列: 公式模板}}，{r} 为行号占位符。
# 取自 data/in_data/old/OSG Weekly QoS Analysis Report - Copy.xlsx 的原始模板公式
# （逐格核对见模块 docstring）。只列数据行内的公式列；模板自身若已有 <f> 也会被保留。
FORMULA_BUILDERS = {
    "sheet1.xml": {"C": "D{r}+F{r}+G{r}", "E": "F{r}+G{r}+H{r}", "J": "C{r}/B{r}"},
    "sheet2.xml": {"C": "D{r}+F{r}+G{r}", "E": "F{r}+G{r}+H{r}", "I": "C{r}/B{r}"},
    # VC 第 2 行口径特殊：(成功+失败-用户失败)/总次数
    "sheet3.xml": {"H": "((F{r}+D{r})-G{r})/B{r}"},
    "sheet4.xml": {"E": "B{r}/C{r}"},
}
# sheet3 第 3 行起改为成功率 = 成功/用户次数
FORMULA_OVERRIDES = {("sheet3.xml", 2): {"H": "F{r}/E{r}"}}


def _formulas_for(sheet: str, row: int) -> dict:
    """该行需要写入的 {列: 公式}（含按行覆盖的特殊口径）。"""
    out = {}
    for col, tpl in FORMULA_BUILDERS.get(sheet, {}).items():
        out[col] = tpl.format(r=row)
    for (s, r0), cols in FORMULA_OVERRIDES.items():
        if s == sheet and row > r0:
            for col, tpl in cols.items():
                out[col] = tpl.format(r=row)
    return out

# 取不到数据的小节 → 数据区下方留一行说明（不改动任何原有内容，纯新增单元格）
NOTES = {
    "sheet6.xml": ("A11", "N/A - not covered by Customer Service KPI Sync "
                          "(source: EM System CAPS dashboard, peak hour 20H)"),
    "sheet9.xml": ("A11", "N/A - not covered by Customer Service KPI Sync "
                          "(source: SMS license usage report)"),
    "sheet10.xml": ("A11", "N/A - not covered by Customer Service KPI Sync "
                           "(source: SMS license usage report)"),
    "sheet5.xml": ("A9", "N/A - Total P4M Users not covered by Customer Service KPI Sync"),
}

# ---------------- 2. XML 改写 ----------------
CELL_RE = r'<c r="%s"([^>]*?)(?:/>|>(.*?)</c>)'


def _set_cell(xml, ref, value, sheet, formula=None):
    """写入单元格。

    - ``formula`` 给出时写 ``<f>公式</f><v>缓存值</v>``（值可为 None，此时只写公式）；
    - 未给公式但原单元格自带 ``<f>`` 时保留原公式，只刷新缓存值（兼容"模板自带公式"的情形）；
    - ``t="…"`` 属性一律去掉（数值/公式单元格不能带字符串类型标记）。
    """
    pat = re.compile(CELL_RE % re.escape(ref), re.S)
    m = pat.search(xml)
    if not m:
        raise KeyError(f"{sheet}!{ref} 单元格不存在")
    attrs = re.sub(r'\st="[^"]*"', "", m.group(1))
    body = m.group(2)

    if formula is not None:
        f_xml = f"<f>{formula}</f>"
    else:
        f_xml = ""
        if body:
            fm = re.search(r"<f[^>]*/>|<f[^>]*>.*?</f>", body, re.S)
            if fm:
                f_xml = fm.group(0)

    if value is None and not f_xml:
        new = f'<c r="{ref}"{attrs}/>'
    elif value is None:
        new = f'<c r="{ref}"{attrs}>{f_xml}</c>'
    else:
        new = f'<c r="{ref}"{attrs}>{f_xml}<v>{value}</v></c>'
    return xml[:m.start()] + new + xml[m.end():]


def _col_idx(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


ROW_RE = r'<row([^>]*?)r="(\d+)"([^>]*?)(?:/>|>(.*?)</row>)'


def _ensure_text_cell(xml, ref, text, sheet):
    """把 ref（列 A、行号大于已有数据行）写成 inlineStr；行不存在则新建行。"""
    mref = re.match(r"([A-Z]+)(\d+)", ref)
    col, rowno = mref.group(1), int(mref.group(2))
    newcell = f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'

    rows = list(re.finditer(ROW_RE, xml, re.S))
    target = None
    for rm in rows:
        if int(rm.group(2)) == rowno:
            target = rm
            break
    if target:
        body = target.group(4) or ""
        # 按列序插入
        pos = len(body)
        for cm in re.finditer(r'<c r="([A-Z]+)\d+"', body):
            if _col_idx(cm.group(1)) > _col_idx(col):
                pos = cm.start()
                break
        body2 = body[:pos] + newcell + body[pos:]
        return (xml[:target.start()]
                + f'<row{target.group(1)}r="{rowno}"{target.group(3)}>{body2}</row>'
                + xml[target.end():])

    # 新建行：插到最后一个行号小于 rowno 的 </row> 之后
    ins = None
    for rm in rows:
        if int(rm.group(2)) < rowno:
            ins = rm.end()
    if ins is None:
        raise KeyError(f"{sheet}!{ref} 无法定位插入点")
    return xml[:ins] + f'<row r="{rowno}">{newcell}</row>' + xml[ins:]


def _set_formula_cache(xml, ref, val):
    """只替换公式单元格里已有的 <v>…</v>，不动 <f>；val 为 None 时保持原值。

    仅用于"模板自带公式"的兜底刷新；本模板已无公式，派生列走 FORMULA_BUILDERS。
    """
    if val is None:
        return xml
    m = re.search(CELL_RE % re.escape(ref), xml, re.S)
    if not m or not m.group(2) or "<f" not in m.group(2):
        return xml
    body = re.sub(r"<v>.*?</v>", f"<v>{val}</v>", m.group(2), count=1, flags=re.S)
    return xml[:m.start()] + f'<c r="{ref}"{m.group(1)}>{body}</c>' + xml[m.end():]


def _prune_old_reports(outdir: str, keep: int) -> int:
    """只保留最近 keep 份带窗口日期的产物，返回删除数量。"""
    if keep <= 0:
        return 0
    files = []
    for p in Path(outdir).glob("OSG Weekly QoS Analysis Report_*.xlsx"):
        if _REPORT_RE.match(p.name):
            files.append(p)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for p in files[keep:]:
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


# ---------------- 3. 生成新文件 ----------------
def build_osg_report(win_start=None, win_end=None, src=None, outdir=None,
                     keep=None) -> dict:
    """按 ume_in_customer_kpi 的数据生成 OSG Weekly QoS Analysis Report。

    Args:
        win_start / win_end: 报告窗口（7 天）。都不传时取表里最新一天作为结束日。
        src: 模板 xlsx 路径（默认 data/in_data/OSG Weekly QoS Analysis Report.xlsx）。
        outdir: 产物目录（默认 data/in_data）。
        keep: 保留最近几份产物（默认 KEEP_REPORTS）。

    Returns:
        {success, output, file_name, win_start, win_end, days, rows, missing,
         formulas_written, pruned}
        missing: {sheet: 取不到的单元格数}，用于判断是否整窗无数据。
        formulas_written: 写入的公式单元格数（当前口径 = 56：sheet1/2 各 21 + sheet3/4 各 7）。
    """
    src = str(src or SRC)
    outdir = str(outdir or OUTDIR)
    keep = KEEP_REPORTS if keep is None else keep
    if not os.path.isfile(src):
        return {"success": False, "error": f"模板不存在: {src}"}

    rows = _load_rows()
    days, win_start, win_end = _resolve_window(rows, win_start, win_end)
    daily = _build_daily(rows, days)
    derived = _build_derived(daily, days)
    serial = {d: (datetime.strptime(d, "%Y-%m-%d") - datetime(1899, 12, 30)).days for d in days}

    # 统计缺口（只统计应填数值的列；日期列不算）
    missing = {}
    for sheet, coldata in daily.items():
        n = sum(1 for vals in coldata.values() for v in vals if v is None)
        if n:
            missing[sheet] = n
    filled = sum(1 for coldata in daily.values()
                 for vals in coldata.values() for v in vals if v is not None)
    if filled == 0:
        return {"success": False,
                "error": f"窗口 {win_start} ~ {win_end} 在表 {TABLE} 中无任何数据",
                "win_start": win_start, "win_end": win_end, "days": days, "missing": missing}

    out = os.path.join(outdir, f"OSG Weekly QoS Analysis Report_{win_start}_{win_end}.xlsx")
    os.makedirs(outdir, exist_ok=True)
    zin = zipfile.ZipFile(src)
    patched = {}
    formulas_written = 0
    for sheet, coldata in daily.items():
        name = "xl/worksheets/" + sheet
        xml = zin.read(name).decode("utf-8")
        first_row, datecol = LAYOUT[sheet]
        for i, day in enumerate(days):
            r = first_row + i
            xml = _set_cell(xml, f"{datecol}{r}", serial[day], sheet)
            for col, vals in coldata.items():
                xml = _set_cell(xml, f"{col}{r}", vals[i], sheet)
            # 公式列：写公式 + 由 _build_derived 算出的缓存值（Excel 打开时会重算）
            for col, formula in _formulas_for(sheet, r).items():
                ref = f"{col}{r}"
                xml = _set_cell(xml, ref, derived.get(sheet, {}).get(ref), sheet,
                                formula=formula)
                formulas_written += 1
        # 模板自带公式（非本脚本管理的公式列）：只刷新缓存值，不动公式
        for ref, val in derived.get(sheet, {}).items():
            xml = _set_formula_cache(xml, ref, val)
        if sheet in NOTES:
            ref, text = NOTES[sheet]
            xml = _ensure_text_cell(xml, ref, text, sheet)
        patched[name] = xml.encode("utf-8")

    # 强制 Excel 打开时整簿重算，避免缓存值与公式不一致
    wbxml = zin.read("xl/workbook.xml").decode("utf-8")
    wbxml = wbxml.replace('<calcPr calcId="144525"/>', '<calcPr calcId="144525" fullCalcOnLoad="1"/>')
    if "fullCalcOnLoad" not in wbxml:
        wbxml = re.sub(r"<calcPr([^>]*)/>", r'<calcPr\1 fullCalcOnLoad="1"/>', wbxml)
    patched["xl/workbook.xml"] = wbxml.encode("utf-8")

    # 校验：每份 sheet XML 必须可解析
    for b in patched.values():
        ET.fromstring(b)

    zout = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED)
    try:
        for item in zin.infolist():
            if item.filename in patched:
                zout.writestr(item, patched[item.filename])
            else:
                zout.writestr(item, zin.read(item.filename))
    finally:
        zout.close()
        zin.close()

    pruned = _prune_old_reports(outdir, keep)
    return {
        "success": True,
        "output": out,
        "file_name": os.path.basename(out),
        "win_start": win_start,
        "win_end": win_end,
        "days": days,
        "rows": len(rows),
        "missing": missing,
        "formulas_written": formulas_written,
        "pruned": pruned,
    }


def main(argv=None) -> int:
    """命令行入口：python -m backend.services.ume_in.t_osg_build [START] [END]"""
    argv = list(sys.argv[1:] if argv is None else argv)
    win_start = argv[0] if len(argv) > 0 and argv[0] else None
    win_end = argv[1] if len(argv) > 1 and argv[1] else None
    res = build_osg_report(win_start, win_end)
    if not res.get("success"):
        print("FAILED:", res.get("error"))
        return 1
    print("WROTE:", res["output"])
    if res.get("missing"):
        print("MISSING:", res["missing"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
