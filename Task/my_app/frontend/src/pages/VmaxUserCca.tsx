/* ============================================================================
 * VmaxUserCca —— VMAX 智能诊断工作台（Intelligent Diagnosis Workspace）
 * ============================================================================
 *
 * 2026-11-07 新建，与旧页 VmaxUserQuery（?page=vmax_user_query）**并存**：
 * 旧页保持「按数据源分视图」的查询工具形态，本页是投诉驱动的单页叙事：
 *
 *   区域 1 故障概览   —— 用户到底出了什么问题（一句话 + 四维分）
 *   区域 2 故障分析   —— 问题在哪层（terminal→ran→transport→core→ott 链路）
 *                        + 五段可解释指标 + 专卡 + 流量 + 时间线
 *   区域 3 根因与建议  —— 根因候选（CCA 关联证据）+ 模板建议 + 证据库
 *
 * 设计原则（用户 2026-11-07）：
 *   - 系统先给答案，用户沿证据深入（原始 XDR / 无线原始 / TCP 只在点证据时加载）
 *   - 无数据 ≠ 正常（unknown 优先于 ok）
 *   - 跨模块关联：单 TCP 重传不直接定无线问题
 *
 * 取数与计算复用 pages/useVmaxDiagnosis.ts（与旧页同源：抽取时只搬逻辑不改
 * 行为）；URL 命名空间 cca*，与旧页 msisdn/vmaxView/complaint/vq* 零冲突；
 * 结论由 vmaxDiagnosisRules.buildVerdict 原样产出，本页不篡改。
 * ========================================================================== */

import { useMemo, useState } from 'react'
import { Alert, Button, DatePicker, Input, Space, Typography } from 'antd'
import { MobileOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'

import { useI18n } from '../i18n'
import { CardBase } from '../components/cards'
import VmaxComplaintTabs from '../components/VmaxComplaintTabs'
import VmaxCcaCards, { type CauseItem, type CellRecord } from '../components/VmaxCcaCards'
import DraggableClickModal from '../components/DraggableClickModal'
import { Table, Descriptions, Tag } from 'antd'
import {
  disabledRangeProps, PAGE_RETENTION_HOURS, clampRange,
} from './vmaxWindow'
import { VmaxWindowContext } from './vmaxWindowContext'
import { CCA_NS, useVmaxDiagnosis } from './useVmaxDiagnosis'
import { buildWorkspaceCorrelation } from '../lib/vmaxWorkspaceRules'
import VmaxWorkspaceOverview from '../components/vmax/VmaxWorkspaceOverview'
import VmaxWorkspaceAnalysis from '../components/vmax/VmaxWorkspaceAnalysis'
import VmaxWorkspaceVerdict from '../components/vmax/VmaxWorkspaceVerdict'
import VmaxEvidenceDrawer, { type EvidenceKind } from '../components/vmax/VmaxEvidenceDrawer'
import VmaxDiagnosisCard from '../components/VmaxDiagnosisCard'
import VmaxOverrideModal from '../components/VmaxOverrideModal'
import { renderI18n } from '../renderI18n'

const { Text } = Typography
const { RangePicker } = DatePicker

type KpiItem = { code: string; name: string; value: unknown }

const fmt = (v: unknown) => (v == null || v === '' || v === '--' ? '—' : String(v))

export default function VmaxUserCca() {
  const { t } = useI18n()
  const d = useVmaxDiagnosis(CCA_NS)

  const [drawer, setDrawer] = useState<{ kind: EvidenceKind | null; open: boolean }>({
    kind: null, open: false,
  })
  const openDrawer = (kind: EvidenceKind) => setDrawer({ kind, open: true })

  const [kpiOpen, setKpiOpen] = useState(false)
  const [kpiCell, setKpiCell] = useState<CellRecord | null>(null)
  const [kpiItems, setKpiItems] = useState<KpiItem[]>([])
  const [kpiAnchor, setKpiAnchor] = useState<{ x: number; y: number } | null>(null)
  const [causeOpen, setCauseOpen] = useState(false)
  const [causeItem, setCauseItem] = useState<CauseItem | null>(null)

  const ws = useMemo(() => buildWorkspaceCorrelation({
    payload: d.diag,
    sources: d.sources,
    scores: d.scores,
    voice: d.voice,
    ott: d.ott,
    game: d.game,
    radio: d.radio,
    timeline: d.timeline,
    cca: d.result,
    complaint: d.complaint,
  }), [d.diag, d.sources, d.scores, d.voice, d.ott, d.game, d.radio, d.timeline, d.result, d.complaint])

  const rangePickerProps = disabledRangeProps(PAGE_RETENTION_HOURS)
  const ctxValue = {
    range: d.range, setRange: d.setRange,
    retentionHours: PAGE_RETENTION_HOURS, query: d.query,
  }

  const kpiColumns = [
    { title: t('vmaxq.kpiName'), dataIndex: 'name', ellipsis: true },
    { title: t('vmaxq.kpiValue'), dataIndex: 'value', width: 110, align: 'right' as const, render: fmt },
    { title: t('vmaxq.kpiCode'), dataIndex: 'code', width: 150, ellipsis: true },
  ]

  return (
    <VmaxWindowContext.Provider value={ctxValue}>
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap>
          <Input
            allowClear
            prefix={<MobileOutlined style={{ color: 'var(--wh-text-dim)' }} />}
            placeholder={t('vmaxq.inputPlaceholder')}
            value={d.msisdn}
            onChange={(e) => d.setMsisdn(e.target.value)}
            onPressEnter={() => void d.run(d.msisdn)}
            style={{ width: 240 }}
            maxLength={24}
          />
          <RangePicker
            value={d.range}
            onChange={(v) => {
              if (v && v[0] && v[1]) d.setRange(clampRange([v[0], v[1]]))
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
            loading={d.diagLoading || d.loading}
            onClick={() => void d.run(d.msisdn)}
          >
            {t('vmaxq.search')}
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxq.ws.queryHint')}</Text>
        </Space>
      </CardBase>

      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <VmaxComplaintTabs
          value={d.complaint}
          onChange={d.setComplaint}
          disabled={!d.anyData}
        />
      </CardBase>

      {!!d.diagError && (
        <Alert
          type="error" showIcon message={d.diagError}
          action={<Button size="small" icon={<ReloadOutlined />} onClick={d.refresh}>{t('vmaxq.retry')}</Button>}
        />
      )}

      <VmaxWorkspaceOverview
        verdict={d.verdict}
        scores={d.scores}
        loading={d.diagLoading}
      />

      <VmaxWorkspaceAnalysis
        metrics={ws.metrics}
        chain={ws.chain}
        complaint={d.complaint}
        voice={d.voice}
        ott={d.ott}
        game={d.game}
        timeline={ws.enrichedTimeline}
        radio={d.radio}
        flowXdr={d.flowXdr}
        scores={d.scores}
        cca={d.result}
        loading={d.diagLoading}
        onOpenEvidence={openDrawer}
      />

      <VmaxWorkspaceVerdict
        rankedCauses={ws.rankedCauses}
        recommendations={ws.recommendations}
        onOpenEvidence={openDrawer}
      />

      <VmaxDiagnosisCard
        payload={d.diag}
        scores={d.scores}
        verdict={d.verdict}
        complaint={d.complaint}
        loading={d.diagLoading}
        error={d.diagError}
        overrides={d.override}
        onOverride={() => d.setOverrideOpen(true)}
        onExportExcel={() => undefined}
        onExportPdf={() => undefined}
        onRefresh={d.refresh}
      />

      {!!d.error && (
        <Alert type="error" showIcon message={d.error}
          action={<Button size="small" icon={<ReloadOutlined />} onClick={d.refresh}>{t('vmaxq.retry')}</Button>} />
      )}
      {!d.loading && !d.error && d.result?.found && (
        <VmaxCcaCards
          result={d.result}
          onOpenKpi={(cell) => {
            setKpiCell(cell)
            setKpiItems(d.result?.cells?.cell_kpi?.[String(cell.cell)] || [])
            setKpiOpen(true)
          }}
          onOpenCause={(item) => { setCauseItem(item); setCauseOpen(true) }}
        />
      )}

      <VmaxEvidenceDrawer
        kind={drawer.kind}
        open={drawer.open}
        onClose={() => setDrawer((s) => ({ ...s, open: false }))}
        msisdn={d.msisdn}
        ctx={ctxValue}
        radio={d.radio}
        diagLoading={d.diagLoading}
        flowXdr={d.flowXdr}
      />

      <VmaxOverrideModal
        open={d.overrideOpen}
        autoVerdict={d.verdict ? renderI18n(t, d.verdict.headline) : ''}
        existing={d.override}
        saving={d.overrideSaving}
        onCancel={() => d.setOverrideOpen(false)}
        onSubmit={(v, r) => void d.submitOverride(v, r)}
        onRevoke={() => void d.revokeOverride()}
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

      <DraggableClickModal
        open={causeOpen}
        title={causeItem?.rule_name || t('vmaxq.causesCard')}
        onClose={() => setCauseOpen(false)}
      >
        {causeItem && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 380 }}>
            <Descriptions size="small" bordered column={1} items={[
              { key: 'conf', label: t('vmaxq.cause.confidence'),
                children: <Tag color={causeItem.confidence >= 90 ? 'red' : 'orange'}>{causeItem.confidence}%</Tag> },
              { key: 'obj', label: t('vmaxq.cause.object'),
                children: `${causeItem.object_name}（${causeItem.object_type}）` },
              { key: 'area', label: t('vmaxq.cause.area'),
                children: [causeItem.province, causeItem.city, causeItem.vendor].filter(Boolean).join(' / ') || '—' },
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
                  rowKey={(r) => r.clttime + r.judge}
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
