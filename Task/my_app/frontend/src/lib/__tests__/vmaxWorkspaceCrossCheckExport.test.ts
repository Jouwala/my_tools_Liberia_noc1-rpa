/* ============================================================================
 * vmaxWorkspaceExport 的小区交叉验证工作表单测（2026-11-07 P3-2b，vitest）
 * ============================================================================
 * 守护三件事：
 *   1. 旧页兼容：不传 crossCheck（旧页 VmaxUserQuery 的调用方式）时
 *      crossCheckSheets() 返回 []，展开进导出规格后与旧行为完全一致
 *      （不出现空表、空行）；
 *   2. 工作台传了 crossCheck 时组装出「判定事实 + KPI 并列对照」同一张表，
 *      列名走 i18n key、无采样显示 —、数字保持 number（不是文本）；
 *   3. 生成的 sheet 能真的被 ExcelJS 序列化并回读（「Excel 打开可读」的
 *      机器可验证代理：xlsx.writeBuffer + xlsx.load 往返不抛错）。
 *
 * 只测纯组装函数 + 统一导出组件（不触发浏览器下载、不 mock DOM）。
 * ========================================================================== */

import { describe, expect, it } from 'vitest'
import ExcelJS from 'exceljs'

import { buildReportWorkbook } from '../../utils/excelReport'
import { crossCheckSheets, type TFunc } from '../vmaxWorkspaceExport'
import { buildCellCrossCheck, type CellCrossCheck } from '../vmaxCellCrossCheck'
import {
  analyzeRadio, type RadioAnalysis, type SourceResult, type XdrRow,
} from '../../pages/vmaxDiagnosisRules'
import type { CcaResult, CauseItem, CellRecord } from '../../components/VmaxCcaCards'

/* ---------------------------------------------------------------------------
 * 合成数据：RAN 侧走真实 analyzeRadio，CCA 侧字段按 VmaxCcaCards 类型给全
 * ------------------------------------------------------------------------ */

const ranRow = (cell: string, over: Partial<XdrRow> = {}): XdrRow => ({
  cell, serving_rsrp: -95, ulsinr: 8, cqi: 10,
  btime: '2026-11-07 08:10:00', ...over,
})

const radioOf = (rows: XdrRow[]): RadioAnalysis => {
  const sources: SourceResult[] = [{ key: '32', label: '32', ok: true, rows, truncated: false }]
  return analyzeRadio(sources) as RadioAnalysis
}

const cellRec = (over: Partial<CellRecord> = {}): CellRecord => ({
  cellname: 'CellA', cell: 1001, cellkey: 'k1', ...over,
})

const cause = (over: Partial<CauseItem> = {}): CauseItem => ({
  rule_name: 'Downlink weak coverage(cell)', object_type: 'CELL(4G)',
  object_name: 'CellA', objectinfo: 'k1', confidence: 90,
  description: '', solution: '', vendor: 'ZTE', province: '', city: '',
  poortime: '', kqicode: 'k1', app_info: [], ...over,
})

const ccaOf = (over: Partial<CcaResult> = {}): CcaResult => ({
  msisdn: '231777777322', found: true, user: {}, terminal: null,
  causes: [], failures: [], cells: null, msg: '', ...over,
})

/** 一致场景：32 主驻留 CellA（4 个采样，RSRP 均值 -100 / P10 -110），
 *  CCA 根因也指向 CellA，并给出 RSRP / SINR / RSRQ 三条小区 KPI。 */
const matchCrossCheck = (): CellCrossCheck => buildCellCrossCheck({
  radio: radioOf([
    ranRow('CellA', { serving_rsrp: -90 }), ranRow('CellA', { serving_rsrp: -100 }),
    ranRow('CellA', { serving_rsrp: -110 }), ranRow('CellA', { serving_rsrp: -100 }),
    ranRow('CellB', { serving_rsrp: -95 }), ranRow('CellB', { serving_rsrp: -95 }),
  ]),
  cca: ccaOf({
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
  }),
})

/** 假 t：返回真实中文模板才能验证 stripBold；没登记的键原样返回 key，
 *  便于断言「列名用的是 i18n key」而不是写死中文。 */
const fakeDict: Record<string, string> = {
  'vmaxq.ws.cross.match.primary':
    '相互印证：CCA 指出的小区正是用户 32 侧主驻留小区 **{{cell}}**（{{n}} 个有效采样）',
}
const t: TFunc = (key, params) => {
  const raw = fakeDict[key] ?? key
  if (!params) return raw
  return Object.entries(params).reduce(
    (s, [k, v]) => s.replaceAll(`{{${k}}}`, String(v)), raw)
}

/** 按第一列标签找行（判定事实块） */
const rowByLabel = (rows: (string | number)[][], label: string) =>
  rows.find((r) => r[0] === label)

/* ---------------------------------------------------------------------------
 * 1. 旧页兼容：不传 crossCheck → 不追加任何工作表
 * ------------------------------------------------------------------------ */
describe('crossCheckSheets · 旧页兼容', () => {
  it('不传 / 传 null → 返回空数组（展开后导出与旧版完全一致）', () => {
    expect(crossCheckSheets(undefined, t, 'w')).toEqual([])
    expect(crossCheckSheets(null, t, 'w')).toEqual([])
  })
})

/* ---------------------------------------------------------------------------
 * 2. 判定事实块：判定/原因/一句话判定/主驻留/两侧列表/命中小区
 * ------------------------------------------------------------------------ */
describe('crossCheckSheets · 判定事实', () => {
  it('一致场景：表名与列名走 i18n key，判定值、采样数、驻留列表正确', () => {
    const sheets = crossCheckSheets(matchCrossCheck(), t, '2026-11-07 08:00 ~ 09:00')
    expect(sheets).toHaveLength(1)
    const sheet = sheets[0]
    expect(sheet.name).toBe('vmaxq.ws.cross.exp.sheet')
    expect(sheet.header).toEqual(['vmaxq.ws.cross.exp.item', 'vmaxq.ws.cross.exp.value'])
    expect(sheet.subtitle).toBe('2026-11-07 08:00 ~ 09:00')
    expect(sheet.autoFilter).toBe(false) // 判定块 2 列 + KPI 块 6 列，筛选无意义

    const rows = sheet.rows as (string | number)[][]
    expect(rowByLabel(rows, 'vmaxq.ws.cross.exp.verdict')?.[1])
      .toBe('vmaxq.ws.cross.verdict.match')
    expect(rowByLabel(rows, 'vmaxq.ws.cross.exp.reason')?.[1]).toBe('—')
    // 一句话判定：**强调** 必须被 stripBold 去掉（工单里不能出现星号）
    const summary = String(rowByLabel(rows, 'vmaxq.ws.cross.exp.summary')?.[1])
    expect(summary).toContain('CellA')
    expect(summary).not.toContain('**')
    expect(rowByLabel(rows, 'vmaxq.ws.cross.exp.ranPrimary')?.[1]).toBe('CellA')
    expect(rowByLabel(rows, 'vmaxq.ws.cross.exp.ranSamples')?.[1]).toBe(4)
    expect(rowByLabel(rows, 'vmaxq.ws.cross.exp.ranServedList')?.[1])
      .toBe('CellA (4) / CellB (2)')
    expect(rowByLabel(rows, 'vmaxq.ws.cross.exp.ccaFlagged')?.[1]).toBe('CellA')
    expect(rowByLabel(rows, 'vmaxq.ws.cross.exp.matched')?.[1]).toBe('CellA')
  })

  it('无法判定场景：原因列给出原因 key，驻留/KPI 列显示 —（不是空串）', () => {
    const cc = buildCellCrossCheck({
      radio: null,
      cca: ccaOf({ causes: [cause({ object_name: 'CellA' })] }),
    })
    const sheet = crossCheckSheets(cc, t, 'w')[0]
    const rows = sheet.rows as (string | number)[][]
    expect(rowByLabel(rows, 'vmaxq.ws.cross.exp.verdict')?.[1])
      .toBe('vmaxq.ws.cross.verdict.unknown')
    expect(rowByLabel(rows, 'vmaxq.ws.cross.exp.reason')?.[1])
      .toBe('vmaxq.ws.cross.reason.noRan')
    expect(rowByLabel(rows, 'vmaxq.ws.cross.exp.ranPrimary')?.[1]).toBe('—')
    expect(rowByLabel(rows, 'vmaxq.ws.cross.exp.ranSamples')?.[1]).toBe('—')
    expect(rowByLabel(rows, 'vmaxq.ws.cross.exp.ranServedList')?.[1]).toBe('—')
  })
})

/* ---------------------------------------------------------------------------
 * 3. KPI 对照块：6 列表头、数字列是 number、无采样是 —
 * ------------------------------------------------------------------------ */
describe('crossCheckSheets · KPI 对照块', () => {
  const kpiRows = (sheet: ReturnType<typeof crossCheckSheets>[number]) => {
    const rows = sheet.rows as (string | number)[][]
    const start = rows.findIndex((r) => r[0] === 'vmaxq.ws.cross.kpi.title')
    return { all: rows, start, block: rows.slice(start + 2) } // +1 小节标题 +1 子表头
  }

  it('子表头 6 列走 i18n；RSRP 行 CCA 值/均值/P10 都是 number', () => {
    const sheet = crossCheckSheets(matchCrossCheck(), t, 'w')[0]
    const { all, start, block } = kpiRows(sheet)
    expect(all[start + 1]).toEqual([
      'vmaxq.ws.cross.kpi.cell', 'vmaxq.ws.cross.kpi.metric',
      'vmaxq.ws.cross.exp.ccaName', 'vmaxq.ws.cross.exp.ccaValue',
      'vmaxq.ws.cross.kpi.ran', 'vmaxq.ws.cross.exp.ranP10',
    ])
    const rsrp = block.find((r) => r[1] === 'RSRP')
    expect(rsrp?.[2]).toBe('Average RSRP')
    expect(rsrp?.[3]).toBe(-88)   // CCA 原值数字串 → number
    expect(rsrp?.[4]).toBe(-100)  // RAN 均值（整数）
    expect(rsrp?.[5]).toBe(-110)  // RAN P10（最差 10% 边缘电平）
    // RSRQ 在 32 侧没有字段：只列 CCA 值，RAN 两列是 —
    const rsrq = block.find((r) => r[1] === 'RSRQ')
    expect(rsrq?.[3]).toBe('—') // CCA 的 '--' 归一成无值
    expect(rsrq?.[4]).toBe('—')
    expect(rsrq?.[5]).toBe('—')
    // 32 有 CQI 采样、CCA 没给 CQI：行保留、CCA 两列 —
    const cqi = block.find((r) => r[1] === 'CQI')
    expect(cqi?.[3]).toBe('—')
    expect(cqi?.[4]).toBe(10)
    // 主驻留标记进小区标签（不新增列）
    expect(rsrp?.[0]).toBe('CellA (vmaxq.ws.cross.kpi.primaryTag)')
  })

  it('CCA 数值文本（如百分比）原样保留，不强行转 number', () => {
    const cc = buildCellCrossCheck({
      radio: radioOf([ranRow('CellA')]),
      cca: ccaOf({
        causes: [cause({ object_name: 'CellA' })],
        cells: {
          cells: [cellRec()],
          cell_kpi: { '1001': [{ code: 'ppc9_1', name: 'Average RSRP', value: '12.33%' }] },
        },
      }),
    })
    const sheet = crossCheckSheets(cc, t, 'w')[0]
    const { block } = kpiRows(sheet)
    expect(block.find((r) => r[1] === 'RSRP')?.[3]).toBe('12.33%')
  })
})

/* ---------------------------------------------------------------------------
 * 4. Excel 可读性代理：统一导出组件能序列化并回读（不触发下载）
 * ------------------------------------------------------------------------ */
describe('crossCheckSheets · Excel 往返', () => {
  it('buildReportWorkbook → writeBuffer → load 回读，中文表名与数字单元格不丢', async () => {
    const sheet = crossCheckSheets(matchCrossCheck(), t, '2026-11-07 08:00 ~ 09:00')[0]
    const wb = buildReportWorkbook([sheet])
    const ws = wb.getWorksheet(sheet.name)
    expect(ws).toBeTruthy()

    const buf = await wb.xlsx.writeBuffer()
    expect(buf.byteLength).toBeGreaterThan(0)

    const wb2 = new ExcelJS.Workbook()
    await wb2.xlsx.load(buf as ArrayBuffer)
    const ws2 = wb2.getWorksheet(sheet.name)
    expect(ws2).toBeTruthy()
    // 标题行（第 1 行）与判定行（第 4 行）都在；采样数是数字而不是文本
    expect(String(ws2?.getCell(1, 1).value)).toContain('vmaxq.ws.cross.title')
    expect(ws2?.getCell(4, 1).value).toBe('vmaxq.ws.cross.exp.verdict')
    expect(ws2?.getCell(8, 2).value).toBe(4)
    expect(typeof ws2?.getCell(8, 2).value).toBe('number')
  })
})
