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
# SLA 达成率入榜的最小样本量：分母（Pass+Failed）不足此数的 FME 不参与 SLA 名次，
# 避免小样本（如 2 单全 Pass = 100%）把真实高达成率的大样本 FME 挤下去。
SLA_MIN_SAMPLE = 5
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
        # SLA 达成率用：优先 eflow_wo.sla_status；缺失时退回 group_sla_status
        "sla_status": _pick(columns, ("sla_status", "sla_status1", "group_sla_status", "SLA Status")),
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
            "time_field": schema["time"] or "", "warnings": warnings, "month": month,
            "sla_field": "", "sla_counted": 0}


# SLA 达标口径（与 nur_calc / portal_qc / gis 一致）：
#   sla_status ∈ ('Pass','Within SLA') 记为达标，'Failed' 记为未达标；
#   两者都为空/其它值（如 None）的记录不计入分母，避免用未知状态拉低达成率。
SLA_PASS_VALUES = ("pass", "within sla")
SLA_FAIL_VALUE = "failed"


def _sla_bucket() -> Dict[str, int]:
    return {"total": 0, "open": 0, "closed": 0, "sla_pass": 0, "sla_fail": 0}


def load_wo_by_site(month: str) -> Dict[str, Any]:
    """读取月份内 WO 并归属到唯一站点，返回按站点 ID 的计数（含 SLA 达标计数）。"""
    key = f"fme_ranking:wo:{month}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    schema = detect_wo_schema()
    result = _empty_wo(schema, month)
    if result["warnings"]:
        return _cache_set(key, result)

    start, end = month_bounds_exclusive(month)
    # sla_status 用于 SLA 达成率；字段缺失时退化为 NULL（达成率为 None 而非 0）
    select = [f'"{schema["site_id"]}" AS site_id' if schema["site_id"] else "NULL AS site_id",
              f'"{schema["site_name"]}" AS site_name' if schema["site_name"] else "NULL AS site_name",
              f'"{schema["time"]}" AS event_time',
              f'"{schema["status"]}" AS status' if schema["status"] else "NULL AS status",
              f'"{schema["sla_status"]}" AS sla_status' if schema["sla_status"] else "NULL AS sla_status"]
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
    sla_counted = 0
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
        bucket = grouped.setdefault(site_key, _sla_bucket())
        bucket["total"] += 1
        if str(row[3] or "").strip().lower() == "closed":
            bucket["closed"] += 1
        else:
            bucket["open"] += 1
        sla = str(row[4] or "").strip().lower()
        if sla in SLA_PASS_VALUES:
            bucket["sla_pass"] += 1
            sla_counted += 1
        elif sla == SLA_FAIL_VALUE:
            bucket["sla_fail"] += 1
            sla_counted += 1
    result["by_site"] = grouped
    result["sla_field"] = schema["sla_status"] or ""
    result["sla_counted"] = sla_counted
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
                                             "site_data_count": 0, "avail_values": [],
                                             "wo": {"total": 0, "open": 0, "closed": 0, "sla_pass": 0, "sla_fail": 0}})
        if site.get("supervisor"):
            group["supervisor_set"].add(str(site["supervisor"]))
        group["site_count"] += 1
        site_key = str(site.get("site_id") or "").strip() or f"name:{site.get('_k', '')}"
        stat = {"total": 0, "open": 0, "closed": 0, "sla_pass": 0, "sla_fail": 0}
        stat.update(wo["by_site"].get(site_key, {}))
        for metric in ("total", "open", "closed", "sla_pass", "sla_fail"):
            group["wo"][metric] += stat[metric]
        values = [avail[(site.get("_k"), day)] for day in days if (site.get("_k"), day) in avail]
        if values:
            group["site_data_count"] += 1
            group["avail_values"].append(sum(values) / len(values))

    rows: List[Dict[str, Any]] = []
    for group in groups.values():
        values = group.pop("avail_values")
        avg = sum(values) / len(values) if values else None
        sla_pass, sla_fail = group["wo"]["sla_pass"], group["wo"]["sla_fail"]
        sla_denom = sla_pass + sla_fail
        item = {
            "fme_name": group["fme_name"], "supervisors": sorted(group.pop("supervisor_set")),
            "site_count": group["site_count"], "sites_with_availability": group["site_data_count"],
            "availability": avg, "sites_below_threshold": sum(1 for value in values if value < threshold),
            "wo_total": group["wo"]["total"], "wo_open": group["wo"]["open"], "wo_closed": group["wo"]["closed"],
            # SLA 达成率 = Pass(+Within SLA) / (Pass + Failed)；无计入口径记录时为 None
            "sla_pass": sla_pass, "sla_fail": sla_fail, "sla_total": sla_denom,
            "sla_rate": (sla_pass / sla_denom) if sla_denom else None,
        }
        rows.append(item)

    # 排名口径：可用率降序；可用率相同时，SLA 达成率高的在前（SLA 作为并列时的决胜项）
    availability_rows = sorted(rows, key=lambda row: (row["availability"] is None, -(row["availability"] or 0),
                                                      -(row["sla_rate"] if row["sla_rate"] is not None else -1), row["fme_name"]))
    wo_rows = sorted(rows, key=lambda row: (row["wo_total"], row["fme_name"]))
    # SLA 达成率排名：降序；无数据的排最后。
    for rank, row in enumerate(availability_rows, 1):
        row["availability_rank"] = rank
    for rank, row in enumerate(wo_rows, 1):
        row["wo_rank"] = rank
    # 小样本保护：分母（Pass+Failed）不足 SLA_MIN_SAMPLE 的 FME 不参与名次，
    # 否则「2 单全 Pass」会压过「80 单全 Pass」。这类行仍返回数据，sla_rank 为 None。
    for row in rows:
        row["sla_ranked"] = row["sla_total"] >= SLA_MIN_SAMPLE
    sla_rows = sorted([r for r in rows if r["sla_ranked"]],
                      key=lambda row: (-(row["sla_rate"] or 0), row["fme_name"]))
    for rank, row in enumerate(sla_rows, 1):
        row["sla_rank"] = rank
    for row in rows:
        if not row["sla_ranked"]:
            row["sla_rank"] = None
    rows.sort(key=lambda row: (row["availability_rank"], row["fme_name"]))

    warnings = list(wo["warnings"])
    if not avail:
        warnings.append(f"{tech} 制式本月无站点可用率数据")
    if not wo.get("sla_field"):
        warnings.append("eflow_wo 缺少 sla_status 字段，SLA 达成率不可用")
    elif not wo.get("sla_counted"):
        warnings.append("本月 WO 无 Pass/Failed 的 SLA 状态记录，SLA 达成率为空")
    return {
        "meta": {"month": month, "tech": tech, "threshold": threshold,
                 "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "elapsed_seconds": round(time.time() - started, 2), "warnings": warnings,
                 "sources": {"master": "master_site_db", "wo": "eflow_wo", "availability": "site_availability_service"},
                 "wo": {k: wo[k] for k in ("source_rows", "matched_rows", "unmatched_rows", "time_field")},
                 "sla": {"field": wo.get("sla_field") or "", "counted": wo.get("sla_counted", 0),
                         "rule": "sla_status ∈ (Pass, Within SLA) 记为达标，Failed 记为未达标；其余不计入分母"}},
        "filters": {"month": month, "tech": tech, "supervisor": supervisor, "fme": fme},
        "summary": {"fme_count": len(rows), "site_count": sum(row["site_count"] for row in rows),
                    "sites_with_availability": sum(row["sites_with_availability"] for row in rows),
                    "wo_total": sum(row["wo_total"] for row in rows), "wo_open": sum(row["wo_open"] for row in rows),
                    "wo_closed": sum(row["wo_closed"] for row in rows),
                    "sla_pass": sum(row["sla_pass"] for row in rows),
                    "sla_fail": sum(row["sla_fail"] for row in rows),
                    "sla_total": sum(row["sla_total"] for row in rows),
                    "sla_rate": (sum(row["sla_pass"] for row in rows) / sum(row["sla_total"] for row in rows))
                                if sum(row["sla_total"] for row in rows) else None},
        "rows": rows,
    }


_WO_DETAIL_COLUMNS = (
    "wo_no", "tt_no", "title", "status", "created_time", "last_modified_time",
    "current_handler", "sla_status", "ticket_severity", "alarm_type",
    "alarm_severity", "alarm_occur_time", "alarm_clear_time", "fault_duration_time",
    "expected_finish_time", "actual_finish_time", "rc_main_category",
)

# 列名 -> 输出字段名（同时给出中文/英文可读标题，前端直接展示）
_WO_FIELD_LABELS: Dict[str, Dict[str, str]] = {
    "wo_no": {"zh": "WO 号", "en": "WO No."},
    "tt_no": {"zh": "TT 号", "en": "TT No."},
    "title": {"zh": "标题", "en": "Title"},
    "site_id": {"zh": "站点 ID", "en": "Site ID"},
    "site_name": {"zh": "站点名称", "en": "Site Name"},
    "status": {"zh": "状态", "en": "Status"},
    "created_time": {"zh": "创建时间", "en": "Created"},
    "last_modified_time": {"zh": "最后修改", "en": "Last Modified"},
    "current_handler": {"zh": "当前处理人", "en": "Current Handler"},
    "sla_status": {"zh": "SLA 状态", "en": "SLA Status"},
    "ticket_severity": {"zh": "严重性", "en": "Severity"},
    "alarm_type": {"zh": "告警类型", "en": "Alarm Type"},
    "alarm_severity": {"zh": "告警等级", "en": "Alarm Severity"},
    "alarm_occur_time": {"zh": "告警发生时间", "en": "Alarm Occur"},
    "alarm_clear_time": {"zh": "告警清除时间", "en": "Alarm Clear"},
    "fault_duration_time": {"zh": "故障时长", "en": "Fault Duration"},
    "expected_finish_time": {"zh": "预计完成", "en": "Expected Finish"},
    "actual_finish_time": {"zh": "实际完成", "en": "Actual Finish"},
    "rc_main_category": {"zh": "根因", "en": "Root Cause"},
}

# 下钻明细行里展示的顺序（先单据标识，再状态时间，最后根因）
_WO_DISPLAY_ORDER = (
    "wo_no", "tt_no", "title", "site_id", "site_name", "status", "sla_status",
    "ticket_severity", "alarm_type", "current_handler", "created_time",
    "alarm_occur_time", "alarm_clear_time", "fault_duration_time",
    "expected_finish_time", "actual_finish_time", "last_modified_time", "rc_main_category",
)


def _resolve_site_id(schema: Dict[str, Any]) -> str:
    """实际读取用的站点 ID 列名。"""
    return schema.get("site_id") or "site_id"


def load_wo_records(month: str) -> List[Dict[str, Any]]:
    """读取月份内 WO 明细（带缓存），并按站点归属。"""
    key = f"fme_ranking:wo_records:{month}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    schema = detect_wo_schema()
    if not schema["table"] or not schema["time"]:
        return _cache_set(key, [])

    columns = set(schema["columns"])
    site_id_col = _resolve_site_id(schema)
    picked = [c for c in _WO_DETAIL_COLUMNS if c in columns]
    select = []
    # site_id 始终取出（用于按 FME 归属），即使不在展示列内
    if site_id_col in columns:
        select.append(f'"{site_id_col}" AS site_id')
    else:
        select.append("NULL AS site_id")
    if schema["site_name"]:
        select.append(f'"{schema["site_name"]}" AS site_name')
    else:
        select.append("NULL AS site_name")
    select += [f'"{c}"' for c in picked]
    sql = (f'SELECT {", ".join(select)} FROM "eflow_wo" '
           f'WHERE "{schema["time"]}" >= ? AND "{schema["time"]}" < ?')

    start, end = month_bounds_exclusive(month)
    try:
        with get_raw_connection(timeout=60) as conn:
            rows = conn.execute(sql, (start, end)).fetchall()
    except Exception as exc:
        logger.warning("[fme-ranking] 读取 WO 明细失败 month=%s: %s", month, exc)
        return _cache_set(key, [])

    out: List[Dict[str, Any]] = []
    for row in rows:
        rec: Dict[str, Any] = {"site_id": row[0], "site_name": row[1]}
        for idx, col in enumerate(picked, start=2):
            rec[col] = row[idx]
        rec["_sid"] = str(rec.get("site_id") or "").strip()
        rec["_k"] = norm_name(rec.get("site_name"))
        rec["_open"] = str(rec.get("status") or "").strip().lower() != "closed"
        out.append(rec)
    return _cache_set(key, out)


def _site_index(master: List[Dict[str, Any]]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """站点 -> FME 归属索引：site_id 优先，站点名兜底。"""
    by_sid: Dict[str, str] = {}
    by_name: Dict[str, str] = {}
    for site in master:
        fme_name = str(site.get("fme_name") or "").strip() or "未分配"
        sid = str(site.get("site_id") or "").strip()
        name_key = site.get("_k") or norm_name(site.get("site_name"))
        if sid and sid not in by_sid:
            by_sid[sid] = fme_name
        if name_key and name_key not in by_name:
            by_name[name_key] = fme_name
    return by_sid, by_name


def build_wo_drilldown(month: str, fme: str = "", supervisor: str = "", limit: int = 800) -> Dict[str, Any]:
    """某 FME（或某 Supervisor 范围）名下的 WO 明细。"""
    month = valid_month(str(month or ""))
    fme = str(fme or "").strip()
    supervisor = str(supervisor or "").strip()
    master = availability.load_master_sites()
    by_sid, by_name = _site_index(master)

    # Supervisor 过滤：先算出该 Supervisor 下的 FME 集合
    allowed_fmes: Optional[set] = None
    if supervisor:
        allowed_fmes = {str(s.get("fme_name") or "").strip() or "未分配" for s in master
                        if str(s.get("supervisor") or "").strip() == supervisor}

    rows: List[Dict[str, Any]] = []
    for rec in load_wo_records(month):
        owner = by_sid.get(rec["_sid"]) if rec["_sid"] else None
        if owner is None and rec["_k"]:
            owner = by_name.get(rec["_k"])
        if owner is None:
            continue
        if fme and owner != fme:
            continue
        if allowed_fmes is not None and owner not in allowed_fmes:
            continue
        item = {"fme_name": owner}
        for col in _WO_DISPLAY_ORDER:
            item[col] = rec.get(col)
        rows.append(item)

    rows.sort(key=lambda r: str(r.get("created_time") or ""), reverse=True)
    truncated = len(rows) > limit
    return {
        "month": month, "fme": fme, "supervisor": supervisor,
        "total": len(rows), "open": sum(1 for r in rows if str(r.get("status") or "").strip().lower() != "closed"),
        "truncated": truncated,
        "columns": [{"key": c, "zh": _WO_FIELD_LABELS[c]["zh"], "en": _WO_FIELD_LABELS[c]["en"]}
                    for c in _WO_DISPLAY_ORDER],
        "rows": rows[:limit],
    }


def build_site_drilldown(month: str, fme: str = "", supervisor: str = "",
                         tech: str = DEFAULT_TECH, threshold: float = DEFAULT_THRESHOLD,
                         limit: int = 800) -> Dict[str, Any]:
    """某 FME 名下站点级可用率与 WO 明细。

    每行 = 一个站点：站点静态信息 + 该制式月均可用率 + 未达标天数 + WO 数。
    这是「FME -> 站点」这一层的下钻，站点行可继续下钻到 WO。
    """
    month = valid_month(str(month or ""))
    fme = str(fme or "").strip()
    supervisor = str(supervisor or "").strip()
    tech = str(tech or DEFAULT_TECH)
    tech = tech if tech in TECHS else DEFAULT_TECH

    master = availability.load_master_sites()
    avail = availability.load_month_availability(month).get(tech, {})
    days = availability.month_days(month)
    by_sid, by_name = _site_index(master)

    wo_agg: Dict[str, Dict[str, int]] = {}
    for rec in load_wo_records(month):
        owner = by_sid.get(rec["_sid"]) if rec["_sid"] else None
        if owner is None and rec["_k"]:
            owner = by_name.get(rec["_k"])
        if owner is None:
            continue
        key = rec["_sid"] or f"name:{rec['_k']}"
        bucket = wo_agg.setdefault(key, {"total": 0, "open": 0, "closed": 0, "sla_pass": 0, "sla_fail": 0})
        bucket["total"] += 1
        if rec["_open"]:
            bucket["open"] += 1
        else:
            bucket["closed"] += 1
        sla = str(rec.get("sla_status") or "").strip().lower()
        if sla in SLA_PASS_VALUES:
            bucket["sla_pass"] += 1
        elif sla == SLA_FAIL_VALUE:
            bucket["sla_fail"] += 1

    rows: List[Dict[str, Any]] = []
    for site in master:
        owner = str(site.get("fme_name") or "").strip() or "未分配"
        if fme and owner != fme:
            continue
        if supervisor and str(site.get("supervisor") or "").strip() != supervisor:
            continue
        values = [avail[(site.get("_k"), day)] for day in days if (site.get("_k"), day) in avail]
        avg = sum(values) / len(values) if values else None
        site_key = str(site.get("site_id") or "").strip() or f"name:{site.get('_k', '')}"
        wo = wo_agg.get(site_key, {"total": 0, "open": 0, "closed": 0, "sla_pass": 0, "sla_fail": 0})
        sla_denom = wo["sla_pass"] + wo["sla_fail"]
        rows.append({
            "site_id": site.get("site_id"), "site_name": site.get("site_name"),
            "fme_name": owner, "supervisor": site.get("supervisor"),
            "region": site.get("region"), "province_county": site.get("province_county"),
            "network_type": site.get("network_type"), "site_type": site.get("site_type"),
            "vip_site": site.get("vip_site"),
            "availability": avg, "days_with_data": len(values),
            "days_below_threshold": sum(1 for v in values if v < threshold),
            "below_threshold": avg is not None and avg < threshold,
            "wo_total": wo["total"], "wo_open": wo["open"], "wo_closed": wo["closed"],
            "sla_pass": wo["sla_pass"], "sla_fail": wo["sla_fail"],
            "sla_rate": (wo["sla_pass"] / sla_denom) if sla_denom else None,
        })

    rows.sort(key=lambda r: (r["availability"] is None, r["availability"] if r["availability"] is not None else 0))
    return {
        "month": month, "fme": fme, "supervisor": supervisor, "tech": tech, "threshold": threshold,
        "total": len(rows), "truncated": len(rows) > limit,
        "sites_with_data": sum(1 for r in rows if r["availability"] is not None),
        "sites_below_threshold": sum(1 for r in rows if r["below_threshold"]),
        "columns": [
            {"key": "site_id", "zh": "站点 ID", "en": "Site ID"},
            {"key": "site_name", "zh": "站点名称", "en": "Site Name"},
            {"key": "region", "zh": "区域", "en": "Region"},
            {"key": "province_county", "zh": "省/县", "en": "Province/County"},
            {"key": "network_type", "zh": "网络类型", "en": "Network Type"},
            {"key": "availability", "zh": "月均可用率", "en": "Monthly Availability"},
            {"key": "days_below_threshold", "zh": "未达标天数", "en": "Days Below"},
            {"key": "days_with_data", "zh": "有数据天数", "en": "Days With Data"},
            {"key": "wo_total", "zh": "WO 总数", "en": "WO Total"},
            {"key": "wo_open", "zh": "未闭环", "en": "Open WO"},
            {"key": "sla_rate", "zh": "SLA 达成率", "en": "SLA Achievement"},
            {"key": "sla_fail", "zh": "SLA 未达标", "en": "SLA Failed"},
            {"key": "supervisor", "zh": "Supervisor", "en": "Supervisor"},
        ],
        "rows": rows[:limit],
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
