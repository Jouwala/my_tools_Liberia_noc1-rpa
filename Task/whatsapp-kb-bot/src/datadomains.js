/**
 * 高频数据域查询 —— 电源 / 历史告警 / WO / 站点可用率。
 *
 * ## 为什么要有这条通道
 *
 * 2026-11-03 审计：生产库 `app` schema 有 78 张表（另有 eflow / ms_sla / battery /
 * ipran_ume / ran_ume / lte_pl / fw 共 7 个业务 schema，最大表 195 万行），
 * 但机器人的工具里**只有 5 个真正在查业务数据**。运维最常问的四类问题 ——
 * 电源、历史告警、WO、可用率 —— **一个都没有对应工具**，模型只能拿规则文档硬编，
 * 或者干脆答不出。
 *
 * 这里走 my_app 的 `/api/bot-data/*`（后端 routers/bot_data.py），四条通道
 * 各自对应固定 SQL：
 *
 *   power            → ipt_power_sites / ipt_power_snapshots
 *   alarm-history    → history_alarm（175 列 / 1.9 万行）
 *   wo               → eflow_wo（173 列 / 1.5 万行）
 *   site-availability→ ms_sla 系列（复用 site_availability_service 口径）
 *   task-stats       → task_runner.list_tasks（与前端任务管理页同源同口径）
 *
 * ## 为什么这些不用 NL2SQL
 *
 * NL2SQL 一次要跑两次 LLM，20~60 秒，且模型偶发写出语义偏差的 SQL ——
 * 对「查无此站」「这个站有几张单」这类要精确结论的问题不可接受。
 * 高频问题必须有固定 SQL。NL2SQL 只作长尾兜底，见 src/dataquery.js。
 *
 * ## 与既有通道的分工
 *
 *   query_site_alarms   → 这个站**现在**有没有告警（eFlow 实时活动告警）
 *   query_alarm_history  → 这个站**历史上**有过哪些告警（history_alarm）
 *   query_tickets        → 工单**数量**统计
 *   query_wo             → WO **明细**（含状态/SLA/根因/影响站点）
 *
 * 「实时告警」与「历史告警」是两份不同的数据，不能互相顶替。
 */
import { CONFIG } from './config.js';

/** HTTP 超时。这几个接口都是点查 + 模糊匹配，秒级返回；超时即失败。 */
const HTTP_TIMEOUT_MS = Number(process.env.BOT_DATA_TIMEOUT_MS || 15000);

/** 单次渲染最多列出多少条明细 —— 群里刷屏比少列几条更糟。 */
const MAX_ROWS_SHOWN = Number(process.env.BOT_DATA_MAX_ROWS || 10);

/** my_app 后端基址（去掉尾部斜杠）。 */
function apiBase() {
  const base = String(CONFIG.myAppApiBase || '').replace(/\/+$/, '');
  if (!base) throw new Error('未配置 myAppApiBase');
  return base;
}

/**
 * 调 my_app 的 /api/bot-data 接口。
 * 失败一律抛出，由 queryDataDomain 统一处理 —— 这里不做降级决策。
 */
async function fetchDomain(domain, params) {
  const url = new URL(`/api/bot-data/${domain}`, apiBase());
  for (const [k, v] of Object.entries(params || {})) {
    if (v === undefined || v === null || v === '') continue;
    url.searchParams.set(k, String(v));
  }

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), HTTP_TIMEOUT_MS);
  let res;
  try {
    res = await fetch(url, { signal: ctrl.signal });
  } catch (err) {
    if (err.name === 'AbortError') throw new Error(`HTTP 超时（${HTTP_TIMEOUT_MS}ms）`);
    throw new Error(`连不上 my_app：${err.cause?.code || err.message}`);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) throw new Error(`my_app 返回 ${res.status}`);
  const data = await res.json();
  if (!data || typeof data !== 'object') throw new Error('my_app 返回结构不符合预期');
  return data;
}

/* -------------------------------- 文案 -------------------------------- */

const T = {
  zh: {
    power: (name) => `【${name}】电源状态`,
    powerAll: '站点电源状态',
    alarm: (name) => `【${name}】历史告警`,
    alarmAll: '历史告警',
    wo: (name) => `【${name}】WO 工单`,
    woAll: 'WO 工单',
    avail: (name) => `【${name}】站点可用率`,
    availAll: '站点可用率',
    taskStats: '任务管理执行统计',
    taskStatsAll: '任务管理执行统计',
    taskStatus: {
      success: '成功', failed: '失败', running: '运行中',
      disabled: '已停用', unknown: '未记录',
    },
    taskFailedTitle: '当前失败的任务',
    taskFailedNone: '当前没有失败的任务。',
    taskRootCause: '近期失败根因聚类',
    taskRootCauseNone: '近期没有失败记录。',
    taskRetry: '将自动重试',
    taskNoRows: '没有匹配的任务。',
    notFound: (what, site) => `库里查不到${what}「${site}」的记录。`,
    empty: (what, site) => `查到了「${site}」，但${what}**没有记录**。`,
    noSite: (what) => `请告诉我是哪个站点（站名），我才能查${what}。`,
    unavailable: '我这边暂时查不到这个数据，请稍后再试。',
    error: (detail) => `查询时出错了${detail ? `：${detail}` : ''}。请稍后再试。`,
    source: '来源：my_app 数据域接口（实时）',
    more: (shown, total) => `…… 另有 ${total - shown} 条未列出`,
    noExact: (what, site, names) =>
      `⚠️ ${what}里没有名为「${site}」的站；以下是模糊匹配到的：${names}`,
    tech: { G: '2G', U: '3G', L: '4G', Tdd: '5G' },
    labels: {
      connectivity: '供电状态', load_current: '负载电流(A)', load_power: '负载功率(kW)',
      battery_voltage: '电池电压(V)', battery_soc: '电池电量(%)',
      battery_charging_state: '充电状态', solar_power: '太阳能功率',
      generator_on: '发电机', fuel_ratio: '燃油比例', fuel_level: '油量',
      grid_on: '市电', snap_time: '快照时间', priority: '优先级',
      criticality: '关键度', cluster: '集群', organization: '所属组织',
      raised: '发生时间', severity_name: '级别', alarmcode: '告警码',
      alarm_title: '告警名称', cleared: '清除时间', clearstate: '清除状态',
      tt_id: '关联TT', impact_site_number: '影响站点数', region: '区域',
      cell_name: '小区', ack_state: '确认状态',
      wo_no: 'WO号', tt_no: '关联TT', title: '标题', status: '状态',
      severity: '级别', created_time: '创建时间', last_modified: '最后更新',
      sla_status: 'SLA', sla_remain_time: 'SLA剩余', current_handler: '当前处理人',
      domain: '领域', ne_name: '网元', impact_down_site_count: '是否影响站点',
      fault_duration: '故障时长', diagnosis: '诊断结论',
      down_site_count: '影响站点数', hub_site: '枢纽站', vip_level: 'VIP等级',
      alarm_occur_time: '告警发生时间', alarm_clear_time: '告警恢复时间',
    },
    yesNo: { 1: '是', 0: '否' },
  },
  en: {
    power: (name) => `Power status for ${name}`,
    powerAll: 'Site power status',
    alarm: (name) => `Historical alarms for ${name}`,
    alarmAll: 'Historical alarms',
    wo: (name) => `Work orders for ${name}`,
    woAll: 'Work orders',
    avail: (name) => `Availability for ${name}`,
    availAll: 'Site availability',
    taskStats: 'Task manager execution stats',
    taskStatsAll: 'Task manager execution stats',
    taskStatus: {
      success: 'succeeded', failed: 'failed', running: 'running',
      disabled: 'disabled', unknown: 'no record',
    },
    taskFailedTitle: 'Currently failing tasks',
    taskFailedNone: 'No task is currently failing.',
    taskRootCause: 'Recent failure root-cause clusters',
    taskRootCauseNone: 'No recent failures.',
    taskRetry: 'will auto-retry',
    taskNoRows: 'No matching task.',
    notFound: (what, site) => `No ${what} record found for "${site}".`,
    empty: (what, site) => `Found "${site}", but it has no ${what} records.`,
    noSite: (what) => `Which site? Please give me the site name so I can look up the ${what}.`,
    unavailable: "I can't reach that data right now. Please try again later.",
    error: (detail) => `Something went wrong while querying${detail ? `: ${detail}` : ''}. Please try again later.`,
    source: 'Source: my_app data domain API (live)',
    more: (shown, total) => `... and ${total - shown} more`,
    noExact: (what, site, names) =>
      `⚠️ No site named "${site}" in ${what}; showing fuzzy matches: ${names}`,
    tech: { G: '2G', U: '3G', L: '4G', Tdd: '5G' },
    labels: {
      connectivity: 'supply', load_current: 'load current(A)', load_power: 'load power(kW)',
      battery_voltage: 'battery voltage(V)', battery_soc: 'battery SOC(%)',
      battery_charging_state: 'charging state', solar_power: 'solar power',
      generator_on: 'generator', fuel_ratio: 'fuel ratio', fuel_level: 'fuel level',
      grid_on: 'grid', snap_time: 'snapshot time', priority: 'priority',
      criticality: 'criticality', cluster: 'cluster', organization: 'organization',
      raised: 'raised at', severity_name: 'severity', alarmcode: 'alarm code',
      alarm_title: 'alarm name', cleared: 'cleared at', clearstate: 'clear state',
      tt_id: 'related TT', impact_site_number: 'impacted sites', region: 'region',
      cell_name: 'cell', ack_state: 'ack state',
      wo_no: 'WO no', tt_no: 'related TT', title: 'title', status: 'status',
      severity: 'severity', created_time: 'created', last_modified: 'last modified',
      sla_status: 'SLA', sla_remain_time: 'SLA left', current_handler: 'handler',
      domain: 'domain', ne_name: 'NE', impact_down_site_count: 'impacted?',
      fault_duration: 'fault duration', diagnosis: 'diagnosis',
      down_site_count: 'impacted sites', hub_site: 'hub site', vip_level: 'VIP level',
      alarm_occur_time: 'alarm raised at', alarm_clear_time: 'alarm cleared at',
    },
    yesNo: { 1: 'yes', 0: 'no' },
  },
};

/** 值 → 展示文本。0/1 这类布尔型字段转成「是/否」，空值一律跳过。 */
function val(v, lang) {
  if (v === null || v === undefined || v === '') return '';
  const t = T[lang] || T.zh;
  const s = String(v);
  if (s === '0' || s === '1') {
    // generator_on / grid_on / clearstate 这类 0/1 字段
    return t.yesNo[s] ?? s;
  }
  return s;
}

/**
 * 列出「标签：值」行，跳过空值。
 *
 * 标签优先取 T[lang].labels（与 my_app 的字段字典对齐的中英文对照表），
 * FIELDS 里的第二项只是**兜底**，防止新加字段忘了写进 labels 时露出英文 key。
 */
function linesFor(row, fields, lang) {
  const t = T[lang] || T.zh;
  const out = [];
  for (const [key, fallbackLabel] of fields) {
    const v = val(row[key], lang);
    if (v === '') continue;
    out.push(`- ${t.labels[key] || fallbackLabel}：${v}`);
  }
  return out;
}

/**
 * 「没有精确匹配」提示。
 *
 * 站名是模糊匹配的：问 "Wood Camp" 会连带命中 "East Wood Camp" / "Wood Camp 2"。
 * 如果**没有一条**是完全相等的，就必须把这点讲清楚 —— 否则用户会把
 * "East Wood Camp" 的供电状态 / 告警当成 "Wood Camp" 的，这属于答错站。
 */
function noExactHint(rows, key, site, lang, what) {
  const t = T[lang] || T.zh;
  const s = String(site || '').trim().toLowerCase();
  if (!s) return '';
  const names = rows.map((r) => String(r[key] || '').trim()).filter(Boolean);
  if (!names.length) return '';
  if (names.some((n) => n.toLowerCase() === s)) return '';
  return t.noExact(what, site, names.join('、'));
}

/* ------------------------------ 各域渲染 ------------------------------ */

const POWER_FIELDS = [
  ['connectivity', 'connectivity'], ['load_current', 'load_current'],
  ['load_power', 'load_power'], ['battery_voltage', 'battery_voltage'],
  ['battery_soc', 'battery_soc'], ['battery_charging_state', 'battery_charging_state'],
  ['solar_power', 'solar_power'], ['generator_on', 'generator_on'],
  ['fuel_ratio', 'fuel_ratio'], ['grid_on', 'grid_on'],
  ['snap_time', 'snap_time'], ['priority', 'priority'],
  ['criticality', 'criticality'], ['cluster', 'cluster'],
];

const ALARM_FIELDS = [
  ['raised', 'raised'], ['severity_name', 'severity_name'], ['alarmcode', 'alarmcode'],
  ['alarm_title', 'alarm_title'], ['cleared', 'cleared'], ['tt_id', 'tt_id'],
  // ⚠️ history_alarm 里没有 impact_site_number 列，实际是 down_site_count（影响站点个数）
  ['down_site_count', 'down_site_count'], ['region', 'region'],
  ['cell_name', 'cell_name'], ['hub_site', 'hub_site'], ['vip_level', 'vip_level'],
];

const WO_FIELDS = [
  ['wo_no', 'wo_no'], ['tt_no', 'tt_no'], ['status', 'status'], ['severity', 'severity'],
  ['title', 'title'], ['created_time', 'created_time'], ['last_modified', 'last_modified'],
  ['sla_status', 'sla_status'], ['sla_remain_time', 'sla_remain_time'],
  ['current_handler', 'current_handler'], ['domain', 'domain'],
  ['impact_down_site_count', 'impact_down_site_count'], ['fault_duration', 'fault_duration'],
  ['alarm_occur_time', 'alarm_occur_time'], ['alarm_clear_time', 'alarm_clear_time'],
  ['diagnosis', 'diagnosis'],
];

function renderPower(d, lang, site) {
  const t = T[lang] || T.zh;
  const rows = d.rows || [];
  if (!rows.length) {
    return site ? t.empty(t.powerAll, site) : t.noSite(t.powerAll);
  }
  const lines = [];
  for (const r of rows.slice(0, MAX_ROWS_SHOWN)) {
    const name = r.name || r.site_id || '';
    lines.push(`## ${t.power(name)}`);
    lines.push('');
    lines.push(...linesFor(r, POWER_FIELDS, lang));
    lines.push('');
  }
  if (rows.length > MAX_ROWS_SHOWN) {
    lines.push(t.more(MAX_ROWS_SHOWN, rows.length));
    lines.push('');
  }
  const ph = noExactHint(rows, 'name', site, lang, t.powerAll);
  if (ph) {
    lines.push(ph);
    lines.push('');
  }
  lines.push(t.source);
  return lines.join('\n');
}

function renderAlarm(d, lang, site) {
  const t = T[lang] || T.zh;
  const rows = d.rows || [];
  if (!rows.length) {
    return site ? t.empty(t.alarmAll, site) : t.noSite(t.alarmAll);
  }
  const lines = [];
  for (const r of rows.slice(0, MAX_ROWS_SHOWN)) {
    const name = r.site_name || site || '';
    lines.push(`### ${t.alarm(name)}`);
    lines.push('');
    lines.push(...linesFor(r, ALARM_FIELDS, lang));
    lines.push('');
  }
  if (rows.length > MAX_ROWS_SHOWN) {
    lines.push(t.more(MAX_ROWS_SHOWN, rows.length));
    lines.push('');
  }
  const ah = noExactHint(rows, 'site_name', site, lang, t.alarmAll);
  if (ah) {
    lines.push(ah);
    lines.push('');
  }
  lines.push(t.source);
  return lines.join('\n');
}

function renderWo(d, lang, site) {
  const t = T[lang] || T.zh;
  const rows = d.rows || [];
  if (!rows.length) {
    return site ? t.empty(t.woAll, site) : t.noSite(t.woAll);
  }
  const lines = [];
  for (const r of rows.slice(0, MAX_ROWS_SHOWN)) {
    const name = r.site_name || site || '';
    lines.push(`### ${t.wo(name)}`);
    lines.push('');
    lines.push(...linesFor(r, WO_FIELDS, lang));
    lines.push('');
  }
  if (rows.length > MAX_ROWS_SHOWN) {
    lines.push(t.more(MAX_ROWS_SHOWN, rows.length));
    lines.push('');
  }
  const wh = noExactHint(rows, 'site_name', site, lang, t.woAll);
  if (wh) {
    lines.push(wh);
    lines.push('');
  }
  lines.push(t.source);
  return lines.join('\n');
}

function renderAvail(d, lang, site) {
  const t = T[lang] || T.zh;
  if (!d.found) {
    return t.notFound(t.availAll, site);
  }
  const lines = [];
  lines.push(`## ${t.avail(site)}（${d.month}）`);
  lines.push('');
  const avg = d.avg_by_tech || {};
  for (const tech of ['G', 'U', 'L', 'Tdd']) {
    if (avg[tech] === undefined || avg[tech] === null) continue;
    const pct = (Number(avg[tech]) * 100).toFixed(2);
    const days = (d.by_tech || {})[tech] || 0;
    lines.push(`- ${t.tech[tech] || tech} 可用率：${pct}%（${days} 天有数据）`);
  }
  const dayList = Object.entries(d.days || {});
  if (dayList.length) {
    lines.push('');
    lines.push('逐日明细（仅列出有数据的日期）：');
    for (const [day, techs] of dayList.slice(-14)) {
      const parts = Object.entries(techs)
        .map(([k, v]) => `${t.tech[k] || k} ${(Number(v) * 100).toFixed(1)}%`)
        .join('　');
      lines.push(`- ${day}：${parts}`);
    }
  }
  lines.push('');
  lines.push(t.source);
  return lines.join('\n');
}

/**
 * 任务管理执行统计渲染。
 *
 * 口径与 my_app 前端「数据同步」任务管理页**完全一致**（同一份
 * `list_tasks(include_runs=True)` 数据 + 同一套 classifyTaskStatus 判定）。
 *
 * ⚠️ 为什么这个域必须是**固定 SQL**而不是 NL2SQL（2026-11-04 实测故障）：
 * 问「my_app 的 task manager 有多少任务成功多少失败」时，NL2SQL 模型把
 * `my_app` 当成要过滤的**字面量**，生成
 * `WHERE task_id ILIKE '%my_app%' OR task_name ILIKE '%my_app%'`。
 * 而 task_name 存的是中文任务名（「eFlow 数据同步」…），没有一条含
 * "my_app" → 命中 0 行 → 机器人答「没有匹配到任何记录」。
 * **数据在库里，答案却是空的。** 高频问题必须有固定口径。
 */
function renderTaskStats(d, lang = 'zh') {
  const t = T[lang] || T.zh;
  const lines = [`## ${t.taskStats}`, ''];

  const counts = d?.counts || {};
  const total = Number(d?.total || 0);
  const st = t.taskStatus || {};

  // 汇总：成功 / 失败放最前 —— 用户问的就是这两个数
  lines.push(`- 注册任务总数：${total}`);
  lines.push(`- ${st.success}：${Number(counts.success || 0)}`);
  lines.push(`- ${st.failed}：${Number(counts.failed || 0)}`);
  if (Number(counts.running || 0) > 0) {
    lines.push(`- ${st.running}：${Number(counts.running || 0)}`);
  }
  if (Number(counts.disabled || 0) > 0) {
    lines.push(`- ${st.disabled}：${Number(counts.disabled || 0)}`);
  }
  if (Number(counts.unknown || 0) > 0) {
    lines.push(`- ${st.unknown}：${Number(counts.unknown || 0)}`);
  }

  // 失败任务明细（横幅口径：只排除 running，不排除 disabled）
  const failed = Array.isArray(d?.failed_now) ? d.failed_now : [];
  const failedTotal = Number(d?.failed_now_total || failed.length);
  lines.push('');
  lines.push(`### ${t.taskFailedTitle}（${failedTotal}）`);
  if (!failed.length) {
    lines.push(t.taskFailedNone);
  } else {
    for (const r of failed.slice(0, MAX_ROWS_SHOWN)) {
      const err = String(r.last_error || '').split('\n')[0].slice(0, 120);
      const retry = r.will_retry && r.next_retry_at
        ? `（${t.taskRetry}：${r.next_retry_at}）` : '';
      lines.push(`- ${r.name || r.task_id}${err ? `：${err}` : ''}${retry}`);
    }
    if (failedTotal > failed.length) {
      lines.push(t.more(failed.length, failedTotal));
    }
  }

  // 失败根因聚类
  const clusters = Array.isArray(d?.failure_clusters) ? d.failure_clusters : [];
  if (clusters.length) {
    lines.push('');
    lines.push(`### ${t.taskRootCause}`);
    for (const c of clusters.slice(0, 5)) {
      lines.push(`- ${Number(c.count || 0)} 次｜${c.error_first_line || '-'}`);
    }
  }

  lines.push('');
  lines.push(t.source);
  return lines.join('\n');
}

/**
 * 按域分发渲染。
 * @param {string} domain
 * @param {object} d 接口返回
 * @param {'zh'|'en'} lang
 * @param {string} site 原始站名（用于「查不到」的措辞）
 */
export function renderDataDomain(domain, d, lang = 'zh', site = '') {
  if (d && d.ok === false && d.message) {
    const t = T[lang] || T.zh;
    return t.error(d.message);
  }
  switch (domain) {
    case 'power': return renderPower(d, lang, site);
    case 'alarm-history': return renderAlarm(d, lang, site);
    case 'wo': return renderWo(d, lang, site);
    case 'site-availability': return renderAvail(d, lang, site);
    case 'task-stats': return renderTaskStats(d, lang);
    default: {
      const t = T[lang] || T.zh;
      return t.error(`未知数据域 ${domain}`);
    }
  }
}

/* -------------------------------- 主入口 -------------------------------- */

/**
 * 查询一个数据域。
 *
 * @param {'power'|'alarm-history'|'wo'|'site-availability'|'task-stats'} domain
 * @param {object} params  查询参数（site / days / severity / status / start / end / month / task_id / limit）
 * @returns {Promise<{ok:boolean, data?:object, error?:string}>}
 */
export async function queryDataDomain(domain, params = {}) {
  try {
    const data = await fetchDomain(domain, params);
    if (!data || typeof data !== 'object') {
      return { ok: false, error: '接口返回结构不符合预期' };
    }
    return { ok: true, data };
  } catch (err) {
    if (process.env.DEBUG_TOOLS === '1') {
      console.error(`[工具] 数据域 ${domain} 查询失败：${err.message}`);
    }
    return { ok: false, error: err.message };
  }
}

/**
 * 取数据集目录（机器人据此知道库里有什么）。
 * @returns {Promise<{ok:boolean, data?:object, error?:string}>}
 */
export async function fetchDatasets() {
  try {
    const data = await fetchDomain('datasets', {});
    return { ok: true, data };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}
