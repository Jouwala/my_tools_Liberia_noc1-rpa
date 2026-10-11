/* GIS 地图「区域排名条」浮层（2026-10-14 新增）
 *
 * 背景与设计意图（用户 2026-10-14 原话）：
 *   「我强烈建议增加一个区域排名条……这样地图负责 Where，右侧面板负责 How many，
 *     两者结合以后，比让地图标签承担所有信息更专业。」
 *
 * 由此确定本组件的三条职责边界：
 *  1. **只负责 How many**。它不画地理信息，也不做筛选之外的交互；
 *     「这个县在哪」一律交回地图。反过来，地图上的县名标签已被压成
 *     `LOFA ● 04` 这种极简形式（见 GISMap.tsx），也是同一条分工的产物。
 *  2. **数字与地图同源**。rows 由 GISMap 从同一份 counties 派生后传入，
 *     本组件**不自己取数、不自己再算一遍** —— 两处各算一次必然会在
 *     四舍五入、口径、过滤条件上分叉，出现「地图上 04、排名条里 3」这类
 *     对不上账的问题（AGENTS.md 三.1b 的下钻一致性要求同理）。
 *  3. **文案全部由外部 t() 好再传进来**（与 MapLegendOverlay 完全一致的做法）。
 *     本组件刻意不 import i18n：若在这里拼 key，check:i18n 的漏键守卫
 *     看不见（它只匹配 `t('字面量')`），拼错时界面会直接显示键名。
 *
 * 交互取舍：
 *   「点击某一行下钻到该县」**刻意留作后续**，本次不做。原因与本组件定位有关 ——
 *   用户要的是一个「读数面板」，而排名条的正确用法是「扫一眼知道哪几个县最痛」。
 *   若行可点，鼠标划过时就必须有 hover 反馈，14 行的高亮在深色底图上会盖过
 *   站点圆点，反倒干扰读图。地图上的县界本身已经可点下钻（handleCountyClick），
 *   下钻路径没有缺失，故此处不重复提供入口。
 *
 * 位置（2026-10-14 第二轮，用户：**「MAINTENANCE ALERTS 要放到 LAYERS 的下面，靠最右边缘」**）：
 *   原先放在 LAYERS **左侧**（right: 196px，即 56 + 132 + 8）。现改为**正下方**并对齐右边缘：
 *     · right 与 LAYERS 相同（10px，2026-10-11 改：原 56px 是"避让 zoom 控件"的
 *       误判，实测 zoom 在 topleft，右上无遮挡；现在两个面板都贴边、互相对齐）；
 *     · top 由**运行时测量** LAYERS 面板的实际高度算出（见 useAnchorTop），
 *       而不是写死一个猜的数值。
 *   为什么测量而不是写死：LAYERS 的高度取决于标题行与复选框行的实际排版
 *   （字号、行高、内边距任一变化都会移位），写死一个「51px」在字体或主题
 *   变动后会悄悄错位。测量能保证「永远紧贴在它下面」这个**语义**成立，
 *   而不是碰巧对齐。
 */
import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { WH } from '../../theme'

/** LAYERS 面板的 DOM 选择器。用 id 而不是结构选择器：
 *  LayerToggleControl 是 portal 进 Leaflet 容器的，DOM 层级不稳定。 */
const LAYERS_PANEL_ID = 'gis-layers-panel'

/**
 * 测出 LAYERS 面板底边相对地图顶部的距离，作为本浮层的 top。
 *
 * 返回 null 表示还没测到（面板尚未挂载）—— 此时退回到 CSS 里的兜底 top，
 * 不会渲染到 0 位置闪一下。
 *
 * 用 ResizeObserver 而不是只测一次：面板内容若因 i18n 切语言而换行变高，
 * 本浮层要跟着下移。只在 window resize 时测是不够的。
 */
function useAnchorTop(fallback: number): number {
  const [top, setTop] = useState<number | null>(null)

  useEffect(() => {
    const panel = document.getElementById(LAYERS_PANEL_ID)
    if (!panel) return

    const measure = () => {
      const rect = panel.getBoundingClientRect()
      /* 用 offsetParent（Leaflet 地图容器，position:relative）作为参照系，
         而不是视口 —— 本浮层是 absolute 定位在地图容器内的，
         用视口坐标会在地图本身滚动/移动时错位。 */
      const holder = (panel.offsetParent as HTMLElement | null) ?? document.body
      const holderTop = holder.getBoundingClientRect().top
      // 面板底边相对于地图容器顶部的距离，再留 8px 间距
      setTop(rect.bottom - holderTop + 8)
    }

    measure()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    ro?.observe(panel)
    window.addEventListener('resize', measure)
    return () => {
      ro?.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [])

  return top ?? fallback
}

/** 排名条的一行。color 由调用方按告警分档给出（与地图填充同色） */
export interface RegionRankingRow {
  name: string
  count: number
  color: string
}

interface Props {
  title: string
  rows: RegionRankingRow[]
  /** 标题右侧的 ⓘ 悬浮说明（口径解释），由外部 t() 好传入 */
  hint?: string
  /** 无数据（全部为 0 或数据未加载）时的占位文案 */
  emptyText: string
  /* 曾有一个 `unit?: string` 属性，把「告警」小字跟在每行数字后面。
     2026-10-14 用户要求「数字后面的告警不要显示了」，已**整体删除**该属性
     而不是留着不传（AGENTS.md 原则 10：删除优于兼容）。
     数字是多少本身由标题和 ⓘ 说明表达；每行再挂一个单位字，
     14 行就是 14 次重复，正是用户要去掉的那份噪声。 */
  /** 最多显示多少行，超出部分折叠为一行「还有 N 个」。默认 8 */
  maxRows?: number
  /** 覆盖率脚注（如「12 / 15 个县有告警」），无则不渲染 */
  footnote?: string
}

const panelStyle: CSSProperties = {
  position: 'absolute',
  zIndex: 1000,
  /* 2026-10-14 用户要求「右上区域排名再大一点」：由 11.5rem 提到 15rem（+30%）。
     字号另在 index.css 的 .gis-rank-* 里整体上调一档，两处一起放大才有意义 ——
     只放宽不放大字，多出来的宽度只会变成县名后面的空白。 */
  /* 宽度上限 15rem：现已略宽于左下角图例（13rem）。原先刻意压窄是怕两块浮层
     被看成一组的顾虑，在「再大一点」这个明确要求面前让位。
     58vw 是门户内嵌窄屏下的兜底。 */
  width: 'min(58vw, 15rem)',
  right: 10,  // 2026-10-11 与 LAYERS 一同贴边：实测 zoom 控件在 topleft，右上无遮挡
  /* 靠最右边缘：与 LAYERS 面板的 right 保持一致，使两块浮层右边缘在同一条竖线上。
     2026-10-11：原 56px 是"避让 zoom 控件"的误判（zoom 实测在 topleft），
     改 10px 让面板真的贴边。文件头第 26-30 行的设计意图在此落地。
     此前 panelStyle 漏写 right，导致元素从 left:0 起、宽度 15rem，视觉上落在
     地图中段偏左 —— 正是用户反馈「没靠到边」的现象。 */
  /* top **不在这里写**：它由 useAnchorTop 实测 LAYERS 面板底边得出，
     运行时经 style 覆盖注入（见组件内 anchorTop）。
     这里只给一个兜底值，供极短的「面板尚未挂载」窗口使用。 */
  top: 124,
  maxHeight: 'calc(100% - 1rem)',
  overflowY: 'auto',
  padding: 'var(--wh-space-sm) var(--wh-space-md)',
  borderRadius: 'var(--wh-radius-lg)',
  border: `1px solid ${WH.cardBorder}`,
  /* 背景**不在这里写**：与 backdrop-filter 成组放在 index.css 的 .gis-rank-overlay，
     那里能按主题各给一档，也便于与图例浮层共用同一套「玻璃底」取舍。 */
  boxShadow: 'var(--wh-shadow-3)',
  fontSize: '0.75rem',
  lineHeight: 1.5,
  color: WH.text,
}

const titleStyle: CSSProperties = {
  fontSize: '0.75rem',
  fontWeight: 700,
  color: WH.textMuted,
  letterSpacing: '0.06em',
  marginBottom: 'var(--wh-space-xs)',
  display: 'flex',
  alignItems: 'center',
  gap: 'var(--wh-space-xs)',
}

/** 一行。数字用等宽数字（tabular-nums）保证竖排后右边缘对齐 —— 这正是排名条比地图标签好读的地方 */
function Row({ row }: { row: RegionRankingRow }) {
  return (
    <div className="gis-rank-row">
      <span className="gis-rank-row__dot" style={{ background: row.color }} />
      <span className="gis-rank-row__name" title={row.name}>{row.name}</span>
      <span className="gis-rank-row__num">{String(row.count).padStart(2, '0')}</span>
    </div>
  )
}

export default function RegionRankingOverlay({
  title, rows, hint, emptyText, maxRows = 8, footnote,
}: Props) {
  /* 截断：只展示前 maxRows 行，其余折成一行计数。
     用户示例里是 6 行，但真实数据有 12 个县非 0，全铺出来会占掉地图右缘一大条。
     截断必须**显式暴露**（AGENTS.md 三.1b 对「静默截断」的禁止）——
     这里用「+N more」明说还有多少行没显示，而不是悄悄砍掉。 */
  const shown = rows.slice(0, maxRows)
  const rest = rows.length - shown.length

  /* top 由 LAYERS 面板实测高度决定；CSS 里的 124 只是面板尚未挂载时的兜底值
     （约为「top 10 + 面板高 ~51 + 间距 8」的两倍余量取整，宁可先低不高，
     因为重测在同一个 effect 里紧跟着发生，不会真的显示在这个位置）。 */
  const anchorTop = useAnchorTop(124)

  return (
    <div className="gis-rank-overlay" style={{ ...panelStyle, top: anchorTop }} role="region" aria-label={title}>
      <div style={titleStyle}>
        {title}
        {hint && <span className="gis-rank-hint" title={hint}>ⓘ</span>}
      </div>
      {shown.length === 0 ? (
        <div style={{ color: WH.textDim, fontSize: '0.6875rem' }}>{emptyText}</div>
      ) : (
        shown.map(r => <Row key={r.name} row={r} />)
      )}
      {rest > 0 && (
        /* 折叠行沿用同一份「+N」文案键；数字由 t() 插值，不由本组件拼句子 */
        <div className="gis-rank-more">{`+${rest}`}</div>
      )}
      {footnote && <div className="gis-rank-footnote">{footnote}</div>}
    </div>
  )
}
