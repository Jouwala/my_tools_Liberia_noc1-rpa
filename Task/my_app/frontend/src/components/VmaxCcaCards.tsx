/* ============================================================================
 * VmaxCcaCards —— VMAX 用户查询「用户概览」页签的五张结果卡
 * ============================================================================
 *
 * 2026-10-26 从 VmaxUserQuery.tsx 抽出：该页并入「信令详单」页签后逼近
 * 500 行上限（AGENTS.md 三.2），把这块纯展示逻辑独立出来。
 *
 * 只做渲染，不含请求与状态：数据与回调由父页面传入。
 *   用户信息 / 终端信息 / 按应用流量 / 驻留小区（含 KPI 弹窗）/ 根因分析
 * 字段标签走 i18n 的 vmaxq.field.*，未识别的键按原始键名兜底（不丢信息）。
 * ========================================================================== */

import { Button, Descriptions, Table, Tag, Typography } from 'antd'

import { useI18n } from '../i18n'
import { CardBase } from '../components/cards'

const { Text } = Typography

type KpiItem = { code: string; name: string; value: unknown }

export type CauseItem = {
  rule_name: string; object_type: string; object_name: string; objectinfo: string
  confidence: number; description: string; solution: string; vendor: string
  province: string; city: string; poortime: string; kqicode: string
  app_info: { clttime: string; judge: string }[]
}

export type CellRecord = {
  cellname?: string; vendor?: string; pci?: number; earfcn?: string
  celllat?: number; celllon?: number; azimuth?: number; height?: number
  cellkey?: string; rat?: number; cell?: number
}

export type CcaResult = {
  msisdn: string
  found: boolean
  user: Record<string, unknown>
  terminal: Record<string, unknown> | null
  window?: { starttime: string; endtime: string }
  cells?: { cells: CellRecord[]; cell_kpi: Record<string, KpiItem[]> } | null
  causes?: CauseItem[] | null
  failures?: string[]
  msg: string
}

/** 统一空值展示：— 而不是 undefined / null（AGENTS.md 三.6） */
const fmt = (v: unknown) => (v == null || v === '' || v === '--' ? '—' : String(v))
const fmtArr = (v: unknown) =>
  Array.isArray(v) && v.length ? v.map((x) => String(x)).join('、') : '—'

/** 字段标签：已知字段用 i18n，未识别的按原始键名兜底展示 */
function fieldLabel(key: string, t: (k: string) => string) {
  const k = `vmaxq.field.${key}`
  return t(k) === k ? key : t(k)
}

export default function VmaxCcaCards({
  result, onOpenKpi, onOpenCause,
}: {
  result: CcaResult
  onOpenKpi: (cell: CellRecord) => void
  onOpenCause: (item: CauseItem) => void
}) {
  const { t } = useI18n()

  const userItems = Object.entries(result.user).map(([key, value]) => ({
    key,
    label: fieldLabel(key, t),
    children: (key === 'imsi_arr' ? fmtArr : fmt)(value),
  }))

  const terminalItems = Object.entries(result.terminal || {}).map(([key, value]) => ({
    key, label: fieldLabel(key, t), children: fmt(value),
  }))

  const cells = result.cells?.cells || []
  const causes = result.causes || []

  /* 覆盖指标：从该小区的 cellKpi 里取 RSRP / SINR / RSRQ 的均值。
   * 上游指标名按制式不同（LTE 与 NR 各一套），这里按优先级匹配前缀，
   * 命中不到返回 null 由渲染层显示 —（不是 0，AGENTS.md 三.6）。
   * 实测 2026-10-26：约 7/19 小区有 MR 采样，其余无值属正常（该小区窗口内无 MR 上报）。 */
  const COVERAGE_SPECS: { key: string; unit: string; names: string[] }[] = [
    { key: 'rsrp', unit: 'dBm', names: ['Average RSRP', 'Average SSBRSRP'] },
    { key: 'sinr', unit: 'dB', names: ['Average Uplink SINR', 'Average Downlink SSB-SINR'] },
    { key: 'rsrq', unit: 'dB', names: ['Average RSRQ', 'Average SSB-RSRQ'] },
  ]
  const coverageOf = (cellKey: string) => {
    const kpis = result.cells?.cell_kpi?.[String(cellKey)] || []
    const out: Record<string, string | null> = {}
    for (const spec of COVERAGE_SPECS) {
      const hit = kpis.find(k => spec.names.some(n => String(k.name).startsWith(n)))
      const raw = hit?.value
      // 上游可能给 "--" 或 null 表示无采样，统一按无值处理
      out[spec.key] = raw == null || raw === '' || raw === '--' ? null : `${raw} ${spec.unit}`
    }
    return out
  }
  /** 小区行的 KPI 归属键：userTrack 的 cell 字段（与 cellKpi 的键一致） */
  const cellKpiKey = (r: CellRecord) => String(r.cell ?? r.cellkey ?? r.cellname ?? '')

  /* 覆盖指标单元格：无采样显示 —；有值时按质量着色，差覆盖一眼可见。
   * 阈值取业界常用口径（LTE）：RSRP ≥ -95 好 / -110~-95 中 / < -110 差；
   * SINR ≥ 10 好 / 0~10 中 / < 0 差；RSRQ ≥ -10 好 / -20~-10 中 / < -20 差。
   * 颜色只引用 --wh-* 令牌（AGENTS.md 三.3：不写死十六进制）。 */
  const covCell = (text: string | null, good: number, fair: number) => {
    if (text == null) return <Text type="secondary">—</Text>
    const n = parseFloat(text)
    const color = Number.isNaN(n)
      ? undefined
      : n >= good ? 'var(--wh-ok)'
      : n >= fair ? 'var(--wh-warn)'
      : 'var(--wh-danger)'
    return <Text style={{ fontSize: 12, color }}>{text}</Text>
  }

  // 全列固定宽 + scroll.x=列宽总和：宽屏上富余宽度按列宽比例分摊。
  // cellname 若不设宽会独吞全部剩余空间（其余 10 列都有 width），宽屏上撑得离谱。
  const cellColumns = [
    { title: t('vmaxq.field.cellname'), dataIndex: 'cellname', render: fmt,
      width: 220, ellipsis: true },
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
    // 覆盖指标三列：直接从该小区 cellKpi 取均值，免去逐个点开 KPI 弹窗
    { title: 'RSRP', key: 'rsrp', width: 105,
      render: (_: unknown, r: CellRecord) => covCell(coverageOf(cellKpiKey(r)).rsrp, -95, -110) },
    { title: 'SINR', key: 'sinr', width: 100,
      render: (_: unknown, r: CellRecord) => covCell(coverageOf(cellKpiKey(r)).sinr, 10, 0) },
    { title: 'RSRQ', key: 'rsrq', width: 100,
      render: (_: unknown, r: CellRecord) => covCell(coverageOf(cellKpiKey(r)).rsrq, -10, -20) },
    { title: 'KPI', key: 'kpi', width: 90,
      render: (_: unknown, r: CellRecord) => (
        <Button type="link" size="small" onClick={() => onOpenKpi(r)}>
          {t('vmaxq.kpi')}
        </Button>
      ) },
  ]

  const causeColumns = [
    { title: t('vmaxq.cause.confidence'), dataIndex: 'confidence', width: 90,
      render: (v: number) => (
        <Tag color={v >= 90 ? 'red' : v >= 60 ? 'orange' : 'default'}>{v}%</Tag>
      ),
      sorter: (a: CauseItem, b: CauseItem) => a.confidence - b.confidence },
    { title: t('vmaxq.cause.rule'), dataIndex: 'rule_name', ellipsis: true },
    { title: t('vmaxq.cause.object'), key: 'obj', width: 190, ellipsis: true,
      render: (_: unknown, r: CauseItem) => r.object_name || r.objectinfo || '—' },
    { title: t('vmaxq.cause.poortime'), dataIndex: 'poortime', width: 150, ellipsis: true,
      render: (v: string) => fmt(v) },
    { title: t('vmaxq.cause.detail'), key: 'act', width: 80,
      render: (_: unknown, r: CauseItem) => (
        <Button type="link" size="small" onClick={() => onOpenCause(r)}>
          {t('vmaxq.cause.detail')}
        </Button>
      ) },
  ]

  return (
    <>
        <CardBase title={t('vmaxq.userCard')} extra={<Tag color="cyan">{result.msisdn}</Tag>}>
          <Descriptions
            column={{ xs: 1, sm: 2, md: 3 }}
            size="small"
            bordered
            items={userItems}
          />
        </CardBase>

        <CardBase title={t('vmaxq.terminalCard')}>
          {result.terminal ? (
            <Descriptions
              column={{ xs: 1, sm: 2, md: 3 }}
              size="small"
              bordered
              items={terminalItems}
            />
          ) : (
            <Text type="secondary">{t('vmaxq.noTerminal')}</Text>
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
                scroll={{ x: 1195 }}
              />
            </>
          ) : (
            <Text type="secondary">{t('vmaxq.noCells')}</Text>
          )}
        </CardBase>

        <CardBase title={t('vmaxq.causesCard')}>
          {causes.length ? (
            <>
              <div style={{ marginBottom: 8 }}>
                <Tag color="red">{t('vmaxq.causeCount', { n: causes.length })}</Tag>
                <Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxq.causesHint')}</Text>
              </div>
              <Table
                rowKey={r => `${r.kqicode}-${r.objectinfo}-${r.poortime}`}
                columns={causeColumns}
                dataSource={causes}
                pagination={{ pageSize: 10, showSizeChanger: true }}
                size="small"
                scroll={{ x: 760 }}
              />
            </>
          ) : (
            <Text type="secondary">{t('vmaxq.noCauses')}</Text>
          )}
        </CardBase>
    </>
  )
}
