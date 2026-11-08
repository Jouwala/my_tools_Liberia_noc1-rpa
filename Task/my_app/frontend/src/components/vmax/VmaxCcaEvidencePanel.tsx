/* ============================================================================
 * VmaxCcaEvidencePanel —— 证据抽屉里的「CCA 画像」面板
 * ============================================================================
 * 2026-11-07 新建（P0-3）：此前抽屉的 cca 分支错挂了 VmaxXdrRecordsPanel
 * （与「无线原始」同一个面板），按钮承诺 CCA 证据、打开的却是 XDR 详单。
 * 现在承载真正的 CCA 结果：用户/终端/小区（含 KPI 弹窗）/根因（含详情
 * 弹窗）。KPI 与根因两个弹窗在此自包含 —— 抽屉是懒挂载的独立作用域，
 * 不能依赖页面级状态。
 * ========================================================================== */

import { useState } from 'react'
import { Typography } from 'antd'

import { useI18n } from '../../i18n'
import type { CauseItem, CellRecord, CcaResult } from '../VmaxCcaCards'
import VmaxCcaCards from '../VmaxCcaCards'
import VmaxCauseDetailModal from './VmaxCauseDetailModal'
import DraggableClickModal from '../DraggableClickModal'
import { Table } from 'antd'

const { Text } = Typography

type KpiItem = { code: string; name: string; value: unknown }

const fmt = (v: unknown) => (v == null || v === '' || v === '--' ? '—' : String(v))

export default function VmaxCcaEvidencePanel({ result }: { result: CcaResult | null }) {
  const { t } = useI18n()

  const [kpiOpen, setKpiOpen] = useState(false)
  const [kpiCell, setKpiCell] = useState<CellRecord | null>(null)
  const [kpiItems, setKpiItems] = useState<KpiItem[]>([])
  const [kpiAnchor, setKpiAnchor] = useState<{ x: number; y: number } | null>(null)
  const [causeItem, setCauseItem] = useState<CauseItem | null>(null)
  const [causeAnchor, setCauseAnchor] = useState<{ x: number; y: number } | null>(null)

  if (!result) {
    return <Text type="secondary">{t('vmaxq.ws.cause.noData')}</Text>
  }

  const kpiColumns = [
    { title: t('vmaxq.kpiName'), dataIndex: 'name', ellipsis: true },
    { title: t('vmaxq.kpiValue'), dataIndex: 'value', width: 110, align: 'right' as const, render: fmt },
    { title: t('vmaxq.kpiCode'), dataIndex: 'code', width: 150, ellipsis: true },
  ]

  return (
    <>
      <VmaxCcaCards
        result={result}
        onOpenKpi={(cell, e) => {
          setKpiAnchor(e ? { x: e.clientX, y: e.clientY } : null)
          setKpiCell(cell)
          setKpiItems(result.cells?.cell_kpi?.[String(cell.cell)] || [])
          setKpiOpen(true)
        }}
        onOpenCause={(item, e) => {
          setCauseAnchor(e ? { x: e.clientX, y: e.clientY } : null)
          setCauseItem(item)
        }}
      />

      <DraggableClickModal
        open={kpiOpen}
        title={`${t('vmaxq.kpiTitle')} · ${kpiCell?.cellname || kpiCell?.cellkey || ''}`}
        anchor={kpiAnchor}
        onClose={() => setKpiOpen(false)}
      >
        {kpiItems.length ? (
          <Table
            rowKey={(r) => r.code}
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

      <VmaxCauseDetailModal
        open={!!causeItem}
        item={causeItem}
        anchor={causeAnchor}
        onClose={() => setCauseItem(null)}
      />
    </>
  )
}
