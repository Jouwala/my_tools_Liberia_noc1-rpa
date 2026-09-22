/* ============================================================================
 * components/cards —— 项目统一卡片入口（唯一推荐的卡片导入路径）
 * ----------------------------------------------------------------------------
 * 页面里**只从这个 barrel 导入卡片**，不要 `import { Card } from 'antd'`，
 * 也不要在页面内自己写 `style={cardStyle}` 的裸卡片：
 *
 *   ❌ import { Card } from 'antd'
 *      <Card title={...} style={cardStyle}>...</Card>
 *   ✅ import { CardBase, StatCard } from '../components/cards'
 *      <CardBase title="标题">...</CardBase>
 *
 * 为什么要有这层：卡片的外观（皮肤令牌 / 等级染色 / 悬停效果）必须**只有一处可改**。
 * 此前每个页面各自 `style={cardStyle}` 甚至内联 background/border/borderRadius，
 * 结果是「统一换卡片风格」要改 40+ 个文件、且总有几处改不动（行内样式优先级高于 CSS）。
 * 收敛到本目录后，改样式只动 CardBase.tsx 与 index.css 的令牌。
 *
 * 组件分工：
 *   CardBase  —— 皮肤外壳，任意内容（图表 / 表格 / 表单 / 列表）都用它
 *   StatCard  —— 数字卡，在 CardBase 皮肤之上加「标题 + 大数字 + 图标」结构
 *   CardTitle —— 项目统一的卡头文字排版（此前在 12 处各写一份内联 span）
 *
 * 相关约定见 Task/my_app/component-api.md 与 DESIGN.md。
 * ========================================================================== */

export { default as CardBase, CardTitle } from './CardBase'
export type { CardBaseProps, CardLevel } from './CardBase'

/* StatCard 的实现在 src/components/StatCard.tsx（历史位置，4 个页面已在用）。
 * 这里只做转出，**不复制实现** —— 保证「同一张卡片只有一个定义」，
 * 也避免改动 src/components/StatCard.tsx 时忘了同步副本。
 * 新代码请统一从本 barrel 导入，旧位置保留仅为不改动既有调用方。 */
export { default as StatCard } from '../StatCard'
