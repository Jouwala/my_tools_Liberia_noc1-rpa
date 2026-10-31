/* ============================================================================
 * VmaxRadioPanel —— 无线质量专项面板（Radio 页签）
 * ============================================================================
 *
 * 【为什么要单独做这张面板 —— 2026-10-31】
 *
 * 改版前 Radio 页签直接挂了 VmaxXdrRecordsPanel（按 XDR 分表查原始话单）。
 * 那个面板是给「XDR 记录」这种通用场景用的：要自己选表、选时间、点查询，
 * 查出来是一张几千行的原始表。它回答不了本页签该回答的问题：
 *
 *   「用户投诉的这段时间，空口到底好不好？差在哪个小区？什么时候差？」
 *
 * 更糟的是：诊断结论页已经算出「无线质量 62 分」，用户点进 Radio 页签
 * 却看到一个需要重新查询的原始表 —— 分数和页签之间没有解释关系。
 *
 * 【本面板的原则】
 *   1. 不重新取数：直接吃诊断接口已经拉回来的 RAN(32) 行。
 *      同一个窗口、同一批采样，才不会和评分卡自相矛盾（见 analyzeRadio 注释）。
 *   2. 先给结论，再给依据：一条结论 + 若干判据，和诊断卡同一套排版语言。
 *   3. 边缘值优先：P10（最差 10% 采样）比均值更能解释投诉，
 *      所以卡片、趋势、表格三处都把 P10 摆在均值旁边。
 *   4. 原始下钻不丢，但折叠起来：需要跨窗口查单条话单时才展开。
 *
 * 【为什么趋势用图、明细用表】
 *   趋势看「什么时候开始差」，折线最直观；
 *   逐小区看「哪个小区差」，是离散对象比较，表格能直接排序和染色。
 *   证据时间线那边坚持用表，是因为它要"同一分钟四列同时可见"，此处不需要。
 * ========================================================================== */

import { useMemo, useState } from 'react'
import {
  Collapse, Empty, Space, Table, Tag, Tooltip, Typography,
} from 'antd'
import ReactECharts from 'echarts-for-react'

import { useI18n } from '../i18n'
import { renderI18n } from '../renderI18n'
import { CardBase } from './cards'
import StatCard from './StatCard'
import VmaxXdrRecordsPanel from './VmaxXdrRecordsPanel'
import {
  axisLabel, axisLine, darkTooltip, splitLine, useTheme, WH,
} from '../theme'
import { hhmm, type RadioAnalysis, type RadioCell } from '../pages/vmaxDiagnosisRules'

const { Text } = Typography

/** 电平/质量分档色。与 THRESHOLDS 同源的判据在规则层，这里只负责显示 */
const LEVEL_COLOR: Record<RadioCell['level'], string> = {
  bad: WH.danger,
  warn: WH.warn,
  ok: WH.ok,
}

/** 给数值染色：RSRP 越接近 0 越好，SINR/CQI 越大越好 */
function metricColor(v: number, thresholds: [number, number], higherIsBetter = true): string {
  if (!v) return WH.textDim
  const [bad, warn] = thresholds
  if (higherIsBetter) {
    if (v < bad) return WH.danger
    if (v < warn) return WH.warn
    return WH.ok
  }
  // RSRP 这类"越小越差"
  if (v < bad) return WH.danger
  if (v < warn) return WH.warn
  return WH.ok
}

export default function VmaxRadioPanel({
  analysis,
  loading,
  msisdn,
}: {
  analysis: RadioAnalysis | null
  loading?: boolean
  msisdn: string
}) {
  const { t } = useI18n()
  const { isDark } = useTheme()
  const [focusCell, setFocusCell] = useState<string | null>(null)

  const buckets = analysis?.buckets || []
  const cells = analysis?.cells || []

  /* ---- 趋势图：RSRP 均值 + P10 用左轴，SINR 用右轴 ----
     两个量纲差一个数量级（dBm 是负值、dB 是正数），必须双轴，
     否则 SINR 那条线会被压成一条直线看不见。 */
  const trendOption = useMemo(() => {
    const minutes = buckets.map((b) => hhmm(b.minute))
    return {
      backgroundColor: 'transparent',
      grid: { left: 48, right: 48, top: 34, bottom: 28 },
      tooltip: {
        trigger: 'axis',
        ...darkTooltip(isDark),
      },
      legend: {
        data: [t('vmaxq.radio.trendRsrp'), t('vmaxq.radio.trendP10'), t('vmaxq.radio.trendSinr')],
        textStyle: { color: isDark ? '#aebbd4' : '#3f5468', fontSize: 11 },
        top: 2,
      },
      xAxis: {
        type: 'category',
        data: minutes,
        axisLabel: axisLabel(isDark),
        axisLine: axisLine(isDark),
      },
      yAxis: [
        {
          type: 'value',
          name: 'dBm',
          nameTextStyle: { color: isDark ? '#aebbd4' : '#3f5468', fontSize: 10 },
          axisLabel: axisLabel(isDark),
          axisLine: axisLine(isDark),
          splitLine: splitLine(isDark),
        },
        {
          type: 'value',
          name: 'dB',
          nameTextStyle: { color: isDark ? '#aebbd4' : '#3f5468', fontSize: 10 },
          axisLabel: axisLabel(isDark),
          axisLine: axisLine(isDark),
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: t('vmaxq.radio.trendRsrp'),
          type: 'line',
          smooth: true,
          showSymbol: buckets.length <= 40,
          data: buckets.map((b) => b.rsrpAvg),
          lineStyle: { width: 2, color: WH.teal },
          itemStyle: { color: WH.teal },
        },
        {
          name: t('vmaxq.radio.trendP10'),
          type: 'line',
          smooth: true,
          showSymbol: buckets.length <= 40,
          // 边缘线用虚线：它和均值是同一量纲，画在一起才看得出"均值掩盖了边缘"
          data: buckets.map((b) => b.rsrpP10),
          lineStyle: { width: 2, type: 'dashed', color: WH.danger },
          itemStyle: { color: WH.danger },
        },
        {
          name: t('vmaxq.radio.trendSinr'),
          type: 'line',
          yAxisIndex: 1,
          smooth: true,
          showSymbol: buckets.length <= 40,
          data: buckets.map((b) => b.sinrAvg),
          lineStyle: { width: 2, color: WH.indigo },
          itemStyle: { color: WH.indigo },
        },
      ],
    }
  }, [buckets, isDark, t])

  /* ---- 逐小区表 ---- */
  const cellColumns = [
    {
      title: t('vmaxq.radio.col.cell'),
      dataIndex: 'cell',
      ellipsis: true,
      render: (v: string, r: RadioCell) => (
        <Space size={4}>
          <span style={{ color: LEVEL_COLOR[r.level] }}>●</span>
          <span style={{ fontFamily: 'monospace' }}>{v || t('vmaxq.radio.noCell')}</span>
        </Space>
      ),
    },
    { title: t('vmaxq.radio.col.samples'), dataIndex: 'samples', width: 80, align: 'right' as const },
    {
      title: t('vmaxq.radio.col.rsrpAvg'),
      dataIndex: 'rsrpAvg',
      width: 100,
      align: 'right' as const,
      render: (v: number) => (
        <span style={{ color: metricColor(v, [-110, -100]) }}>
          {v ? `${v}` : '—'} {v ? t('vmaxq.radio.unit.dbm') : ''}
        </span>
      ),
    },
    {
      title: t('vmaxq.radio.col.rsrpP10'),
      dataIndex: 'rsrpP10',
      width: 100,
      align: 'right' as const,
      render: (v: number) => (
        <span style={{ color: metricColor(v, [-110, -100]), fontWeight: 600 }}>
          {v ? `${v}` : '—'} {v ? t('vmaxq.radio.unit.dbm') : ''}
        </span>
      ),
    },
    {
      title: t('vmaxq.radio.col.sinr'),
      dataIndex: 'sinrAvg',
      width: 100,
      align: 'right' as const,
      render: (v: number) => (
        <span style={{ color: metricColor(v, [0, 5]) }}>
          {v ? `${v}` : '—'} {v ? t('vmaxq.radio.unit.db') : ''}
        </span>
      ),
    },
    {
      title: t('vmaxq.radio.col.cqi'),
      dataIndex: 'cqiAvg',
      width: 90,
      align: 'right' as const,
      render: (v: number) => <span>{v || '—'}</span>,
    },
  ]

  /* ---------- 空态：必须说清楚"为什么没有无线数据" ---------- */
  if (!analysis || analysis.samples === 0) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
        <CardBase title={t('vmaxq.radio.title')}>
          {loading ? (
            <div style={{ textAlign: 'center', padding: 40 }}>
              <Text type="secondary">{t('vmaxq.diag.loading')}</Text>
            </div>
          ) : (
            <Empty
              description={(
                <Space direction="vertical" size={4}>
                  <Text>{renderI18n(t, analysis?.headline)}</Text>
                  {!!analysis?.basis.length && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {renderI18n(t, analysis.basis[0])}
                    </Text>
                  )}
                  <Text type="secondary" style={{ fontSize: 12 }}>{t('vmaxq.radio.noData')}</Text>
                </Space>
              )}
            />
          )}
        </CardBase>
        <RawDrilldown msisdn={msisdn} />
      </div>
    )
  }

  const levelTag = analysis.level === 'bad' ? 'red' : analysis.level === 'warn' ? 'orange' : 'green'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>
      {/* ① 结论条 —— 与诊断卡同一排版语言：先给一句话，再逐条给判据 */}
      <CardBase
        title={t('vmaxq.radio.title')}
        extra={(
          <Text type="secondary" style={{ fontSize: 11 }}>
            {t('vmaxq.radio.source', { n: analysis.samples })}
          </Text>
        )}
      >
        <Space size={8} align="start" style={{ marginBottom: 8 }}>
          <Tag color={levelTag} style={{ marginInlineEnd: 0, fontSize: 12 }}>
            {renderI18n(t, analysis.headline)}
          </Tag>
          {!!analysis.worstCell && (
            <Text style={{ fontSize: 12, color: WH.textMuted, fontFamily: 'monospace' }}>
              {analysis.worstCell}
            </Text>
          )}
        </Space>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {analysis.basis.map((b, i) => (
            <Text key={i} style={{ fontSize: 12, color: WH.textMuted }}>
              · {renderI18n(t, b)}
            </Text>
          ))}
        </div>
      </CardBase>

      {/* ② KPI 卡 —— 均值和 P10 成对出现，避免"均值好看"误导 */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
        gap: 'var(--wh-space-sm)',
      }}>
        <StatCard
          title={t('vmaxq.radio.samples')}
          value={analysis.samples}
          accentColor={WH.teal}
          subText={analysis.rats.map((r) => `${r.name} ${r.n}`).join(' · ')}
        />
        <StatCard
          title={t('vmaxq.radio.rsrpAvg')}
          value={analysis.rsrpAvg}
          suffix={t('vmaxq.radio.unit.dbm')}
          accentColor={metricColor(analysis.rsrpAvg, [-110, -100])}
        />
        <StatCard
          title={t('vmaxq.radio.rsrpP10')}
          value={analysis.rsrpP10}
          suffix={t('vmaxq.radio.unit.dbm')}
          accentColor={metricColor(analysis.rsrpP10, [-110, -100])}
          subText={t('vmaxq.radio.p10Hint')}
        />
        <StatCard
          title={t('vmaxq.radio.sinrAvg')}
          value={analysis.sinrAvg}
          suffix={t('vmaxq.radio.unit.db')}
          accentColor={metricColor(analysis.sinrAvg, [0, 5])}
        />
        <StatCard
          title={t('vmaxq.radio.cqiAvg')}
          value={analysis.cqiAvg || '—'}
          accentColor={WH.indigo}
        />
      </div>

      {/* ③ 趋势：回答"什么时候开始差" */}
      {buckets.length > 0 && (
        <CardBase
          title={t('vmaxq.radio.trend')}
          extra={<Text type="secondary" style={{ fontSize: 11 }}>{t('vmaxq.radio.trendHint')}</Text>}
        >
          <ReactECharts option={trendOption} style={{ height: 300 }} notMerge />
        </CardBase>
      )}

      {/* ④ 逐小区：回答"哪个小区差" */}
      <CardBase
        title={t('vmaxq.radio.cells')}
        extra={<Text type="secondary" style={{ fontSize: 11 }}>{t('vmaxq.radio.cellsHint')}</Text>}
      >
        {cells.length ? (
          <Table
            rowKey="cell"
            size="small"
            bordered
            columns={cellColumns}
            dataSource={cells}
            pagination={cells.length > 15 ? { pageSize: 15, showSizeChanger: false, size: 'small' } : false}
            scroll={{ x: 620 }}
            onRow={(r) => ({
              onClick: () => setFocusCell(focusCell === r.cell ? null : r.cell),
              style: {
                cursor: 'pointer',
                background: focusCell === r.cell
                  ? 'color-mix(in srgb, var(--wh-teal) 10%, transparent)'
                  : undefined,
              },
            })}
          />
        ) : (
          <Text type="secondary">{t('vmaxq.radio.noCell')}</Text>
        )}
        {focusCell && (
          <div style={{ marginTop: 8 }}>
            <Space size={6} wrap>
              <Text strong style={{ fontSize: 12, fontFamily: 'monospace' }}>{focusCell}</Text>
              <Tag
                color={cells.find((c) => c.cell === focusCell)?.level === 'bad' ? 'red'
                  : cells.find((c) => c.cell === focusCell)?.level === 'warn' ? 'orange' : 'green'}
                style={{ marginInlineEnd: 0 }}
              >
                {t(`vmaxq.diag.level${(() => {
                  const c = cells.find((x) => x.cell === focusCell)
                  return c?.level === 'bad' ? 'Bad' : c?.level === 'warn' ? 'Warn' : 'Good'
                })()}`)}
              </Tag>
            </Space>
          </div>
        )}
      </CardBase>

      <RawDrilldown msisdn={msisdn} />
    </div>
  )
}

/** 原始下钻：保留能力但不占视线（默认折叠） */
function RawDrilldown({ msisdn }: { msisdn: string }) {
  const { t } = useI18n()
  return (
    <Collapse
      items={[{
        key: 'raw',
        label: (
          <Space size={6}>
            <Text strong style={{ fontSize: 12 }}>{t('vmaxq.radio.raw')}</Text>
            <Tooltip title={t('vmaxq.radio.rawHint')}>
              <Text type="secondary" style={{ fontSize: 11 }}>{t('vmaxq.radio.rawHint')}</Text>
            </Tooltip>
          </Space>
        ),
        children: <VmaxXdrRecordsPanel msisdn={msisdn} />,
      }]}
    />
  )
}
