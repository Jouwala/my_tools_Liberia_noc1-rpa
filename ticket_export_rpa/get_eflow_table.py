"""
eFlow TT Data Fetcher
从 ZTE 网管系统获取 eFlow TT 工单列表数据
使用原始 socket + SSL（绕过 requests/urllib3 的 TLS 兼容问题）
支持自动登录获取鉴权 Cookie
"""

import ssl
import socket
import sys
import json
import time
import os
import re
import base64
import sqlite3
import glob
from datetime import datetime, timezone


try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HOST = "10.100.20.8"
PORT = 28001
TT_API_PATH = "/api/eflow-ticket/v1/eflow-tt/base/list"
WO_API_PATH = "/api/eflow-wo/v1/eflow-wo/base/list"
CR_API_PATH = "/api/eflow-asset/v1/eflow-cr/base/list"
PM_API_PATH = "/api/eflow-pm/v1/eflow-pm-task/base/list"
SITE_API_PATH = "/api/cmdb/v1/data/search/Site"
PERSON_API_PATH = "/api/cmdb/v1/data/search/Person"

USERNAME = "admin"
PASSWORD = "Brysj*8*"

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

SESSION_COOKIE = ""
FORGERY_TOKEN = ""


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


def _http_request(method, path, headers_extra=None, body=None):
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

    return status_line, resp_headers, header_part, resp_body


FALLBACK_COOKIE = (
    "X-Rm-Data-Version-zenap=1773367620002_0_0_0_0_0_0_0_0; "
    "Z-AUTH-CODE-28001=1154983705_f188b025b7b64878ae0f4511e90ab1a2; "
    "x-dexmesh-user-28001=D86935A99B38A02CDAEA05C225E9303A21FA22B872499884D7B2A1E26A5645FE; "
    "forgerydefense-28001=cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"
)
FALLBACK_FORGERY = "cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"


def login():
    global SESSION_COOKIE, FORGERY_TOKEN

    print("[LOGIN] Starting authentication...")

    try:
        print("[LOGIN] Step 1: Getting authorize page...")
        status, hdrs, raw_hdrs, body = _http_request(
            "GET",
            "/api/oauth2/v1/authorize?scope=user.login&response_type=code&redirect_uri=/uportal/framework/default.html"
        )
        print(f"[LOGIN] Status: {status}")

        init_cookies = []
        forgery_token = ""
        for line in raw_hdrs.split("\r\n"):
            if line.lower().startswith("set-cookie:"):
                cookie_val = line.split(": ", 1)[1].split(";")[0]
                if cookie_val.split("=")[1]:
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

        if "200" in status:
            pk_data = json.loads(body.decode('utf-8'))
            public_key_b64 = pk_data.get("rsaPublicKey", "")
            print(f"[LOGIN] Got rsaPublicKey ({len(public_key_b64)} chars)")
        else:
            print("[LOGIN] API failed, using HTML embedded key")

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
            f"Referer: https://{HOST}:{PORT}/api/oauth2/v1/authorize?scope=user.login&response_type=code&redirect_uri=/uportal/framework/default.html\r\n"
            f"X-Requested-With: XMLHttpRequest\r\n"
        )
        if forgery_token:
            login_headers += f"forgerydefense: {forgery_token}\r\n"

        status, hdrs, raw_hdrs, body = _http_request(
            "POST",
            "/api/oauth2/v1/login_rsa",
            headers_extra=login_headers,
            body=login_payload,
        )
        print(f"[LOGIN] Login status: {status}")

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

        SESSION_COOKIE = "; ".join(cookies)
        FORGERY_TOKEN = forgery_token

        resp_text = body.decode('utf-8', errors='replace')
        if "302" in status or "default.html" in resp_text or len(cookies) > 3:
            print(f"[LOGIN] SUCCESS - {len(cookies)} cookies")
        else:
            print(f"[LOGIN] Response: {resp_text[:300]}")
            if not any("Z-AUTH-CODE" in c for c in cookies):
                raise Exception("Login failed - no auth cookie obtained")

        print(f"[LOGIN] Cookie: {SESSION_COOKIE[:100]}...")

    except Exception as e:
        print(f"[LOGIN] FAILED: {e}")
        print("[LOGIN] Falling back to hardcoded cookies...")
        SESSION_COOKIE = FALLBACK_COOKIE
        FORGERY_TOKEN = FALLBACK_FORGERY

    return SESSION_COOKIE


def _rsa_encrypt_pem(plaintext, public_key_b64):
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives import serialization

    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
    public_key = serialization.load_pem_public_key(pem.encode())

    encrypted = public_key.encrypt(
        plaintext.encode('utf-8'),
        asym_padding.PKCS1v15()
    )
    return base64.b64encode(encrypted).decode('ascii')


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


TT_FIELDS = "color,woId,procId,opName,pendingStatus,displayName,woNum,woInfo,status,ttSource,ticketType,projectName,templateName,creator,creatorContactInfo,ticketSeverity,createTime,alarmCategory,alarmSubcategory,alarmSeverity,alarmType,alarmId,alarmCode,subAlarmName,subAlarmNeName,subAlarmNeNaIp,appendingAlarmName,appendingAlarmNeName,appendingAlarmNeIp,netWorkType,neName,neId,neIP,impactedServiceOrNo,impactedServiceWireless,siteOutageOrNo,reasonType,slaTotalDuration,slaStatus,remainingTime,targetFinishTime,groupSlaTime,groupSlaStatus,groupSlaRemainsTime,regionLevel1Name,regionLevel2Name,assetName,siteId,assetType,siteClass,lastModifiedTime,candidateOperator,vendor,alarmOccurTime,alarmClearTime,faultDurationTime"

TT_STATUS_FILTER = '((status eq "WaitFOAccept") or (status eq "WaitFOProcess") or (status eq "WaitBOAccept") or (status eq "WaitBOProcess") or (status eq "WaitThirdAccept") or (status eq "WaitThirdProcess") or (status eq "WaitConfirm") or (status eq "Closed") or (status eq "Draft"))'

TIME_FILTER_TEMPLATE = '{status_filter} and (lastModifiedTime ge {start_ms}) and (lastModifiedTime le {end_ms})'

TT_PAYLOAD_BASE = {
    "customInfo": {"pageType": "allTicket"},
    "field": TT_FIELDS,
    "order": "lastModifiedTime desc",
    "relationFilter": {"eflow_ticket_ticket_asset_all": ""},
    "eflow_ticket_ticket_asset_all": "",
}

TT_REFERER = f"https://{HOST}:{PORT}/iui/ticket-mgt/v1/"


WO_FIELDS = "woId,procId,opName,ttWoid,pendingStatus,woNum,parentwoNum,status,displayName,creator,createTime,lastModifiedTime,candidateOperator,siteId,ticketSeverity,spareDomain,neName,neType,neIp,vendor,subSource,alarmOccurTime,alarmClearTime,expectedFinishTime,source,projectName,templateName,creatorContactInfo,alarmCategory,alarmSubcategory,alarmSeverity,reasonType,alarmId,alarmCode,subAlarmName,subAlarmNEName,subAlarmNEIP,appendingAlarmName,appendingAlarmNEName,appendingAlarmNEIP,networkType,neId,impactedServiceOrNo,impactedService,siteOutageOrNo,aiMindFailReasonType,faultDurationTime,slaTotalDuration,slaStatus,remainingTime,targetFinishTime,groupSlaTime,groupSlaStatus,groupSlaRemainsTime,groupSlaDeadlineTime,rcaFillingMode,regionLevel1Name,regionLevel2Name,assetName,assetType,siteClass,spareRequired,spareavailable,rejectCategory,etc,arriveSiteTime,travelTime"

WO_STATUS_FILTER = '((status eq "WaitAccept") or (status eq "WaitStartTrip") or (status eq "WaitArriveSite") or (status eq "WaitProcess") or (status eq "WaitConfirm") or (status eq "WaitLeaveSite") or (status eq "WaitSPApplication") or (status eq "WaitBONPOProcess") or (status eq "PhasedReply") or (status eq "Closed") or (status eq "Draft"))'

WO_PAYLOAD_BASE = {
    "customInfo": {"pageType": "allTicket"},
    "field": WO_FIELDS,
    "order": "lastModifiedTime desc",
    "relationFilter": {"eflow_wo_wo_asset": ""},
}

WO_REFERER = f"https://{HOST}:{PORT}/iui/wo-mgt/v1/"


CR_FIELDS = "woId,procId,opName,woNum,status,changeType,displayName,creator,requesterWorkGroupName,createTime,candidateOperator,mopMaker,mopChecker,ipRelatedActivity,implementer,implementResult,plannedStartTime,plannedEndTime,actualImplementationStartTime,actualImplementationEndTime,downtimeStart,downtimeEnd,rollbackStartTime,rollbackEndTime,closeTime,lastModifiedTime"

CR_STATUS_FILTER = '((status eq "WaitL1Approve") or (status eq "WaitL2Approve") or (status eq "WaitL3Approve") or (status eq "WaitL4Approve") or (status eq "WaitL5Approve") or (status eq "WaitL6Approve") or (status eq "WaitL7Approve") or (status eq "WaitL8Approve") or (status eq "WaitImplement") or (status eq "Implementing") or (status eq "PhaseUpdate") or (status eq "WaitUpdate") or (status eq "Closed") or (status eq "Canceled") or (status eq "Draft"))'

CR_PAYLOAD_BASE = {
    "customInfo": {"pageType": "allTicket"},
    "field": CR_FIELDS,
    "order": "lastModifiedTime desc",
    "length": 50,
}

CR_REFERER = f"https://{HOST}:{PORT}/iui/am-mgt/v1/"


PM_FIELDS = "woId,procId,opName,ftpFilePath,woNum,status,displayName,serviceClassification,creator,createTime,lastModifiedTime,candidateOperator,pmManagerRealName,assetName,assetId,source,parentWoNum,planBeginTime,planEndTime,templateName,filename,pmContentCompletedNum,pmContentTotalNum,pmtOverdue"

PM_STATUS_FILTER = '((status eq "Scheduling") or (status eq "WaitAccept") or (status eq "WaitProcess") or (status eq "Transfer") or (status eq "WaitReProcess") or (status eq "WaitPMManagerApprove") or (status eq "WaitFLMLeaderApprove") or (status eq "Draft") or (status eq "Closed"))'

PM_PAYLOAD_BASE = {
    "customInfo": {"pageType": "allTicket"},
    "field": PM_FIELDS,
    "order": "lastModifiedTime desc",
    "relationFilter": {"eflow_pm_task_asset": ""},
    "length": 200,
}

PM_REFERER = f"https://{HOST}:{PORT}/iui/pm-mgt/v1/"


SITE_PAYLOAD_BASE = {
    "limit": 10,
    "skip": 0,
    "sort": {"cmdb#create-time": False},
    "callScene": "ui",
}

SITE_REFERER = f"https://{HOST}:{PORT}/iui/cmdb/"


PERSON_PAYLOAD_BASE = {
    "limit": 10,
    "skip": 0,
    "sort": {"cmdb#create-time": False},
    "callScene": "ui",
}

PERSON_REFERER = f"https://{HOST}:{PORT}/iui/cmdb/"


def _get_time_range_ms():
    start_dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
    return int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)


def fetch_paginated_data(api_path, payload_base, referer, label, page_param="start", size_param="length"):
    print(f"[INFO] Fetching {label} data...")

    start_time = time.time()

    all_rows = []
    total = None
    page_size = payload_base.get(size_param, 2000)
    start = 0

    headers_extra = (
        f"Cookie: {SESSION_COOKIE}\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Referer: {referer}\r\n"
        f"forgerydefense: {FORGERY_TOKEN}\r\n"
        f"Content-Type: application/json\r\n"
        f"Origin: https://{HOST}:{PORT}\r\n"
    )

    while True:
        payload = dict(payload_base)
        payload[size_param] = page_size
        payload[page_param] = start

        body = json.dumps(payload)
        status_line, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", api_path, headers_extra=headers_extra, body=body,
        )

        print(f"[INFO] {label} page {page_param}={start}: {len(resp_body)} bytes, {status_line}")

        data = json.loads(resp_body.decode('utf-8'))

        if isinstance(data, list):
            rows = data
            print(f"[INFO] {label} page {page_param}={start}: {len(rows)} records")
            all_rows.extend(rows)
            print(f"[INFO] {label} collected {len(all_rows)} records")
            if len(rows) < page_size:
                break
            start += page_size
            continue

        if not isinstance(data, dict):
            print(f"[WARN] Unexpected response type: {type(data)}")
            break

        if data.get("code") not in (0, None, "0"):
            print(f"[WARN] API error code={data.get('code')}, msg={data.get('msg', '')[:100]}")
            break

        if total is None:
            total = data.get("total", 0)
            print(f"[INFO] {label} total records: {total}")

        rows = parse_response(data, label=label)
        if not isinstance(rows, list):
            rows = []

        all_rows.extend(rows)
        print(f"[INFO] {label} collected {len(all_rows)}/{total} records")

        if len(all_rows) >= total or len(rows) < page_size:
            break

        start += page_size

        if start >= total:
            break

    elapsed = time.time() - start_time
    print(f"[INFO] {label} API: {elapsed:.2f}s, {len(all_rows)} records total")

    return all_rows


def fetch_eflow_tt_data(payload_base=TT_PAYLOAD_BASE):
    return fetch_paginated_data(TT_API_PATH, payload_base, TT_REFERER, "eFlow TT")


def fetch_eflow_wo_data(payload_base=WO_PAYLOAD_BASE):
    return fetch_paginated_data(WO_API_PATH, payload_base, WO_REFERER, "eFlow WO")


def fetch_eflow_cr_data(payload_base=CR_PAYLOAD_BASE):
    return fetch_paginated_data(CR_API_PATH, payload_base, CR_REFERER, "eFlow CR")


def fetch_eflow_pm_data(payload_base=PM_PAYLOAD_BASE):
    return fetch_paginated_data(PM_API_PATH, payload_base, PM_REFERER, "eFlow PM")


def fetch_site_data(payload_base=SITE_PAYLOAD_BASE):
    return fetch_paginated_data(SITE_API_PATH, payload_base, SITE_REFERER, "Site", page_param="skip", size_param="limit")


def fetch_person_data(payload_base=PERSON_PAYLOAD_BASE):
    return fetch_paginated_data(PERSON_API_PATH, payload_base, PERSON_REFERER, "Person", page_param="skip", size_param="limit")


def parse_response(data, label=""):
    prefix = f"[{label}] " if label else ""
    if isinstance(data, dict):
        if data.get("code") not in (0, None, "0"):
            print(f"{prefix}[WARN] API error code={data.get('code')}, msg={data.get('msg', '')[:100]}")
            return []
        # 尝试常见的数据键名
        rows = None
        for key in ("result", "data", "records", "list", "rows", "items"):
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

    if not rows:
        print(f"{prefix}[WARN] No data.")
        return []

    if isinstance(rows, list):
        print(f"{prefix}[INFO] {len(rows)} records")
    return rows


def _write_sheet(writer, df, sheet_name):
    import pandas as pd
    from openpyxl.styles import PatternFill, Font

    df.to_excel(writer, index=False, sheet_name=sheet_name)
    ws = writer.sheets[sheet_name]

    for col_idx, col in enumerate(df.columns, 1):
        max_len = max(
            len(str(col)),
            df[col].astype(str).str.len().max() if len(df) > 0 else 0,
        )
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 50)

    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    for col_idx in range(1, len(df.columns) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font


def _table_name(sheet_name):
    return sheet_name.replace(" ", "_").lower()


def save_to_sqlite(sheets_data):
    import pandas as pd

    db_path = os.path.join(OUTPUT_DIR, "eflow.sqlite3")
    conn = sqlite3.connect(db_path)

    for sheet_name, rows in sheets_data:
        if not isinstance(rows, list) or not rows:
            print(f"[SKIP] {sheet_name}: no data")
            continue
        df = pd.DataFrame(rows)
        # SQLite 不支持 list/dict 类型，转换为 JSON 字符串
        for col in df.columns:
            if df[col].apply(lambda x: isinstance(x, (list, dict))).any():
                df[col] = df[col].apply(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else x)
        table = _table_name(sheet_name)
        df.to_sql(table, conn, if_exists="replace", index=False)
        print(f"[INFO] SQLite table '{table}': {len(df)} rows, {len(df.columns)} columns")

    conn.close()
    print(f"[INFO] SQLite saved: {db_path}")
    return db_path


def write_excel_from_sqlite(sheets_data):
    import pandas as pd

    db_path = os.path.join(OUTPUT_DIR, "eflow.sqlite3")
    conn = sqlite3.connect(db_path)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(OUTPUT_DIR, f"eflow_{timestamp}.xlsx")

    seq = 1
    while os.path.exists(output_file):
        output_file = os.path.join(OUTPUT_DIR, f"eflow_{timestamp}_{seq}.xlsx")
        seq += 1

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        for sheet_name, _ in sheets_data:
            table = _table_name(sheet_name)
            df = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
            if df.empty:
                print(f"[SKIP] {sheet_name}: no data")
                continue
            _write_sheet(writer, df, sheet_name)
            print(f"[INFO] Excel {sheet_name}: {len(df)} rows, {len(df.columns)} columns")

    conn.close()
    print(f"[INFO] Excel saved: {output_file}")

    # 删除旧 Excel 文件，只保留最新
    for old_file in glob.glob(os.path.join(OUTPUT_DIR, "eflow_*.xlsx")):
        if os.path.abspath(old_file) != os.path.abspath(output_file):
            try:
                os.remove(old_file)
                print(f"[CLEAN] Deleted old file: {os.path.basename(old_file)}")
            except OSError:
                print(f"[WARN] Cannot delete (in use): {os.path.basename(old_file)}")

    return output_file


def main():
    import pandas as pd

    start_time = time.time()
    print("=" * 60)
    print(f"eFlow TT Fetcher - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    login()

    try:
        start_ms, end_ms = _get_time_range_ms()
        print(f"[INFO] Time range: {start_ms} to {end_ms}")

        tt_payload = dict(TT_PAYLOAD_BASE)
        tt_payload["filter"] = TIME_FILTER_TEMPLATE.format(status_filter=TT_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)
        tt_rows = fetch_eflow_tt_data(payload_base=tt_payload)

        wo_payload = dict(WO_PAYLOAD_BASE)
        wo_payload["filter"] = TIME_FILTER_TEMPLATE.format(status_filter=WO_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)
        wo_rows = fetch_eflow_wo_data(payload_base=wo_payload)

        cr_payload = dict(CR_PAYLOAD_BASE)
        cr_payload["filter"] = TIME_FILTER_TEMPLATE.format(status_filter=CR_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)
        cr_rows = fetch_eflow_cr_data(payload_base=cr_payload)

        pm_payload = dict(PM_PAYLOAD_BASE)
        pm_payload["filter"] = TIME_FILTER_TEMPLATE.format(status_filter=PM_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)
        pm_rows = fetch_eflow_pm_data(payload_base=pm_payload)

        site_rows = fetch_site_data()
        person_rows = fetch_person_data()

        sheets_data = [
            ("eFlow TT", tt_rows),
            ("eFlow WO", wo_rows),
            ("eFlow CR", cr_rows),
            ("eFlow PM", pm_rows),
            ("Site", site_rows),
            ("Person", person_rows),
        ]
        save_to_sqlite(sheets_data)
        write_excel_from_sqlite(sheets_data)

    except Exception as e:
        import traceback
        print(f"[ERROR] {e}")
        traceback.print_exc()

    total_elapsed = time.time() - start_time
    print(f"\n[DONE] Completed in {total_elapsed:.2f}s")


if __name__ == "__main__":
    main()
