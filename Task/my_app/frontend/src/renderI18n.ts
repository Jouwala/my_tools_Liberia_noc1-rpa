/* ============================================================================
 * renderI18n.ts —— 把规则层产出的 `I18nText` 解析成最终字符串
 * ============================================================================
 *
 * 【为什么需要这一层】
 *   `pages/vmaxDiagnosisRules.ts` 是纯函数（不依赖 React，可单测），拿不到 `t()`。
 *   它产出的结论 / 证据 / 建议都是要显示给人看的文案，所以只能返回结构化描述
 *   `{ key, params }`，由渲染层翻译。这个文件就是那个「渲染层翻译器」。
 *
 * 【为什么要支持嵌套】
 *   有些句子本身含一句可变短语，例如
 *     「无线侧不可判：{{why}}」  其中 why 又是「RAN 域无记录」
 *   规则层不知道当前语言，无法先把 why 翻好再拼。所以 params 允许放 I18nText，
 *   这里递归解析。递归只发生在 params 上，深度有限（实际最多 2 层），不需要防环。
 *
 * 【为什么不直接返回 t(key, params)】
 *   直接传会得到 `[object Object]` —— t() 内部 `String(v)`。必须先就地展开。
 *
 * 【为什么不 import I18nText 类型】
 *   本文件只负责「翻译」，不应该反向依赖某个业务模块的类型（会形成
 *   rules ←→ render 的双向依赖）。这里按结构判断，任何形如 `{key, params}`
 *   的对象都能解析。
 * ========================================================================== */

/** 结构化文案：字典键 + 插值参数（参数可再嵌套一层同结构） */
export type Translatable = {
  key: string
  params?: Record<string, string | number | Translatable>
}

type TFn = (key: string, params?: Record<string, string | number>) => string

/** 按结构判断是不是 Translatable（不依赖具体类型定义） */
export function isTranslatable(v: unknown): v is Translatable {
  return !!v && typeof v === 'object' && typeof (v as Translatable).key === 'string'
}

/**
 * 把 Translatable 解析成当前语言的字符串。
 *
 * @param t    useI18n() 返回的 t
 * @param v    Translatable / 普通字符串 / null
 * @returns    可直接渲染的字符串；null/undefined 返回空串
 */
export function renderI18n(
  t: TFn,
  v: Translatable | string | number | null | undefined,
): string {
  if (v === null || v === undefined) return ''
  // 数字原样转字符串：调用方常把「数值 | 文案」放同一字段（如时长、计数），
  // 让调用点不必自己分支。
  if (typeof v === 'string' || typeof v === 'number') return String(v)

  // 先递归把嵌套的 Translatable 参数展开成字符串
  const flat: Record<string, string | number> = {}
  if (v.params) {
    for (const [k, pv] of Object.entries(v.params)) {
      flat[k] = isTranslatable(pv) ? renderI18n(t, pv) : pv
    }
  }
  return t(v.key, Object.keys(flat).length ? flat : undefined)
}

/** 批量解析（证据行、依据行这类数组） */
export function renderI18nList(
  t: TFn,
  list: (Translatable | string | number)[] | null | undefined,
): string[] {
  if (!list) return []
  return list.map((v) => renderI18n(t, v))
}
