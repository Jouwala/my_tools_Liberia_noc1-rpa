# -*- coding: utf-8 -*-
"""Meta 基准报告服务（ORANGE vs MTN 速率 PK + FDD 网络侧 KPI）。

口径全部来自 `bm_meta_caliber`（唯一真相源），本模块只负责拼查询与组装返回。

三个对外能力：

| 函数 | 作用 | 对应端点 |
| --- | --- | --- |
| `build_overview` | 汇总卡 + 逐日 PK 曲线 + 网络侧 KPI 序列 + 月度 + 胜负 + 评分 | `/api/bm-meta/overview` |
| `build_trend` | 指定指标的单指标趋势（含滚动均值） | `/api/bm-meta/trend` |
| `build_drilldown` | 某指标 / 某日 / 某胜者 的原始行明细 | `/api/bm-meta/drilldown` |

## 与 bm_speedtest_service 的关键差异

1. **没有品牌归一**：`speedtest_data` 用 `provider` 列 + LIKE 匹配才分出两家；
   本表**两家就是两个固定列**（`orange_liberia` / `mtn_liberia`），
   不存在匹配歧义，故 `_where()` 只过滤时间，不绑定任何 pattern。
2. **两组指标**：两家 PK（`BRAND_METRICS`）与网络侧 KPI（`NETWORK_METRICS`）
   分开处理，后者**不参与 PK、不打分** —— 原因见口径模块 docstring。
3. **比率列**：`bp` 与两个 PRB 利用率库里是小数比率，展示层 ×100 带 `%`，
   但**胜负与评分用原始比率**（同比放大不改变大小关系，但保持与库内一致）。

## 下钻一致性

概览与下钻共用同一份 `_where()`（同一时间列、同一左闭右开区间），
故「卡片上的 49 天」与「点开后 49 行」严格相等。
`/drilldown` 的 `winner` 过滤在**已算出胜者的基础上**再收窄，不另写一套比较逻辑。
"""
from __future__ import annotations

import logging
from typing import Any

from backend.database import get_raw_connection
from backend.services import bm_meta_caliber as cal

logger = logging.getLogger("bm_meta")


# ---------------- 内部工具 ----------------

def _fetch(conn, sql: str, params: tuple) -> list[dict]:
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _where(start: str, end: str) -> tuple[str, tuple]:
    """统一 WHERE 片段 + 其参数，**左闭右开** [start, end)。

    ⚠️ 没有前导 `WHERE` 关键字 —— 调用方一律写成 `... {where} AND ...`。
    过滤的是 `time::date`：本表 `time` 恒为 00:00:00（实测 612 行全部如此），
    但用 `::date` 而非直接比 `time`，是为了与下钻、与前端传来的 `day` 字符串
    在语义上完全对齐（都是"日"而不是"时刻"）。
    """
    return f"WHERE {cal.TIME_COL}::date >= ? AND {cal.TIME_COL}::date < ?", (start, end)


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


def _ratio(v, nd: int = 2) -> float | None:
    """小数比率 → 百分数（0.1956 → 19.56）。仅用于展示，不参与胜负。"""
    n = _num(v)
    return None if n is None else round(n * 100.0, nd)


def _percentile(sorted_vals: list[float], q: float) -> float | None:
    """线性插值分位数（与 numpy 默认一致），列表须已升序且非空。"""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 2)
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return round(sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac, 2)


def _display(metric: str, v: float | None) -> float | None:
    """按指标单位决定展示值：比率列 ×100，其余原值。"""
    if v is None:
        return None
    return _ratio(v) if cal.metric_meta(metric).get("unit") == "ratio" else _r(v)


# ---------------- 汇总与序列 ----------------

def _agg_sql() -> str:
    """两家 PK 的区间汇总（均值 / 极值 / 配对天数）。"""
    o, m = cal.BRAND_METRICS["speed"]["col"], cal.BRAND_METRICS["speed"]["mtn_col"]
    return f"""
        SELECT
            COUNT(*)                                        AS days,
            AVG({o})                                        AS o_avg,
            MIN({o})                                        AS o_min,
            MAX({o})                                        AS o_max,
            AVG({m})                                        AS m_avg,
            MIN({m})                                        AS m_min,
            MAX({m})                                        AS m_max
        FROM {cal.TABLE}
        {{where}}
    """


def _network_sql() -> str:
    """网络侧 KPI 的区间汇总（每列一组 avg/min/max，均不含 NULL）。"""
    parts = ["COUNT(*) AS days"]
    for k, meta in cal.NETWORK_METRICS.items():
        c = f'"{meta["col"]}"'
        parts.append(f"AVG({c}) AS {k}_avg")
        parts.append(f"MIN({c}) AS {k}_min")
        parts.append(f"MAX({c}) AS {k}_max")
    return f"SELECT {', '.join(parts)} FROM {cal.TABLE} {{where}}"


def _pair_daily_sql() -> str:
    """逐日两家里程碑值 + 网络侧 KPI（一行一天，供 PK 曲线与 KPI 曲线共用）。"""
    o, m = cal.BRAND_METRICS["speed"]["col"], cal.BRAND_METRICS["speed"]["mtn_col"]
    net = ", ".join(f'"{v["col"]}" AS {k}' for k, v in cal.NETWORK_METRICS.items())
    return f"""
        SELECT {cal.TIME_COL}::date AS day, {o} AS orange, {m} AS mtn, {net}
        FROM {cal.TABLE}
        {{where}}
        ORDER BY day
    """


def _month_sql() -> str:
    """按月两家里程碑值 + 网络侧 KPI 均值。"""
    o, m = cal.BRAND_METRICS["speed"]["col"], cal.BRAND_METRICS["speed"]["mtn_col"]
    net = ", ".join(f'AVG("{v["col"]}") AS {k}' for k, v in cal.NETWORK_METRICS.items())
    return f"""
        SELECT to_char({cal.TIME_COL}, 'YYYY-MM') AS ym,
               COUNT(*) AS days,
               AVG({o}) AS orange, AVG({m}) AS mtn,
               {net}
        FROM {cal.TABLE}
        {{where}}
        GROUP BY 1
        ORDER BY 1
    """


def _detail_sql() -> str:
    """下钻明细（网络侧 KPI 原样取，比率列由服务层换算展示）。"""
    net = ", ".join(f'"{v["col"]}" AS {k}' for k, v in cal.NETWORK_METRICS.items())
    o, m = cal.BRAND_METRICS["speed"]["col"], cal.BRAND_METRICS["speed"]["mtn_col"]
    return f"""
        SELECT {cal.TIME_COL}::date AS day, {o} AS orange, {m} AS mtn, {net},
               _source_file, _source_sheet, _import_time
        FROM {cal.TABLE}
        {{where}}
        ORDER BY day
        LIMIT ?
    """


def _summary(rows: list[dict], net_rows: list[dict]) -> dict[str, Any]:
    """两家汇总卡（均值/极值/P50/P90/配对天数）。"""
    a = rows[0] if rows else {}
    n = net_rows[0] if net_rows else {}
    days = int(a.get("days") or 0)
    out: dict[str, Any] = {}
    for b, key in (("ORANGE", "o"), ("MTN", "m")):
        out[b] = {
            "brand": b,
            "label": cal.BRAND_LABELS[b],
            "days": days,
            "speed": _r(a.get(f"{key}_avg")),
            "speed_min": _r(a.get(f"{key}_min")),
            "speed_max": _r(a.get(f"{key}_max")),
        }
    out["network"] = {"days": int(n.get("days") or 0)}
    for k in cal.NETWORK_METRICS:
        out["network"][k] = _display(k, n.get(f"{k}_avg"))
        out["network"][f"{k}_min"] = _display(k, n.get(f"{k}_min"))
        out["network"][f"{k}_max"] = _display(k, n.get(f"{k}_max"))
    return out


def _win_stats(daily: list[dict]) -> dict[str, Any]:
    """逐日胜负统计。相平的日期计入 `ties`，**不计入任何一方的胜场**。"""
    total = len(daily)
    o_wins = m_wins = ties = 0
    for d in daily:
        w = cal.winner_of(_num(d.get("orange")), _num(d.get("mtn")))
        if w == "ORANGE":
            o_wins += 1
        elif w == "MTN":
            m_wins += 1
        else:
            ties += 1
    paired = o_wins + m_wins
    return {
        "total_days": total,
        "paired_days": paired,
        "ties": ties,
        "orange_wins": o_wins,
        "mtn_wins": m_wins,
        "orange_win_rate": round(o_wins / paired * 100, 1) if paired else None,
        "mtn_win_rate": round(m_wins / paired * 100, 1) if paired else None,
        "orange_lead_days": o_wins,
        "mtn_lead_days": m_wins,
    }


def _monthly(daily: list[dict]) -> list[dict]:
    """按月聚合，**从已算好的逐日数据派生**（保证月度表与逐日表口径一致）。

    刻意不在 SQL 里另写一份 AVG：那样月度值会与逐日曲线的月度感觉对不上，
    且"某月胜场数"无法从 SQL 聚合里直接得到。
    """
    buckets: dict[str, list[dict]] = {}
    for d in daily:
        buckets.setdefault(str(d["day"])[:7], []).append(d)
    out = []
    for ym in sorted(buckets):
        rows = buckets[ym]
        o = [_num(r["orange"]) for r in rows if _num(r["orange"]) is not None]
        m = [_num(r["mtn"]) for r in rows if _num(r["mtn"]) is not None]
        w = _win_stats(rows)
        rec: dict[str, Any] = {
            "ym": ym,
            "days": len(rows),
            "orange_speed": round(sum(o) / len(o), 2) if o else None,
            "mtn_speed": round(sum(m) / len(m), 2) if m else None,
            "orange_wins": w["orange_wins"],
            "mtn_wins": w["mtn_wins"],
        }
        rec["winner"] = cal.winner_of(rec["orange_speed"], rec["mtn_speed"])
        for k in cal.NETWORK_METRICS:
            vals = [_num(r.get(k)) for r in rows if _num(r.get(k)) is not None]
            rec[k] = _display(k, sum(vals) / len(vals)) if vals else None
        out.append(rec)
    return out


# ---------------- 对外能力 ----------------

def build_overview(start: str, end: str) -> dict[str, Any]:
    """概览：汇总卡 + 逐日 PK + 网络侧 KPI 序列 + 月度 + 胜负 + 综合评分。"""
    with get_raw_connection() as conn:
        w, params = _where(start, end)
        agg = _fetch(conn, _agg_sql().format(where=w), params)
        net = _fetch(conn, _network_sql().format(where=w), params)
        daily = _fetch(conn, _pair_daily_sql().format(where=w), params)
        # 数据全量区间（不受 start/end 限制），用于界面提示"实际数据范围"
        cur = conn.cursor()
        cur.execute(f"SELECT MIN({cal.TIME_COL})::date, MAX({cal.TIME_COL})::date, COUNT(*) FROM {cal.TABLE}")
        dmin, dmax, total_rows = cur.fetchone()

    summary = _summary(agg, net)
    wins = _win_stats(daily)

    pairs = {"speed": {"ORANGE": summary["ORANGE"]["speed"], "MTN": summary["MTN"]["speed"]}}
    scores = cal.score_brands(pairs)

    # 逐日序列：展示层换算比率列（前端拿到即可直接用，不需要知道单位规则）
    daily_out = []
    for d in daily:
        o, m = _num(d.get("orange")), _num(d.get("mtn"))
        rec: dict[str, Any] = {
            "day": str(d["day"]),
            "orange_speed": _r(o),
            "mtn_speed": _r(m),
            "winner": cal.winner_of(o, m),
        }
        for k in cal.NETWORK_METRICS:
            rec[k] = _display(k, _num(d.get(k)))
        daily_out.append(rec)

    warnings = []
    if wins["ties"]:
        warnings.append(f"{wins['ties']} 天两家速率相同，未计入任何一方胜场。")

    return {
        "meta": {
            "start": start,
            "end": end,
            "brands": list(cal.BRANDS),
            "row_count": total_rows,
            "data_min_date": str(dmin) if dmin else None,
            "data_max_date": str(dmax) if dmax else None,
            "daily_total": len(daily_out),
            "daily_returned": len(daily_out),
            "daily_truncated": False,
            "warnings": warnings,
        },
        "filters": {
            "min_date": str(dmin) if dmin else None,
            "max_date": str(dmax) if dmax else None,
            "row_count": total_rows,
            "brands": [{"key": b, "label": cal.BRAND_LABELS[b]} for b in cal.BRANDS],
            "metrics": [
                {"key": k, "kind": v["kind"], "unit": v["unit"], "group": "brand"}
                for k, v in cal.BRAND_METRICS.items()
            ] + [
                {"key": k, "kind": v["kind"], "unit": v["unit"], "group": "network"}
                for k, v in cal.NETWORK_METRICS.items()
            ],
        },
        "summary": summary,
        "scores": scores,
        "score_weights": cal.SCORE_WEIGHTS,
        "daily": daily_out,
        "monthly": _monthly(daily),
        "wins": wins,
    }


def build_trend(start: str, end: str, metric: str = "speed", window: int = 7) -> dict[str, Any]:
    """单指标趋势。

    两家 PK 指标（`speed`）返回双线 + 各自滚动均值 + 逐日胜者；
    网络侧 KPI 返回单线 + 滚动均值（**没有胜者概念**）。
    """
    meta = cal.metric_meta(metric)
    with get_raw_connection() as conn:
        w, params = _where(start, end)
        rows = _fetch(conn, _pair_daily_sql().format(where=w), params)

    win = max(1, int(window))
    is_brand = meta["group"] == "brand"
    points: list[dict] = []
    buf_o: list[float] = []
    buf_m: list[float] = []
    buf_n: list[float] = []

    for r in rows:
        o = _num(r.get("orange")) if is_brand else None
        m = _num(r.get("mtn")) if is_brand else None
        nv = _num(r.get(metric)) if not is_brand else None

        if is_brand:
            if o is not None:
                buf_o.append(o)
            if m is not None:
                buf_m.append(m)
            buf_o[:] = buf_o[-win:]
            buf_m[:] = buf_m[-win:]
            points.append({
                "day": str(r["day"]),
                "orange": _display(metric, o),
                "mtn": _display(metric, m),
                "orange_ma": round(sum(buf_o) / len(buf_o), 2) if buf_o else None,
                "mtn_ma": round(sum(buf_m) / len(buf_m), 2) if buf_m else None,
                "value": None, "value_ma": None,
                "winner": cal.winner_of(o, m),
            })
        else:
            if nv is not None:
                buf_n.append(nv)
            buf_n[:] = buf_n[-win:]
            points.append({
                "day": str(r["day"]),
                "orange": None, "mtn": None,
                "orange_ma": None, "mtn_ma": None,
                "value": _display(metric, nv),
                "value_ma": _display(metric, sum(buf_n) / len(buf_n)) if buf_n else None,
                "winner": None,
            })

    return {
        "meta": {
            "start": start, "end": end, "metric": metric,
            "kind": meta["kind"], "unit": meta["unit"], "group": meta["group"],
            "window": win, "points": len(points),
        },
        "points": points,
    }


def build_drilldown(start: str, end: str, metric: str = "", day: str = "",
                    winner: str = "", limit: int = 500) -> dict[str, Any]:
    """明细下钻：按 日期 / 胜者 过滤。

    `winner` 过滤（`winner=ORANGE` / `winner=MTN`）只对两家 PK 指标有意义：
    它复用 `cal.winner_of`，与 `/overview` 的胜负统计**同一套判定**，
    因此"卡片上的 49 天"与"点开后的 49 行"严格相等。

    ⚠️ `day` 过滤**必须走 `cal.TIME_COL` 原列**，不能写成 `AND day = ?`：
    `day` 只是 SELECT 列表里的别名，在 WHERE 阶段尚不存在，实测报
    `字段 "day" 不存在`。参数顺序 = WHERE 的 (start, end) 在前、日过滤在后，
    最后才是 LIMIT —— 占位符顺序必须与 SQL 文本一致。
    """
    if metric:
        cal.metric_meta(metric)  # 校验 key，未知指标直接抛错而不是静默返回空列
    lim = max(1, min(int(limit), cal.MAX_DETAIL_ROWS))

    where_sql, params = _where(start, end)
    params = list(params)
    if day:
        where_sql += f" AND {cal.TIME_COL}::date = ?"
        params.append(day)

    sql = _detail_sql().format(where=where_sql)
    # 多取一行做截断探针（见 AGENTS.md：不能凭 len(rows) >= limit 判断）
    params.append(lim + 1)
    with get_raw_connection() as conn:
        rows = _fetch(conn, sql, tuple(params))

    out = []
    for r in rows[:lim]:
        o, m = _num(r.get("orange")), _num(r.get("mtn"))
        w = cal.winner_of(o, m)
        if winner and w != winner:
            continue
        rec: dict[str, Any] = {
            "day": str(r["day"]),
            "orange_speed": _r(o),
            "mtn_speed": _r(m),
            "winner": w,
            "winner_label": cal.BRAND_LABELS.get(w) if w else None,
            "gap": round(o - m, 2) if (o is not None and m is not None) else None,
            "source_file": r.get("_source_file"),
            "source_sheet": r.get("_source_sheet"),
            "import_time": r.get("_import_time"),
        }
        for k in cal.NETWORK_METRICS:
            rec[k] = _display(k, _num(r.get(k)))
        out.append(rec)

    truncated = len(rows) > lim
    return {
        "rows": out,
        "meta": {
            "metric": metric, "day": day, "winner": winner,
            "limit": lim, "returned": len(out), "truncated": truncated,
            "start": start, "end": end,
        },
    }
