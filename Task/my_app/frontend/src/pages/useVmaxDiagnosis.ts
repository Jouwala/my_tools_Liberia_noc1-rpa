/* ============================================================================
 * useVmaxDiagnosis —— VMAX 取数 + 诊断计算共用 hook（2026-11-07）
 * ----------------------------------------------------------------------------
 * 从 pages/VmaxUserQuery.tsx 158–270 与 292–319 行抽出，只抽取不改逻辑：
 *   - vmaxDiagnosis 先行取四源（含 flow 复用），vmaxFlowXdr 只作回退，
 *     vmaxCcaQuery 并行不挡诊断，seq 守卫防旧响应覆盖；
 *   - scoreAll / analyzeVoice / analyzeOtt / analyzeGame / analyzeRadio /
 *     buildTimeline / buildVerdict 纯前端重算，切投诉不重取；
 *   - 号码/投诉写 URL（replaceState），时间窗滚动不记。
 *
 * 命名空间参数化，支持新页：
 *   ns.msisdnKey    号码参数名（旧页 'msisdn'，新页 'ccaMsisdn'）
 *   ns.complaintKey 投诉参数名（旧页 'complaint'，新页 'ccaComplaint'）
 *   ns.clearKeys    run() 时清理的残留旧参数（旧页清 vqStart/vqEnd）
 *   ns.seedFrom     只读迁移：无本站号码但有此参数时填充输入框（不回写）
 *
 * 旧页 VmaxUserQuery 目前仍内联旧逻辑（未强制迁移），本 hook 供新工作台
 * VmaxUserCca 使用；后续可把旧页也切到同一 hook（行为已对齐）。
 * ========================================================================== */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { vmaxCcaQuery, vmaxDiagnosis, vmaxFlowXdr } from '../api'
import { readParam, writeParams } from '../urlState'
import type { CcaResult } from '../components/VmaxCcaCards'
import type { FlowData } from '../components/VmaxFlowCategoryTabs'
import type { OverrideInfo } from '../components/VmaxDiagnosisCard'
import {
  clampRange, rangeToParams, readInitialRange,
  type VmaxRange,
} from './vmaxWindow'
import type { VmaxQuerySnapshot } from './vmaxWindowContext'
import {
  analyzeGame, analyzeOtt, analyzeRadio, analyzeVoice, buildTimeline,
  buildVerdict, isComplaintKey, scoreAll,
  type ComplaintKey, type DiagnosisPayload,
} from './vmaxDiagnosisRules'

export type VmaxNs = {
  msisdnKey: string
  complaintKey: string
  clearKeys?: string[]
  seedFrom?: string
}

export const LEGACY_NS: VmaxNs = {
  msisdnKey: 'msisdn',
  complaintKey: 'complaint',
  clearKeys: ['vqStart', 'vqEnd'],
}
export const CCA_NS: VmaxNs = {
  msisdnKey: 'ccaMsisdn',
  complaintKey: 'ccaComplaint',
  clearKeys: ['ccaStart', 'ccaEnd'],
  seedFrom: 'msisdn',
}

const readInitialMsisdn = (ns: VmaxNs): string =>
  readParam(ns.msisdnKey) || (ns.seedFrom ? readParam(ns.seedFrom) : '')

const readInitialComplaint = (ns: VmaxNs): ComplaintKey => {
  const v = readParam(ns.complaintKey)
  return v && isComplaintKey(v) ? v : 'all'
}

export function useVmaxDiagnosis(ns: VmaxNs) {
  const [msisdn, setMsisdn] = useState(() => readInitialMsisdn(ns))
  const [range, setRange] = useState<VmaxRange>(readInitialRange)

  const [diag, setDiag] = useState<DiagnosisPayload | null>(null)
  const [diagLoading, setDiagLoading] = useState(false)
  const [diagError, setDiagError] = useState('')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<CcaResult | null>(null)
  const [searched, setSearched] = useState(false)

  const [flowXdr, setFlowXdr] = useState<FlowData | null>(null)
  const [flowError, setFlowError] = useState('')
  const [flowLoading, setFlowLoading] = useState(false)

  const [query, setQuery] = useState<VmaxQuerySnapshot | null>(null)
  const queryTokenRef = useRef(0)

  const [complaint, setComplaint] = useState<ComplaintKey>(() => readInitialComplaint(ns))
  const seqRef = useRef(0)

  const [overrideOpen, setOverrideOpen] = useState(false)
  const [overrideSaving, setOverrideSaving] = useState(false)
  const [override, setOverride] = useState<OverrideInfo | null>(null)

  useEffect(() => {
    writeParams({
      [ns.complaintKey]: complaint === 'all' ? '' : complaint,
    })
  }, [complaint, ns.complaintKey])

  useEffect(() => {
    if (!query) return
    const seq = ++seqRef.current
    const { start, end } = rangeToParams(query.range)

    setDiagLoading(true); setDiagError(''); setSearched(true)
    setFlowXdr(null); setFlowError(''); setFlowLoading(true)
    void (async () => {
      try {
        const r = await vmaxDiagnosis(query.msisdn, start, end)
        if (seq !== seqRef.current) return
        const data = r.data as DiagnosisPayload
        setDiag(data)
        if (data.flow && (data.flow as FlowData)?.apps) {
          setFlowXdr({ found: true, ...(data.flow as FlowData) })
          setFlowError('')
          setFlowLoading(false)
        } else {
          try {
            const f = await vmaxFlowXdr(query.msisdn, start, end)
            if (seq !== seqRef.current) return
            setFlowXdr(f.data as FlowData)
            setFlowError('')
          } catch (e: any) {
            if (seq !== seqRef.current) return
            setFlowXdr(null)
            setFlowError(e?.response?.data?.detail || e?.message || String(e))
          } finally {
            if (seq === seqRef.current) setFlowLoading(false)
          }
        }
      } catch (e: any) {
        if (seq !== seqRef.current) return
        setDiagError(e?.response?.data?.detail || e?.message || String(e))
        setDiag(null)
        try {
          const f = await vmaxFlowXdr(query.msisdn, start, end)
          if (seq !== seqRef.current) return
          setFlowXdr(f.data as FlowData)
          setFlowError('')
        } catch (e2: any) {
          if (seq !== seqRef.current) return
          setFlowXdr(null)
          setFlowError(e2?.response?.data?.detail || e2?.message || String(e2))
        } finally {
          if (seq === seqRef.current) setFlowLoading(false)
        }
      } finally {
        if (seq === seqRef.current) setDiagLoading(false)
      }
    })()

    setLoading(true); setError('')
    void (async () => {
      try {
        const r = await vmaxCcaQuery(query.msisdn, start, end)
        if (seq !== seqRef.current) return
        setResult(r.data as CcaResult)
      } catch (e: any) {
        if (seq !== seqRef.current) return
        setError(e?.response?.data?.detail || e?.message || String(e))
        setResult(null)
      } finally {
        if (seq === seqRef.current) setLoading(false)
      }
    })()
  }, [query?.token])   // eslint-disable-line react-hooks/exhaustive-deps

  const sources = useMemo(() => diag?.sources || [], [diag])
  const scores = useMemo(() => (sources.length ? scoreAll(sources) : []), [sources])
  const voice = useMemo(() => (sources.length ? analyzeVoice(sources) : null), [sources])
  const ott = useMemo(() => (sources.length ? analyzeOtt(sources) : null), [sources])
  const game = useMemo(() => (sources.length ? analyzeGame(sources) : null), [sources])
  const timeline = useMemo(() => (sources.length ? buildTimeline(sources) : []), [sources])
  const radio = useMemo(() => (sources.length ? analyzeRadio(sources) : null), [sources])
  const verdict = useMemo(() => (
    sources.length && voice && ott && game
      ? buildVerdict(complaint, scores, voice, ott, game, sources)
      : null
  ), [complaint, scores, voice, ott, game, sources])

  useEffect(() => {
    if (!query) { setOverride(null); return }
    const { start, end } = rangeToParams(query.range)
    void (async () => {
      try {
        const r = await fetch(
          `/api/vmax-diagnosis/override?msisdn=${encodeURIComponent(query.msisdn)}`
          + `&start=${encodeURIComponent(start || '')}&end=${encodeURIComponent(end || '')}`,
          { credentials: 'same-origin' })
        if (!r.ok) { setOverride(null); return }
        const body = await r.json()
        setOverride(body?.data || null)
      } catch {
        setOverride(null)
      }
    })()
  }, [query?.token])   // eslint-disable-line react-hooks/exhaustive-deps

  const run = useCallback((raw: string) => {
    const q = raw.trim()
    if (!q) return
    const win = clampRange(range)
    queryTokenRef.current += 1
    const clear: Record<string, string> = {}
    ;(ns.clearKeys || []).forEach((k) => { clear[k] = '' })
    writeParams({ [ns.msisdnKey]: q, ...clear })
    setQuery({ token: queryTokenRef.current, msisdn: q, range: win })
  }, [range, ns.msisdnKey, ns.clearKeys])   // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = useCallback(() => {
    if (!query) return
    queryTokenRef.current += 1
    setQuery({ token: queryTokenRef.current, msisdn: query.msisdn, range: query.range })
  }, [query])

  const bootRef = useRef(false)
  useEffect(() => {
    if (bootRef.current) return
    bootRef.current = true
    if (!msisdn.trim()) return
    void run(msisdn)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const submitOverride = useCallback(async (v: string, reason: string) => {
    if (!query) return
    const { start, end } = rangeToParams(query.range)
    setOverrideSaving(true)
    try {
      const r = await fetch('/api/vmax-diagnosis/override', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          msisdn: query.msisdn, start, end,
          verdict_auto: verdict?.headline || '',
          verdict_manual: v, reason,
        }),
      })
      if (r.ok) {
        const body = await r.json()
        setOverride(body?.data || null)
        setOverrideOpen(false)
      }
    } finally {
      setOverrideSaving(false)
    }
  }, [query, verdict])

  const revokeOverride = useCallback(async () => {
    if (!override) return
    setOverrideSaving(true)
    try {
      await fetch(`/api/vmax-diagnosis/override/${override.id}`, {
        method: 'DELETE', credentials: 'same-origin',
      })
      setOverride(null)
      setOverrideOpen(false)
    } finally {
      setOverrideSaving(false)
    }
  }, [override])

  const anyData = !!sources.length && sources.some((s) => s.rows.length > 0)

  return {
    msisdn, setMsisdn, range, setRange,
    diag, diagLoading, diagError,
    loading, error, result, searched,
    flowXdr, flowError, flowLoading,
    query, complaint, setComplaint,
    override, overrideOpen, setOverrideOpen, overrideSaving,
    run, refresh, submitOverride, revokeOverride,
    sources, scores, voice, ott, game, timeline, radio, verdict,
    anyData,
  }
}

export type VmaxDiag = ReturnType<typeof useVmaxDiagnosis>
