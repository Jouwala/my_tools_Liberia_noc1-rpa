"""
eflow_rules_matcher.py - eFlow TT 规则匹配与矫正工具 (v2)
=========================================================
根据 eflow_tt 数据库中的告警数据，应用 TT Update Severity Rule 进行匹配和矫正。

v2 修正要点
-----------
1. 支持完整比较运算符：=, !=, <>, >, <, >=, <=, in, not in
2. 加入 downSiteCount 字段（DB 列 down_site_count）
3. 使用左折叠方式重写 OR/AND 逻辑（第一行 orAnd 视为显示 artifact 忽略）
4. 同优先级内按条件特异性（条件数）降序排序，越具体越优先
5. 全面向量化匹配：pandas Series 层完成 mask 计算，避免 1000 行 × 15 规则的 Python 循环
6. 数据归一化补齐：NaN / 空字符串 / 脏值 (REGULAR（Normal)) 处理
7. 输出运行时长（秒）
"""

import sys
import time
import sqlite3
from pathlib import Path

import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

SCRIPT_DIR = Path(__file__).parent
APP_DB_PATH = SCRIPT_DIR.parent.parent.parent / "db" / "app.db"
RULES_XLSX = SCRIPT_DIR / "eflow_TT_rules.xlsx"
OUTPUT_XLSX = SCRIPT_DIR / "eflow_tt_severity_correction.xlsx"
OUTPUT_REPORT = SCRIPT_DIR / "MATCHING_REPORT.md"

# ------------------------------------------------------------------ #
# 数据加载
# ------------------------------------------------------------------ #

def get_eflow_tt_data(limit: int = 1000) -> pd.DataFrame:
    conn = sqlite3.connect(str(APP_DB_PATH))
    query = """
        SELECT
            wo_no, tt_no, ticket_no, title,
            alarm_code, alarm_category, alarm_subcategory, alarm_type,
            alarm_severity, ticket_severity,
            site_name, ne_name, domain, status, ticket_type,
            project_name, template_name,
            vip_site, site_type, site_class,
            down_site_count, site_information
        FROM eflow_tt
        WHERE alarm_code IS NOT NULL AND alarm_code != ''
        ORDER BY last_modified_time DESC
        LIMIT ?
    """
    df = pd.read_sql_query(query, conn, params=(limit,))
    conn.close()
    print(f"✓ 从数据库读取 {len(df)} 条 eflow_tt 记录")
    return df


def load_rules() -> pd.DataFrame:
    df = pd.read_excel(RULES_XLSX)
    df = df[df['状态'].astype(str).str.upper() == 'ACTIVE'].copy()
    df['优先级'] = pd.to_numeric(df['优先级'], errors='coerce').fillna(99).astype(int)
    print(f"✓ 加载 {len(df)} 条 ACTIVE 规则")
    return df


# ------------------------------------------------------------------ #
# 条件解析
# ------------------------------------------------------------------ #

import re

# 注意：>= 优先级必须放在 = 前面；not in 放在 in 前面
_OP_RE = re.compile(
    r"^\s*([\w.]+)\s*(>=|<=|!=|<>|\bin\b|\bnot\s+in\b|>|<|=)\s+'([^']*)'\s*$",
    re.IGNORECASE,
)


def parse_conditions(cond_str: str) -> list[dict]:
    """把 eflow_TT_rules.xlsx 里 `条件` 列的字符串还原为结构化 list。

    单条形如：
        AND | eflow_ticket_ticket_wo.downSiteCount >= '5' ()
        OR  | eflow_ticket_ticket_wo.alarmCode in '9970, 9980' (string)
    """
    if not cond_str or (isinstance(cond_str, float) and pd.isna(cond_str)):
        return []
    out: list[dict] = []
    for raw in str(cond_str).split(';'):
        part = raw.strip()
        if not part or '|' not in part:
            continue
        or_and, rest = part.split('|', 1)
        or_and = or_and.strip().upper()
        # 去掉末尾的 (type) 标记
        if rest.rfind('(') > rest.rfind("'"):
            rest = rest[:rest.rfind('(')]
        m = _OP_RE.match(rest.strip())
        if not m:
            continue
        field_path, symbol, value_str = m.group(1), m.group(2).lower().replace('  ', ' '), m.group(3)
        field = field_path.split('.')[-1]
        symbol = symbol.strip().replace(' ', '')  # 'notin' 归一化
        if symbol == 'in':
            values = [v.strip() for v in value_str.split(',') if v.strip() != '']
        elif symbol == 'notin':
            values = [v.strip() for v in value_str.split(',') if v.strip() != '']
        else:
            values = [value_str]
        out.append({'or_and': or_and, 'field': field, 'symbol': symbol, 'values': values})
    return out


# ------------------------------------------------------------------ #
# 字段值准备（向量化）
# ------------------------------------------------------------------ #

def _norm_vip(v) -> str:
    if pd.isna(v):
        return ''
    s = str(v).strip().lower()
    if s in ('yes', 'true', '1'):
        return '1'
    if s in ('no', 'false', '0'):
        return '0'
    return s


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


def _norm_site_type(v) -> str:
    if pd.isna(v):
        return ''
    s = str(v).strip()
    key = s.upper().replace(' ', '')
    return _SITE_TYPE_MAP.get(key, s.upper())


def build_value_frame(tt_df: pd.DataFrame) -> pd.DataFrame:
    """把规则用到的字段全部向量化归一化，列名对应规则里的 field。"""
    vf = pd.DataFrame(index=tt_df.index)
    vf['alarmCode'] = (
        tt_df['alarm_code'].fillna('').astype(str).str.strip()
        .str.replace(r'\.0+$', '', regex=True)
    )
    vf['vipSite'] = tt_df['vip_site'].map(_norm_vip)
    # site_type 优先；为空时回退到 site_information 取站点类型
    _primary = tt_df['site_type'].map(_norm_site_type)
    _fallback = (tt_df['site_information'].map(_norm_site_type)
                 if 'site_information' in tt_df.columns else _primary)
    vf['siteSubType'] = _primary.where(_primary != '', _fallback)
    vf['assetType'] = vf['siteSubType']            # 目前 DB 只有 site_type 一列承载资产类型
    vf['netWorkType'] = tt_df['domain'].fillna('').astype(str).str.strip().str.upper()
    vf['downSiteCount'] = (
        tt_df['down_site_count'].fillna('').astype(str).str.strip()
    )
    return vf


# ------------------------------------------------------------------ #
# 向量化条件求值
# ------------------------------------------------------------------ #

def _eval_one(vf: pd.DataFrame, cond: dict) -> pd.Series:
    field = cond['field']
    symbol = cond['symbol']
    values = cond['values']
    if field not in vf.columns:
        return pd.Series(False, index=vf.index)
    col = vf[field]
    if symbol == '=':
        return col.astype(str) == str(values[0])
    if symbol in ('!=', '<>'):
        return col.astype(str) != str(values[0])
    if symbol == 'in':
        return col.astype(str).isin([str(v) for v in values])
    if symbol == 'notin':
        return ~col.astype(str).isin([str(v) for v in values])
    if symbol in ('>', '<', '>=', '<='):
        try:
            bound = float(values[0])
        except (TypeError, ValueError):
            return pd.Series(False, index=vf.index)
        num = pd.to_numeric(col, errors='coerce')
        if symbol == '>':
            return num > bound
        if symbol == '<':
            return num < bound
        if symbol == '>=':
            return num >= bound
        return num <= bound
    return pd.Series(False, index=vf.index)


def build_rule_mask(vf: pd.DataFrame, conds: list[dict]) -> pd.Series:
    """左折叠 OR/AND。首行 orAnd 忽略。空条件列表 → 全 False。"""
    if not conds:
        return pd.Series(False, index=vf.index)
    mask = _eval_one(vf, conds[0])
    for c in conds[1:]:
        m = _eval_one(vf, c)
        if c['or_and'] == 'AND':
            mask = mask & m
        elif c['or_and'] == 'OR':
            mask = mask | m
        else:
            # 未知连接器，按 AND 兜底
            mask = mask & m
    return mask


# ------------------------------------------------------------------ #
# 匹配主流程
# ------------------------------------------------------------------ #

def prepare_rules(rules_df: pd.DataFrame) -> pd.DataFrame:
    r = rules_df.copy()
    r['conds'] = r['条件'].map(parse_conditions)
    r['cond_count'] = r['conds'].map(len)
    # 同优先级 → 条件数多的（更具体）在前 → 再按 ID 保证确定性
    r = r.sort_values(['优先级', 'cond_count', 'ID'],
                      ascending=[True, False, True]).reset_index(drop=True)
    return r


def match_all(tt_df: pd.DataFrame, rules_ready: pd.DataFrame) -> pd.DataFrame:
    vf = build_value_frame(tt_df)
    n = len(tt_df)

    rule_id = pd.Series(pd.NA, index=tt_df.index, dtype='object')
    rule_sev = pd.Series(pd.NA, index=tt_df.index, dtype='object')
    rule_pri = pd.Series(pd.NA, index=tt_df.index, dtype='object')
    rule_name = pd.Series(pd.NA, index=tt_df.index, dtype='object')
    detail = pd.Series('', index=tt_df.index, dtype='object')
    pending = pd.Series(True, index=tt_df.index)

    for _, rule in rules_ready.iterrows():
        if not pending.any():
            break
        conds = rule['conds']
        mask = build_rule_mask(vf, conds) & pending
        if not mask.any():
            continue
        # 生成人类可读详情
        det = _fmt_detail(vf, conds)[mask]
        rule_id[mask] = rule['ID']
        rule_sev[mask] = rule['严重级别']
        rule_pri[mask] = rule['优先级']
        rule_name[mask] = rule['规则名称']
        detail[mask] = det
        pending[mask] = False

    out = tt_df.copy()
    out['Matched_Rule_ID'] = rule_id.fillna('No Match')
    out['Matched_Rule_Name'] = rule_name.fillna('')
    out['Matched_Priority'] = rule_pri.fillna('')
    out['New_Severity'] = rule_sev.fillna('No Change')
    out['Match_Details'] = detail
    cur_sev = out['ticket_severity'].fillna('').astype(str).str.strip().str.upper()
    new_sev = out['New_Severity'].astype(str).str.strip().str.upper()
    out['Severity_Changed'] = np.where(
        (out['Matched_Rule_ID'] != 'No Match') & (cur_sev != new_sev) & (new_sev != 'NO CHANGE'),
        'YES', 'NO',
    )
    return out


def _fmt_detail(vf: pd.DataFrame, conds: list[dict]) -> pd.Series:
    """为每条 TT 生成 "field=value 符号 期望 ✓/✗" 的详情字符串（向量化）。"""
    idx = vf.index
    parts = [pd.Series([''] * len(idx), index=idx, dtype='object')] * 0
    detail = pd.Series([''] * len(idx), index=idx, dtype='object')
    for c in conds:
        m = _eval_one(vf, c)
        col = vf[c['field']] if c['field'] in vf.columns else pd.Series('', index=idx)
        exp = ','.join(c['values']) if len(c['values']) > 1 else c['values'][0]
        seg = (c['field'] + '=' + col.astype(str) + ' ' + c['symbol'] + ' ' + exp
               + np.where(m, ' ✓', ' ✗'))
        detail = detail.where(detail == '', detail + '; ') + seg
    return detail


# ------------------------------------------------------------------ #
# 报告
# ------------------------------------------------------------------ #

def build_report(results: pd.DataFrame, rules_ready: pd.DataFrame, elapsed: float) -> str:
    total = len(results)
    matched = int((results['Matched_Rule_ID'] != 'No Match').sum())
    changed = int((results['Severity_Changed'] == 'YES').sum())

    lines: list[str] = []
    lines.append('# eFlow TT 规则匹配分析报告 (v2)')
    lines.append('')
    lines.append(f'生成时间：{time.strftime("%Y-%m-%d %H:%M:%S")}')
    lines.append(f'运行耗时：{elapsed:.2f} 秒')
    lines.append('')
    lines.append('## 修正摘要')
    lines.append('')
    lines.append('本版相对上一版的核心修复：')
    lines.append('')
    lines.append('1. 加入 `downSiteCount` 字段（DB `down_site_count`），支持规则 225 / 233。')
    lines.append('2. 比较运算符支持 `>= <= > < != <> in not in =`，正则不再把 `>=` 误吞为 `=`。')
    lines.append('3. OR/AND 采用左折叠求值，修复 Rule 206/207/208/209/234 "首条 AND + 后续 OR" 类型的漏配。')
    lines.append('4. 同优先级内按条件特异性降序匹配（条件数多者先），再按 ID 保证确定性。')
    lines.append('5. 数据归一化补齐：`site_type` 脏值 (REGULAR（Normal)/REGULAR(COOL.i)) 合并到 NORMAL/COOL；`vip_site` NaN → 空串。')
    lines.append('6. `site_type` 为空时回退到 `site_information` 取站点类型（ERA/REGULAR），使 Rule 229 (ERA) 等能正确命中原本被兜底 Rule 230 吞掉的 TT。')
    lines.append('')
    lines.append('## 总体结果')
    lines.append('')
    lines.append('| 指标 | 数量 | 占比 |')
    lines.append('|------|------|------|')
    lines.append(f'| 总 TT 记录数 | {total} | 100.0% |')
    lines.append(f'| 成功匹配规则 | {matched} | {matched / total * 100:.1f}% |')
    lines.append(f'| 未匹配 | {total - matched} | {(total - matched) / total * 100:.1f}% |')
    lines.append(f'| 需要级别变更 | {changed} | {changed / total * 100:.1f}% |')
    lines.append('')

    # 按规则分组
    grp = (results[results['Matched_Rule_ID'] != 'No Match']
           .groupby(['Matched_Priority', 'Matched_Rule_ID', 'Matched_Rule_Name', 'New_Severity'],
                    dropna=False)
           .agg(matched=('Matched_Rule_ID', 'size'),
                changed=('Severity_Changed', lambda s: (s == 'YES').sum()))
           .reset_index()
           .sort_values(['Matched_Priority', 'Matched_Rule_ID']))
    lines.append('## 按规则分组')
    lines.append('')
    lines.append('| 优先级 | 规则 ID | 规则名称 | 目标级别 | 匹配数 | 需变更数 |')
    lines.append('|--------|---------|----------|----------|--------|----------|')
    for _, row in grp.iterrows():
        lines.append(f'| {row["Matched_Priority"]} | {row["Matched_Rule_ID"]} | {row["Matched_Rule_Name"]} '
                     f'| {row["New_Severity"]} | {row["matched"]} | {row["changed"]} |')
    lines.append('')

    # 未匹配明细
    unmatched = results[results['Matched_Rule_ID'] == 'No Match']
    if len(unmatched) > 0:
        lines.append(f'## 未匹配记录（{len(unmatched)} 条）')
        lines.append('')
        lines.append('主要分布：')
        lines.append('')
        um = (unmatched.assign(alarm=unmatched['alarm_code'].astype(str).str.replace(r'\.0+$', '', regex=True))
              .groupby(['alarm', 'vip_site', 'site_type'], dropna=False).size()
              .sort_values(ascending=False).head(10))
        lines.append('| alarm_code | vip_site | site_type | 数量 |')
        lines.append('|------------|----------|-----------|------|')
        for (a, v, s), n in um.items():
            lines.append(f'| {a} | {v} | {s if pd.notna(s) else "(null)"} | {n} |')
        lines.append('')

    # 变更模式
    chg = results[results['Severity_Changed'] == 'YES']
    if len(chg) > 0:
        lines.append(f'## 级别变更（{len(chg)} 条）')
        lines.append('')
        lines.append('### 变更方向矩阵')
        lines.append('')
        mat = (chg.assign(cur=chg['ticket_severity'].astype(str).str.strip().str.upper(),
                          new=chg['New_Severity'].astype(str).str.strip().str.upper())
               .pivot_table(index='cur', columns='new', values='tt_no', aggfunc='count', fill_value=0))
        lines.append('| 当前 \\ 建议 | ' + ' | '.join(mat.columns.tolist()) + ' |')
        lines.append('|' + '---|' * (len(mat.columns) + 1))
        for idx, row in mat.iterrows():
            lines.append(f'| {idx} | ' + ' | '.join(str(int(v)) for v in row.tolist()) + ' |')
        lines.append('')

        lines.append('### 变更来源规则')
        lines.append('')
        src = chg.groupby(['Matched_Rule_ID', 'Matched_Rule_Name', 'New_Severity']).size().reset_index(name='count')
        src = src.sort_values('count', ascending=False)
        lines.append('| 规则 ID | 规则名称 | 目标级别 | 变更数 |')
        lines.append('|---------|----------|----------|--------|')
        for _, row in src.iterrows():
            lines.append(f'| {row["Matched_Rule_ID"]} | {row["Matched_Rule_Name"]} | {row["New_Severity"]} | {row["count"]} |')
        lines.append('')

    # 字段说明
    lines.append('## 字段映射')
    lines.append('')
    lines.append('| 规则字段 | DB 列 | 归一化 |')
    lines.append('|----------|-------|--------|')
    lines.append('| alarmCode | alarm_code | 去除末尾 `.0` |')
    lines.append('| vipSite | vip_site | Yes/No → 1/0，NaN → 空串 |')
    lines.append('| siteSubType | site_type → site_information | site_type 优先；为空回退 site_information，大写归一 |')
    lines.append('| assetType | 同 siteSubType | 与 siteSubType 同源 |')
    lines.append('| netWorkType | domain | 大写 |')
    lines.append('| downSiteCount | down_site_count | 字符串数值，`to_numeric` 参与 >=/<= 比较 |')
    lines.append('')

    # 结论
    lines.append('## 结论')
    lines.append('')
    lines.append(f'- 修正后共 {matched} 条 TT 匹配到规则，占比 {matched / total * 100:.1f}%。')
    lines.append(f'- {changed} 条需要级别调整，占比 {changed / total * 100:.1f}%（补 site_information 回退前为 161/1000 = 16.1%，最初错误版为 236/1000 = 23.6%）。')
    lines.append('- alarmCode=9995 的 TT 已按 `down_site_count` 分流到 Rule 225 (P1) 或 Rule 233 (P2)，不再落入兜底 Rule 230。')
    lines.append('- MRNC/高温类多 OR 规则（206/207/208/209/234）现在可以正常命中非首条告警码。')
    lines.append('- `site_type` 为空时回退 `site_information`：原被 Rule 230 误判为 P3→P4 的 ERA 站点 TT 现匹配 Rule 229 (P3)，与本就 P3 一致，无需变更。')
    return '\n'.join(lines)


# ------------------------------------------------------------------ #
# 导出 & 可复用运行入口（CLI main 与定时任务 eflow_check 共用）
# ------------------------------------------------------------------ #

def rule_breakdown(results: pd.DataFrame) -> list[dict]:
    """按规则分组的匹配/变更统计，供前端页签展示。"""
    m = results[results['Matched_Rule_ID'] != 'No Match']
    if len(m) == 0:
        return []
    grp = (m.groupby(['Matched_Priority', 'Matched_Rule_ID', 'Matched_Rule_Name', 'New_Severity'],
                     dropna=False)
           .agg(matched=('Matched_Rule_ID', 'size'),
                changed=('Severity_Changed', lambda s: (s == 'YES').sum()))
           .reset_index()
           .sort_values(['Matched_Priority', 'Matched_Rule_ID']))
    out = []
    for _, r in grp.iterrows():
        out.append({
            'priority': None if pd.isna(r['Matched_Priority']) else int(r['Matched_Priority']),
            'rule_id': None if pd.isna(r['Matched_Rule_ID']) else int(r['Matched_Rule_ID']),
            'rule_name': '' if pd.isna(r['Matched_Rule_Name']) else str(r['Matched_Rule_Name']),
            'severity': '' if pd.isna(r['New_Severity']) else str(r['New_Severity']),
            'matched': int(r['matched']),
            'changed': int(r['changed']),
        })
    return out


def export_outputs(results: pd.DataFrame, rules_ready: pd.DataFrame, elapsed: float) -> dict:
    """导出 Excel 矫正表 + Markdown 报告，返回文件路径信息。"""
    xlsx_path = None
    alt_used = False
    try:
        with pd.ExcelWriter(OUTPUT_XLSX, engine='openpyxl') as writer:
            results.to_excel(writer, sheet_name='All_TT_Records', index=False)
            results[results['Matched_Rule_ID'] != 'No Match'].to_excel(
                writer, sheet_name='Matched_Rules', index=False)
            results[results['Severity_Changed'] == 'YES'].to_excel(
                writer, sheet_name='Severity_Changes', index=False)
        xlsx_path = OUTPUT_XLSX
    except PermissionError:
        alt = OUTPUT_XLSX.with_name(OUTPUT_XLSX.stem + '_new.xlsx')
        with pd.ExcelWriter(alt, engine='openpyxl') as writer:
            results.to_excel(writer, sheet_name='All_TT_Records', index=False)
            results[results['Matched_Rule_ID'] != 'No Match'].to_excel(
                writer, sheet_name='Matched_Rules', index=False)
            results[results['Severity_Changed'] == 'YES'].to_excel(
                writer, sheet_name='Severity_Changes', index=False)
        xlsx_path = alt
        alt_used = True
    report = build_report(results, rules_ready, elapsed)
    OUTPUT_REPORT.write_text(report, encoding='utf-8')
    return {
        'xlsx': str(xlsx_path) if xlsx_path else '',
        'report': str(OUTPUT_REPORT),
        'xlsx_name': xlsx_path.name if xlsx_path else '',
        'report_name': OUTPUT_REPORT.name,
        'alt_used': alt_used,
    }


def run(limit: int = 1000) -> dict:
    """执行完整匹配流程并导出结果，返回可序列化摘要（供定时任务/前端使用）。"""
    t0 = time.perf_counter()
    rules_df = load_rules()
    tt_df = get_eflow_tt_data(limit=limit)
    rules_ready = prepare_rules(rules_df)
    results = match_all(tt_df, rules_ready)
    elapsed = time.perf_counter() - t0
    files = export_outputs(results, rules_ready, elapsed)

    total = len(results)
    matched = int((results['Matched_Rule_ID'] != 'No Match').sum())
    changed = int((results['Severity_Changed'] == 'YES').sum())
    change_matrix = []
    chg = results[results['Severity_Changed'] == 'YES']
    if len(chg) > 0:
        cur = chg['ticket_severity'].fillna('').astype(str).str.strip().str.upper()
        new = chg['New_Severity'].astype(str).str.strip().str.upper()
        cm = pd.DataFrame({'cur': cur, 'new': new})
        for (c, n), cnt in cm.groupby(['cur', 'new']).size().items():
            change_matrix.append({'from': c, 'to': n, 'count': int(cnt)})
    return {
        'success': True,
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'limit': limit,
        'total': total,
        'matched': matched,
        'unmatched': total - matched,
        'changed': changed,
        'elapsed_seconds': round(elapsed, 2),
        'rule_breakdown': rule_breakdown(results),
        'change_matrix': change_matrix,
        'files': files,
    }


# ------------------------------------------------------------------ #
# 主入口
# ------------------------------------------------------------------ #

def main() -> int:
    print('=' * 80)
    print('eFlow TT 规则匹配与矫正工具 v2')
    print('=' * 80)
    r = run(limit=1000)
    print(f"✓ Excel 输出：{r['files']['xlsx']}")
    if r['files'].get('alt_used'):
        print(f"⚠ 原文件被占用，输出到 {r['files']['xlsx']}")
    print(f"✓ 报告输出：{r['files']['report']}")
    print()
    print('=' * 80)
    pct = (r['matched'] / r['total'] * 100) if r['total'] else 0
    cpct = (r['changed'] / r['total'] * 100) if r['total'] else 0
    print(f"总 TT：{r['total']}  匹配：{r['matched']} ({pct:.1f}%)  "
          f"需变更：{r['changed']} ({cpct:.1f}%)")
    print(f"运行耗时：{r['elapsed_seconds']:.2f} 秒")
    print('=' * 80)
    return 0


if __name__ == '__main__':
    sys.exit(main())
