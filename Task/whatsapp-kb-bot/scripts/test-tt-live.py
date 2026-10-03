#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TT 实时兜底（--live-row）的行为测试。

覆盖三件在真实环境里很难复现、但一旦出错就是**静默错答**的事：

  ① 本地库没有、实时行有 → 必须出完整报告，且**标出来源是实时**；
     否则用户会以为这是本地快照，而两者可能不一致。
  ② 实时行缺字段（eFlow 的 live 字段远少于 eflow_tt 的列）→ 不能崩、
     英文输出不能残留中文。这是**最容易漏**的一条：本地行字段齐全，
     测试全绿，一上实时就 KeyError/空洞。
  ③ --live-row 传了非 JSON / 非对象 → 必须报错退出，**不能静默退回本地库**。
     否则用户发一个本地没有的新单，会收到「工单库里没有找到」，
     而事实是我们压根没去实时查 —— 用户会得出「实时也没有」的错误结论。

运行：
    python scripts/test-tt-live.py
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_SCRIPTS)
sys.path.insert(0, _SCRIPTS)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

spec = importlib.util.spec_from_file_location('tt', os.path.join(_SCRIPTS, 'tt-analyze.py'))
tt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tt)

_fails: list[str] = []
_passes = 0


def check(cond, label, detail=''):
    global _passes
    if cond:
        _passes += 1
        print(f'  ✓ {label}')
    else:
        _fails.append(label)
        print(f'  ✗ {label}' + (f'\n      {detail}' if detail else ''))


# 一份「实时行」：字段刻意**比本地行少很多**，模拟 eFlow live 的真实形态。
# 取值参考 my_app `_normalize_tt_live_row` 的输出（已是 eflow_tt 列名）。
LIVE_ROW = {
    'tt_no': 'TT202609290052',
    'wo_no': 'WO202609290061',
    'status': 'WaitFOProcess',
    'operation_type': 'FOProcess',
    'ticket_severity': 'P3',
    'alarm_code': 'ALM-1001',
    'alarm_severity': 'Major',
    'alarm_type': 'Power',
    'domain': 'RAN',
    'site_name': 'Bokessa',
    'site_id': '3283',
    'site_type': 'NORMAL',
    'site_information': 'REGULAR',
    'region_level1': 'Lofa',
    'vip_site': 'No',
    'hub_site': 'No',
    'down_site_count': '1',
    'site_outage': 'Yes',
    'whether_impacted_service': 'Yes',
    'impacted_service': '2G',
    'ticket_type': 'Fault',
    'created_time': '2026-09-29 08:00:00',
    'alarm_occur_time': '2026-09-29 07:55:00',
    'current_handler': 'FO Group A',
    'last_processer': 'john.doe',
    'last_process_time': '2026-09-29 09:10:00',
    'sub_alarm_name': 'Mains Fail',
    'sub_alarm_ne_name': 'BOKESSA_BTS1',
    'sub_alarm_ne_ip': '10.1.2.3',
    'title': 'Bokessa site down',
    # 刻意**不给** `_sync_time`：实时行没有「同步时间」这个概念
}

print('[1] 实时行能渲染出完整报告（本地库完全没参与）')
res = tt.analyze('TT202609290052', [], 'zh', [], live_row=LIVE_ROW)
check(res.get('found') is True, '实时行被判为 found')
check(res.get('live') is True, '结果带 live=True 标记（供上游区分来源）')
check(res['tt_no'] == 'TT202609290052', '单号回显正确')

zh = tt.render_text(res, 'zh')
check('⚡' in zh and 'eFlow' in zh, '中文报告标出「已实时查 eFlow」来源')
check('TT202609290052' in zh, '中文报告含单号')
check('Bokessa' in zh, '中文报告含站点名')
check('工单库里没有找到' not in zh, '实时命中时绝不出现「查无此单」文案')

en = tt.render_text(res, 'en')
check('live' in en.lower() and 'eFlow' in en, '英文报告标出来源')
check('not found' not in en.lower(), '英文实时命中时不出现 not found')
check(not any('\u4e00' <= c <= '\u9fff' for c in en), '英文输出无中文残留')

print('\n[2] 实时行字段缺失时不能崩、英文不能残留中文')
for missing in ('site_name', 'alarm_code', 'site_type', 'current_handler',
                'alarm_occur_time', '_sync_time', 'down_site_count'):
    partial = {k: v for k, v in LIVE_ROW.items() if k != missing}
    try:
        r2 = tt.analyze('TT202609290052', [], 'en', [], live_row=partial)
        t2 = tt.render_text(r2, 'en')
    except Exception as e:  # noqa: BLE001
        check(False, f'缺 {missing} 时仍能渲染', f'{type(e).__name__}: {e}')
        continue
    residue = [c for c in t2 if '\u4e00' <= c <= '\u9fff']
    check(not residue, f'缺 {missing} → 英文无中文残留', ''.join(residue))

print('\n[3] 实时行里 tt_no 缺失 → 用调用方传入的单号兜底')
no_no = {k: v for k, v in LIVE_ROW.items() if k != 'tt_no'}
r3 = tt.analyze('TT202609290052', [], 'zh', [], live_row=no_no)
check(r3.get('found') is True, 'tt_no 缺失仍判为 found')
check(r3['tt_no'] == 'TT202609290052', 'tt_no 用调用方传入的单号兜底')

print('\n[4] 本地行（live_row=None）行为不变：live 标记必须是 False')
local_like = tt.analyze('TT202609290052', [], 'zh', [], live_row=LIVE_ROW)
check(local_like.get('live') is True, '传 live_row → live=True')
# 用一份必然不存在的单号走本地路径，确认 live 标记默认不是 True
try:
    miss = tt.analyze('TT999999999999', [], 'zh', [], live_row=None)
    check(miss.get('live') is not True, '本地 miss 的结果不带 live=True')
    check(miss.get('found') is False, '本地 miss 时 found=False')
except FileNotFoundError:
    print('  (跳过：工单库不可达)')

print('\n[5] CLI：--live-row 解析失败必须报错，不能静默退回本地库')
PY = sys.executable
SCRIPT = os.path.join(_SCRIPTS, 'tt-analyze.py')


def run_cli(argv, stdin_text=None):
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    p = subprocess.run([PY, SCRIPT, *argv], capture_output=True, text=True,
                       timeout=180, encoding='utf-8', errors='replace',
                       input=stdin_text, env=env)
    return p


p = run_cli(['TT202609290052', '--live-row', '{not json'], '')
check(p.returncode == 2, '非法 JSON → 退出码 2', f'实得 {p.returncode}')
check('实时行解析失败' in (p.stderr or ''), '非法 JSON → stderr 说明原因')
check('工单库里没有找到' not in (p.stdout or ''),
      '非法 JSON → **绝不**输出「工单库里没有找到」（否则误导用户）')

p = run_cli(['TT202609290052', '--live-row', '[1,2,3]'], '')
check(p.returncode == 2, 'JSON 数组（非对象）→ 退出码 2', f'实得 {p.returncode}')

p = run_cli(['TT202609290052', '--live-row', '-'], json.dumps(LIVE_ROW))
check(p.returncode == 0, '经 stdin 传实时行 → 退出码 0', f'实得 {p.returncode}\n{p.stderr[:400]}')
check('⚡' in (p.stdout or ''), '经 stdin 传实时行的输出标出来源')
check('Bokessa' in (p.stdout or ''), '经 stdin 传实时行的输出含站点名')

p = run_cli(['TT202609290052', '--live-row', '-'], '')
check(p.returncode == 2, 'stdin 为空 → 退出码 2（不静默退回本地库）', f'实得 {p.returncode}')

print('\n[6] 实时行的 JSON 能以 --live-row 直接内联传（命令行形式）')
p = run_cli(['TT202609290052', '--live-row', json.dumps(LIVE_ROW, ensure_ascii=False), '--json'])
check(p.returncode == 0, '命令行内联 JSON → 退出码 0', f'实得 {p.returncode}\n{p.stderr[:400]}')
if p.returncode == 0:
    try:
        j = json.loads(p.stdout)
        check(j.get('live') is True, '--json 输出里 live=True')
        check(j.get('found') is True, '--json 输出里 found=True')
    except Exception as e:  # noqa: BLE001
        check(False, '--json 输出可解析', str(e))

# ------------------------------------------------------------------ #
# [7] 真实 eFlow 字段集 —— 上面 LIVE_ROW 是「理想字段」，掩盖了生产形态
# ------------------------------------------------------------------ #
# ⚠️ 为什么必须单列这一段：LIVE_ROW 里带了 `vip_site` / `down_site_count` /
# `domain` / `site_information` —— 但 eFlow 的 base/list **根本不返回这些**
#（只返回 24 个紧凑字段，见 my_app `_TT_LIVE_FIELD_KEYS`）。
# 于是上面所有用例全绿，生产上却出问题：级别规则要的字段全是空，
# 规则**静默失配**，报告显示「规则未命中，需人工确认」——
# 而同一单号本地库判的是「与规则一致，正常」。同一张单，两种口径。
# 这段用**真实**字段集复现那个场景，钉住修复后的措辞。
REAL_LIVE_ROW = {
    'tt_no': 'TT202609290052', 'status': 'WaitFOProcess', 'ticket_severity': 'P4',
    'alarm_severity': '1005001', 'alarm_type': 'Communication Alarm',
    'alarm_code': '9981', 'alarm_reason_type': 'OTHER',
    'site_outage': 'Yes', 'impacted_service': 'Yes', 'site_name': 'Baikedou',
    'site_id': '4103', 'site_type': 'NORMAL', 'region_level1': 'Lofa',
    'alarm_id': '1764214582064', 'vendor': 'ZTE', 'ne_name': 'Baikedou', 'ne_id': '4103',
    'created_time': '2026-09-29 14:23:03', 'last_modified_time': '2026-09-29 14:23:05',
    'alarm_occur_time': '179069086', 'fault_duration_time': '7611504',
    # 刻意**不含** vip_site / down_site_count / domain / site_information
}

print('\n[7] 真实 eFlow 字段集：级别判不了时必须说「没核对成」，不能说「未命中」')
r7 = tt.analyze('TT202609290052', tt.load_rules(lang='zh'), 'zh', [],
                live_row=REAL_LIVE_ROW)
check(r7.get('verdict') == 'incomplete',
      'verdict=incomplete（不是 unknown）', str(r7.get('verdict')))
check(bool(r7.get('missing_rule_fields')),
      '列出缺失字段', str(r7.get('missing_rule_fields')))

t7 = tt.render_text(r7, 'zh')
check('未能核对规则' in t7, '中文明确说「未能核对规则」', t7[:200])
check('规则未命中' not in t7,
      '**绝不**说「规则未命中」——那是把「数据不全」包装成「已核实不匹配」')
check('缺失字段' in t7, '中文列出缺哪些字段')

t7en = tt.render_text(r7, 'en')
check('not evaluated' in t7en, '英文说「rules not evaluated」', t7en[:200])
check('no rule matched' not in t7en, '英文不说 no rule matched')

# 字段齐全时，判定必须照旧——修复不能把正常路径也变成「判不了」
print('\n[8] 字段齐全 → 判定不受影响（防止修复矫枉过正）')
r8 = tt.analyze('TT202609290052', tt.load_rules(lang='zh'), 'zh', [],
                live_row=LIVE_ROW)
check(r8.get('verdict') != 'incomplete',
      '字段齐全时不判为 incomplete', str(r8.get('verdict')))
check(r8.get('missing_rule_fields') == [], '字段齐全时缺失列表为空',
      str(r8.get('missing_rule_fields')))

print('\n' + '=' * 50)
print(f'通过 {_passes} 项，失败 {len(_fails)} 项')
for f in _fails:
    print(f'  ✗ {f}')
sys.exit(1 if _fails else 0)
