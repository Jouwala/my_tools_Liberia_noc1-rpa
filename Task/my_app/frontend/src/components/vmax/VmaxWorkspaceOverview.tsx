/* ============================================================================
 * VmaxWorkspaceOverview —— 区域 1 故障概览（CCA 工作台）
 * ============================================================================
 * 第一屏只回答「用户到底出了什么问题」：
 *   结论条（buildVerdict 原样）+ 四维评分 + 业务影响 chips，
 * 无数据写 unknown，绝不写「正常」。
 * ========================================================================== */

import { Space, Tag, Typography } from 'antd'

import { useI18n } from '../../i18n'
import { renderI18n } from '../../renderI18n'
import { CardBase } from '../cards'
import { WH } from '../../theme'
import type { DimensionScore, Verdict } from '../../pages/vmaxDiagnosisRules'

const { Text } = Typography

const SCORE_LABEL: Record<string, string> = {
  availability: 'vmaxq.diag.score.availability',
  latency: 'vmaxq.diag.score.latency',
  transport: 'vmaxq.diag.score.transport',
  radio: 'vmaxq.diag.score.radio',
}

export function scoreColor(score: number | null): string {
  if (score === null) return WH.textDim
  if (score >= 80) return WH.ok
  if (score >= 50) return WH.warn
  return WH.danger
}

export function levelText(score: number | null, t: (k: string) => string): string {
  if (score === null) return t('vmaxq.ws.level.unknown')
  if (score >= 80) return t('vmaxq.ws.level.ok')
  if (score >= 50) return t('vmaxq.ws.level.warn')
  return t('vmaxq.ws.level.bad')
}

export default function VmaxWorkspaceOverview({
  verdict, scores, loading,
}: {
  verdict: Verdict | null
  scores: DimensionScore[]
  loading: boolean
}) {
  const { t } = useI18n()
  return (
    <CardBase title={t('vmaxq.ws.zone1.title')} loading={loading}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-sm)' }}>
        {verdict && (
          <div>
            <Space size={6} wrap>
              <Tag color={verdict.reproduced ? 'red' : 'green'} style={{ marginInlineEnd: 0 }}>
                {verdict.reproduced ? t('vmaxq.ws.verdict.found') : t('vmaxq.ws.verdict.notFound')}
              </Tag>
              <Text strong>{renderI18n(t, verdict.headline)}</Text>
              <Tag style={{ marginInlineEnd: 0 }}>
                {t('vmaxq.ws.confidence', { v: t(`vmaxq.diag.confidence.${verdict.confidence}`) })}
              </Tag>
            </Space>
            <div style={{ marginTop: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {renderI18n(t, verdict.suggestion)}
              </Text>
            </div>
          </div>
        )}
        <Space size={6} wrap>
          {scores.map((s) => (
            <Tag key={s.key} color={s.score === null ? 'default' : s.score >= 80 ? 'green' : s.score >= 50 ? 'orange' : 'red'}>
              {t(SCORE_LABEL[s.key])} · {s.score === null ? t('vmaxq.diag.score.na') : s.score}
            </Tag>
          ))}
        </Space>
      </div>
    </CardBase>
  )
}
