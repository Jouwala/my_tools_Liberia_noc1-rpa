"""email_recovery 三态探测 / 持续故障升级 / 发信任务覆盖 —— 回归测试。

覆盖 2026-09-18 那次 65 小时邮件全故障后新增的逻辑：

  1. EWS 故障分三类（server_down / auth_error / cred_mismatch），不再混为一谈
  2. 持续故障升级告警：翻转通知之外，超过阈值周期性再提醒（原方案会永久静默）
  3. 不可补发失败（子进程超时 / BUDGET_EXCEEDED）不得进入补发链
  4. EWS 发信任务集合自动推导，且每个任务都有补发分发分支
  5. PG→SQLite 同步必须跳过本地权威表（credentials）—— 否则设置页密码每小时被抹掉
  6. mailbox_cleanup 必须区分"邮箱为空"与"所有文件夹读取失败"

全部离线：不发真实邮件、不连 EWS、不改线上 app.db。
运行：
    cd D:/01_RPA/Task/my_app
    python -m pytest tests/test_email_recovery_states.py -q
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services import email_recovery as er  # noqa: E402
from backend.services import email_task_coverage as etc  # noqa: E402
from backend.scripts import sync_pg_to_sqlite as sps  # noqa: E402


# ---------------------------------------------------------------- 三态状态机

def _run_probe_sequence(monkeypatch, kinds, hours):
    """按脚本回放探测结果，返回每次的 _probe_and_track 结果。"""
    seq = list(kinds)
    monkeypatch.setattr(er, "probe_ews_reachable", lambda: (seq.pop(0), "scripted"))
    t0 = datetime(2026, 9, 18, 0, 0, 0)
    state: dict = {}
    return [er._probe_and_track(state, t0 + timedelta(hours=h)) for h in hours], state


def test_first_fault_reports_transition_then_stays_silent(monkeypatch):
    results, state = _run_probe_sequence(
        monkeypatch,
        [er.PROBE_SERVER_DOWN, er.PROBE_SERVER_DOWN, er.PROBE_SERVER_DOWN],
        [0, 1, 2],
    )
    assert results[0]["transition"] == "went_server_down"
    assert results[0]["fault_count"] == 1
    # 同一故障持续期间不再翻转通知（防刷屏）
    assert results[1]["transition"] is None
    assert results[2]["transition"] is None
    assert results[2]["fault_count"] == 3
    assert state[er.EWS_STATE_KEY]["kind"] == er.PROBE_SERVER_DOWN


def test_fault_kind_change_is_a_transition(monkeypatch):
    """server_down → auth_error 是重要信息（需人工介入），必须通知。"""
    results, _ = _run_probe_sequence(
        monkeypatch,
        [er.PROBE_SERVER_DOWN, er.PROBE_AUTH_ERROR],
        [0, 1],
    )
    assert results[0]["transition"] == "went_server_down"
    assert results[1]["transition"] == "changed_fault"
    assert results[1]["kind"] == er.PROBE_AUTH_ERROR


def test_recovery_resets_fault_count(monkeypatch):
    results, state = _run_probe_sequence(
        monkeypatch,
        [er.PROBE_SERVER_DOWN, er.PROBE_SERVER_DOWN, er.PROBE_OK],
        [0, 1, 2],
    )
    assert results[2]["transition"] == "recovered"
    assert results[2]["fault_count"] == 0
    assert state[er.EWS_STATE_KEY]["status"] == "up"


# ------------------------------------------------------- 持续故障升级告警

def test_escalation_fires_after_threshold_then_respects_interval(monkeypatch):
    """原方案只有翻转通知 → 密码失效 65 小时全程静默；现在必须周期性再叫醒人。"""
    monkeypatch.setattr(er, "_ESCALATE_AFTER_HOURS", 6.0)
    monkeypatch.setattr(er, "_ESCALATE_EVERY_HOURS", 24.0)
    down = er.PROBE_SERVER_DOWN
    results, _ = _run_probe_sequence(
        monkeypatch,
        [down, down, down, down, down, down],
        [0, 1, 7, 8, 32, 33],
    )
    escalations = [r["escalate"] for r in results]
    #            +0h    +1h    +7h    +8h    +32h   +33h
    assert escalations == [False, False, True, False, True, False]


def test_no_escalation_while_healthy(monkeypatch):
    results, _ = _run_probe_sequence(
        monkeypatch, [er.PROBE_OK, er.PROBE_OK], [0, 100],
    )
    assert [r["escalate"] for r in results] == [False, False]


# ------------------------------------------------------------ 通知文案分流

def _capture_notifications(monkeypatch):
    calls = []
    monkeypatch.setattr(
        er, "_notify_ews_state",
        lambda kind, msg, escalate=False: calls.append(
            {"kind": kind, "escalate": escalate, "msg": msg}),
    )
    return calls


def _fake_summary(kind, transition, escalate):
    return {
        "recovered": 0, "attempted": 0, "skipped": 0, "expired": 0,
        "reason": "ews_down", "ews_kind": kind,
        "ews_detail": "HTTP 401（NTLM 认证被拒）",
        "ews_transition": transition, "ews_escalate": escalate,
        "ews_down_count": 3, "ews_down_since": "2026-09-18T12:00:00",
    }


def test_auth_error_message_points_at_settings_page(monkeypatch):
    """2026-09-18 的教训：旧文案写"连接 exchmail 超时…已静默"，把人引向"等服务端恢复"。"""
    calls = _capture_notifications(monkeypatch)
    monkeypatch.setattr(er, "recover_failed_emails",
                        lambda: _fake_summary(er.PROBE_AUTH_ERROR, "went_auth_error", False))
    summary = er.run_email_recovery_task()
    assert summary["success"] is True          # 依赖故障不算任务失败
    assert "需人工" in summary["message"]
    assert "设置" in summary["message"]
    assert calls and calls[0]["kind"] == er.PROBE_AUTH_ERROR
    assert "人工介入" in calls[0]["msg"]


def test_server_down_message_does_not_claim_credentials(monkeypatch):
    calls = _capture_notifications(monkeypatch)
    monkeypatch.setattr(er, "recover_failed_emails",
                        lambda: _fake_summary(er.PROBE_SERVER_DOWN, "went_down", False))
    summary = er.run_email_recovery_task()
    assert summary["success"] is True
    assert "凭据" not in summary["message"]
    assert calls[0]["kind"] == er.PROBE_SERVER_DOWN


def test_escalation_notification_is_marked(monkeypatch):
    calls = _capture_notifications(monkeypatch)
    monkeypatch.setattr(er, "recover_failed_emails",
                        lambda: _fake_summary(er.PROBE_AUTH_ERROR, None, True))
    summary = er.run_email_recovery_task()
    assert "升级" in summary["message"]
    assert calls and calls[0]["escalate"] is True
    assert "持续故障" in calls[0]["msg"]


# --------------------------------------------------------- 不可补发失败判定

def test_subprocess_timeout_is_not_treated_as_resendable_ews_failure():
    """`timed out after` 是本地杀子进程，补发会造成重复发送。"""
    timeout_err = ("timeout: Command '['C:\\...\\python.exe', 'owa_mail_report.py']' "
                   "timed out after 120 seconds")
    assert any(k in timeout_err for k in er.NOT_RESENDABLE_KEYS)
    # 真·EWS 网络失败仍应可补发
    ews_err = "returncode=3 ... Unable to connect to the remote server"
    assert not any(k in ews_err for k in er.NOT_RESENDABLE_KEYS)
    assert any(k in ews_err for k in er.EWS_FAIL_KEYS)


# ------------------------------ auto_retry 与补发通道的判据必须一致（防互相谦让）

def test_is_ews_resendable_classification():
    assert er.is_ews_resendable("TransportError: Unable to connect to the remote server")
    assert er.is_ews_resendable("RateLimitError: Max timeout reached")
    assert er.is_ews_resendable("ErrorSendItem: SOAP error")
    # 非 EWS 失败：留给 auto_retry
    assert not er.is_ews_resendable("[WinError 10065] No route to host")
    assert not er.is_ews_resendable("timed out after 180 seconds")
    assert not er.is_ews_resendable("BUDGET_EXCEEDED: 已转后台")
    assert not er.is_ews_resendable("")


def test_non_ews_failure_of_email_task_is_still_auto_retried():
    """回归：fw_kpi_sync 进 EMAIL_TASK_IDS 后，其远端 API 连接失败不能被两边谦让掉。

    历史证据：2026-09-18 09:00:40 `[WinError 10060]` 失败 → 10:07:41
    `trig=auto_retry ok=1` 恢复。补发通道只看 EWS_FAIL_KEYS，不会管这类失败。
    """
    from backend.services import auto_retry as ar
    assert ar._is_excluded_from_retry("fw_kpi_sync", "[WinError 10065] No route to host") is False
    assert ar._is_excluded_from_retry("fw_kpi_sync", "timed out after 180 seconds") is False
    assert ar._is_excluded_from_retry("liberia_email_1h", "[WinError 10065]") is False


def test_ews_failure_of_email_task_is_deferred_to_recovery():
    """EWS 失败必须让给补发通道，否则 auto_retry 重跑会重复发送。"""
    from backend.services import auto_retry as ar
    assert ar._is_excluded_from_retry(
        "fw_kpi_sync", "TransportError: Unable to connect to the remote server") is True
    assert ar._is_excluded_from_retry("liberia_email_1h", "SOAP SendItem failed") is True


def test_auto_retry_self_and_non_email_tasks_unaffected():
    from backend.services import auto_retry as ar
    assert ar._is_excluded_from_retry("auto_retry_failed", "anything") is True
    assert ar._is_excluded_from_retry("eflow_sync", "[WinError 10065]") is False
    # 漏跑扫描拿不到失败原因 → 维持任务级粗排除
    assert ar._is_excluded_from_retry("fw_kpi_sync", None) is True
    assert "fw_kpi_sync" in ar._exclude_task_ids()


def test_include_email_env_escape_hatch(monkeypatch):
    from backend.services import auto_retry as ar
    monkeypatch.setenv("AUTO_RETRY_INCLUDE_EMAIL", "1")
    assert ar._email_task_ids() == set()
    assert ar._is_excluded_from_retry("fw_kpi_sync", "TransportError") is False


# ---------------------------------------------------- 发信任务集合与分发覆盖

def test_derived_tasks_include_known_email_tasks():
    discovered = etc.discover_email_tasks()
    for must in ("liberia_email_1h", "liberia_email_8h", "fw_kpi_sync",
                 "ume_in_osg_report", "sp_material_report", "battery_email"):
        assert must in discovered, f"{must} 未被推导为 EWS 发信任务"


def test_derived_tasks_exclude_non_email_tasks():
    """只生成 / 只同步 / 走 126 SMTP 的任务不得被误判。"""
    discovered = etc.discover_email_tasks()
    for must_not in ("sp_report_generate", "sp_online_report_generate",
                     "sp_whatsapp_report", "battery_kpi_sync",
                     "mailbox_cleanup", "email_recovery"):
        assert must_not not in discovered, f"{must_not} 被误判为 EWS 发信任务"


def test_every_email_task_has_a_dispatch_entry():
    """推导会持续带出新任务；没有分发分支就会静默无法补发。"""
    assert er._UNDISPATCHED_EMAIL_TASKS == []
    assert set(er.EMAIL_TASK_IDS) == set(er._TASK_DISPATCH)


def test_explicit_list_is_subset_of_effective_list():
    assert er._EXPLICIT_EMAIL_TASK_IDS <= set(er.EMAIL_TASK_IDS)


# ------------------------------------------- PG→SQLite 同步不得抹掉本地权威表

def test_local_authoritative_tables_are_skipped_by_sync():
    """P0：app.credentials 在 PG 里是空壳，同步却会 DROP 掉 SQLite 侧的凭据表。"""
    assert "credentials" in sps.SKIP_TABLES
    assert "email_recipients" in sps.SKIP_TABLES
    # app schema 映射为无前缀表名 —— 这正是"空壳 PG 表清空本地表"的原因
    assert sps.sanitize_table_name("app", "credentials") == "credentials"


def test_sync_skips_credentials_without_touching_connections():
    """跳过必须在拿连接之前短路，否则会 DROP 掉本地表。"""
    assert sps.sync_table(None, None, "app", "credentials") == 0


def test_dual_mode_tables_are_not_skipped():
    """issue_reports 走 get_raw_connection 双模，pg 模式下 PG 才是权威，不能跳过。"""
    assert "issue_reports" not in sps.SKIP_TABLES


# ------------------------------------------- mailbox_cleanup 不得假绿

def test_mailbox_all_folders_failed_is_an_error(monkeypatch):
    from backend.services import mailbox_cleanup as mc
    monkeypatch.setattr(mc, "get_account", lambda: object())
    monkeypatch.setattr(mc, "get_total_count", lambda acct: (0, ["inbox", "sent"]))
    result = mc.run_mailbox_cleanup()
    assert result["success"] is False
    assert result["reason"] == "count_unavailable"


def test_mailbox_genuinely_empty_is_ok(monkeypatch):
    from backend.services import mailbox_cleanup as mc
    monkeypatch.setattr(mc, "get_account", lambda: object())
    monkeypatch.setattr(mc, "get_total_count", lambda acct: (0, []))
    result = mc.run_mailbox_cleanup()
    assert result["success"] is True
    assert result["reason"] == "count_under_threshold"


def test_mailbox_partial_read_failure_is_reported(monkeypatch):
    from backend.services import mailbox_cleanup as mc
    monkeypatch.setattr(mc, "get_account", lambda: object())
    monkeypatch.setattr(mc, "get_total_count", lambda acct: (120, ["sent"]))
    result = mc.run_mailbox_cleanup()
    assert result["success"] is True
    assert result["failed_folders"] == ["sent"]
    assert "读取失败" in result["message"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
