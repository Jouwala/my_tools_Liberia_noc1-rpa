"""db_freshness_check 任务健康判定的离线测试（不连库、不发通知）。

这里锁住两个真实踩过的坑：
    1. `_cron_next_and_interval` 的 aware/naive 相减异常（2026-09-18 发现）：旧实现
       先把下次触发时刻去掉时区、再与仍带时区的下下次相减 → TypeError 被 `except:
       return None, None` 静默吞掉，导致「成功逾期」维度自 2026-08-13 上线起
       从未生效过一次（所有任务永远"不逾期"）。
    2. 「24h 无执行记录」对低频任务的误报：eFlow 规则收集 cron 是每 3 天一次，
       按 24h 判据每小时都报一次异常。接入健康告警后误报会直接变成刷屏，
       所以判据必须按 cron 周期收紧。

运行：
    cd D:/01_RPA/Task/my_app
    python tests/test_task_health_detect.py
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services.db_freshness_check import (  # noqa: E402
    _cron_next_and_interval,
    _silent_task_candidates,
)


def test_cron_interval_actually_computed():
    """cron 间隔必须真的算得出来（回归 aware/naive 静默失效）。"""
    now = datetime(2026, 9, 18, 8, 0, 0)
    for cron, expect_days in (("59 23 */3 * *", 3), ("0 */6 * * *", 0.25), ("45 * * * *", 1 / 24)):
        nxt, interval = _cron_next_and_interval(cron, now)
        assert nxt is not None, f"cron={cron} 下次触发解析失败"
        assert interval is not None, f"cron={cron} 间隔解析失败（逾期/低频判定会整体降级）"
        got_days = interval.total_seconds() / 86400
        assert abs(got_days - expect_days) < 0.02, f"cron={cron} 间隔异常: {got_days} 天"


def test_bad_cron_returns_none_without_raising():
    assert _cron_next_and_interval("", datetime.now()) == (None, None)
    assert _cron_next_and_interval("not a cron", datetime.now()) == (None, None)


def test_low_frequency_task_not_reported_as_silent():
    """每 3 天一次的任务，1.5 天没记录不算静默；小时级任务 1.5 天没记录必须算。"""
    now = datetime(2026, 9, 18, 10, 0)
    cutoff = (now - timedelta(hours=24)).isoformat()
    last_36h = (now - timedelta(hours=36)).isoformat()
    registry = ["hourly_task", "every3days_task", "never_run_task", "disabled_task", "fresh_task"]
    exec_latest = {
        "hourly_task": last_36h,
        "every3days_task": last_36h,
        "disabled_task": last_36h,
        "fresh_task": now.isoformat(),
    }
    cron_map = {
        "hourly_task": "45 * * * *",
        "every3days_task": "59 23 */3 * *",
        "disabled_task": "45 * * * *",
        "fresh_task": "45 * * * *",
    }
    got = _silent_task_candidates(registry, exec_latest, {"disabled_task"}, cutoff,
                                  cron_map, {}, 24)
    assert "hourly_task" in got, f"小时级任务 36h 无记录必须报: {got}"
    assert "never_run_task" in got, f"从未执行的任务必须报（漏分组/漏注册的典型症状）: {got}"
    assert "every3days_task" not in got, f"低频任务未到下一期，不得报: {got}"
    assert "disabled_task" not in got, "已禁用任务不得报"
    assert "fresh_task" not in got, "有近期记录的任务不得报"


def test_unknown_cron_still_reported():
    """cron 解析不出间隔时宁可多报不可漏报（保持旧判据行为）。"""
    now = datetime(2026, 9, 18, 10, 0)
    cutoff = (now - timedelta(hours=24)).isoformat()
    got = _silent_task_candidates(["weird_task"], {"weird_task": (now - timedelta(hours=40)).isoformat()},
                                  set(), cutoff, {"weird_task": "坏掉的 cron"}, {}, 24)
    assert got == ["weird_task"], got


CHECKS = [
    test_cron_interval_actually_computed,
    test_bad_cron_returns_none_without_raising,
    test_low_frequency_task_not_reported_as_silent,
    test_unknown_cron_still_reported,
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
