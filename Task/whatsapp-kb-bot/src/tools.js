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
import { parseVmaxCcaIntent, runVmaxCca } from './vmaxcca.js';
import { parseWarehouseIntent, runWarehouseQuery, isWarehouseKnowledgeQuestion } from './warehousetool.js';
import {
  queryTickets,
  renderStats,
  parseDateRange,
  parseSeverity,
  parseStatus,
  parseListIntent,
  parseKeyword,
  KEYWORD_TERMS,
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
import {
  lookupEflowRules,
  renderEflowRuleAnswer,
  renderEflowRuleUnavailable,
} from './eflowRules.js';

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
      '**区间统计**问题。参数是日期范围、级别、闭环状态、站点名、领域关键字（都可选）。' +
      '**提问里带了告警类型限定词**（Fiber / 光纤 / Microwave / Power / Transmission / Congestion）' +
      '→ 必须填 keyword，否则会把「Fiber 相关」答成全网总数。',
    args: '{"start":"YYYY-MM-DD 或 空","end":"YYYY-MM-DD 或 空","severity":"P1~P4 或 空","status":"open|closed|all","site":"站点名 或 空","keyword":"Fiber 或 空"}',
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
    name: 'query_vmax_cca',
    desc:
      '按**手机号码**查 VMAX CCA 投诉系统的 XDR 用户信息：MSISDN/IMSI/IMEI/机型/流量/' +
      '驻留小区/根因分析。用于提问里出现 TEL 或 MSISDN + 手机号码（利比里亚号：231 开头 ' +
      '12 位，或本地 9 位如 773777115）的查询，可带一个截止时间（查它往前 60 分钟）。' +
      '**不要**用 lookup_alarm_code / query_tickets 答这类问题 —— 手机号不是告警码。',
    args: '{"msisdn":"231773777115 或 773777115","time":"2026-10-25 10:07 或 空"}',
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
    name: 'lookup_eflow_rule',
    desc:
      '查**eFlow 规则配置**：这个告警码会不会被压缩成父告警、会不会自动建 TT、由哪条定级/派发/推单规则接管。' +
      '用于「X 会被压缩成什么，会不会自动建单」「will alarm X be compressed / create a ticket automatically」' +
      '「这条告警支持自动派单吗」。查的是 eFlow 规则表本身：**没查到 = eFlow 没配专门规则**；' +
      '但「没配专门规则」**不等于「不建单」** —— 派发有兜底规则（#164 无条件进 FO 线），' +
      '所以压缩结论和建单结论必须分开给，不能一句「不支持」了事。' +
      '参数：code=告警码；parts=both|compress|tt（问了几件事）。',
    args: '{"code":"200201001","parts":"both"}',
  },
  {
    name: 'query_warehouse',
    desc:
      '查**库房（SP 备件库房）**的实时数据。用于「库房现在什么情况」「各仓库存多少」' +
      '「某物料还有多少库存」「这张入库单/出库单什么状态」这类**事实查询**。' +
      '参数：kind=overview（总览）/ material（按物料查库存，给 keyword）/ ' +
      'ticket（按单号查单据，给 ticket_no，单号形如 SPIB202610220006 或 SPOB202609150003）。' +
      '**不要**用 search_knowledge 答这类问题 —— 库存和单据状态每小时都在变，' +
      '语料里没有也不该有这些数字。',
    args: '{"kind":"overview","keyword":"物料编码或名称 或 空","ticket_no":"SPIB... 或 SPOB... 或 空"}',
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
  '· 出现告警码，且**同时**问「压缩」和「会不会自动建单/派单」（compressed + service ticket ' +
  'automatically generated）→ 用 lookup_eflow_rule，parts=both。两件事都要答，别只答压缩。\n' +
  '· 出现告警码，只问**会不会自动建单 / 自动派单 / 支持自动处理吗**（will a ticket be created ' +
  'automatically / 自动建 TT）→ 用 lookup_eflow_rule，parts=tt。\n' +
  '· 出现告警码，且问**级别 / 定级 / 几级**；或只问「P1 是什么级别」「P1 规则」→ 用 lookup_level_rule。\n' +
  '· 有告警码且问含义/压缩/级别时，**一律不要**用 search_knowledge —— 那是查表题，不是叙述题。\n' +
  '· 问某个**站点当前有没有告警 / 是不是 up / 什么告警 / down 没 down** → 用 query_site_alarms；' +
  '把站点名填进 site。**这类问题绝不要用 query_tickets** —— query_tickets 是工单数量，' +
  '按站名匹配工单会得到 0，而 0 张工单**不等于**没有告警，那会答错。\n' +
  '· 出现 TEL / MSISDN + **手机号码**（利比里亚号：231 开头 12 位，或 773777115 这类本地号）' +
    '→ 用 query_vmax_cca，号码填 msisdn（本地号原样填，执行层自动补 231），截止时间填 time。' +
    '手机号**不是**告警码，不要用 lookup_alarm_code。\n' +
    '· 提到**库房/仓库/库存/存货/备件/领料/入库/出库/调拨**（或 warehouse / inventory / stock / spare parts）' +
    '→ 用 query_warehouse。带单号（SPIB/SPOB 开头）填 ticket_no；' +
    '点名物料时填 keyword 且 kind=material；其余（只说「库房怎么样」）kind=overview。\n' +
    '· 库房问题**一律不要**用 search_knowledge —— 库存数量与单据状态是实时数据，' +
    '语料里没有，检索只会给出「资料里没有实际库房数据」。\n' +
  '· 其余「流程 / 为什么 / 怎么走 / 定义」这类**叙述性静态知识** → 用 search_knowledge。\n' +
  '· 注意区分：「P1 是什么」= lookup_level_rule；「今天有几个 P1」= query_tickets。\n' +
  '· 拿不准且**没有**告警码 → 用 search_knowledge。\n' +
  '· 提问里若点名了**具体站点**（如「Wood camp 这个站」「Qcell R.I.A 有几个单」），' +
  '把站点名原样填进 site；没点名就留空字符串。\n' +
  '· 提问里若带了**告警类型限定词**（Fiber / 光纤 / 光缆 / Microwave / Power / ' +
  'Transmission / Congestion），把该词填进 keyword。**没限定就留空** —— ' +
  '漏填等于把「Fiber 相关的工单」答成全网总数（2026-10-26 实测的故障）。\n' +
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
  // 复数/不规则写法：2026-10-26 实测「How many TTs in last 7 days?」残余出
  // `["TTs"]`（`tt` 有、`tts` 没有），规则层弃权 → 白多花一次模型调用。
  'tts', 'wos', 'nums',
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
  // 工单的同义说法（英文侧）。中文侧的「故障单」在 leftoverTerms 的剥词表里，
  // 英文侧走的是这张停用词表 —— 「how many fault tickets today」里的 fault
  // 若不在这里，会被当成陌生专名 → 规则层弃权（2026-10-18 与中文同因）。
  'fault', 'faults', 'incident', 'incidents', 'case', 'cases',
  'issue', 'issues', 'problem', 'problems', 'outage', 'outages',
  // 「X 相关的单」里的关联词：2026-10-26 实测「How many Fiber issues **related**
  // TTs for last 7 days?」残余出 "related" —— 它不是条件，只是一句连接词。
  // 漏了它，即使 keyword 已经抽出来，规则层仍会弃权（弃权后就没人填 keyword 了）。
  'related', 'regarding', 'concerning', 'about', 'involving', 'linked',
]);

/**
 * 抹掉提问里所有已知的领域关键字写法（英文与中文）。
 *
 * 与 `parseKeyword` 共用同一张词表（`KEYWORD_TERMS`），只是这里要的是「抹掉」
 * 而不是「取出第一个」—— 一句话里可能既有 "Fiber" 又有 "光纤"。
 *
 * 不能只抹 `parseKeyword` 返回的那一个：它的返回值是**规范名**（`Fiber`），
 * 而句子里写的是 `光纤`/`Fiber Break`，正则对不上。
 */
function stripKeywordWords(q) {
  let s = String(q || '');
  for (const [, re] of KEYWORD_TERMS) {
    const g = new RegExp(re.source, 'gi');
    s = s.replace(g, ' ');
  }
  return s;
}

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
  // 工单的同义说法 —— 必须先于「单」这个单字剥，否则「故障单」会先被剥成
  // 「故障」，「故障」再被当成解释不了的专名（站名/人名）→ 规则层弃权交模型层。
  //
  // 2026-10-18 实测（qa_log 2026-10-16T23:02~23:07）：群里 7 条提问**全部**落到
  // 模型层，每条 4.4~4.9 秒，「今天多少故障单」耗时 35.7 秒。原因就是
  // `leftoverTerms('本周多少故障单')` 返回 `["故障"]`。
  // 补上这一组后同样的问法回到规则层（约 60ms），且不再让模型去猜
  // status/severity —— 「给我发下本周的P1故障单的ID」曾因模型把 status 猜成
  // open 而给出错误的「未闭环」口径。
  s = s.replace(/(故障单|告警单|问题单|工单|故障|单子)/g, ' ');
  // 中文时间与数量词
  s = s.replace(
    /(今天|今日|昨天|昨日|前天|本周|这周|上周|本月|这个月|上个月|最近|过去|近|多少|几个|几单|几条|有没有|有吗|有没|有|数量|总计|合计|一共|个|单|条|天|周|月|年|日|的|了|吗|呢|啊|吧|请|帮|我|看|查|下|一下|这个|那个|哪些|什么)/g,
    ' '
  );
  // 「要单号名单」的说法（parseListIntent 认得的那批）也必须剥掉，
  // 否则残余的 "ID" / "TT" 会被当成解释不了的专名，
  // 导致规则层白白弃权、多花一次模型调用。
  // 实测：「本月有几个P1的单子，请输出TT单的ID给我」曾因此落到模型层。
  // ⚠️ `ID` / `TT` 必须带词边界：整条正则是 /i 大小写不敏感，
  // 裸 `ID` 会把 **incidents → inc ents**、`TT` 会把 **settlement → se tt lement**
  // 切碎，剩下的碎片随后被当成陌生专名 → 规则层白白弃权。
  // （2026-10-18 加「号码」时实测踩到：`how many P1 incidents today` 被切成
  //  inc + ents 两条残余。旧代码此处也是裸 `ID`，只是当时没人用 incidents 提问。）
  s = s.replace(
    /单号|编号|号码|明细|清单|列出|列一下|列出来|发下|发一下|发来|有哪些|哪几单|哪些单|输出|给我|\bTT\b(?!\d)|\bID\b/gi,
    ' '
  );
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
/**
 * 「会不会自动建单」类问法 → lookup_eflow_rule（parts=tt）。
 *
 * 为什么要单列：压缩和建单是**两件事**，答案不同（子告警会被压缩、TT 却建在父告警上）。
 * 旧实现只认压缩，用户问「会被压缩吗，会不会自动建单」时后半句被整段丢掉
 * —— 2026-10-28 群内实测（200201001）。
 */
const TICKET_INTENT =
  /(建单|建\s*TT|自动.{0,4}(建单|创建|生成|派单|开工单)|生成.{0,4}工单|service\s*ticket|trouble\s*ticket|auto.{0,6}ticket|ticket.{0,20}(automatic|auto|created|generated)|raise\s+a\s+ticket)/i;
/** 级别类问法 → lookup_level_rule。 */
const LEVEL_INTENT = /(级[别位]|定级|几级|什么级别|怎么判定|如何判定|severity|priority|P\s*[1-4]\s*(级别|是什么|怎么|规则)?|P\s*[1-4]\s*规则)/i;

/**
 * 去掉日期/时间片段，避免把年份、时钟数字当成告警码。
 *
 * 2026-10-28 群里实测：`Liscr site one 5G AAU radio offline since 2026-10-27 22:41:57,
 * still no auto TT…` 被 `extractAlarmCode` 抽出 **2026**（日期里的年份），
 * 路由成 lookup_alarm_code，回一句「码表里没有 2026」，整条站名/时间/无自动建单
 * 的诉求全丢 —— 压根没进知识库。
 *
 * 只摘「形如日期/时刻」的片段，不动裸数字码：
 *   2026-10-27 / 2026/10/27 / 2026年10月27日 / 22:41:57 / 22:41 / 裸年份 2026
 */
function stripDateTime(q) {
  return String(q)
    .replace(/\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?/g, ' ')
    .replace(/\d{1,2}:\d{2}(?::\d{2})?/g, ' ')
    .replace(/\b(?:19|20)\d{2}\b/g, ' ');
}

/** TEL / MSISDN 上下文：这类句子里的长数字是手机号，不是告警码。 */
const CCA_CONTEXT = /(?:^|[^A-Za-z])(?:tel|msisdn)\b/i;

/**
 * 从提问里抽告警码：≥3 位数字（够长才算码；短码只在「告警码」上下文里认）。
 *
 * 两条护栏（都是 2026-10-28 实测补的，否则知识类提问会被静默劫持成查表）：
 *   · 先摘掉日期/时间片段 —— 年份 2026 不是码；
 *   · 长号码（≥10 位）不是码 —— 手机号 12 位、TT 单号 12 位都归各自通道；
 *   · 句中出现 TEL/MSISDN 时一律不认码，让 CCA 通道处理（号码写在前面的
 *     「231777550122 TEL please check…」旧实现会漏判成码）。
 */
function extractAlarmCode(q) {
  const s = String(q);
  // 「告警码 9990」/「alarm code 9920」这类显式上下文里，3 位也可以
  const explicit = s.match(/(?:告警码|告警|alarm\s*code|alarm)\s*[:：]?\s*(\d{3,})/i);
  if (explicit) return explicit[1];
  if (CCA_CONTEXT.test(s)) return '';
  // 否则要 4~9 位：低于 4 位会误吃「P1」「3G」；≥10 位是手机号/单号，不是码
  const long = stripDateTime(s).match(/\b(\d{4,9})\b/);
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
    // 压缩 + 建单是两件事，一起问时必须两个都答 → 走 eFlow 规则配置（能同时给压缩与建单）
    if (COMPRESS_INTENT.test(q) && TICKET_INTENT.test(q)) {
      return { tool: 'lookup_eflow_rule', args: { code, parts: 'both' } };
    }
    if (COMPRESS_INTENT.test(q)) return { tool: 'lookup_compress', args: { code } };
    // 只问建单（没问压缩）→ 直接查 eFlow 规则；旧实现会当成「含义」回一句码表解释，答非所问
    if (TICKET_INTENT.test(q)) return { tool: 'lookup_eflow_rule', args: { code, parts: 'tt' } };
    if (LEVEL_INTENT.test(q)) return { tool: 'lookup_level_rule', args: { code } };
    if (MEANING_INTENT.test(q)) return { tool: 'lookup_alarm_code', args: { code } };
    // 有码但没明确问法：默认当「含义」（最常见的「这个码是什么」意图）
    return { tool: 'lookup_alarm_code', args: { code } };
  }

  // 无数字码，但问句里出现**已知告警名/缩写**（CSD、MW LINK DOWN…）→ 解析成码再查。
  // 手册 §3.3 的场景：「CSD 定几级」没有长数字，向量会召回错行；这里改走查表。
  // 仅在**有级别/含义/压缩意图**时才生效，避免把普通叙述题误当查表。
  const wantsLookup =
    LEVEL_INTENT.test(q) || MEANING_INTENT.test(q) || COMPRESS_INTENT.test(q) || TICKET_INTENT.test(q);
  if (wantsLookup) {
    const byName = resolveCodeByName(lookups, q);
    if (byName) {
      if (COMPRESS_INTENT.test(q) && TICKET_INTENT.test(q)) {
        return { tool: 'lookup_eflow_rule', args: { code: byName, parts: 'both' } };
      }
      if (COMPRESS_INTENT.test(q)) return { tool: 'lookup_compress', args: { code: byName } };
      if (TICKET_INTENT.test(q)) return { tool: 'lookup_eflow_rule', args: { code: byName, parts: 'tt' } };
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
  // 疑问词/助动词不是站名 —— 2026-10-28 实测：「How will Alarm Code 200201001 be
  // compressed…」被抽成站名「How」，整题拐进站点告警通道，答了一句「How 现在没有告警」。
  'how', 'will', 'would', 'be', 'was', 'were', 'are', 'do', 'does', 'did', 'can',
  'could', 'should', 'may', 'might', 'code', 'alarmcode', 'mean', 'means',
]);

function extractSiteName(q) {
  const s = String(q || '');

  // ① *...* 强调包裹 —— 用户惯用 *Palm Bay* 点名，最可靠，优先。
  const star = s.match(/\*+\s*([^*]{2,40}?)\s*\*+/);
  if (star) {
    const name = star[1].trim();
    if (name && !SITE_STOPWORDS.has(name.toLowerCase())) return name;
  }

  // ①.5 「site name X」/「站点 X」显式引导词。
  //
  // 2026-10-24 新增：现场提问常写成
  //   site name :Grand Cess(3629），Alarm: 9920(Critical)…
  // 站名后面紧跟**中文全角括号**里的站号。纯英文大写词正则会把
  // `3629` 一起吞成专名的一部分，再被「首词是小写…」等规则卡住而弃权，
  // 最终整句退回查表通道 —— 站名和时间全丢。
  //
  // 边界为什么是「括号/分隔符 **或 遇到停用词**」：
  // 只靠标点不够——`site name Palm Bay form eflow` 里 `form`（FROM 的拼错）
  // 是停用词但前面没有标点，会连读成 `Palm Bay form eflow`。
  // 所以逐词累积，碰到停用词立刻停，保留已累积的部分。
  const guided = s.match(/(?:site\s*name|站点?)\s*[:：]?\s*([A-Za-z][A-Za-z0-9'.\-\s]{1,60})/);
  if (guided) {
    const words = guided[1].split(/[\s,;:()（）,。;]+/).filter(Boolean);
    const keep = [];
    for (const w of words) {
      if (SITE_STOPWORDS.has(w.toLowerCase())) break;
      keep.push(w);
      if (keep.length >= 4) break; // 站名极少超过 4 个词，防止吞掉整句
    }
    const name = keep.join(' ');
    if (name.length >= 3 && !SITE_STOPWORDS.has(name.split(/\s+/)[0].toLowerCase())) {
      return name;
    }
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

  // ①.15 VMAX CCA 用户查询：TEL/MSISDN + 号码是用户与群的**约定信号**
  //（「看到 TEL 就是查 CCA」）。必须排在站点告警与查表意图**之前**：
  //   · 「TEL 231773777115」里的 12 位长数字会被 extractAlarmCode 当成告警码，
  //     拐去 lookup_alarm_code 只回一句「码表里没有」，号码与时间全丢
  //     （与 2026-10-24 站点名+告警码被查表吞掉是同一类故障）；
  //   · 号码查询也不是工单统计/告警状态，晚判同样会被前面的数量词截走。
  const cca = parseVmaxCcaIntent(q, now);
  if (cca) return { tool: 'query_vmax_cca', args: { msisdn: cca.msisdn, time: cca.endText } };

  // ①.18 库房（SP 备件库房）意图。
  //
  // 必须排在**查表**与**统计**之前，两条都会被抢：
  //   · 「物料 033030100282 还有多少库存」里有「多少」→ COUNT_INTENT 命中，
  //     会被统计通道接走，去查工单表 —— 工单表里没有物料，答「0 单」，
  //     而用户问的是库存数量，**答错而不报错**；
  //   · 「SPIB202610220006 这个入库单什么状态」里的长数字会被
  //     extractAlarmCode 当成告警码，拐去 lookup_alarm_code 只回「码表里没有」。
  //
  // 库房单号（SPIB/SPOB）不是告警码，这一点与 VMAX 手机号同理。
  const wh = parseWarehouseIntent(q);
  if (wh) return wh;

  // 查表意图**提前算一次**：下面站点告警通道要靠它区分「名称→码的查表题」
  // 与「某站现在有没有告警」。①.5 复用同一结果，不重复解析（名称反查要扫码表）。
  const hasCountWordEarly = COUNT_INTENT.test(q);
  const lookupIntentEarly = hasCountWordEarly ? null : parseLookupIntent(q);

  // ①.2 站点告警意图：出现**告警状态词**时，优先走 query_site_alarms。
  // 必须在统计判断**和查表判断**之前 —— 否则
  // 「Palm Bay 有没有告警」会被 COUNT_INTENT 的「有没有」拐去统计，
  // 回一句 tickets: 0，把「工单数」误当「告警状态」。
  //
  // 2026-10-24 修正：原先这里有个 `&& !extractAlarmCode(q)`，本意是让出
  // 「what is alarm code 9920」这类纯查码题。但群里真实问法形如
  //   site name :Grand Cess(3629)，Alarm: 9920(Critical)，Alarm occurred 2026-10-24 10:50:29
  // 句子里**同时**有站名和告警码，于是被这个条件否掉 → 继续往下落到
  // parseLookupIntent → 只回了「9920 是 Complete site down」，整条站名/时间全丢。
  // 判据改为「**有站名** + 告警语义」：站名才是站点告警通道的前提，
  // 告警码在这里只是**补充信息**，不再一票否决。
  // 「what is alarm code 9920」没有站名 → 仍走查表，不受影响。
  if (SITE_ALARM_INTENT.test(q)) {
    const site = extractSiteName(q);
    // 告警码不下推：本通道回答的是「这个站现在有哪些活动告警」，
    // 把码塞进过滤条件会让「码记错了」的用户直接得到「无告警」的假结论。
    //
    // 2026-10-28 补充：**明确在问某个告警码的规则**时，不要拐进站点通道。
    // 「How will Alarm Code 200201001 be compressed…」里 `alarm` 命中了
    // SITE_ALARM_INTENT，站点名又误抽成「How」，于是整题被答成
    // 「How 现在没有告警」—— 与用户问的压缩/建单毫无关系。
    // 判据：有「告警码/alarm code」这类**码上下文**，且**没有**显式站点引导词。
    const codeContext = /(告警码|告警\s*号|alarm\s*code)/i.test(q);
    const explicitSite = /(\bsite\s*name\b|\bsite\s*[:：]|站点|基站|\*[^*]{2,40}\*)/i.test(q);
    // 2026-10-28 再补：**「名称 → 告警码」的查表题**也不能进站点通道。
    // 黄金集里三条一直是红的：
    //   Fiber Break 是什么告警 / Complete site down 是什么码 / MW LINK DOWN 是几级
    // 它们没有数字码，靠名称反查（resolveCodeByName）；但「告警 / down」命中了
    // SITE_ALARM_INTENT，站名又被抽成「Fiber Break」「Complete」这类短语，
    // 于是被答成「X 现在没有告警」—— 与用户问的码/级别毫无关系。
    // 判据：句子里**没有数字码**且能按名称解析出告警码 → 那是查表题，让给 ①.5。
    // 有数字码的混合问法（site name X, Alarm: 9920）不受影响，仍是站点通道。
    const nameToCode = lookupIntentEarly && !/\d{3,}/.test(q);
    if (site && !nameToCode && !(codeContext && !explicitSite)) {
      return { tool: 'query_site_alarms', args: { site } };
    }
  }

  // ①.5 查表意图（告警码含义 / 压缩 / 级别）。
  //
  // 必须**先于**统计判断：`test-tools.mjs [3] q8` 明确要求
  // 「告警码 198094422 会被压缩成什么」不得被当成统计。
  // 但若问题里同时有**数量词**（「198094422 压缩后有几单」），那是统计意图 ——
  // 所以这里只在**没有数量词**时才认查表，交下面走统计。
  // （结果在 ①.2 之前已算好，见 lookupIntentEarly。）
  if (lookupIntentEarly) return lookupIntentEarly;

  // ② 统计意图：必须有数量/时间信号，且不是纯知识问法。
  const date = parseDateRange(q, now);
  const sev = parseSeverity(q);
  const kw = parseKeyword(q);
  const hasCountWord = COUNT_INTENT.test(q);
  const isKnowledge = KNOWLEDGE_INTENT.test(q);
  const isStats = (hasCountWord || date) && !isKnowledge;

  // ③ 有额外条件（站名等规则抽不准的专名）时弃权，交模型层。
  //
  // ⚠️ 但已知的**领域关键字**（Fiber / Microwave…）不算「抽不准的专名」——
  // 它有对应的查询参数（keyword），吃掉它是静默丢条件。
  // 2026-10-26 实测：「How many Fiber issues related TTs for last 7 days?」
  // 残余出 `["Fiber","related","TTs"]` 直接弃权，模型层也没有 keyword 参数可填，
  // 于是回了全网 753，而同一句去掉 "Fiber issues related" 之后还是 753。
  // 现在把关键字从残余里剥掉再判断；剩下的残余仍按原纪律弃权。
  if (isStats) {
    // ⚠️ 不能用 `\b` 包关键字：中文与 ASCII 之间**没有词边界**
    //（「有多少光纤故障单」里 `\b光纤\b` 根本不成立），所以这里改为
    // 把词表里**所有**能命中本句的写法一律抹掉，再判残余。
    // 2026-10-26 实测：只用 `\b${kw}\b` 时中文问法仍弃权。
    const residual = leftoverTerms(kw ? stripKeywordWords(q) : q);
    if (residual.length) return null;
  }

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
          // 规则层已认出的领域关键字：必须真的传到查询里，
          // 否则就是「解析了但不用」——与没解析一样，且更隐蔽。
          keyword: kw,
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
  // 领域关键字：仍以**原始提问**为准（parseKeyword 是封闭词表，规则层与模型层
  // 同一个函数）—— 模型给的 keyword 只在原句里确实出现时采信，
  // 防止模型把「TTs」之类泛词当关键字塞进来，导致 0 单。
  const kwFromQ = parseKeyword(question);
  const kwFromModel = String(raw.keyword || '').trim().slice(0, 30);
  out.keyword =
    kwFromQ ||
    (kwFromModel && question.toLowerCase().includes(kwFromModel.toLowerCase()) ? kwFromModel : '');
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
  // lookup_eflow_rule 同属这一类 —— 规则配置的结论必须原样给，不能让模型改写。
  if (
    call.tool === 'lookup_alarm_code' ||
    call.tool === 'lookup_compress' ||
    call.tool === 'lookup_level_rule' ||
    call.tool === 'lookup_eflow_rule'
  ) {
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
      // ttTiming 是逐跳耗时（取 PG 行 / 跑渲染脚本 / eFlow 实时），
      // 只在日志里用，不进回复正文。见 tt.js 的 analyzeTt。
      stats: { totalMs: Date.now() - t0, okCount: r.okCount, total: r.total, ttTiming: r.timing },
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

  if (call.tool === 'query_vmax_cca') {
    // 号码/时间的最终解析在 vmaxcca.js 里做（优先级：规则层解析 > 模型参数 > 当前时刻），
    // 与统计通道 normalizeArgs 同一纪律 —— 模型不知道现在几点。
    const r = await runVmaxCca(call.args || {}, {
      lang,
      now: opts.now,
      question: opts.question || '',
    });
    return {
      text: r.text,
      answered: r.answered,
      channel: 'vmaxcca',
      // 透传本通道的回复长度上限（CCA 内容比全局 2000 长，见 vmaxcca.js 注释）
      maxReplyChars: r.maxReplyChars,
      stats: { ...(r.stats || {}), totalMs: Date.now() - t0 },
      routeArgs: r.routeArgs,
    };
  }

  if (call.tool === 'query_warehouse') {
    // kind 决定查什么：总览 / 按物料 / 按单号。
    // 参数优先用规则层解析出的（rule 层 > 模型层），与统计通道同一纪律。
    const args = {
      ...(call.args || {}),
      ...(opts.warehouseArgs || {}),
    };
    // 模型可能漏填 kind（只回 {"tool":"query_warehouse","args":{}}），
    // 也可能把单号当物料名填进 keyword —— 这里按提问重新校一遍。
    // 返回 null = 这是道**口径问题**，该走知识库而不是实时数据。
    const corrected = correctWarehouseArgs(args, opts.question || '');
    if (!corrected) {
      const res = await ragAnswer(opts.question || '', index, { lang, onDebug: opts.onDebug });
      return { ...res, channel: 'kb' };
    }
    opts.onDebug?.({ stage: 'tool-query_warehouse', args: corrected });
    const r = await runWarehouseQuery(corrected, lang);
    return {
      text: r.text,
      answered: r.answered,
      channel: 'warehouse',
      stats: { ...(r.stats || {}), totalMs: Date.now() - t0 },
      routeArgs: corrected,
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

/** 「查不到时去网页版问」的尾巴：网页挂件自己要传 webHint:false 关掉（见 http-server.js）。 */
function webHintFor(opts) {
  return opts.webHint === false ? (text) => text : (text) => withWebHint(text, opts.lang || 'zh', CONFIG);
}

/** 渲染失败不让整条回复挂掉。 */
function lookupFail(lang, kind, code, opts = {}) {
  const text = renderNotFound(kind, code, lang);
  return {
    answered: false,
    channel: 'lookup',
    text: webHintFor({ ...opts, lang })(text),
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

  // —— eFlow 规则配置通道（压缩 + 自动建单）——
  // **不依赖** data/lookups.json：那张表只是「产生过 TT 的码」的快照。
  // 用户问的是「eFlow 里配没配」，所以这里查的是规则表本身。
  if (call.tool === 'lookup_eflow_rule') {
    // 模型有时会把整句塞进 code（"Alarm Code 200201001"）。必须抽出数字再查 ——
    // 否则是拿一个不存在的码去比对规则，会得出「没配」的**假结论**。
    const rawCode = String(call.args?.code || '').trim();
    const codeN = /^\d+$/.test(rawCode) ? rawCode : (rawCode.match(/\d{3,}/) || [''])[0];
    if (!codeN) return lookupFail(lang, 'compress', rawCode, opts);
    const parts =
      call.args?.parts === 'tt' || call.args?.parts === 'compress' ? call.args.parts : 'both';
    const r = await lookupEflowRules(codeN);
    if (!r.ok) {
      // 通道不可用 → 只说「查不了」，绝不说「没配」
      return {
        answered: false,
        channel: 'eflowrule',
        text: webHintFor({ ...opts, lang })(renderEflowRuleUnavailable(lang, r.reason)),
        stats: { totalMs: Date.now() - t0, reason: r.reason },
        routeArgs: { code: codeN, parts },
      };
    }
    return {
      answered: true,
      channel: 'eflowrule',
      text: renderEflowRuleAnswer(r.data, lang, parts),
      stats: {
        totalMs: Date.now() - t0,
        rulesChecked: r.data.sources?.alarmRules?.correlationEnabled,
      },
      routeArgs: { code: codeN, parts },
    };
  }

  if (!lookups) {
    const text =
      lang === 'en'
        ? 'The lookup table is not built yet. Ask an admin to run: npm run ingest'
        : '查找表还没构建，请管理员运行：npm run ingest';
    return { answered: false, channel: 'lookup', text, stats: { totalMs: Date.now() - t0 } };
  }

  if (call.tool === 'lookup_alarm_code') {
    if (!code) return lookupFail(lang, 'alarm', code, opts);
    const data = findAlarmCode(lookups, code);
    if (!data) return lookupFail(lang, 'alarm', code, opts);
    return {
      answered: true,
      channel: 'lookup',
      text: renderAlarmCode(data, lang),
      stats: { totalMs: Date.now() - t0 },
      routeArgs: { code },
    };
  }

  if (call.tool === 'lookup_compress') {
    if (!code) return lookupFail(lang, 'compress', code, opts);
    const rows = findCompress(lookups, code);
    if (!rows.length) {
      // 本地快照未命中 ≠ eFlow 没配。快照只收录「产生过 TT 的码」，
      // 用户问的新码（如 5G 的 200201001）必然落在快照之外。
      // 先升级到 eFlow 规则表核实；核实不到才回「查不到」。
      const r = await lookupEflowRules(code);
      if (r.ok) {
        return {
          answered: true,
          channel: 'eflowrule',
          text: renderEflowRuleAnswer(r.data, lang, 'compress'),
          stats: {
            totalMs: Date.now() - t0,
            escalated: 'eflow',
            rulesChecked: r.data.sources?.alarmRules?.correlationEnabled,
          },
          routeArgs: { code },
        };
      }
      return lookupFail(lang, 'compress', code, opts);
    }
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
        text: webHintFor({ ...opts, lang })(text),
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
 * 校正模型吐出的库房参数。
 *
 * 模型在这件事上会犯三种错，每一种都会让答案**完全跑偏**：
 *   ① 漏填 kind —— 只回 {"tool":"query_warehouse","args":{}}，
 *      执行层默认按总览查，于是「某物料还有多少库存」答成全库总览；
 *   ② 把单号填进 keyword —— 「SPIB202610220006 这个单什么状态」
 *      变成去物料表里 LIKE '%SPIB202610220006%'，答「没找到」；
 *   ③ 把物料名填进 ticket_no —— 反过来，查单据时查不到。
 *
 * 所以：**只要原句里能自己解析出来，就以规则层为准**（与统计通道
 * 「规则解析 > 模型给的」同一纪律）。模型只在规则层也认不出时才被采信。
 */
function correctWarehouseArgs(args, question) {
  const out = { ...(args || {}) };
  const rule = parseWarehouseIntent(question);

  // 规则层认不出（纯英文长句等）→ 至少保证 kind 合法。
  // ⚠️ 但**知识问法**（有哪些类型/怎么算）规则层会返回 null（走 RAG），
  //    这里必须把它也判出来交回知识库通道 ——
  //    否则模型一旦选了 query_warehouse，口径问题又被实时数据吃掉。
  if (!rule && isWarehouseKnowledgeQuestion(question)) {
    return null; // ← 调用方据此改走 RAG
  }

  // 规则层认得出 → 用规则层的 kind 与关键参数
  if (rule) {
    out.kind = rule.args.kind;
    if (rule.args.kind === 'ticket') {
      out.ticket_no = rule.args.ticket_no;
      out.keyword = '';
    } else if (rule.args.kind === 'material') {
      out.keyword = rule.args.keyword || out.keyword || '';
      out.ticket_no = '';
    }
    return out;
  }

  // 规则层认不出（纯英文长句等）→ 至少保证 kind 合法
  const kind = String(out.kind || '').toLowerCase();
  if (!['overview', 'material', 'ticket'].includes(kind)) {
    out.kind = out.ticket_no ? 'ticket' : out.keyword ? 'material' : 'overview';
  }
  out.keyword = String(out.keyword || '').trim();
  out.ticket_no = String(out.ticket_no || '').trim().toUpperCase();
  return out;
}

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
