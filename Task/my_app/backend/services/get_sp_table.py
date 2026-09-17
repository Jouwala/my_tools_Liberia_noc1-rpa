"""
import logging
SP（备件）数据同步服务。

从远端 SFTP 服务器（10.100.20.11）拉取 5 份备件管理 Excel 报表，
归一化后写入 my_app 的 SQLite 数据库 db/app.db，供「仓库看板」展示；
同时镜像写入 FineBI 服务器（DESKTOP-D4GF62）上的
WareHouseDashBoard/inventory.db（UNC 网络路径），供 FineBI 仓库看板读取。

表名与 WareHouseDashBoard 保持一致（2026-09-16 起上游目录/文件名已变更）：
  - inband_details   （Inbound  Ticket，sp/inbound            → inbound.xlsx）
  - outband_details  （Outbound Ticket，sp/outbound           → outbound.xlsx）
  - inventory_details（Inventory，      sp/inventory_management → inventory_management.xlsx）
  - ocrule_details   （OC Rule，         OCAuto/OCAutoOutput，递归找 csv→excel）
  - transfer_details  （WH Transfer，    sp/wh_transfer        → wh_transfer.xlsx）

可直接作为任务集成进任务管理（run_sp_data_sync）。
"""
import logging
import os
import stat
import sys
import io
import time
import socket
from datetime import datetime, timedelta
from pathlib import Path

import paramiko
import pandas as pd
from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names, table_columns, write_df
import sqlite3


def _rows_as_dicts(cursor):
    """cursor -> [dict, ...]（双模：sqlite Row / PG 元组均兼容）"""
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in cursor.fetchall()]


try:
    import psycopg2
    _OPERR = (sqlite3.OperationalError, psycopg2.OperationalError)
except Exception:
    _OPERR = (sqlite3.OperationalError,)

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

# ========== 外部化配置（Settings 页面可编辑的 sp_sftp_config.json） ==========
# 主机/目录可页面调整；凭据走 credential_store（_runtime_credentials）。
try:
    from backend.services.task_config_files import load_json_config
    _SP_CONF = load_json_config(Path(__file__).resolve().parent / "sp_sftp_config.json")
except Exception:
    _SP_CONF = None
if _SP_CONF:
    SFTP_HOST = _SP_CONF.get("sftp_host", SFTP_HOST)
    SFTP_PORT = int(_SP_CONF.get("sftp_port", SFTP_PORT))
    _sp_folders = _SP_CONF.get("folders") or {}
    print(f"[SP] 已加载 sp_sftp_config.json: host={SFTP_HOST}")

# ====== FineBI 仓库看板镜像库（UNC 网络路径，任务成功后把最新数据同步过去） ======
# 默认指向 FineBI 服务器上的 WareHouseDashBoard/inventory.db（该库仅含 5 张 SP 表）。
# 可在 sp_sftp_config.json 里改路径 / 关闭（"mirror_enabled": false）。
MIRROR_DB_PATH = r"\\DESKTOP-D4GF62\FineBI6.0\webapps\Python\Unified_Tools\WareHouseDashBoard\inventory.db"
MIRROR_ENABLED = True
if _SP_CONF:
    MIRROR_DB_PATH = _SP_CONF.get("mirror_db_path", MIRROR_DB_PATH)
    MIRROR_ENABLED = bool(_SP_CONF.get("mirror_enabled", MIRROR_ENABLED))


def _runtime_credentials():
    """运行时获取凭据（环境变量 > 数据库 > 模块默认值），支持页面改密后免重启生效。"""
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        from credential_store import get_credential
    return get_credential("sftp_sp", SFTP_USER, SFTP_PASS)

# 5 份报表的下载定义
# ⚠️ 2026-09-16：上游把数据源迁到 /home/ubuntu/sp 下的新目录 + 固定文件名
#    sp/<目录名>/<yyyymmdd>/<yyyymmddHHMMSSfff>/<文件名>.xlsx
#    旧的 sp/spinbound|spoutbound|spinventory|sp-wh_transfer 已于 2026-09-15 08:00 停更，
#    继续用会静默取到过期快照。带 "filename" 的走 find_latest_named_excel（校验文件名）。
SP_TABLES = {
    "inband_details": {
        "remote_folder": "sp/inbound",
        "filename": "inbound.xlsx",
        "local_name": "inband_details.xlsx",
        "nested": True,        # 进入 日期/时间戳 子目录找最新 excel
        "csv": False,
        "recursive": False,
        "search": None,
    },
    "outband_details": {
        "remote_folder": "sp/outbound",
        "filename": "outbound.xlsx",
        "local_name": "outband_details.xlsx",
        "nested": True,
        "csv": False,
        "recursive": False,
        "search": None,
    },
    "inventory_details": {
        "remote_folder": "sp/inventory_management",
        "filename": "inventory_management.xlsx",
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
        "remote_folder": "sp/wh_transfer",
        "filename": "wh_transfer.xlsx",
        "local_name": "transfer_details.xlsx",
        "nested": True,
        "csv": False,
        "recursive": False,
        "search": None,
    },
}

# 应用 sp_sftp_config.json 里的远程目录覆盖（页面可调）
if _SP_CONF:
    _sp_folders = _SP_CONF.get("folders") or {}
    for _table, _folder in _sp_folders.items():
        if _table in SP_TABLES and isinstance(_folder, str) and _folder.strip():
            SP_TABLES[_table]["remote_folder"] = _folder

# 增量去重的表（保留历史累计），其余表为「整表替换」
APPEND_TABLES = {"inventory_details"}

# ====== 增量表保留期（2026-09-11 新增）======
# inventory_details 是逐日快照表（每天约 2400 行），只追加不清理会无限增长：
# 镜像库 2026-02 起已累计 41 万行 / 108MB。默认保留最近 180 天。
#
# 口径说明（重要）：
#   1) 基准取**表中最新的合法 update_date**（YYYY-MM-DD），不是系统当天。上游
#      SFTP 断流时只会保留「最近 N 天有数据的快照」，绝不会把整表清空。
#   2) 保留天数 = keep_days，即 cutoff = 最新日期 - (keep_days - 1)（含头含尾 N 天）。
#   3) myapp/?page=warehouse 的「Inventory Quantity Trend」直接读取本表全部
#      update_date 做趋势（sp_dashboard.load_inventory_trend，无日期参数时返回
#      全部日期），因此该值同时决定趋势图的最大回溯天数——调小会直接砍掉趋势图
#      的历史。需求方明确要求 180 天。
#   4) 可在 sp_sftp_config.json 用 "inventory_retention_days" 覆盖；<=0 表示不清理。
INVENTORY_RETENTION_DAYS = 180
RETENTION_DAYS = {"inventory_details": INVENTORY_RETENTION_DAYS}


def _retention_days(table_name: str) -> int:
    """运行时读取某表的保留天数（页面改 sp_sftp_config.json 后免重启生效）。

    优先级：sp_sftp_config.json 的 inventory_retention_days > 模块默认值。
    返回 <=0 表示不清理。
    """
    days = RETENTION_DAYS.get(table_name, 0)
    try:
        try:
            from backend.services.task_config_files import load_json_config
        except ImportError:
            from task_config_files import load_json_config
        conf = load_json_config(Path(__file__).resolve().parent / "sp_sftp_config.json") or {}
        days = int(conf.get("inventory_retention_days", days))
    except Exception:
        logging.getLogger(__name__).warning(
            "[SILENT-EXCEPT] _retention_days: exception swallowed", exc_info=True)
    return days


def _retention_cutoff(conn, table_name: str, keep_days: int):
    """按「表中最新合法 update_date - (keep_days-1)」算出截止日，返回 (cutoff, base_date)。

    基准用表内最新日期而非系统当天：上游断流时不会误删整表。

    只在 Python 侧挑出合法的 YYYY-MM-DD 再取 max —— 不用 SQL 的 MAX/GLOB：
      - SQL 的 MAX 是字符串比较，一条遗留格式（如 '2026/01/05'，'/' > '-'）会
        污染结果并让解析失败，进而使整表跳过清理；
      - GLOB 是 SQLite 专有，本模块同时支持 PG 方言。
    无法计算时返回 (None, None)，调用方应跳过清理（宁可不删）。
    """
    if keep_days is None or keep_days <= 0:
        return None, None
    try:
        rows = conn.execute(
            f'SELECT DISTINCT "update_date" FROM "{table_name}"').fetchall()
    except _OPERR:
        return None, None
    best = None
    for row in rows:
        raw = row[0] if not isinstance(row, dict) else row.get("update_date")
        if raw is None:
            continue
        s = str(raw).strip()[:10]
        try:
            dt = datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            continue          # 遗留/异常格式：忽略，不参与基准
        if best is None or dt > best[0]:
            best = (dt, s)
    if best is None:
        return None, None
    cutoff = (best[0] - timedelta(days=keep_days - 1)).strftime("%Y-%m-%d")
    return cutoff, best[1]


def _prune_by_retention(conn, table_name: str, keep_days: int, label: str = "app.db") -> dict:
    """删除超过保留期的历史快照行（按 update_date）。返回统计信息，不抛异常。

    只做「删除更早的整日快照」，不触碰保留期内的行；表为空/日期异常/保留期<=0
    一律跳过。update_date 非 YYYY-MM-DD 的遗留行因字符串比较不成立而天然保留。
    """
    info = {"table": table_name, "label": label, "keep_days": keep_days,
            "base_date": None, "cutoff": None, "deleted": 0, "rows_before": None}
    try:
        info["rows_before"] = conn.execute(
            f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0] or 0
    except _OPERR as e:
        info["detail"] = f"表不可读，跳过清理: {e}"
        return info
    cutoff, base = _retention_cutoff(conn, table_name, keep_days)
    info["base_date"] = base
    if cutoff is None:
        info["rows_after"] = info["rows_before"]
        info["detail"] = "保留期<=0 或无合法 update_date，跳过清理"
        return info
    info["cutoff"] = cutoff
    try:
        cur = conn.execute(
            f'DELETE FROM "{table_name}" '
            f'WHERE "update_date" IS NOT NULL AND "update_date" != \'\' '
            f'AND "update_date" < ?', (cutoff,))
        info["deleted"] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        info["rows_after"] = conn.execute(
            f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0] or 0
        print(f"[保留期][{label}] {table_name}: 基准 {base}，保留 {keep_days} 天"
              f"（cutoff {cutoff}）→ 删除 {info['deleted']} 行，"
              f"{info['rows_before']} → {info['rows_after']} 行")
    except _OPERR as e:
        info["rows_after"] = info["rows_before"]
        info["detail"] = f"清理失败: {e}"
        print(f"[保留期][{label}] {table_name}: 清理失败 {e}")
    return info


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


def find_latest_named_excel(sftp, folder_path, filename, max_dates=5, max_slots=3):
    """在 sp/<目录名>/<yyyymmdd>/<yyyymmddHHMMSSfff>/<文件名>.xlsx 结构里，
    取**文件名精确匹配**（忽略大小写）的最新一份。

    从最新日期目录往前找（最多 max_dates 天、每天最多 max_slots 个时间戳目录），
    命中即返回，避免对整棵树做全量递归。
    """
    target = str(filename).lower()

    def _subdirs(path):
        try:
            ds = [f for f in sftp.listdir_attr(path) if stat.S_ISDIR(f.st_mode)]
        except IOError:
            logging.getLogger(__name__).warning(
                "[SILENT-EXCEPT] find_latest_named_excel: listdir %s", path, exc_info=True)
            return []
        ds.sort(key=lambda x: x.st_mtime, reverse=True)
        return [d.filename for d in ds]

    for date_dir in _subdirs(folder_path)[:max_dates]:
        date_path = f"{folder_path}/{date_dir}"
        for ts_dir in _subdirs(date_path)[:max_slots]:
            ts_path = f"{date_path}/{ts_dir}"
            try:
                names = [f.filename for f in sftp.listdir_attr(ts_path)
                         if not stat.S_ISDIR(f.st_mode)]
            except IOError:
                continue
            for n in names:
                if n.lower() == target:
                    return f"{ts_path}/{n}"
    return None


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
    if isinstance(conn, sqlite3.Connection):
        pk_ddl = "id INTEGER PRIMARY KEY AUTOINCREMENT"
    else:
        pk_ddl = "id SERIAL PRIMARY KEY"
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS sp_sync_log (
            {pk_ddl},
            table_name TEXT,
            rows INTEGER,
            synced_at TEXT
        )
    """)


def _write_table(conn, table_name: str, df: pd.DataFrame, sink: dict | None = None):
    """写入 app.db；sink 传入时把写入后的 DataFrame 交给镜像收集器（table -> df）。"""
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
        write_df(df, table_name, if_exists="replace")

    if table_name not in APPEND_TABLES:
        # 上面 replace 已写入；append 表需要在合并后单独写
        pass
    if table_name in APPEND_TABLES:
        write_df(df, table_name, if_exists="replace")

    # 交给镜像：append 表远端也按「远端已有行反连接」追加，传入合并后的
    # 全量内存 df 即可（只保留本轮新行语义由 _mirror_append_table 保证）。
    if sink is not None:
        sink[table_name] = df


def _table_exists(conn, table_name: str) -> bool:
    return table_name in set(list_table_names(conn))


# ====== FineBI 镜像库写入（UNC 网络路径 inventory.db） ======
# 远端 inventory.db 是 WareHouseDashBoard 看板的专用库（仅含 5 张 SP 表），
# 由本任务作为唯一写入方维护；journal_mode 保持 delete（SMB 上 WAL 不可靠）。
# 普通表整表替换；增量表（APPEND_TABLES）只追加远端没有的新行，保护远端历史。
MIRROR_APPEND_TABLES = tuple(APPEND_TABLES)
MIRROR_CONNECT_TIMEOUT = 30.0   # SMB 首次连接可能较慢
MIRROR_BUSY_TIMEOUT_MS = 30000  # 看板进程可能正持有读锁
MIRROR_RETRIES = 2              # 整体镜像失败重试次数（SMB 抖动自愈）
MIRROR_RETRY_WAIT = 5           # 重试间隔基数（秒）
# 追加表反连接列：与 app.db 增量去重的 subset 一致（update_date + 业务键）
MIRROR_DEDUP_COLS = ['update_date', 'Serial No.', 'Material No.',
                     'Warehouse Name', 'Material Type']


def _mirror_runtime_config():
    """运行时读取镜像配置（页面改 sp_sftp_config.json 后免重启生效）。"""
    try:
        from backend.services.task_config_files import load_json_config
    except ImportError:
        from task_config_files import load_json_config
    conf = load_json_config(Path(__file__).resolve().parent / "sp_sftp_config.json")
    path = MIRROR_DB_PATH
    enabled = MIRROR_ENABLED
    if conf:
        path = conf.get("mirror_db_path", path)
        enabled = bool(conf.get("mirror_enabled", enabled))
    return enabled, path


def _connect_mirror(db_path: str):
    """连接远端 SQLite（SMB UNC 路径）：短超时 + busy_timeout 扛看板读锁。"""
    con = sqlite3.connect(str(db_path), timeout=MIRROR_CONNECT_TIMEOUT)
    con.execute(f"PRAGMA busy_timeout = {MIRROR_BUSY_TIMEOUT_MS}")
    return con


def _mirror_ensure_table(con, table_name: str, df: pd.DataFrame):
    """远端建表（若不存在）。列名来自 WareHouseDashBoard excel2db 同构的 DataFrame。"""
    cols_sql = ", ".join(
        f'"{str(c).replace(chr(34), chr(34) * 2)}" TEXT' for c in df.columns
    )
    con.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" ({cols_sql})')


def _mirror_replace_table(con, table_name: str, df: pd.DataFrame):
    """整表替换：事务内 DELETE + 分块 INSERT（与 app.db 同步语义一致）。"""
    cols = [str(c) for c in df.columns]
    quoted = ", ".join(f'"{c.replace(chr(34), chr(34) * 2)}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    delete_sql = f'DELETE FROM "{table_name}"'
    insert_sql = f'INSERT INTO "{table_name}" ({quoted}) VALUES ({placeholders})'
    con.execute(delete_sql)
    chunk = 2000
    for start in range(0, len(df), chunk):
        batch = df.iloc[start:start + chunk]
        con.executemany(insert_sql, batch.itertuples(index=False, name=None))
    return len(df)


def _mirror_append_table(con, table_name: str, df: pd.DataFrame):
    """追加表：只 INSERT 远端还没有的新行，绝不删改远端历史累计数据。

    反连接键与 app.db 增量去重一致（update_date + Serial/Material/Warehouse/Type），
    空远端表直接整批插入（避免对 32 万行大表做无谓的全表反连接）。
    """
    subset = [c for c in MIRROR_DEDUP_COLS if c in df.columns]
    cur = con.execute(f'SELECT COUNT(*) FROM "{table_name}"')
    remote_cnt = cur.fetchone()[0] or 0
    inserted = 0
    if remote_cnt == 0:
        if len(df):
            inserted = _mirror_replace_table(con, table_name, df)
        return inserted, remote_cnt
    cols = [str(c) for c in df.columns]
    quoted = ", ".join(f'"{c.replace(chr(34), chr(34) * 2)}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    insert_sql = f'INSERT INTO "{table_name}" ({quoted}) VALUES ({placeholders})'
    if subset:
        dedup_cols = [c for c in subset if c in cols]
        if dedup_cols:
            sel = ", ".join(f'NULLIF("{c.replace(chr(34), chr(34) * 2)}", \'\')' for c in dedup_cols)
            existing = {
                tuple("" if v is None else str(v).strip() for v in row)
                for row in con.execute(f'SELECT {sel} FROM "{table_name}"')
            }
            keys = [
                tuple("" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()
                      for v in row)
                for row in df[dedup_cols].itertuples(index=False, name=None)
            ]
            todo_mask = [k not in existing for k in keys]
            pending = df.loc[todo_mask]
            # 批内同键去重（app.db 侧 keep='first' 语义一致）
            if len(pending):
                pending = pending.drop_duplicates(subset=dedup_cols, keep="first")
            if len(pending):
                con.executemany(
                    insert_sql, pending.itertuples(index=False, name=None))
                inserted = len(pending)
            return inserted, remote_cnt
    # 无可用去重列（理论不到达）：退化为整表替换语义
    return _mirror_replace_table(con, table_name, df), remote_cnt


def _mirror_table_exists(con, table_name: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    return row is not None


def _mirror_coerce_values(df: pd.DataFrame) -> pd.DataFrame:
    """SQLite 只能绑定基础类型：datetime 列转字符串，其余非基础类型转 str。

    pd.read_excel 会把 Excel 日期列解析成 datetime64/pd.Timestamp，
    直接 itertuples 绑定会报 "type 'Timestamp' is not supported"。
    """
    out = df.copy()
    for col in out.columns:
        s = out[col]
        if pd.api.types.is_datetime64_any_dtype(s):
            out[col] = s.dt.strftime('%Y-%m-%d %H:%M:%S')
        elif s.dtype == object:
            def _conv(v):
                if v is None or v is pd.NaT:
                    return None
                if isinstance(v, float) and pd.isna(v):
                    return None
                if isinstance(v, (str, int, float, bytes, bool)):
                    return v
                if hasattr(v, "strftime"):
                    return v.strftime('%Y-%m-%d %H:%M:%S')
                return str(v)
            out[col] = s.map(_conv)
    return out


def _mirror_write_all(tables_data: dict) -> dict:
    """把本轮各表 DataFrame 写入远端镜像库，返回 {table: {rows, status, detail?}}。

    - 远端列缺失时自动对齐 app.db 的列（远端建表/补列），多余列忽略；
    - 写前核对远端表存在且结构可容纳（INSERT OR IGNORE 保底防结构漂移报错）；
    - 任一表失败仅标记该表 error，不影响其它表。
    """
    mirror_result = {}
    enabled, db_path = _mirror_runtime_config()
    if not enabled:
        mirror_result["_meta"] = {"status": "disabled", "detail": "mirror_enabled=false"}
        return mirror_result
    if not db_path or not str(db_path).strip():
        mirror_result["_meta"] = {"status": "error", "detail": "mirror_db_path 为空"}
        return mirror_result
    last_err = None
    for attempt in range(1, MIRROR_RETRIES + 1):
        con = None
        attempt_res: dict = {}
        try:
            con = _connect_mirror(db_path)
            for table_name, df in tables_data.items():
                if df is None:
                    continue
                try:
                    if len(df) == 0:
                        # 空报表：跳过镜像，避免把远端已有数据清空（远端表结构也不被破坏）
                        attempt_res[table_name] = {
                            "rows": 0, "status": "skipped", "detail": "本轮 0 行，跳过镜像"}
                        print(f"[镜像] {table_name}: 本轮 0 行，跳过（保留远端现状）")
                        continue
                    if not _mirror_table_exists(con, table_name):
                        _mirror_ensure_table(con, table_name, df)
                    remote_cols = {
                        r[1] for r in con.execute(f'PRAGMA table_info("{table_name}")').fetchall()
                    }
                    out = df.copy()
                    missing = [c for c in map(str, out.columns) if c not in remote_cols]
                    for c in missing:
                        con.execute(
                            f'ALTER TABLE "{table_name}" '
                            f'ADD COLUMN "{str(c).replace(chr(34), chr(34) * 2)}" TEXT')
                    out = out[[c for c in map(str, out.columns)
                               if c in remote_cols or c in missing]]
                    out = _mirror_coerce_values(out)
                    if table_name in MIRROR_APPEND_TABLES:
                        inserted, remote_cnt = _mirror_append_table(con, table_name, out)
                        attempt_res[table_name] = {
                            "rows": inserted, "remote_rows": remote_cnt + inserted,
                            "status": "ok", "mode": "append",
                        }
                        print(f"[镜像] {table_name}: 追加 {inserted} 行 "
                              f"(远端原 {remote_cnt} 行，现 {remote_cnt + inserted} 行)")
                    else:
                        n = _mirror_replace_table(con, table_name, out)
                        attempt_res[table_name] = {
                            "rows": n, "remote_rows": n, "status": "ok", "mode": "replace",
                        }
                        print(f"[镜像] {table_name}: 替换 {n} 行")
                except Exception as e:
                    attempt_res[table_name] = {
                        "rows": 0, "status": "error", "detail": str(e)}
                    print(f"[镜像][错误] {table_name}: {e}")
            # ====== 保留期清理（镜像库）：与 app.db 同口径，避免 FineBI 看板库无限增长 ======
            for _t in MIRROR_APPEND_TABLES:
                if not _mirror_table_exists(con, _t):
                    continue
                try:
                    _rinfo = _prune_by_retention(
                        con, _t, _retention_days(_t), label="mirror")
                    attempt_res.setdefault("_retention", {})[_t] = _rinfo
                except Exception as e:
                    logging.getLogger(__name__).warning(
                        "[SILENT-EXCEPT] mirror retention prune: exception swallowed",
                        exc_info=True)
                    attempt_res.setdefault("_retention", {})[_t] = {
                        "table": _t, "status": "error", "detail": str(e)}
                    print(f"[保留期][mirror] {_t}: 清理异常 {e}")
            con.commit()
            attempt_res["_meta"] = {"status": "ok", "db": str(db_path), "attempt": attempt}
            return attempt_res
        except Exception as e:
            last_err = e
            print(f"[镜像][致命] 第{attempt}次连接/写入失败: {e}")
            # 本轮已写但未 commit 的表数据并未落库，如实标记为失败；
            # 连接都没建立时，本轮未到达的表也要补上 error 标记
            for t, v in attempt_res.items():
                if v.get("status") == "ok":
                    v["status"] = "error"
                    v["detail"] = f"事务未提交（连接中断）: {e}"
            for t in tables_data:
                if t not in attempt_res:
                    attempt_res[t] = {"rows": 0, "status": "error",
                                      "detail": f"连接/写入中断: {e}"}
            attempt_res["_meta"] = {"status": "error", "detail": str(e), "attempt": attempt}
            if attempt < MIRROR_RETRIES:
                time.sleep(MIRROR_RETRY_WAIT * attempt)
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    logging.getLogger(__name__).warning(
                        "[SILENT-EXCEPT] _mirror_write_all: exception swallowed", exc_info=True)
        mirror_result = attempt_res
    print(f"[镜像][放弃] {MIRROR_RETRIES} 次尝试均失败: {last_err}")
    return mirror_result


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
    _sftp_user, _sftp_pass = _runtime_credentials()
    client.connect(username=_sftp_user, password=_sftp_pass)
    sftp = paramiko.SFTPClient.from_transport(client)
    return client, sftp


# ====== 主流程 ======
def run_sp_data_sync() -> dict:
    """拉取 5 份 SP 报表并写入 db/app.db，再镜像写入 FineBI inventory.db，返回执行结果。

    健壮性增强：
      - 整体 SFTP 连接/同步失败会按指数退避自动重试；
      - 单表下载中途断线会先重建连接再重试该表，避免一次网络抖动拖垮整轮；
      - app.db 全部落库后统一镜像到 UNC 路径 inventory.db（普通表整表替换、
        inventory_details 只追加远端没有的新行），镜像失败不影响 app.db 主结果，
        但会在 result["mirror"]/message 中显式暴露。
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
    # 本轮各表最新数据（镜像写入用）：table -> 已加 update_time/update_date 的 df
    mirror_data: dict = {}
    mirror_enabled, _mirror_path = _mirror_runtime_config()
    if mirror_enabled:
        result["mirror"] = {}

    last_err = None
    for attempt in range(1, SFTP_MAX_ATTEMPTS + 1):
        result["attempts"] = attempt
        client = None
        sftp = None
        try:
            client, sftp = _connect_sftp()
            conn = get_raw_connection(str(DB_PATH))
            _ensure_log_table(conn)

            for table_name, cfg in SP_TABLES.items():
                local_path = SP_DATA_DIR / cfg["local_name"]
                remote_file = None
                # 单表重试：失败则重建连接后重试该表
                for sub in range(1, SFTP_TABLE_RETRY + 2):
                    try:
                        if cfg.get("filename"):
                            remote_file = find_latest_named_excel(
                                sftp, cfg["remote_folder"], cfg["filename"])
                        elif cfg["nested"]:
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
                        _write_table(conn, table_name, df, sink=mirror_data)
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

            # ====== 保留期清理（app.db）：删除超过 N 天的历史快照，避免表无限增长 ======
            # 以表中最新的合法 update_date 为基准，只删更早的整日快照；上游断流时不会清空整表。
            retention_info = {}
            for _t in RETENTION_DAYS:
                if not _table_exists(conn, _t):
                    continue
                try:
                    retention_info[_t] = _prune_by_retention(
                        conn, _t, _retention_days(_t), label="app.db")
                    conn.commit()
                except Exception as e:
                    logging.getLogger(__name__).warning(
                        "[SILENT-EXCEPT] retention prune: exception swallowed", exc_info=True)
                    retention_info[_t] = {"table": _t, "status": "error", "detail": str(e)}
                    print(f"[保留期][app.db] {_t}: 清理异常 {e}")
            if retention_info:
                result["retention"] = retention_info

            conn.close()
            # ====== 镜像写入 FineBI inventory.db（app.db 全部落库后执行） ======
            if mirror_enabled and mirror_data:
                mirror_res = _mirror_write_all(mirror_data)
                result["mirror"] = {k: v for k, v in mirror_res.items()}
                _meta = mirror_res.get("_meta") or {}
                mirror_errs = [t for t, v in mirror_res.items()
                               if t != "_meta" and v.get("status") == "error"]
                result["mirror_errors"] = mirror_errs
                if _meta.get("status") != "ok" or mirror_errs:
                    # 镜像失败不影响 app.db 主结果，但要在任务报告里显式暴露
                    result["mirror_success"] = False
                    print(f"[镜像][警告] 镜像未完全成功，失败表: {mirror_errs or _meta.get('detail')}")
                else:
                    result["mirror_success"] = True
                    print("[镜像] FineBI inventory.db 写入完成")
            ok = sum(1 for v in result["tables"].values() if v.get("status") == "ok")
            result["message"] = f"SP 数据同步完成：{ok}/{len(SP_TABLES)} 个表成功（第{attempt}次尝试）"
            _pruned = sum(int(v.get("deleted") or 0)
                          for v in (result.get("retention") or {}).values()
                          if isinstance(v, dict))
            if _pruned:
                result["message"] += f"；保留期清理删除 {_pruned} 行历史快照"
            if mirror_enabled:
                if result.get("mirror_success"):
                    result["message"] += "；已镜像写入 FineBI inventory.db"
                elif "mirror_errors" in result:
                    errs = ", ".join(result["mirror_errors"]) or "连接失败"
                    result["message"] += f"；镜像写入 FineBI inventory.db 失败: {errs}"
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
    with get_raw_connection(str(DB_PATH)) as conn:
        if isinstance(conn, sqlite3.Connection):
            conn.row_factory = sqlite3.Row
        try:
            # 最近同步时间
            last_sync = None
            try:
                cur = conn.execute(
                    "SELECT synced_at FROM sp_sync_log ORDER BY id DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row:
                    last_sync = row[0]
            except _OPERR:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_sp_summary: exception swallowed", exc_info=True)
                pass

            summary = {"last_sync": last_sync, "tables": []}
            for table_name in SP_TABLES.keys():
                entry = {"table": table_name, "row_count": 0,
                         "columns": [], "last_sync": last_sync,
                         "metrics": None}
                try:
                    cur = conn.execute(f"SELECT COUNT(*) AS c FROM {table_name}")
                    cnt = cur.fetchone()
                    entry["row_count"] = cnt[0] if cnt else 0
                    cur = conn.execute(f"SELECT * FROM {table_name} LIMIT 1")
                    cols = cur.fetchall()
                    if cols:
                        entry["columns"] = [d[0] for d in cur.description]
                        df = pd.read_sql(f"SELECT * FROM {table_name}", conn)
                        # Inbound / Outbound：closed 拆分；Inventory：Material Type 拆分
                        if table_name in ("inband_details", "outband_details"):
                            entry["metrics"] = _status_breakdown(df)
                        elif table_name == "inventory_details":
                            entry["metrics"] = _type_breakdown(df)
                except _OPERR:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_sp_summary: exception swallowed", exc_info=True)
                    pass
                summary["tables"].append(entry)
            return summary
        finally:
            conn.close()


def get_sp_rows(table: str, page: int = 1, size: int = 50, search: str = "") -> dict:
    """分页 + 模糊搜索返回某 SP 表的数据。"""
    if table not in SP_TABLES:
        return {"error": f"未知表: {table}"}
    with get_raw_connection(str(DB_PATH)) as conn:
        if isinstance(conn, sqlite3.Connection):
            conn.row_factory = sqlite3.Row
        try:
            columns = table_columns(conn, table)
            where = ""
            params = []
            if search:
                like_cols = [c for c in columns if c not in ("update_time", "update_date")]
                if like_cols:
                    where = " WHERE " + " OR ".join(f"CAST({c} AS TEXT) LIKE ?" for c in like_cols)
                    params = [f"%{search}%"] * len(like_cols)
            cur = conn.execute(f"SELECT COUNT(*) AS c FROM {table}{where}", params)
            total = (cur.fetchone() or (0,))[0]
            offset = (max(1, page) - 1) * size
            # TODO-PHASE3-PK: 原 ORDER BY rowid DESC；SP 通用表无显式主键（df.to_sql 无 index），
            # 改用 update_time 近似“最近写入优先”（_write_table 写入时包含 update_time）。
            cur = conn.execute(
                f"SELECT * FROM {table}{where} ORDER BY update_time DESC LIMIT ? OFFSET ?",
                params + [size, offset],
            )
            rows = _rows_as_dicts(cur)
            return {
                "table": table,
                "columns": columns,
                "rows": rows,
                "total": total,
                "page": page,
                "size": size,
            }
        except _OPERR:
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