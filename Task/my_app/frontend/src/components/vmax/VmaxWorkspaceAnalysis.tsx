/* ============================================================================
 * VmaxWorkspaceAnalysis —— 区域 2 故障分析（CCA 工作台）
 * ============================================================================
 * 问题发生在哪里、为什么：
 *   - 端到端链路条 terminal → ran → transport → core → ott，
 *     节点状态取 metrics 最差值（unknown 优先于 ok，避免「缺数据=正常」）；
 *   - 链路下挂五段 ExplainableMetric；
 *   - 专卡（语音/OTT/游戏）按投诉类型置顶，其余折叠摘要；
 *   - 流量分类与证据时间线直接内嵌（同一批 rows，不重取）。
 * ========================================================================== */

import { Collapse, Space, Tag, Typography } from 'antd'

import { useI18n } from '../../i18n'
import { CardBase } from '../cards'
import { CHAIN_NODE_KEY, type ChainStatus, type EvidenceKind, type ExplainMetric, type Level } from '../../lib/vmaxWorkspaceRules'
import type { ComplaintKey, DimensionScore, GameResult, OttResult, RadioAnalysis, TimelineRow, VoiceResult } from '../../pages/vmaxDiagnosisRules'
import type { CcaResult } from '../VmaxCcaCards'
import type { FlowData } from '../VmaxFlowCategoryTabs'
import ExplainableMetric from './ExplainableMetric'
import VmaxCrossCheck from './VmaxCrossCheck'
import VmaxVoiceCard from '../VmaxVoiceCard'
import VmaxOttCard from '../VmaxOttCard'
import VmaxGameCard from '../VmaxGameCard'
import VmaxFlowCategoryTabs from '../VmaxFlowCategoryTabs'
import VmaxEvidenceTimeline from '../VmaxEvidenceTimeline'

const { Text } = Typography

const LEVEL_TAG: Record<Level, string> = {
  ok: 'green', warn: 'orange', bad: 'red', unknown: 'default',
}

export default function VmaxWorkspaceAnalysis({
  metrics, chain, complaint,
  voice, ott, game, timeline, flowXdr,
  radio, cca,
  loading,
  onOpenEvidence,
}: {
  metrics: ExplainMetric[]
  chain: ChainStatus[]
  complaint: ComplaintKey
  voice: VoiceResult | null
  ott: OttResult | null
  game: GameResult | null
  timeline: TimelineRow[]
  radio: RadioAnalysis | null
  flowXdr: FlowData | null
  scores: DimensionScore[]
  cca: CcaResult | null
  loading: boolean
  onOpenEvidence: (kind: EvidenceKind) => void
}) {
  const { t } = useI18n()

  const primaryCard = complaint === 'voice' ? 'voice'
    : complaint === 'ott' ? 'ott'
    : complaint === 'game' ? 'game' : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
      <CardBase title={t('vmaxq.ws.zone2.title')}>
        <Space size="large" wrap align="center">
          {chain.map((c, i) => (
            <Space key={c.node} size={6} align="center">
              {i > 0 && <Text type="secondary">→</Text>}
              <Tag color={LEVEL_TAG[c.level]} style={{ marginInlineEnd: 0, padding: '2px 10px' }}>
                {t(CHAIN_NODE_KEY[c.node])}
              </Tag>
            </Space>
          ))}
        </Space>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-sm)', marginTop: 8 }}>
          {metrics.map((m) => (
            <ExplainableMetric key={m.id} metric={m} onOpenEvidence={onOpenEvidence} />
          ))}
        </div>
      </CardBase>

      {voice && primaryCard === 'voice' && <VmaxVoiceCard voice={voice} />}
      {ott && primaryCard === 'ott' && <VmaxOttCard ott={ott} />}
      {game && primaryCard === 'game' && <VmaxGameCard game={game} />}

      {/* 小区交叉验证（P3-2）：用户实际驻留小区（RAN 32）× CCA 根因/驻留小区。
          放在按投诉类型置顶的专卡之后、流量/时间线之前 —— 回答「问题落在哪个
          小区」的定位判据应先于原始明细。规则见 lib/vmaxCellCrossCheck.ts。 */}
      <VmaxCrossCheck radio={radio} cca={cca} onOpenEvidence={onOpenEvidence} />

      <CardBase title={t('vmaxq.flowCard')}>
        <VmaxFlowCategoryTabs flow={flowXdr} />
      </CardBase>

      <VmaxEvidenceTimeline rows={timeline} loading={loading} />

      <CardBase title={t('vmaxq.ws.deep')}
        extra={(
          <Space size={4}>
            <Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxq.ws.drawerHint')}</Text>
          </Space>
        )}>
        <Collapse size="small" items={[
          ...(voice && primaryCard !== 'voice' ? [{ key: 'voice', label: t('vmaxq.voice.card'), children: <VmaxVoiceCard voice={voice} /> }] : []),
          ...(ott && primaryCard !== 'ott' ? [{ key: 'ott', label: t('vmaxq.ott.card'), children: <VmaxOttCard ott={ott} /> }] : []),
          ...(game && primaryCard !== 'game' ? [{ key: 'game', label: t('vmaxq.game.card'), children: <VmaxGameCard game={game} /> }] : []),
        ]} />
      </CardBase>
    </div>
  )
}
