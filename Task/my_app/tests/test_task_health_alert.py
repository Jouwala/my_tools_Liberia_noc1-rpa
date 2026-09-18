"""task_health_alert 离线测试：翻转去重的 6 个场景（不联网、不真发通知）。

运行：
    cd D:/01_RPA/Task/my_app
    python tests/test_task_health_alert.py
"""
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services import task_health_alert as tha  # noqa: E402


class FakeSenders:
    """记录每次通知调用；fail 置 True 时两条通道都返回失败（模拟 SMTP 抖动）。"""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def tuple(self):
        return self._text, self._mail

    def _text(self, text):
        self.calls.append(("wx", text))
        return not self.fail

    def _mail(self, subject, title, message, ts, ok):
        self.calls.append(("mail", subject))
        return not self.fail


def _state():
    return Path(tempfile.mktemp(suffix=".json"))


def _run(senders, findings, now, state):
    return tha.evaluate_and_notify(findings, now=now, state_path=state, senders=senders.tuple())


def test_first_occurrence_notifies_once():
    state = _state()
    s = FakeSenders()
    now = datetime(2026, 9, 18, 9, 0)
    res = _run(s, {"group_missing": ["olib_soc_kpi_daily_sync"]}, now, state)
    assert res["new"] == 1 and res["notified"] is True, res
    assert len(s.calls) == 2, f"应各发一条微信+邮件: {s.calls}"
    assert "olib_soc_kpi_daily_sync" in s.calls[0][1]
    assert "GROUP_TASK_MAP" in s.calls[0][1], "正文必须带下一步处置动作（否则收到的人不知道做什么）"


def test_persistent_issue_stays_silent():
    state = _state()
    s = FakeSenders()
    t0 = datetime(2026, 9, 18, 9, 0)
    _run(s, {"silent": ["vmax_multi_data_sync"]}, t0, state)
    n0 = len(s.calls)
    for h in range(1, 20):                      # 之后 19 小时持续异常
        res = _run(s, {"silent": ["vmax_multi_data_sync"]}, t0 + timedelta(hours=h), state)
        assert res["skipped"] == "no_change" and not res["notified"], (h, res)
    assert len(s.calls) == n0, "持续期间不得重复刷屏"


def test_resolution_notifies_once_and_clears():
    state = _state()
    s = FakeSenders()
    t0 = datetime(2026, 9, 18, 9, 0)
    _run(s, {"stuck": [dict(task_id="eflow_sync", detail="队列 id=1 pending")]}, t0, state)
    res = _run(s, {}, t0 + timedelta(hours=1), state)     # 异常消失
    assert res["resolved"] == 1 and res["notified"] is True, res
    assert res["new"] == 0
    again = _run(s, {}, t0 + timedelta(hours=2), state)   # 不应把"恢复"重复发
    assert again["resolved"] == 0 and again["skipped"] == "no_change", again


def test_long_running_issue_renotified_after_threshold():
    state = _state()
    s = FakeSenders()
    t0 = datetime(2026, 9, 18, 9, 0)
    _run(s, {"overdue": ["sp_data_sync"]}, t0, state)
    res = _run(s, {"overdue": ["sp_data_sync"]}, t0 + timedelta(hours=tha.RENOTIFY_HOURS + 1), state)
    assert res["renotified"] == 1 and res["new"] == 0 and res["notified"] is True, res
    assert "第 2 次提醒" in [c[1] for c in s.calls if c[0] == "wx"][-1]


def test_send_failure_retries_next_round():
    state = _state()
    bad = FakeSenders(fail=True)
    t0 = datetime(2026, 9, 18, 9, 0)
    res = _run(bad, {"group_missing": ["x_task"]}, t0, state)
    assert res["notified"] is False, res
    good = FakeSenders()
    res2 = _run(good, {"group_missing": ["x_task"]}, t0 + timedelta(hours=1), state)
    assert res2["pending_notify"] == 1 and res2["notified"] is True, (
        f"发送失败必须留下重试机会，否则一次抖动就永久吞掉这条异常: {res2}")


def test_env_switch_mutes_completely():
    import os
    state = _state()
    s = FakeSenders()
    os.environ["TASK_HEALTH_ALERT_ENABLED"] = "0"
    try:
        res = _run(s, {"silent": ["any_task"]}, datetime(2026, 9, 18, 9, 0), state)
        assert res["skipped"] == "disabled_by_env" and not s.calls, res
        assert not state.exists(), "静音时不应写状态文件"
    finally:
        os.environ.pop("TASK_HEALTH_ALERT_ENABLED", None)


CHECKS = [
    test_first_occurrence_notifies_once,
    test_persistent_issue_stays_silent,
    test_resolution_notifies_once_and_clears,
    test_long_running_issue_renotified_after_threshold,
    test_send_failure_retries_next_round,
    test_env_switch_mutes_completely,
]


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    passed = failed = 0
    for fn in CHECKS:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[ERROR] {fn.__name__}: {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"[PASS] {fn.__name__}")
    print(f"\nPASS={passed} FAIL={failed}")
    sys.exit(1 if failed else 0)
