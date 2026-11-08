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
 * 2026-11-07 P3-1 —— 诊断取数改为**渐进渲染**：
 *   优先走 SSE `/api/vmax-diagnosis/stream`：每到一个源就更新 diag，区域 2
 *   的链路与指标随之补齐（不必等 21s 全部到齐）；流不可用（非 200 / 非 SSE /
 *   中断 / 没有 done 帧）时自动回退到原来的 `vmaxDiagnosis()`，行为不变。
 *   结论（verdict）只在 `diagComplete`（四源到齐）之后计算 —— 半份数据先给
 *   「没发现问题」是投诉场景里最危险的误读。
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
import { useI18n } from '../i18n'
import { readSse } from '../lib/sseStream'
import { buildVerdictSnapshot, serializeVerdictSnapshot } from '../lib/vmaxVerdictSnapshot'
import { renderI18n } from '../renderI18n'
import {
  clampRange, rangeToParams, readInitialRange,
  type VmaxRange,
} from './vmaxWindow'
import type { VmaxQuerySnapshot } from './vmaxWindowContext'
import {
  analyzeGame, analyzeOtt, analyzeRadio, analyzeVoice, buildTimeline,
  buildVerdict, isComplaintKey, scoreAll,
  type ComplaintKey, type DiagnosisPayload, type SourceResult,
} from './vmaxDiagnosisRules'

/** 诊断固定四个源（1300 / 1100 / 32 / 1301）—— 渐进渲染的进度分母 */
export const DIAG_SOURCE_TOTAL = 4

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
  // P3-3：覆写提交要把系统判定渲染成字符串（后端 verdict_auto 是 str），
  // 以及生成快照摘要时复用同一份 t()
  const { t } = useI18n()
  const [msisdn, setMsisdn] = useState(() => readInitialMsisdn(ns))
  const [range, setRange] = useState<VmaxRange>(readInitialRange)

  const [diag, setDiag] = useState<DiagnosisPayload | null>(null)
  const [diagLoading, setDiagLoading] = useState(false)
  const [diagError, setDiagError] = useState('')
  /* P3-1 渐进渲染（2026-11-07）：
   *   loadedKeys  —— 已经返回的源（页面上显示「取数 x/4」进度）
   *   diagComplete —— 四源是否全部到齐。**结论只在这之后才算**：四个源串行
   *     ≈21s，半份数据先给「没发现问题」，在投诉场景里是最危险的误读。 */
  const [loadedKeys, setLoadedKeys] = useState<string[]>([])
  const [diagComplete, setDiagComplete] = useState(false)

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
    // P3-1：流式取数被新查询取代时要主动掐断，否则旧流会继续占着上游会话
    const ctrl = new AbortController()
    const qs = `msisdn=${encodeURIComponent(query.msisdn)}`
      + `&start=${encodeURIComponent(start || '')}&end=${encodeURIComponent(end || '')}`

    setDiagLoading(true); setDiagError(''); setSearched(true)
    setDiagComplete(false); setLoadedKeys([])
    setFlowXdr(null); setFlowError(''); setFlowLoading(true)

    /* 流量回退单查：与改造前同一逻辑（拿不到 flow 时才多打一次上游） */
    const loadFlow = async () => {
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

    /* 非流式回退：与改造前**逐行同一套**逻辑（vmaxDiagnosis + flow 复用 + 回退单查）。
     * 触发条件：SSE 端点不可用（非 200 / 非 text/event-stream / 中途中断 / 没有
     * done 帧）。最坏情况下页面行为与 P3-1 改造之前完全一致。 */
    const runNonStream = async () => {
      try {
        const r = await vmaxDiagnosis(query.msisdn, start, end)
        if (seq !== seqRef.current) return
        const data = r.data as DiagnosisPayload
        setDiag(data)
        setDiagComplete(true)
        setLoadedKeys((data.sources || []).map((s) => s.key))
        if (data.flow && (data.flow as FlowData)?.apps) {
          setFlowXdr({ found: true, ...(data.flow as FlowData) })
          setFlowError('')
          setFlowLoading(false)
        } else {
          await loadFlow()
        }
      } catch (e: any) {
        if (seq !== seqRef.current) return
        setDiagError(e?.response?.data?.detail || e?.message || String(e))
        setDiag(null)
        await loadFlow()
      } finally {
        if (seq === seqRef.current) setDiagLoading(false)
      }
    }

    void (async () => {
      /* 渐进渲染主路径：每到一个源就更新 diag（区域 2 的链路/指标逐步补齐），
       * done 到了才置 diagComplete（结论才允许出）。 */
      const streamed: SourceResult[] = []
      let streamFlow: FlowData | null = null
      let streamDone = false
      try {
        await readSse(`/api/vmax-diagnosis/stream?${qs}`, {
          signal: ctrl.signal,
          onEvent: (ev) => {
            if (seq !== seqRef.current) return
            const data = ev.data as any
            if (ev.event === 'source') {
              const src = data as SourceResult
              const i = streamed.findIndex((s) => s.key === src.key)
              if (i >= 0) streamed[i] = src
              else streamed.push(src)
              setDiag({
                window: { start: start || '', end: end || '' },
                imsi: '',
                sources: [...streamed],
              })
              setLoadedKeys(streamed.map((s) => s.key))
            } else if (ev.event === 'flow') {
              // 业务流量比 32 源早到（1300+1301 到齐即可算）
              if (data?.flow && (data.flow as FlowData)?.apps) {
                streamFlow = data.flow as FlowData
                setFlowXdr({ found: true, ...streamFlow })
                setFlowError('')
                setFlowLoading(false)
              }
            } else if (ev.event === 'done') {
              setDiag({
                window: data?.window || { start: start || '', end: end || '' },
                sources: [...streamed],
                imsi: data?.imsi || '',
                flow: streamFlow,
                flow_reused: !!streamFlow,
              })
              // 四源到齐 —— verdict 的 useMemo 依赖它，从这一刻起才出结论
              setDiagComplete(true)
              setDiagLoading(false)
              streamDone = true
            } else if (ev.event === 'error') {
              // 抛给外层 catch → 回退非流式（那里会把错误翻成页面可读文案）
              throw new Error(String(data?.detail || '诊断流内部错误'))
            }
          },
        })
        if (seq !== seqRef.current) return
        if (!streamDone) throw new Error('诊断流未正常结束')
        if (!streamFlow) await loadFlow()
        else setFlowLoading(false)
      } catch (e) {
        if (ctrl.signal.aborted || seq !== seqRef.current) return
        // eslint-disable-next-line no-console
        console.warn('[vmax-diagnosis] 渐进流不可用，回退非流式接口:', e)
        await runNonStream()
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

    // 组件卸载 / 新查询：掐断旧流
    return () => ctrl.abort()
  }, [query?.token])   // eslint-disable-line react-hooks/exhaustive-deps

  const sources = useMemo(() => diag?.sources || [], [diag])
  const scores = useMemo(() => (sources.length ? scoreAll(sources) : []), [sources])
  const voice = useMemo(() => (sources.length ? analyzeVoice(sources) : null), [sources])
  const ott = useMemo(() => (sources.length ? analyzeOtt(sources) : null), [sources])
  const game = useMemo(() => (sources.length ? analyzeGame(sources) : null), [sources])
  const timeline = useMemo(() => (sources.length ? buildTimeline(sources) : []), [sources])
  const radio = useMemo(() => (sources.length ? analyzeRadio(sources) : null), [sources])
  const verdict = useMemo(() => (
    /* P3-1：**必须 diagComplete**。四源串行 ≈21s，先回来的可能只有 1300；
     * 此时 voice/ott/game 已经能从 1300 算出来，若不加这道闸门，页面会先给
     * 一个「没发现问题」的结论，32 到了再翻案 —— 在投诉处理场景里这比慢更糟。 */
    diagComplete && sources.length && voice && ott && game
      ? buildVerdict(complaint, scores, voice, ott, game, sources)
      : null
  ), [diagComplete, complaint, scores, voice, ott, game, sources])

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
    // P3-3：随覆写存一份完整诊断快照（可审计）。快照**只打包既有状态**，
    // 不重算任何口径 —— 否则会出现「快照里的分与页面上的分不一致」。
    const snapshot = buildVerdictSnapshot({
      complaint,
      window: { start: start || '', end: end || '' },
      verdict,
      scores,
      sources,
      voice,
      ott,
      game,
      imsi: diag?.imsi || null,
    })
    setOverrideSaving(true)
    try {
      const r = await fetch('/api/vmax-diagnosis/override', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          msisdn: query.msisdn, start, end,
          // 后端 `verdict_auto` 是字符串：必须送**渲染后的一句话**。
          // 修 P3-3 时发现原实现直接送 `verdict.headline`（{key, params} 对象），
          // pydantic 校验必然 422 —— 覆写其实从未提交成功过；结构化 headline
          // 现在存在 snapshot.verdict.headline 里（审计要的是可复现的结构）。
          verdict_auto: verdict ? renderI18n(t, verdict.headline) : '',
          verdict_manual: v, reason,
          // 入参字段叫 snapshot（后端 OverrideIn.snapshot），落库列是 verdict_snapshot；
          // GET/history 回读的字段名仍是 verdict_snapshot（见 OverrideInfo 类型）。
          snapshot: serializeVerdictSnapshot(snapshot),
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
  }, [query, verdict, complaint, scores, sources, voice, ott, game, diag, t])

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
    /* P3-1 渐进渲染：页面用 loadedKeys/diagTotal 显示「取数 x/4」，
     * diagComplete 表示四源到齐（结论是否可用的唯一判据） */
    diagComplete, loadedKeys, diagTotal: DIAG_SOURCE_TOTAL,
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
