# -*- coding: utf-8 -*-
"""
CNN UME KPI 数据同步服务（Core Network - xGW License Occupancy）

功能：
1. 登录 ZTE CNN UME 网管系统（https://10.121.1.2:28808/em-portal），获取鉴权 Cookie 与 forgery token。
2. 创建 xGW License Occupancy 等 8 个历史指标查询任务（ME 级，小时/天粒度）。
3. 轮询查询进度直到完成，导出为 Excel 文件。
4. 将导出的 xlsx 通过 DbWriterClient API 写入远程 CNN 数据库（db_ps_cs_cn.sqlite3）。
5. 清理本地 xlsx 文件。
6. 额外执行 1 个月粒度（gr=2592000）查询：开始时间为 7 个月前 1 号 00:00:00，
   写入远程数据库表名前加 "1month_" 前缀（如 1month_xGW_LICENSE_OCCUPANCY_TEMPLATE_OSS_UME）。

集成方式：
- 通过 Task Manager 调度（task_id="cnn_kpi_sync"）
- 数据写入：HTTP API → DB CNN (E:\\01_RPA\\LBR_Tools\\KPI\\db_ps_cs_cn.sqlite3)
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
import logging
import threading
import random
import openpyxl
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("cnn_ume_kpi_service")

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:ccn_ume_kpi_service>: exception swallowed", exc_info=True)
    pass

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# ============================================================
# 配置
# ============================================================
HOST = "10.121.1.2"
PORT = 28808
LOGIN_PORTAL = "/em-portal"


def _runtime_credentials():
    """运行时获取凭据（环境变量 > 数据库 > 模块默认值），支持页面改密后免重启生效。"""
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        from credential_store import get_credential
    return get_credential("ccn_ume")

# 数据目录（my_app 自包含）
CNN_UME_DATA_DIR = Path(r"d:\01_RPA\Task\my_app\data\cnn_ume")
CNN_UME_DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = str(CNN_UME_DATA_DIR / "exports")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 查询时间范围：上个月同一天 → 今天（滚动 1 个月）
CNN_KPI_DAYS_BACK = int(os.environ.get("CNN_KPI_DAYS_BACK", "7"))

# ========== 外部化配置（Settings 页面可编辑的 cnn_kpi_config.json） ==========
try:
    from backend.services.task_config_files import load_json_config
    _CNN_CONF = load_json_config(Path(__file__).resolve().parent / "cnn_kpi_config.json")
except Exception:
    _CNN_CONF = None
if _CNN_CONF:
    HOST = _CNN_CONF.get("host", HOST)
    PORT = int(_CNN_CONF.get("port", PORT))
    if not os.environ.get("CNN_KPI_DAYS_BACK"):
        CNN_KPI_DAYS_BACK = max(1, int(_CNN_CONF.get("days_back", CNN_KPI_DAYS_BACK)))
    print(f"[CNN] 已加载 cnn_kpi_config.json: host={HOST}, days_back={CNN_KPI_DAYS_BACK}")

# 并行查询线程数
MAX_PARALLEL_WORKERS = int(os.environ.get("CNN_KPI_PARALLEL_WORKERS", "8"))

# ========== 重试 / 超时配置（环境变量可调） ==========
HTTP_MAX_RETRIES = max(0, int(os.environ.get("CNN_KPI_HTTP_MAX_RETRIES", "3")))
HTTP_RETRY_DELAY = float(os.environ.get("CNN_KPI_HTTP_RETRY_DELAY", "1"))
HTTP_CONNECT_TIMEOUT = float(os.environ.get("CNN_KPI_CONNECT_TIMEOUT", "15"))
HTTP_READ_TIMEOUT = float(os.environ.get("CNN_KPI_READ_TIMEOUT", "90"))

# PM 接口路径
HISTORY_PATH = "/api/pm-analysis/v2/history"
HISTORY_POLL_PATH = "/api/pm-analysis/v1/history"
HISTORY_EXPORT_PATH = "/api/pm-analysis/v3/history/export"
HISTORY_REFERER = f"https://{HOST}:{PORT}/em-portal"

# 远程写入 API 配置（DB CNN: db_ps_cs_cn.sqlite3）
DB_NAME = "db_ps_cs_cn.sqlite3"
try:
    from backend.services.db_writer_client import DbWriterClient
except ImportError:
    logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:ccn_ume_kpi_service>: exception swallowed", exc_info=True)
    from db_writer_client import DbWriterClient
try:
    _db_writer = DbWriterClient()
except Exception:
    _db_writer = None
    logger.warning("[CNN] db_writer_client 初始化失败")

# 标识列候选（用于联合主键去重；ME 级导出常见 "ME"/"Managed Element"，
# 注意导出中可能带不间断空格 \xa0。必须取**全部存在**的候选列，只取第一个
# 会导致同一 Begin Time 下多行（不同 NE/计数器）被 upsert 塌缩）
IDENTITY_COL_CANDIDATES = [
    "ME", "NE", "Managed Element", "Managed\xa0Element", "ManagedElement",
    "SERVICE", "Measurement Object", "Counter", "Object", "MO",
    "NodeB", "NodeB Name", "eNodeB", "eNodeB Name", "Cell", "Cell Name",
    "Group", "SubNetwork", "NE Name", "Name",
]

# gr 显示名称替换规则
GR_RENAME = {
    "3600": "1Hour",
    "86400": "1Day",
    "2592000": "1Month",
}

# grouplayer 替换规则
GROUPLAYER_RENAME = {
    "me,WV4.IubLink": "Sites",
    "me,gv4.BTSSiteManager": "Sites",
    "me,eNodeBFunction": "Sites",
    "me,gv4.BTSSiteManager,gv4.BTS.cell": "Cells",
    "me,eNodeBFunction,EUtranCellFDD": "Cells",
    "me,WV4.IubLink,WV4.UtranCell": "Cells",
    "me,fservice": "NE",
    "me": "NE",
}

# ============================================================
# KPI 查询配置（8 个模板）
# ============================================================
CNN_KPI_QUERY_CONFIGS = {
    "xGW_LICENSE": {
        "favoriteconditionname": "xGW_LICENSE_OCCUPANCY_TEMPLATE_OSS_updated",
        "templatename": "xGW_LICENSE_OCCUPANCY_TEMPLATE_OSS_updated",
        "templateid": "1649220598189",
        "gr": "3600",
        "groupbygroup": False,
        "filterlayer": "all",
        "grouplayer": "me",
        "motid": "55035",
        "nfctid": "cn.ngc.xgw-u",
        "items": ["C550350013", "C550350015", "C550350016"],
        "itemsposition": [0, 0, 0],
        "itemsposition1": [0, 0, 0],
        "groupchoice": None,
        "invaliditems": [],
        "table_name": "xGW_LICENSE_OCCUPANCY_TEMPLATE_OSS_UME",
    },
    "xGW_CPU_USAGE": {
        "favoriteconditionname": "xGW_CPU_USAGE_TEMPLATE_OSS_updated",
        "templatename": "xGW_CPU_USAGE_TEMPLATE_OSS_updated",
        "templateid": "1649220598188",
        "gr": "86400",
        "groupbygroup": False,
        "filterlayer": "all",
        "grouplayer": "me",
        "motid": "55011",
        "nfctid": "cn.ngc.xgw-u",
        "items": ["C550110011", "C550110012", "C550110013"],
        "itemsposition": [0, 0, 0],
        "itemsposition1": [0, 0, 0],
        "groupchoice": None,
        "invaliditems": [],
        "table_name": "xGW_CPU_USAGE_TEMPLATE_OSS_UME_UME",
    },
    "VOICE_TRAFFIC": {
        "favoriteconditionname": "VOICE_TRAFFIC_TEMPLATE_OSS_updated",
        "templatename": "VOICE_TRAFFIC_TEMPLATE_OSS_updated",
        "templateid": "1649220598190",
        "gr": "86400",
        "groupbygroup": False,
        "filterlayer": "all",
        "grouplayer": "me,fservice",
        "motid": "50113",
        "nfctid": "cn.wcn.cs.mscs",
        "items": ["cn.wcn.cs.501130016"],
        "itemsposition": [0],
        "itemsposition1": [0],
        "groupchoice": None,
        "invaliditems": [],
        "table_name": "VOICE_TRAFFIC_TEMPLATE_OSS_UME",
    },
    "VLR_SUBSCRIBERS": {
        "favoriteconditionname": "VLR_SUBSCRIBERS_TEMPLATE_OSS_updated",
        "templatename": "VLR_SUBSCRIBERS_TEMPLATE_OSS_updated",
        "templateid": "1649220598191",
        "gr": "86400",
        "groupbygroup": False,
        "filterlayer": "all",
        "grouplayer": "me,fservice",
        "motid": "50009",
        "nfctid": "cn.wcn.cs.mscs",
        "items": ["C407380014"],
        "itemsposition": [0],
        "itemsposition1": [0],
        "groupchoice": None,
        "invaliditems": [],
        "table_name": "VLR_SUBSCRIBERS_TEMPLATE_OSS_UME",
    },
    "DATA_SUBSCRIBERS": {
        "favoriteconditionname": "DATA_SUBSCRIBERS_TEMPLATE_OSS_updated",
        "templatename": "DATA_SUBSCRIBERS_TEMPLATE_OSS_updated",
        "templateid": "1649220598192",
        "gr": "86400",
        "groupbygroup": False,
        "filterlayer": "all",
        "grouplayer": "me,fservice",
        "motid": "50900,50300",
        "nfctid": "cn.umac.amfmmegngpsgsn",
        "items": ["C405080015", "C405080016", "C431000001"],
        "itemsposition": [1, 1, 0],
        "itemsposition1": [0, 0, 0],
        "groupchoice": "cn_service_group_choice=normal",
        "invaliditems": [],
        "table_name": "DATA_SUBSCRIBERS_TEMPLATE_OSS_UME",
    },
    "3G_FDD_DATA_TRAFFIC": {
        "favoriteconditionname": "3G_FDD_DATA_TRAFFIC_TEMPLATE_OSS_updated",
        "templatename": "3G_FDD_DATA_TRAFFIC_TEMPLATE_OSS_updated",
        "templateid": "1649220598193",
        "gr": "86400",
        "groupbygroup": False,
        "filterlayer": "all",
        "grouplayer": "me,fservice,cnngcxgwu4923",
        "motid": "4923",
        "nfctid": "cn.ngc.xgw-u",
        "items": ["C049230117"],
        "itemsposition": [0],
        "itemsposition1": [0],
        "groupchoice": None,
        "invaliditems": [],
        "table_name": "3G_FDD_DATA_TRAFFIC_TEMPLATE_OSS_UME",
    },
    "4G_FDD_DATA_TRAFFIC": {
        "favoriteconditionname": "4G_FDD_DATA_TRAFFIC_TEMPLATE_OSS_updated",
        "templatename": "4G_FDD_DATA_TRAFFIC_TEMPLATE_OSS_updated",
        "templateid": "1649220598194",
        "gr": "86400",
        "groupbygroup": False,
        "filterlayer": "all",
        "grouplayer": "me,fservice,cnngcxgwu4868",
        "motid": "4868",
        "nfctid": "cn.ngc.xgw-u",
        "items": ["cn.xgw.48680010"],
        "itemsposition": [0],
        "itemsposition1": [0],
        "groupchoice": None,
        "invaliditems": [],
        "table_name": "4G_FDD_DATA_TRAFFIC_TEMPLATE_OSS_UME",
    },
    "FREE_RATING_GROUP": {
        "favoriteconditionname": "FREE_RATING_GROUP_TEMPLATE_OSS_updated",
        "templatename": "FREE_RATING_GROUP_TEMPLATE_OSS_updated",
        "templateid": "1649220598195",
        "gr": "86400",
        "groupbygroup": False,
        "filterlayer": "all",
        "grouplayer": "me,fservice,cnngcxgwu55040",
        "motid": "55040",
        "nfctid": "cn.ngc.xgw-u",
        "items": ["C550400011", "C550400012", "C550400013"],
        "itemsposition": [0, 0, 0],
        "itemsposition1": [0, 0, 0],
        "groupchoice": None,
        "invaliditems": None,
        "table_name": "FREE_RATING_GROUP_TEMPLATE_OSS_update_UME",
    },
}

# ========== 外部化配置：CNN 查询模板（Settings 页面可编辑的 cnn_kpi_config.json） ==========
# 优先级：环境变量 > 配置文件 > 内置默认。items/positions 逗号串 → 列表。
try:
    from backend.services.task_config_files import load_json_config, normalize_query_configs
    _CNN_CONF_QC = load_json_config(Path(__file__).resolve().parent / "cnn_kpi_config.json")
except Exception:
    _CNN_CONF_QC = None
if _CNN_CONF_QC:
    if not os.environ.get("CNN_KPI_DAYS_BACK"):
        CNN_KPI_DAYS_BACK = max(1, int(_CNN_CONF_QC.get("days_back", CNN_KPI_DAYS_BACK)))
    if isinstance(_CNN_CONF_QC.get("query_configs"), list):
        _rebuilt_cnn = normalize_query_configs(_CNN_CONF_QC["query_configs"])
        if _rebuilt_cnn:
            CNN_KPI_QUERY_CONFIGS = _rebuilt_cnn
    print(f"[CNN] 已加载 cnn_kpi_config.json: 模板={list(CNN_KPI_QUERY_CONFIGS.keys())}")

# 任务列表
CNN_KPI_TASKS = [
    {"key": "xGW_LICENSE"},
    {"key": "xGW_CPU_USAGE"},
    {"key": "VOICE_TRAFFIC"},
    {"key": "VLR_SUBSCRIBERS"},
    {"key": "DATA_SUBSCRIBERS"},
    {"key": "3G_FDD_DATA_TRAFFIC"},
    {"key": "4G_FDD_DATA_TRAFFIC"},
    {"key": "FREE_RATING_GROUP"},
]


# ============================================================
# 1 个月粒度查询配置（gr=2592000），表名前加 "1month_" 前缀
# ============================================================
def _build_monthly_query_configs():
    """从现有查询配置派生月度（gr=2592000）配置：仅改 gr 与表名前缀。"""
    import copy
    monthly = {}
    for key, cfg in CNN_KPI_QUERY_CONFIGS.items():
        m_cfg = copy.deepcopy(cfg)
        m_cfg["gr"] = "2592000"
        m_cfg["table_name"] = "1month_" + cfg["table_name"]
        monthly[key] = m_cfg
    return monthly


CNN_KPI_MONTHLY_QUERY_CONFIGS = _build_monthly_query_configs()

# 月度任务列表（与日/时粒度任务并行执行，查询 7 个月前 1 号 00:00:00 至今）
CNN_KPI_MONTHLY_TASKS = [
    {"key": key, "monthly": True} for key in CNN_KPI_QUERY_CONFIGS
]


# ============================================================
# HTTP / SSL 工具函数（连接复用 + bytearray + 截断检测）
# ============================================================
_http_local = threading.local()


def _create_ssl_socket():
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
            logger.warning(f"[CNN][HTTP] Connect failed (attempt {retry+1}): {e}, retry in {delay:.1f}s")
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
        f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36\r\n"
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
            logger.warning(f"[CNN][HTTP] Send failed (attempt {retry+1}): {e}, retry in {delay:.1f}s")
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
            logger.warning(f"[CNN][HTTP] Cannot parse response (attempt {retry+1}), retry in {delay:.1f}s")
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
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives import serialization
    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
    public_key = serialization.load_pem_public_key(pem.encode())
    encrypted = public_key.encrypt(plaintext.encode('utf-8'), asym_padding.PKCS1v15())
    return base64.b64encode(encrypted).decode('ascii')


def _auth_headers(cookie: str, forgery_token: str, extra: dict = None) -> str:
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


def _http_request_with_retry(method, path, headers_extra=None, body=None,
                             max_retries: int = 2, retry_statuses: tuple = None) -> tuple:
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
                    logger.info(f"[CNN][HTTP] {status} on {path}, retry in {wait_sec}s")
                    time.sleep(wait_sec)
                    continue
            return status, hdrs, raw_hdrs, resp_body
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                wait_sec = 2 ** attempt
                logger.info(f"[CNN][HTTP] Failed: {e}, retry in {wait_sec}s")
                time.sleep(wait_sec)
            else:
                break
    raise last_exception or Exception(f"HTTP request failed after {max_retries + 1} attempts")


# ============================================================
# 登录
# ============================================================
def _login():
    """执行 CNN UME 登录流程，返回 {cookie, forgery_token}。"""
    logger.info("[CNN] Starting authentication...")
    session_cookie = ""
    forgery_token = ""

    # Step 1: authorize
    status, hdrs, raw_hdrs, body = _http_request(
        "GET",
        f"/api/oauth2/v1/authorize?scope=user.login&response_type=code&redirect_uri={LOGIN_PORTAL}"
    )
    init_cookies = []
    for line in raw_hdrs.split("\r\n"):
        if line.lower().startswith("set-cookie:"):
            cookie_val = line.split(": ", 1)[1].split(";")[0]
            if cookie_val.split("=", 1)[-1]:
                init_cookies.append(cookie_val)
                if "forgerydefense" in cookie_val:
                    forgery_token = cookie_val.split("=", 1)[1]

    init_cookie_str = "; ".join(init_cookies)
    html = body.decode('utf-8', errors='replace')
    lp_match = re.search(r'var\s+loginParameters\s*=\s*["\']([^"\']+)["\']', html)
    login_parameters = lp_match.group(1) if lp_match else ""

    # Step 2: RSA public key
    rsa_headers = f"Cookie: {init_cookie_str}\r\nX-Requested-With: XMLHttpRequest\r\n"
    status, hdrs, raw_hdrs, body = _http_request(
        "GET", "/api/oauth2/v1/login/publickey", headers_extra=rsa_headers,
    )
    public_key_b64 = ""
    if "200" in status:
        pk_data = json.loads(body.decode('utf-8'))
        public_key_b64 = pk_data.get("rsaPublicKey", "")
    if not public_key_b64:
        raise Exception("无法获取 RSA 公钥，登录中止")

    # Step 3: Encrypt password
    _cred_user, _cred_pwd = _runtime_credentials()
    encrypted_pwd = _rsa_encrypt_pem(_cred_pwd, public_key_b64)

    # Step 4: Login
    login_payload = json.dumps({
        "username": _cred_user,
        "password": encrypted_pwd,
        "parameters": login_parameters,
    })
    login_headers = (
        f"Content-Type: application/json\r\n"
        f"Cookie: {init_cookie_str}\r\n"
        f"Referer: https://{HOST}:{PORT}/api/oauth2/v1/authorize?scope=user.login"
        f"&response_type=code&redirect_uri={LOGIN_PORTAL}\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
    )
    if forgery_token:
        login_headers += f"forgerydefense: {forgery_token}\r\n"

    status, hdrs, raw_hdrs, body = _http_request(
        "POST", "/api/oauth2/v1/login_rsa",
        headers_extra=login_headers, body=login_payload,
    )

    cookies = list(init_cookies)
    for line in raw_hdrs.split("\r\n"):
        if line.lower().startswith("set-cookie:"):
            cookie_val = line.split(": ", 1)[1].split(";")[0]
            if cookie_val.split("=", 1)[-1]:
                cookie_name = cookie_val.split("=", 1)[0]
                cookies = [c for c in cookies if not c.startswith(cookie_name + "=")]
                cookies.append(cookie_val)
                if "forgerydefense" in cookie_val:
                    forgery_token = cookie_val.split("=", 1)[1]

    session_cookie = "; ".join(cookies)
    resp_text = body.decode('utf-8', errors='replace')

    success = (
        "302" in status
        or "em-portal" in resp_text
        or "default.html" in resp_text
        or any("Z-AUTH-CODE" in c for c in cookies)
        or len(cookies) > 3
    )
    if not success:
        raise Exception(f"CNN UME 登录失败: {resp_text[:200]}")

    logger.info(f"[CNN] Login SUCCESS - {len(cookies)} cookies")
    return {"cookie": session_cookie, "forgery_token": forgery_token}


# ============================================================
# Payload 构造
# ============================================================
def _subtract_months(dt, months):
    import calendar
    year = dt.year
    month = dt.month - months
    while month < 1:
        month += 12
        year -= 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def build_cnn_kpi_payload(cfg: dict, start_iso: str = None, end_iso: str = None, monthly: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    if end_iso is None:
        end_iso = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if start_iso is None:
        if monthly:
            # 1 个月粒度：开始时间为 7 个月前 1 号 00:00:00
            start_dt = _subtract_months(now, 7).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
        else:
            start_dt = (now.replace(hour=0, minute=0, second=0, microsecond=0)) - timedelta(days=CNN_KPI_DAYS_BACK)
        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    timeinfo = {
        "mode": 1, "start": start_iso, "end": end_iso, "relative": -1,
        "timezonetype": "1", "clienttimezone": "Atlantic/Reykjavik",
        "showtimezoneoffset": False,
        "querylongtime": {"type": 0, "value": 1},
        "timespanfilter": "00:00:00-24:00:00",
        "dayfiltertype": 0,
        "dayinmonthfilter": "1111111111111111111111111111111",
    }

    fields = [
        ("arraycounterinfos", []),
        ("displaymode", 0),
        ("favoriteconditionname", cfg["favoriteconditionname"]),
        ("gr", cfg["gr"]),
        ("groupattributetype", 0),
        ("groupbygroup", cfg["groupbygroup"]),
        ("groupbyplmn", False),
        ("grouptype", 0),
        ("items", cfg["items"]),
        ("itemsposition", cfg["itemsposition"]),
        ("itemsposition1", cfg["itemsposition1"]),
        ("motid", cfg["motid"]),
        ("nfctid", cfg["nfctid"]),
        ("plmnpdfdisplaymode", False),
        ("queryallbusiness", False),
        ("showbusinesscolumn", False),
        ("showintegrity", False),
        ("straightquery", False),
        ("templatename", cfg["templatename"]),
        ("templateid", cfg["templateid"]),
        ("versiondatacompare", False),
        ("needdeployfilter", False),
        ("timeinfo", timeinfo),
        ("thresholdinfos", []),
        ("sendalarm", False),
        ("templatetype", 0),
        ("filterlayer", cfg.get("filterlayer", "all")),
        ("grouplayer", cfg.get("grouplayer", "me")),
        ("containvcell", 0),
        ("resfilterattribute", ""),
        ("uilocations", []),
        ("reslocation", []),
    ]

    if cfg.get("groupchoice"):
        fields.append(("groupchoice", cfg["groupchoice"]))

    fields.extend([
        ("inexistenceres", False),
        ("firstDayOfWeek", 7),
        ("iswireless", False),
        ("hidehistorystopbutton", False),
        ("opencustomizehistoryexport", False),
        ("opentemplatecustomcolumn", False),
    ])

    if cfg.get("invaliditems") is not None:
        fields.append(("invaliditems", cfg["invaliditems"]))

    return dict(fields)


# ============================================================
# KPI 查询 / 轮询 / 导出
# ============================================================
def create_history_query(cookie: str, forgery_token: str, payload: dict) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    headers = _auth_headers(cookie, forgery_token)
    status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
        "POST", HISTORY_PATH, headers_extra=headers, body=body.encode('utf-8'), max_retries=2,
    )
    resp_text = resp_body.decode('utf-8', errors='replace')
    if "200" not in status:
        raise Exception(f"Create KPI query failed: {status}")
    data = json.loads(resp_text)
    queryid = data.get("queryid") or data.get("id")
    if not queryid:
        raise Exception(f"No queryid returned: {resp_text[:500]}")
    return queryid


def wait_history_ready(cookie: str, forgery_token: str, queryid: str,
                       timeout: int = 300, interval: int = 5) -> dict:
    path = f"{HISTORY_POLL_PATH}?type=0&queryid={queryid}"
    headers = _auth_headers(cookie, forgery_token)
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
            "GET", path, headers_extra=headers, max_retries=1,
        )
        data = json.loads(resp_body.decode('utf-8', errors='replace'))
        if data.get("querystate") == 1 or data.get("progress", 0) >= 100:
            return data
        time.sleep(interval)
    raise Exception(f"KPI query timed out after {timeout}s")


def _extract_xlsx_bytes(resp_bytes):
    if len(resp_bytes) < 4 or resp_bytes[:2] != b'PK':
        return resp_bytes
    try:
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(resp_bytes))
        xlsx_names = [n for n in z.namelist() if n.lower().endswith('.xlsx')]
        if xlsx_names:
            return z.read(xlsx_names[0])
        names = z.namelist()
        if len(names) == 1:
            return z.read(names[0])
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] _extract_xlsx_bytes: exception swallowed", exc_info=True)
        pass
    return resp_bytes


def export_history(cookie: str, forgery_token: str, queryid: str, filename: str) -> bytes:
    """导出 KPI 历史数据，直接返回 xlsx 字节（不落盘）。"""
    payload = {
        "id": queryid, "filename": filename, "chartlayout": 1, "contentmode": 0,
        "customizefieldtype": "0", "exportfiletype": 1, "exportserialnumber": False,
        "exporttableheaders": False, "formatwithts": 0, "imageinfo": [],
        "itemshowtype": 0, "tableheaders": {},
    }
    body = json.dumps(payload, ensure_ascii=False)
    headers = _auth_headers(cookie, forgery_token)
    status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
        "POST", HISTORY_EXPORT_PATH, headers_extra=headers, body=body.encode('utf-8'), max_retries=2,
    )
    if "200" not in status:
        raise Exception(f"Export KPI history failed: {status}")

    xlsx_bytes = _extract_xlsx_bytes(resp_body)
    logger.info(f"[CNN] Exported: {filename}.xlsx ({len(xlsx_bytes)} bytes, in-memory)")
    return xlsx_bytes


# ============================================================
# 文件命名
# ============================================================
def _resolve_grouplayer_name(grouplayer: str, groupbygroup: bool) -> str:
    if grouplayer == "all":
        return "Group" if groupbygroup else "NW"
    if grouplayer in GROUPLAYER_RENAME:
        return GROUPLAYER_RENAME[grouplayer]
    if grouplayer.startswith("me,fservice,"):
        return "NE"
    return grouplayer


def build_filename(cfg: dict) -> str:
    name = cfg["templatename"]
    layer = _resolve_grouplayer_name(cfg.get("grouplayer", "me"), cfg.get("groupbygroup", False))
    gr_label = GR_RENAME.get(cfg["gr"], cfg["gr"])
    return f"{name}_{layer}_{gr_label}"


# ============================================================
# xlsx 读取与主键检测
# ============================================================
def read_xlsx(filepath):
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
        data = [list(row) for row in rows_iter if not all(v is None for v in row)]
    finally:
        wb.close()
    return headers, data


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


def detect_key_cols(headers):
    if "Begin Time" not in headers:
        return None
    key_cols = ["Begin Time"]
    for cand in IDENTITY_COL_CANDIDATES:
        if cand in headers and cand not in key_cols:
            key_cols.append(cand)
    # 无网元标识列时退而用 End Time，避免同一天所有行被 upsert 塌缩成一行
    if len(key_cols) == 1 and "End Time" in headers:
        key_cols.append("End Time")
    return key_cols


# ============================================================
# 数据库导入（通过 API 写入远程 DB CNN）
# ============================================================
def import_to_database(export_results: dict = None):
    """将导出的 xlsx 数据通过 API 写入远程 CNN 数据库。

    Args:
        export_results: {file_prefix: xlsx_bytes} 内存数据。
                        如果为 None 则回退到磁盘读取（兼容旧模式）。
    """
    logger.info("[CNN][DB] 开始导入数据库（API 模式）")
    total_imported = 0
    files_to_delete = []

    for task in CNN_KPI_TASKS + CNN_KPI_MONTHLY_TASKS:
        cfg = CNN_KPI_MONTHLY_QUERY_CONFIGS[task["key"]] if task.get("monthly") else CNN_KPI_QUERY_CONFIGS[task["key"]]
        table_name = cfg["table_name"]
        file_prefix = build_filename(cfg)

        # 优先从内存获取，回退磁盘
        xlsx_bytes = export_results.get(file_prefix) if export_results else None
        if xlsx_bytes:
            logger.info(f"[CNN][DB] {table_name}: reading from memory ({len(xlsx_bytes)} bytes)")
            headers, data = read_xlsx_bytes(xlsx_bytes)
        else:
            pattern = os.path.join(OUTPUT_DIR, f"{file_prefix}*.xlsx")
            files = [f for f in glob.glob(pattern) if not os.path.basename(f).startswith("~$")]
            if not files:
                logger.info(f"[CNN][DB] {table_name}: no file found (prefix={file_prefix})")
                continue
            files.sort(key=os.path.getmtime, reverse=True)
            xlsx_file = files[0]
            files_to_delete.append(xlsx_file)
            logger.info(f"[CNN][DB] {table_name}: reading {os.path.basename(xlsx_file)}")
            headers, data = read_xlsx(xlsx_file)

        logger.info(f"[CNN][DB] {table_name}: {len(data)} rows, {len(headers)} cols")

        key_cols = detect_key_cols(headers)
        if not key_cols:
            raise Exception(f"[CNN][DB] {table_name}: 缺少 Begin Time 列，解析失败")
        if not data:
            raise Exception(f"[CNN][DB] {table_name}: 解析后无数据行")
        logger.info(f"[CNN][DB] {table_name}: 主键列 = {key_cols}")

        # 校验所选主键在当批数据内是否唯一；不唯一则尝试扩展，再不行报错（避免 upsert 静默塌缩）
        if not _cols_unique(headers, data, key_cols):
            logger.warning(f"[CNN][DB] {table_name}: 自然主键 {key_cols} 在数据中不唯一，尝试扩展")
            for cand in headers:
                if cand in key_cols:
                    continue
                expanded = key_cols + [cand]
                if _cols_unique(headers, data, expanded):
                    logger.warning(f"[CNN][DB] {table_name}: 主键扩展为 {expanded}")
                    key_cols = expanded
                    break
            else:
                raise Exception(
                    f"[CNN][DB] {table_name}: 无法凑出唯一主键(自然键={key_cols!r})，"
                    f"放弃 upsert 以免数据塌缩。请检查导出表结构。"
                )

        # 通过 API 写入
        if _db_writer is not None:
            try:
                str_data = []
                key_idx = [headers.index(k) for k in key_cols if k in headers]
                for row in data:
                    if len(row) < len(headers):
                        row.extend([None] * (len(headers) - len(row)))
                    elif len(row) > len(headers):
                        row = row[:len(headers)]
                    clean_row = [str(v) if v is not None else None for v in row]
                    # 主键列空值填 ""，避免服务端建表时 NOT NULL 主键写入失败
                    for i in key_idx:
                        if clean_row[i] is None:
                            clean_row[i] = ""
                    str_data.append(clean_row)

                result = _db_writer.write_data(
                    db=DB_NAME,
                    table=table_name,
                    columns=headers,
                    rows=str_data,
                    mode="upsert",
                    pk_columns=key_cols,
                )
                row_count = result.get("rows_written", 0)
                if row_count == 0:
                    # 数据已存在/已同步（upsert 后无新增行），不视为失败
                    logger.info(f"[CNN][DB][API] {table_name}: 无新增行（数据已存在/已同步）")
                else:
                    logger.info(f"[CNN][DB][API] {table_name}: written {row_count} rows")
            except Exception as e:
                raise Exception(f"[CNN][DB][API] {table_name}: 写入失败: {e}")
        else:
            raise Exception(f"[CNN][DB] db_writer 不可用，无法写入 {table_name}")

        total_imported += row_count
        headers = data = None
        gc.collect()

    # 清理磁盘残留（仅回退模式）
    for fpath in files_to_delete:
        try:
            os.remove(fpath)
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] import_to_database: exception swallowed", exc_info=True)
            pass

    logger.info(f"[CNN][DB] 导入完成，总计 {total_imported} 行")
    return total_imported


# ============================================================
# 单任务执行
# ============================================================
def _run_single_kpi_query(auth: dict, task: dict, start_index: int = 0) -> tuple:
    """执行单个 KPI 查询 + 导出，返回 (file_prefix, xlsx_bytes) 内存数据。"""
    monthly = task.get("monthly", False)
    cfg = CNN_KPI_MONTHLY_QUERY_CONFIGS[task["key"]] if monthly else CNN_KPI_QUERY_CONFIGS[task["key"]]
    file_prefix = build_filename(cfg)

    delay = start_index * 0.8
    if delay > 0:
        time.sleep(delay)

    logger.info(f"[CNN] Starting: {cfg['templatename']} (gr={cfg['gr']})")
    payload = build_cnn_kpi_payload(cfg, monthly=monthly)
    cookie = auth["cookie"]
    forgery_token = auth["forgery_token"]

    queryid = create_history_query(cookie, forgery_token, payload)
    wait_history_ready(cookie, forgery_token, queryid)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{file_prefix}_{timestamp}"
    xlsx_bytes = export_history(cookie, forgery_token, queryid, filename)

    return file_prefix, xlsx_bytes


# ============================================================
# 主入口
# ============================================================
def run_cnn_kpi_sync() -> dict:
    """CNN UME KPI 同步主流程：登录 → 并行查询 → 导出 → API 写入 DB CNN。"""
    t_start = time.time()
    result = {"success": False, "tables": {}, "errors": [], "elapsed_seconds": 0}

    logger.info(f"[CNN] KPI sync started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"[CNN] Tasks: {len(CNN_KPI_TASKS) + len(CNN_KPI_MONTHLY_TASKS)} "
                f"({len(CNN_KPI_TASKS)} daily + {len(CNN_KPI_MONTHLY_TASKS)} monthly), Workers: {MAX_PARALLEL_WORKERS}")

    try:
        # 1. 登录
        auth = _login()

        # 2. 并行查询（全程内存，不落盘；日/时粒度 + 1 个月粒度同时执行）
        all_tasks = CNN_KPI_TASKS + CNN_KPI_MONTHLY_TASKS
        export_data = {}  # {file_prefix: xlsx_bytes}
        errors = []
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
            future_to_task = {}
            for idx, task in enumerate(all_tasks):
                future = executor.submit(_run_with_cleanup, _run_single_kpi_query, auth, task, idx)
                future_to_task[future] = task

            for future in as_completed(future_to_task):
                task = future_to_task[future]
                task_label = f"{task['key']}[M]" if task.get("monthly") else task["key"]
                try:
                    file_prefix, xlsx_bytes = future.result()
                    export_data[file_prefix] = xlsx_bytes
                    logger.info(f"[CNN] [{task_label}] exported: {len(xlsx_bytes)} bytes (in-memory)")
                except Exception as e:
                    errors.append(f"[{task_label}] {e}")
                    logger.error(f"[CNN] [{task_label}] failed: {e}")

        result["errors"] = errors

        # 3. 数据库导入（API 写入，直接从内存读取）
        if export_data:
            total_rows = import_to_database(export_results=export_data)
            result["total_rows"] = total_rows
        else:
            logger.warning("[CNN] No data exported, skip database import.")
            result["total_rows"] = 0

        result["success"] = len(errors) == 0

    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"[CNN] Task failed: {e}")

    elapsed = time.time() - t_start
    result["elapsed_seconds"] = round(elapsed, 2)
    logger.info(f"[CNN] KPI sync done: {result.get('total_rows', 0)} rows, {elapsed:.2f}s")
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
    t0 = time.time()
    res = run_cnn_kpi_sync()
    print(f"\nCNN UME KPI 结果: {'成功' if res['success'] else '失败'}")
    if res['errors']:
        print(f"错误: {res['errors']}")
    print(f"耗时: {res['elapsed_seconds']}s")
