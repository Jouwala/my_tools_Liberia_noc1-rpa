/* ============================================================================
 * vmaxCellCrossCheck.ts —— CCA 小区 KPI × RAN(32) 的交叉验证层（P3-2）
 * ============================================================================
 *
 * 2026-11-07 新建。解决一个具体缺口：`cca.cells.cell_kpi` 此前只活在「驻留
 * 小区」弹窗里，关联层 terminal 节点只数 causes 个数；而 CCA 的小区级无线
 * 指标与 RAN(32) 的 UE 级 MR 采样本来可以互证 ——「投诉/根因指向的小区」与
 * 「用户实际驻留的小区」是不是同一个，是投诉处理最经典的第一个排障动作。
 *
 * 【本层只做并列与关联，不做判定】三条红线（与 vmaxWorkspaceRules.ts 一致）：
 *   1. buildVerdict 是唯一结论来源，本文件**不参与结论**，也不改任何 verdict；
 *   2. 阈值唯一出处是 vmaxDiagnosisRules.ts 的 `THRESHOLDS`，本层不复制阈值、
 *      不按指标数值重新判「好坏」—— KPI 对照只并列展示两侧原值；
 *   3. 无数据 = unknown，绝不写「正常」。两侧都有数据但小区对不上才叫
 *      「不一致」，且不一致本身是排障线索，不是错误。
 *
 * 【为什么单独一个文件，而不是塞进 vmaxWorkspaceRules.ts】
 *   后者 2026-11-07 恰好已到 500 行（AGENTS.md 三.2 单文件 <500 行），再往里
 *   加就会把它推过上限；本文件是独立可测的纯函数模块，不依赖 React。
 *
 * 【数据来源（全部是既有接口字段，不新增取数）】
 *   - RAN 侧：`RadioAnalysis`（pages/vmaxDiagnosisRules.ts 的 analyzeRadio 产出，
 *     只吃 source key === '32' 的行）。逐小区字段：cell / samples / rsrpAvg /
 *     rsrpP10 / sinrAvg / cqiAvg。**复用它的聚合，不在本层重新解析原始行** ——
 *     哨兵值过滤（rsrp 正数、sinr 255、cqi 65535 都当无采样）与小区名取值
 *     （上游列叫 `cell`）只在 analyzeRadio 一处，避免第二套口径。
 *   - CCA 侧：`CcaResult.cells.cells`（userTrack 驻留小区，CellRecord.cellname）
 *     与 `CcaResult.causes`（根因，object_type 含 CELL 时 object_name 即小区名）；
 *     `cells.cell_kpi` 的键是 `cell ?? cellkey ?? cellname`（与
 *     components/VmaxCcaCards.tsx 的 cellKpiKey 同口径）。
 *
 * 【判定规则（诚实优先）】
 *   - 归一：小区名「去全部空白 + 转大写」后**精确比较**。不做模糊/别名/拼音
 *     匹配 —— 猜错会造出假的「一致」，比不判更糟。
 *   - 基准小区：CCA 根因里有 CELL 类对象 → 用根因指向的小区（basis='cause'）；
 *     否则退回 CCA 驻留列表（basis='userTrack'），仍是有价值的 A/B 互证。
 *   - 一致：基准小区与 32 侧驻留小区有交集（match）。
 *   - 不一致：两侧都有数据但无交集（mismatch）。
 *   - 无法判定：32 侧无有效采样，或 CCA 侧无小区级信息（unknown）——
 *     界面必须常驻显示「无法判定」，不得落成「正常」。
 * ========================================================================== */

import {
  tx, type I18nText, type RadioAnalysis, type RadioCell,
} from '../pages/vmaxDiagnosisRules'
import type { CcaResult, CellRecord } from '../components/VmaxCcaCards'
import type { EvidenceRef } from './vmaxWorkspaceRules'

/* ---------------------------------------------------------------------------
 * 类型
 * ------------------------------------------------------------------------ */

export type CrossVerdict = 'match' | 'mismatch' | 'unknown'

/** unknown 的具体原因：32 侧无有效采样 / CCA 侧无小区级信息 */
export type CrossReason = 'noRan' | 'noCca' | null

/** 基准小区来源：CCA 根因 / CCA 驻留列表 */
export type CrossBasis = 'cause' | 'userTrack' | null

/** 可与 RAN 侧对照的 KPI 族（RSRQ 在 32 侧没有对应字段，只并列 CCA 值） */
export type KpiMetricId = 'rsrp' | 'sinr' | 'cqi' | 'rsrq'

/** CCA 小区 KPI 原始条目（名称/数值原样，只做空值归一） */
export type KpiItemRow = { code: string; name: string; value: string | null }

/** 一行指标对照：CCA 原值 vs RAN 同小区聚合 */
export type KpiCompareRow = {
  id: KpiMetricId
  /** CCA 侧命中该族的条目（可能多条：如 UL SINR / DL SSB-SINR） */
  cca: KpiItemRow[]
  /** RAN 侧该小区有效采样数（0 = 该小区在 32 侧无有效采样） */
  ranSamples: number
  /** RAN 侧均值；null = 无采样（界面显示 —，不是 0） */
  ranAvg: number | null
  /** RAN 侧 RSRP 的 P10（边缘 10% 电平），其他族为 null */
  ranP10: number | null
  /** 展示单位（只用于排版，不参与判定） */
  unit: string
}

/** 单个小区的 KPI 对照块 */
export type CrossCellKpi = {
  /** 小区名（展示用原文，取自 CCA 或 RAN） */
  cell: string
  /** 该小区是否就是 32 侧主驻留小区 */
  isRanPrimary: boolean
  /** RAN 侧同名小区聚合；null = 32 侧没有该小区的有效采样 */
  ran: RadioCell | null
  rows: KpiCompareRow[]
}

export type CellCrossCheck = {
  verdict: CrossVerdict
  /** verdict === 'unknown' 时的具体原因，否则 null */
  reason: CrossReason
  /** 拿什么跟 32 侧比：CCA 根因 / CCA 驻留列表；两侧都无小区信息时 null */
  basis: CrossBasis
  /** RAN(32) 主驻留小区（有效采样最多）；null = 无有效采样 */
  ranPrimary: string | null
  /** RAN(32) 驻留小区（有效采样降序，samples=0 的不算驻留） */
  ranServed: RadioCell[]
  /** CCA 根因指出的小区（CELL 类 object_name，去重保序） */
  ccaFlagged: string[]
  /** CCA 驻留小区（userTrack 的 cellname，去重保序） */
  ccaServed: string[]
  /** 归一后与 32 侧驻留小区命中的 CCA 小区名（展示用原文） */
  matched: string[]
  /** 一句话判定（规则层只产 I18nText，渲染层翻译） */
  headline: I18nText
  /** 参与 KPI 并列对照的小区（命中小区 / 32 主驻留 / CCA 首个指出，最多 3 个） */
  cellKpis: CrossCellKpi[]
  /** 证据入口：32 原始记录 / CCA 画像 */
  refs: EvidenceRef[]
}

/** 判定 → i18n key（组件与导出共用一份，勿在组件里各写一份） */
export const CROSS_VERDICT_KEY: Record<CrossVerdict, string> = {
  match: 'vmaxq.ws.cross.verdict.match',
  mismatch: 'vmaxq.ws.cross.verdict.mismatch',
  unknown: 'vmaxq.ws.cross.verdict.unknown',
}

/** 表头列名（组件表格用；列名也是文案，走字典） */
export const CROSS_KPI_COL_KEY = {
  cell: 'vmaxq.ws.cross.kpi.cell',
  metric: 'vmaxq.ws.cross.kpi.metric',
  ran: 'vmaxq.ws.cross.kpi.ran',
  cca: 'vmaxq.ws.cross.kpi.cca',
  primaryTag: 'vmaxq.ws.cross.kpi.primaryTag',
} as const

/* ---------------------------------------------------------------------------
 * 小工具
 * ------------------------------------------------------------------------ */

/**
 * 小区名归一：去全部空白 + 转大写后精确比较。
 * 刻意**不做**模糊/别名/拼音匹配 —— 猜错会造出假「一致」。
 */
const normCell = (v: unknown): string => String(v ?? '').trim().replace(/\s+/g, '').toUpperCase()

/** CCA KPI 值归一：上游用 "--" / 空串表示无值，统一成 null（界面显示 —） */
const fmtKpiValue = (v: unknown): string | null => {
  if (v === null || v === undefined) return null
  const s = String(v).trim()
  return !s || s === '--' || s === '-' ? null : s
}

/** 列表拼接：分隔符用语言中立的 " / "（列表本身是数据，不是文案） */
const joinCells = (list: string[]): string => {
  const head = list.slice(0, 3).join(' / ')
  return list.length > 3 ? `${head} …` : head
}

/** CCA 根因里 CELL 类对象指向的小区（去重保序） */
function ccaFlaggedCells(cca: CcaResult | null): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const c of cca?.causes || []) {
    if (!String(c.object_type || '').toUpperCase().includes('CELL')) continue
    const name = String(c.object_name ?? '').trim()
    const key = normCell(name)
    if (!name || !key || seen.has(key)) continue
    seen.add(key)
    out.push(name)
  }
  return out
}

/** CCA 驻留小区（userTrack 的 cellname，去重保序） */
function ccaServedCells(cca: CcaResult | null): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const cell of cca?.cells?.cells || []) {
    const name = String(cell.cellname ?? '').trim()
    const key = normCell(name)
    if (!name || !key || seen.has(key)) continue
    seen.add(key)
    out.push(name)
  }
  return out
}

/** 某小区在 CCA cell_kpi 里的全部 KPI 条目 */
function ccaKpiItems(cca: CcaResult | null, cellName: string): KpiItemRow[] {
  const cells = cca?.cells
  if (!cells) return []
  const key = normCell(cellName)
  const rec: CellRecord | undefined = cells.cells.find((c) => normCell(c.cellname) === key)
  if (!rec) return []
  // 与 VmaxCcaCards.tsx 的 cellKpiKey 同口径：cell → cellkey → cellname
  const kpiKey = String(rec.cell ?? rec.cellkey ?? rec.cellname ?? '')
  return (cells.cell_kpi[kpiKey] || []).map((it) => ({
    code: it.code,
    name: it.name,
    value: fmtKpiValue(it.value),
  }))
}

/* ---------------------------------------------------------------------------
 * KPI 族：CCA 名称匹配 + RAN 侧取值
 *
 * 只用于「把两侧同一指标摆在一起」，**不参与好坏判定**。CCA 的 KPI 名称来自
 * 上游字典（global/kpi_popup/query_kpi，见 backend/services/vmax_cca/README.md），
 * 实测形如 "Average RSRP" / "Average Uplink SINR" / "Average SSB-RSRQ"；
 * 按关键字归类，比逐条登记名称稳（字典会随制式增删）。
 * RAN 侧 0 表示无有效采样（analyzeRadio 已把哨兵值过滤成 0），显示 — 不是 0。
 * ------------------------------------------------------------------------ */

type KpiFamily = {
  id: KpiMetricId
  pattern: RegExp
  unit: string
  ranAvg: (c: RadioCell) => number | null
  ranP10: (c: RadioCell) => number | null
}

const KPI_FAMILIES: KpiFamily[] = [
  { id: 'rsrp', pattern: /RSRP/i, unit: 'dBm',
    ranAvg: (c) => c.rsrpAvg || null, ranP10: (c) => c.rsrpP10 || null },
  { id: 'sinr', pattern: /SINR/i, unit: 'dB',
    ranAvg: (c) => c.sinrAvg || null, ranP10: () => null },
  { id: 'cqi', pattern: /CQI/i, unit: '',
    ranAvg: (c) => c.cqiAvg || null, ranP10: () => null },
  // 32 侧没有 RSRQ 字段：只并列 CCA 侧原值，RAN 列显示 —
  { id: 'rsrq', pattern: /RSRQ/i, unit: 'dB',
    ranAvg: () => null, ranP10: () => null },
]

/** 某小区的一行行指标对照；两侧都没有的族直接不出现（不留空行） */
function kpiRowsOf(cca: CcaResult | null, cellName: string, ran: RadioCell | null): KpiCompareRow[] {
  const items = ccaKpiItems(cca, cellName)
  const out: KpiCompareRow[] = []
  for (const fam of KPI_FAMILIES) {
    const hit = items.filter((it) => fam.pattern.test(it.name))
    const ranAvg = ran ? fam.ranAvg(ran) : null
    if (!hit.length && ranAvg === null) continue
    out.push({
      id: fam.id,
      cca: hit,
      ranSamples: ran ? ran.samples : 0,
      ranAvg,
      ranP10: ran ? fam.ranP10(ran) : null,
      unit: fam.unit,
    })
  }
  return out
}

/* ---------------------------------------------------------------------------
 * 主入口
 * ------------------------------------------------------------------------ */

export function buildCellCrossCheck(
  input: { radio: RadioAnalysis | null; cca: CcaResult | null },
): CellCrossCheck {
  const { radio, cca } = input

  // RAN 侧驻留小区：有效采样 > 0 才算「用户驻留过」；按有效采样降序，首个即主驻留。
  // 多小区（用户在小区间移动）不合并成一句结论，整份列表都保留给界面展示。
  const ranServed = [...(radio?.cells ?? [])]
    .filter((c) => c.samples > 0)
    .sort((a, b) => b.samples - a.samples)
  const primary = ranServed[0] ?? null
  const hasRan = !!radio && radio.samples > 0 && ranServed.length > 0

  // CCA 侧两种小区来源：根因指向（强证据）优先，没有才退回驻留列表
  const flagged = ccaFlaggedCells(cca)
  const ccaServed = ccaServedCells(cca)
  const basis: CrossBasis = flagged.length ? 'cause' : ccaServed.length ? 'userTrack' : null
  const candidates = basis === 'cause' ? flagged : ccaServed

  // 归一后精确比较（同名但大小写/空格不同的仍算同一个小区）
  const ranByName = new Map<string, RadioCell>()
  for (const c of ranServed) {
    const key = normCell(c.cell)
    if (key && !ranByName.has(key)) ranByName.set(key, c)
  }
  const matched: string[] = []
  const matchedKeys = new Set<string>()
  for (const name of candidates) {
    const key = normCell(name)
    if (!key || matchedKeys.has(key) || !ranByName.has(key)) continue
    matchedKeys.add(key)
    matched.push(name)
  }
  const matchedRanOf = (name: string): RadioCell | null => ranByName.get(normCell(name)) ?? null

  // —— 判定：无数据绝不落成「正常」 ——
  const verdict: CrossVerdict = !hasRan ? 'unknown'
    : basis === null ? 'unknown'
    : matched.length ? 'match' : 'mismatch'
  const reason: CrossReason = verdict !== 'unknown' ? null : hasRan ? 'noCca' : 'noRan'

  // —— 一句话判定（参数全为数据或已翻译文案，规则层不拼语言相关分隔符） ——
  let headline: I18nText
  if (verdict === 'unknown') {
    headline = reason === 'noRan'
      ? tx('vmaxq.ws.cross.unknown.noRan')
      : tx('vmaxq.ws.cross.unknown.noCca')
  } else if (verdict === 'mismatch') {
    headline = basis === 'cause'
      ? tx('vmaxq.ws.cross.mismatch', {
          cell: primary?.cell ?? '—', n: primary?.samples ?? 0, cca: joinCells(flagged),
        })
      : tx('vmaxq.ws.cross.mismatchTrack', {
          cell: primary?.cell ?? '—', n: primary?.samples ?? 0, cca: joinCells(ccaServed),
        })
  } else {
    const primaryMatch = !!primary && matched.some((m) => normCell(m) === normCell(primary.cell))
    const firstHitRan = matchedRanOf(matched[0])
    if (basis === 'userTrack') {
      // 用命中的那个小区（不一定是主驻留）：CCA 驻留列表可能只覆盖用户的次驻留
      // 小区，写成主驻留会把「两侧都记录 CellB」错说成「都记录 CellA」。
      headline = tx('vmaxq.ws.cross.match.track', {
        cell: matched[0], n: firstHitRan?.samples ?? 0,
      })
    } else if (primaryMatch && primary) {
      headline = tx('vmaxq.ws.cross.match.primary', { cell: primary.cell, n: primary.samples })
    } else {
      headline = tx('vmaxq.ws.cross.match.other', {
        cell: matched[0],
        n: firstHitRan?.samples ?? 0,
        primary: primary?.cell ?? '—',
        m: primary?.samples ?? 0,
      })
    }
  }

  // —— KPI 并列对照：命中小区 / 32 主驻留 / CCA 首个指出小区，最多 3 个 ——
  const targets: string[] = []
  const pushTarget = (name: string | null | undefined) => {
    if (!name) return
    const key = normCell(name)
    if (!key || targets.some((t) => normCell(t) === key)) return
    targets.push(name)
  }
  matched.forEach(pushTarget)
  pushTarget(primary?.cell)
  pushTarget(flagged[0])
  const cellKpis: CrossCellKpi[] = targets.slice(0, 3).map((name) => {
    const ran = matchedRanOf(name)
    return {
      cell: name,
      isRanPrimary: !!primary && normCell(primary.cell) === normCell(name),
      ran,
      rows: kpiRowsOf(cca, name, ran),
    }
  })

  const refs: EvidenceRef[] = []
  if (hasRan) refs.push({ kind: 'records', sourceLabel: '32' })
  if (basis !== null) refs.push({ kind: 'cca', sourceLabel: 'CCA' })

  return {
    verdict, reason, basis,
    ranPrimary: primary?.cell ?? null,
    ranServed, ccaFlagged: flagged, ccaServed, matched,
    headline, cellKpis, refs,
  }
}
