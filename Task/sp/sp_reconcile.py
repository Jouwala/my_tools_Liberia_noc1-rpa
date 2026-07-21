import pandas as pd
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')

df_in  = pd.read_excel(os.path.join(DATA_DIR, 'spinbound.xlsx'))
df_out = pd.read_excel(os.path.join(DATA_DIR, 'spoutbound.xlsx'))
df_inv = pd.read_excel(os.path.join(DATA_DIR, 'spinventory.xlsx'))

in_col  = 'Inbound Qty'
out_col = 'Outbound Qty'
stk_col = 'Stock Qty'

print('='*60)
print('         差异精确排查')
print('='*60)

# ── 1. 按 Status 过滤 ──
print('\n【1】按 Status 过滤对比')
in_closed  = df_in[df_in['Status'] == 'Closed']
out_closed = df_out[df_out['Status'] == 'Closed']

print(f'  入库 Closed 数量: {in_closed[in_col].sum()}  (全部: {df_in[in_col].sum()})')
print(f'  出库 Closed 数量: {out_closed[out_col].sum()}  (全部: {df_out[out_col].sum()})')
print(f'  Closed入库 - Closed出库 = {in_closed[in_col].sum() - out_closed[out_col].sum()}')
print(f'  实际库存: {df_inv[stk_col].sum()}')

# ── 2. 未关闭入库详情 ──
print('\n【2】未关闭入库工单 (WaitingForVerify)')
in_open = df_in[df_in['Status'] != 'Closed']
print(f'  条数: {len(in_open)}, 数量: {in_open[in_col].sum()}')
print(in_open[['Inbound No.', 'Inbound Type', 'Material No.', 'Serial No.', in_col, 'Status']].to_string(index=False))

# ── 3. 未关闭出库详情 ──
print('\n【3】未关闭出库工单分布')
out_open = df_out[df_out['Status'] != 'Closed']
print(f'  总条数: {len(out_open)}, 总数量: {out_open[out_col].sum()}')
for status, grp in out_open.groupby('Status'):
    print(f'\n  [{status}] 条数={len(grp)}, 数量={grp[out_col].sum()}')
    for otype, ogrp in grp.groupby('Outbound Type'):
        print(f'    - {otype}: {ogrp[out_col].sum()}')

# ── 4. 按 Serial No. 交叉比对 ──
print('\n【4】按 Serial No. 交叉比对')
in_sns  = set(df_in['Serial No.'].dropna().astype(str))
out_sns = set(df_out['Serial No.'].dropna().astype(str))
inv_sns = set(df_inv['Serial No.'].dropna().astype(str))

# 在库存中但从未出现在入库表
in_inv_not_inbound = inv_sns - in_sns
print(f'  库存中有、但入库表没有的 SN: {len(in_inv_not_inbound)} 个')
if in_inv_not_inbound:
    inv_only = df_inv[df_inv['Serial No.'].astype(str).isin(in_inv_not_inbound)]
    print(f'  涉及库存数量: {inv_only[stk_col].sum()}')
    print(inv_only[['Serial No.', 'Material No.', 'Material Name', stk_col, 'Warehouse Name']].head(20).to_string(index=False))

# 在出库中但从未出现在入库表
out_not_in = out_sns - in_sns
print(f'\n  出库中有、但入库表没有的 SN: {len(out_not_in)} 个')
if out_not_in:
    out_only = df_out[df_out['Serial No.'].astype(str).isin(out_not_in)]
    print(f'  涉及出库数量: {out_only[out_col].sum()}')

# 在入库中但不在库存中(且不在出库中)
in_not_inv_not_out = in_sns - inv_sns - out_sns
print(f'\n  入库中有、库存和出库都没有的 SN: {len(in_not_inv_not_out)} 个')
if in_not_inv_not_out:
    in_only = df_in[df_in['Serial No.'].astype(str).isin(in_not_inv_not_out)]
    print(f'  涉及入库数量: {in_only[in_col].sum()}')

# ── 5. 按 Material Type 对账 ──
print('\n【5】按 Material Type 对账')
in_by_type  = df_in.groupby('Material Type')[in_col].sum()
out_by_type = df_out.groupby('Material Type')[out_col].sum()
inv_by_type = df_inv.groupby('Material Type')[stk_col].sum()
all_types = sorted(set(in_by_type.index) | set(out_by_type.index) | set(inv_by_type.index))
print(f'{"Material Type":<15} {"Inbound":>10} {"Outbound":>10} {"In-Out":>10} {"Inventory":>10} {"差异":>8}')
print('-'*65)
total_diff = 0
for t in all_types:
    i = int(in_by_type.get(t, 0))
    o = int(out_by_type.get(t, 0))
    s = int(inv_by_type.get(t, 0))
    diff = s - (i - o)
    total_diff += diff
    print(f'{t:<15} {i:>10} {o:>10} {i-o:>10} {s:>10} {diff:>8}')
print('-'*65)
print(f'{"合计":<15} {int(in_by_type.sum()):>10} {int(out_by_type.sum()):>10} {int(in_by_type.sum()-out_by_type.sum()):>10} {int(inv_by_type.sum()):>10} {total_diff:>8}')
