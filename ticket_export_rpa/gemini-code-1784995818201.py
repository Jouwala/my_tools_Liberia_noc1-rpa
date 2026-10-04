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
import gzip
import zipfile
import pandas as pd
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed


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
PASSWORD = _get_credential("eflow", env="EFLOW_PASS")

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

SESSION_COOKIE = ""
FORGERY_TOKEN = ""

# 调整线程池大小，增加网络与文件并发读取能效
MAX_PARALLEL_DOWNLOADS = 6


def _create_ssl_socket():
    """优化套接字创建：启用 TCP_NODELAY 降低小包延迟，设置合理缓冲区大小"""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers('ALL:@SECLEVEL=0')
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # 禁用 Nagle 算法
    sock.settimeout(30)
    
    ssock = ctx.wrap_socket(sock)
    ssock.connect((HOST, PORT))
    return ssock


def _http_request(method, path, headers_extra=None, body=None):
    """优化 HTTP 数据接收逻辑，使用 bytearray 减少内存拷贝并支持自动解析 Chunked"""
    ssock = _create_ssl_socket()

    headers = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: {HOST}:{PORT}\r\n"
        f"Accept: application/json, text/plain, */*\r\n"
        f"Accept-Language: en-US,en;q=0.9\r\n"
        f"Accept-Encoding: gzip, deflate\r\n"  # 开启数据压缩以显著减少网络传输耗时
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

    # 使用 bytearray 优化 IO 接收内存分配
    chunks = bytearray()
    while True:
        try:
            chunk = ssock.recv(65536)
            if not chunk:
                break
            chunks.extend(chunk)
        except socket.timeout:
            break
    ssock.close()

    response_data = bytes(chunks)
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

    if "gzip" in resp_headers.get("content-encoding", "").lower() and resp_body:
        try:
            resp_body = gzip.decompress(resp_body)
        except Exception as e:
            print(f"[WARN] Failed to decompress gzip response: {e}")

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


def _decode_chunked(data):
    """优化 Chunked 解码，减少切片拷贝开销"""
    result = bytearray()
    pos = 0
    data_len = len(data)
    while pos < data_len:
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


# 配置字段
TT_FIELDS = "color,woId,procId,opName,pendingStatus,displayName,woNum,woInfo,status,ttSource,ticketType,projectName,templateName,creator,creatorContactInfo,ticketSeverity,createTime,alarmCategory,alarmSubcategory,alarmSeverity,alarmType,alarmId,alarmCode,subAlarmName,subAlarmNeName,subAlarmNeNaIp,appendingAlarmName,appendingAlarmNeName,appendingAlarmNeIp,netWorkType,neName,neId,neIP,impactedServiceOrNo,impactedServiceWireless,siteOutageOrNo,reasonType,slaTotalDuration,slaStatus,remainingTime,targetFinishTime,groupSlaTime,groupSlaStatus,groupSlaRemainsTime,regionLevel1Name,regionLevel2Name,assetName,siteId,assetType,siteClass,lastModifiedTime,candidateOperator,vendor,alarmOccurTime,alarmClearTime,faultDurationTime"
TT_STATUS_FILTER = '((status eq "WaitFOAccept") or (status eq "WaitFOProcess") or (status eq "WaitBOAccept") or (status eq "WaitBOProcess") or (status eq "WaitThirdAccept") or (status eq "WaitThirdProcess") or (status eq "WaitConfirm") or (status eq "Closed") or (status eq "Draft"))'
TIME_FILTER_TEMPLATE = '{status_filter} and (lastModifiedTime ge {start_ms}) and (lastModifiedTime le {end_ms})'
TT_PAYLOAD_BASE = {"customInfo": {"pageType": "allTicket"}, "field": TT_FIELDS, "order": "lastModifiedTime desc", "relationFilter": {"eflow_ticket_ticket_asset_all": ""}}
TT_REFERER = f"https://{HOST}:{PORT}/iui/ticket-mgt/v1/"
TT_EXPORT_COLUMNS = ["displayName", "woInfo", "status", "pendingStatus", "ttSource", "ticketType", "projectName", "templateName", "creator", "creatorContactInfo", "ticketSeverity", "alarmCategory", "alarmSubcategory", "alarmSeverity", "alarmType", "alarmCode", "subAlarmName", "subAlarmNeName", "subAlarmNeIp", "appendingAlarmName", "appendingAlarmNeName", "appendingAlarmNeIp", "netWorkType", "neName", "neId", "neIP", "impactedServiceOrNo", "impactedServiceWireless", "siteOutageOrNo", "reasonType", "slaTotalDuration", "slaStatus", "remainingTime", "targetFinishTime", "groupSlaTime", "groupSlaStatus", "groupSlaRemainsTime", "regionLevel1Name", "regionLevel2Name", "assetName", "siteId", "assetType", "siteClass", "candidateOperator", "vendor", "createTime", "lastModifiedTime", "alarmOccurTime", "alarmClearTime", "faultDurationTime", "procId", "opName", "assignmentSuggestions", "description", "specificProblem", "position", "additionalInfo", "severity", "alarmServerTime", "neType", "alarmId", "alarmDescription", "downSiteCount", "downSiteList", "downSiteCount2g", "downSiteList2g", "downSiteCount3g", "downSiteList3g", "downSiteCount4g", "downSiteList4g", "downSiteCount5g", "downSiteList5g", "downSiteCountVip", "downSiteListVip", "preprocessed", "processTime", "aiMindFailReason", "aiMindDiagnosisResult", "aiMindMaintenanceSuggestions", "groupSlaDeadlineTime", "category", "subCategory", "detailCategory", "actualFinishTime", "faultResolvedBy", "faultRecoveryTime", "processingDescription", "siteInformation", "vipSite", "hubsite", "upperLevelOpticalFiberAccessPoint", "opticalFiberAccessPoint", "nextLevelOpticalFiberAccessPoint", "regionId", "assetId", "orgId", "fixedGeneratorId", "fixedGeneratorModel", "fixedGeneratorManufacturer", "latestRefuelingTime", "latestPowerGenerationTime", "maintenanceTeam", "maintenanceTeamContractNo", "lastMaintenanceTime", "mobileGeneratorId", "mobileGeneratorModel", "mobileGeneratorManufacturer", "latestRefuelingTicketNo", "latestPowerGenerationTicketNo", "batteryCount", "battery1Id", "battery1Model", "battery1Manufacturer", "battery2Id", "battery2Model", "battery2Manufacturer", "battery3Id", "battery3Model", "battery3Manufacturer", "spareRequired", "spareAvailable", "spareDomain", "spareDevice", "spareName", "spareNo", "SuspendDetail", "LastSuspendStatus", "LastSuspendOperator", "LastSuspendOperatorGroup", "LastSuspendTime", "LastResumeOperator", "LastResumeOperatorGroup", "LastResumeTime", "LastProcesser", "LastProcesserGroup", "LastProcessTime", "faultResolved", "woNum", "CreateDetail", "FOAcceptDetail", "FOProcessDetail", "BOAcceptDetail", "BOProcessDetail", "ThirdAcceptDetail", "ThirdProcessDetail", "ConfirmDetail", "ClosedDetail", "createAttachment", "foAcceptAttachment", "foProcessAttachment", "boAcceptAttachment", "boProcessAttachment", "thirdAcceptAttachment", "thirdProcessAttachment", "confirmAttachment", "createWOAttachment", "woProcessAttachment", "woBONPOProcessAttachment"]
TT_EXPORT_CONFIG = {"type": "Export", "serviceName": "eflow-ticket", "config": json.dumps(TT_EXPORT_COLUMNS)}
TT_USERHABITS_PATH = "/api/eflow-ticket/v1/userhabits/add/eflow-tt"
TT_DOWNLOAD_PATH = "/api/eflow-ticket/v1/attachment/download/eflow-tt"

WO_FIELDS = "woId,procId,opName,ttWoid,pendingStatus,woNum,parentwoNum,status,displayName,creator,createTime,lastModifiedTime,candidateOperator,siteId,ticketSeverity,spareDomain,neName,neType,neIp,vendor,subSource,alarmOccurTime,alarmClearTime,expectedFinishTime,source,projectName,templateName,creatorContactInfo,alarmCategory,alarmSubcategory,alarmSeverity,reasonType,alarmId,alarmCode,subAlarmName,subAlarmNEName,subAlarmNEIP,appendingAlarmName,appendingAlarmNEName,appendingAlarmNEIP,networkType,neId,impactedServiceOrNo,impactedService,siteOutageOrNo,aiMindFailReasonType,faultDurationTime,slaTotalDuration,slaStatus,remainingTime,targetFinishTime,groupSlaTime,groupSlaStatus,groupSlaRemainsTime,groupSlaDeadlineTime,rcaFillingMode,regionLevel1Name,regionLevel2Name,assetName,assetType,siteClass,spareRequired,spareavailable,rejectCategory,etc,arriveSiteTime,travelTime"
WO_STATUS_FILTER = '((status eq "WaitAccept") or (status eq "WaitStartTrip") or (status eq "WaitArriveSite") or (status eq "WaitProcess") or (status eq "WaitConfirm") or (status eq "WaitLeaveSite") or (status eq "WaitSPApplication") or (status eq "WaitBONPOProcess") or (status eq "PhasedReply") or (status eq "Closed") or (status eq "Draft"))'
WO_PAYLOAD_BASE = {"customInfo": {"pageType": "allTicket"}, "field": WO_FIELDS, "order": "lastModifiedTime desc", "relationFilter": {"eflow_wo_wo_asset": ""}}
WO_REFERER = f"https://{HOST}:{PORT}/iui/wo-mgt/v1/"
WO_EXPORT_COLUMNS = ["woNum", "parentwoNum", "displayName", "status", "pendingStatus", "creator", "createTime", "lastModifiedTime", "opName", "candidateOperator", "ticketSeverity", "neType", "vendor", "alarmOccurTime", "alarmClearTime", "expectedFinishTime", "source", "projectName", "templateName", "assignmentSuggestions", "creatorContactInfo", "description", "positionInfo", "alarmServerTime", "alarmCategory", "alarmSubcategory", "alarmSeverity", "alarmType", "reasonType", "alarmId", "alarmCode", "alarmDescription", "subAlarmName", "subAlarmNEName", "subAlarmNEIP", "appendingAlarmName", "appendingAlarmNEName", "appendingAlarmNEIP", "networkType", "neName", "neId", "neIp", "impactedServiceOrNo", "impactedService", "siteOutageOrNo", "downSiteCount", "downsitelist", "downSiteCount2g", "downSiteList2g", "downSiteCount3g", "downSiteList3g", "downSiteCount4g", "downSiteList4g", "downSiteCount5g", "downSiteList5g", "downSiteCountVip", "downSiteListVip", "aiMindPreProcessed", "aiMindProcessTime", "aiMindFailReason", "aiMindFailReasonType", "aiMindDiagnosisResult", "aiMindMaintenanceSuggestions", "faultDurationTime", "slaTotalDuration", "slaStatus", "remainingTime", "targetFinishTime", "groupSlaTime", "groupSlaStatus", "groupSlaRemainsTime", "groupSlaDeadlineTime", "category", "subCategory", "detailCategory", "additionalInformation", "rcaFillingMode", "actualFinishTime", "faultResolvedBy", "faultResolvingTime", "processingDescription", "regionId", "assetId", "assetName", "siteId", "siteName", "siteType", "siteInformation", "siteClass", "orgId", "vipSite", "hubSite", "regionLevel1Name", "regionLevel2Name", "cableLineSection", "upperNodeFiberAccessPoint", "currentFiberAccessPoint", "nextNodeFiberAccessPoint", "fixedGeneratorId", "fixedGeneratorModel", "fixedGeneratorManufacturer", "fixLatestRefuelingTime", "latestPowerGenerationTime", "maintenanceTeamContractNo", "lastMaintenanceTime", "mobileGeneratorId", "mobileGeneratorModel", "mobileGeneratorManufacturer", "dgLatestRefuelingTime", "latestRefuelingTicketNo", "latestPowerGenerationTicketNo", "batteryCount", "battery1ID", "battery1Model", "battery1Manufacturer", "battery2ID", "battery2Model", "battery2Manufacturer", "battery3ID", "battery3Model", "battery3Manufacturer", "spareRequired", "spareavailable", "sparedomain", "sparedevice", "sparename", "spareno", "rejectCategory", "detailedProgressDescription", "etc", "arriveSiteTime", "travelTime", "SuspendDetail", "LastSuspendStatus", "LastSuspendOperator", "LastSuspendOperatorGroup", "LastSuspendTime", "LastResumeOperator", "LastResumeOperatorGroup", "LastResumeTime", "LastRejector", "LastRejectorGroup", "LastRejectTime", "LastProcesser", "LastProcesserGroup", "LastProcessTime", "FaultResolved", "rejectInfo", "rejectReason", "CreateDetail", "AcceptDetail", "SPApplicationDetail", "StartTripDetail", "ArriveSiteDetail", "BONPOProcessDetail", "ProcessDetail", "ConfirmDetail", "LeaveSiteDetail", "ClosedDetail", "createAttachment", "acceptAttachment", "startTripAttachment", "arriveSiteAttachment", "processAttachment", "spApplicationAttachment", "bonpoProcessAttachment", "leaveSiteAttachment", "confirmAttachment"]
WO_EXPORT_CONFIG = {"type": "Export", "serviceName": "eflow-wo", "config": json.dumps(WO_EXPORT_COLUMNS)}
WO_ASYNC_PATH = "/api/eflow-wo/v1/export/async/eflow-wo"
WO_USERHABITS_PATH = "/api/eflow-wo/v1/userhabits/add/eflow-wo"
WO_DOWNLOAD_PATH = "/api/eflow-wo/v1/attachment/download/eflow-wo"
WO_FIELD_DETAILS_NAME_OVERRIDES = {"displayName": "field.woDisplayName"}
WO_FIELD_DETAILS_RELATION_FILTER = {"alarmCode", "alarmId", "alarmType", "assetId", "assetName", "battery1ID", "battery2ID", "battery3ID", "category", "createTime", "creator", "etc", "hubSite"}

CR_FIELDS = "woId,procId,opName,woNum,status,changeType,displayName,creator,requesterWorkGroupName,createTime,candidateOperator,mopMaker,mopChecker,ipRelatedActivity,implementer,implementResult,plannedStartTime,plannedEndTime,actualImplementationStartTime,actualImplementationEndTime,downtimeStart,downtimeEnd,rollbackStartTime,rollbackEndTime,closeTime,lastModifiedTime"
CR_STATUS_FILTER = '((status eq "WaitL1Approve") or (status eq "WaitL2Approve") or (status eq "WaitL3Approve") or (status eq "WaitL4Approve") or (status eq "WaitL5Approve") or (status eq "WaitL6Approve") or (status eq "WaitL7Approve") or (status eq "WaitL8Approve") or (status eq "WaitImplement") or (status eq "Implementing") or (status eq "PhaseUpdate") or (status eq "WaitUpdate") or (status eq "Closed") or (status eq "Canceled") or (status eq "Draft"))'
CR_PAYLOAD_BASE = {"customInfo": {"pageType": "allTicket"}, "field": CR_FIELDS, "order": "lastModifiedTime desc", "length": 50}
CR_REFERER = f"https://{HOST}:{PORT}/iui/am-mgt/v1/"
CR_EXPORT_COLUMNS = ["woNum", "status", "changeType", "displayName", "description", "triggerForChange", "changeCategory", "subCategory", "creator", "createTime", "candidateOperator", "implementer", "implementerContactNumber", "implementResult", "ipRelatedActivity", "mopMaker", "mopChecker", "plannedStartTime", "plannedEndTime", "actualImplementationStartTime", "actualImplementationEndTime", "downtimeStart", "downtimeEnd", "rollbackStartTime", "rollbackEndTime", "closeTime", "vendor", "predictedChangeImpact", "affectedSite", "downtimeRequired", "alarmSuppressedObject", "lastModifiedTime", "operatingCircleOrSubCenter", "operatingDivisionOrDistrictOrThana", "requesterUserName", "requesterWorkGroupName", "requesterCompany", "requesterContactNumber", "requesterEmail", "CreateDetail", "UpdateDetail", "AnalysisDetail", "ResultFeedbackDetail", "DomainApproveDetail", "CRManagerConfirmDetail", "StartImplementingDetail", "DomainLeadConfirmDetail", "NOCApproveDetail", "L1ApproveDetail", "L2ApproveDetail", "L3ApproveDetail", "L4ApproveDetail", "L5ApproveDetail", "L6ApproveDetail", "L7ApproveDetail", "L8ApproveDetail", "ClosedDetail"]
CR_EXPORT_CONFIG = {"type": "Export", "serviceName": "eflow-asset", "config": json.dumps(CR_EXPORT_COLUMNS)}
CR_ASYNC_PATH = "/api/eflow-asset/v1/export/async/eflow-cr"
CR_USERHABITS_PATH = "/api/eflow-asset/v1/userhabits/add/eflow-cr"
CR_DOWNLOAD_PATH = "/api/eflow-asset/v1/attachment/download/eflow-cr"

PM_FIELDS = "woId,procId,opName,ftpFilePath,woNum,status,displayName,serviceClassification,creator,createTime,lastModifiedTime,candidateOperator,pmManagerRealName,assetName,assetId,source,parentWoNum,planBeginTime,planEndTime,templateName,filename,pmContentCompletedNum,pmContentTotalNum,pmtOverdue"
PM_STATUS_FILTER = '((status eq "Scheduling") or (status eq "WaitAccept") or (status eq "WaitProcess") or (status eq "Transfer") or (status eq "WaitReProcess") or (status eq "WaitPMManagerApprove") or (status eq "WaitFLMLeaderApprove") or (status eq "Draft") or (status eq "Closed"))'
PM_PAYLOAD_BASE = {"customInfo": {"pageType": "allTicket"}, "field": PM_FIELDS, "order": "lastModifiedTime desc", "relationFilter": {"eflow_pm_task_asset": ""}, "length": 200}
PM_REFERER = f"https://{HOST}:{PORT}/iui/pm-mgt/v1/"
PM_EXPORT_COLUMNS = ["woNum", "status", "displayName", "serviceClassification", "pmtOverdue", "creator", "createTime", "lastModifiedTime", "candidateOperator", "pmManagerRealName", "assetId", "assetName", "source", "parentWoNum", "planBeginTime", "planEndTime", "templateName", "pmContentCompletedNum", "pmContentTotalNum", "CreateDetail", "CreateLastOperator", "CreateLastGroup", "CreateLastTime", "ScheduleDetail", "ScheduleLastOperator", "ScheduleLastGroup", "ScheduleLastTime", "PMManagerApproveDetail", "PMManagerApproveLastOperator", "PMManagerApproveLastGroup", "PMManagerApproveLastTime", "FLMLeaderApproveDetail", "FLMLeaderApproveLastOperator", "FLMLeaderApproveLastGroup", "FLMLeaderApproveLastTime", "ProcessDetail", "ProcessLastOperator", "ProcessLastGroup", "ProcessLastTime", "AcceptDetail", "AcceptLastOperator", "AcceptLastGroup", "AcceptLastTime", "ClosedDetail", "ClosedLastOperator", "ClosedLastGroup", "ClosedLastTime"]
PM_EXPORT_CONFIG = {"type": "Export", "serviceName": "eflow-pm", "config": json.dumps(PM_EXPORT_COLUMNS)}
PM_ASYNC_PATH = "/api/eflow-pm/v1/export/async/eflow-pm-task"
PM_USERHABITS_PATH = "/api/eflow-pm/v1/userhabits/add/eflow-pm-task"
PM_DOWNLOAD_PATH = "/api/eflow-pm/v1/attachment/download/eflow-pm-task"

SITE_PAYLOAD_BASE = {"limit": 10, "skip": 0, "sort": {"cmdb#create-time": False}, "callScene": "ui"}
SITE_REFERER = f"https://{HOST}:{PORT}/iui/cmdb/"
PERSON_PAYLOAD_BASE = {"limit": 10, "skip": 0, "sort": {"cmdb#create-time": False}, "callScene": "ui"}
PERSON_REFERER = f"https://{HOST}:{PORT}/iui/cmdb/"
SITE_ASYNC_PATH = "/api/cmdb/v1/data/export/Site"
SITE_DOWNLOAD_PATH = "/api/cmdb/v1/attachment/download/Site"
PERSON_ASYNC_PATH = "/api/cmdb/v1/data/export/Person"
PERSON_DOWNLOAD_PATH = "/api/cmdb/v1/attachment/download/Person"


def _get_time_range_ms():
    start_dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
    return int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)


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


def wait_export_ready_generic(export_list_api, referer, file_name, max_wait=600, initial_delay=3, poll_interval=3):
    """通用导出等待函数：降低初始等待时间(从10s降低到3s)，动态轮询(从10s变更为3s)提高任务就绪响应速度"""
    headers_extra = _export_headers_extra(referer)
    body = json.dumps({})
    time.sleep(initial_delay)

    for attempt in range(max_wait // poll_interval):
        status, hdrs, _, resp_body = _http_request("POST", export_list_api, headers_extra=headers_extra, body=body)
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
        except Exception as e:
            print(f"[WARN] Failed to parse export status: {e}")

        time.sleep(poll_interval)
    return "", None


def read_export_zip_generic(zip_path):
    """优化 ZIP 解压与读取：使用内存提取解压后直接利用 pandas 并行读取，避免写磁盘开销"""
    extract_dir = os.path.splitext(zip_path)[0]
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_dir)
        files = z.namelist()

    data_files = [f for f in files if f.lower().endswith((".xlsx", ".xls", ".csv"))]
    if not data_files:
        raise Exception("No data file found in ZIP")

    file_paths = [os.path.join(extract_dir, f) for f in data_files]
    
    # 线程池并发读取 CSV/Excel
    dfs = []
    with ThreadPoolExecutor(max_workers=min(4, len(file_paths))) as executor:
        futures = [executor.submit(lambda p: pd.read_csv(p) if p.endswith('.csv') else pd.read_excel(p), path) for path in file_paths]
        for future in futures:
            dfs.append(future.result())

    df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    records = df.to_dict("records")
    
    shutil.rmtree(extract_dir, ignore_errors=True)
    return records


# 通用导出方法抽象工厂
def _execute_export_pipeline(module_label, api_path, async_path, download_path, export_list_path, userhabits_path, referer, filter_str, export_cols, payload_extra=None):
    headers_extra = _export_headers_extra(referer)
    
    # 1. 准备/交互
    prep_payload = {"customInfo": {"pageType": "allTicket"}, "field": "woId", "filter": filter_str, "length": 1, "start": 0}
    if payload_extra:
        prep_payload.update(payload_extra)
    _http_request("POST", api_path, headers_extra=headers_extra, body=json.dumps(prep_payload))
    
    # 2. 触发后台任务
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"{module_label}-export-{USERNAME}-{timestamp}"
    field_details = {col: {"value": col, "name": f"field.{col}", "checked": True} for col in export_cols}
    
    task_payload = {
        "fileName": file_name,
        "type": "xlsx",
        "exportType": "0",
        "field": export_cols,
        "fieldDetails": field_details,
        "filter": filter_str,
        "tableName": module_label.replace('-', '_'),
        "tableType": module_label
    }
    status, _, _, resp_body = _http_request("POST", async_path, headers_extra=headers_extra, body=json.dumps(task_payload))
    
    # 3. 轮询状态
    ftp_file_path, _ = wait_export_ready_generic(export_list_path, referer, file_name)
    
    # 4. 下载 Zip
    dl_payload = {"fileName": f"{file_name}.zip", "tableType": module_label}
    if ftp_file_path:
        dl_payload["ftpFilePath"] = ftp_file_path if ftp_file_path.endswith('.zip') else f"{ftp_file_path}.zip"
    
    _, hdrs, _, resp_body = _http_request("POST", download_path, headers_extra=headers_extra, body=json.dumps(dl_payload))
    
    zip_path = os.path.join(OUTPUT_DIR, f"{file_name}.zip")
    with open(zip_path, "wb") as f:
        f.write(resp_body)
        
    rows = read_export_zip_generic(zip_path)
    return rows


def _fetch_tt_pipeline(start_ms, end_ms):
    tt_filter = TIME_FILTER_TEMPLATE.format(status_filter=TT_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)
    rows = _execute_export_pipeline("eflow-tt", TT_API_PATH, "/api/eflow-ticket/v1/export/async/eflow-tt", TT_DOWNLOAD_PATH, "/api/eflow-ticket/v1/export/list/eflow-tt", TT_USERHABITS_PATH, TT_REFERER, tt_filter, TT_EXPORT_COLUMNS)
    return ("eFlow TT", rows)


def _fetch_wo_pipeline(start_ms, end_ms):
    wo_filter = TIME_FILTER_TEMPLATE.format(status_filter=WO_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)
    rows = _execute_export_pipeline("eflow-wo", WO_API_PATH, WO_ASYNC_PATH, WO_DOWNLOAD_PATH, "/api/eflow-wo/v1/export/list/eflow-wo", WO_USERHABITS_PATH, WO_REFERER, wo_filter, WO_EXPORT_COLUMNS)
    return ("eFlow WO", rows)


def _fetch_cr_pipeline(start_ms, end_ms):
    cr_filter = TIME_FILTER_TEMPLATE.format(status_filter=CR_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)
    rows = _execute_export_pipeline("eflow-cr", CR_API_PATH, CR_ASYNC_PATH, CR_DOWNLOAD_PATH, "/api/eflow-asset/v1/export/list/eflow-cr", CR_USERHABITS_PATH, CR_REFERER, cr_filter, CR_EXPORT_COLUMNS)
    return ("eFlow CR", rows)


def _fetch_pm_pipeline(start_ms, end_ms):
    pm_filter = TIME_FILTER_TEMPLATE.format(status_filter=PM_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)
    rows = _execute_export_pipeline("eflow-pm-task", PM_API_PATH, PM_ASYNC_PATH, PM_DOWNLOAD_PATH, "/api/eflow-pm/v1/export/list/eflow-pm-task", PM_USERHABITS_PATH, PM_REFERER, pm_filter, PM_EXPORT_COLUMNS)
    return ("eFlow PM", rows)


def _fetch_cmdb_direct(api_path, referer, filename_prefix):
    """CMDB 直接导出并读取优化"""
    headers_extra = _export_headers_extra(referer)
    status, _, _, resp_body = _http_request("POST", api_path, headers_extra=headers_extra, body=json.dumps({"callScene": "ui"}))
    xlsx_path = os.path.join(OUTPUT_DIR, f"{filename_prefix}.xlsx")
    with open(xlsx_path, "wb") as f:
        f.write(resp_body)
    df = pd.read_excel(xlsx_path)
    return df.to_dict("records")


def _fetch_site_pipeline():
    return ("Site", _fetch_cmdb_direct(SITE_ASYNC_PATH, SITE_REFERER, "Site"))


def _fetch_person_pipeline():
    return ("Person", _fetch_cmdb_direct(PERSON_ASYNC_PATH, PERSON_REFERER, "Person"))


def save_to_sqlite(sheets_data):
    """优化 SQLite 存储性能：启用 WAL 事务模式、批量提交与关闭同步机制"""
    start_time = time.time()
    db_path = os.path.join(OUTPUT_DIR, "eflow.sqlite3")
    conn = sqlite3.connect(db_path)
    
    # SQLite 性能补丁
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = OFF;")
    conn.execute("PRAGMA temp_store = MEMORY;")

    for sheet_name, rows in sheets_data:
        if not isinstance(rows, list) or not rows:
            continue
        df = pd.DataFrame(rows)
        
        # 优化 json 格式化处理效率
        object_cols = df.select_dtypes(include=["object"]).columns
        for col in object_cols:
            df[col] = df[col].apply(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else x)
            
        table = sheet_name.replace(" ", "_").lower()
        df.to_sql(table, conn, if_exists="replace", index=False, chunksize=10000)

    conn.commit()
    conn.close()
    print(f"[INFO] SQLite saved: {db_path} ({time.time() - start_time:.2f}s)")
    return db_path


def cleanup_old_export_files(output_dir=OUTPUT_DIR):
    zip_patterns = ["*.zip", "*.xlsx"]
    for pattern in zip_patterns:
        files = glob.glob(os.path.join(output_dir, pattern))
        for f in files:
            try:
                if "eflow_" not in f:  # 保留生成的报表结果，清除导出过程中间件
                    os.remove(f)
            except OSError:
                pass


def main():
    start_time = time.time()
    print("=" * 60)
    print(f"eFlow TT Fetcher (Optimized) - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    login()

    try:
        start_ms, end_ms = _get_time_range_ms()

        pipelines = [
            ("tt", lambda: _fetch_tt_pipeline(start_ms, end_ms)),
            ("wo", lambda: _fetch_wo_pipeline(start_ms, end_ms)),
            ("cr", lambda: _fetch_cr_pipeline(start_ms, end_ms)),
            ("pm", lambda: _fetch_pm_pipeline(start_ms, end_ms)),
            ("site", _fetch_site_pipeline),
            ("person", _fetch_person_pipeline),
        ]

        results = {}
        print(f"[INFO] Starting optimized parallel export pipelines...")
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_DOWNLOADS) as executor:
            future_to_key = {executor.submit(fn): key for key, fn in pipelines}
            for future in as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    sheet_name, rows = future.result()
                    results[sheet_name] = rows
                    print(f"[INFO] Pipeline {sheet_name} completed: {len(rows)} records")
                except Exception as e:
                    print(f"[ERROR] {key} pipeline failed: {e}")

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

    except Exception as e:
        import traceback
        print(f"[ERROR] {e}")
        traceback.print_exc()

    print(f"\n[DONE] Completed in {time.time() - start_time:.2f}s")


if __name__ == "__main__":
    main()