/* ============================================================================
 * CR 变更分析 —— 两个下钻弹窗的状态与取数
 * ============================================================================
 *
 * 从 `CrChangeAnalysis.tsx` 拆出（页面 731 行，超出 AGENTS.md 第三节 2 的
 * 单文件 500 行上限）。
 *
 * 页面里有**两套**下钻，它们的行类型不同，故分成两个 hook：
 *   - `useCrStatusDrill` —— 类别 / 状态 / 月份明细：一行 = 一张 CR
 *     （走 `/cr-analysis/drilldown`）
 *   - `useCrFlowDrill`   —— 审批步骤明细：一行 = 一次步骤停留
 *     （走 `/cr-analysis/workflow-drilldown`）
 *
 * 两者都遵循 AGENTS.md 第三节 1b 的铁律：**下钻参数必须与被点卡片的维度
 * 严格一致**。窗口（start/end）由页面传入，过滤维度由调用方给。
 * ========================================================================== */

import { useCallback, useRef, useState } from 'react'
import dayjs from 'dayjs'

import { useI18n } from '../../i18n'
import { getCrAnalysisDrilldown, getCrAnalysisWorkflowDrilldown } from '../../api'
import type { DetailRow, Metric, StepDrillRow, StepKey } from './crTypes'

type Pt = { x: number; y: number } | null
/** 时间窗口：调用方负责格式化，hook 只管透传 */
export type Window = { start: string; end: string }
export type FlowKind = 'arrived' | 'current'

const fmtWindow = (s: string | undefined, e: string | undefined): Window => ({
  start: s || '', end: e || '',
})

/** 空窗口不传参：后端会回落到自己的默认窗口（与概览一致） */
const dropEmpty = (w: Window): Record<string, string> => {
  const out: Record<string, string> = {}
  if (w.start) out.start = w.start
  if (w.end) out.end = w.end
  return out
}

/* ---------------- 类别 / 状态 / 月份明细 ---------------- */

export function useCrStatusDrill(win: Window) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<Pt>(null)
  const [title, setTitle] = useState('')
  const [rows, setRows] = useState<DetailRow[]>([])
  const [total, setTotal] = useState(0)
  const [truncated, setTruncated] = useState(false)
  const [warn, setWarn] = useState('')
  const [loading, setLoading] = useState(false)
  /** 导出文件名用的批次标识（弹窗组件需要） */
  const [metric, setMetric] = useState('')

  /**
   * @param statusKey metric='status' 时必传：后端归一后的大写状态值
   * @param titleStatus 状态展示名（仅用于标题；缺省则直接显示 key）
   */
  const openDrill = useCallback(async (
    m: Metric, category = '', sub = '', month = '',
    at?: Pt, statusKey = '', titleStatus = '',
  ) => {
    setOpen(true)
    setAnchor(at || null)
    setLoading(true)
    setRows([])
    setTotal(0)
    setTruncated(false)
    setWarn('')
    setMetric(m)

    // 标题把下钻维度写清楚，用户才知道这一屏到底是什么
    const parts = [t(`cr.metric.${m}`)]
    if (statusKey) parts.push(titleStatus || statusKey)
    if (category) parts.push(category)
    if (sub) parts.push(sub)
    if (month) parts.push(month)
    setTitle(parts.join(' · '))

    try {
      const params: Record<string, unknown> = { metric: m, ...dropEmpty(win) }
      if (category) params.category = category
      if (sub) params.sub_category = sub
      if (month) params.month = month
      // 空状态那一桶要显式传 ''，故只在 status 批次上设置
      if (m === 'status') params.status = statusKey
      const r = await getCrAnalysisDrilldown(params as any)
      const d = r.data || {}
      setRows(d.rows || [])
      setTotal(d.total ?? (d.rows || []).length)
      setTruncated(!!d.truncated)
      setWarn((d.meta?.warnings || []).join('; '))
    } catch (e: any) {
      setWarn(e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [win, t])

  return {
    open, anchor, title, rows, total, truncated, warn, loading, metric,
    openDrill, close: () => setOpen(false),
  }
}

/* ---------------- 审批步骤明细 ---------------- */

/**
 * 步骤显示名 → i18n key。显式 switch：动态拼 key 会被 `check:i18n` 读成
 * 字面量而报「字典缺失」（AGENTS.md 第三节 1b 第 3 条）。
 * 放模块层是为了成为稳定引用，可直接进 useCallback 依赖。
 */
export function flowStepLabelKey(k: StepKey): string {
  switch (k) {
    case 'created': return 'cr.flow.step.created'
    case 'update': return 'cr.flow.step.update'
    case 'bo_fo': return 'cr.flow.step.bo_fo'
    case 'td': return 'cr.flow.step.td'
    case 'cm': return 'cr.flow.step.cm'
    case 'implement': return 'cr.flow.step.implement'
    case 'feedback': return 'cr.flow.step.feedback'
  }
}

export function useCrFlowDrill(win: Window) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [anchor, setAnchor] = useState<Pt>(null)
  const [title, setTitle] = useState('')
  const [rows, setRows] = useState<StepDrillRow[]>([])
  const [total, setTotal] = useState(0)
  const [truncated, setTruncated] = useState(false)
  const [warn, setWarn] = useState('')
  const [loading, setLoading] = useState(false)
  /** 导出文件名：step_kind */
  const fileKey = useRef('')

  const openDrill = useCallback(async (step: StepKey, kind: FlowKind, at?: Pt) => {
    fileKey.current = `${step}_${kind}`
    setOpen(true)
    setAnchor(at || null)
    setLoading(true)
    setRows([])
    setTotal(0)
    setTruncated(false)
    setWarn('')
    setTitle([
      t(flowStepLabelKey(step)),
      t(kind === 'current' ? 'cr.flow.kind.current' : 'cr.flow.kind.arrived'),
    ].join(' · '))

    try {
      const r = await getCrAnalysisWorkflowDrilldown({
        ...dropEmpty(win), step, kind,
      })
      const d = r.data || {}
      setRows(d.rows || [])
      setTotal(d.total ?? (d.rows || []).length)
      setTruncated(!!d.truncated)
      setWarn((d.meta?.warnings || []).join('; '))
    } catch (e: any) {
      setWarn(e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [win, t])

  return {
    open, anchor, title, rows, total, truncated, warn, loading,
    fileKey: fileKey.current,
    openDrill, close: () => setOpen(false),
  }
}

/** 日期 → 'YYYY-MM-DD'；空值保持空串（交给后端默认窗口） */
export const dayStr = (d: dayjs.Dayjs | null | undefined) =>
  d ? d.format('YYYY-MM-DD') : ''

/** 把页面上的 Dayjs 窗口转成 hook 接受的字符串窗口 */
export const windowOf = (start: dayjs.Dayjs | null, end: dayjs.Dayjs | null): Window =>
  fmtWindow(dayStr(start), dayStr(end))
