#!/usr/bin/env node
/**
 * check-v3-team-i18n.mjs —— V3 团队门户国际化一致性守卫
 *
 * 为什么单独写一份（2026-11-06）：
 *   仓库已有 check-i18n.mjs，但它只扫 `src/`（React 统一门户），完全看不到
 *   `v3/team_portal/assets/team-*.js` 这些**纯静态脚本**。团队门户的文案散在
 *   三处自有字典里，且 Auto Report 的 Report Type 列根本不是前端文案 ——
 *   它是 my_app 后端 /api/email-reports/latest 返回的 task_name / label，
 *   后端按 **Accept-Language 请求头**决定给中文还是英文。
 *
 *   实测事故：团队门户裸 fetch 没带这个头，浏览器自动带的是**系统语言**，
 *   于是英文界面下 Report Type 整列中文；同时面板外壳只在首次渲染时生成，
 *   点 EN/中文 后表头永远停在首屏那门语言。两处都不会报错、都不会露 key，
 *   只有切到英文才看得见 —— 与 check-i18n.mjs 注释里写的那类隐蔽故障同源。
 *
 * 检查项（任一失败 → 退出码 1）：
 *   [1] team-panels.js / team-login.js 的 I18N 字典 zh/en 键对称，en 值不含中文
 *   [2] 报告请求必须带 Accept-Language（前端 ↔ 后端 _req_lang 的契约）
 *   [3] 语言切换必须重建外壳 + 作废旧语言数据重拉（shellLang / loaded=false）
 *   [4] 团队专有脚本的界面字面量不得硬编码中文（title="中文" / >中文<）
 *   [5] 登录页 <title> 走 i18n
 *   [6] 可选：my_app 的 _SOURCES 每个报告源都有不含中文的 label_en；
 *       并确认后端仍从 Accept-Language 取语言（前端修法依赖这个契约）。
 *       取不到 my_app 源码时打印 INFO 跳过，不判失败 —— 门户仓库不硬依赖它。
 *
 * 零第三方依赖（只用 node:fs / node:path），Windows 与 CI 的 Linux 都能跑。
 * 用法：node scripts/check-v3-team-i18n.mjs  或  npm run check:v3-i18n
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const CJK = /[\u4e00-\u9fff]/
const problems = []
const notes = []
const fail = (msg) => problems.push(msg)
const note = (msg) => notes.push(msg)
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8')

const V3 = 'v3/team_portal/assets/'
const FILES = {
  panels: V3 + 'team-panels.js',
  layout: V3 + 'team-layout.js',
  login: 'v3/team-login.js'
}
const SRC = {}
for (const [k, rel] of Object.entries(FILES)) {
  const p = path.join(ROOT, rel)
  if (!fs.existsSync(p)) {
    console.error(`[v3-i18n] 取不到真相源 ${rel} —— 守卫无法判定，按失败处理`)
    process.exit(1)
  }
  SRC[k] = read(rel)
}

/** 从 `var <marker> = { ... }` 抽出**完整对象字面量**（字符串/注释感知），
 *  再用 Function 求值，比逐行正则稳：字典值里出现引号、逗号都不会误判。 */
function objectLiteral(src, marker) {
  const i = src.indexOf(marker)
  if (i < 0) return null
  const s = src.indexOf('{', i + marker.length)
  if (s < 0) return null
  let depth = 0, quote = null, esc = false
  for (let p = s; p < src.length; p++) {
    const c = src[p], n = src[p + 1]
    if (quote) {
      if (esc) { esc = false; continue }
      if (c === '\\') { esc = true; continue }
      if (c === quote) quote = null
      continue
    }
    if (c === '/' && n === '/') {
      const e = src.indexOf('\n', p)
      p = e < 0 ? src.length : e
      continue
    }
    if (c === '/' && n === '*') {
      const e = src.indexOf('*/', p + 2)
      p = e < 0 ? src.length : e + 1
      continue
    }
    if (c === "'" || c === '"' || c === '`') { quote = c; continue }
    if (c === '{') depth++
    else if (c === '}') {
      depth--
      if (depth === 0) return src.slice(s, p + 1)
    }
  }
  return null
}

/** 去掉块注释与行注释，用于「界面硬编码中文」扫描，避免注释里的中文误报 */
const stripComments = (s) => s
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(^|[^:])\/\/[^\n]*/g, '$1')

console.log('─'.repeat(70))
console.log('V3 团队门户 i18n 一致性检查')
console.log('─'.repeat(70))

// ------------------------------------------------------- [1] 字典对称 / en 无中文
for (const [name, key] of [['team-panels.js（Auto Report / Complaint）', 'panels'],
                           ['team-login.js（登录页）', 'login']]) {
  const lit = objectLiteral(SRC[key], 'var I18N =')
  if (!lit) { fail(`${name}：定位不到 var I18N = { … } —— 结构变了？`); continue }
  let dict
  try { dict = Function('"use strict"; return (' + lit + ');')() } catch (e) {
    fail(`${name}：I18N 对象字面量无法求值：${e.message}`)
    continue
  }
  const zh = Object.keys(dict.zh || {}), en = Object.keys(dict.en || {})
  const onlyZh = zh.filter((k) => !en.includes(k)).sort()
  const onlyEn = en.filter((k) => !zh.includes(k)).sort()
  if (onlyZh.length) fail(`${name}：${onlyZh.length} 个键只有 zh（英文界面回落中文）：${onlyZh.join(', ')}`)
  if (onlyEn.length) fail(`${name}：${onlyEn.length} 个键只有 en（中文界面露 key 原文）：${onlyEn.join(', ')}`)
  const stillZh = en.filter((k) => CJK.test(String(dict.en[k])))
  if (stillZh.length) {
    fail(`${name}：${stillZh.length} 个 en 值仍是中文（加了键没翻译）：` +
      stillZh.map((k) => `      - ${k} = ${String(dict.en[k]).slice(0, 40)}`).join('\n'))
  }
  console.log(`  ${name.padEnd(42)} zh=${zh.length}  en=${en.length}`)
}

// -------------------------------------- [2][3][5] 前端 ↔ 后端语言契约 / 重绘
const panels = SRC.panels
const cleanPanels = stripComments(panels)
if (!/Accept-Language/.test(cleanPanels) || !/reportHeaders\(\)/.test(cleanPanels)) {
  fail('team-panels.js：报告请求没有带 Accept-Language 头（my_app 的 _req_lang() 只读这个头，' +
       '浏览器自动带的是系统语言 → 英文界面下 Report Type 整列中文）')
}
if (!/shellLang/.test(cleanPanels) || !/reportState\.loaded\s*=\s*false/.test(cleanPanels)) {
  fail('team-panels.js：语言切换时没有「重建外壳 + 作废旧语言 rows 重拉」' +
       '（表头会停在首屏语言、报告名会停在旧语言）')
}
if (!/lang\(\)\s*!==\s*reportState\.lang/.test(cleanPanels)) {
  fail('team-panels.js：缺少「请求在途时切换语言 → 丢弃旧结果并重新取数」的兜底')
}
if (!/esc\(t\('refresh'\)\)/.test(cleanPanels) || !/esc\(t\('loading'\)\)/.test(cleanPanels)) {
  fail('team-panels.js：刷新按钮 / 加载提示应走 t(\'refresh\') / t(\'loading\')，' +
       '不要复用 t(\'colDownload\')（曾把「下载」显示在加载中）')
}
if (!/document\.title\s*=\s*T\.title/.test(stripComments(SRC.login))) {
  fail('team-login.js：<title> 没有走 i18n（英文态浏览器标签仍显示中文）')
}

// ------------------------------------------- [4] 界面字面量不得硬编码中文
const layoutClean = stripComments(SRC.layout)
const hardCoded = []
layoutClean.split(/\r?\n/).forEach((line, i) => {
  if (/^\s*(\/\/|\*|\/\*)/.test(line)) return
  for (const m of line.matchAll(/title=\\?["']([^"']*[\u4e00-\u9fff][^"']*)\\?["']/g)) {
    hardCoded.push(`${FILES.layout}:${i + 1} title="中文" → ${m[1].slice(0, 30)}`)
  }
  for (const m of line.matchAll(/>([^<>{}]*[\u4e00-\u9fff][^<>{}]*)</g)) {
    hardCoded.push(`${FILES.layout}:${i + 1} >中文< → ${m[1].slice(0, 30)}`)
  }
})
if (hardCoded.length) {
  fail(`team-layout.js 有 ${hardCoded.length} 处界面硬编码中文（英文界面会漏中文）：\n` +
    hardCoded.slice(0, 12).map((x) => '      - ' + x).join('\n'))
}
if (!/function paintHandles\(/.test(layoutClean) || !/paintHandles\(\)/.test(layoutClean)) {
  fail('team-layout.js：手柄文案改完后没有重绘出口（语言切换时 html[lang] 变化不会更新手柄）')
}

// -------------------------------- [6] 可选：my_app 报告源译文 + 语言契约
const backend = path.join(ROOT, '..', 'Task', 'my_app', 'backend', 'routers', 'email_reports.py')
if (!fs.existsSync(backend)) {
  note('未找到 ../Task/my_app/backend/routers/email_reports.py，跳过后端报告源译文对账（门户仓库不硬依赖 my_app）')
} else {
  const py = fs.readFileSync(backend, 'utf8')
  if (!/accept\.startswith\(["']en["']\)/.test(py)) {
    fail('my_app 的 _req_lang() 不再从 Accept-Language 判定语言 —— team-panels.js 的修法依赖这个契约，' +
         '两边必须同改（否则英文界面又会出现中文报告名）')
  }
  const seg = py.slice(py.indexOf('_SOURCES = ['), py.indexOf('_SOURCE_BY_ID'))
  const ids = [...seg.matchAll(/dict\(id=["']([^"']+)["']/g)].map((m) => m[1])
  const labelsEn = [...seg.matchAll(/label_en=["']([^"']*)["']/g)].map((m) => m[1])
  if (!ids.length) {
    fail('从 email_reports.py 的 _SOURCES 解析到 0 个报告源 —— 真相源取法与代码写法脱节了，按失败处理')
  } else {
    console.log(`  my_app _SOURCES                          源=${ids.length}  label_en=${labelsEn.length}`)
    if (labelsEn.length !== ids.length) {
      fail(`_SOURCES 有 ${ids.length} 个源，但只有 ${labelsEn.length} 个 label_en —— ` +
           '漏配的那个在英文界面会报错或显示中文')
    }
    const zhLabels = labelsEn.filter((v) => CJK.test(v))
    if (zhLabels.length) {
      fail(`_SOURCES 里 ${zhLabels.length} 个 label_en 仍是中文（${zhLabels.slice(0, 3).join(' / ')}）`)
    }
  }
}

// --------------------------------------------------------------- 输出
for (const n of notes) console.log(`  ℹ ${n}`)
if (problems.length) {
  console.log(`\n✗ 发现 ${problems.length} 类问题：\n`)
  problems.forEach((p, i) => console.log(`  [${i + 1}] ${p}\n`))
  console.log('✗ 未通过：修复后重跑 npm run check:v3-i18n')
  process.exit(1)
}
console.log('\n✓ 通过：团队字典 zh/en 对称、报告请求带语言头、切换语言会重绘并重拉、' +
            '界面无硬编码中文，报告源译文齐全。')
