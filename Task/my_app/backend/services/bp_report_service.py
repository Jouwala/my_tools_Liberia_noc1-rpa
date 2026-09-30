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

from backend.database import get_raw_connection
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


def _bound_to_label(grain: str, bound: str, is_start: bool) -> str:
    """把一个**日期**边界转成该粒度 `time_col` 里真正存的**周期标签**。

    为什么必须有这一步（2026-09-30 修的线上 bug）：
      前端 `rangeParams()` 恒定传 `YYYY-MM-DD`（`BpReport.tsx:191`），
      但 `bp_overall_week.week` 存的是 `2026-W40`、`bp_overall_month.month` 存的是 `2026-09`。
      拿日期去和标签做字符串比较会**静默失配**：
        `'2026-W35' >= '2026-08-25'` → False（第 6 位 `'W'`(0x57) > `'0'`(0x30)），
      于是 `week` 粒度的 trend **整段为空**（实测 trend 点数 0，用户报的正是这个）；
      `month` 更隐蔽：`'2026-09' >= '2026-08-25'` 侥幸为 True，但
      `'2026-08' >= '2026-08-25'` 为 False —— 于是**八月被悄悄丢掉**，
      8~9 月只返回 1 个点而不是 2 个，界面看着"有数据"，实际漏了一整月。

    转换规则（start 取「不早于该边界」、end 取「不晚于该边界」）：
      - week ：`iso_week_key(日期)`，边界日期所在 ISO 周。start 用所在周、
               end 也用所在周 —— 因为 `period_to_day_range()` 还原时本就按整周取，
               两者对同一周会得到同一个标签，前后一致。
      - month：`month_key(日期)` → `YYYY-MM`。
      - day  ：原样（`day` 列存的就是 `YYYY-MM-DD`）。
    已经是标签形态的输入（`2026-W40` / `2026-09`）经 `day_str()` 归一后转换结果不变，
    所以重复调用是幂等的，旧的「传标签边界」调用方也不会被破坏。
    """
    if not bound:
        return bound
    if grain == "day":
        return bound
    if grain == "week":
        key = cal.iso_week_key(bound)
        return key or bound
    if grain == "month":
        key = cal.month_key(bound)
        return key or bound
    return bound


def _effective_range(conn, grain: str, start: str, end: str) -> Tuple[str, str]:
    """把空范围补成数据实际边界，避免前端拿到空区间。

    返回的是**周期标签**形态（日粒度即日期，周/月粒度是 `2023-W48` / `2023-04`），
    因为 trend 查询比较的 `week`/`month` 列存的就是标签。
    需要真日期时由调用方用 `cal.period_to_day_range()` 转换
    —— **不要**拿标签去和 `bp_cell_daily.day` 比较（字符串比较会静默失配）。

    ⚠️ 传进来的 start/end 也可能是**日期**（前端就是），必须经 `_bound_to_label()`
    归一，否则周粒度整段为空、月粒度静默丢月 —— 详见该函数 docstring。
    """
    table, time_col = GRAIN_SPEC[grain][0], GRAIN_SPEC[grain][1]
    if not start:
        start = store.scalar(conn, f"SELECT MIN({time_col}) FROM {table}") or ""
    else:
        start = _bound_to_label(grain, start, True)
    if not end:
        end = store.scalar(conn, f"SELECT MAX({time_col}) FROM {table}") or ""
    else:
        end = _bound_to_label(grain, end, False)
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
        # 逐日的三个量一起取（同一谓词、同一次扫描）：
        #   bp   —— is_bp=1 的行数（既有语义，下钻 scope=bp 与之相等）
        #   und  —— is_bp IS NULL 的行数（当日「不可判定」的小区数）
        #   tot  —— 当日明细行数（**ume 天**下它恒等于概览的 total_cells，
        #           见 `_recompute_daily`：分母就是该口径下出现的全部小区行数。
        #           excel 天的 total_cells 是 Excel 全网口径、无名单，不可下钻。）
        det_daily: Dict[str, int] = {}
        und_daily: Dict[str, int] = {}
        tot_daily: Dict[str, int] = {}
        for r in conn.execute(
                f"SELECT day, COUNT(*) AS n,"
                f" SUM(CASE WHEN is_bp=1 THEN 1 ELSE 0 END) AS bp,"
                f" SUM(CASE WHEN is_bp IS NULL THEN 1 ELSE 0 END) AS und"
                f" FROM bp_cell_daily WHERE {dwhere} GROUP BY day",
                tuple(dparams)).fetchall():
            det_daily[r["day"]] = r["bp"] or 0
            und_daily[r["day"]] = r["und"] or 0
            tot_daily[r["day"]] = r["n"] or 0

        # Excel「Overall」侧的合计（与展示值并排展示差异）——三种粒度都要算，
        # 否则周/月视图的合计行会缺一个对照值。
        excel_total = store.scalar(
            conn, "SELECT SUM(bp_cells_excel) FROM bp_overall_daily WHERE "
                  + dwhere, tuple(dparams))

        if grain == "day":
            det, und, tot_rows = det_daily, und_daily, tot_daily
        else:
            # 周/月：把每天的明细数按 ISO 周键 / 月份归并（与概览 period 标签同构）
            det, und, tot_rows = {}, {}, {}
            for day_s, n in det_daily.items():
                key = (cal.iso_week_key(day_s) if grain == "week"
                       else cal.month_key(day_s))
                if key:
                    det[key] = det.get(key, 0) + n
                    und[key] = und.get(key, 0) + und_daily.get(day_s, 0)
                    tot_rows[key] = tot_rows.get(key, 0) + tot_daily.get(day_s, 0)

        for pt in trend:
            n = det.get(pt["period"], 0)
            # 该期明细是否覆盖（覆盖才允许下钻，且下钻行数会等于这里的 n）
            pt["detail_cells"] = n
            # 与展示值的差异：非 0 即说明上游两张 sheet 不一致，界面标出来
            pt["detail_diff"] = (n - (pt["bp_cells"] or 0)) if n else None
            # 明细完全缺失的期（2023 全年、2024 部分周）只给汇总，不给下钻
            pt["drillable"] = n > 0
            # 不可判定小区数：日粒度即当日 is_bp IS NULL 的行数；
            # 界面据此给出「已判定 / 不可判定 N 个」的真实状态，并可下钻到这 N 行。
            pt["undecidable"] = und.get(pt["period"], 0)
            # total_cells 能否下钻：只有当该期的 total_cells **就是**明细表在该期的
            # 行数时才给入口（ume 天成立；excel 天的 total_cells 是 Excel 全网口径、
            # 未提供名单，点开必然对不上，那是比不给点更糟的体验）。
            pt["total_drillable"] = bool(
                tot_rows.get(pt["period"], 0) > 0
                and pt["source"] == "ume"
                and tot_rows.get(pt["period"]) == (pt["total_cells"] or 0))

        # 周/月判定的「为什么不可判定」：三态里的 None 有两个完全不同的成因，
        # 界面必须能分别解释，否则用户只会看到一句无信息量的「不可判定」：
        #   ① 周期未过完（数据天数/完整周数不足）—— 等时间走完自然会出结论；
        #   ② 结构性不足（如 2026-09 只有 3 个完整周 < 口径要求的 4 个）——
        #      这个月**永远**判不出来，是口径与日历的错配，不是数据缺失。
        for pt in trend:
            if grain == "week":
                if pt.get("is_bp_week") is None:
                    have = pt.get("total_days") or 0
                    pt["verdict_reason"] = ("incomplete" if have < cal.WEEK_TOTAL_DAYS
                                            else "no_data")
                else:
                    pt["verdict_reason"] = ""
            elif grain == "month":
                if pt.get("is_bp_month") is None:
                    have = pt.get("total_weeks") or 0
                    pt["verdict_reason"] = ("insufficient_weeks"
                                            if have < cal.MONTH_TOTAL_WEEKS
                                            else "no_data")
                else:
                    pt["verdict_reason"] = ""
            else:
                pt["verdict_reason"] = ""
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
            # ⚠️ `total_cells` 的可下钻性**逐期不同**，不是一个全局常量：
            #   - `source='ume'` 的期：分母就是明细表在该期的行数（`_recompute_daily`
            #     的定义），因此 `scope=all` 下钻行数**恰好等于** total_cells；
            #   - `source='excel'` 的期：total_cells 是 Excel 的「全网小区数」，
            #     未提供名单，明细只覆盖 BP Cells List 里的小区，点开必然对不上。
            # 前端因此改用 `trend[].total_drillable` 逐期判断，而不再一律禁用。
            "total_cells": {"scope": "all", "comparable": "per_period",
                            "detail_cells": detail_cells,
                            "note": "Excel 口径的全网小区数，未提供名单；明细表只覆盖 "
                                    f"{detail_cells} 个曾在 BP Cells List 出现的小区。"
                                    "ume 来源的期可下钻（分母即明细行数），"
                                    "excel 来源的期不可下钻 —— 见 trend[].total_drillable"},
            "traffic_tb": {"scope": "all", "comparable": False,
                           "note": "流量按明细行求和，与 Excel 的 Total Traffic 口径不同"},
            # 判定口径的阈值：界面用它解释「为什么这期判不出来」
            "verdict_rule": {
                "week_bp_days": cal.WEEK_BP_DAYS,
                "week_total_days": cal.WEEK_TOTAL_DAYS,
                "month_bp_weeks": cal.MONTH_BP_WEEKS,
                "month_total_weeks": cal.MONTH_TOTAL_WEEKS,
                "note": "周判定需 7 天全有数据；月判定需 ≥4 个完整周。"
                        "因此「本周未过完」与「本月只有 3 个完整周」都会得到"
                        "「不可判定」，但两者性质不同：前者等时间走完即可判定，"
                        "后者是这个月**永远**判不出来（口径与日历错配）。"
                        "逐期成因见 trend[].verdict_reason。",
            },
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


def _attach_site_names(rows: List[Dict[str, Any]]) -> None:
    """给明细行补 `site_name`（按 `me_id` 关联主库的站点名表）。**尽力而为，不抛错。**

    ===================== 为什么在物化库之外另查 =====================
    BP 的物化库是**独立 sqlite**（`data/bp_report.sqlite3`，见 bp_report_store.py:4-13），
    而站点名在主库 PG 的 `app.cm_cell_data` 里（`Site_ID` / `Site_Name` / `Cell_Name` / `Tech`）。
    两者不同库，无法 JOIN，只能在应用层按 `me_id` 批量查一次再贴回来。
    刻意**不**把站点名冗余进 `bp_cell_daily`：那是派生库，站点名是主库的活数据，
    复制进来就多一份会过期的真相源（AGENTS.md 四.5）。

    ===================== 关联键为什么是 me_id =====================
    `me_id` 就是 **ManagedElement ID**，即 `cm_cell_data.Site_ID`。实测（2026-09-30）：
      · 按 `me_id == Site_ID` 关联：BP 去重 me_id 745 个，命中 733 个 = **98.4%**；
      · 按 `cell_name == Cell_Name` 关联：6297 个小区只命中 1340 个 = **21.3%**，
        且**同站不同扇区会指向不同 Site_ID**（实测 `10th Street-S0` → 1300，
        而 `-S1`/`-S2` → 5300），说明小区名不可作关联键。
    未命中的 12 个 me_id（占明细 2499 行 / 0.53%）`site_name` 留空，
    前端按 AGENTS.md 三.6 显示 `—`，不显示成 0。

    ===================== 降级策略 =====================
    主库不可达（PG 挂 / 连接串错 / SQLite 模式）时**只记 warning 并返回**，
    站点名整体留空 —— 下钻的主功能（BP 明细与判定依据）不因附属字段而失败。
    这也保证 `MY_APP_DB_MODE=sqlite` 回退路径（R7 熔断开关）下页面照常可用。
    """
    if not rows:
        return
    ids = sorted({str(r.get("me_id")).strip()
                  for r in rows if r.get("me_id") not in (None, "")})
    if not ids:
        return
    try:
        conn = get_raw_connection()
        try:
            cur = conn.cursor()
            # 占位符由 get_raw_connection 统一转换（pg 模式会 ? -> %s），与其它查询一致
            marks = ",".join("?" for _ in ids)
            cur.execute(
                f'SELECT "Site_ID", "Site_Name" FROM app.cm_cell_data'
                f' WHERE "Site_ID" IN ({marks})', tuple(ids))
            mapping = {str(sid).strip(): str(sname or "").strip()
                       for sid, sname in cur.fetchall() if sname}
        finally:
            conn.close()
    except Exception as exc:                                 # noqa: BLE001
        logger.warning("站点名查询失败（下钻仍返回，site_name 留空）：%s", exc)
        return
    for r in rows:
        key = str(r.get("me_id") or "").strip()
        r["site_name"] = mapping.get(key) or None


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

        # 站点名（用户要求：Site ID 之外最好也能看到站点名）。
        # 在**物化库之外**单独查，见 `_attach_site_names()` 的 docstring。
        _attach_site_names(rows)

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
