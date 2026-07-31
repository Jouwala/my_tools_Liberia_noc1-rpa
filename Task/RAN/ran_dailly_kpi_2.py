# -*- coding: utf-8 -*-
"""
RAN Monthly KPI 数据导入脚本 (2026-06)
功能：
  1. 从Downloads文件夹查找最新的OLIB Network KPIs xlsx文件（_NW和_Region两类）
  2. 对_NW文件增加Group列(值为G_NW)，与对应_Region文件合并后写入SQLite数据库
  3. 以 Begin Time + Group 为key进行替换/更新
  4. 上传数据库到FTP
  5. 删除本地已处理的xlsx文件
"""

import os
import gc
import sys
import glob
import time
import io
import subprocess
import sqlite3
import openpyxl
import warnings
from ftplib import FTP, error_perm

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# 忽略openpyxl的UserWarning
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# 修复 Windows CMD 下中文输出编码问题
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============================================================
# 配置
# ============================================================
TECHS = ["2G", "3G", "FDD", "TDD"]

DOWNLOADS_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

# 数据库保存路径（当前脚本所在目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "ran_kpi_202606.sqlite3")

# FTP 配置
FTP_HOST = "192.168.100.19"
FTP_USER = "ZTEEMS"
FTP_PASS = "DX"
FTP_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI/RAN"

# 上传时的文件名
UPLOAD_DB_NAME = "ran_kpi_daily_202606.sqlite3"

# 文件匹配列表
FILE_PATTERNS = [
    "TDD OLIB Network KPIs_NW",
    "TDD OLIB Network KPIs_Region",
    "FDD OLIB Network KPIs_NW",
    "FDD OLIB Network KPIs_Region",
    "3G OLIB Network KPIs_NW",
    "3G OLIB Network KPIs_Region",
    "2G OLIB Network KPIs_NW",
    "2G OLIB Network KPIs_Region",
]


def find_latest_xlsx(pattern_prefix):
    """在Downloads目录中查找匹配前缀的最新xlsx文件"""
    pattern = os.path.join(DOWNLOADS_DIR, f"{pattern_prefix}*.xlsx")
    files = glob.glob(pattern)
    # 排除临时文件
    files = [f for f in files if not os.path.basename(f).startswith("~$")]
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def read_xlsx(filepath):
    """读取xlsx文件，返回列名和数据行列表。先读入内存再解析，避免长时间持有文件句柄。"""
    with open(filepath, 'rb') as f:
        file_bytes = f.read()

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
    try:
        ws = wb.active

        rows_iter = ws.iter_rows(values_only=True)
        headers = [str(col).strip() if col is not None else f"col_{i}"
                   for i, col in enumerate(next(rows_iter))]

        data = []
        for row in rows_iter:
            if all(v is None for v in row):
                continue
            data.append(list(row))
    finally:
        wb.close()
    return headers, data


def upload_to_ftp(local_path, remote_dir, filename, max_retries=2):
    """上传文件到 FTP 服务器（带重试机制）"""
    for attempt in range(1, max_retries + 1):
        print(f"  [FTP] 连接 {FTP_HOST} ...（第 {attempt} 次）")
        ftp = None
        try:
            ftp = FTP(FTP_HOST, timeout=30)
            ftp.encoding = "utf-8"
            if attempt > 1:
                ftp.set_debuglevel(1)
            ftp.login(FTP_USER, FTP_PASS)
            print(f"  登录成功: {FTP_USER}")

            ftp.cwd("/")
            parts = remote_dir.strip("/").split("/")
            for i in range(len(parts)):
                abs_path = "/" + "/".join(parts[:i + 1])
                try:
                    ftp.cwd(abs_path)
                except error_perm:
                    try:
                        ftp.mkd(abs_path)
                        ftp.cwd(abs_path)
                    except error_perm as e2:
                        print(f"  [WARNING] 无法创建目录 {abs_path}: {e2}")

            current_dir = ftp.pwd()
            print(f"  远程目录: {current_dir}")
            expected = "/" + "/".join(parts)
            if current_dir != expected:
                print(f"  [WARNING] 目录不匹配，期望 {expected}，实际 {current_dir}")
                ftp.cwd(expected)

            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {filename}", f)

            print(f"  [OK] 已上传: {filename}")
            ftp.quit()
            return True
        except Exception as e:
            print(f"  [ERROR] FTP 上传失败: {e}")
            if ftp:
                try:
                    ftp.close()
                except Exception:
                    pass
    return False


def write_to_db(db_path, table_name, headers, data):
    """
    将数据写入SQLite数据库。
    以 'Begin Time' 和 'Group' 列为联合主键，使用 INSERT OR REPLACE 实现更新/替换。
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    if "Begin Time" not in headers or "Group" not in headers:
        print(f"  [警告] 表 {table_name} 缺少 'Begin Time' 或 'Group' 列，跳过。")
        conn.close()
        return 0

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    table_exists = cursor.fetchone() is not None

    if not table_exists:
        create_sql = (
            f'CREATE TABLE "{table_name}" (\n'
            f'  "Begin Time" TEXT NOT NULL,\n'
            f'  "Group" TEXT NOT NULL,\n'
            f'  PRIMARY KEY ("Begin Time", "Group")\n'
            f')'
        )
        cursor.execute(create_sql)

        for h in headers:
            if h in ("Begin Time", "Group"):
                continue
            safe_col = h.replace('"', '""')
            try:
                cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{safe_col}" TEXT')
            except sqlite3.OperationalError:
                pass
    else:
        cursor.execute(f'PRAGMA table_info("{table_name}")')
        existing_cols = {row[1] for row in cursor.fetchall()}
        for h in headers:
            if h not in existing_cols:
                safe_col = h.replace('"', '""')
                try:
                    cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{safe_col}" TEXT')
                except sqlite3.OperationalError:
                    pass

    quoted_headers = [f'"{h.replace(chr(34), chr(34)+chr(34))}"' for h in headers]
    placeholders = ", ".join(["?"] * len(headers))
    insert_sql = (
        f'INSERT OR REPLACE INTO "{table_name}" '
        f'({", ".join(quoted_headers)}) VALUES ({placeholders})'
    )

    row_count = 0
    batch = []
    for row in data:
        if len(row) < len(headers):
            row.extend([None] * (len(headers) - len(row)))
        elif len(row) > len(headers):
            row = row[:len(headers)]

        str_row = []
        for v in row:
            if v is None:
                str_row.append(None)
            else:
                str_row.append(str(v))
        batch.append(str_row)
        row_count += 1

        if len(batch) >= 500:
            cursor.executemany(insert_sql, batch)
            batch.clear()

    if batch:
        cursor.executemany(insert_sql, batch)

    conn.commit()
    conn.close()
    return row_count


def main():
    print(f"Downloads: {DOWNLOADS_DIR}")
    print(f"DB: {DB_PATH}")
    print("=" * 60)

    total_imported = 0
    files_to_delete = []

    for tech in TECHS:
        nw_prefix = f"{tech} OLIB Network KPIs_NW"
        region_prefix = f"{tech} OLIB Network KPIs_Region"
        table_name = f"{tech}_OLIB_Network_KPIs"

        nw_file = find_latest_xlsx(nw_prefix)
        region_file = find_latest_xlsx(region_prefix)

        print(f"\n[{tech}]")

        # ---- 处理 _NW 文件 ----
        nw_headers = None
        nw_data = None
        if nw_file:
            files_to_delete.append(nw_file)
            nw_filename = os.path.basename(nw_file)
            print(f"  _NW: {nw_filename}")
            print(f"  _NW Group: G_NW")

            nw_headers, nw_data = read_xlsx(nw_file)
            print(f"  _NW: {len(nw_data)} rows, {len(nw_headers)} cols")

            # 增加 "Group" 列，值为 "G_NW"
            if "Group" not in nw_headers:
                nw_headers.append("Group")
                for row in nw_data:
                    row.append("G_NW")
            else:
                group_idx = nw_headers.index("Group")
                for row in nw_data:
                    row[group_idx] = "G_NW"
        else:
            print(f"  _NW: not found")

        # ---- 处理 _Region 文件 ----
        rg_headers = None
        rg_data = None
        if region_file:
            files_to_delete.append(region_file)
            rg_filename = os.path.basename(region_file)
            print(f"  _Region: {rg_filename}")

            rg_headers, rg_data = read_xlsx(region_file)
            print(f"  _Region: {len(rg_data)} rows, {len(rg_headers)} cols")

            # _Region文件保持原有Group列，若无则不强制添加
        else:
            print(f"  _Region: not found")

        # ---- 合并写入 ----
        if nw_headers is None and rg_headers is None:
            print(f"  [skip] no files found")
            continue

        # 合并列头（取并集，保持顺序）
        if nw_headers and rg_headers:
            merged_headers = list(nw_headers)
            for h in rg_headers:
                if h not in merged_headers:
                    merged_headers.append(h)
        elif nw_headers:
            merged_headers = list(nw_headers)
        else:
            merged_headers = list(rg_headers)

        # 构建合并数据
        merged_data = []

        if nw_headers and nw_data:
            for row in nw_data:
                new_row = []
                while len(row) < len(nw_headers):
                    row.append(None)
                for h in merged_headers:
                    if h in nw_headers:
                        new_row.append(row[nw_headers.index(h)])
                    else:
                        new_row.append(None)
                merged_data.append(new_row)

        if rg_headers and rg_data:
            for row in rg_data:
                new_row = []
                while len(row) < len(rg_headers):
                    row.append(None)
                for h in merged_headers:
                    if h in rg_headers:
                        new_row.append(row[rg_headers.index(h)])
                    else:
                        new_row.append(None)
                merged_data.append(new_row)

        print(f"  merged: {len(merged_data)} rows, {len(merged_headers)} cols -> {table_name}")

        row_count = write_to_db(DB_PATH, table_name, merged_headers, merged_data)
        print(f"  written: {row_count} rows")
        total_imported += row_count

        # 释放大对象
        nw_headers = nw_data = None
        rg_headers = rg_data = None
        merged_headers = merged_data = None
        gc.collect()

    # ---- FTP 上传已移除（数据通过 API 写入远程） ----
    print("\n[INFO] FTP 上传已移除，数据由 my_app API 写入远程")

    # ---- 清理已导入的xlsx文件 ----
    print("\n[cleanup]")

    all_files = set(files_to_delete)
    # 同时收集所有匹配的副本（包括历史版本）
    for pattern_name in FILE_PATTERNS:
        pattern = os.path.join(DOWNLOADS_DIR, f"{pattern_name}*.xlsx")
        for fpath in glob.glob(pattern):
            if not os.path.basename(fpath).startswith("~$"):
                all_files.add(fpath)

    gc.collect()

    deleted_count = 0
    failed_files = []
    for fpath in all_files:
        try:
            os.remove(fpath)
            print(f"  deleted: {os.path.basename(fpath)}")
            deleted_count += 1
        except PermissionError:
            failed_files.append(fpath)
        except Exception as e:
            print(f"  [error] {os.path.basename(fpath)}: {e}")

    # 对锁定文件重试（PowerShell Remove-Item -Force）
    if failed_files:
        print(f"  retrying {len(failed_files)} locked files with PowerShell force...")
        time.sleep(2)
        for fpath in failed_files:
            try:
                subprocess.run(
                    ['powershell', '-Command',
                     f'Remove-Item -Path "{fpath}" -Force -ErrorAction Stop'],
                    capture_output=True, timeout=15,
                    creationflags=_SUBPROCESS_FLAGS,
                )
                if not os.path.exists(fpath):
                    print(f"  deleted (force): {os.path.basename(fpath)}")
                    deleted_count += 1
                else:
                    print(f"  [warn] {os.path.basename(fpath)}: still locked")
                    import ctypes
                    ctypes.windll.kernel32.MoveFileExW(
                        fpath, None, 0x4  # MOVEFILE_DELAY_UNTIL_REBOOT
                    )
            except Exception as e:
                print(f"  [error] {os.path.basename(fpath)}: {e}")

    print(f"  total deleted: {deleted_count} files")

    print("\n" + "=" * 60)
    print(f"Done. total: {total_imported} rows")
    print(f"DB: {DB_PATH}")


if __name__ == "__main__":
    main()
