# -*- coding: utf-8 -*-
"""TTs and MTTR (Hour) 报表生成 —— 把人工核对过的 TMP/_gen_tt_mttr.py 口径固化为定时任务。

数据源：`liberia_email_1h` 链路（eflow_sync 每小时 :00）产出的
`data/eflow/tt_reports/Liberia Orange Site Down hourly Report_*.xlsx` 的 **Processed Data** 页。
本模块只读本地文件、只写本地文件，不调用 eFlow API，故归 m 组（内务轻任务）。

三个 sheet（建表顺序 == tab 顺序）：
  Summary   —— 分月 TTs / MTTR / Target（P1~P4 + 未填等级的 N/A 块）+ P1~P4 四张组合图；
               统计单元格全部是 COUNTIFS/AVERAGEIFS 公式，不是写死的值
  Raw Data  —— 有 WO 的原始工单（保留源表全部列，不按月份裁剪）
  ZTE       —— 在 Raw Data 基础上过滤「告警发生→告警清除历时 < 48h」+「Site Category 非空」
               +「告警月份 >= 2026-01」，并追加 MTTR (Hour) / Month / SLA Target (Hour) 三列

口径来自 2026-10-04 与用户逐条确认，并经 WPS COM 重算与 pandas 独立复算对拍（150 格零差异），
改动过滤条件前先看 `tt_mttr_report.md`。
"""
from __future__ import annotations

import glob
import logging
import os
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_BASE = Path(__file__).resolve().parent.parent.parent

REPORT_DIR = _BASE / "data" / "eflow" / "tt_reports"
# 源文件通配（与 email_reports._SOURCES 的 liberia_1h 同源）
SOURCE_PATTERN = "Liberia Orange Site Down hourly Report_*.xlsx"
SOURCE_SHEET = "Processed Data"
OUTPUT_PREFIX = "TTs and MTTR (Hour)"
# 源表列名契约：缺任一列说明上游报表改版，必须显式失败而不是静默出错数
REQUIRED_COLS = ["WO No.", "Alarm Occur Time", "Alarm Clear Time", "Ticket Severity", "Site Category"]

MTTR_LIMIT_H = 48.0
MONTH_FROM = "2026-01"
TARGETS = {"P1": 4, "P2": 8, "P3": 16, "P4": 48}
SEVERITIES = ["P1", "P2", "P3", "P4"]
# 源表有少量工单没填 Ticket Severity，单列一块，避免被四个等级块静默丢掉
BLOCKS = SEVERITIES + ["N/A"]
# 每次生成一个新文件（文件名带时间戳），本目录**只保留最新一份**（2026-10-05 用户要求）。
# 为什么不能完全不清理：本任务写的是 tt_reports，而 eflow_data_mapper._cleanup_old_tt_reports
# 的清理名单里没有本产物（它只清自己那 8 个 pattern），旧文件没人管就会一直堆。
# 为什么先前是 10：留几份便于对比历次生成；现改为 1，目录里始终只有当期报告。
KEEP_FILES = 1

BAR, LINE, TGT = "#8EA9DB", "#00B0F0", "#FF0000"


def _latest_source() -> Path:
    """取最新一份小时报表作为数据源（按修改时间）。"""
    cands = sorted(glob.glob(str(REPORT_DIR / SOURCE_PATTERN)), key=os.path.getmtime)
    if not cands:
        raise FileNotFoundError(
            f"未找到数据源：{REPORT_DIR} 下没有 {SOURCE_PATTERN}（上游 eflow_sync 未产出）")
    return Path(cands[-1])


def _output_path(now: datetime) -> Path:
    """输出路径：`TTs and MTTR (Hour)_YYYY-MM-DD_HH-MM-SS.xlsx`；已占用则按项目规则加 _N。"""
    stem = f"{OUTPUT_PREFIX}_{now.strftime('%Y-%m-%d_%H-%M-%S')}"
    target = REPORT_DIR / f"{stem}.xlsx"
    seq = 1
    while target.exists():
        target = REPORT_DIR / f"{stem}_{seq}.xlsx"
        seq += 1
    return target


def _prune_old_outputs(keep: Path | None = None) -> int:
    """只保留最新一份本任务产物（KEEP_FILES=1），返回删除数（被占用的文件跳过）。

    ⚠ 匹配用 `OUTPUT_PREFIX*.xlsx` 而不是 `OUTPUT_PREFIX_*.xlsx`：
    早期人工核对留下的 `TTs and MTTR (Hour).xlsx`（无下划线）也属于本任务产物，
    且它同样在 email_reports._SOURCES 的下载白名单里，用带下划线的窄通配
    会把它永久留下 —— 用户要的是「目录里只剩最新一份」。
    `keep` 传本次刚写出的文件，避免极端情况下（同秒重跑）把自己删掉。
    """
    cands = sorted(glob.glob(str(REPORT_DIR / f"{OUTPUT_PREFIX}*.xlsx")),
                   key=os.path.getmtime, reverse=True)
    if keep is not None:
        keep_res = str(keep.resolve())
        cands = [p for p in cands if str(Path(p).resolve()) != keep_res]
    removed = 0
    for path in cands[KEEP_FILES - 1:]:
        try:
            os.remove(path)
            removed += 1
            logger.info("[CLEAN] %s", os.path.basename(path))
        except OSError as exc:
            logger.warning("[CLEAN] 跳过（占用或权限）%s: %s", os.path.basename(path), exc)
    return removed


def _load_and_filter(src: Path):
    """读源表 → 算 MTTR → 两级裁剪（Raw Data / ZTE），返回三个 DataFrame 与剔除计数。"""
    import pandas as pd

    df = pd.read_excel(src, sheet_name=SOURCE_SHEET)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"源表 {SOURCE_SHEET} 页缺少必需列 {missing}，上游报表结构已变更")

    cols = [c for c in df.columns if c != "Index"]
    occur = pd.to_datetime(df["Alarm Occur Time"], errors="coerce")
    clear = pd.to_datetime(df["Alarm Clear Time"], errors="coerce")
    df["_mttr"] = (clear - occur).dt.total_seconds() / 3600.0

    # ① 有 WO 的工单进 Raw Data（保留源表全部列，不按月份/历时裁剪）
    has_wo = df["WO No."].notna() & (df["WO No."].astype(str).str.strip() != "")
    raw = df[has_wo].copy()
    raw["Month"] = pd.to_datetime(raw["Alarm Occur Time"], errors="coerce").dt.strftime("%Y-%m")

    # ② ZTE：告警发生→告警清除历时 < 48h 且 Site Category 非空 且 告警月份 >= MONTH_FROM
    sc = raw["Site Category"].astype(str).str.strip()
    has_cat = raw["Site Category"].notna() & ~sc.isin(("", "nan", "None"))
    measured = raw["_mttr"].notna() & (raw["_mttr"] >= 0)
    closed_in_limit = measured & (raw["_mttr"] < MTTR_LIMIT_H)
    in_scope = closed_in_limit & has_cat & (raw["Month"] >= MONTH_FROM)

    flt = raw[in_scope].copy()
    flt["MTTR (Hour)"] = flt["_mttr"].round(4)
    flt["SLA Target (Hour)"] = flt["Ticket Severity"].map(TARGETS)

    dropped = {
        "uncleared": int(raw["_mttr"].isna().sum()),
        "negative": int((raw["_mttr"] < 0).sum()),
        "over_limit": int((measured & (raw["_mttr"] >= MTTR_LIMIT_H)).sum()),
        "no_site_category": int((closed_in_limit & ~has_cat & (raw["Month"] >= MONTH_FROM)).sum()),
        "before_month_from": int((closed_in_limit & has_cat & (raw["Month"] < MONTH_FROM)).sum()),
    }

    # 派生列插在 Alarm Clear Time 之后，让 MTTR 与它的两个输入列相邻
    cut = cols.index("Alarm Clear Time") + 1
    flt_cols = cols[:cut] + ["MTTR (Hour)", "Month", "SLA Target (Hour)"] + cols[cut:]
    return df, raw, flt, cols, flt_cols, dropped


def _monthly_stats(flt, months):
    """按 (等级, 月份) 复算 TTs 与 MTTR 均值，既作公式缓存值，也作自检依据。"""
    import pandas as pd

    def sev_mask(frame, sev):
        col = frame["Ticket Severity"]
        return col.isna() if sev == "N/A" else col == sev

    truth = {}
    for sev in BLOCKS:
        sub = flt[sev_mask(flt, sev)]
        for m in months:
            s = sub[sub["Month"] == m]["MTTR (Hour)"]
            truth[(sev, m)] = (int(len(s)), round(float(s.mean()), 2) if len(s) else None)
    total = sum(cnt for cnt, _ in truth.values())
    if total != len(flt):
        raise AssertionError(f"等级分块未覆盖全部过滤后工单：分块合计 {total} != ZTE {len(flt)}")
    return truth


def _col_letter(idx0: int) -> str:
    """0-based 列号 → Excel 列字母。"""
    s = ""
    idx0 += 1
    while idx0:
        idx0, rem = divmod(idx0 - 1, 26)
        s = chr(65 + rem) + s
    return s


def _dump(ws, frame, columns, fmt):
    """把 DataFrame 逐格写入（空值写 blank、时间列带格式），返回数据行数。"""
    import pandas as pd

    for c, name in enumerate(columns):
        ws.write_string(0, c, str(name), fmt["hdr"])
    ws.set_row(0, 26)
    vals = frame[columns].astype(object).where(pd.notna(frame[columns]), None).values.tolist()
    for r, row in enumerate(vals, start=1):
        for c, v in enumerate(row):
            if v is None or v is pd.NaT:
                ws.write_blank(r, c, None)
            elif isinstance(v, (pd.Timestamp, datetime)):
                ws.write_datetime(r, c, v.to_pydatetime() if isinstance(v, pd.Timestamp) else v,
                                  fmt["dt"])
            elif isinstance(v, bool):
                ws.write_string(r, c, str(v))
            elif isinstance(v, (int, float)):
                ws.write_number(r, c, v, fmt["n2"] if columns[c] == "MTTR (Hour)" else None)
            else:
                ws.write_string(r, c, str(v))
    return len(vals)


def _formats(wb):
    return {
        "title": wb.add_format({"bold": True, "font_size": 16, "font_color": "#1F4E79"}),
        "meta_k": wb.add_format({"bold": True, "font_color": "#404040", "font_size": 10}),
        "meta_v": wb.add_format({"font_color": "#404040", "font_size": 10}),
        "blk": wb.add_format({"bold": True, "font_color": "#00405A", "bg_color": "#00B0F0",
                              "align": "center", "valign": "vcenter", "border": 1,
                              "border_color": "#808080"}),
        "head": wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#2E75B6",
                               "align": "center", "valign": "vcenter", "border": 1,
                               "border_color": "#FFFFFF"}),
        "cell": wb.add_format({"border": 1, "border_color": "#BFBFBF", "align": "center"}),
        "num2": wb.add_format({"border": 1, "border_color": "#BFBFBF", "align": "center",
                               "num_format": "0.00"}),
        "tgt": wb.add_format({"border": 1, "border_color": "#BFBFBF", "align": "center",
                              "font_color": "#C00000", "bold": True}),
        "hdr": wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#2E75B6",
                              "align": "center", "valign": "vcenter", "text_wrap": True}),
        "dt": wb.add_format({"num_format": "yyyy-mm-dd hh:mm:ss"}),
        "n2": wb.add_format({"num_format": "0.00"}),
    }


def _write_workbook(out: Path, src: Path, df, raw, flt, raw_cols, flt_cols, months, truth):
    """按 Summary → Raw Data → ZTE 的顺序建工作簿；Summary 的统计格写公式。"""
    import xlsxwriter

    wb = xlsxwriter.Workbook(str(out), {"strings_to_formulas": False, "strings_to_urls": False})
    F = _formats(wb)

    ws = wb.add_worksheet("Summary")

    ws_raw = wb.add_worksheet("Raw Data")
    n_raw = _dump(ws_raw, raw, raw_cols, F)
    ws_raw.freeze_panes(1, 0)
    ws_raw.autofilter(0, 0, n_raw, len(raw_cols) - 1)
    for c, name in enumerate(raw_cols):
        ws_raw.set_column(c, c, 42 if name == "FO Process Detail"
                          else min(max(len(str(name)) + 4, 12), 30))

    ws_flt = wb.add_worksheet("ZTE")
    n_flt = _dump(ws_flt, flt, flt_cols, F)
    ws_flt.freeze_panes(1, 0)
    ws_flt.autofilter(0, 0, n_flt, len(flt_cols) - 1)
    for c, name in enumerate(flt_cols):
        ws_flt.set_column(c, c, 42 if name == "FO Process Detail"
                          else min(max(len(str(name)) + 4, 12), 30))

    l_sev = _col_letter(flt_cols.index("Ticket Severity"))
    l_mttr = _col_letter(flt_cols.index("MTTR (Hour)"))
    l_mon = _col_letter(flt_cols.index("Month"))
    rng = lambda L: f"'ZTE'!${L}$2:${L}${n_flt + 1}"

    for c, width in enumerate([12, 10, 10, 10, 3]):
        ws.set_column(c, c, width)
    ws.hide_gridlines(2)
    ws.merge_range("A1:D1", "TTs and MTTR (Hour)", F["title"])
    ws.set_row(0, 24)
    meta = [
        ("Source", src.name),
        ("Conditions", f"1) WO No. 非空   2) 告警发生→告警清除历时 < {MTTR_LIMIT_H:g} 小时   "
                       f"3) 告警月份 >= {MONTH_FROM}   4) Site Category 非空"),
        ("Tickets", f"原始 {len(df)} / 有 WO {len(raw)} / 过滤后 {len(flt)}"),
        ("Note", "N/A 块 = 源表未填 Ticket Severity 的工单，无 SLA 目标，只做统计不出图"),
        ("Generated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    ]
    for i, (k, v) in enumerate(meta, start=2):
        ws.write_string(i - 1, 0, k, F["meta_k"])
        ws.merge_range(i - 1, 1, i - 1, 9, v, F["meta_v"])

    row = 7  # 第一个块的标题行（1~5 行为元信息，6 行留空）
    blocks = {}
    for sev in BLOCKS:
        # COUNTIFS/AVERAGEIFS 用 "=" 匹配空单元格，对应源表未填 Ticket Severity 的工单
        crit = '"="' if sev == "N/A" else f'"{sev}"'
        ws.merge_range(row, 0, row, 3, sev, F["blk"])
        for c, head in enumerate(["MONTH", "TTs", "MTTR", "Target"]):
            ws.write_string(row + 1, c, head, F["head"])
        first = row + 2
        for i, m in enumerate(months):
            r = first + i
            ws.write_string(r, 0, m, F["cell"])
            cnt, avg = truth[(sev, m)]
            ws.write_formula(r, 1, f'=COUNTIFS({rng(l_sev)},{crit},{rng(l_mon)},$A{r + 1})',
                             F["cell"], cnt)
            ws.write_formula(
                r, 2,
                f'=IF($B{r + 1}=0,"",ROUND(AVERAGEIFS({rng(l_mttr)},{rng(l_sev)},{crit},'
                f'{rng(l_mon)},$A{r + 1}),2))',
                F["num2"], avg if avg is not None else "")
            if sev in TARGETS:
                ws.write_number(r, 3, TARGETS[sev], F["tgt"])
            else:
                ws.write_string(r, 3, "—", F["tgt"])
        last = first + len(months) - 1
        blocks[sev] = (first + 1, last + 1)  # Excel 1-based 的数据首末行
        row = last + 2

    for sev in SEVERITIES:
        a, b = blocks[sev]
        bar = wb.add_chart({"type": "column"})
        bar.add_series({
            "name": f"{sev} TTs",
            "categories": f"=Summary!$A${a}:$A${b}",
            "values": f"=Summary!$B${a}:$B${b}",
            "fill": {"color": BAR},
            "gap_width": 60,
            "data_labels": {"value": True, "font": {"size": 9, "color": "#404040"}},
        })
        bar.set_y_axis({"num_format": "#,##0", "major_gridlines": {"visible": False}})
        bar.set_x_axis({"num_font_size": 9})
        bar.set_size({"width": 580, "height": 320})

        line = wb.add_chart({"type": "line"})
        line.add_series({
            "name": f"{sev} MTTR",
            "categories": f"=Summary!$A${a}:$A${b}",
            "values": f"=Summary!$C${a}:$C${b}",
            "y2_axis": True,
            "line": {"color": LINE, "width": 2.25},
            "marker": {"type": "circle", "size": 6, "fill": {"color": LINE}, "border": {"color": LINE}},
            "data_labels": {"value": True, "font": {"size": 9, "color": "#404040"}, "position": "above"},
        })
        line.add_series({
            "name": f"{sev} Target",
            "categories": f"=Summary!$A${a}:$A${b}",
            "values": f"=Summary!$D${a}:$D${b}",
            "y2_axis": True,
            "line": {"color": TGT, "width": 2.75},
            "marker": {"type": "none"},
        })
        # 上限交给 Excel 自动缩放：MTTR 超标的月份（如 P1 2026-05 的 16.37h）不能被裁掉
        line.set_y2_axis({"num_format": "0.00", "min": 0})
        bar.combine(line)
        bar.set_title({"name": sev, "name_font": {"size": 13, "bold": True, "color": "#1F4E79"}})
        bar.set_legend({"position": "bottom", "font": {"size": 9}})
        bar.set_chartarea({"border": {"color": "#D9D9D9"}})

        col = 5 if SEVERITIES.index(sev) % 2 == 0 else 13
        r0 = 7 if SEVERITIES.index(sev) < 2 else 25
        ws.insert_chart(r0, col, bar)

    ws.activate()
    wb.close()


def run_tt_mttr_report() -> dict:
    """任务入口（零参）：生成 TTs and MTTR (Hour) 报表，返回结果摘要。"""
    t0 = time.time()
    src = _latest_source()
    logger.info("[TT_MTTR] 源文件 %s (%.1f MB)", src.name, src.stat().st_size / 1048576)

    df, raw, flt, raw_cols, flt_cols, dropped = _load_and_filter(src)
    months = sorted(m for m in flt["Month"].dropna().unique())
    if not months:
        raise ValueError(f"过滤后无数据（ZTE 0 行），源文件 {src.name}，剔除明细 {dropped}")
    truth = _monthly_stats(flt, months)

    out = _output_path(datetime.now())
    _write_workbook(out, src, df, raw, flt, raw_cols, flt_cols, months, truth)
    removed = _prune_old_outputs(keep=out)

    elapsed = round(time.time() - t0, 2)
    result = {
        "success": True,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_file": src.name,
        "output_file": out.name,
        "output_size_mb": round(out.stat().st_size / 1048576, 2),
        "tickets": {"total": int(len(df)), "with_wo": int(len(raw)), "in_report": int(len(flt))},
        "dropped": dropped,
        "months": [f"{m} 合计 {sum(truth[(s, m)][0] for s in BLOCKS)} 单" for m in months],
        "cleaned": removed,
        "elapsed_seconds": elapsed,
    }
    logger.info("[TT_MTTR] 已写出 %s (%.2f MB)，原始 %d / 有 WO %d / 入报告 %d，耗时 %.2f 秒",
                out.name, result["output_size_mb"], len(df), len(raw), len(flt), elapsed)
    return result


if __name__ == "__main__":
    import json
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run_tt_mttr_report(), ensure_ascii=False, indent=2))
