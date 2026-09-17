# -*- coding: utf-8 -*-
"""UME「Dong customer」周度业务 KPI 采集与分析服务（ume_in）

数据来源（见 backend/services/ume_in/url.txt）：
    https://172.17.208.1:28808/em-portal/  （账号 10172755）
    接口 POST /api/pm-analysis/v2/history   —— 与 MW UME 同一套 UME PM-analysis 协议

与 backend/services/mw_ume/mw_ume_kpi_service.py 的关系：
- **协议完全同源**（原始 socket + TLS 免证书校验 → OAuth2 authorize → RSA 公钥 →
  login_rsa → 建查询拿 queryid → 轮询 querystate → v3/history/export 导出 xlsx）。
- 但**刻意不复用其模块级函数**：那边 HOST/PORT/LOGIN_PORTAL/HISTORY_REFERER 是
  模块全局变量，同进程（n 组 worker）内改它们会污染 MW UME 任务。
  故本模块自带 `UMEPortalClient`（凭参构造，无全局状态），仅复用其中纯函数
  （`read_xlsx_bytes` / `save_to_db` / `ensure_unique_key_cols`）。
- 采集 7 个「Dong customer weekly」模板（IVR / P4M / Memory / CPU / VC / USSD / PPS），
  日粒度（gr=86400），落库到主库表 `ume_in_customer_kpi`（sqlite/PG 双模），
  再做指标口径分析（成功率 / 失败分解 / 资源利用率 / 健康分级 / 多日趋势）。

定时任务：`ume_in_kpi_sync`（每日 05:45，worker 组 n）。
凭据：credential_store key="ume_in"（Settings 页面可改），env 覆盖 UME_IN_USER / UME_IN_PASSWORD。
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
from datetime import datetime, timezone, timedelta

from backend.database import get_raw_connection
from backend.services.mw_ume.mw_ume_kpi_service import (
    read_xlsx_bytes,
    save_to_db,
    ensure_unique_key_cols,
)

logger = logging.getLogger("ume_in_kpi_service")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - 非 Windows / 已被重定向时忽略
    pass

# ============================================================
# 门户连接配置（可用环境变量覆盖）
# ============================================================
HOST = os.environ.get("UME_IN_HOST", "172.17.208.1")
PORT = int(os.environ.get("UME_IN_PORT", "28808"))
LOGIN_PORTAL = os.environ.get("UME_IN_PORTAL", "/em-portal/")
USERNAME = os.environ.get("UME_IN_USER", "10172755")
PASSWORD = os.environ.get("UME_IN_PASSWORD", "Zte@liberia202609")

REFERER = f"https://{HOST}:{PORT}{LOGIN_PORTAL}"
HISTORY_PATH = "/api/pm-analysis/v2/history"
HISTORY_POLL_PATH = "/api/pm-analysis/v1/history"
HISTORY_EXPORT_PATH = "/api/pm-analysis/v3/history/export"

# 目标表名（主库，sqlite/PG 双模）
TABLE_NAME = os.environ.get("UME_IN_TABLE", "ume_in_customer_kpi")

# 默认回看天数（url.txt 抓包为 3 天；这里取 7 天，首次同步即有完整周趋势）
DAYS_BACK = int(os.environ.get("UME_IN_DAYS_BACK", "7"))
MAX_PARALLEL_WORKERS = int(os.environ.get("UME_IN_PARALLEL_WORKERS", "4"))

# 落库主键（模板不同但同一天同一 SERVICE 会撞车 → 必须带 KPI 维度）
KEY_COLS = ["Begin Time", "KPI", "NE", "SERVICE"]

# ---------- 健康判定阈值（可按需调整） ----------
# ① 服务质量：总成功率阈值（仅用于配色展示，不直接触发告警）
SUCCESS_WARN = float(os.environ.get("UME_IN_SUCCESS_WARN", "0.99"))   # 成功率 <99% 关注
SUCCESS_CRIT = float(os.environ.get("UME_IN_SUCCESS_CRIT", "0.95"))   # 成功率 <95% 异常
# ② 系统健康：系统侧失败率阈值（真正触发告警的口径）
#    理由：PPS 的 82% 成功率里 96% 是「余额不足」、USSD 的 89% 里 99.98% 是「用户失败」，
#    都是业务正常结果；把它们当故障会产生大量假告警。运维该盯的是系统侧失败。
SYS_FAIL_WARN = float(os.environ.get("UME_IN_SYS_FAIL_WARN", "0.001"))  # 系统侧失败率 >=0.1%
SYS_FAIL_CRIT = float(os.environ.get("UME_IN_SYS_FAIL_CRIT", "0.01"))   # 系统侧失败率 >=1%
# ③ 资源利用率（以日均值为准，峰值仅作参考——top=100% 常为瞬时尖峰）
RES_WARN = float(os.environ.get("UME_IN_RES_WARN", "80"))             # 日均 >=80% 关注
RES_CRIT = float(os.environ.get("UME_IN_RES_CRIT", "90"))             # 日均 >=90% 异常
RES_SPIKE_TOP = float(os.environ.get("UME_IN_RES_SPIKE_TOP", "95"))   # 峰值阈值
RES_SPIKE_BASE = float(os.environ.get("UME_IN_RES_SPIKE_BASE", "50"))  # 基线偏高才认定尖峰有意义

# ============================================================
# KPI 模板清单（与 url.txt 严格一致，字段顺序敏感）
#   kind=success_rate → 业务量/成功率类
#   kind=resource     → 资源利用率类
# fail_cols 三元组：(列名, 中文标签, 归因侧)；英文标签在 FAIL_LABEL_EN 里按中文标签查
#   system = 系统侧（运维该管）/ user = 用户侧（业务正常结果）
# ============================================================
KPI_SPECS = [
    {
        "key": "IVR",
        "template": "Dong_customer weekly IVR KPI",
        "motid": "64300",
        "templateid": "1731730870314",
        "items": ["C637210002", "C637210003"],
        "title_zh": "IVR 语音自助",
        "title_en": "IVR Self-service",
        "kind": "success_rate",
        "attempt_col": "PA Times",
        "success_col": None,
        "fail_cols": [("PA Failed Times", "处理失败", "system")],
    },
    {
        "key": "P4M",
        "template": "Dong_customer weekly P4M KPI",
        "motid": "64300",
        "templateid": "1731730870313",
        "items": ["C637240001", "C637240002", "C637240005", "C637240006"],
        "title_zh": "P4M 业务开通",
        "title_en": "P4M Provisioning",
        "kind": "success_rate",
        "attempt_col": "Request Times",
        "success_col": "Subscribe Times",
        "fail_cols": [],
        # 「请求 → 订阅」是转化率语义，不是成功率，不参与告警
        "rate_label_zh": "订阅转化率",
        "rate_label_en": "Subscribe conversion",
        "alarm": False,
        "extra_cols": [("Black list management Times", "黑名单管理", "Black list management"),
                       ("White list management Times", "白名单管理", "White list management")],
    },
    {
        "key": "VC",
        "template": "Dong_customer_weekly_VC_KPI",
        "motid": "64300",
        "templateid": "1731730870310",
        "items": ["C637260001", "C637260002", "C637260014",
                  "C637260003", "C637260015", "C637260013"],
        "title_zh": "VC 充值",
        "title_en": "VC Recharge",
        "kind": "success_rate",
        "attempt_col": "Recharge received times",
        "success_col": "Recharge success times",
        "fail_cols": [("Recharge failed times", "充值失败", "system"),
                      ("User recharge failed times", "用户侧失败", "user")],
    },
    {
        "key": "USSD",
        "template": "Dong_customer Weekly_USSD_KPI",
        "motid": "64301",
        "templateid": "1731730870309",
        "items": ["C637120003", "C637120007", "C637120030",
                  "C637120029", "C637120028"],
        "title_zh": "USSD 交互",
        "title_en": "USSD Session",
        "kind": "success_rate",
        "attempt_col": "Call Attempts",
        "success_col": "Send Success Times",
        "fail_cols": [("DataBase result error Times", "数据库错误", "system"),
                      ("System Fail Times", "系统失败", "system"),
                      ("User Fail Times", "用户失败", "user")],
    },
    {
        "key": "PPS",
        "template": "Dong_customer_PPS_KPI",
        "motid": "64300",
        "templateid": "1731730870308",
        "items": ["C637000001", "C637000102", "C637000103",
                  "C637000104", "C637000105", "C637000101"],
        "title_zh": "PPS 预付费呼叫",
        "title_en": "PPS Prepaid Call",
        "kind": "success_rate",
        "attempt_col": "Call attempts",
        "success_col": "Success Times",
        "fail_cols": [("User Status Abnormal Times", "用户状态异常", "user"),
                      ("Balance Insufficient Times", "余额不足", "user"),
                      ("Other User Failed Times", "其他用户失败", "user"),
                      ("System Failed Times", "系统失败", "system")],
    },
    {
        "key": "CPU",
        "template": "Dong_Customer_Weekly_CPU KPI",
        "motid": "61017",
        "templateid": "1731730870311",
        "items": ["C557050003", "C557050004"],
        "title_zh": "CPU 利用率",
        "title_en": "CPU Utilisation",
        "kind": "resource",
        "primary_col": "Usage average ratio of CPU(%)",
        "top_col": "Usage top ratio of CPU(%)",
    },
    {
        "key": "MEM",
        "template": "Dong_Customer Weekly_Memory_KPI",
        "motid": "61016",
        "templateid": "1731730870312",
        "items": ["C557040003", "C557040004", "C557040005", "C557040006",
                  "C557040007", "C557040008", "C557040009"],
        "title_zh": "内存利用率",
        "title_en": "Memory Utilisation",
        "kind": "resource",
        "primary_col": "Mean ratio of the memory usage(%)",
        "top_col": "Usage top ratio of memory(%)",
        "capacity_col": "Capacity of memory(KB)",
        "used_col": "Size of used memory(KB)",
        "free_col": "Size of free memory(KB)",
    },
]

SPEC_BY_KEY = {s["key"]: s for s in KPI_SPECS}

# ============================================================
# 英文标签（前端 EN 环境用；中文标签是 UME 模板里的原始列义，不能直接展示给英文用户）
# ============================================================
FAIL_LABEL_EN = {
    "处理失败": "Processing failed",
    "充值失败": "Recharge failed",
    "用户侧失败": "User-side failure",
    "数据库错误": "Database error",
    "系统失败": "System failure",
    "用户失败": "User failure",
    "用户状态异常": "User status abnormal",
    "余额不足": "Insufficient balance",
    "其他用户失败": "Other user failure",
}

EXTRA_LABEL_EN = {
    "黑名单管理": "Black list management",
    "白名单管理": "White list management",
}

# 告警的 metric / message 结构化编码（前端按 locale 组装文案，避免后端下发中文句子）
METRIC_SYS_FAIL = "sys_fail_rate"
METRIC_SUCCESS_RATE = "success_rate"
METRIC_RESOURCE = "resource"


def _en(mapping, zh, fallback=None):
    """取英文标签；查不到就退回传入的兜底（默认原中文），保证不会出现空字符串。"""
    return mapping.get(zh) or fallback or zh


def _runtime_credentials():
    """运行时凭据：环境变量 > credential_store > 模块默认值。"""
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        return USERNAME, PASSWORD
    return get_credential("ume_in", USERNAME, PASSWORD)


# ============================================================
# UME PM-analysis 门户客户端（无全局状态，可安全与 MW UME 共存）
# ============================================================
class UMEPortalClient:
    """UME 门户会话：登录 / 建查询 / 轮询 / 导出（全程内存，不落盘）。"""

    def __init__(self, host=HOST, port=PORT, portal=LOGIN_PORTAL,
                 username=None, password=None, timeout=30):
        self.host = host
        self.port = port
        self.portal = portal
        self.referer = f"https://{host}:{port}{portal}"
        self.username = username
        self.password = password
        self.timeout = timeout
        self.cookie = ""
        self.forgery_token = ""

    # ---------- 底层 HTTP（原始 socket + TLS） ----------
    def _ssl_socket(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("ALL:@SECLEVEL=0")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        ssock = ctx.wrap_socket(sock)
        ssock.connect((self.host, self.port))
        return ssock

    @staticmethod
    def _decode_chunked(data):
        result = b""
        pos = 0
        while pos < len(data):
            line_end = data.find(b"\r\n", pos)
            if line_end == -1:
                break
            try:
                chunk_size = int(data[pos:line_end].decode("utf-8", errors="replace").strip(), 16)
            except ValueError:
                break
            if chunk_size == 0:
                break
            pos = line_end + 2
            result += data[pos:pos + chunk_size]
            pos += chunk_size + 2
        return result

    def _request(self, method, path, headers_extra=None, body=None):
        ssock = self._ssl_socket()
        headers = (
            f"{method} {path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
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

        request_bytes = headers.encode("utf-8")
        if body:
            request_bytes += body if isinstance(body, bytes) else body.encode("utf-8")
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

        header_part = response_data[:header_end].decode("utf-8", errors="replace")
        resp_body = response_data[header_end + 4:]
        status_line = header_part.split("\r\n")[0]

        resp_headers = {}
        for line in header_part.split("\r\n")[1:]:
            if ": " in line:
                k, v = line.split(": ", 1)
                resp_headers[k.lower()] = v

        if "chunked" in resp_headers.get("transfer-encoding", ""):
            resp_body = self._decode_chunked(resp_body)
        if "gzip" in resp_headers.get("content-encoding", ""):
            resp_body = gzip.decompress(resp_body)

        return status_line, resp_headers, header_part, resp_body

    def _request_retry(self, method, path, headers_extra=None, body=None,
                       max_retries=2, retry_statuses=("499", "500", "502", "503", "504")):
        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                status, hdrs, raw, resp_body = self._request(
                    method, path, headers_extra=headers_extra, body=body)
                if any(code in status for code in retry_statuses) and attempt < max_retries:
                    wait = 2 ** attempt
                    logger.info(f"[HTTP] {status} on {path}, retry in {wait}s "
                                f"({attempt + 1}/{max_retries + 1})")
                    time.sleep(wait)
                    continue
                return status, hdrs, raw, resp_body
            except Exception as e:  # noqa: BLE001
                last_exc = e
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                else:
                    break
        raise last_exc or Exception(f"HTTP failed after {max_retries + 1} attempts")

    def _auth_headers(self, extra=None):
        headers = (
            f"Content-Type: application/json; charset=UTF-8\r\n"
            f"Accept: application/json, text/plain, */*\r\n"
            f"Accept-Encoding: gzip\r\n"
            f"Cookie: {self.cookie}\r\n"
            f"Referer: {self.referer}\r\n"
            f"X-Requested-With: XMLHttpRequest\r\n"
            f"language-option: en-US\r\n"
            f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        )
        if self.forgery_token:
            headers += f"forgerydefense: {self.forgery_token}\r\n"
        for k, v in (extra or {}).items():
            headers += f"{k}: {v}\r\n"
        return headers

    # ---------- 登录 ----------
    @staticmethod
    def _rsa_encrypt(plaintext, public_key_b64):
        from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
        from cryptography.hazmat.primitives import serialization

        pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
        pub = serialization.load_pem_public_key(pem.encode())
        enc = pub.encrypt(plaintext.encode("utf-8"), asym_padding.PKCS1v15())
        return base64.b64encode(enc).decode("ascii")

    def login(self):
        """OAuth2 + RSA 登录，成功后填充 cookie / forgery_token。"""
        user, pwd = (self.username, self.password)
        if user is None or pwd is None:
            user, pwd = _runtime_credentials()

        logger.info(f"[LOGIN] {user}@{self.host}:{self.port}{self.portal}")
        auth_path = ("/api/oauth2/v1/authorize?scope=user.login&response_type=code"
                     f"&redirect_uri={self.portal}")

        status, hdrs, raw_hdrs, body = self._request("GET", auth_path)
        cookies, forgery = [], ""
        for line in raw_hdrs.split("\r\n"):
            if line.lower().startswith("set-cookie:"):
                cv = line.split(": ", 1)[1].split(";")[0]
                if cv.split("=", 1)[-1]:
                    cookies.append(cv)
                    if "forgerydefense" in cv:
                        forgery = cv.split("=", 1)[1]
        init_cookie = "; ".join(cookies)

        html = body.decode("utf-8", errors="replace")
        m = re.search(r'var\s+loginParameters\s*=\s*["\']([^"\']+)["\']', html)
        login_params = m.group(1) if m else ""

        status, hdrs, raw_hdrs, body = self._request(
            "GET", "/api/oauth2/v1/login/publickey",
            headers_extra=f"Cookie: {init_cookie}\r\nX-Requested-With: XMLHttpRequest\r\n")
        public_key = ""
        if "200" in status:
            public_key = json.loads(body.decode("utf-8")).get("rsaPublicKey", "")
        if not public_key:
            raise Exception("无法获取 RSA 公钥，登录中止")

        payload = json.dumps({
            "username": user,
            "password": self._rsa_encrypt(pwd, public_key),
            "parameters": login_params,
        })

        login_headers = (
            f"Content-Type: application/json\r\n"
            f"Cookie: {init_cookie}\r\n"
            f"Referer: https://{self.host}:{self.port}{auth_path}\r\n"
            f"X-Requested-With: XMLHttpRequest\r\n"
        )
        if forgery:
            login_headers += f"forgerydefense: {forgery}\r\n"

        status, hdrs, raw_hdrs, body = self._request(
            "POST", "/api/oauth2/v1/login_rsa",
            headers_extra=login_headers, body=payload)

        merged = list(cookies)
        for line in raw_hdrs.split("\r\n"):
            if line.lower().startswith("set-cookie:"):
                cv = line.split(": ", 1)[1].split(";")[0]
                if cv.split("=", 1)[-1]:
                    name = cv.split("=", 1)[0]
                    merged = [c for c in merged if not c.startswith(name + "=")]
                    merged.append(cv)
                    if "forgerydefense" in cv:
                        forgery = cv.split("=", 1)[1]

        text = body.decode("utf-8", errors="replace")
        ok = ("302" in status or "uportal" in text or "portal" in text.lower()
              or "default.html" in text or any("Z-AUTH-CODE" in c for c in merged)
              or len(merged) > 3)
        if not ok:
            raise Exception(f"登录失败 - 未获取到鉴权 Cookie: {status} {text[:200]}")

        self.cookie = "; ".join(merged)
        self.forgery_token = forgery
        logger.info(f"[LOGIN] OK - {len(merged)} cookies, forgery={'yes' if forgery else 'no'}")
        return self

    # ---------- 查询 / 轮询 / 导出 ----------
    def create_query(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        status, hdrs, raw, resp = self._request_retry(
            "POST", HISTORY_PATH, headers_extra=self._auth_headers(), body=body)
        text = resp.decode("utf-8", errors="replace")
        if "200" not in status:
            raise Exception(f"Create query failed: {status} {text[:300]}")
        data = json.loads(text)
        qid = data.get("queryid") or data.get("id")
        if not qid:
            raise Exception(f"No queryid returned: {text[:300]}")
        return qid

    def wait_ready(self, queryid, timeout=600, interval=5):
        path = f"{HISTORY_POLL_PATH}?type=0&queryid={queryid}"
        deadline = time.time() + timeout
        last = {}
        while time.time() < deadline:
            status, hdrs, raw, resp = self._request_retry(
                "GET", path, headers_extra=self._auth_headers(), max_retries=1)
            text = resp.decode("utf-8", errors="replace")
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                time.sleep(interval)
                continue
            last = data
            progress = data.get("progress", data.get("Progress", 0))
            state = data.get("querystate", data.get("state", -1))
            if state in (2, 3):
                raise Exception(f"Query failed on server: querystate={state}")
            if state == 1 or progress >= 100:
                return data
            time.sleep(interval)
        raise Exception(f"Query timed out after {timeout}s (last={last})")

    def export_memory(self, queryid, filename):
        """导出结果为内存 xlsx bytes（自动解 ZIP 外壳）。"""
        payload = {
            "id": queryid, "filename": filename, "exportfiletype": 1,
            "itemshowtype": 0, "contentmode": 0, "customizefieldtype": "0",
            "imageinfo": [], "chartlayout": 1, "exportserialnumber": False,
            "exporttableheaders": False, "tableheaders": {},
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        status, hdrs, raw, resp = self._request_retry(
            "POST", HISTORY_EXPORT_PATH, headers_extra=self._auth_headers(), body=body)
        if "200" not in status:
            raise Exception(f"Export failed: {status} {resp[:200]!r}")
        # 导出接口返回 ZIP 包裹的 xlsx（PK 头），内存解包
        if len(resp) > 4 and resp[:2] == b"PK":
            try:
                import zipfile
                z = zipfile.ZipFile(io.BytesIO(resp))
                names = [n for n in z.namelist() if n.lower().endswith(".xlsx")] or z.namelist()
                if names:
                    resp = z.read(names[0])
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[EXPORT] ZIP unwrap failed ({e}), treating as raw xlsx")
        return resp


# ============================================================
# Payload 构造（字段顺序与 url.txt 严格一致）
# ============================================================
def build_payload(spec, start_iso=None, end_iso=None, relative=None, days_back=DAYS_BACK):
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if end_iso is None:
        end_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if start_iso is None:
        start_iso = (now - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if relative is None:
        relative = -days_back

    items = spec["items"]
    return {
        "arraycounterinfos": [],
        "displaymode": 0,
        "favoriteconditionname": spec["template"],
        "gr": "86400",
        "groupattributetype": 0,
        "groupbygroup": False,
        "groupbyplmn": False,
        "grouptype": 0,
        "items": items,
        "itemsposition": [0] * len(items),
        "itemsposition1": [0] * len(items),
        "motid": spec["motid"],
        "nfctid": "cn.vas.zxin",
        "plmnpdfdisplaymode": False,
        "queryallbusiness": False,
        "showbusinesscolumn": False,
        "showintegrity": False,
        "straightquery": False,
        "templatename": spec["template"],
        "templateid": spec["templateid"],
        "needdeployfilter": False,
        "timeinfo": {
            "mode": 1,
            "start": start_iso,
            "end": end_iso,
            "relative": relative,
            "timezonetype": "1",
            "clienttimezone": "Atlantic/Reykjavik",
            "showtimezoneoffset": False,
            "querylongtime": {"type": 0, "value": "3"},
            "timespanfilter": "00:00:00-24:00:00",
            "dayfiltertype": 0,
            "dayinmonthfilter": "1111111111111111111111111111111",
        },
        "thresholdinfos": [],
        "templatetype": 0,
        "filterlayer": "all",
        "grouplayer": "me,fservice",
        "containvcell": 0,
        "resfilterattribute": "",
        "uilocations": [],
        "reslocation": [],
        "inexistenceres": False,
        "firstDayOfWeek": 7,
        "iswireless": False,
        "hidehistorystopbutton": False,
        "opencustomizehistoryexport": False,
        "opentemplatecustomcolumn": False,
    }


# ============================================================
# 采集
# ============================================================
def fetch_one(client, spec, start_iso=None, end_iso=None, relative=None,
              days_back=DAYS_BACK):
    """抓取单个模板，返回 (key, headers, data)。"""
    payload = build_payload(spec, start_iso, end_iso, relative, days_back)
    qid = client.create_query(payload)
    client.wait_ready(qid)
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    fname = spec["template"].replace(" ", "_")
    xlsx = client.export_memory(qid, f"{fname}_{ts}")
    headers, data = read_xlsx_bytes(xlsx)
    logger.info(f"[FETCH] {spec['key']}: {len(data)} rows, {len(headers)} cols")
    return spec["key"], headers, data


def fetch_all(days_back=DAYS_BACK, specs=None):
    """并行抓取全部模板，返回 (datasets, errors)。datasets = [(key, headers, data)]"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    specs = specs or KPI_SPECS
    client = UMEPortalClient().login()
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    start_iso = (now - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    datasets, errors = [], []
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as ex:
        futs = {ex.submit(fetch_one, client, s, start_iso, end_iso, -days_back,
                          days_back): s for s in specs}
        for fut in as_completed(futs):
            spec = futs[fut]
            try:
                datasets.append(fut.result())
            except Exception as e:  # noqa: BLE001
                errors.append(f"{spec['key']}: {e}")
                logger.error(f"[FETCH] {spec['key']} failed: {e}")
    return datasets, errors


def save_datasets(datasets, table=TABLE_NAME):
    """把各模板数据合并写入主库：统一追加 KPI 列作为维度，主键 Begin Time+KPI+NE+SERVICE。"""
    total = 0
    errors = []
    for key, headers, data in datasets:
        try:
            if not data:
                continue
            hdr = ["KPI"] + list(headers)
            rows = [[key] + list(r) for r in data]
            key_cols = [c for c in KEY_COLS if c in hdr]
            key_cols = ensure_unique_key_cols(hdr, rows, key_cols)
            total += save_to_db(table, hdr, rows, key_cols)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{key}(写库): {e}")
            logger.error(f"[SAVE] {key} failed: {e}")
    return total, errors


def run_ume_in_kpi_sync(days_back=DAYS_BACK):
    """定时任务入口：登录 → 抓 7 个模板 → 写主库 → 返回结果摘要。"""
    t0 = time.time()
    logger.info(f"[MAIN] ume_in KPI sync start, days_back={days_back}, table={TABLE_NAME}")
    result = {"success": False, "rows_written": 0, "table": TABLE_NAME,
              "kpis": [], "errors": [], "days_back": days_back}
    try:
        datasets, errors = fetch_all(days_back=days_back)
        result["errors"].extend(errors)
        if not datasets:
            result["errors"].append("无任何模板抓取成功，跳过写库")
            return result
        result["kpis"] = [k for k, _, _ in datasets]
        rows, save_errors = save_datasets(datasets)
        result["errors"].extend(save_errors)
        result["rows_written"] = rows
        result["success"] = rows > 0 and not errors
    except Exception as e:  # noqa: BLE001
        result["errors"].append(str(e))
        logger.exception("[MAIN] ume_in KPI sync failed")
    finally:
        gc.collect()
    logger.info(f"[MAIN] done in {time.time() - t0:.1f}s, rows={result['rows_written']}, "
                f"errors={result['errors']}")
    return result


# ============================================================
# 读数 + 分析
# ============================================================
def _num(v):
    """把库里的 TEXT 值转 float；不可解析返回 None。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _load_rows(days=None):
    """读主库表，返回 (rows:list[dict], columns)。表不存在时返回 ([], [])。"""
    try:
        with get_raw_connection(timeout=30.0) as conn:
            cur = conn.cursor()
            cur.execute(f'SELECT * FROM "{TABLE_NAME}"')
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[LOAD] 读取 {TABLE_NAME} 失败（可能尚未建表）: {e}")
        return [], []

    for r in rows:
        bt = str(r.get("Begin Time") or "")
        r["_day"] = bt[:10]
    if days:
        keep = sorted({r["_day"] for r in rows if r["_day"]})[-days:]
        ks = set(keep)
        rows = [r for r in rows if r["_day"] in ks]
    return rows, cols


def _rate_status(rate):
    """服务质量配色（总成功率，仅用于展示，不触发告警）。"""
    if rate is None:
        return "unknown"
    if rate < SUCCESS_CRIT:
        return "critical"
    if rate < SUCCESS_WARN:
        return "warning"
    return "good"


def _sys_status(sys_fail_rate):
    """系统健康（系统侧失败率，真正决定告警等级）。"""
    if sys_fail_rate is None:
        return "unknown"
    if sys_fail_rate >= SYS_FAIL_CRIT:
        return "critical"
    if sys_fail_rate >= SYS_FAIL_WARN:
        return "warning"
    return "good"


def _res_status(avg, top):
    """资源健康：以日均值为准（峰值 top=100% 常为瞬时尖峰，单独看会误报）。"""
    if avg is None and top is None:
        return "unknown"
    if avg is not None and avg >= RES_CRIT:
        return "critical"
    if avg is not None and avg >= RES_WARN:
        return "warning"
    if top is not None and top >= RES_SPIKE_TOP and (avg or 0) >= RES_SPIKE_BASE:
        return "warning"
    return "good"


def _analyze_success_kpi(spec, rows, days):
    """业务量类 KPI：总成功率 + 失败按「系统侧/用户侧」归因 + 多日趋势。"""
    attempt_col = spec.get("attempt_col")
    success_col = spec.get("success_col")
    fail_cols = spec.get("fail_cols") or []
    extra_cols = spec.get("extra_cols") or []
    is_alarm = spec.get("alarm", True)

    by_day = {}
    for r in rows:
        by_day.setdefault(r["_day"], []).append(r)

    def agg(rs):
        att = sum(_num(r.get(attempt_col)) or 0 for r in rs) if attempt_col else 0.0
        if success_col:
            suc = sum(_num(r.get(success_col)) or 0 for r in rs)
        else:
            fail_sum = sum(sum(_num(r.get(c)) or 0 for c, _l, _s in fail_cols) for r in rs)
            suc = max(att - fail_sum, 0.0)

        fails, sys_f, user_f = [], 0.0, 0.0
        for col, label, side in fail_cols:
            v = sum(_num(r.get(col)) or 0 for r in rs)
            if v:
                fails.append({"name": label, "name_en": _en(FAIL_LABEL_EN, label),
                              "col": col, "side": side, "value": v})
            if side == "system":
                sys_f += v
            elif side == "user":
                user_f += v

        extras = [{"name": lb, "name_en": lb_en, "value": sum(_num(r.get(c)) or 0 for r in rs)}
                  for c, lb, lb_en in extra_cols]

        failed = (sys_f + user_f) if fail_cols else (max(att - suc, 0.0) if att else 0.0)
        rate = (suc / att) if att else None
        sys_rate = (sys_f / att) if att else None
        user_ratio = (user_f / failed) if failed else None

        if not is_alarm:
            status = "info"
        elif fail_cols:
            status = _sys_status(sys_rate)
        else:
            status = _rate_status(rate)

        return {
            "attempts": att, "success": suc, "failed": failed,
            "success_rate": rate, "system_failed": sys_f, "user_failed": user_f,
            "system_fail_rate": sys_rate, "user_fail_ratio": user_ratio,
            "rate_status": _rate_status(rate), "status": status,
            "failures": sorted(fails, key=lambda x: -x["value"]),
            "extras": extras,
        }

    trend = []
    for d in days:
        a = agg(by_day.get(d, []))
        trend.append({"day": d, "attempts": a["attempts"], "success": a["success"],
                      "failed": a["failed"], "success_rate": a["success_rate"],
                      "system_failed": a["system_failed"],
                      "system_fail_rate": a["system_fail_rate"]})

    latest = days[-1] if days else None
    latest_rows = by_day.get(latest, [])
    services = []
    for r in sorted(latest_rows, key=lambda x: str(x.get("SERVICE") or "")):
        a = agg([r])
        services.append({
            "service": r.get("SERVICE"), "ne": r.get("NE"),
            "attempts": a["attempts"], "success": a["success"], "failed": a["failed"],
            "success_rate": a["success_rate"],
            "system_failed": a["system_failed"], "user_failed": a["user_failed"],
            "system_fail_rate": a["system_fail_rate"],
            "user_fail_ratio": a["user_fail_ratio"],
            "rate_status": a["rate_status"], "status": a["status"],
            "failures": a["failures"],
        })

    total = agg(latest_rows)
    return {
        "key": spec["key"], "title_zh": spec["title_zh"], "title_en": spec["title_en"],
        "kind": "success_rate", "day": latest,
        "alarm": is_alarm,
        "rate_label_zh": spec.get("rate_label_zh", "成功率"),
        "rate_label_en": spec.get("rate_label_en", "Success rate"),
        "attempts": total["attempts"], "success": total["success"],
        "failed": total["failed"], "success_rate": total["success_rate"],
        "system_failed": total["system_failed"], "user_failed": total["user_failed"],
        "system_fail_rate": total["system_fail_rate"],
        "user_fail_ratio": total["user_fail_ratio"],
        "status": total["status"], "rate_status": total["rate_status"],
        "failures": total["failures"], "extras": total["extras"],
        "services": services, "trend": trend,
        "attempt_col": attempt_col, "success_col": success_col,
    }


def _analyze_resource_kpi(spec, rows, days):
    """资源类 KPI：按天×SERVICE 汇总均值/峰值 + 趋势。"""
    pcol, tcol = spec.get("primary_col"), spec.get("top_col")

    by_day = {}
    for r in rows:
        by_day.setdefault(r["_day"], []).append(r)

    def peak(rs, col):
        vals = [v for v in (_num(r.get(col)) for r in rs) if v is not None]
        return max(vals) if vals else None

    def mean(rs, col):
        vals = [v for v in (_num(r.get(col)) for r in rs) if v is not None]
        return sum(vals) / len(vals) if vals else None

    trend = []
    for d in days:
        rs = by_day.get(d, [])
        trend.append({"day": d, "avg": mean(rs, pcol), "top": peak(rs, tcol)})

    latest = days[-1] if days else None
    services = []
    for r in sorted(by_day.get(latest, []), key=lambda x: str(x.get("SERVICE") or "")):
        avg, top = _num(r.get(pcol)), _num(r.get(tcol))
        services.append({
            "service": r.get("SERVICE"), "ne": r.get("NE"),
            "avg": avg, "top": top, "status": _res_status(avg, top),
            "capacity_kb": _num(r.get(spec.get("capacity_col"))) if spec.get("capacity_col") else None,
            "used_kb": _num(r.get(spec.get("used_col"))) if spec.get("used_col") else None,
            "free_kb": _num(r.get(spec.get("free_col"))) if spec.get("free_col") else None,
        })

    rs_latest = by_day.get(latest, [])
    avg_all, top_all = mean(rs_latest, pcol), peak(rs_latest, tcol)
    return {
        "key": spec["key"], "title_zh": spec["title_zh"], "title_en": spec["title_en"],
        "kind": "resource", "day": latest,
        "avg": avg_all, "top": top_all,
        "status": _res_status(avg_all, top_all),
        "services": services, "trend": trend,
    }


def _build_alerts(kpis):
    """生成告警/提示清单。

    告警（critical/warning）只来自**系统侧失败率**与**资源利用率**；
    总成功率偏低但失败集中在用户侧时，只给 info 级提示（避免把业务正常结果当故障）。
    """
    def _g(v):
        return "—" if v is None else f"{v:g}"

    alerts = []
    for k in kpis:
        if k["kind"] == "success_rate":
            for s in k["services"]:
                if s["status"] in ("critical", "warning") and s["system_fail_rate"] is not None:
                    thr = SYS_FAIL_CRIT if s["status"] == "critical" else SYS_FAIL_WARN
                    alerts.append({
                        "level": s["status"], "kpi": k["key"],
                        "kpi_title": k["title_zh"], "kpi_title_en": k["title_en"],
                        "service": s["service"],
                        "metric": "系统侧失败率", "metric_en": "System-side failure rate",
                        "metric_code": METRIC_SYS_FAIL, "message_code": METRIC_SYS_FAIL,
                        "value": s["system_fail_rate"], "unit": "ratio", "threshold": thr,
                        "message": (f"{k['title_zh']} / {s['service']} 系统侧失败率 "
                                    f"{s['system_fail_rate'] * 100:.2f}%（阈值 {thr * 100:g}%）"),
                    })
            if (k["status"] == "good" and k["rate_status"] in ("critical", "warning")
                    and (k["user_fail_ratio"] or 0) >= 0.9 and k["success_rate"] is not None):
                top = k["failures"][0] if k["failures"] else None
                top_zh = top["name"] if top else "用户侧原因"
                top_en = (top.get("name_en") if top else None) or "user-side reasons"
                alerts.append({
                    "level": "info", "kpi": k["key"],
                    "kpi_title": k["title_zh"], "kpi_title_en": k["title_en"],
                    "service": None,
                    "metric": k["rate_label_zh"], "metric_en": k["rate_label_en"],
                    "metric_code": METRIC_SUCCESS_RATE, "message_code": "user_side",
                    "value": k["success_rate"], "unit": "ratio", "threshold": SUCCESS_CRIT,
                    "top_reason": top_zh, "top_reason_en": top_en,
                    "user_fail_ratio": k["user_fail_ratio"],
                    "message": (f"{k['title_zh']} {k['rate_label_zh']} "
                                f"{k['success_rate'] * 100:.2f}%，但 "
                                f"{(k['user_fail_ratio'] or 0) * 100:.1f}% 的失败属用户侧"
                                f"（主因：{top_zh}），系统侧正常"),
                })
        else:
            for s in k["services"]:
                if s["status"] in ("critical", "warning"):
                    avg, top = s["avg"], s["top"]
                    # 「实测值 / 阈值」必须同口径：日均超标就报日均，尖峰触发就报峰值
                    if avg is not None and avg >= RES_WARN:
                        value, thr, basis = avg, (RES_CRIT if s["status"] == "critical" else RES_WARN), "avg"
                    else:
                        value, thr, basis = top, RES_SPIKE_TOP, "top"
                    alerts.append({
                        "level": s["status"], "kpi": k["key"],
                        "kpi_title": k["title_zh"], "kpi_title_en": k["title_en"],
                        "service": s["service"],
                        "metric": k["title_zh"], "metric_en": k["title_en"],
                        "metric_code": METRIC_RESOURCE, "message_code": "resource",
                        "value": value, "unit": "%", "threshold": thr,
                        "avg": avg, "top": top, "basis": basis,
                        "message": (f"{k['title_zh']} / {s['service']} 日均 {_g(avg)}%、"
                                    f"峰值 {_g(top)}%（"
                                    + ("日均超标" if basis == "avg" else "峰值超标")
                                    + f"，阈值 {thr:g}%）"),
                    })

    order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: (order.get(a["level"], 9), -(a["value"] or 0)))
    return alerts


def load_overview(days=7):
    """读取主库数据并输出看板所需的完整分析结果。"""
    t0 = time.time()
    rows, _cols = _load_rows()
    all_days = sorted({r["_day"] for r in rows if r["_day"]})
    if not all_days:
        return {
            "meta": {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     "source": f"https://{HOST}:{PORT}{LOGIN_PORTAL}",
                     "table": TABLE_NAME,
                     "days": [], "latest_day": None, "total_rows": 0,
                     "has_data": False, "thresholds": {
                         "success_warn": SUCCESS_WARN, "success_crit": SUCCESS_CRIT,
                         "sys_fail_warn": SYS_FAIL_WARN, "sys_fail_crit": SYS_FAIL_CRIT,
                         "res_warn": RES_WARN, "res_crit": RES_CRIT}},
            "summary": {"kpi_count": 0, "service_count": 0, "healthy": 0,
                        "warning": 0, "critical": 0, "info": 0, "alert_count": 0,
                        "total_attempts": 0, "total_failed": 0,
                        "total_system_failed": 0, "total_user_failed": 0},
            "kpis": [], "alerts": [],
        }

    days = all_days[-max(1, days):]
    keep = set(days)
    rows = [r for r in rows if r["_day"] in keep]

    kpis = []
    for spec in KPI_SPECS:
        sub = [r for r in rows if str(r.get("KPI")) == spec["key"]]
        if not sub:
            continue
        if spec["kind"] == "success_rate":
            kpis.append(_analyze_success_kpi(spec, sub, days))
        else:
            kpis.append(_analyze_resource_kpi(spec, sub, days))

    alerts = _build_alerts(kpis)
    healthy = sum(1 for k in kpis if k["status"] == "good")
    warning = sum(1 for k in kpis if k["status"] == "warning")
    critical = sum(1 for k in kpis if k["status"] == "critical")
    info = sum(1 for k in kpis if k["status"] == "info")

    latest = days[-1]
    service_count = len({str(r.get("SERVICE")) for r in rows if r["_day"] == latest})

    return {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": f"https://{HOST}:{PORT}{LOGIN_PORTAL}",
            "table": TABLE_NAME, "days": days, "latest_day": latest,
            "total_rows": len(rows), "has_data": True,
            "elapsed_seconds": round(time.time() - t0, 3),
            "thresholds": {"success_warn": SUCCESS_WARN, "success_crit": SUCCESS_CRIT,
                           "sys_fail_warn": SYS_FAIL_WARN, "sys_fail_crit": SYS_FAIL_CRIT,
                           "res_warn": RES_WARN, "res_crit": RES_CRIT},
        },
        "summary": {"kpi_count": len(kpis), "service_count": service_count,
                    "healthy": healthy, "warning": warning, "critical": critical,
                    "info": info, "alert_count": len(alerts),
                    "total_attempts": sum(k.get("attempts") or 0 for k in kpis),
                    "total_failed": sum(k.get("failed") or 0 for k in kpis),
                    "total_system_failed": sum(k.get("system_failed") or 0 for k in kpis),
                    "total_user_failed": sum(k.get("user_failed") or 0 for k in kpis)},
        "kpis": kpis,
        "alerts": alerts,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    print(run_ume_in_kpi_sync())
