#!/usr/bin/env node
/**
 * 送达回执判定测试。
 *   node scripts/test-whatsapp-ack.mjs
 *
 * 只测 `src/ack.js` 的两个纯函数 —— 不连 WhatsApp、不发消息。
 *
 * ## 为什么值得单独一个测试
 *
 * 2026-10-28 实测：群里每条回复都在 30s 后被判「未送达」，连用户明明收到
 * 并正常追问了的回答也不例外。根因是 Baileys 对群聊**不发** `messages.update`，
 * 而是发 `message-receipt.update`，且载荷里**没有 status 字段**，只有时间戳。
 *
 * 这种错在生产上的表现只有「报表里全是未送达」，看不出是哪条通道漏了；
 * 所以把两条通道的载荷形状都固化成断言 —— 一旦哪天升级 baileys 改了字段名，
 * 这里会先红，而不是等群里再出一次「答案发了但没人看见」。
 */
import { ackIdFromUpdate, ackIdFromReceipt, ACK_DONE } from '../src/ack.js';

let pass = 0;
let fail = 0;
function check(cond, label, detail = '') {
  if (cond) {
    pass++;
    console.log(`  ✓ ${label}`);
  } else {
    fail++;
    console.log(`  ✗ ${label}${detail ? `\n      ${detail}` : ''}`);
  }
}

const ID = '3EB07A336D6BC0B9D749F0';

// ── 私聊通道：messages.update ───────────────────────────────────────────
console.log('\n[1] 私聊回执（messages.update，带 status 枚举）');

check(ACK_DONE.has(2) && ACK_DONE.has(3) && ACK_DONE.has(4) && ACK_DONE.has(5),
  'ACK_DONE 覆盖 SERVER_ACK(2)/DELIVERY_ACK(3)/READ(4)/PLAYED(5)');
check(!ACK_DONE.has(1), 'PENDING(1) 不算送达');

check(
  ackIdFromUpdate({ key: { id: ID, fromMe: true }, update: { status: 3 } }) === ID,
  'DELIVERY_ACK → 确认送达'
);
check(
  ackIdFromUpdate({ key: { id: ID, fromMe: true }, update: { status: 2 } }) === ID,
  'SERVER_ACK → 确认送达（服务端已受理）'
);
check(
  ackIdFromUpdate({ key: { id: ID, fromMe: true }, update: { status: 4 } }) === ID,
  'READ → 确认送达'
);
check(
  ackIdFromUpdate({ key: { id: ID, fromMe: true }, update: { status: 1 } }) === null,
  'PENDING → 还没确认（不能提前 commit）'
);
check(
  ackIdFromUpdate({ key: { id: ID, fromMe: false }, update: { status: 3 } }) === null,
  'fromMe=false 的 update → 忽略（那是别人消息的状态）'
);
check(ackIdFromUpdate({ key: { id: ID, fromMe: true } }) === null, '没有 update.status → 忽略');
check(ackIdFromUpdate({ key: { fromMe: true }, update: { status: 3 } }) === null, '没有 key.id → 忽略');
check(ackIdFromUpdate(null) === null, 'null 载荷不抛异常');
check(ackIdFromUpdate(undefined) === null, 'undefined 载荷不抛异常');

// ── 群聊通道：message-receipt.update ───────────────────────────────────
console.log('\n[2] 群聊回执（message-receipt.update，只有时间戳，没有 status）');

check(
  ackIdFromReceipt({
    key: { id: ID, remoteJid: '120363428304591700@g.us', fromMe: true, participant: '112176710811648@lid' },
    receipt: { userJid: '112176710811648@lid', receiptTimestamp: 1761642680 },
  }) === ID,
  'receiptTimestamp（已投递）→ 确认送达  ← 2026-10-28 修的就是这一条'
);
check(
  ackIdFromReceipt({
    key: { id: ID, remoteJid: '120363428304591700@g.us', fromMe: true },
    receipt: { userJid: '112176710811648@lid', readTimestamp: 1761642699 },
  }) === ID,
  'readTimestamp（已读）→ 确认送达（已读必然已投递）'
);
check(
  ackIdFromReceipt({
    key: { id: ID, remoteJid: '120363428304591700@g.us' },
    receipt: { userJid: 'x@lid' },
  }) === null,
  '回执里两个时间戳都没有 → 忽略（不是投递事件）'
);
check(
  ackIdFromReceipt({ key: { id: ID }, receipt: { receiptTimestamp: 0 } }) === ID,
  'receiptTimestamp=0 也算送达（用 != null 判，不能用真值判）'
);
check(ackIdFromReceipt({ key: {}, receipt: { receiptTimestamp: 1 } }) === null, '没有 key.id → 忽略');
check(ackIdFromReceipt({}) === null, '空对象不抛异常');
check(ackIdFromReceipt(null) === null, 'null 载荷不抛异常');

// ── 交叉校验：群回执不能靠 status 判 ────────────────────────────────────
console.log('\n[3] 两条通道不能混用（回归护栏）');

check(
  ackIdFromUpdate({ key: { id: ID, fromMe: true }, receipt: { receiptTimestamp: 1 } }) === null,
  '群回执形状喂给 messages.update 判定 → null（这正是原先的 bug：群回执永远匹配不上）'
);
check(
  ackIdFromReceipt({ key: { id: ID, fromMe: true }, update: { status: 3 } }) === null,
  '私聊形状喂给 receipt 判定 → null（两条通道各自独立）'
);

console.log(`\n${fail === 0 ? '✓ 全部通过' : '✗ 有失败'}：${pass} 通过 / ${fail} 失败\n`);
process.exit(fail === 0 ? 0 : 1);
