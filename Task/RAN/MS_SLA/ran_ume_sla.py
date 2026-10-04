# -*- coding: utf-8 -*-
"""
RAN UME SLA 指标同步脚本

功能：
1. 登录 ZTE RAN UME 网管系统，获取鉴权 Cookie 与 forgery token。
2. 根据 Payload.txt 中的配置，批量创建 12 类 SLA 历史指标查询任务：
   - 技术类型：GSM、UMTS、FDD
   - 时间粒度：1Month（2592000 秒）、1Day（86400 秒）
   - 聚合层级：Sites、NW
3. 轮询查询进度直到完成，导出为 Excel 文件。
4. 读取导出的 Excel 文件，写入 SQLite 数据库 lbr_ms_sla_kpi.sqlite3。
   表名规则：Hourly_<文件名基础部分>
5. 上传数据库到 FTP /01_RPA/LBR_Tools/KPI/MS_SLA。
6. 清理本地已处理的 xlsx 文件。

文件命名规则（与 Payload.txt 一致）：
  {templatename}_{grouplayer}_{gr}.xlsx
  其中 grouplayer 和 gr 会替换为可读名称。
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
import subprocess
import sqlite3
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from ftplib import FTP, error_perm

import openpyxl


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

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# ============================================================
# 配置
# ============================================================
HOST = "10.100.28.27"
PORT = 28001
USERNAME = "NOC"
PASSWORD = _get_credential("zte_ume", env="RAN_UME_PASS")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

# 并行查询线程数
MAX_PARALLEL_WORKERS = int(os.environ.get("SLA_PARALLEL_WORKERS", "4"))

# 时间范围：默认最近 32 天
DAYS_BACK = int(os.environ.get("SLA_DAYS_BACK", "32"))

# SLA 接口路径
SLA_HISTORY_PATH = "/api/pm-analysis/v2/history"
SLA_HISTORY_POLL_PATH = "/api/pm-analysis/v1/history"
SLA_HISTORY_EXPORT_PATH = "/api/pm-analysis/v3/history/export"
SLA_REFERER = f"https://{HOST}:{PORT}/iui/pm/angularTask/dist/pmManagement.html"

# 数据库配置
DB_NAME = "lbr_ms_sla_kpi.sqlite3"
DB_PATH = os.path.join(SCRIPT_DIR, DB_NAME)
BATCH_SIZE = 2000

# 是否使用与旧脚本（lbr_ms_sla_kpi_monthly.py / daily.py）一致的表名
# True:  Hourly_KPI_RPA_SITE_MS_SLA_GSM1month_SITE
# False: Hourly_KPI_RPA_SITE_MS_SLA_GSM_Sites_1Month
USE_LEGACY_TABLE_NAMES = True

# FTP 配置
FTP_HOST = "192.168.100.19"
FTP_USER = "ZTEEMS"
FTP_PASS = "DX"
FTP_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI/MS_SLA"

# 备用鉴权信息
FALLBACK_COOKIE = (
    "X-Rm-Data-Version-zenap=1773367620002_0_0_0_0_0_0_0_0; "
    "Z-AUTH-CODE-28001=1154983705_f188b025b7b64878ae0f4511e90ab1a2; "
    "x-dexmesh-user-28001=D86935A99B38A02CDAEA05C225E9303A21FA22B872499884D7B2A1E26A5645FE; "
    "forgerydefense-28001=cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"
)
FALLBACK_FORGERY = "cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"

# grouplayer / gr 显示名称替换规则
GROUP_LAYER_RENAME = {
    "me,WV4.IubLink": "Sites",
    "me,gv4.BTSSiteManager": "Sites",
    "me,eNodeBFunction": "Sites",
    "all": "NW",
}
GR_RENAME = {
    "2592000": "1Month",
    "86400": "1Day",
}

# SLA 查询配置（从 Payload.txt 提取）
SLA_QUERY_CONFIGS = {
    "GSM": {
        "templateid": "1638004472426",
        "templatename": "KPI_RPA_SITE_MS_SLA_GSM",
        "motid": "gsmPm.cell",
        "nfctid": "MRNC",
        "containvcell": 0,
        "indexfillingtype": "zeroDenominator",
        "showbusinesscolumn": False,
        "versiondatacompare": False,
        "items": [
            "306024", "900241213", "901415213", "306002", "306006", "306003",
            "306008", "306035", "306036", "900008213", "1675910745777", "306004",
            "1638004469689", "1675910745799",
        ],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    },
    "UMTS": {
        "templateid": "1638004472427",
        "templatename": "KPI_RPA_SITE_MS_SLA_UMTS",
        "motid": "wPm.UtranCell,wPm.LogicCell",
        "nfctid": "MRNC",
        "containvcell": 2,
        "indexfillingtype": "zeroDenominator",
        "showbusinesscolumn": False,
        "versiondatacompare": False,
        "items": [
            "300249", "300240", "300294", "300243", "901593214", "300020",
            "300046", "300073", "300476", "300478", "300532", "300857",
            "300824", "300840", "901597214", "901598214", "300139", "900005214",
            "901411214", "901410214", "901620214", "901621214", "901622214",
            "901623214", "901604214", "901605214", "901603214", "901596214",
        ],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    },
    "FDD": {
        "templateid": "1638004472428",
        "templatename": "KPI_RPA_SITE_MS_SLA_FDD",
        "motid": "EUtranCellFDD",
        "businessmotid": "EUtranCellFDD,FDDV3.EUtranCellFDD",
        "nfctid": "ITBBU,SDR,#",
        "containvcell": 0,
        "indexfillingtype": "zeroDenominator",
        "showbusinesscolumn": True,
        "items": [
            "1638004469333", "1638004469335", "1638004469337", "1638004469340",
            "1638004469341", "1638004469330", "1638004469331", "C373343602",
            "C373343605", "1638004469342", "1638004469343", "1638004469344",
            "1638004469345", "C373200029", "C373364118", "C373353961",
            "1638004469332", "1638004469785", "1603456136636", "1638004477799",
        ],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [2, 2, 2, 2, 2, 2, 2, 1, 1, 2, 2, 2, 2, 1, 1, 1, 2, 2, 2, 2],
        "itempositionbusiness": [0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0],
    },
}

# ============================================================
# HTTP / SSL 工具函数
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


# ============================================================
# 登录
# ============================================================
def login():
    """
    执行 RAN UME 登录流程（优先使用共享缓存，避免同账户重复登录）。
    返回包含 cookie 和 forgery_token 的字典；失败时回退到 FALLBACK_COOKIE。
    """
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
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
# SLA 查询
# ============================================================
def _sla_auth_headers(cookie: str, forgery_token: str, extra: dict | None = None) -> str:
    """构造 SLA 接口需要的鉴权请求头。"""
    headers = (
        f"Content-Type: application/json; charset=UTF-8\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Encoding: gzip\r\n"
        f"Cookie: {cookie}\r\n"
        f"Referer: {SLA_REFERER}\r\n"
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
    max_retries: int = 2,
    retry_statuses: tuple | None = None,
) -> tuple:
    """
    带重试的 HTTP 请求封装。
    对 499 / 5xx 状态码进行指数退避重试。
    """
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


def build_sla_payload(
    tech: str,
    grouplayer: str,
    gr_seconds: str,
    start_iso: str | None = None,
    end_iso: str | None = None,
) -> dict:
    """
    构造 SLA 历史指标查询 Payload。

    Args:
        tech: "GSM" / "UMTS" / "FDD"
        grouplayer: 原始 grouplayer 值，如 "me,gv4.BTSSiteManager" 或 "all"
        gr_seconds: 粒度秒数，"2592000" 或 "86400"
        start_iso: 开始时间 ISO 字符串
        end_iso: 结束时间 ISO 字符串
    """
    cfg = SLA_QUERY_CONFIGS.get(tech)
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

    # 按 Payload.txt 中的字段顺序构造（部分 ZTE 接口对顺序敏感）
    payload = {
        "arraycounterinfos": [],
        "datatype": 0,
        "displaymode": 0,
        "favoriteconditionname": cfg["templatename"],
        "gr": gr_seconds,
        "groupattributetype": 0,
        "groupbygroup": False,
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

    if "versiondatacompare" in cfg:
        payload["versiondatacompare"] = cfg["versiondatacompare"]

    payload.update({
        "needdeployfilter": False,
        "timeinfo": timeinfo,
        "indexfillingtype": cfg["indexfillingtype"],
    })

    if "businessmotid" in cfg:
        payload["businessmotid"] = cfg["businessmotid"]
    if "itempositionbusiness" in cfg:
        payload["itempositionbusiness"] = cfg["itempositionbusiness"]

    payload.update({
        "thresholdinfos": [],
        "templatetype": 0,
        "filterlayer": "all",
        "grouplayer": grouplayer,
        "containvcell": cfg["containvcell"],
        "resfilterattribute": "",
        "uilocations": [],
        "reslocation": [],
        "inexistenceres": False,
    })

    if "businessmotid" in cfg:
        payload["groupbusinessids"] = []
        payload["businessfilterscope"] = []

    payload.update({
        "firstDayOfWeek": 7,
        "iswireless": True,
        "hidehistorystopbutton": True,
        "opencustomizehistoryexport": False,
        "opentemplatecustomcolumn": False,
    })

    return payload


def create_sla_history_query(cookie: str, forgery_token: str, payload: dict) -> str:
    """创建 SLA 历史指标查询任务，返回 queryid。"""
    print(f"[SLA] Creating history query: {payload.get('templatename')} / {payload.get('grouplayer')} / {payload.get('gr')}")
    body = json.dumps(payload, ensure_ascii=False)
    headers = _sla_auth_headers(cookie, forgery_token)

    try:
        status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
            "POST",
            SLA_HISTORY_PATH,
            headers_extra=headers,
            body=body.encode('utf-8'),
            max_retries=2,
        )
    except Exception as e:
        print(f"[SLA] Create query failed after retries: {e}")
        raise

    print(f"[SLA] Create query status: {status}")

    resp_text = resp_body.decode('utf-8', errors='replace')
    print(f"[SLA] Create query response: {resp_text[:500]}")

    if "200" not in status:
        print(f"[SLA] Request headers:\n{headers}")
        print(f"[SLA] Request body preview:\n{body[:1000]}")
        raise Exception(f"Create SLA query failed: {status}")

    data = json.loads(resp_text)
    queryid = data.get("queryid") or data.get("id")
    if not queryid:
        raise Exception(f"No queryid returned: {resp_text[:500]}")
    print(f"[SLA] Query ID: {queryid}")
    return queryid


def wait_sla_history_ready(
    cookie: str,
    forgery_token: str,
    queryid: str,
    timeout: int = 300,
    interval: int = 5,
) -> dict:
    """轮询 SLA 历史指标查询进度，直到完成或超时。"""
    print(f"[SLA] Polling query progress (timeout={timeout}s, interval={interval}s)...")
    path = f"{SLA_HISTORY_POLL_PATH}?type=0&queryid={queryid}"
    headers = _sla_auth_headers(cookie, forgery_token, extra={"Accept": "application/json, text/plain, */*"})

    deadline = time.time() + timeout
    while time.time() < deadline:
        status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
            "GET",
            path,
            headers_extra=headers,
            max_retries=1,
        )
        resp_text = resp_body.decode('utf-8', errors='replace')
        data = json.loads(resp_text)
        progress = data.get("progress", 0)
        querystate = data.get("querystate", 0)
        print(f"[SLA] Progress: {progress}%, state: {querystate}")

        if querystate == 1 or progress >= 100:
            print("[SLA] Query ready")
            return data

        time.sleep(interval)

    raise Exception(f"SLA query timed out after {timeout}s")


def export_sla_history(
    cookie: str,
    forgery_token: str,
    queryid: str,
    filename: str,
    output_path: str | None = None,
) -> str:
    """导出并下载 SLA 历史指标结果，返回保存的文件路径。"""
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

    print(f"[SLA] Exporting history data: {filename}")
    body = json.dumps(payload, ensure_ascii=False)
    headers = _sla_auth_headers(cookie, forgery_token)

    status, hdrs, raw_hdrs, resp_body = _http_request_with_retry(
        "POST",
        SLA_HISTORY_EXPORT_PATH,
        headers_extra=headers,
        body=body.encode('utf-8'),
        max_retries=2,
    )
    print(f"[SLA] Export status: {status}")

    if "200" not in status:
        raise Exception(f"Export SLA history failed: {status}")

    if not output_path:
        output_path = os.path.join(OUTPUT_DIR, f"{filename}.xlsx")

    with open(output_path, "wb") as f:
        f.write(resp_body)
    print(f"[SLA] Saved to: {output_path} ({len(resp_body)} bytes)")
    return output_path


# ============================================================
# 文件命名
# ============================================================
def build_sla_filename(templatename: str, grouplayer: str, gr_seconds: str) -> str:
    """按规则构造 SLA 导出文件名（不含扩展名）。"""
    group_label = GROUP_LAYER_RENAME.get(grouplayer, grouplayer)
    gr_label = GR_RENAME.get(gr_seconds, gr_seconds)
    return f"{templatename}_{group_label}_{gr_label}"


def build_legacy_table_name(tech: str, grouplayer: str, gr_seconds: str) -> str:
    """构造与旧脚本兼容的表名：Hourly_KPI_RPA_SITE_MS_SLA_<tech><period>_<layer>。"""
    period = "1month" if gr_seconds == "2592000" else "1day"
    layer = "SITE" if grouplayer != "all" else "NW"
    templatename = SLA_QUERY_CONFIGS[tech]["templatename"]
    return f"Hourly_{templatename}{period}_{layer}"


# ============================================================
# 数据库写入（参考 lbr_ms_sla_kpi_monthly.py / daily.py）
# ============================================================
def read_xlsx_streaming(filepath: str) -> tuple[list[str], list[list]]:
    """流式读取 xlsx 文件，返回 (headers, data)。"""
    with open(filepath, 'rb') as f:
        file_bytes = f.read()

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    try:
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)

        header_row = next(rows_iter)
        headers = [str(col).strip() if col is not None else f"col_{i}"
                   for i, col in enumerate(header_row)]

        data = []
        for row in rows_iter:
            if all(v is None for v in row):
                continue
            data.append(list(row))
    finally:
        wb.close()

    del file_bytes
    return headers, data


def write_to_db(db_path: str, table_name: str, headers: list[str], data: list[list]) -> int:
    """将数据写入 SQLite 数据库（全量替换策略）。"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 性能优化 PRAGMA
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=OFF")
    cursor.execute("PRAGMA cache_size=-64000")
    cursor.execute("PRAGMA temp_store=MEMORY")

    # 表已存在则删除
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    if cursor.fetchone():
        cursor.execute(f'DROP TABLE "{table_name}"')

    # 建表
    col_defs = ", ".join(
        f'"{h.replace(chr(34), chr(34)+chr(34))}" TEXT' for h in headers
    )
    cursor.execute(f'CREATE TABLE "{table_name}" ({col_defs})')

    # 批量插入
    quoted_headers = [f'"{h.replace(chr(34), chr(34)+chr(34))}"' for h in headers]
    placeholders = ", ".join(["?"] * len(headers))
    insert_sql = (
        f'INSERT INTO "{table_name}" '
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

        if len(batch) >= BATCH_SIZE:
            cursor.executemany(insert_sql, batch)
            batch.clear()

    if batch:
        cursor.executemany(insert_sql, batch)

    conn.commit()

    # 对第一列建索引
    if headers:
        first_col = headers[0].replace('"', '""')
        try:
            cursor.execute(
                f'CREATE INDEX IF NOT EXISTS "idx_{table_name}_{first_col}" '
                f'ON "{table_name}" ("{first_col}")'
            )
            conn.commit()
        except Exception:
            pass

    conn.close()
    return row_count


# ============================================================
# FTP 上传（参考 lbr_ms_sla_kpi_monthly.py / daily.py）
# ============================================================
def upload_to_ftp(local_path: str, remote_dir: str, filename: str, max_retries: int = 2) -> bool:
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


# ============================================================
# 任务执行
# ============================================================
def _run_single_sla_query(cookie: str, forgery_token: str, task_cfg: dict) -> dict | None:
    """执行单个 SLA 查询任务（用于多线程并行），返回包含文件路径与目标表名的字典。"""
    tech = task_cfg["tech"]
    grouplayer = task_cfg["grouplayer"]
    gr_seconds = task_cfg["gr"]
    task_index = task_cfg.get("index", 0)

    # 错峰启动
    stagger_sec = task_index * 0.8
    if stagger_sec > 0:
        print(f"[MAIN] SLA query [{tech}/{grouplayer}/{gr_seconds}] waiting {stagger_sec:.1f}s to stagger...")
        time.sleep(stagger_sec)

    cfg = SLA_QUERY_CONFIGS[tech]
    filename = build_sla_filename(cfg["templatename"], grouplayer, gr_seconds)
    output_path = os.path.join(OUTPUT_DIR, f"{filename}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.xlsx")

    print(f"[MAIN] Starting SLA query [{tech}/{grouplayer}/{gr_seconds}]...")

    payload = build_sla_payload(tech, grouplayer, gr_seconds)
    queryid = create_sla_history_query(cookie, forgery_token, payload)
    status = wait_sla_history_ready(cookie, forgery_token, queryid)
    print(f"[MAIN] SLA query [{tech}/{grouplayer}/{gr_seconds}] ready: totalcount={status.get('totalcount')}")

    saved_path = export_sla_history(cookie, forgery_token, queryid, filename=filename, output_path=output_path)
    print(f"[MAIN] SLA export [{tech}/{grouplayer}/{gr_seconds}] saved: {saved_path}")

    table_name = build_legacy_table_name(tech, grouplayer, gr_seconds) if USE_LEGACY_TABLE_NAMES else _derive_table_name(saved_path)
    return {"path": saved_path, "table_name": table_name}


def _derive_table_name(filepath: str) -> str:
    """根据文件路径生成表名：Hourly_<基础文件名>。"""
    base = os.path.splitext(os.path.basename(filepath))[0]
    # 去掉时间戳后缀（_20260723000000 这种 14 位数字）
    base = re.sub(r'_\d{14}$', '', base)
    return f"Hourly_{base}"


def process_xlsx_to_db(filepath: str, table_name: str | None = None) -> tuple[str, int]:
    """读取单个 xlsx 文件并写入数据库，返回 (table_name, row_count)。"""
    print(f"\n[DB] Processing {os.path.basename(filepath)}")
    t0 = time.time()
    headers, data = read_xlsx_streaming(filepath)
    t1 = time.time()
    print(f"  read: {len(data)} rows, {len(headers)} cols ({t1 - t0:.1f}s)")

    if table_name is None:
        table_name = _derive_table_name(filepath)
    t2 = time.time()
    row_count = write_to_db(DB_PATH, table_name, headers, data)
    t3 = time.time()
    print(f"  written: {row_count} rows -> {table_name} ({t3 - t2:.1f}s)")

    return table_name, row_count


def cleanup_sla_exports(output_dir: str = OUTPUT_DIR) -> int:
    """清理所有 SLA 导出文件。"""
    deleted = 0
    for cfg in SLA_QUERY_CONFIGS.values():
        templatename = cfg["templatename"]
        for grouplayer in GROUP_LAYER_RENAME.keys():
            for gr_seconds in GR_RENAME.keys():
                base_name = build_sla_filename(templatename, grouplayer, gr_seconds)
                pattern = os.path.join(output_dir, f"{base_name}_*.xlsx")
                for fpath in glob.glob(pattern):
                    if os.path.basename(fpath).startswith("~$"):
                        continue
                    try:
                        os.remove(fpath)
                        print(f"[CLEANUP] deleted: {os.path.basename(fpath)}")
                        deleted += 1
                    except PermissionError:
                        print(f"[CLEANUP] locked, retry with PowerShell: {os.path.basename(fpath)}")
                        try:
                            subprocess.run(
                                ['powershell', '-Command',
                                 f'Remove-Item -Path "{fpath}" -Force -ErrorAction Stop'],
                                capture_output=True, timeout=15,
                                creationflags=_SUBPROCESS_FLAGS,
                            )
                            if not os.path.exists(fpath):
                                print(f"[CLEANUP] deleted (force): {os.path.basename(fpath)}")
                                deleted += 1
                            else:
                                import ctypes
                                ctypes.windll.kernel32.MoveFileExW(fpath, None, 0x4)
                        except Exception as e:
                            print(f"[CLEANUP] failed: {os.path.basename(fpath)}: {e}")
                    except Exception as e:
                        print(f"[CLEANUP] failed: {os.path.basename(fpath)}: {e}")
    return deleted


def run_sla_sync(
    cookie: str | None = None,
    forgery_token: str | None = None,
    max_workers: int = MAX_PARALLEL_WORKERS,
) -> dict:
    """
    执行完整的 SLA 指标同步流程：获取 -> 入库 -> 上传 -> 清理。
    返回统计信息字典。
    """
    if not cookie or not forgery_token:
        auth = login()
        cookie = auth["cookie"]
        forgery_token = auth["forgery_token"]

    task_configs = []
    idx = 0
    for tech in SLA_QUERY_CONFIGS.keys():
        for grouplayer in ("me,gv4.BTSSiteManager", "me,WV4.IubLink", "me,eNodeBFunction", "all"):
            tech_layer_map = {
                "GSM": "me,gv4.BTSSiteManager",
                "UMTS": "me,WV4.IubLink",
                "FDD": "me,eNodeBFunction",
            }
            if grouplayer != "all" and grouplayer != tech_layer_map.get(tech):
                continue
            for gr in ("2592000", "86400"):
                task_configs.append({"tech": tech, "grouplayer": grouplayer, "gr": gr, "index": idx})
                idx += 1

    print(f"[MAIN] Total SLA tasks: {len(task_configs)}, max parallel workers: {max_workers}")

    # 1. 并行获取所有 SLA 文件
    download_results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_cfg = {
            executor.submit(_run_single_sla_query, cookie, forgery_token, cfg): cfg
            for cfg in task_configs
        }
        for future in as_completed(future_to_cfg):
            cfg = future_to_cfg[future]
            try:
                result = future.result()
                if result:
                    download_results.append(result)
            except Exception as e:
                print(f"[MAIN] SLA query [{cfg['tech']}/{cfg['grouplayer']}/{cfg['gr']}] failed: {e}")

    if not download_results:
        print("[MAIN] No files downloaded, skipping DB import.")
        return {"downloaded": 0, "imported_rows": 0, "tables": [], "ftp_ok": False}

    # 2. 顺序导入数据库
    print(f"\n[DB] Importing {len(download_results)} files to {DB_PATH}")
    total_imported = 0
    imported_tables = []
    for item in download_results:
        filepath = item["path"]
        table_name = item["table_name"]
        try:
            table_name, row_count = process_xlsx_to_db(filepath, table_name=table_name)
            total_imported += row_count
            imported_tables.append(table_name)
        except Exception as e:
            print(f"[DB] Failed to import {os.path.basename(filepath)}: {e}")

    # 3. FTP 上传已移除（数据通过 API 写入远程）
    print("\n[INFO] FTP 上传已移除，数据由 my_app API 写入远程")

    # 4. 清理本地 xlsx 文件
    print("\n[cleanup]")
    deleted_count = cleanup_sla_exports()
    print(f"  total deleted: {deleted_count} files")

    gc.collect()

    return {
        "downloaded": len(saved_files),
        "imported_rows": total_imported,
        "tables": imported_tables,
        "ftp_ok": upload_ok,
    }


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    total_start = time.time()
    print(f"[MAIN] RAN UME SLA sync started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[MAIN] Output dir: {OUTPUT_DIR}")
    print(f"[MAIN] DB path: {DB_PATH}")

    stats = run_sla_sync()

    total_elapsed = time.time() - total_start
    print("\n" + "=" * 60)
    print(f"[MAIN] Total completed in {total_elapsed:.2f} seconds")
    print(f"[MAIN] Downloaded: {stats['downloaded']} files")
    print(f"[MAIN] Imported rows: {stats['imported_rows']}")
    print(f"[MAIN] Tables: {stats['tables']}")
    print(f"[MAIN] FTP upload: {'OK' if stats['ftp_ok'] else 'FAILED'}")
