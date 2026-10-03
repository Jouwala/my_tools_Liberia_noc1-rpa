/**
 * 会话记忆：按「会话 + 提问人」缓存最近几轮问答。
 *
 * 为什么按 sender 而不是只按群：群里多人同时问不同的事，若共用一份上下文，
 * A 的追问会被 B 上一轮的答案带偏。拆到人这一级，代价是「引用别人的提问
 * 再追问」接不上——那种场景由 replyQuote 的原文里通常还带着单号/术语兜住。
 *
 * 为什么只放在内存里、不落盘：重启即清空是可接受的（同事会重新问一遍），
 * 而落盘要处理跨天污染、隐私残留，复杂度换来的收益很小。
 */
import { CONFIG } from './config.js';

/** 存储：key -> { updatedAt, turns: [{ q, a }] } */
const store = new Map();

/** 单条存进记忆的上限字数：答案再长也不值得整段留在上下文里。 */
const TURN_TEXT_CAP = 400;

/** 记忆键。私聊时 participant 可能缺失，回退到 chatJid。 */
export function memoryKey(chatJid, sender) {
  const who = String(sender || chatJid || '').split('@')[0];
  return `${chatJid || 'unknown'}|${who}`;
}

export function clearMemory(key) {
  if (key) store.delete(key);
  else store.clear();
  return store.size;
}

/**
 * 取该会话最近的问答轮次。超时的整条会话视为不存在（返回空数组）。
 * 读取时顺手判过期，不需要后台定时器。
 */
export function getTurns(key) {
  if (!CONFIG.memoryEnabled || !key) return [];
  const rec = store.get(key);
  if (!rec) return [];
  if (Date.now() - rec.updatedAt > CONFIG.memoryTtlMs) {
    store.delete(key);
    return [];
  }
  return rec.turns.slice(-CONFIG.memoryMaxTurns);
}

/** 记录一轮问答。只存成功作答的轮次——兜底文案进上下文只会教模型说「查不到」。 */
export function pushTurn(key, question, answer) {
  if (!CONFIG.memoryEnabled || !key || !answer) return;
  const cap = (s) => String(s || '').trim().slice(0, TURN_TEXT_CAP);
  const rec = store.get(key) || { updatedAt: 0, turns: [] };
  rec.turns.push({ q: cap(question), a: cap(answer) });
  if (rec.turns.length > CONFIG.memoryMaxTurns) {
    rec.turns.splice(0, rec.turns.length - CONFIG.memoryMaxTurns);
  }
  rec.updatedAt = Date.now();
  store.set(key, rec);

  // 会话数上限：群很多时避免这个 Map 无限增长。
  // 淘汰最久未使用的（getTurns 里已删过期的，这里兜住活跃但超量的那批）。
  const maxChats = CONFIG.memoryMaxChats;
  if (maxChats > 0 && store.size > maxChats) {
    let oldestKey = null;
    let oldest = Infinity;
    for (const [k, v] of store) {
      if (v.updatedAt < oldest) {
        oldest = v.updatedAt;
        oldestKey = k;
      }
    }
    if (oldestKey) store.delete(oldestKey);
  }
}

/** 诊断/单测用 */
export function memoryStats() {
  return {
    chats: store.size,
    enabled: !!CONFIG.memoryEnabled,
    turns: [...store.values()].reduce((n, r) => n + r.turns.length, 0),
  };
}
