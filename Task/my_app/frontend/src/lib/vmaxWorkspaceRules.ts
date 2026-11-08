/* ============================================================================
 * vmaxWorkspaceRules.ts —— VMAX 智能诊断工作台（CCA）的关联与解释层
 * ============================================================================
 *
 * 2026-11-07 新建。这一层**只做视图层的解释与关联**，不碰出结论逻辑：
 *   - vmaxDiagnosisRules.ts 的 buildVerdict / scoreAll 是唯一结论来源，本文件
 *     禁止复制阈值（ottRttBad/ottJitterBad 等一律引 THRESHOLDS），禁止篡改
 *     verdict —— 现在**真的有单测**守这两条：src/lib/__tests__/
 *     vmaxWorkspaceRules.test.ts（此前头注释声称有单测、实际基建为零，
 *     2026-11-07 补齐 vitest，`npm test` 跑）；
 *   - CCA（vmax-cca-query）不参与 verdict（sources 只有 1300/1100/32/1301），
 *     这里只把它的 causes/failures 当作**关联证据**叠层；
 *   - 文案一律 I18nText（tx），渲染层 renderI18n 翻译，禁止中文字面量。
 *
 * 两个纯函数：
 *   buildExplainableMetrics —— 把「四维分 + 专项」摊成
 *     为什么重要 / 观测到什么 / 何时发生 / 可能影响 / 需要验证
 *   buildWorkspaceCorrelation —— 跨模块 links + rankedCauses +
 *     recommendations（规则模板无 LLM）+ enrichedTimeline（基线分钟桶不变）
 *
 * 链路顺序（端到端）：terminal → ran → transport → core → ott。
 * 无数据 = unknown，绝不写「正常」。
 * ========================================================================== */

import {
  THRESHOLDS,
  tx,
  type ComplaintKey,
  type DimensionScore,
  type DiagnosisPayload,
  type GameResult,
  type I18nText,
  type OttResult,
  type RadioAnalysis,
  type ScoreKey,
  type SourceResult,
  type TimelineRow,
  type VoiceResult,
} from '../pages/vmaxDiagnosisRules'
import type { CauseItem, CcaResult, CellRecord } from '../components/VmaxCcaCards'

/* ---------------------------------------------------------------------------
 * 类型
 * ------------------------------------------------------------------------ */

export type EvidenceRef = {
  /** 原始证据去向：抽屉内对应面板 */
  kind: 'xdr' | 'records' | 'radio' | 'flow' | 'cca'
  /** 上游源标签（展示用） */
  sourceLabel: string
}

/** 证据抽屉的面板类型 —— 从 EvidenceRef 派生，抽屉/指标行/页面共用一份 */
export type EvidenceKind = EvidenceRef['kind']

export type ChainNode = 'terminal' | 'ran' | 'transport' | 'core' | 'ott'
export const CHAIN_ORDER: ChainNode[] = ['terminal', 'ran', 'transport', 'core', 'ott']

/** 链路节点 → i18n key（Analysis / Verdict / 导出共用，勿在组件里各写一份） */
export const CHAIN_NODE_KEY: Record<ChainNode, string> = {
  terminal: 'vmaxq.ws.chain.terminal',
  ran: 'vmaxq.ws.chain.ran',
  transport: 'vmaxq.ws.chain.transport',
  core: 'vmaxq.ws.chain.core',
  ott: 'vmaxq.ws.chain.ott',
}

export type Level = 'ok' | 'warn' | 'bad' | 'unknown'

export type ExplainMetric = {
  id: string
  node: ChainNode
  /** 指标标题（i18n key） */
  titleKey: string
  titleParams?: Record<string, string | number | I18nText>
  why: I18nText
  observed: I18nText
  /* 何时发生：从时间线坏分钟派生，null 表示本指标不绑定分钟 */
  when: string | null
  impact: I18nText
  verify: I18nText[]
  level: Level
  refs: EvidenceRef[]
}

export type ChainStatus = { node: ChainNode; level: Level }

export type CrossModuleLink = {
  id: string
  modules: ChainNode[]
  strength: 'strong' | 'weak' | 'contradict'
  support: I18nText[]
  refute: I18nText[]
  refs: EvidenceRef[]
}

export type RankedCause = {
  id: string
  label: string
  confidence: number
  /** 与维度异常的对齐：命中的维度 key（排序与解释用） */
  aligned: ScoreKey[]
  /** 跨模块支持度 0~1 */
  crossSupport: number
  cause: CauseItem | null
  failures: string[]
}

export type Recommendation = {
  id: string
  node: ChainNode
  /* 模板 key：sugg 留空沿用 verdict.suggestion */
  sugg: I18nText | null
  needEvidence: I18nText | null
  action: I18nText | null
}

export type WorkspaceCorrelation = {
  metrics: ExplainMetric[]
  chain: ChainStatus[]
  links: CrossModuleLink[]
  rankedCauses: RankedCause[]
  recommendations: Recommendation[]
  enrichedTimeline: TimelineRow[]
}

type Input = {
  payload: DiagnosisPayload | null
  sources: SourceResult[]
  scores: DimensionScore[]
  voice: VoiceResult | null
  ott: OttResult | null
  game: GameResult | null
  radio: RadioAnalysis | null
  timeline: TimelineRow[]
  cca: CcaResult | null
  complaint: ComplaintKey
}

/* ---------------------------------------------------------------------------
 * 小工具
 * ------------------------------------------------------------------------ */

const scoreOf = (scores: DimensionScore[], k: ScoreKey): number | null =>
  scores.find((s) => s.key === k)?.score ?? null

const levelOf = (score: number | null): Level =>
  score === null ? 'unknown' : score >= THRESHOLDS.scoreGood ? 'ok'
  : score >= THRESHOLDS.scoreBad ? 'warn' : 'bad'

/** 时间线中某列 bad 的最近分钟（HH:mm） */
function badMinute(rows: TimelineRow[], col: 'radio' | 'traffic' | 'latency' | 'transport' | 'voice'): string | null {
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const r = rows[i]
    if (r[col].level === 'bad') return r.minute.slice(11, 16)
  }
  return null
}

function srcOf(sources: SourceResult[], key: string): SourceResult | undefined {
  return sources.find((s) => s.key === key)
}

function rowsOfCca(cca: CcaResult | null): { causes: CauseItem[]; failures: string[]; cells: CellRecord[] } {
  return {
    causes: cca?.causes || [],
    failures: cca?.failures || [],
    cells: cca?.cells?.cells || [],
  }
}

/* ---------------------------------------------------------------------------
 * 可解释指标（五段：why / observed / when / impact / verify）
 * ------------------------------------------------------------------------ */

function buildMetrics(input: Input): ExplainMetric[] {
  const { scores, sources, voice, ott, game, radio, timeline } = input
  const out: ExplainMetric[] = []

  // 接入可用性 → core（会话/信令面 1100）
  {
    const s = scores.find((x) => x.key === 'availability')
    out.push({
      id: 'm-avail', node: 'core',
      titleKey: 'vmaxq.ws.metric.avail.title',
      why: tx('vmaxq.ws.metric.avail.why'),
      observed: s?.evidence[0] || (s?.score === null
        ? tx('vmaxq.ws.metric.nodata') : tx('vmaxq.ws.metric.avail.ok')),
      when: badMinute(timeline, 'voice'),
      impact: tx('vmaxq.ws.metric.avail.impact'),
      verify: [tx('vmaxq.ws.metric.verify.core')],
      level: levelOf(s?.score ?? null),
      refs: [{ kind: 'xdr', sourceLabel: srcOf(sources, '1100')?.label || '1100' }],
    })
  }
  // 响应时延 → transport
  {
    const s = scores.find((x) => x.key === 'latency')
    const d = (s?.detail || {}) as { firstP90?: number }
    out.push({
      id: 'm-latency', node: 'transport',
      titleKey: 'vmaxq.ws.metric.lat.title',
      why: tx('vmaxq.ws.metric.lat.why'),
      observed: s?.evidence[0] ? s.evidence[0]
        : d.firstP90 ? tx('vmaxq.vd.ev.latencyP90', { p90: `${d.firstP90} ms` })
        : tx('vmaxq.ws.metric.nodata'),
      when: badMinute(timeline, 'latency'),
      impact: tx('vmaxq.ws.metric.lat.impact'),
      verify: [tx('vmaxq.ws.metric.verify.transport')],
      level: levelOf(s?.score ?? null),
      refs: [{ kind: 'xdr', sourceLabel: srcOf(sources, '1300')?.label || '1300' }],
    })
  }
  // 传输质量 → transport
  {
    const s = scores.find((x) => x.key === 'transport')
    out.push({
      id: 'm-trans', node: 'transport',
      titleKey: 'vmaxq.ws.metric.trans.title',
      why: tx('vmaxq.ws.metric.trans.why'),
      observed: s?.evidence[0] || tx('vmaxq.ws.metric.nodata'),
      when: badMinute(timeline, 'transport'),
      impact: tx('vmaxq.ws.metric.trans.impact'),
      verify: [tx('vmaxq.ws.metric.verify.transport')],
      level: levelOf(s?.score ?? null),
      refs: [{ kind: 'xdr', sourceLabel: srcOf(sources, '1300')?.label || '1300' }],
    })
  }
  // 无线质量 → ran
  {
    const s = scores.find((x) => x.key === 'radio')
    const src32 = srcOf(sources, '32')
    out.push({
      id: 'm-radio', node: 'ran',
      titleKey: 'vmaxq.ws.metric.radio.title',
      why: tx('vmaxq.ws.metric.radio.why'),
      observed: radio?.headline || s?.evidence[0] || tx('vmaxq.ws.metric.nodata'),
      when: badMinute(timeline, 'radio'),
      impact: tx('vmaxq.ws.metric.radio.impact'),
      verify: [tx('vmaxq.ws.metric.verify.radio')],
      level: levelOf(s?.score ?? null),
      refs: [{ kind: 'records', sourceLabel: src32?.label || '32' }],
    })
  }
  // 语音链路 → core（CSFB/VoLTE）
  {
    const active = voice && voice.mode !== 'none'
    out.push({
      id: 'm-voice', node: 'core',
      titleKey: 'vmaxq.ws.metric.voice.title',
      why: tx('vmaxq.ws.metric.voice.why'),
      observed: !voice ? tx('vmaxq.ws.metric.nodata')
        : active ? voice.evidence[0] : tx('vmaxq.vd.ev.voiceNone'),
      when: badMinute(timeline, 'voice'),
      impact: tx('vmaxq.ws.metric.voice.impact'),
      verify: [tx('vmaxq.ws.metric.verify.core')],
      level: voice === null ? 'unknown'
        : voice.badCount > 0 ? 'bad'
        : !active ? 'unknown' : 'ok',
      refs: [{ kind: 'xdr', sourceLabel: srcOf(sources, '1100')?.label || '1100' }],
    })
  }
  // OTT → ott
  {
    const has = !!ott && ott.totalSessions > 0
    const worse = has && ott !== null
      && (ott.avgDlRtt > THRESHOLDS.ottRttBad
        || ott.jitter > THRESHOLDS.ottJitterBad
        || ott.retransRate > THRESHOLDS.retrans)
    out.push({
      id: 'm-ott', node: 'ott',
      titleKey: 'vmaxq.ws.metric.ott.title',
      why: tx('vmaxq.ws.metric.ott.why'),
      observed: !ott ? tx('vmaxq.ws.metric.nodata')
        : has ? ott.evidence[0] : tx('vmaxq.vd.ev.ottNone'),
      when: null,
      impact: tx('vmaxq.ws.metric.ott.impact'),
      verify: [tx('vmaxq.ws.metric.verify.app')],
      level: ott === null ? 'unknown' : !has ? 'unknown' : worse ? 'bad' : 'ok',
      refs: [{ kind: 'flow', sourceLabel: srcOf(sources, '1300')?.label || '1300' }],
    })
  }
  // 游戏 → ott（应用体验维度）
  {
    const has = !!game && game.totalSessions > 0
    out.push({
      id: 'm-game', node: 'ott',
      titleKey: 'vmaxq.ws.metric.game.title',
      why: tx('vmaxq.ws.metric.game.why'),
      observed: !game ? tx('vmaxq.ws.metric.nodata')
        : has ? game.evidence[0] : tx('vmaxq.vd.ev.gameNone'),
      when: null,
      impact: tx('vmaxq.ws.metric.game.impact'),
      verify: [tx('vmaxq.ws.metric.verify.app')],
      level: game === null ? 'unknown' : !has ? 'unknown' : 'ok',
      refs: [{ kind: 'flow', sourceLabel: srcOf(sources, '1300')?.label || '1300' }],
    })
  }
  // 终端/小区画像 → terminal（CCA 证据层）
  {
    const { causes, failures, cells } = rowsOfCca(input.cca)
    out.push({
      id: 'm-term', node: 'terminal',
      titleKey: 'vmaxq.ws.metric.term.title',
      why: tx('vmaxq.ws.metric.term.why'),
      observed: causes.length
        ? tx('vmaxq.ws.metric.term.ok', { n: causes.length, m: cells.length })
        : tx('vmaxq.ws.metric.nodata'),
      when: null,
      impact: tx('vmaxq.ws.metric.term.impact'),
      verify: [tx('vmaxq.ws.metric.verify.terminal')],
      level: input.cca === null ? 'unknown' : causes.length ? 'warn' : 'ok',
      refs: [{ kind: 'cca', sourceLabel: 'CCA' }],
    })
    void failures
  }
  return out
}

function buildChain(metrics: ExplainMetric[]): ChainStatus[] {
  const rank: Record<Level, number> = { ok: 0, warn: 1, unknown: 1, bad: 2 }
  return CHAIN_ORDER.map((node) => {
    const ms = metrics.filter((m) => m.node === node)
    if (!ms.length) return { node, level: 'unknown' as Level }
    let worst: Level = 'ok'
    for (const m of ms) if (rank[m.level] > rank[worst]) worst = m.level
    return { node, level: worst }
  })
}

/* ---------------------------------------------------------------------------
 * 跨模块关联
 * ------------------------------------------------------------------------ */

function buildLinks(input: Input, chain: ChainStatus[]): CrossModuleLink[] {
  const links: CrossModuleLink[] = []
  const byNode = (n: ChainNode): Level => chain.find((c) => c.node === n)?.level || 'unknown'
  const badMinutes = [
    badMinute(input.timeline, 'radio'),
    badMinute(input.timeline, 'transport'),
    badMinute(input.timeline, 'latency'),
    badMinute(input.timeline, 'voice'),
  ].filter(Boolean) as string[]

  const coOccur = new Set(badMinutes).size >= 1 && badMinutes.length >= 2
  // 同分钟双坏 → 强关联（至少两种维度同分钟 bad）；仅单点坏 → 弱关联/反向证据
  if (byNode('ran') !== 'ok' && byNode('ran') !== 'unknown'
      && (byNode('transport') === 'bad' || byNode('transport') === 'warn')) {
    links.push({
      id: 'l-ran-trans', modules: ['ran', 'transport'],
      strength: coOccur ? 'strong' : 'weak',
      support: [tx(coOccur ? 'vmaxq.ws.link.coOccur' : 'vmaxq.ws.link.ranTrans')],
      refute: [],
      refs: [{ kind: 'records', sourceLabel: '32+1300' }],
    })
  }
  if (byNode('core') !== 'ok' && byNode('core') !== 'unknown' && byNode('ran') !== 'ok') {
    links.push({
      id: 'l-core-ran', modules: ['core', 'ran'],
      strength: 'weak',
      support: [tx('vmaxq.ws.link.coreRan')],
      refute: [],
      refs: [{ kind: 'xdr', sourceLabel: '1100+32' }],
    })
  }
  if (byNode('ott') === 'bad' || byNode('ott') === 'warn') {
    const radioOk = scoreOf(input.scores, 'radio') !== null
      && (scoreOf(input.scores, 'radio') ?? 100) >= THRESHOLDS.scoreGood
    if (radioOk) {
      links.push({
        id: 'l-ott-radio', modules: ['ott', 'ran'],
        strength: 'contradict',
        support: [],
        refute: [tx('vmaxq.ws.link.ottRefute')],
        refs: [{ kind: 'flow', sourceLabel: '1300' }],
      })
    }
  }
  return links
}

/* ---------------------------------------------------------------------------
 * 排行：CCA causes 按维度异常对齐排序（只加分，不改结论字）
 * ------------------------------------------------------------------------ */

/* CCA 规则 → 诊断维度 的对齐表（2026-11-07 P2-8 重构）。
 *
 * 旧版 alignOf 把规则名+object 名拼成大写串做 includes，且「一个都没命中
 * 也兜底 availability」——后果有二：object_type 恒为 CELL(4G) 之类，导致
 * 每条小区级根因都被对齐到 radio；没对齐上的也假挂 availability，
 * crossSupport 永不为 0，排行被噪声污染。现改三级：
 *   1. CCA_RULE_ALIGN_EXACT —— 已确证规则名的精确映射（键为大写规范化后
 *      的规则名）。新规则确证后在此登记，登记时注明来源与日期；
 *   2. CCA_RULE_KEYWORDS —— 未登记规则的保守关键词（只搜规则名，不搜
 *      object 名），只留语义无歧义的 token，逐条写明对应理由；
 *   3. 两级都没命中 → 空数组：诚实显示「无维度对齐」，crossSupport 为 0，
 *      排序只剩 CCA 自身 confidence。 */
const CCA_RULE_ALIGN_EXACT: Record<string, ScoreKey[]> = {
  // 唯一确证样例：backend/services/vmax_cca/README.md「根因」接口样例（2026-11-07）
  'DOWNLINK WEAK COVERAGE(CELL)': ['radio'],
}

const CCA_RULE_KEYWORDS: { token: string; dim: ScoreKey }[] = [
  // 无线侧：覆盖/信号类词只可能出自 RAN 侧规则
  { token: 'WEAK COVERAGE', dim: 'radio' },
  { token: 'RSRP', dim: 'radio' },
  { token: 'SINR', dim: 'radio' },
  { token: 'RADIO', dim: 'radio' },
  { token: 'SIGNAL', dim: 'radio' },
  // 传输质量：重传/丢包类（泛词 PACKET 单独出现不定性，只认 RETRAN / LOSS）
  { token: 'RETRAN', dim: 'transport' },
  { token: 'LOSS', dim: 'transport' },
  { token: 'TRANSPORT', dim: 'transport' },
  // 时延类
  { token: 'DELAY', dim: 'latency' },
  { token: 'LATENCY', dim: 'latency' },
  { token: 'TIMEOUT', dim: 'latency' },
  { token: 'RTT', dim: 'latency' },
  // 接入/会话成功类（FAILURE 已由 FAIL 覆盖；CONNECT/ACCESS 歧义大，不收）
  { token: 'SLC', dim: 'availability' },
  { token: 'FAIL', dim: 'availability' },
  { token: 'AVAIL', dim: 'availability' },
]

function alignOf(cause: CauseItem): ScoreKey[] {
  const rule = String(cause.rule_name || '').trim().toUpperCase()
  const exact = CCA_RULE_ALIGN_EXACT[rule]
  if (exact) return exact
  const dims: ScoreKey[] = []
  for (const { token, dim } of CCA_RULE_KEYWORDS) {
    if (rule.includes(token) && !dims.includes(dim)) dims.push(dim)
  }
  return dims
}

function crossSupportOf(cause: CauseItem, scores: DimensionScore[]): number {
  const aligned = alignOf(cause)
  let support = 0
  for (const k of aligned) {
    const s = scoreOf(scores, k)
    if (s !== null) support += s < THRESHOLDS.scoreBad ? 1 : s < THRESHOLDS.scoreGood ? 0.5 : 0
  }
  return Math.min(1, support)
}

function buildRankedCauses(input: Input): RankedCause[] {
  const { causes, failures } = rowsOfCca(input.cca)
  return [...causes]
    .map((c, i) => ({
      id: `c-${i}`,
      label: c.rule_name || c.object_name || '—',
      confidence: c.confidence || 0,
      aligned: alignOf(c),
      crossSupport: crossSupportOf(c, input.scores),
      cause: c,
      failures: [] as string[],
    }))
    .sort((a, b) =>
      (b.crossSupport * 100 + b.confidence) - (a.crossSupport * 100 + a.confidence))
    .slice(0, 8)
    .map((r) => ({ ...r, failures: input.cca === null ? [] : failures.slice(0, 3) }))
}

/* ---------------------------------------------------------------------------
 * 建议：模板化，无 LLM
 * ------------------------------------------------------------------------ */

function buildRecs(_input: Input, chain: ChainStatus[]): Recommendation[] {
  const recs: Recommendation[] = []
  const focus = (() => {
    const r = chain.find((c) => c.level === 'bad')
    return r ? r.node : null
  })()
  if (focus) {
    recs.push({
      id: 'r-1', node: focus,
      sugg: null,
      needEvidence: tx('vmaxq.ws.rec.need'),
      action: tx('vmaxq.ws.rec.action'),
    })
  }
  return recs
}

/* ---------------------------------------------------------------------------
 * 主入口
 * ------------------------------------------------------------------------ */

export function buildWorkspaceCorrelation(input: Input): WorkspaceCorrelation {
  const metrics = buildMetrics(input)
  const chain = buildChain(metrics)
  const links = buildLinks(input, chain)
  const rankedCauses = buildRankedCauses(input)
  const recommendations = buildRecs(input, chain)
  // enrichedTimeline：基线分钟桶不变（VmaxEvidenceTimeline 逐行渲染同一份 rows）。
  return {
    metrics, chain, links, rankedCauses, recommendations,
    enrichedTimeline: input.timeline,
  }
}
