#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 my_app 的 TT 规则导出为知识库文档（供 RAG 检索）。

用法：
    python scripts/export-tt-knowledge.py

产出（写入 whatsapp-kb-bot/knowledge/）：
    TT单-告警压缩规则.md     由 eflow_alarm_rules.xlsx  导出
    TT单-级别判定规则.md     由 eflow_TT_rules.xlsx     导出
    TT单-告警码字典.md       由 eflow_tt_alarm_code_distinct.xlsx 导出

规则更新后重跑本脚本 + `npm run ingest` 即可。

设计取向：为**检索**服务，不为「读起来完整」服务。
每个告警码、每条规则都独立成段，避免被分块器切碎后语义残缺。
"""
from __future__ import annotations

import os
import sys

try:
    import openpyxl
except ImportError:  # pragma: no cover
    _FALLBACK = r'Y:/Task/my_app/Lib/site-packages'
    if os.path.isdir(_FALLBACK) and _FALLBACK not in sys.path:
        sys.path.append(_FALLBACK)
    import openpyxl

MY_APP_DIR = os.environ.get('MY_APP_DIR', r'Y:/Task/my_app')
RULES_DIR = os.path.join(MY_APP_DIR, 'backend', 'services', 'eflow_rules')
DATA_DIR = os.path.join(MY_APP_DIR, 'data')

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(os.path.dirname(HERE), 'knowledge')


def read_rows(path: str) -> tuple[list[str], list[tuple]]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return [], []
    header = [str(h or '').strip() for h in rows[0]]
    return header, rows[1:]


def cell(row: tuple, header: list[str], name: str, default=''):
    try:
        i = header.index(name)
    except ValueError:
        return default
    v = row[i] if i < len(row) else None
    return '' if v is None else str(v).strip()


def write_doc(filename: str, lines: list[str]) -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines).rstrip() + '\n')
    return path


# ------------------------------------------------------------------ #
# 1. 告警压缩规则
# ------------------------------------------------------------------ #

def export_alarm_rules() -> str:
    src = os.path.join(RULES_DIR, 'eflow_alarm_rules.xlsx')
    header, rows = read_rows(src)

    lines = [
        '# TT 单 - 告警压缩规则（告警相关性/父子衍生）',
        '',
        '本文件说明：多条原始告警在什么条件下会被**压缩**成一条新的衍生告警。',
        '压缩后，衍生出的告警作为**父告警**，参与压缩的基础告警作为**子告警**挂在下面。',
        '所有规则来自 eFlow 告警配置中心，规则包为 OUTAGE（退服类）。',
        '',
    ]

    # ---- 速览节 ----
    # 一条完整规则有 20+ 个参数，远超单个知识块容量，检索时必然被切散，
    # 导致「父告警码是什么」这类问题取不到。所以额外生成一份自包含摘要：
    # 每条规则压到 400 字符内，保证一个块就能装下全部关键信息。
    def brief(r, header) -> list[str]:
        name = cell(r, header, '规则名称')
        if not name or name.lower().startswith('init'):
            return []
        params = {}
        for kv in cell(r, header, '参数').split(';'):
            if '=' in kv:
                k, v = kv.split('=', 1)
                params[k.strip()] = v.strip()

        def pick(*keys):
            for k in keys:
                for pk, pv in params.items():
                    if k.lower() in pk.lower():
                        return pv
            return ''

        rat = pick('RAT(type)', 'type')
        sev = pick('specificProblem')
        root = pick('rootAlarmCode')
        site = pick('siteAlarmCode')
        # 注意：这里不能命名为 cell —— 会遮蔽全局的 cell() 取列函数，
        # 导致后面 cell(r, header, '状态') 报 UnboundLocalError。
        cell_code = pick('cellAlarmList')
        rel = pick('relationAlarmCode')

        out = [f'### 压缩规则速览：{name}', '']
        head = f'规则 {name}'
        if rat:
            head += f'（{rat}）'
        head += f'，状态 {cell(r, header, "状态") or "UNKNOWN"}。'
        out.append(head)
        if site:
            out.append(f'- 基础告警（子告警）站点断站码：{site}')
        if cell_code:
            out.append(f'- 基础告警（子告警）小区退服码：{cell_code}')
        if rel:
            out.append(f'- 关联告警码：{rel}')
        if root:
            out.append(f'- 衍生告警（父告警）根告警码：{root}')
        if sev:
            out.append(f'- 衍生告警名称：{sev}')
        out.append('')
        return out

    briefs: list[str] = []
    for r in rows:
        briefs += brief(r, header)
    if briefs:
        lines += ['## 规则速览（每条规则的关键码，查压缩结果先看这里）', ''] + briefs

    lines += ['## 规则详情（完整参数）', '']

    for r in rows:
        name = cell(r, header, '规则名称')
        if not name or name.lower().startswith('init'):
            continue  # 跳过资源初始化类规则，它们不产生告警压缩
        desc = cell(r, header, '描述')
        status = cell(r, header, '状态')
        params = cell(r, header, '参数')

        lines.append(f'## 压缩规则：{name}')
        lines.append('')
        if desc:
            lines.append(f'- 作用：{desc}')
        lines.append(f'- 状态：{status or "UNKNOWN"}')
        if params:
            lines.append('- 关键参数：')
            for kv in params.split(';'):
                kv = kv.strip()
                if not kv or '=' not in kv:
                    continue
                k, v = kv.split('=', 1)
                lines.append(f'  - {k.strip()} = {v.strip()}')
        lines.append('')

    def parse_params(r) -> dict:
        d = {}
        for kv in cell(r, header, '参数').split(';'):
            if '=' in kv:
                k, v = kv.split('=', 1)
                d[k.strip()] = v.strip()
        return d

    def find_param(params: dict, *keys) -> str:
        for k in keys:
            for pk, pv in params.items():
                if k.lower() in pk.lower().replace(' ', ''):
                    return pv
        return ''

    # 每个码都记下完整上下文（所属规则 + 该规则的父告警码）。
    # 这一点很关键：早先只记「参与哪些规则」，结果模型看到 198094422 的段落
    # 却答不出「压缩成什么」—— 因为答案在另一个块里，没被检索到。
    # 让每段自带完整答案，就不依赖跨块拼凑。
    codes: dict[str, list[dict]] = {}
    for r in rows:
        name = cell(r, header, '规则名称')
        if not name or name.lower().startswith('init'):
            continue
        params = parse_params(r)
        root = find_param(params, 'rootAlarmCode')
        derived = find_param(params, 'specificProblem')
        rat = find_param(params, 'RAT(type)', 'type')
        status = cell(r, header, '状态') or 'UNKNOWN'

        for pk, pv in params.items():
            if 'code' not in pk.lower() and 'alarm' not in pk.lower():
                continue
            for c in pv.replace('，', ',').split(','):
                c = c.strip()
                if c.isdigit():
                    codes.setdefault(c, []).append({
                        'rule': name, 'field': pk, 'root': root,
                        'derived': derived, 'rat': rat, 'status': status,
                    })

    if codes:
        lines += [
            '## 告警码 → 压缩归属速查',
            '',
            '本节按告警码逐个列出：它参与哪条压缩规则、扮演什么角色、压缩后的父告警码是什么。',
            '查「某个告警码会被压缩成什么」，看这里最直接。',
            '',
        ]
        for c in sorted(codes, key=lambda x: (len(x), x)):
            lines.append(f'### 告警码 {c}')
            lines.append('')
            for e in codes[c]:
                seg = f'- 规则 {e["rule"]}'
                if e['rat']:
                    seg += f'（{e["rat"]}）'
                seg += f'，字段「{e["field"]}」'
                if e['status'] != 'ENABLED':
                    seg += f'，状态 {e["status"]}（未启用）'
                lines.append(seg)
                if e['root']:
                    tail = f'  → 压缩后的父告警码是 {e["root"]}'
                    if e['derived']:
                        tail += f'（{e["derived"]}）'
                    lines.append(tail)
                else:
                    lines.append('  → 该规则未配置父告警码（rootAlarmCode）')
            lines.append('')

    return write_doc('TT单-告警压缩规则.md', lines)


# ------------------------------------------------------------------ #
# 2. TT 级别判定规则
# ------------------------------------------------------------------ #

def export_tt_rules() -> str:
    src = os.path.join(RULES_DIR, 'eflow_TT_rules.xlsx')
    header, rows = read_rows(src)

    lines = [
        '# TT 单 - 级别判定规则（TT Update Severity Rule）',
        '',
        '本文件说明：TT 单的严重级别（P1–P4）依据什么条件判定。',
        '规则按**优先级**从小到大依次匹配，命中即停止，后面的规则不再参与。',
        '同一优先级内，条件条数多的规则（更具体）优先。',
        '',
        '级别含义：P1 最严重，P4 最轻。',
        '',
    ]

    for r in rows:
        rid = cell(r, header, 'ID')
        if not rid:
            continue
        name = cell(r, header, '规则名称')
        sev = cell(r, header, '严重级别')
        pri = cell(r, header, '优先级')
        status = cell(r, header, '状态')
        cond = cell(r, header, '条件')

        lines.append(f'## 规则 {rid}：{name} → {sev}')
        lines.append('')
        lines.append(f'- 目标级别：{sev}（优先级 {pri}，状态 {status}）')
        if cond:
            lines.append('- 匹配条件：')
            for part in cond.split(';'):
                part = part.strip()
                if not part:
                    continue
                lines.append(f'  - {part}')
        lines.append('')

    lines += [
        '## 判定流程小结',
        '',
        '1. 取该 TT 单的字段值：告警码 alarmCode、是否 VIP 站点 vipSite、',
        '   站点子类型 siteSubType、网络类型 netWorkType、断站数 downSiteCount。',
        '2. 按优先级从小到大遍历规则，逐条判断条件是否全部满足。',
        '3. 第一条命中的规则给出建议级别；与当前级别不同则建议调整。',
        '4. 若所有规则都未命中，则无法判定，需人工确认。',
        '',
    ]
    return write_doc('TT单-级别判定规则.md', lines)


# ------------------------------------------------------------------ #
# 3. 告警码字典
# ------------------------------------------------------------------ #

def export_alarm_codes() -> str:
    src = os.path.join(DATA_DIR, 'eflow_tt_alarm_code_distinct.xlsx')
    if not os.path.isfile(src):
        return ''
    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    lines = [
        '# TT 单 - 告警码字典',
        '',
        '本文件列出实际产生过 TT 单的告警码及其含义，按出现次数从多到少排列。',
        '',
    ]

    for sn in wb.sheetnames:
        ws = wb[sn]
        rows = list(ws.iter_rows(values_only=True))
        if not rows or sn == 'alarm_code_raw':
            continue
        header = [str(h or '').strip() for h in rows[0]]
        lines.append(f'## {sn}')
        lines.append('')
        for r in rows[1:]:
            if not r or r[0] is None:
                continue
            code = cell(r, header, 'alarm_code')
            if not code:
                continue
            desc = cell(r, header, 'alarm_description')
            cnt = cell(r, header, 'tt_count')
            first = cell(r, header, 'first_seen')
            last = cell(r, header, 'last_seen')
            variants = cell(r, header, 'description_variants')
            lines.append(f'### 告警码 {code}')
            lines.append('')
            if desc:
                lines.append(f'- 含义：{desc}')
            if cnt:
                lines.append(f'- 累计 TT 单数：{cnt}')
            if variants and variants != '1':
                lines.append(f'- 描述变体数：{variants}')
            if first and last:
                lines.append(f'- 首次出现：{first}；最近出现：{last}')
            lines.append('')
    wb.close()
    return write_doc('TT单-告警码字典.md', lines)


def main() -> int:
    jobs = [
        ('告警压缩规则', export_alarm_rules),
        ('TT 级别判定规则', export_tt_rules),
        ('告警码字典', export_alarm_codes),
    ]
    for label, fn in jobs:
        try:
            p = fn()
            print(f'  ✓ {label}: {p}' if p else f'  - {label}: 源文件缺失，跳过')
        except Exception as e:
            print(f'  ✗ {label} 失败：{e}')
    print(f'\n输出目录：{OUT_DIR}')
    print('下一步：npm run ingest')
    return 0


if __name__ == '__main__':
    sys.exit(main())
