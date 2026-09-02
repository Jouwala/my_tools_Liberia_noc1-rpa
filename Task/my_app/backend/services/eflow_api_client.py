"""
eFlow API Client - 集成版
直接从 ZTE 网管系统 eFlow API 获取 TT/WO/CR/PM/Site/Person/RealtimeAlarm 数据
使用原始 socket + SSL（绕过 requests/urllib3 的 TLS 兼容问题）
"""
import ssl
import socket
import json
import io
import time
import re
import base64
import uuid
import logging
import gzip
import os
import random
import glob
import shutil
import csv
from pathlib import Path
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import ftplib
from backend.database import get_raw_connection

logger = logging.getLogger("eflow_api")

# ========== 连接配置 ==========
HOST = os.environ.get("EFLOW_HOST", "10.100.20.8")
PORT = int(os.environ.get("EFLOW_PORT", "28001"))
USERNAME = os.environ.get("EFLOW_USER", "admin")
PASSWORD = os.environ.get("EFLOW_PASS", "Brysj*8*")


def _runtime_credentials():
    """运行时获取凭据（环境变量 > 数据库 > 模块默认值），支持页面改密后免重启生效。"""
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        from credential_store import get_credential
    return get_credential("eflow", USERNAME, PASSWORD,
                          env_user="EFLOW_USER", env_secret="EFLOW_PASS")
MAX_PARALLEL_DOWNLOADS = max(1, int(os.environ.get("EFLOW_MAX_PARALLEL_DOWNLOADS", "6")))

# ========== 重试配置 ==========
HTTP_MAX_RETRIES = max(0, int(os.environ.get("EFLOW_HTTP_MAX_RETRIES", "3")))
HTTP_RETRY_DELAY = float(os.environ.get("EFLOW_HTTP_RETRY_DELAY", "1"))
HTTP_CONNECT_TIMEOUT = float(os.environ.get("EFLOW_CONNECT_TIMEOUT", "15"))
HTTP_READ_TIMEOUT = float(os.environ.get("EFLOW_READ_TIMEOUT", "90"))

# ========== FTP 配置 ==========
# FTP 主机/端口已统一收敛到 backend.config.remote_host（get_ftp_host / get_ftp_port），
# 由 eflow_data_mapper 连接时调用，避免硬编码、支持页面热更新。
FTP_USER = os.environ.get("FTP_USER", "FINEBI")
FTP_PASS = os.environ.get("FTP_PASS", "DX")
FTP_REMOTE_DIR = os.environ.get("FTP_REMOTE_DIR", "/Python")

# ========== API 路径 ==========
TT_API_PATH = "/api/eflow-ticket/v1/eflow-tt/base/list"
WO_API_PATH = "/api/eflow-wo/v1/eflow-wo/base/list"
CR_API_PATH = "/api/eflow-asset/v1/eflow-cr/base/list"
PM_API_PATH = "/api/eflow-pm/v1/eflow-pm-task/base/list"
SITE_API_PATH = "/api/cmdb/v1/data/search/Site"
PERSON_API_PATH = "/api/cmdb/v1/data/search/Person"

# ========== 外部化配置（Settings 页面可编辑的 eflow_config.json） ==========
# 优先级：环境变量 > 配置文件 > 内置默认。凭据由 credential_store / 凭据管理页签负责。
_EFLOW_CONF_PATH = Path(__file__).resolve().parent / "eflow_config.json"


def _load_eflow_config() -> dict | None:
    try:
        if _EFLOW_CONF_PATH.exists():
            with open(_EFLOW_CONF_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else None
    except Exception as e:
        logger.warning(f"读取 eflow_config.json 失败，使用内置默认: {e}")
    return None


_EFLOW_CONF = _load_eflow_config()
if _EFLOW_CONF is not None:
    if not os.environ.get("EFLOW_HOST"):
        HOST = _EFLOW_CONF.get("host", HOST)
    if not os.environ.get("EFLOW_PORT"):
        PORT = int(_EFLOW_CONF.get("port", PORT))
    if not os.environ.get("FTP_REMOTE_DIR"):
        FTP_REMOTE_DIR = _EFLOW_CONF.get("ftp_remote_dir", FTP_REMOTE_DIR)
    if not os.environ.get("EFLOW_CONNECT_TIMEOUT"):
        HTTP_CONNECT_TIMEOUT = float(_EFLOW_CONF.get("connect_timeout", HTTP_CONNECT_TIMEOUT))
    if not os.environ.get("EFLOW_READ_TIMEOUT"):
        HTTP_READ_TIMEOUT = float(_EFLOW_CONF.get("read_timeout", HTTP_READ_TIMEOUT))
    if not os.environ.get("EFLOW_HTTP_MAX_RETRIES"):
        HTTP_MAX_RETRIES = max(0, int(_EFLOW_CONF.get("max_retries", HTTP_MAX_RETRIES)))
    if not os.environ.get("EFLOW_DELTA_DAYS"):
        # 注意：EFLOW_DELTA_DAYS 定义在本块之后，这里用与内置默认一致的常量值
        EFLOW_DELTA_DAYS = max(1, int(_EFLOW_CONF.get("delta_days", 3)))
    if not os.environ.get("EFLOW_FULL_DAYS"):
        EFLOW_FULL_DAYS = max(0, int(_EFLOW_CONF.get("full_days", 0)))
    TT_API_PATH = _EFLOW_CONF.get("tt_api_path", TT_API_PATH)
    WO_API_PATH = _EFLOW_CONF.get("wo_api_path", WO_API_PATH)
    CR_API_PATH = _EFLOW_CONF.get("cr_api_path", CR_API_PATH)
    PM_API_PATH = _EFLOW_CONF.get("pm_api_path", PM_API_PATH)
    SITE_API_PATH = _EFLOW_CONF.get("site_api_path", SITE_API_PATH)
    PERSON_API_PATH = _EFLOW_CONF.get("person_api_path", PERSON_API_PATH)
    logger.info(f"[eFlow] 已加载 eflow_config.json: host={HOST}, delta={EFLOW_DELTA_DAYS}天")
ALARM_API_PATH = "/api/fm-active/v1/activealarms/table"
HIS_ALARM_API_PATH = "/api/fm-history/v1/hisalarms/pageinfo"

# ========== 数据目录 ==========
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "eflow")
os.makedirs(DATA_DIR, exist_ok=True)

# 仪表盘统一主库（GIS Map / RealTime Alarm Map / Alarm Dashboard 从此处读取）
APP_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "db", "app.db")

# ========== 小时报告与图片生成配置 ==========
TT_REPORT_SUBDIR = "tt_reports"          # 报告与图片输出子目录
SEND_EMAIL_AFTER_REPORT = False          # 是否在生成报告后发送邮件

# ========== 抓取时间窗口 ==========
# delta 模式（每小时）：只抓最近 N 天修改过的工单，配合增量写入保留历史
EFLOW_DELTA_DAYS = int(os.environ.get("EFLOW_DELTA_DAYS", "3"))
# full 模式（每日兜底）：0 = 自 2026-01-01 全量（保持原始语义），>0 = 最近 N 天
EFLOW_FULL_DAYS = int(os.environ.get("EFLOW_FULL_DAYS", "0"))

# eFlow TT 导出列名 -> mail_126.ExcelDataProcessor 期望列名
# 注意：Site Category 不再取 TT 自带的 Site Class（P1-P4 严重级别），
# 而是由 generate_hourly_report_with_images 步骤2.5 从 master_site_db.site_caregory 匹配填充
# 注意：eFlow 导出的 "TT No." 列实际包含的是关联的 WO 编号，不是真正的 TT 编号；
#       真正的 TT 编号在 tt_no 字段（由 generate_hourly_report_with_images 步骤2 从 tt_no 回填到 Ticket No.）
_TT_COLUMN_RENAME = {
    "Asset Name": "Site Name",
    "SLA Total Duration": "SLA Time",
    "Occurrence Time": "Alarm Occur Time",
    "Alarm Clearing Time": "Alarm Clear Time",
    "SLA Remaining Duration": "SLA Remain Time",
    #"TT No.": "Ticket No.",
}

# Site 表中作为 TX 值来源的列名（传输类型）
SITE_TX_SOURCE_COL = "TRM Type"

# ========== 会话状态 ==========
_session_cookie = ""
_forgery_token = ""
_http_local = threading.local()
# 401 自动重登录用：锁串行化登录（避免多线程同时登录互踢），代数用于并发线程
# 判断「是否已有其他线程刷新过会话」。
_auth_lock = threading.Lock()
_auth_generation = 0


# ========== SSL / HTTP 基础 ==========
def _create_ssl_socket():
    """Create one TLS connection. Connections are reused per worker thread."""
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


def _rebuild_auth_headers(headers_extra):
    """用当前最新会话重新生成 Cookie / forgerydefense 请求头。

    401 触发强制重登录后，原 headers_extra 里的 Cookie/forgerydefense 仍是旧会话
    的值，直接重试等于白试；此函数用新的 _session_cookie/_forgery_token 覆盖这两行。
    """
    if not headers_extra:
        return headers_extra
    headers_extra = re.sub(r"(?m)^Cookie: .*$", lambda m: f"Cookie: {_session_cookie}", headers_extra)
    headers_extra = re.sub(r"(?m)^forgerydefense: .*$", lambda m: f"forgerydefense: {_forgery_token}", headers_extra)
    return headers_extra


def _reauthenticate_on_401():
    """401 会话过期时强制重新登录；多线程并发只让一个线程真正登录，其余复用。"""
    global _auth_generation
    gen = _auth_generation
    with _auth_lock:
        if _auth_generation == gen:
            logger.warning("[AUTH] HTTP 401：会话已过期，强制重新登录")
            login(force_refresh=True)
        else:
            logger.info("[AUTH] HTTP 401：其他线程已刷新会话，直接复用新会话重试")


def _retry_delay(attempt: int) -> float:
    """Bounded exponential backoff with jitter, preventing retry bursts."""
    return min(20.0, HTTP_RETRY_DELAY * (2 ** attempt)) + random.uniform(0, 0.25)


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


def _chunked_complete(buf, start):
    """严格增量判断 chunked 响应体是否已收完（避免把数据内容误判为终止块）。

    按 chunk 边界逐个推进：`<hex-size>\r\n<data>\r\n` ... `0\r\n\r\n`。
    只有走到 size==0 且后面还有结尾 CRLF 才算完整，遇到半包返回 False。
    """
    pos, n = start, len(buf)
    while True:
        eol = buf.find(b"\r\n", pos)
        if eol == -1:
            return False
        try:
            size = int(buf[pos:eol].split(b";")[0].strip(), 16)
        except ValueError:
            return False
        pos = eol + 2
        if size == 0:
            # 终止块，后面至少还要有结尾 CRLF（trailer 场景此处先按 CRLF 判定）
            return n >= pos + 2
        if n < pos + size + 2:
            return False
        pos += size + 2


def _http_request(method, path, headers_extra=None, body=None, retry=0, _auth_retried=False):
    """
    发送 HTTP 请求，带重试机制。

    Args:
        retry: 内部使用，表示当前是第几次重试（不传则为首次）
        _auth_retried: 内部使用，标记是否已因 401 做过一次重登录重试
    """
    try:
        ssock = _get_thread_socket()
    except (ssl.SSLError, socket.timeout, ConnectionError, OSError) as e:
        if retry < HTTP_MAX_RETRIES:
            delay = HTTP_RETRY_DELAY * (2 ** retry)
            logger.warning(f"Socket connect failed (attempt {retry+1}/{HTTP_MAX_RETRIES+1}): {e}, retrying in {delay}s")
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
            delay = HTTP_RETRY_DELAY * (2 ** retry)
            logger.warning(f"Socket send failed (attempt {retry+1}/{HTTP_MAX_RETRIES+1}): {e}, retrying in {delay}s")
            time.sleep(delay)
            return _http_request(method, path, headers_extra=headers_extra, body=body, retry=retry + 1)
        raise

    # bytearray avoids quadratic copying for large ZIP/XLSX exports.
    response_data = bytearray()
    content_length = None
    header_end_found = False
    header_end_pos = 0
    is_chunked = False

    while True:
        try:
            chunk = ssock.recv(65536)
            if not chunk:
                break
            response_data.extend(chunk)
        except socket.timeout:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _http_request: exception swallowed", exc_info=True)
            break

        # 解析 Content-Length（首次收到数据后立即解析）
        if not header_end_found:
            pos = response_data.find(b"\r\n\r\n")
            if pos != -1:
                header_end_found = True
                header_end_pos = pos
                header_part = response_data[:pos].decode('utf-8', errors='replace')
                for line in header_part.split("\r\n"):
                    low = line.lower()
                    if low.startswith("content-length:"):
                        try:
                            content_length = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _http_request: exception swallowed", exc_info=True)
                            pass
                    elif low.startswith("transfer-encoding:") and "chunked" in low:
                        is_chunked = True

        # chunked 响应没有 Content-Length：按 chunk 边界判断是否已收完，
        # 避免一直 recv 到读超时（此前每个 chunked 请求都要空等 HTTP_READ_TIMEOUT 秒）。
        if header_end_found and content_length is None and is_chunked:
            if _chunked_complete(response_data, header_end_pos + 4):
                break

        # 如果已知 Content-Length 且已收满，提前退出
        if header_end_found and content_length is not None:
            body_data = response_data[header_end_pos + 4:]
            if len(body_data) >= content_length:
                break

    # Keep a fully read Content-Length response alive for the next request on
    # this worker.  Any incomplete or ambiguous response closes the socket.

    # Content-Length 预期与实际不符，视为部分数据
    if header_end_found and content_length is not None:
        body_data = response_data[header_end_pos + 4:]
        if len(body_data) < content_length:
            _close_thread_socket()
            raise ConnectionError(f"Response body truncated: {len(body_data)}/{content_length} bytes")

    header_end = response_data.find(b"\r\n\r\n")
    if header_end == -1:
        if retry < HTTP_MAX_RETRIES:
            delay = HTTP_RETRY_DELAY * (2 ** retry)
            logger.warning(f"Cannot parse HTTP response (attempt {retry+1}/{HTTP_MAX_RETRIES+1}), retrying in {delay}s")
            time.sleep(delay)
            return _http_request(method, path, headers_extra=headers_extra, body=body, retry=retry + 1)
        raise Exception("Cannot parse HTTP response")

    header_part = response_data[:header_end].decode('utf-8', errors='replace')
    resp_body = response_data[header_end + 4:]

    status_line = header_part.split("\r\n")[0]
    resp_headers = {}
    for line in header_part.split("\r\n")[1:]:
        if ": " in line:
            k, v = line.split(": ", 1)
            resp_headers[k.lower()] = v

    if "chunked" in resp_headers.get("transfer-encoding", ""):
        resp_body = _decode_chunked(resp_body)
        # Chunked framing has no Content-Length; do not reuse this connection.
        _close_thread_socket()
    elif "close" in resp_headers.get("connection", "").lower() or content_length is None:
        _close_thread_socket()

    # 401 = 会话过期：强制重新登录一次后，用新会话重建请求头重试。
    # （eFlow 会话有效期短，全量同步 8~22 分钟常在中途过期；此前无此处理，
    #   6 条并行管道全部 401 → fetch_all_data 返回空 → "API 未返回任何数据"）
    if "401" in status_line and not _auth_retried:
        _close_thread_socket()
        _reauthenticate_on_401()
        headers_extra = _rebuild_auth_headers(headers_extra)
        return _http_request(method, path, headers_extra=headers_extra, body=body,
                             retry=retry, _auth_retried=True)

    return status_line, resp_headers, header_part, resp_body


# ========== RSA 加密 ==========
def _rsa_encrypt_pem(plaintext, public_key_b64):
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives import serialization

    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
    public_key = serialization.load_pem_public_key(pem.encode())
    encrypted = public_key.encrypt(plaintext.encode('utf-8'), asym_padding.PKCS1v15())
    return base64.b64encode(encrypted).decode('ascii')


# ========== 登录认证 ==========
def login(force_refresh: bool = False):
    global _session_cookie, _forgery_token, _auth_generation

    try:
        try:
            from backend.services.auth_manager import get_auth
        except ImportError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] login: exception swallowed", exc_info=True)
            from auth_manager import get_auth
        # force_refresh=True：跳过 auth_manager 磁盘缓存（其仅按 TTL 判过期，
        # 服务器会话可能已死但未到 TTL），401 恢复时务必强制真实登录。
        result = get_auth(HOST, PORT, *_runtime_credentials(), force_refresh=force_refresh)
        source = "强制刷新" if force_refresh else ("缓存" if result["from_cache"] else "重新登录")
        logger.info(f"eFlow 鉴权成功（来源: {source}）")
        _session_cookie = result["cookie"]
        _forgery_token = result["forgery_token"]
        _auth_generation += 1
    except Exception as e:
        logger.error(f"eFlow auth_manager 失败: {e}")
        raise

    return _session_cookie


def get_session_headers():
    """返回当前会话 (cookie, forgery_token)（Phase 4：跨模块访问器，每次调用取最新值）。"""
    return _session_cookie, _forgery_token


def ensure_login():
    """确保会话已登录（Phase 4：跨模块会话访问器，避免子模块导入时绑定过期 cookie）。"""
    if not _session_cookie:
        login()
    return _session_cookie


def _headers_extra(referer):
    return (
        f"Cookie: {_session_cookie}\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Referer: {referer}\r\n"
        f"forgerydefense: {_forgery_token}\r\n"
        f"Content-Type: application/json\r\n"
        f"Origin: https://{HOST}:{PORT}\r\n"
    )


# ========== 响应解析 ==========
def parse_response(data, label=""):
    prefix = f"[{label}] " if label else ""
    if isinstance(data, dict):
        if data.get("code") not in (0, None, "0"):
            logger.warning(f"{prefix}API error code={data.get('code')}, msg={data.get('msg', '')[:100]}")
            return []
        rows = None
        for key in ("alarms", "result", "data", "records", "list", "rows", "items"):
            rows = data.get(key)
            if rows is not None:
                break
        else:
            rows = []
        if isinstance(rows, dict):
            nested_rows = None
            for key in ("data", "list", "records", "rows", "items", "result"):
                nested_rows = rows.get(key)
                if nested_rows is not None:
                    break
            rows = nested_rows if nested_rows is not None else rows
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    return rows if isinstance(rows, list) else []


def _safe_json_loads(resp_body, label=""):
    """
    安全解析 JSON，当 JSON 被截断时尝试恢复。
    返回 (parsed_dict_or_list, success_flag)
    """
    try:
        data = json.loads(resp_body)
        return data, True
    except json.JSONDecodeError as e:
        logger.warning(f"{label} JSON decode error: {e}, attempting recovery ({len(resp_body)} bytes)")
        # 尝试找到最后一个完整的对象/数组边界
        text = resp_body
        for char in ('}', ']'):
            last_pos = text.rfind(char)
            if last_pos > 0:
                try:
                    data = json.loads(text[:last_pos + 1])
                    logger.info(f"{label} JSON recovered by truncating at last '{char}'")
                    return data, True
                except json.JSONDecodeError:
                    logging.getLogger(__name__).warning("[SILENT-EXCEPT] _safe_json_loads: exception swallowed", exc_info=True)
                    continue
        logger.error(f"{label} JSON unrecoverable")
        return {}, False


# ========== 分页查询 ==========
def fetch_paginated_data(api_path, payload_base, referer, label, page_param="start", size_param="length"):
    logger.info(f"Fetching {label} data...")
    start_time = time.time()

    all_rows = []
    total = None
    page_size = payload_base.get(size_param, 2000)
    start = 0

    headers_extra = _headers_extra(referer)

    while True:
        payload = dict(payload_base)
        payload[size_param] = page_size
        payload[page_param] = start

        body = json.dumps(payload)
        status_line, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", api_path, headers_extra=headers_extra, body=body,
        )

        data = json.loads(resp_body.decode('utf-8'))

        if isinstance(data, list):
            rows = data
            all_rows.extend(rows)
            if len(rows) < page_size:
                break
            start += page_size
            continue

        if not isinstance(data, dict):
            break

        if data.get("code") not in (0, None, "0"):
            logger.warning(f"{label} API error: {data.get('msg', '')[:100]}")
            break

        if total is None:
            total = data.get("total", 0)
            logger.info(f"{label} total records: {total}")

        rows = parse_response(data, label=label)
        all_rows.extend(rows)

        if len(all_rows) >= total or len(rows) < page_size:
            break
        start += page_size
        if start >= total:
            break

    elapsed = time.time() - start_time
    logger.info(f"{label}: {len(all_rows)} records in {elapsed:.2f}s")
    return all_rows


# ========== TT / WO / CR / PM 查询配置 ==========


def _get_time_range_ms(days_back: int | None = None):
    """返回查询起止毫秒时间戳。

    days_back: None 或省略 -> 使用 delta 窗口（EFLOW_DELTA_DAYS）
               0      -> 自 2026-01-01 全量（保持原始语义）
               >0     -> 最近 N 天
    """
    if days_back is None:
        days_back = EFLOW_DELTA_DAYS
    end_dt = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
    if days_back and days_back > 0:
        start_dt = (end_dt - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start_dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)


# ========== 导出流水线函数 ==========


# ========== 导出通用函数 ==========
def _create_export_task(async_path, referer, payload, label):
    """创建异步导出任务，返回 (ftp_file_path, file_name)"""
    headers_extra = _headers_extra(referer)
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request("POST", async_path, headers_extra=headers_extra, body=body)

    if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
        try:
            resp_body = gzip.decompress(resp_body)
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _create_export_task: exception swallowed", exc_info=True)
            pass

    ftp_file_path = ""
    file_name = payload.get("fileName", "")
    if "200" in status:
        try:
            resp_data = json.loads(resp_body.decode('utf-8'))
            if isinstance(resp_data, dict):
                ftp_file_path = resp_data.get("ftpFilePath", "")
                if not ftp_file_path and isinstance(resp_data.get("data"), dict):
                    ftp_file_path = resp_data["data"].get("ftpFilePath", "")
        except Exception as e:
            logger.warning(f"{label} export async parse failed: {e}")
    logger.info(f"{label} export task created: {file_name}, ftp={ftp_file_path}")
    return ftp_file_path, file_name


def _wait_export_ready(list_path, referer, file_name, label, max_wait=300, interval=10):
    """轮询等待导出完成，返回 (ftp_path, item)"""
    headers_extra = _headers_extra(referer)
    body = json.dumps({})

    for attempt in range(max_wait // interval):
        status, hdrs, raw_hdrs, resp_body = _http_request("POST", list_path, headers_extra=headers_extra, body=body)

        if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
            try:
                resp_body = gzip.decompress(resp_body)
            except Exception:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _wait_export_ready: exception swallowed", exc_info=True)
                pass

        try:
            data = json.loads(resp_body.decode('utf-8'))
            items = data if isinstance(data, list) else data.get("result", data.get("data", []))
            for item in items:
                item_file_name = item.get("fileName", "")
                if file_name in item_file_name or item_file_name == file_name:
                    status_str = item.get("status", "")
                    uuid_val = item.get("uuid", "")
                    rate = item.get("rate", "")
                    if status_str.lower() in ("success", "sucess") or rate == "100%":
                        ftp_path = item.get("ftpFilePath", "")
                        if not ftp_path and uuid_val:
                            ftp_path = f"{uuid_val}.zip"
                        return ftp_path, item
        except Exception:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] _wait_export_ready: exception swallowed", exc_info=True)
            pass

        logger.info(f"{label} waiting export... ({attempt + 1}/{max_wait // interval})")
        time.sleep(interval)

    return "", None


def _download_export_zip(download_path, referer, file_name, ftp_file_path, table_type, label, output_dir):
    """下载导出的 ZIP 文件"""
    headers_extra = _headers_extra(referer)
    file_name_body = file_name if file_name.endswith(".zip") else f"{file_name}.zip"
    ftp_path_body = ftp_file_path if ftp_file_path.endswith(".zip") else f"{ftp_file_path}.zip"
    body_payload = {"fileName": file_name_body, "tableType": table_type}
    if ftp_file_path:
        body_payload["ftpFilePath"] = ftp_path_body

    body = json.dumps(body_payload)
    status, hdrs, raw_hdrs, resp_body = _http_request("POST", download_path, headers_extra=headers_extra, body=body)

    if "200" not in status:
        raise Exception(f"{label} download failed: {status}")

    filename = file_name if file_name.endswith(".zip") else f"{file_name}.zip"
    cd = hdrs.get("content-disposition", "")
    if cd:
        fn_match = re.search(r'filename=["\']?([^"\';]+)', cd)
        if fn_match:
            filename = fn_match.group(1)

    zip_path = os.path.join(output_dir, filename)
    seq = 1
    while os.path.exists(zip_path):
        base, ext = os.path.splitext(filename)
        zip_path = os.path.join(output_dir, f"{base}_{seq}{ext}")
        seq += 1

    with open(zip_path, "wb") as f:
        f.write(resp_body)
    logger.info(f"{label} ZIP saved: {zip_path}")
    return zip_path


def _read_export_zip(zip_path, label):
    """读取导出 ZIP 中的数据文件，返回 records list"""
    import zipfile
    import pandas as pd

    with zipfile.ZipFile(zip_path, "r") as z:
        files = z.namelist()

    data_files = [f for f in files if f.lower().endswith((".xlsx", ".xls", ".csv"))]
    if not data_files:
        raise Exception(f"No data file found in {label} ZIP")

    read_start = time.time()
    dfs = []
    with zipfile.ZipFile(zip_path, "r") as z:
        for data_file in data_files:
            # Parse directly from the archive: much less disk I/O and no
            # extract-directory contention when all pipelines finish together.
            content = io.BytesIO(z.read(data_file))
            if data_file.lower().endswith(".csv"):
                dfs.append(pd.read_csv(content))
            else:
                dfs.append(pd.read_excel(content))

    df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    logger.info(f"{label}: {len(df)} rows, {len(df.columns)} columns (read {time.time() - read_start:.2f}s)")

    return df.to_dict("records")


def _set_export_columns(userhabits_path, referer, export_config, label):
    """设置导出列配置"""
    headers_extra = _headers_extra(referer)
    body = json.dumps(export_config)
    status, _, _, _ = _http_request("POST", userhabits_path, headers_extra=headers_extra, body=body)
    logger.info(f"{label} set export columns: {status}")


def _prepare_export(api_path, referer, payload, label):
    """预查询以激活导出"""
    headers_extra = _headers_extra(referer)
    body = json.dumps(payload)
    status, _, _, _ = _http_request("POST", api_path, headers_extra=headers_extra, body=body)
    logger.info(f"{label} prepare export: {status}")


# ========== 各端点导出流水线 ==========


# ========== Realtime / History Alarm ==========

# 历史告警抓取窗口（小时）。若设置则用"滚动窗口 now-H小时~now"，避免按天边界造成的整日重叠重抓；
# 未设置(<=0)则回退到按天窗口（HIS_ALARM_DAYS_BACK）。默认 48h：覆盖每日 cron 间隔 + TT ID 晚绑定缓冲。
# （C：缩小/滚动窗口。配合 B 的 upsert 累积，旧数据保留、只抓增量）


# ========== 告警数据持久化 ==========


# ========== 告警数据持久化 ==========


# ========== 历史告警数据持久化 ==========


# ========== 告警写入仪表盘主库 db/app.db ==========


# ========== 告警独立入口 ==========


# ========== Excel 写入工具 ==========


# 远端 FB 表兼容列别名：查看器/报表期望的列名 -> 原始导出列名（按顺序取第一个存在的列）
# 保证远端 Eflow_TT_FB / Eflow_WO_FB 同时包含原始列和这些加工列名，取值相同。


# ============================================================
# 小时报告与图片生成（复用 mail_126.py 的方法）
# ============================================================




# mail_126.py 所在目录（项目内部 backend/services/report/）


# ============================================================
# 主入口：获取数据后生成 Hourly Report / Summary Report / 图片
# ============================================================





# ========== 主入口 ==========


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] <module:eflow_api_client>: exception swallowed", exc_info=True)
        pass

    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')

    # Phase 4 拆分：入口函数已迁移至子模块（模块内全局名不走 __getattr__，需显式导入）
    try:
        from backend.services.eflow_alarm_service import (
            fetch_and_save_active_alarm, fetch_and_save_history_alarm, fetch_and_save_alarm_data,
        )
        from backend.services.eflow_data_mapper import fetch_all_data, generate_excel_report
    except ImportError:
        from eflow_alarm_service import (
            fetch_and_save_active_alarm, fetch_and_save_history_alarm, fetch_and_save_alarm_data,
        )
        from eflow_data_mapper import fetch_all_data, generate_excel_report

    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode == "active_alarm":
        t0 = time.time()
        result = fetch_and_save_active_alarm()
        print(f"Active alarm: {len(result['realtime_alarm'])} records")
        print(f"Total: {time.time() - t0:.2f}s")
    elif mode == "history_alarm":
        t0 = time.time()
        result = fetch_and_save_history_alarm()
        print(f"History alarm: {len(result['history_alarm'])} records")
        print(f"Total: {time.time() - t0:.2f}s")
    elif mode == "alarm":
        t0 = time.time()
        result = fetch_and_save_alarm_data()
        print(f"Active alarm: {len(result['realtime_alarm'])} records")
        print(f"History alarm: {len(result['history_alarm'])} records")
        print(f"Total: {time.time() - t0:.2f}s")
    elif mode == "report":
        t0 = time.time()
        # 解析可选参数：python eflow_api_client.py report [upload]
        upload_to_ftp_flag = len(sys.argv) > 2 and sys.argv[2] == "upload"
        result = generate_excel_report(upload_ftp=upload_to_ftp_flag)
        print(f"\n=== Excel Report Summary ===")
        print(f"  SQLite DB: {result.get('db_path')}")
        print(f"  Excel:     {result.get('excel_path')}")
        print(f"  Sheets:    {len(result.get('sheets', {}))}")
        for name, count in result.get('sheets', {}).items():
            print(f"    - {name}: {count} rows")
        if result.get('upload_success'):
            print(f"  FTP:       uploaded OK")
        print(f"\nTotal: {time.time() - t0:.2f}s")
    else:
        t0 = time.time()
        data = fetch_all_data()
        print(f"\n=== Data Fetch Summary ===")
        for name, rows in data.items():
            print(f"  {name}: {len(rows)} rows")
        print(f"\nTotal: {time.time() - t0:.2f}s")

        # 同时生成 Excel 报告（使用已有数据，即使部分管道失败）
        report_t0 = time.time()
        print(f"\n--- Generating Excel report ---")
        report = generate_excel_report(data=data, upload_ftp=False)
        print(f"  SQLite DB: {report.get('db_path')}")
        print(f"  Excel:     {report.get('excel_path')}")
        print(f"  Report time: {time.time() - report_t0:.2f}s")


# ========== Phase 4 拆分兼容层（PEP 562 惰性重导出） ==========
# 以下入口函数已迁移至子模块；旧导入路径（from <本模块> import X）通过
# 模块级 __getattr__ 惰性解析，避免顶层互相导入造成循环依赖。
_PHASE4_SPLITS = {
    "fetch_all_data": "eflow_data_mapper",
    "save_to_sqlite": "eflow_data_mapper",
    "write_excel_from_sqlite": "eflow_data_mapper",
    "cleanup_old_export_files": "eflow_data_mapper",
    "upload_to_ftp": "eflow_data_mapper",
    "upload_tt_reports_to_ftp": "eflow_data_mapper",
    "generate_and_upload_fb_excel": "eflow_data_mapper",
    "load_report_data_from_db": "eflow_data_mapper",
    "generate_hourly_report_with_images": "eflow_data_mapper",
    "generate_excel_report": "eflow_data_mapper",
    "fetch_and_save_active_alarm": "eflow_alarm_service",
    "fetch_and_save_history_alarm": "eflow_alarm_service",
    "fetch_and_save_alarm_data": "eflow_alarm_service",
    # 常量/辅助（tests/test_all_apis.py 等以 api.X 属性方式访问，同样走惰性重导出）
    "TIME_FILTER_TEMPLATE": "eflow_data_mapper",
    "TT_REFERER": "eflow_data_mapper",
    "TT_FIELDS": "eflow_data_mapper",
    "TT_STATUS_FILTER": "eflow_data_mapper",
    "WO_REFERER": "eflow_data_mapper",
    "WO_FIELDS": "eflow_data_mapper",
    "WO_STATUS_FILTER": "eflow_data_mapper",
    "CR_REFERER": "eflow_data_mapper",
    "CR_FIELDS": "eflow_data_mapper",
    "CR_STATUS_FILTER": "eflow_data_mapper",
    "PM_REFERER": "eflow_data_mapper",
    "PM_FIELDS": "eflow_data_mapper",
    "PM_STATUS_FILTER": "eflow_data_mapper",
    "SITE_ASYNC_PATH": "eflow_data_mapper",
    "SITE_REFERER": "eflow_data_mapper",
    "PERSON_ASYNC_PATH": "eflow_data_mapper",
    "PERSON_REFERER": "eflow_data_mapper",
    "ALARM_REFERER": "eflow_alarm_service",
    "ALARM_CONDITION": "eflow_alarm_service",
    "HIS_ALARM_CONDITION": "eflow_alarm_service",
    "_get_his_alarm_time_range": "eflow_alarm_service",
}


def __getattr__(name):
    target = _PHASE4_SPLITS.get(name)
    if target is not None:
        import importlib
        pkg = f"{__package__}.{target}" if __package__ else target
        return getattr(importlib.import_module(pkg), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
