#!/usr/bin/env node
/**
 * 用 my_app 的 Python 解释器跑指定脚本，透传命令行参数。
 *
 * 存在的意义：tt-analyze.py / export-tt-knowledge.py 依赖 openpyxl
 * （装在 my_app 的 Lib/site-packages，而 my_app 内嵌 venv 的 shim 已失效），
 * 在 package.json 里写死一长串解释器路径既难读也难改，统一收在这里。
 *
 * 用法：
 *   npm run tt -- TT202609150073
 *   npm run export-kb
 *
 * 解释器可用环境变量 TT_PYTHON 覆盖。
 */
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

const PYTHON =
  process.env.TT_PYTHON ||
  'C:/Users/ZTEEMS/AppData/Local/Programs/Python/Python312/python.exe';

const [script, ...rest] = process.argv.slice(2);
if (!script) {
  console.error('用法：npm run <cmd> -- <py脚本名> [参数...]');
  process.exit(2);
}

const target = resolve(HERE, script);
if (!existsSync(target)) {
  console.error(`找不到脚本：${target}`);
  process.exit(2);
}
if (!existsSync(PYTHON)) {
  console.error(
    `找不到 Python 解释器：${PYTHON}\n` +
      `可用环境变量 TT_PYTHON 指定正确的路径。`
  );
  process.exit(2);
}

const child = spawn(PYTHON, [target, ...rest], { stdio: 'inherit' });
child.on('exit', (code) => process.exit(code ?? 1));
child.on('error', (err) => {
  console.error(`启动 Python 失败：${err.message}`);
  process.exit(1);
});
