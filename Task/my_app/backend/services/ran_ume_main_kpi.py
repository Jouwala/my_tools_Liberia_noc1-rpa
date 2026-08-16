# -*- coding: utf-8 -*-
"""
import logging
RAN UME Main KPI 每日同步脚本

功能：
1. 登录 ZTE RAN UME 网管系统，获取鉴权 Cookie 与 forgery token。
2. 根据 Payload 2.txt 中的配置，批量创建 Main KPI 历史指标查询任务：
   - 技术类型：GSM(2G)、UMTS(3G)、FDD(4G)
   - 聚合层级：Cells、Sites、Group、NW
   - 时间粒度：1Day（86400 秒）
3. 轮询查询进度直到完成，导出为 Excel 文件。
4. 通过 HTTP API 将 Excel 数据直接写入远程 SQLite 数据库（WAL 模式安全）。
5. 清理本地已处理的 xlsx 文件。

数据库写入方式：
- 使用 DbWriterClient 通过 HTTP POST 上传 Excel 到远程服务
- 远程服务按主键去重后增量插入
- NW 层级数据自动添加 Group='NW' 列
- 回退方案：如果 API 不可用，自动回退到 FTP 下载/上传模式
"""

import logging
import base64
import gc
import glob
import gzip
import io
import json
import os
import re
import socket
import ssl
import subprocess
import sqlite3
import sys
import time
import warnings
import threading
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from ftplib import FTP, error_perm

import pandas as pd
from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names, table_columns

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:ran_ume_main_kpi>: exception swallowed", exc_info=True)
    pass

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# ============================================================
# 配置
# ============================================================
HOST = "10.100.28.27"
PORT = 28001
USERNAME = "NOC"
PASSWORD = "Zte@2025!"


def _runtime_credentials():
    """运行时获取凭据（环境变量 > 数据库 > 模块默认值），支持页面改密后免重启生效。"""
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        from credential_store import get_credential
    return get_credential("zte_ume", USERNAME, PASSWORD)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

# 并行查询线程数
MAX_PARALLEL_WORKERS = int(os.environ.get("MAIN_KPI_PARALLEL_WORKERS", "4"))

# ========== 重试 / 超时配置（环境变量可调） ==========
HTTP_MAX_RETRIES = max(0, int(os.environ.get("MAIN_KPI_HTTP_MAX_RETRIES", "3")))
HTTP_RETRY_DELAY = float(os.environ.get("MAIN_KPI_HTTP_RETRY_DELAY", "1"))
HTTP_CONNECT_TIMEOUT = float(os.environ.get("MAIN_KPI_CONNECT_TIMEOUT", "15"))
HTTP_READ_TIMEOUT = float(os.environ.get("MAIN_KPI_READ_TIMEOUT", "90"))

# 时间范围：每日更新只需要最近 3 天（覆盖周末），首次运行可设大值
DAYS_BACK = int(os.environ.get("MAIN_KPI_DAYS_BACK", "3"))

# ========== 外部化配置（Settings 页面可编辑的 main_kpi_config.json） ==========
try:
    from backend.services.task_config_files import load_json_config
    _MAIN_CONF = load_json_config(Path(__file__).resolve().parent / "main_kpi_config.json")
except Exception:
    _MAIN_CONF = None
if _MAIN_CONF:
    HOST = _MAIN_CONF.get("host", HOST)
    PORT = int(_MAIN_CONF.get("port", PORT))
    if not os.environ.get("MAIN_KPI_DAYS_BACK"):
        DAYS_BACK = max(1, int(_MAIN_CONF.get("days_back", DAYS_BACK)))
    HISTORY_REFERER = f"https://{HOST}:{PORT}/iui/pm/angularTask/dist/pmManagement.html"
    print(f"[MAIN_KPI] 已加载 main_kpi_config.json: host={HOST}, days_back={DAYS_BACK}")

# SLA / PM 接口路径
HISTORY_PATH = "/api/pm-analysis/v2/history"
HISTORY_POLL_PATH = "/api/pm-analysis/v1/history"
HISTORY_EXPORT_PATH = "/api/pm-analysis/v3/history/export"
HISTORY_REFERER = f"https://{HOST}:{PORT}/iui/pm/angularTask/dist/pmManagement.html"

# 数据库配置
DB_NAME = "db.sqlite3"

# 远程写入 API 配置（替代 FTP 下载/上传）
try:
    from backend.services.db_writer_client import DbWriterClient
except ImportError:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:ran_ume_main_kpi>: exception swallowed", exc_info=True)
    from db_writer_client import DbWriterClient
try:
    _db_writer = DbWriterClient()
except Exception:
    _db_writer = None
    print("[WARNING] db_writer_client 初始化失败，将回退到 FTP 模式")

# 备用鉴权信息
FALLBACK_COOKIE = (
    "X-Rm-Data-Version-zenap=1773367620002_0_0_0_0_0_0_0_0; "
    "Z-AUTH-CODE-28001=1154983705_f188b025b7b64878ae0f4511e90ab1a2; "
    "x-dexmesh-user-28001=D86935A99B38A02CDAEA05C225E9303A21FA22B872499884D7B2A1E26A5645FE; "
    "forgerydefense-28001=cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"
)
FALLBACK_FORGERY = "cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"

# grouplayer 显示名称替换规则
GROUP_LAYER_RENAME = {
    "me,WV4.IubLink": "Sites",
    "me,gv4.BTSSiteManager": "Sites",
    "me,eNodeBFunction": "Sites",
    "me,gv4.BTSSiteManager,gv4.BTS.cell": "Cells",
    "me,eNodeBFunction,EUtranCellFDD": "Cells",
    "me,WV4.IubLink,WV4.UtranCell": "Cells",
    "all": "NW",
}

# gr 显示名称替换规则
GR_RENAME = {
    "2592000": "1Month",
    "86400": "1Day",
}

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
# KPI 查询配置（从 Payload 2.txt 提取）
# ============================================================
MAIN_KPI_QUERY_CONFIGS = {
    "GSM": {
        "templateid": "1638004472354",
        "templatename": "GSM_KPIs_ZTE_OLR_FB",
        "motid": "gsmPm.cell",
        "nfctid": "MRNC",
        "containvcell": 0,
        "indexfillingtype": "zeroDenominator",
        "showbusinesscolumn": False,
        "items": ["306024", "306002", "306006", "306003", "306008", "1675910745777", "306004"],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [0, 0, 0, 0, 0, 0, 0],
        "uilocations": [
            {"haslogicmoc": False, "id": "706b4d6f-11c7-41b9-b2de-68f77a4e559d", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "491d8c88-8c1c-4f29-8516-748b2f2a5d32", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "0e4d065e-c2a2-4cf6-a783-0e892dd262c1", "moc": "group.ran.topo", "model": "rangroup"},
        ],
    },
    "UMTS": {
        "templateid": "1638004472355",
        "templatename": "UMTS_KPIs_ZTE_OLR_FB",
        "motid": "wPm.UtranCell,wPm.LogicCell",
        "nfctid": "MRNC",
        "containvcell": 2,
        "indexfillingtype": "default",
        "showbusinesscolumn": False,
        "items": ["300857", "901593214", "901597214", "901598214", "300020", "300043", "300249", "901604214", "901605214", "300532", "901410214", "901411214", "300476", "300139", "300294"],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0],
        "itemsposition1": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "uilocations": [
            {"haslogicmoc": False, "id": "02bb459f-04b2-4254-a5e4-2fcca30ba2f0", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "970b0b1d-7069-403a-ba76-f28717fd5970", "moc": "group.ran.topo", "model": "rangroup"},
        ],
    },
    "FDD": {
        "templateid": "1638004472356",
        "templatename": "FDD_KPIs_ZTE_OLR_FB",
        "motid": "EUtranCellFDD",
        "businessmotid": "EUtranCellFDD,FDDV3.EUtranCellFDD",
        "nfctid": "ITBBU,SDR,#",
        "containvcell": 0,
        "indexfillingtype": "default",
        "showbusinesscolumn": True,
        "items": ["1638004469333", "1638004469340", "1638004469330", "1638004469331", "1638004469342", "1638004469343", "1638004469344", "1638004469345", "C373200029", "1638004469332", "1638004469785"],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [2, 2, 2, 2, 2, 2, 2, 2, 1, 2, 2],
        "itempositionbusiness": [0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0],
        "uilocations": [
            {"haslogicmoc": False, "id": "6bd47747-1d35-45ec-8acf-5eff139101bf", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "d417d820-6257-42a8-b919-a5ed48df2e68", "moc": "group.ran.topo", "model": "rangroup"},
        ],
    },
}

# 任务配置：每个查询对应的目标表、层级、是否添加 Group 列、showbusinesscolumn 覆盖
MAIN_KPI_TASKS = [
    # GSM
    {"tech": "GSM", "grouplayer": "me,gv4.BTSSiteManager,gv4.BTS.cell", "gr": "86400", "groupbygroup": True, "layer": "Cells", "table": "2G_Main_Kpi_Cell_Daily", "add_group_column": False, "showbusinesscolumn": None},
    {"tech": "GSM", "grouplayer": "me,gv4.BTSSiteManager", "gr": "86400", "groupbygroup": True, "layer": "Sites", "table": "2G_Main_Kpi_Site_Daily", "add_group_column": False, "showbusinesscolumn": None},
    {"tech": "GSM", "grouplayer": "all", "gr": "86400", "groupbygroup": True, "layer": "Group", "table": "2G_Main_Kpi_group_Daily", "add_group_column": False, "showbusinesscolumn": None},
    {"tech": "GSM", "grouplayer": "all", "gr": "86400", "groupbygroup": False, "layer": "NW", "table": "2G_Main_Kpi_group_Daily", "add_group_column": True, "showbusinesscolumn": None},
    # UMTS
    {"tech": "UMTS", "grouplayer": "me,WV4.IubLink,WV4.UtranCell", "gr": "86400", "groupbygroup": True, "layer": "Cells", "table": "3G_Main_Kpi_Cell_Daily", "add_group_column": False, "showbusinesscolumn": None},
    {"tech": "UMTS", "grouplayer": "me,WV4.IubLink", "gr": "86400", "groupbygroup": True, "layer": "Sites", "table": "3G_Main_Kpi_Site_Daily", "add_group_column": False, "showbusinesscolumn": None},
    {"tech": "UMTS", "grouplayer": "all", "gr": "86400", "groupbygroup": True, "layer": "Group", "table": "3G_Main_Kpi_group_Daily", "add_group_column": False, "showbusinesscolumn": None},
    {"tech": "UMTS", "grouplayer": "all", "gr": "86400", "groupbygroup": False, "layer": "NW", "table": "3G_Main_Kpi_group_Daily", "add_group_column": True, "showbusinesscolumn": None},
    # FDD — Cells/Sites: showbusinesscolumn=true; Group/NW: showbusinesscolumn=false（与 Payload 2.txt 一致）
    {"tech": "FDD", "grouplayer": "me,eNodeBFunction,EUtranCellFDD", "gr": "86400", "groupbygroup": True, "layer": "Cells", "table": "4G_Main_Kpi_Cell_Daily", "add_group_column": False, "showbusinesscolumn": True},
    {"tech": "FDD", "grouplayer": "me,eNodeBFunction", "gr": "86400", "groupbygroup": True, "layer": "Sites", "table": "4G_Main_Kpi_Site_Daily", "add_group_column": False, "showbusinesscolumn": True},
    {"tech": "FDD", "grouplayer": "all", "gr": "86400", "groupbygroup": True, "layer": "Group", "table": "4G_Main_Kpi_group_Daily", "add_group_column": False, "showbusinesscolumn": False},
    {"tech": "FDD", "grouplayer": "all", "gr": "86400", "groupbygroup": False, "layer": "NW", "table": "4G_Main_Kpi_group_Daily", "add_group_column": True, "showbusinesscolumn": False},
]

# ============================================================
# HTTP / SSL 工具函数（连接复用 + bytearray + 截断检测）
# ============================================================
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
    ssock.connect((HOST, PORT))
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
            print(f"[HTTP] Connect failed (attempt {retry+1}): {e}, retry in {delay:.1f}s")
            time.sleep(delay)
            return _http_request(method, path, headers_extra=headers_extra, body=body, retry=retry + 1)
        raise

    headers = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: {HOST}:{PORT}\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Language: en-US,en;q=0.9\r\n"
        f"Accept-Encoding: identity\r\n"
        f"Connection: keep-alive\r\n"
        f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36\r\n"
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
            print(f"[HTTP] Send failed (attempt {retry+1}): {e}, retry in {delay:.1f}s")
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

    # Truncation detection
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
            print(f"[HTTP] Cannot parse response (attempt {retry+1}), retry in {delay:.1f}s")
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
    """使用 RSA 公钥（Base64 编码）对明文进行 PKCS1v15 加密，返回 Base64 密文。"""
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives import serialization

    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
    public_key = serialization.load_pem_public_key(pem.encode())

    encrypted = public_key.encrypt(
        plaintext.encode('utf-8'),
        asym_padding.PKCS1v15()
    )
    return base64.b64encode(encrypted).decode('ascii')


# ============================================================
# 登录
# ============================================================
def login():
    """执行 RAN UME 登录流程（优先使用共享缓存，避免同账户重复登录）。"""
    try:
        try:
            from backend.services.auth_manager import get_auth
        except ImportError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] login: exception swallowed", exc_info=True)
            from auth_manager import get_auth
        result = get_auth(HOST, PORT, *_runtime_credentials())
        source = "缓存" if result["from_cache"] else "重新登录"
        print(f"[LOGIN] 鉴权成功（来源: {source}）")
        return {"cookie": result["cookie"], "forgery_token": result["forgery_token"]}
    except Exception as e:
        print(f"[LOGIN] auth_manager 失败: {e}")
        print("[LOGIN] Falling back to hardcoded cookies...")
        return {"cookie": FALLBACK_COOKIE, "forgery_token": FALLBACK_FORGERY}


# ============================================================
# KPI 查询
# ============================================================
def _auth_headers(cookie: str, forgery_token: str, extra: dict | None = None) -> str:
    """构造 KPI 接口需要的鉴权请求头。"""
    headers = (
        f"Content-Type: application/json; charset=UTF-8\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Encoding: gzip\r\n"
        f"Cookie: {cookie}\r\n"
        f"Referer: {HISTORY_REFERER}\r\n"
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


def _http_request_with_retry(
    method,
    path,
    headers_extra=None,
    body=None,
    max_retries: int = 2,
    retry_statuses: tuple | None = None,
) -> tuple:
    """带重试的 HTTP 请求封装，对 499/5xx 进行指数退避重试。"""
    if retry_statuses is None:
        retry_statuses = ("499", "500", "502", "503", "504")

    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            status, hdrs, raw_hdrs, resp_body = _http_request(
                method, path, headers_extra=headers_extra, body=body
            )
            if any(code in status for code in retry_statuses):
                last_exception = Exception(f"Retryable status: {status}")
                if attempt < max_retries:
                    wait_sec = 2 ** attempt
                    print(f"[HTTP] {status} on {path}, retrying in {wait_sec}s (attempt {attempt + 1}/{max_retries + 1})...")
                    time.sleep(wait_sec)
                    continue
            return status, hdrs, raw_hdrs, resp_body
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                wait_sec = 2 ** attempt
                print(f"[HTTP] Request failed: {e}, retrying in {wait_sec}s (attempt {attempt + 1}/{max_retries + 1})...")
                time.sleep(wait_sec)
            else:
                break

    raise last_exception or Exception(f"HTTP request failed after {max_retries + 1} attempts")


def build_kpi_payload(tech: str, grouplayer: str, gr_seconds: str, groupbygroup: bool,
                      start_iso: str | None = None, end_iso: str | None = None,
                      showbusinesscolumn: bool | None = None) -> dict:
    """构造 Main KPI 历史指标查询 Payload，字段顺序与 Payload 2.txt 一致。"""
    cfg = MAIN_KPI_QUERY_CONFIGS.get(tech)
    if not cfg:
        raise ValueError(f"Unsupported tech: {tech}")

    now = datetime.now(timezone.utc)
    if end_iso is None:
        end_iso = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if start_iso is None:
        start_dt = (now - timedelta(days=DAYS_BACK)).replace(hour=0, minute=0, second=0, microsecond=0)
        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    items = cfg["items"]
    item_count = len(items)

    timeinfo = {
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
    }

    # showbusinesscolumn: 任务级别覆盖优先，否则使用配置默认值
    _showbusinesscolumn = showbusinesscolumn if showbusinesscolumn is not None else cfg["showbusinesscolumn"]

    payload = {
        "arraycounterinfos": [],
        "datatype": 0,
        "displaymode": 0,
        "favoriteconditionname": cfg["templatename"],
        "gr": gr_seconds,
        "groupattributetype": 0,
        "groupbygroup": groupbygroup,
        "groupbyplmn": False,
        "grouptype": 0,
        "items": items,
        "itemsposition": cfg.get("itemsposition", [0] * item_count),
        "itemsposition1": cfg.get("itemsposition1", [0] * item_count),
        "motid": cfg["motid"],
        "nfctid": cfg["nfctid"],
        "plmnpdfdisplaymode": False,
        "queryallbusiness": False,
        "showbusinesscolumn": _showbusinesscolumn,
        "showintegrity": False,
        "straightquery": False,
        "templatename": cfg["templatename"],
        "templateid": cfg["templateid"],
    }

    if "versiondatacompare" in cfg:
        payload["versiondatacompare"] = cfg["versiondatacompare"]

    payload.update({
        "needdeployfilter": False,
        "timeinfo": timeinfo,
        "indexfillingtype": cfg["indexfillingtype"],
    })

    if "businessmotid" in cfg:
        payload["businessmotid"] = cfg["businessmotid"]
    if "itempositionbusiness" in cfg:
        payload["itempositionbusiness"] = cfg["itempositionbusiness"]

    payload.update({
        "thresholdinfos": [],
        "templatetype": 0,
        "filterlayer": "group",
        "grouplayer": grouplayer,
        "containvcell": cfg["containvcell"],
        "resfilterattribute": "",
        "uilocations": cfg.get("uilocations", []),
        "reslocation": [],
        "inexistenceres": False,
    })

    if "businessmotid" in cfg:
        payload["groupbusinessids"] = []
        payload["businessfilterscope"] = []

    payload.update({
        "firstDayOfWeek": 7,
        "iswireless": True,
        "hidehistorystopbutton": True,
        "opencustomizehistoryexport": False,
        "opentemplatecustomcolumn": False,
    })

    return payload


def create_history_query(cookie: str, forgery_token: str, payload: dict) -> str:
    """创建 KPI 历史指标查询任务，返回 queryid。"""
    print(f"[KPI] Creating history query: {payload.get('templatename')} / {payload.get('grouplayer')} / gr={payload.get('gr')} / groupbygroup={payload.get('groupbygroup')}")
    body = json.dumps(payload, ensure_ascii=False)
    headers = _auth_headers(cookie, forgery_token)

    try:
        status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
            "POST", HISTORY_PATH, headers_extra=headers, body=body.encode('utf-8'), max_retries=2,
        )
    except Exception as e:
        print(f"[KPI] Create query failed after retries: {e}")
        raise

    print(f"[KPI] Create query status: {status}")
    resp_text = resp_body.decode('utf-8', errors='replace')
    print(f"[KPI] Create query response: {resp_text[:500]}")

    if "200" not in status:
        print(f"[KPI] Request headers:\n{headers}")
        print(f"[KPI] Request body preview:\n{body[:1000]}")
        raise Exception(f"Create KPI query failed: {status}")

    data = json.loads(resp_text)
    queryid = data.get("queryid") or data.get("id")
    if not queryid:
        raise Exception(f"No queryid returned: {resp_text[:500]}")
    print(f"[KPI] Query ID: {queryid}")
    return queryid


def wait_history_ready(cookie: str, forgery_token: str, queryid: str,
                       timeout: int = 300, interval: int = 5) -> dict:
    """轮询 KPI 历史指标查询进度，直到完成或超时。"""
    print(f"[KPI] Polling query progress (timeout={timeout}s, interval={interval}s)...")
    path = f"{HISTORY_POLL_PATH}?type=0&queryid={queryid}"
    headers = _auth_headers(cookie, forgery_token, extra={"Accept": "application/json, text/plain, */*"})

    deadline = time.time() + timeout
    while time.time() < deadline:
        status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
            "GET", path, headers_extra=headers, max_retries=1,
        )
        resp_text = resp_body.decode('utf-8', errors='replace')
        data = json.loads(resp_text)
        progress = data.get("progress", 0)
        querystate = data.get("querystate", 0)
        print(f"[KPI] Progress: {progress}%, state: {querystate}")

        if querystate == 1 or progress >= 100:
            print("[KPI] Query ready")
            return data

        time.sleep(interval)

    raise Exception(f"KPI query timed out after {timeout}s")


def export_history(cookie: str, forgery_token: str, queryid: str, filename: str,
                   output_path: str | None = None) -> bytes:
    """导出并下载 KPI 历史指标结果，直接返回 xlsx 字节（不落盘）。"""
    payload = {
        "id": queryid,
        "filename": filename,
        "chartlayout": 1,
        "contentmode": 0,
        "customizefieldtype": "0",
        "exportfiletype": 1,
        "exportserialnumber": False,
        "exporttableheaders": False,
        "formatwithts": 0,
        "imageinfo": [],
        "itemshowtype": 0,
        "tableheaders": {},
    }

    print(f"[KPI] Exporting history data: {filename}")
    body = json.dumps(payload, ensure_ascii=False)
    headers = _auth_headers(cookie, forgery_token)

    status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
        "POST", HISTORY_EXPORT_PATH, headers_extra=headers, body=body.encode('utf-8'), max_retries=2,
    )
    print(f"[KPI] Export status: {status}")

    if "200" not in status:
        raise Exception(f"Export KPI history failed: {status}")

    print(f"[KPI] Exported: {filename}.xlsx ({len(resp_body)} bytes, in-memory)")
    return resp_body


# ============================================================
# 文件命名
# ============================================================
def build_filename(templatename: str, grouplayer: str, gr_seconds: str) -> str:
    """按规则构造 KPI 导出文件名（不含扩展名）。"""
    group_label = GROUP_LAYER_RENAME.get(grouplayer, grouplayer)
    if grouplayer == "all":
        # all + groupbygroup=false -> NW; all + groupbygroup=true -> Group
        # 这里由调用方在 task 中显式指定 layer，所以不再重复处理
        pass
    gr_label = GR_RENAME.get(gr_seconds, gr_seconds)
    return f"{templatename}_{group_label}_{gr_label}"


# ============================================================
# FTP 下载 / 上传（已废弃，保留备用）
# ============================================================
from backend.config.remote_host import get_ftp_host  # 远程主机统一来源
FTP_USER = "FINEBI"
FTP_PASS = "DX"
FTP_REMOTE_DIR = "/Python"
FTP_UPLOAD_USER = "ZTEEMS"
FTP_UPLOAD_PASS = "DX"
FTP_UPLOAD_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI/RAN"


def download_from_ftp(remote_dir: str, filename: str, local_path: str,
                      user: str | None = None, password: str | None = None,
                      max_retries: int = 2) -> bool:
    """[已废弃] 从 FTP 服务器下载文件。请使用 DbWriterClient 代替。"""
    _user = user or FTP_USER
    _pass = password or FTP_PASS
    for attempt in range(1, max_retries + 1):
        print(f"[FTP] 连接 {get_ftp_host()} 下载 {filename} ...（第 {attempt} 次）")
        ftp = None
        try:
            ftp = FTP(get_ftp_host(), timeout=30)
            ftp.encoding = "utf-8"
            ftp.login(_user, _pass)
            ftp.cwd("/")
            parts = remote_dir.strip("/").split("/")
            for i in range(len(parts)):
                abs_path = "/" + "/".join(parts[:i + 1])
                try:
                    ftp.cwd(abs_path)
                except error_perm:
                    raise
            with open(local_path, "wb") as f:
                ftp.retrbinary(f"RETR {filename}", f.write)
            ftp.quit()
            return True
        except Exception as e:
            print(f"  [ERROR] FTP 下载失败: {e}")
            if ftp:
                try:
                    ftp.close()
                except Exception:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] download_from_ftp: exception swallowed", exc_info=True)
                    pass
    return False


def upload_to_ftp(local_path: str, remote_dir: str, filename: str,
                  user: str | None = None, password: str | None = None,
                  max_retries: int = 2) -> bool:
    """[已废弃] 上传文件到 FTP 服务器。请使用 DbWriterClient 代替。"""
    _user = user or FTP_USER
    _pass = password or FTP_PASS
    for attempt in range(1, max_retries + 1):
        print(f"[FTP] 连接 {get_ftp_host()} 上传 {filename} ...（第 {attempt} 次）")
        ftp = None
        try:
            ftp = FTP(get_ftp_host(), timeout=30)
            ftp.encoding = "utf-8"
            ftp.login(_user, _pass)
            ftp.cwd("/")
            parts = remote_dir.strip("/").split("/")
            for i in range(len(parts)):
                abs_path = "/" + "/".join(parts[:i + 1])
                try:
                    ftp.cwd(abs_path)
                except error_perm:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] upload_to_ftp: exception swallowed", exc_info=True)
                    try:
                        ftp.mkd(abs_path)
                        ftp.cwd(abs_path)
                    except error_perm:
                        logging.getLogger(__name__).warning("[SILENT-EXCEPT] upload_to_ftp: exception swallowed", exc_info=True)
                        pass
            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {filename}", f)
            ftp.quit()
            return True
        except Exception as e:
            print(f"  [ERROR] FTP 上传失败: {e}")
            if ftp:
                try:
                    ftp.close()
                except Exception:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] upload_to_ftp: exception swallowed", exc_info=True)
                    pass
    return False


# ============================================================
# 数据库更新（参考 excel2db.py，增强主键去重）
# ============================================================
def quote_identifier(name: str) -> str:
    """为 SQL 标识符添加双引号。"""
    return f'"{name}"'


def get_table_info(conn, table_name: str) -> list[str]:
    """获取表的列名列表。"""
    return table_columns(conn, table_name)


def _strip_item_prefix(col_name: str) -> str:
    """去掉列名中的 {item_id}: 前缀，如 '306024:TCH total traffic number(erl)' -> 'TCH total traffic number(erl)'"""
    # 匹配模式: 数字或字母数字ID后面跟冒号
    m = re.match(r'^\d+:(.+)', col_name)
    return m.group(1) if m else col_name


def add_missing_columns(conn, table_name: str, excel_columns: list[str]) -> None:
    """自动检测并向数据库表中添加 Excel 中存在但数据库中缺失的列。
    支持去掉 {item_id}: 前缀后的模糊匹配，避免因旧数据列名带前缀而重复添加列。
    # TODO-PHASE3-DDL: ALTER TABLE ... ADD COLUMN ... NUMERIC 在 sqlite 与 pg 均兼容，
    但 ran_ume db 为独立库，pg 模式需确保 conn 指向正确的目标库。"""
    db_cols = get_table_info(conn, table_name)
    # 规范化列名：去掉 {item_id}: 前缀
    db_cols_normalized = {_strip_item_prefix(c): c for c in db_cols}

    missing_cols = []
    for col in excel_columns:
        normalized = _strip_item_prefix(col)
        if normalized not in db_cols_normalized and col not in db_cols:
            missing_cols.append(col)

    if missing_cols:
        cursor = conn.cursor()
        for col in missing_cols:
            print(f"  [DB] 检测到新字段，正在向表 {table_name} 添加列: {col}")
            try:
                alter_query = f"ALTER TABLE {quote_identifier(table_name)} ADD COLUMN {quote_identifier(col)} NUMERIC"
                cursor.execute(alter_query)
            except Exception as e:
                print(f"  [DB] 向表 {table_name} 添加列 {col} 失败: {e}")
        conn.commit()


def detect_primary_keys(table_type: str, columns: list[str]) -> list[str]:
    """根据表类型和列名，自动检测主键列。"""
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


def sync_excel_to_db(excel_file_path: str, db_table: str, db_path: str,
                     table_type: str, add_group_column: bool = False) -> int:
    """同步 Excel 数据到数据库表：先全量导入临时表，再用 SQL 按主键去重插入目标表。"""
    print(f"\n[DB] 开始同步 {os.path.basename(excel_file_path)} -> {db_table}")

    if not os.path.exists(excel_file_path):
        print(f"  [WARNING] Excel 文件不存在: {excel_file_path}")
        return 0

    # 读取 Excel
    excel_df = pd.read_excel(excel_file_path)
    print(f"  读取 Excel: {excel_df.shape[0]} 行, {excel_df.shape[1]} 列")

    # 为 NW 数据添加 Group 列
    if add_group_column:
        excel_df['Group'] = 'NW'
        print(f"  已添加 'Group' 列，值为 'NW'")

    with get_raw_connection(db_path) as conn:
        try:
            cursor = conn.cursor()
            table_exists = db_table in set(list_table_names(conn))

            if not table_exists:
                # 表不存在，直接创建并插入
                # TODO-PHASE3-SCHEMA: ran_ume 独立库，pg 模式需 engine_override 指向该库；
                # sqlite 模式保持原有 df.to_sql 行为不变。
                excel_df.to_sql(db_table, conn, if_exists='replace', index=False)
                print(f"  表 {db_table} 不存在，已创建并插入 {len(excel_df)} 条记录")
                return len(excel_df)

            # 自动添加缺失列（已支持 strip item_id 前缀匹配）
            add_missing_columns(conn, db_table, excel_df.columns.tolist())

            # 获取数据库列信息，建立 Excel 列名到 DB 列名的映射
            db_columns = get_table_info(conn, db_table)
            excel_columns = excel_df.columns.tolist()

            # 建立规范化列名映射：normalized_name -> db_column_name
            db_norm_map = {_strip_item_prefix(c): c for c in db_columns}

            # 将 Excel 列名映射到 DB 列名（优先匹配精确名称，再匹配规范化名称）
            excel_to_db = {}
            for ec in excel_columns:
                if ec in db_columns:
                    excel_to_db[ec] = ec
                else:
                    norm = _strip_item_prefix(ec)
                    if norm in db_norm_map:
                        excel_to_db[ec] = db_norm_map[norm]

            # 重命名 Excel DataFrame 列名为 DB 列名（仅对能映射的列）
            if excel_to_db:
                excel_df = excel_df.rename(columns=excel_to_db)

            # 只取 Excel 和 DB 共有的列
            common_columns = [col for col in db_columns if col in excel_df.columns.tolist()]
            if not common_columns:
                print(f"  [ERROR] Excel 文件和数据库表 {db_table} 没有共同的列，无法同步")
                return 0

            excel_df = excel_df[common_columns]

            # 检测主键列
            pk_cols = detect_primary_keys(table_type, common_columns)
            if len(pk_cols) < 2:
                print(f"  [WARNING] 未检测到足够主键列，回退到使用所有共同列去重")
                pk_cols = common_columns

            print(f"  使用主键列去重: {pk_cols}")

            # 将 Excel 数据写入临时表
            temp_table = f"_temp_{db_table}"
            cursor.execute(f'DROP TABLE IF EXISTS "{temp_table}"')
            # TODO-PHASE3-SCHEMA: ran_ume 独立库，pg 模式需 engine_override 指向该库；
            # sqlite 模式保持原有 df.to_sql 行为不变。
            excel_df.to_sql(temp_table, conn, if_exists='replace', index=False)

            # 用 SQL LEFT JOIN 按主键去重，仅插入新行
            pk_conditions = " AND ".join(
                f't."{pk}" = m."{pk}"' for pk in pk_cols
            )
            cols_str = ", ".join(f'"{c}"' for c in common_columns)
            # SELECT 需要带 t. 前缀，避免与 m 表列名歧义
            cols_str_t = ", ".join(f't."{c}"' for c in common_columns)

            sql = (
                f'INSERT INTO "{db_table}" ({cols_str}) '
                f'SELECT {cols_str_t} FROM "{temp_table}" t '
                f'LEFT JOIN "{db_table}" m ON {pk_conditions} '
                f'WHERE m."{pk_cols[0]}" IS NULL'
            )

            cursor.execute(sql)
            inserted = cursor.rowcount
            conn.commit()

            # 清理临时表
            cursor.execute(f'DROP TABLE IF EXISTS "{temp_table}"')
            conn.commit()

            if inserted > 0:
                print(f"  表 {db_table} 有更新，插入了 {inserted} 条新记录")
            else:
                print(f"  表 {db_table} 无更新，无需操作")
            return inserted

        except Exception as e:
            print(f"  [ERROR] 同步 {excel_file_path} 到表 {db_table} 时出错: {e}")
            raise
        finally:
            conn.close()


# ============================================================
# 任务执行
# ============================================================
def _run_single_kpi_query(cookie: str, forgery_token: str, task: dict, task_index: int) -> dict | None:
    """执行单个 KPI 查询任务，返回文件路径和目标表信息。"""
    tech = task["tech"]
    grouplayer = task["grouplayer"]
    gr = task["gr"]
    groupbygroup = task["groupbygroup"]
    layer = task["layer"]

    # 错峰启动
    stagger_sec = task_index * 0.8
    if stagger_sec > 0:
        print(f"[MAIN] KPI query [{tech}/{layer}] waiting {stagger_sec:.1f}s to stagger...")
        time.sleep(stagger_sec)

    cfg = MAIN_KPI_QUERY_CONFIGS[tech]
    filename = build_filename(cfg["templatename"], grouplayer, gr)
    # 文件名需要区分 Group/NW（两者 grouplayer 都是 all）
    filename = f"{cfg['templatename']}_{layer}_{GR_RENAME.get(gr, gr)}"
    output_path = os.path.join(OUTPUT_DIR, f"{filename}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.xlsx")

    print(f"[MAIN] Starting KPI query [{tech}/{layer}]...")

    payload = build_kpi_payload(tech, grouplayer, gr, groupbygroup,
                                showbusinesscolumn=task.get("showbusinesscolumn"))
    queryid = create_history_query(cookie, forgery_token, payload)
    status = wait_history_ready(cookie, forgery_token, queryid)
    print(f"[MAIN] KPI query [{tech}/{layer}] ready: totalcount={status.get('totalcount')}")

    saved_bytes = export_history(cookie, forgery_token, queryid, filename=filename)
    print(f"[MAIN] KPI export [{tech}/{layer}] done: {len(saved_bytes)} bytes (in-memory)")

    return {
        "xlsx_bytes": saved_bytes,
        "filename": f"{filename}.xlsx",
        "table": task["table"],
        "table_type": layer,
        "add_group_column": task["add_group_column"],
    }


def cleanup_kpi_exports(output_dir: str = OUTPUT_DIR) -> int:
    """清理本地 KPI xlsx 文件。"""
    deleted = 0
    for cfg in MAIN_KPI_QUERY_CONFIGS.values():
        templatename = cfg["templatename"]
        for layer in ("Cells", "Sites", "Group", "NW"):
            for gr_label in GR_RENAME.values():
                pattern = os.path.join(output_dir, f"{templatename}_{layer}_{gr_label}_*.xlsx")
                for fpath in glob.glob(pattern):
                    if os.path.basename(fpath).startswith("~$"):
                        continue
                    try:
                        os.remove(fpath)
                        print(f"[CLEANUP] deleted: {os.path.basename(fpath)}")
                        deleted += 1
                    except PermissionError:
                        print(f"[CLEANUP] locked, retry with PowerShell: {os.path.basename(fpath)}")
                        try:
                            subprocess.run(
                                ['powershell', '-Command',
                                 f'Remove-Item -Path "{fpath}" -Force -ErrorAction Stop'],
                                capture_output=True, timeout=15,
                                creationflags=_SUBPROCESS_FLAGS,
                            )
                            if not os.path.exists(fpath):
                                print(f"[CLEANUP] deleted (force): {os.path.basename(fpath)}")
                                deleted += 1
                            else:
                                import ctypes
                                ctypes.windll.kernel32.MoveFileExW(fpath, None, 0x4)
                        except Exception as e:
                            print(f"[CLEANUP] failed: {os.path.basename(fpath)}: {e}")
                    except Exception as e:
                        print(f"[CLEANUP] failed: {os.path.basename(fpath)}: {e}")
    return deleted


def run_main_kpi_sync(cookie: str | None = None, forgery_token: str | None = None,
                      max_workers: int = MAX_PARALLEL_WORKERS) -> dict:
    """执行完整的 Main KPI 同步流程：获取 -> 通过 HTTP API 写入远程数据库 -> 清理。"""
    if not cookie or not forgery_token:
        auth = login()
        cookie = auth["cookie"]
        forgery_token = auth["forgery_token"]

    print(f"\n[MAIN] Total KPI tasks: {len(MAIN_KPI_TASKS)}, max parallel workers: {max_workers}")

    # 1. 并行获取所有 KPI 文件
    download_results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {
            executor.submit(_run_with_cleanup, _run_single_kpi_query, cookie, forgery_token, task, idx): task
            for idx, task in enumerate(MAIN_KPI_TASKS)
        }
        for future in as_completed(future_to_task):
            task = future_to_task[future]
            try:
                result = future.result()
                if result:
                    download_results.append(result)
            except Exception as e:
                print(f"[MAIN] KPI query [{task['tech']}/{task['layer']}] failed: {e}")

    if not download_results:
        print("[MAIN] No files downloaded, skipping DB import.")
        return {"success": False, "downloaded": 0, "imported_rows": 0, "tables": [],
                "api_ok": False, "error": "未下载到任何 KPI 文件"}

    # 2. 通过 HTTP API 写入远程数据库（全程内存，不落盘）
    print(f"\n[API] 通过远程写入 API 导入 {len(download_results)} 个文件")
    total_imported = 0
    imported_tables = []
    api_errors = []
    api_ok = True

    if _db_writer is None:
        print("[API] [ERROR] db_writer_client 不可用，无法写入")
        api_ok = False
        api_errors.append("db_writer_client 不可用")
    else:
        for item in download_results:
            try:
                result = _db_writer.upload_excel_bytes(
                    db=DB_NAME,
                    table=item["table"],
                    file_bytes=item["xlsx_bytes"],
                    filename=item["filename"],
                    table_type=item["table_type"],
                    add_group_column=item["add_group_column"],
                    group_value="NW",
                )
                rows = result.get("rows_written", 0)
                if rows == 0:
                    # 数据已存在/已同步（dedup 后无新增行），不视为失败
                    print(f"[API] {item['table']}: 无新增行（数据已存在/已同步）")
                else:
                    total_imported += rows
                    if item["table"] not in imported_tables:
                        imported_tables.append(item["table"])
                    print(f"[API] {item['table']}: +{rows} 行")
            except Exception as e:
                print(f"[API] [ERROR] 写入 {item['table']} 失败: {e}")
                api_ok = False
                api_errors.append(f"{item['table']}: {e}")

    # 3. 释放内存
    downloaded_count = len(download_results)
    download_results = None
    gc.collect()

    # API 写入失败时显式标记任务失败，避免"任务成功但远程库未更新"的假成功
    if not api_ok:
        print("[API] [WARNING] 远程写入存在失败，任务将标记为失败")

    return {
        "success": api_ok,
        "downloaded": downloaded_count,
        "imported_rows": total_imported,
        "tables": imported_tables,
        "api_ok": api_ok,
        "error": "; ".join(api_errors) if api_errors else None,
    }


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    total_start = time.time()
    print(f"[MAIN] RAN UME Main KPI sync started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[MAIN] Output dir: {OUTPUT_DIR}")
    print(f"[MAIN] DB target: {DB_NAME} (via remote API)")

    stats = run_main_kpi_sync()

    total_elapsed = time.time() - total_start
    print("\n" + "=" * 60)
    print(f"[MAIN] Total completed in {total_elapsed:.2f} seconds")
    print(f"[MAIN] Downloaded: {stats['downloaded']} files")
    print(f"[MAIN] Imported rows: {stats['imported_rows']}")
    print(f"[MAIN] Tables: {stats['tables']}")
    print(f"[MAIN] Remote write: {'OK' if stats['api_ok'] else 'FAILED'}")