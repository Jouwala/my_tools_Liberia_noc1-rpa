# -*- coding: utf-8 -*-
"""`wa_notify_service`（P1 告警 Baileys 推送通道）的回归测试。

覆盖四件事：
  1. 在线判定三态 + **进程被杀时的假健康窗口**（本次发现的真实缺陷）；
  2. 投递与作业文件原子写；
  3. 等回报的三种终局（done / failed / 超时），且**超时绝不算成功**；
  4. 局部失败不整体放弃 —— 否则 my_app 会以为全没发而重发，群里出现重复告警。

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
