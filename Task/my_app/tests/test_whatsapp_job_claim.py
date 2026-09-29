# -*- coding: utf-8 -*-
"""扩展作业交接契约单测：TT 告警文本作业如何经统一认领口送到 Chrome 扩展。

对应 `backend/services/whatsapp_job_claim.py` 与 `backend/routers/whatsapp_outbox.py`。

## 为什么值得单独锁一层

系统里有**两个**作业源（定时发图、TT 告警文本），但扩展只轮询
`/api/whatsapp/ext/job` 一个端点。这条交界上踩过/极易踩三个坑：

  1. **缺 `pending: True`** —— 扩展以 `job.pending === true` 判定有无作业
     （`background.js` 的 `tryClaimJob`）。文本源自带的作业字典没有这个字段，
     直接返回会让扩展**永远认为没有作业**，告警静默不发。**真实发生过**。
  2. **缺 `kind`** —— 扩展靠它分发到发图 / 发文本两条路径；缺了会走错发送引擎。
  3. **回报走错源** —— 发图回 `groups_sent`、文本回 `sent`，回错作业源等于
     把「已发送」记成别人的结果，`send_status` 会据此误判。

另有两个健壮性要求：一个作业源抛异常不能让另一个源也发不出去；
`running` 中的作业不能被重复认领（否则多个扩展实例重复发送同一批告警）。
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import tt_alarm_job as TJ
from backend.services import whatsapp_ext_service as EX
from backend.services import whatsapp_job_claim as C


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """两个作业文件都指向临时目录，避免碰到真实作业状态。"""
    monkeypatch.setattr(TJ, "JOB_FILE", tmp_path / "tt.json")
    monkeypatch.setattr(EX, "JOB_FILE", tmp_path / "img.json")
    return tmp_path


@pytest.fixture
def client():
    # TestClient 默认 client host 是 "testclient"，既不被会话中间件
    # （`backend/main.py:301`）也不被 require_protected（`backend/security.py:23`）
    # 当成回环 → 401。生产路径本就是回环自动放行，故伪装成 127.0.0.1。
    return TestClient(app, client=("127.0.0.1", 12345))


def _dispatch_text(tt_no="TT1", text="告警未清除", groups=None):
    return TJ.dispatch([{"tt_no": tt_no, "text": text}], groups or ["值班群A"])


# ==========================================================
# 认领层：kind / pending / 优先级 / 互斥
# ==========================================================
def test_no_job_returns_none(isolated):
    assert C.claim_next_job() is None


def test_text_job_is_claimed_with_kind_and_pending(isolated):
    """缺 pending 会让扩展永远认为无作业 —— 这个字段必须由认领层补上。"""
    _dispatch_text()
    job = C.claim_next_job()
    assert job is not None
    assert job["kind"] == "text"
    assert job["pending"] is True, "扩展以 pending===true 判定有无作业，缺则告警静默不发"
    assert job["messages"][0]["tt_no"] == "TT1"
    assert job["groups"] == ["值班群A"]


def test_claimed_job_is_marked_running_and_not_reclaimed(isolated):
    """认领即置 running，避免多个扩展实例重复发送同一批告警。"""
    _dispatch_text()
    C.claim_next_job()
    assert TJ.read_job()["status"] == "running"
    assert C.claim_next_job() is None


def test_image_job_takes_priority_over_text(isolated):
    """两个源都可用时优先发图（它由人工/定时显式投递），且不应顺带拿走文本作业。"""
    _dispatch_text(tt_no="TT2")
    EX._write_job({"job_id": "IMG1", "status": "pending", "groups": ["值班群B"],
                   "result": None})
    job = C.claim_next_job()
    assert job["kind"] == "image"
    assert job["job_id"] == "IMG1"
    assert TJ.read_job()["status"] == "pending", "文本作业不应被顺带认领"


def test_text_is_claimed_after_image_is_taken(isolated):
    _dispatch_text(tt_no="TT3")
    EX._write_job({"job_id": "IMG2", "status": "pending", "groups": [], "result": None})
    assert C.claim_next_job()["kind"] == "image"
    assert C.claim_next_job()["kind"] == "text"


def test_one_broken_source_does_not_block_the_other(isolated, monkeypatch):
    """一个源坏掉（如图片目录不可读）不应让另一个源也发不出去。"""
    def boom():
        raise RuntimeError("图片目录不可读")

    monkeypatch.setattr(EX, "claim_pending_job", boom)
    _dispatch_text(tt_no="TT9")
    job = C.claim_next_job()
    assert job is not None and job["kind"] == "text"


# ==========================================================
# 回报层：按 kind 转交对应作业源
# ==========================================================
def test_text_result_carries_sent_back_to_tt_job(isolated):
    _dispatch_text(tt_no="TT1")
    job = C.claim_next_job()
    assert C.report_result("text", job["job_id"], {"ok": True, "sent": ["TT1"], "errors": []})
    done = TJ.read_job()
    assert done["status"] == "done"
    assert done["result"]["sent"] == ["TT1"], "sent 是置 send_status='Y' 的依据"


def test_unknown_kind_is_rejected(isolated):
    """回错源会把「已发送」记成别人的结果，故未知 kind 必须拒绝而非默认发图。"""
    assert C.report_result("bogus", "X", {"ok": True}) is False


def test_result_for_wrong_job_id_is_rejected(isolated):
    _dispatch_text()
    C.claim_next_job()
    assert C.report_result("text", "bogus", {"ok": True, "sent": []}) is False


# ==========================================================
# HTTP 契约：扩展实际看到的东西
# ==========================================================
def test_endpoint_returns_pending_false_when_idle(isolated, client):
    r = client.get("/api/whatsapp/ext/job")
    assert r.status_code == 200
    assert r.json() == {"pending": False}


def test_endpoint_hands_text_job_to_extension(isolated, client):
    """扩展视角的完整往返：认领 → 看到 kind/messages → 回报 → 作业落终态。"""
    _dispatch_text(tt_no="TT202609270103", groups=["值班群A"])

    r = client.get("/api/whatsapp/ext/job")
    assert r.status_code == 200
    job = r.json()
    assert job["pending"] is True
    assert job["kind"] == "text"
    assert job["messages"][0]["tt_no"] == "TT202609270103"
    assert job["groups"] == ["值班群A"]

    r = client.post("/api/whatsapp/ext/job/result", json={
        "job_id": job["job_id"], "kind": "text", "ok": True,
        "sent": ["TT202609270103"], "errors": [],
    })
    assert r.status_code == 200 and r.json()["ok"] is True
    assert TJ.read_job()["result"]["sent"] == ["TT202609270103"]


def test_endpoint_still_serves_image_jobs(isolated, client):
    """回归：发图作业仍走原路径，kind=image 且回报走 groups_sent。"""
    EX._write_job({"job_id": "IMG-1", "status": "pending", "groups": ["值班群B"],
                   "result": None})
    job = client.get("/api/whatsapp/ext/job").json()
    assert job["kind"] == "image"
    assert job["pending"] is True

    r = client.post("/api/whatsapp/ext/job/result", json={
        "job_id": "IMG-1", "kind": "image", "ok": True,
        "groups_sent": ["值班群B"], "errors": [],
    })
    assert r.status_code == 200
    assert EX._read_job()["status"] == "completed"


def test_endpoint_rejects_stale_job_id(isolated, client):
    r = client.post("/api/whatsapp/ext/job/result", json={
        "job_id": "bogus", "kind": "text", "ok": True, "sent": [],
    })
    assert r.status_code == 409
