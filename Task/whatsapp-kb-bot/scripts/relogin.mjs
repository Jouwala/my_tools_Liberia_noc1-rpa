#!/usr/bin/env node
/**
 * 换号 / 重新登录辅助脚本。
 *
 *   node scripts/relogin.mjs                 # 机器人本体（data/auth）
 *   node scripts/relogin.mjs --notify        # P1 告警推送（data/auth-notify）
 *
 * 做的事：把凭据目录整体改名备份，然后提示你重新扫码。
 * 不直接删除任何东西 —— 万一换号失败，可以改回来。
 *
 * 为什么需要它：登录凭据和手机号绑定。想换一个号码，
 * 必须先清掉旧凭据，否则 Baileys 会继续用旧身份连接。
 *
 * 为什么需要 --notify：notify.js 用**独立的凭据目录**（见 src/notify.js 的
 * AUTH_DIR 注释）。两个进程共用一份凭据会被 WhatsApp 判为同号双开并无限
 * 互踢（code=440），2026-10-03 事故即由此而来。所以两边各有各的码要扫。
 */
import { existsSync, renameSync, readdirSync, readFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { CONFIG, ROOT } from '../src/config.js';

// 目标进程：默认机器人本体，--notify 切到告警推送。
// 环境变量与 src/notify.js 的 AUTH_DIR 保持同一优先级，改一处必须改另一处。
const FOR_NOTIFY = process.argv.includes('--notify');
const AUTH = FOR_NOTIFY
  ? process.env.NOTIFY_AUTH_DIR || join(ROOT, 'data', 'auth-notify')
  : CONFIG.authDirAbs;
const BACKUP_ROOT = join(AUTH, '..');
const WHO = FOR_NOTIFY ? 'P1 告警推送（notify.js）' : '知识库机器人（index.js）';
const START_CMD = FOR_NOTIFY ? 'npm run notify' : 'npm start';

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

console.log(`=== 重新登录（换号）辅助 —— ${WHO} ===\n`);
console.log(`凭据目录：${AUTH}\n`);

// 目录不存在时**不能**简单说「直接运行 npm start 扫码即可」就完事 ——
// 那是把用户推给另一个脚本，而那个脚本原本又会把用户推回来
//（2026-10-03 实测：relogin 说去跑 notify，notify 说去跑 relogin，死循环）。
// 现在明确说清职责分工：本脚本只管**清**，扫码由目标进程自己出码。
if (!existsSync(AUTH)) {
  console.log('该目录不存在，说明这个通道**还没登录过**（本脚本只负责清旧凭据，不负责出二维码）。\n');
  console.log('直接启动它，二维码会自己打出来：');
  console.log(`    ${START_CMD}\n`);
  console.log('（本项目两个进程各有独立凭据，两边都要单独扫一次码）');
  process.exit(0);
}

const id = currentIdentity();

// 没有有效凭据就该停下。否则会把空目录也"备份"一遍，
// 产生一堆零文件的 auth.bak-* —— 实测用户会重复执行本脚本，
// 之后面对多个备份目录，搞不清该把哪个改回去。
if (!id) {
  console.log('当前没有有效的登录凭据（目录为空，或缺少/损坏 creds.json）。\n');
  console.log(`无需执行换号 —— 直接启动它，二维码会自己打出来：\n    ${START_CMD}`);
  process.exit(0);
}

console.log('当前登录身份：');
console.log(`  号码  : ${String(id.id || '').split(':')[0].split('@')[0] || '(未知)'}`);
console.log(`  LID   : ${id.lid || '(无)'}`);
console.log(`  显示名: ${id.name || '(无)'}`);
const fileCount = readdirSync(AUTH).filter((f) => f.endsWith('.json')).length;
console.log(`  凭据文件: ${fileCount} 个\n`);

// 1. 硬性检查目标进程是否还在跑。
//    2026-10-12~14 事故：手动多开的第二实例与线上 bot 顶号（440）34 小时，
//    日志怀疑源头之一就是本脚本带活进程运行。这里原先只有一句文字提醒，
//    拦不住手滑 —— 改成强制：心跳新鲜 + pid 存活就拒绝执行。
//    用心跳而不是 bot.lock/notify.lock：锁要目标进程用新版代码启动过才存在，
//    心跳从进程启动那一刻就在写，覆盖面更早。
const HEARTBEAT = join(ROOT, 'data', FOR_NOTIFY ? 'notify_heartbeat.json' : 'bot_heartbeat.json');
const STOP_CMD = FOR_NOTIFY
  ? 'powershell -NoProfile -File autostart-notify.ps1 -Stop'
  : 'powershell -NoProfile -File autostart.ps1 -Stop';
function targetRunning() {
  try {
    const hb = JSON.parse(readFileSync(HEARTBEAT, 'utf8'));
    if (!hb?.at || !hb?.pid) return false;
    const ageMs = Date.now() - Date.parse(hb.at);
    if (!Number.isFinite(ageMs) || ageMs > 90_000) return false; // 心跳过期 → 进程多半已死
    try {
      process.kill(hb.pid, 0);
      return true; // 心跳新鲜且 pid 活着 → 还在跑
    } catch {
      return false;
    }
  } catch {
    return false; // 无心跳文件 → 进程没在跑（或从未启动过）
  }
}
if (targetRunning()) {
  console.error(`✗ ${WHO} 还在运行（心跳新鲜，pid 见 ${HEARTBEAT}）。`);
  console.error('  两个实例用同一份凭据会互相顶号（440 无限互踢）。先停掉它：');
  console.error(`    ${STOP_CMD}`);
  console.error('  （本脚本只检查心跳这一种信号；拿不准就打开任务管理器再确认一遍）');
  process.exit(1);
}
console.log('✓ 心跳检查通过：目标进程未在运行。');
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
console.log(`2) 运行：${START_CMD}`);
console.log('3) 手机 WhatsApp → 设置 → 已关联的设备 → 关联设备');
console.log('4) 扫描终端里的二维码');
console.log();
console.log(`想用回原来的号码：把 ${backup}`);
console.log(`改名为 ${AUTH} 即可（先停掉对应进程）。`);
