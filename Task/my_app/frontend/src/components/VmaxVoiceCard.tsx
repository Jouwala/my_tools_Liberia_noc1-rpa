/* ============================================================================
 * VmaxVoiceCard —— 语音链路卡（CSFB / VoLTE）
 * ============================================================================
 *
 * 【2026-10-31 新增，方案 §4.4；评审意见 3：
 *   「语音投诉：目前主要是 CSFB，不过马上会有 VoLTE，要找 1100 的 SGs 接口记录来判」】
 *
 * CSFB 判据链（全部来自 1100，实测可用）：
 *   SGs 位置更新 → CS Fallback Triggered → Extended Service Request → 回落
 *   寻呼（被叫）单独看，因为「打不进来」和「打不出去」是两条不同的故障。
 *
 * VoLTE 判据（预埋，上线即用）：
 *   1100 出现 QCI=1 承载 / 1300 出现 qci=1 话单。
 *   ⚠ 不能用 qci=0 冒充：实测 qci=0 的 49 条是 DNS 小包。
 *
 * 【为什么把「无 SGs」写成警示而不是 0】
 *   本时段 0 条 SGs 有两种完全不同的含义：
 *     ① 用户在窗口内没打过电话（正常）
 *     ② 该区域 SGs 接口没覆盖/没配，CSFB 根本不可用（严重）
 *   在只有数据的页面上分不清，所以卡片明说「也可能是 SGs 未覆盖」，
 *   并把「本窗口有无起呼」一并展示，让人自己看这两条是否同时成立。
 * ========================================================================== */

import { Space, Statistic, Table, Tag, Typography } from 'antd'

import { useI18n } from '../i18n'
import { CardBase } from './cards'
import { WH } from '../theme'
import { ms, THRESHOLDS, type VoiceResult } from '../pages/vmaxDiagnosisRules'

const { Text } = Typography

export default function VmaxVoiceCard({ voice }: { voice: VoiceResult }) {
  const { t } = useI18n()

  const modeText = voice.mode === 'none'
    ? t('vmaxq.voice.mode.none')
    : t(`vmaxq.voice.mode.${voice.mode}`)
  const modeColor = voice.mode === 'volte' ? 'geekblue' : voice.mode === 'csfb' ? 'purple' : 'default'
  const slow = voice.fallbackMs !== null && voice.fallbackMs > THRESHOLDS.csfbFallback
  const badRate = voice.successRate !== null && voice.successRate < 90

  const cells = [
    { key: 'sgs', label: t('vmaxq.voice.sgs'), value: voice.sgsCount,
      bad: voice.sgsCount === 0 && voice.mode !== 'none' },
    { key: 'trig', label: t('vmaxq.voice.csfbTrigger'), value: voice.csfbTrigger },
    { key: 'esr', label: t('vmaxq.voice.esr'), value: voice.esrCount },
    { key: 'page', label: t('vmaxq.voice.page'), value: voice.pagingCount },
    { key: 'bad', label: t('vmaxq.voice.timeout'), value: voice.badCount, bad: voice.badCount > 0 },
    { key: 'qci1', label: 'QCI=1', value: voice.qci1 },
  ]

  return (
    <CardBase
      level={voice.badCount > 0 ? 'crit' : (slow || badRate) ? 'warn' : 'ok'}
      title={(
        <Space size={6}>
          <span style={{ fontSize: '0.8125rem', fontWeight: 600 }}>{t('vmaxq.voice.card')}</span>
          <Tag color={modeColor} style={{ marginInlineEnd: 0 }}>{modeText}</Tag>
          {slow && <Tag color="orange" style={{ marginInlineEnd: 0 }}>{t('vmaxq.voice.fallbackMs')} {ms(voice.fallbackMs || 0)}</Tag>}
        </Space>
      )}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-sm)' }}>
        {/* 六个计数：CSFB 链的每一环都在这一行里，扫一眼就知道断在哪 */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(104px, 1fr))',
          gap: 8,
        }}>
          {cells.map((c) => (
            <div key={c.key} style={{
              padding: '6px 10px',
              borderRadius: 6,
              background: 'var(--wh-fill-secondary, rgba(127,127,127,0.08))',
            }}>
              <div style={{ fontSize: 11, color: WH.textDim }}>{c.label}</div>
              <Statistic
                value={c.value}
                valueStyle={{
                  fontSize: '1.125rem', fontWeight: 700, lineHeight: 1.3,
                  color: c.bad ? WH.danger : WH.text,
                }}
              />
            </div>
          ))}
        </div>

        {/* 成功率 / 回落耗时：两个「率与时长」类指标，单列一行。
            用带冒号的标签键（vmaxq.voice.estLabel）而不是「标签 + 硬编码冒号」：
            中文是全角「：」、英文是半角「: 」，标点也是文案。
            值单独一个 <Text> 是为了染色（异常值转红/黄），不能塞进模板。 */}
        <Space size={16} wrap>
          <Text style={{ fontSize: 12 }}>
            {t('vmaxq.voice.estLabel')}
            <Text strong style={{ fontSize: 12, color: badRate ? WH.danger : WH.text }}>
              {voice.successRate === null ? '—' : `${voice.successRate}%`}
            </Text>
          </Text>
          <Text style={{ fontSize: 12 }}>
            {t('vmaxq.voice.fallbackMsLabel')}
            <Text strong style={{ fontSize: 12, color: slow ? WH.warn : WH.text }}>
              {voice.fallbackMs === null ? '—' : ms(voice.fallbackMs)}
            </Text>
          </Text>
        </Space>

        {/* 无语音活动 / 无 SGs 的明确说明（见文件头「为什么写成警示」） */}
        {voice.mode === 'none' && (
          <Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxq.voice.noActivity')}</Text>
        )}
        {voice.mode !== 'none' && voice.sgsCount === 0 && (
          <Text type="warning" style={{ fontSize: 12 }}>{t('vmaxq.voice.noSgs')}</Text>
        )}

        {/* 回落链明细：只收语音相关的四类过程，766 条全表会把卡撑爆 */}
        {voice.steps.length > 0 && (
          <Table
            rowKey={(r, i) => `${r.time}-${r.proc}-${i}`}
            size="small"
            bordered
            columns={[
              { title: t('vmaxq.voice.stepTime'), dataIndex: 'time', width: 150,
                render: (v: string) => (v ? v.slice(11, 19) : '—') },
              { title: t('vmaxq.voice.stepInterface'), dataIndex: 'iface', width: 92 },
              { title: t('vmaxq.voice.stepProc'), dataIndex: 'proc', ellipsis: true },
              { title: t('vmaxq.voice.stepCause'), dataIndex: 'cause', ellipsis: true,
                render: (v: string) => (v === '—' ? v : <Text style={{ fontSize: 12 }}>{v}</Text>) },
              {
                title: t('vmaxq.voice.stepStatus'), dataIndex: 'status', width: 92,
                render: (v: string) => (
                  <Tag color={v === 'Success' ? 'green' : v === 'Timeout' ? 'orange' : v === 'Failure' ? 'red' : 'default'}
                    style={{ marginInlineEnd: 0 }}>
                    {v}
                  </Tag>
                ),
              },
              { title: t('vmaxq.voice.stepCell'), dataIndex: 'cell', width: 160, ellipsis: true },
            ]}
            dataSource={voice.steps.slice(0, 40)}
            pagination={voice.steps.length > 10 ? { pageSize: 10, size: 'small' } : false}
            scroll={{ x: 760 }}
          />
        )}

        <Text type="secondary" style={{ fontSize: 11 }}>{t('vmaxq.voice.voltePending')}</Text>
      </div>
    </CardBase>
  )
}
