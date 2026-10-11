# -*- coding: utf-8 -*-
"""WhatsApp 双通道回退编排单测（backend/services/whatsapp_dispatch.py）。

对应 2026-10-11 的架构改动：SP 系列报表任务从「Playwright 直发」改为
「Baileys 主通道 → Playwright 回退」。这里锁住编排层的四个关键行为：

  1. **主通道成功即返回**：Baileys 确认送达时**绝不**再碰 Playwright
     （两条通道并发 = 群里收到两份，是硬性禁止的）。
  2. **主通道失败才回退**：投递失败 / 零确认 / 超时都要落到 Playwright。
  3. **回退自身失败不再二次回退**：避免无限循环（沿用 tt_alarm 约束）。
  4. **`WHATSAPP_DISPATCH_CHANNEL=playwright` 能把三个任务整体打回旧行为**
     —— Baileys 副号一旦被封，运维改一个环境变量即可退场，无需改代码。

用 monkeypatch 顶掉两个真实通道，测试本身**零网络、零浏览器**。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import whatsapp_dispatch as wd


@pytest.fixture
def fake_channels(monkeypatch):
    """把 _try_baileys / _try_playwright 换成可编程的假通道，记录调用次数。"""
    calls = {"baileys": 0, "playwright": 0}
    state = {"baileys": None, "playwright": None}

    def fake_baileys(photos, captions, files, groups):
        calls["baileys"] += 1
        return state["baileys"]

    def fake_playwright(photos, captions, files, groups):
        calls["playwright"] += 1
        return state["playwright"]

    monkeypatch.setattr(wd, "_try_baileys", fake_baileys)
    monkeypatch.setattr(wd, "_try_playwright", fake_playwright)
    return calls, state


def test_baileys_success_skips_playwright(fake_channels):
    calls, state = fake_channels
    state["baileys"] = {"ok": True, "groups_sent": ["1203@g.us"], "errors": []}
    state["playwright"] = {"success": True, "groups_sent": ["should-not-run"]}

    out = wd.send_with_fallback(files=["a.xlsx"], groups=["WH&SP Management"])

    assert out["success"] is True
    assert out["channel"] == "baileys"
    assert out["fell_back"] is False
    assert calls["playwright"] == 0, "主通道成功时绝不能触发回退（否则群里两份）"
    assert out["groups_sent"] == ["1203@g.us"]


def test_baileys_fail_falls_back_to_playwright(fake_channels):
    calls, state = fake_channels
    state["baileys"] = {"ok": False, "confirmed": False, "timed_out": True,
                        "groups_sent": [], "errors": ["未在 600s 内回报"]}
    state["playwright"] = {"success": True, "groups_sent": ["g@g.us"], "errors": []}

    out = wd.send_with_fallback(files=["a.xlsx"], groups=["Wh&sp"])

    assert out["success"] is True
    assert out["channel"] == "playwright"
    assert out["fell_back"] is True
    assert calls["baileys"] == 1 and calls["playwright"] == 1


def test_baileys_zero_confirmation_counts_as_failure(fake_channels):
    """回报 ok=false / groups_sent 空（零确认）也要回退 —— 与 tt_alarm 判据一致。"""
    calls, state = fake_channels
    state["baileys"] = {"ok": False, "confirmed": True, "groups_sent": [],
                        "errors": ["群未确认"]}
    state["playwright"] = {"success": True, "groups_sent": ["g@g.us"]}

    out = wd.send_with_fallback(files=["a.xlsx"], groups=["x"])
    assert out["channel"] == "playwright"
    assert calls["playwright"] == 1


def test_both_channels_fail_no_third_attempt(fake_channels):
    calls, state = fake_channels
    state["baileys"] = {"ok": False, "groups_sent": [], "errors": ["b-fail"]}
    state["playwright"] = {"success": False, "groups_sent": [], "errors": ["pw-fail"]}

    out = wd.send_with_fallback(files=["a.xlsx"], groups=["x"])

    assert out["success"] is False
    assert out["channel"] is None
    # 恰好各一次：不得出现第三次尝试（无限回退）
    assert calls["baileys"] == 1 and calls["playwright"] == 1
    joined = " ".join(out["errors"])
    assert "b-fail" in joined and "pw-fail" in joined


def test_forced_playwright_skips_baileys(fake_channels, monkeypatch):
    calls, state = fake_channels
    state["playwright"] = {"success": True, "groups_sent": ["g@g.us"]}
    monkeypatch.setenv("WHATSAPP_DISPATCH_CHANNEL", "playwright")

    out = wd.send_with_fallback(files=["a.xlsx"], groups=["x"])

    assert out["channel"] == "playwright"
    assert calls["baileys"] == 0, "强制 Playwright 时不应触碰 Baileys"
    assert out["fell_back"] is False, "未试主通道，不算回退"


def test_empty_groups_rejected(fake_channels):
    calls, _ = fake_channels
    out = wd.send_with_fallback(files=["a.xlsx"], groups=[])
    assert out["success"] is False
    assert calls["baileys"] == 0 and calls["playwright"] == 0


def test_no_content_returns_failure(fake_channels):
    """photos 与 files 都空时应返回失败（不是静默发空作业）。

    真实通道里 Baileys 的 build_items 会得到空 items 并拒绝；编排层把这次拒绝
    视作主通道失败，于是照常走一次 Playwright 回退（Playwright 同样会因空内容失败）。
    这里用假通道验证的是编排层语义：空内容最终 **success=False**，不会误报成功。
    """
    calls, _ = fake_channels
    out = wd.send_with_fallback(photos=[], files=[], groups=["x"])
    assert out["success"] is False
    assert out["channel"] is None
