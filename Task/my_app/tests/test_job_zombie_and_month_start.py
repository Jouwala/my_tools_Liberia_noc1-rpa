# -*- coding: utf-8 -*-
"""2026-10-01 两份修复的回归锁：僵尸作业回收 + 月初空窗不误报。

## 为什么值得单独锁

这两个问题都属于**「监控全绿但业务已经坏了」**那一类，最难靠人发现：

1. **僵尸作业堵死推送**：扩展认领作业后不回报（浏览器被关/扩展崩），作业永远停在
   `running`；而认领只认 `pending` → 整个作业邮箱被永久堵死。任务侧因为
   「本轮候选 0 单」提前返回 `success=True`，**日志全绿、群里静默收不到告警**。
   实测 2026-10-01 04:15~04:55 连续 4 轮告警未达。

2. **月初空窗被当成失败**：`cells_kpi_sync` 每天 04:50 物化当月数据，而 UME 按日
   发布（`Begin Time = D` 的行要到 D+1 凌晨才有，已实测 `End-1d == Begin` 全等）。
   故每月 1 号 04:50 跑时本月必然为空 —— 旧代码 `success = rows > 0` 把它判为失败，
   触发微信+邮件误报，把真故障淹没在噪声里。

两条都必须**只放宽该放宽的**：僵尸判定要有时间阈值（否则多实例重复发告警），
月初豁免要同时限定「当前月」且「1 号」（否则历史月为空也被放过 = 掩盖真故障）。
"""
from datetime import datetime, timedelta

import pytest

from backend.services import job_staleness as JS
from backend.services import tt_alarm_job as TJ
from backend.services.ran_cells_kpi_sync import _is_month_start_pending


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """作业文件指向临时目录，避免碰真实作业状态。"""
    monkeypatch.setattr(TJ, "JOB_FILE", tmp_path / "tt.json")
    return tmp_path


def _dispatch(tt_no="TT1"):
    return TJ.dispatch([{"tt_no": tt_no, "text": "x"}], ["值班群A"])


def _age_claim(seconds):
    """把作业的 claimed_at 回拨 seconds 秒，模拟"认领后很久没回报"。"""
    job = TJ.read_job()
    job["claimed_at"] = (datetime.now() - timedelta(seconds=seconds)).isoformat(timespec="seconds")
    TJ.write_job(job)


# ==========================================================
# 一、僵尸回收：该放的要放，不该放的一律不放
# ==========================================================
def test_running_job_within_threshold_is_not_reclaimed(isolated):
    """正常发送中（未超阈值）**绝不能**被重新认领 —— 否则多实例重复发同一批告警。

    这条与 `test_whatsapp_job_claim.py::test_claimed_job_is_marked_running_and_not_reclaimed`
    是同一诉求，此处再锁一次是为了防止改僵尸逻辑时把互斥一起改坏。
    """
    _dispatch()
    first = TJ.claim_pending_job()
    assert first is not None
    assert TJ.read_job()["status"] == "running"
    assert TJ.claim_pending_job() is None, "未超阈值的 running 作业不可被抢"


def test_stale_running_job_is_reclaimed(isolated):
    """认领超过阈值未回报 → 判定僵尸并允许重新认领（本次修复的核心）。"""
    _dispatch(tt_no="TT_STALE")
    TJ.claim_pending_job()
    _age_claim(TJ.STALE_RUNNING_SECONDS + 60)

    again = TJ.claim_pending_job()
    assert again is not None, "僵尸作业必须能被重新认领，否则作业邮箱永久堵死"
    assert again["messages"][0]["tt_no"] == "TT_STALE"


def test_reclaim_refreshes_claimed_at(isolated):
    """回收后 claimed_at 必须刷新，否则下一次轮询会立刻又判定为僵尸。"""
    _dispatch()
    TJ.claim_pending_job()
    _age_claim(TJ.STALE_RUNNING_SECONDS + 60)
    before = TJ.read_job()["claimed_at"]

    TJ.claim_pending_job()
    after = TJ.read_job()["claimed_at"]
    assert after != before
    # 再轮询不应立刻又是僵尸
    assert TJ.claim_pending_job() is None


def test_terminal_job_is_never_reclaimed(isolated):
    """已回报（done/failed）的作业不能被当成僵尸再发一遍。"""
    _dispatch()
    job = TJ.claim_pending_job()
    TJ.complete_job(job["job_id"], {"ok": True, "sent": ["TT1"]})
    assert TJ.read_job()["status"] == "done"

    _age_claim(TJ.STALE_RUNNING_SECONDS + 60)
    assert TJ.claim_pending_job() is None, "终态作业不应被重新投递"


def test_no_job_file_returns_none(isolated):
    assert TJ.claim_pending_job() is None


# ==========================================================
# 二、job_staleness 纯函数口径
# ==========================================================
@pytest.mark.parametrize("status,expected", [
    ("pending", False), ("done", False), ("failed", False), (None, False),
])
def test_non_running_is_never_stale(status, expected):
    assert JS.is_stale_running({"status": status}, 3600) is expected


def test_running_without_claimed_at_is_stale():
    """claimed_at 缺失（旧版本写入/被手改）→ 无从证明还在发送，保守判僵尸。"""
    assert JS.is_stale_running({"status": "running", "claimed_at": None}, 3600) is True


def test_running_with_unparsable_claimed_at_is_stale():
    assert JS.is_stale_running(
        {"status": "running", "claimed_at": "不是时间"}, 3600) is True


def test_threshold_boundary_is_strict():
    """恰好等于阈值**不算**僵尸（用 `>` 而非 `>=`），留出边界余量。"""
    now = 1_000_000.0
    at = datetime.fromtimestamp(now - 3600).isoformat(timespec="seconds")
    assert JS.is_stale_running({"status": "running", "claimed_at": at}, 3600, now) is False
    assert JS.is_stale_running({"status": "running", "claimed_at": at}, 3599, now) is True


def test_none_job_is_not_stale():
    assert JS.is_stale_running(None, 3600) is False


# ==========================================================
# 三、月初空窗：只豁免"当月 1 号"，历史月/月中一律照旧报失败
# ==========================================================
@pytest.mark.parametrize("month,now,expected", [
    # 当月 1 号 → 预期空窗（本月第一天还没过完，天粒度数据此刻算不出）
    ("2026-10", datetime(2026, 10, 1, 4, 50), True),
    ("2026-09", datetime(2026, 9, 1, 4, 50), True),
    # 当月 2 号及以后仍为空 → 真故障，必须报
    ("2026-10", datetime(2026, 10, 2, 4, 50), False),
    ("2026-10", datetime(2026, 10, 31, 4, 50), False),
    # 历史月为空 → 真故障，绝不能豁免（否则掩盖漏采）
    ("2026-09", datetime(2026, 10, 1, 4, 50), False),
    ("2026-08", datetime(2026, 10, 15, 4, 50), False),
])
def test_month_start_pending_only_for_current_month_day_one(month, now, expected):
    assert _is_month_start_pending(month, now) is expected


def test_month_start_rollover(monkeypatch):
    """跨年边界：1 月 1 日跑的当月是 2027-01。"""
    assert _is_month_start_pending("2027-01", datetime(2027, 1, 1, 4, 50)) is True
    assert _is_month_start_pending("2026-12", datetime(2027, 1, 1, 4, 50)) is False
