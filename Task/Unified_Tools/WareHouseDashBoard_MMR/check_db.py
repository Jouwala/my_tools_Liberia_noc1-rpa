import sqlite3

conn = sqlite3.connect("inventory.db")
cursor = conn.cursor()

print("=== woType values in ocrule_details ===")
cursor.execute("SELECT DISTINCT woType FROM ocrule_details")
types = cursor.fetchall()
for t in types:
    print(f"  - '{t[0]}'")

print("\n=== triggerStep values in ocrule_details ===")
cursor.execute("SELECT DISTINCT triggerStep FROM ocrule_details")
steps = cursor.fetchall()
for s in steps:
    print(f"  - '{s[0]}'")

print("\n=== Sample data (first 3 rows) ===")
cursor.execute("SELECT * FROM ocrule_details LIMIT 3")
rows = cursor.fetchall()
col_names = [desc[0] for desc in cursor.description]
for row in rows:
    print("-" * 50)
    for i, col in enumerate(col_names):
        print(f"  {col}: {row[i]}")

conn.close()
