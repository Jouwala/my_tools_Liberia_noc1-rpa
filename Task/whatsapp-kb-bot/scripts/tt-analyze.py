#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TT 单分析 —— 独立实现，只依赖 Python 标准库 + openpyxl。

用法：
    python tt-analyze.py TT202609150073
    python tt-analyze.py TT202609150073 --json

数据来源（my_app 根目录自动定位，可用环境变量 MY_APP_DIR 覆盖，
详见 scripts/my_app_paths.py）：
    工单库   <my_app>/db/app.db            （表 eflow_tt，只读打开）
    级别规则 <my_app>/backend/services/eflow_rules/eflow_TT_rules.xlsx

匹配口径**精确复刻** my_app 的
`backend/services/eflow_rules/eflow_rules_matcher.py`
（该模块依赖 pandas，本机 Python 环境未安装，故用纯 Python 重写，
算法逐步对应：parse_conditions / build_value_frame / _eval_one /
build_rule_mask / prepare_rules / match_all）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime

# ------------------------------------------------------------------ #
# 输出编码兜底
# ------------------------------------------------------------------ #
# 本脚本的输出含中文与全角符号（｜·：），而 Windows 上 Python 的 stdout
# 默认跟随系统代码页。机器人是通过 Node 子进程调用的，环境里**没有 LANG**，
# 于是编码退化成 cp1252 —— 一 print 中文就抛：
#     UnicodeEncodeError: 'charmap' codec can't encode characters ...
# 表现为群里收到「分析 XX 时出错了：UnicodeEncodeError: ...」。
#
# 处理分两种情况，因为两个使用场景要的东西不一样：
#   · 被管道接走（机器人在用）→ 下游按 UTF-8 解码，必须强制 UTF-8；
#   · 人在控制台看 → 强制 UTF-8 会在 cp936 控制台上变乱码，
#     所以保留原编码，只把装不下的字符替换掉，保证不崩。
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream.isatty():
            _stream.reconfigure(errors='replace')
        else:
            _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:  # 老解释器 / 已被重定向成奇怪对象
        pass

# ------------------------------------------------------------------ #
# 路径配置（可用环境变量覆盖）
# ------------------------------------------------------------------ #

# my_app 根目录的定位收在 scripts/my_app_paths.py 里 —— 不再写死 Y: 盘。
# 2026-10-03：写死 Y:/Task/my_app 导致换机后 TT 分析直接 Errno 2
#（Y: 在别的机器上指向的盘里根本没有 Task/my_app）。详见该模块的说明。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import my_app_paths  # noqa: E402

MY_APP_DIR = my_app_paths.find_my_app_dir()
DB_PATH = my_app_paths.resolve('MY_APP_DB', 'db', 'app.db')
RULES_XLSX = my_app_paths.resolve(
    'MY_APP_TT_RULES', 'backend', 'services', 'eflow_rules', 'eflow_TT_rules.xlsx'
)

# 推单/派单规则（配置中心全量规则）。用来回答「这单排给谁、依据哪条规则」。
# 由 my_app 的 eflow_Push_Rule_Collector.py 导出，与级别规则表同目录。
PUSH_RULES_XLSX = my_app_paths.resolve(
    'MY_APP_PUSH_RULES', 'backend', 'services', 'eflow_rules', 'eflow_push_rules.xlsx'
)


# 群里中英文混用（导入的 iMind 官方手册本身就是英文），所以输出语言要跟着
# **提问语言**走。语言由上游 `src/lang.js` 判定后用 `--lang` 传进来，默认中文。
#
# ⚠️ 这两个常量必须定义在**所有函数之前** —— 它们被用作形参默认值
#（如 `_multi(v, max_items=2, lang=DEFAULT_LANG)`），而默认值是在**函数定义时**
# 求值的，放到文件后面会直接 `NameError`。文案表本身在下面「多语言文案」一节。
SUPPORTED_LANGS = ('zh', 'en')
DEFAULT_LANG = 'zh'


def _import_openpyxl(lang: str = DEFAULT_LANG):
    """按需导入 openpyxl（只有读规则表才需要）。

    **为什么不在模块顶层导入** —— 曾经就是那样，踩过一次：
    openpyxl 只被 `load_rules()` 用到，但顶层导入会把它变成**整个模块**的前置
    依赖，后果有两个，都很难排查：

      · 纯渲染逻辑（`render_text` / 链路解析 / 字段清洗）根本不碰 Excel，
        却因为缺 openpyxl 连 `import` 都失败 —— 于是这些逻辑**没法离线单测**；
      · `scripts/test-tt-rules.py` 里那段「规则表不可达就 SKIP」的降级逻辑
        **永远走不到**：崩在 import 上，而它本意是优雅跳过。

    本机 openpyxl 并不在解释器的 site-packages 里（实测 Python312 / 3.14 都没有），
    而是躺在 my_app 的 `Lib/site-packages` 下（my_app 内嵌 venv 的 shim 已失效）
    —— 所以还要带上这个回退路径。路径由 my_app_paths 解析，**不再写死盘符**：
    早先写死 Y: 盘，换机后该目录不存在，回退静默失效，报错就变成了
    「缺 openpyxl」这种指向错误方向的结论。
    """
    try:
        import openpyxl  # noqa: PLC0415 —— 刻意延迟导入

        return openpyxl
    except ImportError:
        pass

    my_app_paths.apply_fallback_site_packages(MY_APP_DIR)
    try:
        import openpyxl  # noqa: PLC0415

        return openpyxl
    except ImportError as e:
        raise ImportError(
            _L(lang)['need_openpyxl'].format(path=fallback)
        ) from e

# ------------------------------------------------------------------ #
# 条件解析
# ------------------------------------------------------------------ #

# 与 my_app 的正则一致：注意 >= <= != <> 必须排在 = 之前，否则会被误吞
_OP_RE = re.compile(
    r"^\s*([\w.]+)\s*(>=|<=|!=|<>|\bin\b|\bnot\s+in\b|>|<|=)\s+'([^']*)'\s*$",
    re.IGNORECASE,
)

# 无条件分隔符 `|` 时的连接词（推单规则表的格式，见 parse_conditions 说明）
_LEAD_OP_RE = re.compile(r'^(AND|OR)\s+(.*)$', re.IGNORECASE)


def parse_conditions(cond_str) -> list[dict]:
    """把规则表 `条件` 列的字符串还原为结构化列表。

    单条形如：
        AND | eflow_ticket_ticket_wo.downSiteCount >= '5' ()
        OR  | eflow_ticket_ticket_wo.alarmCode in '9970, 9980' (string)
    """
    if not cond_str:
        return []
    out: list[dict] = []
    for raw in str(cond_str).split(';'):
        part = raw.strip()
        if not part:
            continue
        # ⚠️ 两张规则表的 `条件` 列**格式不一样**，两种都要认：
        #   eflow_TT_rules.xlsx   → `AND | field op 'v' (t)`   （收集脚本插了 `|`）
        #   eflow_push_rules.xlsx → `AND field op 'v' ()`      （配置中心原文，**没有 `|`**）
        # 早期只认前者，导致推单规则的条件一条都解析不出来。
        if '|' in part:
            or_and, rest = part.split('|', 1)
        else:
            m_lead = _LEAD_OP_RE.match(part)
            if not m_lead:
                continue
            or_and, rest = m_lead.group(1), m_lead.group(2)
        or_and = or_and.strip().upper()
        # 去掉末尾的 (type) 标记
        if rest.rfind('(') > rest.rfind("'"):
            rest = rest[: rest.rfind('(')]
        m = _OP_RE.match(rest.strip())
        if not m:
            continue
        field_path, symbol, value_str = m.group(1), m.group(2), m.group(3)
        field = field_path.split('.')[-1]
        symbol = symbol.lower().replace(' ', '')  # 'not in' → 'notin'
        if symbol in ('in', 'notin'):
            values = [v.strip() for v in value_str.split(',') if v.strip() != '']
        else:
            values = [value_str]
        out.append({'or_and': or_and, 'field': field, 'symbol': symbol, 'values': values})
    return out


# ------------------------------------------------------------------ #
# 字段归一化
# ------------------------------------------------------------------ #

# assetType 的归一化表（值域 NORMAL / COOL）。
# DB 的 `site_type` 列除了干净的 NORMAL/COOL，还混着 `REGULAR（Normal)`、
# `REGULAR(COOL.i）` 这类写法（各 63 / 13 行），归一化后都落回 NORMAL / COOL。
_SITE_TYPE_MAP = {
    'NORMAL': 'NORMAL',
    'REGULAR（NORMAL)': 'NORMAL',
    'REGULAR(NORMAL)': 'NORMAL',
    'COOL': 'COOL',
    'REGULAR(COOL.I）': 'COOL',
    'REGULAR（COOL.I）': 'COOL',
    'ERA': 'ERA',
    '': '',
}

# siteSubType 的归一化表（值域 REGULAR / ERA）。
# ⚠️ 这张表是**后加的** —— 见 build_value_frame 里那段说明：siteSubType 与 assetType
# 是两个不同的字段，各有各的值域。`REGULAR(...)` 那两种写法是 DB 里的脏值
#（在 site_information 列里也有 63 / 13 行），语义上属于 REGULAR。
_SITE_SUB_TYPE_MAP = {
    'REGULAR': 'REGULAR',
    'REGULAR（NORMAL)': 'REGULAR',
    'REGULAR(NORMAL)': 'REGULAR',
    'REGULAR(COOL.I）': 'REGULAR',
    'REGULAR（COOL.I）': 'REGULAR',
    'ERA': 'ERA',
    '': '',
}


def norm_vip(v) -> str:
    if v is None:
        return ''
    s = str(v).strip().lower()
    if s in ('yes', 'true', '1'):
        return '1'
    if s in ('no', 'false', '0'):
        return '0'
    return s


def norm_site_type(v) -> str:
    """assetType：`site_type` 列 → NORMAL / COOL。"""
    if v is None:
        return ''
    s = str(v).strip()
    key = s.upper().replace(' ', '')
    return _SITE_TYPE_MAP.get(key, s.upper())


def norm_site_sub_type(v) -> str:
    """siteSubType：`site_information` 列 → REGULAR / ERA。"""
    if v is None:
        return ''
    s = str(v).strip()
    key = s.upper().replace(' ', '')
    return _SITE_SUB_TYPE_MAP.get(key, s.upper())


def norm_alarm_code_text(v) -> str:
    """展示用：剥掉告警码的浮点文本尾巴（'9910.0' → '9910'）。

    ## 为什么展示侧要单独有一个归一化（2026-10-05 修复）

    `eflow_tt.alarm_code` 经同步链路后是**文本列**，`'99933'` 与 `'99933.0'`
    两种形态**并存**（my_app 侧 `tt_alarm_message.norm_alarm_code` 注释里有同一记载）。
    于是 `Alarm: 9910.0(Critical)` 这种带尾巴的告警码会直接发到值班群。

    这里与 `build_value_frame` 的 `alarmCode` 是**两条独立的路**，不是重复：
      * `build_value_frame` → `alarmCode`：供**规则匹配**判等用；
      * `render_text` → `record['alarm_code']`：供**人看**。

    两条路各错各的（本次就是：匹配侧正则写坏、展示侧压根没归一化），
    所以别把其中一个当成另一个的等价物 —— 改一处务必核对另一处。

    与 `Task/my_app/backend/services/tt_alarm_message.py:42` 的 `norm_alarm_code`
    语义对齐（那边只去一次 '.0'，此处去 '.000' 等多零形态）。
    """
    if v is None:
        return ''
    return re.sub(r'\.0+$', '', str(v).strip())


def build_value_frame(row: dict) -> dict:
    """把规则用到的字段归一化，键名对应规则里的 field。

    ⚠️ `siteSubType` 与 `assetType` 是**两个不同的字段**，各有各的 DB 列，别合并。

    早先这里跟 my_app 的 `eflow_rules_matcher.build_value_frame` 一样，把两者
    都写成 `site_type`（"目前 DB 只有 site_type 一列承载资产类型"）—— **那是错的**，
    实测三路取证：

      ① 规则表的值域完全不重叠：
         `assetType` 只用过 NORMAL / COOL；`siteSubType` 只用过 REGULAR / ERA。
      ② DB 交叉表显示这是两列：
         `NORMAL × REGULAR` 24664、`None × ERA` 6607、`COOL × REGULAR` 3003
         —— `site_type` 只装资产类型，`site_information` 只装子类型。
      ③ `eflow_data_mapper.py:304` 写着 `"assetType": "site_type"`，
         且 `TT_FIELDS` 里根本没有 siteSubType。

    后果（合并时的实测）：`siteSubType='REGULAR'` 的规则**永远不可能命中**
    —— REGULAR 站点的 `site_type` 是 NORMAL/COOL，取不到 'REGULAR'。
    典型受害规则是推单规则 #200「Regular电源故障推送TT到IPT」：本该命中却判不命中，
    于是大批单子报「无匹配规则」。ERA 站点则因为 `site_type` 为空、
    回退到 `site_information` 拿到 'ERA' 而**歪打正着**，所以这个 bug 一直没暴露。

    注意：修正后 `assetType` 对 NORMAL/COOL 站点取值不变（仍来自 `site_type`），
    所以已验收的级别规则 #227/#228 判定**不受影响**；ERA 站点的 assetType
    由 'ERA' 变成 ''，而没有任何规则用 `assetType='ERA'`，同样不影响。
    """
    def g(k):
        return row.get(k)

    alarm_code = str(g('alarm_code') or '').strip()
    # 剥掉浮点文本尾巴：'9910.0' → '9910'（供**规则匹配**用，见下方 alarmCode）。
    #
    # ⚠️ 2026-10-05 修复：这里原本写成 `re.sub(r'\.0+\$', ...)` —— `$` 被反斜杠
    # 转义成了**字面量 `$` 字符**，正则要求码尾真的有一个 '$' 才匹配，于是
    # **永远匹配不上**。
    #
    # 注意本行只影响 `alarmCode`（规则匹配字段）。**展示**用的告警码走
    # `res['record']['alarm_code']`（下方 :1254 的原始行），故渲染侧另有
    # `norm_alarm_code_text` 处理 —— 两处都要正确，否则会出现
    # 「规则判命中 9910、消息里却显示 9910.0」的错位。
    #
    # 语义与 `Task/my_app/backend/services/tt_alarm_message.py:42` 的
    # `norm_alarm_code` 一致（那边只去一次 '.0'，此处去 '.000' 等多零形态）。
    alarm_code = re.sub(r'\.0+$', '', alarm_code)

    return {
        'alarmCode': alarm_code,
        'vipSite': norm_vip(g('vip_site')),
        'siteSubType': norm_site_sub_type(g('site_information')),  # REGULAR / ERA
        'assetType': norm_site_type(g('site_type')),               # NORMAL / COOL
        'netWorkType': str(g('domain') or '').strip().upper(),
        'downSiteCount': str(g('down_site_count') or '').strip(),
    }


# ------------------------------------------------------------------ #
# 条件求值
# ------------------------------------------------------------------ #

def eval_one(vf: dict, cond: dict) -> bool:
    """单条件求值。字段缺失或数值无法转换 → False（与 my_app 一致）。"""
    field, symbol, values = cond['field'], cond['symbol'], cond['values']
    if field not in vf:
        return False
    col = str(vf[field])

    if symbol == '=':
        return col == str(values[0])
    if symbol in ('!=', '<>'):
        return col != str(values[0])
    if symbol == 'in':
        return col in [str(v) for v in values]
    if symbol == 'notin':
        return col not in [str(v) for v in values]
    if symbol in ('>', '<', '>=', '<='):
        try:
            bound = float(values[0])
            num = float(col)
        except (TypeError, ValueError):
            return False
        if symbol == '>':
            return num > bound
        if symbol == '<':
            return num < bound
        if symbol == '>=':
            return num >= bound
        return num <= bound
    return False


def build_rule_match(vf: dict, conds: list[dict]) -> bool:
    """左折叠 OR/AND。首行 orAnd 忽略。空条件列表 → 不匹配。

    必须左折叠而非先分组：my_app 实测过 Rule 206/207/208/209/234
    属于「首条 AND + 后续 OR」类型，先分组会漏配。
    """
    if not conds:
        return False
    mask = eval_one(vf, conds[0])
    for c in conds[1:]:
        m = eval_one(vf, c)
        if c['or_and'] == 'OR':
            mask = mask or m
        else:  # AND 及未知连接器都按 AND 兜底
            mask = mask and m
    return mask


def fmt_detail(vf: dict, conds: list[dict]) -> str:
    """生成 `field=value 符号 期望 ✓/✗` 的详情串，便于解释为什么命中。"""
    parts = []
    for c in conds:
        v = vf.get(c['field'], '(缺字段)')
        ok = eval_one(vf, c)
        exp = ','.join(c['values'])
        parts.append(f"{c['field']}={v} {c['symbol']} {exp} {'✓' if ok else '✗'}")
    return '; '.join(parts)


# ------------------------------------------------------------------ #
# 规则加载与匹配
# ------------------------------------------------------------------ #

def load_rules(path: str = RULES_XLSX, lang: str = DEFAULT_LANG) -> list[dict]:
    """读 eflow_TT_rules.xlsx，解析条件，按 my_app 的排序规则排好。"""
    openpyxl = _import_openpyxl(lang)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return []
    header = [str(h or '').strip() for h in rows[0]]
    idx = {h: i for i, h in enumerate(header)}

    rules: list[dict] = []
    for r in rows[1:]:
        if not r or r[idx.get('ID', 0)] is None:
            continue

        def cell(name):
            i = idx.get(name)
            return r[i] if i is not None and i < len(r) else None

        conds = parse_conditions(cell('条件'))
        rules.append({
            'id': cell('ID'),
            'name': cell('规则名称') or '',
            'priority': cell('优先级'),
            'severity': (str(cell('严重级别') or '')).strip().upper(),
            'status': (str(cell('状态') or '')).strip().upper(),
            'conds': conds,
            'cond_count': len(conds),
        })

    # 只保留启用中的规则；同优先级 → 条件数多者（更具体）优先 → 再按 ID 保证确定性
    rules = [x for x in rules if x['status'] in ('', 'ACTIVE')]
    rules.sort(key=lambda x: (_num(x['priority']), -x['cond_count'], _num(x['id'])))
    return rules


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float('inf')


def match_rules(vf: dict, rules: list[dict]) -> dict | None:
    """按排好序的规则依次尝试，第一条命中的即结果（与 my_app 的 pending 机制等价）。"""
    for rule in rules:
        if build_rule_match(vf, rule['conds']):
            return rule
    return None


def missing_rule_fields(vf: dict, rules: list[dict]) -> list[str]:
    """返回「取值缺失、导致规则无法判定」的字段名（去重保序）。

    为什么需要它：`build_value_frame` **总是**输出全部键，缺的字段变成空串；
    而 `eval_one` 对空串求值为 False —— 与「字段有值但不匹配」**完全无法区分**。
    于是实时行（eFlow 只回 24 个紧凑字段）下，11/15 条级别规则全部静默失配，
    报告一律显示「规则未命中，需人工确认」。

    这比「查不到」更糟：它是一句**看起来有依据、实际没查过**的结论。
    实测同一单号本地判 P4「与规则一致，正常」，实时判 P4「规则未命中」——
    同一张单，两种口径。

    判据：字段在 vf 里为空（'' 或 None），且**至少有一条规则**用到它。
    空值是「本行没这个数据」，「值不匹配」才是真的不匹配，必须分开。
    """
    used = {}
    for rule in rules:
        for c in rule['conds']:
            used.setdefault(c['field'], str(vf.get(c['field']) or '').strip())
    return [f for f, v in used.items() if not v]


def conds_all_evaluable(vf: dict, conds: list[dict]) -> bool:
    """这条规则的所有条件字段是否都有值可判。

    缺一个字段就可能让整条规则误判（尤其 AND 链），所以**宁可整条弃权**，
    也不给一个基于空值的「不匹配」结论。
    """
    return all(str(vf.get(c['field']) or '').strip() for c in conds)


# ------------------------------------------------------------------ #
# 派单 / 推单规则（回答「这单排给谁、依据哪条规则」）
# ------------------------------------------------------------------ #
# 背景：工单库里**没有**记录「命中了哪条派单规则」——
#   · `creator` 只写死 `assign_rule`；
#   · `create_detail` 的 Operator 也只有 `assign_rule(assign_rule)`；
#   · 没有任何 rule_id 列。
# 所以「具体哪个规则」只能**反推**：拿推单规则表逐条匹配本单字段。
#
# ⚠️ 反推必须交叉验证。否则会把「条件恰好也满足、但实际没走它」的规则
# 当成事实发到群里 —— 与 rowid 静默错位是同一类风险（错得毫无痕迹）。
# 见 `resolve_assign()`：条件命中只是**必要**条件，还要过两道自洽性检查。

# 两类规则管两件事，分两个阶段：
#   ttDispatchRule  （autoDispatch）        创建时决定走 FO 还是 BO
#   ttPushOrderRule （FOAccept/BOAccept/…） 决定派给哪个组
_PUSH_RULE_TYPES = ('ttDispatchRule', 'ttPushOrderRule')

# `动态项(JSON).operationResult` 的取值含义（从规则名反推，见 _dispatch_goes_fo）
_DISPATCH_FO = '1'
_DISPATCH_BO = '2'

# 规则里的 `触发步骤` → 工单库里的流水列（_DETAIL_COLS 的键）。
# 用来判断「这条规则有没有可能在本单上触发」：规则是在某一步被触发的，
# 那一步必须真的在本单流水里出现过。这样 FOAccept 的规则就不会套到只走 BO 的单上，
# Confirm / ThirdAccept 的规则也不会套到还没走到那一步的单上。
_TRIGGER_TO_STEP = {
    'autoDispatch': 'create',
    'FOAccept': 'fo_accept',
    'BOAccept': 'bo_accept',
    'FOProcess': 'fo_process',
    'BOProcess': 'bo_process',
    'ThirdAccept': 'third_accept',
    'ThirdProcess': 'third_process',
    'Confirm': 'confirm',
    'Closed': 'closed',
}


def _norm_handler(s) -> str:
    """把处理人写法归一，便于跨来源比对。

    `G:ZTE_NOC_FO(ZTE_NOC_FO)` / `P:FE Robot(fe_robot)` / `ZTE_NOC_FO(group)`
        → `ZTE_NOC_FO` / `FE ROBOT` / `ZTE_NOC_FO`
    """
    s = str(s or '').strip()
    s = re.sub(r'^[A-Za-z]:', '', s)   # 去 P: / G: 前缀
    s = s.split('(')[0].strip()        # 去 (ZTE_NOC_FO) / (group)
    return s.upper()


def _parse_targets(raw) -> list[str]:
    """`目标处理人` 形如 `ZTE_NOC_FO(group); ZTE_FE_FE(group)` → ['ZTE_NOC_FO', ...]"""
    if not raw:
        return []
    return [t for t in (_norm_handler(x) for x in str(raw).split(';')) if t]


def _push_path_results(path: str) -> set:
    """从 `推送路径` 里抽出各步的 Operation Result。

    `FOAccept,2>FOProcess,8>FOProcess` → {'2', '8'}

    ⚠️ 只能当**加分项**，不能当否决项 —— 两个原因（都实测踩过）：
      · 工单库里 `Operation Result` 存的是**文字标签**（如 `Reassign to Third Part`），
        而规则里写的是**数字码**（如 `5`），只有部分步骤能对上；
      · 推送路径包含**尚未走到**的后续步骤（单子还在 FOProcess 时，
        ThirdAccept 的结果自然还没产生）。
    拿它做子集校验会误杀正确的规则（实测 145/300 张单被误判）。
    """
    out: set = set()
    for seg in str(path or '').split('>'):
        seg = seg.strip()
        if ',' in seg:
            out.add(seg.split(',', 1)[1].strip())
    return out


def load_push_rules(path: str = PUSH_RULES_XLSX, lang: str = DEFAULT_LANG) -> list[dict]:
    """读 eflow_push_rules.xlsx，只留 TT 的派单/推单规则。

    ⚠️ **停用的规则也保留**（`status` 字段带着状态）。原因：规则表的 `状态`
    明显滞后于实际生效情况 —— 实测 300 张单里有 49 张（16%）只能靠
    `状态=STOP` 的规则解释（如 #201「Regular断站故障手动到FO」，其目标
    `ZTE_NOC_FO` 真的出现在这些单的派单链路上）。若直接丢弃，
    这批单会误报成「无匹配规则」。
    分档使用见 `resolve_assign()`：ACTIVE 优先，ACTIVE 里没人命中目标时才看停用的，
    并在输出里标注状态，不当成高置信结论。

    读不到（文件不存在 / 盘断了）返回空列表 —— 这是**可选增强**，
    不该让整个 TT 查询失败。
    """
    if not os.path.isfile(path):
        return []
    openpyxl = _import_openpyxl(lang)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return []
    header = [str(h or '').strip() for h in rows[0]]
    idx = {h: i for i, h in enumerate(header)}

    def cell(r, name):
        i = idx.get(name)
        return r[i] if i is not None and i < len(r) else None

    rules: list[dict] = []
    for r in rows[1:]:
        if not r or cell(r, 'ID') is None:
            continue
        rtype = str(cell(r, '规则类型') or '').strip()
        if rtype not in _PUSH_RULE_TYPES:
            continue
        try:
            dyn = json.loads(str(cell(r, '动态项(JSON)') or '{}'))
        except (json.JSONDecodeError, TypeError):
            dyn = {}
        if not isinstance(dyn, dict):
            dyn = {}
        rules.append({
            'id': cell(r, 'ID'),
            'name': str(cell(r, '规则名称') or '').strip(),
            'type': rtype,
            'trigger': str(cell(r, '触发步骤') or '').strip(),
            'priority': cell(r, '优先级'),
            'status': str(cell(r, '状态') or '').strip().upper(),
            'target_raw': str(cell(r, '目标处理人') or '').strip(),
            'targets': _parse_targets(cell(r, '目标处理人')),
            'push_path': str(cell(r, '推送路径') or '').strip(),
            'operation_result': str(dyn.get('operationResult') or '').strip(),
            'conds': parse_conditions(cell(r, '条件')),
            'cond_count': len(parse_conditions(cell(r, '条件'))),
        })

    # 同优先级 → 条件多者（更具体）优先 → 再按 ID 保证确定性
    rules.sort(key=lambda x: (_num(x['priority']), -x['cond_count'], _num(x['id'])))
    return rules


def is_active_rule(rule: dict) -> bool:
    """规则是否处于启用状态（状态列为空时按启用处理，与配置中心的缺省一致）。"""
    return str(rule.get('status') or '').strip().upper() in ('', 'ACTIVE')


def _iter_detail_steps(r: dict):
    """按链路顺序产出 (label_key, 解析后的步骤字典)。

    与 `_chain_steps` 同源，但保留 `Operation Result` 等原始键 ——
    推单规则的交叉验证要用。
    """
    for col, key in _DETAIL_COLS:
        raw = r.get(col)
        if not raw:
            continue
        for d in _parse_detail(str(raw)):
            yield key, d


def _assign_signals(r: dict) -> dict:
    """从本单流水里抽出用于**交叉验证**推单规则的信号。"""
    results: set = set()
    targets: set = set()
    steps: set = set()
    create_next = ''
    for key, d in _iter_detail_steps(r):
        steps.add(key)
        res = _one_line(d.get('Operation Result'))
        if res:
            results.add(res)
        for v in (d.get('Assign To'), d.get('Assignee Group')):
            n = _norm_handler(v)
            if n:
                targets.add(n)
        # 「创建」那一步的 Next Status 直接写明被路由到哪：
        #   `Waiting for FO Accept` / `Waiting for BO Accept`
        # 这比「有没有 fo_accept 流水」更早、更可靠 —— 单子还在等受理时
        # 受理流水自然还没产生，但路由**已经**发生了（autoDispatch 在创建时就决定了）。
        if key == 'create' and not create_next:
            create_next = _one_line(d.get('Next Status')).upper()
    n = _norm_handler(r.get('current_handler'))
    if n:
        targets.add(n)
    return {
        'results': results, 'targets': targets, 'steps': steps,
        'create_next': create_next,
        'routed_fo': 'FO ACCEPT' in create_next,
        'routed_bo': 'BO ACCEPT' in create_next,
        # 是否已经走过「受理」这一步（没走过 → 派单规则还没轮到生效）
        'accepted': bool(steps & {'fo_accept', 'bo_accept'}),
    }


def _rule_brief(rule: dict) -> str:
    """`#204 小区故障派ZTE WO`"""
    return f"#{rule['id']} {rule['name']}".strip()


def _rule_meta(rule: dict) -> str:
    """`FOAccept·P2` —— 触发步骤与优先级，让人一眼看出规则在哪一步、多优先。

    优先级在规则表里是浮点（`3.0`），显示要取整成 `P3`，否则会出现 `P3.0` 这种别扭写法。
    """
    bits = []
    if rule.get('trigger'):
        bits.append(str(rule['trigger']))
    n = _num(rule.get('priority'))
    if n != float('inf'):
        bits.append(f"P{int(n)}")
    return '·'.join(bits)


def _cond_brief(vf: dict, conds: list[dict], lang: str = DEFAULT_LANG,
                max_vals: int = 2, max_len: int = 110) -> str:
    """把命中条件压成**有长度预算**的一行。

    `alarmCode=9991 in 9971/9981 等 7 个；siteSubType=REGULAR = REGULAR`

    为什么不能直接复用 `fmt_detail`：它是给级别规则（条件少、值少）用的。
    推单规则里有两种「长条件」会撑爆回复 ——
      · `alarmCode in [7 个值]`（值多）；
      · 同一字段写成**多条** `=` 条件（实测 #154 有 10 条 `alarmCode = X`，
        逐条列出来光这一行就 250+ 字符）。
    而整条回复有 `maxReplyChars` 上限（见 config.json），超了**从尾部截断**，
    被砍掉的正好是最后一段「时效」—— 恰恰是用户要的信息。所以这里必须自己控长。

    做法：按顺序往预算里塞条件，塞不下就停，并补 `…（共 N 条）` 说明是**摘要**。
    """
    L = _L(lang)
    parts: list[str] = []
    budget = max_len
    for c in conds:
        vals = c['values']
        if len(vals) > max_vals:
            exp = '/'.join(vals[:max_vals]) + L['more'].format(n=len(vals))
        else:
            exp = '/'.join(vals)
        piece = f"{c['field']}={vf.get(c['field'], '-')} {c['symbol']} {exp}"
        if parts and len(piece) + len(L['cond_sep']) > budget:
            break
        parts.append(piece)
        budget -= len(piece) + len(L['cond_sep'])
    text = L['cond_sep'].join(parts)
    if len(parts) < len(conds):
        text += L['cond_more'].format(n=len(conds))
    return text


def _rule_hits_target(x: dict, sig: dict) -> bool:
    """规则的 `目标处理人` 是否真的出现在本单的派单链路上。

    这是反推里**最强的一条证据** —— 它来自工单现场（`Assign To` / `current_handler`），
    与规则表本身无关，所以不会「自证」。
    """
    return bool(x['targets']) and bool(set(x['targets']) & sig['targets'])


def _pick_stage_rule(cands: list[dict], sig: dict) -> tuple[dict | None, list[dict]]:
    """在「条件命中」的候选里挑出最可能是真凶的那条，并给出同等可信的备选。

    `cands` 已按 (优先级, 条件数降序, ID) 排好，即「更具体的优先」。
    再按两条证据重排（都是**独立于规则表**的现场事实）：

      ① 目标处理人真的出现在本单派单链路上  —— 决定性；
      ② 推送路径的操作结果与本单流水有交集  —— 弱加分（见 _push_path_results 的说明）。

    返回 (选中, 同样可信的备选)。备选非空意味着**无法唯一确定**是哪条规则，
    此时目标答案仍然正确，但规则 ID 要如实说明「可能是这几条」。
    """
    if not cands:
        return None, []

    def score(x: dict) -> tuple[int, int]:
        return (
            1 if _rule_hits_target(x, sig) else 0,
            len(_push_path_results(x['push_path']) & sig['results']),
        )

    # sorted 是稳定排序：同分时保留原来的 (优先级, 条件数, ID) 顺序 → 结果确定
    ranked = sorted(cands, key=score, reverse=True)
    top = ranked[0]
    top_score = score(top)
    peers = [x for x in ranked[1:] if score(x) == top_score]
    return top, peers


def resolve_assign(vf: dict, r: dict, push_rules: list[dict]) -> dict:
    """反推本单的派单依据，分两个阶段，各自带**可信度**。

    阶段一 autoDispatch：创建时决定走 FO 还是 BO   —— ttDispatchRule
    阶段二 FOAccept / BOAccept / …：决定派给哪个组 —— ttPushOrderRule

    每阶段的判定都过三道：
      ① 条件命中（`build_rule_match`）—— 必要条件，**不充分**
      ② 规则触发步骤真的在本单流水里出现过（`_TRIGGER_TO_STEP`）
      ③ 规则的 `目标处理人` 出现在本单的派单链路上（阶段一换成 operationResult
         指向的 FO/BO 与本单实际流程一致）

    阶段二分三档（`tier` 字段），因为规则表的 `状态` 有滞后：
      `active`  —— 启用规则命中且目标落在链路上 → 可以当事实说；
      `stopped` —— 没有启用的规则说得通，但**停用**的规则说得通（如 #201）；
                   输出时标注状态，措辞降级为「疑似/规则表快照显示已停用」；
      `none`    —— 都没有 → 说「未匹配到推单规则」，不硬猜。

    只有 ①②③ 全过才 `ok=True`。只过 ① 的会返回但 `ok=False`，
    渲染时标注「条件命中，但与本单流水不一致」—— 宁可说「不确定」，不可报错规则。
    """
    if not push_rules:
        return {}

    sig = _assign_signals(r)
    # 「走没走 FO/BO」优先看创建步骤的 Next Status（创建时就定了，最直接）；
    # 该字段为空时退回「有没有对应受理流水」。
    went_fo = sig['routed_fo'] or 'fo_accept' in sig['steps']
    went_bo = sig['routed_bo'] or 'bo_accept' in sig['steps']

    out: dict = {
        'stage': 'FOAccept' if 'fo_accept' in sig['steps'] else (
            'BOAccept' if 'bo_accept' in sig['steps'] else ''),
        # 是否已走到受理（没走到 → 派单规则还没轮到生效，措辞要区别对待）。
        # 只放这个 bool，不要把 `sig` 整个塞进来：里面的 results/targets/steps 是
        # **set**，`--json` 一序列化就 TypeError（实测踩过）。需要排查时直接调
        # `_assign_signals()`。
        'accepted': sig['accepted'],
    }

    active = [x for x in push_rules if is_active_rule(x)]
    stopped = [x for x in push_rules if not is_active_rule(x)]

    # ── 阶段一：autoDispatch（创建）──
    # 无条件规则是「兜底默认」（如 #164 直接派 FO），所以它天然命中；
    # 排序已保证优先级高的先试，取第一条命中的即可。
    chosen = None
    for x in (y for y in active if y['type'] == 'ttDispatchRule'):
        if not x['conds'] or build_rule_match(vf, x['conds']):
            chosen = x
            break
    if chosen:
        # 交叉验证：规则的 operationResult（1→FO / 2→BO）要与本单实际走的流程一致。
        # 这个映射是从规则名反推的，所以必须验 —— 映射若反了，这里会失败并降级成
        # 「未确认」，而不是把错的规则当事实发出去。
        want_fo = chosen['operation_result'] == _DISPATCH_FO
        want_bo = chosen['operation_result'] == _DISPATCH_BO
        if want_fo and not went_fo:
            ok, code = False, 'r_disp_fo'
        elif want_bo and not went_bo:
            ok, code = False, 'r_disp_bo'
        else:
            ok, code = True, ''
        out['dispatch'] = {'rule': chosen, 'ok': ok, 'reason_code': code, 'tier': 'active'}

    # ── 阶段二：派单 ──
    # 只考虑「触发步骤本单确实走到过」的规则（条件②），再取条件命中的（条件①）。
    def _cands(pool: list[dict]) -> list[dict]:
        return [
            x for x in pool
            if x['type'] == 'ttPushOrderRule'
            and _TRIGGER_TO_STEP.get(x['trigger'], '') in sig['steps']
            and build_rule_match(vf, x['conds'])
        ]

    # 诊断用：条件命中且触发步骤走到过的候选规则数（两档合计）
    out['push_candidates'] = len(_cands(active)) + len(_cands(stopped))

    push = None
    for pool, tier in ((active, 'active'), (stopped, 'stopped')):
        top, peers = _pick_stage_rule(_cands(pool), sig)
        if top is None:
            continue
        if _rule_hits_target(top, sig):
            # 目标真的落在本单链路上 → 这一档成立，不再往下找
            push = {'rule': top, 'ok': True, 'reason_code': '', 'peers': peers, 'tier': tier}
            break
        if push is None:
            # 条件命中但目标不在链路上：先记下作兜底，继续看下一档有没有更说得通的
            push = {
                'rule': top, 'ok': False, 'peers': peers, 'tier': tier,
                'reason_code': 'r_target_absent',
            }
    out['push'] = push
    return out


# ------------------------------------------------------------------ #
# 数据库读取
# ------------------------------------------------------------------ #

# 与 my_app 的 _TT_COLUMNS 对齐（匹配所需 + 展示所需）。
# ⚠️ tt_no / ticket_no / wo_no 三列是索引复核（_row_keys）依赖的，不能删。
_TT_COLUMNS = (
    'tt_no', 'ticket_no', 'wo_no', 'title',
    'alarm_code', 'alarm_severity', 'ticket_severity',
    'site_name', 'ne_name', 'domain', 'status', 'ticket_type', 'project_name',
    'vip_site', 'site_type', 'site_class', 'down_site_count', 'site_information',
    'root_cause', 'sub_root_cause', 'alarm_occur_time', 'created_time',
    'last_modified_time', 'region_level1', 'sub_alarm_name', 'description',
    # ↓ 链路 / 时效 / 影响面：群里回复要用（见 render_text）
    'current_handler', 'last_processer', 'last_process_time', 'operation_type',
    'sla_status', 'sla_time', 'sla_remain_time', 'sla_deadline',
    'fault_duration_time', 'alarm_clear_time', 'fault_resolved',
    'impacted_service', 'whether_impacted_service', 'site_outage',
    'ne_id', 'site_id', 'hub_site', 'vendor', 'suspended',
    'sub_alarm_ne_name', 'sub_alarm_ne_ip', 'alarm_type', 'alarm_reason_type',
    'specific_problem', 'down_site_list',
    'col_2g_down_site_count', 'col_3g_down_site_count',
    'col_4g_down_site_count', 'col_5g_down_site_count', 'vip_down_site_count',
    '_sync_time',
    # 操作流水原文（解析成链路，见 _chain_steps）
    'create_detail', 'fo_accept_detail', 'fo_process_detail',
    'bo_accept_detail', 'bo_process_detail',
    'third_accept_detail', 'third_process_detail',
    'confirm_detail', 'closed_detail', 'suspend_detail',
)

# 单号 → rowid 的本地索引缓存。
#
# 为什么需要：eflow_tt 表上**一个索引都没有**，任何单号查询都是全表扫描。
# 实测（1.58GB / 34676 行，库在 Y 盘网络盘上）：
#     全表扫描取一行    → 12 ~ 18 秒
#     按 rowid 取整行   → 0.003 秒        （差约 6000 倍）
# 所以把「单号 → rowid」导出一份到本地，查单号时先查本地映射再按 rowid 精确取行。
_INDEX_CACHE = os.environ.get(
    'TT_INDEX_CACHE',
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'tt-index.json'),
)
_INDEX_TTL = float(os.environ.get('TT_INDEX_TTL', 600))  # 秒；超过则重建

# 索引「被判定失效」的事件日志。
#
# 为什么需要：my_app 会整体重排 eflow_tt 的 rowid（实测某次同步后索引 100% 错位），
# 但**没有任何办法从代码侧知道它多久发生一次**。这个日志就是用来观察频率的：
#   · 几天才写一行 → 现在的方案没问题，每次代价只是一次重建（11~32 秒）；
#   · 每天都在写甚至每小时都在写 → 说明索引方案不适合这个库，
#     得改成「本地镜像业务列」的思路（不再依赖 rowid）。
_INVALIDATION_LOG = os.environ.get(
    'TT_INVALIDATION_LOG',
    os.path.join(os.path.dirname(_INDEX_CACHE), 'logs', 'tt-index-invalidations.log'),
)


def _log_invalidation(reason: str) -> None:
    """记一笔索引失效事件。写不进去也不影响主流程。"""
    try:
        os.makedirs(os.path.dirname(_INVALIDATION_LOG), exist_ok=True)
        with open(_INVALIDATION_LOG, 'a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")}\t{reason}\n')
    except Exception:
        pass


def _connect():
    """只读打开工单库。

    **必须用 immutable=1，不能用 mode=ro。** 工单库在 Y 盘（网络盘）上，
    而 SQLite 的 WAL 模式依赖共享内存（`-shm` 文件），在网络文件系统上不可靠。
    实测 `mode=ro` 会在扫描中途触发 Windows `page error`：
    **直接干掉整个 Python 进程，连 traceback 都留不下**
    —— 这就是群里那句「分析 XX 时出错了：Traceback (most recent call last):」的来源。

    `immutable=1` 告诉 SQLite「这个文件不会被修改」，跳过全部 WAL 与加锁处理，
    直接读主库文件。实测稳定（代价：若 my_app 正在写入，可能读到稍旧的快照，
    对本用途可接受）。
    """
    return sqlite3.connect(f'file:{DB_PATH}?immutable=1', uri=True)


def _load_index() -> tuple[dict, float, int, list]:
    """读本地单号索引，返回 (映射, 构建时间戳, 已覆盖的最大 rowid, 锚点)。

    缺失或损坏时返回 ({}, 0, 0, [])。
    """
    try:
        with open(_INDEX_CACHE, encoding='utf-8') as f:
            data = json.load(f)
        m = data.get('map')
        if isinstance(m, dict):
            a = data.get('anchors')
            return (
                m,
                float(data.get('builtAt', 0)),
                int(data.get('maxRowid', 0)),
                a if isinstance(a, list) else [],
            )
    except Exception:
        pass
    return {}, 0.0, 0, []


def _pick_anchors(mapping: dict, n: int = 3) -> list:
    """挑几个「rowid → 该行应含哪个单号」的锚点，用于日后校验索引是否还成立。

    **为什么非要有这个。** rowid 只在同一次写入布局下稳定。实测工单库会被
    整体重写（某次同步后 rowid 全部重新分配），这时：
      · `max(rowid)` 看起来仍在正常增长（34676 → 34702），
      · 增量同步只追加 `rowid > max` 的行，
    所以**增量机制完全察觉不到**，而索引已经 100% 错位 ——
    实测抽样 200 个单号，旧索引正确率 0.0%，且指向的行都存在，
    于是 `fetch_tt` 会**静默返回另一个工单**（实测 TT202609110023
    被解析成 TT202603120041），比「查不到」危险得多。

    锚点就是几个可随时抽查的对照样本：读索引时花约 3ms 核对一遍，
    对不上就认定索引作废、整表重建。
    """
    keys = sorted(mapping)
    if not keys:
        return []
    picks = [keys[0], keys[len(keys) // 2], keys[-1]]
    # 去重后保留顺序（键很少时首/中/尾可能重合）
    seen, out = set(), []
    for k in picks[:n]:
        if k not in seen:
            seen.add(k)
            out.append([mapping[k], k])
    return out


def _verify_anchors(cur, anchors: list) -> bool:
    """抽查锚点，判断索引是否仍与当前库布局对得上。

    每个锚点一次 rowid 查询（约 1ms），三个锚点约 3ms —— 相对于一次
    「全表扫描 12~18 秒」或「返回错误工单」，这点代价可以忽略。
    """
    if not anchors:
        return False
    for rid, key in anchors:
        row = cur.execute(
            'SELECT tt_no, ticket_no, wo_no FROM "eflow_tt" WHERE rowid = ?', (rid,)
        ).fetchone()
        if not row:
            return False
        if key not in {str(v).strip().upper() for v in row if v}:
            return False
    return True


def _row_keys(row) -> set:
    """从取回的整行里抽出「可用来认单号」的键集合。

    索引命中后**必须**用它复核一次：索引错位时按 rowid 取回的是另一个工单，
    而且是静默的（不报错、字段齐全）。宁可当没命中，也不能报错单。
    依赖 _TT_COLUMNS 里保留 tt_no / ticket_no / wo_no 三列。
    """
    d = dict(row)
    return {
        str(d[k]).strip().upper()
        for k in ('tt_no', 'ticket_no', 'wo_no')
        if d.get(k)
    }


def _save_index(mapping: dict, max_rid: int) -> None:
    """原子写入，避免读到半截文件。写不进去也不影响正确性，只是下次还得扫。"""
    try:
        os.makedirs(os.path.dirname(_INDEX_CACHE), exist_ok=True)
        tmp = _INDEX_CACHE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(
                {
                    'builtAt': time.time(),
                    'count': len(mapping),
                    'maxRowid': max_rid,
                    'anchors': _pick_anchors(mapping),
                    'map': mapping,
                },
                f, ensure_ascii=False,
            )
        os.replace(tmp, _INDEX_CACHE)
    except Exception:
        pass


def _build_index(cur, since: int = 0) -> dict:
    """导出单号 → rowid（tt_no / ticket_no / wo_no 三个都收）。

    `since > 0` 时只取 rowid 更大的行 —— 这是**增量**同步。
    之所以可行：rowid 是主键，`WHERE rowid > ?` 能走 B-tree 范围扫描，
    不必读全表。实测只取 676 行 2.9s，而全表 34676 行要 10.2s。
    """
    cur.execute(
        'SELECT rowid, tt_no, ticket_no, wo_no FROM "eflow_tt" WHERE rowid > ?', (since,)
    )
    mapping: dict[str, int] = {}
    for rid, *keys in cur:
        for k in keys:
            if k:
                s = str(k).strip().upper()
                if s:
                    mapping.setdefault(s, rid)
    return mapping


def fetch_tt(tt_no: str, lang: str = DEFAULT_LANG) -> dict | None:
    """按单号取一条 TT 记录。只读打开，绝不写库。"""
    if not os.path.isfile(DB_PATH):
        raise FileNotFoundError(_L(lang)['db_missing'].format(path=DB_PATH))

    target = tt_no.strip().upper()
    con = _connect()
    con.row_factory = sqlite3.Row
    try:
        cur = con.cursor()
        cur.execute('PRAGMA table_info("eflow_tt")')
        existing = {c[1] for c in cur.fetchall()}
        cols = [c for c in _TT_COLUMNS if c in existing]
        sel = ', '.join(f'"{c}"' for c in cols)

        # 「索引不可信」标记。用来区分两种「没命中」：
        #   · 索引可信 → 没命中就是真没有，可以直接回答「查无此单」；
        #   · 索引不可信 → 没命中什么都说明不了，必须退回全表直查。
        suspect = False

        # ① 读本地索引，并先抽查锚点。
        #    锚点对不上 = 库被整体重排过，索引 100% 失效，直接当没有索引。
        #    这一步必须做在「用索引回答」之前：索引失效时的错误答案有两种形态 ——
        #    取回别人的工单（静默错），或者目标单号的新 rowid 对不上旧值而误报「查无此单」。
        mapping, built_at, max_rid, anchors = _load_index()
        if mapping and not _verify_anchors(cur, anchors):
            _log_invalidation(f'锚点抽查不通过（{len(anchors)} 个锚点），索引作废')
            mapping = {}
            suspect = True

        # ② 索引可用且命中 → 按 rowid 精确取行（毫秒级）。
        #    即使索引已过期也先用：晚几分钟的数据，远好过让用户等一次全表扫描。
        if mapping:
            rid = mapping.get(target)
            if rid is not None:
                row = cur.execute(
                    f'SELECT {sel} FROM "eflow_tt" WHERE rowid = ?', (rid,)
                ).fetchone()
                if row and target in _row_keys(row):
                    return dict(row)
                # 行取回来了但不是这个单号 → 索引不可信，丢掉它走重建
                _log_invalidation(f'rowid 取回的行不含 {target}，索引错位')
                mapping = {}
                suspect = True

        # ③ 索引新鲜且可信但没命中 → 这个单号确实不在库里，不必再扫全表
        #    （扫一次要 10~100 秒，这一步省掉的是超时风险的大头）
        if mapping and (time.time() - built_at) < _INDEX_TTL:
            return None

        # ④ 需要重建，分两种：
        #    索引只是过期 → 增量同步（`rowid > 上次最大值`，只读新增行）；
        #    索引缺失或已判定失效 → 必须整表重建，因为 rowid 已经全部重排，
        #    增量取到的是「错位后的新增行」，对旧映射毫无修复作用。
        if mapping:
            fresh = _build_index(cur, since=max_rid)
            if fresh:
                mapping = {**mapping, **fresh}
                cur.execute('SELECT max(rowid) FROM "eflow_tt"')
                max_rid = cur.fetchone()[0] or max_rid
        else:
            mapping = _build_index(cur, since=0)
            cur.execute('SELECT max(rowid) FROM "eflow_tt"')
            max_rid = cur.fetchone()[0] or max_rid
            # 重建后自查一次。连刚建出来的索引都过不了锚点，说明库正在被改写
            # （扫到的是半途状态）—— 这时**绝不能**拿它回答。
            if mapping and not _verify_anchors(cur, _pick_anchors(mapping)):
                _log_invalidation('重建后锚点仍不通过，库可能正在被改写')
                mapping = {}
                suspect = True
        if mapping:
            _save_index(mapping, max_rid)

        if mapping:
            rid = mapping.get(target)
            if rid is not None:
                row = cur.execute(
                    f'SELECT {sel} FROM "eflow_tt" WHERE rowid = ?', (rid,)
                ).fetchone()
                if row and target in _row_keys(row):
                    return dict(row)

        # ⑤ 索引给不出可信答案时，退回全表直查。
        #    慢（12~18 秒），但这是唯一不依赖 rowid 的取数方式 ——
        #    只有它能在「库正在被改写」这种极端情况下保证结果正确。
        #    注意只在 suspect 时才走这里：索引可信的「没命中」在上面第 ③ 步
        #    就已经返回了，不必再浪费一次全表扫描。
        if suspect:
            _log_invalidation(f'改用全表直查 {target}')
            row = cur.execute(
                f'SELECT {sel} FROM "eflow_tt" WHERE UPPER("tt_no") = ?', (target,)
            ).fetchone()
            return dict(row) if row else None

        return None
    finally:
        con.close()


# ------------------------------------------------------------------ #
# 分析
# ------------------------------------------------------------------ #

def latest_tt_no() -> str:
    """库内最新的 TT 单号。

    用途：用户报的单号查不到时，十有八九是「数据还没同步过来」而不是「单号写错」。
    把库内最新单号一并告诉他，他自己就能判断是等一等还是核对单号。

    优先从本地索引取（单号形如 TT+12 位数字，定长，字典序即时间序），
    避免为了这一句提示再去扫一遍全表。

    注意：`builtAt` 会被增量同步刷新，所以「索引新鲜」**不等于**「索引正确」——
    库被整体重排后，索引会一直显得新鲜。这里同样要过一遍锚点，
    对不上就退回全表查询（慢但不会给出错误提示）。
    """
    mapping, built_at, _, anchors = _load_index()
    try:
        con = _connect()
        try:
            cur = con.cursor()
            if (
                mapping
                and (time.time() - built_at) < _INDEX_TTL
                and _verify_anchors(cur, anchors)
            ):
                cands = [k for k in mapping if k.startswith('TT')]
                if cands:
                    return max(cands)
            cur.execute(
                'SELECT tt_no FROM "eflow_tt" WHERE tt_no IS NOT NULL '
                'ORDER BY tt_no DESC LIMIT 1'
            )
            row = cur.fetchone()
            return str(row[0]) if row and row[0] else ''
        finally:
            con.close()
    except Exception:
        return ''


def analyze(tt_no: str, rules: list[dict], lang: str = DEFAULT_LANG,
            push_rules: list[dict] | None = None,
            live_row: dict | None = None) -> dict:
    """分析一个单。

    `live_row` 非空时**跳过本地库**，直接用这份「实时行」分析 —— 它是
    `eflow-live-tt.py` 从 eFlow API 实时拉回来的、已经映射成 eflow_tt 列名的
    dict（见 my_app 的 `_normalize_tt_live_row`）。

    走 live 时返回结构里会多两个键：
      · `live`   = True，供上游/测试区分「实时」与「本地快照」；
      · `_sync_time` 缺失是正常的（实时行没有「同步时间」这个概念），
        渲染层会自动省略那一行。

    渲染与规则匹配**完全复用同一套代码** —— 否则「本地查到的单」和
    「实时查到的单」会呈现两种格式，用户一眼就能看出差异，且要维护两份口径。
    """
    if live_row is not None:
        row = dict(live_row)
        # 单号以调用方传入的为准：实时行的 tt_no 可能为空（eFlow 有时只回 woNum）
        row.setdefault('tt_no', tt_no)
        if not row.get('tt_no'):
            row['tt_no'] = tt_no
    else:
        row = fetch_tt(tt_no, lang)

    if not row:
        return {'found': False, 'tt_no': tt_no, 'latest_tt_no': latest_tt_no()}

    # 里程碑时间轴要用的 WO 行（WO派单 / 现场处置 两跳，见 build_milestones）。
    # 刻意**不进 record**：测试 [12] 的字段闭环断言要求 record 键 ⊆ _TT_COLUMNS
    # （eflow_tt 的 SELECT 列），WO 字段来自另一张表，混进去会破坏那条防回归。
    wo = fetch_wo(row.get('wo_no'), lang)

    vf = build_value_frame(row)
    rule = match_rules(vf, rules)

    # 派单依据（「这单排给谁、依据哪条规则」）。推单规则表读不到时返回 {} —— 可选增强，
    # 缺了它照样出级别判定与处理链路，只是没有「派单依据」这一段。
    assign = resolve_assign(vf, row, push_rules or [])

    # 「没命中」分两种，必须区别对待（见 missing_rule_fields 的说明）：
    #   · 真没命中：字段都有值，规则就是不匹配 → 可信的「需人工确认」；
    #   · 判不了  ：有字段是空的（实时行只有 24 个紧凑字段）→ 规则**根本没被真正评估**，
    #               此时说「未命中」等于把「数据不全」包装成「已核实不匹配」。
    absent = missing_rule_fields(vf, rules) if not rule else []

    cur_sev = str(row.get('ticket_severity') or '').strip().upper()
    if rule:
        new_sev = rule['severity']
        changed = cur_sev != new_sev
        verdict = 'adjust' if changed else 'ok'
    else:
        new_sev = ''
        changed = False
        verdict = 'incomplete' if absent else 'unknown'

    return {
        'found': True,
        'live': live_row is not None,
        'tt_no': row.get('tt_no') or row.get('ticket_no') or tt_no,
        'verdict': verdict,
        'missing_rule_fields': absent,
        'current_severity': cur_sev,
        'suggested_severity': new_sev,
        'need_change': changed,
        'matched_rule_id': rule['id'] if rule else None,
        'matched_rule_name': rule['name'] if rule else '',
        'match_details': fmt_detail(vf, rule['conds']) if rule else '',
        'assign': assign,
        'wo': wo or {},
        'fields': vf,
        'record': {
            k: (str(row.get(k)) if row.get(k) is not None else '')
            for k in (
                # 基本信息 / 站点
                # ⚠️ `site_class`（站点等级）已按要求移出抬头，但**保留在 record 里**：
                # `--json` 调用方仍会读到它，删掉等于改对外字段。
                # ⚠️ 抬头要的 `site_type` / `site_information` 必须**同时**出现在
                # `_TT_COLUMNS`（取数）和这里（进 record）—— 只进前者的话
                # `r.get()` 永远拿到 None，抬头会静默少一段。测试 [12] 守这条。
                'title', 'site_name', 'site_id', 'ne_id', 'region_level1',
                'site_type', 'site_information', 'site_class',
                'vip_site', 'hub_site', 'vendor',
                # 告警
                'alarm_code', 'alarm_severity', 'domain', 'alarm_type',
                'sub_alarm_name', 'sub_alarm_ne_name', 'sub_alarm_ne_ip',
                'specific_problem',
                # 影响面
                'down_site_count', 'impacted_service', 'whether_impacted_service',
                'site_outage', 'ticket_type', 'suspended', 'root_cause',
                # 链路
                'status', 'operation_type', 'current_handler',
                'last_processer', 'last_process_time',
                # 时效
                'sla_status', 'sla_time', 'sla_remain_time', 'sla_deadline',
                'fault_duration_time', 'alarm_occur_time', 'alarm_clear_time',
                'fault_resolved', 'created_time',
                # 数据新鲜度（告诉用户这个快照是什么时候同步的）
                '_sync_time',
                # 操作流水原文 —— 由 _chain_steps 解析成链路
                'create_detail', 'fo_accept_detail', 'fo_process_detail',
                'bo_accept_detail', 'bo_process_detail',
                'third_accept_detail', 'third_process_detail',
                'confirm_detail', 'closed_detail',
            )
        },
    }


# ------------------------------------------------------------------ #
# 处理链路：把操作流水原文解析成结构化步骤
# ------------------------------------------------------------------ #

# 链路顺序与官方口径一致（knowledge/01_告警到TT到指派_端到端链路总览.md）：
#   Created → FOAccept/BOAccept → FOProcess/BOProcess
#   → [ThirdAccept → ThirdProcess] → Confirm → Closed
# 按这个元组顺序遍历，就自然得到时间序（不用去解析时间字符串排序）。
# 第二项是**标签键**，具体文案按语言在 _CHAIN_LABELS 里取。
_DETAIL_COLS = (
    ('create_detail', 'create'),
    ('fo_accept_detail', 'fo_accept'),
    ('fo_process_detail', 'fo_process'),
    ('bo_accept_detail', 'bo_accept'),
    ('bo_process_detail', 'bo_process'),
    ('third_accept_detail', 'third_accept'),
    ('third_process_detail', 'third_process'),
    ('confirm_detail', 'confirm'),
    ('closed_detail', 'closed'),
)


# ------------------------------------------------------------------ #
# B5：级别规则真匹配（复用同一套 matcher，不做第二份实现）
# ------------------------------------------------------------------ #
#
# 为什么走这条 CLI 而不是在 Node 里再写一个 matcher：
#   手册 B5 明确「不要复制一份会漂移的 JS matcher」。级别规则的条件语义
#   （左折叠 OR/AND、siteSubType vs assetType 区分、字符串比较）在
#   `build_rule_match` / `eval_one` 里已经和 my_app 对齐并验收过。
#   在 Node 里重写必然随时间与工单分析结果不一致 —— 群里问「9990 非 VIP 几级」
#   与直接分析该单得到两个结论，是最难排查的一类故障。
#
# 口径与工单分析**完全一致**：同一个 `build_value_frame` + `match_rules`。
# 缺字段时复用 `missing_rule_fields` 判据输出 incomplete（措辞对齐「未能核对规则」）。


def lookup_level(code: str, asset: str = '', vip: str = '', sub: str = '',
                 domain: str = '', down: str = '',
                 rules: list[dict] | None = None,
                 lang: str = DEFAULT_LANG) -> dict:
    """按「告警码 + 站点属性」直接问级别（不经工单库）。

    构造一个最小的 `row`，走与工单分析**完全相同**的 value frame 与匹配：
      · 用户给了属性 → 参与匹配；
      · 用户没给的属性 → 空串（与「DB 里该列为空」同义）。

    返回：
      · matched  : 命中的规则（id/name/severity/priority）或 None
      · verdict  : 'ok'（命中）/ 'incomplete'（字段缺失、规则未被真正评估）/ 'unknown'（都不匹配）
      · missing  : 缺的字段名（incomplete 时非空）
      · details  : 命中规则的逐条条件求值（便于解释）
    """
    row = {
        'alarm_code': code,
        'site_type': asset,          # assetType: NORMAL / COOL
        'vip_site': vip,             # vipSite: 0 / 1
        'site_information': sub,     # siteSubType: REGULAR / ERA
        'domain': domain,            # netWorkType
        'down_site_count': down,     # downSiteCount
    }
    vf = build_value_frame(row)
    rule = match_rules(vf, rules or [])
    absent = missing_rule_fields(vf, rules or []) if not rule else []
    if rule:
        verdict = 'ok'
    elif absent:
        verdict = 'incomplete'
    else:
        verdict = 'unknown'
    return {
        'found': True,
        'mode': 'lookup_level',
        'verdict': verdict,
        'missing_rule_fields': absent,
        'matched_rule_id': rule['id'] if rule else None,
        'matched_rule_name': rule['name'] if rule else '',
        'suggested_severity': rule['severity'] if rule else '',
        'match_details': fmt_detail(vf, rule['conds']) if rule else '',
        'fields': vf,
    }


def render_level_lookup(res: dict, code: str, attrs: dict, lang: str = DEFAULT_LANG) -> str:
    """渲染级别查表结果（中英）。数据字段（规则名）保持原文，与 TT 通道一致。"""
    L = _L(lang)
    attr_bits = []
    if attrs.get('asset'):
        attr_bits.append(f"assetType={attrs['asset']}")
    if attrs.get('sub'):
        attr_bits.append(f"siteSubType={attrs['sub']}")
    if attrs.get('vip') != '':
        attr_bits.append(f"vipSite={attrs['vip']}")
    if attrs.get('down'):
        attr_bits.append(f"downSiteCount={attrs['down']}")
    attr_str = '，'.join(attr_bits) if attr_bits else ''

    v = res['verdict']
    if v == 'ok':
        head = (f"告警码 {code}（{attr_str}）→ {res['suggested_severity']}"
                if lang != 'en'
                else f"Alarm code {code} ({attr_str}) → {res['suggested_severity']}")
        line = (f"命中规则：# {res['matched_rule_id']} {res['matched_rule_name']}"
                if lang != 'en'
                else f"Matched rule: # {res['matched_rule_id']} {res['matched_rule_name']}")
        det = (f"判定依据：{res['match_details']}" if lang != 'en'
               else f"Basis: {res['match_details']}")
        return f"{head}\n{line}\n{det}"
    if v == 'incomplete':
        miss = '、'.join(res['missing_rule_fields'])
        if lang == 'en':
            return (f"Alarm code {code} ({attr_str}) — cannot determine severity: "
                    f"missing fields {miss}. Rules were not fully evaluated. "
                    f"Provide more site attributes (assetType / vipSite / siteSubType) to match.")
        return (f"告警码 {code}（{attr_str}）—— 级别无法判定：缺少字段 {miss}，"
                f"规则未被真正评估。请补充站点属性（assetType / vipSite / siteSubType）再匹配。")
    # unknown
    if lang == 'en':
        return (f"Alarm code {code} ({attr_str}) — no enabled severity rule matched. "
                f"I won't guess.")
    return f"告警码 {code}（{attr_str}）—— 没有命中的级别规则。我不会按通用知识猜。"


# ------------------------------------------------------------------ #
# 多语言文案
# ------------------------------------------------------------------ #
# SUPPORTED_LANGS / DEFAULT_LANG 定义在文件顶部（它们被用作形参默认值，
# 必须在函数定义之前求值）。这里只放各语言的文案表。
_CHAIN_LABELS: dict[str, dict[str, str]] = {
    'zh': {
        'create': '创建', 'fo_accept': 'FO 受理', 'fo_process': 'FO 处理',
        'bo_accept': 'BO 受理', 'bo_process': 'BO 处理',
        'third_accept': '第三方受理', 'third_process': '第三方处理',
        'confirm': '确认', 'closed': '关单',
    },
    'en': {
        'create': 'Create', 'fo_accept': 'FO Accept', 'fo_process': 'FO Process',
        'bo_accept': 'BO Accept', 'bo_process': 'BO Process',
        'third_accept': 'Third-party Accept', 'third_process': 'Third-party Process',
        'confirm': 'Confirm', 'closed': 'Closed',
    },
}

# SLA 状态取值 → 各语言标签。
# 只列**非超期**状态；超期由 _SLA_OVERDUE + `sla_remain_time` 为负共同判定。
_SLA_STATUS_LABEL: dict[str, dict[str, str]] = {
    'zh': {'pass': '未超期', 'normal': '未超期', 'ok': '未超期',
           'warning': '临近超期', 'warn': '临近超期'},
    'en': {'pass': 'On time', 'normal': 'On time', 'ok': 'On time',
           'warning': 'Near deadline', 'warn': 'Near deadline'},
}
_SLA_OVERDUE = {'overdue', 'fail', 'failed', 'expired'}

_LABELS: dict[str, dict[str, str]] = {
    'zh': {
        # 底层失败的**诊断文案**（写 stderr，退出码 2/3）。
        # 只写「原因」，不写「读取规则表失败：」这类前缀 —— 前缀由 Node 侧
        # 按语言补（tt.js 的 FAIL_TEXT.error）。两层都带前缀会变成
        # 「分析 X 时出错了：读取规则表失败：…」这种套娃。
        'need_openpyxl': '缺少 openpyxl，无法读取规则表'
                         '（已尝试当前解释器与 {path}；该路径在 Y 盘，'
                         '网络盘断开时会一并不可用）。',
        'db_missing': '找不到工单库 {path}（Y 盘，网络盘可能已断开）。',
        'not_found': '工单库里没有找到单号 {tt}。',
        'not_found_hint': (
            '库内最新单号是 {latest}。若你发的单号比它新，多半是数据还没同步过来'
            '（工单库同步有延迟），稍后再试；若比它旧很多，请核对一下单号有没有写错。'
        ),
        'not_found_only': '请核对单号是否写错。',
        'sep': '｜', 'lparen': '（', 'rparen': '）',
        # 抬头里的站点属性：`site_type` → 站点类型(NORMAL/COOL)，
        # `site_information` → 站点子类型(REGULAR/ERA)。两者都先过归一化，
        # 免得把 DB 里的脏值（`REGULAR（Normal)`）原样端给用户。
        'site_type': '站点类型', 'site_sub_type': '站点子类型',
        'no_site': '(无站点)',
        'title': '标题：', 'alarm': '告警：', 'alarm_object': '告警对象：',
        'impact': '影响：',
        'svc_down': '{svc} 中断', 'site_outage': '站点退服',
        'sites_down': '断站 {n}', 'hub_site': 'Hub 站',
        # 多值字段被截断时的后缀（见 _multi）
        'more': ' 等 {n} 个',
        'level': '级别：',
        'level_ok': '（与规则一致，正常）',
        'level_adjust': ' → 【建议改 {sev}】（与规则不一致）',
        'level_unknown': '（规则未命中，需人工确认）',
        # 「判不了」≠「没命中」。实时行只有 eFlow 的紧凑字段，级别规则要的
        # vip_site / down_site_count / domain / site_information 都不在里面，
        # 15 条规则里有 11 条因此**根本没被真正评估**。这时必须说清楚是数据不全，
        # 否则用户会以为「已核实过、确实没有匹配规则」—— 那是假的。
        'level_incomplete': '（实时数据不含级别判定所需字段，未能核对规则）',
        # 缺哪些字段 —— 让用户知道为什么判不了、该去补什么
        'missing_fields': '缺失字段：',
        'rule': '命中规则：', 'basis': '判定依据：',
        # 派单依据（见 resolve_assign）。`assign_none` 是**降级措辞** ——
        # 反推不出来时宁可说不知道，也不报一条猜的规则。
        'assign': '【派单依据】',
        'assign_create': '创建：', 'assign_push': '派单：',
        'assign_cond': '命中条件：',
        'assign_to': ' → {v}',
        'assign_no_cond': '（无条件，兜底默认）',
        'assign_none': '未匹配到推单规则（可能由人工派单或默认流程决定）',
        'assign_not_yet': '尚未受理，派单规则还没生效（当前环节见上）',
        'assign_stale': '规则表快照里状态为 {status}，可能已停用或快照滞后',
        'assign_peers': '（{rules} 条件同样命中、目标相同，无法唯一确定是哪条）',
        'cond_sep': '；',
        'cond_more': '…（共 {n} 条）',
        # 反推失败时的原因文案（键名对应 resolve_assign 的 reason_code）
        'dispatch_fo': '走 FO', 'dispatch_bo': '走 BO',
        'r_disp_fo': '规则指向 FO，但本单实际走的是 BO（或未受理）',
        'r_disp_bo': '规则指向 BO，但本单实际走的是 FO（或未受理）',
        'r_target_absent': '条件命中，但目标处理人未出现在本单派单链路上',
        'chain': '【处理链路】', 'no_chain': '（暂无操作流水）',
        # 里程碑时间轴（见 build_milestones，与 my_app 复盘报告同口径）
        'milestone': '【里程碑时间轴】',
        'ts_count': '（{n}/{total} 有确凿时间戳）',
        'route_auto': '自动派单（{rule}）',
        'route_auto_uncertain': '疑似自动派单（{rule}，与本单流水不完全一致）',
        'route_none': '未匹配到自动派单规则',
        'wo_auto': '{wo}，{creator} 自动创建',
        'wo_human': '{wo}，创建者 {creator}',
        'no_wo': '未产生 WO',
        'step_start': '出发', 'step_arrive': '到场', 'step_leave': '离场',
        'step_sep': '；',
        'onsite_unproven': '未证实：无现场动作明细（有 WO 不等于有人到场）',
        'current': '当前环节：', 'handler': '处理方', 'last_by': '末次处理',
        'chain_assign': ' → 派 {v}',
        'timeliness': '【时效】', 'sync': '数据同步：',
        'sla_prefix': 'SLA：',
        'sla_none': 'SLA：（无数据）',
        'sla_overdue': 'SLA：⚠️ 已超期',
        'sla_raw': 'SLA：{raw}',
        'sla_target': '时长 {v}', 'sla_due': '截止 {v}',
        'sla_remain': '剩余 {v}', 'sla_over': '超时 {v}',
        'fault_none': '故障：（无数据）', 'fault': '故障：',
        'fault_duration': '时长 {v}', 'fault_occurred': '发生 {v}',
        'fault_cleared': '清除 {v}',
        'resolved': '已恢复', 'unresolved': '未恢复',
        # 实时兜底来源标记（本地库 miss、改从 eFlow 实时拉的）
        'live_src': '⚡ 本地库暂无此单，已实时查 eFlow',
    },
    'en': {
        'need_openpyxl': 'openpyxl is missing, so the rules workbook cannot be read '
                         '(tried the current interpreter and {path}; that path is on '
                         'drive Y: and becomes unavailable when the network drive drops).',
        'db_missing': 'Ticket database not found at {path} '
                      '(drive Y: — the network drive may be disconnected).',
        'not_found': 'Ticket {tt} not found in the ticket database.',
        'not_found_hint': (
            'The newest ticket in the database is {latest}. '
            'If yours is newer it is most likely not synced yet (sync has a delay) — retry later. '
            'If it is much older, please double-check the number.'
        ),
        'not_found_only': 'Please double-check the ticket number.',
        'sep': ' | ', 'lparen': '(', 'rparen': ')',
        # 与中文同义。英文标签必须是纯 ASCII —— 抬头会进 cjk_left 断言。
        'site_type': 'Site type', 'site_sub_type': 'Site subtype',
        'no_site': '(no site)',
        'title': 'Title: ', 'alarm': 'Alarm: ', 'alarm_object': 'Alarm object: ',
        'impact': 'Impact: ',
        'svc_down': '{svc} outage', 'site_outage': 'site outage',
        'sites_down': '{n} site(s) down', 'hub_site': 'hub site',
        # 与中文 `等 N 个` 同义（N 是**总数**，不是省略数）
        'more': ' ({n} total)',
        'level': 'Severity: ',
        'level_ok': ' (matches rule)',
        'level_adjust': ' → [suggest {sev}] (differs from rule)',
        'level_unknown': ' (no rule matched — manual check needed)',
        # 「判不了」≠「没命中」；纯 ASCII，见中文同名键的说明
        'level_incomplete':
            ' (live data lacks the fields severity rules need — rules not evaluated)',
        'missing_fields': 'Missing fields: ',
        'rule': 'Matched rule: ', 'basis': 'Basis: ',
        # 与中文同义；`assign_none` 是降级措辞
        'assign': '[Assignment basis]',
        'assign_create': 'Create: ', 'assign_push': 'Dispatch: ',
        'assign_cond': 'Matched: ',
        'assign_to': ' → {v}',
        'assign_no_cond': ' (no conditions — catch-all default)',
        'assign_none': 'no push rule matched (likely manual routing or a built-in default)',
        'assign_not_yet': 'not accepted yet — no dispatch rule applies yet '
                          '(see current stage above)',
        'assign_stale': 'snapshot status: {status} — may be retired or stale',
        'assign_peers': '({rules} matched the same conditions and target — '
                        'cannot pin down which one)',
        'cond_sep': '; ',
        'cond_more': '… ({n} conditions total)',
        # 键名对应 resolve_assign 的 reason_code
        'dispatch_fo': 'route to FO', 'dispatch_bo': 'route to BO',
        'r_disp_fo': 'the rule routes to FO, but this ticket actually went to BO '
                     '(or was never accepted)',
        'r_disp_bo': 'the rule routes to BO, but this ticket actually went to FO '
                     '(or was never accepted)',
        'r_target_absent': "the rule's conditions matched, but its target never appears "
                           "in this ticket's assignment chain",
        'chain': '[Handling chain]', 'no_chain': '(no operation log)',
        # Milestone timeline (see build_milestones, same semantics as my_app's postmortem).
        # Labels inside must stay pure ASCII — the English output passes a
        # zero-Chinese-residue assertion. Rule names are data, not labels.
        'milestone': '[Milestone timeline]',
        'ts_count': ' ({n}/{total} with confirmed timestamps)',
        'route_auto': 'auto-dispatch ({rule})',
        'route_auto_uncertain': 'likely auto-dispatch ({rule}, not fully consistent with the log)',
        'route_none': 'no auto-dispatch rule matched',
        'wo_auto': '{wo}, auto-created by {creator}',
        'wo_human': '{wo}, created by {creator}',
        'no_wo': 'no WO created',
        'step_start': 'Start', 'step_arrive': 'Arrive', 'step_leave': 'Leave',
        'step_sep': '; ',
        'onsite_unproven': 'unproven: no onsite step found (a WO alone does not prove anyone went onsite)',
        'current': 'Current stage: ', 'handler': 'Handling group', 'last_by': 'Last handled by',
        'chain_assign': ' → assigned {v}',
        'timeliness': '[Timeliness]', 'sync': 'Data synced: ',
        'sla_prefix': 'SLA: ',
        'sla_none': 'SLA: (no data)',
        'sla_overdue': 'SLA: ⚠️ OVERDUE',
        'sla_raw': 'SLA: {raw}',
        'sla_target': 'Target {v}', 'sla_due': 'Due {v}',
        'sla_remain': 'Remaining {v}', 'sla_over': 'Overdue by {v}',
        'fault_none': 'Fault: (no data)', 'fault': 'Fault: ',
        'fault_duration': 'Duration {v}', 'fault_occurred': 'Occurred {v}',
        'fault_cleared': 'Cleared {v}',
        'resolved': 'resolved', 'unresolved': 'unresolved',
        # Live-fallback source marker (local DB missed, fetched from eFlow live).
        # 纯 ASCII —— 英文输出要过「零中文残留」断言（见 test-tt-lang.py）。
        'live_src': '[live] not in local DB yet - fetched from eFlow in real time',
    },
}


def _L(lang: str) -> dict:
    """取某语言的文案表（未知语言回退中文）。"""
    return _LABELS.get(lang) or _LABELS[DEFAULT_LANG]


def _one_line(v, limit: int = 0) -> str:
    """把可能含换行/连续空白的字段压成单行。

    聊天窗口里换行就是排版 —— 库里 `sub_alarm_ne_name` 之类字段带 `\n`，
    不压平会把回复的一行拆成好几行。
    """
    s = re.sub(r'\s+', ' ', str(v if v is not None else '')).strip()
    return s[:limit] if limit else s


def _multi(v, max_items: int = 2, lang: str = DEFAULT_LANG) -> str:
    """把 `A;\\nB;\\nC` 这类多值字段压成 `A/B`（超过 max_items 个则省略）。

    这类字段一个单子可能挂着好几个网元，全列出来太长，取前两个够定位。
    省略时的后缀（`等 N 个` / `(N total)`）也要按语言取 —— 这是最早被
    多语言单测抓出来的硬编码中文（英文回复里冒出「等 3 个」）。
    """
    items = [x.strip() for x in re.split(r'[;\n]+', str(v or '')) if x.strip()]
    if not items:
        return ''
    if len(items) > max_items:
        return '/'.join(items[:max_items]) + _L(lang)['more'].format(n=len(items))
    return '/'.join(items)


def _parse_detail(text: str) -> list[dict]:
    """解析一段操作流水，返回结构化步骤列表（一段里可能串了多条）。

    原文形如：
        Operation Step:Create. Operation Result:FO Accept. Operation Time:2026-9-11 03:14:07.
        Operator:assign_rule(assign_rule). Operator Group:. Next Status:Waiting for FO Accept.
        Assign To:. Assignee Group:. Remark:

    做法是「先按 `Operation Step:` 切块，再按已知键名切分」，而不是整段写一个正则 ——
    因为字段值可能为空（`Operator Group:.`）、也可能含句点（Remark），
    固定顺序的长正则很容易在空值处失配。
    """
    out: list[dict] = []
    for chunk in re.split(r'Operation Step:\s*', text)[1:]:
        # ⚠️ `Operator Group:` 必须排在 `Operator:` 前面，否则会在
        # `Operator Group:` 的位置先匹配到 `Operator:`，把键名切错。
        parts = re.split(
            r'(Operation Result:|Operation Time:|Operator Group:|Next Status:|'
            r'Assign To:|Assignee Group:|Remark:|Operator:)',
            chunk,
        )
        step: dict[str, str] = {}
        if parts:
            step['Operation Step'] = parts[0].strip().rstrip('.').strip()
        for i in range(1, len(parts) - 1, 2):
            step[parts[i].rstrip(':')] = parts[i + 1].strip().rstrip('.').strip()
        if step.get('Operation Step') or step.get('Operation Time'):
            out.append(step)
    return out


def _chain_steps(r: dict, lang: str = DEFAULT_LANG, assign: dict | None = None) -> list[dict]:
    """按链路顺序拼出已完成的操作步骤（含「派给谁」）。

    `assign` 是 `resolve_assign()` 的结果。传进来是为了把**第 1 步「创建」**
    的 Operator 从无信息量的 `assign_rule(assign_rule)` 换成具体规则名 ——
    工单库里 `create_detail` 的 Operator 只写死 `assign_rule`，
    命中的是哪条规则要靠反推（见 resolve_assign 的说明）。
    """
    chain_labels = _CHAIN_LABELS.get(lang) or _CHAIN_LABELS[DEFAULT_LANG]
    dispatch = ((assign or {}).get('dispatch') or {}).get('rule')
    steps: list[dict] = []
    for col, key in _DETAIL_COLS:
        raw = r.get(col)
        if not raw:
            continue
        for d in _parse_detail(str(raw)):
            operator = d.get('Operator', '')
            # 只改「创建」这一步：把无信息量的 `assign_rule(assign_rule)` 展开成
            # `assign_rule(assign_rule) → #164 TT单直接派FO accept`。
            # 注意创建人未必是 assign_rule（实测有 `admin(admin)` 这种人工建单），
            # 但**路由规则照样生效**，所以两种情况都补上规则名。
            if key == 'create' and dispatch:
                operator = f"{operator or 'assign_rule'} → {_rule_brief(dispatch)}"
            steps.append({
                'label': chain_labels.get(key, key),
                'time': d.get('Operation Time', ''),
                'operator': operator,
                'assign_to': d.get('Assign To', ''),
                'next': d.get('Next Status', ''),
            })
    return steps


def _sla_line(r: dict, lang: str = DEFAULT_LANG) -> str:
    """SLA 一行。

    **以库里的 `sla_status` 为准，不要自己拿 `sla_deadline` 和当前时间比。**
    实测 TT202609110023 的截止时间是 2026-09-11 15:13:53（早已过去），
    而 `sla_status` 仍是 Pass —— 因为告警在 08:25 就清除了，SLA 时钟随之停表。
    自己算必然误报「已超期」。
    """
    L = _L(lang)
    raw = _one_line(r.get('sla_status'))
    remain = _one_line(r.get('sla_remain_time'))
    if not raw and not remain:
        return L['sla_none']

    # 两个独立信号互相印证「是否超期」：
    #   · sla_status = Failed
    #   · sla_remain_time 为负（如 -0d1h19m）
    # 实测 4/4 一致，且都与「截止时间早于实际清除时间」吻合，故任一为真即判超期。
    #
    # ⚠️ 反过来**不要**拿 `sla_deadline` 跟当前时间比来判断超期：
    # Pass 的单子截止时间可能早已过去（告警清除后 SLA 时钟停表），那样必然误报。
    overdue = remain.startswith('-') or raw.lower() in _SLA_OVERDUE
    if overdue:
        head = L['sla_overdue']
    elif raw:
        status_labels = _SLA_STATUS_LABEL.get(lang) or _SLA_STATUS_LABEL[DEFAULT_LANG]
        label = status_labels.get(raw.lower(), '')
        head = (
            f"{L['sla_prefix']}{label}{L['lparen']}{raw}{L['rparen']}"
            if label else L['sla_raw'].format(raw=raw)
        )
    else:
        head = L['sla_prefix']

    bits = []
    if r.get('sla_time'):
        bits.append(L['sla_target'].format(v=_one_line(r['sla_time'])))
    if r.get('sla_deadline'):
        bits.append(L['sla_due'].format(v=_one_line(r['sla_deadline'])))
    if remain:
        # 负数对人不直观，转成「超时 X」/「Overdue by X」
        bits.append(
            L['sla_over'].format(v=remain.lstrip('-')) if remain.startswith('-')
            else L['sla_remain'].format(v=remain)
        )
    return head + (L['sep'] + L['sep'].join(bits) if bits else '')


def _fault_line(r: dict, lang: str = DEFAULT_LANG) -> str:
    """故障时长 / 发生与清除时间 / 是否已恢复。"""
    L = _L(lang)
    bits = []
    if r.get('fault_duration_time'):
        bits.append(L['fault_duration'].format(v=_one_line(r['fault_duration_time'])))
    if r.get('alarm_occur_time'):
        bits.append(L['fault_occurred'].format(v=_one_line(r['alarm_occur_time'])))
    if r.get('alarm_clear_time'):
        bits.append(L['fault_cleared'].format(v=_one_line(r['alarm_clear_time'])))
    resolved = _one_line(r.get('fault_resolved'))
    if resolved:
        bits.append(L['resolved'] if resolved.lower() in ('yes', '1', 'true') else L['unresolved'])
    if not bits:
        return L['fault_none']
    return L['fault'] + L['sep'].join(bits)


# ------------------------------------------------------------------ #
# 里程碑时间轴 —— 与 my_app「TT 复盘报告（程序化版）」同口径
# ------------------------------------------------------------------ #
# 逻辑移植自 my_app/backend/services/tt_postmortem/build_tt_timeline()。
# 数据同源：两边读的都是 Y 盘同一个 app.db（eflow_tt / eflow_wo），
# 因此不通过 HTTP 接口取 —— 机器人不依赖 my_app 服务在线（见 tt.js 的取舍说明）。
#
# 与旧【处理链路】（_chain_steps）的区别：
#   · 9 跳**全部列出**（含未发生的），无时间戳的排在其后 —— 这就是
#     my_app 页面上「7/9 有确凿时间戳」的呈现；
#   · 跳按**真实发生时间**排序，而不是按流水列的固定顺序 ——
#     告警常常在接单前就自愈了，按列顺序排会出现负间隔；
#   · 相邻跳之间标注间隔（排序后重算）；
#   · 「现场处置」遵循 my_app 2026-09-23 的修正：WO 存在**不能**推定有人到场，
#     无出发/到场/离场明细时一律报「未证实」。

# WO 侧需要的列（eflow_wo 上 wo_no 可按索引命中，实测 0.1s）。
_WO_COLUMNS = (
    'wo_no', 'created_time', 'creator', 'status',
    'start_trip_detail', 'arrive_site_detail', 'leave_site_detail',
)

# my_app 的 STAGE_CONTRACT（9 跳契约）。键 → 标签见 _MILESTONE_LABELS。
_MILESTONE_CONTRACT = (
    'alarm_occur', 'tt_create', 'dispatch_route', 'fo_accept',
    'wo_dispatch', 'onsite_action', 'alarm_clear', 'fo_process', 'confirm',
)

_MILESTONE_LABELS: dict[str, dict[str, str]] = {
    'zh': {
        'alarm_occur': '告警发生', 'tt_create': 'TT建单', 'dispatch_route': '派单路由',
        'fo_accept': 'FO接单', 'wo_dispatch': 'WO派单', 'onsite_action': '现场处置',
        'alarm_clear': '告警清除', 'fo_process': 'FO填报', 'confirm': '关单确认',
    },
    # 纯 ASCII —— 英文输出会过零中文残留断言。
    'en': {
        'alarm_occur': 'Alarm occurred', 'tt_create': 'TT created', 'dispatch_route': 'Dispatch route',
        'fo_accept': 'FO Accept', 'wo_dispatch': 'WO dispatch', 'onsite_action': 'Onsite action',
        'alarm_clear': 'Alarm cleared', 'fo_process': 'FO Process', 'confirm': 'Confirm',
    },
}

# 系统/机器人账号标识（与 my_app 的 _ROBOT_TOKENS 同表）。
# Operator 里出现这些词说明动作是系统自动执行，不能记成「人工」。
_ROBOT_TOKENS = ('fe_robot', 'auto_robot', 'assign_rule', 'system', 'robot', 'auto_')

# WO JSON 明细的时间字段候选（与 my_app 的 _parse_wo_json_step 同序）。
_WO_TIME_KEYS = ('operationtime', 'operatetime', 'opertime', 'opTime', 'time')


def fetch_wo(wo_no, lang: str = DEFAULT_LANG) -> dict | None:
    """按 WO 号取工单行（时间轴的 WO派单 / 现场处置 两跳用）。

    与 fetch_tt 一样：immutable 只读、按列存在性过滤。
    wo_no 上有索引（实测 0.1s），不需要 rowid 缓存。
    查不到或出错都返回 None —— 时间轴其余 7 跳不依赖它。
    """
    if not wo_no or not os.path.isfile(DB_PATH):
        return None
    con = _connect()
    con.row_factory = sqlite3.Row
    try:
        cur = con.cursor()
        cur.execute('PRAGMA table_info("eflow_wo")')
        existing = {c[1] for c in cur.fetchall()}
        cols = [c for c in _WO_COLUMNS if c in existing]
        if 'wo_no' not in cols:
            return None
        sel = ', '.join(f'"{c}"' for c in cols)
        row = cur.execute(
            f'SELECT {sel} FROM "eflow_wo" WHERE UPPER("wo_no") = ?',
            (str(wo_no).strip().upper(),),
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        # WO 侧任何失败都只降级这两跳，不影响时间轴主体
        return None
    finally:
        con.close()


def _parse_dt(s) -> 'datetime | None':
    """解析库中各种时间串 → datetime，失败返回 None。

    ⚠ eFlow 流水里的 Operation Time **月/日不补零**（`2026-9-21 23:25:35`）。
    不用 strptime + 截断的写法：格式串字面长度（`%Y-%m-%d %H:%M:%S` 是 17）
    和实际展开宽度（4 位年是 19）不一致，按 len 截会把秒切掉、静默解析失败
    （首版实测 9 跳时间全空）。这里直接正则拆分量构造 datetime，
    非法值（13 月 / 25 点）ValueError → None，绝不猜。
    """
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    m = re.match(
        r'^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2}))?)?',
        s,
    )
    if not m:
        return None
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0),
        )
    except ValueError:
        return None


def _norm_wo_time(val) -> str:
    """WO JSON 明细里的时间：epoch 毫秒/秒 或已格式化字符串 → 统一字符串。"""
    if val in (None, ''):
        return ''
    s = str(val).strip()
    if re.fullmatch(r'\d{10,13}', s):
        try:
            n = int(s)
            if n < 10_000_000_000:
                n *= 1000
            return datetime.fromtimestamp(n / 1000).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            return ''
    return s


def _is_robot_operator(operator) -> bool:
    low = str(operator or '').lower()
    return any(tok in low for tok in _ROBOT_TOKENS)


def _detail_first(raw) -> tuple[str, 'datetime | None']:
    """从一段 `Operation Step:` 流水里取第一条有内容的步骤 → (operator, dt)。"""
    for st in _parse_detail(raw or ''):
        op = str(st.get('Operator') or '').strip()
        dt = _parse_dt(st.get('Operation Time'))
        if op or dt:
            return op, dt
    return '', None


def _wo_json_step(raw) -> tuple[str, str]:
    """解析 WO 的 JSON 数组型明细（start_trip / arrive_site / leave_site）。

    这些字段**不是** `Operation Time:` 文本，而是 JSON 数组：
    ``[{"opname":"Start Trip","operator":"FE_FE_133","opertime":...}]``。
    实测（my_app 侧）直接套文本解析会把 9,950 条 start_trip 全漏掉。
    返回 (operator 展示名, 时间字符串)；解析不出来就是空串。
    """
    s = str(raw or '').strip()
    if not s or s == '[]':
        return '', ''
    try:
        arr = json.loads(s)
    except Exception:
        return _detail_first(s)[0], ''
    if not isinstance(arr, list) or not arr:
        return '', ''
    item = arr[-1] if isinstance(arr[-1], dict) else {}
    op = str(item.get('operator') or '').strip()
    name = ''
    try:
        cand = json.loads(str(item.get('candidateoperator') or '[]'))
        if isinstance(cand, list) and cand and isinstance(cand[0], dict):
            name = str(cand[0].get('name') or '').strip()
    except Exception:
        name = ''
    display = f'{name}({op})' if (name and op) else (op or name)
    ts = ''
    for k in _WO_TIME_KEYS:
        if item.get(k):
            ts = _norm_wo_time(item[k])
            if ts:
                break
    return display, ts


def _fmt_gap(sec) -> str:
    """秒 → `+40m` / `+7h12m` / `+3d2h` 一类紧凑间隔；负值/空返回空串。"""
    if sec is None:
        return ''
    sec = int(sec)
    if sec < 0:
        return ''
    if sec < 60:
        return f'+{sec}s'
    if sec < 3600:
        return f'+{sec // 60}m'
    if sec < 86400:
        return f'+{sec // 3600}h{(sec % 3600) // 60:02d}m'
    return f'+{sec // 86400}d{(sec % 86400) // 3600}h'


def build_milestones(res: dict, lang: str = DEFAULT_LANG) -> dict:
    """构建里程碑时间轴。返回 {'nodes': [...], 'ts_count': int, 'total': 9}。

    node: {'key','label','time'(str|''),'text'(补充说明),'gap'(距上一跳)}
    时间为空的节点 `time=''`，说明放 `text`（未证实 / 未发生 / 决策型）。
    """
    r = res.get('record') or {}
    labels = _MILESTONE_LABELS.get(lang) or _MILESTONE_LABELS[DEFAULT_LANG]
    L = _L(lang)
    wo = res.get('wo') or {}
    assign = res.get('assign') or {}

    nodes: list[dict] = []

    def _add(key, dt, text=''):
        nodes.append({
            'key': key,
            'label': labels.get(key, key),
            'time': dt.strftime('%Y-%m-%d %H:%M:%S') if dt else '',
            'text': _one_line(text) if text else '',
        })

    # 1. 告警发生
    _add('alarm_occur', _parse_dt(r.get('alarm_occur_time')))

    # 2. TT 建单（created_time 优先，流水时间兜底）
    t_create = _parse_dt(r.get('created_time')) or _detail_first(r.get('create_detail'))[1]
    _add('tt_create', t_create)

    # 3. 派单路由 —— 决策型节点，时间点即建单时刻，不重复显示时间
    disp = (assign.get('dispatch') or {})
    if disp.get('rule'):
        brief = _rule_brief(disp['rule'])
        _add('dispatch_route', None,
             L['route_auto'].format(rule=brief) if disp.get('ok')
             else L['route_auto_uncertain'].format(rule=brief))
    else:
        _add('dispatch_route', None, L['route_none'])

    # 4. FO 接单（BO 流程的单回退 bo_accept_detail，信息不丢）
    op, t = _detail_first(r.get('fo_accept_detail'))
    if not (op or t):
        op, t = _detail_first(r.get('bo_accept_detail'))
    _add('fo_accept', t, op)

    # 5. WO 派单（条件动作：没有 WO 不算缺失）
    if wo.get('wo_no'):
        wo_creator = str(wo.get('creator') or '').strip()
        t_wo = _parse_dt(wo.get('created_time'))
        note = L['wo_auto'].format(wo=wo['wo_no'], creator=wo_creator or '-') \
            if _is_robot_operator(wo_creator) \
            else L['wo_human'].format(wo=wo['wo_no'], creator=wo_creator or '-')
        _add('wo_dispatch', t_wo, note)
    else:
        _add('wo_dispatch', None, L['no_wo'])

    # 6. 现场处置 —— 无出发/到场/离场明细时**必须报「未证实」**，
    #    不能拿「有 WO」当「有人到场」的证据（WO 多为 fe_robot 自动生成）。
    wo_steps = []
    for f, lbl_key in (('start_trip_detail', 'step_start'), ('arrive_site_detail', 'step_arrive'),
                       ('leave_site_detail', 'step_leave')):
        op, ts = _wo_json_step(wo.get(f))
        if not (op or ts):
            op, ts = _detail_first(wo.get(f))
            ts = ts.strftime('%Y-%m-%d %H:%M:%S') if ts else ''
        if op or ts:
            wo_steps.append((L[lbl_key], op, ts))
    if wo_steps:
        first_dt = min((_parse_dt(s[2]) for s in wo_steps if _parse_dt(s[2])),
                       default=None)
        # 分隔符必须按语言取：en 输出里残留全角「；」会被零中文断言抓出来
        text = L['step_sep'].join(f'{lbl} {ts or "-"} {op or "-"}' for lbl, op, ts in wo_steps)
        _add('onsite_action', first_dt, text)
    else:
        _add('onsite_action', None, L['onsite_unproven'])

    # 7. 告警清除
    _add('alarm_clear', _parse_dt(r.get('alarm_clear_time')))

    # 8. FO 填报（BO 流程回退 bo_process_detail）
    op, t = _detail_first(r.get('fo_process_detail'))
    if not (op or t):
        op, t = _detail_first(r.get('bo_process_detail'))
    _add('fo_process', t, op)

    # 9. 关单确认（closed_detail 兜底：有些单只有关单流水没有确认流水）
    op, t = _detail_first(r.get('confirm_detail'))
    if not (op or t):
        op, t = _detail_first(r.get('closed_detail'))
    _add('confirm', t, op)

    # ── 排序：有时间的按真实时间升序在前，无时间的按契约位置排在其后 ──
    # 按列固定顺序排会出现负间隔（告警常常先于接单就自愈了）。
    contract_pos = {k: i for i, k in enumerate(_MILESTONE_CONTRACT)}
    nodes.sort(key=lambda n: (
        0 if n['time'] else 1,
        _parse_dt(n['time']) or datetime.max if n['time'] else datetime.max,
        contract_pos.get(n['key'], 99),
    ))

    # ── 相邻跳间隔：排序后重算（沿用排序前的间隔必然错位）──
    prev = None
    ts_count = 0
    for n in nodes:
        if n['time']:
            ts_count += 1
            cur = _parse_dt(n['time'])
            if prev is not None:
                try:
                    n['gap'] = _fmt_gap((cur - prev).total_seconds())
                except Exception:
                    n['gap'] = ''
            else:
                n['gap'] = ''
            prev = cur if cur is not None else prev
        else:
            n['gap'] = ''

    return {'nodes': nodes, 'ts_count': ts_count, 'total': len(nodes)}


def _assign_lines(res: dict, lang: str = DEFAULT_LANG) -> list[str]:
    """「派单依据」段落：这单排给谁、依据哪条规则。

    数据来自 `resolve_assign()` 的**反推**（工单库不记录命中了哪条规则），
    所以措辞跟着可信度走：反推成立就直接说规则名，反推不成立就明说「无法确认」。
    返回 [] 表示没内容可输出（推单规则表读不到）—— 此时整段都不出现。
    """
    L = _L(lang)
    a = res.get('assign') or {}
    if not a:
        return []
    vf = res.get('fields') or {}
    out = [L['assign']]

    def _head(prefix: str, rule: dict) -> str:
        line = prefix + _rule_brief(rule)
        meta = _rule_meta(rule)
        return line + (f"{L['lparen']}{meta}{L['rparen']}" if meta else '')

    def _reason(entry: dict) -> str:
        code = entry.get('reason_code')
        return f"{L['lparen']}{L[code]}{L['rparen']}" if code and code in L else ''

    # ── 创建阶段：autoDispatch（走 FO 还是 BO）──
    disp = a.get('dispatch')
    if disp:
        rule = disp['rule']
        line = _head(L['assign_create'], rule)
        if disp.get('ok'):
            key = ('dispatch_fo' if rule['operation_result'] == _DISPATCH_FO
                   else 'dispatch_bo' if rule['operation_result'] == _DISPATCH_BO else '')
            if key:
                line += L['assign_to'].format(v=L[key])
        else:
            line += _reason(disp)
        # 「无条件 → 兜底默认」是对规则性质的补充说明，放在最后不打断主句
        if not rule['conds']:
            line += L['assign_no_cond']
        out.append(line)

    # ── 派单阶段：决定派给哪个组 ──
    push = a.get('push')
    if push:
        rule = push['rule']
        line = _head(L['assign_push'], rule)
        if push.get('ok'):
            targets = '/'.join(rule['targets']) or rule.get('target_raw') or '-'
            line += L['assign_to'].format(v=targets)
        else:
            line += _reason(push)
        if push.get('tier') == 'stopped':
            line += (f"{L['lparen']}"
                     + L['assign_stale'].format(status=rule.get('status') or '-')
                     + f"{L['rparen']}")
        out.append(line)
        # 命中条件 —— 直接回答「为什么」。只在确认命中时才列，否则会误导。
        if push.get('ok') and rule['conds']:
            out.append(L['assign_cond'] + _cond_brief(vf, rule['conds'], lang))
        peers = push.get('peers') or []
        if peers:
            out.append(L['assign_peers'].format(
                rules='、'.join(_rule_brief(x) for x in peers[:2])
            ))
    else:
        # 还没受理 → 派单规则本来就轮不到生效，别写成「人工派单」误导人
        if a.get('accepted') is False:
            out.append(L['assign_push'] + L['assign_not_yet'])
        else:
            out.append(L['assign_push'] + L['assign_none'])
    return out


def render_text(res: dict, lang: str = DEFAULT_LANG) -> str:
    """给人看的输出（直接发到聊天窗口，**不过 LLM**）。

    顺序：抬头 → 告警/影响面 → 级别判定 → 处理链路 → 时效。
    文案按 `lang` 取（zh / en）—— 语言由上游按**提问语言**判定后传入，
    见 `src/lang.js`。长度由 config.json 的 `maxReplyChars` 兜底（默认 1500）。
    """
    L = _L(lang)
    sep = L['sep']

    if not res.get('found'):
        out = [L['not_found'].format(tt=res['tt_no'])]
        latest = res.get('latest_tt_no')
        out.append(
            L['not_found_hint'].format(latest=latest) if latest else L['not_found_only']
        )
        return '\n'.join(out)

    r = res['record']
    out: list[str] = []

    # 实时兜底标记：必须**显式**告诉用户这份数据是刚问 eFlow 要的，
    # 而不是本地快照 —— 两者可能不一致（实时行没有「同步时间」，且本地同步有延迟）。
    # 不标的话，用户无从知道刚才那句「本地库里没有」和现在这份报告的关系。
    if res.get('live'):
        out.append(L['live_src'])

    # ── 抬头：单号 · 站点(站号) | 区域 | 站点等级 ──
    # ── 抬头：单号 · 站点(站号) | 区域 | 站点类型 | 站点子类型 ──
    # 站点类型/子类型走归一化函数（`site_type` → NORMAL/COOL、
    # `site_information` → REGULAR/ERA），不直接展示 DB 原始脏值。
    head = f"{res['tt_no']} · {r.get('site_name') or L['no_site']}"
    sid = r.get('site_id') or r.get('ne_id')
    if sid:
        head += f"{L['lparen']}{sid}{L['rparen']}"
    asset = norm_site_type(r.get('site_type'))
    sub_type = norm_site_sub_type(r.get('site_information'))
    extra = [
        v for v in (
            r.get('region_level1'),
            f"{L['site_type']} {asset}" if asset else '',
            f"{L['site_sub_type']} {sub_type}" if sub_type else '',
        ) if v
    ]
    if extra:
        head += sep + sep.join(extra)
    out.append(head)

    if r.get('title'):
        out.append(L['title'] + _one_line(r['title'], 80))

    # ── 告警与影响面 ──
    alarm = (
        f"{L['alarm']}{norm_alarm_code_text(r.get('alarm_code')) or '-'}"
        f"{L['lparen']}{r.get('alarm_severity') or '-'}{L['rparen']}"
    )
    if r.get('domain'):
        alarm += sep + r['domain']
    if r.get('alarm_type'):
        alarm += sep + r['alarm_type']
    out.append(alarm)

    if r.get('sub_alarm_name'):
        where = sep.join(v for v in (_multi(r.get('sub_alarm_ne_name'), lang=lang),
                                     _multi(r.get('sub_alarm_ne_ip'), lang=lang)) if v)
        # 子告警名可能挂着多个（分号/换行分隔），只取第一个，避免这一行过长
        name = _one_line(re.split(r'[;\n]', str(r['sub_alarm_name']))[0], 50)
        out.append(L['alarm_object'] + (f"{where}{sep}{name}" if where else name))

    impact = []
    if str(r.get('whether_impacted_service') or '').lower() in ('yes', '1'):
        impact.append(L['svc_down'].format(svc=r.get('impacted_service') or 'service'))
    if str(r.get('site_outage') or '').lower() in ('yes', '1'):
        impact.append(L['site_outage'])
    if r.get('down_site_count') not in (None, '', '0'):
        impact.append(L['sites_down'].format(n=r['down_site_count']))
    impact.append(f"VIP {r.get('vip_site') or '-'}")
    if str(r.get('hub_site') or '').lower() in ('yes', '1'):
        impact.append(L['hub_site'])
    out.append(L['impact'] + sep.join(impact))

    # ── 级别判定（本通道的原始用途）──
    if res['verdict'] == 'adjust':
        out.append(
            f"{L['level']}{res['current_severity']}"
            + L['level_adjust'].format(sev=res['suggested_severity'])
        )
    elif res['verdict'] == 'ok':
        out.append(f"{L['level']}{res['current_severity']}{L['level_ok']}")
    elif res['verdict'] == 'incomplete':
        # 数据不全 → 明确说「没核对成」，而不是「没命中」。
        # 并列出到底缺哪些字段，用户才知道该去看本地报告 / 去 eFlow 手工确认。
        miss = '、'.join(res.get('missing_rule_fields') or []) if lang == 'zh' \
            else ', '.join(res.get('missing_rule_fields') or [])
        out.append(f"{L['level']}{res['current_severity'] or '-'}{L['level_incomplete']}")
        if miss:
            out.append(L['missing_fields'] + miss)
    else:
        out.append(f"{L['level']}{res['current_severity'] or '-'}{L['level_unknown']}")
    if res['matched_rule_id']:
        out.append(f"{L['rule']}#{res['matched_rule_id']} {res['matched_rule_name']}")
        out.append(f"{L['basis']}{res['match_details']}")

    # ── 里程碑时间轴（替代旧【处理链路】，与 my_app 复盘报告同口径）──
    # 9 跳全部列出；有确凿时间戳的按真实时间排序在前，其余按契约位置排后；
    # 相邻跳标注间隔。旧【处理链路】只列已完成的跳、按流水列固定顺序排，
    # 告警先于接单自愈时读起来像时间倒挂 —— 这就是换掉它的原因。
    ms = build_milestones(res, lang)
    out.append('')
    out.append(L['milestone'] + L['ts_count'].format(n=ms['ts_count'], total=ms['total']))
    for i, n in enumerate(ms['nodes'], 1):
        if n['time']:
            line = f"{i}. {n['label']}  {n['time']}"
            if n['gap']:
                line += f"{L['lparen']}{n['gap']}{L['rparen']}"
            if n['text']:
                line += f"  {n['text']}"
        elif n['text']:
            line = f"{i}. {n['label']}  {L['lparen']}{n['text']}{L['rparen']}"
        else:
            line = f"{i}. {n['label']}"
        out.append(line)

    out.append(L['current'] + _one_line(r.get('operation_type') or r.get('status') or '-'))
    who = []
    if r.get('current_handler'):
        who.append(f"{L['handler']} {_one_line(r['current_handler'])}")
    if r.get('last_processer'):
        lp = f"{L['last_by']} {_one_line(r['last_processer'])}"
        if r.get('last_process_time'):
            lp += f" @ {_one_line(r['last_process_time'])}"
        who.append(lp)
    if who:
        out.append(sep.join(who))

    # ── 派单依据（「这单排给谁、依据哪条规则」）──
    assign_lines = _assign_lines(res, lang)
    if assign_lines:
        out.append('')
        out.extend(assign_lines)

    # ── 时效 ──
    out.append('')
    out.append(L['timeliness'])
    out.append(_sla_line(r, lang))
    out.append(_fault_line(r, lang))
    if r.get('_sync_time'):
        out.append(L['sync'] + str(r['_sync_time'])[:19].replace('T', ' '))

    return '\n'.join(out)


def rebuild_index() -> int:
    """重建本地单号索引。耗时约 15 秒（要扫一遍 1.58GB 的全表）。"""
    if not os.path.isfile(DB_PATH):
        print(f'找不到工单库：{DB_PATH}', file=sys.stderr)
        return 2
    t0 = time.time()
    con = _connect()
    try:
        cur = con.cursor()
        mapping = _build_index(cur)
        cur.execute('SELECT max(rowid) FROM "eflow_tt"')
        max_rid = cur.fetchone()[0] or 0
    except Exception as e:
        print(f'重建失败：{e}', file=sys.stderr)
        return 3
    finally:
        con.close()
    _save_index(mapping, max_rid)
    print(f'✓ 本地单号索引已重建：{len(mapping)} 个单号')
    print(f'  缓存文件：{_INDEX_CACHE}')
    print(f'  耗时：{time.time() - t0:.1f}s（之后每次查单号约 3ms）')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description='TT 单分析')
    ap.add_argument('tt_no', nargs='?', help='TT 单号，如 TT202609150073')
    ap.add_argument('--json', action='store_true', help='输出 JSON')
    ap.add_argument('--lang', default=DEFAULT_LANG, choices=list(SUPPORTED_LANGS),
                    help='回复语言：zh（默认）/ en —— 由上游按提问语言判定后传入')
    ap.add_argument('--live-row',
                    help='改用这份 JSON（eflow-live-tt.py 的实时结果）分析，跳过本地库。'
                         '传 - 表示从 stdin 读入。')
    ap.add_argument('--rebuild-index', action='store_true',
                    help='重建本地单号索引后退出（首次部署、或数据大量更新后跑一次）')
    # B5：按「码 + 站点属性」直接问级别（复用同一套 matcher，见 lookup_level）。
    ap.add_argument('--lookup-level', metavar='CODE',
                    help='级别查表：给告警码，配合 --asset/--vip/--sub 等属性直接判定级别')
    ap.add_argument('--asset', default='', help='assetType（NORMAL / COOL）')
    ap.add_argument('--vip', default='', help='vipSite（0 / 1）')
    ap.add_argument('--sub', default='', help='siteSubType（REGULAR / ERA）')
    ap.add_argument('--domain', default='', help='netWorkType（如 OCS）')
    ap.add_argument('--down', default='', help='downSiteCount')
    args = ap.parse_args()

    if args.rebuild_index:
        return rebuild_index()

    # —— B5：级别查表模式（不需要 TT 单号）——
    if args.lookup_level:
        try:
            rules = load_rules(lang=args.lang)
        except Exception as e:
            print(str(e), file=sys.stderr)
            return 2
        res = lookup_level(
            args.lookup_level, args.asset, args.vip, args.sub, args.domain, args.down,
            rules=rules, lang=args.lang,
        )
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(render_level_lookup(
                res, args.lookup_level,
                {'asset': args.asset, 'vip': args.vip, 'sub': args.sub, 'down': args.down},
                args.lang,
            ))
        # 退出码：命中 0；incomplete 4（能判但字段缺）；unknown 1（不匹配）
        return 0 if res['verdict'] == 'ok' else (4 if res['verdict'] == 'incomplete' else 1)

    if not args.tt_no:
        ap.error('需要提供 TT 单号（或使用 --rebuild-index / --lookup-level）')

    try:
        rules = load_rules(lang=args.lang)
    except Exception as e:
        # 只打**原因**，不加「读取规则表失败：」前缀 —— 上游 tt.js 已经按语言
        # 包了一层「分析 X 时出错了：」，两层都加前缀会套娃。
        print(str(e), file=sys.stderr)
        return 2

    # 推单/派单规则是**可选增强**（用来回答「排给谁、依据哪条规则」）。
    # 读不到就静默降级：整段「派单依据」不输出，其余照常。
    try:
        push_rules = load_push_rules(lang=args.lang)
    except Exception:
        push_rules = []

    # 实时行：本地库查不到时由 eflow-live-tt.py 从 eFlow 实时拉回来的。
    # 解析失败**不静默降级成「查本地库」** —— 否则用户发一个本地没有的新单，
    # 会收到「工单库里没有找到」这句话，而事实是我们没去实时查。
    live_row = None
    if args.live_row is not None:
        try:
            raw = sys.stdin.read() if args.live_row == '-' else args.live_row
            live_row = json.loads(raw)
            if not isinstance(live_row, dict):
                raise ValueError('实时行必须是 JSON 对象')
        except Exception as e:
            print(f'实时行解析失败：{e}', file=sys.stderr)
            return 2

    try:
        res = analyze(args.tt_no, rules, args.lang, push_rules, live_row=live_row)
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(render_text(res, args.lang))
    return 0 if res.get('found') else 1


if __name__ == '__main__':
    sys.exit(main())
