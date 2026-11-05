/**
 * NL2SQL 长尾兜底 —— 「数据库里有数据，但机器人没有对应的专用工具」时走这条。
 *
 * ## 定位
 *
 * 精确通道（src/datadomains.js）覆盖高频域：电源 / 历史告警 / WO / 可用率。
 * 但库里还有 74 张可见表（app schema 78 张减掉备份表），运维会问的问题远不止
 * 这四类：「南西区哪些站最近有丢包」「TOP10 掉线站」「这个月 P1 工单按根因怎么分布」。
 * 为每个问题加工具不现实 —— 这条通道就是为此存在的。
 *
 * ## 复用现成的管道，不重造
 *
 * my_app 已有完整的 NL2SQL 实现（`services/nl2sql_service.py`），带三重护栏：
 *
 *   ① 表/列白名单由服务端提供，模型不猜（`build_schema_context` 取真实列元数据）；
 *   ② `sql_guard.validate_sql()` 强制校验 —— 只允许 SELECT/WITH、禁多语句、
 *      禁 schema 前缀、禁未知表；
 *   ③ `execute_readonly()` 只读执行，LIMIT 一律收敛到 5 万行。
 *
 * ⚠️ 本模块**不直接连数据库**，只调 my_app 的 `/api/data-agent/ask` ——
 * 护栏必须留在服务端，bot 侧再抄一遍只会出现两份规则不一致。
 *
 * ## 模型通道：OWU 优先，Ollama 兜底
 *
 *   ① OWU（192.168.100.27:8443，mimo-v2.6-flash）—— 与群机器人同一模型，
 *      质量一致。内网私有 CA，**由 my_app 侧**用 NL2SQL_CA_FILE 处理。
 *   ② Ollama（192.168.100.27:11434，qwen2.5:7b-instruct）—— 明文 HTTP，
 *      无证书问题；OWU 挂了还能查。
 *
 * ⚠️ `base_url` 必须是**完整的 chat/completions URL**：my_app 的
 * `nl2sql_service._call_provider` 直接拿 base_url 当最终地址用，不会拼接路径。
 *
 * ## 延迟
 *
 * `ask()` 只跑**一次** LLM（生成 SQL）+ 一次 SQL 执行，不是两次 ——
 * 结果解读不在服务端做。所以实测在 10 秒上下，不是 60 秒。
 */
import { CONFIG } from './config.js';
import { resolveApiKey } from './llm.js';

/** HTTP 超时。含一次 LLM + 一次 SQL 执行；超时即降级到 Ollama 通道。 */
const HTTP_TIMEOUT_MS = Number(process.env.NL2SQL_TIMEOUT_MS || 90000);

/** Ollama 兜底用的模型（.27 那台上确实存在，2026-11-03 实测）。 */
const FALLBACK_MODEL = process.env.NL2SQL_FALLBACK_MODEL || 'qwen2.5:7b-instruct';

/** 渲染最多列出多少行 —— 群里刷屏比少列几行更糟。 */
const MAX_ROWS_SHOWN = Number(process.env.NL2SQL_MAX_ROWS || 15);

/** my_app 后端基址（去掉尾部斜杠）。 */
function apiBase() {
  const base = String(CONFIG.myAppApiBase || '').replace(/\/+$/, '');
  if (!base) throw new Error('未配置 myAppApiBase');
  return base;
}

/**
 * 拼出 provider 的完整 chat/completions URL。
 *
 * ⚠️ my_app 侧 `url = base_url or defaults.get(provider)` —— **不拼路径**。
 * 传 `https://host/api/v1` 会 404，必须传完整的 `.../api/v1/chat/completions`。
 */
function chatUrl(base, suffix = '/chat/completions') {
  const b = String(base || '').replace(/\/+$/, '');
  if (!b) return '';
  if (b.endsWith('/chat/completions')) return b;
  return b + suffix;
}

/** 通道定义：按优先级排列。 */
function channels() {
  const list = [];
  const key = (() => {
    try {
      return resolveApiKey()?.key || '';
    } catch {
      return '';
    }
  })();

  const owuBase = CONFIG.chatBaseUrl || '';
  if (owuBase) {
    list.push({
      name: 'OWU',
      provider: 'openai',
      api_key: key || 'ollama',   // OWU 需要真 key；取不到就退化占位，让服务端先试
      model: CONFIG.chatModel || 'mimo-v2.6-flash',
      base_url: chatUrl(owuBase),
    });
  }

  const ollamaBase = CONFIG.ollamaUrl || '';
  if (ollamaBase) {
    list.push({
      name: 'Ollama',
      provider: 'openai',
      // Ollama 不校验 key，但 my_app 侧要求 api_key 非空，否则直接抛错。
      api_key: 'ollama-local',
      model: FALLBACK_MODEL,
      base_url: chatUrl(ollamaBase, '/v1/chat/completions'),
    });
  }
  return list;
}

/**
 * 调 my_app 的 NL2SQL 接口。
 * @param {string} question 自然语言问题
 * @param {object} ch 通道定义
 */
async function askVia(question, ch) {
  const url = new URL('/api/data-agent/ask', apiBase());
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), HTTP_TIMEOUT_MS);
  let res;
  try {
    res = await fetch(url, {
      method: 'POST',
      signal: ctrl.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        provider: ch.provider,
        api_key: ch.api_key,
        model: ch.model,
        base_url: ch.base_url,
        run: true,
      }),
    });
  } catch (err) {
    if (err.name === 'AbortError') throw new Error(`超时（${HTTP_TIMEOUT_MS}ms）`);
    throw new Error(`连不上 my_app：${err.cause?.code || err.message}`);
  } finally {
    clearTimeout(timer);
  }

  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(`my_app 返回非 JSON：${text.slice(0, 120)}`);
  }
  if (!res.ok) {
    // ⚠️ my_app 的 data_agent 端点返回的是 `{"error": "..."}`，
    // 而不是 FastAPI 默认的 `{"detail": "..."}` —— 只读 detail 会把真实原因
    // 吞成一句「my_app 返回 400」，排查时完全看不到真正的原因。
    const msg = data?.error || data?.detail || `my_app 返回 ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

/* -------------------------------- 文案 -------------------------------- */

const T = {
  zh: {
    header: '数据库查询结果',
    // ⚠️ 空结果**不等于**「没有这条数据」—— 也可能是过滤条件写窄了。
    // 2026-11-04 真实故障：模型把系统名 `my_app` 当数据值过滤（`ILIKE '%my_app%'`），
    // 库里 3 万多行被它自己滤成 0 行，机器人却回答「没有匹配到任何记录」——
    // 把「查错了」包装成了「确定没有」。所以措辞必须留出这一层余地。
    empty:
      '查询执行成功，但**没有匹配到任何记录**。\n\n' +
      '（可能是过滤条件过窄，也可能是确实没有符合条件的数据 —— ' +
      '可以让我换个条件再查一次。）',
    failed: '这条查询没能跑通',
    sql: '执行的 SQL',
    via: (name) => `取数通道：${name}`,
    more: (shown, total) => `…… 另有 ${total - shown} 行未列出`,
    noTool:
      '这个问题超出了我的专用查询范围（站点属性 / 电源 / 历史告警 / WO / 可用率 / TT）。\n' +
      '我已经尝试直接查库，但没能生成可执行的查询。',
    error: (detail) => `查库时出错了${detail ? `：${detail}` : ''}。请稍后再试，或换个问法。`,
  },
  en: {
    header: 'Database query result',
    // Same caveat as the Chinese text above: an empty result may mean the
    // filter was too narrow, not that the data does not exist.
    empty:
      'The query ran successfully but **matched no rows**.\n\n' +
      '(The filter may have been too narrow, or there may simply be no matching ' +
      'data - ask me to retry with different conditions.)',
    failed: 'This query could not be executed',
    sql: 'Executed SQL',
    via: (name) => `Channel: ${name}`,
    more: (shown, total) => `... and ${total - shown} more rows`,
    noTool:
      'This question is outside my dedicated lookup tools (site attributes / power / ' +
      'historical alarms / WO / availability / tickets).\nI tried querying the database ' +
      'directly but could not produce an executable query.',
    error: (detail) => `Database query failed${detail ? `: ${detail}` : ''}. Please try again later.`,
  },
};

/** snake_case → 可读标签（模型生成的 SQL 列名是任意的，只能做通用美化）。 */
function prettyCol(name) {
  return String(name || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** 值 → 展示文本。对象/数组转 JSON 摘要，别把整行糊在回复里。 */
function cell(v) {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'object') {
    const s = JSON.stringify(v);
    return s.length > 60 ? `${s.slice(0, 57)}...` : s;
  }
  const s = String(v);
  return s.length > 120 ? `${s.slice(0, 117)}...` : s;
}

/**
 * 渲染 NL2SQL 结果。
 *
 * @param {object} d        my_app 返回
 * @param {'zh'|'en'} lang
 * @param {string} via      实际用的通道名
 */
export function renderDataQuery(d, lang = 'zh', via = '') {
  const t = T[lang] || T.zh;

  if (!d || typeof d !== 'object') {
    return t.error('接口无返回');
  }
  // my_app 用 detail 字段报错（HTTPException），成功时是 200 + 正常结构。
  if (d.detail && !d.sql && !d.columns) {
    return t.error(String(d.detail));
  }

  const columns = Array.isArray(d.columns) ? d.columns : [];
  const rows = Array.isArray(d.rows) ? d.rows : [];

  if (!columns.length || !rows.length) {
    const lines = [`## ${t.header}`, ''];
    lines.push(t.empty);
    if (d.executed_sql) {
      lines.push('');
      lines.push(`\`${String(d.executed_sql).trim()}\``);
    }
    return lines.join('\n');
  }

  const lines = [`## ${t.header}`, ''];
  for (const r of rows.slice(0, MAX_ROWS_SHOWN)) {
    lines.push(`- ${prettyCol(columns[0])}：${cell(r[columns[0]])}`);
    for (let i = 1; i < columns.length; i++) {
      lines.push(`  ${prettyCol(columns[i])}：${cell(r[columns[i]])}`);
    }
    lines.push('');
  }
  const total = Number(d.row_count || rows.length);
  if (total > MAX_ROWS_SHOWN) {
    lines.push(t.more(MAX_ROWS_SHOWN, total));
    lines.push('');
  }

  if (d.executed_sql) {
    lines.push(`\`${String(d.executed_sql).trim()}\``);
    lines.push('');
  }
  if (via) {
    lines.push(t.via(via));
  }
  return lines.join('\n');
}

/* -------------------------------- 主入口 -------------------------------- */

/**
 * 用 NL2SQL 查库 —— OWU 优先，失败降级 Ollama。
 *
 * @param {string} question 自然语言问题（要能被模型翻译成 SQL）
 * @returns {Promise<{ok:boolean, data?:object, error?:string, via?:string, tried?:string[]}>}
 */
export async function queryData(question) {
  const q = String(question || '').trim();
  if (!q) return { ok: false, error: '问题不能为空' };

  const chs = channels();
  if (!chs.length) {
    return { ok: false, error: '未配置任何模型通道（chatBaseUrl / ollamaUrl 均为空）' };
  }

  const tried = [];
  let lastErr = '';
  for (const ch of chs) {
    tried.push(ch.name);
    try {
      const data = await askVia(q, ch);
      if (data && (data.sql || data.columns)) {
        return { ok: true, data, via: ch.name, tried };
      }
      lastErr = data?.detail || '接口未返回 SQL';
    } catch (err) {
      lastErr = err.message;
      if (process.env.DEBUG_TOOLS === '1') {
        console.error(`[工具] NL2SQL ${ch.name} 失败：${err.message}`);
      }
    }
  }
  return { ok: false, error: lastErr || '所有通道都失败', tried };
}

/** 供提示层引用：告诉模型这条通道是干什么的、什么时候用。 */
export const NL2SQL_HINT =
  'query_data —— 通用数据库查询（NL2SQL）。仅在专用工具都不适用时使用：' +
  '专用工具覆盖站点属性、电源、历史告警、WO、站点可用率、TT 统计与单号分析、' +
  '实时告警、告警码规则、库存。问题涉及其他数据（KPI、丢包、传输光路、电池、拓扑、' +
  '任务队列等）时才用它。**它慢（十秒级）**，优先考虑专用工具。';
