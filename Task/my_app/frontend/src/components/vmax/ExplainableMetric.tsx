/* ============================================================================
 * ExplainableMetric —— 可解释指标行（CCA 工作台区域 2，2026-11-07 瘦身版）
 * ============================================================================
 * 常驻只留三样：指标名 Tag、本次观测（按等级着色）+ 何时发生；
 * 静态教学文案（为什么重要 / 可能影响 / 需要验证）收进 ⓘ 悬浮气泡
 * （AGENTS.md 第四节第 10 条：说「怎么算的」→ 收起，说「这次观测到什么」
 * → 常驻）。行尾「查看证据」按 refs 打开对应原始证据抽屉 —— 证据按需
 * 加载的最后一环，此前只建了 refs 没有入口。
 * ========================================================================== */

import { Button, Tag } from 'antd'

import { useI18n } from '../../i18n'
import { renderI18n } from '../../renderI18n'
import { WH } from '../../theme'
import { ExplainIcon } from '../MetricExplain'
import type { EvidenceKind, ExplainMetric, Level } from '../../lib/vmaxWorkspaceRules'

const LEVEL_COLOR: Record<Level, string> = {
  ok: WH.ok,
  warn: WH.warn,
  bad: WH.danger,
  unknown: WH.textDim,
}

export default function ExplainableMetric({
  metric, onOpenEvidence,
}: {
  metric: ExplainMetric
  onOpenEvidence: (kind: EvidenceKind) => void
}) {
  const { t } = useI18n()

  // ⓘ 气泡内容：三段静态解释合成一条可复制的文案（ExplainPopover 自带复制）
  const explainText = [
    `${t('vmaxq.ws.metric.why')}：${renderI18n(t, metric.why)}`,
    `${t('vmaxq.ws.metric.impact')}：${renderI18n(t, metric.impact)}`,
    ...metric.verify.map((v) => `${t('vmaxq.ws.metric.verify')}：${renderI18n(t, v)}`),
  ].join('\n')

  const ref = metric.refs[0]

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      flexWrap: 'wrap', minHeight: 26,
    }}>
      <Tag style={{ marginInlineEnd: 0, flexShrink: 0 }}>
        {renderI18n(t, { key: metric.titleKey, params: metric.titleParams })}
      </Tag>
      <span style={{
        fontSize: 12, color: LEVEL_COLOR[metric.level],
        flex: 1, minWidth: 180,
      }}>
        {renderI18n(t, metric.observed)}
        {metric.when && (
          <Tag color="default" style={{ marginInlineStart: 4 }}>
            {t('vmaxq.ws.metric.when', { time: metric.when })}
          </Tag>
        )}
      </span>
      <ExplainIcon text={explainText} />
      {ref && (
        <Button
          type="link" size="small"
          style={{ padding: 0, height: 'auto', flexShrink: 0 }}
          onClick={() => onOpenEvidence(ref.kind)}
        >
          {t('vmaxq.ws.evidence.open')}
        </Button>
      )}
    </div>
  )
}
