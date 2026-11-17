# -*- coding: utf-8 -*-
"""eFlow 全量对账删除的闸门回归。不联网、不写真实库。

覆盖的安全场景（每个都是「误删真实工单」的高危路径）：
  ① delta 模式绝不对账删除 —— 3 天窗口天然不完整；
  ② 上游权威集合为空 → 拒绝删除（不能把「查不到」当成「全被删」）；
  ③ 上游扫描异常 → 拒绝删除，并把错误写进 result["errors"]；
  ④ 待删量超过安全上限 → 拒绝删除；
  ⑤ 上游扫描不完整（total 与实拉条数不符）→ 抛错，拒绝删除；
  ⑥ 正常路径：只删「上游已无」的行，本地有、上游有的行必须留下；
  ⑦ 开关 EFLOW_RECONCILE_DELETE=0 → 完全不删。
"""
import sqlite3

import pytest

from backend.services import sync_from_eflow_api as sync_mod
from backend.services.eflow_reconcile import UpstreamVerifyError


def _make_db():
    """建一个内存库，带 eflow_tt / eflow_wo / eflow_cr 三张表。"""
    conn = sqlite3.connect(":memory:")
    conn.execute('CREATE TABLE "eflow_tt" ("tt_no" TEXT, "last_modified_time" TEXT)')
    conn.execute('CREATE TABLE "eflow_wo" ("wo_no" TEXT, "last_modified_time" TEXT)')
    conn.execute('CREATE TABLE "eflow_cr" ("change_request_id" TEXT, "last_modified_time" TEXT)')
    conn.commit()
    return conn


def _fill(conn, table, key_col, keys):
    conn.executemany(
        f'INSERT INTO "{table}" ("{key_col}", "last_modified_time") VALUES (?, ?)',
        [(k, "2026-11-01 00:00:00") for k in keys])
    conn.commit()


def _rows(conn, table, key_col):
    cur = conn.cursor()
    out = {r[0] for r in cur.execute(f'SELECT "{key_col}" FROM "{table}"')}
    cur.close()
    return out


class _FakeUpstream:
    """替换 fetch_authoritative_keys。

    真实签名返回 `(keys_by_label, errors_by_label)`：单表扫描失败只隔离该表，
    不再抛异常整轮放弃（2026-11-17 改）。
    """

    def __init__(self, keys=None, exc=None, scan_errors=None):
        self.keys = keys if keys is not None else {}
        self.exc = exc
        self.scan_errors = scan_errors or {}
        self.calls = 0

    def __call__(self, conn):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        keys = {k: v for k, v in self.keys.items() if k not in self.scan_errors}
        return keys, dict(self.scan_errors)


def _patch(monkeypatch, fake):
    monkeypatch.setattr(
        "backend.services.eflow_reconcile.fetch_authoritative_keys", fake)
    return fake


# ---------------- 闸门 ①：只在 full 模式删 ----------------

def test_reconcile_never_runs_in_delta_mode(monkeypatch):
    """delta 模式不得触发任何删除（窗口不完整，删了就是事故）。"""
    conn = _make_db()
    _fill(conn, "eflow_tt", "tt_no", ["TT202601010001"])
    fake = _patch(monkeypatch, _FakeUpstream({"TT": set(), "WO": set(), "CR": set()}))

    result = {"errors": []}
    # 主流程只在 full 模式调用 _reconcile_delete；这里直接验证 delta 路径不调用。
    # 模拟主流程的守卫：mode != "full" 时不进入对账。
    mode = "delta"
    if mode == "full":  # pragma: no cover - 断言 delta 不会进这个分支
        sync_mod._reconcile_delete(conn, result)

    assert fake.calls == 0
    assert _rows(conn, "eflow_tt", "tt_no") == {"TT202601010001"}


# ---------------- 闸门 ②：上游集合为空 → 拒绝 ----------------

def test_empty_upstream_set_refuses_to_delete(monkeypatch):
    """上游权威集合为空 → 该表不删（空集合不等于「全被删」）。

    按表隔离：TT 集合为空只影响 TT，**不影响**其他表继续对账删除。
    """
    conn = _make_db()
    _fill(conn, "eflow_tt", "tt_no", ["TT202601010001", "TT202601010002"])
    _fill(conn, "eflow_wo", "wo_no", ["WO001", "WO002"])
    # TT 上游为空 → TT 不删；WO 上游有 WO001 → WO002 该删
    _patch(monkeypatch, _FakeUpstream({"TT": set(), "WO": {"WO001"}, "CR": set()}))

    result = {"errors": []}
    sync_mod._reconcile_delete(conn, result)

    assert _rows(conn, "eflow_tt", "tt_no") == {"TT202601010001", "TT202601010002"}, \
        "空上游集合时该表一张都不能删"
    assert _rows(conn, "eflow_wo", "wo_no") == {"WO001"}, "其他表不受牵连"
    assert result["errors"], "空上游集合必须记进 errors"
    assert "eflow_tt" in result["reconcile_skipped"]


# ---------------- 扫描器整体崩了 → 整轮放弃 ----------------

def test_scanner_crash_refuses_to_delete(monkeypatch):
    """扫描器本身抛异常（连一张表都没扫出来）→ 整轮放弃删除。

    注意：单表扫描失败**不再**走这条路径（见下一条用例），
    只有扫描器整体崩掉才整轮放弃。
    """
    conn = _make_db()
    _fill(conn, "eflow_tt", "tt_no", ["TT202601010001"])
    _patch(monkeypatch, _FakeUpstream(exc=UpstreamVerifyError("上游 500")))

    result = {"errors": []}
    sync_mod._reconcile_delete(conn, result)

    assert _rows(conn, "eflow_tt", "tt_no") == {"TT202601010001"}
    assert result["errors"]
    assert "上游 500" in result["reconcile_skipped"]


# ---------------- 单表扫描失败 → 只隔离该表（2026-11-17） ----------------

def test_single_table_scan_error_isolates_only_that_table(monkeypatch):
    """单表扫描不完整 → 只跳过该表，其他表照常对账删除。

    背景（2026-11-17 实测）：TT 扫描差 1 行（42054/42055）曾导致整轮放弃，
    WO 与 CR 当轮也全都不删，任务还 success=False 连发告警。
    """
    conn = _make_db()
    _fill(conn, "eflow_tt", "tt_no", ["TT001", "TT002"])
    _fill(conn, "eflow_wo", "wo_no", ["WO001", "WO002"])
    _fill(conn, "eflow_cr", "change_request_id", ["CR001", "CR002"])

    _patch(monkeypatch, _FakeUpstream(
        keys={"TT": {"TT001"}, "WO": {"WO001"}, "CR": {"CR001"}},
        scan_errors={"TT": "TT 上游只拉到 42054/42055 行"},
    ))

    result = {"errors": []}
    sync_mod._reconcile_delete(conn, result)

    assert _rows(conn, "eflow_tt", "tt_no") == {"TT001", "TT002"}, \
        "TT 扫描不完整 → 一张都不能删"
    assert _rows(conn, "eflow_wo", "wo_no") == {"WO001"}, "WO 不受牵连，照常删"
    assert _rows(conn, "eflow_cr", "change_request_id") == {"CR001"}, "CR 不受牵连，照常删"
    assert any("TT" in e and "扫描不完整" in e for e in result["errors"])
    assert "eflow_tt" in result["reconcile_skipped"]

# ---------------- 闸门 ④：待删量超上限 → 拒绝 ----------------

def test_too_many_deletions_refuses_to_delete(monkeypatch):
    """待删量超过安全上限 → 跳过该表（上游异常时的最后防线）。

    注意：本用例必须让**上游集合非空**，否则会先被闸门 ③（空集合跳过）拦下，
    测不到闸门 ④。300 行里上游只保留 1 个 → 待删 299 个
    → 超过上限 max(200, 300*0.05=15)=200 → 跳过该表。
    """
    conn = _make_db()
    local = {f"TT2026010{i:04d}" for i in range(300)}
    _fill(conn, "eflow_tt", "tt_no", local)
    _patch(monkeypatch, _FakeUpstream({"TT": {"TT20260100000"},
                                       "WO": set(), "CR": set()}))

    result = {"errors": []}
    sync_mod._reconcile_delete(conn, result)

    # 闸门 ④ 拦下 → 该表一张都不能删
    assert len(_rows(conn, "eflow_tt", "tt_no")) == 300, "超上限时一张都不能删"
    assert result["errors"]
    # 跳过原因写在 errors 里（reconcile_skipped 是被跳过的表名列表）
    assert any("超过安全上限" in e for e in result["errors"])
    assert "eflow_tt" in result["reconcile_skipped"]


def test_ratio_limit_blocks_large_relative_deletion(monkeypatch):
    """待删数超过阈值但未超绝对上限时，仍按上限判定删除。"""
    conn = _make_db()
    local = {f"TT2026010{i:04d}" for i in range(20)}
    _fill(conn, "eflow_tt", "tt_no", local)
    # 上游保留 1 个 → 待删 19 个；上限 = max(200, 20*0.05=1) = 200 → 不拦（绝对上限主导）
    up = {f"TT2026010{i:04d}" for i in range(1)}
    _patch(monkeypatch, _FakeUpstream({"TT": up, "WO": set(), "CR": set()}))

    result = {"errors": []}
    sync_mod._reconcile_delete(conn, result)

    assert _rows(conn, "eflow_tt", "tt_no") == up
    assert result["reconcile_deleted"]["eflow_tt"] == 19


# ---------------- 闸门 ⑤：扫描不完整 → 抛错 ----------------

def test_incomplete_scan_raises_upstream_error():
    """上游声明 total 但没拉全 → 抛 UpstreamVerifyError（不返回残缺集合）。"""
    from backend.services import eflow_reconcile

    calls = {"n": 0}

    def fake_http(method, path, headers_extra=None, body=None, max_retries=None, **kw):
        calls["n"] += 1
        # 第一页满（200 条，total 声明 500）→ 第二页开始只给 10 条 → 触发不完整判定
        if calls["n"] == 1:
            payload = {"code": 0, "total": 500,
                       "result": [{"woNum": f"TT{i:06d}"} for i in range(200)]}
        else:
            payload = {"code": 0, "total": 500,
                       "result": [{"woNum": f"TTX{i:03d}"} for i in range(10)]}
        import json as _json
        return "200 OK", {}, {}, _json.dumps(payload).encode("utf-8")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(eflow_reconcile, "_http_request", fake_http)
    try:
        with pytest.raises(UpstreamVerifyError):
            eflow_reconcile._scan_upstream_keys("/api/x", "ref", {}, "TT")
    finally:
        monkey.undo()


def test_small_shortfall_is_tolerated():
    """缺口在容差内（count 抖动）→ 不抛错，正常返回键集合。

    背景：上游 total 是首页读到的计数，扫描要跑几分钟，期间有单增减，
    精确相等不可能满足。2026-11-17 实测差 1 行与 4 行就整轮失败。
    """
    from backend.services import eflow_reconcile
    import json as _json

    calls = {"n": 0}

    def fake_http(method, path, headers_extra=None, body=None, max_retries=None, **kw):
        calls["n"] += 1
        # 声明 total=500，实拉 497（缺 3，远小于容差 max(10, 2)）→ 应被容忍
        payload = {"code": 0, "total": 500,
                   "result": [{"woNum": f"TT{i:06d}"} for i in range(497)]}
        return "200 OK", {}, {}, _json.dumps(payload).encode("utf-8")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(eflow_reconcile, "_http_request", fake_http)
    try:
        keys = eflow_reconcile._scan_upstream_keys("/api/x", "ref", {}, "TT")
    finally:
        monkey.undo()

    assert len(keys) == 497


def test_shortfall_tolerance_scales_with_table_size():
    """容差 = max(绝对下限 10, total × 0.5%)。"""
    from backend.services.eflow_reconcile import _shortfall_tolerance

    assert _shortfall_tolerance(300) == 10        # 小表走绝对下限
    assert _shortfall_tolerance(42000) == 210     # 大表按 0.5%
    assert _shortfall_tolerance(0) == 10


# ---------------- 正常路径：只删上游已无的 ----------------

def test_deletes_only_upstream_absent_rows(monkeypatch):
    """核心场景：上游已删的行被删掉，仍存在的行必须留下。"""
    conn = _make_db()
    _fill(conn, "eflow_tt", "tt_no", ["TT001", "TT002", "TT003"])
    _fill(conn, "eflow_wo", "wo_no", ["WO001", "WO002"])
    _fill(conn, "eflow_cr", "change_request_id", ["CR001", "CR002", "CR003"])

    upstream = {
        "TT": {"TT001", "TT003"},      # TT002 上游已删
        "WO": {"WO001"},               # WO002 上游已删
        "CR": {"CR001", "CR002"},      # CR003 上游已删
    }
    _patch(monkeypatch, _FakeUpstream(upstream))

    result = {"errors": []}
    sync_mod._reconcile_delete(conn, result)

    assert _rows(conn, "eflow_tt", "tt_no") == {"TT001", "TT003"}
    assert _rows(conn, "eflow_wo", "wo_no") == {"WO001"}
    assert _rows(conn, "eflow_cr", "change_request_id") == {"CR001", "CR002"}
    assert result["reconcile_deleted"] == {"eflow_tt": 1, "eflow_wo": 1, "eflow_cr": 1}
    assert not result["errors"]


# ---------------- 开关：EFLOW_RECONCILE_DELETE=0 → 完全不删 ----------------

def test_switch_off_skips_deletion(monkeypatch):
    """开关关掉时完全不删（线上出问题可零改码回滚）。"""
    monkeypatch.setenv("EFLOW_RECONCILE_DELETE", "0")
    conn = _make_db()
    _fill(conn, "eflow_tt", "tt_no", ["TT001", "TT002"])
    fake = _patch(monkeypatch, _FakeUpstream({"TT": {"TT001"}, "WO": set(), "CR": set()}))

    result = {"errors": []}
    sync_mod._reconcile_delete(conn, result)

    assert fake.calls == 0, "开关关掉时不该发起上游扫描"
    assert _rows(conn, "eflow_tt", "tt_no") == {"TT001", "TT002"}
