# -*- coding: utf-8 -*-
"""5G 派单**单条判定链**的单测（`g5_dispatch.process_alarm`）。

## 为什么要有这组用例

`g5_dispatch.process_alarm` 是 5G 派单的判定内核：一条告警进来，
按固定的十步判定链落到**唯一一个**出口（派单 / 演练 / 合并 / 跳过 / 等待 /
过期 / 失败）。每一步的出口都对应一种现场后果，**任何一步漏判都会造成
错派、漏派或重复派单** —— 故这里逐个出口钉一条用例。

不触网、不碰库：eFlow 调用与状态表写入都被替身挡掉，只验判定与计数。
"""
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.eflow_assign import assign_engine as engine  # noqa: E402
from backend.services.eflow_5g import g5_dispatch as dispatch  # noqa: E402
from backend.services.eflow_5g import g5_rules as rules  # noqa: E402

NOW = 1_760_000_000_000


def _alarm(code="200201001", site="4162", sitename="Liscr", cell="52",
           cellname="Liscr-S2", raised_ms=None, key=None, **extra):
    a = {
        "alarmcode": {"value": code},
        "site": {"value": site},
        "sitename": {"value": sitename},
        "cell": {"value": cell},
        "cellname": {"value": cellname},
        "alarmkey": {"value": key or f"key-{code}-{site}-{cell}"},
        "id": {"value": f"id-{key or code}"},
    }
    if raised_ms is not None:
        a["alarmraisedtime"] = {"value": raised_ms}
    a.update(extra)
    return a


class _FakeConn:
    """状态表写入替身：只记录，不落库。"""

    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []


class _FakeIndex:
    """cmdb 站点索引替身：只按数字站号 + 站点名精确命中。"""

    def lookup(self, name):
        return None


def _ctx(**over) -> engine.AssignContext:
    kw = dict(
        alarm_codes={"200201001", "200201018", "200201041", "200201043", "200201060"},
        correlation_codes={"99933"},
        correlation_window_minutes=60,
        window_minutes=180,
        min_age_minutes=15,
        group_window_minutes=10,
        assign_group="ZTE_NOC_FO",
        dry_run=True,
        groups=["test123"],
        push_title="5G Site Alarm TT Assign Notification",
        tag="5G",
        outage_label="the same 5G site outage",
    )
    kw.update(over)
    return engine.AssignContext(**kw)


def _run(alarm, *, rec=None, ctx=None, all_alarms=None, group_map=None,
         group_tt=None, group_cells=None, resolve=None,
         assign_ret=("TT20261029001", "")):
    """跑一条告警 → (结果 dict, 状态表写入过的行, group_tt, group_cells)。"""
    conn = _FakeConn()
    ctx = ctx or _ctx()
    group_tt = {} if group_tt is None else group_tt
    group_cells = {} if group_cells is None else group_cells
    group_map = group_map or {}

    orig_resolve = dispatch.client.resolve_site
    orig_assign = dispatch.engine.assign_with_retry
    orig_upsert = dispatch.store.upsert_record
    try:
        if resolve is not None:
            dispatch.client.resolve_site = resolve
        dispatch.engine.assign_with_retry = (lambda *a, **kw: assign_ret)
        # 状态表写入替身：只把行记进 conn.rows，不碰数据库
        dispatch.store.upsert_record = (
            lambda c, rec, *a, **kw: c.rows.append(dict(rec)))
        res = dispatch.process_alarm(
            alarm, ctx, rec or {}, {"id": "g1", "acceptType": "FO"},
            _FakeIndex(), conn, all_alarms or [], group_map,
            group_tt, group_cells, NOW)
    finally:
        dispatch.client.resolve_site = orig_resolve
        dispatch.engine.assign_with_retry = orig_assign
        dispatch.store.upsert_record = orig_upsert
    return res, conn.rows, group_tt, group_cells


# ============================ 出口 1：已处理 ============================
def test_already_assigned_is_skipped_forever():
    """状态表有 `Y` → 永久跳过（否则同一告警每轮重复建 TT）。"""
    a = _alarm(raised_ms=NOW - 20 * 60_000)
    res, _rows, _tt, _cells = _run(a, rec={"assign_status": "Y"})
    assert res["action"] == dispatch.ACTION_SKIP
    assert res.get("due") is not True


def test_dry_run_record_is_skipped_only_in_dry_run():
    """演练记录 `D`：演练模式下算已处理；关掉 dry_run 后必须重新处理。"""
    a = _alarm(raised_ms=NOW - 20 * 60_000)
    res, _r, _t, _c = _run(a, rec={"assign_status": "D"}, ctx=_ctx(dry_run=True))
    assert res["action"] == dispatch.ACTION_SKIP
    res2, _r2, _t2, _c2 = _run(a, rec={"assign_status": "D"}, ctx=_ctx(dry_run=False))
    assert res2["action"] == dispatch.ACTION_ASSIGN


# ============================ 出口 2：上游已有 TT ============================
def test_upstream_tt_is_skipped():
    """上游 `ttid` 非空 → 不重复派（eFlow 自己的规则先建了单）。"""
    a = _alarm(raised_ms=NOW - 20 * 60_000, ttid={"value": "TT20261026001"})
    res, _r, _t, _c = _run(a)
    assert res["action"] == dispatch.ACTION_SKIP
    assert res["sample"]["action"] == "skip_existing_tt"


def test_empty_ttid_is_not_treated_as_upstream_tt():
    """`ttid='empty'` 是占位值，不算上游已有 TT。"""
    a = _alarm(raised_ms=NOW - 20 * 60_000, ttid={"value": "empty"})
    res, _r, _t, _c = _run(a)
    assert res["action"] == dispatch.ACTION_DRY_RUN


# ============================ 出口 3/4：等待与过期 ============================
def test_too_young_waits_instead_of_skipping():
    """存续不足 15 分钟 → **等待**（不是跳过）：下轮还要看它。"""
    a = _alarm(raised_ms=NOW - 5 * 60_000)
    res, _r, _t, _c = _run(a)
    assert res["action"] == dispatch.ACTION_WAIT
    assert res["age_minutes"] == 5.0
    assert res.get("due") is not True


def test_too_old_expires():
    """存续超过 180 分钟 → 过期不派（防上线瞬间把积压告警全派出去）。"""
    a = _alarm(raised_ms=NOW - 4 * 3600_000)
    res, _r, _t, _c = _run(a)
    assert res["action"] == dispatch.ACTION_EXPIRED


# ============================ 出口 5：关联命中 ============================
def test_correlation_hit_skips():
    """同站同窗口已有 99933 → 不重复派单。"""
    a = _alarm(raised_ms=NOW - 20 * 60_000, key="tgt")
    corr = _alarm(code="99933", site="4162", sitename="Liscr",
                  raised_ms=NOW - 18 * 60_000, key="corr")
    res, _r, _t, _c = _run(a, all_alarms=[a, corr])
    assert res["action"] == dispatch.ACTION_SKIP
    assert res["sample"]["action"] == "skip"


def test_correlation_undetermined_still_assigns():
    """关联判定**无法完成** → 按「无关联」继续派单并留痕（不因名字对不上长期漏派）。"""
    a = _alarm(raised_ms=NOW - 20 * 60_000, key="tgt")
    # 关联告警自身站点信息不足 → 无法比对 → undetermined
    corr = _alarm(code="99933", site="--", sitename="--",
                  raised_ms=NOW - 18 * 60_000, key="corr")
    res, _r, _t, _c = _run(a, all_alarms=[a, corr])
    assert res["action"] == dispatch.ACTION_DRY_RUN
    assert res["correlation_undetermined"] is True
    assert res["corr_note"] and "could not be determined" in res["corr_note"]


# ============================ 出口 6：合并 ============================
def test_merged_into_group_root():
    """同站多小区：成员告警并入组长已建的 TT，不单独派单。"""
    member = _alarm(cell="51", cellname="Liscr-S1", raised_ms=NOW - 20 * 60_000, key="m1")
    group_map = {"m1": {"root": "root1", "members": [member], "site": "id:4162"}}
    res, rows, tt, cells = _run(member, group_map=group_map,
                                group_tt={"root1": "TT20261029002"},
                                ctx=_ctx(dry_run=False))
    assert res["action"] == dispatch.ACTION_MERGED
    assert res["root"] == "root1"
    assert "Liscr-S1" in res["cells"]
    # 落表：状态 Y（真派单）+ 共用组长的 TT 号 + 说明为什么没单独派
    assert rows[-1]["assign_status"] == "Y"
    assert rows[-1]["tt_no"] == "TT20261029002"
    assert "合并到组长告警" in rows[-1]["skip_reason"]


def test_merged_in_dry_run_records_d():
    """演练模式下合并的成员记 `D`（关掉 dry_run 后要重新处理）。"""
    member = _alarm(cell="51", cellname="Liscr-S1", raised_ms=NOW - 20 * 60_000, key="m1")
    group_map = {"m1": {"root": "root1", "members": [member], "site": "id:4162"}}
    res, rows, _tt, _c = _run(member, group_map=group_map,
                              group_tt={"root1": ""}, ctx=_ctx(dry_run=True))
    assert res["action"] == dispatch.ACTION_MERGED
    assert rows[-1]["assign_status"] == "D"


# ============================ 出口 7：站点解析失败 ============================
def test_site_resolution_failure_is_not_silent():
    """站点解析失败 → 记 N + 产出「需人工处理」通报（不能静默漏派）。"""
    a = _alarm(raised_ms=NOW - 20 * 60_000)
    res, rows, _t, _c = _run(a, resolve=lambda al, idx, trace=None: ("", ""))
    assert res["action"] == dispatch.ACTION_FAIL
    assert rows[-1]["assign_status"] == "N"
    assert res["manual"] is not None
    assert "failed" in res["manual"]["reason"]


def test_site_resolution_failure_does_not_notify_twice():
    """已通报过（send_status=Y）→ 不再重复发「需人工处理」。"""
    a = _alarm(raised_ms=NOW - 20 * 60_000)
    res, _r, _t, _c = _run(a, rec={"send_status": "Y"},
                            resolve=lambda al, idx, trace=None: ("", ""))
    assert res["action"] == dispatch.ACTION_FAIL
    assert res["manual"] is None


# ============================ 出口 8/9：演练与真派单 ============================
def test_dry_run_records_and_renders_preview():
    """演练：记 `D`、不调派单接口、产出「将发的正文」素材。"""
    a = _alarm(raised_ms=NOW - 20 * 60_000)
    res, rows, tt, cells = _run(a)
    assert res["action"] == dispatch.ACTION_DRY_RUN
    assert rows[-1]["assign_status"] == "D"
    assert res["site_id"] == "4162" and res["site_name"] == "Liscr"
    assert res["cell"] == "Liscr-S2"
    assert res.get("due") is True


def test_real_assign_records_tt_and_group_cells():
    """真派单：回查到 TT 才算成功 → 落表 `Y` + TT 号，本组小区累积。"""
    a = _alarm(cell="52", cellname="Liscr-S2", raised_ms=NOW - 20 * 60_000, key="root1")
    res, rows, tt, cells = _run(a, ctx=_ctx(dry_run=False))
    assert res["action"] == dispatch.ACTION_ASSIGN
    assert res["tt_no"] == "TT20261029001"
    assert rows[-1]["assign_status"] == "Y"
    assert rows[-1]["tt_no"] == "TT20261029001"
    assert tt["root1"] == "TT20261029001"
    assert cells["root1"] == ["Liscr-S2"]


def test_assign_failure_records_n_and_reports():
    """派单失败（回查不到 ttid）→ 记 `N` + warnings，不谎报成功。"""
    a = _alarm(raised_ms=NOW - 20 * 60_000)
    res, rows, _t, _c = _run(a, ctx=_ctx(dry_run=False),
                             assign_ret=("", "assign API returned success but no TT"))
    assert res["action"] == dispatch.ACTION_FAIL
    assert rows[-1]["assign_status"] == "N"
    assert "no TT" in rows[-1]["last_error"]
    assert res["warning"] and "派单失败" in res["warning"]


def test_suspect_ttstatus_does_not_block_but_is_traced():
    """eFlow 侧 ttstatus 非 0 → 不阻断派单（照派），但必须留痕。"""
    a = _alarm(raised_ms=NOW - 20 * 60_000, ttstatus={"value": "2"})
    res, _r, _t, _c = _run(a)
    assert res["action"] == dispatch.ACTION_DRY_RUN
    assert res["suspect_ttstatus"] is True
    assert res["warning"] and "ttstatus" in res["warning"]


# ============================ 基础记录 ============================
def test_base_record_contains_cell_and_site():
    """状态表基础行必须带小区名（5G 特有维度，排障要看清楚是哪几个小区）。"""
    a = _alarm(raised_ms=NOW - 20 * 60_000)
    rec = dispatch.build_base_record(a, {})
    assert rec["cell_name"] == "Liscr-S2"
    assert rec["site_id"] == "4162" and rec["site_name"] == "Liscr"
    assert rec["alarm_code"] == "200201001"
    assert rec["occur_time"]


def test_alarm_code_is_normalized_in_record():
    """告警码归一化（去掉 .0 尾巴）后落表，避免 '200201001.0' 之类脏值。"""
    a = _alarm(code="200201001.0", raised_ms=NOW - 20 * 60_000)
    rec = dispatch.build_base_record(a, {})
    assert rec["alarm_code"] == "200201001"


def test_rules_module_exposes_same_behaviour():
    """再导出的纯函数与 `g5_rules` 是同一实现（避免两处漂移）。"""
    a = _alarm(cellname="Liscr-S2")
    assert rules.alarm_cell(a) == dispatch.rules.alarm_cell(a)
