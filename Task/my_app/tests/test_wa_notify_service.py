# -*- coding: utf-8 -*-
"""`wa_notify_service`（P1 告警 Baileys 推送通道）的回归测试。

覆盖五件事：
  1. 在线判定三态 + **进程被杀时的假健康窗口**（本次发现的真实缺陷）；
  2. 投递与作业文件原子写；
  3. 等回报的三种终局（done / failed / 超时），且**超时绝不算成功**；
  4. 局部失败不整体放弃 —— 否则 my_app 会以为全没发而重发，群里出现重复告警；
  5. 消费端（`notify.js`）认领的**防重入** —— `setInterval` + async 回调会重入，
     认领若不置 `running` 就会重复发送（2026-10-05 实测缺陷）。

⚠️ 测试全部把作业/心跳文件指到 `tmp_path`，**绝不碰 bot 的真实信箱**
（真实信箱里有生产告警，写坏了会直接影响值班群）。
"""
import json
import os
from datetime import datetime, timedelta

import pytest

from backend.services import wa_notify_service as n


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """把两个文件都隔离到临时目录，避免污染 bot 的真实信箱。"""
    monkeypatch.setattr(n, "JOB_FILE", tmp_path / "job.json")
    monkeypatch.setattr(n, "HEARTBEAT_FILE", tmp_path / "hb.json")
    return tmp_path


def _hb(path, **kw):
    data = {"at": datetime.now().isoformat(timespec="seconds"),
            "connected": True, "groups": 4, "pid": os.getpid()}
    data.update(kw)
    path.write_text(json.dumps(data), encoding="utf-8")


# ==========================================================
# 一、在线判定
# ==========================================================
class TestIsOnline:
    def test_无心跳判_unknown_而不是_offline(self):
        """推送进程刚重启时还没写心跳，判离线会每次重启都误报一次。"""
        r = n.is_online()
        assert r["status"] == "unknown"
        assert "尚无" in r["reason"]

    def test_心跳新鲜判_online(self, tmp_path):
        _hb(tmp_path / "hb.json")
        r = n.is_online()
        assert r["status"] == "online"
        assert r["groups"] == 4

    def test_超阈值判_offline(self, tmp_path):
        old = (datetime.now() - timedelta(minutes=10)).isoformat(timespec="seconds")
        _hb(tmp_path / "hb.json", at=old)
        r = n.is_online()
        assert r["status"] == "offline"
        assert "无心跳" in r["reason"]

    def test_进程已死立即判_offline(self, tmp_path):
        """**本次修复的缺陷**：心跳文件是进程被杀时来不及更新的。

        实测 `Stop-Process -Force` 后文件里仍是 `connected:true` + 旧时间戳，
        只看时间戳会有最长 `stale` 秒（默认 5 分钟）的「假健康」窗口 ——
        而这段时间里告警投出去其实没人消费。
        pid 校验把这个窗口压到一次轮询。
        """
        _hb(tmp_path / "hb.json", pid=999999)   # 几乎不可能存在的 pid
        r = n.is_online()
        assert r["status"] == "offline"
        assert "999999" in r["reason"]

    def test_未连接判_offline(self, tmp_path):
        _hb(tmp_path / "hb.json", connected=False)
        r = n.is_online()
        assert r["status"] == "offline"
        assert "relogin" in r["reason"]      # 必须指出怎么修

    def test_心跳坏值不抛异常(self, tmp_path):
        (tmp_path / "hb.json").write_text("{ 不是 json", encoding="utf-8")
        assert n.is_online()["status"] == "unknown"

    def test_now_可注入(self, tmp_path):
        _hb(tmp_path / "hb.json")
        future = datetime.now().timestamp() + 600
        assert n.is_online(now=future)["status"] == "offline"

    def test_pid_探测_存活与不存在(self):
        assert n._pid_alive(os.getpid()) is True
        assert n._pid_alive(999999) is False


# ==========================================================
# 二、投递
# ==========================================================
class TestDispatch:
    def test_投递写出_pending_作业(self, tmp_path):
        d = n.dispatch([{"tt_no": "TT1", "text": "hi"}], ["OLR Eflow Issues"])
        assert d["ok"] is True
        assert d["dispatched"] == 1
        job = json.loads((tmp_path / "job.json").read_text(encoding="utf-8"))
        assert job["status"] == "pending"
        assert job["kind"] == "text"
        assert job["groups"] == ["OLR Eflow Issues"]
        assert job["messages"][0]["tt_no"] == "TT1"

    def test_空消息不投递(self):
        assert n.dispatch([], ["g"])["ok"] is False

    def test_空群不投递(self):
        assert n.dispatch([{"tt_no": "T", "text": "x"}], [])["ok"] is False

    def test_覆盖旧作业时旧_pending_会被记日志但不阻断(self, tmp_path, caplog):
        """告警是「最新状态最重要」，堆积旧单只会延迟当前告警。"""
        n.dispatch([{"tt_no": "OLD", "text": "x"}], ["g"])
        d = n.dispatch([{"tt_no": "NEW", "text": "y"}], ["g"])
        assert d["ok"] is True
        job = json.loads((tmp_path / "job.json").read_text(encoding="utf-8"))
        assert job["messages"][0]["tt_no"] == "NEW"

    def test_原子写不留临时文件(self, tmp_path):
        n.dispatch([{"tt_no": "T", "text": "x"}], ["g"])
        assert [f.name for f in tmp_path.iterdir()] == ["job.json"]


# ==========================================================
# 三、等回报
# ==========================================================
class TestWaitForResult:
    def _write_final(self, tmp_path, job_id, ok, sent, errors=None):
        (tmp_path / "job.json").write_text(json.dumps({
            "job_id": job_id, "status": "done" if ok else "failed",
            "result": {"ok": ok, "sent": sent, "errors": errors or []},
        }), encoding="utf-8")

    def test_成功回报带_message_id(self, tmp_path):
        self._write_final(tmp_path, "J1", True,
                          [{"tt_no": "TT1", "jid": "g@g.us", "message_id": "3EB0ABC"}])
        r = n.wait_for_job_result("J1", timeout=3)
        assert r["confirmed"] is True and r["ok"] is True
        assert r["sent"] == ["TT1"]
        # message id 是服务端回执 —— 与扩展通道「数 DOM 气泡猜」最本质的区别
        assert r["message_ids"]["TT1"] == "3EB0ABC"

    def test_失败回报不算成功(self, tmp_path):
        self._write_final(tmp_path, "J1", False, [], ["发送失败"])
        r = n.wait_for_job_result("J1", timeout=3)
        assert r["confirmed"] is True
        assert r["ok"] is False
        assert r["sent"] == []

    def test_超时不算成功(self, tmp_path):
        """超时必须如实为未确认 —— 调用方据此绝不能把 send_status 置 'Y'。"""
        r = n.wait_for_job_result("J1", timeout=2)
        assert r["timed_out"] is True
        assert r["confirmed"] is False
        assert r["ok"] is False
        assert "notify.js" in r["errors"][0]   # 必须给出排查动作

    def test_作业被新单覆盖时立即返回(self, tmp_path):
        self._write_final(tmp_path, "J2", True, [{"tt_no": "X", "message_id": "m"}])
        r = n.wait_for_job_result("J1", timeout=5)
        assert r["confirmed"] is False
        assert "覆盖" in r["errors"][0]

    def test_局部成功被如实回报(self, tmp_path):
        """3 条里成了 1 条就报 1 条，不能报整体失败 —— 否则 my_app 会全部重发。"""
        self._write_final(tmp_path, "J1", True,
                          [{"tt_no": "TT1", "message_id": "m1"}],
                          ["TT2 → 群：发送失败"])
        r = n.wait_for_job_result("J1", timeout=3)
        assert r["sent"] == ["TT1"]
        assert r["ok"] is True
        assert "TT2" in r["errors"][0]


# ==========================================================
# 四、消费端认领的防重入（2026-10-05 重复告警缺陷的守卫）
# ==========================================================
class TestNotifyClaimAntiReentry:
    """锁死「认领即置 running」这条不变量。

    背景（2026-10-05 实测缺陷）：`notify.js` 的轮询是
    `setInterval(async () => { await runJob(...) })`，而 **`setInterval` 不等待
    上一次异步回调结束**。若认领时只读不改状态，`sendMessage()` 的网络往返期间
    作业文件一直是 `pending`，于是**每个 tick 都重新认领同一单并重发**
    （仿真实测同一条 P1 告警被发了 5 次）。

    旧扩展通道本来有这道防护（`tt_alarm_job.claim_pending_job` 认领即置
    `running`），换到 Baileys 通道时丢了。这里用**真实源码**做断言，
    避免「改了 JS 但测试测的是 Python 侧的假实现」。
    """

    @staticmethod
    def _notify_js() -> str:
        from pathlib import Path
        p = (Path(__file__).resolve().parents[1].parent
             / "whatsapp-kb-bot" / "src" / "notify.js")
        if not p.is_file():
            pytest.skip("whatsapp-kb-bot 不在本机，跳过消费端源码断言")
        return p.read_text(encoding="utf-8")

    def test_认领函数必须把状态推进到_running(self):
        """核心不变量：读到 pending 后**就地写回 running**，否则会重复发送。"""
        src = self._notify_js()
        body = src.split("function claimJob()", 1)[1].split("\n}", 1)[0]
        assert "status: 'running'" in body, (
            "claimJob 认领后未把状态推进到 running —— `setInterval` 的异步回调会重入，"
            "同一单会被重复发送（2026-10-05 事故）")
        assert "claimed_at" in body, "认领必须记录 claimed_at，否则僵尸回收无法判定"
        assert "writeJsonAtomic" in body, "状态推进必须是原子写回"

    def test_保留僵尸回收(self):
        """置了 running 就必须有回收，否则一次崩溃把信箱永久堵死。

        这正是 `tt_alarm_job.py:14-24` 记录的 2026-10-01 事故形态
        （作业停在 running，后续所有告警投递失败，而任务自己 success=True）。
        """
        src = self._notify_js()
        body = src.split("function claimJob()", 1)[1].split("\n}", 1)[0]
        assert "STALE_RUNNING_MS" in body, "缺僵尸回收：进程被杀后信箱会被永久堵死"
        assert "age < STALE_RUNNING_MS" in body
        # 阈值必须远大于正常发送耗时（秒级），否则会把发送中的作业当僵尸抢走
        stale_ms = int(
            src.split("NOTIFY_STALE_RUNNING_MS", 1)[1].split("||", 1)[1]
            .split(")", 1)[0].strip())
        assert stale_ms >= 60_000, (
            f"僵尸阈值 {stale_ms}ms 过小，会把正在发送的作业当僵尸抢走 → 重复发送")

    def test_写回失败时不认领(self):
        """状态没推进就发出去 = 退回「每 tick 重发一遍」，宁可本轮不发。"""
        src = self._notify_js()
        body = src.split("function claimJob()", 1)[1].split("\n}", 1)[0]
        assert "catch" in body and "return null" in body, \
            "认领写回失败必须放弃本轮（return null），不能照发"
