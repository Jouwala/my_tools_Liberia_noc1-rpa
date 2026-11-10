/**
 * my_app 目录与规则源文件清单 —— JS 侧的单一真相源。
 *
 * ## 为什么单独成模块
 *
 * 同一个「规则表在哪」的事实现在有三个消费者：
 *   · `scripts/sync-kb.mjs`      —— 算指纹、判断要不要重建知识库；
 *   · `src/index.js` 的 ping     —— 判断规则表是否比知识库新；
 *   · `src/ruleSourceFreshness.js` —— 纯函数判据（不读盘，但语义要与之一致）。
 *
 * Python 侧另有一份 `scripts/my_app_paths.py`，那是给 tt-analyze.py 用的，
 * 解析策略相同但语言不同 —— 改候选路径时**两处都要看**。
 *
 * ## 解析策略（与 my_app_paths.py 一致）
 *
 *   1. 环境变量 `MY_APP_DIR` —— 显式指定，最高优先级；
 *   2. 仓库内并排布局 `../../my_app` —— 与盘符无关，换机也成立；
 *   3. 已知盘符兜底（.20 的 D 盘、.19 的 Y 盘映射）。
 *
 * 找不到时返回 null，由调用方决定如何降级（鲜度提示直接不显示）。
 */
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url)); // <bot>/src
export const BOT_ROOT = resolve(HERE, '..');

/** 仓库根：src -> whatsapp-kb-bot -> Task -> 仓库根 */
export const REPO_ROOT = resolve(HERE, '..', '..', '..');

/**
 * 本仓库是不是「便携副本」（根目录有 ISOLATED_COPY.flag）。
 *
 * 便携副本（D:\01_olbr_portal）必须**完全自包含**：它有自己的 my_app、
 * 自己的 app.db、自己的 runtime。若副本在找不到自己的 my_app 时回落到
 * D:/01_RPA/Task/my_app，就会读到**生产库的工单数据** —— 数据串库，
 * 而且是静默的（查询能返回结果，只是结果是生产的）。
 *
 * 所以副本里禁用一切「指向仓库之外」的候选；找不到就返回 null。
 * 主仓库没有这个 flag，行为与收口前完全一致。
 */
function isIsolatedCopy() {
  try {
    return existsSync(join(REPO_ROOT, 'ISOLATED_COPY.flag'));
  } catch {
    return false;
  }
}

/**
 * 规则源文件（相对 my_app 根）。
 * 与 `scripts/export-tt-knowledge.py` 读取的是同一批 —— 加新导出源要两处一起改。
 */
export const RULE_SOURCE_FILES = [
  ['backend', 'services', 'eflow_rules', 'eflow_alarm_rules.xlsx'],
  ['backend', 'services', 'eflow_rules', 'eflow_TT_rules.xlsx'],
  ['backend', 'services', 'eflow_rules', 'eflow_push_rules.xlsx'],
  ['data', 'eflow_tt_alarm_code_distinct.xlsx'],
];

let cached;

/** 返回 my_app 根目录；找不到返回 null。结果缓存（进程内路径不会变）。 */
export function myAppDir() {
  if (cached !== undefined) return cached;
  const candidates = [
    process.env.MY_APP_DIR,
    resolve(BOT_ROOT, '..', 'my_app'), // 仓库内并排布局
  ].filter(Boolean);
  // 指向仓库之外的候选（历史部署的盘符）。便携副本下必须禁用 ——
  // 见 isIsolatedCopy() 的说明：落到生产库是静默的数据串库。
  if (!isIsolatedCopy()) {
    candidates.push(
      'D:/01_RPA/Task/my_app', // 本机 .20
      'Y:/Task/my_app',        // 历史部署（.19 的 E 盘映射）
    );
  }
  cached = candidates.find((c) => {
    try {
      return existsSync(c) && existsSync(join(c, 'backend', 'services', 'eflow_rules'));
    } catch {
      return false;
    }
  }) ?? null;
  return cached;
}
