#!/usr/bin/env node
/**
 * 离线问答测试：不连 WhatsApp，跑**与群里完全一致**的答题链路。
 * 用于验证知识库效果、调阈值，或在部署前做冒烟测试。
 *
 *   npm run ask -- "年假有几天"
 *   npm run ask -- "分析TT单TT202609150073"
 *   npm run ask -- --debug "报销流程怎么走"
 */
import { CONFIG } from '../src/config.js';
import { loadIndex } from '../src/rag.js';
import { routeAnswer, describeRoute } from '../src/answer.js';
import { validateProvider, providerInfo } from '../src/llm.js';

const argv = process.argv.slice(2);
const debug = argv.includes('--debug');
const question = argv.filter((a) => a !== '--debug').join(' ').trim();

if (!question) {
  console.error('用法：npm run ask -- [--debug] "你的问题"');
  process.exit(1);
}

// 先校验 provider，避免跑到一半抛出难懂的堆栈
const v = validateProvider();
if (!v.ok) {
  console.error(`✗ ${v.message}`);
  process.exit(1);
}

const info = providerInfo();
const index = loadIndex();
console.log(`索引：${index.meta.chunks} 块 / ${index.meta.files} 文件`);
console.log(`对话模型：[${info.provider}] ${info.model}\n`);
console.log(`问：${question}\n`);

let result;
try {
  result = await routeAnswer(question, index, {
    onDebug: debug
      ? (d) => {
          console.log('--- 检索诊断 ---');
          console.log(`  嵌入耗时  : ${d.embedMs}ms`);
          console.log(`  top1      : ${d.topBase}`);
          console.log(`  基线(中位): ${d.baseline}`);
          console.log(`  gap       : ${d.gap}   (阈值 ${CONFIG.minGap}, 启用gap=${d.useGap})`);
          console.log(`  判定      : ${d.hit ? '命中' : '未命中'}`);
          for (const c of d.candidates) {
            console.log(`    · base=${c.base}  sem=${c.sem}  lex=${c.lex}  ${c.source}`);
          }
          console.log('');
        }
      : undefined,
  });
} catch (err) {
  console.error(`✗ 调用失败：${err.message}`);
  process.exit(1);
}

console.log(`答：${result.text}\n`);
console.log(
  `${describeRoute(result)}｜命中=${result.answered}｜总耗时 ${result.stats?.totalMs ?? '-'}ms` +
    (result.stats?.outputTokens != null
      ? `（生成 ${result.stats.genMs ?? '-'}ms，${result.stats.outputTokens} tokens）`
      : '')
);
