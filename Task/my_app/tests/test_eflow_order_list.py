# -*- coding: utf-8 -*-
"""TT/WO 列表直查的纯函数回归。不联网、不写库。"""
from backend.services.eflow_order_list import (
    build_tt_row,
    build_wo_row,
    format_duration,
    status_display,
    wo_no_from_info,
)
from backend.services.sync_from_eflow_api import _clean_column_name


def test_duration_matches_export_format():
    assert format_duration(57600000) == "0d16h0m"
    assert format_duration(27841643) == "0d7h44m"
    assert format_duration("") is None
    assert format_duration(None) is None


def test_status_display_uses_stored_names():
    assert status_display("WaitFOProcess", "activate", "TT") == "Waiting for FO Process"
    assert status_display("WaitThirdAccept", "activate", "TT") == "Waiting for Third Accept"
    assert status_display("Closed", "activate", "TT") == "Closed"
    assert status_display("WaitAccept", "activate", "WO") == "Waiting for Accept"
    assert status_display("WaitStartTrip", "activate", "WO") == "Waiting for Departure"
    assert status_display("WaitConfirm", "activate", "WO") == "Wait For Confirm"
    assert status_display("WaitProcess", "suspend", "WO") == "Waiting for Process(Suspended)"


def test_wo_no_from_info():
    raw = '[{"woNum":"WO202611120062","status":"Accepted"}]'
    assert wo_no_from_info(raw) == "WO202611120062"
    assert wo_no_from_info("") is None
    assert wo_no_from_info(None) is None
    assert wo_no_from_info("WO202611120062") == "WO202611120062"
    assert wo_no_from_info("[") is None


def test_tt_row_headers_land_on_existing_columns():
    row = build_tt_row({
        "woNum": "TT202611120098",
        "status": "WaitThirdAccept",
        "pendingStatus": "activate",
        "opName": "ThirdAccept",
        "displayName": " 3741.[Zannah Town]Complete site down (CSD)",
        "assetName": "Zannah Town",
        "siteId": "3741",
        "ticketSeverity": "P3",
        "alarmCode": "9920",
        "netWorkType": "RAN",
        "createTime": 1794527088232,
        "alarmOccurTime": 1794512661000,
        "targetFinishTime": 1794570261000,
        "slaTotalDuration": 57600000,
        "candidateOperator": "G:3rd_Power",
        "woInfo": '[{"woNum":"WO202611120062"}]',
    })
    assert row["TT No."] == "TT202611120098"
    assert row["Status"] == "Waiting for Third Accept"
    assert row["Operation Type"] == "ThirdAccept"
    assert row["WO No."] == "WO202611120062"
    assert row["Created Time"] == "2026-11-12 23:44:48"
    assert row["Occurrence Time"] == "2026-11-12 19:44:21"
    assert row["SLA Expected Finish Time"] == "2026-11-13 11:44:21"
    assert row["SLA Total Duration"] == "0d16h0m"
    assert _clean_column_name("TT No.") == "tt_no"
    assert _clean_column_name("Operation Type") == "operation_type"


def test_wo_row_headers():
    row = build_wo_row({
        "woNum": "WO202611120061",
        "parentwoNum": "TT202611120096",
        "status": "WaitAccept",
        "pendingStatus": "activate",
        "opName": "Accept",
        "displayName": " 4264.[Zubah Town]Partial site down (PSD)",
        "siteId": "4264",
        "ticketSeverity": "P2",
    })
    assert row["WO No."] == "WO202611120061"
    assert row["TT NO."] == "TT202611120096"
    assert row["Status"] == "Waiting for Accept"
    assert row["Operation Step"] == "Accept"
    assert row["Work Order Title"].startswith(" 4264.")
