/**
 * 工单**聚合统计**的解析与渲染 —— 回答「今天有几个 P1」这类区间问题。
 *
 * 与 src/tt.js 的分工：
 *   tt.js      → 「这一单现在什么情况」：消息里带单号，取**一行**做规则判定；
 *   本模块     → 「今天有几个 P1」：按 日期/级别/状态/站点 做**聚合**。
 *
 * ## 为什么数字由脚本渲染、不让模型生成
 *
 * 群里同事会把机器人说的话当依据去执行（派单、催单）。模型一旦自由发挥，
 * 「0」可能被说成「没有」，也可能凭语感说成「有几个」——后者是编造。
 * 所以这里所有数字都来自 HTTP 响应或 SQLite 的 COUNT(*)，
 * 模型只负责**选工具、抽参数**，一个数字都不参与。
 *
 * ## 取数在另一个模块
 *
 * 本模块只做**日期/级别/状态的解析**与**结果渲染**，是纯函数，可离线测试。
 * 真正去 HTTP / SQLite 取数的是 src/ttsource.js（2026-10-07 拆出 —— 本文件
 * 一度涨到 605 行，超过 AGENTS.md 第三节原则 2 的 500 行上限）。
 * 拆分的收益很直接：`scripts/test-tools.mjs` 全程离线，跑的就是本模块。
 *
 * ## 时间字段统一用 alarm_occur_time
 *
 * my_app 的 `_time_filter`（backend/routers/tt_wo_dashboard.py:92）过滤的就是它。
 * 两条通道若各用一个字段，「今天有几个 P1」会得到两个不同答案，
 * 那是最难排查的一类故障——两边都"能跑"，只是数对不上。
 */
import { CONFIG } from './config.js';

// 取数层原样转出，调用方仍从本模块 import（ttsource 是内部拆分细节）
export {
  queryTickets,
  fallbackAvailable,
  isOpenStatus,
  siteFromTitle,
} from './ttsource.js';
import { isOpenStatus } from './ttsource.js';

/* ------------------------------- 日期解析 ------------------------------- */

/** Date → 'YYYY-MM-DD'（本地时区，与工单库的口径一致）。 */
export function fmtDate(d) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/**
 * 在 base 上加减天数，返回 'YYYY-MM-DD' 字符串（不修改入参）。
 *
 * 返回字符串而不是 Date 是刻意的：本模块内部**所有**日期都是
 * 'YYYY-MM-DD' 这个形状，中间态若混进 Date 对象，迟早有人忘了 fmtDate
 * 就把它塞进 URL。统一形状后，`a.localeCompare(b)` 直接就能比大小。
 */
export function shiftDate(base, days) {
  const d = new Date(base.getTime());
  d.setDate(d.getDate() + days);
  return fmtDate(d);
}

/**
 * 本周周一（**返回 Date**，不是字符串）。
 *
 * 与 shiftDate 的形状不同是刻意的：这个函数只在 parseDateRange 内部用，
 * 调用方紧接着就要加减天数或 fmtDate，留成 Date 少一次字符串↔Date 往返。
 * getDay() 里周日是 0，换算成 7 才能算对周界（否则周日会被算成下一周）。
 */
function weekStart(d) {
  const dow = d.getDay() === 0 ? 7 : d.getDay();
  const out = new Date(d.getTime());
  out.setDate(out.getDate() - (dow - 1));
  return out;
}

/**
 * 中文星期 → 1..7（周一=1 … 周日/周天=7）。认不出返回 0。
 *
 * 为什么要单独一张表而不是用 Date 解析：`new Date('周五')` 返回 Invalid Date，
 * 而 `new Date('2026-10-09')` 之外的任何中文日期串都不可移植。这里只需要
 * 「第几个星期几」，用一张表最直白。
 */
const WEEKDAY_ZH = { 日: 7, 天: 7, 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6 };
function weekdayNum(ch) {
  return WEEKDAY_ZH[ch] || 0;
}

/**
 * 解析「本周五 / 上周六 / 下周一 / 周五」这类**具体星期几**。
 *
 * ## 为什么必须单独一步
 *
 * 旧实现里「本周五有几个单」会被 `/本周/` 命中，直接返回**整周**区间
 * （2026-10-18 实测：返回 10-05~10-06，即周一至今，而不是周五那一天）。
 * 用户问的是某一天，拿到的是 5~7 天的合计 —— 数字偏大但**不报错**，
 * 属于最难发现的那类错误。同理「上周六」返回的是上周全周。
 *
 * ## 语义约定（与英文侧对齐）
 *
 *   · 本周X → 本周的那一天（若在未来，也照算 —— 用户说的是哪一天就是哪一天）
 *   · 上周X → 上周的该天
 *   · 下周X → 下周的该天
 *   · 裸「周X / 星期X / 礼拜X」→ **最近一个**该天（含今天，向前找）
 *
 * 只认单字星期（周三/星期五/礼拜天）。「周三到周五」这种区间
 * 交给下面的 A~B 逻辑会出错，故明确**不在此处**支持 —— 返回该句的起始日更稳妥。
 */
function parseWeekday(s, now) {
  // 前缀与星期必须**在同一个匹配里**拿到。
  //
  // 走过的弯路（2026-10-18 实测，都失败）：
  //   ① `(…|本周)?\s*(?:周|…)` —— 引擎优先让可选组不参与，「本周五」只匹配到「周五」；
  //   ② 空串作交替分支 `(…|本周|)\s*(?:周|…)` —— 引擎同样先试空分支；
  //   ③ 先匹配「周X」再向左读前缀 —— 「周」匹配到了「**本**周五」的第二个字，
  //      `m.index` 落在「本」之后，向左只剩一个字，前缀永远读不到。
  // 结论：让前缀随 token 一起被正则吃掉，用 `(?<![本上下])` 保证不从词中间起匹配。
  //
  // 关键点是**前缀字符本身不被排他**：`本` 只作为「周」的左邻时才排除，
  // 匹配从 `本` 开始仍然合法（`本周五` 能被完整吃下）。
  //
  // 「礼拜」一律先归一成「星期」再匹配 —— 两者语义完全相同，但多一种词形
  // 就多一条交替分支、多一处优先级陷阱（实测「下礼拜天」会命中后面那个
  // 「礼拜天」，「上上个礼拜一」会漏掉「上上个」）。归一后只剩三种词形，
  // 「上/下/本/这」前缀的表也只需写一份。
  const norm = s.replace(/礼拜/g, '星期');
  const m = norm.match(
    /(上上个星期|上上星期|上上周|上个星期|上星期|上周|上个星期|下个星期|下星期|下周|下一周|上一周|下周|本周|本星期|这周|这个星期|(?<![本上下])周|(?<![本上下])星期)\s*([一二三四五六日天])/
  );
  if (!m) return null;
  const target = weekdayNum(m[2]);
  if (!target) return null;
  const prefix = m[1] || '';

  const ws = weekStart(now);
  let offset = 0;
  // ⚠️ 这里判断的是**归一后**的前缀（「礼拜」已变成「星期」），
  // 所以只写「星期」形态即可。漏掉 `上上个星期` 这个形态时，
  // 「上上个礼拜一」会静默落进"本周"分支，差两周而不报错。
  if (/^上上个星期|^上上星期|^上上周/.test(prefix)) offset = -14;
  else if (/^(上个星期|上星期|上周|上一周)/.test(prefix)) offset = -7;
  else if (/^(下个星期|下星期|下周|下一周)/.test(prefix)) offset = 7;

  if (offset) {
    const d = new Date(ws.getTime());
    d.setDate(d.getDate() + offset + (target - 1));
    const day = fmtDate(d);
    return { start: day, end: day };
  }
  // 其余所有情况（「本周X」「这周X」「星期X」「周X」「礼拜X」）都按**本周的那一天**算。
  //
  // 为什么裸「星期X」不是「最近一个星期X」：
  // 中文里「星期三有几个单」几乎总指**本周三**。旧实现按"向前回溯到最近的周三"
  // 算，于是在周二问「星期三」会得到**上周三**（2026-10-18 实测：问 10-06（周二）
  // 的星期三，返回 09-30）。这种"差一周"的错误不会报错，最难发现。
  // 未来日期照算 —— 用户说的是哪一天就是哪一天，不在日期层面替他做决定。
  const d = new Date(ws.getTime());
  d.setDate(d.getDate() + (target - 1));
  const day = fmtDate(d);
  return { start: day, end: day };
}

/**
 * 中文数字 → 阿拉伯数字（**只用于「近N天」这类数量**，不做全局替换）。
 *
 * 支持 一~九十九（群里实际只会出现 1~30 这类量级）。
 * 为什么不用全局替换：那样会毁掉「12号」「10月12日」里的写法，
 * 也可能把站名里的数字改掉。所以只让调用方在**已定位到的片段**上换。
 */
function zhNumToInt(str) {
  const s = String(str || '').trim();
  if (!s) return NaN;
  if (/^\d+$/.test(s)) return Number(s);
  const DIGIT = { 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
  // 十 / 十五 / 二十 / 二十五 / 三十
  if (s === '十') return 10;
  if (/^十[一二三四五六七八九]$/.test(s)) return 10 + DIGIT[s[1]];
  if (/^[一二两三四五六七八九]十$/.test(s)) return DIGIT[s[0]] * 10;
  if (/^[一二两三四五六七八九]十[一二三四五六七八九]$/.test(s)) {
    return DIGIT[s[0]] * 10 + DIGIT[s[2]];
  }
  if (/^[一二两三四五六七八九]$/.test(s)) return DIGIT[s];
  return NaN;
}

/**
 * 从自然语言里解析日期区间。
 *
 * 支持：今天/昨天/前天/本周/上周/本月/近N天/N天前、
 *       YYYY-MM-DD、YYYY/M/D、YYYY年M月D日、M月D日、N号、以及 A~B 区间。
 *
 * 返回 { start, end }（都是 'YYYY-MM-DD'），解析不出返回 null。
 *
 * ⚠️ 这件事**必须由这里做，不能交给模型**：模型没有时钟，
 * 问它「今天是几号」只能得到瞎猜。日期错了，后面查得再准也是错的答案。
 */
export function parseDateRange(text, now = new Date()) {
  const s = String(text || '');
  const today = fmtDate(now);

  // 相对日
  if (/今天|今日|当天/.test(s)) return { start: today, end: today };
  if (/昨天|昨日/.test(s)) {
    const d = shiftDate(now, -1);
    return { start: d, end: d };
  }
  if (/前天/.test(s)) {
    const d = shiftDate(now, -2);
    return { start: d, end: d };
  }
  // 英文相对日（群里英文提问常见；2026-10-08 实测「how many P1 Tickets for this
  // month」因不认英文日期而落到模型层，2.9s 才答 —— 本应由规则层 60ms 出结果）。
  if (/\b(today|now)\b/i.test(s)) return { start: today, end: today };
  if (/\byesterday\b/i.test(s)) {
    const d = shiftDate(now, -1);
    return { start: d, end: d };
  }

  // 具体星期几（本周五 / 上周六 / 下周一 / 周五）。
  //
  // ⚠️ 必须排在 `/本周/` `/上周/` 之前：那两个分支只认「整周」，
  // 会让「本周五」返回周一至今的整段（2026-10-18 实测），数字偏大而不报错。
  const wd = parseWeekday(s, now);
  if (wd) return wd;

  // 周 / 月
  if (/本周|这周|这一周/.test(s)) {
    return { start: fmtDate(weekStart(now)), end: today };
  }
  if (/上周|上一周/.test(s)) {
    const ws = weekStart(now);
    return { start: shiftDate(ws, -7), end: shiftDate(ws, -1) };
  }
  if (/本月|这个月|当月/.test(s)) {
    const p = (n) => String(n).padStart(2, '0');
    return { start: `${now.getFullYear()}-${p(now.getMonth() + 1)}-01`, end: today };
  }
  if (/上个月|上月/.test(s)) {
    const p = (n) => String(n).padStart(2, '0');
    const first = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const last = new Date(now.getFullYear(), now.getMonth(), 0);
    return { start: fmtDate(first), end: fmtDate(last) };
  }
  // 英文周 / 月（this month / this week / last month / last week）
  const monthStart = () =>
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`;
  if (/\bthis\s+month\b|\bcurrent\s+month\b/i.test(s)) {
    return { start: monthStart(), end: today };
  }
  if (/\blast\s+month\b|\bprevious\s+month\b/i.test(s)) {
    const first = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const last = new Date(now.getFullYear(), now.getMonth(), 0);
    return { start: fmtDate(first), end: fmtDate(last) };
  }
  if (/\bthis\s+week\b|\bcurrent\s+week\b/i.test(s)) {
    return { start: fmtDate(weekStart(now)), end: today };
  }
  if (/\blast\s+week\b|\bprevious\s+week\b/i.test(s)) {
    const ws = weekStart(now);
    return { start: shiftDate(ws, -7), end: shiftDate(ws, -1) };
  }
  // 英文近 N 天：last N days / past N days
  const enRecent = s.match(/\b(?:last|past|recent)\s+(\d{1,3})\s+days?\b/i);
  if (enRecent) {
    const n = Math.max(1, Number(enRecent[1]));
    return { start: shiftDate(now, -(n - 1)), end: today };
  }

  // 近 N 天 / 过去 N 天：含今天，所以往前推 N-1 天。
  //
  // 数字部分同时认阿拉伯与中文（`\d` 之外再收「一二两三…十」构成的 1~99）。
  // 2026-10-18 实测：「最近三天有多少单」返回 start:'' —— 因为 `(\d{1,3})`
  // 压根不匹配「三」，而 `/最近/` 已被这一步消费掉，后面没有分支再兜，
  // 最终带着空日期去查（queryTickets 缺省"不过滤"，会拉全库 3 万多条）。
  // 中文量词的合法范围有限，用 `[\d一二两三四五六七八九十]{1,3}` 收窄，
  // 避免误吃「最近发生的单」这类不含数字的说法。
  const NUM_ZH = '[\\d一二两三四五六七八九十]{1,3}';
  const recent = s.match(new RegExp(`(?:最近|近|过去)\\s*(${NUM_ZH})\\s*(?:天|日)`));
  if (recent) {
    const n = Math.max(1, zhNumToInt(recent[1]));
    if (Number.isFinite(n)) return { start: shiftDate(now, -(n - 1)), end: today };
  }
  // N 天前（同样认中文数字：「三天前」）
  const ago = s.match(new RegExp(`(${NUM_ZH})\\s*天前`));
  if (ago) {
    const n = zhNumToInt(ago[1]);
    if (Number.isFinite(n)) {
      const d = shiftDate(now, -n);
      return { start: d, end: d };
    }
  }

  // 完整日期 YYYY-MM-DD / YYYY/M/D / YYYY年M月D日
  const full = [...s.matchAll(/(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?/g)];
  if (full.length) {
    const mk = (m) =>
      `${m[1]}-${String(m[2]).padStart(2, '0')}-${String(m[3]).padStart(2, '0')}`;
    if (full.length >= 2) return { start: mk(full[0]), end: mk(full[1]) };
    const d = mk(full[0]);
    return { start: d, end: d };
  }

  // 月日（当年）：M月D日 / M-D / M/D
  const md = s.match(/(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?/);
  if (md) {
    const d = `${now.getFullYear()}-${String(md[1]).padStart(2, '0')}-${String(md[2]).padStart(2, '0')}`;
    return { start: d, end: d };
  }
  // N 号（当月）
  const dayNo = s.match(/(\d{1,2})\s*号/);
  if (dayNo) {
    const d = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(dayNo[1]).padStart(2, '0')}`;
    return { start: d, end: d };
  }

  return null;
}

/**
 * 级别：P1~P4（大小写与空格不敏感）。
 *
 * 多个 P 数字（如「P1 和 P2」「P1/P2」）时**返回 null**：单个 P 会让规则层
 * 误判为「只查 P1」，而「各有几个」的本意是分别统计两组。
 * 弃权 → 上层交模型层抽参，模型能看到完整上下文。
 * 2026-10-08 深度测试发现「P1 和 P2 各有几个」答成 P1 单数，**沉默错误**。
 */
export function parseSeverity(text) {
  const all = [...String(text || '').matchAll(/\bP\s*([1-4])\b/gi)];
  if (!all.length) return null;
  if (all.length > 1) return null;  // 多个 P：弃权，不让规则层挑一个瞎答
  return `P${all[0][1]}`;
}

/**
 * 用户是否明确要**单号列表**。
 *
 * 「本月有几个 P1」只要个数；「本月有几个 P1，**请输出TT单的ID给我**」
 * 要的是名单。两者的取数代价差很多：
 *   · 只要个数 → overview 一次轻量聚合；
 *   · 要名单   → 必须 drilldown 把符合条件的行全捞回来。
 * 所以必须先分清，不能一律按"要名单"处理（本月 P2 有几百条）。
 *
 * 2026-10-07 实测漏判：「本月有几个P1的单子，请输出TT单的ID给我」
 * 只回了「P1 单 6 个」——用户明确要 ID，却一个都没给。
 *
 * 2026-10-08 实测：英文侧只认干巴巴的 `list`，自然说法
 * （give me the ticket IDs / show me the tickets / which tickets）不触发，
 * 用户问「how many P1 Tickets for this month」只拿到 3 个样例单号，
 * 反问「为什么只给我3个TT」。故补齐英文说法。
 *
 * 2026-10-08 二修：「sent me the p1 tickets list for this month」仍没触发 ——
 * ① 动词是 `sent`（不是 send/send me）；② `list` 在 `tickets` **后面**
 *    （旧式样 `list ... ticket` 只认 list 在前）。故改为**双向**：`list` 与
 *    ticket 词在同一句里出现即可（不再要求前后顺序），并补 sent/wanna。
 *
 * 2026-10-18 三修（qa_log 2026-10-16T23:04 实测）：中文侧的「发下 / 发一下」
 * 完全没被认出来 —— 「给我发下本周的P1故障单」list=false，于是一句明确要单号的
 * 话只回了「P1 单 1 个」，一个单号都没给。
 * 「号码」更糟：「给我发下本周的P1故障单的号码」list=false 且未被剥词，
 * 规则层弃权后模型把 **号码** 当成工单号去调 analyze_ticket，答了个空。
 * 故补：发下/发一下/发来/输出/列出来 + 号码（「号码」单独出现不算，
 * 必须与 ticket 词同句，见 LIST_INTENT_PAIR —— 否则「告警码 99933 的号码」
 * 这类查表问法会被误判成要名单）。
 */
const LIST_INTENT =
  /(单号|单的\s*id|的\s*id|编号|号码|列出|列一下|列出来|清单|明细|发下|发一下|发来|具体是哪|哪几单|哪些单|哪些是|有哪些|给我单|(?:give|send|show|sends?|sent|provide|list|want|wanna)\s+(?:me\s+)?(?:the\s+)?(?:ticket|tt|list|id)|\bwhich\s+(?:ticket|tt|one)s?\b|\bticket\s*(?:id|no)s?\b|\btt\s*no\b|\ball\s+(?:the\s+)?(?:ticket|tt)s?\b|\bid\s+list\b|\bthe\s+ids?\b|\bwhat\s+are\s+(?:the\s+)?[^?]*\b(?:ticket|tt)s?)/i;

// 只要句子里**同时**出现「list/enumerate」类词与「ticket/tt/p1-4」，
// 就认定用户要名单（不要求先后顺序）—— 覆盖「... tickets list ...」
// 「... list the tickets」两种语序。
const LIST_INTENT_PAIR =
  /(?=[^?]*\b(?:list|enumerate|ids?)\b)(?=[^?]*\b(?:ticket|tt|p[1-4])\b)/i;

export function parseListIntent(text) {
  const s = String(text || '');
  // 主正则命中 或 「list/ids + ticket」成对出现（不看语序）
  return LIST_INTENT.test(s) || LIST_INTENT_PAIR.test(s);
}

/** 闭环状态：默认 all（不加条件），只有明确说未闭环/已闭环才过滤。 */
export function parseStatus(text) {
  const s = String(text || '');
  if (/未闭环|没闭环|没有闭环|未关闭|没关闭|未处理|没处理|还没|仍在|未完成|open\b|unresolved/i.test(s)) {
    return 'open';
  }
  if (/已闭环|已关闭|已完成|closed\b|resolved/i.test(s)) return 'closed';
  return 'all';
}

/**
 * 领域关键字过滤（如「Fiber issues related TTs」里的 Fiber）。
 *
 * ## 为什么必须有这个
 *
 * 2026-10-26 群里实测（同一分钟连问两句）：
 *
 * ```
 * How many Fiber issues related TTs for last 7 days?  → 753 ticket(s)
 * How many  TTs in last 7 days?                       → 753 ticket(s)
 * ```
 *
 * 两句数一模一样 —— **Fiber 这个条件被整个丢掉了**。根因在路由层：
 * `leftoverTerms` 剥完日期/级别/工单同义词后剩下 `["Fiber","related","TTs"]`，
 * 判定为「有额外条件」，规则层弃权交模型层；而 `query_tickets` 的参数表里
 * **压根没有关键字这一项**，模型就算看懂了「Fiber」也无处可填，
 * 只能回一个全网总数，且回复里不带任何「条件没生效」的提示。
 *
 * 这与 README 第三节「答错不如弃权」是同一类故障：宁可不答，也不能
 * 把「全网 753」当成「Fiber 相关 753」发到群里。
 *
 * ## 只认已知的领域词表
 *
 * 不做「任意陌生英文词都当关键字」—— 那样会把站名（Wood camp）也当成
 * 关键字去 LIKE，结果是 0 单，比现在更糟。站名有 `site` 参数单独走。
 * 词表只收**工单正文里确有取值**的告警族（实测 DB：
 * title 277 行 / description 413 行 / alarm_description 249 行含 "fiber"）。
 *
 * @param {string} text 原始提问
 * @returns {string} 关键字（首个大写形式原样返回），或 ''
 */
export const KEYWORD_TERMS = [
  // 词表按「最具体 → 最泛化」排列，先命中先返回
  ['Fiber Break', /fiber\s*break|光纤断|光缆断/i],
  ['Fiber', /fiber|光纤|光缆/i],
  ['Microwave', /\bmicrowave\b|\bMW\s+link|\bMWL\b|微波/i],
  ['Power', /\bpower\b|电源|发电机/i],
  ['Transmission', /\btransmission\b|传输/i],
  ['Congestion', /\bcongestion\b|拥塞/i],
];

export function parseKeyword(text) {
  const s = String(text || '');
  for (const [term, re] of KEYWORD_TERMS) {
    if (re.test(s)) return term;
  }
  return '';
}

/* -------------------------------- 渲染 -------------------------------- */

/** 把 status 分桶压成一行人话；只取前 3 个，避免刷屏。 */
function statusLine(statusMap, lang) {
  const entries = Object.entries(statusMap || {})
    .filter(([, v]) => Number(v) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 3);
  if (!entries.length) return '';
  const label = lang === 'en' ? 'Status' : '状态';
  const colon = lang === 'en' ? ': ' : '：';
  const sep = lang === 'en' ? ', ' : '、';
  return `${label}${colon}${entries.map(([k, v]) => `${k} ${v}`).join(sep)}`;
}

/**
 * 渲染查询结果。
 *
 * 所有数字都来自 data（HTTP 响应或 SQLite COUNT），**未经模型加工**。
 *
 * @param {object} data       queryTickets 返回的 data
 * @param {'zh'|'en'} lang
 * @param {boolean} degraded  是否走了 SQLite 降级（是则标注口径）
 * @param {boolean} wantList  用户是否点名要单号列表（决定列表标签与条数上限）
 * @param {boolean} dateGuessed 日期是兜底成"今天"的（谁都没给）—— 加一句说明
 */
export function renderStats(
  data,
  lang = 'zh',
  degraded = false,
  wantList = false,
  dateGuessed = false
) {
  const T = {
    zh: {
      range: (s, e) => (s === e ? `${s}` : `${s} ~ ${e}`),
      // 有领域关键字时，标签必须带上它 —— 「753 个工单」与
      // 「Fiber 相关工单 753 个」是两个不同的事实，标签不写就成了前者。
      found: (n, sev, kw) =>
        kw ? `「${kw}」相关工单 ${n} 个` : sev ? `${sev} 单 ${n} 个` : `工单 ${n} 个`,
      amongOpen: (n) => `其中未闭环 ${n} 个`,
      openLabel: '未闭环',
      sevPart: '级别分布',
      sample: '最近几单',
      // 用户点名要单号时，标题得换一个 —— 「最近几单」听着像顺带给的，
      // 而他要的就是这个列表。
      list: '单号',
      more: (n) => `（还有 ${n} 单未列出）`,
      stale: '（本地副本口径，可能有同步延迟）',
      noDetail: '（这次没能取到单号明细，可以到看板上按级别下钻查看。）',
      guessed: '（提问里没给日期，按今天算的；要别的区间请说清楚日期）',
      // 标点必须按语言取：英文回复里出现「：」「（」「、」是实打实的漏翻
      //（2026-10-08 实测：英文问「P1 tickets this month」回的是
      // 「Latest：TT...（Cooper Hill）、...」—— 标签是英文、标点是中文）。
      colon: '：',
      sep: '、',
      paren: (s) => `（${s}）`,
      // 站点+0 单：必须点明是**工单**为 0，别被读成「该站没告警/没问题」。
      siteZero: (site) => `工单${'：'}0（站点 ${site}；这是工单数量，不代表该站没有告警，查告警请直接问「${site} 有没有告警」）`,
    },
    en: {
      range: (s, e) => (s === e ? `${s}` : `${s} ~ ${e}`),
      found: (n, sev, kw) =>
        kw ? `${n} ticket(s) matching "${kw}"` : sev ? `${n} ${sev} ticket(s)` : `${n} ticket(s)`,
      amongOpen: (n) => `of which ${n} still open`,
      openLabel: 'open',
      sevPart: 'By severity',
      sample: 'Latest',
      list: 'Ticket IDs',
      more: (n) => ` (+${n} more not listed)`,
      stale: '(from the local replica — may lag behind live data)',
      noDetail: '(Ticket IDs unavailable for this query — the detail view returned none.)',
      guessed: '(no date in the question — assumed today; give a date for another range)',
      colon: ': ',
      sep: ', ',
      paren: (s) => ` (${s})`,
      siteZero: (site) => `tickets: 0 (site ${site}; this is a ticket count, not an alarm status — ask "${site} alarms" for live alarms)`,
    },
  }[lang];

  const range = data.start ? T.range(data.start, data.end || data.start) : '';
  const lines = [];

  if (data.total === 0) {
    // 「今天有 P1 吗」的正确答案是「P1：0 个」，不是一句「查不到工单」——
    // 后者会被理解成"查询失败"或"这条件有问题"。
    // 这里必须把级别说全，否则用户不知道 0 指的是什么为 0。
    // 站点+0 单是**最高危的误读**：用户问站，看到「0」会以为"该站没事"。
    // 其实这里 0 说的是**匹配到的工单数**，与告警状态是两回事。
    // 所以站点非空时用专门的措辞把边界讲清楚（见 T.siteZero）。
    if (data.site && !data.severity) {
      return [range, T.siteZero(data.site)].filter(Boolean).join('\n');
    }
    const cond = [data.status === 'open' ? T.openLabel : '', data.site || ''].filter(Boolean);
    let body;
    if (lang === 'en') {
      body = data.keyword
        ? `tickets matching "${data.keyword}"${T.colon}0`
        : data.severity ? `${data.severity}${T.colon}0` : `tickets${T.colon}0`;
    } else {
      body = data.keyword
        ? `「${data.keyword}」相关工单${T.colon}0 个`
        : data.severity ? `${data.severity}${T.colon}0 个` : `工单${T.colon}0 个`;
    }
    return [range, cond.length ? `${body}${T.paren(cond.join(T.sep))}` : body].filter(Boolean).join('\n');
  }

  lines.push(`${range} ${T.found(data.total, data.severity, data.keyword)}`.trim());
  // 「6 个」和「未闭环 1 个」并列容易读成"6 个里只有 1 个没闭环"，
  // 但两者其实是同一批单的两个侧面：总数 6、其中 1 个还没闭环。
  // 补一个「其中」把关系说死，省掉一次误读。
  if (data.status === 'all' && data.open != null && data.open !== data.total) {
    lines.push(T.amongOpen(data.open));
  }

  const sevMap = data.by_severity || {};
  // 已经按单个级别过滤时，再列一次「级别分布」是废话 —— 只在全量查询时给。
  //
  // 2026-10-14 实测：今天只有 P3/P2/P4 三个级别有量、P1=0，旧实现会跳过
  // 该级别不显示，于是群里的同事看不到「P1 0」这一行，被反推为「P1 缺一张
  // 没统计」，有歧义。改为全量查询时永远把 P1~P4 列出来，缺的补 0，**顺序
  // 固定**（P1→P4），让消息像 KPI 看板一样稳定可对账。
  if (!data.severity) {
    const sevOrder = ['P1', 'P2', 'P3', 'P4'];
    const line = sevOrder
      .map((k) => `${k} ${Number(sevMap[k] || 0)}`)
      .join(T.sep);
    lines.push(`${T.sevPart}${T.colon}${line}`);
  }
  if (data.by_status) {
    const st = statusLine(data.by_status, lang);
    if (st) lines.push(st);
  }

  // 单号列表：用户点名要 ID 时给到 ttStatsListLimit，否则只作「最近几单」的抓手。
  const limit = wantList
    ? Number(CONFIG.ttStatsListLimit ?? 10)
    : Number(CONFIG.ttStatsSampleLimit ?? 3);
  const samples = (data.samples || []).slice(0, limit);
  if (samples.length) {
    // 状态混合时才逐条标「未闭环」，否则是噪声（见 openMark 注释）
    const mark = hasMixedStatus(samples);
    lines.push(
      `${wantList ? T.list : T.sample}${T.colon}${samples
        .map(
          (s) =>
            `${s.tt_no}${s.site_name ? T.paren(s.site_name) : ''}${mark ? openMark(s, lang) : ''}`
        )
        .join(T.sep)}`
    );
    // 明确告诉用户"列表被截断了"，否则他会以为一共就这几单
    const rest = Number(data.detail_total || data.total || 0) - samples.length;
    if (wantList && rest > 0) lines.push(T.more(rest));
  } else if (wantList && data.severity) {
    // 走 overview 时拿不到明细（不该发生，但真发生了要说清楚，
    // 而不是让用户对着"6 个"却看不到单号发懵）
    lines.push(T.noDetail);
  }
  if (degraded) lines.push(T.stale);
  if (dateGuessed) lines.push(T.guessed);
  return lines.join('\n');
}

/**
 * 单号后面的闭环标记 —— 只在**这批单里两种状态都有**时才标。
 *
 * ## 为什么必须标
 *
 * 2026-10-07 实测：回复了「P1 单 6 个 / 其中未闭环 1 个 / 单号：…（六个）」
 * 之后，用户立刻追问「那个单子未闭环」——因为回复只说了**有 1 个**，
 * 没说**是哪个**。名单都打出来了，状态却藏着，用户只能再问一次。
 *
 * ## 为什么不是无条件标
 *
 * 全部未闭环（或全部已闭环）时，每行都缀一个同样的词是噪声：
 * 上面那句「其中未闭环 1 个」已经把话说尽了。只在**混合**时才逐条区分。
 */
function openMark(sample, lang) {
  const open = isOpenStatus(sample.status);
  return open ? (lang === 'en' ? ' [open]' : '［未闭环］') : '';
}

/** 这批样例里是否同时存在未闭环与已闭环（决定要不要逐条标状态）。 */
function hasMixedStatus(samples) {
  const opens = samples.filter((s) => isOpenStatus(s.status)).length;
  return opens > 0 && opens < samples.length;
}
