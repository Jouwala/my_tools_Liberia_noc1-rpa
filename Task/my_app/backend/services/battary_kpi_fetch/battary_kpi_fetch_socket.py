# -*- coding: utf-8 -*-
"""
Battery KPI UME API Fetcher (Socket + RSA 方式)
=================================================
参考 ran_network_kpi_zeenshan/ran_network_kpi_zs.py 的纯接口实现方式，
使用 **原始 socket + SSL + RSA 加密登录**（不依赖 Playwright 浏览器、不依赖 requests），
登录成功后通过原始 HTTP 请求调用 url.txt 中的 3 个电池 KPI API。

与 battary_kpi_fetch.py（Playwright + requests）的区别：
  - 本脚本：纯接口方式，无浏览器，依赖轻（cryptography + pandas + openpyxl）
  - 适用场景：192.168.170.2 未弹验证码时，可全程自动化；弹验证码时回退到
    auth_info.json（浏览器登录产生的鉴权文件，见 ensure_auth_info 说明）

凭据来源（优先级从高到低）：
  命令行参数 > 环境变量(BATT_HOST/BATT_PORT/BATT_USERNAME/BATT_PASSWORD)
  > credential_store(battery_ume，即「设置 → 凭据管理」页面) > url.txt > 内置默认值

auth_info.json 回退说明（2026-09-23）：
  该 UME 启用图形验证码时 RSA 纯接口登录会失败，此时回退读取同目录的
  auth_info.json。该文件原本由 battary_kpi_login.py（Playwright）生成，但
  生成脚本与 playwright 依赖均已不在本仓库，导致回退链实际是空的、任务必然
  报「RSA 登录未成功且无可用 auth_info.json」。现已内置
  ``ensure_auth_info(force=False)`` 兜底：用 credential_store 的账号密码调
  同一套 RSA 接口，成功后写出兼容格式的 auth_info.json，使回退链真正可用。

登录流程（参考 ran_network_kpi_zs.py）：
  1. GET /api/oauth2/v1/authorize  → 获取初始 Cookie + loginParameters
  2. GET /api/oauth2/v1/login/publickey → 获取 RSA 公钥
  3. RSA(PKCS1v15) 加密密码
  4. POST /api/oauth2/v1/login_rsa → 获取会话 Cookie + forgerydefense token

调用顺序：
  1. POST /api/configuration/v1/standard-point/get-by-multi-moc  → 测量点元数据
  2. POST /api/monitor-manager/v1/realtime-data/get-by-condition  → 分页实时数据
  3. POST /api/monitor-manager/v1/realtime-data/export            → 导出文件

数据处理使用 pandas 向量化操作；原始响应保存为 JSON，结构化数据保存为 Excel/CSV。
"""

from __future__ import annotations

import base64
import gzip
import importlib.util
import json
import math
import os
import re
import socket
import ssl
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# ---------------------------------------------------------------------------
# 路径配置（脚本相对路径）
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
URL_FILE = SCRIPT_DIR / "url.txt"
AUTH_INFO_FILE = SCRIPT_DIR / "auth_info.json"   # 浏览器登录产生的鉴权（回退用）
OUTPUT_DIR = SCRIPT_DIR / "output_socket"

# ---------------------------------------------------------------------------
# 依赖检查
# ---------------------------------------------------------------------------


def _check_dependencies() -> None:
    missing = []
    if importlib.util.find_spec("cryptography") is None:
        missing.append("cryptography")
    if importlib.util.find_spec("pandas") is None:
        missing.append("pandas")
    if importlib.util.find_spec("openpyxl") is None:
        missing.append("openpyxl")
    if missing:
        print("缺少以下依赖，请先安装：")
        print("  pip install " + " ".join(missing))
        sys.exit(1)


_check_dependencies()

import pandas as pd  # noqa: E402

# ---------------------------------------------------------------------------
# 解析 url.txt（与 battary_kpi_login.parse_url_txt 同逻辑，本脚本内联以避免引入 playwright）
# ---------------------------------------------------------------------------


def parse_url_txt(url_file: Path) -> dict:
    """解析 url.txt，提取目标 URL、用户名、密码。"""
    if not url_file.exists():
        raise FileNotFoundError(f"未找到 url.txt: {url_file}")

    content = url_file.read_text(encoding='utf-8')
    target_url = ""
    username = ""
    password = ""

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("https://") or line.lower().startswith("http://"):
            target_url = line
        elif re.search(r"用户名|username", line, re.IGNORECASE):
            parts = re.split(r"[：:]", line, maxsplit=1)
            if len(parts) == 2:
                username = parts[1].strip()
        elif re.search(r"密码|password", line, re.IGNORECASE):
            parts = re.split(r"[：:]", line, maxsplit=1)
            if len(parts) == 2:
                password = parts[1].strip()

    if not target_url:
        raise ValueError("url.txt 中未找到 URL")
    if not username:
        raise ValueError("url.txt 中未找到用户名")
    if not password:
        raise ValueError("url.txt 中未找到密码")

    from urllib.parse import urlparse
    parsed = urlparse(target_url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    return {
        "target_url": target_url,
        "host": host,
        "port": port,
        "username": username,
        "password": password,
    }


def _runtime_credentials():
    """运行时凭据：环境变量 > credential_store > 内置默认值。

    凭据由「设置 → 凭据管理」的 battery_ume 分组维护（页面改密后最迟 30 秒生效，
    无需重启服务、无需改代码）。credential_store 不可用时回退内置默认值，
    保持本脚本「可直接独立运行」的特性。
    """
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        try:
            from credential_store import get_credential
        except ImportError:
            # credential_store 都导入不了：只回退用户名，口令留空让登录明确失败。
            # 原此处回退 DEFAULT_PASSWORD 字面量，2026-09-27 已删除该硬编码口令。
            return DEFAULT_USERNAME, ""
    return get_credential("battery_ume")


def load_credentials(args=None) -> dict:
    """加载凭据，优先级：命令行参数 > 环境变量 > credential_store > url.txt > 内置默认值。

    脚本无需 url.txt 即可独立运行；url.txt 存在时作为第四优先级自动读取。
    """
    import os

    # 1. 内置默认值（口令不在代码里，留空；由下面第 3.5 步 credential_store 填充）
    host = DEFAULT_HOST
    port = DEFAULT_PORT
    username = DEFAULT_USERNAME
    password = ""

    # 2. url.txt（若存在则覆盖默认值，向后兼容）
    if URL_FILE.exists():
        try:
            creds = parse_url_txt(URL_FILE)
            host = creds["host"]
            port = creds["port"]
            username = creds["username"]
            password = creds["password"]
        except Exception:
            pass  # url.txt 解析失败不阻断，继续用默认值

    # 3. 环境变量
    host = os.environ.get("BATT_HOST", host)
    port = int(os.environ.get("BATT_PORT", port))
    username = os.environ.get("BATT_USERNAME", username)
    password = os.environ.get("BATT_PASSWORD", password)

    # 3.5 credential_store（「设置 → 凭据管理」的 battery_ume 分组）
    #     只覆盖账号密码，不覆盖 host/port（主机端口由 BATT_HOST/BATT_PORT/url.txt 决定）。
    #     环境变量已经显式设置了账号/密码时不覆盖，保持「环境变量 > 数据库」的项目约定。
    try:
        cred_user, cred_pwd = _runtime_credentials()
        if cred_user and not os.environ.get("BATT_USERNAME"):
            username = cred_user
        if cred_pwd and not os.environ.get("BATT_PASSWORD"):
            password = cred_pwd
    except Exception as e:  # credential_store 不可用不应阻断脚本独立运行
        print(f"[CRED] credential_store 读取失败，沿用上级优先级值: {e}")

    # 4. 命令行参数（最高优先级）
    if args is not None:
        if getattr(args, "host", None):
            host = args.host
        if getattr(args, "port", None):
            port = args.port
        if getattr(args, "username", None):
            username = args.username
        if getattr(args, "password", None):
            password = args.password

    return {
        "target_url": f"https://{host}:{port}",
        "host": host,
        "port": port,
        "username": username,
        "password": password,
    }


def parse_args():
    """解析命令行参数（全部可选，不传则用内置默认值/环境变量/url.txt）。"""
    import argparse
    parser = argparse.ArgumentParser(
        description="Battery KPI API 抓取（Socket+RSA 方式）— 无需 url.txt 即可独立运行",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "凭据优先级: 命令行参数 > 环境变量(BATT_HOST/BATT_PORT/BATT_USERNAME/BATT_PASSWORD) "
            "> credential_store(battery_ume) > url.txt > 内置默认值\n"
            "示例:\n"
            "  python battary_kpi_fetch_socket.py                          # 用内置默认值\n"
            "  python battary_kpi_fetch_socket.py --host 10.100.28.27 --port 28001\n"
            "  set BATT_PASSWORD=xxx && python battary_kpi_fetch_socket.py  # 用环境变量"
        ),
    )
    parser.add_argument("--host", default=None, help=f"目标主机（默认 {DEFAULT_HOST}）")
    parser.add_argument("--port", type=int, default=None, help=f"目标端口（默认 {DEFAULT_PORT}）")
    parser.add_argument("--username", default=None, help=f"用户名（默认 {DEFAULT_USERNAME}）")
    parser.add_argument("--password", default=None, help="密码（默认内置）")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# API 配置（来自 url.txt）
# ---------------------------------------------------------------------------
MOC = "r32.uedm.batt"
SMP_IDS = ["batt.health", "batt.prst.soc", "batt.charge.discharge.status"]

PATH_STANDARD_POINT = "/api/configuration/v1/standard-point/get-by-multi-moc"
PATH_GET_BY_CONDITION = "/api/monitor-manager/v1/realtime-data/get-by-condition"
PATH_EXPORT = "/api/monitor-manager/v1/realtime-data/export"

# 分页与超时配置
PAGE_SIZE = 200
MAX_PAGES = 5000
SOCKET_TIMEOUT = 30            # 单次 socket 接收超时（秒）
REQUEST_MAX_RETRIES = 2        # 单次请求重试次数

# ---------------------------------------------------------------------------
# 内置默认凭据（源自 url.txt，脚本可独立运行无需 url.txt）
# 覆盖优先级：命令行参数 > 环境变量 > url.txt > 内置默认值
# ---------------------------------------------------------------------------
DEFAULT_HOST = "192.168.170.2"
DEFAULT_PORT = 443
# 口令由 credential_store 的 `battery_ume` 组提供（见 _runtime_credentials）。
# 2026-09-27 删除硬编码 DEFAULT_PASSWORD —— 重复副本且已入库。
DEFAULT_USERNAME = "zeeshan mazhar"

# 全局主机/端口（登录后由 credentials 填充）
_HOST = ""
_PORT = 443


# ---------------------------------------------------------------------------
# 原始 socket + SSL HTTP 工具（参考 ran_network_kpi_zs.py）
# ---------------------------------------------------------------------------


def _create_ssl_socket(host: str, port: int):
    """创建绕过证书校验的 TLS socket。"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers('ALL:@SECLEVEL=0')
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(SOCKET_TIMEOUT)
    ssock = ctx.wrap_socket(sock)
    ssock.connect((host, port))
    return ssock


def _decode_chunked(data: bytes) -> bytes:
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


def _http_request(method: str, path: str, host: str, port: int,
                  headers_extra: str | None = None, body=None) -> tuple:
    """发送原始 HTTP 请求并返回 (状态行, 响应头字典, 原始头文本, 响应体字节)。"""
    ssock = _create_ssl_socket(host, port)

    headers = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Language: en-US,en;q=0.9\r\n"
        f"Accept-Encoding: gzip\r\n"
        f"Connection: close\r\n"
        f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36\r\n"
    )
    if headers_extra:
        headers += headers_extra
    if body:
        body_bytes = body if isinstance(body, bytes) else body.encode('utf-8')
        headers += f"Content-Length: {len(body_bytes)}\r\n"
    else:
        body_bytes = b""
    headers += "\r\n"

    request_bytes = headers.encode('utf-8') + body_bytes
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


def _http_request_with_retry(method: str, path: str, host: str, port: int,
                             headers_extra: str | None = None, body=None,
                             max_retries: int = REQUEST_MAX_RETRIES) -> tuple:
    """带重试的 HTTP 请求封装，对 499/5xx 进行指数退避重试。"""
    retry_statuses = ("499", "500", "502", "503", "504")
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            status, hdrs, raw_hdrs, resp_body = _http_request(
                method, path, host, port, headers_extra=headers_extra, body=body
            )
            if any(code in status for code in retry_statuses):
                last_exception = Exception(f"Retryable status: {status}")
                if attempt < max_retries:
                    wait_sec = 2 ** attempt
                    log(f"[HTTP] {status} on {path}, retrying in {wait_sec}s "
                        f"(attempt {attempt + 1}/{max_retries + 1})...")
                    time.sleep(wait_sec)
                    continue
            return status, hdrs, raw_hdrs, resp_body
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                wait_sec = 2 ** attempt
                log(f"[HTTP] Request failed: {e}, retrying in {wait_sec}s "
                    f"(attempt {attempt + 1}/{max_retries + 1})...")
                time.sleep(wait_sec)
            else:
                break
    raise last_exception or Exception(f"HTTP request failed after {max_retries + 1} attempts")


# ---------------------------------------------------------------------------
# RSA 加密（参考 ran_network_kpi_zs.py）
# ---------------------------------------------------------------------------


def _rsa_encrypt_pem(plaintext: str, public_key_b64: str) -> str:
    """使用 RSA 公钥（Base64 编码）对明文进行 PKCS1v15 加密，返回 Base64 密文。"""
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives import serialization

    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
    public_key = serialization.load_pem_public_key(pem.encode())
    encrypted = public_key.encrypt(plaintext.encode('utf-8'), asym_padding.PKCS1v15())
    return base64.b64encode(encrypted).decode('ascii')


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    """带时间戳的日志输出（UTF-8）。"""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


# ---------------------------------------------------------------------------
# 登录（纯接口 RSA 方式，参考 ran_network_kpi_zs.py）
# ---------------------------------------------------------------------------


def login_rsa(credentials: dict) -> dict | None:
    """RSA 纯接口登录 192.168.170.2。

    Returns:
        成功返回 {"cookie": ..., "forgery_token": ..., "host": ..., "port": ...}；
        失败返回 None（可能需要验证码）。
    """
    host = credentials["host"]
    port = credentials["port"]
    username = credentials["username"]
    password = credentials["password"]

    log("[LOGIN] Step 1: GET authorize page...")
    try:
        status, hdrs, raw_hdrs, body = _http_request(
            "GET",
            "/api/oauth2/v1/authorize?scope=user.login&response_type=code"
            "&redirect_uri=/uportal/framework/default.html",
            host, port,
        )
    except Exception as e:
        log(f"[LOGIN] authorize 请求失败: {e}")
        return None
    log(f"[LOGIN] authorize status: {status}")

    init_cookies = []
    forgery_token = ""
    for line in raw_hdrs.split("\r\n"):
        if line.lower().startswith("set-cookie:"):
            cookie_val = line.split(": ", 1)[1].split(";")[0]
            if cookie_val.split("=", 1)[-1]:
                init_cookies.append(cookie_val)
                if "forgerydefense" in cookie_val:
                    forgery_token = cookie_val.split("=", 1)[1]
    init_cookie_str = "; ".join(init_cookies)
    log(f"[LOGIN] Got {len(init_cookies)} cookies")

    html = body.decode('utf-8', errors='replace')
    lp_match = re.search(r'var\s+loginParameters\s*=\s*["\']([^"\']+)["\']', html)
    login_parameters = lp_match.group(1) if lp_match else ""

    # authorize 页面 HTML 可能引用 captcha 相关 JS/CSS，但 login_rsa 接口未必强制验证码。
    # 参考 ran_network_kpi_zs.py：不做此阻断性检查，直接尝试 RSA 登录；
    # 若 login_rsa 真的需要验证码会返回失败，再走 auth_info.json 回退。
    if re.search(r'captcha|verifycode|validatecode|checkcode', html, re.IGNORECASE):
        log("[LOGIN] authorize 页面含验证码关键字（仅提示，仍尝试 RSA 登录）")

    log("[LOGIN] Step 2: GET RSA public key...")
    rsa_headers = f"Cookie: {init_cookie_str}\r\nX-Requested-With: XMLHttpRequest\r\n"
    try:
        status, hdrs, raw_hdrs, body = _http_request(
            "GET", "/api/oauth2/v1/login/publickey", host, port,
            headers_extra=rsa_headers,
        )
    except Exception as e:
        log(f"[LOGIN] publickey 请求失败: {e}")
        return None

    public_key_b64 = ""
    if "200" in status:
        try:
            pk_data = json.loads(body.decode('utf-8'))
            public_key_b64 = pk_data.get("rsaPublicKey", "")
        except Exception as e:
            log(f"[LOGIN] 解析 publickey 响应失败: {e}")
    if not public_key_b64:
        log("[LOGIN] 未获取到 RSA 公钥")
        return None
    log(f"[LOGIN] Got rsaPublicKey ({len(public_key_b64)} chars)")

    log("[LOGIN] Step 3: RSA encrypt password...")
    try:
        encrypted_pwd = _rsa_encrypt_pem(password, public_key_b64)
    except Exception as e:
        log(f"[LOGIN] RSA 加密失败: {e}")
        return None

    log("[LOGIN] Step 4: POST login_rsa...")
    login_payload = json.dumps({
        "username": username,
        "password": encrypted_pwd,
        "parameters": login_parameters,
    })
    login_headers = (
        f"Content-Type: application/json\r\n"
        f"Cookie: {init_cookie_str}\r\n"
        f"Referer: https://{host}:{port}/api/oauth2/v1/authorize?scope=user.login"
        f"&response_type=code&redirect_uri=/uportal/framework/default.html\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
    )
    if forgery_token:
        login_headers += f"forgerydefense: {forgery_token}\r\n"

    try:
        status, hdrs, raw_hdrs, body = _http_request(
            "POST", "/api/oauth2/v1/login_rsa", host, port,
            headers_extra=login_headers, body=login_payload,
        )
    except Exception as e:
        log(f"[LOGIN] login_rsa 请求失败: {e}")
        return None
    log(f"[LOGIN] login_rsa status: {status}")

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

    # 判断登录成功（参考 ran_network_kpi_zs.py，合并多种判定以提升可靠性）：
    #   - 302 跳转 / 响应含 default.html / 拿到 Z-AUTH-CODE / Cookie 数 > 3
    success = ("302" in status or "default.html" in resp_text or
               any("Z-AUTH-CODE" in c for c in cookies) or len(cookies) > 3)
    if not success:
        log(f"[LOGIN] 登录未成功，响应: {resp_text[:300]}")
        return None

    log(f"[LOGIN] SUCCESS - {len(cookies)} cookies, forgery_token={forgery_token[:16]}...")
    return {
        "cookie": session_cookie,
        "forgery_token": forgery_token,
        "host": host,
        "port": port,
    }


def load_auth_info_fallback() -> dict | None:
    """从 auth_info.json 加载浏览器登录产生的鉴权信息（回退方案）。"""
    if not AUTH_INFO_FILE.exists():
        return None
    try:
        data = json.loads(AUTH_INFO_FILE.read_text(encoding='utf-8'))
        cookie = data.get("cookie", "")
        forgery_token = data.get("forgery_token", "")
        if not cookie or not forgery_token:
            return None
        log(f"[AUTH] 已加载 auth_info.json（登录时间: {data.get('login_time', '未知')}）")
        return {
            "cookie": cookie,
            "forgery_token": forgery_token,
            "host": data.get("host", ""),
            "port": data.get("port", 443),
        }
    except Exception as e:
        log(f"[AUTH] 加载 auth_info.json 失败: {e}")
        return None


def auth_info_is_fresh(max_age_hours: float = 1.0) -> bool:
    """判断 auth_info.json 是否存在且未过期。

    UME 会话通常几小时就失效，过期文件继续用只会拿到 401；此处按文件内
    ``login_time``（缺失时回退文件 mtime）判断。

    2026-10-06：默认窗口由 8 小时压到 1 小时。192.168.170.2 的会话寿命是**实测**
    出来的（最近 8 天日志：21 次诞生、20 次在下一轮之前被 401 证实已死，
    证死年龄 58~60 分钟），8 小时窗口全是空头信任。口径与 auth_manager 的
    AUTH_TTL_OVERRIDES 中该主机一致，改一处要改两处，否则共享缓存放短了、
    这个回退文件还按 8 小时自欺。
    """
    if not AUTH_INFO_FILE.exists():
        return False
    try:
        data = json.loads(AUTH_INFO_FILE.read_text(encoding='utf-8'))
        stamp = data.get("login_time") or ""
        try:
            logged_at = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            logged_at = datetime.fromtimestamp(AUTH_INFO_FILE.stat().st_mtime)
        age_h = (datetime.now() - logged_at).total_seconds() / 3600.0
        if age_h > max_age_hours:
            log(f"[AUTH] auth_info.json 已过期（{age_h:.1f}h > {max_age_hours}h）")
            return False
        return True
    except Exception:
        return False


def ensure_auth_info(force: bool = False, max_age_hours: float = 1.0) -> bool:
    """确保 auth_info.json 可用（浏览器登录脚本已不在仓库，此处用 RSA 接口兜底生成）。

    背景：RSA 纯接口登录失败时会回退读 auth_info.json，但该文件原本由
    ``battary_kpi_login.py``（Playwright）生成，而生成脚本与 playwright 依赖
    都已不在本仓库 —— 回退链实际是空的，任务必然报
    「RSA 登录未成功且无可用 auth_info.json」。

    这里用 credential_store 的账号密码（battery_ume 分组）调同一套 RSA 接口，
    成功后写出与浏览器脚本兼容的 auth_info.json，让回退链真正可用。

    Returns:
        True 表示存在可用的 auth_info.json（含本次新生成）。
    """
    if not force and auth_info_is_fresh(max_age_hours):
        return True

    credentials = load_credentials(None)
    log(f"[AUTH] 尝试经 RSA 接口生成 auth_info.json（{credentials['host']}:{credentials['port']}）")
    auth = login_rsa(credentials)
    if not auth or not auth.get("cookie"):
        log("[AUTH] RSA 接口登录失败，无法生成 auth_info.json"
            "（该 UME 可能已启用图形验证码，需人工介入）")
        return False

    payload = {
        "cookie": auth["cookie"],
        "forgery_token": auth.get("forgery_token", ""),
        "host": auth.get("host") or credentials["host"],
        "port": auth.get("port") or credentials["port"],
        "username": credentials["username"],
        "login_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "ensure_auth_info (RSA interface)",
    }
    tmp = AUTH_INFO_FILE.with_name(AUTH_INFO_FILE.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(str(tmp), str(AUTH_INFO_FILE))
        log(f"[AUTH] auth_info.json 已生成 → {AUTH_INFO_FILE}")
        return True
    except OSError as e:
        log(f"[AUTH] 写入 auth_info.json 失败: {e}")
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return False


# ---------------------------------------------------------------------------
# 鉴权请求头构造
# ---------------------------------------------------------------------------


def _auth_headers(cookie: str, forgery_token: str, referer: str | None = None,
                  extra: dict | None = None) -> str:
    """构造 API 鉴权请求头。"""
    ref = referer or f"https://{_HOST}/uportal/framework/default.html"
    headers = (
        f"Content-Type: application/json; charset=UTF-8\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Encoding: gzip\r\n"
        f"Cookie: {cookie}\r\n"
        f"Referer: {ref}\r\n"
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


def _api_path_with_token(path: str, forgery_token: str) -> str:
    """拼装带 forgerydefense 查询参数的 API path。"""
    qs = urlencode({"forgerydefense": forgery_token})
    return f"{path}?{qs}"


# ---------------------------------------------------------------------------
# 安全写文件（文件被占用时自动加序号）
# ---------------------------------------------------------------------------


def write_json_safe(path: Path, data) -> Path:
    for attempt in range(20):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return path
        except (PermissionError, OSError) as exc:
            log(f"写入 {path.name} 失败（{exc}），尝试新路径...")
            path = path.parent / f"{path.stem}_{attempt + 1}{path.suffix}"
    raise RuntimeError(f"无法写入文件：{path.parent}（已尝试 20 次）")


def write_bytes_safe(path: Path, data: bytes) -> Path:
    for attempt in range(20):
        try:
            with open(path, "wb") as f:
                f.write(data)
            return path
        except (PermissionError, OSError) as exc:
            log(f"写入 {path.name} 失败（{exc}），尝试新路径...")
            path = path.parent / f"{path.stem}_{attempt + 1}{path.suffix}"
    raise RuntimeError(f"无法写入文件：{path.parent}（已尝试 20 次）")


def write_excel_safe(path: Path, df: pd.DataFrame, sheet_name: str = "Sheet1") -> Path:
    for attempt in range(20):
        try:
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
            return path
        except (PermissionError, OSError) as exc:
            log(f"写入 {path.name} 失败（{exc}），尝试新路径...")
            path = path.parent / f"{path.stem}_{attempt + 1}{path.suffix}"
    raise RuntimeError(f"无法写入文件：{path.parent}（已尝试 20 次）")


def write_csv_safe(path: Path, df: pd.DataFrame) -> Path:
    for attempt in range(20):
        try:
            df.to_csv(path, index=False, encoding="utf-8-sig")
            return path
        except (PermissionError, OSError) as exc:
            log(f"写入 {path.name} 失败（{exc}），尝试新路径...")
            path = path.parent / f"{path.stem}_{attempt + 1}{path.suffix}"
    raise RuntimeError(f"无法写入文件：{path.parent}（已尝试 20 次）")


# ---------------------------------------------------------------------------
# API 调用（原始 socket）
# ---------------------------------------------------------------------------


class AuthExpiredError(Exception):
    """上游返回 401/403（会话失效）专用异常。

    与普通请求失败区分开的原因：普通失败（网络抖动、单页 5xx）在分页循环里
    的既有语义是"丢一页、保留已取数据"；而会话失效后继续用同一会话翻页只会
    页页 401，并且 battery_kpi_service 落库时对 battery_latest 是"先清空再整表
    写入"—— 把半截数据当全量快照落库等于看板丢站点。上层捕获本异常后作废
    共享缓存（auth_manager.invalidate_cache）、强制重登并整体重试一次。
    """


def _status_code(status_line: str) -> int:
    """从状态行（如 'HTTP/1.1 401 Unauthorized'）解析数字状态码，解析失败返回 0。"""
    for token in status_line.split():
        if token.isdigit():
            return int(token)
    return 0


def _post_json(path: str, auth: dict, payload: dict) -> tuple[str, dict, bytes]:
    """POST JSON 到指定 API path，返回 (status, headers, body_bytes)。"""
    full_path = _api_path_with_token(path, auth["forgery_token"])
    body = json.dumps(payload, ensure_ascii=False)
    headers = _auth_headers(auth["cookie"], auth["forgery_token"])
    status, hdrs, _, resp_body = _http_request_with_retry(
        "POST", full_path, auth["host"], auth["port"],
        headers_extra=headers, body=body,
    )
    return status, hdrs, resp_body


def fetch_standard_point(auth: dict) -> dict:
    """获取 r32.uedm.batt 测量点元数据。"""
    log("[API] standard-point →")
    payload = {"moc": [MOC], "name": ""}
    status, hdrs, resp_body = _post_json(PATH_STANDARD_POINT, auth, payload)
    log(f"[API] standard-point status: {status}")
    if "200" not in status:
        raise Exception(f"standard-point 失败: {status}, body={resp_body[:500]}")
    data = json.loads(resp_body.decode('utf-8', errors='replace'))
    log(f"[API] standard-point 响应长度: {len(resp_body)} 字节")
    return data


def fetch_realtime_page(auth: dict, page_no: int, page_size: int) -> dict:
    """拉取指定页的实时数据。"""
    payload = {
        "pageNo": page_no,
        "pageSize": page_size,
        "moc": MOC,
        "smpId": SMP_IDS,
        "moName": "",
        "position": [],
    }
    status, hdrs, resp_body = _post_json(PATH_GET_BY_CONDITION, auth, payload)
    code = _status_code(status)
    if code in (401, 403):
        # 401/403 = 会话死了：既不属于可重试的瞬时错误，也不属于"丢一页保其余"
        # 的数据错误（继续翻页只会页页 401）。抛专用异常交上层做重登恢复，
        # 见 AuthExpiredError 与 battery_kpi_service.fetch_battery_records。
        raise AuthExpiredError(
            f"get-by-condition 第 {page_no} 页会话失效: {status}, body={resp_body[:200]}")
    if "200" not in status:
        raise Exception(f"get-by-condition 第 {page_no} 页失败: {status}, body={resp_body[:500]}")
    return json.loads(resp_body.decode('utf-8', errors='replace'))


def fetch_all_realtime(auth: dict) -> tuple[dict, list[dict]]:
    """分页拉取所有电池实时数据。"""
    log(f"[API] get-by-condition 开始分页拉取（pageSize={PAGE_SIZE}）")
    first_page = fetch_realtime_page(auth, 1, PAGE_SIZE)

    records, total, page_size_returned = _extract_page(first_page)
    all_records: list[dict] = list(records)
    log(f"[API] 第 1 页记录数: {len(records)}，total={total}")

    if total and page_size_returned:
        total_pages = min(math.ceil(total / page_size_returned), MAX_PAGES)
    else:
        total_pages = MAX_PAGES if len(records) >= PAGE_SIZE else 1

    for page_no in range(2, total_pages + 1):
        try:
            page_data = fetch_realtime_page(auth, page_no, PAGE_SIZE)
        except AuthExpiredError:
            # 会话失效：向上抛给调用方做 401 恢复（作废缓存+重登+整体重试）。
            # 绝不能像普通失败那样 break —— 那会把半截数据当全量快照交给落库
            # （battery_latest 先清空再整表写入，半截数据 = 看板丢站点）
            raise
        except Exception as exc:
            log(f"[API] 第 {page_no} 页拉取失败：{exc}，停止分页")
            break
        page_records, _, _ = _extract_page(page_data)
        if not page_records:
            log(f"[API] 第 {page_no} 页无记录，停止分页")
            break
        all_records.extend(page_records)
        log(f"[API] 第 {page_no}/{total_pages} 页记录数: {len(page_records)}，累计: {len(all_records)}")
        if len(page_records) < PAGE_SIZE:
            break

    log(f"[API] 分页拉取完成，总记录数: {len(all_records)}")
    return first_page, all_records


def _extract_page(page_resp) -> tuple[list[dict], int | None, int | None]:
    """从分页响应中自适应提取 (记录列表, total, pageSize)。

    兼容多种返回结构，包括 192.168.170.2 的 data.values 结构：
      - {"data": {"values": [...], "total": N, "titles": {...}}}
      - {"data": {"list": [...], "total": N, "pageSize": M}}
      - {"data": {"records": [...], "total": N, "size": M}}
      - {"data": [...]}
    """
    if not isinstance(page_resp, dict):
        return [], None, None
    body = page_resp.get("data", page_resp)
    records: list[dict] = []
    total: int | None = None
    page_size: int | None = None
    if isinstance(body, list):
        records = body
    elif isinstance(body, dict):
        # values 在前（192.168.170.2 实际结构），其余兼容其它 UME 版本
        for key in ("values", "list", "records", "rows", "items", "result"):
            val = body.get(key)
            if isinstance(val, list):
                records = val
                break
        total = body.get("total") or page_resp.get("total")
        page_size = body.get("pageSize") or body.get("size") or PAGE_SIZE
    return records, total, page_size


def _extract_titles(page_resp) -> dict:
    """从首页响应提取 titles（列名映射），用于结构化时重命名列。

    titles 结构示例：
      {"mo": "Monitor Object", "position": "Position",
       "batt.health": {"name": "Battery Health(%)",
                       "batt.health.value": "Value",
                       "batt.health.updateTime": "Update Time"}, ...}
    """
    if not isinstance(page_resp, dict):
        return {}
    body = page_resp.get("data", page_resp)
    if isinstance(body, dict):
        titles = body.get("titles")
        if isinstance(titles, dict):
            return titles
    return {}


def call_export(auth: dict) -> tuple[Path | None, dict | None]:
    """调用 export 接口触发后端导出。"""
    log("[API] export →")
    payload = {
        "mocSmpParam": {MOC: SMP_IDS},
        "moName": "",
        "position": [],
    }
    status, hdrs, resp_body = _post_json(PATH_EXPORT, auth, payload)
    content_type = hdrs.get("content-type", "").lower()
    log(f"[API] export status: {status}，Content-Type: {content_type}")

    binary_ct = any(t in content_type for t in
                    ("application/octet-stream", "excel", "spreadsheet", "csv", "zip"))
    cd = hdrs.get("content-disposition", "")
    has_filename = "filename" in cd.lower()

    if binary_ct or (has_filename and "json" not in content_type):
        ext = _guess_extension(content_type, cd)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = OUTPUT_DIR / f"battery_export_{ts}{ext}"
        saved = write_bytes_safe(filepath, resp_body)
        log(f"[API] export 文件已保存: {saved.name}（{len(resp_body)} 字节）")
        return saved, None

    try:
        data = json.loads(resp_body.decode('utf-8', errors='replace'))
    except Exception:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = OUTPUT_DIR / f"battery_export_{ts}.bin"
        saved = write_bytes_safe(filepath, resp_body)
        log(f"[API] export 未知响应类型，已保存为: {saved.name}")
        return saved, None

    log(f"[API] export JSON 响应长度: {len(resp_body)} 字节")
    return None, data


def _guess_extension(content_type: str, content_disposition: str) -> str:
    cd_lower = content_disposition.lower()
    m = re.search(r'filename\*?=(?:utf-8\'\')?"?([^";]+)"?', cd_lower)
    if m:
        ext = Path(m.group(1).strip()).suffix
        if ext:
            return ext
    if "spreadsheet" in content_type or "excel" in content_type:
        return ".xlsx"
    if "csv" in content_type:
        return ".csv"
    if "zip" in content_type:
        return ".zip"
    if "pdf" in content_type:
        return ".pdf"
    return ".bin"


# ---------------------------------------------------------------------------
# 数据结构化（pandas 向量化，与 battary_kpi_fetch.py 同逻辑）
# ---------------------------------------------------------------------------


def flatten_records(records: list[dict], smp_meta: dict | None = None,
                    titles: dict | None = None) -> pd.DataFrame:
    """将实时数据记录扁平化为 DataFrame（向量化操作）。

    Args:
        records: get-by-condition 返回的记录列表
        smp_meta: standard-point 返回的测量点元数据（备用列名映射）
        titles: get-by-condition 首页 data.titles（列名映射，优先级高于 smp_meta）
    """
    if not records:
        log("[DATA] 无记录可结构化")
        return pd.DataFrame()

    smp_name_map = _build_smp_name_map(smp_meta)
    titles_rename = _build_titles_rename_map(titles)
    sample = records[0]

    # 策略 A：记录直接含 smpId + smpValue
    if isinstance(sample, dict) and "smpId" in sample and any(
        k in sample for k in ("smpValue", "value", "smpvalue", "val")
    ):
        df = pd.DataFrame(records)
        value_col = next((c for c in ("smpValue", "value", "smpvalue", "val") if c in df.columns), None)
        if value_col is None:
            return _apply_rename(df, titles_rename, smp_name_map)
        pivot = df.pivot_table(
            index=[c for c in df.columns if c not in ("smpId", value_col)],
            columns="smpId",
            values=value_col,
            aggfunc="last",
        ).reset_index()
        pivot.columns.name = None
        pivot = _rename_smp_columns(pivot, smp_name_map)
        log(f"[DATA] 策略 A 透视完成：{len(pivot)} 行 × {len(pivot.columns)} 列")
        return _apply_rename(pivot, titles_rename, smp_name_map)

    # 策略 B：记录含 smpList / smps 数组（注意：values 已是实际记录字段，不在此次）
    for list_key in ("smpList", "smps", "smpListRt", "smpData"):
        if isinstance(sample, dict) and list_key in sample and isinstance(sample[list_key], list):
            df = pd.DataFrame(records)
            try:
                exploded = df.explode(list_key, ignore_index=True)
                sub = pd.json_normalize(exploded[list_key])
                sub.columns = [f"{list_key}.{c}" for c in sub.columns]
                merged = pd.concat(
                    [exploded.drop(columns=[list_key]).reset_index(drop=True), sub], axis=1
                )
                smpid_col = f"{list_key}.smpId"
                value_candidates = [f"{list_key}.{v}" for v in ("smpValue", "value", "smpvalue", "val")]
                value_col = next((c for c in value_candidates if c in merged.columns), None)
                if smpid_col in merged.columns and value_col:
                    index_cols = [c for c in merged.columns if c not in (smpid_col, value_col)]
                    pivot = merged.pivot_table(
                        index=index_cols,
                        columns=smpid_col,
                        values=value_col,
                        aggfunc="last",
                    ).reset_index()
                    pivot.columns.name = None
                    pivot = _rename_smp_columns(pivot, smp_name_map)
                    log(f"[DATA] 策略 B（{list_key}）展开完成：{len(pivot)} 行 × {len(pivot.columns)} 列")
                    return _apply_rename(pivot, titles_rename, smp_name_map)
                return _apply_rename(merged, titles_rename, smp_name_map)
            except Exception as exc:
                log(f"[DATA] 策略 B（{list_key}）展开失败：{exc}，回退原始 DataFrame")
                return _apply_rename(df, titles_rename, smp_name_map)

    # 策略 C：直接 json_normalize（192.168.170.2 的 data.values 扁平记录走此分支）
    try:
        df = pd.json_normalize(records)
        log(f"[DATA] 策略 C json_normalize：{len(df)} 行 × {len(df.columns)} 列")
        return _apply_rename(df, titles_rename, smp_name_map)
    except Exception:
        return _apply_rename(pd.DataFrame(records), titles_rename, smp_name_map)


def _build_titles_rename_map(titles: dict | None) -> dict[str, str]:
    """从 get-by-condition 首页 data.titles 构建列名重命名映射。

    titles 结构：
      {"mo": "Monitor Object",
       "batt.health": {"name": "Battery Health(%)",
                       "batt.health.value": "Value",
                       "batt.health.updateTime": "Update Time"}}

    生成映射：
      mo -> "Monitor Object"
      batt.health.value -> "Battery Health(%) - Value"
      batt.health.updateTime -> "Battery Health(%) - Update Time"
    """
    if not titles:
        return {}
    rename: dict[str, str] = {}
    for key, val in titles.items():
        if isinstance(val, str):
            # 简单字段：mo -> "Monitor Object"
            if key != val:
                rename[key] = val
        elif isinstance(val, dict):
            # 嵌套字段：测量点的 value/updateTime 子列
            group_name = val.get("name", key)
            for sub_key, sub_val in val.items():
                if sub_key == "name":
                    continue
                if isinstance(sub_val, str) and sub_key != sub_val:
                    rename[sub_key] = f"{group_name} - {sub_val}"
    return rename


def _apply_rename(df: pd.DataFrame, titles_rename: dict[str, str],
                  smp_name_map: dict[str, str]) -> pd.DataFrame:
    """应用列名重命名（titles 优先，smp_name_map 兜底）。向量化 rename。"""
    if df.empty:
        return df
    if titles_rename:
        # 仅重命名实际存在的列
        rename_dict = {c: titles_rename[c] for c in df.columns if c in titles_rename}
        if rename_dict:
            df = df.rename(columns=rename_dict)
            log(f"[DATA] 已按 titles 重命名 {len(rename_dict)} 列")
    elif smp_name_map:
        df = _rename_smp_columns(df, smp_name_map)
    return df


def _build_smp_name_map(smp_meta: dict | None) -> dict[str, str]:
    if not smp_meta:
        return {}
    name_map: dict[str, str] = {}

    def _walk(obj):
        if isinstance(obj, dict):
            smp_id = obj.get("smpId") or obj.get("id") or obj.get("name")
            display = obj.get("displayName") or obj.get("label") or obj.get("cnName") or obj.get("description")
            if smp_id and display:
                name_map[str(smp_id)] = str(display)
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(smp_meta)
    return name_map


def _rename_smp_columns(df: pd.DataFrame, smp_name_map: dict[str, str]) -> pd.DataFrame:
    if not smp_name_map:
        return df
    new_cols = []
    for c in df.columns:
        if str(c) in smp_name_map:
            new_cols.append(f"{smp_name_map[str(c)]} ({c})")
        else:
            new_cols.append(c)
    df.columns = new_cols
    return df


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main(args=None) -> int:
    global _HOST, _PORT
    """主流程：鉴权 → 拉取元数据 → 分页实时数据 → 导出 → 结构化。"""
    start = time.time()
    print(f"[MAIN] Battery KPI API 抓取（Socket+RSA 方式）开始: "
          f"{time.strftime('%Y-%m-%d %H:%M:%S')}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log(f"输出目录: {OUTPUT_DIR}")

    # 1. 加载凭据（命令行参数 > 环境变量 > credential_store > url.txt > 内置默认值）
    credentials = load_credentials(args)
    _HOST = credentials["host"]
    _PORT = credentials["port"]
    log(f"目标: {_HOST}:{_PORT}, 用户: {credentials['username']}")

    # 2. 登录：先尝试 RSA 纯接口，失败回退 auth_info.json
    log("=" * 60)
    log("[STEP 1] 鉴权（RSA 纯接口登录，失败回退 auth_info.json）")
    log("=" * 60)
    t0 = time.time()
    auth = login_rsa(credentials)
    if auth is None:
        log("[LOGIN] RSA 纯接口登录失败（可能需要验证码），尝试回退到 auth_info.json...")
        auth = load_auth_info_fallback()
        if auth is None:
            print("[MAIN] 鉴权失败：RSA 登录未成功且无可用 auth_info.json。")
            print("       可先执行 ensure_auth_info(force=True) 生成鉴权文件，"
                  "或在「设置 → 凭据管理 → Battery UME」核对账号密码后重试。")
            return 1
        log("[AUTH] 使用 auth_info.json 中的鉴权信息继续")
    # 回退场景下 host/port 可能缺失，用 url.txt 补全
    if not auth.get("host"):
        auth["host"] = credentials["host"]
        auth["port"] = credentials["port"]
        _HOST = auth["host"]
        _PORT = auth["port"]
    log(f"鉴权完成，耗时 {time.time() - t0:.2f}s")

    # 3. 调用 3 个 API
    try:
        # 3.1 standard-point
        log("=" * 60)
        log("[STEP 2] standard-point 测量点元数据")
        log("=" * 60)
        t0 = time.time()
        smp_meta = fetch_standard_point(auth)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        smp_path = write_json_safe(OUTPUT_DIR / f"standard_point_{ts}.json", smp_meta)
        log(f"元数据已保存: {smp_path.name}（耗时 {time.time() - t0:.2f}s）")

        # 3.2 get-by-condition
        log("=" * 60)
        log("[STEP 3] get-by-condition 分页实时数据")
        log("=" * 60)
        t0 = time.time()
        first_page, all_records = fetch_all_realtime(auth)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        write_json_safe(OUTPUT_DIR / f"realtime_page1_{ts}.json", first_page)
        all_path = write_json_safe(OUTPUT_DIR / f"realtime_all_{ts}.json", all_records)
        log(f"全部记录已保存: {all_path.name}（耗时 {time.time() - t0:.2f}s）")
        # 提取首页 titles（列名映射），用于结构化时重命名列
        titles = _extract_titles(first_page)
        if titles:
            log(f"[DATA] 已提取 titles（{len(titles)} 个字段组）")

        # 3.3 export
        log("=" * 60)
        log("[STEP 4] export 触发导出")
        log("=" * 60)
        t0 = time.time()
        export_file, export_json = call_export(auth)
        if export_json is not None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_json_path = write_json_safe(OUTPUT_DIR / f"export_response_{ts}.json", export_json)
            log(f"export JSON 响应已保存: {export_json_path.name}")
        log(f"export 耗时 {time.time() - t0:.2f}s")

        # 4. 结构化
        log("=" * 60)
        log("[STEP 5] 结构化数据并写入 Excel/CSV")
        log("=" * 60)
        t0 = time.time()
        df = flatten_records(all_records, smp_meta, titles)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not df.empty:
            excel_path = write_excel_safe(OUTPUT_DIR / f"battery_realtime_{ts}.xlsx", df, "battery")
            log(f"Excel 已保存: {excel_path.name}（{len(df)} 行 × {len(df.columns)} 列）")
            csv_path = write_csv_safe(OUTPUT_DIR / f"battery_realtime_{ts}.csv", df)
            log(f"CSV 已保存: {csv_path.name}")

            print("\n[PREVIEW] 数据预览（前 5 行）：")
            with pd.option_context("display.max_columns", None, "display.width", 200,
                                   "display.max_colwidth", 30):
                print(df.head(5).to_string())
        else:
            log("无数据可写入 Excel")
        log(f"结构化耗时 {time.time() - t0:.2f}s")

    except Exception as exc:
        import traceback
        print(f"[MAIN] 流程异常: {exc}")
        traceback.print_exc()
        return 1

    total_elapsed = time.time() - start
    print(f"\n[MAIN] 全部完成，总耗时 {total_elapsed:.2f} 秒")
    return 0


if __name__ == "__main__":
    cli_args = parse_args()
    sys.exit(main(cli_args))
