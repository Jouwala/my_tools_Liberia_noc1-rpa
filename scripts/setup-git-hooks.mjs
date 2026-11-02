#!/usr/bin/env node
/**
 * 安装提交前守卫：把 `core.hooksPath` 指向仓库内的 `.githooks/`。
 *
 * 为什么需要这个（2026-10-31）：
 *   守卫以前只写在 `.git/hooks/pre-commit`，而 `.git/hooks/` **不随仓库分发** ——
 *   换机器 / 克隆一份 / 别人来提交，守卫都不存在。文档里写一百遍「记得改文档」
 *   也没用 —— 靠自觉已经失效过 15 次。
 *
 *   Git 提供了官方的分发方式：`core.hooksPath`。把钩子文件放进仓库的
 *   `.githooks/`，再让 Git 去那里找钩子。`core.hooksPath` 本身是**本地配置**
 *   （写在 `.git/config`，不入库），所以每台机器克隆后跑一次本脚本即可。
 *
 * 用法：
 *   node scripts/setup-git-hooks.mjs           # 安装
 *   node scripts/setup-git-hooks.mjs --check   # 只检查，不改配置
 *   node scripts/setup-git-hooks.mjs --uninstall
 *
 * 无第三方依赖（只用 Node 内置模块 + git CLI）。
 */

import { spawnSync } from 'node:child_process'
import { existsSync, lstatSync, mkdirSync, realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join, relative, resolve } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const HOOKS_DIR = '.githooks'
const isWin = process.platform === 'win32'

/** git 命令一律在**调用者当前目录**执行 —— 否则在 worktree 里跑本脚本时，
 *  会去查主仓库的状态，而 Git 实际找钩子的位置是当前工作树根目录。
 *  两者不一致会让 `--check` 报「已启用」，实际钩子却静默不执行。 */
function git(args, opts = {}) {
  return spawnSync('git', args, { cwd: process.cwd(), encoding: 'utf8', shell: false, ...opts })
}

/** 当前工作树根目录（worktree 里与主仓库不同） */
function workTreeRoot() {
  const r = git(['rev-parse', '--show-toplevel'])
  return r.status === 0 ? r.stdout.trim() : ROOT
}

/** 是否处于 worktree（.git 是文件而非目录） */
function isWorkTree() {
  const r = git(['rev-parse', '--git-dir'])
  if (r.status !== 0) return false
  const common = git(['rev-parse', '--git-common-dir'])
  if (common.status !== 0) return false
  return r.stdout.trim() !== common.stdout.trim()
}

function currentHooksPath() {
  const r = git(['config', '--get', 'core.hooksPath'])
  return r.status === 0 ? r.stdout.trim() : ''
}

/**
 * 检查 / 重建 AI 工具规则链接。
 *
 * 背景（2026-11-02）：规则真源移到了 `_agents\rules\`（可入库），Qoder 通过
 * `.qoder\rules\` → `_agents\rules\` 的 **junction** 读到同一份文件。
 * 但 `.qoder\` 整个目录被 `.gitignore:129` 挡住，**junction 不随仓库分发** ——
 * 新克隆的机器上 `_agents\rules\*` 在、`.qoder\rules\` 不在，Qoder 静默读不到任何规则。
 *
 * 与 `core.hooksPath` 完全同一类问题：**「每台机器做一次」的动作，不做就静默失效**。
 * 所以并进这个脚本，一次装齐。幂等：已经是正确链接就跳过。
 */
function agentRulesLink() {
  const linkDir = join(ROOT, '.qoder', 'rules')
  const targetDir = join(ROOT, '_agents', 'rules')

  if (!existsSync(targetDir)) {
    return { status: 'no-source', detail: `真源目录不存在：${targetDir}` }
  }

  // 用 fs.lstat 判断是不是链接（不用 existsSync —— 失效的链接也返回 false）
  let isLink = false
  try {
    isLink = lstatSync(linkDir).isSymbolicLink()
  } catch {
    /* 不存在 */
  }

  if (isLink) {
    let resolved = ''
    try {
      resolved = realpathSync(linkDir)
    } catch {
      return { status: 'broken', detail: `${linkDir} 是链接但目标不存在` }
    }
    const ok = resolve(resolved).toLowerCase() === resolve(targetDir).toLowerCase()
    return ok
      ? { status: 'ok', detail: `${linkDir} → ${targetDir}` }
      : { status: 'wrong-target', detail: `${linkDir} → ${resolved}（应为 ${targetDir}）` }
  }

  return existsSync(linkDir)
    ? { status: 'real-dir', detail: `${linkDir} 是实体目录（旧布局），需先备份再替换` }
    : { status: 'missing', detail: `${linkDir} 不存在` }
}

/** 建 junction（Windows）。POSIX 上退化为 symlink。 */
function createAgentRulesLink() {
  const linkDir = join(ROOT, '.qoder', 'rules')
  const targetDir = join(ROOT, '_agents', 'rules')

  // `.qoder\` 本身也被 gitignore；建链接前确保父目录在
  mkdirSync(join(ROOT, '.qoder'), { recursive: true })

  const cmd = isWin ? 'cmd' : 'ln'
  const args = isWin
    ? ['/c', 'mklink', '/J', linkDir, targetDir] // /J = junction，不需要管理员权限
    : ['-s', targetDir, linkDir]

  const r = spawnSync(cmd, args, { encoding: 'utf8', shell: false })
  return { ok: r.status === 0, out: `${r.stdout ?? ''}${r.stderr ?? ''}`.trim() }
}

function main() {
  const args = process.argv.slice(2)
  const mode = args.includes('--uninstall')
    ? 'uninstall'
    : args.includes('--check')
      ? 'check'
      : 'install'

  const root = workTreeRoot()
  const hookFile = join(root, HOOKS_DIR, 'pre-commit')
  const inWorkTree = isWorkTree()

  const current = currentHooksPath()

  if (mode === 'check') {
    const link = agentRulesLink()
    const hookOk = current === HOOKS_DIR && existsSync(hookFile)
    if (hookOk) {
      console.log(`✓ 提交前守卫已启用（core.hooksPath = ${HOOKS_DIR}）`)
      console.log(`  钩子文件 = ${relative(root, hookFile)}`)
    }
    if (link.status === 'ok') console.log(`✓ 规则链接正常：${link.detail}`)
    else console.log(`✗ 规则链接异常（${link.status}）：${link.detail}`)

    if (hookOk && link.status === 'ok') return 0

    if (!hookOk) {
      if (current !== HOOKS_DIR) {
        console.log(
          current
            ? `✗ core.hooksPath = ${current}，不是 ${HOOKS_DIR} —— 守卫没有指向仓库内版本`
            : '✗ core.hooksPath 未设置 —— 提交前守卫未启用'
        )
      } else {
        console.log(`✗ core.hooksPath = ${HOOKS_DIR}，但当前工作树里没有 ${HOOKS_DIR}\\pre-commit`)
        if (inWorkTree) {
          console.log('  原因：core.hooksPath 是**相对路径**，Git 按「当前工作树根目录」解析，')
          console.log('        worktree 的分支还没合入含 .githooks/ 的提交 → 钩子静默不执行。')
          console.log('  处置：把 .githooks/ 合进该分支（或从 master 重新拉分支），即可自动生效。')
        }
        console.log('  排查：git rev-parse --show-toplevel  # 看 Git 实际找钩子的位置')
      }
    }
    console.log('  修复：node scripts/setup-git-hooks.mjs')
    return 1
  }

  if (mode === 'uninstall') {
    const r = git(['config', '--unset', 'core.hooksPath'])
    if (r.status !== 0) {
      console.log('core.hooksPath 本来就没设置，无需卸载。')
      return 0
    }
    console.log('✓ 已卸载 core.hooksPath（提交前守卫不再生效）')
    return 0
  }

  // install
  if (!existsSync(hookFile)) {
    console.error(`✗ 找不到 ${relative(root, hookFile)} —— 仓库不完整？`)
    if (inWorkTree) {
      console.error('  提示：你似乎在 worktree 里，而该分支还没合入含 .githooks/ 的提交。')
      console.error('        core.hooksPath 是相对路径，按当前工作树根目录解析；')
      console.error('        在这里设了也指向不存在的目录 → 钩子静默不执行。')
      console.error('  处置：先在主仓库装一次（配置是共享的），并把 .githooks/ 合进本分支。')
    }
    return 2
  }

  const r = git(['config', 'core.hooksPath', HOOKS_DIR])
  if (r.status !== 0) {
    console.error(`✗ 设置 core.hooksPath 失败：${(r.stderr ?? '').trim()}`)
    return 1
  }

  // Git for Windows / Unix 都要求钩子可执行。Windows 上 Git Bash 靠 shebang
  // 识别文件类型，但 +x 位仍要设置，core.fileMode 为 false 时由 Git 自行处理。
  const chmod = spawnSync('chmod', ['+x', hookFile], { shell: false })
  if (chmod.status !== 0) {
    // Windows 上没有 chmod，不是错误
    console.log('（跳过 chmod +x：当前环境无 chmod，Windows 上 Git 不依赖该位）')
  }

  console.log('✓ 提交前守卫已启用')
  console.log(`  core.hooksPath = ${HOOKS_DIR}`)
  console.log(`  钩子文件       = ${relative(root, hookFile)}`)
  console.log('')
  console.log('  守卫内容：门户整洁度 / 团队门户生成物一致性 / 门户文档一致性 / 门户 i18n')
  console.log('            my_app 文档一致性 / my_app i18n 漏键')
  console.log('')
  console.log('  紧急绕过：git commit --no-verify')
  console.log('  CI 兜底  ：.github/workflows/docs-consistency.yml（push/PR 都跑）')

  // ── 规则链接（qoder → _agents/rules）──
  console.log('')
  const before = agentRulesLink()
  if (before.status === 'ok') {
    console.log(`✓ 规则链接已存在：${before.detail}`)
  } else if (before.status === 'real-dir') {
    console.log(`⚠ ${before.detail}`)
    console.log('  处置（会删掉实体目录，先确认里面没有独有的修改）：')
    console.log('    Move-Item .qoder\\rules .qoder\\rules_bak')
    console.log('    node scripts/setup-git-hooks.mjs')
  } else if (before.status === 'wrong-target' || before.status === 'broken') {
    console.log(`⚠ ${before.detail}，尝试重建…`)
    const rm = spawnSync(isWin ? 'cmd' : 'rm', isWin ? ['/c', 'rmdir', join(ROOT, '.qoder', 'rules')] : ['-f', join(ROOT, '.qoder', 'rules')], { shell: false })
    if (rm.status !== 0) console.log('  删除旧链接失败，请手工处理。')
    else handleresult()
  } else if (before.status === 'no-source') {
    console.log(`⚠ ${before.detail} —— 跳过（仓库不完整？）`)
  } else {
    handleresult()
  }

  function handleresult() {
    const r = createAgentRulesLink()
    if (r.ok) console.log(`✓ 规则链接已建立：.qoder\\rules → _agents\\rules（junction，不随 git 分发）`)
    else console.log(`✗ 建链接失败：${r.out || '(无输出)'}`)
  }

  if (inWorkTree) {
    console.log('')
    console.log('  注：你在 worktree 里。core.hooksPath 是共享配置（写在主仓库的 .git/config），')
    console.log('      但路径按**当前工作树根目录**解析 —— 其它 worktree 的分支若还没合入')
    console.log('      .githooks/，在那些 worktree 里钩子会静默不执行（用 --check 可查）。')
  }
  return 0
}

process.exit(main())
