"""
eFlow API Client - 集成版
直接从 ZTE 网管系统 eFlow API 获取 TT/WO/CR/PM/Site/Person/RealtimeAlarm 数据
使用原始 socket + SSL（绕过 requests/urllib3 的 TLS 兼容问题）
"""
import ssl
import socket
import json
import time
import re
import base64
import uuid
import logging
import gzip
import os
import shutil
import csv
import sqlite3
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("eflow_api")

# ========== 连接配置 ==========
HOST = os.environ.get("EFLOW_HOST", "10.100.20.8")
PORT = int(os.environ.get("EFLOW_PORT", "28001"))
USERNAME = os.environ.get("EFLOW_USER", "admin")
PASSWORD = os.environ.get("EFLOW_PASS", "Brysj*8*")
MAX_PARALLEL_DOWNLOADS = 4

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

# ========== 会话状态 ==========
_session_cookie = ""
_forgery_token = ""


# ========== SSL / HTTP 基础 ==========
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

    logger.info("Starting eFlow authentication...")

    try:
        # Step 1: Get authorize page
        status, hdrs, raw_hdrs, body = _http_request(
            "GET",
            "/api/oauth2/v1/authorize?scope=user.login&response_type=code&redirect_uri=/uportal/framework/default.html"
        )

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

        html = body.decode('utf-8', errors='replace')
        lp_match = re.search(r'var\s+loginParameters\s*=\s*["\']([^"\']+)["\']', html)
        login_parameters = lp_match.group(1) if lp_match else ""

        # Step 2: Get RSA public key
        rsa_headers = f"Cookie: {init_cookie_str}\r\nX-Requested-With: XMLHttpRequest\r\n"
        status, hdrs, raw_hdrs, body = _http_request(
            "GET", "/api/oauth2/v1/login/publickey", headers_extra=rsa_headers,
        )

        public_key_b64 = ""
        if "200" in status:
            pk_data = json.loads(body.decode('utf-8'))
            public_key_b64 = pk_data.get("rsaPublicKey", "")

        # Step 3: Encrypt password
        encrypted_pwd = _rsa_encrypt_pem(PASSWORD, public_key_b64)

        # Step 4: Submit login
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

        _session_cookie = "; ".join(cookies)
        _forgery_token = forgery_token

        if not any("Z-AUTH-CODE" in c for c in cookies):
            raise Exception("Login failed - no auth cookie obtained")

        logger.info(f"eFlow login success ({len(cookies)} cookies)")

    except Exception as e:
        logger.error(f"eFlow login failed: {e}")
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


def _wait_export_ready(list_path, referer, file_name, label, max_wait=600, interval=10):
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

    extract_dir = os.path.splitext(zip_path)[0]
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_dir)
        files = z.namelist()

    data_files = [f for f in files if f.lower().endswith((".xlsx", ".xls", ".csv"))]
    if not data_files:
        raise Exception(f"No data file found in {label} ZIP")

    read_start = time.time()
    dfs = []
    for data_file in data_files:
        full_path = os.path.join(extract_dir, data_file)
        if full_path.lower().endswith(".csv"):
            dfs.append(pd.read_csv(full_path))
        else:
            dfs.append(pd.read_excel(full_path))

    df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    logger.info(f"{label}: {len(df)} rows, {len(df.columns)} columns (read {time.time() - read_start:.2f}s)")

    try:
        shutil.rmtree(extract_dir)
    except OSError:
        pass

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

    logger.info("TT: waiting 10s before polling...")
    time.sleep(10)

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

    logger.info("WO: waiting 10s before polling...")
    time.sleep(10)

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

    logger.info("CR: waiting 10s before polling...")
    time.sleep(10)

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

    logger.info("PM: waiting 10s before polling...")
    time.sleep(10)

    pm_list_path = "/api/eflow-pm/v1/export/list/eflow-pm-task"
    ftp_file_path, _ = _wait_export_ready(pm_list_path, PM_REFERER, file_name, "PM")
    zip_path = _download_export_zip(PM_DOWNLOAD_PATH, PM_REFERER, file_name, ftp_file_path, "eflow-pm-task", "PM", tmp_dir)
    rows = _read_export_zip(zip_path, "PM")
    return ("eFlow PM", rows)


def _fetch_site_pipeline(tmp_dir):
    """CMDB Site 导出为同步下载"""
    import pandas as pd
    headers_extra = _headers_extra(SITE_REFERER)
    payload = {"callScene": "ui"}
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request("POST", SITE_ASYNC_PATH, headers_extra=headers_extra, body=body)

    if "200" not in status:
        raise Exception(f"Site export failed: {status}")

    filename = "Site.xlsx"
    cd = hdrs.get("content-disposition", "")
    if cd:
        fn_match = re.search(r'filename=["\']?([^"\';]+)', cd)
        if fn_match:
            filename = fn_match.group(1)

    xlsx_path = os.path.join(tmp_dir, filename)
    seq = 1
    while os.path.exists(xlsx_path):
        base, ext = os.path.splitext(filename)
        xlsx_path = os.path.join(tmp_dir, f"{base}_{seq}{ext}")
        seq += 1

    with open(xlsx_path, "wb") as f:
        f.write(resp_body)

    t0 = time.time()
    df = pd.read_excel(xlsx_path)
    logger.info(f"Site: {len(df)} rows, {len(df.columns)} columns (read {time.time() - t0:.2f}s)")
    return ("Site", df.to_dict("records"))


def _fetch_person_pipeline(tmp_dir):
    """CMDB Person 导出为同步下载"""
    import pandas as pd
    headers_extra = _headers_extra(PERSON_REFERER)
    payload = {"callScene": "ui"}
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request("POST", PERSON_ASYNC_PATH, headers_extra=headers_extra, body=body)

    if "200" not in status:
        raise Exception(f"Person export failed: {status}")

    filename = "Person.xlsx"
    cd = hdrs.get("content-disposition", "")
    if cd:
        fn_match = re.search(r'filename=["\']?([^"\';]+)', cd)
        if fn_match:
            filename = fn_match.group(1)

    xlsx_path = os.path.join(tmp_dir, filename)
    seq = 1
    while os.path.exists(xlsx_path):
        base, ext = os.path.splitext(filename)
        xlsx_path = os.path.join(tmp_dir, f"{base}_{seq}{ext}")
        seq += 1

    with open(xlsx_path, "wb") as f:
        f.write(resp_body)

    t0 = time.time()
    df = pd.read_excel(xlsx_path)
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

# FM History Alarm 查询条件：近 7 天（动态计算）
HIS_ALARM_DAYS_BACK = int(os.environ.get("EFLOW_HIS_ALARM_DAYS", "7"))


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

        data = json.loads(resp_body.decode('utf-8'))

        if not isinstance(data, dict):
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

    logger.info(f"History Alarm SQLite saved: {db_file}, {len(rows_to_insert)} records")
    return db_file


# ========== 告警独立入口 ==========
def fetch_and_save_active_alarm():
    """
    仅同步实时告警：登录 eFlow -> 获取实时告警 -> 保存 CSV + SQLite
    """
    logger.info("Starting active alarm sync...")
    start_time = time.time()

    if not _session_cookie:
        login()

    alarm_result = _fetch_alarm_pipeline()
    _, alarm_rows = alarm_result if isinstance(alarm_result, tuple) else ("realtime_alarm", alarm_result)
    write_alarm_csv(alarm_rows)
    write_alarm_sqlite(alarm_rows)

    elapsed = time.time() - start_time
    logger.info(f"Active alarm sync completed in {elapsed:.2f}s, {len(alarm_rows)} records")
    return {"realtime_alarm": alarm_rows}


def fetch_and_save_history_alarm():
    """
    仅同步历史告警：登录 eFlow -> 获取历史告警 -> 过滤 TT ID -> 保存 CSV + SQLite
    """
    logger.info("Starting history alarm sync...")
    start_time = time.time()

    if not _session_cookie:
        login()

    his_result = _fetch_history_alarm_pipeline()
    _, his_rows = his_result if isinstance(his_result, tuple) else ("history_alarm", his_result)
    write_history_alarm_csv(his_rows)
    filtered_his_rows = _filter_rows_with_tt_id(his_rows)
    logger.info(
        f"History alarm filtered: {len(his_rows)} -> {len(filtered_his_rows)} "
        f"(removed {len(his_rows) - len(filtered_his_rows)} rows with empty/invalid TT ID)"
    )
    write_history_alarm_sqlite(filtered_his_rows)

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


# ========== 主入口 ==========
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

        pipelines = [
            ("tt", lambda: _fetch_tt_pipeline(start_ms, end_ms, tmp_dir)),
            ("wo", lambda: _fetch_wo_pipeline(start_ms, end_ms, tmp_dir)),
            ("cr", lambda: _fetch_cr_pipeline(start_ms, end_ms, tmp_dir)),
            ("pm", lambda: _fetch_pm_pipeline(start_ms, end_ms, tmp_dir)),
            ("site", lambda: _fetch_site_pipeline(tmp_dir)),
            ("person", lambda: _fetch_person_pipeline(tmp_dir)),
            ("alarm", _fetch_alarm_pipeline),
            ("history_alarm", _fetch_history_alarm_pipeline),
        ]

        results = {}
        logger.info(f"Starting parallel pipelines (max_workers={MAX_PARALLEL_DOWNLOADS})...")
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_DOWNLOADS) as executor:
            future_to_key = {executor.submit(fn): key for key, fn in pipelines}
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
    else:
        t0 = time.time()
        data = fetch_all_data()
        for name, rows in data.items():
            print(f"  {name}: {len(rows)} rows")
        print(f"\nTotal: {time.time() - t0:.2f}s")
