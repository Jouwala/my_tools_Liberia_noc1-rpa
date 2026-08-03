"""
my_app 精简打包脚本
排除缓存、数据库、临时文件等，生成 my_app_minimal.zip
"""

import zipfile
import os
from pathlib import Path

# ============ 配置区 ============
SRC   = Path(r"d:\01_RPA\Task\my_app")
OUT   = Path(r"d:\01_RPA\Task\my_app_minimal.zip")
ARC_ROOT = "my_app/"          # zip 内顶级目录名

EXCLUDE_DIRS   = {
    "__pycache__", "node_modules", "dist", ".venv", ".git",
    "TMP", "debug", "uploads", "sla_exports", "exports",
    "reports", ".pytest_cache", ".venv-test",
}
EXCLUDE_FILES = {
    "_patch.py", "_zip.py", "dashboard_data.json",
    "app.db", "app.db-shm", "app.db-wal",
    "api_test_result.json",
    "TTWODashboard - Copy.tsx",
    "_check_db.py", "ftp_sync.py",
}
EXCLUDE_EXTS   = {".pyc", ".pyo", ".db", ".sqlite3"}
EXCLUDE_SUFFIX = ("-shm", "-wal")
EXCLUDE_PREFIX = [
    "data\\eflow\\",
    "data\\ran_ume\\",
    "data\\site_outage\\",
    "data\\ms_sla\\WithoutSLA",
    "data\\ms_sla\\ZTE OLR",
    "data\\ms_sla\\lbr_ms_sla",
]

# ============ 主逻辑 ============
def should_exclude(p: Path, rel: str) -> bool:
    """判断文件是否应被排除"""
    rel_win = rel.replace("/", "\\")

    # 目录名匹配
    if any(part in EXCLUDE_DIRS for part in p.parts):
        return True
    # 文件名匹配
    if p.name in EXCLUDE_FILES:
        return True
    # 扩展名匹配
    if p.suffix.lower() in EXCLUDE_EXTS:
        return True
    # 后缀匹配（如 app.db-shm）
    if any(rel_win.endswith(s) for s in EXCLUDE_SUFFIX):
        return True
    # 路径前缀匹配
    if any(rel_win.startswith(pre) for pre in EXCLUDE_PREFIX):
        return True
    # 根目录下多余的 zip/log 文件
    if p.name.endswith((".zip", ".log")) and p.parent == SRC:
        return True
    return False


def resolve_output_path(out: Path) -> Path:
    """自动处理同名冲突（避免 PermissionError）"""
    if not out.exists():
        return out
    i = 1
    while True:
        candidate = out.parent / f"{out.stem}_mini_{i}{out.suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def main():
    out_path = resolve_output_path(OUT)
    count = 0

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(SRC):
            # 裁剪目录树：直接剔除被排除的目录
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for f in files:
                fp = Path(root) / f
                rel = str(fp.relative_to(SRC))

                if should_exclude(fp, rel):
                    continue

                # data/ms_sla 特殊处理：仅保留 KPI list
                rel_win = rel.replace("/", "\\")
                if rel_win.startswith("data\\ms_sla\\"):
                    if "KPI list - Operation" not in f:
                        continue

                arcname = ARC_ROOT + rel.replace("\\", "/")
                zf.write(str(fp), arcname)
                count += 1

    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"Done: {out_path}")
    print(f"Files: {count}, Size: {size_mb:.2f} MB")


if __name__ == "__main__":
    main()
