#!/usr/bin/env node
/**
 * check-i18n.mjs —— 门户 i18n 一致性守卫
 *
 * 为什么门户要单独写一份（2026-10-31）：
 *   门户的 t() 与 my_app 不一样：`DICTS[lang][key] ?? zh[key] ?? key`
 *   （见 src/i18n.tsx 的 LanguageProvider）。**只缺 en 不露 key，而是英文界面
 *   直接显示中文** —— 没有报错、没有异常，只有切到英文才看得见，所以能长期无人发现。
 *   更要命的是门户的文案有**两本字典**：界面文案（zh/en）和看板目录数据
 *   （zhDashboard/enDashboard）。后者按 `dash.<id>.title` / `cat.*` / `dept.*` /
 *   `owner.*` / `tag.*` 取键，而键名来自 initialDashboards.ts 的**数据值**。
 *   于是「加一条看板、忘了加英文」是门户最常见的坏法，且 my_app 那种
 *   「扫源码里的 t('字面量')」根本查不到它 —— 键在数据文件里，不在代码里。
 *
 * 检查项（任一失败 → 退出码 1）：
 *   [1] zh / en 界面字典键集合对称 —— 界面文案走 t()：`DICTS[lang][k] ?? zh[k] ?? k`，
 *       所以缺 en = 英文界面显示中文，缺 zh = 中文界面**露 key 原文**，两个方向都有症状。
 *   [2] 看板字典的不对称**只报信息、不判失败**：translateDashboard / translateCategory /
 *       translateDept / translateOwner / translateTag 是 `dict[k] ?? 原值`，没有 zh 兜底，
 *       而原值本身就是中文 —— 「en 有 zh 无」无害，现有 10 个 tag.* 键就是这么写的。
 *   [3] 源码 t('字面量') 与 t(`前缀${…}`) 模板族用到的键，两本界面字典都要有
 *   [4] 错误签名 t(key, { defaultValue })
 *   [5] 界面硬编码中文（App.tsx / components / pages）
 *   [6] **目录数据全覆盖**（门户特有）：initialDashboards.ts 每条看板派生出的键
 *       dash.<id>.title / dash.<id>.desc / cat.<映射后的分类> / dept.* / owner.* / tag.*
 *       在 **enDashboard** 里必须存在。值本身是拉丁文时跳过 —— 回落原值即正确，
 *       为它建键是凭空造工作量。
 *   [7] **反查唯一性**：cat.* / dept.* / owner.* 的 en 值不得重复。
 *       reverseTranslateCategory / Dept / Owner 是**按值反查**的（i18n.tsx 里
 *       `if (value === dept && key.startsWith('dept.'))`），两个键同值时英文态筛选
 *       会认错岗位。这是代码里的真实约束，不是洁癖。
 *   [8] getCatKey 映射表覆盖数据里出现的每一个分类值（漏一行 → 该分类查不到键）
 *   [9] **en 侧的值本身不得还是中文** —— 「键加了、没翻译」比缺键更隐蔽：
 *       字典看起来完整、守卫按旧规则全绿，英文界面却整段中文。唯一豁免是
 *       nav.langTip（语言按钮要显示它切换到的那个语言，en 侧刻意写「切换到中文」）。
 *
 * 取不到真相源时**显式失败**（不静默跳过）—— 门户文档守卫 2026-10-31 就踩过
 * 「正则匹配 0 条 → 检查当作不适用 → 显示 PASS 却什么都没查」的坑。
 *
 * 零第三方依赖（只用 node:fs / node:path），Windows 与 CI 的 Linux 都能跑。
 *
 * 用法：
 *   cd liberia-noc_soc-数据看板统一门户 && node scripts/check-i18n.mjs
 *   或 npm run check:i18n
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const SRC = path.join(ROOT, 'src')
const I18N = path.join(SRC, 'i18n.tsx')
const DASH = path.join(SRC, 'data', 'initialDashboards.ts')

const problems = []
const warnings = []
let exitCode = 0
const fail = (msg) => { exitCode = 1; problems.push(msg) }
const rel = (p) => path.relative(ROOT, p).replace(/\\/g, '/')
const CJK = /[一-鿿]/

// ---------------------------------------------------------------- 读取与切块
for (const [what, p] of [['i18n.tsx', I18N], ['initialDashboards.ts', DASH]]) {
  if (!fs.existsSync(p)) {
    console.error(`[i18n] 取不到真相源：${what}（${p}）—— 守卫无法判定，按失败处理`)
    process.exit(1)
  }
}
const i18nLines = fs.readFileSync(I18N, 'utf8').split(/\r?\n/)
const dashSrc = fs.readFileSync(DASH, 'utf8')

/** 按 `const <名字>: Record<…> = {` 起、到顶格 `};` 止，切出一段字典 */
function block(name) {
  const re = new RegExp(`^const ${name}: Record`)
  const s = i18nLines.findIndex((l) => re.test(l))
  if (s < 0) return null
  let e = s
  for (; e < i18nLines.length; e++) if (/^\};/.test(i18nLines[e])) break
  if (e >= i18nLines.length) return null
  return { start: s + 1, end: e + 1, lines: i18nLines.slice(s, e) }
}

const BLOCKS = { zh: 'zh', en: 'en', zhDash: 'zhDashboard', enDash: 'enDashboard' }
const DICT = {}
for (const [slot, name] of Object.entries(BLOCKS)) {
  const b = block(name)
  if (!b) {
    console.error(`[i18n] 定位不到字典块 const ${name}: Record —— 结构变了？守卫按失败处理`)
    process.exit(1)
  }
  DICT[slot] = b
}

/** 块内的键集合（键一律带引号，与本仓库写法一致） */
const keySetOf = (b) => {
  const s = new Map()
  b.lines.forEach((l, i) => {
    const m = l.match(/^\s*'([^'\n]+)'\s*:/)
    if (m) s.set(m[1], b.start + i)
  })
  return s
}
/** 块内键 → 值（只取单引号值；跨行值不在本检查范围） */
const valueMapOf = (b) => {
  const s = new Map()
  for (const m of b.lines.join('\n').matchAll(/^\s*'([^'\n]+)'\s*:\s*'((?:[^'\\]|\\.)*)'/gm)) s.set(m[1], m[2])
  return s
}

const zh = keySetOf(DICT.zh), en = keySetOf(DICT.en)
const zhD = keySetOf(DICT.zhDash), enD = keySetOf(DICT.enDash)

console.log('─'.repeat(70))
console.log('门户 i18n 一致性检查')
console.log('─'.repeat(70))
console.log(`  界面字典   zh=${zh.size} (i18n.tsx:${DICT.zh.start}-${DICT.zh.end})  en=${en.size} (…:${DICT.en.start}-${DICT.en.end})`)
console.log(`  看板字典   zh=${zhD.size} (…:${DICT.zhDash.start}-${DICT.zhDash.end})  en=${enD.size} (…:${DICT.enDash.start}-${DICT.enDash.end})`)

const listKeys = (arr) => arr.map((k) => `      - ${k}`).join('\n')

// ---------------------------------------------------------- [1][2] 字典对称
const diffA = (a, b) => [...a.keys()].filter((k) => !b.has(k)).sort()
const sym = (a, b, an, bn, side) => {
  const onlyA = diffA(a, b), onlyB = diffA(b, a)
  if (onlyA.length) fail(`${an} 有、${bn} 缺失 ${onlyA.length} 个键（${side}）：\n${listKeys(onlyA)}`)
  if (onlyB.length) fail(`${bn} 有、${an} 缺失 ${onlyB.length} 个键（${side}）：\n${listKeys(onlyB)}`)
}
// 界面字典走的是 t()：`DICTS[lang][key] ?? zh[key] ?? key` —— 两个方向都有真实症状
sym(zh, en, 'zh', 'en', '缺 en → 英文界面回落中文；缺 zh → 中文界面露 key 原文')

/**
 * 看板字典**不适用**上面那条：translateDashboard / translateCategory / translateDept /
 * translateOwner / translateTag 全部是 `dict[key] ?? 原值`（没有中间那本 zh 兜底），
 * 而原值本身就是中文 —— 所以「en 有、zh 没有」在门户完全无害，现有 10 个 tag.* 键
 * 就是这么写的。真正有害的只有「数据值是中文、en 侧没键」，那由 [6] 逐条查。
 * 这里只把不对称的数量当信息报出来，供人工判断要不要补齐。
 */
const dOnlyZh = diffA(zhD, enD), dOnlyEn = diffA(enD, zhD)
if (dOnlyZh.length || dOnlyEn.length) {
  console.log(`  ℹ 看板字典不对称：仅 zh 有 ${dOnlyZh.length} 个、仅 en 有 ${dOnlyEn.length} 个` +
    `（回落原值即正确，不判失败；有害的那类由 [6] 逐条查）`)
}

// ---------------------------------------------------------- 遍历源码
function walk(dir) {
  const out = []
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name)
    if (e.isDirectory()) {
      if (e.name === 'node_modules' || e.name.startsWith('.')) continue
      out.push(...walk(full))
    } else if (/\.(tsx?|jsx?)$/.test(e.name)) {
      if (/(_bak_|\.bak_)/.test(e.name)) continue // 时间戳快照
      if (full === I18N) continue                 // 字典自身不检查
      out.push(full)
    }
  }
  return out
}

const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1')

const used = new Map()
const files = walk(SRC)
for (const file of files) {
  const raw = fs.readFileSync(file, 'utf8')
  const clean = stripComments(raw)
  // [3a] t('字面量')
  for (const m of clean.matchAll(/\bt\(\s*'([^'\n]+)'/g)) {
    if (!used.has(m[1])) used.set(m[1], new Set())
    used.get(m[1]).add(rel(file))
  }
  // [3b] t(`静态前缀${…}`)：字典里同族的键都必须两边都有（同 my_app [1a]）
  for (const m of clean.matchAll(/\bt\(\s*`([^`$\n]*)\$\{/g)) {
    const prefix = m[1]
    if (!prefix) continue
    const family = new Set([...zh.keys(), ...en.keys(), ...zhD.keys(), ...enD.keys()].filter((k) => k.startsWith(prefix)))
    for (const k of family) {
      if (!used.has(k)) used.set(k, new Set())
      used.get(k).add(`${rel(file)} (模板前缀 ${prefix})`)
    }
  }
  // [4] 错误签名
  raw.split(/\r?\n/).forEach((line, i) => {
    if (/^\s*(\/\/|\*|\/\*)/.test(line)) return
    if (/\bt\(\s*['"][^'"]+['"]\s*,\s*\{\s*defaultValue\s*:/.test(line)) {
      fail(`${rel(file)}:${i + 1} 用了错误签名 t(key, { defaultValue })：t() 的第二参数是插值参数，`
        + `键不存在时原样返回键名（或回落 zh）。改法：把键补进 zh 与 en 两处。\n      > ${line.trim()}`)
    }
  })
  // [5] 界面硬编码中文
  if (/[\\/](pages|components)[\\/]/.test(file) || file === path.join(SRC, 'App.tsx')) {
    raw.split(/\r?\n/).forEach((line, i) => {
      if (/^\s*(\/\/|\*|\/\*)/.test(line)) return
      const jsx = (line.match(/>\s*([^<>{}]*[一-鿿][^<>{}]*?)\s*</) || [])[1]
      const attr = (line.match(/\b(aria-label|title|label|placeholder|tooltip|description|message|content|emptyText|okText|cancelText)\s*[:=]\s*['"]([^'"]*[一-鿿][^'"]*)['"]/) || [])[2]
      const hit = jsx || attr
      if (hit) fail(`${rel(file)}:${i + 1} 界面硬编码中文「${hit.trim().slice(0, 40)}」，应走 t()：\n      > ${line.trim().slice(0, 120)}`)
    })
  }
}

// ---------------------------------------------------------- [3] 用到的键在不在
const missBoth = [], missEn = [], missZh = []
for (const [k, where] of used) {
  const inZh = zh.has(k) || zhD.has(k), inEn = en.has(k) || enD.has(k)
  const at = [...where].join(', ')
  if (!inZh && !inEn) missBoth.push(`      - ${k}   ← ${at}`)
  else if (!inEn) missEn.push(`      - ${k}   ← ${at}`)
  else if (!inZh) missZh.push(`      - ${k}   ← ${at}`)
}
if (missBoth.length) fail(`以下 ${missBoth.length} 个键被代码用到，但 zh / en 都不存在（**界面直接露出 key 原文**）：\n${missBoth.join('\n')}`)
if (missEn.length) fail(`以下 ${missEn.length} 个键被代码用到，但 en 侧不存在（**英文界面显示中文**）：\n${missEn.join('\n')}`)
if (missZh.length) fail(`以下 ${missZh.length} 个键被代码用到，但 zh 侧不存在（**中文界面露出 key 原文**）：\n${missZh.join('\n')}`)

// ---------------------------------------------------------- 目录数据解析
const dashLines = dashSrc.split(/\r?\n/)
const boards = []
let cur = null
dashLines.forEach((l, i) => {
  const id = (l.match(/\bid:\s*'([^']+)'/) || [])[1]
  if (id) { cur = { id, line: i + 1 }; boards.push(cur); return }
  if (!cur) return
  for (const f of ['title', 'description', 'category', 'department', 'owner', 'updateFrequency']) {
    const v = (l.match(new RegExp(`^\\s*${f}:\\s*'([^']*)'`)) || [])[1]
    if (v !== undefined) cur[f] = v
  }
  const tg = l.match(/^\s*tags:\s*\[([^\]]*)\]/)
  if (tg) cur.tags = [...tg[1].matchAll(/'([^']+)'/g)].map((m) => m[1])
})
if (!boards.length) {
  console.error('[i18n] 从 initialDashboards.ts 解析到 0 条看板 —— 真相源取不到，按失败处理（不要当「不适用」跳过）')
  process.exit(1)
}

// getCatKey 映射表（中文分类 → 键后缀）
const catMapSrc = (() => {
  const s = i18nLines.findIndex((l) => /const getCatKey/.test(l))
  if (s < 0) return null
  const e = i18nLines.findIndex((l, i) => i > s && /^\s*const map:/.test(l))
  if (e < 0) return null
  const stop = i18nLines.findIndex((l, i) => i > e && /^\s*\};/.test(l))
  return i18nLines.slice(e, stop < 0 ? i18nLines.length : stop + 1).join('\n')
})()
if (catMapSrc === null) {
  console.error('[i18n] 定位不到 getCatKey 的 map 表 —— 结构变了？守卫按失败处理')
  process.exit(1)
}
const catMap = new Map([...catMapSrc.matchAll(/'([^']+)'\s*:\s*'([^']+)'/g)].map((m) => [m[1], m[2]]))

// [6] 目录数据 → 键。只要求 **en 侧**存在（回落 `?? 原值`，原值就是中文，zh 侧缺了也无害）
const dataMiss = []
const want = (key, why, idAt) => {
  if (!enD.has(key)) {
    dataMiss.push(`      - ${key}   enDashboard 缺键 → 英文界面显示中文「${why}」${idAt ? `   ← ${idAt}` : ''}`)
  }
}
for (const b of boards) {
  if (b.title && CJK.test(b.title)) want(`dash.${b.id}.title`, '看板标题', `initialDashboards.ts:${b.line}`)
  if (b.description && CJK.test(b.description)) want(`dash.${b.id}.desc`, '看板描述', `initialDashboards.ts:${b.line}`)
  if (b.category) {
    if (!catMap.has(b.category)) {
      dataMiss.push(`      - cat.${b.category}   分类没进 getCatKey 映射表 → 英文界面显示中文   ← initialDashboards.ts:${b.line}`)
    } else {
      want(`cat.${catMap.get(b.category)}`, '分类', `initialDashboards.ts:${b.line}`)
    }
  }
  if (b.department && CJK.test(b.department)) want(`dept.${b.department}`, '部门', `initialDashboards.ts:${b.line}`)
  if (b.owner && CJK.test(b.owner)) want(`owner.${b.owner}`, '负责人', `initialDashboards.ts:${b.line}`)
  for (const t of b.tags || []) if (CJK.test(t)) want(`tag.${t}`, '标签', `initialDashboards.ts:${b.line}`)
}
if (dataMiss.length) {
  fail(`看板目录数据有 ${dataMiss.length} 个派生键在 enDashboard 里不存在（新增看板、改分类/部门/负责人名称后忘了补英文，是最常见的门户 i18n 事故）：\n${[...new Set(dataMiss)].join('\n')}`)
}

// [8] 映射表里有、但 en 字典里没键的分类
for (const [cn, suffix] of catMap) {
  const k = `cat.${suffix}`
  if (!enD.has(k)) fail(`getCatKey 把「${cn}」映射到 ${k}，但 enDashboard 里没这个键 → 英文界面显示中文`)
}

// [9] en 侧的值本身还是中文 —— 这是「键加了、没翻译」的形态，比缺键更隐蔽
const EN_VALUE_HAS_CJK_ALLOWED = new Set([
  'nav.langTip', // en 值刻意写「切换到中文」：语言按钮要显示它切换到的那个语言
])
for (const [name, dict] of [['en', DICT.en], ['enDashboard', DICT.enDash]]) {
  const stillZh = [...valueMapOf(dict)].filter(([k, v]) => CJK.test(v) && !EN_VALUE_HAS_CJK_ALLOWED.has(k))
  if (stillZh.length) {
    fail(`${name} 里 ${stillZh.length} 个键的值仍是中文（加了键没翻译，英文界面看不出任何异常）：\n` +
      stillZh.slice(0, 20).map(([k, v]) => `      - ${k} = ${v.slice(0, 40)}`).join('\n') +
      (stillZh.length > 20 ? `\n      … 其余 ${stillZh.length - 20}` : ''))
  }
}

// [7] 反查唯一性：cat./dept./owner. 的 en 值不得重复
for (const prefix of ['cat.', 'dept.', 'owner.']) {
  const byValue = new Map()
  for (const [k, v] of valueMapOf(DICT.enDash)) {
    if (!k.startsWith(prefix)) continue
    if (!byValue.has(v)) byValue.set(v, [])
    byValue.get(v).push(k)
  }
  for (const [v, keys] of byValue) {
    if (keys.length > 1) fail(`${prefix}* 的 en 值「${v}」被 ${keys.length} 个键共用（${keys.join(' / ')}）：reverseTranslate* 按值反查，英文态筛选会认错`)
  }
}

// ---------------------------------------------------------- 输出
const unusedDash = [...zhD.keys()].filter((k) => !k.startsWith('dash.') && !used.has(k))
  .filter((k) => !boards.some((b) => b.category && catMap.get(b.category) && k === `cat.${catMap.get(b.category)}`))
  .filter((k) => !boards.some((b) => k === `dept.${b.department}` || k === `owner.${b.owner}` || (b.tags || []).some((t) => k === `tag.${t}`)))
  .sort()
console.log(`  代码引用到的键 : ${used.size}`)
console.log(`  看板条目       : ${boards.length}（分类映射表 ${catMap.size} 条）`)
if (unusedDash.length) console.log(`  ℹ 看板字典里未被数据引用的键 ${unusedDash.length} 个（清理候选，不影响功能）`)

if (problems.length) {
  console.log(`\n✗ 发现 ${problems.length} 类问题：\n`)
  problems.forEach((p, i) => console.log(`  [${i + 1}] ${p}\n`))
}
if (warnings.length) {
  console.log(`⚠ 提示 ${warnings.length} 处：\n`)
  warnings.forEach((w) => console.log(`  - ${w}`))
}
console.log(exitCode === 0
  ? '\n✓ 通过：界面字典 zh/en 对称，代码用到的键齐全，56 条看板的标题/描述/分类/部门/负责人/标签在 en 侧都有译文。'
  : '\n✗ 未通过：修复后重跑（已挂进 .githooks/pre-commit 与 CI，见根 AGENTS.md 第四节第 9 条）。')
process.exit(exitCode)
