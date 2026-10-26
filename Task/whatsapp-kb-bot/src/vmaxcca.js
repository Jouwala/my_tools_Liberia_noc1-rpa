/**
 * VMAX CCA 用户查询通道 —— 「TEL <号码>[，<截止时间>]」→ XDR CCA 投诉信息。
 *
 * ## 场景（2026-10-25 需求）
 *
 * 群成员发「TEL 231773777115，2026-10-25 10:07」，机器人按「截止时间往前
 * 60 分钟」的窗口查 VMAX CCA，按固定模板回：
 *   XDR CCA / MSISDN / IMSI / IMEI / Model / Total traffic /
 *   Track Cells / Cell Name / Lat, Lon / Root Cause Analysis
 * 字段名沿用需求方给的英文标签 —— 它们是 CCA 页面上的领域标识符，与
 * TT 通道「规则名不翻译」同一口径；界面说明句仍按提问语言中英各一份。
 *
 * ## 为什么单独开一条通道（而不是塞进 RAG / 查表）
 *
 * 答案在 VMAX 实时接口里，不在语料里 —— 与工单统计/站点告警同一理由。
 * 且「TEL 231773777115」里的 12 位长数字会被查表意图当成告警码
 * （tools.js 的 extractAlarmCode 认 ≥4 位数字），必须在它**之前**截住，
 * 否则只回一句「码表里没有」，号码与时间全丢。
 *
 * ## 数据链路
 *
 * my_app 已有只读透传接口 GET /api/vmax-cca-query?msisdn=&start=&end=
 * （backend/routers/vmax_cca_query.py → backend/services/vmax_cca/），返回
 * {msisdn, found, user, terminal, window, flow, cells, causes, failures, msg}。
 * 机器人与 my_app 同机，走 127.0.0.1 回环；main.py 的会话中间件对真实本机
 * 回环放行（backend/security.py 的 client_is_local）—— 与工单统计通道同一条
 * 路，不另配凭据，机器人侧也不碰 VMAX 密码。
 *
 * 没有 SQLite 降级：XDR 数据没有本地副本，my_app / VMAX 不可用时**如实说
 * 查不了**（与站点告警通道同一原则：绝不把「查不了」伪装成「查无此号」）。
 *
 * ## 号码归一（normalizeLiberiaMsisdn）
 *
 * 现场写法五花八门：231 77 377 7115 / 77 377 7115 / 07737777115 / +231773777115。
 * VMAX 服务端只认 231 开头的 12 位完整号码（services/vmax_cca/README.md 第 2 节
 * 真号实测：剥成 9 位返回 IMSI is not found），所以这里统一归一成 12 位。
 * 规则层判据锚在 TEL/MSISDN 关键字上，不会把告警码之类的长数字误当号码。
 *
 * ## 时间窗
 *
 * 截止时间未给 → 按当前时刻；窗口恒为 60 分钟（CCA_WINDOW_MIN，需求约定）。
 * 支持的写法：2026-10-25 10:07 / 10:07:30 / 2026/10/25 10:07 /
 * 2026年10月25日 10:07 / 仅时刻 10:07（按当天）/ 仅日期 2026-10-25（按当天
 * 23:59，CCA 日界惯例，见 vmax_cca_client.normalize_window）。
 * 时间是兜底猜出来的必须在回复里说清（「按当前时刻算的」），不能装作用户给的
 * —— 与统计通道 dateGuessed 同一纪律。
 */
import { CONFIG } from './config.js';

/** 查询窗口宽度（分钟）。需求约定：截止时间往前 60 分钟。 */
export const CCA_WINDOW_MIN = 60;

/** 小区列表最多列几个 —— 全列会刷屏（实测一天 41 个小区）。 */
const MAX_CELLS_LISTED = 8;
/** 根因最多列几条 —— 实测一天 16~59 条，全列没人读得完；只带置信度最高的前几条。 */
const MAX_CAUSES_LISTED = 3;
/** 单行截断长度（根因的处理建议可能很长）。 */
const LINE_BUDGET = 200;

const TIMEOUT_MS = Number(
  process.env.VMAX_CCA_TIMEOUT_MS ?? CONFIG.vmaxCcaTimeoutMs ?? 240000
);

/* ------------------------------- 号码归一 ------------------------------- */

/**
 * 把现场各种写法的利比里亚手机号归一成 VMAX 认的 231 开头 12 位格式。
 *
 * 规则（不猜、不静默截断；形状对不上就原样透传，让上游用
 * 「IMSI is not found」如实回答，比这边悄悄改错强）：
 *   · 231 开头且 12 位            → 原样（完整格式）；
 *   · 本地 8~10 位（可带前导 0）   → 剥前导 0 后补 231；
 *   · 国际冠码 00231…             → 剥 00 后按上面两条走；
 *   · 其他形状                    → 原样透传。
 */
export function normalizeLiberiaMsisdn(raw) {
  let d = String(raw || '').replace(/\D/g, '');
  if (!d) return '';
  if (d.startsWith('00')) d = d.replace(/^0+/, '');
  if (d.length === 12 && d.startsWith('231')) return d;
  if (d.length >= 8 && d.length <= 10 && !d.startsWith('231')) {
    return '231' + d.replace(/^0+/, '');
  }
  return d;
}

/* ------------------------------- 时间解析 ------------------------------- */

/** Date → 'YYYY-MM-DD HH:mm'（本地时区，与 CCA 页面同一基准，不用 UTC）。 */
export function fmtDateTime(d) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/**
 * 从一段文本里解析「截止时间」。
 *
 * 三档优先级：完整日期时间 > 仅日期 > 仅时刻。都认不出返回 null。
 * 日期分隔符支持 - / . 年月日；冒号兼容全角（先归一成半角再匹配，
 * 中文输入法打出来的 10：07 是真实出现过的写法）。
 *
 * @returns {{end: Date, given: boolean}|null} given=false 表示是当天兜底
 */
export function parseCcaEndtime(text, now = new Date()) {
  const s = String(text || '').replace(/：/g, ':');
  if (!s) return null;

  // ① 完整日期时间：2026-10-25 10:07[:30] / 2026年10月25日 10:07 / 2026/10/25 10:07
  const dt = s.match(
    /(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})[日T\s]*(\d{1,2}):(\d{2})(?::(\d{2}))?/
  );
  if (dt) {
    const end = new Date(
      +dt[1], +dt[2] - 1, +dt[3], +dt[4], +dt[5], dt[6] ? +dt[6] : 0
    );
    const sane =
      +dt[2] >= 1 && +dt[2] <= 12 && +dt[3] >= 1 && +dt[3] <= 31 &&
      +dt[4] <= 23 && +dt[5] <= 59;
    if (sane && !Number.isNaN(end.getTime())) return { end, given: true };
  }

  // ② 仅日期：2026-10-25 → 按当天 23:59（CCA 日界惯例；60 分钟窗口落在
  //    日尾。用户只给日期时没有更自然的时刻可猜，猜了必须可见 —— endText
  //    会原样回显在窗口行里，用户能一眼看出窗口落在哪）。
  const day = s.match(/(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?/);
  if (day) {
    const end = new Date(+day[1], +day[2] - 1, +day[3], 23, 59, 0);
    const sane = +day[2] >= 1 && +day[2] <= 12 && +day[3] >= 1 && +day[3] <= 31;
    if (sane && !Number.isNaN(end.getTime())) return { end, given: true };
  }

  // ③ 仅时刻：10:07 → 当天。前导断言保证不匹配日期片段或号码的一部分。
  const tm = s.match(/(?:^|[^\d:/])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d:])/);
  if (tm) {
    const h = +tm[1], m = +tm[2];
    if (h <= 23 && m <= 59) {
      const end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), h, m, tm[3] ? +tm[3] : 0);
      return { end, given: true };
    }
  }
  return null;
}

/* --------------------------- 规则层意图识别 --------------------------- */

/** TEL / MSISDN 关键字（「看到 TEL 就是查 CCA」是需求方与群的约定）。 */
const CCA_KEYWORD = /(?:^|[^A-Za-z])(?:tel|msisdn)\b/i;

/**
 * 规则层解析「TEL <号码>[，<截止时间>]」。
 *
 * 步骤：先把时间片段从句子里摘掉（避免「TEL 231773777115 2026-10-25 10:07」
 * 里日期的数字被并进号码），再取 TEL/MSISDN 关键字后面的数字串。
 *
 * @returns {{msisdn:string, end:Date, start:Date, timeGiven:boolean,
 *            startText:string, endText:string}|null}
 *   null = 不是 CCA 意图（无关键字，或号码位数不够 7 位）。
 */
export function parseVmaxCcaIntent(question, now = new Date()) {
  const raw = String(question || '');
  if (!CCA_KEYWORD.test(raw)) return null;

  // 摘掉时间片段（仅当它出现在句子里才摘，别把号码里的数字弄丢）
  let rest = raw.replace(/：/g, ':');
  const tm = parseCcaEndtime(raw, now);
  let end;
  let timeGiven = false;
  if (tm) {
    end = tm.end;
    timeGiven = true;
    rest = rest.replace(/(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})[日T\s]*(\d{1,2}):(\d{2})(?::(\d{2}))?/, ' ')
      .replace(/(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?/, ' ')
      .replace(/(?:^|[^\d:/])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d:])/, ' ');
  } else {
    end = now;
  }

  // TEL/MSISDN 关键字后面的号码串（数字 + 空格/横线/括号等分隔）
  const kw = rest.match(CCA_KEYWORD);
  if (!kw) return null;
  const after = rest.slice((kw.index || 0) + kw[0].length);
  const num = after.match(/^[\s:=（(\-]*((?:\d[\s\-().]*){7,15})/);
  if (!num) return null;
  const digits = num[1].replace(/\D/g, '');
  if (digits.length < 7 || digits.length > 15) return null;

  const msisdn = normalizeLiberiaMsisdn(digits);
  const start = new Date(end.getTime() - CCA_WINDOW_MIN * 60 * 1000);
  return {
    msisdn,
    end,
    start,
    timeGiven,
    startText: fmtDateTime(start),
    endText: fmtDateTime(end),
  };
}

/* -------------------------------- 文案 -------------------------------- */

const T = {
  zh: {
    header: (msisdn, win) => `XDR CCA：${msisdn} ｜ 窗口 ${win.start} ~ ${win.end}`,
    windowNote: (t) => `（未给截止时间，按 ${t} 往前 ${CCA_WINDOW_MIN} 分钟查询）`,
    moreCells: (n) => `…（还有 ${n} 个小区未列出）`,
    advice: (s) => `建议：${s}`,
    noCause: '—（该窗口无根因记录）',
    causeFail: '—（根因子查询失败，见文末说明）',
    notFound: (msisdn, msg) =>
      `VMAX CCA 里查不到号码 ${msisdn}${msg ? `（上游返回：${msg}）` : ''}。\n` +
      `请核对号码 —— 需 231 开头的完整 12 位号码；本地 9 位号我会自动补 231。`,
    unavailable:
      'VMAX CCA 查询暂不可用（my_app 没起、未配置 myAppApiBase，或该工具被关闭）。请到 my_app 的「VMAX 用户查询」页查询。',
    error: (d) => `查 VMAX CCA 时出错了${d ? `：${d}` : ''}。请稍后再试。`,
    usage:
      '想查 CCA 请这样发：TEL 231773777115，2026-10-25 10:07\n' +
      '（时间可不填，默认查当前时刻往前 60 分钟；号码写 77 377 7115 这类本地格式也行）。',
    failures: (list) => `⚠ 部分子查询失败：${list}`,
    source: '来源：VMAX CCA（经 my_app 实时查询）',
  },
  en: {
    header: (msisdn, win) => `XDR CCA: ${msisdn} | window ${win.start} ~ ${win.end}`,
    windowNote: (t) => `(no end time given — queried ${CCA_WINDOW_MIN} min back from ${t})`,
    moreCells: (n) => `…(+${n} more cells not listed)`,
    advice: (s) => `Advice: ${s}`,
    noCause: '—(no cause records in this window)',
    causeFail: '—(cause sub-query failed, see note below)',
    notFound: (msisdn, msg) =>
      `Number ${msisdn} was not found in VMAX CCA${msg ? ` (upstream says: ${msg})` : ''}.\n` +
      `Please double-check — VMAX needs the full 12-digit number starting with 231; ` +
      `I auto-prepend 231 to 9-digit local numbers.`,
    unavailable:
      'VMAX CCA query is unavailable right now (my_app down, myAppApiBase not set, or this tool is disabled). Please use the "VMAX User Query" page in my_app.',
    error: (d) => `Something went wrong querying VMAX CCA${d ? `: ${d}` : ''}. Please try again shortly.`,
    usage:
      'To query CCA send: TEL 231773777115, 2026-10-25 10:07\n' +
      '(time is optional — defaults to the last 60 minutes from now; local formats like 77 377 7115 also work).',
    failures: (list) => `⚠ Some sub-queries failed: ${list}`,
    source: 'Source: VMAX CCA (live via my_app)',
  },
};

/* -------------------------------- 渲染 -------------------------------- */

/** 数组值扁平化：去掉 '--' 占位与空串（上游查无数据时全字段都是 '--'）。 */
function arrVals(arr) {
  if (!Array.isArray(arr)) return [];
  return arr
    .flat(2)
    .map((x) => String(x ?? '').trim())
    .filter((s) => s && s !== '--');
}

function trunc(s, n) {
  const t = String(s || '');
  return t.length <= n ? t : t.slice(0, n) + '…';
}

/** 坐标：缺的一侧显示 —（不能显示成 0，那是另一个位置）。 */
const fmtCoord = (v) => (v == null || v === '' ? '—' : String(v));

/**
 * 把 /api/vmax-cca-query 的响应渲染成群消息（纯函数，可离线测试）。
 *
 * @param {object} data 接口响应
 * @param {'zh'|'en'} lang
 * @param {object} ctx { msisdn, timeGiven, nowText, win: {start, end} }
 */
export function renderCcaResult(data, lang, ctx = {}) {
  const t = T[lang] || T.zh;
  const msisdn = String(ctx.msisdn || data?.msisdn || '');
  const win = ctx.win || {
    start: String(data?.window?.starttime || '').slice(0, 16),
    end: String(data?.window?.endtime || '').slice(0, 16),
  };

  if (!data?.found) {
    // 查无此号是**明确结论**（真去 VMAX 查过了），answered=true 才能进会话历史。
    return { answered: true, text: t.notFound(msisdn, String(data?.msg || '')) };
  }

  const user = data.user || {};
  const terminal = data.terminal || {};
  const imsi = arrVals(user.imsi_arr).join('; ') || String(user.imsi || '').trim();
  const imei = arrVals(terminal.imei_arr).join('; ');
  const modelName = arrVals(terminal.modelname_arr).join('; ');
  const modelVendor = arrVals(terminal.modelvendor_arr).join('; ');
  const model = modelName && modelVendor
    ? `${modelName}（${modelVendor}）`
    : modelName || modelVendor;

  const cells = Array.isArray(data.cells?.cells) ? data.cells.cells : [];
  const names = cells.map((c) => String(c?.cellname || '').trim()).filter(Boolean);
  const coords = cells
    .filter((c) => c?.celllat != null || c?.celllon != null)
    .map((c) => `(${fmtCoord(c.celllat)}, ${fmtCoord(c.celllon)})`);

  const lines = [
    t.header(msisdn, win),
    `MSISDN: ${msisdn || '—'}`,
    `IMSI: ${imsi || '—'}`,
    `IMEI: ${imei || '—'}`,
    `Model: ${model || '—'}`,
    // flow 为 null 是业务正常（多数用户无 DPI 记录），如实显示 —
    `Total traffic: ${data.flow ? String(data.flow.total_flux ?? '—') : '—'}`,
    `Track Cells: ${cells.length || (data.cells ? 0 : '—')}`,
  ];
  if (names.length) {
    lines.push(`Cell Name: ${names.slice(0, MAX_CELLS_LISTED).join('; ')}`);
    if (names.length > MAX_CELLS_LISTED) lines.push(`  ${t.moreCells(names.length - MAX_CELLS_LISTED)}`);
  } else {
    lines.push('Cell Name: —');
  }
  if (coords.length) {
    lines.push(`Lat, Lon: ${coords.slice(0, MAX_CELLS_LISTED).join('; ')}`);
  } else {
    lines.push('Lat, Lon: —');
  }

  // 根因：列表按置信度降序（客户端排好序），只取前几条；首条附处理建议。
  const causes = Array.isArray(data.causes) ? data.causes : [];
  const failures = Array.isArray(data.failures) ? data.failures : [];
  if (causes.length) {
    lines.push('Root Cause Analysis:');
    causes.slice(0, MAX_CAUSES_LISTED).forEach((c, i) => {
      const conf = Number(c?.confidence);
      const bits = [
        Number.isFinite(conf) && conf > 0 ? `[${Math.round(conf)}%]` : '',
        String(c?.rule_name || '').trim(),
        c?.object_name ? `— ${String(c.object_name).trim()}` : '',
      ].filter(Boolean);
      lines.push(`${i + 1}. ${bits.join(' ')}`);
    });
    const sol = String(causes[0]?.solution || '').trim();
    if (sol) lines.push(`   ${t.advice(trunc(sol, LINE_BUDGET))}`);
  } else if (failures.some((f) => String(f).startsWith('causes'))) {
    lines.push(`Root Cause Analysis: ${t.causeFail}`);
  } else {
    lines.push(`Root Cause Analysis: ${t.noCause}`);
  }

  if (failures.length) lines.push(t.failures(trunc(failures.join('；'), LINE_BUDGET)));
  if (ctx.timeGiven === false && ctx.nowText) lines.push(t.windowNote(ctx.nowText));
  lines.push(t.source);
  return { answered: true, text: lines.join('\n') };
}

/* ------------------------------ 取数与编排 ------------------------------ */

/** 是否启用（config.json 的 vmaxCcaEnabled，默认开；环境变量可临时关）。 */
function enabled() {
  if (CONFIG.vmaxCcaEnabled === false || CONFIG.vmaxCcaEnabled === 'false') return false;
  if (process.env.VMAX_CCA_ENABLED === '0' || process.env.VMAX_CCA_ENABLED === 'false') return false;
  return !!String(CONFIG.myAppApiBase || '').trim();
}

/**
 * 调 my_app 的 /api/vmax-cca-query。失败抛错（信息里带上游 detail，
 * 422/502/503 的中文说明对用户有用），由调用方渲染成「查不了」文案。
 */
async function fetchCca(msisdn, startText, endText) {
  const base = String(CONFIG.myAppApiBase || '').replace(/\/+$/, '');
  const url = `${base}/api/vmax-cca-query?${new URLSearchParams({
    msisdn, start: startText, end: endText,
  })}`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    const body = await res.json().catch(() => null);
    if (!res.ok) {
      throw new Error(String(body?.detail || `HTTP ${res.status}`));
    }
    if (!body || typeof body !== 'object') throw new Error('响应不是 JSON 对象');
    return body;
  } catch (err) {
    if (err.name === 'AbortError') throw new Error(`查询超时（${TIMEOUT_MS}ms）`);
    if (err?.cause?.code) throw new Error(`连不上 my_app：${err.cause.code}`);
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 执行 query_vmax_cca 工具。
 *
 * 参数来源优先级与统计通道 normalizeArgs 一致：**规则层从原始提问解析 >
 * 模型给的 > 当前时刻**（规则层有本机时钟，模型只有抄来的字符串）。
 *
 * @param {object} args   路由参数 {msisdn, time}
 * @param {object} opts   {lang, now, question}
 * @returns {Promise<{text:string, answered:boolean, channel:'vmaxcca', stats?:object, routeArgs?:object}>}
 */
export async function runVmaxCca(args, { lang = 'zh', now = new Date(), question = '' } = {}) {
  const t = T[lang] || T.zh;
  const t0 = Date.now();

  const intent = parseVmaxCcaIntent(question, now);
  let msisdn = intent?.msisdn || '';
  let end = intent?.end;
  let timeGiven = intent?.timeGiven || false;

  if (!msisdn) {
    // 模型层路径（提问里没写 TEL，模型把号码抽进了 args）
    msisdn = normalizeLiberiaMsisdn(args?.msisdn);
    for (const src of [String(args?.time || ''), String(args?.end || ''), question]) {
      const r = parseCcaEndtime(src, now);
      if (r) { end = r.end; timeGiven = true; break; }
    }
  }

  if (!msisdn) {
    return {
      answered: false,
      channel: 'vmaxcca',
      text: t.usage,
      stats: { totalMs: Date.now() - t0 },
    };
  }
  if (!enabled()) {
    return {
      answered: false,
      channel: 'vmaxcca',
      text: t.unavailable,
      stats: { totalMs: Date.now() - t0 },
      routeArgs: { msisdn },
    };
  }

  if (!end) end = now;
  const start = new Date(end.getTime() - CCA_WINDOW_MIN * 60 * 1000);
  const startText = fmtDateTime(start);
  const endText = fmtDateTime(end);
  const nowText = fmtDateTime(now);

  try {
    const data = await fetchCca(msisdn, startText, endText);
    const rendered = renderCcaResult(data, lang, {
      msisdn,
      timeGiven,
      nowText,
      win: { start: startText, end: endText },
    });
    return {
      ...rendered,
      channel: 'vmaxcca',
      stats: {
        totalMs: Date.now() - t0,
        found: !!data?.found,
        cells: Array.isArray(data?.cells?.cells) ? data.cells.cells.length : 0,
        causes: Array.isArray(data?.causes) ? data.causes.length : 0,
      },
      routeArgs: { msisdn, start: startText, end: endText },
    };
  } catch (err) {
    return {
      answered: false,
      channel: 'vmaxcca',
      text: t.error(String(err?.message || err)),
      stats: { totalMs: Date.now() - t0 },
      routeArgs: { msisdn, start: startText, end: endText },
    };
  }
}

export const _internal = { enabled, arrVals, T, TIMEOUT_MS };
