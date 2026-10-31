/* ============================================================================
 * VmaxComplaintTabs —— 投诉类型一级页签
 * ============================================================================
 *
 * 【2026-10-31 新增，评审意见 1：「投诉类型要不要做成页面上的页签的形式，不要下拉」】
 *
 * 它**不是一个过滤器**，而是「换一套判据权重」（方案 §4.2）：
 *   选「语音」   → 先判 CSFB 回落链，大流量类指标降权
 *   选「OTT」    → 先判 STUN 会话是否存在，再算通话期间抖动
 *   选「游戏」   → 先看游戏应用的 RTT / 抖动 / 重传，再看 SINR
 *   选「视频」   → 先看视频类首包时延与重传，CSFB 链降权
 *   选「上网慢」 → 先看 DNS / TCP 握手时延与重传率，语音降权
 *
 * 为什么放前端算权重而不是让后端按类型出结果：
 *   切类型要**秒切**。后端算意味着每切一次多打一次上游（1300 三页 12s，
 *   且上游限并发），体验与上游压力都不允许。数据一次拉齐，权重在前端换。
 *
 * 页签下面那行说明不是装饰：它告诉排障的人「这次我按哪条链在判」，
 * 避免看完结论才发现判据不是自己想的那条。
 * ========================================================================== */

import { Segmented, Space, Typography } from 'antd'

import { useI18n } from '../i18n'
import { COMPLAINT_KEYS, type ComplaintKey } from '../pages/vmaxDiagnosisRules'

const { Text } = Typography

export default function VmaxComplaintTabs({
  value,
  onChange,
  disabled,
}: {
  value: ComplaintKey
  onChange: (v: ComplaintKey) => void
  /** 没查过号码时置灰（判据栏在没有数据时点它没有意义） */
  disabled?: boolean
}) {
  const { t } = useI18n()

  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      <Space wrap align="center" size="small">
        <Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxq.complaint.title')}</Text>
        <Segmented
          className="wh-seg"
          disabled={disabled}
          options={COMPLAINT_KEYS.map((k) => ({
            label: t(`vmaxq.complaint.${k}`),
            value: k,
          }))}
          value={value}
          onChange={(v) => onChange(v as ComplaintKey)}
          style={{ background: 'var(--wh-seg-bg)' }}
        />
      </Space>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {t(`vmaxq.complaint.${value}Hint`)}
      </Text>
    </Space>
  )
}
