#!/usr/bin/env node
/**
 * prune-fe-dist.mjs —— 清理 _fe_dist/assets 下**不再被引用的**陈旧 chunk
 *
 * 背景（2026-10-07）：
 *   vite.config.ts 的 `emptyOutDir: false` 是**刻意**的 —— 本机 safe-delete 钩子会拦截
 *   Vite 的 prepare-out-dir 清空动作导致构建中断。但那处注释写着「改由构建脚本/人工清理
 *   dist2/assets」，而 `package.json` 的 build 里**从来没有这一步**，也没有对应脚本。
 *   于是每次构建都只增不减：实测 assets 已积累 14108 个文件 / 322.8 MB，
 *   单个 chunk 的陈旧副本多达 226 份（hash 变化后旧文件永远留着）。
 *
 *   本脚本把注释里承诺的那一步补上。**它不替代 emptyOutDir**（仍需保持 false），
 *   只是在构建成功后做一次「删除不可达产物」的收尾。
 *
 * 为什么是「可达性」而不是「按时间戳」：
 *   hash 文件名是内容寻址的，构建产物之间靠 import 互相引用。
 *   从 index.html 的入口 chunk 出发做**传递闭包**，就能精确算出本次构建真正需要哪些文件；
 *   其余一律是历史残留。这比「删 N 天前的」安全得多 —— 不会误删仍被引用的老 chunk
 *   （例如内容未变、hash 未变、因此日期很旧的那个分包）。
 *
 * 安全设计：
 *   - **默认干跑**，只打印将删除的数量与体积；加 --apply 才真删。
 *   - 白名单保护：public/ 复制来的静态资产（非 hash 命名，如 alarm-management.html、
 *     lib/leaflet/**）不在 assets 里，本脚本只动 assets/，不碰 outDir 其它目录。
 *   - 只删「形如 name-<8位hash>.js / .css」且不可达的文件；不符合该形状的文件一律保留
 *     （避免误删构建产物之外的东西）。
 *   - 若入口解析失败或可达集为空，**直接放弃并退出 1** —— 宁可不清，也不能把线上目录删空。
 *
 * 用法：
 *   node scripts/prune-fe-dist.mjs              # 干跑，看会删什么
 *   node scripts/prune-fe-dist.mjs --apply      # 真正删除
 *   FE_DIST_OUT=... node scripts/prune-fe-dist.mjs   # 与 vite.config.ts 同一环境变量口径
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT_DIR = process.env.FE_DIST_OUT || 'D:/01_RPA/Task/_fe_dist'
const APPLY = process.argv.includes('--apply')

const INDEX = path.join(OUT_DIR, 'index.html')
const ASSETS = path.join(OUT_DIR, 'assets')

/** 构建产物命名：name-<hash>.js|css|woff2|... 只认带 hash 的这些，其余不碰。 */
const HASHED = /-[A-Za-z0-9_-]{8,}\.(js|css)$/

function die(msg) {
  console.error(`[prune] ${msg}`)
  process.exit(1)
}

if (!fs.existsSync(INDEX)) die(`找不到入口 ${INDEX}（先构建一次）`)
if (!fs.existsSync(ASSETS)) die(`找不到 ${ASSETS}`)

const html = fs.readFileSync(INDEX, 'utf8')

/* 从 index.html 取出所有 /myapp/assets/xxx 形式（<script src> 与 <link href>） */
const entries = new Set()
for (const m of html.matchAll(/(?:src|href)="[^"]*\/assets\/([^"/]+)"/g)) entries.add(m[1])
if (!entries.size) die('index.html 里没解析出任何 assets 引用 —— 拒绝清理')

/* 传递闭包：chunk 之间以相对路径互相 import（如 "./Foo-abc12345.js"）。
   用「文件名」而非完整路径建索引 —— 同一 assets 目录下文件名唯一。 */
const byName = new Map()
for (const f of fs.readdirSync(ASSETS, { withFileTypes: true })) {
  if (f.isFile()) byName.set(f.name, path.join(ASSETS, f.name))
}

const reachable = new Set()
const queue = [...entries]
while (queue.length) {
  const name = queue.pop()
  if (reachable.has(name) || !byName.has(name)) continue
  reachable.add(name)
  const text = fs.readFileSync(byName.get(name), 'utf8')
  /* 只扫带 hash 形状的引用，避免把无关字符串当成文件名 */
  for (const m of text.matchAll(/[\w.-]*-[A-Za-z0-9_-]{8,}\.(?:js|css)/g)) {
    const ref = m[0].replace(/^\.\//, '')
    if (!reachable.has(ref) && byName.has(ref)) queue.push(ref)
  }
}

if (reachable.size < 2) die(`可达集只有 ${reachable.size} 个文件，疑似解析失败 —— 拒绝清理`)

const all = [...byName.keys()]
const victims = all.filter((n) => HASHED.test(n) && !reachable.has(n))
const kept = all.filter((n) => !victims.includes(n))

const bytes = victims.reduce((s, n) => s + fs.statSync(byName.get(n)).size, 0)
const mb = (bytes / 1024 / 1024).toFixed(1)

console.log('─'.repeat(60))
console.log(`  产物目录     : ${OUT_DIR}`)
console.log(`  入口 chunk   : ${[...entries].filter((e) => e.startsWith('index-')).join(', ') || [...entries][0]}`)
console.log(`  可达文件     : ${reachable.size}`)
console.log(`  目录内文件   : ${all.length}`)
console.log(`  陈旧可删     : ${victims.length} 个 / ${mb} MB`)
console.log(`  保留（非hash形状，未判定）: ${kept.length - reachable.size}`)
console.log('─'.repeat(60))

if (!APPLY) {
  console.log('[干跑] 未删除任何文件。确认无误后加 --apply。')
  if (victims.length) {
    console.log('  样例：' + victims.slice(0, 5).join(', '))
  }
  process.exit(0)
}

let removed = 0
for (const n of victims) {
  try {
    fs.unlinkSync(byName.get(n))
    removed++
  } catch (e) {
    console.error(`[prune] 删除失败 ${n}: ${e.message}`)
  }
}
console.log(`已删除 ${removed}/${victims.length} 个陈旧 chunk，释放约 ${mb} MB。`)
