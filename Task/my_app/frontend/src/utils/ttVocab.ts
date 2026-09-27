/**
 * tt_postmortem 后端词表 → 当前语言文案。
 *
 * 背景：后端 `services/tt_postmortem` 不感知前端语言，`_SEG_META` /
 * `STAGE_CONTRACT` / `_WO_STAGE_SPECS` 的第二列全是中文硬编码。前端若直接显示
 * `label`，英文界面就会整片冒中文（实测 noc_analyst 的环形图图例、瓶颈卡、
 * 偏离清单全是中文）。
 *
 * 为什么不能只按 key 走：后端聚合时 segment 的 key 是 `"{phase}:{目标事件}"`，
 * **起点只进了中文标签、没有对应字段**；`tickets[].bottleneck`、
 * `noc_stats[].worst_segment` 更是只有中文串。所以除了正向 key 表，
 * 这里还登记后端原文，用于反查。
 *
 * 两条铁律：
 *   1. 任何一端认不出来就原样回落，绝不输出「A → 」这种半截文案；
 *   2. 中文模式下显示结果不变 —— zh 词条与后端原文逐字相同
 *      （改后端词表必须同步改这里，否则英文回落、中文照旧，问题被藏起来）。
 *
 * 出处：backend/services/tt_postmortem/__init__.py `_SEG_META`（约 :2319）、
 * `STAGE_CONTRACT`（约 :1609）、`_WO_STAGE_SPECS`（约 :2849）。
 */

type EvVocab = {
  /** 后端事件键，如 fo_process */
  ev: string
  /** 分段端点用的短名词条（后端 _SEG_META 第二列） */
  shortKey: string
  /** 里程碑/动作表用的全名词条（后端 STAGE_CONTRACT 第三列） */
  nodeKey: string
  /** 上面两个词条的中文原文，用于反查 */
  shortZh: string
  nodeZh: string
}

/** 顺序与后端 _SEG_META / STAGE_CONTRACT 一致；tail 是「至今未见关单」的伪端点 */
const EV_VOCAB: EvVocab[] = [
  { ev: 'alarm_occur',    shortKey: 'ttPm.short.alarm_occur',    nodeKey: 'ttPm.node.alarmOccur',    shortZh: '告警发生',      nodeZh: '告警发生' },
  { ev: 'tt_create',      shortKey: 'ttPm.short.tt_create',      nodeKey: 'ttPm.node.ttCreate',      shortZh: 'TT 建单',       nodeZh: 'TT 自动建单' },
  { ev: 'dispatch_route', shortKey: 'ttPm.short.dispatch_route', nodeKey: 'ttPm.node.dispatchRoute', shortZh: '派单路由决定',  nodeZh: '派单路由决定' },
  { ev: 'fo_accept',      shortKey: 'ttPm.short.fo_accept',      nodeKey: 'ttPm.node.foAccept',      shortZh: 'FO 接单',       nodeZh: 'FO Accept 接单' },
  { ev: 'wo_dispatch',    shortKey: 'ttPm.short.wo_dispatch',    nodeKey: 'ttPm.node.woDispatch',    shortZh: 'WO 派单',       nodeZh: 'WO 派单' },
  { ev: 'onsite_action',  shortKey: 'ttPm.short.onsite_action',  nodeKey: 'ttPm.node.onsiteAction',  shortZh: '现场出发',      nodeZh: '现场处置' },
  { ev: 'wo_step',        shortKey: 'ttPm.short.wo_step',        nodeKey: 'ttPm.node.woStep',        shortZh: '现场步骤',      nodeZh: '现场步骤' },
  { ev: 'alarm_clear',    shortKey: 'ttPm.short.alarm_clear',    nodeKey: 'ttPm.node.alarmClear',    shortZh: '告警清除/自愈', nodeZh: '告警清除/自愈' },
  { ev: 'fo_process',     shortKey: 'ttPm.short.fo_process',     nodeKey: 'ttPm.node.foProcess',     shortZh: 'FO 提交关单',   nodeZh: 'FO Process 填报' },
  { ev: 'confirm',        shortKey: 'ttPm.short.confirm',        nodeKey: 'ttPm.node.confirm',       shortZh: '确认关单',      nodeZh: 'Confirm 关单' },
]

const TAIL: EvVocab = {
  ev: 'tail', shortKey: 'ttPm.short.tail', nodeKey: 'ttPm.short.tail',
  shortZh: '至今（未见关单）', nodeZh: '至今（未见关单）',
}

const BY_EV = new Map<string, EvVocab>([...EV_VOCAB, TAIL].map(v => [v.ev, v]))

/** 后端中文（短名与全名同表）→ 词表条目。二者不冲突：同名的一定指向同一事件。 */
const BY_ZH = new Map<string, EvVocab>()
for (const v of EV_VOCAB) {
  BY_ZH.set(v.shortZh, v)
  BY_ZH.set(v.nodeZh, v)
}
BY_ZH.set(TAIL.shortZh, TAIL)

/** 后端分段标签的箭头分隔符（f"{src} → {dst}"，U+2192 两侧各一个半角空格） */
const ARROW = ' → '

export type Tf = (key: string, params?: Record<string, string | number>) => string

const textOf = (t: Tf, v: EvVocab, style: 'short' | 'node') =>
  t(style === 'short' ? v.shortKey : v.nodeKey)

/**
 * 「A → B」形式的时间归因标签。style=short 用于分段（环形图/分段表/瓶颈卡），
 * style=node 用于偏离清单里的超时项（那里是里程碑全名）。
 * 解析不出来（不含箭头、或任一端不在词表）时原样返回。
 */
export const spanTextFromZh = (
  t: Tf, raw: string | null | undefined, style: 'short' | 'node' = 'short',
): string => {
  if (!raw) return ''
  const i = raw.indexOf(ARROW)
  if (i <= 0) return endpointTextFromZh(t, raw, style)
  const a = BY_ZH.get(raw.slice(0, i).trim())
  const b = BY_ZH.get(raw.slice(i + ARROW.length).trim())
  if (!a || !b) return raw
  return `${textOf(t, a, style)}${ARROW}${textOf(t, b, style)}`
}

/** 单个端点名（后端 _SEG_META / STAGE_CONTRACT 的中文短名或全名） */
export const endpointTextFromZh = (
  t: Tf, raw: string | null | undefined, style: 'short' | 'node' = 'short',
): string => {
  if (!raw) return ''
  const v = BY_ZH.get(raw.trim())
  return v ? textOf(t, v, style) : raw
}

/** 里程碑全名：stage_stats / missing_stats / expected_actions 的 label */
export const nodeTextFromZh = (t: Tf, raw: string | null | undefined): string =>
  endpointTextFromZh(t, raw, 'node')

/** 分段标签（环形图图例、分段表、瓶颈卡、worst_segment、逐单 bottleneck） */
export const segTextFromZh = (t: Tf, raw: string | null | undefined): string =>
  spanTextFromZh(t, raw, 'short')

/**
 * 按 key 取事件文案（key 存在时优先用它，比反查中文更稳）。
 * 认不出来返回空串，让调用方回落后端原文。
 */
export const evText = (t: Tf, ev: string | null | undefined, style: 'short' | 'node'): string => {
  const v = ev ? BY_EV.get(ev) : undefined
  return v ? textOf(t, v, style) : ''
}

/** 责任方：后端只在「归系统」时给固定词，归人时给真实姓名（属数据，不翻译） */
export const ownerTextFromZh = (t: Tf, raw?: string | null): string => {
  switch (raw) {
    case '系统/流程': return t('ttPm.owner.sysFlow')
    case '系统/自愈': return t('ttPm.owner.sysSelfHeal')
    case '（未记录操作人）': return t('ttPm.owner.noOperator')
    default: return raw || '-'
  }
}

/** 后端 label 里不带模板、直接写死的偏离名 → 词条（偏离 4/5/6/7） */
const DEV_FIXED = new Map<string, string>([
  ['高等级断站未派 WO', 'noc.devNoWoCritical'],
  ['根因填报错位（POWER←TRM）', 'noc.devRootCauseMismatch'],
  ['告警已清除后仍延迟关单', 'noc.devLateCloseAfterClear'],
])

/**
 * 偏离清单标签。后端是中文模板拼出来的（偏离 1/2/3），这里按同样的形状反解：
 *   缺少「X」 / 「A → B」超时 / 「B」早于「A」
 * 命中不了的（如 SLA Failed 本来就是英文、或后端新增了模板）原样回落。
 */
export const devTextFromZh = (t: Tf, raw: string | null | undefined): string => {
  if (!raw) return ''
  const fixed = DEV_FIXED.get(raw.trim())
  if (fixed) return t(fixed)
  if (raw.startsWith('缺少「') && raw.endsWith('」')) {
    // 「缺少「」是 3 个字符、结尾的「」」是 1 个字符，别按字节数切
    return t('noc.devMissing', { stage: nodeTextFromZh(t, raw.slice(3, -1)) })
  }
  if (raw.startsWith('「') && raw.endsWith('」超时')) {
    return t('noc.devLate', { span: spanTextFromZh(t, raw.slice(1, -3), 'node') })
  }
  const m = /^「(.+)」早于「(.+)」$/.exec(raw)
  if (m) {
    return t('noc.devOutOfOrder', {
      earlier: nodeTextFromZh(t, m[1]), later: nodeTextFromZh(t, m[2]),
    })
  }
  return raw
}

/** WO 生命周期逐跳（后端 _WO_STAGE_SPECS 第一列 → 词条） */
export const woStageLabelKey = (key?: string | null): string => {
  switch (key) {
    case 'wo_create': return 'noc.woLifeWoCreated'
    case 'wo_accept': return 'noc.woLifeAccept'
    case 'wo_start_trip': return 'noc.woLifeStartTrip'
    case 'wo_arrive': return 'noc.woLifeArrive'
    case 'wo_process': return 'noc.woLifeProcess'
    case 'wo_confirm': return 'noc.woLifeConfirm'
    case 'wo_leave': return 'noc.woLifeLeave'
    default: return ''
  }
}
