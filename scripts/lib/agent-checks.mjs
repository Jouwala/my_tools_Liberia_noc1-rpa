/**
 * Agent 完成自检的检查实现（被 scripts/agent-done-check.mjs 调用）。
 *
 * 拆成独立模块的原因：CLI + 输出 + 钩子判定在一处，检查项在另一处 ——
 * 文件各自都在 AGENTS.md 第三节原则 2 的 500 行上限内，且以后加检查项不需要
 * 碰 CLI 与钩子逻辑（反之亦然）。
 *
 * 零第三方依赖（Node 内置模块 + git CLI）。
 */

import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const SELF_DIR = dirname(fileURLToPath(import.meta.url))
export const ROOT = resolve(SELF_DIR, '..', '..')

const isWin = process.platform === 'win32'
export const PORTAL = 'liberia-noc_soc-数据看板统一门户'
export const MYAPP = 'Task/my_app'

/** 证据目录：TMP/ 已被根 .gitignore 覆盖（:135），随时可重建，不入库 */
export const STATE_DIR = join(ROOT, 'TMP', 'agent-done-check')
const HASH_FILE = join(STATE_DIR, 'last-pass.txt')
const BASELINE_FILE = join(STATE_DIR, 'baseline.txt')

// ─────────────────────────────────────────────────────────────────────────────
// 执行封装
// ─────────────────────────────────────────────────────────────────────────────

/** 跑一条命令并收集结果。失败不抛异常 —— 由调用方决定如何呈现。 */
function run(cmd, args, cwd, timeoutMs = 300_000) {
  const started = Date.now()
  // Windows 上 npm 是 `npm.cmd`，Node 24 起 spawnSync(..., {shell:false}) 会直接
  // 抛 EINVAL（.cmd 不是可执行文件）。这里传的都是脚本内的字面量、无外部输入，
  // 因此开 shell 是安全的。POSIX 下保持 shell:false。
  const needsShell = isWin && /\.(cmd|bat)$/i.test(cmd)
  const r = spawnSync(cmd, args, {
    cwd,
    encoding: 'utf8',
    shell: needsShell,
    timeout: timeoutMs,
    windowsHide: true,
    maxBuffer: 32 * 1024 * 1024,
  })
  return {
    ok: r.status === 0,
    status: r.status,
    stdout: (r.stdout ?? '').trim(),
    stderr: (r.stderr ?? '').trim(),
    ms: Date.now() - started,
    error: r.error ? String(r.error.message) : '',
  }
}

const git = (args) => run('git', args, ROOT, 60_000)
const node = (args, cwd) => run(process.execPath, args, cwd)
const python = (args, cwd, timeoutMs) => run('python', args, cwd, timeoutMs)
const npm = (script, cwd, timeoutMs = 900_000) =>
  run(isWin ? 'npm.cmd' : 'npm', ['run', script], cwd, timeoutMs)

export function firstLines(text, n) {
  return (text || '')
    .split(/\r?\n/)
    .filter((l) => l.trim())
    .slice(0, n)
    .join('\n')
}

function statMs(p) {
  try {
    return statSync(p).mtimeMs
  } catch {
    return 0
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 变更收集
// ─────────────────────────────────────────────────────────────────────────────

/** 读取工作区变更。用 -z 分隔，避免中文路径被 git 转义后无法直接比较。 */
export function collectChanges() {
  const r = git(['status', '--porcelain=v1', '-z', '--untracked-files=all'])
  if (!r.ok) return { ok: false, error: r.stderr || r.error, files: [] }

  const files = []
  for (const entry of r.stdout.split('\0')) {
    if (!entry || entry.length < 4) continue
    const code = entry.slice(0, 2)
    const path = entry.slice(3)
    if (!path) continue
    files.push({ code, path: path.replace(/\\/g, '/') })
  }
  return { ok: true, files }
}

/**
 * 差分指纹：对「暂存区 diff + 工作区 diff + 未跟踪文件清单」取哈希。
 *
 * 用途见 CLAUDE 侧说明 —— 本仓库工作区长期有别人在途的改动（实测量级数十个），
 * 所以「工作区脏」不能当作「agent 改过东西」。指纹变了才说明本轮真的动了文件。
 */
export function diffHash() {
  const pieces = []
  for (const [label, args] of [
    ['cached', ['diff', '--cached', '--binary']],
    ['worktree', ['diff', '--binary']],
  ]) {
    const r = git(args)
    if (r.ok) pieces.push(`${label}:${r.stdout}`)
  }
  const untracked = git(['ls-files', '--others', '--exclude-standard', '-z'])
  if (untracked.ok) {
    pieces.push('untracked:' + untracked.stdout.split('\0').filter(Boolean).sort().join('\n'))
  }
  return createHash('sha1').update(pieces.join('\n---\n')).digest('hex')
}

// ─────────────────────────────────────────────────────────────────────────────
// 状态文件
// ─────────────────────────────────────────────────────────────────────────────

export function readState(name) {
  const file = name === 'baseline' ? BASELINE_FILE : HASH_FILE
  try {
    return readFileSync(file, 'utf8').trim()
  } catch {
    return ''
  }
}

export function writeState(name, text) {
  mkdirSync(STATE_DIR, { recursive: true })
  writeFileSync(name === 'baseline' ? BASELINE_FILE : HASH_FILE, text, 'utf8')
}

/**
 * pytest 基线：把「改动前就已经红」的用例记下来，只对新增失败报警。
 *
 * 为什么需要 —— 2026-11-02 实测，本仓库 pytest 在**无人改动时**就有 4 条失败
 * 加 1 条 ERROR（别人在途改动所致）。若要求全绿，任何人都跑不过，守卫立刻
 * 退化成噪声，然后被绕过。这与 pre-commit 刻意不塞构建是同一条经验：
 * **守卫只要开始误伤，就会被绕开。**
 *
 * 基线只用于 pytest，不用于 ruff —— E9/F821 是「执行到那行必然崩」的真缺陷，
 * 没有「本来就该红」的正当理由，而且 ruff 那边改成只查本次改动的文件后
 * 已经不会误伤（见 tier2Checks）。
 *
 * 基线文件落在 TMP/（不入库），因为失败集合因机器与在途改动而异。
 */
export function parseBaseline() {
  return new Set(
    readState('baseline')
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter((s) => s && !s.startsWith('#')),
  )
}

export function formatBaseline(pytestIds) {
  return [
    '# Agent 完成自检的 pytest 基线（TMP/agent-done-check/baseline.txt，不入库）',
    '# 一行一个用例 id。只记录「改动前就已经红」的用例。',
    '# ⚠ 若把本次改动导致的失败记进来，等于给自己发免死金牌。',
    ...pytestIds,
  ].join('\n')
}

// ─────────────────────────────────────────────────────────────────────────────
// 第一档：六道快守卫（与 .githooks/pre-commit 完全同一份代码）
//
// 刻意复用既有脚本而不是重写判定逻辑 —— AGENTS.md 第四节第 5 条「不要新增第二个
// 真相源」。这里只负责「按什么顺序跑、怎么汇总」，判对判错仍是那些脚本说了算。
// ─────────────────────────────────────────────────────────────────────────────

export function tier1Guards() {
  const portalCwd = join(ROOT, PORTAL)
  const myappCwd = join(ROOT, MYAPP)

  const guard = (name, file, fn) => {
    if (!existsSync(file)) return null
    const r = fn()
    return { name, ok: r.ok, detail: r.ok ? '' : firstLines(r.stdout + '\n' + r.stderr, 6), ms: r.ms }
  }

  return [
    guard('门户整洁度', join(portalCwd, 'scripts', 'check-cleanliness.mjs'), () =>
      node(['scripts/check-cleanliness.mjs', 'audit'], portalCwd),
    ),
    guard('团队门户生成物一致性', join(portalCwd, 'scripts', 'check-team-scope.mjs'), () =>
      node(['scripts/check-team-scope.mjs'], portalCwd),
    ),
    guard('门户文档一致性', join(portalCwd, 'scripts', 'check-doc-consistency.mjs'), () =>
      node(['scripts/check-doc-consistency.mjs'], portalCwd),
    ),
    guard('门户 i18n', join(portalCwd, 'scripts', 'check-i18n.mjs'), () =>
      node(['scripts/check-i18n.mjs'], portalCwd),
    ),
    guard('my_app 文档一致性', join(myappCwd, 'tests', 'test_doc_consistency.py'), () =>
      python(['tests/test_doc_consistency.py'], myappCwd, 120_000),
    ),
    guard('my_app i18n', join(myappCwd, 'frontend', 'scripts', 'check-i18n.mjs'), () =>
      node(['scripts/check-i18n.mjs'], join(myappCwd, 'frontend')),
    ),
  ].filter(Boolean)
}

// ─────────────────────────────────────────────────────────────────────────────
// 第二档：按改动路径决定还要检查什么
//
// 只在真正相关的文件被动过时才跑，避免「改一行文档被要求跑构建」这种噪声 ——
// 噪声是守卫被绕过的第一原因。
// ─────────────────────────────────────────────────────────────────────────────

export function tier2Checks(files, { full = false } = {}) {
  const touched = (prefix) => files.some((f) => f.path.startsWith(prefix))
  const list = []

  // ── 后端静态检查：**只查本次改动的 .py 文件** ──────────────────────────
  //
  // 为什么不是 `ruff check backend` 全量 —— 2026-11-02 实测，工作区里躺着别人在途
  // 改动引入的 `soc_trend_sync.py:130 F821 Optional`。全量检查会让**任何人**的自检
  // 都红，与本轮改动无关。守卫只要开始误伤无关的人，就会被绕开（与 pre-commit
  // 刻意不塞构建是同一条经验）。
  //
  // 只查自己改的文件则两头都对：别人在途的缺陷不拦我；我自己新引入的 F821/E9 必拦。
  // 这也让「基线」对 ruff 变得不必要 —— E9/F821 没有「本来就该红」的正当理由。
  const touchedPy = files
    .filter((f) => f.path.startsWith(`${MYAPP}/backend/`) && f.path.endsWith('.py'))
    .filter((f) => existsSync(join(ROOT, f.path)))
    .map((f) => f.path.slice(MYAPP.length + 1).replace(/\//g, '\\'))

  if (touchedPy.length && existsSync(join(ROOT, MYAPP, 'pyproject.toml'))) {
    const r = python(
      ['-m', 'ruff', 'check', '--select', 'E9,F821', '--output-format=concise', '--no-cache', ...touchedPy],
      join(ROOT, MYAPP),
      180_000,
    )
    list.push({
      name: `后端 ruff（本次改动 ${touchedPy.length} 个 .py，E9 + F821）`,
      ok: r.ok,
      detail: r.ok ? '' : firstLines(r.stdout + '\n' + r.stderr, 8),
      ms: r.ms,
      hint: r.ok
        ? ''
        : 'E9 = 语法错误，F821 = 未定义名（执行到那行必然 NameError）。这两类必须真修，不能记进基线。',
    })
  }

  // 前端构建慢，默认只提示；--full 才真跑（真跑时由 fullChecks 负责，这里不重复登记）。
  // 但「未验证」必须显式暴露出来 —— 宁可让 agent 写「未验证」，也不能让它默认「通过」。
  if (!full && touched(`${MYAPP}/frontend/src/`)) {
    list.push({
      name: 'my_app 前端构建（npm run build）',
      ok: null,
      detail: '未执行（快检不跑构建）',
      ms: 0,
      hint: '改前端必须 `cd Task/my_app/frontend && npm run build`（含 check:i18n + tsc），或对本脚本加 --full。',
    })
  }

  // 帮助内容源改过 → 必须重生成文档，否则站内帮助与 MD 不一致（AGENTS.md 三.6）
  const helpSrc = [`${MYAPP}/frontend/src/pages/helpContent.ts`, `${MYAPP}/frontend/src/pages/helpTaskDocs.ts`]
  if (files.some((f) => helpSrc.includes(f.path))) {
    const src = helpSrc.map((p) => join(ROOT, p)).filter(existsSync)
    const gen = [
      `${MYAPP}/docs/manual/15-user-help.md`,
      `${MYAPP}/docs/manual/15-user-help-en.md`,
      `${MYAPP}/frontend/public/manual.html`,
    ]
      .map((p) => join(ROOT, p))
      .filter(existsSync)
    const newestSrc = Math.max(...src.map(statMs))
    const oldestGen = Math.min(...gen.map(statMs))
    const stale = gen.length > 0 && src.length > 0 && newestSrc > oldestGen
    list.push({
      name: '帮助文档重生成（npm run docs）',
      ok: !stale,
      detail: stale ? '生成物比源文件旧，说明改了 TS 却没重跑生成器。' : '',
      ms: 0,
      hint: stale ? '`cd Task/my_app/frontend && npm run docs` 重新生成 15-user-help*.md 与 public/manual.html。' : '',
    })
  }

  return list
}

// ─────────────────────────────────────────────────────────────────────────────
// 第三档：--full，构建 + pytest + 门户 lint
// ─────────────────────────────────────────────────────────────────────────────

export function fullChecks(files) {
  const touched = (prefix) => files.some((f) => f.path.startsWith(prefix))
  const myappFrontend = join(ROOT, MYAPP, 'frontend')
  const myappRoot = join(ROOT, MYAPP)
  const portalCwd = join(ROOT, PORTAL)
  const list = []

  if (touched(`${MYAPP}/frontend/`) && existsSync(join(myappFrontend, 'package.json'))) {
    const r = npm('build', myappFrontend)
    list.push({
      name: 'my_app 前端构建（npm run build）',
      ok: r.ok,
      detail: r.ok ? '' : firstLines(r.stdout + '\n' + r.stderr, 20),
      ms: r.ms,
      hint: r.ok ? '' : 'build = check:i18n + tsc + vite build；产物必须落 Task/_fe_dist，否则后端白屏。',
    })
  }

  if (existsSync(join(myappRoot, 'pyproject.toml'))) {
    const r = python(['-m', 'pytest', 'tests', '-q'], myappRoot, 900_000)
    const current = [...parsePytest(r.stdout + '\n' + r.stderr)]
    const baseline = parseBaseline()
    const introduced = current.filter((id) => !baseline.has(id))
    const fixed = [...baseline].filter((id) => !current.includes(id))
    list.push({
      name: 'my_app pytest（相对基线无新增失败）',
      ok: introduced.length === 0,
      detail:
        introduced.length === 0
          ? baseline.size
            ? `无新增失败；基线内仍有 ${current.length} 条已知失败。${fixed.length ? `本次修好 ${fixed.length} 条，建议 --update-baseline。` : ''}`
            : '全绿'
          : `新增失败 ${introduced.length} 条：\n  ` + introduced.slice(0, 8).join('\n  '),
      ms: r.ms,
      hint:
        introduced.length === 0
          ? ''
          : baseline.size === 0
            ? '尚无基线记录。若确认这些失败不是本次引入的，跑 --update-baseline；否则必须修掉。'
            : '',
    })
  }

  if (touched(`${PORTAL}/`) && existsSync(join(portalCwd, 'package.json'))) {
    const r = npm('lint', portalCwd, 600_000)
    list.push({
      name: '门户 lint（tsc --noEmit）',
      ok: r.ok,
      detail: r.ok ? '' : firstLines(r.stdout + '\n' + r.stderr, 20),
      ms: r.ms,
    })
  }

  return list
}

/** pytest 输出里的失败/错误用例 id（`FAILED path::test` / `ERROR path::test`） */
export function parsePytest(output) {
  const ids = new Set()
  for (const line of output.split(/\r?\n/)) {
    const m = line.match(/^(?:FAILED|ERROR)\s+(\S+)/)
    if (m) ids.add(m[1])
  }
  return ids
}

export { run, python, npm }
