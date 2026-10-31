/* ============================================================================
 * VmaxGameCard —— 游戏会话识别
 * ============================================================================
 *
 * 【2026-10-31 新增，方案 §4.3；评审意见 2：
 *   「『游戏』页签不能删 —— XDR 话单里有时候会有 egame 之类的」】
 *
 * 三档识别（优先级从高到低）：
 *   ① 上游 service ∈ {Game, Gaming}
 *   ② app_content_name / subservice 关键词库（含 egame / e-game）
 *   ③ 兜底：名称含 game / play 且 service ≠ Network Storage → 标「疑似」
 *
 * 【必须避开的坑（实测已见到）】
 *   PALMPLAYSTORE（25 条）、GOOGLEPLAY_API（1 条）**是应用商店，不是游戏**。
 *   黑名单在识别之前生效 —— 否则「③ 兜底」会把应用商店全收进来，
 *   结果就是「用户明明在下载应用，诊断说他打了 25 局游戏」。
 *
 * 【空态不删页签】
 *   页签结构本身是「这个面板长什么样」的信息，不该随数据有无消失；
 *   空的时候说明「我们在找什么」（识别关键词可展开看），
 *   这样现场就能判断「是这个应用不在库里」还是「用户真没玩」。
 * ========================================================================== */

import { Collapse, Empty, Space, Table, Tag, Typography } from 'antd'

import { renderI18nList } from '../renderI18n'
import { useI18n } from '../i18n'
import { CardBase } from './cards'
import { WH } from '../theme'
import { GAME_KEYWORDS, pct, type GameResult } from '../pages/vmaxDiagnosisRules'

const { Text } = Typography

export default function VmaxGameCard({ game }: { game: GameResult }) {
  const { t } = useI18n()
  const has = game.totalSessions > 0

  const keywordsPanel = (
    <Collapse
      ghost
      size="small"
      items={[{
        key: 'kw',
        label: (
          <Text style={{ fontSize: 12 }}>
            {/* 括号是文案的一部分：中文全角「（）」、英文半角「 (n)」 */}
            {t('vmaxq.game.keywordsCount', { n: GAME_KEYWORDS.length })}
          </Text>
        ),
        children: (
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            <Text type="secondary" style={{ fontSize: 11 }}>{t('vmaxq.game.keywordsHint')}</Text>
            <Space size={4} wrap>
              {GAME_KEYWORDS.map((k) => (
                <Tag key={k} style={{ marginInlineEnd: 0, fontSize: 11 }}>{k}</Tag>
              ))}
            </Space>
          </Space>
        ),
      }]}
    />
  )

  return (
    <CardBase
      level={has ? 'warn' : 'default'}
      title={t('vmaxq.game.card')}
      extra={(
        <Text type="secondary" style={{ fontSize: 11 }}>
          {has ? t('vmaxq.game.found', { n: game.totalSessions }) : t('vmaxq.game.none')}
        </Text>
      )}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-xs)' }}>
        {has ? (
          <Table
            rowKey="app"
            size="small"
            bordered
            columns={[
              {
                title: t('vmaxq.ott.app'),
                dataIndex: 'app',
                ellipsis: true,
                render: (v: string, r) => (
                  <Space size={4}>
                    <span>{v}</span>
                    {r.tier === 'suspect' && (
                      <Tag color="orange" style={{ marginInlineEnd: 0, fontSize: 10 }}>
                        {t('vmaxq.game.suspect')}
                      </Tag>
                    )}
                  </Space>
                ),
              },
              { title: t('vmaxq.game.traffic'), dataIndex: 'records', width: 90, align: 'right' as const,
                render: (v: number) => t('vmaxq.game.times', { n: v }) },
              { title: t('vmaxq.game.avgRtt'), dataIndex: 'avgRtt', width: 100, align: 'right' as const,
                render: (v: number) => (v > 0 ? `${v} ms` : '—') },
              { title: t('vmaxq.game.jitter'), dataIndex: 'jitter', width: 90, align: 'right' as const,
                render: (v: number) => (v > 0 ? `${v} ms` : '—') },
              { title: t('vmaxq.game.retrans'), dataIndex: 'retransRate', width: 92, align: 'right' as const,
                render: (v: number) => (v > 0 ? pct(v) : '—') },
            ]}
            dataSource={game.hits}
            pagination={false}
            scroll={{ x: 560 }}
          />
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={<Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxq.game.none')}</Text>}
            style={{ margin: '4px 0' }}
          />
        )}

        <Space direction="vertical" size={2}>
          {renderI18nList(t, game.evidence).map((line, i) => (
            <Text key={i} style={{ fontSize: 12, color: WH.textMuted }}>· {line}</Text>
          ))}
        </Space>

        {keywordsPanel}
      </div>
    </CardBase>
  )
}
