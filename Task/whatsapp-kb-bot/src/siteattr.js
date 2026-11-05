/**
 * 站点**属性**查询 —— 「这个站是不是 VIP 站 / 什么类型 / 是不是枢纽站」。
 *
 * ## 为什么要有这条通道
 *
 * 2026-11-03 实测故障：问「站点 lofa bridge 是 VIP 站点吗」，机器人答
 * 「是 VIP 站点，依据 assetType 为 vipSite（ticket_asset = 1）」——
 * **结论错、依据错、来源错**：
 *
 *   · 结论错：Lofa Bridge 的 vipsite 实为 `No`（三处独立数据源一致）。
 *   · 依据错：`assetType` 的合法取值只有 NORMAL / COOL / ERA，**没有 vipSite**；
 *     VIP 是**独立字段** `vipSite`（1=是 0=否）。模型把两个字段揉成了一个。
 *   · 来源错：答的是「级别怎么按 vipSite 定」的**规则文档**，里面一个站点名都没有。
 *
 * 根因是**知识库里没有站点实体数据** —— 站点属性在数据库里，不在语料里。
 * 规则文档能回答「VIP 站会被定成几级」，**回答不了「某某站是不是 VIP 站」**。
 *
 * ## 两条数据源
 *
 *   ① HTTP：my_app 的 `/api/site-attribute` —— 生产库 PostgreSQL，**实时**；
 *   ② SQLite：scripts/site-attr.py 读 my_app/db/app.db —— 同步副本，**有延迟**。
 *
 * 与 src/ttsource.js 同一套「HTTP 优先 + SQLite 降级 + 如实标注口径」纪律。
 * 降级时回复里必须带「本地副本」那句 —— 站点属性（尤其 VIP 标记）
 * 改动不频繁，但**不能让用户以为看到的是实时值**。
 *
 * ## 三处 VIP 判定与冲突处理
 *
 * VIP 判定在三处都有：`eflow_site.vipsite`（Yes/No，主口径）、
 * `master_site_db.vip_site`（Y/N）、`vip_site_list`（独立名单）。
 * 三处不一致时**如实报冲突**，不挑一个顺眼的报 —— 见 renderSiteAttribute。
 *
 * ## 与站点告警通道的关系

 * `query_site_alarms` 回答「这个站**现在有没有告警**」（eFlow 实时活动告警）；
 * 本模块回答「这个站**是什么属性**」（站点主数据）。
 * 两者是**不同的事实**，不能互相顶替 —— 与 src/sitealarms.js 的说明同源。
 */
import { execFile } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { CONFIG, ROOT } from './config.js';

const SCRIPT = resolve(ROOT, 'scripts', 'site-attr.py');

/** 与 src/ttsource.js / src/sitealarms.js 同一套解释器约定（可用 TT_PYTHON 覆盖）。 */
const PYTHON =
  process.env.TT_PYTHON ||
  'C:/Users/ZTEEMS/AppData/Local/Programs/Python/Python312/python.exe';

/** HTTP 超时。这个接口只做点查 + 模糊匹配，很快；超时即降级。 */
const HTTP_TIMEOUT_MS = Number(process.env.SITE_ATTR_TIMEOUT_MS || 8000);

/** SQLite 降级超时。app.db 在部分部署里位于网络盘，首次打开可能偏慢。 */
const FALLBACK_TIMEOUT_MS = Number(process.env.SITE_ATTR_FALLBACK_TIMEOUT_MS || 30000);

/* ------------------------------- HTTP 通道 ------------------------------- */

/** my_app 后端基址（去掉尾部斜杠）。 */
function apiBase() {
  const base = String(CONFIG.myAppApiBase || '').replace(/\/+$/, '');
  if (!base) throw new Error('未配置 myAppApiBase');
  return base;
}

/**
 * 调 my_app 的站点属性接口。
 *
 * 失败（服务没起 / 超时 / 非 2xx / 结构不符）**一律抛出**，
 * 由 querySiteAttribute 捕获后降级 —— 这里不做降级决策，职责单一。
 */
async function fetchHttp(site) {
  const url = new URL('/api/site-attribute', apiBase());
  url.searchParams.set('site', site);

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
  if (!data || typeof data !== 'object' || !('found' in data)) {
    throw new Error('my_app 返回结构不符合预期');
  }
  return { ...data, source: 'http' };
}

/* ----------------------------- SQLite 降级 ----------------------------- */

/** 降级通道是否可用（脚本 + 解释器都在）。 */
export function fallbackAvailable() {
  return existsSync(SCRIPT) && existsSync(PYTHON);
}

/** 跑 scripts/site-attr.py，返回解析后的结果。永不抛异常（失败返回 {error}）。 */
function runPython(site) {
  return new Promise((done) => {
    execFile(
      PYTHON,
      [SCRIPT, '--site', site],
      {
        timeout: FALLBACK_TIMEOUT_MS,
        encoding: 'utf8',
        windowsHide: true,
        maxBuffer: 2 * 1024 * 1024,
        // 与 src/ttsource.js 同因：进程环境没有 LANG，Python 的 stdout 会退化成
        // 系统代码页，一 print 中文就 UnicodeEncodeError。
        env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
      },
      (err, stdout, stderr) => {
        const out = (stdout || '').trim();
        if (err || !out) {
          const lines = String(stderr || err?.message || '').trim().split('\n').filter(Boolean);
          done({ error: lines[lines.length - 1] || '未知错误' });
          return;
        }
        try {
          done(JSON.parse(out));
        } catch {
          done({ error: `脚本输出不是 JSON：${out.slice(0, 120)}` });
        }
      }
    );
  });
}

/* -------------------------------- 文案 -------------------------------- */

const T = {
  zh: {
    header: (name) => `【${name}】站点属性`,
    vipYes: '**是 VIP 站点**',
    vipNo: '**不是 VIP 站点**',
    vipUnknown: 'VIP 属性**未知**（数据源里查不到明确的 VIP 标记）',
    conflict:
      '⚠️ 三处数据源的 VIP 判定**不一致**：' +
      '主站表认为不是 VIP，eFlow 站点属性认为不是 VIP，但独立 VIP 名单里**有**这个站。' +
      '以 eFlow 站点属性（主口径）为准，如需确认请查 VIP 名单。',
    hubYes: '枢纽站',
    hubNo: '非枢纽站',
    hubUnknown: '枢纽属性未知',
    // 字段名 → 中文标签（与 my_app 的字段字典对齐，避免再造一套叫法）
    labels: {
      site_type: '站点类型',
      site_sub_type: '站点子类型',
      region: '区域',
      province: '省/县',
      site_information: '站点信息',
      site_priority: '站点优先级',
      site_class: '站点分类',
      victims: '影响用户数',
      fme_name: '维护负责人',
    },
    notFound: (site, candidates) => {
      let t = `站点库里查不到「${site}」。请核对站名拼写（用站表里的正式英文名）。`;
      if (candidates && candidates.length) {
        t += `\n相近的站名：${candidates.join('、')}`;
      }
      return t;
    },
    unavailable: '我这边暂时查不到站点属性，请稍后再试，或到站点主数据看板确认。',
    error: (detail) => `查站点属性时出错了${detail ? `：${detail}` : ''}。请稍后再试。`,
    sourceLive: '来源：my_app 站点属性接口（实时）',
    sourceLocal: '来源：本地站点库副本（可能有延迟，非实时）',
    conflictNote: '数据源判定不一致，已如实标注。',
  },
  en: {
    header: (name) => `Site attributes for ${name}`,
    vipYes: '**is a VIP site**',
    vipNo: '**is not a VIP site**',
    vipUnknown: 'VIP status **unknown** (no explicit VIP flag in the data sources)',
    conflict:
      '⚠️ The three data sources **disagree**: the master site table says not VIP, ' +
      'the eFlow site attribute says not VIP, but the standalone VIP list **does** contain it. ' +
      'The eFlow site attribute (primary source) is used; check the VIP list to confirm.',
    hubYes: 'hub site',
    hubNo: 'not a hub site',
    hubUnknown: 'hub status unknown',
    labels: {
      site_type: 'site type',
      site_sub_type: 'site sub-type',
      region: 'region',
      province: 'province/county',
      site_information: 'site info',
      site_priority: 'site priority',
      site_class: 'site class',
      victims: 'affected subscribers',
      fme_name: 'maintenance owner',
    },
    notFound: (site, candidates) => {
      let t = `No site named "${site}" in the site database. Please double-check the spelling (use the official English name).`;
      if (candidates && candidates.length) {
        t += `\nSimilar names: ${candidates.join(', ')}`;
      }
      return t;
    },
    unavailable: "I can't reach the site attribute data right now. Please try again later.",
    error: (detail) => `Something went wrong while looking up site attributes${detail ? `: ${detail}` : ''}. Please try again later.`,
    sourceLive: 'Source: my_app site attribute API (live)',
    sourceLocal: 'Source: local site database copy (may be delayed, not live)',
    conflictNote: 'Data sources disagree — flagged explicitly.',
  },
};

/** 把 Yes/No 之类归一化的布尔值渲染成文案。 */
function yesNoText(v, lang) {
  const t = T[lang] || T.zh;
  if (v === true) return t.vipYes;
  if (v === false) return t.vipNo;
  return t.vipUnknown;
}

/**
 * 渲染站点属性回复。
 *
 * @param {object} d      接口/脚本返回的属性对象
 * @param {'zh'|'en'} lang
 * @param {boolean} degraded 是否走了本地副本降级
 */
export function renderSiteAttribute(d, lang = 'zh', degraded = false) {
  const t = T[lang] || T.zh;
  const name = d.site_name || d.site || '';

  if (!d.found) {
    return [t.notFound(d.site, d.candidates)].join('\n');
  }

  // 口径判定：**双保险** —— degraded 标志与 source 任一表明是副本，就标副本。
  // 只看其中一个会在「HTTP 没配直接走副本」时把副本说成实时
  // （2026-11-03 实测过一次正文标「实时」而日志标「本地副本」）。
  const isLocal = degraded || d.source === 'sqlite' || d.source === 'local';

  const lines = [];
  lines.push(`## ${t.header(name)}`);
  lines.push('');

  // VIP 判定 —— 主结论，放在最前面
  lines.push(`- VIP：${yesNoText(d.is_vip, lang)}`);

  // 三处判定不一致 —— 必须说，不能藏
  if (d.consistency === 'conflict') {
    lines.push(`- ${t.conflict}`);
  }

  // 其余属性字段（只列有值的）
  const fieldOrder = [
    'site_type', 'site_sub_type', 'region', 'province',
    'site_information', 'site_priority', 'site_class',
    'victims', 'fme_name',
  ];
  for (const key of fieldOrder) {
    const v = d[key];
    if (v === null || v === undefined || v === '') continue;
    lines.push(`- ${t.labels[key] || key}：${v}`);
  }

  // 枢纽站
  if (d.is_hub_site === true) lines.push(`- ${t.hubYes}`);
  else if (d.is_hub_site === false) lines.push(`- ${t.hubNo}`);
  else lines.push(`- ${t.hubUnknown}`);

  // 站号
  if (d.site_id !== null && d.site_id !== undefined && d.site_id !== '') {
    lines.push(`- 站号：${d.site_id}`);
  }

  lines.push('');
  lines.push(isLocal ? t.sourceLocal : t.sourceLive);

  return lines.join('\n');
}

/* -------------------------------- 主入口 -------------------------------- */

/**
 * 查询站点属性 —— HTTP 优先，失败降级本地 SQLite。
 *
 * @param {string} site
 * @param {{lang?:'zh'|'en'}} [opts]
 * @returns {Promise<{ok:boolean, data?:object, error?:string, degraded?:boolean}>}
 */
export async function querySiteAttribute(site, opts = {}) {
  const name = String(site || '').trim();
  if (!name) {
    return { ok: false, error: '站点名不能为空' };
  }

  const httpEnabled = CONFIG.ttStatsHttp !== false && !!CONFIG.myAppApiBase;
  if (httpEnabled) {
    try {
      const data = await fetchHttp(name);
      // ⚠️ degraded 必须与 source **严格对应**：
      // source=http → 实时（正文标「实时」）；source=sqlite → 副本（正文标「本地副本」）。
      // 两者错位会让正文与日志口径打架（2026-11-03 实测过一次）。
      return { ok: true, data, degraded: false };
    } catch (err) {
      if (process.env.DEBUG_TOOLS === '1') {
        console.error(`[工具] 站点属性 HTTP 失败：${err.message}`);
      }
    }
  }

  if (!fallbackAvailable()) {
    return {
      ok: false,
      error: '站点属性查询不可用（HTTP 未配置且本地降级脚本缺失）',
    };
  }
  const fb = await runPython(name);
  if (fb.error) return { ok: false, error: fb.error };
  // 降级结果的 source 强制为 sqlite（脚本给的），degraded=true —— 二者对齐。
  return { ok: true, data: { ...fb, source: fb.source || 'sqlite' }, degraded: true };
}
