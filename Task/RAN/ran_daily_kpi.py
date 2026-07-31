"""
RAN Daily KPI 数据导入脚本
功能：从Downloads文件夹中查找最新的OLIB Network KPIs xlsx文件（_NW和_Group两类），
      对_NW文件增加Group列，与对应_Group文件合并后写入SQLite数据库，
      以 Begin Time + Group 为key进行替换/更新。
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

# 修复 Windows CMD 下中文输出编码问题（代码页936=GBK无法输出中文时强制使用UTF-8）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 技术制式列表
TECHS = ["2G", "3G", "FDD", "TDD"]

# 下载文件夹路径
DOWNLOADS_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

# 数据库保存路径（当前脚本所在目录）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "ran_kpi_daily.sqlite3")

# FTP 配置
FTP_HOST = "192.168.100.19"
FTP_USER = "ZTEEMS"
FTP_PASS = "DX"
FTP_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI/RAN"


def find_latest_xlsx(pattern_prefix):
    """在Downloads目录中查找匹配前缀的最新xlsx文件"""
    pattern = os.path.join(DOWNLOADS_DIR, f"{pattern_prefix}*.xlsx")
    files = glob.glob(pattern)
    if not files:
        return None
    # 按修改时间降序排列，返回最新的
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
                ftp.set_debuglevel(1)  # 重试时开启调试日志
            ftp.login(FTP_USER, FTP_PASS)
            print(f"  登录成功: {FTP_USER}")

            # 先回到根目录，确保起点一致
            ftp.cwd("/")

            # 切换到目标目录（绝对路径逐级创建）
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

            # 验证当前目录是否正确
            current_dir = ftp.pwd()
            print(f"  远程目录: {current_dir}")
            expected = "/" + "/".join(parts)
            if current_dir != expected:
                print(f"  [WARNING] 目录不匹配，期望 {expected}，实际 {current_dir}")
                ftp.cwd(expected)

            # 上传
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
    如果表已存在且结构兼容，则追加/替换数据；否则重建表。
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 检查是否有 Begin Time 和 Group 列
    if "Begin Time" not in headers or "Group" not in headers:
        print(f"  [警告] 表 {table_name} 缺少 'Begin Time' 或 'Group' 列，跳过。")
        conn.close()
        return 0

    # 检查表是否已存在
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    table_exists = cursor.fetchone() is not None

    if not table_exists:
        # 新建表：先创建只有主键列的表，再动态添加其他列
        create_sql = (
            f'CREATE TABLE "{table_name}" (\n'
            f'  "Begin Time" TEXT NOT NULL,\n'
            f'  "Group" TEXT NOT NULL,\n'
            f'  PRIMARY KEY ("Begin Time", "Group")\n'
            f')'
        )
        cursor.execute(create_sql)

        # 添加非key列
        for h in headers:
            if h in ("Begin Time", "Group"):
                continue
            safe_col = h.replace('"', '""')
            try:
                cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{safe_col}" TEXT')
            except sqlite3.OperationalError:
                pass
    else:
        # 表已存在，检查并添加缺少的列
        cursor.execute(f'PRAGMA table_info("{table_name}")')
        existing_cols = {row[1] for row in cursor.fetchall()}
        for h in headers:
            if h not in existing_cols:
                safe_col = h.replace('"', '""')
                try:
                    cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{safe_col}" TEXT')
                except sqlite3.OperationalError:
                    pass

    # 构建 INSERT OR REPLACE 语句
    quoted_headers = [f'"{h.replace(chr(34), chr(34)+chr(34))}"' for h in headers]
    placeholders = ", ".join(["?"] * len(headers))
    insert_sql = (
        f'INSERT OR REPLACE INTO "{table_name}" '
        f'({", ".join(quoted_headers)}) VALUES ({placeholders})'
    )

    # 批量插入数据
    row_count = 0
    batch = []
    for row in data:
        # 确保列数一致
        if len(row) < len(headers):
            row.extend([None] * (len(headers) - len(row)))
        elif len(row) > len(headers):
            row = row[:len(headers)]

        # 将值转为字符串存储
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
    files_to_delete = []  # 收集所有需要删除的文件路径

    for tech in TECHS:
        nw_prefix = f"{tech} OLIB Network KPIs_NW"
        group_prefix = f"{tech} OLIB Network KPIs_Group"
        table_name = f"{tech}_OLIB_Network_KPIs"

        nw_file = find_latest_xlsx(nw_prefix)
        group_file = find_latest_xlsx(group_prefix)

        print(f"\n[{tech}]")

        # ---- 处理 _NW 文件 ----
        nw_headers = None
        nw_data = None
        nw_source = f"{tech} OLIB Network KPIs_NW"
        if nw_file:
            files_to_delete.append(nw_file)
            nw_filename = os.path.basename(nw_file)
            print(f"  _NW: {nw_filename}")

            # 从文件名提取Group值：按空格分割取第一个元素 + "_NW"
            group_value = nw_filename.split(" ")[0] + "_NW"
            print(f"  _NW Group: {group_value}")

            nw_headers, nw_data = read_xlsx(nw_file)
            print(f"  _NW: {len(nw_data)} rows, {len(nw_headers)} cols")

            # 增加 "Group" 列
            if "Group" not in nw_headers:
                nw_headers.append("Group")
                for row in nw_data:
                    row.append(group_value)
            else:
                group_idx = nw_headers.index("Group")
                for row in nw_data:
                    row[group_idx] = group_value

            # 增加 "Source File" 列
            if "Source File" not in nw_headers:
                nw_headers.append("Source File")
                for row in nw_data:
                    row.append(nw_source)
            else:
                sf_idx = nw_headers.index("Source File")
                for row in nw_data:
                    row[sf_idx] = nw_source
        else:
            print(f"  _NW: not found")

        # ---- 处理 _Group 文件 ----
        grp_headers = None
        grp_data = None
        grp_source = f"{tech} OLIB Network KPIs_Group"
        if group_file:
            files_to_delete.append(group_file)
            grp_filename = os.path.basename(group_file)
            print(f"  _Group: {grp_filename}")

            grp_headers, grp_data = read_xlsx(group_file)
            print(f"  _Group: {len(grp_data)} rows, {len(grp_headers)} cols")

            # 增加 "Source File" 列
            if "Source File" not in grp_headers:
                grp_headers.append("Source File")
                for row in grp_data:
                    row.append(grp_source)
            else:
                sf_idx = grp_headers.index("Source File")
                for row in grp_data:
                    row[sf_idx] = grp_source
        else:
            print(f"  _Group: not found")

        # ---- 合并写入 ----
        if nw_headers is None and grp_headers is None:
            print(f"  [skip] no files found")
            continue

        # 合并列头（取并集，保持顺序）
        if nw_headers and grp_headers:
            # 以_NW列头为基础，追加_Group中独有的列
            merged_headers = list(nw_headers)
            for h in grp_headers:
                if h not in merged_headers:
                    merged_headers.append(h)
        elif nw_headers:
            merged_headers = list(nw_headers)
        else:
            merged_headers = list(grp_headers)

        # 构建合并数据
        merged_data = []

        if nw_headers and nw_data:
            for row in nw_data:
                new_row = []
                # 保证列数与nw_headers一致
                while len(row) < len(nw_headers):
                    row.append(None)
                for h in merged_headers:
                    if h in nw_headers:
                        new_row.append(row[nw_headers.index(h)])
                    else:
                        new_row.append(None)
                merged_data.append(new_row)

        if grp_headers and grp_data:
            for row in grp_data:
                new_row = []
                while len(row) < len(grp_headers):
                    row.append(None)
                for h in merged_headers:
                    if h in grp_headers:
                        new_row.append(row[grp_headers.index(h)])
                    else:
                        new_row.append(None)
                merged_data.append(new_row)

        print(f"  merged: {len(merged_data)} rows, {len(merged_headers)} cols -> {table_name}")

        row_count = write_to_db(DB_PATH, table_name, merged_headers, merged_data)
        print(f"  written: {row_count} rows")
        total_imported += row_count

        # 显式释放本迭代中的大对象引用，帮助GC及时回收workbook句柄
        nw_headers = nw_data = None
        grp_headers = grp_data = None
        merged_headers = merged_data = None
        gc.collect()

    # ---- FTP 上传数据库文件 ----
    # ---- FTP 上传已移除（数据通过 API 写入远程） ----
    print("\n[INFO] FTP 上传已移除，数据由 my_app API 写入远程")

    # ---- 清理已导入的xlsx文件 ----
    print("\n[cleanup]")

    # 收集所有匹配的文件（包括历史副本）
    cleanup_prefixes = []
    for tech in TECHS:
        cleanup_prefixes.append(f"{tech} OLIB Network KPIs_NW")
        cleanup_prefixes.append(f"{tech} OLIB Network KPIs_Group")

    all_files = set(files_to_delete)
    for prefix in cleanup_prefixes:
        pattern = os.path.join(DOWNLOADS_DIR, f"{prefix}*.xlsx")
        for fpath in glob.glob(pattern):
            all_files.add(fpath)

    # 主动释放所有workbook引用并强制GC
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

    # 对失败的文件重试（使用 PowerShell Remove-Item -Force）
    if failed_files:
        print(f"  retrying {len(failed_files)} locked files with PowerShell force...")
        time.sleep(2)
        for fpath in failed_files:
            try:
                result = subprocess.run(
                    ['powershell', '-Command',
                     f'Remove-Item -Path "{fpath}" -Force -ErrorAction Stop'],
                    capture_output=True, timeout=15,
                    creationflags=_SUBPROCESS_FLAGS,
                )
                if not os.path.exists(fpath):
                    print(f"  deleted (force): {os.path.basename(fpath)}")
                    deleted_count += 1
                else:
                    print(f"  [warn] {os.path.basename(fpath)}: still locked, scheduled for reboot")
                    # 标记重启后删除
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
