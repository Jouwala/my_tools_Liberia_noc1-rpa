/* ==================== 生成 docs/manual/15-user-help.md ====================
 * 用 rolldown 把 frontend/src/helpMarkdown.ts 打包成可独立执行的模块，
 * 调用 buildHelpMarkdown() 并落盘：
 *   - 默认：docs/manual/15-user-help.md（中文）+ docs/manual/15-user-help-en.md（英文）
 *   - --en：只生成英文版
 * 用法：cd frontend && node scripts/generate-help-doc.mjs [--en]
 * 帮助内容改动后重跑本脚本即可同步本地 MD（内容源：helpContent.ts + helpTaskDocs.ts）。
 * ================================================ */
import { rolldown } from 'rolldown'
import { pathToFileURL } from 'node:url'
import { mkdir, writeFile, rm } from 'node:fs/promises'
import path from 'node:path'

const frontendDir = path.resolve(import.meta.dirname, '..')
const repoRoot = path.resolve(frontendDir, '..')
const distDir = path.join(frontendDir, 'node_modules', '.help-doc-build')
const docsDir = path.join(repoRoot, 'docs', 'manual')
const enOnly = process.argv.includes('--en')

// 1) 打包 helpMarkdown.ts（该模块只依赖 helpContent/helpTaskDocs，无 UI/浏览器依赖）
const bundle = await rolldown({
  input: path.join(frontendDir, 'src', 'helpMarkdown.ts'),
})
const { output } = await bundle.generate({ format: 'esm' })
await mkdir(distDir, { recursive: true })
const bundlePath = path.join(distDir, 'helpMarkdown.mjs')
await writeFile(bundlePath, output[0].code, 'utf8')

// 2) 动态导入打包产物并生成文档
const mod = await import(pathToFileURL(bundlePath).href)
const genDate = new Date().toISOString().slice(0, 10)

if (!enOnly) {
  const zh = mod.buildHelpMarkdown('zh')
  const zhPath = path.join(docsDir, '15-user-help.md')
  await writeFile(zhPath, zh, 'utf8')
  console.log(`zh: ${zhPath} (${(zh.length / 1024).toFixed(1)} kB)`)
}

const en = mod.buildHelpMarkdown('en')
const enPath = path.join(docsDir, '15-user-help-en.md')
await writeFile(enPath, en, 'utf8')
console.log(`en: ${enPath} (${(en.length / 1024).toFixed(1)} kB)`)

// 3) 清理临时打包目录
await rm(distDir, { recursive: true, force: true })
console.log(`生成日期: ${genDate}`)
