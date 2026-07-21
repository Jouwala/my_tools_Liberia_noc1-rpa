"""诊断：对比 API 原始数据与 Excel 输出"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'd:\01_RPA\Site_outage')
import fetch_site_outage_v2 as m

m.login()

BASE = "/api/alarmstatistics-service/v1/levelregion"

# 检查所有 API 的原始返回
apis = [
    ("Logical Site", f"{BASE}/getRegionSiteDataTable", "GET"),
    ("Logical Cell", f"{BASE}/getRegionCellDataTable", "GET"),
    ("Physical Site", f"{BASE}/getCountRepetitionSiteDown", "GET"),
    ("Logical Total", f"{BASE}/getBorDataByVendor", "GET"),
    ("Physical Site Map", f"{BASE}/getCountRepetitionSiteDownToMap", "GET"),
    ("Site Class Statistics", f"{BASE}/getSiteDownStatisticOfClass", "GET"),
    ("Mains Fail Duration", f"{BASE}/getMainsFailOfDuration", "POST"),
    ("Logical Site Outages Hour", f"{BASE}/getCountSiteDownToHour", "POST"),
]

for name, path, method in apis:
    print(f"\n{'='*60}")
    print(f"[{name}]")
    print(f"{'='*60}")
    for st in ["ALL", "ERA", "REGULAR"]:
        data = m.fetch_data(st, path, method)
        rows = m.parse_response(data, st)
        if isinstance(rows, dict):
            print(f"  {st}: {json.dumps(rows, ensure_ascii=False)}")
        elif isinstance(rows, list):
            print(f"  {st}: {len(rows)} records, sample={json.dumps(rows[:2], ensure_ascii=False)}")
        else:
            print(f"  {st}: {rows}")
