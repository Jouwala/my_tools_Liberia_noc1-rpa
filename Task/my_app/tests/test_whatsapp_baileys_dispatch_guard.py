# -*- coding: utf-8 -*-
"""Baileys 单作业文件互斥守卫单测（backend/services/whatsapp_send_baileys_service.py）。

## 为什么值得锁

notify.js 只认**一个** `whatsapp_send_baileys_job.json`。若在该文件已有
`pending`（待认领）或 `running`（未超僵尸阈值）作业时又投递新作业，新作业会
**覆盖**旧作业 → 旧作业静默丢失（图/文档没发出去却无人知晓）。

正常路径下这种重叠不会发生：SP 三个任务已按 cron 错峰（见 task_registry），
且独立的 `whatsapp_send_baileys` 任务默认 `enabled=False`。但「任务被手动启用 /
auto_retry 重试重叠 / 未来新增调用方」都可能踩到，故这里加一道守卫并锁死它。

测试用 monkeypatch 把 JOB_FILE 指向临时目录，**不碰真实作业文件、不发网络**。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import whatsapp_send_baileys_service as bsvc


@pytest.fixture
def tmp_job(tmp_path, monkeypatch):
    """把作业文件指向临时目录，避免污染生产作业文件。"""
    job_file = tmp_path / "whatsapp_send_baileys_job.json"
    monkeypatch.setattr(bsvc, "JOB_FILE", job_file)
    return job_file


@pytest.fixture
def mk_items(tmp_path):
    """在临时目录造**真实存在**的文件，返回构造 items 的工厂。

    文件存在性检查会在配额检查之前触发，故测试必须用真实文件，
    否则所有用例都会先撞上「文件不存在」而测不到目标分支。
    """
    def _make(specs):
        # specs: [("a.png",) | ("r.xlsx",) ...]
        out = []
        for name in specs:
            p = tmp_path / name
            p.write_bytes(b"x")
            out.append({"kind": "image", "name": name,
                        "file_name": name, "path": str(p)})
        return out
    return _make


def test_build_items_sets_document_kind_for_xlsx(tmp_path):
    """xlsx 必须标成 kind=document —— 否则 notify.js 走 image 通道发成损坏图片。

    2026-10-11 回归：build_items 曾把所有 item 的 kind 写死 image，notify.js
    的 isDoc 判据「kind 存在时只看 kind」于是把 xlsx 当图片发 —— 服务端照回
    message id（误判成功），但群里只有图片、没有 excel 文件。
    """
    png = tmp_path / "a.png"
    xlsx = tmp_path / "b.xlsx"
    png.write_bytes(b"x")
    xlsx.write_bytes(b"x")
    items = bsvc.build_items([str(png), str(xlsx)], None)
    kinds = {(Path(i["name"]).suffix): i["kind"] for i in items}
    assert kinds[".png"] == "image"
    assert kinds[".xlsx"] == "document"


def test_dispatch_refuses_when_pending_exists(tmp_job, mk_items):
    # 预置一个 pending 作业
    bsvc._write_job({"job_id": "old-pending", "status": "pending",
                     "groups": ["x"], "items": []})
    out = bsvc.dispatch_items(mk_items(["a.png"]), ["x"])
    assert out["ok"] is False
    assert "old-pending" in " ".join(out["errors"])
    # 旧作业未被覆盖
    assert bsvc._read_job()["job_id"] == "old-pending"


def test_dispatch_refuses_when_running_fresh(tmp_job, mk_items):
    import datetime
    bsvc._write_job({"job_id": "old-running", "status": "running",
                     "claimed_at": datetime.datetime.now().isoformat(timespec="seconds"),
                     "groups": ["x"], "items": []})
    out = bsvc.dispatch_items(mk_items(["a.png"]), ["x"])
    assert out["ok"] is False
    assert bsvc._read_job()["job_id"] == "old-running"


def test_dispatch_proceeds_when_previous_terminal(tmp_job, mk_items, monkeypatch):
    """上一作业已终态时，新作业应正常投递（守卫不误伤）。"""
    bsvc._write_job({"job_id": "old-done", "status": "done", "groups": ["x"], "items": []})
    monkeypatch.setattr(bsvc, "WAIT_SECONDS", 0)
    bsvc.dispatch_items(mk_items(["a.png"]), ["x"])
    # 守卫放行 → 作业文件已被新作业取代（不再是 old-done）
    assert bsvc._read_job()["job_id"] != "old-done"


def test_dispatch_rejects_missing_file(tmp_job):
    """文件不存在 → 投递前直接拒绝（不白等一轮网络往返）。"""
    items = [{"kind": "image", "name": "nope.png", "file_name": "nope.png",
              "path": "C:/definitely/not/here/nope.png"}]
    out = bsvc.dispatch_items(items, ["x"])
    assert out["ok"] is False
    assert "文件不存在" in " ".join(out["errors"])


def test_dispatch_rejects_over_image_budget(tmp_job, mk_items):
    """图片数超过 max_images 时投递前主动拒绝（避免 notify.js 静默截断）。"""
    out = bsvc.dispatch_items(mk_items([f"a{i}.png" for i in range(7)]),
                              ["x"], max_images=6, max_documents=1)
    assert out["ok"] is False
    assert "图片" in " ".join(out["errors"])


def test_dispatch_rejects_over_document_budget(tmp_job, mk_items):
    """两份 xlsx 超过 max_documents=1 → 拒绝（SP WhatsApp 报表的真实形态：4 图 + 2 文档）。"""
    items = mk_items([f"a{i}.png" for i in range(4)] + [f"r{i}.xlsx" for i in range(2)])
    out = bsvc.dispatch_items(items, ["x"], max_images=6, max_documents=1)
    assert out["ok"] is False
    assert "文档" in " ".join(out["errors"])


def test_dispatch_within_budget_passes_guard(tmp_job, mk_items, monkeypatch):
    """4 图 + 1 文档在配额内 → 守卫放行（不误伤）。"""
    monkeypatch.setattr(bsvc, "WAIT_SECONDS", 0)
    items = mk_items([f"a{i}.png" for i in range(4)] + ["r.xlsx"])
    out = bsvc.dispatch_items(items, ["x"], max_images=6, max_documents=1)
    # 守卫放行 → 作业被投递（job_id 存在）；未真等回报，故 ok=False（超时）
    assert out["job_id"]
    assert bsvc._read_job()["job_id"] == out["job_id"]


def test_errors_on_success_are_not_ok(tmp_job, mk_items, monkeypatch):
    """notify 报 ok 但 result.errors 非空 → 仍判失败（有 item 未送达）。"""
    monkeypatch.setattr(bsvc, "WAIT_SECONDS", 5)
    monkeypatch.setattr(bsvc, "TASK_POLL_INTERVAL", 0.01)
    items = mk_items(["a.png"])

    # 模拟 notify.js：投递后立刻回写一个「ok=true 但有 errors」的终态
    orig_write = bsvc._write_job

    def fake_write(job):
        orig_write(job)
        if job.get("status") == "pending":
            bad = dict(job)
            bad["status"] = "done"
            bad["result"] = {"ok": True, "groups_sent": ["g@g.us"],
                             "errors": ["a.png：读盘失败"]}
            orig_write(bad)

    monkeypatch.setattr(bsvc, "_write_job", fake_write)
    out = bsvc.dispatch_items(items, ["x"])
    assert out["ok"] is False, "有单项错误时不得报成功（否则静默丢附件）"
    assert out["confirmed"] is True
