/* ==================== 轻量富文本：**强调** → 加粗 ====================
 * 为什么需要：
 *   口径说明、图例备注这类长文案是从手册/复盘里搬过来的，天然带 Markdown 的
 *   `**强调**` 标记。而它们大多这样渲染：`{t('some.key')}` —— React 把字符串
 *   原样输出，于是界面上直接看到 ** 星号本身。
 *   2026-11-02 实测：`?page=avail_county` 展开「口径说明」后显示
 *   「站点按**名称**关联站点主数据」，星号裸露；全站 i18n 里同类文案共 50+ 处
 *   （`nur.calcNote.*` 十余条、`gis.rankHint`、`person.siteLegend.*` 等）。
 *
 * 用法：
 *   - JSX 文本节点  → `{renderRich(t('key'))}`     （星号变成 <strong>）
 *   - HTML 属性/复制 → `stripBold(t('key'))`        （星号直接去掉，属性里不能放标签）
 *
 * 边界：只认 `**...**`，不解析标题/列表/链接 —— 够用即可，别在这里长成半个 Markdown 解析器。
 * ================================================================== */
import { Fragment, type ReactNode } from 'react'

/** 带捕获组的 split：分隔符 `**...**` 会保留在结果数组里 */
const BOLD_RE = /(\*\*[^*\n]+\*\*)/g

/** 渲染成 ReactNode：`**x**` → 加粗，其余原样（换行仍交给容器的 pre-line） */
export function renderRich(text?: string | null): ReactNode {
  if (!text) return text ?? ''
  if (!text.includes('**')) return text
  return text.split(BOLD_RE).map((part, i) => {
    if (part.length > 4 && part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i} style={{ fontWeight: 600 }}>{part.slice(2, -2)}</strong>
    }
    return <Fragment key={i}>{part}</Fragment>
  })
}

/** 纯文本场景（HTML title 属性、写入剪贴板）：去掉标记本身，不保留强调 */
export function stripBold(text?: string | null): string {
  return (text || '').replace(/\*\*/g, '')
}
