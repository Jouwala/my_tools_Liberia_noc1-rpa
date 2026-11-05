/* -*- coding: utf-8 -*-
 * sitelist.js - 站名清单（用来校验「抽出来的站名是不是真站名」）
 * =================================================================
 *
 * 为什么需要这个
 * --------------
 * 机器人的站名抽取是**规则**驱动的：句子里的英文大写词会被当成站名候选
 * （规则见 tools.js 的 extractSiteName ②「纯英文专名」）。于是
 *
 *     最近7天全网有多少条 Critical 级别的告警
 *                    ^^^^^^^^^
 * 里的 "Critical"（告警级别）会被抽成站名，机器人拿着它去查告警表，
 * 查不到就回一句「查到了 Critical，但历史告警没有记录」——
 * 那是**假答案**：库里明明有近两万行历史告警。
 *
 * 有了站名清单，规则层就能把「明显不是站名」的候选剔掉，
 * 整句改走 NL2SQL 做跨站统计（query_data）。
 *
 * 清单来源
 * --------
 * my_app 的 `GET /api/bot-data/sites` —— eflow_site / ipt_power_sites /
 * eflow_wo / history_alarm 四张表的**站名并集**（约 900 个）。
 * 必须是并集：实测 "Wood Camp 2" 只在 ipt_power_sites 里，
 * 只认 eflow_site 会把真实站名误杀。
 *
 * 时效
 * ----
 * 站名主数据变化很慢（天级），TTL 10 分钟足够；清单拉不到时
 * `isKnownSite()` 返回 null（=无法判断），调用方按「不拦截」处理，
 * 绝不能因为清单不可用就把所有站名都毙掉。
 */

import { CONFIG } from './config.js';

/** 清单缓存有效期：10 分钟。 */
const TTL_MS = Number(process.env.SITE_LIST_TTL_MS || 10 * 60 * 1000);

/** HTTP 超时。清单是辅助信息，不该拖慢主流程。 */
const HTTP_TIMEOUT_MS = Number(process.env.SITE_LIST_TIMEOUT_MS || 8000);

/** @type {Set<string>|null} 小写归一后的站名集合；null = 尚未加载成功。 */
let cache = null;

/** @type {number} 上次成功拉取的时间戳。 */
let fetchedAt = 0;

/** @type {Promise<void>|null} 正在进行的拉取，避免并发重复请求。 */
let inflight = null;

/** my_app 后端基址（去掉尾部斜杠）。 */
function apiBase() {
  const base = String(CONFIG.myAppApiBase || '').replace(/\/+$/, '');
  if (!base) throw new Error('未配置 myAppApiBase');
  return base;
}

/** 站名归一：小写 + 折叠空白 + 去掉首尾标点。 */
function norm(name) {
  return String(name || '')
    .toLowerCase()
    .replace(/[\s ]+/g, ' ')
    .replace(/^[^\w一-鿿]+|[^\w一-鿿]+$/g, '')
    .trim();
}

/**
 * 拉取站名清单（带 TTL 缓存）。
 *
 * @param {boolean} force 忽略 TTL 强制刷新
 * @returns {Promise<Set<string>|null>} 归一后的站名集合；失败返回 null
 */
export async function ensureSiteList(force = false) {
  if (!force && cache && Date.now() - fetchedAt < TTL_MS) return cache;
  if (inflight) return inflight;

  inflight = (async () => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), HTTP_TIMEOUT_MS);
    try {
      const url = new URL('/api/bot-data/sites', apiBase());
      const res = await fetch(url, { signal: ctrl.signal });
      if (!res.ok) throw new Error(`my_app 返回 ${res.status}`);
      const data = await res.json();
      const list = Array.isArray(data?.sites) ? data.sites : [];
      if (!list.length) throw new Error('站名清单为空');
      const set = new Set();
      for (const n of list) {
        const v = norm(n);
        if (v) set.add(v);
      }
      cache = set;
      fetchedAt = Date.now();
      return cache;
    } catch (err) {
      if (process.env.DEBUG_TOOLS === '1') {
        console.error(`[站名清单] 拉取失败：${err.message}`);
      }
      // ⚠️ 拉取失败**不抛** —— 清单是辅助信息，拿不到就按「无法判断」处理。
      return null;
    } finally {
      clearTimeout(timer);
      inflight = null;
    }
  })();

  return inflight;
}

/**
 * 告警级别 / 度量词 —— **任何语境下都不可能是站名**，硬排除。
 *
 * 双保险：即使长度下限规则被绕过，这些词也不会被当成站名。
 */
const NEVER_SITE = new Set([
  'critical', 'major', 'minor', 'warning', 'fatal', 'info', 'severity',
  'priority', 'total', 'count', 'number', 'summary',
]);

/**
 * 站名是否真实存在。
 *
 * 判定分三级：
 *   ① **完全相等**（归一后）→ 存在；
 *   ② 清单里的站名**包含**候选（如 "wood camp" ⊃ "woodcamp"）→ 存在；
 *   ③ 候选**包含**清单里的站名（如 "wood camp 2" ⊃ "wood camp"）→ 存在，
 *      但**被包含的站名至少要 4 个字符**。
 *
 * ⚠️ ③ 的长度下限是实测踩出来的：生产库站名里有 "iti" / "r2" / "btc" / "cvi"
 * 这类 2~3 字母缩写，而 `"critical".includes("iti")` 为真 —— 不设下限的话，
 * 英文告警级别 Critical 会被判成站名，跨站统计题就永远进不了 NL2SQL。
 *
 * 判定整体是**宽松**的：现场写法千奇百怪（"Woodcamp" / "Wood Camp."），
 * 过度严格会把真实站名毙掉，比放过一个假站名更糟。
 *
 * @param {string} name 候选站名
 * @returns {boolean|null} true/false；**清单未就绪时返回 null（无法判断）**
 */
export function isKnownSite(name) {
  if (!cache) return null;
  const n = norm(name);
  if (!n) return false;
  if (NEVER_SITE.has(n)) return false;
  if (cache.has(n)) return true;
  for (const s of cache) {
    // ② 站名包含候选
    if (s.length >= 3 && s.includes(n)) return true;
  }
  for (const s of cache) {
    // ③ 候选包含站名（站名至少 4 字符，避开 iti / r2 这类缩写）
    if (s.length >= 4 && n.includes(s)) return true;
  }
  // ④ **去空格后再比** —— "Woodcamp" 与 "Wood Camp" 是同一个站。
  //    现场手写/口述经常连写，不认的话会把真实站名毙掉。
  //    ⚠️ 不能加 "nc !== n" 的条件：候选**没有**空格时 nc === n，
  //    而那正是要处理的场景（候选无空格、站名有空格）。
  const nc = n.replace(/\s+/g, '');
  if (nc.length >= 3) {
    if (cache.has(nc)) return true;
    for (const s of cache) {
      const sc = s.replace(/\s+/g, '');
      if (sc.length >= 4 && (sc.includes(nc) || nc.includes(sc))) return true;
    }
  }
  return false;
}

/** 清单是否已就绪。 */
export function siteListReady() {
  return cache !== null;
}

/** 清单里的站名数量（调试用）。 */
export function siteListSize() {
  return cache ? cache.size : 0;
}
