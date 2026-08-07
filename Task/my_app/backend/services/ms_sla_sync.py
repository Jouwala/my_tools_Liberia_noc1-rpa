"""MS SLA 数据同步服务（Phase 4 从 ms_sla_service.py 拆分）

负责 RAN UME SLA 指标数据的抓取与入库：
- UME 登录认证（RSA + cookie 会话）与 HTTP 原始 socket 基础
- SLA History 查询任务创建/轮询/导出（多数据集并行）
- xlsx 解析 -> SQLite 入库（_SITE 表主键自动探测）-> FTP/远程 API 分发
路径/FTP/UME 等共享常量仍由 ms_sla_service 提供（本模块单向依赖，无循环）。
"""

import base64
import gc
import glob
import gzip
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import time
import copy
import logging
import warnings
import threading
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, date, timezone, timedelta
from ftplib import FTP, error_perm
from pathlib import Path

import openpyxl
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import PatternFill, Font
from backend.database import get_raw_connection


from backend.services.ms_sla_service import (  # Phase 4 拆分：共享常量/基础函数
    BATCH_SIZE,
    DB_NAME,
    DB_PATH,
    FTP_UP_HOST,
    FTP_UP_PASS,
    FTP_UP_USER,
    SLA_OUTPUT_DIR,
    UME_HOST,
    UME_PASSWORD,
    UME_PORT,
    UME_USERNAME,
    _SUBPROCESS_FLAGS,
    _db_writer,
    logger,
)


def _runtime_credentials():
    """运行时获取凭据（环境变量 > 数据库 > 模块默认值），支持页面改密后免重启生效。"""
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        from credential_store import get_credential
    return get_credential("zte_ume", UME_USERNAME, UME_PASSWORD)

# 并行查询线程数
MAX_PARALLEL_WORKERS = int(os.environ.get("SLA_PARALLEL_WORKERS", "4"))

# ========== 重试 / 超时配置（环境变量可调） ==========
HTTP_MAX_RETRIES = max(0, int(os.environ.get("SLA_HTTP_MAX_RETRIES", "3")))
HTTP_RETRY_DELAY = float(os.environ.get("SLA_HTTP_RETRY_DELAY", "1"))
HTTP_CONNECT_TIMEOUT = float(os.environ.get("SLA_CONNECT_TIMEOUT", "15"))
HTTP_READ_TIMEOUT = float(os.environ.get("SLA_READ_TIMEOUT", "90"))
# 时间范围：默认最近 32 天
DAYS_BACK = int(os.environ.get("SLA_DAYS_BACK", "7"))
# 1Month 粒度查询的回溯窗口：保持覆盖整月（报表 Month 行依赖月度值）
SLA_MONTH_DAYS_BACK = int(os.environ.get("SLA_MONTH_DAYS_BACK", "32"))

# _SITE 表主键的站点/网元标识列（精确匹配，避免 SubnetWork ID 等被关键字误选）
_SITE_PK_COLUMN_CANDIDATES = [
    "SITE ID", "Site ID", "NodeB ID", "NodeBId",
    "eNodeB ID", "eNodeBId", "ENodeB ID",
    "ME ID", "ManagedElement ID", "Managed\xa0Element", "ME",
]


def _detect_site_pk_column(headers: list) -> str | None:
    """在 _SITE 表头中查找真正的站点/网元标识列。"""
    for cand in _SITE_PK_COLUMN_CANDIDATES:
        if cand in headers:
            return cand
    return None


def _cols_unique(headers: list, data: list, cols: list) -> bool:
    """判断当批数据按 cols 组合是否唯一（用于避免 upsert 主键塌缩）。"""
    idxs = [headers.index(c) for c in cols if c in headers]
    if not idxs:
        return False
    seen = set()
    for row in data:
        key = tuple((row[i] if i < len(row) else None) for i in idxs)
        if key in seen:
            return False
        seen.add(key)
    return True


def _choose_pk_columns(headers: list, data: list, table_name: str) -> list:
    """为 ms_sla 表选择 upsert 主键，保证所选主键在当批数据内唯一。

    - _SITE 表：首列(时间) + 站点/网元列
    - 非 _SITE 表：首列(时间)；若首列不唯一，依次附加后续列直到唯一
    - 实在凑不出唯一键则抛异常（调用方据此报错/降级，而非静默塌缩）
    """
    if not headers or not data:
        raise Exception(f"[{table_name}] 无表头或数据，无法选择主键")
    pk_cols = [headers[0]]
    if "_SITE" in table_name:
        site_pk = _detect_site_pk_column(headers)
        if site_pk:
            pk_cols.append(site_pk)
    if _cols_unique(headers, data, pk_cols):
        return pk_cols
    # 首列（或 _SITE 主键）不唯一 -> 尝试附加后续列凑出唯一键
    for extra in headers[1:]:
        if extra in pk_cols:
            continue
        cand = pk_cols + [extra]
        if _cols_unique(headers, data, cand):
            logger.warning(f"[{table_name}] 主键首列非唯一，已扩展为 {cand}")
            return cand
    raise Exception(
        f"[{table_name}] 无法凑出唯一主键（首列={headers[0]!r}，"
        f"附加其余列仍不能去重），放弃 upsert 以免数据塌缩。请检查导出表结构。"
    )
SLA_HISTORY_PATH = "/api/pm-analysis/v2/history"
SLA_HISTORY_POLL_PATH = "/api/pm-analysis/v1/history"
SLA_HISTORY_EXPORT_PATH = "/api/pm-analysis/v3/history/export"
SLA_REFERER = f"https://{UME_HOST}:{UME_PORT}/iui/pm/angularTask/dist/pmManagement.html"

# 备用鉴权信息
FALLBACK_COOKIE = (
    "X-Rm-Data-Version-zenap=1773367620002_0_0_0_0_0_0_0_0; "
    "Z-AUTH-CODE-28001=1154983705_f188b025b7b64878ae0f4511e90ab1a2; "
    "x-dexmesh-user-28001=D86935A99B38A02CDAEA05C225E9303A21FA22B872499884D7B2A1E26A5645FE; "
    "forgerydefense-28001=cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"
)
FALLBACK_FORGERY = "cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"

# grouplayer / gr 显示名称替换规则
GROUP_LAYER_RENAME = {
    "me,WV4.IubLink": "Sites",
    "me,gv4.BTSSiteManager": "Sites",
    "me,eNodeBFunction": "Sites",
    "all": "NW",
}
GR_RENAME = {
    "2592000": "1Month",
    "86400": "1Day",
}

# SLA 查询配置
SLA_QUERY_CONFIGS = {
    "GSM": {
        "templateid": "1638004472426",
        "templatename": "KPI_RPA_SITE_MS_SLA_GSM",
        "motid": "gsmPm.cell",
        "nfctid": "MRNC",
        "containvcell": 0,
        "indexfillingtype": "zeroDenominator",
        "showbusinesscolumn": False,
        "versiondatacompare": False,
        "items": [
            "306024", "900241213", "901415213", "306002", "306006", "306003",
            "306008", "306035", "306036", "900008213", "1675910745777", "306004",
            "1638004469689", "1675910745799",
        ],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    },
    "UMTS": {
        "templateid": "1638004472427",
        "templatename": "KPI_RPA_SITE_MS_SLA_UMTS",
        "motid": "wPm.UtranCell,wPm.LogicCell",
        "nfctid": "MRNC",
        "containvcell": 2,
        "indexfillingtype": "zeroDenominator",
        "showbusinesscolumn": False,
        "versiondatacompare": False,
        "items": [
            "300249", "300240", "300294", "300243", "901593214", "300020",
            "300046", "300073", "300476", "300478", "300532", "300857",
            "300824", "300840", "901597214", "901598214", "300139", "900005214",
            "901411214", "901410214", "901620214", "901621214", "901622214",
            "901623214", "901604214", "901605214", "901603214", "901596214",
        ],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    },
    "FDD": {
        "templateid": "1638004472428",
        "templatename": "KPI_RPA_SITE_MS_SLA_FDD",
        "motid": "EUtranCellFDD",
        "businessmotid": "EUtranCellFDD,FDDV3.EUtranCellFDD",
        "nfctid": "ITBBU,SDR,#",
        "containvcell": 0,
        "indexfillingtype": "zeroDenominator",
        "showbusinesscolumn": True,
        "items": [
            "1638004469333", "1638004469335", "1638004469337", "1638004469340",
            "1638004469341", "1638004469330", "1638004469331", "C373343602",
            "C373343605", "1638004469342", "1638004469343", "1638004469344",
            "1638004469345", "C373200029", "C373364118", "C373353961",
            "1638004469332", "1638004469785", "1603456136636", "1638004477799",
        ],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [2, 2, 2, 2, 2, 2, 2, 1, 1, 2, 2, 2, 2, 1, 1, 1, 2, 2, 2, 2],
        "itempositionbusiness": [0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0],
    },
}
def read_xlsx_streaming(filepath):
    """流式读取xlsx文件，返回 (headers, data)"""
    with open(filepath, 'rb') as f:
        file_bytes = f.read()
    return read_xlsx_bytes(file_bytes)


def read_xlsx_bytes(file_bytes: bytes):
    """从内存字节直接解析 xlsx，不经磁盘。"""
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    try:
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        header_row = next(rows_iter)
        headers = [str(col).strip() if col is not None else f"col_{i}"
                   for i, col in enumerate(header_row)]
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
    """将数据增量写入 SQLite 数据库（按主键 upsert，保留历史）。

    主键：首列（时间）+ _SITE 表的站点/网元标识列，与远程 API 写入的 pk 规则保持一致。
    """
    with get_raw_connection(str(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=OFF")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.execute("PRAGMA temp_store=MEMORY")

        def _q(col):
            return f'"{col.replace(chr(34), chr(34)+chr(34))}"'

        # 建表（幂等，全部 TEXT，不强制 NOT NULL）
        col_defs = ", ".join(f"{_q(h)} TEXT" for h in headers)
        cursor.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" ({col_defs})')

        # 补充缺失列
        exist_cols = {r[1] for r in cursor.execute(f'PRAGMA table_info("{table_name}")').fetchall()}
        for h in headers:
            if h not in exist_cols:
                cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN {_q(h)} TEXT')

        # 主键：优先用 _choose_pk_columns（保证唯一，避免 upsert 塌缩）；
        # 若实在凑不出唯一键，降级为"无唯一索引的普通写入"（不塌缩、仅可能重复）并告警
        try:
            pk_cols = _choose_pk_columns(headers, data, table_name)
        except Exception as pk_err:
            logger.warning(f"[{table_name}] 无法选出唯一主键({pk_err})，本地写入降级为无唯一索引模式(不塌缩)")
            pk_cols = None

        # 保证唯一约束存在：先清理历史重复行，再建唯一索引（upsert 才能生效）
        if pk_cols:
            pk_q = ", ".join(_q(k) for k in pk_cols)
            try:
                cursor.execute(
                    f'DELETE FROM "{table_name}" WHERE rowid NOT IN ('
                    f'SELECT MIN(rowid) FROM "{table_name}" GROUP BY {pk_q})'
                )
                # 先删除旧的同名唯一索引，避免主键列变更后 IF NOT EXISTS 跳过导致旧索引残留
                cursor.execute(f'DROP INDEX IF EXISTS "u_{table_name}"')
                cursor.execute(
                    f'CREATE UNIQUE INDEX "u_{table_name}" ON "{table_name}" ({pk_q})'
                )
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] write_to_db: exception swallowed", exc_info=True)
                conn.rollback()

        quoted_headers = [_q(h) for h in headers]
        placeholders = ", ".join(["?"] * len(headers))
        insert_sql = f'INSERT OR REPLACE INTO "{table_name}" ({", ".join(quoted_headers)}) VALUES ({placeholders})'

        row_count = 0
        batch = []
        for row in data:
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

        if headers:
            first_col = headers[0].replace('"', '""')
            try:
                cursor.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_{first_col}" ON "{table_name}" ("{first_col}")')
                conn.commit()
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] write_to_db: exception swallowed", exc_info=True)
                pass
        conn.close()
        return row_count


def _upload_to_ftp(local_path, remote_dir, filename, max_retries=2):
    """上传文件到 FTP 服务器（带重试）"""
    for attempt in range(1, max_retries + 1):
        ftp = None
        try:
            ftp = FTP(FTP_UP_HOST, timeout=30)
            ftp.encoding = "utf-8"
            ftp.login(FTP_UP_USER, FTP_UP_PASS)
            ftp.cwd("/")
            parts = remote_dir.strip("/").split("/")
            for i in range(len(parts)):
                abs_path = "/" + "/".join(parts[:i + 1])
                try:
                    ftp.cwd(abs_path)
                except error_perm:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] _upload_to_ftp: exception swallowed", exc_info=True)
                    try:
                        ftp.mkd(abs_path)
                        ftp.cwd(abs_path)
                    except error_perm:
                        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _upload_to_ftp: exception swallowed", exc_info=True)
                        pass
            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {filename}", f)
            ftp.quit()
            return True
        except Exception as e:
            logger.warning(f"FTP上传失败(第{attempt}次): {e}")
            if ftp:
                try:
                    ftp.close()
                except Exception:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] _upload_to_ftp: exception swallowed", exc_info=True)
                    pass
    return False
_http_local = threading.local()


def _create_ssl_socket():
    """创建绕过证书校验的 TLS socket。"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers('ALL:@SECLEVEL=0')
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(HTTP_CONNECT_TIMEOUT)
    ssock = ctx.wrap_socket(sock)
    ssock.connect((UME_HOST, UME_PORT))
    ssock.settimeout(HTTP_READ_TIMEOUT)
    return ssock


def _get_thread_socket():
    ssock = getattr(_http_local, "socket", None)
    if ssock is None:
        ssock = _create_ssl_socket()
        _http_local.socket = ssock
    return ssock


def _close_thread_socket():
    ssock = getattr(_http_local, "socket", None)
    _http_local.socket = None
    if ssock is not None:
        try:
            ssock.close()
        except OSError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _close_thread_socket: exception swallowed", exc_info=True)
            pass


def _run_with_cleanup(fn, *args, **kwargs):
    """Wrap a pipeline task to ensure its TLS connection is released afterwards."""
    try:
        return fn(*args, **kwargs)
    finally:
        _close_thread_socket()


def _decode_chunked(data):
    """解码 HTTP chunked 响应体。"""
    result = bytearray()
    pos = 0
    while pos < len(data):
        line_end = data.find(b"\r\n", pos)
        if line_end == -1:
            break
        chunk_size_str = data[pos:line_end].decode('utf-8', errors='replace').strip()
        try:
            chunk_size = int(chunk_size_str, 16)
        except ValueError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _decode_chunked: exception swallowed", exc_info=True)
            break
        if chunk_size == 0:
            break
        pos = line_end + 2
        result.extend(data[pos:pos + chunk_size])
        pos += chunk_size + 2
    return bytes(result)


def _http_request(method, path, headers_extra=None, body=None, retry=0):
    """发送原始 HTTP 请求，带连接复用、bytearray接收、截断检测和重试。"""
    try:
        ssock = _get_thread_socket()
    except (ssl.SSLError, socket.timeout, ConnectionError, OSError) as e:
        if retry < HTTP_MAX_RETRIES:
            delay = HTTP_RETRY_DELAY * (2 ** retry) + random.uniform(0, 0.25)
            logger.warning(f"[SLA][HTTP] Connect failed (attempt {retry+1}): {e}, retry in {delay:.1f}s")
            time.sleep(delay)
            return _http_request(method, path, headers_extra=headers_extra, body=body, retry=retry + 1)
        raise

    headers = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: {UME_HOST}:{UME_PORT}\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Language: en-US,en;q=0.9\r\n"
        f"Accept-Encoding: identity\r\n"
        f"Connection: keep-alive\r\n"
        f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\r\n"
    )
    if headers_extra:
        headers += headers_extra
    if body:
        headers += f"Content-Length: {len(body)}\r\n"
    headers += "\r\n"

    request_bytes = headers.encode('utf-8')
    if body:
        request_bytes += body if isinstance(body, bytes) else body.encode('utf-8')

    try:
        ssock.sendall(request_bytes)
    except (socket.timeout, ConnectionError, OSError) as e:
        _close_thread_socket()
        if retry < HTTP_MAX_RETRIES:
            delay = HTTP_RETRY_DELAY * (2 ** retry) + random.uniform(0, 0.25)
            logger.warning(f"[SLA][HTTP] Send failed (attempt {retry+1}): {e}, retry in {delay:.1f}s")
            time.sleep(delay)
            return _http_request(method, path, headers_extra=headers_extra, body=body, retry=retry + 1)
        raise

    response_data = bytearray()
    content_length = None
    header_end_found = False
    header_end_pos = 0

    while True:
        try:
            chunk = ssock.recv(65536)
            if not chunk:
                break
            response_data.extend(chunk)
        except socket.timeout:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _http_request: exception swallowed", exc_info=True)
            break

        if not header_end_found:
            pos = response_data.find(b"\r\n\r\n")
            if pos != -1:
                header_end_found = True
                header_end_pos = pos
                hp = response_data[:pos].decode('utf-8', errors='replace')
                for line in hp.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        try:
                            content_length = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _http_request: exception swallowed", exc_info=True)
                            pass
                        break

        if header_end_found and content_length is not None:
            if len(response_data) - (header_end_pos + 4) >= content_length:
                break

    if header_end_found and content_length is not None:
        body_data = response_data[header_end_pos + 4:]
        if len(body_data) < content_length:
            _close_thread_socket()
            raise ConnectionError(f"Response truncated: {len(body_data)}/{content_length} bytes")

    header_end = response_data.find(b"\r\n\r\n")
    if header_end == -1:
        _close_thread_socket()
        if retry < HTTP_MAX_RETRIES:
            delay = HTTP_RETRY_DELAY * (2 ** retry) + random.uniform(0, 0.25)
            logger.warning(f"[SLA][HTTP] Cannot parse response (attempt {retry+1}), retry in {delay:.1f}s")
            time.sleep(delay)
            return _http_request(method, path, headers_extra=headers_extra, body=body, retry=retry + 1)
        raise Exception("Cannot parse HTTP response")

    header_part = response_data[:header_end].decode('utf-8', errors='replace')
    resp_body = bytes(response_data[header_end + 4:])
    status_line = header_part.split("\r\n")[0]

    resp_headers = {}
    for line in header_part.split("\r\n")[1:]:
        if ": " in line:
            k, v = line.split(": ", 1)
            resp_headers[k.lower()] = v

    if "chunked" in resp_headers.get("transfer-encoding", ""):
        resp_body = _decode_chunked(resp_body)
        _close_thread_socket()
    elif "close" in resp_headers.get("connection", "").lower() or content_length is None:
        _close_thread_socket()

    if "gzip" in resp_headers.get("content-encoding", ""):
        try:
            resp_body = gzip.decompress(resp_body)
        except Exception as exc:
            raise Exception(f"Failed to decompress gzip response: {exc}")

    return status_line, resp_headers, header_part, resp_body


def _rsa_encrypt_pem(plaintext, public_key_b64):
    """使用 RSA 公钥对明文进行 PKCS1v15 加密，返回 Base64 密文。"""
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives import serialization
    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
    public_key = serialization.load_pem_public_key(pem.encode())
    encrypted = public_key.encrypt(plaintext.encode('utf-8'), asym_padding.PKCS1v15())
    return base64.b64encode(encrypted).decode('ascii')
def _ume_login(max_retries=2):
    """执行 RAN UME 登录流程（优先使用共享缓存，避免同账户重复登录）。

    Args:
        max_retries: 登录失败时最大重试次数（含首次），默认2次
    """
    try:
        try:
            from backend.services.auth_manager import get_auth
        except ImportError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _ume_login: exception swallowed", exc_info=True)
            from auth_manager import get_auth
        result = get_auth(UME_HOST, UME_PORT, *_runtime_credentials())
        source = "缓存" if result["from_cache"] else "重新登录"
        logger.info(f"[LOGIN] 鉴权成功（来源: {source}）")
        return {"cookie": result["cookie"], "forgery_token": result["forgery_token"]}
    except Exception as e:
        logger.warning(f"[LOGIN] auth_manager 失败: {e}，使用备用 Cookie")
        return {"cookie": FALLBACK_COOKIE, "forgery_token": FALLBACK_FORGERY}
def _sla_auth_headers(cookie, forgery_token, extra=None):
    """构造 SLA 接口鉴权请求头。"""
    headers = (
        f"Content-Type: application/json; charset=UTF-8\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Encoding: gzip\r\n"
        f"Cookie: {cookie}\r\n"
        f"Referer: {SLA_REFERER}\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
    )
    if forgery_token:
        headers += f"forgerydefense: {forgery_token}\r\n"
    if extra:
        for k, v in extra.items():
            headers += f"{k}: {v}\r\n"
    return headers


def _http_request_with_retry(method, path, headers_extra=None, body=None, max_retries=2, retry_statuses=None):
    """带重试的 HTTP 请求封装。"""
    if retry_statuses is None:
        retry_statuses = ("499", "500", "502", "503", "504")
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            status, hdrs, raw_hdrs, resp_body = _http_request(method, path, headers_extra=headers_extra, body=body)
            if any(code in status for code in retry_statuses):
                last_exception = Exception(f"Retryable status: {status}")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
            return status, hdrs, raw_hdrs, resp_body
        except Exception as e:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _http_request_with_retry: exception swallowed", exc_info=True)
            last_exception = e
            if attempt < max_retries:
                time.sleep(2 ** attempt)
            else:
                break
    raise last_exception or Exception(f"HTTP request failed after {max_retries + 1} attempts")


def _build_sla_payload(tech, grouplayer, gr_seconds, start_iso=None, end_iso=None):
    """构造 SLA 历史指标查询 Payload。"""
    cfg = SLA_QUERY_CONFIGS.get(tech)
    if not cfg:
        raise ValueError(f"Unsupported tech: {tech}")
    now = datetime.now(timezone.utc)
    if end_iso is None:
        end_iso = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if start_iso is None:
        # 1Day 查询用小窗口（本地库增量累积），1Month 查询保持整月窗口
        days_back = SLA_MONTH_DAYS_BACK if gr_seconds == "2592000" else DAYS_BACK
        start_dt = (now - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    items = cfg["items"]
    item_count = len(items)
    timeinfo = {
        "mode": 1, "start": start_iso, "end": end_iso, "relative": -1,
        "timezonetype": "1", "clienttimezone": "Atlantic/Reykjavik",
        "showtimezoneoffset": False, "querylongtime": {"type": 3, "value": 1},
        "timespanfilter": "00:00:00-24:00:00", "dayfiltertype": 0,
        "dayinmonthfilter": "1111111111111111111111111111111",
    }
    payload = {
        "arraycounterinfos": [], "datatype": 0, "displaymode": 0,
        "favoriteconditionname": cfg["templatename"], "gr": gr_seconds,
        "groupattributetype": 0, "groupbygroup": False, "groupbyplmn": False,
        "grouptype": 0, "items": items,
        "itemsposition": cfg.get("itemsposition", [0] * item_count),
        "itemsposition1": cfg.get("itemsposition1", [0] * item_count),
        "motid": cfg["motid"], "nfctid": cfg["nfctid"],
        "plmnpdfdisplaymode": False, "queryallbusiness": False,
        "showbusinesscolumn": cfg["showbusinesscolumn"], "showintegrity": False,
        "straightquery": False, "templatename": cfg["templatename"],
        "templateid": cfg["templateid"],
    }
    if "versiondatacompare" in cfg:
        payload["versiondatacompare"] = cfg["versiondatacompare"]
    payload.update({"needdeployfilter": False, "timeinfo": timeinfo, "indexfillingtype": cfg["indexfillingtype"]})
    if "businessmotid" in cfg:
        payload["businessmotid"] = cfg["businessmotid"]
    if "itempositionbusiness" in cfg:
        payload["itempositionbusiness"] = cfg["itempositionbusiness"]
    payload.update({
        "thresholdinfos": [], "templatetype": 0, "filterlayer": "all",
        "grouplayer": grouplayer, "containvcell": cfg["containvcell"],
        "resfilterattribute": "", "uilocations": [], "reslocation": [], "inexistenceres": False,
    })
    if "businessmotid" in cfg:
        payload["groupbusinessids"] = []
        payload["businessfilterscope"] = []
    payload.update({"firstDayOfWeek": 7, "iswireless": True, "hidehistorystopbutton": True,
                    "opencustomizehistoryexport": False, "opentemplatecustomcolumn": False})
    return payload


def _create_sla_history_query(cookie, forgery_token, payload):
    """创建 SLA 历史指标查询任务，返回 queryid。"""
    logger.info(f"[SLA] 创建查询: {payload.get('templatename')} / {payload.get('grouplayer')} / {payload.get('gr')}")
    body = json.dumps(payload, ensure_ascii=False)
    headers = _sla_auth_headers(cookie, forgery_token)
    status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
        "POST", SLA_HISTORY_PATH, headers_extra=headers, body=body.encode('utf-8'), max_retries=2,
    )
    if "200" not in status:
        raise Exception(f"Create SLA query failed: {status}")
    data = json.loads(resp_body.decode('utf-8', errors='replace'))
    queryid = data.get("queryid") or data.get("id")
    if not queryid:
        raise Exception(f"No queryid returned")
    logger.info(f"[SLA] Query ID: {queryid}")
    return queryid


def _wait_sla_history_ready(cookie, forgery_token, queryid, timeout=300, interval=5):
    """轮询 SLA 查询进度直到完成。"""
    path = f"{SLA_HISTORY_POLL_PATH}?type=0&queryid={queryid}"
    headers = _sla_auth_headers(cookie, forgery_token, extra={"Accept": "application/json, text/plain, */*"})
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, hdrs, raw_hdrs, resp_body = _http_request_with_retry("GET", path, headers_extra=headers, max_retries=1)
        data = json.loads(resp_body.decode('utf-8', errors='replace'))
        progress = data.get("progress", 0)
        querystate = data.get("querystate", 0)
        if querystate == 1 or progress >= 100:
            return data
        time.sleep(interval)
    raise Exception(f"SLA query timed out after {timeout}s")


def _export_sla_history(cookie, forgery_token, queryid, filename, output_path=None) -> bytes:
    """导出并下载 SLA 历史指标结果，直接返回 xlsx 字节（不落盘）。"""
    payload = {
        "id": queryid, "filename": filename, "chartlayout": 1, "contentmode": 0,
        "customizefieldtype": "0", "exportfiletype": 1, "exportserialnumber": False,
        "exporttableheaders": False, "formatwithts": 0, "imageinfo": [],
        "itemshowtype": 0, "tableheaders": {},
    }
    body = json.dumps(payload, ensure_ascii=False)
    headers = _sla_auth_headers(cookie, forgery_token)
    status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
        "POST", SLA_HISTORY_EXPORT_PATH, headers_extra=headers, body=body.encode('utf-8'), max_retries=2,
    )
    if "200" not in status:
        raise Exception(f"Export SLA history failed: {status}")
    logger.info(f"[SLA] 已导出: {filename}.xlsx ({len(resp_body)} bytes, in-memory)")
    return resp_body
def _build_sla_filename(templatename, grouplayer, gr_seconds):
    """构造 SLA 导出文件名。"""
    group_label = GROUP_LAYER_RENAME.get(grouplayer, grouplayer)
    gr_label = GR_RENAME.get(gr_seconds, gr_seconds)
    return f"{templatename}_{group_label}_{gr_label}"


def _build_legacy_table_name(tech, grouplayer, gr_seconds):
    """构造与旧脚本兼容的表名。"""
    period = "1month" if gr_seconds == "2592000" else "1day"
    layer = "SITE" if grouplayer != "all" else "NW"
    templatename = SLA_QUERY_CONFIGS[tech]["templatename"]
    return f"Hourly_{templatename}{period}_{layer}"


def _derive_table_name(filepath):
    """根据文件路径生成表名。"""
    base = os.path.splitext(os.path.basename(filepath))[0]
    base = re.sub(r'_\d{14}$', '', base)
    return f"Hourly_{base}"
def _run_single_sla_query(cookie, forgery_token, task_cfg):
    """执行单个 SLA 查询任务（用于多线程并行）。"""
    tech = task_cfg["tech"]
    grouplayer = task_cfg["grouplayer"]
    gr_seconds = task_cfg["gr"]
    task_index = task_cfg.get("index", 0)

    stagger_sec = task_index * 0.8
    if stagger_sec > 0:
        time.sleep(stagger_sec)

    cfg = SLA_QUERY_CONFIGS[tech]
    filename = _build_sla_filename(cfg["templatename"], grouplayer, gr_seconds)
    output_path = os.path.join(SLA_OUTPUT_DIR, f"{filename}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.xlsx")

    logger.info(f"[SLA] 开始查询 [{tech}/{grouplayer}/{gr_seconds}]...")
    payload = _build_sla_payload(tech, grouplayer, gr_seconds)
    queryid = _create_sla_history_query(cookie, forgery_token, payload)
    status = _wait_sla_history_ready(cookie, forgery_token, queryid)
    logger.info(f"[SLA] 查询完成 [{tech}/{grouplayer}/{gr_seconds}]: totalcount={status.get('totalcount')}")

    xlsx_bytes = _export_sla_history(cookie, forgery_token, queryid, filename=filename)
    table_name = _build_legacy_table_name(tech, grouplayer, gr_seconds)
    return {"xlsx_bytes": xlsx_bytes, "table_name": table_name}


def _cleanup_sla_exports():
    """清理所有 SLA 导出文件。"""
    deleted = 0
    for cfg in SLA_QUERY_CONFIGS.values():
        templatename = cfg["templatename"]
        for grouplayer in GROUP_LAYER_RENAME.keys():
            for gr_seconds in GR_RENAME.keys():
                base_name = _build_sla_filename(templatename, grouplayer, gr_seconds)
                pattern = os.path.join(SLA_OUTPUT_DIR, f"{base_name}_*.xlsx")
                for fpath in glob.glob(pattern):
                    if os.path.basename(fpath).startswith("~$"):
                        continue
                    try:
                        os.remove(fpath)
                        deleted += 1
                    except PermissionError:
                        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _cleanup_sla_exports: exception swallowed", exc_info=True)
                        try:
                            subprocess.run(
                                ['powershell', '-Command', f'Remove-Item -Path "{fpath}" -Force -ErrorAction Stop'],
                                capture_output=True, timeout=15,
                                creationflags=_SUBPROCESS_FLAGS,
                            )
                            if not os.path.exists(fpath):
                                deleted += 1
                        except Exception:
                            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _cleanup_sla_exports: exception swallowed", exc_info=True)
                            pass
                    except Exception:
                        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _cleanup_sla_exports: exception swallowed", exc_info=True)
                        pass
    return deleted
def run_ms_sla_sync(max_workers=None):
    """
    执行完整的 SLA 指标同步流程：API 查询 -> 入库 -> FTP 上传 -> 清理。
    替代原来的 run_ms_sla_daily_import + run_ms_sla_monthly_import。
    """
    if max_workers is None:
        max_workers = MAX_PARALLEL_WORKERS
    t_start = time.time()
    logger.info(f"RAN UME SLA 同步开始 (workers={max_workers}, days_back={DAYS_BACK})")

    # 1. 登录
    auth = _ume_login()
    cookie = auth["cookie"]
    forgery_token = auth["forgery_token"]

    # 2. 构建任务列表: 3 tech × (Sites + NW) × (1Day + 1Month) = 12 个任务
    task_configs = []
    idx = 0
    tech_layer_map = {"GSM": "me,gv4.BTSSiteManager", "UMTS": "me,WV4.IubLink", "FDD": "me,eNodeBFunction"}
    for tech in SLA_QUERY_CONFIGS.keys():
        for grouplayer in (tech_layer_map[tech], "all"):
            for gr in ("2592000", "86400"):
                task_configs.append({"tech": tech, "grouplayer": grouplayer, "gr": gr, "index": idx})
                idx += 1

    logger.info(f"  总任务数: {len(task_configs)}")

    # 3. 并行获取所有 SLA 文件
    download_results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_cfg = {
            executor.submit(_run_with_cleanup, _run_single_sla_query, cookie, forgery_token, cfg): cfg
            for cfg in task_configs
        }
        for future in as_completed(future_to_cfg):
            cfg = future_to_cfg[future]
            try:
                result = future.result()
                if result:
                    download_results.append(result)
            except Exception as e:
                logger.warning(f"  SLA查询失败 [{cfg['tech']}/{cfg['grouplayer']}/{cfg['gr']}]: {e}")

    if not download_results:
        elapsed = time.time() - t_start
        logger.error("SLA 同步失败: 无文件下载")
        return {"success": False, "error": "无文件下载", "elapsed_seconds": round(elapsed, 2)}

    # 4. 顺序导入数据库（从内存读取）
    logger.info(f"  导入 {len(download_results)} 个文件到数据库...")
    total_imported = 0
    imported_tables = []
    table_data_cache = []  # 缓存 (table_name, headers, data) 用于 API 写入
    for item in download_results:
        xlsx_bytes = item["xlsx_bytes"]
        table_name = item["table_name"]
        try:
            headers, data = read_xlsx_bytes(xlsx_bytes)
            row_count = write_to_db(DB_PATH, table_name, headers, data)
            total_imported += row_count
            imported_tables.append(table_name)
            table_data_cache.append((table_name, headers, data))
            logger.info(f"    {table_name}: {row_count} 行")
        except Exception as e:
            logger.warning(f"    导入失败 {table_name}: {e}")

    # 5. API 优先写入远程数据库，失败则回退 FTP 上传
    api_ok = False
    if _db_writer is not None:
        api_ok = True
        for table_name, headers, data in table_data_cache:
            try:
                if not data:
                    raise Exception(f"解析后无数据行: {table_name}")
                str_data = [[str(v) if v is not None else None for v in row] for row in data]
                # 主键：用 _choose_pk_columns 保证唯一，避免 upsert 静默塌缩；
                # 凑不出唯一键时抛出明确异常（被下方 except 捕获并标记 API 失败，不塌缩）
                pk_cols = _choose_pk_columns(headers, data, table_name)
                api_result = _db_writer.write_data(
                    db=DB_NAME,
                    table=table_name,
                    columns=headers,
                    rows=str_data,
                    mode="upsert",
                    pk_columns=pk_cols if headers else None,
                )
                api_rows = api_result.get("rows_written", 0)
                if api_rows == 0:
                    raise Exception(f"API 返回 0 行写入: {table_name}")
                logger.info(f"  [API] {table_name}: {api_rows} rows")
            except Exception as e:
                logger.error(f"  [API] {table_name} 写入失败: {e}")
                api_ok = False
        if api_ok:
            logger.info("  [API] 远程写入完成，跳过 FTP 上传")
        else:
            logger.warning("  [API] 部分表写入失败，回退到 FTP 上传")

    if not api_ok:
        logger.warning("  [API] 部分表写入失败，数据已保留在本地 SQLite")

    # 释放缓存
    del table_data_cache
    gc.collect()

    # 6. 清理本地 xlsx 文件
    deleted = _cleanup_sla_exports()
    logger.info(f"  清理文件: {deleted} 个")

    gc.collect()
    elapsed = time.time() - t_start
    logger.info(f"RAN UME SLA 同步完成: {total_imported} 行, {len(imported_tables)} 表, {elapsed:.1f}s")
    return {
        "success": True,
        "downloaded": len(download_results),
        "total_rows": total_imported,
        "tables": imported_tables,
        "api_ok": api_ok,
        "ftp_uploaded": False,
        "files_cleaned": deleted,
        "elapsed_seconds": round(elapsed, 2),
    }
