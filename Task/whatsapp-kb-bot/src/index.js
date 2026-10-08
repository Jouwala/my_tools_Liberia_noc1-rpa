#!/usr/bin/env node
/**
 * 入口：加载索引 → 启动 WhatsApp → 群内 @提及 触发知识库问答。
 *
 *   npm start
 *   npm start -- --debug      打印每次检索的诊断信息
 */
import { CONFIG, describeConfig, ROOT } from './config.js';
import { loadIndex } from './rag.js';
import { loadLookupsOnce } from './tools.js';
import { routeAnswer } from './answer.js';
import { healthCheck, warmup, loadedModels } from './ollama.js';
import { validateProvider, providerInfo, pingProvider } from './llm.js';
import { startWhatsApp, stopWhatsApp } from './whatsapp.js';
import { ttAvailable } from './tt.js';
import { scanKnowledge, diffIndex, freshnessWarning } from './indexFreshness.js';
import { LOADED_MTIME, PROCESS_STARTED_AT, fmtTime, isStale, uptimeText } from './buildinfo.js';

const DEBUG = process.argv.includes('--debug') || process.env.DEBUG_RAG === '1';

/* ---------------------------- 优雅退出与兜底 ---------------------------- */

// 必须优雅关闭：直接 Ctrl+C 会让 Baileys 的凭据写入中断，可能导致下次要重新扫码
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, async () => {
    await stopWhatsApp(`收到 ${sig}`);
    process.exit(0);
  });
}

// 不让单个未捕获的 Promise 异常掀翻整个进程
process.on('unhandledRejection', (err) => {
  console.error(`[未处理的 Promise 异常] ${err?.stack || err}`);
});
process.on('uncaughtException', (err) => {
  console.error(`[未捕获异常] ${err?.stack || err}`);
});

async function main() {
  console.log('=== WhatsApp 知识库助手 ===\n');
  for (const [k, v] of Object.entries(describeConfig())) {
    console.log(`  ${k.padEnd(10, '　')}: ${v}`);
  }
  console.log();

  // 1. provider 配置自检（缺 key 就在这里失败，不要等到第一条消息）
  const v = validateProvider();
  if (!v.ok) {
    console.error(`✗ ${v.message}\n`);
    process.exit(1);
  }
  const info = providerInfo();
  if (info.provider === 'openai') {
    console.log(`✓ 对话 provider：openai 兼容接口（密钥来源：${info.keySource || '未知'}）`);
    const p = await pingProvider();
    if (p.ok && !p.warning) {
      console.log(`  ✓ 连通性正常：${p.message}`);
    } else if (p.ok && p.warning) {
      console.log('  ! 连通性正常但模型输出异常：');
      for (const line of String(p.message).split('\n')) console.log(`    ${line}`);
    } else {
      // 刻意不终止启动。
      // ping 只是"最好能过"的探测，不是硬门槛：它用的 token 预算比真实问答小，
      // 失败不代表问答一定失败。而且群里先用 ping/help 就能验证传输层，
      // 没必要因为一次探测把用户完全卡死 —— 那会让人连排查入口都进不去。
      console.log('  ! 连通性探测未通过 —— 继续启动，但云端问答可能失败');
      for (const line of String(p.message).split('\n')) console.log(`    ${line}`);
      console.log('    排查：npm run diag   （打印云端返回的完整响应结构）');
    }
  } else {
    console.log('✓ 对话 provider：本地 Ollama');
  }

  // 2. Ollama 自检（嵌入始终走 Ollama；.20 那台没有本地 Ollama，配置指向内网 .27）
  //
  // ⚠️ **这里刻意不 exit(1)**（2026-10-01 改，停机 29 小时事故的治本项）。
  //
  // 原因：Ollama 只影响**问答**（嵌入检索），而机器人还会收发消息、执行内置命令
  // （ping / help）。原先 Ollama 一不可用就 `process.exit(1)`，等于让一个旁路依赖
  // 的可用性决定整条链路的生死 —— 实测后果是：.20 那台**从未安装** Ollama
  // （`ollama.exe` 不存在），配置里的 `127.0.0.1:11434` 永远连不上，于是机器人
  // 自 2026-09-30 09:49 起再没起来过，且**没有任何告警**，直到 10-01 排查才发现
  // 「它已经停了 29 小时」。
  //
  // 改为：不可用时只标记 `qaAvailable = false`，进程照常连接并响应；
  // 真正提问时再回一句明确的故障话术。这样「能不能收发消息」与「能不能查知识库」
  // 解耦，坏一半不会拖垮全部。
  let qaAvailable = true;
  try {
    const h = await healthCheck();
    const needChat = CONFIG.chatProvider === 'ollama';
    if (!h.embedModelPresent || (needChat && !h.chatModelPresent)) {
      qaAvailable = false;
      const missing = [];
      if (!h.embedModelPresent) missing.push(CONFIG.embedModel);
      if (needChat && !h.chatModelPresent) missing.push(CONFIG.chatModel);
      console.error(`! Ollama（${CONFIG.ollamaUrl}）缺模型：${missing.join(', ')}`);
      console.error(`  问答将不可用；收发消息与内置命令 ping/help 不受影响。`);
      console.error(`  修复：在该机执行 ollama pull ${missing.join(' && ollama pull ')}`);
    } else {
      console.log(`✓ Ollama 就绪（${CONFIG.ollamaUrl}，嵌入模型 ${CONFIG.embedModel}）`);
    }
  } catch (err) {
    qaAvailable = false;
    console.error(`! Ollama 连接失败（${CONFIG.ollamaUrl}）：${err.message}`);
    console.error('  问答将不可用；收发消息与内置命令 ping/help 不受影响。');
  }

  // 3. 预热本地模型，并检查常驻情况（直接决定每次回答的延迟）
  try {
    const w = await warmup();
    const gb = (b) => (b / 1024 ** 3).toFixed(2);
    if (w.bothResident) {
      console.log(
        w.chatLocal
          ? `✓ 本地两个模型均已常驻（合计 ${gb(w.residentBytes)} GB），问答无需重载`
          : `✓ 对话走云端，本地仅需嵌入模型（${gb(w.residentBytes)} GB），无模型互挤问题`
      );
    } else {
      console.log('! 本地两个模型无法同时常驻 —— 每次提问都要重载模型，实测每次多花 3~5 秒');
      console.log(`  已常驻：${w.loaded.map((m) => m.name).join(', ') || '（无）'}`);
      console.log('  修复：给 Ollama 服务设置环境变量 OLLAMA_MAX_LOADED_MODELS=2 后重启 Ollama');
    }
  } catch (err) {
    console.log(`! 预热失败（不影响运行）：${err.message}`);
  }
  console.log();

  // 4. 索引
  const index = loadIndex();
  console.log(
    `✓ 索引就绪：${index.meta.chunks} 块 / ${index.meta.files} 个文件` +
      `（${index.meta.embedModel}, ${index.meta.dim}维, 构建于 ${index.meta.builtAt}）`
  );

  // 索引新鲜度：磁盘 knowledge/ 与内存索引是否一致。
  // 与 Ollama 自检同一取舍——**只警告、不 exit(1)**：索引过期只影响问答质量，
  // 不该让收发消息和 ping/help 一起起不来。结果交给 ping 暴露给群里。
  // 每次 ping 都重新扫盘（与代码指纹同一个理由：调用时算，不能冻在启动那刻）。
  const freshness = () => {
    try {
      return diffIndex(index.meta, scanKnowledge(CONFIG.knowledgeDirAbs, ROOT));
    } catch {
      return null; // 扫盘失败（网络盘抖动等）不该影响 ping
    }
  };
  {
    const w = freshnessWarning(freshness());
    if (w) {
      console.error(`! ${w}`);
      console.error(`  当前进程仍用内存里的旧索引（${index.meta.chunks} 块 / ${index.meta.files} 文件）。`);
    } else {
      console.log('✓ 索引新鲜：与磁盘 knowledge/ 一致');
    }
  }

  // TT 单分析：实时查 my_app 工单库，与知识库是两条独立通道
  if (ttAvailable()) {
    console.log('✓ 工单分析就绪：消息里带 TT / WO 单号（如 TT202609150073、WO202609220055）会实时查工单库');
  } else {
    console.log('! 工单分析不可用（缺 scripts/tt-analyze.py 或 Python 解释器），TT 类问题将走知识库');
  }

  // 查表数据（告警码 / 压缩 / 级别）：告警码含义、压缩结果、级别规则三类问法走它，
  // 不经 LLM。缺失时查表工具会如实回「未构建」，不退回 RAG。
  const lookups = loadLookupsOnce();
  if (lookups) {
    console.log(
      `✓ 查表就绪：告警码 ${lookups.alarmCodes.size} 条 / 压缩规则 ${lookups.compress.length} 条 / 级别规则 ${lookups.levelRules.length} 条`
    );
  } else {
    console.log('! 查表数据缺失（data/lookups.json）——告警码/压缩/级别问法会提示「未构建」，请 npm run ingest');
  }
  console.log();

  // 回复语言：按**提问语言**自动切换（见 src/lang.js）。
  // 打出来是为了排障 —— 「英文提问收到中文回复」要么是这里没生效，
  // 要么是进程在跑旧代码（见下面的代码指纹）。
  console.log('✓ 回复语言：中 / 英自动适配（按提问语言判定）');
  // 代码指纹：磁盘上源文件的最大修改时间。
  // 下次怀疑「改了没效果」时，@机器人发 ping，对比那里的指纹即可 ——
  // 若那里的指纹比这个进程的启动时间新，说明改完没重启。
  console.log(`  代码指纹：${fmtTime(LOADED_MTIME)}（本进程启动于 ${fmtTime(PROCESS_STARTED_AT)}）\n`);

  // 5. 启动
  // 内置命令：不查知识库，用于确认「@到了 + 能回消息」这条链路是通的。
  // 排查顺序永远是先 ping 后提问：ping 有回应说明传输层没问题，故障必在检索侧。
  const builtins = {
    ping: async () => {
      const w = await loadedModels().catch(() => null);
      const lines = [
        'pong ✅ 机器人在线',
        `知识库：${index.meta.chunks} 块 / ${index.meta.files} 个文件`,
        `对话模型：[${info.provider}] ${info.model}`,
        `嵌入模型：${CONFIG.embedModel}（${CONFIG.ollamaUrl}）`,
        '回复语言：中 / 英自动适配',
      ];
      if (info.provider === 'openai') {
        lines.push('对话走云端，本地无模型互挤，响应通常 1–3 秒');
      } else if (w) {
        lines.push(
          w.bothResident ? '本地模型常驻：两个都在内存，响应约 1 秒' : '本地模型常驻：仅 1 个，响应约 8–12 秒'
        );
      }
      // 运行时长 + 代码新鲜度。
      // 「改了代码没生效」是这里最容易踩的坑（改文件 + 重启才生效，忘了重启
      // 不报任何错，只是回复内容是旧的）。所以把判断直接放到 ping 里 ——
      // 群里 @ 一下就知道，不用登机器翻日志。
      lines.push(`已运行：${uptimeText()}（启动于 ${fmtTime(PROCESS_STARTED_AT)}）`);
      if (isStale()) {
        lines.push('⚠️ 磁盘上的代码比本进程新 —— 现在跑的是旧代码，重启后新改动才生效');
      } else {
        lines.push('代码版本：最新（与磁盘一致）');
      }
      // 索引新鲜度：磁盘 knowledge/ 是否比内存索引新（如新增了 08_ 但没 ingest/重启）。
      // 「代码新鲜」不等于「索引新鲜」——两者是独立的两件事，都要报。
      const fw = freshnessWarning(freshness());
      if (fw) lines.push(fw);
      return lines.join('\n');
    },
    help: async () =>
      [
        '直接 @我 + 问题就行，我会在你的知识库里找答案。',
        '找得到就直接答；找不到我会明说没有依据，不会编。',
        '',
        '三类问题走的是不同通道：',
        '  · 带 TT / WO 单号（如 TT202609150073、WO202609220055）→ 实时查工单库，给出级别判定与命中规则',
        '  · 今天/昨天有几个 P1、某站昨天几单 → 查工单统计（数字由脚本算，不编）',
        '  · 告警码含义 / 压缩结果 / 级别规则（如「告警码 99933 是什么意思」）→ 查表，带出处',
        '  · 其他（流程、为什么、SOP）→ 查知识库，答案带来源文件名',
        '一次可以贴多个单号（最多 3 个），我会逐个分析。',
        '内置命令：ping（测在线）、help（看这段）',
      ].join('\n'),
  };

  await startWhatsApp({
    builtins,
    onQuestion: async (question, { lang, onRetry, onLive, history } = {}) => {
      const t0 = Date.now();

      // 嵌入不可用时**不再整条短路**：2026-10-08 修正。
      //
      // 旧行为：qaAvailable=false 时直接返回一句「知识库不可用」——
      // 但这把**不依赖嵌入**的通道（TT 单号分析、工单统计、按站点查告警、
      // 告警码查表）也一起挡死了。嵌入挂掉时，用户连「查 TT单号」都用不了，
      // 属于把「坏一半」升级成「全坏」。
      //
      // 新行为：交给 routeAnswer 正常路由。
      //   · 工具通道（tt / stats / sitealarm / lookup）不需要嵌入 → 照常工作；
      //   · 知识库通道在 src/rag.js 里**就地捕获**嵌入异常，回一句说清
      //     「知识库此刻不可用」的明确话术（不再是含糊的 errorText）。
      // 这样嵌入故障只影响它本该影响的那一部分。
      // （qaAvailable 仍保留：只在启动自检里打印状态，供 ping/排障用。）
      void qaAvailable;

      const result = await routeAnswer(question, index, {
        // 语言由接入层按提问原文判定后传下来（见 whatsapp.js / lang.js），
        // 这里只负责转发 —— 避免两处各判一次、口径还可能不一致。
        lang,
        // 会话历史：追问（「那个单子未闭环」）靠它才能落地。
        // 接入层算好了传下来，这里**必须原样转发** ——
        // 2026-10-07 实测漏掉这一行：探针里追问能正确落到 TT202610020012，
        // 群里却走成了知识库、32 秒后答「资料未包含…流程」。
        // 传参链任何一环断了，前后两处单看都"没问题"，只有端到端才暴露。
        history,
        // 工单通道失败自动重试前，先把垫话发出去（透传到接入层）
        onRetry,
        // 本地库查不到、要去 eFlow 实时查之前，同样先垫一句
        onLive,
        onRoute: ({ channel, ttNo, ttNos, count, okCount, ms, ok }) => {
          if (channel === 'tt') {
            const multi = count > 1 ? `（${okCount}/${count} 个单成功）` : '';
            console.log(`[TT分析] ${(ttNos || [ttNo]).join(', ')}｜${ms}ms｜${ok ? '成功' : '失败'}${multi}`);
          }
        },
        onDebug: DEBUG
          ? (d) => {
              console.log(`\n--- 检索诊断 ---`);
              console.log(`  嵌入耗时 : ${d.embedMs}ms`);
              console.log(`  top1     : ${d.topBase}`);
              console.log(`  基线(中位): ${d.baseline}`);
              console.log(`  gap      : ${d.gap}  (阈值 ${CONFIG.minGap}, 使用gap=${d.useGap})`);
              console.log(`  判定     : ${d.hit ? '命中' : '未命中'}`);
              if (d.excluded != null) console.log(`  来源排除 : ${d.excluded} 块（kbExcludeSources）`);
              for (const c of d.candidates) {
                console.log(`    · base=${c.base} sem=${c.sem} lex=${c.lex} bm25=${c.bm25 ?? 0}  ${c.source}`);
              }
            }
          : undefined,
      });
      if (DEBUG) console.log(`  总耗时   : ${Date.now() - t0}ms\n`);
      return result;
    },
  });
}

main().catch((err) => {
  console.error(`\n启动失败：${err.message}`);
  process.exit(1);
});
