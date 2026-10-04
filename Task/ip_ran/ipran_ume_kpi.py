# -*- coding: utf-8 -*-
"""
iPRAN UME KPI 数据获取脚本（IP RAN - M6000 系列路由器性能指标）

功能：
1. 登录 ZTE iPRAN UME 网管系统（https://10.100.2.99:28001/portal-athena），获取鉴权 Cookie 与 forgery token。
2. 根据 url.txt 中的 Payload 配置，创建历史指标查询任务（HQ M6K-FW，15 分钟粒度 gr=900）。
3. 轮询查询进度直到完成，导出为 Excel 文件。
4. 将导出的 xlsx 导入 SQLite 数据库（以 Begin Time + 元素标识列为联合主键，SQL 临时表去重）。
5. 上传数据库到 FTP /01_RPA/LBR_Tools/KPI/IPRAN。
6. 清理本地 xlsx 文件。

文件命名规则（来自 url.txt）：
  {favoriteconditionname}_{filterlayer}_{gr_renamed}.xlsx
  其中：
    gr:"900"    → "15mins"
    gr:"3600"   → "1hour"
    gr:"86400"  → "1Day"

参考：
- ran_ume_sla.py：登录 / 查询 / 轮询 / 导出 / 数据库 / FTP 流程
- cnn_ume_kpi.py：同一套 ZTE UME PM 接口 + ZIP 解包 + 临时表去重
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
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed


# --- 凭据引导（2026-10-04）：口令不写在源码里，统一走共享入口 ---
# 优先环境变量，其次「设置 → 凭据管理」页面（credential_store）。
import os as _os, sys as _sys
# 注意：判据是 credentials.py 这个**文件**，不是 shared/ 这个**目录**。
# Task/Unified_Tools/shared 也存在但里面没有 credentials.py，只判目录会
# 命中它、import 失败后被 except 吞掉 -> 静默降级为空口令（实测踩过）。
_ws = _os.path.dirname(_os.path.abspath(__file__))
_cand = None
while _ws:
    _try = _os.path.join(_ws, "Unified_Tools", "shared", "credentials.py")
    if _os.path.isfile(_try):
        _cand = _try
        break
    _p = _os.path.dirname(_ws)
    if _p == _ws:
        break
    _ws = _p
if _cand:
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_cand)))
try:
    from shared.credentials import get_credential as _get_credential
except Exception:  # 凭据库不可用时降级，不让脚本直接崩
    def _get_credential(_key, env=None, default=""):
        return (_os.environ.get(env, "") if env else "") or default

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
HOST = "10.100.2.99"
PORT = 28001
USERNAME = "noc1"
PASSWORD = _get_credential("ipran_ume", env="IPRAN_UME_PASS")
LOGIN_PORTAL = "/portal-athena/framework/default.html"

# 脚本目录与输出目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

# 查询时间范围：默认最近 1 天（24 小时）
# 可通过环境变量 IPRAN_KPI_DAYS_BACK 覆盖
DAYS_BACK = int(os.environ.get("IPRAN_KPI_DAYS_BACK", "1"))

# 查询时间范围：固定为前一个月的 00:00:00 到今天的 23:59:59
# 例如今天 2026-07-29 → start 2026-06-29 00:00:00, end 2026-07-29 23:59:59
# 可通过环境变量 IPRAN_KPI_MONTHS_BACK 覆盖（默认 1 个月）
MONTHS_BACK = int(os.environ.get("IPRAN_KPI_MONTHS_BACK", "1"))

# 并行查询线程数
MAX_PARALLEL_WORKERS = int(os.environ.get("IPRAN_KPI_PARALLEL_WORKERS", "4"))

# PM 接口路径（与 ran_ume_sla.py / cnn_ume_kpi.py 一致）
HISTORY_PATH = "/api/pm-analysis/v2/history"
HISTORY_POLL_PATH = "/api/pm-analysis/v1/history"
HISTORY_EXPORT_PATH = "/api/pm-analysis/v3/history/export"
HISTORY_REFERER = f"https://{HOST}:{PORT}{LOGIN_PORTAL}"

# 数据库配置（与脚本同目录）
DB_NAME = "ipran_ume_kpi.sqlite3"
DB_PATH = os.path.join(SCRIPT_DIR, DB_NAME)

# FTP 上传配置
FTP_HOST = "192.168.100.19"
FTP_USER = "ZTEEMS"
FTP_PASS = "DX"
FTP_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI/IPRAN"

# 标识列候选（用于联合主键去重）。按优先级排序，自动检测实际导出中包含哪些。
IDENTITY_COL_CANDIDATES = ["NE", "ME", "Managed Element", "SERVICE", "Measurement Object"]

# gr 显示名称替换规则（来自 url.txt，注意大小写）
GR_RENAME = {
    "900": "15mins",
    "3600": "1hour",
    "86400": "1Day",
}

# ============================================================
# KPI 查询配置（从 url.txt 提取）
# 字段顺序与 url.txt Payload 严格一致（ZTE 接口对字段顺序敏感）
# ============================================================
# 从自动生成的配置模块导入（由 _parse_payload.py 从 Payload.txt 解析生成）
# 包含 5 个查询配置：IPCORE HQ-ODC、Metro-ring、Gbarnga/Buchanna/RIA/Kakata、Banjor/ELWA、OLT
from _configs_generated import IPRAN_KPI_QUERY_CONFIGS as _PAYLOAD_CONFIGS, IPRAN_KPI_TASKS as _PAYLOAD_TASKS

# HQ M6K-FW 配置（来自 url.txt），与 Payload.txt 中的 5 个配置合并
_HQ_M6K_FW_CONFIG = {
    "favoriteconditionname": "HQ M6K-FW",
    "filterlayer": "bnctp",
    "grouplayer": "me,bnctp",
    "gr": "900",
    "motid": "BNCTN.PMP",
    "nfctid": (
        "bn.me.ZXR10.15K-M6000-16SE,"
        "bn.me.ZXR10.15K-M6000-18S,"
        "bn.me.ZXR10.15K-M6000-18S-Plus,"
        "bn.me.ZXR10.15K-M6000-2S10,"
        "bn.me.ZXR10.15K-M6000-2S16,"
        "bn.me.ZXR10.15K-M6000-2S4,"
        "bn.me.ZXR10.15K-M6000-2S4-Plus,"
        "bn.me.ZXR10.15K-M6000-2S6,"
        "bn.me.ZXR10.15K-M6000-3S,"
        "bn.me.ZXR10.15K-M6000-3S-Plus,"
        "bn.me.ZXR10.15K-M6000-4SE,"
        "bn.me.ZXR10.15K-M6000-5S,"
        "bn.me.ZXR10.15K-M6000-6F,"
        "bn.me.ZXR10.15K-M6000-8S,"
        "bn.me.ZXR10.15K-M6000-8SE,"
        "bn.me.ZXR10.15K-M6000-8S-Plus,"
        "bn.me.ZXR10.15K-M6000-S-VND,"
        "bn.me.ZXR10.15K-M6000-S-VRC"
    ),
    "items": ["C019901990", "C019911991"],
    "itemsposition": [0, 0],
    "itemsposition1": [0, 0],
    "containvcell": 0,
    "indexfillingtype": "zeroDenominator",
    "uilocations": [
        {
            "id": "f72f2173-766a-4ae2-9215-c33fd7fe2b07$ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_3}",
            "moc": "bnag",
            "model": "bnag",
        }
    ],
    "reslocation": [
        {
            "id": "ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_3}",
            "displayName": '{"en_US":"SmartGroup:3","zh_CN":"SmartGroup:3"}',
            "nbiId": "ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_3}",
            "labelDn": "HQ-M6K-8S_Plus_PS01#SmartGroup:3",
            "moc": "bnag",
            "path": [
                {
                    "id": "f72f2173-766a-4ae2-9215-c33fd7fe2b07",
                    "displayName": "HQ-M6K-8S_Plus_PS01",
                    "model": "wlme",
                    "nbiId": "BN:ME{431941261}",
                },
                {
                    "id": "ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_3}",
                    "displayName": "SmartGroup:3",
                    "model": "bnag",
                    "nbiId": "ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_3}",
                },
            ],
        }
    ],
    # chartsetting：图表显示配置（JSON 字符串，来自 url.txt）
    "chartsetting": (
        '{"showchart":true,"layout":1,"showMarkLineLabel":false,"showDataZoom":true,'
        '"charts":[{"id":"03059aec-6875-bca7-06bb9cd39805d826","legendmode":0,"displayMode":0,'
        '"mos":["f72f2173-766a-4ae2-9215-c33fd7fe2b07$ME{f72f2173-766a-4ae2-9215-c33fd7fe2b07},EQ={/r=0/sh=0/sl=255},FTP={/p=124_3}"],'
        '"mosNames":["\\"HQ-M6K-8S_Plus_PS01\\"-SmartGroup:3"],'
        '"itemids":["order_8","order_9"],'
        '"selectedlegend":["order_8","order_9"],'
        '"markingsettings":[],"custommarkingsettings":[],"showsetting":[]}],'
        '"thresholdIds":[],'
        '"countersInfo":['
        '{"key":"order_8","id":"C019901990","itemposition":0,"itemposition1":0},'
        '{"key":"order_9","id":"C019911991","itemposition":0,"itemposition1":0}'
        ']}'
    ),
    # favorite_id：收藏条件 ID（来自 url.txt Payload 末尾的 id 字段）
    "favorite_id": "4e033c70f47943318d2d77717b80eb4e",
    # 数据库表名（空格和连字符替换为下划线）
    "table_name": "HQ_M6K_FW_bnctp_15mins",
}

# 合并所有查询配置：HQ M6K-FW（url.txt）+ 5 个配置（Payload.txt）
IPRAN_KPI_QUERY_CONFIGS = {"HQ_M6K_FW": _HQ_M6K_FW_CONFIG}
IPRAN_KPI_QUERY_CONFIGS.update(_PAYLOAD_CONFIGS)

# 任务列表（共 6 个查询任务）
IPRAN_KPI_TASKS = [{"key": "HQ_M6K_FW"}] + _PAYLOAD_TASKS


# ============================================================
# HTTP / SSL 工具函数（复用 ran_ume_sla.py / cnn_ume_kpi.py 实现）
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
    """执行 iPRAN UME 登录流程，返回包含 cookie 和 forgery_token 的字典。

    流程：
    1. GET /api/oauth2/v1/authorize（redirect_uri=/portal-athena/framework/default.html）获取初始 cookie 与 forgery token
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
            or "portal-athena" in resp_text
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
# Payload 构造（字段顺序与 url.txt 严格一致）
# ============================================================
def _subtract_months(dt, months):
    """从 datetime 中减去指定自然月数，日溢出时钳制到月末。
    例: 2026-07-29 - 1 month = 2026-06-29；2026-03-31 - 1 month = 2026-02-28。
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


def build_ipran_kpi_payload(cfg: dict, start_iso: str = None, end_iso: str = None) -> dict:
    """构造 iPRAN KPI 历史指标查询 Payload。

    字段顺序严格遵循 url.txt 中的原始请求（ZTE 接口对字段顺序敏感）。

    时间范围默认：前一个月的 00:00:00 到今天的 23:59:59（UTC）。
    例如今天 2026-07-29 → start 2026-06-29T00:00:00.000Z, end 2026-07-29T23:59:59.000Z
    """
    now = datetime.now(timezone.utc)
    if end_iso is None:
        # 今天的 23:59:59（UTC）
        end_iso = now.replace(hour=23, minute=59, second=59, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if start_iso is None:
        # 前一个月的 00:00:00（UTC）
        start_dt = _subtract_months(now.replace(hour=0, minute=0, second=0, microsecond=0), MONTHS_BACK)
        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    timeinfo = {
        "mode": 1,
        "start": start_iso,
        "end": end_iso,
        "relative": -7,
        "timezonetype": "1",
        "clienttimezone": "Atlantic/Reykjavik",
        "showtimezoneoffset": cfg.get("showtimezoneoffset", False),
        "querylongtime": {"type": 0, "value": 1},
        "timespanfilter": "00:00:00-24:00:00",
        "dayfiltertype": 0,
        "dayinmonthfilter": "1111111111111111111111111111111",
    }

    # 严格按 url.txt / Payload.txt 字段顺序构造（使用 list of tuples 保证 JSON 序列化时的字段顺序）
    fields = [
        ("arraycounterinfos", []),
        ("displaymode", cfg.get("displaymode", 0)),
        ("favoriteconditionname", cfg["favoriteconditionname"]),
        ("gr", cfg["gr"]),
        ("groupattributetype", 0),
        ("groupbygroup", False),
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
    ]

    # versiondatacompare：仅部分配置有此字段（如 IPCORE HQ-ODC），位于 straightquery 之后
    if "versiondatacompare" in cfg:
        fields.append(("versiondatacompare", cfg["versiondatacompare"]))

    fields.extend([
        ("needdeployfilter", False),
        ("timeinfo", timeinfo),
        ("indexfillingtype", cfg.get("indexfillingtype", "zeroDenominator")),
        ("thresholdinfos", []),
        ("sendalarm", False),
        ("templatetype", 0),
        ("filterlayer", cfg["filterlayer"]),
        ("grouplayer", cfg["grouplayer"]),
        ("containvcell", cfg.get("containvcell", 0)),
        ("resfilterattribute", ""),
        ("uilocations", cfg.get("uilocations", [])),
        ("reslocation", cfg.get("reslocation", [])),
        ("inexistenceres", False),
        ("firstDayOfWeek", 7),
        ("iswireless", False),
        ("hidehistorystopbutton", False),
        ("opencustomizehistoryexport", False),
        ("opentemplatecustomcolumn", False),
    ])

    # invaliditems：位于 opentemplatecustomcolumn 之后、chartsetting 之前（来自 Payload.txt Metro-ring）
    if cfg.get("invaliditems") is not None:
        fields.append(("invaliditems", cfg["invaliditems"]))

    # chartsetting：图表显示配置（JSON 字符串，可选）
    if cfg.get("chartsetting"):
        fields.append(("chartsetting", cfg["chartsetting"]))

    # id：收藏条件 ID（可选，来自 url.txt / Payload.txt 末尾）
    if cfg.get("favorite_id"):
        fields.append(("id", cfg["favorite_id"]))

    # 转为有序 dict（Python 3.7+ dict 保持插入顺序）
    payload = dict(fields)
    return payload


# ============================================================
# KPI 查询 / 轮询 / 导出
# ============================================================
def create_history_query(cookie: str, forgery_token: str, payload: dict) -> str:
    """创建 KPI 历史指标查询任务，返回 queryid。"""
    print(f"[KPI] Creating: {payload.get('favoriteconditionname')} / "
          f"filterlayer={payload.get('filterlayer')} / gr={payload.get('gr')}")
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
                       timeout: int = 1200, interval: int = 10) -> dict:
    """轮询 KPI 历史指标查询进度，直到完成或超时。

    Args:
        timeout: 超时秒数，默认 1200s（20 分钟），因为 iPRAN 指标查询可能需要 10-15 分钟。
        interval: 轮询间隔秒数，默认 10s。
    """
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
    """导出接口可能返回 ZIP 包裹的 xlsx（PK 头但内层才是真正的 xlsx）。
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
            print(f"[KPI] Detected ZIP wrapper, extracted inner xlsx: "
                  f"{xlsx_names[0]} ({len(inner)} bytes)")
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

    # 导出可能返回 ZIP 包裹的 xlsx，解包为真正的 xlsx 字节
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
def build_filename(cfg: dict) -> str:
    """构造 KPI 导出文件名前缀（不含时间戳和扩展名）。

    命名规则（来自 url.txt）：
    - 文件名 = favoriteconditionname + filterlayer + gr(替换后)，用下划线连接
    - favoriteconditionname: 将空格、斜杠、连字符等非法文件名字符替换为下划线
    - filterlayer: 原样使用（如 "bnctp"）
    - gr: 900 -> "15mins", 3600 -> "1hour", 86400 -> "1Day"

    注意：favoriteconditionname 中的 "/" 在 Windows 文件系统中是非法字符
    （如 "Gbarnga/Buchanna/RIA/Kakata"、"Banjor/ELWA"），必须替换。
    """
    name = cfg["favoriteconditionname"]
    # 替换 Windows 非法文件名字符：空格、斜杠、反斜杠、连字符
    name = name.replace(" ", "_").replace("/", "_").replace("\\", "_").replace("-", "_")
    layer = cfg["filterlayer"]
    gr_label = GR_RENAME.get(cfg["gr"], cfg["gr"])
    return f"{name}_{layer}_{gr_label}"


def sanitize_table_name(name: str) -> str:
    """将文件名前缀转为合法的 SQLite 表名（空格和连字符替换为下划线）。"""
    return name.replace(" ", "_").replace("-", "_")


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
# 数据库导入（参考 cnn_ume_kpi.py / ran_ume_sla.py）
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

    返回 list（如 ['Begin Time', 'NE', 'Measurement Object']）；
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
        print("  [DB][WARN] 未检测到任何标识列（NE/ME/SERVICE/Measurement Object），"
              "仅使用 'Begin Time' 作为主键。")
        print(f"  [DB][WARN] 导出列名: {headers}")
        print("  [DB][WARN] 若存在多元素同时刻数据，可能互相覆盖。")

    return key_cols


def write_to_db(db_path, table_name, headers, data, key_cols):
    """将数据写入 SQLite 数据库。

    去重策略：使用 SQL 临时表（遵循项目约定，避免 pandas 内存合并）。
    1. 将所有入参数据写入临时表
    2. DELETE 主表中 (key_cols) 匹配临时表的行
    3. INSERT 主表 SELECT FROM 临时表
    4. DROP 临时表
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
    temp_table = "_tmp_import_ipran"
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
    - 自动检测主键列（Begin Time + 元素标识列）
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

    for task in IPRAN_KPI_TASKS:
        cfg = IPRAN_KPI_QUERY_CONFIGS[task["key"]]
        table_name = cfg.get("table_name") or sanitize_table_name(build_filename(cfg))
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

        # 检测主键列
        key_cols = detect_key_cols(headers)
        if not key_cols:
            print("  [skip] 无法确定主键（缺少 Begin Time 列）")
            continue

        print(f"  key cols: {key_cols}")
        row_count = write_to_db(DB_PATH, table_name, headers, data, key_cols)
        print(f"  written: {row_count} rows")
        total_imported += row_count

        # 释放本迭代大对象
        headers = data = None
        gc.collect()

    # ---- FTP 上传已移除（数据通过 API 写入远程） ----
    print("\n[INFO] FTP 上传已移除，数据由 my_app API 写入远程")

    # ---- 清理已导入的 xlsx 文件 ----
    print("\n[cleanup]")
    all_files = set(files_to_delete)
    for task in IPRAN_KPI_TASKS:
        cfg = IPRAN_KPI_QUERY_CONFIGS[task["key"]]
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
    cfg = IPRAN_KPI_QUERY_CONFIGS[task["key"]]
    file_prefix = build_filename(cfg)

    # 错峰启动：按索引延迟，避免同时冲击接口
    delay = start_index * 0.8
    if delay > 0:
        time.sleep(delay)

    print(f"\n[MAIN] Starting KPI query: {cfg['favoriteconditionname']} "
          f"(prefix={file_prefix})")

    payload = build_ipran_kpi_payload(cfg)

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
def run_ipran_kpi_sync():
    """主流程：登录 → 并行查询 → 导出 → 数据库导入 → FTP → 清理。"""
    t_start = time.time()
    print(f"[MAIN] iPRAN UME KPI sync started at "
          f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[MAIN] Host: https://{HOST}:{PORT}{LOGIN_PORTAL}")
    print(f"[MAIN] Output dir: {OUTPUT_DIR}")
    print(f"[MAIN] DB path: {DB_PATH}")
    print(f"[MAIN] Months back: {MONTHS_BACK} (前一个月 00:00:00 到今天 23:59:59 UTC)")
    print(f"[MAIN] Parallel workers: {MAX_PARALLEL_WORKERS}")
    print(f"[MAIN] Total tasks: {len(IPRAN_KPI_TASKS)}")
    print("=" * 70)

    # 1. 登录
    auth = login()

    # 2. 并行执行查询
    results = []
    errors = []

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
        future_to_task = {}
        for idx, task in enumerate(IPRAN_KPI_TASKS):
            future = executor.submit(_run_single_kpi_query, auth, task, idx)
            future_to_task[future] = task

        for future in as_completed(future_to_task):
            task = future_to_task[future]
            task_label = task["key"]
            try:
                file_prefix, saved_path = future.result()
                results.append((file_prefix, saved_path))
                print(f"[MAIN] KPI query [{task_label}] succeeded: "
                      f"{os.path.basename(saved_path)}")
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
    print("\n" + "=" * 60)
    print(f"[MAIN] Total completed in {elapsed_total:.2f} seconds")
    print("[MAIN] Done.")
    return results


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    run_ipran_kpi_sync()
