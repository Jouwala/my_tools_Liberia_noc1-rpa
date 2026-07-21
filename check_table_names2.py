import sqlite3

conn = sqlite3.connect(r'd:\01_RPA\Task\RAN\Avalability\ran_kpi_avalability_1day.sqlite3')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = cursor.fetchall()
print("=== Tables in database ===")
for t in tables:
    count = cursor.execute(f"SELECT COUNT(*) FROM \"{t[0]}\"").fetchone()[0]
    print(f"  [{t[0]}]  {count} rows")
conn.close()
