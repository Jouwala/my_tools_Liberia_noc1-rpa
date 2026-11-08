#!/usr/bin/env node
/**
 * 分支卫生守卫 —— 零第三方依赖，CI 跑在 GitHub Actions 上。
 *
 * 目的（docs/git-workflow.md 第 2、3 节）：
 *   - master 只能走 PR 合入（分支保护在 Web 侧，本脚本守的是 PR 内容）
 *   - 一个 PR 只含一个业务功能；diff > 50 文件必须说明
 *   - 提交信息必须带模块前缀；禁止 feat(workspace) / 汇总提交
 *
 * 环境变量：
 *   GITHUB_BASE_SHA / GITHUB_HEAD_SHA — PR 的 base/head SHA（CI 自动给）
 *   BRANCH_FILE_LIMIT — 默认 50
 *   ALLOW_LARGE_DIFF=1 — 紧急豁免（仅本地临时用）
 *
 * 失败码：1（CI red），并打印修复方法。
 */
import { execSync } from 'node:child_process';

const FILE_LIMIT = Number(process.env.BRANCH_FILE_LIMIT ?? '50');
const FORBIDDEN_SUBJECTS = ['workspace', '汇总', 'wip', '杂项', 'misc', 'all'];

function run(cmd) {
  return execSync(cmd, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

function fail(msg, hint) {
  console.error(`✗ ${msg}`);
  if (hint) console.error(`  修复: ${hint}`);
  process.exitCode = 1;
}

const base = process.env.GITHUB_BASE_SHA;
const head = process.env.GITHUB_HEAD_SHA;
if (!base || !head) {
  console.error('缺少 GITHUB_BASE_SHA / GITHUB_HEAD_SHA（仅限 CI 运行；本地请用 --base --head 传参）');
  process.exit(2);
}

console.log(`branch-hygiene: ${base.slice(0, 7)}...${head.slice(0, 7)}`);

// 1) diff 文件数
let files = [];
try {
  files = run(`git diff --name-only ${base}...${head}`).split('\n').filter(Boolean);
} catch { files = []; }
console.log(`diff files: ${files.length} (limit ${FILE_LIMIT})`);
if (files.length > FILE_LIMIT && process.env.ALLOW_LARGE_DIFF !== '1') {
  fail(`diff ${files.length} 文件 > ${FILE_LIMIT}，一个 PR 只允许一个业务功能`,
    `按 docs/git-workflow.md 第 5 节拆：git log --name-only ${base}..${head} 按模块分组后逐组开 PR`);
}

// 2) 提交信息前缀
let subjects = [];
try {
  subjects = run(`git log --format=%s ${base}..${head}`).split('\n').filter(Boolean);
} catch { subjects = []; }
for (const s of subjects) {
  const m = s.match(/^(feat|fix|docs|refactor|test|chore)\(([a-z0-9_\u4e00-\u9fff-]+)\):?\s+\S+/i);
  if (!m) {
    fail(`提交信息缺模块前缀: "${s}"`, `格式: feat(vmax): ... / fix(portal): ...`);
    continue;
  }
  const mod = m[2].toLowerCase();
  if (FORBIDDEN_SUBJECTS.includes(mod)) {
    fail(`禁止使用含糊模块名 "${mod}"（${s}）`, `用具体模块：vmax/portal/whatsapp/eflow/ipt/gis/feedback/myapp/governance`);
  }
}

// 3) 单提交文件数（拦截 eaf3e573 式打包提交）
if (files.length <= FILE_LIMIT) {
  let shas = [];
  try { shas = run(`git log --format=%H ${base}..${head}`).split('\n').filter(Boolean); } catch {}
  for (const sha of shas) {
    let n = 0;
    try { n = Number(run(`git diff-tree --no-commit-id --name-only -r ${sha}`).split('\n').filter(Boolean).length) || 0; } catch {}
    if (n > FILE_LIMIT) {
      fail(`单提交 ${sha.slice(0,7)} 触及 ${n} 文件（疑似跨域打包）`,
        `拆成多个带前缀的小提交：git reset --soft <base> 后逐域重提`);
    }
  }
}

if (!process.exitCode) console.log('✓ branch-hygiene PASS');
else console.error('branch-hygiene FAIL：请按 docs/git-workflow.md 拆分后重推');
