# -*- coding: utf-8 -*-
"""
RAN UME Network KPI (Zeenshan) 每日同步脚本

功能：
1. 登录 ZTE RAN UME 网管系统，获取鉴权 Cookie 与 forgery token。
2. 根据 Payload.txt 中的配置，批量创建 Network KPI 历史指标查询任务：
   - 技术类型：2G(GSM)、3G(UMTS)、FDD(4G)、TDD(4G)
   - 聚合层级：Group（groupbygroup=true）、NW（groupbygroup=false）
   - 时间粒度：1Day（86400 秒）
3. 轮询查询进度直到完成，导出为 Excel 文件。
4. 清理同类型历史 xlsx 文件，仅保留最新一份。

文件命名规则（来自 Payload.txt）：
- templatename 中的空格替换为下划线
- grouplayer "all" + groupbygroup=true  → "Group"
- grouplayer "all" + groupbygroup=false → "NW"
- gr "86400"  → "1Day"
- gr "2592000" → "1Month"
- 最终格式：{templatename}_{Group|NW}_{1Day|1Month}_{timestamp}.xlsx
"""

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
import sys
import time
import warnings
import sqlite3
import subprocess
import threading
import random
import openpyxl
from ftplib import FTP, error_perm
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

# 并行查询线程数
MAX_PARALLEL_WORKERS = int(os.environ.get("NW_KPI_PARALLEL_WORKERS", "4"))

# ========== 重试 / 超时配置（环境变量可调） ==========
HTTP_MAX_RETRIES = max(0, int(os.environ.get("NW_KPI_HTTP_MAX_RETRIES", "3")))
HTTP_RETRY_DELAY = float(os.environ.get("NW_KPI_HTTP_RETRY_DELAY", "1"))
HTTP_CONNECT_TIMEOUT = float(os.environ.get("NW_KPI_CONNECT_TIMEOUT", "15"))
HTTP_READ_TIMEOUT = float(os.environ.get("NW_KPI_READ_TIMEOUT", "90"))

# 时间范围：今天之前的 367 天（覆盖一年）
DAYS_BACK = int(os.environ.get("NW_KPI_DAYS_BACK", "367"))

# PM 接口路径
HISTORY_PATH = "/api/pm-analysis/v2/history"
HISTORY_POLL_PATH = "/api/pm-analysis/v1/history"
HISTORY_EXPORT_PATH = "/api/pm-analysis/v3/history/export"
HISTORY_REFERER = f"https://{HOST}:{PORT}/iui/pm/angularTask/dist/pmManagement.html"

# 数据库配置（参考 ran_daily_kpi.py）
DB_NAME = "ran_kpi_daily.sqlite3"
DB_PATH = os.path.join(SCRIPT_DIR, DB_NAME)

# FTP 上传配置（目标数据库）
FTP_HOST = "192.168.100.19"
FTP_USER = "ZTEEMS"
FTP_PASS = "DX"
FTP_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI/RAN"

# 远程写入 API 配置
try:
    from backend.services.db_writer_client import DbWriterClient
except ImportError:
    from db_writer_client import DbWriterClient
try:
    _db_writer = DbWriterClient()
except Exception:
    _db_writer = None
    print("[WARNING] db_writer_client init failed, fallback to FTP")

# 备用鉴权信息
FALLBACK_COOKIE = (
    "X-Rm-Data-Version-zenap=1773367620002_0_0_0_0_0_0_0_0; "
    "Z-AUTH-CODE-28001=1154983705_f188b025b7b64878ae0f4511e90ab1a2; "
    "x-dexmesh-user-28001=D86935A99B38A02CDAEA05C225E9303A21FA22B872499884D7B2A1E26A5645FE; "
    "forgerydefense-28001=cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"
)
FALLBACK_FORGERY = "cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"

# gr 显示名称替换规则
GR_RENAME = {
    "2592000": "1Month",
    "86400": "1Day",
}

# ============================================================
# KPI 查询配置（从 Payload.txt 提取）
# ============================================================
# 21 个 rangroup uilocations（所有技术共用）
UILOCATIONS = [
    {"haslogicmoc": False, "id": "129a8734-d9ae-47be-af3c-b65067076afa", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "e0e043f8-3982-44d4-956e-4e3d48e4064f", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "8f437c12-329e-4271-b6b0-e6ed589d62fb", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "84b3c1f0-0271-406a-9352-df986890f640", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "384666b0-a6f2-4fd9-9d62-ad78ee30e269", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "c1f9b830-37c9-408b-bd65-85798c408098", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "be624030-7288-4ef3-9a25-64995b4e0c55", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "4d2720da-d256-4c37-a853-6e2f91a845db", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "f649683c-3885-4a10-8a90-c3f7c3f635eb", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "2d3dbb66-e0b4-4b48-9e41-9282931fc7da", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "3bee4b0d-d4f6-4eda-8c04-d316601275eb", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "0552422a-6612-42d9-8de9-a83d0393c50f", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "faec4465-b7be-4820-add1-15d337b8265e", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "8d44493a-f337-4a5a-8d46-2d9c899ea7c7", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "4272f8e8-4624-4514-a580-dc031d8ffda6", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "c02ef87d-18a3-4960-8166-8a540f7fc751", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "2f897e12-cda6-43d2-9b84-3ea6ebf09ca7", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "a213130a-cdd9-45a5-9c3c-ff9e1a97cdfd", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "ba7fadd5-1cd3-4494-886b-601e48f973f6", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "a5916579-4f81-483c-a1e5-ef9117aea2cf", "moc": "group.ran.topo", "model": "rangroup"},
    {"haslogicmoc": False, "id": "aeafb27d-a14f-4bca-92d9-6022ad427f27", "moc": "group.ran.topo", "model": "rangroup"},
]

NW_KPI_QUERY_CONFIGS = {
    "2G": {
        "templateid": "1638004472347",
        "templatename": "2G OLIB Network KPIs",
        "motid": "gsmPm.cell",
        "nfctid": "MRNC",
        "containvcell": 0,
        "indexfillingtype": "zeroDenominator",
        "showbusinesscolumn": False,
        "versiondatacompare": False,
        "items": ["306024", "306002", "306006", "306003", "306008", "1675910745777", "306004"],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [0, 0, 0, 0, 0, 0, 0],
    },
    "3G": {
        "templateid": "1638004472348",
        "templatename": "3G OLIB Network KPIs",
        "motid": "wPm.UtranCell,wPm.LogicCell",
        "nfctid": "MRNC",
        "containvcell": 1,
        "indexfillingtype": "default",
        "showbusinesscolumn": False,
        "versiondatacompare": False,
        "items": ["300857", "901593214", "901597214", "901598214", "300020", "300043", "300249", "901604214", "901605214", "300532", "901410214", "901411214", "300476"],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0],
        "itemsposition1": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    },
    "FDD": {
        "templateid": "1638004472345",
        "templatename": "FDD OLIB Network KPIs",
        "motid": "EUtranCellFDD",
        "businessmotid": "EUtranCellFDD,FDDV3.EUtranCellFDD",
        "nfctid": "ITBBU,SDR,#",
        "containvcell": 0,
        "indexfillingtype": "default",
        "showbusinesscolumn": False,
        "items": ["1638004469333", "1638004469340", "1638004469330", "1638004469331", "1638004469342", "1638004469343", "1638004469344", "1638004469345", "C373200029", "1638004469332", "1638004469785"],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [2, 2, 2, 2, 2, 2, 2, 2, 1, 2, 2],
        "itempositionbusiness": [0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0],
    },
    "TDD": {
        "templateid": "1638004472346",
        "templatename": "TDD OLIB Network KPIs",
        "motid": "EUtranCellTDD",
        "businessmotid": "EUtranCellTDD,TDDV3.EUtranCellTDD,CUEUtranCellTDDLTE",
        "nfctid": "ITBBU,SDR,#",
        "containvcell": 0,
        "indexfillingtype": "default",
        "showbusinesscolumn": False,
        "items": ["1638004469353", "1638004469355", "1638004469356", "1638004469352", "1638004469358", "1638004469359", "1638004469360", "1638004469361", "C373200029", "341089", "341088"],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [2, 2, 2, 2, 2, 2, 2, 2, 1, 0, 0],
        "itempositionbusiness": [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 2],
    },
}

# 任务配置：4 技术 × 2 模式（Group/NW）= 8 个查询
NW_KPI_TASKS = [
    {"tech": "2G",  "gr": "86400", "groupbygroup": True,  "layer": "Group"},
    {"tech": "2G",  "gr": "86400", "groupbygroup": False, "layer": "NW"},
    {"tech": "3G",  "gr": "86400", "groupbygroup": True,  "layer": "Group"},
    {"tech": "3G",  "gr": "86400", "groupbygroup": False, "layer": "NW"},
    {"tech": "FDD", "gr": "86400", "groupbygroup": True,  "layer": "Group"},
    {"tech": "FDD", "gr": "86400", "groupbygroup": False, "layer": "NW"},
    {"tech": "TDD", "gr": "86400", "groupbygroup": True,  "layer": "Group"},
    {"tech": "TDD", "gr": "86400", "groupbygroup": False, "layer": "NW"},
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
            from auth_manager import get_auth
        result = get_auth(HOST, PORT, USERNAME, PASSWORD)
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
    max_retries: int = 4,
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


def build_nw_kpi_payload(tech: str, gr_seconds: str, groupbygroup: bool,
                         start_iso: str | None = None, end_iso: str | None = None) -> dict:
    """构造 Network KPI 历史指标查询 Payload，字段顺序与 Payload.txt 一致。"""
    cfg = NW_KPI_QUERY_CONFIGS.get(tech)
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

    # 按 Payload.txt 字段顺序构造
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
        "showbusinesscolumn": cfg["showbusinesscolumn"],
        "showintegrity": False,
        "straightquery": False,
        "templatename": cfg["templatename"],
        "templateid": cfg["templateid"],
    }

    # 2G/3G 有 versiondatacompare，FDD/TDD 没有
    if "versiondatacompare" in cfg:
        payload["versiondatacompare"] = cfg["versiondatacompare"]

    payload["needdeployfilter"] = False
    payload["timeinfo"] = timeinfo
    payload["indexfillingtype"] = cfg["indexfillingtype"]

    # FDD/TDD 有 businessmotid 和 itempositionbusiness
    if "businessmotid" in cfg:
        payload["businessmotid"] = cfg["businessmotid"]
    if "itempositionbusiness" in cfg:
        payload["itempositionbusiness"] = cfg["itempositionbusiness"]

    payload["thresholdinfos"] = []
    payload["templatetype"] = 0
    payload["filterlayer"] = "group"
    payload["grouplayer"] = "all"
    payload["containvcell"] = cfg["containvcell"]
    payload["resfilterattribute"] = ""
    payload["uilocations"] = UILOCATIONS
    payload["reslocation"] = []
    payload["inexistenceres"] = False

    if "businessmotid" in cfg:
        payload["groupbusinessids"] = []
        payload["businessfilterscope"] = []

    payload["firstDayOfWeek"] = 7
    payload["iswireless"] = True
    payload["hidehistorystopbutton"] = True
    payload["opencustomizehistoryexport"] = False
    payload["opentemplatecustomcolumn"] = False

    return payload


def create_history_query(cookie: str, forgery_token: str, payload: dict) -> str:
    """创建 KPI 历史指标查询任务，返回 queryid。"""
    print(f"[KPI] Creating: {payload.get('templatename')} / groupbygroup={payload.get('groupbygroup')} / gr={payload.get('gr')}")
    body = json.dumps(payload, ensure_ascii=False)
    headers = _auth_headers(cookie, forgery_token)

    try:
        status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
            "POST", HISTORY_PATH, headers_extra=headers, body=body.encode('utf-8'), max_retries=3,
        )
    except Exception as e:
        print(f"[KPI] Create query failed after retries: {e}")
        raise

    print(f"[KPI] Create query status: {status}")
    resp_text = resp_body.decode('utf-8', errors='replace')

    if "200" not in status:
        print(f"[KPI] Request headers:\n{headers}")
        print(f"[KPI] Request body preview:\n{body[:1000]}")
        print(f"[KPI] Response: {resp_text[:500]}")
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
    print(f"[KPI] Polling progress (timeout={timeout}s, interval={interval}s)...")
    path = f"{HISTORY_POLL_PATH}?type=0&queryid={queryid}"
    headers = _auth_headers(cookie, forgery_token, extra={"Accept": "application/json, text/plain, */*"})

    deadline = time.time() + timeout
    while time.time() < deadline:
        status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
            "GET", path, headers_extra=headers, max_retries=3,
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
                   output_path: str | None = None) -> str:
    """导出并下载 KPI 历史指标结果，返回保存的文件路径。"""
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

    print(f"[KPI] Exporting: {filename}")
    body = json.dumps(payload, ensure_ascii=False)
    headers = _auth_headers(cookie, forgery_token)

    status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
        "POST", HISTORY_EXPORT_PATH, headers_extra=headers, body=body.encode('utf-8'), max_retries=3,
    )
    print(f"[KPI] Export status: {status}")

    if "200" not in status:
        raise Exception(f"Export KPI history failed: {status}")

    if not output_path:
        output_path = os.path.join(OUTPUT_DIR, f"{filename}.xlsx")

    with open(output_path, "wb") as f:
        f.write(resp_body)
    print(f"[KPI] Saved to: {output_path} ({len(resp_body)} bytes)")
    return output_path


# ============================================================
# 文件命名
# ============================================================
def build_filename(templatename: str, layer: str, gr_seconds: str) -> str:
    """按规则构造 KPI 导出文件名前缀（不含时间戳和扩展名）。
    - templatename 中的空格替换为下划线
    - layer: Group / NW
    - gr: 86400 -> 1Day, 2592000 -> 1Month
    """
    name_clean = templatename.replace(" ", "_")
    gr_label = GR_RENAME.get(gr_seconds, gr_seconds)
    return f"{name_clean}_{layer}_{gr_label}"


# ============================================================
# 旧文件清理
# ============================================================
def cleanup_old_exports(file_prefix: str) -> int:
    """删除同前缀的历史 xlsx 文件（保留最新一份由调用方在导出后处理）。
    实际策略：导出新文件后，删除所有同前缀的旧文件（不含当前文件）。
    """
    pattern = os.path.join(OUTPUT_DIR, f"{file_prefix}_*.xlsx")
    files = [f for f in glob.glob(pattern) if not os.path.basename(f).startswith("~$")]
    # 按修改时间降序，保留最新一份
    files.sort(key=os.path.getmtime, reverse=True)

    deleted = 0
    for f in files[1:]:  # 跳过最新的
        try:
            os.remove(f)
            print(f"[CLEANUP] deleted old: {os.path.basename(f)}")
            deleted += 1
        except Exception as e:
            print(f"[CLEANUP] failed to delete {os.path.basename(f)}: {e}")
    return deleted


# ============================================================
# 数据库导入（参考 ran_daily_kpi.py）
# ============================================================
def find_latest_xlsx(prefix):
    """在 Downloads 目录中查找匹配前缀的最新 xlsx 文件。"""
    pattern = os.path.join(OUTPUT_DIR, f"{prefix}*.xlsx")
    files = [f for f in glob.glob(pattern) if not os.path.basename(f).startswith("~$")]
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def read_xlsx(filepath):
    """读取 xlsx 文件，返回 (headers, data)。流式读取，先读入内存再解析。"""
    with open(filepath, 'rb') as f:
        file_bytes = f.read()

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    try:
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        headers = [str(col).strip() if col is not None else f"col_{i}"
                   for i, col in enumerate(next(rows_iter))]
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
    """将数据写入 SQLite 数据库。
    以 'Begin Time' 和 'Group' 列为联合主键，使用 INSERT OR REPLACE 实现更新/替换。
    """
    # 打开/初始化数据库时若遇到文件锁(SMB 读锁/云同步/索引服务等)会直接报
    # "readonly database"，这里加重试 + 长超时(busy_timeout)，让锁释放窗口内的
    # 写入能自动穿过。连接重试窗口拉到 ~50s 以抗间歇性独占锁。
    last_err = None
    for _attempt in range(1, 11):
        try:
            conn = sqlite3.connect(db_path, timeout=60)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=OFF")
            cursor.execute("PRAGMA cache_size=-64000")
            cursor.execute("PRAGMA busy_timeout=60000")
            break
        except sqlite3.OperationalError as e:
            last_err = e
            try:
                conn.close()
            except Exception:
                pass
            if _attempt < 10:
                print(f"  [DB] 打开/初始化失败（可能文件被锁），5s 后重试 ({_attempt}/10): {e}")
                time.sleep(5)
    else:
        raise last_err or sqlite3.OperationalError("write_to_db connect failed")

    if "Begin Time" not in headers or "Group" not in headers:
        print(f"  [DB] 表 {table_name} 缺少 'Begin Time' 或 'Group' 列，跳过。")
        conn.close()
        return 0

    # 检查表是否已存在
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    table_exists = cursor.fetchone() is not None

    if not table_exists:
        # 新建表
        create_sql = (
            f'CREATE TABLE "{table_name}" (\n'
            f'  "Begin Time" TEXT NOT NULL,\n'
            f'  "Group" TEXT NOT NULL,\n'
            f'  PRIMARY KEY ("Begin Time", "Group")\n'
            f')'
        )
        cursor.execute(create_sql)
        for h in headers:
            if h in ("Begin Time", "Group"):
                continue
            safe_col = h.replace('"', '""')
            try:
                cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{safe_col}" TEXT')
            except sqlite3.OperationalError:
                pass
    else:
        # 表已存在，检查并添加缺少的列
        cursor.execute(f'PRAGMA table_info("{table_name}")')
        existing_cols = {row[1] for row in cursor.fetchall()}
        for h in headers:
            if h not in existing_cols:
                safe_col = h.replace('"', '""')
                try:
                    cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{safe_col}" TEXT')
                except sqlite3.OperationalError:
                    pass

    # INSERT OR REPLACE
    quoted_headers = [f'"{h.replace(chr(34), chr(34)+chr(34))}"' for h in headers]
    placeholders = ", ".join(["?"] * len(headers))
    insert_sql = (
        f'INSERT OR REPLACE INTO "{table_name}" '
        f'({", ".join(quoted_headers)}) VALUES ({placeholders})'
    )

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

        if len(batch) >= 2000:
            cursor.executemany(insert_sql, batch)
            batch.clear()

    if batch:
        cursor.executemany(insert_sql, batch)

    conn.commit()
    conn.close()
    return row_count


def upload_to_ftp(local_path, remote_dir, filename, max_retries=2):
    """上传文件到 FTP 服务器（带重试机制）。"""
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
                print(f"  [WARNING] 目录不匹配，期望 {expected}，实际 {current_dir}")
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


def import_to_database():
    """将导出的 NW 和 Group xlsx 文件导入 SQLite 数据库。
    参考 ran_daily_kpi.py 的处理逻辑：
    - 对 NW 文件增加 Group 列（值为 {tech}_NW）和 Source File 列
    - 对 Group 文件增加 Source File 列
    - 合并 NW 和 Group 数据后写入表 {tech}_OLIB_Network_KPIs
    - 以 (Begin Time, Group) 为联合主键，INSERT OR REPLACE
    """
    print("\n" + "=" * 70)
    print("[DB] 开始导入数据库")
    print(f"[DB] 数据库路径: {DB_PATH}")
    print("=" * 70)

    total_imported = 0
    files_to_delete = []

    for tech in ["2G", "3G", "FDD", "TDD"]:
        # 文件前缀（与 build_filename 生成的一致，空格已替换为下划线）
        nw_prefix = f"{tech}_OLIB_Network_KPIs_NW_1Day"
        group_prefix = f"{tech}_OLIB_Network_KPIs_Group_1Day"
        table_name = f"{tech}_OLIB_Network_KPIs"

        nw_file = find_latest_xlsx(nw_prefix)
        group_file = find_latest_xlsx(group_prefix)

        print(f"\n[{tech}]")

        # ---- 处理 _NW 文件 ----
        nw_headers = None
        nw_data = None
        nw_source = f"{tech} OLIB Network KPIs_NW"
        if nw_file:
            files_to_delete.append(nw_file)
            print(f"  _NW: {os.path.basename(nw_file)}")

            # NW 数据的 Group 值
            group_value = f"{tech}_NW"
            print(f"  _NW Group: {group_value}")

            nw_headers, nw_data = read_xlsx(nw_file)
            print(f"  _NW: {len(nw_data)} rows, {len(nw_headers)} cols")

            # 增加 "Group" 列
            if "Group" not in nw_headers:
                nw_headers.append("Group")
                for row in nw_data:
                    row.append(group_value)
            else:
                group_idx = nw_headers.index("Group")
                for row in nw_data:
                    row[group_idx] = group_value

            # 增加 "Source File" 列
            if "Source File" not in nw_headers:
                nw_headers.append("Source File")
                for row in nw_data:
                    row.append(nw_source)
            else:
                sf_idx = nw_headers.index("Source File")
                for row in nw_data:
                    row[sf_idx] = nw_source
        else:
            print(f"  _NW: not found")

        # ---- 处理 _Group 文件 ----
        grp_headers = None
        grp_data = None
        grp_source = f"{tech} OLIB Network KPIs_Group"
        if group_file:
            files_to_delete.append(group_file)
            print(f"  _Group: {os.path.basename(group_file)}")

            grp_headers, grp_data = read_xlsx(group_file)
            print(f"  _Group: {len(grp_data)} rows, {len(grp_headers)} cols")

            # 增加 "Source File" 列
            if "Source File" not in grp_headers:
                grp_headers.append("Source File")
                for row in grp_data:
                    row.append(grp_source)
            else:
                sf_idx = grp_headers.index("Source File")
                for row in grp_data:
                    row[sf_idx] = grp_source
        else:
            print(f"  _Group: not found")

        # ---- 合并写入 ----
        if nw_headers is None and grp_headers is None:
            print(f"  [skip] no files found")
            continue

        # 合并列头（取并集，保持顺序）
        if nw_headers and grp_headers:
            merged_headers = list(nw_headers)
            for h in grp_headers:
                if h not in merged_headers:
                    merged_headers.append(h)
        elif nw_headers:
            merged_headers = list(nw_headers)
        else:
            merged_headers = list(grp_headers)

        # 构建合并数据
        merged_data = []

        if nw_headers and nw_data:
            for row in nw_data:
                new_row = []
                while len(row) < len(nw_headers):
                    row.append(None)
                for h in merged_headers:
                    if h in nw_headers:
                        new_row.append(row[nw_headers.index(h)])
                    else:
                        new_row.append(None)
                merged_data.append(new_row)

        if grp_headers and grp_data:
            for row in grp_data:
                new_row = []
                while len(row) < len(grp_headers):
                    row.append(None)
                for h in merged_headers:
                    if h in grp_headers:
                        new_row.append(row[grp_headers.index(h)])
                    else:
                        new_row.append(None)
                merged_data.append(new_row)

        print(f"  merged: {len(merged_data)} rows, {len(merged_headers)} cols -> {table_name}")

        if not merged_data:
            raise Exception(f"[Network KPI] {table_name}: 合并后无数据行，解析失败")

        # API 优先写入，回退到本地 SQLite
        if _db_writer is not None:
            try:
                result = _db_writer.write_data(
                    db=DB_NAME,
                    table=table_name,
                    columns=merged_headers,
                    rows=merged_data,
                    mode="upsert",
                    pk_columns=["Begin Time", "Group"],
                )
                row_count = result.get("rows_written", 0)
                if row_count == 0:
                    raise Exception("API 返回 0 行写入")
                print(f"  [API] written: {row_count} rows")
            except Exception as e:
                print(f"  [API] 写入失败: {e}，回退到本地")
                row_count = write_to_db(DB_PATH, table_name, merged_headers, merged_data)
                print(f"  [LOCAL] written: {row_count} rows")
        else:
            row_count = write_to_db(DB_PATH, table_name, merged_headers, merged_data)
            print(f"  [LOCAL] written: {row_count} rows")

        if row_count == 0:
            raise Exception(f"[Network KPI] {table_name}: 写入 0 行，数据丢失")
        total_imported += row_count

        # 释放本迭代大对象
        nw_headers = nw_data = None
        grp_headers = grp_data = None
        merged_headers = merged_data = None
        gc.collect()

    # ---- FTP upload (conditional) ----
    if _db_writer is None:
        print("\n[FTP Upload]")
        print(f"  uploading: {DB_NAME}")
        if upload_to_ftp(DB_PATH, FTP_REMOTE_DIR, DB_NAME):
            print(f"  [OK] uploaded: {DB_NAME}")
        else:
            print(f"  [FAIL] upload failed: {DB_NAME}")
    else:
        print("\n[API] data written via remote API, no FTP needed")

    # ---- 清理已导入的 xlsx 文件 ----
    print("\n[cleanup]")
    all_files = set(files_to_delete)
    for tech in ["2G", "3G", "FDD", "TDD"]:
        for prefix in [f"{tech}_OLIB_Network_KPIs_NW_1Day", f"{tech}_OLIB_Network_KPIs_Group_1Day"]:
            pattern = os.path.join(OUTPUT_DIR, f"{prefix}*.xlsx")
            for fpath in glob.glob(pattern):
                if not os.path.basename(fpath).startswith("~$"):
                    all_files.add(fpath)

    gc.collect()

    deleted_count = 0
    failed_files = []
    for fpath in all_files:
        try:
            os.remove(fpath)
            print(f"  deleted: {os.path.basename(fpath)}")
            deleted_count += 1
        except PermissionError:
            failed_files.append(fpath)
        except Exception as e:
            print(f"  [error] {os.path.basename(fpath)}: {e}")

    # 对锁定文件用 PowerShell 强制删除
    if failed_files:
        print(f"  retrying {len(failed_files)} locked files with PowerShell force...")
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
                    print(f"  [warn] {os.path.basename(fpath)}: still locked, scheduled for reboot")
                    import ctypes
                    ctypes.windll.kernel32.MoveFileExW(fpath, None, 0x4)
            except Exception as e:
                print(f"  [error] {os.path.basename(fpath)}: {e}")

    print(f"  total deleted: {deleted_count} files")
    print(f"\n[DB] 导入完成，总计 {total_imported} 行")
    return total_imported


# ============================================================
# 单任务执行
# ============================================================
def _run_single_kpi_query(auth: dict, task: dict, start_index: int) -> tuple[str, str]:
    """执行单个 KPI 查询任务，返回 (file_prefix, saved_path) 或抛异常。"""
    tech = task["tech"]
    layer = task["layer"]
    gr = task["gr"]
    groupbygroup = task["groupbygroup"]

    cfg = NW_KPI_QUERY_CONFIGS[tech]
    templatename = cfg["templatename"]
    file_prefix = build_filename(templatename, layer, gr)

    # 错峰启动：按索引延迟，避免同时冲击接口
    delay = start_index * 0.8
    if delay > 0:
        time.sleep(delay)

    print(f"\n[MAIN] Starting KPI query: {tech}/{layer} (prefix={file_prefix})")

    payload = build_nw_kpi_payload(tech, gr, groupbygroup)

    cookie = auth["cookie"]
    forgery_token = auth["forgery_token"]

    queryid = create_history_query(cookie, forgery_token, payload)
    wait_history_ready(cookie, forgery_token, queryid)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{file_prefix}_{timestamp}"
    saved_path = export_history(cookie, forgery_token, queryid, filename)

    # 清理同前缀旧文件
    cleanup_old_exports(file_prefix)

    return file_prefix, saved_path


# ============================================================
# 主函数
# ============================================================
def run_network_kpi_sync():
    """主流程：登录 → 并行查询 → 导出 → 清理。"""
    t_start = time.time()
    print(f"[MAIN] RAN UME Network KPI (Zeenshan) sync started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[MAIN] Output dir: {OUTPUT_DIR}")
    print(f"[MAIN] Days back: {DAYS_BACK}")
    print(f"[MAIN] Parallel workers: {MAX_PARALLEL_WORKERS}")
    print(f"[MAIN] Total tasks: {len(NW_KPI_TASKS)}")
    print("=" * 70)

    # 1. 登录
    auth = login()

    # 2. 并行执行查询
    results = []
    errors = []

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
        future_to_task = {}
        for idx, task in enumerate(NW_KPI_TASKS):
            future = executor.submit(_run_with_cleanup, _run_single_kpi_query, auth, task, idx)
            future_to_task[future] = task

        for future in as_completed(future_to_task):
            task = future_to_task[future]
            task_label = f"{task['tech']}/{task['layer']}"
            try:
                file_prefix, saved_path = future.result()
                results.append((file_prefix, saved_path))
                print(f"[MAIN] KPI query [{task_label}] succeeded: {os.path.basename(saved_path)}")
            except Exception as e:
                errors.append((task_label, str(e)))
                print(f"[MAIN] KPI query [{task_label}] failed: {e}")

    # 3. 汇总
    elapsed = time.time() - t_start
    print("\n" + "=" * 70)
    print(f"[MAIN] Export completed in {elapsed:.2f} seconds")
    print(f"[MAIN] Successfully exported {len(results)} files:")
    for prefix, path in results:
        print(f"  - {os.path.basename(path)}")

    if errors:
        print(f"[MAIN] Failed queries ({len(errors)}):")
        for label, err in errors:
            print(f"  - {label}: {err}")

    # 释放资源
    gc.collect()

    # 4. 数据库导入（参考 ran_daily_kpi.py）
    if results:
        import_to_database()
    else:
        print("\n[MAIN] No files exported, skip database import.")

    elapsed_total = time.time() - t_start
    print(f"\n[MAIN] Total completed in {elapsed_total:.2f} seconds")
    print(f"[MAIN] Done.")
    return results


if __name__ == "__main__":
    run_network_kpi_sync()
