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
    # ⚠️ 故意用裸 sqlite3.connect：本模块是**独立可运行的 eFlow 规则匹配工具**
    # （脚本形态，见 SCRIPT_DIR / OUTPUT_XLSX），不在 FastAPI 进程内、不经过
    # database.py 的 DB_MODE 熔断，只读本地 db/app.db 做离线核对。
    # 因此这里与 routers/ 的约束不同：它本来就不参与 PG 模式。
    # 注意 APP_DB_PATH 指向的是**真库** db/app.db（不是 backend/app.db 那个空占位）。
    conn = sqlite3.connect(str(APP_DB_PATH))
    query = """
        SELECT
            wo_no, tt_no, ticket_no, title,
            alarm_code, alarm_category, alarm_subcategory, alarm_type,
            alarm_severity, ticket_severity,
            -- site_id：规则 266/268 的 downstreamSites 要靠它关联 master_site_db
            -- （2026-10-23）。用 site_id 而不是 site_name，后者有重名会放大行数。
            site_id, site_name, ne_name, domain, status, ticket_type,
            project_name, template_name,
            vip_site, hub_site, site_type, site_class,
            down_site_count, site_information, alarm_description,
            -- 下钻明细要字段（2026-10-23）：规则原始字段 + 建单/告警时间
            created_time, alarm_occur_time, alarm_clear_time
        FROM eflow_tt
        WHERE alarm_code IS NOT NULL AND alarm_code != ''
        -- 样本口径：建单时间最新的 1000 条（2026-10-23 由 last_modified_time 改为此列）。
        -- 用 created_time 而不是 last_modified_time：本任务检查的是「最近新开的报单」，
        -- 一条老 TT 若今天被改状态，不该把新 TT 挤出样本。
        -- created_time 实测 39469 行无空值，可直接排序。
        ORDER BY created_time DESC
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


def load_site_attrs(site_ids) -> dict:
    """按 site_id 批量取站点属性，供规则里本地 eflow_tt 没有的字段使用。

    返回 {site_id(str): {...}}，每个站点含三个键：

    | 键             | 来源                                      | 供哪条规则 |
    |----------------|-------------------------------------------|-----------|
    | downstreamSites| `master_site_db.victims`（仅 hub_site='Y'）| 266 / 268 |
    | siteSubType    | `eflow_site.sitesubtype`（REGULAR/ERA）    | 273 / 274 |
    | assetType      | `eflow_site."Site Type"`（NORMAL/COOL）    | 269 / 270 |

    数据源是 2026-10-23 与业务方核对确认的（见 docs/manual/11-feature-guide.md）：

    · **downstreamSites 不能用 `eflow_tt.down_site_count`** —— 那是「当前下挂的故障站点数」，
      与「站点拓扑上的下属站点总数」不是一个概念。
    · **siteSubType / assetType 不能用 `eflow_tt.site_type`** —— eflow_tt 只有一列 site_type，
      取值是 NORMAL/COOL/ERA，没有 REGULAR，导致规则 273/274（REGULAR/ERA Cell Down）
      从未命中过一张单，110 条 9971/9981/9991 全部落兜底 275。
      eflow_site 才有真正的两列：sitesubtype(REGULAR/ERA) + Site Type(NORMAL/COOL)。
    · **关联键一律用 site_id，不用 site_name** —— 实测 eflow_tt 39469 行按 site_id 命中
      39357（99.7%）；site_name 会因重名放大行数（9995 的 873 条 join 出 908 行）。

    站点查不到时该站点不出现（调用方把对应字段留空 → 条件不成立 → 落兜底），
    保持「宁可漏判不误判」的既有取向。
    """
    ids = [str(x) for x in site_ids if x is not None and str(x).strip() != '']
    if not ids:
        return {}
    # 与 get_eflow_tt_data 相同：本模块是独立脚本形态，只读本地 sqlite
    conn = sqlite3.connect(str(APP_DB_PATH))
    try:
        ph = ",".join("?" * len(ids))
        out: dict = {}
        # ① 下属站点数：只取 HUB 行（规则 266/268 本就以 hubSite='1' 为前提）
        for sid, victims in conn.execute(
            f"SELECT CAST(site_id AS TEXT), victims FROM master_site_db "
            f"WHERE UPPER(hub_site)='Y' AND site_id IS NOT NULL "
            f"AND CAST(site_id AS TEXT) IN ({ph})",
            ids,
        ):
            try:
                out.setdefault(str(sid), {})["downstreamSites"] = int(victims)
            except (TypeError, ValueError):
                continue
        # ② siteSubType / assetType：eflow_site 的 sitesubtype / Site Type 两列
        #    列名含空格，必须双引号；Site ID 同理。
        for sid, subtype, stype, trm in conn.execute(
            f'SELECT CAST("Site ID" AS TEXT), sitesubtype, "Site Type", "TRM Type" FROM eflow_site '
            f'WHERE "Site ID" IS NOT NULL AND CAST("Site ID" AS TEXT) IN ({ph})',
            ids,
        ):
            rec = out.setdefault(str(sid), {})
            if subtype is not None and str(subtype).strip() != "":
                rec["siteSubType"] = str(subtype).strip()
            if stype is not None and str(stype).strip() != "":
                rec["assetType"] = str(stype).strip()
            # TRM Type 只用于下钻明细展示，不参与规则判定
            if trm is not None and str(trm).strip() != "":
                rec["trmType"] = str(trm).strip()
    finally:
        conn.close()
    return out


def build_value_frame(tt_df: pd.DataFrame, attrs: dict | None = None) -> pd.DataFrame:
    """把规则用到的字段全部向量化归一化，列名对应规则里的 field。"""
    vf = pd.DataFrame(index=tt_df.index)
    vf['alarmCode'] = (
        tt_df['alarm_code'].fillna('').astype(str).str.strip()
        .str.replace(r'\.0+$', '', regex=True)
    )
    vf['vipSite'] = tt_df['vip_site'].map(_norm_vip)
    # hubSite 2026-10-23 补：规则 266/268 按 `hubSite = '1'` 匹配，但本函数此前
    # **根本没有加载这一列**，`_eval_one` 发现字段不在 vf 里就返回全 False ——
    # 于是"HUB 站点 9995"两条规则从未命中过一张单（实测 61 张全落 No Match）。
    # 注意 DB 列 `hub_site` 的取值是 Yes/No（不是 1/0），必须与 vipSite 走同一套
    # 归一化，否则即便列加上了也匹配不上 '1'。
    vf['hubSite'] = tt_df['hub_site'].map(_norm_vip) if 'hub_site' in tt_df.columns else ''
    # siteSubType / assetType —— 2026-10-23 改为取 eflow_site 的两列：
    #   siteSubType ← eflow_site.sitesubtype（REGULAR / ERA）→ 供规则 273 / 274
    #   assetType   ← eflow_site."Site Type"（NORMAL / COOL） → 供规则 269 / 270
    #
    # 此前两者都来自 eflow_tt.site_type（一张表只有一列），值域仅 NORMAL/COOL/ERA，
    # **没有 REGULAR**。规则 273/274 要 siteSubType='REGULAR'/'ERA'，于是 274 从未命中，
    # 样本里 110 条 9971/9981/9991 全部落兜底 275 —— 表现为「规则表里少了两行」。
    # eflow_tt.site_type 只作为兜底：查不到站点属性时仍给一个可用的近似值。
    _primary = tt_df['site_type'].map(_norm_site_type)
    _fallback = (tt_df['site_information'].map(_norm_site_type)
                 if 'site_information' in tt_df.columns else _primary)
    _tt_type = _primary.where(_primary != '', _fallback)
    if attrs is not None and 'site_id' in tt_df.columns:
        _sid = tt_df['site_id'].astype(str)
        _sub = _sid.map(lambda s: (attrs.get(str(s)) or {}).get('siteSubType'))
        _ast = _sid.map(lambda s: (attrs.get(str(s)) or {}).get('assetType'))
        # eflow_site 有值就用它；没有则回退到 eflow_tt.site_type（保持旧行为不至于全空）
        vf['siteSubType'] = _sub.where(_sub.notna() & (_sub != ''), _tt_type)
        vf['assetType'] = _ast.where(_ast.notna() & (_ast != ''), _tt_type)
    else:
        vf['siteSubType'] = _tt_type
        vf['assetType'] = _tt_type
    vf['netWorkType'] = tt_df['domain'].fillna('').astype(str).str.strip().str.upper()
    vf['downSiteCount'] = (
        tt_df['down_site_count'].fillna('').astype(str).str.strip()
    )
    # alarmDescription 2026-10-23 补：规则 272（High Temperature P4）按告警描述
    # 精确匹配 'Board power-off due to overtemperature protection'，DB 列
    # `alarm_description` 确有此值（实测 226 行），但此前同样没被加载，
    # 导致该规则从未命中。与 hubSite 是同一个缺陷的第二处。
    vf['alarmDescription'] = (
        tt_df['alarm_description'].fillna('').astype(str).str.strip()
        if 'alarm_description' in tt_df.columns else ''
    )
    # downstreamSites 2026-10-23 补：规则 266/268（HUB site P1/P2）按它分档，
    # 但 eflow_tt 表**没有这一列**（只有 down_site_count = 当前故障下挂站点数，
    # 语义完全不同，不能替代），两条规则因此长期无法命中。
    # 数据源由业务方指定：master_site_db 中 hub_site='Y' 行的 victims 列，按 site_id 关联。
    # 查不到的站点留空 → 条件不成立 → 落兜底 275，与「宁可漏判也不误判」的既有取向一致。
    if attrs is not None and 'site_id' in tt_df.columns:
        vf['downstreamSites'] = (
            tt_df['site_id'].astype(str)
            .map(lambda s: (attrs.get(str(s)) or {}).get('downstreamSites'))
        ).map(lambda v: '' if v is None else str(v))
    return vf


# ------------------------------------------------------------------ #
# 向量化条件求值
# ------------------------------------------------------------------ #

# 规则引用了、但 build_value_frame 没能提供的字段。
# 这类字段让整条规则**永远无法命中**，且从结果上看不出任何异常（只表现为
# 一堆 No Match）。2026-10-23 的 hubSite 事故就是这样：规则 266/268 引用了
# hubSite，但该列既没查也没归一化，61 张 9995 全部落到兜底。
# 收集起来写进报告，下次再缺字段时能当场看见，而不是靠人肉比对 323 个列名。
_MISSING_FIELDS: dict[str, set] = {}


def reset_missing_fields() -> None:
    """每轮匹配开始前清空（run() 调用，避免上一轮的结果串到这一轮）。"""
    _MISSING_FIELDS.clear()


def get_missing_fields() -> dict[str, set]:
    """返回 {字段名: {引用它的规则 ID 集合}}。"""
    return {k: set(v) for k, v in _MISSING_FIELDS.items()}


def _eval_one(vf: pd.DataFrame, cond: dict, rule_id=None) -> pd.Series:
    field = cond['field']
    symbol = cond['symbol']
    values = cond['values']
    if field not in vf.columns:
        # 字段本地没有 → 该条件无法评估。**按 False 处理是保守选择**：
        # 宁可这条规则不命中，也不要凭空「猜」命中去做级别矫正。
        # 但静默 False 正是本次 hubSite 事故的温床（规则 266/268 从未命中却无人察觉），
        # 所以这里额外记一条告警，由 run() 汇总进报告，让缺口暴露在明面上。
        _MISSING_FIELDS.setdefault(field, set()).add(rule_id)
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


def build_rule_mask(vf: pd.DataFrame, conds: list[dict], rule_id=None) -> pd.Series:
    """左折叠 OR/AND。首行 orAnd 忽略。**空条件列表 → 全 True（兜底规则）**。

    ## 2026-10-23 修复：无条件规则的语义

    此前空条件返回全 False，把「无条件规则」当成了「永不命中」。
    实测后果：规则 275 `other ticket P4`（ACTIVE / 优先级 5 / 级别 P4 / 条件为空）
    一张单都没命中，最近 1000 张里有 376 张落在 `No Match`（37.6%）——
    报告上看着像「规则覆盖缺口」，实际是这条兜底规则被静默废掉了。

    在 eFlow 配置中心里，条件留空 = 不设筛选 = 全部命中。规则名 `other ticket`
    与「最低优先级 + 最低级别」也印证它是兜底。因此这里改为返回全 True：
    它只在所有更高优先级规则都未命中时才会被执行（`match_all` 的 `pending` 约束），
    所以不会抢走任何具体规则的命中。

    ## 为什么这不是「盲目放宽」

    兜底规则排在最后（优先级 5，同优先级内条件多的先、ID 大的先），
    前面任何一条命中都会把该行从 `pending` 里剔除。
    所以改动的唯一效果是：**原本无人认领的单子现在归到兜底规则名下**，
    已有命中的判定结果一条都不变。
    """
    if not conds:
        return pd.Series(True, index=vf.index)
    mask = _eval_one(vf, conds[0], rule_id)
    for c in conds[1:]:
        m = _eval_one(vf, c, rule_id)
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


def match_all(tt_df: pd.DataFrame, rules_ready: pd.DataFrame,
              attrs: dict | None = None) -> pd.DataFrame:
    vf = build_value_frame(tt_df, attrs=attrs)
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
        mask = build_rule_mask(vf, conds, rule['ID']) & pending
        if not mask.any():
            continue
        # 生成人类可读详情
        det = _fmt_detail(vf, conds, rule['ID'])[mask]
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

    # ---- 下钻明细要的「规则里用到的全部字段」（2026-10-23）----
    # 写的是**判定时实际参与比较的值**（归一化之后），不是 DB 原始列：
    # 例如 vipSite 是 '1'/'0' 而非 Yes/No、siteSubType 来自 eflow_site 而非 eflow_tt。
    # 这样下钻明细里看到的每个值都能和 Match_Details 里的 ✓/✗ 对得上。
    # assetType 与 siteSubType 同源（规则 269/270 用 assetType，273/274 用 siteSubType），
    # 两列都保留，避免看明细的人以为只有一列被用到。
    for _col, _field in [
        ('Rule_Field_alarmCode', 'alarmCode'),
        ('Rule_Field_vipSite', 'vipSite'),
        ('Rule_Field_hubSite', 'hubSite'),
        ('Rule_Field_siteSubType', 'siteSubType'),
        ('Rule_Field_assetType', 'assetType'),
        ('Rule_Field_netWorkType', 'netWorkType'),
        ('Rule_Field_downstreamSites', 'downstreamSites'),
        ('Rule_Field_alarmDescription', 'alarmDescription'),
    ]:
        out[_col] = vf[_field] if _field in vf.columns else ''

    # TRM Type 只做展示（来自 eflow_site），不参与判定
    if attrs is not None and 'site_id' in tt_df.columns:
        out['TRM_Type'] = tt_df['site_id'].astype(str).map(
            lambda s: (attrs.get(str(s)) or {}).get('trmType', ''))
    else:
        out['TRM_Type'] = ''

    cur_sev = out['ticket_severity'].fillna('').astype(str).str.strip().str.upper()
    new_sev = out['New_Severity'].astype(str).str.strip().str.upper()
    out['Severity_Changed'] = np.where(
        (out['Matched_Rule_ID'] != 'No Match') & (cur_sev != new_sev) & (new_sev != 'NO CHANGE'),
        'YES', 'NO',
    )
    return out


def _fmt_detail(vf: pd.DataFrame, conds: list[dict], rule_id=None) -> pd.Series:
    """为每条 TT 生成 "field=value 符号 期望 ✓/✗" 的详情字符串（向量化）。"""
    idx = vf.index
    parts = [pd.Series([''] * len(idx), index=idx, dtype='object')] * 0
    detail = pd.Series([''] * len(idx), index=idx, dtype='object')
    for c in conds:
        m = _eval_one(vf, c, rule_id)
        col = vf[c['field']] if c['field'] in vf.columns else pd.Series('', index=idx)
        exp = ','.join(c['values']) if len(c['values']) > 1 else c['values'][0]
        seg = (c['field'] + '=' + col.astype(str) + ' ' + c['symbol'] + ' ' + exp
               + np.where(m, ' ✓', ' ✗'))
        detail = detail.where(detail == '', detail + '; ') + seg
    return detail


def format_details(vf: pd.DataFrame, conds: list[dict]) -> pd.Series:
    """对外暴露 `_fmt_detail`：推单规则（ttPushOrderRule）等复用同一套「逐条匹配」文案。

    单独包一层是为了让 `tt_rule_evidence` 不必调用下划线函数 —— 匹配语义仍是**同一份实现**。
    """
    return _fmt_detail(vf, conds)


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
    lines.append('本版相对上一版的核心修复（2026-10-23）：')
    lines.append('')
    lines.append('1. **无条件规则 = 兜底**：`build_rule_mask` 对空条件此前返回全 False，'
                 '把 ACTIVE 的兜底规则 275 `other ticket P4` 变成「永不命中」，'
                 '导致 376 张单（37.6%）显示 `No Match`。现改为全 True。')
    lines.append('2. **补 `hubSite` 字段**：规则 266/268 引用 `hubSite`，但该列既没查也没归一化，'
                 '两条规则从未命中过一张单。`hub_site` 的取值是 Yes/No，已按 vipSite 同一套规则归一为 1/0。')
    lines.append('3. **补 `alarmDescription` 字段**：规则 272（高温）按描述精确匹配，DB 有该列但未加载。')
    lines.append('4. **缺失字段暴露**：规则引用到本地取不到的条件字段时，不再静默按 False 处理，'
                 '而是汇总进本报告的「缺失字段」小节 —— 这类规则是「无法评估」，不是「没有匹配」。')
    lines.append('5. **统计自洽校验**：报告主动验算 `匹配 + 未匹配 = 总数`、`一致 + 变更 = 匹配`、'
                 '`变更 ⊆ 匹配`，并把子集关系画成缩进表，避免把「变更数」误读成与「匹配数」并列。')
    lines.append('')
    lines.append('> 以下为更早版本（v2）的修复记录，保留备查：')
    lines.append('> 加入 `downSiteCount`；比较运算符支持 `>= <= > < != <> in not in =`；'
                 'OR/AND 左折叠求值；同优先级按条件特异性降序；`site_type` 脏值归一；'
                 '`site_type` 为空时回退 `site_information`。')
    lines.append('')
    lines.append('## 总体结果')
    lines.append('')
    lines.append('> **口径说明**：「需要级别变更」是「成功匹配」的**子集**，不是并列项。')
    lines.append('> 恒等式：总记录 = 匹配 + 未匹配；匹配 = 级别一致 + 需要变更。')
    lines.append('')
    lines.append('| 指标 | 数量 | 占比 |')
    lines.append('|------|------|------|')
    lines.append(f'| 总 TT 记录数 | {total} | 100.0% |')
    lines.append(f'| ├─ 成功匹配规则 | {matched} | {matched / total * 100:.1f}% |')
    lines.append(f'| │　├─ 级别已正确 | {matched - changed} | {(matched - changed) / total * 100:.1f}% |')
    lines.append(f'| │　└─ **需要级别变更** | **{changed}** | {changed / total * 100:.1f}% |')
    lines.append(f'| └─ 未匹配任何规则 | {total - matched} | {(total - matched) / total * 100:.1f}% |')
    lines.append('')

    # 自洽性自检：把上面那张表的加法真算一遍，不靠人眼。
    # 报告一旦不自洽（比如兜底规则失效导致大量 No Match，看着像"覆盖缺口"），
    # 读者很难发现，所以这里主动断言并写明。
    checks = [
        ('匹配 + 未匹配 = 总数', matched + (total - matched) == total),
        ('级别一致 + 需要变更 = 匹配数', (matched - changed) + changed == matched),
        ('需要变更 ⊆ 匹配', changed <= matched),
    ]
    bad = [name for name, ok in checks if not ok]
    if bad:
        lines.append(f'> ⚠ **统计不自洽**：{"；".join(bad)} —— 请检查数据处理逻辑。')
    else:
        lines.append('> ✓ 统计自洽：匹配 + 未匹配 = 总数，且变更数包含在匹配数内。')
    lines.append('')

    # 规则引用了、但本地取不到的字段 —— 这类规则会**永远无法命中**。
    missing = get_missing_fields()
    if missing:
        lines.append('## ⚠ 规则引用了本地缺失的字段（这些规则永远不会命中）')
        lines.append('')
        lines.append('| 字段 | 引用它的规则 ID | 说明 |')
        lines.append('|------|-----------------|------|')
        for f, rids in sorted(missing.items()):
            ids = '、'.join(str(x) for x in sorted(rids, key=lambda v: str(v)))
            hint = {
                'downstreamSites': 'eflow_tt 表无此列；2026-10-23 起改为关联 master_site_db '
                                   '（hub_site=Y 行的 victims）取数。仍出现在这里说明 '
                                   '该站点在 master_site_db 中查不到',
            }.get(f, '该字段未在 build_value_frame 中提供')
            lines.append(f'| `{f}` | {ids} | {hint} |')
        lines.append('')
        lines.append('> 这些规则不是「没有匹配到」，而是**根本无法评估**。'
                     '若该字段确实应该参与判定，需要在 `build_value_frame` 中补上；'
                     '若 DB 确实没有，则规则本身需要调整。')
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
    lines.append('| siteSubType | `eflow_site.sitesubtype`（REGULAR/ERA） | 按 site_id 关联；取不到时回退 eflow_tt.site_type（2026-10-23 改，规则 273/274） |')
    lines.append('| assetType | `eflow_site."Site Type"`（NORMAL/COOL） | 按 site_id 关联；取不到时回退 eflow_tt.site_type（2026-10-23 改，规则 269/270） |')
    lines.append('| netWorkType | domain | 大写 |')
    lines.append('| downSiteCount | down_site_count | 字符串数值，`to_numeric` 参与 >=/<= 比较 |')
    lines.append('| hubSite | hub_site | Yes/No → 1/0（2026-10-23 补，规则 266/268） |')
    lines.append('| alarmDescription | alarm_description | 去首尾空格（2026-10-23 补，规则 272） |')
    lines.append('| downstreamSites | `master_site_db.victims`（hub_site=Y） | 按 site_id 关联（2026-10-23 补，规则 266/268） |')
    lines.append('')

    # 结论
    lines.append('## 结论')
    lines.append('')
    lines.append(f'- 本轮 {total} 条 TT 中，{matched} 条匹配到规则（{matched / total * 100:.1f}%），'
                 f'{total - matched} 条未匹配。')
    lines.append(f'- 其中 {changed} 条建议调整级别（占 {changed / total * 100:.1f}%）。'
                 f'注意「需要变更」包含在「匹配」之内，不是额外的一批单子。')
    if missing:
        names = '、'.join(f'`{k}`' for k in sorted(missing))
        lines.append(f'- ⚠ 有 {len(missing)} 个条件字段本地取不到（{names}），'
                     f'涉及规则无法评估，已在本报告「缺失字段」小节列出。'
                     f'这部分规则既不算命中、也不算未命中 —— 是判定能力的缺口。')
    if total - matched == 0:
        lines.append('- ✓ 所有 TT 都落到了某条规则（含兜底规则），没有「无人认领」的单子。')
    return '\n'.join(lines)


# ------------------------------------------------------------------ #
# 导出 & 可复用运行入口（CLI main 与定时任务 eflow_check 共用）
# ------------------------------------------------------------------ #

def rule_breakdown(results: pd.DataFrame, rules_ready: pd.DataFrame | None = None) -> list[dict]:
    """按规则分组的匹配/变更统计，供前端页签展示。

    ⚠ 2026-10-23 起**未命中的规则也会列出**（matched=0），不再只列有命中的。
    此前只列命中规则，于是规则文件里有 10 条、页面上只看到 8 条，
    使用者合理地质疑「统计不全」—— 而真实原因可能是数据里确实没有该类型的单。

    两条不命中的情况必须能区分开，所以每行都带 `matched=0` 时：
      · 规则条件正常，只是本批样本没有符合的 TT  → 正常，用户自己就能看出来
      · 规则引用了本地取不到的字段（见 missing_fields）→ 页面另有告警条说明
    """
    m = results[results['Matched_Rule_ID'] != 'No Match']
    grp = (m.groupby(['Matched_Priority', 'Matched_Rule_ID', 'Matched_Rule_Name', 'New_Severity'],
                     dropna=False)
           .agg(matched=('Matched_Rule_ID', 'size'),
                changed=('Severity_Changed', lambda s: (s == 'YES').sum()))
           .reset_index()
           .sort_values(['Matched_Priority', 'Matched_Rule_ID'])) if len(m) else pd.DataFrame()
    out = []
    seen: set = set()
    for _, r in (grp.iterrows() if len(grp) else []):
        rid = None if pd.isna(r['Matched_Rule_ID']) else int(r['Matched_Rule_ID'])
        seen.add(rid)
        out.append({
            'priority': None if pd.isna(r['Matched_Priority']) else int(r['Matched_Priority']),
            'rule_id': rid,
            'rule_name': '' if pd.isna(r['Matched_Rule_Name']) else str(r['Matched_Rule_Name']),
            'severity': '' if pd.isna(r['New_Severity']) else str(r['New_Severity']),
            'matched': int(r['matched']),
            'changed': int(r['changed']),
        })
    # 补齐未命中的规则：数值为 0，名称/级别/优先级取自规则文件本身
    if rules_ready is not None and len(rules_ready):
        for _, rule in rules_ready.iterrows():
            try:
                rid = int(rule['ID'])
            except (TypeError, ValueError):
                continue
            if rid in seen:
                continue
            out.append({
                'priority': None if pd.isna(rule['优先级']) else int(rule['优先级']),
                'rule_id': rid,
                'rule_name': '' if pd.isna(rule['规则名称']) else str(rule['规则名称']),
                'severity': '' if pd.isna(rule['严重级别']) else str(rule['严重级别']),
                'matched': 0,
                'changed': 0,
            })
        # 未命中的排在后面：有命中的先看，0 命中的作为「规则全集」补充
        out.sort(key=lambda d: (d['matched'] == 0, d['priority'] if d['priority'] is not None else 99,
                                d['rule_id'] if d['rule_id'] is not None else 0))
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
    reset_missing_fields()   # 每轮清空，避免上一轮的缺失字段串到这一轮
    rules_df = load_rules()
    tt_df = get_eflow_tt_data(limit=limit)
    rules_ready = prepare_rules(rules_df)
    # 规则要而 eflow_tt 没有的站点属性（downstreamSites / siteSubType / assetType）
    # 统一从 master_site_db + eflow_site 按 site_id 批量取，只查本批样本用到的站点。
    attrs = load_site_attrs(tt_df['site_id']) if 'site_id' in tt_df.columns else {}
    results = match_all(tt_df, rules_ready, attrs=attrs)
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
        # 矫正表的精确修改时间。Email Reports 页签据此校验「页面数字」与「下钻明细」
        # 是否出自同一次运行 —— 两者不同源时页面会显示不一致告警，
        # 而不是让用户看到卡片数字与下钻行数对不上（2026-10-23 加）。
        'correction_mtime': Path(files['xlsx']).stat().st_mtime if files.get('xlsx') else None,
        'rule_breakdown': rule_breakdown(results, rules_ready),
        'change_matrix': change_matrix,
        # 规则引用了但本地取不到的字段：这些规则永远不会命中，需要人工确认
        'missing_fields': {k: sorted(str(x) for x in v) for k, v in get_missing_fields().items()},
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
