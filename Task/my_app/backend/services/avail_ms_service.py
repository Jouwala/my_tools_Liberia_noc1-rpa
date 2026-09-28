# -*- coding: utf-8 -*-
"""可用率多维矩阵（avail_ms）数据服务。

=========================== 数据源 ===========================

本机派生库 `data/avail_recon.sqlite3` -> 表 `availability_daily`
（列：Begin_Time, End_Time, Tech, FME_Region, Cell_Group,
  Numerator, Denominator, Cell_Availability, WK, Month）

它不是任何业务系统的原生表，由定时任务 `avail_recon_sync`（每天 06:10，
见 `backend/services/avail_recon_sync.py` 顶部说明）从远端
`2G/3G/4G_Main_Kpi_Site_Daily` × `Master_Site_Database_.Region` **近似重建**，
近 300 天 / 8000 行量级。本页每次请求直接只读查它（整表读入 + 300s 缓存），
不做任何二次落库。

=========================== 口径（勿改） ===========================

    可用率 = SUM(Numerator) / SUM(Denominator)

`Numerator` / `Denominator` 是重建时按 (日, 制式, 区域, 调度组) 聚合出的
「站点可用率算术平均」与「有值站点数」，因此先乘后加等价于**站点级加权**。
**不得**改成 AVG(Cell_Availability) —— 那会把大区与小区的权重拉平
（`avail_recon_sync.py` 顶部记录了 v1 因口径错误返工的经过）。

三个维度与需求图片一一对应（都是同一张 (制式 × 站点类型) 表的切法）：

    区域    ：ALL / Montserrado / North East / South West / UNMATCHED
    制式    ：2G（Regular/Cooli/ERA）、3G（Regular/Cooli）、4G（Regular/ERA）
    站点类型：Regular（2G/3G/4G）、Cooli（2G/3G）、ERA（2G/4G）

=========================== 三条必须保留的口径事实 ===========================

1. **区域 ALL ≠ 三区域相加。** 远端站点名匹配不上 `Master_Site_Database` 的站点落在
   `FME_Region IS NULL`，本模块把它单列为 `UNMATCHED` 行，但它**计入 ALL**
   （实测约占总分母 2.3%）。矩阵接口因此在有未匹配数据时返回
   `region_all_includes_unmatched` 警告码，页面必须显示说明。

2. **`4G FDD NERA` 是脏值**（仅 2025-12-24 ~ 2026-01-27 有 140 行，来自 LTE_NERA
   调度组）。它在制式维度计入 4G 总量，在站点类型维度单列为 `Other` ——
   两者因此在该时间窗内对不上，返回 `other_site_type_present` 警告码。

3. **可用率侧的站点类型来自 KPI 调度组，TT 侧的站点类型来自站点主数据。**
   前者见 `avail_recon_sync.site_type()`，后者见本模块 `norm_site_category()`
   （口径必须与 `backend/routers/gis.py:_norm_site_category` 及
   `backend/services/eflow_rules/eflow_rules_matcher.py` 的 `_SITE_TYPE_MAP`
   保持一致）。两套分类的站点集合有少量差异，属已知近似口径 —— 所以 TT 下钻
   返回 `tt_type_source`，且**不按制式过滤 TT**（TT 表没有制式字段），
   只把各制式断站数列出来供人工判断。

=========================== 对外接口 ===========================

    get_options()                可选周期列表（日/周/月）+ 数据截止日
    build_matrix(period, value)  三张矩阵（区域 / 制式 / 站点类型）+ 环比
    build_trends(period, value)  三个维度各自的多序列趋势（页面曲线图），同口径
    get_drilldown(level, ...)    level=period：时间明细 + 构成分解 + 历史趋势
                                 level=tt    ：相关 TT 工单明细

文件末尾另有一组**公开门面**（`fetch_all` / `cell` / `warnings_for` …），
供 `avail_flm_service` 复用同一套口径，避免第二个页面重写聚合 —— 详见那里的注释。
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from collections import namedtuple
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("avail_ms")

# my_app 自持派生库（与 dashboard_service.LOCAL_SQLITE_FILES['__local_avail_recon__'] 同一文件）
AVAIL_DB = Path(__file__).resolve().parents[2] / "data" / "avail_recon.sqlite3"

# 未达标阈值（比率），与 site_availability_service.DEFAULT_THRESHOLD 同值同义
DEFAULT_THRESHOLD = 0.9965

PERIODS = ("day", "week", "month")
# 周期 -> 时间列（白名单，杜绝拼接注入）
PERIOD_COL = {"day": "Begin_Time", "week": "WK", "month": "Month"}

TECHS = ("2G", "3G", "4G")
# 站点类型：前三档是需求口径；Other 承载 NERA 之类未映射的调度组（见 docstring 第 2 条）
SITE_TYPES = ("Regular", "Cooli", "ERA", "Other")

REGION_ALL = "ALL"
REGION_UNMATCHED = "UNMATCHED"  # FME_Region 为空 = 远端站点主数据没匹配上的桶

# 区域展示顺序：先固定的三区域，其余（含新出现的区域）按字母序追加，不被静默吞掉
PREFERRED_REGIONS = ("Montserrado", "North East", "South West")

# Cell_Group（重建时按调度组生成）-> (制式, 站点类型)
# 新增调度组时这里必须补映射；没补的组会被计入制式总量但从站点类型列里缺席，
# 因此 _unknown_cell_groups() 会把它暴露成警告，而不是让数字悄悄对不上。
CELL_GROUP_MAP: Dict[str, Tuple[str, str]] = {
    "2G Regular": ("2G", "Regular"),
    "2G Cooli": ("2G", "Cooli"),
    "2G ERA": ("2G", "ERA"),
    "3G Regular": ("3G", "Regular"),
    "3G Cooli": ("3G", "Cooli"),
    "4G FDD Regular": ("4G", "Regular"),
    "4G FDD ERA": ("4G", "ERA"),
    "4G FDD NERA": ("4G", "Other"),
}

# TT 下钻的两道上限，语义不同、都要显式暴露给前端（绝不静默截断）：
#   TT_FETCH_LIMIT  读库安全网：单月 TT 实测 ~5000 行，2 万足够覆盖一个月
#   TT_RETURN_LIMIT 返回给弹窗的条数上限（表格分页展示），超出时 meta.truncated=True
TT_FETCH_LIMIT = 20000
TT_RETURN_LIMIT = 2000

# 派生库行（整表读入后按维度切片；列名与 availability_daily 对齐，另加两个预计算周期列）
Row = namedtuple("Row", "day tech region cell_group numerator denominator wk month")


# ============ 统一缓存（复用项目 cache 服务，与 site_availability_service 同款）============
try:
    from backend.services.cache import get_cache

    _cache = get_cache()
except Exception:  # pragma: no cover - 缓存服务不可用时退化为无缓存
    _cache = None

_CACHE_TTL = 300


def _cache_get(key: str):
    if _cache is None:
        return None
    try:
        return _cache.get(key)
    except Exception:
        return None


def _cache_set(key: str, value, ttl: int = _CACHE_TTL):
    if _cache is None:
        return value
    try:
        _cache.set(key, value, ttl)
    except Exception:
        pass
    return value


class AvailMsError(Exception):
    """派生库缺失等不可恢复错误（路由层转成可展示的失败结构）。"""


# ----------------------------------------------------------------------
# 只读访问
# ----------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    """只读打开派生库（与 dashboard_service._query_local 同一写法：file:...?mode=ro）。

    这是 my_app **自持派生库**，不是主库 —— 主库的 PG/SQLite 双模（MY_APP_DB_MODE）
    与它无关，因此不存在「裸 sqlite3.connect 在 pg 模式下必然失败」的问题。
    """
    if not AVAIL_DB.is_file():
        raise AvailMsError(f"可用率派生库不存在: {AVAIL_DB}（先跑定时任务 avail_recon_sync 重建）")
    con = sqlite3.connect(f"file:{AVAIL_DB}?mode=ro", uri=True, timeout=30)
    con.execute("PRAGMA query_only=ON")
    return con


def _fetch_all() -> List[Row]:
    """整表读入（8000 行量级，带 300s 缓存）。

    整表读而不是每个维度各写一条 GROUP BY：表本身只有几千行，一次读入后在 Python
    里切片，能让三张矩阵共用同一份数据（口径不可能分叉），也省掉十几条聚合 SQL。
    周/月两列**直接取表里重建任务算好的 WK / Month**，绝不自己再推一遍 ——
    周口径是重建脚本自定义的（周一起算、周号为当年第几周），重算必然与库里分叉。
    """
    ck = "avail_ms:all"
    cached = _cache_get(ck)
    if cached is not None:
        return cached
    t0 = time.time()
    con = _connect()
    try:
        raw = con.execute(
            "SELECT Begin_Time, Tech, COALESCE(FME_Region, ''), Cell_Group, "
            "COALESCE(Numerator, 0), COALESCE(Denominator, 0), "
            "COALESCE(WK, ''), COALESCE(Month, '') "
            "FROM availability_daily WHERE Begin_Time IS NOT NULL"
        ).fetchall()
    finally:
        con.close()
    rows = [Row(str(r[0] or "")[:10], str(r[1] or ""), str(r[2] or ""), str(r[3] or ""),
                int(r[4] or 0), int(r[5] or 0), str(r[6] or ""), str(r[7] or ""))
            for r in raw]
    logger.info("[avail-ms] 读入 %d 行，耗时 %.0fms", len(rows), (time.time() - t0) * 1000)
    return _cache_set(ck, rows)


def _period_of(row: Row, period: str) -> str:
    """行 -> 所属周期值（直接用表列）。Month 缺失时回落到日期前 7 位。"""
    if period == "day":
        return row.day
    if period == "month":
        return row.month or row.day[:7]
    return row.wk


def _distinct(period: str) -> List[str]:
    """某周期粒度下有数据的全部取值，升序。"""
    vals = {_period_of(r, period) for r in _fetch_all()}
    return sorted(v for v in vals if v)


def _latest_value(period: str) -> str:
    vals = _distinct(period)
    return vals[-1] if vals else ""


def _prev_value(period: str, value: str) -> str:
    """上一期：按库里**实际有数据**的取值取前一个，数据有缺口时不会串期。"""
    vals = _distinct(period)
    if value in vals:
        i = vals.index(value)
        return vals[i - 1] if i > 0 else ""
    prev = [v for v in vals if v < value]
    return prev[-1] if prev else ""


# ----------------------------------------------------------------------
# 维度切片
# ----------------------------------------------------------------------
def _groups_for(tech: Optional[str], site_type: Optional[str]) -> Optional[List[str]]:
    """(制式, 站点类型) 对应的 Cell_Group 列表。

    空列表 = 「不限制」；None = 「该组合在口径上不存在」（如 4G+Cooli、3G+ERA），
    调用方据此把单元格渲染成 `—` 而不是 0（取不到数据不得显示成 0）。
    """
    if not tech and not site_type:
        return []
    if tech and site_type:
        return [cg for cg, (t, s) in CELL_GROUP_MAP.items() if t == tech and s == site_type] or None
    if tech:
        return [cg for cg, (t, _s) in CELL_GROUP_MAP.items() if t == tech]
    return [cg for cg, (_t, s) in CELL_GROUP_MAP.items() if s == site_type]


def _region_ok(reg: str, region: str) -> bool:
    """区域匹配：ALL=不限制；UNMATCHED=只要空区域；其余=精确匹配。"""
    if not region or region == REGION_ALL:
        return True
    if region == REGION_UNMATCHED:
        return not reg
    return reg == region


def _filter_cell(rows: Sequence[Row], region: str, tech: Optional[str],
                 site_type: Optional[str]) -> Optional[List[Row]]:
    """按 (区域, 制式, 站点类型) 过滤；组合不存在返回 None（区别于「过滤后为空」）。"""
    allowed = _groups_for(tech, site_type)
    if allowed is None:
        return None
    allowed_set = set(allowed) if allowed else None
    region = region or REGION_ALL
    out = []
    for r in rows:
        if not _region_ok(r.region, region):
            continue
        if tech and r.tech != tech:
            continue
        if allowed_set is not None and r.cell_group not in allowed_set:
            continue
        out.append(r)
    return out


def _sum_rows(rows: Sequence[Row]) -> Tuple[int, int, Optional[float]]:
    num = sum(r.numerator for r in rows)
    den = sum(r.denominator for r in rows)
    return num, den, (num / den if den else None)


def _cell(rows: Sequence[Row], prev_rows: Sequence[Row], region: str,
          tech: Optional[str], site_type: Optional[str],
          threshold: float) -> Dict[str, Any]:
    """一个单元格：当期值 + 环比上一期（delta_pp 为百分点差）。

    组合不存在或本期无数据 -> availability=None（前端显示 `—`）；
    `below` 为 None 与 False 是两回事：前者=取不到数据，后者=达标。
    """
    cur_rows = _filter_cell(rows, region, tech, site_type)
    if cur_rows is None:
        return {"availability": None, "numerator": 0, "denominator": 0,
                "below": None, "prev_availability": None, "delta_pp": None}
    num, den, av = _sum_rows(cur_rows)
    prev_av: Optional[float] = None
    prev_cell = _filter_cell(prev_rows, region, tech, site_type) if prev_rows else None
    if prev_cell:
        prev_av = _sum_rows(prev_cell)[2]
    delta = round((av - prev_av) * 100, 4) if (av is not None and prev_av is not None) else None
    return {
        "availability": av,
        "numerator": num,
        "denominator": den,
        "below": None if av is None else bool(av < threshold),
        "prev_availability": prev_av,
        "delta_pp": delta,
    }


def _regions_in(rows: Sequence[Row]) -> List[str]:
    """本期真实出现的区域（不含空值）：固定顺序在前，其余字母序。"""
    found = {r.region for r in rows if r.region}
    ordered = [x for x in PREFERRED_REGIONS if x in found]
    return ordered + sorted(found - set(PREFERRED_REGIONS))


def _has_unmatched(rows: Sequence[Row]) -> bool:
    return any(not r.region for r in rows)


def _unmatched_share(rows: Sequence[Row]) -> Optional[float]:
    """未匹配主数据的站点占本期分母的比例（页面的口径说明要用到）。"""
    total = sum(r.denominator for r in rows)
    if not total:
        return None
    miss = sum(r.denominator for r in rows if not r.region)
    return round(miss / total, 6)


def _unknown_cell_groups(rows: Sequence[Row]) -> List[str]:
    """出现过的、未登记进 CELL_GROUP_MAP 的调度组（新脏值自动暴露）。"""
    return sorted({r.cell_group for r in rows if r.cell_group and r.cell_group not in CELL_GROUP_MAP})


def _warnings_for(rows: Sequence[Row]) -> List[str]:
    """本期需要提示给用户的口径说明（码值，界面文案走 i18n，不在这里写中文）。"""
    w: List[str] = []
    if _has_unmatched(rows):
        w.append("region_all_includes_unmatched")
    if any(CELL_GROUP_MAP.get(r.cell_group, ("", ""))[1] == "Other" for r in rows):
        w.append("other_site_type_present")
    if _unknown_cell_groups(rows):
        w.append("unknown_cell_group")
    if not rows:
        w.append("no_data_for_period")
    return w


# ----------------------------------------------------------------------
# 对外：选项
# ----------------------------------------------------------------------
def get_options() -> Dict[str, Any]:
    """三档周期的可选值 + 数据截止日（页面顶部「数据截至」取它）。"""
    try:
        rows = _fetch_all()
    except AvailMsError as e:
        return {"data_through": "", "latest": {}, "days": [], "weeks": [], "months": [],
                "threshold": DEFAULT_THRESHOLD, "warnings": ["derived_db_missing"],
                "error": str(e)}
    return {
        "data_through": max((r.day for r in rows), default=""),
        "latest": {"day": _latest_value("day"), "week": _latest_value("week"),
                   "month": _latest_value("month")},
        # 倒序：下拉框默认把最近的放最前
        "days": list(reversed(_distinct("day"))),
        "weeks": list(reversed(_distinct("week"))),
        "months": list(reversed(_distinct("month"))),
        "threshold": DEFAULT_THRESHOLD,
        "warnings": [],
    }


# ----------------------------------------------------------------------
# 对外：三张矩阵
# ----------------------------------------------------------------------
def build_matrix(period: str = "day", value: str = "",
                 threshold: float = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """按周期返回三张矩阵（区域 / 制式 / 站点类型）。

    制式与站点类型两张表的区域口径是 **ALL（含未匹配）**，与区域表首行一致；
    需求图片这两张表没有区域维度，故不按区域拆。
    """
    t0 = time.time()
    if period not in PERIODS:
        period = "day"
    value = value or _latest_value(period)
    prev_value = _prev_value(period, value)
    all_rows = _fetch_all()
    rows = [r for r in all_rows if _period_of(r, period) == value] if value else []
    prev_rows = [r for r in all_rows if prev_value and _period_of(r, period) == prev_value]

    groups: List[Dict[str, Any]] = []

    # ---- 区域 × 制式（ALL 行含未匹配站点，故末行单列 UNMATCHED 供对账）----
    region_rows = [REGION_ALL] + _regions_in(rows)
    if _has_unmatched(rows):
        region_rows.append(REGION_UNMATCHED)
    groups.append({
        "dim": "region",
        "columns": list(TECHS),
        "rows": [{"key": rk,
                  "cells": {tk: _cell(rows, prev_rows, rk, tk, None, threshold) for tk in TECHS}}
                 for rk in region_rows],
    })

    # ---- 制式 × 站点类型 ----
    groups.append({
        "dim": "tech",
        "columns": list(SITE_TYPES),
        "rows": [{"key": tk,
                  "cells": {st: _cell(rows, prev_rows, REGION_ALL, tk, st, threshold)
                            for st in SITE_TYPES}}
                 for tk in TECHS],
    })

    # ---- 站点类型 × 制式 ----
    groups.append({
        "dim": "site_type",
        "columns": list(TECHS),
        "rows": [{"key": st,
                  "cells": {tk: _cell(rows, prev_rows, REGION_ALL, tk, st, threshold)
                            for tk in TECHS}}
                 for st in SITE_TYPES],
    })

    return {
        "meta": {
            "period": period,
            "value": value,
            "prev_value": prev_value,
            "data_through": max((r.day for r in all_rows), default=""),
            "threshold": threshold,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
            "warnings": _warnings_for(rows),
            "unknown_cell_groups": _unknown_cell_groups(rows),
        },
        "summary": {
            "by_tech": {tk: _cell(rows, prev_rows, REGION_ALL, tk, None, threshold)["availability"]
                        for tk in TECHS},
            "unmatched_share": _unmatched_share(rows),
            "regions": _regions_in(rows),
            "rows_in_period": len(rows),
        },
        "groups": groups,
    }


# ----------------------------------------------------------------------
# 对外：趋势（三个维度的曲线图）
# ----------------------------------------------------------------------
# 各档位默认回溯多少期。数据源本身只有 287 天，month 档 12 期即全量。
TREND_POINTS: Dict[str, int] = {"day": 30, "week": 12, "month": 12}
TREND_POINTS_MAX = 120          # 上限：再多既看不清也没意义（前端要传大值需先想清楚）
TREND_DIMS = ("region", "tech", "site_type")


def _trend_order(dim: str, present: set) -> List[str]:
    """曲线顺序与矩阵行顺序保持一致（固定维度在前，其余字母序），避免"图与表不一样顺"。"""
    if dim == "region":
        head = [REGION_ALL, *PREFERRED_REGIONS]
    elif dim == "tech":
        head = list(TECHS)
    else:
        head = list(SITE_TYPES)
    return [k for k in head if k in present] + sorted(present - set(head))


def build_trends(period: str = "day", value: str = "", points: int = 0,
                 threshold: float = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """三个维度各自的多序列趋势（曲线图用）。

    每个点 = 该维度取值在那一期的**加权可用率** `SUM(Numerator)/SUM(Denominator)`，
    与矩阵单元格、下钻明细完全同口径 —— 曲线与表格对不上就是 bug，不是"展示差异"。

    一次请求返回三个维度（region / tech / site_type），因为它们共用同一段窗口、
    同一遍扫表：分成三个端点只会让前端多两次往返、后端多扫两遍。
    区域维度会**原样返回 UNMATCHED 序列**（是否画进图里由前端决定，见 AvailMs.tsx 的说明）。
    """
    if period not in PERIODS:
        period = "day"
    vals = _distinct(period)
    meta: Dict[str, Any] = {
        "period": period, "value": value or (vals[-1] if vals else ""),
        "start": "", "end": "", "points": 0, "threshold": threshold,
        "generated_at": datetime.now().isoformat(timespec="seconds"), "warnings": [],
    }
    if not vals:
        meta["warnings"] = ["no_data_for_period"]
        return {"meta": meta, "categories": [], "dims": {d: [] for d in TREND_DIMS}}

    value = value or vals[-1]
    if value in vals:
        end = vals.index(value) + 1
    else:
        # 请求的周期值库里没有（例如刚跨期）：退到"不晚于它的最后一期"，别抛错
        le = [v for v in vals if v <= value]
        end = len(le) or len(vals)

    n = points if points and points > 0 else TREND_POINTS[period]
    n = max(1, min(int(n), TREND_POINTS_MAX))
    window = vals[max(0, end - n):end]
    wanted = set(window)

    # 单遍扫表同时给三个维度分桶
    acc: Dict[Tuple[str, str, str], List[int]] = {}
    for r in _fetch_all():
        p = _period_of(r, period)
        if p not in wanted:
            continue
        site_type = CELL_GROUP_MAP.get(r.cell_group, ("", ""))[1]
        for dim, key in (("region", REGION_ALL),
                         ("region", r.region or REGION_UNMATCHED),
                         ("tech", r.tech or ""),
                         ("site_type", site_type)):
            if not key:
                continue    # 未登记调度组在站点类型维度上不归属（与矩阵列的缺失一致）
            a = acc.setdefault((dim, key, p), [0, 0])
            a[0] += r.numerator
            a[1] += r.denominator

    dims: Dict[str, List[Dict[str, Any]]] = {}
    for dim in TREND_DIMS:
        present = {k for (d, k, _p) in acc if d == dim}
        series = []
        for key in _trend_order(dim, present):
            values: List[Optional[float]] = []
            nums: List[int] = []
            dens: List[int] = []
            tot_n = tot_d = below = 0
            for p in window:
                a = acc.get((dim, key, p))
                if not a or not a[1]:
                    values.append(None)
                    nums.append(0)
                    dens.append(0)
                    continue
                v = round(a[0] / a[1], 6)
                values.append(v)
                nums.append(a[0])
                dens.append(a[1])
                tot_n += a[0]
                tot_d += a[1]
                if v < threshold:
                    below += 1
            if all(v is None for v in values):
                continue        # 窗口内整条线都没数据 -> 不返回（如 Other 只在 2025-12 有值）
            series.append({"key": key, "values": values, "numerators": nums,
                           "denominators": dens, "below_periods": below,
                           "overall": round(tot_n / tot_d, 6) if tot_d else None})
        dims[dim] = series

    win_rows = [r for r in _fetch_all() if _period_of(r, period) in wanted]
    meta.update({"value": value, "start": window[0], "end": window[-1],
                 "points": len(window), "warnings": _warnings_for(win_rows)})
    return {"meta": meta, "categories": window, "dims": dims}


# ----------------------------------------------------------------------
# 对外：下钻
# ----------------------------------------------------------------------
def get_drilldown(level: str = "period", period: str = "day", value: str = "",
                  region: str = REGION_ALL, tech: str = "", site_type: str = "",
                  threshold: float = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """单元格下钻。

    level=period：该单元格在本期内的**按日明细** + 按 Cell_Group 的**构成分解**
                 （回答「为什么 4G 总量比 Regular+ERA 多」）+ 最近 30 期历史趋势。
    level=tt    ：该单元格相关 TT 工单明细（时间窗取本期在派生库里的实际日期范围）。
    """
    if period not in PERIODS:
        period = "day"
    value = value or _latest_value(period)
    region = region or REGION_ALL
    tech = tech or ""
    site_type = site_type or ""
    if level == "tt":
        return _tt_drilldown(period, value, region, tech, site_type)

    all_rows = _fetch_all()
    rows = [r for r in all_rows if _period_of(r, period) == value] if value else []
    cell_rows = _filter_cell(rows, region, tech or None, site_type or None)
    meta_base = {"level": "period", "period": period, "value": value, "region": region,
                 "tech": tech, "site_type": site_type, "threshold": threshold,
                 "generated_at": datetime.now().isoformat(timespec="seconds")}
    if cell_rows is None:
        meta_base["warnings"] = ["combination_not_applicable"]
        return {"meta": meta_base, "series": [], "breakdown": [], "history": [],
                "truncated": False, "cell": None}

    # 按日明细：比当前周期更细一档（day 档就是当天各调度组的合成）
    by_day: Dict[str, List[int]] = {}
    for r in cell_rows:
        acc = by_day.setdefault(r.day, [0, 0])
        acc[0] += r.numerator
        acc[1] += r.denominator
    series = [_series_item(k, v, threshold) for k, v in sorted(by_day.items())]

    # 构成分解：本期各 Cell_Group
    by_cg: Dict[str, List[int]] = {}
    for r in cell_rows:
        acc = by_cg.setdefault(r.cell_group, [0, 0])
        acc[0] += r.numerator
        acc[1] += r.denominator
    breakdown = []
    for cg, (n, d) in sorted(by_cg.items()):
        t, s = CELL_GROUP_MAP.get(cg, ("", ""))
        item = _series_item(cg, (n, d), threshold)
        item.update({"cell_group": cg, "tech": t, "site_type": s})
        breakdown.append(item)

    # 历史：最近 30 期同口径值（弹窗里画趋势）
    hist: Dict[str, List[int]] = {}
    for r in all_rows:
        p = _period_of(r, period)
        if not p:
            continue
        if not _region_ok(r.region, region):
            continue
        if tech and r.tech != tech:
            continue
        if site_type and CELL_GROUP_MAP.get(r.cell_group, ("", ""))[1] != site_type:
            continue
        acc = hist.setdefault(p, [0, 0])
        acc[0] += r.numerator
        acc[1] += r.denominator
    history = [_series_item(k, v, threshold) for k, v in sorted(hist.items())][-30:]

    warnings = _warnings_for(rows)
    if not series:
        warnings.append("no_detail_for_cell")
    meta_base["warnings"] = warnings
    # 弹窗里的当期值与矩阵单元格同口径（含环比上一期），避免两处各算一套。
    # ⚠️ `_prev_value` 必须**先算出来存进变量**：它内部要全表扫一遍取 distinct，
    # 若直接写进下面的列表推导，Python 会按元素重新求值（实测 8132 行 → 8132 次全表扫、
    # 6600 万次函数调用、单请求 8~13 秒）；提出来之后是 1 次。2026-09-28 性能剖析发现并修复。
    prev = _prev_value(period, value)
    prev_rows = [r for r in all_rows if _period_of(r, period) == prev] if prev else []
    return {
        "meta": meta_base,
        "series": series,
        "breakdown": breakdown,
        "history": history,
        "truncated": False,
        "cell": _cell(rows, prev_rows, region, tech or None, site_type or None, threshold),
    }


def _series_item(key: str, nd: Sequence[int], threshold: float) -> Dict[str, Any]:
    n, d = int(nd[0]), int(nd[1])
    av = (n / d) if d else None
    return {"key": key, "numerator": n, "denominator": d, "availability": av,
            "below": None if av is None else bool(av < threshold)}


def _period_bounds(period: str, value: str) -> Tuple[str, str]:
    """本期在派生库里的实际日期范围。

    刻意从表里取 MIN/MAX Begin_Time，而不是按周号/月做日期推算 —— 周标签是重建
    脚本自定义的（周一起算、周号为当年第几周），用 ISO 周反推会错位。
    """
    if period == "day":
        return value, value
    col = PERIOD_COL[period]
    con = _connect()
    try:
        r = con.execute(f"SELECT MIN(Begin_Time), MAX(Begin_Time) FROM availability_daily "
                        f"WHERE {col} = ?", (value,)).fetchone()
    finally:
        con.close()
    if not r or not r[0]:
        return value, value
    return str(r[0])[:10], str(r[1])[:10]


# ----------------------------------------------------------------------
# TT 下钻
# ----------------------------------------------------------------------
def norm_site_category(value: Any) -> str:
    """站点等级归一化 -> Regular / Cooli / ERA / Other。

    ⚠️ 口径必须与 `backend/routers/gis.py:_norm_site_category` 和
    `backend/services/eflow_rules/eflow_rules_matcher.py` 的 `_norm_site_type` 一致
    （去括号内制式后缀 + 去空格下划线 + 大写）。库里 `site_caregory` 存在
    `REGULAR（NORMAL)` / `REGULAR(COOL.I）` 这类全角半角混用脏值，
    不归一化会把同一档劈成两半。改一处必须改另两处。
    """
    if value is None:
        return "Other"
    s = str(value).strip()
    if not s:
        return "Other"
    # 去掉括号内容后连括号一起去掉，兼容全角/半角左右括号混用（同 gis.py 的写法）
    s = re.sub(r"[（(][^（()）]*[)）]", "()", s)
    s = s.replace("(", "").replace(")", "").replace("（", "").replace("）", "")
    key = s.upper().replace(" ", "").replace("_", "")
    if key in ("REGULAR", "NORMAL"):
        return "Regular"
    if key == "COOL":
        return "Cooli"
    if key == "ERA":
        return "ERA"
    return "Other"


def _load_site_meta() -> Dict[str, Dict[str, str]]:
    """站点主数据 -> {site_id: {site_name, region, site_type}}（带缓存）。

    为什么不复用 `site_availability_service.load_master_sites()`：那里没有 SELECT
    `site_caregory`（它的站点类型取的是 eflow_tt 的 site_type 列），而本页要按
    「Regular/Cooli/ERA」过滤只能从 `site_caregory` 归一化 —— 扩它的 SELECT 会改动
    另一个页面共用的缓存载荷，故在本模块自持一份最小查询。
    """
    ck = "avail_ms:site_meta"
    cached = _cache_get(ck)
    if cached is not None:
        return cached
    from backend.database import get_raw_connection

    out: Dict[str, Dict[str, str]] = {}
    try:
        with get_raw_connection(timeout=30) as conn:
            for r in conn.execute(
                    "SELECT site_id, site_name, region, site_caregory FROM master_site_db"
            ).fetchall():
                sid = str(r[0] or "").strip()
                if not sid:
                    continue
                out[sid] = {"site_name": str(r[1] or ""), "region": str(r[2] or ""),
                            "site_type": norm_site_category(r[3])}
    except Exception as e:  # noqa: BLE001 - 站点表读不到不该让整页 500
        logger.warning("[avail-ms] 读取 master_site_db 失败: %s", e)
    return _cache_set(ck, out)


TT_COLUMNS = [
    "tt_no", "title", "status", "ticket_severity", "site_id", "site_name",
    "site_outage", "current_handler", "root_cause",
    "alarm_occur_time", "alarm_clear_time", "created_time", "fault_duration_time",
    "col_2g_down_site_count", "col_3g_down_site_count", "col_4g_down_site_count",
]

_DUR_RE = re.compile(r"(?:(\d+)d)?\s*(?:(\d+)h)?\s*(?:(\d+)m)?")


def _mttr_minutes(occur: Any, clear: Any, duration: Any) -> Optional[float]:
    """MTTR（分钟）。优先解析 `fault_duration_time`（形如 `0d5h26m`），
    缺失时用 `alarm_clear_time - alarm_occur_time` 兜底；都取不到返回 None。

    刻意不用 SQL 的 julianday()（PG 没有该函数）；本文件按跨方言口径处理。
    """
    txt = str(duration or "").strip()
    if txt:
        m = _DUR_RE.fullmatch(txt)
        if m and any(m.groups()):
            d_, h_, mi_ = (int(g) if g else 0 for g in m.groups())
            return round(d_ * 1440 + h_ * 60 + mi_, 1)
    a, b = str(occur or "").strip(), str(clear or "").strip()
    if not a or not b:
        return None
    try:
        fmt = "%Y-%m-%d %H:%M:%S"
        delta = datetime.strptime(b[:19], fmt) - datetime.strptime(a[:19], fmt)
        return round(delta.total_seconds() / 60, 1)
    except ValueError:
        return None


def _tt_drilldown(period: str, value: str, region: str, tech: str,
                  site_type: str) -> Dict[str, Any]:
    """本期相关 TT 工单明细。

    时间字段：优先 `alarm_occur_time`（故障发生时刻，与可用率同轴），为空回落
    `created_time`（与 site_availability_service 的工单归属口径一致）。
    区域与站点类型都取**站点主数据**（见 meta.tt_type_source）。
    """
    warnings: List[str] = []
    start, end = _period_bounds(period, value)
    meta: Dict[str, Any] = {
        "level": "tt", "period": period, "value": value, "region": region, "tech": tech,
        "site_type": site_type, "start": start, "end": end, "total": 0, "truncated": False,
        "tt_type_source": "master_site_db",
        "generated_at": datetime.now().isoformat(timespec="seconds"), "warnings": [],
    }
    if region == REGION_UNMATCHED:
        # 可用率侧这个桶的含义是「远端站点名匹配失败」，派生库里没有站点名单，
        # 无法反推是哪些站点 —— 显式说明，不返回一份"看起来对"的错数据。
        meta["warnings"] = ["unmatched_region_no_tt"]
        return {"meta": meta, "rows": []}

    from backend.database import get_raw_connection

    site_meta = _load_site_meta()
    cols = ", ".join(TT_COLUMNS)
    sql = (f"SELECT {cols} FROM eflow_tt "
           f"WHERE COALESCE(NULLIF(alarm_occur_time, ''), created_time) >= ? "
           f"AND COALESCE(NULLIF(alarm_occur_time, ''), created_time) <= ? "
           f"ORDER BY COALESCE(NULLIF(alarm_occur_time, ''), created_time) DESC "
           f"LIMIT {TT_FETCH_LIMIT}")
    try:
        with get_raw_connection(timeout=60) as conn:
            fetched = conn.execute(sql, (f"{start} 00:00:00", f"{end} 23:59:59")).fetchall()
    except Exception as e:  # noqa: BLE001
        logger.warning("[avail-ms] 读取 eflow_tt 失败 %s~%s: %s", start, end, e)
        meta["warnings"] = ["tt_read_failed"]
        return {"meta": meta, "rows": []}

    rows: List[Dict[str, Any]] = []
    unassigned = 0
    for r in fetched:
        row = {c: r[i] for i, c in enumerate(TT_COLUMNS)}
        info = site_meta.get(str(row.get("site_id") or "").strip())
        if info is None:
            # 不在站点主数据里的 TT：无法确定区域与站点类型，单列计数不静默丢弃
            unassigned += 1
            continue
        if region and region != REGION_ALL and info["region"] != region:
            continue
        if site_type and info["site_type"] != site_type:
            continue
        row["region"] = info["region"]
        row["site_type_norm"] = info["site_type"]
        row["mttr_minutes"] = _mttr_minutes(row.get("alarm_occur_time"),
                                           row.get("alarm_clear_time"),
                                           row.get("fault_duration_time"))
        rows.append(row)

    if tech:
        # TT 表没有制式字段（只有各制式断站数），因此**不按制式过滤** ——
        # 返回说明码 + 每行的 2G/3G/4G 断站数，由用户判断与所选制式的相关性。
        warnings.append("tt_no_tech_filter")
    if len(fetched) >= TT_FETCH_LIMIT:
        warnings.append("tt_fetch_capped")
    if unassigned:
        warnings.append("tt_site_unassigned")
    if not rows:
        warnings.append("no_tt_in_period")

    matched_total = len(rows)
    truncated = matched_total > TT_RETURN_LIMIT
    if truncated:
        warnings.append("tt_truncated")
    meta.update({"total": matched_total, "returned": min(matched_total, TT_RETURN_LIMIT),
                 "truncated": truncated, "unassigned": unassigned, "warnings": warnings})
    # rows 本来就按时间倒序，截断保留最近的若干条
    return {"meta": meta, "rows": rows[:TT_RETURN_LIMIT]}


# ======================================================================
# 供其他页面复用的公开门面（当前唯一使用者：avail_flm_service）
# ----------------------------------------------------------------------
# 这两页读同一个派生库、用同一套单元格口径（SUM(分子)/SUM(分母)），差别只在"行与列怎么摆"。
# 直接 import 上面的下划线函数也能跑，但那会让口径的实现者与调用者之间没有契约 ——
# 所以这里显式转发一层：**要复用就调这里，不要在别的 service 里再写一遍聚合**。
# ======================================================================
def fetch_all() -> List[Row]:
    """整表读入（带 300s 缓存）。"""
    return _fetch_all()


def period_of(row: Row, period: str) -> str:
    """一行属于哪一期（day=Begin_Time / week=WK / month=Month）。"""
    return _period_of(row, period)


def cell(rows: Sequence[Row], prev_rows: Sequence[Row], region: str,
         tech: Optional[str], site_type: Optional[str],
         threshold: float = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """一个单元格（当期值 + 环比）。组合不存在返回 availability=None，不返回 0。"""
    return _cell(rows, prev_rows, region, tech, site_type, threshold)


def warnings_for(rows: Sequence[Row]) -> List[str]:
    return _warnings_for(rows)


def has_unmatched(rows: Sequence[Row]) -> bool:
    return _has_unmatched(rows)


def unmatched_share(rows: Sequence[Row]) -> Optional[float]:
    return _unmatched_share(rows)


def unknown_cell_groups(rows: Sequence[Row]) -> List[str]:
    return _unknown_cell_groups(rows)


def periods(period: str) -> List[str]:
    return _distinct(period)


def latest_value(period: str) -> str:
    return _latest_value(period)


def previous_value(period: str, value: str) -> str:
    return _prev_value(period, value)


def site_types_in(rows: Sequence[Row]) -> List[str]:
    """本期出现过的站点类型（按 SITE_TYPES 的固定顺序）。"""
    found = {CELL_GROUP_MAP.get(r.cell_group, ("", ""))[1] for r in rows}
    return [st for st in SITE_TYPES if st in found]
