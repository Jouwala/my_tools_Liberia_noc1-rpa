/**
 * 配置加载：config.json 为基准，环境变量可覆盖（便于临时调试 / 容器部署）。
 * 路径统一解析为「项目根目录」下的绝对路径，避免受 cwd 影响。
 *
 * ## 配置来源优先级（从低到高）
 *
 *   config.json  ← 默认值
 *   环境变量     ← 临时调试 / 容器覆盖
 *   my_app API  ← 运行时拉取（启动时从 my_app 后端读取，统一管理）
 *
 * ## 为什么需要 my_app API 这一层
 *
 * WhatsApp 机器人的模型配置原本写死在 config.json 里，和 my_app 前端
 *「AI Model Settings」页面是两套独立的配置 —— 改了一处另一处不生效。
 * 加上 API 层后，用户在 my_app 页面改配置 → 机器人下次重启自动用新模型。
 *
 * @module config
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

// ─────────────────────────────────────────────────────────────────────────────
// 运行时对话配置（可被 my_app API 覆盖）
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 运行时对话配置。在 loadRuntimeConfig() 调用前，所有字段保持 config.json / 环境变量的默认值。
 * llm.js 的 chat() / openaiChat() / providerInfo() / validateProvider() 全部
 * 引用 RUNTIME_CONFIG 而非 CONFIG，确保 API 拉到的值实时生效。
 */
export const RUNTIME_CONFIG = {
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
};

/**
 * 把 my_app Settings 页存的 Open WebUI **UI 地址**规范化为其 **OpenAI 兼容 API base**。
 *
 * 为什么必须补：Settings 页的 `openwebui_base_url` 存的是网页地址
 * （如 `http://192.168.100.27:3000`）。bot 的 llm.js 只会拼 `/chat/completions`，
 * 若不补前缀就会打到 SPA 路由，返回 **405**：
 *   2026-10-12 实测 POST http://192.168.100.27:3000/chat/completions
 *   → HTTP 405 {"detail":"Method Not Allowed"}，与当日故障日志逐字一致。
 *
 * 补 **`/api/v1`** 而不是 `/api`，是 2026-10-12 实测定的：
 *   - `POST /api/v1/chat/completions` + Bearer <静态key>  → 200（OpenAI 兼容，返回 choices[]）
 *   - `POST /api/chat/completions`    + 同一把静态 key     → 403（那条路径只认 JWT/网页会话）
 * 所以机器人用静态 API Key 时必须走 /api/v1。
 *
 * 只对 Open WebUI 来源套用 —— WorkBuddy 本地代理（…/v1）与 custom（用户自填）
 * 本来就是完整 API base，补前缀会把它们拼坏。
 *
 * @param {string} url  UI 地址或已带 /api(/v1) 的地址
 * @returns {string}    OpenAI 兼容 API base（以 /api/v1 结尾）
 */
function toOpenWebUiApiBase(url) {
  const base = String(url || '').replace(/\/+$/, '');
  if (!base) return base;
  // 已显式带 API 路径就尊重用户写法，不再补（避免 /api/v1/api/v1）
  if (/\/api(\/v1)?$/.test(base)) return base;
  return `${base}/api/v1`;
}

/**
 * 从 my_app 后端拉取 AI 模型配置，用返回值覆盖 RUNTIME_CONFIG。
 * 拉取失败时**不抛** —— config.json / 环境变量已是有效兜底，直接用。
 *
 * @param {string} apiBase  my_app 后端地址，如 "http://127.0.0.1:7038"
 * @returns {Promise<boolean>} 是否成功拉到了 my_app 的配置
 */
export async function loadRuntimeConfig(apiBase) {
  const url = `${apiBase.replace(/\/+$/, '')}/api/ai-model-settings`;
  let controller;
  try {
    controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    const res = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' } });
    clearTimeout(timer);

    if (!res.ok) {
      console.warn(`[config] my_app AI配置返回 ${res.status}，使用 config.json 默认值`);
      return false;
    }

    const data = await res.json();
    const cfg = data.config || data;

    // provider 是用户实际选定的模式（local / openwebui / both），
    // 是**唯一真相**。local_enabled 是 UI 上"启用本地代理"的子开关，
    // 在 provider=openwebui 时与当前选择无关，不该影响 bot 的选择。
    //
    // my_app 返回的 provider 与"用什么模型"的关系：
    //   - "local"      → 用 local_model
    //   - "openwebui"  → 用 openwebui_model
    //   - "both"       → 优先 local_model，没有就回退到 openwebui_model
    const provider = (cfg.provider || 'both').toLowerCase();
    const hasLocalModel = cfg.local_model && cfg.local_model.trim();
    const hasOwuModel = cfg.openwebui_model && cfg.openwebui_model.trim();
    const hasCustomModel = cfg.custom_model && cfg.custom_model.trim();

    if (provider === 'openwebui') {
      if (hasOwuModel) {
        RUNTIME_CONFIG.chatModel = cfg.openwebui_model.trim();
        RUNTIME_CONFIG.chatBaseUrl = toOpenWebUiApiBase(cfg.openwebui_base_url);
        // Open WebUI 需要鉴权（Bearer）。key 从环境变量读 —— 不与 WorkBuddy/
        // Agnes 的占位值混淆，改配置只改 .env 里的 OPENWEBUI_API_KEY。
        RUNTIME_CONFIG.chatApiKeyEnv = 'OPENWEBUI_API_KEY';
      } else if (hasLocalModel) {
        console.warn(`[config] provider=openwebui 但 openwebui_model 为空，回退到 config.json 默认值`);
        return false;
      }
    } else if (provider === 'local') {
      if (hasLocalModel) {
        RUNTIME_CONFIG.chatModel = cfg.local_model.trim();
        RUNTIME_CONFIG.chatBaseUrl = (cfg.local_base_url || '').replace(/\/+$/, '');
      } else if (hasOwuModel) {
        RUNTIME_CONFIG.chatModel = cfg.openwebui_model.trim();
        RUNTIME_CONFIG.chatBaseUrl = toOpenWebUiApiBase(cfg.openwebui_base_url);
        RUNTIME_CONFIG.chatApiKeyEnv = 'OPENWEBUI_API_KEY';
      }
    } else if (provider === 'custom') {
      if (hasCustomModel) {
        RUNTIME_CONFIG.chatModel = cfg.custom_model.trim();
        RUNTIME_CONFIG.chatBaseUrl = (cfg.custom_base_url || '').replace(/\/+$/, '');
        RUNTIME_CONFIG.chatApiKey = cfg.custom_api_key || '';
      } else if (hasLocalModel) {
        console.warn(`[config] provider=custom 但 custom_model 为空，回退到 config.json 默认值`);
        return false;
      }
    } else {
      // "both"：本地优先，本地为空时回退到 OWU
      if (hasLocalModel) {
        RUNTIME_CONFIG.chatModel = cfg.local_model.trim();
        RUNTIME_CONFIG.chatBaseUrl = (cfg.local_base_url || '').replace(/\/+$/, '');
      } else if (hasOwuModel) {
        RUNTIME_CONFIG.chatModel = cfg.openwebui_model.trim();
        RUNTIME_CONFIG.chatBaseUrl = toOpenWebUiApiBase(cfg.openwebui_base_url);
        RUNTIME_CONFIG.chatApiKeyEnv = 'OPENWEBUI_API_KEY';
      }
    }

    // API Key 仍走环境变量 / config.json（不在 API 响应里传）
    // my_app 的 openwebui_email/password 用于别处，不影响 bot

    console.log(`[config] 已从 my_app 加载 AI 配置 → ${RUNTIME_CONFIG.chatModel} @ ${RUNTIME_CONFIG.chatBaseUrl}`);
    return true;
  } catch (err) {
    const msg = err.name === 'AbortError' ? '超时（5s）' : err.message;
    console.warn(`[config] 无法从 my_app 拉取 AI 配置（${msg}），使用 config.json 默认值`);
    return false;
  } finally {
    clearTimeout(controller?.timer);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 主 CONFIG（包含 RUNTIME_CONFIG 的对话字段作为动态别名）
// ─────────────────────────────────────────────────────────────────────────────

export const CONFIG = {
  ...raw,

  // —— 对话 provider：指向运行时配置（API 拉到的值实时生效）——
  get chatProvider() {
    return RUNTIME_CONFIG.chatProvider;
  },
  get chatModel() {
    return RUNTIME_CONFIG.chatModel;
  },
  get chatBaseUrl() {
    return RUNTIME_CONFIG.chatBaseUrl;
  },
  get chatApiKeyEnv() {
    return RUNTIME_CONFIG.chatApiKeyEnv;
  },
  get chatApiKey() {
    return RUNTIME_CONFIG.chatApiKey;
  },
  get chatTimeoutMs() {
    return RUNTIME_CONFIG.chatTimeoutMs;
  },
  get enableThinking() {
    return RUNTIME_CONFIG.enableThinking;
  },

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
  // parent-child 合并上限：同标题路径的相邻块合并回上下文的字符上限。
  parentMergeMaxChars: Number(process.env.PARENT_MERGE_MAX_CHARS ?? raw.parentMergeMaxChars ?? 1200),
  // MMR 同源限流：topK 内同一 source 最多保留几块。
  mmrMaxPerSource: Number(process.env.MMR_MAX_PER_SOURCE ?? raw.mmrMaxPerSource ?? 3),
  // BM25（词级字面）与向量的融合权重。置 0 即回退旧 bigram 混合。
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

  // 单号分析是否优先走 my_app 的 PG 实时接口（默认开；my_app 没起/失败时降级到
  // 本地 SQLite 副本 + eFlow 实时兜底）。与 ttStatsHttp 同构：
  // 环境变量 TT_ANALYSIS_HTTP=0 可临时关掉（排查「是不是 HTTP 通道把结论带偏了」）。
  ttAnalysisHttp:
    process.env.TT_ANALYSIS_HTTP != null
      ? !(process.env.TT_ANALYSIS_HTTP === '0' || process.env.TT_ANALYSIS_HTTP === 'false')
      : raw.ttAnalysisHttp !== false,

  // 按站点查实时告警（query_site_alarms）。默认开；环境变量可临时关（排查
  // 「是不是这条通道把问题带偏了」时有用）。超时同理由 env 覆盖。
  ttSiteAlarmFallback:
    process.env.TT_SITE_ALARM_FALLBACK != null
      ? !(process.env.TT_SITE_ALARM_FALLBACK === '0' || process.env.TT_SITE_ALARM_FALLBACK === 'false')
      : raw.ttSiteAlarmFallback !== false,
  ttSiteAlarmTimeoutMs: Number(process.env.TT_SITE_ALARM_TIMEOUT_MS ?? raw.ttSiteAlarmTimeoutMs ?? 180000),

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
    const n = raw.notify && typeof raw.notify === 'object' ? raw.notify : {};
    const fs = n.fileSend && typeof n.fileSend === 'object' ? n.fileSend : {};
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
    RUNTIME_CONFIG.chatProvider === 'ollama'
      ? `${RUNTIME_CONFIG.chatModel} @ ${CONFIG.ollamaUrl}`
      : `${RUNTIME_CONFIG.chatModel} @ ${RUNTIME_CONFIG.chatBaseUrl}`;
  return {
    对话模型: `[${RUNTIME_CONFIG.chatProvider}] ${chatTarget}`,
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
