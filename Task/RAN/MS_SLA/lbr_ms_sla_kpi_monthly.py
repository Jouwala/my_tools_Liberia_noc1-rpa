# -*- coding: utf-8 -*-
"""
MS SLA KPI 月度数据导入脚本
功能：
  1. 从Downloads文件夹查找最新的 KPI_RPA_SITE_MS_SLA_*1month_* xlsx文件
  2. 读取每个文件写入SQLite数据库 lbr_ms_sla_kpi.sqlite3
     表名为文件名前加 "Hourly_"
  3. 上传数据库到FTP /01_RPA/LBR_Tools/KPI/MS_SLA
  4. 删除本地已处理的xlsx文件
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
FILE_PREFIXES = [
    "KPI_RPA_SITE_MS_SLA_GSM1month_SITE",
    "KPI_RPA_SITE_MS_SLA_UMTS1month_SITE",
    "KPI_RPA_SITE_MS_SLA_FDD1month_SITE",
    "KPI_RPA_SITE_MS_SLA_GSM1month_NW",
    "KPI_RPA_SITE_MS_SLA_UMTS1month_NW",
    "KPI_RPA_SITE_MS_SLA_FDD1month_NW",
]

DOWNLOADS_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

# 数据库保存路径（当前脚本所在目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = "lbr_ms_sla_kpi.sqlite3"
DB_PATH = os.path.join(SCRIPT_DIR, DB_NAME)

# FTP 配置
FTP_HOST = "192.168.100.19"
FTP_USER = "ZTEEMS"
FTP_PASS = "DX"
FTP_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI/MS_SLA"

# SQLite 批量插入大小（大文件优化）
BATCH_SIZE = 2000


def find_latest_xlsx(prefix):
    """在Downloads目录中查找匹配前缀的最新xlsx文件"""
    pattern = os.path.join(DOWNLOADS_DIR, f"{prefix}*.xlsx")
    files = glob.glob(pattern)
    # 排除临时文件
    files = [f for f in files if not os.path.basename(f).startswith("~$")]
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def read_xlsx_streaming(filepath):
    """
    流式读取xlsx文件，返回 (headers, data)。
    先将文件读入内存再解析，避免长时间持有文件句柄。
    使用 read_only 模式 + data_only 减少内存开销。
    """
    with open(filepath, 'rb') as f:
        file_bytes = f.read()

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    try:
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)

        # 读取表头
        header_row = next(rows_iter)
        headers = [str(col).strip() if col is not None else f"col_{i}"
                   for i, col in enumerate(header_row)]

        # 收集数据行（跳过全空行）
        data = []
        for row in rows_iter:
            if all(v is None for v in row):
                continue
            data.append(list(row))
    finally:
        wb.close()

    del file_bytes
    return headers, data


def write_to_db(db_path, table_name, headers, data):
    """
    将数据写入SQLite数据库（大文件优化版）。
    - WAL journal mode 提升并发写入性能
    - 大事务批量提交，减少磁盘 I/O
    - 全量替换策略（DROP + CREATE）
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 性能优化 PRAGMA
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=OFF")
    cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
    cursor.execute("PRAGMA temp_store=MEMORY")

    # 检查表是否存在，存在则先删除（全量替换策略）
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    if cursor.fetchone():
        cursor.execute(f'DROP TABLE "{table_name}"')

    # 建表：所有列 TEXT 类型
    col_defs = ", ".join(
        f'"{h.replace(chr(34), chr(34)+chr(34))}" TEXT' for h in headers
    )
    cursor.execute(f'CREATE TABLE "{table_name}" ({col_defs})')

    # 批量插入
    quoted_headers = [f'"{h.replace(chr(34), chr(34)+chr(34))}"' for h in headers]
    placeholders = ", ".join(["?"] * len(headers))
    insert_sql = (
        f'INSERT INTO "{table_name}" '
        f'({", ".join(quoted_headers)}) VALUES ({placeholders})'
    )

    row_count = 0
    batch = []
    for row in data:
        # 补齐列数
        if len(row) < len(headers):
            row.extend([None] * (len(headers) - len(row)))
        elif len(row) > len(headers):
            row = row[:len(headers)]

        str_row = [str(v) if v is not None else None for v in row]
        batch.append(str_row)
        row_count += 1

        if len(batch) >= BATCH_SIZE:
            cursor.executemany(insert_sql, batch)
            batch.clear()

    if batch:
        cursor.executemany(insert_sql, batch)

    conn.commit()

    # 建索引：对第一列（通常是时间列）建索引加速查询
    if headers:
        first_col = headers[0].replace('"', '""')
        try:
            cursor.execute(
                f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_{first_col}" '
                f'ON "{table_name}" ("{first_col}")'
            )
            conn.commit()
        except Exception:
            pass

    conn.close()
    return row_count


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

            # 使用绝对路径逐级导航
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


def main():
    print(f"Downloads: {DOWNLOADS_DIR}")
    print(f"DB: {DB_PATH}")
    print("=" * 60)

    total_imported = 0
    files_to_delete = []

    for prefix in FILE_PREFIXES:
        table_name = f"Hourly_{prefix}"
        print(f"\n[{prefix}]")

        filepath = find_latest_xlsx(prefix)
        if not filepath:
            print(f"  not found, skip")
            continue

        files_to_delete.append(filepath)
        print(f"  file: {os.path.basename(filepath)}")

        # 读取
        t0 = time.time()
        headers, data = read_xlsx_streaming(filepath)
        t1 = time.time()
        print(f"  read: {len(data)} rows, {len(headers)} cols ({t1-t0:.1f}s)")

        # 写入数据库
        t2 = time.time()
        row_count = write_to_db(DB_PATH, table_name, headers, data)
        t3 = time.time()
        print(f"  written: {row_count} rows -> {table_name} ({t3-t2:.1f}s)")
        total_imported += row_count

        # 立即释放大对象
        headers = None
        data = None
        gc.collect()

    # ---- FTP 上传已移除（数据通过 API 写入远程） ----
    print("\n[INFO] FTP 上传已移除，数据由 my_app API 写入远程")

    # ---- 清理所有匹配的xlsx文件（包括历史版本） ----
    print("\n[cleanup]")

    all_files = set(files_to_delete)
    for prefix in FILE_PREFIXES:
        pattern = os.path.join(DOWNLOADS_DIR, f"{prefix}*.xlsx")
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

    # 对锁定文件用 PowerShell 强制删除
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
