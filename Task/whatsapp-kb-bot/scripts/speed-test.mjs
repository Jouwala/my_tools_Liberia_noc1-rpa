#!/usr/bin/env node
/**
 * 速度对比测试：在线 deepseek-v4.1-flash vs 本地 qwen2.5:7b-instruct
 * 用同一个问题测试两个模型，对比响应时间
 */
import { readFileSync } from 'node:fs';

const QUESTIONS = [
  "What is a Trouble Ticket",
  "What does P1 mean in NOC",
  "What is alarm compression",
  "how many P1 tickets today",
];

const MODELS = [
  {
    name: '在线 deepseek-v4.1-flash',
    provider: 'openai',
    baseUrl: 'http://127.0.0.1:8788/v1',
    model: 'deepseek-v4.1-flash',
    apiKey: 'wbproxy',
  },
  {
    name: '本地 qwen2.5:7b-instruct',
    provider: 'ollama',
    baseUrl: 'http://192.168.100.27:11434/v1',
    model: 'qwen2.5:7b-instruct',
    apiKey: 'not-needed',
  },
];

async function chat(model, question) {
  const start = Date.now();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60000);

  try {
    const response = await fetch(`${model.baseUrl}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(model.provider === 'openai' ? { 'Authorization': `Bearer ${model.apiKey}` } : {}),
      },
      body: JSON.stringify({
        model: model.model,
        messages: [
          { role: 'system', content: 'You are a helpful assistant. Reply in one sentence.' },
          { role: 'user', content: question },
        ],
        max_tokens: 100,
        temperature: 0.2,
      }),
      signal: controller.signal,
    });

    clearTimeout(timeout);
    const data = await response.json();
    const elapsed = Date.now() - start;
    const answer = data.choices?.[0]?.message?.content || '(无回复)';
    const tokens = data.usage?.completion_tokens || 0;
    const speed = tokens > 0 ? Math.round(tokens / (elapsed / 1000)) : 0;
    
    return { elapsed, answer, tokens, speed, ok: true };
  } catch (e) {
    clearTimeout(timeout);
    return { elapsed: Date.now() - start, answer: '', tokens: 0, speed: 0, ok: false, error: e.message };
  }
}

async function main() {
  console.log('\n🔬 模型速度对比测试\n');
  console.log(`问题数量: ${QUESTIONS.length}`);
  console.log(`模型数量: ${MODELS.length}\n`);
  
  const results = {};
  
  for (const model of MODELS) {
    console.log(`\n${'='.repeat(60)}`);
    console.log(`📦 ${model.name}`);
    console.log(`${'='.repeat(60)}`);
    results[model.name] = [];
    
    for (const q of QUESTIONS) {
      process.stdout.write(`\n⏱  问: "${q}"\n`);
      const result = await chat(model, q);
      
      if (result.ok) {
        console.log(`   ⏱  耗时: ${result.elapsed}ms | tokens: ${result.tokens} | 速度: ${result.speed}/s`);
        console.log(`   📝 答: ${result.answer.slice(0, 80)}${result.answer.length > 80 ? '...' : ''}`);
        results[model.name].push(result);
      } else {
        console.log(`   ❌ 失败: ${result.error}`);
        results[model.name].push({ ...result, elapsed: 0 });
      }
    }
  }
  
  // 总结
  console.log('\n\n' + '='.repeat(70));
  console.log('📊 总结');
  console.log('='.repeat(70));
  
  for (const model of MODELS) {
    const ok = results[model.name].filter(r => r.ok);
    const avg = ok.length > 0 
      ? Math.round(ok.reduce((sum, r) => sum + r.elapsed, 0) / ok.length)
      : 0;
    const avgSpeed = ok.length > 0 && ok.reduce((sum, r) => sum + r.speed, 0) > 0
      ? Math.round(ok.reduce((sum, r) => sum + r.speed, 0) / ok.length)
      : 0;
    
    console.log(`\n${model.name}:`);
    console.log(`  平均响应时间: ${avg}ms`);
    console.log(`  平均生成速度: ${avgSpeed} tokens/s`);
    console.log(`  成功次数: ${ok.length}/${QUESTIONS.length}`);
  }
  
  // 速度对比
  const model1 = results[MODELS[0].name];
  const model2 = results[MODELS[1].name];
  const avg1 = model1.filter(r => r.ok).reduce((s, r) => s + r.elapsed, 0) / model1.filter(r => r.ok).length;
  const avg2 = model2.filter(r => r.ok).reduce((s, r) => s + r.elapsed, 0) / model2.filter(r => r.ok).length;
  
  console.log('\n' + '-'.repeat(70));
  if (avg1 < avg2) {
    const faster = ((avg2 - avg1) / avg2 * 100).toFixed(0);
    console.log(`🏆 赢家: ${MODELS[0].name}，快 ${faster}%`);
  } else {
    const faster = ((avg1 - avg2) / avg1 * 100).toFixed(0);
    console.log(`🏆 赢家: ${MODELS[1].name}，快 ${faster}%`);
  }
}

main().catch(console.error);
