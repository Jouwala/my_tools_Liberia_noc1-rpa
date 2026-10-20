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


# ============================================================
# _retry_skip_pairs：重投去重台账（2026-10-20 新增，四条判据各自锁一条）
# 纯函数、不碰网络，入参就是「旧作业 + 本次 items」，直接调它最贴近真实判定。
# ============================================================


def _prev_job(status, sent_pairs, items, errors=None, minutes_ago=0):
    """造一份「上一轮作业」字典（completed_at 按 minutes_ago 回退，便于测时间窗）。

    items 必须**逐条复制**：真实场景里上一轮的 items 来自作业文件，是独立的一份数据。
    若直接复用调用方的 list 对象，改动 prev["items"][0]["fingerprint"] 会同时改到
    本轮的 items（同一对象），「文件被重新生成」那类用例就永远测不出差异。
    """
    import datetime as _dt
    return {
        "job_id": "old-job", "status": status, "groups": ["x"],
        "items": [dict(i) for i in items],
        "completed_at": (_dt.datetime.now() - _dt.timedelta(minutes=minutes_ago))
                        .isoformat(timespec="seconds"),
        "result": {"ok": True, "groups_sent": ["x"], "errors": errors or [],
                   "sent_pairs": sent_pairs},
    }


def test_retry_skip_pairs_carries_on_partial_failure(mk_items):
    """正例：上一份部分送达后判失败 + 文件字节没变 → 重投必须带 skip_pairs。

    2026-10-20 回归：ALL.png 已发到第一个群后掉线，auto_retry 整批重发，
    第一个群在 4 分钟内收到两张一模一样的图。
    """
    items = mk_items(["ALL.png", "COOL.png"])
    got = bsvc._retry_skip_pairs(
        _prev_job("failed", ["sig1|x", "sig1|y"], items, errors=["连接已断开"]), items)
    assert got == {"retry_of": "old-job", "skip_pairs": ["sig1|x", "sig1|y"]}


def test_retry_skip_pairs_accepts_done_with_errors(mk_items):
    """notify 报 done 但 errors 非空 —— my_app 侧同样判失败，也要带去台账。"""
    items = mk_items(["ALL.png"])
    got = bsvc._retry_skip_pairs(
        _prev_job("done", ["sigA|x"], items, errors=["a.png：读盘失败"]), items)
    assert got and got["skip_pairs"] == ["sigA|x"]


def test_retry_skip_pairs_skips_previous_clean_success(mk_items):
    """上一份是**干净成功** → 不去重：用户手动再点一次就该重发同一批图。"""
    items = mk_items(["ALL.png"])
    assert bsvc._retry_skip_pairs(_prev_job("done", ["sigA|x"], items), items) is None


def test_retry_skip_pairs_skips_when_no_sent_pairs(mk_items):
    """旧版 notify.js 没写 sent_pairs → 无从知道发过什么，退回整批重发。"""
    items = mk_items(["ALL.png"])
    prev = _prev_job("failed", [], items, errors=["连接已断开"])
    assert bsvc._retry_skip_pairs(prev, items) is None


def test_retry_skip_pairs_skips_when_running(tmp_job, mk_items):
    """旧作业还在 running（不是重投场景）→ 不带台账。"""
    items = mk_items(["ALL.png"])
    prev = _prev_job("running", ["sigA|x"], items, errors=["连接已断开"])
    assert bsvc._retry_skip_pairs(prev, items) is None


def test_retry_skip_pairs_skips_when_fingerprint_changed(mk_items):
    """上一轮之后文件被重新生成（投递时记录的指纹不同）→ 新的一批图，必须整批发。

    这正是「指纹必须在投递时记录」的理由：如果两边都现读磁盘，
    上一轮作业与本轮读到的是同一份当前状态，字节变过也测不出来。
    """
    items = mk_items(["ALL.png"])
    prev = _prev_job("failed", ["sigA|x"], items, errors=["连接已断开"])
    for it in prev["items"]:
        it["fingerprint"] = f"{it['name']}|{it['path']}|0|0"   # 上一轮投递时的值
    assert bsvc._retry_skip_pairs(prev, items) is None


def test_fingerprint_prefers_recorded_value(mk_items):
    """投递时记录的指纹优先；旧作业没这个字段时现算（能比，只是测不出字节变化）。"""
    items = mk_items(["ALL.png"])
    live = bsvc._item_fingerprint(items[0])
    assert bsvc._fp_of(items[0]) == live
    items[0]["fingerprint"] = "recorded-at-delivery-time"
    assert bsvc._fp_of(items[0]) == "recorded-at-delivery-time"


def test_retry_skip_pairs_skips_outside_window(mk_items):
    """旧作业的失败发生在 2 小时前（远超 30 分钟窗口）→ 今天的调度照发。"""
    items = mk_items(["ALL.png"])
    prev = _prev_job("failed", ["sigA|x"], items, errors=["连接已断开"], minutes_ago=120)
    assert bsvc._retry_skip_pairs(prev, items) is None


def test_retry_skip_pairs_skips_when_window_disabled(mk_items, monkeypatch):
    """RETRY_DEDUP_WINDOW_SECONDS=0 是运维关开关的路径，必须完全退回旧行为。"""
    monkeypatch.setattr(bsvc, "RETRY_DEDUP_WINDOW_SECONDS", 0)
    items = mk_items(["ALL.png"])
    prev = _prev_job("failed", ["sigA|x"], items, errors=["连接已断开"])
    assert bsvc._retry_skip_pairs(prev, items) is None


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
