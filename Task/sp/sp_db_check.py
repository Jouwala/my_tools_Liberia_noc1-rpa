"""
诊断 inventory.db 中 Stock Qty 全为 0 的问题
请在数据库所在机器上运行: python sp_db_check.py
"""
import sqlite3
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = r"C:\FineBI6.0\webapps\Python\Unified_Tools\WareHouseDashBoard\inventory.db"

if not os.path.exists(DB_PATH):
    print(f"[错误] 数据库不存在: {DB_PATH}")
    print("请修改脚本顶部的 DB_PATH 为正确路径")
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# ── 1. 查看所有表 ──
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print(f"=== 数据库表列表 ({len(tables)} 个) ===")
for t in tables:
    print(f"  {t}")

# ── 2. 检查三张关键表 ──
for tbl in ['inband_details', 'outband_details', 'inventory_details']:
    if tbl not in tables:
        print(f"\n[警告] 表 {tbl} 不存在！")
        continue
    cur.execute(f'PRAGMA table_info("{tbl}")')
    cols = cur.fetchall()
    cur.execute(f'SELECT COUNT(*) FROM "{tbl}"')
    cnt = cur.fetchone()[0]
    print(f"\n=== {tbl} ({cnt} 行) ===")
    print("  列名:")
    col_names = []
    for c in cols:
        print(f"    {c[1]:30s} {c[2]}")
        col_names.append(c[1])

    # 检查关键列是否存在
    key_cols = ["WarehouseId", "Material No.", "Serial No."]
    for kc in key_cols:
        if kc not in col_names:
            print(f"  [!] 缺少列: {kc}")

    # 检查是否有 Stock Date 列
    if "Stock Date" in col_names:
        cur.execute(f'SELECT MIN("Stock Date"), MAX("Stock Date"), COUNT(DISTINCT "Stock Date") FROM "{tbl}"')
        r = cur.fetchone()
        print(f"  Stock Date 范围: {r[0]} ~ {r[1]} (共 {r[2]} 个不同日期)")

    # 样本数据
    cur.execute(f'SELECT * FROM "{tbl}" LIMIT 3')
    rows = cur.fetchall()
    print(f"  样本数据 (前3行):")
    for row in rows:
        print(f"    {row}")

# ── 3. 核心诊断：JOIN 匹配率 ──
print("\n\n=== 核心诊断：JOIN 匹配率 ===")

# 3a. 检查 inventory 的 Serial No. 格式
if 'inventory_details' in tables:
    cur.execute('SELECT "Serial No." FROM inventory_details LIMIT 10')
    inv_sns = [r[0] for r in cur.fetchall()]
    print(f"\ninventory_details Serial No. 样本:")
    for s in inv_sns:
        print(f"  '{s}'")

if 'inband_details' in tables:
    cur.execute('SELECT "Serial No." FROM inband_details LIMIT 10')
    in_sns = [r[0] for r in cur.fetchall()]
    print(f"\ninband_details Serial No. 样本:")
    for s in in_sns:
        print(f"  '{s}'")

# 3b. 直接测试 JOIN 能匹配多少
print("\n--- JOIN 匹配测试 ---")
try:
    cur.execute("""
    SELECT COUNT(*)
    FROM inband_details i
    INNER JOIN inventory_details inv
      ON i."WarehouseId" = inv."WarehouseId"
      AND i."Material No." = inv."Material No."
      AND i."Serial No." = inv."Serial No."
    """)
    match_cnt = cur.fetchone()[0]
    print(f"入库 INNER JOIN 库存 (无日期过滤): {match_cnt} 行匹配")
except Exception as e:
    print(f"JOIN 失败: {e}")

try:
    cur.execute("""
    SELECT COUNT(*)
    FROM inventory_details inv
    WHERE inv."Stock Date" = (SELECT MAX("Stock Date") FROM inventory_details)
    """)
    inv_latest = cur.fetchone()[0]
    print(f"库存最新日期行数: {inv_latest}")
except Exception as e:
    print(f"日期过滤失败 (可能无 Stock Date 列): {e}")

# 3c. 只用 WarehouseId + Material No. + Serial No. 匹配
try:
    cur.execute("""
    SELECT COUNT(*)
    FROM (SELECT DISTINCT "WarehouseId", "Material No.", "Serial No." FROM inband_details) i
    INNER JOIN (SELECT DISTINCT "WarehouseId", "Material No.", "Serial No." FROM inventory_details) inv
      ON i."WarehouseId" = inv."WarehouseId"
      AND i."Material No." = inv."Material No."
      AND i."Serial No." = inv."Serial No."
    """)
    match_distinct = cur.fetchone()[0]
    print(f"去重后三字段 JOIN: {match_distinct} 组匹配")
except Exception as e:
    print(f"去重JOIN失败: {e}")

# 3d. 只用 Serial No. 匹配
try:
    cur.execute("""
    SELECT COUNT(*)
    FROM (SELECT DISTINCT "Serial No." FROM inband_details) i
    INNER JOIN (SELECT DISTINCT "Serial No." FROM inventory_details) inv
      ON i."Serial No." = inv."Serial No."
    """)
    match_sn = cur.fetchone()[0]
    print(f"仅 Serial No. JOIN: {match_sn} 组匹配")
except Exception as e:
    print(f"SN JOIN 失败: {e}")

conn.close()
print("\n=== 诊断完成 ===")
