"""
RAN UME Login Module
从 ZTE RAN UME 网管系统登录并获取鉴权 Cookie / forgery token
可独立运行，也可被其他脚本导入使用。
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
import subprocess
import sqlite3
import warnings
from ftplib import FTP, error_perm
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

try:
    import openpyxl
except ImportError:
    openpyxl = None


try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HOST = "10.100.28.27"
PORT = 28001
USERNAME = "NOC"
PASSWORD = "Zte@2025!"

# PM 导出文件保存目录（与 ran_kpi_precess.py 保持一致，使用 Downloads 目录）
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

# PM 指标查询并行数
MAX_PARALLEL_WORKERS = int(os.environ.get("PM_PARALLEL_WORKERS", "4"))

# 数据库处理配置（参考 ran_kpi_precess.py）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "ran_kpi_202606.sqlite3")
UPLOAD_DB_NAME = "ran_kpi_daily_202606.sqlite3"

# FTP 配置
FTP_HOST = "192.168.100.19"
FTP_USER = "ZTEEMS"
FTP_PASS = "DX"
FTP_REMOTE_DIR = "/01_RPA/LBR_Tools/KPI/RAN"

# 需要处理的技术类型
TECHS = ["2G", "3G", "FDD", "TDD"]

# 忽略 openpyxl 的 UserWarning
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# 备用鉴权信息：当自动登录失败时回退使用
FALLBACK_COOKIE = (
    "X-Rm-Data-Version-zenap=1773367620002_0_0_0_0_0_0_0_0; "
    "Z-AUTH-CODE-28001=1154983705_f188b025b7b64878ae0f4511e90ab1a2; "
    "x-dexmesh-user-28001=D86935A99B38A02CDAEA05C225E9303A21FA22B872499884D7B2A1E26A5645FE; "
    "forgerydefense-28001=cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"
)
FALLBACK_FORGERY = "cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"


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


def login():
    """
    执行 RAN UME 登录流程（优先使用共享缓存，避免同账户重复登录）。
    返回包含 cookie 和 forgery_token 的字典；失败时回退到 FALLBACK_COOKIE。
    """
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        from auth_manager import get_auth
        result = get_auth(HOST, PORT, USERNAME, PASSWORD)
        source = "缓存" if result["from_cache"] else "重新登录"
        print(f"[LOGIN] 鉴权成功（来源: {source}）")
        return {"cookie": result["cookie"], "forgery_token": result["forgery_token"]}
    except Exception as e:
        print(f"[LOGIN] auth_manager 失败: {e}")
        print("[LOGIN] Falling back to hardcoded cookies...")
        return {"cookie": FALLBACK_COOKIE, "forgery_token": FALLBACK_FORGERY}


# ---------------------------------------------------------------------------
# PM 指标查询
# ---------------------------------------------------------------------------

PM_HISTORY_PATH = "/api/pm-analysis/v2/history"
PM_HISTORY_POLL_PATH = "/api/pm-analysis/v1/history"
PM_HISTORY_EXPORT_PATH = "/api/pm-analysis/v3/history/export"
PM_REFERER = f"https://{HOST}:{PORT}/iui/pm/angularTask/dist/pmManagement.html"


def _pm_auth_headers(cookie: str, forgery_token: str, extra: dict | None = None) -> str:
    """构造 PM 接口需要的鉴权请求头。"""
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
    if extra:
        for k, v in extra.items():
            headers += f"{k}: {v}\r\n"
    return headers


PM_QUERY_CONFIGS = {
    "2G": {
        "templateid": "1638004472347",
        "base_name": "2G OLIB Network KPIs",
        "motid": "gsmPm.cell",
        "containvcell": 0,
        "indexfillingtype": "zeroDenominator",
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
        "templateid": "1638004472348",
        "base_name": "3G OLIB Network KPIs",
        "motid": "wPm.UtranCell,wPm.LogicCell",
        "containvcell": 1,
        "indexfillingtype": "default",
        "nfctid": "MRNC",
        "items": [
            "300857", "901593214", "901597214", "901598214", "300020", "300043", "300249",
            "901604214", "901605214", "300532", "901410214", "901411214", "300476",
        ],
        "uilocations": [
            {"haslogicmoc": False, "id": "5f0d1249-70ef-41d4-9775-4bc714f4cac7", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "6cafdd69-1bbe-4181-85c4-888465394892", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "6e5f401a-4a34-41b4-a29e-18936670f481", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "56b65e84-9a84-4441-bbd2-46d33cde02f5", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "f02801db-a267-4c44-bfd6-09746d93849f", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "88e9e97f-27bb-43c2-8627-8f3a8b65bf19", "moc": "group.ran.topo", "model": "rangroup"},
        ],
    },
    "TDD": {
        "templateid": "1638004472346",
        "base_name": "TDD OLIB Network KPIs",
        "motid": "EUtranCellTDD",
        "businessmotid": "EUtranCellTDD,TDDV3.EUtranCellTDD,CUEUtranCellTDDLTE",
        "containvcell": 0,
        "indexfillingtype": "default",
        "nfctid": "ITBBU,SDR,#",
        "items": [
            "1638004469353", "1638004469355", "1638004469356", "1638004469352", "1638004469358",
            "1638004469359", "1638004469360", "1638004469361", "C373200029", "341089", "341088",
        ],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [2, 2, 2, 2, 2, 2, 2, 2, 1, 0, 0],
        "itempositionbusiness": [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 2],
        "uilocations": [
            {"haslogicmoc": False, "id": "e7435e36-cdf1-4865-b8f7-98a8408a101c", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "88562cf4-fbcc-4d4f-8011-16974e755b08", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "8c9ae146-f4ae-4ef6-8adf-1205d47a6d42", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "3fab34d9-b7f0-40c3-afe1-058f5814fbed", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "5ca35171-ccab-41b0-8348-5e1801d08873", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "5e384e6d-7a5d-4b6f-88f3-abc0dd4d625f", "moc": "group.ran.topo", "model": "rangroup"},
        ],
    },
    "FDD": {
        "templateid": "1638004472345",
        "base_name": "FDD OLIB Network KPIs",
        "motid": "EUtranCellFDD",
        "businessmotid": "EUtranCellFDD,FDDV3.EUtranCellFDD",
        "containvcell": 0,
        "indexfillingtype": "default",
        "nfctid": "ITBBU,SDR,#",
        "items": [
            "1638004469333", "1638004469340", "1638004469330", "1638004469331", "1638004469342",
            "1638004469343", "1638004469344", "1638004469345", "C373200029", "1638004469332", "1638004469785",
        ],
        "itemsposition": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "itemsposition1": [2, 2, 2, 2, 2, 2, 2, 2, 1, 2, 2],
        "itempositionbusiness": [0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0],
        "uilocations": [
            {"haslogicmoc": False, "id": "e7435e36-cdf1-4865-b8f7-98a8408a101c", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "88562cf4-fbcc-4d4f-8011-16974e755b08", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "8c9ae146-f4ae-4ef6-8adf-1205d47a6d42", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "3fab34d9-b7f0-40c3-afe1-058f5814fbed", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "5ca35171-ccab-41b0-8348-5e1801d08873", "moc": "group.ran.topo", "model": "rangroup"},
            {"haslogicmoc": False, "id": "5e384e6d-7a5d-4b6f-88f3-abc0dd4d625f", "moc": "group.ran.topo", "model": "rangroup"},
        ],
    },
}


def build_pm_query_payload(
    network_type: str = "2G",
    start_iso: str | None = None,
    end_iso: str | None = None,
    groupbygroup: bool = True,
    templatename: str | None = None,
) -> dict:
    """
    构造 PM 历史指标查询 Payload。

    Args:
        network_type: "2G"、"3G" 或 "TDD"
        start_iso: 开始时间 ISO 字符串
        end_iso: 结束时间 ISO 字符串
        groupbygroup: 是否按组聚合
        templatename: 自定义模板名，为空则自动生成
    """
    cfg = PM_QUERY_CONFIGS.get(network_type)
    if not cfg:
        raise ValueError(f"Unsupported network_type: {network_type}")

    now = datetime.now(timezone.utc)
    if end_iso is None:
        end_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if start_iso is None:
        start_iso = (now - timedelta(days=91)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    if templatename is None:
        suffix = "Group" if groupbygroup else "NW"
        templatename = f"{cfg['base_name']}{suffix}"

    items = cfg["items"]
    item_count = len(items)

    payload = {
        "arraycounterinfos": [],
        "containvcell": cfg["containvcell"],
        "datatype": 0,
        "displaymode": 0,
        "favoriteconditionname": templatename,
        "filterlayer": "group",
        "firstDayOfWeek": 7,
        "gr": "86400",
        "groupattributetype": 0,
        "groupbygroup": groupbygroup,
        "groupbyplmn": False,
        "grouplayer": "all",
        "grouptype": 0,
        "hidehistorystopbutton": True,
        "indexfillingtype": cfg["indexfillingtype"],
        "inexistenceres": False,
        "iswireless": True,
        "items": items,
        "itemsposition": cfg.get("itemsposition", [0] * item_count),
        "itemsposition1": cfg.get("itemsposition1", [0] * item_count),
        "motid": cfg["motid"],
        "needdeployfilter": False,
        "nfctid": cfg["nfctid"],
        "opencustomizehistoryexport": False,
        "opentemplatecustomcolumn": False,
        "plmnpdfdisplaymode": False,
        "queryallbusiness": False,
        "resfilterattribute": "",
        "reslocation": [],
        "showbusinesscolumn": False,
        "showintegrity": False,
        "straightquery": False,
        "templateid": cfg["templateid"],
        "templatename": templatename,
        "templatetype": 0,
        "thresholdinfos": [],
        "timeinfo": {
            "mode": 1,
            "start": start_iso,
            "end": end_iso,
            "relative": -1,
        },
        "uilocations": cfg["uilocations"],
        "versiondatacompare": False,
    }

    # TDD 特有字段
    if "businessmotid" in cfg:
        payload["businessmotid"] = cfg["businessmotid"]
        payload["businessfilterscope"] = []
        payload["groupbusinessids"] = []
    if "itempositionbusiness" in cfg:
        payload["itempositionbusiness"] = cfg["itempositionbusiness"]

    return payload


def get_default_pm_query_payload(
    start_iso: str | None = None,
    end_iso: str | None = None,
    groupbygroup: bool = True,
    templatename: str | None = None,
) -> dict:
    """返回默认的 2G PM 历史指标查询 Payload（兼容旧接口）。"""
    return build_pm_query_payload(
        network_type="2G",
        start_iso=start_iso,
        end_iso=end_iso,
        groupbygroup=groupbygroup,
        templatename=templatename,
    )


def create_pm_history_query(cookie: str, forgery_token: str, payload: dict) -> str:
    """
    创建 PM 历史指标查询任务。
    返回 queryid。
    """
    print("[PM] Creating history query...")
    body = json.dumps(payload, ensure_ascii=False)
    headers = _pm_auth_headers(cookie, forgery_token)

    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST",
        PM_HISTORY_PATH,
        headers_extra=headers,
        body=body.encode('utf-8'),
    )
    print(f"[PM] Create query status: {status}")

    if "200" not in status:
        raise Exception(f"Create PM query failed: {status}")

    resp_text = resp_body.decode('utf-8', errors='replace')
    print(f"[PM] Create query response: {resp_text[:300]}")
    data = json.loads(resp_text)
    queryid = data.get("queryid") or data.get("id")
    if not queryid:
        raise Exception(f"No queryid returned: {resp_text[:500]}")
    print(f"[PM] Query ID: {queryid}")
    return queryid


def wait_pm_history_ready(
    cookie: str,
    forgery_token: str,
    queryid: str,
    timeout: int = 300,
    interval: int = 5,
) -> dict:
    """
    轮询 PM 历史指标查询进度，直到完成或超时。
    返回最终状态字典。
    """
    print(f"[PM] Polling query progress (timeout={timeout}s, interval={interval}s)...")
    path = f"{PM_HISTORY_POLL_PATH}?type=0&queryid={queryid}"
    headers = _pm_auth_headers(cookie, forgery_token, extra={"Accept": "application/json, text/plain, */*"})

    deadline = time.time() + timeout
    while time.time() < deadline:
        status, hdrs, raw_hdrs, resp_body = _http_request(
            "GET",
            path,
            headers_extra=headers,
        )
        resp_text = resp_body.decode('utf-8', errors='replace')
        data = json.loads(resp_text)
        progress = data.get("progress", 0)
        querystate = data.get("querystate", 0)
        print(f"[PM] Progress: {progress}%, state: {querystate}")

        if querystate == 1 or progress >= 100:
            print("[PM] Query ready")
            return data

        time.sleep(interval)

    raise Exception(f"PM query timed out after {timeout}s")


def export_pm_history(
    cookie: str,
    forgery_token: str,
    queryid: str,
    filename: str | None = None,
    output_path: str | None = None,
) -> str:
    """
    导出并下载 PM 历史指标结果。
    返回保存的文件路径。
    """
    if not filename:
        filename = f"PM_History_{queryid}"

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

    print(f"[PM] Exporting history data: {filename}")
    body = json.dumps(payload, ensure_ascii=False)
    headers = _pm_auth_headers(cookie, forgery_token)

    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST",
        PM_HISTORY_EXPORT_PATH,
        headers_extra=headers,
        body=body.encode('utf-8'),
    )
    print(f"[PM] Export status: {status}")

    if "200" not in status:
        raise Exception(f"Export PM history failed: {status}")

    if not output_path:
        output_path = os.path.join(OUTPUT_DIR, f"{filename}.xlsx")

    with open(output_path, "wb") as f:
        f.write(resp_body)
    print(f"[PM] Saved to: {output_path} ({len(resp_body)} bytes)")
    return output_path


def find_latest_xlsx(pattern_prefix: str, search_dir: str = OUTPUT_DIR) -> str | None:
    """在指定目录中查找匹配前缀的最新 xlsx 文件。"""
    pattern = os.path.join(search_dir, f"{pattern_prefix}*.xlsx")
    files = glob.glob(pattern)
    files = [f for f in files if not os.path.basename(f).startswith("~$")]
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def read_xlsx(filepath: str) -> tuple[list[str], list[list]]:
    """读取 xlsx 文件，返回列名和数据行列表。"""
    if openpyxl is None:
        raise ImportError("缺少 openpyxl，请先安装：pip install openpyxl")

    with open(filepath, 'rb') as f:
        file_bytes = f.read()

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
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


def write_to_db(db_path: str, table_name: str, headers: list[str], data: list[list]) -> int:
    """将数据写入 SQLite，以 'Begin Time' 和 'Group' 为联合主键进行替换/更新。"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    if "Begin Time" not in headers or "Group" not in headers:
        print(f"  [警告] 表 {table_name} 缺少 'Begin Time' 或 'Group' 列，跳过。")
        conn.close()
        return 0

    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    table_exists = cursor.fetchone() is not None

    if not table_exists:
        create_sql = (
            f'CREATE TABLE "{table_name}" (\n'
            f'  "Begin Time" TEXT NOT NULL,\n'
            f'  "Group" TEXT NOT NULL,\n'
            f'  PRIMARY KEY ("Begin Time", "Group")\n'
            f')'
        )
        cursor.execute(create_sql)
        for h in headers:
            if h in ("Begin Time", "Group"):
                continue
            safe_col = h.replace('"', '""')
            try:
                cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{safe_col}" TEXT')
            except sqlite3.OperationalError:
                pass
    else:
        cursor.execute(f'PRAGMA table_info("{table_name}")')
        existing_cols = {row[1] for row in cursor.fetchall()}
        for h in headers:
            if h not in existing_cols:
                safe_col = h.replace('"', '""')
                try:
                    cursor.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "{safe_col}" TEXT')
                except sqlite3.OperationalError:
                    pass

    quoted_headers = [f'"{h.replace(chr(34), chr(34)+chr(34))}"' for h in headers]
    placeholders = ", ".join(["?"] * len(headers))
    insert_sql = (
        f'INSERT OR REPLACE INTO "{table_name}" '
        f'({", ".join(quoted_headers)}) VALUES ({placeholders})'
    )

    row_count = 0
    batch = []
    for row in data:
        if len(row) < len(headers):
            row.extend([None] * (len(headers) - len(row)))
        elif len(row) > len(headers):
            row = row[:len(headers)]

        str_row = []
        for v in row:
            if v is None:
                str_row.append(None)
            else:
                str_row.append(str(v))
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


def process_and_upload_pm_data() -> int:
    """
    处理 Downloads 目录中的 PM xlsx 文件并上传数据库。
    参考 ran_kpi_precess.py 的逻辑。
    返回导入的总行数。
    """
    if openpyxl is None:
        print("[ERROR] 缺少 openpyxl，无法处理 xlsx 文件。请运行：pip install openpyxl")
        return 0

    print(f"\n[PROCESS] 开始处理 PM 数据...")
    print(f"  数据来源: {OUTPUT_DIR}")
    print(f"  数据库: {DB_PATH}")

    total_imported = 0
    files_to_delete = []

    for tech in TECHS:
        nw_prefix = f"{tech} OLIB Network KPIs_NW"
        region_prefix = f"{tech} OLIB Network KPIs_Region"
        table_name = f"{tech}_OLIB_Network_KPIs"

        nw_file = find_latest_xlsx(nw_prefix)
        region_file = find_latest_xlsx(region_prefix)

        print(f"\n[{tech}]")

        nw_headers = None
        nw_data = None
        if nw_file:
            files_to_delete.append(nw_file)
            print(f"  _NW: {os.path.basename(nw_file)}")
            nw_headers, nw_data = read_xlsx(nw_file)
            print(f"  _NW: {len(nw_data)} rows, {len(nw_headers)} cols")
            if "Group" not in nw_headers:
                nw_headers.append("Group")
                for row in nw_data:
                    row.append("G_NW")
            else:
                group_idx = nw_headers.index("Group")
                for row in nw_data:
                    row[group_idx] = "G_NW"
        else:
            print(f"  _NW: not found")

        rg_headers = None
        rg_data = None
        if region_file:
            files_to_delete.append(region_file)
            print(f"  _Region: {os.path.basename(region_file)}")
            rg_headers, rg_data = read_xlsx(region_file)
            print(f"  _Region: {len(rg_data)} rows, {len(rg_headers)} cols")
        else:
            print(f"  _Region: not found")

        if nw_headers is None and rg_headers is None:
            print(f"  [skip] no files found")
            continue

        if nw_headers and rg_headers:
            merged_headers = list(nw_headers)
            for h in rg_headers:
                if h not in merged_headers:
                    merged_headers.append(h)
        elif nw_headers:
            merged_headers = list(nw_headers)
        else:
            merged_headers = list(rg_headers)

        merged_data = []
        if nw_headers and nw_data:
            for row in nw_data:
                while len(row) < len(nw_headers):
                    row.append(None)
                new_row = []
                for h in merged_headers:
                    if h in nw_headers:
                        new_row.append(row[nw_headers.index(h)])
                    else:
                        new_row.append(None)
                merged_data.append(new_row)

        if rg_headers and rg_data:
            for row in rg_data:
                while len(row) < len(rg_headers):
                    row.append(None)
                new_row = []
                for h in merged_headers:
                    if h in rg_headers:
                        new_row.append(row[rg_headers.index(h)])
                    else:
                        new_row.append(None)
                merged_data.append(new_row)

        print(f"  merged: {len(merged_data)} rows, {len(merged_headers)} cols -> {table_name}")
        row_count = write_to_db(DB_PATH, table_name, merged_headers, merged_data)
        print(f"  written: {row_count} rows")
        total_imported += row_count

        nw_headers = nw_data = None
        rg_headers = rg_data = None
        merged_headers = merged_data = None
        gc.collect()

    # FTP 上传已移除（数据通过 API 写入远程）
    print("\n[INFO] FTP 上传已移除，数据由 my_app API 写入远程")

    # 清理已处理的 xlsx 文件
    print("\n[cleanup]")
    all_files = set(files_to_delete)
    for tech in TECHS:
        for suffix in ("_NW", "_Region"):
            pattern = os.path.join(OUTPUT_DIR, f"{tech} OLIB Network KPIs{suffix}*.xlsx")
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
                    print(f"  [warn] {os.path.basename(fpath)}: still locked")
                    import ctypes
                    ctypes.windll.kernel32.MoveFileExW(fpath, None, 0x4)
            except Exception as e:
                print(f"  [error] {os.path.basename(fpath)}: {e}")

    print(f"  total deleted: {deleted_count} files")
    return total_imported


def _run_single_pm_query(cookie: str, forgery_token: str, cfg: dict) -> str | None:
    """执行单个 PM 查询任务（用于多线程并行）。"""
    network_type = cfg["network_type"]
    suffix = cfg["suffix"]
    groupbygroup = cfg["groupbygroup"]
    # Group (groupbygroup=True) 对应 ran_kpi_precess.py 中的 _Region 文件
    file_suffix = "Region" if suffix == "Group" else suffix
    print(f"[MAIN] Starting PM history query [{network_type}/{suffix}] (groupbygroup={groupbygroup})...")

    pm_payload = build_pm_query_payload(
        network_type=network_type,
        groupbygroup=groupbygroup,
    )
    queryid = create_pm_history_query(cookie, forgery_token, pm_payload)
    pm_status = wait_pm_history_ready(cookie, forgery_token, queryid)
    print(f"[MAIN] PM query [{network_type}/{suffix}] ready: totalcount={pm_status.get('totalcount')}")

    filename = f"{network_type} OLIB Network KPIs_{file_suffix}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    saved_path = export_pm_history(
        cookie, forgery_token, queryid,
        filename=filename,
        output_path=os.path.join(OUTPUT_DIR, f"{filename}.xlsx"),
    )
    print(f"[MAIN] PM export [{network_type}/{suffix}] saved: {saved_path}")
    return saved_path


if __name__ == "__main__":
    start = time.time()
    print(f"[MAIN] RAN UME login started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    result = login()
    elapsed = time.time() - start
    print(f"[MAIN] Login completed in {elapsed:.2f} seconds")
    print(f"[MAIN] Cookie length: {len(result['cookie'])}")
    print(f"[MAIN] Forgery token length: {len(result['forgery_token'])}")

    # 登录成功后分别查询 2G/3G/TDD/FDD 的 Group 和 NW 八类历史指标
    pm_configs = [
        {"network_type": "2G", "groupbygroup": True, "suffix": "Group"},
        {"network_type": "2G", "groupbygroup": False, "suffix": "NW"},
        {"network_type": "3G", "groupbygroup": True, "suffix": "Group"},
        {"network_type": "3G", "groupbygroup": False, "suffix": "NW"},
        {"network_type": "TDD", "groupbygroup": True, "suffix": "Group"},
        {"network_type": "TDD", "groupbygroup": False, "suffix": "NW"},
        {"network_type": "FDD", "groupbygroup": True, "suffix": "Group"},
        {"network_type": "FDD", "groupbygroup": False, "suffix": "NW"},
    ]

    print(f"[MAIN] Starting PM queries with max {MAX_PARALLEL_WORKERS} parallel workers...")
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_WORKERS) as executor:
        future_to_cfg = {
            executor.submit(_run_single_pm_query, result["cookie"], result["forgery_token"], cfg): cfg
            for cfg in pm_configs
        }
        for future in as_completed(future_to_cfg):
            cfg = future_to_cfg[future]
            try:
                future.result()
            except Exception as e:
                print(f"[MAIN] PM query [{cfg['network_type']}/{cfg['suffix']}] failed: {e}")

    # 处理下载的 xlsx 文件并上传数据库
    total_imported = process_and_upload_pm_data()

    total_elapsed = time.time() - start
    print(f"[MAIN] Total completed in {total_elapsed:.2f} seconds")
    print(f"[MAIN] Total imported rows: {total_imported}")
