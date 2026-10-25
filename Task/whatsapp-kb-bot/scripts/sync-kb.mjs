#!/usr/bin/env node
/**
 * 规则文件 → 知识库 同步器（**幂等**：没有变化就什么都不做）。
 *
 *   node scripts/sync-kb.mjs            # 检查并同步
 *   node scripts/sync-kb.mjs --force    # 跳过「有无变化」判断，强制重建
 *   node scripts/sync-kb.mjs --dry-run  # 只报告会做什么，不执行
 *
 * ## 为什么需要它
 *
 * 知识库有两条链路会用到 TT 规则，它们的自动性是**不一样**的：
 *
 *   · 实时通道（带 TT 单号提问）：`src/tt.js` 每次起子进程跑 `tt-analyze.py`，
 *     每次都重新读 xlsx —— 规则一改，**下一个问题就用新规则**。不需要任何操作。
 *
 *   · 知识库通道（「推单规则怎么配」这类叙述题）：索引 `data/index.json` 是
 *     `npm run ingest` 生成的快照，且 bot 进程启动时一次性读进内存。规则改了
 *     但不 export + ingest + 重启，bot 会一直按旧规则回答，且**不报任何错**。
 *     2026-09-15 与 2026-10-23 各踩过一次。
 *
 * 本脚本把「export → ingest → 重启」串成一步，并由 my_app 的定时任务在每次
 * 规则采集完成后调用（见 `backend/services/whatsapp_kb_service.py`）。
 *
 * ## 为什么用「指纹」而不是每次都重建
 *
 * `ingest` 要重新算 800+ 条向量（约 40 秒），并且**必须重启 bot 进程**新索引
 * 才生效 —— 而重启与用户提问存在竞态，代价不小。规则采集是每 3 天一次，
 * 绝大多数时候内容根本没变。所以先比指纹，变了才动：
 *
 *   1. 把四份源 xlsx 的 size + mtime 拼成指纹，与上次成功同步时存的比对；
 *   2. 指纹一致 → 直接退出 0（`skipped`）；不一致 → 走完整流程；
 *   3. 流程成功后写回指纹。中途失败**不写**，下次会重试。
 *
 * 注意：指纹只覆盖**规则源文件**。如果有人手改了 knowledge/ 下的 md，
 * 本脚本查不出来 —— 那种情况靠 bot 的 `ping` 报「磁盘知识比索引新」暴露。
 *
 * ## 退出码
 *
 *   0 已同步 / 无需同步    1 同步失败（调用方据此把任务标记为失败）
 */
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync, statSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { scanKnowledge, diffIndex } from '../src/indexFreshness.js';
import { myAppDir, RULE_SOURCE_FILES } from '../src/myAppPaths.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..');
const STATE_PATH = join(ROOT, 'data', 'kb_sync_state.json');
const INDEX_PATH = join(ROOT, 'data', 'index.json');
const KNOWLEDGE_DIR = join(ROOT, 'knowledge');

const FORCE = process.argv.includes('--force');
const DRY_RUN = process.argv.includes('--dry-run');

/**
 * 计算规则源文件指纹；任一文件缺失返回 ok=false（调用方据此判定不可同步）。
 *
 * 规则源清单与路径解析都在 `src/myAppPaths.js` —— 与 ping 的鲜度检测共用
 * 同一份事实，避免两处各写一套后在换机时漂移。
 */
function computeSourceFingerprint(myAppDir) {
  const parts = [];
  for (const segs of RULE_SOURCE_FILES) {
    const full = join(myAppDir, ...segs);
    if (!existsSync(full)) return { ok: false, missing: segs.join('/') };
    const st = statSync(full);
    parts.push(`${segs[segs.length - 1]}:${st.size}:${Math.round(st.mtimeMs)}`);
  }
  return { ok: true, fingerprint: parts.join('|'), parts };
}

function readState() {
  try {
    return JSON.parse(readFileSync(STATE_PATH, 'utf8'));
  } catch {
    return {};
  }
}

function writeState(obj) {
  mkdirSync(dirname(STATE_PATH), { recursive: true });
  writeFileSync(STATE_PATH, JSON.stringify(obj, null, 2) + '\n', 'utf8');
}

/** 用 my_app 的解释器跑 Python 脚本（与 run-py.mjs 同一条路径）。 */
function runPy(scriptName, extraArgs = []) {
  const r = spawnSync(
    process.execPath,
    [join(HERE, 'run-py.mjs'), scriptName, ...extraArgs],
    { cwd: ROOT, stdio: 'inherit', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }
  );
  return r.status ?? 1;
}

function runNpm(script) {
  const isWin = process.platform === 'win32';
  const r = spawnSync(isWin ? 'npm.cmd' : 'npm', ['run', script], {
    cwd: ROOT,
    stdio: 'inherit',
    shell: isWin,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });
  return r.status ?? 1;
}

/**
 * 重启 bot 进程。
 *
 * 走 `autostart.ps1`：它同时处理「stop 旧进程」与「start 新进程 + 等连上」，
 * 并且在计划任务 WhatsAppKB_Bot_EnsureRunning 同时存在时不会起出两份
 * （脚本自己判活：已有健康进程时直接复用）。
 *
 * @returns {number} 0 = 成功
 */
function restartBot() {
  const isWin = process.platform === 'win32';
  if (!isWin) {
    console.warn('! 非 Windows 平台，跳过 bot 重启（请手动重启）');
    return 0;
  }
  const stop = spawnSync(
    'powershell.exe',
    ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', join(ROOT, 'autostart.ps1'), '-Stop'],
    { cwd: ROOT, stdio: 'inherit' }
  );
  if ((stop.status ?? 1) !== 0) return stop.status ?? 1;
  const start = spawnSync(
    'powershell.exe',
    ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', join(ROOT, 'autostart.ps1')],
    { cwd: ROOT, stdio: 'inherit' }
  );
  return start.status ?? 1;
}

/** 索引与磁盘知识是否一致（重启后核对，确认新索引真的被加载）。 */
function checkIndexFresh() {
  try {
    const meta = JSON.parse(readFileSync(INDEX_PATH, 'utf8')).meta;
    const diff = diffIndex(meta, scanKnowledge(KNOWLEDGE_DIR, ROOT));
    return { ok: diff.ok, diff, meta };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

function main() {
  const appDir = myAppDir();
  if (!appDir) {
    console.error('✗ 找不到 my_app 目录（可设 MY_APP_DIR 覆盖）');
    return 1;
  }
  console.log(`my_app 目录：${appDir}`);

  const fp = computeSourceFingerprint(appDir);
  if (!fp.ok) {
    // 缺源文件 = 采集任务可能还没跑过或盘断了。**不改动知识库**：
    // 导出脚本对缺文件会「跳过」，若此时重建索引，
    // 会把已有的那份 md 内容原样留下、却把索引整体重算一遍，得不偿失。
    console.error(`✗ 规则源文件缺失：${fp.missing}`);
    console.error('  知识库未改动。请先执行 eFlow 规则采集任务。');
    return 1;
  }

  const state = readState();
  if (!FORCE && state.sourceFingerprint === fp.fingerprint) {
    console.log('✓ 规则源文件自上次同步后未变化，跳过（--force 可强制重建）');
    // 仍然核对一次索引新鲜度：md 若被手改过，这里要报出来
    const fresh = checkIndexFresh();
    if (!fresh.ok && fresh.diff) {
      console.warn('! 但索引与磁盘 knowledge/ 不一致（可能是手改了 md）—— 建议 --force 重建');
    }
    return 0;
  }

  console.log('→ 检测到规则更新，开始同步知识库');
  console.log(`  指纹：${fp.fingerprint}`);
  if (DRY_RUN) {
    console.log('[dry-run] 将执行：export-kb → ingest → 重启 bot');
    return 0;
  }

  console.log('\n[1/3] 导出知识文档…');
  const exportCode = runPy('export-tt-knowledge.py');
  if (exportCode !== 0) {
    console.error(`✗ 导出失败（exit=${exportCode}），知识库未改动`);
    return 1;
  }

  console.log('\n[2/3] 重建索引…');
  const ingestCode = runNpm('ingest');
  if (ingestCode !== 0) {
    console.error(`✗ 索引重建失败（exit=${ingestCode}）`);
    console.error('  index.json 可能已损坏，请检查后手动重跑 npm run ingest');
    return 1;
  }

  console.log('\n[3/3] 重启 bot 以加载新索引…');
  const restartCode = restartBot();
  if (restartCode !== 0) {
    console.error(`✗ bot 重启失败（exit=${restartCode}）`);
    console.error('  新索引已写好，但**跑着的进程仍用旧索引**。请手动执行：');
    console.error('    powershell -File autostart.ps1 -Stop');
    console.error('    powershell -File autostart.ps1');
    // 不写指纹：下次运行会重试整个流程
    return 1;
  }

  const fresh = checkIndexFresh();
  if (!fresh.ok) {
    console.warn('! 索引与磁盘知识仍不一致，请人工核对：', JSON.stringify(fresh.diff || fresh.error));
  } else {
    console.log(`✓ 索引新鲜（${fresh.meta?.chunks} 块 / ${fresh.meta?.files} 个文件）`);
  }

  writeState({
    sourceFingerprint: fp.fingerprint,
    parts: fp.parts,
    syncedAt: new Date().toISOString(),
    chunks: fresh.meta?.chunks ?? null,
    files: fresh.meta?.files ?? null,
  });
  console.log('\n✓ 知识库同步完成');
  return 0;
}

process.exit(main());
