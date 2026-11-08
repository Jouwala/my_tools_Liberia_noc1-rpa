/* ============================================================================
 * VmaxCrossCheck —— 小区交叉验证卡（CCA 工作台区域 2，P3-2）
 * ============================================================================
 * 把「用户实际驻留的小区（RAN 32）」与「CCA 根因/驻留小区」摆在一起：
 *   - 判定一致 / 不一致 / 无法判定（unknown 永不当成「正常」）；
 *   - 不一致时常驻提示「这本身是排障线索」，并给出两边各是谁；
 *   - 同小区 KPI 只做并列对照（见 VmaxCrossCheckKpiTable，不做阈值判定）；
 *   - 口径说明走 CalcChainNote（默认收起），列头 ⓘ 与数字悬浮走 MetricExplain。
 * 放在「链路 + 五段指标」与按投诉类型置顶的专卡之后、流量/时间线之前：
 * 它回答的是「问题落在哪个小区」，属于定位判据，应排在明细之前。
 * 规则全部在 lib/vmaxCellCrossCheck.ts（纯函数、可单测），本文件只排版。
 * ========================================================================== */

import { useMemo } from 'react'
import { Alert, Button, Space, Tag, Typography } from 'antd'

import { useI18n } from '../../i18n'
import { renderI18n } from '../../renderI18n'
import { renderRich } from '../../utils/richText'
import { CardBase } from '../cards'
import CalcChainNote from '../CalcChainNote'
import VmaxCrossCheckKpiTable from './VmaxCrossCheckKpiTable'
import {
  buildCellCrossCheck, CROSS_VERDICT_KEY, type CrossVerdict,
} from '../../lib/vmaxCellCrossCheck'
import type { EvidenceKind } from '../../lib/vmaxWorkspaceRules'
import type { CcaResult } from '../VmaxCcaCards'
import type { RadioAnalysis } from '../../pages/vmaxDiagnosisRules'

const { Text } = Typography

const VERDICT_TAG: Record<CrossVerdict, string> = {
  match: 'green', mismatch: 'orange', unknown: 'default',
}

const SMALL = { fontSize: 12 } as const

export default function VmaxCrossCheck({
  radio, cca, onOpenEvidence,
}: {
  radio: RadioAnalysis | null
  cca: CcaResult | null
  onOpenEvidence: (kind: EvidenceKind) => void
}) {
  const { t } = useI18n()
  const cc = useMemo(() => buildCellCrossCheck({ radio, cca }), [radio, cca])

  // 尚未发起任何查询（两侧都为空）：不占位，避免首屏出现「无法判定」噪声。
  // 只在一侧有数据时照常渲染 —— 那正是「数据不足」需要被如实说出来的场景。
  if (!radio && !cca) return null

  const primary = cc.ranServed[0] ?? null

  return (
    <CardBase
      title={t('vmaxq.ws.cross.title')}
      extra={(
        <Space size={4}>
          {cc.refs.map((ref) => (
            <Button key={ref.kind} size="small" onClick={() => onOpenEvidence(ref.kind)}>
              {ref.kind === 'cca' ? t('vmaxq.ws.evidence.cca') : t('vmaxq.ws.evidence.radio')}
            </Button>
          ))}
        </Space>
      )}
    >
      {/* 判定：unknown 走常驻告警（数据不足必须看得见，不得显示成「正常」） */}
      {cc.verdict === 'unknown' ? (
        <Alert type="warning" showIcon message={renderRich(renderI18n(t, cc.headline))} />
      ) : (
        <Space size={8} wrap align="center">
          <Tag color={VERDICT_TAG[cc.verdict]} style={{ marginInlineEnd: 0 }}>
            {t(CROSS_VERDICT_KEY[cc.verdict])}
          </Tag>
          <Text style={SMALL}>{renderRich(renderI18n(t, cc.headline))}</Text>
        </Space>
      )}

      {/* 不一致：这本身是有价值的排障线索，常驻提示（不是口径解释） */}
      {cc.verdict === 'mismatch' && (
        <Alert
          type="warning" showIcon style={{ marginTop: 8 }}
          message={t('vmaxq.ws.cross.mismatchHint')}
        />
      )}

      {/* 两侧驻留事实（多小区不合并成一句结论，数量与主小区都摆出来） */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 8 }}>
        {cc.ranPrimary && primary && (
          <Text type="secondary" style={SMALL}>
            {t('vmaxq.ws.cross.ranServed', {
              cell: cc.ranPrimary, n: primary.samples, m: cc.ranServed.length,
            })}
          </Text>
        )}
        {cc.ccaFlagged.length > 0 && (
          <Text type="secondary" style={SMALL}>
            {t('vmaxq.ws.cross.ccaFlagged', { cells: cc.ccaFlagged.join(' / ') })}
          </Text>
        )}
        {cc.ccaServed.length > 0 && (
          <Text type="secondary" style={SMALL}>
            {t('vmaxq.ws.cross.ccaServed', { n: cc.ccaServed.length })}
          </Text>
        )}
      </div>

      {/* 同小区 KPI 并列对照：只摆数字，不判好坏（阈值唯一出处是 THRESHOLDS） */}
      <VmaxCrossCheckKpiTable cellKpis={cc.cellKpis} />

      <CalcChainNote
        style={{ marginTop: 12 }}
        title={t('vmaxq.ws.cross.note.title')}
        sections={[
          { title: t('vmaxq.ws.cross.note.srcTitle'), lines: [t('vmaxq.ws.cross.note.src')] },
          { title: t('vmaxq.ws.cross.note.primaryTitle'), lines: [t('vmaxq.ws.cross.note.primary')] },
          { title: t('vmaxq.ws.cross.note.matchTitle'), lines: [t('vmaxq.ws.cross.note.match')] },
          { title: t('vmaxq.ws.cross.note.kpiTitle'), lines: [t('vmaxq.ws.cross.note.kpi')] },
        ]}
      />
    </CardBase>
  )
}
