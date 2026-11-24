# -*- coding: utf-8 -*-
"""IP RAN 看板 ME/端口改名自适应 + 月度未完成行过滤（2026-11-16）。

背景：UME 改名后，native_catalog 里按旧名生成的 SQL 会永远查不到数据
（`9000-3EA_LBS_UPE59` → `M6K_2s16_LBS_UPE59`）；端口名也会随设备换代变化。
本文件锁住「自动改名 + 端口按速率后缀/历史均值匹配」以及「月度表不画未完成
当月」两条行为。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_parse_me_from_mosname():
    from backend.services.ipran_me_alias import _me_from_mosname

    assert _me_from_mosname('"6180H-A_RIA_UPE24"-"OIXG4A[0-1-7]-10GE:2"') == "6180H-A_RIA_UPE24"
    assert _me_from_mosname('M6k_2s16_Buchanan2_UPE77-"RPN-04XGL-H-VIRTUAL[0-0-1-0]-10GE:2"') == "M6k_2s16_Buchanan2_UPE77"
    # 整串都是「ME-MO」、没有引号分隔 → 不可靠，跳过（不能把 SmartGroup:20 当成 ME）
    assert _me_from_mosname("M6K_2s16_Gbarnga_UPE76-SmartGroup:20") == ""


def test_match_ports_prefers_same_suffix_and_closest_average():
    from backend.services.ipran_me_alias import _match_ports

    old = {"P90E-2CGT-Q28[0-0-2-0]-100GE:1": 6958.0}
    new = {
        "RPN-02CG-H-VIRTUAL[0-0-7-0]-100GE:1": 7151.0,
        "RPN-02CG-H-VIRTUAL[0-0-15-0]-100GE:1": 120.0,
        "RPN-04XGL-H-VIRTUAL[0-0-4-0]-10GE:1": 7000.0,
    }
    assert _match_ports(old, new) == {
        "P90E-2CGT-Q28[0-0-2-0]-100GE:1": "RPN-02CG-H-VIRTUAL[0-0-7-0]-100GE:1"}


def test_apply_sql_and_text_use_alias(monkeypatch):
    from backend.services import ipran_me_alias as a

    monkeypatch.setattr(a, "aliases", lambda: {
        "9000-3EA_LBS_UPE59": {
            "new": "M6K_2s16_LBS_UPE59",
            "table": "Metro_ring_me_15mins",
            "ports": {"P90E-2CGT-Q28[0-0-2-0]-100GE:1":
                      "RPN-02CG-H-VIRTUAL[0-0-7-0]-100GE:1"},
        }
    })
    sql = ('SELECT 1 FROM "Metro_ring_me_15mins" WHERE "ME"=\'9000-3EA_LBS_UPE59\' '
           'AND "Measure Object"=\'P90E-2CGT-Q28[0-0-2-0]-100GE:1\'')
    out = a.apply_sql(sql)
    assert '"ME"=\'M6K_2s16_LBS_UPE59\'' in out
    assert '"Measure Object"=\'RPN-02CG-H-VIRTUAL[0-0-7-0]-100GE:1\'' in out
    assert a.apply_text('"9000-3EA_LBS_UPE59"-"P90E-2CGT-Q28[0-0-2-0]-100GE:1"') == \
        '"M6K_2s16_LBS_UPE59"-"RPN-02CG-H-VIRTUAL[0-0-7-0]-100GE:1"'


def test_apply_sql_no_alias_is_noop(monkeypatch):
    from backend.services import ipran_me_alias as a

    monkeypatch.setattr(a, "aliases", lambda: {})
    sql = 'SELECT 1 FROM t WHERE "ME"=\'X\''
    assert a.apply_sql(sql) == sql


def test_drop_future_month_rows():
    from backend.services.dashboard_service import _drop_future_month_rows

    now = datetime.now()
    this_month = now.strftime("%Y-%m")
    next_month = (now.replace(day=28) + timedelta(days=5)).strftime("%Y-%m")
    rows = [[this_month, 1], [next_month, 2], ["2026-01", 3]]
    out = _drop_future_month_rows(rows)
    assert [r[0] for r in out] == [this_month, "2026-01"]
