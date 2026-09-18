import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Alert, Button, Card, Collapse, Empty, Segmented, Space, Spin, Statistic, Table, Tabs, Tooltip, Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  ReloadOutlined, DownloadOutlined, SyncOutlined, WarningOutlined, InfoCircleOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { getUmeInOverview, syncUmeIn } from '../api'
import { useI18n } from '../i18n'
import { useTheme, WH, darkTooltip, axisLabel, axisLine, splitLine, cardStyle } from '../theme'
import { exportReport } from '../utils/excelReport'
import type { ReportSheetSpec } from '../utils/excelReport'
import DraggableClickModal from '../components/DraggableClickModal'
import { SearchableExportTable } from '../components/SearchableExportTable'

const { Text, Title } = Typography

/* ==================== 类型（与后端 ume_in_kpi_service.load_overview 对齐） ==================== */
type Status = 'good' | 'warning' | 'critical' | 'info' | 'unknown'

interface FailureItem { name: string; name_en?: string; col: string; side: 'system' | 'user'; value: number }

interface SvcRow {
  service: string
  ne?: string
  attempts: number
  success: number
  failed: number
  success_rate: number | null
  system_failed: number
  user_failed: number
  system_fail_rate: number | null
  user_fail_ratio: number | null
  rate_status: Status
  status: Status
  failures: FailureItem[]
}

interface ResSvcRow {
  service: string
  ne?: string
  avg: number | null
  top: number | null
  status: Status
  capacity_kb: number | null
  used_kb: number | null
  free_kb: number | null
}

interface TrendPoint {
  day: string
  attempts: number
  success: number
  failed: number
  success_rate: number | null
  system_failed?: number
  system_fail_rate?: number | null
  avg?: number | null
  top?: number | null
}

interface SuccessKpi {
  key: string
  title_zh: string
  title_en: string
  kind: 'success_rate'
  day: string
  alarm: boolean
  rate_label_zh: string
  rate_label_en: string
  attempts: number
  success: number
  failed: number
  success_rate: number | null
  system_failed: number
  user_failed: number
  system_fail_rate: number | null
  user_fail_ratio: number | null
  status: Status
  rate_status: Status
  failures: FailureItem[]
  extras: { name: string; name_en?: string; value: number }[]
  services: SvcRow[]
  trend: TrendPoint[]
}

interface ResourceKpi {
  key: string
  title_zh: string
  title_en: string
  kind: 'resource'
  day: string
  avg: number | null
  top: number | null
  status: Status
  services: ResSvcRow[]
  trend: TrendPoint[]
}

type AnyKpi = SuccessKpi | ResourceKpi

interface AlertRow {
  level: 'critical' | 'warning' | 'info'
  kpi: string
  kpi_title: string
  /** 英文标题（后端下发；缺失时前端退回 kpi 编码，不显示中文） */
  kpi_title_en?: string
  service: string | null
  metric: string
  metric_en?: string
  /** 'sys_fail_rate' | 'success_rate' | 'resource' */
  metric_code?: string
  /** 'sys_fail_rate' | 'user_side' | 'resource' —— 决定 message 用哪个模板组装 */
  message_code?: string
  value: number | null
  unit: string
  threshold: number
  avg?: number | null
  top?: number | null
  basis?: 'avg' | 'top'
  top_reason?: string
  top_reason_en?: string
  /** 用户侧失败占比（仅 info 级「用户侧为主」提示会带） */
  user_fail_ratio?: number | null
  message: string
}

interface OverviewResp {
  meta: {
    generated_at: string
    source: string
    table: string
    days: string[]
    latest_day: string | null
    total_rows: number
    has_data: boolean
    elapsed_seconds?: number
    thresholds: Record<string, number>
  }
  summary: {
    kpi_count: number
    service_count: number
    healthy: number
    warning: number
    critical: number
    info: number
    alert_count: number
    total_attempts: number
    total_failed: number
    total_system_failed: number
    total_user_failed: number
  }
  kpis: AnyKpi[]
  alerts: AlertRow[]
}

/* ==================== 工具 ==================== */
const num = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined || Number.isNaN(v)
    ? '—'
    : v.toLocaleString(undefined, { maximumFractionDigits: digits })

const pct = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? '—' : `${(v * 100).toFixed(digits)}%`

/** 大数缩写：12.3M / 456.7K */
const compact = (v: number | null | undefined) => {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const a = Math.abs(v)
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`
  return String(v)
}

/** 状态 → 文字色（DOM 层用 CSS 变量） */
const STATUS_COLOR: Record<Status, string> = {
  good: WH.teal,
  warning: WH.sev.Warning,
  critical: WH.sev.Critical,
  info: WH.blue,
  unknown: WH.textDim,
}

/** 下钻表格的通用模糊搜索（对行内全部字段做不区分大小写的包含匹配） */
function filterRows<T extends object>(rows: T[], q: string): T[] {
  const s = q.trim().toLowerCase()
  if (!s) return rows
  return rows.filter(r =>
    Object.values(r as Record<string, unknown>).some(
      v => v !== null && v !== undefined && String(v).toLowerCase().includes(s)))
}

/** 告警「实测值 / 阈值」按单位格式化（ratio 转百分比） */
const alertValueText = (a: AlertRow) =>
  a.unit === 'ratio' ? pct(a.value, 2) : (a.value === null ? '—' : `${a.value}%`)
const alertThresholdText = (a: AlertRow) =>
  a.unit === 'ratio' ? pct(a.threshold, 2) : `${a.threshold}%`

/* ==================== 国际化取值（英文环境优先用后端下发的 *_en，缺失时退回中性值） ==================== */
type TFnEarly = (key: string, params?: Record<string, string | number>) => string

const pick = (en: boolean, zh: string, enVal?: string | null) => (en && enVal ? enVal : zh)

const kpiTitleOf = (k: { title_zh: string; title_en?: string }, en: boolean) =>
  pick(en, k.title_zh, k.title_en)

/** 告警里的 KPI 名：英文环境缺失英文标题时退回 KPI 编码（绝不显示中文） */
const alertKpiLabel = (a: AlertRow, en: boolean) =>
  en ? (a.kpi_title_en || a.kpi) : a.kpi_title

const failReasonOf = (f: { name: string; name_en?: string }, en: boolean) =>
  pick(en, f.name, f.name_en)

/**
 * 告警文案：后端只下发结构化字段（message_code + 数值），这里按 locale 组装。
 * 这样后端不用维护两份文案，前端也不会漏翻。
 */
function alertTexts(a: AlertRow, en: boolean, t: TFnEarly): { metric: string; message: string } {
  const kpi = alertKpiLabel(a, en)
  const metric = pick(en, a.metric, a.metric_en)
  if (!en || !a.message_code) return { metric, message: a.message }
  const p = {
    kpi, service: a.service ?? '', metric,
    value: (a.unit === 'ratio' ? (a.value ?? 0) * 100 : (a.value ?? 0)).toFixed(2),
    thr: (a.unit === 'ratio' ? a.threshold * 100 : a.threshold).toString(),
    avg: a.avg === null || a.avg === undefined ? '—' : String(a.avg),
    top: a.top === null || a.top === undefined ? '—' : String(a.top),
    ratio: ((a.user_fail_ratio ?? 0) * 100).toFixed(1),
    reason: pick(en, a.top_reason ?? '', a.top_reason_en),
  }
  switch (a.message_code) {
    case 'sys_fail_rate':
      return { metric, message: t('uk.alert.msg.sysFail', p) }
    case 'user_side':
      return { metric, message: t('uk.alert.msg.userSide', p) }
    case 'resource':
      return {
        metric,
        message: t(a.basis === 'top' ? 'uk.alert.msg.resTop' : 'uk.alert.msg.resAvg', p),
      }
    default:
      return { metric, message: a.message }
  }
}

/** 下钻用：把两种 KPI 的服务行统一成一个扁平结构（不适用字段留空） */
interface DrillServiceRow {
  service: string
  attempts?: number
  success?: number
  failed?: number
  success_rate?: number | null
  system_failed?: number
  system_fail_rate?: number | null
  user_failed?: number
  avg?: number | null
  top?: number | null
  used_kb?: number | null
  status: Status
}

interface DrillFailRow {
  service: string
  name: string
  name_en?: string
  side: 'system' | 'user'
  value: number
}

interface DrillTrendRow {
  day: string
  attempts: number
  success: number
  failed: number
  success_rate: number | null
  system_failed: number
  system_fail_rate: number | null
  avg: number | null
  top: number | null
}

/* ==================== 下钻目标（全页统一） ====================
 * 页面上每个可下钻的元素都只做一件事：把「下钻目标」写进 state。
 * 弹窗（DrillModal）自己根据 target 反查数据、组装页签与导出，页面无需重复逻辑。 */
type DrillFocus = 'service' | 'fail' | 'trend'

/** 单个 KPI 的下钻：服务明细 / 失败构成 / 多日趋势（或指定某天的当日指标） */
interface KpiDrill {
  kind: 'kpi'
  kpiKey: string
  /** 指定后该 SERVICE 排最前（作为对比参照保留其余） */
  service?: string | null
  /** 指定后「趋势」页签只显示该天，并改名为「当日指标」 */
  day?: string | null
  /** 打开时默认选中的页签 */
  focus?: DrillFocus
  title?: string
  subtitle?: string
  level?: Status
}

/** 跨 KPI 的汇总下钻：概览统计卡用（KPI 项数 / 服务数 / 总业务量 / 总失败 / 系统侧失败 / 用户侧失败 / 告警数） */
type SummaryMetric = 'kpis' | 'services' | 'attempts' | 'failed' | 'system_failed' | 'user_failed' | 'alerts'

interface SummaryDrill {
  kind: 'summary'
  metric: SummaryMetric
  title: string
  subtitle?: string
  level?: Status
}

type DrillTarget = KpiDrill | SummaryDrill

interface DrillState {
  target: DrillTarget
  anchor: { x: number; y: number }
}

/** 汇总下钻的行：既能承载成功率类 KPI 的服务行，也能承载资源类 KPI 的服务行 */
interface SummaryRow {
  kpi: string
  kpi_title: string
  service: string
  attempts?: number
  success?: number
  failed?: number
  success_rate?: number | null
  system_failed?: number
  system_fail_rate?: number | null
  user_failed?: number
  avg?: number | null
  top?: number | null
  status: Status
}

/** 汇总下钻的数据构造（纯函数，便于单测/核对） */
function buildSummaryRows(data: OverviewResp, metric: SummaryMetric, en: boolean): SummaryRow[] {
  const success = data.kpis.filter((k): k is SuccessKpi => k.kind === 'success_rate')
  const res = data.kpis.filter((k): k is ResourceKpi => k.kind === 'resource')

  if (metric === 'kpis') {
    // 一行一个 KPI；资源类 KPI 没有业务量/失败，填 avg/top
    return data.kpis.map(k => (k.kind === 'success_rate'
      ? {
        kpi: k.key, kpi_title: kpiTitleOf(k, en), service: '',
        attempts: k.attempts, success: k.success, failed: k.failed,
        success_rate: k.success_rate, system_failed: k.system_failed,
        system_fail_rate: k.system_fail_rate, user_failed: k.user_failed,
        status: k.status,
      }
      : {
        kpi: k.key, kpi_title: kpiTitleOf(k, en), service: '',
        avg: k.avg, top: k.top, status: k.status,
      }))
  }

  if (metric === 'alerts') return []  // 告警单独渲染，不走 SummaryRow

  /** 「服务数」卡片口径 = 最新一天出现过的**不同 SERVICE 个数**（后端 `len({SERVICE})`），
   *  所以下钻必须按 SERVICE 归并：同一个 SERVICE 可能同时挂在 CPU / Memory 等多个 KPI 下，
   *  不归并会得到 34 行，与卡片上的 16 对不上。 */
  if (metric === 'services') {
    // 取组内「最严重」状态。info 是「参考、不告警」（如 P4M 转化率），语义上比 good 轻，
    // 所以排序是 critical > warning > good > info —— 否则一个 5 个 KPI 都正常、
    // 只有 P4M 是 info 的服务会被显示成「参考」。
    const RANK: Record<Status, number> = { unknown: -1, info: 0, good: 1, warning: 2, critical: 3 }
    const acc = new Map<string, {
      kpis: string[]; titles: string[]
      attempts: number; success: number; failed: number
      system_failed: number; user_failed: number
      avg: number | null; top: number | null
      rank: number; status: Status
    }>()
    const get = (svc: string) => {
      let a = acc.get(svc)
      if (!a) {
        a = {
          kpis: [], titles: [], attempts: 0, success: 0, failed: 0,
          system_failed: 0, user_failed: 0, avg: null, top: null, rank: -1, status: 'unknown',
        }
        acc.set(svc, a)
      }
      return a
    }
    const mark = (a: ReturnType<typeof get>, kpiKey: string, kpiTitle: string, st: Status) => {
      if (!a.kpis.includes(kpiKey)) { a.kpis.push(kpiKey); a.titles.push(kpiTitle) }
      if (RANK[st] > a.rank) { a.rank = RANK[st]; a.status = st }
    }
    for (const k of success) {
      for (const s of k.services) {
        const a = get(s.service ?? '')
        mark(a, k.key, kpiTitleOf(k, en), s.status)
        a.attempts += s.attempts || 0
        a.success += s.success || 0
        a.failed += s.failed || 0
        a.system_failed += s.system_failed || 0
        a.user_failed += s.user_failed || 0
      }
    }
    for (const k of res) {
      for (const s of k.services) {
        const a = get(s.service ?? '')
        mark(a, k.key, kpiTitleOf(k, en), s.status)
        if (s.avg !== null && (a.avg === null || s.avg > a.avg)) a.avg = s.avg
        if (s.top !== null && (a.top === null || s.top > a.top)) a.top = s.top
      }
    }
    return [...acc.entries()]
      .map(([service, a]): SummaryRow => ({
        kpi: a.kpis.join(', '),
        kpi_title: a.titles.join(' / '),
        service,
        // 资源类 KPI 没有业务量/失败 → 留空，避免显示成误导性的 0
        attempts: a.attempts || undefined,
        success: a.attempts ? a.success : undefined,
        failed: a.attempts ? a.failed : undefined,
        success_rate: a.attempts ? a.success / a.attempts : undefined,
        system_failed: a.attempts ? a.system_failed : undefined,
        system_fail_rate: a.attempts ? a.system_failed / a.attempts : undefined,
        user_failed: a.attempts ? a.user_failed : undefined,
        avg: a.avg ?? undefined,
        top: a.top ?? undefined,
        status: a.status,
      }))
      .sort((x, y) => (y.attempts ?? 0) - (x.attempts ?? 0))
  }

  // 其余汇总指标都只存在于成功率类 KPI 的服务行上
  const rows: SummaryRow[] = success.flatMap(k => k.services.map(s => ({
    kpi: k.key, kpi_title: kpiTitleOf(k, en), service: s.service ?? '',
    attempts: s.attempts, success: s.success, failed: s.failed,
    success_rate: s.success_rate, system_failed: s.system_failed,
    system_fail_rate: s.system_fail_rate, user_failed: s.user_failed,
    status: s.status,
  })))
  const key: keyof SummaryRow = metric
  return rows.sort((a, b) => (Number(b[key]) || 0) - (Number(a[key]) || 0))
}

/** 从 ECharts click 事件里取鼠标坐标（拿不到就退回屏幕中心） */
function anchorFromChart(p: unknown): { x: number; y: number } {
  const ev = (p as { event?: { event?: MouseEvent } })?.event?.event
  return {
    x: typeof ev?.clientX === 'number' ? ev.clientX : window.innerWidth / 2,
    y: typeof ev?.clientY === 'number' ? ev.clientY : window.innerHeight / 2,
  }
}

/** 状态徽标配色：浅色主题用深色字 + 淡底，深色主题用亮色字 + 淡底。
 *  ⚠️ 不要用 antd <Tag color="var(--x)">——antd v6 无法解析 CSS 变量，
 *  会回落成默认灰底，再叠加白字就变成「看不见」。这里全部用内联样式。 */
const BADGE_PALETTE: Record<'dark' | 'light', Record<Status, { bg: string; fg: string }>> = {
  dark: {
    good: { bg: 'rgba(0, 217, 255,0.18)', fg: '#00d9ff' },
    warning: { bg: 'rgba(255,212,59,0.18)', fg: '#ffd43b' },
    critical: { bg: 'rgba(255,71,87,0.20)', fg: '#ff8a94' },
    info: { bg: 'rgba(37, 140, 255,0.18)', fg: '#258cff' },
    unknown: { bg: 'rgba(148,163,184,0.18)', fg: '#94a3b8' },
  },
  light: {
    good: { bg: 'rgba(13,148,136,0.14)', fg: '#0d9488' },
    warning: { bg: 'rgba(180,83,9,0.14)', fg: '#b45309' },
    critical: { bg: 'rgba(217,45,32,0.14)', fg: '#d92d20' },
    info: { bg: 'rgba(3,105,161,0.14)', fg: '#0369a1' },
    unknown: { bg: 'rgba(91,114,136,0.14)', fg: '#5b7288' },
  },
}

/** 状态徽标（主题感知、始终可读） */
function StatusBadge({ status, label, isDark }: { status: Status; label: string; isDark: boolean }) {
  const c = BADGE_PALETTE[isDark ? 'dark' : 'light'][status] ?? BADGE_PALETTE.light.unknown
  return (
    <span style={{
      display: 'inline-block', padding: '0 8px', borderRadius: 10, fontSize: 12,
      lineHeight: '20px', whiteSpace: 'nowrap', fontWeight: 600,
      background: c.bg, color: c.fg,
    }}>
      {label}
    </span>
  )
}

/** 失败原因小标签：系统侧高亮，用户侧弱化 */
function Pill({ text, side, isDark }: { text: string; side: 'system' | 'user'; isDark: boolean }) {
  const c = BADGE_PALETTE[isDark ? 'dark' : 'light'][side === 'system' ? 'critical' : 'unknown']
  return (
    <span style={{
      display: 'inline-block', padding: '0 6px', borderRadius: 8, fontSize: 11,
      lineHeight: '18px', whiteSpace: 'nowrap', background: c.bg, color: c.fg,
    }}>
      {text}
    </span>
  )
}

/* ==================== 下钻弹窗的列定义（模块级，页面与弹窗共用） ==================== */
type TFn = (key: string, params?: Record<string, string | number>) => string
type StatusLabelFn = (s: Status) => string

/** 告警表格列：告警卡片与「告警数」汇总下钻共用 */
function buildAlertColumns(
  t: TFn, isDark: boolean, statusLabel: StatusLabelFn, en: boolean,
): ColumnsType<AlertRow> {
  return [
    {
      title: t('uk.col.level'), dataIndex: 'level', width: 90,
      render: (v: string) => <StatusBadge status={v as Status} label={statusLabel(v as Status)} isDark={isDark} />,
    },
    {
      title: t('uk.col.kpi'), dataIndex: 'kpi_title', width: 140,
      render: (_: unknown, r) => (
        <Space direction="vertical" size={0}>
          <Text style={{ color: WH.text }}>{alertKpiLabel(r, en)}</Text>
          <Text style={{ color: WH.textDim, fontSize: 11 }}>{r.kpi}</Text>
        </Space>
      ),
    },
    {
      title: t('uk.col.service'), dataIndex: 'service', width: 210,
      render: (v: string | null) => (v
        ? <Text style={{ color: WH.text }}>{v}</Text>
        : <Text style={{ color: WH.textDim }}>—</Text>),
    },
    {
      title: t('uk.col.metric'), dataIndex: 'metric', width: 130,
      render: (_: unknown, r) => <Text style={{ color: WH.textMuted }}>{alertTexts(r, en, t).metric}</Text>,
    },
    {
      title: t('uk.col.value'), dataIndex: 'value', align: 'right', width: 110,
      render: (_: unknown, r) => (
        <Text strong style={{ color: STATUS_COLOR[r.level as Status] }}>{alertValueText(r)}</Text>
      ),
    },
    {
      title: t('uk.col.threshold'), dataIndex: 'threshold', align: 'right', width: 100,
      render: (_: unknown, r) => <Text style={{ color: WH.textDim }}>{alertThresholdText(r)}</Text>,
    },
    {
      title: t('uk.alerts.message'), dataIndex: 'message',
      render: (_: unknown, r) => (
        <Text style={{ color: WH.textMuted, fontSize: 12 }}>{alertTexts(r, en, t).message}</Text>
      ),
    },
  ]
}

/** KPI 下钻「服务明细」列：按 KPI 类型切换（资源类用 日均/峰值；内存列仅在真有数据时出现） */
function buildDrillServiceColumns(
  isRes: boolean, hasMem: boolean, t: TFn, isDark: boolean, statusLabel: StatusLabelFn,
): ColumnsType<DrillServiceRow> {
  if (isRes) {
    return [
      { title: t('uk.col.service'), dataIndex: 'service', width: 260,
        render: (v: string) => <Text style={{ color: WH.text }}>{v}</Text> },
      { title: t('uk.res.avg'), dataIndex: 'avg', align: 'right', width: 100,
        render: (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${v}%`) },
      { title: t('uk.res.top'), dataIndex: 'top', align: 'right', width: 100,
        render: (v: number | null | undefined) => (
          <Text style={{ color: (v ?? 0) >= 95 ? WH.sev.Critical : WH.textMuted }}>
            {v === null || v === undefined ? '—' : `${v}%`}
          </Text>
        ) },
      ...(hasMem ? [{
        title: t('uk.col.usedMem'), dataIndex: 'used_kb', align: 'right' as const, width: 130,
        render: (v: number | null | undefined) =>
          (v === null || v === undefined ? '—' : `${(v / 1024 / 1024).toFixed(1)} GB`),
      }] : []),
      { title: t('uk.col.status'), dataIndex: 'status', align: 'center', width: 100,
        render: (v: Status) => <StatusBadge status={v} label={statusLabel(v)} isDark={isDark} /> },
    ]
  }
  return [
    { title: t('uk.col.service'), dataIndex: 'service', width: 240,
      render: (v: string) => <Text style={{ color: WH.text }}>{v}</Text> },
    { title: t('uk.col.attempts'), dataIndex: 'attempts', align: 'right', width: 110,
      render: (v?: number) => <Tooltip title={num(v)}><span>{compact(v)}</span></Tooltip> },
    { title: t('uk.col.success'), dataIndex: 'success', align: 'right', width: 110,
      render: (v?: number) => <Tooltip title={num(v)}><span>{compact(v)}</span></Tooltip> },
    { title: t('uk.col.failed'), dataIndex: 'failed', align: 'right', width: 110,
      render: (v?: number) => <Tooltip title={num(v)}><span>{compact(v)}</span></Tooltip> },
    { title: t('uk.col.rate'), dataIndex: 'success_rate', align: 'right', width: 100,
      render: (v: number | null | undefined) => <Text style={{ color: WH.text }}>{pct(v)}</Text> },
    { title: t('uk.col.systemFailed'), dataIndex: 'system_failed', align: 'right', width: 120,
      render: (v?: number) => (
        <Text style={{ color: (v ?? 0) > 0 ? WH.sev.Critical : WH.textMuted }}>{num(v)}</Text>
      ) },
    { title: t('uk.col.sysFailRate'), dataIndex: 'system_fail_rate', align: 'right', width: 130,
      render: (v: number | null | undefined) => (
        <Text style={{ color: (v ?? 0) > 0 ? WH.sev.Critical : WH.textDim }}>{pct(v, 4)}</Text>
      ) },
    { title: t('uk.col.userFailed'), dataIndex: 'user_failed', align: 'right', width: 110,
      render: (v?: number) => <Text style={{ color: WH.textMuted }}>{num(v)}</Text> },
    { title: t('uk.col.status'), dataIndex: 'status', align: 'center', width: 100,
      render: (v: Status) => <StatusBadge status={v} label={statusLabel(v)} isDark={isDark} /> },
  ]
}

function buildDrillFailColumns(t: TFn, isDark: boolean, en: boolean): ColumnsType<DrillFailRow> {
  return [
    { title: t('uk.col.service'), dataIndex: 'service', width: 240,
      render: (v: string) => <Text style={{ color: WH.text }}>{v}</Text> },
    { title: t('uk.fail.reason'), dataIndex: 'name', width: 240,
      render: (_: unknown, r) => <Text style={{ color: WH.text }}>{failReasonOf(r, en)}</Text> },
    { title: t('uk.fail.side'), dataIndex: 'side', width: 110,
      render: (v: 'system' | 'user') => (
        <Pill text={v === 'system' ? t('uk.fail.system') : t('uk.fail.user')} side={v} isDark={isDark} />
      ) },
    { title: t('uk.col.failed'), dataIndex: 'value', align: 'right', width: 130,
      render: (v: number) => <Text style={{ color: WH.text }}>{num(v)}</Text> },
  ]
}

function buildDrillTrendColumns(t: TFn, isDark: boolean, isRes: boolean): ColumnsType<DrillTrendRow> {
  const head: ColumnsType<DrillTrendRow> = [
    { title: t('uk.col.day'), dataIndex: 'day', width: 120,
      render: (v: string) => <Text style={{ color: WH.text }}>{v}</Text> },
  ]
  if (isRes) {
    return [
      ...head,
      { title: t('uk.res.avg'), dataIndex: 'avg', align: 'right', width: 110,
        render: (v: number | null) => <Text style={{ color: WH.text }}>{v === null ? '—' : `${v}%`}</Text> },
      { title: t('uk.res.top'), dataIndex: 'top', align: 'right', width: 110,
        render: (v: number | null) => (
          <Text style={{ color: (v ?? 0) >= 95 ? WH.sev.Critical : WH.textMuted }}>
            {v === null ? '—' : `${v}%`}
          </Text>
        ) },
    ]
  }
  return [
    ...head,
    { title: t('uk.col.attempts'), dataIndex: 'attempts', align: 'right', width: 120,
      render: (v: number) => <Tooltip title={num(v)}><span>{compact(v)}</span></Tooltip> },
    { title: t('uk.col.success'), dataIndex: 'success', align: 'right', width: 120,
      render: (v: number) => <Tooltip title={num(v)}><span>{compact(v)}</span></Tooltip> },
    { title: t('uk.col.failed'), dataIndex: 'failed', align: 'right', width: 120,
      render: (v: number) => <Tooltip title={num(v)}><span>{compact(v)}</span></Tooltip> },
    { title: t('uk.col.rate'), dataIndex: 'success_rate', align: 'right', width: 100,
      render: (v: number | null) => <Text style={{ color: WH.text }}>{pct(v)}</Text> },
    { title: t('uk.col.systemFailed'), dataIndex: 'system_failed', align: 'right', width: 120,
      render: (v: number) => (
        <Text style={{ color: v > 0 ? WH.sev.Critical : WH.textMuted }}>{num(v)}</Text>
      ) },
    { title: t('uk.col.sysFailRate'), dataIndex: 'system_fail_rate', align: 'right', width: 130,
      render: (v: number | null) => (
        <Text style={{ color: (v ?? 0) > 0 ? WH.sev.Critical : WH.textDim }}>{pct(v, 4)}</Text>
      ) },
  ]
}

/** 汇总下钻的列：按行里实际出现的字段动态拼（成功率类 / 资源类 KPI 混排时不出现空列） */
function buildSummaryColumns(
  rows: SummaryRow[], t: TFn, isDark: boolean, statusLabel: StatusLabelFn,
): ColumnsType<SummaryRow> {
  const hasService = rows.some(r => r.service)
  const hasSuccess = rows.some(r => r.attempts !== undefined)
  const hasRes = rows.some(r => r.avg !== undefined || r.top !== undefined)
  const cols: ColumnsType<SummaryRow> = [
    {
      title: t('uk.col.kpi'), dataIndex: 'kpi', width: 150, fixed: 'left',
      render: (v: string, r) => (
        <Space direction="vertical" size={0}>
          <Text style={{ color: WH.text }}>{r.kpi_title}</Text>
          <Text style={{ color: WH.textDim, fontSize: 11 }}>{v}</Text>
        </Space>
      ),
    },
  ]
  if (hasService) {
    cols.push({
      title: t('uk.col.service'), dataIndex: 'service', width: 230,
      render: (v: string) => (v
        ? <Text style={{ color: WH.text }}>{v}</Text>
        : <Text style={{ color: WH.textDim }}>—</Text>),
    })
  }
  if (hasSuccess) {
    cols.push(
      { title: t('uk.col.attempts'), dataIndex: 'attempts', align: 'right', width: 110,
        sorter: (a, b) => (a.attempts ?? 0) - (b.attempts ?? 0),
        render: (v?: number) => <Tooltip title={num(v)}><span>{compact(v)}</span></Tooltip> },
      { title: t('uk.col.failed'), dataIndex: 'failed', align: 'right', width: 110,
        sorter: (a, b) => (a.failed ?? 0) - (b.failed ?? 0),
        render: (v?: number) => <Tooltip title={num(v)}><span>{compact(v)}</span></Tooltip> },
      { title: t('uk.col.rate'), dataIndex: 'success_rate', align: 'right', width: 100,
        sorter: (a, b) => (a.success_rate ?? 0) - (b.success_rate ?? 0),
        render: (v: number | null | undefined) => <Text style={{ color: WH.text }}>{pct(v)}</Text> },
      { title: t('uk.col.systemFailed'), dataIndex: 'system_failed', align: 'right', width: 120,
        sorter: (a, b) => (a.system_failed ?? 0) - (b.system_failed ?? 0),
        render: (v?: number) => (
          <Text style={{ color: (v ?? 0) > 0 ? WH.sev.Critical : WH.textMuted }}>{num(v)}</Text>
        ) },
      { title: t('uk.col.sysFailRate'), dataIndex: 'system_fail_rate', align: 'right', width: 130,
        render: (v: number | null | undefined) => (
          <Text style={{ color: (v ?? 0) > 0 ? WH.sev.Critical : WH.textDim }}>{pct(v, 4)}</Text>
        ) },
      { title: t('uk.col.userFailed'), dataIndex: 'user_failed', align: 'right', width: 120,
        sorter: (a, b) => (a.user_failed ?? 0) - (b.user_failed ?? 0),
        render: (v?: number) => <Text style={{ color: WH.textMuted }}>{num(v)}</Text> },
    )
  }
  if (hasRes) {
    cols.push(
      { title: t('uk.res.avg'), dataIndex: 'avg', align: 'right', width: 100,
        sorter: (a, b) => (a.avg ?? 0) - (b.avg ?? 0),
        render: (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${v}%`) },
      { title: t('uk.res.top'), dataIndex: 'top', align: 'right', width: 100,
        sorter: (a, b) => (a.top ?? 0) - (b.top ?? 0),
        render: (v: number | null | undefined) => (
          <Text style={{ color: (v ?? 0) >= 95 ? WH.sev.Critical : WH.textMuted }}>
            {v === null || v === undefined ? '—' : `${v}%`}
          </Text>
        ) },
    )
  }
  cols.push({
    title: t('uk.col.status'), dataIndex: 'status', align: 'center', width: 96,
    filters: (['good', 'warning', 'critical', 'info'] as Status[]).map(s => ({ text: statusLabel(s), value: s })),
    onFilter: (v, r) => r.status === v,
    render: (v: Status) => <StatusBadge status={v} label={statusLabel(v)} isDark={isDark} />,
  })
  return cols
}

/* ==================== 统一下钻弹窗 ====================
 * 全页所有下钻入口（告警行 / KPI 表单元格 / 两张图表 / 资源表 / 概览统计卡 / 分析提示）
 * 都只是往 state 里写一个 DrillTarget，弹窗自己反查数据、组装页签与导出。
 * 表格用项目统一的 SearchableExportTable（搜索 + 导出 + 分页），弹窗用 DraggableClickModal。 */
function DrillModal({
  data, target, anchor, onClose, onDrill,
}: {
  data: OverviewResp
  target: DrillTarget | null
  anchor: { x: number; y: number } | null
  onClose: () => void
  /** 弹窗内继续下钻：同一个弹窗换内容（沿用当前锚点，不新增弹窗、不做返回栈） */
  onDrill: (target: DrillTarget) => void
}) {
  const { t, locale } = useI18n()
  const en = locale === 'en'
  const { isDark } = useTheme()
  const [tab, setTab] = useState('service')
  const [search, setSearch] = useState('')

  const statusLabel = useCallback((s: Status) => t(`uk.status.${s}` as 'uk.status.good'), [t])

  useEffect(() => {
    if (!target) return
    setSearch('')
    setTab(target.kind === 'kpi' ? (target.focus ?? 'service') : 'all')
  }, [target])

  const kpiKey = target?.kind === 'kpi' ? target.kpiKey : null
  const kpi = useMemo<AnyKpi | null>(
    () => (kpiKey ? data.kpis.find(k => k.key === kpiKey) ?? null : null), [kpiKey, data])

  const targetSvc = target?.kind === 'kpi' ? target.service ?? null : null
  const targetDay = target?.kind === 'kpi' ? target.day ?? null : null

  /** 服务明细：命中 SERVICE 排最前，其余保留作对比参照 */
  const serviceRows = useMemo<DrillServiceRow[]>(() => {
    if (!kpi) return []
    const rows: DrillServiceRow[] = kpi.kind === 'success_rate'
      ? kpi.services.map(s => ({
        service: s.service ?? '',
        attempts: s.attempts, success: s.success, failed: s.failed,
        success_rate: s.success_rate, system_failed: s.system_failed,
        system_fail_rate: s.system_fail_rate, user_failed: s.user_failed,
        status: s.status,
      }))
      : kpi.services.map(s => ({
        service: s.service ?? '', avg: s.avg, top: s.top, used_kb: s.used_kb, status: s.status,
      }))
    if (!targetSvc) return rows
    return [...rows].sort((a, b) => Number(b.service === targetSvc) - Number(a.service === targetSvc))
  }, [kpi, targetSvc])

  /** 失败构成：仅成功率类 KPI 有；已定位 SERVICE 时只看该服务 */
  const failRows = useMemo<DrillFailRow[]>(() => {
    if (!kpi || kpi.kind !== 'success_rate') return []
    const svcs = targetSvc ? kpi.services.filter(s => s.service === targetSvc) : kpi.services
    return svcs
      .flatMap(s => s.failures.map(f => ({
        service: s.service ?? '', name: f.name, name_en: f.name_en,
        side: f.side, value: f.value,
      })))
      .sort((a, b) => b.value - a.value)
  }, [kpi, targetSvc])

  const allTrend = useMemo<DrillTrendRow[]>(() => {
    if (!kpi) return []
    return kpi.trend.map(p => ({
      day: p.day, attempts: p.attempts, success: p.success, failed: p.failed,
      success_rate: p.success_rate ?? null,
      system_failed: p.system_failed ?? 0,
      system_fail_rate: p.system_fail_rate ?? null,
      avg: p.avg ?? null, top: p.top ?? null,
    }))
  }, [kpi])

  /** 指定了某天 → 趋势页签只显示该天（改名「当日指标」）；否则显示完整多日趋势 */
  const trendRows = useMemo(
    () => (targetDay ? allTrend.filter(r => r.day === targetDay) : allTrend), [allTrend, targetDay])

  const summaryRows = useMemo<SummaryRow[]>(
    () => (target?.kind === 'summary' && target.metric !== 'alerts'
      ? buildSummaryRows(data, target.metric, en) : []),
    [target, data, en])

  const shownSvc = useMemo(() => filterRows(serviceRows, search), [serviceRows, search])
  const shownFail = useMemo(() => filterRows(failRows, search), [failRows, search])
  const shownTrend = useMemo(() => filterRows(trendRows, search), [trendRows, search])
  const shownSummary = useMemo(() => filterRows(summaryRows, search), [summaryRows, search])

  const isRes = kpi?.kind === 'resource'
  const hasMem = useMemo(
    () => serviceRows.some(r => r.used_kb !== null && r.used_kb !== undefined), [serviceRows])

  const svcColumns = useMemo(
    () => buildDrillServiceColumns(!!isRes, hasMem, t, isDark, statusLabel),
    [isRes, hasMem, t, isDark, statusLabel])
  const failColumns = useMemo(() => buildDrillFailColumns(t, isDark, en), [t, isDark, en])
  const trendColumns = useMemo(
    () => buildDrillTrendColumns(t, isDark, !!isRes), [t, isDark, isRes])
  const summaryColumns = useMemo(
    () => buildSummaryColumns(summaryRows, t, isDark, statusLabel),
    [summaryRows, t, isDark, statusLabel])
  const alertColumns = useMemo(
    () => buildAlertColumns(t, isDark, statusLabel, en), [t, isDark, statusLabel, en])

  /* ---------- 导出：与当前页签所见一致 ---------- */
  const doExport = useCallback(async (kind: string) => {
    if (!target) return
    const stamp = data.meta.latest_day ?? 'export'
    const kpiName = kpi ? kpiTitleOf(kpi, en) : (target.kind === 'kpi' ? target.kpiKey : 'summary')
    const sub = target.kind === 'kpi' ? target.subtitle : target.subtitle

    if (kind === 'service') {
      await exportReport([{
        name: 'Service Detail', title: `${kpiName} · ${t('uk.drill.tabService')}`, subtitle: sub,
        header: isRes
          ? [t('uk.col.service'), t('uk.res.avg'), t('uk.res.top'),
            ...(hasMem ? [t('uk.col.usedMem')] : []), t('uk.col.status')]
          : [t('uk.col.service'), t('uk.col.attempts'), t('uk.col.success'), t('uk.col.failed'),
            t('uk.col.rate'), t('uk.col.systemFailed'), t('uk.col.sysFailRate'),
            t('uk.col.userFailed'), t('uk.col.status')],
        rows: shownSvc.map(r => (isRes
          ? [r.service, r.avg ?? '', r.top ?? '',
            ...(hasMem
              ? [r.used_kb === null || r.used_kb === undefined ? '' : Number((r.used_kb / 1024 / 1024).toFixed(1))]
              : []),
            statusLabel(r.status)]
          : [r.service, r.attempts ?? '', r.success ?? '', r.failed ?? '',
            r.success_rate === null || r.success_rate === undefined ? '' : Number((r.success_rate * 100).toFixed(4)),
            r.system_failed ?? '',
            r.system_fail_rate === null || r.system_fail_rate === undefined ? '' : Number((r.system_fail_rate * 100).toFixed(6)),
            r.user_failed ?? '', statusLabel(r.status)])),
        numericCols: isRes ? [1, 2, ...(hasMem ? [3] : [])] : [1, 2, 3, 4, 5, 6, 7],
      }], `${kpiKey}_Service_${stamp}`)
      return
    }
    if (kind === 'fail') {
      await exportReport([{
        name: 'Failure Breakdown', title: `${kpiName} · ${t('uk.drill.tabFail')}`, subtitle: sub,
        header: [t('uk.col.service'), t('uk.fail.reason'), t('uk.fail.side'), t('uk.col.failed')],
        rows: shownFail.map(r => [
          r.service, failReasonOf(r, en), r.side === 'system' ? t('uk.fail.system') : t('uk.fail.user'),
          r.value,
        ]),
        numericCols: [3],
      }], `${kpiKey}_Failure_${stamp}`)
      return
    }
    if (kind === 'trend') {
      await exportReport([{
        name: 'Trend',
        title: `${kpiName} · ${targetDay ? `${t('uk.drill.tabDay')} ${targetDay}` : t('uk.drill.tabTrend')}`,
        subtitle: sub,
        header: isRes
          ? [t('uk.col.day'), t('uk.res.avg'), t('uk.res.top')]
          : [t('uk.col.day'), t('uk.col.attempts'), t('uk.col.success'), t('uk.col.failed'),
            t('uk.col.rate'), t('uk.col.systemFailed'), t('uk.col.sysFailRate')],
        rows: shownTrend.map(r => (isRes
          ? [r.day, r.avg ?? '', r.top ?? '']
          : [r.day, r.attempts, r.success, r.failed,
            r.success_rate === null ? '' : Number((r.success_rate * 100).toFixed(4)),
            r.system_failed,
            r.system_fail_rate === null ? '' : Number((r.system_fail_rate * 100).toFixed(6))])),
        numericCols: isRes ? [1, 2] : [1, 2, 3, 4, 5, 6],
      }], `${kpiKey}_Trend_${stamp}`)
      return
    }
    if (kind === 'alerts') {
      await exportReport([{
        name: 'Alerts', title: t('uk.export.alertsTitle'), subtitle: `${t('uk.generatedAt')}: ${data.meta.generated_at}`,
        header: [t('uk.col.level'), t('uk.col.kpi'), t('uk.col.service'), t('uk.col.metric'),
          t('uk.col.value'), t('uk.col.threshold'), t('uk.alerts.message')],
        rows: data.alerts.map(a => [
          statusLabel(a.level as Status), alertKpiLabel(a, en), a.service ?? '',
          alertTexts(a, en, t).metric,
          a.unit === 'ratio' ? Number(((a.value ?? 0) * 100).toFixed(4)) : (a.value ?? ''),
          a.unit === 'ratio' ? Number((a.threshold * 100).toFixed(4)) : a.threshold,
          alertTexts(a, en, t).message,
        ]),
        numericCols: [4, 5],
      }], `Customer_KPI_Alerts_${stamp}`)
      return
    }
    // 汇总下钻
    await exportReport([{
      name: 'Summary', title: target.kind === 'summary' ? target.title : t('uk.table.title'),
      subtitle: sub,
      header: summaryColumns.map(c => String((c as { title?: unknown }).title ?? '')),
      rows: shownSummary.map(r => summaryColumns.map(c => {
        const k = (c as { dataIndex?: keyof SummaryRow }).dataIndex
        if (!k) return ''
        const v = r[k]
        if (v === null || v === undefined) return ''
        if (k === 'status') return statusLabel(v as Status)
        if (k === 'success_rate' || k === 'system_fail_rate') return Number(((v as number) * 100).toFixed(4))
        return v as string | number
      })),
    }], `Customer_KPI_${target.kind === 'summary' ? target.metric : 'summary'}_${stamp}`)
  }, [target, data, kpi, kpiKey, isRes, hasMem, shownSvc, shownFail, shownTrend, shownSummary,
    summaryColumns, targetDay, statusLabel, en, t])

  if (!target) return null

  /* ---------- 标题 ---------- */
  const titleNode = (
    <Space size={8} wrap>
      {target.level && (
        <StatusBadge status={target.level} label={statusLabel(target.level)} isDark={isDark} />
      )}
      <span>
        {target.kind === 'kpi'
          ? target.title ?? t('uk.drill.title', { kpi: kpi ? kpiTitleOf(kpi, en) : target.kpiKey })
          : target.title}
      </span>
      {target.kind === 'kpi' && target.service && (
        <Text style={{ color: WH.textMuted, fontSize: 12 }}>{target.service}</Text>
      )}
      {target.kind === 'kpi' && target.day && (
        <Text style={{ color: WH.textMuted, fontSize: 12 }}>{target.day}</Text>
      )}
      {target.kind === 'summary' && (
        <Text style={{ color: WH.textDim, fontSize: 12 }}>
          {t('common.records', { n: target.metric === 'alerts' ? data.alerts.length : summaryRows.length })}
        </Text>
      )}
    </Space>
  )

  /* ---------- 顶部摘要（告警原文 / KPI 关键指标） ----------
   * 指定了某天时摘要要显示**那一天**的数字，否则会出现「摘要写最新日、页签却是某天」的矛盾。 */
  const headline: string[] = (() => {
    if (!kpi) return []
    if (targetDay) {
      const row = allTrend.find(r => r.day === targetDay)
      if (row) {
        return kpi.kind === 'success_rate'
          ? [
            `${t('uk.col.day')}: ${row.day}`,
            `${t('uk.col.attempts')}: ${num(row.attempts)}`,
            `${t('uk.col.failed')}: ${num(row.failed)}`,
            `${t('uk.col.rate')}: ${pct(row.success_rate)}`,
            `${t('uk.col.systemFailed')}: ${num(row.system_failed)} (${pct(row.system_fail_rate, 4)})`,
          ]
          : [
            `${t('uk.col.day')}: ${row.day}`,
            `${t('uk.res.avg')}: ${row.avg ?? '—'}%`,
            `${t('uk.res.top')}: ${row.top ?? '—'}%`,
          ]
      }
    }
    return kpi.kind === 'success_rate'
      ? [
        `${t('uk.col.attempts')}: ${num(kpi.attempts)}`,
        `${t('uk.col.failed')}: ${num(kpi.failed)}`,
        `${t('uk.col.rate')}: ${pct(kpi.success_rate)}`,
        `${t('uk.col.systemFailed')}: ${num(kpi.system_failed)} (${pct(kpi.system_fail_rate, 4)})`,
        `${t('uk.col.userFailed')}: ${num(kpi.user_failed)}`,
        `${t('uk.latestDay')}: ${kpi.day}`,
      ]
      : [
        `${t('uk.res.avg')}: ${kpi.avg ?? '—'}%`,
        `${t('uk.res.top')}: ${kpi.top ?? '—'}%`,
        `${t('uk.latestDay')}: ${kpi.day}`,
      ]
  })()

  const banner = target.kind === 'kpi' ? (
    <Alert
      type={target.level === 'critical' ? 'error' : (target.level === 'warning' ? 'warning' : 'info')}
      showIcon
      style={{ marginBottom: 'var(--wh-space-sm)' }}
      message={target.subtitle ?? (kpi ? kpiTitleOf(kpi, en) : target.kpiKey)}
      description={
        <Space size={16} wrap>
          {headline.map((s, i) => (
            <Text key={i} style={{ color: WH.textMuted, fontSize: 12 }}>{s}</Text>
          ))}
        </Space>
      }
    />
  ) : (
    <Text style={{ color: WH.textDim, fontSize: 12, display: 'block', marginBottom: 'var(--wh-space-sm)' }}>
      {t('uk.drill.summaryNote')}
    </Text>
  )

  /* ---------- 弹窗内的下钻（点行继续深入，沿用当前锚点） ---------- */
  const rowDrill = (kpiKey2: string, service?: string | null) =>
    onDrill({ kind: 'kpi', kpiKey: kpiKey2, service: service || null, focus: 'service' })

  if (target.kind === 'summary') {
    const isAlertList = target.metric === 'alerts'
    return (
      <DraggableClickModal open anchor={anchor} onClose={onClose} width={1320} title={titleNode}>
        {banner}
        <SearchableExportTable
          data={isAlertList ? data.alerts : shownSummary}
          columns={isAlertList ? alertColumns : summaryColumns}
          search={search}
          onSearchChange={setSearch}
          onExport={() => void doExport(isAlertList ? 'alerts' : 'summary')}
          exportText={t('common.exportExcel')}
          rowKey={(r: SummaryRow | AlertRow, i?: number) =>
            (isAlertList ? `al-${(r as AlertRow).kpi}-${(r as AlertRow).service ?? ''}` : `sm-${(r as SummaryRow).kpi}-${(r as SummaryRow).service}`) + `-${i ?? 0}`}
          ariaLabel={target.title}
          onRow={isAlertList
            ? (r: AlertRow) => {
              const a = r as AlertRow
              return {
                onClick: () => onDrill({
                  kind: 'kpi', kpiKey: a.kpi, service: a.service, focus: 'fail',
                  level: a.level as Status, subtitle: alertTexts(a, en, t).message,
                  title: t('uk.drill.title', { kpi: alertKpiLabel(a, en) }),
                }),
                style: { cursor: 'pointer' },
              }
            }
            : (r: SummaryRow) => {
              const s = r as SummaryRow
              return {
                // 「服务数」下钻的 kpi 列可能是 "CPU, Memory" 这种归并值 → 取第一个 KPI 继续下钻
                onClick: () => rowDrill(s.kpi.split(',')[0].trim(), s.service),
                style: { cursor: 'pointer' },
              }
            }}
        />
      </DraggableClickModal>
    )
  }

  return (
    <DraggableClickModal open anchor={anchor} onClose={onClose} width={1320} title={titleNode}>
      {banner}
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'service',
            label: `${t('uk.drill.tabService')} (${serviceRows.length})`,
            children: (
              <SearchableExportTable
                data={shownSvc}
                columns={svcColumns}
                search={search}
                onSearchChange={setSearch}
                onExport={() => void doExport('service')}
                exportText={t('common.exportExcel')}
                rowKey={(r: DrillServiceRow, i?: number) => `svc-${r.service}-${i ?? 0}`}
                ariaLabel={t('uk.drill.tabService')}
              />
            ),
          },
          ...(failRows.length ? [{
            key: 'fail',
            label: `${t('uk.drill.tabFail')} (${failRows.length})`,
            children: (
              <SearchableExportTable
                data={shownFail}
                columns={failColumns}
                search={search}
                onSearchChange={setSearch}
                onExport={() => void doExport('fail')}
                exportText={t('common.exportExcel')}
                rowKey={(r: DrillFailRow, i?: number) => `fail-${r.service}-${r.name}-${i ?? 0}`}
                ariaLabel={t('uk.drill.tabFail')}
              />
            ),
          }] : []),
          {
            key: 'trend',
            label: targetDay
              ? `${t('uk.drill.tabDay')} (${targetDay})`
              : `${t('uk.drill.tabTrend')} (${allTrend.length})`,
            children: (
              <SearchableExportTable
                data={shownTrend}
                columns={trendColumns}
                search={search}
                onSearchChange={setSearch}
                onExport={() => void doExport('trend')}
                exportText={t('common.exportExcel')}
                rowKey={(r: DrillTrendRow, i?: number) => `trend-${r.day}-${i ?? 0}`}
                ariaLabel={t('uk.drill.tabTrend')}
              />
            ),
          },
        ]}
      />
    </DraggableClickModal>
  )
}

export default function UmeInKpi() {
  const { t, locale } = useI18n()
  const en = locale === 'en'
  const { isDark, palette, colors } = useTheme()

  const [days, setDays] = useState(7)
  const [data, setData] = useState<OverviewResp | null>(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /* 全页统一下钻：drill = 下钻目标 + 点击坐标（弹窗以点击点为中心） */
  const [drill, setDrill] = useState<DrillState | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await getUmeInOverview({ days })
      setData(r.data as OverviewResp)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } }; message?: string })
      setError(msg?.response?.data?.detail || msg?.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => { void load() }, [load])

  const doSync = useCallback(async () => {
    setSyncing(true)
    setError(null)
    try {
      await syncUmeIn({ days_back: days })
      await load()
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } }; message?: string })
      setError(msg?.response?.data?.detail || msg?.message || String(e))
    } finally {
      setSyncing(false)
    }
  }, [days, load])

  const statusLabel = useCallback(
    (s: Status) => t(`uk.status.${s}` as 'uk.status.good'), [t])

  const kpis = data?.kpis ?? []
  const successKpis = useMemo(
    () => kpis.filter((k): k is SuccessKpi => k.kind === 'success_rate'), [kpis])
  const resourceKpis = useMemo(
    () => kpis.filter((k): k is ResourceKpi => k.kind === 'resource'), [kpis])

  /* ==================== 全页统一下钻入口 ====================
   * 每个可下钻的元素只调用 drillTo(target, 点击坐标)，弹窗自己反查数据。
   * 不传 anchor 时沿用当前锚点 —— 这样在弹窗内部继续下钻时弹窗不会跳位。 */
  const drillTo = useCallback((target: DrillTarget, anchor?: { x: number; y: number }) => {
    setDrill(prev => ({
      target,
      anchor: anchor ?? prev?.anchor ?? { x: window.innerWidth / 2, y: window.innerHeight / 2 },
    }))
  }, [])

  const closeDrill = useCallback(() => setDrill(null), [])

  /** 表格单元格下钻：虚线下划线 + tooltip 提示（沿用 RanCellsKpi 的交互约定） */
  const drillCell = (content: ReactNode, target: DrillTarget, tip?: string) => (
    <Tooltip title={tip ?? t('uk.drillHint')}>
      <span
        onClick={(e: { clientX: number; clientY: number }) => drillTo(target, { x: e.clientX, y: e.clientY })}
        style={{ cursor: 'pointer', borderBottom: '1px dashed rgba(128,128,128,0.5)' }}
      >
        {content}
      </span>
    </Tooltip>
  )

  /* ---------- 图表点击下钻：ECharts click params → 统一 DrillTarget ---------- */
  /** 失败率构成图：x 轴就是 KPI key → 直接下钻到该 KPI 的失败构成 */
  const onFailChartClick = useCallback((p: unknown) => {
    const name = (p as { name?: string })?.name
    if (!name) return
    drillTo({ kind: 'kpi', kpiKey: name, focus: 'fail' }, anchorFromChart(p))
  }, [drillTo])

  /** 趋势图：seriesName=KPI、name=日期 → 下钻到「该 KPI 该天」的当日指标 */
  const onTrendChartClick = useCallback((p: unknown) => {
    const { seriesName, name } = (p as { seriesName?: string; name?: string }) ?? {}
    if (!seriesName) return
    drillTo(
      { kind: 'kpi', kpiKey: seriesName, day: name ?? null, focus: 'trend' },
      anchorFromChart(p),
    )
  }, [drillTo])

  /** 资源利用率图：y 轴标签是 `${kpi} · ${service}` → 拆开下钻到该 KPI 的该服务 */
  const onResChartClick = useCallback((p: unknown) => {
    const label = (p as { name?: string })?.name ?? ''
    const idx = label.indexOf(' · ')
    if (idx < 0) return
    drillTo(
      { kind: 'kpi', kpiKey: label.slice(0, idx), service: label.slice(idx + 3), focus: 'service' },
      anchorFromChart(p),
    )
  }, [drillTo])

  /* ---------- 图表 1：失败率构成（系统侧 / 用户侧） ---------- */
  const failChartOption = useMemo(() => {
    const rows = successKpis
      .map(k => {
        const att = k.attempts || 0
        const sysR = att ? (k.system_failed / att) * 100 : 0
        const userR = att ? (k.user_failed / att) * 100 : 0
        return { key: k.key, sysR, userR, sysF: k.system_failed, userF: k.user_failed }
      })
      .filter(r => r.sysR > 0 || r.userR > 0)
    if (!rows.length) return null
    return {
      tooltip: {
        ...darkTooltip(isDark),
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (ps: { name: string; seriesName: string; value: number; marker: string; dataIndex: number }[]) => {
          const r = rows[ps[0].dataIndex]
          const lines = ps.map(p => `${p.marker}${p.seriesName}: ${p.value.toFixed(3)}%`)
          lines.push(`系统侧失败: ${num(r.sysF)} 次`, `用户侧失败: ${num(r.userF)} 次`)
          return `<b>${r.key}</b><br/>${lines.join('<br/>')}`
        },
      },
      legend: { textStyle: { color: palette.textMuted, fontSize: 11 }, top: 0 },
      grid: { left: 8, right: 16, top: 34, bottom: 4, containLabel: true },
      xAxis: {
        type: 'category',
        data: rows.map(r => r.key),
        axisLabel: axisLabel(isDark),
        axisLine: axisLine(isDark),
      },
      yAxis: {
        type: 'value',
        name: t('uk.chart.failRateAxis'),
        nameTextStyle: { color: palette.textDim, fontSize: 11 },
        axisLabel: { ...axisLabel(isDark), formatter: '{value}%' },
        axisLine: axisLine(isDark),
        splitLine: splitLine(isDark),
      },
      series: [
        {
          name: t('uk.fail.system'),
          type: 'bar',
          stack: 'fail',
          barMaxWidth: 42,
          itemStyle: { color: palette.sev.Critical },
          data: rows.map(r => Number(r.sysR.toFixed(4))),
        },
        {
          name: t('uk.fail.user'),
          type: 'bar',
          stack: 'fail',
          barMaxWidth: 42,
          itemStyle: { color: colors[3] },
          data: rows.map(r => Number(r.userR.toFixed(4))),
        },
      ],
    }
  }, [successKpis, isDark, palette, colors, t])

  /* ---------- 图表 2：成功率多日趋势 ---------- */
  const trendChartOption = useMemo(() => {
    const daysArr = data?.meta.days ?? []
    if (!daysArr.length || !successKpis.length) return null
    return {
      tooltip: {
        ...darkTooltip(isDark),
        trigger: 'axis',
        valueFormatter: (v: number) => (v === null ? '—' : `${v}%`),
      },
      legend: { textStyle: { color: palette.textMuted, fontSize: 11 }, top: 0 },
      grid: { left: 8, right: 16, top: 34, bottom: 4, containLabel: true },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: daysArr,
        axisLabel: axisLabel(isDark),
        axisLine: axisLine(isDark),
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        axisLabel: { ...axisLabel(isDark), formatter: '{value}%' },
        axisLine: axisLine(isDark),
        splitLine: splitLine(isDark),
      },
      series: successKpis.map((k, i) => ({
        name: k.key,
        type: 'line',
        smooth: true,
        symbolSize: 6,
        itemStyle: { color: colors[i % colors.length] },
        lineStyle: { width: 2 },
        connectNulls: true,
        data: daysArr.map(d => {
          const p = k.trend.find(x => x.day === d)
          return p?.success_rate === null || p?.success_rate === undefined
            ? null
            : Number((p.success_rate * 100).toFixed(3))
        }),
      })),
    }
  }, [data, successKpis, isDark, palette, colors])

  /* ---------- 图表 3：资源利用率（日均 / 峰值） ---------- */
  const resChartOption = useMemo(() => {
    const rows = resourceKpis.flatMap(k =>
      k.services.map(s => ({ label: `${k.key} · ${s.service}`, avg: s.avg, top: s.top, status: s.status })))
      .filter(r => r.avg !== null || r.top !== null)
      .sort((a, b) => (b.avg ?? 0) - (a.avg ?? 0))
      .slice(0, 16)
      .reverse()
    if (!rows.length) return null
    const thr = data?.meta.thresholds?.res_warn ?? 80
    return {
      tooltip: { ...darkTooltip(isDark), trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { textStyle: { color: palette.textMuted, fontSize: 11 }, top: 0 },
      grid: { left: 8, right: 24, top: 34, bottom: 4, containLabel: true },
      xAxis: {
        type: 'value',
        max: 100,
        axisLabel: { ...axisLabel(isDark), formatter: '{value}%' },
        axisLine: axisLine(isDark),
        splitLine: splitLine(isDark),
      },
      yAxis: {
        type: 'category',
        data: rows.map(r => r.label),
        axisLabel: { ...axisLabel(isDark), fontSize: 10 },
        axisLine: axisLine(isDark),
      },
      series: [
        {
          name: t('uk.res.avg'),
          type: 'bar',
          barMaxWidth: 12,
          itemStyle: {
            color: (p: { dataIndex: number }) =>
              (rows[p.dataIndex].avg ?? 0) >= thr ? palette.sev.Warning : colors[0],
          },
          data: rows.map(r => r.avg ?? 0),
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: { color: palette.sev.Critical, type: 'dashed' },
            label: { formatter: `${t('uk.res.warnLine')} ${thr}%`, color: palette.textMuted, fontSize: 10 },
            data: [{ xAxis: thr }],
          },
        },
        {
          name: t('uk.res.top'),
          type: 'scatter',
          symbolSize: 7,
          itemStyle: { color: palette.sev.Critical },
          data: rows.map((r, i) => [r.top ?? 0, i]),
        },
      ],
    }
  }, [resourceKpis, data, isDark, palette, colors, t])

  /* ---------- 表格：业务 KPI 汇总（行内可展开到 SERVICE；关键单元格可点击下钻） ---------- */
  const successColumns: ColumnsType<SuccessKpi> = [
    {
      title: t('uk.col.kpi'), dataIndex: 'key', width: 150, fixed: 'left',
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          {drillCell(
            <Text strong style={{ color: WH.text }}>{locale === 'en' ? r.title_en : r.title_zh}</Text>,
            { kind: 'kpi', kpiKey: r.key, focus: 'service' },
          )}
          <Text style={{ color: WH.textDim, fontSize: 11 }}>{r.key}</Text>
        </Space>
      ),
    },
    {
      title: t('uk.col.attempts'), dataIndex: 'attempts', align: 'right', width: 110,
      sorter: (a, b) => a.attempts - b.attempts,
      render: (v: number, r) => drillCell(
        compact(v), { kind: 'kpi', kpiKey: r.key, focus: 'service' }, `${num(v)} · ${t('uk.drillHint')}`),
    },
    {
      title: t('uk.col.success'), dataIndex: 'success', align: 'right', width: 110,
      render: (v: number, r) => drillCell(
        compact(v), { kind: 'kpi', kpiKey: r.key, focus: 'service' }, `${num(v)} · ${t('uk.drillHint')}`),
    },
    {
      title: t('uk.col.failed'), dataIndex: 'failed', align: 'right', width: 110,
      sorter: (a, b) => a.failed - b.failed,
      render: (v: number, r) => drillCell(
        compact(v), { kind: 'kpi', kpiKey: r.key, focus: 'fail' }, `${num(v)} · ${t('uk.drillHint')}`),
    },
    {
      title: t('uk.col.rate'), dataIndex: 'success_rate', align: 'right', width: 120,
      sorter: (a, b) => (a.success_rate ?? 0) - (b.success_rate ?? 0),
      render: (v: number | null, r) => drillCell(
        <Space direction="vertical" size={0} style={{ alignItems: 'flex-end' }}>
          <Text strong style={{ color: STATUS_COLOR[r.rate_status] }}>{pct(v)}</Text>
          <Text style={{ color: WH.textDim, fontSize: 10 }}>
            {locale === 'en' ? r.rate_label_en : r.rate_label_zh}
          </Text>
        </Space>,
        { kind: 'kpi', kpiKey: r.key, focus: 'trend' },
      ),
    },
    {
      title: t('uk.col.systemFailed'), dataIndex: 'system_failed', align: 'right', width: 140,
      sorter: (a, b) => a.system_failed - b.system_failed,
      render: (v: number, r) => drillCell(
        <Space direction="vertical" size={0} style={{ alignItems: 'flex-end' }}>
          <Text style={{ color: v > 0 ? WH.sev.Critical : WH.textMuted }}>{num(v)}</Text>
          <Text style={{ color: WH.textDim, fontSize: 10 }}>{pct(r.system_fail_rate, 4)}</Text>
        </Space>,
        { kind: 'kpi', kpiKey: r.key, focus: 'fail' },
      ),
    },
    {
      title: t('uk.col.userFailed'), dataIndex: 'user_failed', align: 'right', width: 130,
      render: (v: number, r) => drillCell(
        <Space direction="vertical" size={0} style={{ alignItems: 'flex-end' }}>
          <Text style={{ color: WH.textMuted }}>{num(v)}</Text>
          <Text style={{ color: WH.textDim, fontSize: 10 }}>
            {r.user_fail_ratio === null ? '—' : `${t('uk.ratio')} ${pct(r.user_fail_ratio, 1)}`}
          </Text>
        </Space>,
        { kind: 'kpi', kpiKey: r.key, focus: 'fail' },
      ),
    },
    {
      title: t('uk.col.status'), dataIndex: 'status', align: 'center', width: 96,
      filters: (['good', 'warning', 'critical', 'info'] as Status[]).map(s => ({ text: statusLabel(s), value: s })),
      onFilter: (v, r) => r.status === v,
      render: (v: Status) => <StatusBadge status={v} label={statusLabel(v)} isDark={isDark} />,
    },
  ]

  /* ---------- 表格：资源利用率（服务/日均/峰值可点击下钻；列工厂需要 KPI key 作上下文） ---------- */
  const buildResColumns = (kpiKey: string): ColumnsType<ResSvcRow> => [
    { title: t('uk.col.service'), dataIndex: 'service', width: 220,
      render: (v: string) => drillCell(
        <Text style={{ color: WH.text }}>{v}</Text>,
        { kind: 'kpi', kpiKey, service: v, focus: 'service' },
      ) },
    {
      title: t('uk.res.avg'), dataIndex: 'avg', align: 'right', width: 100,
      sorter: (a, b) => (a.avg ?? 0) - (b.avg ?? 0),
      render: (v: number | null, r) => drillCell(
        v === null ? '—' : `${v}%`,
        { kind: 'kpi', kpiKey, service: r.service, focus: 'service' },
      ),
    },
    {
      title: t('uk.res.top'), dataIndex: 'top', align: 'right', width: 100,
      render: (v: number | null, r) => drillCell(
        <Text style={{ color: (v ?? 0) >= 95 ? WH.sev.Critical : WH.textMuted }}>
          {v === null ? '—' : `${v}%`}
        </Text>,
        { kind: 'kpi', kpiKey, service: r.service, focus: 'trend' },
      ),
    },
    {
      title: t('uk.col.usedMem'), dataIndex: 'used_kb', align: 'right', width: 120,
      render: (v: number | null) => (v === null ? '—' : `${(v / 1024 / 1024).toFixed(1)} GB`),
    },
    {
      title: t('uk.col.status'), dataIndex: 'status', align: 'center', width: 96,
      filters: (['good', 'warning', 'critical'] as Status[]).map(s => ({ text: statusLabel(s), value: s })),
      onFilter: (v, r) => r.status === v,
      render: (v: Status) => <StatusBadge status={v} label={statusLabel(v)} isDark={isDark} />,
    },
  ]

  /* ---------- 表格：告警列表（模块级 buildAlertColumns，告警卡片与「告警数」汇总下钻共用） ---------- */
  const alertColumns = useMemo(
    () => buildAlertColumns(t, isDark, statusLabel, en), [t, isDark, statusLabel, en])

  /* ---------- 导出 Excel（与页面当前所见一致：仅导出已加载的 KPI） ---------- */
  const onExport = useCallback(async () => {
    if (!data) return
    const specs: ReportSheetSpec[] = []
    const kpiCols = [t('uk.col.kpi'), t('uk.col.attempts'), t('uk.col.success'), t('uk.col.failed'),
      t('uk.col.rate'), t('uk.col.systemFailed'), t('uk.col.sysFailRate'),
      t('uk.col.userFailed'), t('uk.col.status')]
    specs.push({
      name: 'KPI Summary',
      title: t('uk.export.summaryTitle'),
      subtitle: `${t('uk.latestDay')}: ${data.meta.latest_day ?? '—'}    |    ${data.meta.days[0] ?? ''} ~ ${data.meta.latest_day ?? ''}`,
      header: kpiCols,
      rows: successKpis.map(k => [
        `${kpiTitleOf(k, locale === 'en')} (${k.key})`, k.attempts, k.success, k.failed,
        k.success_rate === null ? '' : Number((k.success_rate * 100).toFixed(4)),
        k.system_failed,
        k.system_fail_rate === null ? '' : Number((k.system_fail_rate * 100).toFixed(6)),
        k.user_failed, statusLabel(k.status),
      ]),
      numericCols: [1, 2, 3, 4, 5, 6, 7],
    })
    specs.push({
      name: 'Service Detail',
      title: t('uk.export.serviceTitle'),
      subtitle: `${t('uk.latestDay')}: ${data.meta.latest_day ?? '—'}`,
      header: [t('uk.col.kpi'), t('uk.col.service'), t('uk.col.attempts'), t('uk.col.success'),
        t('uk.col.failed'), t('uk.col.rate'), t('uk.col.systemFailed'),
        t('uk.col.userFailed'), t('uk.col.status')],
      rows: successKpis.flatMap(k => k.services.map(s => [
        k.key, s.service ?? '', s.attempts, s.success, s.failed,
        s.success_rate === null ? '' : Number((s.success_rate * 100).toFixed(4)),
        s.system_failed, s.user_failed, statusLabel(s.status),
      ])),
      numericCols: [2, 3, 4, 5, 6, 7],
    })
    specs.push({
      name: 'Failure Breakdown',
      title: t('uk.export.failTitle'),
      subtitle: `${t('uk.latestDay')}: ${data.meta.latest_day ?? '—'}`,
      header: [t('uk.col.kpi'), t('uk.col.service'), t('uk.fail.reason'), t('uk.fail.side'), t('uk.col.failed')],
      rows: successKpis.flatMap(k => k.services.flatMap(s => s.failures.map(f => [
        k.key, s.service ?? '', failReasonOf(f, en),
        f.side === 'system' ? t('uk.fail.system') : t('uk.fail.user'), f.value,
      ]))),
      numericCols: [4],
    })
    specs.push({
      name: 'Resource',
      title: t('uk.export.resTitle'),
      subtitle: `${t('uk.latestDay')}: ${data.meta.latest_day ?? '—'}`,
      header: [t('uk.col.kpi'), t('uk.col.service'), t('uk.res.avg'), t('uk.res.top'),
        t('uk.col.usedMem'), t('uk.col.status')],
      rows: resourceKpis.flatMap(k => k.services.map(s => [
        k.key, s.service ?? '', s.avg ?? '', s.top ?? '',
        s.used_kb === null ? '' : Number((s.used_kb / 1024 / 1024).toFixed(1)), statusLabel(s.status),
      ])),
      numericCols: [2, 3, 4],
    })
    specs.push({
      name: 'Trend',
      title: t('uk.export.trendTitle'),
      header: [t('uk.col.kpi'), t('uk.col.day'), t('uk.col.attempts'), t('uk.col.success'),
        t('uk.col.failed'), t('uk.col.rate'), t('uk.col.systemFailed')],
      rows: successKpis.flatMap(k => k.trend.map(p => [
        k.key, p.day, p.attempts, p.success, p.failed,
        p.success_rate === null ? '' : Number((p.success_rate * 100).toFixed(4)),
        p.system_failed ?? 0,
      ])),
      numericCols: [2, 3, 4, 5, 6],
    })
    specs.push({
      name: 'Alerts',
      title: t('uk.export.alertsTitle'),
      subtitle: `${t('uk.generatedAt')}: ${data.meta.generated_at}`,
      header: [t('uk.col.level'), t('uk.col.kpi'), t('uk.col.service'), t('uk.col.metric'),
        t('uk.col.value'), t('uk.col.threshold'), t('uk.alerts.message')],
      rows: data.alerts.map(a => [
        statusLabel(a.level as Status), alertKpiLabel(a, en), a.service ?? '',
        alertTexts(a, en, t).metric,
        a.unit === 'ratio' ? Number(((a.value ?? 0) * 100).toFixed(4)) : (a.value ?? ''),
        a.unit === 'ratio' ? Number((a.threshold * 100).toFixed(4)) : a.threshold,
        alertTexts(a, en, t).message,
      ]),
      numericCols: [4, 5],
    })
    await exportReport(specs, `Customer_KPI_${data.meta.latest_day ?? 'export'}`)
  }, [data, successKpis, resourceKpis, statusLabel, en, t])

  const thresholds = data?.meta.thresholds
  const alerts = data?.alerts ?? []
  const hardAlerts = alerts.filter(a => a.level !== 'info')
  const infoAlerts = alerts.filter(a => a.level === 'info')

  /* ---------- 概览统计卡（每张都可下钻） ---------- */
  const summaryCards = useMemo(() => {
    if (!data) return []
    const mk = (metric: SummaryMetric, title: string, value: number | string, color: string) => ({
      title, value, color,
      drill: { kind: 'summary' as const, metric, title } as DrillTarget,
    })
    return [
      mk('kpis', t('uk.sum.kpi'), data.summary.kpi_count, WH.blue),
      mk('services', t('uk.sum.service'), data.summary.service_count, WH.blue),
      mk('attempts', t('uk.sum.attempts'), compact(data.summary.total_attempts), WH.text),
      mk('failed', t('uk.sum.failed'), compact(data.summary.total_failed), WH.sev.Warning),
      mk('system_failed', t('uk.sum.systemFailed'), num(data.summary.total_system_failed), WH.sev.Critical),
      mk('user_failed', t('uk.sum.userFailed'), compact(data.summary.total_user_failed), WH.textMuted),
      mk('alerts', t('uk.sum.alerts'), hardAlerts.length, hardAlerts.length ? WH.sev.Critical : WH.teal),
    ]
    // hardAlerts 由 data 派生，故 data 为依赖即可覆盖
  }, [data, t])

  return (
    <div style={{ background: WH.bg, borderRadius: 'var(--wh-radius-lg)', padding: 'var(--wh-space-xs)', minHeight: 'var(--wh-page-min-height)' }}>
      {/* ---------- 头部 ---------- */}
      <Card style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }} styles={{ body: { padding: 'var(--wh-space-sm) var(--wh-space-md)' } }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--wh-space-sm)', alignItems: 'center', justifyContent: 'space-between' }}>
          <Space direction="vertical" size={2}>
            <Title level={5} style={{ margin: 0, color: WH.text }}>{t('nav.umeInKpi')}</Title>
            <Text style={{ color: WH.textMuted, fontSize: 12 }}>
              {t('uk.subtitle')}
            </Text>
            {data?.meta.has_data && (
              <Space size={12} wrap style={{ marginTop: 2 }}>
                <Text style={{ color: WH.textDim, fontSize: 11 }}>
                  {t('uk.latestDay')}: <b style={{ color: WH.teal }}>{data.meta.latest_day}</b>
                </Text>
                <Text style={{ color: WH.textDim, fontSize: 11 }}>
                  {t('uk.generatedAt')}: {data.meta.generated_at}
                </Text>
                <Text style={{ color: WH.textDim, fontSize: 11 }}>
                  {t('uk.source')}: {data.meta.source}
                </Text>
              </Space>
            )}
          </Space>
          <Space wrap>
            <Segmented
              value={days}
              onChange={v => setDays(Number(v))}
              options={[
                { label: t('uk.days7'), value: 7 },
                { label: t('uk.days14'), value: 14 },
                { label: t('uk.days30'), value: 30 },
              ]}
            />
            <Tooltip title={t('uk.syncHint')}>
              <Button icon={<SyncOutlined />} loading={syncing} onClick={doSync}>
                {syncing ? t('uk.syncing') : t('uk.sync')}
              </Button>
            </Tooltip>
            <Tooltip title={t('uk.exportHint')}>
              <Button icon={<DownloadOutlined />} disabled={!successKpis.length} onClick={onExport}>
                {t('uk.export')}
              </Button>
            </Tooltip>
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>
              {t('uk.refresh')}
            </Button>
          </Space>
        </div>
      </Card>

      {error && (
        <Alert
          type="error" showIcon style={{ marginBottom: 'var(--wh-space-md)' }}
          message={t('uk.loadFailed')} description={error}
          action={<Button size="small" onClick={() => void load()}>{t('uk.retry')}</Button>}
        />
      )}

      <Spin spinning={loading && !data}>
        {!data?.meta.has_data ? (
          <Card style={cardStyle}>
            <Empty
              description={
                <Space direction="vertical" size={4}>
                  <Text style={{ color: WH.textMuted }}>{t('uk.noData')}</Text>
                  <Text style={{ color: WH.textDim, fontSize: 12 }}>{t('uk.noDataHint')}</Text>
                </Space>
              }
            >
              <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={doSync}>
                {t('uk.sync')}
              </Button>
            </Empty>
          </Card>
        ) : (
          <>
            {/* ---------- 告警（默认收起；展开为统一表格，点击行下钻） ---------- */}
            {hardAlerts.length > 0 && (
              <Card
                style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }}
                styles={{ body: { padding: 'var(--wh-space-xs) var(--wh-space-md)' } }}
              >
                <Collapse
                  ghost
                  defaultActiveKey={[]}
                  items={[{
                    key: 'alerts',
                    label: (
                      <Space size={8} wrap>
                        <WarningOutlined style={{ color: WH.sev.Critical }} />
                        <Text strong style={{ color: WH.text }}>
                          {t('uk.alerts.title')} ({hardAlerts.length})
                        </Text>
                        <Text style={{ color: WH.textDim, fontSize: 11 }}>{t('uk.alerts.expandHint')}</Text>
                      </Space>
                    ),
                    children: (
                      <Table<AlertRow>
                        rowKey={(r, i) => `${r.kpi}-${r.service ?? ''}-${r.metric}-${i ?? 0}`}
                        size="small"
                        dataSource={hardAlerts}
                        columns={alertColumns}
                        pagination={false}
                        scroll={{ x: 1080 }}
                        onRow={r => ({
                          onClick: (e: { clientX: number; clientY: number }) => drillTo(
                            {
                              kind: 'kpi', kpiKey: r.kpi, service: r.service, focus: 'fail',
                              level: r.level as Status, subtitle: alertTexts(r, en, t).message,
                              title: t('uk.drill.title', { kpi: alertKpiLabel(r, en) }),
                            },
                            { x: e.clientX, y: e.clientY },
                          ),
                          style: { cursor: 'pointer' },
                        })}
                        aria-label={t('uk.alerts.title')}
                      />
                    ),
                  }]}
                />
              </Card>
            )}

            {/* ---------- 概览统计（每张卡都可点击下钻到对应明细） ---------- */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 'var(--wh-space-sm)', marginBottom: 'var(--wh-space-md)' }}>
              {summaryCards.map((c, i) => (
                <Tooltip key={i} title={t('uk.drillHint')}>
                  <span style={{ display: 'block' }}>
                    <Card
                      style={{ ...cardStyle, cursor: 'pointer' }}
                      styles={{ body: { padding: 'var(--wh-space-sm)' } }}
                      onClick={(e: { clientX: number; clientY: number }) =>
                        drillTo(c.drill, { x: e.clientX, y: e.clientY })}
                    >
                      <Statistic
                        title={<span style={{ color: WH.textMuted, fontSize: 12 }}>{c.title}</span>}
                        value={c.value}
                        valueStyle={{ color: c.color, fontWeight: 700, fontSize: '1.375rem' }}
                      />
                    </Card>
                  </span>
                </Tooltip>
              ))}
            </div>

            {/* ---------- 业务 KPI 表 ---------- */}
            <Card
              title={<Text strong style={{ color: WH.text }}>{t('uk.table.title')}</Text>}
              extra={<Text style={{ color: WH.textDim, fontSize: 11 }}>{t('uk.table.expandHint')}</Text>}
              style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }}
              styles={{ body: { padding: 0 } }}
            >
              <Table<SuccessKpi>
                rowKey="key"
                size="small"
                dataSource={successKpis}
                columns={successColumns}
                pagination={false}
                scroll={{ x: 1080 }}
                expandable={{
                  expandedRowRender: (r) => (
                    <div style={{ padding: '4px 0' }}>
                      <Text style={{ color: WH.textMuted, fontSize: 12, display: 'block', marginBottom: 6 }}>
                        {t('uk.svcDetail')} · {t('uk.latestDay')} {r.day}
                      </Text>
                      <Table<SvcRow>
                        rowKey={s => `${r.key}-${s.service}`}
                        size="small"
                        dataSource={r.services}
                        pagination={false}
                        columns={[
                          { title: t('uk.col.service'), dataIndex: 'service', width: 220 },
                          { title: t('uk.col.attempts'), dataIndex: 'attempts', align: 'right', width: 100,
                            render: (v: number) => <Tooltip title={num(v)}><span>{compact(v)}</span></Tooltip> },
                          { title: t('uk.col.success'), dataIndex: 'success', align: 'right', width: 100,
                            render: (v: number) => <Tooltip title={num(v)}><span>{compact(v)}</span></Tooltip> },
                          { title: t('uk.col.failed'), dataIndex: 'failed', align: 'right', width: 100,
                            render: (v: number) => <Tooltip title={num(v)}><span>{compact(v)}</span></Tooltip> },
                          { title: t('uk.col.rate'), dataIndex: 'success_rate', align: 'right', width: 90,
                            render: (v: number | null, s: SvcRow) => (
                              <Text style={{ color: STATUS_COLOR[s.rate_status] }}>{pct(v)}</Text>) },
                          { title: t('uk.col.systemFailed'), dataIndex: 'system_failed', align: 'right', width: 100,
                            render: (v: number, s: SvcRow) => (
                              <Text style={{ color: v > 0 ? WH.sev.Critical : WH.textMuted }}>
                                {num(v)} <span style={{ color: WH.textDim, fontSize: 10 }}>({pct(s.system_fail_rate, 3)})</span>
                              </Text>) },
                          { title: t('uk.fail.reason'), key: 'failures',
                            render: (_: unknown, s: SvcRow) => (
                              s.failures.length
                                ? <Space size={4} wrap>{s.failures.map((f, i) => (
                                    <Pill key={i} text={`${f.name} ${compact(f.value)}`} side={f.side} isDark={isDark} />
                                  ))}</Space>
                                : <Text style={{ color: WH.textDim }}>—</Text>) },
                        ]}
                      />
                    </div>
                  ),
                }}
              />
            </Card>

            {/* ---------- 图表：失败率构成 + 成功率趋势（均可点击下钻） ---------- */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 'var(--wh-space-md)', marginBottom: 'var(--wh-space-md)' }}>
              <Card
                title={<Text strong style={{ color: WH.text }}>{t('uk.chart.failTitle')}</Text>}
                extra={<Text style={{ color: WH.textDim, fontSize: 11 }}>{t('uk.chart.drillHint')}</Text>}
                style={cardStyle}
              >
                {failChartOption
                  ? (
                    <ReactECharts
                      option={failChartOption} style={{ height: 300, cursor: 'pointer' }} notMerge
                      onEvents={{ click: onFailChartClick }}
                    />
                  )
                  : <Empty description={t('uk.chart.noFail')} />}
              </Card>
              <Card
                title={<Text strong style={{ color: WH.text }}>{t('uk.chart.trendTitle')}</Text>}
                extra={<Text style={{ color: WH.textDim, fontSize: 11 }}>{t('uk.chart.drillHint')}</Text>}
                style={cardStyle}
              >
                {trendChartOption
                  ? (
                    <ReactECharts
                      option={trendChartOption} style={{ height: 300, cursor: 'pointer' }} notMerge
                      onEvents={{ click: onTrendChartClick }}
                    />
                  )
                  : <Empty description={t('uk.noData')} />}
              </Card>
            </div>

            {/* ---------- 资源利用率（图表与表格均可点击下钻） ---------- */}
            <Card
              title={<Text strong style={{ color: WH.text }}>{t('uk.res.title')}</Text>}
              extra={
                <Space size={12} wrap>
                  <Text style={{ color: WH.textDim, fontSize: 11 }}>{t('uk.chart.drillHint')}</Text>
                  <Text style={{ color: WH.textDim, fontSize: 11 }}>
                    {t('uk.res.thresholdHint', {
                      warn: String(thresholds?.res_warn ?? 80),
                      crit: String(thresholds?.res_crit ?? 90),
                    })}
                  </Text>
                </Space>
              }
              style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }}
            >
              {resChartOption && (
                <ReactECharts
                  option={resChartOption} style={{ height: 420, cursor: 'pointer' }} notMerge
                  onEvents={{ click: onResChartClick }}
                />
              )}
              {resourceKpis.map(k => (
                <div key={k.key} style={{ marginTop: 'var(--wh-space-sm)' }}>
                  <Space style={{ marginBottom: 6 }}>
                    <Text strong style={{ color: WH.text }}>
                      {locale === 'en' ? k.title_en : k.title_zh}
                    </Text>
                    <StatusBadge status={k.status} label={statusLabel(k.status)} isDark={isDark} />
                    <Text style={{ color: WH.textDim, fontSize: 11 }}>
                      {t('uk.res.avg')} {k.avg === null ? '—' : `${k.avg}%`} · {t('uk.res.top')} {k.top === null ? '—' : `${k.top}%`}
                    </Text>
                  </Space>
                  <Table<ResSvcRow>
                    rowKey={s => `${k.key}-${s.service}`}
                    size="small"
                    dataSource={k.services}
                    columns={buildResColumns(k.key)}
                    pagination={false}
                  />
                </div>
              ))}
            </Card>

            {/* ---------- 分析提示（用户侧失败为主，非故障；点击可下钻核对归因） ---------- */}
            {infoAlerts.length > 0 && (
              <Card
                title={<Space><InfoCircleOutlined style={{ color: WH.blue }} />
                  <Text strong style={{ color: WH.text }}>{t('uk.info.title')}</Text></Space>}
                extra={<Text style={{ color: WH.textDim, fontSize: 11 }}>{t('uk.drillHint')}</Text>}
                style={cardStyle}
                styles={{ body: { padding: 'var(--wh-space-sm) var(--wh-space-md)' } }}
              >
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  {infoAlerts.map((a, i) => (
                    <Text
                      key={i}
                      style={{ color: WH.textMuted, fontSize: 12, cursor: 'pointer', display: 'block' }}
                      onClick={(e: { clientX: number; clientY: number }) => drillTo(
                        {
                          kind: 'kpi', kpiKey: a.kpi, service: a.service, focus: 'fail',
                          level: 'info', subtitle: alertTexts(a, en, t).message,
                          title: t('uk.drill.title', { kpi: alertKpiLabel(a, en) }),
                        },
                        { x: e.clientX, y: e.clientY },
                      )}
                    >
                      • {alertTexts(a, en, t).message}
                    </Text>
                  ))}
                </Space>
              </Card>
            )}
          </>
        )}
      </Spin>

      {/* ==================== 全页统一下钻弹窗（统一弹窗 + 统一表格格式） ==================== */}
      {data && (
        <DrillModal
          data={data}
          target={drill?.target ?? null}
          anchor={drill?.anchor ?? null}
          onClose={closeDrill}
          onDrill={drillTo}
        />
      )}
    </div>
  )
}
