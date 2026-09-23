/* ============================================================================
 * 新功能页模板 —— 照抄本文件即可自动获得项目统一风格
 * ============================================================================
 *
 * ⚠️ 本文件不是「示例」，是**可复制的最小骨架**。新增页面时：
 *   1. 复制本文件为 `frontend/src/pages/YourPage.tsx`
 *   2. 把 `TemplatePage` 改成你的组件名、`tpl.*` 改成你的 i18n 键前缀
 *   3. 三处同步登记（漏一处手册就和界面对不上）：
 *      - `frontend/src/App.tsx` 菜单数组
 *      - `frontend/src/i18n.tsx` 的 zh 与 en **两处**字典
 *      - `docs/manual/11-feature-guide.md` 按导航顺序加一节
 *
 * 本文件演示了「项目统一」的全部要素，每处都标了为什么：
 *   ✅ 卡片一律用 components/cards（不 import antd 的 Card）
 *   ✅ 导出 Excel 一律用 utils/excelReport（不裸写 xlsx）
 *   ✅ 文案一律走 t()，颜色一律走 theme 令牌
 *   ✅ 下钻弹窗用 DraggableClickModal
 *   ✅ 图表取色分两层：DOM 用 WH，ECharts 用 DARK/LIGHT 实值
 * ========================================================================== */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Col, DatePicker, Empty, Input, Row, Select, Space, Table, Tag, Typography } from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import ReactECharts from 'echarts-for-react'

import { useI18n } from '../i18n'
import {
  WH, useTheme, cardStyle,
  axisLabel, axisLine, darkTooltip, splitLine,
} from '../theme'
import { CardBase, StatCard } from '../components/cards'
import DraggableClickModal from '../components/DraggableClickModal'
import { exportAoaReport } from '../utils/excelReport'
// 你的接口封装写进 api.ts 后再 import，不要在本页裸写 fetch
// import { getTemplateOverview } from '../api'

const { Text } = Typography

/* ---- 类型（与后端返回结构对齐） ---- */
type Row0 = { day: string; site_id: string; site_name: string; value: number }

/** 统一空值展示：- 而不是 undefined / null */
const fmt = (v: unknown) => (v == null || v === '' ? '-' : String(v))

export default function TemplatePage() {
  const { t } = useI18n()
  // 图表必须知道当前主题，才能取 DARK/LIGHT 实值（canvas 解析不了 CSS 变量）
  const { isDark } = useTheme()

  /* ---- 筛选条件 ---- */
  const [start, setStart] = useState<Dayjs | null>(dayjs().subtract(30, 'day'))
  const [end, setEnd] = useState<Dayjs | null>(dayjs())
  const [region, setRegion] = useState('')
  const [keyword, setKeyword] = useState('')
  const [regions, setRegions] = useState<string[]>([])

  /* ---- 数据与状态：loading / error / data 三件套是页面标配 ---- */
  const [data, setData] = useState<Row0[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  /* ---- 下钻弹窗 ---- */
  const [open, setOpen] = useState(false)
  const [drillRows, setDrillRows] = useState<Row0[]>([])
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)

  /* ---- 取数：所有失败都要落到 error 上并渲染 <Alert>，不要静默 ---- */
  const load = useCallback(async () => {
    if (!start || !end) return
    setLoading(true)
    setError('')
    try {
      // 换成真实调用：const r = await getTemplateOverview({ ... })
      // setData(r.data?.rows || [])
      setData([])
    } catch (e: any) {
      setError(e?.message || String(e))
      setData([])
    } finally {
      setLoading(false)
    }
  }, [start, end, region, keyword])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    // 筛选项也走 api.ts，失败不要阻塞页面
    // getTemplateFilters().then(r => setRegions(r.data?.regions || [])).catch(() => undefined)
    setRegions([])
  }, [])

  /* ---- 前端过滤：与卡片联动，保持与后端筛选口径一致 ---- */
  const rows = useMemo(() => {
    if (!keyword.trim()) return data
    const q = keyword.toLowerCase()
    return data.filter(r => Object.values(r).some(v => v != null && String(v).toLowerCase().includes(q)))
  }, [data, keyword])

  /* ---- 汇总数字 ---- */
  const total = useMemo(() => rows.reduce((s, r) => s + (r.value || 0), 0), [rows])
  const affected = useMemo(() => new Set(rows.map(r => r.site_id)).size, [rows])

  /* ---- 图表配置 ----
   * ⚠️ 最容易犯的错：写成 color: WH.text。
   * WH 是 CSS 变量字符串 'var(--wh-text)'，canvas 解析不了 → 图例看不清。
   * 必须用 isDark 取实值（或 LIGHT/DARK 里的具体色）。
   */
  const chartOption = useMemo(() => {
    const byDay = new Map<string, number>()
    for (const r of rows) byDay.set(r.day, (byDay.get(r.day) || 0) + (r.value || 0))
    const days = [...byDay.keys()].sort()
    return {
      tooltip: { trigger: 'axis', ...darkTooltip(isDark) },
      grid: { left: 50, right: 24, top: 28, bottom: 48 },
      xAxis: {
        type: 'category',
        data: days.map(d => d.slice(5)),
        axisLabel: { ...axisLabel(isDark), rotate: 35 },
        axisLine: axisLine(isDark),
      },
      yAxis: {
        type: 'value',
        axisLabel: axisLabel(isDark),
        splitLine: splitLine(isDark),
      },
      series: [{
        name: t('tpl.series.value'),
        type: 'bar',
        data: days.map(d => byDay.get(d) || 0),
        itemStyle: { color: isDark ? '#00d9ff' : '#0d9488' },
      }],
    }
  }, [rows, isDark, t])

  /* ---- 导出：一律走 excelReport ----
   * 不要再写 XLSX.utils.aoa_to_sheet + book_new + writeFile 四连。
   * sheet 名不用自己 substring(0,31) 或去重，模块已统一处理。
   */
  const exportRows = useCallback((list: Row0[], name: string) => {
    if (!list.length) return
    void exportAoaReport({
      filename: `${name}_${dayjs().format('YYYYMMDD_HHmmss')}.xlsx`,
      sheetName: name,
      title: name,
      header: [t('tpl.col.day'), t('tpl.col.siteId'), t('tpl.col.siteName'), t('tpl.col.value')],
      rows: list.map(r => [r.day, r.site_id, r.site_name, r.value]),
      numericCols: [3],
    })
  }, [t])

  /* ---- 下钻：打开弹窗并取明细，坐标用于「以点击点为中心」弹出 ---- */
  const openDrill = useCallback(async (row: Row0, at?: { x: number; y: number }) => {
    setOpen(true)
    setAnchor(at || null)
    // 换成真实调用：setDrillRows((await getTemplateDrilldown({ ... })).data?.rows || [])
    setDrillRows([row])
  }, [])

  /* ---- 表格列：getter 集中定义，便于同一份定义复用到导出 ---- */
  const columns = useMemo(() => [
    { title: t('tpl.col.day'), dataIndex: 'day' },
    { title: t('tpl.col.siteId'), dataIndex: 'site_id', render: fmt },
    { title: t('tpl.col.siteName'), dataIndex: 'site_name', render: fmt },
    {
      title: t('tpl.col.value'), dataIndex: 'value',
      sorter: (a: Row0, b: Row0) => (a.value || 0) - (b.value || 0),
      render: (v: number) => <Text strong>{fmt(v)}</Text>,
    },
    {
      title: t('tpl.col.action'), key: 'action',
      render: (_: unknown, r: Row0) => (
        <Button type="link" onClick={e => void openDrill(r, { x: e.clientX, y: e.clientY })}>
          {t('tpl.drill')}
        </Button>
      ),
    },
  ], [t, openDrill])

  const drillColumns = useMemo(() => [
    { title: t('tpl.col.day'), dataIndex: 'day' },
    { title: t('tpl.col.siteName'), dataIndex: 'site_name', render: fmt },
    { title: t('tpl.col.value'), dataIndex: 'value', render: fmt },
  ], [t])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>

      {/* ① 筛选条：用 CardBase，不要自己写 style={cardStyle} 的裸 Card */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Space wrap>
          <DatePicker value={start} onChange={setStart} />
          <span>{t('tpl.to')}</span>
          <DatePicker value={end} onChange={setEnd} />
          <Select
            allowClear
            placeholder={t('tpl.region')}
            value={region || undefined}
            onChange={v => setRegion(v || '')}
            options={regions.map(v => ({ value: v, label: v }))}
            style={{ width: 180 }}
            showSearch
          />
          <Input
            allowClear
            placeholder={t('tpl.search')}
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            style={{ width: 180 }}
          />
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
            {t('tpl.refresh')}
          </Button>
          <Button
            icon={<DownloadOutlined />}
            onClick={() => exportRows(rows, 'template_rows')}
            disabled={!rows.length}
          >
            {t('common.exportExcel')}
          </Button>
        </Space>
      </CardBase>

      {/* ② 错误与警告：必须可见，不要只 console.error */}
      {error && <Alert type="error" showIcon message={error} />}

      {/* ③ 数字卡：用 StatCard（它已挂统一卡片皮肤） */}
      <Row gutter={[12, 12]}>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title={t('tpl.kpi.total')} value={total} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title={t('tpl.kpi.sites')} value={affected} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard title={t('tpl.kpi.rows')} value={rows.length} />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          {/* 语义等级染色：ok / warn / crit，复用 --wh-ok/--wh-warn/--wh-danger */}
          <CardBase level={total > 100 ? 'crit' : 'ok'} title={t('tpl.kpi.status')} as="div">
            <Text strong style={{ fontSize: 24 }}>{fmt(total)}</Text>
          </CardBase>
        </Col>
      </Row>

      {/* ④ 图表卡：title 传字符串即自动套统一卡头排版 */}
      <CardBase
        title={t('tpl.chart.title')}
        extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('tpl.chart.hint')}</Text>}
      >
        {rows.length
          ? <ReactECharts option={chartOption} style={{ height: 340 }} notMerge />
          : <Empty description={t('tpl.empty')} />}
      </CardBase>

      {/* ⑤ 表格卡：可交互卡片加 interactive 获得统一悬停效果 */}
      <CardBase title={t('tpl.table.title')} interactive={false}>
        <Table
          rowKey={r => `${r.day}-${r.site_id}`}
          columns={columns}
          dataSource={rows}
          loading={loading}
          pagination={{ pageSize: 12, showSizeChanger: true }}
          scroll={{ x: 900 }}
          size="small"
        />
      </CardBase>

      {/* ⑥ 下钻弹窗：可拖拽、点遮罩不关闭、Esc 关闭 */}
      <DraggableClickModal
        open={open}
        title={t('tpl.drillTitle')}
        anchor={anchor}
        onClose={() => setOpen(false)}
      >
        <Space wrap style={{ marginBottom: 'var(--wh-space-sm)' }}>
          <Tag color="blue">{t('tpl.drillCount', { n: drillRows.length })}</Tag>
          <Button
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => exportRows(drillRows, 'template_drill')}
          >
            {t('common.exportExcel')}
          </Button>
        </Space>
        {/* 弹窗内不要用 cardStyle 再套一层卡片 —— 弹窗本身就是容器 */}
        <div style={{ ...cardStyle, boxShadow: 'none', background: 'transparent', border: 'none' }}>
          <Table
            rowKey={r => `${r.day}-${r.site_id}`}
            columns={drillColumns}
            dataSource={drillRows}
            pagination={{ pageSize: 10 }}
            size="small"
            scroll={{ x: 700 }}
          />
        </div>
      </DraggableClickModal>
    </div>
  )
}

/* ============================================================================
 * 配套的 i18n 键（加进 frontend/src/i18n.tsx 的 zh 与 en **两处**）：
 *
 * zh: {
 *   'tpl.to': '至',
 *   'tpl.region': '区域',
 *   'tpl.search': '搜索',
 *   'tpl.refresh': '刷新',
 *   'tpl.empty': '暂无数据',
 *   'tpl.drill': '下钻',
 *   'tpl.drillTitle': '明细',
 *   'tpl.drillCount': '共 {{n}} 条',
 *   'tpl.series.value': '数值',
 *   'tpl.col.day': '日期',
 *   'tpl.col.siteId': '站点 ID',
 *   'tpl.col.siteName': '站点名',
 *   'tpl.col.value': '数值',
 *   'tpl.col.action': '操作',
 *   'tpl.chart.title': '每日趋势',
 *   'tpl.chart.hint': '点击可下钻',
 *   'tpl.table.title': '明细列表',
 *   'tpl.kpi.total': '总计',
 *   'tpl.kpi.sites': '涉及站点',
 *   'tpl.kpi.rows': '记录数',
 *   'tpl.kpi.status': '状态',
 * }
 * en: { ... 同结构英文 ... }
 *
 * 这些键在本模板里**尚未真正写入 i18n.tsx**（避免污染真实字典）。
 * 复制本文件开新页时，务必把你要用的键补进两处字典，否则界面显示 key。
 * ========================================================================== */
