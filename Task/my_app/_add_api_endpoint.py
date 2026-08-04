# -*- coding: utf-8 -*-
"""给 db_writer_api.py 添加 /api/read 端点"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

with open(r'D:\01_RPA\Task\data_base\db_writer_api.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Check if endpoint already exists
if '/api/read' in content and 'def read_table' in content:
    print("Endpoint already exists, skipping.")
    sys.exit(0)

# Find the insertion point (before if __name__ == "__main__")
marker = '\nif __name__ == "__main__":'
idx = content.find(marker)

if idx <= 0:
    print("ERROR: Could not find insertion point")
    sys.exit(1)

new_endpoint = '''
@app.post("/api/read")
def read_table(payload: dict):
    """读取表格数据（SELECT 查询）"""
    import sqlite3
    
    db = payload.get("db", "")
    table = payload.get("table", "")
    columns = payload.get("columns", [])
    limit = min(int(payload.get("limit", 10000)), 100000)
    where = payload.get("where", "")
    order_by = payload.get("order_by", "")
    
    db_path = _get_db_path(db)
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail=f"Database not found: {db}")
    
    # Build SQL query
    col_clause = ", ".join(columns) if columns else "*"
    sql = f'SELECT {col_clause} FROM "{table}"'
    
    if where:
        sql += f" WHERE {where}"
    
    if order_by:
        sql += f" ORDER BY {order_by}"
    
    sql += f" LIMIT {limit}"
    
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        cursor.execute(sql)
        
        # Get column names
        col_names = [description[0] for description in cursor.description] if cursor.description else []
        
        # Get all rows
        rows = cursor.fetchall()
        conn.close()
        
        return {
            "success": True,
            "columns": col_names,
            "rows": [list(row) for row in rows],
            "count": len(rows)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

'''

# Insert before the marker
content = content[:idx] + new_endpoint + content[idx:]

with open(r'D:\01_RPA\Task\data_base\db_writer_api.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Successfully added /api/read endpoint")
print(f"File size: {len(content)} bytes")
