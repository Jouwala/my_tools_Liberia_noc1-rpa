# -*- coding: utf-8 -*-
"""TT 批量级别核查：纯函数单测（不连库、不打网络，可安全被 pytest 收集）。

覆盖：
  - 单号清洗（大小写 / 去重 / 噪声词 / 截断）
  - 粘贴文本拆分（换行 / 逗号 / 分号 / 制表符）
  - 判定口径（正常 / 需调整 / 无法判定）
  - 规则字段取值整形（NaN、整数值浮点、No Match）
"""
from backend.services.eflow_rules import tt_batch_severity as B


# ---------------- 入参清洗 ----------------

def test_normalize_uppercases_dedupes_and_filters():
    r = B.normalize_tt_list(["tt202609140082", "TT202609140082", "  ", "TT号", "NOT", "A", "TT202609140080"])
    assert r["valid"] == ["TT202609140082", "TT202609140080"]
    assert r["duplicated"] == 1
    assert "TT号" in r["invalid"] and "NOT" in r["invalid"] and "A" in r["invalid"]


def test_normalize_truncates_to_limit():
    r = B.normalize_tt_list([f"TT2026{i:08d}" for i in range(10)], limit=3)
    assert len(r["valid"]) == 3
    assert r["truncated"] is True


def test_parse_tt_text_splits_on_common_separators():
    assert B.parse_tt_text("TT1\nTT2,TT3;TT4\tTT5|TT6") == ["TT1", "TT2", "TT3", "TT4", "TT5", "TT6"]
    assert B.parse_tt_text("") == []
    assert B.parse_tt_text(None) == []


# ---------------- 判定口径 ----------------

def _src(**kw):
    base = {
        "tt_no": "TT202609140001", "ticket_severity": "P3", "site_name": "Bandor",
        "alarm_code": "99933.0", "vip_site": "No", "site_type": "", "down_site_count": "1",
    }
    base.update(kw)
    return base


def _matched(sev="P3", rule="229", changed="NO"):
    return {
        "Matched_Rule_ID": rule, "Matched_Rule_Name": "无线断站级别重定义-P3-rule2",
        "Matched_Priority": 3.0, "New_Severity": sev, "Severity_Changed": changed,
        "Match_Details": "alarmCode=99933 in ... ✓",
    }


def test_row_marks_ok_when_level_matches_rule():
    row = B._row_from_match("TT202609140001", _src(), _matched())
    assert row["level_status"] == "ok"
    assert row["ticket_severity"] == "P3" and row["expected_severity"] == "P3"
    assert row["matched_rule_id"] == "229" and row["matched_priority"] == "3"
    assert row["alarm_code"] == "99933"  # 末尾 .0 被去掉


def test_row_marks_adjust_when_rule_suggests_other_level():
    row = B._row_from_match("TT202609140001", _src(), _matched(sev="P1", changed="YES"))
    assert row["level_status"] == "adjust"
    assert row["ticket_severity"] == "P3" and row["expected_severity"] == "P1"


def test_row_unknown_when_no_rule_matched():
    row = B._row_from_match("TT202609140001", _src(), _matched(sev="", rule="No Match", changed="NO"))
    assert row["level_status"] == "unknown"
    assert row["matched_rule_id"] == "" and row["expected_severity"] == ""


def test_row_unknown_when_ticket_severity_empty():
    row = B._row_from_match("TT202609140001", _src(ticket_severity=None), _matched(sev="P3", changed="YES"))
    assert row["level_status"] == "unknown"
    assert row["ticket_severity"] == ""


def test_missing_row_is_not_found():
    row = B._missing_row("TT000000000001")
    assert row["found"] is False and row["level_status"] == "unknown"
    assert row["tt_no"] == "TT000000000001"


def test_check_batch_rejects_empty_input_without_touching_db():
    res = B.check_batch(["not a tt", "TT"])
    assert res["ok"] is False
    assert res["rows"] == [] and res["summary"]["found"] == 0
    assert set(res["input"]["invalid"]) == {"NOT", "A", "TT"}
