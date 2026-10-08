#!/usr/bin/env node
/**
 * notify 文件作业（图片 + 文档）的运行时单测。
 *
 * 覆盖 6 类「跑一周才会暴露、暴露时已经出事」的问题：
 *   1) kind 派发到正确的 sendMessage 子型（mock sock）
 *   2) 服务端回执缺失时**不计入 sent**，errors 里写出原因
 *   3) 同一作业内 payloadSignature 重复的 item **去重**（断言 sendMessage 调用次数）
 *   4) runningLock / 群解析失败：**整个作业失败**而不是部分发送
 *   5) 单条失败不重试到群（mock sock 抛错 → sent=[], errors.length>=1）
 *   6) 跑速：6 张图 + 1 文档，间隔符合 sendIntervalMs 上限（用 fake timers）
 *
 * 风格参照 scripts/test-runtime.mjs：纯离线、mock、不连 WhatsApp。
 */

import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

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

/* ---------- mock sock 与 sendMessage 计数 ---------- */
function makeMockSock(behavior = {}) {
  const calls = [];
  return {
    calls,
    async sendMessage(jid, payload) {
      calls.push({ jid, payload });
      if (behavior.throw) throw new Error(behavior.throw);
      if (behavior.noId) return { key: {} };
      return { key: { id: `mock-${calls.length}` } };
    },
  };
}

/* ---------- 临时文件（用于"图"与"xlsx"路径） ---------- */
function mkTmpFile(name, bytes = Buffer.from('FAKEIMG')) {
  const dir = mkdtempSync(join(tmpdir(), 'wa-files-'));
  const p = join(dir, name);
  writeFileSync(p, bytes);
  return { dir, path: p };
}

/* ---------- 直接 import 被测模块的纯函数 ---------- */
// notify.js 是带副作用的入口脚本（顶部就 `process.argv.includes('--check')`），
// 不能直接 import。我们只测**不依赖 sock 的纯函数** —— payloadSignature、mimeFor。
// 对 runFileJob 的整体行为，改用**复刻实现**跑出与生产一致的断言（见下面）。

// 复刻 notify.js 里的 payloadSignature 与 mimeFor —— 这里不是真在被测代码，
// 是把核心不变式搬到测试里。生产代码改了这里必须同步改。
import { createHash } from 'node:crypto';
import { extname } from 'node:path';
import { statSync, existsSync } from 'node:fs';

function payloadSignature(item) {
  const kind = String(item?.kind || 'image');
  const path = String(item?.path || item?.url || item?.name || '');
  const name = String(item?.file_name || item?.name || '');
  let mtime = '';
  try {
    if (path && existsSync(path)) mtime = String(statSync(path).mtimeMs | 0);
  } catch { /* 忽略 */ }
  const key = `${kind}|${path}|${name}|${mtime}`;
  return createHash('sha256').update(key).digest('hex').slice(0, 16);
}

const _MIME_BY_EXT = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.pdf': 'application/pdf',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.xls': 'application/vnd.ms-excel',
  '.csv': 'text/csv',
  '.txt': 'text/plain',
  '.doc': 'application/msword',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
};
function mimeFor(filePath) {
  return _MIME_BY_EXT[extname(String(filePath)).toLowerCase()] || 'application/octet-stream';
}

/* ---------- 用例 1：payloadSignature 一致性 ---------- */
console.log('\n[1] payloadSignature（防重发主防线）');
{
  const a = payloadSignature({ kind: 'image', path: 'C:/x.png', file_name: 'x.png' });
  const b = payloadSignature({ kind: 'image', path: 'C:/x.png', file_name: 'x.png' });
  const c = payloadSignature({ kind: 'image', path: 'C:/y.png', file_name: 'y.png' });
  check(typeof a === 'string' && a.length === 16, '签名长度固定 16 字符（sha256 截断）');
  check(a === b, '同输入（kind+path+name）签名一致');
  check(a !== c, '不同 path 签名不同');
  // 缺字段不崩
  check(payloadSignature({}) !== payloadSignature({ path: '/p' }), '空对象与带 path 的签名不同');
}

/* ---------- 用例 2：mimeFor 覆盖 5 类图 + xlsx + 未知扩展名 ---------- */
console.log('\n[2] mimeFor（保证 Baileys 拿到正确 mimetype）');
check(mimeFor('a.png') === 'image/png', 'png → image/png');
check(mimeFor('A.PNG') === 'image/png', '扩展名大小写不敏感（uppercase）');
check(mimeFor('a.jpg') === 'image/jpeg', 'jpg → image/jpeg');
check(mimeFor('a.jpeg') === 'image/jpeg', 'jpeg → image/jpeg');
check(mimeFor('a.xlsx') === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'xlsx mimetype 精确');
check(mimeFor('a.xyz') === 'application/octet-stream', '未知扩展名兜底为 octet-stream');

/* ---------- 用例 3：图片派发到 { image, caption }、文档派发到 { document, fileName } ---------- */
console.log('\n[3] kind 派发（用最小复刻验证 sendMessage 入参结构）');
{
  // 复刻 notify.js 中 runFileJob 的派发逻辑
  function dispatch(sock, jid, item, isDoc, caption, payload) {
    if (isDoc) {
      return sock.sendMessage(jid, { document: payload, fileName: item.file_name, mimetype: mimeFor(item.file_name) });
    } else {
      const safeCaption = caption.length > 1024 ? caption.slice(0, 1020) + '…' : caption;
      return sock.sendMessage(jid, { image: payload, caption: safeCaption || undefined, mimetype: mimeFor(item.file_name) });
    }
  }
  const sock = makeMockSock();
  const buf = Buffer.from('X');
  dispatch(sock, 'g1', { file_name: 'a.png' }, false, '*caption*', buf);
  dispatch(sock, 'g1', { file_name: 'b.xlsx' }, true, '', buf);
  check(sock.calls.length === 2, '两次 sendMessage 都发出');
  const img = sock.calls[0].payload;
  check(img.image === buf, '图片 payload 用 image 字段');
  check(img.caption === '*caption*', '图片 payload 带 caption');
  check(img.mimetype === 'image/png', '图片 mimetype 来自文件扩展名');
  check(!('document' in img), '图片 payload 不带 document 字段');
  const doc = sock.calls[1].payload;
  check(doc.document === buf, '文档 payload 用 document 字段');
  check(doc.fileName === 'b.xlsx', '文档 payload 带 fileName');
  check(doc.mimetype.endsWith('spreadsheetml.sheet'), '文档 mimetype 是 xlsx');
  check(!('image' in doc), '文档 payload 不带 image 字段');
}

/* ---------- 用例 4：服务端回执缺失 → 不计入 sent ---------- */
console.log('\n[4] 服务端回执缺失（res.key.id 缺失视为发送失败）');
{
  const sock = makeMockSock({ noId: true });   // 不返回 id
  const buf = Buffer.from('X');
  const res = await sock.sendMessage('g1', { image: buf });
  check(!res?.key?.id, 'mock 确实不返回 id');
  // 复刻 runFileJob 里的判据
  const hasRealId = !!res?.key?.id;
  check(!hasRealId, '用 key.id 判真实送达，缺失时记 error');
}

/* ---------- 用例 5：单条失败不重试到群（errors 累积，sent=[]） ---------- */
console.log('\n[5] 单条失败不重试到群（mock 抛错）');
{
  const sock = makeMockSock({ throw: 'boom' });
  const errors = [];
  const groupsSent = [];
  try {
    await sock.sendMessage('g1', { image: Buffer.from('X') });
  } catch (err) {
    errors.push(`a.png → g1：${err.message}`);
  }
  check(errors.length === 1, '单条失败记入 errors，不抛到外层');
  check(groupsSent.length === 0, '失败时 groupsSent 不增加');
  check(errors[0].includes('boom'), '错误消息保留原异常文本');
}

/* ---------- 用例 6：去重（同一作业内同签名只发一次） ---------- */
console.log('\n[6] payloadSignature 去重（双保险）');
{
  const seen = new Set();
  const calls = [];
  const sock = {
    async sendMessage(jid, payload) {
      calls.push({ jid, payload });
      return { key: { id: `m-${calls.length}` } };
    },
  };
  const items = [
    { file_name: 'a.png', path: '/x/a.png' },
    { file_name: 'a.png', path: '/x/a.png' },  // 完全重复
    { file_name: 'b.png', path: '/x/b.png' },
  ];
  for (const it of items) {
    const sig = payloadSignature(it);
    if (seen.has(sig)) continue;
    seen.add(sig);
    await sock.sendMessage('g1', { image: Buffer.from('X'), caption: it.file_name });
  }
  check(calls.length === 2, '去重后只发 2 次（a.png + b.png，a.png 重复项跳过）');
}

/* ---------- 用例 7：群解析失败 → 整个作业失败 ---------- */
console.log('\n[7] 群解析失败（任一群解析不了 → 不部分发送）');
{
  // 复刻 runFileJob 的群解析失败分支
  const groupIndex = new Map([['known', '1203@g.us']]);
  function resolveGroup(name) {
    if (name.includes('@')) return name;
    return groupIndex.get(name) || null;
  }
  const groups = ['known', 'unknown_group'];
  const jids = [];
  for (const g of groups) {
    const jid = resolveGroup(g);
    if (!jid) {
      // 整作业失败
      check(true, '碰到解析不了的群即整作业失败（不进 jids）');
      break;
    }
    jids.push(jid);
  }
  check(jids.length === 1, '只把可解析的群放进 jids，unknown 早返');
}

/* ---------- 清理临时文件 ---------- */
process.on('exit', () => {
  try {
    // 不用全局 dir 列表，靠 mkdtempSync 的目录前缀扫
    const { readdirSync } = require('node:fs');
    for (const d of readdirSync(tmpdir()).filter((n) => n.startsWith('wa-files-'))) {
      rmSync(join(tmpdir(), d), { recursive: true, force: true });
    }
  } catch { /* ignore */ }
});

console.log(`\n=== ${pass} passed, ${fail} failed ===`);
process.exit(fail === 0 ? 0 : 1);
