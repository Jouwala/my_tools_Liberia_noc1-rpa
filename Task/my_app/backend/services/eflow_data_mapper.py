"""eFlow 数据映射与报表服务（Phase 4 从 eflow_api_client.py 拆分）

负责工单/资产类数据（TT/WO/CR/PM/Site/Person）的抓取管线、SQLite 入库、
Excel 导出、FTP 上传与小时/日报报表生成：
- fetch_all_data：并行管线抓取全部工单数据
  · **大窗口（全量兜底）时 TT/WO 分段拉取**（`_fetch_pipeline_segmented`，
    2026-10-09 新增）：TT/WO 走异步导出管道，轮询窗口只有 120s，而 10 个月的大窗口
    导出要 8~22 分钟，必然超时 → 下载 500。分段（默认 30 天）后每段都能在窗口内完成。
- save_to_sqlite / write_excel_from_sqlite：入库与导出
- generate_excel_report / generate_hourly_report_with_images：报表生成
- upload_to_ftp / upload_tt_reports_to_ftp / generate_and_upload_fb_excel：分发
HTTP 基础、登录会话、重试仍由 eflow_api_client 提供（本模块单向依赖，无循环）。
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
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import ftplib
from backend.database import get_raw_connection
from backend.dialect_helpers import list_table_names


from backend.config.remote_host import get_ftp_host, get_ftp_port
from backend.services.eflow_api_client import (  # Phase 4 拆分：共享常量/基础函数
    APP_DB_PATH,
    CR_API_PATH,
    DATA_DIR,
    FTP_PASS,
    FTP_REMOTE_DIR,
    FTP_USER,
    HOST,
    MAX_PARALLEL_DOWNLOADS,
    PM_API_PATH,
    PORT,
    SEND_EMAIL_AFTER_REPORT,
    SITE_TX_SOURCE_COL,
    TT_API_PATH,
    TT_REPORT_SUBDIR,
    USERNAME,
    WO_API_PATH,
    _TT_COLUMN_RENAME,
    _close_thread_socket,
    _create_export_task,
    _download_export_zip,
    _get_time_range_ms,
    fetch_paginated_data,
    _headers_extra,
    _http_request,
    _prepare_export,
    _read_export_zip,
    _set_export_columns,
    _wait_export_ready,
    ensure_login,
    logger,
)


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


# ========== 实时单票查询（TT 快速分析回退用，纯内存不落库） ==========

# base/list 是「最近修改优先」的列表接口，不支持服务端 filter（实测传 filter 一律返回 0，
# 自定义 field 会 400/500）。因此只能分页拉取后客户端匹配。TT 单号在列表行的 woNum 字段
# （displayName 是标题而非单号）。命中行自带的时间/站点/告警/状态字段足以支撑分析报告，
# 缺 root_cause/downSiteCount/lastProcesser 等深层字段（base/list 不返回），由 _build_report
# 自动跳过，不影响结构。

# live camelCase 字段 → eflow_tt 列名（仅覆盖 base/list 实际返回的紧凑字段集）
_TT_LIVE_COL_MAP = {
    "woNum": "tt_no",
    "status": "status",
    "ticketSeverity": "ticket_severity",
    "alarmSeverity": "alarm_severity",
    "alarmType": "alarm_type",
    "alarmCode": "alarm_code",
    "subAlarmName": "sub_alarm_name",
    "reasonType": "alarm_reason_type",
    "siteOutageOrNo": "site_outage",
    "impactedServiceOrNo": "impacted_service",
    "assetName": "site_name",
    "siteId": "site_id",
    "assetType": "site_type",
    "regionLevel1Name": "region_level1",
    "regionLevel2Name": "region_level2",
    "alarmId": "alarm_id",
    "vendor": "vendor",
    "neName": "ne_name",
    "neId": "ne_id",
    # 时间戳列（ms → 可读串）
    "createTime": "created_time",
    "lastModifiedTime": "last_modified_time",
    "alarmOccurTime": "alarm_occur_time",
    "alarmClearTime": "alarm_clear_time",
    "faultDurationTime": "fault_duration_time",
}
_TT_MS_COLS = {"createTime", "lastModifiedTime", "alarmOccurTime",
               "alarmClearTime", "faultDurationTime"}
_TT_PAGE_LEN = 2000          # 单次 length；实测 2000 可用，~4s/3MB
_TT_MAX_SCAN = 4000          # 最多向前扫描行数（实时分析目标都是很新的单，前几页即命中）


def _dt_from_ms(v):
    """eFlow 时间戳 → '%Y-%m-%d %H:%M:%S'（与 eflow_tt 落库格式一致，parse_dt 可解析）。

    兼容两种时间戳：13 位及以上毫秒，或 10 位 epoch 秒（实测 base/list 里
    alarmOccurTime 走秒、createTime 走毫秒）。
    """
    if v is None:
        return None
    s = str(v).strip().rstrip("0").rstrip(".")
    digits = s.replace(".", "")
    if digits.isdigit() and len(digits) >= 10:
        try:
            ts = int(float(s))
            if len(digits) >= 13:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return None
    return s if s else None


def _normalize_tt_live_row(raw: dict) -> dict:
    """把 live base/list 返回的 camelCase 行 → eflow_tt 列名 dict（内存，供报告使用）。"""
    d: dict = {}
    for src, dst in _TT_LIVE_COL_MAP.items():
        if src not in raw or raw[src] is None:
            continue
        val = raw[src]
        if src in _TT_MS_COLS:
            conv = _dt_from_ms(val)
            if conv:
                d[dst] = conv
        else:
            d[dst] = val
    d["_tt_live_raw"] = raw
    return d


def _fetch_tt_page(start: int) -> list:
    """拉取一页 TT 列表（最近修改优先）。失败/非 200 返回 []。"""
    payload = dict(TT_PAYLOAD_BASE)
    payload["start"] = start
    payload["length"] = _TT_PAGE_LEN
    try:
        status, _hdrs, _rh, rsp = _http_request(
            "POST", TT_API_PATH, headers_extra=_headers_extra(TT_REFERER),
            body=json.dumps(payload))
    except Exception as e:  # noqa: BLE001
        logger.warning("tt-live 分页请求异常: %s", e)
        return []
    if "200" not in status:
        logger.warning("tt-live 分页非 200: %s", status)
        return []
    try:
        data = json.loads(rsp.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning("tt-live 分页 JSON 解析失败: %s", e)
        return []
    res = data.get("result")
    return res if isinstance(res, list) else []


def fetch_tt_live_batch(tt_nos) -> dict:
    """按单号批量实时拉取 TT：一次分页遍历匹配全部目标单（纯内存不落库）。

    为什么是批量而不是逐单调 `fetch_tt_live`：base/list 按最近修改倒序分页，
    单页 ~4s/3MB。P1 推送一轮要对多个在跟单做「是否自上次发送后仍未更新」判断，
    逐单查询会把同一批分页重复拉 N 遍；本函数把整轮查询压成**一次**遍历。

    返回 `{单号大写: 归一化行}`；扫完 `_TT_MAX_SCAN` 行仍未命中的单不在结果里，
    由调用方自行回退本地镜像（那里的 last_modified 对「一直没更新的停滞单」
    恰好是准确的 —— 它本来就没更新过）。
    """
    targets = {str(t or "").strip().upper() for t in (tt_nos or []) if str(t or "").strip()}
    if not targets:
        return {}
    ensure_login()

    found: dict = {}
    scanned = 0
    start = 0
    while scanned < _TT_MAX_SCAN and len(found) < len(targets):
        rows = _fetch_tt_page(start)
        if not rows:
            break
        for r in rows:
            num = str(r.get("woNum") or "").strip().upper()
            if num in targets and num not in found:
                found[num] = _normalize_tt_live_row(r)
        scanned += len(rows)
        if len(rows) < _TT_PAGE_LEN:
            break
        start += _TT_PAGE_LEN
    return found


def fetch_tt_live(tt_clean: str) -> dict | None:
    """按单号实时回 eFlow 拉取单条 TT（本地库 miss 时的兜底）。

    纯内存：不做任何写库。命中返回归一化后的 eflow_tt 列名 dict；未命中返回 None。
    多个单号一起查时请用 `fetch_tt_live_batch` —— 一次分页遍历匹配全部，
    逐单调用会把同一批分页重复拉 N 遍。
    """
    tt_clean = (tt_clean or "").strip().upper()
    if not tt_clean:
        return None
    return fetch_tt_live_batch([tt_clean]).get(tt_clean)


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
    with get_raw_connection(db_path) as conn:

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
            # TODO-PHASE3-SCHEMA: eflow 表写入独立库 eflow.sqlite3（非 app.db）。
            # 默认 sqlite 模式直接 to_sql（行为不变）；PG 模式需 engine_override 指向 schema=eflow。
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
    with get_raw_connection(db_path) as conn:

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
        logger.info(f"Connecting to FTP {get_ftp_host()}:{get_ftp_port()}...")
        ftp = ftplib.FTP()
        ftp.connect(get_ftp_host(), get_ftp_port(), timeout=30)
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
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] upload_to_ftp: exception swallowed", exc_info=True)
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
        logger.info(f"Connecting to FTP {get_ftp_host()}:{get_ftp_port()} for tt_reports upload...")
        ftp = ftplib.FTP()
        ftp.connect(get_ftp_host(), get_ftp_port(), timeout=30)
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
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] upload_tt_reports_to_ftp: exception swallowed", exc_info=True)
            pass
        return False
_FB_ALIASES = {
    "Eflow_TT_FB": {
        "Ticket No.": ["TT No.", "Ticket No."],
        "TT Source": ["Source"],
        "Domain": ["Network Type", "Domain"],
        "SLA Time": ["SLA Total Duration"],
        "SLA Remain Time": ["SLA Remaining Duration"],
        "SLA Deadline": ["SLA Expected Finish Time", "SLA Deadline"],
        "Site Name": ["Asset Name", "Site Name"],
        "Site Type": ["Asset Type", "Site Type"],
        "Proc ID": ["Process Instance ID", "Proc ID", "procid"],
        "procld": ["Process Instance ID", "Proc ID", "procid"],
        "procId": ["Process Instance ID", "Proc ID", "procid"],
        "Operation Step": ["Operation Step", "Operation Type"],
        "Server Time": ["Alarm Server Time"],
        "Group SLA Deadline": ["Group SLA Deadline Time"],
        "Processing Description": ["Process Description", "Processing Description"],
        "Spare Sub Domain": ["Spare Domain", "Spare Sub Domain"],
        "SpareName": ["Spare Name", "SpareName"],
        "Spare TTicket No": ["Spare No.", "Spare Ticket No", "Spare TTicket No"],
        "Spare Ticket No": ["Spare No.", "Spare Ticket No"],
        "NE Type": ["MOC"],
        "Vendor": ["Vender", "Vendor"],
        "Alarm Occur Time": ["Occurrence Time"],
        "Alarm Clear Time": ["Alarm Clearing Time"],
        "Template": ["Template Name"],
        "Alarm SubCategory": ["Alarm Sub Category"],
        "Impact/Down Site Count(Number of Down Site)": ["Down Site Count"],
        "Impact/Down Site Count (Number of Down Site)": ["Down Site Count"],
        "E2E SLA Status": ["Group SLA Status"],
        "E2E SLA Remains Time": ["Group SLA Remains Time"],
        "Expected Finish Time(E2E SLA Deadline Time)": ["Group SLA Deadline Time", "SLA Expected Finish Time"],
        "Expected Finish Time (E2E SLA Deadline Time)": ["Group SLA Deadline Time", "SLA Expected Finish Time"],
        "Latest Power Generation Time": ["Latest Power Generation Time"],
        "LatesPower Generation Time": ["Latest Power Generation Time"],
        "Update Time": ["Last Modified Time"],
    },
    "Eflow_WO_FB": {
        "procId": ["Process Instance ID", "Proc ID", "procid"],
        "Title": ["Work Order Title"],
        "NE Type": ["MOC"],
        "Vendor": ["Vender", "Vendor"],
        "Alarm Occur Time": ["Occurrence Time"],
        "Alarm Clear Time": ["Alarm Clearing Time"],
        "Template": ["Template Name"],
        "Alarm SubCategory": ["Alarm Sub Category"],
        "Alarm Reason Type": ["Reason Type"],
        "Alarm Code": ["Alarm Code", "Alarm ID"],
        "Impact/Down Site Count(Number of Down Site)": ["Impact/Down Site Count"],
        "Impact/Down Site Count (Number of Down Site)": ["Impact/Down Site Count"],
        "E2E SLA Status": ["Group SLA Status"],
        "E2E SLA Remains Time": ["Group SLA Remains Time"],
        "Expected Finish Time(E2E SLA Deadline Time)": ["Group SLA Deadline Time", "Expected Finish Time"],
        "Expected Finish Time (E2E SLA Deadline Time)": ["Group SLA Deadline Time", "Expected Finish Time"],
        "Site Information": ["Site Information", "Site Informtion"],
        "Region Level1": [],
        "Region Level2": [],
        "Latest Power Generation Time": [],
        "LatesPower Generation Time": [],
        "Update Time": ["Last Modified Time"],
    },
}


def _rename_fb_columns(df, table_name: str):
    """把远端 FB 表列名统一成查看器/报表期望的规范名（与远端已重命名的列一致）。

    远端 Eflow_WO_FB / Eflow_TT_FB 已通过 ALTER TABLE RENAME 改成这些列名，
    客户端写入前也做同样重命名，保证删表重建后列名不会回到旧拼写。
    """
    mapping = {
        "Eflow_TT_FB": {
            "Region ID": "Region Id",
            "Organization Id": "Organization ID",
        },
        "Eflow_WO_FB": {
            "TT NO.": "TT No.",
            "Region ID": "Region Id",
            "Organization Id": "Organization ID",
        },
    }.get(table_name, {})
    if not mapping or df is None:
        return df
    rename_map = {k: v for k, v in mapping.items() if k in df.columns}
    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def _apply_fb_aliases(df, table_name: str):
    """给远端 FB 表数据补充兼容列名（值取自原始列，取不到则留空）。"""
    aliases = _FB_ALIASES.get(table_name, {})
    if not aliases or df is None:
        return df
    df = df.copy()
    for alias, sources in aliases.items():
        if alias in df.columns:
            continue
        src = next((s for s in sources if s in df.columns), None)
        df[alias] = df[src] if src is not None else None
    return df


# 远端 FB 表里被视为「空日期」的字面量（见 _normalize_fb_nulls 的说明）。
# ⚠ 刻意**只收 NaT 系**，不收 'nan'/''/'None'：那几种字面量在 FB 表里是**既有事实**
# （"WO No." 有 22226 行是字符串 'nan'、"Current Handler" 27351 行 …），
# 全应用（含 FineBI 数据集口径与 my_app 的宽表 ETL）都按「非空字符串」容忍它们。
# 把它们一起改成 NULL 是一次影响面极大的语义变更，收益却只是"看着干净"，
# 不属于本次故障范围。见下方 docstring。
_FB_NULLISH = {"NaT", "NAT"}


def _normalize_fb_nulls(df, table_name: str):
    """写入远端前把**空日期**统一成 NULL（而不是字面量 'NaT'）。

    为什么必须有这一步（2026-09-21 事故）：
        pandas 的 datetime64 列在 `.values.tolist()` 时把 NaT 原样交出来，而
        DbWriterClient 用 `json.dumps(default=str)` 序列化 → `str(pd.NaT) == 'NaT'`，
        于是 eFlow 导出里的**空日期**落到远端就成了**字符串 'NaT'**。
        （float 列的 NaN 则被 json 写成裸 NaN，SQLite 侧本来就落成 NULL，不是问题。）

    实测污染面（远端 db.sqlite3，2026-09-21）：
        Eflow_TT_FB."Alarm Occur Time" = 'NaT' →   3 行（别名列 "Occurrence Time" 同）
        Eflow_TT_FB."Alarm Clear Time" = 'NaT' →  95 行（别名列 "Alarm Clearing Time" 同）
        Eflow_WO_FB."Alarm Occur Time" = 'NaT' →   1 行 / "Alarm Clear Time" → 180 行
    危害不是"看着脏"（这正是本次故障的次生缺陷）：
        1. 文本排序下 'NaT' > '2026-09-21 …'，`ORDER BY "Alarm Occur Time" DESC`
           把脏行排到**最前面** → 看板 TT 明细顶部出现空白行；
        2. `MAX("Alarm Occur Time")` 直接返回 'NaT' → 任何"最新时间"判定都算错；
        3. `julianday('NaT')` → NULL → MTTR / 时长类指标静默变空。

    实现（刻意做窄）：
        - datetime64 列：`str(Timestamp)`（与 json default=str 产物一致，含微秒也一致），
          NaT → None；
        - 数值列：有 NaN 时逐格置 None（顺手让 payload 里不再出现裸 NaN —— 那是
          非法 JSON，严格的解析器会直接 400）；
        - 其它列：只把 'NaT' 字面量置 None，**不动 'nan'/''/'None'**（理由见 _FB_NULLISH）。
        int/bool 列不动。
    """
    if df is None or len(df.columns) == 0:
        return df

    def _nn(v):
        if v is None:
            return None
        if isinstance(v, float) and v != v:          # NaN（含 numpy.float64）
            return None
        try:
            if pd.isna(v):                            # NaT / None / np.nan
                return None
        except (TypeError, ValueError):
            pass                                      # 数组类值：isna 会抛，跳过
        if isinstance(v, str) and v.strip() in _FB_NULLISH:
            return None
        return v

    df = df.copy()
    converted = []
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_datetime64_any_dtype(s):
            df[col] = pd.Series([None if pd.isna(v) else str(v) for v in s],
                                index=s.index, dtype=object)
            if s.isna().any():
                converted.append(str(col))
        elif pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            if s.isna().any():          # 只在此列真有 NaN 时重建（否则保持原 dtype）
                df[col] = pd.Series([None if pd.isna(v) else v for v in s],
                                    index=s.index, dtype=object)
                converted.append(str(col))
        else:
            if not any(isinstance(v, str) and v.strip() in _FB_NULLISH for v in s):
                continue                # 绝大多数文本列不含 NaT，直接跳过（省一次全列 map）
            # ⚠ 必须显式构造 object dtype：pandas 3.x 的 str dtype 会把 None 又变回 NaN
            df[col] = pd.Series([_nn(v) for v in s], index=s.index, dtype=object)
            converted.append(str(col))
    if converted:
        logger.info(f"[FB] {table_name}: 空日期归一为 NULL 的列 {len(converted)} 个: "
                    f"{converted[:12]}{' ...' if len(converted) > 12 else ''}")
    return df


def _fill_wo_from_tt(df_wo, df_tt, columns: list):
    """WO 表的空列按 WO No. 关联 TT 表回填（取每个 WO 首个非空值）。"""
    if df_wo is None or df_tt is None or df_wo.empty or df_tt.empty:
        return df_wo
    key = "WO No."
    if key not in df_wo.columns or key not in df_tt.columns:
        return df_wo
    tt = df_tt[[key] + [c for c in columns if c in df_tt.columns]].dropna(subset=[key])
    if tt.empty:
        return df_wo
    df_wo = df_wo.copy()
    for col in columns:
        if col not in tt.columns:
            continue
        sub = tt[[key, col]].dropna(subset=[col])
        if sub.empty:
            continue
        first = sub.drop_duplicates(subset=[key], keep="first")
        mapping = dict(zip(first[key].astype(str), first[col]))
        df_wo[col] = df_wo[key].astype(str).map(mapping)
    return df_wo


def generate_and_upload_fb_excel(all_data: dict) -> dict:
    """
    从 eFlow 同步数据，通过 DbWriterClient API 增量写入远程 DB Main (db.sqlite3)。
    使用 upsert（INSERT OR REPLACE）按工单号（WO No.）更新，保留远程历史数据。

    Args:
        all_data: fetch_all_data() 返回的 {sheet_name: rows} 字典

    Returns:
        dict: {"upload_success": bool}
    """
    import pandas as pd

    t0 = time.time()
    result = {"upload_success": False}

    tt_rows = all_data.get("eFlow TT") or []
    wo_rows = all_data.get("eFlow WO") or []
    df_tt = pd.DataFrame(tt_rows) if tt_rows else None
    df_wo = pd.DataFrame(wo_rows) if wo_rows else None

    if df_tt is None and df_wo is None:
        logger.warning("无 eFlow TT/WO 数据，跳过 API 写入")
        return result

    # 通过 API 写入远程 DB Main (db.sqlite3)
    written = 0
    total_tables = 0
    try:
        try:
            from backend.services.db_writer_client import DbWriterClient
        except ImportError:
            logging.getLogger(__name__).warning("[SILENT-EXCEPT] generate_and_upload_fb_excel: exception swallowed", exc_info=True)
            from services.db_writer_client import DbWriterClient
        client = DbWriterClient()
        client.health()

        if df_tt is not None:
            df_tt = _rename_fb_columns(df_tt, "Eflow_TT_FB")
            df_tt = _apply_fb_aliases(df_tt, "Eflow_TT_FB")
        if df_wo is not None:
            df_wo = _rename_fb_columns(df_wo, "Eflow_WO_FB")
            df_wo = _apply_fb_aliases(df_wo, "Eflow_WO_FB")
            # WO 的 Region Level / 发电时间在 WO 导出中不存在，用 TT 数据按 WO No. 回填
            df_wo = _fill_wo_from_tt(
                df_wo, df_tt,
                ["Region Level1", "Region Level2",
                 "Latest Power Generation Time", "LatesPower Generation Time"],
            )

        # 空值归一（NaN / NaT / 'nan' / 'NaT' / '' → NULL）必须放在**所有列变换之后、
        # 写库之前**：`_fill_wo_from_tt` 也会引入 NaN。详见 _normalize_fb_nulls 的说明。
        df_tt = _normalize_fb_nulls(df_tt, "Eflow_TT_FB")
        df_wo = _normalize_fb_nulls(df_wo, "Eflow_WO_FB")

        for df, table_name, pk_cols in [
            (df_tt, "Eflow_TT_FB", ["TT No."]),
            (df_wo, "Eflow_WO_FB", ["WO No."]),
        ]:
            if df is None:
                continue
            total_tables += 1
            columns = list(df.columns)
            rows = df.values.tolist()
            logger.info(f"[FB] {table_name}: {len(columns)} columns sent (含兼容列), rows={len(rows)}")
            write_result = client.write_data(
                db="db.sqlite3",
                table=table_name,
                columns=columns,
                rows=rows,
                mode="upsert",
                pk_columns=pk_cols,
            )
            if write_result.get("success"):
                written += 1
                logger.info(f"API 写入成功: {table_name} -> db.sqlite3 ({write_result.get('rows_written', 0)} 行)")
            else:
                logger.warning(f"API 写入返回失败: {table_name} -> {write_result}")

        result["upload_success"] = written == total_tables and total_tables > 0
        logger.info(f"FB Excel API 写入完成: {written}/{total_tables}, 用时 {time.time() - t0:.2f}s")
    except (ConnectionError, Exception) as e:
        logger.error(f"FB Excel API 写入失败: {e}")

    return result
def _find_col_fuzzy(df, keyword):
    """在 DataFrame 列中模糊查找包含 keyword（不区分大小写）的列名，返回第一个匹配或 None。"""
    kw = keyword.lower()
    for col in df.columns:
        if kw in str(col).lower():
            return col
    return None


def _build_site_attr_map(sheets_data, processor_cls):
    """构建 TRM Type / FME / Supervisor / Site Category 的映射。

    - TRM Type: 从 eFlow Site 数据获取
    - FME / Supervisor / Site Category: 从 master_site_db 表的
      fme_name / supervisor / site_caregory 列获取

    返回 dict:
        {
            "trm_type": (id_map, name_map),
            "fme": (id_map, name_map),
            "supervisor": (id_map, name_map),
            "site_category": (id_map, name_map),
        }
    每个 id_map: normalize_id(Site ID) -> value
    每个 name_map: strip(Site Name) -> value
    """
    import pandas as pd

    empty_result = {
        "trm_type": ({}, {}),
        "fme": ({}, {}),
        "supervisor": ({}, {}),
        "site_category": ({}, {}),
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

    # --- FME / Supervisor / Site Category: 从 master_site_db 读取 ---
    fme_result = ({}, {})
    sup_result = ({}, {})
    category_result = ({}, {})
    try:
        if os.path.exists(APP_DB_PATH):
            with get_raw_connection(APP_DB_PATH) as conn:
                df_master = pd.read_sql_query(
                    'SELECT site_id, site_name, fme_name, supervisor, site_caregory FROM master_site_db', conn)
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

                # Site Category 映射（列名 site_caregory 为 master_site_db 原始拼写）
                cat_id, cat_name_map = {}, {}
                for _, r in df_master.iterrows():
                    val = str(r.get("site_caregory", "")).strip() if pd.notna(r.get("site_caregory")) else ""
                    sid = processor_cls.normalize_id(r.get("site_id"))
                    sname = str(r.get("site_name", "")).strip()
                    if sid:
                        cat_id[sid] = val
                    if sname:
                        cat_name_map[sname] = val
                category_result = (cat_id, cat_name_map)
                logger.info(f"site_category 映射(master_site_db): {len(cat_id)} by ID, {len(cat_name_map)} by Name")
        else:
            logger.warning(f"master_site_db 不可用: {APP_DB_PATH} 不存在")
    except Exception as e:
        logger.warning(f"从 master_site_db 读取 FME/Supervisor/Site Category 失败: {e}")

    return {
        "trm_type": trm_result,
        "fme": fme_result,
        "supervisor": sup_result,
        "site_category": category_result,
    }
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


def load_report_data_from_db() -> dict:
    """从 app.db 累计表读取完整工单/站点数据，重建报告生成所需的原始列名结构。

    抓取改为 delta 增量后，当次快照只含最近修改的工单，而小时/8小时/Summary 报告
    依赖完整的 open 工单集合，因此从本地累计库（增量写入）读取原始列名数据。

    Returns:
        {"eFlow TT": [row_dict...], "Site": [row_dict...]} 与 fetch_all_data 的键一致
    """
    from backend.services.sync_from_eflow_api import SITE_COLUMN_MAP, TT_COLUMN_MAP

    out: dict = {}
    with get_raw_connection(APP_DB_PATH) as conn:
        if isinstance(conn, sqlite3.Connection):
            conn.row_factory = sqlite3.Row
        try:
            tables = set(list_table_names(conn))

            if "eflow_tt" in tables:
                inv = {}
                for raw, mapped in TT_COLUMN_MAP.items():
                    inv.setdefault(mapped, raw)
                cur = conn.execute("SELECT * FROM eflow_tt")
                cols = [d[0] for d in cur.description]
                tt_rows = []
                for r in cur.fetchall():
                    row = dict(zip(cols, r))
                    tt_rows.append({inv.get(k, k): v for k, v in row.items()})
                out["eFlow TT"] = tt_rows
                logger.info(f"[REPORT-DB] eflow_tt loaded: {len(tt_rows)} rows")

            if "eflow_site" in tables:
                inv = {}
                for raw, mapped in SITE_COLUMN_MAP.items():
                    inv.setdefault(mapped, raw)
                cur = conn.execute("SELECT * FROM eflow_site")
                cols = [d[0] for d in cur.description]
                site_rows = []
                for r in cur.fetchall():
                    row = dict(zip(cols, r))
                    site_rows.append({inv.get(k, k): v for k, v in row.items()})
                out["Site"] = site_rows
                logger.info(f"[REPORT-DB] eflow_site loaded: {len(site_rows)} rows")
        finally:
            conn.close()
        return out
def _cleanup_old_tt_reports(output_dir):
    """tt_reports 目录同类型文件只保留最新一份（含图片降级产生的带序号 PNG）."""
    pats = [
        "Liberia Orange Site Down hourly Report_*.xlsx",
        "Liberia Orange Site Down 8 hours Report_*.xlsx",
        "Liberia Orange TT Summary Report_*.xlsx",
        "Liberia Orange Site Down 8 hours Report_*.png",
        "Summary_*.png",
        "Open Tickets_*.png",
        "Prolong Tickets_*.png",
    ]
    for pat in pats:
        matched = sorted(glob.glob(os.path.join(output_dir, pat)), key=os.path.getmtime, reverse=True)
        for old_f in matched[1:]:
            try:
                os.remove(old_f)
                logger.info(f"[CLEAN] {os.path.basename(old_f)}")
            except OSError:
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] _cleanup_old_tt_reports: exception swallowed", exc_info=True)
                pass

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

    # 2.1 修复 Ticket No.：eFlow 导出的 "TT No" 列包含真正的 TT 编号，
    #     而 "Ticket No." 列实际包含的是 WO 编号。
    #     原始列名 "TT No" 经 _clean_column_name 等价于 tt_no。
    _tt_raw_col = next((c for c in df_source.columns
                        if re.sub(r'[\.\s]+', '_', c.strip()).strip('_').lower() == 'tt_no'), None)
    if _tt_raw_col:
        df_source["Ticket No."] = df_source[_tt_raw_col]
        logger.info(f"Ticket No. 已从原始列 '{_tt_raw_col}' 回填（真正的 TT 编号）")
    else:
        logger.warning("未找到包含 TT 编号的列，Ticket No. 将保持原值")

    # 2.5 从 Site 数据添加 TRM Type / FME / Supervisor / Site Category 列
    attr_maps = _build_site_attr_map(sheets_data, ExcelDataProcessor)
    if "Site ID" in df_source.columns:
        df_source["Site ID"] = df_source["Site ID"].apply(ExcelDataProcessor.normalize_id)

    _attr_col_names = {
        "trm_type": "TRM Type",
        "fme": "FME",
        "supervisor": "Supervisor",
        "site_category": "Site Category",
    }
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

        # 9. 图片（失败不阻断整体：Excel 报告已生成，仅记录错误）
        step_start = time.time()
        logger.info("步骤6: 生成图片（matplotlib）...")
        try:
            image_paths = ExcelDataProcessor.generate_summary_images(
                summary_df, open_tickets, prolong_tickets, output_dir)
            result["image_paths"] = image_paths
        except Exception as e:
            logger.error(f"图片生成失败（不影响报告文件）: {e}")
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


    # cleanup old tt_reports
    _cleanup_old_tt_reports(output_dir)

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
def _run_pipeline_with_connection_cleanup(pipeline):
    """Prevent worker-local keep-alive sockets from leaking between sync runs."""
    try:
        return pipeline()
    finally:
        _close_thread_socket()


# ==============================================================================
# 全窗口分段拉取（2026-10-09 新增，修 eflow_sync_full 的全量失败）
# ==============================================================================
# 为什么需要分段：TT/WO 走的是**异步导出管道**（_prepare_export → 建导出任务 →
# 轮询 → 下载 zip，见 _fetch_tt_pipeline:246），而轮询窗口只有
# EXPORT_POLL_MAX_WAIT=120s（eflow_api_client.py:67-68）。代码自己的注释说全量导出
# 要「8~22 分钟」（eflow_api_client.py:431）—— 于是「lastModifiedTime >= 2026-01-01」
# 这种 10 个月的大窗口必然轮询超时 → 下载返回 HTTP 500 → 该管线失败。
# 实测证据：eflow_sync_full 在 2026-10-05 ~ 10-08 **每天**都 TT/WO 失败
# （log/worker_runtime_n_*.log），eflow_tt 里早期工单的 _sync_time 一直停在回填日。
#
# 改法：把大窗口切成若干小段（默认 30 天），逐段导出再合并 —— 每段都能在轮询窗口内
# 完成。仅当窗口**跨度大**时才分段；小时级 delta（3 天）保持单段，行为不变。
#
# ⚠ 环境变量 EFLOW_FULL_SEGMENT_DAYS 可调段长；调小 = 段数变多、更稳但更慢。
#   段长不要低于 ~7 天（否则请求数暴涨），也不要大到超过轮询能完成的量。
_FULL_SEGMENT_DAYS_DEFAULT = 30
#: 窗口跨度超过这个天数才启用分段（低于它的大概率单段能跑完，不必多此一举）
_SEGMENT_THRESHOLD_DAYS_DEFAULT = 60


def _segment_days():
    try:
        return max(1, int(os.environ.get("EFLOW_FULL_SEGMENT_DAYS")
                          or _FULL_SEGMENT_DAYS_DEFAULT))
    except (TypeError, ValueError):
        return _FULL_SEGMENT_DAYS_DEFAULT


def _segment_threshold_days():
    try:
        return max(1, int(os.environ.get("EFLOW_SEGMENT_THRESHOLD_DAYS")
                          or _SEGMENT_THRESHOLD_DAYS_DEFAULT))
    except (TypeError, ValueError):
        return _SEGMENT_THRESHOLD_DAYS_DEFAULT


def _segment_ranges(start_ms: int, end_ms: int, segment_days: int) -> list:
    """把毫秒区间 [start_ms, end_ms] 切成**连续、不重叠、完整覆盖**的小段。

    返回 [(seg_start_ms, seg_end_ms), ...]，末段封顶到 end_ms。
    起点 >= 终点时返回单段 [(start_ms, end_ms)]（空窗口不切）。
    """
    if segment_days <= 0 or end_ms <= start_ms:
        return [(start_ms, end_ms)]
    step = int(timedelta(days=segment_days).total_seconds() * 1000)
    ranges = []
    cur = start_ms
    while cur < end_ms:
        nxt = min(cur + step, end_ms)
        ranges.append((cur, nxt))
        cur = nxt
    return ranges or [(start_ms, end_ms)]


def _dedup_rows(rows: list, key_candidates: tuple) -> list:
    """按主键去重（保留首现），供分段合并用；找不到主键列则原样返回。

    与 _upsert_df 的「同主键保留一行」口径一致，避免分段边界重叠导致行数虚增。
    """
    if not rows:
        return rows
    first = rows[0]
    if not isinstance(first, dict):
        return rows
    key = next((k for k in key_candidates if k in first), None)
    if key is None:
        return rows
    seen, out = set(), []
    for r in rows:
        v = r.get(key) if isinstance(r, dict) else None
        if v is None:
            out.append(r)
            continue
        v = str(v)
        if v in seen:
            continue
        seen.add(v)
        out.append(r)
    return out


def _fetch_pipeline_segmented(pipeline_fn, start_ms, end_ms, tmp_dir,
                              key_candidates=("TT No.", "WO No.", "TT NO.")):
    """逐段调用 pipeline_fn(seg_start, seg_end, tmp_dir)，合并各段 rows。

    返回 (sheet_name, merged_rows)。**任何一段失败都会向上抛**（不吞）——
    交给 fetch_all_data 的既有 except 记录，再由 sync_from_eflow_api 判定必需表缺失。
    段间 sleep 3s，降低对上游导出端点的瞬时压力。

    key_candidates 用**导出的原始列名**（本函数拿到的还是未做列映射的导出行，
    映射发生在下游 _sync_tt/_sync_wo）：TT/WO 的唯一键都是 "TT No." / "WO No."。
    """
    ranges = _segment_ranges(start_ms, end_ms, _segment_days())
    logger.info(f"Segmented fetch: {len(ranges)} segments x <= {_segment_days()}d")

    sheet_name = None
    merged = []
    for i, (s, e) in enumerate(ranges, 1):
        logger.info(f"  segment {i}/{len(ranges)}: {s} ~ {e}")
        name, rows = pipeline_fn(s, e, tmp_dir)
        sheet_name = name
        merged.extend(rows or [])
        if i < len(ranges):
            time.sleep(3)   # 段间节流，避免连续导出打爆上游

    merged = _dedup_rows(merged, key_candidates)
    logger.info(f"Segmented fetch done: {len(merged)} rows (deduped)")
    return sheet_name, merged


def fetch_all_data(tmp_dir: str = None, days_back: int | None = None) -> dict:
    """
    从 eFlow API 获取所有数据，返回 {sheet_name: records_list} 字典

    Args:
        tmp_dir: 临时文件目录，不传则自动创建
    """
    start_time = time.time()

    # 确保已登录
    ensure_login()

    # 创建临时目录
    auto_tmp = False
    if tmp_dir is None:
        import tempfile
        tmp_dir = tempfile.mkdtemp(prefix="eflow_")
        auto_tmp = True

    try:
        start_ms, end_ms = _get_time_range_ms(days_back)
        logger.info(f"Time range: {start_ms} to {end_ms}")

        # 大窗口（全量兜底）→ TT/WO 分段拉取；小窗口（小时级 delta）→ 单段原样。
        # 见 _segment_ranges 上方的说明：大窗口单次导出超过 120s 轮询窗口必然 500。
        span_days = max(0.0, (end_ms - start_ms) / 86400000.0)
        segmented = span_days > _segment_threshold_days()
        if segmented:
            logger.info(
                f"Window spans {span_days:.1f}d > {_segment_threshold_days()}d "
                f"→ TT/WO 分段拉取（段长 {_segment_days()}d）"
            )

        def _tt():
            if segmented:
                return _fetch_pipeline_segmented(_fetch_tt_pipeline, start_ms, end_ms, tmp_dir)
            return _fetch_tt_pipeline(start_ms, end_ms, tmp_dir)

        def _wo():
            if segmented:
                return _fetch_pipeline_segmented(_fetch_wo_pipeline, start_ms, end_ms, tmp_dir)
            return _fetch_wo_pipeline(start_ms, end_ms, tmp_dir)

        # 仅包含工单/资产类数据；告警由独立任务 eflow_active_alarm / eflow_history_alarm 负责
        pipelines = [
            ("tt", _tt),
            ("wo", _wo),
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
                logging.getLogger(__name__).warning("[SILENT-EXCEPT] fetch_all_data: exception swallowed", exc_info=True)
                pass
