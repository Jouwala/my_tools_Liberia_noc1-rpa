/* ============================================================================
 * AvailCountyDrillModal.tsx —— 县维度可用率的下钻弹窗
 * ----------------------------------------------------------------------------
 * 三层下钻的第二、三层：
 *   county_sites  某县某制式的站点明细（点站点 -> 逐日）
 *   site_daily    某站点的逐日明细（2G/3G/4G 三列）
 *   tt            该县的 TT 工单明细
 *
 * 抽出来的理由：弹窗是「独立交互区域」，它只关心 drill 数据与 target，
 * 与主页面的取数/筛选状态无关。独立成组件后主页面文件回到 500 行以内，
 * 且弹窗的行为可以单独读、单独改。
 * ========================================================================== */
import { Alert, Button, Empty, Space, Spin, Table, Tabs, Tag } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import DraggableClickModal from '../../components/DraggableClickModal'
import {
  Drill, DrillLevel, SiteDailyRow, SiteRow, TtRow,
} from './availCountyTypes'

export interface AvailCountyDrillModalProps {
  open: boolean
  anchor: { x: number; y: number } | null
  target: { county: string; tech: string; label: string } | null
  drill: Drill | null
  drillLoading: boolean
  modalTab: DrillLevel
  onClose: () => void
  onTabChange: (lv: DrillLevel) => void
  onSiteClick: (row: SiteRow) => void
  onExport: () => void
  /** 警告码 -> i18n 键；null = 该码没有对应文案（跳过） */
  warnKey: (code: string) => string | null
  /** 警告码 -> 是否是错误级（红）还是提示级（黄） */
  isErrorWarn: (code: string) => boolean
  t: (key: string, params?: Record<string, string | number>) => string
  /** 站点明细列（含「点站点 -> 逐日」的回调） */
  drillSiteCols: ColumnsType<SiteRow>
  drillDailyCols: ColumnsType<SiteDailyRow>
  drillTtCols: ColumnsType<TtRow>
}

export default function AvailCountyDrillModal(props: AvailCountyDrillModalProps) {
  const {
    open, anchor, target, drill, drillLoading, modalTab,
    onClose, onTabChange, onSiteClick, onExport,
    warnKey, isErrorWarn, t,
    drillSiteCols, drillDailyCols, drillTtCols,
  } = props

  const warnAlerts = (codes: string[], err?: string) => (
    <Space direction="vertical" style={{ width: '100%' }} size={4}>
      {codes.map((code, i) => {
        const k = warnKey(code)
        if (!k) return null
        return (
          <Alert key={`${code}-${i}`} type={isErrorWarn(code) ? 'error' : 'warning'} showIcon
            message={t(k)} description={isErrorWarn(code) && err ? err : undefined} />
        )
      })}
    </Space>
  )

  return (
    <DraggableClickModal
      open={open}
      title={target?.label || t('availCounty.drillTitle')}
      anchor={anchor}
      onClose={onClose}
    >
      <Space wrap style={{ marginBottom: 'var(--wh-space-sm)' }}>
        <Tag color="blue">{t('availCounty.drillCount', { n: drill?.meta?.total ?? 0 })}</Tag>
        {drill?.meta?.truncated && (
          <Tag color="orange">{t('availCounty.truncated')}</Tag>
        )}
        <Button
          size="small"
          icon={<DownloadOutlined />}
          onClick={onExport}
          disabled={!drill?.rows?.length}
        >
          {t('common.exportExcel')}
        </Button>
      </Space>

      {drill?.meta?.warnings?.length ? (
        <div style={{ marginBottom: 'var(--wh-space-sm)' }}>
          {warnAlerts(drill.meta.warnings, drill.meta.error)}
        </div>
      ) : null}

      <Tabs
        activeKey={modalTab}
        onChange={k => onTabChange(k as DrillLevel)}
        size="small"
        items={[
          { key: 'county_sites', label: t('availCounty.tabSites') },
          { key: 'site_daily', label: t('availCounty.tabDaily') },
          { key: 'tt', label: t('availCounty.tabTt') },
        ]}
      />

      {drillLoading ? (
        <div style={{ padding: 'var(--wh-space-lg)', textAlign: 'center' }}><Spin /></div>
      ) : modalTab === 'county_sites' ? (
        <Table
          rowKey={(r: SiteRow) => r.site_key}
          size="small"
          columns={drillSiteCols}
          dataSource={(drill?.rows || []) as SiteRow[]}
          pagination={{ pageSize: 12, showSizeChanger: true }}
          scroll={{ x: 760 }}
        />
      ) : modalTab === 'site_daily' ? (
        <Table
          rowKey={(r: SiteDailyRow) => r.day}
          size="small"
          columns={drillDailyCols}
          dataSource={(drill?.rows || []) as SiteDailyRow[]}
          pagination={false}
          scroll={{ x: 560 }}
        />
      ) : (
        <Table
          rowKey={(r: TtRow) => r.tt_no}
          size="small"
          columns={drillTtCols}
          dataSource={(drill?.rows || []) as TtRow[]}
          pagination={{ pageSize: 12, showSizeChanger: true }}
          scroll={{ x: 1300 }}
          locale={{ emptyText: <Empty description={t('common.noData')} /> }}
        />
      )}
    </DraggableClickModal>
  )
}
