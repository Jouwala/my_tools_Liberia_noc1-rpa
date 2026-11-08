/* ============================================================================
 * vmaxCellCrossCheck 单测（2026-11-07 P3-2，vitest）
 * ============================================================================
 * 守护「CCA 小区 × RAN(32)」交叉验证层的四条判定与两条红线：
 *   1. 一致 / 不一致 / 无 32 数据 / 无 CCA 数据 四种判定都按真实字段产出；
 *   2. 任一侧无数据 = unknown，绝不落成「正常」；
 *   3. 小区名归一后精确匹配（不做模糊猜测）；
 *   4. KPI 对照只并列展示 —— 指标好坏**不影响**判定，也不改 buildVerdict。
 *
 * RAN 侧刻意用真实入口 analyzeRadio() 从合成 XdrRow 构造（顺带覆盖哨兵值
 * 255 / 65535 / 正数 RSRP 的过滤），不手搓 RadioAnalysis 对象。
 * ========================================================================== */

import { describe, expect, it } from 'vitest'

import {
  analyzeRadio, buildVerdict, scoreAll,
  type GameResult, type OttResult, type RadioAnalysis,
  type SourceResult, type VoiceResult, type XdrRow,
} from '../../pages/vmaxDiagnosisRules'
import type { CcaResult, CauseItem, CellRecord } from '../../components/VmaxCcaCards'
import { buildCellCrossCheck } from '../vmaxCellCrossCheck'

/* ---------------------------------------------------------------------------
 * 合成数据工厂：字段显式给出，不依赖默认值
 * ------------------------------------------------------------------------ */

const ranRow = (cell: string, over: Partial<XdrRow> = {}): XdrRow => ({
  cell,
  serving_rsrp: -95,
  ulsinr: 8,
  cqi: 10,
  btime: '2026-11-07 08:10:00',
  ...over,
})

const rowsOf = (cell: string, n: number, over: Partial<XdrRow> = {}): XdrRow[] =>
  Array.from({ length: n }, () => ranRow(cell, over))

const sourcesOf = (rows: XdrRow[]): SourceResult[] => ([
  { key: '32', label: '32', ok: true, rows, truncated: false },
])

/** 真实聚合入口：RAN(32) → RadioAnalysis（含哨兵值过滤与逐小区聚合） */
const radioOf = (rows: XdrRow[]): RadioAnalysis =>
  analyzeRadio(sourcesOf(rows)) as RadioAnalysis

const cellRec = (over: Partial<CellRecord> = {}): CellRecord => ({
  cellname: 'CellA', cell: 1001, cellkey: 'k1', ...over,
})

const cause = (over: Partial<CauseItem> = {}): CauseItem => ({
  rule_name: 'Downlink weak coverage(cell)', object_type: 'CELL(4G)',
  object_name: 'CellA', objectinfo: 'k1', confidence: 90,
  description: '', solution: '', vendor: 'ZTE', province: '', city: '',
  poortime: '', kqicode: 'k1', app_info: [],
  ...over,
})

const ccaOf = (over: Partial<CcaResult> = {}): CcaResult => ({
  msisdn: '231777777322', found: true, user: {}, terminal: null,
  causes: [], failures: [], cells: null, msg: '',
  ...over,
})

/* ---------------------------------------------------------------------------
 * 1. 一致：CCA 根因指向的小区 = 32 侧主驻留小区
 * ------------------------------------------------------------------------ */
describe('buildCellCrossCheck · 一致', () => {
  it('根因指向主驻留小区 → match，标题为 match.primary', () => {
    const radio = radioOf([...rowsOf('CellA', 4), ...rowsOf('CellB', 2)])
    const cca = ccaOf({
      causes: [cause({ object_name: 'CellA' })],
      cells: { cells: [cellRec({ cellname: 'CellA' })], cell_kpi: {} },
    })
    const cc = buildCellCrossCheck({ radio, cca })
    expect(cc.verdict).toBe('match')
    expect(cc.basis).toBe('cause')
    expect(cc.reason).toBeNull()
    expect(cc.ranPrimary).toBe('CellA')
    expect(cc.ranServed.map((c) => c.cell)).toEqual(['CellA', 'CellB'])
    expect(cc.matched).toEqual(['CellA'])
    expect(cc.headline.key).toBe('vmaxq.ws.cross.match.primary')
    expect(cc.headline.params).toMatchObject({ cell: 'CellA', n: 4 })
    expect(cc.refs.map((r) => r.kind)).toEqual(['records', 'cca'])
  })

  it('CCA 指向的是用户路过的次驻留小区 → match，标题为 match.other', () => {
    const radio = radioOf([...rowsOf('CellA', 4), ...rowsOf('CellB', 2)])
    const cca = ccaOf({ causes: [cause({ object_name: 'CellB' })] })
    const cc = buildCellCrossCheck({ radio, cca })
    expect(cc.verdict).toBe('match')
    expect(cc.matched).toEqual(['CellB'])
    expect(cc.ranPrimary).toBe('CellA')
    expect(cc.headline.key).toBe('vmaxq.ws.cross.match.other')
    expect(cc.headline.params).toMatchObject({ cell: 'CellB', n: 2, primary: 'CellA', m: 4 })
  })

  it('无 CELL 类根因时退回 CCA 驻留列表比较 → match.track', () => {
    const radio = radioOf(rowsOf('CellA', 3))
    const cca = ccaOf({ cells: { cells: [cellRec({ cellname: 'CellA' })], cell_kpi: {} } })
    const cc = buildCellCrossCheck({ radio, cca })
    expect(cc.basis).toBe('userTrack')
    expect(cc.verdict).toBe('match')
    expect(cc.headline.key).toBe('vmaxq.ws.cross.match.track')
  })

  it('CCA 驻留列表只覆盖次驻留小区时，match.track 说的是命中的那个小区', () => {
    const radio = radioOf([...rowsOf('CellA', 4), ...rowsOf('CellB', 2)])
    const cca = ccaOf({ cells: { cells: [cellRec({ cellname: 'CellB' })], cell_kpi: {} } })
    const cc = buildCellCrossCheck({ radio, cca })
    expect(cc.verdict).toBe('match')
    expect(cc.ranPrimary).toBe('CellA')
    expect(cc.matched).toEqual(['CellB'])
    // 不能说成「两侧都记录用户驻留 CellA」—— CCA 侧只记录了 CellB
    expect(cc.headline.params).toMatchObject({ cell: 'CellB', n: 2 })
  })

  it('小区名只用去空白 + 大写归一后精确匹配', () => {
    const radio = radioOf(rowsOf('Cell A', 3))
    const cca = ccaOf({ causes: [cause({ object_name: ' cell  a ' })] })
    const cc = buildCellCrossCheck({ radio, cca })
    expect(cc.verdict).toBe('match')
    expect(cc.matched).toEqual(['cell  a']) // 展示保留 CCA 原文
  })
})

/* ---------------------------------------------------------------------------
 * 2. 不一致：两侧都有数据但小区对不上（本身是排障线索，不是错误）
 * ------------------------------------------------------------------------ */
describe('buildCellCrossCheck · 不一致', () => {
  it('CCA 指向 CellB、用户 32 侧实际驻留 CellA → mismatch', () => {
    const radio = radioOf(rowsOf('CellA', 3))
    const cca = ccaOf({ causes: [cause({ object_name: 'CellB' })] })
    const cc = buildCellCrossCheck({ radio, cca })
    expect(cc.verdict).toBe('mismatch')
    expect(cc.reason).toBeNull()
    expect(cc.matched).toEqual([])
    expect(cc.ccaFlagged).toEqual(['CellB'])
    expect(cc.headline.key).toBe('vmaxq.ws.cross.mismatch')
    expect(cc.headline.params).toMatchObject({ cell: 'CellA', n: 3, cca: 'CellB' })
  })

  it('退回 CCA 驻留列表时也不一致 → mismatchTrack', () => {
    const radio = radioOf(rowsOf('CellA', 3))
    const cca = ccaOf({ cells: { cells: [cellRec({ cellname: 'CellB' })], cell_kpi: {} } })
    const cc = buildCellCrossCheck({ radio, cca })
    expect(cc.basis).toBe('userTrack')
    expect(cc.verdict).toBe('mismatch')
    expect(cc.headline.key).toBe('vmaxq.ws.cross.mismatchTrack')
  })
})

/* ---------------------------------------------------------------------------
 * 3. 无法判定：任一侧无数据 → unknown（绝不写「正常」）
 * ------------------------------------------------------------------------ */
describe('buildCellCrossCheck · 无法判定', () => {
  it('无 32 数据（radio=null）→ unknown / noRan', () => {
    const cc = buildCellCrossCheck({
      radio: null,
      cca: ccaOf({ causes: [cause()] }),
    })
    expect(cc.verdict).toBe('unknown')
    expect(cc.reason).toBe('noRan')
    expect(cc.headline.key).toBe('vmaxq.ws.cross.unknown.noRan')
  })

  it('32 有行但全是哨兵值（正数 RSRP / 255 / 65535）→ 无有效采样仍是 unknown', () => {
    const radio = radioOf([ranRow('CellA', { serving_rsrp: 0, ulsinr: 255, cqi: 65535 })])
    expect(radio.samples).toBe(0)
    const cc = buildCellCrossCheck({ radio, cca: ccaOf({ causes: [cause()] }) })
    expect(cc.verdict).toBe('unknown')
    expect(cc.reason).toBe('noRan')
  })

  it('无 CCA 数据（cca=null）→ unknown / noCca', () => {
    const cc = buildCellCrossCheck({ radio: radioOf(rowsOf('CellA', 3)), cca: null })
    expect(cc.verdict).toBe('unknown')
    expect(cc.reason).toBe('noCca')
    expect(cc.headline.key).toBe('vmaxq.ws.cross.unknown.noCca')
  })

  it('CCA 有返回但没有小区级信息（无 causes、无 cells）→ unknown / noCca', () => {
    const cc = buildCellCrossCheck({ radio: radioOf(rowsOf('CellA', 3)), cca: ccaOf() })
    expect(cc.verdict).toBe('unknown')
    expect(cc.reason).toBe('noCca')
  })
})

/* ---------------------------------------------------------------------------
 * 4. KPI 并列对照：只摆数字，不判阈值、不改结论
 * ------------------------------------------------------------------------ */
describe('buildCellCrossCheck · KPI 对照', () => {
  const ccaWithKpi = () => ccaOf({
    causes: [cause({ object_name: 'CellA' })],
    cells: {
      cells: [cellRec({ cellname: 'CellA', cell: 1001 })],
      cell_kpi: {
        '1001': [
          { code: 'ppc1_1', name: 'Average RSRP', value: '-88' },
          { code: 'ppc2_1', name: 'Average Uplink SINR', value: 3.5 },
          { code: 'ppc4_1', name: 'Average SSB-RSRQ', value: '--' },
        ],
      },
    },
  })

  it('同小区两侧 KPI 按族并列（RSRP / SINR 有 RAN 均值，RSRQ 只有 CCA 原值）', () => {
    const radio = radioOf([
      ...rowsOf('CellA', 2, { serving_rsrp: -100, ulsinr: 5, cqi: 10 }),
    ])
    const cc = buildCellCrossCheck({ radio, cca: ccaWithKpi() })
    expect(cc.cellKpis).toHaveLength(1)
    const rows = cc.cellKpis[0].rows
    const rsrp = rows.find((r) => r.id === 'rsrp')
    const sinr = rows.find((r) => r.id === 'sinr')
    const rsrq = rows.find((r) => r.id === 'rsrq')
    expect(rsrp?.ranAvg).toBe(-100)
    expect(rsrp?.cca).toEqual([{ code: 'ppc1_1', name: 'Average RSRP', value: '-88' }])
    expect(sinr?.ranAvg).toBe(5)
    // CCA 无值（'--'）归一成 null，界面显示 —（不是 0）；32 侧没有 RSRQ 字段
    expect(rsrq?.cca[0]?.value).toBeNull()
    expect(rsrq?.ranAvg).toBeNull()
    // 32 侧有 CQI 采样但 CCA 没给 CQI 条目：仍保留一行，CCA 列为空
    const cqi = rows.find((r) => r.id === 'cqi')
    expect(cqi?.ranAvg).toBe(10)
    expect(cqi?.cca).toEqual([])
  })

  it('32 侧该小区无有效采样时 ran=null、ranAvg=null（不是 0）', () => {
    const radio = radioOf(rowsOf('CellA', 2))
    // CCA 指向的小区在 32 侧没有采样
    const cca = ccaOf({
      causes: [cause({ object_name: 'CellB' })],
      cells: {
        cells: [cellRec({ cellname: 'CellB', cell: 2002 })],
        cell_kpi: { '2002': [{ code: 'ppc1_1', name: 'Average RSRP', value: '-120' }] },
      },
    })
    const cc = buildCellCrossCheck({ radio, cca })
    const hit = cc.cellKpis.find((c) => c.cell === 'CellB')
    expect(hit).toBeDefined()
    expect(hit?.ran).toBeNull()
    expect(hit?.rows.every((r) => r.ranAvg === null)).toBe(true)
    expect(hit?.rows[0].cca[0]?.value).toBe('-120')
  })

  it('KPI 好坏不参与判定：同小区名，无论 32 侧指标好坏都判 match', () => {
    const good = buildCellCrossCheck({
      radio: radioOf(rowsOf('CellA', 3, { serving_rsrp: -80, ulsinr: 20 })),
      cca: ccaWithKpi(),
    })
    const bad = buildCellCrossCheck({
      radio: radioOf(rowsOf('CellA', 3, { serving_rsrp: -120, ulsinr: -5 })),
      cca: ccaWithKpi(),
    })
    expect(good.verdict).toBe('match')
    expect(bad.verdict).toBe('match')
  })
})

/* ---------------------------------------------------------------------------
 * 5. 不篡改结论：buildCellCrossCheck 不修改入参、不影响 buildVerdict
 * ------------------------------------------------------------------------ */
describe('buildCellCrossCheck · 不改结论', () => {
  const noneVoice = (): VoiceResult => ({
    mode: 'none', sgsCount: 0, csfbTrigger: 0, esrCount: 0, pagingCount: 0,
    badCount: 0, successRate: null, fallbackMs: null, steps: [], qci1: 0, evidence: [],
  })
  const ottResult = (): OttResult => ({
    sessions: [], totalSessions: 5, totalDurationS: 100,
    avgDlRtt: 100, jitter: 0, retransRate: 0, baselineRtt: 80, evidence: [],
  })
  const emptyGame = (): GameResult => ({ hits: [], totalSessions: 0, evidence: [] })

  it('交叉验证不修改入参，buildVerdict 结果前后完全一致', () => {
    const rows = [...rowsOf('CellA', 4), ...rowsOf('CellB', 2)]
    const radio = radioOf(rows)
    const cca = ccaOf({ causes: [cause({ object_name: 'CellB' })] })
    const sources = sourcesOf(rows)
    const scores = scoreAll(sources)

    const before = JSON.stringify({ radio, cca })
    const v1 = buildVerdict('all', scores, noneVoice(), ottResult(), emptyGame(), sources)
    buildCellCrossCheck({ radio, cca })
    const v2 = buildVerdict('all', scores, noneVoice(), ottResult(), emptyGame(), sources)

    expect(JSON.stringify({ radio, cca })).toBe(before)
    expect(v2).toEqual(v1)
  })
})
