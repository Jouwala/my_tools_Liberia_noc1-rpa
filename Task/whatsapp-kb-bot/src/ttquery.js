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
export { queryTickets, fallbackAvailable, isOpenStatus, siteFromTitle } from './ttsource.js';

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

  // 近 N 天 / 过去 N 天：含今天，所以往前推 N-1 天
  const recent = s.match(/(?:最近|近|过去)\s*(\d{1,3})\s*(?:天|日)/);
  if (recent) {
    const n = Math.max(1, Number(recent[1]));
    return { start: shiftDate(now, -(n - 1)), end: today };
  }
  // N 天前
  const ago = s.match(/(\d{1,3})\s*天前/);
  if (ago) {
    const d = shiftDate(now, -Number(ago[1]));
    return { start: d, end: d };
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

/** 级别：P1~P4（大小写与空格不敏感）。 */
export function parseSeverity(text) {
  const m = String(text || '').match(/\bP\s*([1-4])\b/i);
  return m ? `P${m[1]}` : null;
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
 */
const LIST_INTENT =
  /(单号|单的\s*id|的\s*id|编号|列出|列一下|list|清单|明细|具体是哪|哪几单|哪些单|哪些是|有哪些|ticket\s*id|tt\s*no|id\s*给|给我单)/i;

export function parseListIntent(text) {
  return LIST_INTENT.test(String(text || ''));
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

/* -------------------------------- 渲染 -------------------------------- */

/** 把 status 分桶压成一行人话；只取前 3 个，避免刷屏。 */
function statusLine(statusMap, lang) {
  const entries = Object.entries(statusMap || {})
    .filter(([, v]) => Number(v) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 3);
  if (!entries.length) return '';
  const label = lang === 'en' ? 'Status' : '状态';
  return `${label}：${entries.map(([k, v]) => `${k} ${v}`).join('、')}`;
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
 */
export function renderStats(data, lang = 'zh', degraded = false, wantList = false) {
  const T = {
    zh: {
      range: (s, e) => (s === e ? `${s}` : `${s} ~ ${e}`),
      found: (n, sev) => (sev ? `${sev} 单 ${n} 个` : `工单 ${n} 个`),
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
    },
    en: {
      range: (s, e) => (s === e ? `${s}` : `${s} ~ ${e}`),
      found: (n, sev) => (sev ? `${n} ${sev} ticket(s)` : `${n} ticket(s)`),
      amongOpen: (n) => `of which ${n} still open`,
      openLabel: 'open',
      sevPart: 'By severity',
      sample: 'Latest',
      list: 'Ticket IDs',
      more: (n) => ` (+${n} more not listed)`,
      stale: '(from the local replica — may lag behind live data)',
      noDetail: '(Ticket IDs unavailable for this query — the detail view returned none.)',
    },
  }[lang];

  const range = data.start ? T.range(data.start, data.end || data.start) : '';
  const lines = [];

  if (data.total === 0) {
    // 「今天有 P1 吗」的正确答案是「P1：0 个」，不是一句「查不到工单」——
    // 后者会被理解成"查询失败"或"这条件有问题"。
    // 这里必须把级别说全，否则用户不知道 0 指的是什么为 0。
    const what = data.severity ? `${data.severity}：0 个` : `工单：0 个`;
    const cond = [data.status === 'open' ? T.openLabel : '', data.site || ''].filter(Boolean);
    return [range, cond.length ? `${what}（${cond.join('、')}）` : what].filter(Boolean).join('\n');
  }

  lines.push(`${range} ${T.found(data.total, data.severity)}`.trim());
  // 「6 个」和「未闭环 1 个」并列容易读成"6 个里只有 1 个没闭环"，
  // 但两者其实是同一批单的两个侧面：总数 6、其中 1 个还没闭环。
  // 补一个「其中」把关系说死，省掉一次误读。
  if (data.status === 'all' && data.open != null && data.open !== data.total) {
    lines.push(T.amongOpen(data.open));
  }

  const sevEntries = Object.entries(data.by_severity || {}).filter(([, v]) => Number(v) > 0);
  // 已经按单个级别过滤时，再列一次「级别分布」是废话 —— 只在全量查询时给。
  if (sevEntries.length && !data.severity) {
    lines.push(`${T.sevPart}：${sevEntries.map(([k, v]) => `${k} ${v}`).join('、')}`);
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
    lines.push(
      `${wantList ? T.list : T.sample}：${samples
        .map((s) => `${s.tt_no}${s.site_name ? `（${s.site_name}）` : ''}`)
        .join('、')}`
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
  return lines.join('\n');
}
