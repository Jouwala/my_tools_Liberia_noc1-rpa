src=open('frontend/src/pages/MsContractKpiReport.tsx',encoding='utf-8').read().split('\n')
for i in range(352,392): print(str(i+1)+' '+src[i].replace("\t","  "))
