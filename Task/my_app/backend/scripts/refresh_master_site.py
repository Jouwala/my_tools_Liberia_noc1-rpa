# refresh_master_site.py
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中（支持从任意目录运行）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import get_raw_connection
from backend.scripts.init_db import load_excel_to_db, SHEET_TABLE_MAP

excel_path = PROJECT_ROOT / "db" / "ZTE OLR MS Master Site Database.xlsx"
if not excel_path.exists():
    print(f"[ERROR] 文件不存在: {excel_path}")
    sys.exit(1)

print(f"正在导入: {excel_path.name}")
with get_raw_connection() as conn:
    load_excel_to_db(excel_path, "", conn, sheet_map=SHEET_TABLE_MAP)
print("master_site_db 更新完成！")