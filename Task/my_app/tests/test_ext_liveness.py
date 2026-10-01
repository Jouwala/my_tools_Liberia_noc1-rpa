# -*- coding: utf-8 -*-
"""`ext_liveness` 扩展在线判定 + 投递前告警的回归测试（2026-10-01 事故）。

覆盖三件事：
  1. 三态判定（online / offline / unknown）与边界、坏值容错；
  2. `record_activity` 的落盘与「写失败不影响主流程」；
  3. `_check_ext_before_dispatch` 只在 **offline** 时告警 —— unknown 不告警是
     **刻意的**，否则服务每次重启都会误报一次，会让人对告警脱敏。
"""
import json
from datetime import datetime, timedelta

import pytest

from backend.services import ext_liveness as L
from backend.services import tt_alarm_whatsapp_service as svc


# ==========================================================
# 一、三态判定（纯函数）
# ==========================================================
def _iso(**delta):
    return (datetime.now() - timedelta(**delta)).isoformat(timespec="seconds")


class TestEvaluate:
    def test_从未见过判_unknown_而不是_offline(self):
        """关键：服务刚重启时没有记录，不能报离线，否则每次重启都误报。"""
        r = L.evaluate({}, stale_seconds=300)
        assert r["status"] == L.STATUS_UNKNOWN
        assert r["age_seconds"] is None
        assert "尚无" in r["reason"]

    def test_近期认领判_online(self):
        r = L.evaluate({"last_seen_at": _iso(seconds=30)}, stale_seconds=300)
        assert r["status"] == L.STATUS_ONLINE
        assert r["age_seconds"] == pytest.approx(30, abs=5)

    def test_超阈值判_offline(self):
        r = L.evaluate({"last_seen_at": _iso(minutes=10)}, stale_seconds=300)
        assert r["status"] == L.STATUS_OFFLINE
        assert "未认领" in r["reason"]

    def test_坏时间戳判_unknown_不炸(self):
        for bad in ("not-a-time", "", None, 12345):
            r = L.evaluate({"last_seen_at": bad}, stale_seconds=300)
            assert r["status"] == L.STATUS_UNKNOWN

    def test_坏入参不抛异常(self):
        for bad in (None, [], "x", 42):
            assert L.evaluate(bad, stale_seconds=300)["status"] == L.STATUS_UNKNOWN

    def test_边界是严格大于(self):
        """恰好等于阈值时算在线（与 job_staleness 的严格 `>` 保持一致）。

        用注入的 `now` 而不是真实时钟：`_iso()` 按秒取整会丢掉微秒，
        真实时间会略微超过 300s 而落到 offline，测出来的是取整误差而非判定逻辑。
        """
        base = datetime(2026, 10, 1, 12, 0, 0)
        state = {"last_seen_at": base.isoformat(timespec="seconds")}
        exactly = base.timestamp() + 300          # 恰好 300s
        assert L.evaluate(state, 300, now=exactly)["status"] == L.STATUS_ONLINE
        assert L.evaluate(state, 300, now=exactly + 1)["status"] == L.STATUS_OFFLINE

    def test_now_可注入(self):
        """注入 now 让判定可复现，不依赖真实时钟。"""
        base = datetime(2026, 10, 1, 12, 0, 0)
        state = {"last_seen_at": base.isoformat(timespec="seconds")}
        after = (base + timedelta(minutes=10)).timestamp()
        assert L.evaluate(state, 300, now=after)["status"] == L.STATUS_OFFLINE

    def test_返回体字段齐全(self):
        r = L.evaluate({"last_seen_at": _iso(seconds=10)}, 300)
        for k in ("status", "last_seen_at", "age_seconds", "stale_seconds", "reason"):
            assert k in r


class TestHumanize:
    @pytest.mark.parametrize("sec,expect", [
        (0, "0 秒"), (45, "45 秒"),
        (60, "1 分钟"), (599, "9 分钟"),
        (3600, "1 小时"), (4800, "1 小时20 分钟"),
    ])
    def test_人话换算(self, sec, expect):
        assert L._humanize(sec) == expect


# ==========================================================
# 二、落盘与容错
# ==========================================================
class TestRecordActivity:
    def test_写入后可读回(self, tmp_path, monkeypatch):
        monkeypatch.setattr(L, "STATE_FILE", tmp_path / "state.json")
        L.record_activity(source="poll")
        st = L.read_state()
        assert st["last_source"] == "poll"
        assert L.evaluate(st, 300)["status"] == L.STATUS_ONLINE

    def test_写失败不抛异常(self, tmp_path, monkeypatch):
        """可观测性设施坏了不能反过来弄坏认领主流程。"""
        # 指向一个不可能建的路径（父路径是文件而非目录）
        bad = tmp_path / "afile"
        bad.write_text("x", encoding="utf-8")
        monkeypatch.setattr(L, "STATE_FILE", bad / "sub" / "state.json")
        L.record_activity(source="poll")  # 不应抛

    def test_文件损坏时返回空字典(self, tmp_path, monkeypatch):
        p = tmp_path / "bad.json"
        p.write_text("{ 不是 json", encoding="utf-8")
        monkeypatch.setattr(L, "STATE_FILE", p)
        assert L.read_state() == {}

    def test_文件缺失时返回空字典(self, tmp_path, monkeypatch):
        monkeypatch.setattr(L, "STATE_FILE", tmp_path / "nope.json")
        assert L.read_state() == {}

    def test_原子写不留临时文件(self, tmp_path, monkeypatch):
        monkeypatch.setattr(L, "STATE_FILE", tmp_path / "state.json")
        L.record_activity(source="poll")
        assert [f.name for f in tmp_path.iterdir()] == ["state.json"]


# ==========================================================
# 三、投递前告警（只在该喊时喊）
# ==========================================================
class TestCheckExtBeforeDispatch:
    def _run(self, status, monkeypatch):
        monkeypatch.setattr(svc.ext_liveness, "check",
                            lambda: {"status": status, "last_seen_at": "x",
                                     "reason": "测试原因"})
        out = {"warnings": [], "errors": []}
        svc._check_ext_before_dispatch(out, due_count=3)
        return out

    def test_offline_时告警且写明影响面(self, monkeypatch):
        out = self._run(L.STATUS_OFFLINE, monkeypatch)
        assert len(out["warnings"]) == 1
        w = out["warnings"][0]
        assert "离线" in w
        assert "3 单" in w          # 必须写明本轮有多少单受影响
        assert "大概率发不出去" in w  # 必须说清后果，不能只报状态

    def test_unknown_不告警(self, monkeypatch):
        """刻意：服务刚重启时无记录，若告警则每次重启都误报一次。"""
        out = self._run(L.STATUS_UNKNOWN, monkeypatch)
        assert out["warnings"] == []

    def test_online_不告警(self, monkeypatch):
        out = self._run(L.STATUS_ONLINE, monkeypatch)
        assert out["warnings"] == []

    def test_状态落进_out_供页面展示(self, monkeypatch):
        out = self._run(L.STATUS_OFFLINE, monkeypatch)
        assert out["ext_status"] == L.STATUS_OFFLINE
        assert out["ext_last_seen_at"] == "x"

    def test_检查本身异常时不阻断发送(self, monkeypatch):
        def _boom():
            raise RuntimeError("读记录炸了")
        monkeypatch.setattr(svc.ext_liveness, "check", _boom)
        out = {"warnings": [], "errors": []}
        svc._check_ext_before_dispatch(out, due_count=1)  # 不应抛
        assert out["warnings"] == []


# ==========================================================
# 四、认领即证据（与 whatsapp_job_claim 的接线）
# ==========================================================
class TestClaimRecordsActivity:
    def test_认领会记录活动(self, tmp_path, monkeypatch):
        """扩展每分钟轮询一次，**空手而归也算活着** —— 故在入口就记录。"""
        from backend.services import whatsapp_job_claim as claim
        monkeypatch.setattr(L, "STATE_FILE", tmp_path / "state.json")
        # 两个作业源都返回 None（无作业可发）——正是"空手而归"的场景
        monkeypatch.setattr(claim.ext, "claim_pending_job", lambda: None)
        monkeypatch.setattr(claim.tt_alarm_job, "claim_pending_job", lambda: None)

        assert claim.claim_next_job() is None
        # 关键断言：没有作业也留下了活动记录
        assert L.evaluate(L.read_state(), 300)["status"] == L.STATUS_ONLINE
