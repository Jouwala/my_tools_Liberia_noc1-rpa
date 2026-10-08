/**
 * 按站点查 eFlow **实时活动告警** —— 「这个站现在有没有告警 / up 没 up」。
 *
 * ## 为什么单独开一条通道
 *
 * 用户问「*Palm Bay* check if this site is up or not? and if have TT?」「check alarm
 * for site name X form eflow」——问的是**站点的实时告警状态**。改造前这类问题会被
 * 路由到 `query_tickets`（工单统计），而工单统计按站点名匹配≈0 单，于是回一句
 * `tickets: 0`。**「0 张工单」被读成了「站点没告警」——答非所问，而且是个自信的错。**
 *
 * 答案在 eFlow 的活动告警接口里，不在工单表里。所以：
 *   · 工单统计（query_tickets）：回答「多少单 / 有没有单」——**工单**维度；
 *   · 本通道（query_site_alarms）：回答「这个站有没有告警 / 什么告警」——**告警**维度。
 * 两者是**不同的事实**，不能互相顶替。
 *
 * ## 实现方式：走桥接脚本，不直连
 *
 * Node 起子进程跑 `scripts/eflow-live-alarms.py`，它复用 my_app 的
 * `eflow_alarm_service._fetch_alarm_pipeline`（与告警看板/同步任务同一套 payload），
 * 拉当前活动告警后**本地按站名过滤**。凭据只读 my_app 那一份，机器人侧不另存密码
 * （与 eflow-live-tt.py 完全同构）。
 *
 * 为什么不把站点过滤直接下推给 eFlow：仓库里**没有** `/activealarms/table` 带站点
 * 过滤的抓包样例，键名靠猜会 400 或**静默返回空**——后者最危险，会把「查不了」
 * 伪装成「没告警」。活动告警总量很小（实测几十条），拉全量再本地过滤代价可忽略。
 *
 * ## 退出码语义（与脚本严格对齐，绝不混淆「无告警」与「查不了」）
 *   0 有活动告警         → answered，附告警明细
 *   1 站点干净（无活动告警）→ answered，明确说「当前无活动告警」
 *   2 通道不可用（缺解释器）→ 未答，让用户去 eFlow 看板
 *   3 真出错（登录/网络）  → 未答，可重试
 *   4 查无此站           → 未答，提示核对站名
 */
import { execFile } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { CONFIG, ROOT } from './config.js';

const SCRIPT = resolve(ROOT, 'scripts', 'eflow-live-alarms.py');

/** 是否启用（config.json 的 `ttSiteAlarmFallback`，默认开）。关掉则本工具不可用。 */
function enabled() {
  const v = CONFIG.ttSiteAlarmFallback;
  if (v === false || v === 'false' || v === 0 || v === '0') return false;
  if (process.env.TT_SITE_ALARM_FALLBACK === '0' || process.env.TT_SITE_ALARM_FALLBACK === 'false') {
    return false;
  }
  return existsSync(SCRIPT);
}

// my_app 的后端运行环境（含 pandas + sqlalchemy）。与 tt.js 用同一常量约定。
const PYTHON =
  process.env.TT_PYTHON ||
  'C:/Users/ZTEEMS/AppData/Local/Programs/Python/Python312/python.exe';

// 活动告警拉全量（几十条）+ eFlow 登录，实测几秒量级；给宽一点防登录慢。
const TIMEOUT_MS = Number(process.env.TT_SITE_ALARM_TIMEOUT_MS || CONFIG.ttSiteAlarmTimeoutMs || 180000);

/* ------------------------------- 文案 ------------------------------- */

const T = {
  zh: {
    header: (site) => `【${site}】告警状态（eFlow 实时）`,
    hasAlarms: (n) => `站点当前有 ${n} 条活动告警：`,
    clean: (site) => `【${site}】当前**没有**活动告警（eFlow 实时活动告警列表里查无此站）。`,
    // 告警行：站名 | 告警 | 级别 | 持续 | 单号
    line: (a) =>
      `- ${a.alarm || '（未知告警）'}` +
      (a.severity ? `（${a.severity}）` : '') +
      (a.duration ? `，持续 ${a.duration}` : '') +
      (a.code ? `，码 ${a.code}` : '') +
      (a.tt ? `，已建单 ${a.tt}` : '，**尚未建单**'),
    region: (a) => (a.region ? `，区域 ${a.region}` : ''),
    notFound: (site) =>
      `eFlow 里没找到叫「${site}」的站点。请核对站名拼写（可用站表里的正式英文名）。`,
    unavailable: '我这边连不上 eFlow 查告警，暂时给不了结论，请到 eFlow 告警看板确认。',
    error: (detail) =>
      `查 eFlow 告警时出错了${detail ? `：${detail}` : ''}。请稍后再试。`,
    source: '来源：eFlow 活动告警接口（实时）',
    footer: '（若告警刚发生/刚恢复，可能有秒级延迟）',
  },
  en: {
    header: (site) => `Alarm status for ${site} (eFlow live)`,
    hasAlarms: (n) => `The site currently has ${n} active alarm(s):`,
    clean: (site) => `${site} has **no** active alarms right now (not present in the eFlow live active-alarm list).`,
    line: (a) =>
      `- ${a.alarm || '(unknown alarm)'}` +
      (a.severity ? ` (${a.severity})` : '') +
      (a.duration ? `, for ${a.duration}` : '') +
      (a.code ? `, code ${a.code}` : '') +
      (a.tt ? `, TT ${a.tt}` : `, **no TT yet**`),
    region: (a) => (a.region ? `, region ${a.region}` : ''),
    notFound: (site) =>
      `No site named "${site}" found in eFlow. Please check the spelling (use the official site name).`,
    unavailable:
      `I couldn't reach eFlow to check alarms right now, so I can't give a conclusion — please confirm on the eFlow alarm dashboard.`,
    error: (detail) =>
      `Something went wrong checking eFlow alarms${detail ? `: ${detail}` : ''}. Please try again shortly.`,
    source: 'Source: eFlow active-alarm API (live)',
    footer: '(if an alarm just raised/cleared, there may be a few seconds of lag)',
  },
};

/* ------------------------------ 渲染 ------------------------------ */

/**
 * @param {object} obj   脚本 stdout 的 JSON
 * @param {'zh'|'en'} lang
 * @param {number} code  脚本退出码
 */
function render(obj, lang, code) {
  const t = T[lang] || T.zh;
  const site = obj?.site_query || '';

  if (code === 4) return { answered: false, text: t.notFound(site) };
  if (code === 2) return { answered: false, text: t.unavailable };

  const matched = Number(obj?.matched || 0);
  if (code === 1 || matched === 0) {
    // 站点干净：这是**明确结论**（有依据），故 answered=true。
    return { answered: true, text: t.clean(site) };
  }

  const alarms = Array.isArray(obj.alarms) ? obj.alarms : [];
  const lines = [t.header(site), t.hasAlarms(matched)];
  for (const a of alarms.slice(0, 10)) {
    lines.push(t.line(a) + t.region(a));
  }
  if (alarms.length > 10) {
    lines.push(lang === 'en' ? `…and ${alarms.length - 10} more.` : `…还有 ${alarms.length - 10} 条未列出。`);
  }
  lines.push('');
  lines.push(t.source);
  lines.push(t.footer);
  return { answered: true, text: lines.join('\n') };
}

/* ------------------------------ 执行 ------------------------------ */

/**
 * @param {string} site  站点名（原始）
 * @param {'zh'|'en'} lang
 * @returns {Promise<{text:string, answered:boolean, channel:'sitealarm', stats?:object}>}
 */
export async function querySiteAlarms(site, lang = 'zh') {
  const t = T[lang] || T.zh;
  const q = String(site || '').trim();
  if (!q) {
    return { answered: false, channel: 'sitealarm', text: t.notFound(''), stats: { totalMs: 0 } };
  }
  if (!enabled()) {
    return { answered: false, channel: 'sitealarm', text: t.unavailable, stats: { totalMs: 0 } };
  }

  const t0 = Date.now();
  return new Promise((resolvePromise) => {
    execFile(
      PYTHON,
      [SCRIPT, q, '--json'],
      {
        timeout: TIMEOUT_MS,
        encoding: 'utf8',
        windowsHide: true,
        maxBuffer: 8 * 1024 * 1024,
        env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
      },
      (err, stdout, stderr) => {
        const ms = Date.now() - t0;
        const out = (stdout || '').trim();
        // 退出码：0 有告警 / 1 干净 / 2 不可用 / 3 出错 / 4 无此站。
        // 除 2/3 外都有 stdout JSON。err.code 拿退出码（execFile 在非 0 时也带 stdout）。
        const codeFromErr = typeof err?.code === 'number' ? err.code : null;

        if (out) {
          try {
            const obj = JSON.parse(out);
            const rendered = render(obj, lang, codeFromErr ?? 0);
            return resolvePromise({
              ...rendered,
              channel: 'sitealarm',
              stats: { totalMs: ms, matched: obj?.matched, total_active: obj?.total_active },
            });
          } catch {
            /* 落到下面按失败处理 */
          }
        }

        // 无 stdout：区分「通道不可用」(2) 与「真出错」(3)
        const detail = (stderr || err?.message || '').trim().split('\n').pop() || '';
        if (codeFromErr === 2) {
          return resolvePromise({
            answered: false,
            channel: 'sitealarm',
            text: t.unavailable,
            stats: { totalMs: ms },
          });
        }
        return resolvePromise({
          answered: false,
          channel: 'sitealarm',
          text: t.error(detail),
          stats: { totalMs: ms },
        });
      }
    );
  });
}

export const _internal = { enabled, SCRIPT };
