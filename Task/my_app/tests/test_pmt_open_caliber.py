"""PMT「未关闭」与「归属到个人」的口径守卫（2026-10-21 给地图徽标加 PMT 时立）。

三条规则都**不与 WO 共用**，且都是改一行就会静默坏掉、界面数字错了也没人发现的：

1. **PMT 终态用精确 `Closed`**，WO 才用前缀 `closed*`。
   `eflow_wo` 实测有 `Closed_Confirmed` 这类衍生值所以要前缀；`eflow_pm` 的 6 个
   状态（`Wait Accept` / `Closed` / `Wait FLM Leader Approve` / `Wait Process` /
   `Transfer` / `Wait PM Manager Approve`）里只有精确 `Closed` 是终态。
   两边共用前缀匹配，将来 eFlow 给 PMT 加一个衍生终态就会**静默扩大**已关闭集合。
2. **`G:` 组池不计入任何个人** —— 挂到个人头上会把整个组的单算给一个人。
   实测 1715 张未关闭 PMT 里 821 张只挂在组池上，它们谁都不算，
   总数走 `/personnel/stats` 的 `pmt.group_pool` 在界面 ⓘ 里说明。
3. **一条 PMT 挂多人时每人各计一次**（不是把 1 拆成 1/N）。
   与 WO 侧 `_wo_person_keys` 的既有行为一致，徽标求和因此可以大于总单数。

另外锁住「PMT 不套时间窗口」这条决策的可观察后果：`_pmt_open_index` 的签名
不接受窗口参数（见 personnel.py 的 `_pmt_open_index` 文档字符串第 1 条）。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.routers.personnel import (  # noqa: E402
    _PMT_COLS, _handler_person_keys, _is_closed, _is_pmt_closed,
)
from backend.services import pm_caliber  # noqa: E402


def test_pmt_detail_select_is_valid_sql():
    """把端点那条 SELECT 真跑一次（`LIMIT 0`）。

    `_PMT_COLS` 是拼进 SELECT 的裸列名，库里某列被改名/删掉就是整页 500。
    直接执行比查 information_schema 可靠 —— 实测 eflow_pm 在 PG 的
    `eflow` 与 `app` 两个 schema 里都有，按 table_name 查列名会拿到两套的并集。
    表整个不存在时跳过：那是旧部署，徽标与页签两侧都会降级成 `—`，不是缺陷。
    """
    from backend.database import get_raw_connection
    from backend.dialect_helpers import list_table_names

    with get_raw_connection() as conn:
        if pm_caliber.TABLE not in set(list_table_names(conn)):
            pytest.skip(f"{pm_caliber.TABLE} 不在本库（旧部署）")
        conn.execute(
            f"SELECT {', '.join(_PMT_COLS)} FROM {pm_caliber.TABLE} LIMIT 0"
        ).fetchall()


def test_pmt_closed_is_exact_match_not_prefix():
    """PMT 只认精确 Closed —— 这是与 WO 的关键差异。"""
    assert _is_pmt_closed("Closed") is True
    assert _is_pmt_closed("  closed  ") is True          # 大小写与首尾空白容错
    assert _is_pmt_closed(None) is False
    assert _is_pmt_closed("") is False
    # WO 侧这些算已关闭（前缀匹配），PMT 侧必须**不算**
    assert _is_closed("Closed_Confirmed") is True
    assert _is_pmt_closed("Closed_Confirmed") is False
    assert _is_pmt_closed("Closed-Reject") is False
    # 实测的 5 个非终态
    for s in ("Wait Accept", "Wait Process", "Wait FLM Leader Approve",
              "Wait PM Manager Approve", "Transfer"):
        assert _is_pmt_closed(s) is False, s


def test_pmt_closed_stays_in_sync_with_pm_caliber():
    """判定必须跟 PM 分析页读同一个终态常量，否则两页的「未关闭」会各自漂移。"""
    assert pm_caliber.CLOSED_STATUS == "Closed"
    assert _is_pmt_closed(pm_caliber.CLOSED_STATUS) is True


def test_group_pool_never_counts_toward_a_person():
    assert _handler_person_keys("G:ZTE_FE_MG") == set()
    assert _handler_person_keys("G:ZTE_FE_MG,G:ZTE_FE_FE") == set()
    assert _handler_person_keys("") == set()
    assert _handler_person_keys(None) == set()
    # 组池 + 个人混合：只取个人那一段
    assert _handler_person_keys("P:Varfee Sarnor,G:ZTE_FE_MG") == {"varfee sarnor"}


def test_multi_person_ticket_counts_once_for_each():
    keys = _handler_person_keys("P:Fedesco Pelleh,P:Alex Nagbe,P:Varfee Sarnor")
    assert keys == {"fedesco pelleh", "alex nagbe", "varfee sarnor"}
    # 同一字段里重复出现同一个人 → 集合去重，不会计两次
    assert _handler_person_keys("P:Alex Nagbe,P:Alex Nagbe") == {"alex nagbe"}


def test_pmt_open_index_takes_no_time_window():
    """PMT 计数**不接受**窗口参数（用户 2026-10-21 确认：按当前全部未关闭）。

    锁签名而不是锁数值 —— 数值要连库，签名不连库也能挡住「顺手加个 days 参数」。
    """
    import inspect

    from backend.routers.personnel import _pmt_open_index

    params = inspect.signature(_pmt_open_index).parameters
    assert list(params) == ["conn"], params
    for banned in ("days", "time_start", "time_end"):
        assert banned not in params
