/**
 * 工具路由 —— 让模型先决定「查什么」，再决定「怎么答」。
 *
 * ## 解决的是什么问题
 *
 * 「今天有 P1 的单子吗」原本会被整句塞进知识库向量检索。检索器确实找到了
 * P1 规则（ID 225/226），模型也诚实地说「资料里没有实际工单数据」——
 * 但那不是用户要的答案。用户问的是**事实**，不是**规则**。
 * 这类问题的答案在数据里，不在语料里，塞进 RAG 必然答错。
 *
 * 所以要先把问题分流：是「查数据」还是「查资料」。
 *
 * ## 两条腿走路：规则先行，模型兜后
 *
 *   ① **规则层**（本模块 parseByRule）：日期、级别、单号这类参数，
 *      用正则从原文里直接抽。理由见 ttquery.js 的 parseDateRange ——
 *      模型不知道今天几号。规则命中就**不花那次模型调用**，
 *      顺带省掉一次往返延迟（群里对延迟很敏感）。
 *   ② **模型层**（本模块 routeByModel）：规则没命中时，把工具清单交给模型，
 *      让它返回 `{tool, args}` JSON。
 *
 * 规则层不是过渡方案：群里高频问题就那么几种句式，规则能吃掉绝大多数，
 * 剩下长尾交给模型。反过来全交给模型，等于每条提问都多花一次调用去
 * 解一个正则能解的题。
 *
 * ## 模型只选工具，不碰数字
 *
 * 工具的返回值由脚本渲染（见 ttquery.js 的 renderStats），
 * 模型不会看到 COUNT(*) 的结果再去"润色"——那一步是编造的温床。
 * 唯一的例外是 search_knowledge：那里模型必须读资料才能答，
 * 但那条通道有 systemPrompt 的「只依据资料、不得编造」约束守着。
 */
import { CONFIG } from './config.js';
import { chat } from './llm.js';
import { answer as ragAnswer, withWebHint } from './rag.js';
import { extractTtNos, analyzeTickets, lookupLevelByRule } from './tt.js';
import { querySiteAlarms } from './sitealarms.js';
import {
  queryTickets,
  renderStats,
  parseDateRange,
  parseSeverity,
  parseStatus,
  parseListIntent,
} from './ttquery.js';
import {
  loadLookups,
  findAlarmCode,
  findCompress,
  findLevelByCode,
  findLevelBySeverity,
  resolveCodeByName,
  parseSiteAttrs,
  filterLevelRulesByAttrs,
  renderAlarmCode,
  renderCompress,
  renderLevelRules,
  renderNotFound,
} from './lookups.js';

/* ------------------------------ 查找表（查表工具） ------------------------------ */

// 启动时读一次（与 loadIndex 同一节拍）。缺失时查表工具如实回「未构建」，
// **不 fallback 进 RAG 装懂** —— 那是这次改造要消灭的行为。
let LOOKUPS = null;
let LOOKUPS_LOADED = false;
export function loadLookupsOnce(path = CONFIG.lookupsPathAbs) {
  if (!LOOKUPS_LOADED) {
    LOOKUPS = loadLookups(path);
    LOOKUPS_LOADED = true;
  }
  return LOOKUPS;
}
/** 供测试注入假查找表。 */
export function __setLookups(l) {
  LOOKUPS = l;
  LOOKUPS_LOADED = true;
}

/* ------------------------------- 工具清单 ------------------------------- */

/**
 * 喂给模型的工具描述。
 *
 * 刻意只列**当前真能用**的工具 —— 写进去一个没有实现的 query_alarms，
 * 模型会真的去调它，然后得到一个"工具不存在"的失败，比没有这个工具更糟。
 */
const TOOL_SPEC = [
  {
    name: 'query_tickets',
    desc:
      '按条件统计工单数量。用于「今天有几个 P1」「昨天未闭环多少单」这类' +
      '**区间统计**问题。参数是日期范围、级别、闭环状态、站点名（都可选）。',
    args: '{"start":"YYYY-MM-DD 或 空","end":"YYYY-MM-DD 或 空","severity":"P1~P4 或 空","status":"open|closed|all","site":"站点名 或 空"}',
  },  {
    name: 'analyze_ticket',
    desc: '查询**单个**工单的详情与级别判定依据。仅当提问里明确出现了 TT/WO 单号时使用。',
    args: '{"tt_no":"TT202609150073"}',
  },
  {
    name: 'query_site_alarms',
    desc:
      '按**站点名**查 eFlow 的**实时活动告警**，回答「这个站现在有没有告警 / up 没 up / 是什么告警」。' +
      '用于「*Palm Bay* check if this site is up or not」「check alarm for site name X form eflow」' +
      '「XX站有告警吗」「XX站是不是 down 了」。参数是站点名。' +
      '**不要**用 query_tickets 答这类问题 —— 那是工单数量，不是告警状态。',
    args: '{"site":"Palm Bay"}',
  },
  {
    name: 'lookup_alarm_code',
    desc:
      '查**告警码的含义**。用于「告警码 99933 是什么意思」「what does alarm code 9920 mean」。' +
      '参数是告警码数字。**不要**用 search_knowledge 答这类问题。',
    args: '{"code":"99933"}',
  },
  {
    name: 'lookup_compress',
    desc:
      '查**告警压缩结果**（子告警码会被压缩成哪个父告警码）。用于' +
      '「198094422 会被压缩成什么」「压缩后的父告警是什么」。参数是子告警码。',
    args: '{"code":"198094422"}',
  },
  {
    name: 'lookup_level_rule',
    desc:
      '查**TT 级别规则**。用于「告警码 9990 NORMAL 非 VIP 是几级」「P1 规则有哪些」' +
      '「P1 是什么级别」。参数：有告警码给 code；只问某级别给 severity（P1~P4）。',
    args: '{"code":"9990","severity":"P1"}',
  },
  {
    name: 'search_knowledge',
    desc:
      '检索知识库文档。用于「流程怎么走」「为什么没有级别」这类**叙述性静态知识**问题，' +
      '以及所有不含工单统计、不含告警码/压缩/级别查表意图的问题。',
    args: '{}',
  },
];

/** 把工具清单渲染成 prompt 里的一段。 */
function renderToolSpec() {
  return TOOL_SPEC.map(
    (t, i) => `${i + 1}) ${t.name}\n   用途：${t.desc}\n   参数：${t.args}`
  ).join('\n');
}

const ROUTER_PROMPT =
  '你是群聊助手的**路由员**：只决定该用哪个工具，不回答问题本身。\n' +
  '下面是可用工具：\n' +
  renderToolSpec() +
  '\n\n规则：\n' +
  '· 提问里出现 TT/WO 单号 → 用 analyze_ticket。\n' +
  '· 问的是「多少单 / 有几个 / 有没有 / 今天昨天的单」这类**数量与事实** → 用 query_tickets。\n' +
  '· 出现告警码，且问**含义**（是什么意思/what does … mean）→ 用 lookup_alarm_code。\n' +
  '· 出现告警码，且问**压缩 / 父告警 / 会被压成什么** → 用 lookup_compress。\n' +
  '· 出现告警码，且问**级别 / 定级 / 几级**；或只问「P1 是什么级别」「P1 规则」→ 用 lookup_level_rule。\n' +
  '· 有告警码且问含义/压缩/级别时，**一律不要**用 search_knowledge —— 那是查表题，不是叙述题。\n' +
  '· 问某个**站点当前有没有告警 / 是不是 up / 什么告警 / down 没 down** → 用 query_site_alarms；' +
  '把站点名填进 site。**这类问题绝不要用 query_tickets** —— query_tickets 是工单数量，' +
  '按站名匹配工单会得到 0，而 0 张工单**不等于**没有告警，那会答错。\n' +
  '· 其余「流程 / 为什么 / 怎么走 / 定义」这类**叙述性静态知识** → 用 search_knowledge。\n' +
  '· 注意区分：「P1 是什么」= lookup_level_rule；「今天有几个 P1」= query_tickets。\n' +
  '· 拿不准且**没有**告警码 → 用 search_knowledge。\n' +
  '· 提问里若点名了**具体站点**（如「Wood camp 这个站」「Qcell R.I.A 有几个单」），' +
  '把站点名原样填进 site；没点名就留空字符串。\n' +
  '· 若提问**本身没说清问什么**（如「那个单子未闭环」「还有几个」），' +
  '参考【最近对话】把上一轮的日期/级别/站点**照抄**进来 —— ' +
  '这种追问单看是缺主语的，猜错就会答成另一个问题。\n' +
  '\n只输出一行 JSON，不要解释：\n' +
  '{"tool":"<工具名>","args":{...}}';

/**
 * 构造路由 prompt，并**注入今天、已解析出的日期、最近对话**。
 *
 * 为什么非注入不可：模型没有时钟，问它「今天是几号」只能得到瞎猜。
 * 2026-10-07 实测「Wood camp 这个站**昨天**有几个单」——
 * 规则层因站名弃权后，日期就断了线，最终查成了**今天**，
 * 返回 0 单，看起来像「这个站昨天没事」，实际是查错了日子。
 *
 * 注入后模型能照抄日期；即便它还是抽错，
 * `normalizeArgs` 里「规则解析 > 模型给的 > 今天」的优先级也会兜住。
 *
 * 【最近对话】解决的是另一类问题：**追问缺主语**。
 * 实测「那个单子未闭环」被答成了「今天全网 36 单」——
 * 单看这句话确实没有日期也没有级别，但上一轮刚问过「本月 P1」。
 */
function buildRouterPrompt(question, now, history = []) {
  const today = parseDateRange('今天', now);
  const fromQ = parseDateRange(question, now);
  const lines = [
    ROUTER_PROMPT,
    '',
    '【上下文】',
    `今天 = ${today.start}`,
  ];
  if (fromQ) {
    lines.push(
      fromQ.start === fromQ.end
        ? `提问中的日期已确定 = ${fromQ.start}（直接照抄进 start 与 end）`
        : `提问中的日期范围已确定 = ${fromQ.start} ~ ${fromQ.end}（直接照抄进 start 与 end）`
    );
  } else {
    lines.push('提问中没有明确日期 → 优先从【最近对话】里找；找不到再留空字符串。');
  }
  const recent = (history || []).slice(-3);
  if (recent.length) {
    lines.push('', '【最近对话】（时间正序，最新一条在最后）');
    for (const h of recent) {
      lines.push(`问：${String(h.q || '').slice(0, 150)}`);
      // 回答只取前几行：单号名单很长，全塞进 prompt 反而稀释重点
      lines.push(`答：${String(h.a || '').slice(0, 200)}`);
    }
  }
  return lines.join('\n');
}

/* ------------------------------- 规则层 ------------------------------- */

/**
 * 统计意图的触发词。
 *
 * 收得**窄**是刻意的：宁可漏判走模型层，也不要把「P1 是什么级别」误判成查数。
 * 所以「P1」单独出现不算，必须搭配数量词或时间词才成立。
 *
 * 2026-10-14 实测踩到：`how many TT creat today?` 因 `creat` 拼写不在这里、
 * 模型把它从 `/today/i` 上带过去（"今天"在英文语料里也常"今天"成 today）才生效
 * — 但模型要花 13s 才给出结果，规则层本应 60ms 内 命中。`\bcreat[a-z]*\b` 把
 * 「creat / created / creating / creation」一并兜住，**只用作统计触发词**，
 * 文本上仍是一个「create 的近似动词」。下限 4 字符防止 `cre` / `crea` 等
 * 裸字过宽。
 *
 * 注意后缀类用 `[a-z]*` **而不是** `\w*`：`\w` 含 `_`，`created_by` 仍会
 * 被命中→误伤；限定字母是「单词内部的继续延伸」更安全。
 */
const COUNT_INTENT =
  /(多少|几个|几单|几条|有多少|有没有|有吗|有没|数量|总计|合计|count|how\s+many|how\s+much|any\s|P\d.*\?|\btoday\b|\byesterday\b|\bcreat[a-z]*\b)/i;

/**
 * 纯知识问法的特征词 —— 命中则**不**走统计通道。
 *
 * 这是 COUNT_INTENT 的反向护栏：「P1 是什么级别」里既有 P1 又有「什么」，
 * 只看 COUNT_INTENT 会被误判为查数。
 */
const KNOWLEDGE_INTENT =
  /(是什么|什么意思|啥意思|怎么判定|如何判定|怎么定|规则|定义|含义|标准|依据|流程|怎么走|如何计算|区别|为什么|what\s+is|how\s+is|define|meaning|rule|criteria|why)/i;

/**
 * 站点/额外条件信号 —— 命中则**放弃规则层短路**，转交模型层抽参数。
 *
 * 这条护栏是 2026-10-07 实测踩出来的：问「Wood camp 这个站昨天有几个单」，
 * 规则层被「有几个」触发、直接带着 `site:''` 出了结果，
 * 模型层根本没机会看到这句话 —— 于是答案给成了**全网 94 单**，
 * 而用户问的是那一个站。**答错而不报错**，是最危险的一类。
 *
 * ## 判据为什么是「残余专名」而不是「站」字
 *
 * 最初只匹配「站 / site」这类词，但实测漏掉了「Qcell R.I.A 有几个 P1」——
 * 裸站名里根本没有「站」字。反过来，把「出现英文字母」当信号又会误伤
 * 「how many P1 tickets today」。
 *
 * 所以判据改成：**把规则层认得的部分全部抹掉，看还剩不剩下解释不了的专名**。
 *   · 「Wood camp 这个站昨天有几个单」→ 残余 Wood camp → 弃权 ✓
 *   · 「Qcell R.I.A 有几个 P1」     → 残余 Qcell R.I.A → 弃权 ✓
 *   · 「昨天一共有多少单」           → 残余为空 → 照常短路 ✓
 *   · 「how many P1 tickets today」  → 残余只剩停用词 tickets → 照常短路 ✓
 *
 * 这个判据统一、可解释，且天然覆盖站名、域、人名等一切"规则不认识的额外条件"。
 * 代价是碰到没进停用词表的新英文词会多花一次模型调用 —— 那是**安全方向**的
 * 代价：多问一次模型，好过默默答错。
 */
const STOP_WORDS = new Set([
  'how', 'many', 'much', 'is', 'are', 'the', 'a', 'an', 'of', 'in', 'on', 'for',
  'and', 'or', 'to', 'do', 'does', 'did', 'have', 'has', 'any', 'there', 'be',
  'ticket', 'tickets', 'tt', 'wo', 'order', 'orders', 'count', 'number', 'total',
  'today', 'yesterday', 'open', 'closed', 'pending', 'p1', 'p2', 'p3', 'p4',
  'severity', 'priority', 'please', 'show', 'me', 'list', 'get', 'check', 'status',
  // 英文时间/限定词：这些是**规则层已认得**的日期信号，不能当残余专名，
  // 否则「how many P1 Tickets for this month」会被判成带额外条件 → 规则层弃权。
  // 2026-10-08 实测：该问法走了模型层 2.9s（正确结果是规则层 60ms）。
  'this', 'that', 'these', 'those', 'for', 'from', 'since', 'last', 'next',
  'current', 'previous', 'month', 'months', 'week', 'weeks', 'day', 'days',
  'year', 'years', 'past', 'recent', 'all', 'total', 'sum', 'during', 'between',
  'of', 'the', 'new', 'were', 'was', 'been', 'raised',
  // create 的近似词：2026-10-14 实测「how many TT creat today?」触发模型层 13s
  // —— `creat` 不在 COUNT_INTENT、也不在 STOP_WORDS，残余里被算成"陌生专名"，
  // 规则层弃权。这里把整族（creat / created / creating / creation）加进来，
  // 让残余识别不再误吃。注意：`creator` / `creators` 不在 STOP_WORDS，
  // 留着不影响（"this site creator"基本不出现于统计问句中）。
  'creat', 'created', 'creating', 'creation',
  // 「要名单」的英文动词：已被 parseListIntent 处理，不能当残余专名。
  'give', 'gimme', 'send', 'sends', 'sent', 'showing', 'provide', 'want',
  'wanna', 'need', 'like', 'help', 'enumerate', 'ids', 'id',
]);

/**
 * 剥掉规则层已经认得的东西，返回剩余的"解释不了的片段"。
 *
 * @param {string} q 原始提问
 * @returns {string[]} 残余片段
 */
export function leftoverTerms(q) {
  let s = String(q || '');
  // 「这个站 / 哪个站 / 站点」这类**中文站点指代**本身就是「有额外条件」的信号：
  // 提问锁定了某个站（哪怕是"这个/那个"），规则层不该带空站点答全网。
  // 单字「站」抹词后会剩下来，长度 <2 会被过滤 —— 所以先在这里记一笔。
  const siteSignal = SITE_WORD.test(s);

  // 单号（已由 analyze_ticket 处理）
  s = s.replace(/\b(?:TT|WO)\d{6,}\b/gi, ' ');
  // 显式日期：2026-10-06 / 2026/10/6 / 2026年10月6日
  s = s.replace(/20\d{2}\s*[-\/年.]\s*\d{1,2}\s*[-\/月.]\s*\d{1,2}\s*日?/g, ' ');
  // 级别
  s = s.replace(/\bP\s*[1-4]\b/gi, ' ');
  // 数字（「近7天」「3个」）
  s = s.replace(/\d+/g, ' ');
  // 中文时间与数量词
  s = s.replace(
    /(今天|今日|昨天|昨日|前天|本周|这周|上周|本月|这个月|上个月|最近|过去|近|多少|几个|几单|几条|有没有|有吗|有没|有|数量|总计|合计|一共|个|单|条|天|周|月|年|日|的|了|吗|呢|啊|吧|请|帮|我|看|查|下|一下|这个|那个|哪些|什么)/g,
    ' '
  );
  // 「要单号名单」的说法（parseListIntent 认得的那批）也必须剥掉，
  // 否则残余的 "ID" / "TT" 会被当成解释不了的专名，
  // 导致规则层白白弃权、多花一次模型调用。
  // 实测：「本月有几个P1的单子，请输出TT单的ID给我」曾因此落到模型层。
  s = s.replace(/单号|编号|明细|清单|列出|列一下|有哪些|哪几单|哪些单|输出|给我|TT(?![0-9])|ID/gi, ' ');
  // 闭环状态词（parseStatus 认得的那批）也必须剥掉 ——
  // 否则「昨天有多少 P2 未闭环」会残余出「未闭环」，规则层白白弃权。
  s = s.replace(/(未闭环|已闭环|未关闭|已关闭|未关闭中|闭环|打开|关闭)/g, ' ');

  const terms = s
    .split(/[^A-Za-z0-9\u4e00-\u9fa5]+/)
    .map((t) => t.trim())
    .filter(Boolean);

  const out = [];
  for (const t of terms) {
    const low = t.toLowerCase();
    // 纯中文残余：抹掉已知的时间/数量/动词后仍剩下的中文片段（长度≥2），
    // 视为**解释不了的专名**（站名/区域名/人名）→ 规则层弃权交模型层。
    //
    // 旧实现是「纯中文只保留匹配 SITE_WORD 的」，于是「蒙塞拉多昨天有几单」
    // 里的「蒙塞拉多」被扔掉 → 带 site:'' 答成全网。中文站名恰恰不带「站」字。
    if (/^[\u4e00-\u9fa5]+$/.test(t)) {
      if (t.length >= 2) out.push(t);
      continue;
    }
    if (STOP_WORDS.has(low)) continue;
    if (low.length < 2) continue;
    out.push(t);
  }
  // 中文站点指代（"这个站"）单独补一条：它可能被抹词后只剩单字「站」，
  // 长度不足 2 被过滤，但语义上就是「有额外条件」。
  if (siteSignal && !out.length) out.push('站');
  return out;
}

/** 「站」类词：中文语境下站点存在与否的直接信号。 */
const SITE_WORD = /(站点?|基站|站名|这个站|那个站|某站|哪个站)/;

/* --------------------------- 查表意图（P0 最大杠杆） --------------------------- */

/** 含义类问法 → lookup_alarm_code。 */
const MEANING_INTENT = /(是什么|什么意思|啥意思|含义|什么意思|代表什么|what\s+is|what\s+does|mean|meaning|字典)/i;
/** 压缩类问法 → lookup_compress。 */
const COMPRESS_INTENT = /(压缩|压缩成|父告警|父码|compress|parent|会被压)/i;
/** 级别类问法 → lookup_level_rule。 */
const LEVEL_INTENT = /(级[别位]|定级|几级|什么级别|怎么判定|如何判定|severity|priority|P\s*[1-4]\s*(级别|是什么|怎么|规则)?|P\s*[1-4]\s*规则)/i;

/** 从提问里抽告警码：≥3 位数字（够长才算码；短码只在「告警码」上下文里认）。 */
function extractAlarmCode(q) {
  // 「告警码 9990」/「alarm code 9920」这类显式上下文里，3 位也可以
  const explicit = String(q).match(/(?:告警码|告警|alarm\s*code|alarm)\s*[:：]?\s*(\d{3,})/i);
  if (explicit) return explicit[1];
  // 否则要 ≥4 位，避免把「P1」「3G」「2G」这类短数字误当码
  const long = String(q).match(/\b(\d{4,})\b/);
  return long ? long[1] : '';
}

/**
 * 查表意图识别：返回 lookup 工具调用，或 null。
 * 只在**同时有告警码或明确级别**时触发，避免把叙述题误当查表。
 */
export function parseLookupIntent(q, lookups) {
  // 未显式传入时按需加载（进程启动已 load 过；测试注入假表时走参数）。
  if (lookups === undefined) lookups = LOOKUPS ?? loadLookupsOnce();
  const code = extractAlarmCode(q);

  // 有告警码：按问法细分
  if (code) {
    if (COMPRESS_INTENT.test(q)) return { tool: 'lookup_compress', args: { code } };
    if (LEVEL_INTENT.test(q)) return { tool: 'lookup_level_rule', args: { code } };
    if (MEANING_INTENT.test(q)) return { tool: 'lookup_alarm_code', args: { code } };
    // 有码但没明确问法：默认当「含义」（最常见的「这个码是什么」意图）
    return { tool: 'lookup_alarm_code', args: { code } };
  }

  // 无数字码，但问句里出现**已知告警名/缩写**（CSD、MW LINK DOWN…）→ 解析成码再查。
  // 手册 §3.3 的场景：「CSD 定几级」没有长数字，向量会召回错行；这里改走查表。
  // 仅在**有级别/含义/压缩意图**时才生效，避免把普通叙述题误当查表。
  const wantsLookup = LEVEL_INTENT.test(q) || MEANING_INTENT.test(q) || COMPRESS_INTENT.test(q);
  if (wantsLookup) {
    const byName = resolveCodeByName(lookups, q);
    if (byName) {
      if (COMPRESS_INTENT.test(q)) return { tool: 'lookup_compress', args: { code: byName } };
      if (LEVEL_INTENT.test(q)) return { tool: 'lookup_level_rule', args: { code: byName } };
      return { tool: 'lookup_alarm_code', args: { code: byName } };
    }
  }

  // 无码但**明确问规则/级别定义** → 级别规则列表。
  // 判据必须锚在「级别」或「规则」这类词上，**不能只靠出现 P1** ——
  // 「今天有p1的单子吗」里也有 P1，但那走统计（COUNT_INTENT 会拦）。
  // 同义问法：「P1 怎么算」「P1 怎么定」「P1 怎么定级」「这条 P1 怎么定的」——
  // 问的是 P 级别的判定依据，与「P1 是什么」等价。正则只列「规则|是什么|怎么判」会漏，
  // 2026-10-08 深度测试发现「P1 怎么算的」被规则层弃权、交给模型层后由 LLM 自由发挥，
  // 出现幻觉数字的概率比走查表高一个量级。
  const asksLevelDef = /(级别|定级|几级|severity|priority)/i.test(q) ||
    /P\s*[1-4][^A-Za-z]{0,8}(规则|是什么|怎么判|怎么算|怎么定|如何判|如何算|如何定)/i.test(q);
  const sev = parseSeverity(q);
  if (sev && asksLevelDef && !COUNT_INTENT.test(q)) {
    return { tool: 'lookup_level_rule', args: { severity: sev } };
  }

  return null;
}

/**
 * 规则层路由：能确定就返回工具调用，确定不了返回 null（交给模型层）。
 *
 * @returns {{tool:string, args:object}|null}
 */
/* --------------------- 站点告警意图（query_site_alarms） --------------------- */

/**
 * 「某站点当前有没有告警」的问法特征。
 *
 * 收得**窄且锚在告警语义上**是刻意的：
 *   · 必须出现告警状态词（告警 / alarm / up / down / 掉站 / 断站 / site down…），
 *     光有站名不算 —— 否则「Wood camp 昨天有几单」会被误拐到告警通道。
 *   · 出现 TT/WO 单号时**不**走这里（那是 analyze_ticket 的地盘），
 *     但「站点有没有告警 and 有没有 TT」这种**混合问法**要能进 —— 见下。
 */
const SITE_ALARM_INTENT =
  /(告警|报警|alarm|是否\s*(up|down|在线|正常)|在不在线)\s*|\bis\s+it\s+up\b|\b(site\s*)?(is\s*)?(down|up)\s*(or|and)?\s*(not)?\b|\bup\s*(or|\/)\s*not\b|掉站|断站/i;

/**
 * 从提问里抽站点名（规则层）。
 *
 * 只处理**规则能可靠抓到**的形态，抓不准就返回 '' 交给模型层：
 *   · 被 `*...*` 包裹的（用户惯用 *Palm Bay* 强调）—— 最可靠；
 *   · 「site name X」「site X」「站点 X」「X 站」这类显式引导词后的专名；
 *   · 纯英文多词专名（Palm Bay / Gbonebu Town）。
 * 中文裸站名（「蒙塞拉多」）规则不可靠 → 留给模型层，保持与统计通道一致的取舍。
 */
const SITE_STOPWORDS = new Set([
  'check', 'if', 'alarm', 'alarms', 'site', 'sitename', 'name', 'please', 'tt', 'wo',
  'up', 'down', 'have', 'has', 'is', 'the', 'for', 'form', 'from', 'and', 'or', 'not',
  'no', 'yes', 'created', 'create', 'why', 'what', 'which', 'any', 'there', 'this',
  'that', 'status', 'now', 'current', 'eflow', 'and', 'of', 'in', 'on', 'to',
]);

function extractSiteName(q) {
  const s = String(q || '');

  // ① *...* 强调包裹 —— 用户惯用 *Palm Bay* 点名，最可靠，优先。
  const star = s.match(/\*+\s*([^*]{2,40}?)\s*\*+/);
  if (star) {
    const name = star[1].trim();
    if (name && !SITE_STOPWORDS.has(name.toLowerCase())) return name;
  }

  // ② 纯英文专名：1~3 个连续「首字母大写」词，且首词不是停用词。
  //    只认**大写开头**的词，天然避开 "site down" 里的 down / "check alarm" 里的 alarm。
  //    例：Palm Bay / Gbonebu / Qcell R.I.A / Wood Camp。
  const capped = s.match(/\b[A-Z][A-Za-z0-9'\-]*(?:\s+[A-Z][A-Za-z0-9'\-]*){0,2}\b/g) || [];
  const cands = capped
    .map((w) => w.trim())
    .filter((w) => {
      const head = w.split(/\s+/)[0].toLowerCase();
      return !SITE_STOPWORDS.has(head) && w.replace(/[^A-Za-z0-9]/g, '').length >= 3;
    });
  // 仅当**恰好一个**候选时采用（多个说明歧义 → 弃权交模型层，宁可不猜）
  if (cands.length === 1) return cands[0];

  // ③ 中文站点：`XX站` / 「站点 XX」——仅当 XX 是 ≥2 个汉字时。
  const zh = s.match(/([一-龥]{2,10})\s*站(?:点)?/) || s.match(/站点?\s*([一-龥]{2,10})/);
  if (zh) return zh[1];

  return '';
}

export function parseByRule(question, now = new Date()) {
  const q = String(question || '').trim();

  // ① 单号优先：TT/WO 单号是强信号，且这条通道最成熟。
  const ttNos = extractTtNos(q);
  if (ttNos.length) return { tool: 'analyze_ticket', args: { tt_no: ttNos[0] } };

  // ①.2 站点告警意图：出现**告警状态词**（且不是纯按单号/告警码查）时，
  // 优先走 query_site_alarms。必须在统计判断之前 —— 否则
  // 「Palm Bay 有没有告警」会被 COUNT_INTENT 的「有没有」拐去统计，
  // 回一句 tickets: 0，把「工单数」误当「告警状态」。
  // 覆盖面：站名能被规则可靠抓到时**直接命中**（省一次模型调用）；
  // 抓不到站名时**弃权**交模型层（模型能从上下文/追问里补全站名）。
  if (SITE_ALARM_INTENT.test(q) && !extractAlarmCode(q)) {
    const site = extractSiteName(q);
    if (site) return { tool: 'query_site_alarms', args: { site } };
  }

  // ①.5 查表意图（告警码含义 / 压缩 / 级别）。
  //
  // 必须**先于**统计判断：`test-tools.mjs [3] q8` 明确要求
  // 「告警码 198094422 会被压缩成什么」不得被当成统计。
  // 但若问题里同时有**数量词**（「198094422 压缩后有几单」），那是统计意图 ——
  // 所以这里只在**没有数量词**时才认查表，交下面走统计。
  const hasCountWordEarly = COUNT_INTENT.test(q);
  if (!hasCountWordEarly) {
    const lk = parseLookupIntent(q);
    if (lk) return lk;
  }

  // ② 统计意图：必须有数量/时间信号，且不是纯知识问法。
  const date = parseDateRange(q, now);
  const sev = parseSeverity(q);
  const hasCountWord = COUNT_INTENT.test(q);
  const isKnowledge = KNOWLEDGE_INTENT.test(q);
  const isStats = (hasCountWord || date) && !isKnowledge;

  // ③ 有额外条件（站名等规则抽不准的专名）时弃权，交模型层。
  if (isStats && leftoverTerms(q).length) return null;

  if (isStats) {
    // 只有「P1 今天」没有数量词也算（「今天P1」＝问今天有没有 P1）
    if (hasCountWord || (date && sev) || date) {
      return {
        tool: 'query_tickets',
        args: {
          start: date?.start || '',
          end: date?.end || '',
          severity: sev || '',
          status: parseStatus(q),
          site: '',
          list: parseListIntent(q),
        },
      };
    }
  }

  return null;
}

/* ------------------------------- 模型层 ------------------------------- */

/**
 * 解析模型的一行 JSON。
 *
 * 宽容处理三种常见噪声：前后有多余文字、用中文引号、末尾带逗号。
 * 解析不出来返回 null —— 由上层退回知识库通道，**不重试**（多花一次调用
 * 换来的只是把同一个不确定的问题再问一遍）。
 *
 * 取对象策略：从右往左找「最后一个完整的 {...}」块。模型有时会先写
 * 一段思考文字（含示例 JSON）再正式答，例如
 *   `也许 {a:1}。最终 {\"tool\":\"query_tickets\",...}`
 * 老实现取第一个 `{` 到最后 `}` 会把中间杂物一起切下来，JSON.parse 失败
 * → null。改成"最后一个能 parse 通的 JSON"更稳。
 */
export function parseToolCall(content) {
  const s = String(content || '');
  if (!s) return null;
  // 找出所有可能的 JSON 块起点（右起扫描）
  let end = s.lastIndexOf('}');
  while (end > 0) {
    // 从 end 向左找匹配的 '{'：用括号配对最简版——不严格（不计字符串内 {），
    // 但工具调用行 JSON 极简，足够覆盖真实场景。
    let depth = 0;
    let start = -1;
    for (let i = end; i >= 0; i--) {
      const ch = s[i];
      if (ch === '}') depth++;
      else if (ch === '{') {
        depth--;
        if (depth === 0) { start = i; break; }
      }
    }
    if (start < 0) return null;
    const candidate = s.slice(start, end + 1);
    let obj;
    try {
      obj = JSON.parse(candidate);
    } catch {
      // 这段不合法，往左找更早的 '}'
      end = s.lastIndexOf('}', end - 1);
      continue;
    }
    const name = String(obj?.tool || '').trim();
    if (!TOOL_SPEC.some((t) => t.name === name)) return null;
    return { tool: name, args: obj?.args && typeof obj.args === 'object' ? obj.args : {} };
  }
  return null;
}

async function routeByModel(question, now, lang, history) {
  try {
    const { content } = await chat(
      [
        { role: 'system', content: buildRouterPrompt(question, now, history) },
        { role: 'user', content: String(question || '').slice(0, 500) },
      ],
      { maxTokens: 128, temperature: 0 }
    );
    return parseToolCall(content);
  } catch {
    return null;
  }
}

/* ------------------------------ 工具执行 ------------------------------ */

/**
 * 规范化模型吐出的参数。
 *
 * 模型最爱犯的三类错：
 *   · 日期写成 "today" / "今天"（它不知道今天几号，但会照着提问抄）；
 *   · **干脆不返回日期** —— 规则层因为"有站名"弃权了，日期却没跟着传下来，
 *     于是「Wood camp 这个站**昨天**有几个单」被兜底成**今天**，
 *     查出来的 0 单看起来像"这个站昨天没事"，实际是查错了日子。
 *     这是 2026-10-07 实测踩到的，**答错而不报错**，必须堵死；
 *   · 级别写成 "p1" 或 "P 1"。
 *
 * 所以这里的优先级是：
 *   **规则从原始提问解析 > 模型给的（含从历史抄来的）> 今天**。
 * 日期本该由规则层算（它才有本机时钟），模型只负责抽它抽得准的东西（站名）。
 *
 * @param {object} args     模型返回的参数
 * @param {Date}   now
 * @param {string} question 原始提问（用于重新解析日期）
 */
function normalizeArgs(args, now = new Date(), question = '') {
  const out = {};
  const raw = args || {};

  const isDate = (v) => /^20\d{2}-\d{2}-\d{2}$/.test(v);

  // ① 规则从**原始提问**解析日期 —— 这是最可靠的一手来源
  const fromQuestion = parseDateRange(question, now);

  // ② 模型给的日期（只接受真日期；"today"/"今天" 一律不认）
  const mStart = String(raw.start || '').trim();
  const mEnd = String(raw.end || '').trim();
  const fromModel =
    isDate(mStart) && isDate(mEnd)
      ? { start: mStart <= mEnd ? mStart : mEnd, end: mStart <= mEnd ? mEnd : mStart }
      : isDate(mStart)
        ? { start: mStart, end: mStart }
        : null;

  const range = fromQuestion || fromModel || parseDateRange('今天', now);
  out.start = range.start;
  out.end = range.end;
  // 日期是不是猜的（谁都没给，只好默认今天）。渲染层据此加一句口径说明 ——
  // 追问被兜底成"今天"时，用户看到的那句「2026-10-07」需要解释从哪来。
  out.dateGuessed = !fromQuestion && !fromModel;

  const sev = String(raw.severity || '').toUpperCase().replace(/\s/g, '');
  out.severity = /^P[1-4]$/.test(sev) ? sev : '';
  const st = String(raw.status || '').toLowerCase();
  out.status = st === 'open' || st === 'closed' ? st : 'all';
  out.site = String(raw.site || '').trim().slice(0, 40);
  // 要单号名单这件事**只从原始提问判断**，不看模型返回什么 ——
  // 模型容易漏掉「请输出TT单的ID给我」这种附加要求，
  // 而漏判的后果是用户要 ID 却只拿到一个数字。
  out.list = parseListIntent(question) || !!raw.list;
  return out;
}

/**
 * 执行一个工具调用。
 *
 * @param {{tool:string,args:object}} call
 * @param {object} index      知识库索引（search_knowledge 用）
 * @param {'zh'|'en'} lang
 * @param {object} [opts]     { onDebug, onRetry, onLive, now }
 * @returns {Promise<{text:string, answered:boolean, channel:string, stats?:object}>}
 */
export async function runTool(call, index, lang, opts = {}) {
  const t0 = Date.now();

  // 查表工具：脚本渲染，不经 LLM（P0 准确率最大杠杆）。
  if (call.tool === 'lookup_alarm_code' || call.tool === 'lookup_compress' || call.tool === 'lookup_level_rule') {
    const out = await runLookup(call, lang, opts);
    out.stats = { ...(out.stats || {}), totalMs: Date.now() - t0 };
    return out;
  }

  if (call.tool === 'analyze_ticket') {
    const no = String(call.args?.tt_no || '').toUpperCase();
    const r = await analyzeTickets(no || '', { lang, onRetry: opts.onRetry, onLive: opts.onLive });
    return {
      text: r.text,
      answered: r.ok,
      channel: 'tt',
      stats: { totalMs: Date.now() - t0, okCount: r.okCount, total: r.total },
    };
  }

  if (call.tool === 'query_site_alarms') {
    const site = String(call.args?.site || '').trim();
    const r = await querySiteAlarms(site, lang);
    return {
      text: r.text,
      answered: r.answered,
      channel: 'sitealarm',
      stats: { ...(r.stats || {}), totalMs: Date.now() - t0 },
      routeArgs: { site },
    };
  }

  if (call.tool === 'query_tickets') {
    const spec = normalizeArgs(call.args, opts.now, opts.question);
    opts.onDebug?.({ stage: 'tool-query_tickets', spec });
    const r = await queryTickets(spec);
    if (!r.ok) {
      // 查询失败**不抛、不编**：明确说查不了，让用户去网页版或问同事。
      return {
        answered: false,
        channel: 'stats',
        text:
          lang === 'en'
            ? `I couldn't run the ticket query: ${r.error}. Please try again later.`
            : `工单统计没查成：${r.error}。稍后再试试～`,
        stats: { totalMs: Date.now() - t0 },
        routeArgs: spec,
      };
    }
    return {
      answered: true,
      channel: 'stats',
      text: renderStatsSafe(r.data, lang, r.degraded, spec.list, spec.dateGuessed),
      stats: { totalMs: Date.now() - t0, degraded: !!r.degraded, source: r.data?.source },
      routeArgs: spec,
    };
  }

  // search_knowledge（也是兜底）
  const res = await ragAnswer(opts.question || '', index, {
    lang,
    onDebug: opts.onDebug,
    history: opts.history,
  });
  return { ...res, channel: 'kb' };
}

/** 渲染失败不让整条回复挂掉。 */
function lookupFail(lang, kind, code) {
  const text = renderNotFound(kind, code, lang);
  return {
    answered: false,
    channel: 'lookup',
    text: withWebHint(text, lang, CONFIG),
    stats: { totalMs: 0 },
  };
}

/**
 * B5：渲染「真规则匹配」的结果（来自 tt-analyze.py --lookup-level）。
 * 数据字段（规则名）保持原文，与 TT 通道「数据行不翻译」一致。
 */
function renderLevelMatch(r, code, attrs, lang) {
  const bits = [];
  if (attrs.assetType) bits.push(`assetType=${attrs.assetType}`);
  if (attrs.siteSubType) bits.push(`siteSubType=${attrs.siteSubType}`);
  if (attrs.vipSite) bits.push(`vipSite=${attrs.vipSite}`);
  const attrStr = bits.join('，');

  if (r.verdict === 'ok') {
    return lang === 'en'
      ? `Alarm code ${code} (${attrStr}) → ${r.severity}\n` +
          `Matched rule: #${r.ruleId} ${r.ruleName}\n` +
          `Basis: ${r.details}\n` +
          `Source: eflow_TT_rules.xlsx（与工单分析同一套规则引擎）`
      : `告警码 ${code}（${attrStr}）→ ${r.severity}\n` +
          `命中规则：#${r.ruleId} ${r.ruleName}\n` +
          `判定依据：${r.details}\n` +
          `来源：eflow_TT_rules.xlsx（与工单分析同一套规则引擎）`;
  }
  if (r.verdict === 'incomplete') {
    const miss = (r.missingFields || []).join('、');
    return lang === 'en'
      ? `Alarm code ${code} (${attrStr}) — cannot determine severity: missing ${miss}. ` +
          `Rules were not fully evaluated (need more site attributes). Not a "no match".`
      : `告警码 ${code}（${attrStr}）—— 级别无法判定：缺少字段 ${miss}，` +
          `规则未被真正评估（需补充站点属性）。这**不是**「未命中规则」。`;
  }
  // unknown：字段齐全但确实没有规则命中
  return lang === 'en'
    ? `Alarm code ${code} (${attrStr}) — no enabled severity rule matched. I won't guess.`
    : `告警码 ${code}（${attrStr}）—— 没有命中的级别规则。我不会按通用知识猜。`;
}

/**
 * 执行查表工具（三个 lookup_*）。**结果原样渲染，绝不送进 LLM 润色。**
 *
 * 查找表缺失（没跑过 ingest）时如实回「未构建」，不 fallback 进 RAG ——
 * 那是这次改造要消灭的「装懂」。
 */
export async function runLookup(call, lang, opts = {}) {
  const lookups = opts.lookups !== undefined ? opts.lookups : loadLookupsOnce();
  const t0 = Date.now();
  const code = String(call.args?.code || '').trim();

  if (!lookups) {
    const text =
      lang === 'en'
        ? 'The lookup table is not built yet. Ask an admin to run: npm run ingest'
        : '查找表还没构建，请管理员运行：npm run ingest';
    return { answered: false, channel: 'lookup', text, stats: { totalMs: Date.now() - t0 } };
  }

  if (call.tool === 'lookup_alarm_code') {
    if (!code) return lookupFail(lang, 'alarm', code);
    const data = findAlarmCode(lookups, code);
    if (!data) return lookupFail(lang, 'alarm', code);
    return {
      answered: true,
      channel: 'lookup',
      text: renderAlarmCode(data, lang),
      stats: { totalMs: Date.now() - t0 },
      routeArgs: { code },
    };
  }

  if (call.tool === 'lookup_compress') {
    if (!code) return lookupFail(lang, 'compress', code);
    const rows = findCompress(lookups, code);
    if (!rows.length) return lookupFail(lang, 'compress', code);
    return {
      answered: true,
      channel: 'lookup',
      text: renderCompress(rows, code, lang),
      stats: { totalMs: Date.now() - t0 },
      routeArgs: { code },
    };
  }

  if (call.tool === 'lookup_level_rule') {
    const sev = String(call.args?.severity || '').toUpperCase();
    const attrs = parseSiteAttrs(opts.question || '');

    // —— B5：有码 + 至少一个站点属性 → 走**真正的规则匹配**（复用 tt-analyze.py）——
    // 口径与工单分析完全一致，避免「查表说 P2、分析工单说 P3」。
    // 脚本不可用（没装 Python/规则表不在）时静默回退到静态候选列表（下面那段）。
    // `opts.staticOnly`（给离线测试/评测用）跳过子进程，避免无谓起 Python。
    if (!opts.staticOnly && code && Object.keys(attrs).length) {
      const r = await lookupLevelByRule(
        code,
        { asset: attrs.assetType, vip: attrs.vipSite, sub: attrs.siteSubType },
        { lang }
      );
      if (!r.unavailable) {
        return {
          answered: r.ok,
          channel: 'lookup',
          text: renderLevelMatch(r, code, attrs, lang),
          stats: { totalMs: Date.now() - t0 },
          routeArgs: { code, ...attrs },
        };
      }
    }

    let rules = [];
    if (code) rules = findLevelByCode(lookups, code);
    else if (/^P[1-4]$/.test(sev)) rules = findLevelBySeverity(lookups, sev);

    // 用户给了站点属性 → 只**过滤**条件里写明冲突取值的行（静态候选场景）。
    const filtered = filterLevelRulesByAttrs(rules, attrs);
    // 过滤后若把候选清空了，退回未过滤集（宁可多列，不可误删到空）
    if (filtered.length) rules = filtered;
    rules = rules.slice().sort((a, b) => a.priority - b.priority);

    if (!rules.length) {
      const text =
        lang === 'en'
          ? `No severity rule references ${code || sev} in the knowledge base. I won't guess.`
          : `知识库的级别规则里没有引用 ${code || sev} 的规则。我不会按通用知识猜。`;
      return {
        answered: false,
        channel: 'lookup',
        text: withWebHint(text, lang, CONFIG),
        stats: { totalMs: Date.now() - t0 },
        routeArgs: { code, severity: sev },
      };
    }
    return {
      answered: true,
      channel: 'lookup',
      text: renderLevelRules(rules, lang, { severity: sev, code }),
      stats: { totalMs: Date.now() - t0 },
      routeArgs: { code, severity: sev },
    };
  }

  return null;
}

/** 渲染失败时不让整条回复挂掉 —— 数字渲染出错也要给出一句人话。 */
function renderStatsSafe(data, lang, degraded, wantList, dateGuessed) {
  try {
    return renderStats(data, lang, degraded, wantList, dateGuessed);
  } catch (err) {
    return lang === 'en'
      ? 'I got the ticket numbers but failed to format the reply. Please try again.'
      : '工单数查到了，但回复格式化失败，麻烦再问一次。';
  }
}

/* --------------------------------- 入口 --------------------------------- */

/**
 * 完整路由：规则层 → 模型层 → 知识库兜底。
 *
 * 任何一步失败都退回知识库通道（用户至少能拿到一句不编造的回复），
 * 这是刻意的设计：工具路由是**增强**，不是依赖。
 *
 * @returns {Promise<{text:string, answered:boolean, channel:string, tool?:string, stats?:object}>}
 */
export async function routeWithTools(question, index, opts = {}) {
  const lang = opts.lang || 'zh';
  const now = opts.now || new Date();

  let call = null;
  let via = null;

  if (CONFIG.toolsEnabled !== false) {
    call = parseByRule(question, now);
    if (call) via = 'rule';
    if (!call) {
      const m = await routeByModel(question, now, lang, opts.history);
      if (m) {
        call = m;
        via = 'model';
      }
    }
  }

  opts.onDebug?.({ stage: 'tool-route', via, call });

  if (!call) {
    const res = await ragAnswer(question, index, { lang, onDebug: opts.onDebug });
    return { ...res, channel: 'kb' };
  }

  const out = await runTool(call, index, lang, { ...opts, question: question });
  return { ...out, tool: call.tool, via };
}
