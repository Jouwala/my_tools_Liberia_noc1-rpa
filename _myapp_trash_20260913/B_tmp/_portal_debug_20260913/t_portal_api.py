"""临时诊断：通过真实 API 触发 eFlow 一键登录，并把 job 状态/日志完整打印出来。"""
import json
import time

import httpx

c = httpx.Client(trust_env=False, timeout=30)
BASE = "http://127.0.0.1:7038"

r = c.post(f"{BASE}/api/portals/login", json={"system": "eflow"})
print("POST /api/portals/login ->", r.status_code, r.text[:300])
job = r.json().get("job_id")
deadline = time.time() + 90
last = None
while time.time() < deadline:
    s = c.get(f"{BASE}/api/portals/login/status", params={"job_id": job}).json()
    key = (s.get("state"), s.get("message"), len(s.get("log") or []))
    if key != last:
        print(f"[{time.strftime('%H:%M:%S')}] state={s.get('state')} msg={s.get('message')}")
        for line in (s.get("log") or []):
            print("      log:", line)
        last = key
    if s.get("state") in ("success", "failed", "need_manual", "unknown"):
        print("FINAL:", json.dumps(s, ensure_ascii=False, indent=2)[:2000])
        break
    time.sleep(1.5)
