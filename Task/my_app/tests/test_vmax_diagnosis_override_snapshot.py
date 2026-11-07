# -*- coding: utf-8 -*-
"""P3-3：覆写记录携带完整诊断快照（`vmax_diagnosis_override.verdict_snapshot`）。

为什么要有这个文件：
    `verdict`（结论 / 四维分 / 证据）是**纯前端**按规则算出来的，
    `verdict_auto` 只是「客户端声明的结论」；覆写记录若不带上输入快照，
    事后从库里无法复现「当时凭什么这么判」。本文件把四件事钉住：

      1. 老库（表已存在、有历史行、没有 `verdict_snapshot` 列）能被**幂等**补列，
         历史行不丢、快照回 NULL（=「当时未存档」），且重复调用无副作用；
      2. POST → GET → history 三处回读到同一份快照，号码仍只以脱敏形式落库；
      3. 超长（> 20KB UTF-8）/ 非法 JSON 一律 422，且**不落半条记录**；
      4. 再次提交不带快照时**保留**已有快照 —— 顺手改个理由不该清掉审计依据。

    全部使用 `tmp_path` 下的 sqlite 临时库（monkeypatch 掉路由自己的
    `get_raw_connection`），**不连生产 PG、不读写生产 app.db**。

运行：
    cd D:/01_RPA/Task/my_app
    python -m pytest tests/test_vmax_diagnosis_override_snapshot.py -q
"""
import json
import sqlite3

import pytest
from fastapi import HTTPException

from backend.routers import vmax_diagnosis_override as R

MSISDN = "231773777115"
START = "2026-11-07 08:00:00"
END = "2026-11-07 10:00:00"
USER = {"username": "alice"}

# 迁移前的老表结构（**不含** verdict_snapshot），用于验证「已有历史行的库能补列」
LEGACY_DDL = """
CREATE TABLE vmax_diagnosis_override (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    msisdn_mask TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    verdict_auto TEXT,
    verdict_manual TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revoked_at TEXT
)
"""


class _SqliteWrap:
    """模拟 `get_raw_connection` 的 with 语义：进入开连接，退出提交/回滚并关闭。

    每个 `with` 都开新连接 —— 路由里一次请求只用一次，但用例可能多次调用。
    """

    def __init__(self, path):
        self._path = path
        self._conn = None

    def __enter__(self):
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._conn.close()
        return False


def _use_sqlite(monkeypatch, path):
    """把路由模块里的 get_raw_connection 指到临时 sqlite 文件。"""
    monkeypatch.setattr(R, "get_raw_connection", lambda *a, **k: _SqliteWrap(path))


def _cols(path):
    conn = sqlite3.connect(str(path))
    try:
        return [r[1] for r in conn.execute("PRAGMA table_info(vmax_diagnosis_override)")]
    finally:
        conn.close()


def _rows(path):
    """读出全部行（dict 形式，便于断言与序列化）。

    表还没建时返回 []：快照校验失败发生在 `_ensure_table` 之前，
    「什么都没落库」也包括「表都还没建」，两种都算合法空。
    """
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        try:
            rows = conn.execute(
                "SELECT * FROM vmax_diagnosis_override ORDER BY id").fetchall()
        except sqlite3.OperationalError:      # 表不存在
            return []
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _snapshot(**over):
    """构造一份最小但结构完整的快照（字段与前端 lib/vmaxVerdictSnapshot.ts 对齐）。"""
    base = {
        "version": 1,
        "generated_at": "2026-11-07T10:05:00.000Z",
        "complaint": "voice",
        "window": {"start": START, "end": END},
        "imsi": "231010000000001",
        "verdict": {
            "headline": {"key": "vmaxq.vd.headline.ok"},
            "basis": [{"key": "vmaxq.vd.basis.voiceNoSgs"}],
            "suggestion": {"key": "vmaxq.vd.sugg.voiceNone"},
            "confidence": "high",
            "reproduced": False,
            "focus": "voice",
        },
        "scores": [
            {"key": "availability", "score": 92, "detail": {}, "evidence": []},
            {"key": "latency", "score": 78, "detail": {}, "evidence": []},
            {"key": "transport", "score": 88, "detail": {}, "evidence": []},
            {"key": "radio", "score": None, "detail": {}, "evidence": []},
        ],
        "sources": [
            {"key": "1300", "label": "用户面话单", "label_key": "vmaxq.diag.src.1300",
             "ok": True, "rows": 12, "truncated": False, "error": ""},
            {"key": "32", "label": "无线质量", "label_key": "vmaxq.diag.src.32",
             "ok": False, "rows": 0, "truncated": False, "error": "RAN 域无记录"},
        ],
        "voice": {"mode": "csfb", "sgsCount": 2, "csfbTrigger": 1, "esrCount": 2},
        "ott": {"totalSessions": 0, "avgDlRtt": 0},
        "game": {"totalSessions": 0, "hits": []},
    }
    base.update(over)
    return json.dumps(base, ensure_ascii=False)


def _body(snapshot=None, **over):
    kwargs = dict(
        msisdn=MSISDN, start=START, end=END,
        verdict_auto="系统判定：未复现语音异常",
        verdict_manual="小区今晚割接，非网络质量问题",
        reason="该小区今晚在割接，用户侧信号正常",
        # 入参叫 snapshot（后端 OverrideIn.snapshot），落库列/回读字段是 verdict_snapshot
        snapshot=snapshot,
    )
    kwargs.update(over)
    return R.OverrideIn(**kwargs)


# ---------------------------------------------------------------- 迁移
def test_legacy_table_migration_is_idempotent(monkeypatch, tmp_path):
    """老库补列：历史行保留、快照为 NULL、重复执行不报错。"""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(LEGACY_DDL)
    conn.execute(
        f"INSERT INTO {R.TABLE} (username, msisdn_mask, window_start, window_end, "
        "verdict_auto, verdict_manual, reason, created_at, updated_at, revoked_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        ("alice", R.mask_msisdn(MSISDN), START, END,
         "历史系统判定", "历史覆写", "历史理由足够十个字以上", "2026-10-01 00:00:00",
         "2026-10-01 00:00:00"),
    )
    conn.commit()
    conn.close()
    assert "verdict_snapshot" not in _cols(path), "前置条件写错：老表不该有快照列"

    _use_sqlite(monkeypatch, path)
    # 连跑两次 —— 第二次必须幂等（真实请求每次都会调 _ensure_table）
    for _ in range(2):
        with R.get_raw_connection() as c:
            R._ensure_table(c)

    assert "verdict_snapshot" in _cols(path)
    rows = _rows(path)
    assert len(rows) == 1, "迁移不得丢历史行"
    assert rows[0]["verdict_manual"] == "历史覆写"
    assert rows[0]["verdict_snapshot"] is None, "老行快照应为 NULL（视为当时未存档）"

    # 老行照常可读（GET 不因新列为空而报错）
    got = R.get_override(msisdn=MSISDN, start=START, end=END, user=USER)
    assert got["data"]["verdict_snapshot"] is None
    assert got["data"]["id"] == rows[0]["id"]


# ---------------------------------------------------------------- 往返
def test_post_works_on_legacy_db_after_lazy_migration(monkeypatch, tmp_path):
    """真实场景：老库（无快照列）上直接提交覆写 —— 补列发生在同一个请求里。

    只测 `_ensure_table` 不够：生产上用户第一次提交覆写时才会触发迁移，
    若 POST 的顺序/占位符有误（例如 INSERT 列数与值数不匹配），只有这条能抓到。
    """
    path = tmp_path / "legacy_post.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(LEGACY_DDL)
    conn.commit()
    conn.close()
    assert "verdict_snapshot" not in _cols(path)

    _use_sqlite(monkeypatch, path)
    snap = _snapshot()
    out = R.submit_override(_body(snap), user=USER)
    assert out["data"]["verdict_snapshot"] == snap
    assert "verdict_snapshot" in _cols(path)


def test_snapshot_roundtrip_through_post_get_history(monkeypatch, tmp_path):
    """POST 写入的快照，GET 与 history 都要原样回读；号码仍只以脱敏形式落库。"""
    path = tmp_path / "roundtrip.db"
    _use_sqlite(monkeypatch, path)
    snap = _snapshot()

    created = R.submit_override(_body(snap), user=USER)
    assert created["data"]["verdict_snapshot"] == snap
    assert created["data"]["msisdn_mask"] == R.mask_msisdn(MSISDN)

    got = R.get_override(msisdn=MSISDN, start=START, end=END, user=USER)
    assert got["data"]["verdict_snapshot"] == snap

    # history 的 limit 是 FastAPI Query 默认值，直接调函数时必须显式传值
    hist = R.list_history(msisdn=MSISDN, limit=20, user=USER)
    assert len(hist["data"]) == 1
    assert hist["data"][0]["verdict_snapshot"] == snap

    # 号码明文不得出现在任何列里（快照本身也只存计数，不存原始话单）
    row_text = json.dumps(_rows(path)[0], ensure_ascii=False, default=str)
    assert MSISDN not in row_text
    assert R.mask_msisdn(MSISDN) in row_text


# ---------------------------------------------------------------- 校验
def test_oversized_snapshot_rejected_with_human_message(monkeypatch, tmp_path):
    """> 20KB（按 UTF-8 字节）→ 422，且不落半条记录。"""
    path = tmp_path / "oversize.db"
    _use_sqlite(monkeypatch, path)
    big = json.dumps({"version": 1, "blob": "x" * (R.MAX_SNAPSHOT_BYTES + 1)})

    with pytest.raises(HTTPException) as ei:
        R.submit_override(_body(big), user=USER)
    assert ei.value.status_code == 422
    assert "20KB" in ei.value.detail
    assert _rows(path) == [], "校验失败的请求不得留下半条覆写记录"


def test_non_object_or_invalid_json_rejected(monkeypatch, tmp_path):
    """快照必须是 JSON 对象：数组 / 纯文本都 422（存进去要能被审计端解析）。"""
    path = tmp_path / "badjson.db"
    _use_sqlite(monkeypatch, path)
    for bad in ("not a json", "[1, 2, 3]"):
        with pytest.raises(HTTPException) as ei:
            R.submit_override(_body(bad), user=USER)
        assert ei.value.status_code == 422
    assert _rows(path) == []


# ---------------------------------------------------------------- 更新语义
def test_update_without_snapshot_keeps_existing(monkeypatch, tmp_path):
    """只改理由/结论、不带快照时，已有快照必须保留（COALESCE 语义）。"""
    path = tmp_path / "keep.db"
    _use_sqlite(monkeypatch, path)
    snap = _snapshot()
    R.submit_override(_body(snap), user=USER)

    updated = R.submit_override(
        _body(None, verdict_manual="割接已结束，仍非网络质量问题",
              reason="割接结束后复测仍正常，判定非网络质量问题"),
        user=USER,
    )
    assert updated["data"]["verdict_snapshot"] == snap, "不带快照的更新把审计依据清空了"
    assert updated["data"]["verdict_manual"] == "割接已结束，仍非网络质量问题"
    assert len(_rows(path)) == 1, "同一 (用户, 号码, 窗口) 应更新同一行而不是新增"


def test_update_with_new_snapshot_replaces(monkeypatch, tmp_path):
    """重新提交并带新快照时，覆盖为本次快照（与 verdict_auto 同一语义）。"""
    path = tmp_path / "replace.db"
    _use_sqlite(monkeypatch, path)
    old = _snapshot(generated_at="2026-11-07T10:05:00.000Z")
    new = _snapshot(generated_at="2026-11-07T11:30:00.000Z")
    R.submit_override(_body(old), user=USER)
    out = R.submit_override(_body(new), user=USER)
    assert out["data"]["verdict_snapshot"] == new
