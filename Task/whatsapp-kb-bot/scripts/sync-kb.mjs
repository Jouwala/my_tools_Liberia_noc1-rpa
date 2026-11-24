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
 * ## 判据：看「导出的知识正文」，不看 xlsx 的 mtime（2026-11-16 改）
 *
 * 旧实现把四份源 xlsx 的 size + mtime 拼成指纹。问题在于**规则采集每天 04:20
 * 都会重写** `eflow_TT_rules.xlsx`：mtime 天天变 → 指纹天天变 → 每天都被判成
 * 「规则更新了」：白算 6001 条向量（约 4 分钟）、每天重启一次 bot，还把
 * 「那一刻 Ollama 必须在线」变成每日固定赌注 —— 2026-11-11 / 11-12 / 11-16
 * 三次失败都是这么来的（当天规则正文其实只有一份文档真的变了）。
 *
 * 现在改成：
 *   1. 先跑导出（本地、幂等；正文没变不落盘，见 export-tt-knowledge.py::write_doc）；
 *   2. 对 knowledge/ 下全部文档算**正文哈希**（src/indexFreshness.js::hashKnowledge）；
 *   3. 与上次成功同步时存下的哈希比对：一致 → 直接退出 0（1~2 秒，不碰 Ollama）；
 *      不一致 → 预检 Ollama → ingest → 重启 bot → 写回新哈希。
 * 中途失败**不写**哈希，下一次运行会重试整套流程。
 *
 * ⚠ 指纹只覆盖**知识库正文**。如果有人手改了 knowledge/ 下的 md，正文哈希会变，
 * 本脚本会照常重建 —— 这正是我们想要的行为（旧实现查不出手改，只能靠 bot 的
 * `ping` 报「磁盘知识比索引新」）。
 *
 * ## 失败时的报错要求（2026-11-16）
 *
 * 失败行必须带 **Ollama 地址**（如 http://192.168.100.27:11434）。my_app 的
 * auto_retry（backend/services/auto_retry.py）会从错误文本里提 host:port 做 TCP
 * 探测门控：嵌入机不可达时**跳过重试且不烧重试额度**，等它恢复后立刻重投。
 * 这是「凌晨 Ollama 不在线 → 知识库陈旧一整天」的自愈路径：2026-11-16 04:35
 * 那次失败后 2 次自动重试在 1 小时内烧光，知识库一直陈旧到第二天。
 *
 * ## 退出码
 *
 *   0 已同步 / 无需同步    1 同步失败（调用方据此把任务标记为失败）
 */
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync, statSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { scanKnowledge, diffIndex, hashKnowledge } from '../src/indexFreshness.js';
import { myAppDir, RULE_SOURCE_FILES } from '../src/myAppPaths.js';
import { CONFIG } from '../src/config.js';
import { healthCheck } from '../src/ollama.js';

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
 * ⚠ 这个指纹**只用来判断「源文件在不在」和打印排查线索**，不再参与「要不要重建」
 * 的决策（那个决策看知识正文哈希，见文件头）。规则源清单与路径解析都在
 * `src/myAppPaths.js` —— 与 ping 的鲜度检测共用同一份事实。
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

async function main() {
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

  // ---- 1. 导出（本地、幂等；正文没变的文件不重写，mtime 保持不变）----
  if (DRY_RUN) {
    console.log('\n[1/4] (dry-run) 跳过导出');
  } else {
    console.log('\n[1/4] 导出知识文档…');
    const exportCode = runPy('export-tt-knowledge.py');
    if (exportCode !== 0) {
      console.error(`✗ 导出失败（exit=${exportCode}），知识库未改动`);
      return 1;
    }
  }

  // ---- 2. 知识库正文指纹 ----
  let snap;
  try {
    const files = scanKnowledge(KNOWLEDGE_DIR, ROOT);
    if (!files.length) {
      console.error(`✗ ${KNOWLEDGE_DIR} 下没有可入库的知识文件`);
      return 1;
    }
    snap = { files, hash: hashKnowledge(files, ROOT) };
  } catch (err) {
    console.error(`✗ 读取知识库文件失败（正文哈希算不出来）：${err.message}`);
    return 1;
  }

  const state = readState();
  if (!FORCE && state.knowledgeHash && state.knowledgeHash === snap.hash) {
    // 正文与上次成功同步时一致 —— 绝大多数日子走到这里就结束，完全不碰 Ollama。
    const fresh = checkIndexFresh();
    if (fresh.ok) {
      // 仍然要刷新 syncedAt（不重建索引）。理由：`src/ruleSourceFreshness.js` 拿
      // 「四个规则源 xlsx 的最新 mtime」与这里的 syncedAt 比，判断「规则表是不是比
      // 知识库新」。规则采集每天 04:20 都会重写 xlsx（mtime 必变、正文往往没变），
      // 若跳过时不动 syncedAt，bot 的 ping 会从 04:20 起一直误报「规则表比知识库新」
      // —— 把「没变化」说成「没同步」，正是这条链路要避免的误报。
      writeState({
        ...state,
        knowledgeHash: snap.hash,
        files: snap.files.length,
        sourceFingerprint: fp.fingerprint,
        syncedAt: new Date().toISOString(),
      });
      console.log(`\n✓ 知识库正文未变化，跳过同步（${snap.files.length} 个文件；--force 可强制重建）`);
      return 0;
    }
    console.log('\n! 正文未变化，但索引与磁盘知识不一致，仍需重建：');
    console.log(`  ${JSON.stringify(fresh.diff || fresh.error)}`);
  }

  if (DRY_RUN) {
    console.log('[dry-run] 将执行：ingest → 重启 bot');
    return 0;
  }

  // ---- 3. 预检 Ollama：失败行必须带地址，供 my_app 的 auto_retry 探测门控 ----
  console.log('\n[2/4] 预检 Ollama 嵌入服务…');
  let health;
  try {
    health = await healthCheck();
  } catch (err) {
    // 「不可达或超时」是有意选的措辞：这两个词在 my_app 的
    // backend/services/auto_retry.py::NETWORK_ERROR_KEYS 里，配合地址才会走
    // TCP 探测门控（目标不可达时不消耗重试额度）。node 的 fetch 在连接被拒时
    // 只报一句 `fetch failed`，不含任何网络关键字 —— 实测那样会被归成 unknown，
    // 又退回「1 小时内烧光 2 次额度」的老路。
    console.error(`✗ 索引未重建：Ollama 嵌入服务不可达或超时（${CONFIG.ollamaUrl}）—— ${err.message}`);
    console.error('  知识文档已导出，索引仍是旧版；下一次运行会重试。');
    return 1;
  }
  if (!health.embedModelPresent) {
    // 与「不可达」区分开：端口是通的，重试也不会长出模型，必须人工 ollama pull。
    console.error(`✗ 索引未重建：缺少嵌入模型 ${CONFIG.embedModel}（${CONFIG.ollamaUrl}），请先 ollama pull`);
    return 1;
  }
  console.log(`  ✓ ${CONFIG.embedModel} 就位（${CONFIG.ollamaUrl}）`);

  // ---- 4. 重建索引 ----
  console.log('\n[3/4] 重建索引…');
  const ingestCode = runNpm('ingest');
  if (ingestCode !== 0) {
    // 地址必须留在这一行：它同时是给人看的线索和 auto_retry 的探测目标。
    console.error(`✗ 索引重建失败（exit=${ingestCode}）：Ollama 嵌入服务 ${CONFIG.ollamaUrl} 不可用或超时`);
    console.error('  index.json 可能已损坏，请检查后手动重跑 npm run ingest');
    return 1;
  }

  console.log('\n[4/4] 重启 bot 以加载新索引…');
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
    // 决策依据：知识正文哈希（见文件头「判据」）
    knowledgeHash: snap.hash,
    files: snap.files.length,
    // 仅作排查线索：这次重建时源 xlsx 是什么状态
    sourceFingerprint: fp.fingerprint,
    syncedAt: new Date().toISOString(),
    chunks: fresh.meta?.chunks ?? null,
  });
  console.log('\n✓ 知识库同步完成');
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((err) => {
    console.error(`\n意外错误：${err.stack || err.message}`);
    process.exit(1);
  });
