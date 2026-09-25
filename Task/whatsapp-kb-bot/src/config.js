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

  authDirAbs: abs(process.env.AUTH_DIR || 'data/auth'),
  logDirAbs: abs('data/logs'),

  // 数值型环境变量覆盖
  topK: Number(process.env.TOP_K ?? raw.topK),
  minAbs: Number(process.env.MIN_ABS ?? raw.minAbs),
  minGap: Number(process.env.MIN_GAP ?? raw.minGap),
  // 检索权重：以前只靠 rag.js 里的 `?? 默认值` 兜底，改配置能生效但没法用环境变量临时试。
  // 统一到这一层，调参时不用改文件。
  semanticWeight: Number(process.env.SEMANTIC_WEIGHT ?? raw.semanticWeight ?? 0.78),
  lexicalWeight: Number(process.env.LEXICAL_WEIGHT ?? raw.lexicalWeight ?? 0.22),
  idBonus: Number(process.env.ID_BONUS ?? raw.idBonus ?? 0.15),
  cooldownMs: Number(process.env.COOLDOWN_MS ?? raw.cooldownMs),
  maxTokens: Number(process.env.MAX_TOKENS ?? raw.maxTokens ?? 512),
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
  };
}
