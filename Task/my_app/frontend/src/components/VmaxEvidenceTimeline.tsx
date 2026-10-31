/* ============================================================================
 * VmaxEvidenceTimeline —— 证据时间线（四个源按分钟对齐）
 * ============================================================================
 *
 * 【2026-10-31 新增，方案 §4.9】
 *
 * 这张表是整个改版的**核心论证载体**。四个数据源各自看都只能得到一句话，
 * 只有按分钟对齐、摆在同一行里，才能得出「这条投诉到底是什么原因」：
 *
 *   时间     业务流量      响应时延      传输质量      无线质量     结论
 *   08:14   视频 320MB ↓   首包 8.2s↑    重传 3.1%↑   RSRP -118↓   弱覆盖下仍有业务（卡顿风险）
 *   08:15   视频 88MB      首包 2.1s     重传 0.2%    RSRP -95     正常
 *   08:31   CSFB Timeout   —            —            SINR -3↓     语音回落失败
 *
 * 【为什么用表格而不是图表】
 *   结论需要「同一时刻四列同时可见」。折线图能看趋势，但四列四个量纲
 *   放一张图要么双轴要么归一化，都会把「这一分钟四项同时差」这个关键
 *   信息模糊掉。表格一行一出结论，直接对应投诉里说的「八点十几分」。
 *
 * 【每格可点】
 *   点任意格子 → 弹窗看该分钟该数据源的原始话单行。
 *   这解决了改版前最大的痛点：结论说「08:14 弱覆盖」，用户却没法验证
 *   ——现在一键就能看到支撑那句话的 MR 记录。
 * ========================================================================== */

import { useMemo, useState } from 'react'
import { Space, Table, Tag, Tooltip, Typography } from 'antd'

import { useI18n } from '../i18n'
import { renderI18n } from '../renderI18n'
import DraggableClickModal from './DraggableClickModal'
import { WH } from '../theme'
import {
  hhmm, type TimelineCell, type TimelineRow, type XdrRow,
} from '../pages/vmaxDiagnosisRules'
import { CardBase } from './cards'

const { Text } = Typography

/** 单元格染色：ok / warn / bad 三档，none 表示该源这一分钟没有记录 */
function cellStyle(level: TimelineCell['level']): React.CSSProperties {
  switch (level) {
    case 'bad':
      return { color: WH.danger, fontWeight: 600 }
    case 'warn':
      return { color: WH.warn, fontWeight: 600 }
    case 'ok':
      return { color: WH.text }
    default:
      return { color: WH.textDim }
  }
}

const ROW_BG: Record<TimelineRow['level'], string | undefined> = {
  bad: 'color-mix(in srgb, var(--wh-danger) 7%, transparent)',
  warn: 'color-mix(in srgb, var(--wh-warn) 6%, transparent)',
  ok: undefined,
  none: undefined,
}

/** 下钻弹窗：该分钟该源的原始行（列由行自己决定，避免为空态硬编码表头） */
type DrillState = { minute: string; source: string; rows: XdrRow[] } | null

export default function VmaxEvidenceTimeline({
  rows,
  loading,
}: {
  rows: TimelineRow[]
  loading?: boolean
}) {
  const { t } = useI18n()
  const [drill, setDrill] = useState<DrillState>(null)
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)

  const openDrill = (
    e: React.MouseEvent<HTMLElement>,
    minute: string,
    source: string,
    cell: TimelineCell,
  ) => {
    setAnchor({ x: e.clientX, y: e.clientY })
    setDrill({ minute, source, rows: cell.rows })
  }

  /* 下钻表的列：取前若干条记录的键并集，最多 12 列 ——
     XDR 单表 88 列，全展示会把弹窗撑到不可读。只挑「人真的会看」的列。 */
  const drillColumns = useMemo(() => {
    if (!drill?.rows.length) return []
    const PREFERRED = [
      'start_time', 'btime', 'imsi', 'msisdn', 'service', 'subservice',
      'app_content_name', 'ul_traffic', 'dl_traffic', '$first_resp_delay',
      'dl_avg_rtt', 'ul_avg_rtt', '$tcp_resp_delay', 'ul_retrans_pkt', 'dl_retrans_pkt',
      'interface', 'procedure_type', 'procedure_status', 'request_cause',
      // RAN(32) 的小区列实测叫 `cell`（不是 cellname / cell_name），
      // 两个都留着，换供应商/表结构时不至于又少一列
      'serving_rsrp', 'ulsinr', 'cqi', 'cell', 'cellname',
    ]
    const present = new Set<string>()
    drill.rows.slice(0, 20).forEach((r) => {
      Object.keys(r).forEach((k) => present.add(k))
    })
    const picked = PREFERRED.filter((k) => present.has(k)).slice(0, 12)
    const keys = picked.length ? picked : [...present].slice(0, 8)
    return keys.map((k) => ({
      title: k,
      dataIndex: k,
      key: k,
      ellipsis: true,
      width: k === 'app_content_name' || k === 'procedure_type' ? 170 : 110,
      render: (v: unknown) => (v === '' || v === null || v === undefined
        ? <Text type="secondary">—</Text>
        : String(v)),
    }))
  }, [drill])

  const columns = [
    {
      title: t('vmaxq.tl.time'),
      dataIndex: 'minute',
      key: 'minute',
      width: 76,
      fixed: 'left' as const,
      render: (v: string) => <Text strong style={{ fontSize: 12 }}>{hhmm(v)}</Text>,
    },
    {
      title: t('vmaxq.tl.traffic'),
      key: 'traffic',
      width: 108,
      render: (_: unknown, r: TimelineRow) => (
        <span style={{ ...cellStyle(r.traffic.level), cursor: r.traffic.rows.length ? 'pointer' : 'default' }}
          onClick={(e) => r.traffic.rows.length && openDrill(e, r.minute, '1300', r.traffic)}>
          {renderI18n(t, r.traffic.text)}
        </span>
      ),
    },
    {
      title: t('vmaxq.tl.latency'),
      key: 'latency',
      width: 118,
      render: (_: unknown, r: TimelineRow) => (
        <span style={{ ...cellStyle(r.latency.level), cursor: r.latency.rows.length ? 'pointer' : 'default' }}
          onClick={(e) => r.latency.rows.length && openDrill(e, r.minute, '1300', r.latency)}>
          {renderI18n(t, r.latency.text)}
        </span>
      ),
    },
    {
      title: t('vmaxq.tl.transport'),
      key: 'transport',
      width: 108,
      render: (_: unknown, r: TimelineRow) => (
        <span style={{ ...cellStyle(r.transport.level), cursor: r.transport.rows.length ? 'pointer' : 'default' }}
          onClick={(e) => r.transport.rows.length && openDrill(e, r.minute, '1300', r.transport)}>
          {renderI18n(t, r.transport.text)}
        </span>
      ),
    },
    {
      title: t('vmaxq.tl.radio'),
      key: 'radio',
      width: 150,
      render: (_: unknown, r: TimelineRow) => (
        <span style={{ ...cellStyle(r.radio.level), cursor: r.radio.rows.length ? 'pointer' : 'default' }}
          onClick={(e) => r.radio.rows.length && openDrill(e, r.minute, '32', r.radio)}>
          {renderI18n(t, r.radio.text)}
        </span>
      ),
    },
    {
      title: t('vmaxq.tl.csfb'),
      key: 'voice',
      width: 140,
      render: (_: unknown, r: TimelineRow) => (
        <span style={{ ...cellStyle(r.voice.level), cursor: r.voice.rows.length ? 'pointer' : 'default' }}
          onClick={(e) => r.voice.rows.length && openDrill(e, r.minute, '1100', r.voice)}>
          {renderI18n(t, r.voice.text)}
        </span>
      ),
    },
    {
      title: t('vmaxq.tl.judge'),
      key: 'judge',
      render: (_: unknown, r: TimelineRow) => (
        <Tag
          color={r.level === 'bad' ? 'red' : r.level === 'warn' ? 'orange' : r.level === 'ok' ? 'green' : 'default'}
          style={{ marginInlineEnd: 0 }}
        >
          {renderI18n(t, r.judge)}
        </Tag>
      ),
    },
  ]

  /* 只显示有结论的行：全空的分钟（四个源都没数据）不占用视线。
     但**至少保留一行**，否则用户会以为组件没渲染。 */
  const shown = useMemo(() => {
    const meaningful = rows.filter((r) => r.level !== 'none')
    return meaningful.length ? meaningful : rows.slice(0, 1)
  }, [rows])

  return (
    <CardBase
      title={t('vmaxq.tl.card')}
      extra={(
        <Space size={4}>
          <Text type="secondary" style={{ fontSize: 11 }}>{t('vmaxq.tl.hint')}</Text>
        </Space>
      )}
    >
      {!rows.length && !loading ? (
        <Text type="secondary">{t('vmaxq.tl.empty')}</Text>
      ) : (
        <Table
          rowKey="minute"
          size="small"
          bordered
          loading={loading}
          columns={columns}
          dataSource={shown}
          pagination={shown.length > 30 ? { pageSize: 30, showSizeChanger: false, size: 'small' } : false}
          scroll={{ x: 820 }}
          onRow={(r) => ({
            style: r.level === 'bad' || r.level === 'warn'
              ? { background: ROW_BG[r.level] }
              : undefined,
          })}
        />
      )}

      <DraggableClickModal
        open={!!drill}
        anchor={anchor}
        title={drill ? t('vmaxq.tl.drill', { minute: hhmm(drill.minute), source: drill.source }) : ''}
        onClose={() => setDrill(null)}
      >
        {drill?.rows.length ? (
          <Table<XdrRow & { __k: number }>
            size="small"
            bordered
            columns={drillColumns}
            dataSource={drill.rows.map((r, i) => ({ ...r, __k: i }))}
            rowKey="__k"
            pagination={{ pageSize: 10, size: 'small' }}
            scroll={{ x: 900 }}
          />
        ) : (
          <Tooltip title={t('vmaxq.tl.noRows')}>
            <Text type="secondary">{t('vmaxq.tl.noRows')}</Text>
          </Tooltip>
        )}
      </DraggableClickModal>
    </CardBase>
  )
}
