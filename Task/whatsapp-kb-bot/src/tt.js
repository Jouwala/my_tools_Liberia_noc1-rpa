/**
 * TT 单分析 —— 调用 my_app 的工单库做实时级别核查。
 *
 * 与 RAG 的分工很明确：
 *   知识库（RAG）回答「规则是什么」——静态知识，向量检索就够；
 *   这里回答「这一单现在什么情况」——必须实时查库，所以走独立通道。
 *
 * 实现方式：Node 起子进程跑 scripts/tt-analyze.py。
 * 之所以不用 my_app 的 HTTP 接口：那要求 my_app 服务在跑，
 * 而子进程方式只依赖「工单库文件可读」，机器人独立可用。
 */
import { execFile } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { CONFIG, ROOT } from './config.js';
import { pickText } from './lang.js';

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
    // 本地库查不到 → 即将去 eFlow 实时查。**必须先说一声**：
    // 实时查询要登录 eFlow + 翻页扫描，实测比本地查询慢得多，
    // 不垫这句的话用户只会看到机器人沉默十几秒，以为它掉线了。
    goingLive: (tt) => `本地工单库还没有 ${tt}（同步有延迟），我去 eFlow 实时查一下，请稍等…`,
    liveMiss: (tt) =>
      `本地库和 eFlow 实时都没查到 ${tt}。请核对一下单号有没有写错。`,
    // detail 是 Python 脚本的 stderr（中文诊断），**只给中文回复用**。
    // 英文回复塞进去就成了中英混排 —— 见下面 en.liveError。
    liveError: (tt, detail) => `实时查 eFlow 时出错了：${detail}`,
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
      `${tt} is not in the local ticket DB yet (sync has a delay) — ` +
      `checking eFlow live, one moment…`,
    liveMiss: (tt) =>
      `Neither the local DB nor a live eFlow lookup found ${tt}. ` +
      `Please double-check the ticket number.`,
    // ⚠️ 这里**刻意丢掉 detail**：它来自 Python 脚本的 stderr，
    // 内容是中文（如「实时兜底不可用：…没找到同时装齐 pandas + sqlalchemy 的解释器」）。
    // 原样拼进英文回复会得到中英混排，实测就是这么漏出去的。
    // 诊断细节对群里用户也没用（他既不能装包也不该知道 we 的依赖），
    // 完整原因已经打到机器人日志里了 —— 面向用户只给结论。
    liveError: (tt) =>
      `The live eFlow lookup did not go through, so ${tt} could only be ` +
      `checked against the local ticket DB.`,
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
 * 本地库查不到时，去 eFlow 实时拉这一单。
 *
 * 返回：
 *   {hit:'yes', analyze:{...}}  实时行拿到了，并且用它渲染出了分析
 *   {hit:'no'}                  实时也没有这一单（本地 + 实时都没有）
 *   {hit:'unavailable', detail} 实时通道不可用/出错（缺解释器、登录失败…）
 *
 * **任何失败都只降级、不抛出** —— 这是给群里用户的回复，
 * 实时兜底挂掉时，至少要保住原来那句「库里没有找到」。
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

        if (err && !out) {
          const detail = String(stderr || err.message || '').trim().split('\n').filter(Boolean).pop();
          resolvePromise({ hit: 'unavailable', detail: detail || FAIL_TEXT[replyLang].unknown });
          return;
        }
        if (!out) {
          // 退出码 1 = 实时也查无此单（脚本约定）
          resolvePromise({ hit: 'no' });
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
 * 分析一个工单（TT / WO），失败时**自动重试一次**，本地查不到时**回 eFlow 实时查**。
 *
 * 为什么要自动重试：实测同一单 `TT202609110023` 被用户连问了 5 次，
 * 前 3 次都失败、第 4 次才成功 —— 失败原因几乎都是 Y 盘网络盘
 * 首次建索引慢（11s~100s 波动）或瞬时不可达，**再跑一次就好了**。
 * 让用户自己重复提问，等于把基础设施的抖动转嫁成人工重试，
 * 而且用户会以为「这单查不到」。
 *
 * 为什么要实时兜底：本地库同步有延迟，用户报的单号常常比库里最新的还新。
 * 以前这种情况只回一句「库里没有 + 库内最新单号」，用户拿不到数据。
 * 现在先垫一句「正在实时查」再回 eFlow 拉 —— 详见 `tryLive`。
 *
 * 刻意**永不抛异常** —— 这是在群里回复用户，
 * 子进程失败也必须给出一句人话，不能静默或抛栈。
 *
 * @param {string} ttNo
 * @param {{lang?: 'zh'|'en', onRetry?: Function, onLive?: Function}} [opts]
 *        回复语言（按提问语言判定，见 lang.js）；
 *        onRetry 在「即将重试」时回调，供上层发垫话；
 *        onLive  在「本地 miss、即将回 eFlow 实时查」时回调，供上层发垫话。
 */
export async function analyzeTt(ttNo, { lang = 'zh', onRetry, onLive } = {}) {
  // 只放行脚本认得的取值，避免上游传错让 argparse 直接退出（exit 2）
  const replyLang = lang === 'en' ? 'en' : 'zh';
  const F = FAIL_TEXT[replyLang];

  const first = await attemptTt(ttNo, replyLang);

  // 本地查到了 → 直接回。
  if (first.ok) return first;

  // 本地 miss（不是故障）→ 回 eFlow 实时查。
  //
  // 判断用 `notFound` 而不是 `!first.ok`：只有**确凿的「查无此单」**才值得
  // 去实时拉。超时/库读不到等故障走下面的重试逻辑 —— 对那些情况，
  // 本地库其实是有这一单的，去 eFlow 反而绕远路且更慢。
  if (first.notFound) {
    const live = await liveFallback(ttNo, replyLang, first, onLive);
    if (live) return live;
  }

  // 值得重试的失败（超时 / 库瞬时读不到）→ 垫一句话再试一次。
  onRetry?.(F.retrying(ttNo));
  await sleep(RETRY_DELAY_MS);
  const second = await attemptTt(ttNo, replyLang);
  if (second.ok) return second;

  // 重试后变成「查无此单」也再兜一次 —— 第一次是超时时尤其容易这样：
  // 索引刚建好，本地确实没有这一单，但实时可能有。
  if (second.notFound) {
    const live = await liveFallback(ttNo, replyLang, second.text ? second : first, onLive);
    if (live) return live;
  }

  // 第二次仍失败 → 返回第二次的结果（文案更贴近当下状态）。
  // 但如果第二次的文案是空的，保留第一次的 —— 有总比没有强。
  return second.text ? second : first;
}

/**
 * 走一次实时兜底，把「垫话 → 查询 → 三种收尾」这套固定流程收在一处
 *（`analyzeTt` 里两处都会用到，复制两份迟早改漏一处）。
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
    return { ok: false, text: `${F.liveMiss(ttNo)}\n${tail}` };
  }
  // 实时通道不可用/出错：不能因为兜底挂了就把本地那句也丢掉，
  // 但要说清「实时没查成」，免得用户以为已经实时确认过没有了。
  return { ok: false, text: `${F.liveError(ttNo, live.detail)}\n${tail}` };
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}
