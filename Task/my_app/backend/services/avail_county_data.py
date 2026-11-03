# -*- coding: utf-8 -*-
"""县维度可用率 —— **取数层**（PG 只读 + 缓存）。

=========================== 本模块的职责 ===========================

只做三件事：
    1. 从 PG 读**站点级日可用率**与站点主数据（只读，不建表不改数）；
    2. 把站点按 `eflow_site.province_county` 归到县；
    3. 提供周期边界（自然周）与「该月最后一个有数据的日子」。

**不含任何聚合统计** —— 聚合在 `avail_county_aggregate.py`，
对外的接口（options / matrix / trend / drilldown）在 `avail_county_service.py`。
这样切分的理由：取数是 IO 密集且要缓存，聚合是纯计算且口径敏感，
两者混在一个文件里会让「口径在哪一段代码里」变得难找。

=========================== 数据源与口径 ===========================

站点主数据
    主库 `eflow_site`（eFlow 站点主数据，830 行 / 站点名去重后 820 个）
    取用字段：site_id, site_name, province_county（**县**）, region,
              network_type, site_type
    ⚠️ `region` 是大区（Montserrado / North East / South West …），
       `province_county` 才是**县** —— 本页按县聚合，用的是后者。

可用率（站点级日粒度，三种制式各一份）
    本地 PG（ms_sla schema，只读）：
      2G : Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_SITE
           站点名 "SITE Name"    指标 "TCH in service rate(%)"
      3G : Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE
           站点名 "NodeB Name"   指标 "Cell Validity Rate(%)"
      4G : Hourly_KPI_RPA_SITE_MS_SLA_FDD1day_SITE
           站点名 "eNodeB Name"  指标 "[FDD]Cell Availability[SDR_ITBBU]"
    站点关联口径：**站点名**（规范化 = 去首尾空白 + 连续空白折叠 + 转小写）。
    为什么不用 site_id：实测 PG 侧 site_id 与 eflow_site.site_id **对不上**
    （4G 重合率仅 4.7%、3G 15.6%、2G 0%），只有名字能对上（命中约 90~91%）。
    同名站点在 eflow_site 里有 10 组（Palala / Totota / Suakoko …），
    **按站点名去重**（实测同名的多行县归属完全一致，无歧义），
    否则一个站点的可用率会被重复计入。

    ⚠️ 这三张表是 **UME MS SLA 站点级日表**，本模块只读，不建表不改数。
    ⚠️ 数据覆盖有限：实测最早 2026-06-18，且**当月可能只有个别天**
       （当前月实测仅 11-01 一天）。页面显示「数据截至」与覆盖天数，
       让「本月只有 1 天」这件事在界面上看得见，而不是让人以为页面坏了。

周口径 = 自然周（周一起算），**直接复用**
    `site_availability_service.month_weeks`（周号 W1..W5 / 跨月裁剪），
    不另起一套，避免同仓库里出现两种周定义。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names
# 复用既有口径：周划分、月份边界、默认阈值 —— 不另起一套
from backend.services.site_availability_service import (
    DEFAULT_THRESHOLD,
    month_days,
    month_weeks,
)

logger = logging.getLogger("avail_county")

# 制式 -> (PG 表名, 站点名列, 可用率列)
TECH_SPEC: Dict[str, Tuple[str, str, str]] = {
    "2G": ("Hourly_KPI_RPA_SITE_MS_SLA_GSM1day_SITE", "SITE Name",
           "TCH in service rate(%)"),
    "3G": ("Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_SITE", "NodeB Name",
           "Cell Validity Rate(%)"),
    "4G": ("Hourly_KPI_RPA_SITE_MS_SLA_FDD1day_SITE", "eNodeB Name",
           "[FDD]Cell Availability[SDR_ITBBU]"),
}
TECHS = ("2G", "3G", "4G")

PERIODS = ("day", "week")

# 未归属站点的虚拟行 key（PG 侧匹配不上 eflow_site 的站点）
UNMATCHED_KEY = "__UNMATCHED__"

# 取数时向**前**多取的天数：环比需要上一期（周档最多跨 7 天）
LOOKBACK_DAYS = 8


# ============ 统一缓存（复用项目 cache 服务，与 avail_ms 同款）============

try:
    from backend.services.cache import get_cache

    _cache = get_cache()
except Exception:  # pragma: no cover - 缓存服务不可用时退化为无缓存
    _cache = None

CACHE_TTL = 300


def cache_get(key: str):
    if _cache is None:
        return None
    try:
        return _cache.get(key)
    except Exception:
        return None


def cache_set(key: str, value, ttl: int = CACHE_TTL):
    if _cache is None:
        return value
    try:
        _cache.set(key, value, ttl)
    except Exception:
        pass
    return value


# ============ 周期工具 ============

def _week_key(d: str) -> str:
    """'YYYY-MM-DD' -> ISO 周 key 'YYYY-Www'（与 month_weeks 的 key 同格式）。"""
    dt = datetime.strptime(d, "%Y-%m-%d").date()
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def latest_day_with_data(month: str) -> str:
    """该月里**最后一个有数据的日子**（不是日历最后一天）。

    为什么必须有这个：UME 的站点级日表同步有滞后，当前月实测可能只有 1~2 天有数据
    （2026-11 实测仅 11-01 一天）。若默认取「日历最后一天」，
    页面打开就是一片空白 —— 用户会以为页面坏了，而不是「今天还没同步」。
    """
    days = month_days(month)
    ck = f"avail_county:lastday:{month}"
    cached = cache_get(ck)
    if cached is not None:
        return cached
    latest = ""
    try:
        with get_raw_connection(timeout=60) as conn:
            if not missing_tables(conn):
                for tbl, _, _ in TECH_SPEC.values():
                    r = conn.execute(
                        'SELECT MAX(substr("Begin Time", 1, 10)) FROM "{tbl}" '
                        'WHERE "Begin Time" >= ? AND "Begin Time" <= ?'.format(tbl=tbl),
                        (f"{days[0]} 00:00:00", f"{days[-1]} 23:59:59"),
                    ).fetchone()
                    if r and r[0] and str(r[0])[:10] > latest:
                        latest = str(r[0])[:10]
    except Exception as e:
        logger.warning("[avail-county] 读取最新有数据日期失败: %s", e)
    if not latest:
        latest = days[-1]
    return cache_set(ck, latest)


def period_bounds(month: str, period: str, value: str,
                  latest_day: str = "") -> Tuple[str, str, List[str], str]:
    """把 (month, period, value) 解析成 (start_day, end_day, days, resolved_value)。

    resolved_value 是**规范化的周期值**：日 = 'YYYY-MM-DD'，周 = 'YYYY-Www'。
    value 为空时取该月的**最后一期**：
      - 日档 = 该月最后一个**有数据**的日子（latest_day）；
      - 周档 = 包含该日的自然周。
    """
    days = month_days(month)
    if not latest_day:
        latest_day = latest_day_with_data(month)

    if period == "day":
        if value and value in days:
            return value, value, [value], value
        if latest_day in days:
            return latest_day, latest_day, [latest_day], latest_day
        last = days[-1]
        return last, last, [last], last

    # week
    weeks = month_weeks(month)
    if value:
        for w in weeks:
            if w["key"] == value:
                return w["days"][0], w["days"][-1], list(w["days"]), w["key"]
    # 默认：包含 latest_day 的那一周（若不在本月内则取本月最后一周）
    for w in weeks:
        if latest_day in w["days"]:
            return w["days"][0], w["days"][-1], list(w["days"]), w["key"]
    w = weeks[-1]
    return w["days"][0], w["days"][-1], list(w["days"]), w["key"]


def prev_period_days(period: str, start_day: str, end_day: str) -> List[str]:
    """上一期的日期列表（环比用）。日档=前一天；周档=紧邻的前 7 个自然日。"""
    sd = datetime.strptime(start_day, "%Y-%m-%d").date()
    if period == "day":
        p = sd - timedelta(days=1)
        return [p.isoformat()]
    # 周档：上一周（周一至周日），整周不裁剪 —— 保证环比是同长度窗口
    monday = sd - timedelta(days=7)
    return [(monday + timedelta(days=i)).isoformat() for i in range(7)]


def load_start_day(start_day: str) -> str:
    """取数窗口起点：本期起点再向前多取 LOOKBACK_DAYS 天（覆盖环比基期）。"""
    return (datetime.strptime(start_day, "%Y-%m-%d").date()
            - timedelta(days=LOOKBACK_DAYS)).isoformat()


# ============ 取数 ============

def _norm_sql(col: str) -> str:
    """站点名规范化 SQL 表达式（与 Python 侧 norm_name 同义）。"""
    return "regexp_replace(lower(trim(%s)), '\\s+', ' ', 'g')" % col


# 站点维度子查询：按**规范化站点名**去重，取该名字对应的站点主数据。
# 同名的多个行县归属一致（实测 10 组全部一致），故 MIN() 是安全的。
_DIM_SQL = (
    "(SELECT {norm} AS nk, MIN(CAST(site_id AS TEXT)) AS sid, MIN(site_name) AS sn, "
    "MIN(province_county) AS pc, MIN(region) AS rg, MIN(site_type) AS st, "
    "MIN(network_type) AS nt FROM eflow_site GROUP BY 1) e"
)


def missing_tables(conn) -> List[str]:
    """返回当前连接里**不存在**的 KPI 表名。"""
    try:
        have = set(list_table_names(conn))
    except Exception:
        return []
    return [spec[0] for spec in TECH_SPEC.values() if spec[0] not in have]


def load_month_data(start_day: str, end_day: str) -> Dict[str, Any]:
    """读 [start_day, end_day] 区间内三制式的**站点级日可用率**。

    返回 {
      "sites": {site_key: {"site_id","site_name","county","region","site_type","network_type"}},
      "by_tech": {"2G": {site_key: {day: value}}, ...},
      "unmatched": {"2G": {norm_name: {day: value}}, ...},
      "data_through": "YYYY-MM-DD",
      "missing_tables": [...],
      "county_sites": {county: [site_key, ...]},
      "county_regions": {county: region},
    }
    """
    ck = f"avail_county:data:{start_day}:{end_day}"
    cached = cache_get(ck)
    if cached is not None:
        return cached

    out: Dict[str, Any] = {
        "sites": {}, "by_tech": {}, "unmatched": {},
        "data_through": "", "missing_tables": [],
    }
    with get_raw_connection(timeout=120) as conn:
        missing = missing_tables(conn)
        if missing:
            out["missing_tables"] = missing
            logger.warning("[avail-county] KPI 表缺失: %s", missing)
            return out

        # 站点主数据（去重后的维度表）
        dim_rows = conn.execute(
            "SELECT {norm} AS nk, MIN(CAST(site_id AS TEXT)), MIN(site_name), "
            "MIN(province_county), MIN(region), MIN(site_type), MIN(network_type) "
            "FROM eflow_site GROUP BY 1"
            .format(norm=_norm_sql("site_name"))
        ).fetchall()
        for r in dim_rows:
            key = str(r[0] or "")
            if not key:
                continue
            out["sites"][key] = {
                "site_id": str(r[1] or ""),
                "site_name": str(r[2] or ""),
                "county": str(r[3] or ""),
                "region": str(r[4] or ""),
                "site_type": str(r[5] or ""),
                "network_type": str(r[6] or ""),
            }

        # 三制式站点级日值（LEFT JOIN：匹配不上的站点 nk 为 NULL）
        for tech, (tbl, site_col, val_col) in TECH_SPEC.items():
            sql = (
                'SELECT e.nk, substr(k."Begin Time", 1, 10) AS d, CAST(k."{val}" AS REAL) '
                'FROM "{tbl}" k LEFT JOIN {dim} ON e.nk = {knorm} '
                'WHERE k."Begin Time" >= ? AND k."Begin Time" <= ? '
                'AND k."{val}" IS NOT NULL'
                .format(val=val_col, tbl=tbl, dim=_DIM_SQL.format(
                    norm=_norm_sql("site_name")), knorm=_norm_sql('k."%s"' % site_col))
            )
            rows = conn.execute(sql, (f"{start_day} 00:00:00", f"{end_day} 23:59:59")).fetchall()
            by_site: Dict[str, Dict[str, float]] = {}
            latest = ""
            for nk, d, v in rows:
                if not d or not nk:
                    continue   # 未归属的站点由 _load_unmatched 单独取
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                # 有效域：UME 给的是 0~1 的比率；>1.5 视为脏值丢弃
                if fv < 0 or fv > 1.5:
                    continue
                d = str(d)[:10]
                if d > latest:
                    latest = d
                by_site.setdefault(str(nk), {})[d] = fv
            out["by_tech"][tech] = by_site
            out["unmatched"][tech] = _load_unmatched(
                conn, tbl, site_col, val_col, start_day, end_day)
            if latest > out["data_through"]:
                out["data_through"] = latest

        # 县 -> 站点清单 / 县 -> 大区（聚合时反复用，先算一次）
        county_sites: Dict[str, List[str]] = {}
        county_regions: Dict[str, Dict[str, int]] = {}
        for key, meta in out["sites"].items():
            county_sites.setdefault(meta["county"], []).append(key)
            if meta["region"]:
                d = county_regions.setdefault(meta["county"], {})
                d[meta["region"]] = d.get(meta["region"], 0) + 1
        out["county_sites"] = county_sites
        out["county_regions"] = {
            c: (max(d.items(), key=lambda kv: kv[1])[0] if d else "")
            for c, d in county_regions.items()
        }

    logger.info("[avail-county] 载入 %s~%s sites=%d data_through=%s",
                start_day, end_day, len(out["sites"]), out["data_through"])
    return cache_set(ck, out)


def _load_unmatched(conn, tbl: str, site_col: str, val_col: str,
                    start_day: str, end_day: str) -> Dict[str, Dict[str, float]]:
    """取 PG 里匹配不上 eflow_site 的站点（按站点名分组）。

    这些站点没有县归属，单列「未归属站点」行，不计入任何县。
    """
    sql = (
        'SELECT k."{sc}", substr(k."Begin Time", 1, 10) AS d, CAST(k."{val}" AS REAL) '
        'FROM "{tbl}" k LEFT JOIN {dim} ON e.nk = {knorm} '
        'WHERE k."Begin Time" >= ? AND k."Begin Time" <= ? '
        'AND k."{val}" IS NOT NULL AND e.nk IS NULL'
        .format(sc=site_col, val=val_col, tbl=tbl, dim=_DIM_SQL.format(
            norm=_norm_sql("site_name")), knorm=_norm_sql('k."%s"' % site_col))
    )
    out: Dict[str, Dict[str, float]] = {}
    for nm, d, v in conn.execute(
        sql, (f"{start_day} 00:00:00", f"{end_day} 23:59:59")
    ).fetchall():
        if not d:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv < 0 or fv > 1.5:
            continue
        out.setdefault(str(nm or ""), {})[str(d)[:10]] = fv
    return out


def load_counties() -> List[Dict[str, Any]]:
    """县清单 + 各县站点数（来自 eflow_site 主数据，与矩阵口径同源）。"""
    ck = "avail_county:counties"
    cached = cache_get(ck)
    if cached is not None:
        return cached
    out: List[Dict[str, Any]] = []
    try:
        with get_raw_connection(timeout=60) as conn:
            rows = conn.execute(
                "SELECT province_county, COUNT(DISTINCT {norm}) "
                "FROM eflow_site GROUP BY 1 ORDER BY 2 DESC"
                .format(norm=_norm_sql("site_name"))
            ).fetchall()
            for name, cnt in rows:
                nm = str(name or "").strip()
                if not nm:
                    continue
                out.append({"county": nm, "site_count": int(cnt or 0)})
    except Exception as e:
        logger.warning("[avail-county] 读取县清单失败: %s", e)
        return out
    return cache_set(ck, out)


def data_months() -> List[str]:
    """有数据的月份（从 KPI 表的 Begin Time 范围推）。

    ⚠️ 下界取三张表 MIN 的最小值、上界取 MAX 的最大值 ——
       三张表的同步进度不一致（实测 2026-11 只有 1 天），
       若上界也用 MIN 会把月份范围压成只剩一个月。
    """
    ck = "avail_county:months"
    cached = cache_get(ck)
    if cached is not None:
        return cached
    months: List[str] = []
    try:
        with get_raw_connection(timeout=60) as conn:
            if missing_tables(conn):
                return months
            mins: List[str] = []
            maxs: List[str] = []
            for tbl, _, _ in TECH_SPEC.values():
                r = conn.execute(
                    'SELECT MIN("Begin Time"), MAX("Begin Time") FROM "{tbl}"'.format(tbl=tbl)
                ).fetchone()
                if r and r[0]:
                    mins.append(str(r[0])[:10])
                if r and r[1]:
                    maxs.append(str(r[1])[:10])
            if mins and maxs:
                lo = min(mins)[:7]
                hi = max(maxs)[:7]
                y, m = int(lo[:4]), int(lo[5:7])
                ey, em = int(hi[:4]), int(hi[5:7])
                while (y, m) <= (ey, em):
                    months.append(f"{y:04d}-{m:02d}")
                    m += 1
                    if m > 12:
                        m = 1
                        y += 1
    except Exception as e:
        logger.warning("[avail-county] 读取可用月份失败: %s", e)
    return cache_set(ck, months)


def current_month() -> str:
    """当前自然月 'YYYY-MM'。"""
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


def default_threshold() -> float:
    """未达标阈值（比率）。复用 site_availability_service 的默认值，不另起一套。"""
    return DEFAULT_THRESHOLD


__all__ = [
    "CACHE_TTL", "DEFAULT_THRESHOLD", "LOOKBACK_DAYS", "PERIODS", "TECHS",
    "TECH_SPEC", "UNMATCHED_KEY", "cache_get", "cache_set", "current_month",
    "data_months", "latest_day_with_data", "load_counties", "load_month_data",
    "load_start_day", "month_days", "month_weeks", "period_bounds",
    "prev_period_days",
]
