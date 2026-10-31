/* ============================================================================
 * VmaxUserQuery —— VMAX 投诉诊断（CCA 投诉系统）
 * ============================================================================
 *
 * 输入用户号码 + 时间窗 → 后端一次取齐四个源，页面给出**一个诊断结论**。
 *
 * ── 2026-10-31 改版（v2）：从「四个数据源」到「一个诊断结论」 ──────────────
 * 改版前的问题（用户原话：「设计非常混乱，没有一点逻辑性」）：
 *   1. 四个页签是**按数据源切的**（Categorized Traffic / Merged XDR /
 *      XDR Records / 用户概览），不是按**投诉问题**切的。接到「视频卡」，
 *      用户要自己在四个页签之间对时间、还得自己判断哪个现象更有解释力。
 *   2. 分类流量经常为空 —— 因为用的是 CCA 的 DPI 流量（多数用户查不到），
 *      而不是 XDR 用户面话单。
 *   3. 无线质量（RAN 32）**从来查不到**：按号码查，而 `$msisdn` 列全为空
 *      （后端已修：改按 IMSI 查，见 docs/VMAX_DIAGNOSIS_REDESIGN.md §5.1）。
 *
 * 改版后（方案 §4.1）：
 *   第一行：号码 + 时间窗（沿用：整页唯一、默认近 3h、滚动）
 *   第二行：**投诉类型**页签（全部/语音/OTT语音视频/视频/游戏/上网慢）
 *           —— 不是过滤器，而是换一套判据权重，切换秒回不重新取数
 *   第三行：视图页签（诊断结论 / 业务流量 / 连接过程 / 无线质量）
 *           —— 每个页签回答一个问题，不再按数据源命名
 *   诊断结论页：结论条 → 人工覆写 → 四维评分 → 语音/OTT/游戏专卡
 *              → 证据时间线 → 导出 Excel / PDF
 *
 * 取数策略（P0'-3/P0'-4，单账号约束：上游同账号限并发）：
 *   - `vmaxDiagnosis` 先行：一次拿四源原始行 + 后端顺手算好的 `flow`
 *     （诊断与时间线用，单源失败不整页失败；`flow` 复用 1300/1301 行，不再打上游）
 *   - `vmaxFlowXdr` 只作回退/懒加载：诊断没给 flow（失败/旧后端）、
 *     诊断失败、或切到 flow 页签仍为空时才单查一次
 *   - `vmaxCcaQuery`：用户/终端/根因（CCA，用户信息条用；慢，但不挡诊断）
 *   诊断与 CCA 各自独立 loading，谁先回谁先渲染 —— CCA 慢 30s 不会挡住诊断先出结果。
 *   流量默认复用 `diag.flow`，不再与诊断并行打第二遍 1300（省约 12s + 避开上游并发上限）。
 *
 * 时间窗：首屏恒为「当时」的最近 3 小时，不写进 URL（见 vmaxWindow.ts）。
 * ========================================================================== */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, Button, DatePicker, Descriptions, Input, Segmented, Space, Spin, Table, Tag, Typography,
} from 'antd'
import { MobileOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'

import { renderI18n, renderI18nList } from '../renderI18n'
import { useI18n } from '../i18n'
import { CardBase } from '../components/cards'
import DraggableClickModal from '../components/DraggableClickModal'
import VmaxXdrPanel from '../components/VmaxXdrPanel'
import VmaxRadioPanel from '../components/VmaxRadioPanel'
import VmaxCcaCards, {
  type CcaResult, type CauseItem, type CellRecord,
} from '../components/VmaxCcaCards'
import VmaxFlowCategoryTabs, { type FlowData } from '../components/VmaxFlowCategoryTabs'
import VmaxComplaintTabs from '../components/VmaxComplaintTabs'
import VmaxDiagnosisCard, { type OverrideInfo } from '../components/VmaxDiagnosisCard'
import VmaxEvidenceTimeline from '../components/VmaxEvidenceTimeline'
import VmaxVoiceCard from '../components/VmaxVoiceCard'
import VmaxOttCard from '../components/VmaxOttCard'
import VmaxGameCard from '../components/VmaxGameCard'
import VmaxOverrideModal from '../components/VmaxOverrideModal'
import { vmaxCcaQuery, vmaxDiagnosis, vmaxFlowXdr } from '../api'
import { readParam, writeParams } from '../urlState'
import { exportReport } from '../utils/excelReport'
import {
  clampRange, disabledRangeProps, PAGE_RETENTION_HOURS, rangeToParams, readInitialRange,
  type VmaxRange,
} from './vmaxWindow'
import { VmaxWindowContext, type VmaxQuerySnapshot } from './vmaxWindowContext'
import {
  analyzeGame, analyzeOtt, analyzeRadio, analyzeVoice, buildTimeline, buildVerdict,
  isComplaintKey, isDiagViewKey, scoreAll, sourceLabel, type ComplaintKey,
  type DiagnosisPayload, type DiagViewKey,
} from './vmaxDiagnosisRules'

const { Text } = Typography
const { RangePicker } = DatePicker

type KpiItem = { code: string; name: string; value: unknown }
type QueryResult = CcaResult

/** 统一空值展示：— 而不是 undefined / null（AGENTS.md 三.6） */
const fmt = (v: unknown) => (v == null || v === '' || v === '--' ? '—' : String(v))

/** 首屏视图：地址栏里带的视角优先（跳回上次看的页签） */
const readInitialView = (): DiagViewKey => {
  const v = readParam('vmaxView')
  return isDiagViewKey(v) ? v : 'diagnosis'
}

/** 首屏投诉类型：可分享（同一个人常年在处理同一类投诉） */
const readInitialComplaint = (): ComplaintKey => {
  const v = readParam('complaint')
  return v && isComplaintKey(v) ? v : 'all'
}

export default function VmaxUserQuery() {
  const { t } = useI18n()

  const [msisdn, setMsisdn] = useState(() => readParam('msisdn'))
  const [range, setRange] = useState<VmaxRange>(readInitialRange)

  /* ---- 三路取数各自的状态（互不阻塞：任一失败不影响其余）---- */
  const [diag, setDiag] = useState<DiagnosisPayload | null>(null)
  const [diagLoading, setDiagLoading] = useState(false)
  const [diagError, setDiagError] = useState('')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<QueryResult | null>(null)
  const [searched, setSearched] = useState(false)

  const [flowXdr, setFlowXdr] = useState<FlowData | null>(null)
  const [flowError, setFlowError] = useState('')
  const [flowLoading, setFlowLoading] = useState(false)

  const [query, setQuery] = useState<VmaxQuerySnapshot | null>(null)
  const queryTokenRef = useRef(0)

  const [view, setView] = useState<DiagViewKey>(readInitialView)
  const [complaint, setComplaint] = useState<ComplaintKey>(readInitialComplaint)

  /* 四个视图**默认全部挂载**：并行取数要求它们同时在跑；
     切走只 display:none（keep-alive），保住面板里的查询结果。
     条件渲染会在切回时把结果/已选表/分页全部卸载（用户反馈过「数据没了」）。
     这里不写 mounted 开关表：四个页签没有任何一个是「按需挂载」的。 */
  const seqRef = useRef(0)

  // 视角与投诉类型写回地址栏（replaceState，不新增历史记录）
  useEffect(() => {
    writeParams({
      vmaxView: view === 'diagnosis' ? '' : view,
      complaint: complaint === 'all' ? '' : complaint,
    })
  }, [view, complaint])

  /* ---- 弹窗 ---- */
  const [kpiOpen, setKpiOpen] = useState(false)
  const [kpiCell, setKpiCell] = useState<CellRecord | null>(null)
  const [kpiItems, setKpiItems] = useState<KpiItem[]>([])
  const [kpiAnchor, setKpiAnchor] = useState<{ x: number; y: number } | null>(null)
  const [causeOpen, setCauseOpen] = useState(false)
  const [causeItem, setCauseItem] = useState<CauseItem | null>(null)

  /* ---- 人工覆写（按用户隔离；本地表，惰性建表见方案 §4.5）---- */
  const [overrideOpen, setOverrideOpen] = useState(false)
  const [overrideSaving, setOverrideSaving] = useState(false)
  const [override, setOverride] = useState<OverrideInfo | null>(null)

  /* ======================================================================
   * 取数：诊断优先、流量复用/懒加载（P0'-3/P0'-4，单账号约束）
   * ----------------------------------------------------------------------
   * 上游 VMAX 同账号限并发（"The maximum number of connections for the user
   * is reached"），三路并行 = 三个请求抢同一个门户会话，谁都慢。
   * 所以：诊断先行（四源一次取齐，含复用的 flow）；CCA 随后（慢不挡诊断）；
   * 流量默认复用 `diag.flow`，只在诊断没给 flow（失败/旧后端）时才回退
   * 单查 `/api/vmax-flow-xdr`，且切到 flow 页签时仍为空才补查一次。
   * ==================================================================== */
  useEffect(() => {
    if (!query) return
    const seq = ++seqRef.current
    const { start, end } = rangeToParams(query.range)

    // 诊断聚合（四源一次取齐，附带 flow 复用）—— 页面最重要的那路
    setDiagLoading(true); setDiagError(''); setSearched(true)
    // 切新号码先清空旧流量，避免旧号码的流量残留；诊断回来再填
    setFlowXdr(null); setFlowError(''); setFlowLoading(true)
    void (async () => {
      try {
        const r = await vmaxDiagnosis(query.msisdn, start, end)
        if (seq !== seqRef.current) return
        const data = r.data as DiagnosisPayload
        setDiag(data)
        // P0'-1 复用：诊断已顺手算好 flow，不再打第二遍 1300（省 ~12s）
        if (data.flow && (data.flow as FlowData)?.apps) {
          setFlowXdr({ found: true, ...(data.flow as FlowData) })
          setFlowError('')
          setFlowLoading(false)
        } else {
          // 回退：诊断没给 flow（失败/旧后端）才单查一次
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
        // 诊断失败时流量也不复用，直接单查（页面至少能看流量）
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

    // ② CCA（用户/终端/根因）—— 慢，但不挡诊断
    setLoading(true); setError('')
    void (async () => {
      try {
        const r = await vmaxCcaQuery(query.msisdn, start, end)
        if (seq !== seqRef.current) return
        setResult(r.data as QueryResult)
      } catch (e: any) {
        if (seq !== seqRef.current) return
        setError(e?.response?.data?.detail || e?.message || String(e))
        setResult(null)
      } finally {
        if (seq === seqRef.current) setLoading(false)
      }
    })()
  }, [query?.token])   // eslint-disable-line react-hooks/exhaustive-deps

  /* 切到 flow 页签时仍无流量（诊断没给 + 回退也失败）→ 补查一次 */
  useEffect(() => {
    if (view !== 'flow') return
    if (flowXdr || flowLoading || diagLoading) return
    if (!query) return
    const seq = seqRef.current
    const { start, end } = rangeToParams(query.range)
    setFlowLoading(true)
    void (async () => {
      try {
        const f = await vmaxFlowXdr(query.msisdn, start, end)
        if (seq !== seqRef.current) return
        setFlowXdr(f.data as FlowData)
        setFlowError('')
      } catch (e: any) {
        if (seq !== seqRef.current) return
        setFlowError(e?.response?.data?.detail || e?.message || String(e))
      } finally {
        if (seq === seqRef.current) setFlowLoading(false)
      }
    })()
  }, [view, flowXdr, flowLoading, diagLoading, query])   // eslint-disable-line react-hooks/exhaustive-deps

  /* ======================================================================
   * 诊断计算：**纯前端**，切投诉类型不重新取数（方案 §4.2）
   * ==================================================================== */
  const sources = useMemo(() => diag?.sources || [], [diag])
  const scores = useMemo(() => (sources.length ? scoreAll(sources) : []), [sources])
  const voice = useMemo(() => (sources.length ? analyzeVoice(sources) : null), [sources])
  const ott = useMemo(() => (sources.length ? analyzeOtt(sources) : null), [sources])
  const game = useMemo(() => (sources.length ? analyzeGame(sources) : null), [sources])
  const timeline = useMemo(() => (sources.length ? buildTimeline(sources) : []), [sources])
  /* 无线专项：Radio 页签用。与 scoreRadio 同一批采样，保证页签解释得了评分卡 */
  const radio = useMemo(() => (sources.length ? analyzeRadio(sources) : null), [sources])
  const verdict = useMemo(() => (
    sources.length && voice && ott && game
      ? buildVerdict(complaint, scores, voice, ott, game, sources)
      : null
  ), [complaint, scores, voice, ott, game, sources])

  /* 覆写读取：号码 + 窗口变了才重取（用 token 而不是 msisdn，避免输入框打字触发） */
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
        setOverride(null)   // 覆写读不到不影响诊断，静默降级
      }
    })()
  }, [query?.token])   // eslint-disable-line react-hooks/exhaustive-deps

  /* ======================================================================
   * 发起查询
   * ==================================================================== */
  const run = useCallback((raw: string) => {
    const q = raw.trim()
    if (!q) return
    const win = clampRange(range)
    queryTokenRef.current += 1
    // 地址栏不再固定时间：时间窗滚动（总是最新的近 3h），残留的旧值清掉
    writeParams({ msisdn: q, vqStart: '', vqEnd: '' })
    setQuery({ token: queryTokenRef.current, msisdn: q, range: win })
  }, [range])

  const refresh = useCallback(() => {
    if (!query) return
    queryTokenRef.current += 1
    setQuery({ token: queryTokenRef.current, msisdn: query.msisdn, range: query.range })
  }, [query])

  // 首屏恢复：URL 带号码说明这是一次真实执行过的查询，自动重放一次
  const bootRef = useRef(false)
  useEffect(() => {
    if (bootRef.current) return
    bootRef.current = true
    writeParams({ vqStart: '', vqEnd: '' })
    if (!msisdn.trim()) return
    void run(msisdn)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /* ======================================================================
   * 导出：Excel（贴工单）/ PDF（走浏览器打印）
   * ==================================================================== */
  const exportExcel = useCallback(async () => {
    if (!diag || !verdict) return
    const win = diag.window
    const cc = t(`vmaxq.complaint.${complaint}`)
    const masked = query ? `****${query.msisdn.slice(-4)}` : ''

    // 导出文件是给外国同事/工单系统看的，标签与值区**都跟随当前界面语言**。
    // （早期版本把结论句/证据句写成中文字面量，注释里还留着「保持中文」的说法，
    //  那是当时的将就；现在规则层已全部改为 i18n key，译文即等于界面语言。）
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
      ...diag.sources.map((s) => [
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

    // 表头也要走 i18n：这几个数组原来是硬编码英文，中文界面下导出反而全英文。
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
    ], `vmax_diagnosis_${query?.msisdn || ''}_${win.start.slice(0, 10)}.xlsx`)
  }, [diag, verdict, complaint, override, scores, timeline, voice, flowXdr, query, t])

  const exportPdf = useCallback(() => {
    // 不引第三方 PDF 库（前端体积 + 中文字体问题）：
    // 加一个 body class 让 @media print 只留结论/评分/时间线/证据，然后走打印对话框。
    document.body.classList.add('vmax-print-mode')
    const cleanup = () => {
      document.body.classList.remove('vmax-print-mode')
      window.removeEventListener('afterprint', cleanup)
    }
    window.addEventListener('afterprint', cleanup)
    window.print()
    // 某些浏览器不触发 afterprint（或被用户取消），兜底 1 秒后清掉
    window.setTimeout(cleanup, 1500)
  }, [])

  /* ---- 覆写提交 ---- */
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

  /* ---- 小区 KPI 弹窗表列 ---- */
  const kpiColumns = useMemo(() => [
    { title: t('vmaxq.kpiName'), dataIndex: 'name', ellipsis: true },
    { title: t('vmaxq.kpiValue'), dataIndex: 'value', width: 110, align: 'right' as const,
      render: fmt },
    { title: t('vmaxq.kpiCode'), dataIndex: 'code', width: 150, ellipsis: true,
      render: (v: string) => <Text type="secondary" style={{ fontSize: 12 }}>{v}</Text> },
  ], [t])

  const rangePickerProps = disabledRangeProps(PAGE_RETENTION_HOURS)
  const anyData = !!sources.length && sources.some((s) => s.rows.length > 0)

  return (
    <VmaxWindowContext.Provider value={{
      range, setRange, retentionHours: PAGE_RETENTION_HOURS, query,
    }}>
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>

      {/* ① 查询条：号码 + 整页唯一时间窗 */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap>
          <Input
            allowClear
            prefix={<MobileOutlined style={{ color: 'var(--wh-text-dim)' }} />}
            placeholder={t('vmaxq.inputPlaceholder')}
            value={msisdn}
            onChange={e => setMsisdn(e.target.value)}
            onPressEnter={() => void run(msisdn)}
            style={{ width: 240 }}
            maxLength={24}
          />
          <RangePicker
            value={range}
            onChange={(v) => {
              if (v && v[0] && v[1]) setRange(clampRange([v[0], v[1]]))
            }}
            allowClear={false}
            showTime={{ format: 'HH:mm' }}
            format="YYYY-MM-DD HH:mm"
            minuteStep={5}
            {...rangePickerProps}
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            loading={diagLoading || loading}
            onClick={() => void run(msisdn)}
          >
            {t('vmaxq.search')}
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxq.hint')}</Text>
        </Space>
      </CardBase>

      {/* ② 投诉类型页签：换判据权重，不重新取数（方案 §4.2） */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <VmaxComplaintTabs
          value={complaint}
          onChange={setComplaint}
          disabled={!anyData}
        />
      </CardBase>

      {/* ③ 视图页签：每个页签回答一个问题，不再按数据源切 */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap align="center" size="middle">
          <Segmented
            className="wh-seg"
            options={[
              { label: t('vmaxq.tab.diagnosis'), value: 'diagnosis' },
              { label: t('vmaxq.tab.flow'), value: 'flow' },
              { label: t('vmaxq.tab.connect'), value: 'connect' },
              { label: t('vmaxq.tab.radio'), value: 'radio' },
            ]}
            value={view}
            onChange={(v) => setView(v as DiagViewKey)}
            style={{ background: 'var(--wh-seg-bg)' }}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t(`vmaxq.tab.${view}Hint`)}
          </Text>
        </Space>
      </CardBase>

      {/* ================= 诊断结论 ================= */}
      <div style={{
        display: view === 'diagnosis' ? 'flex' : 'none',
        flexDirection: 'column',
        gap: 'var(--wh-space-md)',
      }}>
        {!!diagError && (
          <Alert
            type="error" showIcon message={diagError}
            action={<Button size="small" icon={<ReloadOutlined />} onClick={refresh}>{t('vmaxq.retry')}</Button>}
          />
        )}
        {!searched && !diagLoading && (
          <CardBase>
            <div style={{ textAlign: 'center', padding: 48 }}>
              <MobileOutlined style={{ fontSize: 40, color: 'var(--wh-text-dim)' }} />
              <div style={{ marginTop: 12 }}>
                <Text type="secondary">{t('vmaxq.empty')}</Text>
              </div>
            </div>
          </CardBase>
        )}

        <VmaxDiagnosisCard
          payload={diag}
          scores={scores}
          verdict={verdict}
          complaint={complaint}
          loading={diagLoading}
          error={diagError}
          overrides={override}
          onOverride={() => setOverrideOpen(true)}
          onExportExcel={() => void exportExcel()}
          onExportPdf={exportPdf}
          onRefresh={refresh}
          onGotoView={(v) => setView(v === 'flow' ? 'flow' : v === 'connect' ? 'connect' : 'radio')}
        />

        {!!voice && <VmaxVoiceCard voice={voice} />}
        {!!ott && <VmaxOttCard ott={ott} />}
        {!!game && <VmaxGameCard game={game} />}

        <VmaxEvidenceTimeline rows={timeline} loading={diagLoading} />

        {/* 用户画像 / 终端 / 根因：诊断结论页的最后一屏（辅助信息，不是主判据） */}
        {!!error && (
          <Alert type="error" showIcon message={error}
            action={<Button size="small" icon={<ReloadOutlined />} onClick={refresh}>{t('vmaxq.retry')}</Button>} />
        )}
        {!!result?.failures?.length && (
          <Alert type="warning" showIcon message={t('vmaxq.partialFail')}
            description={result.failures.join('；')} />
        )}
        {!loading && !error && result && !result.found && (
          <Alert type="warning" showIcon
            message={t('vmaxq.notFound', { msisdn: result.msisdn })}
            description={result.msg ? `${t('vmaxq.upstreamMsg')}：${result.msg}` : undefined} />
        )}
        {!loading && !error && result?.found && (
          <VmaxCcaCards
            result={result as CcaResult}
            onOpenKpi={(cell) => {
              setKpiCell(cell)
              setKpiItems(result?.cells?.cell_kpi?.[String(cell.cell)] || [])
              setKpiOpen(true)
            }}
            onOpenCause={(item) => { setCauseItem(item); setCauseOpen(true) }}
          />
        )}
      </div>

      {/* ================= 业务流量 ================= */}
      <div style={{
        display: view === 'flow' ? 'flex' : 'none',
        flexDirection: 'column',
        gap: 'var(--wh-space-md)',
      }}>
        {!!flowError && (
          <Alert type="error" showIcon message={flowError}
            action={<Button size="small" icon={<ReloadOutlined />} onClick={refresh}>{t('vmaxq.retry')}</Button>} />
        )}
        {(diagLoading || flowLoading) && !flowXdr && (
          <CardBase>
            <div style={{ textAlign: 'center', padding: 60 }}>
              <Spin size="large" />
              <div style={{ marginTop: 12 }}>
                <Text type="secondary">{t('vmaxq.diag.loading')}</Text>
              </div>
            </div>
          </CardBase>
        )}
        {/* 空态三段式：告诉用户「别的源有没有数据」（方案 §4.10） */}
        {!diagLoading && !flowLoading && !flowXdr && searched && !flowError && (
          <CardBase>
            <div style={{ textAlign: 'center', padding: 40 }}>
              <MobileOutlined style={{ fontSize: 40, color: 'var(--wh-text-dim)' }} />
              <div style={{ marginTop: 12 }}>
                <Text type="secondary">{t('vmaxq.empty.title')}</Text>
              </div>
              <div style={{ marginTop: 8 }}>
                <Text style={{ fontSize: 12, color: 'var(--wh-textMuted)' }}>
                  · {t('vmaxq.empty.sources')}：{sources
                    .map((s) => t('vmaxq.diag.srcCount', { src: sourceLabel(t, s), n: s.rows.length }))
                    .join(t('vmaxq.listSep'))}
                </Text>
              </div>
              {sources.filter((s) => s.key !== '1300' && s.rows.length > 0).map((s) => (
                <div key={s.key} style={{ marginTop: 2 }}>
                  <Text style={{ fontSize: 12, color: 'var(--wh-textMuted)' }}>
                    · {t('vmaxq.empty.otherHint', { src: sourceLabel(t, s), n: s.rows.length })}
                  </Text>
                </div>
              ))}
              <Space size={6} style={{ marginTop: 10 }} wrap>
                <Button size="small" onClick={() => setView('connect')}>{t('vmaxq.empty.gotoConn')}</Button>
                <Button size="small" onClick={() => setView('radio')}>{t('vmaxq.empty.gotoRadio')}</Button>
              </Space>
            </div>
          </CardBase>
        )}
        {!diagLoading && flowXdr && (
          <CardBase
            title={t('vmaxq.flowCard')}
            extra={flowXdr.source ? <Tag color="cyan">{flowXdr.source}</Tag> : undefined}
          >
            <VmaxFlowCategoryTabs flow={flowXdr} />
          </CardBase>
        )}
      </div>

      {/* ================= 连接过程（合并 XDR 明细） ================= */}
      <div style={{ display: view === 'connect' ? 'block' : 'none' }}>
        <VmaxXdrPanel msisdn={msisdn} />
      </div>

      {/* ================= 无线质量（专项分析 + 原始下钻） =================
          不再直接挂原始分表面板：那个面板要自己选表选时间重新查，
          查出来是几千行原始话单，回答不了「这段时间空口好不好、差在哪个小区」。
          改为吃诊断已取到的 RAN(32) 行做聚合（同一批采样，才和评分卡不矛盾），
          原始下钻折叠在面板底部，需要跨窗口查单条话单时再展开。 */}
      <div style={{
        display: view === 'radio' ? 'flex' : 'none',
        flexDirection: 'column',
        gap: 'var(--wh-space-md)',
      }}>
        <VmaxRadioPanel
          analysis={radio}
          loading={diagLoading}
          msisdn={msisdn}
        />
      </div>

      {/* ================= 弹窗区 ================= */}
      <VmaxOverrideModal
        open={overrideOpen}
        autoVerdict={verdict ? renderI18n(t, verdict.headline) : ''}
        existing={override}
        saving={overrideSaving}
        onCancel={() => setOverrideOpen(false)}
        onSubmit={(v, r) => void submitOverride(v, r)}
        onRevoke={() => void revokeOverride()}
      />

      <DraggableClickModal
        open={kpiOpen}
        title={`${t('vmaxq.kpiTitle')} · ${kpiCell?.cellname || kpiCell?.cellkey || ''}`}
        anchor={kpiAnchor}
        onClose={() => setKpiOpen(false)}
      >
        {kpiItems.length ? (
          <Table
            rowKey={r => r.code}
            columns={kpiColumns}
            dataSource={kpiItems}
            pagination={{ pageSize: 12 }}
            size="small"
            scroll={{ x: 460 }}
          />
        ) : (
          <Text type="secondary">{t('vmaxq.noKpi')}</Text>
        )}
      </DraggableClickModal>

      <DraggableClickModal
        open={causeOpen}
        title={causeItem?.rule_name || t('vmaxq.causesCard')}
        onClose={() => setCauseOpen(false)}
      >
        {causeItem && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 380 }}>
            <Descriptions size="small" bordered column={1} items={[
              { key: 'conf', label: t('vmaxq.cause.confidence'),
                children: <Tag color={causeItem.confidence >= 90 ? 'red' : 'orange'}>
                  {causeItem.confidence}%</Tag> },
              { key: 'obj', label: t('vmaxq.cause.object'),
                children: `${causeItem.object_name}（${causeItem.object_type}）` },
              { key: 'area', label: t('vmaxq.cause.area'),
                children: [causeItem.province, causeItem.city, causeItem.vendor]
                  .filter(Boolean).join(' / ') || '—' },
              { key: 'poor', label: t('vmaxq.cause.poortime'),
                children: fmt(causeItem.poortime) },
            ]} />
            <div>
              <Text strong>{t('vmaxq.cause.description')}</Text>
              <div style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>{causeItem.description}</div>
            </div>
            {causeItem.solution && (
              <div>
                <Text strong>{t('vmaxq.cause.solution')}</Text>
                <div style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>{causeItem.solution}</div>
              </div>
            )}
            {!!causeItem.app_info.length && (
              <div>
                <Text strong>{t('vmaxq.cause.timeline')}</Text>
                <Table
                  style={{ marginTop: 4 }}
                  rowKey={r => r.clttime + r.judge}
                  columns={[
                    { title: t('vmaxq.cause.time'), dataIndex: 'clttime', width: 140 },
                    { title: t('vmaxq.cause.judge'), dataIndex: 'judge' },
                  ]}
                  dataSource={causeItem.app_info}
                  pagination={false}
                  size="small"
                />
              </div>
            )}
          </div>
        )}
      </DraggableClickModal>
    </div>
    </VmaxWindowContext.Provider>
  )
}
