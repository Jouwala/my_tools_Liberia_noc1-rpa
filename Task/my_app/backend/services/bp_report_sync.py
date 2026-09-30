# -*- coding: utf-8 -*-
"""BP Report —— 从 RAN_UME 更新（每日任务）。

=========================== 做什么 ===========================

1. 从 RAN_UME 侧读取 4G 小区级日指标（PRB 利用率 / DL IP 吞吐 / 流量）；
2. 关联 `bp_cell_dict` 补上 Cluster / Layer（**RAN_UME 没有这个维度**）；
3. 按 `bp_caliber` 的 BP 口径重算每小区每日 `is_bp`，UPSERT 进 `bp_cell_daily`；
4. 重算日/周/月汇总（周用 4/7、月用 3/4 判定）；
5. 与 Excel 导入的**历史真值对账**，差异写入 `bp_sync_meta`。

=========================== 数据来源 ===========================

读**远端口径**的 `db.sqlite3.4G_Main_Kpi_Cell_Daily`（经 `remote_readonly`），
而不是本机 `Task\\RAN\\db.sqlite3` —— 后者是运维副本，实测冻结在 2026-06-15，
而 BP Report 要更新到当天。

指标列（该表已含全部所需列，**不需要新建 UME PM 模板**）：
    prb_dl = "1638004469342:[FDD]DL PRB Utilization Rate[SDR_ITBBU]"
    thr_dl = "1638004469332:[FDD]DL IP Throughput(Mbps)[SDR_ITBBU]"
    dl_gb  = "1638004469330:[FDD]DL Traffic Volume (GBytes)-new"
    ul_gb  = "1638004469331:[FDD]UL Traffic Volume (GBytes)-new"

⚠️ **`Average DL Active User Number` 走独立通道**（2026-09-30 接入）。
该指标**不在** `4G_Main_Kpi_Cell_Daily` 里，且**加不进去**：那张表由日粒度
任务（`gr=86400`）写入，而该指标**只在小时粒度（`gr=3600`）可用**，日粒度下
UME 会 HTTP 200 + 静默丢弃该列（原文 `PDF counter/indicator dimension is illegal`）。
故改由 `bp_active_user` 按小时取数、本地聚合成**当日峰值**后并入判定。
取不到时该日仍记 `is_bp = NULL`（不可判定），**不猜、不当 0**。

=========================== 与 Excel 的关系（重要） ===========================

Excel 是**上游（umlaut）按自己口径算好的结果**。三个条件里 PRB/吞吐取自
RAN_UME 日表，Active User 取自 UME 小时粒度的当日峰值，故本项目是
**可复现口径的重算**；但 Excel 的 Cluster/Layer 归类仍以它为权威。

- Excel 导入的行 `source='excel'`；重算只写 `is_bp/prb_dl/thr_dl/dl_gb/ul_gb/active_user`
  这些**指标列**，`cluster/layer/region` 保持 Excel 的权威值不动；
- 重新计算的日汇总写入 `bp_overall_daily.bp_cells`，而 Excel 原值一直保留在
  `bp_cells_excel` 列 —— 两个数字**并存**，`/meta` 给出差异，页面可对照。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from backend.services import bp_active_user as au_src
from backend.services import bp_caliber as cal
from backend.services import bp_report_store as store

logger = logging.getLogger("bp_report_sync")

# 远端源库（逻辑名，见 db_writer_api 的 GET /api/dbs）
SRC_DB = "db.sqlite3"
SRC_TABLE = cal.UME_CELL_TABLE

# 远端 API 一次最多 5 万行（remote_readonly.MAX_LIMIT），逐日分片取。
REMOTE_LIMIT = 50000

# 默认回看天数：覆盖昨天+今天，与其它 UME 日任务一致（cells_kpi_sync 也是 2 天）。
DEFAULT_WINDOW_DAYS = 2


def _sql_str(s: Any) -> str:
    return "'" + str(s or "").replace("'", "''") + "'"


def _fetch_days(days: List[str], timeout: int = 600) -> List[Tuple[Any, ...]]:
    """按天从远端取 4G 小区级指标。

    **逐日一条 SQL**，而不是整个窗口一条：远端单次 limit 上限 50000，而全网
    小区 × 1 天就可达数万行，多天合并必然被截断且**静默**（远端只是少返回行）。
    逐日取时单日仍可能逼近上限，因此返回值会被调用方核对行数并告警。
    """
    from backend.services.remote_readonly import query_rows

    # 只取**确认存在**的列。`Average DL Active User Number` 不在远端表里，
    # 若把它拼进 SELECT，SQLite 会把双引号标识符当字符串字面量返回，
    # 整列变成「列名文本」而不报错 —— 所以先过一道列名守卫。
    cols_wanted = [cal.COL_DAY, "ManagedElement ID", cal.COL_CELL_NAME,
                   cal.COL_PRB_DL, cal.COL_THR_DL, cal.COL_DL_GB, cal.COL_UL_GB]
    cal.assert_columns_exist(cols_wanted)
    cols = '","'.join(cols_wanted)
    out: List[Tuple[Any, ...]] = []
    for day in days:
        sql = (f'SELECT "{cols}" FROM "{SRC_TABLE}" '
               f'WHERE "{cal.COL_DAY}" LIKE {_sql_str(day + "%")}')
        rows = query_rows(SRC_DB, sql, limit=REMOTE_LIMIT, timeout=timeout)
        if len(rows) >= REMOTE_LIMIT:
            # 撞上限 = 当天数据被静默截断，必须显式暴露（AGENTS.md 1b 的截断铁律）
            raise RuntimeError(
                f"{day} 返回行数达到远端上限 {REMOTE_LIMIT}，数据可能被截断；"
                f"请把该日拆成更细的分片查询")
        logger.info("[BP] 远端 %s 取回 %s 行", day, len(rows))
        cal.assert_no_literal_fallback(rows, cols_wanted)
        out.extend(rows)
    return out


def _load_dict(conn) -> Dict[str, Tuple[str, str]]:
    """读小区 → (cluster, layer) 字典。"""
    return {r["cell_name"]: (r["cluster"], r["layer"])
            for r in conn.execute("SELECT cell_name, cluster, layer FROM bp_cell_dict")}


# ============================================================
# 汇总重算
# ============================================================

def _recompute_daily(conn, days: List[str], now: str) -> Dict[str, Any]:
    """按重算后的 `bp_cell_daily` 重算 `bp_overall_daily` / `bp_region_daily` /
    `bp_layer_daily` 的 BP 计数。

    分母（Total Cells）用**该口径下出现的全部小区行数**；分子（BP）只数
    `is_bp = 1` —— `NULL`（不可判定）既不算分子也不算分母以外的处理，
    它仍在分母里（小区确实存在），但永远不进分子。
    """
    stats = {"days": 0, "bp_cells": 0, "undecidable": 0}
    for day in days:
        rows = conn.execute(
            "SELECT cluster, layer, is_bp, dl_gb, ul_gb, prb_dl, thr_dl "
            "FROM bp_cell_daily WHERE day=?", (day,)).fetchall()
        if not rows:
            continue
        stats["days"] += 1
        total = len(rows)
        bp = sum(1 for r in rows if r["is_bp"] == 1)
        und = sum(1 for r in rows if r["is_bp"] is None)
        stats["bp_cells"] += bp
        stats["undecidable"] += und

        # 流量（TB）= (DL + UL) GB / 1024，只算非 ERA 分区 —— 对齐 Excel 的
        # "4G_Data_Traffic(TB) - excluding ERA" 口径。
        gb = sum((r["dl_gb"] or 0) + (r["ul_gb"] or 0)
                 for r in rows if (r["cluster"] or "") != "ERA")
        traffic_tb = round(gb / 1024.0, 6) if gb else None

        conn.execute(
            "INSERT INTO bp_overall_daily(day, bp_cells, total_cells, bp_ratio, traffic_tb,"
            " bp_cells_excel, native_date, source, updated_at)"
            " VALUES (?,?,?,?,?, COALESCE((SELECT bp_cells_excel FROM bp_overall_daily"
            " WHERE day=?), NULL), NULL, 'ume', ?)"
            " ON CONFLICT(day) DO UPDATE SET bp_cells=excluded.bp_cells,"
            " total_cells=excluded.total_cells, bp_ratio=excluded.bp_ratio,"
            " traffic_tb=COALESCE(excluded.traffic_tb, bp_overall_daily.traffic_tb),"
            " source=excluded.source, updated_at=excluded.updated_at",
            (day, bp, total, (round(bp / total, 9) if total else None), traffic_tb,
             day, now))

        # 分区
        by_region: Dict[str, List[Any]] = {}
        for r in rows:
            by_region.setdefault(r["cluster"] or cal.UNKNOWN, []).append(r)
        for region, rs in by_region.items():
            t = len(rs)
            b = sum(1 for r in rs if r["is_bp"] == 1)
            g = sum((r["dl_gb"] or 0) + (r["ul_gb"] or 0) for r in rs)
            conn.execute(
                "INSERT INTO bp_region_daily(day, region, bp_number, total_cell,"
                " bp_ratio, traffic_tb, source, updated_at) VALUES (?,?,?,?,?,?,'ume',?)"
                " ON CONFLICT(day, region) DO UPDATE SET bp_number=excluded.bp_number,"
                " total_cell=excluded.total_cell, bp_ratio=excluded.bp_ratio,"
                " traffic_tb=excluded.traffic_tb, source=excluded.source,"
                " updated_at=excluded.updated_at",
                (day, region, b, t, (round(b / t, 9) if t else None),
                 (round(g / 1024.0, 6) if g else None), now))

        # 分层（按 region × layer）
        by_layer: Dict[Tuple[str, str], List[Any]] = {}
        for r in rows:
            key = (r["cluster"] or cal.UNKNOWN, r["layer"] or cal.UNKNOWN)
            by_layer.setdefault(key, []).append(r)
        for (region, layer), rs in by_layer.items():
            t = len(rs)
            b = sum(1 for r in rs if r["is_bp"] == 1)
            conn.execute(
                "INSERT INTO bp_layer_daily(day, region, layer, bp_number, total_cell,"
                " bp_ratio, source, updated_at) VALUES (?,?,?,?,?,?,'ume',?)"
                " ON CONFLICT(day, region, layer) DO UPDATE SET"
                " bp_number=excluded.bp_number, total_cell=excluded.total_cell,"
                " bp_ratio=excluded.bp_ratio, source=excluded.source,"
                " updated_at=excluded.updated_at",
                (day, region, layer, b, t, (round(b / t, 9) if t else None), now))
    return stats


def _recompute_week(conn, days: List[str], now: str) -> int:
    """重算周汇总：一周内 >= 4/7 天为 BP → 该周为 BP。

    ⚠️ **不用 SQLite 的 `strftime('%Y-W%W')` 分组** —— 实测它与 Python 的 ISO 周
    不等价：`%W` 是「周一起算、可到 W00」的周号，且**年份不回绕**
    （`2025-12-31` 得 `2025-W52`，而 ISO 是 `2026-W01`；`2026-01-01` 得 `2026-W00`）。
    直接用会让跨年那两周落到错误的周键上。这里改成**在 Python 里按 ISO 周分组**
    （唯一真相源是 `bp_caliber.iso_week_key`），再按分组好的日期列表精确 `IN (...)` 查询。

    `bp_days` = 该周里出现 BP 的天数；`total_days` = 该周实际有数据的天数
    （不是恒等于 7 —— 数据缺口必须显式体现，否则会把「只采到 3 天」误判成不达标）。

    ============ 2026-09-29 修正：不覆盖 Excel 已有的周行 ============

    这条规则来自一次真实的数据损坏。此处原先用 `ON CONFLICT DO UPDATE` 无条件覆盖，
    踩到两个独立的坑，`2026-W39` / `2026-W40` / `2026-09` 三行被写成 `bp_cells=0`：

      ① **分母取了本轮同步的天而不是整周**。增量同步只带 1~2 天，`total_days` 变 1、
         `bp_days` 变 0，判定自然为「不是 BP 周」。现已改为从库里取该周的全部天。

      ② **两套 population 的单位根本不同**，无法相加：
           - Excel 明细（`BP Cells List`）**只列 BP 小区**，一天约 400~500 行，
             `bp_cells` 与之同量级（周 462 / 月 448）；
           - RAN_UME 明细**列出全部被评估小区**，一天约 5,865 行，其中 `is_bp=1` 可能为 0。
         把两者混在一起求和/求去重，得到的数会在两套量级之间跳，既不是 Excel 的
         "BP cells"，也不是可靠的任何东西。这不是可以靠调整聚合函数修好的
         —— 是数据模型层面的差异。

    因此本函数的策略是：**只写库里还没有的周（Excel 未覆盖的新周期），
    已存在的行一律不动**。Excel 历史值因此绝对安全；RAN_UME 新采到的周
    仍会进入周视图。Excel 与重算的口径差异继续在日粒度与明细里如实可见。

    Returns:
        实际写入（新建）的周数。
    """
    by_week: Dict[str, List[str]] = {}
    for d in days:
        wk = cal.iso_week_key(d)
        if wk:
            by_week.setdefault(wk, []).append(d)

    n = 0
    for week, _sync_days in sorted(by_week.items()):
        # ① 已有该周（Excel 导入的）→ 保留，绝不覆盖
        exists = conn.execute(
            "SELECT 1 FROM bp_overall_week WHERE week=?", (week,)).fetchone()
        if exists:
            continue

        # ② 该周在库里的**完整**日期集合（分母的正确来源），而不是本次同步的那几天
        lo_hi = cal.period_to_day_range(week)
        if lo_hi is None:
            continue
        wdays = [r["day"] for r in conn.execute(
            "SELECT DISTINCT day FROM bp_cell_daily WHERE day >= ? AND day <= ?"
            " ORDER BY day", lo_hi).fetchall()]
        if not wdays:
            continue
        ph = ",".join("?" for _ in wdays)
        # 逐日判「当天是否出现 BP」：周口径（4/7 days）问的是「这一周里有几天出现 BP」，
        # 不是「几天全网都是 BP」，所以用「当天存在 is_bp=1 的小区」作为该日为 BP 日。
        per_day = conn.execute(
            f"SELECT day, SUM(CASE WHEN is_bp=1 THEN 1 ELSE 0 END) AS b"
            f" FROM bp_cell_daily WHERE day IN ({ph}) GROUP BY day", tuple(wdays)).fetchall()
        if not per_day:
            continue
        total_days = len(per_day)
        bp_days = sum(1 for r in per_day if (r["b"] or 0) > 0)

        # 单位与日表一致（`_recompute_daily` 同款）：total = 该周被评估的小区数，
        # bp = 其中判为 BP 的数量。
        agg = conn.execute(
            f"SELECT SUM(CASE WHEN is_bp=1 THEN 1 ELSE 0 END) AS b, COUNT(*) AS t,"
            f" SUM(COALESCE(dl_gb,0)+COALESCE(ul_gb,0)) AS g"
            f" FROM bp_cell_daily WHERE day IN ({ph})", tuple(wdays)).fetchone()
        bp = agg["b"] or 0
        total = agg["t"] or 0
        g = agg["g"] or 0
        is_bp_week = cal.is_bp_week(bp_days, total_days)
        # 纯 INSERT：上面已确认该周在库里不存在，所以不需要（也不允许）UPSERT
        conn.execute(
            "INSERT INTO bp_overall_week(week, bp_days, total_days, is_bp_week, bp_cells,"
            " total_cells, bp_ratio, traffic_tb, native_period, source, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?, NULL, 'ume', ?)",
            (week, bp_days, total_days,
             (None if is_bp_week is None else int(is_bp_week)),
             bp, total, (round(bp / total, 9) if total else None),
             (round(g / 1024.0, 6) if g else None), now))
        n += 1
    return n


def _recompute_month(conn, months: List[str], now: str) -> int:
    """重算月汇总：一个月内 >= 3/4 个**完整周**为 BP → 该月为 BP。

    分母用 `cal.week_days_in_month()` 给出的完整周数（周一与周日都在月内的 ISO 周），
    与口径里的 `3 / 4 full weeks` 一致；跨月的那两周不计。

    ============ 2026-09-29 修正：不覆盖 Excel 已有的月行 ============

    与 `_recompute_week` 同因同解。此处的 `ON CONFLICT DO UPDATE` 曾把 Excel 的
    `2026-09`（真值 448）覆盖成 15,270 —— 那是把 26 天的**明细行数**累加的结果，
    而 Excel 的月值是「BP 小区个数」（同日 4,480 与周值 462 同量级）。
    两套 population（Excel 明细只列 BP 小区；RAN_UME 明细列出全部被评估小区）
    量级相差数倍，混算得不到任何有意义的数。

    因此：**只写库里还没有的月，已存在的 Excel 行一律保留**。
    """
    n = 0
    for month in months:
        # ① 已有该月（Excel 导入的）→ 保留，绝不覆盖
        exists = conn.execute(
            "SELECT 1 FROM bp_overall_month WHERE month=?", (month,)).fetchone()
        if exists:
            continue

        full_weeks = cal.week_days_in_month(month)
        if not full_weeks:
            continue
        bp_weeks = 0
        for w in full_weeks:
            row = conn.execute(
                "SELECT is_bp_week FROM bp_overall_week WHERE week=?", (w,)).fetchone()
            if row and row["is_bp_week"] == 1:
                bp_weeks += 1

        # 该月在库里的**完整**日期集合（而不是本次同步的那几天）
        lo_hi = cal.period_to_day_range(month)
        if lo_hi is None:
            continue
        mdays = [r["day"] for r in conn.execute(
            "SELECT DISTINCT day FROM bp_cell_daily WHERE day >= ? AND day <= ?"
            " ORDER BY day", lo_hi).fetchall()]
        if not mdays:
            continue
        ph = ",".join("?" for _ in mdays)
        # 单位与日/周表一致：total = 该月被评估小区数，bp = 其中判为 BP 的数量
        agg = conn.execute(
            f"SELECT SUM(CASE WHEN is_bp=1 THEN 1 ELSE 0 END) AS b, COUNT(*) AS t,"
            f" SUM(COALESCE(dl_gb,0)+COALESCE(ul_gb,0)) AS g"
            f" FROM bp_cell_daily WHERE day IN ({ph})", tuple(mdays)).fetchone()
        bp = agg["b"] or 0
        total = agg["t"] or 0
        g = agg["g"] or 0
        # 完整周数不足 4 时 is_bp_month 为 None（不可判定）—— 当月未过完即属此列
        is_bp_month = cal.is_bp_month(bp_weeks, len(full_weeks))
        # 纯 INSERT：上面已确认该月不存在
        conn.execute(
            "INSERT INTO bp_overall_month(month, bp_weeks, total_weeks, is_bp_month,"
            " bp_cells, total_cells, bp_ratio, traffic_tb, native_period, source, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?, NULL, 'ume', ?)",
            (month, bp_weeks, len(full_weeks),
             (None if is_bp_month is None else int(is_bp_month)),
             bp, total, (round(bp / total, 9) if total else None),
             (round(g / 1024.0, 6) if g else None), now))
        n += 1
    return n


# ============================================================
# 判定列补算（fill-only）
# ============================================================

def backfill_period_verdicts(conn, months: Optional[List[str]] = None) -> Dict[str, int]:
    """把周/月汇总行里**空着的判定列**补算出来（只填空，绝不覆盖已有值）。

    ============ 为什么需要这个函数（2026-09-30）============

    `_recompute_week` / `_recompute_month` 是**纯 INSERT** 的（2026-09-29 的数据
    损坏事故后改成这样），只写库里还不存在的周期。于是所有**已存在**的行
    —— Excel 导入的、以及早期同步创建的 —— 判定列永远停在 NULL：
    用户看到「最新一期判定：不可判定」，而库里其实早就有足够数据能判出来
    （如 `2026-W39`：7 天数据齐全、7 天都有 BP → 应判为「是」）。

    关键在于**把两件事分开**：

      - Excel 的**指标真值**（`bp_cells` / `total_cells` / `bp_ratio` /
        `traffic_tb`）—— 一个字都不能动。那场事故就是覆盖了它们；
      - **判定列**（`bp_days` / `total_days` / `is_bp_week` / `bp_weeks` /
        `total_weeks` / `is_bp_month`）—— Excel 从来不提供这些列，它们天生是
        NULL，补算是**填空**而不是覆盖。

    所以本函数只 UPDATE 判定列，且带 `... IS NULL` 条件（已有值一律不动，
    包括 Excel 若将来提供了判定值的情况）。

    判定规则完全走 `bp_caliber`，与 INSERT 路径同源；分母是**库里实际有数据的
    天数/完整周数**，因此「本周只过了 3 天」仍会诚实地得到 NULL（不可判定）。

    Returns:
        `{"weeks": 补算的周数, "months": 补算的月数}`。
    """
    stat = {"weeks": 0, "months": 0}

    # ---------- 周 ----------
    weeks = [r["week"] for r in conn.execute(
        "SELECT week FROM bp_overall_week WHERE is_bp_week IS NULL ORDER BY week"
    ).fetchall()]
    for week in weeks:
        lo_hi = cal.period_to_day_range(week)
        if lo_hi is None:
            continue
        wdays = [r["day"] for r in conn.execute(
            "SELECT DISTINCT day FROM bp_cell_daily WHERE day >= ? AND day <= ?"
            " ORDER BY day", lo_hi).fetchall()]
        if not wdays:
            continue
        ph = ",".join("?" for _ in wdays)
        # 「该日是否为 BP 日」= 当天存在 is_bp=1 的小区（与 INSERT 路径同一判据）
        per_day = conn.execute(
            f"SELECT day, SUM(CASE WHEN is_bp=1 THEN 1 ELSE 0 END) AS b"
            f" FROM bp_cell_daily WHERE day IN ({ph}) GROUP BY day",
            tuple(wdays)).fetchall()
        total_days = len(per_day)
        bp_days = sum(1 for r in per_day if (r["b"] or 0) > 0)
        verdict = cal.is_bp_week(bp_days, total_days)
        # 注意：verdict 为 None 时也要写 —— 把 total_days/bp_days 落库，
        # 界面才能显示「本周仅 3/7 天」这种可解释的进度，而不是一个光秃秃的 NULL。
        conn.execute(
            "UPDATE bp_overall_week SET bp_days=?, total_days=?, is_bp_week=?"
            " WHERE week=? AND is_bp_week IS NULL",
            (bp_days, total_days, (None if verdict is None else int(verdict)), week))
        stat["weeks"] += 1

    # ---------- 月 ----------
    ms = months or [r["month"] for r in conn.execute(
        "SELECT month FROM bp_overall_month WHERE is_bp_month IS NULL ORDER BY month"
    ).fetchall()]
    for month in ms:
        full_weeks = cal.week_days_in_month(month) or []
        if not full_weeks:
            continue
        bp_weeks = 0
        for w in full_weeks:
            row = conn.execute(
                "SELECT is_bp_week FROM bp_overall_week WHERE week=?", (w,)).fetchone()
            if row and row["is_bp_week"] == 1:
                bp_weeks += 1
        verdict = cal.is_bp_month(bp_weeks, len(full_weeks))
        # total_weeks 恒写入：即便 < 4（2026-09 只有 3 个完整周 → 永远判不出），
        # 界面也要能显示「仅 3 个完整周（口径要求 ≥4）」，而不是「不可判定」四个字。
        conn.execute(
            "UPDATE bp_overall_month SET bp_weeks=?, total_weeks=?, is_bp_month=?"
            " WHERE month=? AND is_bp_month IS NULL",
            (bp_weeks, len(full_weeks),
             (None if verdict is None else int(verdict)), month))
        stat["months"] += 1

    return stat


# ============================================================
# 对账
# ============================================================

def _reconcile(conn, days: List[str]) -> Dict[str, Any]:
    """把重算值与 Excel 真值逐日比对，返回差异摘要。

    这是本模块**最重要的输出**：只有对账才能回答「重算值与上游差多少」。
    差异本身不是 bug —— active-user 缺失、Cluster 字典覆盖不全、上游私有口径
    都会造成差异；把差异**显式量化**才能判断可信度。
    """
    diffs: List[Dict[str, Any]] = []
    matched = 0
    for day in days:
        row = conn.execute(
            "SELECT bp_cells, bp_cells_excel FROM bp_overall_daily WHERE day=?",
            (day,)).fetchone()
        if not row or row["bp_cells_excel"] is None:
            continue
        calc, excel = row["bp_cells"], row["bp_cells_excel"]
        if calc == excel:
            matched += 1
        else:
            diffs.append({"day": day, "recomputed": calc, "excel": excel,
                          "delta": (calc - excel) if (calc is not None) else None})
    return {"compared_days": len(days), "matched_days": matched,
            "mismatched_days": len(diffs), "top_diffs": diffs[:20]}


# ============================================================
# 任务入口
# ============================================================

def run_bp_report_sync(window_days: int = DEFAULT_WINDOW_DAYS,
                       day: Optional[str] = None,
                       fetch_remote: bool = True) -> Dict[str, Any]:
    """my_app 定时任务入口：从 RAN_UME 更新 BP 数据。

    Args:
        window_days: 回看天数（默认 2 = 昨天+今天）。
        day:         只处理指定某天 `YYYY-MM-DD`（补数用），此时忽略 window_days。
        fetch_remote: False 时跳过远端取数，只用库内已有指标重算汇总
                      （改口径后重算时用，避免重复拉远端）。

    Returns:
        dict: {success, days, cells, fetch, recompute, reconcile, warnings, errors,
               elapsed_seconds}
    """
    t0 = time.time()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result: Dict[str, Any] = {
        "success": False, "days": [], "cells": 0, "fetch": None,
        "recompute": None, "reconcile": None,
        "warnings": [], "errors": [], "elapsed_seconds": 0,
    }

    if not store.db_exists():
        result["errors"].append(
            "物化库 data/bp_report.sqlite3 不存在，请先跑 Excel 导入 "
            "（backend.services.bp_report_import.run_import）")
        result["elapsed_seconds"] = round(time.time() - t0, 2)
        return result

    if day:
        days = [day]
    else:
        today = datetime.now().date()
        days = [(today - timedelta(days=i)).strftime("%Y-%m-%d")
                for i in range(max(1, window_days))]
        days.reverse()  # 从早到晚，便于日志阅读
    result["days"] = days

    # 口径完备性：Active User 现在走独立的小时粒度通道，届时若取不到会在下面
    # 逐日记录告警。此处只反映**编译期**口径（ACTIVE_USER_ITEM 是否已认领）。
    au = cal.active_user_status()
    if not au["available"]:
        result["warnings"].append(
            "口径未登记：Average DL Active User Number 已由 bp_active_user 取数，"
            "但 bp_caliber.ACTIVE_USER_ITEM 仍为 None，请同步更新口径常量。")

    try:
        with store.write_conn() as conn:
            store.ensure_schema(conn)
            cell_dict = _load_dict(conn)
            if not cell_dict:
                result["errors"].append("bp_cell_dict 为空，请先跑 Excel 导入")
                result["elapsed_seconds"] = round(time.time() - t0, 2)
                return result

            # ---------- 1) 取数 + 逐小区判定 ----------
            known_cells = 0
            unknown_cells = 0
            undecidable = 0
            written = 0
            stale_cleared = 0

            if fetch_remote:
                try:
                    rows = _fetch_days(days)
                    result["fetch"] = {"days": len(days), "rows": len(rows)}
                except Exception as e:
                    logger.exception("[BP] 远端取数失败")
                    result["errors"].append(f"远端取数失败: {e}")
                    rows = []
            else:
                rows = []
                result["fetch"] = {"skipped": True}

            # ---------- 1b) 忙时三值（小时粒度 → AU 最大小时）----------
            # 口径标定（2026-09-30）：umlaut 的三个条件按【忙时】判定 ——
            # 取 AU 最大小时的 PRB/Thr/AU 三值。09-21 实测该口径与 Excel
            # 明细逐小区一致（Jaccard=1.00），日均口径只有 17 个（差 30 倍）。
            # PRB/Thr 也必须用忙时值：日均值口径下 PRB p95=0.616，命中骤减。
            # 取不到就让该日 is_bp = NULL（不可判定），绝不当 0 ——
            # 当 0 会把本可能是 BP 的小区判成非 BP（错算）。
            busy_vals: Dict[str, Dict[str, Dict[str, float]]] = {}
            if fetch_remote and rows:
                busy_vals, busy_errors = au_src.fetch_days_busy(days)
                result["active_user"] = {
                    "days_ok": sorted(busy_vals.keys()),
                    "days_failed": busy_errors,
                    "cells": {d: len(v) for d, v in busy_vals.items()},
                    "caliber": "busy_hour(peak AU hour)",
                }
                for d, why in busy_errors.items():
                    result["warnings"].append(
                        f"{d} 的忙时三值取数失败，该日走完其余条件的小区记为"
                        f"「不可判定」：{why}")
            else:
                result["active_user"] = {"skipped": True,
                                         "reason": "未取远端数据"}

            payload: List[tuple] = []
            for r in rows:
                # 列序由 _fetch_days 的 cols_wanted 决定：
                # 0=Begin Time 1=ManagedElement ID 2=Cell Name
                # 3=PRB DL 4=Thr DL 5=DL GB 6=UL GB
                d = cal.day_str(r[0])
                if not d:
                    continue
                cell = str(r[2]).replace("\xa0", " ").strip() if r[2] is not None else ""
                if not cell:
                    continue
                cluster, layer = cell_dict.get(cell, (cal.UNKNOWN, cal.UNKNOWN))
                if cluster == cal.UNKNOWN:
                    unknown_cells += 1
                else:
                    known_cells += 1
                # 该日该小区的忙时三值（AU 最大小时）；缺失 → None → 不可判定。
                # PRB/Thr 同样用忙时值替代日均值（口径标定结论，见上方注释）。
                bv = (busy_vals.get(d) or {}).get(cell)
                au_val = bv["au"] if bv else None
                prb_val = bv["prb"] if bv else r[3]
                thr_val = bv["thr"] if bv else r[4]
                is_bp = cal.is_bp_day(prb_val, thr_val, au_val)
                if is_bp is None:
                    undecidable += 1
                payload.append((
                    d, cell, str(r[1]).strip() if r[1] is not None else None,
                    cluster, layer,
                    (None if is_bp is None else int(is_bp)),
                    prb_val, thr_val, au_val, r[5], r[6],
                    cluster,  # Excel Regional sheet 的原生分区语义与 cluster 同源
                    "ume", now))

                if len(payload) >= 20000:
                    written += store.upsert_many(
                        conn, "bp_cell_daily",
                        ("day", "cell_name", "me_id", "cluster", "layer", "is_bp",
                         "prb_dl", "thr_dl", "active_user", "dl_gb", "ul_gb",
                         "region", "source", "updated_at"),
                        payload, ("day", "cell_name"))
                    payload.clear()
            if payload:
                written += store.upsert_many(
                    conn, "bp_cell_daily",
                    ("day", "cell_name", "me_id", "cluster", "layer", "is_bp",
                     "prb_dl", "thr_dl", "active_user", "dl_gb", "ul_gb",
                     "region", "source", "updated_at"),
                    payload, ("day", "cell_name"))

            # 清掉这些日期里**只由 Excel 导入、RAN_UME 侧已不存在**的残留行。
            # 不清的后果实测过：2026-09-26 的 BP Cells List 只有 53 行（该 sheet 的
            # 最后一天不完整），而重算侧有 5792 行，两批行叠在同一张表里、按 cluster
            # 一聚合就让「重算值」看起来恰好等于 Excel 值 —— 一个**假吻合**，
            # 比数值不对更危险。Excel 的汇总真值保留在 bp_overall_daily.bp_cells_excel，
            # 小区清单保留在 bp_cell_dict，都不依赖这些残留明细行。
            cur = conn.cursor()
            for d in days:
                cur.execute(
                    "DELETE FROM bp_cell_daily WHERE day=? AND source='excel' "
                    "AND cell_name NOT IN (SELECT cell_name FROM bp_cell_daily "
                    "WHERE day=? AND source='ume')", (d, d))
                stale_cleared += cur.rowcount or 0
            if stale_cleared:
                logger.info("[BP] 清理 Excel 残留明细行 %s 行", stale_cleared)
            result["stale_cleared"] = stale_cleared

            result["cells"] = written
            result["coverage"] = {
                "in_dict": known_cells, "not_in_dict": unknown_cells,
                "undecidable": undecidable,
                "dict_size": len(cell_dict),
            }
            if unknown_cells:
                result["warnings"].append(
                    f"{unknown_cells} 行小区不在 Cluster 字典内（RAN_UME 侧新增或"
                    f"从未成为过 BP 的小区），已归为 {cal.UNKNOWN}。")

            # ---------- 2) 重算汇总 ----------
            # 日汇总：RAN_UME 是**当日数据的权威来源**，按天 UPSERT（幂等）。
            # 周/月汇总：**只新建 Excel 尚未覆盖的周期，已存在的行一律不覆盖** ——
            #   原因见 `_recompute_week` / `_recompute_month` 的详细说明：
            #   Excel 明细只列 BP 小区（~450/天），RAN_UME 明细列出全部被评估小区
            #   （~5,865/天），两套 population 混算得到的数没有意义，曾把
            #   Excel 的 `2026-09`（真值 448）覆盖成 15,270。
            #   这是 2026-09-29 实测损坏后确立的策略：**宁可少写，不可改错历史**。
            daily = _recompute_daily(conn, days, now)
            wk = _recompute_week(conn, days, now)
            mo = _recompute_month(conn, sorted({cal.month_key(d) for d in days
                                                if cal.month_key(d)}), now)
            # 3b) 把已存在周/月行上**空着的判定列**补算出来（只填空、不覆盖指标真值）。
            #     没有这一步，Excel 导入的周/月行永远没有判定 —— 页面的
            #     「最新一期判定」就只剩「不可判定」可显示。详见该函数 docstring。
            vf = backfill_period_verdicts(conn)
            result["recompute"] = {"daily": daily, "weeks": wk, "months": mo,
                                   "verdict_backfill": vf}

            # ---------- 3) 对账 ----------
            result["reconcile"] = _reconcile(conn, days)

            # 口径不完整时，重算值与 Excel **必然**不一致（缺一个条件）。
            # 把这一点写成对账结论的一部分，避免使用者把差异当成实现 bug。
            if not au["available"]:
                result["reconcile"]["caliber_note"] = (
                    "重算仅覆盖 PRB 与吞吐两个条件，缺失的 Average DL Active User Number "
                    "是判定中最关键的一项，因此重算 BP 数**必然低于** Excel 值；"
                    "该差异属口径缺口，不是实现缺陷。")

            # ---------- 4) 元信息 ----------
            store.set_meta(conn, "last_sync_at", now, now)
            store.set_meta(conn, "last_sync_days", days, now)
            store.set_meta(conn, "last_sync_warnings", result["warnings"], now)
            store.set_meta(conn, "last_sync_errors", result["errors"], now)
            store.set_meta(conn, "last_reconcile", result["reconcile"], now)
            store.set_meta(conn, "coverage", result["coverage"], now)
            store.set_meta(conn, "caliber", cal.caliber_snapshot(), now)
            store.set_meta(conn, "active_user_status", au, now)

            # 全局脏值计数（导入时统计，供 /meta 展示）
            cur = conn.cursor()
            dirty_cluster = cur.execute(
                "SELECT COUNT(*) FROM bp_cell_daily WHERE cluster=?", (cal.UNKNOWN,)
            ).fetchone()[0]
            dirty_layer = cur.execute(
                "SELECT COUNT(*) FROM bp_cell_daily WHERE layer=?", (cal.UNKNOWN,)
            ).fetchone()[0]
            store.set_meta(conn, "dirty_counts",
                           {"rows_unknown_cluster": dirty_cluster,
                            "rows_unknown_layer": dirty_layer}, now)

        result["success"] = not result["errors"] and written > 0
    except Exception as e:
        logger.exception("[BP] 同步失败")
        result["errors"].append(f"同步异常: {e}")

    result["elapsed_seconds"] = round(time.time() - t0, 2)
    logger.info("[BP] 同步完成 days=%s cells=%s %.2fs success=%s errors=%s",
                result["days"], result["cells"], result["elapsed_seconds"],
                result["success"], result["errors"])
    return result


if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="BP Report RAN_UME 更新")
    ap.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    ap.add_argument("--day", default=None, help="只处理某天 YYYY-MM-DD")
    ap.add_argument("--no-fetch", action="store_true", help="不取远端，只用库内指标重算")
    args = ap.parse_args()
    print(json.dumps(run_bp_report_sync(window_days=args.window_days, day=args.day,
                                        fetch_remote=not args.no_fetch),
                     ensure_ascii=False, indent=2, default=str))
