# -*- coding: utf-8 -*-
"""
CNN UME KPI 数据获取脚本（Core Network - xGW License Occupancy）

功能：
1. 登录 ZTE CNN UME 网管系统（https://10.121.1.2:28808/em-portal），获取鉴权 Cookie 与 forgery token。
2. 创建 xGW License Occupancy 历史指标查询任务（ME 级，小时粒度 gr=3600）。
3. 轮询查询进度直到完成，导出为 Excel 文件。
4. 将导出的 xlsx 导入 SQLite 数据库（以 Begin Time + 元素标识列为联合主键，INSERT OR REPLACE）。
5. 上传数据库到 FTP /01_RPA/LBR_Tools/KPI/CNN。
6. 清理本地 xlsx 文件。

参考：
- ran_network_kpi_zs.py：登录 / 查询 / 轮询 / 导出流程（同一套 ZTE UME PM 接口）
- ran_daily_kpi.py：数据库导入流程（INSERT OR REPLACE 去重）
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
import openpyxl
from ftplib import FTP, error_perm
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# 强制 UTF-8 输出（修复 Windows CMD 中文编码问题）
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# ============================================================
# 配置
# ============================================================
HOST = "10.121.1.2"
PORT = 28808
USERNAME = "oss"
PASSWORD = "Mwebazeaaron@25"
LOGIN_PORTAL = "/em-portal"

# 脚本目录与输出目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

# 查询时间范围：固定为 1 个自然月（如今天 2026-07-26 → start 2026-06-26, end 2026-07-26）
# 可通过环境变量 CNN_KPI_MONTHS_BACK 覆盖（默认 1 个月）
MONTHS_BACK = int(os.environ.get("CNN_KPI_MONTHS_BACK", "1"))

# 并行查询线程数
MAX_PARALLEL_WORKERS = int(os.environ.get("CNN_KPI_PARALLEL_WORKERS", "4"))

# PM 接口路径（与 ran_network_kpi_zs.py 完全一致）
HISTORY_PATH = "/api/pm-analysis/v2/history"
HISTORY_POLL_PATH = "/api/pm-analysis/v1/history"
HISTORY_EXPORT_PATH = "/api/pm-analysis/v3/history/export"
HISTORY_REFERER = f"https://{HOST}:{PORT}/em-portal"

# 数据库配置（db_ps_cs_cn.sqlite3，与脚本同目录）
DB_NAME = "db_ps_cs_cn.sqlite3"
DB_PATH = os.path.join(SCRIPT_DIR, DB_NAME)

# FTP 上传配置（目标数据库）
FTP_HOST = "192.168.100.19"
FTP_USER = "ZTEEMS"
FTP_PASS = "DX"
FTP_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI/CNN"

# 标识列候选（用于联合主键去重）。按优先级排序，自动检测实际导出中包含哪些。
# 不同模板的导出包含不同标识列：
#   xGW_LICENSE/xGW_CPU_USAGE: Begin Time + NE
#   VOICE_TRAFFIC/VLR_SUBSCRIBERS/DATA_SUBSCRIBERS: Begin Time + NE + SERVICE
#   3G_FDD/4G_FDD/FREE_RATING_GROUP: Begin Time + NE + SERVICE + Measurement Object
IDENTITY_COL_CANDIDATES = ["NE", "SERVICE", "Measurement Object"]

# gr 显示名称替换规则（来自 Payload.txt）
GR_RENAME = {
    "3600": "1Hour",
    "86400": "1Day",
    "2592000": "1Month",
}

# grouplayer 替换规则（来自 Payload.txt）
# 用于文件命名中的 layer 部分。未命中的 grouplayer 值原样保留。
# 注意：me,fservice,* (3 段及以上) 统一映射为 NE（用户确认）
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
# KPI 查询配置（从 Payload.txt 提取，共 8 个模板）
# 字段顺序与 Payload 严格一致（ZTE 接口对字段顺序敏感）
# table_name 对应 db_ps_cs_cn.sqlite3 中既有的 UME 表
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
        # Payload.txt 中 FREE_RATING_GROUP 无 invaliditems 字段
        "invaliditems": None,
        "table_name": "FREE_RATING_GROUP_TEMPLATE_OSS_update_UME",
    },
}

# 任务列表（8 个 KPI 模板）
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
# HTTP / SSL 工具函数（复用 ran_network_kpi_zs.py 实现）
# ============================================================
def _create_ssl_socket():
    """创建绕过证书校验的 TLS socket（绕过 ZTE UME 的 TLS 兼容性问题）。"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers('ALL:@SECLEVEL=0')
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30)
    ssock = ctx.wrap_socket(sock)
    ssock.connect((HOST, PORT))
    return ssock


def _decode_chunked(data):
    """解码 HTTP chunked 响应体。"""
    result = b""
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
        result += data[pos:pos + chunk_size]
        pos += chunk_size + 2
    return result


def _http_request(method, path, headers_extra=None, body=None):
    """发送原始 HTTP 请求并返回状态行、响应头字典、原始头文本和响应体字节。"""
    ssock = _create_ssl_socket()

    headers = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: {HOST}:{PORT}\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Language: en-US,en;q=0.9\r\n"
        f"Accept-Encoding: identity\r\n"
        f"Connection: close\r\n"
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

    ssock.sendall(request_bytes)

    response_data = b""
    while True:
        try:
            chunk = ssock.recv(65536)
            if not chunk:
                break
            response_data += chunk
        except socket.timeout:
            break
    ssock.close()

    header_end = response_data.find(b"\r\n\r\n")
    if header_end == -1:
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


def _auth_headers(cookie: str, forgery_token: str, extra: dict = None) -> str:
    """构造 PM 接口需要的鉴权请求头。"""
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
                    print(f"[HTTP] {status} on {path}, retrying in {wait_sec}s "
                          f"(attempt {attempt + 1}/{max_retries + 1})...")
                    time.sleep(wait_sec)
                    continue
            return status, hdrs, raw_hdrs, resp_body
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                wait_sec = 2 ** attempt
                print(f"[HTTP] Request failed: {e}, retrying in {wait_sec}s "
                      f"(attempt {attempt + 1}/{max_retries + 1})...")
                time.sleep(wait_sec)
            else:
                break

    raise last_exception or Exception(f"HTTP request failed after {max_retries + 1} attempts")


# ============================================================
# 登录
# ============================================================
def login():
    """执行 CNN UME 登录流程，返回包含 cookie 和 forgery_token 的字典。

    流程：
    1. GET /api/oauth2/v1/authorize（redirect_uri=/em-portal）获取初始 cookie 与 forgery token
    2. GET /api/oauth2/v1/login/publickey 获取 RSA 公钥
    3. RSA 加密密码
    4. POST /api/oauth2/v1/login_rsa 提交登录
    """
    print("[LOGIN] Starting authentication...")
    session_cookie = ""
    forgery_token = ""

    try:
        print("[LOGIN] Step 1: Getting authorize page...")
        status, hdrs, raw_hdrs, body = _http_request(
            "GET",
            f"/api/oauth2/v1/authorize?scope=user.login&response_type=code"
            f"&redirect_uri={LOGIN_PORTAL}"
        )
        print(f"[LOGIN] Status: {status}")

        init_cookies = []
        for line in raw_hdrs.split("\r\n"):
            if line.lower().startswith("set-cookie:"):
                cookie_val = line.split(": ", 1)[1].split(";")[0]
                if cookie_val.split("=", 1)[-1]:
                    init_cookies.append(cookie_val)
                    if "forgerydefense" in cookie_val:
                        forgery_token = cookie_val.split("=", 1)[1]

        init_cookie_str = "; ".join(init_cookies)
        print(f"[LOGIN] Got {len(init_cookies)} cookies")

        html = body.decode('utf-8', errors='replace')
        lp_match = re.search(r'var\s+loginParameters\s*=\s*["\']([^"\']+)["\']', html)
        login_parameters = lp_match.group(1) if lp_match else ""
        print(f"[LOGIN] Got loginParameters ({len(login_parameters)} chars)")

        print("[LOGIN] Step 2: Getting RSA public key from API...")
        rsa_headers = f"Cookie: {init_cookie_str}\r\nX-Requested-With: XMLHttpRequest\r\n"
        status, hdrs, raw_hdrs, body = _http_request(
            "GET", "/api/oauth2/v1/login/publickey",
            headers_extra=rsa_headers,
        )
        print(f"[LOGIN] Public key API status: {status}")

        public_key_b64 = ""
        if "200" in status:
            pk_data = json.loads(body.decode('utf-8'))
            public_key_b64 = pk_data.get("rsaPublicKey", "")
            print(f"[LOGIN] Got rsaPublicKey ({len(public_key_b64)} chars)")
        else:
            print("[LOGIN] API failed, public key unavailable")

        if not public_key_b64:
            raise Exception("无法获取 RSA 公钥，登录中止")

        print("[LOGIN] Step 3: Encrypting password with RSA...")
        encrypted_pwd = _rsa_encrypt_pem(PASSWORD, public_key_b64)
        print(f"[LOGIN] Encrypted ({len(encrypted_pwd)} chars)")

        print("[LOGIN] Step 4: Submitting login...")
        login_payload = json.dumps({
            "username": USERNAME,
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
            headers_extra=login_headers,
            body=login_payload,
        )
        print(f"[LOGIN] Login status: {status}")

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

        # 登录成功判定：302 跳转 / 响应包含 portal / 拿到 Z-AUTH-CODE / cookie 数量充足
        success = (
            "302" in status
            or "em-portal" in resp_text
            or "default.html" in resp_text
            or any("Z-AUTH-CODE" in c for c in cookies)
            or len(cookies) > 3
        )
        if success:
            print(f"[LOGIN] SUCCESS - {len(cookies)} cookies")
        else:
            print(f"[LOGIN] Response: {resp_text[:300]}")
            raise Exception("登录失败 - 未获取到鉴权 Cookie")

        print(f"[LOGIN] Cookie: {session_cookie[:100]}...")

    except Exception as e:
        print(f"[LOGIN] FAILED: {e}")
        raise

    return {"cookie": session_cookie, "forgery_token": forgery_token}


# ============================================================
# Payload 构造（字段顺序与用户提供的 Payload 严格一致）
# ============================================================
def _subtract_months(dt, months):
    """从 datetime 中减去指定自然月数，日溢出时钳制到月末。
    例: 2026-07-26 - 1 month = 2026-06-26；2026-03-31 - 1 month = 2026-02-28。
    """
    import calendar
    year = dt.year
    month = dt.month - months
    while month < 1:
        month += 12
        year -= 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def build_cnn_kpi_payload(cfg: dict, start_iso: str = None, end_iso: str = None) -> dict:
    """构造 CNN KPI 历史指标查询 Payload。"""
    now = datetime.now(timezone.utc)
    if end_iso is None:
        end_iso = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if start_iso is None:
        # 固定 1 个自然月（如 2026-07-26 → 2026-06-26）
        start_dt = _subtract_months(now.replace(hour=0, minute=0, second=0, microsecond=0), MONTHS_BACK)
        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    timeinfo = {
        "mode": 1,
        "start": start_iso,
        "end": end_iso,
        "relative": -1,
        "timezonetype": "1",
        "clienttimezone": "Atlantic/Reykjavik",
        "showtimezoneoffset": False,
        "querylongtime": {"type": 0, "value": 1},
        "timespanfilter": "00:00:00-24:00:00",
        "dayfiltertype": 0,
        "dayinmonthfilter": "1111111111111111111111111111111",
    }

    # 严格按 Payload.txt 字段顺序构造（ZTE 接口对字段顺序敏感）
    # 使用 list of tuples 保证 JSON 序列化时的字段顺序
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
        ("uilocations", []),  # Payload.txt 中均为空数组
        ("reslocation", []),
    ]

    # groupchoice 仅 DATA_SUBSCRIBERS 有，位于 reslocation 之后、inexistenceres 之前
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

    # invaliditems 位于最后（FREE_RATING_GROUP 在 Payload.txt 中无此字段）
    if cfg.get("invaliditems") is not None:
        fields.append(("invaliditems", cfg["invaliditems"]))

    # 转为有序 dict（Python 3.7+ dict 保持插入顺序）
    payload = dict(fields)
    return payload


# ============================================================
# KPI 查询 / 轮询 / 导出
# ============================================================
def create_history_query(cookie: str, forgery_token: str, payload: dict) -> str:
    """创建 KPI 历史指标查询任务，返回 queryid。"""
    print(f"[KPI] Creating: {payload.get('favoriteconditionname')} / gr={payload.get('gr')}")
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

    if "200" not in status:
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
    headers = _auth_headers(cookie, forgery_token)

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


def _extract_xlsx_bytes(resp_bytes):
    """CNN 导出接口返回 ZIP 包裹的 xlsx（PK 头但内层才是真正的 xlsx）。
    本函数检测并解包，返回真正的 xlsx 字节。若非 ZIP 则原样返回。
    """
    if len(resp_bytes) < 4 or resp_bytes[:2] != b'PK':
        return resp_bytes
    try:
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(resp_bytes))
        # 优先查找 .xlsx 条目
        xlsx_names = [n for n in z.namelist() if n.lower().endswith('.xlsx')]
        if len(xlsx_names) >= 1:
            inner = z.read(xlsx_names[0])
            print(f"[KPI] Detected ZIP wrapper, extracted inner xlsx: {xlsx_names[0]} ({len(inner)} bytes)")
            return inner
        # 若 ZIP 内仅 1 个文件，直接返回其内容
        names = z.namelist()
        if len(names) == 1:
            inner = z.read(names[0])
            print(f"[KPI] Detected ZIP wrapper, extracted: {names[0]} ({len(inner)} bytes)")
            return inner
    except Exception as e:
        print(f"[KPI] ZIP extraction attempt failed ({e}), treating as raw xlsx")
    return resp_bytes


def export_history(cookie: str, forgery_token: str, queryid: str, filename: str,
                   output_dir: str = None) -> str:
    """导出并下载 KPI 历史指标结果，返回保存的文件路径。

    CNN 导出接口返回 ZIP 包裹的 xlsx，本函数自动解包后保存真正的 xlsx。
    若目标文件被占用，自动在文件名后追加 _序号 生成新文件。
    """
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
        "POST", HISTORY_EXPORT_PATH, headers_extra=headers, body=body.encode('utf-8'), max_retries=2,
    )
    print(f"[KPI] Export status: {status}")

    if "200" not in status:
        raise Exception(f"Export KPI history failed: {status}")

    # CNN 导出返回 ZIP 包裹的 xlsx，解包为真正的 xlsx 字节
    resp_body = _extract_xlsx_bytes(resp_body)

    if not output_dir:
        output_dir = OUTPUT_DIR

    # 安全写入：若文件被占用则追加 _序号
    basename = f"{filename}.xlsx"
    output_path = os.path.join(output_dir, basename)
    idx = 0
    while True:
        try:
            with open(output_path, "wb") as f:
                f.write(resp_body)
            break
        except PermissionError:
            idx += 1
            if idx > 999:
                raise
            output_path = os.path.join(output_dir, f"{filename}_{idx}.xlsx")

    print(f"[KPI] Saved to: {output_path} ({len(resp_body)} bytes)")
    return output_path


# ============================================================
# 文件命名
# ============================================================
def _resolve_grouplayer_name(grouplayer: str, groupbygroup: bool) -> str:
    """根据 Payload.txt 规则将 grouplayer 映射为文件名中的 layer 部分。

    规则（来自 Payload.txt）：
    - "me,WV4.IubLink" / "me,gv4.BTSSiteManager" / "me,eNodeBFunction" → "Sites"
    - "me,gv4.BTSSiteManager,gv4.BTS.cell" / "me,eNodeBFunction,EUtranCellFDD" / "me,WV4.IubLink,WV4.UtranCell" → "Cells"
    - "me,fservice" → "NE"
    - "me" → "NE"
    - "all": groupbygroup=false → "NW", groupbygroup=true → "Group"
    - "me,fservice,*" (3 段及以上，未显式列出) → "NE"（用户确认统一映射）
    - 其他未命中的值原样保留
    """
    if grouplayer == "all":
        return "Group" if groupbygroup else "NW"
    if grouplayer in GROUPLAYER_RENAME:
        return GROUPLAYER_RENAME[grouplayer]
    # me,fservice,* 统一映射为 NE
    if grouplayer.startswith("me,fservice,"):
        return "NE"
    # 未命中规则，原样保留
    return grouplayer


def build_filename(cfg: dict) -> str:
    """构造 KPI 导出文件名前缀（不含时间戳和扩展名）。

    命名规则（来自 Payload.txt）：
    - 文件名 = templatename + grouplayer(替换后) + gr(替换后)，用下划线连接
    - templatename: 原样使用（如 xGW_LICENSE_OCCUPANCY_TEMPLATE_OSS_updated）
    - grouplayer: 按规则替换为 NE/Sites/Cells/NW/Group
    - gr: 3600 -> 1Hour, 86400 -> 1Day, 2592000 -> 1Month
    """
    name = cfg["templatename"]
    layer = _resolve_grouplayer_name(cfg.get("grouplayer", "me"), cfg.get("groupbygroup", False))
    gr_label = GR_RENAME.get(cfg["gr"], cfg["gr"])
    return f"{name}_{layer}_{gr_label}"


# ============================================================
# 旧文件清理
# ============================================================
def cleanup_old_exports(file_prefix: str) -> int:
    """删除同前缀的历史 xlsx 文件（保留最新一份）。"""
    pattern = os.path.join(OUTPUT_DIR, f"{file_prefix}_*.xlsx")
    files = [f for f in glob.glob(pattern) if not os.path.basename(f).startswith("~$")]
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
# 数据库导入（参考 ran_daily_kpi.py / ran_network_kpi_zs.py）
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
    """读取 xlsx 文件，返回 (headers, data)。先读入内存再解析。"""
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


def detect_key_cols(headers):
    """检测联合主键列：必须包含 'Begin Time'，并自动追加所有存在的标识列。

    不同模板的导出包含不同标识列：
      xGW_LICENSE/xGW_CPU_USAGE: Begin Time + NE
      VOICE_TRAFFIC/VLR_SUBSCRIBERS/DATA_SUBSCRIBERS: Begin Time + NE + SERVICE
      3G_FDD/4G_FDD/FREE_RATING_GROUP: Begin Time + NE + SERVICE + Measurement Object

    返回 list（如 ['Begin Time', 'NE', 'SERVICE', 'Measurement Object']）；
    若缺少 'Begin Time' 返回 None。
    """
    if "Begin Time" not in headers:
        print(f"  [DB][ERROR] 缺少 'Begin Time' 列。实际列名: {headers}")
        return None

    key_cols = ["Begin Time"]

    # 自动追加所有存在的标识列（按候选顺序）
    for cand in IDENTITY_COL_CANDIDATES:
        if cand in headers:
            key_cols.append(cand)

    if len(key_cols) == 1:
        print(f"  [DB][WARN] 未检测到任何标识列（NE/SERVICE/Measurement Object），"
              f"仅使用 'Begin Time' 作为主键。")
        print(f"  [DB][WARN] 导出列名: {headers}")
        print(f"  [DB][WARN] 若存在多元素同时刻数据，可能互相覆盖。")

    return key_cols


def write_to_db(db_path, table_name, headers, data, key_cols):
    """将数据写入 SQLite 数据库。

    去重策略：使用 SQL 临时表（遵循项目约定，避免 pandas 内存合并）。
    1. 将所有入参数据写入临时表
    2. DELETE 主表中 (key_cols) 匹配临时表的行
    3. INSERT 主表 SELECT FROM 临时表
    4. DROP 临时表

    优势：主表无需 PRIMARY KEY / UNIQUE 约束即可实现去重替换，
    适配既有无 PK 的表（如 xGW_LICENSE_OCCUPANCY_TEMPLATE_OSS_UME）。
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 性能优化
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=OFF")
    cursor.execute("PRAGMA cache_size=-64000")

    if not key_cols or any(c not in headers for c in key_cols):
        print(f"  [DB] 主键列不可用 key_cols={key_cols}，跳过。")
        conn.close()
        return 0

    def _q(col):
        return '"' + col.replace('"', '""') + '"'

    # 检查表是否已存在
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    table_exists = cursor.fetchone() is not None

    if not table_exists:
        # 新建表（仅声明列，不设 PK —— 去重由临时表逻辑保证）
        col_decls = ",\n  ".join(f"{_q(h)} TEXT" for h in headers)
        cursor.execute(f'CREATE TABLE "{table_name}" (\n  {col_decls}\n)')
    else:
        # 表已存在，检查并添加缺少的列
        cursor.execute(f'PRAGMA table_info("{table_name}")')
        existing_cols = {row[1] for row in cursor.fetchall()}
        for h in headers:
            if h not in existing_cols:
                try:
                    cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN {_q(h)} TEXT')
                except sqlite3.OperationalError:
                    pass

    # ---- 临时表去重 ----
    temp_table = "_tmp_import_cnn"
    cursor.execute(f'DROP TABLE IF EXISTS "{temp_table}"')
    temp_cols = ", ".join(_q(h) for h in headers)
    cursor.execute(f'CREATE TABLE "{temp_table}" ({temp_cols})')

    placeholders = ", ".join(["?"] * len(headers))
    insert_temp_sql = f'INSERT INTO "{temp_table}" ({temp_cols}) VALUES ({placeholders})'

    # 预处理 + 批量写入临时表
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
            cursor.executemany(insert_temp_sql, batch)
            batch.clear()
    if batch:
        cursor.executemany(insert_temp_sql, batch)

    # 删除主表中与临时表 key_cols 匹配的行（行值 IN 子查询）
    key_cols_q = ", ".join(_q(k) for k in key_cols)
    del_sql = (
        f'DELETE FROM "{table_name}" WHERE ({key_cols_q}) IN '
        f'(SELECT {key_cols_q} FROM "{temp_table}")'
    )
    cursor.execute(del_sql)
    deleted_count = cursor.rowcount

    # 从临时表插入到主表
    insert_main_sql = (
        f'INSERT INTO "{table_name}" ({temp_cols}) '
        f'SELECT {temp_cols} FROM "{temp_table}"'
    )
    cursor.execute(insert_main_sql)

    # 清理临时表
    cursor.execute(f'DROP TABLE IF EXISTS "{temp_table}"')

    conn.commit()
    conn.close()
    print(f"  [DB] 去重替换: 删除旧数据 {deleted_count} 行，写入新数据 {row_count} 行")
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
    """将导出的 xlsx 文件导入 SQLite 数据库。

    流程：
    - 读取 xlsx
    - 自动检测主键列（Begin Time + 元素标识列 NE）
    - 使用 SQL 临时表去重写入（DELETE 匹配 key + INSERT）
    - 上传数据库到 FTP
    - 清理本地 xlsx
    """
    print("\n" + "=" * 70)
    print("[DB] 开始导入数据库")
    print(f"[DB] 数据库路径: {DB_PATH}")
    print("=" * 70)

    total_imported = 0
    files_to_delete = []

    for task in CNN_KPI_TASKS:
        cfg = CNN_KPI_QUERY_CONFIGS[task["key"]]
        table_name = cfg["table_name"]
        file_prefix = build_filename(cfg)

        xlsx_file = find_latest_xlsx(file_prefix)
        print(f"\n[{table_name}]")

        if not xlsx_file:
            print(f"  not found (prefix={file_prefix})")
            continue

        files_to_delete.append(xlsx_file)
        print(f"  file: {os.path.basename(xlsx_file)}")

        headers, data = read_xlsx(xlsx_file)
        print(f"  rows: {len(data)}, cols: {len(headers)}")

        # 不增加 "Source File" 列 —— 既有 UME 表（如 xGW_LICENSE_OCCUPANCY_TEMPLATE_OSS_UME）
        # 无此列，保持 schema 一致。

        # 检测主键列
        key_cols = detect_key_cols(headers)
        if not key_cols:
            print(f"  [skip] 无法确定主键（缺少 Begin Time 列）")
            continue

        print(f"  key cols: {key_cols}")
        row_count = write_to_db(DB_PATH, table_name, headers, data, key_cols)
        print(f"  written: {row_count} rows")
        total_imported += row_count

        # 释放本迭代大对象
        headers = data = None
        gc.collect()

    # ---- FTP 上传数据库 ----
    print("\n[FTP Upload]")
    print(f"  uploading: {DB_NAME}")
    if upload_to_ftp(DB_PATH, FTP_REMOTE_DIR, DB_NAME):
        print(f"  [OK] 数据库已上传: {DB_NAME}")
    else:
        print(f"  [FAIL] 数据库上传失败: {DB_NAME}")

    # ---- 清理已导入的 xlsx 文件 ----
    print("\n[cleanup]")
    all_files = set(files_to_delete)
    for task in CNN_KPI_TASKS:
        cfg = CNN_KPI_QUERY_CONFIGS[task["key"]]
        prefix = build_filename(cfg)
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
                    capture_output=True, timeout=15
                )
                if not os.path.exists(fpath):
                    print(f"  deleted (force): {os.path.basename(fpath)}")
                    deleted_count += 1
                else:
                    print(f"  [warn] {os.path.basename(fpath)}: still locked, scheduled for reboot")
                    import ctypes
                    ctypes.windll.kernel32.MoveFileExW(fpath, None, 0x4)  # MOVEFILE_DELAY_UNTIL_REBOOT
            except Exception as e:
                print(f"  [error] {os.path.basename(fpath)}: {e}")

    print(f"  total deleted: {deleted_count} files")
    print(f"\n[DB] 导入完成，总计 {total_imported} 行")
    return total_imported


# ============================================================
# 单任务执行
# ============================================================
def _run_single_kpi_query(auth: dict, task: dict, start_index: int = 0) -> tuple:
    """执行单个 KPI 查询任务，返回 (file_prefix, saved_path) 或抛异常。"""
    cfg = CNN_KPI_QUERY_CONFIGS[task["key"]]
    file_prefix = build_filename(cfg)

    # 错峰启动：按索引延迟，避免同时冲击接口
    delay = start_index * 0.8
    if delay > 0:
        time.sleep(delay)

    print(f"\n[MAIN] Starting KPI query: {cfg['templatename']} (prefix={file_prefix})")

    payload = build_cnn_kpi_payload(cfg)

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
def run_cnn_kpi_sync():
    """主流程：登录 → 并行查询 → 导出 → 数据库导入 → FTP → 清理。"""
    t_start = time.time()
    print(f"[MAIN] CNN UME KPI sync started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[MAIN] Host: https://{HOST}:{PORT}{LOGIN_PORTAL}")
    print(f"[MAIN] Output dir: {OUTPUT_DIR}")
    print(f"[MAIN] Months back: {MONTHS_BACK}")
    print(f"[MAIN] Parallel workers: {MAX_PARALLEL_WORKERS}")
    print(f"[MAIN] Total tasks: {len(CNN_KPI_TASKS)}")
    print("=" * 70)

    # 1. 登录
    auth = login()

    # 2. 并行执行查询
    results = []
    errors = []

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
        future_to_task = {}
        for idx, task in enumerate(CNN_KPI_TASKS):
            future = executor.submit(_run_single_kpi_query, auth, task, idx)
            future_to_task[future] = task

        for future in as_completed(future_to_task):
            task = future_to_task[future]
            task_label = task["key"]
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

    gc.collect()

    # 4. 数据库导入
    if results:
        import_to_database()
    else:
        print("\n[MAIN] No files exported, skip database import.")

    elapsed_total = time.time() - t_start
    print(f"\n[MAIN] Total completed in {elapsed_total:.2f} seconds")
    print(f"[MAIN] Done.")
    return results


if __name__ == "__main__":
    run_cnn_kpi_sync()
