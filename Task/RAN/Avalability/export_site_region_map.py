"""
将 Master Site Database 中的 Site Name 和 Region 映射提取出来，
添加到 ran_kpi_avalability_1day.sqlite3 中作为新表，方便 FineBI 单连接查询
"""
import sqlite3
import pandas as pd
import time

start_time = time.time()

# 读取 OLR Site Database 获取站点列表
print("Loading OLR Site Database...")
df_site = pd.read_excel(r'd:\01_RPA\Task\OLR Site Database_Jun 2026 v1.xlsx', sheet_name='Sheet5', skiprows=1)
site_names = df_site['Site Name'].dropna().unique()
print(f"Found {len(site_names)} sites in OLR database")

# 假设 Master Site Database 也在某个 Excel 或数据库中
# 这里需要你提供实际的数据源路径
# 示例：如果 Master Site Database 是 Excel
try:
    df_master = pd.read_excel(r'd:\01_RPA\TMP\OLR Site Database_Jun 2026 v1.xlsx', sheet_name='Sheet5', skiprows=1)
    # 确认有 Region 列
    if 'Region' in df_master.columns:
        site_region_map = df_master[['Site Name', 'Region']].dropna()
        print(f"Found {len(site_region_map)} site-region mappings")
        
        # 写入 SQLite
        conn = sqlite3.connect(r'd:\01_RPA\Task\RAN\Avalability\ran_kpi_avalability_1day.sqlite3')
        site_region_map.to_sql('Site_Region_Map', conn, if_exists='replace', index=False)
        print("Site_Region_Map table created successfully!")
        
        # 验证
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM Site_Region_Map")
        count = cur.fetchone()[0]
        print(f"Verified: {count} records in Site_Region_Map")
        conn.close()
    else:
        print("ERROR: 'Region' column not found in Master Site Database")
        print("Available columns:", df_master.columns.tolist())
except Exception as e:
    print(f"Error: {e}")
    print("\n请提供 Master Site Database 的实际文件路径")

elapsed = time.time() - start_time
print(f"\nExecution time: {elapsed:.2f} seconds")
