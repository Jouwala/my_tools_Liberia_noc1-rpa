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

print('=== 数量对比 ===')
total_in  = df_in[in_col].sum()
total_out = df_out[out_col].sum()
total_stk = df_inv[stk_col].sum()
print(f'入库总量   : {total_in}')
print(f'出库总量   : {total_out}')
print(f'当前库存   : {total_stk}')
print(f'入库-出库  : {total_in - total_out}')
print(f'差异(库存-差值): {total_stk - (total_in - total_out)}')

print()
print('=== 入库类型分析 ===')
print(df_in.groupby('Inbound Type')[in_col].sum())

print()
print('=== 出库类型分析 ===')
print(df_out.groupby('Outbound Type')[out_col].sum())

print()
print('=== Borrow Outbound 归还情况 ===')
borrow_out = df_out[df_out['Outbound Type'] == 'Borrow Outbound']
print(f'Borrow出库总数量: {borrow_out[out_col].sum()}')
has_return = borrow_out['Return Detail'].notna().sum()
no_return  = borrow_out['Return Detail'].isna().sum()
print(f'  有归还记录条数: {has_return}')
print(f'  无归还记录条数: {no_return}')
unreturned_qty = borrow_out[borrow_out['Return Detail'].isna()][out_col].sum()
returned_qty   = borrow_out[borrow_out['Return Detail'].notna()][out_col].sum()
print(f'  未归还数量合计: {unreturned_qty}')
print(f'  已归还数量合计: {returned_qty}')

print()
print('=== Repair Outbound 归还情况 ===')
repair_out = df_out[df_out['Outbound Type'] == 'Repair Outbound']
print(f'Repair出库总数量: {repair_out[out_col].sum()}')
repair_has_return = repair_out['Return Detail'].notna().sum()
repair_no_return  = repair_out['Return Detail'].isna().sum()
print(f'  有归还记录条数: {repair_has_return}')
print(f'  无归还记录条数: {repair_no_return}')
repair_unreturned_qty = repair_out[repair_out['Return Detail'].isna()][out_col].sum()
print(f'  未归还数量合计: {repair_unreturned_qty}')

print()
print('=== Others Outbound 分析 ===')
others_out = df_out[df_out['Outbound Type'] == 'Others Outbound']
print(f'Others出库总数量: {others_out[out_col].sum()}')
print('Description 样本:')
print(others_out['Description'].value_counts().head(10))

print()
print('=== 差异拆解 ===')
gain_in = df_in[df_in['Inbound Type'] == 'Inventory Gain Inbound'][in_col].sum()
borrow_return_in = df_in[df_in['Inbound Type'] == 'Borrow Return Inbound'][in_col].sum()
print(f'Inventory Gain Inbound (盘点盈余，增加库存): +{gain_in}')
print(f'Borrow Return Inbound  (借出归还，增加库存): +{borrow_return_in}')
print(f'Borrow Outbound 未归还 (借出在外，应减库存): -{unreturned_qty}')
print(f'Repair Outbound  未归还 (维修在外，应减库存): -{repair_unreturned_qty}')

# 修正公式：库存 = 入库 - 出库 + 借出归还入库(已含在入库中)
# 实际上 Borrow Return Inbound 已经在入库里了，Borrow Outbound 已归还的也通过 Borrow Return Inbound 回来
# 关键：Borrow Outbound 中"未归还"的部分，已经从库存扣减，但通过 Borrow Return Inbound 回来
# 所以差异来自：Others Outbound（退货/处置，不回库） + 数据时间不同步
print()
print('=== 结论 ===')
net_out_non_return = others_out[out_col].sum() + repair_unreturned_qty + unreturned_qty
print(f'出库后不回库的数量估算: {net_out_non_return}')
print(f'理论库存 = 入库({total_in}) - 不回库出库({net_out_non_return}) = {total_in - net_out_non_return}')
print(f'实际库存: {total_stk}')
print(f'剩余差异: {total_stk - (total_in - net_out_non_return)}  (可能来自数据时间差或transfer调拨)')
