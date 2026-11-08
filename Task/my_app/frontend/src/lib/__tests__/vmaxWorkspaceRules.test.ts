/* ============================================================================
 * vmaxWorkspaceRules 单测（2026-11-07 P2-10，vitest）
 * ============================================================================
 * 此前 vmaxWorkspaceRules.ts 头注释声称「单测里断言 verdict 文本不变」，
 * 但前端没有任何测试基建 —— 本文件把这句话变成事实。守护四件事：
 *
 *   1. THRESHOLDS.ottRttBad / ottJitterBad 迁移后数值不变（2026-11-07 从
 *      两处硬编码收敛而来，150/60 是经评审的口径）；
 *   2. buildVerdict 对边界值的行为不变（OTT RTT 恰在阈值上 → 不算差；
 *      超过 → worse。结论 key 是对外的契约）；
 *   3. 全空数据 verdict 不变（allEmpty / voiceNone 分支 —— 「无数据 ≠ 正常」
 *      的两个关键出口）；
 *   4. 工作台关联层：链路最差值传播、unknown 不被读成 ok、
 *      CCA 规则对齐的三级策略（精确表命中 / 关键词命中 / 诚实空对齐）。
 *
 * 只测纯函数（lib/pages 的规则层），不挂 React、不发请求 —— CI 零环境依赖。
 * ========================================================================== */

import { describe, expect, it } from 'vitest'

import {
  buildVerdict, scoreAll, THRESHOLDS,
  type DimensionScore, type GameResult, type OttResult,
  type SourceResult, type VoiceResult,
} from '../../pages/vmaxDiagnosisRules'
import {
  buildWorkspaceCorrelation, CHAIN_ORDER,
} from '../vmaxWorkspaceRules'
import type { CauseItem, CcaResult } from '../../components/VmaxCcaCards'

/* ---------------------------------------------------------------------------
 * 合成数据工厂：全部字段显式给出，不让测试依赖默认值
 * ------------------------------------------------------------------------ */

const emptySources = (): SourceResult[] => (['1300', '1100', '32', '1301'].map((key) => ({
  key, label: key, ok: true, rows: [], truncated: false,
})))

const nullScores = (): DimensionScore[] => ([
  { key: 'availability', score: null, sub: null, detail: {}, evidence: [] },
  { key: 'latency', score: null, sub: null, detail: {}, evidence: [] },
  { key: 'transport', score: null, sub: null, detail: {}, evidence: [] },
  { key: 'radio', score: null, sub: null, detail: {}, evidence: [] },
])

const score = (key: DimensionScore['key'], s: number): DimensionScore => ({
  key, score: s, sub: null, detail: {}, evidence: [],
})

const noneVoice = (): VoiceResult => ({
  mode: 'none', sgsCount: 0, csfbTrigger: 0, esrCount: 0, pagingCount: 0,
  badCount: 0, successRate: null, fallbackMs: null, steps: [], qci1: 0, evidence: [],
})

const ottResult = (over: Partial<OttResult> = {}): OttResult => ({
  sessions: [], totalSessions: 5, totalDurationS: 100,
  avgDlRtt: 100, jitter: 0, retransRate: 0, baselineRtt: 80, evidence: [],
  ...over,
})

const emptyGame = (): GameResult => ({ hits: [], totalSessions: 0, evidence: [] })

const cause = (over: Partial<CauseItem>): CauseItem => ({
  rule_name: '', object_type: 'CELL(4G)', object_name: 'CellA', objectinfo: '',
  confidence: 50, description: '', solution: '', vendor: 'ZTE',
  province: '', city: '', poortime: '', kqicode: 'k1', app_info: [],
  ...over,
})

const ccaWith = (causes: CauseItem[]): CcaResult => ({
  msisdn: '8880000', found: true, user: {}, terminal: null,
  causes, failures: [], cells: null, msg: '',
})

/* ---------------------------------------------------------------------------
 * 1. 阈值常量：收敛后数值不变
 * ------------------------------------------------------------------------ */
describe('THRESHOLDS', () => {
  it('OTT 体验偏差线维持 150ms / 60ms（2026-11-07 收敛为唯一出处）', () => {
    expect(THRESHOLDS.ottRttBad).toBe(150)
    expect(THRESHOLDS.ottJitterBad).toBe(60)
  })
})

/* ---------------------------------------------------------------------------
 * 2. buildVerdict：结论 key 是对外契约，不得漂移
 * ------------------------------------------------------------------------ */
describe('buildVerdict', () => {
  it('全空数据（all）：走 allEmpty，绝不写「正常」', () => {
    const v = buildVerdict('all', nullScores(), noneVoice(), ottResult(), emptyGame(), emptySources())
    expect(v.headline.key).toBe('vmaxq.vd.headline.allEmpty')
    expect(v.reproduced).toBe(false)
    expect(v.confidence).toBe('low')
    expect(v.focus).toBe('none')
  })

  it('全空数据（voice）：走 voiceNone，给出核对方向', () => {
    const v = buildVerdict('voice', nullScores(), noneVoice(), ottResult(), emptyGame(), emptySources())
    expect(v.headline.key).toBe('vmaxq.vd.headline.voiceNone')
    expect(v.reproduced).toBe(false)
  })

  it('OTT RTT 恰在阈值（150）不算差，超过才算 worse', () => {
    const at = buildVerdict('ott', nullScores(), noneVoice(),
      ottResult({ avgDlRtt: 150 }), emptyGame(), emptySources())
    const over = buildVerdict('ott', nullScores(), noneVoice(),
      ottResult({ avgDlRtt: 151 }), emptyGame(), emptySources())
    expect(at.headline.key).toBe('vmaxq.vd.headline.ottOk')
    expect(over.headline.key).toBe('vmaxq.vd.headline.ottWorse')
    expect(over.headline.params?.rtt).toBe(151)
  })
})

/* ---------------------------------------------------------------------------
 * 3. scoreAll：空数据返回 null 分（不是 0 分）
 * ------------------------------------------------------------------------ */
describe('scoreAll', () => {
  it('四源全空 → 四维全 null', () => {
    const scores = scoreAll(emptySources())
    expect(scores.map((s) => s.score)).toEqual([null, null, null, null])
  })
})

/* ---------------------------------------------------------------------------
 * 4. 工作台关联层：链路 / 根因对齐
 * ------------------------------------------------------------------------ */
describe('buildWorkspaceCorrelation', () => {
  const base = (over: Partial<Parameters<typeof buildWorkspaceCorrelation>[0]> = {}) => ({
    payload: null, sources: emptySources(), scores: nullScores(),
    voice: noneVoice(), ott: ottResult(), game: emptyGame(),
    radio: null, timeline: [], cca: ccaWith([]), complaint: 'all' as const,
    ...over,
  })

  it('CHAIN_ORDER 固定为端到端五节点', () => {
    expect(CHAIN_ORDER).toEqual(['terminal', 'ran', 'transport', 'core', 'ott'])
  })

  it('链路最差值传播：radio 坏 → ran=bad；无数据节点保持 unknown（不是 ok）', () => {
    const ws = buildWorkspaceCorrelation(base({ scores: [score('radio', 40)] }))
    const byNode = Object.fromEntries(ws.chain.map((c) => [c.node, c.level]))
    expect(byNode.ran).toBe('bad')
    expect(byNode.core).toBe('unknown')
    expect(byNode.transport).toBe('unknown')
    // CCA 无根因候选（有返回）→ ok：有数据但证据层不告警；
    // 有候选才 warn（对齐用例里覆盖）
    expect(byNode.terminal).toBe('ok')
  })

  it('CCA 规则对齐：确证规则走精确表，未登记规则诚实空对齐（无假兜底）', () => {
    const ws = buildWorkspaceCorrelation(base({
      scores: [score('radio', 40)],
      cca: ccaWith([
        cause({ rule_name: 'Downlink weak coverage(cell) ', confidence: 90 }),
        cause({ rule_name: 'Mystery Rule X', confidence: 80 }),
      ]),
    }))
    const weak = ws.rankedCauses.find((r) => r.label.includes('weak coverage'))
    const mystery = ws.rankedCauses.find((r) => r.label === 'Mystery Rule X')
    expect(weak?.aligned).toEqual(['radio'])
    expect(weak?.crossSupport).toBe(1) // radio=40 < scoreBad(50) → 满支持
    expect(mystery?.aligned).toEqual([])
    expect(mystery?.crossSupport).toBe(0)
  })

  it('关键词对齐只搜规则名，RETRAN → transport', () => {
    const ws = buildWorkspaceCorrelation(base({
      cca: ccaWith([cause({ rule_name: 'Tcp Retransmission Ratio High', confidence: 60 })]),
    }))
    expect(ws.rankedCauses[0]?.aligned).toEqual(['transport'])
  })

  it('排行 = 跨模块支持度×100 + 置信度，支持度优先于裸置信度', () => {
    const ws = buildWorkspaceCorrelation(base({
      scores: [score('radio', 40)],
      cca: ccaWith([
        cause({ rule_name: 'Downlink weak coverage(cell) ', confidence: 90 }),
        cause({ rule_name: 'Mystery Rule X', confidence: 99 }),
      ]),
    }))
    // 90 分但无对齐的 Mystery 排在 1.0 支持度 ×100+90 的 weak coverage 之后
    expect(ws.rankedCauses[0]?.label).toContain('weak coverage')
  })
})
