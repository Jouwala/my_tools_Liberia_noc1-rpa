import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')
DB_PATH = r"C:\FineBI6.0\webapps\Python\Unified_Tools\WareHouseDashBoard\inventory.db"
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
for tbl in ['inband_details', 'outband_details', 'inventory_details']:
    cur.execute(f'PRAGMA table_info("{tbl}")')
    cols = [c[1] for c in cur.fetchall()]
    cur.execute(f'SELECT COUNT(*) FROM "{tbl}"')
    cnt = cur.fetchone()[0]
    print(f"\n[{tbl}] {cnt} rows")
    print(f"  columns: {cols}")
    cur.execute(f'SELECT "Serial No." FROM "{tbl}" LIMIT 3')
    print(f"  SN sample: {[r[0] for r in cur.fetchall()]}")
conn.close()
