/**
 * 全站统一的日期时间格式：ISO `YYYY-MM-DD HH:mm:ss`（24 小时制）。
 *
 * 时区口径：后端进程与调度器都跑在 UTC 服务器上（naive `datetime.now()` 即 UTC），
 * 因此不带偏移的字符串一律按 UTC 解读并原样呈现；带 `Z` / `±hh:mm` 的按其自身偏移换算到 UTC。
 * 展示层不再用 `toLocaleString`，否则浏览器区域设置会把同一时刻渲染成 12 小时制或 M/D 顺序。
 */

export const TZ_UTC = 'UTC'

const pad2 = (n: number) => String(n).padStart(2, '0')

/** 解析后端时间：number 视为 Unix 秒；naive 字符串视为 UTC。解析失败返回 null。 */
export function parseServerDate(value: string | number | Date | null | undefined): Date | null {
  if (value == null || value === '') return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return null
    const d = new Date(value * 1000)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const raw = String(value).trim()
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
  // JS 会把不带偏移的 date-time 按浏览器本地时区解析，这里补 Z 强制成 UTC。
  const iso = raw.replace(' ', 'T')
  const d = new Date(hasZone ? iso : `${iso}Z`)
  return Number.isNaN(d.getTime()) ? null : d
}

/**
 * 格式化为 `YYYY-MM-DD HH:mm:ss`（UTC）。
 * @param opts.seconds 默认带秒；语音播报等紧凑场景可关闭
 * @param opts.zone    是否在末尾追加 `UTC` 标注
 * @param opts.fallback 解析失败时的占位文本，默认 `-`
 */
export function formatDateTime(
  value: string | number | Date | null | undefined,
  opts: { seconds?: boolean; zone?: boolean; fallback?: string } = {},
): string {
  const { seconds = true, zone = false, fallback = '-' } = opts
  const d = parseServerDate(value)
  if (!d) return fallback
  const date = `${d.getUTCFullYear()}-${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())}`
  const time = `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}${seconds ? `:${pad2(d.getUTCSeconds())}` : ''}`
  const out = `${date} ${time}`
  return zone ? `${out} ${TZ_UTC}` : out
}

/** 只取日期部分：`YYYY-MM-DD`（UTC）。 */
export function formatDate(value: string | number | Date | null | undefined, fallback = '-'): string {
  return formatDateTime(value, { seconds: false, fallback }).slice(0, 10) || fallback
}
