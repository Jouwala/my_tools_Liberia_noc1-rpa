# -*- coding: utf-8 -*-
"""
RAN UME CM MO Export Script (v2)

根据 new_url.txt 的接口流程，从 RAN UME 网管系统获取 CM 配置数据。

支持 5 个数据获取流程：
1. GSM      — moquery (GGsmCell)                                    → 下载 .xlsx
2. UMTS     — moquery (UUtranCellFDD)                               → 下载 .xlsx
3. ITBBU LTE — exportmultivermofile (ManagedElementType: ITBBU)
              sheetDescList: DUEUtranCellTDDLTE, DUEUtranCellFDDLTE
              treePath: /ManagedElement/ENBDUFunction/DULTE/...
4. SDR LTE  — exportmultivermofile (ManagedElementType: SDR)
              sheetDescList: EUtranCellFDD（仅此一个，DUE mocs 不存在于 SDR）
              treePath: /ManagedElement/ENBFunctionFDD/...
5. NR       — exportmultivermofile (ManagedElementType: ITBBU)
              sheetDescList: NRCellDU（完整 payload，不追加默认 mocs）
              treePath: /ManagedElement/GNBDUFunction/NRCellDU

当 new_url.txt 中的 payload 被 "Show more" 截断时，脚本会用 DEFAULT_MOC_DEFS
自动补全 sheetDescList。完整 payload 的原 sheetDescList 会被保留，不追加任何 moc。

字段提取：
  Site_ID   : ManagedElement 列（moquery 响应自带；exportvermo Excel 自带；
              若缺失则从 moId 的第一个 / 之前部分提取）
  Site_Name : NE_Name 列（exportvermo Excel 自带；moquery 无此列，
              回退到 moDescription 或 ManagedElement）
  Cell_ID   : cellLocalId / cellNo / localCellId / cellId / cellSN / cellIdentity / cId
  Cell_Name : userLabel / name

输出：
  Sheet 1 "Cell_Data"     : Site_ID, Site_Name, Cell_ID, Cell_Name, Tech
  Sheet 2 "Site_Summary"  : Site_ID, Site_Name, NumberOfCells, Tech,
                            region, province_county, site_caregory（来自主库 master_site_db，按站点名匹配）
  Sheet 3 "Tech_Summary"  : Tech, Total_Sites, Total_Cells
"""

import base64
import gc
import glob
import gzip
import io
import json
import os
import re
import shutil
import socket
import ssl
import sys
import time
import urllib.parse
import warnings
import zipfile
from datetime import datetime

import openpyxl
import pandas as pd

try:
    # line_buffering=True：worker 长驻进程 stdout 是块缓冲，裸 print() 的
    # [TASK]/[POLL] 诊断会一直憋在缓冲里不落盘（2026-08-15 排查痛点），
    # 改行缓冲后每次 print 立即落日志。
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
except Exception:
    pass

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")
warnings.filterwarnings("ignore", category=FutureWarning)
pd.set_option("future.no_silent_downcasting", True)

# ============================================================
# 配置
# ============================================================
HOST = "10.100.28.27"
PORT = 28001
USERNAME = "NOC"
PASSWORD = "Zte@2025!"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# my_app 根目录（backend/services/cm_data -> my_app）；数据统一存放于 data/cm_data/（服务隔离）
MY_APP_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
DATA_DIR = os.path.join(MY_APP_ROOT, "data", "cm_data")
OUTPUT_DIR = DATA_DIR
URL_TXT_PATH = os.path.join(SCRIPT_DIR, "new_url.txt")
# 页面编辑产物：Settings「任务配置」页签修改网元/流程后写入此结构化文件，
# 解析时优先于 new_url.txt（new_url.txt 保留为遗留回退/参考）
CM_FLOWS_PATH = os.path.join(SCRIPT_DIR, "cm_flows.json")
RAW_DATA_DIR = os.path.join(DATA_DIR, "raw_data")
# 远程写入失败时的本地回退库
LOCAL_DB_PATH = os.path.join(DATA_DIR, "cm_cell_data.sqlite3")

# 远程数据库写入配置（DbWriterClient API 直写，full_replace 快照替换）
REMOTE_DB_NAME = "db.sqlite3"
CELL_TABLE = "cm_cell_data"
SUMMARY_TABLE = "cm_site_summary"

# 远程写入客户端（定时任务加载时走 backend.services 路径，独立运行时直连）
try:
    from backend.services.db_writer_client import DbWriterClient
except ImportError:
    try:
        sys.path.insert(0, os.path.join(SCRIPT_DIR, ".."))
        from db_writer_client import DbWriterClient
    except ImportError:
        DbWriterClient = None
        print("[WARNING] db_writer_client 不可用，数据库写入仅能回退本地 SQLite")

_db_writer = DbWriterClient() if DbWriterClient is not None else None

# API 路径
MOQUERY_PATH = "/api/randps/v1/ManagedElementType/MRNC/moquery"
EXPORT_VERMO_PATH = "/api/tpdatahandle/v1/exportmultivermofile"
STATUS_PATH = "/api/cmtaskmng/v1/taskstatus"
DOWNLOAD_PATH = "/api/cmtaskmng/v1/task/exportFile"
REFERER = f"https://{HOST}:{PORT}/uportal/framework/default.html"

# ============ 瞬时失败自愈配置（2026-08-15 新增） ============
# HTTP 层：连接级失败（未收到任何字节）/ HTTP 5xx 才重试，避免 POST 重复提交副作用
HTTP_RETRY_MAX = 2
HTTP_RETRY_BACKOFF = [1.0, 2.0]
# exportvermo 流程级：创建任务→轮询→下载 整体重试次数（新 taskNo 无副作用）
EXPORT_FLOW_RETRY_MAX = 2
EXPORT_FLOW_RETRY_BACKOFF = 3.0
# moquery 流程重试
MOQUERY_RETRY_MAX = 1
# 登录重试
LOGIN_RETRY_MAX = 1

# 备用鉴权信息
FALLBACK_COOKIE = (
    "X-Rm-Data-Version-zenap=1773367620002_0_0_0_0_0_0_0_0; "
    "Z-AUTH-CODE-28001=1154983705_f188b025b7b64878ae0f4511e90ab1a2; "
    "x-dexmesh-user-28001=D86935A99B38A02CDAEA05C225E9303A21FA22B872499884D7B2A1E26A5645FE; "
    "forgerydefense-28001=cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"
)
FALLBACK_FORGERY = "cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"

# 目标 sheet（含新流程可能出现的 sheet 名）
TARGET_SHEETS = [
    "EUtranCellFDD",
    "EUtranCellFDDLTE",
    "EUtranCellTDDLTE",
    "EUtranCellTDD",
    "DUEUtranCellFDDLTE",
    "DUEUtranCellTDDLTE",
    "UMTSLocalCell",
    "UUtranCellFDD",
    "GSMCarrier",
    "GGsmCell",
    "NRCellCU",
    "NRCellDU",
]

# sheet 名匹配映射（支持模糊匹配）
SHEET_MAPPING = {
    "EUtranCellFDD": "EUtranCellFDD",
    "EUtranCellFDDLTE": "EUtranCellFDDLTE",
    "EUtranCellTDDLTE": "EUtranCellTDDLTE",
    "EUtranCellTDD": "EUtranCellTDD",
    "DUEUtranCellFDDLTE": "DUEUtranCellFDDLTE",
    "DUEUtranCellTDDLTE": "DUEUtranCellTDDLTE",
    "UMTSLocalCell": "UMTSLocalCell",
    "UUtranCellFDD": "UUtranCellFDD",
    "GSMCarrier": "GSMCarrier",
    "GGsmCell": "GGsmCell",
    "NRCellCU": "NRCellCU",
    "NRCellDU": "NRCellDU",
}

# Tech 映射：sheet 名 -> 制式
TECH_MAPPING = {
    "EUtranCellFDD": "4G",
    "EUtranCellFDDLTE": "4G",
    "EUtranCellTDDLTE": "4G",
    "EUtranCellTDD": "4G",
    "DUEUtranCellFDDLTE": "4G",
    "DUEUtranCellTDDLTE": "4G",
    "UMTSLocalCell": "3G",
    "UUtranCellFDD": "3G",
    "GSMCarrier": "2G",
    "GGsmCell": "2G",
    "NRCellCU": "5G",
    "NRCellDU": "5G",
}

# ============================================================
# 外部化配置（Settings →「任务配置」维护的 cm_data_config.json）
#   优先级：环境变量 > 配置文件 > 内置默认；凭据走 credential_store(cm_data)。
#   ⚠ 必须位于上面所有被覆盖常量（含 TECH_MAPPING）之后、使用它们的函数之前；
#     REFERER 依赖 HOST/PORT，故在本块末尾重算。
# ============================================================
try:
    from backend.services.task_config_files import apply_config_overrides
except ImportError:
    from task_config_files import apply_config_overrides  # type: ignore

_CM_CONF = apply_config_overrides(
    globals(),
    os.path.join(os.path.dirname(SCRIPT_DIR), "cm_data_config.json"),
    {
        "host": ("HOST", str, "CM_HOST"),
        "port": ("PORT", int, "CM_PORT"),
        "http_retry_max": ("HTTP_RETRY_MAX", lambda v: max(0, int(v)), None),
        "export_flow_retry_max": ("EXPORT_FLOW_RETRY_MAX", lambda v: max(0, int(v)), None),
        "moquery_retry_max": ("MOQUERY_RETRY_MAX", lambda v: max(0, int(v)), None),
        "login_retry_max": ("LOGIN_RETRY_MAX", lambda v: max(0, int(v)), None),
    },
    log_name="cm_data",
)
if _CM_CONF:
    _cm_paths = _CM_CONF.get("urls") or {}
    if isinstance(_cm_paths, dict):
        if _cm_paths.get("moquery"):
            MOQUERY_PATH = _cm_paths["moquery"]
        if _cm_paths.get("export"):
            EXPORT_VERMO_PATH = _cm_paths["export"]
        if _cm_paths.get("status"):
            STATUS_PATH = _cm_paths["status"]
        if _cm_paths.get("download"):
            DOWNLOAD_PATH = _cm_paths["download"]
    _cm_sheets = _CM_CONF.get("target_sheets")
    if isinstance(_cm_sheets, list) and _cm_sheets:
        TARGET_SHEETS = [str(s).strip() for s in _cm_sheets if str(s).strip()]
        SHEET_MAPPING = {s: s for s in TARGET_SHEETS}
        for _s in TARGET_SHEETS:
            TECH_MAPPING.setdefault(_s, "4G")
REFERER = f"https://{HOST}:{PORT}/uportal/framework/default.html"

# 字段候选（按优先级）
SITE_ID_FIELDS = ["ManagedElement", "NE_Name"]
SITE_NAME_FIELDS = ["NE_Name", "moDescription", "ManagedElement"]
CELL_ID_FIELDS = ["cellLocalId", "cellNo", "localCellId", "cellId", "cellSN", "cellIdentity", "cId"]
CELL_NAME_FIELDS = ["userLabel", "userLabel ", "name"]

OUTPUT_HEADERS = ["Site_ID", "Site_Name", "Cell_ID", "Cell_Name", "Tech"]
# Site_Summary 基础列 + master_site_db 补全列（site_caregory 为源表原始拼写，保持不变）
SUMMARY_BASE_HEADERS = ["Site_ID", "Site_Name", "NumberOfCells", "Tech"]
MASTER_ATTR_COLS = ["region", "province_county", "site_caregory"]
SUMMARY_HEADERS = SUMMARY_BASE_HEADERS + MASTER_ATTR_COLS
# 去重键：Excel 导出用前4个，moquery 用后面的字段（moId/userLabel/cellIdentity/cId 等）
DEDUP_KEYS = [
    "ManagedElement", "NE_Name", "cellNo", "mainBand",  # Excel 导出
    "moId", "userLabel", "cellIdentity", "cId", "localCellId",  # moquery
]


# ============================================================
# HTTP / SSL 工具函数
# ============================================================
def _create_ssl_socket():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers('ALL:@SECLEVEL=0')
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(60)
    ssock = ctx.wrap_socket(sock)
    ssock.connect((HOST, PORT))
    return ssock


def _decode_chunked(data):
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


def _http_request_once(method, path, headers_extra=None, body=None):
    """单次 HTTP 请求（新连接）。连接级失败（未收到任何字节）抛 socket/OSError，
    交由 _http_request 重试；已收到部分响应的读取超时按"返回已读数据"处理，
    避免对 POST 盲目重试造成重复提交。"""
    ssock = _create_ssl_socket()
    try:
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
                if not response_data:
                    # 一条响应字节都没收到：视为连接级失败，可安全重试
                    raise
                break  # 已收到部分响应：返回已读部分，不在此层重试
    finally:
        try:
            ssock.close()
        except Exception:
            pass

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


def _http_request(method, path, headers_extra=None, body=None):
    """HTTP 请求（带瞬时失败重试）。

    2026-08-15 加固：RAN UME 偶发网络抖动/5xx 曾导致整任务失败。此处仅对
    「连接级失败（未收到任何响应字节）」「HTTP 5xx」重试，指数退避；
    部分响应解析失败不在此层重试（避免 POST 重复提交副作用）。
    """
    last_err = None
    for attempt in range(HTTP_RETRY_MAX + 1):
        try:
            status_line, resp_headers, header_part, resp_body = _http_request_once(
                method, path, headers_extra=headers_extra, body=body)
            code = status_line.split(" ")[1] if " " in status_line else "000"
            if code.startswith("5"):
                last_err = Exception(f"HTTP {status_line}")
                if attempt < HTTP_RETRY_MAX:
                    wait = HTTP_RETRY_BACKOFF[attempt]
                    print(f"[RETRY] {method} {path} HTTP {code}，{wait}s 后重试 "
                          f"({attempt + 1}/{HTTP_RETRY_MAX})")
                    time.sleep(wait)
                    continue
                raise last_err
            return status_line, resp_headers, header_part, resp_body
        except (socket.timeout, ConnectionError, OSError) as e:
            last_err = e
            if attempt < HTTP_RETRY_MAX:
                wait = HTTP_RETRY_BACKOFF[attempt]
                print(f"[RETRY] {method} {path} 连接异常({type(e).__name__})，"
                      f"{wait}s 后重试 ({attempt + 1}/{HTTP_RETRY_MAX})")
                time.sleep(wait)
                continue
            raise
    raise last_err


def _rsa_encrypt_pem(plaintext, public_key_b64):
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives import serialization
    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
    public_key = serialization.load_pem_public_key(pem.encode())
    encrypted = public_key.encrypt(plaintext.encode('utf-8'), asym_padding.PKCS1v15())
    return base64.b64encode(encrypted).decode('ascii')


def _runtime_credentials():
    """运行时凭据：环境变量 > credential_store > 模块默认值。

    凭据由「设置 → 凭据管理」的 cm_data 分组维护（页面改密后最迟 30 秒生效）。
    环境变量 CM_USERNAME / CM_PASSWORD 仍可作为最高优先级覆盖。
    """
    user = os.environ.get("CM_USERNAME") or None
    pwd = os.environ.get("CM_PASSWORD") or None
    if user and pwd:
        return user, pwd
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        try:
            from credential_store import get_credential  # type: ignore
        except ImportError:
            return user or USERNAME, pwd or PASSWORD
    cred_user, cred_pwd = get_credential("cm_data", USERNAME, PASSWORD)
    return user or cred_user, pwd or cred_pwd


# ============================================================
# 登录
# ============================================================
def login():
    print("[LOGIN] 开始鉴权...")
    _login_user, _login_pwd = _runtime_credentials()
    session_cookie = ""
    forgery_token = ""
    try:
        print("[LOGIN] Step 1: 获取 authorize 页面...")
        status, hdrs, raw_hdrs, body = _http_request(
            "GET",
            "/api/oauth2/v1/authorize?scope=user.login&response_type=code"
            "&redirect_uri=/uportal/framework/default.html"
        )
        init_cookies = []
        for line in raw_hdrs.split("\r\n"):
            if line.lower().startswith("set-cookie:"):
                cookie_val = line.split(": ", 1)[1].split(";")[0]
                if cookie_val.split("=")[1]:
                    init_cookies.append(cookie_val)
                    if "forgerydefense" in cookie_val:
                        forgery_token = cookie_val.split("=", 1)[1]
        init_cookie_str = "; ".join(init_cookies)

        html = body.decode('utf-8', errors='replace')
        lp_match = re.search(r'var\s+loginParameters\s*=\s*["\']([^"\']+)["\']', html)
        login_parameters = lp_match.group(1) if lp_match else ""

        print("[LOGIN] Step 2: 获取 RSA 公钥...")
        rsa_headers = f"Cookie: {init_cookie_str}\r\nX-Requested-With: XMLHttpRequest\r\n"
        status, hdrs, raw_hdrs, body = _http_request(
            "GET", "/api/oauth2/v1/login/publickey", headers_extra=rsa_headers,
        )
        public_key_b64 = ""
        if "200" in status:
            pk_data = json.loads(body.decode('utf-8'))
            public_key_b64 = pk_data.get("rsaPublicKey", "")

        print("[LOGIN] Step 3: RSA 加密密码...")
        encrypted_pwd = _rsa_encrypt_pem(_login_pwd, public_key_b64)

        print("[LOGIN] Step 4: 提交登录...")
        login_payload = json.dumps({
            "username": _login_user, "password": encrypted_pwd, "parameters": login_parameters,
        })
        login_headers = (
            f"Content-Type: application/json\r\n"
            f"Cookie: {init_cookie_str}\r\n"
            f"Referer: https://{HOST}:{PORT}/api/oauth2/v1/authorize?scope=user.login"
            f"&response_type=code&redirect_uri=/uportal/framework/default.html\r\n"
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
                if cookie_val.split("=")[1]:
                    cookie_name = cookie_val.split("=")[0]
                    cookies = [c for c in cookies if not c.startswith(cookie_name + "=")]
                    cookies.append(cookie_val)
                    if "forgerydefense" in cookie_val:
                        forgery_token = cookie_val.split("=", 1)[1]
        session_cookie = "; ".join(cookies)

        resp_text = body.decode('utf-8', errors='replace')
        if "302" in status or "default.html" in resp_text or len(cookies) > 3:
            print(f"[LOGIN] 成功 - {len(cookies)} cookies")
        else:
            if not any("Z-AUTH-CODE" in c for c in cookies):
                raise Exception("Login failed - no auth cookie obtained")
    except Exception as e:
        print(f"[LOGIN] 失败: {e}")
        print("[LOGIN] 使用备用 cookies...")
        session_cookie = FALLBACK_COOKIE
        forgery_token = FALLBACK_FORGERY
    return {"cookie": session_cookie, "forgery_token": forgery_token}


# ============================================================
# 解析 new_url.txt
# ============================================================
def _find_json_payload(text, start_pos=0):
    """从 text 中 start_pos 位置开始，用括号匹配提取完整 JSON。返回 (json_obj, end_pos) 或 (None, start_pos)。"""
    brace_start = text.find('{', start_pos)
    if brace_start == -1:
        return None, start_pos
    brace_count = 0
    for i in range(brace_start, len(text)):
        c = text[i]
        if c == '{':
            brace_count += 1
        elif c == '}':
            brace_count -= 1
        if brace_count == 0:
            json_str = text[brace_start:i + 1]
            try:
                return json.loads(json_str), i + 1
            except json.JSONDecodeError:
                return None, i + 1
    return None, len(text)


def _extract_payload_regex(text, start_pos):
    """当 JSON 被截断无法完整解析时，用正则提取关键字段构造 payload。

    提取 ManagedElementType、templateName、neList 等。
    适用于 exportmultivermofile 的超长 payload 被 "Show more" 截断的情况。

    从 start_pos 开始向后搜索第一个包含 "ManagedElementType" 的行，
    跳过 Status Code / Remote Address / Referrer Policy 等中间行。
    """
    # 从 start_pos 向后搜索 "ManagedElementType"，范围限定 1000 字符内
    search_region = text[start_pos:start_pos + 1000]
    me_idx = search_region.find('"ManagedElementType"')
    if me_idx == -1:
        return None
    # 定位到 payload 行的起始位置（往前找 { 开头）
    payload_start = start_pos + me_idx
    brace_pos = search_region.rfind('{', 0, me_idx)
    if brace_pos != -1:
        payload_start = start_pos + brace_pos
    # 找到该行的结尾（第一个换行）
    line_end = text.find("\n", payload_start)
    if line_end == -1:
        line_end = len(text)
    line = text[payload_start:line_end]

    # 提取 ManagedElementType
    me_match = re.search(r'"ManagedElementType"\s*:\s*"([^"]+)"', line)
    if not me_match:
        return None
    me_type = me_match.group(1)

    # 提取 templateName
    tpl_match = re.search(r'"templateName"\s*:\s*"([^"]+)"', line)
    template_name = tpl_match.group(1) if tpl_match else "RANCM-Custom-template"

    # 提取 neList（所有 "SubNetwork=X,ManagedElement=Y" 模式）
    ne_list = re.findall(r'"(SubNetwork=\d+,ManagedElement=\d+)"', line)
    if not ne_list:
        return None

    # 构造完整 payload（不含 excelDesc，由 enrich_exportvermo_payload 补全）
    payload = {
        "ManagedElementType": me_type,
        "templateName": template_name,
        "neList": ne_list,
        "templateType": "mo",
        "appExtend": "param_template_export",
        "exportMode": "",
        "splitNeNum": 3000,
        "needResultFile": True,
    }
    return payload


# 各 ManagedElementType 的默认 moc 定义（用于 payload 被截断或缺少 sheetDescList 时补全）
# attrNames 只保留输出所需的关键字段，避免超长 payload
DEFAULT_MOC_DEFS = {
    "ITBBU": [
        {
            "moc": "DUEUtranCellTDDLTE",
            "attrNames": ["moId", "userLabel", "cellLocalId", "refECellEquipFuncTDDLTE", "refExtECellEqFuncTDDLTE"],
            "treePath": "/ManagedElement/ENBDUFunction/DULTE/DUEUtranCellTDDLTE",
        },
        {
            "moc": "DUEUtranCellFDDLTE",
            "attrNames": ["moId", "userLabel", "cellLocalId", "refECellEquipFuncFDDLTE", "refExtECellEqFuncFDDLTE"],
            "treePath": "/ManagedElement/ENBDUFunction/DULTE/DUEUtranCellFDDLTE",
        },
    ],
    "SDR": [
        {
            "moc": "EUtranCellFDD",
            "attrNames": ["moId", "userLabel", "cellLocalId"],
            "treePath": "/ManagedElement/ENBFunctionFDD/EUtranCellFDD",
        },
    ],
}

# NRCellDU 的 moc 定义（独立流程，使用 ITBBU 的 NE 列表）
NR_CELL_DU_MOC_DEF = {
    "moc": "NRCellDU",
    "attrNames": ["moId", "userLabel", "cellLocalId", "nrPhysicalCellDUId"],
    "treePath": "/ManagedElement/GNBDUFunction/NRCellDU",
}


def enrich_exportvermo_payload(flow):
    """补全 exportvermo 流程的 sheetDescList。

    场景：
    1. payload 被 "Show more" 截断 → sheetDescList 完全缺失 → 用 DEFAULT_MOC_DEFS 补全
    2. payload 完整（如 NR 流程含 NRCellDU） → 尊重原 sheetDescList，不追加

    注意：DUEUtranCellFDDLTE/DUEUtranCellTDDLTE 只存在于 ITBBU 设备上，
    SDR 设备上不存在（API 返回 "MOC does not exist" 错误）。
    """
    payload = flow.get("payload") or {}
    me_type = payload.get("ManagedElementType", "")
    defaults = DEFAULT_MOC_DEFS.get(me_type)
    if not defaults:
        return flow

    excel_desc = payload.get("excelDesc") or {}
    sheet_list = list(excel_desc.get("sheetDescList") or [])

    # sheetDescList 完全缺失（payload 被截断）→ 用所有默认 mocs 补全
    if not sheet_list:
        for entry in defaults:
            sheet_list.append(dict(entry))
        excel_desc["sheetDescList"] = sheet_list
        payload["excelDesc"] = excel_desc
        flow["payload"] = payload
        added_names = [e["moc"] for e in defaults]
        print(f"[ENRICH] {me_type} payload 补全（截断恢复）: 追加 {added_names} (共 {len(sheet_list)} 个 moc)")
        return flow

    # sheetDescList 已存在 → 尊重原定义，不追加
    return flow


def parse_new_url_txt():
    """解析 new_url.txt，提取所有 POST 请求的 endpoint 和 payload。

    使用全文内容 + 括号匹配，能正确处理超长 JSON 行。
    跳过 ranmes/query 请求（不需要用于导出）。
    """
    print(f"[PARSE] 读取 {URL_TXT_PATH}")
    with open(URL_TXT_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    flows = []
    pos = 0

    while True:
        # 查找下一个 "Request URL:"
        url_pos = content.find("Request URL:", pos)
        if url_pos == -1:
            break

        # 提取 URL 行
        url_end = content.find("\n", url_pos)
        if url_end == -1:
            break
        url_line = content[url_pos:url_end].strip()
        url = url_line.replace("Request URL:", "").strip()
        if url.startswith(f"https://{HOST}:{PORT}"):
            url = url.replace(f"https://{HOST}:{PORT}", "")
        # 只显示 URL 的最后一段用于调试
        url_short = url.split("?")[0][-60:]

        # 查找紧随其后的 "Request Method:"
        method_pos = content.find("Request Method:", url_end)
        if method_pos == -1 or method_pos > url_end + 200:
            print(f"[PARSE] DEBUG: URL={url_short}, 未找到Method, 跳过")
            pos = url_end
            continue
        method_end = content.find("\n", method_pos)
        method_line = content[method_pos:method_end].strip()
        method = method_line.replace("Request Method:", "").strip()

        if method != "POST":
            pos = method_end
            continue

        # 查找 Method 之后的 JSON payload
        payload, payload_end = _find_json_payload(content, method_end)
        if payload is None:
            # JSON 解析失败（可能是截断的超长行），尝试用正则提取关键字段
            print(f"[PARSE] DEBUG: URL={url_short}, POST, JSON解析失败, 尝试正则提取...")
            payload = _extract_payload_regex(content, method_end)
            if payload is None:
                print(f"[PARSE] DEBUG: URL={url_short}, 正则提取也失败, 跳过")
                pos = method_end
                continue
            # 正则提取成功，pos 跳到行尾
            next_nl = content.find("\n", method_end)
            payload_end = next_nl if next_nl != -1 else len(content)
            print(f"[PARSE] DEBUG: URL={url_short}, 正则提取成功: {payload.get('ManagedElementType', '?')}")

        pos = payload_end
        print(f"[PARSE] DEBUG: URL={url_short}, POST, payload键={list(payload.keys())[:5]}")

        # 跳过 ranmes/query
        if "ranmes/query" in url:
            continue

        # 分类
        if "moquery" in url:
            moc_list = payload.get("mocList", [])
            if any("GGsmCell" in m for m in moc_list):
                name = "GSM"
            elif any("UUtranCellFDD" in m for m in moc_list):
                name = "UMTS"
            else:
                name = "Unknown"
            flow = {"name": name, "type": "moquery", "path": url, "payload": payload}
        elif "exportmultivermofile" in url:
            me_type = payload.get("ManagedElementType", "Unknown")
            flow = {"name": me_type, "type": "exportvermo", "path": url, "payload": payload}
            # 补全 sheetDescList（处理截断的 payload 和扩展 moc）
            flow = enrich_exportvermo_payload(flow)
        else:
            continue

        # 去重
        if not any(f["path"] == flow["path"] and f["payload"] == flow["payload"] for f in flows):
            ne_count = len(payload.get("neList", []))
            print(f"[PARSE] 流程: {flow['name']} ({flow['type']}), NE数: {ne_count}")
            flows.append(flow)

    print(f"[PARSE] 共解析 {len(flows)} 个流程")

    # 回退搜索：如果未找到 exportvermo 流程，直接搜索 "ManagedElementType" 提取 payload
    if not any(f["type"] == "exportvermo" for f in flows):
        print("[PARSE] 未找到 exportvermo 流程，尝试回退搜索...")
        search_pos = 0
        while True:
            me_pos = content.find('"ManagedElementType"', search_pos)
            if me_pos == -1:
                break
            # 用正则提取（处理截断的 JSON）
            payload = _extract_payload_regex(content, me_pos - 500)
            if payload is None:
                search_pos = me_pos + 1
                continue
            # 计算搜索位置（跳过当前行）
            line_end = content.find("\n", me_pos)
            search_pos = line_end if line_end != -1 else me_pos + 1
            me_type = payload.get("ManagedElementType", "Unknown")
            flow = {"name": me_type, "type": "exportvermo", "path": EXPORT_VERMO_PATH, "payload": payload}
            # 回退路径下同样补全 sheetDescList
            flow = enrich_exportvermo_payload(flow)
            if not any(f["path"] == flow["path"] and f["payload"] == flow["payload"] for f in flows):
                ne_count = len(payload.get("neList", []))
                print(f"[PARSE] 回退找到: {me_type} (exportvermo), NE数: {ne_count}")
                flows.append(flow)

    # NR 流程：始终从 new_url.txt 第 105-107 行提取 payload（覆盖主解析循环的结果）
    # 先移除主解析循环中可能已添加的含 NRCellDU 的流程（避免重复/payload 不完整）
    nr_flows_to_remove = []
    for f in flows:
        if f['type'] == 'exportvermo':
            sd = f['payload'].get('excelDesc') or {}
            sheet_list = sd.get('sheetDescList') or []
            mocs = [s.get('moc', '') for s in sheet_list if isinstance(s, dict)]
            if 'NRCellDU' in mocs:
                nr_flows_to_remove.append(f)
    for f in nr_flows_to_remove:
        flows.remove(f)
        print(f"[PARSE] 移除主解析循环中的 NRCellDU 流程: {f['name']} (将由 new_url.txt L105-107 替换)")

    # 从 new_url.txt 第 105-107 行提取 NR payload
    # 注意：文件可能使用 \r\n 换行符，用二进制模式读取避免 universal newlines 问题
    nr_payload_from_file = None
    try:
        with open(URL_TXT_PATH, 'rb') as f:
            raw = f.read()
        # 在二进制内容中搜索 NRCellDU（位于第 106 行的 payload 中）
        nr_pos = raw.find(b'NRCellDU')
        if nr_pos >= 0:
            # 找到包含 NRCellDU 的行起点（向前找换行符）
            line_start = raw.rfind(b'\n', 0, nr_pos) + 1
            # 跳过 \r
            if raw[line_start:line_start + 1] == b'\r':
                line_start += 1
            # 找到行终点（向后找换行符）
            line_end = raw.find(b'\n', nr_pos)
            if line_end < 0:
                line_end = len(raw)
            # 去掉行尾 \r
            if raw[line_end - 1:line_end] == b'\r':
                line_end -= 1
            line_bytes = raw[line_start:line_end]
            line_str = line_bytes.decode('utf-8').strip()
            if line_str.startswith('{'):
                nr_payload_from_file = json.loads(line_str)
                print(f"[PARSE] 从 new_url.txt L105-107 提取到 NR payload (NRCellDU), 行长: {len(line_str)}")
    except Exception as e:
        print(f"[PARSE] 读取 NR payload 失败: {e}")

    if nr_payload_from_file:
        nr_flow = {"name": "NR", "type": "exportvermo", "path": EXPORT_VERMO_PATH, "payload": nr_payload_from_file}
        flows.append(nr_flow)
        ne_count = len(nr_payload_from_file.get('neList', []))
        print(f"[PARSE] 添加 NR 流程 (new_url.txt L105-107), NE数: {ne_count}")
    else:
        print("[PARSE] 警告: 未能从 new_url.txt L105-107 提取 NR payload")

    print(f"[PARSE] 最终流程数: {len(flows)}")
    for f in flows:
        ne_count = len(f['payload'].get('neList', []))
        moc_info = ""
        if f['type'] == 'exportvermo':
            sd = f['payload'].get('excelDesc') or {}
            sheet_list = sd.get('sheetDescList') or []
            mocs = [s.get('moc', '?') for s in sheet_list if isinstance(s, dict)]
            moc_info = f", mocs={mocs}"
        print(f"  - {f['name']} ({f['type']}): NE数={ne_count}{moc_info}")
    return flows


# ============================================================
# 鉴权请求头
# ============================================================
def _auth_headers(cookie, forgery_token, extra=None):
    headers = (
        f"Content-Type: application/json; charset=UTF-8\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Encoding: gzip\r\n"
        f"Cookie: {cookie}\r\n"
        f"Referer: {REFERER}\r\n"
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


# ============================================================
# 创建导出任务（仅用于 exportvermo 流程）
# ============================================================
def create_task(cookie, forgery_token, flow):
    """创建导出任务，返回 taskNo。仅用于 exportvermo 流程。

    2026-08-15 加固：RAN 网络网元退役后，new_url.txt 中手工抓包的 neList 会
    包含已不存在的网元，接口返回 code=1004 且无 taskNo（曾导致整任务失败：
    "未获取到 taskNo [SDR]"）。此处对 code=1004 自动剔除被明确拒绝的网元后
    重试（最多 6 轮），只移除 API 点名的网元，其余不动；无法进展时抛原始错误。
    """
    name = flow["name"]
    path = flow["path"]
    payload = flow["payload"]
    print(f"\n[TASK] 创建任务: {name} ({flow['type']})")

    task_no = None
    for attempt in range(6):
        body = json.dumps(payload, ensure_ascii=False)
        headers = _auth_headers(cookie, forgery_token)

        status, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", path, headers_extra=headers, body=body.encode('utf-8')
        )
        print(f"[TASK] {name} Status: {status}")

        if "200" not in status:
            resp_text = resp_body.decode('utf-8', errors='replace')
            raise Exception(f"创建任务失败 [{name}]: {status}\nResponse: {resp_text[:500]}")

        resp_text = resp_body.decode('utf-8', errors='replace')
        print(f"[TASK] {name} Response (前300字符): {resp_text[:300]}")

        # 失效网元自动剔除：code=1004 时接口会指出具体 NE，移除后重试
        try:
            resp_data = json.loads(resp_text)
        except json.JSONDecodeError:
            resp_data = {}
        if isinstance(resp_data, dict) and resp_data.get("code") == 1004:
            bad_nes = list(dict.fromkeys(
                re.findall(r'SubNetwork=\d+,ManagedElement=\d+',
                           resp_data.get("message", "") or "")))
            ne_list = payload.get("neList") or []
            removed = [ne for ne in bad_nes if ne in ne_list]
            if not removed:
                msg = resp_data.get("message", "") or ""
                print(f"[TASK] {name} code=1004 但无法解析/剔除网元: {msg[:200]}")
                # 剔除记录（供 result_json.warnings 展示具体原因）
                flow.setdefault("_skipped_nes", []).append(
                    {"ne": ",".join(bad_nes) or "(无法解析)", "reason": msg[:500]})
                raise Exception(f"未获取到 taskNo [{name}]: {msg[:500]}")
            payload["neList"] = [ne for ne in ne_list if ne not in removed]
            # 记录被剔除的网元与原因（warnings 展示用）
            reason = (resp_data.get("message", "") or "")[:500]
            for ne in removed:
                flow.setdefault("_skipped_nes", []).append({"ne": ne, "reason": reason})
            print(f"[TASK] {name} 剔除失效网元 {len(removed)} 个"
                  f"（{', '.join(removed)}），剩余 {len(payload['neList'])} 个，重试")
            continue

        # 解析 taskNo
        data = resp_data
        if isinstance(data, dict):
            for key in ["taskNo", "taskno", "task_no"]:
                val = data.get(key)
                if isinstance(val, str) and val:
                    task_no = val
                    break
            if not task_no and isinstance(data.get("data"), dict):
                for key in ["taskNo", "taskno", "task_no"]:
                    val = data["data"].get(key)
                    if isinstance(val, str) and val:
                        task_no = val
                        break
            if not task_no and isinstance(data.get("data"), str):
                task_no = data["data"]

        if not task_no:
            match = re.search(r'(tpdatahandle_\w+_export_\d+_[a-f0-9-]+)', resp_text)
            if match:
                task_no = match.group(1)

        if task_no:
            break
        print(f"[TASK] {name} 响应长度: {len(resp_text)}")
        print(f"[TASK] {name} 响应尾部: ...{resp_text[-300:]}")
        # 具体原因：优先取 API message（code!=0 时），便于 UI/日志直接定位
        api_msg = ""
        if isinstance(resp_data, dict) and resp_data.get("code") != 0:
            api_msg = f": {resp_data.get('message', '')[:300]}"
        raise Exception(f"未获取到 taskNo [{name}]{api_msg}")

    if not task_no:
        print(f"[TASK] {name} 响应长度: {len(resp_text)}")
        print(f"[TASK] {name} 响应尾部: ...{resp_text[-300:]}")
        api_msg = ""
        if isinstance(resp_data, dict) and resp_data.get("code") != 0:
            api_msg = f": {resp_data.get('message', '')[:300]}"
        raise Exception(f"未获取到 taskNo [{name}]{api_msg}")

    print(f"[TASK] {name} TaskNo: {task_no}")
    return task_no


# ============================================================
# Moquery 流程：直接获取 MO 数据
# ============================================================
def execute_moquery(cookie, forgery_token, flow, retries_log=None):
    """执行 moquery 查询，直接返回 MO 数据 DataFrame。

    moquery API 直接返回 MO 数据（不创建导出任务）。
    将 ignoreDetail 改为 false 以获取实际属性值。
    2026-08-15 加固：查询/解析瞬时失败重试 MOQUERY_RETRY_MAX 次。
    """
    name = flow["name"]
    path = flow["path"]
    payload = dict(flow["payload"])  # 复制，避免修改原始

    # 修改 ignoreDetail 为 false，获取实际数据
    payload["ignoreDetail"] = False
    print(f"\n[MOQUERY] {name} 查询 MO 数据 (ignoreDetail=False)")

    data = None
    resp_text = ""
    last_exc = None
    attempt = 0
    relogin_done = False
    while True:
        try:
            body = json.dumps(payload, ensure_ascii=False)
            headers = _auth_headers(cookie, forgery_token)

            status, hdrs, raw_hdrs, resp_body = _http_request(
                "POST", path, headers_extra=headers, body=body.encode('utf-8')
            )
            print(f"[MOQUERY] {name} Status: {status}")

            if "200" not in status:
                resp_text = resp_body.decode('utf-8', errors='replace')
                raise Exception(f"moquery 失败 [{name}]: {status}\nResponse: {resp_text[:500]}")

            resp_text = resp_body.decode('utf-8', errors='replace')
            print(f"[MOQUERY] {name} 响应长度: {len(resp_text)} 字符")

            # 解析响应
            data = json.loads(resp_text)
            break
        except Exception as e:
            last_exc = e
            # 会话过期/互踢（401）：重新登录后重试一次，不消耗瞬时重试额度
            if not relogin_done and _is_session_expired(e):
                relogin_done = True
                print(f"[RETRY] {name} 会话过期/互踢(401)，重新登录后重试")
                try:
                    _auth = login()
                    cookie, forgery_token = _auth["cookie"], _auth["forgery_token"]
                except Exception:
                    pass
                continue
            if attempt >= MOQUERY_RETRY_MAX or not _is_transient_failure(e):
                raise
            attempt += 1
            if retries_log is not None:
                retries_log[name] = retries_log.get(name, 0) + 1
            print(f"[RETRY] {name} moquery 瞬时失败（{str(e)[:150]}），"
                  f"1s 后重试 ({retries_log.get(name, 0) if retries_log else 1}/{MOQUERY_RETRY_MAX})")
            time.sleep(1.0)
    if data is None:
        raise last_exc

    result = data.get("result", [])
    if not result:
        print(f"[MOQUERY] {name} result 为空，响应键: {list(data.keys())}")
        print(f"[MOQUERY] {name} 完整响应: {resp_text[:1000]}")
        return pd.DataFrame(columns=OUTPUT_HEADERS)

    # 保存原始数据到 raw_data 目录（Excel 格式，每个 MOC 一个 sheet）
    # 文件名用 moquery_ 前缀，process_excel_files 会跳过这些文件（已由 execute_moquery 处理）
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    raw_xlsx_path = os.path.join(RAW_DATA_DIR, f"moquery_{name}.xlsx")
    raw_writer = pd.ExcelWriter(raw_xlsx_path, engine='openpyxl')

    print(f"[MOQUERY] {name} result 包含 {len(result)} 个 MOC")
    all_dfs = []

    for moc_info in result:
        moc = moc_info.get("moc", "")
        attr_names = moc_info.get("attrNames", [])
        print(f"[MOQUERY] {name} MOC: {moc}, attrNames: {len(attr_names)} 个")

        # 查找 MO 实例数据（多种可能的字段名）
        mo_instances = None
        for key in ["moInstances", "data", "mos", "instances", "moList", "values"]:
            if key in moc_info and isinstance(moc_info[key], list):
                mo_instances = moc_info[key]
                print(f"[MOQUERY] {name} MO 实例在 '{key}' 字段, 共 {len(mo_instances)} 条")
                break

        if mo_instances is None:
            # 检查是否有除 moc/attrNames 之外的键
            other_keys = [k for k in moc_info.keys() if k not in ("moc", "attrNames", "mocDescription")]
            if other_keys:
                print(f"[MOQUERY] {name} 其他字段: {other_keys[:10]}")
                for key in other_keys:
                    val = moc_info[key]
                    if isinstance(val, list) and val and isinstance(val[0], dict):
                        mo_instances = val
                        print(f"[MOQUERY] {name} MO 实例在 '{key}' 字段, 共 {len(mo_instances)} 条")
                        break

        if not mo_instances:
            print(f"[MOQUERY] {name} 未找到 MO 实例数据，moc_info 键: {list(moc_info.keys())}")
            continue

        # 转换为 DataFrame
        # values 可能是 list of lists（按 attrNames 顺序），需要映射为 dict
        if mo_instances and isinstance(mo_instances[0], list):
            print(f"[MOQUERY] {name} values 为 list-of-lists 格式, 用 attrNames 映射")
            # 每个 inner list 的值按 attrNames 顺序对应
            mo_dicts = []
            for row in mo_instances:
                if len(row) == len(attr_names):
                    mo_dicts.append(dict(zip(attr_names, row)))
                else:
                    # 长度不匹配，用索引作为 key
                    mo_dicts.append({f"col_{i}": v for i, v in enumerate(row)})
            df = pd.DataFrame(mo_dicts)
        else:
            df = pd.DataFrame(mo_instances)
        print(f"[MOQUERY] {name} DataFrame: {len(df)} 行, 列: {list(df.columns)[:15]}")

        # 保存原始数据到 Excel（每个 MOC 一个 sheet）
        sheet_name = moc.split("/")[-1] if "/" in moc else moc
        if len(sheet_name) > 31:
            sheet_name = sheet_name[:31]
        try:
            df.to_excel(raw_writer, sheet_name=sheet_name, index=False)
        except Exception as e:
            print(f"[MOQUERY] {name} 保存 sheet '{sheet_name}' 失败: {e}")

        # 确定 Tech（根据 MOC 名称）
        moc_lower = moc.lower()
        if "ggsmcell" in moc_lower:
            tech_name = "GGsmCell"
        elif "uutrancellfdd" in moc_lower:
            tech_name = "UUtranCellFDD"
        elif "eutrancellfdd" in moc_lower:
            tech_name = "EUtranCellFDD"
        elif "nrcellcu" in moc_lower:
            tech_name = "NRCellCU"
        else:
            tech_name = moc.split("/")[-1] if "/" in moc else moc

        # 按 DEDUP_KEYS 去重
        dedup_cols = [c for c in DEDUP_KEYS if c in df.columns]
        if dedup_cols:
            before = len(df)
            df = df.drop_duplicates(subset=dedup_cols, keep="first").reset_index(drop=True)
            removed = before - len(df)
            if removed > 0:
                print(f"[MOQUERY] {name} 去重({','.join(dedup_cols)}): 删除 {removed} 行, 剩余 {len(df)} 行")

        # 向量化提取字段（moquery 专用：Site_ID/Site_Name 从 moDescription/userLabel 提取）
        site_id = _extract_moquery_site_id(df)
        site_name = _extract_moquery_site_name(df)
        cell_id = _extract_first_available(df, CELL_ID_FIELDS)
        cell_name = _extract_first_available(df, CELL_NAME_FIELDS)

        result_df = pd.DataFrame({
            "Site_ID": site_id, "Site_Name": site_name,
            "Cell_ID": cell_id, "Cell_Name": cell_name, "Tech": tech_name,
        })

        # 打印提取样本便于调试
        if len(result_df) > 0:
            print(f"    [EXTRACT] Site_ID 样本: {result_df['Site_ID'].dropna().head(3).tolist()}")
            print(f"    [EXTRACT] Site_Name 样本: {result_df['Site_Name'].dropna().head(3).tolist()}")

        # 过滤无效行
        cell_id_str = result_df["Cell_ID"].astype(str).str.strip()
        mask = result_df["Cell_ID"].notna() & cell_id_str.str.match(r'^\d+(\.\d+)?$', na=False)
        removed = len(result_df) - mask.sum()
        if removed > 0:
            filtered_vals = cell_id_str[~mask][:5].tolist()
            print(f"[MOQUERY] {name} 过滤无效行: {removed} 行, 样本: {filtered_vals}")
        result_df = result_df[mask].reset_index(drop=True)
        result_df["Cell_ID"] = result_df["Cell_ID"].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        print(f"[MOQUERY] {name} 提取有效行: {len(result_df)}")

        all_dfs.append(result_df)

    # 关闭 ExcelWriter，保存原始数据文件
    try:
        raw_writer.close()
        print(f"[MOQUERY] {name} 原始数据已保存: {os.path.basename(raw_xlsx_path)}")
    except Exception as e:
        print(f"[MOQUERY] {name} 保存原始数据失败: {e}")

    if not all_dfs:
        print(f"[MOQUERY] {name} 无有效数据")
        return pd.DataFrame(columns=OUTPUT_HEADERS)

    merged = pd.concat(all_dfs, ignore_index=True)
    for col in OUTPUT_HEADERS:
        if col in merged.columns:
            merged[col] = merged[col].fillna("").astype(str)
    print(f"[MOQUERY] {name} 合并后: {len(merged)} 行")
    return merged


# ============================================================
# 轮询任务状态
# ============================================================
def _normalize_status_data(data):
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, list) and inner and isinstance(inner[0], dict):
            merged = dict(data)
            merged.update(inner[0])
            return merged
        if isinstance(inner, dict):
            merged = dict(data)
            merged.update(inner)
            return merged
        return data
    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            return data[0]
        return {}
    return {}


def poll_task_status(cookie, forgery_token, task_no, name="", timeout=600, interval=5):
    """轮询任务状态，返回 (fileName, download_forgerydefense)。"""
    print(f"\n[POLL] {name} 轮询状态 (timeout={timeout}s)...")
    path = f"{STATUS_PATH}?taskNo={task_no}"
    headers = _auth_headers(cookie, forgery_token)

    deadline = time.time() + timeout
    last_progress = -1

    while time.time() < deadline:
        status, hdrs, raw_hdrs, resp_body = _http_request("GET", path, headers_extra=headers)
        resp_text = resp_body.decode('utf-8', errors='replace')

        try:
            raw = json.loads(resp_text)
        except json.JSONDecodeError:
            time.sleep(interval)
            continue

        data = _normalize_status_data(raw)
        progress = data.get("progress", data.get("progressRate", 0))
        task_status = data.get("taskStatus", data.get("status", data.get("state", "")))

        if progress != last_progress:
            print(f"[POLL] {name} Progress: {progress}%, Status: {task_status}")
            last_progress = progress

        is_done = (
            (isinstance(progress, (int, float)) and progress >= 100)
            or task_status in [1, 2, "1", "2", "success", "complete", "completed", "完成"]
            or data.get("finishFlag") == 1
            or data.get("isFinish") == 1
        )

        if is_done:
            print(f"[POLL] {name} 任务完成")
            return _extract_download_info(resp_text, data, forgery_token)

        time.sleep(interval)

    raise Exception(f"任务轮询超时 [{name}] ({timeout}s)")


def _extract_download_info(resp_text, data, default_forgery):
    file_name = None
    download_forgery = default_forgery

    for key in ["fileName", "filepath", "filePath", "file"]:
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            file_name = val.strip()
            break

    if not file_name and isinstance(data.get("data"), dict):
        d = data["data"]
        for key in ["fileName", "filepath", "filePath", "file"]:
            val = d.get(key)
            if isinstance(val, str) and val.strip():
                file_name = val.strip()
                break
        download_forgery = d.get("forgerydefense", download_forgery)

    if not file_name:
        match = re.search(r'(/cmdata/temp/plan/[^\s"\'&]+\.xlsx)', resp_text)
        if not match:
            match = re.search(r'(/cmdata/temp/plan/[^\s"\'&]+\.zip)', resp_text)
        if match:
            file_name = match.group(1)

    if file_name:
        match = re.search(r'forgerydefense["\s:=]+([a-f0-9]{64})', resp_text)
        if match:
            download_forgery = match.group(1)

    if not file_name:
        print(f"[POLL] 完整响应: {resp_text}")
        # 具体原因：带上状态响应（可能是导出失败/空结果/格式变化），便于 UI 定位
        raise Exception(f"任务完成但未获取到 fileName，状态响应: {resp_text[:500]}")

    print(f"[POLL] FileName: {file_name}")
    return file_name, download_forgery


# ============================================================
# 下载文件
# ============================================================
def download_file(cookie, forgery_token, file_name, download_forgery, name=""):
    print(f"\n[DOWNLOAD] {name} 下载: {file_name}")
    encoded_name = urllib.parse.quote(file_name, safe='/')
    path = f"{DOWNLOAD_PATH}?fileName={encoded_name}&forgerydefense={download_forgery}"
    headers = _auth_headers(cookie, forgery_token, extra={
        "Accept": "application/zip, application/octet-stream, */*",
        "Accept-Encoding": "identity",
    })

    status, hdrs, raw_hdrs, resp_body = _http_request("GET", path, headers_extra=headers)
    print(f"[DOWNLOAD] {name} Status: {status}")

    if "200" not in status:
        raise Exception(f"下载失败 [{name}]: {status}")

    print(f"[DOWNLOAD] {name} 文件大小: {len(resp_body)} bytes ({len(resp_body)/1024:.1f} KB)")
    return resp_body


# ============================================================
# 文件处理
# ============================================================
def get_unique_path(base_path):
    if not os.path.exists(base_path):
        return base_path
    name, ext = os.path.splitext(base_path)
    seq = 1
    while True:
        new_path = f"{name}_{seq}{ext}"
        if not os.path.exists(new_path):
            return new_path
        seq += 1


def save_downloaded(file_bytes, save_dir, flow_name, index, file_name=""):
    """保存下载的文件（xlsx 或 zip），返回保存路径列表。

    注意：xlsx 文件本身也是 ZIP 格式（以 PK 开头），需要通过 file_name 扩展名
    或 ZIP 内容来判断是 xlsx 还是包含 xlsx 的 ZIP 包。

    关键：即使 file_name 不为空，如果扩展名不是 .xlsx，也必须检查 ZIP 内容，
    因为 xlsx 文件的内部结构（[Content_Types].xml, xl/ 等）会被误判为 ZIP 包内容。
    """
    saved_paths = []

    # 优先通过 file_name 扩展名判断
    is_xlsx = bool(file_name) and file_name.lower().endswith('.xlsx')

    # 如果 file_name 不是 .xlsx，通过 ZIP 内容判断（不论 file_name 是否为空）
    if not is_xlsx and file_bytes[:2] == b'PK':
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                names = zf.namelist()
                # xlsx 文件内部包含 [Content_Types].xml 和 xl/ 目录
                is_xlsx = '[Content_Types].xml' in names or any(n.startswith('xl/') for n in names)
                if not is_xlsx:
                    # 检查是否是包含 xlsx 的 ZIP 包
                    has_xlsx = any(n.endswith('.xlsx') for n in names)
                    if has_xlsx:
                        # ZIP 包（内含 xlsx 文件），解压
                        zip_name = f"{flow_name}_{index}.zip"
                        zip_path = os.path.join(save_dir, zip_name)
                        with open(zip_path, 'wb') as f:
                            f.write(file_bytes)
                        print(f"[SAVE] {flow_name} ZIP (含xlsx): {zip_name}")
                        with zipfile.ZipFile(zip_path) as zf:
                            zf.extractall(save_dir)
                            for name in zf.namelist():
                                if name.endswith('.xlsx'):
                                    # 重命名为统一格式 {flow_name}_{index}.xlsx
                                    old_path = os.path.join(save_dir, name)
                                    new_path = os.path.join(save_dir, f"{flow_name}_{index}.xlsx")
                                    if os.path.exists(new_path):
                                        os.remove(new_path)
                                    os.rename(old_path, new_path)
                                    saved_paths.append(new_path)
                                elif name.endswith('.csv'):
                                    # result_*.csv 是错误信息文件，不是数据文件，删除
                                    csv_path = os.path.join(save_dir, name)
                                    if os.path.exists(csv_path):
                                        os.remove(csv_path)
                        os.remove(zip_path)
                        return saved_paths
        except zipfile.BadZipFile:
            is_xlsx = False

    # 直接是 xlsx 文件，保存为单个文件
    xlsx_name = f"{flow_name}_{index}.xlsx"
    xlsx_path = os.path.join(save_dir, xlsx_name)
    with open(xlsx_path, 'wb') as f:
        f.write(file_bytes)
    print(f"[SAVE] {flow_name} XLSX: {xlsx_name}")
    saved_paths.append(xlsx_path)
    return saved_paths


def _match_target_sheet(sheet_name):
    if sheet_name in TARGET_SHEETS:
        return sheet_name
    lower = sheet_name.lower()
    for target in TARGET_SHEETS:
        if target.lower() in lower:
            return target
    return None


def _extract_first_available(df, fields):
    result = pd.Series(dtype=str, index=df.index)
    for field in fields:
        if field in df.columns:
            col = df[field]
            mask = result.isna() | (result.astype(str).str.strip() == "")
            result = result.astype(str)
            col_str = col.astype(str).where(col.notna(), "")
            result[mask] = col_str[mask]
    result = result.replace("", pd.NA)
    return result


# moquery 专用：从 moDescription / ldn 中向量化提取 Site_ID
# GSM moDescription: "userLabel=New Hope Comm-S4,LAC=13,CI=18344,BtsId=4,SiteId=1834,..."
# GSM ldn: "GBssFunction=1,GBtsSiteManager=1834,GGsmCell=4"
# UMTS moDescription: "CID=38442,userLabel=Webo-S2,RncId=105" (无 SiteId，需用 CID//10 推导)
SITE_ID_PATTERNS = [
    r"SiteId=(\d+)",          # GSM moDescription
    r"GBtsSiteManager=(\d+)",  # GSM ldn
    r"Site=(\d+)",             # 通用
    r"SiteId\s*=\s*(\d+)",     # 带空格
]


def _extract_moquery_site_id(df):
    """从 moDescription / ldn 列中向量化提取 Site_ID。

    优先级：moDescription 中的 SiteId > ldn 中的 GBtsSiteManager > 其他模式
    若都未匹配，返回全 NA（不使用 ManagedElement，因为它只是序号/RNC ID）。
    """
    result = pd.Series(pd.NA, index=df.index, dtype=str)

    for col_name in ["moDescription", "ldn"]:
        col = None
        for c in df.columns:
            if str(c).strip() == col_name:
                col = df[c]
                break
        if col is None:
            continue

        col_str = col.astype(str).where(col.notna(), "")
        for pattern in SITE_ID_PATTERNS:
            mask = result.isna()
            if not mask.any():
                break
            extracted = col_str[mask].str.extract(pattern, expand=False)
            # 只更新成功匹配的位置
            valid = extracted.notna()
            if valid.any():
                idx = result.index[mask][valid.values]
                result.loc[idx] = extracted[valid].values

    # 回退：UMTS 的 moDescription 无 SiteId 字段，Site_ID = CID // 10（站址号*10+扇区号惯例）。
    # 已用原始数据验证：CID 末位 == userLabel 扇区号占 97.67%（不匹配为扇区号>9 的多扇区站）；
    # GSM 亦满足 SiteId == CI//10（100%），故该推导对两制式均安全。
    mask = result.isna()
    if mask.any():
        cid_str = None
        # 优先用 cId 列（UMTS moquery 自带）
        for c in df.columns:
            if str(c).strip() == "cId":
                cid_str = df[c].astype(str).str.strip().where(df[c].notna(), "")
                break
        # 其次从 moDescription 中提取 CID=xxx
        if cid_str is None:
            for c in df.columns:
                if str(c).strip() == "moDescription":
                    mo_str = df[c].astype(str).where(df[c].notna(), "")
                    cid_str = mo_str.str.extract(r"CID=(\d+)", expand=False).fillna("")
                    break
        if cid_str is not None:
            # 去掉末位扇区号得到站址号（向量化）
            extracted = cid_str[mask].str.extract(r"^(\d+)\d$", expand=False)
            valid = extracted.notna()
            if valid.any():
                idx = result.index[mask][valid.values]
                result.loc[idx] = extracted[valid].values
                print(f"[MOQUERY] Site_ID CID//10 回退推导: {int(valid.sum())} 行")

    return result


def _extract_moquery_site_name(df):
    """从 userLabel 列中向量化提取 Site_Name。

    userLabel 格式: "<SiteName>-S<sector>" (如 "New Hope Comm-S4", "Webo-S2")
    Site_Name = 最后一个 "-S<digit>" 之前的部分

    若不匹配 -S<digit> 模式，回退到 userLabel 全值。
    若 userLabel 也缺失，回退到 moDescription 中的 userLabel=xxx。
    """
    result = pd.Series(pd.NA, index=df.index, dtype=str)

    # 1. 优先从 userLabel 列提取
    for col_name in ["userLabel"]:
        col = None
        for c in df.columns:
            if str(c).strip() == col_name:
                col = df[c]
                break
        if col is None:
            continue

        col_str = col.astype(str).where(col.notna(), "")
        # 匹配 -S<digit> 结尾，取之前部分
        extracted = col_str.str.replace(r"-S\d+$", "", regex=True)
        # 空字符串转为 NA
        extracted = extracted.where(extracted.str.strip() != "", pd.NA)
        mask = result.isna() & extracted.notna()
        if mask.any():
            result.loc[mask] = extracted[mask]

    # 2. 回退：从 moDescription 中提取 userLabel=xxx
    for col_name in ["moDescription"]:
        col = None
        for c in df.columns:
            if str(c).strip() == col_name:
                col = df[c]
                break
        if col is None:
            continue

        mask = result.isna()
        if not mask.any():
            continue
        col_str = col.astype(str).where(col.notna(), "")
        # 提取 userLabel=xxx 中的 xxx
        extracted = col_str[mask].str.extract(r"userLabel=([^,]+)", expand=False)
        # 去掉 -S<digit> 后缀
        extracted = extracted.str.replace(r"-S\d+$", "", regex=True)
        valid = extracted.notna() & (extracted.str.strip() != "")
        if valid.any():
            idx = result.index[mask][valid.values]
            result.loc[idx] = extracted[valid].values

    return result


def _ensure_site_columns(df):
    """如果 DataFrame 缺少 ManagedElement 列，从 moId 中向量化提取。

    moId 格式: SubNetwork=X,ManagedElement=Y/Function/MOC-Id
    ManagedElement = 第一个 / 之前的部分（如 SubNetwork=1,ManagedElement=1）

    注意：不自动创建 NE_Name 回退。NE_Name 由 _extract_first_available 通过
    SITE_NAME_FIELDS = ["NE_Name", "moDescription", "ManagedElement"] 自然回退。
    """
    # 查找 moId 列（可能带空格或大小写不同）
    moId_col = None
    for c in df.columns:
        if str(c).strip().lower() == "moid":
            moId_col = c
            break

    # 判断 ManagedElement 是否需要从 moId 提取
    me_col = None
    for c in df.columns:
        if str(c).strip() == "ManagedElement":
            me_col = c
            break
    me_need_extract = me_col is None or df[me_col].isna().all()

    if me_need_extract and moId_col is not None:
        moId_str = df[moId_col].astype(str)
        df["ManagedElement"] = moId_str.str.split("/").str[0]
        print(f"    [ENSURE] 从 moId 提取 ManagedElement, 样本: {df['ManagedElement'].head(3).tolist()}")

    return df


def process_excel_files(save_dir):
    """处理所有 Excel 文件，返回合并后的 DataFrame。"""
    print("\n" + "=" * 70)
    print("[PROCESS] 处理数据文件")
    print("=" * 70)

    all_dfs = []
    found_sheets = set()

    data_files = []
    for root, _dirs, files in os.walk(save_dir):
        for f in files:
            if f.startswith("~$"):
                continue
            # 跳过 moquery 原始数据文件（已由 execute_moquery 处理）
            if f.startswith("moquery_"):
                continue
            # 跳过 result_*.csv（错误信息文件，非数据文件）
            if f.startswith("result_") and f.endswith(".csv"):
                continue
            if f.lower().endswith((".xlsx", ".xlsm", ".xls", ".csv")):
                data_files.append(os.path.join(root, f))

    if not data_files:
        print("[PROCESS] 未找到数据文件")
        return pd.DataFrame(columns=OUTPUT_HEADERS)

    print(f"[PROCESS] 找到 {len(data_files)} 个数据文件")

    for file_path in data_files:
        print(f"\n[PROCESS] 处理: {os.path.basename(file_path)}")
        try:
            if file_path.lower().endswith(".csv"):
                df_all = pd.read_csv(file_path, dtype=str, low_memory=False)
                matched = _match_target_sheet(os.path.basename(file_path).split(".")[0])
                sheets = {matched: df_all} if matched else {}
            else:
                xls = pd.ExcelFile(file_path)
                print(f"  所有 sheet: {list(xls.sheet_names)}")
                sheets = {}
                for sn in xls.sheet_names:
                    matched = _match_target_sheet(sn)
                    if matched:
                        sheets[matched] = pd.read_excel(xls, sheet_name=sn, dtype=str)
                        found_sheets.add(matched)
                        print(f"  [MATCH] '{sn}' -> '{matched}'")
        except Exception as e:
            print(f"  [ERROR] 读取失败: {e}")
            continue

        for tech_name, df in sheets.items():
            if df.empty:
                print(f"  [SHEET] {tech_name}: 空表，跳过")
                continue
            print(f"  [SHEET] {tech_name}: {len(df)} 行, {len(df.columns)} 列")
            print(f"    列名: {list(df.columns)[:20]}")

            # 按 DEDUP_KEYS 去重
            dedup_cols = [c for c in DEDUP_KEYS if c in df.columns]
            if dedup_cols:
                before = len(df)
                df = df.drop_duplicates(subset=dedup_cols, keep="first").reset_index(drop=True)
                removed = before - len(df)
                if removed > 0:
                    print(f"    去重({','.join(dedup_cols)}): 删除 {removed} 行, 剩余 {len(df)} 行")

            # 向量化提取字段
            df = _ensure_site_columns(df)
            site_id = _extract_first_available(df, SITE_ID_FIELDS)
            site_name = _extract_first_available(df, SITE_NAME_FIELDS)
            cell_id = _extract_first_available(df, CELL_ID_FIELDS)
            cell_name = _extract_first_available(df, CELL_NAME_FIELDS)

            result = pd.DataFrame({
                "Site_ID": site_id, "Site_Name": site_name,
                "Cell_ID": cell_id, "Cell_Name": cell_name, "Tech": tech_name,
            })

            # 过滤无效行：Cell_ID 必须为数字（含浮点格式）
            cell_id_str = result["Cell_ID"].astype(str).str.strip()
            mask = result["Cell_ID"].notna() & cell_id_str.str.match(r'^\d+(\.\d+)?$', na=False)
            removed = len(result) - mask.sum()
            if removed > 0:
                filtered_vals = cell_id_str[~mask][:5].tolist()
                print(f"    过滤无效行: {removed} 行, 样本: {filtered_vals}")
            result = result[mask].reset_index(drop=True)
            result["Cell_ID"] = result["Cell_ID"].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            print(f"    提取有效行: {len(result)}")
            if len(result) > 0:
                print(f"    Cell_ID 样本: {result['Cell_ID'].head(5).tolist()}")

            all_dfs.append(result)

    if not all_dfs:
        missing = [s for s in TARGET_SHEETS if s not in found_sheets]
        if missing:
            print(f"\n[PROCESS] 未找到的 sheet: {missing}")
        return pd.DataFrame(columns=OUTPUT_HEADERS)

    missing = [s for s in TARGET_SHEETS if s not in found_sheets]
    if missing:
        print(f"\n[PROCESS] 未找到的 sheet: {missing}")

    merged = pd.concat(all_dfs, ignore_index=True)
    for col in OUTPUT_HEADERS:
        if col in merged.columns:
            merged[col] = merged[col].fillna("").astype(str)

    # 跨文件去重
    before = len(merged)
    merged = merged.drop_duplicates(subset=OUTPUT_HEADERS, keep="first").reset_index(drop=True)
    removed = before - len(merged)
    if removed > 0:
        print(f"[PROCESS] 跨文件去重: 删除 {removed} 行")

    print(f"\n[PROCESS] 总计提取 {len(merged)} 行")
    return merged


# ============================================================
# 汇总表 + 输出
# ============================================================
def _enrich_summary_from_master(summary_df):
    """从主库 master_site_db 按站点名（不区分大小写，回退 Site_ID）向量化补全
    region / province_county / site_caregory 三列。

    master_site_db 缺失或不可用时三列置空，不影响主流程（独立运行场景兼容）。
    """
    for c in MASTER_ATTR_COLS:
        summary_df[c] = ""
    if summary_df.empty:
        return summary_df
    try:
        from backend.database import engine
        ms = pd.read_sql(
            "SELECT site_id, site_name, region, province_county, site_caregory "
            "FROM master_site_db", engine, dtype=str)
    except Exception as e:
        print(f"[MASTER] master_site_db 不可用，跳过区域/类别补全: {e}")
        return summary_df
    ms = ms.fillna("").astype(str).apply(lambda s: s.str.strip())
    if ms.empty:
        return summary_df
    # 双键索引：站点名（小写）优先，Site_ID 回退；各键去重保首条
    name_ref = ms.assign(_k=ms["site_name"].str.lower())
    name_ref = name_ref[name_ref["_k"] != ""].drop_duplicates("_k").set_index("_k")
    id_ref = ms.assign(_k=ms["site_id"])
    id_ref = id_ref[id_ref["_k"] != ""].drop_duplicates("_k").set_index("_k")
    k_name = summary_df["Site_Name"].astype(str).str.strip().str.lower()
    k_id = summary_df["Site_ID"].astype(str).str.strip()
    for c in MASTER_ATTR_COLS:
        v = k_name.map(name_ref[c])
        miss = v.isna() | (v == "")
        if miss.any():
            v = v.where(~miss, k_id.map(id_ref[c]))
        summary_df[c] = v.fillna("")
    matched = (summary_df[MASTER_ATTR_COLS] != "").any(axis=1)
    print(f"[MASTER] master_site_db 补全命中: {int(matched.sum())}/{len(summary_df)} 站")
    return summary_df


def build_summary_df(merged_df):
    if merged_df.empty:
        return pd.DataFrame(columns=SUMMARY_HEADERS)
    df = merged_df.copy()
    df["Tech"] = df["Tech"].map(TECH_MAPPING).fillna(df["Tech"])
    unique_cells = df.drop_duplicates(subset=["Site_ID", "Site_Name", "Cell_ID", "Tech"])
    summary = (
        unique_cells
        .groupby(["Site_ID", "Site_Name", "Tech"], as_index=False)
        .size()
        .rename(columns={"size": "NumberOfCells"})
    )
    summary = summary[SUMMARY_BASE_HEADERS]
    summary["NumberOfCells"] = summary["NumberOfCells"].astype(int)
    summary = summary.sort_values(["Site_ID", "Site_Name", "Tech"]).reset_index(drop=True)
    return _enrich_summary_from_master(summary)


def _auto_column_width(ws):
    for col_cells in ws.columns:
        max_length = 0
        col_letter = col_cells[0].column_letter
        for cell in col_cells:
            try:
                val_len = len(str(cell.value)) if cell.value else 0
                if val_len > max_length:
                    max_length = val_len
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_length + 2, 50)


def cleanup_old_outputs(current_path):
    pattern = os.path.join(OUTPUT_DIR, "cm_cell_data_*.xlsx")
    old_files = [f for f in glob.glob(pattern)
                 if os.path.abspath(f) != os.path.abspath(current_path)
                 and not os.path.basename(f).startswith("~$")]
    if not old_files:
        return
    print(f"\n[CLEANUP] 删除旧输出文件 ({len(old_files)} 个):")
    for f in old_files:
        try:
            os.remove(f)
            print(f"  - 已删除: {os.path.basename(f)}")
        except Exception as e:
            print(f"  - 删除失败: {os.path.basename(f)}: {e}")


def cleanup_raw_data():
    """清理 raw_data 目录中的旧文件和目录，只保留最新一次的原始数据。"""
    if not os.path.exists(RAW_DATA_DIR):
        return
    old_items = []
    for f in os.listdir(RAW_DATA_DIR):
        if f.startswith("~$"):
            continue
        old_items.append(os.path.join(RAW_DATA_DIR, f))
    if not old_items:
        return
    print(f"\n[CLEANUP] 清理旧原始数据 ({len(old_items)} 个):")
    for f in old_items:
        try:
            if os.path.isdir(f):
                shutil.rmtree(f)
            else:
                os.remove(f)
            print(f"  - 已删除: {os.path.basename(f)}")
        except Exception as e:
            print(f"  - 删除失败: {os.path.basename(f)}: {e}")


def generate_output(merged_df):
    if merged_df.empty:
        print("\n[OUTPUT] 无数据可输出")
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    output_name = f"cm_cell_data_{timestamp}.xlsx"
    output_path = get_unique_path(os.path.join(OUTPUT_DIR, output_name))

    print(f"\n[OUTPUT] 生成输出文件: {os.path.basename(output_path)}")

    summary_df = build_summary_df(merged_df)
    print(f"[OUTPUT] Site_Summary 行数: {len(summary_df)}")

    # 按制式统计
    tech_summary = (
        summary_df.groupby("Tech", as_index=False)
        .agg(Total_Sites=("Site_Name", "count"), Total_Cells=("NumberOfCells", "sum"))
        .sort_values("Tech")
        .reset_index(drop=True)
    )
    print(f"[OUTPUT] Tech_Summary 行数: {len(tech_summary)}")

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        merged_df.to_excel(writer, sheet_name="Cell_Data", index=False)
        _auto_column_width(writer.sheets["Cell_Data"])
        summary_df.to_excel(writer, sheet_name="Site_Summary", index=False)
        _auto_column_width(writer.sheets["Site_Summary"])
        tech_summary.to_excel(writer, sheet_name="Tech_Summary", index=False)
        _auto_column_width(writer.sheets["Tech_Summary"])

    print(f"[OUTPUT] 已保存: {output_path}")
    print(f"[OUTPUT] Cell_Data 行数: {len(merged_df)}")
    print(f"[OUTPUT] Site_Summary 行数: {len(summary_df)}")

    print("[OUTPUT] 按制式统计:")
    for _, row in tech_summary.iterrows():
        print(f"  - {row['Tech']}: {row['Total_Sites']} 站, {row['Total_Cells']} 小区")

    cleanup_old_outputs(output_path)
    return output_path


# ============================================================
# 数据库写入（API 直写远程，失败回退本地 SQLite；同时写主库供 Table Browser 展示）
# ============================================================
def _write_app_db(merged_df, summary_df):
    """同写 my_app 主库，供 Table Browser / 数据总览页展示。

    通过 backend.database.engine 写入，跟随 DB_MODE 熔断开关：
    pg 模式写 PostgreSQL 的 app schema，sqlite 模式写 db/app.db。
    全量替换（快照语义）。独立运行场景 backend 不可用时静默跳过，不影响主流程。
    """
    try:
        from backend.database import engine
    except Exception as e:
        print(f"[DB][APP] backend.database 不可用 ({e})，跳过主库写入")
        return
    merged_df.to_sql(CELL_TABLE, engine, if_exists="replace", index=False)
    summary_df.to_sql(SUMMARY_TABLE, engine, if_exists="replace", index=False)
    print(f"[DB][APP] 已写入主库（Table Browser 可见）: "
          f"{CELL_TABLE} {len(merged_df)} 行 / {SUMMARY_TABLE} {len(summary_df)} 行")


def _write_local_sqlite(merged_df, summary_df):
    """远程写入失败时的本地回退：全量替换写入本地 SQLite（DROP+CREATE，快照语义）"""
    import sqlite3
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=60)
    try:
        merged_df.to_sql(CELL_TABLE, conn, if_exists="replace", index=False)
        summary_df.to_sql(SUMMARY_TABLE, conn, if_exists="replace", index=False)
        conn.commit()
    finally:
        conn.close()
    print(f"[DB][LOCAL] 已回退写入本地 SQLite: {LOCAL_DB_PATH}")


def write_to_database(merged_df):
    """将 CM 数据写入数据库：API 直写远程 db.sqlite3（full_replace 全量快照替换），
    失败时回退本地 SQLite 副本。返回失败信息列表（空列表 = 全部成功）。"""
    summary_df = build_summary_df(merged_df)
    datasets = [
        (CELL_TABLE, merged_df, list(OUTPUT_HEADERS)),
        (SUMMARY_TABLE, summary_df, list(SUMMARY_HEADERS)),
    ]
    api_errors = []
    if _db_writer is None:
        api_errors.append("db_writer_client 不可用")
    else:
        for table, df, cols in datasets:
            try:
                # 向量化转字符串，避免 None/NaN 进入 API
                rows = df[cols].fillna("").astype(str).values.tolist()
                res = _db_writer.write_data(
                    db=REMOTE_DB_NAME, table=table, columns=cols,
                    rows=rows, mode="full_replace",
                )
                rows_written = res.get("rows_written", 0)
                if rows_written == 0 and len(df) > 0:
                    raise Exception(f"API 返回 0 行写入: {table}")
                print(f"[DB][API] {table}: 写入 {rows_written} 行 (full_replace)")
            except Exception as e:
                print(f"[DB][API] {table} 写入失败: {e}")
                api_errors.append(f"{table}: {e}")
                break  # 任一表失败则本次整体回退本地，保证两表快照一致
    # 同写主库（跟随 DB_MODE：PG app schema 或 db/app.db）：供 Table Browser / 数据总览展示，与远程写入相互独立
    try:
        _write_app_db(merged_df, summary_df)
    except Exception as e:
        print(f"[DB][APP] 主库写入失败: {e}")
        api_errors.append(f"主库: {e}")
    if api_errors:
        _write_local_sqlite(merged_df, summary_df)
    return api_errors


# ============================================================
# 流程/网元配置管理（Settings「任务配置」页签，2026-08-15）
# 页面编辑网元清单/导入导出 → 写 cm_flows.json（结构化，解析优先）；
# new_url.txt 保留为遗留来源（未编辑过时仍生效）。
# ============================================================
_NE_PATTERN = re.compile(r'^SubNetwork=\d+,ManagedElement=\d+$')


def _normalize_flow_payload(flow: dict) -> dict:
    """规范化流程 payload，防外部工具（如 PowerShell JSON 往返）把数组写成空格字符串。

    - excelDesc.sheetDescList[].attrNames: str("moId userLabel ...") → ["moId", "userLabel", ...]
    - neList: 确保是字符串列表
    """
    payload = flow.get("payload")
    if not isinstance(payload, dict):
        return flow
    excel_desc = payload.get("excelDesc")
    if isinstance(excel_desc, dict):
        for sheet in excel_desc.get("sheetDescList") or []:
            if isinstance(sheet, dict):
                an = sheet.get("attrNames")
                if isinstance(an, str) and an.strip():
                    sheet["attrNames"] = [x for x in an.split() if x]
    ne_list = payload.get("neList")
    if isinstance(ne_list, str):
        payload["neList"] = [x for x in ne_list.split(",") if x.strip()]
    elif isinstance(ne_list, list):
        payload["neList"] = [x for x in ne_list if isinstance(x, str)]
    return flow


def _load_structured_flows():
    """读 cm_flows.json（页面编辑产物）；不存在/损坏返回 None（回退 new_url.txt）。"""
    if not os.path.exists(CM_FLOWS_PATH):
        return None
    try:
        with open(CM_FLOWS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        flows = data.get("flows") if isinstance(data, dict) else None
        if isinstance(flows, list):
            return [_normalize_flow_payload(f) for f in flows if isinstance(f, dict)]
    except Exception as e:
        print(f"[FLOWS] 读取 cm_flows.json 失败，回退 new_url.txt: {e}")
    return None


def _write_cm_flows_json(flows):
    """原子写 cm_flows.json（临时文件 + os.replace，避免半写损坏）。"""
    data = {"version": 1, "source": "cm_flows.json (Settings 任务配置页签编辑产物)", "flows": flows}
    tmp = CM_FLOWS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CM_FLOWS_PATH)


def _ensure_cm_flows_json():
    """首次编辑前：把当前生效流程（new_url.txt 解析结果）落成 cm_flows.json。"""
    if _load_structured_flows() is not None:
        return
    flows = parse_new_url_txt()
    _write_cm_flows_json(flows)
    print(f"[FLOWS] 已从 new_url.txt 生成 cm_flows.json（{len(flows)} 个流程），后续编辑以此为准")


def get_effective_flows():
    """获取当前生效的流程：cm_flows.json（页面编辑产物）优先，否则解析 new_url.txt。"""
    structured = _load_structured_flows()
    if structured is not None:
        print(f"[FLOWS] 使用 cm_flows.json（{len(structured)} 个流程）")
        return structured
    return parse_new_url_txt()


def get_cm_flow_config() -> dict:
    """流程配置视图（供页面展示/编辑）：每流程 name/type/path/ne_count/ne_list。"""
    flows = get_effective_flows()
    out = []
    for f in flows:
        payload = f.get("payload") or {}
        ne_list = payload.get("neList") or []
        out.append({
            "name": f.get("name", ""),
            "type": f.get("type", ""),
            "path": f.get("path", ""),
            "ne_count": len(ne_list),
            "ne_list": list(ne_list),
        })
    return {"flows": out}


def update_cm_flow_ne_list(name: str, ne_list) -> dict:
    """更新指定流程的网元清单（校验格式 + 去重保序），写入 cm_flows.json。"""
    if not isinstance(ne_list, list) or not all(isinstance(x, str) for x in ne_list):
        return {"success": False, "error": "ne_list 必须是字符串数组"}
    bad = [ne for ne in ne_list if not _NE_PATTERN.match(ne.strip())]
    if bad:
        return {"success": False,
                "error": f"非法网元格式: {', '.join(bad[:5])}（应为 SubNetwork=X,ManagedElement=Y）"}
    _ensure_cm_flows_json()
    flows = _load_structured_flows()
    if flows is None:
        return {"success": False, "error": "无法加载流程配置"}
    target = next((f for f in flows if f.get("name") == name), None)
    if target is None:
        return {"success": False, "error": f"流程 {name} 不存在"}
    seen, cleaned = set(), []
    for ne in ne_list:
        ne = ne.strip()
        if ne and ne not in seen:
            seen.add(ne)
            cleaned.append(ne)
    target.setdefault("payload", {})["neList"] = cleaned
    _write_cm_flows_json(flows)
    return {"success": True, "name": name, "ne_count": len(cleaned)}


def export_cm_flow_config() -> dict:
    """导出全量流程配置（含 payload/neList，可整体导入还原）。"""
    _ensure_cm_flows_json()
    flows = _load_structured_flows() or []
    return {"version": 1, "flows": flows}


def import_cm_flow_config(flows) -> dict:
    """导入流程配置（整体替换）。逐项校验：name/path/payload 必备，neList 格式合法。"""
    if not isinstance(flows, list):
        return {"success": False, "applied": [], "errors": [{"index": "(body)", "error": "flows 必须是数组"}]}
    valid, errors = [], []
    for i, f in enumerate(flows):
        if not isinstance(f, dict) or not f.get("name") or not f.get("path"):
            errors.append({"index": i, "error": "缺少 name/path"})
            continue
        payload = f.get("payload")
        if not isinstance(payload, dict):
            errors.append({"index": i, "error": f"{f.get('name')}: payload 缺失"})
            continue
        ne_list = payload.get("neList")
        if ne_list is not None:
            if (not isinstance(ne_list, list)
                    or not all(isinstance(x, str) and _NE_PATTERN.match(x.strip()) for x in ne_list)):
                errors.append({"index": i, "error": f"{f.get('name')}: neList 含非法网元"})
                continue
        # 规范化 attrNames（防止客户端工具把数组写成空格字符串）
        valid.append(_normalize_flow_payload(f))
    if valid:
        _write_cm_flows_json(valid)
    return {"success": not errors, "applied": [f["name"] for f in valid], "errors": errors}


# ============================================================
# 数据采集 + 调度任务入口
# ============================================================
def _is_transient_failure(exc) -> bool:
    """判定失败是否瞬时（可整体重试）。确定性失败（配置/数据问题）不重试。"""
    text = str(exc)
    permanent_markers = ["code=1004", "创建任务失败", "MOC does not exist",
                         "模板", "template", "数据库写入失败"]
    return not any(m in text for m in permanent_markers)


def _is_session_expired(exc) -> bool:
    """判定是否为 UME 会话过期/互踢（401 Unauthorized），需要重新登录。"""
    text = str(exc)
    return "401" in text or "Unauthorized" in text or "hasLogged" in text


def _run_exportvermo_flow(cookie, forgery_token, flow, save_dir, idx, retries_log):
    """exportvermo 流程：创建任务→轮询→下载→保存，带瞬时失败整体重试。

    2026-08-15 加固：UME 侧偶发「导出任务完成但未生成文件」/网络抖动时，
    用新 taskNo 整体重试（最多 EXPORT_FLOW_RETRY_MAX 次）；会话过期/互踢(401)
    时重新登录后重试一次（不消耗额度）；确定性失败（code=1004 残留 / 4xx /
    模板错误）立即抛错，错误含具体原因。
    """
    name = flow["name"]
    attempt = 0
    relogin_done = False
    while True:
        try:
            task_no = create_task(cookie, forgery_token, flow)
            file_name, download_forgery = poll_task_status(cookie, forgery_token, task_no, name)
            file_bytes = download_file(cookie, forgery_token, file_name, download_forgery, name)
            save_downloaded(file_bytes, save_dir, name, idx, file_name)
            return
        except Exception as e:
            if not relogin_done and _is_session_expired(e):
                relogin_done = True
                print(f"[RETRY] {name} 会话过期/互踢(401)，重新登录后重试")
                try:
                    _auth = login()
                    cookie, forgery_token = _auth["cookie"], _auth["forgery_token"]
                except Exception:
                    pass
                continue
            if attempt >= EXPORT_FLOW_RETRY_MAX or not _is_transient_failure(e):
                raise
            attempt += 1
            retries_log[name] = retries_log.get(name, 0) + 1
            wait = EXPORT_FLOW_RETRY_BACKOFF * attempt
            print(f"[RETRY] {name} exportvermo 流程瞬时失败（{str(e)[:160]}），"
                  f"{wait}s 后整体重试 ({retries_log[name]}/{EXPORT_FLOW_RETRY_MAX})")
            time.sleep(wait)


def collect_cm_data():
    """获取并合并 CM 数据 + 生成本地 Excel（仅保留最新一份）。

    返回 (merged_df, output_path, diagnostics)；
    diagnostics = {"retries": {flow: 次数}, "warnings": [{flow, ne, reason}]}；
    任一环节失败直接抛异常（错误含具体原因）。
    """
    # 1. 获取流程：cm_flows.json（页面编辑产物）优先，否则解析 new_url.txt
    flows = get_effective_flows()
    if not flows:
        raise Exception("未解析到任何流程（new_url.txt / cm_flows.json 均为空）")

    # 2. 登录（瞬时失败重试一次）
    try:
        auth = login()
    except Exception:
        print("[RETRY] 登录失败，重试一次")
        auth = login()
    cookie = auth["cookie"]
    forgery_token = auth["forgery_token"]

    # 3. 原始数据目录（持久保存，获取新数据前清理旧数据）
    save_dir = RAW_DATA_DIR
    cleanup_raw_data()
    os.makedirs(save_dir, exist_ok=True)

    # moquery 流程直接返回 DataFrame，exportvermo 流程下载文件后统一处理
    moquery_dfs = []  # moquery 流程的 DataFrame 列表
    retries_log = {}  # flow -> 瞬时重试次数（写进 result_json）
    warnings = []     # 被剔除的失效网元（写进 result_json.warnings）

    # 4. 串行执行所有流程
    for idx, flow in enumerate(flows):
        name = flow["name"]
        flow_type = flow["type"]
        print(f"\n{'=' * 70}")
        print(f"[FLOW {idx+1}/{len(flows)}] {name} ({flow_type})")
        print(f"{'=' * 70}")

        if flow_type == "moquery":
            # moquery 流程：直接获取 MO 数据（内部会保存原始数据）
            df = execute_moquery(cookie, forgery_token, flow, retries_log)
            if not df.empty:
                moquery_dfs.append(df)
        else:
            # exportvermo 流程：创建任务 → 轮询 → 下载（带瞬时失败整体重试）
            _run_exportvermo_flow(cookie, forgery_token, flow, save_dir, idx, retries_log)
            # 收集本流程被自动剔除的失效网元（具体原因，供 UI/日志展示）
            for item in flow.get("_skipped_nes", []):
                warnings.append({"flow": name, **item})

        # 流程间间隔
        if idx < len(flows) - 1:
            time.sleep(2)

    # 5. 合并数据
    all_dfs = list(moquery_dfs)

    # 处理 exportvermo 下载的 Excel 文件
    data_files = []
    for f in os.listdir(save_dir):
        if f.startswith("~$"):
            continue
        if f.lower().endswith((".xlsx", ".xlsm", ".xls", ".csv")):
            data_files.append(os.path.join(save_dir, f))

    if data_files:
        excel_df = process_excel_files(save_dir)
        if not excel_df.empty:
            all_dfs.append(excel_df)

    # 合并所有数据
    if all_dfs:
        merged_df = pd.concat(all_dfs, ignore_index=True)
        for col in OUTPUT_HEADERS:
            if col in merged_df.columns:
                merged_df[col] = merged_df[col].fillna("").astype(str)
        # 跨流程去重
        before = len(merged_df)
        merged_df = merged_df.drop_duplicates(subset=OUTPUT_HEADERS, keep="first").reset_index(drop=True)
        removed = before - len(merged_df)
        if removed > 0:
            print(f"[COLLECT] 跨流程去重: 删除 {removed} 行")
        print(f"[COLLECT] 总计 {len(merged_df)} 行")
    else:
        merged_df = pd.DataFrame(columns=OUTPUT_HEADERS)

    # 6. 生成本地 Excel 输出（cleanup_old_outputs 仅保留最新一份）
    output_path = generate_output(merged_df)

    # 不删除 raw_data 目录，保留最新原始数据
    gc.collect()
    diagnostics = {"retries": retries_log, "warnings": warnings}
    return merged_df, output_path, diagnostics


def run_cm_data_sync():
    """定时任务入口：拉取 RAN UME CM 小区配置数据 → API 写入数据库 + 本地保留最新 Excel。"""
    t0 = time.time()
    result = {"success": False, "rows": 0, "output_path": None,
              "errors": [], "retries": {}, "warnings": [], "elapsed_seconds": 0}

    merged_df, output_path, diagnostics = collect_cm_data()
    result["output_path"] = output_path
    result["retries"] = diagnostics.get("retries", {})
    result["warnings"] = diagnostics.get("warnings", [])

    # 被剔除的失效网元写入 log/cm_data_sync.log（持久审计，UI 之外的第二处可见）
    if result["warnings"]:
        try:
            log_dir = os.path.join(MY_APP_ROOT, "log")
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "cm_data_sync.log"), "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                        f"剔除失效网元 {len(result['warnings'])} 个:\n")
                for w in result["warnings"]:
                    f.write(f"  - {w.get('flow')}: {w.get('ne')} -> {w.get('reason', '')}\n")
        except Exception as e:
            print(f"[WARN] 写 cm_data_sync.log 失败: {e}")

    if merged_df is None or merged_df.empty:
        result["elapsed_seconds"] = round(time.time() - t0, 2)
        raise Exception("CM 数据获取为空，无有效数据可写入")

    api_errors = write_to_database(merged_df)
    result["rows"] = int(len(merged_df))
    result["elapsed_seconds"] = round(time.time() - t0, 2)

    if api_errors:
        result["errors"] = api_errors
        # 显式失败：避免数据库未更新但任务显示成功（本地副本已保留可回补）
        raise Exception("数据库写入失败（已回退本地 SQLite 副本）: " + "; ".join(api_errors))

    result["success"] = True
    print(f"[SYNC] CM 数据同步完成: {result['rows']} 行, 耗时 {result['elapsed_seconds']} 秒")
    return result


# ============================================================
# 主函数（独立运行入口，与定时任务同流程）
# ============================================================
def main():
    t_start = time.time()
    print(f"[MAIN] RAN UME CM MO Export 开始于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    output_path = None
    try:
        sync_result = run_cm_data_sync()
        output_path = sync_result.get("output_path")
    except Exception as e:
        print(f"\n[MAIN] 错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        gc.collect()

    elapsed = time.time() - t_start
    print(f"\n[MAIN] 总耗时: {elapsed:.2f} 秒")
    if output_path:
        print(f"[MAIN] 输出文件: {output_path}")
    print("[MAIN] 完成.")
    return output_path


if __name__ == "__main__":
    main()
