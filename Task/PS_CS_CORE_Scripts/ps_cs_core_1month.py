# -*- coding: utf-8 -*-
"""
PS_CS_CORE 自动化脚本
功能：
  1. 从下载文件夹找到最新的 CSV 和 ZIP 文件
  2. 解析 CSV（直接读取）和 ZIP（内含 xlsx，内存直读不落盘）
  3. 通过 API 写入远程数据库 db_ps_cs_cn.sqlite3（表名前加 "1month_" 前缀）
  4. API 失败时回退到本地 SQLite + FTP 上传
"""

import os
import re
import csv
import sys
import io
import json
import time
import shutil
import sqlite3
import zipfile
import urllib.request
import urllib.error
from datetime import datetime
from ftplib import FTP, error_perm
from openpyxl import load_workbook

# 修复 Windows CMD 下中文输出编码问题（代码页936=GBK无法输出中文时强制使用UTF-8）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============================================================
# 配置
# ============================================================
# CSV 文件搜索目录：当前用户主目录（如 C:\Users\ZTEEMS）
CSV_SEARCH_DIR = os.path.expanduser("~")
# ZIP 文件搜索目录：下载文件夹
ZIP_SEARCH_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = "db_ps_cs_cn.sqlite3"
DB_PATH = os.path.join(DB_DIR, DB_NAME)

# 远程写入 API 配置（API 优先，FTP 回退）
API_HOST = os.environ.get("DB_WRITER_HOST", "192.168.100.19")
API_PORT = int(os.environ.get("DB_WRITER_PORT", "8765"))
API_BASE_URL = f"http://{API_HOST}:{API_PORT}"
API_TIMEOUT = 900  # 秒
API_MAX_RETRIES = 3

FTP_HOST = "192.168.100.19"
FTP_USER = "ZTEEMS"
FTP_PASS = "DX"
FTP_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI"

# 列表1：CSV 文件关键字（从 OSS 导出的 History Performance CSV）
CSV_TEMPLATES = [
    "VOICE_TRAFFIC_TEMPLATE_OSS",
    "VLR_SUBSCRIBERS_TEMPLATE_OSS",
    "USSD_RATIO_TEMPLATE_OSS",
    "TDD_DATA_TRAFFIC_TEMPLATE_OSS",
    "LOCATION_UPDATE_TEMPLATE_OSS",
    "LICENSE_OCCUPANCY_TEMPLATE_OSS",
    "DATA_SUBSCRIBERS_TEMPLATE_OSS",
]

# 列表2：ZIP 文件关键字（内含 xlsx）
ZIP_TEMPLATES = [
    "xGW_LICENSE_OCCUPANCY_TEMPLATE_OSS",
    "VOICE_TRAFFIC_TEMPLATE_OSS",
    "VLR_SUBSCRIBERS_TEMPLATE_OSS",
    "DATA_SUBSCRIBERS_TEMPLATE_OSS",
    "3G_FDD_DATA_TRAFFIC_TEMPLATE_OSS",
    "4G_FDD_DATA_TRAFFIC_TEMPLATE_OSS",
    "FREE_RATING_GROUP_TEMPLATE_OSS_update",
    "xGW_CPU_USAGE_TEMPLATE_OSS_UME",
]


# ============================================================
# 工具函数
# ============================================================
# 扫描噪音目录：这些目录里没有报表附件，但文件量最大（影刀 venv / CEF 缓存 / 浏览器 profile）
SEARCH_PRUNE_DIRS = {"AppData", "node_modules", "__pycache__", "venv310", "$RECYCLE.BIN", "System Volume Information"}
SEARCH_MAX_DEPTH = 4


def _iter_candidate_files(directory, max_depth=SEARCH_MAX_DEPTH):
    """有界遍历，产出 (路径, mtime)。跳过噪音目录与隐藏目录，不跟随符号链接/junction。"""
    stack = [(directory, 0)]
    while stack:
        path, depth = stack.pop()
        try:
            with os.scandir(path) as it:
                entries = list(it)
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_file(follow_symlinks=False):
                    yield e.path, e.stat(follow_symlinks=False).st_mtime
                elif e.is_dir(follow_symlinks=False):
                    if e.name in SEARCH_PRUNE_DIRS or e.name.startswith("."):
                        continue
                    if depth < max_depth:
                        stack.append((e.path, depth + 1))
            except OSError:
                continue


def find_latest_files(directory, keywords, extension):
    """
    单次遍历目录，为每个 keyword 各找出文件名含该 keyword 且后缀为 extension 的最新文件。
    返回 {keyword: (路径, mtime)}；未命中的 keyword 不出现在结果中。
    """
    best = {}
    suffix = extension.lower()
    pairs = [(kw.lower(), kw) for kw in keywords]
    for path, mtime in _iter_candidate_files(directory):
        name = os.path.basename(path).lower()
        if not name.endswith(suffix):
            continue
        for kw_l, kw in pairs:
            if kw_l in name and (kw not in best or mtime > best[kw][1]):
                best[kw] = (path, mtime)
    return best


def sanitize_table_name(name):
    """将模板名转为合法的 SQLite 表名"""
    return re.sub(r'[^A-Za-z0-9_]', '_', name)


# ============================================================
# CSV 解析（列表1）
# ============================================================
def parse_csv_file(filepath):
    """
    解析 OSS 导出的 CSV 文件。
    格式：前5行是元数据，第6行是表头，之后是数据行。
    返回 (headers: list, rows: list of tuples, metadata: dict)
    """
    metadata = {}
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    # 解析元数据（前5行）
    for line in lines[:5]:
        line = line.strip()
        if ":" in line:
            key, _, val = line.partition(":")
            metadata[key.strip()] = val.strip().lstrip(", ").strip()

    # 找到表头行（包含 Start Time 的行）
    header_idx = None
    for i, line in enumerate(lines):
        if "Start Time" in line or "Index," in line:
            header_idx = i
            break

    if header_idx is None:
        print(f"  [WARNING] 未找到表头: {filepath}")
        return None, [], metadata

    headers = [h.strip() for h in lines[header_idx].split(",")]
    rows = []
    for line in lines[header_idx + 1:]:
        line = line.strip()
        if not line:
            continue
        parts = [v.strip() for v in line.split(",")]
        rows.append(tuple(parts))

    return headers, rows, metadata


def write_csv_to_db(conn, table_name, headers, rows):
    """将 CSV 数据写入 SQLite 表（替换已有数据）"""
    cursor = conn.cursor()
    cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')

    col_defs = ", ".join(f'"{h}" TEXT' for h in headers)
    cursor.execute(f'CREATE TABLE "{table_name}" ({col_defs})')

    placeholders = ", ".join("?" for _ in headers)
    insert_sql = f'INSERT INTO "{table_name}" VALUES ({placeholders})'
    cursor.executemany(insert_sql, rows)
    conn.commit()
    print(f"  [OK] CSV -> 表 '{table_name}'：{len(rows)} 行")


# ============================================================
# ZIP/XLSX 解析（列表2）—— 内存直读，不解压到临时目录
# ============================================================
def parse_zip_xlsx(filepath, keyword):
    """
    从 ZIP 内存直读 xlsx 文件内容（不落盘）。
    返回 (headers, rows) 或 (None, []) 如果失败。
    """
    with zipfile.ZipFile(filepath, "r") as zf:
        xlsx_names = [n for n in zf.namelist() if n.lower().endswith(".xlsx")]
        if not xlsx_names:
            print(f"  [WARNING] ZIP 中未找到 xlsx: {filepath}")
            return None, []

        xlsx_bytes = zf.read(xlsx_names[0])

    wb = load_workbook(io.BytesIO(xlsx_bytes), data_only=True, read_only=True)
    try:
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        headers = [str(c).strip() if c is not None else "" for c in next(rows_iter)]
        rows = []
        for row in rows_iter:
            rows.append(tuple(str(c) if c is not None else "" for c in row))
    finally:
        wb.close()

    return headers, rows


def write_xlsx_to_db(conn, table_name, headers, rows):
    """将 xlsx 数据写入 SQLite 表"""
    cursor = conn.cursor()
    cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')

    col_defs = ", ".join(f'"{h}" TEXT' for h in headers)
    cursor.execute(f'CREATE TABLE "{table_name}" ({col_defs})')

    placeholders = ", ".join("?" for _ in headers)
    insert_sql = f'INSERT INTO "{table_name}" VALUES ({placeholders})'
    cursor.executemany(insert_sql, rows)
    conn.commit()
    print(f"  [OK] XLSX -> 表 '{table_name}'：{len(rows)} 行")


# ============================================================
# API 写入（优先）
# ============================================================
def write_via_api(table_name, headers, rows):
    """通过 HTTP API 写入远程数据库，返回 (success, rows_written)"""
    payload = {
        "db": DB_NAME,
        "table": table_name,
        "columns": headers,
        "rows": [list(r) for r in rows],
        "mode": "full_replace",
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    for attempt in range(1, API_MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                f"{API_BASE_URL}/api/write",
                data=data,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            rows_written = result.get("rows_written", 0)
            if rows_written == 0:
                raise Exception(f"API 返回 0 行写入")
            return True, rows_written
        except Exception as e:
            if attempt < API_MAX_RETRIES:
                wait = 2 ** attempt
                print(f"  [API] 失败({e})，{wait}s 后重试 ({attempt}/{API_MAX_RETRIES})...")
                time.sleep(wait)
            else:
                print(f"  [API] 最终失败: {e}")
    return False, 0


# ============================================================
# 本地 SQLite 写入（回退）
# ============================================================
# ============================================================
# FTP 上传（仅回退模式使用）
# ============================================================
def upload_to_ftp(local_path, remote_dir, filename, max_retries=2):
    """上传文件到 FTP 服务器（带重试机制）"""
    for attempt in range(1, max_retries + 1):
        print(f"\n[FTP] 连接 {FTP_HOST} ...（第 {attempt} 次）")
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


# ============================================================
# 主流程
# ============================================================
def main():
    t_start = time.time()
    print("=" * 60)
    print(f"PS_CS_CORE 自动化脚本 - {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 60)
    print(f"数据源:   CSV -> {CSV_SEARCH_DIR}")
    print(f"          ZIP -> {ZIP_SEARCH_DIR}")
    print(f"写入目标: API {API_BASE_URL} -> {DB_NAME}")
    print(f"回退:     本地 {DB_PATH} + FTP")

    # 本地 SQLite 仅用于 _update_log 跟踪 + API 失败时的回退写入
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS _update_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template TEXT,
            source_type TEXT,
            source_file TEXT,
            update_time TEXT
        )
    """)
    conn.commit()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    api_failed_tables = []  # 记录 API 写入失败的表，最后回退本地+FTP

    # ---- 处理列表1：CSV 文件 ----
    print("\n--- 处理 CSV 文件（列表1）搜索目录: " + CSV_SEARCH_DIR + " ---")
    csv_count = 0
    csv_hits = find_latest_files(CSV_SEARCH_DIR, CSV_TEMPLATES, ".csv")
    for template in CSV_TEMPLATES:
        print(f"\n[{template}]")
        filepath = csv_hits.get(template, (None, 0))[0]
        if not filepath:
            print(f"  [SKIP] 未找到匹配的 CSV 文件")
            continue

        file_mtime = os.path.getmtime(filepath)
        print(f"  文件: {os.path.basename(filepath)}")
        print(f"  修改时间: {datetime.fromtimestamp(file_mtime):%Y-%m-%d %H:%M:%S}")

        # 检查是否比数据库中已有数据更旧（防止老文件覆盖新数据）
        table_name = "1month_" + sanitize_table_name(template) + "_EMS"
        cursor.execute(
            "SELECT MAX(source_file) FROM _update_log WHERE template=? AND source_type='CSV'",
            (template,)
        )
        last_source = cursor.fetchone()[0]
        if last_source:
            def extract_ts(filename):
                m = re.search(r'(\d{14})', filename)
                return m.group(1) if m else ""
            last_ts = extract_ts(last_source)
            curr_ts = extract_ts(os.path.basename(filepath))
            if last_ts and curr_ts and curr_ts < last_ts:
                print(f"  [SKIP] 当前文件比已入库文件更旧（已有: {last_source}），跳过")
                continue

        headers, rows, meta = parse_csv_file(filepath)
        if headers and rows:
            # API 优先写入
            ok, rows_written = write_via_api(table_name, headers, rows)
            if ok:
                print(f"  [API] 表 '{table_name}'：{rows_written} 行")
            else:
                # 回退到本地 SQLite
                write_csv_to_db(conn, table_name, headers, rows)
                api_failed_tables.append(table_name)

            # 删除已处理的 CSV 文件
            try:
                os.remove(filepath)
                print(f"  [OK] 已删除: {os.path.basename(filepath)}")
            except Exception as e:
                print(f"  [WARNING] 删除失败: {e}")

            cursor.execute(
                "INSERT INTO _update_log (template, source_type, source_file, update_time) VALUES (?,?,?,?)",
                (template, "CSV", os.path.basename(filepath), now_str)
            )
            conn.commit()
            csv_count += 1

    print(f"\nCSV 处理完成: {csv_count}/{len(CSV_TEMPLATES)} 个模板")

    # ---- 处理列表2：ZIP 文件（含 xlsx）----
    print("\n--- 处理 ZIP/XLSX 文件（列表2）搜索目录: " + ZIP_SEARCH_DIR + " ---")
    zip_count = 0
    zip_hits = find_latest_files(ZIP_SEARCH_DIR, ZIP_TEMPLATES, ".zip")
    for template in ZIP_TEMPLATES:
        print(f"\n[{template}]")
        filepath = zip_hits.get(template, (None, 0))[0]
        if not filepath:
            print(f"  [SKIP] 未找到匹配的 ZIP 文件")
            continue

        print(f"  文件: {os.path.basename(filepath)}")
        print(f"  修改时间: {datetime.fromtimestamp(os.path.getmtime(filepath)):%Y-%m-%d %H:%M:%S}")

        headers, rows = parse_zip_xlsx(filepath, template)
        if headers and rows:
            table_name = "1month_" + sanitize_table_name(template) + "_UME"

            # API 优先写入
            ok, rows_written = write_via_api(table_name, headers, rows)
            if ok:
                print(f"  [API] 表 '{table_name}'：{rows_written} 行")
            else:
                # 回退到本地 SQLite
                write_xlsx_to_db(conn, table_name, headers, rows)
                api_failed_tables.append(table_name)

            # 删除已处理的 ZIP 文件
            try:
                os.remove(filepath)
                print(f"  [OK] 已删除: {os.path.basename(filepath)}")
            except Exception as e:
                print(f"  [WARNING] 删除失败: {e}")

            cursor.execute(
                "INSERT INTO _update_log (template, source_type, source_file, update_time) VALUES (?,?,?,?)",
                (template, "ZIP/XLSX", os.path.basename(filepath), now_str)
            )
            conn.commit()
            zip_count += 1

    print(f"\nZIP/XLSX 处理完成: {zip_count}/{len(ZIP_TEMPLATES)} 个模板")

    conn.close()

    # ---- API 失败时回退写本地 SQLite（不做 FTP 上传）----
    if api_failed_tables:
        print(f"\n[回退] {len(api_failed_tables)} 个表已写入本地 SQLite: {DB_PATH}")
    else:
        print("\n[结果] 全部通过 API 写入远程")

    elapsed = time.time() - t_start
    print("\n" + "=" * 60)
    print(f"执行完毕！用时: {elapsed:.2f} 秒")
    print(f"写入方式: {'API 全部成功' if not api_failed_tables else f'API 失败 {len(api_failed_tables)} 个表，已回退 FTP'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
