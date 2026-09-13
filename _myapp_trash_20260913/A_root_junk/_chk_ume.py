# -*- coding: utf-8 -*-
"""验证：用 relatedAlarms/table 的 aid 查 RAN UME 是否命中。"""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from backend.services.ran_ume import ran_ume_alarm_service as ume

for aid in ("1639656429564", "1789054360535"):
    res = ume.lookup_alarm(aid, days=30, limit=20, with_history=False)
    print(f"=== lookup_alarm({aid}) ok={res.get('ok')} mode={res.get('mode')}")
    print("  error:", res.get("error"))
    al = res.get("alarm") or {}
    print("  alarm:", {k: al.get(k) for k in ("alarmcode","restype","title_en","code_name","raised_time")})
    sug = res.get("suggestion")
    if res.get("suggestion_error"):
        print("  suggestion_error:", res.get("suggestion_error"))
    print("  suggestion:", sug)
    print()