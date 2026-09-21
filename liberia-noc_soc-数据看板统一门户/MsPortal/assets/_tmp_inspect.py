import io,sys,json
sys.stdout.reconfigure(encoding='utf-8')
s=io.open('data.js',encoding='utf-8').read()
lines=s.split('\n')
mark='"platform": "finebi"'
out=[]
for i,l in enumerate(lines,1):
    if mark in l:
        j=i-1
        while j>0 and '"id"' not in lines[j-1]:
            j-=1
        out.append('==== platform line %d id line %d'%(i,j))
        for k in range(j-1,i+2):
            out.append('%d %s'%(k+1, lines[k]))
io.open('_inspect_out.txt','w',encoding='utf-8').write('\n'.join(out))
