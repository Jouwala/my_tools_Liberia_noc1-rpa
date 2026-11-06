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
import json
import time
import ctypes
import shutil
import sqlite3
import threading
import tempfile
from ctypes import wintypes
from typing import Optional
from datetime import datetime
from contextlib import contextmanager

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
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
DB_CNN_PATH = r"E:\01_RPA\LBR_Tools\KPI\db_ps_cs_cn.sqlite3"
DB_IPRAN_PATH = r"E:\01_RPA\LBR_Tools\KPI\IPRAN\ipran_ume_kpi.sqlite3"
DB_MS_SLA_PATH = r"E:\01_RPA\LBR_Tools\KPI\MS_SLA\lbr_ms_sla_kpi.sqlite3"
DB_FW_PATH = r"E:\01_RPA\LBR_Tools\KPI\FW\fw_db.sqlite"
# ---- 以下为 my-finebi 看板门户新增需求（2026-09-14）----
DB_MASTER_PATH = r"E:\01_RPA\LBR_Tools\ZTE_OLR_MS_Master_Site_Database\olbr_ms_master_database.sqlite3"
DB_SP_PATH = r"C:\FineBI6.0\webapps\Python\Unified_Tools\WareHouseDashBoard\inventory.db"
DB_AVAIL_RECON_PATH = r"D:\01_RPA\Task\my-finebi\data\avail_recon.sqlite3"
DB_MTTR_TT_PATH = r"D:\01_RPA\Task\my-finebi\data\mttr_tt.sqlite3"
DB_PROGRESS_PATH = r"D:\01_RPA\Task\my-finebi\data\progress.sqlite3"


API_HOST = "0.0.0.0"
API_PORT = 8765

# 可选鉴权：设置环境变量 DB_API_TOKEN 后，/api/query 与 /api/dbs 需带
# X-API-Token 头。未设置则不做校验（与既有 /api/read 等接口的内网免认证模型一致）。
READONLY_TOKEN = os.environ.get("DB_API_TOKEN", "").strip()

# 逻辑库名 -> 实际路径。新增数据库只需在脚本同目录放 db_map.json 覆盖，
# 不必修改本文件代码：
#   { "some_new.sqlite3": "E:\\path\\to\\some_new.sqlite3" }
_BUILTIN_DB_MAP = {
    "db.sqlite3": DB_MAIN_PATH,
    "ran_kpi_daily.sqlite3": DB_DAILY_PATH,
    "ran_kpi_daily_202606.sqlite3": DB_ORANGE_PATH,
    "db_ps_cs_cn.sqlite3": DB_CNN_PATH,
    "ipran_ume_kpi.sqlite3": DB_IPRAN_PATH,
    "lbr_ms_sla_kpi.sqlite3": DB_MS_SLA_PATH,
    "fw_db.sqlite": DB_FW_PATH,
    "olbr_ms_master_database.sqlite3": DB_MASTER_PATH,
    "inventory.db": DB_SP_PATH,
    "avail_recon.sqlite3": DB_AVAIL_RECON_PATH,
    "mttr_tt.sqlite3": DB_MTTR_TT_PATH,
    "progress.sqlite3": DB_PROGRESS_PATH,
}


def _load_db_map() -> dict:
    """内置映射 + 外部 db_map.json（外部优先覆盖）"""
    mapping = dict(_BUILTIN_DB_MAP)
    p = os.environ.get("DB_MAP_JSON", "").strip()
    if not p:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db_map.json")
    if p and os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                extra = {k: v for k, v in data.items() if isinstance(v, str) and v.strip()}
                mapping.update(extra)
                print(f"[API] db_map.json 已加载，额外映射 {len(extra)} 条: {p}")
        except Exception as e:
            print(f"[API] db_map.json 解析失败（忽略）: {e}")
    return mapping


DB_MAP = _load_db_map()

# 写入锁（保证串行写入，WAL 安全）
_write_lock = threading.Lock()

# 活动 DB 句柄计数（供 /healthz 观测：被杀时是否正忙于写入）
_db_handles = 0
_db_handles_lock = threading.Lock()

# 单次批量转换的行数：每转换这么多行就让出一次 GIL。
# 大 payload 的逐行 str() 转换是纯 Python 循环，会独占 GIL 数十秒，
# 导致线程池里的 /health 无法应答，守护进程误判进程卡死
# （2026-11-04 04:18-05:00 事故：两次强杀、42 分钟不可用）。
YIELD_ROWS = 5000


def _yield_gil():
    time.sleep(0)


# Excel 解析放到独立进程：openpyxl 是纯 Python，解析一个几万行的 KPI 表会连续
# 几十秒独占 GIL，把事件循环一起饿死——这正是 2026-11-04 04:18 起 /health 超时、
# 04:40 出现 TCP 连接超时的来源。
# 进程池一旦损坏（子进程被 OOM 杀掉、导入失败）不会自动恢复，所以必须重建后再试一次：
# 只回退到进程内解析等于悄悄放弃本次修复，卡死会重新出现且不再有任何痕迹。
# 真正超时则直接放弃并返回 5xx——调用方（db_writer_client）对 5xx 重试、对 4xx 不重试，
# 而 dedup_insert 按主键去重是幂等的，重试安全。
EXCEL_PARSE_TIMEOUT = 600
_excel_pool = None


def _read_excel_worker(path: str):
    import pandas as _pd
    return _pd.read_excel(path)


def _reset_excel_pool():
    global _excel_pool
    if _excel_pool is not None:
        try:
            _excel_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        _excel_pool = None


def _read_excel(path: str):
    global _excel_pool
    from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutureTimeout

    for attempt in (1, 2):
        try:
            if _excel_pool is None:
                _excel_pool = ProcessPoolExecutor(max_workers=1)
            return _excel_pool.submit(_read_excel_worker, path).result(timeout=EXCEL_PARSE_TIMEOUT)
        except FutureTimeout:
            _reset_excel_pool()
            raise RuntimeError(f"Excel 解析超过 {EXCEL_PARSE_TIMEOUT}s 未完成，已中止（可重试）")
        except Exception as e:
            _reset_excel_pool()
            print(f"[UPLOAD] 独立进程解析不可用（第 {attempt} 次）: {e}", flush=True)

    print("[UPLOAD] 独立进程连续两次不可用，回退进程内解析", flush=True)
    return pd.read_excel(path)


app = FastAPI(title="SQLite Writer API", version="1.2.1")

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
    """根据逻辑名称返回实际数据库文件路径（含 db_map.json 外部扩展）。"""
    path = DB_MAP.get(db_name)
    if not path:
        raise HTTPException(status_code=400, detail=f"Unknown database: {db_name}")
    return path


def _strip_item_prefix(col_name: str) -> str:
    """去掉列名中的 {item_id}: 前缀。"""
    m = re.match(r'^\d+:(.+)', col_name)
    return m.group(1) if m else col_name


def _quote(name: str) -> str:
    return f'"{name}"'


def _quote_ident(name) -> str:
    """标识符加引号，内部双引号按 SQL 规范翻倍转义。

    与 ``_quote`` 的区别只在于名字里真的含 ``"`` 时：那种写法今天会拼出语法错的
    SQL，转义后才是合法标识符。不含引号的常规列名两者逐字节相同。
    """
    return f'"{str(name).replace(chr(34), chr(34) + chr(34))}"'


def _read_col_clause(columns: list) -> str:
    """组装 /api/read 的 SELECT 列片段。

    服务端负责加引号，调用方一律传**裸列名**：含空格的列如 ``Begin Time`` 不加引号
    就是语法错误；而调用方自己带引号会被再包一层成 ``""Begin Time""``，同样是语法
    错误 —— 2026-11-05 打线上两种错都实测复现过，``db_freshness_check._api_window_max``
    早年踩过同一个坑并留了注释。
    """
    return ", ".join(_quote_ident(c) for c in columns) if columns else "*"


@contextmanager
def _open_db(db_path: str):
    """打开数据库连接（WAL 模式 + 性能优化）。"""
    global _db_handles
    with _db_handles_lock:
        _db_handles += 1
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA cache_size=-64000")
    try:
        yield conn
    finally:
        # 2026-08-27：连接关闭前做一次 PASSIVE checkpoint，把已提交 WAL 帧尽量回写
        # 主库，防止 -wal 无限膨胀（ipran 15min 级写入曾胀到 193MB 卡死读路径）。
        # PASSIVE 不阻塞、读连接上也是无害的 no-op。
        try:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass
        conn.close()
        with _db_handles_lock:
            _db_handles -= 1


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


def _ensure_upsert_index(cursor: sqlite3.Cursor, table_name: str, pk_columns: list) -> bool:
    """缺少唯一索引时做一次历史去重并建索引；索引已存在时什么都不做。

    INSERT OR REPLACE 靠 `u_<表名>` 唯一索引判定「同一主键」，所以老表首次转成
    upsert 时必须补上。但**不能每次请求都跑一遍**：原写法对每张已建索引的表仍然
    执行 ``DELETE ... GROUP BY`` —— 2026-11-05 本机实测 600 万行要 6~8s，纯属白跑，
    还全程串行占着全局写锁，把同机其他远程写入一起拖慢。

    注意这**不是** `ipran_kpi_sync` 超时的主因（主因是客户端每小时重发 3 天全量
    共 37 万行，见 ipran_ume_kpi_service 的水位增量）；此处只是去掉无谓开销。
    """
    index_name = f"u_{table_name}"
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    )
    if cursor.fetchone():
        return False
    pk_q = ", ".join(_quote_ident(c) for c in pk_columns)
    cursor.execute(
        f'DELETE FROM {_quote(table_name)} WHERE rowid NOT IN ('
        f'SELECT MIN(rowid) FROM {_quote(table_name)} GROUP BY {pk_q})'
    )
    cursor.execute(
        f'CREATE UNIQUE INDEX IF NOT EXISTS {_quote(index_name)} '
        f'ON {_quote(table_name)} ({pk_q})'
    )
    return True


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
        "version": "1.2.0",
        "time": datetime.now().isoformat(),
        "db_main": DB_MAIN_PATH,
        "db_main_exists": os.path.exists(DB_MAIN_PATH),
        "db_daily": DB_DAILY_PATH,
        "db_daily_exists": os.path.exists(DB_DAILY_PATH),
        "db_orange": DB_ORANGE_PATH,
        "db_orange_exists": os.path.exists(DB_ORANGE_PATH),
        "db_cnn": DB_CNN_PATH,
        "db_cnn_exists": os.path.exists(DB_CNN_PATH),
        "db_ipran": DB_IPRAN_PATH,
        "db_ipran_exists": os.path.exists(DB_IPRAN_PATH),
        "db_ms_sla": DB_MS_SLA_PATH,
        "db_ms_sla_exists": os.path.exists(DB_MS_SLA_PATH),
        # 2026-09-14 新增：全量逻辑库清单 + 只读接口鉴权开关
        "auth_enabled": bool(READONLY_TOKEN),
        "db_map": {k: os.path.exists(v) for k, v in sorted(DB_MAP.items())},
    }


# ============================================================
# 工作集下限（防换页）
# ============================================================
# 2026-11-05 实测归因：本机空闲物理内存只有 2.4-3.2GB（FineBI 常驻 13.4GB），
# 本进程私有内存 755MB，而工作集被内存平衡器削到 33-46MB。每到 :36-:48 的
# 任务高峰，缺页换入就把请求拖慢：/healthz 实测 11,145ms，而**同一连接上紧
# 跟着的下一个请求只花 1ms**，且这 11s 内本进程 CPU 时间增量为 0.00s、日志
# 里没有任何 [WRITE]/[UPLOAD]。所以既不是事件循环被占死，也不是它自己在干
# 活——是它被换出内存了。重启对这种状态毫无帮助（新进程要从零换页，实测
# "重启后立刻同样无响应"就是这个原因），只会把降级伪装成 WinError 10061。
# 设一个硬下限，内存平衡器便无权回收这部分，热页留在物理内存里。
WS_MIN_MB = int(os.environ.get("DB_API_WS_MIN_MB", "256"))
_MB = 1024 * 1024

# HANDLE 必须按指针宽度传递：GetCurrentProcess() 默认被 ctypes 当作 c_int 返回，
# 伪句柄 -1 会被截断成无效值，GetProcessMemoryInfo 静默返回 0。
_k32 = ctypes.windll.kernel32
_psapi = ctypes.windll.psapi
_k32.GetCurrentProcess.restype = wintypes.HANDLE
_k32.SetProcessWorkingSetSizeEx.argtypes = [wintypes.HANDLE, ctypes.c_size_t,
                                           ctypes.c_size_t, wintypes.DWORD]
_k32.SetProcessWorkingSetSizeEx.restype = wintypes.BOOL
_psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
_psapi.GetProcessMemoryInfo.restype = wintypes.BOOL


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("WorkingSetSizeEx", ctypes.c_size_t),
    ]


def _memory_status():
    """(工作集 MB, 私有内存 MB)，取不到时返回 None。"""
    try:
        buf = _PROCESS_MEMORY_COUNTERS()
        buf.cb = ctypes.sizeof(buf)
        ok = _psapi.GetProcessMemoryInfo(_k32.GetCurrentProcess(), ctypes.byref(buf), buf.cb)
        if not ok:
            return None
        return round(buf.WorkingSetSize / _MB, 1), round(buf.PagefileUsage / _MB, 1)
    except Exception:
        return None


def _pin_working_set(mb):
    """给本进程工作集设硬下限；mb<=0 表示取消下限。"""
    if mb <= 0:
        return "disabled"
    try:
        QUOTA_LIMITS_HARDWS_MIN_ENABLE = 0x0001
        # Maximum 传 -1 = 保持上限不变，只钉住下限。
        ok = _k32.SetProcessWorkingSetSizeEx(_k32.GetCurrentProcess(), mb * _MB,
                                            ctypes.c_size_t(-1), QUOTA_LIMITS_HARDWS_MIN_ENABLE)
        return "ok" if ok else "failed(err=%d)" % _k32.GetLastError()
    except Exception as exc:
        return "error(%s)" % exc


def _disk_ctx(path=None):
    """卷剩余空间：给了 path 只报它所在的盘，否则把三个数据盘都报一遍。
    2026-11-02 04:12/04:43/05:45/09:27 四次 upload_excel 返回
    "database or disk is full"，但事后看不出是哪个盘、剩多少——
    db.sqlite3 在 C:，C: 还放着系统托管的 pagefile.sys，两者会互相抢空间。
    """
    try:
        if path:
            drives = [os.path.splitdrive(os.path.abspath(path))[0] + os.sep]
        else:
            drives = ["C:\\", "D:\\", "E:\\"]
        parts = []
        for drv in drives:
            if not os.path.isdir(drv):
                continue
            usage = shutil.disk_usage(drv)
            parts.append(f"{drv} free={usage.free // _MB}MB/{usage.total // _MB}MB")
        return " ".join(parts) if parts else "no volume"
    except Exception as exc:
        return f"disk_usage({path}) failed: {exc}"


@app.exception_handler(sqlite3.OperationalError)
async def _on_sqlite_operational_error(request, exc):
    """/api/write 等接口没有包 try/except，SQLite 错误原本只会变成裸的
    "Internal Server Error"——10-31、11-01、11-02 共 26 次写入失败因此
    查不到原因。这里把消息和各盘剩余空间一并返回并落日志。
    """
    msg = str(exc)
    ctx = _disk_ctx()
    print(f"[ERROR] {request.url.path} sqlite: {msg} | {ctx}", flush=True)
    return JSONResponse(status_code=500, content={"detail": f"{msg} | {ctx}"})


@app.get("/healthz")
async def healthz():
    """守护进程专用存活探针。

    与 /health 的区别：async def 直接在事件循环上执行，不进线程池、不 stat
    12 个数据库路径，因此线程池被慢查询占满时仍能立即应答。只有"事件循环本身
    被饿死"才会超时——那才是真正需要重启的信号。
    """
    with _db_handles_lock:
        handles = _db_handles
    mem = _memory_status()
    return {
        "status": "ok",
        "version": "1.2.0",
        "time": datetime.now().isoformat(),
        "active_db_ops": handles,
        "write_lock_held": _write_lock.locked(),
        "ws_mb": mem[0] if mem else None,
        "priv_mb": mem[1] if mem else None,
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
    # 载荷规模留痕：行数/列数是事后判断"哪次写入压住了事件循环"的第一手证据。
    print(f"[WRITE] db={db_name} table={table_name} rows={row_count} cols={col_count} mode={mode}", flush=True)

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
                    # 旧表可能没有主键约束：首次转 upsert 时按 pk 清理重复行并建唯一
                    # 索引，否则 INSERT OR REPLACE 无法真正替换（会累积重复行）。
                    # 索引已经存在时绝不重复扫描全表 —— 见 _ensure_upsert_index 的说明。
                    db_cols = _get_table_columns(conn, table_name)
                    pk_exist = [c for c in pk_columns if c in db_cols]
                    if pk_exist:
                        _ensure_upsert_index(cursor, table_name, pk_exist)

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
                    _yield_gil()
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
                for _n, row in enumerate(rows, 1):
                    temp_row = []
                    for idx in common_indices:
                        val = row[idx] if idx < len(row) else None
                        temp_row.append(str(val) if val is not None else None)
                    temp_data.append(temp_row)
                    if _n % YIELD_ROWS == 0:
                        _yield_gil()

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

                # 主键列（仅保留实际存在的列；不存在则不过滤成 PK）
                pk_cols = [c for c in (pk_columns or []) if c in columns]
                col_defs = []
                for c in columns:
                    safe = c.replace(chr(34), chr(34) + chr(34))
                    if c in pk_cols:
                        col_defs.append(f'"{safe}" TEXT NOT NULL')
                    else:
                        col_defs.append(f'"{safe}" TEXT')
                if pk_cols:
                    pk_str = ", ".join(f'"{c.replace(chr(34), chr(34) + chr(34))}"' for c in pk_cols)
                    col_defs.append(f"PRIMARY KEY ({pk_str})")
                cursor.execute(f'CREATE TABLE "{table_name}" ({", ".join(col_defs)})')

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
                    _yield_gil()
                    cursor.executemany(insert_sql, clean_batch)
                    inserted += len(clean_batch)

                conn.commit()
                return {"success": True, "rows_written": inserted, "table": table_name, "mode": "full_replace"}

            else:
                raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")


def _import_excel(db_path: str, tmp_path: str, table: str, table_type: str,
                  add_group_column: bool, group_value: str) -> dict:
    """解析 Excel 并按 dedup_insert 语义入库。

    刻意写成同步函数：上传端点是 async def，直接在事件循环里跑 openpyxl 解析和
    executemany 会让 /healthz 与 TCP accept 一起停摆，守护进程只能靠"猜"判断死活。
    """
    df = _read_excel(tmp_path)
    if add_group_column:
        df['Group'] = group_value

    columns = df.columns.tolist()
    rows = df.values.tolist()
    row_count = len(rows)

    # 转换为字符串（None 保持 None）
    str_rows = []
    for _n, row in enumerate(rows, 1):
        str_rows.append([str(v) if pd.notna(v) else None for v in row])
        if _n % YIELD_ROWS == 0:
            _yield_gil()

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
                _yield_gil()

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
        print(f"[UPLOAD] {file.filename} bytes={len(content)} -> {db}/{table}", flush=True)
        return await run_in_threadpool(
            _import_excel, db_path, tmp_path, table, table_type,
            add_group_column, group_value,
        )

    except HTTPException:
        raise
    except Exception as e:
        ctx = _disk_ctx(db_path)
        print(f"[ERROR] upload_excel {file.filename} db={db} table={table}: {e} | {ctx}", flush=True)
        raise HTTPException(status_code=500, detail=f"{e} | {ctx}")
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
def list_tables(db: str, counts: bool = False):
    """列出数据库中的所有表；默认只返回表名（?counts=1 时才统计行数）。

    说明（2026-08-27）：原实现对每张表都跑 SELECT COUNT(*)，在大 WAL 库（如
    ipran_ume_kpi 的 -wal 曾膨胀到 193MB）上逐表 COUNT 要扫整个 WAL，导致
    /api/tables 耗时远超 60s、巡检超时判失败。巡检只用表名不用行数，故默认
    跳过 COUNT；需要行数时传 ?counts=1。"""
    db_path = _get_db_path(db)
    if not os.path.exists(db_path):
        return {"tables": [], "db_exists": False}

    with _open_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = []
        for (name,) in cursor.fetchall():
            count = None
            if counts:
                cursor.execute(f'SELECT COUNT(*) FROM "{name}"')
                count = cursor.fetchone()[0]
            tables.append({"name": name, "rows": count})
    return {"tables": tables, "db_exists": True}


@app.post("/api/read")
def read_table(payload: dict):
    """读取表格数据（SELECT 查询）"""
    db = payload.get("db", "")
    table = payload.get("table", "")
    columns = payload.get("columns", [])
    limit = min(int(payload.get("limit", 10000)), 100000)
    where = payload.get("where", "")
    order_by = payload.get("order_by", "")

    db_path = _get_db_path(db)
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail=f"Database not found: {db}")

    # Build SQL query
    col_clause = _read_col_clause(columns)
    sql = f'SELECT {col_clause} FROM "{table}"'

    if where:
        sql += f" WHERE {where}"

    if order_by:
        sql += f" ORDER BY {order_by}"

    sql += f" LIMIT {limit}"

    try:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        cursor.execute(sql)

        col_names = [description[0].strip('"') for description in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        conn.close()

        return {
            "success": True,
            "columns": col_names,
            "rows": [list(row) for row in rows],
            "count": len(rows)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


# ============================================================
# 只读 SQL 查询接口（2026-09-14 新增）
#
# 背景：my-finebi 看板门户原生看板的组件 SQL 是任意复杂 SELECT
# （UNION ALL / 嵌套子查询 / 聚合 / 计算列），/api/read 的
# table+where+order_by 模型无法表达，故新增本接口。
#
# 安全模型（分层，真实防线在连接层）：
#   a. 语句形状守卫：单语句（禁分号）、必须以 SELECT/WITH 开头
#   b. 连接级只读：PRAGMA query_only=ON —— 数据库层强制拒绝一切写操作
#   c. 高危标记拦截（仅拦截几乎不可能作为列名出现的模式，
#      避免误杀 BI 中常见的 Call/Update 等列名）
#   d. 可选 X-API-Token（环境变量 DB_API_TOKEN 设置后生效）
#   e. 结果行数硬上限 50000
# ============================================================
_READ_DANGEROUS = re.compile(
    r"(load_extension|xp_cmdshell|sp_executesql|sys_exec|master\.\.|"
    r"into\s+outfile|into\s+dumpfile|attach\s+database|detach\s+database|"
    r"pragma\s+\w+\s*=)",
    re.IGNORECASE,
)
_HAS_LIMIT_RE = re.compile(r"\b(limit\s+\d+|top\s+\d+|fetch\s+first)\b", re.IGNORECASE)


def _check_token(request: Request) -> None:
    """可选鉴权：仅当设置了 DB_API_TOKEN 时校验"""
    if not READONLY_TOKEN:
        return
    if request.headers.get("X-API-Token", "") != READONLY_TOKEN:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Token")


def _guard_readonly(sql: str) -> str:
    """只读语句守卫"""
    s = (sql or "").strip()
    if not s:
        raise HTTPException(status_code=400, detail="sql 不能为空")
    if ";" in s:
        raise HTTPException(status_code=400, detail="仅允许单条语句（不允许分号）")
    stripped = re.sub(r"(?s)/\*.*?\*/", " ", s)  # 去块注释再检查
    if not re.match(r"^\s*(select|with)\b", stripped, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="仅允许 SELECT / WITH 只读查询")
    if _READ_DANGEROUS.search(stripped):
        raise HTTPException(status_code=400, detail="SQL 含高危标记，已拒绝")
    return s


def _wrap_limit_readonly(sql: str, limit: int) -> str:
    """给无 LIMIT 的 SQL 包一层上限。

    包裹 limit+1 而非 limit：多取一行用于**准确判断是否发生截断**
    （返回行数 > limit 即说明还有更多数据），随后由调用方截回 limit 行。
    若只包裹 limit，则 fetchmany(limit+1) 永远取不到第 limit+1 行，
    truncated 会恒为 False —— 调用方无法得知结果被截断。

    已有 LIMIT/TOP/FETCH 的 SQL 不包裹，避免破坏原分页语义。
    """
    s = sql.strip().rstrip(";").strip()
    if _HAS_LIMIT_RE.search(s):
        return s
    return f"SELECT * FROM (\n{s}\n) AS _q LIMIT {limit + 1}"


@app.get("/api/dbs")
def list_dbs(request: Request):
    """列出可用逻辑库名及其文件存在状态（便于调用方发现可用数据源）"""
    _check_token(request)
    out = []
    for name, path in sorted(DB_MAP.items()):
        out.append({"db": name, "path": path, "exists": os.path.exists(path)})
    return {"dbs": out, "count": len(out)}


@app.post("/api/query")
def query_readonly(payload: dict, request: Request):
    """
    只读 SQL 查询（任意 SELECT / WITH）。

    请求体 JSON:
    {
        "db": "db.sqlite3",     # 逻辑库名，见 GET /api/dbs
        "sql": "SELECT ...",    # 单条只读语句
        "limit": 5000           # 可选，1..50000，默认 5000
    }

    响应:
    {
        "success": true,
        "columns": [...],
        "rows": [[...], ...],
        "count": 123,
        "truncated": false,
        "elapsed_ms": 12.3
    }
    """
    _check_token(request)

    db_name = payload.get("db")
    sql = payload.get("sql")
    if not db_name or not sql:
        raise HTTPException(status_code=400, detail="Missing required fields: db, sql")

    try:
        limit = max(1, min(int(payload.get("limit", 5000)), 50000))
    except (TypeError, ValueError):
        limit = 5000

    db_path = _get_db_path(db_name)
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail=f"Database not found: {db_name}")

    sql = _guard_readonly(sql)
    t0 = time.time()

    # 只读连接：不设 journal_mode=WAL（那是写操作，会触碰库头），
    # 只加 query_only + busy_timeout，保证对 FineBI 正在写的库零干扰。
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        cursor = conn.cursor()
        cursor.execute(_wrap_limit_readonly(sql, limit))
        columns = [d[0] for d in (cursor.description or [])]
        rows = cursor.fetchmany(limit + 1)
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    return {
        "success": True,
        "columns": columns,
        "rows": [list(r) for r in rows],
        "count": len(rows),
        "truncated": truncated,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    total_start = time.time()
    print(f"[API] SQLite Writer API v1.2.0 starting...")
    for _name, _path in sorted(DB_MAP.items()):
        print(f"[API] DB {_name:<34} exists={os.path.exists(_path)}  {_path}")
    print(f"[API] Auth: {'X-API-Token 已启用' if READONLY_TOKEN else '未启用（内网免认证）'}")
    # 先钉住工作集再开始服务，否则第一批大文件写入换来的热页会在下一个任务
    # 高峰被内存平衡器全部回收，探针就得等换页（实测 11s）。
    _pinned = _pin_working_set(WS_MIN_MB)
    _m = _memory_status()
    print(f"[API] 工作集下限 {_pinned} min={WS_MIN_MB}MB 现状 ws={_m[0] if _m else '?'}MB "
          f"priv={_m[1] if _m else '?'}MB")
    print(f"[API] Listening on {API_HOST}:{API_PORT}")

    # timeout_keep_alive 默认 5s：巡检和 FineBI 都复用长连接，5s 会被掐断后立刻重连，
    # 在 err.log 里留下成片 WinError 10054，掩盖真正的卡死现场。
    uvicorn.run(app, host=API_HOST, port=API_PORT, log_level="info", timeout_keep_alive=30)

    elapsed = time.time() - total_start
    print(f"[API] Server stopped. Runtime: {elapsed:.1f}s")
