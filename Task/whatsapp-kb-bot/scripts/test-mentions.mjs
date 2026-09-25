#!/usr/bin/env node
/**
 * @提及识别逻辑的单元测试。
 *   node scripts/test-mentions.mjs
 *
 * 覆盖真实环境里最容易出错的几种 JID 形态：
 * 手机号 JID、LID、带设备后缀、群内提及他人、引用回复。
 */
import { selfIdentifiers, jidForms, extractText, detectTrigger, stripMentions, isAllowedChat } from '../src/mentions.js';

let pass = 0;
let fail = 0;

function eq(actual, expected, label) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) {
    pass++;
    console.log(`  ✓ ${label}`);
  } else {
    fail++;
    console.log(`  ✗ ${label}\n      期望 ${e}\n      实际 ${a}`);
  }
}

// 模拟机器人：手机号 8613800138000，设备号 5，LID 为 99887766
const sock = {
  user: {
    id: '8613800138000:5@s.whatsapp.net',
    lid: '99887766@lid',
  },
};
const self = selfIdentifiers(sock);

console.log('\n[1] 自身标识收集');
console.log(`    收集到：${[...self].join(' | ')}`);
eq(self.has('8613800138000@s.whatsapp.net'), true, '含归一化后的手机号 JID');
eq(self.has('8613800138000'), true, '含纯号码形式');
eq(self.has('99887766@lid'), true, '含 LID');

console.log('\n[1b] 换号后的真实故障：sock.user 没有 LID，只有凭据里有');
console.log('     （2026-09-15 线上现场：换号到 +231 77 699 0822 后，群里 @机器人 无响应）');

// 复现现场：sock.user 上只有手机号，凭据里存着 LID。
// 旧代码只读 sock.user，导致 LID 形态的 @提及 全部静默失效。
const sockNoLid = { user: { id: '231776990822:1@s.whatsapp.net' } };
const credsMe = { id: '231776990822:1@s.whatsapp.net', lid: '91019685171349:1@lid' };
const lidMention = {
  extendedTextMessage: { text: '@91019685171349 你好', contextInfo: { mentionedJid: ['91019685171349@lid'] } },
};

const selfNoCreds = selfIdentifiers(sockNoLid);
eq(selfNoCreds.has('91019685171349@lid'), false, '只传 sock → LID 缺失（复现故障）');
eq(
  detectTrigger(lidMention, selfNoCreds),
  { triggered: false, via: null },
  '只传 sock 时，LID 形态的 @ 不触发（这就是当时的现场）'
);

const selfWithCreds = selfIdentifiers(sockNoLid, credsMe);
eq(selfWithCreds.has('91019685171349@lid'), true, '传入 creds.me → 含归一化 LID');
eq(selfWithCreds.has('91019685171349'), true, '传入 creds.me → 含 LID 纯数字形式');
eq(
  detectTrigger(lidMention, selfWithCreds),
  { triggered: true, via: 'mention' },
  '传入 creds.me 后，LID 形态的 @ 正常触发（修复生效）'
);
eq(
  detectTrigger(
    { extendedTextMessage: { text: 'hi', contextInfo: { mentionedJid: ['231776990822@s.whatsapp.net'] } } },
    selfWithCreds
  ),
  { triggered: true, via: 'mention' },
  '同一份标识里，手机号形态仍然照常触发（没有顾此失彼）'
);

console.log('\n[2] 群内 @机器人（手机号 JID）');
eq(
  detectTrigger(
    { extendedTextMessage: { text: '@8613800138000 年假有几天', contextInfo: { mentionedJid: ['8613800138000@s.whatsapp.net'] } } },
    self
  ),
  { triggered: true, via: 'mention' },
  '手机号 JID 提及 → 触发'
);

console.log('\n[3] 群内 @机器人（带设备后缀）');
eq(
  detectTrigger(
    { extendedTextMessage: { text: 'hi', contextInfo: { mentionedJid: ['8613800138000:12@s.whatsapp.net'] } } },
    self
  ),
  { triggered: true, via: 'mention' },
  '提及 JID 带设备后缀 → 触发'
);

console.log('\n[4] 群内 @机器人（LID 形式）');
eq(
  detectTrigger(
    { extendedTextMessage: { text: 'hi', contextInfo: { mentionedJid: ['99887766@lid'] } } },
    self
  ),
  { triggered: true, via: 'mention' },
  'LID 提及 → 触发'
);

console.log('\n[5] @的是别人 → 不应触发');
eq(
  detectTrigger(
    { extendedTextMessage: { text: '@8613900000000 你看下', contextInfo: { mentionedJid: ['8613900000000@s.whatsapp.net'] } } },
    self
  ),
  { triggered: false, via: null },
  '提及他人 → 不触发'
);

console.log('\n[6] 无人提及 → 不应触发');
eq(detectTrigger({ conversation: '今天天气不错' }, self), { triggered: false, via: null }, '普通群消息 → 不触发');

console.log('\n[7] 引用回复机器人');
eq(
  detectTrigger(
    { extendedTextMessage: { text: '那报销呢', contextInfo: { stanzaId: 'BOT_MSG_1' } } },
    self,
    new Set(['BOT_MSG_1'])
  ),
  { triggered: true, via: 'reply' },
  '回复机器人消息 → 触发'
);

console.log('\n[8] 引用回复别人的消息 → 不应触发');
eq(
  detectTrigger(
    { extendedTextMessage: { text: '同意', contextInfo: { stanzaId: 'OTHER_MSG' } } },
    self,
    new Set(['BOT_MSG_1'])
  ),
  { triggered: false, via: null },
  '回复他人消息 → 不触发'
);

console.log('\n[9] 文本抽取（多种消息类型）');
eq(extractText({ conversation: '纯文本' }), '纯文本', 'conversation');
eq(extractText({ extendedTextMessage: { text: '扩展文本' } }), '扩展文本', 'extendedTextMessage');
eq(extractText({ imageMessage: { caption: '图片说明' } }), '图片说明', 'imageMessage.caption');
eq(extractText({ videoMessage: { caption: '视频说明' } }), '视频说明', 'videoMessage.caption');
eq(extractText({ documentMessage: { caption: '文档说明' } }), '文档说明', 'documentMessage.caption');
eq(extractText({ stickerMessage: {} }), '', '贴纸无文本 → 空串');
eq(extractText(null), '', 'null → 空串');

console.log('\n[10] 剥离 @标记');
eq(stripMentions('@8613800138000 年假有几天'), '年假有几天', '剥离手机号 @');
eq(stripMentions('@8613800138000@c.us 报销流程'), '报销流程', '剥离完整 JID @');
eq(stripMentions('  @8613800138000   '), '', '只有 @ 没有正文 → 空串');
eq(stripMentions('年假  有  几天'), '年假 有 几天', '压缩多余空白');

console.log('\n[11] 会话准入');
const base = { allowGroups: ['*'], replyMode: 'group' };
eq(isAllowedChat({ ...base, chatJid: '123@g.us', isGroup: true }), true, '群聊 + 通配白名单 → 允许');
eq(isAllowedChat({ ...base, chatJid: '999@s.whatsapp.net', isGroup: false }), false, '私聊 + group 模式 → 拒绝');
eq(
  isAllowedChat({ allowGroups: ['123@g.us'], replyMode: 'group', chatJid: '456@g.us', isGroup: true }),
  false,
  '群聊不在白名单 → 拒绝'
);
eq(
  isAllowedChat({ allowGroups: ['123@g.us'], replyMode: 'group', chatJid: '123@g.us', isGroup: true }),
  true,
  '群聊在白名单 → 允许'
);
eq(
  isAllowedChat({ allowGroups: ['*'], replyMode: 'all', chatJid: '999@s.whatsapp.net', isGroup: false }),
  true,
  '私聊 + all 模式 → 允许'
);

console.log('\n[12] LID 延迟下发（真实环境踩过的坑）');
// WhatsApp 常在连接建立之后才下发 LID。若只在连接时算一次自身标识并缓存，
// 缓存里就永久没有 LID，之后所有 LID 形态的 @提及 会静默失效。
// 因此实现改为「每条消息实时重算」——本组用例锁定该行为。
const lateSock = { user: { id: '8615638281623:5@s.whatsapp.net' } };
const idsBefore = selfIdentifiers(lateSock);
eq(idsBefore.has('12345678@lid'), false, '连接时未下发 LID → 集合中确实没有');

lateSock.user.lid = '12345678@lid'; // 服务端稍后补上
const idsAfter = selfIdentifiers(lateSock);
eq(idsAfter.has('12345678@lid'), true, 'LID 下发后重新计算 → 已包含');

eq(
  detectTrigger(
    { extendedTextMessage: { text: 'hi', contextInfo: { mentionedJid: ['12345678@lid'] } } },
    idsBefore
  ),
  { triggered: false, via: null },
  '用旧快照匹配 LID 提及 → 漏判（这正是缓存版本会静默失效的原因）'
);
eq(
  detectTrigger(
    { extendedTextMessage: { text: 'hi', contextInfo: { mentionedJid: ['12345678@lid'] } } },
    idsAfter
  ),
  { triggered: true, via: 'mention' },
  '用实时重算的集合匹配 LID 提及 → 正确触发'
);

console.log('\n[13] 剥离 @标记后为空的情形（触发提示语而非提问）');
eq(stripMentions('@8613800138000'), '', '只有 @ 无正文 → 空');
eq(stripMentions('@8613800138000@c.us'), '', '只有完整 JID 无正文 → 空');
eq(stripMentions('  @99887766@lid  '), '', '只有 LID 无正文 → 空');

console.log(`\n${'='.repeat(46)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
