import io
s=io.open("MsPortal 商用就绪度检测 —— 结论与整改方案.md",encoding="utf-8").read().splitlines()
for i,l in enumerate(s[65:88],66):
    print('%4d %s'%(i,l))
