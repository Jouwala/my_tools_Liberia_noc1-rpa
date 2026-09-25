/**
 * 统一答题入口 —— 群里、命令行、将来可能的其他入口都走这里。
 *
 * 存在的意义：分流逻辑（TT 单 vs 知识库）如果只写在 index.js 里，
 * 命令行测试工具就绕过了它，导致「测出来的行为」不等于「群里的行为」。
 * 抽到一处后，`npm run ask` 复现的就是线上路径。
 *
 * 两条通道：
 *   ① 消息里带 TT 单号 → 实时查 my_app 工单库。
 *      这类问题问的是「这一单现在什么情况」，答案在库里而不在语料里，
 *      塞进知识库只会变成过期快照。
 *   ② 其余 → 知识库向量检索。
 */
import { CONFIG } from './config.js';
import { detectLang } from './lang.js';
import { answer as ragAnswer } from './rag.js';
import { extractTtNo, analyzeTt } from './tt.js';

/**
 * @param {string} question  用户原始问题
 * @param {object} index     知识库索引（loadIndex() 的返回值）
 * @param {object} [opts]
 * @param {Function} [opts.onDebug]  检索诊断回调，仅知识库通道会触发
 * @param {Function} [opts.onRoute]  路由回调 ({channel, ttNo, ms, ok, lang})
 * @param {'zh'|'en'} [opts.lang]    回复语言；不传则按提问语言自动判定
 * @returns {Promise<{text:string, answered:boolean, channel:'tt'|'kb', stats?:object}>}
 */
export async function routeAnswer(question, index, { onDebug, onRoute, lang } = {}) {
  // 回复语言跟着提问语言走（英文提问 → 英文回复）。
  // 两条通道的机制不同，所以处理方式也不同：
  //   · TT 通道是脚本渲染的**模板**，没有模型参与 → 必须显式把语言传下去（--lang）；
  //   · 知识库通道是 **LLM 生成** → 靠 systemPrompt 的「用与提问相同的语言回答」
  //     加上消息序列**末尾**的 LANG_HINT 双保险（见 rag.js）。
  // 另外还有几句**不经过模型**的固定回复（未命中 / 排队 / 故障 / TT 失败），
  // 它们只能靠调用方按语言取文案（pickText）—— 改 prompt 管不到。
  const replyLang = lang || detectLang(question);
  const ttNo = extractTtNo(question);

  if (ttNo) {
    const t0 = Date.now();
    const r = await analyzeTt(ttNo, { lang: replyLang });
    const ms = Date.now() - t0;
    onRoute?.({ channel: 'tt', ttNo, ms, ok: r.ok, lang: replyLang });
    return {
      text: r.text,
      answered: r.ok,
      channel: 'tt',
      stats: { totalMs: ms, outputTokens: null },
    };
  }

  const result = await ragAnswer(question, index, { onDebug, lang: replyLang });
  onRoute?.({ channel: 'kb', lang: replyLang });
  return { ...result, channel: 'kb' };
}

/** 给日志/输出用的一行描述。 */
export function describeRoute(r) {
  if (r.channel === 'tt') {
    return `通道=TT单（实时查工单库${r.stats?.totalMs != null ? `，${r.stats.totalMs}ms` : ''}）`;
  }
  return `通道=知识库（${CONFIG.embedModel} 嵌入 + 混合检索）`;
}
