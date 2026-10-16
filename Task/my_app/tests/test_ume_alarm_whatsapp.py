# -*- coding: utf-8 -*-
"""ZTE UME 告警推送单测：配置解析、筛选口径、去重/状态表、消息渲染。

对应 `backend/services/ume_alarm_config.py` / `ume_alarm_store.py` /
`ume_alarm_whatsapp_service.py`。不发真实网络请求（客户端在测试里被替身替换）。

锁的是三类**极易踩**的错：
  1. 「留空 = 不过滤」被记反成「留空 = 全丢」（`in set()` 恒 False）；
  2. 告警码多形态（`89069` / `3305119853` / `89069.0`）判等漏掉；
  3. bootstrap「首轮只登记不发送」失效，上线瞬间把存量刷进群。
"""
import json

import pytest

from backend.services import ume_alarm_client as CL
from backend.services import ume_alarm_config as C
from backend.services import ume_alarm_store as store
from backend.services import ume_alarm_whatsapp_service as S
from backend.services.ume_alarm_client import norm_alarm_code


def _p(conf, env=None):
    return C.parse_config(conf, norm_alarm_code, env or {})


# ---------------- 配置解析 ----------------

def test_defaults_when_nothing_configured():
    got = _p({}, {})
    assert got["alarm_pairs"] == {("89029", "major"), ("89006", "major")}
    assert got["groups"] == C.DEFAULT_GROUPS
    assert got["groups_fallback"] is True
    assert got["resend_minutes"] == C.DEFAULT_RESEND_MINUTES
    assert got["bootstrap"] is True


def test_norm_pairs_parses_code_level():
    got = _p({"alarm_pairs": "89029:major, 89006:MAJOR "}, {})
    assert got["alarm_pairs"] == {("89029", "major"), ("89006", "major")}


def test_norm_pairs_skips_bad_entries():
    # 缺冒号的条目跳过，但不整条丢（否则一处分号错误会放开全部告警）
    got = _p({"alarm_pairs": "89029:major, garbage"}, {})
    assert got["alarm_pairs"] == {("89029", "major")}


def test_alarm_code_normalizes_float_tail():
    got = _p({"alarm_codes": "89069, 89006.0 "}, {})
    assert got["alarm_codes"] == {"89069", "89006"}


def test_empty_string_in_file_means_no_filter_not_drop_all():
    """配置文件里显式写空串 = 用户清空白名单 = 不过滤。"""
    got = _p({"alarm_codes": "", "alarm_levels": ""}, {})
    assert got["alarm_codes"] == set()
    assert got["alarm_levels"] == set()


def test_env_wins_over_file():
    got = _p({"resend_minutes": 30, "groups": "fromfile"},
             {"UME_ALARM_RESEND_MINUTES": "5", "UME_ALARM_WHATSAPP_GROUPS": "fromenv"})
    assert got["resend_minutes"] == 5
    assert got["resend_from"] == "env"
    assert got["groups"] == ["fromenv"]
    assert got["groups_from"] == "env"


def test_bool_false_in_file_is_respected():
    """JSON 里布尔 false 不能被当成"没配置"退回默认（truthy 的老坑）。"""
    got = _p({"bootstrap": False}, {})
    assert got["bootstrap"] is False


# ---------------- 筛选口径（码 且 级别） ----------------

def _alarm(code, level):
    return {"alarm_id": "id-" + code + level, "alarm_code": code, "level": level}


def test_matches_exact_pairs_only(monkeypatch):
    """精确「码:级别」对 —— 不做笛卡尔积，89029+critical 不应命中。"""
    monkeypatch.setattr(S, "ALARM_PAIRS",
                        {("89029", "major"), ("89006", "major")})
    monkeypatch.setattr(S, "ALARM_CODES", set())
    monkeypatch.setattr(S, "ALARM_LEVELS", set())
    assert S.matches(_alarm("89029", "major")) is True
    assert S.matches(_alarm("89006", "major")) is True
    assert S.matches(_alarm("89029", "critical")) is False   # 码对、级别不对
    assert S.matches(_alarm("89006", "warning")) is False
    assert S.matches(_alarm("89069", "major")) is False       # 级别对、码不对


def test_matches_falls_back_to_sets_when_no_pairs(monkeypatch):
    """未配 pairs 时回退旧口径：码集合 ∩ 级别集合。"""
    monkeypatch.setattr(S, "ALARM_PAIRS", set())
    monkeypatch.setattr(S, "ALARM_CODES", {"89069"})
    monkeypatch.setattr(S, "ALARM_LEVELS", {"major"})
    assert S.matches(_alarm("89069", "major")) is True
    assert S.matches(_alarm("89069", "critical")) is False


def test_matches_empty_whitelist_means_no_filter(monkeypatch):
    """pairs 与 codes/levels 都留空 = 不过滤（**不是**全丢）。"""
    monkeypatch.setattr(S, "ALARM_PAIRS", set())
    monkeypatch.setattr(S, "ALARM_CODES", set())
    monkeypatch.setattr(S, "ALARM_LEVELS", set())
    assert S.matches(_alarm("99999", "warning")) is True


def test_matches_normalizes_code_shape(monkeypatch):
    monkeypatch.setattr(S, "ALARM_PAIRS", {("89069", "major")})
    monkeypatch.setattr(S, "ALARM_CODES", set())
    monkeypatch.setattr(S, "ALARM_LEVELS", set())
    assert S.matches(_alarm("89069.0", "major")) is True


# ---------------- 消息渲染 ----------------

def test_build_alarm_message_has_title_and_fields():
    txt = S.build_alarm_message(
        {"alarm_code": "89069", "level": "major", "object": "NODE-1",
         "description": "disk bad", "occur_time": "2026-10-16 10:00:00"}, 1)
    assert S.PUSH_TITLE in txt
    assert "89069" in txt and "major" in txt and "NODE-1" in txt
    assert "REMINDER" not in txt  # 首推无横幅


def test_build_alarm_message_reminder_banner():
    txt = S.build_alarm_message(
        {"alarm_code": "89069", "level": "major", "object": "NODE-1"}, 3, 25)
    assert "REMINDER #3" in txt
    assert "open 25m" in txt


def test_build_recover_message():
    txt = S.build_recover_message("k1", {
        "alarm_code": "89029", "level": "critical", "object": "NODE-9",
        "first_seen_time": "2026-10-16 09:00:00"})
    assert S.RECOVER_TITLE in txt
    assert "89029" in txt and "NODE-9" in txt


# ---------------- 状态表（sqlite 内存库，避免依赖生产 PG） ----------------

@pytest.fixture()
def conn():
    import sqlite3
    c = sqlite3.connect(":memory:")
    store.ensure_log_table(c)
    yield c
    c.close()


def test_ensure_log_table_idempotent(conn):
    store.ensure_log_table(conn)  # 再建一次不应报错
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ume_alarm_whatsapp_log)")}
    assert "alarm_key" in cols
    assert "bootstrapped" in cols
    assert "recover_notified" in cols


def test_record_send_ok_sets_y_and_increments(conn):
    row = {"alarm_id": "a1", "alarm_code": "89029", "level": "major",
           "object": "N1", "occur_time": "2026-10-16 10:00:00"}
    rec = store.record_send(conn, row, ok=True)
    assert rec["send_status"] == "Y"
    assert rec["send_count"] == 1
    rec2 = store.record_send(conn, row, ok=True, existing=rec)
    assert rec2["send_count"] == 2


def test_record_send_fail_keeps_status_and_count(conn):
    row = {"alarm_id": "a2", "alarm_code": "89029", "level": "major", "object": "N2"}
    store.record_send(conn, row, ok=True)
    rec = store.load_records(conn, ["a2"])["a2"]
    # 失败一次：send_status 不应被抹成 N、send_count 不增
    store.record_send(conn, row, ok=False, error="offline", existing=rec)
    rec2 = store.load_records(conn, ["a2"])["a2"]
    assert rec2["send_status"] == "Y"
    assert rec2["send_count"] == 1
    assert "offline" in rec2["last_error"]


def test_mark_bootstrapped_and_recover(conn):
    row = {"alarm_id": "b1", "alarm_code": "89029", "level": "major", "object": "NB"}
    store.touch_seen(conn, row)
    store.mark_bootstrapped(conn, "b1")
    rec = store.load_records(conn, ["b1"])["b1"]
    assert rec["bootstrapped"] == "Y"
    store.mark_recover_notified(conn, "b1")
    rec2 = store.load_records(conn, ["b1"])["b1"]
    assert rec2["recover_notified"] == "Y"


def test_load_open_records_excludes_cleared_and_recovered(conn):
    for k in ("o1", "o2", "o3"):
        store.touch_seen(conn, {"alarm_id": k, "alarm_code": "1", "level": "major"})
    store.mark_cleared(conn, "o1")
    store.mark_recover_notified(conn, "o2")
    open_keys = set(store.load_open_records(conn).keys())
    assert "o1" not in open_keys   # 已清除
    assert "o2" not in open_keys   # 已发恢复
    assert "o3" in open_keys


# ---------------- 服务编排：bootstrap 与首推决策（替身客户端） ----------------

def _run_with(monkeypatch, alarms, tmp_conn, bootstrap):
    """用内存库 + 替身客户端跑一轮 run_ume_alarm_whatsapp。"""
    import sqlite3
    store.ensure_log_table(tmp_conn)
    monkeypatch.setattr(S, "BOOTSTRAP", bootstrap)
    monkeypatch.setattr(S, "get_raw_connection", lambda *a, **k: _CM(tmp_conn))
    monkeypatch.setattr(S.client, "fetch_alarms",
                        lambda *a, **k: {"alarms": alarms, "total": len(alarms),
                                         "fetched": len(alarms), "truncated": False,
                                         "pages": 1})
    monkeypatch.setattr(S, "dispatch", lambda msgs, groups: {
        "ok": True, "job_id": "job1", "dispatched": len(msgs), "errors": []})
    monkeypatch.setattr(S, "wait_for_job_result", lambda jid, timeout=None: {
        "ok": True, "confirmed": True, "sent": [m["tt_no"] for m in _LAST_MSGS["m"]],
        "message_ids": {}, "errors": [], "timed_out": False})
    monkeypatch.setattr(S.wa_notify, "check_channel_before_dispatch",
                        lambda out, due, mins: None)
    monkeypatch.setattr(S, "GROUPS_FALLBACK", False)


class _CM:
    """极简上下文管理器（不关闭共享内存连接）。"""
    def __init__(self, c):
        self.c = c

    def __enter__(self):
        return self.c

    def __exit__(self, *a):
        return False


_LAST_MSGS = {"m": []}


def test_bootstrap_registers_without_sending(monkeypatch):
    import sqlite3
    conn = sqlite3.connect(":memory:")
    store.ensure_log_table(conn)
    # 捕获 dispatch 实参
    sent = []
    monkeypatch.setattr(S, "BOOTSTRAP", True)
    monkeypatch.setattr(S, "get_raw_connection", lambda *a, **k: _CM(conn))
    monkeypatch.setattr(S.client, "fetch_alarms",
                        lambda *a, **k: {"alarms": [_alarm("89029", "major")],
                                         "total": 1, "fetched": 1,
                                         "truncated": False, "pages": 1})
    monkeypatch.setattr(S, "dispatch",
                        lambda msgs, groups: sent.append(msgs) or {
                            "ok": True, "job_id": "j", "dispatched": len(msgs),
                            "errors": []})
    monkeypatch.setattr(S.wa_notify, "check_channel_before_dispatch",
                        lambda out, due, mins: None)
    monkeypatch.setattr(S, "GROUPS_FALLBACK", False)
    out = S.run_ume_alarm_whatsapp()
    assert out["bootstrap_registered"] == 1
    assert sent == []  # 首轮不发
    rec = store.load_records(conn, ["id-89029major"])["id-89029major"]
    assert rec["bootstrapped"] == "Y"
    conn.close()


# ---------------- 会话缓存（防止每分钟重登触发上游 gvcode 验证码） ----------------

def test_login_reuses_cached_session(monkeypatch):
    """第二次 login 命中缓存时**不得**再走密码登录（否则每分钟一轮会撞上游验证码）。"""
    CL._clear_session_cache()
    login_calls = []

    monkeypatch.setattr(CL, "_keystone_login",
                        lambda u, p: login_calls.append(1) or {
                            "cookie": "c", "unscoped_token": "u"})
    monkeypatch.setattr(CL, "_resolve_project_id", lambda *a, **k: "pid")
    monkeypatch.setattr(CL, "_fetch_project_token", lambda *a, **k: "ptok")
    monkeypatch.setattr(CL, "_session_usable", lambda s: True)

    s1 = CL.login("admin")
    s2 = CL.login("admin")
    assert s1 == s2
    assert len(login_calls) == 1  # 只真登录了一次


def test_login_force_refresh_bypasses_cache(monkeypatch):
    CL._clear_session_cache()
    login_calls = []
    monkeypatch.setattr(CL, "_keystone_login",
                        lambda u, p: login_calls.append(1) or {
                            "cookie": "c", "unscoped_token": "u"})
    monkeypatch.setattr(CL, "_resolve_project_id", lambda *a, **k: "pid")
    monkeypatch.setattr(CL, "_fetch_project_token", lambda *a, **k: "ptok")
    monkeypatch.setattr(CL, "_session_usable", lambda s: True)

    CL.login("admin")
    CL.login("admin", force_refresh=True)
    assert len(login_calls) == 2  # force 跳过缓存


def test_login_relogins_when_cached_session_dead(monkeypatch):
    CL._clear_session_cache()
    login_calls = []
    monkeypatch.setattr(CL, "_keystone_login",
                        lambda u, p: login_calls.append(1) or {
                            "cookie": "c", "unscoped_token": "u"})
    monkeypatch.setattr(CL, "_resolve_project_id", lambda *a, **k: "pid")
    monkeypatch.setattr(CL, "_fetch_project_token", lambda *a, **k: "ptok")
    # 缓存探活失败 → 第二次 login 应作废缓存并重登
    monkeypatch.setattr(CL, "_session_usable", lambda s: False)

    CL.login("admin")                 # 首次：无缓存，真登录
    CL.login("admin")                 # 探活 False → 重登
    assert len(login_calls) == 2
