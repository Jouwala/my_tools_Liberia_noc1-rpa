import pandas as pd
import openpyxl
import sys, os
sys.stdout.reconfigure(encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")

# 用pandas读取
df_inv = pd.read_excel(os.path.join(DATA_DIR, "spinventory.xlsx"))
print("=== pandas 读取 inventory Serial No. 类型和前10个 ===")
print(f"dtype: {df_inv['Serial No.'].dtype}")
print(df_inv['Serial No.'].head(10).tolist())
print(f"转为str后: {df_inv['Serial No.'].astype(str).head(10).tolist()}")

# 用openpyxl读取原始值
wb = openpyxl.load_workbook(os.path.join(DATA_DIR, "spinventory.xlsx"), read_only=True)
ws = wb.active
raw_sns = []
for i, row in enumerate(ws.iter_rows(min_row=2, max_row=11, min_col=1, max_col=1, values_only=True)):
    raw_sns.append((row[0], type(row[0]).__name__))
wb.close()
print(f"\n=== openpyxl 原始值 ===")
for v, t in raw_sns:
    print(f"  {v}  ({t})")

# 检查问题SN：在pandas中的格式
problem_sns = ["W0116LR00002-Monrovia Warehouse_01-0101", "W0116LR00001-Monrovia Warehouse_01-0101", "762605700026"]
print(f"\n=== 检查问题SN在pandas中 ===")
for sn in problem_sns:
    matches = df_inv[df_inv['Serial No.'].astype(str).str.contains(sn, na=False, regex=False)]
    print(f"  搜索 '{sn}': {len(matches)} 条")
    if len(matches) > 0:
        print(f"  实际值: {matches['Serial No.'].iloc[0]}")

# 查看入库表的SN格式
df_in = pd.read_excel(os.path.join(DATA_DIR, "spinbound.xlsx"))
print(f"\n=== inbound Serial No. dtype: {df_in['Serial No.'].dtype} ===")
print(df_in['Serial No.'].astype(str).head(10).tolist())

# 关键检查：pandas float转换问题
test_sn = 762605700026
print(f"\n=== float转换测试 ===")
print(f"  原始int: {test_sn}")
print(f"  float: {float(test_sn)}")
print(f"  str(float): '{str(float(test_sn))}'")
print(f"  int->str: '{str(test_sn)}'")
print(f"  pandas astype(str) of float: {pd.Series([float(test_sn)]).astype(str).iloc[0]}")
