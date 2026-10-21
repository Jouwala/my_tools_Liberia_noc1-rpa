"""「负责的站点」口径守卫 —— `master_site_db.fme_name` 的解析（2026-10-21 改口径时立）。

人员位置地图（`?page=person`）的站点集合、徽标「站点数」、KPI「Sites」、
下钻抽屉「站点」页签**全部**依赖这一个解析函数。库里 `fme_name` 的写法不统一
（单人 / 双人共担 / 双空格 / `/` 左右带空格），解析错一档，地图上就会出现
「这个人少了 98 个站」或「两个人共用站只算给一个」这类静默错数。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.routers.personnel import _fme_keys  # noqa: E402


def test_single_owner():
    assert _fme_keys("Mark D. Paye") == {"mark d. paye"}


def test_two_owners_share_the_site():
    """实测两种双人写法：`A / B` 与 `A /B`（斜杠后无空格），都两边都算。"""
    assert _fme_keys("Ernest Feikai  Sherman / Darlington Rue") == {
        "ernest feikai sherman", "darlington rue"}
    assert _fme_keys("Fedesco Pelleh /Alex Nagbe") == {
        "fedesco pelleh", "alex nagbe"}


def test_blank_and_none_yield_nothing():
    assert _fme_keys(None) == set()
    assert _fme_keys("") == set()
    assert _fme_keys("   ") == set()
    # 只有分隔符，不能凭空造出一个负责人
    assert _fme_keys(" / ") == set()


def test_repeated_name_counts_once():
    """同一个人写两遍（脏数据）不能让站点数翻倍 —— 返回的是 set。"""
    assert _fme_keys("Alex Nagbe / Alex Nagbe") == {"alex nagbe"}
