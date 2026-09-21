import json,datetime,collections
p=r"C:\Users\ZTEEMS\.codex\sessions\2026\09\21\rollout-2026-09-21T09-41-09-01a0c357-3e7a-7222-8f89-1b2c48b5f9ed.jsonl"
def P(s): return datetime.datetime.fromisoformat(s.replace("Z","+00:00"))
recs=[]
with open(p,encoding="utf-8") as f:
    for ln in f:
        ln=ln.strip()
        if not ln: continue
        try: recs.append(json.loads(ln))
        except: pass
print("records",len(recs))
# count by top-level type
print(collections.Counter(r.get("type") for r in recs))
