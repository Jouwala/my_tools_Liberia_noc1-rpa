#!/usr/bin/env node
/**
 * 换号 / 重新登录辅助脚本。
 *
 *   node scripts/relogin.mjs
 *
 * 做的事：把 data/auth/ 整体改名备份，然后提示你重新扫码。
 * 不直接删除任何东西 —— 万一换号失败，可以改回来。
 *
 * 为什么需要它：登录凭据和手机号绑定。想换一个号码，
 * 必须先清掉旧凭据，否则 Baileys 会继续用旧身份连接。
 */
import { existsSync, renameSync, readdirSync, readFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { CONFIG } from '../src/config.js';

const AUTH = CONFIG.authDirAbs;
const BACKUP_ROOT = join(AUTH, '..');

function currentIdentity() {
  const p = join(AUTH, 'creds.json');
  if (!existsSync(p)) return null;
  try {
    const me = JSON.parse(readFileSync(p, 'utf8')).me || {};
    return { id: me.id, lid: me.lid, name: me.name };
  } catch {
    return null;
  }
}

console.log('=== 重新登录（换号）辅助 ===\n');

if (!existsSync(AUTH)) {
  console.log(`data/auth/ 不存在，无需清理。\n直接运行 npm start 扫码即可。`);
  process.exit(0);
}

const id = currentIdentity();

// 没有有效凭据就该停下。否则会把空目录也"备份"一遍，
// 产生一堆零文件的 auth.bak-* —— 实测用户会重复执行本脚本，
// 之后面对多个备份目录，搞不清该把哪个改回去。
if (!id) {
  console.log('当前没有有效的登录凭据（data/auth/ 为空，或缺少/损坏 creds.json）。\n');
  console.log('无需执行换号 —— 直接运行 npm start 扫码即可。');
  process.exit(0);
}

console.log('当前登录身份：');
console.log(`  号码  : ${String(id.id || '').split(':')[0].split('@')[0] || '(未知)'}`);
console.log(`  LID   : ${id.lid || '(无)'}`);
console.log(`  显示名: ${id.name || '(无)'}`);
const fileCount = readdirSync(AUTH).filter((f) => f.endsWith('.json')).length;
console.log(`  凭据文件: ${fileCount} 个\n`);

// 1. 提醒停掉正在运行的机器人
console.log('⚠️  执行前请确认机器人已停止（终端里按过 Ctrl+C）。');
console.log('    如果它还在跑，会一边被清凭据一边重连，状态会乱。\n');

// 2. 备份（改名，不删除）
const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
const backup = join(BACKUP_ROOT, `auth.bak-${stamp}`);
try {
  renameSync(AUTH, backup);
  console.log(`✓ 旧凭据已备份到：\n  ${backup}\n`);
} catch (err) {
  console.error(`✗ 备份失败：${err.message}`);
  console.error('  常见原因：机器人进程还占着这个目录，先停掉它再试。');
  process.exit(1);
}

mkdirSync(AUTH, { recursive: true });

// 3. 下一步
console.log('='.repeat(52));
console.log('下一步：');
console.log('='.repeat(52));
console.log('1) 在要用的那个手机号上确认 WhatsApp 已登录');
console.log('   （本机需要的是「已关联的设备」，不是重新注册）');
console.log('2) 运行：npm start');
console.log('3) 手机 WhatsApp → 设置 → 已关联的设备 → 关联设备');
console.log('4) 扫描终端里的二维码');
console.log();
console.log(`想用回原来的号码：把 ${backup}`);
console.log('改名为 data/auth 即可（先停掉机器人）。');
