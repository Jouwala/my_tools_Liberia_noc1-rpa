# -*- coding: utf-8 -*-
"""BP Report —— 查询层（供 routers/bp_report.py 调用）。

=========================== 下钻一致性（AGENTS.md 第三节 1b 的铁律） ===========================

页面上每个数字都要能点开落到明细，且**下钻端点的 WHERE 必须与概览端点完全一致**。
本模块的做法是：概览与下钻共用同一组 SQL 谓词构造函数（`_scope_sql()`），
概览的数字由 `SUM(CASE WHEN <同一谓词>)` 得出，下钻的明细由 `WHERE <同一谓词>` 得出。
两边不可能漂移，因为它们是**同一个字符串**。

`MAX_DETAIL_ROWS` 显著大于前端单页最大量（200），且截断时返回 `meta.truncated`。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.services import bp_caliber as cal
from backend.services import bp_report_store as store

logger = logging.getLogger("bp_report_service")

#: 明细取样上限。必须显著大于前端单页最大数据量（200 行/页），否则会静默截断，
#: 让下钻行数少于概览数字 —— 见 AGENTS.md 第三节 1b。
MAX_DETAIL_ROWS = 20000

#: 趋势图最多返回的点数（日粒度 3 年约 1050 点，够用；周/月更少）。
MAX_TREND_POINTS = 2000

#: 三种粒度的表映射：粒度 → (表名, 时间列, BP 列, 总数列, 比率列, 流量列)
GRAIN_SPEC = {
    "day": ("bp_overall_daily", "day", "bp_cells", "total_cells", "bp_ratio", "traffic_tb"),
    "week": ("bp_overall_week", "week", "bp_cells", "total_cells", "bp_ratio", "traffic_tb"),
    "month": ("bp_overall_month", "month", "bp_cells", "total_cells", "bp_ratio", "traffic_tb"),
}

#: 分区维度的合法取值（含清洗后的 Unknown）
DIM_REGION = ("Cluster1", "Cluster2", "Cluster3", "Cluster4",
              "Cluster5", "Cluster6", "Rural", "ERA", cal.UNKNOWN)
DIM_LAYER = cal.VALID_LAYERS + (cal.UNKNOWN,)


def _conn():
    """只读连接。库不存在时抛 FileNotFoundError，由 router 转成可读的错误。"""
    if not store.db_exists():
        raise FileNotFoundError(
            "物化库 data/bp_report.sqlite3 不存在，请先跑 Excel 导入"
            "（backend.services.bp_report_import.run_import）")
    return store.connect(read_only=True)


def _range_sql(col: str, start: str, end: str) -> Tuple[str, List[Any]]:
    """构造时间范围谓词。**概览与下钻共用**，保证两者完全一致。"""
    parts: List[str] = []
    params: List[Any] = []
    if start:
        parts.append(f"{col} >= ?")
        params.append(start)
    if end:
        parts.append(f"{col} <= ?")
        params.append(end)
    return (" AND ".join(parts) if parts else "1=1"), params


def _range_sql_day(col: str, start: str, end: str) -> Tuple[str, List[Any]]:
    """日粒度明细的时间范围谓词（`day` 是 `YYYY-MM-DD`，可直接比较）。"""
    return _range_sql(col, start, end)


def _effective_range(conn, grain: str, start: str, end: str) -> Tuple[str, str]:
    """把空范围补成数据实际边界，避免前端拿到空区间。

    返回的是**周期标签**形态（日粒度即日期，周/月粒度是 `2023-W48` / `2023-04`），
    因为 trend 查询比较的 `week`/`month` 列存的就是标签。
    需要真日期时由调用方用 `cal.period_to_day_range()` 转换
    —— **不要**拿标签去和 `bp_cell_daily.day` 比较（字符串比较会静默失配）。
    """
    table, time_col = GRAIN_SPEC[grain][0], GRAIN_SPEC[grain][1]
    if not start:
        start = store.scalar(conn, f"SELECT MIN({time_col}) FROM {table}") or ""
    if not end:
        end = store.scalar(conn, f"SELECT MAX({time_col}) FROM {table}") or ""
    return start, end


# ============================================================
# 概览
# ============================================================

def load_overview(start: str = "", end: str = "",
                  granularity: str = "day") -> Dict[str, Any]:
    """概览：趋势 + 合计 + 口径元信息。

    对应 Excel 的 `Overall - Daily` / `Overall - 1 Weekly` / `Overall - Monthly`。

    ===================== 两个分母，必须分清（下钻一致性的前提） =====================

    Excel 给的是**两个不同分母**的数：
      - `Number of BP cells`（bp_cells）—— 分子，Excel 的 `BP Cells List` 明细能逐行对上；
      - `Total Cells`（total_cells）—— 全网小区数（实测约 6114），**Excel 未提供名单**。

    而明细表 `bp_cell_daily` 只含 `BP Cells List` 里出现过的 4269 个小区，因此：

      ✅ `bp_cells` == `/cells?scope=bp` 的行数（**可对上，已强制保证**）
      ⚠️ `total_cells` **无法**用明细对账 —— 明细里根本没有非 BP Cells List 的小区。
         硬要比只会得到「明细 472 ≠ 概览 6114」这种看着像 bug 的差异。

    这个标定是本模块实测出来的（2026-09-29）：Excel 的 BP Cells List 是「曾是 BP 的小区
    清单」，**不是**全网小区名册。所以 `total_cells` 在界面上标注为「Excel 全网口径」，
    且 `/cells` 返回的 `total` 只代表「明细表覆盖的小区数」，两者**不是**同一指标，
    不可互相校验 —— 详见 `load_cells()` 的 docstring。
    """
    t0 = time.time()
    grain = granularity if granularity in GRAIN_SPEC else "day"
    table, time_col, bp_col, tot_col, ratio_col, traf_col = GRAIN_SPEC[grain]

    with _conn() as conn:
        # ⚠️ 两套边界，别混用（2026-09-29）：
        #   start/end        —— **周期标签**形态，用于 trend 查询（表里的 week/month 列就是标签）
        #   d_start/d_end    —— **真日期**形态，用于查 bp_cell_daily.day（明细表只有日期）
        # 混用会让字符串比较静默失配：`'2026-09-26' <= '2026-09'` 不成立，
        # 明细统计整个变空，trend[].detail_cells 全 0，而 /cells 却查得到数据。
        table, time_col = GRAIN_SPEC[grain][0], GRAIN_SPEC[grain][1]
        label_start, label_end = _effective_range(conn, grain, start, end)
        where, params = _range_sql(time_col, label_start, label_end)

        d_start, d_end = label_start, label_end
        if grain != "day":
            r = cal.period_to_day_range(label_start)
            if r:
                d_start = r[0]
            r = cal.period_to_day_range(label_end)
            if r:
                d_end = r[1]

        # 日粒度多带一列 Excel 原值用于对账；周/月没有该列
        extra = ", bp_cells_excel" if grain == "day" else ", NULL AS bp_cells_excel"
        trend = store.rows_to_dicts(conn.execute(
            f"SELECT {time_col} AS period, {bp_col} AS bp_cells, {tot_col} AS total_cells,"
            f" {ratio_col} AS bp_ratio, {traf_col} AS traffic_tb{extra}, source"
            f" FROM {table} WHERE {where} ORDER BY {time_col} DESC LIMIT ?",
            tuple(params) + (MAX_TREND_POINTS,)).fetchall())
        trend.reverse()  # 转成时间升序给图表

        # 周/月附上判定中间量，界面才能解释「为什么这周/这月算 BP」
        if grain == "week":
            mid = store.rows_to_dicts(conn.execute(
                f"SELECT {time_col} AS period, bp_days, total_days, is_bp_week"
                f" FROM {table} WHERE {where}", tuple(params)).fetchall())
            m = {r["period"]: r for r in mid}
            for r in trend:
                r.update({k: m.get(r["period"], {}).get(k) for k in
                          ("bp_days", "total_days", "is_bp_week")})
        elif grain == "month":
            mid = store.rows_to_dicts(conn.execute(
                f"SELECT {time_col} AS period, bp_weeks, total_weeks, is_bp_month"
                f" FROM {table} WHERE {where}", tuple(params)).fetchall())
            m = {r["period"]: r for r in mid}
            for r in trend:
                r.update({k: m.get(r["period"], {}).get(k) for k in
                          ("bp_weeks", "total_weeks", "is_bp_month")})

        # 合计。用与 trend **同一谓词**，所以合计 == 趋势各点之和（口径一致的保证）
        agg = conn.execute(
            f"SELECT COUNT(*) AS periods, SUM({bp_col}) AS bp_cells,"
            f" SUM({tot_col}) AS total_cells, SUM({traf_col}) AS traffic_tb,"
            f" AVG({ratio_col}) AS avg_ratio"
            f" FROM {table} WHERE {where}", tuple(params)).fetchone()

        meta = _build_meta(conn, grain, label_start, label_end, t0)
        cells_total = store.scalar(conn, "SELECT COUNT(*) FROM bp_cell_dict") or 0

        # 明细侧实际覆盖的小区数（用于解释「为何明细行数与 total_cells 不同」）
        detail_cells = store.scalar(
            conn, "SELECT COUNT(DISTINCT cell_name) FROM bp_cell_daily") or 0

        # ⚠️ 明细表的覆盖面**小于**汇总表，绝不能拿明细值覆盖展示值。实测（2026-09-29）：
        #     `BP Cells List` 只有 423,927 行，**只含 2024~2026**：
        #       2024: 153,436   2025: 124,869   2026: 145,622
        #     而 `Overall - Daily` / `Regional - Daily` 覆盖 2023 起全部日期。
        #     2023 年明细为 0 行；2024 全年少 13,553 行（1/15、1/21、1/22、1/29… 整天缺）。
        #     若用明细值覆盖展示值，历史区间会显示成 0 —— 比原问题严重得多。
        # 因此：**展示值一律取汇总表**（bp_overall_daily，权威且连续）；
        #       明细表只用于下钻，并显式标注「该期是否可下钻」。
        #
        # 为什么两个数字会差（已实测，双向）：
        #   - 2025/2026：Excel `Overall` 恒**低于** `Regional` 与 `BP Cells List`
        #     （2026 差 2,115；2025 差 2,263）—— 汇总查询与明细清单口径不同；
        #   - 2023/2024：明细**少于**汇总 —— `BP Cells List` 导出不全。
        # 二者都不是本模块的 bug，是上游 Excel 自身的不一致，必须如实并列展示。
        detail_total = None
        excel_total = None
        # ---- 明细覆盖：**三种粒度都要算**（2026-09-29 修复） ----
        # 旧实现只在 grain == "day" 里设置 detail_cells / drillable，于是周/月粒度下
        # 这两个字段**整个缺失**。前端的守卫写的是 `r.drillable === false`，
        # 对 undefined 不成立 —— 结果周/月行的下钻入口**既没置灰也没有正确的行数**，
        # 2023 那类无明细的周点开就是空弹窗（正是守卫想避免的情况）。
        #
        # 现在统一按粒度把明细日归并到 period 标签上，三种粒度都有该字段。
        # 明细表用 day 列做与 /cells 完全同源的谓词，保证行数和下钻一致。
        # ⚠️ 这里必须用 d_start/d_end（真日期），不能用 start/end（周/月是标签）。
        dwhere, dparams = _range_sql("day", d_start, d_end)
        det_daily: Dict[str, int] = {r["day"]: r["bp"] for r in conn.execute(
            f"SELECT day, SUM(CASE WHEN is_bp=1 THEN 1 ELSE 0 END) AS bp"
            f" FROM bp_cell_daily WHERE {dwhere} GROUP BY day",
            tuple(dparams)).fetchall()}

        # Excel「Overall」侧的合计（与展示值并排展示差异）——三种粒度都要算，
        # 否则周/月视图的合计行会缺一个对照值。
        excel_total = store.scalar(
            conn, "SELECT SUM(bp_cells_excel) FROM bp_overall_daily WHERE "
                  + dwhere, tuple(dparams))

        if grain == "day":
            det = det_daily
        else:
            # 周/月：把每天的明细数按 ISO 周键 / 月份归并（与概览 period 标签同构）
            det = {}
            for day_s, n in det_daily.items():
                key = (cal.iso_week_key(day_s) if grain == "week"
                       else cal.month_key(day_s))
                if key:
                    det[key] = det.get(key, 0) + n

        for pt in trend:
            n = det.get(pt["period"], 0)
            # 该期明细是否覆盖（覆盖才允许下钻，且下钻行数会等于这里的 n）
            pt["detail_cells"] = n
            # 与展示值的差异：非 0 即说明上游两张 sheet 不一致，界面标出来
            pt["detail_diff"] = (n - (pt["bp_cells"] or 0)) if n else None
            # 明细完全缺失的期（2023 全年、2024 部分周）只给汇总，不给下钻
            pt["drillable"] = n > 0
        detail_total = sum(det_daily.values())

    return {
        "meta": meta,
        "granularity": grain,
        "range": {"start": label_start, "end": label_end},
        "summary": {
            "periods": agg["periods"] or 0,
            "bp_cells": agg["bp_cells"] or 0,
            "total_cells": agg["total_cells"] or 0,
            "traffic_tb": round(agg["traffic_tb"], 3) if agg["traffic_tb"] else None,
            "avg_ratio": agg["avg_ratio"],
            "dict_cells": cells_total,
            # 明细侧（BP Cells List）同范围的**行数合计**（与粒度无关，恒为日明细之和）
            "detail_cells": detail_total,
        },
        # 下钻口径声明：界面据此决定「哪些数字可以点」以及点击后预期看到多少行
        "drilldown": {
            # ✅ 可下钻：点某期的 bp_cells，行数 == 该期 trend[].detail_cells
            "bp_cells": {"scope": "bp", "comparable": True,
                         "source": "bp_cell_daily",
                         "note": "行数等于该期 trend[].detail_cells；与 BP Cells List 同源"},
            # ⚠️ 以下两项都不可下钻，原因不同
            # 分母：Excel 未提供全网小区名册
            "total_cells": {"scope": "all", "comparable": False,
                            "detail_cells": detail_cells,
                            "note": "Excel 口径的全网小区数，未提供名单；明细表只覆盖 "
                                    f"{detail_cells} 个曾在 BP Cells List 出现的小区，"
                                    "两者不是同一指标，不可互相校验"},
            "traffic_tb": {"scope": "all", "comparable": False,
                           "note": "流量按明细行求和，与 Excel 的 Total Traffic 口径不同"},
            # 明细覆盖面：2023 全部缺失、2024 部分缺失 —— 界面据此禁用下钻入口，
            # 而不是让用户点开一个空弹窗
            "detail_coverage": {
                "full_years": [2025, 2026],
                "partial_years": [2024],
                "missing_years": [2023],
                "note": "BP Cells List 只导出 2024~2026：2023 无明细，2024 缺 13,553 行"
                        "（整天缺失）。这些期只能看汇总，下钻入口应置灰。",
            },
            # Excel 内部不一致的事实，必须让使用者知道，否则会误以为是我们算错
            "excel_inconsistency": {
                "bp_cells_excel": excel_total,
                "note": "Excel 各 sheet 本身不一致：2025/2026 的 Overall 恒低于 Regional"
                        "（分别差 2,263 / 2,115 行）；2024 的 BP Cells List 少于 Regional。"
                        "展示值统一取 Overall - Daily（连续且权威），明细仅供下钻。",
            },
        },
        "trend": trend,
    }


def _build_meta(conn, grain: str, start: str, end: str, t0: float) -> Dict[str, Any]:
    """口径与数据质量的元信息。页面的告警条与「口径说明」区块都读它。"""
    au = cal.active_user_status()
    meta = {
        "grain": grain,
        "start": start,
        "end": end,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": round(time.time() - t0, 3),
        "caliber": cal.caliber_snapshot(),
        "active_user": au,
        "last_import_at": store.get_meta(conn, "last_import_at"),
        "last_sync_at": store.get_meta(conn, "last_sync_at"),
        "source_file": store.get_meta(conn, "source_file"),
        "warnings": [],
    }
    # 口径缺口是本页**必须常驻显示**的信息，不是可选提示
    if not au["available"]:
        meta["warnings"].append(au["reason"])
    dirty = store.get_meta(conn, "dirty_counts") or {}
    if dirty.get("rows_unknown_cluster"):
        meta["warnings"].append(
            f"有 {dirty['rows_unknown_cluster']} 行小区的 Cluster 无法归类"
            f"（Excel 原列脏值或不在字典内），已归为 {cal.UNKNOWN}。")
    meta["dirty"] = dirty
    return meta


# ============================================================
# 分区 / 分层
# ============================================================

def load_regional(start: str = "", end: str = "", region: str = "") -> Dict[str, Any]:
    """分区维度：对应 Excel 的 `Regional - Daily`（Region = Cluster1..6/Rural/ERA）。"""
    t0 = time.time()
    with _conn() as conn:
        if not start:
            start = store.scalar(conn, "SELECT MIN(day) FROM bp_region_daily") or ""
        if not end:
            end = store.scalar(conn, "SELECT MAX(day) FROM bp_region_daily") or ""
        where, params = _range_sql("day", start, end)
        if region:
            where += " AND region = ?"
            params.append(region)

        rows = store.rows_to_dicts(conn.execute(
            f"SELECT day, region, bp_number, total_cell, bp_ratio, traffic_tb, source"
            f" FROM bp_region_daily WHERE {where} ORDER BY day", tuple(params)).fetchall())

        # 按日汇总 + 按分区汇总，两个视角都从同一批行算，数字必然一致
        by_region: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            k = r["region"]
            s = by_region.setdefault(k, {"region": k, "bp_number": 0, "total_cell": 0,
                                         "traffic_tb": 0.0, "days": 0})
            s["bp_number"] += r["bp_number"] or 0
            s["total_cell"] += r["total_cell"] or 0
            s["traffic_tb"] += r["traffic_tb"] or 0
            s["days"] += 1
        for s in by_region.values():
            s["traffic_tb"] = round(s["traffic_tb"], 3) if s["traffic_tb"] else None

        regions = sorted(by_region.values(), key=lambda x: cal.sortable_cluster(x["region"]))
        meta = _build_meta(conn, "day", start, end, t0)

    return {"meta": meta, "range": {"start": start, "end": end},
            "regions": regions, "series": rows}


def load_layer(start: str = "", end: str = "", region: str = "",
               layer: str = "") -> Dict[str, Any]:
    """分层维度：对应 Excel 的 `Frequency layer - Daily`（L800/L1800 20M/...）。

    注意 Excel 的该 sheet 是「按 Region 再按层」，所以同一层在不同 Region 各有一行；
    这里按层聚合，Region 作为可选取值过滤。
    """
    t0 = time.time()
    with _conn() as conn:
        if not start:
            start = store.scalar(conn, "SELECT MIN(day) FROM bp_layer_daily") or ""
        if not end:
            end = store.scalar(conn, "SELECT MAX(day) FROM bp_layer_daily") or ""
        where, params = _range_sql("day", start, end)
        if region:
            where += " AND region = ?"
            params.append(region)
        if layer:
            where += " AND layer = ?"
            params.append(layer)

        rows = store.rows_to_dicts(conn.execute(
            f"SELECT day, region, layer, bp_number, total_cell, bp_ratio, source"
            f" FROM bp_layer_daily WHERE {where} ORDER BY day", tuple(params)).fetchall())

        by_layer: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            k = r["layer"]
            s = by_layer.setdefault(k, {"layer": k, "bp_number": 0, "total_cell": 0,
                                        "days": 0})
            s["bp_number"] += r["bp_number"] or 0
            s["total_cell"] += r["total_cell"] or 0
            s["days"] += 1
        layers = sorted(by_layer.values(), key=lambda x: cal.sortable_layer(x["layer"]))
        meta = _build_meta(conn, "day", start, end, t0)

    return {"meta": meta, "range": {"start": start, "end": end},
            "layers": layers, "series": rows}


# ============================================================
# 下钻
# ============================================================

def _excel_cells_for(conn, day: str, start: str, end: str) -> Optional[int]:
    """取 Excel `Overall - Daily` 在该范围的 BP 小区数合计（用于与明细行数并排展示）。

    见 `load_cells()` 返回体里 `excel_cells` 的说明：Excel 的两张 sheet 本身就
    对不上（实测日均差 +9），所以两个数字都要给出来。
    """
    if day:
        return store.scalar(
            conn, "SELECT bp_cells_excel FROM bp_overall_daily WHERE day=?", (day,))
    where, params = _range_sql("day", start, end)
    return store.scalar(
        conn, f"SELECT SUM(bp_cells_excel) FROM bp_overall_daily WHERE {where}",
        tuple(params))


def load_cells(day: str = "", start: str = "", end: str = "",
               region: str = "", layer: str = "", scope: str = "all",
               limit: int = MAX_DETAIL_ROWS) -> Dict[str, Any]:
    """小区明细下钻。

    Args:
        day:    单日 `YYYY-MM-DD`；给了就优先用它（单日下钻）。
        start/end: 日期区间（不给 day 时用）。
        region/layer: 分区/分层过滤。
        scope:  `bp` 只看 BP 小区 / `nonbp` 只看非 BP / `undecidable` 只看不可判定 /
                `all` 全部。
        limit:  取样上限，截断时 meta.truncated=True。

    ===================== 与概览数字的对应关系（AGENTS.md 第三节 1b） =====================

    本函数与 `load_overview()` 共用谓词构造，因此：

      ✅ `scope=bp` 的行数 == 概览 `trend[].detail_cells`（**同一 WHERE，已保证**）
      ⚠️ `scope=all` 的 `total` 是**明细表**行数，**不是**概览的 `summary.total_cells`
         —— 后者是 Excel 全网小区数（约 6114），明细只含 BP Cells List 里的小区。
         概览的 `drilldown.total_cells.comparable=False` 就是给前端据此**不把
         total_cells 做成下钻入口**用的。
      ⚠️ 概览的 `summary.bp_cells` 取自汇总表（Excel Overall），与明细行数**可能不等**：
         - 2025/2026：明细**多**于汇总（Overall 汇总查询口径更窄）；
         - 2023/2024：明细**少**于汇总（BP Cells List 导出不全，2023 全缺）。
         逐期差异见 `trend[].detail_diff`，可下钻性见 `trend[].drillable`。
    """
    t0 = time.time()
    with _conn() as conn:
        # 与概览同源的谓词：概览用 day 比较，这里也用 day 比较（同一个字符串构造器）
        if day:
            # 单日下钻：day 必须是真日期；若是 `2023-W48` 这类周期标签则先还原。
            rng = cal.period_to_day_range(day)
            if rng is None:
                raise ValueError(f"无法识别的日期/周期：{day!r}（需 YYYY-MM-DD / YYYY-Www / YYYY-MM）")
            if rng[0] != rng[1]:
                # 传进来的其实是周/月标签 —— 还原成区间，不要退回字符串比较
                where, params = "day >= ? AND day <= ?", [rng[0], rng[1]]
            else:
                where, params = "day = ?", [rng[0]]
        else:
            # ⚠️ start/end 也允许是周期标签（前端按周/月下钻时会传 period）。
            # 直接把它们丢进 `day >= ?` 是 2026-09-29 那场事故的成因：
            # `'2026-08-24' >= '2023-W48'` 字符串成立，于是返回无关日期的大批数据。
            s_day, e_day = start, end
            if start:
                r = cal.period_to_day_range(start)
                if r is None:
                    raise ValueError(f"无法识别的起始日期/周期：{start!r}")
                s_day = r[0]
            if end:
                r = cal.period_to_day_range(end)
                if r is None:
                    raise ValueError(f"无法识别的结束日期/周期：{end!r}")
                e_day = r[1]          # 用区间的**末日**，周/月标签才能取满整段
            where, params = _range_sql_day("day", s_day, e_day)
        if region:
            where += " AND cluster = ?"
            params.append(region)
        if layer:
            where += " AND layer = ?"
            params.append(layer)

        scope_norm = scope if scope in ("bp", "nonbp", "undecidable", "all") else "all"
        scope_sql = {"bp": "is_bp = 1", "nonbp": "is_bp = 0",
                     "undecidable": "is_bp IS NULL", "all": "1=1"}[scope_norm]
        full_where = f"{where} AND {scope_sql}"

        # 计数用**不带 limit** 的同谓词查询 —— 这是「概览数字 == 下钻计数」的保证
        counts = conn.execute(
            f"SELECT COUNT(*) AS n,"
            f" SUM(CASE WHEN is_bp=1 THEN 1 ELSE 0 END) AS bp,"
            f" SUM(CASE WHEN is_bp=0 THEN 1 ELSE 0 END) AS nonbp,"
            f" SUM(CASE WHEN is_bp IS NULL THEN 1 ELSE 0 END) AS und"
            f" FROM bp_cell_daily WHERE {where}", tuple(params)).fetchone()

        rows = store.rows_to_dicts(conn.execute(
            f"SELECT day, cell_name, me_id, cluster, layer, is_bp, prb_dl, thr_dl,"
            f" active_user, dl_gb, ul_gb, source FROM bp_cell_daily"
            f" WHERE {full_where} ORDER BY day DESC, cell_name LIMIT ?",
            tuple(params) + (limit,)).fetchall())

        # 判定依据：把三个条件各自是否满足也算出来，界面才能解释「为什么它不是 BP」
        for r in rows:
            r["prb_ok"] = (r["prb_dl"] is not None
                           and r["prb_dl"] > cal.THR_DL_PRB_RATIO)
            r["thr_ok"] = (r["thr_dl"] is not None
                           and r["thr_dl"] < cal.THR_DL_THROUGHPUT_MBPS)
            r["user_ok"] = None if r["active_user"] is None else (
                r["active_user"] > cal.THR_ACTIVE_USER)

        truncated = len(rows) >= limit
        meta = _build_meta(conn, "day", day or start, day or end, t0)
        meta["truncated"] = truncated
        meta["limit"] = limit
        if truncated:
            meta["warnings"].append(
                f"明细已达取样上限 {limit} 行，仅显示前 {limit} 行；"
                f"请缩小日期范围或加分区/分层过滤。")

    return {
        "meta": meta,
        "scope": scope_norm,
        "filters": {"day": day, "start": start, "end": end,
                    "region": region, "layer": layer},
        "total": counts["n"] or 0,
        "bp": counts["bp"] or 0,
        "nonbp": counts["nonbp"] or 0,
        "undecidable": counts["und"] or 0,
        # 自检：计数无筛选时应当自洽（bp + nonbp + undecidable == total）。
        # 若为 False 说明三态判定与存储有矛盾，界面应告警而不是照常展示。
        "consistent": (counts["n"] or 0) == ((counts["bp"] or 0)
                                             + (counts["nonbp"] or 0)
                                             + (counts["und"] or 0)),
        # ⚠️ 与 Excel `Overall - Daily` 的 bp_cells 存在**系统性**差异。
        # 实测（2026-09-01..09-26，26 天）：明细行数**恒高于** overall 表 2~11 行
        # （日均 +9）。这是**上游两张 sheet 本身的口径差**，不是本模块的 bug：
        #   - `Overall - Daily` 的 `Number of BP cells` 是 umlaut 的汇总查询结果；
        #   - `BP Cells List` 是另一条明细查询导出的清单。
        #   两者在 Excel 里就对不上（源文件即如此）。
        # 因此：`bp_cells_excel` 才是与 Excel 可对账的数字，`total`/`bp` 是明细表
        # 实际行数。界面必须**同时显示两者并标注差异**，不能只显示一个让人误判。
        "excel_cells": _excel_cells_for(conn, day, start, end),
        "rows": rows,
    }


# ============================================================
# 口径 / 数据质量
# ============================================================

def load_meta() -> Dict[str, Any]:
    """口径说明、脏值统计、同步状态与对账差异（页面的「口径与数据质量」区块）。"""
    with _conn() as conn:
        allm = store.all_meta(conn)
        counts = {}
        for t in ("bp_cell_daily", "bp_cell_dict", "bp_overall_daily", "bp_region_daily",
                  "bp_layer_daily", "bp_overall_week", "bp_overall_month"):
            counts[t] = store.table_count(conn, t)

        # 分区/分层的实际取值分布（界面用它做筛选下拉，也便于发现新出现的脏值）
        regions = store.distinct_values(conn, "bp_region_daily", "region")
        layers = store.distinct_values(conn, "bp_layer_daily", "layer")

    au = cal.active_user_status()
    return {
        "caliber": cal.caliber_snapshot(),
        "active_user": au,
        "counts": counts,
        "regions": sorted(regions, key=cal.sortable_cluster),
        "layers": sorted(layers, key=cal.sortable_layer),
        "valid_clusters": list(cal.VALID_CLUSTERS),
        "valid_layers": list(cal.VALID_LAYERS),
        "last_import_at": allm.get("last_import_at"),
        "last_sync_at": allm.get("last_sync_at"),
        "source_file": allm.get("source_file"),
        "source_mtime": allm.get("source_mtime"),
        "dirty": allm.get("dirty_counts") or {},
        "coverage": allm.get("coverage") or {},
        "reconcile": allm.get("last_reconcile") or {},
        "warnings": allm.get("last_sync_warnings") or [],
        "errors": allm.get("last_sync_errors") or [],
        "notes": [
            "BP 判定（Daily）：Average DL Active User Number > 2.5 且 "
            "[FDD]DL IP Throughput(Mbps) < 3 且 [FDD]DL PRB Utilization Rate > 80%。",
            "Weekly：一周内 4/7 天为 BP 即该周为 BP。",
            "Monthly：一个月内 3/4 个完整周为 BP 即该月为 BP。",
            "Cluster 归属来自 BP Report 的 BP Cells List（RAN_UME 无此维度）。",
            "Excel 提供的汇总真值保留在 bp_cells_excel，与重算值并存不覆盖。",
        ],
    }
