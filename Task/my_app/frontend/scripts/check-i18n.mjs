#!/usr/bin/env node
/**
 * check-i18n.mjs —— i18n 一致性守卫
 *
 * 背景（为什么需要它）：
 *   2026-09-22 发现 NocAnalyst 页面的「刷新」按钮在界面上显示成字面量 `qa.refresh`。
 *   根因是 `t('qa.refresh', { defaultValue: '刷新' })`：
 *     1. `qa.refresh` 键在 zh/en 两份字典里都不存在；
 *     2. `t(key, params)` 的第二个参数是**插值参数**，不是 options 对象 ——
 *        传 `{ defaultValue }` 不会生效，`t()` 最终原样返回 key 本身；
 *     3. 于是用户看到的就是 `qa.refresh` 这串英文。
 *
 *   这类"键名写错/漏加字典/用错 t() 签名"的问题，TypeScript 查不出来
 *   （t() 的 key 是 string，不是联合类型），构建也不报错，只有切到界面上才会肉眼发现。
 *   本脚本把这类问题变成**可自动检测的构建前检查**。
 *
 * 检查项：
 *   [1] 页面里 t('xxx') 用到的键，是否在 zh 与 en **两份**字典都存在（漏一份 → 英文界面露 key）
 *   [1b] `labelKey: 'xxx'` 形式的**间接引用**同样纳入 [1] 的检查范围（2026-10-06 补，见下）
 *   [2] 是否用了 `t(key, { defaultValue: ... })` 这种**错误签名**（t 的第二参数是插值参数）
 *   [3] 硬编码中文界面字面量（应走 t()）
 *   [4] zh/en 键集合差异（任一侧多出或缺失）
 *
 * 为什么有 [1b]：
 *   全部 ~80 个侧栏标签**不写** t('nav.xxx')，而是把键名放进 PAGE_META / DEFAULT_GROUPS /
 *   FINEBI_BOARDS 的 labelKey 字段，再由 t(PAGE_META[k].labelKey) 这种**变量调用**取用。
 *   只匹配 t('字面量') 时这批键全部落在守卫视野之外 —— 2026-10-06 的 `nav.warehouseSummary`
 *   漏键就是这样逃过构建、直到界面上露出 key 原文才被发现。
 *   实测这些 labelKey 全是静态字面量（无 `labelKey: someVar`），因此可以静态提取，不需要真做变量分析。
 *
 * 用法：
 *   cd frontend && node scripts\check-i18n.mjs
 *   退出码 0 = 通过；1 = 有问题（可挂到 CI / 提交前钩子）
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SRC = path.resolve(__dirname, '..', 'src')
const I18N = path.join(SRC, 'i18n.tsx')

const problems = []
const warnings = []
let exitCode = 0

const rel = (p) => path.relative(path.resolve(__dirname, '..'), p).replace(/\\/g, '/')

// ---------------------------------------------------------------- 读取字典
if (!fs.existsSync(I18N)) {
  console.error(`[i18n] 找不到字典文件：${I18N}`)
  process.exit(1)
}
const i18nSrc = fs.readFileSync(I18N, 'utf8')

// 粗切 zh / en 两段：以第一个顶层 `en: {` 为界
const enMarker = i18nSrc.search(/\n\s{2}en\s*:\s*\{/)
if (enMarker < 0) {
  console.error('[i18n] 无法在 i18n.tsx 中定位 en 字典（预期出现 `  en: {`）')
  process.exit(1)
}
const zhSrc = i18nSrc.slice(0, enMarker)
const enSrc = i18nSrc.slice(enMarker)

/** 把源码里的注释去掉，避免注释中的 t('...') 被误判为真实调用 */
function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '') // 块注释
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1') // 行注释（避开 http:// 这类）
}

/** 抽取某段源码里的键集合 */
function extractKeys(src) {
  const keys = new Set()
  // 匹配  'some.key': value   （键必须带引号，符合本仓库既有写法）
  for (const m of src.matchAll(/^\s*'([^'\n]+)'\s*:/gm)) keys.add(m[1])
  return keys
}

const zhKeys = extractKeys(zhSrc)
const enKeys = extractKeys(enSrc)

// ------------------------------------------------- [4] 两份字典的键集合是否一致
const onlyZh = [...zhKeys].filter((k) => !enKeys.has(k)).sort()
const onlyEn = [...enKeys].filter((k) => !zhKeys.has(k)).sort()

if (onlyZh.length) {
  exitCode = 1
  problems.push(
    `zh 有、en 缺失的键 ${onlyZh.length} 个（英文界面会露出 key 原文）：\n` +
      onlyZh.map((k) => `      - ${k}`).join('\n')
  )
}
if (onlyEn.length) {
  exitCode = 1
  problems.push(
    `en 有、zh 缺失的键 ${onlyEn.length} 个（中文界面会露出 key 原文）：\n` +
      onlyEn.map((k) => `      - ${k}`).join('\n')
  )
}

// ------------------------------------------------- 遍历源码文件
function walk(dir) {
  const out = []
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name)
    if (e.isDirectory()) {
      if (e.name === 'node_modules' || e.name.startsWith('_myapp_trash')) continue
      out.push(...walk(full))
    } else if (/\.(tsx?|jsx?)$/.test(e.name)) {
      if (/_bak_|\.bak_/.test(e.name)) continue // 跳过时间戳备份
      if (full === I18N) continue // 字典自身不检查
      out.push(full)
    }
  }
  return out
}

/**
 * 模板页 `_TemplatePage.tsx` 是**可复制骨架**，其 `tpl.*` 键按设计就不在字典里 ——
 * 复制者要把前缀改成自己的（见该文件头部第 2 步）。因此这里单独列出豁免，
 * 但要检查「复制后忘了改前缀」的情况：若 `tpl.*` 键出现在**非模板文件**里，那是真问题。
 */
const TEMPLATE_FILE = path.join(SRC, 'pages', '_TemplatePage.tsx')
const TEMPLATE_KEY_PREFIX = /^tpl\./

const files = walk(SRC)
const usedKeys = new Map() // key -> Set<相对文件名>
const leftoverTpl = [] // 非模板文件里残留的 tpl.* 键

for (const file of files) {
  const raw = fs.readFileSync(file, 'utf8')
  const src = stripComments(raw) // 注释里的 t('...') 不算真实调用
  const lines = raw.split(/\r?\n/) // 报错行号仍按原文计

  // ---------------------------------------- [1] 收集 t('...') 用到的键
  for (const m of src.matchAll(/\bt\(\s*'([^'\n]+)'/g)) {
    const key = m[1]
    if (!usedKeys.has(key)) usedKeys.set(key, new Set())
    usedKeys.get(key).add(rel(file))
  }

  // -------------------- [1a] 收集模板调用 t(`prefix.${expr}`) 的**全部候选键**
  // 背景（2026-10-19 补）：上一条正则只认单引号字面量，于是
  //   t(`ttwo.milestoneEn.${g.key}`) 这种模板调用**完全逃过检查** ——
  // 实测漏掉了 milestoneEn.leaveSite / milestoneCn.leaveSite 两个键，
  // build 全绿、界面上却直接露出 `ttwo.milestoneEn.leaveSite` 原文。
  //
  // 做法：抽出静态前缀（如 `ttwo.milestoneEn.`），把它与字典里同前缀的键
  // 求交集 —— 凡是在字典里出现过的同族键，都必须**两本字典都有**。
  // 局限：只能校验「字典里已存在的同族键」，无法凭空推断一个都没出现过的键；
  // 覆盖不到时靠 tmplPrefixes 的提示行让人工确认。
  for (const m of src.matchAll(/\bt\(\s*`([^`$\n]*)\$\{/g)) {
    const prefix = m[1]
    if (!prefix) continue
    // 取两本字典的并集：任一侧出现过的同族键都要求「两边都有」
    const family = new Set()
    for (const k of zhKeys) if (k.startsWith(prefix)) family.add(k)
    for (const k of enKeys) if (k.startsWith(prefix)) family.add(k)
    for (const k of family) {
      if (!usedKeys.has(k)) usedKeys.set(k, new Set())
      usedKeys.get(k).add(`${rel(file)} (模板前缀 ${prefix})`)
    }
  }

  // ------------------------------- [1b] 收集 labelKey: '...'（间接引用的文案键）
  // 背景（2026-10-06 补）：侧栏/页面标题不写 t('nav.xxx')，而是把键名放进
  // PAGE_META / DEFAULT_GROUPS / FINEBI_BOARDS 的 labelKey 字段，由
  // t(PAGE_META[k].labelKey) 这种**变量调用**取用 —— 上面的 t('字面量') 正则捕不到。
  // 于是 `nav.warehouseSummary` 漏键时本脚本全绿、build 也照样通过，界面上才露出 key 原文。
  // 实测 App.tsx 的 labelKey 全部是静态字面量（无 labelKey: someVar），故可静态提取。
  // ⚠ 只收 labelKey：相邻的 key: 'grp_xxx' 是**内部标识**，按设计不入字典，
  //   一并收集会凭空造出假缺失。
  for (const m of src.matchAll(/\blabelKey\s*:\s*'([^'\n]+)'/g)) {
    const key = m[1]
    if (!usedKeys.has(key)) usedKeys.set(key, new Set())
    usedKeys.get(key).add(`${rel(file)} (labelKey)`)
  }
  // 记录 tpl.* 是否出现在非模板文件（= 复制模板后忘了改前缀）
  if (file !== TEMPLATE_FILE) {
    for (const m of src.matchAll(/\bt\(\s*'(tpl\.[^'\n]+)'/g)) {
      leftoverTpl.push({ key: m[1], where: rel(file) })
    }
  }

  // ---------------------------------------- [2] 错误签名 t(key, { defaultValue })
  lines.forEach((line, i) => {
    if (/^\s*(\/\/|\*|\/\*)/.test(line)) return
    // t('x', { defaultValue: ... })  /  t("x", { defaultValue: ... })
    const bad = line.match(/\bt\(\s*['"][^'"]+['"]\s*,\s*\{\s*defaultValue\s*:/)
    if (bad) {
      exitCode = 1
      problems.push(
        `${rel(file)}:${i + 1} 用了错误签名 t(key, { defaultValue })。\n` +
          `      t() 的第二个参数是**插值参数**（如 { n: 3 } 替换 {n}），不是 options 对象。\n` +
          `      键不存在时 t() 会原样返回 key 字符串，defaultValue 不生效 → 界面露出 key 原文。\n` +
          `      改法：把键补进 i18n.tsx 的 zh 与 en 两处，然后写 t('your.key')。\n` +
          `      > ${line.trim()}`
      )
    }
  })

  // ---------------------------------------- [3] 硬编码中文界面字面量
  // 只查页面/组件里 JSX 文本节点与常见展示型属性，避开注释与中文标点密集的说明文本
  if (/[\\/](pages|components)[\\/]/.test(file)) {
    lines.forEach((line, i) => {
      if (/^\s*(\/\/|\*|\/\*)/.test(line)) return // 注释
      const trimmed = line.trim()
      // JSX 文本节点： >纯中文<  或  >中文…<
      const jsx = line.match(/>\s*([^<>{}]*[\u4e00-\u9fff][^<>{}]*?)\s*</)
      // 展示型属性： title="中文"  label="中文"  placeholder="中文"  tooltip/message
      const attr = line.match(
        /\b(title|label|placeholder|tooltip|description|message|emptyText|okText|cancelText)\s*[:=]\s*['"]([^'"]*[\u4e00-\u9fff][^'"]*)['"]/
      )
      const hit = jsx?.[1] || attr?.[2]
      if (!hit) return
      if (/^\s*[·—\-/、,，。:：|]+$/.test(hit)) return
      // 允许纯符号/单位/中文标点
      if (!/[\u4e00-\u9fff]/.test(hit)) return
      warnings.push(`${rel(file)}:${i + 1}  疑似硬编码中文界面文案：「${hit.trim()}」\n      > ${trimmed}`)
    })
  }
}

// ---------------------------------------- [1] 汇总：用到的键是否都在两份字典里
const missingZh = []
const missingEn = []
for (const [key, where] of usedKeys) {
  // 模板文件的 tpl.* 键按设计不入字典（复制者改前缀），跳过
  if (TEMPLATE_KEY_PREFIX.test(key) && where.size === 1 && where.has(rel(TEMPLATE_FILE))) continue
  if (!zhKeys.has(key) && !enKeys.has(key)) {
    missingZh.push({ key, where, both: true })
  } else if (!zhKeys.has(key)) {
    missingZh.push({ key, where, both: false })
  } else if (!enKeys.has(key)) {
    missingEn.push({ key, where })
  }
}

if (missingZh.length) {
  exitCode = 1
  problems.push(
    `以下 ${missingZh.length} 个键在代码里被 t() 使用，但 zh 字典缺失` +
      `（标 * 的表示 en 也缺失 → 界面会显示 key 原文）：\n` +
      missingZh
        .map(
          (x) =>
            `      - ${x.key}${x.both ? ' *' : ''}   ← ${[...x.where].join(', ')}`
        )
        .join('\n')
  )
}
if (missingEn.length) {
  exitCode = 1
  problems.push(
    `以下 ${missingEn.length} 个键被 t() 使用，但 en 字典缺失（英文界面显示 key 原文）：\n` +
      missingEn.map((x) => `      - ${x.key}   ← ${[...x.where].join(', ')}`).join('\n')
  )
}

if (leftoverTpl.length) {
  exitCode = 1
  problems.push(
    `以下文件残留了模板占位键 tpl.*（复制 _TemplatePage.tsx 后忘了把前缀改成自己的）：\n` +
      leftoverTpl.map((x) => `      - ${x.key}   ← ${x.where}`).join('\n')
  )
}

// ---------------------------------------- 未被任何代码引用的键（仅提示，不失败）
const unused = [...zhKeys].filter((k) => !usedKeys.has(k)).sort()

// ---------------------------------------------------------------- 输出
const line = '─'.repeat(64)
console.log(line)
console.log('my_app i18n 一致性检查')
console.log(line)
console.log(`  扫描源码文件      : ${files.length}`)
console.log(`  zh 字典键数       : ${zhKeys.size}`)
console.log(`  en 字典键数       : ${enKeys.size}`)
console.log(`  代码中 t() 用到的键: ${usedKeys.size}`)
console.log('')

if (problems.length) {
  console.log(`✗ 发现 ${problems.length} 类问题：\n`)
  problems.forEach((p, i) => console.log(`  [${i + 1}] ${p}\n`))
}

if (warnings.length) {
  console.log(`⚠ 疑似硬编码中文 ${warnings.length} 处（需人工确认，多为技术术语可忽略）：\n`)
  warnings.slice(0, 40).forEach((w) => console.log(`  - ${w}`))
  if (warnings.length > 40) console.log(`  … 其余 ${warnings.length - 40} 处省略`)
  console.log('')
}

if (unused.length) {
  console.log(`ℹ 字典里存在但代码未引用的键 ${unused.length} 个（清理候选，不影响功能）：`)
  console.log(`  ${unused.slice(0, 25).join(', ')}${unused.length > 25 ? ` … 等 ${unused.length} 个` : ''}`)
  console.log('')
}

if (exitCode === 0) {
  console.log('✓ 通过：代码用到的所有文案键在 zh / en 两份字典中均存在，且未发现错误签名。')
} else {
  console.log('✗ 未通过：请修复上述问题后重新运行（详见脚本头部注释说明）。')
}

process.exit(exitCode)
