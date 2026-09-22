# -*- coding: utf-8 -*-
"""
MW UME KPI 数据同步服务（集成 my_app 版本，零落盘直写主库）

与原 backend/services/mw_ume/mw_ume_kpi.py 的关系：
- 保留原脚本完整 HTTP 协议层（登录 / 建查询 / 轮询 / 导出，socket + RSA 登录）。
- 改造点（对应需求「数据不落地，直接写入数据库」）：
  1. export_history_to_memory：导出结果保持在内存 bytes，不再写 xlsx 文件；
  2. read_xlsx_bytes：从内存 bytes 解析 Excel，不落盘；
  3. save_to_db：直接写入 my_app 主库 app.db（backend.database.get_raw_connection，
     sqlite/PG 双模 upsert），固定表名 mw_ume_bw_ultilazation；
  4. 移除原脚本的 FTP 上传、xlsx 落盘/清理、独立 sqlite 文件流程。

定时任务：每天 05:15（task_registry.py TASK_SPECS -> default_cron="15 5 * * *"）。

鉴权信息来源：
- 默认：192.168.169.247:28001, NOC_MW / Zte@202608（与原脚本一致）
- 优先：credential_store（key="mw_ume"，Settings 页面可改密，免重启生效）
- 环境变量覆盖：MW_UME_HOST / MW_UME_PORT / MW_UME_USER / MW_UME_PASSWORD
"""

import base64
import gc
import gzip
import io
import json
import logging
import os
import re
import socket
import ssl
import sys
import time
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

import openpyxl

from backend.database import get_raw_connection
from backend.dialect_helpers import table_columns, upsert, safe_pragma

logger = logging.getLogger("mw_ume_kpi_service")

# 强制 UTF-8 输出（Windows worker 日志）
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# ============================================================
# 配置（与原脚本一致；可经环境变量 / credential_store 覆盖）
# ============================================================
HOST = os.environ.get("MW_UME_HOST", "192.168.169.247")
PORT = int(os.environ.get("MW_UME_PORT", "28001"))
USERNAME = os.environ.get("MW_UME_USER", "NOC_MW")
PASSWORD = os.environ.get("MW_UME_PASSWORD", "Zte@202608")
LOGIN_PORTAL = "/uportal/framework/default.html"

# 查询时间范围：默认最近 1 天（昨天 00:00:00 到今天 00:00:00 UTC）
DAYS_BACK = int(os.environ.get("MW_UME_KPI_DAYS_BACK", "1"))
# 并行查询线程数（当前仅 1 个 FINBI 查询）
MAX_PARALLEL_WORKERS = int(os.environ.get("MW_UME_KPI_PARALLEL_WORKERS", "4"))

# PM 接口路径
HISTORY_PATH = "/api/pm-analysis/v2/history"
HISTORY_POLL_PATH = "/api/pm-analysis/v1/history"
HISTORY_EXPORT_PATH = "/api/pm-analysis/v3/history/export"

# 目标表名（用户指定，保持原拼写）
TABLE_NAME = os.environ.get("MW_UME_KPI_TABLE", "mw_ume_bw_ultilazation")

# 标识列候选（用于联合主键去重）
IDENTITY_COL_CANDIDATES = ["NE", "ME", "Managed Element", "SERVICE", "Measurement Object"]

# gr 显示名称替换规则
GR_RENAME = {
    "900": "15min",
    "3600": "1hour",
    "86400": "1Day",
}

# ---------- 15 分钟实时（RT）同步配置 ----------
# 独立表：避免 15 分钟行混入日粒度表影响现有拓扑看板的「最新日期」口径
RT_TABLE_NAME = os.environ.get("MW_UME_KPI_TABLE_RT", "mw_ume_bw_ultilazation_rt")
# 每次同步回看窗口（小时）：取最近 2 小时，展示只用最新一个 15 分钟槽位
RT_WINDOW_HOURS = float(os.environ.get("MW_UME_KPI_RT_WINDOW_HOURS", "2"))
# RT 表保留期（小时）：仅保留最近 N 小时数据（默认 25h，覆盖看板 24h 趋势 + 1h 出数延迟容忍），
# 每次同步末尾顺带清理更早的槽位，避免该表无限增长（实测约 721 行/槽、~70,900 行/天）。
RT_RETENTION_HOURS = float(os.environ.get("MW_UME_KPI_RT_RETENTION_HOURS", "25"))
# RT 查询粒度（秒）：900 = 15 分钟
RT_GR = os.environ.get("MW_UME_KPI_RT_GR", "900")


def _runtime_credentials():
    """运行时获取凭据（环境变量 > credential_store > 模块默认值）。"""
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        try:
            from credential_store import get_credential
        except ImportError:
            return USERNAME, PASSWORD
    return get_credential("mw_ume", USERNAME, PASSWORD)


# ============================================================
# KPI 查询配置（与原脚本 url.txt 严格一致，字段顺序敏感）
# ============================================================
_FINBI_CONFIG = {
    "favoriteconditionname": "FINBI",
    "gr": "86400",
    "groupbygroup": False,
    "filterlayer": "all",
    "grouplayer": "orignaldata_layermoc",
    "motid": "BNCTN.PMP",
    "nfctid": (
        "bn.me.ZXMW.ER2020D.V2A,"
        "bn.me.ZXMW.ER2020E.V2A,"
        "bn.me.ZXMW.ER2020H.V2A,"
        "bn.me.ZXMW.ER2020.V2A,"
        "bn.me.ZXMW.NR8000TR.A1,"
        "bn.me.ZXMW.NR8000TR.V2A,"
        "bn.me.ZXMW.NR8120.A1,"
        "bn.me.ZXMW.NR8120.V2A,"
        "bn.me.ZXMW.NR8150.A1,"
        "bn.me.ZXMW.NR8150.V2A,"
        "bn.me.ZXMW.NR8250.A1,"
        "bn.me.ZXMW.NR8250.V2A,"
        "bn.me.ZXMW.NR8950.A1,"
        "bn.me.ZXMW.NR8961.EBU.V2A,"
        "bn.me.ZXMW.NR8961.V2A,"
        "bn.me.ZXMW.NR9000TR.V2A,"
        "bn.me.ZXMW.NR9120.V2A,"
        "bn.me.ZXMW.NR9150.V2A,"
        "bn.me.ZXMW.NR9250.V2A,"
        "bn.me.ZXMW.NR9350.V2A,"
        "bn.me.ZXMW.NR9961.MBU.V2A"
    ),
    "items": [
        "C083085151",
        "C083085153",
        "C083085155",
        "C083085161",
        "C083085163",
        "C083085165",
    ],
    "itemsposition": [0, 0, 0, 0, 0, 0],
    "itemsposition1": [0, 0, 0, 0, 0, 0],
    "templatename": "FINBI",
    "templateid": "1700328565985",
    "containvcell": 0,
    "drawitems": [],
}

MW_UME_KPI_QUERY_CONFIGS = {"FINBI": _FINBI_CONFIG}
MW_UME_KPI_TASKS = [{"key": "FINBI"}]


# ============================================================
# 外部化配置（Settings →「任务配置」页维护的 mw_ume_config.json）
#   优先级：环境变量 > 配置文件 > 内置默认；凭据走 credential_store(mw_ume)。
#   文件缺失/损坏时行为与旧版完全一致（用上面的内置默认）。
#   ⚠ 必须在 HISTORY_REFERER 与查询 dict 构造之前完成覆盖：这三者都在导入期
#     用当时的 HOST/PORT/模板值算出，晚于本行的赋值不会影响它们。
# ============================================================
# ⚠ 路径必须与 task_configs_registry 注册的路径一致（backend/services/ 下）：
#   本模块在 mw_ume/ 子包内，要用 parents[1]，写 parent 会导致页面保存的文件没人读。
_MW_CONFIG_PATH = Path(__file__).resolve().parents[1] / "mw_ume_config.json"

try:
    from backend.services.task_config_files import load_json_config, normalize_query_configs
    _MW_CONF = load_json_config(_MW_CONFIG_PATH)
except ImportError:
    from task_config_files import load_json_config, normalize_query_configs  # type: ignore
    _MW_CONF = load_json_config(_MW_CONFIG_PATH)
except Exception as _e:  # noqa: BLE001 - 配置读取失败一律回退内置默认
    _MW_CONF = None

if _MW_CONF:
    if not os.environ.get("MW_UME_HOST"):
        HOST = str(_MW_CONF.get("host") or HOST).strip() or HOST
    if not os.environ.get("MW_UME_PORT") and _MW_CONF.get("port"):
        PORT = int(_MW_CONF["port"])
    if not os.environ.get("MW_UME_KPI_DAYS_BACK") and _MW_CONF.get("days_back"):
        DAYS_BACK = max(1, int(_MW_CONF["days_back"]))
    if not os.environ.get("MW_UME_KPI_PARALLEL_WORKERS") and _MW_CONF.get("max_parallel_workers"):
        MAX_PARALLEL_WORKERS = max(1, int(_MW_CONF["max_parallel_workers"]))
    if _MW_CONF.get("login_portal"):
        LOGIN_PORTAL = str(_MW_CONF["login_portal"])
    _mw_urls = _MW_CONF.get("urls") or {}
    if isinstance(_mw_urls, dict):
        if _mw_urls.get("history"):
            HISTORY_PATH = _mw_urls["history"]
        if _mw_urls.get("poll"):
            HISTORY_POLL_PATH = _mw_urls["poll"]
        if _mw_urls.get("export"):
            HISTORY_EXPORT_PATH = _mw_urls["export"]
    if not os.environ.get("MW_UME_KPI_TABLE") and _MW_CONF.get("table_name"):
        TABLE_NAME = str(_MW_CONF["table_name"]).strip()
    _mw_rt = _MW_CONF.get("rt") or {}
    if isinstance(_mw_rt, dict):
        if not os.environ.get("MW_UME_KPI_TABLE_RT") and _mw_rt.get("table_name"):
            RT_TABLE_NAME = str(_mw_rt["table_name"]).strip()
        if not os.environ.get("MW_UME_KPI_RT_WINDOW_HOURS") and _mw_rt.get("window_hours"):
            RT_WINDOW_HOURS = float(_mw_rt["window_hours"])
        if not os.environ.get("MW_UME_KPI_RT_RETENTION_HOURS") and _mw_rt.get("retention_hours"):
            RT_RETENTION_HOURS = float(_mw_rt["retention_hours"])
        if not os.environ.get("MW_UME_KPI_RT_GR") and _mw_rt.get("gr"):
            RT_GR = str(_mw_rt["gr"])
    # KPI 模板：配置文件里的每一行按自身的 key 合并到内置模板之上。
    # 不锁死 "FINBI"：页面上改标识、增删模板都要能生效（标识被改也不至于整套模板失效）。
    _mw_qc = normalize_query_configs(_MW_CONF.get("query_configs") or [])
    if _mw_qc:
        MW_UME_KPI_QUERY_CONFIGS = {
            k: dict(_FINBI_CONFIG, **{f: v for f, v in row.items() if f != "key"})
            for k, row in _mw_qc.items()
        }
        MW_UME_KPI_TASKS = [{"key": k} for k in MW_UME_KPI_QUERY_CONFIGS]

# Referer 依赖可能被上面覆盖过的 HOST/PORT/LOGIN_PORTAL，故在其之后计算
HISTORY_REFERER = f"https://{HOST}:{PORT}{LOGIN_PORTAL}"

# 15 分钟实时（RT）查询：沿用上面（可能已被配置覆盖过的）同一批模板，仅把粒度换成 RT_GR
MW_UME_KPI_QUERY_CONFIGS_RT = {f"{k}_RT": dict(cfg, gr=RT_GR)
                               for k, cfg in MW_UME_KPI_QUERY_CONFIGS.items()}
MW_UME_KPI_TASKS_RT = [{"key": k} for k in MW_UME_KPI_QUERY_CONFIGS_RT]


# ============================================================
# HTTP / SSL 工具函数（与原脚本一致）
# ============================================================
def _create_ssl_socket():
    """创建绕过证书校验的 TLS socket。"""
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
                    logger.info(f"[HTTP] {status} on {path}, retrying in {wait_sec}s "
                                f"(attempt {attempt + 1}/{max_retries + 1})...")
                    time.sleep(wait_sec)
                    continue
            return status, hdrs, raw_hdrs, resp_body
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                wait_sec = 2 ** attempt
                logger.info(f"[HTTP] Request failed: {e}, retrying in {wait_sec}s "
                            f"(attempt {attempt + 1}/{max_retries + 1})...")
                time.sleep(wait_sec)
            else:
                break

    raise last_exception or Exception(f"HTTP request failed after {max_retries + 1} attempts")


# ============================================================
# 登录（与原脚本一致）
# ============================================================
def login():
    """执行 MW UME 登录流程，返回包含 cookie 和 forgery_token 的字典。"""
    logger.info("[LOGIN] Starting authentication...")
    session_cookie = ""
    forgery_token = ""

    user, pwd = _runtime_credentials()

    try:
        logger.info("[LOGIN] Step 1: Getting authorize page...")
        status, hdrs, raw_hdrs, body = _http_request(
            "GET",
            f"/api/oauth2/v1/authorize?scope=user.login&response_type=code"
            f"&redirect_uri={LOGIN_PORTAL}"
        )
        logger.info(f"[LOGIN] Status: {status}")

        init_cookies = []
        for line in raw_hdrs.split("\r\n"):
            if line.lower().startswith("set-cookie:"):
                cookie_val = line.split(": ", 1)[1].split(";")[0]
                if cookie_val.split("=", 1)[-1]:
                    init_cookies.append(cookie_val)
                    if "forgerydefense" in cookie_val:
                        forgery_token = cookie_val.split("=", 1)[1]

        init_cookie_str = "; ".join(init_cookies)
        logger.info(f"[LOGIN] Got {len(init_cookies)} cookies")

        html = body.decode('utf-8', errors='replace')
        lp_match = re.search(r'var\s+loginParameters\s*=\s*["\']([^"\']+)["\']', html)
        login_parameters = lp_match.group(1) if lp_match else ""

        logger.info("[LOGIN] Step 2: Getting RSA public key from API...")
        rsa_headers = f"Cookie: {init_cookie_str}\r\nX-Requested-With: XMLHttpRequest\r\n"
        status, hdrs, raw_hdrs, body = _http_request(
            "GET", "/api/oauth2/v1/login/publickey",
            headers_extra=rsa_headers,
        )

        public_key_b64 = ""
        if "200" in status:
            pk_data = json.loads(body.decode('utf-8'))
            public_key_b64 = pk_data.get("rsaPublicKey", "")

        if not public_key_b64:
            raise Exception("无法获取 RSA 公钥，登录中止")

        logger.info("[LOGIN] Step 3: Encrypting password with RSA...")
        encrypted_pwd = _rsa_encrypt_pem(pwd, public_key_b64)

        logger.info("[LOGIN] Step 4: Submitting login...")
        login_payload = json.dumps({
            "username": user,
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
        logger.info(f"[LOGIN] Login status: {status}")

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
            or "uportal" in resp_text
            or "portal" in resp_text.lower()
            or "default.html" in resp_text
            or any("Z-AUTH-CODE" in c for c in cookies)
            or len(cookies) > 3
        )
        if success:
            logger.info(f"[LOGIN] SUCCESS - {len(cookies)} cookies")
        else:
            logger.info(f"[LOGIN] Response: {resp_text[:300]}")
            raise Exception("登录失败 - 未获取到鉴权 Cookie")

    except Exception as e:
        logger.error(f"[LOGIN] FAILED: {e}")
        raise

    return {"cookie": session_cookie, "forgery_token": forgery_token}


# ============================================================
# Payload 构造（字段顺序与原脚本/url.txt 严格一致）
# ============================================================
def build_mw_ume_kpi_payload(cfg: dict, start_iso: str = None, end_iso: str = None,
                             relative: int = None) -> dict:
    """构造 MW UME KPI 历史指标查询 Payload。"""
    now = datetime.now(timezone.utc)
    if end_iso is None:
        end_iso = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if start_iso is None:
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=DAYS_BACK)
        start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    timeinfo = {
        "mode": 1,
        "start": start_iso,
        "end": end_iso,
        "relative": relative if relative is not None else -DAYS_BACK,
        "timezonetype": "1",
        "clienttimezone": "Atlantic/Reykjavik",
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
        ("groupbygroup", cfg.get("groupbygroup", False)),
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
        ("needdeployfilter", False),
        ("timeinfo", timeinfo),
        ("thresholdinfos", []),
        ("templatetype", 0),
        ("filterlayer", cfg["filterlayer"]),
        ("grouplayer", cfg["grouplayer"]),
        ("containvcell", cfg.get("containvcell", 0)),
        ("resfilterattribute", ""),
        ("uilocations", []),
        ("reslocation", []),
        ("inexistenceres", False),
        ("firstDayOfWeek", 7),
        ("iswireless", False),
        ("hidehistorystopbutton", False),
        ("opencustomizehistoryexport", False),
        ("opentemplatecustomcolumn", False),
        ("drawitems", cfg.get("drawitems", [])),
    ]

    payload = dict(fields)
    return payload


# ============================================================
# KPI 查询 / 轮询 / 内存导出
# ============================================================
def create_history_query(cookie: str, forgery_token: str, payload: dict) -> str:
    """创建 KPI 历史指标查询任务，返回 queryid。"""
    logger.info(f"[KPI] Creating: {payload.get('favoriteconditionname')} / "
                f"filterlayer={payload.get('filterlayer')} / gr={payload.get('gr')}")
    body = json.dumps(payload, ensure_ascii=False)
    headers = _auth_headers(cookie, forgery_token)

    status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
        "POST", HISTORY_PATH, headers_extra=headers, body=body.encode('utf-8'), max_retries=2,
    )

    logger.info(f"[KPI] Create query status: {status}")
    resp_text = resp_body.decode('utf-8', errors='replace')

    if "200" not in status:
        logger.info(f"[KPI] Response: {resp_text[:500]}")
        raise Exception(f"Create KPI query failed: {status}")

    data = json.loads(resp_text)
    queryid = data.get("queryid") or data.get("id")
    if not queryid:
        raise Exception(f"No queryid returned: {resp_text[:500]}")
    logger.info(f"[KPI] Query ID: {queryid}")
    return queryid


def wait_history_ready(cookie: str, forgery_token: str, queryid: str,
                       timeout: int = 600, interval: int = 10) -> dict:
    """轮询 KPI 历史指标查询进度，直到完成或超时。"""
    logger.info(f"[KPI] Polling progress (timeout={timeout}s, interval={interval}s)...")
    path = f"{HISTORY_POLL_PATH}?type=0&queryid={queryid}"
    headers = _auth_headers(cookie, forgery_token)

    deadline = time.time() + timeout
    last_data = {}
    poll_count = 0
    while time.time() < deadline:
        status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
            "GET", path, headers_extra=headers, max_retries=1,
        )
        resp_text = resp_body.decode('utf-8', errors='replace')
        try:
            data = json.loads(resp_text)
        except json.JSONDecodeError:
            logger.warning(f"[KPI] Poll #{poll_count} non-JSON response: {resp_text[:300]}")
            time.sleep(interval)
            poll_count += 1
            continue
        last_data = data

        # 兼容多种字段命名：progress/Progress, querystate/state
        progress = data.get("progress", data.get("Progress", 0))
        querystate = data.get("querystate", data.get("state", data.get("queryState", -1)))
        poll_count += 1
        logger.info(f"[KPI] Poll #{poll_count}: progress={progress}%, querystate={querystate}, "
                    f"keys={list(data.keys())}")

        # querystate==1 或 progress>=100 表示完成；querystate==2/3 通常表示失败
        if querystate in (2, 3):
            raise Exception(f"KPI query failed on server: querystate={querystate}, response={resp_text[:500]}")
        if querystate == 1 or progress >= 100:
            logger.info(f"[KPI] Query ready after {poll_count} polls")
            return data

        time.sleep(interval)

    raise Exception(f"KPI query timed out after {timeout}s (last state: {last_data})")


def _extract_xlsx_bytes(resp_bytes):
    """导出接口可能返回 ZIP 包裹的 xlsx（PK 头但内层才是真正的 xlsx），本函数在内存中解包。"""
    if len(resp_bytes) < 4 or resp_bytes[:2] != b'PK':
        return resp_bytes
    try:
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(resp_bytes))
        xlsx_names = [n for n in z.namelist() if n.lower().endswith('.xlsx')]
        if len(xlsx_names) >= 1:
            inner = z.read(xlsx_names[0])
            logger.info(f"[KPI] Detected ZIP wrapper, extracted inner xlsx: "
                        f"{xlsx_names[0]} ({len(inner)} bytes)")
            return inner
        names = z.namelist()
        if len(names) == 1:
            inner = z.read(names[0])
            logger.info(f"[KPI] Detected ZIP wrapper, extracted: {names[0]} ({len(inner)} bytes)")
            return inner
    except Exception as e:
        logger.warning(f"[KPI] ZIP extraction attempt failed ({e}), treating as raw xlsx")
    return resp_bytes


def export_history_to_memory(cookie: str, forgery_token: str, queryid: str, filename: str) -> bytes:
    """导出并下载 KPI 历史指标结果，返回内存 bytes（不落盘）。"""
    payload = {
        "id": queryid,
        "filename": filename,
        "exportfiletype": 1,
        "itemshowtype": 0,
        "contentmode": 0,
        "customizefieldtype": "0",
        "imageinfo": [],
        "chartlayout": 1,
        "exportserialnumber": False,
        "exporttableheaders": False,
        "tableheaders": {},
    }

    logger.info(f"[KPI] Exporting (in-memory): {filename}")
    body = json.dumps(payload, ensure_ascii=False)
    headers = _auth_headers(cookie, forgery_token)

    status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
        "POST", HISTORY_EXPORT_PATH, headers_extra=headers, body=body.encode('utf-8'), max_retries=2,
    )
    logger.info(f"[KPI] Export status: {status}")

    if "200" not in status:
        err_text = resp_body.decode('utf-8', errors='replace')[:500]
        raise Exception(f"Export KPI history failed: {status}, body: {err_text}")

    # 导出可能返回 ZIP 包裹的 xlsx，内存解包为真正的 xlsx 字节
    resp_body = _extract_xlsx_bytes(resp_body)
    logger.info(f"[KPI] Export in memory: {len(resp_body)} bytes")
    return resp_body


# ============================================================
# 文件命名 / 表名
# ============================================================
def build_filename(cfg: dict) -> str:
    """构造 KPI 导出文件名前缀（不含时间戳和扩展名）。"""
    name = cfg["favoriteconditionname"]
    name = name.replace(" ", "_").replace("/", "_").replace("\\", "_").replace("-", "_")
    layer = cfg["filterlayer"]
    gr_label = GR_RENAME.get(cfg["gr"], cfg["gr"])
    return f"{name}_{layer}_{gr_label}"


def sanitize_table_name(name: str) -> str:
    """将文件名前缀转为合法的 SQLite 表名。"""
    return name.replace(" ", "_").replace("-", "_")


# ============================================================
# 内存解析 + 直写主库
# ============================================================
def read_xlsx_bytes(file_bytes: bytes):
    """从内存 bytes 解析 xlsx，返回 (headers, data)。"""
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
    """检测联合主键列：必须包含 'Begin Time'，并自动追加所有存在的标识列。"""
    if "Begin Time" not in headers:
        logger.warning(f"  [DB] 缺少 'Begin Time' 列。实际列名: {headers}")
        return None

    key_cols = ["Begin Time"]
    for cand in IDENTITY_COL_CANDIDATES:
        if cand in headers and cand not in key_cols:
            key_cols.append(cand)

    if len(key_cols) == 1:
        logger.warning("  [DB] 未检测到任何标识列（NE/ME/SERVICE/Measurement Object），仅使用 'Begin Time' 作为主键。")

    return key_cols


def ensure_unique_key_cols(headers: list, data: list, key_cols: list) -> list:
    """校验 key_cols 在当批数据内是否唯一；不唯一则逐个追加列直到唯一。

    返回扩展后的 key_cols；耗尽所有列仍不唯一则抛异常（宁可失败也不静默塌缩丢数据）。
    """
    if _cols_unique(headers, data, key_cols):
        return key_cols
    logger.warning(f"  [DB] 自然主键 {key_cols} 在数据中不唯一，尝试扩展")
    for cand in headers:
        if cand in key_cols:
            continue
        expanded = key_cols + [cand]
        if _cols_unique(headers, data, expanded):
            logger.warning(f"  [DB] 主键扩展为 {expanded}")
            return expanded
    raise Exception(
        f"无法凑出唯一主键(自然键={key_cols!r})，放弃 upsert 以免数据塌缩。"
        f"请检查导出表结构。"
    )


def save_to_db(table_name: str, headers: list, data: list, key_cols: list) -> int:
    """将数据直接写入 my_app 主库 app.db（sqlite/PG 双模 upsert）。

    去重策略：以 key_cols 建唯一索引，逐行 INSERT OR REPLACE（PG 为 ON CONFLICT DO UPDATE），
    同 key 数据自动覆盖，保留历史行。
    """
    if not headers or not data:
        return 0
    if not key_cols or any(c not in headers for c in key_cols):
        logger.warning(f"  [DB] 主键列不可用 key_cols={key_cols}，跳过。")
        return 0

    import sqlite3
    import hashlib

    def _q(col):
        return '"' + col.replace('"', '""') + '"'

    # app.db 主库（backend.database.get_raw_connection 默认路径；PG 模式映射 app schema）
    with get_raw_connection(timeout=60.0) as conn:
        cursor = conn.cursor()
        is_pg = not isinstance(conn, sqlite3.Connection)

        # PG 并发串行化（2026-08-31 修复）：本流程用固定索引名 u_<table>，且每次
        # 无条件 DROP+CREATE UNIQUE INDEX；而 _PsycopgRaw 为 autocommit，每个语句
        # 立即提交，两个并发写者（如生产 Worker + 开发实例 in-process 同时触发）会
        # 互删对方刚建好的唯一索引，导致 INSERT ... ON CONFLICT 时报
        # 「没有匹配ON CONFLICT说明的唯一或者排除约束」(SQLSTATE 42P10)。
        # 用 PG 会话级 advisory lock 让同一张表的写者排队，串行执行 DROP/CREATE/INSERT，
        # 从根上消除该竞态（sqlite 走 INSERT OR REPLACE 不依赖索引，无需加锁）。
        lock_key = None
        if is_pg:
            # 63-bit 正 bigint（PG advisory lock 合法键），由表名稳定派生
            lock_key = int.from_bytes(
                hashlib.sha256(f"u_{table_name}".encode("utf-8")).digest()[:8], "big"
            ) & 0x7FFFFFFFFFFFFFFF
            cursor.execute("SELECT pg_advisory_lock(?)", (lock_key,))
        try:
            # 建表（幂等，全部 TEXT，不强制 NOT NULL）
            cols_decl = ", ".join(f"{_q(h)} TEXT" for h in headers)
            cursor.execute(f'CREATE TABLE IF NOT EXISTS "{table_name}" ({cols_decl})')

            # 补列
            exist_cols = set(table_columns(conn, table_name))
            for h in headers:
                if h not in exist_cols:
                    try:
                        cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN {_q(h)} TEXT')
                    except Exception:
                        pass

            # 清理历史重复行（rowid 仅 sqlite；PG 用 ctid），再重建唯一索引，upsert 才能生效
            pk_q = ", ".join(_q(k) for k in key_cols)
            if isinstance(conn, sqlite3.Connection):
                cursor.execute(
                    f'DELETE FROM "{table_name}" WHERE rowid NOT IN ('
                    f'SELECT MIN(rowid) FROM "{table_name}" GROUP BY {pk_q})'
                )
            else:
                cursor.execute(
                    f'DELETE FROM "{table_name}" WHERE ctid NOT IN ('
                    f'SELECT MIN(ctid) FROM "{table_name}" GROUP BY {pk_q})'
                )
            cursor.execute(f'DROP INDEX IF EXISTS "u_{table_name}"')
            cursor.execute(f'CREATE UNIQUE INDEX "u_{table_name}" ON "{table_name}" ({pk_q})')

            # 构造记录（统一转 str）
            records = []
            for row in data:
                r = list(row)
                if len(r) < len(headers):
                    r = r + [None] * (len(headers) - len(r))
                records.append({h: (str(v) if v is not None else None)
                                for h, v in zip(headers, r[:len(headers)])})

            upsert(conn, table_name, records, conflict_cols=list(key_cols))
            conn.commit()
        finally:
            if is_pg and lock_key is not None:
                try:
                    cursor.execute("SELECT pg_advisory_unlock(?)", (lock_key,))
                except Exception:  # noqa: BLE001 - 连接可能已关闭，解锁失败忽略
                    pass

    logger.info(f"  [DB] {table_name}: Upserted {len(records)} rows (pk={key_cols})")
    return len(records)


# ============================================================
# 单任务执行（内存流水线）
# ============================================================
def _run_single_kpi_query(auth: dict, task: dict, start_index: int = 0,
                          configs: dict = None, start_iso: str = None,
                          end_iso: str = None, relative: int = None) -> tuple:
    """执行单个 KPI 查询任务，返回 (key, headers, data) 或抛异常。全程不落盘。"""
    cfg = (configs or MW_UME_KPI_QUERY_CONFIGS)[task["key"]]

    # 错峰启动
    delay = start_index * 0.8
    if delay > 0:
        time.sleep(delay)

    logger.info(f"[MAIN] Starting KPI query: {cfg['favoriteconditionname']}")

    payload = build_mw_ume_kpi_payload(cfg, start_iso=start_iso, end_iso=end_iso,
                                       relative=relative)

    cookie = auth["cookie"]
    forgery_token = auth["forgery_token"]

    queryid = create_history_query(cookie, forgery_token, payload)
    wait_history_ready(cookie, forgery_token, queryid)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{build_filename(cfg)}_{timestamp}"
    xlsx_bytes = export_history_to_memory(cookie, forgery_token, queryid, filename)

    headers, data = read_xlsx_bytes(xlsx_bytes)
    logger.info(f"[MAIN] Parsed in memory: {len(data)} rows, {len(headers)} cols")

    return task["key"], headers, data


# ============================================================
# 主入口（供 task_registry 懒加载调用）
# ============================================================
def _run_sync_core(table_name: str, tasks: list, configs: dict,
                   start_iso: str = None, end_iso: str = None,
                   relative: int = None, window_desc: str = ""):
    """通用同步流水线：登录 → 查询 → 内存导出/解析 → 直写 app.db。

    返回 dict（供任务执行历史展示）：{"success": bool, "rows_written": int, "table": str, "errors": [...]}
    """
    t_start = time.time()
    logger.info(f"[MAIN] MW UME KPI sync started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"[MAIN] Host: https://{HOST}:{PORT}{LOGIN_PORTAL}")
    logger.info(f"[MAIN] Target table: {table_name}")
    logger.info(f"[MAIN] Time window: {window_desc or '昨天 00:00:00 到今天 00:00:00 UTC（默认）'}")

    result = {"success": False, "rows_written": 0, "table": table_name, "errors": []}

    # 1. 登录
    auth = login()

    # 2. 并行执行查询（内存流水线）
    from concurrent.futures import ThreadPoolExecutor, as_completed

    datasets = []  # (key, headers, data)
    errors = []

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
        future_to_task = {}
        for idx, task in enumerate(tasks):
            future = executor.submit(_run_single_kpi_query, auth, task, idx,
                                     configs, start_iso, end_iso, relative)
            future_to_task[future] = task

        for future in as_completed(future_to_task):
            task = future_to_task[future]
            task_label = task["key"]
            try:
                key, headers, data = future.result()
                datasets.append((key, headers, data))
                logger.info(f"[MAIN] KPI query [{task_label}] succeeded: {len(data)} rows")
            except Exception as e:
                errors.append(f"{task_label}: {e}")
                logger.error(f"[MAIN] KPI query [{task_label}] failed: {e}")

    if not datasets:
        result["errors"] = errors or ["无任何查询成功，跳过写库"]
        logger.error(f"[MAIN] No data fetched, skip DB write. errors={errors}")
        return result

    # 3. 直写主库
    total_written = 0
    for key, headers, data in datasets:
        try:
            key_cols = detect_key_cols(headers)
            if not key_cols:
                raise Exception(f"无法确定主键（缺少 Begin Time 列）: {headers[:10]}")
            # 主键在当批数据内必须唯一，否则扩展列，避免 upsert 静默塌缩丢数据
            key_cols = ensure_unique_key_cols(headers, data, key_cols)
            rows = save_to_db(table_name, headers, data, key_cols)
            total_written += rows
        except Exception as e:
            errors.append(f"{key}(写库): {e}")
            logger.error(f"[MAIN] DB write [{key}] failed: {e}")

    elapsed_total = time.time() - t_start
    result["rows_written"] = total_written
    result["errors"] = errors
    result["success"] = total_written > 0 and not errors

    logger.info(f"[MAIN] Total completed in {elapsed_total:.2f} seconds, "
                f"written {total_written} rows to {table_name}, errors={errors}")
    gc.collect()
    return result


def run_mw_ume_kpi_sync():
    """主流程（日粒度）：登录 → 查询 → 内存导出/解析 → 直写 app.db（表 mw_ume_bw_ultilazation）。"""
    return _run_sync_core(TABLE_NAME, MW_UME_KPI_TASKS, MW_UME_KPI_QUERY_CONFIGS,
                          window_desc=f"最近 {DAYS_BACK} 天（昨天 00:00:00 到今天 00:00:00 UTC）")


def _cleanup_rt_retention():
    """按保留期清理 RT 表：删除 Begin Time 早于「当前 UTC - RT_RETENTION_HOURS」的行。

    与同步共用 get_raw_connection（sqlite/PG 双模）；Begin Time 落库格式为定宽
    "%Y-%m-%d %H:%M:%S"（UTC），可直接按字符串比较。清理失败只记警告，不阻断同步。
    返回删除行数。
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=RT_RETENTION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        import sqlite3
        from backend.dialect_helpers import safe_pragma  # noqa: F401  (保持双模连接语义一致)

        with get_raw_connection(timeout=60.0) as conn:
            cur = conn.cursor()
            cur.execute(
                f'DELETE FROM "{RT_TABLE_NAME}" WHERE "Begin Time" < ?',
                (cutoff,),
            )
            deleted = cur.rowcount
            conn.commit()
        if deleted:
            logger.info(f"[MAIN] RT retention: deleted {deleted} rows older than {cutoff} "
                        f"(retention={RT_RETENTION_HOURS:g}h) from {RT_TABLE_NAME}")
        return deleted or 0
    except Exception as e:
        logger.warning(f"[MAIN] RT retention cleanup failed (non-fatal): {e}")
        return 0


def run_mw_ume_kpi_sync_rt():
    """实时流程（15 分钟粒度，gr=900）：取最近 2 小时数据直写 app.db（表 mw_ume_bw_ultilazation_rt）。

    看板只使用最新一个 15 分钟槽位；回看 2 小时是为容忍 UME 侧出数延迟，
    保证每轮同步都能拿到至少一个完整槽位。
    写库完成后顺带执行保留期清理（默认 25h），防止 RT 表无限增长。
    """
    now = datetime.now(timezone.utc)
    end_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    start_iso = (now - timedelta(hours=RT_WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    window_desc = f"最近 {RT_WINDOW_HOURS:g} 小时（{start_iso} ~ {end_iso}，gr=900/15 分钟）"
    result = _run_sync_core(RT_TABLE_NAME, MW_UME_KPI_TASKS_RT, MW_UME_KPI_QUERY_CONFIGS_RT,
                            start_iso=start_iso, end_iso=end_iso, relative=0,
                            window_desc=window_desc)
    if result.get("success"):
        result["retention_deleted"] = _cleanup_rt_retention()
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    print(run_mw_ume_kpi_sync())
