#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TT 单分析的规则匹配单测。

    python scripts/test-tt-rules.py

覆盖三块「错了会给出错误级别建议」的逻辑：
    条件解析、运算符求值、AND/OR 左折叠。
不依赖工单库，只用规则表 + 构造数据，可离线跑。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

def _load_module():
    """tt-analyze.py 文件名带连字符，不能直接 import，用 importlib 从路径加载。"""
    import importlib.util

    path = os.path.join(HERE, 'tt-analyze.py')
    spec = importlib.util.spec_from_file_location('tt_analyze', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tt = _load_module()

pass_n = 0
fail_n = 0


def check(cond, label, detail=''):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print(f'  ✓ {label}')
    else:
        fail_n += 1
        print(f'  ✗ {label}' + (f'\n      {detail}' if detail else ''))


# ------------------------------------------------------------------ #
print('\n[1] 条件解析 parse_conditions')

conds = tt.parse_conditions(
    "AND | eflow_ticket_ticket_wo.alarmCode in '9970, 9980' (string); "
    "OR | eflow_ticket_ticket_wo.vipSite = '1' ()"
)
check(len(conds) == 2, f'解析出 2 条条件（实际 {len(conds)}）')
check(conds[0]['or_and'] == 'AND' and conds[1]['or_and'] == 'OR', '连接符解析正确')
check(conds[0]['field'] == 'alarmCode', '字段名取点号最后一段（alarmCode）')
check(conds[0]['symbol'] == 'in', 'in 运算符识别正确')
check(conds[0]['values'] == ['9970', '9980'], f'in 的值拆成列表（{conds[0]["values"]}）')
check(conds[1]['values'] == ['1'], '= 的值保持单元素')

# 关键回归：>= 不能被误吞成 =
c = tt.parse_conditions("AND | eflow_ticket_ticket_wo.downSiteCount >= '5' ()")
check(c and c[0]['symbol'] == '>=', f'>= 不被误吞为 =（实际 {c[0]["symbol"] if c else "空"}）')

c = tt.parse_conditions("OR | eflow_ticket_ticket_wo.netWorkType not in 'RAN, MW' (string)")
check(c and c[0]['symbol'] == 'notin', f'not in 归一化为 notin（实际 {c[0]["symbol"] if c else "空"}）')

check(tt.parse_conditions('') == [], '空条件 → 空列表')
check(tt.parse_conditions(None) == [], 'None → 空列表')

# ------------------------------------------------------------------ #
print('\n[2] 单条件求值 eval_one')

vf = {
    'alarmCode': '99933',
    'vipSite': '0',
    'siteSubType': 'ERA',
    'netWorkType': 'RAN',
    'downSiteCount': '3',
}

check(tt.eval_one(vf, {'field': 'alarmCode', 'symbol': '=', 'values': ['99933']}), '= 相等命中')
check(not tt.eval_one(vf, {'field': 'alarmCode', 'symbol': '=', 'values': ['9995']}), '= 不等不命中')
check(tt.eval_one(vf, {'field': 'alarmCode', 'symbol': 'in', 'values': ['9995', '99933']}), 'in 命中')
check(not tt.eval_one(vf, {'field': 'alarmCode', 'symbol': 'in', 'values': ['9995']}), 'in 不命中')
check(tt.eval_one(vf, {'field': 'alarmCode', 'symbol': 'notin', 'values': ['9995']}), 'notin 命中')
check(tt.eval_one(vf, {'field': 'downSiteCount', 'symbol': '>=', 'values': ['3']}), '>= 边界相等命中')
check(tt.eval_one(vf, {'field': 'downSiteCount', 'symbol': '>', 'values': ['2']}), '> 命中')
check(not tt.eval_one(vf, {'field': 'downSiteCount', 'symbol': '>', 'values': ['3']}), '> 边界不命中')
check(tt.eval_one(vf, {'field': 'downSiteCount', 'symbol': '<=', 'values': ['3']}), '<= 边界相等命中')
check(tt.eval_one(vf, {'field': 'vipSite', 'symbol': '!=', 'values': ['1']}), '!= 命中')
check(not tt.eval_one(vf, {'field': '不存在的字段', 'symbol': '=', 'values': ['x']}), '字段缺失 → False')
check(
    not tt.eval_one(vf, {'field': 'alarmCode', 'symbol': '>', 'values': ['abc']}),
    '数值比较遇非数字 → False（不抛异常）'
)

# ------------------------------------------------------------------ #
print('\n[3] AND/OR 左折叠 build_rule_match')

# 首条 AND 被忽略，从第二条开始按连接符折叠 —— 这是 my_app 踩过的坑
conds = [
    {'or_and': 'AND', 'field': 'alarmCode', 'symbol': '=', 'values': ['99933']},
    {'or_and': 'OR', 'field': 'alarmCode', 'symbol': '=', 'values': ['9995']},
]
check(tt.build_rule_match(vf, conds), '首条 AND + 后续 OR：命中任一即真')

conds = [
    {'or_and': 'AND', 'field': 'alarmCode', 'symbol': '=', 'values': ['99933']},
    {'or_and': 'AND', 'field': 'netWorkType', 'symbol': '=', 'values': ['MW']},
]
check(not tt.build_rule_match(vf, conds), 'AND 链：一项不满足即假')

check(not tt.build_rule_match(vf, []), '空条件 → 不匹配')

# ------------------------------------------------------------------ #
print('\n[4] 字段归一化 build_value_frame')

# ⚠️ assetType 与 siteSubType 是**两个不同的字段**，来自两个不同的列：
#     site_type        → NORMAL / COOL   （assetType，见 eflow_data_mapper.py:304）
#     site_information → REGULAR / ERA   （siteSubType）
# 曾经两者都取 site_type（跟 my_app 一致），导致 `siteSubType='REGULAR'` 的规则
# 永远不可能命中。这几条断言就是钉住这个修正的。
v = tt.build_value_frame({
    'alarm_code': '9995.0', 'vip_site': 'Yes', 'site_type': 'REGULAR(NORMAL)',
    'domain': 'ran', 'down_site_count': 3, 'site_information': 'REGULAR',
})
check(v['alarmCode'] == '9995', f'告警码去掉末尾 .0（{v["alarmCode"]}）')
check(v['vipSite'] == '1', f'Yes → 1（{v["vipSite"]}）')
check(v['assetType'] == 'NORMAL', f'site_type 脏值归一到 assetType（{v["assetType"]}）')
check(v['siteSubType'] == 'REGULAR', f'site_information 归一为 siteSubType（{v["siteSubType"]}）')
check(v['netWorkType'] == 'RAN', f'域转大写（{v["netWorkType"]}）')

# 两列取值不同 —— 这正是修正前被抹掉的信息
v = tt.build_value_frame({
    'alarm_code': '9910', 'vip_site': 'No', 'site_type': 'COOL',
    'domain': 'RAN', 'down_site_count': 1, 'site_information': 'REGULAR',
})
check(v['assetType'] == 'COOL' and v['siteSubType'] == 'REGULAR',
      f'两列不同值不互相覆盖（asset={v["assetType"]}, sub={v["siteSubType"]}）')

# ERA 站点：site_type 为空、site_information 为 ERA（实测 6607 行是这种组合）
v = tt.build_value_frame({
    'alarm_code': '9995', 'vip_site': 'No', 'site_type': None,
    'domain': 'RAN', 'down_site_count': 1, 'site_information': 'ERA',
})
check(v['siteSubType'] == 'ERA', f'site_type 空、site_information=ERA（{v["siteSubType"]}）')
check(v['assetType'] == '', f'ERA 站点没有 assetType（{v["assetType"]!r}）')

v = tt.build_value_frame({'alarm_code': '1', 'vip_site': None, 'site_type': None,
                          'domain': None, 'down_site_count': None, 'site_information': None})
check(v['vipSite'] == '' and v['siteSubType'] == '' and v['assetType'] == '',
      'None 值不抛异常，归一为空串')

# ------------------------------------------------------------------ #
print('\n[5] 真实规则表加载')

if not os.path.isfile(tt.RULES_XLSX):
    # 规则表在 Y 盘（网络盘）。拿不到是环境问题，不是代码问题 —— 跳过而非判失败，
    # 否则离线 / 断网时 npm test 会整体变红，掩盖真正的前四段回归。
    print(f'  ⊘ SKIP：规则表不可达（{tt.RULES_XLSX}），跳过真实规则表校验')
else:
    try:
        rules = tt.load_rules()
        check(len(rules) > 0, f'加载到 {len(rules)} 条规则')
        check(all(r['conds'] for r in rules), '每条规则都解析出了条件')
        pr = [tt._num(r['priority']) for r in rules]
        check(pr == sorted(pr), '已按优先级升序排序')
        # 同优先级内条件数应降序（更具体的优先）
        ok = True
        for i in range(len(rules) - 1):
            if rules[i]['priority'] == rules[i + 1]['priority']:
                if rules[i]['cond_count'] < rules[i + 1]['cond_count']:
                    ok = False
                    break
        check(ok, '同优先级内按条件数降序（条件多的更具体，优先匹配）')
    except Exception as e:
        check(False, f'加载规则表失败：{e}')

# ------------------------------------------------------------------ #
print('\n[6] 派单规则反推（不依赖规则表，全部用构造规则 + 构造流水）')


def _mk_rule(rid, name, rtype, trigger, targets, conds=None, path='', op_res='',
             status='ACTIVE', priority=2):
    return {
        'id': rid, 'name': name, 'type': rtype, 'trigger': trigger,
        'priority': priority, 'status': status,
        'target_raw': '; '.join(targets), 'targets': [t.upper() for t in targets],
        'push_path': path, 'operation_result': op_res,
        'conds': conds or [], 'cond_count': len(conds or []),
    }


def _mk_row(steps, current_handler=''):
    """steps: [(列名, [步骤字典, ...]), ...] —— 拼成 fetch_tt 返回的那种行。"""
    row = {'current_handler': current_handler}
    for col, ds in steps:
        row[col] = '; '.join(
            ' '.join(f'{k}: {v}.' for k, v in d.items()) for d in ds
        )
    return row


_COND = [{'or_and': 'AND', 'field': 'alarmCode', 'symbol': 'in', 'values': ['9910']}]

# ── 辅助函数本身 ──
check(tt._norm_handler('G:ZTE_NOC_FO(ZTE_NOC_FO)') == 'ZTE_NOC_FO', '_norm_handler 去前缀与括号')
check(tt._norm_handler('P:FE Robot(fe_robot)') == 'FE ROBOT', '_norm_handler 转大写')
check(tt._parse_targets('ZTE_FE_FE(group); ZTE_NOC_FO(group)') == ['ZTE_FE_FE', 'ZTE_NOC_FO'],
      '_parse_targets 拆分多目标')
check(tt._push_path_results('FOAccept,2>FOProcess,8>FOProcess') == {'2', '8'},
      '_push_path_results 抽出各步结果')
check(tt._push_path_results('') == set(), '_push_path_results 空串 → 空集')
check(tt._rule_meta({'trigger': 'FOAccept', 'priority': 2}) == 'FOAccept·P2',
      '_rule_meta 优先级取整（不出现 P2.0）')
check(tt._rule_meta({'trigger': '', 'priority': None}) == '', '_rule_meta 无信息 → 空串')

# ── 触发步骤没走到过的规则不该被考虑（条件②）──
_fo_rule = _mk_rule(204, '小区故障派ZTE WO', 'ttPushOrderRule', 'FOAccept',
                    ['ZTE_NOC_FO'], _COND)
_bo_rule = _mk_rule(153, 'TT自动推单给BO-RAN组', 'ttPushOrderRule', 'BOAccept',
                    ['ZTE_BO_RAN'], _COND)
_disp = _mk_rule(164, 'TT单直接派FO accept', 'ttDispatchRule', 'autoDispatch',
                 [], [], op_res='1', priority=3)

# 只走 FO 的单：BOAccept 规则虽条件命中，但触发步骤没走到 → 不选它
_row_fo = _mk_row([
    ('create_detail', [{'Operation Step': 'Create', 'Operator': 'assign_rule(assign_rule)',
                        'Next Status': 'Waiting for FO Accept'}]),
    ('fo_accept_detail', [{'Operation Step': 'FO Accept', 'Operation Result': '2',
                           'Assign To': 'P:FE Robot(fe_robot)'}]),
    ('fo_process_detail', [{'Operation Step': 'FO Process', 'Operation Result': '8',
                            'Assign To': 'G:ZTE_NOC_FO(ZTE_NOC_FO)'}]),
], current_handler='G:ZTE_NOC_FO')
_res = tt.resolve_assign({'alarmCode': '9910'}, _row_fo, [_disp, _fo_rule, _bo_rule])
check((_res.get('push') or {}).get('rule', {}).get('id') == 204,
      '选中触发步骤真正走到过的那条（#204 而非 #153）',
      f'实际 {(_res.get("push") or {}).get("rule")}')
check((_res.get('push') or {}).get('ok') is True, '目标落在链路上 → ok=True')
check((_res.get('push') or {}).get('tier') == 'active', 'ACTIVE 规则 → tier=active')
check((_res.get('dispatch') or {}).get('rule', {}).get('id') == 164,
      '创建阶段选到兜底规则 #164')
check((_res.get('dispatch') or {}).get('ok') is True,
      '创建步骤 Next Status=Waiting for FO Accept → 与 #164 指向 FO 一致')

# ── 目标不在链路上 → ok=False，不能当事实说 ──
_row_other = _mk_row([
    ('create_detail', [{'Operation Step': 'Create', 'Next Status': 'Waiting for FO Accept'}]),
    ('fo_accept_detail', [{'Operation Step': 'FO Accept', 'Operation Result': '2',
                           'Assign To': 'P:FE Robot(fe_robot)'}]),
    ('fo_process_detail', [{'Operation Step': 'FO Process', 'Operation Result': '8',
                            'Assign To': 'G:SOME_OTHER_GROUP(SOME_OTHER_GROUP)'}]),
])
_res = tt.resolve_assign({'alarmCode': '9910'}, _row_other, [_disp, _fo_rule])
check((_res.get('push') or {}).get('ok') is False,
      '目标没出现在链路上 → ok=False（降级为「无法确认」）')
check((_res.get('push') or {}).get('reason_code') == 'r_target_absent',
      'reason_code 指向 target_absent')

# ── ACTIVE 说不通时，停用规则可以兜底，但要标出状态（tier=stopped）──
_stopped = _mk_rule(201, 'Regular断站故障手动到FO', 'ttPushOrderRule', 'FOAccept',
                    ['ZTE_FE_FE', 'ZTE_NOC_FO'], _COND, status='STOP')
_res = tt.resolve_assign({'alarmCode': '9910'}, _row_fo, [_disp, _stopped])
_p = _res.get('push') or {}
check(_p.get('rule', {}).get('id') == 201, '没有 ACTIVE 规则说得通 → 用停用规则兜底')
check(_p.get('ok') is True and _p.get('tier') == 'stopped',
      '停用规则命中 → ok=True 但 tier=stopped（渲染时标注状态）')

# ── ACTIVE 命中目标时，不该被停用规则抢走 ──
_res = tt.resolve_assign({'alarmCode': '9910'}, _row_fo, [_disp, _fo_rule, _stopped])
check((_res.get('push') or {}).get('rule', {}).get('id') == 204 and
      (_res.get('push') or {}).get('tier') == 'active',
      'ACTIVE 优先于停用（#204 胜过 #201）')

# ── 条件全不命中 → push=None，且不硬猜 ──
_res = tt.resolve_assign({'alarmCode': '999999'}, _row_fo, [_disp, _fo_rule, _stopped])
check(_res.get('push') is None, '条件都不命中 → push=None（渲染成「未匹配」）')
check(_res.get('push_candidates') == 0, 'push_candidates 计数为 0')

# ── 还没受理的单：不能因为「没有 fo_accept 流水」就说规则指向错了 ──
_row_wait = _mk_row([
    ('create_detail', [{'Operation Step': 'Create', 'Operator': 'admin(admin)',
                        'Next Status': 'Waiting for FO Accept'}]),
], current_handler='G:ZTE_NOC_FO')
_res = tt.resolve_assign({'alarmCode': '9910'}, _row_wait, [_disp, _fo_rule])
check((_res.get('dispatch') or {}).get('ok') is True,
      '未受理但 Next Status 指向 FO → 派单规则判定仍成立')
check(_res.get('accepted') is False, 'accepted=False（渲染时说「还没生效」而非「人工派单」）')
check(_res.get('push') is None, '未受理 → 没有派单规则可生效')

# ── 多目标规则：命中任一目标即可（如 #201 的 ZTE_FE_FE; ZTE_NOC_FO）──
check(tt._rule_hits_target(_stopped, {'targets': {'ZTE_NOC_FO'}}) is True,
      '多目标规则命中其中一个即可')
check(tt._rule_hits_target(_stopped, {'targets': {'ZTE_BO_PS'}}) is False,
      '目标都不在链路上 → False')
check(tt._rule_hits_target(_mk_rule(9, 'x', 't', 'FOAccept', []), {'targets': {'A'}}) is False,
      '规则没有目标处理人 → 不算命中（不靠空集自证）')

# ── 推送路径只能当加分项，不能当否决项（DB 存文字标签，规则存数字码）──
_weird = _mk_rule(200, 'Regular电源故障推送TT到IPT', 'ttPushOrderRule', 'FOAccept',
                  ['3rd_Power'], _COND, path='FOAccept,2>FOProcess,5>ThirdAccept')
_row_txt = _mk_row([
    ('create_detail', [{'Operation Step': 'Create', 'Next Status': 'Waiting for FO Accept'}]),
    ('fo_accept_detail', [{'Operation Step': 'FO Accept', 'Operation Result': '2',
                           'Assign To': 'P:FE Robot(fe_robot)'}]),
    # 结果存的是**文字标签**而非规则里的数字码 5 —— 不能因此判它不命中
    ('fo_process_detail', [{'Operation Step': 'FO Process',
                            'Operation Result': 'Reassign to Third Part',
                            'Assign To': 'G:3rd_Power(3rd_Power)'}]),
])
_res = tt.resolve_assign({'alarmCode': '9910'}, _row_txt, [_disp, _weird])
check((_res.get('push') or {}).get('ok') is True,
      '结果字段是文字标签时仍能确认命中（路径结果不参与否决）')

# ── 结果不能含 set（否则 --json 直接 TypeError）──
import json as _json

check(_json.dumps(_res, ensure_ascii=False) is not None,
      'resolve_assign 的返回值可 JSON 序列化（无 set）')

# ------------------------------------------------------------------ #
# B5：lookup_level —— 按「码 + 属性」直接判级别，复用同一套 matcher。
# 用合成规则表（不依赖 XLSX，离线可跑），验证：
#   ① 属性齐全时命中正确级别；② 缺字段 → incomplete（不是 unknown）；
#   ③ 都不匹配 → unknown；④ 与 match_rules 口径一致（同一代码路径）。
print('\n[9] B5 lookup_level（级别真匹配）')


def _c(field, sym, vals, orand='AND'):
    return {'field': field, 'symbol': sym, 'values': list(vals), 'or_and': orand}


def _rule(rid, name, prio, sev, conds):
    return {'id': rid, 'name': name, 'priority': prio, 'severity': sev,
            'status': 'ACTIVE', 'conds': conds, 'cond_count': len(conds)}


_MK = [
    _rule(227, '无线断站级别重定义-P2-new', 3, 'P2',
          [_c('assetType', '=', ['NORMAL']), _c('alarmCode', 'in', ['9970', '9990', '9920']),
           _c('vipSite', '=', ['0'])]),
    _rule(228, '无线断站级别重定义-P3-rule1', 3, 'P3',
          [_c('assetType', '=', ['COOL']), _c('alarmCode', 'in', ['9970', '9990', '9920']),
           _c('vipSite', '=', ['0'])]),
    _rule(226, '无线断站级别重定义-P1-rule2', 2, 'P1',
          [_c('vipSite', '=', ['1']), _c('alarmCode', 'in', ['9920'])]),
    _rule(230, 'TT-lowest severity', 4, 'P4', [_c('vipSite', 'in', ['0', '1'])]),
]

_r = tt.lookup_level('9990', asset='NORMAL', vip='0', rules=_MK)
check(_r['verdict'] == 'ok' and _r['suggested_severity'] == 'P2' and _r['matched_rule_id'] == 227,
      'NORMAL 非VIP 9990 → P2（#227）', str(_r))

_r = tt.lookup_level('9990', asset='COOL', vip='0', rules=_MK)
check(_r['verdict'] == 'ok' and _r['suggested_severity'] == 'P3' and _r['matched_rule_id'] == 228,
      'COOL 非VIP 9990 → P3（#228）', str(_r))

_r = tt.lookup_level('9920', vip='1', rules=_MK)
check(_r['verdict'] == 'ok' and _r['suggested_severity'] == 'P1' and _r['matched_rule_id'] == 226,
      'VIP=1 9920 → P1（#226）', str(_r))

# 缺字段（vipSite 未给）→ incomplete，不是 unknown
_r = tt.lookup_level('9990', asset='NORMAL', rules=_MK)
check(_r['verdict'] == 'incomplete' and 'vipSite' in _r['missing_rule_fields'],
      '缺 vipSite → incomplete（不是「未命中」）', str(_r))

# 兜底规则命中（P4）—— 与「连兜底都不中」区分
_r = tt.lookup_level('11111', vip='0', rules=_MK)
check(_r['verdict'] == 'ok' and _r['suggested_severity'] == 'P4',
      '未覆盖的码 + vipSite 有值 → 兜底 P4（#230）', str(_r))

# 与 match_rules 同口径：手工构造 vf 直接 match，结果应与 lookup_level 一致
_vf = tt.build_value_frame({'alarm_code': '9990', 'site_type': 'NORMAL', 'vip_site': '0',
                            'site_information': '', 'domain': '', 'down_site_count': ''})
_direct = tt.match_rules(_vf, _MK)
check(_direct is not None and _direct['id'] == 227, 'lookup_level 与 match_rules 口径一致', str(_direct))

# 渲染：命中时含级别与规则 ID；incomplete 时措辞点明「不是未命中」
_txt = tt.render_level_lookup(tt.lookup_level('9990', asset='NORMAL', vip='0', rules=_MK),
                              '9990', {'asset': 'NORMAL', 'vip': '0'}, 'zh')
check('P2' in _txt and '227' in _txt, '渲染含级别与规则 ID', _txt)
_txt2 = tt.render_level_lookup(tt.lookup_level('9990', asset='NORMAL', rules=_MK),
                               '9990', {'asset': 'NORMAL'}, 'zh')
check('无法判定' in _txt2 and '未被真正评估' in _txt2,
      'incomplete 渲染点明「规则未被真正评估」（≠未命中）', _txt2)

# ------------------------------------------------------------------ #
print('\n' + '=' * 50)
print(f'通过 {pass_n} 项，失败 {fail_n} 项')
sys.exit(1 if fail_n else 0)
