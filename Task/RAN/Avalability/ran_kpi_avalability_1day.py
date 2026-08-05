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
import io
from datetime import datetime, date, timezone, timedelta
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
# RAN UME API 拉取（替代手动从 Downloads 取文件）
# 复用 Task/ran_ume/ran_ume_login.py 客户端：login / create / wait / export
# ============================================================
_RAN_UME_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ran_ume")
)
if _RAN_UME_DIR not in sys.path:
    sys.path.insert(0, _RAN_UME_DIR)

try:
    import ran_ume_login as rume
    HAS_RAN_UME = True
except Exception as _imp_err:  # pragma: no cover
    rume = None
    HAS_RAN_UME = False
    print(f"[WARN] 无法导入 ran_ume_login ({_RAN_UME_DIR}): {_imp_err}")

# API 拉取的 xlsx 全程内存处理：fetch 阶段返回原始字节（不落盘），
# 由 reader 在内存中解析，避免任何临时文件。
API_OUTPUT_DIR = None  # 已废弃：数据不再写入磁盘

# 4 个可用性模板的 PM 查询配置（来自 RAN UME 已保存模板，由运维粘贴）
# 每个键对应 FILE_PREFIXES 中的一项；导出文件以该 prefix 命名，
# 后续 reader 据此映射到 Daily_<PREFIX> 表。
AVAILABILITY_PM_CONFIGS = {
    "KPI_RPA_CELL_AVAIL_FDD": {
        "templateid": "1638004472410",
        "templatename": "KPI_RPA_CELL_AVAIL_FDD",
        "motid": "EUtranCellFDD",
        "nfctid": "ITBBU,SDR,#",
        "containvcell": 0,
        "indexfillingtype": "zeroDenominator",
        "groupattributetype": 0,
        "groupbygroup": False,
        "showbusinesscolumn": True,
        "grouplayer": "me,eNodeBFunction,EUtranCellFDD",
        "items": ["C373230700", "C373230706"],
        "itemsposition": [0, 0],
        "itemsposition1": [1, 1],
        "businessmotid": "FDDV3.EUtranCellFDD",
        "itempositionbusiness": [0, 0],
    },
    "KPI_RPA_CELL_AVAIL_UMTS": {
        "templateid": "1638004472409",
        "templatename": "KPI_RPA_CELL_AVAIL_UMTS",
        "motid": "wPm.UtranCell",
        "nfctid": "MRNC",
        "containvcell": 2,
        "indexfillingtype": "zeroDenominator",
        "groupattributetype": 1,
        "groupattribute": "freqBandInd",
        "groupbygroup": False,
        "showbusinesscolumn": False,
        "grouplayer": "me,WV4.IubLink,WV4.UtranCell",
        "items": ["C310464560"],
        "itemsposition": [0],
        "itemsposition1": [0],
    },
    "KPI_RPA_CELL_AVAIL_GSM": {
        "templateid": "1638004472408",
        "templatename": "KPI_RPA_CELL_AVAIL_GSM",
        "motid": "gsmPm.cell",
        "nfctid": "MRNC",
        "containvcell": 0,
        "indexfillingtype": "zeroDenominator",
        "groupattributetype": 1,
        "groupattribute": "freqBand",
        "groupbygroup": False,
        "showbusinesscolumn": False,
        "grouplayer": "me,gv4.BTSSiteManager,gv4.BTS.cell",
        "items": ["C901080019", "C901080029", "C901080028", "C901080009", "C901080010", "C901080020"],
        "itemsposition": [0, 0, 0, 0, 0, 0],
        "itemsposition1": [0, 0, 0, 0, 0, 0],
    },
    "KPI_RPA_CELL_AVAIL_TDD": {
        "templateid": "1638004472411",
        "templatename": "KPI_RPA_CELL_AVAIL_TDD",
        "motid": "EUtranCellTDD",
        "nfctid": "ITBBU,SDR,#",
        "containvcell": 0,
        "indexfillingtype": "zeroDenominator",
        "groupattributetype": 0,
        "groupbygroup": False,
        "showbusinesscolumn": True,
        "grouplayer": "me,eNodeBFunction,EUtranCellTDD",
        "items": ["C373230706", "C373230700"],
        "itemsposition": [0, 0],
        "itemsposition1": [1, 1],
        "businessmotid": "TDDV3.EUtranCellTDD",
        "itempositionbusiness": [0, 0],
    },
}



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
# 主键（业务键）定义 —— 按数据定义，用于「按主键覆盖写入」
# 每张 Daily_* 表的天然唯一键 = (Begin Time 日期, 小区标识列)
# 注意：RAN UME 导出的表头使用「不间断空格 \xa0」而非普通空格，
#       因此用 _norm() 归一化后再匹配，避免硬编码空格导致匹配失败。
# ============================================================
def _norm(s):
    """归一化列名：把不间断空格/全角空格等统一成普通空格并压缩。"""
    if not isinstance(s, str):
        return s
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


# 模板 prefix -> 小区标识列的「归一化」名称
_PK_CELLNAME_LOOKUP = {
    "KPI_RPA_CELL_AVAIL_FDD":  "E-UTRAN FDD Cell Name",
    "KPI_RPA_CELL_AVAIL_UMTS": "Cell Name",
    "KPI_RPA_CELL_AVAIL_GSM":  "BTS Name",
    "KPI_RPA_CELL_AVAIL_TDD":  "E-UTRAN TDD Cell Name",
}


def _resolve_pk(table_name, headers):
    """
    根据表名 + 实际列头，返回用于覆盖写入的主键列（原始列名列表）。
    返回 [日期列, 小区标识列]；若匹配不到则回退到 [首列, 含 Cell Name/BTS Name 的列]。
    """
    prefix = table_name[6:] if table_name.startswith("Daily_") else table_name
    norm_to_orig = {_norm(h): h for h in headers}

    pk = []

    # 1) 日期列（通常是第一列 Begin Time）
    time_cand = "Begin Time"
    if _norm(time_cand) in norm_to_orig:
        pk.append(norm_to_orig[_norm(time_cand)])

    # 2) 小区标识列
    cell_norm = _PK_CELLNAME_LOOKUP.get(prefix)
    if cell_norm and cell_norm in norm_to_orig:
        pk.append(norm_to_orig[cell_norm])
    elif len(pk) < 2:
        # 回退：找含 Cell Name / BTS Name 的列
        for h in headers:
            n = _norm(h)
            if "Cell Name" in n or n == "BTS Name":
                if h not in pk:
                    pk.append(h)
                    break

    if len(pk) >= 2:
        return pk[:2]
    # 极端回退：首两列
    return [headers[0], headers[1]] if len(headers) >= 2 else [headers[0]]


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


def _read_xlsx_bytes(data: bytes):
    """
    从内存中的 xlsx 原始字节读取（不落盘）。
    优先使用 openpyxl（支持 BytesIO 内存读取），无磁盘临时文件。
    返回 (headers, rows, row_count)。
    """
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
    try:
        ws = wb.active
        all_data = list(ws.iter_rows(values_only=True))
    finally:
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
    worker_id = os.getpid()
    file_bytes = task_info.get("file_bytes")
    table_name = task_info.get("table_name")

    try:
        # ====== 内存模式：API 拉取的 xlsx 字节，全程不落盘 ======
        if file_bytes is not None:
            source_name = task_info.get("source_name", "memory.xlsx")
            if not table_name:
                name_no_ext = re.sub(r'_\d+$', '', os.path.splitext(source_name)[0])
                matched_prefix = next(
                    (p for p in FILE_PREFIXES if name_no_ext.startswith(p)), None
                )
                table_name = f"Daily_{matched_prefix}" if matched_prefix else f"Daily_{name_no_ext}"
            t0 = time.time()
            print(f"  [Worker {worker_id}] (in-memory) {source_name} -> {table_name}")
            headers, rows, row_count = _read_xlsx_bytes(file_bytes)
            if row_count == 0:
                queue.put(("__DONE__", worker_id, 0))
                return (table_name, 0, time.time() - t0)
            for i in range(0, row_count, batch_size):
                queue.put((table_name, headers, rows[i:i + batch_size]))
            print(f"  [Worker {worker_id}] Read {row_count} rows (in-memory) -> {table_name}")
            queue.put(("__DONE__", worker_id, row_count))
            return (table_name, row_count, time.time() - t0)

        # ====== 文件模式（遗留：从 Downloads / ZIP 读取，会落盘）======
        file_path = task_info["file_path"]
        file_type = task_info["file_type"]
        zip_internal = task_info.get("zip_internal_name")
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

        # 首次遇到新表：初始化表结构（按主键覆盖写入 / 累积历史）
        if table_name not in tables:
            pk_cols = _resolve_pk(table_name, headers)
            _q = lambda s: '"' + s.replace('"', '""') + '"'
            quoted_pk = ", ".join(_q(c) for c in pk_cols)

            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            table_existed = cursor.fetchone() is not None

            if table_existed:
                # 列结构是否一致（任一新列在旧表中不存在则重建，避免 INSERT 失败）
                existing_cols = {
                    r[1] for r in cursor.execute(
                        f'PRAGMA table_info("{table_name}")'
                    ).fetchall()
                }
                schema_changed = not all(h in existing_cols for h in headers)
                if schema_changed:
                    print(f"  [WARN] {table_name} 列结构变化，DROP 并重建")
                    cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                    table_existed = False

            if not table_existed:
                col_defs = ", ".join(_q(h) + " TEXT" for h in headers)
                pk_def = ", ".join(_q(c) for c in pk_cols)
                cursor.execute(
                    f'CREATE TABLE "{table_name}" ({col_defs}, PRIMARY KEY ({pk_def}))'
                )
                print(f"  [Writer] 建表 {table_name} PK=({quoted_pk})")
            else:
                # 表已存在且结构一致：确保唯一索引，INSERT OR REPLACE 据此覆盖
                idx_name = f"uq_{table_name}"
                try:
                    cursor.execute(
                        f'CREATE UNIQUE INDEX IF NOT EXISTS "{idx_name}" '
                        f'ON "{table_name}" ({quoted_pk})'
                    )
                except Exception as e:
                    print(f"  [WARN] 唯一索引创建失败 {table_name}: {e}")

            # 构建 INSERT 语句（按主键覆盖写入）
            quoted = [_q(h) for h in headers]
            placeholders = ", ".join(["?"] * len(headers))
            sql = (
                f'INSERT OR REPLACE INTO "{table_name}" '
                f'({", ".join(quoted)}) VALUES ({placeholders})'
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

    # ---- 唯一索引已在建表/首次遇到表时创建，无需再建冗余索引 ----
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
# RAN UME API 拉取
# ============================================================
def build_availability_payload(cfg, start_iso, end_iso):
    """依据模板配置构造 RAN UME PM 历史查询 payload（1 天窗口）。"""
    items = cfg["items"]
    n = len(items)
    payload = {
        "arraycounterinfos": [],
        "datatype": 0,
        "displaymode": 0,
        "favoriteconditionname": cfg["templatename"],
        "gr": "86400",
        "groupattributetype": cfg.get("groupattributetype", 0),
        "groupbygroup": cfg.get("groupbygroup", False),
        "groupbyplmn": False,
        "grouptype": 0,
        "items": items,
        "itemsposition": cfg.get("itemsposition", [0] * n),
        "itemsposition1": cfg.get("itemsposition1", [0] * n),
        "motid": cfg["motid"],
        "nfctid": cfg["nfctid"],
        "plmnpdfdisplaymode": False,
        "queryallbusiness": False,
        "showbusinesscolumn": cfg.get("showbusinesscolumn", False),
        "showintegrity": False,
        "straightquery": False,
        "templatename": cfg["templatename"],
        "templateid": cfg["templateid"],
        "needdeployfilter": False,
        "timeinfo": {
            "mode": 1,
            "start": start_iso,
            "end": end_iso,
            "relative": -1,
            "timezonetype": "1",
            "clienttimezone": "Atlantic/Reykjavik",
            "showtimezoneoffset": False,
            "querylongtime": {"type": 3, "value": 1},
            "timespanfilter": "00:00:00-24:00:00",
            "dayfiltertype": 0,
            "dayinmonthfilter": "1111111111111111111111111111111",
        },
        "indexfillingtype": cfg.get("indexfillingtype", "zeroDenominator"),
        "thresholdinfos": [],
        "templatetype": 0,
        "filterlayer": "all",
        "grouplayer": cfg["grouplayer"],
        "containvcell": cfg.get("containvcell", 0),
        "resfilterattribute": "",
        "uilocations": [],
        "reslocation": [],
        "inexistenceres": False,
        "firstDayOfWeek": 7,
        "iswireless": True,
        "hidehistorystopbutton": True,
        "opencustomizehistoryexport": False,
        "opentemplatecustomcolumn": False,
    }
    if "businessmotid" in cfg:
        payload["businessmotid"] = cfg["businessmotid"]
        payload["itempositionbusiness"] = cfg.get("itempositionbusiness", [0] * n)
        payload["businessfilterscope"] = []
        payload["groupbusinessids"] = []
    if "groupattribute" in cfg:
        payload["groupattribute"] = cfg["groupattribute"]
    return payload


def _utc_day_midnight(dt):
    """把时间截断到 UTC 当天 00:00:00。"""
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def fetch_availability_range(start_dt, end_dt, max_retries=2):
    """
    拉取 [start_dt, end_dt) UTC 窗口内 4 个可用性模板的数据，全程内存
    （export return_bytes=True），不写入任何临时文件。
    返回 tasks 列表：[{file_bytes, file_type, source_name, table_name}, ...]
    单个模板失败会重试 max_retries 次；仍失败则跳过（backfill 时该模板此窗口留空，可重跑补齐）。
    """
    if not HAS_RAN_UME:
        print("[ERROR] ran_ume_login 不可用，无法 API 拉取。请检查 Task/ran_ume 目录。")
        return []

    print(f"  [API] 使用 RAN UME 客户端: {_RAN_UME_DIR}")
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    print(f"  [API] 时间窗口(UTC): {start_iso} ~ {end_iso}")

    auth = rume.login()
    cookie = auth["cookie"]
    forgery = auth["forgery_token"]

    tasks = []
    for prefix, cfg in AVAILABILITY_PM_CONFIGS.items():
        ok = False
        for attempt in range(1, max_retries + 1):
            try:
                print(f"\n  [API] 拉取 {prefix} (templateid={cfg['templateid']}) ... [attempt {attempt}]")
                payload = build_availability_payload(cfg, start_iso, end_iso)
                queryid = rume.create_pm_history_query(cookie, forgery, payload)
                rume.wait_pm_history_ready(cookie, forgery, queryid, timeout=600, interval=5)
                ts = datetime.now().strftime("%Y%m%d%H%M%S")
                filename = f"{prefix}_win_{ts}"
                # 关键：return_bytes=True -> 全程内存，不落盘
                xlsx_bytes = rume.export_pm_history(
                    cookie, forgery, queryid, filename=filename, return_bytes=True
                )
                tasks.append({
                    "file_bytes": xlsx_bytes,
                    "file_type": "xlsx",
                    "source_name": f"{filename}.xlsx",
                    "table_name": f"Daily_{prefix}",
                })
                print(f"  [API] 已取得内存数据: {filename}.xlsx ({len(xlsx_bytes)} bytes)")
                ok = True
                break
            except Exception as e:
                print(f"  [ERROR] {prefix} 拉取失败(attempt {attempt}): {e}")
                import traceback as _tb
                _tb.print_exc()
        if not ok:
            print(f"  [WARN] {prefix} 在窗口 {start_iso}~{end_iso} 多次重试失败，跳过该模板")

    print(f"\n  [API] 共获取 {len(tasks)} 个模板数据（均驻留内存，未落盘）")
    return tasks


def fetch_availability_via_api(window_days=2):
    """
    每日模式：拉取「前 window_days 天」窗口（默认 2 天）的可用性数据。
    配合按主键覆盖写入（INSERT OR REPLACE），重叠天会被幂等刷新，
    可安全重复执行以捕获 RAN UME 的迟到修正。
    """
    now_utc = datetime.now(timezone.utc)
    end_dt = _utc_day_midnight(now_utc)
    start_dt = end_dt - timedelta(days=window_days)
    return fetch_availability_range(start_dt, end_dt)



# ============================================================
# 写入 + 上传 流水线（可被每日模式与 backfill 复用）
# ============================================================
DEFAULT_BACKFILL_CHUNK_DAYS = 7   # backfill 分片天数（可调，避免单查询过大）


def run_write_pipeline(tasks, do_upload=True):
    """
    把 tasks（内存 xlsx 字节）经多进程 reader → SQLite writer 写入 DB；
    写完后按需 FTP 上传到远程。返回写入总行数。
    写法是按主键覆盖（INSERT OR REPLACE），重跑不产生重复行。
    """
    # ---- 多进程并行写入数据库 ----
    print(f"\n[write] 多进程写入数据库...")
    print(f"  启动 {MAX_WORKERS} 个 Reader 进程")
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

    # ---- VACUUM：回收 INSERT OR REPLACE 产生的空闲页，避免文件无限膨胀 ----
    # 仅在即将上传远程时执行（backfill 分片阶段 do_upload=False 跳过）。
    if do_upload:
        _vacuum_db()

    # ---- FTP 上传：把本地构建好的数据库推送到远程 192.168.100.19 ----
    # 说明：my_app 并未集成本库（无对应推送逻辑），远程 \\192.168.100.19\e\01_RPA\LBR_Tools\KPI\RAN\
    # 的副本只能由本脚本通过 FTP 直接上传。若不上传，远程 DB 将停止更新。
    if do_upload:
        print(f"\n[upload] FTP 上传数据库到远程 {FTP_HOST}:{FTP_REMOTE_DIR} ...")
        try:
            upload_ok = upload_to_ftp(DB_PATH, FTP_REMOTE_DIR, DB_NAME)
        except Exception as e:
            upload_ok = False
            print(f"  [ERROR] FTP 上传异常: {e}")
        if upload_ok:
            print(f"  [OK] 远程数据库已更新: {FTP_REMOTE_DIR}/{DB_NAME}")
        else:
            print(f"  [WARN] FTP 上传失败，请检查 {FTP_HOST} 连通性 / 账号，并手动重传 {DB_PATH}")
    else:
        print(f"\n[upload] 跳过 FTP 上传（backfill 分片阶段，结尾统一上传）")

    return


def _vacuum_db():
    """回收 INSERT OR REPLACE 产生的空闲页，避免文件无限膨胀。
    仅在空闲页占比过高时执行；异常时静默跳过。"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("PRAGMA page_count"); pc = cur.fetchone()[0]
        cur.execute("PRAGMA freelist_count"); fl = cur.fetchone()[0]
        conn.close()
        if pc and fl > max(50000, int(pc * 0.25)):
            print(f"\n[vacuum] 空闲页 {fl}/{pc}，执行 VACUUM 压缩...")
            t0 = time.time()
            vconn = sqlite3.connect(DB_PATH)
            vconn.execute("VACUUM")
            vconn.close()
            print(f"  [vacuum] 完成 ({time.time() - t0:.1f}s)")
        else:
            print(f"\n[vacuum] 空闲页 {fl}/{pc}，无需压缩")
    except Exception as e:
        print(f"  [vacuum] 跳过（异常）: {e}")


def backfill(start_day_str, end_day_str=None, chunk_days=DEFAULT_BACKFILL_CHUNK_DAYS, do_upload=True):
    """
    补采历史数据：从 start_day_str 到 end_day_str（默认今天），
    按 chunk_days 天分片，每片经 fetch_availability_range 拉取并 UPSERT 写入本地 DB；
    全部分片完成后统一 FTP 上传一次远程。

    写法是按主键覆盖（INSERT OR REPLACE），因此：
      - 重跑不会产生重复行；
      - 若某分片失败留空，可重复执行 backfill 补齐（幂等）。
    """
    start = _utc_day_midnight(
        datetime.strptime(start_day_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    )
    if end_day_str:
        end = _utc_day_midnight(
            datetime.strptime(end_day_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        )
    else:
        end = _utc_day_midnight(datetime.now(timezone.utc))

    if start >= end:
        print(f"[BACKFILL] 起始日 {start.date()} >= 结束日 {end.date()}，无需补采")
        return

    total_days = (end - start).days
    n_chunks = (total_days + chunk_days - 1) // chunk_days
    print("=" * 60)
    print(f"  [BACKFILL] 补采范围: {start.date()} ~ {end.date()} (chunk_days={chunk_days})")
    print(f"  [BACKFILL] 共约 {total_days} 天，将分 {n_chunks} 片")
    print("=" * 60)

    chunk_idx = 0
    total_tasks = 0
    cur = start
    while cur < end:
        chunk_end = min(cur + timedelta(days=chunk_days), end)
        print(f"\n[BACKFILL] === 分片 {chunk_idx}: {cur.date()} ~ {chunk_end.date()} ===")
        tasks = fetch_availability_range(cur, chunk_end)
        if tasks:
            run_write_pipeline(tasks, do_upload=False)
            total_tasks += len(tasks)
        else:
            print(f"  [WARN] 分片 {cur.date()}~{chunk_end.date()} 未获取到任何数据，跳过")
        cur = chunk_end
        chunk_idx += 1

    # 全部分片写完后，统一 VACUUM + 上传一次远程
    if do_upload:
        print(f"\n[BACKFILL] 所有 {chunk_idx} 个分片写入完成，VACUUM 压缩并统一 FTP 上传到远程 ...")
        _vacuum_db()
        try:
            ok = upload_to_ftp(DB_PATH, FTP_REMOTE_DIR, DB_NAME)
        except Exception as e:
            ok = False
            print(f"  [ERROR] FTP 上传异常: {e}")
        print(f"  [{'OK' if ok else 'WARN'}] 远程数据库更新: {ok}")
    else:
        print(f"\n[BACKFILL] 跳过 FTP 上传（do_upload=False）")

    print(f"\n[BACKFILL] 完成：{chunk_idx} 个分片，{total_tasks} 个模板数据写入本地 DB")


# ============================================================
# 主函数（每日模式，默认 2 天窗口）
# ============================================================
def main():
    t_total_start = time.time()
    start_time = datetime.now()
    print("=" * 60)
    print(f"  脚本开始时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  架构: 内存(xlsx bytes) → ProcessPoolExecutor → Queue → SQLite Writer")
    print(f"  DB: {DB_PATH}")
    print(f"  BATCH_SIZE: {BATCH_SIZE} | Workers: {MAX_WORKERS} | Queue: {QUEUE_MAX}")
    print("=" * 60)

    # ---- 1. 通过 RAN UME API 拉取（默认 2 天窗口）----
    t_find_start = time.time()
    print(f"\n[1/3] 通过 RAN UME API 拉取数据（每日 2 天窗口）...")
    tasks = fetch_availability_via_api(window_days=2)
    t_find_end = time.time()
    print(f"  拉取耗时: {t_find_end - t_find_start:.2f}s")

    if not tasks:
        print(f"\n[WARN] 未通过 API 获取到任何数据，退出")
        print(f"  请检查 RAN UME 连通性 / 鉴权，以及 AVAILABILITY_PM_CONFIGS 模板配置")
        return

    # ---- 2 & 3. 写入数据库 + FTP 上传 ----
    run_write_pipeline(tasks, do_upload=True)

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
    import argparse
    parser = argparse.ArgumentParser(
        description="RAN 小区可用性 1-day KPI（RAN UME API 拉取 + 主键覆盖写入）"
    )
    parser.add_argument(
        "--backfill", metavar="START", nargs="?", const="2026-01-01",
        help="补采历史数据：从 START(YYYY-MM-DD) 到今天；不传值默认 2026-01-01",
    )
    parser.add_argument("--end", metavar="END", default=None,
                        help="backfill 结束日 YYYY-MM-DD（默认今天）")
    parser.add_argument("--chunk-days", type=int, default=DEFAULT_BACKFILL_CHUNK_DAYS,
                        help=f"backfill 分片天数（默认 {DEFAULT_BACKFILL_CHUNK_DAYS}）")
    parser.add_argument("--window-days", type=int, default=2,
                        help="每日模式窗口天数（默认 2）")
    args = parser.parse_args()

    try:
        if args.backfill:
            backfill(args.backfill, end_day_str=args.end,
                     chunk_days=args.chunk_days, do_upload=True)
        else:
            # 每日模式（定时任务默认调用，无参数）
            tasks = fetch_availability_via_api(window_days=args.window_days)
            if tasks:
                run_write_pipeline(tasks, do_upload=True)
            else:
                print("[WARN] 未获取到数据，退出")
    except Exception as e:
        import traceback
        print(f"\n[FATAL ERROR] {e}")
        traceback.print_exc()
        sys.exit(1)
