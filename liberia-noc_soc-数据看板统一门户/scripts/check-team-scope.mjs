#!/usr/bin/env node
/**
 * 团队门户生成物与钩子的**一致性守卫**
 * ----------------------------------------------------------------------------
 * 背景：`v3/team_portal/` 的资产是从上游 `v3/olbrportal/` **生成**出来的：
 *   · assets/olbr.js          ← scripts/patch_team_portal.py（打作用域钩子）
 *   · assets/team-matrix.js   ← scripts/gen_team_matrix.py（可见性矩阵）
 *   · assets/team-scope-map.js ← 同上
 *   · 其余共享资产             ← scripts/sync_team_assets.py（同步上游）
 *
 * 这些生成物**都在版本库里** —— 团队门户是静态壳，nginx 直接 alias 发它们，
 * 不经任何构建步骤。于是「改了上游忘了重跑脚本」会直接上线：
 * 症状是团队门户里的功能悄悄消失。
 *
 *   实测（2026-10-30）：上游加了「团队门户」功能（um.team* 的 16 个 i18n 键 +
 *   olbr.js 里的 UM_TEAMS 与团队选择器），而团队门户那份 olbr-data.js / olbr.js
 *   还是改动前的副本 —— 团队门户的「用户管理」面板里**没有团队归属下拉框**，
 *   管理员在团队门户上无法给账号指派团队。这类漂移肉眼极难发现
 *   （两份文件都「看起来对」），故交给机器。
 *
 * 本脚本把四个检查串起来，任一不一致就以非零退出码结束。
 * 挂在 pre-commit 上（见 .git/hooks/pre-commit）。
 *
 * 用法：
 *   node scripts/check-team-scope.mjs
 *
 * 无第三方依赖（本仓库没有 husky/lint-staged，见 AGENTS.md 原则 7）。
 */

import { spawnSync } from 'node:child_process'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(fileURLToPath(new URL('.', import.meta.url)), '..')

/** 四个检查：标签 + 命令 */
const CHECKS = [
  { label: '团队门户 olbr.js 与上游基线一致', args: ['scripts/patch_team_portal.py', '--check'] },
  { label: '可见性矩阵与 scope-map.json 一致', args: ['scripts/gen_team_matrix.py', '--check'] },
  { label: '团队门户共享资产与上游一致', args: ['scripts/sync_team_assets.py', '--check'] },
  { label: '作用域覆盖度对账', args: ['scripts/check_scope_coverage.py'] },
]

/** 找一个能跑 python 的解释器（Windows 上 python 可能不在 PATH） */
function pythonCmd() {
  for (const cmd of ['python', 'python3', 'py']) {
    const r = spawnSync(cmd, ['--version'], { encoding: 'utf-8', shell: false })
    if (r.status === 0) return cmd
  }
  return null
}

function main() {
  const py = pythonCmd()
  if (!py) {
    console.error('✗ 找不到 python —— 团队门户的一致性检查需要它（脚本都是 Python 写的）')
    return 2
  }

  console.log('── 团队门户生成物一致性检查 ──')
  let failed = 0

  for (const check of CHECKS) {
    const r = spawnSync(py, check.args, {
      cwd: ROOT,
      encoding: 'utf-8',
      shell: false,
    })
    const out = `${r.stdout ?? ''}${r.stderr ?? ''}`.trim()
    if (r.status === 0) {
      console.log(`  ✓ ${check.label}`)
    } else {
      failed += 1
      console.log(`  ✗ ${check.label}`)
      if (out) console.log(out.split('\n').map((l) => `      ${l}`).join('\n'))
    }
  }

  if (failed > 0) {
    console.error(`\n✗ ${failed} 项检查未通过。处理办法：`)
    console.error('  跑对应的生成脚本，把生成物重新生成后再提交：')
    console.error('    python scripts/patch_team_portal.py     # 团队门户 olbr.js')
    console.error('    python scripts/gen_team_matrix.py        # 可见性矩阵')
    console.error('    python scripts/sync_team_assets.py       # 共享资产')
    console.error('  若「作用域覆盖度对账」报错，说明上游新增了内容容器但没登记到')
    console.error('  v3/team_portal/block-manifest.json —— 详见报错里的三条处理办法。')
    return 1
  }

  console.log('✓ 团队门户生成物全部与上游一致')
  return 0
}

process.exit(main())
