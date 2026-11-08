/* ============================================================================
 * VmaxEvidenceDrawer —— 原始证据抽屉（CCA 工作台，懒挂载）
 * ============================================================================
 * 首屏只取诊断 + CCA + flow 摘要；用户点「查看证据」才挂载对应原始面板，
 * 关闭即卸载。抽屉作用域独立 Provider，值由页面 query 派生；
 * XDR 面板 URL 键以 cca 前缀避免与旧页 mxSvc/rtSvc/rtTable 互踩。
 *
 * ⚠ 参数前缀不在面板组件内改（真并行踩键靠 Provider token 隔离，参见
 *    VmaxXdrPanel:144-154 以 ctx.query.token 决定，并行取数不读 URL 键）：
 *    面板各自用 token 触发，抽屉开/关决定挂载，关闭即卸载后不再发请求。
 *
 * 2026-11-07（P0-3/P0-4）：cca 分支此前错挂 VmaxXdrRecordsPanel（与
 * 「无线原始」同面板），现换成 VmaxCcaEvidencePanel（KPI/根因弹窗自包含）；
 * 清掉底部隐藏 span（为「读 token 触发重取」留的占位，接线从未完成）。
 * EvidenceKind 类型从 vmaxWorkspaceRules 下沉后此处直接复用。
 * ========================================================================== */

import { Drawer } from 'antd'

import { useI18n } from '../../i18n'
import { VmaxWindowContext, type VmaxWindowValue } from '../../pages/vmaxWindowContext'
import { PAGE_RETENTION_HOURS } from '../../pages/vmaxWindow'
import type { RadioAnalysis } from '../../pages/vmaxDiagnosisRules'
import type { CcaResult } from '../VmaxCcaCards'
import type { FlowData } from '../VmaxFlowCategoryTabs'
import type { EvidenceKind } from '../../lib/vmaxWorkspaceRules'
import VmaxXdrPanel from '../VmaxXdrPanel'
import VmaxXdrRecordsPanel from '../VmaxXdrRecordsPanel'
import VmaxRadioPanel from '../VmaxRadioPanel'
import VmaxFlowCategoryTabs from '../VmaxFlowCategoryTabs'
import VmaxCcaEvidencePanel from './VmaxCcaEvidencePanel'

export type { EvidenceKind }

export default function VmaxEvidenceDrawer({
  kind, open, onClose, msisdn, ctx, radio, diagLoading, flowXdr, cca,
}: {
  kind: EvidenceKind | null
  open: boolean
  onClose: () => void
  msisdn: string
  ctx: VmaxWindowValue
  radio: RadioAnalysis | null
  diagLoading: boolean
  flowXdr: FlowData | null
  /** CCA 查询结果（cca 面板用；页面已有，不重取） */
  cca: CcaResult | null
}) {
  const { t } = useI18n()
  const titleKey = kind === 'xdr' ? 'vmaxq.ws.drawer.xdr'
    : kind === 'records' ? 'vmaxq.ws.drawer.records'
    : kind === 'radio' ? 'vmaxq.ws.drawer.radio'
    : kind === 'flow' ? 'vmaxq.ws.drawer.flow'
    : 'vmaxq.ws.drawer.cca'

  const value: VmaxWindowValue = {
    ...ctx,
    retentionHours: PAGE_RETENTION_HOURS,
  }

  return (
    <Drawer
      placement="right"
      width="min(95vw, 72rem)"
      open={open}
      onClose={onClose}
      title={titleKey ? t(titleKey) : t('vmaxq.ws.drawer.title')}
      destroyOnHidden
    >
      {/* 抽屉内独立 Provider：子面板靠 ctx.query.token 决定并行取数;
          关闭即 destroyOnHidden 卸载，不再发请求。 */}
      <VmaxWindowContext.Provider value={value}>
        {kind === 'xdr' && <VmaxXdrPanel msisdn={msisdn} />}
        {kind === 'records' && <VmaxXdrRecordsPanel msisdn={msisdn} />}
        {kind === 'radio' && (
          <VmaxRadioPanel analysis={radio} loading={diagLoading} msisdn={msisdn} />
        )}
        {kind === 'flow' && <VmaxFlowCategoryTabs flow={flowXdr} />}
        {kind === 'cca' && <VmaxCcaEvidencePanel result={cca} />}
      </VmaxWindowContext.Provider>
    </Drawer>
  )
}
