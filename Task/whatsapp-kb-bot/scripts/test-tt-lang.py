#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TT 单分析的多语言渲染单测。

    python scripts/test-tt-lang.py

覆盖「回复语言跟随提问语言」这条链路里**纯 Python 的那一半**（JS 那一半
—— detectLang / buildMessages —— 在 scripts/test-lang.mjs）。

为什么必须单测，不能靠肉眼看一遍输出：
    · 文案散在 4 张表里（_LABELS / _CHAIN_LABELS / _SLA_STATUS_LABEL /
      _DETAIL_COLS），**漏翻一条**在中文场景下完全看不出来，只有英文提问时
      才会冒出来一句中文（或直接 KeyError）；
    · 中英两条渲染路径是同一段代码，一旦哪个分支用了硬编码中文，
      只有逐字符扫一遍才能发现 —— 这就是本文件的核心断言。

不依赖工单库、不依赖规则表，可离线跑。
"""
from __future__ import annotations

import copy
import json
import os
import re
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
# 「中文残留」探测器
# ------------------------------------------------------------------ #
# 覆盖四类字符：
#   中日韩汉字（含扩展 A、兼容区）、CJK 标点（【】：、）、全角形式（｜（）＃）。
# 特意**不**包含 '·'(U+00B7) 与 '✓' —— 它们在中英两边共用，不算语言信号。
_CJK = re.compile(r'[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]')


def cjk_left(s: str) -> str:
    """返回字符串里残留的中文字符（去重后按出现顺序）。"""
    seen, out = set(), []
    for ch in s:
        if _CJK.match(ch) and ch not in seen:
            seen.add(ch)
            out.append(ch)
    return ''.join(out)


# ------------------------------------------------------------------ #
# 测试数据：以线上真实单 TT202609110023 为原型
# ------------------------------------------------------------------ #
TT_NO = 'TT202609110023'

RECORD = {
    'site_name': 'Dulay', 'site_id': '9187', 'ne_id': '',
    'region_level1': 'Nimba', 'site_class': 'P4',
    # 抬头展示的是这两列（归一化后）：site_type → 站点类型、site_information → 站点子类型。
    # `site_class` 仍在 record 里（JSON 调用方要用），但**不再进抬头**。
    'site_type': 'NORMAL', 'site_information': 'REGULAR',
    'title': '9187.[Dulay]2G SITE DOWN',
    'alarm_code': '9980', 'alarm_severity': 'Critical',
    'domain': 'RAN', 'alarm_type': 'Communication Alarm',
    'sub_alarm_name': 'Cell interruption alarm',
    # 真实值就是「分号 + 换行」分隔的多值 —— 不压平会把回复拆成好几行
    'sub_alarm_ne_name': 'BSC1(1);\nKileaken',
    'sub_alarm_ne_ip': '129.0.1.1',
    'whether_impacted_service': 'Yes', 'impacted_service': '2G',
    'site_outage': 'Yes', 'down_site_count': '1',
    'vip_site': 'No', 'hub_site': 'No',
    'operation_type': 'FOProcess(WO RCA to FO Confirm)',
    'current_handler': 'G:ZTE_NOC_FO',
    'last_processer': 'Emmanuel Egbe(FE_FE_118)',
    'last_process_time': '2026-09-12 21:14:42',
    'sla_status': 'Pass', 'sla_time': '0d16h0m',
    'sla_deadline': '2026-09-11 15:13:53', 'sla_remain_time': '0d6h48m',
    'fault_duration_time': '0d9h11m',
    'alarm_occur_time': '2026-09-10 23:13:53',
    'alarm_clear_time': '2026-09-11 08:25:14',
    'fault_resolved': 'Yes',
    '_sync_time': '2026-09-15T09:20:40.000Z',
    'create_detail': (
        'Operation Step:Create. Operation Result:FO Accept. '
        'Operation Time:2026-9-11 03:14:07. Operator:assign_rule(assign_rule). '
        'Operator Group:. Next Status:Waiting for FO Accept. '
        'Assign To:. Assignee Group:. Remark:'
    ),
    'fo_accept_detail': (
        'Operation Step:FO Accept. Operation Result:FO Process. '
        'Operation Time:2026-9-11 03:14:08. Operator:FE Robot(fe_robot). '
        'Operator Group:G:ZTE_FE_FE(ZTE_FE_FE). Next Status:Waiting for FO Process. '
        'Assign To:P:FE Robot(fe_robot). Assignee Group:. Remark:'
    ),
    'fo_process_detail': (
        'Operation Step:FO Process. Operation Result:8. '
        'Operation Time:2026-9-11 03:14:09. Operator:FE Robot(fe_robot). '
        'Operator Group:G:ZTE_FE_FE(ZTE_FE_FE). Next Status:Waiting for FO Process. '
        'Assign To:G:ZTE_NOC_FO(ZTE_NOC_FO). Assignee Group:. Remark:'
    ),
}

# 规则名 / 判定依据是**数据**（来自规则表），不是界面文案。
# 线上它们是中文（如「无线断站级别重定义-P3-rule2」），英文回复里出现中文
# 是正常的 —— 所以「英文输出零中文」这条断言必须用 ASCII 版数据来做，
# 否则测的是数据而不是文案。中文版数据另有一项专门的断言（见 [5]）。
RES = {
    'found': True, 'tt_no': TT_NO,
    'verdict': 'ok', 'current_severity': 'P3', 'suggested_severity': 'P3',
    'matched_rule_id': 229,
    'matched_rule_name': 'DownsiteSeverity-P3-rule2',
    'match_details': 'siteSubType=ERA = ERA ok; alarmCode=9980 in 9970,9980 ok',
    'record': RECORD,
}

# 真实线上形态：规则名是中文
RES_CN_RULE = copy.deepcopy(RES)
RES_CN_RULE['matched_rule_name'] = '无线断站级别重定义-P3-rule2'
RES_CN_RULE['match_details'] = 'siteSubType=ERA = ERA ✓; alarmCode=9980 in 9970,9980,... ✓'

RES_NOT_FOUND = {
    'found': False, 'tt_no': 'TT202609119999', 'latest_tt_no': 'TT202609150073',
}

# 超期单：两个信号同时指向超期（sla_status=Failed 且 remain 为负）
RES_OVERDUE = copy.deepcopy(RES)
RES_OVERDUE['record']['sla_status'] = 'Failed'
RES_OVERDUE['record']['sla_remain_time'] = '-0d1h19m'

# 临近超期：只靠 sla_status 的映射表，remain 仍是正的
RES_WARN = copy.deepcopy(RES)
RES_WARN['record']['sla_status'] = 'Warning'


# ------------------------------------------------------------------ #
print('\n[1] 文案表完整性（漏翻一条 = 英文提问时冒出中文，或直接 KeyError）')

for table_name in ('_LABELS', '_CHAIN_LABELS', '_SLA_STATUS_LABEL', '_MILESTONE_LABELS'):
    table = getattr(tt, table_name)
    check(set(table) >= {'zh', 'en'}, f'{table_name} 同时提供 zh / en')
    zh_keys, en_keys = set(table['zh']), set(table['en'])
    missing_en = sorted(zh_keys - en_keys)
    extra_en = sorted(en_keys - zh_keys)
    check(
        not missing_en and not extra_en,
        f'{table_name} 中英键集完全一致（各 {len(zh_keys)} 条）',
        f'英文缺：{missing_en}；英文多：{extra_en}',
    )

check(tt.SUPPORTED_LANGS == ('zh', 'en'), "SUPPORTED_LANGS == ('zh', 'en')")
check(tt.DEFAULT_LANG == 'zh', 'DEFAULT_LANG == zh（未知语言一律回退中文）')

# _LABELS 里每个值都得能 .format()，且不能把 {v} 之类的占位符漏掉
_placeholders = {
    'not_found': {'tt'}, 'not_found_hint': {'latest'},
    'need_openpyxl': {'path'}, 'db_missing': {'path'},
    'svc_down': {'svc'}, 'sites_down': {'n'}, 'more': {'n'},
    'level_adjust': {'sev'}, 'sla_raw': {'raw'},
    'sla_target': {'v'}, 'sla_due': {'v'}, 'sla_remain': {'v'}, 'sla_over': {'v'},
    'fault_duration': {'v'}, 'fault_occurred': {'v'}, 'fault_cleared': {'v'},
}
bad_fmt = []
for lang in ('zh', 'en'):
    for key, want in _placeholders.items():
        got = set(re.findall(r'\{(\w+)\}', tt._LABELS[lang][key]))
        if got != want:
            bad_fmt.append(f'{lang}.{key}: 期望 {want} 实得 {got}')
check(not bad_fmt, '带占位符的文案中英占位符一致', '；'.join(bad_fmt))


# ------------------------------------------------------------------ #
print('\n[2] 操作流水解析（_parse_detail 的键名切分）')

steps = tt._parse_detail(RECORD['fo_accept_detail'])
check(len(steps) == 1, f'单段流水解析出 1 步（实得 {len(steps)}）')
if steps:
    s = steps[0]
    check(s.get('Operation Step') == 'FO Accept',
          "Operation Step 取到 'FO Accept'", f"实得 {s.get('Operation Step')!r}")
    # ⚠️ 这是当初踩过的坑：正则里 `Operator Group:` 必须排在 `Operator:` 前面。
    # 顺序写反时 `Operator Group:G:ZTE_FE_FE(...)` 会被切成
    # Operator='' + Group 内容错位 —— 单看输出很难发现。
    check(s.get('Operator') == 'FE Robot(fe_robot)',
          "Operator 未被 'Operator Group:' 截断", f"实得 {s.get('Operator')!r}")
    check(s.get('Operator Group') == 'G:ZTE_FE_FE(ZTE_FE_FE)',
          "Operator Group 正确", f"实得 {s.get('Operator Group')!r}")
    check(s.get('Assign To') == 'P:FE Robot(fe_robot)',
          'Assign To（派给谁）正确', f"实得 {s.get('Assign To')!r}")

two = RECORD['fo_accept_detail'] + RECORD['fo_process_detail']
check(len(tt._parse_detail(two)) == 2, '一段里串了两条流水 → 解析出 2 步')
check(tt._parse_detail('') == [], '空串解析出 0 步（不抛异常）')


# ------------------------------------------------------------------ #
print('\n[3] 字段清洗（多值 / 换行）')

check(tt._one_line('a\nb  c') == 'a b c', '_one_line 把换行与连续空白压成单个空格')
check(tt._one_line(None) == '', '_one_line(None) 返回空串')
check(tt._one_line('abcdef', 3) == 'abc', '_one_line 按 limit 截断')
check(tt._multi('BSC1(1);\nKileaken') == 'BSC1(1)/Kileaken',
      '_multi 把「分号+换行」多值压成 A/B', f'实得 {tt._multi("BSC1(1);\nKileaken")!r}')
check(tt._multi('A;B;C;D') == 'A/B 等 4 个', '_multi 超过上限时省略并报总数')
check(tt._multi('') == '', '_multi(空) 返回空串')


# ------------------------------------------------------------------ #
print('\n[4] 英文输出：不允许残留任何中文（本文件的核心断言）')

zh_text = tt.render_text(RES, 'zh')
en_text = tt.render_text(RES, 'en')

zh_lines, en_lines = zh_text.split('\n'), en_text.split('\n')
check(len(zh_lines) == len(en_lines),
      f'中英行数一致（各 {len(zh_lines)} 行）—— 翻译不能丢内容',
      f'zh={len(zh_lines)} en={len(en_lines)}')

check(bool(cjk_left(zh_text)), '中文输出含中文（否则说明 lang 没生效）')
left = cjk_left(en_text)
check(not left, '英文输出零中文 / 零全角标点', f'残留：{left!r}')

step_re = re.compile(r'^\d+\. ')
zh_steps = [l for l in zh_lines if step_re.match(l)]
en_steps = [l for l in en_lines if step_re.match(l)]


# 状态标记符号表 —— 与 tt-analyze.py 的 st_done / st_fail / ... 一一对应。
# 显式列出而不是靠正则猜：符号里含变体选择符（⚠️ 是 U+26A0 U+FE0F），
# 用「非 ASCII 字符」这类笼统规则既容易多吞也容易漏吞。
_STATE_SYMS = ('✅', '❌', '⏳', '⚠️', 'ℹ️', '—', '·')


# 标记附注（`❌ 异常` 的「异常」部分）—— 中英两份都要在这里列出。
# 与 tt-analyze.py 的 st_note_* 一一对应；漏一条会让标签比对多吞/少吞文字。
_STATE_NOTES = {
    'zh': ('异常', '未完成', '未证实', '不适用', '决策型', '无数据'),
    'en': ('PROBLEM', 'not done yet', 'unproven', 'n/a', 'decision point', 'no data'),
}


def strip_mark(line: str, lang: str = 'zh') -> str:
    """去掉行首的 `N. ` 与状态标记，只留标签（供顺序断言比对）。

    2026-10-25 起里程碑每行多了状态标记（见 build_milestones 的 state）；
    断言**状态本身**的另有专门用例（见 [4b]）。
    """
    body = line.split('. ', 1)[1]
    for sym in _STATE_SYMS:
        if body.startswith(sym):
            body = body[len(sym):].lstrip()
            # 有的标记带附注（`❌ 异常`），一并剥掉 —— 按最长匹配，
            # 避免 'n/a' 之类的短串先命中导致残留
            for note in sorted(_STATE_NOTES[lang], key=len, reverse=True):
                if body.startswith(note):
                    body = body[len(note):].lstrip()
                    break
            break
    return body

check(len(zh_steps) == len(en_steps) == 9,
      f'里程碑跳数中英一致（各 {len(zh_steps)} 跳，契约固定 9 跳）')

for probe in ('Milestone timeline', 'Alarm occurred', 'TT created', 'Dispatch route',
              'FO Accept', 'WO dispatch', 'Onsite action', 'FO Process', 'Confirm',
              'Current stage', 'Timeliness', 'Severity', 'On time'):
    check(probe in en_text, f'英文输出含 "{probe}"')

# 创建步的 Operator 只会是 assign_rule(assign_rule) —— 无信息量的系统账号不上墙，
# 派单信息由「派单路由」跳承担（旧行为是「原始 Operator → 规则名」，已废弃）。
check('assign_rule' not in en_text,
      '创建跳不显示无信息量的 assign_rule 操作人')

# 未知语言必须回退中文，而不是抛异常或输出空
check(tt.render_text(RES, 'fr') == zh_text, '未知语言（fr）回退中文')
check(tt.render_text(RES) == zh_text, '不传 lang 时默认中文')
check(tt._L('fr') is tt._LABELS['zh'], '_L(未知语言) 返回中文表')
check(tt._L('en') is tt._LABELS['en'], '_L(en) 返回英文表')


# ------------------------------------------------------------------ #
print('\n[4a] 里程碑时间轴：9 跳契约、真实时间排序、间隔、未证实语义')

# 夹具 record 有时间的跳：告警发生(09-10 23:13) / 建单(03:14:07，create_detail 兜底)
# / FO接单(03:14:08) / FO填报(03:14:09) / 告警清除(09-11 08:25:14) → 5/9。
check('【里程碑时间轴】' in zh_text, 'zh 输出含「【里程碑时间轴】」标题')
check('（5/9 有确凿时间戳）' in zh_text, 'zh 标题带 5/9 时间戳计数', zh_text.split('\n')[7] if len(zh_lines) > 7 else '')
check('(5/9 with confirmed timestamps)' in en_text, 'en 标题带 5/9 时间戳计数')

# 排序契约：有确凿时间戳的按真实时间升序在前，无时间的按契约位置排在其后。
# 告警常在接单前就自愈 —— 按流水列固定顺序排会出现负间隔，这是换掉旧链路的原因。
en_labels = [strip_mark(l, 'en').split('  ')[0] for l in en_steps]
check(en_labels == ['Alarm occurred', 'TT created', 'FO Accept', 'FO Process',
                    'Alarm cleared', 'Dispatch route', 'WO dispatch', 'Onsite action',
                    'Confirm'],
      'en 9 跳顺序：时间跳按真实时间升序，无时间跳按契约位置排后',
      f'实得 {en_labels}')
zh_labels = [strip_mark(l).split('  ')[0] for l in zh_steps]
check(zh_labels == ['告警发生', 'TT建单', 'FO接单', 'FO填报', '告警清除',
                    '派单路由', 'WO派单', '现场处置', '关单确认'],
      'zh 9 跳顺序与 en 一一对应', f'实得 {zh_labels}')

# 间隔只出现在相邻时间跳之间，且形如 +40m / +3h48m。
# 第 1 跳没有「上一跳」，间隔为空是正确行为。
_gap_re = re.compile(r'（\+\d+[smhd]')
check(all(_gap_re.search(l) for l in zh_steps[1:5]),
      '第 2~5 跳（有时间）都带间隔标注', f'实得 {zh_steps[1:5]}')
check(not _gap_re.search(zh_steps[0]),
      '第 1 跳没有上一跳，不带间隔')
check(not any(_gap_re.search(l) for l in zh_steps[5:]),
      '无时间跳不出现间隔标注')

# WO 两跳：JSON 数组型明细（start_trip / arrive_site），epoch/字符串时间都要能解析
RES_WO = copy.deepcopy(RES)
RES_WO['wo'] = {
    'wo_no': 'WO202609110012', 'created_time': '2026-09-11 03:20:00',
    'creator': 'fe_robot', 'status': 'Closed',
    'start_trip_detail': '[{"opname":"Start Trip","operator":"FE_FE_118",'
                         '"opertime":"2026-09-11 08:30:00"}]',
    'arrive_site_detail': '[{"opname":"Arrive Site","operator":"FE_FE_118",'
                          '"opertime":"2026-09-11 08:35:00"}]',
    'leave_site_detail': '[]',
}
zh_w = tt.render_text(RES_WO, 'zh')
en_w = tt.render_text(RES_WO, 'en')
check('(7/9 with confirmed timestamps)' in en_w,
      '有 WO + 现场动作 → 时间戳计数 5→7', en_w.split('\n')[7])
check('WO202609110012' in en_w, 'WO 派单跳显示 WO 号')
check('FE_FE_118' in en_w, '现场处置跳显示 WO 明细里的操作人（JSON 解析）')
check('Start' in en_w and 'Arrive' in en_w, '现场处置跳显示出发/到场')
check('出发' in zh_w and '到场' in zh_w, 'zh 现场处置跳显示出发/到场')
check('auto-created by fe_robot' in en_w, 'WO 创建者是机器人账号时明确标注')
# 现场动作(08:30/08:35)晚于告警清除(08:25) → Onsite action 排在 Alarm cleared 之后
en_w_labels = [strip_mark(l, 'en').split('  ')[0]
               for l in en_w.split('\n') if step_re.match(l)]
check(en_w_labels.index('Onsite action') > en_w_labels.index('Alarm cleared'),
      '现场动作晚于告警清除时，排序如实反映（自愈后补现场动作）',
      f'实得 {en_w_labels}')
check(not cjk_left(en_w), '含 WO 两跳的英文输出无中文残留', f'残留：{cjk_left(en_w)!r}')



# ------------------------------------------------------------------ #
print('\n[4c] 里程碑状态标记：完成打勾 / 有问题打叉 / 未完成也给状态')

# 用户 2026-10-25 的要求：Milestone timeline 每一跳都要有状态，
# 已完成的 ✅、出了问题的 ❌、还没走到的 ⏳。核心断言是**三态可区分**，
# 而不是「每行都有符号」—— 全都一样就等于没有状态。

def _state_of(line: str) -> str:
    """从一行里取出状态符号（找不到返回 ''）。"""
    body = line.split('. ', 1)[1]
    for sym in _STATE_SYMS:
        if body.startswith(sym):
            return sym
    return ''


_base = tt.build_milestones(RES, 'zh')['nodes']
_by_key = {n['key']: n for n in _base}

# ① 有确凿时间戳的跳 = done
check(all(_by_key[k]['state'] == 'done'
          for k in ('alarm_occur', 'tt_create', 'fo_accept', 'fo_process', 'alarm_clear')),
      '有时间戳的 5 跳状态为 done',
      f"实得 {{k: _by_key[k]['state'] for k in ('alarm_occur', 'tt_create', 'fo_accept', 'fo_process', 'alarm_clear')}}")

# ② 全体都是已完成时，输出里压根不该出现红叉
check('❌' not in en_text, '数据正常的单不出现 ❌', en_text)

# ③ 派单路由是决策型 —— 没有时间但不是「未完成」，不能标成 ⏳
check(_by_key['dispatch_route']['state'] in ('decision', 'fail'),
      '派单路由是决策型节点（不误判为未完成）',
      f"实得 {_by_key['dispatch_route']['state']}")

# ④ 有 WO 但无现场明细 = 未证实，且必须区分于「未完成」
_wo_nosteps = copy.deepcopy(RES)
_wo_nosteps['wo'] = {'wo_no': 'WO202609110099', 'created_time': '2026-09-11 03:20:00',
                     'creator': 'fe_robot', 'status': 'Closed',
                     'start_trip_detail': '[]', 'arrive_site_detail': '[]',
                     'leave_site_detail': '[]'}
_wo_nodes = {n['key']: n for n in tt.build_milestones(_wo_nosteps, 'zh')['nodes']}
check(_wo_nodes['onsite_action']['state'] == 'unproven',
      '有 WO 无现场明细 → onsite_action 标为 unproven（不是 pending）',
      f"实得 {_wo_nodes['onsite_action']['state']}")

# ⑤ 无 WO → 两跳都应是「不适用」，不该报红
check(_by_key['wo_dispatch']['state'] == 'skipped', '无 WO → WO 派单标为 skipped')
check(_by_key['onsite_action']['state'] == 'skipped',
      '无 WO → 现场处置标为 skipped（不重复报警）',
      f"实得 {_by_key['onsite_action']['state']}")

# ⑥ 派单超时 → 红叉（与文本「超时限」同源）
_late = copy.deepcopy(RES)
_late['alarm_row'] = {'assign_delay': '15min',
                      'assigned_time': '1762816800000',   # 远早于建单
                      'alarmraisedtime': '1762776000000'}
_late_nodes = {n['key']: n for n in tt.build_milestones(_late, 'zh')['nodes']}
check(_late_nodes['alarm_occur']['state'] == 'fail',
      '派单超出 assign_delay 时限 → alarm_occur 标为 fail',
      f"实得 {_late_nodes['alarm_occur']['state']}")

# ⑦ 现场动作时间倒挂 → 红叉（离场早于到场）
_rev = copy.deepcopy(RES_WO)
_rev['wo'] = dict(RES_WO['wo'])
_rev['wo']['start_trip_detail'] = ('[{"opname":"Start Trip","operator":"FE_1",'
                                   '"opertime":"2026-09-11 08:30:00"}]')
_rev['wo']['arrive_site_detail'] = ('[{"opname":"Arrive Site","operator":"FE_1",'
                                    '"opertime":"2026-09-11 09:00:00"}]')
_rev['wo']['leave_site_detail'] = ('[{"opname":"Leave Site","operator":"FE_1",'
                                   '"opertime":"2026-09-11 08:45:00"}]')
_rev_nodes = {n['key']: n for n in tt.build_milestones(_rev, 'zh')['nodes']}
check(_rev_nodes['onsite_action']['state'] == 'fail',
      '离场早于到场 → onsite_action 标为 fail（时间倒挂）',
      f"实得 {_rev_nodes['onsite_action']['state']}")

# ⑧ 渲染层：红叉行必须真的写进输出
_rev_text = tt.render_text(_rev, 'zh')
check(any(l.startswith(tuple(f'{i}. ❌' for i in range(1, 10)))
          for l in _rev_text.split('\n')),
      'zh 输出里出现 ❌ 标记行', _rev_text)
check(cjk_left(tt.render_text(_rev, 'en')) == '',
      '带 ❌ 的英文输出仍无中文残留（附注是纯 ASCII）',
      f"残留：{cjk_left(tt.render_text(_rev, 'en'))!r}")

# ⑨ 中英标记符号必须完全一致（只有附注文字可以不同）
for _k in ('done', 'fail', 'pending', 'unproven', 'skipped', 'decision', 'empty'):
    check(tt._L('zh')[f'st_{_k}'] == tt._L('en')[f'st_{_k}'],
          f'st_{_k} 中英符号一致')


# ------------------------------------------------------------------ #
print('\n[4d] 第三方派单：WO 两跳标「不适用」并说明原因，不误报未证实')

# 用户 2026-10-25 反馈（TT202610250010，推单规则 200 → 3RD_POWER）：
# 第三方组不走 WO 流程，里程碑第 8/9 跳应显示「不适用 + 原因」，
# 而不是笼统的「未产生 WO」/「未证实」——后者会被误读成数据缺失或漏采。
_TP_PUSH = {'id': '200', 'name': 'RegularPowerToIPT', 'type': 'ttPushOrderRule',
            'trigger': 'FOAccept', 'priority': 2, 'status': 'ACTIVE',
            'target_raw': '3RD_POWER(group)', 'targets': ['3RD_POWER'],
            'push_path': '', 'operation_result': '', 'conds': [], 'cond_count': 0}

RES_TP = copy.deepcopy(RES)
RES_TP['assign'] = {'dispatch': {'rule': _TP_PUSH, 'ok': True, 'reason_code': '', 'tier': 'active'},
                    'push': {'rule': _TP_PUSH, 'ok': True, 'reason_code': '', 'tier': 'active'},
                    'accepted': True}

_tp_nodes = {n['key']: n for n in tt.build_milestones(RES_TP, 'zh')['nodes']}
check(_tp_nodes['wo_dispatch']['state'] == 'skipped', '第三方派单 → WO 派单标 skipped')
check(_tp_nodes['onsite_action']['state'] == 'skipped',
      '第三方派单 → 现场处置标 skipped（不是 unproven）',
      f"实得 {_tp_nodes['onsite_action']['state']}")
check('3RD_POWER' in _tp_nodes['wo_dispatch']['text'],
      'WO 跳写明派给了哪个第三方组', f"实得 {_tp_nodes['wo_dispatch']['text']!r}")

_tp_zh = tt.render_text(RES_TP, 'zh')
_tp_en = tt.render_text(RES_TP, 'en')
check('第三方 3RD_POWER' in _tp_zh, 'zh 输出点明第三方组名')
check('不走 WO 流程' in _tp_zh, 'zh 输出说明不走 WO 流程')
check('未证实' not in _tp_zh.split('[Assignment basis]')[0].split('【派单依据】')[0],
      'zh 第三方单不再出现「未证实」误报', _tp_zh)
check(cjk_left(_tp_en) == '', '第三方单的英文输出无中文残留',
      f"残留：{cjk_left(_tp_en)!r}")
check('3RD_POWER' in _tp_en and 'no WO flow' in _tp_en, 'en 输出点明第三方与不走 WO')

# 非第三方（ZTE_NOC_FO）不能命中这条分支 —— 否则 FO 单的「未产生 WO」会被改错
_fo_push = dict(_TP_PUSH, target_raw='ZTE_NOC_FO(group)', targets=['ZTE_NOC_FO'])
RES_FO = copy.deepcopy(RES)
RES_FO['assign'] = {'dispatch': {'rule': _fo_push, 'ok': True, 'reason_code': '', 'tier': 'active'},
                    'push': {'rule': _fo_push, 'ok': True, 'reason_code': '', 'tier': 'active'},
                    'accepted': True}
check(tt._third_party_target(RES_FO) == '', 'FO 派单不被误判为第三方')
check(tt._third_party_target({'assign': {}}) == '', '无派单数据时返回空串（不误判）')

# 三种第三方组名都要能认出来（知识库里 ThirdAccept 环节的默认组）
for _name in ('3rd_Power', '3rd_Fiber_HW', '3rd_Fiber_NANOTECH', 'Orange', 'ORANGE_NOC'):
    _r = {'assign': {'push': {'rule': dict(_TP_PUSH, target_raw=_name, targets=[_name])}}}
    check(tt._third_party_target(_r) != '', f'识别第三方组 {_name}')


# ------------------------------------------------------------------ #
print('\n[4b] 抬头：站点类型 / 站点子类型（不再显示「站点等级 P2」）')

# 需求：抬头去掉 `站点等级 P2`，改成 `站点类型` + `站点子类型`。
# 两列都过归一化（site_type → NORMAL/COOL、site_information → REGULAR/ERA），
# 免得把 DB 脏值（`REGULAR（Normal)`）原样端给用户。
_head_zh = zh_text.split('\n')[0]
_head_en = en_text.split('\n')[0]
check('站点类型 NORMAL' in _head_zh, 'zh 抬头含「站点类型 NORMAL」', _head_zh)
check('站点子类型 REGULAR' in _head_zh, 'zh 抬头含「站点子类型 REGULAR」', _head_zh)
check('Site type NORMAL' in _head_en, 'en 抬头含 "Site type NORMAL"', _head_en)
check('Site subtype REGULAR' in _head_en, 'en 抬头含 "Site subtype REGULAR"', _head_en)
check('站点等级' not in _head_zh and 'site class' not in _head_en,
      '抬头不再出现「站点等级 / site class」', f'{_head_zh} || {_head_en}')
# 抬头仍是一行，尾部顺序为 区域 → 站点类型 → 站点子类型
check(_head_zh.split('｜')[-3:] == ['Nimba', '站点类型 NORMAL', '站点子类型 REGULAR'],
      'zh 抬头尾部顺序：区域 → 站点类型 → 站点子类型', _head_zh)
check(_head_en.split(' | ')[-3:] == ['Nimba', 'Site type NORMAL', 'Site subtype REGULAR'],
      'en 抬头尾部顺序：region → site type → site subtype', _head_en)

# DB 脏值必须归一后再显示，不能原样外泄
_dirty = copy.deepcopy(RES)
_dirty['record']['site_type'] = 'REGULAR（Normal)'
_dirty['record']['site_information'] = 'REGULAR（COOL.I）'
_hd_dirty = tt.render_text(_dirty, 'zh').split('\n')[0]
check('站点类型 NORMAL' in _hd_dirty and '站点子类型 REGULAR' in _hd_dirty,
      '抬头显示归一化后的值', _hd_dirty)
check('REGULAR（Normal)' not in _hd_dirty, '脏值原文不出现在抬头', _hd_dirty)

# 字段缺失时该段整段不出现（不能留下「站点类型 」这种空标签）
_blank_site = copy.deepcopy(RES)
_blank_site['record']['site_type'] = ''
_blank_site['record']['site_information'] = None
_hd_blank = tt.render_text(_blank_site, 'zh').split('\n')[0]
check('站点类型' not in _hd_blank and '站点子类型' not in _hd_blank,
      '两列为空时不出空标签', _hd_blank)
check(_hd_blank.endswith('Nimba'), '仅剩区域时抬头仍以区域收尾', _hd_blank)
check(not cjk_left(tt.render_text(_blank_site, 'en').split('\n')[0]),
      '两列为空时英文抬头无中文残留')


# ------------------------------------------------------------------ #
print('\n[5] 数据里的中文不算「没翻译」—— 只允许出现在规则名/依据那两行')

en_cn = tt.render_text(RES_CN_RULE, 'en')
# 派单路由跳引用规则名（数据，不做翻译），与 Matched rule / Basis 同属数据行
data_lines = [l for l in en_cn.split('\n')
              if l.startswith('Matched rule: ') or l.startswith('Basis: ')
              or 'Dispatch route' in l]
check(len(data_lines) == 3,
      '定位到 3 行「数据行」（规则名 + 判定依据 + 派单路由跳）')
rest = '\n'.join(l for l in en_cn.split('\n') if l not in data_lines)
left = cjk_left(rest)
check(not left, '剔除数据行后，英文输出无中文残留', f'残留：{left!r}')
check(bool(cjk_left('\n'.join(data_lines))),
      '数据行确实保留了中文规则名（照实呈现，不做臆造翻译）')


# ------------------------------------------------------------------ #
print('\n[5b] 派单依据段：中英双语、链路首步展开、三种降级措辞')

# 规则名照旧用 ASCII 版，才能把「文案没翻」和「数据是中文」区分开
def _mk_push_rule(rid, name, rtype='ttPushOrderRule', trigger='FOAccept',
                  targets=('ZTE_NOC_FO',), conds=None, op_res='', status='ACTIVE'):
    conds = conds or []
    return {
        'id': rid, 'name': name, 'type': rtype, 'trigger': trigger,
        'priority': 2, 'status': status, 'target_raw': '; '.join(targets),
        'targets': [t.upper() for t in targets], 'push_path': '',
        'operation_result': op_res, 'conds': conds, 'cond_count': len(conds),
    }


_CONDS = [
    {'or_and': 'AND', 'field': 'alarmCode', 'symbol': 'in',
     'values': ['9971', '9981', '9991', '199087342']},
    {'or_and': 'AND', 'field': 'siteSubType', 'symbol': '=', 'values': ['REGULAR']},
]
_DISP_RULE = _mk_push_rule(164, 'TT-FO-accept-default', 'ttDispatchRule',
                           'autoDispatch', (), op_res='1')
_PUSH_RULE = _mk_push_rule(204, 'Cell-fault-to-ZTE-WO', conds=_CONDS)

_ASSIGN_OK = {
    'stage': 'FOAccept', 'accepted': True,
    'dispatch': {'rule': _DISP_RULE, 'ok': True, 'reason_code': '', 'tier': 'active'},
    'push': {'rule': _PUSH_RULE, 'ok': True, 'reason_code': '', 'peers': [], 'tier': 'active'},
}
RES_ASSIGN = copy.deepcopy(RES)
RES_ASSIGN['assign'] = _ASSIGN_OK
RES_ASSIGN['fields'] = {'alarmCode': '9991', 'siteSubType': 'REGULAR'}

zh_a = tt.render_text(RES_ASSIGN, 'zh')
en_a = tt.render_text(RES_ASSIGN, 'en')
check('【派单依据】' in zh_a, 'zh 输出含「【派单依据】」段')
check('[Assignment basis]' in en_a, 'en 输出含 "[Assignment basis]" 段')
check(len(zh_a.split('\n')) == len(en_a.split('\n')),
      f'派单依据段中英行数一致（各 {len(zh_a.split(chr(10)))} 行）')
check(not cjk_left(en_a), '含派单依据段的英文输出零中文', f'残留：{cjk_left(en_a)!r}')

# 链路第 1 步：`assign_rule(assign_rule)` 要展开成具体规则
check('#164 TT-FO-accept-default' in en_a,
      '派单路由跳显示具体规则（不再是光秃秃的 assign_rule）')
check('auto-dispatch (#164 TT-FO-accept-default)' in en_a,
      '派单路由跳带 auto-dispatch 说明与规则名')
check('#204 Cell-fault-to-ZTE-WO' in en_a, '派单行给出规则 ID 与名称')
check('ZTE_NOC_FO' in en_a, '派单行给出目标处理人')
check('Create:' in en_a and 'Dispatch:' in en_a, '中英两阶段行都有标签')
check('route to FO' in en_a, 'en 显示路由方向')
check('Matched:' in en_a, 'en 显示命中条件行')
check('(4 total)' in en_a, 'en 长值列表截断后缀正确')
check('(no conditions — catch-all default)' in en_a, 'en 标注无条件兜底规则')

# 停用档：要说清「规则表里状态是 STOP」，不能当成既成事实
_a_stop = copy.deepcopy(_ASSIGN_OK)
_a_stop['push'] = {'rule': _mk_push_rule(201, 'Regular-downsite-to-FO', status='STOP',
                                         targets=('ZTE_FE_FE', 'ZTE_NOC_FO')),
                   'ok': True, 'reason_code': '', 'peers': [], 'tier': 'stopped'}
RES_STOP = copy.deepcopy(RES_ASSIGN)
RES_STOP['assign'] = _a_stop
zh_s, en_s = tt.render_text(RES_STOP, 'zh'), tt.render_text(RES_STOP, 'en')
check('STOP' in zh_s and '快照' in zh_s, 'zh 停用档标注状态与快照滞后')
check('STOP' in en_s and 'snapshot' in en_s, 'en 停用档标注状态与快照滞后')
check(not cjk_left(en_s), 'en 停用档无中文残留', f'残留：{cjk_left(en_s)!r}')

# 反推不成立：必须明说「无法确认」，而不是把猜的规则当事实
_a_bad = copy.deepcopy(_ASSIGN_OK)
_a_bad['push'] = {'rule': _PUSH_RULE, 'ok': False, 'reason_code': 'r_target_absent',
                  'peers': [], 'tier': 'active'}
RES_BAD = copy.deepcopy(RES_ASSIGN)
RES_BAD['assign'] = _a_bad
zh_b, en_b = tt.render_text(RES_BAD, 'zh'), tt.render_text(RES_BAD, 'en')
check('未出现在本单派单链路上' in zh_b, 'zh 反推不成立 → 明说目标未出现')
check('never appears' in en_b, 'en 反推不成立 → 明说不确认')
check(not cjk_left(en_b), 'en 反推不成立时无中文残留', f'残留：{cjk_left(en_b)!r}')

# 条件都不命中
_a_none = {'stage': 'FOAccept', 'accepted': True,
           'dispatch': _ASSIGN_OK['dispatch'], 'push': None, 'push_candidates': 0}
RES_NONE = copy.deepcopy(RES_ASSIGN)
RES_NONE['assign'] = _a_none
zh_n, en_n = tt.render_text(RES_NONE, 'zh'), tt.render_text(RES_NONE, 'en')
check('未匹配到推单规则' in zh_n, 'zh 无匹配 → 「未匹配到推单规则」')
check('no push rule matched' in en_n, 'en 无匹配 → "no push rule matched"')
check(not cjk_left(en_n), 'en 无匹配时无中文残留', f'残留：{cjk_left(en_n)!r}')

# 还没受理：不能说成「人工派单」
_a_wait = {'stage': '', 'accepted': False,
           'dispatch': _ASSIGN_OK['dispatch'], 'push': None, 'push_candidates': 0}
RES_WAIT = copy.deepcopy(RES_ASSIGN)
RES_WAIT['assign'] = _a_wait
zh_w, en_w = tt.render_text(RES_WAIT, 'zh'), tt.render_text(RES_WAIT, 'en')
check('尚未受理' in zh_w, 'zh 未受理 → 「尚未受理，派单规则还没生效」')
check('not accepted yet' in en_w, 'en 未受理 → "not accepted yet"')
check(not cjk_left(en_w), 'en 未受理时无中文残留', f'残留：{cjk_left(en_w)!r}')

# 推单规则表读不到 → 整段不出现（可选增强，不能把回复弄坏）
check('【派单依据】' not in zh_text and '[Assignment basis]' not in en_text,
      '没有 assign 数据时整段不渲染（规则表读不到也能正常回复）')
check(tt._assign_lines({'found': True}, 'zh') == [], '_assign_lines 空输入返回空列表')

# 命中条件行的长度预算（条件多/值多时必须自己截，否则一行就 250+ 字符）
_many = [{'or_and': 'AND', 'field': 'alarmCode', 'symbol': '=', 'values': [str(i)]}
         for i in range(10)]
_brief = tt._cond_brief({'alarmCode': '1'}, _many, 'zh')
check(len(_brief) <= 130, f'条件多时 _cond_brief 自己截长（{len(_brief)} 字符）', _brief)
check('共 10 条' in _brief, '截断时说明总条数（读者知道这是摘要）')
_long_vals = [{'or_and': 'AND', 'field': 'alarmCode', 'symbol': 'in',
               'values': [str(1000000 + i) for i in range(9)]}]
_brief2 = tt._cond_brief({'alarmCode': '1'}, _long_vals, 'en')
check(len(_brief2) <= 130, f'值多时 _cond_brief 自己截长（{len(_brief2)} 字符）', _brief2)

# 回复长度护栏：`maxReplyChars` 是**从尾部**截断的（src/whatsapp.js 的 truncate），
# 超了会先把最后的「时效」段整段砍掉 —— 而那正是用户要看的信息。
# 这里用「最坏情况」的派单依据（10 条条件 + 停用档）压一遍，确保整条回复仍在上限内。
# 以后再加字段 / 改文案把回复撑长了，这条断言会先红。
_cfg_path = os.path.join(os.path.dirname(HERE), 'config.json')
_max_reply = 1500
if os.path.isfile(_cfg_path):
    with open(_cfg_path, encoding='utf-8') as fh:
        _max_reply = int(json.load(fh).get('maxReplyChars') or 1500)
_worst = copy.deepcopy(RES_ASSIGN)
_worst['assign'] = {
    'stage': 'BOAccept', 'accepted': True,
    'dispatch': {'rule': _DISP_RULE, 'ok': True, 'reason_code': '', 'tier': 'active'},
    'push': {'rule': _mk_push_rule(154, 'TT-auto-push-to-BO-MW', trigger='BOAccept',
                                   targets=('ZTE_BO_MW',), conds=_many, status='STOP'),
             'ok': True, 'reason_code': '', 'tier': 'stopped'},
}
for _lang in ('zh', 'en'):
    _t = tt.render_text(_worst, _lang)
    check(len(_t) <= _max_reply,
          f'{_lang} 最坏情况回复不超 maxReplyChars（{len(_t)} <= {_max_reply}）',
          f'超长会被从尾部截断，先丢「时效」段：{len(_t)} > {_max_reply}')


# ------------------------------------------------------------------ #
print('\n[6] 时效段：超期判定用库里的字段，不拿当前时间硬算')

# 未超期
check('未超期' in tt._sla_line(RECORD, 'zh'), 'zh 未超期 → 文案「未超期」')
check('On time' in tt._sla_line(RECORD, 'en'), 'en 未超期 → 文案 "On time"')

# 超期：sla_status=Failed + remain 为负，两个信号互证
zh_sla = tt._sla_line(RES_OVERDUE['record'], 'zh')
en_sla = tt._sla_line(RES_OVERDUE['record'], 'en')
check('已超期' in zh_sla, 'zh 超期 → 文案「已超期」', zh_sla)
check('OVERDUE' in en_sla, 'en 超期 → 文案 "OVERDUE"', en_sla)
check('1h19m' in zh_sla and '1h19m' in en_sla,
      '超时时长去掉负号后展示（0d1h19m 而非 -0d1h19m）', f'zh={zh_sla!r}')
check(not cjk_left(en_sla), 'en 超期行无中文残留', f'残留：{cjk_left(en_sla)!r}')

# 临近超期：只靠 sla_status 映射
check('临近超期' in tt._sla_line(RES_WARN['record'], 'zh'), 'zh Warning → 「临近超期」')
check('Near deadline' in tt._sla_line(RES_WARN['record'], 'en'), 'en Warning → "Near deadline"')

# 无数据
check('（无数据）' in tt._sla_line({}, 'zh'), 'zh 无 SLA 数据 → 文案「（无数据）」')
check('(no data)' in tt._sla_line({}, 'en'), 'en 无 SLA 数据 → 文案 "(no data)"')

# 故障段
zh_f = tt._fault_line(RECORD, 'zh')
en_f = tt._fault_line(RECORD, 'en')
check('已恢复' in zh_f and 'resolved' in en_f, '故障已恢复中英文案正确')
check(not cjk_left(en_f), 'en 故障行无中文残留', f'残留：{cjk_left(en_f)!r}')


# ------------------------------------------------------------------ #
print('\n[7] 查无此单：中英文案 + 提示带最新单号')

zh_nf = tt.render_text(RES_NOT_FOUND, 'zh')
en_nf = tt.render_text(RES_NOT_FOUND, 'en')
check('没有找到单号' in zh_nf, 'zh 查无此单文案正确')
check('not found' in en_nf, 'en 查无此单文案正确')
check(not cjk_left(en_nf), 'en 查无此单无中文残留', f'残留：{cjk_left(en_nf)!r}')
check('TT202609150073' in zh_nf and 'TT202609150073' in en_nf,
      '两种语言都带上库内最新单号（便于判断是同步延迟还是写错）')

# 没有 latest 时退化成短提示，不能留一个 {latest} 占位符
nf_no_latest = tt.render_text({'found': False, 'tt_no': 'TT1'}, 'en')
check('{latest}' not in nf_no_latest and '{tt}' not in nf_no_latest,
      '缺 latest 时不残留未替换的占位符', nf_no_latest)
check(not cjk_left(nf_no_latest), 'en 短提示无中文残留')


# ------------------------------------------------------------------ #
print('\n[8] 全字段覆盖：把 record 填满，两种语言都不能崩、不能留中文')

# 用 analyze() 实际会填进 record 的键全集，全部塞上真实形态的值。
# 目的是让 render_text 的每个分支都走到 —— 有分支只在特定字段非空时才渲染，
# 只测一张典型单子覆盖不到（例如 BO 处理 / 第三方 / 关单）。
FULL = copy.deepcopy(RECORD)
FULL.update({
    'bo_accept_detail': (
        'Operation Step:BO Accept. Operation Result:BO Process. '
        'Operation Time:2026-9-11 04:00:00. Operator:BO Robot(bo_robot). '
        'Operator Group:G:ZTE_BO(BO). Next Status:Waiting for BO Process. '
        'Assign To:G:ZTE_BO_NOC(BO_NOC). Assignee Group:. Remark:'
    ),
    'bo_process_detail': (
        'Operation Step:BO Process. Operation Result:Confirm. '
        'Operation Time:2026-9-11 05:00:00. Operator:BO Robot(bo_robot). '
        'Operator Group:G:ZTE_BO(BO). Next Status:Waiting for Confirm. '
        'Assign To:G:ZTE_BO_NOC(BO_NOC). Assignee Group:. Remark:'
    ),
    'third_accept_detail': (
        'Operation Step:Third Accept. Operation Time:2026-9-11 06:00:00. '
        'Operator:Third Party(tp). Assign To:P:Vendor(vendor). '
        'Operator Group:. Assignee Group:. Remark:'
    ),
    'third_process_detail': (
        'Operation Step:Third Process. Operation Time:2026-9-11 07:00:00. '
        'Operator:Third Party(tp). Assign To:G:ZTE_NOC_FO(ZTE_NOC_FO). '
        'Operator Group:. Assignee Group:. Remark:'
    ),
    'confirm_detail': (
        'Operation Step:Confirm. Operation Time:2026-9-11 08:00:00. '
        'Operator:FE Robot(fe_robot). Operator Group:G:ZTE_FE_FE(ZTE_FE_FE). '
        'Assign To:. Assignee Group:. Remark:'
    ),
    'closed_detail': (
        'Operation Step:Closed. Operation Time:2026-9-11 09:00:00. '
        'Operator:System(system). Operator Group:. Assign To:. Remark:'
    ),
    'suspend_detail': (
        'Operation Step:Suspend. Operation Time:2026-9-11 09:30:00. '
        'Operator:System(system). Operator Group:. Assign To:. Remark:'
    ),
    'sub_alarm_ne_name': 'BSC1(1);\nKileaken;\nKileaken-2',
    'hub_site': 'Yes', 'suspended': 'No', 'vendor': 'ZTE',
    'site_type': 'COOL', 'site_information': 'ERA',
    'vip_site': 'Yes', 'ne_id': '9187',
    'alarm_reason_type': 'Power', 'specific_problem': 'Site down',
    'down_site_list': 'Kileaken;\nDulay', 'impacted_service': '2G/3G',
    'fault_resolved': 'No', 'status': 'Processing',
})

RES_FULL = copy.deepcopy(RES)
RES_FULL['record'] = FULL
RES_FULL['verdict'] = 'adjust'
RES_FULL['current_severity'] = 'P4'
RES_FULL['suggested_severity'] = 'P3'

zh_full = tt.render_text(RES_FULL, 'zh')
en_full = tt.render_text(RES_FULL, 'en')
check(len(zh_full.split('\n')) == len(en_full.split('\n')),
      f'全字段单：中英行数一致（各 {len(zh_full.split(chr(10)))} 行）')
en_full_steps = [l for l in en_full.split('\n') if step_re.match(l)]
zh_full_steps = [l for l in zh_full.split('\n') if step_re.match(l)]
check(len(zh_full_steps) == len(en_full_steps) == 9,
      f'9 个环节全有流水 → 渲染出 9 步（实得 zh={len(zh_full_steps)} '
      f'en={len(en_full_steps)}）')
# 里程碑契约没有 BO/第三方独立跳（与 my_app 的 STAGE_CONTRACT 同口径），
# 但信息不丢：FO 侧流水缺失时回退 BO 流水取时间与操作人。
check('Third-party' not in en_full,
      '不再含第三方独立跳（契约 9 跳，与 my_app 复盘报告一致）')

# 有时间戳的跳必须按真实时间升序（告警先于接单自愈是常态，不能排出负间隔）
_full_ts = [re.search(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', l).group(0)
            for l in en_full_steps if re.search(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', l)]
check(len(_full_ts) >= 3 and _full_ts == sorted(_full_ts),
      '有时间跳按真实时间升序排列', f'实得 {_full_ts}')

# FO 流水缺失 → 回退 BO 流水
_no_fo = copy.deepcopy(RES)
_no_fo['record']['fo_accept_detail'] = ''
_no_fo['record']['bo_accept_detail'] = (
    'Operation Step:BO Accept. Operation Result:BO Process. '
    'Operation Time:2026-9-11 05:00:00. Operator:BO Robot(bo_robot). '
    'Operator Group:. Next Status:Waiting for BO Process. '
    'Assign To:. Assignee Group:. Remark:'
)
en_nf_fo = tt.render_text(_no_fo, 'en')
check('BO Robot(bo_robot)' in en_nf_fo,
      'FO 流水缺失时回退 BO 流水（操作人/时间不丢）')
left = cjk_left(en_full)
check(not left, '全字段单：英文输出无中文残留', f'残留：{left!r}')
check('[suggest' in en_full, '英文输出含「建议改级别」标记')
check('9187.[Dulay]2G SITE DOWN' in en_full,
      '英文输出原样保留 title（数据不做翻译）')
check('BSC1(1)/Kileaken' in en_full,
      '多值字段已压平成 A/B 形式（不把回复拆成多行）')

# 旧「链路顺序」断言已由 [4a] 的里程碑 9 跳顺序断言取代
#（契约顺序 + 真实时间排序都在那里覆盖）。

# 多值截断后缀也要按语言走（当初就是这条抓到 `_multi` 里硬编码的「等 N 个」）
check(tt._multi('A;B;C;D') == 'A/B 等 4 个', 'zh 多值截断 → 「等 4 个」（N 为总数）')
check(tt._multi('A;B;C;D', lang='en') == 'A/B (4 total)',
      'en 多值截断 → "(4 total)"', f'实得 {tt._multi("A;B;C;D", lang="en")!r}')
check('等' not in tt._multi('A;B;C;D', lang='en'),
      'en 多值截断不残留「等」字')

# 空流水 → 不能崩，9 跳照常全部列出（契约跳数固定），缺的只是时间戳
RES_NO_CHAIN = copy.deepcopy(RES)
RES_NO_CHAIN['record'] = {k: v for k, v in RECORD.items() if not k.endswith('_detail')}
zh_nc = tt.render_text(RES_NO_CHAIN, 'zh')
en_nc = tt.render_text(RES_NO_CHAIN, 'en')
check('（2/9 有确凿时间戳）' in zh_nc,
      '全部流水为空：只剩告警发生/清除两个字段时间（2/9）', zh_nc)
check('（未产生 WO）' in zh_nc, '无流水单：WO 跳明说未产生 WO')
check('（未证实' in zh_nc, '无流水单：现场处置跳报「未证实」而不是装作有数据')
check(not cjk_left(en_nc), '无流水单：英文输出无中文残留', f'残留：{cjk_left(en_nc)!r}')


# ------------------------------------------------------------------ #
print('\n[10] 逐字段置空扫描：任一份数据缺失时，英文输出都不得出现中文')

# 手搓样例永远会漏分支 —— 某个分支只在「这个字段恰好非空」时才渲染，
# 而它内部可能藏着硬编码中文。这里改用矩阵：把每个字段逐个置空，
# 再用每种语言渲染一遍。分支覆盖靠数据组合堆出来，不靠人想。
bad_cases: list[str] = []
cases = 0


def _probe(label, res_obj):
    global cases
    cases += 1
    try:
        out = tt.render_text(res_obj, 'en')
    except Exception as e:  # noqa: BLE001
        bad_cases.append(f'{label} 抛异常：{type(e).__name__}: {e}')
        return
    left = cjk_left(out)
    if left:
        bad_cases.append(f'{label} 残留 {left!r}')


for key in sorted(FULL):
    for empty in ('', None, '0'):
        probe = copy.deepcopy(RES_FULL)
        probe['record'][key] = empty
        _probe(f'record.{key}={empty!r}', probe)

for key, vals in (
    ('verdict', ('ok', 'adjust', 'unknown', '', None)),
    ('matched_rule_id', (None, 0, '', '')),
    ('matched_rule_name', ('',)),
    ('match_details', ('',)),
    ('current_severity', ('', None)),
    ('suggested_severity', ('', None)),
    ('record', ({},)),
):
    for v in vals:
        probe = copy.deepcopy(RES_FULL)
        probe[key] = v
        _probe(f'{key}={v!r}', probe)

# 空白整单：所有字段都空
blank = copy.deepcopy(RES_FULL)
blank['record'] = {k: '' for k in FULL}
_probe('record 全空', blank)

check(not bad_cases, f'{cases} 种「缺字段」组合下英文输出均无中文',
      '\n      '.join(bad_cases[:12]))

# 未知语言不能抛异常
lang_err = []
for bad_lang in ('fr', 'EN', 'zh-CN', '', None, 'en_US'):
    try:
        tt.render_text(RES_FULL, bad_lang)
    except Exception as e:  # noqa: BLE001
        lang_err.append(f'{bad_lang!r}: {type(e).__name__}')
check(not lang_err, '未知 / 非法语言标识不抛异常（回退中文）', '；'.join(lang_err))


# ------------------------------------------------------------------ #
print('\n[11] CLI 参数：--lang 只接受 zh / en')

src = open(os.path.join(HERE, 'tt-analyze.py'), encoding='utf-8').read()
check("add_argument('--lang'" in src, '脚本注册了 --lang 参数')
check("choices=list(SUPPORTED_LANGS)" in src, '--lang 限定取值（传错会让 argparse 直接退出）')
check('render_text(res, args.lang)' in src, 'main() 把 --lang 传给了 render_text')
check('--lang' in src and 'zh（默认）' in src, '--lang 帮助文案说明了默认值')

# 脚本级失败（退出码 2/3）走 stderr → 由 tt.js 按语言包一层「分析 X 时出错了：」。
# 脚本这边必须只输出**原因**，否则会出现「…时出错了：读取规则表失败：…」的套娃。
check('print(str(e), file=sys.stderr)' in src,
      'main() 只打印失败原因，不自带前缀（避免与 tt.js 双层套娃）')

# 前缀由 tt.js 补，脚本这边只给原因。
# 直接查文案值而不是匹配源码文本 —— 注释里也会出现同样的字面量，匹配源码会误判。
_prefix_re = re.compile(r'^(读取|查询|分析|Failed to read|Query failed|Failed to analyze)')
bad_prefix = [
    f'{lang}.{key}: {tt._LABELS[lang][key]!r}'
    for lang in ('zh', 'en')
    for key in ('need_openpyxl', 'db_missing')
    if _prefix_re.match(tt._LABELS[lang][key])
]
check(not bad_prefix, '脚本级失败文案不含「XX失败：」前缀（前缀由 tt.js 统一补）',
      '；'.join(bad_prefix))

# 失败原因本身也要按语言取：英文提问不能收到中文诊断
check('load_rules(lang=args.lang)' in src, 'main() 把语言传给 load_rules')
# 语言 / 推单规则 / 实时行 / 实时 WO 行都必须传进 analyze：
#   · 语言 → 失败诊断与渲染文案的语种；
#   · 推单规则 → 「派单依据」那一段；
#   · 实时行 → 本地库 miss 时改用它渲染（live_row= 是关键字传参，
#     所以要连关键字一起匹配，光匹配位置参数会漏掉它）；
#   · 实时 WO 行 → 单号分析走 HTTP 时，时间轴 WO 两跳也来自 PG 实时（wo_row=）。
# 调用跨行书写是允许的，关键参数名必须都在。
check('analyze(args.tt_no, rules, args.lang, push_rules,' in src
      and 'live_row=live_row' in src
      and 'wo_row=wo_row' in src,
      'main() 把语言、推单规则、实时行与实时 WO 行都传给 analyze')
check('load_push_rules(lang=args.lang)' in src, 'main() 把语言传给 load_push_rules')
check("_L(lang)['need_openpyxl']" in src, '缺 openpyxl 的诊断按语言取')
check("_L(lang)['db_missing']" in src, '缺工单库的诊断按语言取')

for probe in ('openpyxl', 'drive Y:'):
    check(probe in tt._LABELS['en']['need_openpyxl'],
          f"英文 need_openpyxl 含 '{probe}'")
check('Y 盘' in tt._LABELS['zh']['need_openpyxl'], '中文 need_openpyxl 提到 Y 盘')
check('drive Y:' in tt._LABELS['en']['db_missing'], '英文 db_missing 提到 drive Y:')


# ------------------------------------------------------------------ #
print('\n[12] 字段闭环：渲染读的 record 字段，必须真的被取出来放进 record')

# 这条是被真实数据抓出来的 bug：`site_information` 在 `_TT_COLUMNS`（取数）里，
# 却漏在 `record` 键清单里 —— `r.get()` 永远拿到 None，抬头静默少一段，
# 任何测试都不报错（测试夹具是手写的 record，绕过了取数环节）。
# 修法之外，这里把「取数 → record → 渲染」三段对一遍，堵住同类问题。
_src = open(os.path.join(HERE, 'tt-analyze.py'), encoding='utf-8').read()


def _fn_block(name):
    """截出某个顶层函数的源码块（到下一个顶层 def 为止）。"""
    m = re.search(rf'^def {name}\(', _src, re.M)
    if not m:
        return ''
    tail = _src[m.end():]
    nxt = re.search(r'^def ', tail, re.M)
    return _src[m.start():m.end() + (nxt.start() if nxt else len(tail))]


_cols_m = re.search(r'_TT_COLUMNS\s*=\s*\((.*?)\n\)', _src, re.S)
_fetched = set(re.findall(r"'([a-z_0-9]+)'", _cols_m.group(1))) if _cols_m else set()

_rec_m = re.search(r"'record':\s*\{\s*\n\s*k:.*?\n\s*for k in \((.*?)\n\s*\)",
                   _src, re.S)
_recorded = set(re.findall(r"'([a-z_0-9]+)'", _rec_m.group(1))) if _rec_m else set()

check(bool(_fetched) and bool(_recorded),
      f'解析出取数列（{len(_fetched)} 个）与 record 键（{len(_recorded)} 个）',
      f'_TT_COLUMNS={len(_fetched)} record={len(_recorded)}')
check(_recorded <= _fetched,
      'record 的每个键都在 _TT_COLUMNS 里（否则 SELECT 取不到、静默变空）',
      f'取不到：{sorted(_recorded - _fetched)}')

# 渲染侧：这些函数都拿 `r` 指代 record。把它们读过（`.get('x')` / `['x']`）的
# 字段全收集起来，跟 record 键清单对一遍 —— 少一个就是抬头/段落静默缺内容。
_RENDER_FNS = ('render_text', '_sla_line', '_fault_line', '_chain_steps',
               '_iter_detail_steps', '_assign_lines', 'build_milestones')
_used: set[str] = set()
for _fn in _RENDER_FNS:
    _body = _fn_block(_fn)
    _used |= set(re.findall(r"\br\.get\('([a-z_0-9]+)'\)", _body))
    _used |= set(re.findall(r"\br\['([a-z_0-9]+)'\]", _body))

check(len(_used) >= 10,
      f'从渲染函数里解析出 {len(_used)} 个 record 字段引用（正则没失配）',
      str(sorted(_used)))
check(_used <= _recorded,
      f'渲染读的 {len(_used)} 个 record 字段全在 record 键清单里',
      f'读不到（永远为空）：{sorted(_used - _recorded)}')
check('site_type' in _used and 'site_information' in _used,
      '抬头读的两个站点字段都被解析到（否则上面两条断言形同虚设）')


# ------------------------------------------------------------------ #
print('\n' + '=' * 50)
print(f'通过 {pass_n} 项，失败 {fail_n} 项')
sys.exit(1 if fail_n else 0)
