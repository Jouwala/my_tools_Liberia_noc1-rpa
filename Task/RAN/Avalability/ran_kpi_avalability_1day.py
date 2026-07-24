# -*- coding: utf-8 -*-
"""
RAN Cell Availability 1-Daily KPI 数据导入脚本（多进程并行版）

架构:
  calamine (Rust)  ──→  ProcessPoolExecutor  ──→  Queue  ──→  SQLite Writer
  (并行读取CSV)          (N个Worker进程)        (进程间通信)   (独立写入进程)

核心优化:
  ✅ csv模块 (C实现) 读取 CSV，calamine (Rust引擎) 读取 XLSX
  ✅ ProcessPoolExecutor 多进程并行读取，绕过 GIL
  ✅ multiprocessing.Queue 解耦读写，Reader 不等待 Writer
  ✅ 独立 SQLite Writer 进程，单连接单事务批量写入
  ✅ PRAGMAs 极致写入优化（synchronous=OFF, cache=128MB, mmap=1GB）
  ✅ BATCH_SIZE=50000，减少 executemany 调用次数
  ✅ ZIP 内 CSV 自动解压到临时文件后由 calamine 读取
"""

import os
import gc
import re
import sys
import glob
import time
import csv as csv_module
import zipfile
import tempfile
import subprocess
import sqlite3
from datetime import datetime, date
from multiprocessing import Process, Manager
from concurrent.futures import ProcessPoolExecutor
from ftplib import FTP, error_perm

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

try:
    from python_calamine import CalamineWorkbook
    HAS_CALAMINE = True
except ImportError:
    HAS_CALAMINE = False
    print("[WARN] python-calamine not installed, xlsx support disabled")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============================================================
# 配置
# ============================================================
FILE_PREFIXES = [
    "KPI_RPA_CELL_AVAIL_FDD",
    "KPI_RPA_CELL_AVAIL_UMTS",
    "KPI_RPA_CELL_AVAIL_GSM",
    "KPI_RPA_CELL_AVAIL_TDD",
]

DOWNLOADS_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = "ran_kpi_avalability_1day.sqlite3"
DB_PATH = os.path.join(SCRIPT_DIR, DB_NAME)

FTP_HOST = "192.168.100.19"
FTP_USER = "ZTEEMS"
FTP_PASS = "DX"
FTP_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI/RAN"

BATCH_SIZE = 50000       # 批量插入行数
QUEUE_MAX = 200          # Queue 最大积压数（防内存溢出）
MAX_WORKERS = 4          # 并行 Reader 进程数


# ============================================================
# 工具函数
# ============================================================
def fmt_time(seconds):
    if seconds < 60:
        return f"{seconds:.2f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s}s ({seconds:.2f}s)"


def convert_value(v):
    """最小化类型转换：仅 datetime/date 需要 isoformat"""
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


# ============================================================
# 文件查找
# ============================================================
def find_matching_files():
    """
    扫描 Downloads 目录，查找匹配 FILE_PREFIXES 的 zip/csv/xlsx 文件。
    返回: list of dict  {file_path, file_type, zip_internal_name}
    """
    tasks = []

    if not os.path.isdir(DOWNLOADS_DIR):
        print(f"  [ERROR] Downloads目录不存在: {DOWNLOADS_DIR}")
        return tasks

    all_files = os.listdir(DOWNLOADS_DIR)
    print(f"  Downloads目录共 {len(all_files)} 个文件，扫描匹配...")

    zip_files = []
    for fname in all_files:
        if fname.startswith("~$"):
            continue
        upper_name = fname.upper()
        if not any(p.upper() in upper_name for p in FILE_PREFIXES):
            continue

        fpath = os.path.join(DOWNLOADS_DIR, fname)
        if not os.path.isfile(fpath):
            continue

        low = fname.lower()
        if low.endswith('.zip'):
            zip_files.append(fpath)
            print(f"  [FOUND ZIP] {fname} ({os.path.getsize(fpath) / 1024 / 1024:.1f}MB)")
        elif low.endswith('.csv'):
            tasks.append({"file_path": fpath, "file_type": "csv", "zip_internal_name": None})
            print(f"  [FOUND CSV] {fname} ({os.path.getsize(fpath) / 1024 / 1024:.1f}MB)")
        elif low.endswith('.xlsx'):
            tasks.append({"file_path": fpath, "file_type": "xlsx", "zip_internal_name": None})
            print(f"  [FOUND XLSX] {fname} ({os.path.getsize(fpath) / 1024 / 1024:.1f}MB)")

    # 处理 ZIP：提取内部 CSV/XLSX 任务
    zip_files.sort(key=os.path.getmtime, reverse=True)
    for zip_path in zip_files:
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for n in zf.namelist():
                    if n.endswith('/'):
                        continue
                    bn = os.path.basename(n)
                    if bn.startswith('~$'):
                        continue
                    low_n = n.lower()
                    # 跳过文件名含 _KPI(Counter) 的文件
                    if "_kpi(counter)" in low_n:
                        print(f"    [SKIP] {bn}")
                        continue
                    if low_n.endswith('.csv'):
                        tasks.append({"file_path": zip_path, "file_type": "zip_csv",
                                      "zip_internal_name": n})
                    elif low_n.endswith('.xlsx'):
                        tasks.append({"file_path": zip_path, "file_type": "zip_xlsx",
                                      "zip_internal_name": n})
        except zipfile.BadZipFile:
            print(f"  [ERROR] zip损坏: {zip_path}")

    csv_count = sum(1 for t in tasks if "csv" in t["file_type"])
    xlsx_count = sum(1 for t in tasks if "xlsx" in t["file_type"])
    print(f"  匹配任务: {len(tasks)} 个（{csv_count} csv, {xlsx_count} xlsx）")
    return tasks


# ============================================================
# Worker: CSV/XLSX Reader（calamine Rust引擎）
# ============================================================
def _stream_csv(filepath, queue, table_name, batch_size):
    """流式读取 CSV → 分批入 Queue，内存仅占 batch_size 行"""
    batch_count = 0
    with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv_module.reader(f)
        header_row = next(reader)
        headers = [str(col).strip() if col else f"col_{i}"
                   for i, col in enumerate(header_row)]
        n_cols = len(headers)
        row_count = 0
        batch = []
        for row in reader:
            if not any(row):
                continue
            if len(row) < n_cols:
                row.extend([None] * (n_cols - len(row)))
            elif len(row) > n_cols:
                row = row[:n_cols]
            batch.append(row)
            row_count += 1
            if len(batch) >= batch_size:
                queue.put((table_name, headers, batch))
                batch_count += 1
                batch = []
        if batch:
            queue.put((table_name, headers, batch))
            batch_count += 1
    print(f"  [_stream_csv] {table_name}: {row_count} rows, {batch_count} batches")
    return headers, row_count


def _read_xlsx(filepath):
    """用 calamine (Rust引擎) 读取 XLSX，返回 (headers, rows)"""
    if not HAS_CALAMINE:
        raise RuntimeError("python-calamine not installed, cannot read xlsx")
    wb = CalamineWorkbook.from_path(filepath)
    sheet = wb.get_sheet_by_index(0)
    all_data = sheet.to_python()
    wb.close()

    if not all_data:
        return [], [], 0

    header_row = all_data[0]
    headers = [str(col).strip() if col is not None else f"col_{i}"
               for i, col in enumerate(header_row)]
    n_cols = len(headers)
    rows = []
    for row in all_data[1:]:
        if all(v is None for v in row):
            continue
        if len(row) < n_cols:
            row = list(row) + [None] * (n_cols - len(row))
        elif len(row) > n_cols:
            row = list(row[:n_cols])
        else:
            row = list(row)
        rows.append(row)
    return headers, rows, len(rows)


def csv_reader_worker(task_info, queue, batch_size):
    """
    Worker 进程入口：
      CSV → csv模块 (C实现)
      XLSX → calamine (Rust引擎)
    将数据批次放入 Queue 供 SQLite Writer 消费。

    task_info: {file_path, file_type, zip_internal_name}
    queue:     multiprocessing.Queue
    batch_size: 每批行数

    Queue 消息协议:
      数据: (table_name, headers_or_None, batch_rows)
      完成: ("__DONE__", worker_id, row_count)
      错误: ("__ERROR__", worker_id, error_msg)
    """
    file_path = task_info["file_path"]
    file_type = task_info["file_type"]
    zip_internal = task_info.get("zip_internal_name")
    worker_id = os.getpid()

    try:
        # ---- 1. 确定实际文件路径 ----
        actual_path = file_path
        temp_path = None

        if file_type.startswith("zip_"):
            # ZIP 内文件：提取到临时文件
            with zipfile.ZipFile(file_path, 'r') as zf:
                ext = ".csv" if file_type == "zip_csv" else ".xlsx"
                suffix = f"_{os.path.basename(zip_internal)}"
                with zf.open(zip_internal) as src, \
                     tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    while True:
                        chunk = src.read(1048576)  # 1MB chunks
                        if not chunk:
                            break
                        tmp.write(chunk)
                    temp_path = tmp.name
                actual_path = temp_path

        # ---- 2. 确定表名 ----
        if zip_internal:
            source_name = os.path.basename(zip_internal)
        else:
            source_name = os.path.basename(file_path)
        name_no_ext = os.path.splitext(source_name)[0]
        # 去掉末尾的 _001, _002 等数字后缀，合并到同一张表
        # e.g. KPI_RPA_CELL_AVAIL_UMTS1day_001 -> KPI_RPA_CELL_AVAIL_UMTS1day
        name_no_ext = re.sub(r'_\d+$', '', name_no_ext)
        # 匹配 FILE_PREFIXES 生成标准表名（不含 1day 等后缀）
        # e.g. KPI_RPA_CELL_AVAIL_FDD1day -> 匹配 KPI_RPA_CELL_AVAIL_FDD -> Daily_KPI_RPA_CELL_AVAIL_FDD
        matched_prefix = None
        for prefix in FILE_PREFIXES:
            if name_no_ext.startswith(prefix):
                matched_prefix = prefix
                break
        if matched_prefix:
            table_name = f"Daily_{matched_prefix}"
        else:
            table_name = f"Daily_{name_no_ext}"

        # ---- 3. 读取数据 ----
        is_csv = file_type in ("csv", "zip_csv")
        t0 = time.time()
        print(f"  [Worker {worker_id}] Processing {source_name} -> {table_name}")

        if is_csv:
            # CSV: 流式读取，内存仅占 batch_size 行
            headers, row_count = _stream_csv(
                actual_path, queue, table_name, batch_size
            )
            print(f"  [Worker {worker_id}] Read {row_count} rows from {source_name} -> {table_name}")
        else:
            # XLSX: calamine 全量读取后分批入 Queue
            headers, rows, row_count = _read_xlsx(actual_path)
            if row_count == 0:
                queue.put(("__DONE__", worker_id, 0))
                return (table_name, 0, time.time() - t0)
            for i in range(0, row_count, batch_size):
                queue.put((table_name, headers, rows[i:i + batch_size]))
            print(f"  [Worker {worker_id}] Read {row_count} rows from {source_name} -> {table_name}")

        t_read = time.time() - t0

        # ---- 5. 清理临时文件 ----
        if temp_path:
            try:
                os.unlink(temp_path)
            except Exception:
                pass

        # 确保 Queue 中的数据被传递（特别是对于小数据量的表）
        # 给 Queue 一点时间确保数据被放入
        import time as _time
        _time.sleep(0.1)  # 100ms 确保数据进入 Queue

        queue.put(("__DONE__", worker_id, row_count))
        t_total = time.time() - t0
        return (table_name, row_count, t_total)

    except Exception as e:
        queue.put(("__ERROR__", worker_id, str(e)))
        if temp_path:
            try:
                os.unlink(temp_path)
            except Exception:
                pass
        return None


# ============================================================
# SQLite Writer 进程
# ============================================================
def sqlite_writer_process(db_path, queue, n_workers):
    """
    独立 SQLite 写入进程：从 Queue 消费数据批次，批量写入 SQLite。

    单连接、单事务、PRAGMAs 极致优化。
    等待 n_workers 个 __DONE__ 信号后退出。
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # ===== 写入优化 PRAGMAs =====
    cursor.execute("PRAGMA journal_mode=DELETE")
    cursor.execute("PRAGMA synchronous=OFF")
    cursor.execute("PRAGMA cache_size=-128000")      # 128MB cache
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA mmap_size=1073741824")     # 1GB mmap
    cursor.execute("PRAGMA cache_spill=OFF")
    cursor.execute("PRAGMA count_changes=OFF")

    tables = {}    # table_name -> {headers, n_cols, sql, created}
    buffers = {}   # table_name -> [rows]
    table_row_counts = {}  # table_name -> row_count (for tracking)
    total_rows = 0
    done_count = 0
    total_msg_count = 0  # 统计收到的总消息数

    cursor.execute("BEGIN TRANSACTION")

    while done_count < n_workers:
        try:
            msg = queue.get(timeout=600)
        except Exception:
            continue

        total_msg_count += 1
        msg_type = msg[0]

        # ---- 完成信号 ----
        if msg_type == "__DONE__":
            done_count += 1
            _, worker_id, row_count = msg
            print(f"  [Writer] Received __DONE__ from worker {worker_id} (total rows: {row_count})")
            continue

        # ---- 错误信号 ----
        if msg_type == "__ERROR__":
            done_count += 1
            continue

        # ---- 数据批次 ----
        table_name, headers, batch = msg

        # 追踪接收到的批次
        if table_name not in tables:
            print(f"  [Writer] First batch for {table_name}: {len(batch)} rows")
        else:
            print(f"  [Writer] Received batch for {table_name}: {len(batch)} rows")

        # 首次遇到新表：初始化表结构
        if table_name not in tables:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            if cursor.fetchone():
                cursor.execute(f'DELETE FROM "{table_name}"')
            else:
                col_defs = ", ".join(
                    f'"{h.replace(chr(34), chr(34)+chr(34))}" TEXT'
                    for h in headers
                )
                cursor.execute(f'CREATE TABLE "{table_name}" ({col_defs})')

            # 构建 INSERT 语句（表存在或新建后都需要构建）
            quoted = [
                f'"{h.replace(chr(34), chr(34)+chr(34))}"'
                for h in headers
            ]
            placeholders = ", ".join(["?"] * len(headers))
            sql = (
                f'INSERT INTO "{table_name}" ({", ".join(quoted)}) VALUES ({placeholders})'
            )
            tables[table_name] = {
                "headers": headers,
                "n_cols": len(headers),
                "sql": sql,
                "created": True,
            }
            buffers[table_name] = []

        info = tables[table_name]
        n_cols = info["n_cols"]
        insert_sql = info["sql"]

        # 规范化列数 + 最小类型转换
        for row in batch:
            if len(row) < n_cols:
                row.extend([None] * (n_cols - len(row)))
            elif len(row) > n_cols:
                row = row[:n_cols]
            buffers[table_name].append([convert_value(v) for v in row])

        # 追踪每个表的行数
        batch_len = len(batch)
        total_rows += batch_len
        if table_name not in table_row_counts:
            table_row_counts[table_name] = 0
        table_row_counts[table_name] += batch_len

        # 缓冲区满则 executemany
        if len(buffers[table_name]) >= BATCH_SIZE:
            try:
                cursor.executemany(insert_sql, buffers[table_name])
            except Exception as e:
                print(f"  [ERROR] executemany failed for {table_name}: {e}")
            buffers[table_name].clear()

    # ---- 最终 flush 所有缓冲区 ----
    print(f"\n  [Writer] Flushing {len(tables)} tables...")
    for tname in tables:
        if buffers.get(tname):
            try:
                cursor.executemany(tables[tname]["sql"], buffers[tname])
                print(f"    Flushed {tname}: {len(buffers[tname])} rows")
            except Exception as e:
                print(f"    [ERROR] flush failed for {tname}: {e}")
            buffers[tname].clear()

    # 打印每个表的写入统计
    print(f"\n  [Writer] Table write summary:")
    for tname, count in sorted(table_row_counts.items()):
        print(f"    {tname}: {count} rows")
    print(f"  [Writer] Total messages received: {total_msg_count}")
    print(f"  [Writer] Done signals received: {done_count}")

    conn.commit()

    # ---- 建索引（第一列，通常是时间列） ----
    for tname, info in tables.items():
        if info["headers"]:
            first_col = info["headers"][0].replace('"', '""')
            try:
                cursor.execute(
                    f'CREATE INDEX IF NOT EXISTS "idx_{tname}_{first_col}" '
                    f'ON "{tname}" ("{first_col}")'
                )
            except Exception:
                pass
    conn.commit()
    conn.close()

    print(f"  [Writer] Total rows written: {total_rows}")
    print(f"  [Writer] Returning from writer process")
    return total_rows


# ============================================================
# FTP 上传
# ============================================================
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


# ============================================================
# 主函数
# ============================================================
def main():
    t_total_start = time.time()
    start_time = datetime.now()
    print("=" * 60)
    print(f"  脚本开始时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  架构: csv(C)/calamine(Rust) → ProcessPoolExecutor → Queue → SQLite Writer")
    print(f"  Downloads: {DOWNLOADS_DIR}")
    print(f"  DB: {DB_PATH}")
    print(f"  BATCH_SIZE: {BATCH_SIZE} | Workers: {MAX_WORKERS} | Queue: {QUEUE_MAX}")
    print("=" * 60)

    files_to_delete = set()

    # ---- 1. 查找文件 ----
    t_find_start = time.time()
    print(f"\n[1/3] 查找文件...")
    tasks = find_matching_files()
    t_find_end = time.time()
    print(f"  查找耗时: {t_find_end - t_find_start:.2f}s")

    if not tasks:
        print(f"\n[WARN] 未找到任何匹配文件，退出")
        print(f"  请将 KPI_RPA_CELL_AVAIL_* 文件放到: {DOWNLOADS_DIR}")
        return

    # 记录需要删除的源文件
    for t in tasks:
        files_to_delete.add(t["file_path"])

    # ---- 2. 多进程并行写入数据库 ----
    print(f"\n[2/3] 多进程写入数据库...")
    print(f"  启动 {MAX_WORKERS} 个 Reader 进程 (calamine Rust引擎)")
    print(f"  启动 1 个 SQLite Writer 进程")
    t_db_start = time.time()

    n_workers = min(MAX_WORKERS, len(tasks))
    n_tasks = len(tasks)  # 实际任务数，用于 Writer 等待所有 __DONE__ 信号
    # Windows 下 ProcessPoolExecutor 使用 spawn，multiprocessing.Queue 无法 pickle
    # 必须使用 Manager().Queue()（基于服务器代理，可跨进程 pickle 传递）
    manager = Manager()
    queue = manager.Queue(QUEUE_MAX)

    # 启动 SQLite Writer 进程
    print(f"  任务数: {n_tasks}, 并发进程数: {n_workers}")
    writer_proc = Process(
        target=sqlite_writer_process,
        args=(DB_PATH, queue, n_tasks),
    )
    writer_proc.start()

    # 启动 Reader 进程池
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = []
        for task in tasks:
            future = executor.submit(csv_reader_worker, task, queue, BATCH_SIZE)
            futures.append(future)

        # 等待所有 Reader 完成并收集结果
        for future in futures:
            try:
                result = future.result()
                if result:
                    tname, nrows, elapsed = result
                    print(f"    [{tname}] {nrows} rows ({elapsed:.2f}s)")
            except Exception as e:
                print(f"    [ERROR] Reader异常: {e}")

    # Writer 进程会收到所有 __DONE__ 后自动退出
    writer_proc.join()
    manager.shutdown()  # 释放 Manager 服务器资源
    t_db_end = time.time()

    print(f"\n  数据库总耗时: {fmt_time(t_db_end - t_db_start)}")
    gc.collect()

    # ---- 3. FTP 上传 ----
    print(f"\n[3/3] FTP上传...")
    t_ftp_start = time.time()
    if upload_to_ftp(DB_PATH, FTP_REMOTE_DIR, DB_NAME):
        print(f"  [OK] 数据库已上传: {DB_NAME}")
    else:
        print(f"  [FAIL] 数据库上传失败: {DB_NAME}")
    t_ftp_end = time.time()
    print(f"  FTP耗时: {fmt_time(t_ftp_end - t_ftp_start)}")

    # ---- 清理文件 ----
    print(f"\n[cleanup]")
    for prefix in FILE_PREFIXES:
        for ext in (".zip", ".csv", ".xlsx"):
            pattern = os.path.join(DOWNLOADS_DIR, f"{prefix}*{ext}")
            for fpath in glob.glob(pattern):
                if not os.path.basename(fpath).startswith("~$"):
                    files_to_delete.add(fpath)

    gc.collect()

    deleted_count = 0
    failed_files = []
    for fpath in files_to_delete:
        try:
            os.remove(fpath)
            print(f"  deleted: {os.path.basename(fpath)}")
            deleted_count += 1
        except PermissionError:
            failed_files.append(fpath)
        except Exception as e:
            print(f"  [error] {os.path.basename(fpath)}: {e}")

    if failed_files:
        print(f"  retrying {len(failed_files)} locked files...")
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
                    import ctypes
                    ctypes.windll.kernel32.MoveFileExW(fpath, None, 0x4)
            except Exception as e:
                print(f"  [error] {os.path.basename(fpath)}: {e}")

    print(f"  total deleted: {deleted_count} files")

    # ================================================================
    # 完成统计
    # ================================================================
    t_total_end = time.time()
    end_time = datetime.now()
    total_elapsed = t_total_end - t_total_start

    # 从数据库读取总行数
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        db_tables = [r[0] for r in cursor.fetchall()]
        total_rows = 0
        print(f"\n  [Final Check] Tables in database: {len(db_tables)}")
        for tbl in db_tables:
            count = cursor.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
            print(f"    {tbl}: {count} rows")
            total_rows += count
        conn.close()
    except Exception as e:
        print(f"  [ERROR] Failed to read database: {e}")
        total_rows = -1

    print("\n" + "=" * 60)
    print(f"  脚本开始时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  脚本完成时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  总耗时: {fmt_time(total_elapsed)}")
    print(f"  写入行数: {total_rows}")
    print(f"  数据库: {DB_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"\n[FATAL ERROR] {e}")
        traceback.print_exc()
        sys.exit(1)
