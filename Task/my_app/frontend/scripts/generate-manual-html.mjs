/* ==================== 生成单文件 HTML 手册 ====================
 * 把 docs/manual/ 全部章节合成为一份 带封面/目录/分章分页 的单文件 HTML：
 *   frontend/public/manual.html → 构建后站点直接可访问 /myapp/manual.html
 * 浏览器打开后 Ctrl+P「另存为 PDF」即得分页的 PDF 手册（零 JS 依赖）。
 *
 * 用法：cd frontend && node scripts/generate-manual-html.mjs
 * 内容源：docs/manual/*.md（改 MD 后重跑本脚本 + npm run build 同步站点）。
 * MD→HTML 使用仓库内已有的 micromark + micromark-extension-gfm（表格/删除线等）。
 *
 * ⚠️ 只提交自己那几章时，别在脏工作区直接重跑（2026-10-06 实证）
 * 本脚本读的是**整个** docs/manual/，会把当前工作区里**所有**未提交的 MD 改动
 * 一起烤进产物。若你只想同步自己写的章节，而同事的 12-configuration.md 等
 * 还在在途（未提交），直接重跑就会把**别人的半成品**打进 manual.html 并随你的
 * 提交入库 —— 产物是生成物，diff 里看不出哪句是谁的，事后极难拆。
 * 正确做法：从一个**只含已提交状态**的干净 worktree 生成，再把产物拷回来：
 *     git worktree add ..\_manual_gen_wt HEAD
 *     # 该 worktree 没有 node_modules，用 junction 借用主仓库依赖（只读）
 *     New-Item -ItemType Junction -Path ..\_manual_gen_wt\...\frontend\node_modules `
 *              -Target <主仓库>\frontend\node_modules
 *     cd ..\_manual_gen_wt\...\frontend; node scripts\generate-manual-html.mjs
 *     # 核对产物不含他人未提交的独有字样后，拷回主仓库
 *     git worktree remove ..\_manual_gen_wt --force
 * ================================================ */
import { readFile, writeFile, stat } from 'node:fs/promises'
import path from 'node:path'
import { micromark } from 'micromark'
import { gfm, gfmHtml } from 'micromark-extension-gfm'

const frontendDir = path.resolve(import.meta.dirname, '..')
const repoRoot = path.resolve(frontendDir, '..')
const docsDir = path.join(repoRoot, 'docs', 'manual')
const outPath = path.join(frontendDir, 'public', 'manual.html')

/** 章节清单：按阅读顺序；part 用于封面/目录分组；title 可覆盖文档自带 H1 */
const CHAPTERS = [
  { file: 'README.md', id: 'ch-00', part: 'meta', title: '关于本手册' },
  { file: '01-overview.md', id: 'ch-01', part: 'design' },
  { file: '02-architecture.md', id: 'ch-02', part: 'design' },
  { file: '03-data-layer.md', id: 'ch-03', part: 'design' },
  { file: '04-task-system.md', id: 'ch-04', part: 'design' },
  { file: '05-security-and-credentials.md', id: 'ch-05', part: 'design' },
  { file: '10-quickstart.md', id: 'ch-10', part: 'usage' },
  { file: '11-feature-guide.md', id: 'ch-11', part: 'usage' },
  { file: '12-configuration.md', id: 'ch-12', part: 'usage' },
  { file: '13-operations.md', id: 'ch-13', part: 'usage' },
  { file: '14-integrations.md', id: 'ch-14', part: 'usage' },
  { file: '15-user-help.md', id: 'ch-15', part: 'usage', title: '使用帮助（一站式指南）' },
  { file: '90-appendix.md', id: 'ch-90', part: 'appendix' },
]

const PART_LABELS = {
  meta: '前言',
  design: '设计篇',
  usage: '使用篇',
  appendix: '附录',
}

/** 逐行处理 MD：跳过代码围栏，抽取 h2/h3 小节、降级标题并注入锚点 */
function processChapter(md, chId) {
  const lines = md.split(/\r?\n/)
  const out = []
  const sections = []
  let inFence = false
  let seq = 0
  let h1Title = null
  for (const line of lines) {
    if (/^\s*(```|~~~)/.test(line)) inFence = !inFence
    if (inFence) { out.push(line); continue }
    const h = /^(#{1,6})\s+(.*)$/.exec(line)
    if (h) {
      const level = h[1].length
      let text = h[2].trim()
      if (level === 1) {
        if (h1Title === null) h1Title = text.replace(/`/g, '')
        continue // H1 由章节头渲染，正文里跳过
      }
      // 标题整体降一级：## → ###、### → ####（章节头用 h2）
      const newLevel = Math.min(level + 1, 6)
      const id = `${chId}-s${seq++}`
      sections.push({ id, level: newLevel, text: text.replace(/`/g, '') })
      out.push(`<a id="${id}"></a>`)
      out.push('#'.repeat(newLevel) + ' ' + h[2])
      continue
    }
    out.push(line)
  }
  return { html: micromark(out.join('\n'), { allowDangerousHtml: true, extensions: [gfm()], htmlExtensions: [gfmHtml()] }), sections, title: h1Title }
}

/** 把相对 .md 链接改写为章内锚点 */
function relink(html) {
  const fileToId = new Map(CHAPTERS.map(c => [c.file, `#${c.id}`]))
  return html.replace(/href="([^"#?]+?\.md)(#[^"]*)?"/g, (m, p, anchor) => {
    const base = path.basename(p)
    if (fileToId.has(base)) return `href="${fileToId.get(base)}"`
    return 'href="#"'
  })
}

const chapterHtml = []
const tocByPart = { meta: [], design: [], usage: [], appendix: [] }
const chapterMeta = []

for (const ch of CHAPTERS) {
  const raw = await readFile(path.join(docsDir, ch.file), 'utf8')
  const { html, sections, title } = processChapter(raw, ch.id)
  const chTitle = ch.title ?? title ?? ch.file
  chapterMeta.push({ ...ch, chTitle, sections: sections.filter(s => s.level === 3) })
  for (const s of sections.filter(s => s.level === 3)) tocByPart[ch.part].push({ ...s, chId: ch.id, chTitle })
  chapterHtml.push({ ch, chTitle, body: relink(html) })
}

const genDate = new Date().toISOString().slice(0, 10)
const totalSections = chapterMeta.reduce((n, c) => n + c.sections.length, 0)

/** 目录（含小节） */
function tocHtml() {
  const parts = ['meta', 'design', 'usage', 'appendix'].filter(p => chapterMeta.some(c => c.part === p))
  return parts.map(part => {
    const rows = chapterMeta.filter(c => c.part === part).map(c => {
      const subs = tocByPart[part].filter(s => s.chId === c.id)
        .map(s => `<li><a href="#${s.id}">${esc(s.text)}</a></li>`).join('')
      return `<li><a class="toc-ch" href="#${c.id}">${esc(c.chTitle)}</a>${subs ? `<ul class="toc-sub">${subs}</ul>` : ''}</li>`
    }).join('')
    return `<div class="toc-part"><div class="toc-part-label">${PART_LABELS[part]}</div><ul>${rows}</ul></div>`
  }).join('')
}

function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') }

const body = chapterHtml.map(({ ch, chTitle, body }) => `
<section class="chapter" id="${ch.id}">
  <header class="chapter-head">
    <div class="chapter-part">${PART_LABELS[ch.part]}</div>
    <h2>${esc(chTitle)}</h2>
  </header>
  ${body}
</section>`).join('\n')

const html = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>my_app 项目手册</title>
<style>
:root { --teal: #0d9488; --ink: #1f2937; --muted: #6b7280; --line: #e5e7eb; --bg: #f8fafc; }
* { box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: 24px; }
body { margin: 0; font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif; color: var(--ink); background: var(--bg); line-height: 1.75; font-size: 15px; }
@media (min-width: 1240px) { body { margin-left: 300px; } }
/* ---------- 侧边目录（屏幕） ---------- */
.sidebar { display: none; }
@media (min-width: 1240px) {
  .sidebar { display: block; position: fixed; left: 0; top: 0; bottom: 0; width: 280px; overflow-y: auto; padding: 24px 18px 40px; background: #fff; border-right: 1px solid var(--line); font-size: 13px; }
}
.sidebar h3 { font-size: 14px; color: var(--teal); margin: 0 0 12px; }
.sidebar a { color: var(--ink); text-decoration: none; display: block; padding: 3px 6px; border-radius: 6px; }
.sidebar a:hover { background: #f0fdfa; color: var(--teal); }
.sidebar .toc-part-label { font-weight: 700; color: var(--teal); margin: 14px 6px 4px; font-size: 12px; letter-spacing: .05em; }
.sidebar ul { list-style: none; margin: 0; padding: 0; }
.sidebar .toc-sub { padding-left: 14px; border-left: 1px solid var(--line); margin: 2px 0 6px; }
.sidebar .toc-sub a { color: var(--muted); font-size: 12px; }
/* ---------- 主区 ---------- */
.wrap { max-width: 880px; margin: 0 auto; padding: 32px 20px 80px; }
/* 封面 */
.cover { text-align: center; padding: 90px 20px 70px; page-break-after: always; }
.cover .logo { font-size: 44px; }
.cover h1 { font-size: 34px; margin: 14px 0 6px; color: var(--teal); }
.cover .sub { color: var(--muted); font-size: 15px; }
.cover .meta { margin-top: 26px; color: var(--muted); font-size: 13px; }
.cover .parts { margin-top: 34px; display: inline-block; text-align: left; border: 1px solid var(--line); border-radius: 12px; background: #fff; padding: 18px 30px; }
.cover .parts li { margin: 4px 0; }
/* 目录（可打印） */
.toc-section { background: #fff; border: 1px solid var(--line); border-radius: 12px; padding: 26px 30px; page-break-after: always; }
.toc-section h2 { color: var(--teal); margin-top: 0; }
.toc-section .toc-part-label { font-weight: 700; color: var(--teal); margin: 16px 0 6px; }
.toc-section ul { list-style: none; padding-left: 0; margin: 0; }
.toc-section .toc-ch { font-weight: 600; }
.toc-section a { color: var(--ink); text-decoration: none; }
.toc-section a:hover { color: var(--teal); }
.toc-section .toc-sub { padding-left: 22px; }
.toc-section .toc-sub li { color: var(--muted); font-size: 13px; }
/* 章节 */
.chapter { background: #fff; border: 1px solid var(--line); border-radius: 12px; padding: 30px 36px 40px; margin-bottom: 26px; page-break-before: always; }
.chapter-head { border-bottom: 2px solid var(--teal); padding-bottom: 10px; margin-bottom: 20px; }
.chapter-part { color: var(--teal); font-size: 12px; font-weight: 700; letter-spacing: .1em; }
.chapter-head h2 { margin: 4px 0 0; font-size: 26px; }
h3 { font-size: 20px; margin: 28px 0 10px; padding-left: 10px; border-left: 4px solid var(--teal); }
h4 { font-size: 17px; margin: 22px 0 8px; }
h5, h6 { font-size: 15px; }
a { color: var(--teal); }
blockquote { margin: 12px 0; padding: 8px 16px; border-left: 4px solid var(--teal); background: #f0fdfa; border-radius: 0 8px 8px 0; color: #0f766e; }
code { background: #f1f5f9; border: 1px solid var(--line); border-radius: 4px; padding: 1px 5px; font-size: 13px; font-family: Consolas, "Courier New", monospace; }
pre { background: #0f172a; color: #e2e8f0; border-radius: 8px; padding: 14px 16px; overflow-x: auto; }
pre code { background: none; border: none; color: inherit; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 13.5px; }
th, td { border: 1px solid var(--line); padding: 6px 10px; text-align: left; vertical-align: top; }
th { background: #f0fdfa; color: #0f766e; }
tr:nth-child(even) td { background: #fafafa; }
hr { border: none; border-top: 1px solid var(--line); margin: 24px 0; }
footer.colophon { text-align: center; color: var(--muted); font-size: 12px; margin-top: 40px; }
/* ---------- 打印 / PDF ---------- */
@page { size: A4; margin: 16mm 13mm; }
@media print {
  body { background: #fff; font-size: 12.5px; margin: 0; }
  .sidebar { display: none !important; }
  .wrap { max-width: none; padding: 0; }
  .cover { padding-top: 30mm; }
  .cover h1 { font-size: 30px; }
  .chapter { border: none; border-radius: 0; padding: 0 0 10px; margin: 0; box-shadow: none; }
  .toc-section { border: none; padding: 0; }
  pre { white-space: pre-wrap; word-break: break-all; }
  table { font-size: 11px; }
  th, td { padding: 4px 7px; }
  h3 { page-break-after: avoid; }
  table, blockquote, pre { page-break-inside: avoid; }
}
</style>
</head>
<body>
<nav class="sidebar no-print">
  <h3>📘 my_app 手册</h3>
  ${tocHtml()}
</nav>
<div class="wrap">
  <section class="cover">
    <div class="logo">📘</div>
    <h1>my_app 项目手册</h1>
    <div class="sub">网络运维数据平台 · 设计手册 + 使用手册</div>
    <div class="meta">基准日期 2026-08-27　|　适用版本 master 当前代码　|　HTML 合成生成 ${genDate}<br>含 ${CHAPTERS.length} 章 · ${totalSections} 个小节　|　打印本页（Ctrl+P）即可导出 PDF<br>英文版使用帮助另见仓库 docs/manual/15-user-help-en.md</div>
    <ul class="parts">${chapterMeta.map(c => `<li><a href="#${c.id}">${PART_LABELS[c.part]} · ${esc(c.chTitle)}</a></li>`).join('')}</ul>
  </section>
  <section class="toc-section">
    <h2>目录</h2>
    ${tocHtml()}
  </section>
  ${body}
  <footer class="colophon">my_app 项目手册 · 由 frontend/scripts/generate-manual-html.mjs 从 docs/manual/*.md 同源生成于 ${genDate} · 改 MD 后重跑该脚本并重新构建前端即可更新</footer>
</div>
</body>
</html>
`

await writeFile(outPath, html, 'utf8')
const kb = ((await stat(outPath)).size / 1024).toFixed(1)
console.log(`✔ ${outPath} (${kb} kB, ${CHAPTERS.length} chapters, ${totalSections} sections)`)
