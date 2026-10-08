/**
 * 配置加载：config.json 为基准，环境变量可覆盖（便于临时调试 / 容器部署）。
 * 路径统一解析为「项目根目录」下的绝对路径，避免受 cwd 影响。
 */
import { readFileSync } from 'node:fs';
import { dirname, resolve, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function readJson(rel) {
  try {
    return JSON.parse(readFileSync(resolve(ROOT, rel), 'utf8'));
  } catch (err) {
    throw new Error(`读取 ${rel} 失败：${err.message}`);
  }
}

const raw = readJson('config.json');

/** 把相对路径解析为绝对路径 */
const abs = (p) => (isAbsolute(p) ? p : resolve(ROOT, p));

export const CONFIG = {
  ...raw,

  // —— 对话 provider ——
  chatProvider: (process.env.CHAT_PROVIDER || raw.chatProvider || 'ollama').toLowerCase(),
  chatModel: process.env.CHAT_MODEL || raw.chatModel,
  chatBaseUrl: process.env.CHAT_BASE_URL || raw.chatBaseUrl || '',
  chatApiKeyEnv: raw.chatApiKeyEnv || 'OPENAI_API_KEY',
  chatApiKey: process.env.CHAT_API_KEY || raw.chatApiKey || '',
  chatTimeoutMs: Number(process.env.CHAT_TIMEOUT_MS ?? raw.chatTimeoutMs ?? 60000),
  // Thinking 模式：知识库问答不需要思维链，只会白烧 token 预算。
  // false = 显式关闭；true = 显式开启；null/undefined = 不传该参数，用服务端默认。
  enableThinking:
    process.env.ENABLE_THINKING != null
      ? process.env.ENABLE_THINKING === '1' || process.env.ENABLE_THINKING === 'true'
      : raw.enableThinking ?? null,

  // —— 本地嵌入（始终走 Ollama）——
  ollamaUrl: process.env.OLLAMA_URL || raw.ollamaUrl,
  embedModel: process.env.EMBED_MODEL || raw.embedModel,

  knowledgeDirAbs: abs(process.env.KNOWLEDGE_DIR || raw.knowledgeDir),
  indexPathAbs: abs(process.env.INDEX_PATH || raw.indexPath),
  // 查表数据（告警码 / 压缩规则 / 级别规则）——由 ingest 生成，查表工具用。
  // 与 index.json 一样是**可重建产物**，data/*.json 已 gitignore。
  lookupsPathAbs: abs(process.env.LOOKUPS_PATH || raw.lookupsPath || 'data/lookups.json'),

  authDirAbs: abs(process.env.AUTH_DIR || 'data/auth'),
  logDirAbs: abs('data/logs'),

  // 问答记录（SQLite）。与运行日志**分开存**：
  // 运行日志按天滚动会过期，问答记录是长期积累的分析资产。
  // 含真实号码，靠 .gitignore 的 data/*.sqlite* 挡住，不入库。
  qaLogPath: process.env.QA_LOG_PATH || abs('data/qa.sqlite'),
  // 关掉后完全不记（排查"记录本身是否影响性能"时用）
  qaLogEnabled: process.env.QA_LOG_ENABLED !== '0',

  // 数值型环境变量覆盖
  topK: Number(process.env.TOP_K ?? raw.topK),
  minAbs: Number(process.env.MIN_ABS ?? raw.minAbs),
  minGap: Number(process.env.MIN_GAP ?? raw.minGap),
  // 检索权重：以前只靠 rag.js 里的 `?? 默认值` 兜底，改配置能生效但没法用环境变量临时试。
  // 统一到这一层，调参时不用改文件。
  semanticWeight: Number(process.env.SEMANTIC_WEIGHT ?? raw.semanticWeight ?? 0.78),
  lexicalWeight: Number(process.env.LEXICAL_WEIGHT ?? raw.lexicalWeight ?? 0.22),
  idBonus: Number(process.env.ID_BONUS ?? raw.idBonus ?? 0.15),

  // 默认检索排除的来源（相对路径数组）。见 config.json 的 $kbSourcePolicy。
  // 环境变量 KB_EXCLUDE_SOURCES 用逗号分隔覆盖（便于临时试值）；空串 → 不排除。
  kbExcludeSources: (() => {
    const env = process.env.KB_EXCLUDE_SOURCES;
    if (env != null) return env.split(',').map((s) => s.trim()).filter(Boolean);
    return Array.isArray(raw.kbExcludeSources) ? raw.kbExcludeSources : [];
  })(),
  kbManualIntent: process.env.KB_MANUAL_INTENT || raw.kbManualIntent || '',

  // —— P1 检索增强 ——
  // parent-child 合并上限：同标题路径的相邻块合并回上下文时的字符上限。
  parentMergeMaxChars: Number(process.env.PARENT_MERGE_MAX_CHARS ?? raw.parentMergeMaxChars ?? 1200),
  // MMR 同源限流：topK 内同一 source 最多保留几块。
  mmrMaxPerSource: Number(process.env.MMR_MAX_PER_SOURCE ?? raw.mmrMaxPerSource ?? 3),
  // BM25（词级字面）与向量的融合权重。置 0 即回退到旧 bigram 混合。
  bm25Weight: Number(process.env.BM25_WEIGHT ?? raw.bm25Weight ?? 0.3),

  cooldownMs: Number(process.env.COOLDOWN_MS ?? raw.cooldownMs),
  maxTokens: Number(process.env.MAX_TOKENS ?? raw.maxTokens ?? 512),

  // —— 工具路由 / 工单聚合统计 ——
  // 环境变量可临时关掉（排查「是不是工具路由把问题带偏了」时很有用）。
  toolsEnabled:
    process.env.TOOLS_ENABLED != null
      ? !(process.env.TOOLS_ENABLED === '0' || process.env.TOOLS_ENABLED === 'false')
      : raw.toolsEnabled !== false,
  myAppApiBase: process.env.MY_APP_API_BASE || raw.myAppApiBase || '',
  ttStatsHttp:
    process.env.TT_STATS_HTTP != null
      ? !(process.env.TT_STATS_HTTP === '0' || process.env.TT_STATS_HTTP === 'false')
      : raw.ttStatsHttp !== false,
  ttStatsTimeoutMs: Number(process.env.TT_STATS_TIMEOUT_MS ?? raw.ttStatsTimeoutMs ?? 15000),
  ttStatsSampleLimit: Number(process.env.TT_STATS_SAMPLE_LIMIT ?? raw.ttStatsSampleLimit ?? 3),
  ttStatsListLimit: Number(process.env.TT_STATS_LIST_LIMIT ?? raw.ttStatsListLimit ?? 10),

  // —— 会话记忆 ——
  memoryEnabled:
    process.env.MEMORY_ENABLED != null
      ? !(process.env.MEMORY_ENABLED === '0' || process.env.MEMORY_ENABLED === 'false')
      : raw.memoryEnabled !== false,
  memoryMaxTurns: Number(process.env.MEMORY_MAX_TURNS ?? raw.memoryMaxTurns ?? 3),
  memoryTtlMs: Number(process.env.MEMORY_TTL_MS ?? raw.memoryTtlMs ?? 600000),
  memoryMaxChats: Number(process.env.MEMORY_MAX_CHATS ?? raw.memoryMaxChats ?? 200),
  // 追问消解：有历史时多花一次小模型调用，把「那第二种情况呢」补全成可检索的独立问题。
  memoryResolve:
    process.env.MEMORY_RESOLVE != null
      ? !(process.env.MEMORY_RESOLVE === '0' || process.env.MEMORY_RESOLVE === 'false')
      : raw.memoryResolve !== false,

  // —— notify 进程（src/notify.js）专用配置块 ——
  // 与聊天机器人的语义完全无关（不查模型、不读索引），只为文件作业速率控制：
  //  - sendIntervalMs：每发一张图/文档后等多少毫秒再发下一条（防风控）
  //  - perGroupDelayMs：群间延时（每条图跨群时也要等，避免单进程被限频）
  //  - maxImages / maxDocuments：单作业内最多发多少张图/多少份文档
  // 不暴露聊天端配置（避免被误读为影响 @机器人问答）。
  notify: (() => {
    const n = (raw.notify && typeof raw.notify === 'object') ? raw.notify : {};
    const fs = (n.fileSend && typeof n.fileSend === 'object') ? n.fileSend : {};
    const env = process.env.NOTIFY_FILE_SEND;
    // 允许整段 JSON 覆盖（便于临时调参）；解析失败忽略走下面逐项
    let override = {};
    if (env) {
      try { override = JSON.parse(env); } catch { /* 忽略，走默认 */ }
    }
    const merged = { ...fs, ...override };
    return {
      fileSend: {
        sendIntervalMs: Number(merged.sendIntervalMs ?? 2000),
        perGroupDelayMs: Number(merged.perGroupDelayMs ?? 8000),
        maxImages: Number(merged.maxImages ?? 6),
        maxDocuments: Number(merged.maxDocuments ?? 1),
      },
    };
  })(),
};

/** 供 --check-only / 日志展示用 */
export function describeConfig() {
  const chatTarget =
    CONFIG.chatProvider === 'ollama' ? `${CONFIG.chatModel} @ ${CONFIG.ollamaUrl}` : `${CONFIG.chatModel} @ ${CONFIG.chatBaseUrl}`;
  return {
    对话模型: `[${CONFIG.chatProvider}] ${chatTarget}`,
    嵌入模型: `${CONFIG.embedModel} @ ${CONFIG.ollamaUrl}`,
    知识库目录: CONFIG.knowledgeDirAbs,
    索引文件: CONFIG.indexPathAbs,
    回复模式: CONFIG.replyMode,
    群白名单: CONFIG.allowGroups,
    命中阈值: `minAbs=${CONFIG.minAbs}, minGap=${CONFIG.minGap}`,
    会话记忆: CONFIG.memoryEnabled
      ? `开（每人最近 ${CONFIG.memoryMaxTurns} 轮，闲置 ${Math.round(CONFIG.memoryTtlMs / 60000)} 分钟过期` +
        `${CONFIG.memoryResolve ? '，追问自动补全成独立问题' : ''}）`
      : '关（每条提问都是全新对话）',
    工具路由: CONFIG.toolsEnabled
      ? `开（规则优先，不定则模型选工具；工单统计 ${CONFIG.ttStatsHttp !== false && CONFIG.myAppApiBase ? 'HTTP 优先 + SQLite 降级' : '仅本地 SQLite'}）`
      : '关（所有问题都走知识库检索）',
  };
}
