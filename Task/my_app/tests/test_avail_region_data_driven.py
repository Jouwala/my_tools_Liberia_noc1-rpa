# -*- coding: utf-8 -*-
"""区域（region）必须是**数据驱动**，不能写死在代码里。

背景（2026-11-04 事故）：`avail_flm_service.FLM_REGIONS` 曾把
("Montserrado","North East","South West") 当白名单过滤，站点主数据换成
North/South 后整页被筛成空表；同时派生库重建仍读远端老主库，导致
「矩阵按老区、TT 按新区」，点格子下钻恒空。

本测试守住三条契约：
  1. 代码里不设默认区域名（区域顺序只能由环境变量 AVAIL_REGION_ORDER 给）
  2. `_flm_regions` / `regions_in` 完全由传入的行决定
  3. 主数据列名换了也能读出来（大小写 / 命名的自适应）
"""
from __future__ import annotations

import os
import sys
from collections import namedtuple

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import avail_flm_service as flm  # noqa: E402
from backend.services import avail_ms_service as ms  # noqa: E402
from backend.services import avail_recon_sync as ars  # noqa: E402

Row = namedtuple("Row", "day tech region cell_group numerator denominator wk month")


def mkrow(region: str, tech: str = "4G") -> Row:
    return Row("2026-11-03", tech, region, f"{tech} FDD Regular", 90, 100, "2026-W45", "2026-11")


def test_no_default_region_names_in_code():
    """没配 AVAIL_REGION_ORDER 时，默认前缀必须为空 —— 代码里不留任何区域名。"""
    assert ms._region_order_from_env() == ()
    assert ms.PREFERRED_REGIONS == ()


def test_flm_regions_follow_data():
    """区域集合由行决定：换成 North/South 就返回 North/South，换成新名字也一样。"""
    rows = [mkrow("North"), mkrow("North"), mkrow("South")]
    assert flm._flm_regions(rows) == ["North", "South"]

    new_rows = [mkrow("Central"), mkrow("South East"), mkrow("Montserrado")]
    assert flm._flm_regions(new_rows) == ["Central", "Montserrado", "South East"]


def test_row_keys_are_data_driven_and_keep_unmatched():
    """行 = 数据里的区域；有未匹配站点时末行补 UNMATCHED。"""
    rows = [mkrow("North"), mkrow("")]
    assert flm._row_keys(rows) == ["North", flm.ROW_UNMATCHED]

    # 纯数据、无未匹配：行就是区域本身，不再"三个区域恒在"
    assert flm._row_keys([mkrow("South")]) == ["South"]


def test_display_order_env_is_hint_not_whitelist(monkeypatch):
    """AVAIL_REGION_ORDER 只影响顺序：没列到的区域仍然出现（不被静默吞掉）。"""
    monkeypatch.setenv("AVAIL_REGION_ORDER", "South")
    assert ms._region_order_from_env() == ("South",)

    rows = [mkrow("North"), mkrow("South"), mkrow("Central")]
    got = ms._regions_in(rows)
    assert got[0] == "South"                          # 配置的排最前
    assert set(got) == {"South", "North", "Central"}  # 其余照常出现


def test_normalize_region_passes_through_unknown():
    """不认识（但合法）的区域名原样透传，不再被吞成 ALL。"""
    assert flm.normalize_region("") == ms.REGION_ALL
    assert flm.normalize_region("North") == "North"
    assert flm.normalize_region("Brand New Region") == "Brand New Region"


@pytest.mark.parametrize("cols,expected_region,expected_name", [
    (["site_id", "site_name", "region"], "region", "site_name"),      # 本机 PG
    (["Site_ID", "Site_Name", "Region"], "Region", "Site_Name"),      # 远端 SQLite
    (["id", "name", "FME_Region"], "FME_Region", "name"),             # 历史列名
])
def test_pick_col_is_case_insensitive(cols, expected_region, expected_name):
    assert ars._pick_col(cols, ars._REGION_COLS, "Region", "t") == expected_region
    assert ars._pick_col(cols, ars._SITE_NAME_COLS, "站点名", "t") == expected_name


def test_pick_col_raises_with_real_columns():
    """找不到列就报错并带上真实列名，绝不静默用错列。"""
    with pytest.raises(ars.AvailReconError) as ei:
        ars._pick_col(["a", "b"], ars._REGION_COLS, "Region", "master_site_db")
    assert "master_site_db" in str(ei.value)
    assert "['a', 'b']" in str(ei.value) or "a" in str(ei.value)
