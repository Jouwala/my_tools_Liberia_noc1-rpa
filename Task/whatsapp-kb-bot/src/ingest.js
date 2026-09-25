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
