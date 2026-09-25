/**
 * 「现在跑着的这份代码是哪个版本」—— 用来一眼看出进程有没有在跑旧代码。
 *
 * 为什么需要：这个项目所有的改动都是「改文件 → 重启进程」才生效。
 * 改了文件忘了重启，表现是**改了没效果**，而且**没有任何报错**：
 * 日志正常、接口正常、回复也正常，只是内容是旧的 —— 最容易白排查半天。
 *
 * 实测踩过两次：语言适配是 2026-09-16 09:19 写进文件的，而进程是
 * 2026-09-15 21:19 起的，于是英文提问一直收到中文回复，日志里却看不出异常。
 *
 * 做法：取 `src/*.js` 与 `scripts/*.py` 的**最大 mtime** 作为代码指纹。
 * 它不追求精确，只要能回答一个问题：
 *
 *     磁盘上的源文件，比这个进程的启动时间更新吗？
 *
 * 更新 → 跑的是旧代码，重启即可。这个判断在 `ping` 里输出，
 * 不用登机器、不用看日志，群里 @ 一下就知道。
 */
import { readdirSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import { ROOT } from './config.js';

/** 参与指纹计算的目录与扩展名 */
const WATCH = [
  { dir: 'src', exts: ['.js'] },
  { dir: 'scripts', exts: ['.py'] },
];

/**
 * 重新扫一遍源文件，取最大 mtime（毫秒）。读不到就返回 0。
 *
 * ⚠️ 每次调用都会重新 stat —— 不能在模块加载时算一次就存起来，
 * 那样 `isStale()` 永远返回 false（指纹被冻在启动那一刻），
 * 就完全失去意义了。
 */
export function codeMtime() {
  let newest = 0;
  for (const { dir, exts } of WATCH) {
    const abs = resolve(ROOT, dir);
    try {
      for (const f of readdirSync(abs)) {
        if (!exts.some((e) => f.endsWith(e))) continue;
        const m = statSync(resolve(abs, f)).mtimeMs;
        if (m > newest) newest = m;
      }
    } catch {
      // 目录读不到就当没有。这只是辅助排查，不能因此让启动失败。
    }
  }
  return newest;
}

/** 本进程的启动时刻（模块加载 ≈ 进程启动） */
export const PROCESS_STARTED_AT = Date.now();

/** 启动时加载的那份代码的指纹（冻结值，用于对比） */
export const LOADED_MTIME = codeMtime();

/** 本地时间 `2026-09-16 09:19:22`；入参为 0 / 空时返回「未知」 */
export function fmtTime(ms) {
  if (!ms) return '未知';
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  );
}

/**
 * 纯函数（便于单测）：磁盘上的代码比进程启动时间更新 → 跑的是旧代码。
 * @param {number} processStartedAt 进程启动时刻（毫秒）
 * @param {number} diskMtime        源文件最大 mtime（毫秒）
 */
export function isStaleCode(processStartedAt, diskMtime) {
  return diskMtime > processStartedAt;
}

/** 当前进程是否在跑旧代码（每次调用都重新扫盘） */
export function isStale() {
  return isStaleCode(PROCESS_STARTED_AT, codeMtime());
}

/** 已运行多久，如 `3 小时 12 分钟` / `8 分钟` */
export function uptimeText() {
  const min = Math.floor((Date.now() - PROCESS_STARTED_AT) / 60000);
  if (min < 60) return `${min} 分钟`;
  return `${Math.floor(min / 60)} 小时 ${min % 60} 分钟`;
}
