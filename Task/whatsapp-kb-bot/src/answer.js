/**
 * 统一答题入口 —— 群里、命令行、将来可能的其他入口都走这里。
 *
 * 存在的意义：分流逻辑（TT 单 vs 知识库）如果只写在 index.js 里，
 * 命令行测试工具就绕过了它，导致「测出来的行为」不等于「群里的行为」。
 * 抽到一处后，`npm run ask` 复现的就是线上路径。
 *
 * 三条通道（由 src/tools.js 的工具路由决定走哪条）：
 *   ① 消息里带 TT 单号 → 实时查 my_app 工单库。
 *      这类问题问的是「这一单现在什么情况」，答案在库里而不在语料里，
 *      塞进知识库只会变成过期快照。
 *   ② 区间统计（今天几个 P1 等）→ 工单聚合查询（src/ttquery.js）。
 *      答案同样是数据，不是语料。这条通道 2026-10-06 新增 ——
 *      此前这类问题被当成知识问题塞进向量检索，模型只能答「资料里没有实际工单数据」。
 *   ③ 其余 → 知识库向量检索。
 */
import { CONFIG } from './config.js';
import { detectLang } from './lang.js';
import { routeWithTools } from './tools.js';

/**
 * @param {string} question  用户原始问题
 * @param {object} index     知识库索引（loadIndex() 的返回值）
 * @param {object} [opts]
 * @param {Function} [opts.onDebug]  检索诊断回调，仅知识库通道会触发
 * @param {Function} [opts.onRoute]  路由回调 ({channel, ttNo, ms, ok, lang})
 * @param {Function} [opts.onRetry]  工单通道失败即将自动重试时的回调（可发垫话）
 * @param {Function} [opts.onLive]   本地库查不到、即将回 eFlow 实时查时的回调（可发垫话）
 * @param {'zh'|'en'} [opts.lang]    回复语言；不传则按提问语言自动判定
 * @param {Array<{q:string,a:string}>} [opts.history] 最近几轮问答，用于解析追问
 * @returns {Promise<{text:string, answered:boolean, channel:'tt'|'kb', stats?:object}>}
 */
export async function routeAnswer(
  question,
  index,
  { onDebug, onRoute, onRetry, onLive, lang, history, webHint } = {}
) {
  // 回复语言跟着提问语言走（英文提问 → 英文回复）。
  // 两条通道的机制不同，所以处理方式也不同：
  //   · TT 通道是脚本渲染的**模板**，没有模型参与 → 必须显式把语言传下去（--lang）；
  //   · 知识库通道是 **LLM 生成** → 靠 systemPrompt 的「用与提问相同的语言回答」
  //     加上消息序列**末尾**的 LANG_HINT 双保险（见 rag.js）。
  // 另外还有几句**不经过模型**的固定回复（未命中 / 排队 / 故障 / TT 失败），
  // 它们只能靠调用方按语言取文案（pickText）—— 改 prompt 管不到。
  const replyLang = lang || detectLang(question);
  const t0 = Date.now();

  const result = await routeWithTools(question, index, {
    lang: replyLang,
    onDebug,
    onRetry,
    onLive,
    history,
    // 网页挂件传 false：查不到时不要附「去网页版问」的尾巴（见 src/http-server.js）
    webHint,
  });

  const ms = Date.now() - t0;
  onRoute?.({
    channel: result.channel,
    tool: result.tool,
    via: result.via,
    ms,
    ok: result.answered,
    lang: replyLang,
  });
  return { ...result, stats: { ...(result.stats || {}), totalMs: ms } };
}

/** 给日志/输出用的一行描述。 */
export function describeRoute(r) {
  const ms = r.stats?.totalMs != null ? `，${r.stats.totalMs}ms` : '';
  const via = r.via ? `｜路由=${r.via === 'rule' ? '规则' : '模型'}` : '';
  const tool = r.tool ? `｜工具=${r.tool}` : '';

  if (r.channel === 'tt') {
    const multi = r.stats?.count > 1 ? `，${r.stats.count} 个单` : '';
    return `通道=TT单（实时查工单库${multi}${ms}）${via}${tool}`;
  }
  if (r.channel === 'stats') {
    const src = r.stats?.source === 'http' ? 'my_app HTTP（PG 实时）' : '本地 SQLite 副本';
    return `通道=工单统计（${src}${ms}）${via}${tool}`;
  }
  if (r.channel === 'lookup') {
    return `通道=查表（data/lookups.json，不经 LLM${ms}）${via}${tool}`;
  }
  if (r.channel === 'eflowrule') {
    // eFlow 规则配置（压缩/建单）。与 lookup 分开记：
    // 「本地快照没有 → 升级到 eFlow 规则表」是排障时要能一眼看出来的路径。
    const esc = r.stats?.escalated === 'eflow' ? '，本地快照未命中已升级' : '';
    const n = r.stats?.rulesChecked != null ? `，核对 ${r.stats.rulesChecked} 条关联规则` : '';
    return `通道=eFlow规则配置（eflow_*_rules.xlsx${n}${esc}${ms}）${via}${tool}`;
  }
  if (r.channel === 'sitealarm') {
    // 2026-10-24 补：此前漏了这一支，站点告警通道的日志会显示成
    // 「通道=知识库（bge-m3…）」—— 排障时会被引到错误的通道上。
    return `通道=站点告警（eFlow 实时活动告警${ms}）${via}${tool}`;
  }
  if (r.channel === 'vmaxcca') {
    return `通道=VMAX CCA（my_app HTTP 实时${ms}）${via}${tool}`;
  }
  if (r.channel === 'warehouse') {
    // 库房通道：单据统计走 my_app HTTP，分仓库存走本地 SQLite 快照。
    const src = r.stats?.source === 'http' ? 'my_app HTTP（实时）' : '本地 SQLite 副本';
    return `通道=库房（${src}${ms}）${via}${tool}`;
  }
  return `通道=知识库（${CONFIG.embedModel} 嵌入 + 混合检索${ms}）${via}${tool}`;
}
