/**
 * TT 单分析 —— 调用 my_app 的工单库做实时级别核查。
 *
 * 与 RAG 的分工很明确：
 *   知识库（RAG）回答「规则是什么」——静态知识，向量检索就够；
 *   这里回答「这一单现在什么情况」——必须实时查库，所以走独立通道。
 *
 * 实现方式：Node 起子进程跑 scripts/tt-analyze.py 渲染。
 * 之所以还留这条子进程路径：它只依赖「工单库文件可读」，my_app 服务挂了也能用，
 * 机器人因此保持独立可用（见 analyzeTt 的第 ③ 步）。
 *
 * ## 取数顺序（2026-10-28 调整）
 *
 *   ① PG 实时库（my_app HTTP）—— 首选，数据最全最新。
 *   ② eFlow 实时拉取 —— PG 说「没这单」或 PG 请求失败时**直接走这里**。
 *   ③ 本地 SQLite 副本 —— 只在 ①② 都拿不到时兜底，命中必须标「可能滞后」。
 *
 * 为什么把 ③ 从第二位挪到最后：那份副本由 `pg_to_sqlite_sync` 每 12 小时
 * 才重建一次，最坏滞后半天；而 eFlow 是数据源头、PG 每小时同步一次。
 * 让一份 12 小时前的数据挡在实时源前面，等于**用旧答案覆盖新答案** ——
 * 2026-10-28 实测：TT202610280006（00:25 建单）在 PG 里有、在副本里没有，
 * 若按旧顺序且 PG 请求失败，用户拿到的会是「查无此单」，而真相是「有，只是副本旧」。
 */
import { execFile } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { CONFIG, ROOT } from './config.js';
import { pickText } from './lang.js';
// 复用聚合通道已验证的 HTTP 取数原语（超时 / 基址 / 错误语义），
// 避免在本文件再抄第三份超时与降级逻辑。
import { fetchJson, apiBase } from './ttsource.js';

const SCRIPT = resolve(ROOT, 'scripts', 'tt-analyze.py');

/**
 * eFlow 实时兜底桥接脚本。
 *
 * 本地工单库同步有延迟，用户报的单号常常比库里最新的还新。以前这种情况直接回
 * 「库里没有 + 库内最新单号」，用户拿不到任何数据 —— 但 my_app 其实**已经有**
 * 实时按单号查 eFlow 的能力（`eflow_data_mapper.fetch_tt_live`，见 my_app 的
 * `.trae/documents/eflow-tt-real-time-fallback.md`）。这里把它接进 TT 通道。
 */
const LIVE_SCRIPT = resolve(ROOT, 'scripts', 'eflow-live-tt.py');

/**
 * 实时兜底是否启用（config.json 的 `ttLiveFallback`，默认开）。
 * 关掉后行为与改造前一致：本地 miss 就直接回「工单库里没有找到」。
 */
function liveFallbackEnabled() {
  const v = CONFIG.ttLiveFallback;
  if (v === false || v === 'false' || v === 0 || v === '0') return false;
  if (process.env.TT_LIVE_FALLBACK === '0' || process.env.TT_LIVE_FALLBACK === 'false') return false;
  return existsSync(LIVE_SCRIPT);
}

/**
 * 单号分析是否优先走 my_app 的 PG 实时接口（config.json 的 `ttAnalysisHttp`，默认开）。
 *
 * 为什么要有这条通道（2026-10-15）：``tt-analyze.py`` 只读本地 SQLite 副本，
 * 而副本由 ``pg_to_sqlite_sync`` 刷新、cron 每 12 小时一次 —— PG 里数据已更新/恢复后，
 * 机器人最坏要再等 12 小时才看见，群里因此投诉「数据每时都在更新，为什么查不到」。
 * 于是让单号分析**优先**读 PG 实时库，SQLite 仅作降级（my_app 没起 / HTTP 失败时），
 * 与聚合统计通道（src/ttsource.js）同构。
 *
 * 关掉（false）即回到改造前：只走本地 SQLite + eFlow 实时兜底。
 */
function analysisHttpEnabled() {
  const v = CONFIG.ttAnalysisHttp;
  if (v === false || v === 'false' || v === 0 || v === '0') return false;
  if (process.env.TT_ANALYSIS_HTTP === '0' || process.env.TT_ANALYSIS_HTTP === 'false') return false;
  return !!CONFIG.myAppApiBase;
}

/**
 * 从 my_app 的 PG 实时接口取一条工单行。
 *
 * 返回 `{tt: <行|null>, wo: <行|null>}`；**任何失败都抛**，由调用方决定降级
 *（与 ttsource.fetchJson 同契约：拿不到就抛，不在取数层做降级决策）。
 *
 * ``found:false``（接口正常工作、但确实没这一单）与「请求失败」是两回事：
 *   · found:false → 返回 {tt:null}，调用方据此走**本地库**（本地可能有、也可能没有）；
 *   · 请求失败   → 抛，调用方据此也走本地库。
 * 两者最终都降级到本地库，但分开表达便于日志与后续细分。
 *
 * WO 行仅在 TT 命中且带 wo_no 时才查 —— 时间轴「WO派单 / 现场处置」两跳要用。
 */
async function fetchRowsHttp(ttNo) {
  const base = apiBase();
  const ttRes = await fetchJson(new URL(`/api/tt-wo-dashboard/tt/${encodeURIComponent(ttNo)}`, base));
  const tt = ttRes && ttRes.found ? ttRes.row : null;
  if (!tt) return { tt: null, wo: null };

  let wo = null;
  const woNo = String(tt.wo_no || '').trim();
  if (woNo) {
    try {
      const woRes = await fetchJson(new URL(`/api/tt-wo-dashboard/wo/${encodeURIComponent(woNo)}`, base));
      if (woRes && woRes.found) wo = woRes.row;
    } catch {
      // WO 拿不到不算致命：时间轴那两跳会退回「未证实」，TT 主体分析照常。
      // 与 tt-analyze.py 的 fetch_wo（查不到返回 None）同语义，故静默。
      wo = null;
    }
  }
  return { tt, wo };
}

// my_app 的后端运行环境（含 sqlite3 + openpyxl）
const PYTHON =
  process.env.TT_PYTHON ||
  'C:/Users/ZTEEMS/AppData/Local/Programs/Python/Python312/python.exe';

// 超时按**最坏情况**给，不是按常规查询。
// 常规查询走本地索引约 1.3 秒；但索引失效时（工单库被整体重排）要整表重建，
// 而全表扫描在 Y 盘上波动极大 —— 实测同一台机器上从 11 秒到 **100 秒**都出现过
// （`SELECT count(*) FROM eflow_tt` 实测 100.0s）。
// 原先的 90 秒会正好卡在这个区间里，让「重建」变成「超时」。
const TIMEOUT_MS = Number(process.env.TT_TIMEOUT_MS || 180000);

/**
 * 工单号形态：TT / WO + 至少 6 位数字（实测形如 TT202609150073、WO202609220055）。
 *
 * ⚠️ 必须同时收 WO —— 曾经只认 TT，后果是**静默答错**而不是答不出：
 * 用户问 `WO202609220055 Please analyze this Work Order.`，WO 号抽不出来
 * （extractTtNo → null），于是落到知识库通道，模型看到 `WO` 前缀把它当成
 * PCT 专利文献号，煞有介事地回答「资料里没有该专利的技术内容」——
 * 一个自信的、跨领域的错误答案。而底层脚本本来就支持 WO
 * （eflow_tt.wo_no 列可反查父单），属于纯路由遗漏。
 */
const TT_RE = /\b(?:TT|WO)\d{6,}\b/gi;

/** 从问题里抽出**所有**工单号（去重、保序、大写）；没有则返回 [] */
export function extractTtNos(text) {
  const found = String(text || '').match(TT_RE) || [];
  const out = [];
  for (const raw of found) {
    const no = raw.toUpperCase();
    if (!out.includes(no)) out.push(no);
  }
  return out;
}

/** 从问题里抽出首个工单号；没有则返回 null（保留旧接口，兼容已有调用） */
export function extractTtNo(text) {
  return extractTtNos(text)[0] ?? null;
}

/**
 * 一条回复里最多分析几个单。
 *
 * 用户会一次贴多个单号问（实测有 `check these TTs TT202609140078,
 * TT202609140077`）。旧实现只取首个，**后面的单号一个字都不提** ——
 * 用户无从知道被漏了，只会以为其余单子也有同样的问题。
 * 但也不能无限展开：单次分析要查库渲染上千字，10 个单会挤爆聊天窗口。
 * 超过上限时明确告知「只分析前 N 个」，把选择权交回用户。
 */
export const MAX_TICKETS_PER_QUESTION = 3;

/**
 * 分析问题里提到的工单（支持多个）。
 *
 * 单号 → 单号之间用分隔线拼接；部分失败时**不影响其余单号**，
 * 失败的用它的失败文案占位（用户能看出哪个单没查到）。
 *
 * @param {string} question
 * @param {{lang?: 'zh'|'en', onRetry?: Function, onLive?: Function}} [opts]
 * @returns {Promise<{ok:boolean, text:string, ttNos:string[], okCount:number, total:number, truncated:boolean}>}
 */
export async function analyzeTickets(question, { lang = 'zh', onRetry, onLive } = {}) {
  const all = extractTtNos(question);
  const ttNos = all.slice(0, MAX_TICKETS_PER_QUESTION);
  const truncated = all.length > ttNos.length;

  if (!ttNos.length) {
    return { ok: false, text: '', ttNos: [], okCount: 0, total: 0, truncated: false };
  }

  const results = [];
  for (const no of ttNos) {
    results.push({ no, ...(await analyzeTt(no, { lang, onRetry, onLive })) });
  }

  const okCount = results.filter((r) => r.ok).length;
  const parts = results.map((r) => (results.length > 1 ? `【${r.no}】\n${r.text}` : r.text));
  if (truncated) {
    parts.push(
      pickText(
        lang,
        `（你一次提了 ${all.length} 个单，这里只分析了前 ${ttNos.length} 个。` +
          `其余请分开问，或再 @我 一次。）`,
        `(You listed ${all.length} tickets — I analyzed the first ${ttNos.length}. ` +
          `Ask again for the rest.)`
      )
    );
  }

  return {
    ok: okCount > 0,
    text: parts.join('\n\n────────\n\n'),
    ttNos,
    okCount,
    total: ttNos.length,
    truncated,
    // 逐跳耗时（见 analyzeTt 的 timing）。多单时按单号列全，
    // 这样「3 个单里有 1 个慢」和「整条通道慢」能分开看。
    timing: results.map((r) => ({ no: r.no, ...(r.timing || {}) })),
  };
}

/** 环境是否具备 TT 分析条件（脚本 + Python 解释器都在） */
export function ttAvailable() {
  return existsSync(SCRIPT) && existsSync(PYTHON);
}

/**
 * B5：按「告警码 + 站点属性」做**真正的级别匹配**（复用 tt-analyze.py 的 matcher）。
 *
 * 为什么不自己算：级别规则的条件语义（左折叠 OR/AND、siteSubType vs assetType
 * 区分、字符串比较）在 Python 侧已与 my_app 对齐并验收。这里再写一份必然漂移，
 * 结果就是「查表说 P2、分析工单说 P3」—— 最难排查的一类不一致。
 *
 * 返回 { ok, verdict, severity, ruleId, ruleName, missingFields, text }；
 * 脚本不可用 / 超时 → { ok:false, unavailable:true }，调用方回退到静态候选列表。
 *
 * @param {string} code    告警码
 * @param {object} attrs   { asset, vip, sub, domain, down }
 * @param {object} [opts]  { lang }
 */
export function lookupLevelByRule(code, attrs = {}, { lang = 'zh' } = {}) {
  const args = [SCRIPT, '--lookup-level', String(code), '--lang', lang, '--json'];
  if (attrs.asset) args.push('--asset', String(attrs.asset));
  if (attrs.vip !== undefined && attrs.vip !== '') args.push('--vip', String(attrs.vip));
  if (attrs.sub) args.push('--sub', String(attrs.sub));
  if (attrs.domain) args.push('--domain', String(attrs.domain));
  if (attrs.down) args.push('--down', String(attrs.down));

  return new Promise((resolvePromise) => {
    execFile(
      PYTHON,
      args,
      {
        timeout: TIMEOUT_MS,
        encoding: 'utf8',
        windowsHide: true,
        maxBuffer: 4 * 1024 * 1024,
        env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
      },
      (err, stdout, stderr) => {
        const out = (stdout || '').trim();
        // 退出码：0 命中 / 1 不匹配 / 4 incomplete —— 这三种都有 stdout JSON。
        if (out) {
          try {
            const res = JSON.parse(out);
            resolvePromise({
              ok: res.verdict === 'ok',
              unavailable: false,
              verdict: res.verdict,
              severity: res.suggested_severity || '',
              ruleId: res.matched_rule_id ?? null,
              ruleName: res.matched_rule_name || '',
              missingFields: res.missing_rule_fields || [],
              details: res.match_details || '',
            });
            return;
          } catch {
            /* 落到下面按失败处理 */
          }
        }
        // 无 stdout（脚本不可用 / 规则表读不到 / 超时）→ unavailable，调用方回退
        resolvePromise({ ok: false, unavailable: true, error: (stderr || err?.message || '').trim() });
      }
    );
  });
}

/**
 * 失败文案（超时 / 出错 / 空结果）。
 *
 * TT 通道不过模型，这几句是脚本之外、由 Node 侧直接发出的兜底 ——
 * 写死中文的话，英文提问遇到超时或异常会收到一句中文报错。
 * 之所以不放进脚本：这些情况发生在**脚本没能正常返回**的时候，
 * 此时只能由调用方兜底。
 */
const FAIL_TEXT = {
  zh: {
    timeout: (tt, s) =>
      `分析 ${tt} 超时（${s}s）。工单库在 Y 盘（网络盘），首次查询要建本地单号索引，` +
      `可能偏慢；稍后再试通常会快很多。`,
    error: (tt, detail) => `分析 ${tt} 时出错了：${detail}`,
    empty: (tt) => `分析 ${tt} 没有返回结果。`,
    unknown: '未知错误',
    retrying: (tt) => `分析 ${tt} 没成功，正在自动重试一次…`,
    // PG 里没有（或 PG 连不上）→ 即将去 eFlow 实时查。**必须先说一声**：
    // 实时查询要登录 eFlow + 翻页扫描，实测比本地查询慢得多，
    // 不垫这句的话用户只会看到机器人沉默十几秒，以为它掉线了。
    // 措辞按 2026-10-28 的新顺序改：现在卡在 PG 这一层（不再是 SQLite 副本），
    // 而 PG 由 `eflow_sync` 每小时从 eFlow 同步一次 —— 说「同步有延迟」太空泛，
    // 说清是「每小时一次」用户才知道该等多久。
    goingLive: (tt) =>
      `实时库里还没有 ${tt}（PG 每小时从 eFlow 同步一次），我去 eFlow 实时查一下，请稍等…`,
    // src 由调用方给：PG 通道说「实时库」，SQLite 通道说「本地库」。
    // 说错来源比不说更糟 —— 用户会照着这句话去核对另一套系统。
    // ⚠️ 来源名必须**按语言**取（F.srcPg / F.srcLocal），不能直接写中文字面量：
    // 英文回复里塞一个「实时库」就是中英混排，实测当场踩到。
    srcPg: '实时库',
    srcLocal: '本地库',
    liveMiss: (tt, src) =>
      `${src || '本地库'}和 eFlow 实时都没查到 ${tt}。请核对一下单号有没有写错。`,
    // detail 是 Python 脚本的 stderr（中文诊断），**只给中文回复用**。
    // 英文回复塞进去就成了中英混排 —— 见下面 en.liveError。
    liveError: (tt, detail) => `实时查 eFlow 时出错了：${detail}`,
    // 最后兜底（本地副本）命中时必须标注：这份数据最坏落后 12 小时，
    // 不标的话用户会拿它当实时数据去做派单决策。
    stale: '⚠️ 实时库暂时取不到，下面这份来自本地副本（每 12 小时同步一次，可能滞后）',
  },
  en: {
    timeout: (tt, s) =>
      `Analyzing ${tt} timed out (${s}s). The ticket DB sits on a network drive (Y:); ` +
      `the first query builds a local index and can be slow — retrying usually works much faster.`,
    error: (tt, detail) => `Something went wrong while analyzing ${tt}: ${detail}`,
    empty: (tt) => `Analyzing ${tt} returned no result.`,
    unknown: 'unknown error',
    retrying: (tt) => `Analyzing ${tt} failed — retrying once automatically…`,
    goingLive: (tt) =>
      `${tt} is not in the live DB yet (PG syncs from eFlow hourly) — ` +
      `checking eFlow live, one moment…`,
    srcPg: 'the live database',
    srcLocal: 'the local DB',
    liveMiss: (tt, src) =>
      `Neither ${src || 'the local DB'} nor a live eFlow lookup found ${tt}. ` +
      `Please double-check the ticket number.`,
    // ⚠️ 这里**刻意丢掉 detail**：它来自 Python 脚本的 stderr，
    // 内容是中文（如「实时兜底不可用：…没找到同时装齐 pandas + sqlalchemy 的解释器」）。
    // 原样拼进英文回复会得到中英混排，实测就是这么漏出去的。
    // 诊断细节对群里用户也没用（他既不能装包也不该知道 we 的依赖），
    // 完整原因已经打到机器人日志里了 —— 面向用户只给结论。
    liveError: (tt) =>
      `The live eFlow lookup did not go through, so ${tt} could only be ` +
      `checked against the local ticket DB.`,
    // 纯 ASCII：英文回复要过「零中文残留」断言（见 test-tt-live-route.mjs [7]）。
    stale: '[stale] live DB unavailable — this is the local replica ' +
      '(synced every 12h, may lag)',
  },
};

/**
 * 重试一次之前等多久。
 *
 * 失败形态以「Y 盘网络盘首次建索引慢」为主（全表扫描实测 11s~100s）。
 * 紧跟着重试会撞上同一个仍在校验/锁定的库，退避一下命中率高得多；
 * 但也不能太久 —— 用户在群里等着，且上层还有 pendingAfterMs 垫话机制。
 */
const RETRY_DELAY_MS = Number(process.env.TT_RETRY_DELAY_MS || 1200);

/**
 * 实时兜底的超时。
 *
 * 比本地查询更宽松：实时路径要 ① 探测解释器（每个候选一次子进程）
 * ② 登录 eFlow（OAuth2 + RSA）③ 分页扫描（每页 2000 行 / ~4 秒 / 3MB，
 * 最多扫 4000 行）。实测比本地查询慢一个数量级。
 * 给 4 分钟（脚本自身还有 180s 的子进程超时兜着）。
 */
const LIVE_TIMEOUT_MS = Number(process.env.TT_LIVE_TIMEOUT_MS || CONFIG.ttLiveTimeoutMs || 240000);

/** 单次尝试（只查本地库）。永不抛异常，失败时返回 {ok:false, text, retriable}。 */
function attemptTt(ttNo, replyLang) {
  return runAnalyze(ttNo, replyLang, null);
}

/**
 * 跑一次 tt-analyze.py，返回 {ok, text, retriable, notFound}。
 * 永不抛异常。
 *
 * @param {string} ttNo
 * @param {'zh'|'en'} replyLang
 * @param {string|null} liveJson  eFlow 实时行的 JSON；非空时脚本跳过本地库
 */
function runAnalyze(ttNo, replyLang, liveJson = null) {
  const F = FAIL_TEXT[replyLang];
  return new Promise((resolvePromise) => {
    const args = [SCRIPT, ttNo, '--lang', replyLang];
    // 实时行走 stdin：命令行传 JSON 会撞上 Windows 的 32K 命令行上限，
    // 而实时行字段多（含长流水文本），实测很容易超。
    if (liveJson != null) args.push('--live-row', '-');

    const child = execFile(
      PYTHON,
      args,
      {
        timeout: TIMEOUT_MS,
        encoding: 'utf8',
        windowsHide: true,
        maxBuffer: 4 * 1024 * 1024,
        // 必须显式指定，不能靠继承环境。
        // 机器人是从 Windows 启动的，环境里没有 LANG，于是 Python 的 stdout
        // 退化成系统代码页（本机实测 cp1252），脚本一 print 中文就抛
        //   UnicodeEncodeError: 'charmap' codec can't encode characters ...
        // 在 Git Bash 里手跑却没事（有 LANG）—— 这正是当初没发现的原因。
        // 配合脚本里的 reconfigure 双保险。
        env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
      },
      (err, stdout, stderr) => {
        const out = (stdout || '').trim();

        if (err) {
          const timedOut = err.killed || /timed out/i.test(err.message || '');
          if (timedOut) {
            // 超时几乎总是「首次建索引慢」，最值得重试
            resolvePromise({ ok: false, text: F.timeout(ttNo, TIMEOUT_MS / 1000), retriable: true });
            return;
          }

          // 「查无此单」不是程序故障：脚本按约定以退出码 1 表示未找到，
          // 但 stdout 里已经写好了一句给用户看的话，直接用，别报「命令失败」。
          // 只有 stdout 为空（退出码 2/3）才是真出错。
          if (out) {
            // 脚本自己给出了理由：可能是「查无此单」（重试无意义），
            // 也可能是「工单库读不到」（重试有意义）。按脚本的措辞判断。
            const foundNothing = !liveJson && /工单库里没有找到|not found in the ticket database/i.test(out);
            resolvePromise({
              ok: false,
              text: out,
              notFound: foundNothing,
              retriable: !foundNothing && /无法访问|读不到|不可用|busy|locked|暂时/i.test(out),
            });
            return;
          }

          const raw = (stderr || err.message || '').trim();
          const lines = raw.split('\n').map((s) => s.trim()).filter(Boolean);
          // Python 的 traceback 第一行永远是 "Traceback (most recent call last):"，
          // 照抄下来等于没信息。真正有用的异常类型和消息在**最后一行**。
          const detail = lines[lines.length - 1] || F.unknown;
          // 真异常（exit 2/3）多为库文件忙/网络盘瞬时不可达 —— 也重试一次
          resolvePromise({ ok: false, text: F.error(ttNo, detail), retriable: true });
          return;
        }

        if (!out) {
          resolvePromise({ ok: false, text: F.empty(ttNo), retriable: true });
          return;
        }
        resolvePromise({ ok: true, text: out });
      }
    );

    // 实时行经 stdin 喂进去。写失败（子进程已退出）不影响结果 —— 回调里会拿到错误。
    if (liveJson != null) {
      child.stdin?.on('error', () => {});
      child.stdin?.end(liveJson, 'utf8');
    }
  });
}

/**
 * PG 没给出答案时（没这单 / 请求失败），去 eFlow 实时拉这一单。
 *
 * 返回：
 *   {hit:'yes', analyze:{...}}  实时行拿到了，并且用它渲染出了分析
 *   {hit:'no'}                  实时也没有这一单（eFlow 是源头，这就是结论）
 *   {hit:'unavailable', detail} 实时通道不可用/出错（缺解释器、登录失败…）
 *
 * **任何失败都只降级、不抛出** —— 这是给群里用户的回复，
 * 实时通道挂掉时，调用方还要继续往本地副本兜。
 */
function tryLive(ttNo, replyLang) {
  return new Promise((resolvePromise) => {
    // 桥接脚本用哪个解释器自己探测（my_app 的 venv 未必装齐依赖），
    // 所以这里刻意**不用** PYTHON，直接交给系统 python。
    execFile(
      PYTHON,
      [LIVE_SCRIPT, ttNo],
      {
        timeout: LIVE_TIMEOUT_MS,
        encoding: 'utf8',
        windowsHide: true,
        maxBuffer: 8 * 1024 * 1024,
        env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
      },
      async (err, stdout, stderr) => {
        const out = (stdout || '').trim();

        if (!out) {
          // ⚠️ 退出码 1 = **实时也查无此单**，不是故障。
          //
          // `eflow-live-tt.py` 的约定（见该脚本 `_MISS` 的注释）：查到→JSON、
          // 没查到→退出码 1 且 stdout 为空、出错→退出码 3。而 execFile 对
          // **任何**非零退出码都给 err，于是退出码 1 也带着 err。
          //
          // 旧实现把 `err && !out` 一律判成 'unavailable'，导致「eFlow 里确实
          // 没有这一单」被说成「实时查 eFlow 时出错了」—— 前者是结论，后者是
          // 故障，用户据此做的决定完全相反（2026-10-28 由 test-tt-analysis-http
          // 的 [7] 抓出）。
          if (err && err.code === 1) {
            resolvePromise({ hit: 'no' });
            return;
          }
          const detail = String(stderr || err?.message || '').trim().split('\n').filter(Boolean).pop();
          resolvePromise({ hit: 'unavailable', detail: detail || FAIL_TEXT[replyLang].unknown });
          return;
        }
        const res = await runAnalyze(ttNo, replyLang, out);
        if (res.ok) {
          resolvePromise({ hit: 'yes', analyze: res });
        } else {
          resolvePromise({ hit: 'unavailable', detail: res.text });
        }
      }
    );
  });
}

/**
 * 分析一个工单（TT / WO）。
 *
 * 取数顺序（2026-10-28 起，理由见文件头）：
 *   ① **PG 实时库**（my_app HTTP）—— 首选，命中即用。
 *   ② **eFlow 实时**（`eflow-live-tt.py`）—— ①说「没这单」或 ①请求失败时。
 *   ③ **本地 SQLite 副本**（`tt-analyze.py` 直读 app.db）—— ①②都拿不到时兜底，
 *      命中会打「可能滞后」标记。
 *
 * 旧顺序是 ①→③→②。把 ③ 挪到最后，是因为那份副本每 12 小时才重建一次，
 * 让它挡在 eFlow 前面等于**用旧答案覆盖新答案**。
 *
 * `ttAnalysisHttp=false`（或 `TT_ANALYSIS_HTTP=0`）时回到**老顺序** ①→③→②，
 * 且 ③ 作为主路径不打滞后标记 —— 那是显式关掉实时库的部署方式，
 * 不该被新顺序悄悄改成「每次都先去 eFlow 绕一圈」。
 *
 * 失败时**自动重试一次**（只针对 ③ 的超时/瞬时读不到；「查无此单」不重试）。
 *
 * 为什么要自动重试：实测同一单 `TT202609110023` 被用户连问了 5 次，
 * 前 3 次都失败、第 4 次才成功 —— 失败原因几乎都是 Y 盘网络盘
 * 首次建索引慢（11s~100s 波动）或瞬时不可达，**再跑一次就好了**。
 * 让用户自己重复提问，等于把基础设施的抖动转嫁成人工重试，
 * 而且用户会以为「这单查不到」。
 *
 * 刻意**永不抛异常** —— 这是在群里回复用户，
 * 子进程失败也必须给出一句人话，不能静默或抛栈。
 *
 * @param {string} ttNo
 * @param {{lang?: 'zh'|'en', onRetry?: Function, onLive?: Function}} [opts]
 *        回复语言（按提问语言判定，见 lang.js）；
 *        onRetry 在「即将重试」时回调，供上层发垫话；
 *        onLive  在「即将回 eFlow 实时查」时回调，供上层发垫话。
 */
export async function analyzeTt(ttNo, opts = {}) {
  // 逐跳计时。**为什么非要这个**：2026-10-28 实测同一单号，独立调用 1.0s，
  // 群里却是 24~58s（qa_log 里 tt 通道 p50 11.8s、max 57.5s），而日志里只有
  // 一个总数 —— 只能靠猜。把「取 PG 行」「跑渲染脚本」「eFlow 实时」分开计时，
  // 下一次慢的时候一眼就能看出是哪一跳，不必再翻 my_app 的任务日志去对时间。
  // 计时是旁路，任何异常都不影响查询结果。
  const timing = { src: '', pg: 0, render: 0, live: 0, total: 0 };
  const started = Date.now();
  try {
    // 先算返回值再补 total：finally 里改的是同一个对象，
    // 所以返回出去的 timing.total 是含全流程的。
    return { ...(await analyzeTtOnce(ttNo, opts, timing)), timing };
  } finally {
    timing.total = Date.now() - started;
  }
}

/**
 * analyzeTt 的本体。单独拆出来只是为了让上面那层能统一收口 timing ——
 * 本体里有 8 个 return 点，逐个补 total 迟早漏一个。
 *
 * @param {{lang?: string, onRetry?: Function, onLive?: Function}} opts
 * @param {{src:string, pg:number, render:number, live:number}} timing 就地累加
 */
async function analyzeTtOnce(ttNo, { lang = 'zh', onRetry, onLive } = {}, timing) {
  // 只放行脚本认得的取值，避免上游传错让 argparse 直接退出（exit 2）
  const replyLang = lang === 'en' ? 'en' : 'zh';
  const F = FAIL_TEXT[replyLang];
  const httpOn = analysisHttpEnabled();

  // ① PG 实时库。
  //    未命中分两种，语义不同故分开记：接口正常但确实没这单（notfound），
  //    与请求失败（error，my_app 没起 / 超时 / 返回结构异常）。
  let pgMiss = null; // null | 'notfound' | 'error'
  if (httpOn) {
    const tp = Date.now();
    try {
      const { tt, wo } = await fetchRowsHttp(ttNo);
      timing.pg = Date.now() - tp;
      if (tt) {
        // 走已有的 --live-row 通道（信封 {"row":<TT>,"wo":<WO>}），
        // 渲染/规则匹配/口径全部复用 tt-analyze.py，不引入第二套格式。
        const env = JSON.stringify({ row: tt, wo: wo || undefined });
        const tr = Date.now();
        const res = await runAnalyze(ttNo, replyLang, env);
        timing.render = Date.now() - tr;
        if (res.ok) {
          timing.src = 'pg';
          return res;
        }
        // 行拿到了、但脚本渲染失败（如规则表缺失）→ 不吞，继续走 ②/③。
        pgMiss = 'error';
        if (process.env.DEBUG_TOOLS === '1') console.error(`[tt] PG 行渲染失败：${res.text}`);
      } else {
        pgMiss = 'notfound';
      }
    } catch (err) {
      timing.pg = Date.now() - tp;
      // 网络/服务异常 → 继续 ②（机器人保持独立可用）
      pgMiss = 'error';
      if (process.env.DEBUG_TOOLS === '1') console.error(`[tt] PG 取行失败：${err.message}`);
    }
  }

  // ② eFlow 实时 —— 紧跟 PG，**不让 12 小时前的副本插队**。
  //
  //    为什么 PG 说「没这单」也要去 eFlow：PG 由 `eflow_sync` 每小时从 eFlow
  //    同步一次，刚建的单在 PG 里最长会缺席一小时（2026-10-28 实测：
  //    TT202610280006 建单 00:25、01:00 才进 PG）。eFlow 才是源头。
  let liveFail = ''; // 实时通道「没查成」的原因；收尾文案要用
  if (httpOn && pgMiss && liveFallbackEnabled()) {
    // 先垫话：实时要登录 + 翻页扫描，十几秒起步，不垫用户以为掉线了。
    onLive?.(F.goingLive(ttNo));
    const tl = Date.now();
    const live = await tryLive(ttNo, replyLang);
    timing.live = Date.now() - tl;
    if (live.hit === 'yes') {
      timing.src = 'eflow';
      return live.analyze;
    }
    // eFlow 明确「没这单」= 结论。副本比 eFlow 更旧，再查一次不可能有新结果，
    // 所以**直接返回**，不再落到 ③（省掉一次可能几十秒的全表扫描）。
    if (live.hit === 'no') {
      timing.src = 'eflow-miss';
      return { ok: false, text: F.liveMiss(ttNo, F.srcPg) };
    }
    liveFail = live.detail || F.unknown;
  }

  // ③ 本地 SQLite 副本 —— 最后兜底。
  //    · httpOn=false：这是**主路径**（老行为），不打滞后标记；
  //    · httpOn=true ：①②都没拿到，命中必须标「可能滞后」，否则用户会
  //      拿一份最坏落后 12 小时的数据去做派单决策。
  const withStale = (res) =>
    httpOn ? { ...res, text: `${F.stale}\n${res.text || ''}`.trim(), stale: true } : res;
  // ①②都没成时，③ 的结论也要带上「实时没查成」——
  // 否则用户会把「查无此单」当成实时确认过的结论。
  const finalize = (res) =>
    liveFail
      ? { ok: false, text: `${F.liveError(ttNo, liveFail)}\n${res.text || ''}`.trim() }
      : res;

  const tl0 = Date.now();
  const first = await attemptTt(ttNo, replyLang);
  timing.render = Date.now() - tl0;
  if (first.ok) {
    timing.src = 'local';
    return withStale(first);
  }

  // 老顺序（PG 关闭）才有的「本地 miss → 实时」分支。
  if (!httpOn && first.notFound) {
    const live = await liveFallback(ttNo, replyLang, first, onLive);
    if (live) {
      timing.src = 'eflow-legacy';
      return live;
    }
  }

  // 确凿「查无此单」不是故障，重试没有意义 —— 直接给结论。
  if (first.notFound) {
    timing.src = 'local-miss';
    return finalize(first);
  }

  // 值得重试的失败（超时 / 库瞬时读不到）→ 垫一句话再试一次。
  onRetry?.(F.retrying(ttNo));
  await sleep(RETRY_DELAY_MS);
  const tl1 = Date.now();
  const second = await attemptTt(ttNo, replyLang);
  timing.render = Date.now() - tl1; // 重试覆盖掉第一次的读数（第二次才是「当下」）
  if (second.ok) {
    timing.src = 'local-retry';
    return withStale(second);
  }

  if (!httpOn && second.notFound) {
    const live = await liveFallback(ttNo, replyLang, second.text ? second : first, onLive);
    if (live) return live;
  }

  // 第二次仍失败 → 返回第二次的结果（文案更贴近当下状态）。
  // 但如果第二次的文案是空的，保留第一次的 —— 有总比没有强。
  timing.src = 'failed';
  return finalize(second.text ? second : first);
}

/**
 * 走一次实时兜底，把「垫话 → 查询 → 三种收尾」这套固定流程收在一处。
 *
 * ⚠️ 2026-10-28 起**只服务于老顺序**（`ttAnalysisHttp=false` 时的
 * 本地副本 → eFlow）。PG 通道开着时走的是 `analyzeTt` 里内联的第 ② 步：
 * 那里 PG 已经试过，收尾文案要说「实时库」（不是「本地库」），
 * 且 eFlow 明确「没这单」时不该再落到副本 —— 与这里的语义不同，故没有复用。
 *
 * @param {string} ttNo
 * @param {'zh'|'en'} replyLang
 * @param {{text?: string}} fallback 本地那句「库里没有找到」，实时也没/没查成时保留在后面
 * @param {Function} [onLive] 发垫话的回调
 * @returns {Promise<{ok:boolean,text:string}|null>} 实时兜底被关闭时返回 null（调用方继续原逻辑）
 */
async function liveFallback(ttNo, replyLang, fallback, onLive) {
  if (!liveFallbackEnabled()) return null;
  const F = FAIL_TEXT[replyLang];

  // 先垫话再查：实时要登录 + 翻页扫描，十几秒起步，不垫用户以为掉线了。
  onLive?.(F.goingLive(ttNo));
  const live = await tryLive(ttNo, replyLang);

  if (live.hit === 'yes') return live.analyze;

  const tail = fallback.text || '';
  if (live.hit === 'no') {
    // 本地 + 实时都没有：原来那句「库里没有 + 库内最新单号」仍然有用
    //（用户能对比「我的单比库内最新还新多少」），保留它，
    // 只在前面加一句「实时也查过了」—— 否则用户会以为我们没去查。
    return { ok: false, text: `${F.liveMiss(ttNo, F.srcLocal)}\n${tail}` };
  }
  // 实时通道不可用/出错：不能因为兜底挂了就把本地那句也丢掉，
  // 但要说清「实时没查成」，免得用户以为已经实时确认过没有了。
  return { ok: false, text: `${F.liveError(ttNo, live.detail)}\n${tail}` };
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * 把逐跳计时压成一行，供 `[回复]` 日志用。
 *
 * 形如 `tt=pg:190/渲染:1010/实时:0/计:1200`（毫秒，只列非零的跳）。
 * 之所以要压成一行：日志按行读，多跳多行会把同一次提问切散，
 * 出问题时反而要在日志里做关联。
 *
 * @param {Array<{no:string,src:string,pg:number,render:number,live:number,total:number}>|object} timing
 * @returns {string} 没有计时数据时返回空串
 */
export function formatTtTiming(timing) {
  const list = Array.isArray(timing) ? timing : timing ? [timing] : [];
  const parts = list
    .filter((t) => t && t.total)
    .map((t) => {
      const hops = [`取行:${t.pg || 0}`, `渲染:${t.render || 0}`];
      if (t.live) hops.push(`实时:${t.live}`);
      const head = list.length > 1 ? `${t.no} ` : '';
      return `${head}${t.src || '?'}(${hops.join('/')}) ${t.total}ms`;
    });
  return parts.join('，');
}
