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
 *     例外：面板背景（见第 6 条）按主题各写一条 rgba，落在 index.css 的
 *     .gis-legend-overlay 里 —— 它是「模糊 + 低不透明度」的组合拳，色值必须和
 *     backdrop-filter 写在同一个类里才能一起被 @supports 降级段接管。
 *  5. 背景加 backdrop-filter：地图瓦片纹理很杂，纯半透明底会让小字读不清。
 *  6. 2026-10-14 用户要求「图例背景改为透明」，同日又要求「继续增加透明度」：
 *     面板背景由 WH.cardBg（近乎不透明）换成极低的 0.18（深）/ 0.30（浅）
 *     不透明度 + 34px 模糊的玻璃底，地图明显从底下透出来。取舍、对比度估算
 *     与「已经到可读性下限」的提醒都写在 index.css 的 .gis-legend-overlay 段。
 *  7. **2026-10-14 第三轮（重要，推翻了第 6 条的结论）**：用户反馈「深色主题下
 *     出现白色背景白色字体」。实测根因不是「不够透明」，而是深色主题下瓦片被
 *     invert 反相后，OSM 的深色公路/注记变成**亮白**，0.18 的暗面板压不住它 ——
 *     于是白底白字。**继续降不透明度只会恶化**：透明度与可读性在「底不可控」时
 *     是互相冲突的。
 *     期间试过给文字加 text-shadow 描边，**已被用户否决并移除**（0.75rem 小字套
 *     一圈同色晕读起来是脏污/重影，不美观）—— 勿再重复该方案。
 *     用户随后连续要求提高透明度：「背景透明度 80%」→ alpha 0.2，
 *     再「100% 透明」→ alpha **0**（当前值，两主题同）。即背景完全不可见，
 *     只剩文字 + 描边 + 阴影浮在瓦片上。index.css 里的 @supports 降级段
 *     已一并删除（它会在不支持 backdrop-filter 的浏览器上偷偷把底加回来）。
 *     这是用户连续三轮要求后的明确取舍：**深色主题下白字压在反相后的亮色
 *     瓦片上可能看不见**，不要再自动加回背景色。彻底解法在底图（:690 不再 invert）。
 *     完整推导见 index.css 的 .gis-legend-overlay 段（勿只看本文件就调数值）。
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

/* ===== 分组（2026-10-17 用户要求「重新设计 legend，现在总是不好区分」）=====

   原实现是一根**平铺**列表：告警状态、关联工单、站点等级混在一起，颜色还是
   红/黄/蓝/绿/紫/灰六种互不相干的色相 —— 只能靠逐行读文字来分辨「这行是什么
   维度的东西」。用户反馈"不好区分"，成因是两条：
     ① **结构**：不同语义（站点当前告警状态 / 关联工单 / 资产等级）混排；
     ② **配色**：色相杂乱，看不出同一族之间的深浅关系。
   改为**分组 + 同组同色系**：
     · 每个 group 一个小标题，语义相近的条目归拢；
     · 组内用**同色相不同深浅**，组间才换色相 —— "同组=同族色"本身成为一条
       视觉线索，不必逐行读文字。
   ⚠️ 颜色值仍由 GISMap 传入（SITE_COLORS 是站点圆点的**唯一真相源**），
      本组件不定义任何颜色 —— 图例色必须与地图实际画的色一致，
      否则比没有图例更糟。 */
export interface MapLegendGroup {
  /** 组标题；为空时不渲染标题行 */
  title?: string
  rows: MapLegendRow[]
}

interface Props {
  title: string
  /** 分组后的图例主体（2026-10-17 新增）。未传时回落到 rows。 */
  groups?: MapLegendGroup[]
  /** 旧接口：平铺行。groups 存在时忽略。 */
  rows?: MapLegendRow[]
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
  /* ⚠️ 2026-10-13：bottom 由 var(--wh-space-sm)(≈8.5px) 上移到 +26px（约图例
     全高 132px 的 1/5），修「图例最下面一行被挡住了」（用户反馈并指定移动量）。
     ---- 遮挡物是谁（Playwright 实测 TMP/_probe_note.json）----
     **不在 iframe 内部** —— 是门户画布自己的 .canvas-note 说明条
     （「GIS Map · /myapp/?page=gis」那条，olbr.css:2352，
      absolute bottom:0 / height 28px / background rgba(255,255,255,.86) + 上边框），
     它贴在 iframe 上沿 iframe 的底缘。图例原来只离画布底 8.5px，
     于是最后一行被这条 28px 的半透明带**盖掉 11~19px（约半行）**。
     这也解释了为什么此前所有 iframe 内的探针都查不出遮挡：
     elementFromPoint / rivals / 裁切检查都在内层文档里问，
     而遮挡物根本在外层页面上 —— 内层永远"看不到"它。
     ---- 取 26px 的依据 ----
     note 高 28px，图例底与画布底原有间隙 8.5px → 至少要上移 28-8.5≈19.5px；
     用户要求按图例高的 1/5（132/5≈26px），比下限多出 ~6px，
     实测上移 26px 后最后一行与 note 顶留有 15px 净距（TMP/_probe_note.json after_fix）。
     ---- 影响面 ----
     本组件只被 GISMap.tsx（Alarm 页签）使用，MW 页与直开 /myapp/?page=gis 的
     其他页不受影响；直开场景没有 note 条，图例只是稍离底边一点，无副作用。
     ⚠️ 若将来门户把 .canvas-note 改位置/删除，这里的 +26px 也应随之复查。 */
  bottom: 'calc(var(--wh-space-sm) + 26px)',
  left: 'var(--wh-space-sm)',
  zIndex: 1000,
  // 上限 13rem：再宽就会压掉地图上的站点；58vw 是窄屏（门户内嵌）时的兜底
  width: 'min(58vw, 13rem)',
  maxHeight: 'calc(100% - 1rem)',
  overflowY: 'auto',
  padding: 'var(--wh-space-sm) var(--wh-space-md)',
  borderRadius: 'var(--wh-radius-lg)',
  border: `1px solid ${WH.cardBorder}`,
  /* 背景**不在这里写**：它和 backdrop-filter 是一组，一并放在 index.css 的
     .gis-legend-overlay —— 那里能按主题各给一档。
     2026-10-14 第五轮起用户要求「100% 透明」，该处背景已是 transparent；
     描边与阴影**刻意保留**：底没了之后，它们是图例「作为一个整体」的唯一视觉边界，
     去掉会让文字与瓦片注记混在一起、分不清哪些是图例。 */
  boxShadow: 'var(--wh-shadow-3)',
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

/* 组内小标题（2026-10-17 分组设计）。比主标题更轻：
   主标题是「图例」这个整体，组标题只是把同一族条目归拢，不该抢层级。
   用左侧一道细竖线做「归属」的视觉连接，比再加一个色块更安静，
   也不会与下面各行的圆点混淆。 */
const subGroupTitleStyle: CSSProperties = {
  fontSize: '0.625rem',
  fontWeight: 600,
  color: WH.textDim,
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
  paddingLeft: 'var(--wh-space-xs)',
  borderLeft: `2px solid ${WH.cardBorder}`,
  marginBottom: '2px',
  lineHeight: 1.4,
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

export default function MapLegendOverlay({ title, groups, rows, utilTitle, utilRows, utilNote, note }: Props) {
  const hasUtil = !!utilTitle && !!utilRows && utilRows.length > 0
  /* 统一成 groups：调用方还没升级时（只传 rows）当作「一个无标题的组」，
     这样旧调用方式仍然工作，且渲染路径只有一条（避免两套 JSX 分叉）。 */
  const effectiveGroups: MapLegendGroup[] = groups && groups.length > 0
    ? groups
    : [{ title: undefined, rows: rows || [] }]
  /* 口径说明默认**收进 ⓘ 悬浮气泡**，不再常驻占版面（2026-09-28 用户要求「这些备注能隐藏吗」）。
     这两段话（利用率来源与槽位、图例数字口径）只在「第一次看不懂时」有用，
     常驻却要占掉图例浮层 4~5 行高度 —— 浮层压在瓦片上，每多一行就多挡一块地图。
     改用项目统一的 ExplainIcon（与各看板指标卡的 ⓘ 同一个组件、同一种交互），
     需要时悬停即可看全文，还顺带获得「一键复制说明」。 */
  return (
    <div className="gis-legend-overlay" style={panelStyle} role="region" aria-label={title}>
      <div style={groupTitleStyle}>
        {title}
        {note && <ExplainIcon text={note} size={12} placement="right" />}
      </div>
      {effectiveGroups.map((g, gi) => (
        <div key={g.title || `g${gi}`} style={{ marginTop: gi === 0 ? 0 : 'var(--wh-space-sm)' }}>
          {/* 组标题只在该组非空且有名字时渲染 —— 空组不该留下一条孤零零的标题 */}
          {g.title && g.rows.length > 0 && (
            <div style={subGroupTitleStyle}>{g.title}</div>
          )}
          {g.rows.map(r => <Row key={r.id} row={r} />)}
        </div>
      ))}
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
