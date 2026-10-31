/* ============================================================================
 * VmaxOttCard —— OTT 语音视频（微信 / WhatsApp）
 * ============================================================================
 *
 * 【2026-10-31 新增，方案 §4.7；评审意见 6：
 *   「是不是没有考虑 SIP 协议的如微信/WhatsApp 语音视频通话的分析呢」】
 *
 * 先把边界说清楚（这一段是这块卡存在的最重要原因）：
 *   实测 2026-10-31，1300 全量扫描 `protocol ∈ {SIP, RTP}` **命中 0 条**，
 *   `service=VoIP` 的 20 条全部是 `subservice=STUN`。
 *   → 本平台**没有** OTT 应用的信令识别能力。
 *
 * 所以这里给的是**三路间接判据**，并明确标注「只能回答网络侧问题」：
 *   ① STUN 会话      —— WebRTC 打洞（微信/WhatsApp 通话必经），能判「有没有通话」
 *   ② 长连接低码率    —— QUIC / WHATSAPP_* 长连接 + 时长 ≥ 10s + 码率低
 *   ③ 通话期抖动      —— 会话内 dl_avg_rtt 的均值与标准差，对照非通话时段基线
 *
 * 【为什么要把「能力边界」做成显眼的 Alert 而不是小字】
 *   排障的人如果不知道这条边界，会拿「网络侧质量正常」去回复用户
 *   「你的微信没问题」，然后被用户打回来。边界必须比结论更显眼。
 * ========================================================================== */

import { Alert, Empty, Space, Statistic, Table, Tag, Typography } from 'antd'

import { renderI18n, renderI18nList } from '../renderI18n'
import { useI18n } from '../i18n'
import { CardBase } from './cards'
import { WH } from '../theme'
import { durText, pct, THRESHOLDS, type I18nText, type OttResult } from '../pages/vmaxDiagnosisRules'

const { Text } = Typography

export default function VmaxOttCard({ ott }: { ott: OttResult }) {
  const { t } = useI18n()

  const badRtt = ott.avgDlRtt > 150
  const badJitter = ott.jitter > 60
  const badRetrans = ott.retransRate > THRESHOLDS.retrans

  // value 允许 I18nText：时长这类「带单位」的值单位本身是文案（中文「204 分 6 秒」
  // vs 英文 "204 min 6 s"），不能在规则层拼成字符串。
  const stats: { key: string; label: string; value: number | I18nText; bad: boolean; suffix: string }[] = [
    { key: 'n', label: t('vmaxq.ott.sessions'), value: ott.totalSessions, bad: false, suffix: '' },
    { key: 'dur', label: t('vmaxq.ott.duration'), value: durText(ott.totalDurationS), bad: false, suffix: '' },
    { key: 'rtt', label: t('vmaxq.ott.rtt'), value: ott.avgDlRtt, bad: badRtt, suffix: ' ms' },
    { key: 'jit', label: t('vmaxq.ott.jitter'), value: ott.jitter, bad: badJitter, suffix: ' ms' },
    { key: 'rt', label: t('vmaxq.ott.retrans'), value: ott.retransRate, bad: badRetrans, suffix: '%' },
  ]

  return (
    <CardBase
      level={ott.totalSessions === 0 ? 'default' : (badRtt || badJitter || badRetrans) ? 'warn' : 'ok'}
      title={t('vmaxq.ott.card')}
      extra={!!ott.baselineRtt && (
        <Tag style={{ marginInlineEnd: 0 }}>
          baseline {ott.baselineRtt} ms
        </Tag>
      )}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-sm)' }}>
        {/* 能力边界必须比结论更显眼 —— 见文件头说明 */}
        <Alert
          type="info"
          showIcon
          message={t('vmaxq.ott.limitTitle')}
          description={t('vmaxq.ott.limitBody')}
          style={{ padding: '6px 12px' }}
        />

        {ott.totalSessions === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={<Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxq.ott.noSession')}</Text>}
            style={{ margin: '4px 0' }}
          />
        ) : (
          <>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(108px, 1fr))',
              gap: 8,
            }}>
              {stats.map((s) => (
                <div key={s.key} style={{
                  padding: '6px 10px', borderRadius: 6,
                  background: 'var(--wh-fill-secondary, rgba(127,127,127,0.08))',
                }}>
                  <div style={{ fontSize: 11, color: WH.textDim }}>{s.label}</div>
                  <Statistic
                    value={typeof s.value === 'string' ? s.value : renderI18n(t, s.value)}
                    suffix={<span style={{ fontSize: 11 }}>{s.suffix}</span>}
                    valueStyle={{
                      fontSize: '1.125rem', fontWeight: 700, lineHeight: 1.3,
                      color: s.bad ? WH.danger : WH.text,
                    }}
                  />
                </div>
              ))}
            </div>

            <Table
              rowKey={(r) => `${r.startTime}-${r.app}`}
              size="small"
              bordered
              columns={[
                { title: t('vmaxq.ott.startTime'), dataIndex: 'startTime', width: 150,
                  render: (v: string) => v.slice(11, 19) },
                { title: t('vmaxq.ott.app'), dataIndex: 'app', ellipsis: true },
                { title: t('vmaxq.ott.durSec'), dataIndex: 'durationS', width: 90, align: 'right' as const },
                { title: t('vmaxq.ott.dlTraffic'), dataIndex: 'dlTraffic', width: 96, align: 'right' as const },
                { title: t('vmaxq.ott.dlRtt'), dataIndex: 'dlRtt', width: 96, align: 'right' as const,
                  render: (v: number) => (v > 0 ? v : '—') },
                { title: t('vmaxq.ott.ulRtt'), dataIndex: 'ulRtt', width: 96, align: 'right' as const,
                  render: (v: number) => (v > 0 ? v : '—') },
                { title: t('vmaxq.ott.retrans'), dataIndex: 'retransRate', width: 92, align: 'right' as const,
                  render: (v: number) => (v > 0 ? pct(v) : '—') },
              ]}
              dataSource={ott.sessions.slice(0, 30)}
              pagination={ott.sessions.length > 10 ? { pageSize: 10, size: 'small' } : false}
              scroll={{ x: 720 }}
            />
          </>
        )}

        <Space direction="vertical" size={2}>
          {renderI18nList(t, ott.evidence).map((line, i) => (
            <Text key={i} style={{ fontSize: 12, color: WH.textMuted }}>· {line}</Text>
          ))}
        </Space>
      </div>
    </CardBase>
  )
}
