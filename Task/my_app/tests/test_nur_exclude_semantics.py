"""NUR Exclude 三档语义回归测试。

=========================== 背景 ===========================
2026-10-06 用户报了一个**方向性错误**：Exclude 的 Y/N 语义被实现反了。
修正前的实现是：

    df = df[df["excluded"] == exclude]

即 `Y` = **只保留**名单内的单、`N` = 只保留名单外的单 —— 那是"筛选出名单"，
不是"排除名单"。实测（名单 46 单全在 2026-08-03~09）：旧实现 `Y`=46 / `N`=1061。

业务确认的正确语义：

| Exclude | 含义 |
| --- | --- |
| 空值 | **全部**参与计算，**完全不看** TT_Exclude |
| `N`  | 全部参与计算，不看 TT_Exclude（与空值同义） |
| `Y`  | 从**全部**里**扣掉**名单内的单 |

所以 Y 不是"名单内"，而是"全部 − 名单内"。这三条断言就是需求本身，
**改这里的期望值前先确认用户是否改了要求**。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import nur_calc  # noqa: E402


# 名单覆盖周：46 个票号全落在 2026-08-03 ~ 2026-08-09
LIST_WEEK = ("2026-08-03", "2026-08-09")
# 名单不涉及的窗口：三档必须完全一致
OTHER_WEEK = ("2026-09-15", "2026-09-15")


def _total(start: str, end: str, exclude: str) -> int:
    info = nur_calc.get_exclude_info()
    if not info.get("count"):
        pytest.skip("排除名单为空，无法验证 Y/N 语义（需要先上传或播种名单）")
    r = nur_calc.compute_overview(start=start, end=end, exclude=exclude)
    return r["tt_total"]


def test_blank_and_N_are_both_full_set():
    """空值与 N 同义：都返回全量，不看名单。"""
    assert _total(*OTHER_WEEK, "") == _total(*OTHER_WEEK, "N")


def test_blank_ignores_list_entirely():
    """空值不看名单 —— 在名单覆盖周，空值必须等于该周全量（即等于 N）。"""
    assert _total(*LIST_WEEK, "") == _total(*LIST_WEEK, "N")


def test_Y_subtracts_the_list():
    """Y = 全部 − 名单内。名单覆盖周里 Y 必须严格小于全量。"""
    full = _total(*LIST_WEEK, "N")
    y = _total(*LIST_WEEK, "Y")
    assert y < full, "Y 应当扣掉名单内的单，必须小于全量"


def test_Y_equals_full_when_list_not_involved():
    """名单不涉及的窗口，Y 扣掉空集 = 全量。"""
    assert _total(*OTHER_WEEK, "Y") == _total(*OTHER_WEEK, "N")


def test_Y_is_not_the_list_itself():
    """**这条是防回归的核心**：Y 绝不能退化成"只保留名单内的单"。

    旧 bug 的特征是 Y 恰好等于名单条数（46）。现在名单覆盖周里，
    Y 应当接近该周全量（扣掉几十单），而不该是几十这个量级。
    """
    info = nur_calc.get_exclude_info()
    n_list = int(info.get("count") or 0)
    y = _total(*LIST_WEEK, "Y")
    assert y > n_list * 5, (
        f"Y={y} 接近名单条数({n_list})，疑似退化成「只保留名单内的单」（旧 bug）"
    )
