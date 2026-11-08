/* ============================================================================
 * VmaxOverrideModal —— 人工覆写诊断结论
 * ============================================================================
 *
 * 【2026-10-31 新增，方案 §4.5；评审意见 4：「允许人工覆写」】
 *
 * 设计取舍（每一条都有理由，改之前先读）：
 *
 * ① **原始结论永不覆盖**。覆写是叠加：页面上同时有「系统判定」与「人工判定」，
 *    人工的置顶并标「人工」。理由：系统判定是可复现的证据链，覆盖掉它就
 *    等于毁掉这条投诉的取证基础，日后追责时说不清「当时为什么这么判」。
 *
 * ② **理由必填 ≥ 10 字**。理由会原样进导出文件。低于 10 字的理由基本等于
 *    没写（"没问题"/"已处理"），起不到留痕作用。
 *
 * ③ **按用户隔离**。同 `vmax_xdr_saved_record`：别人的覆写看不到，
 *    避免同一条投诉被多人互相改写。
 *
 * ④ 用 antd Modal 而非 DraggableClickModal：这里要**阻断**（必须做选择），
 *    可拖拽的浮层会被误认为可以拖走不管。项目里下钻一律用
 *    DraggableClickModal（不影响原页面），表单确认用 Modal —— 两者职责不同。
 * ========================================================================== */

import { useEffect, useState } from 'react'
import { Alert, Button, Descriptions, Input, Modal, Space, Typography } from 'antd'

import { useI18n } from '../i18n'
import { WH } from '../theme'
import CalcChainNote, { type CalcChainSection } from './CalcChainNote'
import type { OverrideInfo } from './VmaxDiagnosisCard'
import { parseVerdictSnapshot, type VerdictSnapshot } from '../lib/vmaxVerdictSnapshot'
import { renderI18n, renderI18nList } from '../renderI18n'

const { TextArea } = Input
const { Text } = Typography

const MIN_REASON = 10

type TFn = (key: string, params?: Record<string, string | number>) => string

/**
 * 把已存档快照整理成可展开的小节（P3-3）。
 *
 * 只做**排版**：所有值都取自快照本身，不重新计算任何指标 ——
 * 否则会出现「弹窗里的分与页面上的分不一致」这种新的不可审计。
 */
function snapshotSections(snap: VerdictSnapshot, t: TFn): CalcChainSection[] {
  const line = (label: string, value: string | number) =>
    t('vmaxq.override.snapshotLine', { label, value })
  const sections: CalcChainSection[] = []

  // ① 上下文：存档时间 / 投诉类型 / 窗口 / IMSI（快照里没有号码明文）
  const ctx: string[] = [
    line(t('vmaxq.print.generated'), snap.generated_at.replace('T', ' ').slice(0, 19)),
    line(t('vmaxq.print.complaint'), t(`vmaxq.complaint.${snap.complaint}`)),
    line(t('vmaxq.diag.window'), `${snap.window.start} ~ ${snap.window.end}`),
  ]
  if (snap.imsi) ctx.push(`IMSI ${snap.imsi}`)
  sections.push({ lines: ctx })

  // ② 结论（快照里的 headline 是 {key, params}，按当前语言渲染）
  if (snap.verdict) {
    sections.push({
      title: t('vmaxq.diag.verdictAuto'),
      lines: [
        renderI18n(t, snap.verdict.headline),
        line(t('vmaxq.diag.confidence'), t(`vmaxq.diag.confidence.${snap.verdict.confidence}`)),
        t(snap.verdict.reproduced ? 'vmaxq.diag.reproduced' : 'vmaxq.diag.notReproduced'),
      ],
    })
    if (snap.verdict.basis.length) {
      sections.push({
        title: t('vmaxq.diag.basis'),
        lines: renderI18nList(t, snap.verdict.basis),
      })
    }
  }

  // ③ 四维评分（null 显示 —：无数据 ≠ 0 分）
  if (snap.scores.length) {
    sections.push({
      lines: snap.scores.map((s) =>
        line(t(`vmaxq.diag.score.${s.key}`), s.score === null ? '—' : `${s.score}/100`)),
    })
  }

  // ④ 数据源状态：条数 / 失败原因 / 是否截断
  if (snap.sources.length) {
    sections.push({
      title: t('vmaxq.diag.sources'),
      lines: snap.sources.map((s) => {
        const name = s.label_key ? t(s.label_key) : s.label
        const text = s.ok
          ? t('vmaxq.diag.srcTag', { src: name, n: s.rows })
          : t('vmaxq.diag.failItem', { src: name, why: s.error || t('vmaxq.diag.sourceFail') })
        return text + (s.truncated ? ' *' : '')
      }),
    })
  }

  // ⑤ 关键指标（语音 / OTT / 游戏）—— 与卡片同一批判定数字
  if (snap.voice) {
    const v = snap.voice
    sections.push({
      title: t('vmaxq.voice.card'),
      lines: [[
        line(t('vmaxq.voice.mode'), t(`vmaxq.voice.mode.${v.mode}`)),
        line(t('vmaxq.voice.sgs'), v.sgsCount),
        line(t('vmaxq.voice.csfbTrigger'), v.csfbTrigger),
        line(t('vmaxq.voice.esr'), v.esrCount),
        line(t('vmaxq.voice.page'), v.pagingCount),
        line(t('vmaxq.voice.timeout'), v.badCount),
        line(t('vmaxq.voice.est'), v.successRate === null ? '—' : `${v.successRate}%`),
        line(t('vmaxq.voice.fallbackMs'), v.fallbackMs === null ? '—' : `${v.fallbackMs}ms`),
      ].join(' · ')],
    })
  }
  if (snap.ott) {
    const o = snap.ott
    sections.push({
      title: t('vmaxq.ott.card'),
      lines: [[
        line(t('vmaxq.ott.sessions'), o.totalSessions),
        line(t('vmaxq.ott.duration'), `${o.totalDurationS}s`),
        line(t('vmaxq.ott.rtt'), `${o.avgDlRtt}ms`),
        line(t('vmaxq.ott.jitter'), `${o.jitter}ms`),
        line(t('vmaxq.ott.retrans'), `${o.retransRate}%`),
      ].join(' · ')],
    })
  }
  if (snap.game) {
    const g = snap.game
    sections.push({
      title: t('vmaxq.game.card'),
      lines: [g.hits.length
        ? `${t('vmaxq.game.found', { n: g.totalSessions })} · `
          + g.hits.map((h) => `${h.app}(${h.records})`).join(t('vmaxq.listSep'))
        : t('vmaxq.game.none')],
    })
  }
  return sections
}

export default function VmaxOverrideModal({
  open,
  autoVerdict,
  existing,
  saving,
  onCancel,
  onSubmit,
  onRevoke,
}: {
  open: boolean
  /** 系统判定（只读展示，永不被改写） */
  autoVerdict: string
  /** 已有的覆写（编辑模式） */
  existing: OverrideInfo | null
  saving?: boolean
  onCancel: () => void
  onSubmit: (verdict: string, reason: string) => void
  onRevoke: () => void
}) {
  const { t } = useI18n()
  const [verdict, setVerdict] = useState('')
  const [reason, setReason] = useState('')
  const [err, setErr] = useState('')
  // P3-3：编辑已有覆写时，把提交当时存档的诊断快照解析出来（老记录没有 → null）
  const snapshot = parseVerdictSnapshot(existing?.verdict_snapshot)

  // 每次打开都用最新值重置：残留上一次的输入比清空更危险（会误提交别人的结论）
  useEffect(() => {
    if (!open) return
    setVerdict(existing?.verdict_manual || '')
    setReason(existing?.reason || '')
    setErr('')
  }, [open, existing])

  const submit = () => {
    const v = verdict.trim()
    const r = reason.trim()
    if (!v) { setErr(t('vmaxq.override.manualRequired')); return }
    if (r.length < MIN_REASON) { setErr(t('vmaxq.override.reasonTooShort')); return }
    setErr('')
    onSubmit(v, r)
  }

  return (
    <Modal
      open={open}
      title={t('vmaxq.override.title')}
      onCancel={onCancel}
      width={640}
      destroyOnClose
      footer={(
        <Space>
          {existing && (
            <Button danger onClick={onRevoke} loading={saving}>
              {t('vmaxq.override.revoke')}
            </Button>
          )}
          <Button onClick={onCancel}>{t('vmaxq.override.cancel')}</Button>
          <Button type="primary" onClick={submit} loading={saving}>
            {t('vmaxq.override.submit')}
          </Button>
        </Space>
      )}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Alert
          type="info"
          showIcon
          message={t('vmaxq.override.note')}
          style={{ padding: '6px 12px' }}
        />

        <Descriptions
          size="small"
          bordered
          column={1}
          items={[{
            key: 'auto',
            label: t('vmaxq.override.auto'),
            children: <Text>{autoVerdict || '—'}</Text>,
          }]}
        />

        {/* ---------- 已存档诊断快照（P3-3，可审计） ----------
            默认收起（AGENTS.md 三.3b），只有确实存过快照才出现；
            老记录（迁移前提交）没有快照 → 不显示，不冒充「没关系」。 */}
        {snapshot && (
          <CalcChainNote
            title={t('vmaxq.override.snapshot')}
            sections={snapshotSections(snapshot, t)}
          />
        )}

        <div>
          <div style={{ marginBottom: 4 }}>
            <Text strong style={{ fontSize: 12 }}>{t('vmaxq.override.manual')}</Text>
          </div>
          <TextArea
            value={verdict}
            onChange={(e) => setVerdict(e.target.value)}
            placeholder={t('vmaxq.override.manualPlaceholder')}
            autoSize={{ minRows: 2, maxRows: 4 }}
            maxLength={300}
            showCount
          />
        </div>

        <div>
          <div style={{ marginBottom: 4 }}>
            <Text strong style={{ fontSize: 12 }}>{t('vmaxq.override.reason')}</Text>
            <Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>
              {reason.trim().length}/{MIN_REASON}
            </Text>
          </div>
          <TextArea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t('vmaxq.override.reasonPlaceholder')}
            autoSize={{ minRows: 3, maxRows: 6 }}
            maxLength={500}
            showCount
          />
        </div>

        {!!err && (
          <Text style={{ fontSize: 12, color: WH.danger }}>{err}</Text>
        )}
      </div>
    </Modal>
  )
}
