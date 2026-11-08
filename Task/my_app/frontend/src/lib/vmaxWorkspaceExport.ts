/* ============================================================================
 * vmaxWorkspaceExport.ts —— VMAX 诊断导出（Excel / PDF）共享模块
 * ============================================================================
 * 2026-11-07 从 VmaxUserQuery.tsx 内联导出逻辑抽出（P0-1）：新工作台
 * VmaxUserCca 的导出按钮此前是 `() => undefined` 死按钮；抽到这里后
 * 新旧两页共用同一份工单摘要，内容不再分叉。
 *
 * 工作台比旧页多两张表（链路状态 / 根因排行）—— 由调用方决定是否传
 * chain / rankedCauses，不传则与旧页导出完全一致（4 张表）。
 *
 * 既有注释保留（原文出处 VmaxUserQuery.tsx 2026-10-31 版）：
 *   - 导出文件是给外国同事/工单系统看的，标签与值区都跟随当前界面语言；
 *   - PDF 不引第三方库：body class + @media print 走浏览器打印。
 * ========================================================================== */

import { renderI18n, renderI18nList } from '../renderI18n'
import { stripBold } from '../utils/richText'
import { exportReport, type ReportSheetSpec } from '../utils/excelReport'
import type { OverrideInfo } from '../components/VmaxDiagnosisCard'
import type { FlowData } from '../components/VmaxFlowCategoryTabs'
import { CHAIN_NODE_KEY, type ChainStatus, type RankedCause } from './vmaxWorkspaceRules'
import { CROSS_KPI_COL_KEY, CROSS_VERDICT_KEY, type CellCrossCheck } from './vmaxCellCrossCheck'
import { parseVerdictSnapshot, snapshotSummary } from './vmaxVerdictSnapshot'
import {
  sourceLabel, type ComplaintKey, type DimensionScore, type SourceResult,
  type TimelineRow, type Verdict, type VoiceResult,
} from '../pages/vmaxDiagnosisRules'

export type TFunc = (key: string, params?: Record<string, string | number>) => string

export type VmaxExportInput = {
  msisdn: string
  win: { start: string; end: string }
  complaint: ComplaintKey
  verdict: Verdict | null
  override: OverrideInfo | null
  scores: DimensionScore[]
  sources: SourceResult[]
  timeline: TimelineRow[]
  voice: VoiceResult | null
  flowXdr: FlowData | null
  /** 工作台专属：链路状态与根因排行（旧页不传 → 导出与旧版一致） */
  chain?: ChainStatus[]
  rankedCauses?: RankedCause[]
  /**
   * 工作台专属（P3-2b）：小区交叉验证（CCA 根因/驻留小区 × RAN 32 实际驻留）。
   * **可选** —— 旧页 VmaxUserQuery 不传，导出仍与旧版完全一致（不出现空表/空行）。
   */
  crossCheck?: CellCrossCheck | null
}

/* ---------------------------------------------------------------------------
 * 小区交叉验证工作表（P3-2b，纯组装，可单测）
 * ------------------------------------------------------------------------ *
 * 内容分两块，放在同一张工作表里（不拆第二张 sheet）：
 *   ① 判定事实（项目/值 两列）：判定 / 无法判定原因 / 一句话判定 /
 *      32 主驻留小区与采样数 / 两侧驻留列表 / 命中小区；
 *   ② KPI 并列对照（6 列）：小区 / 指标 / CCA KPI 名称 / CCA 值 /
 *      RAN(32) 均值 / RAN(32) P10。
 * 为什么放同一张：工单是「一个判据一张表」给人整段贴的，判定与它的 KPI
 * 依据分到两张 sheet，接收方还得自己对读；同 sheet 用空行 + 小节标题隔开即可。
 * 数据全部来自 CellCrossCheck（lib/vmaxCellCrossCheck.ts），本层不重算口径、
 * 不判阈值、不改结论；无采样一律「—」，数字保持 number（不写成文本）。
 * ------------------------------------------------------------------------ */

/** CCA KPI 原值可能是数字串（如 "-88" / "3.5"）也可能是文本（如 "12.33%"）：
 *  数字串转 number（Excel 里可排序/求和），文本原样保留。 */
function kpiValueCell(v: string | null): string | number {
  if (v === null) return '—'
  const n = Number(v)
  return v.trim() !== '' && Number.isFinite(n) ? n : v
}

/**
 * 把交叉验证结果组装成 0 或 1 张工作表。
 *
 * `crossCheck` 未传（旧页）/ 为 null 时返回 `[]` —— 调用方展开后导出内容与
 * 旧版完全一致（不出现空表、空行）。工作台传了才追加一张「小区交叉验证」。
 */
export function crossCheckSheets(
  crossCheck: CellCrossCheck | null | undefined,
  t: TFunc,
  subtitle: string,
): ReportSheetSpec[] {
  if (!crossCheck) return []
  const cc = crossCheck
  const primary = cc.ranServed[0] ?? null
  const reasonKey = cc.reason === 'noRan' ? 'vmaxq.ws.cross.reason.noRan'
    : cc.reason === 'noCca' ? 'vmaxq.ws.cross.reason.noCca' : null

  const rows: (string | number)[][] = [
    [t('vmaxq.ws.cross.exp.verdict'), t(CROSS_VERDICT_KEY[cc.verdict])],
    [t('vmaxq.ws.cross.exp.reason'), reasonKey ? t(reasonKey) : '—'],
    // 一句话判定带 **强调** 标记，导出是纯文本 → stripBold（星号不能进工单）
    [t('vmaxq.ws.cross.exp.summary'), stripBold(renderI18n(t, cc.headline))],
    [t('vmaxq.ws.cross.exp.ranPrimary'), cc.ranPrimary ?? '—'],
    [t('vmaxq.ws.cross.exp.ranSamples'), primary ? primary.samples : '—'],
    [t('vmaxq.ws.cross.exp.ranServedList'),
      cc.ranServed.length ? cc.ranServed.map((c) => `${c.cell} (${c.samples})`).join(' / ') : '—'],
    [t('vmaxq.ws.cross.exp.ccaFlagged'),
      cc.ccaFlagged.length ? cc.ccaFlagged.join(' / ') : '—'],
    [t('vmaxq.ws.cross.exp.ccaServedList'),
      cc.ccaServed.length ? cc.ccaServed.join(' / ') : '—'],
    [t('vmaxq.ws.cross.exp.matched'), cc.matched.length ? cc.matched.join(' / ') : '—'],
  ]

  // ② KPI 对照块：空行 + 小节标题 + 子表头 + 每（小区 × 指标 × CCA 条目）一行。
  //    CCA 同一指标有多条（如 UL SINR / DL SSB-SINR）时逐条展开，避免多值挤一格。
  if (cc.cellKpis.some((c) => c.rows.length)) {
    rows.push(['', '', '', '', '', ''])
    rows.push([t('vmaxq.ws.cross.kpi.title'), '', '', '', '', ''])
    rows.push([
      t(CROSS_KPI_COL_KEY.cell), t(CROSS_KPI_COL_KEY.metric),
      t('vmaxq.ws.cross.exp.ccaName'), t('vmaxq.ws.cross.exp.ccaValue'),
      t(CROSS_KPI_COL_KEY.ran), t('vmaxq.ws.cross.exp.ranP10'),
    ])
    for (const entry of cc.cellKpis) {
      const cellLabel = entry.isRanPrimary
        ? `${entry.cell} (${t(CROSS_KPI_COL_KEY.primaryTag)})`
        : entry.cell
      for (const row of entry.rows) {
        const ranAvg = row.ranAvg === null ? '—' : row.ranAvg
        const ranP10 = row.ranP10 === null ? '—' : row.ranP10
        if (!row.cca.length) {
          // 只有 32 侧采样、CCA 没有该指标：两侧对照仍留下空位（不编造 CCA 值）
          rows.push([cellLabel, row.id.toUpperCase(), '—', '—', ranAvg, ranP10])
          continue
        }
        for (const item of row.cca) {
          rows.push([
            cellLabel, row.id.toUpperCase(), item.name,
            kpiValueCell(item.value), ranAvg, ranP10,
          ])
        }
      }
    }
  }

  return [{
    name: t('vmaxq.ws.cross.exp.sheet'),
    title: t('vmaxq.ws.cross.title'),
    subtitle,
    header: [t('vmaxq.ws.cross.exp.item'), t('vmaxq.ws.cross.exp.value')],
    rows,
    // 判定块两列、KPI 块六列 —— 列宽按六列给；数字列右对齐（3/4/5 为 KPI 数值列）
    columnWidths: [30, 24, 24, 14, 16, 16],
    numericCols: [3, 4, 5],
    // 混合两张表，且首行表头只有两列 → 不挂自动筛选（筛选对该结构无意义）
    autoFilter: false,
  }]
}

/* ---------------------------------------------------------------------------
 * Excel：多表工单摘要
 * ------------------------------------------------------------------------ */
export async function exportVmaxDiagnosisExcel(input: VmaxExportInput, t: TFunc): Promise<void> {
  const { msisdn, win, complaint, verdict, override, scores, sources, timeline,
    voice, flowXdr, chain, rankedCauses, crossCheck } = input
  if (!verdict) return
  const cc = t(`vmaxq.complaint.${complaint}`)
  const masked = `****${msisdn.slice(-4)}`

  const verdictRows: (string | number)[][] = [
    ['MSISDN', masked],
    [t('vmaxq.diag.window'), `${win.start} ~ ${win.end}`],
    [t('vmaxq.print.complaint'), cc],
    [t('vmaxq.diag.verdictAuto'), renderI18n(t, verdict.headline)],
    [t('vmaxq.diag.confidence'), t(`vmaxq.diag.confidence.${verdict.confidence}`)],
    [verdict.reproduced ? t('vmaxq.diag.reproduced') : t('vmaxq.diag.notReproduced'), ''],
    [t('vmaxq.diag.verdictManual'), override?.verdict_manual || '—'],
    [t('vmaxq.override.reason'), override?.reason || '—'],
    [t('vmaxq.diag.overridden'), override
      ? `${override.username} @ ${override.created_at.replace('T', ' ').slice(0, 16)}`
      : '—'],
    // P3-3：覆写记录随附的诊断快照摘要（完整 JSON 在库里，导出只附一行）
    [t('vmaxq.override.snapshot'),
      snapshotSummary(parseVerdictSnapshot(override?.verdict_snapshot), t) || '—'],
    [t('vmaxq.print.generated'), new Date().toLocaleString()],
    ['—', '—'],
    [t('vmaxq.diag.basis'), renderI18nList(t, verdict.basis).join(' | ')],
    [t('vmaxq.diag.suggestion'), renderI18n(t, verdict.suggestion)],
    ['—', '—'],
    [t('vmaxq.diag.score.availability'), scores.find((s) => s.key === 'availability')?.score ?? 'N/A'],
    [t('vmaxq.diag.score.latency'), scores.find((s) => s.key === 'latency')?.score ?? 'N/A'],
    [t('vmaxq.diag.score.transport'), scores.find((s) => s.key === 'transport')?.score ?? 'N/A'],
    [t('vmaxq.diag.score.radio'), scores.find((s) => s.key === 'radio')?.score ?? 'N/A'],
    ['—', '—'],
    ...sources.map((s) => [
      sourceLabel(t, s),
      s.ok
        ? t('vmaxq.diag.sourceOk', { n: s.rows.length }) + (s.truncated ? ' *' : '')
        // 导出表里就是「原因: 说明」，不需要「数据源（原因）」那种括号包裹，
        // 所以不复用 vmaxq.diag.failItem，直接拼一个不带括号的版本。
        : `${t('vmaxq.diag.sourceFail')}: ${s.error || ''}`.trim(),
    ] as (string | number)[]),
  ]

  const tlHeader = [
    t('vmaxq.print.tl.minute'), t('vmaxq.print.tl.traffic'), t('vmaxq.print.tl.latency'),
    t('vmaxq.print.tl.transport'), t('vmaxq.print.tl.radio'), t('vmaxq.print.tl.voice'),
    t('vmaxq.print.tl.verdict'),
  ]
  const tlRows = timeline.map((r) => [
    r.minute.slice(11),
    renderI18n(t, r.traffic.text), renderI18n(t, r.latency.text),
    renderI18n(t, r.transport.text), renderI18n(t, r.radio.text),
    renderI18n(t, r.voice.text), renderI18n(t, r.judge),
  ])

  const voiceHeader = [
    t('vmaxq.print.col.time'), t('vmaxq.print.col.iface'), t('vmaxq.print.col.proc'),
    t('vmaxq.print.col.cause'), t('vmaxq.print.col.result'), t('vmaxq.print.col.cell'),
  ]
  const voiceRows = (voice?.steps || []).map((s) => [
    s.time, s.iface, s.proc, s.cause, s.status, s.cell,
  ])

  const appHeader = [
    t('vmaxq.print.col.app'), t('vmaxq.print.col.category'), t('vmaxq.print.col.ul'),
    t('vmaxq.print.col.dl'), t('vmaxq.print.col.total'), t('vmaxq.print.col.share'),
  ]
  const appRows = (flowXdr?.apps || []).map((a) => [
    a.app_name, a.category_label, a.ul_traffic, a.dl_traffic, a.total_traffic, a.ratio,
  ])

  const dash = ['—', '—', '—', '—', '—', '—']
  await exportReport([
    {
      name: t('vmaxq.diag.card'),
      title: t('vmaxq.diag.expVerdictTitle'),
      subtitle: t('vmaxq.diag.expVerdictSub', {
        msisdn: masked, window: `${win.start} ~ ${win.end}`, complaint: cc,
      }),
      header: [t('vmaxq.diag.expItem'), t('vmaxq.diag.expValue')],
      rows: verdictRows,
      columnWidths: [24, 80],
    },
    ...(chain?.length ? [{
      name: t('vmaxq.ws.chain.title'),
      title: t('vmaxq.ws.chain.title'),
      subtitle: `${win.start} ~ ${win.end}`,
      header: [t('vmaxq.ws.chain.node'), t('vmaxq.ws.chain.level')],
      rows: chain.map((c) => [t(CHAIN_NODE_KEY[c.node]), t(`vmaxq.ws.level.${c.level}`)]),
      columnWidths: [24, 16],
    }] : []),
    ...(rankedCauses?.length ? [{
      name: t('vmaxq.ws.exp.causeSheet'),
      title: t('vmaxq.ws.exp.causeTitle'),
      subtitle: t('vmaxq.ws.exp.causeSub', { n: rankedCauses.length }),
      header: [
        t('vmaxq.ws.cause.label'), t('vmaxq.ws.cause.confidence'),
        t('vmaxq.ws.cause.support'), t('vmaxq.ws.exp.causeDims'),
      ],
      rows: rankedCauses.map((r) => [
        r.label, `${r.confidence}%`, `${Math.round(r.crossSupport * 100)}%`,
        r.aligned.map((k) => t(`vmaxq.diag.score.${k}`)).join(', ') || '—',
      ]),
      columnWidths: [36, 12, 12, 28],
    }] : []),
    // P3-2b：小区交叉验证（仅工作台传入；旧页不传 → 不产生这张表）
    ...crossCheckSheets(crossCheck, t, `${win.start} ~ ${win.end}`),
    {
      name: t('vmaxq.tl.card'),
      title: t('vmaxq.diag.expTimelineTitle'),
      subtitle: `${win.start} ~ ${win.end}`,
      header: tlHeader,
      rows: tlRows,
      columnWidths: [8, 16, 16, 14, 22, 20, 28],
    },
    {
      name: t('vmaxq.voice.card'),
      title: t('vmaxq.diag.expVoiceTitle'),
      subtitle: voice
        ? t('vmaxq.diag.expVoiceSub', {
          mode: t(`vmaxq.voice.mode.${voice.mode}`),
          sgs: voice.sgsCount, csfb: voice.csfbTrigger,
          rate: voice.successRate ?? 'N/A',
        })
        : '',
      header: voiceHeader,
      rows: voiceRows.length ? voiceRows : [dash],
      columnWidths: [22, 12, 30, 28, 12, 24],
    },
    {
      name: t('vmaxq.flow.cat.all'),
      title: t('vmaxq.diag.expAppTitle'),
      subtitle: t('vmaxq.diag.expAppSub', {
        total: flowXdr?.total_flux || '—', records: flowXdr?.records || 0,
      }),
      header: appHeader,
      rows: appRows.length ? appRows : [dash],
      columnWidths: [30, 16, 12, 12, 12, 10],
    },
  ], `vmax_diagnosis_${msisdn}_${win.start.slice(0, 10)}.xlsx`)
}

/* ---------------------------------------------------------------------------
 * PDF：body class + @media print（不引第三方库，与旧页同一方案）
 * ------------------------------------------------------------------------ */
export function exportVmaxPrintPdf(): void {
  document.body.classList.add('vmax-print-mode')
  const cleanup = () => {
    document.body.classList.remove('vmax-print-mode')
    window.removeEventListener('afterprint', cleanup)
  }
  window.addEventListener('afterprint', cleanup)
  window.print()
  // 某些浏览器不触发 afterprint（或被用户取消），兜底 1 秒后清掉
  window.setTimeout(cleanup, 1500)
}
