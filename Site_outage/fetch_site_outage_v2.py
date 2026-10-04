"""
Site Outage Data Fetcher v2
从 ZTE 网管系统获取 Region Site Down 数据并写入 Excel
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
from datetime import datetime
from urllib.parse import urlencode, quote


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

# 修复终端中文输出编码问题
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# ==================== 配置 ====================
HOST = "10.100.20.8"
PORT = 28001
BASE_API = "/api/alarmstatistics-service/v1/levelregion"

# API 配置: (sheet名, API路径, 是否有sitetype参数, 方法)
API_CONFIGS = [
    ("Logical Site",              f"{BASE_API}/getRegionSiteDataTable",              True,  "GET"),
    ("Logical Cell",              f"{BASE_API}/getRegionCellDataTable",              True,  "GET"),
    ("Physical Site",             f"{BASE_API}/getCountRepetitionSiteDown",          True,  "GET"),
    ("Logical Total",             f"{BASE_API}/getBorDataByVendor",                  True,  "GET"),
    ("Physical Site Map",         f"{BASE_API}/getCountRepetitionSiteDownToMap",     True,  "GET"),
    ("Site Class Statistics",     f"{BASE_API}/getSiteDownStatisticOfClass",         True,  "GET"),
    ("Mains Fail Duration",       f"{BASE_API}/getMainsFailOfDuration",              True,  "POST"),
    ("Logical Site Outages Hour", f"{BASE_API}/getCountSiteDownToHour",              True,  "POST"),
]

# 登录凭据
USERNAME = "admin"
PASSWORD = _get_credential("eflow", env="EFLOW_PASS")

SITE_TYPES = ["ALL", "ERA", "REGULAR"]

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# 全局 Cookie（登录后自动填充）
SESSION_COOKIE = ""
FORGERY_TOKEN = ""


def _create_ssl_socket():
    """创建 SSL 连接"""
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
    """发送原始 HTTP 请求，返回 (status_line, headers_dict, body_bytes)"""
    ssock = _create_ssl_socket()

    headers = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: {HOST}:{PORT}\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Language: en-US,en;q=0.9\r\n"
        f"Accept-Encoding: identity\r\n"
        f"Connection: close\r\n"
        f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36\r\n"
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

    # 解析响应
    header_end = response_data.find(b"\r\n\r\n")
    if header_end == -1:
        raise Exception("Cannot parse HTTP response")

    header_part = response_data[:header_end].decode('utf-8', errors='replace')
    resp_body = response_data[header_end + 4:]

    status_line = header_part.split("\r\n")[0]

    # 解析 headers 为 dict
    resp_headers = {}
    for line in header_part.split("\r\n")[1:]:
        if ": " in line:
            k, v = line.split(": ", 1)
            resp_headers[k.lower()] = v

    # 处理 chunked
    if "chunked" in resp_headers.get("transfer-encoding", ""):
        resp_body = _decode_chunked(resp_body)

    return status_line, resp_headers, header_part, resp_body


# 备用 Cookie（登录失败时使用）
FALLBACK_COOKIE = (
    "X-Rm-Data-Version-zenap=1773367620002_0_0_0_0_0_0_0_0; "
    "Z-AUTH-CODE-28001=1154983705_f188b025b7b64878ae0f4511e90ab1a2; "
    "x-dexmesh-user-28001=D86935A99B38A02CDAEA05C225E9303A21FA22B872499884D7B2A1E26A5645FE; "
    "forgerydefense-28001=cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"
)
FALLBACK_FORGERY = "cfe68ff2abd4792b0b08eadcd739630fa22737448c5908a53f1c688d2f28c08a"


def login():
    """自动登录获取鉴权 Cookie（优先使用共享缓存，避免同账户重复登录），失败则使用备用 Cookie"""
    global SESSION_COOKIE, FORGERY_TOKEN

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Task"))
        from auth_manager import get_auth
        result = get_auth(HOST, PORT, USERNAME, PASSWORD)
        source = "缓存" if result["from_cache"] else "重新登录"
        print(f"[LOGIN] 鉴权成功（来源: {source}）")
        SESSION_COOKIE = result["cookie"]
        FORGERY_TOKEN = result["forgery_token"]
    except Exception as e:
        print(f"[LOGIN] auth_manager 失败: {e}")
        print("[LOGIN] Falling back to hardcoded cookies...")
        SESSION_COOKIE = FALLBACK_COOKIE
        FORGERY_TOKEN = FALLBACK_FORGERY

    return SESSION_COOKIE


def _rsa_encrypt_pem(plaintext, public_key_b64):
    """使用 cryptography 库进行标准 RSA PKCS#1 v1.5 加密（兼容 JSEncrypt）"""
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives import serialization

    # 构建 PEM 格式公钥
    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
    public_key = serialization.load_pem_public_key(pem.encode())

    # PKCS#1 v1.5 加密（与 JSEncrypt 完全一致）
    encrypted = public_key.encrypt(
        plaintext.encode('utf-8'),
        asym_padding.PKCS1v15()
    )
    return base64.b64encode(encrypted).decode('ascii')


def fetch_data(sitetype, api_path, method="GET"):
    """使用原始 socket + SSL 发送 HTTP 请求"""
    print(f"[INFO] Requesting sitetype={sitetype}")

    start_time = time.time()

    query_string = urlencode({"regionLevel": "1", "sitetype": sitetype})
    headers_extra = (
        f"Cookie: {SESSION_COOKIE}\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Referer: https://{HOST}:{PORT}/iui/alarmstatistics-ui/sitedown-ui/index.html\r\n"
        f"forgerydefense: {FORGERY_TOKEN}\r\n"
    )

    if method == "POST":
        headers_extra += "Content-Type: application/json\r\n"
        body = json.dumps({
            "regionLevel": "1",
            "timeRange": ["0-2", "2-4", "4-6", "6-12", "12-24", ">48"],
            "sitetype": sitetype,
        })
        status_line, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", api_path, headers_extra=headers_extra, body=body,
        )
    else:
        status_line, hdrs, raw_hdrs, resp_body = _http_request(
            "GET", f"{api_path}?{query_string}", headers_extra=headers_extra,
        )

    elapsed = time.time() - start_time
    print(f"[INFO] {sitetype}: {elapsed:.2f}s, {len(resp_body)} bytes, {status_line}")

    data = json.loads(resp_body.decode('utf-8'))
    return data


def _decode_chunked(data):
    """Decode chunked transfer encoding"""
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


def parse_response(data, sitetype):
    """Parse API JSON response, return list of rows or dict"""
    if isinstance(data, dict):
        if data.get("code") not in (0, None):
            print(f"[WARN] {sitetype}: API error code={data.get('code')}, msg={data.get('msg', '')[:100]}")
            return []
        rows = data.get("data", [])
        # 嵌套结构: {"data": {"data": [...], ...}}
        if isinstance(rows, dict):
            # Site Class Statistics: {"header": [...], "value": [...]}
            if "header" in rows and "value" in rows:
                return rows  # 返回原始 dict
            # getCountSiteDownToHour: {"fields": [...], "values": [...]}
            if "fields" in rows and "values" in rows:
                return rows  # 返回原始 dict
            rows = rows.get("data", [])
    elif isinstance(data, list):
        rows = data
    else:
        rows = []

    if not rows:
        print(f"[WARN] {sitetype}: No data.")
        return []

    if isinstance(rows, list):
        print(f"[INFO] {sitetype}: {len(rows)} records")
    return rows


def _build_region_rantype_df(all_data):
    """构建 region+rantype+num 格式的 DataFrame（Logical Site/Cell）"""
    import pandas as pd

    all_regions = []
    for sitetype, rows in all_data.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            region = row.get("region", "")
            if region and region not in all_regions:
                all_regions.append(region)

    merged = pd.DataFrame({"Region": all_regions})

    for sitetype, rows in all_data.items():
        if not isinstance(rows, list):
            continue
        pivot = {}
        for row in rows:
            region = row.get("region", "")
            rantype = row.get("rantype", "")
            num = row.get("num", 0)
            if region not in pivot:
                pivot[region] = {}
            pivot[region][rantype] = num

        rantypes = sorted(set(row.get("rantype", "") for row in rows))
        for rt in rantypes:
            col_name = f"{sitetype}_{rt}"
            merged[col_name] = merged["Region"].map(
                lambda r, rt_=rt, pv=pivot: pv.get(r, {}).get(rt_, "")
            )

    _add_diff_columns(merged, all_data)
    return merged


def _build_region_num_df(all_data):
    """构建 region+num 格式的 DataFrame（Physical Site/Map）"""
    import pandas as pd

    all_regions = []
    for sitetype, rows in all_data.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            region = row.get("region", "")
            if region and region not in all_regions:
                all_regions.append(region)

    merged = pd.DataFrame({"Region": all_regions})

    for sitetype, rows in all_data.items():
        if not isinstance(rows, list):
            continue
        region_map = {row.get("region", ""): row.get("num", 0) for row in rows}
        merged[sitetype] = merged["Region"].map(lambda r, rm=region_map: rm.get(r, ""))

    # Diff = ALL - ERA - REGULAR
    if all(c in merged.columns for c in ["ALL", "ERA", "REGULAR"]):
        merged["Diff"] = (
            pd.to_numeric(merged["ALL"], errors="coerce").fillna(0)
            - pd.to_numeric(merged["ERA"], errors="coerce").fillna(0)
            - pd.to_numeric(merged["REGULAR"], errors="coerce").fillna(0)
        ).astype(int)

    return merged


def _build_vendor_df(all_data):
    """构建 Logical Total (getBorDataByVendor) 的 DataFrame，合并 ALL/ERA/REGULAR + Diff"""
    import pandas as pd

    # 收集所有 Type+Field 组合
    all_rows = []  # (Type, Vendor, Field, {sitetype: value})
    field_map = {}  # (Type, Field) -> {sitetype: value}

    for sitetype in ["ALL", "ERA", "REGULAR"]:
        rows = all_data.get(sitetype, [])
        if not isinstance(rows, list):
            continue
        for item in rows:
            vendor = item.get("vendor", "")
            fields = item.get("fields", [])
            values = item.get("values", [])
            sd_type = item.get("siteDownType", "")
            for f, v in zip(fields, values):
                key = (sd_type, vendor, f)
                if key not in field_map:
                    field_map[key] = {"Type": sd_type, "Vendor": vendor, "Field": f}
                field_map[key][sitetype] = v

    if not field_map:
        return pd.DataFrame()

    records = list(field_map.values())
    merged = pd.DataFrame(records)

    # 确保 ALL/ERA/REGULAR 列存在
    for col in ["ALL", "ERA", "REGULAR"]:
        if col not in merged.columns:
            merged[col] = 0

    # Diff = ALL - ERA - REGULAR
    merged["Diff"] = (
        pd.to_numeric(merged["ALL"], errors="coerce").fillna(0)
        - pd.to_numeric(merged["ERA"], errors="coerce").fillna(0)
        - pd.to_numeric(merged["REGULAR"], errors="coerce").fillna(0)
    ).astype(int)

    return merged


def _build_class_df(data):
    """构建 header/value 或 fields/values 格式的 DataFrame（单 sitetype）"""
    import pandas as pd

    if isinstance(data, dict):
        if "header" in data and "value" in data:
            return pd.DataFrame({"Class": data["header"], "Count": data["value"]})
        if "fields" in data and "values" in data:
            return pd.DataFrame({"Duration": data["fields"], "Count": data["values"]})
    return pd.DataFrame()


def _build_class_merged_df(all_data):
    """构建 header/value 或 fields/values 格式的合并 DataFrame（ALL/ERA/REGULAR + Diff）"""
    import pandas as pd

    # 确定 key 列名和 val 字段
    first = next((v for v in all_data.values() if v), {})
    if not isinstance(first, dict):
        return pd.DataFrame()

    if "header" in first:
        key_col, cat_key, val_key = "Class", "header", "value"
    elif "fields" in first:
        key_col, cat_key, val_key = "Duration", "fields", "values"
    else:
        return pd.DataFrame()

    # 收集所有 sitetype 的 categories（保持顺序，取并集）
    all_cats = []
    for sitetype in ["ALL", "ERA", "REGULAR"]:
        data = all_data.get(sitetype, {})
        if isinstance(data, dict) and cat_key in data:
            for c in data[cat_key]:
                if c not in all_cats:
                    all_cats.append(c)

    merged = pd.DataFrame({key_col: all_cats})

    for sitetype in ["ALL", "ERA", "REGULAR"]:
        data = all_data.get(sitetype, {})
        if isinstance(data, dict) and cat_key in data and val_key in data:
            cat_val_map = dict(zip(data[cat_key], data[val_key]))
            merged[sitetype] = merged[key_col].map(lambda x, m=cat_val_map: m.get(x, 0))
        else:
            merged[sitetype] = 0

    # Diff = ALL - ERA - REGULAR
    merged["Diff"] = (
        pd.to_numeric(merged["ALL"], errors="coerce").fillna(0)
        - pd.to_numeric(merged["ERA"], errors="coerce").fillna(0)
        - pd.to_numeric(merged["REGULAR"], errors="coerce").fillna(0)
    ).astype(int)

    return merged


def _add_diff_columns(merged, all_data):
    """为 region+rantype 格式添加 Diff 列"""
    import pandas as pd

    rantypes_list = sorted(set(
        row.get("rantype", "")
        for rows in all_data.values()
        if isinstance(rows, list)
        for row in rows
    ))
    for rt in rantypes_list:
        col_all = f"ALL_{rt}"
        col_era = f"ERA_{rt}"
        col_reg = f"REGULAR_{rt}"
        if col_all in merged.columns:
            merged[f"Diff_{rt}"] = (
                pd.to_numeric(merged.get(col_all, 0), errors="coerce").fillna(0)
                - pd.to_numeric(merged.get(col_era, 0), errors="coerce").fillna(0)
                - pd.to_numeric(merged.get(col_reg, 0), errors="coerce").fillna(0)
            ).astype(int)

    diff_cols = [c for c in merged.columns if c.startswith("Diff_") and not c.startswith("Diff_ALL")]
    if diff_cols:
        suffix = diff_cols[0].replace("Diff_", "").split("_")[-1]
        merged[f"Diff_ALL_{suffix}"] = merged[diff_cols].sum(axis=1).astype(int)


def _write_sheet(writer, df, sheet_name):
    """写入单个 sheet 并格式化"""
    from openpyxl.styles import PatternFill, Font

    df.to_excel(writer, index=False, sheet_name=sheet_name)
    ws = writer.sheets[sheet_name]

    # 自动列宽
    for col_idx, col in enumerate(df.columns, 1):
        max_len = max(
            len(str(col)),
            df[col].astype(str).str.len().max() if len(df) > 0 else 0,
        )
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 50)

    # 非零 Diff 值高亮（黄色填充 + 红色字体）
    highlight_fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
    highlight_font = Font(color="FF0000", bold=True)

    diff_col_names = [c for c in df.columns if c == "Diff" or c.startswith("Diff_")]
    for col_name in diff_col_names:
        col_idx = list(df.columns).index(col_name) + 1
        for row_idx in range(2, len(df) + 2):
            cell = ws.cell(row=row_idx, column=col_idx)
            if cell.value and cell.value != 0:
                cell.fill = highlight_fill
                cell.font = highlight_font


def write_to_excel(sheets_data):
    """Write all sheets to one Excel file.
    sheets_data: list of (sheet_name, DataFrame)
    生成新文件后删除旧的 site_outage_*.xlsx，只保留最新一个。
    """
    import pandas as pd
    import glob

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(OUTPUT_DIR, f"site_outage_{timestamp}.xlsx")

    # 如果文件被占用，加序号
    seq = 1
    while os.path.exists(output_file):
        output_file = os.path.join(OUTPUT_DIR, f"site_outage_{timestamp}_{seq}.xlsx")
        seq += 1

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        for sheet_name, df in sheets_data:
            if df is not None and not df.empty:
                _write_sheet(writer, df, sheet_name)
                print(f"[INFO] {sheet_name}: {len(df)} rows, {len(df.columns)} columns")
            else:
                print(f"[SKIP] {sheet_name}: no data")

    print(f"[INFO] Excel saved: {output_file}")

    # 删除旧的 Excel 文件，只保留当前生成的
    for old_file in glob.glob(os.path.join(OUTPUT_DIR, "site_outage_*.xlsx")):
        if os.path.abspath(old_file) != os.path.abspath(output_file):
            try:
                os.remove(old_file)
                print(f"[CLEAN] Deleted old file: {os.path.basename(old_file)}")
            except OSError:
                print(f"[WARN] Cannot delete (in use): {os.path.basename(old_file)}")

    return output_file


def main():
    import pandas as pd  # noqa

    start_time = time.time()
    print("=" * 60)
    print(f"Site Outage Fetcher - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 0. 自动登录获取鉴权
    login()

    sheets_data = []

    for sheet_name, api_path, has_sitetype, method in API_CONFIGS:
        print(f"\n[{sheet_name}] Fetching...")

        try:
            if has_sitetype:
                # 获取 ALL/ERA/REGULAR 三种 sitetype
                all_data = {}
                for sitetype in SITE_TYPES:
                    data = fetch_data(sitetype, api_path, method)
                    rows = parse_response(data, sitetype)
                    all_data[sitetype] = rows

                # 根据数据结构选择构建方式
                first_rows = next((v for v in all_data.values() if v), [])
                if isinstance(first_rows, dict) and ("header" in first_rows or "fields" in first_rows):
                    # Site Class Statistics / Hour format → 合并 ALL/ERA/REGULAR + Diff
                    df = _build_class_merged_df(all_data)
                elif isinstance(first_rows, list) and first_rows and "rantype" in first_rows[0]:
                    # region+rantype+num
                    df = _build_region_rantype_df(all_data)
                elif isinstance(first_rows, list) and first_rows and "vendor" in first_rows[0]:
                    # vendor format
                    df = _build_vendor_df(all_data)
                elif isinstance(first_rows, list) and first_rows and "region" in first_rows[0]:
                    # region+num only
                    df = _build_region_num_df(all_data)
                else:
                    df = pd.DataFrame()
            else:
                # POST API（无 sitetype 参数）
                data = fetch_data("ALL", api_path, method)
                rows = parse_response(data, "ALL")
                if isinstance(rows, dict) and ("header" in rows or "fields" in rows):
                    df = _build_class_df(rows)
                elif isinstance(rows, list) and rows:
                    df = pd.DataFrame(rows)
                else:
                    df = pd.DataFrame()

            sheets_data.append((sheet_name, df))

        except Exception as e:
            print(f"[ERROR] {sheet_name}: {e}")
            sheets_data.append((sheet_name, pd.DataFrame()))

    # 写入 Excel
    output_file = write_to_excel(sheets_data)

    total_elapsed = time.time() - start_time
    print(f"\n[DONE] Completed in {total_elapsed:.2f}s")
    return output_file


if __name__ == "__main__":
    main()
