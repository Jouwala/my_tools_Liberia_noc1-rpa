"""
my_app 最小可运行压缩包生成脚本
输出：d:\\01_RPA\\Task\\my_app_minimal.zip
"""
import zipfile
import os
import time
from pathlib import Path

start_time = time.time()

SRC = Path(r'd:\01_RPA\Task\my_app')
OUT = Path(r'd:\01_RPA\Task\my_app_minimal.zip')

# 如果文件被占用，自动加序号
if OUT.exists():
    try:
        OUT.unlink()
    except PermissionError:
        i = 1
        while True:
            OUT = Path(r'd:\01_RPA\Task') / f'my_app_minimal_{i}.zip'
            if not OUT.exists():
                break
            i += 1

# ── 排除规则 ──
EXCLUDE_DIRS = {
    '__pycache__', 'node_modules', 'dist', 'dist_test', 'dist_rebuild',
    '.venv', '.git', 'TMP', 'debug', 'uploads', 'sla_exports', 'exports',
    'reports', '.pytest_cache', '.venv-test',
}
EXCLUDE_FILES = {
    '_patch.py', '_zip.py', 'dashboard_data.json',
    'app.db', 'app.db-shm', 'app.db-wal',
    'api_test_result.json', 'TTWODashboard - Copy.tsx',
    '_check_db.py', 'ftp_sync.py',
}
EXCLUDE_EXTS = {'.pyc', '.pyo', '.db', '.sqlite3', '.bak', '.log', '.png', '.jpg', '.jpeg', '.gif'}
EXCLUDE_SUFFIX = ('-shm', '-wal')
EXCLUDE_DIR_PATHS = ['backend/data', 'data/eflow', 'data/ran_ume', 'data/site_outage', 'data/_remote_kpi']


def norm(p: str) -> str:
    return p.replace(os.sep, '/')


def should_exclude(fp: Path, rel: str) -> bool:
    rel_n = norm(rel)
    name = fp.name
    # 目录名匹配
    for part in Path(rel_n).parts:
        if part in EXCLUDE_DIRS:
            return True
    # 文件名精确排除
    if name in EXCLUDE_FILES:
        return True
    # 扩展名排除
    if fp.suffix.lower() in EXCLUDE_EXTS:
        return True
    # 后缀排除
    for s in EXCLUDE_SUFFIX:
        if name.endswith(s):
            return True
    # 运行时数据目录排除
    for dp in EXCLUDE_DIR_PATHS:
        if rel_n.startswith(dp + '/') or rel_n == dp:
            return True
    # 根目录下的 zip 排除
    if name.endswith('.zip') and fp.parent == SRC:
        return True
    # db/ 下的 Copy 文件排除
    if rel_n.startswith('db/') and 'Copy' in name:
        return True
    # data/ms_sla/ 仅保留 KPI list - Operation.xlsx
    if rel_n.startswith('data/ms_sla/') and 'KPI list - Operation' not in name:
        return True
    return False


# ── 打包 ──
count = 0
with zipfile.ZipFile(str(OUT), 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        root_rel = norm(str(Path(root).relative_to(SRC)))
        if root_rel.startswith('backend'):
            dirs[:] = [d for d in dirs if d != 'data']
        for f in files:
            fp = Path(root) / f
            rel = str(fp.relative_to(SRC))
            if should_exclude(fp, rel):
                continue
            arcname = 'my_app/' + norm(rel)
            zf.write(str(fp), arcname)
            count += 1

size_mb = OUT.stat().st_size / 1024 / 1024
elapsed = time.time() - start_time
print(f'输出: {OUT}')
print(f'文件数: {count}, 大小: {size_mb:.2f} MB')
print(f'耗时: {elapsed:.1f} 秒')
