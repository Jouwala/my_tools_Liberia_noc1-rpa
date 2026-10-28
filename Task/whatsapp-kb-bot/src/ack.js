/**
 * 送达回执的判定 —— 纯函数，不碰 socket、不碰日志。
 *
 * ## 为什么单独成一个模块（2026-10-28）
 *
 * Baileys 的送达回执**有两条事件通道**，载荷形状完全不同：
 *
 *   · 私聊 → `messages.update`
 *       [{ key: { id, fromMe }, update: { status: <WAMessageStatus> } }]
 *
 *   · 群聊 / 状态广播 → `message-receipt.update`
 *       [{ key: { id, fromMe, participant }, receipt: { userJid, receiptTimestamp } }]
 *       （或 `readTimestamp`。**没有 `status` 字段**）
 *
 * 分支逻辑写在 `node_modules/baileys/lib/Socket/messages-recv.js` 的
 * `handleReceipt` 里：`if (isJidGroup(remoteJid) || isJidStatusBroadcast(remoteJid))
 * { … emit('message-receipt.update') } else { … emit('messages.update') }`。
 *
 * 本项目原先只订阅了 `messages.update`，于是群里的每条回复都在 30s 后被判
 * 「未送达」：日志刷 `[未送达]`、`qa_log.ack` 恒为 undelivered、并且连带
 * `abortAck` 把「写会话历史 / 记 answered=1」一并撤销 —— 那些用户明明收到
 * 并正常追问了的回答，全被当成没送到。
 *
 * 判定逻辑抽在这里，是为了能脱离 WhatsApp 连接做单元测试
 * （见 `scripts/test-whatsapp-ack.mjs`）：错一个字段名就永远收不到回执，
 * 而这种错在生产上只表现为「报表里全是未送达」，很难归因。
 */

/** 视为「已送达」的 WAMessageStatus 取值（私聊通道）。 */
export const ACK_DONE = new Set([
  2, // SERVER_ACK
  3, // DELIVERY_ACK
  4, // READ
  5, // PLAYED
]);

/**
 * 从一条 `messages.update` 里取被确认的 msgId；不是「已送达」则返回 null。
 * 只认 fromMe 的 update —— 别人的消息与我们无关。
 */
export function ackIdFromUpdate(u) {
  const id = u?.key?.id;
  if (!id || !u.key?.fromMe) return null;
  const status = u.update?.status;
  if (status == null || !ACK_DONE.has(status)) return null;
  return id;
}

/**
 * 从一条 `message-receipt.update` 里取被确认的 msgId；不是「已送达」则返回 null。
 *
 * 群聊回执没有 status 枚举，只有时间戳：
 *   · `receiptTimestamp` → 已投递（对应私聊的 DELIVERY_ACK）
 *   · `readTimestamp`    → 已读（已读必然已投递）
 * 两者任一存在即算送达。`played` 之类的事件不在此列。
 *
 * 不判 fromMe：回执按 msgId 与待确认表对账，别人的消息 id 根本不在表里。
 * （而且群回执的 fromMe 是 Baileys 用 `!attrs.recipient` 推出来的，
 *  rely 它反而多一处可能失效的条件。）
 */
export function ackIdFromReceipt(r) {
  const id = r?.key?.id;
  if (!id) return null;
  const rc = r.receipt || {};
  if (rc.receiptTimestamp != null || rc.readTimestamp != null) return id;
  return null;
}
