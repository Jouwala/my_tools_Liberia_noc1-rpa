# -*- coding: utf-8 -*-
"""县名归一化的契约测试。

背景（2026-11-04）：`db/ZTE OLR MS Master Site Database 20261103.xlsx` 的
「Province/County」列自带 3 种脏值（Monsteraddo / Rivercess / River cess，
共 7 行），顺带污染了派生表 `cm_site_summary`。归一化在**导入写库前**执行，
本测试守住三条契约：

  1. 大小写 / 空格变体靠紧凑键自动收敛（不为每种变体写规则）
  2. 拼写错误只认**显式别名表**，不做模糊匹配（避免 Grand Bassa / Grand Cape Mount 混淆）
  3. 认不出就原样返回 —— 不猜、不置空
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.county_normalize import (  # noqa: E402
    LIBERIA_COUNTIES, audit_counties, compact_key, normalize_admin_columns,
    normalize_county,
)


def test_fifteen_counties_and_river_cess_canonical():
    """利比里亚共 15 个县，River Cess 的标准写法带空格。"""
    assert len(LIBERIA_COUNTIES) == 15
    assert len(set(LIBERIA_COUNTIES)) == 15
    assert "River Cess" in LIBERIA_COUNTIES
    assert "Montserrado" in LIBERIA_COUNTIES


@pytest.mark.parametrize("raw,expected", [
    ("Monsteraddo", "Montserrado"),      # Excel 笔误
    ("Rivercess", "River Cess"),         # 少空格
    ("River cess", "River Cess"),        # 大小写
    ("RIVER CESS", "River Cess"),        # 全大写
    ("  River   Cess  ", "River Cess"),  # 多空格 + 首尾空白
    ("grand-bassa", "Grand Bassa"),      # 连字符（紧凑键匹配）
    ("Montserrado", "Montserrado"),      # 标准值幂等
])
def test_variants_collapse(raw, expected):
    assert normalize_county(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_blank_stays_blank(raw):
    assert normalize_county(raw) == ""


def test_unknown_is_passed_through_not_guessed():
    """认不出就原样返回 —— 绝不模糊匹配到某个"看起来像"的县。"""
    assert normalize_county("Unknown County") == "Unknown County"
    assert normalize_county("Grand") == "Grand"
    # 只差一个字母也不猜（Grand Bassa vs Grand Cape Mount 这类最容易混）
    assert normalize_county("Grand Basa") == "Grand Basa"


def test_json_placeholder_is_not_touched():
    """告警表的 province 列存的是 JSON 占位，不是县名 —— 必须原样返回。"""
    raw = '{"displayname": {"en": "", "zh": ""}, "value": "empty"}'
    assert normalize_county(raw) == raw


def test_compact_key():
    assert compact_key("River Cess") == compact_key("rivercess") == "rivercess"
    assert compact_key(None) == ""


def test_audit_lists_only_changed_values():
    audit = audit_counties(["Monsteraddo", "Monsteraddo", "Nimba", "Rivercess", ""])
    got = {(raw, norm, n) for raw, norm, n in audit}
    assert got == {("Monsteraddo", "Montserrado", 2), ("Rivercess", "River Cess", 1)}


def test_normalize_admin_columns_inplace():
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({
        "Site ID": ["1", "2", "3", "4"],
        "province_county": ["Monsteraddo", "Rivercess", "River cess", "Nimba"],
        "other": ["a", "b", "c", "d"],
    })
    fixed = normalize_admin_columns(df)
    assert list(df["province_county"]) == ["Montserrado", "River Cess", "River Cess", "Nimba"]
    assert "province_county" in fixed
    assert sum(n for _, _, n in fixed["province_county"]) == 3
    # 非县列不受影响
    assert list(df["other"]) == ["a", "b", "c", "d"]


def test_normalize_admin_columns_ignores_clean_frame():
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"province_county": ["Nimba", "Bong"]})
    assert normalize_admin_columns(df) == {}
