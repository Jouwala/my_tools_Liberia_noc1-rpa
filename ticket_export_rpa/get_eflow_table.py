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
import shutil
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

# 并发下载端点数；CMDB + eFlow 共 6 个端点，默认 4 个并发以平衡速度与服务端压力
MAX_PARALLEL_DOWNLOADS = 4


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

TT_EXPORT_CONFIG = {
    "type": "Export",
    "serviceName": "eflow-ticket",
    "config": json.dumps(TT_EXPORT_COLUMNS),
}

TT_USERHABITS_PATH = "/api/eflow-ticket/v1/userhabits/add/eflow-tt"
TT_DOWNLOAD_PATH = "/api/eflow-ticket/v1/attachment/download/eflow-tt"


WO_FIELDS = "woId,procId,opName,ttWoid,pendingStatus,woNum,parentwoNum,status,displayName,creator,createTime,lastModifiedTime,candidateOperator,siteId,ticketSeverity,spareDomain,neName,neType,neIp,vendor,subSource,alarmOccurTime,alarmClearTime,expectedFinishTime,source,projectName,templateName,creatorContactInfo,alarmCategory,alarmSubcategory,alarmSeverity,reasonType,alarmId,alarmCode,subAlarmName,subAlarmNEName,subAlarmNEIP,appendingAlarmName,appendingAlarmNEName,appendingAlarmNEIP,networkType,neId,impactedServiceOrNo,impactedService,siteOutageOrNo,aiMindFailReasonType,faultDurationTime,slaTotalDuration,slaStatus,remainingTime,targetFinishTime,groupSlaTime,groupSlaStatus,groupSlaRemainsTime,groupSlaDeadlineTime,rcaFillingMode,regionLevel1Name,regionLevel2Name,assetName,assetType,siteClass,spareRequired,spareavailable,rejectCategory,etc,arriveSiteTime,travelTime"

WO_STATUS_FILTER = '((status eq "WaitAccept") or (status eq "WaitStartTrip") or (status eq "WaitArriveSite") or (status eq "WaitProcess") or (status eq "WaitConfirm") or (status eq "WaitLeaveSite") or (status eq "WaitSPApplication") or (status eq "WaitBONPOProcess") or (status eq "PhasedReply") or (status eq "Closed") or (status eq "Draft"))'

WO_PAYLOAD_BASE = {
    "customInfo": {"pageType": "allTicket"},
    "field": WO_FIELDS,
    "order": "lastModifiedTime desc",
    "relationFilter": {"eflow_wo_wo_asset": ""},
}

WO_REFERER = f"https://{HOST}:{PORT}/iui/wo-mgt/v1/"

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

WO_EXPORT_CONFIG = {
    "type": "Export",
    "serviceName": "eflow-wo",
    "config": json.dumps(WO_EXPORT_COLUMNS),
}

WO_ASYNC_PATH = "/api/eflow-wo/v1/export/async/eflow-wo"
WO_USERHABITS_PATH = "/api/eflow-wo/v1/userhabits/add/eflow-wo"
WO_DOWNLOAD_PATH = "/api/eflow-wo/v1/attachment/download/eflow-wo"

# WO 导出 fieldDetails 元数据：与浏览器手动导出请求保持一致
WO_FIELD_DETAILS_NAME_OVERRIDES = {
    "displayName": "field.woDisplayName",
}

WO_FIELD_DETAILS_RELATION_FILTER = {
    "alarmCode", "alarmId", "alarmType", "assetId", "assetName",
    "battery1ID", "battery2ID", "battery3ID", "category", "createTime",
    "creator", "etc", "hubSite",
}


CR_FIELDS = "woId,procId,opName,woNum,status,changeType,displayName,creator,requesterWorkGroupName,createTime,candidateOperator,mopMaker,mopChecker,ipRelatedActivity,implementer,implementResult,plannedStartTime,plannedEndTime,actualImplementationStartTime,actualImplementationEndTime,downtimeStart,downtimeEnd,rollbackStartTime,rollbackEndTime,closeTime,lastModifiedTime"

CR_STATUS_FILTER = '((status eq "WaitL1Approve") or (status eq "WaitL2Approve") or (status eq "WaitL3Approve") or (status eq "WaitL4Approve") or (status eq "WaitL5Approve") or (status eq "WaitL6Approve") or (status eq "WaitL7Approve") or (status eq "WaitL8Approve") or (status eq "WaitImplement") or (status eq "Implementing") or (status eq "PhaseUpdate") or (status eq "WaitUpdate") or (status eq "Closed") or (status eq "Canceled") or (status eq "Draft"))'

CR_PAYLOAD_BASE = {
    "customInfo": {"pageType": "allTicket"},
    "field": CR_FIELDS,
    "order": "lastModifiedTime desc",
    "length": 50,
}

CR_REFERER = f"https://{HOST}:{PORT}/iui/am-mgt/v1/"

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

CR_EXPORT_CONFIG = {
    "type": "Export",
    "serviceName": "eflow-asset",
    "config": json.dumps(CR_EXPORT_COLUMNS),
}

CR_ASYNC_PATH = "/api/eflow-asset/v1/export/async/eflow-cr"
CR_USERHABITS_PATH = "/api/eflow-asset/v1/userhabits/add/eflow-cr"
CR_DOWNLOAD_PATH = "/api/eflow-asset/v1/attachment/download/eflow-cr"


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

PM_EXPORT_CONFIG = {
    "type": "Export",
    "serviceName": "eflow-pm",
    "config": json.dumps(PM_EXPORT_COLUMNS),
}

PM_ASYNC_PATH = "/api/eflow-pm/v1/export/async/eflow-pm-task"
PM_USERHABITS_PATH = "/api/eflow-pm/v1/userhabits/add/eflow-pm-task"
PM_DOWNLOAD_PATH = "/api/eflow-pm/v1/attachment/download/eflow-pm-task"


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

SITE_ASYNC_PATH = "/api/cmdb/v1/data/export/Site"
SITE_DOWNLOAD_PATH = "/api/cmdb/v1/attachment/download/Site"
PERSON_ASYNC_PATH = "/api/cmdb/v1/data/export/Person"
PERSON_DOWNLOAD_PATH = "/api/cmdb/v1/attachment/download/Person"


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


def create_tt_export_task(filter_str, output_dir=OUTPUT_DIR):
    headers_extra = _export_headers_extra(TT_REFERER)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"eflow-tt-export-{USERNAME}-{timestamp}"
    field_details = {col: {"value": col, "name": f"field.{col}", "checked": True} for col in TT_EXPORT_COLUMNS}
    payload = {
        "fileName": file_name,
        "type": "xlsx",
        "createTimeRange": "",
        "exportType": "0",
        "customInfo": {"pageType": "allTicket"},
        "field": TT_EXPORT_COLUMNS,
        "fieldDetails": field_details,
        "filter": filter_str,
        "relationFilter": {"eflow_ticket_ticket_export_op": "", "eflow_ticket_ticket_attachment_export": ""},
        "relationTable": [],
        "tableName": "eflow_ticket_ticket_wo",
        "tableType": "eflow-tt",
    }
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", "/api/eflow-ticket/v1/export/async/eflow-tt", headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Create TT export task: {status}, {len(resp_body)} bytes")
    print(f"[DEBUG] export async headers: {raw_hdrs[:500]}")

    # 处理 gzip 压缩
    if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
        try:
            import gzip
            resp_body = gzip.decompress(resp_body)
            print(f"[INFO] Decompressed async response: {len(resp_body)} bytes")
        except Exception as e:
            print(f"[WARN] Failed to decompress async response: {e}")

    ftp_file_path = ""
    if "200" in status:
        try:
            resp_text = resp_body.decode('utf-8')
            print(f"[DEBUG] export async response: {resp_text[:500]}")
            resp_data = json.loads(resp_text)
            if isinstance(resp_data, dict):
                ftp_file_path = resp_data.get("ftpFilePath", "")
                if not ftp_file_path and isinstance(resp_data.get("data"), dict):
                    ftp_file_path = resp_data["data"].get("ftpFilePath", "")
                print(f"[INFO] Export ftpFilePath: {ftp_file_path}")
            else:
                print(f"[WARN] export async response is not dict: {type(resp_data)}, value={resp_data}")
        except Exception as e:
            print(f"[WARN] Failed to parse export async response: {e}")
    return ftp_file_path, file_name


def prepare_tt_export(filter_str):
    headers_extra = _export_headers_extra(TT_REFERER)
    payload = {
        "customInfo": {"pageType": "allTicket"},
        "field": TT_FIELDS,
        "filter": filter_str,
        "length": 1,
        "order": "lastModifiedTime desc",
        "relationFilter": {"eflow_ticket_ticket_asset_all": ""},
        "start": 0,
    }
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", TT_API_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Prepare TT export (base/list): {status}, {len(resp_body)} bytes")
    return status


def find_matching_success_export(filter_str):
    headers_extra = _export_headers_extra(TT_REFERER)
    body = json.dumps({})
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", "/api/eflow-ticket/v1/export/list/eflow-tt", headers_extra=headers_extra, body=body,
    )

    if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
        try:
            import gzip
            resp_body = gzip.decompress(resp_body)
        except Exception as e:
            print(f"[WARN] Failed to decompress export list response: {e}")

    try:
        data = json.loads(resp_body.decode('utf-8'))
        items = data if isinstance(data, list) else data.get("result", data.get("data", []))
        for item in items:
            item_filter = item.get("filter", "")
            is_success = item.get("status", "").lower() in ("success", "sucess") or item.get("rate", "") == "100%"
            if is_success and item_filter == filter_str:
                uuid_val = item.get("uuid", "")
                ftp_path = item.get("ftpFilePath", "")
                if not ftp_path and uuid_val:
                    ftp_path = f"{uuid_val}.zip"
                file_name = item.get("fileName", "")
                if file_name.endswith(".zip"):
                    file_name = file_name[:-4]
                print(f"[INFO] Found existing success export: {file_name}, ftpFilePath={ftp_path}")
                return file_name, ftp_path, item
    except Exception as e:
        print(f"[WARN] Failed to find existing export: {e}")
    return "", "", None


def wait_tt_export_ready(file_name, max_wait=120, interval=5):
    headers_extra = _export_headers_extra(TT_REFERER)
    body = json.dumps({})

    for attempt in range(max_wait // interval):
        status, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", "/api/eflow-ticket/v1/export/list/eflow-tt", headers_extra=headers_extra, body=body,
        )

        # 处理 gzip 压缩
        if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
            try:
                import gzip
                resp_body = gzip.decompress(resp_body)
            except Exception as e:
                print(f"[WARN] Failed to decompress export list response: {e}")

        try:
            resp_text = resp_body.decode('utf-8')
            print(f"[DEBUG] export list response: {resp_text[:500]}")
            data = json.loads(resp_text)

            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("result", data.get("data", []))

            for item in items:
                item_file_name = item.get("fileName", "")
                if file_name in item_file_name or item_file_name == file_name:
                    status_str = item.get("status", "")
                    uuid_val = item.get("uuid", "")
                    rate = item.get("rate", "")
                    print(f"[INFO] Export task {item_file_name}: status={status_str}, rate={rate}, uuid={uuid_val}")
                    if status_str.lower() in ("success", "sucess") or rate == "100%":
                        ftp_path = item.get("ftpFilePath", "")
                        if not ftp_path and uuid_val:
                            ftp_path = f"{uuid_val}.zip"
                        return ftp_path, item
        except Exception as e:
            print(f"[WARN] Failed to parse export list: {e}")

        print(f"[INFO] Waiting export ready... ({attempt + 1}/{max_wait // interval})")
        time.sleep(interval)

    return "", None


def _export_headers_extra(referer):
    return (
        f"Cookie: {SESSION_COOKIE}\r\n"
        f"language-option: en-US\r\n"
        f"timeZoneInfo: Default,Atlantic/Reykjavik,\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"Referer: {referer}\r\n"
        f"forgerydefense: {FORGERY_TOKEN}\r\n"
        f"Content-Type: application/json\r\n"
        f"Origin: https://{HOST}:{PORT}\r\n"
    )


def set_tt_export_columns():
    headers_extra = _export_headers_extra(TT_REFERER)
    body = json.dumps(TT_EXPORT_CONFIG)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", TT_USERHABITS_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Set TT export columns: {status}")

    ftp_file_path = ""
    if "200" in status:
        try:
            resp_text = resp_body.decode('utf-8')
            print(f"[DEBUG] userhabits response: {resp_text[:300]}")
            resp_data = json.loads(resp_text)
            if isinstance(resp_data, dict):
                ftp_file_path = resp_data.get("ftpFilePath", "")
                print(f"[INFO] Export ftpFilePath: {ftp_file_path}")
            else:
                print(f"[WARN] userhabits response is not dict: {type(resp_data)}, value={resp_data}")
        except Exception as e:
            print(f"[WARN] Failed to parse userhabits response: {e}")
    return ftp_file_path


def download_tt_export_zip(file_name, ftp_file_path="", output_dir=OUTPUT_DIR):
    headers_extra = _export_headers_extra(TT_REFERER)
    file_name_body = file_name if file_name.endswith(".zip") else f"{file_name}.zip"
    ftp_path_body = ftp_file_path if ftp_file_path.endswith(".zip") else f"{ftp_file_path}.zip"
    body_payload = {
        "fileName": file_name_body,
        "tableType": "eflow-tt",
    }
    if ftp_file_path:
        body_payload["ftpFilePath"] = ftp_path_body
    body = json.dumps(body_payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", TT_DOWNLOAD_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Download TT export: {status}, {len(resp_body)} bytes")

    if "200" not in status:
        try:
            err_text = resp_body.decode('utf-8')
            print(f"[DEBUG] Download error response: {err_text[:500]}")
        except Exception:
            pass
        raise Exception(f"Download failed: {status}")

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
    print(f"[INFO] ZIP saved: {zip_path}")
    return zip_path


def _read_data_file(path):
    """读取单个数据文件（CSV 或 Excel），用于 ZIP 内多文件并行读取。"""
    import pandas as pd
    if path.lower().endswith(".csv"):
        return pd.read_csv(path)
    return pd.read_excel(path)


def _read_data_files_parallel(file_paths, max_workers=4):
    """并行读取多个数据文件并合并为 DataFrame。"""
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor

    if not file_paths:
        return pd.DataFrame()

    dfs = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = executor.map(_read_data_file, file_paths)
        for df in results:
            dfs.append(df)

    if dfs:
        return pd.concat(dfs, ignore_index=True)
    return pd.DataFrame()


def read_tt_export_zip(zip_path):
    import zipfile
    import pandas as pd

    extract_dir = os.path.splitext(zip_path)[0]
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_dir)
        files = z.namelist()
        print(f"[INFO] ZIP extracted: {len(files)} files -> {extract_dir}")

    data_files = [f for f in files if f.lower().endswith((".xlsx", ".xls", ".csv"))]
    if not data_files:
        raise Exception("No data file found in ZIP")
    print(f"[INFO] TT ZIP data files: {len(data_files)} -> {data_files}")

    read_start = time.time()
    file_paths = [os.path.join(extract_dir, f) for f in data_files]
    df = _read_data_files_parallel(file_paths, max_workers=4)

    print(f"[INFO] TT export data: {len(df)} rows, {len(df.columns)} columns (read {time.time() - read_start:.2f}s)")
    records = df.to_dict("records")
    try:
        shutil.rmtree(extract_dir)
        print(f"[CLEAN] Removed TT extract dir: {extract_dir}")
    except OSError as e:
        print(f"[WARN] Cannot remove TT extract dir {extract_dir}: {e}")
    return records


def create_wo_export_task(filter_str, output_dir=OUTPUT_DIR):
    headers_extra = _export_headers_extra(WO_REFERER)
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
        "fileName": file_name,
        "type": "xlsx",
        "createTimeRange": "",
        "exportType": "0",
        "field": WO_EXPORT_COLUMNS,
        "fieldDetails": field_details,
        "filter": filter_str,
        "relationFilter": {"eflow_wo_wo_export_op": "", "eflow_wo_wo_attachment_export": ""},
        "relationTable": [],
        "tableName": "eflow_wo_wo_wo",
        "tableType": "eflow-wo",
    }
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", WO_ASYNC_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Create WO export task: {status}, {len(resp_body)} bytes")

    if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
        try:
            import gzip
            resp_body = gzip.decompress(resp_body)
        except Exception as e:
            print(f"[WARN] Failed to decompress WO async response: {e}")

    ftp_file_path = ""
    if "200" in status:
        try:
            resp_text = resp_body.decode('utf-8')
            resp_data = json.loads(resp_text)
            if isinstance(resp_data, dict):
                ftp_file_path = resp_data.get("ftpFilePath", "")
                if not ftp_file_path and isinstance(resp_data.get("data"), dict):
                    ftp_file_path = resp_data["data"].get("ftpFilePath", "")
        except Exception as e:
            print(f"[WARN] Failed to parse WO export async response: {e}")
    return ftp_file_path, file_name


def prepare_wo_export(filter_str):
    headers_extra = _export_headers_extra(WO_REFERER)
    payload = {
        "customInfo": {"pageType": "allTicket"},
        "field": WO_FIELDS,
        "filter": filter_str,
        "length": 1,
        "order": "lastModifiedTime desc",
        "relationFilter": {"eflow_wo_wo_asset": ""},
        "start": 0,
    }
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", WO_API_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Prepare WO export (base/list): {status}, {len(resp_body)} bytes")
    return status


def wait_wo_export_ready(file_name, max_wait=120, interval=5):
    headers_extra = _export_headers_extra(WO_REFERER)
    body = json.dumps({})

    for attempt in range(max_wait // interval):
        status, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", "/api/eflow-wo/v1/export/list/eflow-wo", headers_extra=headers_extra, body=body,
        )

        if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
            try:
                import gzip
                resp_body = gzip.decompress(resp_body)
            except Exception as e:
                print(f"[WARN] Failed to decompress WO export list response: {e}")

        try:
            resp_text = resp_body.decode('utf-8')
            data = json.loads(resp_text)

            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("result", data.get("data", []))

            for item in items:
                item_file_name = item.get("fileName", "")
                if file_name in item_file_name or item_file_name == file_name:
                    status_str = item.get("status", "")
                    uuid_val = item.get("uuid", "")
                    rate = item.get("rate", "")
                    print(f"[INFO] WO export task {item_file_name}: status={status_str}, rate={rate}, uuid={uuid_val}")
                    if status_str.lower() in ("success", "sucess") or rate == "100%":
                        ftp_path = item.get("ftpFilePath", "")
                        if not ftp_path and uuid_val:
                            ftp_path = f"{uuid_val}.zip"
                        return ftp_path, item
        except Exception as e:
            print(f"[WARN] Failed to parse WO export list: {e}")

        print(f"[INFO] Waiting WO export ready... ({attempt + 1}/{max_wait // interval})")
        time.sleep(interval)

    return "", None


def set_wo_export_columns():
    headers_extra = _export_headers_extra(WO_REFERER)
    body = json.dumps(WO_EXPORT_CONFIG)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", WO_USERHABITS_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Set WO export columns: {status}")
    return ""


def download_wo_export_zip(file_name, ftp_file_path="", output_dir=OUTPUT_DIR):
    headers_extra = _export_headers_extra(WO_REFERER)
    file_name_body = file_name if file_name.endswith(".zip") else f"{file_name}.zip"
    ftp_path_body = ftp_file_path if ftp_file_path.endswith(".zip") else f"{ftp_file_path}.zip"
    body_payload = {
        "fileName": file_name_body,
        "tableType": "eflow-wo",
    }
    if ftp_file_path:
        body_payload["ftpFilePath"] = ftp_path_body
    body = json.dumps(body_payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", WO_DOWNLOAD_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Download WO export: {status}, {len(resp_body)} bytes")

    if "200" not in status:
        try:
            err_text = resp_body.decode('utf-8')
            print(f"[DEBUG] WO Download error response: {err_text[:500]}")
        except Exception:
            pass
        raise Exception(f"WO Download failed: {status}")

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
    print(f"[INFO] WO ZIP saved: {zip_path}")
    return zip_path


def read_wo_export_zip(zip_path):
    import zipfile
    import pandas as pd

    extract_dir = os.path.splitext(zip_path)[0]
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_dir)
        files = z.namelist()
        print(f"[INFO] WO ZIP extracted: {len(files)} files -> {extract_dir}")

    data_files = [f for f in files if f.lower().endswith((".xlsx", ".xls", ".csv"))]
    if not data_files:
        raise Exception("No data file found in WO ZIP")
    print(f"[INFO] WO ZIP data files: {len(data_files)} -> {data_files}")

    read_start = time.time()
    file_paths = [os.path.join(extract_dir, f) for f in data_files]
    df = _read_data_files_parallel(file_paths, max_workers=4)

    print(f"[INFO] WO export data: {len(df)} rows, {len(df.columns)} columns (read {time.time() - read_start:.2f}s)")
    records = df.to_dict("records")
    try:
        shutil.rmtree(extract_dir)
        print(f"[CLEAN] Removed WO extract dir: {extract_dir}")
    except OSError as e:
        print(f"[WARN] Cannot remove WO extract dir {extract_dir}: {e}")
    return records


def create_cr_export_task(filter_str, output_dir=OUTPUT_DIR):
    headers_extra = _export_headers_extra(CR_REFERER)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"eflow-cr-export-{USERNAME}-{timestamp}"
    field_details = {}
    for col in CR_EXPORT_COLUMNS:
        meta = {"value": col, "name": f"field.{col}", "checked": True}
        if col.endswith("Detail"):
            meta["hide"] = True
        field_details[col] = meta
    payload = {
        "fileName": file_name,
        "type": "xlsx",
        "createTimeRange": "",
        "exportType": "0",
        "field": CR_EXPORT_COLUMNS,
        "fieldDetails": field_details,
        "filter": filter_str,
        "relationFilter": {"eflow_am_cr_op": ""},
        "relationTable": [],
        "tableName": "eflow_am_cr_wo",
        "tableType": "eflow-cr",
    }
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", CR_ASYNC_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Create CR export task: {status}, {len(resp_body)} bytes")

    if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
        try:
            import gzip
            resp_body = gzip.decompress(resp_body)
        except Exception as e:
            print(f"[WARN] Failed to decompress CR async response: {e}")

    ftp_file_path = ""
    if "200" in status:
        try:
            resp_text = resp_body.decode('utf-8')
            resp_data = json.loads(resp_text)
            if isinstance(resp_data, dict):
                ftp_file_path = resp_data.get("ftpFilePath", "")
                if not ftp_file_path and isinstance(resp_data.get("data"), dict):
                    ftp_file_path = resp_data["data"].get("ftpFilePath", "")
        except Exception as e:
            print(f"[WARN] Failed to parse CR export async response: {e}")
    return ftp_file_path, file_name


def prepare_cr_export(filter_str):
    headers_extra = _export_headers_extra(CR_REFERER)
    payload = {
        "customInfo": {"pageType": "allTicket"},
        "field": CR_FIELDS,
        "filter": filter_str,
        "length": 1,
        "order": "lastModifiedTime desc",
        "start": 0,
    }
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", CR_API_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Prepare CR export (base/list): {status}, {len(resp_body)} bytes")
    return status


def wait_cr_export_ready(file_name, max_wait=120, interval=5):
    headers_extra = _export_headers_extra(CR_REFERER)
    body = json.dumps({})

    for attempt in range(max_wait // interval):
        status, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", "/api/eflow-asset/v1/export/list/eflow-cr", headers_extra=headers_extra, body=body,
        )

        if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
            try:
                import gzip
                resp_body = gzip.decompress(resp_body)
            except Exception as e:
                print(f"[WARN] Failed to decompress CR export list response: {e}")

        try:
            resp_text = resp_body.decode('utf-8')
            data = json.loads(resp_text)

            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("result", data.get("data", []))

            for item in items:
                item_file_name = item.get("fileName", "")
                if file_name in item_file_name or item_file_name == file_name:
                    status_str = item.get("status", "")
                    uuid_val = item.get("uuid", "")
                    rate = item.get("rate", "")
                    print(f"[INFO] CR export task {item_file_name}: status={status_str}, rate={rate}, uuid={uuid_val}")
                    if status_str.lower() in ("success", "sucess") or rate == "100%":
                        ftp_path = item.get("ftpFilePath", "")
                        if not ftp_path and uuid_val:
                            ftp_path = f"{uuid_val}.zip"
                        return ftp_path, item
        except Exception as e:
            print(f"[WARN] Failed to parse CR export list: {e}")

        print(f"[INFO] Waiting CR export ready... ({attempt + 1}/{max_wait // interval})")
        time.sleep(interval)

    return "", None


def set_cr_export_columns():
    headers_extra = _export_headers_extra(CR_REFERER)
    body = json.dumps(CR_EXPORT_CONFIG)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", CR_USERHABITS_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Set CR export columns: {status}")
    return ""


def download_cr_export_zip(file_name, ftp_file_path="", output_dir=OUTPUT_DIR):
    headers_extra = _export_headers_extra(CR_REFERER)
    file_name_body = file_name if file_name.endswith(".zip") else f"{file_name}.zip"
    ftp_path_body = ftp_file_path if ftp_file_path.endswith(".zip") else f"{ftp_file_path}.zip"
    body_payload = {
        "fileName": file_name_body,
        "tableType": "eflow-cr",
    }
    if ftp_file_path:
        body_payload["ftpFilePath"] = ftp_path_body
    body = json.dumps(body_payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", CR_DOWNLOAD_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Download CR export: {status}, {len(resp_body)} bytes")

    if "200" not in status:
        try:
            err_text = resp_body.decode('utf-8')
            print(f"[DEBUG] CR Download error response: {err_text[:500]}")
        except Exception:
            pass
        raise Exception(f"CR Download failed: {status}")

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
    print(f"[INFO] CR ZIP saved: {zip_path}")
    return zip_path


def read_cr_export_zip(zip_path):
    import zipfile
    import pandas as pd

    extract_dir = os.path.splitext(zip_path)[0]
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_dir)
        files = z.namelist()
        print(f"[INFO] CR ZIP extracted: {len(files)} files -> {extract_dir}")

    data_files = [f for f in files if f.lower().endswith((".xlsx", ".xls", ".csv"))]
    if not data_files:
        raise Exception("No data file found in CR ZIP")
    print(f"[INFO] CR ZIP data files: {len(data_files)} -> {data_files}")

    read_start = time.time()
    file_paths = [os.path.join(extract_dir, f) for f in data_files]
    df = _read_data_files_parallel(file_paths, max_workers=4)

    print(f"[INFO] CR export data: {len(df)} rows, {len(df.columns)} columns (read {time.time() - read_start:.2f}s)")
    records = df.to_dict("records")
    try:
        shutil.rmtree(extract_dir)
        print(f"[CLEAN] Removed CR extract dir: {extract_dir}")
    except OSError as e:
        print(f"[WARN] Cannot remove CR extract dir {extract_dir}: {e}")
    return records


def fetch_eflow_cr_data(payload_base=CR_PAYLOAD_BASE):
    return fetch_paginated_data(CR_API_PATH, payload_base, CR_REFERER, "eFlow CR")


def create_pm_export_task(filter_str, output_dir=OUTPUT_DIR):
    headers_extra = _export_headers_extra(PM_REFERER)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"eflow-pm-task-export-{USERNAME}-{timestamp}"
    field_details = {}
    for col in PM_EXPORT_COLUMNS:
        meta = {"value": col, "name": f"field.{col}", "checked": True}
        if col.endswith("Detail"):
            meta["hide"] = True
        field_details[col] = meta
    payload = {
        "fileName": file_name,
        "type": "xlsx",
        "createTimeRange": "",
        "exportType": "0",
        "field": PM_EXPORT_COLUMNS,
        "fieldDetails": field_details,
        "filter": filter_str,
        "relationFilter": {"eflow_pm_export_op": ""},
        "relationTable": [],
        "tableName": "eflow_pm_task_wo",
        "tableType": "eflow-pm-task",
    }
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", PM_ASYNC_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Create PM export task: {status}, {len(resp_body)} bytes")

    if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
        try:
            import gzip
            resp_body = gzip.decompress(resp_body)
        except Exception as e:
            print(f"[WARN] Failed to decompress PM async response: {e}")

    ftp_file_path = ""
    if "200" in status:
        try:
            resp_text = resp_body.decode('utf-8')
            resp_data = json.loads(resp_text)
            if isinstance(resp_data, dict):
                ftp_file_path = resp_data.get("ftpFilePath", "")
                if not ftp_file_path and isinstance(resp_data.get("data"), dict):
                    ftp_file_path = resp_data["data"].get("ftpFilePath", "")
        except Exception as e:
            print(f"[WARN] Failed to parse PM export async response: {e}")
    return ftp_file_path, file_name


def prepare_pm_export(filter_str):
    headers_extra = _export_headers_extra(PM_REFERER)
    payload = {
        "customInfo": {"pageType": "allTicket"},
        "field": PM_FIELDS,
        "filter": filter_str,
        "length": 1,
        "order": "lastModifiedTime desc",
        "relationFilter": {"eflow_pm_task_asset": ""},
        "start": 0,
    }
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", PM_API_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Prepare PM export (base/list): {status}, {len(resp_body)} bytes")
    return status


def wait_pm_export_ready(file_name, max_wait=120, interval=5):
    headers_extra = _export_headers_extra(PM_REFERER)
    body = json.dumps({})

    for attempt in range(max_wait // interval):
        status, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", "/api/eflow-pm/v1/export/list/eflow-pm-task", headers_extra=headers_extra, body=body,
        )

        if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
            try:
                import gzip
                resp_body = gzip.decompress(resp_body)
            except Exception as e:
                print(f"[WARN] Failed to decompress PM export list response: {e}")

        try:
            resp_text = resp_body.decode('utf-8')
            data = json.loads(resp_text)

            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("result", data.get("data", []))

            for item in items:
                item_file_name = item.get("fileName", "")
                if file_name in item_file_name or item_file_name == file_name:
                    status_str = item.get("status", "")
                    uuid_val = item.get("uuid", "")
                    rate = item.get("rate", "")
                    print(f"[INFO] PM export task {item_file_name}: status={status_str}, rate={rate}, uuid={uuid_val}")
                    if status_str.lower() in ("success", "sucess") or rate == "100%":
                        ftp_path = item.get("ftpFilePath", "")
                        if not ftp_path and uuid_val:
                            ftp_path = f"{uuid_val}.zip"
                        return ftp_path, item
        except Exception as e:
            print(f"[WARN] Failed to parse PM export list: {e}")

        print(f"[INFO] Waiting PM export ready... ({attempt + 1}/{max_wait // interval})")
        time.sleep(interval)

    return "", None


def set_pm_export_columns():
    headers_extra = _export_headers_extra(PM_REFERER)
    body = json.dumps(PM_EXPORT_CONFIG)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", PM_USERHABITS_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Set PM export columns: {status}")
    return ""


def download_pm_export_zip(file_name, ftp_file_path="", output_dir=OUTPUT_DIR):
    headers_extra = _export_headers_extra(PM_REFERER)
    file_name_body = file_name if file_name.endswith(".zip") else f"{file_name}.zip"
    ftp_path_body = ftp_file_path if ftp_file_path.endswith(".zip") else f"{ftp_file_path}.zip"
    body_payload = {
        "fileName": file_name_body,
        "tableType": "eflow-pm-task",
    }
    if ftp_file_path:
        body_payload["ftpFilePath"] = ftp_path_body
    body = json.dumps(body_payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", PM_DOWNLOAD_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Download PM export: {status}, {len(resp_body)} bytes")

    if "200" not in status:
        try:
            err_text = resp_body.decode('utf-8')
            print(f"[DEBUG] PM Download error response: {err_text[:500]}")
        except Exception:
            pass
        raise Exception(f"PM Download failed: {status}")

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
    print(f"[INFO] PM ZIP saved: {zip_path}")
    return zip_path


def read_pm_export_zip(zip_path):
    import zipfile
    import pandas as pd

    extract_dir = os.path.splitext(zip_path)[0]
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_dir)
        files = z.namelist()
        print(f"[INFO] PM ZIP extracted: {len(files)} files -> {extract_dir}")

    data_files = [f for f in files if f.lower().endswith((".xlsx", ".xls", ".csv"))]
    if not data_files:
        raise Exception("No data file found in PM ZIP")
    print(f"[INFO] PM ZIP data files: {len(data_files)} -> {data_files}")

    read_start = time.time()
    file_paths = [os.path.join(extract_dir, f) for f in data_files]
    df = _read_data_files_parallel(file_paths, max_workers=4)

    print(f"[INFO] PM export data: {len(df)} rows, {len(df.columns)} columns (read {time.time() - read_start:.2f}s)")
    records = df.to_dict("records")
    try:
        shutil.rmtree(extract_dir)
        print(f"[CLEAN] Removed PM extract dir: {extract_dir}")
    except OSError as e:
        print(f"[WARN] Cannot remove PM extract dir {extract_dir}: {e}")
    return records


def create_site_export_task(output_dir=OUTPUT_DIR):
    headers_extra = _export_headers_extra(SITE_REFERER)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"Site-export-{USERNAME}-{timestamp}"
    payload = {
        "fileName": file_name,
        "callScene": "ui",
    }
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", SITE_ASYNC_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Create Site export task: {status}, {len(resp_body)} bytes")

    if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
        try:
            import gzip
            resp_body = gzip.decompress(resp_body)
        except Exception as e:
            print(f"[WARN] Failed to decompress Site async response: {e}")

    ftp_file_path = ""
    if "200" in status:
        try:
            resp_text = resp_body.decode('utf-8')
            resp_data = json.loads(resp_text)
            if isinstance(resp_data, dict):
                ftp_file_path = resp_data.get("ftpFilePath", "")
                if not ftp_file_path and isinstance(resp_data.get("data"), dict):
                    ftp_file_path = resp_data["data"].get("ftpFilePath", "")
        except Exception as e:
            print(f"[WARN] Failed to parse Site export async response: {e}")
    return ftp_file_path, file_name


def wait_site_export_ready(file_name, max_wait=120, interval=5):
    headers_extra = _export_headers_extra(SITE_REFERER)
    body = json.dumps({})

    for attempt in range(max_wait // interval):
        status, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", "/api/cmdb/v1/export/list/Site", headers_extra=headers_extra, body=body,
        )

        if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
            try:
                import gzip
                resp_body = gzip.decompress(resp_body)
            except Exception as e:
                print(f"[WARN] Failed to decompress Site export list response: {e}")

        try:
            resp_text = resp_body.decode('utf-8')
            data = json.loads(resp_text)

            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("result", data.get("data", []))

            for item in items:
                item_file_name = item.get("fileName", "")
                if file_name in item_file_name or item_file_name == file_name:
                    status_str = item.get("status", "")
                    uuid_val = item.get("uuid", "")
                    rate = item.get("rate", "")
                    print(f"[INFO] Site export task {item_file_name}: status={status_str}, rate={rate}, uuid={uuid_val}")
                    if status_str.lower() in ("success", "sucess") or rate == "100%":
                        ftp_path = item.get("ftpFilePath", "")
                        if not ftp_path and uuid_val:
                            ftp_path = f"{uuid_val}.zip"
                        return ftp_path, item
        except Exception as e:
            print(f"[WARN] Failed to parse Site export list: {e}")

        print(f"[INFO] Waiting Site export ready... ({attempt + 1}/{max_wait // interval})")
        time.sleep(interval)

    return "", None


def download_site_export_zip(file_name, ftp_file_path="", output_dir=OUTPUT_DIR):
    headers_extra = _export_headers_extra(SITE_REFERER)
    file_name_body = file_name if file_name.endswith(".zip") else f"{file_name}.zip"
    ftp_path_body = ftp_file_path if ftp_file_path.endswith(".zip") else f"{ftp_file_path}.zip"
    body_payload = {
        "fileName": file_name_body,
        "tableType": "Site",
    }
    if ftp_file_path:
        body_payload["ftpFilePath"] = ftp_path_body
    body = json.dumps(body_payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", SITE_DOWNLOAD_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Download Site export: {status}, {len(resp_body)} bytes")

    if "200" not in status:
        try:
            err_text = resp_body.decode('utf-8')
            print(f"[DEBUG] Site Download error response: {err_text[:500]}")
        except Exception:
            pass
        raise Exception(f"Site Download failed: {status}")

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
    print(f"[INFO] Site ZIP saved: {zip_path}")
    return zip_path


def read_site_export_zip(zip_path):
    import zipfile
    import pandas as pd

    extract_dir = os.path.splitext(zip_path)[0]
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_dir)
        files = z.namelist()
        print(f"[INFO] Site ZIP extracted: {len(files)} files -> {extract_dir}")

    data_files = [f for f in files if f.lower().endswith((".xlsx", ".xls", ".csv"))]
    if not data_files:
        raise Exception("No data file found in Site ZIP")

    dfs = []
    for data_file in data_files:
        full_path = os.path.join(extract_dir, data_file)
        if full_path.lower().endswith(".csv"):
            dfs.append(pd.read_csv(full_path))
        else:
            dfs.append(pd.read_excel(full_path))

    if dfs:
        df = pd.concat(dfs, ignore_index=True)
    else:
        df = pd.DataFrame()

    print(f"[INFO] Site export data: {len(df)} rows, {len(df.columns)} columns")
    records = df.to_dict("records")
    try:
        shutil.rmtree(extract_dir)
        print(f"[CLEAN] Removed Site extract dir: {extract_dir}")
    except OSError as e:
        print(f"[WARN] Cannot remove Site extract dir {extract_dir}: {e}")
    return records


def create_person_export_task(output_dir=OUTPUT_DIR):
    headers_extra = _export_headers_extra(PERSON_REFERER)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"Person-export-{USERNAME}-{timestamp}"
    payload = {
        "fileName": file_name,
        "callScene": "ui",
    }
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", PERSON_ASYNC_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Create Person export task: {status}, {len(resp_body)} bytes")

    if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
        try:
            import gzip
            resp_body = gzip.decompress(resp_body)
        except Exception as e:
            print(f"[WARN] Failed to decompress Person async response: {e}")

    ftp_file_path = ""
    if "200" in status:
        try:
            resp_text = resp_body.decode('utf-8')
            resp_data = json.loads(resp_text)
            if isinstance(resp_data, dict):
                ftp_file_path = resp_data.get("ftpFilePath", "")
                if not ftp_file_path and isinstance(resp_data.get("data"), dict):
                    ftp_file_path = resp_data["data"].get("ftpFilePath", "")
        except Exception as e:
            print(f"[WARN] Failed to parse Person export async response: {e}")
    return ftp_file_path, file_name


def wait_person_export_ready(file_name, max_wait=120, interval=5):
    headers_extra = _export_headers_extra(PERSON_REFERER)
    body = json.dumps({})

    for attempt in range(max_wait // interval):
        status, hdrs, raw_hdrs, resp_body = _http_request(
            "POST", "/api/cmdb/v1/export/list/Person", headers_extra=headers_extra, body=body,
        )

        if "gzip" in hdrs.get("content-encoding", "").lower() and resp_body:
            try:
                import gzip
                resp_body = gzip.decompress(resp_body)
            except Exception as e:
                print(f"[WARN] Failed to decompress Person export list response: {e}")

        try:
            resp_text = resp_body.decode('utf-8')
            data = json.loads(resp_text)

            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("result", data.get("data", []))

            for item in items:
                item_file_name = item.get("fileName", "")
                if file_name in item_file_name or item_file_name == file_name:
                    status_str = item.get("status", "")
                    uuid_val = item.get("uuid", "")
                    rate = item.get("rate", "")
                    print(f"[INFO] Person export task {item_file_name}: status={status_str}, rate={rate}, uuid={uuid_val}")
                    if status_str.lower() in ("success", "sucess") or rate == "100%":
                        ftp_path = item.get("ftpFilePath", "")
                        if not ftp_path and uuid_val:
                            ftp_path = f"{uuid_val}.zip"
                        return ftp_path, item
        except Exception as e:
            print(f"[WARN] Failed to parse Person export list: {e}")

        print(f"[INFO] Waiting Person export ready... ({attempt + 1}/{max_wait // interval})")
        time.sleep(interval)

    return "", None


def download_person_export_zip(file_name, ftp_file_path="", output_dir=OUTPUT_DIR):
    headers_extra = _export_headers_extra(PERSON_REFERER)
    file_name_body = file_name if file_name.endswith(".zip") else f"{file_name}.zip"
    ftp_path_body = ftp_file_path if ftp_file_path.endswith(".zip") else f"{ftp_file_path}.zip"
    body_payload = {
        "fileName": file_name_body,
        "tableType": "Person",
    }
    if ftp_file_path:
        body_payload["ftpFilePath"] = ftp_path_body
    body = json.dumps(body_payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", PERSON_DOWNLOAD_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Download Person export: {status}, {len(resp_body)} bytes")

    if "200" not in status:
        try:
            err_text = resp_body.decode('utf-8')
            print(f"[DEBUG] Person Download error response: {err_text[:500]}")
        except Exception:
            pass
        raise Exception(f"Person Download failed: {status}")

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
    print(f"[INFO] Person ZIP saved: {zip_path}")
    return zip_path


def read_person_export_zip(zip_path):
    import zipfile
    import pandas as pd

    extract_dir = os.path.splitext(zip_path)[0]
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_dir)
        files = z.namelist()
        print(f"[INFO] Person ZIP extracted: {len(files)} files -> {extract_dir}")

    data_files = [f for f in files if f.lower().endswith((".xlsx", ".xls", ".csv"))]
    if not data_files:
        raise Exception("No data file found in Person ZIP")

    dfs = []
    for data_file in data_files:
        full_path = os.path.join(extract_dir, data_file)
        if full_path.lower().endswith(".csv"):
            dfs.append(pd.read_csv(full_path))
        else:
            dfs.append(pd.read_excel(full_path))

    if dfs:
        df = pd.concat(dfs, ignore_index=True)
    else:
        df = pd.DataFrame()

    print(f"[INFO] Person export data: {len(df)} rows, {len(df.columns)} columns")
    records = df.to_dict("records")
    try:
        shutil.rmtree(extract_dir)
        print(f"[CLEAN] Removed Person extract dir: {extract_dir}")
    except OSError as e:
        print(f"[WARN] Cannot remove Person extract dir {extract_dir}: {e}")
    return records


def fetch_site_export_xlsx(output_dir=OUTPUT_DIR):
    """CMDB Site 导出为同步下载，响应体即为 Site.xlsx 文件。"""
    headers_extra = _export_headers_extra(SITE_REFERER)
    payload = {"callScene": "ui"}
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", SITE_ASYNC_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Site export: {status}, {len(resp_body)} bytes")

    if "200" not in status:
        try:
            err_text = resp_body.decode('utf-8')
            print(f"[DEBUG] Site export error response: {err_text[:500]}")
        except Exception:
            pass
        raise Exception(f"Site export failed: {status}")

    filename = "Site.xlsx"
    cd = hdrs.get("content-disposition", "")
    if cd:
        fn_match = re.search(r'filename=["\']?([^"\';]+)', cd)
        if fn_match:
            filename = fn_match.group(1)

    xlsx_path = os.path.join(output_dir, filename)
    seq = 1
    while os.path.exists(xlsx_path):
        base, ext = os.path.splitext(filename)
        xlsx_path = os.path.join(output_dir, f"{base}_{seq}{ext}")
        seq += 1

    with open(xlsx_path, "wb") as f:
        f.write(resp_body)
    print(f"[INFO] Site XLSX saved: {xlsx_path}")
    return xlsx_path


def read_site_xlsx(xlsx_path):
    import pandas as pd
    t0 = time.time()
    df = pd.read_excel(xlsx_path)
    print(f"[INFO] Site export data: {len(df)} rows, {len(df.columns)} columns (read {time.time() - t0:.2f}s)")
    return df.to_dict("records")


def fetch_person_export_xlsx(output_dir=OUTPUT_DIR):
    """CMDB Person 导出为同步下载，响应体即为 Person.xlsx 文件。"""
    headers_extra = _export_headers_extra(PERSON_REFERER)
    payload = {"callScene": "ui"}
    body = json.dumps(payload)
    status, hdrs, raw_hdrs, resp_body = _http_request(
        "POST", PERSON_ASYNC_PATH, headers_extra=headers_extra, body=body,
    )
    print(f"[INFO] Person export: {status}, {len(resp_body)} bytes")

    if "200" not in status:
        try:
            err_text = resp_body.decode('utf-8')
            print(f"[DEBUG] Person export error response: {err_text[:500]}")
        except Exception:
            pass
        raise Exception(f"Person export failed: {status}")

    filename = "Person.xlsx"
    cd = hdrs.get("content-disposition", "")
    if cd:
        fn_match = re.search(r'filename=["\']?([^"\';]+)', cd)
        if fn_match:
            filename = fn_match.group(1)

    xlsx_path = os.path.join(output_dir, filename)
    seq = 1
    while os.path.exists(xlsx_path):
        base, ext = os.path.splitext(filename)
        xlsx_path = os.path.join(output_dir, f"{base}_{seq}{ext}")
        seq += 1

    with open(xlsx_path, "wb") as f:
        f.write(resp_body)
    print(f"[INFO] Person XLSX saved: {xlsx_path}")
    return xlsx_path


def read_person_xlsx(xlsx_path):
    import pandas as pd
    t0 = time.time()
    df = pd.read_excel(xlsx_path)
    print(f"[INFO] Person export data: {len(df)} rows, {len(df.columns)} columns (read {time.time() - t0:.2f}s)")
    return df.to_dict("records")


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

    df.to_excel(writer, index=False, sheet_name=sheet_name)
    worksheet = writer.sheets[sheet_name]
    workbook = writer.book

    header_format = workbook.add_format({
        "bold": True,
        "bg_color": "#4472C4",
        "font_color": "#FFFFFF",
    })
    worksheet.set_row(0, None, header_format)

    # 列宽采样计算，xlsxwriter 比 openpyxl 快一个数量级
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
    return sheet_name.replace(" ", "_").lower()


def save_to_sqlite(sheets_data):
    import pandas as pd

    start_time = time.time()
    db_path = os.path.join(OUTPUT_DIR, "eflow.sqlite3")
    conn = sqlite3.connect(db_path)

    for sheet_name, rows in sheets_data:
        t0 = time.time()
        if not isinstance(rows, list) or not rows:
            print(f"[SKIP] {sheet_name}: no data")
            continue
        df = pd.DataFrame(rows)
        # SQLite 不支持 list/dict 类型，仅对 object/str 列检测并转换
        object_cols = df.select_dtypes(include=["object", "str"]).columns
        for col in object_cols:
            if df[col].apply(lambda x: isinstance(x, (list, dict))).any():
                df[col] = df[col].apply(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else x)
        table = _table_name(sheet_name)
        # 不使用 method='multi'，避免列数多（如 158 列）触发 SQLite "too many SQL variables"
        df.to_sql(table, conn, if_exists="replace", index=False, chunksize=5000)
        print(f"[INFO] SQLite table '{table}': {len(df)} rows, {len(df.columns)} columns ({time.time() - t0:.2f}s)")

    conn.close()
    print(f"[INFO] SQLite saved: {db_path} (total {time.time() - start_time:.2f}s)")
    return db_path


def write_excel_from_sqlite(sheets_data):
    import pandas as pd

    start_time = time.time()
    db_path = os.path.join(OUTPUT_DIR, "eflow.sqlite3")
    conn = sqlite3.connect(db_path)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(OUTPUT_DIR, f"eflow_{timestamp}.xlsx")

    seq = 1
    while os.path.exists(output_file):
        output_file = os.path.join(OUTPUT_DIR, f"eflow_{timestamp}_{seq}.xlsx")
        seq += 1

    with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
        for sheet_name, _ in sheets_data:
            t0 = time.time()
            table = _table_name(sheet_name)
            df = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
            if df.empty:
                print(f"[SKIP] {sheet_name}: no data")
                continue
            _write_sheet(writer, df, sheet_name)
            print(f"[INFO] Excel {sheet_name}: {len(df)} rows, {len(df.columns)} columns ({time.time() - t0:.2f}s)")

    conn.close()
    print(f"[INFO] Excel saved: {output_file} (total {time.time() - start_time:.2f}s)")

    # 删除旧 Excel 文件，只保留最新
    for old_file in glob.glob(os.path.join(OUTPUT_DIR, "eflow_*.xlsx")):
        if os.path.abspath(old_file) != os.path.abspath(output_file):
            try:
                os.remove(old_file)
                print(f"[CLEAN] Deleted old file: {os.path.basename(old_file)}")
            except OSError:
                print(f"[WARN] Cannot delete (in use): {os.path.basename(old_file)}")

    return output_file


def cleanup_old_export_files(output_dir=OUTPUT_DIR):
    """SQLite 生成后，按类型只保留最新导出文件，删除旧文件和解压目录。"""
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
                print(f"[CLEAN] Deleted old export ZIP: {os.path.basename(old_file)}")
            except OSError as e:
                print(f"[WARN] Cannot delete {old_file}: {e}")

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
                print(f"[CLEAN] Deleted old export XLSX: {os.path.basename(old_file)}")
            except OSError as e:
                print(f"[WARN] Cannot delete {old_file}: {e}")

    # 删除残留的解压目录（正常情况下读取后已删除，这里兜底）
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
                print(f"[CLEAN] Deleted old extract dir: {name}")
            except OSError as e:
                print(f"[WARN] Cannot delete dir {full_path}: {e}")


def _fetch_tt_pipeline(start_ms, end_ms):
    tt_filter = TIME_FILTER_TEMPLATE.format(status_filter=TT_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)
    prepare_tt_export(tt_filter)
    set_tt_export_columns()
    ftp_file_path, file_name = create_tt_export_task(tt_filter)
    print(f"[INFO] Created TT export task file name: {file_name}")
    print(f"[INFO] Waiting 10s before polling TT export status...")
    time.sleep(10)
    ftp_file_path, _ = wait_tt_export_ready(file_name, max_wait=600, interval=10)
    print(f"[INFO] TT export ready ftpFilePath: {ftp_file_path}")
    zip_path = download_tt_export_zip(file_name, ftp_file_path)
    rows = read_tt_export_zip(zip_path)
    return ("eFlow TT", rows)


def _fetch_wo_pipeline(start_ms, end_ms):
    wo_filter = TIME_FILTER_TEMPLATE.format(status_filter=WO_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)
    prepare_wo_export(wo_filter)
    set_wo_export_columns()
    ftp_file_path, file_name = create_wo_export_task(wo_filter)
    print(f"[INFO] Created WO export task file name: {file_name}")
    print(f"[INFO] Waiting 10s before polling WO export status...")
    time.sleep(10)
    ftp_file_path, _ = wait_wo_export_ready(file_name, max_wait=600, interval=10)
    print(f"[INFO] WO export ready ftpFilePath: {ftp_file_path}")
    zip_path = download_wo_export_zip(file_name, ftp_file_path)
    rows = read_wo_export_zip(zip_path)
    return ("eFlow WO", rows)


def _fetch_cr_pipeline(start_ms, end_ms):
    cr_filter = TIME_FILTER_TEMPLATE.format(status_filter=CR_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)
    prepare_cr_export(cr_filter)
    set_cr_export_columns()
    ftp_file_path, file_name = create_cr_export_task(cr_filter)
    print(f"[INFO] Created CR export task file name: {file_name}")
    print(f"[INFO] Waiting 10s before polling CR export status...")
    time.sleep(10)
    ftp_file_path, _ = wait_cr_export_ready(file_name, max_wait=600, interval=10)
    print(f"[INFO] CR export ready ftpFilePath: {ftp_file_path}")
    zip_path = download_cr_export_zip(file_name, ftp_file_path)
    rows = read_cr_export_zip(zip_path)
    return ("eFlow CR", rows)


def _fetch_pm_pipeline(start_ms, end_ms):
    pm_filter = TIME_FILTER_TEMPLATE.format(status_filter=PM_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)
    prepare_pm_export(pm_filter)
    set_pm_export_columns()
    ftp_file_path, file_name = create_pm_export_task(pm_filter)
    print(f"[INFO] Created PM export task file name: {file_name}")
    print(f"[INFO] Waiting 10s before polling PM export status...")
    time.sleep(10)
    ftp_file_path, _ = wait_pm_export_ready(file_name, max_wait=600, interval=10)
    print(f"[INFO] PM export ready ftpFilePath: {ftp_file_path}")
    zip_path = download_pm_export_zip(file_name, ftp_file_path)
    rows = read_pm_export_zip(zip_path)
    return ("eFlow PM", rows)


def _fetch_site_pipeline():
    xlsx_path = fetch_site_export_xlsx()
    rows = read_site_xlsx(xlsx_path)
    return ("Site", rows)


def _fetch_person_pipeline():
    xlsx_path = fetch_person_export_xlsx()
    rows = read_person_xlsx(xlsx_path)
    return ("Person", rows)


# ============================================================
# 获取数据后生成 Excel 报告与图片（复用 mail_126.py 的方法）
# ============================================================
TT_REPORT_SUBDIR = "tt_reports"          # 报告与图片输出子目录
SEND_EMAIL_AFTER_REPORT = False          # 是否在生成报告后发送邮件（需配置 to_receiver.txt）

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


def _build_site_tx_map(sheets_data, processor_cls):
    """从 Site 数据构建 (site_id_map, site_name_map) -> TX(TRM Type) 映射。

    site_id_map: normalize_id(Site ID) -> TX
    site_name_map: strip(Site Name) -> TX
    返回 (id_map, name_map)；Site 无数据或无 TX 列时返回 ({}, {})。
    """
    import pandas as pd

    site_rows = []
    for sheet_name, rows in sheets_data:
        if sheet_name == "Site":
            site_rows = rows or []
            break
    if not site_rows:
        return {}, {}

    df_site = pd.DataFrame(site_rows)
    df_site = processor_cls.clean_columns(df_site)
    if SITE_TX_SOURCE_COL not in df_site.columns:
        print(f"[WARN] Site 表无 '{SITE_TX_SOURCE_COL}' 列，无法生成 TX 映射")
        return {}, {}

    id_map = {}
    name_map = {}
    for _, r in df_site.iterrows():
        tx_val = r.get(SITE_TX_SOURCE_COL)
        if pd.isna(tx_val):
            tx_val = ""
        tx_val = str(tx_val).strip()
        sid = processor_cls.normalize_id(r.get("Site ID"))
        sname = str(r.get("Site Name", "")).strip()
        if sid:
            id_map[sid] = tx_val
        if sname:
            name_map[sname] = tx_val
    print(f"[INFO] TX 映射构建完成: {len(id_map)} by Site ID, {len(name_map)} by Site Name")
    return id_map, name_map


def _import_excel_processor():
    """安全导入 mail_126.ExcelDataProcessor。

    mail_126.py 顶部依赖 `from process_site_person import process`，
    且 EmailSender 类级属性会执行 pd.read_csv("to_receiver.txt")；
    本函数在导入前注入占位模块并补齐 to_receiver.txt，避免 ImportError。
    返回 (ExcelDataProcessor, EmailSender)。
    """
    import sys
    import types

    script_dir = OUTPUT_DIR

    # 1) 注入 process_site_person 占位模块（mail_126.py 顶部 import 依赖）
    if "process_site_person" not in sys.modules:
        stub = types.ModuleType("process_site_person")
        stub.process = lambda *args, **kwargs: None
        sys.modules["process_site_person"] = stub

    # 2) 确保 to_receiver.txt 存在（EmailSender 类级 pd.read_csv 依赖，相对 CWD）
    receiver_file = os.path.join(script_dir, "to_receiver.txt")
    if not os.path.exists(receiver_file):
        with open(receiver_file, "w", encoding="utf-8") as f:
            f.write("nobody@example.invalid\n")
        print(f"[INFO] Created placeholder {receiver_file} (请替换为真实收件人邮箱以启用邮件发送)")

    # 3) 将脚本目录加入 sys.path
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    # 4) 切到脚本目录导入（pd.read_csv("to_receiver.txt") 依赖 CWD），导入后恢复
    prev_cwd = os.getcwd()
    try:
        os.chdir(script_dir)
        from mail_126 import ExcelDataProcessor, EmailSender
    finally:
        os.chdir(prev_cwd)
    return ExcelDataProcessor, EmailSender


def generate_excel_and_images(sheets_data, output_dir=None, send_email=None):
    """获取数据后生成 Excel 报告与图片，复用 mail_126.py 的方法。

    流程：提取 eFlow TT 数据 → 列名映射 → 字段提取 → Hourly Report →
          8 Hours Report → TT Summary 计算 → Summary Report → 图片（→ 邮件）。
    跳过 read_excel_data 以避免 Site_Maintainer_Category.xlsx 主数据依赖。
    返回生成文件路径字典；失败返回 None。
    """
    import pandas as pd

    total_start = time.time()
    start_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if output_dir is None:
        output_dir = os.path.join(OUTPUT_DIR, TT_REPORT_SUBDIR)
    if send_email is None:
        send_email = SEND_EMAIL_AFTER_REPORT

    print("\n" + "=" * 60)
    print(f"Generate Excel & Images - {start_time_str}")
    print("=" * 60)

    # 导入 mail_126（处理其导入期依赖）
    try:
        ExcelDataProcessor, EmailSender = _import_excel_processor()
    except Exception as e:
        import traceback
        print(f"[ERROR] 无法导入 mail_126.ExcelDataProcessor: {e}")
        traceback.print_exc()
        return None

    # 1. 提取 eFlow TT 数据
    tt_rows = []
    for sheet_name, rows in sheets_data:
        if sheet_name == "eFlow TT":
            tt_rows = rows or []
            break
    if not tt_rows:
        print("[WARN] No eFlow TT data, skip report generation")
        return None
    print(f"[INFO] eFlow TT rows: {len(tt_rows)}")

    # 2. 构建 DataFrame 并重命名列以匹配 ExcelDataProcessor 期望
    df_source = pd.DataFrame(tt_rows)
    df_source = ExcelDataProcessor.clean_columns(df_source)
    rename_map = {k: v for k, v in _TT_COLUMN_RENAME.items() if k in df_source.columns}
    if rename_map:
        df_source = df_source.rename(columns=rename_map)
    print(f"[INFO] TT DataFrame: {df_source.shape}, renamed: {rename_map}")

    # 2.5 添加 TX 列：从 Site 表的 TRM Type 按 Site ID/Name 匹配
    id_map, name_map = _build_site_tx_map(sheets_data, ExcelDataProcessor)
    if "Site ID" in df_source.columns:
        df_source["Site ID"] = df_source["Site ID"].apply(ExcelDataProcessor.normalize_id)
    if id_map or name_map:
        df_source["TX"] = df_source["Site ID"].map(id_map) if "Site ID" in df_source.columns else ""
        # Site ID 匹配不上的，用 Site Name 后备匹配
        mask = df_source["TX"].isna()
        if mask.any() and name_map and "Site Name" in df_source.columns:
            df_source.loc[mask, "TX"] = (
                df_source.loc[mask, "Site Name"].astype(str).str.strip().map(name_map)
            )
        df_source["TX"] = df_source["TX"].fillna("")
        matched = (df_source["TX"].astype(str).str.strip() != "").sum()
        print(f"[INFO] TX 列已添加，匹配率: {matched}/{len(df_source)} "
              f"({matched / max(len(df_source), 1) * 100:.1f}%)")
    else:
        df_source["TX"] = ""
        print("[WARN] TX 列为空（Site 表无 TRM Type 数据）")

    # 3. 直接设置数据源（跳过 read_excel_data，避免主数据文件依赖）
    ExcelDataProcessor.df_master_cache = None
    ExcelDataProcessor.df_eflow_source = df_source

    hourly_file = eight_hour_file = eight_hour_img = summary_file = None
    image_paths = []
    try:
        # 4. 字段提取
        step_start = time.time()
        print("\n📌 步骤1: 提取字段...")
        df_extracted = ExcelDataProcessor.extract_fields()
        print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

        # 4.5 填补缺失的 SLA Status（eFlow 导出为空时，用时间差计算）
        step_start = time.time()
        print("\n📌 步骤1.5: 填补缺失的 SLA Status...")
        ExcelDataProcessor.fill_missing_sla_status(df_extracted)
        print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

        # 5. Hourly Report
        step_start = time.time()
        print("\n📌 步骤2: 生成 Hourly Report...")
        hourly_file, _ = ExcelDataProcessor.write_hourly_report(
            df_extracted, output_dir=output_dir)
        print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

        # 6. 8 Hours Report
        step_start = time.time()
        print("\n📌 步骤3: 生成 8 Hours Report...")
        eight_hour_file, eight_hour_img, _ = ExcelDataProcessor.write_8hours_report(
            df_extracted, output_dir=output_dir)
        print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

        # 7. TT Summary 计算
        step_start = time.time()
        print("\n📌 步骤4: 计算 SLA Status / Summary...")
        df_open, open_tickets, prolong_tickets, summary_df, raw_df = \
            ExcelDataProcessor.compute_tt_summary(df_extracted)
        print(f"   Open Tickets: {len(open_tickets)}, Prolong: {len(prolong_tickets)}")
        print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

        # 8. TT Summary Report
        step_start = time.time()
        print("\n📌 步骤5: 生成 TT Summary Report...")
        summary_file = ExcelDataProcessor.write_summary_report(
            open_tickets, prolong_tickets, summary_df, raw_df, output_dir=output_dir)
        print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

        # 9. 图片
        step_start = time.time()
        print("\n📌 步骤6: 生成图片（matplotlib）...")
        image_paths = ExcelDataProcessor.generate_summary_images(
            summary_df, open_tickets, prolong_tickets, output_dir)
        print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

        # 10. 邮件（可选）
        if send_email:
            step_start = time.time()
            print("\n📌 步骤7: 发送邮件...")
            try:
                EmailSender.send_report_email(summary_file, summary_df, image_paths=image_paths)
            except Exception as e:
                print(f"❌ 邮件发送失败: {e}")
            print(f"   ⏱️ 用时: {time.time() - step_start:.2f}s")

    except Exception as e:
        import traceback
        print(f"[ERROR] 报告生成失败: {e}")
        traceback.print_exc()
        return None

    total_elapsed = time.time() - total_start
    end_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n🎉 报告生成完成!")
    print(f"⏰ 开始时间: {start_time_str}")
    print(f"⏰ 结束时间: {end_time_str}")
    print(f"⏱️ 总用时: {total_elapsed:.2f}s")
    if hourly_file:
        print(f"📁 Hourly Report: {hourly_file}")
    if eight_hour_file:
        print(f"📁 8 Hours Report: {eight_hour_file}")
    if summary_file:
        print(f"📁 Summary Report: {summary_file}")
    for p in image_paths:
        print(f"🖼️  图片: {p}")

    return {
        "hourly_file": hourly_file,
        "eight_hour_file": eight_hour_file,
        "eight_hour_img": eight_hour_img,
        "summary_file": summary_file,
        "image_paths": image_paths,
    }


def main():
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor, as_completed

    start_time = time.time()
    print("=" * 60)
    print(f"eFlow TT Fetcher - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    login()

    try:
        start_ms, end_ms = _get_time_range_ms()
        print(f"[INFO] Time range: {start_ms} to {end_ms}")

        pipelines = [
            ("tt", lambda: _fetch_tt_pipeline(start_ms, end_ms)),
            ("wo", lambda: _fetch_wo_pipeline(start_ms, end_ms)),
            ("cr", lambda: _fetch_cr_pipeline(start_ms, end_ms)),
            ("pm", lambda: _fetch_pm_pipeline(start_ms, end_ms)),
            ("site", _fetch_site_pipeline),
            ("person", _fetch_person_pipeline),
        ]

        results = {}
        print(f"[INFO] Starting parallel export pipelines (max_workers={MAX_PARALLEL_DOWNLOADS})...")
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_DOWNLOADS) as executor:
            future_to_key = {executor.submit(fn): key for key, fn in pipelines}
            for future in as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    sheet_name, rows = future.result()
                    results[sheet_name] = rows
                    print(f"[INFO] {sheet_name} pipeline completed: {len(rows)} rows")
                except Exception as e:
                    print(f"[ERROR] {key} pipeline failed: {e}")
                    import traceback
                    traceback.print_exc()

        sheets_data = [
            ("eFlow TT", results.get("eFlow TT", [])),
            ("eFlow WO", results.get("eFlow WO", [])),
            ("eFlow CR", results.get("eFlow CR", [])),
            ("eFlow PM", results.get("eFlow PM", [])),
            ("Site", results.get("Site", [])),
            ("Person", results.get("Person", [])),
        ]
        save_to_sqlite(sheets_data)
        cleanup_old_export_files()

        # 获取数据后生成 Excel 报告与图片（复用 mail_126.py 的方法）
        generate_excel_and_images(sheets_data)

    except Exception as e:
        import traceback
        print(f"[ERROR] {e}")
        traceback.print_exc()

    total_elapsed = time.time() - start_time
    print(f"\n[DONE] Completed in {total_elapsed:.2f}s")


if __name__ == "__main__":
    main()
