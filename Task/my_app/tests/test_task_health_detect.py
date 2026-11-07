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
    _result_output_count,
    _dependency_source,
    _dependency_guidance,
    _is_dependency_failure,
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


def test_never_run_lowfreq_task_exempt_until_due():
    """2026-09-25 误报回归：从未执行分支也要按 cron 到期判定。

    olib_soc_vmax_report（`30 7 1 * *` 每月一次）在 09-18~09-30 被每小时误报
    「24h 无执行记录」共 7 天——旧逻辑的低频豁免只覆盖「有历史记录」分支。
    到期日（10-01）之后仍无记录则必须报（真漏分组不漏）。"""
    cron_map = {"monthly_task": "30 7 1 * *"}
    # 场景 1：09-18 巡检（到期前）→ 不得报
    now = datetime(2026, 9, 18, 10, 0)
    cutoff = (now - timedelta(hours=24)).isoformat()
    got = _silent_task_candidates(["monthly_task"], {}, set(), cutoff, cron_map, {}, 24)
    assert got == [], f"月任务在到期日前不得报 silent: {got}"
    # 场景 2：10-01 09:00 巡检（窗口 [09-30 09:00, 10-01 09:00] 含 07:30 到期时刻，
    # 应跑没跑）→ 必须报。小时级巡检窗口平铺覆盖时间轴，任何到期时刻必落入
    # 某轮窗口；错过窗口的后续轮次由 stuck/auto_retry 补写记录后的其他维度接管。
    now2 = datetime(2026, 10, 1, 9, 0)
    cutoff2 = (now2 - timedelta(hours=24)).isoformat()
    got2 = _silent_task_candidates(["monthly_task"], {}, set(), cutoff2, cron_map, {}, 24)
    assert got2 == ["monthly_task"], f"到期后仍无记录必须报（漏分组症状）: {got2}"
    # 场景 3：每日任务从未执行 → 窗口内必到期 → 照常报（不扩大豁免）
    got3 = _silent_task_candidates(["daily_task"], {}, set(), cutoff,
                                   {"daily_task": "20 6 * * *"}, {}, 24)
    assert got3 == ["daily_task"], f"每日任务从未执行必须报: {got3}"


def test_inflight_task_exempt_from_silent():
    """2026-09-25 误报回归：exec_log 完成时才写入，队列有 pending/running 在途行的
    任务不得报「24h 无执行记录」（ms_sla_full 05:15 案例）；无在途行的任务照常报。"""
    now = datetime(2026, 9, 25, 5, 15)
    cutoff = (now - timedelta(hours=24)).isoformat()
    yesterday = (now - timedelta(hours=24, minutes=9)).isoformat()   # 恰好越过 24h 线
    registry = ["ms_sla_full", "hourly_task"]
    exec_latest = {"ms_sla_full": yesterday, "hourly_task": yesterday}
    cron_map = {"ms_sla_full": "0 5 * * *", "hourly_task": "*/5 * * * *"}
    got = _silent_task_candidates(registry, exec_latest, set(), cutoff,
                                  cron_map, {}, 24, inflight_ids={"ms_sla_full"})
    assert "ms_sla_full" not in got, f"队列有在途行仍报 silent = 误报复发: {got}"
    assert "hourly_task" in got, "无在途行的任务必须照常报（豁免不得扩大化）"
    # 不传 inflight（旧调用方/None）→ 行为与旧判据一致
    got2 = _silent_task_candidates(registry, exec_latest, set(), cutoff, cron_map, {}, 24)
    assert "ms_sla_full" in got2, "缺省不豁免，保持向后兼容"


# ==========================================================
# 「成功但零产出」判据（2026-11-06 新增）
# ==========================================================
# 背景：vmax_multi_data_sync 连续 34 天 rows=0 却 success=1，
# 而当时四个维度都不覆盖它（有记录、有分组、无滞留、每小时都成功）。
# 这些用例锁住「明确是 0」与「没有自报条数」必须区分 —— 否则任务一旦改了
# 字段名，检查会变成永久误报。
def test_output_count_distinguishes_zero_from_absent():
    """0 要能取到（判空用），但字段缺失/JSON 坏/布尔值必须返回 None。"""
    assert _result_output_count('{"rows": 0}', ("rows",)) == 0
    assert _result_output_count('{"rows": 102}', ("rows",)) == 102
    # 没有登记字段 → None（不能当成 0，否则改字段名就永久误报）
    assert _result_output_count('{"other": 5}', ("rows",)) is None
    # 非 JSON → None
    assert _result_output_count("not-json", ("rows",)) is None
    # 布尔不是条数
    assert _result_output_count('{"rows": true}', ("rows",)) is None
    # 负数不算产出（防御异常值），但仍返回数值本身
    assert _result_output_count('{"rows": -1}', ("rows",)) == -1


def test_output_count_takes_max_of_keys():
    """多个键取最大：有的任务 rows 不含 skipped，total_rows 才是全量。"""
    assert _result_output_count('{"rows": 0, "total_rows": 7}', ("rows", "total_rows")) == 7
    assert _result_output_count('{"rows": 5}', ("rows", "total_rows")) == 5


def test_dependency_source_splits_dbwriter_ews_network():
    """依赖类失败必须能分辨是 DbWriter / EWS / 通用网络 —— 现场近 5 天全是 DbWriter。"""
    cases = [
        ("[DbWriter] 请求失败: http://192.168.100.19:8765/api/write -> timed out", "db_writer"),
        ("[API写入失败] Metro_ring: [DbWriter] 请求失败: 8765/api/write", "db_writer"),
        ("RateLimitError: Max timeout reached", "ews"),
        ("Unable to connect to the remote server", "ews"),
        ("HTTPSConnectionPool(...): Read timed out.", "network"),
        ("10061 Connection refused", "network"),
    ]
    for err, want in cases:
        got = _dependency_source(err)
        assert got == want, f"{err[:50]!r} 应为 {want}，实际 {got}"
        assert _is_dependency_failure(err), f"{err[:50]!r} 应判为依赖类失败"


def test_dependency_guidance_points_at_real_source():
    """guidance 必须指向真实故障源：DbWriter 故障不能让人去查 Exchange 密码。"""
    g = "\n".join(_dependency_guidance(["[DbWriter] 8765 fail"]))
    assert "DbWriter" in g and "8765" in g, f"DbWriter 故障的指引没指向 db_writer：\n{g}"
    assert "Exchange" not in g, f"DbWriter 故障却让人去查 Exchange 密码：\n{g}"

    g2 = "\n".join(_dependency_guidance(["RateLimitError: Max timeout reached"]))
    assert "EWS" in g2, f"EWS 故障的指引没指向 EWS：\n{g2}"

    # 混合故障源时两类指引都要出现（不能只报第一类）
    g3 = "\n".join(_dependency_guidance(["[DbWriter] fail", "Read timed out"]))
    assert "DbWriter" in g3 and "网络" in g3, f"混合故障源指引缺项：\n{g3}"


CHECKS = [
    test_cron_interval_actually_computed,
    test_bad_cron_returns_none_without_raising,
    test_low_frequency_task_not_reported_as_silent,
    test_unknown_cron_still_reported,
    test_never_run_lowfreq_task_exempt_until_due,
    test_inflight_task_exempt_from_silent,
    test_output_count_distinguishes_zero_from_absent,
    test_output_count_takes_max_of_keys,
    test_dependency_source_splits_dbwriter_ews_network,
    test_dependency_guidance_points_at_real_source,
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
