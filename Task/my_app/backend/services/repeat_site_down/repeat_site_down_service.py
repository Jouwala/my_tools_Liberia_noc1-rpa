"""Daily site-down aggregation and drilldown from eflow_tt + eflow_site."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names, table_columns

logger = logging.getLogger(__name__)
_schema_cache: dict[str, Any] | None = None


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _detect_schema(refresh: bool = False) -> dict[str, Any]:
    global _schema_cache
    if _schema_cache is not None and not refresh:
        return _schema_cache
    with get_raw_connection() as conn:
        tables = set(list_table_names(conn))
        tt = set(table_columns(conn, "eflow_tt")) if "eflow_tt" in tables else set()
        site = set(table_columns(conn, "eflow_site")) if "eflow_site" in tables else set()
    pick = lambda cols, names: next((c for c in names if c in cols), None)
    tt_id = pick(tt, ("site_id", "siteid", "site_code")); tt_name = pick(tt, ("site_name", "sitename", "asset_name"))
    site_id = pick(site, ("site_id", "siteid", "site_code")); site_name = pick(site, ("site_name", "sitename", "name"))
    schema = {
        "tables": tables, "tt_columns": tt, "site_columns": site,
        "tt_id": tt_id, "tt_name": tt_name, "site_id": site_id, "site_name": site_name,
        "outage": pick(tt, ("site_outage", "whether_site_interruption_site_outage_or_not", "site_interruption")),
        "occur": pick(tt, ("alarm_occur_time", "created_time", "last_modified_time")),
        "tt_no": pick(tt, ("tt_no", "ticket_no", "wo_no")),
        "site_fields": {k: c for k, c in {
            "region": pick(site, ("region", "region_level1", "area")),
            "province_county": pick(site, ("province_county", "district", "commune")),
            "site_status": pick(site, ("site_status", "status")),
        }.items() if c},
    }
    _schema_cache = schema
    return schema


def refresh_schema() -> dict[str, Any]:
    return _detect_schema(True)


def _validate_date(value: str, label: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be YYYY-MM-DD") from exc


def default_window() -> tuple[str, str]:
    end = date.today(); return (end - timedelta(days=30)).isoformat(), end.isoformat()


def _base_result(start: str, end: str, schema: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    if "eflow_tt" not in schema["tables"]: warnings.append("eflow_tt table is unavailable")
    if "eflow_site" not in schema["tables"]: warnings.append("eflow_site table is unavailable; site metadata cannot be enriched")
    if not schema["outage"]: warnings.append("No site-outage flag column was found; outage rows cannot be selected")
    if not schema["occur"]: warnings.append("No occurrence-time column was found; daily grouping is unavailable")
    return {
        "filters": {"start": start, "end": end, "region": "", "site": ""},
        "meta": {"generated_at": datetime.now().isoformat(timespec="seconds"), "source_tables": ["eflow_tt", "eflow_site"], "counting_rule": "one eflow_tt row with site_outage=Yes equals one outage occurrence", "warnings": warnings, "schema": {k: v for k, v in schema.items() if k not in ("tables", "tt_columns", "site_columns")}},
        "summary": {"outage_events": 0, "affected_sites": 0, "repeat_sites": 0, "peak_day": "", "peak_day_count": 0}, "daily": [], "sites": [], "events": [],
    }


def _load_events(start: str, end: str, region: str = "", site_query: str = "") -> tuple[dict[str, Any], list[dict[str, Any]]]:
    schema = _detect_schema(); result = _base_result(start, end, schema)
    if result["meta"]["warnings"]: return result, []
    tt_id, tt_name, occur, outage = schema["tt_id"], schema["tt_name"], schema["occur"], schema["outage"]
    if not tt_id and not tt_name:
        result["meta"]["warnings"].append("eflow_tt has neither site_id nor site_name"); return result, []
    # Select all currently available TT columns for the detail level, while keeping a stable normalized set.
    stable = ["title", "status", "ticket_severity", "alarm_category", "alarm_code", "domain", "site_outage", "down_site_count", "down_site_list", "alarm_clear_time", "fault_duration_time", "created_time", "last_modified_time", "root_cause", "sub_root_cause", "current_handler", "sla_status", "region_level1", "site_type", "site_class"]
    select = [f't."{occur}" AS occur_time', f't."{outage}" AS outage_flag']
    for col, alias in ((tt_id, "tt_site_id"), (tt_name, "tt_site_name"), (schema["tt_no"], "tt_no")):
        if col: select.append(f't."{col}" AS "{alias}"')
    for col in stable:
        if col in schema["tt_columns"]: select.append(f't."{col}" AS "{col}"')
    if schema["site_id"]: select.append(f's."{schema["site_id"]}" AS site_dim_id')
    if schema["site_name"]: select.append(f's."{schema["site_name"]}" AS site_dim_name')
    for alias, col in schema["site_fields"].items(): select.append(f's."{col}" AS "site_{alias}"')
    params: list[Any] = [start + " 00:00:00", (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d") + " 00:00:00"]
    where = [f't."{occur}" >= ?', f't."{occur}" < ?', f"LOWER(TRIM(CAST(t.\"{outage}\" AS TEXT))) IN ('yes', 'y', '1', 'true')"]
    if schema["site_id"] and tt_id: join = f'LEFT JOIN eflow_site s ON CAST(t."{tt_id}" AS TEXT) = CAST(s."{schema["site_id"]}" AS TEXT)'
    elif schema["site_name"] and tt_name: join = f'LEFT JOIN eflow_site s ON LOWER(TRIM(CAST(t."{tt_name}" AS TEXT))) = LOWER(TRIM(CAST(s."{schema["site_name"]}" AS TEXT)))'
    else: join = "LEFT JOIN eflow_site s ON 1=0"
    if region and schema["site_fields"].get("region"):
        where.append(f's."{schema["site_fields"]["region"]}" = ?'); params.append(region)
    if site_query:
        terms = []
        if tt_id: terms.append(f'CAST(t."{tt_id}" AS TEXT) ILIKE ?')
        if tt_name: terms.append(f'CAST(t."{tt_name}" AS TEXT) ILIKE ?')
        if schema["site_name"]: terms.append(f'CAST(s."{schema["site_name"]}" AS TEXT) ILIKE ?')
        where.append("(" + " OR ".join(terms) + ")"); params.extend([f"%{site_query}%"] * len(terms))
    sql = f'SELECT {", ".join(select)} FROM eflow_tt t {join} WHERE ' + " AND ".join(where) + f' ORDER BY t."{occur}" DESC'
    with get_raw_connection() as conn: rows = conn.execute(sql, params).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row) if hasattr(row, "keys") else {}
        ts = _clean(d.get("occur_time")); day = ts[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", ts) else ""
        if not day:
            result["meta"]["malformed_time_rows"] = result["meta"].get("malformed_time_rows", 0) + 1; continue
        sid = _clean(d.get("tt_site_id") or d.get("site_dim_id")); sname = _clean(d.get("tt_site_name") or d.get("site_dim_name"))
        if not sid and not sname: sid, sname = "__unknown__", "Unknown"
        event = {"day": day, "site_id": sid, "site_name": sname, "region": _clean(d.get("site_region") or d.get("region_level1")), "tt_no": _clean(d.get("tt_no")), "alarm_occur_time": ts, "outage_flag": _clean(d.get("outage_flag"))}
        for key in stable:
            if key in d: event[key] = d.get(key)
        events.append(event)
    result["meta"]["source_rows"] = len(events)
    return result, events


def _aggregate(result: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    by_day: dict[str, int] = {}; by_site: dict[str, dict[str, Any]] = {}
    for event in events:
        by_day[event["day"]] = by_day.get(event["day"], 0) + 1
        key = event["site_id"] or _norm(event["site_name"])
        item = by_site.setdefault(key, {"site_id": event["site_id"], "site_name": event["site_name"], "region": event["region"], "outage_count": 0, "days": set(), "daily": {}})
        item["outage_count"] += 1; item["days"].add(event["day"]); item["daily"][event["day"]] = item["daily"].get(event["day"], 0) + 1
    result["daily"] = [{"day": d, "outage_count": n, "affected_sites": len({e["site_id"] or _norm(e["site_name"]) for e in events if e["day"] == d})} for d, n in sorted(by_day.items())]
    result["sites"] = []
    for item in by_site.values():
        item["repeat_days"] = len(item.pop("days")); item["daily"] = [{"day": d, "outage_count": n} for d, n in sorted(item["daily"].items())]; result["sites"].append(item)
    result["sites"].sort(key=lambda x: (-x["outage_count"], -x["repeat_days"], x["site_name"]))
    peak = max(result["daily"], key=lambda x: x["outage_count"], default={})
    result["summary"] = {"outage_events": len(events), "affected_sites": len(result["sites"]), "repeat_sites": sum(1 for s in result["sites"] if s["repeat_days"] > 1), "peak_day": peak.get("day", ""), "peak_day_count": peak.get("outage_count", 0)}
    result["events"] = events
    return result


def get_filters() -> dict[str, Any]:
    schema = _detect_schema(); regions: list[str] = []
    if schema["site_fields"].get("region") and "eflow_site" in schema["tables"]:
        with get_raw_connection() as conn: regions = [str(r[0]) for r in conn.execute(f'SELECT DISTINCT "{schema["site_fields"]["region"]}" FROM eflow_site WHERE "{schema["site_fields"]["region"]}" IS NOT NULL AND TRIM(CAST("{schema["site_fields"]["region"]}" AS TEXT)) != \'\' ORDER BY 1').fetchall()]
    start, end = default_window(); return {"regions": regions, "default_start": start, "default_end": end, "schema": _base_result(start, end, schema)["meta"]}


def get_overview(start: str, end: str, region: str = "", site_query: str = "") -> dict[str, Any]:
    start, end = _validate_date(start, "start"), _validate_date(end, "end")
    if start > end: raise ValueError("start must be <= end")
    result, events = _load_events(start, end, region.strip(), site_query.strip()); result["filters"].update({"region": region, "site": site_query}); return _aggregate(result, events)


def get_day_drilldown(start: str, end: str, day: str, region: str = "", site_query: str = "") -> dict[str, Any]:
    day = _validate_date(day, "day"); result = get_overview(start, end, region, site_query); events = [e for e in result["events"] if e["day"] == day]
    day_result = {"day": day, "summary": {"outage_events": len(events), "affected_sites": len({e["site_id"] or _norm(e["site_name"]) for e in events})}, "events": events, "sites": []}
    groups: dict[str, dict[str, Any]] = {}
    for e in events:
        key = e["site_id"] or _norm(e["site_name"]); item = groups.setdefault(key, {"site_id": e["site_id"], "site_name": e["site_name"], "region": e["region"], "outage_count": 0}); item["outage_count"] += 1
    day_result["sites"] = sorted(groups.values(), key=lambda x: (-x["outage_count"], x["site_name"])); day_result["meta"] = result["meta"]; return day_result


def get_site_drilldown(start: str, end: str, site_id: str = "", site_name: str = "", region: str = "", site_query: str = "") -> dict[str, Any]:
    result = get_overview(start, end, region, site_query or site_id or site_name); events = [e for e in result["events"] if (site_id and e["site_id"] == site_id) or (not site_id and site_name and e["site_name"] == site_name)]
    daily: dict[str, int] = {}
    for e in events: daily[e["day"]] = daily.get(e["day"], 0) + 1
    return {"site": {"site_id": site_id or (events[0]["site_id"] if events else ""), "site_name": site_name or (events[0]["site_name"] if events else ""), "region": events[0]["region"] if events else region}, "summary": {"outage_events": len(events), "repeat_days": len(daily)}, "daily": [{"day": d, "outage_count": n} for d, n in sorted(daily.items())], "events": events, "meta": result["meta"]}


def get_event_detail(start: str, end: str, tt_no: str = "", alarm_occur_time: str = "", site_id: str = "", site_name: str = "", region: str = "") -> dict[str, Any]:
    result = get_site_drilldown(start, end, site_id, site_name, region); candidates = result["events"]
    if tt_no: candidates = [e for e in candidates if e.get("tt_no") == tt_no]
    if alarm_occur_time: candidates = [e for e in candidates if e.get("alarm_occur_time") == alarm_occur_time]
    return {"event": candidates[0] if candidates else None, "meta": result["meta"]}
