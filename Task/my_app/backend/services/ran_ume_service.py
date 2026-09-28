"""
RAN UME 服务集成
集成 ran_ume_login.py（PM 数据获取）+ generate_daily_availability.py（可用性报表生成）
从 ZTE RAN UME 网管系统获取 2G/3G/FDD/TDD PM 历史指标，生成 Daily Availability KPI 报表
"""
import ssl
import socket
import sys
import json
import time
import re
import base64
import gzip
import glob
import io
import gc
import os
import sqlite3
import urllib.request
import urllib.error
import warnings
import logging
import threading
import random
from ftplib import FTP, error_perm
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names

logger = logging.getLogger("ran_ume_service")

try:
    import openpyxl
except ImportError:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:ran_ume_service>: exception swallowed", exc_info=True)
    openpyxl = None

try:
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:ran_ume_service>: exception swallowed", exc_info=True)
    pd = None
    plt = None
    np = None

try:
    from .atomic_write import atomic_excel_writer, AtomicReplaceFallback, cleanup_stale_tmp_files
except ImportError:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:ran_ume_service>: exception swallowed", exc_info=True)
    from atomic_write import atomic_excel_writer, AtomicReplaceFallback, cleanup_stale_tmp_files

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# 远程写入 API 配置（DB Orange: ran_kpi_daily_202606.sqlite3）
DB_ORANGE_NAME = "ran_kpi_daily_202606.sqlite3"
# Availability 报表数据源库（由 network_kpi_sync 写入，含新旧两套 Group 命名的全量历史）
DB_DAILY_NAME = "ran_kpi_daily.sqlite3"
from backend.config.remote_host import get_api_host, get_ftp_host  # 远程主机统一来源
API_PORT = int(os.environ.get("DB_WRITER_PORT", "8765"))

# 查询时间范围：按天粒度 PM 指标，远程为 upsert 写入（历史保留），
# 每日运行只需回补最近几天即可覆盖漏跑与 UME 修正。
RAN_UME_DAYS_BACK = int(os.environ.get("RAN_UME_DAYS_BACK", "7"))
try:
    from backend.services.db_writer_client import DbWriterClient
except ImportError:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:ran_ume_service>: exception swallowed", exc_info=True)
    from db_writer_client import DbWriterClient
try:
    _db_writer = DbWriterClient()
except Exception:
    _db_writer = None
    print("[WARNING] db_writer_client 初始化失败，DB Orange 写入不可用")

# ========== 配置 ==========
HOST = os.environ.get("RAN_UME_HOST", "10.100.28.27")
PORT = int(os.environ.get("RAN_UME_PORT", "28001"))
USERNAME = os.environ.get("RAN_UME_USER", "NOC")
# 2026-09-27：原默认值为硬编码明文口令（已入库）。改为默认空串 —— 真实口令由
# credential_store 的 `zte_ume` 组提供；env/配置都取不到时留空让认证明确失败。
PASSWORD = os.environ.get("RAN_UME_PASS", "")

# ========== 外部化配置（Settings 页面可编辑的 ran_ume_config.json） ==========
# 优先级：环境变量 > 配置文件 > 内置默认。凭据走 credential_store。
try:
    from backend.services.task_config_files import load_json_config
    _RAN_UME_CONF = load_json_config(Path(__file__).resolve().parent / "ran_ume_config.json")
except Exception:
    _RAN_UME_CONF = None
if _RAN_UME_CONF:
    if not os.environ.get("RAN_UME_HOST"):
        HOST = _RAN_UME_CONF.get("host", HOST)
    if not os.environ.get("RAN_UME_PORT"):
        PORT = int(_RAN_UME_CONF.get("port", PORT))
    if not os.environ.get("RAN_UME_DAYS_BACK"):
        RAN_UME_DAYS_BACK = max(1, int(_RAN_UME_CONF.get("days_back", RAN_UME_DAYS_BACK)))
    logging.getLogger("ran_ume_service").info(
        f"[RAN] 已加载 ran_ume_config.json: host={HOST}, days_back={RAN_UME_DAYS_BACK}")


def _runtime_credentials():
    """运行时获取凭据（环境变量 > 数据库 > 模块默认值），支持页面改密后免重启生效。"""
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        from credential_store import get_credential
    return get_credential("zte_ume", USERNAME, PASSWORD,
                          env_user="RAN_UME_USER", env_secret="RAN_UME_PASS")

RAN_UME_DATA_DIR = Path(r"d:\01_RPA\Task\my_app\data\ran_ume")
RAN_UME_DATA_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_DIR = str(RAN_UME_DATA_DIR / "exports")
os.makedirs(OUTPUT_DIR, exist_ok=True)
MAX_PARALLEL_WORKERS = max(1, int(os.environ.get("RAN_UME_MAX_PARALLEL", "4")))

# ========== 重试 / 超时配置（环境变量可调） ==========
HTTP_MAX_RETRIES = max(0, int(os.environ.get("RAN_UME_HTTP_MAX_RETRIES", "3")))
HTTP_RETRY_DELAY = float(os.environ.get("RAN_UME_HTTP_RETRY_DELAY", "1"))
HTTP_CONNECT_TIMEOUT = float(os.environ.get("RAN_UME_CONNECT_TIMEOUT", "15"))
HTTP_READ_TIMEOUT = float(os.environ.get("RAN_UME_READ_TIMEOUT", "90"))

SCRIPT_DIR = Path(__file__).resolve().parent
# ran_kpi_daily.sqlite3 仅用于 Availability 报表读取（由 ran_ume_network_kpi.py 写入）
DB_PATH = RAN_UME_DATA_DIR / "ran_kpi_daily.sqlite3"

# FTP 配置（仅用于 Availability 图表图片上传）
# FTP 主机已收敛到 backend.config.remote_host.get_ftp_host()
FTP_USER = "ZTEEMS"
FTP_PASS = "DX"

# 技术类型
TECHS = ["2G", "3G", "FDD", "TDD"]

# 可用性报表输出目录
AVAILABILITY_OUTPUT_DIR = RAN_UME_DATA_DIR

# 备用鉴权信息
FALLBACK_COOKIE = (
    "X-Rm-Data-Version-zenap=1773367620002_0_0_0_0_0_0_0_0; "
    "Z-AUTH-CODE-28001=1154983705_f188b025b7b64878ae0f4511e90ab1a2; "
    "x-dexmesh-user-28001=D86935A99B38A02CDAEA05C225E9303A21FA22B872499884D7B2A1E26A5645FE; "
    "forgerydefense-28001=cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"
)
FALLBACK_FORGERY = "cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"

# Availability 配置
TARGET_SHEETS = ['Availability-NW', 'Availability-Regular', 'Availability-COOL', 'Availability-ERA']

TECH_MAP = {
    "2G_OLIB_Network_KPIs": "2G",
    "3G_OLIB_Network_KPIs": "3G",
    "FDD_OLIB_Network_KPIs": "FDD",
    "TDD_OLIB_Network_KPIs": "TDD",
}

SHEET_CONFIG = {
    'Availability-NW': {
        # 兼容新旧命名：旧写入路径为 G_NW，network_kpi_sync 新写入为 2G_NW/3G_NW/FDD_NW/TDD_NW
        'patterns': [r'^G_NW$', r'_NW$'],
        'tech_groups': {'2G': '2G ALL', '3G': '3G ALL', 'FDD': 'FDD ALL', 'TDD': 'TDD ALL'},
    },
    'Availability-Regular': {
        'patterns': [r'Regular'],
        'tech_groups': {'2G': '2G Regular', '3G': '3G Regular', 'FDD': 'FDD Regular'},
    },
    'Availability-COOL': {
        'patterns': [r'Cooli'],
        'tech_groups': {'2G': '2G Cooli', '3G': '3G Cooli', 'FDD': 'FDD Cooli'},
    },
    'Availability-ERA': {
        'patterns': [r'ERA'],
        'tech_groups': {'2G': '2G ERA', 'FDD': 'FDD ERA'},
    },
}

AVAILABILITY_METRICS = {
    "2G_OLIB_Network_KPIs": "TCH in service rate(%)",
    "3G_OLIB_Network_KPIs": "Cell Validity Rate(%)",
    "FDD_OLIB_Network_KPIs": "[FDD]Cell Availability[SDR_ITBBU]",
    "TDD_OLIB_Network_KPIs": "[TDD]Cell Availability[SDR_ITBBU]",
}

COLOR_MAP = {
    '2G ALL': '#2F5496', '3G ALL': '#ED7D31', '4G ALL': '#70AD47', 'FDD ALL': '#70AD47',
    '2G Regular': '#2F5496', '3G Regular': '#ED7D31', '4G Regular': '#70AD47', 'FDD Regular': '#70AD47',
    '2G Cooli': '#2F5496', '3G Cooli': '#ED7D31', '4G Cooli': '#70AD47', 'FDD Cooli': '#70AD47',
    '2G ERA': '#2F5496', '4G ERA': '#70AD47', 'FDD ERA': '#70AD47',
}

TARGET_VALUE = 0.9965
BG_COLOR = '#E8F0FE'
TITLE_COLOR = '#2F5496'
GRID_COLOR = '#C5C5C5'
MAX_LABEL_COLOR = '#FF0000'
MIN_LABEL_COLOR = '#ED7D31'

FTP_UPLOAD_PATH = "/01_RPA/LBR_Tools/KPI/RAN/ORANGE"


# ========== SSL / HTTP（连接复用 + bytearray + 截断检测） ==========
_http_local = threading.local()


def _create_ssl_socket():
    """Create one TLS connection."""
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
    """Per-thread TLS connection reuse, avoiding re-handshake per request."""
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
    """HTTP request with per-thread connection reuse, bytearray recv, truncation detection."""
    try:
        ssock = _get_thread_socket()
    except (ssl.SSLError, socket.timeout, ConnectionError, OSError) as e:
        if retry < HTTP_MAX_RETRIES:
            delay = HTTP_RETRY_DELAY * (2 ** retry) + random.uniform(0, 0.25)
            logger.warning(f"Socket connect failed (attempt {retry+1}): {e}, retry in {delay:.1f}s")
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
            logger.warning(f"Socket send failed (attempt {retry+1}): {e}, retry in {delay:.1f}s")
            time.sleep(delay)
            return _http_request(method, path, headers_extra=headers_extra, body=body, retry=retry + 1)
        raise

    # bytearray avoids O(n²) copying for large responses
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
                header_part = response_data[:pos].decode('utf-8', errors='replace')
                for line in header_part.split("\r\n"):
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

    # Truncation detection: fail fast on incomplete response
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
            logger.warning(f"Cannot parse response (attempt {retry+1}), retry in {delay:.1f}s")
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
            raise Exception(f"Failed to decompress gzip: {exc}")

    return status_line, resp_headers, header_part, resp_body


def _rsa_encrypt_pem(plaintext, public_key_b64):
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives import serialization
    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
    public_key = serialization.load_pem_public_key(pem.encode())
    encrypted = public_key.encrypt(plaintext.encode('utf-8'), asym_padding.PKCS1v15())
    return base64.b64encode(encrypted).decode('ascii')


# ========== 登录 ==========
def _login(max_retries=2):
    """执行 RAN UME 登录流程（优先使用共享缓存，避免同账户重复登录）。

    Args:
        max_retries: 登录失败时最大重试次数（含首次），默认2次
    """
    try:
        try:
            from backend.services.auth_manager import get_auth
        except ImportError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _login: exception swallowed", exc_info=True)
            from auth_manager import get_auth
        result = get_auth(HOST, PORT, *_runtime_credentials())
        source = "缓存" if result["from_cache"] else "重新登录"
        logger.info(f"[RAN_UME] 鉴权成功（来源: {source}）")
        return {"cookie": result["cookie"], "forgery_token": result["forgery_token"]}
    except Exception as e:
        logger.error(f"[RAN_UME] auth_manager 失败: {e}, using fallback cookies")
        return {"cookie": FALLBACK_COOKIE, "forgery_token": FALLBACK_FORGERY}


# ========== PM 查询 ==========
PM_REFERER = f"https://{HOST}:{PORT}/iui/pm/angularTask/dist/pmManagement.html"
PM_HISTORY_PATH = "/api/pm-analysis/v2/history"
PM_HISTORY_POLL_PATH = "/api/pm-analysis/v1/history"
PM_HISTORY_EXPORT_PATH = "/api/pm-analysis/v3/history/export"

PM_QUERY_CONFIGS = {
    "2G": {
        "templateid": "1638004472347", "base_name": "2G OLIB Network KPIs",
        "motid": "gsmPm.cell", "containvcell": 0, "indexfillingtype": "zeroDenominator",
        "nfctid": "MRNC",
        "items": ["306024", "306002", "306006", "306003", "306008", "1675910745777", "306004"],
        "uilocations": [
            {"haslogicmoc": False, "id": "bf4aa97e-54d4-4686-8fad-27481a1a8f3b", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "7017adf9-4ba6-4582-bb1c-251f2659dc5a", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "cb19a368-a1fd-4950-be1a-007c1485c424", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "50489222-477d-4071-a7f6-1f76fcdaea63", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "ac09c60f-ede4-4726-9a95-70dfd7f56ab3", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "1212567e-8919-422e-a507-a1657d0ea66a", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "3aa01f9d-6107-4120-904f-18c10816182b", "moc": "group.ran.topo", "model": "rangroup"},
        ],
    },
    "3G": {
        "templateid": "1638004472348", "base_name": "3G OLIB Network KPIs",
        "motid": "wPm.UtranCell,wPm.LogicCell", "containvcell": 1, "indexfillingtype": "default",
        "nfctid": "MRNC",
        "items": ["300857", "901593214", "901597214", "901598214", "300020", "300043", "300249",
                  "901604214", "901605214", "300532", "901410214", "901411214", "300476"],
        "uilocations": [
            {"haslogicmoc": False, "id": "5f0d1249-70ef-41d4-9775-4bc714f4cac7", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "6cafdd69-1bbe-4181-85c4-888465394892", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "6e5f401a-8a86-4a24-8b6e-18974f4cac7", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "56b55e84-9a8c-4441-bbd2-46d33cde02f5", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "f02801db-a267-4c44-bfd6-09746d93849f", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "88e9e97f-27bb-43c2-8627-8f3a8b65bf19", "moc": "group.ran.topo", "model": "rangroup"},
        ],
    },
    "TDD": {
        "templateid": "1638004472346", "base_name": "TDD OLIB Network KPIs",
        "motid": "EUtranCellTDD", "businessmotid": "EUtranCellTDD,TDDV3.EUtranCellTDD,CUEUtranCellTDDLTE",
        "containvcell": 0, "indexfillingtype": "default", "nfctid": "ITBBU,SDR,#",
        "items": ["1638004469353", "1638004469355", "1638004469356", "1638004469352", "1638004469358",
                  "1638004469359", "1638004469360", "1638004469361", "C373200029", "341089", "341088"],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [2, 2, 2, 2, 2, 2, 2, 2, 1, 0, 0],
        "itempositionbusiness": [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 2],
        "uilocations": [
            {"haslogicmoc": False, "id": "e7435e36-cdf1-4865-b8f7-98a8408a101c", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "88562cf4-fbcc-4d4f-8011-16974e755b08", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "8c9ae146-f4ae-4ef6-8adf-1205d47a6d42", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "3fab34d9-b7f0-40c3-afe1-058f58148bed", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "5ca35171-ccab-41b0-8348-5e1801d08873", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "5e384e6d-7a5d-4b6f-88f3-abc0dd4d625f", "moc": "group.ran.topo", "model": "rangroup"},
        ],
    },
    "FDD": {
        "templateid": "1638004472345", "base_name": "FDD OLIB Network KPIs",
        "motid": "EUtranCellFDD", "businessmotid": "EUtranCellFDD,FDDV3.EUtranCellFDD",
        "containvcell": 0, "indexfillingtype": "default", "nfctid": "ITBBU,SDR,#",
        "items": ["1638004469333", "1638004469340", "1638004469330", "1638004469331", "1638004469342",
                  "1638004469343", "1638004469344", "1638004469345", "C373200029", "1638004469332", "1638004469785"],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [2, 2, 2, 2, 2, 2, 2, 2, 1, 2, 2],
        "itempositionbusiness": [0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0],
        "uilocations": [
            {"haslogicmoc": False, "id": "e7435e36-cdf1-4865-b8f7-98a8408a101c", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "88562cf4-fbcc-4d4f-8011-16974e755b08", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "8c9ae146-f4ae-4ef6-8adf-1205d47a6d42", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "3fab34d9-b7f0-40c3-afe1-058f58148bed", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "5ca35171-ccab-41b0-8348-5e1801d08873", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "5e384e6d-7a5d-4b6f-88f3-abc0dd4d625f", "moc": "group.ran.topo", "model": "rangroup"},
        ],
    },
}

# ========== 外部化配置：PM 查询模板（Settings 页面可编辑的 ran_ume_config.json） ==========
# 优先级：环境变量 > 配置文件 > 内置默认。items/uilocations 逗号串 → 列表/对象。
if _RAN_UME_CONF and isinstance(_RAN_UME_CONF.get("query_configs"), list):
    _rebuilt_pm = {}
    for _row in _RAN_UME_CONF["query_configs"]:
        _tech = str(_row.get("tech", "")).strip()
        if not _tech:
            continue
        _items = [x.strip() for x in str(_row.get("items", "")).split(",") if x.strip()]
        _uploc = [{"haslogicmoc": False, "id": u.strip(), "moc": "group.ran.topo", "model": "rangroup"}
                  for u in str(_row.get("uilocations", "")).split(",") if u.strip()]
        _base = PM_QUERY_CONFIGS.get(_tech, {})  # 内置默认兜底（含 itempositionbusiness）

        def _pm_ints(v):
            if isinstance(v, (list, tuple)):
                return [int(x) for x in v]
            return [int(x) for x in str(v or "").split(",") if x.strip()]

        _q = {
            "templateid": str(_row.get("templateid") or _base.get("templateid", "")),
            "base_name": str(_row.get("templatename", _row.get("base_name", "")) or _base.get("base_name", "")),
            "motid": str(_row.get("motid") or _base.get("motid", "")),
            "nfctid": str(_row.get("nfctid") or _base.get("nfctid", "")),
            "containvcell": int(_row.get("containvcell", _base.get("containvcell", 0)) or 0),
            "indexfillingtype": str(_row.get("indexfillingtype") or _base.get("indexfillingtype", "default")),
            "items": _items,
            "uilocations": _uploc,
        }
        # FDD/TDD 4G/5G 混合选择必须携带 itempositionbusiness（及位置数组），否则 UME 返回 0001610001
        for _pf in ("itemsposition", "itemsposition1", "itempositionbusiness"):
            _pv = _pm_ints(_row.get(_pf)) or _base.get(_pf)
            if _pv:
                _q[_pf] = _pv
        if _row.get("businessmotid") or _base.get("businessmotid"):
            _q["businessmotid"] = str(_row.get("businessmotid") or _base["businessmotid"])
        _rebuilt_pm[_tech] = _q
    if _rebuilt_pm:
        PM_QUERY_CONFIGS = _rebuilt_pm
        logging.getLogger("ran_ume_service").info(
            f"[RAN] ran_ume_config.json 已加载 PM 模板: {list(PM_QUERY_CONFIGS.keys())}")


def _pm_auth_headers(cookie, forgery_token):
    headers = (
        f"Content-Type: application/json; charset=UTF-8\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Encoding: gzip, deflate, br\r\n"
        f"Cookie: {cookie}\r\n"
        f"Referer: {PM_REFERER}\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
    )
    if forgery_token:
        headers += f"forgerydefense: {forgery_token}\r\n"
    return headers


def _build_pm_payload(network_type, groupbygroup=True):
    cfg = PM_QUERY_CONFIGS.get(network_type)
    if not cfg:
        raise ValueError(f"Unsupported: {network_type}")

    now = datetime.now(timezone.utc)
    end_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    start_iso = (now - timedelta(days=RAN_UME_DAYS_BACK)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    suffix = "Group" if groupbygroup else "NW"
    templatename = f"{cfg['base_name']}{suffix}"
    items = cfg["items"]
    item_count = len(items)

    payload = {
        "arraycounterinfos": [], "containvcell": cfg["containvcell"],
        "datatype": 0, "displaymode": 0, "favoriteconditionname": templatename,
        "filterlayer": "group", "firstDayOfWeek": 7, "gr": "86400",
        "groupattributetype": 0, "groupbygroup": groupbygroup, "groupbyplmn": False,
        "grouplayer": "all", "grouptype": 0, "hidehistorystopbutton": True,
        "indexfillingtype": cfg["indexfillingtype"], "inexistenceres": False,
        "iswireless": True, "items": items,
        "itemsposition": cfg.get("itemsposition", [0] * item_count),
        "itemsposition1": cfg.get("itemsposition1", [0] * item_count),
        "motid": cfg["motid"], "needdeployfilter": False, "nfctid": cfg["nfctid"],
        "opencustomizehistoryexport": False, "opentemplatecustomcolumn": False,
        "plmnpdfdisplaymode": False, "queryallbusiness": False,
        "resfilterattribute": "", "reslocation": [], "showbusinesscolumn": False,
        "showintegrity": False, "straightquery": False,
        "templateid": cfg["templateid"], "templatename": templatename,
        "templatetype": 0, "thresholdinfos": [],
        "timeinfo": {"mode": 1, "start": start_iso, "end": end_iso, "relative": -1},
        "uilocations": cfg["uilocations"], "versiondatacompare": False,
    }

    if "businessmotid" in cfg:
        payload["businessmotid"] = cfg["businessmotid"]
        payload["businessfilterscope"] = []
        payload["groupbusinessids"] = []
    if "itempositionbusiness" in cfg:
        payload["itempositionbusiness"] = cfg["itempositionbusiness"]

    return payload


def _run_single_pm_query(cookie, forgery_token, cfg):
    """执行单个 PM 查询 + 导出"""
    network_type = cfg["network_type"]
    suffix = cfg["suffix"]
    groupbygroup = cfg["groupbygroup"]
    file_suffix = "Region" if suffix == "Group" else suffix

    logger.info(f"[PM] Starting query [{network_type}/{suffix}]")
    payload = _build_pm_payload(network_type, groupbygroup)
    body = json.dumps(payload, ensure_ascii=False)
    headers = _pm_auth_headers(cookie, forgery_token)

    status, hdrs, raw_hdrs, resp_body = _http_request("POST", PM_HISTORY_PATH, headers_extra=headers, body=body.encode('utf-8'))
    if "200" not in status:
        raise Exception(f"Create PM query failed: {status}")

    data = json.loads(resp_body.decode('utf-8'))
    queryid = data.get("queryid") or data.get("id")
    if not queryid:
        raise Exception(f"No queryid: {resp_body.decode('utf-8', errors='replace')[:500]}")

    # Poll
    poll_path = f"{PM_HISTORY_POLL_PATH}?type=0&queryid={queryid}"
    poll_headers = _pm_auth_headers(cookie, forgery_token, )
    deadline = time.time() + 300
    while time.time() < deadline:
        status, hdrs, raw_hdrs, resp_body = _http_request("GET", poll_path, headers_extra=poll_headers)
        poll_data = json.loads(resp_body.decode('utf-8'))
        if poll_data.get("querystate") == 1 or poll_data.get("progress", 0) >= 100:
            break
        time.sleep(5)

    # Export
    filename = f"{network_type} OLIB Network KPIs_{file_suffix}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    export_payload = {
        "id": queryid, "filename": filename, "chartlayout": 1, "contentmode": 0,
        "customizefieldtype": "0", "exportfiletype": 1, "exportserialnumber": False,
        "exporttableheaders": False, "formatwithts": 0, "imageinfo": [],
        "itemshowtype": 0, "tableheaders": {},
    }
    export_body = json.dumps(export_payload, ensure_ascii=False)
    status, hdrs, raw_hdrs, resp_body = _http_request("POST", PM_HISTORY_EXPORT_PATH, headers_extra=headers, body=export_body.encode('utf-8'))
    if "200" not in status:
        raise Exception(f"Export failed: {status}")

    # 内存直传，不落盘
    file_key = f"{network_type} OLIB Network KPIs_{file_suffix}"
    logger.info(f"[PM] [{network_type}/{suffix}] exported: {len(resp_body)} bytes (in-memory)")
    return file_key, resp_body


# ========== DB 写入 ==========
def _read_xlsx(filepath):
    if openpyxl is None:
        raise ImportError("缺少 openpyxl")
    with open(filepath, 'rb') as f:
        file_bytes = f.read()
    return _read_xlsx_bytes(file_bytes)


def _read_xlsx_bytes(file_bytes: bytes):
    """从内存字节直接解析 xlsx。"""
    if openpyxl is None:
        raise ImportError("缺少 openpyxl")
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
    try:
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        headers = [str(col).strip() if col is not None else f"col_{i}" for i, col in enumerate(next(rows_iter))]
        data = [list(row) for row in rows_iter if not all(v is None for v in row)]
    finally:
        wb.close()
    return headers, data



def _find_latest_xlsx(pattern_prefix, search_dir=OUTPUT_DIR):
    pattern = os.path.join(search_dir, f"{pattern_prefix}*.xlsx")
    files = [f for f in glob.glob(pattern) if not os.path.basename(f).startswith("~$")]
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]



# ========== 主任务函数 ==========
def run_ran_ume_pm_sync() -> dict:
    """
    RAN UME PM 数据获取任务：
    1. 登录 RAN UME
    2. 并行查询 2G/3G/FDD/TDD × NW/Group = 8 个 PM 指标
    3. 通过 API 写入远程 ran_kpi_daily_202606.sqlite3（DB Orange）

    Returns: dict with success, tables, errors, etc.
    """
    start_time = time.time()
    result = {"success": False, "tables": {}, "errors": [], "elapsed_seconds": 0}

    try:
        # Login
        auth = _login()
        cookie = auth["cookie"]
        forgery_token = auth["forgery_token"]

        # PM configs
        pm_configs = [
            {"network_type": t, "groupbygroup": g, "suffix": s}
            for t in TECHS for g, s in [(True, "Group"), (False, "NW")]
        ]

        # Parallel queries
        logger.info(f"[RAN_UME] Starting {len(pm_configs)} PM queries...")
        exported_data = {}  # {file_key: xlsx_bytes}
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
            futures = {
                executor.submit(_run_with_cleanup, _run_single_pm_query, cookie, forgery_token, cfg): cfg
                for cfg in pm_configs
            }
            for future in as_completed(futures):
                cfg = futures[future]
                try:
                    file_key, xlsx_bytes = future.result()
                    exported_data[file_key] = xlsx_bytes
                except Exception as e:
                    err = f"[{cfg['network_type']}/{cfg['suffix']}] failed: {e}"
                    logger.error(err)
                    result["errors"].append(err)

        # 整体 401（缓存 cookie 过期）→ 清缓存重登再跑一次
        if result["errors"] and all("401" in e for e in result["errors"]):
            logger.warning("[RAN_UME] 全部 PM 查询 401（会话过期），清除缓存并重新登录后重试一次...")
            try:
                from backend.services.auth_manager import invalidate_cache, get_auth
            except ImportError:
                try:
                    from auth_manager import invalidate_cache, get_auth
                except ImportError:
                    invalidate_cache = get_auth = None
            if invalidate_cache:
                invalidate_cache(HOST, PORT)
            if get_auth:
                try:
                    r2 = get_auth(HOST, PORT, *_runtime_credentials(), force_refresh=True)
                    cookie2, forgery2 = r2["cookie"], r2["forgery_token"]
                    logger.info("[RAN_UME] 401 后重新登录成功（来源: %s）",
                                "缓存" if r2["from_cache"] else "重新登录")
                    result["errors"] = []
                    exported_data = {}
                    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
                        futures2 = {
                            executor.submit(_run_with_cleanup, _run_single_pm_query,
                                            cookie2, forgery2, cfg): cfg
                            for cfg in pm_configs
                        }
                        for future in as_completed(futures2):
                            cfg = futures2[future]
                            try:
                                file_key, xlsx_bytes = future.result()
                                exported_data[file_key] = xlsx_bytes
                            except Exception as e:
                                err = f"[{cfg['network_type']}/{cfg['suffix']}] failed: {e}"
                                logger.error(err)
                                result["errors"].append(err)
                except Exception as e:
                    logger.error(f"[RAN_UME] 401 后重新登录失败: {e}")

        # Process xlsx → API 写入远程 DB Orange (ran_kpi_daily_202606.sqlite3)
        total_imported = 0
        api_all_ok = True

        if _db_writer is None:
            logger.error("[RAN_UME] db_writer_client 不可用，无法写入远程数据库")
            result["errors"].append("db_writer_client 不可用")
            result["success"] = False
            result["total_rows"] = 0
            return result

        for tech in TECHS:
            nw_bytes = exported_data.get(f"{tech} OLIB Network KPIs_NW")
            region_bytes = exported_data.get(f"{tech} OLIB Network KPIs_Region")
            table_name = f"{tech}_OLIB_Network_KPIs"

            merged_headers = None
            merged_data = []

            if nw_bytes:
                h, d = _read_xlsx_bytes(nw_bytes)
                if "Group" not in h:
                    h.append("Group")
                    for row in d:
                        row.append("G_NW")
                else:
                    gi = h.index("Group")
                    for row in d:
                        row[gi] = "G_NW"
                merged_headers = list(h)
                merged_data.extend(d)

            if region_bytes:
                h, d = _read_xlsx_bytes(region_bytes)
                if merged_headers:
                    # 将 Region 数据按 merged_headers 顺序重排，避免列错位
                    # Region 文件列顺序可能和 NW 不同（Group 位置不同）
                    col_map = []  # merged_headers[i] 在 h 中的索引
                    for col in merged_headers:
                        col_map.append(h.index(col) if col in h else -1)
                    # 检查是否有 Region 独有的列
                    for col in h:
                        if col not in merged_headers:
                            merged_headers.append(col)
                            col_map.append(h.index(col))
                    # 重排每行数据
                    reordered = []
                    for row in d:
                        new_row = []
                        for idx in col_map:
                            if idx >= 0 and idx < len(row):
                                new_row.append(row[idx])
                            else:
                                new_row.append("")
                        reordered.append(new_row)
                    merged_data.extend(reordered)
                else:
                    merged_headers = list(h)
                    merged_data.extend(d)

            if merged_headers and merged_data:
                row_count = len(merged_data)
                result["tables"][table_name] = row_count
                total_imported += row_count

                # [API] 写入远程 DB Orange（ran_kpi_daily_202606.sqlite3）
                try:
                    str_data = [[str(v) if v is not None else None for v in row] for row in merged_data]
                    api_result = _db_writer.write_data(
                        db=DB_ORANGE_NAME,
                        table=table_name,
                        columns=merged_headers,
                        rows=str_data,
                        mode="upsert",
                        pk_columns=["Begin Time", "Group"],
                    )
                    api_rows = api_result.get("rows_written", 0)
                    if api_rows == 0:
                        # 数据已存在/已同步（upsert 后无新增行），不视为失败
                        logger.info(f"[RAN_UME][API] DB Orange {table_name}: 无新增行（数据已存在/已同步）")
                    else:
                        logger.info(f"[RAN_UME][API] DB Orange {table_name}: {api_rows} rows")
                except Exception as e:
                    logger.error(f"[RAN_UME][API] DB Orange {table_name} 写入失败: {e}")
                    api_all_ok = False

        if api_all_ok:
            logger.info("[RAN_UME][API] 远程写入全部完成")
        else:
            logger.warning("[RAN_UME][API] 部分表写入失败")
            result["errors"].append("API 写入部分失败")

        result["success"] = len(result["errors"]) == 0
        result["total_rows"] = total_imported

    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"[RAN_UME] Task failed: {e}")

    elapsed = time.time() - start_time
    result["elapsed_seconds"] = round(elapsed, 2)
    logger.info(f"[RAN_UME] PM sync done: {result.get('total_rows', 0)} rows, {elapsed:.2f}s")
    return result


# ========== Availability 报表生成 ==========
def _normalize_chart_label(name):
    if 'TDD' in name:
        return None
    name = name.replace('FDD ALL', '4G ALL')
    name = name.replace('FDD Regular', '4G Regular')
    name = name.replace('FDD Cooli', '4G Cooli')
    name = name.replace('FDD ERA', '4G ERA')
    return name


def _find_availability_column(columns, table_name):
    configured = AVAILABILITY_METRICS.get(table_name, "").strip()
    if configured and configured in columns:
        return configured
    for col in columns:
        if any(kw in col.lower() for kw in ["cell availability", "availability"]):
            return col
    return columns[0] if columns else None


def _generate_chart(df, sheet_name, output_dir):
    if pd is None or plt is None:
        return ""
    if df.empty or 'Cell Group' not in df.columns:
        return ""

    df = df.copy()
    df['Cell Group'] = df['Cell Group'].apply(_normalize_chart_label)
    df = df.dropna(subset=['Cell Group'])
    if df.empty:
        return ""

    cell_groups = sorted(df['Cell Group'].unique().tolist())
    pivot_df = df.pivot_table(index='Begin Time', columns='Cell Group', values='Cell Availability')
    dates = pivot_df.index.tolist()
    n_dates = len(dates)

    fig, ax = plt.subplots(figsize=(14, 5.5))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    for cg in cell_groups:
        values = pivot_df[cg].values
        color = COLOR_MAP.get(cg, '#333333')
        ax.plot(range(n_dates), values, color=color, linewidth=1.2, label=cg, alpha=0.85)

    ax.axhline(y=TARGET_VALUE, color='#FF0000', linestyle='--', linewidth=1.0, alpha=0.7)
    ax.text(n_dates - 1, TARGET_VALUE + 0.003, f'T:{TARGET_VALUE*100:.2f}%',
            color=MAX_LABEL_COLOR, fontsize=8, ha='right', fontweight='bold')

    # 标注全局最大值和最小值
    all_values = pivot_df.values
    if not np.all(np.isnan(all_values)):
        max_pos = np.unravel_index(np.nanargmax(all_values), all_values.shape)
        min_pos = np.unravel_index(np.nanargmin(all_values), all_values.shape)
        max_val = all_values[max_pos]
        min_val = all_values[min_pos]
        max_x = max_pos[0]   # 日期索引
        min_x = min_pos[0]   # 日期索引

        ax.annotate(f'{max_val*100:.2f}%',
                    xy=(max_x, max_val),
                    xytext=(max_x, max_val + 0.015),
                    fontsize=7.5, color=MAX_LABEL_COLOR, ha='center', fontweight='bold',
                    arrowprops=dict(arrowstyle='->', color=MAX_LABEL_COLOR, lw=0.8))

        ax.annotate(f'{min_val*100:.2f}%',
                    xy=(min_x, min_val),
                    xytext=(min_x, min_val - 0.02),
                    fontsize=7.5, color=MIN_LABEL_COLOR, ha='center', fontweight='bold',
                    arrowprops=dict(arrowstyle='->', color=MIN_LABEL_COLOR, lw=0.8))

    # Y轴：最小值动态，最大值固定102%
    y_min = max(0.60, pivot_df.min().min() - 0.03)
    ax.set_ylim(y_min, 1.02)
    ax.set_ylabel('Cell Availability', fontsize=9)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x*100:.2f}%'))
    ax.set_title(sheet_name, fontsize=13, fontweight='bold', color=TITLE_COLOR, pad=12)
    ax.grid(axis='y', linestyle='--', color=GRID_COLOR, linewidth=0.6, alpha=0.6)
    ax.legend(loc='lower center', bbox_to_anchor=(0.5, -0.18), ncol=len(cell_groups), fontsize=7.5, frameon=False)

    # 横坐标显示日期
    date_labels = []
    for d in dates:
        s = str(d)
        if 'T' in s:
            s = s.split('T')[0]
        if len(s) >= 10:
            s = s[5:]  # MM-DD
        date_labels.append(s)
    # 根据数据量控制显示的刻度数
    if n_dates > 30:
        step = max(1, n_dates // 15)
        tick_positions = list(range(0, n_dates, step))
        tick_labels = [date_labels[i] for i in tick_positions]
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, rotation=45, fontsize=7, ha='right')
    else:
        ax.set_xticks(range(n_dates))
        ax.set_xticklabels(date_labels, rotation=45, fontsize=7, ha='right')

    plt.tight_layout()

    output_path = os.path.join(output_dir, f'{sheet_name}.png')
    # 与 xlsx 相同的锁容忍：先写临时文件再替换，扛 WPS云同步/Defender/索引瞬时锁
    # 注意 savefig 按扩展名推断格式，临时文件必须仍以 .png 结尾
    _tmp = output_path + f".{os.getpid()}.tmp.png"
    _last_err = None
    for _attempt in range(46):
        try:
            fig.savefig(_tmp, dpi=150, bbox_inches='tight', facecolor=BG_COLOR, edgecolor='none')
            os.replace(_tmp, output_path)
            _last_err = None
            break
        except (PermissionError, OSError) as _e:
            _last_err = _e
            time.sleep(2.0)
    if _last_err is not None:
        try:
            fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor=BG_COLOR, edgecolor='none')
        except Exception as _e2:
            logging.getLogger(__name__).warning(
                "[SILENT-EXCEPT] _generate_chart savefig: exception swallowed", exc_info=True)
            plt.close(fig)
            return None
    plt.close(fig)
    return output_path


def _read_remote_daily_tables() -> dict:
    """通过 db_writer_api 读取远程 ran_kpi_daily.sqlite3 的 4 张 OLIB 表。

    返回 {table_name: DataFrame}；任一表读取失败抛异常，由调用方回退本地库。
    远程库同时包含新旧两套 Group 命名的全量历史（旧导入路径 05-08~07-27、
    network_kpi_sync 07-28 起），报表曲线可同时展示两套区域口径。
    """
    base = f"http://{get_api_host()}:{API_PORT}"
    result = {}
    for table in TECH_MAP:
        payload = {"db": DB_DAILY_NAME, "table": table, "limit": 300000}
        req = urllib.request.Request(base + "/api/read",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read().decode())
        cols = d.get("columns") or []
        if not cols:
            raise Exception(f"{table}: 远程读取未返回列信息")
        result[table] = pd.DataFrame(d.get("rows") or [], columns=cols)
    return result


def _refresh_local_daily_db(table_dfs: dict):
    """远程读取成功后覆盖更新本地 ran_kpi_daily.sqlite3，保持兜底副本最新。

    先写临时文件再原子替换，避免报表写到一半被读/进程中断损坏本地库。
    """
    try:
        tmp_path = str(DB_PATH) + ".tmp"
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        # 注意：sqlite3 连接必须显式 close（with 块只提交不关闭），
        # 否则 Windows 上 tmp 文件被占用导致 os.replace 失败
        conn = sqlite3.connect(tmp_path, timeout=60)
        try:
            for table, df in table_dfs.items():
                df.to_sql(table, conn, if_exists="replace", index=False)
        finally:
            conn.close()
        # 目标文件可能被其他进程短暂占用，重试几次
        last_err = None
        for _ in range(5):
            try:
                os.replace(tmp_path, str(DB_PATH))
                last_err = None
                break
            except OSError as e:
                last_err = e
                time.sleep(1)
        if last_err:
            raise last_err
        logger.info(f"[Availability] 本地兜底库已同步远程: {DB_PATH}")
    except Exception as e:
        logger.warning(f"[Availability] 本地库同步失败（不影响本次报表）: {e}")


def run_availability_report() -> dict:
    """
    生成 Daily Availability KPI 报表：
    1. 从 ran_kpi_daily.sqlite3 读取 PM 数据
    2. 生成 Excel + 图表 PNG
    3. 上传图片到 FTP

    Returns: dict
    """
    start_time = time.time()
    result = {"success": False, "errors": [], "generated_files": [], "elapsed_seconds": 0}

    if pd is None:
        result["errors"].append("缺少 pandas 依赖")
        return result

    try:
        # 优先读远程库（network_kpi_sync 写入的唯一真相源），失败回退本地兜底副本
        table_dfs = None
        try:
            table_dfs = _read_remote_daily_tables()
            logger.info(f"[Availability] 数据源: 远程库 {DB_DAILY_NAME} @ {get_api_host()}:{API_PORT}")
            _refresh_local_daily_db(table_dfs)
        except Exception as e:
            logger.warning(f"[Availability] 远程库读取失败: {e}，回退本地库")

        if table_dfs is None:
            db_path = str(DB_PATH)
            if not os.path.exists(db_path):
                result["errors"].append(f"远程库不可读且本地数据库不存在: {db_path}")
                return result
            with get_raw_connection(db_path) as conn:
                tables = [t for t in list_table_names(conn) if t in TECH_MAP]
                table_dfs = {}
                for table in tables:
                    table_dfs[table] = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
                conn.close()

            if not table_dfs:
                result["errors"].append("数据库中未找到 OLIB Network KPIs 表")
                return result

        # Build availability data（远程/本地两条路径共用）
        sheet_rows = {sheet: [] for sheet in TARGET_SHEETS}
        for table_name, df in table_dfs.items():
            tech = TECH_MAP[table_name]
            if "Begin Time" not in df.columns or "Group" not in df.columns:
                continue
            avail_col = _find_availability_column(list(df.columns), table_name)
            if not avail_col:
                continue

            df = df.copy()
            # [:10] 同时兼容 ISO(T分隔)与空格分隔两种时间格式，统一取日期部分
            df['Begin Time'] = df['Begin Time'].apply(lambda x: str(x)[:10] if x else "")
            df[avail_col] = pd.to_numeric(df[avail_col], errors='coerce')
            if not df[avail_col].dropna().empty and df[avail_col].dropna().max() > 1:
                df[avail_col] = df[avail_col] / 100.0

            for sheet_name, cfg in SHEET_CONFIG.items():
                if tech not in cfg['tech_groups']:
                    continue
                mask = df['Group'].apply(
                    lambda x: any(re.search(p, str(x), re.IGNORECASE) for p in cfg['patterns']) if x else False
                )
                sub = df[mask].copy()
                if sub.empty:
                    continue
                agg = sub.groupby('Begin Time')[avail_col].mean().reset_index()
                agg['Cell Group'] = cfg['tech_groups'][tech]
                agg['Cell Availability'] = agg[avail_col]
                sheet_rows[sheet_name].append(agg[['Begin Time', 'Cell Group', 'Cell Availability']])

        # Write Excel（原子写：先写临时文件，再 os.replace，重试扛文件锁）
        output_excel = str(AVAILABILITY_OUTPUT_DIR / "Daily_Aailability_KPI.xlsx")
        try:
            with atomic_excel_writer(output_excel) as writer:
                for sheet_name in TARGET_SHEETS:
                    frames = sheet_rows.get(sheet_name, [])
                    if frames:
                        df = pd.concat(frames, ignore_index=True).sort_values(['Cell Group', 'Begin Time'])
                    else:
                        df = pd.DataFrame(columns=['Begin Time', 'Cell Group', 'Cell Availability'])
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
        except AtomicReplaceFallback as fb:
            logger.warning(f"[Availability] 文件被锁，数据已保存到备用路径: {fb.fallback_path}")
            result["errors"].append(f"文件被锁，数据已保存到: {fb.fallback_path}")
            output_excel = fb.fallback_path
        result["generated_files"].append(output_excel)

        # Generate charts
        output_dir = str(AVAILABILITY_OUTPUT_DIR)
        generated_images = []
        for sheet_name in TARGET_SHEETS:
            frames = sheet_rows.get(sheet_name, [])
            if frames:
                df = pd.concat(frames, ignore_index=True).sort_values(['Cell Group', 'Begin Time'])
            else:
                df = pd.DataFrame()
            img_path = _generate_chart(df, sheet_name, output_dir)
            if img_path:
                generated_images.append(img_path)
                result["generated_files"].append(img_path)

        # Upload images to FTP
        for img_path in generated_images:
            try:
                ftp = FTP()
                ftp.connect(get_ftp_host(), 21, timeout=30)
                ftp.encoding = "utf-8"
                ftp.login(FTP_USER, FTP_PASS)
                parts = FTP_UPLOAD_PATH.strip('/').split('/')
                current = ''
                for part in parts:
                    current += f'/{part}'
                    try:
                        ftp.cwd(current)
                    except error_perm:
                        logging.getLogger(__name__).warning("[SILENT-EXCEPT] run_availability_report: exception swallowed", exc_info=True)
                        ftp.mkd(current)
                        ftp.cwd(current)
                fname = os.path.basename(img_path)
                with open(img_path, 'rb') as f:
                    ftp.storbinary(f'STOR {fname}', f)
                ftp.quit()
            except Exception as e:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] run_availability_report: exception swallowed", exc_info=True)
                result["errors"].append(f"FTP upload {os.path.basename(img_path)} failed: {e}")

        result["success"] = len(result["errors"]) == 0

    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"[Availability] Report failed: {e}")

    elapsed = time.time() - start_time
    result["elapsed_seconds"] = round(elapsed, 2)
    return result


def run_ran_ume_full_task() -> dict:
    """
    完整的 RAN UME 任务：PM 数据获取 + Availability 报表生成
    """
    start_time = time.time()
    result = {"success": False, "steps": {}, "errors": [], "elapsed_seconds": 0}

    # 清理上次异常退出残留的临时文件
    cleanup_stale_tmp_files(RAN_UME_DATA_DIR)

    # Step 1: PM data fetch
    logger.info("[RAN_UME] Step 1: PM data fetch...")
    pm_result = run_ran_ume_pm_sync()
    result["steps"]["pm_sync"] = pm_result
    if not pm_result["success"]:
        result["errors"].extend(pm_result.get("errors", []))

    # Step 2: Availability report
    logger.info("[RAN_UME] Step 2: Availability report generation...")
    avail_result = run_availability_report()
    result["steps"]["availability"] = avail_result
    if not avail_result["success"]:
        result["errors"].extend(avail_result.get("errors", []))

    result["success"] = pm_result["success"] and avail_result["success"]

    elapsed = time.time() - start_time
    result["elapsed_seconds"] = round(elapsed, 2)
    logger.info(f"[RAN_UME] Full task done: {elapsed:.2f}s, success={result['success']}")
    return result


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:ran_ume_service>: exception swallowed", exc_info=True)
        pass
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')

    t0 = time.time()
    result = run_ran_ume_full_task()
    print(f"\nRAN UME 任务结果: {'成功' if result['success'] else '失败'}")
    print(f"步骤: {list(result['steps'].keys())}")
    if result['errors']:
        print(f"错误: {result['errors']}")
    print(f"耗时: {result['elapsed_seconds']}s")