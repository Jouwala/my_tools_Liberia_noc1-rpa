/* ============================================================================
 * 县维度可用率（?page=avail_county）
 * ----------------------------------------------------------------------------
 * 需求：按 `eflow_site.province_county`（**县**）看本月的可用率，
 *       行 = 县、列 = 2G / 3G / 4G 可用率，日 / 周用**页签**切粒度，能下钻尽下钻。
 *
 * 数据源与口径（后端 backend/services/avail_county_data.py 顶部有完整说明）：
 *   - 站点主数据：主库 `eflow_site`（830 行，按 province_county 分县）
 *   - 可用率：本地 PG 的 UME MS SLA **站点级日表**三张
 *       2G = ..._GSM1day_SITE  「TCH in service rate(%)」
 *       3G = ..._UMTS1day_SITE 「Cell Validity Rate(%)」
 *       4G = ..._FDD1day_SITE  「[FDD]Cell Availability[SDR_ITBBU]」
 *     站点关联按**站点名**（site_id 对不上：实测 4G 重合率仅 4.7%）。
 *
 * ⚠️ 口径与 `avail_ms` / `avail_flm` **不同**，两页数字不可互相印证：
 *     那两页是 SUM(分子)/SUM(分母)（重建库自带的可加分子分母）；
 *     本页是 UME 直接给的站点级比率，**只能站点等权平均**。
 *     页面顶部已显式说明，避免运维把两页数字对不上当成 bug。
 *
 * ⚠️ 数据覆盖有限（实测最早 2026-06-18，当前月可能只有 1~2 天有数据）。
 *     页面显示「数据截至」与「本月有 N 天数据」，让「还没同步」这件事看得见。
 *
 * 下钻三层（AGENTS.md 第三节 1b：每个数字都要可点）：
 *   县 × 制式单元格 → 该县的站点明细 → 某站点的逐日明细；另有该县的 TT 工单。
 *
 * 文件拆分（工作区 AGENTS.md 第三节原则 2：新增文件 ≤500 行）：
 *   本文件                    页面主体：筛选、状态编排、渲染
 *   availCountyTypes.ts       类型与常量
 *   availCountyHelpers.tsx    列定义与纯函数
 *   availCountyExport.ts      Excel 导出
 *   AvailCountyDrillModal.tsx 下钻弹窗
 *   useAvailCountyData.ts     选项 / 矩阵 / 曲线取数
 *   useAvailCountyDrill.ts    下钻状态机
 * ========================================================================== */
import { useCallback, useMemo, useState } from 'react'
import {
  Alert, Button, Col, Empty, InputNumber, Row, Select, Space, Spin, Table, Tabs,
  Tag, Typography,
} from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'

import { useI18n } from '../i18n'
import { WH } from '../theme'
import { CardBase, StatCard } from '../components/cards'
import CalcChainNote from '../components/CalcChainNote'
// 曲线组件与 avail_ms / avail_flm 共用（多序列折线 + 阈值线 + 点可下钻）
import AvailTrend from './AvailTrend'
import type { TrendSeries } from './AvailTrend'
import {
  buildCountyColumns, countyLabel, granLabelKey, isErrorWarn, siteColumns,
  siteDailyColumns, ttColumns, warnKey,
} from './availCounty/availCountyHelpers'
import {
  exportAvailCountyDrill, exportAvailCountyPage,
} from './availCounty/availCountyExport'
import AvailCountyDrillModal from './availCounty/AvailCountyDrillModal'
import { useAvailCountyData } from './availCounty/useAvailCountyData'
import { useAvailCountyDrill } from './availCounty/useAvailCountyDrill'
import {
  CellTarget, Gran, GRANS, MatrixRow, TECHS,
} from './availCounty/availCountyTypes'

const { Text } = Typography

export default function AvailCounty() {
  const { t } = useI18n()

  /* ---- 筛选项 ---- */
  const [thresholdPct, setThresholdPct] = useState(99.65)
  const thr = useMemo(() => Math.round(thresholdPct * 100) / 10000, [thresholdPct])

  /* ---- 页签：日 / 周 ---- */
  const [gran, setGran] = useState<Gran>('day')
  const [month, setMonth] = useState('')
  /** 每个档位各记一个「选中期」（互不干扰） */
  const [valueByGran, setValueByGran] = useState<Record<Gran, string>>({ day: '', week: '' })
  /** 曲线看哪个县（空 = 全网） */
  const [trendCounty, setTrendCounty] = useState('')

  const reqValue = valueByGran[gran]

  const {
    options, matrix, trend, loading, trendLoading, error, curMonth, load,
  } = useAvailCountyData({ gran, month, reqValue, thr, trendCounty })

  const drill = useAvailCountyDrill({
    gran, curMonth, thr,
    matrixValue: matrix?.meta.value || '',
    reqValue,
  })

  /* ---- 曲线上的点 -> 下钻（打开的是那个点自己那一期） ---- */
  const pointTarget = useCallback((tech: string, day: string): CellTarget => ({
    county: trendCounty,
    tech,
    label: `${countyLabel(trendCounty || '__all__', t('availCounty.unmatched'))} · ${tech} · ${day}`,
  }), [trendCounty, t])

  /* ---- 标签：县名是业务原值不翻译；未归属行走 i18n ---- */
  const unmatchedText = t('availCounty.unmatched')
  const rowLabel = useCallback((c: string) => countyLabel(c, unmatchedText), [unmatchedText])

  /* ---- 数字卡：全网三制式的本期可用率（可点 -> 全网下钻） ---- */
  const statCards = useMemo(() => {
    const by = matrix?.summary?.by_tech || {}
    return TECHS.map(tech => {
      const cell = by[tech]
      const v = cell?.availability ?? null
      const below = v != null && v < thr
      return (
        <Col xs={12} sm={8} key={tech}>
          <StatCard
            title={t('availCounty.kpiTech', { tech })}
            value={v == null ? '—' : (v * 100).toFixed(2)}
            suffix={v == null ? '' : '%'}
            accentColor={v == null ? WH.textMuted : (below ? WH.danger : WH.ok)}
            subText={
              matrix
                ? `${t('availCounty.kpiBelow', { n: cell?.counties_below ?? 0, total: cell?.counties_with_data ?? 0 })}`
                : undefined
            }
            onClick={e => drill.openDrill(
              { county: '', tech, label: `${t('availCounty.allNetwork')} · ${tech}` },
              { x: e.clientX, y: e.clientY })}
          />
        </Col>
      )
    })
  }, [matrix, thr, t, drill])

  /* ---- 主表列 ---- */
  const techLabels: Record<string, string> = useMemo(() => ({
    '2G': t('availCounty.tech2G'),
    '3G': t('availCounty.tech3G'),
    '4G': t('availCounty.tech4G'),
  }), [t])

  const columns: ColumnsType<MatrixRow> = useMemo(() => buildCountyColumns(
    matrix?.meta.techs || [...TECHS],
    (row, tech) => drill.openDrill({
      county: row.county, tech,
      label: `${rowLabel(row.county)} · ${techLabels[tech] || tech}`,
    }),
    {
      county: t('availCounty.colCounty'),
      region: t('availCounty.colRegion'),
      sites: t('availCounty.colSites'),
      avail: t('availCounty.colAvail'),
      unmatched: unmatchedText,
      threshold: t('availCounty.threshold'),
    },
    techLabels,
  ), [matrix, drill, rowLabel, techLabels, t, unmatchedText])

  /* ---- 下钻列 ---- */
  const drillSiteCols = useMemo(() => siteColumns(
    drill.target?.tech || '',
    {
      site: t('availCounty.colSite'), siteId: t('availCounty.colSiteId'),
      region: t('availCounty.colRegion'), type: t('availCounty.colSiteType'),
      avail: t('availCounty.colAvail'), days: t('availCounty.colDays'),
    },
    drill.openSiteDaily,
  ), [drill, t])

  const drillDailyCols = useMemo(() => siteDailyColumns(
    [...TECHS],
    { day: t('availCounty.colDay'), avail: t('availCounty.colAvail') },
    techLabels,
  ), [t, techLabels])

  const drillTtCols = useMemo(() => ttColumns({
    ttNo: t('availCounty.colTtNo'), title: t('availCounty.colTitle'),
    severity: t('availCounty.colSeverity'), site: t('availCounty.colSite'),
    status: t('availCounty.colStatus'), occur: t('availCounty.colOccur'),
    handler: t('availCounty.colHandler'), downSites: t('availCounty.colDownSites'),
    rootCause: t('availCounty.colRootCause'),
  }), [t])

  /* ---- 曲线序列（复用 AvailTrend 的数据结构） ---- */
  const trendSeries: TrendSeries[] = useMemo(() => {
    return (trend?.series || []).map(s => ({
      key: s.key,
      values: s.values,
      numerators: s.numerators,
      denominators: s.denominators,
      overall: s.overall,
      below_periods: s.below_periods,
    }))
  }, [trend])

  /* ---- 导出 ---- */
  const exportPage = useCallback(async () => {
    if (!matrix) return
    await exportAvailCountyPage(matrix, trend, {
      trendCounty, techLabels, thresholdPct, rowLabel, t,
    })
  }, [matrix, trend, trendCounty, techLabels, thresholdPct, rowLabel, t])

  const exportDrill = useCallback(async () => {
    if (!drill.drill || !drill.target) return
    await exportAvailCountyDrill(drill.drill, drill.target, {
      modalTab: drill.modalTab, drillValue: drill.drillValue,
      thresholdPct, techLabels, t,
    })
  }, [drill, thresholdPct, techLabels, t])

  /* ---- 页面渲染 ---- */
  const techs = matrix?.meta.techs || [...TECHS]
  const monthOptions = (options?.months || []).map(m => ({ value: m, label: m }))
  const countyOptions = [
    { value: '', label: t('availCounty.allNetwork') },
    ...(options?.counties || []).map(c => ({ value: c.county, label: c.county })),
  ]

  /** 警告码 -> 提示条。失败类用红色，口径类用黄色。 */
  const warnAlerts = (codes: string[], err?: string) => (
    <Space direction="vertical" style={{ width: '100%' }} size={4}>
      {codes.map((code, i) => {
        const k = warnKey(code)
        if (!k) return null
        return (
          <Alert key={`${code}-${i}`} type={isErrorWarn(code) ? 'error' : 'warning'} showIcon
            message={t(k)} description={isErrorWarn(code) && err ? err : undefined} />
        )
      })}
    </Space>
  )

  /** 选项级警告（如后端提示 KPI 表缺失）与选项级错误（接口挂了的真实原因） */
  const optionWarnings = options?.warnings || []
  const optionError = optionWarnings.some(c => isErrorWarn(c)) ? options?.error : undefined

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>

      {/* ① 筛选条 */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap>
          <Select
            style={{ width: 130 }}
            value={curMonth || undefined}
            onChange={v => { setMonth(v); setValueByGran({ day: '', week: '' }) }}
            options={monthOptions}
            placeholder={t('availCounty.colMonth')}
            aria-label={t('availCounty.colMonth')}
          />
          <Tabs
            activeKey={gran}
            onChange={k => setGran(k as Gran)}
            size="small"
            style={{ marginBottom: 0 }}
            items={GRANS.map(g => ({ key: g, label: t(granLabelKey(g)) }))}
          />
          <InputNumber
            value={thresholdPct}
            onChange={v => setThresholdPct(Number(v ?? 99.65))}
            min={0}
            max={100}
            step={0.05}
            addonAfter="%"
            style={{ width: 130 }}
            aria-label={t('availCounty.threshold')}
          />
          <Select
            style={{ width: 190 }}
            value={trendCounty}
            onChange={v => setTrendCounty(v || '')}
            options={countyOptions}
            showSearch
            optionFilterProp="label"
            placeholder={t('availCounty.trendCounty')}
            aria-label={t('availCounty.trendCounty')}
          />
          <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
            {t('common.refresh')}
          </Button>
          <Button
            icon={<DownloadOutlined />}
            onClick={() => void exportPage()}
            disabled={!matrix}
          >
            {t('common.exportExcel')}
          </Button>
        </Space>
      </CardBase>

      {/* ② 失败态：接口出错时必须显式说出来，不能只显示「暂无数据」 */}
      {error && <Alert type="error" showIcon message={t('availCounty.warn.loadFailed')} description={error} />}

      {/* ③ 口径说明：与 avail_ms / avail_flm 口径不同，必须显式说明。
          默认收起（AGENTS.md 三.3b：解释「怎么算的」→ 收起；「算错了/算不全」→ 常驻）。
          这段是纯口径解释，常驻要占 4 行，故收进 CalcChainNote。 */}
      <CalcChainNote
        title={t('availCounty.caliberTitle')}
        sections={[
          { lines: [t('availCounty.caliberNote')] },
          // 「未归属站点」那行是口径问题（为什么有一行不属于任何县），
          // 原先挤在 Tag 的括号里，常驻且难读 —— 挪进说明，Tag 只留短标签。
          ...(matrix?.meta.has_unmatched
            ? [{ title: t('availCounty.note.unmatchedTitle'), lines: [t('availCounty.unmatchedWhy')] }]
            : []),
        ]}
      />

      {/* ④ 数据覆盖提示：本月只同步了 N 天 / 截至某日 */}
      {matrix && (
        <Space wrap size={8}>
          <Tag color="blue">{t('availCounty.dataThrough')} {matrix.meta.data_through || '—'}</Tag>
          <Tag color={matrix.meta.month_covered_count < matrix.meta.month_day_count
            ? 'orange' : 'blue'}>
            {t('availCounty.coveredDays', {
              n: matrix.meta.month_covered_count, total: matrix.meta.month_day_count,
            })}
          </Tag>
          {matrix.meta.has_unmatched && (
            <Tag color="orange">{t('availCounty.unmatchedTag')}</Tag>
          )}
        </Space>
      )}

      {/* ⑤ 数字卡 */}
      <Row gutter={[12, 12]}>{statCards}</Row>

      {/* ⑥ 主表 + 曲线 */}
      <CardBase
        title={t('availCounty.tableTitle')}
        extra={(
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('availCounty.clickHint')}
          </Text>
        )}
      >
        {/* 选项级警告（如 KPI 表缺失）与矩阵级警告合并展示 */}
        {optionWarnings.length ? (
          <div style={{ marginBottom: 'var(--wh-space-sm)' }}>
            {warnAlerts(optionWarnings, optionError)}
          </div>
        ) : null}
        {matrix?.meta.warnings?.length ? (
          <div style={{ marginBottom: 'var(--wh-space-sm)' }}>
            {warnAlerts(matrix.meta.warnings)}
          </div>
        ) : null}

        {/* 曲线：所选县（或全网）三制式走势 */}
        <div style={{ marginBottom: 'var(--wh-space-sm)' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('availCounty.trendCaption', {
              county: trendCounty ? rowLabel(trendCounty) : t('availCounty.allNetwork'),
            })}
          </Text>
          {trendLoading && !trend ? (
            <div style={{ padding: 'var(--wh-space-lg)', textAlign: 'center' }}><Spin /></div>
          ) : (
            <AvailTrend
              categories={trend?.categories || []}
              series={trendSeries}
              thresholdPct={thresholdPct}
              labelOf={k => techLabels[k] || k}
              onPoint={(k, v) => drill.openDrill(pointTarget(k, v), undefined, v)}
              emptyText={t('common.noData')}
              ariaText={t('availCounty.trendAria')}
            />
          )}
        </div>

        {matrix && matrix.rows.length ? (
          <Table
            rowKey="county"
            size="small"
            columns={columns}
            dataSource={matrix.rows}
            loading={loading}
            pagination={false}
            scroll={{ x: 760 }}
          />
        ) : (
          <Empty description={t('common.noData')} />
        )}
      </CardBase>

      {/* ⑦ 下钻弹窗 */}
      <AvailCountyDrillModal
        open={drill.open}
        anchor={drill.anchor}
        target={drill.target}
        drill={drill.drill}
        drillLoading={drill.drillLoading}
        modalTab={drill.modalTab}
        onClose={drill.close}
        onTabChange={drill.changeTab}
        onSiteClick={drill.openSiteDaily}
        onExport={() => void exportDrill()}
        warnKey={warnKey}
        isErrorWarn={isErrorWarn}
        t={t}
        drillSiteCols={drillSiteCols}
        drillDailyCols={drillDailyCols}
        drillTtCols={drillTtCols}
      />
    </div>
  )
}
