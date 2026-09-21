import json,datetime,collections
p=r"C:\Users\ZTEEMS\.codex\sessions\2026\09\21\rollout-2026-09-21T09-41-09-01a0c357-3e7a-7222-8f89-1b2c48b5f9ed.jsonl"
def P(s): return datetime.datetime.fromisoformat(s.replace("Z","+00:00"))
recs=[json.loads(l) for l in open(p,encoding="utf-8") if l.strip()]
# turns
ev=[r for r in recs if r.get("type")=="event_msg"]
starts=[r for r in ev if r["payload"]["type"]=="task_started"]
comp=[r for r in ev if r["payload"]["type"]=="task_complete"]
print("nstarts",len(starts),"ncomp",len(comp))
print("first start",starts[0]["timestamp"])
print("turn boundaries:")
for s in starts: print("  START",s["timestamp"])
u=[r for r in recs if r.get("type")=="response_item" and r["payload"].get("type")=="message" and r["payload"].get("role")=="user"]
for x in u:
    c=x["payload"]["content"]
    t="".join(p.get("text","") for p in c if isinstance(p,dict))
    print("USER",x["timestamp"],"|",t[:120].replace(chr(10)," "))
last=recs[-1]["timestamp"]
print("last",last)
tc=collections.Counter()
for r in recs:
    if r.get("type")=="event_msg" and r["payload"].get("type")=="token_count":
        pl=r["payload"].get("info") or {}
        tu=pl.get("total_token_usage") or {}
        for k,v in tu.items():
            if isinstance(v,int): tc[k]=max(tc[k],v)
print("max total_token_usage",dict(tc))
summ=[r for r in recs if r.get("type")=="event_msg" and r["payload"].get("type")=="token_count"]
print("last token_count payload:",json.dumps(summ[-1]["payload"],ensure_ascii=False)[:800])
