/* 拓扑工具条：层 / 布局 / 着色 / 搜索 / 过滤 / 缩放。文案全部走 i18n。 */
import { Button, Input, Segmented, Select, Space, Switch } from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'

import { WH } from '../../theme'
import { useI18n } from '../../i18n'
import { CardBase } from '../../components/cards'
import { LAYER_KEYS, LAYER_LABEL_KEY } from './layerDefs'
import type { ColorMode, LayerKey, LayoutKey, Tier } from './types'

export type TierFilter = 'all' | Tier
export type StatusFilter = 'all' | 'up' | 'down' | 'alarm'

interface Props {
  layer: LayerKey
  onLayer: (k: LayerKey) => void
  layoutKey: LayoutKey
  onLayout: (k: LayoutKey) => void
  colorMode: ColorMode
  onColor: (k: ColorMode) => void
  showAllLabels: boolean
  onAllLabels: (v: boolean) => void
  foldParallel: boolean
  onFold: (v: boolean) => void
  loading: boolean
  onRefresh: () => void
  onExport: () => void
  canExport: boolean
  metaLine: string | null
  query: string
  onQuery: (v: string) => void
  onLocate: () => void
  tierFilter: TierFilter
  onTier: (v: TierFilter) => void
  statusFilter: StatusFilter
  onStatus: (v: StatusFilter) => void
  onZoomIn: () => void
  onZoomOut: () => void
  onFit: () => void
}

export default function TopologyControls(p: Props) {
  const { t } = useI18n()
  const tierName = (tier: Tier) => {
    switch (tier) {
      case 0: return t('ipranTopo.tier.0')
      case 1: return t('ipranTopo.tier.1')
      case 2: return t('ipranTopo.tier.2')
      default: return t('ipranTopo.tier.3')
    }
  }
  return (
    <>
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap size={12} align="center">
          <span style={{ color: WH.textMuted, fontSize: 13 }}>{t('ipranTopo.toolbar.layer')}</span>
          <Segmented className="wh-seg" size="small" value={p.layer}
            onChange={(v) => p.onLayer(v as LayerKey)}
            options={LAYER_KEYS.map((k) => ({ label: t(LAYER_LABEL_KEY[k]), value: k }))} />
          <span style={{ color: WH.textDim, fontSize: 12 }}>{t('ipranTopo.layer.hint')}</span>
        </Space>
      </CardBase>
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap size={12} align="center">
          <span style={{ color: WH.textMuted, fontSize: 13 }}>{t('ipranTopo.toolbar.layout')}</span>
          <Segmented className="wh-seg" size="small" value={p.layoutKey}
            onChange={(v) => p.onLayout(v as LayoutKey)}
            options={[
              { label: t('ipranTopo.layout.force'), value: 'force' },
              { label: t('ipranTopo.layout.geo'), value: 'geo' },
              { label: t('ipranTopo.layout.tier'), value: 'tier' },
            ]} />
          <span style={{ color: WH.textMuted, fontSize: 13 }}>{t('ipranTopo.toolbar.color')}</span>
          <Segmented className="wh-seg" size="small" value={p.colorMode}
            onChange={(v) => p.onColor(v as ColorMode)}
            options={[
              { label: t('ipranTopo.color.tier'), value: 'tier' },
              { label: t('ipranTopo.color.up'), value: 'up' },
              { label: t('ipranTopo.color.sev'), value: 'sev' },
            ]} />
          <Switch size="small" checked={p.showAllLabels} onChange={p.onAllLabels}
            checkedChildren={t('ipranTopo.opt.allLabels')} unCheckedChildren={t('ipranTopo.opt.allLabels')} />
          <Switch size="small" checked={p.foldParallel} onChange={p.onFold}
            checkedChildren={t('ipranTopo.opt.fold')} unCheckedChildren={t('ipranTopo.opt.fold')} />
          <Button size="small" onClick={p.onZoomIn}>{t('ipranTopo.btn.zoomIn')}</Button>
          <Button size="small" onClick={p.onZoomOut}>{t('ipranTopo.btn.zoomOut')}</Button>
          <Button size="small" onClick={p.onFit}>{t('ipranTopo.btn.fit')}</Button>
          <Button icon={<ReloadOutlined />} loading={p.loading} onClick={p.onRefresh}>{t('ipranTopo.btn.refresh')}</Button>
          <Button icon={<DownloadOutlined />} disabled={!p.canExport} onClick={p.onExport}>{t('ipranTopo.btn.export')}</Button>
          {p.metaLine && <span style={{ color: WH.textDim, fontSize: 12 }}>{p.metaLine}</span>}
        </Space>
      </CardBase>
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap size={12} align="center">
          <Input.Search allowClear size="small" style={{ width: 240 }}
            placeholder={t('ipranTopo.toolbar.searchPh')}
            value={p.query} onChange={(e) => p.onQuery(e.target.value)} onSearch={p.onLocate} />
          <span style={{ color: WH.textMuted, fontSize: 13 }}>{t('ipranTopo.toolbar.filterTier')}</span>
          <Select size="small" style={{ width: 140 }} value={p.tierFilter}
            onChange={(v) => p.onTier(v)}
            options={[
              { value: 'all', label: t('ipranTopo.filter.all') },
              { value: 0, label: tierName(0) },
              { value: 1, label: tierName(1) },
              { value: 2, label: tierName(2) },
              { value: 3, label: tierName(3) },
            ]} />
          <span style={{ color: WH.textMuted, fontSize: 13 }}>{t('ipranTopo.toolbar.filterStatus')}</span>
          <Select size="small" style={{ width: 140 }} value={p.statusFilter}
            onChange={(v) => p.onStatus(v)}
            options={[
              { value: 'all', label: t('ipranTopo.filter.all') },
              { value: 'up', label: t('ipranTopo.filter.up') },
              { value: 'down', label: t('ipranTopo.filter.down') },
              { value: 'alarm', label: t('ipranTopo.filter.alarm') },
            ]} />
        </Space>
      </CardBase>
    </>
  )
}
