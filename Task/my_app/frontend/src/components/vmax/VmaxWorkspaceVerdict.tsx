/* ============================================================================
 * VmaxWorkspaceVerdict —— 区域 3 根因与处理建议（CCA 工作台）
 * ============================================================================
 * 回答最终判断：根因候选 / 建议排查层级 / 待补证据 / Action Plan 任务，
 * 全部规则模板，无 LLM。
 *
 * 2026-11-07：根因排行表的「详情」直接打开 VmaxCauseDetailModal（锚定点击处），
 * 不再绕道证据抽屉；并新增 ccaError / ccaLoading —— CCA 查询失败常驻红条
 * （AGENTS.md 第四节第 10 条：说「这次算不全」→ 常驻），与「未发现根因」
 * 这两种空表含义严格分开，用户不会再把失败读成「没问题」。
 * ========================================================================== */

import { useState } from 'react'
import { Alert, Button, Space, Table, Typography } from 'antd'

import { useI18n } from '../../i18n'
import { renderI18n } from '../../renderI18n'
import { CardBase } from '../cards'
import type { CauseItem } from '../VmaxCcaCards'
import type { EvidenceKind, RankedCause, Recommendation } from '../../lib/vmaxWorkspaceRules'
import { CHAIN_NODE_KEY } from '../../lib/vmaxWorkspaceRules'
import VmaxCauseDetailModal from './VmaxCauseDetailModal'

const { Text } = Typography

export default function VmaxWorkspaceVerdict({
  rankedCauses, recommendations, ccaError, ccaLoading,
  diagLoading, diagLoaded, diagTotal, onOpenEvidence,
}: {
  rankedCauses: RankedCause[]
  recommendations: Recommendation[]
  /** CCA 根因查询失败原因（空 = 成功）。失败时常驻红条，区别于「无根因」 */
  ccaError?: string
  /** CCA 根因查询进行中 */
  ccaLoading?: boolean
  /* ---- P3-1 渐进渲染（2026-11-07）----
   * 四个源串行 ≈21s，先回来的只有一部分。此期间**不出结论**：
   *   - 根因排行的 crossSupport 是从「四维分」算的，半份数据会给出错的关联强度；
   *   - 建议是按链路最差节点推的，半份数据可能指向错误层级。
   * 所以此时两张表都换成「取数进度」文案，避免用户把「还没取完」读成「没问题」。 */
  diagLoading?: boolean
  diagLoaded?: number
  diagTotal?: number
  onOpenEvidence: (kind: EvidenceKind) => void
}) {
  const { t } = useI18n()
  const [detailItem, setDetailItem] = useState<CauseItem | null>(null)
  const [detailAnchor, setDetailAnchor] = useState<{ x: number; y: number } | null>(null)

  /** 取数进度（与「CCA 查询中」区分：那是另一个请求） */
  const diagProgress = t('vmaxq.ws.cause.diagLoading', {
    n: diagLoaded ?? 0, total: diagTotal ?? 4,
  })

  const causeColumns = [
    { title: t('vmaxq.ws.cause.label'), dataIndex: 'label', ellipsis: true },
    { title: t('vmaxq.ws.cause.confidence'), dataIndex: 'confidence', width: 100,
      render: (v: number) => `${v}%` },
    { title: t('vmaxq.ws.cause.support'), dataIndex: 'crossSupport', width: 120,
      render: (v: number) => `${Math.round(v * 100)}%` },
    { title: t('vmaxq.cause.detail'), width: 90, render: (_: unknown, r: RankedCause) => (
      r.cause ? (
        <Button size="small" type="link" onClick={(e) => {
          setDetailAnchor({ x: e.clientX, y: e.clientY })
          setDetailItem(r.cause)
        }}>
          {t('vmaxq.cause.detail')}
        </Button>
      ) : null
    ) },
  ]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
      <CardBase title={t('vmaxq.ws.zone3.title')}>
        {/* CCA 查询失败：常驻可见（不是口径解释，是「这次没算出来」） */}
        {!!ccaError && (
          <Alert
            type="error" showIcon style={{ marginBottom: 8 }}
            message={t('vmaxq.ws.cause.queryFail')}
            description={ccaError}
          />
        )}
        {diagLoading ? (
          <Text type="secondary">{diagProgress}</Text>
        ) : rankedCauses.length ? (
          <Table
            size="small"
            rowKey="id"
            loading={ccaLoading}
            columns={causeColumns}
            dataSource={rankedCauses}
            pagination={false}
            scroll={{ x: 600 }}
          />
        ) : (
          <Text type="secondary">
            {ccaLoading ? t('vmaxq.ws.cause.loading') : t('vmaxq.ws.cause.empty')}
          </Text>
        )}
      </CardBase>

      <CardBase title={t('vmaxq.ws.rec.title')}>
        {diagLoading ? (
          <Text type="secondary">{diagProgress}</Text>
        ) : recommendations.length ? recommendations.map((r) => (
          <div key={r.id} style={{ marginBottom: 8 }}>
            <Text strong style={{ fontSize: 12 }}>{t(CHAIN_NODE_KEY[r.node])}</Text>
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

      <VmaxCauseDetailModal
        open={!!detailItem}
        item={detailItem}
        anchor={detailAnchor}
        onClose={() => setDetailItem(null)}
      />
    </div>
  )
}
