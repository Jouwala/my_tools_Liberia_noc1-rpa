/* ============================================================================
 * vmaxVerdictSnapshot 单测（2026-11-07 P3-3，vitest）
 * ============================================================================
 * 覆写记录随附的诊断快照是**审计证据**，三个性质必须锁住：
 *   1. 快照只打包既有状态（值原样带过来，本模块不重算口径）；
 *   2. 不存原始话单行 —— 因此号码明文不会进快照（号码只在表里的 msisdn_mask）；
 *   3. 读取端对坏数据/未知版本必须容错（返回 null 而不是让覆写弹窗崩掉）。
 *
 * 只测纯函数，不挂 React、不发请求。
 * ========================================================================== */

import { describe, expect, it } from 'vitest'

import {
  buildVerdictSnapshot, parseVerdictSnapshot, serializeVerdictSnapshot,
  snapshotSummary, SNAPSHOT_VERSION,
  type SnapshotInput,
} from '../vmaxVerdictSnapshot'
import type {
  DimensionScore, GameResult, OttResult, SourceResult, Verdict, VoiceResult,
} from '../../pages/vmaxDiagnosisRules'

const MSISDN = '231773777115'

const sources = (): SourceResult[] => ([
  {
    key: '1300', label: '用户面话单', label_key: 'vmaxq.diag.src.1300', ok: true,
    // 行里刻意带号码明文：快照若把 rows 带出去，下面的断言会失败
    rows: [{ msisdn: MSISDN, app_content_name: 'WHATSAPP' }, { msisdn: MSISDN }],
    truncated: true,
  },
  { key: '32', label: '无线质量', ok: false, rows: [], error: 'RAN 域无记录' },
])

const scores = (): DimensionScore[] => ([
  { key: 'availability', score: 92, sub: null, detail: { success: 88 }, evidence: [] },
  { key: 'latency', score: null, sub: null, detail: {}, evidence: [] },
])

const verdict = (): Verdict => ({
  headline: { key: 'vmaxq.vd.headline.allOk' },
  basis: [{ key: 'vmaxq.vd.basis.voiceNoSgs' }],
  suggestion: { key: 'vmaxq.vd.sugg.voiceNone' },
  confidence: 'high',
  reproduced: false,
  focus: 'voice',
})

const voice = (): VoiceResult => ({
  mode: 'csfb', sgsCount: 2, csfbTrigger: 1, esrCount: 2, pagingCount: 0,
  badCount: 1, successRate: 100, fallbackMs: 850, steps: [], qci1: 0, evidence: [],
})

const ott = (): OttResult => ({
  sessions: [], totalSessions: 3, totalDurationS: 120, avgDlRtt: 90,
  jitter: 12, retransRate: 0.4, baselineRtt: 70, evidence: [],
})

const game = (): GameResult => ({
  totalSessions: 2,
  hits: [{ app: 'PUBG', tier: 'keyword', records: 2, trafficKb: 10, avgRtt: 80, jitter: 5, retransRate: 0 }],
  evidence: [],
})

const input = (): SnapshotInput => ({
  complaint: 'voice',
  window: { start: '2026-11-07 08:00', end: '2026-11-07 10:00' },
  verdict: verdict(),
  scores: scores(),
  sources: sources(),
  voice: voice(),
  ott: ott(),
  game: game(),
  imsi: '231010000000001',
})

describe('buildVerdictSnapshot', () => {
  it('原样打包既有状态（不重算口径、补版本号与时间）', () => {
    const snap = buildVerdictSnapshot(input())
    expect(snap.version).toBe(SNAPSHOT_VERSION)
    expect(snap.generated_at).toBeTruthy()
    expect(snap.complaint).toBe('voice')
    expect(snap.window).toEqual({ start: '2026-11-07 08:00', end: '2026-11-07 10:00' })
    expect(snap.imsi).toBe('231010000000001')
    expect(snap.verdict?.confidence).toBe('high')
    expect(snap.verdict?.reproduced).toBe(false)
    expect(snap.scores.map((s) => s.score)).toEqual([92, null])  // null 保持 null，不塌成 0
    expect(snap.voice?.successRate).toBe(100)
    expect(snap.ott?.avgDlRtt).toBe(90)
    expect(snap.game?.totalSessions).toBe(2)
  })

  it('数据源只存条数与状态，不存 rows（号码明文不进快照）', () => {
    const snap = buildVerdictSnapshot(input())
    expect(snap.sources[0]).toMatchObject({ key: '1300', rows: 2, ok: true, truncated: true })
    expect(snap.sources[1]).toMatchObject({ key: '32', rows: 0, ok: false, error: 'RAN 域无记录' })
    const json = serializeVerdictSnapshot(snap)
    expect(json).not.toContain(MSISDN)
    expect(json).not.toContain('msisdn')
  })

  it('空状态（没有 verdict/语音/OTT/游戏）不抛错，对应字段为 null', () => {
    const snap = buildVerdictSnapshot({
      ...input(), verdict: null, voice: null, ott: null, game: null,
      sources: [], scores: [], imsi: null,
    })
    expect(snap.verdict).toBeNull()
    expect(snap.voice).toBeNull()
    expect(snap.ott).toBeNull()
    expect(snap.game).toBeNull()
    expect(snap.scores).toEqual([])
    expect(snap.imsi).toBeNull()
  })
})

describe('parseVerdictSnapshot', () => {
  it('往返：build → serialize → parse 得到同构快照', () => {
    const snap = buildVerdictSnapshot(input())
    const back = parseVerdictSnapshot(serializeVerdictSnapshot(snap))
    expect(back).toEqual(snap)
  })

  it('老记录/坏数据/未知版本一律返回 null（不抛错）', () => {
    expect(parseVerdictSnapshot(null)).toBeNull()
    expect(parseVerdictSnapshot('')).toBeNull()
    expect(parseVerdictSnapshot('not json')).toBeNull()
    expect(parseVerdictSnapshot('[1,2,3]')).toBeNull()
    expect(parseVerdictSnapshot(JSON.stringify({ version: 99 }))).toBeNull()
    // 版本号对但骨架缺失：不能让覆写弹窗渲染时抛 TypeError
    expect(parseVerdictSnapshot(JSON.stringify({ version: 1 }))).toBeNull()
    expect(parseVerdictSnapshot(JSON.stringify({
      version: 1, generated_at: 'x', complaint: 'voice',
      window: { start: 'a', end: 'b' }, scores: [], sources: [],
      verdict: { headline: { key: 'k' } },   // 缺 basis / suggestion
    }))).toBeNull()
  })
})

describe('snapshotSummary', () => {
  it('导出摘要只用快照既有值（置信度/复现/四维/源条数）', () => {
    const snap = buildVerdictSnapshot(input())
    const seen: string[] = []
    const t = (key: string, params?: Record<string, string | number>) => {
      seen.push(key)
      if (key === 'vmaxq.override.snapshotSummary') {
        return JSON.stringify(params)
      }
      return key
    }
    const text = snapshotSummary(snap, t)
    expect(seen).toContain('vmaxq.override.snapshotSummary')
    const params = JSON.parse(text) as Record<string, string>
    expect(params.scores).toBe('92/—/—/—')  // 缺的维度显示 —，不是 0
    expect(params.sources).toContain('1300:2')
    expect(params.sources).toContain('32:0!')  // ! = 该源失败
    expect(params.conf).toBe('vmaxq.diag.confidence.high')
    expect(snapshotSummary(null, t)).toBe('')
  })
})
