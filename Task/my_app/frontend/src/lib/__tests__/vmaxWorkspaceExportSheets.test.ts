/* ============================================================================
 * vmaxWorkspaceExport 的「旧页兼容 / 工作台新增」工作表清单单测（P3-2b）
 * ============================================================================
 * 直接调用入口函数 exportVmaxDiagnosisExcel，把统一导出组件
 * utils/excelReport 的 exportReport **mock 掉**（只截获 Excel 规格、不真下载），
 * 于是能断言：
 *   1. 旧页 VmaxUserQuery 的调用方式（不传 chain / rankedCauses / crossCheck）
 *      → 仍然只有旧的 4 张表，名字与顺序完全不变；
 *   2. 工作台传入 crossCheck → 多出「小区交叉验证」一张，位置在根因排行之后、
 *      证据时间线之前；交叉验证为空（null）时不多表。
 * ========================================================================== */

import { describe, expect, it, vi } from 'vitest'

/** vi.mock 是提升的：用它截获导出规格（不写文件、不触发浏览器下载） */
const captured = vi.hoisted(() => ({
  specs: [] as { name: string }[],
  filename: '',
}))

vi.mock('../../utils/excelReport', () => ({
  exportReport: async (specs: { name: string }[], filename: string) => {
    captured.specs = specs
    captured.filename = filename
  },
}))

import {
  exportVmaxDiagnosisExcel, type TFunc, type VmaxExportInput,
} from '../vmaxWorkspaceExport'
import { buildCellCrossCheck } from '../vmaxCellCrossCheck'
import {
  analyzeRadio, type RadioAnalysis, type SourceResult, type Verdict, type XdrRow,
} from '../../pages/vmaxDiagnosisRules'
import type { CcaResult, CauseItem } from '../../components/VmaxCcaCards'

/* ---------------------------------------------------------------------------
 * 最小可用输入（t 用「回显 key」的假实现，导出规格里的 name 就是 i18n key）
 * ------------------------------------------------------------------------ */

const t: TFunc = (key) => key

/** 测试专用假文案（key 首段 x 不是字典命名空间，check:i18n 的间接引用规则不会把它当文案键） */
const fakeText = (key: string) => ({ key })

const fakeVerdict = {
  headline: fakeText('x.headline'),
  confidence: 'low',
  reproduced: false,
  basis: [],
  suggestion: fakeText('x.suggestion'),
} as unknown as Verdict

const ranRow = (cell: string): XdrRow => ({
  cell, serving_rsrp: -100, ulsinr: 5, cqi: 10, btime: '2026-11-07 08:10:00',
})

const radioOf = (rows: XdrRow[]): RadioAnalysis => {
  const sources: SourceResult[] = [{ key: '32', label: '32', ok: true, rows, truncated: false }]
  return analyzeRadio(sources) as RadioAnalysis
}

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

const baseInput = (): VmaxExportInput => ({
  msisdn: '231777777322',
  win: { start: '2026-11-07 08:00', end: '2026-11-07 09:00' },
  complaint: 'all',
  verdict: fakeVerdict,
  override: null,
  scores: [],
  sources: [],
  timeline: [],
  voice: null,
  flowXdr: null,
})

/** 旧页 4 张表的顺序（VmaxUserQuery 不传工作台专属参数） */
const OLD_SHEETS = [
  'vmaxq.diag.card', 'vmaxq.tl.card', 'vmaxq.voice.card', 'vmaxq.flow.cat.all',
]

describe('exportVmaxDiagnosisExcel · 工作表清单', () => {
  it('旧页调用方式（不传 crossCheck/chain/rankedCauses）与旧行为完全一致：4 张表、无空表', async () => {
    captured.specs = []
    await exportVmaxDiagnosisExcel(baseInput(), t)
    expect(captured.specs.map((s) => s.name)).toEqual(OLD_SHEETS)
  })

  it('工作台传 crossCheck 后：多出「小区交叉验证」表，位置在根因排行之后、时间线之前', async () => {
    const crossCheck = buildCellCrossCheck({
      radio: radioOf([ranRow('CellA'), ranRow('CellA')]),
      cca: ccaOf({ causes: [cause()] }),
    })
    captured.specs = []
    await exportVmaxDiagnosisExcel({
      ...baseInput(),
      chain: [{ node: 'ran', level: 'bad' }],
      rankedCauses: [],
      crossCheck,
    }, t)

    const names = captured.specs.map((s) => s.name)
    // 精确断言顺序：结论 → 链路 → 小区交叉验证 → 时间线 → 语音 → 流量
    expect(names).toEqual([
      'vmaxq.diag.card',
      'vmaxq.ws.chain.title',
      'vmaxq.ws.cross.exp.sheet',
      'vmaxq.tl.card',
      'vmaxq.voice.card',
      'vmaxq.flow.cat.all',
    ])
  })

  it('crossCheck 为 null（工作台尚未取到数据）时不多出空表', async () => {
    captured.specs = []
    await exportVmaxDiagnosisExcel({
      ...baseInput(), crossCheck: null,
    }, t)
    expect(captured.specs.map((s) => s.name)).toEqual(OLD_SHEETS)
  })
})
