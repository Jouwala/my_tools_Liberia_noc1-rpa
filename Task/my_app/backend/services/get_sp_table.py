"""
import logging
SP（备件）数据同步服务。

从远端 SFTP 服务器（10.100.20.11）拉取 5 份备件管理 Excel 报表，
归一化后写入 my_app 的 SQLite 数据库 db/app.db，供「仓库看板」展示。

表名与 WareHouseDashBoard 保持一致：
  - inband_details   （Inbound  Ticket，sp/spinbound）
  - outband_details  （Outbound Ticket，sp/spoutbound）
  - inventory_details（Inventory，       sp/spinventory，增量去重）
  - ocrule_details   （OC Rule，         OCAuto/OCAutoOutput，递归找 csv→excel）
  - transfer_details  （WH Transfer，    sp/sp-wh_transfer，递归找 xlsx）

可直接作为任务集成进任务管理（run_sp_data_sync）。
"""
import os
import stat
import sys
import io
import time
import socket
from datetime import datetime
from pathlib import Path

import paramiko
import pandas as pd
from backend.database import get_raw_connection

try:
    from .atomic_write import atomic_to_excel
except ImportError:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:get_sp_table>: exception swallowed", exc_info=True)
    from atomic_write import atomic_to_excel

# 强制 stdout / stderr 为 utf-8，避免中文乱码
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# ====== 路径配置 ======
SERVICE_DIR = Path(__file__).resolve().parent          # backend/services
BACKEND_DIR = SERVICE_DIR.parent                       # backend
# 注意：app.db 实际位于**项目根** db/ 下（与 database.py 一致），不是 backend/db/
DB_PATH = SERVICE_DIR.parent.parent / 'db' / 'app.db'
SP_DATA_DIR = BACKEND_DIR / 'data' / 'sp'

# ====== SFTP 连接配置 ======
SFTP_HOST = "10.100.20.11"
SFTP_PORT = 22
SFTP_USER = "ubuntu"
SFTP_PASS = "UbuntU1!2@3#4$"

# 5 份报表的下载定义
SP_TABLES = {
    "inband_details": {
        "remote_folder": "sp/spinbound",
        "local_name": "inband_details.xlsx",
        "nested": True,        # 进入 日期/时间戳 子目录找最新 excel
        "csv": False,
        "recursive": False,
        "search": None,
    },
    "outband_details": {
        "remote_folder": "sp/spoutbound",
        "local_name": "outband_details.xlsx",
        "nested": True,
        "csv": False,
        "recursive": False,
        "search": None,
    },
    "inventory_details": {
        "remote_folder": "sp/spinventory",
        "local_name": "inventory_details.xlsx",
        "nested": True,
        "csv": False,
        "recursive": False,
        "search": None,
    },
    "ocrule_details": {
        "remote_folder": "OCAuto/OCAutoOutput",
        "local_name": "ocrule_details.xlsx",
        "nested": False,
        "csv": True,          # 找到 csv 后转 excel
        "recursive": True,
        "search": "ocrule",
    },
    "transfer_details": {
        "remote_folder": "sp/sp-wh_transfer",
        "local_name": "transfer_details.xlsx",
        "nested": False,
        "csv": False,
        "recursive": True,
        "search": "sp-wh_transfer",
    },
}

# 增量去重的表（保留历史累计），其余表为「整表替换」
APPEND_TABLES = {"inventory_details"}


# ====== SFTP 辅助函数 ======
def find_latest_subfolder(sftp, base_path):
    """找到 base_path 下修改时间最新的子目录"""
    dirs = []
    try:
        for f in sftp.listdir_attr(base_path):
            if stat.S_ISDIR(f.st_mode):
                dirs.append(f)
    except IOError:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] find_latest_subfolder: exception swallowed", exc_info=True)
        return None
    if not dirs:
        return None
    dirs.sort(key=lambda x: x.st_mtime, reverse=True)
    return dirs[0].filename


def find_latest_excel_in_nested(sftp, folder_path):
    """进入日期文件夹 → 最新时间戳文件夹 → 找最新 Excel"""
    latest_date = find_latest_subfolder(sftp, folder_path)
    if not latest_date:
        return None
    date_path = f"{folder_path}/{latest_date}"
    latest_time = find_latest_subfolder(sftp, date_path)
    if not latest_time:
        return None
    time_path = f"{date_path}/{latest_time}"
    files = []
    try:
        for f in sftp.listdir_attr(time_path):
            if not stat.S_ISDIR(f.st_mode) and f.filename.lower().endswith(('.xlsx', '.xls')):
                files.append(f)
    except IOError:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] find_latest_excel_in_nested: exception swallowed", exc_info=True)
        return None
    if not files:
        return None
    files.sort(key=lambda x: x.st_mtime, reverse=True)
    return f"{time_path}/{files[0].filename}"


def _scan_recursive(sftp, path, predicate, collector):
    try:
        for f in sftp.listdir_attr(path):
            full = f"{path}/{f.filename}"
            if stat.S_ISDIR(f.st_mode):
                _scan_recursive(sftp, full, predicate, collector)
            elif predicate(f):
                collector.append((f, full))
    except IOError:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _scan_recursive: exception swallowed", exc_info=True)
        pass


def find_latest_ocrule_csv_recursive(sftp, folder_path):
    """递归搜索包含 ocrule 的最新 csv"""
    found = []
    _scan_recursive(
        sftp, folder_path,
        lambda f: (not stat.S_ISDIR(f.st_mode)
                   and "ocrule" in f.filename.lower()
                   and f.filename.lower().endswith(".csv")),
        found,
    )
    if not found:
        return None
    found.sort(key=lambda x: x[0].st_mtime, reverse=True)
    return found[0][1]


def find_latest_transfer_xlsx_recursive(sftp, folder_path):
    """递归搜索包含 sp-wh_transfer 的最新 xlsx"""
    found = []
    _scan_recursive(
        sftp, folder_path,
        lambda f: (not stat.S_ISDIR(f.st_mode)
                   and "sp-wh_transfer" in f.filename.lower()
                   and f.filename.lower().endswith(('.xlsx', '.xls'))),
        found,
    )
    if not found:
        return None
    found.sort(key=lambda x: x[0].st_mtime, reverse=True)
    return found[0][1]


def download_file(sftp, remote_file, local_path, convert_to_excel=False):
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    if convert_to_excel:
        temp_csv = str(SP_DATA_DIR / "_temp_ocrule.csv")
        sftp.get(remote_file, temp_csv)
        df = pd.read_csv(temp_csv)
        atomic_to_excel(df, local_path, index=False)
        try:
            os.remove(temp_csv)
        except OSError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] download_file: exception swallowed", exc_info=True)
            pass
    else:
        # 关键修复：先下载到临时文件，再原子替换到最终路径。
        # 直接 sftp.get(remote_file, local_path) 会在目标被锁(Excel/SMB读)时
        # 直接报 Permission denied；临时文件+os.replace 重试可穿过短暂锁。
        final = Path(local_path)
        tmp = final.with_suffix(final.suffix + f".{os.getpid()}.tmp")
        sftp.get(remote_file, str(tmp))
        try:
            from .atomic_write import atomic_replace_file
        except ImportError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] download_file: exception swallowed", exc_info=True)
            from atomic_write import atomic_replace_file
        atomic_replace_file(str(tmp), str(final))


# ====== 字段归一化（与 WareHouseDashBoard/excel2db.py 保持一致）======
NA_VALUES = {'', 'NA', 'N/A', '-', 'na', 'n/a'}


def normalize_fields(df: pd.DataFrame) -> pd.DataFrame:
    if 'Warehouse Name' in df.columns:
        df['Warehouse Name'] = df['Warehouse Name'].fillna('N/A')
        df['Warehouse Name'] = df['Warehouse Name'].apply(
            lambda x: 'N/A' if isinstance(x, str) and x.strip() == '' else x)
    if 'Material No.' in df.columns:
        df['Material No.'] = df['Material No.'].fillna('N/A')
        df['Material No.'] = df['Material No.'].apply(
            lambda x: 'N/A' if (isinstance(x, str) and x.strip() in NA_VALUES) else x)
    if 'Serial No.' in df.columns:
        df['Serial No.'] = df['Serial No.'].fillna('N/A')
        df['Serial No.'] = df['Serial No.'].apply(
            lambda x: 'N/A' if (isinstance(x, str) and x.strip() in NA_VALUES) else x)
    if 'Material Type' in df.columns:
        df['Material Type'] = df['Material Type'].fillna('N/A')
        df['Material Type'] = df['Material Type'].apply(
            lambda x: 'N/A' if isinstance(x, str) and x.strip() == '' else x)
    return df


# ====== 数据库写入 ======
def _ensure_log_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sp_sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT,
            rows INTEGER,
            synced_at TEXT
        )
    """)


def _write_table(conn, table_name: str, df: pd.DataFrame):
    now = datetime.now()
    update_time = now.strftime('%Y-%m-%d %H:%M:%S')
    update_date = now.strftime('%Y-%m-%d')
    df = df.copy()
    df['update_time'] = update_time
    df['update_date'] = update_date
    df = normalize_fields(df)

    if table_name in APPEND_TABLES and _table_exists(conn, table_name):
        # 增量去重：保留历史累计
        subset = [c for c in ['update_date', 'Serial No.', 'Material No.',
                              'Warehouse Name', 'Material Type'] if c in df.columns]
        df_old = pd.read_sql(f"SELECT * FROM {table_name}", conn)
        df_combined = pd.concat([df, df_old], ignore_index=True)
        if subset:
            df = df_combined.drop_duplicates(subset=subset, keep='first')
        else:
            df = df_combined.drop_duplicates(keep='first')
    else:
        # 整表替换
        df.to_sql(table_name, conn, if_exists='replace', index=False)

    if table_name not in APPEND_TABLES:
        # 上面 replace 已写入；append 表需要在合并后单独写
        pass
    if table_name in APPEND_TABLES:
        df.to_sql(table_name, conn, if_exists='replace', index=False)


def _table_exists(conn, table_name: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cur.fetchone() is not None


# ====== SFTP 连接（带 keepalive / 超时，便于断线自愈）======
SFTP_CONNECT_TIMEOUT = 30
SFTP_KEEPALIVE = 30
SFTP_MAX_ATTEMPTS = 3          # 整体连接/同步重试次数
SFTP_ATTEMPT_BACKOFF = 5       # 退避基数（秒），第 n 次整体重试等待 n*base
SFTP_TABLE_RETRY = 2           # 单表下载失败后，重建连接重试次数


def _connect_sftp():
    """建立带 keepalive 与超时保护的 SFTP 连接，返回 (client, sftp)。"""
    sock = socket.create_connection((SFTP_HOST, SFTP_PORT), timeout=SFTP_CONNECT_TIMEOUT)
    client = paramiko.Transport(sock)
    client.set_keepalive(SFTP_KEEPALIVE)
    client.connect(username=SFTP_USER, password=SFTP_PASS)
    sftp = paramiko.SFTPClient.from_transport(client)
    return client, sftp


# ====== 主流程 ======
def run_sp_data_sync() -> dict:
    """拉取 5 份 SP 报表并写入 db/app.db，返回执行结果。

    健壮性增强：
      - 整体 SFTP 连接/同步失败会按指数退避自动重试；
      - 单表下载中途断线会先重建连接再重试该表，避免一次网络抖动拖垮整轮。
    """
    os.makedirs(SP_DATA_DIR, exist_ok=True)
    now = datetime.now()
    synced_at = now.strftime('%Y-%m-%d %H:%M:%S')
    result = {
        "success": True,
        "message": "",
        "synced_at": synced_at,
        "tables": {},
        "attempts": 0,
    }

    last_err = None
    for attempt in range(1, SFTP_MAX_ATTEMPTS + 1):
        result["attempts"] = attempt
        client = None
        sftp = None
        try:
            client, sftp = _connect_sftp()
            conn = __import__('sqlite3').connect(str(DB_PATH))
            _ensure_log_table(conn)

            for table_name, cfg in SP_TABLES.items():
                local_path = SP_DATA_DIR / cfg["local_name"]
                remote_file = None
                # 单表重试：失败则重建连接后重试该表
                for sub in range(1, SFTP_TABLE_RETRY + 2):
                    try:
                        if cfg["nested"]:
                            remote_file = find_latest_excel_in_nested(sftp, cfg["remote_folder"])
                        elif cfg["recursive"]:
                            if cfg["csv"]:
                                remote_file = find_latest_ocrule_csv_recursive(sftp, cfg["remote_folder"])
                            else:
                                remote_file = find_latest_transfer_xlsx_recursive(sftp, cfg["remote_folder"])
                        if not remote_file:
                            msg = f"[警告] {table_name} 未找到远端文件，跳过"
                            print(msg)
                            result["tables"][table_name] = {"rows": 0, "status": "skipped", "detail": msg}
                            break

                        download_file(sftp, remote_file, str(local_path), cfg["csv"])
                        df = pd.read_excel(local_path)
                        _write_table(conn, table_name, df)
                        conn.execute(
                            "INSERT INTO sp_sync_log (table_name, rows, synced_at) VALUES (?,?,?)",
                            (table_name, len(df), synced_at),
                        )
                        conn.commit()
                        result["tables"][table_name] = {"rows": len(df), "status": "ok"}
                        print(f"[成功] {table_name}: {len(df)} 行 (来源 {remote_file})")
                        break
                    except Exception as e:
                        print(f"[错误] {table_name} 第{sub}次尝试失败: {e}")
                        if sub <= SFTP_TABLE_RETRY:
                            # 连接可能已断，重建后重试该表
                            try:
                                sftp.close(); client.close()
                            except Exception:
                                logging.getLogger(__name__).warning("[SILENT-EXCEPT] run_sp_data_sync: exception swallowed", exc_info=True)
                                pass
                            client, sftp = _connect_sftp()
                            continue
                        result["tables"][table_name] = {"rows": 0, "status": "error", "detail": str(e)}
                        result["success"] = False

            conn.close()
            ok = sum(1 for v in result["tables"].values() if v.get("status") == "ok")
            result["message"] = f"SP 数据同步完成：{ok}/{len(SP_TABLES)} 个表成功（第{attempt}次尝试）"
            print(f"[完成] {result['message']}")
            break  # 整轮成功，退出整体重试循环
        except Exception as e:
            last_err = e
            result["success"] = False
            result["message"] = f"SFTP 连接/同步失败(第{attempt}次尝试): {e}"
            print(f"[致命] {result['message']}")
            if attempt < SFTP_MAX_ATTEMPTS:
                wait = SFTP_ATTEMPT_BACKOFF * attempt
                print(f"[重试] {wait}s 后整体重试 ({attempt}/{SFTP_MAX_ATTEMPTS})...")
                time.sleep(wait)
        finally:
            try:
                if sftp:
                    sftp.close()
                if client:
                    client.close()
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] run_sp_data_sync: exception swallowed", exc_info=True)
                pass

    if last_err is not None and not result["tables"]:
        # 所有尝试都未能建立连接：明确标记为失败
        result["success"] = False
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(run_sp_data_sync(), ensure_ascii=False, indent=2))


# ====== 看板查询辅助（供前端仓库看板使用）======
def _status_breakdown(df: pd.DataFrame) -> dict | None:
    """若含 status/closed 类列，返回 closed / unclosed 计数；否则 None。"""
    status_col = None
    for c in df.columns:
        cl = str(c).lower()
        if 'status' in cl or 'closed' in cl:
            status_col = c
            break
    if status_col is None:
        return None
    total = len(df)
    closed = 0
    for v in df[status_col].astype(str).str.strip().str.lower():
        if v in ('closed', 'close', 'done', '已关闭', '完成', 'yes', 'y', '1', 'true'):
            closed += 1
    return {"column": status_col, "closed": closed, "unclosed": total - closed}


def _type_breakdown(df: pd.DataFrame, max_items: int = 3) -> dict | None:
    """若含 type 类列（如 Material Type），返回各取值计数。"""
    type_col = None
    for c in df.columns:
        if 'type' in str(c).lower():
            type_col = c
            break
    if type_col is None:
        return None
    counts = df[type_col].astype(str).fillna('N/A').value_counts().head(max_items).to_dict()
    return {"column": type_col, "counts": counts}


def get_sp_summary() -> dict:
    """返回各 SP 表的总行数、列、最近同步时间、衍生指标。"""
    import sqlite3
    with get_raw_connection(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            # 最近同步时间
            last_sync = None
            try:
                row = conn.execute(
                    "SELECT synced_at FROM sp_sync_log ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    last_sync = row["synced_at"]
            except sqlite3.OperationalError:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_sp_summary: exception swallowed", exc_info=True)
                pass

            summary = {"last_sync": last_sync, "tables": []}
            for table_name in SP_TABLES.keys():
                entry = {"table": table_name, "row_count": 0,
                         "columns": [], "last_sync": last_sync,
                         "metrics": None}
                try:
                    cnt = conn.execute(f"SELECT COUNT(*) AS c FROM {table_name}").fetchone()
                    entry["row_count"] = cnt["c"] if cnt else 0
                    cols = conn.execute(f"SELECT * FROM {table_name} LIMIT 1").fetchall()
                    if cols:
                        entry["columns"] = list(cols[0].keys())
                        df = pd.read_sql(f"SELECT * FROM {table_name}", conn)
                        # Inbound / Outbound：closed 拆分；Inventory：Material Type 拆分
                        if table_name in ("inband_details", "outband_details"):
                            entry["metrics"] = _status_breakdown(df)
                        elif table_name == "inventory_details":
                            entry["metrics"] = _type_breakdown(df)
                except sqlite3.OperationalError:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_sp_summary: exception swallowed", exc_info=True)
                    pass
                summary["tables"].append(entry)
            return summary
        finally:
            conn.close()


def get_sp_rows(table: str, page: int = 1, size: int = 50, search: str = "") -> dict:
    """分页 + 模糊搜索返回某 SP 表的数据。"""
    import sqlite3
    if table not in SP_TABLES:
        return {"error": f"未知表: {table}"}
    with get_raw_connection(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        try:
            columns = [d[1] for d in conn.execute(f"PRAGMA table_info({table})")]
            where = ""
            params = []
            if search:
                like_cols = [c for c in columns if c not in ("update_time", "update_date")]
                if like_cols:
                    where = " WHERE " + " OR ".join(f"CAST({c} AS TEXT) LIKE ?" for c in like_cols)
                    params = [f"%{search}%"] * len(like_cols)
            total = conn.execute(f"SELECT COUNT(*) AS c FROM {table}{where}", params).fetchone()["c"]
            offset = (max(1, page) - 1) * size
            rows = conn.execute(
                f"SELECT * FROM {table}{where} ORDER BY rowid DESC LIMIT ? OFFSET ?",
                params + [size, offset],
            ).fetchall()
            return {
                "table": table,
                "columns": columns,
                "rows": [dict(r) for r in rows],
                "total": total,
                "page": page,
                "size": size,
            }
        except sqlite3.OperationalError:
            # 表尚未创建（任务未运行过）→ 返回空结果，前端优雅展示
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_sp_rows: exception swallowed", exc_info=True)
            return {
                "table": table,
                "columns": [],
                "rows": [],
                "total": 0,
                "page": page,
                "size": size,
            }
        finally:
            conn.close()