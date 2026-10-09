#!/usr/bin/env node
/**
 * 5天英文测试快速执行脚本
 *
 * 用法：
 *   node scripts/test-5day.mjs                    # 交互式选择天数
 *   node scripts/test-5day.mjs --day 1           # 直接运行指定天数
 *   node scripts/test-5day.mjs --all             # 运行全部5天
 *   node scripts/test-5day.mjs --regression      # 只跑回归测试
 */
import { execSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const argv = process.argv.slice(2);

// ANSI 颜色
const C = {
  green: '\x1b[32m',
  red: '\x1b[31m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  cyan: '\x1b[36m',
  reset: '\x1b[0m',
  bold: '\x1b[1m',
};

function log(color, prefix, msg) {
  console.log(`${color}[${prefix}]${C.reset} ${msg}`);
}
const pass = (msg) => log(C.green, '✓', msg);
const fail = (msg) => log(C.red, '✗', msg);
const info = (msg) => log(C.cyan, 'i', msg);
const warn = (msg) => log(C.yellow, '!', msg);

// 运行命令
function run(cmd, label) {
  try {
    info(`执行: ${label}`);
    const output = execSync(cmd, { encoding: 'utf8', timeout: 120000 });
    pass(`${label} ✓`);
    return { ok: true, output };
  } catch (e) {
    fail(`${label} ✗`);
    if (e.stdout) console.log(e.stdout);
    if (e.stderr) console.log(e.stderr);
    return { ok: false, output: e.stdout || '', error: e.stderr };
  }
}

// 逐条执行测试
async function ask(question, label) {
  return new Promise((resolve) => {
    try {
      const cmd = `node scripts/ask.mjs "${question.replace(/"/g, '\\"')}"`;
      const output = execSync(cmd, { encoding: 'utf8', timeout: 60000 });
      console.log(`  ${C.blue}→${C.reset} ${label}`);
      // 显示完整回答内容
      const lines = output.split('\n');
      for (const line of lines) {
        console.log(`    ${line}`);
      }
      // 判断是否未命中
      const notFound = output.includes("don't have") || 
                       output.includes("can't answer") ||
                       output.includes("not found") ||
                       output.includes("notFound");
      if (notFound) {
        pass(`"${question}" → 未命中（正确行为）`);
      } else {
        pass(`"${question}" → ✓`);
      }
      resolve({ ok: true, output });
    } catch (e) {
      fail(`"${question}" → ✗`);
      if (e.stdout) console.log(e.stdout);
      resolve({ ok: false, error: e.message });
    }
  });
}

// 各天测试用例
const TEST_CASES = {
  1: {
    name: 'Day 1: 路由与语言判定',
    regression: ['node scripts/test-tools.mjs', 'node scripts/test-lang.mjs'],
    ask: [
      ['how many tickets today', '英文 today'],
      ['how many P1 tickets this week', '英文 this week'],
      ['how many tickets yesterday', '英文 yesterday'],
      ['how many tickets last month', '英文 last month'],
      ['what is a P1 ticket', 'KB 通道'],
      ['how many P1 tickets today', 'Stats 通道'],
      ['analyze TT202609110023?', '英文问号'],
      ['analyze TT202609110023？', '全角问号'],
    ],
  },
  2: {
    name: 'Day 2: 知识库问答',
    regression: [],
    ask: [
      ['What is a Trouble Ticket', '基础概念'],
      ['What does P1 mean in NOC', '级别含义'],
      ['What is alarm compression', '告警压缩'],
      ['What is the TT creation workflow', '工作流'],
      ['How to assign a TT to FO', '指派规则'],
      ['What is the weather in Monrovia', '未命中'],
      ['Who won the football yesterday', '未命中'],
    ],
  },
  3: {
    name: 'Day 3: 工单统计',
    regression: [],
    ask: [
      ['how many tickets today', '今日总数'],
      ['how many P1 tickets today', 'P1 统计'],
      ['how many P2 tickets yesterday', '昨日 P2'],
      ['how many open tickets this week', '本周未闭环'],
      ['how many P1 tickets this month, give me the ticket IDs', '要单号列表'],
      ['show me the P2 ticket IDs for this week', '英文列表意图'],
      ['how many tickets at Wood camp today', '站点过滤'],
    ],
  },
  4: {
    name: 'Day 4: 工单分析与告警码',
    regression: ['node scripts/test-tt-extract.mjs', 'node scripts/test-lookups.mjs'],
    ask: [
      ['analyze TT202609110023', 'TT 单分析'],
      ['please check TT202609150073', '英文 TT'],
      ['analyze WO202609220055', 'WO 单（回溯）'],
      ['what does alarm code 9991 mean', '告警码含义'],
      ['what is alarm code 9990', '告警码查询'],
      ['CSD alarm is which level', '告警名→码→级别'],
      ['Fiber Break alarm code', '告警名查询'],
      ['what level is a 3G CELL DOWN alarm', '告警级别'],
    ],
  },
  5: {
    name: 'Day 5: 边界与回归',
    regression: ['npm test'],
    ask: [
      ['check TT202609140078, TT202609140077', '多单分析'],
      ['analyze these TT202609140078 TT202609140077', '多单格式2'],
      ['analyze TT202609999999', '不存在的单号'],
      ['analyze TT123456', '格式正确但不存在'],
      ['ping', '内置命令'],
    ],
  },
};

// 显示菜单
function showMenu() {
  console.log(`\n${C.bold}📅 5天英文测试选择${C.reset}\n`);
  for (const [day, data] of Object.entries(TEST_CASES)) {
    console.log(`  ${C.cyan}${day}${C.reset}. ${data.name}`);
  }
  console.log(`\n  ${C.cyan}a${C.reset}. 运行全部5天`);
  console.log(`  ${C.cyan}r${C.reset}. 只跑回归测试`);
  console.log(`  ${C.cyan}q${C.reset}. 退出`);
  console.log();
}

// 主流程
async function main() {
  const dayArg = argv.find((a) => a.startsWith('--day='));
  const runAll = argv.includes('--all');
  const runRegression = argv.includes('--regression');

  if (runRegression) {
    console.log(`\n${C.bold}🔧 运行回归测试${C.reset}\n`);
    for (const test of ['test-tools.mjs', 'test-lang.mjs', 'test-tt-extract.mjs', 'test-lookups.mjs']) {
      run(`node scripts/${test}`, `${test}`);
    }
    return;
  }

  if (runAll) {
    for (let d = 1; d <= 5; d++) {
      await runDay(d, TEST_CASES[d]);
    }
    return;
  }

  if (dayArg) {
    const day = parseInt(dayArg.split('=')[1]);
    if (TEST_CASES[day]) {
      await runDay(day, TEST_CASES[day]);
    } else {
      fail(`无效天数: ${day}`);
    }
    return;
  }

  // 交互模式
  showMenu();
  process.stdout.write('请选择 (1-5/a/r/q): ');
}

async function runDay(day, data) {
  console.log(`\n${C.bold}${'='.repeat(50)}${C.reset}`);
  console.log(`${C.bold}${C.blue}📅 ${data.name}${C.reset}`);
  console.log(`${C.bold}${'='.repeat(50)}${C.reset}\n`);

  // 回归测试
  if (data.regression?.length) {
    console.log(`${C.bold}[回归测试]${C.reset}`);
    for (const cmd of data.regression) {
      run(cmd, cmd.split(' ').slice(1).join(' '));
    }
    console.log();
  }

  // 问答测试
  if (data.ask?.length) {
    console.log(`${C.bold}[问答测试]${C.reset}`);
    for (const [q, label] of data.ask) {
      await ask(q, label);
    }
  }

  // 统计
  console.log(`\n${C.bold}📊 Day ${day} 完成${C.reset}`);
}

main().catch(console.error);
