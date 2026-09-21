import io,re,sys,json
sys.stdout.reconfigure(encoding='utf-8')
s=io.open('data.js',encoding='utf-8').read()
out=[]
for m in re.finditer(r'\{[^{}]*"platform": "finebi"[^{}]*\}', s):
    blk=m.group(0)
    i=blk.find('"id"'); 
    idm=re.search(r'"(?:id|key|code|page)"\s*:\s*"([^"]+)"', blk)
    um=re.search(r'"url"\s*:\s*"([^"]+)"', blk)
    out.append((idm.group(1) if idm else '?', um.group(1) if um else '?'))
io.open('_fb_list.txt','w',encoding='utf-8').write('\n'.join('%s -> %s'%(a,b) for a,b in out))
