# -*- coding: utf-8 -*-
"""
ems_kpi_daily.py — 把"每日 counter 汇总"按 Query_Template.xml + samples 公式
计算成每个模板的 KPI, 输出 <模板名>.csv (天粒度, 格式与 GUI 导出一致)。

输入数据源抽象: daily_raw.json (由数据获取层产生, 如 EmsKpiDaily.java)
  {
    "window": {"start": "...", "end": "..."},
    "counters": {
        "<原始 counter 名>": {"2026-06-26": 123.0, "2026-06-27": 456.0, ...}
    }
  }

输出: csv_out/<模板名>.csv
  Index,Start Time,End Time,Query Granularity,<KPI 名>,...
"""

import csv
import datetime
import json
import os

import ems_kpi_templates as T

HERE = os.path.dirname(os.path.abspath(__file__))
DAILY_RAW = os.path.join(HERE, "daily_raw.json")
OUT_DIR = os.path.join(HERE, "csv_out")


def load_daily_raw(path=DAILY_RAW):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fmt_val(v):
    """格式化数值: 整数不带小数, 其余保留 4 位"""
    if v is None:
        return ""
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return "%.4f" % v
    return str(v)


def _is_gauge(desc):
    """判断 counter 是瞬时/均值型 (Number/Mean) 还是累计型 (Times/Duration)"""
    d = desc.lower()
    return ("number" in d or "mean" in d or "maximum" in d or "count" in d
            or "subscriber" in d or "license" in d)


def _day_val(entry, is_gauge):
    """从 {sum,max} 或纯数值条目取每日值"""
    if entry is None:
        return 0
    if isinstance(entry, dict):
        return entry.get("max", 0) if is_gauge else entry.get("sum", 0)
    return entry


def build_csvs(data, out_dir=OUT_DIR):
    """为每个模板生成 CSV。返回 [(模板名, csv路径, 行数, 备注)]"""
    os.makedirs(out_dir, exist_ok=True)
    templates = T.parse_query_templates()
    flat = data.get("counters", {})
    results = []
    for tpl in templates:
        name = tpl["name"]
        xp = os.path.join(T.SAMPLES_DIR, name + ".xlsx")
        if not os.path.exists(xp):
            results.append((name, None, 0, "缺 samples/%s.xlsx" % name))
            continue
        spec = T.parse_sample_formula(xp)

        # counter ref -> 可能的原始 counter 名列表
        ref_to_raws = {}
        for ref, desc in spec["counters"].items():
            ref_to_raws[ref] = T.resolve_raw_counter_names(ref, desc, tpl["poid"])

        # 本模板用到的原始 counter 名 (取第一个存在于数据中的候选)
        ref_to_raw = {}
        ref_is_gauge = {}
        for ref, desc in spec["counters"].items():
            for c in ref_to_raws[ref]:
                if c in flat:
                    ref_to_raw[ref] = c
                    ref_is_gauge[ref] = _is_gauge(desc)
                    break
        needed_raw = set(ref_to_raw.values())
        have_raw = {r for r in needed_raw if r in flat}
        if not have_raw:
            results.append((name, None, 0, "无计数器数据 (原始文件未包含或数据源未提供)"))
            continue

        # 日期并集
        all_days = set()
        for raw in have_raw:
            all_days.update(flat[raw].keys())
        all_days = sorted(all_days)

        # KPI 列
        kpi_name = spec["kpi_name"]
        kpi_cols = [kpi_name] if kpi_name else list(spec["counters"].keys())

        # 逐日计算
        daily_values = []
        for day in all_days:
            row_vals = []
            if spec["formula"]:
                refs = T.formula_refs(spec["formula"])
                cv = {}
                for ref in refs:
                    raw = ref_to_raw.get(ref)
                    cv[ref] = _day_val(flat.get(raw, {}).get(day), ref_is_gauge.get(ref, False))
                v = T.evaluate_formula(spec["formula"], cv)
                row_vals.append(v)
            else:
                for ref in kpi_cols:
                    raw = ref_to_raw.get(ref)
                    row_vals.append(_day_val(flat.get(raw, {}).get(day), ref_is_gauge.get(ref, False)))
            daily_values.append((day, row_vals))

        # 写 CSV (目标被占用时自动改用带时间戳的备用文件名)
        out_path = os.path.join(out_dir, name + ".csv")
        try:
            _write_csv(out_path, kpi_cols, daily_values)
            results.append((name, out_path, len(daily_values), "OK"))
        except PermissionError:
            alt = os.path.join(out_dir, "%s_%s.csv" % (
                name, datetime.datetime.now().strftime("%H%M%S")))
            _write_csv(alt, kpi_cols, daily_values)
            results.append((name, alt, len(daily_values),
                            "原文件被占用(可能被Excel打开), 已写到备用名"))
    return results


def _write_csv(out_path, kpi_cols, daily_values):
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Index", "Start Time", "End Time", "Query Granularity"] + kpi_cols)
        for i, (day, vals) in enumerate(daily_values, 1):
            dt = datetime.datetime.strptime(day, "%Y-%m-%d")
            start = dt.strftime("%Y-%m-%d %H:%M:%S")
            end = (dt + datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
            w.writerow([i, start, end, "1Day(s)"] + [fmt_val(v) for v in vals])


def main():
    data = load_daily_raw()
    for name, path, n, msg in build_csvs(data):
        print("  %-36s rows=%-4s %s" % (name, n, msg if path is None else path))


if __name__ == "__main__":
    main()
