/**
 * 结构化查找表 —— 让「码表 / 压缩 / 级别」三类问法**走查表而不走 LLM 自由生成**。
 *
 * ## 为什么单独做一层
 *
 * `03_TT级别规则.md` 是表格 + 完整条件原文。`chunkText` 按 420 字切块，
 * 标题处强制断块，但**表格行仍会被切断**，AND/OR 与结论分离。
 * 同质「告警码 X → 父码 Y」块靠 idBonus 部分缓解，问「CSD 定几级」没有长数字时
 * 仍会召回错行。这些问题的正确答案**明明白白写在语料里**，
 * 交给 flash 总结只会引入幻觉（连 512 token 都装不下完整条件）。
 *
 * 所以：告警码含义 / 压缩结果 / 级别规则 → **脚本查表 + 模板渲染 + 带出处**。
 * LLM 生成的通道只留给真正的叙述题（流程、为什么、SOP）。
 *
 * ## 数据从哪来
 *
 * ingest 时从 `knowledge/*.md` 解析（与线上语料**同源**，不另建一份会漂移的表），
 * 落 `data/lookups.json`（gitignore）。源数据在 md 与 Excel，
 * 每次 `npm run export-kb && npm run ingest` 会重算。
 *
 * ## P0 的边界（不要越界）
 *
 * 级别规则**不做完整 matcher** —— 那会与 `scripts/tt-analyze.py` 的 eFlow 口径漂移。
 * P0 只做到「按告警码列出候选规则 + 条件原文」；用户给了站点属性（VIP/NORMAL/ERA）
 * 时只**过滤**表格里写明该条件的行，吃不准就列候选并注明「未做完整规则引擎匹配」。
 * 真匹配是 P1（B5），复用工单分析的 matcher。
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';

/* -------------------------------- 解析 -------------------------------- */

/** 从 raw 里抽出「### 告警码 12345」下的 `- 含义：…`。 */
export function parseAlarmDict(raw, sourceRel) {
  const out = new Map();
  const re = /^###\s*告警码\s*(\d+)\s*$([\s\S]*?)(?=^###\s|\Z)/gm;
  let m;
  while ((m = re.exec(raw))) {
    const code = m[1];
    const body = m[2];
    const name = (body.match(/^\s*-\s*含义[:：]\s*(.+)$/m) || [])[1]?.trim() || '';
    const count = (body.match(/^\s*-\s*累计\s*TT\s*单数[:：]\s*(\d+)/m) || [])[1];
    const prev = out.get(code);
    // 同一码在文件里可能出现多次（导出按出现次数排，"duplicate" 是原文件特征）。
    // 保留**首次**出现，但用后续出现补全缺失的 name / count ——
    // 否则「含义」为空的那次会覆盖掉有描述的。
    out.set(code, {
      code,
      name: name || prev?.name || '',
      // 「(无描述)」当没有 —— 与字典里的写法一致，渲染时省略
      hasName: (!!name && name !== '(无描述)') || (prev?.hasName ?? false),
      totalTickets: count != null ? Number(count) : prev?.totalTickets,
      source: sourceRel,
    });
  }
  return out;
}

/**
 * 从压缩规则文件里抽「压缩规则速览」段。
 * 同一子码可能出现在多条规则里 —— 全部保留，渲染时 ENABLED 优先、
 * DISABLED 必须标注（**禁止当启用规则输出**）。
 */
export function parseCompressRules(raw, sourceRel) {
  const rules = [];
  const re = /^###\s*压缩规则速览[:：]\s*(\S+)\s*$([\s\S]*?)(?=^###\s|\Z)/gm;
  let m;
  while ((m = re.exec(raw))) {
    const ruleId = m[1].trim();
    const body = m[2];
    const status = (body.match(/状态\s*(ENABLED|DISABLED)/i) || [])[1]?.toUpperCase() || 'UNKNOWN';
    const parentCode = (body.match(/衍生告警（父告警）根告警码[:：]\s*([0-9,\s]+)/) || [])[1]?.replace(/\s/g, '') || '';
    const parentName = (body.match(/衍生告警名称[:：]\s*(.+)$/m) || [])[1]?.trim() || '';
    // 子告警码：站点断站码 + 小区退服码 两行都算
    const childCodes = [];
    for (const line of body.split('\n')) {
      const mm = line.match(/基础告警（子告警）(?:站点断站码|小区退服码)[:：]\s*([0-9,\s]+)/);
      if (mm) childCodes.push(...mm[1].split(',').map((s) => s.trim()).filter(Boolean));
    }
    if (!parentCode) continue; // 没有父码的段不算一条可用规则
    rules.push({
      ruleId,
      childCodes: [...new Set(childCodes)],
      parentCode,
      parentName,
      status,
      source: sourceRel,
    });
  }
  return rules;
}

/**
 * 从级别规则文件抽「| 优先级 | ID | 规则名称 | 级别 | 条件 |」表格。
 * 告警码从条件列抽 `\d{3,}`（规则里也有 8/47 这类短码 —— 短码只在
 * 「告警码」上下文里才触发查表，这里一并收，匹配时按用户给的码精确比对）。
 */
export function parseLevelRules(raw, sourceRel) {
  const rules = [];
  for (const line of raw.split('\n')) {
    // | 2 | 199 | 无线断小区级别重定义-P4 | P4 | OR vipSite = 0; AND alarmCode in ... |
    const m = line.match(/^\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*(P[1-4])\s*\|\s*([^|]+?)\s*\|\s*$/);
    if (!m) continue;
    const [, priority, id, name, severity, when] = m;
    const alarmCodes = [...new Set((when.match(/\d{3,}/g) || []))];
    rules.push({
      id,
      name: name.trim(),
      severity,
      priority: Number(priority),
      alarmCodes,
      when: when.trim(),
      source: sourceRel,
    });
  }
  return rules;
}

/* -------------------------------- 构建 -------------------------------- */

const DICT_FILE = 'TT单-告警码字典.md';
const COMPRESS_FILE = 'TT单-告警压缩规则.md';
const LEVEL_FILE = '03_TT级别规则.md';

/**
 * 扫描 knowledge/ 生成完整查找表对象。
 *
 * @param {string} knowledgeDirAbs 知识库根目录绝对路径
 * @param {string} root            项目根（用于算相对路径出处）
 * @returns {{builtAt:string, alarmCodes:Map, compress:Array, levelRules:Array}}
 */
export function buildLookups(knowledgeDirAbs, root) {
  const rel = (name) => `knowledge/${name}`;
  const read = (name) => {
    const abs = join(knowledgeDirAbs, name);
    return existsSync(abs) ? readFileSync(abs, 'utf8') : '';
  };

  const alarmCodes = parseAlarmDict(read(DICT_FILE), rel(DICT_FILE));
  const compress = parseCompressRules(read(COMPRESS_FILE), rel(COMPRESS_FILE));
  const levelRules = parseLevelRules(read(LEVEL_FILE), rel(LEVEL_FILE));

  // 解析失败要能看见（不要静默空对象）——由调用方（ingest）打印条数
  const built = { builtAt: new Date().toISOString(), alarmCodes, compress, levelRules };
  // 内存对象也带别名表，否则 resolveCodeByName 在未落盘/未 load 时失效
  built.aliases = buildAliases(built);
  return built;
}

/** 落盘 `data/lookups.json`。Map 不能直接 JSON 化，转成普通对象。 */
export function saveLookups(lookups, path) {
  if (!path) throw new Error('saveLookups 需要明确路径');
  mkdirSync(dirname(path), { recursive: true });
  const obj = {
    builtAt: lookups.builtAt,
    alarmCodes: Object.fromEntries(lookups.alarmCodes),
    compress: lookups.compress,
    levelRules: lookups.levelRules,
    aliases: Object.fromEntries(buildAliases(lookups)),
  };
  writeFileSync(path, JSON.stringify(obj), 'utf8');
}

/* -------------------------------- 别名索引 -------------------------------- */

/**
 * 从告警名构造「名称/缩写 → 码」别名表，供**没有数字码**的问法命中查表。
 *
 * 为什么必须做：现场会问「CSD 定几级」「断站是什么级别」这类**不带码**的问题。
 * 手册 §3.3 指出，这类问法没有长数字，向量检索会召回错行（同质块 + 字面权重低）。
 * 有了别名表，`CSD` 能解析成 9920、再走 `lookup_level_rule`，答案来自查表而非生成。
 *
 * 别名来源：告警名全文的归一化形式 + 括号里的缩写（如 `Complete site down (CSD)` → `CSD`）。
 * 归一化：转小写、删空白与标点，便于「4G site down」「4g-sitedown」都能对上。
 */
function normalizeAlias(s) {
  return String(s || '')
    .toLowerCase()
    .replace(/[\s\-_/()（）.]+/g, '')
    .trim();
}

export function buildAliases(lookups) {
  const map = new Map();
  const put = (alias, code) => {
    const k = normalizeAlias(alias);
    if (k.length < 2) return; // 单字符别名噪声太大
    if (!map.has(k)) map.set(k, code);
  };
  for (const [code, d] of lookups?.alarmCodes || []) {
    if (!d.hasName) continue;
    put(d.name, code);
    // 括号里的缩写：Complete site down (CSD) → CSD
    const br = String(d.name).match(/\(([^)]+)\)/);
    if (br) put(br[1], code);
    // 去掉括号部分的名字：`Complete site down (CSD)` → `Complete site down`。
    // 现场常只说主体名（不说缩写），只登记整串会漏「Complete site down 是什么码」。
    const noParen = String(d.name).replace(/[（(][^）)]*[）)]/g, ' ').trim();
    if (noParen && noParen !== d.name) put(noParen, code);
    // 「X/Y」型名称（Fiber/Link Break）的每一段都当别名：
    // 现场常只说其中一半（Fiber Break），整串匹配会漏。
    for (const part of String(d.name).split('/')) put(part, code);
  }
  return map;
}

/**
 * 把问句里的告警名/缩写解析成告警码。找不到返回 ''。
 * 只在**没有数字码**时兜底用。
 */
export function resolveCodeByName(lookups, q) {
  const aliases = lookups?.aliases instanceof Map ? lookups.aliases : new Map(Object.entries(lookups?.aliases || {}));
  if (!aliases.size) return '';
  const nq = normalizeAlias(q);
  if (!nq) return '';
  // 长别名优先，避免短名误吞（如 "csd" 应优先于某个更短的巧合子串）
  const keys = [...aliases.keys()].sort((a, b) => b.length - a.length);
  for (const k of keys) {
    if (nq.includes(k)) return aliases.get(k);
  }
  return '';
}

/**
 * 启动时读一次（与 loadIndex 一样）。文件缺失返回 null ——
 * 查表工具据此回「查找表未构建，请 npm run ingest」，**不 fallback 进 RAG 装懂**。
 */
export function loadLookups(path) {
  try {
    if (!existsSync(path)) return null;
    const o = JSON.parse(readFileSync(path, 'utf8'));
    return {
      builtAt: o.builtAt,
      alarmCodes: new Map(Object.entries(o.alarmCodes || {})),
      compress: Array.isArray(o.compress) ? o.compress : [],
      levelRules: Array.isArray(o.levelRules) ? o.levelRules : [],
      aliases: new Map(Object.entries(o.aliases || {})),
    };
  } catch {
    return null;
  }
}

/* -------------------------------- 查询 -------------------------------- */

/** 查告警码含义。未收录返回 null。 */
export function findAlarmCode(lookups, code) {
  return lookups?.alarmCodes?.get(String(code)) || null;
}

/**
 * 查「子码会被压缩成什么」。同一子码可能命中多条规则 —— 全部返回。
 * 排序：ENABLED 在前（DISABLED 是停用规则，绝不当启用结论给）。
 */
export function findCompress(lookups, code) {
  const c = String(code);
  const hit = (lookups?.compress || []).filter((r) => r.childCodes.includes(c));
  return hit.sort((a, b) => (a.status === 'ENABLED' ? -1 : 1) - (b.status === 'ENABLED' ? -1 : 1));
}

/**
 * 按告警码列出候选级别规则。
 * @param {object} lookups
 * @param {string} code 告警码
 */
export function findLevelByCode(lookups, code) {
  const c = String(code);
  return (lookups?.levelRules || []).filter((r) => r.alarmCodes.includes(c));
}

/** 纯「P1 是什么级别」→ 该级别的规则列表（给规则清单，不编定义）。 */
export function findLevelBySeverity(lookups, severity) {
  const s = String(severity).toUpperCase();
  return (lookups?.levelRules || [])
    .filter((r) => r.severity === s)
    .sort((a, b) => a.priority - b.priority);
}

/**
 * eFlow 表单/告警列表的**字段标签** → 规则引擎里的字段名。
 *
 * ## 这张表为什么必须有
 *
 * 2026-11-10 群内实测：问「RAN Site Type：REGULAR；Site VIP Level：YES；
 * Hub Site Flag：YES；Downstream Site Count：7，alarm code:9995」，机器人答
 * 「级别无法判定：缺少 hubSite、downstreamSites、downSiteCount、assetType…」。
 *
 * 用户**明明白白给了**四个字段，却被判成一个都没给 —— 因为旧版
 * `parseSiteAttrs` 只认**裸值**（`\bVIP\b` / `\bREGULAR\b` 这种），
 * 认不出「标签：值」这种**从 eFlow 界面上照抄**的写法。
 * 值班员在 eFlow 告警列表里看到的就是这些列名，提问自然照抄。
 *
 * 标签取自 my_app `backend/routers/bot_data.py` 的字段字典（eFlow 真实列名）：
 *   `down_site_count` → "Downstream Site Count"
 *   `hub_site`        → "Hub Site Flag"
 *   `vip_level`       → "Site Vip Level"
 *
 * ⚠️ **最要紧的一条**：eFlow 界面上的 "Downstream Site Count" 指的是
 * **`downSiteCount`（当前故障下挂的断站数）**，而级别规则里的
 * `downstreamSites` 是**站点拓扑上的下属站点总数** —— 两个**不同的**字段
 * （my_app `eflow_rules_matcher.load_site_attrs` 的注释里专门讲过这件事）。
 * 规则 266 要求 `downstreamSites>=5` **且** `downSiteCount>=5`，两个都要。
 * 所以标签表里把 "Downstream Site Count" 归给 `downSiteCount`，
 * `downstreamSites` 只认中文的「下属站点数/下游站点总数」与 `downstreamSites` 本名 ——
 * 宁可少认，也不能把一个字段的数当成另一个字段的数去判级。
 */
const LABEL_FIELDS = new Map([
  // —— 枢纽站 ——
  ['hubsiteflag', 'hubSite'],
  ['hubsite', 'hubSite'],
  ['枢纽站标志', 'hubSite'],
  ['枢纽站', 'hubSite'],
  ['枢纽站点', 'hubSite'],
  // —— 当前故障下挂的断站数（eFlow 列名 "Downstream Site Count"）——
  ['downstreamsitecount', 'downSiteCount'],
  ['downsitecount', 'downSiteCount'],
  ['断站数', 'downSiteCount'],
  // —— 站点拓扑上的下属站点总数（**不是** downSiteCount）——
  ['downstreamsites', 'downstreamSites'],
  ['下游站点数', 'downstreamSites'],
  ['下属站点数', 'downstreamSites'],
  ['下游站点数量', 'downstreamSites'],
  ['下属站点数量', 'downstreamSites'],
  ['下游站点总数', 'downstreamSites'],
  ['下属站点总数', 'downstreamSites'],
  // —— 站点子类型 / 资产类型（两个字段取值域不重叠，按**取值**再分派）——
  ['ransitetype', 'siteSubType'],
  ['站点子类型', 'siteSubType'],
  ['sitetype', 'siteSubType'],
  ['站点类型', 'siteSubType'],
  ['ran站点类型', 'siteSubType'],
  ['assettype', 'assetType'],
  ['资产类型', 'assetType'],
  // —— VIP ——
  ['siteviplevel', 'vipSite'],
  ['viplevel', 'vipSite'],
  ['站点vip等级', 'vipSite'],
  ['vip等级', 'vipSite'],
  ['站点vip', 'vipSite'],
  ['vip站点', 'vipSite'],
  ['vip站', 'vipSite'],
  ['vip', 'vipSite'],
  // —— 其它规则字段 ——
  ['networktype', 'netWorkType'],
  ['专业域', 'netWorkType'],
  ['alarmdescription', 'alarmDescription'],
  ['告警描述', 'alarmDescription'],
]);

/** 标签归一：去空格/下划线/连字符/括号，全小写。 */
function normLabel(s) {
  return String(s || '')
    .toLowerCase()
    .replace(/[\s_\-()（）]/g, '');
}

/**
 * 标签 → 字段名。**查不到时剥掉疑问前缀再试一次**。
 *
 * ## 为什么需要（2026-11-10 线上验证时踩到）
 *
 * 值班员口述时常用疑问写法：「是否枢纽站：是」「是否VIP站：是」
 * 「是否下游站点总数：7」。标签表里存的是**字段名**（枢纽站 / VIP站 /
 * 下游站点总数），前面多出来的「是否」让整串对不上，字段就被漏掉 ——
 * 而漏掉 `hubSite` 会让规则 #266/#268/#277 **全部**判不出级别。
 *
 * 更糟的是漏掉 VIP 标签时，裸值兜底会把「是否VIP站：否」判成 **VIP=1**
 * （裸值正则只认「非VIP / 不是VIP / vip=0」，认不出「是否…：否」），
 * 直接把级别算高。这是**答错而不报错**，比漏字段严重。
 *
 * ## 为什么只剥疑问前缀，不做模糊包含
 *
 * 包含匹配会把「不是枢纽站」也当成枢纽站标签（虽然取值会兜住），
 * 但「非VIP站点」这类写法一旦判成 `vipSite=0` 再被裸值兜底覆盖成 1，
 * 边界就说不清了。疑问前缀是**有限、可枚举**的一小撮，剥它没有歧义。
 */
function resolveLabelField(label) {
  const key = normLabel(label);
  if (LABEL_FIELDS.has(key)) return LABEL_FIELDS.get(key);
  let k = key;
  for (;;) {
    // 顺序有意义：先剥长的（是不是），再剥短的（是否 / 为 / 是）
    const next = k.replace(/^(是不是|是否|为|是)/, '');
    if (next === k) break;
    k = next;
    if (LABEL_FIELDS.has(k)) return LABEL_FIELDS.get(k);
  }
  return null;
}

/**
 * 从「标签：值」里抽一个字段的取值，并按字段语义归一。
 *
 * @returns {string} 归一后的取值；认不出返回 ''（**不是** null —— 空串即「没给」）
 */
function normalizeAttrValue(field, raw) {
  const v = String(raw || '').trim().replace(/^["'“”]+|["'“”]+$/g, '');
  if (!v) return '';
  switch (field) {
    case 'hubSite':
    case 'vipSite': {
      const k = v.toLowerCase();
      if (['yes', 'y', 'true', '1', '是', '有'].includes(k)) return '1';
      if (['no', 'n', 'false', '0', '否', '无'].includes(k)) return '0';
      return '';
    }
    case 'downSiteCount':
    case 'downstreamSites': {
      const m = v.match(/-?\d+/);
      return m ? String(parseInt(m[0], 10)) : '';
    }
    case 'siteSubType':
    case 'assetType': {
      const k = v.toUpperCase();
      // 两个字段取值域不重叠（REGULAR/ERA vs NORMAL/COOL）——
      // 标签说是「站点类型」但值是 NORMAL/COOL 时，应归 assetType（见调用方）。
      if (k === 'REGULAR' || k === 'ERA') return k;
      if (k === 'NORMAL' || k === 'COOL') return k;
      return '';
    }
    default:
      return v;
  }
}

/**
 * 扫一遍「标签：值」形式的成对字段。
 *
 * @param {string} s 提问原文
 * @returns {object} 字段名 → 取值
 */
function parseLabeledAttrs(s) {
  const out = {};
  for (const m of attrPairs(s)) {
    const field = resolveLabelField(m.label);
    if (!field) continue;
    const val = normalizeAttrValue(field, m.value);
    if (!val) continue;
    // 「站点类型」这类标签下，值域决定它到底是哪个字段：
    //   REGULAR/ERA → siteSubType；NORMAL/COOL → assetType。
    if (field === 'siteSubType' && (val === 'NORMAL' || val === 'COOL')) {
      out.assetType = val;
      continue;
    }
    if (field === 'assetType' && (val === 'REGULAR' || val === 'ERA')) {
      out.siteSubType = val;
      continue;
    }
    // 先出现的先算（同名字段重复出现时以第一处为准，避免被后半句覆盖）
    if (!(field in out)) out[field] = val;
  }
  return out;
}

/**
 * 找出所有「标签：值」成对出现的地方。
 *
 * @param {string} s 提问原文
 * @returns {Array<{label:string, value:string}>}
 */
function attrPairs(s) {
  const out = [];
  // 标签：中文/英文词 + 可选空格；取值：到下一个分隔符为止。
  const re = /([A-Za-z一-鿿][A-Za-z0-9一-鿿\s_\-]{0,30}?)\s*[:：=＝]\s*([^;；,，。\n\r]{1,40})/g;
  let m;
  while ((m = re.exec(String(s || ''))) !== null) {
    out.push({ label: m[1], value: m[2] });
  }
  return out;
}

/**
 * 把**已知的 eFlow 字段标签**从提问里剥掉（连同它的取值）。
 *
 * ## 为什么需要（2026-11-10 实测）
 *
 * 值班员提问时会直接把 eFlow 告警列表的**列名**贴过来：
 *   「…；Downstream Site Count：7，alarm code:9995. which kind of TT will be creadted?」
 *
 * 而统计意图的正则里有 `count` 这个词 —— "Downstream Site Count" **本身含 Count**，
 * 于是这条问题被当成「在问数量」，统计通道把查表通道整条抢走，
 * 最后落到模型层自由发挥（2026-11-10 实测：机器人答成「级别无法判定，缺 hubSite…」）。
 *
 * 列名是**用户粘贴的上下文**，不是问题的一部分。所以判意图前先把它剥掉，
 * 剩下的才是用户真正在问什么。
 *
 * 只剥**已知**标签 —— 未知标签原样保留，免得把真问题也削掉
 * （例如 "alarm code:9995" 的 "alarm code" 不在表里，会保留）。
 */
export function stripKnownAttrLabels(s) {
  const text = String(s || '');
  const re = /([A-Za-z一-鿿][A-Za-z0-9一-鿿\s_\-]{0,30}?)\s*[:：=＝]\s*([^;；,，。\n\r]{1,40})/g;
  return text.replace(re, (m, label) => (resolveLabelField(label) ? ' ' : m));
}

/**
 * 从提问里抽站点属性。
 *
 * 两层：
 *  ① **标签式**（"Hub Site Flag：YES"）—— 值班员从 eFlow 界面照抄列名时用；
 *     2026-11-10 新增。这一层优先。
 *  ② **裸值式**（"NORMAL 非 VIP"）—— 旧行为，保持不变。
 *     只在①**没抽到**该字段时才生效，避免两者打架
 *     （例："Site VIP Level：NO" 里含 "VIP"，裸值式会误判成 1）。
 *
 * 抽不到就是**不设该键**（不过滤、不参与匹配）—— 与旧语义一致。
 *
 * @returns {{assetType?:string, siteSubType?:string, vipSite?:'0'|'1',
 *            hubSite?:'0'|'1', downSiteCount?:string, downstreamSites?:string,
 *            netWorkType?:string, alarmDescription?:string}}
 */
export function parseSiteAttrs(q) {
  const s = String(q || '');
  const out = {};

  // ① 标签式（优先）
  Object.assign(out, parseLabeledAttrs(s));

  // ② 裸值式（仅补①没抽到的字段）
  // 资产类型
  if (!out.assetType) {
    if (/\bNORMAL\b/i.test(s)) out.assetType = 'NORMAL';
    else if (/\bCOOL\b/i.test(s)) out.assetType = 'COOL';
  }
  // 站点子类型
  if (!out.siteSubType) {
    if (/\bERA\b/i.test(s)) out.siteSubType = 'ERA';
    else if (/\bREGULAR\b/i.test(s)) out.siteSubType = 'REGULAR';
  }
  // VIP：显式说「非 VIP / VIP=0 / 不是VIP」→ 0；「VIP / VIP=1 / 是VIP」→ 1
  if (out.vipSite === undefined) {
    if (/(非\s*VIP|不是\s*VIP|vip\s*[:=]\s*0|vipSite\s*[:=]\s*0)/i.test(s)) out.vipSite = '0';
    else if (/(\bVIP\b|vip\s*[:=]\s*1|vipSite\s*[:=]\s*1)/i.test(s)) out.vipSite = '1';
  }
  return out;
}

/**
 * 按站点属性**过滤**候选级别规则：只丢掉「条件里明确写了冲突取值」的行。
 * 条件没提该属性的规则一律保留（吃不准就不排除）。
 */
export function filterLevelRulesByAttrs(rules, attrs = {}) {
  const has = Object.keys(attrs).length > 0;
  if (!has) return rules;
  return rules.filter((r) => {
    const w = String(r.when || '');
    if (attrs.assetType && /assetType\s*=/.test(w) && !new RegExp(`assetType\\s*=\\s*${attrs.assetType}\\b`).test(w)) {
      return false; // 条件写了别的 assetType → 冲突，排除
    }
    if (attrs.siteSubType && /siteSubType\s*=/.test(w) && !new RegExp(`siteSubType\\s*=\\s*${attrs.siteSubType}\\b`).test(w)) {
      return false;
    }
    if (attrs.vipSite && /vipSite\s*=\s*'?1'?/.test(w) && attrs.vipSite === '0') return false;
    if (attrs.vipSite === '1' && /vipSite\s*=\s*'?0'?/.test(w)) return false;
    return true;
  });
}

/* -------------------------------- 渲染 -------------------------------- */
// 渲染是**纯函数**：输出带出处文件名、不含 Markdown 标题 `#`、数据字段不翻译。

const SRC = (rel) => rel.split('/').pop();

function fmtTicketCount(n) {
  return n != null ? `，累计 TT 单 ${n}` : '';
}

/** 告警码含义。 */
export function renderAlarmCode(data, lang) {
  const name = data.hasName ? data.name : '';
  if (lang === 'en') {
    const head = name
      ? `Alarm code ${data.code} → ${name}`
      : `Alarm code ${data.code} is in the code table but has no description recorded.`;
    return `${head}${data.totalTickets != null ? ` (${data.totalTickets} TTs so far)` : ''}\nSource: ${SRC(data.source)}`;
  }
  const head = name ? `告警码 ${data.code} → ${name}` : `告警码 ${data.code} 在码表里，但没有记录含义描述。`;
  return `${head}${fmtTicketCount(data.totalTickets)}\n来源：${SRC(data.source)}`;
}

/** 压缩结果（子码 → 父码）。 */
export function renderCompress(rows, code, lang) {
  const enabled = rows.filter((r) => r.status === 'ENABLED');
  const disabled = rows.filter((r) => r.status !== 'ENABLED');

  const line = (r) =>
    lang === 'en'
      ? `Alarm code ${code} → parent alarm ${r.parentCode}${r.parentName ? ` (${r.parentName})` : ''}\nRule: ${r.ruleId} (${r.status})\nSource: ${SRC(r.source)}`
      : `告警码 ${code} → 压缩父告警 ${r.parentCode}${r.parentName ? `（${r.parentName}）` : ''}\n规则：${r.ruleId}（${r.status}）\n来源：${SRC(r.source)}`;

  const parts = enabled.map(line);
  // 停用规则必须标注，且排在最后 —— 不能让它看起来是当前的启用结论
  for (const r of disabled) {
    parts.push(
      lang === 'en'
        ? `${line(r)}\nNote: this rule is DISABLED — not the active compression.`
        : `${line(r)}\n注：该规则状态为 DISABLED（已停用），不是当前生效的压缩规则。`
    );
  }
  return parts.join('\n\n');
}

/** 级别规则候选列表。 */
export function renderLevelRules(rules, lang, { severity = '', code = '', siteAttrs = '' } = {}) {
  const head =
    lang === 'en'
      ? `Matching severity rule(s)${code ? ` for alarm code ${code}` : ''}${severity ? ` (${severity})` : ''}:`
      : `符合条件${code ? `（告警码 ${code}）` : ''}${severity ? `（${severity}）` : ''}的级别规则：`;
  const lines = rules.map(
    (r) =>
      lang === 'en'
        ? `- #${r.id} ${r.name} → ${r.severity}（priority ${r.priority}）\n  condition: ${r.when}`
        : `- #${r.id} ${r.name} → ${r.severity}（优先级 ${r.priority}）\n  条件：${r.when}`
  );
  const tail =
    lang === 'en'
      ? `Source: ${SRC(rules[0]?.source || '')}` +
        '\n(Not a full rule-engine match — to confirm a specific ticket, analyze its TT number.)'
      : `来源：${SRC(rules[0]?.source || '')}` +
        '\n（未做完整规则引擎匹配，要核实具体单请用分析 TT 单号。）';
  return [head, ...lines, tail].join('\n');
}

/** 未收录的固定文案（不经模型）。 */
export function renderNotFound(kind, code, lang) {
  if (lang === 'en') {
    const what = kind === 'compress' ? 'compression rule table' : 'alarm code table';
    return `The knowledge base ${what} does not contain ${code}. I won't guess from general knowledge.`;
  }
  const what = kind === 'compress' ? '告警压缩规则表' : '告警码表';
  return `知识库${what}里没有 ${code}。我不会按通用知识猜。`;
}
