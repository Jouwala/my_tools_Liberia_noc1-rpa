/**
 * 定位可用的 Python 解释器 —— 让 bot 不绑死某一台机器的安装路径。
 *
 * ## 为什么需要这个模块
 *
 * 原先有 5 个模块各自硬编码同一个解释器路径：
 *
 *     C:/Users/ZTEEMS/AppData/Local/Programs/Python/Python312/python.exe
 *
 * 涉及 `src/tt.js`、`src/eflowRules.js`、`src/sitealarms.js`、
 * `src/siteattr.js`、`src/ttsource.js`。那个路径在便携副本
 * （`D:\01_olbr_portal`）上**同样存在**（同一个 Windows 用户），所以副本
 * 表面上「能跑」—— 但副本自带 `runtime/python312/python.exe`，副本要能
 * 脱离本机 Python 安装独立运行，就不该优先用系统安装。
 *
 * 2026-11-10：便携化收口。
 *
 * ## 解析策略（按优先级，与 scripts/python_path.py 一致）
 *
 *   1. 环境变量 `TT_PYTHON` —— 显式指定，最高优先级；
 *   2. **仓库自带的 runtime** —— `<仓库根>/runtime/python312/python.exe`。
 *      便携副本用它（副本根目录才有 `runtime/`），版本与系统安装一致
 *      （3.12.x），site-packages 齐备（实测含 openpyxl / pandas / sqlalchemy）；
 *   3. **系统 Python 3.12** —— `C:/Users/<用户>/AppData/Local/Programs/
 *      Python/Python312/python.exe` 与 `C:/Python312/python.exe`。
 *      生产仓库靠这一档（它没有 `runtime/`）；
 *   4. **my_app 内嵌 venv** —— `<仓库根>/Task/my_app/Scripts/python.exe`，
 *      最后兜底（3.13，与前两档大版本不同，只在前面的都缺时才启用）。
 *
 * ## 为什么不做「同步时改写」
 *
 * 硬编码路径也可以靠同步脚本改写成副本路径，但那样**同一份源码在两个目录
 * 下内容不同**：复制、比对、diff 全都失真，改写脚本一旦漏改就是隐蔽故障。
 * 从代码自身位置推导则两边共用同一份源码、行为等价 —— 这是本次收口的主线。
 *
 * ## 为什么把「系统 Python」排在「my_app venv」前面
 *
 * 生产仓库的 bot 一直用系统 Python 3.12 运行；my_app 内嵌 venv 是 3.13，
 * 大版本不同。收口是便携化改造，**不应顺带改变生产的行为**，所以 venv
 * 只作兜底。
 */
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url)); // <bot>/src

/** <bot>/src -> <bot> -> Task -> 仓库根 */
export const REPO_ROOT = resolve(HERE, '..', '..', '..');

/** 候选的解释器（按优先级）。路径一律从仓库根推导，与盘符无关。 */
const CANDIDATES = [
  join(REPO_ROOT, 'runtime', 'python312', 'python.exe'), // 便携副本自带
  'C:/Users/ZTEEMS/AppData/Local/Programs/Python/Python312/python.exe',
  'C:/Python312/python.exe',
  join(REPO_ROOT, 'Task', 'my_app', 'Scripts', 'python.exe'), // venv 兜底
];

/**
 * 返回可用的 Python 解释器路径。
 *
 * @param {string[]} [envNames] 额外检查的环境变量名（按传入顺序，优先级最高）。
 *   例：`resolvePython(['EFLOW_RULE_PYTHON', 'TT_PYTHON'])`。
 * @returns {string}
 */
export function resolvePython(envNames = ['TT_PYTHON']) {
  for (const name of envNames) {
    const v = process.env[name];
    if (v) return v;
  }
  for (const cand of CANDIDATES) {
    try {
      if (existsSync(cand)) return cand;
    } catch {
      // 忽略：路径不可访问时继续试下一个
    }
  }
  // 一个候选都不可用时回落到第一个（系统 Python）——
  // 让调用方的报错信息指向「解释器不可用」而不是「路径未定义」。
  return CANDIDATES[0];
}

/** 默认解释器：与 scripts/python_path.py 的解析结果保持一致。 */
export const PYTHON = resolvePython();
