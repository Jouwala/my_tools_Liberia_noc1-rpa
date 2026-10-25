/**
 * 规则源文件新鲜度 —— 回答「my_app 那边的规则表，比我们知识库同步过的时间还新吗」。
 *
 * ## 为什么需要（第三种「用旧资料」的情形）
 *
 * bot 已有两种「看起来在跑、其实用旧的」检测：
 *   · 代码指纹（`isStale`）—— 改了源码没重启；
 *   · 索引新鲜度（`indexFreshness.js`）—— 改了 knowledge/ 没 ingest/重启。
 *
 * 2026-10-23 出现第三种：**eFlow 规则本身更新了**，规则采集把
 * `eflow_push_rules.xlsx` 等 xlsx 写到了 my_app，但 `knowledge/` 下的 md
 * 还是上一版导出的 —— 磁盘 md 与索引完全一致（前两种检测都报「正常」），
 * bot 却一直在按旧规则回答。这类问题前两种检测**永远发现不了**。
 *
 * ## 判据
 *
 * 拿四个规则源 xlsx 里**最新**的 mtime，与 `data/kb_sync_state.json` 记录的
 * `syncedAt`（上次成功同步的时刻）比。源文件更新 → 说明知识库落后了。
 *
 * 没用「xlsx 指纹」而用时间，是为了让这个模块保持**纯函数**、便于离线单测；
 * 指纹比对留给真正执行同步的 `scripts/sync-kb.mjs`。
 *
 * ## 不抛异常是硬要求
 *
 * 与索引新鲜度同一取舍：这属于**旁路质量问题**，不该让 `ping` 挂掉。
 * 任何读盘/解析失败都返回 null（= 不提示）。
 */

/**
 * @param {{sourceMtimeMs:number|null, syncedAtMs:number|null, graceMs?:number}} input
 * @returns {string|null} 需要提示时返回一行中文；否则 null
 */
export function ruleSourceWarning({ sourceMtimeMs, syncedAtMs, graceMs = 0 }) {
  // 任一信息缺失就不判断：宁可漏报，也不要误报吓人
  if (!Number.isFinite(sourceMtimeMs) || !Number.isFinite(syncedAtMs)) return null;
  // 留宽限：同步脚本写完状态到 xlsx 落盘之间存在秒级抖动
  if (sourceMtimeMs <= syncedAtMs + graceMs) return null;

  const hours = Math.round(((sourceMtimeMs - syncedAtMs) / 3600000) * 10) / 10;
  const lag = hours >= 1 ? `约 ${hours} 小时` : '不到 1 小时';
  return `⚠️ 规则表比知识库新（落后${lag}）—— 知识库问答仍按旧规则回答。定时任务会自动同步；急用可手动跑 scripts/sync-kb.mjs`;
}

/**
 * 从磁盘读出现实数据并调用上面的纯函数。读不到一律返回 null。
 *
 * @param {(p:string)=>Date|null} readSyncedAt  注入，便于单测
 * @param {number|null} sourceMtimeMs
 * @returns {string|null}
 */
export function checkRuleSourceFreshness(readSyncedAt, sourceMtimeMs) {
  try {
    const d = readSyncedAt();
    return ruleSourceWarning({
      sourceMtimeMs,
      syncedAtMs: d instanceof Date && !Number.isNaN(d.getTime()) ? d.getTime() : null,
    });
  } catch {
    return null;
  }
}
