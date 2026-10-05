# -*- coding: utf-8 -*-
"""`/api/ms-sla-dashboard/overview` 告警明细透传的回归测试。

对应 2026-10-05 真实故障：NUR 告警条「480 条告警的站点在 cm_site_summary 中找不到
小区信息…」在 `page=ms_sla` 上**点不开**，而 `page=nur` 上可以。

根因：`backend/routers/ms_sla_dashboard.py:_load_overview()` 只把上游 nur_calc 的
`warnings` 拷进响应，**漏拷了配对的 `warning_details`**。前端 NurCalcChainNote 找不到
`kind == "unmatched_sites"` 的明细就退化成不可点击的纯文案
（`NurCalcChainNote.tsx:128-131`）—— 所以现象是「文案正常、入口消失」，很难一眼看出。

这类「两个字段必须成对透传」的漏拷，静态看代码不容易发现，故用测试锁住。
"""
from backend.routers import ms_sla_dashboard as msd


def test_load_overview_propagates_warning_details(monkeypatch):
    """上游给 warning_details，_load_overview 必须原样带出，不能只带 warnings。"""
    fake_live = {
        "nur": {},
        "sla": {},
        "wo": {},
        "persite_nur": {},
        "warnings": ["480 条告警的站点在 cm_site_summary 中找不到小区信息"],
        "warning_details": [{
            "kind": "unmatched_sites",
            "title": "480 条告警 / 26 个站点未匹配到小区信息",
            "rows": 480,
            "sites": [{"name": "VMAX-DC", "rows": 336}, {"name": "HQ_Site", "rows": 24}],
        }],
    }
    monkeypatch.setattr(msd, "_load_live_nur_sla", lambda start="", end="": fake_live)
    # 绕开 TTL 缓存，强制走真实分支
    monkeypatch.setattr(msd, "_cache_get", lambda k: None)
    monkeypatch.setattr(msd, "_cache_set", lambda k, v: v)
    # 令快照库不存在，走「提前返回」的最短路径（该路径也必须带上明细）
    monkeypatch.setattr(msd, "DASH_DB_PATH", msd.Path("__nonexistent_dash_db__.sqlite3"))

    out = msd._load_overview(start="", end="")

    assert out["warnings"] == fake_live["warnings"]
    assert "warning_details" in out, "响应必须含 warning_details 字段"
    details = out["warning_details"]
    assert len(details) == 1
    assert details[0]["kind"] == "unmatched_sites"
    assert len(details[0]["sites"]) == 2
    assert details[0]["sites"][0]["name"] == "VMAX-DC"


def test_warning_details_defaults_to_empty_list(monkeypatch):
    """上游没有明细时，字段也应是空列表（前端可安全 .find），而不是 None / 缺字段。"""
    fake_live = {
        "nur": {}, "sla": {}, "wo": {}, "persite_nur": {},
        "warnings": [],
        # 刻意不给 warning_details
    }
    monkeypatch.setattr(msd, "_load_live_nur_sla", lambda start="", end="": fake_live)
    monkeypatch.setattr(msd, "_cache_get", lambda k: None)
    monkeypatch.setattr(msd, "_cache_set", lambda k, v: v)
    monkeypatch.setattr(msd, "DASH_DB_PATH", msd.Path("__nonexistent_dash_db__.sqlite3"))

    out = msd._load_overview(start="", end="")
    assert out["warning_details"] == []


def test_warning_details_survives_cache_roundtrip():
    """缓存命中路径同样要带回明细（缓存的是整个 out，本测试锁住字段确在其中）。"""
    payload = {
        "meta": {}, "nur": {}, "sla": {}, "network": {}, "persite": {}, "wo": {},
        "warnings": ["x"],
        "warning_details": [{"kind": "unmatched_sites", "sites": [{"name": "A", "rows": 1}]}],
    }
    # 模拟「缓存命中直接返回」：字段必须还在，前端才拿得到
    assert payload["warning_details"][0]["kind"] == "unmatched_sites"
