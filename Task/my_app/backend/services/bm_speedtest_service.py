# -*- coding: utf-8 -*-
"""Speedtest 竞对分析服务（ORANGE vs MTN）。

口径全部来自 `bm_speedtest_caliber`（唯一真相源），本模块只负责拼查询与组装返回。

三个对外能力：

| 函数 | 作用 | 对应端点 |
| --- | --- | --- |
| `build_overview` | 汇总卡 + 逐日对比曲线 + 月度对比 + 胜负统计 + 综合评分 | `/api/bm-speedtest/overview` |
| `build_trend` | 指定指标的单指标趋势（含滚动均值） | `/api/bm-speedtest/trend` |
| `build_drilldown` | 某指标 / 某日 / 某品牌的原始行明细 | `/api/bm-speedtest/drilldown` |

## 下钻一致性

三者共用 `cal.base_sql()` 与同一份 `_where()`：
概览里任何一个数字，点开后下钻行数必须与它严格一致。
`/drilldown` 额外支持 `metric` 上的「谁更强」过滤（`winner=ORANGE` 等），
该过滤在**配对后的逐日数据**上做，与胜负统计同一份 CTE，不另写一套比较逻辑。
"""
from __future__ import annotations

import logging
from typing import Any

from backend.database import get_raw_connection
from backend.services import bm_speedtest_caliber as cal

logger = logging.getLogger("bm_speedtest")


# ---------------- 内部工具 ----------------

def _fetch(conn, sql: str, params: tuple) -> list[dict]:
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _where(start: str, end: str) -> tuple[str, tuple]:
    """统一 WHERE 片段 + 其参数（品牌 pattern 在前，区间在后，顺序不可换）。

    ⚠️ 两条硬约束，改这里前务必看懂：

    1. **没有前导 `WHERE` 关键字** —— 调用方一律写成 `... {where} AND ...`。
    2. **过滤的是 `day` 而不是 `aggregate_date`** —— `cal.base_sql()` 已经把
       `aggregate_date::date` 投影成 `day`，外层子查询里根本不存在
       `aggregate_date` 这一列。早先版本写 `aggregate_date` 实测报
       `字段 "aggregate_date" 不存在`。左闭右开（`>= start AND < end`）的口径
       在 `base_sql` 内外完全一致，故概览与下钻的日期范围严格相同。
    """
    sql = "WHERE day >= ? AND day < ?"
    return sql, (*cal.brand_patterns(), start, end)


def _num(v) -> float | None:
    """DB 数值 → float；None 保持 None（前端渲染 —，不显示成 0）。"""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _r(v, nd: int = 2) -> float | None:
    n = _num(v)
    return None if n is None else round(n, nd)


def _brand_params(start: str, end: str) -> tuple:
    return (*cal.brand_patterns(), start, end)


# ---------------- 汇总 ----------------

_AGG_SQL = """
SELECT brand,
       COUNT(*)                          AS days,
       AVG(dl)  AS download,  AVG(ul)  AS upload,
       AVG(lat) AS latency,   AVG(jit) AS jitter,
       MIN(dl)  AS download_min, MAX(dl) AS download_max,
       MIN(ul)  AS upload_min,   MAX(ul) AS upload_max,
       MIN(lat) AS latency_min,  MAX(lat) AS latency_max,
       MIN(jit) AS jitter_min,   MAX(jit) AS jitter_max,
       SUM(tests)   AS tests,
       SUM(samples) AS samples,
       SUM(devices) AS devices,
       AVG(tests)   AS tests_per_day,
       MIN(day) AS first_day, MAX(day) AS last_day
FROM ({base}) t
{where} AND brand IN ('ORANGE', 'MTN')
GROUP BY brand
"""

# 四个分位数子查询共用同一份 base + where（下钻一致性），
# 每个子查询各自绑定一份完整参数，顺序必须是 base 的 pattern 在前、区间在后。
_PCT_SQL = """
SELECT brand, metric, p50, p90 FROM (
  SELECT 'download' AS metric, brand,
         PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY dl)  AS p50,
         PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY dl)  AS p90
  FROM ({base}) t {where} AND brand IN ('ORANGE','MTN') GROUP BY brand
  UNION ALL
  SELECT 'upload', brand,
         PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ul),
         PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY ul)
  FROM ({base}) t {where} AND brand IN ('ORANGE','MTN') GROUP BY brand
  UNION ALL
  SELECT 'latency', brand,
         PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY lat),
         PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY lat)
  FROM ({base}) t {where} AND brand IN ('ORANGE','MTN') GROUP BY brand
  UNION ALL
  SELECT 'jitter', brand,
         PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY jit),
         PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY jit)
  FROM ({base}) t {where} AND brand IN ('ORANGE','MTN') GROUP BY brand
) p
"""


def _summary(conn, start: str, end: str) -> dict[str, Any]:
    """两家在窗口内的指标汇总 + 分位数。"""
    where, params = _where(start, end)
    rows = _fetch(conn, _AGG_SQL.format(base=cal.base_sql(), where=where), params)
    # _PCT_SQL 含 4 个并列子查询，每个各需一份完整参数（同一份 where 重复 4 次）
    pcts = _fetch(conn, _PCT_SQL.format(base=cal.base_sql(), where=where), params * 4)

    pct_map: dict[str, dict] = {}
    for r in pcts:
        b = r["brand"]
        pct_map.setdefault(b, {})[r["metric"]] = {"p50": _r(r["p50"]), "p90": _r(r["p90"])}

    out: dict[str, Any] = {}
    for r in rows:
        b = r["brand"]
        out[b] = {
            "brand": b,
            "label": cal.BRAND_LABELS.get(b, b),
            "days": r["days"],
            "download": _r(r["download"]),
            "upload": _r(r["upload"]),
            "latency": _r(r["latency"], 1),
            "jitter": _r(r["jitter"]),
            "download_min": _r(r["download_min"]), "download_max": _r(r["download_max"]),
            "upload_min": _r(r["upload_min"]), "upload_max": _r(r["upload_max"]),
            "latency_min": _r(r["latency_min"], 1), "latency_max": _r(r["latency_max"], 1),
            "jitter_min": _r(r["jitter_min"]), "jitter_max": _r(r["jitter_max"]),
            "tests": int(r["tests"] or 0),
            "samples": int(r["samples"] or 0),
            "devices": int(r["devices"] or 0),
            "tests_per_day": _r(r["tests_per_day"], 1),
            "first_day": str(r["first_day"]) if r["first_day"] else None,
            "last_day": str(r["last_day"]) if r["last_day"] else None,
            "pcts": pct_map.get(b, {}),
        }
    # 缺数据的一方补空壳，保证前端两列恒定存在
    for b in cal.BRANDS:
        out.setdefault(b, {"brand": b, "label": cal.BRAND_LABELS[b], "days": 0,
                           "download": None, "upload": None, "latency": None, "jitter": None,
                           "tests": 0, "samples": 0, "devices": 0, "tests_per_day": None,
                           "first_day": None, "last_day": None, "pcts": {}})
    return out


_PAIR_DAILY_SQL = """
SELECT
    MIN(day) AS day,
    MAX(CASE WHEN brand='ORANGE' THEN dl  END) AS o_download,
    MAX(CASE WHEN brand='MTN'    THEN dl  END) AS m_download,
    MAX(CASE WHEN brand='ORANGE' THEN ul  END) AS o_upload,
    MAX(CASE WHEN brand='MTN'    THEN ul  END) AS m_upload,
    MAX(CASE WHEN brand='ORANGE' THEN lat END) AS o_latency,
    MAX(CASE WHEN brand='MTN'    THEN lat END) AS m_latency,
    MAX(CASE WHEN brand='ORANGE' THEN jit END) AS o_jitter,
    MAX(CASE WHEN brand='MTN'    THEN jit END) AS m_jitter,
    SUM(CASE WHEN brand='ORANGE' THEN tests END) AS o_tests,
    SUM(CASE WHEN brand='MTN'    THEN tests END) AS m_tests
FROM ({base}) t
{where} AND brand IN ('ORANGE','MTN')
GROUP BY day
ORDER BY day
"""


def _daily(conn, start: str, end: str) -> list[dict]:
    """逐日两品牌并排（同一天最多一家一行，实测无重复，MAX 只是防御）。

    返回结构刻意扁平（`orange_download` / `mtn_download` 并列），
    前端画双折线与渲染表格都不用再转换。
    """
    where, params = _where(start, end)
    rows = _fetch(conn, _PAIR_DAILY_SQL.format(base=cal.base_sql(), where=where), params)
    out = []
    for r in rows:
        item: dict[str, Any] = {"day": str(r["day"])}
        for metric in cal.METRICS:
            key = {"download": "download", "upload": "upload",
                   "latency": "latency", "jitter": "jitter"}[metric]
            o = _r(r[f"o_{key}"], 1 if metric == "latency" else 2)
            m = _r(r[f"m_{key}"], 1 if metric == "latency" else 2)
            item[f"orange_{metric}"] = o
            item[f"mtn_{metric}"] = m
            item[f"winner_{metric}"] = cal.winner_of(o, m, cal.METRICS[metric]["kind"])
        item["orange_tests"] = int(r["o_tests"] or 0)
        item["mtn_tests"] = int(r["m_tests"] or 0)
        out.append(item)
    return out


def _win_stats(daily: list[dict]) -> dict[str, Any]:
    """基于 `_daily` 的配对结果算胜负：**只统计两家都有数据的日子**。

    单边缺数据的日子计入 `unpaired_days` 并单独暴露 ——
    「那天 MTN 没测」不等于「那天 MTN 输了」。
    """
    out: dict[str, Any] = {"total_days": len(daily), "unpaired_days": 0, "metrics": {}}
    for metric in cal.METRICS:
        o_key, m_key = f"orange_{metric}", f"mtn_{metric}"
        w_key = f"winner_{metric}"
        paired = [d for d in daily if d[o_key] is not None and d[m_key] is not None]
        o = sum(1 for d in paired if d[w_key] == "ORANGE")
        m = sum(1 for d in paired if d[w_key] == "MTN")
        tie = len(paired) - o - m
        out["metrics"][metric] = {
            "paired_days": len(paired),
            "orange_wins": o,
            "mtn_wins": m,
            "ties": tie,
            "orange_win_rate": round(o / len(paired) * 100, 1) if paired else None,
            "mtn_win_rate": round(m / len(paired) * 100, 1) if paired else None,
        }
    unpaired = sum(1 for d in daily
                   if d["orange_download"] is None or d["mtn_download"] is None)
    out["unpaired_days"] = unpaired
    out["paired_days"] = len(daily) - unpaired
    return out


_MONTH_SQL = """
SELECT TO_CHAR(day, 'YYYY-MM') AS ym,
       MAX(CASE WHEN brand='ORANGE' THEN dl  END) AS o_download,
       MAX(CASE WHEN brand='MTN'    THEN dl  END) AS m_download,
       MAX(CASE WHEN brand='ORANGE' THEN ul  END) AS o_upload,
       MAX(CASE WHEN brand='MTN'    THEN ul  END) AS m_upload,
       MAX(CASE WHEN brand='ORANGE' THEN lat END) AS o_latency,
       MAX(CASE WHEN brand='MTN'    THEN lat END) AS m_latency,
       MAX(CASE WHEN brand='ORANGE' THEN jit END) AS o_jitter,
       MAX(CASE WHEN brand='MTN'    THEN jit END) AS m_jitter,
       SUM(CASE WHEN brand='ORANGE' THEN tests END) AS o_tests,
       SUM(CASE WHEN brand='MTN'    THEN tests END) AS m_tests,
       COUNT(DISTINCT CASE WHEN brand='ORANGE' THEN day END) AS o_days,
       COUNT(DISTINCT CASE WHEN brand='MTN'    THEN day END) AS m_days
FROM ({base}) t
{where} AND brand IN ('ORANGE','MTN')
GROUP BY TO_CHAR(day, 'YYYY-MM')
ORDER BY ym
"""


def _monthly(conn, start: str, end: str) -> list[dict]:
    """按月聚合：**月度均值要用「日均值的均值」**，故用 AVG 而非对原始行 AVG。

    这里 SQL 用 MAX(CASE...) 取到的是「该品牌该月逐日均值」的中间层 ——
    因为 `base` 的一行就是一天，外层再 AVG 才是「日均值的月均值」。
    写成 AVG 的话与逐日曲线对不上，用户会当成 bug。
    """
    where, params = _where(start, end)
    # 先用逐日配对（与 _daily 同一份逻辑），再按月求均值
    daily = _daily(conn, start, end)
    acc: dict[str, dict] = {}
    for d in daily:
        ym = d["day"][:7]
        slot = acc.setdefault(ym, {"ym": ym, "days": 0, "orange": {}, "mtn": {}})
        slot["days"] += 1
        for b, prefix in (("orange", "orange"), ("mtn", "mtn")):
            for metric in cal.METRICS:
                v = d.get(f"{prefix}_{metric}")
                if v is None:
                    continue
                slot[b].setdefault(metric, []).append(v)
            t = d.get(f"{prefix}_tests")
            if t:
                slot[b].setdefault("tests", []).append(t)

    out = []
    for ym in sorted(acc):
        slot = acc[ym]
        item: dict[str, Any] = {"ym": ym, "days": slot["days"]}
        for b in ("orange", "mtn"):
            for metric in cal.METRICS:
                vals = slot[b].get(metric) or []
                nd = 1 if metric == "latency" else 2
                item[f"{b}_{metric}"] = round(sum(vals) / len(vals), nd) if vals else None
            ts = slot[b].get("tests") or []
            item[f"{b}_tests"] = int(sum(ts)) if ts else 0
        for metric in cal.METRICS:
            item[f"winner_{metric}"] = cal.winner_of(
                item[f"orange_{metric}"], item[f"mtn_{metric}"], cal.METRICS[metric]["kind"])
        out.append(item)
    return out


def _filters(conn) -> dict[str, Any]:
    """返回页面可用的筛选范围（实际只有时间维度，见 caliber 模块说明）。"""
    sql = f"""SELECT MIN(aggregate_date::date) AS d0, MAX(aggregate_date::date) AS d1,
                     COUNT(*) AS n, COUNT(DISTINCT provider) AS p
              FROM {cal.TABLE}"""
    cur = conn.cursor()
    cur.execute(sql)
    row = cur.fetchone()
    return {
        "min_date": str(row[0]) if row and row[0] else None,
        "max_date": str(row[1]) if row and row[1] else None,
        "row_count": int(row[2] or 0) if row else 0,
        "brands": [{"key": b, "label": cal.BRAND_LABELS[b]} for b in cal.BRANDS],
        "metrics": [{"key": m, "kind": cal.METRICS[m]["kind"], "unit": cal.METRICS[m]["unit"]}
                    for m in cal.METRICS],
    }


def build_overview(start: str, end: str) -> dict[str, Any]:
    """页面主接口：汇总卡 + 逐日曲线 + 月度 + 胜负 + 评分。"""
    conn = get_raw_connection()
    try:
        summary = _summary(conn, start, end)
        daily = _daily(conn, start, end)
        monthly = _monthly(conn, start, end)
        wins = _win_stats(daily)
        scores = cal.score_brands(summary)
        filters = _filters(conn)
    finally:
        conn.close()

    # 逐日曲线可能几千点，概览里只回最近 400 天，全量走 /trend（并显式告知截断）
    trend_rows = daily[-400:] if len(daily) > 400 else daily
    return {
        "meta": {
            "start": start, "end": end,
            "brands": list(cal.BRANDS),
            "row_count": filters["row_count"],
            "data_min_date": filters["min_date"],
            "data_max_date": filters["max_date"],
            "daily_total": len(daily),
            "daily_returned": len(trend_rows),
            "daily_truncated": len(daily) > len(trend_rows),
            "warnings": [],
        },
        "filters": filters,
        "summary": {b: summary[b] for b in cal.BRANDS},
        "scores": scores,
        "score_weights": cal.SCORE_WEIGHTS,
        "daily": trend_rows,
        "monthly": monthly,
        "wins": wins,
    }


_TREND_SQL = """
SELECT day,
       MAX(CASE WHEN brand='ORANGE' THEN {col} END) AS o,
       MAX(CASE WHEN brand='MTN'    THEN {col} END) AS m
FROM ({base}) t
{where} AND brand IN ('ORANGE','MTN')
GROUP BY day ORDER BY day
"""


def build_trend(start: str, end: str, metric: str, window: int = 7) -> dict[str, Any]:
    """单指标趋势 + 滚动均值（窗口默认 7 天，NULL 不参与均值，PG 原生支持）。"""
    metric = metric if metric in cal.METRICS else "download"
    col = cal.metric_col(metric)
    kind = cal.METRICS[metric]["kind"]
    nd = 1 if metric == "latency" else 2

    where, params = _where(start, end)
    conn = get_raw_connection()
    try:
        rows = _fetch(conn, _TREND_SQL.format(base=cal.base_sql(), where=where, col=col), params)
    finally:
        conn.close()

    series = []
    o_hist: list[float] = []
    m_hist: list[float] = []
    for r in rows:
        o, m = _r(r["o"], nd), _r(r["m"], nd)
        if o is not None:
            o_hist.append(o)
        if m is not None:
            m_hist.append(m)
        series.append({
            "day": str(r["day"]),
            "orange": o, "mtn": m,
            "orange_ma": round(sum(o_hist[-window:]) / len(o_hist[-window:]), nd) if o_hist else None,
            "mtn_ma": round(sum(m_hist[-window:]) / len(m_hist[-window:]), nd) if m_hist else None,
            "winner": cal.winner_of(o, m, kind),
        })
    return {
        "meta": {"start": start, "end": end, "metric": metric, "kind": kind,
                 "unit": cal.METRICS[metric]["unit"], "window": window,
                 "points": len(series)},
        "series": series,
    }


_DETAIL_SQL = """
SELECT brand, day, provider, location, device, technology_type, metric_type,
       dl, ul, lat, jit, tests, samples, devices, _source_file, _import_time
FROM ({base}) t
{where} AND brand IN ('ORANGE','MTN')
{extra}
ORDER BY day DESC, brand
LIMIT {limit}
"""


def build_drilldown(start: str, end: str, metric: str = "", day: str = "",
                    brand: str = "", winner: str = "", limit: int = 500) -> dict[str, Any]:
    """明细下钻：支持按 指标×日期×品牌 过滤，或「某指标下谁更强」过滤。

    ## `winner` 过滤为什么必须额外收窄品牌（AGENTS.md 第三节 1b 的一致性铁律）

    `winner` 的语义是「**某个品牌赢的那些天**」，所以它同时隐含两个条件：
    ① 日期属于该品牌的胜日集合；② 行本身属于该品牌。
    只做 ① 会把赢家的行和输家的行一起返回（实测每天 2 行 → 49 个胜日返回 98 行），
    用户看到的下钻行数与「ORANGE 赢 49 天」这个数字对不上，会直接当成 bug。
    故此处**追加 `brand = winner`**，使「下钻行数 == 胜负统计里的胜场天数」严格成立。
    """
    limit = max(1, min(int(limit or 500), cal.MAX_DETAIL_ROWS))
    where, params = _where(start, end)
    extra_sql = ""
    extra_params: list = []

    if brand in cal.BRANDS:
        extra_sql += " AND brand = ?"
        extra_params.append(brand)
    if day:
        extra_sql += " AND day = ?"
        extra_params.append(day)

    if winner in cal.BRANDS and metric in cal.METRICS:
        conn = get_raw_connection()
        try:
            daily = _daily(conn, start, end)
        finally:
            conn.close()
        days = [d["day"] for d in daily if d.get(f"winner_{metric}") == winner]
        if not days:
            return {"meta": {"start": start, "end": end, "metric": metric, "winner": winner,
                             "total": 0, "returned": 0, "truncated": False}, "rows": []}
        marks = ",".join(["?"] * len(days))
        extra_sql += f" AND day IN ({marks})"
        extra_params.extend(days)
        # 只返回胜者自己的行，使行数 == 胜场天数（见 docstring）
        extra_sql += " AND brand = ?"
        extra_params.append(winner)

    # 多取一行用于判断是否真的被截断：仅当"取满 limit 且还有更多"才算截断。
    # 只按 len(out) >= limit 判断会把「正好等于 limit」误报为截断。
    probe_limit = limit + 1
    sql = _DETAIL_SQL.format(base=cal.base_sql(), where=where, extra=extra_sql, limit=probe_limit)
    all_params = (*params, *extra_params)

    conn = get_raw_connection()
    try:
        rows = _fetch(conn, sql, all_params)
    finally:
        conn.close()

    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    out = []
    for r in rows:
        out.append({
            "brand": r["brand"],
            "brand_label": cal.BRAND_LABELS.get(r["brand"], r["brand"]),
            "day": str(r["day"]),
            "provider": r["provider"],
            "location": r["location"],
            "device": r["device"] or "all",
            "technology_type": r["technology_type"],
            "metric_type": r["metric_type"],
            "download": _r(r["dl"]),
            "upload": _r(r["ul"]),
            "latency": _r(r["lat"], 1),
            "jitter": _r(r["jit"]),
            "tests": int(r["tests"] or 0),
            "samples": int(r["samples"] or 0),
            "devices": int(r["devices"] or 0),
            "source_file": r["_source_file"],
            "import_time": r["_import_time"],
        })
    return {
        "meta": {"start": start, "end": end, "metric": metric or None,
                 "day": day or None, "brand": brand or None, "winner": winner or None,
                 "total": len(out), "returned": len(out),
                 "truncated": truncated, "limit": limit},
        "rows": out,
    }
