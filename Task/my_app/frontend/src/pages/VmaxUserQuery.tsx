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
  Alert, Button, DatePicker, Descriptions, Input, Space, Spin, Table, Tag, Typography,
} from 'antd'
import { MobileOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'

import { useI18n } from '../i18n'
import { CardBase } from '../components/cards'
import DraggableClickModal from '../components/DraggableClickModal'
import { vmaxCcaQuery } from '../api'

const { Text } = Typography;
const { RangePicker } = DatePicker

type KpiItem = { code: string; name: string; value: unknown }

type CellRecord = {
  cellname?: string; vendor?: string; pci?: number; earfcn?: string
  celllat?: number; celllon?: number; azimuth?: number; height?: number
  cellkey?: string; rat?: number; cell?: number
}

type QueryResult = {
  msisdn: string
  found: boolean
  user: Record<string, unknown>
  terminal: Record<string, unknown> | null
  window?: { starttime: string; endtime: string }
  flow?: { total_flux: string; apps: unknown[] } | null
  cells?: { cells: CellRecord[]; cell_kpi: Record<string, KpiItem[]> } | null
  failures?: string[]
  msg: string
}

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
  // 当前查询的请求序号：旧请求的迟到结果直接丢弃（抄 EflowQa 的 ttSeqRef）
  const seqRef = useRef(0)

  // 小区 KPI 弹窗（可拖拽，点遮罩不关闭）
  const [kpiOpen, setKpiOpen] = useState(false)
  const [kpiCell, setKpiCell] = useState<CellRecord | null>(null)
  const [kpiItems, setKpiItems] = useState<KpiItem[]>([])
  const [kpiAnchor, setKpiAnchor] = useState<{ x: number; y: number } | null>(null)

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
          <CardBase title={t('vmaxq.userCard')} extra={<Tag color="cyan">{result.msisdn}</Tag>}>
            <Descriptions
              column={{ xs: 1, sm: 2, md: 3 }}
              size="small"
              bordered
              items={userItems(result.user || {})}
            />
          </CardBase>

          <CardBase title={t('vmaxq.terminalCard')}>
            {result.terminal ? (
              <Descriptions
                column={{ xs: 1, sm: 2, md: 3 }}
                size="small"
                bordered
                items={terminalItems(result.terminal)}
              />
            ) : (
              <Text type="secondary">{t('vmaxq.noTerminal')}</Text>
            )}
          </CardBase>

          <CardBase
            title={t('vmaxq.flowCard')}
            extra={result.window
              ? <Text type="secondary" style={{ fontSize: 12 }}>
                  {result.window.starttime.slice(0, 10)} ~ {result.window.endtime.slice(0, 10)}
                </Text>
              : undefined}
          >
            {result.flow ? (
              <>
                <Descriptions size="small" bordered column={1} items={[{
                  key: 'total', label: t('vmaxq.flowTotal'),
                  children: <Text strong>{result.flow.total_flux}</Text>,
                }]} />
                {flowApps.length > 0 && (
                  <Table
                    style={{ marginTop: 12 }}
                    rowKey={(_, i) => String(i)}
                    columns={flowColumns}
                    dataSource={flowApps as Record<string, unknown>[]}
                    pagination={{ pageSize: 8 }}
                    size="small"
                  />
                )}
              </>
            ) : (
              <Text type="secondary">{t('vmaxq.noFlow')}</Text>
            )}
          </CardBase>

          <CardBase title={t('vmaxq.cellsCard')}>
            {result.cells?.cells?.length ? (
              <>
                <div style={{ marginBottom: 8 }}>
                  <Tag color="blue">{t('vmaxq.cellCount', { n: result.cells.cells.length })}</Tag>
                  <Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxq.cellsHint')}</Text>
                </div>
                <Table
                  rowKey={r => String(r.cell ?? r.cellkey ?? r.cellname)}
                  columns={cellColumns}
                  dataSource={result.cells.cells}
                  pagination={{ pageSize: 10, showSizeChanger: true }}
                  size="small"
                  scroll={{ x: 760 }}
                />
              </>
            ) : (
              <Text type="secondary">{t('vmaxq.noCells')}</Text>
            )}
          </CardBase>
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
  )
}
