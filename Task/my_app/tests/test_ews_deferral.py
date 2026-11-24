# -*- coding: utf-8 -*-
"""邮箱通道降级时的「延后执行」门禁（services/ews_deferral.py）回归测试。

要锁住的行为（2026-11-18 用户要求）：

  1. 通道**已确认不可用**且探测足够新时，纯发信任务在定时触发下**不执行**；
  2. 通道正常 / 探测过期 / 手动触发 / 未标注任务 → 一律照常执行（fail-open）；
  3. 延后记录带 ``EWS_DEFERRED`` 标记，能被 email_recovery 识别为「恢复后要补」，
     且不会被 auto_retry 当成普通失败重投（否则降级期间又空跑一轮）；
  4. 注册表里**只**给纯发信任务标注，带同步 / WhatsApp 副通道的任务不得标注。

全部离线：不连 EWS、不发邮件、不写线上 DB。
运行：
    cd D:/01_RPA/Task/my_app
    python -m pytest tests/test_ews_deferral.py -q
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services import ews_deferral as ed  # noqa: E402
from backend.services import email_recovery as er  # noqa: E402


def _probe(status="down", kind="server_down", minutes_ago=2, detail="HTTP 401（NTLM 认证被拒）"):
    return {
        "status": status,
        "kind": kind,
        "detail": detail,
        "last_probe_at": (datetime.now() - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds"),
    }


@pytest.fixture
def deferrable_task():
    return {
        "task_id": "liberia_email_1h",
        "name": "Liberia 宕站 1小时报告邮件",
        "category": "email",
        "defer_on_ews_down": True,
    }


def _patch_probe(monkeypatch, probe):
    monkeypatch.setattr(ed, "_read_probe", lambda: probe)


# ------------------------------------------------------------ 门禁判定

def test_defers_when_channel_down_and_probe_fresh(monkeypatch, deferrable_task):
    _patch_probe(monkeypatch, _probe(kind="server_down"))
    res = ed.maybe_defer(deferrable_task, "scheduled")
    assert res is not None
    assert res["success"] is False and res["deferred"] is True
    assert res["ews_kind"] == "server_down"
    assert ed.DEFERRED_MARKER in res["error"]


def test_auth_error_also_defers(monkeypatch, deferrable_task):
    """凭据被拒同样发不出去；不能因为不是 server_down 就继续空跑。"""
    _patch_probe(monkeypatch, _probe(kind="auth_error"))
    assert ed.maybe_defer(deferrable_task, "scheduled") is not None


def test_no_defer_when_channel_up(monkeypatch, deferrable_task):
    _patch_probe(monkeypatch, _probe(status="up", kind="ok"))
    assert ed.maybe_defer(deferrable_task, "scheduled") is None


def test_stale_probe_fails_open(monkeypatch, deferrable_task):
    """探测过期（email_recovery 被堵住等）时不许凭旧结论静默跳过。"""
    _patch_probe(monkeypatch, _probe(minutes_ago=ed._MAX_PROBE_AGE_MIN + 5))
    assert ed.maybe_defer(deferrable_task, "scheduled") is None


def test_missing_last_probe_at_fails_open(monkeypatch, deferrable_task):
    _patch_probe(monkeypatch, {"status": "down", "kind": "server_down"})
    assert ed.maybe_defer(deferrable_task, "scheduled") is None


def test_manual_trigger_is_never_deferred(monkeypatch, deferrable_task):
    """人可能刚改完密码要立刻验证；手动触发必须照常执行。"""
    _patch_probe(monkeypatch, _probe())
    assert ed.maybe_defer(deferrable_task, "manual") is None


def test_unflagged_task_is_not_deferred(monkeypatch):
    _patch_probe(monkeypatch, _probe())
    task = {"task_id": "fw_kpi_sync", "defer_on_ews_down": False}
    assert ed.maybe_defer(task, "scheduled") is None


def test_env_kill_switch(monkeypatch, deferrable_task):
    _patch_probe(monkeypatch, _probe())
    monkeypatch.setenv("EWS_DEFER_ON_DOWN", "0")
    assert ed.maybe_defer(deferrable_task, "scheduled") is None


def test_missing_state_fails_open(monkeypatch, deferrable_task):
    _patch_probe(monkeypatch, None)
    assert ed.maybe_defer(deferrable_task, "scheduled") is None


# ------------------------------------------- 与补发 / 重试通道的衔接

def test_deferred_marker_is_resendable_after_recovery(monkeypatch, deferrable_task):
    _patch_probe(monkeypatch, _probe(detail="ErrorTimeoutExpired: timed out after 300 seconds"))
    res = ed.maybe_defer(deferrable_task, "scheduled")
    # 即便探测详情里带 "timed out after"（本属不可补发关键字），延后记录也必须可补发
    assert er.is_ews_resendable(res["error"]) is True


def test_deferred_record_is_not_auto_retried(monkeypatch, deferrable_task):
    """mailbox_cleanup 不在 EMAIL_TASK_IDS 内，但延后同样不能被 auto_retry 重投。"""
    from backend.services import auto_retry as ar
    _patch_probe(monkeypatch, _probe())
    res = ed.maybe_defer(deferrable_task, "scheduled")
    assert ar._is_excluded_from_retry("mailbox_cleanup", res["error"]) is True


def test_deferred_record_is_classified_as_ews_dependency():
    """db_freshness 必须把延后记录归为「EWS 依赖类」，否则会按「任务真停摆」逐条告警。

    与 2026-09-18 的教训同源：一次 EWS 故障让 14 个报表任务各自「逾期」刷屏。
    """
    from backend.services.db_freshness_check import (
        _dependency_source, _is_dependency_failure,
    )

    err = "EWS_DEFERRED: 邮箱通道未恢复（server_down，最后探测 2026-11-18T14:40:00）"
    assert _dependency_source(err) == "ews"
    assert _is_dependency_failure(err) is True


# ------------------------------------------------- 注册表标注范围（防误标）

def test_registry_marks_only_pure_senders():
    sys.path.insert(0, str(ROOT))
    from backend.task_registry import EWS_DEFERRABLE_IDS, TASK_SPECS

    ids = {s["task_id"] for s in TASK_SPECS}
    stale = EWS_DEFERRABLE_IDS - ids
    assert not stale, f"EWS_DEFERRABLE_IDS 里有不存在的任务: {sorted(stale)}"

    # 纯发信任务应被标注
    for must in ("liberia_email_1h", "kpi_ms_contract", "sp_material_report",
                 "packet_loss_email", "battery_email", "mailbox_cleanup"):
        assert must in EWS_DEFERRABLE_IDS, f"{must} 应可延后"

    # 带同步 / WhatsApp 副通道的任务**不得**标注：延后会停掉同步或群发
    for must_not in ("fw_kpi_sync", "ume_in_osg_report",
                     "sp_email_details", "sp_online_report_send"):
        assert must_not not in EWS_DEFERRABLE_IDS, f"{must_not} 不应整轮延后"


# ------------------------------------------------------ run_task 集成

def test_run_task_defers_without_calling_func(monkeypatch):
    """门禁命中时任务函数一次都不许调用，且不触发失败告警。"""
    from backend.services import task_runner as tr

    called = []
    saved = []
    notified = []

    monkeypatch.setattr(tr, "_refresh_task_schedule_from_db", lambda tid: None)
    monkeypatch.setattr(tr, "_save_task_result", lambda r: saved.append(r))
    monkeypatch.setattr(tr, "notify_task_failure",
                        lambda *a, **k: notified.append(a))
    monkeypatch.setattr(tr, "notify_task_failure_email",
                        lambda *a, **k: notified.append(a))
    _patch_probe(monkeypatch, _probe())

    task_id = "__t_ews_defer"
    tr._task_registry[task_id] = {
        "task_id": task_id,
        "name": "deferred probe",
        "category": "email",
        "enabled": True,
        "func": lambda: called.append(1) or {"success": True},
        "defer_on_ews_down": True,
        "is_test": False,
    }
    try:
        out = tr.run_task(task_id, trigger="scheduled")
    finally:
        tr._task_registry.pop(task_id, None)

    assert called == [], "通道不可用时任务函数不得被执行"
    assert out["deferred"] is True
    assert out["trigger"] == "deferred"
    assert out["success"] is False
    assert ed.DEFERRED_MARKER in out["error"]
    assert notified == [], "延后属于依赖不可用，不应发失败告警"
    assert saved and saved[0]["trigger"] == "deferred"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
