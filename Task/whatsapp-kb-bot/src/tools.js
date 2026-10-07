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
import { answer as ragAnswer } from './rag.js';
import { extractTtNos, analyzeTickets } from './tt.js';
import {
  queryTickets,
  renderStats,
  parseDateRange,
  parseSeverity,
  parseStatus,
  parseListIntent,
} from './ttquery.js';

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
    name: 'search_knowledge',
    desc:
      '检索知识库文档。用于「规则是什么」「某告警码是什么意思」「流程怎么走」' +
      '这类**静态知识**问题，以及所有不含工单统计意图的问题。',
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
  '· 问的是「规则 / 含义 / 流程 / 怎么判定」这类**静态知识** → 用 search_knowledge。\n' +
  '· 注意区分：「P1 是什么」= search_knowledge；「今天有几个 P1」= query_tickets。\n' +
  '· 拿不准就用 search_knowledge。\n' +
  '· 提问里若点名了**具体站点**（如「Wood camp 这个站」「Qcell R.I.A 有几个单」），' +
  '把站点名原样填进 site；没点名就留空字符串。\n' +
  '\n只输出一行 JSON，不要解释：\n' +
  '{"tool":"<工具名>","args":{...}}';

/**
 * 构造路由 prompt，并**注入今天与已解析出的日期**。
 *
 * 为什么非注入不可：模型没有时钟，问它「今天是几号」只能得到瞎猜。
 * 2026-10-07 实测「Wood camp 这个站**昨天**有几个单」——
 * 规则层因站名弃权后，日期就断了线，最终查成了**今天**，
 * 返回 0 单，看起来像「这个站昨天没事」，实际是查错了日子。
 *
 * 注入后模型能照抄日期；即便它还是抽错，
 * `normalizeArgs` 里「规则解析 > 模型给的 > 今天」的优先级也会兜住。
 */
function buildRouterPrompt(question, now) {
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
    lines.push('提问中没有明确日期 → start 与 end 都留空字符串，不要自己编。');
  }
  return lines.join('\n');
}

/* ------------------------------- 规则层 ------------------------------- */

/**
 * 统计意图的触发词。
 *
 * 收得**窄**是刻意的：宁可漏判走模型层，也不要把「P1 是什么级别」误判成查数。
 * 所以「P1」单独出现不算，必须搭配数量词或时间词才成立。
 */
const COUNT_INTENT =
  /(多少|几个|几单|几条|有多少|有没有|有吗|有没|数量|总计|合计|count|how\s+many|how\s+much|any\s|P\d.*\?|today|yesterday)/i;

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
]);

/**
 * 剥掉规则层已经认得的东西，返回剩余的"解释不了的片段"。
 *
 * @param {string} q 原始提问
 * @returns {string[]} 残余片段
 */
export function leftoverTerms(q) {
  let s = String(q || '');

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
    /(今天|今日|昨天|昨日|前天|本周|这周|上周|本月|这个月|上个月|最近|过去|近|多少|几个|几单|几条|有没有|有吗|有没|数量|总计|合计|一共|个|单|条|的|了|吗|呢|啊|吧|请|帮|我|看|查|下|一下|这个|那个|哪些|什么)/g,
    ' '
  );
  // 「要单号名单」的说法（parseListIntent 认得的那批）也必须剥掉，
  // 否则残余的 "ID" / "TT" 会被当成解释不了的专名，
  // 导致规则层白白弃权、多花一次模型调用。
  // 实测：「本月有几个P1的单子，请输出TT单的ID给我」曾因此落到模型层。
  s = s.replace(/单号|编号|明细|清单|列出|列一下|有哪些|哪几单|哪些单|输出|给我|TT(?![0-9])|ID/gi, ' ');

  const terms = s
    .split(/[^A-Za-z0-9\u4e00-\u9fa5]+/)
    .map((t) => t.trim())
    .filter(Boolean);

  const out = [];
  for (const t of terms) {
    const low = t.toLowerCase();
    // 纯中文残余不再深究：中文问句抹掉已知词后本就剩零碎，
    // 逐字判断只会带来噪声。站点信号主要靠英文专名与"站"字。
    if (/^[\u4e00-\u9fa5]+$/.test(t)) {
      if (SITE_WORD.test(t)) out.push(t);
      continue;
    }
    if (STOP_WORDS.has(low)) continue;
    if (low.length < 2) continue;
    out.push(t);
  }
  return out;
}

/** 「站」类词：中文语境下站点存在与否的直接信号。 */
const SITE_WORD = /(站点?|基站|站名|这个站|那个站|某站|哪个站)/;

/**
 * 规则层路由：能确定就返回工具调用，确定不了返回 null（交给模型层）。
 *
 * @returns {{tool:string, args:object}|null}
 */
export function parseByRule(question, now = new Date()) {
  const q = String(question || '').trim();

  // ① 单号优先：TT/WO 单号是强信号，且这条通道最成熟。
  const ttNos = extractTtNos(q);
  if (ttNos.length) return { tool: 'analyze_ticket', args: { tt_no: ttNos[0] } };

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
 */
export function parseToolCall(content) {
  const s = String(content || '');
  const start = s.indexOf('{');
  const end = s.lastIndexOf('}');
  if (start < 0 || end <= start) return null;
  let obj;
  try {
    obj = JSON.parse(s.slice(start, end + 1));
  } catch {
    return null;
  }
  const name = String(obj?.tool || '').trim();
  if (!TOOL_SPEC.some((t) => t.name === name)) return null;
  return { tool: name, args: obj?.args && typeof obj.args === 'object' ? obj.args : {} };
}

async function routeByModel(question, now, lang) {
  try {
    const { content } = await chat(
      [
        { role: 'system', content: buildRouterPrompt(question, now) },
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
 * 所以这里的优先级是：**规则从原始提问解析出的日期 > 模型给的日期 > 今天**。
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
      };
    }
    return {
      answered: true,
      channel: 'stats',
      text: renderStatsSafe(r.data, lang, r.degraded, spec.list),
      stats: { totalMs: Date.now() - t0, degraded: !!r.degraded, source: r.data?.source },
    };
  }

  // search_knowledge（也是兜底）
  const res = await ragAnswer(opts.question || '', index, { lang, onDebug: opts.onDebug });
  return { ...res, channel: 'kb' };
}

/** 渲染失败时不让整条回复挂掉 —— 数字渲染出错也要给出一句人话。 */
function renderStatsSafe(data, lang, degraded, wantList) {
  try {
    return renderStats(data, lang, degraded, wantList);
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
      const m = await routeByModel(question, now, lang);
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
