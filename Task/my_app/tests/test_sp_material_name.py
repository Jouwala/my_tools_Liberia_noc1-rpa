# -*- coding: utf-8 -*-
"""SP 物料主数据名字解析守卫（pytest，不连库、不碰生产文件）。

## 为什么有这个测试

2026-11-06 查明：上游 SFTP 明细里的 `Material Name` 是**单据导出那一刻**的快照名，
物料在 eFlow 改名后历史单据不回写。`Summary-Current` 以 Material Name 为主键，
于是同一物料裂成两行、入库/出库/库存被拆开（当天 SpareParts 4 组、86 行受影响）。
修复是把「按 `Material No.` 取 `sp_material` 最新名」收敛成
`backend/services/sp_material_name.py` 一处，由报表生成器与明细落库共用。

本测试钉死四件事，防止口径再分叉：

1. 物料号归一（前导零 / Excel 数字形式）两侧对得上，否则大面积不命中 = 等于没改。
2. **命中才覆盖，未命中保留原值** —— 名字不允许被清空成 `''` 或 `Unknown`。
3. **`|` 是合法字符**：主数据 979 条里 510 条名字本身含 `|`，禁止出现任何字符清洗。
4. 解析实现只有一份：生成器不得再自带一套读主数据的 SQL。
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from backend.services.sp_material_name import (
    NAME_COL, NO_COL, normalize_dataframe, normalize_rows, norm_key)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = PROJECT_ROOT / "backend" / "services" / "sp_report_gen" / "gernarate_sp_report.py"
MODULE_SRC = PROJECT_ROOT / "backend" / "services" / "sp_material_name.py"

LUT = {
    "122630731000": "Chassis (NR9000TR)",                    # 主数据已去掉结尾 |
    "180000413323": "Fan unit A(High anti-corrosion)",
    "122630731001": "Chassis (NR9000TR)|",                   # 主数据本身就带 |
    "33030100337": "DTB_B|Digital Trunk Board|",             # 名字中间的 | 也要原样保留
}


def _df(*rows):
    return pd.DataFrame(list(rows), columns=[NO_COL, NAME_COL, "Material Type"])


# ---------------------------------------------------------------- 物料号归一
@pytest.mark.parametrize("raw,expected", [
    ("033030100337", "33030100337"),      # 明细文本带前导零
    (33030100337, "33030100337"),         # Excel 存成整数
    ("33030100337.0", "33030100337"),     # 被读成浮点
    ("  122630731000 ", "122630731000"),  # 前后空白
    ("", ""),
    (None, ""),
    (float("nan"), ""),
    ("DTB_B", "DTB_B"),                   # 非数字原样
])
def test_norm_key_aligns_text_and_number(raw, expected):
    assert norm_key(raw) == expected


def test_leading_zero_rows_still_hit():
    """明细写前导零、主数据不带，也必须命中（否则等于本次修复没生效）。"""
    df = _df(("033030100337", "旧名", "SpareParts"))
    stats = normalize_dataframe(df, name_lut=LUT)
    assert stats["changed"] == 1 and stats["missing"] == 0
    assert df.loc[0, NAME_COL] == "DTB_B|Digital Trunk Board|"


# ---------------------------------------------------------------- 覆盖语义
def test_hit_overwrites_and_counts():
    df = _df(("122630731000", "Chassis (NR9000TR)|", "SpareParts"),
             ("180000413323", "Fan unit A(High anti-corrosion)", "SpareParts"))
    stats = normalize_dataframe(df, name_lut=LUT)
    assert stats["changed"] == 1          # 第二行本来就和主数据一致，不计入改动
    assert stats["missing"] == 0
    assert df[NAME_COL].tolist() == ["Chassis (NR9000TR)", "Fan unit A(High anti-corrosion)"]


def test_miss_keeps_original_never_blanks():
    """主数据缺档必须保留原值：把名字清空会让页面出现空物料。"""
    df = _df(("999999999999", "Upstream Keeps This", "SpareParts"))
    stats = normalize_dataframe(df, name_lut=LUT)
    assert stats["missing"] == 1 and stats["changed"] == 0
    assert df.loc[0, NAME_COL] == "Upstream Keeps This"


def test_master_pipe_names_survive():
    """`|` 结尾是主数据自己的合法值，覆盖后必须原样出现。"""
    df = _df(("122630731001", "随便一个旧名", "SpareParts"))
    normalize_dataframe(df, name_lut=LUT)
    assert df.loc[0, NAME_COL] == "Chassis (NR9000TR)|"


def test_type_column_untouched_without_explicit_lut():
    """Material Type 默认不动：两张总表按它拆分 SpareParts / Consumables。"""
    df = _df(("122630731000", "旧名", "SpareParts"))
    stats = normalize_dataframe(df, name_lut=LUT)
    assert stats["type_changed"] == 0
    assert df.loc[0, "Material Type"] == "SpareParts"


def test_type_overwrite_needs_both_args():
    df = _df(("122630731000", "旧名", "Consumables"))
    stats = normalize_dataframe(df, name_lut=LUT,
                               type_col="Material Type", type_lut={"122630731000": "SpareParts"})
    assert stats["type_changed"] == 1
    assert df.loc[0, "Material Type"] == "SpareParts"


def test_missing_columns_skip_without_raising():
    """上游改表头（缺 Material No.）时不能抛异常，只能报告跳过。"""
    df = pd.DataFrame([{"Material Name": "X"}])
    stats = normalize_dataframe(df, name_lut=LUT)
    assert stats.get("skipped") and "Material No." in stats["skipped"]

    df2 = pd.DataFrame([{"Material No.": "122630731000"}])
    assert "Material Name" in normalize_dataframe(df2, name_lut=LUT).get("skipped", "")


# ---------------------------------------------------------------- SheetData 版
def test_normalize_rows_hit_miss_and_counts():
    columns = ["Serial No.", NO_COL, NAME_COL]
    rows = [["S1", "122630731000", "Chassis (NR9000TR)|"],
            ["S2", "122630731001", "Chassis (NR9000TR)|"],
            ["S3", "999999999999", "Keep Me"]]
    stats = normalize_rows(columns, rows)   # 走真实主数据前先看结构：无库时会被跳过
    if stats.get("skipped"):                # CI 环境没有库，主数据不可用属预期
        assert stats["skipped"] == "主数据不可用"
        return
    assert stats["changed"] + stats["missing"] > 0
    assert rows[2][2] == "Keep Me"          # 未命中永远保留原值


def test_normalize_rows_without_material_columns():
    stats = normalize_rows(["Ticket No.", "Title"], [["T1", "x"]])
    assert "缺" in stats.get("skipped", "")


# ---------------------------------------------------------------- 单一真相源
def test_generator_does_not_own_its_master_query():
    """生成器不得自带一套读主数据的实现（口径只能有一份）。"""
    src = GENERATOR.read_text(encoding="utf-8")
    assert "from backend.services.sp_material_name import" in src
    assert "def load_material_maps_from_db" not in src, "主数据查询应只在 sp_material_name.py"
    assert 'information_schema' not in src, "生成器里不该再出现库内自省 SQL"
    # 旧实现名不允许复活
    assert "apply_inventory_fields" not in src
    assert not re.search(r"def\s+_overlay_column\s*\(", src)


def test_no_pipe_scrubbing_anywhere():
    """禁止「去掉结尾 |」这类字符清洗：510 条主数据名字本身就含 |。"""
    for path in (MODULE_SRC, GENERATOR):
        src = path.read_text(encoding="utf-8")
        assert not re.search(r'\.rstrip\(\s*"\|"\s*\)', src), f"{path.name} 出现了 | 清洗"
        assert not re.search(r'\.replace\(\s*"\|"', src), f"{path.name} 出现了 | 清洗"


def test_master_refresh_runs_before_generation():
    """Step 0 必须存在：04:55 的主数据快照早于当天白天的改名，报表会用到旧名。"""
    src = GENERATOR.read_text(encoding="utf-8")
    assert "def refresh_material_master()" in src
    assert "from backend.services.sp_material_sync import run_sp_material_sync" in src
    body = src.split("def main()")[1]
    assert "refresh_material_master()" in body.split("sftp_download()")[0]
    # 刷新后必须作废缓存，否则拿到的还是改名前的映射
    assert "load_material_maps(force_refresh=True)" in src


def test_all_five_details_are_normalized():
    """五份明细 + 五份原始快照都要过名字归一：漏 inventory 就照样裂行。"""
    src = GENERATOR.read_text(encoding="utf-8")
    body = src.split("def apply_material_master_fields")[1]
    for token in ("INB_PATH", "OUTB_PATH", "INV_PATH", "TRANSFER_PATH",
                  "TRANSFER_RETURN_PATH", "DETAIL_PATHS"):
        assert token in body, f"归一范围少了 {token}"
