"""
eFlow API Client - 集成版
直接从 ZTE 网管系统 eFlow API 获取 TT/WO/CR/PM/Site/Person/RealtimeAlarm 数据
使用原始 socket + SSL（绕过 requests/urllib3 的 TLS 兼容问题）
"""
import ssl
import socket
import json
import io
import time
import re
import base64
import uuid
import logging
import gzip
import os
import random
import glob
import shutil
import csv
import sqlite3
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import ftplib

logger = logging.getLogger("eflow_api")

# ========== 连接配置 ==========
HOST = os.environ.get("EFLOW_HOST", "10.100.20.8")
PORT = int(os.environ.get("EFLOW_PORT", "28001"))
USERNAME = os.environ.get("EFLOW_USER", "admin")
PASSWORD = os.environ.get("EFLOW_PASS", "Brysj*8*")
MAX_PARALLEL_DOWNLOADS = max(1, int(os.environ.get("EFLOW_MAX_PARALLEL_DOWNLOADS", "6")))

# ========== 重试配置 ==========
HTTP_MAX_RETRIES = max(0, int(os.environ.get("EFLOW_HTTP_MAX_RETRIES", "3")))
HTTP_RETRY_DELAY = float(os.environ.get("EFLOW_HTTP_RETRY_DELAY", "1"))
HTTP_CONNECT_TIMEOUT = float(os.environ.get("EFLOW_CONNECT_TIMEOUT", "15"))
HTTP_READ_TIMEOUT = float(os.environ.get("EFLOW_READ_TIMEOUT", "90"))

# ========== FTP 配置 ==========
FTP_HOST = os.environ.get("FTP_HOST", "192.168.100.19")
FTP_PORT = int(os.environ.get("FTP_PORT", "21"))
FTP_USER = os.environ.get("FTP_USER", "FINEBI")
FTP_PASS = os.environ.get("FTP_PASS", "DX")
FTP_REMOTE_DIR = os.environ.get("FTP_REMOTE_DIR", "/Python")

# ========== API 路径 ==========
TT_API_PATH = "/api/eflow-ticket/v1/eflow-tt/base/list"
WO_API_PATH = "/api/eflow-wo/v1/eflow-wo/base/list"
CR_API_PATH = "/api/eflow-asset/v1/eflow-cr/base/list"
PM_API_PATH = "/api/eflow-pm/v1/eflow-pm-task/base/list"
SITE_API_PATH = "/api/cmdb/v1/data/search/Site"
PERSON_API_PATH = "/api/cmdb/v1/data/search/Person"
ALARM_API_PATH = "/api/fm-active/v1/activealarms/table"
HIS_ALARM_API_PATH = "/api/fm-history/v1/hisalarms/pageinfo"

# ========== 数据目录 ==========
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "eflow")
os.makedirs(DATA_DIR, exist_ok=True)

# 仪表盘统一主库（GIS Map / RealTime Alarm Map / Alarm Dashboard 从此处读取）
APP_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "db", "app.db")

# ========== 小时报告与图片生成配置 ==========
TT_REPORT_SUBDIR = "tt_reports"          # 报告与图片输出子目录
SEND_EMAIL_AFTER_REPORT = False          # 是否在生成报告后发送邮件

# eFlow TT 导出列名 -> mail_126.ExcelDataProcessor 期望列名
_TT_COLUMN_RENAME = {
    "TT No.": "Ticket No.",
    "Asset Name": "Site Name",
    "Site Class": "Site Category",
    "SLA Total Duration": "SLA Time",
    "Occurrence Time": "Alarm Occur Time",
    "Alarm Clearing Time": "Alarm Clear Time",
    "SLA Remaining Duration": "SLA Remain Time",
}

# Site 表中作为 TX 值来源的列名（传输类型）
SITE_TX_SOURCE_COL = "TRM Type"

# ========== 会话状态 ==========
_session_cookie = ""
_forgery_token = ""
_http_local = threading.local()


# ========== SSL / HTTP 基础 ==========
def _create_ssl_socket():
    """Create one TLS connection. Connections are reused per worker thread."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers('ALL:@SECLEVEL=0')
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(HTTP_CONNECT_TIMEOUT)
    ssock = ctx.wrap_socket(sock)
    ssock.connect((HOST, PORT))
    ssock.settimeout(HTTP_READ_TIMEOUT)
    return ssock


def _get_thread_socket():
    ssock = getattr(_http_local, "socket", None)
    if ssock is None:
        ssock = _create_ssl_socket()
        _http_local.socket = ssock
    return ssock


def _close_thread_socket():
    ssock = getattr(_http_local, "socket", None)
    _http_local.socket = None
    if ssock is not None:
        try:
            ssock.close()
        except OSError:
            pass


def _retry_delay(attempt: int) -> float:
    """Bounded exponential backoff with jitter, preventing retry bursts."""
    return min(20.0, HTTP_RETRY_DELAY * (2 ** attempt)) + random.uniform(0, 0.25)


def _decode_chunked(data):
    result = bytearray()
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
        result.extend(data[pos:pos + chunk_size])
        pos += chunk_size + 2
    return bytes(result)


def _http_request(method, path, headers_extra=None, body=None, retry=0):
    """
    发送 HTTP 请求，带重试机制。
    
    Args:
        retry: 内部使用，表示当前是第几次重试（不传则为首次）
    """
    try:
        ssock = _get_thread_socket()
    except (ssl.SSLError, socket.timeout, ConnectionError, OSError) as e:
        if retry < HTTP_MAX_RETRIES:
            delay = HTTP_RETRY_DELAY * (2 ** retry)
            logger.warning(f"Socket connect failed (attempt {retry+1}/{HTTP_MAX_RETRIES+1}): {e}, retrying in {delay}s")
            time.sleep(delay)
            return _http_request(method, path, headers_extra=headers_extra, body=body, retry=retry + 1)
        raise

    headers = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: {HOST}:{PORT}\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Language: en-US,en;q=0.9\r\n"
        f"Accept-Encoding: identity\r\n"
        f"Connection: keep-alive\r\n"
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

    try:
        ssock.sendall(request_bytes)
    except (socket.timeout, ConnectionError, OSError) as e:
        _close_thread_socket()
        if retry < HTTP_MAX_RETRIES:
            delay = HTTP_RETRY_DELAY * (2 ** retry)
            logger.warning(f"Socket send failed (attempt {retry+1}/{HTTP_MAX_RETRIES+1}): {e}, retrying in {delay}s")
            time.sleep(delay)
            return _http_request(method, path, headers_extra=headers_extra, body=body, retry=retry + 1)
        raise

    # bytearray avoids quadratic copying for large ZIP/XLSX exports.
    response_data = bytearray()
    content_length = None
    header_end_found = False
    header_end_pos = 0

    while True:
        try:
            chunk = ssock.recv(65536)
            if not chunk:
                break
            response_data.extend(chunk)
        except socket.timeout:
            break

        # 解析 Content-Length（首次收到数据后立即解析）
        if not header_end_found:
            pos = response_data.find(b"\r\n\r\n")
            if pos != -1:
                header_end_found = True
                header_end_pos = pos
                header_part = response_data[:pos].decode('utf-8', errors='replace')
                for line in header_part.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        try:
                            content_length = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
                        break

        # 如果已知 Content-Length 且已收满，提前退出
        if header_end_found and content_length is not None:
            body_data = response_data[header_end_pos + 4:]
            if len(body_data) >= content_length:
                break

    # Keep a fully read Content-Length response alive for the next request on
    # this worker.  Any incomplete or ambiguous response closes the socket.

    # Content-Length 预期与实际不符，视为部分数据
    if header_end_found and content_length is not None:
        body_data = response_data[header_end_pos + 4:]
        if len(body_data) < content_length:
            _close_thread_socket()
            raise ConnectionError(f"Response body truncated: {len(body_data)}/{content_length} bytes")

    header_end = response_data.find(b"\r\n\r\n")
    if header_end == -1:
        if retry < HTTP_MAX_RETRIES:
            delay = HTTP_RETRY_DELAY * (2 ** retry)
            logger.warning(f"Cannot parse HTTP response (attempt {retry+1}/{HTTP_MAX_RETRIES+1}), retrying in {delay}s")
            time.sleep(delay)
            return _http_request(method, path, headers_extra=headers_extra, body=body, retry=retry + 1)
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
        # Chunked framing has no Content-Length; do not reuse this connection.
        _close_thread_socket()
    elif "close" in resp_headers.get("connection", "").lower() or content_length is None:
        _close_thread_socket()

    return status_line, resp_headers, header_part, resp_body


# ========== RSA 加密 ==========
def _rsa_encrypt_pem(plaintext, public_key_b64):
    from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
    from cryptography.hazmat.primitives import serialization

    pem = f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"
    public_key = serialization.load_pem_public_key(pem.encode())
    encrypted = public_key.encrypt(plaintext.encode('utf-8'), asym_padding.PKCS1v15())
    return base64.b64encode(encrypted).decode('ascii')


# ========== 登录认证 ==========
def login():
    global _session_cookie, _forgery_token

    try:
        try:
            from backend.services.auth_manager import get_auth
        except ImportError:
            from auth_manager import get_auth
        result = get_auth(HOST, PORT, USERNAME, PASSWORD)
        source = "缓存" if result["from_cache"] else "重新登录"
        logger.info(f"eFlow 鉴权成功（来源: {source}）")
        _session_cookie = result["cookie"]
        _forgery_token = result["forgery_token"]
    except Exception as e:
        logger.error(f"eFlow auth_manager 失败: {e}")
        raise

    return _session_cookie


def _headers_extra(referer):
    return (
        f"Cookie: {_session_cookie}\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Referer: {referer}\r\n"
        f"forgerydefense: {_forgery_token}\r\n"
        f"Content-Type: application/json\r\n"
        f"Origin: https://{HOST}:{PORT}\r\n"
    )


# ========== 响应解析 ==========
def parse_response(data, label=""):
    prefix = f"[{label}] " if label else ""
    if isinstance(data, dict):
        if data.get("code") not in (0, None, "0"):
            logger.warning(f"{prefix}API error code={data.get('code')}, msg={data.get('msg', '')[:100]}")
            return []
        rows = None
        for key in ("alarms", "result", "data", "records", "list", "rows", "items"):
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
    return rows if isinstance(rows, list) else []


def _safe_json_loads(resp_body, label=""):
    """
    安全解析 JSON，当 JSON 被截断时尝试恢复。
    返回 (parsed_dict_or_list, success_flag)
    """
    try:
        data = json.loads(resp_body)
        return data, True
    except json.JSONDecodeError as e:
        logger.warning(f"{label} JSON decode error: {e}, attempting recovery ({len(resp_body)} bytes)")
        # 尝试找到最后一个完整的对象/数组边界
        text = resp_body
        for char in ('}', ']'):
            last_pos = text.rfind(char)
            if last_pos > 0:
                try:
                    data = json.loads(text[:last_pos + 1])
                    logger.info(f"{label} JSON recovered by truncating at last '{char}'")
                    return data, True
                except json.JSONDecodeError:
                    continue
        logger.error(f"{label} JSON unrecoverable")
        return {}, False


# ========== 分页查询 ==========
def fetch_paginated_data(api_path, payload_base, referer, label, page_param="start", size_param="length"):
    logger.info(f"Fetching {label} data...")
    start_time = time.time()

    all_rows = []
    total = None
    page_size = payload_base.get(size_param, 2000)
    start = 0

    headers_extra = _headers_extra(referer)

    while True:
        payload = dict(payload_base)
        payload[size_param] = page_size
        payload[page_param] = start

        body = json.dumps(payload)
        status_line, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", api_path, headers_extra=headers_extra, body=body,
        )

        data = json.loads(resp_body.decode('utf-8'))

        if isinstance(data, list):
            rows = data
            all_rows.extend(rows)
            if len(rows) < page_size:
                break
            start += page_size
            continue

        if not isinstance(data, dict):
            break

        if data.get("code") not in (0, None, "0"):
            logger.warning(f"{label} API error: {data.get('msg', '')[:100]}")
            break

        if total is None:
            total = data.get("total", 0)
            logger.info(f"{label} total records: {total}")

        rows = parse_response(data, label=label)
        all_rows.extend(rows)

        if len(all_rows) >= total or len(rows) < page_size:
            break
        start += page_size
        if start >= total:
            break

    elapsed = time.time() - start_time
    logger.info(f"{label}: {len(all_rows)} records in {elapsed:.2f}s")
    return all_rows


# ========== TT / WO / CR / PM 查询配置 ==========
TT_FIELDS = "color,woId,procId,opName,pendingStatus,displayName,woNum,woInfo,status,ttSource,ticketType,projectName,templateName,creator,creatorContactInfo,ticketSeverity,createTime,alarmCategory,alarmSubcategory,alarmSeverity,alarmType,alarmId,alarmCode,subAlarmName,subAlarmNeName,subAlarmNeNaIp,appendingAlarmName,appendingAlarmNeName,appendingAlarmNeIp,netWorkType,neName,neId,neIP,impactedServiceOrNo,impactedServiceWireless,siteOutageOrNo,reasonType,slaTotalDuration,slaStatus,remainingTime,targetFinishTime,groupSlaTime,groupSlaStatus,groupSlaRemainsTime,regionLevel1Name,regionLevel2Name,assetName,siteId,assetType,siteClass,lastModifiedTime,candidateOperator,vendor,alarmOccurTime,alarmClearTime,faultDurationTime"
TT_STATUS_FILTER = '((status eq "WaitFOAccept") or (status eq "WaitFOProcess") or (status eq "WaitBOAccept") or (status eq "WaitBOProcess") or (status eq "WaitThirdAccept") or (status eq "WaitThirdProcess") or (status eq "WaitConfirm") or (status eq "Closed") or (status eq "Draft"))'
TT_REFERER = f"https://{HOST}:{PORT}/iui/ticket-mgt/v1/"
TT_PAYLOAD_BASE = {
    "customInfo": {"pageType": "allTicket"},
    "field": TT_FIELDS,
    "order": "lastModifiedTime desc",
    "relationFilter": {"eflow_ticket_ticket_asset_all": ""},
    "eflow_ticket_ticket_asset_all": "",
}

WO_FIELDS = "woId,procId,opName,ttWoid,pendingStatus,woNum,parentwoNum,status,displayName,creator,createTime,lastModifiedTime,candidateOperator,siteId,ticketSeverity,spareDomain,neName,neType,neIp,vendor,subSource,alarmOccurTime,alarmClearTime,expectedFinishTime,source,projectName,templateName,creatorContactInfo,alarmCategory,alarmSubcategory,alarmSeverity,reasonType,alarmId,alarmCode,subAlarmName,subAlarmNEName,subAlarmNEIP,appendingAlarmName,appendingAlarmNEName,appendingAlarmNEIP,networkType,neId,impactedServiceOrNo,impactedService,siteOutageOrNo,aiMindFailReasonType,faultDurationTime,slaTotalDuration,slaStatus,remainingTime,targetFinishTime,groupSlaTime,groupSlaStatus,groupSlaRemainsTime,groupSlaDeadlineTime,rcaFillingMode,regionLevel1Name,regionLevel2Name,assetName,assetType,siteClass,spareRequired,spareavailable,rejectCategory,etc,arriveSiteTime,travelTime"
WO_STATUS_FILTER = '((status eq "WaitAccept") or (status eq "WaitStartTrip") or (status eq "WaitArriveSite") or (status eq "WaitProcess") or (status eq "WaitConfirm") or (status eq "WaitLeaveSite") or (status eq "WaitSPApplication") or (status eq "WaitBONPOProcess") or (status eq "PhasedReply") or (status eq "Closed") or (status eq "Draft"))'
WO_REFERER = f"https://{HOST}:{PORT}/iui/wo-mgt/v1/"
WO_PAYLOAD_BASE = {
    "customInfo": {"pageType": "allTicket"},
    "field": WO_FIELDS,
    "order": "lastModifiedTime desc",
    "relationFilter": {"eflow_wo_wo_asset": ""},
}

CR_FIELDS = "woId,procId,opName,woNum,status,changeType,displayName,creator,requesterWorkGroupName,createTime,candidateOperator,mopMaker,mopChecker,ipRelatedActivity,implementer,implementResult,plannedStartTime,plannedEndTime,actualImplementationStartTime,actualImplementationEndTime,downtimeStart,downtimeEnd,rollbackStartTime,rollbackEndTime,closeTime,lastModifiedTime"
CR_STATUS_FILTER = '((status eq "WaitL1Approve") or (status eq "WaitL2Approve") or (status eq "WaitL3Approve") or (status eq "WaitL4Approve") or (status eq "WaitL5Approve") or (status eq "WaitL6Approve") or (status eq "WaitL7Approve") or (status eq "WaitL8Approve") or (status eq "WaitImplement") or (status eq "Implementing") or (status eq "PhaseUpdate") or (status eq "WaitUpdate") or (status eq "Closed") or (status eq "Canceled") or (status eq "Draft"))'
CR_REFERER = f"https://{HOST}:{PORT}/iui/am-mgt/v1/"
CR_PAYLOAD_BASE = {
    "customInfo": {"pageType": "allTicket"},
    "field": CR_FIELDS,
    "order": "lastModifiedTime desc",
    "length": 50,
}

PM_FIELDS = "woId,procId,opName,ftpFilePath,woNum,status,displayName,serviceClassification,creator,createTime,lastModifiedTime,candidateOperator,pmManagerRealName,assetName,assetId,source,parentWoNum,planBeginTime,planEndTime,templateName,filename,pmContentCompletedNum,pmContentTotalNum,pmtOverdue"
PM_STATUS_FILTER = '((status eq "Scheduling") or (status eq "WaitAccept") or (status eq "WaitProcess") or (status eq "Transfer") or (status eq "WaitReProcess") or (status eq "WaitPMManagerApprove") or (status eq "WaitFLMLeaderApprove") or (status eq "Draft") or (status eq "Closed"))'
PM_REFERER = f"https://{HOST}:{PORT}/iui/pm-mgt/v1/"
PM_PAYLOAD_BASE = {
    "customInfo": {"pageType": "allTicket"},
    "field": PM_FIELDS,
    "order": "lastModifiedTime desc",
    "relationFilter": {"eflow_pm_task_asset": ""},
    "length": 200,
}

# ========== Site / Person 查询配置 ==========
SITE_PAYLOAD_BASE = {"limit": 10, "skip": 0, "sort": {"cmdb#create-time": False}, "callScene": "ui"}
SITE_REFERER = f"https://{HOST}:{PORT}/iui/cmdb/"
PERSON_PAYLOAD_BASE = {"limit": 10, "skip": 0, "sort": {"cmdb#create-time": False}, "callScene": "ui"}
PERSON_REFERER = f"https://{HOST}:{PORT}/iui/cmdb/"

# ========== 时间范围 ==========
TIME_FILTER_TEMPLATE = '{status_filter} and (lastModifiedTime ge {start_ms}) and (lastModifiedTime le {end_ms})'


def _get_time_range_ms():
    start_dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
    return int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)


# ========== 导出流水线函数 ==========
TT_EXPORT_COLUMNS = [
    "displayName", "woInfo", "status", "pendingStatus", "ttSource", "ticketType", "projectName", "templateName",
    "creator", "creatorContactInfo", "ticketSeverity", "alarmCategory", "alarmSubcategory", "alarmSeverity",
    "alarmType", "alarmCode", "subAlarmName", "subAlarmNeName", "subAlarmNeIp", "appendingAlarmName",
    "appendingAlarmNeName", "appendingAlarmNeIp", "netWorkType", "neName", "neId", "neIP", "impactedServiceOrNo",
    "impactedServiceWireless", "siteOutageOrNo", "reasonType", "slaTotalDuration", "slaStatus", "remainingTime",
    "targetFinishTime", "groupSlaTime", "groupSlaStatus", "groupSlaRemainsTime", "regionLevel1Name", "regionLevel2Name",
    "assetName", "siteId", "assetType", "siteClass", "candidateOperator", "vendor", "createTime", "lastModifiedTime",
    "alarmOccurTime", "alarmClearTime", "faultDurationTime", "procId", "opName", "assignmentSuggestions",
    "description", "specificProblem", "position", "additionalInfo", "severity", "alarmServerTime", "neType",
    "alarmId", "alarmDescription", "downSiteCount", "downSiteList", "downSiteCount2g", "downSiteList2g",
    "downSiteCount3g", "downSiteList3g", "downSiteCount4g", "downSiteList4g", "downSiteCount5g", "downSiteList5g",
    "downSiteCountVip", "downSiteListVip", "preprocessed", "processTime", "aiMindFailReason", "aiMindDiagnosisResult",
    "aiMindMaintenanceSuggestions", "groupSlaDeadlineTime", "category", "subCategory", "detailCategory",
    "actualFinishTime", "faultResolvedBy", "faultRecoveryTime", "processingDescription", "siteInformation",
    "vipSite", "hubsite", "upperLevelOpticalFiberAccessPoint", "opticalFiberAccessPoint",
    "nextLevelOpticalFiberAccessPoint", "regionId", "assetId", "orgId", "fixedGeneratorId", "fixedGeneratorModel",
    "fixedGeneratorManufacturer", "latestRefuelingTime", "latestPowerGenerationTime", "maintenanceTeam",
    "maintenanceTeamContractNo", "lastMaintenanceTime", "mobileGeneratorId", "mobileGeneratorModel",
    "mobileGeneratorManufacturer", "latestRefuelingTicketNo", "latestPowerGenerationTicketNo", "batteryCount",
    "battery1Id", "battery1Model", "battery1Manufacturer", "battery2Id", "battery2Model", "battery2Manufacturer",
    "battery3Id", "battery3Model", "battery3Manufacturer", "spareRequired", "spareAvailable", "spareDomain",
    "spareDevice", "spareName", "spareNo", "SuspendDetail", "LastSuspendStatus", "LastSuspendOperator",
    "LastSuspendOperatorGroup", "LastSuspendTime", "LastResumeOperator", "LastResumeOperatorGroup",
    "LastResumeTime", "LastProcesser", "LastProcesserGroup", "LastProcessTime", "faultResolved", "woNum",
    "CreateDetail", "FOAcceptDetail", "FOProcessDetail", "BOAcceptDetail", "BOProcessDetail",
    "ThirdAcceptDetail", "ThirdProcessDetail", "ConfirmDetail", "ClosedDetail", "createAttachment",
    "foAcceptAttachment", "foProcessAttachment", "boAcceptAttachment", "boProcessAttachment",
    "thirdAcceptAttachment", "thirdProcessAttachment", "confirmAttachment", "createWOAttachment",
    "woProcessAttachment", "woBONPOProcessAttachment",
]

WO_EXPORT_COLUMNS = [
    "woNum", "parentwoNum", "displayName", "status", "pendingStatus", "creator", "createTime",
    "lastModifiedTime", "opName", "candidateOperator", "ticketSeverity", "neType", "vendor",
    "alarmOccurTime", "alarmClearTime", "expectedFinishTime", "source", "projectName",
    "templateName", "assignmentSuggestions", "creatorContactInfo", "description", "positionInfo",
    "alarmServerTime", "alarmCategory", "alarmSubcategory", "alarmSeverity", "alarmType",
    "reasonType", "alarmId", "alarmCode", "alarmDescription", "subAlarmName", "subAlarmNEName",
    "subAlarmNEIP", "appendingAlarmName", "appendingAlarmNEName", "appendingAlarmNEIP",
    "networkType", "neName", "neId", "neIp", "impactedServiceOrNo", "impactedService",
    "siteOutageOrNo", "downSiteCount", "downsitelist", "downSiteCount2g", "downSiteList2g",
    "downSiteCount3g", "downSiteList3g", "downSiteCount4g", "downSiteList4g", "downSiteCount5g",
    "downSiteList5g", "downSiteCountVip", "downSiteListVip", "aiMindPreProcessed",
    "aiMindProcessTime", "aiMindFailReason", "aiMindFailReasonType", "aiMindDiagnosisResult",
    "aiMindMaintenanceSuggestions", "faultDurationTime", "slaTotalDuration", "slaStatus",
    "remainingTime", "targetFinishTime", "groupSlaTime", "groupSlaStatus", "groupSlaRemainsTime",
    "groupSlaDeadlineTime", "category", "subCategory", "detailCategory", "additionalInformation",
    "rcaFillingMode", "actualFinishTime", "faultResolvedBy", "faultResolvingTime",
    "processingDescription", "regionId", "assetId", "assetName", "siteId", "siteName", "siteType",
    "siteInformation", "siteClass", "orgId", "vipSite", "hubSite", "regionLevel1Name",
    "regionLevel2Name", "cableLineSection", "upperNodeFiberAccessPoint", "currentFiberAccessPoint",
    "nextNodeFiberAccessPoint", "fixedGeneratorId", "fixedGeneratorModel",
    "fixedGeneratorManufacturer", "fixLatestRefuelingTime", "latestPowerGenerationTime",
    "maintenanceTeamContractNo", "lastMaintenanceTime", "mobileGeneratorId", "mobileGeneratorModel",
    "mobileGeneratorManufacturer", "dgLatestRefuelingTime", "latestRefuelingTicketNo",
    "latestPowerGenerationTicketNo", "batteryCount", "battery1ID", "battery1Model",
    "battery1Manufacturer", "battery2ID", "battery2Model", "battery2Manufacturer", "battery3ID",
    "battery3Model", "battery3Manufacturer", "spareRequired", "spareavailable", "sparedomain",
    "sparedevice", "sparename", "spareno", "rejectCategory", "detailedProgressDescription", "etc",
    "arriveSiteTime", "travelTime", "SuspendDetail", "LastSuspendStatus", "LastSuspendOperator",
    "LastSuspendOperatorGroup", "LastSuspendTime", "LastResumeOperator", "LastResumeOperatorGroup",
    "LastResumeTime", "LastRejector", "LastRejectorGroup", "LastRejectTime", "LastProcesser",
    "LastProcesserGroup", "LastProcessTime", "FaultResolved", "rejectInfo", "rejectReason",
    "CreateDetail", "AcceptDetail", "SPApplicationDetail", "StartTripDetail", "ArriveSiteDetail",
    "BONPOProcessDetail", "ProcessDetail", "ConfirmDetail", "LeaveSiteDetail", "ClosedDetail",
    "createAttachment", "acceptAttachment", "startTripAttachment", "arriveSiteAttachment",
    "processAttachment", "spApplicationAttachment", "bonpoProcessAttachment", "leaveSiteAttachment",
    "confirmAttachment",
]

WO_FIELD_DETAILS_NAME_OVERRIDES = {"displayName": "field.woDisplayName"}
WO_FIELD_DETAILS_RELATION_FILTER = {
    "alarmCode", "alarmId", "alarmType", "assetId", "assetName",
    "battery1ID", "battery2ID", "battery3ID", "category", "createTime",
    "creator", "etc", "hubSite",
}

CR_EXPORT_COLUMNS = [
    "woNum", "status", "changeType", "displayName", "description", "triggerForChange",
    "changeCategory", "subCategory", "creator", "createTime", "candidateOperator", "implementer",
    "implementerContactNumber", "implementResult", "ipRelatedActivity", "mopMaker", "mopChecker",
    "plannedStartTime", "plannedEndTime", "actualImplementationStartTime", "actualImplementationEndTime",
    "downtimeStart", "downtimeEnd", "rollbackStartTime", "rollbackEndTime", "closeTime", "vendor",
    "predictedChangeImpact", "affectedSite", "downtimeRequired", "alarmSuppressedObject",
    "lastModifiedTime", "operatingCircleOrSubCenter", "operatingDivisionOrDistrictOrThana",
    "requesterUserName", "requesterWorkGroupName", "requesterCompany", "requesterContactNumber",
    "requesterEmail", "CreateDetail", "UpdateDetail", "AnalysisDetail", "ResultFeedbackDetail",
    "DomainApproveDetail", "CRManagerConfirmDetail", "StartImplementingDetail",
    "DomainLeadConfirmDetail", "NOCApproveDetail", "L1ApproveDetail", "L2ApproveDetail",
    "L3ApproveDetail", "L4ApproveDetail", "L5ApproveDetail", "L6ApproveDetail", "L7ApproveDetail",
    "L8ApproveDetail", "ClosedDetail",
]

PM_EXPORT_COLUMNS = [
    "woNum", "status", "displayName", "serviceClassification", "pmtOverdue", "creator", "createTime",
    "lastModifiedTime", "candidateOperator", "pmManagerRealName", "assetId", "assetName", "source",
    "parentWoNum", "planBeginTime", "planEndTime", "templateName", "pmContentCompletedNum",
    "pmContentTotalNum", "CreateDetail", "CreateLastOperator", "CreateLastGroup", "CreateLastTime",
    "ScheduleDetail", "ScheduleLastOperator", "ScheduleLastGroup", "ScheduleLastTime",
    "PMManagerApproveDetail", "PMManagerApproveLastOperator", "PMManagerApproveLastGroup",
    "PMManagerApproveLastTime", "FLMLeaderApproveDetail", "FLMLeaderApproveLastOperator",
    "FLMLeaderApproveLastGroup", "FLMLeaderApproveLastTime", "ProcessDetail", "ProcessLastOperator",
    "ProcessLastGroup", "ProcessLastTime", "AcceptDetail", "AcceptLastOperator", "AcceptLastGroup",
    "AcceptLastTime", "ClosedDetail", "ClosedLastOperator", "ClosedLastGroup", "ClosedLastTime",
]

# Export API paths
TT_ASYNC_PATH = "/api/eflow-ticket/v1/export/async/eflow-tt"
TT_USERHABITS_PATH = "/api/eflow-ticket/v1/userhabits/add/eflow-tt"
TT_DOWNLOAD_PATH = "/api/eflow-ticket/v1/attachment/download/eflow-tt"
WO_ASYNC_PATH = "/api/eflow-wo/v1/export/async/eflow-wo"
WO_USERHABITS_PATH = "/api/eflow-wo/v1/userhabits/add/eflow-wo"
WO_DOWNLOAD_PATH = "/api/eflow-wo/v1/attachment/download/eflow-wo"
CR_ASYNC_PATH = "/api/eflow-asset/v1/export/async/eflow-cr"
CR_USERHABITS_PATH = "/api/eflow-asset/v1/userhabits/add/eflow-cr"
CR_DOWNLOAD_PATH = "/api/eflow-asset/v1/attachment/download/eflow-cr"
PM_ASYNC_PATH = "/api/eflow-pm/v1/export/async/eflow-pm-task"
PM_USERHABITS_PATH = "/api/eflow-pm/v1/userhabits/add/eflow-pm-task"
PM_DOWNLOAD_PATH = "/api/eflow-pm/v1/attachment/download/eflow-pm-task"
SITE_ASYNC_PATH = "/api/cmdb/v1/data/export/Site"
SITE_DOWNLOAD_PATH = "/api/cmdb/v1/attachment/download/Site"
PERSON_ASYNC_PATH = "/api/cmdb/v1/data/export/Person"
PERSON_DOWNLOAD_PATH = "/api/cmdb/v1/attachment/download/Person"


# ========== 导出通用函数 ==========
def _create_export_task(async_path, referer, payload, label):
    """创建异步导出任务，返回 (ftp_file_path, file_name)"""
    headers_extra = _headers_extra(referer)
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request("POST", async_path, headers_extra=headers_extra, body=body)

    if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
        try:
            resp_body = gzip.decompress(resp_body)
        except Exception:
            pass

    ftp_file_path = ""
    file_name = payload.get("fileName", "")
    if "200" in status:
        try:
            resp_data = json.loads(resp_body.decode('utf-8'))
            if isinstance(resp_data, dict):
                ftp_file_path = resp_data.get("ftpFilePath", "")
                if not ftp_file_path and isinstance(resp_data.get("data"), dict):
                    ftp_file_path = resp_data["data"].get("ftpFilePath", "")
        except Exception as e:
            logger.warning(f"{label} export async parse failed: {e}")
    logger.info(f"{label} export task created: {file_name}, ftp={ftp_file_path}")
    return ftp_file_path, file_name


def _wait_export_ready(list_path, referer, file_name, label, max_wait=300, interval=10):
    """轮询等待导出完成，返回 (ftp_path, item)"""
    headers_extra = _headers_extra(referer)
    body = json.dumps({})

    for attempt in range(max_wait // interval):
        status, hdrs, raw_hdrs, resp_body = _http_request("POST", list_path, headers_extra=headers_extra, body=body)

        if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
            try:
                resp_body = gzip.decompress(resp_body)
            except Exception:
                pass

        try:
            data = json.loads(resp_body.decode('utf-8'))
            items = data if isinstance(data, list) else data.get("result", data.get("data", []))
            for item in items:
                item_file_name = item.get("fileName", "")
                if file_name in item_file_name or item_file_name == file_name:
                    status_str = item.get("status", "")
                    uuid_val = item.get("uuid", "")
                    rate = item.get("rate", "")
                    if status_str.lower() in ("success", "sucess") or rate == "100%":
                        ftp_path = item.get("ftpFilePath", "")
                        if not ftp_path and uuid_val:
                            ftp_path = f"{uuid_val}.zip"
                        return ftp_path, item
        except Exception:
            pass

        logger.info(f"{label} waiting export... ({attempt + 1}/{max_wait // interval})")
        time.sleep(interval)

    return "", None


def _download_export_zip(download_path, referer, file_name, ftp_file_path, table_type, label, output_dir):
    """下载导出的 ZIP 文件"""
    headers_extra = _headers_extra(referer)
    file_name_body = file_name if file_name.endswith(".zip") else f"{file_name}.zip"
    ftp_path_body = ftp_file_path if ftp_file_path.endswith(".zip") else f"{ftp_file_path}.zip"
    body_payload = {"fileName": file_name_body, "tableType": table_type}
    if ftp_file_path:
        body_payload["ftpFilePath"] = ftp_path_body

    body = json.dumps(body_payload)
    status, hdrs, raw_hdrs, resp_body = _http_request("POST", download_path, headers_extra=headers_extra, body=body)

    if "200" not in status:
        raise Exception(f"{label} download failed: {status}")

    filename = file_name if file_name.endswith(".zip") else f"{file_name}.zip"
    cd = hdrs.get("content-disposition", "")
    if cd:
        fn_match = re.search(r'filename=["\']?([^"\';]+)', cd)
        if fn_match:
            filename = fn_match.group(1)

    zip_path = os.path.join(output_dir, filename)
    seq = 1
    while os.path.exists(zip_path):
        base, ext = os.path.splitext(filename)
        zip_path = os.path.join(output_dir, f"{base}_{seq}{ext}")
        seq += 1

    with open(zip_path, "wb") as f:
        f.write(resp_body)
    logger.info(f"{label} ZIP saved: {zip_path}")
    return zip_path


def _read_export_zip(zip_path, label):
    """读取导出 ZIP 中的数据文件，返回 records list"""
    import zipfile
    import pandas as pd

    with zipfile.ZipFile(zip_path, "r") as z:
        files = z.namelist()

    data_files = [f for f in files if f.lower().endswith((".xlsx", ".xls", ".csv"))]
    if not data_files:
        raise Exception(f"No data file found in {label} ZIP")

    read_start = time.time()
    dfs = []
    with zipfile.ZipFile(zip_path, "r") as z:
        for data_file in data_files:
            # Parse directly from the archive: much less disk I/O and no
            # extract-directory contention when all pipelines finish together.
            content = io.BytesIO(z.read(data_file))
            if data_file.lower().endswith(".csv"):
                dfs.append(pd.read_csv(content))
            else:
                dfs.append(pd.read_excel(content))

    df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    logger.info(f"{label}: {len(df)} rows, {len(df.columns)} columns (read {time.time() - read_start:.2f}s)")

    return df.to_dict("records")


def _set_export_columns(userhabits_path, referer, export_config, label):
    """设置导出列配置"""
    headers_extra = _headers_extra(referer)
    body = json.dumps(export_config)
    status, _, _, _ = _http_request("POST", userhabits_path, headers_extra=headers_extra, body=body)
    logger.info(f"{label} set export columns: {status}")


def _prepare_export(api_path, referer, payload, label):
    """预查询以激活导出"""
    headers_extra = _headers_extra(referer)
    body = json.dumps(payload)
    status, _, _, _ = _http_request("POST", api_path, headers_extra=headers_extra, body=body)
    logger.info(f"{label} prepare export: {status}")


# ========== 各端点导出流水线 ==========
def _fetch_tt_pipeline(start_ms, end_ms, tmp_dir):
    tt_filter = TIME_FILTER_TEMPLATE.format(status_filter=TT_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)

    # Prepare + set columns + create task
    _prepare_export(TT_API_PATH, TT_REFERER, {
        "customInfo": {"pageType": "allTicket"}, "field": TT_FIELDS,
        "filter": tt_filter, "length": 1, "order": "lastModifiedTime desc",
        "relationFilter": {"eflow_ticket_ticket_asset_all": ""}, "start": 0,
    }, "TT")

    export_config = {"type": "Export", "serviceName": "eflow-ticket", "config": json.dumps(TT_EXPORT_COLUMNS)}
    _set_export_columns(TT_USERHABITS_PATH, TT_REFERER, export_config, "TT")

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"eflow-tt-export-{USERNAME}-{timestamp}"
    field_details = {col: {"value": col, "name": f"field.{col}", "checked": True} for col in TT_EXPORT_COLUMNS}
    payload = {
        "fileName": file_name, "type": "xlsx", "createTimeRange": "", "exportType": "0",
        "customInfo": {"pageType": "allTicket"}, "field": TT_EXPORT_COLUMNS, "fieldDetails": field_details,
        "filter": tt_filter,
        "relationFilter": {"eflow_ticket_ticket_export_op": "", "eflow_ticket_ticket_attachment_export": ""},
        "relationTable": [], "tableName": "eflow_ticket_ticket_wo", "tableType": "eflow-tt",
    }
    ftp_file_path, _ = _create_export_task(TT_ASYNC_PATH, TT_REFERER, payload, "TT")

    logger.info("TT: waiting 5s before polling...")
    time.sleep(5)

    # List path for TT
    tt_list_path = "/api/eflow-ticket/v1/export/list/eflow-tt"
    ftp_file_path, _ = _wait_export_ready(tt_list_path, TT_REFERER, file_name, "TT")
    zip_path = _download_export_zip(TT_DOWNLOAD_PATH, TT_REFERER, file_name, ftp_file_path, "eflow-tt", "TT", tmp_dir)
    rows = _read_export_zip(zip_path, "TT")
    return ("eFlow TT", rows)


def _fetch_wo_pipeline(start_ms, end_ms, tmp_dir):
    wo_filter = TIME_FILTER_TEMPLATE.format(status_filter=WO_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)

    _prepare_export(WO_API_PATH, WO_REFERER, {
        "customInfo": {"pageType": "allTicket"}, "field": WO_FIELDS,
        "filter": wo_filter, "length": 1, "order": "lastModifiedTime desc",
        "relationFilter": {"eflow_wo_wo_asset": ""}, "start": 0,
    }, "WO")

    export_config = {"type": "Export", "serviceName": "eflow-wo", "config": json.dumps(WO_EXPORT_COLUMNS)}
    _set_export_columns(WO_USERHABITS_PATH, WO_REFERER, export_config, "WO")

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"eflow-wo-export-{USERNAME}-{timestamp}"
    field_details = {}
    for col in WO_EXPORT_COLUMNS:
        meta = {"value": col, "name": WO_FIELD_DETAILS_NAME_OVERRIDES.get(col, f"field.{col}"), "checked": True}
        if col.endswith("Detail") or col.endswith("Attachment"):
            meta["hide"] = True
        if col in WO_FIELD_DETAILS_RELATION_FILTER:
            meta["relationFilter"] = "eflow_wo_wo_export_op"
        field_details[col] = meta
    payload = {
        "fileName": file_name, "type": "xlsx", "createTimeRange": "", "exportType": "0",
        "field": WO_EXPORT_COLUMNS, "fieldDetails": field_details, "filter": wo_filter,
        "relationFilter": {"eflow_wo_wo_export_op": "", "eflow_wo_wo_attachment_export": ""},
        "relationTable": [], "tableName": "eflow_wo_wo_wo", "tableType": "eflow-wo",
    }
    ftp_file_path, _ = _create_export_task(WO_ASYNC_PATH, WO_REFERER, payload, "WO")

    logger.info("WO: waiting 5s before polling...")
    time.sleep(5)

    wo_list_path = "/api/eflow-wo/v1/export/list/eflow-wo"
    ftp_file_path, _ = _wait_export_ready(wo_list_path, WO_REFERER, file_name, "WO")
    zip_path = _download_export_zip(WO_DOWNLOAD_PATH, WO_REFERER, file_name, ftp_file_path, "eflow-wo", "WO", tmp_dir)
    rows = _read_export_zip(zip_path, "WO")
    return ("eFlow WO", rows)


def _fetch_cr_pipeline(start_ms, end_ms, tmp_dir):
    cr_filter = TIME_FILTER_TEMPLATE.format(status_filter=CR_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)

    _prepare_export(CR_API_PATH, CR_REFERER, {
        "customInfo": {"pageType": "allTicket"}, "field": CR_FIELDS,
        "filter": cr_filter, "length": 1, "order": "lastModifiedTime desc", "start": 0,
    }, "CR")

    export_config = {"type": "Export", "serviceName": "eflow-asset", "config": json.dumps(CR_EXPORT_COLUMNS)}
    _set_export_columns(CR_USERHABITS_PATH, CR_REFERER, export_config, "CR")

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"eflow-cr-export-{USERNAME}-{timestamp}"
    field_details = {}
    for col in CR_EXPORT_COLUMNS:
        meta = {"value": col, "name": f"field.{col}", "checked": True}
        if col.endswith("Detail"):
            meta["hide"] = True
        field_details[col] = meta
    payload = {
        "fileName": file_name, "type": "xlsx", "createTimeRange": "", "exportType": "0",
        "field": CR_EXPORT_COLUMNS, "fieldDetails": field_details, "filter": cr_filter,
        "relationFilter": {"eflow_am_cr_op": ""}, "relationTable": [],
        "tableName": "eflow_am_cr_wo", "tableType": "eflow-cr",
    }
    ftp_file_path, _ = _create_export_task(CR_ASYNC_PATH, CR_REFERER, payload, "CR")

    logger.info("CR: waiting 5s before polling...")
    time.sleep(5)

    cr_list_path = "/api/eflow-asset/v1/export/list/eflow-cr"
    ftp_file_path, _ = _wait_export_ready(cr_list_path, CR_REFERER, file_name, "CR")
    zip_path = _download_export_zip(CR_DOWNLOAD_PATH, CR_REFERER, file_name, ftp_file_path, "eflow-cr", "CR", tmp_dir)
    rows = _read_export_zip(zip_path, "CR")
    return ("eFlow CR", rows)


def _fetch_pm_pipeline(start_ms, end_ms, tmp_dir):
    pm_filter = TIME_FILTER_TEMPLATE.format(status_filter=PM_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)

    _prepare_export(PM_API_PATH, PM_REFERER, {
        "customInfo": {"pageType": "allTicket"}, "field": PM_FIELDS,
        "filter": pm_filter, "length": 1, "order": "lastModifiedTime desc",
        "relationFilter": {"eflow_pm_task_asset": ""}, "start": 0,
    }, "PM")

    export_config = {"type": "Export", "serviceName": "eflow-pm", "config": json.dumps(PM_EXPORT_COLUMNS)}
    _set_export_columns(PM_USERHABITS_PATH, PM_REFERER, export_config, "PM")

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"eflow-pm-task-export-{USERNAME}-{timestamp}"
    field_details = {}
    for col in PM_EXPORT_COLUMNS:
        meta = {"value": col, "name": f"field.{col}", "checked": True}
        if col.endswith("Detail"):
            meta["hide"] = True
        field_details[col] = meta
    payload = {
        "fileName": file_name, "type": "xlsx", "createTimeRange": "", "exportType": "0",
        "field": PM_EXPORT_COLUMNS, "fieldDetails": field_details, "filter": pm_filter,
        "relationFilter": {"eflow_pm_export_op": ""}, "relationTable": [],
        "tableName": "eflow_pm_task_wo", "tableType": "eflow-pm-task",
    }
    ftp_file_path, _ = _create_export_task(PM_ASYNC_PATH, PM_REFERER, payload, "PM")

    logger.info("PM: waiting 5s before polling...")
    time.sleep(5)

    pm_list_path = "/api/eflow-pm/v1/export/list/eflow-pm-task"
    ftp_file_path, _ = _wait_export_ready(pm_list_path, PM_REFERER, file_name, "PM")
    zip_path = _download_export_zip(PM_DOWNLOAD_PATH, PM_REFERER, file_name, ftp_file_path, "eflow-pm-task", "PM", tmp_dir)
    rows = _read_export_zip(zip_path, "PM")
    return ("eFlow PM", rows)


def _fetch_site_pipeline(tmp_dir):
    """CMDB Site 导出为同步下载，内存直读不落盘"""
    import pandas as pd
    headers_extra = _headers_extra(SITE_REFERER)
    payload = {"callScene": "ui"}
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request("POST", SITE_ASYNC_PATH, headers_extra=headers_extra, body=body)

    if "200" not in status:
        raise Exception(f"Site export failed: {status}")

    t0 = time.time()
    df = pd.read_excel(io.BytesIO(bytes(resp_body)))
    logger.info(f"Site: {len(df)} rows, {len(df.columns)} columns (read {time.time() - t0:.2f}s)")
    return ("Site", df.to_dict("records"))


def _fetch_person_pipeline(tmp_dir):
    """CMDB Person 导出为同步下载，内存直读不落盘"""
    import pandas as pd
    headers_extra = _headers_extra(PERSON_REFERER)
    payload = {"callScene": "ui"}
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request("POST", PERSON_ASYNC_PATH, headers_extra=headers_extra, body=body)

    if "200" not in status:
        raise Exception(f"Person export failed: {status}")

    t0 = time.time()
    df = pd.read_excel(io.BytesIO(bytes(resp_body)))
    logger.info(f"Person: {len(df)} rows, {len(df.columns)} columns (read {time.time() - t0:.2f}s)")
    return ("Person", df.to_dict("records"))


# ========== Realtime / History Alarm ==========
ALARM_REFERER = f"https://{HOST}:{PORT}/iui/fm/angularFm/dist/index.html"

# 实时/历史告警共用 alarmcodeconds，保证过滤条件一致。
ALARM_CODE_CONDS = [
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
]

ALARM_CONDITION = {
    "alarmcodeconds": ALARM_CODE_CONDS,
    "alarmcodefiltermode": 0, "visibles": [1], "timezonetype": 0,
    "sortinfo": {"sortdirection": 0, "sortfield": "servertime", "combinesortinfos": []},
    "extensionconds": {"maintainstatus": {"valuelist": ["0"]}},
    "querymetype": 2, "refresh": True,
}

# FM History Alarm 查询条件：近 3 天（动态计算）
HIS_ALARM_DAYS_BACK = int(os.environ.get("EFLOW_HIS_ALARM_DAYS", "3"))


def _get_his_alarm_time_range():
    """返回历史告警查询的起止时间 (start_dt, end_dt)"""
    from datetime import timedelta
    end_dt = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
    start_dt = (end_dt - timedelta(days=HIS_ALARM_DAYS_BACK)).replace(hour=0, minute=0, second=0)
    return start_dt, end_dt


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
    "Site Status", "Networktype", "Alarm Source", "Site Name", "neip", "restypename",
    "RAN Site Type", "MW Layer", "Vendor", "Power Infomation", "Transmission Type",
    "Site ID", "Site Attribute", "TT ID", "durationname", "codename", "Alarm Title",
    "Region", "link", "perceivedseverityname", "reasonname", "POP Site", "clearstatename",
    "Circle", "Site Class", "Type", "Link Path", "Site VIP Level", "Cell Name",
    "Assign RuleName", "RAN Type", "Latest Match Time", "First Match Time",
    "Assign Delay", "rootcount", "auxiliarycount",
]


def _normalize_alarm_rows(rows):
    """将 FM Active Alarm 的字段对象转换为以 columnname 为键的字典列表"""
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


def _fetch_alarm_pipeline():
    """获取实时告警数据"""
    logger.info("Fetching active alarm data...")
    start_time = time.time()

    all_rows = []
    total = None
    page_size = 200
    page = 1

    headers_extra = (
        f"Cookie: {_session_cookie}\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Referer: {ALARM_REFERER}\r\n"
        f"forgerydefense: {_forgery_token}\r\n"
        f"Content-Type: application/json\r\n"
        f"Origin: https://{HOST}:{PORT}\r\n"
        f"LogTracking: True\r\n"
    )

    query_id = "T" + uuid.uuid4().hex
    active_tab_id = "fm-active_" + uuid.uuid4().hex

    while True:
        now = datetime.now(timezone.utc)
        payload = {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}"[:-3] + "Z",
            "condition": ALARM_CONDITION, "manual": False,
            "page": page, "pagesize": page_size,
            "queryid": query_id, "activeTabId": active_tab_id,
        }

        body = json.dumps(payload)
        status_line, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", ALARM_API_PATH, headers_extra=headers_extra, body=body,
        )

        data = json.loads(resp_body.decode('utf-8'))

        if isinstance(data, list):
            rows = _normalize_alarm_rows(data)
            all_rows.extend(rows)
            if len(rows) < page_size:
                break
            page += 1
            continue

        if not isinstance(data, dict):
            break

        if data.get("code") not in (0, None, "0"):
            break

        if total is None:
            total = data.get("totalcount") or data.get("total", 0)
            logger.info(f"Alarm total records: {total}")

        rows = parse_response(data, label="Alarm")
        rows = _normalize_alarm_rows(rows)
        all_rows.extend(rows)

        if len(rows) < page_size:
            break
        page += 1
        if page > 500:
            break

    elapsed = time.time() - start_time
    logger.info(f"Alarm: {len(all_rows)} records in {elapsed:.2f}s")
    return ("realtime_alarm", all_rows)


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


def _fetch_history_alarm_pipeline():
    """获取历史告警数据（近 N 天，默认 7 天）"""
    logger.info("Fetching history alarm data...")
    start_time = time.time()

    all_rows = []
    total = None
    page_size = 2000
    offset = 0

    headers_extra = (
        f"Cookie: {_session_cookie}\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Referer: {ALARM_REFERER}\r\n"
        f"forgerydefense: {_forgery_token}\r\n"
        f"Content-Type: application/json\r\n"
        f"Origin: https://{HOST}:{PORT}\r\n"
        f"LogTracking: True\r\n"
    )

    his_start, his_end = _get_his_alarm_time_range()
    logger.info(f"History alarm range: {his_start.isoformat()} ~ {his_end.isoformat()}")

    while True:
        now = datetime.now(timezone.utc)
        now_ms = int(now.timestamp() * 1000)
        iso_ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}"[:-3] + "Z"

        condition = dict(HIS_ALARM_CONDITION)
        condition["alarmraisedtime"] = {
            "mode": "0",
            "start": int(his_start.timestamp() * 1000),
            "end": int(his_end.timestamp() * 1000),
        }
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

        logger.info(f"History alarm offset={offset}: {len(resp_body)} bytes, {status_line}")

        data, parse_ok = _safe_json_loads(resp_body.decode('utf-8'), label=f"History(offset={offset})")
        if not parse_ok or not isinstance(data, dict):
            logger.warning(f"Unexpected history response type: {type(data)}")
            break

        if data.get("code") not in (0, None, "0"):
            logger.warning(f"History API error code={data.get('code')}, msg={data.get('msg', '')[:100]}")
            break

        if total is None:
            total = data.get("totalcount") or data.get("total", 0)
            logger.info(f"History alarm total records: {total}")

        rows = parse_response(data, label="History")
        if not isinstance(rows, list):
            rows = []

        rows = _normalize_alarm_rows(rows)
        if not rows:
            break

        prev_count = len(all_rows)
        all_rows.extend(rows)
        if len(all_rows) == prev_count:
            logger.warning("No new history records, stopping pagination")
            break

        if len(rows) < page_size:
            break

        offset += page_size
        if offset > 100000:
            logger.warning("Reached max history offset limit (100000)")
            break

    elapsed = time.time() - start_time
    logger.info(f"History Alarm: {len(all_rows)} records in {elapsed:.2f}s")
    return ("history_alarm", all_rows)


# ========== 告警数据持久化 ==========
def write_alarm_csv(data):
    """将规范化后的原始告警数据写入 CSV，只保留最新一个文件。"""
    output_file = os.path.join(DATA_DIR, "eflow_alarm_raw.csv")

    if not isinstance(data, list) or not data:
        logger.warning("Alarm CSV: no data")
        return output_file

    fieldnames = sorted(set().union(*(row.keys() for row in data)))
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)

    logger.info(f"Alarm CSV saved: {output_file}, {len(data)} records")
    return output_file


# ========== 告警数据持久化 ==========
def write_alarm_sqlite(data):
    """过滤指定字段并替换写入 eflow.sqlite3 的 realtime_alarm 表。"""
    db_file = os.path.join(DATA_DIR, "eflow.sqlite3")

    if not isinstance(data, list) or not data:
        logger.warning("Alarm SQLite: no data")
        return db_file

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    col_defs = ", ".join([f'"{col}" TEXT' for col in ALARM_COLUMNS])
    cursor.execute("DROP TABLE IF EXISTS realtime_alarm")
    cursor.execute(f"CREATE TABLE realtime_alarm ({col_defs})")

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

    logger.info(f"Alarm SQLite saved: {db_file}, {len(rows_to_insert)} records")
    return db_file


# ========== 历史告警数据持久化 ==========
def write_history_alarm_csv(data):
    """将规范化后的历史告警数据写入 CSV，只保留最新一个文件。"""
    output_file = os.path.join(DATA_DIR, "eflow_history_alarm_raw.csv")

    if not isinstance(data, list) or not data:
        logger.warning("History Alarm CSV: no data")
        return output_file

    fieldnames = sorted(set().union(*(row.keys() for row in data)))
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)

    logger.info(f"History Alarm CSV saved: {output_file}, {len(data)} records")
    return output_file


def write_history_alarm_sqlite(data):
    """过滤指定字段并替换写入 eflow.sqlite3 的 history_alarm 表。"""
    db_file = os.path.join(DATA_DIR, "eflow.sqlite3")

    if not isinstance(data, list) or not data:
        logger.warning("History Alarm SQLite: no data")
        return db_file

    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    col_defs = ", ".join([f'"{col}" TEXT' for col in ALARM_COLUMNS])
    cursor.execute("DROP TABLE IF EXISTS history_alarm")
    cursor.execute(f"CREATE TABLE history_alarm ({col_defs})")

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

    logger.info(f"History Alarm SQLite saved: {db_file}, {len(rows_to_insert)} records")
    return db_file


# ========== 告警写入仪表盘主库 db/app.db ==========
def _clean_column_name(col: str) -> str:
    """通用列名清洗：转 snake_case（本地副本，避免跨模块依赖）。"""
    if not isinstance(col, str):
        col = str(col)
    col = col.strip()
    col = re.sub(r'[^\w\s]', '_', col)
    col = re.sub(r'\s+', '_', col)
    col = re.sub(r'_+', '_', col)
    col = col.strip('_').lower()
    if col and col[0].isdigit():
        col = f'col_{col}'
    return col or 'unnamed'


def _write_alarm_to_appdb(table_name: str, rows, index_cols: list):
    """将完整告警数据（全字段 + snake_case 归一化）写入仪表盘主库 db/app.db。

    仪表盘的 routers（gis.py / alarm_dashboard.py）从 db/app.db 读取 realtime_alarm /
    history_alarm，之前的 write_alarm_sqlite 只写入 data/eflow/eflow.sqlite3，导致
    任务显示 Success 但仪表盘数据不更新。此函数补全写入主库，列结构与 routers 期望一致。
    """
    if not isinstance(rows, list) or not rows:
        logger.warning(f"{table_name} -> app.db: no data, skip")
        return
    try:
        df = pd.DataFrame(rows)
        # 列名归一化为 snake_case（与 sync_from_eflow_api._sync_*_alarm 一致）
        new_cols = [_clean_column_name(c) for c in df.columns]
        seen = {}
        final_cols = []
        for c in new_cols:
            if c in seen:
                seen[c] += 1
                final_cols.append(f"{c}_{seen[c]}")
            else:
                seen[c] = 0
                final_cols.append(c)
        df.columns = final_cols
        # list/dict 列序列化为 JSON（SQLite 不支持）
        object_cols = df.select_dtypes(include=["object"]).columns
        for col in object_cols:
            if df[col].apply(lambda x: isinstance(x, (list, dict))).any():
                df[col] = df[col].apply(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else x)
        df["_sync_time"] = datetime.now().isoformat()

        conn = sqlite3.connect(APP_DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        df.to_sql(table_name, conn, if_exists="replace", index=False, chunksize=5000)
        for idx_col in index_cols:
            if idx_col in df.columns:
                conn.execute(f'CREATE INDEX IF NOT EXISTS idx_{table_name}_{idx_col} ON {table_name}({idx_col})')
        conn.commit()
        conn.close()
        logger.info(f"{table_name} 已写入 app.db: {len(df)} 行, {len(df.columns)} 列")
    except Exception as e:
        logger.error(f"{table_name} 写入 app.db 失败: {e}")


# ========== 告警独立入口 ==========
def fetch_and_save_active_alarm():
    """
    仅同步实时告警：登录 eFlow -> 获取实时告警 -> 保存 SQLite（不生成 CSV）
    """
    logger.info("Starting active alarm sync...")
    start_time = time.time()

    if not _session_cookie:
        login()

    alarm_result = _fetch_alarm_pipeline()
    _, alarm_rows = alarm_result if isinstance(alarm_result, tuple) else ("realtime_alarm", alarm_result)
    write_alarm_sqlite(alarm_rows)
    _write_alarm_to_appdb("realtime_alarm", alarm_rows, ["site_id", "tt_id", "alarmraisedtime", "site_name"])

    elapsed = time.time() - start_time
    logger.info(f"Active alarm sync completed in {elapsed:.2f}s, {len(alarm_rows)} records")
    return {"realtime_alarm": alarm_rows}


def fetch_and_save_history_alarm():
    """
    仅同步历史告警：登录 eFlow -> 获取历史告警 -> 过滤 TT ID -> 保存 SQLite（不生成 CSV）
    """
    logger.info("Starting history alarm sync...")
    start_time = time.time()

    if not _session_cookie:
        login()

    his_result = _fetch_history_alarm_pipeline()
    _, his_rows = his_result if isinstance(his_result, tuple) else ("history_alarm", his_result)
    filtered_his_rows = _filter_rows_with_tt_id(his_rows)
    logger.info(
        f"History alarm filtered: {len(his_rows)} -> {len(filtered_his_rows)} "
        f"(removed {len(his_rows) - len(filtered_his_rows)} rows with empty/invalid TT ID)"
    )
    write_history_alarm_sqlite(filtered_his_rows)
    _write_alarm_to_appdb("history_alarm", filtered_his_rows, ["site_id", "tt_id", "alarmraisedtime", "region"])

    elapsed = time.time() - start_time
    logger.info(f"History alarm sync completed in {elapsed:.2f}s, {len(filtered_his_rows)} records")
    return {"history_alarm": filtered_his_rows}


def fetch_and_save_alarm_data():
    """
    同步实时告警 + 历史告警（合并入口，用于统一调度）
    """
    logger.info("Starting alarm (active + history) sync...")
    start_time = time.time()

    result = {}
    try:
        active_result = fetch_and_save_active_alarm()
        result.update(active_result)
    except Exception as e:
        logger.error(f"Active alarm failed: {e}")
        result["realtime_alarm"] = []

    try:
        history_result = fetch_and_save_history_alarm()
        result.update(history_result)
    except Exception as e:
        logger.error(f"History alarm failed: {e}")
        result["history_alarm"] = []

    elapsed = time.time() - start_time
    logger.info(
        f"All alarm sync completed in {elapsed:.2f}s: "
        f"active={len(result.get('realtime_alarm', []))}, history={len(result.get('history_alarm', []))}"
    )
    return result


# ========== Excel 写入工具 ==========
def _write_sheet(writer, df, sheet_name):
    """将 DataFrame 写入 Excel sheet，带格式（标题行蓝色白字 + 自适应列宽）"""
    df.to_excel(writer, index=False, sheet_name=sheet_name)
    worksheet = writer.sheets[sheet_name]
    workbook = writer.book

    header_format = workbook.add_format({
        "bold": True,
        "bg_color": "#4472C4",
        "font_color": "#FFFFFF",
    })
    worksheet.set_row(0, None, header_format)

    # 列宽采样计算
    sample_limit = 10000
    for col_idx, col in enumerate(df.columns):
        col_len = len(str(col))
        if len(df) > 0:
            if len(df) > sample_limit:
                sample = df[col].iloc[:sample_limit].astype(str).str.len().max()
            else:
                sample = df[col].astype(str).str.len().max()
            sample_int = int(sample) if pd.notna(sample) else 0
            max_len = max(col_len, sample_int)
        else:
            max_len = col_len
        worksheet.set_column(col_idx, col_idx, min(max_len + 2, 50))


def _table_name(sheet_name):
    """将 sheet 名转换为 SQLite 表名（小写 + 下划线）"""
    return sheet_name.replace(" ", "_").lower()


def save_to_sqlite(sheets_data):
    """
    将数据保存到 SQLite 数据库。
    
    Args:
        sheets_data: 可以是 dict{sheet_name: rows} 或 list[(sheet_name, rows), ...]
    
    Returns:
        db_path: SQLite 文件路径
    """
    import pandas as pd

    start_time = time.time()
    db_path = os.path.join(DATA_DIR, "eflow.sqlite3")
    conn = sqlite3.connect(db_path)

    items = sheets_data.items() if isinstance(sheets_data, dict) else sheets_data
    for entry in items:
        sheet_name, rows = entry if isinstance(entry, tuple) else (entry[0], entry[1])
        t0 = time.time()
        if not isinstance(rows, list) or not rows:
            logger.warning(f"[SKIP] {sheet_name}: no data")
            continue
        df = pd.DataFrame(rows)
        # SQLite 不支持 list/dict 类型，对 object/str 列检测并转换
        object_cols = df.select_dtypes(include=["object", "str"]).columns
        for col in object_cols:
            if df[col].apply(lambda x: isinstance(x, (list, dict))).any():
                df[col] = df[col].apply(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else x)
        table = _table_name(sheet_name)
        df.to_sql(table, conn, if_exists="replace", index=False, chunksize=5000)
        logger.info(f"SQLite table '{table}': {len(df)} rows, {len(df.columns)} columns ({time.time() - t0:.2f}s)")

    conn.close()
    logger.info(f"SQLite saved: {db_path} (total {time.time() - start_time:.2f}s)")
    return db_path


def write_excel_from_sqlite(sheets_data):
    """
    从 SQLite 读取数据并生成格式化 Excel 报告。
    
    Args:
        sheets_data: 可以是 dict{sheet_name: rows} 或 list[(sheet_name, rows), ...]
    
    Returns:
        output_file: Excel 文件路径
    """
    import pandas as pd

    start_time = time.time()
    db_path = os.path.join(DATA_DIR, "eflow.sqlite3")
    conn = sqlite3.connect(db_path)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(DATA_DIR, f"eflow_{timestamp}.xlsx")

    seq = 1
    while os.path.exists(output_file):
        output_file = os.path.join(DATA_DIR, f"eflow_{timestamp}_{seq}.xlsx")
        seq += 1

    items = sheets_data.items() if isinstance(sheets_data, dict) else sheets_data
    with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
        for entry in items:
            sheet_name, _ = entry if isinstance(entry, tuple) else (entry[0], entry[1])
            t0 = time.time()
            table = _table_name(sheet_name)
            df = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
            if df.empty:
                logger.warning(f"[SKIP] {sheet_name}: no data")
                continue
            _write_sheet(writer, df, sheet_name)
            logger.info(f"Excel {sheet_name}: {len(df)} rows, {len(df.columns)} columns ({time.time() - t0:.2f}s)")

    conn.close()
    logger.info(f"Excel saved: {output_file} (total {time.time() - start_time:.2f}s)")

    # 删除旧 Excel 文件，只保留最新
    for old_file in glob.glob(os.path.join(DATA_DIR, "eflow_*.xlsx")):
        if os.path.abspath(old_file) != os.path.abspath(output_file):
            try:
                os.remove(old_file)
                logger.info(f"[CLEAN] Deleted old file: {os.path.basename(old_file)}")
            except OSError:
                logger.warning(f"[WARN] Cannot delete (in use): {os.path.basename(old_file)}")

    return output_file


def cleanup_old_export_files(output_dir=None):
    """SQLite 生成后，按类型只保留最新导出文件，删除旧文件和解压目录。"""
    if output_dir is None:
        output_dir = DATA_DIR

    zip_patterns = [
        "eflow-tt-export-*.zip",
        "eflow-wo-export-*.zip",
        "eflow-cr-export-*.zip",
        "eflow-pm-task-export-*.zip",
        "Site-export-*.zip",
        "Person-export-*.zip",
    ]

    # 按类型保留最新 ZIP，删除旧 ZIP
    for pattern in zip_patterns:
        files = glob.glob(os.path.join(output_dir, pattern))
        if len(files) <= 1:
            continue
        files.sort(key=os.path.getmtime)
        for old_file in files[:-1]:
            try:
                os.remove(old_file)
                logger.info(f"[CLEAN] Deleted old export ZIP: {os.path.basename(old_file)}")
            except OSError as e:
                logger.warning(f"[WARN] Cannot delete {old_file}: {e}")

    # Site/Person 为同步 XLSX 下载，保留最新，删除旧 XLSX
    xlsx_patterns = [
        "Site*.xlsx",
        "Person*.xlsx",
    ]
    for pattern in xlsx_patterns:
        files = glob.glob(os.path.join(output_dir, pattern))
        if len(files) <= 1:
            continue
        files.sort(key=os.path.getmtime)
        for old_file in files[:-1]:
            try:
                os.remove(old_file)
                logger.info(f"[CLEAN] Deleted old export XLSX: {os.path.basename(old_file)}")
            except OSError as e:
                logger.warning(f"[WARN] Cannot delete {old_file}: {e}")

    # 删除残留的解压目录
    for name in os.listdir(output_dir):
        full_path = os.path.join(output_dir, name)
        if not os.path.isdir(full_path):
            continue
        if (
            name.startswith("eflow-tt-export-")
            or name.startswith("eflow-wo-export-")
            or name.startswith("eflow-cr-export-")
            or name.startswith("eflow-pm-task-export-")
            or name.startswith("Site-export-")
            or name.startswith("Person-export-")
        ):
            try:
                shutil.rmtree(full_path)
                logger.info(f"[CLEAN] Deleted old extract dir: {name}")
            except OSError as e:
                logger.warning(f"[WARN] Cannot delete dir {full_path}: {e}")


def upload_to_ftp(local_file_path, remote_filename=None):
    """
    将本地文件上传到 FTP 服务器。
    
    Args:
        local_file_path: 本地文件路径
        remote_filename: 远程文件名，默认使用本地文件名
    
    Returns:
        bool: 是否上传成功
    """
    if not local_file_path or not os.path.exists(local_file_path):
        logger.warning(f"FTP upload skipped: file not found - {local_file_path}")
        return False

    if remote_filename is None:
        remote_filename = os.path.basename(local_file_path)

    try:
        logger.info(f"Connecting to FTP {FTP_HOST}:{FTP_PORT}...")
        ftp = ftplib.FTP()
        ftp.connect(FTP_HOST, FTP_PORT, timeout=30)
        ftp.login(FTP_USER, FTP_PASS)
        logger.info(f"FTP login success")

        # 确保远程目录存在，逐级创建
        dirs = FTP_REMOTE_DIR.strip("/").split("/")
        current_path = ""
        for d in dirs:
            current_path += f"/{d}"
            try:
                ftp.cwd(current_path)
            except ftplib.error_perm:
                try:
                    ftp.mkd(current_path)
                    ftp.cwd(current_path)
                    logger.info(f"FTP created dir: {current_path}")
                except ftplib.error_perm as e:
                    logger.warning(f"FTP cannot create dir {current_path}: {e}")
                    ftp.cwd("/")
                    break

        with open(local_file_path, "rb") as f:
            ftp.storbinary(f"STOR {remote_filename}", f)

        ftp.quit()
        logger.info(f"FTP upload success: {remote_filename} -> {FTP_REMOTE_DIR}/")
        return True

    except (ftplib.all_errors, socket.timeout, ConnectionError, OSError) as e:
        logger.error(f"FTP upload failed: {e}")
        try:
            ftp.quit()
        except Exception:
            pass
        return False


def upload_tt_reports_to_ftp(local_dir=None):
    """
    将 tt_reports 目录下的所有文件上传到 FTP，并删除远端之前上传的旧文件，只保留最新一份。

    Args:
        local_dir: 本地 tt_reports 目录路径，默认使用 DATA_DIR/tt_reports

    Returns:
        bool: 是否全部上传成功
    """
    if local_dir is None:
        local_dir = os.path.join(DATA_DIR, TT_REPORT_SUBDIR)

    if not os.path.isdir(local_dir):
        logger.warning(f"FTP upload skipped: tt_reports dir not found - {local_dir}")
        return False

    # 收集本地文件
    local_files = [f for f in os.listdir(local_dir) if os.path.isfile(os.path.join(local_dir, f))]
    if not local_files:
        logger.warning("FTP upload skipped: tt_reports is empty")
        return False

    ftp = None
    try:
        logger.info(f"Connecting to FTP {FTP_HOST}:{FTP_PORT} for tt_reports upload...")
        ftp = ftplib.FTP()
        ftp.connect(FTP_HOST, FTP_PORT, timeout=30)
        ftp.login(FTP_USER, FTP_PASS)
        logger.info("FTP login success")

        # 确保远程目录存在
        dirs = FTP_REMOTE_DIR.strip("/").split("/")
        current_path = ""
        for d in dirs:
            current_path += f"/{d}"
            try:
                ftp.cwd(current_path)
            except ftplib.error_perm:
                try:
                    ftp.mkd(current_path)
                    ftp.cwd(current_path)
                    logger.info(f"FTP created dir: {current_path}")
                except ftplib.error_perm as e:
                    logger.warning(f"FTP cannot create dir {current_path}: {e}")
                    ftp.cwd("/")
                    break

        # 删除远端旧文件（只保留本次上传的）
        try:
            remote_files = ftp.nlst()
            for rf in remote_files:
                if rf in (".", ".."):
                    continue
                # 只删除与 tt_reports 同类型的文件（xlsx/png）
                if rf.endswith((".xlsx", ".png")):
                    try:
                        ftp.delete(rf)
                        logger.info(f"FTP deleted old file: {rf}")
                    except ftplib.error_perm as e:
                        logger.warning(f"FTP cannot delete {rf}: {e}")
        except ftplib.error_perm as e:
            logger.warning(f"FTP list remote files failed: {e}")

        # 上传本地 tt_reports 中的所有文件
        success_count = 0
        for filename in local_files:
            filepath = os.path.join(local_dir, filename)
            try:
                with open(filepath, "rb") as f:
                    ftp.storbinary(f"STOR {filename}", f)
                success_count += 1
                logger.info(f"FTP uploaded: {filename}")
            except (ftplib.all_errors, OSError) as e:
                logger.error(f"FTP upload failed for {filename}: {e}")

        ftp.quit()
        logger.info(f"FTP tt_reports upload done: {success_count}/{len(local_files)} files -> {FTP_REMOTE_DIR}/")
        return success_count == len(local_files)

    except (ftplib.all_errors, socket.timeout, ConnectionError, OSError) as e:
        logger.error(f"FTP tt_reports upload failed: {e}")
        try:
            if ftp:
                ftp.quit()
        except Exception:
            pass
        return False


# FINEBI FTP 上传路径（Eflow_TT_FB / Eflow_WO_FB）
FTP_FB_REMOTE_DIR = "/webroot/WEB-INF/reportlets/excel"


def generate_and_upload_fb_excel(all_data: dict) -> dict:
    """
    从 eFlow 同步数据生成 Eflow_TT_FB.xlsx 和 Eflow_WO_FB.xlsx，
    保存到 db/ 目录并上传到 FTP /webroot/WEB-INF/reportlets/excel。

    Args:
        all_data: fetch_all_data() 返回的 {sheet_name: rows} 字典

    Returns:
        dict: {"tt_path": ..., "wo_path": ..., "upload_success": bool}
    """
    import pandas as pd

    t0 = time.time()
    db_dir = os.path.dirname(APP_DB_PATH)
    result = {"tt_path": None, "wo_path": None, "upload_success": False}

    # 生成 Eflow_TT_FB.xlsx
    tt_rows = all_data.get("eFlow TT") or []
    if tt_rows:
        df_tt = pd.DataFrame(tt_rows)
        tt_path = os.path.join(db_dir, "Eflow_TT_FB.xlsx")
        try:
            df_tt.to_excel(tt_path, index=False, engine="openpyxl")
            result["tt_path"] = tt_path
            logger.info(f"Eflow_TT_FB.xlsx 已生成: {len(df_tt)} 行 -> {tt_path}")
        except PermissionError:
            tt_path = os.path.join(db_dir, "Eflow_TT_FB_1.xlsx")
            df_tt.to_excel(tt_path, index=False, engine="openpyxl")
            result["tt_path"] = tt_path
            logger.info(f"Eflow_TT_FB_1.xlsx 已生成(原文件被占用): {len(df_tt)} 行")
    else:
        logger.warning("无 eFlow TT 数据，跳过 Eflow_TT_FB.xlsx")

    # 生成 Eflow_WO_FB.xlsx
    wo_rows = all_data.get("eFlow WO") or []
    if wo_rows:
        df_wo = pd.DataFrame(wo_rows)
        wo_path = os.path.join(db_dir, "Eflow_WO_FB.xlsx")
        try:
            df_wo.to_excel(wo_path, index=False, engine="openpyxl")
            result["wo_path"] = wo_path
            logger.info(f"Eflow_WO_FB.xlsx 已生成: {len(df_wo)} 行 -> {wo_path}")
        except PermissionError:
            wo_path = os.path.join(db_dir, "Eflow_WO_FB_1.xlsx")
            df_wo.to_excel(wo_path, index=False, engine="openpyxl")
            result["wo_path"] = wo_path
            logger.info(f"Eflow_WO_FB_1.xlsx 已生成(原文件被占用): {len(df_wo)} 行")
    else:
        logger.warning("无 eFlow WO 数据，跳过 Eflow_WO_FB.xlsx")

    # 上传到 FTP /webroot/WEB-INF/reportlets/excel
    uploaded = 0
    total_files = 0
    ftp = None
    files_to_upload = [(result["tt_path"], "Eflow_TT_FB.xlsx"), (result["wo_path"], "Eflow_WO_FB.xlsx")]
    try:
        ftp = ftplib.FTP()
        ftp.connect(FTP_HOST, FTP_PORT, timeout=30)
        ftp.login(FTP_USER, FTP_PASS)

        # 切换到目标目录
        dirs = FTP_FB_REMOTE_DIR.strip("/").split("/")
        current_path = ""
        for d in dirs:
            current_path += f"/{d}"
            try:
                ftp.cwd(current_path)
            except ftplib.error_perm:
                try:
                    ftp.mkd(current_path)
                    ftp.cwd(current_path)
                except ftplib.error_perm:
                    ftp.cwd("/")
                    break

        for local_path, remote_name in files_to_upload:
            if not local_path or not os.path.exists(local_path):
                continue
            total_files += 1
            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {remote_name}", f)
            uploaded += 1
            logger.info(f"FTP 上传成功: {remote_name} -> {FTP_FB_REMOTE_DIR}/")

        ftp.quit()
        result["upload_success"] = uploaded == total_files and total_files > 0
        logger.info(f"FB Excel FTP 上传完成: {uploaded}/{total_files}, 用时 {time.time() - t0:.2f}s")
    except (ftplib.all_errors, socket.timeout, ConnectionError, OSError) as e:
        logger.error(f"FB Excel FTP 上传失败: {e}")
        try:
            if ftp:
                ftp.quit()
        except Exception:
            pass

    return result


# ============================================================
# 小时报告与图片生成（复用 mail_126.py 的方法）
# ============================================================


def _find_col_fuzzy(df, keyword):
    """在 DataFrame 列中模糊查找包含 keyword（不区分大小写）的列名，返回第一个匹配或 None。"""
    kw = keyword.lower()
    for col in df.columns:
        if kw in str(col).lower():
            return col
    return None


def _build_site_attr_map(sheets_data, processor_cls):
    """构建 TRM Type / FME / Supervisor 的映射。

    - TRM Type: 从 eFlow Site 数据获取
    - FME / Supervisor: 从 master_site_db 表的 fme_name / supervisor 列获取

    返回 dict:
        {
            "trm_type": (id_map, name_map),
            "fme": (id_map, name_map),
            "supervisor": (id_map, name_map),
        }
    每个 id_map: normalize_id(Site ID) -> value
    每个 name_map: strip(Site Name) -> value
    """
    import pandas as pd

    empty_result = {
        "trm_type": ({}, {}),
        "fme": ({}, {}),
        "supervisor": ({}, {}),
    }

    # --- TRM Type: 从 eFlow Site 数据获取 ---
    site_rows = []
    for sheet_name, rows in sheets_data:
        if sheet_name == "Site":
            site_rows = rows or []
            break

    trm_result = ({}, {})
    if site_rows:
        df_site = pd.DataFrame(site_rows)
        df_site = processor_cls.clean_columns(df_site)
        trm_col = SITE_TX_SOURCE_COL if SITE_TX_SOURCE_COL in df_site.columns else _find_col_fuzzy(df_site, "TRM")
        logger.info(f"Site TRM 列: '{trm_col}'")
        if trm_col and trm_col in df_site.columns:
            id_map, name_map = {}, {}
            for _, r in df_site.iterrows():
                val = str(r.get(trm_col, "")).strip() if pd.notna(r.get(trm_col)) else ""
                sid = processor_cls.normalize_id(r.get("Site ID"))
                sname = str(r.get("Site Name", "")).strip()
                if sid:
                    id_map[sid] = val
                if sname:
                    name_map[sname] = val
            trm_result = (id_map, name_map)
            logger.info(f"trm_type 映射: {len(id_map)} by ID, {len(name_map)} by Name")

    # --- FME / Supervisor: 从 master_site_db 读取 ---
    fme_result = ({}, {})
    sup_result = ({}, {})
    try:
        if os.path.exists(APP_DB_PATH):
            conn = sqlite3.connect(APP_DB_PATH)
            df_master = pd.read_sql_query(
                'SELECT site_id, site_name, fme_name, supervisor FROM master_site_db', conn)
            conn.close()
            logger.info(f"master_site_db 读取: {len(df_master)} 行")

            # FME 映射
            fme_id, fme_name_map = {}, {}
            for _, r in df_master.iterrows():
                val = str(r.get("fme_name", "")).strip() if pd.notna(r.get("fme_name")) else ""
                sid = processor_cls.normalize_id(r.get("site_id"))
                sname = str(r.get("site_name", "")).strip()
                if sid:
                    fme_id[sid] = val
                if sname:
                    fme_name_map[sname] = val
            fme_result = (fme_id, fme_name_map)
            logger.info(f"fme 映射(master_site_db): {len(fme_id)} by ID, {len(fme_name_map)} by Name")

            # Supervisor 映射
            sup_id, sup_name_map = {}, {}
            for _, r in df_master.iterrows():
                val = str(r.get("supervisor", "")).strip() if pd.notna(r.get("supervisor")) else ""
                sid = processor_cls.normalize_id(r.get("site_id"))
                sname = str(r.get("site_name", "")).strip()
                if sid:
                    sup_id[sid] = val
                if sname:
                    sup_name_map[sname] = val
            sup_result = (sup_id, sup_name_map)
            logger.info(f"supervisor 映射(master_site_db): {len(sup_id)} by ID, {len(sup_name_map)} by Name")
        else:
            logger.warning(f"master_site_db 不可用: {APP_DB_PATH} 不存在")
    except Exception as e:
        logger.warning(f"从 master_site_db 读取 FME/Supervisor 失败: {e}")

    return {
        "trm_type": trm_result,
        "fme": fme_result,
        "supervisor": sup_result,
    }


# mail_126.py 所在目录（项目内部 backend/services/report/）
_TICKET_EXPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report")


def _import_excel_processor():
    """安全导入 mail_126.ExcelDataProcessor。

    mail_126.py 已复制到项目内部 backend/services/report/ 目录，
    无需外部依赖。EmailSender 类级属性会执行 pd.read_csv("to_receiver.txt")，
    本函数在导入前补齐 to_receiver.txt，避免 FileNotFoundError。
    返回 (ExcelDataProcessor, EmailSender)。
    """
    import sys

    script_dir = _TICKET_EXPORT_DIR

    # 1) 确保 to_receiver.txt 存在
    receiver_file = os.path.join(script_dir, "to_receiver.txt")
    if not os.path.exists(receiver_file):
        with open(receiver_file, "w", encoding="utf-8") as f:
            f.write("nobody@example.invalid\n")
        logger.info(f"Created placeholder {receiver_file}")

    # 2) 将脚本目录加入 sys.path
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    # 3) 切到脚本目录导入（pd.read_csv("to_receiver.txt") 依赖 CWD），导入后恢复
    prev_cwd = os.getcwd()
    try:
        os.chdir(script_dir)
        from mail_126 import ExcelDataProcessor, EmailSender
    finally:
        os.chdir(prev_cwd)
    return ExcelDataProcessor, EmailSender


# ============================================================
# 主入口：获取数据后生成 Hourly Report / Summary Report / 图片
# ============================================================

def generate_hourly_report_with_images(data: dict, send_email: bool = None) -> dict:
    """
    从 eFlow 同步数据生成小时报告、Summary 报告和图片，复用 mail_126.py 的 ExcelDataProcessor。

    Args:
        data: fetch_all_data() 返回的 {sheet_name: rows} 字典
        send_email: 是否发送邮件（默认 False）

    Returns:
        dict: 生成的文件路径字典；失败返回 {"success": False}
    """
    import pandas as pd

    total_start = time.time()
    start_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_dir = os.path.join(DATA_DIR, TT_REPORT_SUBDIR)
    if send_email is None:
        send_email = SEND_EMAIL_AFTER_REPORT

    logger.info(f"开始生成小时报告与图片 - {start_time_str}")

    # 导入 mail_126
    try:
        ExcelDataProcessor, EmailSender = _import_excel_processor()
    except Exception as e:
        import traceback
        logger.error(f"无法导入 mail_126.ExcelDataProcessor: {e}")
        traceback.print_exc()
        return {"success": False, "error": str(e)}

    # 转换 data dict 为 sheets_data 列表格式
    sheets_data = [(k, v) for k, v in data.items()]

    # 1. 提取 eFlow TT 数据
    tt_rows = []
    for sheet_name, rows in sheets_data:
        if sheet_name == "eFlow TT":
            tt_rows = rows or []
            break
    if not tt_rows:
        logger.warning("没有 eFlow TT 数据，跳过报告生成")
        return {"success": False, "error": "No eFlow TT data"}
    logger.info(f"eFlow TT 行数: {len(tt_rows)}")

    # 2. 构建 DataFrame 并重命名列
    df_source = pd.DataFrame(tt_rows)
    df_source = ExcelDataProcessor.clean_columns(df_source)
    rename_map = {k: v for k, v in _TT_COLUMN_RENAME.items() if k in df_source.columns}
    if rename_map:
        df_source = df_source.rename(columns=rename_map)
    logger.info(f"TT DataFrame: {df_source.shape}, 重命名: {rename_map}")

    # 2.5 从 Site 数据添加 TRM Type / FME / Supervisor 列
    attr_maps = _build_site_attr_map(sheets_data, ExcelDataProcessor)
    if "Site ID" in df_source.columns:
        df_source["Site ID"] = df_source["Site ID"].apply(ExcelDataProcessor.normalize_id)

    _attr_col_names = {"trm_type": "TRM Type", "fme": "FME", "supervisor": "Supervisor"}
    for attr_key, col_label in _attr_col_names.items():
        id_map, name_map = attr_maps.get(attr_key, ({}, {}))
        if id_map or name_map:
            df_source[col_label] = df_source["Site ID"].map(id_map) if "Site ID" in df_source.columns else ""
            mask = df_source[col_label].isna()
            if mask.any() and name_map and "Site Name" in df_source.columns:
                df_source.loc[mask, col_label] = (
                    df_source.loc[mask, "Site Name"].astype(str).str.strip().map(name_map)
                )
            df_source[col_label] = df_source[col_label].fillna("")
            matched = (df_source[col_label].astype(str).str.strip() != "").sum()
            logger.info(f"{col_label} 列已添加，匹配率: {matched}/{len(df_source)}")
        else:
            df_source[col_label] = ""
            logger.warning(f"{col_label} 列为空（Site 表无对应数据）")

    # 3. 直接设置数据源
    ExcelDataProcessor.df_master_cache = None
    ExcelDataProcessor.df_eflow_source = df_source

    result = {
        "success": True,
        "hourly_file": None,
        "eight_hour_file": None,
        "eight_hour_img": None,
        "summary_file": None,
        "image_paths": [],
    }

    try:
        # 4. 字段提取
        step_start = time.time()
        logger.info("步骤1: 提取字段...")
        df_extracted = ExcelDataProcessor.extract_fields()
        logger.info(f"   用时: {time.time() - step_start:.2f}s")

        # 5. Hourly Report
        step_start = time.time()
        logger.info("步骤2: 生成 Hourly Report...")
        hourly_file, _ = ExcelDataProcessor.write_hourly_report(
            df_extracted, output_dir=output_dir)
        result["hourly_file"] = hourly_file
        logger.info(f"   用时: {time.time() - step_start:.2f}s")

        # 6. 8 Hours Report
        step_start = time.time()
        logger.info("步骤3: 生成 8 Hours Report...")
        eight_hour_file, eight_hour_img, _ = ExcelDataProcessor.write_8hours_report(
            df_extracted, output_dir=output_dir)
        result["eight_hour_file"] = eight_hour_file
        result["eight_hour_img"] = eight_hour_img
        logger.info(f"   用时: {time.time() - step_start:.2f}s")

        # 7. TT Summary 计算
        step_start = time.time()
        logger.info("步骤4: 计算 SLA Status / Summary...")
        df_open, open_tickets, prolong_tickets, summary_df, raw_df = \
            ExcelDataProcessor.compute_tt_summary(df_extracted)
        logger.info(f"   Open Tickets: {len(open_tickets)}, Prolong: {len(prolong_tickets)}")
        logger.info(f"   用时: {time.time() - step_start:.2f}s")

        # 8. TT Summary Report
        step_start = time.time()
        logger.info("步骤5: 生成 TT Summary Report...")
        summary_file = ExcelDataProcessor.write_summary_report(
            open_tickets, prolong_tickets, summary_df, raw_df, output_dir=output_dir)
        result["summary_file"] = summary_file
        logger.info(f"   用时: {time.time() - step_start:.2f}s")

        # 9. 图片
        step_start = time.time()
        logger.info("步骤6: 生成图片（matplotlib）...")
        image_paths = ExcelDataProcessor.generate_summary_images(
            summary_df, open_tickets, prolong_tickets, output_dir)
        result["image_paths"] = image_paths
        logger.info(f"   用时: {time.time() - step_start:.2f}s")

        # 10. 邮件（可选）
        if send_email:
            step_start = time.time()
            logger.info("步骤7: 发送邮件...")
            try:
                EmailSender.send_report_email(summary_file, summary_df, image_paths=image_paths)
            except Exception as e:
                logger.error(f"邮件发送失败: {e}")
            logger.info(f"   用时: {time.time() - step_start:.2f}s")

    except Exception as e:
        import traceback
        logger.error(f"报告生成失败: {e}")
        traceback.print_exc()
        result["success"] = False
        result["error"] = str(e)

    total_elapsed = time.time() - total_start
    end_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"报告生成完成! 开始: {start_time_str}, 结束: {end_time_str}, 用时: {total_elapsed:.2f}s")
    if result.get("hourly_file"):
        logger.info(f"  Hourly Report: {result['hourly_file']}")
    if result.get("eight_hour_file"):
        logger.info(f"  8 Hours Report: {result['eight_hour_file']}")
    if result.get("summary_file"):
        logger.info(f"  Summary Report: {result['summary_file']}")
    for p in result.get("image_paths", []):
        logger.info(f"  图片: {p}")

    return result


def generate_excel_report(data=None, save_sqlite=True, save_excel=True, cleanup=True, upload_ftp=False):
    """
    从获取的数据生成 SQLite 和 Excel 报告，并可选择上传到 FTP。
    
    如果未提供 data，则调用 fetch_all_data() 先获取数据。
    
    Args:
        data: dict{sheet_name: rows} 或 None
        save_sqlite: 是否保存到 SQLite
        save_excel: 是否生成 Excel
        cleanup: 是否清理旧导出文件
        upload_ftp: 是否上传 Excel 到 FTP
    
    Returns:
        dict: {"db_path": ..., "excel_path": ..., "sheets": ..., "upload_success": ...}
    """
    start_time = time.time()

    if data is None:
        logger.info("No data provided, fetching all eFlow data first...")
        data = fetch_all_data()

    result = {"db_path": None, "excel_path": None, "sheets": {}, "upload_success": False}

    if save_sqlite:
        db_path = save_to_sqlite(data)
        result["db_path"] = db_path

    if save_excel:
        excel_path = write_excel_from_sqlite(data)
        result["excel_path"] = excel_path

    if cleanup:
        cleanup_old_export_files()

    # FTP 上传
    if upload_ftp and result["excel_path"]:
        upload_success = upload_to_ftp(result["excel_path"])
        result["upload_success"] = upload_success

    elapsed = time.time() - start_time
    logger.info(f"Excel report generated in {elapsed:.2f}s")

    for sheet_name, rows in data.items():
        result["sheets"][sheet_name] = len(rows)

    return result


# ========== 主入口 ==========
def _run_pipeline_with_connection_cleanup(pipeline):
    """Prevent worker-local keep-alive sockets from leaking between sync runs."""
    try:
        return pipeline()
    finally:
        _close_thread_socket()


def fetch_all_data(tmp_dir: str = None) -> dict:
    """
    从 eFlow API 获取所有数据，返回 {sheet_name: records_list} 字典
    
    Args:
        tmp_dir: 临时文件目录，不传则自动创建
    """
    start_time = time.time()

    # 确保已登录
    if not _session_cookie:
        login()

    # 创建临时目录
    auto_tmp = False
    if tmp_dir is None:
        import tempfile
        tmp_dir = tempfile.mkdtemp(prefix="eflow_")
        auto_tmp = True

    try:
        start_ms, end_ms = _get_time_range_ms()
        logger.info(f"Time range: {start_ms} to {end_ms}")

        # 仅包含工单/资产类数据；告警由独立任务 eflow_active_alarm / eflow_history_alarm 负责
        pipelines = [
            ("tt", lambda: _fetch_tt_pipeline(start_ms, end_ms, tmp_dir)),
            ("wo", lambda: _fetch_wo_pipeline(start_ms, end_ms, tmp_dir)),
            ("cr", lambda: _fetch_cr_pipeline(start_ms, end_ms, tmp_dir)),
            ("pm", lambda: _fetch_pm_pipeline(start_ms, end_ms, tmp_dir)),
            ("site", lambda: _fetch_site_pipeline(tmp_dir)),
            ("person", lambda: _fetch_person_pipeline(tmp_dir)),
        ]

        results = {}
        logger.info(f"Starting parallel pipelines (max_workers={MAX_PARALLEL_DOWNLOADS})...")
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_DOWNLOADS) as executor:
            future_to_key = {
                executor.submit(_run_pipeline_with_connection_cleanup, fn): key
                for key, fn in pipelines
            }
            for future in as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    sheet_name, rows = future.result()
                    results[sheet_name] = rows
                    logger.info(f"{key} completed: {len(rows)} rows")
                except Exception as e:
                    logger.error(f"{key} pipeline failed: {e}")
                    import traceback
                    traceback.print_exc()

        elapsed = time.time() - start_time
        total_rows = sum(len(v) for v in results.values())
        logger.info(f"All data fetched: {len(results)} tables, {total_rows} rows, {elapsed:.2f}s")
        return results

    finally:
        # 清理临时目录
        if auto_tmp and os.path.exists(tmp_dir):
            try:
                shutil.rmtree(tmp_dir)
            except OSError:
                pass


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')

    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode == "active_alarm":
        t0 = time.time()
        result = fetch_and_save_active_alarm()
        print(f"Active alarm: {len(result['realtime_alarm'])} records")
        print(f"Total: {time.time() - t0:.2f}s")
    elif mode == "history_alarm":
        t0 = time.time()
        result = fetch_and_save_history_alarm()
        print(f"History alarm: {len(result['history_alarm'])} records")
        print(f"Total: {time.time() - t0:.2f}s")
    elif mode == "alarm":
        t0 = time.time()
        result = fetch_and_save_alarm_data()
        print(f"Active alarm: {len(result['realtime_alarm'])} records")
        print(f"History alarm: {len(result['history_alarm'])} records")
        print(f"Total: {time.time() - t0:.2f}s")
    elif mode == "report":
        t0 = time.time()
        # 解析可选参数：python eflow_api_client.py report [upload]
        upload_to_ftp_flag = len(sys.argv) > 2 and sys.argv[2] == "upload"
        result = generate_excel_report(upload_ftp=upload_to_ftp_flag)
        print(f"\n=== Excel Report Summary ===")
        print(f"  SQLite DB: {result.get('db_path')}")
        print(f"  Excel:     {result.get('excel_path')}")
        print(f"  Sheets:    {len(result.get('sheets', {}))}")
        for name, count in result.get('sheets', {}).items():
            print(f"    - {name}: {count} rows")
        if result.get('upload_success'):
            print(f"  FTP:       uploaded OK")
        print(f"\nTotal: {time.time() - t0:.2f}s")
    else:
        t0 = time.time()
        data = fetch_all_data()
        print(f"\n=== Data Fetch Summary ===")
        for name, rows in data.items():
            print(f"  {name}: {len(rows)} rows")
        print(f"\nTotal: {time.time() - t0:.2f}s")

        # 同时生成 Excel 报告（使用已有数据，即使部分管道失败）
        report_t0 = time.time()
        print(f"\n--- Generating Excel report ---")
        report = generate_excel_report(data=data, upload_ftp=False)
        print(f"  SQLite DB: {report.get('db_path')}")
        print(f"  Excel:     {report.get('excel_path')}")
        print(f"  Report time: {time.time() - report_t0:.2f}s")
