#!/usr/bin/env node
/**
 * 门户仓库整洁度守卫（scripts/check-cleanliness.mjs）
 *
 * 背景：AGENTS.md 第四节第 7 条要求「一次性探针与转储只能落 TMP\ 并自清」，
 * 但这条约定在本仓库已失效过多次（2026-09-24 审计：门户 506 个跟踪文件里
 * 347 个是探针/转储/手工快照/日志）。人是记不住的，所以把判断写成脚本。
 *
 * 两个职责：
 *   1. audit  —— 扫描「不该被跟踪却被跟踪了」的文件，退出码非 0 表示不干净。
 *                 可单独跑（npm run check:clean），也可被 pre-commit 钩子调用。
 *   2. clean  —— 清理 TMP\ 里的历史积压。默认只报告，加 --apply 才真删；
 *                 默认保留最近 7 天（可能还有人在排查），加 --days=N 可调。
 *
 * 用法：
 *   node scripts/check-cleanliness.mjs audit
 *   node scripts/check-cleanliness.mjs clean              # 只报告
 *   node scripts/check-cleanliness.mjs clean --apply      # 真删
 *   node scripts/check-cleanliness.mjs clean --apply --days=3
 *
 * 无第三方依赖（本仓库没有 husky/lint-staged，不为此新增依赖，见 AGENTS.md 原则 7）。
 */

import { execFileSync } from 'node:child_process'
import { existsSync, readdirSync, rmSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(fileURLToPath(new URL('.', import.meta.url)), '..')

/** 已跟踪文件里，命中就报警的规则。写在这里而不是 .gitignore —— 忽略规则对
 *  已入库文件无效，这些是「清理漏网的存量」而不是「防止新增」。 */
const TRACKED_NOISE = [
  [/^t\d+(\.py)?$/, '根目录一次性探针（t2/t3/t4/t5.py 之类），应移入 TMP/'],
  [/\.bak_|_bak_|\.bak$/, '手工快照不进版本库（AGENTS.md 第四节第 7 条）'],
  [/\.log$/, '运行日志'],
  [/(^|\/)_[^/]*$/, '_ 前缀过程产物（除非在 src/ server/ 下，那是真源码）'],
  [/portal-default\.json$/, '运行时写入，严禁入库'],
  [/^auth-data\//, '含加盐密码哈希，严禁入库'],
]

/** 反向豁免：这些 _ 前缀文件是真源码，历史上刻意保留在版本库里。 */
const SOURCE_EXEMPT = [/^src\//, /^server\//]

function gitFiles() {
  return execFileSync('git', ['ls-files'], { cwd: ROOT, encoding: 'utf8' })
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
}

function audit() {
  const offenders = []
  for (const f of gitFiles()) {
    if (SOURCE_EXEMPT.some((re) => re.test(f))) continue
    for (const [re, why] of TRACKED_NOISE) {
      if (re.test(f)) {
        offenders.push({ file: f, why })
        break
      }
    }
  }

  if (offenders.length === 0) {
    console.log('✓ 整洁度检查通过：没有探针/快照/日志混入版本库。')
    return 0
  }

  console.error(`✗ 发现 ${offenders.length} 个不该入库的文件：\n`)
  for (const { file, why } of offenders) console.error(`  ${file}\n      └ ${why}`)
  console.error('\n处理办法：')
  console.error('  移出版本库（保留磁盘文件）：git rm --cached "<文件>"')
  console.error('  一次性探针请放到 TMP/ 下，那边已被忽略。')
  return 1
}

function clean({ apply, days }) {
  const tmpDir = join(ROOT, 'TMP')
  if (!existsSync(tmpDir)) {
    console.log('TMP/ 不存在，无需清理。')
    return 0
  }

  const cutoffMs = Date.now() - days * 24 * 60 * 60 * 1000
  const stale = []
  let staleBytes = 0

  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name)
      if (entry.isDirectory()) {
        walk(full)
      } else if (entry.isFile()) {
        const st = statSync(full)
        if (st.mtimeMs < cutoffMs) {
          stale.push(full)
          staleBytes += st.size
        }
      }
    }
  }
  walk(tmpDir)

  const mb = (staleBytes / 1048576).toFixed(1)
  if (stale.length === 0) {
    console.log(`✓ TMP/ 无需清理：没有早于 ${days} 天的文件。`)
    return 0
  }

  console.log(`TMP/ 中早于 ${days} 天的文件：${stale.length} 个，共 ${mb} MB`)
  if (!apply) {
    console.log('\n（仅报告。加 --apply 才会真删）')
    for (const f of stale.slice(0, 20)) console.log('  ' + relative(ROOT, f))
    if (stale.length > 20) console.log(`  … 另有 ${stale.length - 20} 个`)
    return 0
  }

  for (const f of stale) rmSync(f, { force: true })
  // 清掉因删文件而空掉的目录（自底向上，目录空才删）
  const pruneEmpty = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) pruneEmpty(join(dir, entry.name))
    }
    if (dir !== tmpDir && readdirSync(dir).length === 0) rmSync(dir, { recursive: true, force: true })
  }
  pruneEmpty(tmpDir)

  console.log(`✓ 已删除 ${stale.length} 个文件，释放约 ${mb} MB。`)
  return 0
}

// ── 入口 ────────────────────────────────────────────────────────────────────
const [cmd = 'audit', ...flags] = process.argv.slice(2)
const apply = flags.includes('--apply')
const daysArg = flags.find((f) => f.startsWith('--days='))
const days = daysArg ? Number(daysArg.split('=')[1]) : 7

let code = 0
if (cmd === 'audit') code = audit()
else if (cmd === 'clean') code = clean({ apply, days })
else {
  console.error(`未知命令：${cmd}\n用法：check-cleanliness.mjs [audit|clean] [--apply] [--days=N]`)
  code = 2
}

process.exit(code)
