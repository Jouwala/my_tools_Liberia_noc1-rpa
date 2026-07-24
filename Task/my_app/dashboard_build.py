#!/usr/bin/env python
"""Extract & aggregate realtime_alarm -> dashboard_data.json"""
import sqlite3, json, re
from datetime import datetime, timezone

DB = r"D:/01_RPA/Task/my_app/db/app.db"
OUT = r"D:/01_RPA/Task/my_app/dashboard_data.json"

REGION_CODE = {
    "Bomi": "BM", "Bong": "BG", "Gbarpolu": "GP", "Grand_Bassa": "GB",
    "Grand_Cape_Mount": "GC", "Grand_Gedeh": "GG", "Grand_Kru": "GK",
    "Lofa": "LF", "Margibi": "MB", "Maryland": "MD", "Montserrado": "ML",
    "Nimba": "NB", "River_Cess": "RC", "River_Gee": "RG", "Sinoe": "SE",
}
# Dashboard column order (matches screenshots)
COL_ORDER = ["GG","GP","GB","GK","RG","NB","SE","RC","GC","BM","BG","LF","MB","ML","MD"]

def parse_duration_to_hours(s: str) -> float:
    """Parse '6h 35min 48s' or '8d 5h 27min 52s' into hours."""
    if not s: return 0.0
    days = re.search(r"(\d+)d", s)
    hours = re.search(r"(\d+)h", s)
    mins = re.search(r"(\d+)min", s)
    secs = re.search(r"(\d+)s", s)
    h = 0.0
    if days:  h += int(days.group(1)) * 24
    if hours: h += int(hours.group(1))
    if mins:  h += int(mins.group(1)) / 60
    if secs:  h += int(secs.group(1)) / 3600
    return h

def duration_bucket(h: float) -> str:
    """Return one of 0-2, 2-4, 4-6, 6-12, 12-24, >48."""
    if h < 2: return "0-2"
    if h < 4: return "2-4"
    if h < 6: return "4-6"
    if h < 12: return "6-12"
    if h < 24: return "12-24"
    return ">48"

def tech_from_record(rec):
    """Determine 2G / 3G / 4G / 5G from type suffix first, then restypename."""
    # Most reliable: the 'type' field has '-4G'/'-3G'/'-2G' suffixes (e.g. '4399-4G')
    t = (rec.get("type") or "")
    m = re.search(r"-(\d+G)\b", t)
    if m: return m.group(1)
    # Fallback to restypename; check ENODEB before NODEB (NODEB is a substring)
    rt = rec.get("restypename") or ""
    if "ENODEB" in rt or "GNB" in rt: return "4G"
    if "NODEB" in rt: return "3G"
    if "BTS" in rt: return "2G"
    return "OTHER"

def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM realtime_alarm").fetchall()]
    con.close()

    # Annotate each row with computed fields
    for r in rows:
        r["_tech"] = tech_from_record(r)
        r["_hours"] = parse_duration_to_hours(r.get("durationname") or "")
        r["_bucket"] = duration_bucket(r["_hours"])
        r["_region_code"] = REGION_CODE.get(r.get("region") or "", "--")

    total = len(rows)
    servertime_ms = max((r.get("servertime") or 0) for r in rows)
    server_iso = datetime.fromtimestamp(servertime_ms/1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # By tech (site & cell counts)
    tech_stats = {}  # tech -> {sites:set, cells:int}
    for r in rows:
        t = r["_tech"]
        if t not in tech_stats:
            tech_stats[t] = {"sites": set(), "cells": 0, "site_set": set()}
        tech_stats[t]["site_set"].add(r.get("site_id"))
        tech_stats[t]["cells"] += 1

    logical_total = {
        tech: {
            "site": len(stats["site_set"]),
            "cell": stats["cells"],
        }
        for tech, stats in tech_stats.items()
    }

    # By region x tech (for Logical Site & Logical Cell)
    region_tech = {}  # region_code -> {tech -> {sites:set, cells:int}}
    for r in rows:
        rc = r["_region_code"]
        if rc == "--":
            continue
        tech = r["_tech"]
        region_tech.setdefault(rc, {}).setdefault(tech, {"sites": set(), "cells": 0})
        region_tech[rc][tech]["sites"].add(r.get("site_id"))
        region_tech[rc][tech]["cells"] += 1

    # Physical Site (per region: distinct site count)
    physical = {rc: len(set(r.get("site_id") for r in rows if r["_region_code"] == rc))
                for rc in COL_ORDER}

    # Logical Site per region × tech
    logical_site = {}
    logical_cell = {}
    for rc in COL_ORDER:
        logical_site[rc] = {}
        logical_cell[rc] = {}
        for tech in ["2G", "3G", "4G", "5G"]:
            d = region_tech.get(rc, {}).get(tech, {"sites": set(), "cells": 0})
            logical_site[rc][tech] = len(d["sites"])
            logical_cell[rc][tech] = d["cells"]

    # Duration buckets - all alarms
    bucket_order = ["0-2", "2-4", "4-6", "6-12", "12-24", ">48"]
    all_buckets = {b: 0 for b in bucket_order}
    for r in rows:
        all_buckets[r["_bucket"]] = all_buckets.get(r["_bucket"], 0) + 1

    # Mains fail (transmission_type='MW') duration
    mains_buckets = {b: 0 for b in bucket_order}
    for r in rows:
        if r.get("transmission_type") == "MW":
            mains_buckets[r["_bucket"]] = mains_buckets.get(r["_bucket"], 0) + 1

    # Mains fail stats (per region - count of MW alarms)
    mains_region = {rc: sum(1 for r in rows if r["_region_code"] == rc and r.get("transmission_type") == "MW")
                    for rc in COL_ORDER}

    # Site class (perceivedseverity -> P1..P4)
    severity = {1: "P1", 2: "P2", 3: "P3", 4: "P4"}
    site_class = {f"P{i+1}": 0 for i in range(4)}
    for r in rows:
        sev = r.get("perceivedseverity") or 0
        label = severity.get(sev, f"P{sev}")
        if label in site_class:
            site_class[label] += 1

    # Per-region alarm count (for map)
    region_alarm_count = {rc: sum(1 for r in rows if r["_region_code"] == rc) for rc in COL_ORDER}

    # site_attribute distribution
    site_attr = {}
    for r in rows:
        a = r.get("site_attribute") or "--"
        site_attr[a] = site_attr.get(a, 0) + 1

    # networktype distribution
    nettype = {}
    for r in rows:
        n = r.get("networktype") or "--"
        nettype[n] = nettype.get(n, 0) + 1

    out = {
        "generated_at": server_iso,
        "total_alarms": total,
        "logical_total": logical_total,           # {tech: {site, cell}}
        "physical_site": physical,                # {region: int}
        "logical_site": logical_site,              # {region: {tech: int}}
        "logical_cell": logical_cell,              # {region: {tech: int}}
        "region_alarm_count": region_alarm_count, # for map
        "duration_buckets": all_buckets,
        "duration_bucket_order": bucket_order,
        "mains_duration_buckets": mains_buckets,
        "mains_region": mains_region,
        "site_class": site_class,
        "site_attribute": site_attr,
        "networktype": nettype,
        "column_order": COL_ORDER,
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"Wrote {OUT}")
    print(json.dumps(out, indent=2, ensure_ascii=False)[:1500])

if __name__ == "__main__":
    main()