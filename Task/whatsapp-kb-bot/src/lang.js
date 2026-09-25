/**
 * 提问语言判定 —— 让回复语言跟着提问语言走。
 *
 * 为什么需要：群里中英文混用（导入的 iMind 官方手册本身就是英文，
 * 现场同事也常用英文），英文提问却收到中文回复会很难用。
 *
 * 判定规则故意做得**朴素**：出现 CJK 汉字就算中文，否则算英文。
 *   · 这个语料只有中英两种，上语言检测库（或让模型判）都是过度设计；
 *   · 这一步是**同步、零成本**的，不额外占一次模型调用。
 *
 * ⚠️ 只把**汉字**当中文信号，不把中文标点算进去 ——
 * 有人用中文输入法打英文句子（结尾是 `？`），
 * 若把全角标点也算作中文，就会被误判。
 */
const CJK = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/;

/** 判定不出语言时的回退值（也是 bot 的母语）。 */
export const DEFAULT_LANG = 'zh';

/** @returns {'zh'|'en'} */
export function detectLang(text) {
  const s = String(text ?? '').trim();
  // 空提问（只 @ 了机器人、没写内容）没有语言信号，
  // 回退默认值 —— 否则 `@bot` 会因为「不含汉字」被判成英文。
  if (!s) return DEFAULT_LANG;
  return CJK.test(s) ? 'zh' : 'en';
}

/**
 * 固定文案的按语言取用。
 *
 * 为什么需要：有几句话**不经过模型**（知识库未命中 / 程序故障 / 排队已满 /
 * TT 查询失败）。它们既不受 systemPrompt 约束，也不会被 LANG_HINT 影响 ——
 * 只改 prompt 的话，英文提问仍会收到中文兜底。
 *
 * 英文缺失时回退中文：宁可回中文，也不能因为漏配一句而发出空消息。
 *
 * @param {'zh'|'en'} lang
 * @param {string} zh 中文文案
 * @param {string} [en] 英文文案
 */
export function pickText(lang, zh, en) {
  return lang === 'en' && en ? en : zh;
}
