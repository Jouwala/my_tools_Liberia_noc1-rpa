// ============================================================================
// 数据口径格式化 —— 「数字绝不撒谎」规则的单一实现
// ----------------------------------------------------------------------------
// 项目硬约束（见 docs/AGENTS.md 第二节第 6 条）：
//   「取不到数据必须显示 —，绝不显示 0——统计里的 0 是"真的一个都没有"，
//     与"没取到"必须能分辨，否则运维会误判成"已清空"。」
//
// 此前这条规则散落在各组件里内联书写（如 TaskSyncWidget 的
// `x !== null ? ... : '—'`），改一处漏一处就会破坏"不撒谎"承诺。
// 本模块把规则收敛成纯函数，并配单测（format.test.ts）锁死行为。
// ============================================================================

/** 「取不到」的统一占位符（与既有 UI 保持一致，是 U+2014 em dash） */
export const NO_DATA = '—';

/**
 * 格式化数值指标。
 * @param value 数值；null / undefined / NaN 视为"取不到"
 * @param opts.digits 小数位（默认 0）
 * @param opts.suffix 单位后缀（如 's'），仅在有值时拼接
 * @returns 有值 → "123" / "12.3s"；取不到 → "—"（绝不返回 "0"）
 */
export function formatMetric(
  value: number | null | undefined,
  opts: { digits?: number; suffix?: string } = {}
): string {
  if (value === null || value === undefined || Number.isNaN(value) || !Number.isFinite(value)) {
    return NO_DATA;
  }
  const { digits = 0, suffix = '' } = opts;
  return `${value.toFixed(digits)}${suffix}`;
}

/**
 * 格式化计数（"0 是真的 0"）。
 * 与 formatMetric 的区别：这里 0 是合法且有意义的（如"失败 0 个"），
 * 只有 null/undefined/NaN 才显示 —。
 */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value) || !Number.isFinite(value)) {
    return NO_DATA;
  }
  return String(value);
}

/**
 * 文本占位：空串/全空白/null → —（用于站点名、备注等）。
 */
export function formatText(value: string | null | undefined): string {
  const s = (value ?? '').trim();
  return s ? s : NO_DATA;
}
