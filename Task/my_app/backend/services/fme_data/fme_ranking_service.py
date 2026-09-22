# -*- coding: utf-8 -*-
"""按 FME 聚合 WO 与站点可用率并生成排名。

站点主数据来自 ``master_site_db``，可用率复用站点可用率服务的统一口径；
WO 直接读取 ``eflow_wo``，优先使用 site_id 关联，站点 ID 不可用时回退到
规范化站点名。这里不生成综合分数，避免把数量和百分比混成没有业务含义的单一指标。
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names, table_columns
from backend.services import site_availability_service as availability

logger = logging.getLogger("fme_ranking")

TECHS = ("G", "U", "L", "Tdd")
DEFAULT_TECH = "L"
DEFAULT_THRESHOLD = availability.DEFAULT_THRESHOLD
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

try:
    from backend.services.cache import get_cache
    _cache = get_cache()
except Exception:  # pragma: no cover
    _cache = None

_CACHE_TTL = 300
_schema_cache: Optional[Dict[str, Any]] = None


def _cache_get(key: str):
    if _cache is None:
        return None
    try:
        return _cache.get(key)
    except Exception:
        return None


def _cache_set(key: str, value: Any):
    if _cache is None:
        return value
    try:
        _cache.set(key, value, _CACHE_TTL)
    except Exception:
        pass
    return value


def norm_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def valid_month(value: str) -> str:
    if value and _MONTH_RE.match(value):
        return value
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


def month_bounds_exclusive(month: str) -> Tuple[str, str]:
    year, mon = int(month[:4]), int(month[5:7])
    end_year, end_month = (year + 1, 1) if mon == 12 else (year, mon + 1)
    return f"{year:04d}-{mon:02d}-01 00:00:00", f"{end_year:04d}-{end_month:02d}-01 00:00:00"


def _pick(columns: set[str], names: Tuple[str, ...]) -> Optional[str]:
    return next((name for name in names if name in columns), None)


def detect_wo_schema(refresh: bool = False) -> Dict[str, Any]:
    """探测 eflow_wo 可用字段，避免动态表字段变动导致 500。"""
    global _schema_cache
    if _schema_cache is not None and not refresh:
        return _schema_cache
    with get_raw_connection() as conn:
        tables = set(list_table_names(conn))
        columns = set(table_columns(conn, "eflow_wo")) if "eflow_wo" in tables else set()
    _schema_cache = {
        "table": "eflow_wo" in tables,
        "columns": columns,
        "site_id": _pick(columns, ("site_id", "siteid", "site_code")),
        "site_name": _pick(columns, ("site_name", "sitename", "asset_name")),
        "time": _pick(columns, ("created_time", "create_time", "alarm_occur_time", "last_modified_time")),
        "status": "status" if "status" in columns else None,
    }
    return _schema_cache


def refresh_schema() -> Dict[str, Any]:
    return detect_wo_schema(refresh=True)


def _empty_wo(schema: Dict[str, Any], month: str) -> Dict[str, Any]:
    warnings: List[str] = []
    if not schema["table"]:
        warnings.append("eflow_wo 表不存在，WO 统计为空")
    if not schema["site_id"] and not schema["site_name"]:
        warnings.append("eflow_wo 缺少 site_id/site_name，无法关联站点")
    if not schema["time"]:
        warnings.append("eflow_wo 缺少时间字段，无法按月份统计")
    return {"by_site": {}, "source_rows": 0, "matched_rows": 0, "unmatched_rows": 0,
            "time_field": schema["time"] or "", "warnings": warnings, "month": month}


def load_wo_by_site(month: str) -> Dict[str, Any]:
    """读取月份内 WO 并归属到唯一站点，返回按站点 ID 的计数。"""
    key = f"fme_ranking:wo:{month}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    schema = detect_wo_schema()
    result = _empty_wo(schema, month)
    if result["warnings"]:
        return _cache_set(key, result)

    start, end = month_bounds_exclusive(month)
    select = [f'"{schema["site_id"]}" AS site_id' if schema["site_id"] else "NULL AS site_id",
              f'"{schema["site_name"]}" AS site_name' if schema["site_name"] else "NULL AS site_name",
              f'"{schema["time"]}" AS event_time',
              f'"{schema["status"]}" AS status' if schema["status"] else "NULL AS status"]
    sql = f'SELECT {", ".join(select)} FROM "eflow_wo" WHERE "{schema["time"]}" >= ? AND "{schema["time"]}" < ?'

    try:
        with get_raw_connection(timeout=30) as conn:
            rows = conn.execute(sql, (start, end)).fetchall()
    except Exception as exc:
        logger.warning("[fme-ranking] 读取 eflow_wo 失败 month=%s: %s", month, exc)
        result["warnings"].append(f"读取 eflow_wo 失败: {exc}")
        return _cache_set(key, result)

    master = availability.load_master_sites()
    by_sid: Dict[str, str] = {}
    by_name: Dict[str, str] = {}
    for site in master:
        sid = str(site.get("site_id") or "").strip()
        name_key = site.get("_k") or norm_name(site.get("site_name"))
        site_key = sid or f"name:{name_key}"
        if sid and sid not in by_sid:
            by_sid[sid] = site_key
        if name_key and name_key not in by_name:
            by_name[name_key] = site_key

    grouped: Dict[str, Dict[str, int]] = {}
    for row in rows:
        result["source_rows"] += 1
        sid = str(row[0] or "").strip()
        name_key = norm_name(row[1])
        site_key = by_sid.get(sid) if sid else None
        if site_key is None and name_key:
            site_key = by_name.get(name_key)
        if site_key is None:
            result["unmatched_rows"] += 1
            continue
        result["matched_rows"] += 1
        bucket = grouped.setdefault(site_key, {"total": 0, "open": 0, "closed": 0})
        bucket["total"] += 1
        if str(row[3] or "").strip().lower() == "closed":
            bucket["closed"] += 1
        else:
            bucket["open"] += 1
    result["by_site"] = grouped
    return _cache_set(key, result)


def build_overview(month: str, tech: str = DEFAULT_TECH, supervisor: str = "", fme: str = "", threshold: float = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """构建 FME 级排名数据。"""
    started = time.time()
    month = valid_month(str(month or ""))
    tech = str(tech or DEFAULT_TECH)
    tech = tech if tech in TECHS else DEFAULT_TECH
    supervisor = str(supervisor or "").strip()
    fme = str(fme or "").strip()
    master = availability.load_master_sites()
    wo = load_wo_by_site(month)
    avail = availability.load_month_availability(month).get(tech, {})
    days = availability.month_days(month)

    groups: Dict[str, Dict[str, Any]] = {}
    for site in master:
        if supervisor and str(site.get("supervisor") or "") != supervisor:
            continue
        if fme and str(site.get("fme_name") or "") != fme:
            continue
        fme_name = str(site.get("fme_name") or "").strip() or "未分配"
        group = groups.setdefault(fme_name, {"fme_name": fme_name, "supervisor_set": set(), "site_count": 0,
                                             "site_data_count": 0, "avail_values": [], "wo": {"total": 0, "open": 0, "closed": 0}})
        if site.get("supervisor"):
            group["supervisor_set"].add(str(site["supervisor"]))
        group["site_count"] += 1
        site_key = str(site.get("site_id") or "").strip() or f"name:{site.get('_k', '')}"
        stat = {"total": 0, "open": 0, "closed": 0}
        stat.update(wo["by_site"].get(site_key, {}))
        for metric in ("total", "open", "closed"):
            group["wo"][metric] += stat[metric]
        values = [avail[(site.get("_k"), day)] for day in days if (site.get("_k"), day) in avail]
        if values:
            group["site_data_count"] += 1
            group["avail_values"].append(sum(values) / len(values))

    rows: List[Dict[str, Any]] = []
    for group in groups.values():
        values = group.pop("avail_values")
        avg = sum(values) / len(values) if values else None
        item = {
            "fme_name": group["fme_name"], "supervisors": sorted(group.pop("supervisor_set")),
            "site_count": group["site_count"], "sites_with_availability": group["site_data_count"],
            "availability": avg, "sites_below_threshold": sum(1 for value in values if value < threshold),
            "wo_total": group["wo"]["total"], "wo_open": group["wo"]["open"], "wo_closed": group["wo"]["closed"],
        }
        rows.append(item)

    availability_rows = sorted(rows, key=lambda row: (row["availability"] is None, -(row["availability"] or 0), row["fme_name"]))
    wo_rows = sorted(rows, key=lambda row: (row["wo_total"], row["fme_name"]))
    for rank, row in enumerate(availability_rows, 1):
        row["availability_rank"] = rank
    for rank, row in enumerate(wo_rows, 1):
        row["wo_rank"] = rank
    rows.sort(key=lambda row: (row["availability_rank"], row["fme_name"]))

    warnings = list(wo["warnings"])
    if not avail:
        warnings.append(f"{tech} 制式本月无站点可用率数据")
    return {
        "meta": {"month": month, "tech": tech, "threshold": threshold,
                 "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "elapsed_seconds": round(time.time() - started, 2), "warnings": warnings,
                 "sources": {"master": "master_site_db", "wo": "eflow_wo", "availability": "site_availability_service"},
                 "wo": {k: wo[k] for k in ("source_rows", "matched_rows", "unmatched_rows", "time_field")}},
        "filters": {"month": month, "tech": tech, "supervisor": supervisor, "fme": fme},
        "summary": {"fme_count": len(rows), "site_count": sum(row["site_count"] for row in rows),
                    "sites_with_availability": sum(row["sites_with_availability"] for row in rows),
                    "wo_total": sum(row["wo_total"] for row in rows), "wo_open": sum(row["wo_open"] for row in rows),
                    "wo_closed": sum(row["wo_closed"] for row in rows)},
        "rows": rows,
    }


def get_filters() -> Dict[str, Any]:
    master = availability.load_master_sites()
    today = date.today()
    months = []
    for offset in range(11, -1, -1):
        year, month = today.year, today.month - offset
        while month <= 0:
            year, month = year - 1, month + 12
        months.append(f"{year:04d}-{month:02d}")
    return {"supervisors": sorted({str(row.get("supervisor") or "").strip() for row in master if str(row.get("supervisor") or "").strip()}),
            "fmes": sorted({str(row.get("fme_name") or "").strip() for row in master if str(row.get("fme_name") or "").strip()}),
            "months": months, "site_count": len(master), "techs": list(TECHS)}
