/* ============================================================================
 * ExplainableMetric —— 五段可解释指标行（CCA 工作台区域 2）
 * ============================================================================
 * 每个指标回答：为什么重要 / 观测到什么 / 何时发生 / 可能影响 / 需要验证
 * 文案全部走 t()；等级色与全站 StatCard 同一套阈值语义（见 VmaxDiagnosisCard）。
 * ========================================================================== */

import { Space, Tag, Typography } from 'antd'

import { useI18n } from '../../i18n'
import { renderI18n } from '../../renderI18n'
import { WH } from '../../theme'
import type { ExplainMetric, Level } from '../../lib/vmaxWorkspaceRules'

const { Text } = Typography

const LEVEL_COLOR: Record<Level, string> = {
  ok: WH.ok,
  warn: WH.warn,
  bad: WH.danger,
  unknown: WH.textDim,
}

export default function ExplainableMetric({ metric }: { metric: ExplainMetric }) {
  const { t } = useI18n()
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
      gap: 'var(--wh-space-sm)',
    }}>
      <div>
        <Text type="secondary" style={{ fontSize: 11 }}>{t('vmaxq.ws.metric.why')}</Text>
        <div style={{ fontSize: 12 }}>{renderI18n(t, metric.why)}</div>
      </div>
      <div>
        <Text type="secondary" style={{ fontSize: 11 }}>{t('vmaxq.ws.metric.observed')}</Text>
        <div style={{ fontSize: 12, color: LEVEL_COLOR[metric.level] }}>
          {renderI18n(t, metric.observed)}
          {metric.when && (
            <Tag color="default" style={{ marginInlineStart: 4 }}>{t('vmaxq.ws.metric.when', { time: metric.when })}</Tag>
          )}
        </div>
      </div>
      <div>
        <Text type="secondary" style={{ fontSize: 11 }}>{t('vmaxq.ws.metric.impact')}</Text>
        <div style={{ fontSize: 12 }}>{renderI18n(t, metric.impact)}</div>
      </div>
      <div>
        <Text type="secondary" style={{ fontSize: 11 }}>{t('vmaxq.ws.metric.verify')}</Text>
        <div style={{ fontSize: 12 }}>
          {metric.verify.map((v, i) => (
            <div key={i}>· {renderI18n(t, v)}</div>
          ))}
        </div>
      </div>
      <Space size={2} align="center">
        <Tag style={{ marginInlineEnd: 0 }}>
          {renderI18n(t, { key: metric.titleKey, params: metric.titleParams })}
        </Tag>
      </Space>
    </div>
  )
}
