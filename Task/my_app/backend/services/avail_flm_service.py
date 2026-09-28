# -*- coding: utf-8 -*-
"""FLM 可用率（avail_flm）—— 「区域」为行、制式 / 站点类型为列的可用率 + 影响可用率的 TT 列表。

=========================== 与 avail_ms 的关系 ===========================

读**同一个派生库** `data/avail_recon.sqlite3`（任务 `avail_recon_sync` 每天 06:10 重建），
用**同一套单元格口径** `SUM(Numerator)/SUM(Denominator)` —— 实现全部复用
`avail_ms_service`（见其文件末尾的公开门面），本模块**不重写任何聚合**。
两页的差别只在"行与列怎么摆"以及本页多一张 TT 列表：

    avail_ms（?page=avail_ms）           本页（?page=avail_flm）
    -----------------------------       -----------------------------
    行=ALL/3 区域/UNMATCHED × 列=制式    行=3 区域（+未匹配） × 列=制式
    行=制式 × 列=站点类型                行=3 区域（+未匹配） × 列=站点类型
    行=站点类型 × 列=制式                （无）
    TT 只在单元格下钻里                   另有一张页面级 TT 列表

=========================== 两条已确认的口径 ===========================
（2026-09-28 与用户逐条确认，改动前请看这两条的来由，别再"照需求表改回去"）

1. **站点类型不做范围限制。** 需求表写「North East 只有 Regular/Cool.i」「South West 只有
   Regular/ERA」，但两个数据源都不支持这个"不存在"：站点主数据 `master_site_db` 里
   NE 有 123 个 ERA 站点（SW 有 22 个 Cool.i），派生库里 NE 的 ERA 分母 6.5 万、
   SW 的 Cool.i 分母 1.2 万，与 Regular 同一量级。所以那是**业务适用范围**而非缺数据，
   硬留空会让用户在 NE 行看不到 ERA —— 而同一批数据在 avail_ms 里是显示 98% 的。
   结论：三个区域都显示三个站点类型，单元格为空只代表"本期确实没数据"。

2. **TT 列表列本期全部工单，不做"是否影响业务"判定。** `eflow_tt` 有
   `whether_impacted_service` 与 `site_outage` 两列，本期数据上两者完全一致
   （Yes 3502 / 空 78 / No 62，全量 3642）—— 用拿一列当"影响可用率"的判据，
   会让一个含糊的定义看起来精确。故口径与 avail_ms 的 TT 页签保持一致（见
   `avail_ms_service._tt_drilldown`）：按站点主数据归属区域与站点类型、不按制式过滤
   （TT 表没有制式字段，返回 `tt_no_tech_filter` 说明码）。

=========================== 对外接口 ===========================

    get_options()                       三档周期可选值 + 数据截止（转发 avail_ms）
    build_matrix(period, value)         区域×制式 + 区域×站点类型 两张表
    build_trends(period, value)         区域趋势 + 站点类型趋势（本页两张图）
    get_tt(period, value, region, ...)  本期全部 TT 工单（页面级列表 / 下钻页签共用）
    get_drilldown(level, ...)           单元格下钻（转发 avail_ms，两页同口径）
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.services import avail_ms_service as ms

logger = logging.getLogger("avail_flm")

# 三个 FLM 区域。取 avail_ms 的固定顺序（Montserrado → North East → South West），
# 这两个常量必须同源：需求表里的区域就是这三个，顺序也一致。
FLM_REGIONS: Tuple[str, ...] = ms.PREFERRED_REGIONS

# 区域×站点类型表的列：只画需求表列的三种（不含 avail_ms 的 `Other`）。
# `4G FDD NERA` 仍计入制式 4G 的总量（它在派生库里就是 4G 的一部分），
# 只是在本页不单列成列 —— 该时间窗内 4G 行 ≠ 三列相加，由 other_site_type_present 说明码提示。
FLM_SITE_TYPES: Tuple[str, ...] = ("Regular", "Cooli", "ERA")

# 行标签：三个区域 + 未匹配主数据桶（末行，便于对账；它不是区域，故不参与"区域"语义）
ROW_UNMATCHED = ms.REGION_UNMATCHED


def get_options() -> Dict[str, Any]:
    return ms.get_options()


def _rows_of(period: str, value: str) -> Tuple[List[ms.Row], List[ms.Row], str, List[ms.Row]]:
    """返回（本期行, 上一期行, 生效的周期值, 全表行）。上一期用于算环比。"""
    all_rows = ms.fetch_all()
    value = value or ms.latest_value(period)
    prev = ms.previous_value(period, value)
    rows = [r for r in all_rows if ms.period_of(r, period) == value] if value else []
    prev_rows = [r for r in all_rows if prev and ms.period_of(r, period) == prev]
    return rows, prev_rows, value, all_rows


def _row_keys(rows: Sequence[ms.Row]) -> List[str]:
    """行顺序：三个 FLM 区域恒在（本期没数据就整行 `—`，表形不随数据跳变），
    末行补未匹配主数据桶（有才补）。"""
    keys: List[str] = list(FLM_REGIONS)
    if ms.has_unmatched(rows):
        keys.append(ROW_UNMATCHED)
    return keys


def build_matrix(period: str = "day", value: str = "",
                 threshold: float = ms.DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """两张表：区域×制式、区域×站点类型。列固定，行=三个 FLM 区域（+未匹配）。"""
    t0 = time.time()
    if period not in ms.PERIODS:
        period = "day"
    rows, prev_rows, value, _all = _rows_of(period, value)

    groups = [
        {
            "dim": "region_tech",
            "columns": list(ms.TECHS),
            "rows": [{"key": rk,
                      "cells": {tk: ms.cell(rows, prev_rows, rk, tk, None, threshold)
                                for tk in ms.TECHS}}
                     for rk in _row_keys(rows)],
        },
        {
            "dim": "region_site_type",
            "columns": list(FLM_SITE_TYPES),
            "rows": [{"key": rk,
                      "cells": {st: ms.cell(rows, prev_rows, rk, None, st, threshold)
                                for st in FLM_SITE_TYPES}}
                     for rk in _row_keys(rows)],
        },
    ]

    # 区域 KPI 卡：该区域**全部制式合计**的可用率（不带制式/站点类型切片）
    by_region = {rk: ms.cell(rows, prev_rows, rk, None, None, threshold)
                 for rk in FLM_REGIONS}
    # 全部三个区域合计（口径上等于 avail_ms 的 ALL 减掉未匹配桶）——
    # 页面上不做成卡片，但导出与对账要用，故一并给出
    total = ms.cell(rows, prev_rows, ms.REGION_ALL, None, None, threshold)

    # 本页没有 ALL 行，avail_ms 那条「ALL ≠ 三区域相加」的说明码在这里不适用；
    # 换成"未匹配站点单列末行"的说明，避免把上一页的文案搬过来造成误读。
    warnings = [w for w in ms.warnings_for(rows) if w != "region_all_includes_unmatched"]
    if ms.has_unmatched(rows):
        warnings.insert(0, "flm_unmatched_last_row")

    return {
        "meta": {
            "period": period,
            "value": value,
            "prev_value": ms.previous_value(period, value),
            "data_through": max((r.day for r in _all), default=""),
            "threshold": threshold,
            "regions": list(FLM_REGIONS),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
            "warnings": warnings,
            "unknown_cell_groups": ms.unknown_cell_groups(rows),
        },
        "summary": {
            "by_region": {rk: by_region[rk] for rk in FLM_REGIONS},
            "by_tech": {tk: ms.cell(rows, prev_rows, ms.REGION_ALL, tk, None, threshold)
                        for tk in ms.TECHS},
            "all_regions": total,
            "unmatched_share": ms.unmatched_share(rows),
            "rows_in_period": len(rows),
        },
        "groups": groups,
    }


def build_trends(period: str = "day", value: str = "", points: int = 0,
                 threshold: float = ms.DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """本页的两张曲线图：区域趋势（3 条线）+ 站点类型趋势（3 条线）。

    复用 `avail_ms_service.build_trends`（一次扫表同时算三个维度），这里做**收窄**：
      * 区域维度只保留三个 FLM 区域 —— 本页没有 ALL 行，图里也不画 ALL；
        未匹配桶（量级 78%）照 avail_ms 的做法不入图。
      * 站点类型维度只保留 Regular/Cooli/ERA（不含 Other，与本页的列一致）。
    也就是说收窄规则与建表用的行/列**同源同序**，图和表不会各说各话。
    """
    data = ms.build_trends(period=period, value=value, points=points, threshold=threshold)
    dims = data.get("dims", {})
    meta = dict(data.get("meta", {}))
    # 与矩阵同理：本页没有 ALL 行也不画 ALL 线，「ALL 含未匹配」这条说明码在这里会误读，剔掉。
    # `other_site_type_present` 保留 —— 它正好解释了站点类型图里为什么没有 Other 那条线。
    meta["warnings"] = [w for w in meta.get("warnings", [])
                        if w != "region_all_includes_unmatched"]
    return {
        "meta": meta,
        "categories": data.get("categories", []),
        "dims": {
            "region": [s for s in dims.get("region", []) if s.get("key") in FLM_REGIONS],
            "site_type": [s for s in dims.get("site_type", [])
                          if s.get("key") in FLM_SITE_TYPES],
        },
    }


def get_tt(period: str = "day", value: str = "", region: str = "",
           site_type: str = "") -> Dict[str, Any]:
    """本期全部 TT 工单（页面级列表与下钻页签共用同一口径）。

    直接转发 `avail_ms_service.get_drilldown(level='tt')` —— 那里已经做了
    「按站点主数据归属区域/站点类型 + 未归属计数 + 截断显式暴露 + TT 无制式字段的说明码」。
    本函数只负责把空区域归一成 ALL，别让它变成"空字符串=什么都不返回"这种坑。

    返回的 `meta` 字段与 avail_ms 完全一致（`total` / `returned` / `truncated` /
    `unassigned` / `start` / `end` / `warnings`），前端两页可复用同一套渲染与文案。
    """
    if period not in ms.PERIODS:
        period = "day"
    return ms.get_drilldown(
        level="tt", period=period, value=value or "",
        region=(region or "").strip() or ms.REGION_ALL,
        tech="", site_type=(site_type or "").strip(), threshold=ms.DEFAULT_THRESHOLD,
    )


def get_drilldown(level: str = "period", period: str = "day", value: str = "",
                  region: str = ms.REGION_ALL, tech: str = "", site_type: str = "",
                  threshold: float = ms.DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """单元格下钻：转发 avail_ms，两页同一副明细口径（不要在这里另写一套过滤）。"""
    return ms.get_drilldown(level=("tt" if level == "tt" else "period"), period=period,
                            value=value, region=region or ms.REGION_ALL, tech=tech,
                            site_type=site_type, threshold=threshold)


def normalize_region(region: str) -> str:
    """区域入参归一：空=ALL；三个 FLM 区域与 UNMATCHED 之外的区域名不允许（本页不展示）。"""
    r = (region or "").strip()
    if not r or r == ms.REGION_ALL:
        return ms.REGION_ALL
    if r in FLM_REGIONS or r == ROW_UNMATCHED:
        return r
    return ms.REGION_ALL


def normalize_site_type(site_type: str) -> str:
    s = (site_type or "").strip()
    return s if s in FLM_SITE_TYPES else ""


def normalize_tech(tech: str) -> str:
    t = (tech or "").strip()
    return t if t in ms.TECHS else ""


__all__ = [
    "FLM_REGIONS", "FLM_SITE_TYPES", "ROW_UNMATCHED",
    "get_options", "build_matrix", "build_trends", "get_tt", "get_drilldown",
    "normalize_region", "normalize_site_type", "normalize_tech",
]
