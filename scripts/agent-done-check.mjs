#!/usr/bin/env node
/**
 * Agent 完成自检 —— 把 AGENTS.md 第十一节的「完成标准」变成可执行脚本。
 *
 * 为什么需要这个（2026-11-02）：
 *   「提醒 agent 做完了要跑测试」和当年「提醒 agent 记得改文档」是同一种失效模式
 *   （AGENTS.md 第四节第 9 条：靠自觉已失效过 15 次）。区别是：文档一致性已经有
 *   `.githooks/pre-commit` 拦着，而**构建、静态检查、测试这三样一道门都没有** ——
 *   pre-commit 刻意不跑它们（太慢，塞进去所有人都会用 --no-verify）。
 *
 *   于是 agent 只要说一句「已完成」就能收尾，没人核对。本脚本补的就是这个缺口：
 *   自己去跑，而不是听 agent 声称跑过。
 *
 * ── 三档强度 ──────────────────────────────────────────────────────────────
 *   默认      六道快守卫（与 pre-commit 同一份代码）+ 路径相关的静态检查 + 变更清单
 *   --full    再加前端构建、pytest、门户 lint（慢，几分钟；改前端/后端时必须跑）
 *   --hook    Stop 钩子模式：读 stdin JSON，按结果决定是否允许 Claude 收尾
 *
 * ── 证据机制（--hook 为什么不误伤闲聊）─────────────────────────────────────
 *   本仓库工作区长期有别人在途的改动（2026-11-02 实测 59 个），所以「工作区脏」
 *   不能当作「agent 改过东西」。改为比对**差分指纹**：
 *     · 通过一次自检 → 把当前指纹记进 TMP/（已 gitignore，不入库）
 *     · Stop 钩子启动时指纹与记录一致 → 本轮没动过任何文件，直接放行
 *     · 指纹变了 → 说明有改动，要求先通过自检
 *   这样闲聊、纯问答、只读排查都不会被拦。
 *
 * ── 基线（为什么不是要求「全绿」）─────────────────────────────────────────
 *   2026-11-02 实测：本仓库在**无人改动时** pytest 与 ruff 就已经是红的
 *   （别人在途的 `soc_trend_sync.py:130 F821 Optional`、4 条既有用例失败）。
 *   若要求全绿，任何人都跑不过，守卫立刻退化成噪声 —— 然后被绕过。
 *   所以改为**增量判定**：只对「相对基线新增」的失败报警。基线本身也拦不住
 *   真正的错：F821 / E9 这类必然是本次引入的（既有代码若真有早就在跑了）。
 *
 * ── 用法 ──────────────────────────────────────────────────────────────────
 *   node scripts/agent-done-check.mjs                      # 快检
 *   node scripts/agent-done-check.mjs --full               # 快检 + 构建 + 测试
 *   node scripts/agent-done-check.mjs --json               # 机器可读输出
 *   node scripts/agent-done-check.mjs --status             # 只看改动分布与指纹
 *   node scripts/agent-done-check.mjs --update-baseline    # 记录当前失败为基线
 *
 * 退出码：0 = 全部已执行项通过；1 = 有未通过项；2 = 脚本自身出错。
 *
 * 检查项实现见 scripts/lib/agent-checks.mjs。本文件只负责 CLI、输出与钩子判定。
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  ROOT,
  MYAPP,
  STATE_DIR,
  collectChanges,
  diffHash,
  readState,
  writeState,
  tier1Guards,
  tier2Checks,
  fullChecks,
  firstLines,
  parseBaseline,
  formatBaseline,
  parsePytest,
  python,
} from './lib/agent-checks.mjs'

// ─────────────────────────────────────────────────────────────────────────────
// 输出
// ─────────────────────────────────────────────────────────────────────────────

const C = {
  reset: '\u001b[0m',
  dim: '\u001b[2m',
  red: '\u001b[31m',
  green: '\u001b[32m',
  yellow: '\u001b[33m',
  bold: '\u001b[1m',
}
const useColor = process.stdout.isTTY && !process.env.NO_COLOR
const c = (code, s) => (useColor ? code + s + C.reset : s)

function printReport({ files, checks, hash, full }) {
  console.log(c(C.bold, '\n══ Agent 完成自检 ══'))
  console.log(c(C.dim, `  指纹 ${hash.slice(0, 12)}　模式 ${full ? '--full' : '快检'}`))

  if (files.length) {
    const groups = new Map()
    for (const f of files) {
      const top = f.path.split('/').slice(0, 2).join('/')
      groups.set(top, (groups.get(top) || 0) + 1)
    }
    console.log(c(C.dim, `  变更 ${files.length} 个文件：`))
    for (const [k, v] of [...groups].sort((a, b) => b[1] - a[1]).slice(0, 8)) {
      console.log(c(C.dim, `    ${String(v).padStart(3)}  ${k}`))
    }
  } else {
    console.log(c(C.dim, '  变更 0 个文件'))
  }

  console.log('')
  for (const ch of checks) {
    const mark = ch.ok === true ? c(C.green, '✓') : ch.ok === false ? c(C.red, '✗') : c(C.yellow, '—')
    const timing = ch.ms ? c(C.dim, ` (${(ch.ms / 1000).toFixed(1)}s)`) : ''
    console.log(`  ${mark} ${ch.name}${timing}`)
    if (ch.detail) {
      for (const line of ch.detail.split(/\r?\n/)) {
        console.log(`      ${ch.ok === false ? c(C.red, line) : c(C.dim, line)}`)
      }
    }
    if (ch.hint) console.log(`      ${c(C.yellow, '→ ' + ch.hint)}`)
  }

  const failed = checks.filter((x) => x.ok === false)
  const unverified = checks.filter((x) => x.ok === null)

  console.log('')
  if (failed.length) {
    console.log(c(C.red, `✗ ${failed.length} 项未通过：${failed.map((x) => x.name).join('、')}`))
  } else {
    console.log(c(C.green, '✓ 所有已执行的检查通过'))
  }
  if (unverified.length) {
    console.log(c(C.yellow, `⚠ 未验证 ${unverified.length} 项：${unverified.map((x) => x.name).join('、')}`))
    console.log(c(C.yellow, '  这些项没有机器证据。收尾报告里必须如实写「未验证」，不得声称通过。'))
  }
  console.log('')
  return failed.length === 0
}

// ─────────────────────────────────────────────────────────────────────────────
// 组装报告
// ─────────────────────────────────────────────────────────────────────────────

function buildReport({ full }) {
  const changes = collectChanges()
  if (!changes.ok) {
    console.error(`无法读取 git 状态：${changes.error}`)
    process.exit(2)
  }
  const checks = [...tier1Guards(), ...tier2Checks(changes.files, { full })]
  if (full) checks.push(...fullChecks(changes.files))
  return { files: changes.files, checks, hash: diffHash(), full }
}

// ─────────────────────────────────────────────────────────────────────────────
// 模式
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Stop 钩子模式：读 stdin JSON，判定是否允许 Claude 收尾。
 *
 * 输出协议（官方 hooks 文档）：决定阻塞时向 stdout 写
 *   {"decision":"block","reason":"..."}
 * 并以 0 退出；放行则静默 exit 0。
 *
 * 关键防死锁点：`stop_hook_active` 为 true 时说明本次续跑**本身就是钩子促成的**，
 * 必须直接放行 —— 否则「钩子判不通过 → 强制续跑 → 又判不通过」会永远停不下来
 * （Claude Code 另有连续 8 次的上限兜底，但不能指望它）。
 */
function hookMode() {
  let input = {}
  try {
    const raw = readFileSync(0, 'utf8')
    input = raw ? JSON.parse(raw) : {}
  } catch {
    // 拿不到输入就放行 —— 钩子自身故障绝不能把用户卡死
    process.exit(0)
  }

  if (input.stop_hook_active === true) process.exit(0)

  const hash = diffHash()
  const lastPass = readState()
  // 与上次通过时一致 → 这一轮没动过任何文件（闲聊 / 问答 / 只读排查）
  if (lastPass && lastPass === hash) process.exit(0)

  const report = buildReport({ full: false })
  const failed = report.checks.filter((ch) => ch.ok === false)

  if (!failed.length) {
    writeState(null, hash)
    process.exit(0)
  }

  const reason = [
    '本轮改动了文件，但完成自检未通过，不能就此收尾。',
    '',
    ...failed.map((ch) => `· ${ch.name}${ch.detail ? '\n  ' + ch.detail.split(/\r?\n/).slice(0, 4).join('\n  ') : ''}`),
    '',
    '处理方式：修掉上面的问题，跑 `node scripts/agent-done-check.mjs` 直到通过；',
    '改过前端或后端还要加 --full 跑构建与测试。',
    '若确实存在无法自行解决的阻塞（需要授权、不可逆操作、须由人决定），',
    '把进度写进 .agent-work/tasks/active/<任务>.md 并明确告诉用户卡在哪，再收尾。',
  ].join('\n')

  process.stdout.write(JSON.stringify({ decision: 'block', reason }) + '\n')
  process.exit(0)
}

function statusMode() {
  const changes = collectChanges()
  const hash = diffHash()
  console.log(`指纹        ${hash}`)
  console.log(`上次通过    ${readState() || '(无记录)'}`)
  console.log(`pytest 基线 ${parseBaseline().size} 条`)
  console.log(`状态目录    ${STATE_DIR}`)
  console.log(`变更        ${changes.files.length} 个文件`)
  for (const f of changes.files.slice(0, 40)) console.log(`  ${f.code} ${f.path}`)
  if (changes.files.length > 40) console.log(`  …还有 ${changes.files.length - 40} 个`)
  process.exit(0)
}

function updateBaseline() {
  const myappRoot = join(ROOT, MYAPP)
  const pytest = python(['-m', 'pytest', 'tests', '-q'], myappRoot, 900_000)
  const ids = [...parsePytest(pytest.stdout + '\n' + pytest.stderr)].sort()
  writeState('baseline', formatBaseline(ids))

  console.log(`✓ pytest 基线已记录 ${ids.length} 条，写入 TMP/agent-done-check/baseline.txt（不入库）`)
  console.log('')
  console.log('  ⚠ 基线只该记录「改动前就已经红」的用例。')
  console.log('    把本次改动导致的失败记进来，等于自己给自己发免死金牌。')
  for (const id of ids.slice(0, 20)) console.log(`    ${id}`)
  process.exit(0)
}

function main() {
  const args = process.argv.slice(2)
  if (args.includes('--hook')) return hookMode()
  if (args.includes('--status')) return statusMode()
  if (args.includes('--update-baseline')) return updateBaseline()

  const full = args.includes('--full')
  const report = buildReport({ full })
  const ok = printReport(report)

  if (args.includes('--json')) {
    console.log(JSON.stringify({ hash: report.hash, ok, checks: report.checks }, null, 2))
  }

  // 通过后记录指纹 —— Stop 钩子靠它区分「动过」和「没动过」
  if (ok) writeState(null, report.hash)

  process.exit(ok ? 0 : 1)
}

main()
