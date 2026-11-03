# -*- coding: utf-8 -*-
"""县维度可用率 —— **聚合层**（纯计算，不碰 PG）。

=========================== 聚合口径（勿改）===========================

    站点期值 = 该站在本期内有值日期的**算术平均**
    县制式期值 = 该县所有**有值站点**的站点期值的**算术平均**（站点等权）
    ⚠️ 与 `avail_ms` / `avail_flm` 的 SUM(分子)/SUM(分母) **不是同一口径**：
       那两页的分母是重建任务算出来的「有值站点数」，可加；
       本页的分母是 UME 直接给的站点级比率，没有可加的分子/分母，只能等权平均。
       两页数字**不可互相印证**，页面已注明。
    未归属：PG 里匹配不上 eflow_site 的站点（实测约占 9%）单列「未归属站点」行，
       **不计入任何一个县**，并在页面显式提示 —— 否则读者会以为「漏了数据」。

=========================== 模块边界 ===========================

本模块只吃 `avail_county_data.load_month_data()` 的返回结构、只出**纯数据**，
不做 SQL、不做缓存、不感知 FastAPI。

拆出这个文件的原因（工作区 AGENTS.md 第三节原则 2：新增文件 ≤500 行）：
口径是本看板最敏感的部分，必须有独立、可单独读懂的位置；
取数（IO + 缓存）与聚合（口径）混在一起会让「口径在哪一段代码里」变得难找。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def avg(vals: Sequence[float]) -> Optional[float]:
    """算术平均；空序列返回 None（**不返回 0** —— 0 会被误读成「可用率为 0%」）。"""
    return sum(vals) / len(vals) if vals else None


def site_period_value(site_daily: Dict[str, float],
                       days: Sequence[str]) -> Optional[float]:
    """站点期值 = 本期内有值日期的算术平均。"""
    vals = [site_daily[d] for d in days if d in site_daily]
    return avg(vals)


def county_cells(data: Dict[str, Any], tech: str, days: Sequence[str],
                 threshold: float) -> Dict[str, Dict[str, Any]]:
    """算出一个制式下**每个县**的期值聚合。

    返回 {county_key: {"availability","sites","site_days","below_sites","min","max"}}
    """
    by_site: Dict[str, Dict[str, float]] = data["by_tech"].get(tech) or {}
    county_sites: Dict[str, List[str]] = data.get("county_sites") or {}

    out: Dict[str, Dict[str, Any]] = {}
    for county, keys in county_sites.items():
        vals: List[float] = []
        site_days = 0
        below = 0
        for key in keys:
            sd = by_site.get(key) or {}
            if not sd:
                continue
            vals_in = [sd[d] for d in days if d in sd]
            if not vals_in:
                continue
            v = sum(vals_in) / len(vals_in)
            vals.append(v)
            site_days += len(vals_in)
            if v < threshold:
                below += 1
        out[county] = {
            "availability": avg(vals),
            "sites": len(vals),
            "site_days": site_days,
            "below_sites": below,
            "min": min(vals) if vals else None,
            "max": max(vals) if vals else None,
        }
    return out


def unmatched_cell(data: Dict[str, Any], tech: str, days: Sequence[str],
                   threshold: float) -> Optional[Dict[str, Any]]:
    """未归属站点的聚合（PG 里匹配不上 eflow_site 的那些）。"""
    unmatched: Dict[str, Dict[str, float]] = (data["unmatched"] or {}).get(tech) or {}
    if not unmatched:
        return None
    vals: List[float] = []
    site_days = 0
    below = 0
    for sd in unmatched.values():
        v = site_period_value(sd, days)
        if v is None:
            continue
        vals.append(v)
        site_days += len([d for d in days if d in sd])
        if v < threshold:
            below += 1
    if not vals:
        return None
    return {
        "availability": avg(vals),
        "sites": len(vals),
        "site_days": site_days,
        "below_sites": below,
        "min": min(vals),
        "max": max(vals),
    }


def cell_payload(cur: Optional[Dict[str, Any]],
                 prv: Optional[Dict[str, Any]],
                 threshold: float) -> Dict[str, Any]:
    """把「本期聚合」与「上一期聚合」合成矩阵单元格的载荷。

    环比差用**百分点**（*100）表示，正数 = 变好。
    任一侧无值时 delta_pp 为 None —— 不用 0 冒充「没变化」。
    """
    cur = cur or {}
    prv = prv or {}
    av = cur.get("availability")
    prev_av = prv.get("availability")
    return {
        "availability": av,
        "sites": cur.get("sites", 0),
        "site_days": cur.get("site_days", 0),
        "below_sites": cur.get("below_sites", 0),
        "min": cur.get("min"),
        "max": cur.get("max"),
        "prev_availability": prev_av,
        "delta_pp": (None if (av is None or prev_av is None)
                     else round((av - prev_av) * 100, 4)),
        "below": None if av is None else (av < threshold),
    }


def county_region(county: str, data: Dict[str, Any]) -> str:
    """县 -> 所属大区（取该县站点里出现最多的 region）。"""
    return (data.get("county_regions") or {}).get(county, "")


def covered_days(data: Dict[str, Any], techs: Sequence[str],
                 days: Sequence[str]) -> List[str]:
    """给定日期窗口内**有数据**的日历天数（各制式取并集）。"""
    return sorted({d for tech in techs
                   for sd in (data["by_tech"].get(tech) or {}).values()
                   for d in sd if d in days})


def summary_by_tech(cur: Dict[str, Dict[str, Dict[str, Any]]],
                     techs: Sequence[str],
                     county_order: Sequence[str],
                     threshold: float) -> Dict[str, Any]:
    """全网汇总（把各县的**县值**再取一次算术平均）。

    ⚠️ 平均的是「县值」而不是「站点值」——于是**每个县一人一票**，
       县的大小（站点多少）不影响权重：1 个站的县和 100 个站的县同等重要。
       这不是站点加权的全网真实可用率，但它与主表逐行读到的数字**能对上**
       （读者在表里看到的那几个数，平均出来就是这里这个数），
       比"更准但和哪一行都对不上"更好解释。
       另：未归属行不在 county_order 里，因此**不计入**全网汇总。
    """
    out: Dict[str, Any] = {}
    for tech in techs:
        all_vals: List[float] = []
        below_counties = 0
        for county in county_order:
            c = cur.get(tech, {}).get(county) or {}
            av = c.get("availability")
            if av is None:
                continue
            all_vals.append(av)
            if av < threshold:
                below_counties += 1
        out[tech] = {
            "availability": avg(all_vals),
            "counties_with_data": len(all_vals),
            "counties_below": below_counties,
            "min": min(all_vals) if all_vals else None,
            "sites": sum((cur.get(tech, {}).get(c) or {}).get("sites", 0)
                         for c in county_order),
        }
    return out


__all__ = [
    "avg", "cell_payload", "covered_days", "county_cells", "county_region",
    "site_period_value", "summary_by_tech", "unmatched_cell",
]
