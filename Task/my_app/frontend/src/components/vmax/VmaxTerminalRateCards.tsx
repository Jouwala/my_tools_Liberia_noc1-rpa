/* ============================================================================
 * VmaxTerminalRateCards —— 终端画像 + 限速推断（CCA 工作台区域 2）
 * ============================================================================
 * 终端画像：IMEI/机型/制式/APN/QCI（只回答「什么终端、在什么网络」，
 *   不证明载波聚合/MIMO 等终端能力——边界写在卡内）。
 * 限速推断：1300 throughput_max 的观测天花板（间接证据，≠ Gx 授权值）；
 *   样本不足显式说无法推断，不编数字。
 * 纯展示：数字全部来自 analyzeTerminal / analyzeRateCeiling 的既有字段。
 * ========================================================================== */

import { Descriptions, Table, Typography } from 'antd'

import { useI18n } from '../../i18n'
import { renderI18n } from '../../renderI18n'
import { CardBase } from '../cards'
import type {
  RateCeilingResult, TerminalProfile,
} from '../../pages/vmaxDiagnosisRules'

const { Text } = Typography

export function VmaxTerminalCard({ profile }: { profile: TerminalProfile | null }) {
  const { t } = useI18n()
  const dash = '—'
  const items = profile ? [
    { label: t('vmaxq.term.imei'), children: profile.imei || dash },
    { label: t('vmaxq.term.model'), children: profile.model || dash },
    { label: t('vmaxq.term.brand'), children: profile.brand || dash },
    { label: t('vmaxq.term.rat'), children: profile.rat || dash },
    { label: t('vmaxq.term.apn'), children: profile.apn || dash },
    { label: t('vmaxq.term.qci'), children: profile.qciMain || dash },
  ] : []
  return (
    <CardBase title={t('vmaxq.term.title')}>
      {profile && profile.samples > 0 ? (
        <>
          <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }} items={items} />
          <Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxq.term.boundary')}</Text>
        </>
      ) : (
        <Text type="secondary">{t('vmaxq.term.empty')}</Text>
      )}
    </CardBase>
  )
}

export function VmaxRateCard({ rate }: { rate: RateCeilingResult | null }) {
  const { t } = useI18n()
  const columns = [
    { title: t('vmaxq.rate.qci'), dataIndex: 'qci', width: 80 },
    { title: t('vmaxq.rate.samples'), dataIndex: 'samples', width: 90 },
    { title: t('vmaxq.rate.dl'), dataIndex: 'dlP90Kbps', width: 130,
      render: (v: number) => (v > 0 ? `${v} Kbps` : '—') },
    { title: t('vmaxq.rate.dlPeak'), dataIndex: 'dlPeakKbps', width: 130,
      render: (v: number) => (v > 0 ? `${v} Kbps` : '—') },
    { title: t('vmaxq.rate.ul'), dataIndex: 'ulP90Kbps', width: 130,
      render: (v: number) => (v > 0 ? `${v} Kbps` : '—') },
    { title: t('vmaxq.rate.inferable'), dataIndex: 'inferable', width: 110,
      render: (v: boolean) => (v ? t('vmaxq.rate.yes') : t('vmaxq.rate.no')) },
  ]
  return (
    <CardBase title={t('vmaxq.rate.title')}>
      {rate && rate.rows.length > 0 ? (
        <Table
          size="small"
          rowKey="qci"
          columns={columns}
          dataSource={rate.rows}
          pagination={false}
          scroll={{ x: 640 }}
        />
      ) : (
        <Text type="secondary">{t('vmaxq.rate.empty')}</Text>
      )}
      {rate && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 6 }}>
          {rate.evidence.map((e, i) => (
            <Text key={i} type="secondary" style={{ fontSize: 12 }}>
              · {renderI18n(t, e)}
            </Text>
          ))}
        </div>
      )}
    </CardBase>
  )
}
