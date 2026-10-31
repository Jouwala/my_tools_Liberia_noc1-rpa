/* ============================================================================
 * VmaxDiagnosisCard —— 投诉诊断结论卡（页面最重要的那块）
 * ============================================================================
 *
 * 【2026-10-31 新增，方案 §4.8】
 *
 * 这块卡回答的是一句话：**「这条投诉，网络侧到底有没有问题、问题在哪」**。
 * 之前页面是四个数据源页签，用户得自己拼出结论；现在结论在最上面。
 *
 * 结构（自上而下）：
 *   ① 结论条   —— 一句话 + 严重度色 + 置信度 + 是否复现
 *   ② 人工覆写 —— 排在系统判定**上面**（人工判定是最终意见），
 *                 但系统判定永不覆盖，两者都留在页面上与导出里
 *   ③ 判定依据 —— 三条以内的证据句，每句都能指到某个源
 *   ④ 四维评分 —— StatCard × 4，点开看该维度的全部证据
 *   ⑤ 数据源命中 —— 「哪个源返回了几条」，让「空」变成一条结论而不是疑问
 *   ⑥ 操作     —— 导出 Excel / 导出 PDF / 覆写
 *
 * 【为什么评分用 StatCard 而不是自绘】
 *   AGENTS.md 要求统一卡片观感。四个分项评分与全站其它 KPI 卡同一形态，
 *   用户扫视时会自动按「卡 = 一个指标」来读，不必再学一种新的视觉语言。
 *
 * 【无数据 ≠ 0 分】
 *   `score === null` 表示这一维**没有任何可用话单**。渲染成灰色的
 *   「无数据可判」而不是 0 分，否则「查不到」会被读成「差到极点」——
 *   这是排障场景里最容易误导人的一处（方案 §7 明确列为红线）。
 * ========================================================================== */

import { useMemo, useState } from 'react'
import { Button, Descriptions, Space, Tag, Tooltip, Typography } from 'antd'
import {
  AlertOutlined, CloudDownloadOutlined, EditOutlined, FilePdfOutlined,
  ReloadOutlined, SafetyOutlined,
} from '@ant-design/icons'

import { useI18n } from '../i18n'
import { CardBase } from './cards'
import StatCard from './StatCard'
import { renderI18n, renderI18nList } from '../renderI18n'
import DraggableClickModal from './DraggableClickModal'
import { WH } from '../theme'
import type {
  ComplaintKey, DimensionScore, DiagnosisPayload, ScoreKey, SourceResult, Verdict,
} from '../pages/vmaxDiagnosisRules'
import { pct, sourceLabel } from '../pages/vmaxDiagnosisRules'

const { Text } = Typography

export type OverrideInfo = {
  id: number
  verdict_manual: string
  reason: string
  username: string
  created_at: string
}

/* ---- 分数 → 语义色：与全站 wh-card-lv-* 同一套阈值语义 ---- */
function scoreColor(score: number | null): string {
  if (score === null) return WH.textDim
  if (score >= 80) return WH.ok
  if (score >= 50) return WH.warn
  return WH.danger
}

function scoreLevel(score: number | null): 'ok' | 'warn' | 'bad' | 'none' {
  if (score === null) return 'none'
  if (score >= 80) return 'ok'
  if (score >= 50) return 'warn'
  return 'bad'
}

function verdictColor(verdict: Verdict): string {
  if (!verdict.reproduced) return WH.ok
  return verdict.confidence === 'high' ? WH.danger : WH.warn
}

export default function VmaxDiagnosisCard({
  payload,
  scores,
  verdict,
  complaint,
  loading,
  error,
  overrides,
  onOverride,
  onExportExcel,
  onExportPdf,
  onRefresh,
  onGotoView,
}: {
  payload: DiagnosisPayload | null
  scores: DimensionScore[]
  verdict: Verdict | null
  complaint: ComplaintKey
  loading: boolean
  error?: string
  /** 当前用户对该号码+窗口的覆写（无则 null） */
  overrides: OverrideInfo | null
  onOverride: () => void
  onExportExcel: () => void
  onExportPdf: () => void
  onRefresh: () => void
  /** 空态时把用户送到对应页签（「查看连接过程」这类） */
  onGotoView?: (v: 'flow' | 'connect' | 'radio') => void
}) {
  const { t } = useI18n()
  const [detail, setDetail] = useState<DimensionScore | null>(null)
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)

  const sources: SourceResult[] = useMemo(() => payload?.sources || [], [payload])
  const totalRows = sources.reduce((a, s) => a + (s.rows?.length || 0), 0)
  const failed = sources.filter((s) => !s.ok)
  const anyData = totalRows > 0

  const openDetail = (s: DimensionScore, e: React.MouseEvent<HTMLElement>) => {
    setAnchor({ x: e.clientX, y: e.clientY })
    setDetail(s)
  }

  return (
    <CardBase
      level={verdict?.reproduced ? (verdict.confidence === 'high' ? 'crit' : 'warn') : 'ok'}
      title={(
        <Space size={6}>
          <SafetyOutlined style={{ color: verdictColor(verdict || ({} as Verdict)) }} />
          <span style={{ fontSize: '0.8125rem', fontWeight: 600 }}>{t('vmaxq.diag.card')}</span>
        </Space>
      )}
      extra={(
        <Space size={4} wrap>
          <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={onRefresh}>
            {t('vmaxq.diag.refresh')}
          </Button>
          <Button size="small" icon={<CloudDownloadOutlined />} disabled={!anyData}
            onClick={onExportExcel}>
            {t('vmaxq.diag.exportExcel')}
          </Button>
          <Button size="small" icon={<FilePdfOutlined />} disabled={!anyData}
            onClick={onExportPdf}>
            {t('vmaxq.diag.exportPdf')}
          </Button>
          <Button size="small" type="primary" ghost icon={<EditOutlined />}
            disabled={!anyData} onClick={onOverride}>
            {overrides ? t('vmaxq.diag.overrideEdit') : t('vmaxq.diag.override')}
          </Button>
        </Space>
      )}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-sm)' }}>

        {/* ---------- 错误 / 部分失败 ---------- */}
        {!!error && (
          <Text type="danger" style={{ fontSize: 12 }}>
            <AlertOutlined /> {error}
          </Text>
        )}
        {!!failed.length && (
          <Text type="warning" style={{ fontSize: 12 }}>
            {t('vmaxq.diag.partialFail')}：
            {failed
              .map((s) => t('vmaxq.diag.failItem', {
                src: sourceLabel(t, s),
                why: s.error || t('vmaxq.diag.sourceFail'),
              }))
              .join(t('vmaxq.listSep'))}
          </Text>
        )}

        {/* ---------- ① 结论条 ---------- */}
        {verdict && (
          <div style={{
            padding: '10px 12px',
            borderRadius: 8,
            background: `color-mix(in srgb, ${verdictColor(verdict)} 10%, transparent)`,
            borderLeft: `3px solid ${verdictColor(verdict)}`,
          }}>
            <Space size={6} wrap align="center">
              <Tag color={verdict.reproduced ? (verdict.confidence === 'high' ? 'red' : 'orange') : 'green'}
                style={{ marginInlineEnd: 0 }}>
                {verdict.reproduced ? t('vmaxq.diag.reproduced') : t('vmaxq.diag.notReproduced')}
              </Tag>
              <Text strong style={{ fontSize: 14 }}>{renderI18n(t, verdict.headline)}</Text>
              <Tooltip title={`${t('vmaxq.diag.confidence')}`}>
                <Tag color="default" style={{ marginInlineEnd: 0 }}>
                  {t('vmaxq.diag.confidence')} {t(`vmaxq.diag.confidence.${verdict.confidence}`)}
                </Tag>
              </Tooltip>
            </Space>
            <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 2 }}>
              {renderI18nList(t, verdict.basis).map((line, i) => (
                <Text key={i} style={{ fontSize: 12, color: WH.textMuted }}>· {line}</Text>
              ))}
            </div>
            <div style={{ marginTop: 6 }}>
              <Text style={{ fontSize: 12 }}>
                <Text strong style={{ fontSize: 12 }}>{t('vmaxq.diag.suggestionLabel')}</Text>
                {renderI18n(t, verdict.suggestion)}
              </Text>
            </div>
          </div>
        )}

        {/* ---------- ② 人工覆写（置顶于系统判定之上） ---------- */}
        {overrides && (
          <div style={{
            padding: '10px 12px',
            borderRadius: 8,
            background: 'color-mix(in srgb, var(--wh-blue) 9%, transparent)',
            borderLeft: '3px solid var(--wh-blue)',
          }}>
            <Space size={6} wrap align="center">
              <Tag color="blue" style={{ marginInlineEnd: 0 }}>{t('vmaxq.diag.verdictManual')}</Tag>
              <Text strong style={{ fontSize: 13 }}>{overrides.verdict_manual}</Text>
            </Space>
            <div style={{ marginTop: 4 }}>
              <Text style={{ fontSize: 12, color: WH.textMuted }}>
                {t('vmaxq.override.reason')}：{overrides.reason}
              </Text>
              <div>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {t('vmaxq.diag.overriddenBy', {
                    user: overrides.username,
                    time: overrides.created_at.replace('T', ' ').slice(0, 16),
                  })}
                </Text>
              </div>
            </div>
          </div>
        )}

        {/* ---------- ④ 四维评分 ---------- */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 'var(--wh-space-sm)',
        }}>
          {scores.map((s) => {
            const accent = scoreColor(s.score)
            return (
              <StatCard
                key={s.key}
                title={(
                  <Space size={4}>
                    <span>{t(`vmaxq.diag.score.${s.key}`)}</span>
                    {verdict?.focus === s.key && (
                      <Tag color="orange" style={{ marginInlineEnd: 0, fontSize: 10, lineHeight: '15px' }}>
                        ●
                      </Tag>
                    )}
                  </Space>
                )}
                value={s.score === null ? '—' : s.score}
                suffix={s.score === null ? undefined : '/100'}
                accentColor={accent}
                subText={
                  s.score === null
                    ? <span title={t('vmaxq.diag.noDataHint')}>{t('vmaxq.diag.score.na')}</span>
                    : (s.sub
                      ? renderI18n(t, s.sub)
                      : t(`vmaxq.diag.level${s.score >= 80 ? 'Good' : s.score >= 50 ? 'Warn' : 'Bad'}`))
                }
                onClick={(e) => openDetail(s, e)}
                prefix={<span style={{
                  fontSize: 12, fontWeight: 700, color: accent,
                }}>{
                  s.score === null ? '?' : (s.score >= 80 ? '✓' : s.score >= 50 ? '!' : '✕')
                }</span>}
              />
            )
          })}
        </div>

        {/* ---------- ⑤ 数据源命中 ---------- */}
        <Descriptions
          size="small"
          bordered
          column={1}
          items={[
            {
              key: 'src',
              label: t('vmaxq.diag.sources'),
              children: (
                <Space size={4} wrap>
                  {sources.map((s) => (
                    <Tooltip key={s.key} title={s.error || ''}>
                      <Tag
                        color={s.ok ? (s.rows.length ? 'cyan' : 'default') : 'red'}
                        style={{ marginInlineEnd: 0 }}
                      >
                        {/* 标签与条数之间的分隔符也算文案：中文用全角「：」，
                            英文该是半角「: 」—— 由 vmaxq.diag.srcTag 模板承载，
                            不能在这里硬编码冒号。 */}
                        {s.ok
                          ? t('vmaxq.diag.srcTag', { src: sourceLabel(t, s), n: s.rows.length })
                          : t('vmaxq.diag.srcTagFail', { src: sourceLabel(t, s) })}
                        {s.truncated ? ' *' : ''}
                      </Tag>
                    </Tooltip>
                  ))}
                  {!!payload?.imsi && (
                    <Tag style={{ marginInlineEnd: 0 }}>IMSI {payload.imsi}</Tag>
                  )}
                  {!!sources.find((s) => s.truncated) && (
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {t('vmaxq.diag.truncatedHint')}
                    </Text>
                  )}
                </Space>
              ),
            },
            {
              key: 'win',
              label: t('vmaxq.diag.window'),
              children: payload
                ? `${payload.window.start} ~ ${payload.window.end.slice(11)}`
                : '—',
            },
          ]}
        />

        {/* ---------- 空态：四源全空时必须说清楚「为什么空」（方案 §4.10） ---------- */}
        {!loading && !anyData && (
          <div style={{
            padding: '12px 14px',
            borderRadius: 8,
            background: 'color-mix(in srgb, var(--wh-warn) 8%, transparent)',
          }}>
            <Text strong style={{ fontSize: 13 }}>{t('vmaxq.empty.title')}</Text>
            <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 3 }}>
              <Text style={{ fontSize: 12, color: WH.textMuted }}>
                · {t('vmaxq.empty.sources')}：{sources
                  .map((s) => t('vmaxq.diag.srcCount', { src: sourceLabel(t, s), n: s.rows.length }))
                  .join(t('vmaxq.listSep'))}
              </Text>
              <Text style={{ fontSize: 12, color: WH.textMuted }}>
                · {t('vmaxq.empty.reasons')}：{t('vmaxq.empty.reason1')}{t('vmaxq.semiSep')}{t('vmaxq.empty.reason2')}{t('vmaxq.semiSep')}{t('vmaxq.empty.reason3')}
              </Text>
            </div>
            <Space size={6} style={{ marginTop: 8 }} wrap>
              <Button size="small" onClick={() => onGotoView?.('connect')}>
                {t('vmaxq.empty.gotoConn')}
              </Button>
              <Button size="small" onClick={() => onGotoView?.('radio')}>
                {t('vmaxq.empty.gotoRadio')}
              </Button>
            </Space>
          </div>
        )}
      </div>

      {/* ---------- 分项证据弹窗 ---------- */}
      <DraggableClickModal
        open={!!detail}
        anchor={anchor}
        title={detail ? t(`vmaxq.diag.score.${detail.key as ScoreKey}`) : ''}
        onClose={() => setDetail(null)}
        width={520}
        maxWidth={520}
      >
        {detail && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 380 }}>
            <Space size={8}>
              <Text strong style={{ fontSize: 20, color: scoreColor(detail.score) }}>
                {detail.score === null ? '—' : detail.score}
              </Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {detail.score === null ? t('vmaxq.diag.noDataHint') : renderI18n(t, detail.sub)}
              </Text>
            </Space>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {renderI18nList(t, detail.evidence).map((line, i) => (
                <Text key={i} style={{ fontSize: 12 }}>· {line}</Text>
              ))}
            </div>
            {!!Object.keys(detail.detail).length && (
              <Descriptions
                size="small"
                bordered
                column={1}
                items={Object.entries(detail.detail).map(([k, v]) => ({
                  key: k,
                  label: k,
                  children: typeof v === 'number' ? String(v) : v,
                }))}
              />
            )}
          </div>
        )}
      </DraggableClickModal>
    </CardBase>
  )
}

/** 供页面复用的分数阈值文案（导出时也用同一套，避免两处不一致）*/
export function scoreText(s: number | null): string {
  if (s === null) return 'N/A'
  return `${s}/100`
}

export { pct }
