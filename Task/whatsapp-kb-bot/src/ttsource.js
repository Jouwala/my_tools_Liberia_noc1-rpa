/**
 * 工单统计的**取数层** —— HTTP 优先，SQLite 降级。
 *
 * 从 src/ttquery.js 拆出来的（2026-10-07，该文件涨到 605 行超过 500 行上限）。
 * 拆分线是**职责**，不是行数：
 *   · ttsource.js（本文件）—— 只知道"去哪儿取数、取回来怎么归一"，
 *     不碰日期解析、不碰文案渲染；
 *   · ttquery.js            —— 日期/级别/状态的**解析** + 结果**渲染**，
 *     不关心数据是 HTTP 来的还是 SQLite 来的。
 * 这条线让两边的测试可以各自独立：本文件要真连服务，ttquery 的解析与渲染
 * 是纯函数（`scripts/test-tools.mjs` 全程离线跑的就是后者）。
 *
 * ## 两条数据源
 *
 *   ① HTTP：my_app 的 /api/tt-wo-dashboard/{overview,drilldown} —— 生产库
 *      PostgreSQL，**实时**；
 *   ② SQLite：scripts/tt-query.py 读 my_app/db/app.db —— 同步副本，**有延迟**。
 *
 * 为什么必须有 ②：src/tt.js:9 写过「之所以不用 HTTP 接口：那要求 my_app 服务在跑」。
 * 机器人要保持独立可用，my_app 挂了也得能答，只是答得旧一点。
 * 降级时**必须如实标注口径**（由渲染层打「本地副本」那句，见 ttquery.renderStats）。
 *
 * ## 时间字段统一用 alarm_occur_time
 *
 * my_app 的 `_time_filter`（backend/routers/tt_wo_dashboard.py:92）过滤的就是它。
 * 两条通道若各用一个字段，「今天有几个 P1」会得到两个不同答案，
 * 那是最难排查的一类故障——两边都"能跑"，只是数对不上。
 */
import { execFile } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { CONFIG, ROOT } from './config.js';

const FALLBACK_SCRIPT = resolve(ROOT, 'scripts', 'tt-query.py');

/** 与 src/tt.js:44 同一个解释器（可用 TT_PYTHON 覆盖）。 */
const PYTHON =
  process.env.TT_PYTHON ||
  'C:/Users/ZTEEMS/AppData/Local/Programs/Python/Python312/python.exe';

/** HTTP 超时。聚合接口要出全量统计，比单票查询慢；超时即降级，不重试。 */
const HTTP_TIMEOUT_MS = Number(process.env.TT_STATS_TIMEOUT_MS || CONFIG.ttStatsTimeoutMs || 15000);

/** SQLite 降级超时。副本在部分部署里位于网络盘，首次全表扫描实测可达数十秒。 */
const FALLBACK_TIMEOUT_MS = Number(process.env.TT_STATS_FALLBACK_TIMEOUT_MS || 60000);

/** 带超时地 fetch 一个 JSON 接口；失败一律抛，由调用方决定是否降级。 */
export async function fetchJson(url) {
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
  return res.json();
}

/** my_app 后端基址（去掉尾部斜杠）。 */
export function apiBase() {
  const base = String(CONFIG.myAppApiBase || '').replace(/\/+$/, '');
  if (!base) throw new Error('未配置 myAppApiBase');
  return base;
}

/** 判断一条工单是否未闭环。空状态也算未闭环（库里确有 status 为空的行）。 */
export function isOpenStatus(status) {
  const v = String(status || '').trim();
  return !v || !v.startsWith('Closed');
}

/**
 * 从 title 里抠出站名 —— 只在补查失败时兜底。
 *
 * `title` 的格式通常是 `<站号>.[<站名>]<告警名>`，例：`4406.[Wood camp]3G CELL DOWN`。
 * 但实测 **241/37223 行的 title 里没有方括号**，所以它只是**兜底**，
 * 真值走 enrichSiteNames 回本地表按主键查（那里 37223 行 site_name 无一为空）。
 * 抠不出来就退回站号 —— 有总比没有强，但不能因此报错。
 */
export function siteFromTitle(title, fallback) {
  const m = String(title || '').match(/\[([^\]]+)\]/);
  if (m && m[1].trim()) return m[1].trim();
  return fallback || '';
}

/** 样例单的截断上限：取「随便看看」与「点名要名单」两个用途里更大的那个。 */
function sampleCap() {
  // ⚠️ 必须取较大值，不能只看 ttStatsSampleLimit：
  // 渲染层在「用户点名要单号」时会展示到 ttStatsListLimit（默认 10）条，
  // 若这里只留 3 条，渲染层拿到手的就只有 3 条 —— 它再怎么切也切不出 10 条。
  // 2026-10-07 实测踩到：HTTP 路径只列了 3 单，降级路径却列了 6 单，
  // **同一个问题走两条通道给出不同长度的名单**，这种不一致最难排查。
  return Math.max(
    Number(CONFIG.ttStatsSampleLimit ?? 3),
    Number(CONFIG.ttStatsListLimit ?? 10)
  );
}

/* ------------------------------- HTTP 通道 ------------------------------- */

/**
 * 调 my_app 的 overview 接口（轻量聚合，**拿不到单号明细**）。
 *
 * 失败（服务没起 / 超时 / 非 2xx / 返回结构不合预期）**一律抛出**，
 * 由 queryTickets 捕获后降级 —— 这里不做降级决策，职责单一。
 */
async function fetchOverview({ start, end, severity, status }) {
  const url = new URL('/api/tt-wo-dashboard/overview', apiBase());
  if (start) url.searchParams.set('time_start', start);
  if (end) url.searchParams.set('time_end', end);

  const data = await fetchJson(url);
  const sev = data?.tt_stats?.ticket_severity;
  if (!data?.summary || !sev) throw new Error('my_app 返回结构不符合预期');

  // ⚠️ overview **不支持按级别过滤**（`tt_wo_dashboard.py:300` 的入参只有
  // time_start / time_end / region / owner / adv，没有 severity）。
  // 所以「昨天有多少 P2」不能拿 tt_total 去答 —— 那是全量总数。
  // 这里从 ticket_severity 分桶里取对应级别的数；
  // 级别的「未闭环」数接口给不了（分桶不交叉），见下面的 can_split_status。
  const sevCount = severity ? Number(sev[severity] || 0) : null;
  const total = severity ? sevCount : Number(data.summary.tt_total || 0);

  // 未闭环数：接口没有该参数，从 status 分桶里自行汇总。
  // 但 status 分桶是**全量**的，不与级别交叉。按级别查时拿它算未闭环
  // 会得到「全量未闭环」，比真实值大得多（2026-10-06 实测：P2=47，
  // 全量未闭环=67 —— 后者显然不是「P2 未闭环」）。
  // 所以按级别查时不在这里算，改由调用方走 drilldown。
  const statusMap = data.tt_stats.status || {};
  const closed = Object.entries(statusMap)
    .filter(([k]) => String(k).startsWith('Closed'))
    .reduce((n, [, v]) => n + Number(v || 0), 0);
  const canSplitStatus = !severity;

  return {
    source: 'http',
    start,
    end,
    severity,
    status,
    total,
    closed: canSplitStatus ? closed : null,
    open: canSplitStatus ? Math.max(0, total - closed) : null,
    // 级别过滤时仍带上分布，供渲染层核对（渲染层会因 severity 非空而不展示）
    by_severity: sev,
    can_split_status: canSplitStatus,
    samples: [],
    latest: null, // HTTP 走实时库，不需要「数据截止时间」这个降级提示
  };
}

/**
 * 下钻取明细行 —— 同时供「精确交叉计数」和「列出单号」两个用途。
 *
 * ## 为什么必须另开一次调用
 *
 * overview 的 `ticket_severity` 与 `status` 是两个**互不交叉**的分桶，
 * 既推不出「P2 且未闭环」，也拿不到任何一条单号。
 * `/drilldown` 支持 `dimension=ticket_severity&value=P2` 精确下钻，
 * 回来的行里有 `status` 和 `tt_no`，两个问题一次解决。
 *
 * ## 代价要说清楚
 *
 * drilldown 会**把符合条件的行全部返回**（没有分页参数），
 * 「本月 P2」这种量级能有几百行。所以只在真需要明细时才调
 * （见 queryTickets 的分支），且拿回来的行要**本地截断**再渲染。
 */
async function fetchDrilldown({ start, end, severity, status, limit }) {
  if (!severity) throw new Error('drilldown 需要按级别下钻');

  const url = new URL('/api/tt-wo-dashboard/drilldown', apiBase());
  url.searchParams.set('type', 'tt');
  url.searchParams.set('dimension', 'ticket_severity');
  url.searchParams.set('value', severity);
  if (start) url.searchParams.set('time_start', start);
  if (end) url.searchParams.set('time_end', end);
  // 只取需要的行数（2026-10-18）。此前一次「本月 P2」要拉回 330KB 全量行，
  // 而调用方最终只用前 ttStatsListLimit(10) 条 —— 纯浪费。
  // limit=0/undefined 表示不限，保持与改造前一致。
  if (limit > 0) url.searchParams.set('limit', String(limit));

  const data = await fetchJson(url);
  const rows = Array.isArray(data?.data) ? data.data : [];
  // 服务端在截断时返回的**总数**（不受 limit 影响）。未截断时为 undefined，
  // 此时下面的 len() 就是真值。
  const serverCount = Number(data?.count);
  const truncated = data?.truncated === true;

  const openRows = rows.filter((r) => isOpenStatus(r.status));
  const closedRows = rows.filter((r) => !isOpenStatus(r.status));

  // 按状态决定「计数主体」是哪一批行；status=all 时全都要
  const picked = status === 'open' ? openRows : status === 'closed' ? closedRows : rows;

  // 样例按发生时间倒序取最新的几条 —— 用户要的是"最近这几单是什么"
  const samples = picked
    .slice()
    .sort((a, b) =>
      String(b.alarm_occur_time || '').localeCompare(String(a.alarm_occur_time || ''))
    )
    .slice(0, sampleCap())
    .map((r) => ({
      tt_no: r.tt_no || '',
      // 站名优先取 title 里的（drilldown 没有 site_name 字段），退回站号
      site_name: siteFromTitle(r.title, r.site_id),
      ticket_severity: r.ticket_severity || '',
      status: r.status || '',
      alarm_occur_time: r.alarm_occur_time || '',
    }));

  // drilldown 不返回 site_name，上面是从 title 正则抠的（241/37223 行抠不出来）。
  // 这里回本地表按单号补一次真值 —— 只补这几条样例，代价是一次点查。
  await enrichSiteNames(samples);

  // 计数口径（2026-10-18 加 limit 后必须区分）：
  //   · 未截断 → 行数就是真值，与改造前完全一致；
  //   · 已截断 → **只能用服务端给的 count**，本地行数是被砍过的。
  // 不加区分的话，用户问「本月 P2 多少单」会拿到 10（limit 值），
  // 而不是 879 —— 比慢更糟。
  const totalCount = truncated && Number.isFinite(serverCount) ? serverCount : picked.length;
  const canSplit = !truncated;
  // 截断时，未闭环数由服务端在同一次查询里算好（`status_buckets`），
  // 不能靠再发一次请求 —— 那会把 879 行再拉一遍，等于把优化抵消掉。
  const serverBuckets = data?.status_buckets || null;

  // 未闭环/已闭环计数：
  //   · 未截断 → 本地按 isOpenStatus 分组（与改造前完全一致）；
  //   · 已截断 → 用服务端同一查询里算好的 status_buckets（口径见后端
  //     _OPEN_STATUS_SQL_NOTE）；若服务端没给，退回 null 让渲染层跳过该行，
  //     绝不用样本行去推算 —— 那会给出一个偏小的假数字。
  let openCount = canSplit ? openRows.length : null;
  let closedCount = canSplit ? closedRows.length : null;
  if (truncated && serverBuckets) {
    openCount = Number(serverBuckets.open);
    closedCount = Number(serverBuckets.closed);
    if (!Number.isFinite(openCount)) openCount = null;
    if (!Number.isFinite(closedCount)) closedCount = null;
  }

  return {
    source: 'http',
    start,
    end,
    severity,
    status,
    total: totalCount,
    open: openCount,
    closed: closedCount,
    by_severity: { [severity]: totalCount },
    can_split_status: true,
    samples,
    detail_total: totalCount,
    truncated,
    latest: null,
  };
}

/* ------------------------------ SQLite 降级 ------------------------------ */

/** 跑 scripts/tt-query.py，返回结构化结果。永不抛异常（失败返回 {error}）。 */
function runPython(args) {
  return new Promise((done) => {
    execFile(
      PYTHON,
      [FALLBACK_SCRIPT, ...args],
      {
        timeout: FALLBACK_TIMEOUT_MS,
        encoding: 'utf8',
        windowsHide: true,
        maxBuffer: 2 * 1024 * 1024,
        // 与 src/tt.js:251 同因：进程环境没有 LANG，Python 的 stdout 会退化成
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

/**
 * 给样例单补真站名 —— 就地改写 samples[i].site_name。
 *
 * 为什么非补不可：`/drilldown` **不返回 site_name**（只有 site_id），
 * 于是回复里只能显示 `TT202610020060（5021）`，群里没人认得出 5021 是哪个站。
 * 本地 `eflow_tt` 表里 `site_name` 是全的（实测 37223 行空值 0 行），
 * 且 `tt_no` 是主键 —— 一次点查就能拿到真值，比从 title 正则猜可靠得多
 * （title 正则实测有 241/37223 行抠不出方括号）。
 *
 * 失败**静默放过**：站名只是个展示字段，补不到就退回站号，
 * 绝不能因为补字段失败而让已经查到的统计数字作废。
 */
async function enrichSiteNames(samples) {
  const nos = samples.map((s) => s.tt_no).filter(Boolean);
  if (!nos.length || !fallbackAvailable()) return;
  const res = await runPython(['--site-names', nos.join(',')]);
  const map = res?.site_names;
  if (!map) return;
  for (const s of samples) {
    const real = map[s.tt_no];
    if (real) s.site_name = real;
  }
}

/** 跑 scripts/tt-query.py 做聚合，返回结构化结果。永不抛异常。 */
function runFallback({ start, end, severity, status, site, keyword }) {
  const args = [];
  if (start) args.push('--start', start);
  if (end) args.push('--end', end);
  if (severity) args.push('--severity', severity);
  if (status && status !== 'all') args.push('--status', status);
  if (site) args.push('--site', site);
  if (keyword) args.push('--keyword', keyword);
  // 与 HTTP 通道的 fetchDrilldown 取同一个上限，避免两条通道给出不同长度的名单
  args.push('--limit', String(sampleCap()));
  return runPython(args);
}

/** 降级通道是否可用（脚本 + 解释器都在）。 */
export function fallbackAvailable() {
  return existsSync(FALLBACK_SCRIPT) && existsSync(PYTHON);
}

/* -------------------------------- 主入口 -------------------------------- */

/**
 * 执行聚合查询 —— HTTP 优先，失败降级到本地 SQLite。
 *
 * @param {{start?:string,end?:string,severity?:string,status?:string,site?:string}} spec
 * @returns {Promise<{ok:boolean, data?:object, error?:string, degraded?:boolean}>}
 */
export async function queryTickets(spec) {
  const q = {
    start: spec.start || null,
    end: spec.end || null,
    severity: spec.severity || null,
    status: spec.status || 'all',
    site: spec.site || null,
    keyword: spec.keyword || null,
  };
  const wantList = !!spec.list;

  // 只传了 start 没传 end（或反之）时补齐成单日 ——
  // 接口侧缺省是「不过滤」，那会返回全库 3 万多条，不是用户想要的。
  if (q.start && !q.end) q.end = q.start;
  if (!q.start && q.end) q.start = q.end;

  const httpEnabled = CONFIG.ttStatsHttp !== false && !!CONFIG.myAppApiBase;
  // 关键字过滤同样只有本地库支持（见 tt-query.py 的 --keyword），走 overview
  // 会返回**不带关键字过滤**的全网总数 —— 那正是 2026-10-26 的故障形态
  // （问 Fiber 相关，答全网 753）。宁可慢一点读本地副本，也不能答一个假数。
  if (httpEnabled && !q.site && !q.keyword) {
    // 站点过滤 overview 接口不支持（要 JOIN 站点表的高级过滤参数），
    // 这种情况直接走本地库 —— 那里有 site_name / site_id 能做模糊匹配。
    try {
      // 走 drilldown（而非轻量的 overview）的条件**收窄**为：
      //   ① 用户点名要单号（「请输出TT单的ID」/「give me the ticket IDs」）
      //      —— overview 一条单号都不给；
      //   ② 问的是「某级别 + 某闭环状态」—— overview 两个分桶不交叉，
      //      拿 status 桶直接算会把全量未闭环当成该级别的未闭环。
      // ❌ 不再用「只要带级别就 drilldown」：drilldown **把符合条件的行全部
      //    返回（无分页）**，问「本月几个 P1」只想要个数却拉全月行，
      //    实测 21s（HTTP 15s 超时 → 降级 SQLite 建索引）。纯「几个 P1」
      //    改走 overview 的 ticket_severity 分桶，数百毫秒。
      //    代价：走 overview 时不给样例单号（渲染层已处理「要名单却没明细」的提示）。
      const needsDrilldown = wantList || (q.severity && q.status !== 'all');
      if (needsDrilldown && q.severity) {
        // 只有「纯要名单」才传 limit（2026-10-18）：
        //   · wantList 且 status=all → 只需要前 N 条单号，全量没有意义；
        //   · 级别 + 闭环状态交叉 → **必须拿全量行**才能本地按 status 分组，
        //     传 limit 会让 open/closed 两个数变成"前 N 行里的分布"，是错的。
        const limit = wantList && q.status === 'all' ? sampleCap() : 0;
        return { ok: true, data: await fetchDrilldown({ ...q, limit }) };
      }
      return { ok: true, data: await fetchOverview(q) };
    } catch (err) {
      // 落到下面降级
      if (process.env.DEBUG_TOOLS === '1') console.error(`[工具] HTTP 聚合失败：${err.message}`);
    }
  }

  if (!fallbackAvailable()) {
    return { ok: false, error: '工单统计不可用（HTTP 未配置且本地降级脚本缺失）' };
  }
  const fb = await runFallback(q);
  if (fb.error) return { ok: false, error: fb.error };
  // 让降级结果也能显示「还有 N 单未列出」—— 脚本返回的 samples 已被 limit 截断，
  // detail_total 用过滤后的 total 代替（SQLite 侧的 total 就是过滤后行数）。
  fb.detail_total = fb.total;
  // 渲染层靠 keyword 判断标题要不要写「Fiber 相关」—— 降级结果里若丢了这一项，
  // 用户看到的会是一个**没有条件的裸总数**，正是本次故障的形态。
  fb.keyword = fb.keyword || q.keyword || '';
  return { ok: true, data: fb, degraded: true };
}
