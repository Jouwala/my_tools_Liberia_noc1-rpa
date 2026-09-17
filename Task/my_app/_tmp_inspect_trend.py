# -*- coding: utf-8 -*-
import json

with open(r'd:\01_RPA\Task\my_app\data\cxo_dashboard\last_known_good.json', encoding='utf-8') as f:
    cache = json.load(f)
keys = cache.get('keys', {})

for g in (91, 92, 93, 94, 95, 99):
    entry = keys.get('summary/trend_%d' % g)
    if not entry:
        print('trend_%d: MISSING' % g)
        continue
    d = entry.get('data') or {}
    print('=== trend_%d | showName=%s | data_time=%s | fetched_at=%s ===' % (
        g, d.get('showName'), entry.get('data_time'), entry.get('fetched_at')))
    print('xData:', d.get('xData'))
    for s in (d.get('yData') or []):
        print('  series: %s -> %s' % (s.get('name'), s.get('yData')))
    print()

# overview KPI 卡
for oid in (131, 132, 133, 134):
    entry = keys.get('summary/overview_%d' % oid)
    d = (entry or {}).get('data') or {}
    print('overview_%d: %s = %s %s (data_time=%s)' % (
        oid, d.get('showName'), d.get('kpiValue'), d.get('unit'), (entry or {}).get('data_time')))
