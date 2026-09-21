import os
res=[]
for r,d,f in os.walk('.'):
    if 'node_modules' in r or '.git' in r: continue
    for n in f:
        if n.endswith(('.ts','.tsx','.php','.js','.py','.json')):
            p=os.path.join(r,n)
            try: t=open(p,encoding='utf-8',errors='ignore').read()
            except: continue
            if 'glance' in t.lower(): res.append(p)
print('\n'.join(res))
