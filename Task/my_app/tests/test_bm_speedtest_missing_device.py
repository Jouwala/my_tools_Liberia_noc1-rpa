# -*- coding: utf-8 -*-
"""speedtest 口径「可缺列」回归（2026-11-16 页面全空事故）。

**事故**：15:55 用户从数据上传页重导 `speedtest_data`（新版 Speedtest 导出 950 行），
新文件**没有 `device` 列** → 整表被替换后列集变化，而 `cal.base_sql()` 把 `device`
写死在 SELECT 里 → `/api/bm-speedtest/{overview,trend,filters}` 全部报
`字段 "device" 不存在`（HTTP 仍 200，错误塞在 meta.warnings），页面所有卡片/曲线空白。

**修法**：`base_sql(columns=...)` 按**实际列名**投影；缺 `device` 时用字面量 `'all'`
顶替（该列实测恒为 `all`/空串，不携带信息，故两者在下游等价）。

本用例只校验 SQL 生成，**不连库、不依赖 PG**（可在 CI 的任意环境跑）。
"""
from backend.services import bm_speedtest_caliber as cal

# 2026-09-30 版完整表结构（含 device）
FULL_COLUMNS = {
    "provider", "location", "device", "aggregate_date",
    "technology_type", "metric_type",
    "test_count", "sample_count", "device_count",
    "minimum_latency", "multi_server_latency", "multi_server_jitter",
    "download_speed", "upload_speed", "download_speed_mbps", "upload_speed_mbps",
    "_source_file", "_source_sheet", "_import_time",
}


def test_full_schema_keeps_device_coalesce():
    """表里有 device 时仍是原来的 COALESCE 语义（不改变既有口径）。"""
    sql = cal.base_sql(FULL_COLUMNS)
    assert "COALESCE(NULLIF(device, ''), 'all') AS device" in sql


def test_missing_device_falls_back_to_literal_all():
    """缺 device 列时**不得**再引用该列（否则 PG 直接 UndefinedColumn）。"""
    sql = cal.base_sql(FULL_COLUMNS - {"device"})
    assert "'all' AS device" in sql
    assert "NULLIF(device" not in sql
    assert "COALESCE(device" not in sql


def test_required_columns_are_still_projected():
    """可缺列只限 device；必需列一个都不能少（少了就是数据不可用，应报错而非静默空图）。"""
    sql = cal.base_sql(FULL_COLUMNS - {"device"})
    for fragment in (
        "provider",
        "location",
        "technology_type",
        "metric_type",
        "_source_file",
        "_import_time",
        "device_count AS devices",
        "download_speed_mbps AS dl",
        "multi_server_jitter  AS jit",
    ):
        assert fragment in sql


def test_none_means_full_schema():
    """不传 columns 的旧调用按完整表结构处理（仅供测试/一次性脚本）。"""
    assert "COALESCE(NULLIF(device" in cal.base_sql()
