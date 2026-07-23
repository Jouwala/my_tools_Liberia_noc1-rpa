"""
eFlow Active & History Alarm Fetcher
从 ZTE FM Active 告警接口获取实时告警数据
从 ZTE FM History 告警接口获取近 7 天历史告警数据
使用原始 socket + SSL（绕过 requests/urllib3 的 TLS 兼容问题）
支持自动登录获取鉴权 Cookie
实时告警写入 eflow_alarm_raw.csv / realtime_alarm
历史告警写入 eflow_history_alarm_raw.csv / history_alarm
"""

import ssl
import socket
import sys
import json
import time
import os
import re
import base64
import uuid
import csv
import sqlite3
from datetime import datetime, timezone


try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

HOST = "10.100.20.8"
PORT = 28001
ALARM_API_PATH = "/api/fm-active/v1/activealarms/table"
HIS_ALARM_API_PATH = "/api/fm-history/v1/hisalarms/pageinfo"

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

        public_key_b64 = ""
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
        raise

    return SESSION_COOKIE


ALARM_REFERER = f"https://{HOST}:{PORT}/iui/fm/angularFm/dist/index.html"

# 实时/历史告警共用 alarmcodeconds，保证过滤条件一致。
ALARM_CODE_CONDS = [
    #{"restype": "zte.ran.itbbu", "alarmcode": 198097062},
    {"restype": "zte.ran.nodeb", "alarmcode": 99933},
    {"restype": "zte.ran.bts", "alarmcode": 9920},
    {"restype": "zte.ran.enodeb", "alarmcode": 9920},
    {"restype": "zte.ran.nodeb", "alarmcode": 9920},
    {"restype": "zte.ran.nodeb", "alarmcode": 9995},
    {"restype": "zte.ran.bts", "alarmcode": 9981},
    {"restype": "zte.ran.nodeb", "alarmcode": 9991},
    {"restype": "zte.ran.nodeb", "alarmcode": 9990},
    {"restype": "zte.ran.enodeb", "alarmcode": 9970},
    {"restype": "zte.ran.enodeb", "alarmcode": 9971},
    {"restype": "zte.ran.bts", "alarmcode": 9910},
    {"restype": "zte.ran.enodeb", "alarmcode": 9910},
    {"restype": "zte.ran.nodeb", "alarmcode": 9910},
    {"restype": "zte.ran.bts", "alarmcode": 9980},
    {"restype": "ZTE_TRM_DWDM_ZXONE_9700", "alarmcode": 4758},
    {"restype": "ZTE_TRM_OTHER_WL_LINK", "alarmcode": 4758},
    #{"restype": "zte.ran.sdr", "alarmcode": 198097062},
]

# FM Active Alarm 查询条件：按浏览器实际请求构造。
ALARM_CONDITION = {
    "alarmcodeconds": ALARM_CODE_CONDS,
    "alarmcodefiltermode": 0,
    "visibles": [1],
    "timezonetype": 0,
    "sortinfo": {"sortdirection": 0, "sortfield": "servertime", "combinesortinfos": []},
    "extensionconds": {"maintainstatus": {"valuelist": ["0"]}},
    "querymetype": 2,
    "refresh": True,
}

# FM History Alarm 查询条件：固定时间范围 2026-07-16 00:00:00 至 2026-07-23 23:59:59（UTC）。
HIS_ALARM_START = datetime(2026, 7, 16, 0, 0, 0, tzinfo=timezone.utc)
HIS_ALARM_END = datetime(2026, 7, 23, 23, 59, 59, tzinfo=timezone.utc)

HIS_ALARM_CONDITION = {
    "alarmraisedtime": {"mode": "0", "start": -1, "end": -1},
    "alarmcodefiltermode": 0,
    "alarmcodeconds": ALARM_CODE_CONDS,
    "querymetype": 0,
    "timezonetype": 0,
    "sortinfo": {"language": "en", "sortdirection": 0, "sortfield": "alarmclearedtime", "combinesortinfos": []},
    "extensionconds": {"maintainstatus": {"valuelist": ["0"]}},
    "usefromsize": True,
}

ALARM_COLUMNS = [
    "Site Status",
    "Networktype",
    "Alarm Source",
    "Site Name",
    "neip",
    "restypename",
    "RAN Site Type",
    "MW Layer",
    "Vendor",
    "Power Infomation",
    "Transmission Type",
    "Site ID",
    "Site Attribute",
    "TT ID",
    "durationname",
    "codename",
    "Alarm Title",
    "Region",
    "link",
    "perceivedseverityname",
    "reasonname",
    "POP Site",
    "clearstatename",
    "Circle",
    "Site Class",
    "Type",
    "Link Path",
    "Site VIP Level",
    "Cell Name",
    "Assign RuleName",
    "RAN Type",
    "Latest Match Time",
    "First Match Time",
    "Assign Delay",
    "rootcount",
    "auxiliarycount",
]


def _new_query_id():
    return "T" + uuid.uuid4().hex


def _new_tab_id():
    return "fm-active_" + uuid.uuid4().hex


def parse_response(data, label=""):
    prefix = f"[{label}] " if label else ""
    print(f"{prefix}[DEBUG] Response type: {type(data)}")
    if isinstance(data, dict):
        print(f"{prefix}[DEBUG] Response keys: {list(data.keys())}")
        if data.get("code") not in (0, None, "0"):
            print(f"{prefix}[WARN] API error code={data.get('code')}, msg={data.get('msg', '')[:100]}")
            return []
        rows = None
        for key in ("alarms", "result", "data", "records", "list", "rows", "items"):
            rows = data.get(key)
            if rows is not None:
                print(f"{prefix}[DEBUG] Found key '{key}', type: {type(rows)}")
                break
        else:
            rows = []
        if isinstance(rows, dict):
            print(f"{prefix}[DEBUG] Nested keys: {list(rows.keys())}")
            nested_rows = None
            for key in ("alarms", "data", "list", "records", "rows", "items", "result"):
                nested_rows = rows.get(key)
                if nested_rows is not None:
                    print(f"{prefix}[DEBUG] Found nested key '{key}', type: {type(nested_rows)}")
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


def _normalize_alarm_rows(rows):
    """将 FM Active Alarm 的字段对象转换为以 columnname 为键、value 为值的字典列表。"""
    if not isinstance(rows, list):
        return rows

    normalized = []
    for row in rows:
        if isinstance(row, dict):
            new_row = {}
            for k, v in row.items():
                if isinstance(v, dict) and "columnname" in v:
                    col_name = v.get("columnname") or k
                    new_row[col_name] = v.get("value")
                else:
                    new_row[k] = v
            normalized.append(new_row)
        elif isinstance(row, list):
            new_row = {}
            for item in row:
                if isinstance(item, dict) and "columnname" in item:
                    col_name = item.get("columnname")
                    if col_name:
                        new_row[col_name] = item.get("value")
            normalized.append(new_row)
        else:
            normalized.append(row)
    return normalized


def _filter_rows_with_tt_id(rows):
    """过滤保留 TT ID 不为空且不为 '-' 的记录。"""
    if not isinstance(rows, list):
        return rows
    filtered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        tt_id = row.get("TT ID", "")
        if isinstance(tt_id, str):
            tt_id = tt_id.strip()
        if tt_id and tt_id != "-":
            filtered.append(row)
    return filtered


def fetch_alarm_data():
    print("[INFO] Fetching active alarm data...")
    start_time = time.time()

    all_rows = []
    total = None
    page_size = 200
    page = 1

    headers_extra = (
        f"Cookie: {SESSION_COOKIE}\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Referer: {ALARM_REFERER}\r\n"
        f"forgerydefense: {FORGERY_TOKEN}\r\n"
        f"Content-Type: application/json\r\n"
        f"Origin: https://{HOST}:{PORT}\r\n"
        f"LogTracking: True\r\n"
    )

    query_id = _new_query_id()
    active_tab_id = _new_tab_id()

    while True:
        now = datetime.now(timezone.utc)
        payload = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}"[:-3] + "Z",
            "condition": ALARM_CONDITION,
            "manual": False,
            "page": page,
            "pagesize": page_size,
            "queryid": query_id,
            "activeTabId": active_tab_id,
        }

        body = json.dumps(payload)
        status_line, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", ALARM_API_PATH, headers_extra=headers_extra, body=body,
        )

        print(f"[INFO] Alarm page={page}: {len(resp_body)} bytes, {status_line}")
        if len(resp_body) < 500:
            print(f"[DEBUG] Response body: {resp_body.decode('utf-8', errors='replace')}")

        data = json.loads(resp_body.decode('utf-8'))

        if isinstance(data, list):
            rows = _normalize_alarm_rows(data)
            print(f"[INFO] Alarm page={page}: {len(rows)} records")
            all_rows.extend(rows)
            print(f"[INFO] Alarm collected {len(all_rows)} records")
            if len(rows) < page_size:
                break
            page += 1
            continue

        if not isinstance(data, dict):
            print(f"[WARN] Unexpected response type: {type(data)}")
            break

        if data.get("code") not in (0, None, "0"):
            print(f"[WARN] API error code={data.get('code')}, msg={data.get('msg', '')[:100]}")
            break

        if total is None:
            total = data.get("totalcount") or data.get("total", 0)
            print(f"[INFO] Alarm total records: {total}")

        rows = parse_response(data, label="Alarm")
        if not isinstance(rows, list):
            rows = []

        rows = _normalize_alarm_rows(rows)
        all_rows.extend(rows)
        print(f"[INFO] Alarm collected {len(all_rows)} records")

        if len(rows) < page_size:
            break

        page += 1

        if page > 500:
            print("[WARN] Reached max page limit (500), stopping pagination")
            break

    elapsed = time.time() - start_time
    print(f"[INFO] Alarm API: {elapsed:.2f}s, {len(all_rows)} records total")

    return all_rows


def fetch_history_alarm_data():
    print("[INFO] Fetching history alarm data...")
    start_time = time.time()

    all_rows = []
    total = None
    page_size = 2000
    offset = 0

    headers_extra = (
        f"Cookie: {SESSION_COOKIE}\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Referer: {ALARM_REFERER}\r\n"
        f"forgerydefense: {FORGERY_TOKEN}\r\n"
        f"Content-Type: application/json\r\n"
        f"Origin: https://{HOST}:{PORT}\r\n"
        f"LogTracking: True\r\n"
    )

    while True:
        now = datetime.now(timezone.utc)
        now_ms = int(now.timestamp() * 1000)
        iso_ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}"[:-3] + "Z"

        condition = dict(HIS_ALARM_CONDITION)
        condition["alarmraisedtime"] = {
            "mode": "0",
            "start": int(HIS_ALARM_START.timestamp() * 1000),
            "end": int(HIS_ALARM_END.timestamp() * 1000),
        }
        # usefromsize 表示后端支持 from/size 分页
        condition["from"] = offset
        condition["size"] = page_size

        payload = {
            "querynum": page_size,
            "condition": condition,
            "timestamp": iso_ts,
            "manual": True,
        }

        body = json.dumps(payload)
        path = f"{HIS_ALARM_API_PATH}?timestamp={now_ms}"
        status_line, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", path, headers_extra=headers_extra, body=body,
        )

        print(f"[INFO] History alarm offset={offset}: {len(resp_body)} bytes, {status_line}")
        if len(resp_body) < 500:
            print(f"[DEBUG] Response body: {resp_body.decode('utf-8', errors='replace')}")

        data = json.loads(resp_body.decode('utf-8'))

        if not isinstance(data, dict):
            print(f"[WARN] Unexpected history response type: {type(data)}")
            break

        if data.get("code") not in (0, None, "0"):
            print(f"[WARN] History API error code={data.get('code')}, msg={data.get('msg', '')[:100]}")
            break

        if total is None:
            total = data.get("totalcount") or data.get("total", 0)
            print(f"[INFO] History alarm total records: {total}")

        rows = parse_response(data, label="History")
        if not isinstance(rows, list):
            rows = []

        rows = _normalize_alarm_rows(rows)
        if not rows:
            break

        # 防止分页参数无效导致重复拉取同一页
        prev_count = len(all_rows)
        all_rows.extend(rows)
        print(f"[INFO] History alarm collected {len(all_rows)} records")
        if len(all_rows) == prev_count:
            print("[WARN] No new records, stopping pagination")
            break

        if len(rows) < page_size:
            break

        offset += page_size
        if offset > 100000:
            print("[WARN] Reached max history offset limit (100000), stopping pagination")
            break

    elapsed = time.time() - start_time
    print(f"[INFO] History Alarm API: {elapsed:.2f}s, {len(all_rows)} records total")

    return all_rows


def write_raw_csv(data):
    """将规范化后的原始告警数据写入 CSV，只保留最新一个文件。"""
    output_file = os.path.join(OUTPUT_DIR, "eflow_alarm_raw.csv")

    if not isinstance(data, list) or not data:
        print("[SKIP] Raw CSV: no data")
        return output_file

    fieldnames = sorted(set().union(*(row.keys() for row in data)))
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)

    print(f"[INFO] Raw CSV saved: {output_file}, {len(data)} records")
    return output_file


def write_to_sqlite(data):
    """过滤指定字段并替换写入 eflow.sqlite3 的 realtime_alarm 表。"""
    db_file = os.path.join(OUTPUT_DIR, "eflow.sqlite3")

    if not isinstance(data, list) or not data:
        print("[SKIP] SQLite: no data")
        return db_file

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    col_defs = ", ".join([f'"{col}" TEXT' for col in ALARM_COLUMNS])
    cursor.execute(f"CREATE TABLE IF NOT EXISTS realtime_alarm ({col_defs})")

    cursor.execute("DELETE FROM realtime_alarm")

    rows_to_insert = []
    for row in data:
        filtered = tuple(row.get(col, "") for col in ALARM_COLUMNS)
        rows_to_insert.append(filtered)

    placeholders = ", ".join(["?" for _ in ALARM_COLUMNS])
    cols = ", ".join([f'"{col}"' for col in ALARM_COLUMNS])
    cursor.executemany(
        f"INSERT INTO realtime_alarm ({cols}) VALUES ({placeholders})",
        rows_to_insert,
    )

    conn.commit()
    conn.close()

    print(f"[INFO] SQLite saved: {db_file}, {len(rows_to_insert)} records")
    return db_file


def write_history_raw_csv(data):
    """将规范化后的历史告警原始数据写入 CSV，只保留最新一个文件。"""
    output_file = os.path.join(OUTPUT_DIR, "eflow_history_alarm_raw.csv")

    if not isinstance(data, list) or not data:
        print("[SKIP] History Raw CSV: no data")
        return output_file

    fieldnames = sorted(set().union(*(row.keys() for row in data)))
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)

    print(f"[INFO] History Raw CSV saved: {output_file}, {len(data)} records")
    return output_file


def write_history_to_sqlite(data):
    """过滤指定字段并替换写入 eflow.sqlite3 的 history_alarm 表。"""
    db_file = os.path.join(OUTPUT_DIR, "eflow.sqlite3")

    if not isinstance(data, list) or not data:
        print("[SKIP] History SQLite: no data")
        return db_file

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    col_defs = ", ".join([f'"{col}" TEXT' for col in ALARM_COLUMNS])
    cursor.execute(f"CREATE TABLE IF NOT EXISTS history_alarm ({col_defs})")

    cursor.execute("DELETE FROM history_alarm")

    rows_to_insert = []
    for row in data:
        filtered = tuple(row.get(col, "") for col in ALARM_COLUMNS)
        rows_to_insert.append(filtered)

    placeholders = ", ".join(["?" for _ in ALARM_COLUMNS])
    cols = ", ".join([f'"{col}"' for col in ALARM_COLUMNS])
    cursor.executemany(
        f"INSERT INTO history_alarm ({cols}) VALUES ({placeholders})",
        rows_to_insert,
    )

    conn.commit()
    conn.close()

    print(f"[INFO] History SQLite saved: {db_file}, {len(rows_to_insert)} records")
    return db_file


def main():
    start_time = time.time()
    print("=" * 60)
    print(f"eFlow Active & History Alarm Fetcher - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    login()

    try:
        alarm_rows = fetch_alarm_data()
        write_raw_csv(alarm_rows)
        write_to_sqlite(alarm_rows)
    except Exception as e:
        print(f"[ERROR] Active alarm failed: {e}")

    try:
        history_rows = fetch_history_alarm_data()
        write_history_raw_csv(history_rows)
        filtered_history_rows = _filter_rows_with_tt_id(history_rows)
        print(
            f"[INFO] History alarm filtered: {len(history_rows)} -> {len(filtered_history_rows)} "
            f"(removed {len(history_rows) - len(filtered_history_rows)} rows with empty/invalid TT ID)"
        )
        write_history_to_sqlite(filtered_history_rows)
    except Exception as e:
        print(f"[ERROR] History alarm failed: {e}")

    total_elapsed = time.time() - start_time
    print(f"\n[DONE] Completed in {total_elapsed:.2f}s")


if __name__ == "__main__":
    main()
