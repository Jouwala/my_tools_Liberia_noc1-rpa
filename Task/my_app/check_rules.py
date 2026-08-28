import pandas as pd
import sys

sys.stdout.reconfigure(encoding='utf-8')

df = pd.read_excel('eflow_TT_rules.xlsx')

print('=' * 80)
print('eFlow TT Rules - Complete Data')
print('=' * 80)
print(f'Total rules: {len(df)}')
print()

# 显示所有列名
print('Columns:', list(df.columns))
print()

# 显示详细数据
for idx, row in df.iterrows():
    print('-' * 80)
    print(f"ID: {row['ID']}")
    print(f"Rule Name: {row['规则名称']}")
    print(f"Rule Type: {row['规则类型']}")
    print(f"WO Type: {row['工单类型']}")
    print(f"Severity Level: {row['严重级别']}")
    print(f"Trigger Step: {row['触发步骤']}")
    print(f"Description: {row['描述']}")
    print(f"Status: {row['状态']}")
    print(f"Priority: {row['优先级']}")
    print(f"Create By: {row['创建人']}, Time: {row['创建时间']}")
    print(f"Update By: {row['更新人']}, Time: {row['更新时间']}")
    if row['条件']:
        cond = row['条件'][:300] + '...' if len(row['条件']) > 300 else row['条件']
        print(f"Conditions:\n{cond}")
    print()

print('=' * 80)
print("Excel file saved to: eflow_TT_rules.xlsx")
print('=' * 80)
