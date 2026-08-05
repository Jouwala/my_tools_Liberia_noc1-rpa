import sqlite3

conn = sqlite3.connect("inventory.db")
cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print("=== Tables ===")
for t in tables:
    print(f"  - '{t[0]}'")

for table in tables:
    table_name = table[0]
    print(f"\n=== {table_name} columns ===")
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    for col in columns:
        print(f"  - '{col[1]}'")
    
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cursor.fetchone()[0]
    print(f"  Row count: {count}")

print("\n=== Material Type in inventory_details ===")
cursor.execute("SELECT DISTINCT `Material Type` FROM inventory_details")
types = cursor.fetchall()
for t in types:
    print(f"  - '{t[0]}'")

print("\n=== Type column in inband_details ===")
cursor.execute("PRAGMA table_info(inband_details)")
columns = cursor.fetchall()
for col in columns:
    if 'type' in col[1].lower() or 'Type' in col[1]:
        print(f"  - '{col[1]}'")

cursor.execute("SELECT DISTINCT * FROM inband_details LIMIT 1")
row = cursor.fetchone()
if row:
    col_names = [desc[0] for desc in cursor.description]
    for i, col in enumerate(col_names):
        if 'type' in col.lower() or 'Type' in col:
            print(f"  Found: '{col}'")

print("\n=== Type values in inband_details ===")
cursor.execute("PRAGMA table_info(inband_details)")
columns = cursor.fetchall()
type_col = None
for col in columns:
    if 'type' in col[1].lower() or 'Type' in col[1] or 'whinType' in col[1]:
        type_col = col[1]
        break
if type_col:
    cursor.execute(f"SELECT DISTINCT `{type_col}` FROM inband_details")
    types = cursor.fetchall()
    for t in types:
        print(f"  - '{t[0]}'")

print("\n=== Out Type column in outband_details ===")
cursor.execute("PRAGMA table_info(outband_details)")
columns = cursor.fetchall()
for col in columns:
    if 'type' in col[1].lower() or 'Type' in col[1] or 'whoutType' in col[1]:
        print(f"  - '{col[1]}'")

print("\n=== Out Type values in outband_details ===")
out_type_col = None
for col in columns:
    if 'type' in col[1].lower() or 'Type' in col[1] or 'whoutType' in col[1]:
        out_type_col = col[1]
        break
if out_type_col:
    cursor.execute(f"SELECT DISTINCT `{out_type_col}` FROM outband_details")
    types = cursor.fetchall()
    for t in types:
        print(f"  - '{t[0]}'")

conn.close()
