/**
 * 检索增强（RAG）核心。
 *
 * 命中判定采用「相对基线差值」而非绝对阈值：
 *   baseline = 该查询与全库相似度的中位数（代表"这个查询对这批语料的泛化水位"）
 *   gap      = top1 - baseline
 *   命中 ⟺ top1 >= minAbs AND gap >= minGap
 *
 * 原因：稠密嵌入对中文的余弦相似度被压缩在窄高位区间，
 * 完全无关的查询 top1 也有 0.33~0.40。绝对阈值必然"永远命中"。
 * gap 是逐查询自适应归一化的量，实测命中/未命中相差约 4 倍，稳定得多。
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync, renameSync } from 'node:fs';
import { dirname } from 'node:path';
import { CONFIG } from './config.js';
import { pickText } from './lang.js';
import { embedOne } from './ollama.js';
import { chat } from './llm.js';

/* ---------------------------------- 向量 ---------------------------------- */

export function cosine(a, b) {
  let dot = 0, na = 0, nb = 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  const den = Math.sqrt(na) * Math.sqrt(nb);
  return den === 0 ? 0 : dot / den;
}

/* -------------------------------- 字面重合 -------------------------------- */

/** 字符 + 字符 bigram 集合。中文无需分词器，实现简单且有效。 */
export function bigrams(text) {
  const s = String(text).toLowerCase().replace(/[\s\p{P}\p{S}]+/gu, '');
  const out = new Set();
  for (let i = 0; i < s.length; i++) {
    out.add(s[i]);
    if (i + 1 < s.length) out.add(s.slice(i, i + 2));
  }
  return out;
}

/** 集合相似度：交集 / sqrt(|A|·|B|) */
export function bigramSim(a, b) {
  const A = bigrams(a);
  const B = bigrams(b);
  if (!A.size || !B.size) return 0;
  let inter = 0;
  for (const x of A) if (B.has(x)) inter++;
  return inter / Math.sqrt(A.size * B.size);
}

/* ---------------------------------- 分块 ---------------------------------- */

/**
 * 硬切：把任意长度的文本切成不超过 size 的片段。
 * 断点优先落在空白或标点处，找不到就从 size 处直接截断。
 * 这是最后一道兜底——保证「块长度 ≤ size」这个不变量在任何输入下都成立。
 */
function hardSplit(s, size) {
  const BREAK = /[\s，,、；;：:）)】」』\]\}]/;
  const MIN_RATIO = 0.6; // 最多回退 40% 找断点，避免切出过短的碎块
  const out = [];
  let rest = s;
  while (rest.length > size) {
    let cut = size;
    for (let i = size; i > Math.floor(size * MIN_RATIO); i--) {
      if (BREAK.test(rest[i - 1])) {
        cut = i;
        break;
      }
    }
    out.push(rest.slice(0, cut).trim());
    rest = rest.slice(cut).trim();
  }
  if (rest) out.push(rest);
  return out;
}

/**
 * 结构感知分块：先按空行切段 → 超长段落按句切 → 硬切兜底 → 再合并并保留重叠。
 *
 * 不变量：返回的每一块长度都 ≤ size。
 * （没有硬切兜底时，无句末标点的长文本会原样成块，实测 5000 字会变成一块。）
 * @returns {string[]}
 */
export function chunkText(text, { size = CONFIG.chunkSize, overlap = CONFIG.chunkOverlap } = {}) {
  const clean = String(text).replace(/\r\n/g, '\n').replace(/[ \t]+/g, ' ').trim();
  if (!clean) return [];

  const paras = clean.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);

  // 一次切分：过长的段落按句末标点拆开
  const units = [];
  for (const p of paras) {
    if (p.length <= size) {
      units.push(p);
      continue;
    }
    const sents = p.split(/(?<=[。！？；.!?;])\s*/).filter(Boolean);
    let buf = '';
    for (const s of sents) {
      if (buf && (buf + s).length > size) {
        units.push(buf.trim());
        buf = s;
      } else {
        buf += s;
      }
    }
    if (buf.trim()) units.push(buf.trim());
  }

  // 二次兜底：仍超长的单元（无标点长文本、代码块、长列表）硬切
  const bounded = [];
  for (const u of units) {
    if (u.length <= size) bounded.push(u);
    else bounded.push(...hardSplit(u, size));
  }

  // 合并过短单元，并保留 overlap 字符的上下文重叠。
  // 不变量在此处直接保证：cur 永远 ≤ size，不需要事后补救式二次切分。
  const chunks = [];
  let cur = '';
  for (const u of bounded) {
    // Markdown 标题处强制断块。
    // 不加这条时，「## 标题 + 说明文字 + 第一条记录」会被合并进同一块，语义被稀释 ——
    // 实测「198094422 会被压缩成什么」检索时，真正含答案的那块（规则速览）
    // 反而竞争不过其他块，模型因此回答「资料里没有」。
    // 结构化文档（规则表、字典、FAQ）都受益于这条。
    const isHeading = /^#{1,6}\s/.test(u);
    if (cur && (isHeading || (cur + '\n' + u).length > size)) {
      chunks.push(cur.trim());
      // 注意：slice(-0) 等价于 slice(0)，会返回整个字符串。
      // 必须显式判断 overlap > 0，否则 overlap=0 时重叠量会变成 100%。
      const tail = overlap > 0 ? cur.slice(-overlap) : '';
      cur = tail + '\n' + u;
      // 单元本身接近 size 时（无标点长文本硬切而来）放不下重叠，丢弃重叠以守住不变量
      if (cur.length > size) cur = u;
    } else {
      cur = cur ? `${cur}\n${u}` : u;
    }
  }
  if (cur.trim()) chunks.push(cur.trim());

  return chunks;
}

/* ------------------------------ parent 元数据 ------------------------------ */

/**
 * 为每个块标注「父级」信息（B1 parent-child 分块）。
 *
 * 目的：小块检索精度高，但可能把 AND/OR 条件或上下句切散。
 * 记录每个块所属的**标题路径**（`##`/`###` 层级）与**规则/告警码**，
 * 检索后由 `buildMessages` 把**同一 parent 的相邻块合并**，
 * 让模型看到完整上下文（上限见 CONFIG.parentMergeMaxChars）。
 *
 * ⚠️ 不改 `chunkText` 的契约（仍返回 string[]，单块 ≤ chunkSize 的不变量不动）——
 * 这里只是**旁挂**元数据，便于单测与回归。
 *
 * @param {string} raw      文档原文
 * @param {string[]} parts  chunkText(raw) 的结果（顺序一致）
 * @returns {Array<{parent:string, headingPath:string[], ruleId:string, alarmCodes:string[]}>}
 */
export function annotateChunks(raw, parts) {
  const text = String(raw || '').replace(/\r\n/g, '\n');
  // 逐行扫描，维护当前标题栈（# 层级）。
  const headings = []; // 形如 [{level, text}]
  const lineHeadingAt = []; // 每行开始时的标题栈快照（只用标题文本路径）

  const lines = text.split('\n');
  const snapshots = [];
  for (const line of lines) {
    const m = line.match(/^(#{1,6})\s+(.+?)\s*$/);
    if (m) {
      const level = m[1].length;
      // 弹出比当前层级更深或相等的标题
      while (headings.length && headings[headings.length - 1].level >= level) headings.pop();
      headings.push({ level, text: m[2].trim() });
    }
    snapshots.push(headings.map((h) => h.text));
  }

  // 为每个块在原文里定位它出现的行号（用块首若干非空白字符匹配）。
  const out = [];
  let searchFrom = 0;
  const normLine = (s) => s.replace(/\s+/g, '');
  const sourceLines = lines.map(normLine);
  for (const part of parts) {
    const probe = normLine(part).slice(0, 40);
    let at = -1;
    if (probe) {
      for (let i = searchFrom; i < sourceLines.length; i++) {
        if (sourceLines[i] && sourceLines[i].includes(probe.slice(0, 20))) {
          at = i;
          break;
        }
      }
    }
    if (at < 0) at = Math.min(searchFrom, snapshots.length - 1);
    searchFrom = Math.max(at, 0);

    const headingPath = (snapshots[at] || []).slice();
    const parent = headingPath.length ? headingPath.join(' › ') : '';
    // 从块内抽规则 ID（`规则 zte-4g-siteoutage` / `#227`）与告警码（≥3 位数字）
    const ruleId =
      (part.match(/规则\s+([A-Za-z0-9][\w-]{2,})/) || [])[1] ||
      (part.match(/#(\d{1,4})\b/) || [])[1] ||
      '';
    const alarmCodes = [...new Set(part.match(/\b\d{3,}\b/g) || [])].slice(0, 40);

    out.push({ parent, headingPath, ruleId, alarmCodes });
  }
  return out;
}

/* --------------------------------- 索引 IO -------------------------------- */

export function saveIndex(index, path = CONFIG.indexPathAbs) {
  mkdirSync(dirname(path), { recursive: true });
  // 原子写入：先落 .tmp 再 rename 覆盖。
  // 直接 writeFileSync 到已存在的文件在 SMB（Y: 盘）上会 EPERM ——
  // 该共享只允许新建文件、不允许原地覆写，但 rename 覆盖是允许的。
  // 顺带避免写到一半中断把索引写坏（旧文件在 rename 成功前始终完整）。
  const tmp = `${path}.tmp`;
  writeFileSync(tmp, JSON.stringify(index), 'utf8');
  renameSync(tmp, path);
}

export function loadIndex(path = CONFIG.indexPathAbs) {
  if (!existsSync(path)) {
    throw new Error(`索引不存在：${path}\n请先运行：npm run ingest`);
  }
  const index = JSON.parse(readFileSync(path, 'utf8'));
  if (!Array.isArray(index.chunks) || !Array.isArray(index.vectors)) {
    throw new Error(`索引文件损坏：${path}`);
  }
  if (index.chunks.length !== index.vectors.length) {
    throw new Error(`索引不一致：chunks=${index.chunks.length} vectors=${index.vectors.length}，请重跑 npm run ingest`);
  }
  return index;
}

/* ---------------------------------- BM25 ---------------------------------- */

/**
 * 分词（B2 词级 BM25 用）：中文按**字 bigram**、英文/数字按 **token**。
 *
 * 为什么中文用 bigram：本项目不引分词器（手册禁止加依赖），而 bge 语料里
 * 中文专名（站名、区域名）恰恰是 bigram 能抓住的。bigram 与英文 token 混在
 * 同一词袋里做 BM25，中英问法都能吃到字面信号。
 *
 * @returns {string[]} token 列表（可重复，供 tf 统计）
 */
export function tokenize(text) {
  const s = String(text || '');
  const out = [];
  // 英文单词 / 数字（含 4G、zte-4g-siteoutage 里的段）
  for (const m of s.matchAll(/[A-Za-z][A-Za-z0-9]*|\d+/g)) out.push(m[0].toLowerCase());
  // 中文：连续汉字段取 bigram（单字段也保留）
  for (const m of s.matchAll(/[一-龥]+/g)) {
    const seg = m[0];
    if (seg.length === 1) out.push(seg);
    for (let i = 0; i + 1 < seg.length; i++) out.push(seg.slice(i, i + 2));
    // 也带上整段，便于命中完整术语（长度 ≥2）
    if (seg.length >= 2 && seg.length <= 8) out.push(seg);
  }
  return out;
}

/**
 * 预计算语料 BM25 统计（df / 平均长度）。
 *
 * 复杂度是 O(块数 × 块长)：822 块约 8ms，5462 块约 32ms（2026-10-18 实测）。
 * 单次调用不贵，但 `retrieve()` 每问一次就调一次，而**语料在一次进程生命周期内不变**
 * （索引只在启动时读一次，见 src/index.js）。所以统计结果按语料缓存，见 bm25StatsFor。
 *
 * 副作用：把分词结果旁挂到 `c._tokens`，供后续调用复用（不落盘）。
 * 这个副作用是有意的 —— 即使缓存未命中，也不会重复分词。
 *
 * @param {Array<{text:string, _tokens?:string[]}>} chunks
 * @returns {{df:Map<string,number>, avgdl:number, N:number, tf:Array<Map<string,number>>}}
 */
export function buildBm25Stats(chunks) {
  const tf = [];
  const df = new Map();
  let totalLen = 0;
  for (const c of chunks) {
    const toks = c._tokens || tokenize(c.text);
    c._tokens = toks; // 旁挂，供同一次检索复用（不落盘）
    const m = new Map();
    for (const t of toks) m.set(t, (m.get(t) || 0) + 1);
    tf.push(m);
    totalLen += toks.length;
    for (const t of m.keys()) df.set(t, (df.get(t) || 0) + 1);
  }
  const N = chunks.length || 1;
  return { df, avgdl: totalLen / N || 1, N, tf };
}

/**
 * 取（或构建）某组块的 BM25 统计，带缓存。
 *
 * `retrieve()` 每问一次都要这组统计，而语料在一次进程生命周期内不变
 * （索引只在启动时读一次，见 src/index.js），所以结果挂在**索引对象**上复用。
 *
 * 为什么键是「排除状态」而不是块数组：
 * 参与打分的块集只由两件事决定 —— 索引内容本身（= index 对象身份），
 * 以及 kbExcludeSources 是否生效（= manualIntent 是否命中）。
 * 同一索引下最多只有这两份统计，用一个布尔位区分即可。
 * 反过来，若对块数组做指纹遍历，每问都要 O(块数) 扫一遍，等于把缓存收益还回去。
 *
 * 失效语义：重新 ingest 会换掉 index 对象（src/index.js 再次 loadIndex），
 * 旧缓存随旧对象被 GC，无需显式失效接口。
 *
 * @param {object} index  索引对象（chunks/vectors），缓存挂在这里
 * @param {boolean} manualAllowed  本查询是否放回了被排除的手册
 * @param {number[]} liveIdx 参与打分的块下标（顺序决定 tf[] 的对位）
 * @returns {{df:Map<string,number>, avgdl:number, N:number, tf:Array<Map<string,number>>}}
 */
function bm25StatsFor(index, manualAllowed, liveIdx) {
  // 非枚举属性：不污染 JSON.stringify(index)，saveIndex 也不会把它落盘
  let cache = index.__bm25;
  if (!cache) {
    Object.defineProperty(index, '__bm25', {
      value: {},
      enumerable: false,
      writable: true,
      configurable: true,
    });
    cache = index.__bm25;
  }
  // liveIdx 在同一种状态下是确定的（由 exclude 与 manualIntent 唯一决定），
  // 所以 slot 命中即代表 tf[] 与 liveIdx 顺序一致。
  const slot = manualAllowed ? '_withManual' : '_default';
  if (!cache[slot]) {
    cache[slot] = buildBm25Stats(liveIdx.map((i) => index.chunks[i]));
  }
  return cache[slot];
}

/**
 * 单块 BM25 分（k1=1.2, b=0.75，标准取值）。
 * 只统计查询里出现过的 token —— 与经典 BM25 等价，且省去全词袋遍历。
 */
export function bm25Score(queryTokens, tfMap, stats) {
  const { df, avgdl, N } = stats;
  const k1 = 1.2;
  const b = 0.75;
  const dl = tfMap.size ? [...tfMap.values()].reduce((a, c) => a + c, 0) : 0;
  let score = 0;
  const qSeen = new Set();
  for (const t of queryTokens) {
    if (qSeen.has(t)) continue;
    qSeen.add(t);
    const f = tfMap.get(t) || 0;
    if (!f) continue;
    const n = df.get(t) || 0;
    const idf = Math.log(1 + (N - n + 0.5) / (n + 0.5));
    score += (idf * (f * (k1 + 1))) / (f + k1 * (1 - b + (b * dl) / avgdl));
  }
  return score;
}

/**
 * 把 BM25 原始分归一化到 [0,1]，便于与余弦融合。
 *
 * ## 为什么要「带门槛」而不是简单除以最高分（2026-10-28 修）
 *
 * 旧实现是 `s / max`。它有个致命性质：**任何查询都会产生一个 1.0** ——
 * 只要语料里有一块和问题共享哪怕一个字，那一块就被顶成满分，再乘权重 0.3，
 * 等于白送 +0.3。语料从 1244 块涨到 5884 块（整套 iMind 手册入库）之后，
 * 「今天天气怎么样」「公司食堂几点开饭」「报销流程怎么走」全部被判成**命中**：
 * 实测 top1 = 0.62~0.69，而它们其实只共享了「天/气/报/公」这种单字噪声。
 *
 * 实测原始分分布（bge-m3 + 5884 块）：
 *   · 真命中：34 ~ 55（「库房有哪些仓库」52.5、「压缩规则」54.5）
 *   · 单字噪声：7 ~ 10（天气 10.5、报销 7.2、食堂 8.2）
 *   · 完全无重叠：0（「年假有几天」）
 * 两档之间有一条很宽的空档，所以用**双门槛**：
 *   `minRaw` 绝对地板（挡单字噪声）+ `relMin * max` 相对地板（挡「同一查询里
 *   明显弱一档」的块，例如 52.5 与 15.7 同场时，15.7 不该拿到 0.3 的加成）。
 * 门槛以下的块 BM25 记 0，与「没有字面证据」等价 —— 纯语义题不受影响。
 *
 * @param {number[]} scores 原始 BM25
 * @param {{minRaw?:number, relMin?:number}} [opts] 门槛；不传则退回旧的纯 max 归一
 */
export function normalizeBm25(scores, { minRaw = 0, relMin = 0 } = {}) {
  const max = Math.max(0, ...scores);
  if (!max) return scores.map(() => 0);
  const floor = Math.max(minRaw, relMin * max);
  if (!floor) return scores.map((s) => s / max);
  return scores.map((s) => (s >= floor ? s / max : 0));
}

/* ---------------------------------- 检索 ---------------------------------- */

/**
 * 提问是否在问「操作手册里的东西」（界面 / 菜单 / 如何创建用户组…）。
 * 只有这类问法才把被排除的操作手册（如 07_）纳入默认检索。
 *
 * @param {string} q
 * @param {object} cfg
 * @returns {boolean}
 */
export function manualIntent(q, cfg = CONFIG) {
  const re = String(cfg.kbManualIntent || '').trim();
  if (!re) return false;
  try {
    return new RegExp(re, 'i').test(String(q || ''));
  } catch {
    // 配置写坏了不能把检索搞崩 —— 当无意图处理（继续排除手册，安全方向）
    return false;
  }
}

/**
 * @returns {{
 *   hit: boolean, gap: number, baseline: number, topBase: number, useGap: boolean,
 *   hits: Array<{text,source,title,sem,lex,base,confident}>, total: number, excluded: number
 * }}
 */
export function retrieve({ queryVec, queryText, index, cfg = CONFIG }) {
  const n = index.chunks.length;
  const sw = cfg.semanticWeight ?? 0.78;
  const lw = cfg.lexicalWeight ?? 0.22;

  // 来源排除策略（见 config.json $kbSourcePolicy）。
  // 07_ 操作手册占索引 52% 的块，中文问「级别/压缩」时向量容易漂到通用操作段落、
  // topK 被同一文件占满；命中块还会随 search_knowledge 上传云端（合规风险）。
  // 只有问法命中 kbManualIntent 时才把手册放回来。
  const exclude = Array.isArray(cfg.kbExcludeSources) ? cfg.kbExcludeSources : [];
  const allowManual = manualIntent(queryText, cfg);

  const rows = new Array(n);
  let excluded = 0; // 被排除的块数（诊断用，见 onDebug）
  // 查询里出现的长数字（告警码、单号、编号）做精确命中加权。
  //
  // 为什么必须加：纯语义检索对「精确 ID」天然无力。实测查「siteAlarmCode 198094422
  // 会被压缩成什么」时，取回的 6 个块全是别的告警码 —— 因为所有
  // 「告警码 X → 父告警码 Y」的块结构高度同质，向量几乎重合，
  // 而字面匹配权重只有 0.22，压不过语义噪声。真正含目标 ID 的那块反而被淹没。
  const queryIds = String(queryText || '').match(/\d{4,}/g) || [];
  const idBonus = Number(cfg.idBonus ?? 0.15);

  // —— B2：词级 BM25，与向量**融合后再取 topK** ——
  // 老写法先按 base 取 topK 再判命中；BM25 需要知道全库统计，故先在 live 集上算。
  const bm25w = Number(cfg.bm25Weight ?? 0);
  const liveIdx = [];
  for (let i = 0; i < n; i++) {
    const chunk = index.chunks[i];
    // 排除列表命中的块**直接跳过**，不给 0 分占位 ——
    // 否则它会进入中位数基线，把「这个查询对这批语料的泛化水位」拉歪。
    if (exclude.length && !allowManual && exclude.includes(chunk.source)) {
      excluded++;
      continue;
    }
    liveIdx.push(i);
  }
  const liveSet = new Set(liveIdx);

  let bm25norm = new Map(); // idx → 归一化 BM25
  if (bm25w > 0 && liveIdx.length) {
    // 统计按「索引 + 排除状态」缓存，见 bm25StatsFor 的注释。
    // 不再每问重建 liveChunks 数组与全库词袋统计。
    const stats = bm25StatsFor(index, allowManual, liveIdx);
    const qToks = tokenize(queryText);
    const raw = liveIdx.map((gi, k) => bm25Score(qToks, stats.tf[k], stats));
    // 双门槛见 normalizeBm25 的注释：不设门槛时任何查询都会拿到一个 1.0，
    // 手册入库后「今天天气怎么样」这类域外问题会被判成命中。
    const norm = normalizeBm25(raw, {
      minRaw: Number(cfg.bm25MinRaw ?? 0),
      relMin: Number(cfg.bm25RelMin ?? 0),
    });
    liveIdx.forEach((gi, k) => bm25norm.set(gi, norm[k]));
  }

  for (let i = 0; i < n; i++) {
    const chunk = index.chunks[i];
    if (!liveSet.has(i)) continue;
    const text = chunk.text;
    const sem = cosine(queryVec, index.vectors[i]);
    const lex = bigramSim(queryText, text);
    let base = sem * sw + lex * lw;
    const bm = bm25norm.get(i) || 0;
    if (bm25w > 0) base += bm * bm25w;
    if (queryIds.length && queryIds.some((id) => text.includes(id))) {
      base += idBonus;
    }
    rows[i] = { idx: i, sem, lex, bm25: bm, base, ...chunk };
  }
  // 排除后可能留下空洞下标 —— 压掉（否则 length 仍是 n，排序里混 undefined）
  const live = rows.filter(Boolean);
  live.sort((a, b) => b.base - a.base);

  // 基线 = 参与打分的块 base 的中位数
  const sorted = live.map((r) => r.base).sort((a, b) => b - a);
  const m = live.length;
  const baseline = m ? sorted[Math.floor(m / 2)] : 0;
  // 条目过少时中位数不可靠（gap→0，什么都判不中），退化为纯绝对阈值
  const useGap = m >= 4;

  const top = live[0] ?? null;
  const gap = top ? top.base - baseline : 0;
  const hit = top
    ? useGap
      ? top.base >= cfg.minAbs && gap >= cfg.minGap
      : top.base >= cfg.minAbs
    : false;

  // B4 MMR：同一 source 最多保留 mmrMaxPerSource 块。
  // topK 被同一文件占满时（07_ 之外的语料也可能扎堆），6 个名额只带回 1 条信息，
  // 模型看到的「资料」严重退化。这里在取 topK 时按来源限流，把名额留给别的文件。
  // 只影响喂给模型的 hits，不影响 baseline/useGap 的判定口径。
  const cap = Number(cfg.mmrMaxPerSource ?? 0);
  const picked = [];
  if (cap > 0) {
    const perSource = new Map();
    for (const r of live) {
      if (picked.length >= cfg.topK) break;
      const cnt = perSource.get(r.source) || 0;
      if (cnt >= cap) continue;
      perSource.set(r.source, cnt + 1);
      picked.push(r);
    }
  } else {
    picked.push(...live.slice(0, cfg.topK));
  }

  const hits = picked.map((r) => ({
    ...r,
    // 逐条传递命中标记，调用方据此决定能否作为依据喂给模型
    confident: useGap ? r.base >= cfg.minAbs && r.base - baseline >= cfg.minGap : r.base >= cfg.minAbs,
  }));

  return { hit, gap, baseline, topBase: top?.base ?? 0, useGap, hits, total: m, excluded };
}

/* --------------------------------- 生成回答 -------------------------------- */

/**
 * 追加在 systemPrompt 末尾的语言要求。
 *
 * 为什么不只靠 systemPrompt 里那句「用与提问相同的语言回答」：
 * systemPrompt 本身是**中文写的**，模型容易被它带偏成中文输出。
 * 把「本次请用英文」放到消息序列**最后**（离生成最近）最不容易被忽略 ——
 * 这是两道保险，不是重复。
 */
const LANG_HINT = {
  zh: '\n\n本次提问是中文，请用中文回答。',
  en: '\n\nThis question is in English — reply in English, keeping the same concise style.',
};

/**
 * 带上下文时追加到 systemPrompt 末尾的护栏。
 *
 * 必须是护栏而不是礼貌提醒：硬性规则 1 说「只使用资料中的内容」，而历史里
 * 恰好有一段**看起来像依据**的上轮答案。不加这句时模型会走上省事的路线 ——
 * 直接复用（甚至加工）上轮答案的数字与结论，等于把上一轮可能的误差滚雪球。
 */
const CONTEXT_NOTE =
  '\n\n补充：下面附有本会话此前的问答，仅用于理解指代（「它」「第二种」「刚才那个」指的是什么）。' +
  '结论仍必须来自最后一条消息里的「资料」，不要用历史答案中的数字或结论代替资料作答；' +
  '资料与历史不一致时，以资料为准。';

/**
 * 组装喂给模型的消息；只使用 confident 的条目作为依据。
 * @param {Array<{q:string,a:string}>} [history] 最近几轮问答（时间正序）
 */
export function buildMessages(question, hits, lang = 'zh', history = []) {
  const usable = mergeParentChunks(hits.filter((h) => h.confident));
  // 每个 confident 块前缀带**文件名与标题**（出处），模型据以在结论后给出
  // 「来源：文件名」。以前只给【i】正文，模型无从知道依据来自哪个文件，
  // 回答也就没法带出处 —— 规则题会被压掉关键条件又说不清依据。
  const context = usable
    .map((h, i) => `【${i + 1}｜${h.source || '未知文件'}｜${h.title || ''}】\n${h.text}`)
    .join('\n\n');
  const withHistory = (history || []).flatMap((t) => [
    { role: 'user', content: t.q },
    { role: 'assistant', content: t.a },
  ]);
  return [
    {
      role: 'system',
      content:
        CONFIG.systemPrompt +
        (withHistory.length ? CONTEXT_NOTE : '') +
        (LANG_HINT[lang] || LANG_HINT.zh),
    },
    ...withHistory,
    { role: 'user', content: `资料：\n${context}\n\n问题：${question}` },
  ];
}

/* --------------------------- parent-child 合并 --------------------------- */

/**
 * 把**同一 parent（标题路径相同）**的相邻块合并回一段上下文（B1）。
 *
 * 为什么需要：小块检索精度高，但会把 AND/OR 条件、表格行、上下句切散
 * —— 「CSD 定几级」召回的那块可能只有半条规则。合并同一标题下的相邻块，
 * 让模型看到完整小节（受 `parentMergeMaxChars` 上限约束，默认 1200）。
 *
 * 只在**同一 source 且同一 parent 且 seq 相邻**时合并，避免跨文档拼凑。
 * 合并后的 `text` 变大，但 `source`/`title`/`parent` 保留首个块的值（出处不变）。
 *
 * @param {Array} hits 已按分数排序的 confident 块
 * @returns {Array} 合并后的块（顺序保持首个块的位置）
 */
export function mergeParentChunks(hits, maxChars = CONFIG.parentMergeMaxChars ?? 1200) {
  const sorted = hits.slice(); // 已按 base 降序，保持
  const used = new Set();
  const out = [];
  for (let i = 0; i < sorted.length; i++) {
    if (used.has(i)) continue;
    const cur = sorted[i];
    if (!cur.parent) {
      out.push(cur);
      used.add(i);
      continue;
    }
    // 找同一 source+parent 的其他块，按 seq 排序后拼进来（受上限约束）
    const group = [cur];
    for (let j = i + 1; j < sorted.length; j++) {
      if (used.has(j)) continue;
      const other = sorted[j];
      if (other.source === cur.source && other.parent === cur.parent) {
        group.push(other);
        used.add(j);
      }
    }
    used.add(i);
    if (group.length === 1) {
      out.push(cur);
      continue;
    }
    group.sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0));
    let text = '';
    const overflow = [];
    for (const g of group) {
      if (text && text.length + g.text.length + 1 > maxChars) {
        // 放不下的块**不丢**：作为独立条目留在候选里（保住召回内容）
        overflow.push(g);
        continue;
      }
      text = text ? `${text}\n${g.text}` : g.text;
    }
    out.push({ ...cur, text });
    for (const g of overflow) out.push(g);
  }
  return out;
}

/* ------------------------------- 追问补全 ------------------------------- */

/**
 * 把口语追问补全成「不需要上文也能看懂」的检索问题。
 *
 * 为什么必须做这一步：嵌入检索的输入只有当前这句。追问「那第二种情况呢」
 * 十几个字没有任何领域词，向量落到语料中心，必然判未命中 —— 光把历史喂给
 * 生成模型没用，历史影响的是**答案**，而召回早在答案之前就失败了。
 *
 * 顺带拿到「是不是在延续上文」这个信号：是新话题就把历史丢掉，
 * 这是多轮记忆最主要的污染来源（同一个人连问两个不相关的模块时，
 * 旧话题会持续拽着召回和措辞）。
 *
 * 失败（超时 / 格式不对 / 云端报错）返回 null，调用方退回原句 —— 
 * 补全是增强，不是依赖（同 retryWithRewrite 的取舍）。
 */
const RESOLVE_PROMPT =
  '你在帮一个知识库问答机器人理解追问。下面给出这个人最近几轮的问答，以及他新的提问。\n' +
  '1) 判断新提问是否在延续上文（问的是同一件事）：延续 = yes，另起话题 = no。\n' +
  '2) 把新提问改写成一句**不看上文也能读懂**的检索问题，补出它省略的主语和对象；\n' +
  '   保持新提问的语言（中文就写中文，英文就写英文），不要扩写成长句。\n' +
  '只输出两行，不要解释：\n' +
  'CONTINUE: yes 或 no\n' +
  'QUERY: <改写后的独立问题>';

/** 解析模型的两行输出；缺 QUERY 视为失败。 */
export function parseResolve(content) {
  const s = String(content || '');
  const q = s.match(/^\s*QUERY\s*[:：]\s*(.+)$/im);
  if (!q) return null;
  const query = q[1].trim();
  if (query.length < 2) return null;
  const c = s.match(/^\s*CONTINUE\s*[:：]\s*(yes|no|true|false|是|否)/im);
  const yes = c && /^(yes|true|是)/i.test(c[1]);
  return { query, continue: c ? !!yes : true };
}

/** 渲染进 prompt 的历史块（只用于补全判断，不进正式对话消息）。 */
export function renderHistoryForResolve(history) {
  return (history || [])
    .map((t, i) => `${i + 1}) 问：${t.q}\n   答：${t.a}`)
    .join('\n');
}

async function resolveFollowUp(question, history, lang) {
  try {
    const { content } = await chat(
      [
        {
          role: 'system',
          content: RESOLVE_PROMPT + (LANG_HINT[lang] || LANG_HINT.zh),
        },
        {
          role: 'user',
          content: `最近问答：\n${renderHistoryForResolve(history)}\n\n新提问：${question}`,
        },
      ],
      { maxTokens: 160, temperature: 0 }
    );
    return parseResolve(content);
  } catch {
    return null;
  }
}

/* -------------------------------- 网页版兜底 -------------------------------- */

/**
 * 未命中时附上网页版助手地址。
 *
 * 只给链接、不代查：网页版能用模型通用知识、能多轮追问，那是它擅长的；
 * 机器人这边一旦放开通用知识，运维参数类问题就可能出现编造，
 * 而同事会把机器人说的话当依据去执行 —— 这条界线不动。
 */
export function withWebHint(text, lang, cfg = CONFIG) {
  const url = String(cfg.webUiFallbackUrl || '').trim();
  if (!url) return text;
  const tpl = pickText(lang, cfg.webUiFallbackText, cfg.webUiFallbackTextEn);
  if (!tpl) return text;
  return `${text}\n${tpl.replace(/\{url\}/g, url)}`;
}

/**
 * 二跳检索：LLM 改写查询 → 重新嵌入检索 → 命中则直接生成回答。
 *
 * 改写目标不是「优化问题」，而是**换掉问法的皮**：用户问「how is a TT created
 * from an alarm」，文档里写的是「告警驱动创建 Trouble Ticket（autoCreateTT）」——
 * 原句向量召回的是告警码字典，改写后的句子才对得上链路文档。
 * 中英各生成一条，两条都查，取命中的最高分；都不中就放弃（宁可承认不知道）。
 *
 * 任何一步失败都返回 null，由调用方走原有兜底 —— 二跳是增强，不是依赖。
 */
const REWRITE_PROMPT =
  '你是一个检索查询改写器。把用户的提问改写成知识库文档中「可能会出现的表述」。\n' +
  '要求：陈述式、带领域术语、不要口语；给出中文和英文各一条；只输出两行，格式：\n' +
  'ZH: <中文表述>\nEN: <English paraphrase>';

async function retryWithRewrite(question, index, cfg, lang, onDebug) {
  try {
    const { content } = await chat(
      [
        { role: 'system', content: REWRITE_PROMPT },
        { role: 'user', content: String(question || '').slice(0, 500) },
      ],
      { maxTokens: 128, temperature: 0 }
    );
    const queries = String(content || '')
      .split('\n')
      .map((l) => l.replace(/^(ZH|EN)\s*[:：]\s*/i, '').trim())
      .filter((l) => l && l.length >= 4)
      .slice(0, 2);
    if (!queries.length) return null;

    let best = null;
    for (const q of queries) {
      const vec = await embedOne(q);
      const r = retrieve({ queryVec: vec, queryText: q, index, cfg });
      onDebug?.({ stage: 'rewrite-retry', rewritten: q, hit: r.hit, topBase: +r.topBase.toFixed(4) });
      if (r.hit && (!best || r.topBase > best.retrieval.topBase)) {
        best = { query: q, retrieval: r };
      }
    }
    if (!best) return null;

    const { content: answerText, stats } = await chat(
      buildMessages(best.query, best.retrieval.hits, lang)
    );
    // 二跳的生成同样可能是空的（只剩标记/思考）—— 空串不能当回答，交回调用方兜底
    if (!String(answerText || '').trim()) return null;
    return {
      answered: true,
      text: answerText,
      retrieval: best.retrieval,
      stats: { ...stats, rewritten: best.query, totalMs: undefined },
    };
  } catch {
    // 改写/检索/生成的任何失败都不致命 —— 回到固定兜底文案
    return null;
  }
}

/**
 * 完整问答链路：嵌入 → 检索 → 命中判定 → 生成。
 * @returns {Promise<{answered:boolean,text:string,retrieval:object,stats?:object}>}
 */
export async function answer(
  question,
  index,
  { cfg = CONFIG, onDebug, lang = 'zh', history = [] } = {}
) {
  const t0 = Date.now();

  // ── 追问补全 ──
  // 「那个单子未闭环」这类提问**单看没有主语**：没有日期、没有级别、
  // 没有站点，向量检索只能检索出字面相近的段落，答非所问。
  // 有会话历史时，先用模型把它改写成一句自洽的独立问题再检索。
  //
  // 只在**有历史**时做：没有上一轮就无所谓"追问"，多花一次调用纯属浪费。
  if (history.length) {
    const resolved = await resolveFollowUp(question, history, lang);
    // CONTINUE:no 表示模型判断这是全新话题，不该套用历史 —— 尊重它的判断
    if (resolved && resolved.continue && resolved.query) question = resolved.query;
  }

  // 嵌入不可用时**不当故障抛出**：以前这里一句 `await embedOne` 直接冒泡到
  // 接入层，最终回一句含糊的 errorText（「抱歉，我这边出了点故障」），
  // 且 answered=0 —— 用户既不知道原因，也不知道该找谁。
  // 典型触发：Ollama 那台缺 `bge-m3`（404 model not found），或嵌入服务临时不可达。
  // 改为**就地降级**：回一句说清「知识库此刻不可用」的话（仍 answered=false，
  // 因为它确实没答上），但语义明确、可行动。工具通道不走这里，故不受影响。
  let queryVec;
  try {
    queryVec = await embedOne(question);
  } catch (err) {
    const reason = String(err?.message || err || '').trim();
    return {
      answered: false,
      text: pickText(
        lang,
        `我这边的知识库暂时不可用（嵌入服务异常：${reason.slice(0, 120)}），查不了这个问题。` +
          `请稍后再试，或直接问「XX站有没有告警 / 查 TT单号」这类不依赖知识库的问题。`,
        `My knowledge base is unavailable right now (embedding service error: ${reason.slice(0, 120)}). ` +
          `Please try again later, or ask something that doesn't need the knowledge base (e.g. "check TT...", "site X alarms").`
      ),
      stats: { totalMs: Date.now() - t0, embedError: reason.slice(0, 160) },
    };
  }
  const tEmbed = Date.now() - t0;

  const retrieval = retrieve({ queryVec, queryText: question, index, cfg });
  onDebug?.({
    stage: 'retrieve',
    embedMs: tEmbed,
    topBase: +retrieval.topBase.toFixed(4),
    baseline: +retrieval.baseline.toFixed(4),
    gap: +retrieval.gap.toFixed(4),
    useGap: retrieval.useGap,
    hit: retrieval.hit,
    // 被来源策略排除掉的块数（07_ 等）——debug 时一眼看出「手册有没有被放回来」
    excluded: retrieval.excluded,
    candidates: retrieval.hits.map((h) => ({
      base: +h.base.toFixed(4),
      sem: +h.sem.toFixed(4),
      lex: +h.lex.toFixed(4),
      bm25: +(h.bm25 || 0).toFixed(4),
      source: h.source,
    })),
  });

  if (!retrieval.hit) {
    // ── 二跳：未命中时让模型改写提问再检索一次 ──
    // 用户口语（尤其英文问法、复合句）与文档标题差异大时，向量会偏到别的块。
    // 标准补救：把「用户怎么问」改写成「文档里怎么写」再查。只重试一次，
    // 改写失败或仍不命中 → 维持固定兜底文案（不经模型的回复按语言取）。
    if (cfg.rewriteRetry !== false) {
      const retried = await retryWithRewrite(question, index, cfg, lang, onDebug);
      if (retried) return retried;
    }
    return {
      answered: false,
      text: pickText(lang, cfg.notFoundText, cfg.notFoundTextEn),
      retrieval,
      stats: { totalMs: Date.now() - t0 },
    };
  }

  const { content, stats } = await chat(buildMessages(question, retrieval.hits, lang));

  // ── 空正文兜底 ──
  // 检索判了命中，但模型一个字都没吐（思考烧光预算 / 只剩工具调用标记被剥离）。
  // 以前这里会直接 `answered:true, text:''` —— 群里收到一条空消息，看着像机器人挂了。
  // 退回「原文摘录」：给的是资料原话 + 来源，比空消息有用，也不涉及任何编造。
  if (!content) {
    onDebug?.({ stage: 'empty-content' });
    return {
      answered: false,
      text: groundExcerpt(retrieval.hits, lang) || pickText(lang, cfg.notFoundText, cfg.notFoundTextEn),
      retrieval,
      stats: { ...stats, embedMs: tEmbed, totalMs: Date.now() - t0, emptyContent: true },
    };
  }

  // ── 生成后检测 ──
  // 模型守着「只依据资料」的规矩：召回的块答不了问题时，它会明说「资料里没有」。
  // 这类回答说明检索器判了命中但召回错了块 —— 同样给一次改写二跳的机会。
  // 误杀代价很低：二跳不中就原回答照发，多花的只是一次改写调用。
  if (cfg.rewriteRetry !== false && looksLikeMiss(content)) {
    const retried = await retryWithRewrite(question, index, cfg, lang, onDebug);
    if (retried) return retried;
  }

  // ── 数字忠实度护栏 ──
  // 生成文本里出现了召回的块**都没有**的长数字 → 丢弃这次生成。
  // 不试图「修正」——那一半会变成另一种编造。改回固定兜底文案，
  // 或只回 top1 原文摘录（前 400 字）+ 来源。
  const ungrounded = ungroundedIds(content, retrieval.hits);
  if (ungrounded.length) {
    onDebug?.({ stage: 'ungrounded', ids: ungrounded.slice(0, 5) });
    const excerpt = groundExcerpt(retrieval.hits, lang);
    return {
      answered: false,
      text: excerpt || pickText(lang, cfg.notFoundText, cfg.notFoundTextEn),
      retrieval,
      stats: { ...stats, embedMs: tEmbed, totalMs: Date.now() - t0, ungrounded: ungrounded.length },
    };
  }

  return {
    answered: true,
    text: content,
    retrieval,
    stats: { ...stats, embedMs: tEmbed, totalMs: Date.now() - t0 },
  };
}

/**
 * 摘录式兜底：生成不可信时，直接把 top1 原文前 400 字当答复，附来源。
 * 这是「答错不如弃权」的落地 —— 宁可给原文，也不给模型加工过的数字。
 */
export function groundExcerpt(hits, lang = 'zh') {
  const top = (hits || []).find((h) => h.confident);
  if (!top) return '';
  const body = String(top.text || '').trim().slice(0, 400);
  const src = top.source || '';
  return lang === 'en'
    ? `I couldn't produce a reliable answer. Closest excerpt:\n${body}\nSource: ${src}`
    : `我没法给出可靠回答。最接近的资料原文：\n${body}\n来源：${src}`;
}

/** 生成回答里的「资料没覆盖」特征（中英双语）。限长度防误杀长回答。 */
const MISS_RE =
  /(没有找到|没找到|没有依据|未提及|未涵盖|没有提及|无法回答|无法确定|资料[^。；]{0,8}(没有|未)|(does|do|did)\s+n[o']?t\s+(explain|cover|mention|contain|address|include)|n[o']t\s+(covered|explained|mentioned|addressed)|not (explained|covered|mentioned)|no (information|details) (about|on)|couldn'?t find|not available in)/i;

function looksLikeMiss(text) {
  const s = String(text || '');
  return s.length > 0 && s.length < 400 && MISS_RE.test(s);
}

/**
 * 数字忠实度护栏：生成文本里的长数字（≥3 位）若**都不**出现在召回的块里，
 * 判定为「编造」（ungrounded）。
 *
 * 为什么必须做：systemPrompt 要求「不得输出资料中未出现的规则 ID / 告警码 / 阈值」，
 * 但模型仍可能在资料答不了时凑一个像样的数字（「9970」「#227」）——
 * 群里的同事会拿它当依据去派单。数字类的幻觉代价最高，必须脚本拦。
 *
 * 取舍：只查**长数字**（≥3 位）。短数字（0/1/2/P1/P4）在自然语言里太常见，
 * 全查会大量误杀正常回答。
 *
 * 关键：corpus 的匹配**必须用整词边界**，不能用 `String.includes`。
 * 子串匹配会把 `9991` 当作 `999` 的存在证据，导致 3 位幻觉数字被错误放行
 * （如「#999」会被「#1991」或「9991」的字面包含覆盖）。这里用单词边界 `\b`
 * 切 corpus 里的所有数字 token，再做集合包含判断。
 *
 * @param {string} answer 生成文本
 * @param {Array<{text:string}>} hits 召回的块（**所有** confident 块，不只 top1）
 * @returns {string[]} 编造的数字列表（空数组=通过）
 */
export function ungroundedIds(answer, hits) {
  const text = String(answer || '');
  const ids = [...new Set(text.match(/\d{3,}/g) || [])];
  if (!ids.length) return [];
  const corpusTokens = new Set();
  for (const h of hits || []) {
    if (h.confident === false) continue;
    const chunkText = String(h.text || '');
    // 从 corpus 块里抽出所有 ≥3 位数字，整词匹配（避免 9991 吸收 999）
    for (const m of chunkText.matchAll(/\d{3,}/g)) corpusTokens.add(m[0]);
  }
  return ids.filter((id) => !corpusTokens.has(id));
}
