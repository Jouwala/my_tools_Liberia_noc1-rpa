# -*- coding: utf-8 -*-
"""
import logging
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
from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names, table_columns, upsert, safe_pragma, pg_trunc_ident

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:ran_ume_network_kpi>: exception swallowed", exc_info=True)
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
MAX_PARALLEL_WORKERS = int(os.environ.get("NW_KPI_PARALLEL_WORKERS", "4"))

# ========== 重试 / 超时配置（环境变量可调） ==========
HTTP_MAX_RETRIES = max(0, int(os.environ.get("NW_KPI_HTTP_MAX_RETRIES", "3")))
HTTP_RETRY_DELAY = float(os.environ.get("NW_KPI_HTTP_RETRY_DELAY", "1"))
HTTP_CONNECT_TIMEOUT = float(os.environ.get("NW_KPI_CONNECT_TIMEOUT", "15"))
HTTP_READ_TIMEOUT = float(os.environ.get("NW_KPI_READ_TIMEOUT", "90"))

# 时间范围：今天之前的 367 天（覆盖一年）
DAYS_BACK = int(os.environ.get("NW_KPI_DAYS_BACK", "14"))

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
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:ran_ume_network_kpi>: exception swallowed", exc_info=True)
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

# 19 个旧命名 ZTE-OLR rangroup（2026-08-11 由 UME 分组管理页面导出，用户确认）。
# 与新命名组是独立口径（无映射关系），UME 上仍 Enabled。
# 用途：① Group 层查询与新组合并导出，恢复 *_ZTE-OLR-* 旧组每日更新；
#       ② NW_OLD 层单独查询这批组，聚合结果按旧流水线口径写入 G_NW。
OLD_UILOCATIONS = [
    # MS-Network 层（7 个）
    {"haslogicmoc": False, "id": "ac09c60f-ede4-4726-9a95-70dfd7f56ab3", "moc": "group.ran.topo", "model": "rangroup"},  # 2G_Regular_ZTE-OLR-MS-Network
    {"haslogicmoc": False, "id": "1212567e-8919-422e-a507-a1657d0ea66a", "moc": "group.ran.topo", "model": "rangroup"},  # 2G_ERA_ZTE-OLR-MS-Network
    {"haslogicmoc": False, "id": "3aa01f9d-6107-4120-904f-18c10816182b", "moc": "group.ran.topo", "model": "rangroup"},  # 2G_Cooli_ZTE-OLR-MS-Network
    {"haslogicmoc": False, "id": "f02801db-a267-4c44-bfd6-09746d93849f", "moc": "group.ran.topo", "model": "rangroup"},  # 3G_Regular_ZTE-OLR-MS-Network
    {"haslogicmoc": False, "id": "88e9e97f-27bb-43c2-8627-8f3a8b65bf19", "moc": "group.ran.topo", "model": "rangroup"},  # 3G_Cooli_ZTE-OLR-MS-Network
    {"haslogicmoc": False, "id": "5e384e6d-7a5d-4b6f-88f3-abc0dd4d625f", "moc": "group.ran.topo", "model": "rangroup"},  # 4G_Regular_ZTE-OLR-MS-Network
    {"haslogicmoc": False, "id": "5ca35171-ccab-41b0-8348-5e1801d08873", "moc": "group.ran.topo", "model": "rangroup"},  # 4G_ERA_ZTE-OLR-MS-Network
    # Region 层（12 个）
    {"haslogicmoc": False, "id": "bf4aa97e-54d4-4686-8fad-27481a1a8f3b", "moc": "group.ran.topo", "model": "rangroup"},  # 2G_Monrovia_ZTE-OLR-Region
    {"haslogicmoc": False, "id": "50489222-477d-4071-a7f6-1f76fcdaea63", "moc": "group.ran.topo", "model": "rangroup"},  # 2G_North_East_ZTE-OLR-Region
    {"haslogicmoc": False, "id": "cb19a368-a1fd-4950-be1a-007c1485c424", "moc": "group.ran.topo", "model": "rangroup"},  # 2G_South_East_ZTE-OLR-Region
    {"haslogicmoc": False, "id": "7017adf9-4ba6-4582-bb1c-251f2659dc5a", "moc": "group.ran.topo", "model": "rangroup"},  # 2G_South_West_ZTE-OLR-Region
    {"haslogicmoc": False, "id": "5f0d1249-70ef-41d4-9775-4bc714f4cac7", "moc": "group.ran.topo", "model": "rangroup"},  # 3G_Monrovia_ZTE-OLR-Region
    {"haslogicmoc": False, "id": "56b65e84-9a84-4441-bbd2-46d33cde02f5", "moc": "group.ran.topo", "model": "rangroup"},  # 3G_North_East_ZTE-OLR-Region
    {"haslogicmoc": False, "id": "6e5f401a-4a34-41b4-a29e-18936670f481", "moc": "group.ran.topo", "model": "rangroup"},  # 3G_South_East_ZTE-OLR-Region
    {"haslogicmoc": False, "id": "6cafdd69-1bbe-4181-85c4-888465394892", "moc": "group.ran.topo", "model": "rangroup"},  # 3G_South_West_ZTE-OLR-Region
    {"haslogicmoc": False, "id": "e7435e36-cdf1-4865-b8f7-98a8408a101c", "moc": "group.ran.topo", "model": "rangroup"},  # 4G_Monrovia_ZTE-OLR-Region
    {"haslogicmoc": False, "id": "3fab34d9-b7f0-40c3-afe1-058f5814fbed", "moc": "group.ran.topo", "model": "rangroup"},  # 4G_North_East_ZTE-OLR-Region
    {"haslogicmoc": False, "id": "8c9ae146-f4ae-4ef6-8adf-1205d47a6d42", "moc": "group.ran.topo", "model": "rangroup"},  # 4G_South_East_ZTE-OLR-Region
    {"haslogicmoc": False, "id": "88562cf4-fbcc-4d4f-8011-16974e755b08", "moc": "group.ran.topo", "model": "rangroup"},  # 4G_South_West_ZTE-OLR-Region
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

# 任务配置：4 技术 × 2 模式（Group/NW）= 8 个查询 + 4 个 NW_OLD（旧组聚合 → G_NW）
# NW_OLD：仅选 19 个旧命名 ZTE-OLR rangroup 做全网聚合，按旧流水线口径写入 G_NW，
# 不影响新命名 {tech}_NW 的统计范围（新旧口径独立）。
NW_KPI_TASKS = [
    {"tech": "2G",  "gr": "86400", "groupbygroup": True,  "layer": "Group"},
    {"tech": "2G",  "gr": "86400", "groupbygroup": False, "layer": "NW"},
    {"tech": "2G",  "gr": "86400", "groupbygroup": False, "layer": "NW_OLD"},
    {"tech": "3G",  "gr": "86400", "groupbygroup": True,  "layer": "Group"},
    {"tech": "3G",  "gr": "86400", "groupbygroup": False, "layer": "NW"},
    {"tech": "3G",  "gr": "86400", "groupbygroup": False, "layer": "NW_OLD"},
    {"tech": "FDD", "gr": "86400", "groupbygroup": True,  "layer": "Group"},
    {"tech": "FDD", "gr": "86400", "groupbygroup": False, "layer": "NW"},
    {"tech": "FDD", "gr": "86400", "groupbygroup": False, "layer": "NW_OLD"},
    {"tech": "TDD", "gr": "86400", "groupbygroup": True,  "layer": "Group"},
    {"tech": "TDD", "gr": "86400", "groupbygroup": False, "layer": "NW"},
    {"tech": "TDD", "gr": "86400", "groupbygroup": False, "layer": "NW_OLD"},
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
                         start_iso: str | None = None, end_iso: str | None = None,
                         locations: list | None = None) -> dict:
    """构造 Network KPI 历史指标查询 Payload，字段顺序与 Payload.txt 一致。

    locations: uilocations 范围，None 时默认新命名 21 组（UILOCATIONS）。
    """
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
    payload["uilocations"] = locations if locations is not None else UILOCATIONS
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

    print(f"[KPI] Exporting: {filename}")
    body = json.dumps(payload, ensure_ascii=False)
    headers = _auth_headers(cookie, forgery_token)

    status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
        "POST", HISTORY_EXPORT_PATH, headers_extra=headers, body=body.encode('utf-8'), max_retries=3,
    )
    print(f"[KPI] Export status: {status}")

    if "200" not in status:
        raise Exception(f"Export KPI history failed: {status}")

    print(f"[KPI] Exported: {filename}.xlsx ({len(resp_body)} bytes, in-memory)")
    return resp_body


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
    """读取 xlsx 文件，返回 (headers, data)。"""
    with open(filepath, 'rb') as f:
        file_bytes = f.read()
    return read_xlsx_bytes(file_bytes)


def read_xlsx_bytes(file_bytes: bytes):
    """从内存字节直接解析 xlsx，不经磁盘。"""
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
    return headers, data


def write_to_db(db_path, table_name, headers, data):
    """将数据写入数据库（双模 sqlite/pg）。
    以 'Begin Time' 和 'Group' 列为联合主键，使用 INSERT OR REPLACE / ON CONFLICT 实现更新/替换。
    PG 模式下列名/表名先按 63 字节 UTF-8 截断（pg_trunc_ident），与建表/加列保持一致。
    """
    # 打开/初始化数据库时若遇到文件锁(SMB 读锁/云同步/索引服务等)会直接报
    # "readonly database"，这里加重试 + 长超时(busy_timeout)，让锁释放窗口内的
    # 写入能自动穿过。连接重试窗口拉到 ~50s 以抗间歇性独占锁。
    last_err = None
    conn = None
    for _attempt in range(1, 11):
        try:
            conn = get_raw_connection(db_path, timeout=60)
            cursor = conn.cursor()
            safe_pragma(conn, "PRAGMA journal_mode=WAL")
            safe_pragma(conn, "PRAGMA synchronous=OFF")
            safe_pragma(conn, "PRAGMA cache_size=-64000")
            safe_pragma(conn, "PRAGMA busy_timeout=60000")
            break
        except Exception as e:
            last_err = e
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] write_to_db: exception swallowed", exc_info=True)
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

    is_sqlite = isinstance(conn, sqlite3.Connection)
    tname = table_name if is_sqlite else pg_trunc_ident(table_name)
    db_headers = headers if is_sqlite else [pg_trunc_ident(h) for h in headers]
    if not is_sqlite:
        seen, dup = set(), []
        for h in db_headers:
            if h in seen and h not in dup:
                dup.append(h)
            seen.add(h)
        if dup:
            logging.getLogger(__name__).warning(
                f"[{table_name}] PG 截断后存在重复列名 {dup}，请人工确认")

    # 检查表是否已存在
    table_exists = tname in set(list_table_names(conn))

    if not table_exists:
        # 新建表
        create_sql = (
            f'CREATE TABLE "{tname}" (\n'
            f'  "Begin Time" TEXT NOT NULL,\n'
            f'  "Group" TEXT NOT NULL,\n'
            f'  PRIMARY KEY ("Begin Time", "Group")\n'
            f')'
        )
        cursor.execute(create_sql)
        for db_h in db_headers:
            if db_h in ("Begin Time", "Group"):
                continue
            safe_col = db_h.replace('"', '""')
            try:
                cursor.execute(f'ALTER TABLE "{tname}" ADD COLUMN "{safe_col}" TEXT')
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] write_to_db: exception swallowed", exc_info=True)
                pass
    else:
        # 表已存在，检查并添加缺少的列
        existing_cols = set(table_columns(conn, tname))
        for db_h in db_headers:
            if db_h not in existing_cols:
                safe_col = db_h.replace('"', '""')
                try:
                    cursor.execute(f'ALTER TABLE "{tname}" ADD COLUMN "{safe_col}" TEXT')
                except Exception:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] write_to_db: exception swallowed", exc_info=True)
                    pass

    # 双模 upsert：以 'Begin Time' + 'Group' 为联合主键（与建表 PRIMARY KEY 一致）
    quoted_headers = [f'"{h.replace(chr(34), chr(34)+chr(34))}"' for h in db_headers]
    conflict_cols = ["Begin Time", "Group"]
    if not is_sqlite:
        conflict_cols = [pg_trunc_ident(c) for c in conflict_cols]
    records = []
    for row in data:
        r = list(row)
        if len(r) < len(headers):
            r = r + [None] * (len(headers) - len(r))
        elif len(r) > len(headers):
            r = r[:len(headers)]
        records.append({db_h: (str(v) if v is not None else None) for db_h, v in zip(db_headers, r)})

    row_count = len(records)
    # 双模 upsert：sqlite=INSERT OR REPLACE / pg=INSERT ... ON CONFLICT DO UPDATE
    for i in range(0, len(records), 2000):
        upsert(conn, tname, records[i:i + 2000], conflict_cols=conflict_cols)

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
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] upload_to_ftp: exception swallowed", exc_info=True)
                    pass
    return False


# ============================================================
# 数据库导入（P2#8 拆分：原 import_to_database 231 行 → 单一职责助手 + 编排）
# ============================================================

def _locate_dataset(data_bytes, prefix, files_to_delete):
    """数据源定位：内存 bytes 优先，否则查找磁盘最新文件（并计入待删除清单）"""
    if data_bytes:
        return data_bytes, None
    file_path = find_latest_xlsx(prefix)
    if file_path:
        files_to_delete.append(file_path)
    return None, file_path


def _read_dataset(data_bytes, file_path, label):
    """读取 xlsx（内存或磁盘）→ (headers, data)；均无时返回 (None, None)"""
    if not data_bytes and not file_path:
        print(f"  {label}: not found")
        return None, None
    if file_path:
        print(f"  {label}: {os.path.basename(file_path)}")
        headers, data = read_xlsx(file_path)
    else:
        print(f"  {label}: from memory ({len(data_bytes)} bytes)")
        headers, data = read_xlsx_bytes(data_bytes)
    print(f"  {label}: {len(data)} rows, {len(headers)} cols")
    return headers, data


def _set_column(headers, data, col_name, value):
    """增加列（或覆盖已有列）并为每行填充固定值"""
    if col_name not in headers:
        headers.append(col_name)
        for row in data:
            row.append(value)
    else:
        idx = headers.index(col_name)
        for row in data:
            row[idx] = value


def _prepare_nw_dataset(tech, data_bytes, file_path, group_value=None, source_name=None, label="_NW"):
    """读取 NW 层数据并补 Group / Source File 列；无数据返回 (None, None)

    group_value/source_name 默认新命名 {tech}_NW；NW_OLD 层传 "G_NW" 复用。
    """
    headers, data = _read_dataset(data_bytes, file_path, label)
    if headers is None:
        return None, None
    gv = group_value if group_value is not None else f"{tech}_NW"
    print(f"  {label} Group: {gv}")
    _set_column(headers, data, "Group", gv)
    _set_column(headers, data, "Source File",
                source_name if source_name is not None else f"{tech} OLIB Network KPIs_NW")
    return headers, data


def _prepare_group_dataset(tech, data_bytes, file_path):
    """读取 Group 数据并补 Source File 列；无数据返回 (None, None)"""
    headers, data = _read_dataset(data_bytes, file_path, "_Group")
    if headers is None:
        return None, None
    _set_column(headers, data, "Source File", f"{tech} OLIB Network KPIs_Group")
    return headers, data


def _merge_datasets(nw_headers, nw_data, grp_headers, grp_data):
    """合并 NW/Group 数据集（列头取并集，按列对齐）→ (merged_headers, merged_data)"""
    if nw_headers and grp_headers:
        merged_headers = list(nw_headers)
        for h in grp_headers:
            if h not in merged_headers:
                merged_headers.append(h)
    elif nw_headers:
        merged_headers = list(nw_headers)
    else:
        merged_headers = list(grp_headers)

    merged_data = []
    for src_headers, src_data in ((nw_headers, nw_data), (grp_headers, grp_data)):
        if not (src_headers and src_data):
            continue
        # 列名 → 下标索引，避免逐列 list.index() 的 O(n²) 扫描
        col_index = {h: i for i, h in enumerate(src_headers)}
        for row in src_data:
            while len(row) < len(src_headers):
                row.append(None)
            merged_data.append([row[col_index[h]] if h in col_index else None for h in merged_headers])
    return merged_headers, merged_data


def _write_dataset(table_name, merged_headers, merged_data, api_failures=None):
    """写入数据库：API 优先，失败回退本地 SQLite，返回写入行数。
    API 写入失败时把表名记入 api_failures，由调用方决定是否需要上报任务失败
    （远程库损坏等场景下若静默回退，会导致任务显示成功但远程库长期未更新）。
    """
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
                # 数据已存在/已同步（upsert 后无新增行），不视为失败也不回退本地
                print("  [API] 无新增行（数据已存在/已同步）")
                return 0
            print(f"  [API] written: {row_count} rows")
            return row_count
        except Exception as e:
            print(f"  [API] 写入失败: {e}，回退到本地")
            if api_failures is not None:
                api_failures.append(f"{table_name}: {e}")
    row_count = write_to_db(DB_PATH, table_name, merged_headers, merged_data)
    print(f"  [LOCAL] written: {row_count} rows")
    return row_count


def _cleanup_imported_files(files_to_delete):
    """清理已导入的 xlsx 文件（锁定文件 PowerShell 强删，仍失败则重启时删除）"""
    print("\n[cleanup]")
    all_files = set(files_to_delete)
    for tech in ["2G", "3G", "FDD", "TDD"]:
        for prefix in [f"{tech}_OLIB_Network_KPIs_NW_1Day", f"{tech}_OLIB_Network_KPIs_NW_OLD_1Day", f"{tech}_OLIB_Network_KPIs_Group_1Day"]:
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
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _cleanup_imported_files: exception swallowed", exc_info=True)
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
    return deleted_count


def import_to_database(export_results: dict = None):
    """将导出的 NW 和 Group xlsx 数据导入 SQLite 数据库。

    Args:
        export_results: {file_prefix: xlsx_bytes} 内存数据。
                        如果为 None 则回退到磁盘读取。
    """
    print("\n" + "=" * 70)
    print("[DB] 开始导入数据库")
    print(f"[DB] 数据库路径: {DB_PATH}")
    print("=" * 70)

    total_imported = 0
    files_to_delete = []
    api_failures = []
    for tech in ["2G", "3G", "FDD", "TDD"]:
        total_imported += _import_one_tech(tech, export_results, files_to_delete, api_failures)

    # ---- 写入结果日志 ----
    if _db_writer is None:
        print("\n[LOCAL] 数据已写入本地 SQLite（API 不可用）")
    elif api_failures:
        print(f"\n[WARNING] {len(api_failures)} 张表远程 API 写入失败，已回退本地:")
        for msg in api_failures:
            print(f"  - {msg}")
    else:
        print("\n[API] 数据已通过远程 API 写入")

    _cleanup_imported_files(files_to_delete)

    print(f"\n[DB] 导入完成，总计 {total_imported} 行")

    if api_failures:
        # 远程写入失败必须让任务显式失败，避免“任务成功但远程库未更新”
        raise Exception(
            f"[Network KPI] 远程 API 写入失败 {len(api_failures)}/4 张表（已回退本地）: "
            + "; ".join(api_failures)
        )

    return total_imported


def _import_one_tech(tech, export_results, files_to_delete, api_failures=None):
    """单个制式（2G/3G/FDD/TDD）的完整导入流程，返回写入行数（无数据源跳过返回 0）"""
    # 文件前缀（与 build_filename 生成的一致，空格已替换为下划线）
    nw_prefix = f"{tech}_OLIB_Network_KPIs_NW_1Day"
    nw_old_prefix = f"{tech}_OLIB_Network_KPIs_NW_OLD_1Day"
    group_prefix = f"{tech}_OLIB_Network_KPIs_Group_1Day"
    table_name = f"{tech}_OLIB_Network_KPIs"

    nw_bytes = export_results.get(nw_prefix) if export_results else None
    nw_old_bytes = export_results.get(nw_old_prefix) if export_results else None
    group_bytes = export_results.get(group_prefix) if export_results else None

    print(f"\n[{tech}]")

    nw_bytes, nw_file = _locate_dataset(nw_bytes, nw_prefix, files_to_delete)
    nw_old_bytes, nw_old_file = _locate_dataset(nw_old_bytes, nw_old_prefix, files_to_delete)
    group_bytes, group_file = _locate_dataset(group_bytes, group_prefix, files_to_delete)

    # ---- 处理 _NW / _NW_OLD / _Group 数据 ----
    nw_headers, nw_data = _prepare_nw_dataset(tech, nw_bytes, nw_file)
    # NW_OLD：旧命名组聚合 → G_NW（旧流水线口径）
    nwo_headers, nwo_data = _prepare_nw_dataset(
        tech, nw_old_bytes, nw_old_file,
        group_value="G_NW",
        source_name=f"{tech} OLIB Network KPIs_NW_OLD",
        label="_NW_OLD",
    )
    grp_headers, grp_data = _prepare_group_dataset(tech, group_bytes, group_file)

    # ---- 合并写入 ----
    if nw_headers is None and grp_headers is None and nwo_headers is None:
        print("  [skip] no files found")
        return 0

    merged_headers, merged_data = _merge_datasets(nw_headers, nw_data, grp_headers, grp_data)
    if nwo_headers:
        merged_headers, merged_data = _merge_datasets(merged_headers, merged_data, nwo_headers, nwo_data)

    print(f"  merged: {len(merged_data)} rows, {len(merged_headers)} cols -> {table_name}")

    if not merged_data:
        raise Exception(f"[Network KPI] {table_name}: 合并后无数据行，解析成功")

    row_count = _write_dataset(table_name, merged_headers, merged_data, api_failures)

    if row_count == 0:
        print(f"[Network KPI] {table_name}: 无新增行（数据已存在/已同步）")

    # 释放本迭代大对象
    nw_headers = nw_data = None
    nwo_headers = nwo_data = None
    grp_headers = grp_data = None
    merged_headers = merged_data = None
    gc.collect()
    return row_count


# ============================================================
# 单任务执行
# ============================================================
def _run_single_kpi_query(auth: dict, task: dict, start_index: int) -> tuple[str, bytes]:
    """执行单个 KPI 查询任务，返回 (file_prefix, xlsx_bytes) 或抛异常。"""
    tech = task["tech"]
    layer = task["layer"]
    gr = task["gr"]
    groupbygroup = task["groupbygroup"]

    cfg = NW_KPI_QUERY_CONFIGS[tech]
    templatename = cfg["templatename"]
    file_prefix = build_filename(templatename, layer, gr)

    # uilocations 范围：Group 层新旧组全选（旧组行随导出自然带回）；
    # NW 层只选新组（保持 {tech}_NW 口径不变）；NW_OLD 层只选旧组（聚合写 G_NW）
    if layer == "Group":
        locations = UILOCATIONS + OLD_UILOCATIONS
    elif layer == "NW_OLD":
        locations = OLD_UILOCATIONS
    else:
        locations = UILOCATIONS

    # 错峰启动：按索引延迟，避免同时冲击接口
    delay = start_index * 0.8
    if delay > 0:
        time.sleep(delay)

    print(f"\n[MAIN] Starting KPI query: {tech}/{layer} (prefix={file_prefix})")

    payload = build_nw_kpi_payload(tech, gr, groupbygroup, locations=locations)

    cookie = auth["cookie"]
    forgery_token = auth["forgery_token"]

    queryid = create_history_query(cookie, forgery_token, payload)
    wait_history_ready(cookie, forgery_token, queryid)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{file_prefix}_{timestamp}"
    xlsx_bytes = export_history(cookie, forgery_token, queryid, filename)

    return file_prefix, xlsx_bytes


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

    # 2. 并行执行查询（全程内存）
    export_data = {}  # {file_prefix: xlsx_bytes}
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
                file_prefix, xlsx_bytes = future.result()
                export_data[file_prefix] = xlsx_bytes
                print(f"[MAIN] KPI query [{task_label}] succeeded: {len(xlsx_bytes)} bytes (in-memory)")
            except Exception as e:
                errors.append((task_label, str(e)))
                print(f"[MAIN] KPI query [{task_label}] failed: {e}")

    # 3. 汇总
    elapsed = time.time() - t_start
    print("\n" + "=" * 70)
    print(f"[MAIN] Export completed in {elapsed:.2f} seconds")
    print(f"[MAIN] Successfully exported {len(export_data)} tables (in-memory)")

    if errors:
        print(f"[MAIN] Failed queries ({len(errors)}):")
        for label, err in errors:
            print(f"  - {label}: {err}")

    # 4. 数据库导入（从内存读取）
    exported_count = len(export_data)
    if export_data:
        try:
            import_to_database(export_results=export_data)
        except Exception as e:
            errors.append(("import_to_database", str(e)))
            print(f"[MAIN] Database import failed: {e}")
    else:
        print("\n[MAIN] No data exported, skip database import.")

    # 释放内存
    export_data = None
    gc.collect()

    elapsed_total = time.time() - t_start
    print(f"\n[MAIN] Total completed in {elapsed_total:.2f} seconds")
    print(f"[MAIN] Done.")
    # 返回结构化结果：errors 为空才算成功；否则 Task Manager 只显示“成功”却看不到部分失败
    return {
        "success": len(errors) == 0,
        "exported": exported_count,
        "errors": [f"{label}: {err}" for label, err in errors],
        "elapsed_seconds": round(elapsed_total, 2),
    }


if __name__ == "__main__":
    run_network_kpi_sync()
