"""
RAN UME 服务集成
集成 ran_ume_login.py（PM 数据获取）+ generate_daily_availability.py（可用性报表生成）
从 ZTE RAN UME 网管系统获取 2G/3G/FDD/TDD PM 历史指标，生成 Daily Availability KPI 报表
"""
import ssl
import socket
import sys
import json
import time
import re
import base64
import gzip
import glob
import io
import gc
import os
import sqlite3
import warnings
import logging
from ftplib import FTP, error_perm
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("ran_ume_service")

try:
    import openpyxl
except ImportError:
    openpyxl = None

try:
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError:
    pd = None
    plt = None
    np = None

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# ========== 配置 ==========
HOST = os.environ.get("RAN_UME_HOST", "10.100.28.27")
PORT = int(os.environ.get("RAN_UME_PORT", "28001"))
USERNAME = os.environ.get("RAN_UME_USER", "NOC")
PASSWORD = os.environ.get("RAN_UME_PASS", "Zte@2025!")

RAN_UME_DATA_DIR = Path(r"d:\01_RPA\Task\my_app\data\ran_ume")
RAN_UME_DATA_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_DIR = str(RAN_UME_DATA_DIR / "exports")
os.makedirs(OUTPUT_DIR, exist_ok=True)
MAX_PARALLEL_WORKERS = 4

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = RAN_UME_DATA_DIR / "ran_kpi_daily.sqlite3"
UPLOAD_DB_NAME = "ran_kpi_daily.sqlite3"

# FTP 配置
FTP_HOST = "192.168.100.19"
FTP_USER = "ZTEEMS"
FTP_PASS = "DX"
FTP_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI/RAN"

# 技术类型
TECHS = ["2G", "3G", "FDD", "TDD"]

# 可用性报表输出目录
AVAILABILITY_OUTPUT_DIR = RAN_UME_DATA_DIR

# 备用鉴权信息
FALLBACK_COOKIE = (
    "X-Rm-Data-Version-zenap=1773367620002_0_0_0_0_0_0_0_0; "
    "Z-AUTH-CODE-28001=1154983705_f188b025b7b64878ae0f4511e90ab1a2; "
    "x-dexmesh-user-28001=D86935A99B38A02CDAEA05C225E9303A21FA22B872499884D7B2A1E26A5645FE; "
    "forgerydefense-28001=cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"
)
FALLBACK_FORGERY = "cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"

# Availability 配置
TARGET_SHEETS = ['Availability-NW', 'Availability-Regular', 'Availability-COOL', 'Availability-ERA']

TECH_MAP = {
    "2G_OLIB_Network_KPIs": "2G",
    "3G_OLIB_Network_KPIs": "3G",
    "FDD_OLIB_Network_KPIs": "FDD",
    "TDD_OLIB_Network_KPIs": "TDD",
}

SHEET_CONFIG = {
    'Availability-NW': {
        'patterns': [r'^G_NW$'],
        'tech_groups': {'2G': '2G ALL', '3G': '3G ALL', 'FDD': 'FDD ALL', 'TDD': 'TDD ALL'},
    },
    'Availability-Regular': {
        'patterns': [r'Regular'],
        'tech_groups': {'2G': '2G Regular', '3G': '3G Regular', 'FDD': 'FDD Regular'},
    },
    'Availability-COOL': {
        'patterns': [r'Cooli'],
        'tech_groups': {'2G': '2G Cooli', '3G': '3G Cooli', 'FDD': 'FDD Cooli'},
    },
    'Availability-ERA': {
        'patterns': [r'ERA'],
        'tech_groups': {'2G': '2G ERA', 'FDD': 'FDD ERA'},
    },
}

AVAILABILITY_METRICS = {
    "2G_OLIB_Network_KPIs": "TCH in service rate(%)",
    "3G_OLIB_Network_KPIs": "Cell Validity Rate(%)",
    "FDD_OLIB_Network_KPIs": "[FDD]Cell Availability[SDR_ITBBU]",
    "TDD_OLIB_Network_KPIs": "[TDD]Cell Availability[SDR_ITBBU]",
}

COLOR_MAP = {
    '2G ALL': '#2F5496', '3G ALL': '#ED7D31', '4G ALL': '#70AD47', 'FDD ALL': '#70AD47',
    '2G Regular': '#2F5496', '3G Regular': '#ED7D31', '4G Regular': '#70AD47', 'FDD Regular': '#70AD47',
    '2G Cooli': '#2F5496', '3G Cooli': '#ED7D31', '4G Cooli': '#70AD47', 'FDD Cooli': '#70AD47',
    '2G ERA': '#2F5496', '4G ERA': '#70AD47', 'FDD ERA': '#70AD47',
}

TARGET_VALUE = 0.9965
BG_COLOR = '#E8F0FE'
TITLE_COLOR = '#2F5496'
GRID_COLOR = '#C5C5C5'
MAX_LABEL_COLOR = '#FF0000'
MIN_LABEL_COLOR = '#ED7D31'

FTP_UPLOAD_PATH = "/01_RPA/LBR_Tools/KPI/RAN/ORANGE"


# ========== SSL / HTTP ==========
def _create_ssl_socket():
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
    ssock = _create_ssl_socket()
    headers = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: {HOST}:{PORT}\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Language: en-US,en;q=0.9\r\n"
        f"Accept-Encoding: identity\r\n"
        f"Connection: close\r\n"
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
            raise Exception(f"Failed to decompress gzip: {exc}")

    return status_line, resp_headers, header_part, resp_body


def _rsa_encrypt_pem(plaintext, public_key_b64):
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives import serialization
    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
    public_key = serialization.load_pem_public_key(pem.encode())
    encrypted = public_key.encrypt(plaintext.encode('utf-8'), asym_padding.PKCS1v15())
    return base64.b64encode(encrypted).decode('ascii')


# ========== 登录 ==========
def _login():
    logger.info("[RAN_UME] Starting authentication...")
    session_cookie = ""
    forgery_token = ""

    try:
        status, hdrs, raw_hdrs, body = _http_request(
            "GET",
            "/api/oauth2/v1/authorize?scope=user.login&response_type=code&redirect_uri=/uportal/framework/default.html"
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

        rsa_headers = f"Cookie: {init_cookie_str}\r\nX-Requested-With: XMLHttpRequest\r\n"
        status, hdrs, raw_hdrs, body = _http_request(
            "GET", "/api/oauth2/v1/login/publickey", headers_extra=rsa_headers,
        )

        public_key_b64 = ""
        if "200" in status:
            pk_data = json.loads(body.decode('utf-8'))
            public_key_b64 = pk_data.get("rsaPublicKey", "")

        encrypted_pwd = _rsa_encrypt_pem(PASSWORD, public_key_b64)

        login_payload = json.dumps({
            "username": USERNAME, "password": encrypted_pwd, "parameters": login_parameters,
        })
        login_headers = (
            f"Content-Type: application/json\r\n"
            f"Cookie: {init_cookie_str}\r\n"
            f"Referer: https://{HOST}:{PORT}/api/oauth2/v1/authorize?scope=user.login&response_type=code&redirect_uri=/uportal/framework/default.html\r\n"
            f"X-Requested-With: XMLHttpRequest\r\n"
        )
        if forgery_token:
            login_headers += f"forgerydefense: {forgery_token}\r\n"

        status, hdrs, raw_hdrs, body = _http_request(
            "POST", "/api/oauth2/v1/login_rsa", headers_extra=login_headers, body=login_payload,
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
        if not any("Z-AUTH-CODE" in c for c in cookies):
            raise Exception("Login failed - no auth cookie obtained")
        logger.info(f"[RAN_UME] Login success ({len(cookies)} cookies)")

    except Exception as e:
        logger.error(f"[RAN_UME] Login failed: {e}, using fallback cookies")
        session_cookie = FALLBACK_COOKIE
        forgery_token = FALLBACK_FORGERY

    return {"cookie": session_cookie, "forgery_token": forgery_token}


# ========== PM 查询 ==========
PM_REFERER = f"https://{HOST}:{PORT}/iui/pm/angularTask/dist/pmManagement.html"
PM_HISTORY_PATH = "/api/pm-analysis/v2/history"
PM_HISTORY_POLL_PATH = "/api/pm-analysis/v1/history"
PM_HISTORY_EXPORT_PATH = "/api/pm-analysis/v3/history/export"

PM_QUERY_CONFIGS = {
    "2G": {
        "templateid": "1638004472347", "base_name": "2G OLIB Network KPIs",
        "motid": "gsmPm.cell", "containvcell": 0, "indexfillingtype": "zeroDenominator",
        "nfctid": "MRNC",
        "items": ["306024", "306002", "306006", "306003", "306008", "1675910745777", "306004"],
        "uilocations": [
            {"haslogicmoc": False, "id": "bf4aa97e-54d4-4686-8fad-27481a1a8f3b", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "7017adf9-4ba6-4582-bb1c-251f2659dc5a", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "cb19a368-a1fd-4950-be1a-007c1485c424", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "50489222-477d-4071-a7f6-1f76fcdaea63", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "ac09c60f-ede4-4726-9a95-70dfd7f56ab3", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "1212567e-8919-422e-a507-a1657d0ea66a", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "3aa01f9d-6107-4120-904f-18c10816182b", "moc": "group.ran.topo", "model": "rangroup"},
        ],
    },
    "3G": {
        "templateid": "1638004472348", "base_name": "3G OLIB Network KPIs",
        "motid": "wPm.UtranCell,wPm.LogicCell", "containvcell": 1, "indexfillingtype": "default",
        "nfctid": "MRNC",
        "items": ["300857", "901593214", "901597214", "901598214", "300020", "300043", "300249",
                  "901604214", "901605214", "300532", "901410214", "901411214", "300476"],
        "uilocations": [
            {"haslogicmoc": False, "id": "5f0d1249-70ef-41d4-9775-4bc714f4cac7", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "6cafdd69-1bbe-4181-85c4-888465394892", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "6e5f401a-8a86-4a24-8b6e-18974f4cac7", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "56b55e84-9a8c-4441-bbd2-46d33cde02f5", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "f02801db-a267-4c44-bfd6-09746d93849f", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "88e9e97f-27bb-43c2-8627-8f3a8b65bf19", "moc": "group.ran.topo", "model": "rangroup"},
        ],
    },
    "TDD": {
        "templateid": "1638004472346", "base_name": "TDD OLIB Network KPIs",
        "motid": "EUtranCellTDD", "businessmotid": "EUtranCellTDD,TDDV3.EUtranCellTDD,CUEUtranCellTDDLTE",
        "containvcell": 0, "indexfillingtype": "default", "nfctid": "ITBBU,SDR,#",
        "items": ["1638004469353", "1638004469355", "1638004469356", "1638004469352", "1638004469358",
                  "1638004469359", "1638004469360", "1638004469361", "C373200029", "341089", "341088"],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [2, 2, 2, 2, 2, 2, 2, 2, 1, 0, 0],
        "itempositionbusiness": [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 2],
        "uilocations": [
            {"haslogicmoc": False, "id": "e7435e36-cdf1-4865-b8f7-98a8408a101c", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "88562cf4-fbcc-4d4f-8011-16974e755b08", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "8c9ae146-f4ae-4ef6-8adf-1205d47a6d42", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "3fab34d9-b7f0-40c3-afe1-058f58148bed", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "5ca35171-ccab-41b0-8348-5e1801d08873", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "5e384e6d-7a5d-4b6f-88f3-abc0dd4d625f", "moc": "group.ran.topo", "model": "rangroup"},
        ],
    },
    "FDD": {
        "templateid": "1638004472345", "base_name": "FDD OLIB Network KPIs",
        "motid": "EUtranCellFDD", "businessmotid": "EUtranCellFDD,FDDV3.EUtranCellFDD",
        "containvcell": 0, "indexfillingtype": "default", "nfctid": "ITBBU,SDR,#",
        "items": ["1638004469333", "1638004469340", "1638004469330", "1638004469331", "1638004469342",
                  "1638004469343", "1638004469344", "1638004469345", "C373200029", "1638004469332", "1638004469785"],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [2, 2, 2, 2, 2, 2, 2, 2, 1, 2, 2],
        "itempositionbusiness": [0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0],
        "uilocations": [
            {"haslogicmoc": False, "id": "e7435e36-cdf1-4865-b8f7-98a8408a101c", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "88562cf4-fbcc-4d4f-8011-16974e755b08", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "8c9ae146-f4ae-4ef6-8adf-1205d47a6d42", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "3fab34d9-b7f0-40c3-afe1-058f58148bed", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "5ca35171-ccab-41b0-8348-5e1801d08873", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "5e384e6d-7a5d-4b6f-88f3-abc0dd4d625f", "moc": "group.ran.topo", "model": "rangroup"},
        ],
    },
}


def _pm_auth_headers(cookie, forgery_token):
    headers = (
        f"Content-Type: application/json; charset=UTF-8\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Encoding: gzip, deflate, br\r\n"
        f"Cookie: {cookie}\r\n"
        f"Referer: {PM_REFERER}\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
    )
    if forgery_token:
        headers += f"forgerydefense: {forgery_token}\r\n"
    return headers


def _build_pm_payload(network_type, groupbygroup=True):
    cfg = PM_QUERY_CONFIGS.get(network_type)
    if not cfg:
        raise ValueError(f"Unsupported: {network_type}")

    now = datetime.now(timezone.utc)
    end_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    start_iso = (now - timedelta(days=91)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    suffix = "Group" if groupbygroup else "NW"
    templatename = f"{cfg['base_name']}{suffix}"
    items = cfg["items"]
    item_count = len(items)

    payload = {
        "arraycounterinfos": [], "containvcell": cfg["containvcell"],
        "datatype": 0, "displaymode": 0, "favoriteconditionname": templatename,
        "filterlayer": "group", "firstDayOfWeek": 7, "gr": "86400",
        "groupattributetype": 0, "groupbygroup": groupbygroup, "groupbyplmn": False,
        "grouplayer": "all", "grouptype": 0, "hidehistorystopbutton": True,
        "indexfillingtype": cfg["indexfillingtype"], "inexistenceres": False,
        "iswireless": True, "items": items,
        "itemsposition": cfg.get("itemsposition", [0] * item_count),
        "itemsposition1": cfg.get("itemsposition1", [0] * item_count),
        "motid": cfg["motid"], "needdeployfilter": False, "nfctid": cfg["nfctid"],
        "opencustomizehistoryexport": False, "opentemplatecustomcolumn": False,
        "plmnpdfdisplaymode": False, "queryallbusiness": False,
        "resfilterattribute": "", "reslocation": [], "showbusinesscolumn": False,
        "showintegrity": False, "straightquery": False,
        "templateid": cfg["templateid"], "templatename": templatename,
        "templatetype": 0, "thresholdinfos": [],
        "timeinfo": {"mode": 1, "start": start_iso, "end": end_iso, "relative": -1},
        "uilocations": cfg["uilocations"], "versiondatacompare": False,
    }

    if "businessmotid" in cfg:
        payload["businessmotid"] = cfg["businessmotid"]
        payload["businessfilterscope"] = []
        payload["groupbusinessids"] = []
    if "itempositionbusiness" in cfg:
        payload["itempositionbusiness"] = cfg["itempositionbusiness"]

    return payload


def _run_single_pm_query(cookie, forgery_token, cfg):
    """执行单个 PM 查询 + 导出"""
    network_type = cfg["network_type"]
    suffix = cfg["suffix"]
    groupbygroup = cfg["groupbygroup"]
    file_suffix = "Region" if suffix == "Group" else suffix

    logger.info(f"[PM] Starting query [{network_type}/{suffix}]")
    payload = _build_pm_payload(network_type, groupbygroup)
    body = json.dumps(payload, ensure_ascii=False)
    headers = _pm_auth_headers(cookie, forgery_token)

    status, hdrs, raw_hdrs, resp_body = _http_request("POST", PM_HISTORY_PATH, headers_extra=headers, body=body.encode('utf-8'))
    if "200" not in status:
        raise Exception(f"Create PM query failed: {status}")

    data = json.loads(resp_body.decode('utf-8'))
    queryid = data.get("queryid") or data.get("id")
    if not queryid:
        raise Exception(f"No queryid: {resp_body.decode('utf-8', errors='replace')[:500]}")

    # Poll
    poll_path = f"{PM_HISTORY_POLL_PATH}?type=0&queryid={queryid}"
    poll_headers = _pm_auth_headers(cookie, forgery_token, )
    deadline = time.time() + 300
    while time.time() < deadline:
        status, hdrs, raw_hdrs, resp_body = _http_request("GET", poll_path, headers_extra=poll_headers)
        poll_data = json.loads(resp_body.decode('utf-8'))
        if poll_data.get("querystate") == 1 or poll_data.get("progress", 0) >= 100:
            break
        time.sleep(5)

    # Export
    filename = f"{network_type} OLIB Network KPIs_{file_suffix}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    export_payload = {
        "id": queryid, "filename": filename, "chartlayout": 1, "contentmode": 0,
        "customizefieldtype": "0", "exportfiletype": 1, "exportserialnumber": False,
        "exporttableheaders": False, "formatwithts": 0, "imageinfo": [],
        "itemshowtype": 0, "tableheaders": {},
    }
    export_body = json.dumps(export_payload, ensure_ascii=False)
    status, hdrs, raw_hdrs, resp_body = _http_request("POST", PM_HISTORY_EXPORT_PATH, headers_extra=headers, body=export_body.encode('utf-8'))
    if "200" not in status:
        raise Exception(f"Export failed: {status}")

    output_path = os.path.join(OUTPUT_DIR, f"{filename}.xlsx")
    seq = 1
    while os.path.exists(output_path):
        output_path = os.path.join(OUTPUT_DIR, f"{filename}_{seq}.xlsx")
        seq += 1
    with open(output_path, "wb") as f:
        f.write(resp_body)
    logger.info(f"[PM] [{network_type}/{suffix}] saved: {output_path} ({len(resp_body)} bytes)")
    return output_path


# ========== DB 写入 ==========
def _read_xlsx(filepath):
    if openpyxl is None:
        raise ImportError("缺少 openpyxl")
    with open(filepath, 'rb') as f:
        file_bytes = f.read()
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
    try:
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        headers = [str(col).strip() if col is not None else f"col_{i}" for i, col in enumerate(next(rows_iter))]
        data = [list(row) for row in rows_iter if not all(v is None for v in row)]
    finally:
        wb.close()
    return headers, data


def _write_to_db(db_path, table_name, headers, data):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    if "Begin Time" not in headers or "Group" not in headers:
        conn.close()
        return 0

    table_exists = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone() is not None

    if not table_exists:
        cursor.execute(
            f'CREATE TABLE "{table_name}" ("Begin Time" TEXT NOT NULL, "Group" TEXT NOT NULL, PRIMARY KEY ("Begin Time", "Group"))'
        )

    for h in headers:
        if h in ("Begin Time", "Group"):
            continue
        try:
            cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{h.replace(chr(34), chr(34)+chr(34))}" TEXT')
        except sqlite3.OperationalError:
            pass

    quoted_headers = [f'"{h.replace(chr(34), chr(34)+chr(34))}"' for h in headers]
    placeholders = ", ".join(["?"] * len(headers))
    insert_sql = f'INSERT OR REPLACE INTO "{table_name}" ({", ".join(quoted_headers)}) VALUES ({placeholders})'

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
        if len(batch) >= 500:
            cursor.executemany(insert_sql, batch)
            batch.clear()
    if batch:
        cursor.executemany(insert_sql, batch)

    conn.commit()
    conn.close()
    return row_count


def _find_latest_xlsx(pattern_prefix, search_dir=OUTPUT_DIR):
    pattern = os.path.join(search_dir, f"{pattern_prefix}*.xlsx")
    files = [f for f in glob.glob(pattern) if not os.path.basename(f).startswith("~$")]
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def _upload_to_ftp(local_path, remote_dir, filename):
    for attempt in range(1, 3):
        try:
            ftp = FTP(FTP_HOST, timeout=30)
            ftp.encoding = "utf-8"
            ftp.login(FTP_USER, FTP_PASS)
            parts = remote_dir.strip("/").split("/")
            for i in range(len(parts)):
                abs_path = "/" + "/".join(parts[:i + 1])
                try:
                    ftp.cwd(abs_path)
                except error_perm:
                    try:
                        ftp.mkd(abs_path)
                        ftp.cwd(abs_path)
                    except error_perm:
                        pass
            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {filename}", f)
            ftp.quit()
            logger.info(f"[FTP] Uploaded: {filename}")
            return True
        except Exception as e:
            logger.warning(f"[FTP] Upload failed (attempt {attempt}): {e}")
    return False


# ========== 主任务函数 ==========
def run_ran_ume_pm_sync() -> dict:
    """
    RAN UME PM 数据获取任务：
    1. 登录 RAN UME
    2. 并行查询 2G/3G/FDD/TDD × NW/Group = 8 个 PM 指标
    3. 写入 SQLite 数据库
    4. 上传 FTP

    Returns: dict with success, tables, errors, etc.
    """
    start_time = time.time()
    result = {"success": False, "tables": {}, "errors": [], "elapsed_seconds": 0}

    try:
        # Login
        auth = _login()
        cookie = auth["cookie"]
        forgery_token = auth["forgery_token"]

        # PM configs
        pm_configs = [
            {"network_type": t, "groupbygroup": g, "suffix": s}
            for t in TECHS for g, s in [(True, "Group"), (False, "NW")]
        ]

        # Parallel queries
        logger.info(f"[RAN_UME] Starting {len(pm_configs)} PM queries...")
        exported_files = []
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
            futures = {
                executor.submit(_run_single_pm_query, cookie, forgery_token, cfg): cfg
                for cfg in pm_configs
            }
            for future in as_completed(futures):
                cfg = futures[future]
                try:
                    path = future.result()
                    exported_files.append(path)
                except Exception as e:
                    err = f"[{cfg['network_type']}/{cfg['suffix']}] failed: {e}"
                    logger.error(err)
                    result["errors"].append(err)

        # Process xlsx → DB
        total_imported = 0
        db_path = str(DB_PATH)
        for tech in TECHS:
            nw_file = _find_latest_xlsx(f"{tech} OLIB Network KPIs_NW")
            region_file = _find_latest_xlsx(f"{tech} OLIB Network KPIs_Region")
            table_name = f"{tech}_OLIB_Network_KPIs"

            merged_headers = None
            merged_data = []

            if nw_file:
                h, d = _read_xlsx(nw_file)
                if "Group" not in h:
                    h.append("Group")
                    for row in d:
                        row.append("G_NW")
                else:
                    gi = h.index("Group")
                    for row in d:
                        row[gi] = "G_NW"
                merged_headers = list(h)
                merged_data.extend(d)

            if region_file:
                h, d = _read_xlsx(region_file)
                if merged_headers:
                    # 将 Region 数据按 merged_headers 顺序重排，避免列错位
                    # Region 文件列顺序可能和 NW 不同（Group 位置不同）
                    col_map = []  # merged_headers[i] 在 h 中的索引
                    for col in merged_headers:
                        col_map.append(h.index(col) if col in h else -1)
                    # 检查是否有 Region 独有的列
                    for col in h:
                        if col not in merged_headers:
                            merged_headers.append(col)
                            col_map.append(h.index(col))
                    # 重排每行数据
                    reordered = []
                    for row in d:
                        new_row = []
                        for idx in col_map:
                            if idx >= 0 and idx < len(row):
                                new_row.append(row[idx])
                            else:
                                new_row.append("")
                        reordered.append(new_row)
                    merged_data.extend(reordered)
                else:
                    merged_headers = list(h)
                    merged_data.extend(d)

            if merged_headers and merged_data:
                row_count = _write_to_db(db_path, table_name, merged_headers, merged_data)
                result["tables"][table_name] = row_count
                total_imported += row_count

        # FTP upload
        if os.path.exists(db_path):
            _upload_to_ftp(db_path, FTP_REMOTE_DIR, UPLOAD_DB_NAME)

        result["success"] = len(result["errors"]) == 0
        result["total_rows"] = total_imported

    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"[RAN_UME] Task failed: {e}")

    elapsed = time.time() - start_time
    result["elapsed_seconds"] = round(elapsed, 2)
    logger.info(f"[RAN_UME] PM sync done: {result.get('total_rows', 0)} rows, {elapsed:.2f}s")
    return result


# ========== Availability 报表生成 ==========
def _normalize_chart_label(name):
    if 'TDD' in name:
        return None
    name = name.replace('FDD ALL', '4G ALL')
    name = name.replace('FDD Regular', '4G Regular')
    name = name.replace('FDD Cooli', '4G Cooli')
    name = name.replace('FDD ERA', '4G ERA')
    return name


def _find_availability_column(columns, table_name):
    configured = AVAILABILITY_METRICS.get(table_name, "").strip()
    if configured and configured in columns:
        return configured
    for col in columns:
        if any(kw in col.lower() for kw in ["cell availability", "availability"]):
            return col
    return columns[0] if columns else None


def _generate_chart(df, sheet_name, output_dir):
    if pd is None or plt is None:
        return ""
    if df.empty or 'Cell Group' not in df.columns:
        return ""

    df = df.copy()
    df['Cell Group'] = df['Cell Group'].apply(_normalize_chart_label)
    df = df.dropna(subset=['Cell Group'])
    if df.empty:
        return ""

    cell_groups = sorted(df['Cell Group'].unique().tolist())
    pivot_df = df.pivot_table(index='Begin Time', columns='Cell Group', values='Cell Availability')
    dates = pivot_df.index.tolist()
    n_dates = len(dates)

    fig, ax = plt.subplots(figsize=(14, 5.5))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    for cg in cell_groups:
        values = pivot_df[cg].values
        color = COLOR_MAP.get(cg, '#333333')
        ax.plot(range(n_dates), values, color=color, linewidth=1.2, label=cg, alpha=0.85)

    ax.axhline(y=TARGET_VALUE, color='#FF0000', linestyle='--', linewidth=1.0, alpha=0.7)
    ax.text(n_dates - 1, TARGET_VALUE + 0.003, f'T:{TARGET_VALUE*100:.2f}%',
            color=MAX_LABEL_COLOR, fontsize=8, ha='right', fontweight='bold')

    # 标注全局最大值和最小值
    all_values = pivot_df.values
    if not np.all(np.isnan(all_values)):
        max_pos = np.unravel_index(np.nanargmax(all_values), all_values.shape)
        min_pos = np.unravel_index(np.nanargmin(all_values), all_values.shape)
        max_val = all_values[max_pos]
        min_val = all_values[min_pos]
        max_x = max_pos[0]   # 日期索引
        min_x = min_pos[0]   # 日期索引

        ax.annotate(f'{max_val*100:.2f}%',
                    xy=(max_x, max_val),
                    xytext=(max_x, max_val + 0.015),
                    fontsize=7.5, color=MAX_LABEL_COLOR, ha='center', fontweight='bold',
                    arrowprops=dict(arrowstyle='->', color=MAX_LABEL_COLOR, lw=0.8))

        ax.annotate(f'{min_val*100:.2f}%',
                    xy=(min_x, min_val),
                    xytext=(min_x, min_val - 0.02),
                    fontsize=7.5, color=MIN_LABEL_COLOR, ha='center', fontweight='bold',
                    arrowprops=dict(arrowstyle='->', color=MIN_LABEL_COLOR, lw=0.8))

    # Y轴：最小值动态，最大值固定102%
    y_min = max(0.60, pivot_df.min().min() - 0.03)
    ax.set_ylim(y_min, 1.02)
    ax.set_ylabel('Cell Availability', fontsize=9)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x*100:.2f}%'))
    ax.set_title(sheet_name, fontsize=13, fontweight='bold', color=TITLE_COLOR, pad=12)
    ax.grid(axis='y', linestyle='--', color=GRID_COLOR, linewidth=0.6, alpha=0.6)
    ax.legend(loc='lower center', bbox_to_anchor=(0.5, -0.18), ncol=len(cell_groups), fontsize=7.5, frameon=False)

    # 横坐标显示日期
    date_labels = []
    for d in dates:
        s = str(d)
        if 'T' in s:
            s = s.split('T')[0]
        if len(s) >= 10:
            s = s[5:]  # MM-DD
        date_labels.append(s)
    # 根据数据量控制显示的刻度数
    if n_dates > 30:
        step = max(1, n_dates // 15)
        tick_positions = list(range(0, n_dates, step))
        tick_labels = [date_labels[i] for i in tick_positions]
        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, rotation=45, fontsize=7, ha='right')
    else:
        ax.set_xticks(range(n_dates))
        ax.set_xticklabels(date_labels, rotation=45, fontsize=7, ha='right')

    plt.tight_layout()

    output_path = os.path.join(output_dir, f'{sheet_name}.png')
    fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor=BG_COLOR, edgecolor='none')
    plt.close(fig)
    return output_path


def run_availability_report() -> dict:
    """
    生成 Daily Availability KPI 报表：
    1. 从 ran_kpi_daily.sqlite3 读取 PM 数据
    2. 生成 Excel + 图表 PNG
    3. 上传图片到 FTP

    Returns: dict
    """
    start_time = time.time()
    result = {"success": False, "errors": [], "generated_files": [], "elapsed_seconds": 0}

    if pd is None:
        result["errors"].append("缺少 pandas 依赖")
        return result

    db_path = str(DB_PATH)
    if not os.path.exists(db_path):
        result["errors"].append(f"数据库不存在: {db_path}")
        return result

    try:
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() if r[0] in TECH_MAP]

        table_dfs = {}
        for table in tables:
            table_dfs[table] = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
        conn.close()

        if not table_dfs:
            result["errors"].append("数据库中未找到 OLIB Network KPIs 表")
            return result

        # Build availability data
        sheet_rows = {sheet: [] for sheet in TARGET_SHEETS}
        for table_name, df in table_dfs.items():
            tech = TECH_MAP[table_name]
            if "Begin Time" not in df.columns or "Group" not in df.columns:
                continue
            avail_col = _find_availability_column(list(df.columns), table_name)
            if not avail_col:
                continue

            df = df.copy()
            df['Begin Time'] = df['Begin Time'].apply(lambda x: str(x).split('T')[0] if x else "")
            df[avail_col] = pd.to_numeric(df[avail_col], errors='coerce')
            if not df[avail_col].dropna().empty and df[avail_col].dropna().max() > 1:
                df[avail_col] = df[avail_col] / 100.0

            for sheet_name, cfg in SHEET_CONFIG.items():
                if tech not in cfg['tech_groups']:
                    continue
                mask = df['Group'].apply(
                    lambda x: any(re.search(p, str(x), re.IGNORECASE) for p in cfg['patterns']) if x else False
                )
                sub = df[mask].copy()
                if sub.empty:
                    continue
                agg = sub.groupby('Begin Time')[avail_col].mean().reset_index()
                agg['Cell Group'] = cfg['tech_groups'][tech]
                agg['Cell Availability'] = agg[avail_col]
                sheet_rows[sheet_name].append(agg[['Begin Time', 'Cell Group', 'Cell Availability']])

        # Write Excel
        output_excel = str(AVAILABILITY_OUTPUT_DIR / "Daily_Aailability_KPI.xlsx")
        with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
            for sheet_name in TARGET_SHEETS:
                frames = sheet_rows.get(sheet_name, [])
                if frames:
                    df = pd.concat(frames, ignore_index=True).sort_values(['Cell Group', 'Begin Time'])
                else:
                    df = pd.DataFrame(columns=['Begin Time', 'Cell Group', 'Cell Availability'])
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        result["generated_files"].append(output_excel)

        # Generate charts
        output_dir = str(AVAILABILITY_OUTPUT_DIR)
        generated_images = []
        for sheet_name in TARGET_SHEETS:
            frames = sheet_rows.get(sheet_name, [])
            if frames:
                df = pd.concat(frames, ignore_index=True).sort_values(['Cell Group', 'Begin Time'])
            else:
                df = pd.DataFrame()
            img_path = _generate_chart(df, sheet_name, output_dir)
            if img_path:
                generated_images.append(img_path)
                result["generated_files"].append(img_path)

        # Upload images to FTP
        for img_path in generated_images:
            try:
                ftp = FTP()
                ftp.connect(FTP_HOST, 21, timeout=30)
                ftp.encoding = "utf-8"
                ftp.login(FTP_USER, FTP_PASS)
                parts = FTP_UPLOAD_PATH.strip('/').split('/')
                current = ''
                for part in parts:
                    current += f'/{part}'
                    try:
                        ftp.cwd(current)
                    except error_perm:
                        ftp.mkd(current)
                        ftp.cwd(current)
                fname = os.path.basename(img_path)
                with open(img_path, 'rb') as f:
                    ftp.storbinary(f'STOR {fname}', f)
                ftp.quit()
            except Exception as e:
                result["errors"].append(f"FTP upload {os.path.basename(img_path)} failed: {e}")

        result["success"] = len(result["errors"]) == 0

    except Exception as e:
        result["errors"].append(str(e))
        logger.error(f"[Availability] Report failed: {e}")

    elapsed = time.time() - start_time
    result["elapsed_seconds"] = round(elapsed, 2)
    return result


def run_ran_ume_full_task() -> dict:
    """
    完整的 RAN UME 任务：PM 数据获取 + Availability 报表生成
    """
    start_time = time.time()
    result = {"success": False, "steps": {}, "errors": [], "elapsed_seconds": 0}

    # Step 1: PM data fetch
    logger.info("[RAN_UME] Step 1: PM data fetch...")
    pm_result = run_ran_ume_pm_sync()
    result["steps"]["pm_sync"] = pm_result
    if not pm_result["success"]:
        result["errors"].extend(pm_result.get("errors", []))

    # Step 2: Availability report
    logger.info("[RAN_UME] Step 2: Availability report generation...")
    avail_result = run_availability_report()
    result["steps"]["availability"] = avail_result
    if not avail_result["success"]:
        result["errors"].extend(avail_result.get("errors", []))

    result["success"] = pm_result["success"] and avail_result["success"]

    elapsed = time.time() - start_time
    result["elapsed_seconds"] = round(elapsed, 2)
    logger.info(f"[RAN_UME] Full task done: {elapsed:.2f}s, success={result['success']}")
    return result


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')

    t0 = time.time()
    result = run_ran_ume_full_task()
    print(f"\nRAN UME 任务结果: {'成功' if result['success'] else '失败'}")
    print(f"步骤: {list(result['steps'].keys())}")
    if result['errors']:
        print(f"错误: {result['errors']}")
    print(f"耗时: {result['elapsed_seconds']}s")
