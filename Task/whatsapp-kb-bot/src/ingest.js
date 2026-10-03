#!/usr/bin/env node
/**
 * 知识库索引构建 CLI。
 *
 *   npm run ingest            扫描 knowledge/ 重建索引
 *   npm run doctor            只做环境自检，不写索引
 *
 * 支持格式：.md / .markdown / .txt / .text
 * 输出：data/index.json（{ meta, chunks[], vectors[][] }）
 */
import { readdirSync, statSync, readFileSync, existsSync } from 'node:fs';
import { join, extname, relative } from 'node:path';
import { CONFIG, describeConfig, ROOT } from './config.js';
import { chunkText, saveIndex } from './rag.js';
import { embed, healthCheck } from './ollama.js';

const EXTS = new Set(['.md', '.markdown', '.txt', '.text']);
const CHECK_ONLY = process.argv.includes('--check-only');

/* ------------------------------- 文件扫描 ------------------------------- */

function walk(dir, acc = []) {
  if (!existsSync(dir)) return acc;
  for (const name of readdirSync(dir)) {
    if (name.startsWith('.')) continue;
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) walk(full, acc);
    else if (EXTS.has(extname(name).toLowerCase())) acc.push(full);
  }
  return acc;
}

/** 取首个一级标题作为文档名，否则用文件名 */
function docTitle(raw, fallback) {
  const m = raw.match(/^\s*#\s+(.+)$/m);
  return m ? m[1].trim() : fallback;
}

/**
 * 分块去重：同一段文本只保留一份。
 *
 * 为什么必须做：实测索引 816 块里有 **73 块是纯重复**（占 9%），
 * 其中 `07_iMind-eFlow-Function-Operation-Guide.md` 里同一段
 * "Prerequisite - The system is deployed successfully..." 样板文字
 * 被切成 **34 份**、另一段 23 份。
 *
 * 危害不是"浪费磁盘"，而是**直接吃掉检索名额**：
 * 实测查 "Prerequisite for eFlow deployment" 时 topK=6 全部命中
 * 同一段重复文本 —— 6 个名额只带回 1 条信息，模型看到的"资料"
 * 严重退化，答非所问的比例随之上升。
 *
 * 归一化：**删除所有空白**再比对，而不是「把连续空白压成一个空格」。
 * 原因：分块器会在断点处重新拼接，同一段原文可能落成
 * `系统\n部署成功` 与 `系统部署成功` 两种形态；压成单空格时两者仍不相等
 * （`系统 部署成功` ≠ `系统部署成功`），重复块会漏网。
 * 中文语料里空白本就不承载语义，整体删除是安全且更彻底的做法。
 *
 * 不做模糊匹配 —— 宁可漏合并，不可误合并
 * （把两段不同的规则当成一段，比留几份重复严重得多）。
 *
 * @returns {{chunks: Array, removed: number, groups: number}}
 */
export function dedupeChunks(chunks) {
  const seen = new Map(); // 归一化文本 → 首次出现的下标
  const out = [];
  let removed = 0;

  for (const c of chunks) {
    const key = c.text.replace(/\s+/g, '').trim();
    if (seen.has(key)) {
      removed++;
      // 记录被合并的出处，便于事后核对（同一文档内的重复是主要来源）
      const first = out[seen.get(key)];
      if (first && first.source !== c.source) first.alsoIn = [...(first.alsoIn || []), c.source];
      continue;
    }
    seen.set(key, out.length);
    out.push(c);
  }
  return { chunks: out, removed, groups: seen.size };
}

/* --------------------------------- 主流程 -------------------------------- */

async function main() {
  console.log('=== WhatsApp 知识库助手 · 索引构建 ===\n');
  for (const [k, v] of Object.entries(describeConfig())) {
    console.log(`  ${k.padEnd(10, '　')}: ${v}`);
  }
  console.log();

  // 1. 环境自检
  console.log('[1/4] 检查 Ollama…');
  let health;
  try {
    health = await healthCheck();
  } catch (err) {
    console.error(`  ✗ ${err.message}`);
    process.exit(1);
  }
  console.log(`  ✓ 已安装模型：${health.models.join(', ')}`);
  if (!health.embedModelPresent) {
    console.error(`  ✗ 缺少嵌入模型 ${CONFIG.embedModel}，请先：ollama pull ${CONFIG.embedModel}`);
    process.exit(1);
  }
  // 建索引只用嵌入模型；对话模型是本地还是云端与此无关，不在这里检查
  console.log('  ✓ 嵌入模型就位');

  if (CHECK_ONLY) {
    console.log('\n自检通过（未写入索引）。');
    return;
  }

  // 2. 扫描 + 分块
  console.log('\n[2/4] 扫描知识库…');
  const files = walk(CONFIG.knowledgeDirAbs);
  if (!files.length) {
    console.error(`  ✗ ${CONFIG.knowledgeDirAbs} 下没有找到 ${[...EXTS].join('/')} 文件。`);
    console.error('    把你的资料（产品文档、FAQ、内部规范…）放进去再运行。');
    process.exit(1);
  }

  const chunks = [];
  for (const file of files) {
    const raw = readFileSync(file, 'utf8');
    const rel = relative(ROOT, file).replace(/\\/g, '/');
    const title = docTitle(raw, rel.split('/').pop());
    const parts = chunkText(raw);
    parts.forEach((text, i) => {
      chunks.push({ text, source: rel, title, seq: i });
    });
    console.log(`  · ${rel}  →  ${parts.length} 块（${raw.length} 字符）`);
  }
  console.log(`  合计 ${files.length} 个文件 / ${chunks.length} 个知识块`);

  if (!chunks.length) {
    console.error('  ✗ 分块结果为空，请检查文件内容。');
    process.exit(1);
  }

  // 2.5 去重：同一段文本只留一份（详见 dedupeChunks 的注释）
  const { chunks: unique, removed } = dedupeChunks(chunks);
  if (removed > 0) {
    console.log(`  去重：移除 ${removed} 个重复块 → ${unique.length} 块（省下 ${(removed / chunks.length * 100).toFixed(1)}% 检索名额）`);
  } else {
    console.log('  去重：无重复块');
  }
  chunks.length = 0;
  chunks.push(...unique);

  // 3. 嵌入
  console.log(`\n[3/4] 生成向量（${CONFIG.embedModel}）…`);
  const t0 = Date.now();
  let vectors;
  try {
    vectors = await embed(chunks.map((c) => c.text));
  } catch (err) {
    console.error(`  ✗ 嵌入失败：${err.message}`);
    process.exit(1);
  }
  const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
  if (vectors.length !== chunks.length) {
    console.error(`  ✗ 向量数量不匹配：${vectors.length} != ${chunks.length}`);
    process.exit(1);
  }
  console.log(`  ✓ ${vectors.length} 条向量，维度 ${vectors[0].length}，耗时 ${elapsed}s`);
  console.log(`    平均 ${(Number(elapsed) / vectors.length * 1000).toFixed(0)} ms/块`);

  // 4. 落盘
  console.log('\n[4/4] 写入索引…');
  const index = {
    meta: {
      builtAt: new Date().toISOString(),
      embedModel: CONFIG.embedModel,
      dim: vectors[0].length,
      files: files.length,
      chunks: chunks.length,
      chunkSize: CONFIG.chunkSize,
      chunkOverlap: CONFIG.chunkOverlap,
      sources: files.map((f) => relative(ROOT, f).replace(/\\/g, '/')),
    },
    chunks,
    vectors,
  };
  saveIndex(index);
  const sizeKb = (statSync(CONFIG.indexPathAbs).size / 1024).toFixed(0);
  console.log(`  ✓ ${CONFIG.indexPathAbs}（${sizeKb} KB）`);
  console.log('\n索引构建完成。下一步：npm start');
}

main().catch((err) => {
  console.error(`\n意外错误：${err.stack || err.message}`);
  process.exit(1);
});
