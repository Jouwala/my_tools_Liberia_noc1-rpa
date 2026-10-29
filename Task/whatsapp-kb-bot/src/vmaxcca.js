/**
 * VMAX CCA 用户查询通道 —— 「TEL <号码>[，<截止时间>]」→ XDR CCA 投诉信息。
 *
 * ## 场景（2026-10-25 需求）
 *
 * 群成员发「TEL 231773777115，2026-10-25 10:07」，机器人按「截止时间往前
 * 60 分钟」的窗口查 VMAX CCA，按固定模板回：
 *   XDR CCA / MSISDN / IMSI / IMEI / Model / Total traffic /
 *   Track Cells / Cell Name / Lat, Lon / Coverage KPI / Root Cause Analysis
 * 字段名沿用需求方给的英文标签 —— 它们是 CCA 页面上的领域标识符，与
 * TT 通道「规则名不翻译」同一口径；界面说明句仍按提问语言中英各一份。
 *
 * ## 2026-10-27 新增两段内容
 *
 * ① **Coverage KPI（RSRP/SINR/RSRQ 等）** —— 需求方要求把覆盖类读数带上。
 *   数据来自 `query_cell` 返回的 `cellKpi`（my_app 已把 ppc/ppb 码映射成
 *   英文名），见 `extractCoverage`。只有无线小区（rat=6）有这些指标，
 *   2G/3G 小区的 KPI 是信令类（PDP/Attach/TAU 成功率），不混进来。
 *   作用是给根因提供**支撑读数**：根因说「下行弱覆盖」，这里给
 *   RSRP -92dBm 与弱覆盖占比 6.5%，排障时两者要对着看。
 *
 * ② **Root Cause Analysis 改为按 Cause Rule 归并后全列** —— 需求方问
 *   「Root Cause Analysis 里是如何选择，能按 Cause Rule 都显示吗」。
 *   上游 `getcause` 返回的是**明细条目**（实测一天 58 条，去重后只有 23 条
 *   不同规则）；原先只取前 3 条，信息被丢掉且看不出「哪条规则命中几处」。
 *   现在按 `rule_name` 归并，23 条规则**全部列出**，每条带置信度、命中对象
 *   （小区/SP，可有多个）与命中条数，见 `groupCausesByRule`。
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
/** 覆盖 KPI 最多列几个小区 —— 每个小区一行，全列同样刷屏。 */
const MAX_COVERAGE_CELLS = 6;
/** 单条 Cause Rule 最多列几个对象（小区 / SP），超出只报数量。 */
const MAX_OBJECTS_PER_RULE = 3;
/** 单行截断长度（根因的处理建议可能很长）。 */
const LINE_BUDGET = 200;

/**
 * CCA 这条通道的回复长度上限（字符）。
 *
 * 为什么单独一份、而不是沿用 CONFIG.maxReplyChars（2000）：
 *   · 2000 是**给 TT 通道**定的（config.json 里写了来由：TT 英文回复最长 ~1690）；
 *   · CCA 要多带「覆盖 KPI」段 + **按 Cause Rule 归并后的全部根因**，
 *     实测一天 58 条原始命中按 rule_name 归并后仍有 23 条规则，
 *     加上头部与覆盖段约 3.5~4 千字符 —— 塞进 2000 会被 whatsapp.js 的
 *     truncate **从尾部砍掉**「来源」行与「处理建议」（与 2026-10-07
 *     TT 通道「时效」段被砍是同一类问题，见 config.json 的 $maxReplyChars）。
 *   · 覆盖类内容若放不下，宁可少列几条低置信度根因，也必须保住尾部的
 *     来源行/失败说明 —— 所以这里给一个独立上限，渲染层再按预算自我裁剪。
 */
export const CCA_REPLY_BUDGET = 4500;

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
  let num = after.match(/^[\s:=（(\-]*((?:\d[\s\-().]*){7,15})/);

  // 2026-10-28 补：号码写在关键字**前面**的写法也要认。
  // 群里真实问法 `231777550122 TEL please check this user last 3 days..` ——
  // 关键字后面的号码段为空，旧实现返回 null，于是这句话落到 extractAlarmCode，
  // 12 位号码被当成告警码，回一句「码表里没有 231777550122」，号码与时间全丢。
  // 只在「已确认有 TEL/MSISDN 关键字」的前提下才全句找号码，所以不会误伤普通提问。
  if (!num) {
    for (const m of rest.matchAll(/[\d][\d\s\-().]{6,}/g)) {
      const d = m[0].replace(/\D/g, '');
      if (d.length >= 7 && d.length <= 15) {
        num = [m[0], d];
        break;
      }
    }
  }
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
    // —— 覆盖段（2026-10-27 新增）——
    coverageTitle: 'Coverage KPI（RSRP/SINR/RSRQ）：',
    noCoverage: 'Coverage KPI: —（该窗口无线小区无覆盖类 KPI）',
    moreCoverage: (n) => `…（还有 ${n} 个小区的覆盖 KPI 未列出）`,
    // —— 根因段（2026-10-27 改为按 Cause Rule 归并全列）——
    causeTitle: 'Root Cause Analysis（按 Cause Rule 归并）：',
    moreObjects: (n) => ` 等 ${n} 个对象`,
    moreRules: (n) => `（其余 ${n} 条规则的完整明细与各自处理建议见 my_app「VMAX 用户查询」页）`,
    droppedRules: (n) => `…（另有 ${n} 条规则因回复长度上限未列出）`,
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
    coverageTitle: 'Coverage KPI (RSRP/SINR/RSRQ):',
    noCoverage: 'Coverage KPI: —(no coverage KPIs for radio cells in this window)',
    moreCoverage: (n) => `…(+${n} more cells with coverage KPIs not listed)`,
    causeTitle: 'Root Cause Analysis (grouped by Cause Rule):',
    moreObjects: (n) => ` and ${n} more object(s)`,
    moreRules: (n) => `(full detail and per-rule advice for the other ${n} rule(s): my_app "VMAX User Query" page)`,
    droppedRules: (n) => `…(+${n} more rule(s) omitted — reply length limit)`,
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

/* ----------------------------- 覆盖类 KPI ----------------------------- */

/**
 * 覆盖类 KPI 的「展示名 → 匹配规则」。
 *
 * 数据来源是 CCA 的 `query_cell` 返回的 `cellKpi`，键是 ppc/ppb 码，
 * 名是 `global/kpi_popup/query_kpi` 字典映射出来的英文名（my_app 侧
 * `vmax_cca_client.kpi_names`）。实测（2026-10-26 真号）无线侧小区会带：
 *
 *   Average RSRP(dBm)                    ppc1208204003_42
 *   Average Uplink SINR(LTE)(dB)         ppc1208204008_42
 *   Average RSRQ(dB)                     ppc1208204036_42
 *   Downlink weak coverage ratio(LTE)(%) ppc1208204005_42
 *   Uplink SINR Poor Ratio(LTE)(%)       ppc1208204026_42
 *   MR ratio of downlink RSRQ interference(%) ppc1208204056_42
 *   prb_dl_avail_rate_42 / prb_ul_avail_rate_42（PRB 空闲率，原名就是码）
 *
 * 匹配用**名字**（不是码）：码是厂商内部编号，上游改字典就会失效；
 * 名字是领域可读标识，且 CC 前端也按名字展示。
 */
const COVERAGE_KPI_DEFS = [
  { key: 'rsrp', label: 'RSRP', match: /Average\s+RSRP/i, unit: 'dBm' },
  { key: 'sinr', label: 'SINR', match: /Average\s+Uplink\s+SINR/i, unit: 'dB' },
  { key: 'rsrq', label: 'RSRQ', match: /Average\s+RSRQ/i, unit: 'dB' },
  { key: 'dlCov', label: 'DL弱覆盖', match: /Downlink weak coverage ratio/i, unit: '%' },
  { key: 'ulSinrPoor', label: '上行SINR劣化', match: /Uplink SINR Poor Ratio/i, unit: '%' },
  { key: 'rsrqInt', label: 'RSRQ干扰比', match: /MR ratio of downlink RSRQ interference/i, unit: '%' },
  { key: 'prbDl', label: 'PRB下行空闲', match: /^prb_dl_avail_rate/i, unit: '%' },
  { key: 'prbUl', label: 'PRB上行空闲', match: /^prb_ul_avail_rate/i, unit: '%' },
];

/** KPI 值转显示文本：数字去掉无意义小数尾零，'--'/空 → null（缺，不是 0）。 */
function fmtKpiValue(v) {
  if (v == null || v === '' || v === '--') return null;
  const n = Number(v);
  if (Number.isFinite(n)) return String(Math.round(n * 100) / 100);
  return String(v);
}

/**
 * 从 `cells.cell_kpi` 里挑出覆盖类 KPI，按小区聚合。
 *
 * ## cell_kpi 的键是「小区 ID 或 cellkey」，同一个小区可能两套键都有
 *
 * 实测（2026-10-26 真号，15 个小区）两种键混用：
 *   · 大多数是小区 ID（`461807001031977`），与 `cells[].cell` 对得上；
 *   · 少数是 cellkey（`4808_21`），上游只给了 cellkey 形态。
 * 更麻烦的是**同一个小区两个键都存在、且内容不同** ——
 * `461807001230869`（cellkey `4808_21`）按 ID 取到的是信令类 KPI，
 * 按 cellkey 取到的才是无线覆盖 KPI。
 * 所以这里**两个键都取、并集**（按 code 去重），不能二选一 ——
 * 二选一会让「根因指向 4808_21 的覆盖问题」在覆盖段里查不到对应读数。
 *
 * ## 只有 LTE（rat=6）小区才有无线覆盖 KPI
 *
 * 2G/3G 小区（rat=1）的 cellKpi 是信令类（PDP/Attach/TAU 成功率），
 * 没有 RSRP/SINR/RSRQ —— 覆盖段只列真正有无线指标的区。
 *
 * @returns {Array<{cell, cellkey, cellname, kpis: Array<{key,label,value,unit}>}>}
 */
export function extractCoverage(cellsData) {
  const cells = Array.isArray(cellsData?.cells) ? cellsData.cells : [];
  const kpiMap = cellsData?.cell_kpi && typeof cellsData.cell_kpi === 'object'
    ? cellsData.cell_kpi
    : {};
  const out = [];
  for (const c of cells) {
    // 两个键都取，并集（按 code 去重，优先保留先命中的）
    const byId = kpiMap[String(c?.cell)];
    const byKey = kpiMap[String(c?.cellkey)];
    const items = [];
    const seen = new Set();
    for (const src of [byId, byKey]) {
      if (!Array.isArray(src)) continue;
      for (const it of src) {
        const code = String(it?.code ?? '');
        if (seen.has(code)) continue;
        seen.add(code);
        items.push(it);
      }
    }
    if (!items.length) continue;
    const kpis = [];
    for (const def of COVERAGE_KPI_DEFS) {
      const hit = items.find((it) => def.match.test(String(it?.name || '')));
      if (!hit) continue;
      const value = fmtKpiValue(hit.value);
      if (value === null) continue;   // 缺值不是 0，别显示成 0
      kpis.push({ key: def.key, label: def.label, value, unit: def.unit });
    }
    if (!kpis.length) continue;       // 只有信令类 KPI 的小区不进覆盖段
    out.push({
      cell: String(c?.cell ?? ''),
      cellkey: String(c?.cellkey ?? ''),
      cellname: String(c?.cellname ?? '').trim(),
      kpis,
    });
  }
  // 覆盖类小区多的排前面（问题最重的先看）
  out.sort((a, b) => b.kpis.length - a.kpis.length);
  return out;
}

/* --------------------------- 根因按规则归并 --------------------------- */

/**
 * 把根因按 **Cause Rule（rule_name）** 归并。
 *
 * ## 为什么要归并而不是直接列原始条目
 *
 * 上游 `getcause` 对同一窗口返回的是**明细条目**：实测一天 58 条，
 * 但去重后只有 23 条不同的 Cause Rule（例："High RSRQ interference(cell)"
 * 一条规则就命中 5 次，分别落在 4 个小区、5 个劣化时段）。
 * 直接列 58 条没人读得完，而且同一个建议会重复 5 遍。
 * 归并后是「23 条规则 × 命中对象」，正是排障要看的粒度。
 *
 * ## 每组保留什么
 *   · confidence：取组内**最高**（最严重的那条代表这条规则）；
 *   · objects  ：命中的对象（小区名 / SP 名），去重后列出；
 *   · solution ：处理建议（组内取第一条非空；同一规则的建议相同）；
 *   · count    ：该规则命中的明细条数（>1 说明多处命中）。
 *
 * @returns {Array<{rule, confidence, objects, objectCount, solution, count, poortime}>}
 */
export function groupCausesByRule(causes) {
  const list = Array.isArray(causes) ? causes : [];
  const groups = new Map();
  for (const c of list) {
    const rule = String(c?.rule_name || '').trim();
    if (!rule) continue;
    let g = groups.get(rule);
    if (!g) {
      g = {
        rule,
        confidence: 0,
        objects: [],
        objectCount: 0,
        solution: '',
        count: 0,
        poortime: '',
      };
      groups.set(rule, g);
    }
    g.count += 1;
    const conf = Number(c?.confidence);
    if (Number.isFinite(conf) && conf > g.confidence) g.confidence = conf;
    // 对象名可能是 '--'（上游没给名字，但 objectinfo 里有 cellkey），
    // 这时用 objectinfo 顶上，不能让它变成空对象。
    const objName = String(c?.object_name || '').trim();
    const objInfo = String(c?.objectinfo || '').trim();
    const obj = objName && objName !== '--' ? objName : objInfo && objInfo !== '--' ? objInfo : '';
    if (obj && !g.objects.includes(obj)) {
      g.objects.push(obj);
      g.objectCount += 1;
    }
    if (!g.solution) g.solution = String(c?.solution || '').trim();
    if (!g.poortime) g.poortime = String(c?.poortime || '').trim();
  }
  // 排序：置信度降序 → 命中对象多的在前 → 规则名（保证稳定输出）
  const out = [...groups.values()];
  out.sort(
    (a, b) =>
      b.confidence - a.confidence ||
      b.objectCount - a.objectCount ||
      a.rule.localeCompare(b.rule)
  );
  return out;
}

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

  // —— 覆盖类 KPI（RSRP/SINR/RSRQ 等）——
  // 单独一段，因为它是「无线质量」的直接读数：根因说"下行弱覆盖"，
  // 这里给出支撑数据（RSRP -92dBm / 弱覆盖比 6.5%），排障时两者要对着看。
  const coverage = extractCoverage(data.cells);
  if (coverage.length) {
    lines.push(t.coverageTitle);
    coverage.slice(0, MAX_COVERAGE_CELLS).forEach((c) => {
      const name = c.cellname || c.cellkey || c.cell || '—';
      const kpiText = c.kpis.map((k) => `${k.label} ${k.value}${k.unit}`).join(' | ');
      lines.push(`  ${name}: ${kpiText}`);
    });
    if (coverage.length > MAX_COVERAGE_CELLS) {
      lines.push(`  ${t.moreCoverage(coverage.length - MAX_COVERAGE_CELLS)}`);
    }
  } else {
    lines.push(t.noCoverage);
  }

  // 根因：按 **Cause Rule 归并**后全部列出（不再是"前 3 条"）。
  // 实测一天 58 条明细 = 23 条规则，全列是排障要的信息量；
  // 同一条规则的对象/条数合并显示，避免重复刷屏。
  //
  // ⚠️ 预算裁剪：整条回复有 CCA_REPLY_BUDGET 上限（whatsapp.js 会从尾部
  // 截断，那会把「来源」行砍掉 —— 与 2026-10-07 TT 通道「时效」段被砍
  // 同一类问题）。所以这里**主动**按预算裁剪根因条数：从低置信度开始
  // 少列，保住尾部；裁掉多少必须如实告知，不能让用户以为「就这些」。
  const causes = Array.isArray(data.causes) ? data.causes : [];
  const failures = Array.isArray(data.failures) ? data.failures : [];
  const ruleGroups = groupCausesByRule(causes);

  // 尾部固定行（失败说明 / 兜底说明 / 来源）——预算里先给它留位置。
  const tail = [];
  if (failures.length) tail.push(t.failures(trunc(failures.join('；'), LINE_BUDGET)));
  if (ctx.timeGiven === false && ctx.nowText) tail.push(t.windowNote(ctx.nowText));
  tail.push(t.source);
  const tailLen = tail.join('\n').length + 1;

  if (ruleGroups.length) {
    const head = lines.join('\n');
    const budgetLeft = CCA_REPLY_BUDGET - head.length - tailLen;
    // 每条根因行的预估长度（规则名 + 置信度 + 对象）
    const costOf = (g) =>
      g.rule.length + (g.confidence > 0 ? 7 : 0) + g.objects.slice(0, MAX_OBJECTS_PER_RULE).join('; ').length + 12;
    // 从低置信度往上加，直到放不下 —— 高置信度的先保住。
    const kept = [];
    let used = 0;
    for (let i = ruleGroups.length - 1; i >= 0; i--) {
      const c = costOf(ruleGroups[i]);
      if (used + c > budgetLeft) continue;   // 跳过这一条，继续试更短的
      used += c;
      kept.unshift(ruleGroups[i]);
    }
    const dropped = ruleGroups.length - kept.length;

    lines.push(t.causeTitle);
    kept.forEach((g, i) => {
      const bits = [
        g.confidence > 0 ? `[${Math.round(g.confidence)}%]` : '',
        g.rule,
      ].filter(Boolean);
      let line = `${i + 1}. ${bits.join(' ')}`;
      if (g.objectCount) {
        const shown = g.objects.slice(0, MAX_OBJECTS_PER_RULE).join('; ');
        const more = g.objectCount - MAX_OBJECTS_PER_RULE;
        line += ` — ${shown}`;
        if (more > 0) line += t.moreObjects(more);
      }
      lines.push(line);
    });
    if (dropped > 0) lines.push(t.droppedRules(dropped));
    // 处理建议：每条规则一条建议太长（23 条 × 上百字会撑爆消息），
    // 只给置信度最高的那条，其余规则的处理建议去 my_app 页面看。
    const top = kept[0];
    if (top?.solution) {
      lines.push(`   ${t.advice(trunc(top.solution, LINE_BUDGET))}`);
    }
    // 指向 my_app 页面（完整明细 + 每条规则各自的建议）。
    // 不重复写「来源：VMAX CCA」——末尾已经有来源行了，这里只说去哪看。
    if (kept.length > 1) lines.push(t.moreRules(kept.length - 1));
  } else if (failures.some((f) => String(f).startsWith('causes'))) {
    lines.push(`Root Cause Analysis: ${t.causeFail}`);
  } else {
    lines.push(`Root Cause Analysis: ${t.noCause}`);
  }

  lines.push(...tail);
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
      // 本通道自带的回复长度上限（比全局 maxReplyChars=2000 宽，
      // 因为要多带覆盖 KPI 段与全部 Cause Rule）。whatsapp.js 优先用这个值。
      maxReplyChars: CCA_REPLY_BUDGET,
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
