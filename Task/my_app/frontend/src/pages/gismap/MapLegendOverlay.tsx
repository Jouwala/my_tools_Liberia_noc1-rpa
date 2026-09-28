/* GIS 地图图例浮层（2026-09-28 新增）
 *
 * 背景与取舍（用户 2026-09-28 要求：「图例直接在地图上显示，竖排」；
 * 位置先按「地图的最右边」做了右上，同日又按用户要求改为**左下**）：
 *  1. 图例原先是控制卡片里的一横排。站点/分档一多就要和工具栏争横向空间，
 *     而真正「边看图边对色」的人在看地图 —— 所以移到地图上，靠右竖排。
 *  2. **点击隐藏的能力必须保留**：控制卡片里那套「点图例 = 隐藏该类站点」
 *     是既有能力（normal 默认隐藏、点一下即可恢复），换位置不能把能力丢掉。
 *     故这里沿用 role="switch" + aria-checked，行为与无障碍语义与迁移前一致，
 *     并补了 Enter/Space 键盘操作（迁移前没有，属顺带增强）。
 *  3. **z-index 取 1000**：Leaflet 的 pane 层级是
 *     tile 200 < overlay 400 < shadow 500 < marker 600 < tooltip 650 < popup 700 < control 1000。
 *     取 1000 才能盖住站点圆点(600)与常驻县名标注(650)；与 Leaflet 控件同层，
 *     而本浮层在 DOM 中位于地图容器**之后**，同层时后者胜，故仍显示在控件之上。
 *     已知代价：站点弹窗(popup, 700)也会被本浮层压住。这是刻意接受的 ——
 *     Leaflet 会自动把弹窗平移进视野，且「图例被弹窗挡住」比这更难用。
 *  4. 配色一律走 WH / --wh-* 令牌，深浅色自动跟随，不写死十六进制（AGENTS.md 三.3）。
 *  5. 背景加 backdrop-filter：地图瓦片纹理很杂，纯半透明底会让小字读不清。
 *
 * ⚠️ 本组件刻意**不引用 i18n**：所有文案（标题、行标签、口径说明）都由 GISMap 先
 *    `t()` 好再传进来。这样 `check:i18n` 的漏键守卫仍能在 GISMap.tsx 里看见字面量键；
 *    若在这里写 `t('gis.legend.' + key)` 这类拼接，守卫看不见、拼错时只会界面显示键名。
 */
import type { CSSProperties } from 'react'
import { WH } from '../../theme'
import { ExplainIcon } from '../../components/MetricExplain'

/** 一行图例。dot = 站点圆点；line = MW 链路实线；dashed = 无 KPI 链路虚线 */
export interface MapLegendRow {
  id: string
  color: string
  label: string
  count: number
  shape?: 'dot' | 'line' | 'dashed'
  /** 被点击隐藏（仅站点类别行会传）：置灰 + 删除线 */
  hidden?: boolean
  /** 隐藏时跟在计数后的小字（如「已隐藏」） */
  hiddenNote?: string
  /** 原生 hover 提示：给「History」这类名字看不出覆盖范围的条目补充说明。
      用原生 title 而不是自绘气泡 —— 浮层已在 Leaflet 之上，
      再叠一层气泡要自己处理定位与层级，收益不值这个复杂度。 */
  hint?: string
  /** 传了才可点击。MW 链路图例不传 —— 它不参与显隐控制，画成可点会误导 */
  onClick?: () => void
}

interface Props {
  title: string
  rows: MapLegendRow[]
  /** MW 链路利用率分组；无数据时整块不渲染 */
  utilTitle?: string
  utilRows?: MapLegendRow[]
  /** 利用率口径说明（匹配链路数 / 总链路数 / 数据槽位） */
  utilNote?: string
  /** 站点计数口径说明 */
  note?: string
}

const panelStyle: CSSProperties = {
  position: 'absolute',
  /* 2026-09-28 用户要求从右上移到**左下**。
     左下角选得开：Leaflet 的默认控件是 zoom（左上）与 attribution（右下），
     本页也没有别的左下覆盖物，不会互相遮挡。
     用 bottom 而不是 top：浮层高度随图例条数变化，贴底能让它向上生长，
     无论 3 条还是 12 条都稳定贴着同一条边；贴顶则要先算高度才知道底部会不会出界。
     注意 maxHeight 用的是 100%（相对地图 Card 的 body），改左下后仍然成立。 */
  bottom: 'var(--wh-space-sm)',
  left: 'var(--wh-space-sm)',
  zIndex: 1000,
  // 上限 13rem：再宽就会压掉地图上的站点；58vw 是窄屏（门户内嵌）时的兜底
  width: 'min(58vw, 13rem)',
  maxHeight: 'calc(100% - 1rem)',
  overflowY: 'auto',
  padding: 'var(--wh-space-sm) var(--wh-space-md)',
  borderRadius: 'var(--wh-radius-lg)',
  border: `1px solid ${WH.cardBorder}`,
  background: WH.cardBg,
  boxShadow: 'var(--wh-shadow-3)',
  backdropFilter: 'blur(8px)',
  WebkitBackdropFilter: 'blur(8px)',
  fontSize: '0.75rem',
  lineHeight: 1.5,
  color: WH.text,
}

const groupTitleStyle: CSSProperties = {
  fontSize: '0.6875rem',
  fontWeight: 600,
  color: WH.textMuted,
  letterSpacing: '0.02em',
  marginBottom: 'var(--wh-space-xs)',
  /* flex 是为了让 ⓘ 图标与标题文字居中对齐（ExplainIcon 是 inline 元素，
     直接跟在文字后面会与基线错位） */
  display: 'flex',
  alignItems: 'center',
  gap: 'var(--wh-space-xs)',
}

/** 色块。三种形状统一放在 18px 宽的定宽容器里居中，保证竖排后文字左边缘对齐 */
function Swatch({ row }: { row: MapLegendRow }) {
  if (row.shape === 'line') {
    return <span style={{ display: 'inline-block', width: 18, height: 3, borderRadius: 2, backgroundColor: row.color }} />
  }
  if (row.shape === 'dashed') {
    return <span style={{ display: 'inline-block', width: 18, height: 0, borderTop: `2px dashed ${row.color}` }} />
  }
  return <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', backgroundColor: row.color }} />
}

function Row({ row }: { row: MapLegendRow }) {
  const clickable = typeof row.onClick === 'function'
  const style: CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: 'var(--wh-space-xs)',
    padding: '2px 0',
    color: WH.text,
    opacity: row.hidden ? 0.45 : 1,
    cursor: clickable ? 'pointer' : 'default',
    userSelect: 'none',
    transition: 'opacity 0.2s',
  }
  const content = (
    <>
      <span style={{ width: 18, display: 'inline-flex', justifyContent: 'center', flex: '0 0 auto' }}>
        <Swatch row={row} />
      </span>
      <span style={{ flex: '1 1 auto', textDecoration: row.hidden ? 'line-through' : 'none' }}>
        {row.label} ({row.count})
      </span>
      {row.hidden && row.hiddenNote && (
        <span style={{ fontSize: '0.625rem', color: WH.textDim, flex: '0 0 auto' }}>{row.hiddenNote}</span>
      )}
    </>
  )
  if (!clickable) return <div style={style} title={row.hint}>{content}</div>
  return (
    <span
      role="switch"
      aria-checked={!row.hidden}
      aria-label={`${row.label} (${row.count})`}
      title={row.hint}
      tabIndex={0}
      onClick={row.onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          row.onClick?.()
        }
      }}
      style={style}
    >
      {content}
    </span>
  )
}

export default function MapLegendOverlay({ title, rows, utilTitle, utilRows, utilNote, note }: Props) {
  const hasUtil = !!utilTitle && !!utilRows && utilRows.length > 0
  /* 口径说明默认**收进 ⓘ 悬浮气泡**，不再常驻占版面（2026-09-28 用户要求「这些备注能隐藏吗」）。
     这两段话（利用率来源与槽位、图例数字口径）只在「第一次看不懂时」有用，
     常驻却要占掉图例浮层 4~5 行高度 —— 浮层压在瓦片上，每多一行就多挡一块地图。
     改用项目统一的 ExplainIcon（与各看板指标卡的 ⓘ 同一个组件、同一种交互），
     需要时悬停即可看全文，还顺带获得「一键复制说明」。 */
  return (
    <div style={panelStyle} role="region" aria-label={title}>
      <div style={groupTitleStyle}>
        {title}
        {note && <ExplainIcon text={note} size={12} placement="right" />}
      </div>
      {rows.map(r => <Row key={r.id} row={r} />)}
      {hasUtil && (
        <>
          <div style={{ ...groupTitleStyle, marginTop: 'var(--wh-space-sm)' }}>
            {utilTitle}
            {utilNote && <ExplainIcon text={utilNote} size={12} placement="right" />}
          </div>
          {(utilRows || []).map(r => <Row key={r.id} row={r} />)}
        </>
      )}
    </div>
  )
}
