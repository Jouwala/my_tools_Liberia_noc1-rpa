/**
 * 门户文档一致性守卫 —— 手册/README 里的「从代码抄来的数字」必须与代码真相源一致。
 *
 * 为什么需要它（2026-10-31 新增）：
 *   门户文档里的看板条数、组件数、任务数同样在悄悄过期。实测一次审计抓到 3 处：
 *     - README.md 说「21 个 my_app 直链 + 19 个 FineBI 条目」→ 实际 53 + 2 + 1 = 56 条
 *     - README.md 说「my_app 后端 34 个定时任务」→ 实际 80 个
 *     - docs/project-overview.md 说「21 个组件」→ 实际 24 个
 *   症状是「README 说的和界面对不上」，而两边看起来都自洽，肉眼极难发现。
 *
 * 与 my_app 的 `tests/test_doc_consistency.py` 是同一思路、同一套约定：
 *   纯 assert + __main__ 计数器，不依赖 pytest（本机 venv 没装 pytest）。
 *
 * 运行（必须用 PATH 上的 node）：
 *   cd D:/01_RPA/liberia-noc_soc-数据看板统一门户
 *   node scripts/check-doc-consistency.mjs
 */
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { globSync } from 'node:fs'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel) => readFileSync(join(ROOT, rel), 'utf8')
const has = (rel) => existsSync(join(ROOT, rel))

const CHECKS = []
const check = (name, fn) => CHECKS.push([name, fn])

/* ────────────────────── 取代码真相源 ────────────────────── */

function dashboardCounts() {
  const src = read('src/data/initialDashboards.ts')
  const ids = src.match(/^\s*id:\s*'([^']+)'/gm) ?? []
  const platforms = src.match(/^\s*platform:\s*'([^']+)'/gm) ?? []
  const count = (p) => platforms.filter((x) => x.includes(`'${p}'`)).length
  return {
    total: ids.length,
    custom: count('custom'),
    finebi: count('finebi'),
    external: count('external'),
  }
}

function componentCount() {
  return globSync('src/components/**/*.tsx', { cwd: ROOT }).length
}

/** my_app 的定时任务数（门户 README 里引用了它）。
 *  真相源是 my_app 的 task_registry.py —— 这里不引 Python，直接读源文件里的
 *  TASK_SPECS 条目数，避免门户装 Python 依赖。
 *
 *  ⚠️ 2026-10-31 修复：原正则只认 `"task_id": "xxx"` 的字面量写法，
 *  而 task_registry.py 实际写的是 `dict(task_id="xxx", ...)` ——
 *  结果匹配 0 条 → myAppTaskCount() 返回 null → 两个检查走 `if (!n) return`
 *  **静默跳过**，守卫显示 PASS 但实际什么都没查。教训：守卫取不到真相源时
 *  必须显式失败，不能当成「不适用」。 */
function myAppTaskCount() {
  const p = join(ROOT, '..', 'Task', 'my_app', 'backend', 'task_registry.py')
  if (!existsSync(p)) return null
  const src = readFileSync(p, 'utf8')
  const start = src.indexOf('TASK_SPECS')
  if (start < 0) return null
  const seg = src.slice(start, src.indexOf('\n]', start))
  // TASK_SPECS 是 list[dict(...)] 字面量，条目以 `dict(task_id="xxx"` 开头
  const ids = seg.match(/task_id\s*=\s*["'][a-z0-9_]+["']/g) ?? []
  const n = ids.length
  if (!n) {
    throw new Error(
      'task_registry.py 的 TASK_SPECS 解析到 0 条 —— 守卫的真相源取法与代码写法脱节了，' +
      '请修正 myAppTaskCount() 的正则（这不是「不适用」，是守卫自己坏了）'
    )
  }
  return n
}

/* ────────────────────── 各条检查 ────────────────────── */

check('README 的看板条数与 initialDashboards.ts 一致', () => {
  const c = dashboardCounts()
  const doc = read('README.md')
  const m = doc.match(/内置\s*(\d+)\s*个 my_app 真实页面直链/)
  if (!m) throw new Error('README.md 里找不到「N 个 my_app 真实页面直链」的表述（守卫本身失效了？）')
  const claimed = Number(m[1])
  if (claimed !== c.custom) {
    throw new Error(
      `README.md 写 ${claimed} 个 my_app 直链，实际 ${c.custom} 个` +
      `（共 ${c.total} 条 = ${c.custom} custom + ${c.finebi} finebi + ${c.external} external）`
    )
  }
})

check('README 的定时任务数与 my_app TASK_SPECS 一致', () => {
  const n = myAppTaskCount()
  if (!n) return // my_app 不在（单独部署门户）→ 跳过
  const doc = read('README.md')
  const m = doc.match(/my_app 后端\s*(\d+)\s*个定时任务/)
  if (!m) throw new Error('README.md 里找不到「my_app 后端 N 个定时任务」（守卫本身失效了？）')
  const claimed = Number(m[1])
  if (claimed !== n) {
    throw new Error(`README.md 写 ${claimed} 个定时任务，my_app TASK_SPECS 实际 ${n} 个`)
  }
})

check('project-overview 的组件数与 src/components 一致', () => {
  const n = componentCount()
  const doc = read('docs/project-overview.md')
  const m = doc.match(/components\\+\s*#\s*(\d+)\s*个组件/)
  if (!m) throw new Error('docs/project-overview.md 里找不到组件数标注（守卫本身失效了？）')
  const claimed = Number(m[1])
  if (claimed !== n) {
    throw new Error(`docs/project-overview.md 写 ${claimed} 个组件，实际 ${n} 个`)
  }
})

check('看板描述里的定时任务数与 my_app 一致', () => {
  const n = myAppTaskCount()
  if (!n) return
  const src = read('src/data/initialDashboards.ts')
  const m = src.match(/调度全部\s*(\d+)\s*个自动化任务/)
  if (!m) throw new Error('initialDashboards.ts 里找不到任务数（守卫本身失效了？）')
  const claimed = Number(m[1])
  if (claimed !== n) {
    throw new Error(`initialDashboards.ts 的看板描述写 ${claimed} 个自动化任务，实际 ${n} 个`)
  }
})

check('根 component-api.md 的门户组件数与 src/components 一致', () => {
  const n = componentCount()
  // 根目录的 component-api.md 是**工作区级**文档（两个子系统共用一份索引）
  const rootDoc = join(ROOT, '..', 'component-api.md')
  if (!existsSync(rootDoc)) return
  const doc = readFileSync(rootDoc, 'utf8')
  const m = doc.match(/统一门户[^\n]*?\|\s*(\d+)\s*个\s*`\.tsx`/)
  if (!m) throw new Error('根 component-api.md 里找不到门户组件数（守卫本身失效了？）')
  const claimed = Number(m[1])
  if (claimed !== n) {
    throw new Error(`根 component-api.md 写 ${claimed} 个门户组件，实际 ${n} 个`)
  }
})

check('用户指南里带 token 的看板条数与 portal-default.json 一致', () => {
  const p = join(ROOT, 'portal-default.json')
  if (!existsSync(p)) return // 运行时文件，未部署时跳过
  const doc = read('docs/user-guide.md')
  const m = doc.match(/目录里\s*(\d+)\s*条看板中有\s*(\d+)\s*条带它/)
  if (!m) throw new Error('docs/user-guide.md 里找不到 token 条数表述（守卫本身失效了？）')
  const items = JSON.parse(readFileSync(p, 'utf8'))
  const list = Array.isArray(items) ? items : items.dashboards ?? items.items ?? []
  const withTok = list.filter((x) => String(x.url ?? '').includes('&t=') || String(x.url ?? '').includes('?t=')).length
  if (Number(m[1]) !== list.length) {
    throw new Error(`docs/user-guide.md 写 ${m[1]} 条看板，portal-default.json 实际 ${list.length} 条`)
  }
  if (Number(m[2]) !== withTok) {
    throw new Error(`docs/user-guide.md 写 ${m[2]} 条带 token，portal-default.json 实际 ${withTok} 条`)
  }
})

/* ────────────────────── 跑 ────────────────────── */

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  let pass = 0
  let fail = 0
  for (const [name, fn] of CHECKS) {
    try {
      fn()
      console.log(`[PASS] ${name}`)
      pass++
    } catch (e) {
      console.log(`[FAIL] ${name}: ${e.message}`)
      fail++
    }
  }
  console.log(`\nPASS=${pass} FAIL=${fail}`)
  process.exit(fail ? 1 : 0)
}

export { CHECKS }
