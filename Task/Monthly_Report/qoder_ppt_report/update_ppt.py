# -*- coding: utf-8 -*-
"""Orange Liberia 月报 PPT 更新脚本

基于 data/orange_liberia_monthly.sqlite3（RAN_UME 月粒度数据）更新：
  第 2 页  RAN Network Performance - KPIs
           - 重建折线图：过去 12 个完整月，7 个 Network KPIs 达标/未达标数量
           - 更新达标计数（😀/☹）与 Insights/KPIs under Target 表格文字
  第 3 页  Network Performance - Traffic
           - 重建 Voice/Data 月度柱形图
           - 更新 Insights 文字

说明：
  - 2026-08 为当月未完成数据，自动剔除
  - 达标值取自 my_app Contract KPIs Report (New) sheet 第 5 行 Target
  - 原文件不动，输出新文件
"""
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.util import Pt

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent
SRC_PPT = BASE_DIR / "Orange Liberia.pptx"
DB_PATH = BASE_DIR / "data" / "orange_liberia_monthly.sqlite3"

MONTH_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

COLOR_GREEN = RGBColor.from_string("00B050")
COLOR_AMBER = RGBColor.from_string("FFC000")
COLOR_RED = RGBColor.from_string("FF0000")

# Network KPIs：(名称, 表, 列, 达标值, 方向) —— 达标值来自 Excel 第 5 行
NETWORK_KPIS = [
    ("2G CSSR voice", "GSM_NW_1month", "OCI_2G_CSSR_CS(%)", 0.97, ">="),
    ("2G DCR", "GSM_NW_1month", "TCH in call drop rate(include handover)(%)", 0.02, "<="),
    ("3G CSSR", "UMTS_NW_1month",
     "U31_3G Call Setup Success Rate - CS_901593_2_UROP.RNC-MO", 0.97, ">="),
    ("3G DCR", "UMTS_NW_1month", "Ratio of CS Call Drop(%)", 0.02, "<="),
    ("3G CSSR HSDPA", "UMTS_NW_1month",
     "U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO", 0.98, ">="),
    ("3G DCR HSDPA", "UMTS_NW_1month",
     "U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO", 0.02, "<="),
    ("3G to 2G HO", "UMTS_NW_1month",
     "Cell Inter-RAT CS Outgoing Handover Success Rate(WCDMA->GSM)(%)", 0.95, ">="),
]

# ---- 第2页拆分趋势图系列定义 ----
# Access 图（4 系列）：CSSR / HO 成功率，量纲 94%~100%
ACCESS_KPIS = [
    ("2G CSSR voice",   "2G CSSR",     "0070C0"),
    ("3G CSSR",         "3G CSSR",     "00B050"),
    ("3G CSSR HSDPA",   "3G CSSR HSDPA", "FFC000"),
    ("3G to 2G HO",     "3G→2G HO",    "7030A0"),
]
ACCESS_Y_RANGE = (0.94, 1.0, "0.0%", 0.01)   # (min, max, 数字格式, 主刻度)
ACCESS_TITLE = "Access KPIs Trend (CSSR & HO)"

# DCR 图（3 系列）：掉话率，量纲 0.1%~0.3%
DCR_KPIS = [
    ("2G DCR",       "2G DCR",       "FF0000"),
    ("3G DCR",       "3G DCR",       "ED7D31"),
    ("3G DCR HSDPA", "3G DCR HSDPA", "00B050"),
]
DCR_Y_RANGE = (0.0, 0.003, "0.00%", 0.001)   # (min, max, 数字格式, 主刻度)
DCR_TITLE = "DCR KPIs Trend (Drop Call Rate)"


def _num(v):
    try:
        return float(str(v).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def month_label(dt_str):
    """'2025-08-01 00:00:00' -> 'Aug-25'"""
    y, m = int(dt_str[:4]), int(dt_str[5:7])
    return f"{MONTH_EN[m - 1]}-{y % 100:02d}"


def load_data():
    """读取月度数据，返回 (完整月份列表, KPI 月度达标统计, traffic 汇总)。"""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()

    # 当月（未完成）剔除
    current_month = datetime.now().strftime("%Y-%m")
    months = sorted({r[0][:7] for r in cur.execute(
        'SELECT "Begin Time" FROM GSM_NW_1month')})
    full_months = [m for m in months if m != current_month]

    # 每个 KPI 每月的值与达标情况
    kpi_monthly = {}  # {kpi_name: {month: value}}
    for name, table, col, tgt, direction in NETWORK_KPIS:
        rows = cur.execute(
            f'SELECT "Begin Time", "{col}" FROM "{table}"').fetchall()
        kpi_monthly[name] = {r[0][:7]: _num(r[1]) for r in rows}

    achieved = []   # 每月达标 KPI 数
    missed = []     # 每月未达标 KPI 数
    missed_names = set()
    for m in full_months:
        a, ms = 0, 0
        for name, table, col, tgt, direction in NETWORK_KPIS:
            v = kpi_monthly[name].get(m)
            if v is None:
                ms += 1
                missed_names.add(name)
                continue
            ok = v >= tgt if direction == ">=" else v <= tgt
            if ok:
                a += 1
            else:
                ms += 1
                missed_names.add(name)
        achieved.append(a)
        missed.append(ms)

    # Traffic 汇总
    def rows_map(table, cols):
        colsql = ", ".join(f'"{c}"' for c in (["Begin Time"] + cols))
        return {r[0][:7]: r[1:] for r in cur.execute(
            f'SELECT {colsql} FROM "{table}"')}

    gsm = rows_map("GSM_NW_1month", [
        "TCH total traffic number(erl)",
        "U31_ZTE_Traffic of Uplink Data TBF (GByte)_900241_2_gv4.bsc-MO",
        "U31_ZTE_Traffic of Downlink Data TBF (GByte)_901415_2_gv4.bsc-MO"])
    umts = rows_map("UMTS_NW_1month", [
        "Cell Traffic Volume, CS(Erl)",
        "U31_Cell DL Traffic Volume, PS(GB)_901411_2_UROP.RNC-MO",
        "U31_Cell UL Traffic Volume, PS(GB)_901410_2_UROP.RNC-MO"])
    fdd = rows_map("FDD_NW_1month", [
        "[FDD]DL Traffic Volume (GBytes)-new",
        "[FDD]UL Traffic Volume (GBytes)-new"])

    voice, data = [], []
    for m in full_months:
        g, u, f = gsm.get(m), umts.get(m), fdd.get(m)
        voice.append(sum(x for x in (_num(g[0]) if g else None,
                                     _num(u[0]) if u else None) if x))
        data.append(sum(x for x in (_num(g[1]) if g else None,
                                    _num(g[2]) if g else None,
                                    _num(u[1]) if u else None,
                                    _num(u[2]) if u else None,
                                    _num(f[0]) if f else None,
                                    _num(f[1]) if f else None) if x))
    con.close()
    labels = [month_label(f"{m}-01 00:00:00") for m in full_months]
    return (labels, full_months, achieved, missed, missed_names,
            voice, data, kpi_monthly)


def remove_shape(shape):
    shape._element.getparent().remove(shape._element)


def fit_table_in_page(tgf, slide_height, margin=50000):
    """压缩表格（上移+按比例缩小行高），保证底边距页面底部至少 margin EMU。"""
    top = tgf.top
    bottom = top + tgf.height
    limit = slide_height - margin
    if bottom <= limit:
        return
    need = bottom - limit
    shift = min(need, 30000)            # 最多上移 ~0.033in，避免碰到标题
    compress = need - shift
    rows_h = sum(r.height for r in tgf.table.rows)
    if rows_h > 0 and compress > 0:
        factor = (rows_h - compress) / rows_h
        for r in tgf.table.rows:
            r.height = max(int(r.height * factor), 90000)  # 不低于 0.1in
    tgf.top = top - shift


def set_cell_text(cell, text):
    cell.text_frame.word_wrap = True
    cell.text = text


def style_line_series(chart, colors):
    for ser, color in zip(chart.series, colors):
        ser.format.line.color.rgb = color
        ser.format.line.width = Pt(2.25)
        # 标记填充同色
        try:
            ser.marker.format.fill.solid()
            ser.marker.format.fill.fore_color.rgb = color
        except Exception:
            pass


def build_trend_chart(slide, name, pos, labels, series_defs, colors,
                      title, y_range, label_size=8):
    """构建带标题/底部图例的折线趋势图。

    series_defs: [(显示名, [月度值...]), ...]
    y_range: (min, max, 数字格式, 主刻度) 或 None（自动刻度）
    """
    chart_data = CategoryChartData()
    chart_data.categories = labels
    for disp, vals in series_defs:
        chart_data.add_series(disp, tuple(vals))
    gf = slide.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, *pos, chart_data)
    gf.name = name
    chart = gf.chart
    chart.has_title = True
    chart.chart_title.text_frame.text = title
    for para in chart.chart_title.text_frame.paragraphs:
        for run in para.runs:
            run.font.size = Pt(12)
            run.font.bold = True
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.legend.include_in_layout = False
    chart.legend.font.size = Pt(9)
    style_line_series(chart, colors)
    va = chart.value_axis
    if y_range:
        y_min, y_max, y_fmt, y_unit = y_range
        va.minimum_scale = y_min
        va.maximum_scale = y_max
        if y_unit is not None:
            va.major_unit = y_unit
        if y_fmt is not None:
            va.tick_labels.number_format = y_fmt
    va.tick_labels.font.size = Pt(label_size)
    va.has_major_gridlines = True
    chart.category_axis.tick_labels.font.size = Pt(label_size)
    return gf


def update_slide2(slide, slide_height, labels, full_months, achieved, missed,
                  missed_names, kpi_monthly):
    # ---- 重建 3 个横排趋势图（原 KPI 图位置，等宽分割）----
    old = next(sh for sh in slide.shapes if sh.has_chart and sh.name == "KPI")
    left, top, total_w, height = old.left, old.top, old.width, old.height
    remove_shape(old)

    gap = 150000
    w = (total_w - 2 * gap) // 3
    pos1 = (left, top, w, height)
    pos2 = (left + w + gap, top, w, height)
    pos3 = (left + 2 * (w + gap), top, w, height)

    # 图1：达标/未达标计数（保持原样式）
    build_trend_chart(
        slide, "KPI", pos1, labels,
        [("Achieved the target", achieved), ("Below the target", missed)],
        [COLOR_GREEN, COLOR_RED],
        "Monthly KPI Trend", (0, len(NETWORK_KPIS), None, None))

    # 图2：Access KPIs（CSSR & HO）
    access_series = [
        (disp, [kpi_monthly[key].get(m) for m in full_months])
        for key, disp, _ in ACCESS_KPIS]
    build_trend_chart(
        slide, "KPI_Trend_Access", pos2, labels, access_series,
        [RGBColor.from_string(c) for _, _, c in ACCESS_KPIS],
        ACCESS_TITLE, ACCESS_Y_RANGE)

    # 图3：DCR KPIs
    dcr_series = [
        (disp, [kpi_monthly[key].get(m) for m in full_months])
        for key, disp, _ in DCR_KPIS]
    build_trend_chart(
        slide, "KPI_Trend_DCR", pos3, labels, dcr_series,
        [RGBColor.from_string(c) for _, _, c in DCR_KPIS],
        DCR_TITLE, DCR_Y_RANGE)

    # ---- 更新表格 ----
    tgf = next(sh for sh in slide.shapes if sh.has_table)
    table = tgf.table
    n_total = len(NETWORK_KPIS)
    # R0 达标/未达标计数
    set_cell_text(table.cell(0, 4), f"{max(achieved)} \U0001F600")
    set_cell_text(table.cell(0, 6), f"{max(missed)} \u2639")
    # R3 Insights
    if missed_names:
        insight = (f"All Network KPIs achieved their contractual targets over the "
                   f"last 12 months, except: {', '.join(sorted(missed_names))}, "
                   f"which are under continuous monitoring.")
    else:
        insight = (f"All {n_total} Network KPIs achieved their contractual targets "
                   f"throughout the last 12 months ({labels[0]} to {labels[-1]}). "
                   f"New thresholds applied since the contract baseline; "
                   f"KPIs closest to threshold (3G to 2G HO, 3G DCR HSDPA) "
                   f"remain under continuous monitoring.")
    set_cell_text(table.cell(3, 1), insight)
    # R6-R8 KPIs under Target 明细
    if missed_names:
        set_cell_text(table.cell(6, 1), "; ".join(sorted(missed_names)))
        set_cell_text(table.cell(6, 2), "To be analyzed")
        set_cell_text(table.cell(6, 3), "To be defined")
    else:
        set_cell_text(table.cell(6, 1), "None - all Network KPIs achieved their targets")
        set_cell_text(table.cell(6, 2), "N/A")
        set_cell_text(table.cell(6, 3), "N/A")
        set_cell_text(table.cell(6, 5), "")
        set_cell_text(table.cell(6, 6), "")
    for r in (7, 8):
        for c in range(1, 7):
            set_cell_text(table.cell(r, c), "")

    # 压缩表格，防止底边超出页面
    fit_table_in_page(tgf, slide_height)


CHART_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"


def _qn(tag):
    return f"{{{CHART_NS}}}{tag}"


def excel_serial(date_str):
    """'YYYY-MM-01' -> Excel 日期序列号（模板 dateAx 使用数值时间轴）"""
    return (date.fromisoformat(date_str) - date(1899, 12, 30)).days


def _set_cache_values(cache, values):
    """替换 numCache/strCache 中的全部 pt 数据。"""
    for pt in cache.findall(_qn("pt")):
        cache.remove(pt)
    pt_count = cache.find(_qn("ptCount"))
    if pt_count is None:
        pt_count = etree.SubElement(cache, _qn("ptCount"))
    pt_count.set("val", str(len(values)))
    for i, v in enumerate(values):
        pt = etree.SubElement(cache, _qn("pt"))
        pt.set("idx", str(i))
        v_el = etree.SubElement(pt, _qn("v"))
        v_el.text = "" if v is None else ("%g" % v)


def _update_ref(el, values):
    """更新 numRef/strRef 下的缓存数据（支持 c:val > c:numRef > c:numCache 两级结构）。"""
    if el is None:
        return
    # 先找直接的 numRef/strRef 子元素
    for ref_tag in ("numRef", "strRef"):
        ref = el.find(_qn(ref_tag))
        if ref is not None:
            for cache_tag in ("numCache", "strCache"):
                cache = ref.find(_qn(cache_tag))
                if cache is not None:
                    _set_cache_values(cache, values)
                    return
            return
    # 兼容 el 本身就是 numRef/strRef
    for cache_tag in ("numCache", "strCache"):
        cache = el.find(_qn(cache_tag))
        if cache is not None:
            _set_cache_values(cache, values)
            return


def update_traffic_chart_data(chart, serials, voice, data):
    """更新模板 TrafficTrend 组合图的数据（barChart=Voice, lineChart=Data），
    保留柱形/折线/双轴/多项式趋势线等全部样式。"""
    plot_area = chart._chartSpace.find(f".//{_qn('chart')}/{_qn('plotArea')}")
    for plot in plot_area:
        tag = etree.QName(plot).localname
        if tag == "barChart":
            for ser in plot.findall(_qn("ser")):
                _update_ref(ser.find(_qn("cat")), serials)
                _update_ref(ser.find(_qn("val")), voice)
        elif tag == "lineChart":
            for ser in plot.findall(_qn("ser")):
                _update_ref(ser.find(_qn("cat")), serials)
                _update_ref(ser.find(_qn("val")), data)
        elif tag in ("catAx", "dateAx"):
            _update_ref(plot.find(_qn("cat")), serials)


def update_slide3(slide, labels, full_months, voice, data):
    # ---- 复用模板组合图，仅替换数据（保留柱形 Voice + 折线 Data + 双轴 + 趋势线）----
    gf = next(sh for sh in slide.shapes if sh.has_chart and sh.name == "TrafficTrend")
    serials = [excel_serial(f"{m}-01") for m in full_months]
    update_traffic_chart_data(gf.chart, serials, voice, data)

    # ---- 更新 Insights ----
    table = next(sh for sh in slide.shapes if sh.has_table).table
    v_growth = (voice[-1] / voice[0] - 1) * 100
    d_growth = (data[-1] / data[0] - 1) * 100
    insight = (
        f"Traffic volumes show a sustained growth over the period "
        f"({labels[0]} to {labels[-1]}).\n"
        f"Voice traffic increased from {voice[0] / 1e6:.1f} MErl to "
        f"{voice[-1] / 1e6:.1f} MErl (+{v_growth:.0f}%).\n"
        f"Data traffic increased from {data[0] / 1e6:.1f} MGB to "
        f"{data[-1] / 1e6:.1f} MGB (+{d_growth:.0f}%).\n"
        f"Source: ZTE RAN UME, NW level monthly granularity (2G/3G/4G)."
    )
    set_cell_text(table.cell(3, 1), insight)


def safe_save(prs, base_path):
    """保存 PPT；若文件被占用（PowerPoint/Excel 打开中），
    自动在文件名后追加 _序号 生成新文件。"""
    p = Path(base_path)
    i = 1
    while True:
        try:
            with open(p, "ab"):
                pass
            prs.save(str(p))
            return p
        except (PermissionError, OSError):
            i += 1
            p = Path(base_path).with_name(
                f"{Path(base_path).stem}_{i}{Path(base_path).suffix}")


def main():
    t0 = time.perf_counter()
    (labels, full_months, achieved, missed,
     missed_names, voice, data, kpi_monthly) = load_data()
    print(f"月份({len(labels)}): {labels}")
    print(f"达标数: {achieved}")
    print(f"未达标数: {missed}  未达标KPI: {missed_names or '无'}")
    print(f"Voice: {[f'{v / 1e6:.1f}M' for v in voice]}")
    print(f"Data : {[f'{d / 1e6:.1f}M' for d in data]}")

    prs = Presentation(str(SRC_PPT))
    update_slide2(prs.slides[1], prs.slide_height, labels, full_months,
                  achieved, missed, missed_names, kpi_monthly)
    update_slide3(prs.slides[2], labels, full_months, voice, data)

    now = datetime.now()
    out = safe_save(prs, BASE_DIR /
                    f"Orange Liberia - {MONTH_EN[now.month - 1]} {now.year}.pptx")
    print(f"已保存: {out}")
    print(f"运行完成，耗时 {time.perf_counter() - t0:.2f} 秒")


if __name__ == "__main__":
    main()
