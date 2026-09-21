import json,datetime,collections
p=r"C:\Users\ZTEEMS\.codex\sessions\2026\09\21\rollout-2026-09-21T09-41-09-01a0c357-3e7a-7222-8f89-1b2c48b5f9ed.jsonl"
def P(s): return datetime.datetime.fromisoformat(s.replace("Z","+00:00"))
recs=[json.loads(l) for l in open(p,encoding="utf-8") if l.strip()]
meta=[r for r in recs if r.get("type")=="session_meta"][0]
print(json.dumps(meta,ensure_ascii=False)[:1500])
