import os, glob

# 搜索所有可能的PM导出文件位置
dirs_to_search = [
    r"D:\01_RPA\Task\my_app\backend\services",
    r"D:\01_RPA\Task\my_app\backend\services\exports",
    r"D:\01_RPA\Task\ran_ume",
    os.path.expanduser("~") + r"\Downloads",
]

for d in dirs_to_search:
    if not os.path.exists(d):
        continue
    xlsx_files = sorted(glob.glob(os.path.join(d, "*.xlsx")), key=os.path.getmtime, reverse=True)[:5]
    if xlsx_files:
        print(f"\n{d}:")
        for f in xlsx_files:
            name = os.path.basename(f)
            mtime = os.path.getmtime(f)
            size = os.path.getsize(f)
            print(f"  {name}  ({size} bytes)")

# 也搜索 _find_latest_xlsx 函数使用的路径
print("\n--- Checking ran_ume_service EXPORT_DIR ---")
from backend.services.ran_ume_service import EXPORT_DIR, _find_latest_xlsx
print(f"EXPORT_DIR: {EXPORT_DIR}")
print(f"Exists: {os.path.exists(str(EXPORT_DIR))}")
if os.path.exists(str(EXPORT_DIR)):
    for f in sorted(os.listdir(str(EXPORT_DIR)), reverse=True)[:10]:
        fp = os.path.join(str(EXPORT_DIR), f)
        if os.path.isfile(fp):
            print(f"  {f} ({os.path.getsize(fp)} bytes)")

for tech in ["2G", "3G", "FDD", "TDD"]:
    for suffix in ["NW", "Region"]:
        fname = _find_latest_xlsx(f"{tech} OLIB Network KPIs_{suffix}")
        print(f"  {tech}_{suffix}: {fname}")
