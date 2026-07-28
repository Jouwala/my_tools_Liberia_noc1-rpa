# -*- coding: utf-8 -*-
"""
SQLite 远程写入代理服务 (部署在 192.168.100.19)

功能：
- 接收 HTTP POST 请求，将数据安全写入本地 SQLite 数据库（WAL 模式）
- 支持两种写入模式：upsert（INSERT OR REPLACE）和 dedup_insert（按主键去重插入）
- 支持 Excel 文件上传导入
- 串行化写入，保证多数据源并发安全

部署方式：
  pip install fastapi uvicorn pandas openpyxl python-multipart
  python db_writer_api.py

默认监听: 0.0.0.0:8765
"""

import os
import re
import sys
import time
import sqlite3
import threading
import tempfile
from typing import Optional
from datetime import datetime
from contextlib import contextmanager

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# ============================================================
# 配置
# ============================================================
# 数据库文件路径（根据实际部署路径修改）
DB_MAIN_PATH = r"C:\FineBI6.0\webapps\Python\db.sqlite3"
DB_DAILY_PATH = r"E:\01_RPA\LBR_Tools\KPI\RAN\ran_kpi_daily.sqlite3"
DB_ORANGE_PATH = r"E:\01_RPA\LBR_Tools\KPI\RAN\ran_kpi_daily_202606.sqlite3"
DB_CNN_PATH = r"E:\01_RPA\LBR_Tools\KPI\CNN\db_ps_cs_cn.sqlite3"


API_HOST = "0.0.0.0"
API_PORT = 8765

# 写入锁（保证串行写入，WAL 安全）
_write_lock = threading.Lock()

app = FastAPI(title="SQLite Writer API", version="1.0.0")

# 主键列候选（用于去重）
TIME_PK_CANDIDATES = [
    "Begin Time", "Begin Time(Period)", "BeginTime", "Period", "Time", "Date"
]
CELL_PK_CANDIDATES = [
    "Cell Name", "Cell", "UtranCell", "EUtranCellFDD", "MO", "Name"
]
SITE_PK_CANDIDATES = [
    "Site Name", "Site", "BTSSite", "eNodeB Name", "eNodeB", "BTS", "MO", "Name"
]
GROUP_PK_CANDIDATES = [
    "Group", "Group Name", "Group ID", "MO", "Name"
]


# ============================================================
# 工具函数
# ============================================================
def _get_db_path(db_name: str) -> str:
    """根据逻辑名称返回实际数据库文件路径。"""
    mapping = {
        "db.sqlite3": DB_MAIN_PATH,
        "ran_kpi_daily.sqlite3": DB_DAILY_PATH,
        "ran_kpi_daily_202606.sqlite3": DB_ORANGE_PATH,
        "db_ps_cs_cn.sqlite3": DB_CNN_PATH,
    }
    path = mapping.get(db_name)
    if not path:
        raise HTTPException(status_code=400, detail=f"Unknown database: {db_name}")
    return path


def _strip_item_prefix(col_name: str) -> str:
    """去掉列名中的 {item_id}: 前缀。"""
    m = re.match(r'^\d+:(.+)', col_name)
    return m.group(1) if m else col_name


def _quote(name: str) -> str:
    return f'"{name}"'


@contextmanager
def _open_db(db_path: str):
    """打开数据库连接（WAL 模式 + 性能优化）。"""
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA cache_size=-64000")
    try:
        yield conn
    finally:
        conn.close()


def _get_table_columns(conn: sqlite3.Connection, table_name: str) -> list:
    """获取表的列名列表。"""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({_quote(table_name)})")
    return [col[1] for col in cursor.fetchall()]


def _add_missing_columns(conn: sqlite3.Connection, table_name: str, new_columns: list):
    """自动添加缺失列（支持 item_id 前缀模糊匹配）。"""
    db_cols = _get_table_columns(conn, table_name)
    db_cols_normalized = {_strip_item_prefix(c): c for c in db_cols}

    missing = []
    for col in new_columns:
        normalized = _strip_item_prefix(col)
        if normalized not in db_cols_normalized and col not in db_cols:
            missing.append(col)

    if missing:
        cursor = conn.cursor()
        for col in missing:
            try:
                cursor.execute(
                    f"ALTER TABLE {_quote(table_name)} ADD COLUMN {_quote(col)} NUMERIC"
                )
            except Exception:
                pass
        conn.commit()


def _detect_primary_keys(table_type: str, columns: list) -> list:
    """根据表类型和列名自动检测主键列。"""
    time_col = next((c for c in TIME_PK_CANDIDATES if c in columns), None)

    if table_type == "Cells":
        entity_col = next((c for c in CELL_PK_CANDIDATES if c in columns), None)
    elif table_type == "Sites":
        entity_col = next((c for c in SITE_PK_CANDIDATES if c in columns), None)
    else:
        entity_col = next((c for c in GROUP_PK_CANDIDATES if c in columns), None)

    pk_cols = []
    if time_col:
        pk_cols.append(time_col)
    if entity_col:
        pk_cols.append(entity_col)
    return pk_cols


# ============================================================
# API 端点
# ============================================================
@app.get("/health")
def health():
    """健康检查。"""
    return {
        "status": "ok",
        "time": datetime.now().isoformat(),
        "db_main": DB_MAIN_PATH,
        "db_main_exists": os.path.exists(DB_MAIN_PATH),
        "db_daily": DB_DAILY_PATH,
        "db_daily_exists": os.path.exists(DB_DAILY_PATH),
        "db_orange": DB_ORANGE_PATH,
        "db_orange_exists": os.path.exists(DB_ORANGE_PATH),
        "db_cnn": DB_CNN_PATH,
        "db_cnn_exists": os.path.exists(DB_CNN_PATH),
    }


@app.post("/api/write")
def write_data(payload: dict):
    """
    通用数据写入接口。

    请求体 JSON:
    {
        "db": "db.sqlite3" | "ran_kpi_daily.sqlite3",
        "table": "表名",
        "columns": ["col1", "col2", ...],
        "rows": [[val1, val2, ...], ...],
        "mode": "upsert" | "dedup_insert" | "full_replace",
        "pk_columns": ["Begin Time", "Group"],       // upsert 模式必须
        "table_type": "Cells" | "Sites" | "Group" | "NW"  // dedup_insert 模式可选
    }
    """
    db_name = payload.get("db")
    table_name = payload.get("table")
    columns = payload.get("columns")
    rows = payload.get("rows")
    mode = payload.get("mode", "upsert")
    pk_columns = payload.get("pk_columns")
    table_type = payload.get("table_type", "Group")

    if not all([db_name, table_name, columns, rows]):
        raise HTTPException(status_code=400, detail="Missing required fields: db, table, columns, rows")

    db_path = _get_db_path(db_name)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    row_count = len(rows)
    col_count = len(columns)

    with _write_lock:
        with _open_db(db_path) as conn:
            cursor = conn.cursor()

            # 检查表是否存在
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            table_exists = cursor.fetchone() is not None

            if mode == "upsert":
                # ---- INSERT OR REPLACE 模式 ----
                if not pk_columns:
                    raise HTTPException(status_code=400, detail="pk_columns required for upsert mode")

                if not table_exists:
                    # 创建表，主键列 NOT NULL
                    pk_defs = []
                    col_defs = []
                    for c in columns:
                        safe = c.replace('"', '""')
                        if c in pk_columns:
                            col_defs.append(f'"{safe}" TEXT NOT NULL')
                        else:
                            col_defs.append(f'"{safe}" TEXT')
                    pk_str = ", ".join(f'"{c.replace(chr(34), chr(34)+chr(34))}"' for c in pk_columns)
                    create_sql = (
                        f'CREATE TABLE "{table_name}" (\n'
                        f'  {", ".join(col_defs)},\n'
                        f'  PRIMARY KEY ({pk_str})\n'
                        f')'
                    )
                    cursor.execute(create_sql)
                else:
                    _add_missing_columns(conn, table_name, columns)

                # 批量 INSERT OR REPLACE
                quoted_cols = [f'"{c.replace(chr(34), chr(34)+chr(34))}"' for c in columns]
                placeholders = ", ".join(["?"] * col_count)
                insert_sql = (
                    f'INSERT OR REPLACE INTO "{table_name}" '
                    f'({", ".join(quoted_cols)}) VALUES ({placeholders})'
                )

                batch_size = 5000
                inserted = 0
                for i in range(0, row_count, batch_size):
                    batch = rows[i:i + batch_size]
                    # 补齐/截断列数
                    clean_batch = []
                    for row in batch:
                        if len(row) < col_count:
                            row = row + [None] * (col_count - len(row))
                        elif len(row) > col_count:
                            row = row[:col_count]
                        clean_batch.append([str(v) if v is not None else None for v in row])
                    cursor.executemany(insert_sql, clean_batch)
                    inserted += len(clean_batch)

                conn.commit()
                return {"success": True, "rows_written": inserted, "table": table_name, "mode": "upsert"}

            elif mode == "dedup_insert":
                # ---- 按主键去重插入模式 ----
                if not table_exists:
                    # 表不存在，直接创建并全量插入
                    df = pd.DataFrame(rows, columns=columns)
                    df.to_sql(table_name, conn, if_exists='replace', index=False)
                    conn.commit()
                    return {"success": True, "rows_written": row_count, "table": table_name, "mode": "dedup_insert(new_table)"}

                # 自动添加缺失列
                _add_missing_columns(conn, table_name, columns)

                # 列名映射（支持 item_id 前缀匹配）
                db_columns = _get_table_columns(conn, table_name)
                db_norm_map = {_strip_item_prefix(c): c for c in db_columns}

                col_rename = {}
                for ec in columns:
                    if ec in db_columns:
                        col_rename[ec] = ec
                    else:
                        norm = _strip_item_prefix(ec)
                        if norm in db_norm_map:
                            col_rename[ec] = db_norm_map[norm]

                # 重命名列
                mapped_columns = [col_rename.get(c, c) for c in columns]

                # 取共有列
                common_columns = [c for c in db_columns if c in mapped_columns]
                if not common_columns:
                    raise HTTPException(status_code=400, detail=f"No common columns between data and table {table_name}")

                # 获取共有列在原始 columns 中的索引
                common_indices = []
                for cc in common_columns:
                    if cc in mapped_columns:
                        common_indices.append(mapped_columns.index(cc))

                # 检测主键
                if pk_columns:
                    pk_cols = pk_columns
                else:
                    pk_cols = _detect_primary_keys(table_type, common_columns)
                if len(pk_cols) < 2:
                    pk_cols = common_columns

                # 写入临时表
                temp_table = f"_temp_{table_name}_{int(time.time())}"
                temp_cols = [common_columns[i] for i in range(len(common_indices))]

                # 提取共有列数据
                temp_data = []
                for row in rows:
                    temp_row = []
                    for idx in common_indices:
                        val = row[idx] if idx < len(row) else None
                        temp_row.append(str(val) if val is not None else None)
                    temp_data.append(temp_row)

                # 创建临时表并插入
                temp_col_defs = ", ".join(f'"{c.replace(chr(34), chr(34)+chr(34))}" TEXT' for c in temp_cols)
                cursor.execute(f'CREATE TEMP TABLE "{temp_table}" ({temp_col_defs})')

                placeholders = ", ".join(["?"] * len(temp_cols))
                temp_insert = f'INSERT INTO "{temp_table}" VALUES ({placeholders})'

                batch_size = 5000
                for i in range(0, len(temp_data), batch_size):
                    cursor.executemany(temp_insert, temp_data[i:i + batch_size])

                # LEFT JOIN 去重插入
                pk_conditions = " AND ".join(f't."{pk}" = m."{pk}"' for pk in pk_cols)
                cols_str = ", ".join(f'"{c}"' for c in temp_cols)
                cols_str_t = ", ".join(f't."{c}"' for c in temp_cols)

                dedup_sql = (
                    f'INSERT INTO "{table_name}" ({cols_str}) '
                    f'SELECT {cols_str_t} FROM "{temp_table}" t '
                    f'LEFT JOIN "{table_name}" m ON {pk_conditions} '
                    f'WHERE m."{pk_cols[0]}" IS NULL'
                )
                cursor.execute(dedup_sql)
                inserted = cursor.rowcount
                conn.commit()

                # 清理临时表
                cursor.execute(f'DROP TABLE IF EXISTS "{temp_table}"')
                conn.commit()

                return {"success": True, "rows_written": inserted, "table": table_name, "mode": "dedup_insert"}

            elif mode == "full_replace":
                # ---- 全量替换模式：DROP 旧表 → 重建 → 写入 ----
                if table_exists:
                    cursor.execute(f'DROP TABLE "{table_name}"')

                col_defs = ", ".join(f'"{ c.replace(chr(34), chr(34)+chr(34)) }" TEXT' for c in columns)
                cursor.execute(f'CREATE TABLE "{table_name}" ({col_defs})')

                quoted_cols = [f'"{ c.replace(chr(34), chr(34)+chr(34)) }"' for c in columns]
                placeholders = ", ".join(["?"] * col_count)
                insert_sql = f'INSERT INTO "{table_name}" ({", ".join(quoted_cols)}) VALUES ({placeholders})'

                batch_size = 5000
                inserted = 0
                for i in range(0, row_count, batch_size):
                    batch = rows[i:i + batch_size]
                    clean_batch = []
                    for row in batch:
                        if len(row) < col_count:
                            row = row + [None] * (col_count - len(row))
                        elif len(row) > col_count:
                            row = row[:col_count]
                        clean_batch.append([str(v) if v is not None else None for v in row])
                    cursor.executemany(insert_sql, clean_batch)
                    inserted += len(clean_batch)

                conn.commit()
                return {"success": True, "rows_written": inserted, "table": table_name, "mode": "full_replace"}

            else:
                raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")


@app.post("/api/upload_excel")
async def upload_excel(
    file: UploadFile = File(...),
    db: str = Form(...),
    table: str = Form(...),
    table_type: str = Form("Group"),
    add_group_column: bool = Form(False),
    group_value: str = Form("NW"),
):
    """
    上传 Excel 文件并导入数据库（dedup_insert 模式）。

    参数：
    - file: xlsx 文件
    - db: 数据库名称 (db.sqlite3 / ran_kpi_daily.sqlite3)
    - table: 目标表名
    - table_type: Cells / Sites / Group / NW
    - add_group_column: 是否添加 Group 列
    - group_value: Group 列的值（默认 NW）
    """
    db_path = _get_db_path(db)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    # 保存上传文件到临时目录
    suffix = os.path.splitext(file.filename or "upload.xlsx")[1] or ".xlsx"
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        content = await file.read()
        with os.fdopen(tmp_fd, 'wb') as f:
            f.write(content)

        # 读取 Excel
        df = pd.read_excel(tmp_path)
        if add_group_column:
            df['Group'] = group_value

        columns = df.columns.tolist()
        rows = df.values.tolist()
        row_count = len(rows)

        # 转换为字符串（None 保持 None）
        str_rows = []
        for row in rows:
            str_rows.append([str(v) if pd.notna(v) else None for v in row])

        # 调用内部写入逻辑
        with _write_lock:
            with _open_db(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,)
                )
                table_exists = cursor.fetchone() is not None

                if not table_exists:
                    df.to_sql(table, conn, if_exists='replace', index=False)
                    conn.commit()
                    return {"success": True, "rows_written": row_count, "table": table, "mode": "new_table"}

                _add_missing_columns(conn, table, columns)
                db_columns = _get_table_columns(conn, table)
                db_norm_map = {_strip_item_prefix(c): c for c in db_columns}

                col_rename = {}
                for ec in columns:
                    if ec in db_columns:
                        col_rename[ec] = ec
                    else:
                        norm = _strip_item_prefix(ec)
                        if norm in db_norm_map:
                            col_rename[ec] = db_norm_map[norm]

                mapped_columns = [col_rename.get(c, c) for c in columns]
                common_columns = [c for c in db_columns if c in mapped_columns]

                if not common_columns:
                    raise HTTPException(status_code=400, detail="No common columns")

                common_indices = [mapped_columns.index(cc) for cc in common_columns]
                pk_cols = _detect_primary_keys(table_type, common_columns)
                if len(pk_cols) < 2:
                    pk_cols = common_columns

                # 临时表去重
                temp_table = f"_temp_{table}_{int(time.time())}"
                temp_col_defs = ", ".join(f'"{c.replace(chr(34), chr(34)+chr(34))}" TEXT' for c in common_columns)
                cursor.execute(f'CREATE TEMP TABLE "{temp_table}" ({temp_col_defs})')

                temp_data = []
                for row in str_rows:
                    temp_row = [row[idx] if idx < len(row) else None for idx in common_indices]
                    temp_data.append(temp_row)

                placeholders = ", ".join(["?"] * len(common_columns))
                temp_insert = f'INSERT INTO "{temp_table}" VALUES ({placeholders})'
                batch_size = 5000
                for i in range(0, len(temp_data), batch_size):
                    cursor.executemany(temp_insert, temp_data[i:i + batch_size])

                pk_conditions = " AND ".join(f't."{pk}" = m."{pk}"' for pk in pk_cols)
                cols_str = ", ".join(f'"{c}"' for c in common_columns)
                cols_str_t = ", ".join(f't."{c}"' for c in common_columns)

                dedup_sql = (
                    f'INSERT INTO "{table}" ({cols_str}) '
                    f'SELECT {cols_str_t} FROM "{temp_table}" t '
                    f'LEFT JOIN "{table}" m ON {pk_conditions} '
                    f'WHERE m."{pk_cols[0]}" IS NULL'
                )
                cursor.execute(dedup_sql)
                inserted = cursor.rowcount
                conn.commit()

                cursor.execute(f'DROP TABLE IF EXISTS "{temp_table}"')
                conn.commit()

        return {"success": True, "rows_written": inserted, "table": table, "mode": "dedup_insert"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.post("/api/dedup")
def dedup_table(payload: dict):
    """
    删除表中基于指定列的重复行（保留 rowid 最小的一条）。

    请求体 JSON:
    {
        "db": "db.sqlite3",
        "table": "表名",
        "pk_columns": ["Begin Time", "Cell Name"]   // 去重依据列
    }

    如果不传 pk_columns，则自动根据 table_type 检测。
    可选参数 "table_type": "Cells" / "Sites" / "Group" / "NW"
    """
    db_name = payload.get("db")
    table_name = payload.get("table")
    pk_columns = payload.get("pk_columns")
    table_type = payload.get("table_type", "Group")

    if not db_name or not table_name:
        raise HTTPException(status_code=400, detail="Missing required fields: db, table")

    db_path = _get_db_path(db_name)
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail=f"Database not found: {db_name}")

    with _write_lock:
        with _open_db(db_path) as conn:
            cursor = conn.cursor()

            # 检查表存在
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail=f"Table not found: {table_name}")

            # 获取列名
            db_columns = _get_table_columns(conn, table_name)

            # 确定去重列
            if not pk_columns:
                pk_columns = _detect_primary_keys(table_type, db_columns)
            if not pk_columns:
                raise HTTPException(status_code=400, detail="Cannot determine dedup columns, please provide pk_columns")

            # 验证列存在
            for pk in pk_columns:
                if pk not in db_columns:
                    raise HTTPException(status_code=400, detail=f"Column '{pk}' not found in table {table_name}")

            # 统计去重前行数
            cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            before_count = cursor.fetchone()[0]

            # 删除重复行：保留 rowid 最小的
            pk_group = ", ".join(f'"{pk}"' for pk in pk_columns)
            delete_sql = (
                f'DELETE FROM "{table_name}" WHERE rowid NOT IN ('
                f'  SELECT MIN(rowid) FROM "{table_name}" GROUP BY {pk_group}'
                f')'
            )
            cursor.execute(delete_sql)
            deleted = cursor.rowcount
            conn.commit()

            after_count = before_count - deleted

    return {
        "success": True,
        "table": table_name,
        "pk_columns": pk_columns,
        "rows_before": before_count,
        "rows_deleted": deleted,
        "rows_after": after_count,
    }


@app.get("/api/tables")
def list_tables(db: str):
    """列出数据库中的所有表及行数。"""
    db_path = _get_db_path(db)
    if not os.path.exists(db_path):
        return {"tables": [], "db_exists": False}

    with _open_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = []
        for (name,) in cursor.fetchall():
            cursor.execute(f'SELECT COUNT(*) FROM "{name}"')
            count = cursor.fetchone()[0]
            tables.append({"name": name, "rows": count})
    return {"tables": tables, "db_exists": True}


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    total_start = time.time()
    print(f"[API] SQLite Writer API starting...")
    print(f"[API] DB Main:   {DB_MAIN_PATH} (exists={os.path.exists(DB_MAIN_PATH)})")
    print(f"[API] DB Daily:  {DB_DAILY_PATH} (exists={os.path.exists(DB_DAILY_PATH)})")
    print(f"[API] DB Orange: {DB_ORANGE_PATH} (exists={os.path.exists(DB_ORANGE_PATH)})")
    print(f"[API] DB CNN:    {DB_CNN_PATH} (exists={os.path.exists(DB_CNN_PATH)})")
    print(f"[API] Listening on {API_HOST}:{API_PORT}")

    uvicorn.run(app, host=API_HOST, port=API_PORT, log_level="info")

    elapsed = time.time() - total_start
    print(f"[API] Server stopped. Runtime: {elapsed:.1f}s")
