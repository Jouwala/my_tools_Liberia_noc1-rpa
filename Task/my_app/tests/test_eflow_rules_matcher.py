# -*- coding: utf-8 -*-
"""eFlow 规则匹配器回归测试（**纯离线**：不读数据库、不读 xlsx、不联网）。

覆盖 2026-10-23 修复的三类「静默失效」——它们的共同特征是
**不报错、不告警，只表现为一堆 No Match**，从而被误读成「规则覆盖缺口」：

  ① 无条件规则被当成「永不命中」
     规则 275 `other ticket P4`（ACTIVE / 优先级 5 / 级别 P4 / 条件为空）
     是兜底规则，但 `build_rule_mask` 对空条件返回全 False，
     实测 1000 张单里有 376 张（37.6%）落到 No Match。

  ② 规则引用的字段没被加载
     规则 266/268 用 `hubSite`、规则 272 用 `alarmDescription`，
     这两列在 DB 里都有，但 `build_value_frame` 没取，于是规则从未命中。

  ③ 缺失字段被静默吞掉
     `_eval_one` 发现字段不在 vf 里就返回 False，没有任何痕迹。
     现在必须记录下来，使缺口能在报告里被看见。

另外钉住「统计自洽」的三条恒等式，防止以后改统计口径时再次出现
「624 + 19 ≠ 1000」这种让人看不懂的展示。
"""
from __future__ import annotations

import pandas as pd
import pytest

from backend.services.eflow_rules import eflow_rules_matcher as M


# ------------------------------------------------------------------ #
# ① 无条件规则 = 兜底
# ------------------------------------------------------------------ #

def test_empty_conditions_match_all_rows():
    """空条件 → 全部命中（兜底），不是全部不命中。"""
    vf = pd.DataFrame({'alarmCode': ['a', 'b', 'c']})
    mask = M.build_rule_mask(vf, [])
    assert len(mask) == 3
    assert bool(mask.all()), '无条件规则必须兜住所有行，否则兜底规则形同废纸'


def test_empty_conditions_on_empty_frame():
    """空 DataFrame 上空条件也不能抛异常。"""
    vf = pd.DataFrame({'alarmCode': []})
    assert len(M.build_rule_mask(vf, [])) == 0


def test_fallback_does_not_steal_specific_rule_hits():
    """兜底规则排在最后时，不能抢走优先级更高的规则的命中。

    这是「空条件返回全 True」最需要守住的边界：如果 match_all 的
    pending 机制失效，兜底规则会把所有单子都算成 P4，P1/P2 全部消失。
    """
    vf = _match_frame([
        {'vip_site': 'Yes', 'alarm_code': '9910', 'ticket_severity': 'P2'},
        {'vip_site': 'No', 'alarm_code': '9910', 'ticket_severity': 'P4'},
    ])
    # 规则 A：VIP → P1；规则 B：无条件兜底 → P4
    rules = pd.DataFrame([
        {'ID': 1, '规则名称': 'VIP P1', '严重级别': 'P1', '优先级': 2,
         '条件': "AND | eflow_ticket_ticket_asset.vipSite = '1' (enums)"},
        {'ID': 2, '规则名称': 'fallback P4', '严重级别': 'P4', '优先级': 5,
         '条件': None},
    ])
    ready = M.prepare_rules(rules)
    out = M.match_all(vf, ready)
    assert out['Matched_Rule_ID'].tolist() == [1, 2]
    assert out['New_Severity'].tolist() == ['P1', 'P4']


# ------------------------------------------------------------------ #
# ② 规则字段必须被加载
# ------------------------------------------------------------------ #

def _match_frame(rows: list[dict]) -> pd.DataFrame:
    """构造能喂给 match_all 的最小 eflow_tt 表。

    `match_all` 结尾要用 `ticket_severity` 算变更，`build_value_frame` 要读
    一整套字段，所以这里统一补齐默认值，测试只写关心的那几列。
    """
    defaults = {
        'alarm_code': '', 'vip_site': 'No', 'hub_site': 'No',
        'site_type': 'NORMAL', 'site_information': 'REGULAR',
        'domain': 'RAN', 'down_site_count': '1',
        'alarm_description': '', 'ticket_severity': 'P4',
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


def _tt_frame(**overrides) -> pd.DataFrame:
    """构造一行最小 eflow_tt 数据，覆盖 build_value_frame 会用到的列。"""
    base = {
        'alarm_code': '9910', 'vip_site': 'No', 'hub_site': 'No',
        'site_type': 'NORMAL', 'site_information': 'REGULAR',
        'domain': 'RAN', 'down_site_count': '1', 'alarm_description': '',
    }
    base.update(overrides)
    return pd.DataFrame([base])


def test_hub_site_is_loaded_and_normalized():
    """DB 的 hub_site 是 Yes/No，规则写的是 '1' —— 必须归一化后才能匹配。"""
    vf = M.build_value_frame(_tt_frame(hub_site='Yes'))
    assert 'hubSite' in vf.columns, 'hubSite 没被加载，规则 266/268 永远无法命中'
    assert vf['hubSite'].iloc[0] == '1'

    vf_no = M.build_value_frame(_tt_frame(hub_site='No'))
    assert vf_no['hubSite'].iloc[0] == '0'


def test_alarm_description_is_loaded():
    desc = 'Board power-off due to overtemperature protection'
    vf = M.build_value_frame(_tt_frame(alarm_description=desc))
    assert 'alarmDescription' in vf.columns, 'alarmDescription 没被加载，规则 272 永远无法命中'
    assert vf['alarmDescription'].iloc[0] == desc


# ------------------------------------------------------------------ #
# ③ 缺失字段必须被记录，而不是静默按 False 处理
# ------------------------------------------------------------------ #

def test_missing_field_is_recorded():
    M.reset_missing_fields()
    vf = pd.DataFrame({'alarmCode': ['9910']})
    conds = M.parse_conditions(
        "AND | eflow_ticket_ticket_wo.downstreamSites >= '5' (number)")
    mask = M.build_rule_mask(vf, conds, rule_id=266)

    assert not bool(mask.any()), '字段取不到时应保守按未命中处理'
    missing = M.get_missing_fields()
    assert 'downstreamSites' in missing, '缺失字段必须被记录，否则缺口无法被发现'
    assert 266 in missing['downstreamSites']


def test_reset_missing_fields_clears_state():
    M.reset_missing_fields()
    vf = pd.DataFrame({'alarmCode': ['9910']})
    M.build_rule_mask(vf, M.parse_conditions(
        "AND | eflow_ticket_ticket_wo.nonExistentField = 'x' (string)"), rule_id=1)
    assert M.get_missing_fields(), '前置条件：应已记录缺失字段'
    M.reset_missing_fields()
    assert M.get_missing_fields() == {}, '新一轮匹配前必须清空，否则上轮结果会串过来'


# ------------------------------------------------------------------ #
# 统计自洽
# ------------------------------------------------------------------ #

def test_stats_identities_hold():
    """总记录 = 匹配 + 未匹配；匹配 = 一致 + 变更；变更 ⊆ 匹配。"""
    vf = _match_frame([
        {'vip_site': 'Yes', 'alarm_code': '9910', 'ticket_severity': 'P2'},
        {'vip_site': 'No', 'alarm_code': '9999', 'ticket_severity': 'P4'},
        {'vip_site': 'No', 'alarm_code': '9999', 'ticket_severity': 'P3'},
        {'vip_site': 'No', 'alarm_code': '9910', 'ticket_severity': 'P2'},
    ])
    rules = pd.DataFrame([
        {'ID': 1, '规则名称': 'VIP P1', '严重级别': 'P1', '优先级': 2,
         '条件': "AND | eflow_ticket_ticket_asset.vipSite = '1' (enums)"},
    ])
    out = M.match_all(vf, M.prepare_rules(rules))
    # 没有兜底规则时，未命中的行保持 No Match
    total = len(out)
    matched = int((out['Matched_Rule_ID'] != 'No Match').sum())
    changed = int((out['Severity_Changed'] == 'YES').sum())

    assert matched + (total - matched) == total
    assert changed <= matched
    # 本用例里只有 1 行 VIP，其余 3 行无规则可匹配
    assert matched == 1 and changed == 1 and total == 4


def test_unmatched_rows_are_not_counted_as_changed():
    """No Match 的行不能被算成「级别变更」——否则变更数会凭空多出来。"""
    vf = _match_frame([{'alarm_code': 'x', 'ticket_severity': 'P1'}])
    rules = pd.DataFrame([
        {'ID': 9, '规则名称': 'never matches', '严重级别': 'P4', '优先级': 5,
         '条件': "AND | eflow_ticket_ticket_wo.alarmCode = 'zzz' (string)"},
    ])
    out = M.match_all(vf, M.prepare_rules(rules))
    assert out['Matched_Rule_ID'].iloc[0] == 'No Match'
    assert out['Severity_Changed'].iloc[0] == 'NO'


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
