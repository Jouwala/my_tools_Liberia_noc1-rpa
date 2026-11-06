/* ============================================================================
 * VmaxWorkspaceVerdict —— 区域 3 根因与处理建议（CCA 工作台）
 * ============================================================================
 * 回答最终判断：根因候选 / 建议排查层级 / 待补证据 / Action Plan 任务，
 * 全部规则模板，无 LLM。
 * ========================================================================== */

import { Button, Space, Table, Typography } from 'antd'

import { useI18n } from '../../i18n'
import { renderI18n } from '../../renderI18n'
import { CardBase } from '../cards'
import type { ChainNode, RankedCause, Recommendation } from '../../lib/vmaxWorkspaceRules'

const { Text } = Typography

const NODE_KEY: Record<ChainNode, string> = {
  terminal: 'vmaxq.ws.chain.terminal',
  ran: 'vmaxq.ws.chain.ran',
  transport: 'vmaxq.ws.chain.transport',
  core: 'vmaxq.ws.chain.core',
  ott: 'vmaxq.ws.chain.ott',
}

export default function VmaxWorkspaceVerdict({
  rankedCauses, recommendations,
  onOpenEvidence,
}: {
  rankedCauses: RankedCause[]
  recommendations: Recommendation[]
  onOpenEvidence: (kind: 'xdr' | 'records' | 'radio' | 'flow' | 'cca') => void
}) {
  const { t } = useI18n()
  const causeColumns = [
    { title: t('vmaxq.ws.cause.label'), dataIndex: 'label', ellipsis: true },
    { title: t('vmaxq.ws.cause.confidence'), dataIndex: 'confidence', width: 100,
      render: (v: number) => `${v}%` },
    { title: t('vmaxq.ws.cause.support'), dataIndex: 'crossSupport', width: 120,
      render: (v: number) => `${Math.round(v * 100)}%` },
    { title: t('vmaxq.cause.detail'), width: 90, render: () => (
      <Button size="small" type="link" onClick={() => onOpenEvidence('cca')}>
        {t('vmaxq.ws.evidence.open')}
      </Button>
    ) },
  ]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
      <CardBase title={t('vmaxq.ws.zone3.title')}>
        {rankedCauses.length ? (
          <Table
            size="small"
            rowKey="id"
            columns={causeColumns}
            dataSource={rankedCauses}
            pagination={false}
            scroll={{ x: 600 }}
          />
        ) : (
          <Text type="secondary">{t('vmaxq.ws.cause.empty')}</Text>
        )}
      </CardBase>

      <CardBase title={t('vmaxq.ws.rec.title')}>
        {recommendations.length ? recommendations.map((r) => (
          <div key={r.id} style={{ marginBottom: 8 }}>
            <Text strong style={{ fontSize: 12 }}>{t(NODE_KEY[r.node])}</Text>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {/* sugg 留空（null）时沿用结论卡的 verdict.suggestion；这里只渲染证据与任务两段 */}
              {r.needEvidence && (
                <Text style={{ fontSize: 12 }}>· {renderI18n(t, r.needEvidence)}</Text>
              )}
              {r.action && (
                <Text style={{ fontSize: 12 }}>· {renderI18n(t, r.action)}</Text>
              )}
            </div>
          </div>
        )) : (
          <Text type="secondary">{t('vmaxq.ws.rec.empty')}</Text>
        )}
        <Space size={6} wrap>
          <Button size="small" onClick={() => onOpenEvidence('xdr')}>{t('vmaxq.ws.evidence.xdr')}</Button>
          <Button size="small" onClick={() => onOpenEvidence('records')}>{t('vmaxq.ws.evidence.radio')}</Button>
          <Button size="small" onClick={() => onOpenEvidence('flow')}>{t('vmaxq.ws.evidence.tcp')}</Button>
          <Button size="small" onClick={() => onOpenEvidence('cca')}>{t('vmaxq.ws.evidence.cca')}</Button>
        </Space>
      </CardBase>
    </div>
  )
}
