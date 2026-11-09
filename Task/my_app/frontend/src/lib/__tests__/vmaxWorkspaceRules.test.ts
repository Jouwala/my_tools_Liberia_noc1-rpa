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
  analyzeAccess, analyzeDataBlock, analyzeOttText, analyzeRadio, analyzeRateCeiling,
  analyzeTerminal, buildVerdict, classifyFailCause,
  scoreAll, THRESHOLDS,
  type DimensionScore, type GameResult, type OttResult,
  type SourceResult, type VoiceResult, type XdrRow,
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

/* ---------------------------------------------------------------------------
 * 5. P0-1 账务分型：强关键词才判 billing，数字码拒绝不等于欠费
 * ------------------------------------------------------------------------ */
describe('classifyFailCause / analyzeAccess（P0-1）', () => {
  it('强账务关键词 → billing；EPS 数字码措辞 → attach_reject（不判账务）', () => {
    expect(classifyFailCause('Insufficient balance, service stopped')).toBe('billing')
    expect(classifyFailCause('OCS credit control failed')).toBe('billing')
    expect(classifyFailCause('EMM cause 111: UE in use')).toBe('attach_reject')
    expect(classifyFailCause('DIAMETER_DATA_SUBSCRIBER_NOT_AVAILABLE')).toBe('attach_reject')
    // Gy Diameter 结果码（RFC 4006）：4012 余额不足 → billing；4010 服务拒绝 → attach
    expect(classifyFailCause('Result-Code: 4012')).toBe('billing')
    expect(classifyFailCause('Result-Code: 4010')).toBe('attach_reject')
    expect(classifyFailCause('ESM cause 12: ESM unknown APN')).toBe('attach_reject')
    expect(classifyFailCause('S1-U Path Failure')).toBe('transport_fail')
    expect(classifyFailCause('')).toBe('unknown')
  })

  it('1100 失败行带账务原因 → verdict 置顶为账务结论', () => {
    const sources = emptySources()
    sources.find((s) => s.key === '1100')!.rows = [
      { procedure_status: 'Failure', fail_cause: 'Insufficient balance', procedure_type: 'ATTACH' },
      { procedure_status: 'Failure', fail_cause: 'Insufficient balance', procedure_type: 'ATTACH' },
    ] as XdrRow[]
    const access = analyzeAccess(sources)
    expect(access.byCategory.billing).toBe(2)
    const v = buildVerdict('slow', nullScores(), noneVoice(), ottResult(), emptyGame(), sources)
    expect(v.headline.key).toBe('vmaxq.vd.headline.billing')
    expect(v.focus).toBe('availability')
    expect(v.hypotheses[0]?.id).toBe('h-billing')
    expect(v.hypotheses[0]?.owner).toBe('billing')
  })

  it('无任何失败时 missingEvidence 仍恒带「账务未查」（不沉默）', () => {
    const v = buildVerdict('all', nullScores(), noneVoice(), ottResult(), emptyGame(), emptySources())
    expect(v.missingEvidence.some((m) => m.key === 'vmaxq.vd.hyp.missing.billing')).toBe(true)
  })

  it('只有数字码拒绝（无强关键词）→ 不判账务，假设表显式列待补账务', () => {
    const sources = emptySources()
    sources.find((s) => s.key === '1100')!.rows = [
      { procedure_status: 'Failure', fail_cause: 'EMM cause 111: UE in use', procedure_type: 'ATTACH' },
    ] as XdrRow[]
    const v = buildVerdict('slow', nullScores(), noneVoice(), ottResult(), emptyGame(), sources)
    expect(v.headline.key).not.toBe('vmaxq.vd.headline.billing')
    expect(v.hypotheses[0]?.id).toBe('h-attach')
    expect(v.hypotheses[0]?.missing.some((m) => m.key === 'vmaxq.vd.hyp.missing.billing')).toBe(true)
  })
})

/* ---------------------------------------------------------------------------
 * 6. P0-2 OTT 文本：WhatsApp 发消息的 TCP 层判据
 * ------------------------------------------------------------------------ */
describe('analyzeOttText（P0-2）', () => {
  const wa = (over: Partial<XdrRow> = {}): XdrRow => ({
    app_content_name: 'WHATSAPP', protocol: 'TCP', duration: 5000,
    ul_traffic: 10, dl_traffic: 10, $first_resp_delay: 4000, ...over,
  })

  it('无 WhatsApp 行 → no_rows（不硬判发送失败）', () => {
    expect(analyzeOttText(emptySources()).stage).toBe('no_rows')
  })

  it('有行但零流量 → no_traffic；首包慢且流量小 → handshake_slow', () => {
    const mk = (rows: XdrRow[]) => {
      const s = emptySources()
      s.find((x) => x.key === '1300')!.rows = rows
      return analyzeOttText(s)
    }
    expect(mk([wa({ ul_traffic: 0, dl_traffic: 0 })]).stage).toBe('no_traffic')
    expect(mk([wa({ ul_traffic: 100, dl_traffic: 100, $first_resp_delay: 9000 })]).stage).toBe('handshake_slow')
    expect(mk([wa({ ul_traffic: 5000, dl_traffic: 5000, $first_resp_delay: 100 })]).stage).toBe('bidirectional')
  })

  it('OTT 投诉 + 文本通道异常 → ottTextBad 结论（不是 ottNone）', () => {
    const sources = emptySources()
    sources.find((s) => s.key === '1300')!.rows = [wa({ ul_traffic: 0, dl_traffic: 0 })]
    const v = buildVerdict('ott', nullScores(), noneVoice(),
      ottResult({ totalSessions: 0, sessions: [] }), emptyGame(), sources)
    expect(v.headline.key).toBe('vmaxq.vd.headline.ottTextBad')
    expect(v.reproduced).toBe(true)
  })
})

/* ---------------------------------------------------------------------------
 * 7. P0-3 无线分型：弱覆盖内部区分切换不及时 / 断站嫌疑 / 真弱覆盖
 * ------------------------------------------------------------------------ */
describe('analyzeRadio 无线分型（P0-3）', () => {
  const ran = (rows: XdrRow[]) => {
    const s = emptySources()
    s.find((x) => x.key === '32')!.rows = rows
    return analyzeRadio(s)!
  }
  const row = (over: Partial<XdrRow> = {}, i = 0): XdrRow => ({
    cell: 'CellA', serving_rsrp: -90, ulsinr: 10, cqi: 10,
    btime: `2026-11-07 08:${String(i).padStart(2, '0')}:00`, ...over,
  })

  it('serving 弱 + 邻区好 → handover_late_suspect', () => {
    const rows = Array.from({ length: 10 }, (_, i) => row({ serving_rsrp: -120, neighbor_rsrp: -85 }, i))
    const r = ran(rows)
    expect(r.mode).toBe('handover_late_suspect')
    expect(r.neighborSamples).toBe(10)
    expect(r.neighborGapDb).toBeGreaterThanOrEqual(10)
  })

  it('serving 弱 + 无邻区 → weak_coverage（结论只到弱覆盖）', () => {
    const rows = Array.from({ length: 10 }, (_, i) => row({ serving_rsrp: -120 }, i))
    const r = ran(rows)
    expect(r.mode).toBe('weak_coverage')
    expect(r.neighborSamples).toBe(0)
  })

  it('阶跃消失 → site_outage_suspect', () => {
    const rows = [
      ...Array.from({ length: 5 }, (_, i) => row({ serving_rsrp: -90 }, i)),
      ...Array.from({ length: 5 }, (_, i) => row({ serving_rsrp: -122 }, i + 10)),
    ]
    const r = ran(rows)
    expect(r.abruptDrop).toBe(true)
    expect(r.mode).toBe('site_outage_suspect')
  })

  it('TA/位置/站点距离：远弱覆盖与近弱覆盖走不同依据', () => {
    const farRows = Array.from({ length: 10 }, (_, i) => row({
      serving_rsrp: -120, ta_ts: 4500, mrlat: 6.3, mrlon: -10.8, neighbor_cell_number: 0,
    }, i))
    const far = ran(farRows)
    expect(far.taMedianM).toBe(4500)
    expect(far.posLat).toBeCloseTo(6.3)
    expect(far.neighborCountMedian).toBe(0)
    expect(far.basis.some((b) => b.key === 'vmaxq.radio.basis.farWeak')).toBe(true)
    expect(far.basis.some((b) => b.key === 'vmaxq.radio.basis.isolated')).toBe(true)

    const nearRows = Array.from({ length: 10 }, (_, i) => row({
      serving_rsrp: -120, ta_ts: 500, mrlat: 6.3, mrlon: -10.8, neighbor_cell_number: 3,
    }, i))
    const near = ran(nearRows)
    expect(near.basis.some((b) => b.key === 'vmaxq.radio.basis.nearWeak')).toBe(true)
  })

  it('渐变弱（中间有过渡值）→ 不是断站', () => {
    const rows = [
      ...Array.from({ length: 3 }, (_, i) => row({ serving_rsrp: -90 }, i)),
      ...Array.from({ length: 3 }, (_, i) => row({ serving_rsrp: -105 }, i + 5)),
      ...Array.from({ length: 3 }, (_, i) => row({ serving_rsrp: -118 }, i + 10)),
    ]
    const r = ran(rows)
    expect(r.abruptDrop).toBe(false)
    expect(r.mode).toBe('weak_coverage')
  })
})

/* ---------------------------------------------------------------------------
 * 8. 终端画像 + 限速推断（2026-11-08）
 * ------------------------------------------------------------------------ */
describe('analyzeTerminal / analyzeRateCeiling（2026-11-08）', () => {
  it('终端画像取 imei/机型/制式/APN 与主 QCI', () => {
    const sources = emptySources()
    sources.find((s) => s.key === '1300')!.rows = [
      { imei: '861234567890123', ue_model: 'XIAOMI 25019PNF3C', rat_name: '(4G)EUTRAN', apn: 'orangelbr', qci: '9' },
      { imei: '861234567890123', ue_model: 'XIAOMI 25019PNF3C', rat_name: '(4G)EUTRAN', apn: 'orangelbr', qci: '9' },
    ] as XdrRow[]
    const p = analyzeTerminal(sources)
    expect(p.imei).toBe('861234567890123')
    expect(p.model).toContain('XIAOMI')
    expect(p.rat).toContain('EUTRAN')
    expect(p.apn).toBe('orangelbr')
    expect(p.qciMain).toBe('9')
  })

  it('数据阻断嫌疑：附着成功+有尝试无流量才成立；只是没用数据不成立', () => {
    const mk = (trafficKb: number, slow: number) => {
      const sources = emptySources()
      sources.find((s) => s.key === '1100')!.rows = Array.from({ length: 10 }, () => ({
        procedure_status: 'Success',
      })) as XdrRow[]
      sources.find((s) => s.key === '1300')!.rows = Array.from({ length: 10 }, (_, i) => ({
        ul_traffic: i < slow ? 0 : trafficKb, dl_traffic: i < slow ? 0 : trafficKb,
        $first_resp_delay: i < slow ? 9000 : 100, qci: '9',
      })) as XdrRow[]
      return analyzeDataBlock(sources)
    }
    expect(mk(5000, 0).suspect).toBe(false)   // 流量在走 → 反证
    expect(mk(0, 2).suspect).toBe(false)      // 只有 2 条尝试 → 不够
    expect(mk(0, 5).suspect).toBe(true)       // 5 条尝试 + 零流量 + 附着成功
    const v = buildVerdict('slow', nullScores(), noneVoice(), ottResult(), emptyGame(), (() => {
      const sources = emptySources()
      sources.find((s) => s.key === '1100')!.rows = Array.from({ length: 10 }, () => ({
        procedure_status: 'Success',
      })) as XdrRow[]
      sources.find((s) => s.key === '1300')!.rows = Array.from({ length: 10 }, () => ({
        ul_traffic: 0, dl_traffic: 0, $first_resp_delay: 9000, qci: '9',
      })) as XdrRow[]
      return sources
    })())
    expect(v.hypotheses.some((h) => h.id === 'h-datablock')).toBe(true)
  })

  it('限速推断：样本不足显式不可推断；样本够则给 P90 天花板', () => {
    const mk = (n: number, kb: number) => {
      const sources = emptySources()
      sources.find((s) => s.key === '1300')!.rows = Array.from({ length: n }, () => ({
        qci: '9', dl_throughput_max: 5000, ul_throughput_max: 1000,
        ul_traffic: kb, dl_traffic: kb,
      })) as XdrRow[]
      return analyzeRateCeiling(sources)
    }
    const few = mk(5, 100)
    expect(few.rows[0]?.inferable).toBe(false)
    expect(few.evidence.some((e) => e.key === 'vmaxq.vd.ev.rateInsufficient')).toBe(true)
    const many = mk(40, 1000)
    expect(many.rows[0]?.inferable).toBe(true)
    expect(many.rows[0]?.dlP90Kbps).toBe(5000)
    expect(many.rows[0]?.ulP90Kbps).toBe(1000)
  })
})
