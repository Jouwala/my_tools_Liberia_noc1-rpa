/* ============================================================================
 * VmaxUserQuery —— VMAX 用户信息查询（CCA 投诉系统）
 * ============================================================================
 *
 * 输入用户号码 + 时间窗 → 后端经 VMAX CCA 投诉查询接口（services/vmax_cca）取：
 *   ① 用户信息（MSISDN/IMSI 映射）  ② 终端信息（IMEI/机型/运营商…）
 *   ③ 窗口内按应用流量（多数用户无 DPI 记录，空态正常）
 *   ④ 窗口内驻留小区列表 + 每小区 KPI（点行弹 DraggableClickModal 看 KPI 明细）
 *
 * 后端只做透传不落库；found=false 表示 VMAX 查无此号（业务正常，展示警示态）。
 * 三态渲染与请求序号守卫抄 EflowQa 的 TT 快速分析（防旧请求迟到回写）。
 * ========================================================================== */

import { useCallback, useMemo, useRef, useState } from 'react'
import {
  Alert, Button, DatePicker, Descriptions, Input, Segmented, Space, Spin, Table, Tag, Typography,
} from 'antd'
import { MobileOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'

import { useI18n } from '../i18n'
import { CardBase } from '../components/cards'
import DraggableClickModal from '../components/DraggableClickModal'
import VmaxXdrPanel from '../components/VmaxXdrPanel'
import VmaxCcaCards, {
  type CcaResult, type CauseItem, type CellRecord,
} from '../components/VmaxCcaCards'
import { vmaxCcaQuery } from '../api'

const { Text } = Typography;
const { RangePicker } = DatePicker

// 结果类型与 VmaxCcaCards 共用一份（避免同一结构两处维护后漂移）
type KpiItem = { code: string; name: string; value: unknown }
type QueryResult = CcaResult

/** 统一空值展示：— 而不是 undefined / null（AGENTS.md 三.6） */
const fmt = (v: unknown) => (v == null || v === '' || v === '--' ? '—' : String(v))

const rangeNums = (start: number, end: number) =>
  Array.from({ length: end - start }, (_, i) => start + i)

/** 当天面板禁用未来时/分（日期级 disabledDate 管不到时间面板） */
const disableFutureTime = (d: unknown, type?: string) => {
  const day = d as Dayjs | null
  if (!day || !day.isSame(dayjs(), 'day')) return {}
  const now = dayjs()
  return {
    disabledHours: () => (type ? rangeNums(now.hour() + 1, 24) : []),
    disabledMinutes: (h: number) => (h === now.hour() ? rangeNums(now.minute() + 1, 60) : []),
  }
}

/** 数组值（imei_arr / network_arr / flag_arr…）扁平化成可读字符串 */
const fmtArr = (v: unknown) => {
  if (Array.isArray(v)) {
    const flat = v.flat(2).map(x => String(x))
    return flat.filter(s => s && s !== '--').join('，') || '—'
  }
  return fmt(v)
}

export default function VmaxUserQuery() {
  const { t } = useI18n()

  const [msisdn, setMsisdn] = useState('')
  // 时间窗：精确到分钟，默认今天 00:00 ~ 当前时刻（后端归一，跨度上限 31 天）
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>([
    dayjs().startOf('day'), dayjs(),
  ])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<QueryResult | null>(null)
  const [searched, setSearched] = useState(false)
  // 视图切换：概览（CCA）/ 详单（Talon XDR）。用 Segmented 而非 Tabs，
  // 与 ttwo 的时间范围开关同一观感（.wh-seg 实心青选中态，选项一眼可见）。
  const [view, setView] = useState<'overview' | 'xdr'>('overview')
  // 当前查询的请求序号：旧请求的迟到结果直接丢弃（抄 EflowQa 的 ttSeqRef）
  const seqRef = useRef(0)

  // 小区 KPI 弹窗（可拖拽，点遮罩不关闭）
  const [kpiOpen, setKpiOpen] = useState(false)
  const [kpiCell, setKpiCell] = useState<CellRecord | null>(null)
  const [kpiItems, setKpiItems] = useState<KpiItem[]>([])
  const [kpiAnchor, setKpiAnchor] = useState<{ x: number; y: number } | null>(null)

  // 根因详情弹窗
  const [causeOpen, setCauseOpen] = useState(false)
  const [causeItem, setCauseItem] = useState<CauseItem | null>(null)

  const run = useCallback(async (raw: string) => {
    const q = raw.trim()
    if (!q) return
    const seq = ++seqRef.current
    setLoading(true)
    setError('')
    setSearched(true)
    const start = range?.[0]?.format('YYYY-MM-DD HH:mm') || undefined
    const end = range?.[1]?.format('YYYY-MM-DD HH:mm') || undefined
    try {
      const r = await vmaxCcaQuery(q, start, end)
      if (seq !== seqRef.current) return   // 已有更新的查询，丢弃本次结果
      setResult(r.data as QueryResult)
    } catch (e: any) {
      if (seq !== seqRef.current) return
      // 后端 HTTPException 的中文说明在 detail（凭据未配置 / 上游不可用等）
      setError(e?.response?.data?.detail || e?.message || String(e))
      setResult(null)
    } finally {
      if (seq === seqRef.current) setLoading(false)
    }
  }, [range])

  /* ---- 用户信息卡：已知字段给 i18n 标签，其余键值兜底 ---- */
  const userItems = useCallback((user: Record<string, unknown>) => {
    const known: Record<string, (v: unknown) => string> = {
      msisdn: fmt, imsi: fmt, imsi_arr: fmtArr,
    }
    return Object.entries(user).map(([key, value]) => ({
      key,
      label: t(`vmaxq.field.${key}`) === `vmaxq.field.${key}` ? key : t(`vmaxq.field.${key}`),
      children: (known[key] ?? fmt)(value),
    }))
  }, [t])

  /* ---- 终端信息卡 ---- */
  const terminalItems = useCallback((terminal: Record<string, unknown>) => {
    const known: Record<string, (v: unknown) => string> = {
      imei_arr: fmtArr, modelname_arr: fmtArr, modelvendor_arr: fmtArr,
      modelos_arr: fmtArr, network_arr: fmtArr, flag_arr: fmtArr,
      country_name: fmt, operator: fmt, msisdn: fmt,
    }
    return Object.entries(terminal).map(([key, value]) => ({
      key,
      label: t(`vmaxq.field.${key}`) === `vmaxq.field.${key}` ? key : t(`vmaxq.field.${key}`),
      children: (known[key] ?? fmt)(value),
    }))
  }, [t])

  /* ---- 驻留小区表列 ---- */
  const cellColumns = useMemo(() => [
    { title: t('vmaxq.field.cellname'), dataIndex: 'cellname', render: fmt,
      ellipsis: true },
    { title: t('vmaxq.field.vendor'), dataIndex: 'vendor', render: fmt, width: 80 },
    { title: t('vmaxq.field.pci'), dataIndex: 'pci', render: fmt, width: 70 },
    { title: t('vmaxq.field.earfcn'), dataIndex: 'earfcn', render: fmt, width: 90 },
    { title: t('vmaxq.field.latlon'), key: 'latlon', width: 170,
      render: (_: unknown, r: CellRecord) =>
        r.celllat == null && r.celllon == null ? '—' : `${fmt(r.celllat)}, ${fmt(r.celllon)}` },
    { title: t('vmaxq.field.azimuth'), dataIndex: 'azimuth', key: 'az', width: 90,
      render: (v: unknown) => (v == null ? '—' : `${v}°`) },
    { title: t('vmaxq.field.height'), dataIndex: 'height', width: 80,
      render: (v: unknown) => (v == null ? '—' : `${v} m`) },
    {
      title: 'KPI', key: 'kpi', width: 90,
      render: (_: unknown, r: CellRecord) => (
        <Button type="link" size="small"
          onClick={e => {
            setKpiCell(r)
            setKpiItems(result?.cells?.cell_kpi?.[String(r.cell)] || [])
            setKpiAnchor({ x: e.clientX, y: e.clientY })
            setKpiOpen(true)
          }}>
          {t('vmaxq.kpi')}
        </Button>
      ),
    },
  ], [t, result])

  const kpiColumns = useMemo(() => [
    { title: t('vmaxq.kpiName'), dataIndex: 'name', ellipsis: true },
    { title: t('vmaxq.kpiValue'), dataIndex: 'value', width: 110, align: 'right' as const,
      render: fmt },
    { title: t('vmaxq.kpiCode'), dataIndex: 'code', width: 150, ellipsis: true,
      render: (v: string) => <Text type="secondary" style={{ fontSize: 12 }}>{v}</Text> },
  ], [t])

  /* ---- 根因分析表列 ---- */
  const causes = result?.causes || []
  const causeColumns = useMemo(() => [
    {
      title: t('vmaxq.cause.confidence'), dataIndex: 'confidence', width: 90,
      render: (v: number) => (
        <Tag color={v >= 90 ? 'red' : v >= 60 ? 'orange' : 'default'}>{v}%</Tag>
      ),
      sorter: (a: CauseItem, b: CauseItem) => a.confidence - b.confidence,
    },
    { title: t('vmaxq.cause.rule'), dataIndex: 'rule_name', ellipsis: true },
    {
      title: t('vmaxq.cause.object'), key: 'obj', width: 190, ellipsis: true,
      render: (_: unknown, r: CauseItem) => r.object_name || r.objectinfo || '—',
    },
    { title: t('vmaxq.cause.poortime'), dataIndex: 'poortime', width: 150, ellipsis: true,
      render: fmt },
    {
      title: t('vmaxq.cause.detail'), key: 'act', width: 80,
      render: (_: unknown, r: CauseItem) => (
        <Button type="link" size="small" onClick={() => { setCauseItem(r); setCauseOpen(true) }}>
          {t('vmaxq.cause.detail')}
        </Button>
      ),
    },
  ], [t])

  const flowApps = result?.flow?.apps || []
  // app_flux 命中样本尚缺（多数用户无 DPI 记录），列名从首条记录的键动态生成
  const flowColumns = useMemo(() => {
    const first = flowApps.find(a => a && typeof a === 'object') as Record<string, unknown> | undefined
    if (!first) return []
    return Object.keys(first).map(k => ({
      title: t(`vmaxq.field.${k}`) === `vmaxq.field.${k}` ? k : t(`vmaxq.field.${k}`),
      dataIndex: k, render: fmt, ellipsis: true,
    }))
  }, [flowApps, t])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>

      {/* ① 查询条：号码 + 时间窗 */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap>
          <Input
            allowClear
            prefix={<MobileOutlined style={{ color: 'var(--wh-text-dim)' }} />}
            placeholder={t('vmaxq.inputPlaceholder')}
            value={msisdn}
            onChange={e => setMsisdn(e.target.value)}
            onPressEnter={() => void run(msisdn)}
            style={{ width: 260 }}
            maxLength={24}
          />
          <RangePicker
            value={range}
            onChange={v => setRange(v as [Dayjs | null, Dayjs | null] | null)}
            allowClear={false}
            showTime={{ format: 'HH:mm' }}
            format="YYYY-MM-DD HH:mm"
            minuteStep={5}
            disabledDate={(d: Dayjs) => d.isAfter(dayjs(), 'day')}
            disabledTime={disableFutureTime}
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            loading={loading}
            onClick={() => void run(msisdn)}
          >
            {t('vmaxq.search')}
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxq.hint')}</Text>
        </Space>
      </CardBase>

      {/* ② 视图切换：概览（CCA）/ 详单（Talon XDR）。共用上面那一个号码输入。
          用 Segmented + .wh-seg（与 ttwo 时间范围开关同一观感）：
          默认 antd Tabs 的页签太淡，用户反馈看不出是两个视角。 */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap align="center" size="middle">
          <Segmented
            className="wh-seg"
            options={[
              { label: t('vmaxq.tab.overview'), value: 'overview' },
              { label: t('vmaxq.tab.xdr'), value: 'xdr' },
            ]}
            value={view}
            onChange={(v) => setView(v as 'overview' | 'xdr')}
            style={{ background: 'var(--wh-seg-bg)' }}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {view === 'overview' ? t('vmaxq.tab.overviewHint') : t('vmaxq.tab.xdrHint')}
          </Text>
        </Space>
      </CardBase>

      {view === 'overview' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
      {/* ② 错误（接口失败）+ 重试 */}
      {error && (
        <Alert
          type="error"
          showIcon
          message={error}
          action={
            <Button size="small" icon={<ReloadOutlined />} onClick={() => void run(msisdn)}>
              {t('vmaxq.retry')}
            </Button>
          }
        />
      )}

      {/* ③ 部分查询失败（不阻断整体结果） */}
      {!!result?.failures?.length && (
        <Alert type="warning" showIcon
          message={t('vmaxq.partialFail')}
          description={result.failures.join('；')} />
      )}

      {/* ④ 加载态 */}
      {loading && (
        <CardBase>
          <div style={{ textAlign: 'center', padding: 60 }}>
            <Spin size="large" />
            <div style={{ marginTop: 12 }}>
              <Text type="secondary">{t('vmaxq.querying')}</Text>
            </div>
          </div>
        </CardBase>
      )}

      {/* ⑤ 查无此号（业务正常返回，非错误） */}
      {!loading && !error && result && !result.found && (
        <Alert
          type="warning"
          showIcon
          message={t('vmaxq.notFound', { msisdn: result.msisdn })}
          description={result.msg ? `${t('vmaxq.upstreamMsg')}：${result.msg}` : undefined}
        />
      )}

      {/* ⑥ 命中：用户 / 终端 / 流量 / 驻留小区 */}
      {!loading && !error && result?.found && (
        <>
          <VmaxCcaCards
            result={result as CcaResult}
            onOpenKpi={(cell) => { setKpiCell(cell); setKpiItems(result?.cells?.cell_kpi?.[String(cell.cell)] || []); setKpiOpen(true) }}
            onOpenCause={(item) => { setCauseItem(item); setCauseOpen(true) }}
          />
        </>
      )}

      {/* ⑦ 初始空态 */}
      {!loading && !error && !result && !searched && (
        <CardBase>
          <div style={{ textAlign: 'center', padding: 48 }}>
            <MobileOutlined style={{ fontSize: 40, color: 'var(--wh-text-dim)' }} />
            <div style={{ marginTop: 12 }}>
              <Text type="secondary">{t('vmaxq.empty')}</Text>
            </div>
          </div>
        </CardBase>
      )}

      {/* ⑧ 小区 KPI 弹窗（可拖拽） */}
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
              </div>
      )}

      {view === 'xdr' && (
        // 号码沿用上面查询条；XDR 的窗口与类型在本视图内独立选（见 VmaxXdrPanel 头注释）
        <VmaxXdrPanel msisdn={msisdn} />
      )}

      {/* ⑨ 根因详情弹窗（劣化描述 + 处理建议 + 逐时段明细） */}
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
  )
}
