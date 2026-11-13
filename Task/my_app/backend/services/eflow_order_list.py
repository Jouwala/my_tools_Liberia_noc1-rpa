# -*- coding: utf-8 -*-
"""TT/WO 列表直查。异步导出登记不上时的退路。

2026-11-13 02:40 和 03:06 两轮 eflow_sync：创建导出回 HTTP 200 且正文为空
（这是成功时的常态），但文件从未出现在导出列表里。TT/WO 列表都停在正好
255 条，最新一条仍是 00:06 那次成功导出；PM 只有 177 条，同期导出正常。
用 00:06 那条的过滤条件和字段再创建一次，同样不入库。前端没有删除导出记录
的接口（queryDay 对 eflow-tt 返回 7，即最多保留 7 天）。

base/list 在同一过滤条件下可用（当时 TT 305、WO 262）。行被改成导出 Excel
的表头，下游 `_sync_tt` / `_sync_wo` 不用改。状态代码翻成库里已有的显示名
（对照过已入库单），时长字段写成 `0d16h0m` 这种导出格式，绝对时间用 UTC。
明细长文本（*Detail）列表接口不返回，upsert 不会覆盖这些列。
"""
from __future__ import annotations

import json
import logging

from backend.services.eflow_api_client import _headers_extra, _http_request
from backend.services.eflow_data_mapper import (
    TIME_FILTER_TEMPLATE,
    TT_API_PATH,
    TT_FIELDS,
    TT_REFERER,
    TT_STATUS_FILTER,
    WO_API_PATH,
    WO_FIELDS,
    WO_REFERER,
    WO_STATUS_FILTER,
    _cr_ms_to_text,
)

logger = logging.getLogger("eflow_api")

_PAGE_SIZE = 200

# 已与库内显示名逐条对过的代码（2026-11-13，命中行的 API status × eflow_tt/eflow_wo.status）。
# 未在当次窗口里出现、但库里有对应显示名的，按同一命名补上，并在注释里标明。
TT_STATUS_DISPLAY = {
    "closed": "Closed",
    "draft": "Draft",
    "waitfoaccept": "Waiting for FO Accept",
    "waitfoprocess": "Waiting for FO Process",
    "waitboaccept": "Waiting for BO Accept",          # 库内有显示名，当次窗口未出现
    "waitboprocess": "Waiting for BO Process",
    "waitthirdaccept": "Waiting for Third Accept",
    "waitthirdprocess": "Waiting for Third Process",  # 与 WaitFOProcess 同一命名
    "waitconfirm": "Wait For Confirm",                # 库内 TT 就是这个写法
}
WO_STATUS_DISPLAY = {
    "closed": "Closed",
    "draft": "Draft",
    "waitaccept": "Waiting for Accept",
    "waitstarttrip": "Waiting for Departure",
    "waitarrivesite": "Waiting for Arrive Site",      # 库内有显示名，当次窗口未出现
    "waitprocess": "Waiting for Process",
    "waitconfirm": "Wait For Confirm",
    "waitleavesite": "Waiting for Leave Site",        # 库内有显示名，当次窗口未出现
    "waitbonpoprocess": "Waiting for BONPO Process",  # 同上
    "phasedreply": "Phased Reply",                    # 同上
    "waitspapplication": "Waiting for SP Application",
}

_PENDING_PLAIN = {"", "activate", "active", "none", "null"}
_UNMAPPED_STATUS = set()
_UNMAPPED_PENDING = set()

# 绝对时间（毫秒）→ 'YYYY-MM-DD HH:MM:SS'。时长字段不要放这里。
_TT_TIME_FIELDS = {"createTime", "lastModifiedTime", "alarmOccurTime", "alarmClearTime", "targetFinishTime"}
_WO_TIME_FIELDS = {"createTime", "lastModifiedTime", "alarmOccurTime", "alarmClearTime", "expectedFinishTime"}
# 毫秒时长 → 导出用的 0d16h0m。57600000 → 0d16h0m 已对过 slaTotalDuration。
_DURATION_FIELDS = {"slaTotalDuration", "remainingTime", "faultDurationTime", "groupSlaRemainsTime", "groupSlaTime"}

TT_LIST_HEADERS = {
    "woNum": "TT No.",
    "displayName": "Title",
    "ttSource": "Source",
    "ticketType": "Ticket Type",
    "projectName": "Project Name",
    "templateName": "Template Name",
    "creator": "Creator",
    "creatorContactInfo": "Creator Contact Info",
    "ticketSeverity": "Ticket Severity",
    "alarmCategory": "Alarm Category",
    "alarmSubcategory": "Alarm Sub Category",
    "alarmSeverity": "Alarm Severity",
    "alarmType": "Alarm Type",
    "alarmCode": "Alarm Code",
    "subAlarmName": "Sub Alarm Name",
    "subAlarmNeName": "Sub Alarm NE Name",
    "subAlarmNeNaIp": "Sub Alarm NE IP",
    "appendingAlarmName": "Appending Alarm Name",
    "appendingAlarmNeName": "Appending Alarm NE Name",
    "appendingAlarmNeIp": "Appending Alarm NE IP",
    "netWorkType": "Network Type",
    "neName": "NE Name",
    "neId": "NE ID",
    "neIP": "NE IP",
    "impactedServiceOrNo": "Whether Impacted Service",
    "impactedServiceWireless": "Impacted Service",
    "siteOutageOrNo": "Site Outage",
    "reasonType": "Alarm Reason Type",
    "slaTotalDuration": "SLA Total Duration",
    "slaStatus": "SLA Status",
    "remainingTime": "SLA Remaining Duration",
    "targetFinishTime": "SLA Expected Finish Time",
    "groupSlaTime": "Group SLA Time",
    "groupSlaStatus": "Group SLA Status",
    "groupSlaRemainsTime": "Group SLA Remains Time",
    "regionLevel1Name": "Region Level1",
    "regionLevel2Name": "Region Level2",
    "assetName": "Asset Name",
    "siteId": "Site ID",
    "assetType": "Asset Type",
    "siteClass": "Site Class",
    "candidateOperator": "Current Handler",
    "vendor": "Vendor",
    "createTime": "Created Time",
    "lastModifiedTime": "Last Modified Time",
    "alarmOccurTime": "Occurrence Time",
    "alarmClearTime": "Alarm Clearing Time",
    "faultDurationTime": "Fault Duration Time",
    "procId": "Proc ID",
    "alarmId": "Alarm ID",
}

WO_LIST_HEADERS = {
    "woNum": "WO No.",
    "parentwoNum": "TT NO.",
    "displayName": "Work Order Title",
    "creator": "Creator",
    "createTime": "Created Time",
    "lastModifiedTime": "Last Modified Time",
    "candidateOperator": "Current Handler",
    "siteId": "Site ID",
    "ticketSeverity": "Ticket Severity",
    "neType": "MOC",
    "vendor": "Vendor",
    "alarmOccurTime": "Occurrence Time",
    "alarmClearTime": "Alarm Clearing Time",
    "expectedFinishTime": "Expected Finish Time",
    "source": "Source",
    "projectName": "Project Name",
    "templateName": "Template Name",
    "creatorContactInfo": "Creator Contact Info",
    "alarmCategory": "Alarm Category",
    "alarmSubcategory": "Alarm Sub Category",
    "alarmSeverity": "Alarm Severity",
    "reasonType": "Reason Type",
    "alarmId": "Alarm ID",
    "alarmCode": "Alarm Code",
    "subAlarmName": "Sub Alarm Name",
    "subAlarmNEName": "Sub Alarm NE Name",
    "subAlarmNEIP": "Sub Alarm NE IP",
    "appendingAlarmName": "Appending Alarm Name",
    "appendingAlarmNEName": "Appending Alarm NE Name",
    "appendingAlarmNEIP": "Appending Alarm NE IP",
    "networkType": "Network Type",
    "neName": "NE Name",
    "neId": "NE ID",
    "neIp": "NE IP",
    "impactedServiceOrNo": "Whether Impacted Service",
    "impactedService": "Impacted Service",
    "siteOutageOrNo": "Site Outage",
    "faultDurationTime": "Fault Duration Time",
    "slaTotalDuration": "SLA Total Duration",
    "slaStatus": "SLA Status",
    "remainingTime": "SLA Remaining Duration",
    "targetFinishTime": "SLA Expected Finish Time",
    "groupSlaTime": "Group SLA Time",
    "groupSlaStatus": "Group SLA Status",
    "groupSlaRemainsTime": "Group SLA Remains Time",
    "regionLevel1Name": "Region Level1",
    "regionLevel2Name": "Region Level2",
    "assetName": "Asset Name",
    "assetType": "Asset Type",
    "siteClass": "Site Class",
}


def format_duration(value):
    """毫秒时长 → 导出格式 `0d16h0m`。空串保持 None，非数字原样返回。"""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        total_ms = int(float(value))
    except (TypeError, ValueError):
        return value
    if total_ms < 0:
        return value
    seconds = total_ms // 1000
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    return f"{days}d{hours}h{minutes}m"


def status_display(code, pending, table: str) -> str:
    """状态代码 → 库内显示名。挂起单在显示名后加 `(Suspended)`。"""
    raw = "" if code is None else str(code).strip()
    mapping = TT_STATUS_DISPLAY if table == "TT" else WO_STATUS_DISPLAY
    name = mapping.get(raw.lower())
    if not name:
        name = raw
        key = (table, raw)
        if raw and key not in _UNMAPPED_STATUS:
            _UNMAPPED_STATUS.add(key)
            logger.warning("%s 出现未映射的状态代码 %r，按原值入库", table, raw)
    pend = "" if pending is None else str(pending).strip().lower()
    if pend not in _PENDING_PLAIN:
        if "suspend" in pend:
            if not name.endswith("(Suspended)"):
                name = f"{name}(Suspended)"
        else:
            key = (table, pend)
            if key not in _UNMAPPED_PENDING:
                _UNMAPPED_PENDING.add(key)
                logger.warning("%s 出现未识别的 pendingStatus %r，状态名不加挂起后缀", table, pend)
    return name


def wo_no_from_info(value):
    """从 TT 的 woInfo（JSON 列表）取出 WO 号。没有就返回 None，避免把空值写进 wo_no。"""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text[0] not in "[{":
            return text
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return None
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return None
    nums = []
    for item in value:
        if not isinstance(item, dict):
            continue
        num = str(item.get("woNum") or "").strip()
        if num and num not in nums:
            nums.append(num)
    return ",".join(nums) or None


def _convert_value(api_field, value, time_fields):
    if isinstance(value, str) and not value.strip():
        return None
    if api_field in time_fields:
        return _cr_ms_to_text(value) if value not in (None, 0, "0") else None
    if api_field in _DURATION_FIELDS:
        return format_duration(value)
    return value


def build_tt_row(item: dict) -> dict:
    row = {}
    for api_field, header in TT_LIST_HEADERS.items():
        if api_field not in item:
            continue
        row[header] = _convert_value(api_field, item.get(api_field), _TT_TIME_FIELDS)
    row["Status"] = status_display(item.get("status"), item.get("pendingStatus"), "TT")
    if "opName" in item and item.get("opName") not in (None, ""):
        # 表头不进 TT_COLUMN_MAP，_clean_column_name 后落在已有列 operation_type。
        row["Operation Type"] = item.get("opName")
    wo_no = wo_no_from_info(item.get("woInfo"))
    if wo_no:
        row["WO No."] = wo_no
    return row


def build_wo_row(item: dict) -> dict:
    row = {}
    for api_field, header in WO_LIST_HEADERS.items():
        if api_field not in item:
            continue
        row[header] = _convert_value(api_field, item.get(api_field), _WO_TIME_FIELDS)
    row["Status"] = status_display(item.get("status"), item.get("pendingStatus"), "WO")
    if item.get("opName") not in (None, ""):
        row["Operation Step"] = item.get("opName")
    return row


def _fetch_pages(path, referer, payload_base, label) -> list:
    headers = _headers_extra(referer)
    rows = []
    start = 0
    total = None
    while True:
        payload = dict(payload_base)
        payload["start"] = start
        payload["length"] = _PAGE_SIZE
        status, _hdrs, _raw, resp = _http_request(
            "POST", path, headers_extra=headers, body=json.dumps(payload), max_retries=0,
        )
        text = (resp or b"").decode("utf-8", "replace")
        if "200" not in status:
            raise RuntimeError(f"{label} 列表接口 {status}: {text[:180]}")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{label} 列表接口返回的不是 JSON") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"{label} 列表接口返回 {type(data).__name__}")
        if data.get("code") not in (0, None, "0"):
            raise RuntimeError(f"{label} 列表接口 code={data.get('code')} {str(data.get('message') or '')[:160]}")
        if total is None:
            total = int(data.get("total") or 0)
            logger.info("%s 直查 total=%s", label, total)
        batch = data.get("result") or []
        if not isinstance(batch, list):
            raise RuntimeError(f"{label} 列表 result 不是数组")
        rows.extend(batch)
        start += _PAGE_SIZE
        if not batch or len(rows) >= total:
            break
    if total and len(rows) < total:
        raise RuntimeError(f"{label} 列表只拿到 {len(rows)}/{total} 行，放弃本次写入")
    return rows


def _to_rows(raw_rows, build, key_header) -> list:
    rows = []
    seen = set()
    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        row = build(item)
        key = str(row.get(key_header) or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def fetch_tt_via_list(start_ms, end_ms):
    """按最后修改时间窗口直查 TT。返回 `("eFlow TT", rows)`，表头与导出一致。"""
    filt = TIME_FILTER_TEMPLATE.format(status_filter=TT_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)
    raw = _fetch_pages(TT_API_PATH, TT_REFERER, {
        "customInfo": {"pageType": "allTicket"},
        "field": TT_FIELDS,
        "filter": filt,
        "order": "lastModifiedTime desc",
        "relationFilter": {"eflow_ticket_ticket_asset_all": ""},
    }, "TT")
    rows = _to_rows(raw, build_tt_row, "TT No.")
    if not rows:
        raise RuntimeError("TT 列表直查返回 0 行（上游异常或账号可见范围失权）")
    logger.info("TT 直查完成: %s 条", len(rows))
    return ("eFlow TT", rows)


def fetch_wo_via_list(start_ms, end_ms):
    """按最后修改时间窗口直查 WO。返回 `("eFlow WO", rows)`。"""
    filt = TIME_FILTER_TEMPLATE.format(status_filter=WO_STATUS_FILTER, start_ms=start_ms, end_ms=end_ms)
    raw = _fetch_pages(WO_API_PATH, WO_REFERER, {
        "customInfo": {"pageType": "allTicket"},
        "field": WO_FIELDS,
        "filter": filt,
        "order": "lastModifiedTime desc",
        "relationFilter": {"eflow_wo_wo_asset": ""},
    }, "WO")
    rows = _to_rows(raw, build_wo_row, "WO No.")
    if not rows:
        raise RuntimeError("WO 列表直查返回 0 行（上游异常或账号可见范围失权）")
    logger.info("WO 直查完成: %s 条", len(rows))
    return ("eFlow WO", rows)
