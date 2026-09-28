# -*- coding: utf-8 -*-
"""
FW 整机吞吐 KPI 数据获取脚本（DPtech/ZTE UMC @ 10.100.2.101/UMC）

功能：
1. 登录经典 UMC（Login!start.action + DES(strEnc) + SM3），鉴权基于会话 Cookie。
   - DES/strEnc 复用服务器原始 js/e.js，通过 Node 子进程执行，保证与浏览器加密 100% 一致。
   - SM3 使用 Node 内置 crypto 的 SM3（已验证与服务器 sm3.js 同为标准 SM3）。
2. 对每台设备（DEVICE_IDS，默认 37781505/37781506）拉取整机吞吐趋势页
   DevDeviceWholeThrouput.action（HTML，内嵌 ECharts 数据）。
3. 从 HTML 中正则提取 timelist / inthrouputlist / outthrouputlist 三个 JS 数组（内存解析）。
4. 通过远程写入 API（db_writer_client -> http://192.168.100.19:8765/api/write）
   将数据 upsert 到远程 fw_db.sqlite（E:/01_RPA/LBR_Tools/KPI/FW/fw_db.sqlite），
   按 (device_id + time_full) 主键替换；API 不可用时降级写入本地 SQLite。
   —— 全程不下载 Excel，数据在内存中解析后批量入库。
5. 同步完成后生成整机吞吐折线图（近 N 天，默认 14 天），
   通过 owa_mail_report.py 发送邮件（名单：Y:/01_RPA/LBR_Tools/KPI/FW/fw_email）。

参考：eflow/ipran_ume/ipran_ume_kpi.py（原始 socket HTTP / SQLite 临时表去重 / UTF-8 / 运行计时）。
注意：本系统（10.100.2.101/UMC，DPtech 经典 UMC）与 ipran_ume_kpi.py 的系统
      （10.100.2.99:28001/portal-athena，OAuth2+RSA REST API）是两套不同架构，
      登录与数据接口均不同，仅复用工程结构与编码约定。

依赖：
- Python 3.8+（同步主流程仅标准库：socket/ssl/gzip/re/json/sqlite3/subprocess/urllib/datetime）
- 图表/邮件功能惰性导入 pandas/matplotlib，并通过托管 venv 调用 owa_mail_report.py
- Node.js >= 14（用于执行 e.js 计算 strEnc 与 SM3；脚本目录需有 e.js 与 _enc.js）
"""

import gc
import io
import os
import re
import ssl
import sys
import gzip
import json
import time
import socket
import sqlite3
import subprocess
from backend.dialect_helpers import list_table_names

_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

# 强制 UTF-8 输出（修复 Windows CMD 中文编码问题）
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# ============================================================
# 配置
# ============================================================
HOST = "10.100.2.101"
PORT = 443


def _runtime_credentials():
    """运行时获取凭据（环境变量 > 数据库 > 模块默认值），支持页面改密后免重启生效。"""
    try:
        from backend.services.credential_store import get_credential
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from credential_store import get_credential
    return get_credential("fw_kpi")

# 脚本目录（相对路径基准）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 查询参数（来自 url.txt）——支持多台设备，按设备分别拉取/入库/出图
# 目标设备 ID 可由配置文件 device_ids 覆盖（见下方外部化配置块）
DEVICE_IDS = ["37781505", "37781506"]

# ========== 外部化配置（Settings 页面可编辑的 fw_kpi_config.json） ==========
# 优先级：环境变量 > 配置文件 > 内置默认
# ⚠ 路径必须与 task_configs_registry 注册的路径一致（backend/services/ 下），
#   否则页面保存的文件没人读：本模块在 fw_kpi/ 子包内，要用 parents[1]。
try:
    from backend.services.task_config_files import load_json_config
    _FW_CONF = load_json_config(Path(__file__).resolve().parents[1] / "fw_kpi_config.json")
except Exception:
    _FW_CONF = None
if _FW_CONF:
    HOST = _FW_CONF.get("host", HOST)
    PORT = int(_FW_CONF.get("port", PORT))
    if isinstance(_FW_CONF.get("device_ids"), list) and _FW_CONF["device_ids"]:
        DEVICE_IDS = [str(d).strip() for d in _FW_CONF["device_ids"] if str(d).strip()]
    print(f"[FW] 已加载 fw_kpi_config.json: host={HOST}, 设备数={len(DEVICE_IDS)}")

# 时间范围：当前时间往前 30 天的 00:00:00 起，到当前时刻止。
# 例如今天 2026-08-04 21:30 → start 2026-07-06 00:00:00, end 2026-08-04 21:30:xx
# 可通过环境变量 FW_KPI_DAYS_BACK 或配置文件 days_back 覆盖（默认 30）。
_DAYS_BACK = int(os.environ.get("FW_KPI_DAYS_BACK") or ((_FW_CONF or {}).get("days_back", 30)))
_NOW = datetime.now()
END_TIME = _NOW.strftime("%Y-%m-%d %H:%M:%S")
START_TIME = (_NOW - timedelta(days=_DAYS_BACK)).replace(
    hour=0, minute=0, second=0, microsecond=0
).strftime("%Y-%m-%d %H:%M:%S")

# Node 加密助手与服务器原始 e.js（用于复刻 strEnc）
ENC_HELPER = os.path.join(SCRIPT_DIR, "_enc.js")
EJS_LOCAL = os.path.join(SCRIPT_DIR, "e.js")
EJS_URL_PATH = "/UMC/js/e.js"

# 数据库（与脚本同目录，仅作远程 API 不可用时的降级备份）
DB_NAME = "fw_db.sqlite"
DB_PATH = os.path.join(SCRIPT_DIR, DB_NAME)
TABLE_NAME = "device_whole_throughput"

# ============================================================
# 远程 API 写入 / 图表 / 邮件配置
# ============================================================
# 远程数据库逻辑名（db_writer_api.py 映射 -> E:\01_RPA\LBR_Tools\KPI\FW\fw_db.sqlite）
REMOTE_DB_NAME = "fw_db.sqlite"
REMOTE_TABLE = TABLE_NAME
API_WRITE_BATCH = 5000  # 每批 POST 行数

# my_app 根目录（.../Task/my_app）
MY_APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
CHART_OUTPUT_DIR = os.path.join(MY_APP_DIR, "TMP", "fw_charts")
EMAIL_REPORTS_DIR = os.path.join(MY_APP_DIR, "email_reports")

# 邮件名单（远程共享目录）
EMAIL_LIST_DIR = r"Y:\01_RPA\LBR_Tools\KPI\FW\fw_email"
SS_EMAIL_FILE = os.path.join(EMAIL_LIST_DIR, "ss_email.txt")
CC_EMAIL_FILE = os.path.join(EMAIL_LIST_DIR, "cc_email.txt")

# 托管 venv Python（带 exchangelib/matplotlib，用于调用 owa_mail_report.py）
_MANAGED_VENV_PY = (
    r"C:\Users\ZTEEMS\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
)

# 图表回看天数（默认 14 天，可用环境变量 FW_CHART_DAYS_BACK 或配置文件 chart_days_back 覆盖）
CHART_DAYS_BACK = int(os.environ.get("FW_CHART_DAYS_BACK") or ((_FW_CONF or {}).get("chart_days_back", 14)))
# 是否在同步后生成图表并发送邮件（FW_CHART_EMAIL=0 可关闭）
ENABLE_CHART_EMAIL = os.environ.get("FW_CHART_EMAIL", "1") != "0"

# 图表颜色配置（与 ipran_chart_service 风格一致）
COLOR_IN = '#2E86AB'
COLOR_OUT = '#A23B72'
BG_COLOR = '#E8F0FE'
TITLE_COLOR = '#2F5496'
GRID_COLOR = '#C5C5C5'


# ============================================================
# HTTP / SSL 工具（复用 ipran_ume_kpi.py 的原始 socket 方式）
# ============================================================
def _create_ssl_socket():
    """创建绕过证书校验的 TLS socket。"""
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
    """解码 HTTP chunked 响应体。"""
    result = b""
    pos = 0
    while pos < len(data):
        line_end = data.find(b"\r\n", pos)
        if line_end == -1:
            break
        try:
            chunk_size = int(data[pos:line_end].decode('utf-8', errors='replace').strip(), 16)
        except ValueError:
            break
        if chunk_size == 0:
            break
        pos = line_end + 2
        result += data[pos:pos + chunk_size]
        pos += chunk_size + 2
    return result


class Session:
    """极简 HTTP 会话：维护 Cookie，发送原始 HTTP 请求。"""

    def __init__(self):
        self.cookies = {}

    def _cookie_header(self):
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def request(self, method, path, headers_extra=None, body=None, referer=None):
        ssock = _create_ssl_socket()
        headers = (
            f"{method} {path} HTTP/1.1\r\n"
            f"Host: {HOST}:{PORT}\r\n"
            f"Accept: text/html,application/json, */*;q=0.8\r\n"
            f"Accept-Language: en-US,en;q=0.9\r\n"
            f"Accept-Encoding: gzip\r\n"
            f"Connection: close\r\n"
            f"User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36\r\n"
        )
        if referer:
            headers += f"Referer: {referer}\r\n"
        if self.cookies:
            headers += f"Cookie: {self._cookie_header()}\r\n"
        if headers_extra:
            headers += headers_extra
        if body is not None:
            body_bytes = body.encode('utf-8') if isinstance(body, str) else body
            headers += f"Content-Length: {len(body_bytes)}\r\n"
        else:
            body_bytes = b""
        headers += "\r\n"

        ssock.sendall(headers.encode('utf-8') + body_bytes)

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

        # 收集 Set-Cookie
        for line in header_part.split("\r\n"):
            if line.lower().startswith("set-cookie:"):
                val = line.split(": ", 1)[1].split(";")[0]
                if "=" in val:
                    k, v = val.split("=", 1)
                    if v:
                        self.cookies[k.strip()] = v

        return status_line, resp_headers, resp_body


# ============================================================
# 加密助手：确保 e.js 存在 + 调用 Node 计算 q/w/smvalidate
# ============================================================
def ensure_ejs(sess: Session):
    """若本地 e.js 不存在，则从服务器拉取并缓存（DES 算法静态，缓存即可）。"""
    if os.path.exists(EJS_LOCAL) and os.path.getsize(EJS_LOCAL) > 1000:
        return
    print("[ENC] 本地 e.js 缺失，从服务器拉取 ...")
    st, hd, body = sess.request("GET", EJS_URL_PATH,
                                referer=f"https://{HOST}:{PORT}/UMC/Login!start.action")
    if not body or len(body) < 1000:
        raise Exception(f"拉取 e.js 失败: {st} len={len(body)}")
    with open(EJS_LOCAL, "wb") as f:
        f.write(body)
    print(f"[ENC] 已缓存 e.js ({len(body)} bytes)")


def compute_login_enc(uname, pwd, cn, cp, c_form):
    """调用 Node 子进程，复用服务器原始 e.js(strEnc) 与内置 SM3 计算登录加密字段。"""
    if not os.path.exists(ENC_HELPER):
        raise Exception(f"缺少 Node 加密助手: {ENC_HELPER}")
    if not os.path.exists(EJS_LOCAL):
        raise Exception(f"缺少 e.js: {EJS_LOCAL}（请先运行 ensure_ejs）")
    proc = subprocess.run(
        ["node", os.path.basename(ENC_HELPER), uname, pwd, cn, cp, c_form],
        cwd=SCRIPT_DIR, capture_output=True, text=True, timeout=30,
        creationflags=_SUBPROCESS_FLAGS,
    )
    if proc.returncode != 0:
        raise Exception(f"Node 加密失败(rc={proc.returncode}): {proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout.strip())
    except Exception as exc:
        raise Exception(f"Node 加密输出解析失败: {exc} / stdout={proc.stdout!r}")


# ============================================================
# 登录
# ============================================================
def login(sess: Session):
    """执行经典 UMC 登录流程。

    流程：
    1. GET /UMC/code.jsp → 取会话码 c_url
    2. GET /UMC/Login!start.action?c=<c_url> → 登录页，提取加密参数 cn / cp / c_form
    3. ensure_ejs + Node 计算 q=strEnc(user,cn,cp,c_form) w=strEnc(pwd,cp,cn,c_form) smvalidate=SM3(user+pwd+cp+cn)
    4. POST /UMC/Login.action (c,q,w,smvalidate) → 成功返回 top.window.location='main.action'
    """
    print("[LOGIN] 开始鉴权 ...")

    # 1) code.jsp
    st, hd, body = sess.request("GET", "/UMC/code.jsp")
    if "200" not in st:
        raise Exception(f"code.jsp 失败: {st}")
    c_url = json.loads(body.decode('utf-8').strip())["c"]
    print(f"[LOGIN] c_url = {c_url}")

    # 2) 登录页
    st, hd, body = sess.request(
        "GET", f"/UMC/Login!start.action?c={c_url}&errmsg=",
        referer=f"https://{HOST}:{PORT}/UMC/",
    )
    if "200" not in st:
        raise Exception(f"登录页拉取失败: {st}")
    html = body.decode('utf-8', errors='replace')
    m_cn = re.search(r'\bcn\s*=\s*"([^"]*)"', html)
    m_cp = re.search(r'\bcp\s*=\s*"([^"]*)"', html)
    m_c = re.search(r'getElementById\(\s*"c"\s*\)\.value\s*=\s*"([^"]*)"', html)
    if not (m_cn and m_cp and m_c):
        raise Exception("无法从登录页提取 cn/cp/c_form（页面结构异常）")
    cn, cp, c_form = m_cn.group(1), m_cp.group(1), m_c.group(1)
    print(f"[LOGIN] cn={cn} cp={cp} c_form={c_form}")

    # 3) 计算加密字段
    ensure_ejs(sess)
    _cred_user, _cred_pwd = _runtime_credentials()
    enc = compute_login_enc(_cred_user, _cred_pwd, cn, cp, c_form)
    print(f"[LOGIN] q={enc['q'][:32]}... w={enc['w'][:32]}... smvalidate={enc['smvalidate'][:32]}...")

    # 4) 提交登录
    form = urllib.parse.urlencode({
        "c": c_form,
        "q": enc["q"],
        "w": enc["w"],
        "p": "",
        "smvalidate": enc["smvalidate"],
        "e": "",
    })
    st, hd, body = sess.request(
        "POST", "/UMC/Login.action",
        headers_extra=(
            "Content-Type: application/x-www-form-urlencoded\r\n"
            "X-Requested-With: XMLHttpRequest\r\n"
        ),
        body=form,
        referer=f"https://{HOST}:{PORT}/UMC/Login!start.action?c={c_url}&errmsg=",
    )
    resp = body.decode('utf-8', errors='replace')
    if "main.action" not in resp:
        raise Exception(f"登录失败: {st} / resp={resp[:300]}")
    print(f"[LOGIN] 成功 (cookies: {list(sess.cookies.keys())})")
    return True


# ============================================================
# 拉取吞吐数据页
# ============================================================
def fetch_throughput_html(sess: Session, device_id, starttime, endtime):
    """拉取整机吞吐趋势页 HTML。"""
    params = urllib.parse.urlencode({
        "trendParam.deviceId": device_id,
        "trendParam.starttime": starttime,
        "trendParam.endtime": endtime,
    })
    path = f"/UMC/dev/sub/DevDeviceWholeThrouput.action?{params}"
    print(f"[DATA] GET {path[:90]}...")
    st, hd, body = sess.request(
        "GET", path,
        referer=f"https://{HOST}:{PORT}/UMC/main.action",
    )
    if "200" not in st:
        raise Exception(f"数据接口失败: {st} (可能未鉴权)")
    print(f"[DATA] 状态 {st}, 大小 {len(body)} bytes, Content-Type={hd.get('content-type')}")
    return body.decode('utf-8', errors='replace')


# ============================================================
# 解析内嵌 JS 数组（内存解析，不落盘 Excel）
# ============================================================
def _extract_array(html, name):
    m = re.search(rf'var\s+{re.escape(name)}\s*=\s*\[([\s\S]*?)\]', html)
    return m.group(1) if m else None


def parse_throughput(html, start_year, start_month):
    """从 HTML 提取 timelist / inthrouputlist / outthrouputlist。

    返回 list[dict]：{time_label, time_full, in_bps, out_bps}
    time_full 由 timelist 推导年份后拼出（跨年自动 +1）。
    """
    time_content = _extract_array(html, "timelist")
    if not time_content:
        raise Exception("未找到 timelist 数组")
    time_labels = re.findall(r'"([^"]*)"', time_content)

    in_content = None
    for nm in ("inthrouputlist", "inthrouputl"):
        in_content = _extract_array(html, nm)
        if in_content:
            break
    out_content = None
    for nm in ("outthrouputlist", "outthrouputl"):
        out_content = _extract_array(html, nm)
        if out_content:
            break
    if not in_content or not out_content:
        raise Exception("未找到 in/out 吞吐数组")

    in_vals = [int(x) for x in re.findall(r'-?\d+', in_content)]
    out_vals = [int(x) for x in re.findall(r'-?\d+', out_content)]

    n = min(len(time_labels), len(in_vals), len(out_vals))
    if n == 0:
        raise Exception("解析到 0 条数据")
    if not (len(time_labels) == len(in_vals) == len(out_vals)):
        print(f"[PARSE] 长度不一致 timelist={len(time_labels)} in={len(in_vals)} out={len(out_vals)}，按最小长度 {n} 对齐")

    # 推导年份：跨年（月份变小）时 year+1
    year = start_year
    prev_month = start_month
    rows = []
    for i in range(n):
        label = time_labels[i].strip()
        try:
            date_part, time_part = label.split()
            mm, dd = date_part.split("-")
            hh, mi = time_part.split(":")
            mm_i = int(mm)
        except Exception:
            # 兜底：按位置解析 "MM-dd HH:MM"
            mm_i = int(label[0:2])
            dd = label[3:5]
            hh = label[6:8]
            mi = label[9:11]
        if mm_i < prev_month:
            year += 1
        prev_month = mm_i
        time_full = f"{year:04d}-{int(mm):02d}-{int(dd):02d} {int(hh):02d}:{int(mi):02d}:00"
        rows.append((time_full, label, in_vals[i], out_vals[i]))

    print(f"[PARSE] 解析得到 {len(rows)} 条记录（{rows[0][0]} ~ {rows[-1][0]}）")
    return rows


# ============================================================
# 数据库写入：远程 API 优先（upsert），失败降级本地 SQLite（临时表去重）
# ============================================================
def write_to_remote_db(rows, device_id):
    """通过远程写入 API 将吞吐数据 upsert 到远程 fw_db.sqlite。

    rows: list[(time_full, time_label, in_bps, out_bps)]
    按 (device_id, time_full) 主键分批 POST，返回写入行数。
    """
    services_dir = os.path.dirname(SCRIPT_DIR)
    if services_dir not in sys.path:
        sys.path.insert(0, services_dir)
    from db_writer_client import DbWriterClient

    client = DbWriterClient()
    # 健康检查（不可达时快速失败，交由本地降级）
    health = client.health()
    if health.get("status") != "ok":
        raise Exception(f"远程写入 API 健康检查失败: {health}")

    columns = ["device_id", "time_full", "time_label", "in_bps", "out_bps"]
    total = 0
    n_batches = (len(rows) + API_WRITE_BATCH - 1) // API_WRITE_BATCH
    for i in range(0, len(rows), API_WRITE_BATCH):
        batch = rows[i:i + API_WRITE_BATCH]
        payload_rows = [[device_id, tf, tl, ib, ob] for tf, tl, ib, ob in batch]
        result = client.write_data(
            db=REMOTE_DB_NAME,
            table=REMOTE_TABLE,
            columns=columns,
            rows=payload_rows,
            mode="upsert",
            pk_columns=["device_id", "time_full"],
        )
        if not result.get("success"):
            raise Exception(f"远程 API 写入失败: {result}")
        total += len(payload_rows)
        print(f"[API] 批次 {i // API_WRITE_BATCH + 1}/{n_batches}: 写入 {len(payload_rows)} 行")
    print(f"[API] 远程写入完成: 共 {total} 行 -> {REMOTE_DB_NAME}/{REMOTE_TABLE}")
    return total


def _open_db():
    """打开数据库；sqlite 模式下若被占用（锁定）则按规则追加 _序号 生成新文件；pg 模式走 PG 连接。"""
    from backend.database import DB_MODE, get_raw_connection
    candidate = DB_PATH
    if DB_MODE == "pg":
        return get_raw_connection(str(candidate), logical_name="fw_db", timeout=10), candidate
    idx = 0
    while True:
        try:
            conn = sqlite3.connect(candidate, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=OFF")
            conn.execute("PRAGMA cache_size=-64000")
            # 探测可写
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
            return conn, candidate
        except sqlite3.OperationalError as exc:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            msg = str(exc).lower()
            if "locked" in msg or "unable to open" in msg or "database is locked" in msg:
                idx += 1
                if idx > 99:
                    raise
                base, ext = os.path.splitext(DB_PATH)
                candidate = f"{base}_{idx}{ext}"
                print(f"[DB] 目标库被占用，改用 {os.path.basename(candidate)}")
                continue
            raise


def write_to_local_db(rows, device_id):
    """降级方案：将吞吐数据写入本地 SQLite，按 (device_id, time_full) 去重替换。

    rows: list[(time_full, time_label, in_bps, out_bps)]
    """
    conn, used_path = _open_db()
    cur = conn.cursor()
    try:
        if TABLE_NAME not in set(list_table_names(conn)):
            cur.execute(
                f'CREATE TABLE "{TABLE_NAME}" ('
                '  device_id   TEXT NOT NULL,'
                '  time_full   TEXT NOT NULL,'
                '  time_label  TEXT,'
                '  in_bps      INTEGER,'
                '  out_bps     INTEGER,'
                '  PRIMARY KEY (device_id, time_full))'
            )
        cur.execute(
            f'CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_time ON "{TABLE_NAME}"(time_full)'
        )

        # 临时表去重：写入临时 → 删除主表冲突行 → 回填
        temp = "_tmp_fw_throughput"
        cur.execute(f'DROP TABLE IF EXISTS "{temp}"')
        cur.execute(
            f'CREATE TABLE "{temp}" ('
            '  device_id TEXT, time_full TEXT, time_label TEXT, in_bps INTEGER, out_bps INTEGER)'
        )
        batch = []
        for time_full, time_label, in_bps, out_bps in rows:
            batch.append((device_id, time_full, time_label, in_bps, out_bps))
            if len(batch) >= 2000:
                cur.executemany(
                    f'INSERT INTO "{temp}" VALUES (?,?,?,?,?)', batch)
                batch.clear()
        if batch:
            cur.executemany(f'INSERT INTO "{temp}" VALUES (?,?,?,?,?)', batch)

        cur.execute(
            f'DELETE FROM "{TABLE_NAME}" WHERE (device_id, time_full) IN '
            f'(SELECT device_id, time_full FROM "{temp}")'
        )
        deleted = cur.rowcount
        cur.execute(
            f'INSERT INTO "{TABLE_NAME}" (device_id, time_full, time_label, in_bps, out_bps) '
            f'SELECT device_id, time_full, time_label, in_bps, out_bps FROM "{temp}"'
        )
        inserted = cur.rowcount
        cur.execute(f'DROP TABLE IF EXISTS "{temp}"')
        conn.commit()
        print(f"[DB] 去重替换: 删除旧数据 {deleted} 行，写入 {inserted} 行 -> {os.path.basename(used_path)}")
        return inserted
    finally:
        conn.close()


# ============================================================
# 图表生成 + 邮件发送（参考 ipran_chart_service.py）
# ============================================================
def _read_addresses(path):
    """从名单文件读取邮箱地址（支持 ; / , 分隔，# 开头为注释）。"""
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for part in line.replace(";", ",").split(","):
                p = part.strip()
                if p:
                    out.append(p)
    return out


def _resolve_recipients():
    to_list = _read_addresses(SS_EMAIL_FILE)
    cc_list = _read_addresses(CC_EMAIL_FILE)
    return to_list, cc_list


def build_chart_dataframe(rows):
    """将解析后的行数据转为图表用 DataFrame（惰性导入 pandas，向量化运算）。"""
    import pandas as pd

    df = pd.DataFrame(rows, columns=["time_full", "time_label", "in_bps", "out_bps"])
    df["time_full"] = pd.to_datetime(df["time_full"], errors="coerce")
    df = df.dropna(subset=["time_full"])
    cutoff = datetime.now() - timedelta(days=CHART_DAYS_BACK)
    df = df[df["time_full"] >= cutoff].sort_values("time_full").reset_index(drop=True)
    # 向量化换算 bps -> Mbps
    df["in_mbps"] = pd.to_numeric(df["in_bps"], errors="coerce") / 1e6
    df["out_mbps"] = pd.to_numeric(df["out_bps"], errors="coerce") / 1e6
    return df


def generate_chart(df, output_path, device_id):
    """生成指定设备的整机吞吐折线图并保存为 PNG（风格与 ipran_chart_service 一致）。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    try:
        if df.empty:
            print("[CHART] 无数据，跳过图表生成")
            return False

        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        fig, ax = plt.subplots(figsize=(14, 5.5))
        ax.set_facecolor(BG_COLOR)
        fig.patch.set_facecolor(BG_COLOR)

        x = range(len(df))
        ax.plot(x, df["in_mbps"], linewidth=1.2,
                label="In Throughput(Mbps)", color=COLOR_IN, alpha=0.85)
        ax.plot(x, df["out_mbps"], linewidth=1.2,
                label="Out Throughput(Mbps)", color=COLOR_OUT, alpha=0.85)

        ax.set_xlabel("Time", fontsize=9)
        ax.set_ylabel("Throughput(Mbps)", fontsize=9)
        ax.set_title(f"FW Whole Throughput (Device: {device_id})\nLast {CHART_DAYS_BACK} Days",
                     fontsize=13, fontweight="bold", color=TITLE_COLOR, pad=12)
        ax.legend(loc='upper left', fontsize=8, frameon=True,
                  facecolor='white', framealpha=0.8, edgecolor='#CCCCCC')
        ax.grid(axis='y', linestyle='--', color=GRID_COLOR, linewidth=0.6, alpha=0.6)
        ax.set_axisbelow(True)
        for spine in ax.spines.values():
            spine.set_color('#B0B0B0')
            spine.set_linewidth(0.5)

        # 分钟粒度：显示 MM-DD HH:MM（兼容 ISO T 分隔与空格分隔格式）
        date_labels = []
        for t in df["time_full"]:
            raw = str(t)
            if 'T' in raw:
                raw = raw.replace('T', ' ')
            date_labels.append(raw[5:16] if len(raw) >= 16 else raw)
        n = len(date_labels)
        max_ticks = 20
        step = max(1, n // max_ticks) if n > max_ticks else 1
        tick_positions = list(range(0, n, step))
        ax.set_xticks(tick_positions)
        ax.set_xticklabels([date_labels[i] for i in tick_positions],
                           rotation=45, fontsize=7, ha='right')
        ax.tick_params(axis='both', labelsize=8)

        plt.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight",
                    facecolor=BG_COLOR, edgecolor='none')
        plt.close(fig)
        print(f"[CHART] 图表已保存: {output_path} (数据点={len(df)})")
        return True
    except Exception as e:
        print(f"[CHART] 生成图表失败: {e}")
        return False


def _send_email(to, cc, subject, body, inline_images):
    """调用通用邮件脚本 owa_mail_report.py 发送（托管 venv 执行）。"""
    script = os.path.join(EMAIL_REPORTS_DIR, "owa_mail_report.py")
    if not os.path.isfile(script):
        return {"success": False, "error": f"脚本不存在: {script}"}

    cmd = [
        _MANAGED_VENV_PY, script,
        "--data-dir", CHART_OUTPUT_DIR,
        "--email-dir", EMAIL_REPORTS_DIR,
        "--no-excel",
        "--subject", subject,
        "--body", body,
        "--to", ";".join(to),
        "--cc", ";".join(cc) if cc else "",
    ]
    for img in inline_images:
        cmd += ["--images", str(img)]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            # 180 → 300（2026-09-18）：实测一次冷启动完整发送（NTLM 握手 + 内嵌图上传
            # + CreateItem/SendItem）要 198.49s，180s 会把**正在发送**的子进程杀掉，
            # 任务记失败却可能已经发出。与 kpi_email_report/liberia_email_report 对齐。
            timeout=300,
            cwd=MY_APP_DIR,
            creationflags=_SUBPROCESS_FLAGS,
        )
        if proc.returncode == 0:
            return {"success": True, "message": proc.stdout[-500:] if proc.stdout else ""}
        return {"success": False, "error": proc.stderr[-1000:] if proc.stderr else proc.stdout}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "邮件发送超时"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def generate_chart_and_send_email(device_rows):
    """按设备分别生成吞吐图表并发送邮件（名单来自 Y:/01_RPA/LBR_Tools/KPI/FW/fw_email）。

    device_rows: {device_id: rows} —— 每台设备生成一张图，邮件附带全部图片。
    """
    t0 = time.time()

    from backend.services.email_recipient_store import get_email_recipients
    to_arg, cc_arg = get_email_recipients("fw_kpi_sync", None, None)
    to_list = [a.strip() for a in (to_arg or "").split(";") if a.strip()]
    cc_list = [a.strip() for a in (cc_arg or "").split(";") if a.strip()]
    print(f"[CHART] 收件人: {len(to_list)} 主送, {len(cc_list)} 抄送")
    if not to_list:
        return {"success": False, "error": f"主送名单为空或不可读: {SS_EMAIL_FILE}"}

    os.makedirs(CHART_OUTPUT_DIR, exist_ok=True)

    # 按设备分别出图
    chart_files = []
    for device_id, rows in device_rows.items():
        df = build_chart_dataframe(rows)
        if df.empty:
            print(f"[CHART] 设备 {device_id}: 近 {CHART_DAYS_BACK} 天无数据，跳过出图")
            continue
        chart_path = os.path.join(CHART_OUTPUT_DIR, f"FW_Whole_Throughput_{device_id}.png")
        if generate_chart(df, chart_path, device_id):
            chart_files.append(chart_path)

    if not chart_files:
        return {"success": False, "error": f"近 {CHART_DAYS_BACK} 天无任何设备可绘图数据"}

    device_txt = " & ".join(device_rows.keys())
    subject = f"FW Whole Throughput Report - {datetime.now().strftime('%Y-%m-%d')}"
    body = (
        "<h3>Dear Team,</h3>"
        "<p>Please find the FW Whole Throughput charts attached (one per device).</p>"
        f"<p>Devices: {device_txt}</p>"
        f"<p>Charts cover the last {CHART_DAYS_BACK} days of 1-minute granularity data.</p>"
        "<br><p>Best regards,<br>ZTENOC OLR</p>"
    )

    result = _send_email(to=to_list, cc=cc_list, subject=subject,
                         body=body, inline_images=chart_files)
    result["elapsed_seconds"] = round(time.time() - t0, 2)
    result["charts"] = [os.path.basename(p) for p in chart_files]
    print(f"[CHART] 邮件发送结果: success={result.get('success')}, "
          f"图片 {len(chart_files)} 张, 耗时 {result['elapsed_seconds']}s")
    return result


# ============================================================
# 主流程
# ============================================================
def run():
    t_start = time.time()
    print("=" * 70)
    print(f"[MAIN] FW 整机吞吐 KPI 同步开始 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[MAIN] 目标: https://{HOST}:{PORT}/UMC  设备ID={DEVICE_IDS}")
    print(f"[MAIN] 时间范围: {START_TIME} ~ {END_TIME}")
    print(f"[MAIN] 远程库: {REMOTE_DB_NAME}/{TABLE_NAME} (db_writer_api)")
    print(f"[MAIN] 本地降级库: {DB_PATH}")
    print("=" * 70)

    sess = Session()

    # 1. 登录（一次登录，多设备复用会话）
    login(sess)

    start_year = int(START_TIME[0:4])
    start_month = int(START_TIME[5:7])

    # 2-4. 逐设备：拉取 → 解析 → 通过 API 写入远程数据库（失败降级本地 SQLite）
    device_rows = {}
    total_inserted = 0
    api_ok = True
    for device_id in DEVICE_IDS:
        print(f"[MAIN] ---- 设备 {device_id} 开始处理 ----")
        try:
            html = fetch_throughput_html(sess, device_id, START_TIME, END_TIME)
            rows = parse_throughput(html, start_year, start_month)
            del html
            gc.collect()
        except Exception as exc:
            print(f"[MAIN] 设备 {device_id} 拉取/解析失败，跳过: {exc}")
            continue
        device_rows[device_id] = rows

        try:
            inserted = write_to_remote_db(rows, device_id)
        except Exception as exc:
            api_ok = False
            print(f"[API] 设备 {device_id} 远程写入失败，降级写入本地 SQLite: {exc}")
            inserted = write_to_local_db(rows, device_id)
        total_inserted += inserted

    if not device_rows:
        print("[MAIN] 所有设备均未获取到数据，终止")
        return {"success": False, "error": "所有设备均未获取到数据"}

    # 5. 按设备分别生成图表并发送邮件（附全部图片）
    email_result = None
    if ENABLE_CHART_EMAIL:
        try:
            email_result = generate_chart_and_send_email(device_rows)
        except Exception as exc:
            email_result = {"success": False, "error": str(exc)}
            print(f"[CHART] 图表/邮件流程异常: {exc}")

    elapsed = time.time() - t_start
    print("=" * 70)
    print(f"[MAIN] 完成: 写入 {total_inserted} 条 (remote_api={api_ok})，总耗时 {elapsed:.2f} 秒")
    if email_result:
        print(f"[MAIN] 邮件: success={email_result.get('success')}")
    print("[MAIN] Done.")

    # 邮件失败必须让任务失败（2026-09-18 修正）。
    # 原实现无论邮件成败都返回 success=True，导致：
    #   (a) 失败不会进入 email_recovery 的失败链 → EWS 恢复后**永不补发**；
    #   (b) 任务历史/看板显示成功 —— 典型的假绿。
    # 这正是 fw_kpi_sync 长期游离在 EMAIL_TASK_IDS 之外却没人发现的另一半原因。
    # 数据同步本身已完成，故在 error 里同时说明，避免误判成"数据没同步"。
    email_failed = bool(email_result) and not email_result.get("success")
    result = {
        "success": not email_failed,
        "rows_written": total_inserted,
        "remote_api": api_ok,
        "devices": list(device_rows.keys()),
        "email": email_result,
        "elapsed_seconds": round(elapsed, 2),
    }
    if email_failed:
        reason = (email_result.get("error") or email_result.get("message")
                  or str(email_result))
        result["error"] = (f"邮件发送失败（数据已同步 {total_inserted} 条，"
                           f"remote_api={api_ok}）: {str(reason)[:800]}")
        print(f"[MAIN] 邮件失败，任务判定为失败: {str(reason)[:200]}")
    return result


def run_fw_kpi_sync() -> dict:
    """供 Task Manager 调用的入口：同步 + 图表 + 邮件。"""
    try:
        return run()
    except Exception as e:
        print(f"[MAIN] 任务异常: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    result = run_fw_kpi_sync()
    print(f"\n结果: {result}")
