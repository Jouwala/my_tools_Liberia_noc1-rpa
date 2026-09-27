/* ============================================================================
 * eFlow 全流程查询（EflowFlow）
 * ============================================================================
 * 用户输入**告警**（告警 ID / aid / 告警码）或 **TT 单号**，页面画出该单在 eFlow 里的
 * 全流程图：
 *   ① 底图 = 规则驱动的状态机（来自 ocrule_details 的 触发步骤 / 推送路径）
 *      告警 → TT 建单 → 自动派单 → FO/BO 接单 → FO/BO 处理 → 第三方 → 确认 → 关单
 *   ② 高亮 = 该单**实际走过**的节点与连线（来自 operation_type 与各 *_detail 里程碑）
 *   ③ 旁路 = TT 派生的 WO 子流程（现场工单）单独一条泳道
 *
 * 后端：GET /api/eflow-flow/query?q=...&lang=zh
 *       GET /api/eflow-flow/graph?lang=zh
 *       GET /api/eflow-flow/rules
 * 判定口径与 NOC 分析 / 单 TT 复盘报告**同源**（都读 ocrule_details），
 * 详见 backend/services/eflow_flow.py 头部说明。
 *
 * 约定（见 AGENTS.md）：
 *   ✅ 卡片一律用 components/cards，不 import antd 的 Card
 *   ✅ 图表取色分两层：DOM 用 WH，ECharts 用 isDark 实值
 *   ✅ 文案一律走 t()，键在 i18n.tsx 中英两处都加
 *   ✅ 表格动作用链接样式，数字可下钻
 * ========================================================================== */

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Col, Descriptions, Empty, Form, Input, Row, Space, Spin,
  Table, Tag, Tooltip, Typography,
} from 'antd'
import {
  ApartmentOutlined, CheckCircleFilled, ClockCircleOutlined,
  DownloadOutlined, ReloadOutlined, SearchOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'

import { useI18n } from '../i18n'
import { WH, useTheme, darkTooltip } from '../theme'
import { CardBase, StatCard } from '../components/cards'
import api from '../api'
import { formatDateTime as fmtDateTime } from '../datetime'
import { exportReport, type ReportSheetSpec } from '../utils/excelReport'

const { Text, Link } = Typography

/* ---- 与后端 backend/services/eflow_flow.py 返回结构对齐的类型 ---- */
type FlowRule = {
  id: string
  name: string
  rule_type: string
  role_zh: string
  role_en: string
  wo_type: string
  trigger_step: string
  status: string
  priority: string
  handler: string
  description: string
  update_time: string
  push_path: string
}

type FlowNode = {
  id: string
  label: string
  stage: string
  rules: FlowRule[]
  rule_count: number
  active_rule_count: number
}

type FlowEdge = { from: string; to: string; kind: string; rule_names: string[] }

type ReachedStep = {
  id: string
  ts: string
  by: string
  note_zh: string
  note_en: string
}

type QueryResult = {
  found: boolean
  query: string
  query_type: string
  via?: string
  graph: { nodes: FlowNode[]; edges: FlowEdge[]; rules_total: number }
  tt?: Record<string, string>
  wo?: Record<string, string> | null
  alarms?: {
    table: string; id: string; aid: string; alarm_code: string; site_name: string
    raised: string; severity: string; title: string; ne_name: string; ne_ip: string
  }[]
  reached?: ReachedStep[]
  reached_ids?: string[]
  actual_edges?: { from: string; to: string }[]
  current?: string | null
  wo_path?: {
    present: boolean
    reached_ids: string[]
    current: string | null
    wo_no?: string
    status?: string
    operation_step?: string
    current_handler?: string
    created_time?: string
    actual_finish_time?: string
    steps?: { key: string; ts: string; detail: string }[]
  }
  rule_hits?: (FlowRule & { node: string; reason_zh: string; reason_en: string })[]
  candidates?: Record<string, string>[]
  message?: string
  message_en?: string
}

/** 统一空值展示 */
const fmt = (v: unknown) => (v == null || v === '' ? '-' : String(v))

/**
 * 步骤/节点 key → i18n 键。
 * ⚠ 必须用显式 switch 返回字面量键：动态拼 `t('eflowFlow.node.' + k)` 会被
 * `npm run check:i18n` 守卫读成键名 `eflowFlow.node.` 而误报「字典缺失」。
 */
function nodeLabelKey(id: string): string {
  switch (id) {
    case 'alarm': return 'eflowFlow.node.alarm'
    case 'create': return 'eflowFlow.node.create'
    case 'autoDispatch': return 'eflowFlow.node.autoDispatch'
    case 'FOAccept': return 'eflowFlow.node.FOAccept'
    case 'FOProcess': return 'eflowFlow.node.FOProcess'
    case 'BOAccept': return 'eflowFlow.node.BOAccept'
    case 'BOProcess': return 'eflowFlow.node.BOProcess'
    case 'ThirdAccept': return 'eflowFlow.node.ThirdAccept'
    case 'ThirdProcess': return 'eflowFlow.node.ThirdProcess'
    case 'Confirm': return 'eflowFlow.node.Confirm'
    case 'Closed': return 'eflowFlow.node.Closed'
    case 'wo_create': return 'eflowFlow.node.woCreate'
    case 'wo_accept': return 'eflowFlow.node.woAccept'
    case 'wo_process': return 'eflowFlow.node.woProcess'
    case 'wo_confirm': return 'eflowFlow.node.woConfirm'
    case 'wo_closed': return 'eflowFlow.node.woClosed'
    default: return 'eflowFlow.node.unknown'
  }
}

/** query_type → i18n 键（同样是显式 switch，不用动态拼接） */
function queryTypeKey(qt: string): string {
  switch (qt) {
    case 'tt': return 'eflowFlow.type.tt'
    case 'alarm': return 'eflowFlow.type.alarm'
    case 'alarm_code': return 'eflowFlow.type.alarmCode'
    default: return 'eflowFlow.type.unknown'
  }
}

/** 节点泳道 → 横坐标（决定流程图的分层从左到右） */
const STAGE_ORDER: Record<string, number> = {
  upstream: 0, create: 1, dispatch: 2, fo: 3, bo: 3, third: 4, confirm: 5, closed: 6, wo: 7,
}

export default function EflowFlow() {
  const { t, locale } = useI18n()
  const { isDark } = useTheme()
  const isZh = locale === 'zh'

  const [keyword, setKeyword] = useState('')
  const [data, setData] = useState<QueryResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState(false)
  /** 当前选中的节点（点击图中节点 → 右侧规则明细） */
  const [activeNode, setActiveNode] = useState<string>('')

  /* ---- 查询 ---- */
  const runQuery = useCallback(async (kw: string) => {
    const q = kw.trim()
    if (!q) return
    setLoading(true)
    setError('')
    setSearched(true)
    try {
      const res = await api.get('/eflow-flow/query', { params: { q, lang: isZh ? 'zh' : 'en' } })
      setData(res.data as QueryResult)
      setActiveNode((res.data as QueryResult)?.current || '')
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || String(e))
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [isZh])

  useEffect(() => {
    // 语言切换后若已有结果，按新语言重查（后端返回的节点标签/注释分语言）
    if (searched && data?.query) void runQuery(data.query)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isZh])

  /* ---- 派生数据 ---- */
  const graph = data?.graph
  const reachedIds = useMemo(() => new Set(data?.reached_ids || []), [data])
  const actualEdgeKeys = useMemo(
    () => new Set((data?.actual_edges || []).map((e) => `${e.from}->${e.to}`)),
    [data],
  )
  const woReached = useMemo(
    () => new Set(data?.wo_path?.reached_ids || []),
    [data],
  )

  const currentNode = data?.current || ''
  const activeNodeObj = useMemo(
    () => graph?.nodes.find((n) => n.id === activeNode) || null,
    [graph, activeNode],
  )

  /** 图上的规则命中节点集合 */
  const hitNodeIds = useMemo(() => {
    const s = new Set<string>()
    for (const h of data?.rule_hits || []) s.add(h.node)
    return s
  }, [data])

  /* ---- ECharts 流程图 ----
   * ⚠ 取色必须用 isDark 实值：WH.xxx 是 'var(--wh-*)'，canvas 解析不了。
   */
  const chartOption = useMemo(() => {
    if (!graph) return {}

    // 节点布局：按 stage 分列，同列内依次下排
    const byStage = new Map<number, FlowNode[]>()
    for (const n of graph.nodes) {
      const col = STAGE_ORDER[n.stage] ?? 0
      if (!byStage.has(col)) byStage.set(col, [])
      byStage.get(col)!.push(n)
    }
    const cols = [...byStage.keys()].sort((a, b) => a - b)

    const X_GAP = 190
    const Y_GAP = 88
    const pos = new Map<string, { x: number; y: number }>()
    let maxRows = 1
    cols.forEach((col, ci) => {
      const list = byStage.get(col)!
      maxRows = Math.max(maxRows, list.length)
      const offset = (list.length - 1) / 2
      list.forEach((n, ri) => {
        pos.set(n.id, { x: ci * X_GAP, y: (ri - offset) * Y_GAP })
      })
    })

    const cOk = isDark ? '#0bc78c' : '#15803d'
    const cCur = isDark ? '#f6cf00' : '#b45309'
    const cIdle = isDark ? '#2a3f66' : '#cbd5e1'
    const cBorder = isDark ? '#6f8cb4' : '#94a3b8'
    const cMainEdge = isDark ? 'rgba(111,140,180,0.45)' : 'rgba(148,163,184,0.55)'
    const cActEdge = isDark ? '#00d9ff' : '#0d9488'
    const cText = isDark ? '#f5f7ff' : '#16233b'

    const nodes = graph.nodes.map((n) => {
      const isReached = reachedIds.has(n.id)
      const isCurrent = n.id === currentNode
      const isHit = hitNodeIds.has(n.id)
      // 优先级：当前 > 已到达 > 有规则命中 > 未涉及
      let border = cIdle
      let bg = isDark ? 'rgba(8,18,44,0.9)' : 'rgba(255,255,255,0.95)'
      let width = 2
      if (isHit) border = cBorder
      if (isReached) { border = cOk; bg = isDark ? 'rgba(11,199,140,0.16)' : 'rgba(21,128,61,0.10)' }
      if (isCurrent) { border = cCur; width = 4; bg = isDark ? 'rgba(246,207,0,0.20)' : 'rgba(180,83,9,0.12)' }

      return {
        id: n.id,
        name: t(nodeLabelKey(n.id)),
        x: pos.get(n.id)?.x ?? 0,
        y: (pos.get(n.id)?.y ?? 0) + (maxRows * Y_GAP) / 2,
        symbolSize: isCurrent ? 54 : 46,
        itemStyle: { color: bg, borderColor: border, borderWidth: width },
        label: {
          show: true,
          color: cText,
          fontSize: 11,
          fontWeight: isCurrent || isReached ? 600 : 400,
          formatter: `${t(nodeLabelKey(n.id))}\n${n.active_rule_count}/${n.rule_count}`,
        },
        // 自定义字段供 tooltip 用
        _reached: isReached,
        _current: isCurrent,
        _ruleCount: n.rule_count,
        _activeCount: n.active_rule_count,
      }
    })

    const edges = graph.edges.map((e) => {
      const isActual = actualEdgeKeys.has(`${e.from}->${e.to}`)
      return {
        source: e.from,
        target: e.to,
        // 实际走过的连线加粗高亮，其余为规则骨架
        lineStyle: {
          color: isActual ? cActEdge : cMainEdge,
          width: isActual ? 3.5 : 1.4,
          type: isActual ? 'solid' : (e.kind === 'rule' ? 'dashed' : 'solid'),
          curveness: 0.12,
        },
        symbol: ['none', 'arrow'],
        symbolSize: 8,
        label: {
          show: Boolean(e.rule_names?.length) && isActual,
          formatter: e.rule_names?.[0] || '',
          fontSize: 9,
          color: cText,
        },
      }
    })

    return {
      tooltip: {
        ...darkTooltip(isDark),
        formatter: (p: any) => {
          if (p.dataType !== 'node') return ''
          const d = p.data
          const status = d._current ? t('eflowFlow.nodeStatusCurrent')
            : d._reached ? t('eflowFlow.nodeStatusReached')
              : t('eflowFlow.nodeStatusNotReached')
          return `<b>${d.name}</b><br/>${status}<br/>${t('eflowFlow.ruleCountShort')}: `
            + `${d._activeCount} / ${d._ruleCount}`
        },
      },
      series: [{
        type: 'graph',
        layout: 'none',
        // 高亮实际路径，其余节点压暗，形成"走到哪一步"的视觉焦点
        nodes,
        edges,
        roam: true,
        draggable: true,
        emphasis: { focus: 'adjacency', lineStyle: { width: 4 } },
        edgeSymbolSize: 8,
      }],
    }
  }, [graph, isDark, t, reachedIds, actualEdgeKeys, currentNode, hitNodeIds])

  /* ---- 规则明细表（当前选中节点） ---- */
  const ruleColumns = useMemo(() => [
    { title: t('eflowFlow.col.ruleName'), dataIndex: 'name', render: fmt, width: 220 },
    {
      title: t('eflowFlow.col.ruleType'), dataIndex: 'rule_type', width: 170,
      render: (v: string, r: FlowRule) => (
        <Tooltip title={isZh ? r.role_zh : r.role_en}><Tag color="blue">{fmt(v)}</Tag></Tooltip>
      ),
    },
    { title: t('eflowFlow.col.triggerStep'), dataIndex: 'trigger_step', render: fmt, width: 150 },
    {
      title: t('eflowFlow.col.status'), dataIndex: 'status', width: 90,
      render: (v: string) => (
        <Tag color={v === 'ACTIVE' ? 'green' : 'default'}>{fmt(v)}</Tag>
      ),
    },
    { title: t('eflowFlow.col.priority'), dataIndex: 'priority', render: fmt, width: 70 },
    {
      title: t('eflowFlow.col.handler'), dataIndex: 'handler', width: 200,
      render: (v: string) => (
        <span style={{ fontSize: 12 }}>{fmt(String(v || '').slice(0, 60))}</span>
      ),
    },
    {
      title: t('eflowFlow.col.pushPath'), dataIndex: 'push_path', width: 200,
      render: (v: string) => <span style={{ fontSize: 12 }}>{fmt(v)}</span>,
    },
  ], [t, isZh])

  /** 实际路径时间轴表 */
  const stepColumns = useMemo(() => [
    {
      title: t('eflowFlow.col.step'), dataIndex: 'id', width: 130,
      render: (v: string) => (
        <Space size={4}>
          {v === currentNode
            ? <ClockCircleOutlined style={{ color: WH.warn }} />
            : <CheckCircleFilled style={{ color: WH.ok }} />}
          <Text strong={v === currentNode}>{t(nodeLabelKey(v))}</Text>
        </Space>
      ),
    },
    {
      title: t('eflowFlow.col.time'), dataIndex: 'ts', width: 180,
      render: (v: string) => (v ? fmtDateTime(v) : '-'),
    },
    { title: t('eflowFlow.col.handler'), dataIndex: 'by', width: 160, render: fmt },
    {
      title: t('eflowFlow.col.note'), dataIndex: 'note_zh',
      render: (_: string, r: ReachedStep) => (isZh ? fmt(r.note_zh) : fmt(r.note_en)),
    },
  ], [t, isZh, currentNode])

  /* ---- 关联告警表 ---- */
  const alarmColumns = useMemo(() => [
    { title: t('eflowFlow.col.alarmId'), dataIndex: 'id', render: fmt, width: 160 },
    { title: t('eflowFlow.col.alarmCode'), dataIndex: 'alarm_code', render: fmt, width: 110 },
    { title: t('eflowFlow.col.site'), dataIndex: 'site_name', render: fmt, width: 150 },
    { title: t('eflowFlow.col.neName'), dataIndex: 'ne_name', render: fmt, width: 180 },
    { title: t('eflowFlow.col.severity'), dataIndex: 'severity', render: fmt, width: 100 },
    {
      title: t('eflowFlow.col.raised'), dataIndex: 'raised', width: 170,
      render: (v: string) => (/^\d+$/.test(String(v)) ? fmtDateTime(Number(v)) : fmt(v)),
    },
    { title: t('eflowFlow.col.title'), dataIndex: 'title', render: fmt },
  ], [t])

  const t6 = data?.tt || {}
  const isAlarmQuery = data?.query_type === 'alarm' || data?.query_type === 'alarm_code'

  // ========== 导出 ==========
  /* 口径与页面完全一致：导出当前查询结果的**全部**节点规则 + 实际经过步骤 + 关联告警，
     不做前端分页取样（表格是 dataSource 全量渲染，没有分页截断）。
     与 noc_analyst 的导出同构：一个工作簿，每块一个 sheet。 */
  const exportFlow = useCallback(async () => {
    if (!data?.found) return
    const nodeName = (id: string) => t(nodeLabelKey(id))
    const sheets: ReportSheetSpec[] = []

    // ① 全流程节点（含规则数），便于对账「哪些环节有规则/哪些没走」
    const nodes = data.graph?.nodes || []
    if (nodes.length) {
      sheets.push({
        name: 'Nodes',
        title: `${t('eflowFlow.title')} · ${data.query}`,
        header: [
          t('eflowFlow.col.step'),
          t('eflowFlow.col.rules'),
          t('eflowFlow.col.activeRules'),
          t('eflowFlow.col.reached'),
        ],
        rows: nodes.map(n => [
          nodeName(n.id),
          n.rule_count ?? 0,
          n.active_rule_count ?? 0,
          reachedIds.has(n.id) ? t('eflowFlow.yes') : t('eflowFlow.no'),
        ]),
        numericCols: [1, 2],
        tabColor: '#2F5496',
      })
    }

    // ② 规则明细（当前选中节点的规则；未选中时退化为全部节点的规则并加一列节点名）
    const selectedRules = activeNode
      ? (nodes.find(n => n.id === activeNode)?.rules || [])
      : []
    const ruleRows = selectedRules.length
      ? selectedRules.map(r => [
          r.name, r.rule_type, isZh ? r.role_zh : r.role_en, r.wo_type,
          r.trigger_step, r.status, r.priority, r.handler, r.push_path, r.update_time,
        ])
      : nodes.flatMap(n => (n.rules || []).map(r => [
          nodeName(n.id), r.name, r.rule_type, isZh ? r.role_zh : r.role_en, r.wo_type,
          r.trigger_step, r.status, r.priority, r.handler, r.push_path, r.update_time,
        ]))
    if (ruleRows.length) {
      const withNode = selectedRules.length === 0
      sheets.push({
        name: 'Rules',
        title: `${t('eflowFlow.rulesTitle')}${selectedRules.length ? ` · ${nodeName(activeNode)}` : ''}`,
        header: withNode
          ? [t('eflowFlow.col.step'), t('eflowFlow.col.ruleName'), t('eflowFlow.col.ruleType'),
             t('eflowFlow.col.role'), t('eflowFlow.col.woType'), t('eflowFlow.col.triggerStep'),
             t('eflowFlow.col.status'), t('eflowFlow.col.priority'), t('eflowFlow.col.handler'),
             t('eflowFlow.col.pushPath'), t('eflowFlow.col.updateTime')]
          : [t('eflowFlow.col.ruleName'), t('eflowFlow.col.ruleType'), t('eflowFlow.col.role'),
             t('eflowFlow.col.woType'), t('eflowFlow.col.triggerStep'), t('eflowFlow.col.status'),
             t('eflowFlow.col.priority'), t('eflowFlow.col.handler'), t('eflowFlow.col.pushPath'),
             t('eflowFlow.col.updateTime')],
        rows: ruleRows,
        tabColor: '#548235',
      })
    }

    // ③ 实际经过的步骤（时间轴）
    const reached = data.reached || []
    if (reached.length) {
      sheets.push({
        name: 'Reached',
        title: `${t('eflowFlow.timelineTitle')} · ${data.query}`,
        header: [
          t('eflowFlow.col.step'), t('eflowFlow.col.time'),
          t('eflowFlow.col.handler'), t('eflowFlow.col.note'),
        ],
        rows: reached.map(s => [
          nodeName(s.id),
          s.ts ? fmtDateTime(s.ts) : '',
          s.by,
          isZh ? s.note_zh : s.note_en,
        ]),
        tabColor: '#BF8F00',
      })
    }

    // ④ 关联告警
    const alarms = data.alarms || []
    if (alarms.length) {
      sheets.push({
        name: 'Alarms',
        title: `${t('eflowFlow.alarms.title')} · ${data.query}`,
        header: [
          t('eflowFlow.col.alarmId'), t('eflowFlow.col.alarmCode'), t('eflowFlow.col.site'),
          t('eflowFlow.col.neName'), t('eflowFlow.col.severity'), t('eflowFlow.col.raised'),
          t('eflowFlow.col.title'),
        ],
        rows: alarms.map(a => [
          a.id, a.alarm_code, a.site_name, a.ne_name, a.severity,
          /^\d+$/.test(String(a.raised)) ? fmtDateTime(Number(a.raised)) : a.raised,
          a.title,
        ]),
        tabColor: '#843C0C',
      })
    }

    if (!sheets.length) return
    const stamp = fmtDateTime(new Date()).replace(/[: ]/g, '-')
    await exportReport(sheets, `eflow_flow_${String(data.query).replace(/[^\w]+/g, '_')}_${stamp}.xlsx`)
  }, [data, activeNode, reachedIds, isZh, t])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--wh-space-md)' }}>

      {/* ① 查询条 */}
      <CardBase bodyStyle={{ padding: 'var(--wh-space-sm) var(--wh-space-md)' }}>
        <Form
          layout="inline"
          onFinish={() => void runQuery(keyword)}
          style={{ rowGap: 8 }}
        >
          <Form.Item style={{ marginBottom: 0, flex: 1, minWidth: 280 }}>
            <Input
              allowClear
              size="large"
              prefix={<SearchOutlined />}
              placeholder={t('eflowFlow.searchPlaceholder')}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onPressEnter={() => void runQuery(keyword)}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Space>
              <Button
                type="primary"
                size="large"
                icon={<ApartmentOutlined />}
                htmlType="submit"
                loading={loading}
              >
                {t('eflowFlow.query')}
              </Button>
              <Button
                size="large"
                icon={<ReloadOutlined />}
                onClick={() => void runQuery(keyword)}
                disabled={!keyword.trim()}
              >
                {t('eflowFlow.refresh')}
              </Button>
              <Button
                size="large"
                icon={<DownloadOutlined />}
                onClick={() => void exportFlow()}
                disabled={!data?.found}
              >
                {t('common.exportExcel')}
              </Button>
            </Space>
          </Form.Item>
        </Form>
        <div style={{ marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>{t('eflowFlow.searchHint')}</Text>
        </div>
      </CardBase>

      {/* ② 错误 */}
      {error && <Alert type="error" showIcon message={error} />}

      {/* ③ 加载中 */}
      {loading && (
        <CardBase><div style={{ textAlign: 'center', padding: 40 }}><Spin size="large" /></div></CardBase>
      )}

      {/* ④ 未搜索时的引导 */}
      {!searched && !loading && (
        <CardBase>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <Space direction="vertical" size={4}>
                <Text>{t('eflowFlow.emptyHint')}</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>{t('eflowFlow.emptyExample')}</Text>
              </Space>
            }
          />
        </CardBase>
      )}

      {/* ⑤ 未找到 */}
      {searched && !loading && data && !data.found && (
        <CardBase>
          <Alert
            type="warning"
            showIcon
            message={isZh ? (data.message || t('eflowFlow.notFound')) : (data.message_en || t('eflowFlow.notFound'))}
            description={
              data.candidates?.length ? (
                <div>
                  <Text type="secondary">{t('eflowFlow.candidatesHint')}</Text>
                  <div style={{ marginTop: 8 }}>
                    <Space wrap>
                      {data.candidates.slice(0, 20).map((c, i) => (
                        <Link
                          key={i}
                          onClick={() => {
                            const tt = c.tt_no || c['tt_no'] || ''
                            if (tt) { setKeyword(tt); void runQuery(tt) }
                          }}
                        >
                          <Tag color="blue">{fmt(c.tt_no)}</Tag>
                        </Link>
                      ))}
                    </Space>
                  </div>
                </div>
              ) : undefined
            }
          />
        </CardBase>
      )}

      {/* ⑥ 结果 */}
      {searched && !loading && data?.found && (
        <>
          {/* 概览数字卡：每个数字都可点（点 → 切到对应节点） */}
          <Row gutter={[12, 12]}>
            <Col xs={12} sm={8} lg={4}>
              <StatCard title={t('eflowFlow.kpi.ttNo')} value={fmt(t6.tt_no)} />
            </Col>
            <Col xs={12} sm={8} lg={4}>
              <CardBase
                level={data.current === 'Closed' ? 'ok' : 'warn'}
                title={t('eflowFlow.kpi.status')}
                as="div"
                interactive
                onClick={() => setActiveNode(data.current || '')}
              >
                <Text strong style={{ fontSize: 15 }}>
                  {data.current ? t(nodeLabelKey(data.current)) : fmt(t6.status)}
                </Text>
                <div style={{ fontSize: 11, color: WH.textDim, marginTop: 2 }}>
                  {fmt(t6.operation_type)}
                </div>
              </CardBase>
            </Col>
            <Col xs={12} sm={8} lg={4}>
              <StatCard title={t('eflowFlow.kpi.severity')} value={fmt(t6.ticket_severity)} />
            </Col>
            <Col xs={12} sm={8} lg={4}>
              <CardBase
                title={t('eflowFlow.kpi.steps')}
                as="div"
                interactive
                onClick={() => setActiveNode('')}
              >
                <Text strong style={{ fontSize: 22 }}>{data.reached_ids?.length || 0}</Text>
                <div style={{ fontSize: 11, color: WH.textDim, marginTop: 2 }}>
                  {t('eflowFlow.kpi.stepsHint', { n: graph?.nodes.length || 0 })}
                </div>
              </CardBase>
            </Col>
            <Col xs={12} sm={8} lg={4}>
              <CardBase title={t('eflowFlow.kpi.rulesTotal')} as="div" interactive
                onClick={() => setActiveNode(data.current || '')}>
                <Text strong style={{ fontSize: 22 }}>{graph?.rules_total || 0}</Text>
                <div style={{ fontSize: 11, color: WH.textDim, marginTop: 2 }}>
                  {t('eflowFlow.kpi.rulesHint', { n: data.rule_hits?.length || 0 })}
                </div>
              </CardBase>
            </Col>
            <Col xs={12} sm={8} lg={4}>
              <CardBase title={t('eflowFlow.kpi.wo')} as="div" interactive
                onClick={() => setActiveNode(data.wo_path?.current || '')}>
                <Text strong style={{ fontSize: 15 }}>{fmt(data.wo_path?.wo_no || t6.wo_no)}</Text>
                <div style={{ fontSize: 11, color: WH.textDim, marginTop: 2 }}>
                  {data.wo_path?.present
                    ? t('eflowFlow.woCurrent', { s: data.wo_path?.operation_step || '-' })
                    : t('eflowFlow.noWo')}
                </div>
              </CardBase>
            </Col>
          </Row>

          {/* 查询命中提示 */}
          <Alert
            type="info"
            showIcon
            message={
              <Space wrap size={8}>
                <Tag color="blue">{t(queryTypeKey(data.query_type))}</Tag>
                <Text>{t('eflowFlow.hitTt', { tt: fmt(t6.tt_no) })}</Text>
                {data.via && <Text type="secondary" style={{ fontSize: 12 }}>{t('eflowFlow.via', { via: data.via })}</Text>}
                {t6.site_name && <Text type="secondary" style={{ fontSize: 12 }}>{t('eflowFlow.site', { site: t6.site_name })}</Text>}
              </Space>
            }
          />

          {/* ⑦ 全流程图 */}
          <CardBase
            title={t('eflowFlow.graph.title')}
            extra={
              <Space size={12} wrap>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  <CheckCircleFilled style={{ color: WH.ok, marginRight: 4 }} />{t('eflowFlow.legend.reached')}
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  <ClockCircleOutlined style={{ color: WH.warn, marginRight: 4 }} />{t('eflowFlow.legend.current')}
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>{t('eflowFlow.legend.hint')}</Text>
              </Space>
            }
          >
            {graph?.nodes?.length
              ? (
                <ReactECharts
                  option={chartOption}
                  style={{ height: 520 }}
                  notMerge
                  onEvents={{
                    click: (p: any) => {
                      if (p?.dataType === 'node' && p?.data?.id) setActiveNode(p.data.id)
                    },
                  }}
                />
              )
              : <Empty description={t('eflowFlow.graph.empty')} />}
          </CardBase>

          {/* ⑧ 节点的规则明细（点击图中节点切换） */}
          <CardBase
            title={
              activeNode
                ? t('eflowFlow.nodeRules.title', { node: t(nodeLabelKey(activeNode)) })
                : t('eflowFlow.nodeRules.titleAll')
            }
            extra={
              activeNodeObj && (
                <Space size={8}>
                  <Tag color="green">{t('eflowFlow.nodeRules.active', { n: activeNodeObj.active_rule_count })}</Tag>
                  <Tag>{t('eflowFlow.nodeRules.total', { n: activeNodeObj.rule_count })}</Tag>
                  <Button size="small" type="link" onClick={() => setActiveNode('')}>
                    {t('eflowFlow.nodeRules.showAll')}
                  </Button>
                </Space>
              )
            }
          >
            <Table
              rowKey={(r: FlowRule) => `${r.name}-${r.trigger_step}-${r.rule_type}`}
              columns={ruleColumns as any}
              dataSource={
                activeNodeObj
                  ? activeNodeObj.rules
                  : (graph?.nodes || []).flatMap((n) => n.rules)
              }
              size="small"
              pagination={{ pageSize: 10, showSizeChanger: true }}
              scroll={{ x: 1180 }}
              locale={{ emptyText: <Empty description={t('eflowFlow.nodeRules.empty')} image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
            />
          </CardBase>

          {/* ⑨ 实际路径时间轴 + TT 基本信息 */}
          <Row gutter={[12, 12]}>
            <Col xs={24} lg={12}>
              <CardBase title={t('eflowFlow.steps.title')}>
                <Table
                  rowKey={(r: ReachedStep) => r.id}
                  columns={stepColumns as any}
                  dataSource={data.reached || []}
                  size="small"
                  pagination={false}
                  scroll={{ x: 620 }}
                />
              </CardBase>
            </Col>
            <Col xs={24} lg={12}>
              <CardBase title={t('eflowFlow.ttInfo.title')}>
                <Descriptions column={1} size="small" bordered
                  labelStyle={{ width: 150, fontSize: 12 }}
                  contentStyle={{ fontSize: 12 }}>
                  <Descriptions.Item label={t('eflowFlow.ttInfo.ttNo')}>{fmt(t6.tt_no)}</Descriptions.Item>
                  <Descriptions.Item label={t('eflowFlow.ttInfo.status')}>{fmt(t6.status)}</Descriptions.Item>
                  <Descriptions.Item label={t('eflowFlow.ttInfo.operationType')}>{fmt(t6.operation_type)}</Descriptions.Item>
                  <Descriptions.Item label={t('eflowFlow.ttInfo.severity')}>{fmt(t6.ticket_severity)}</Descriptions.Item>
                  <Descriptions.Item label={t('eflowFlow.ttInfo.alarmCode')}>{fmt(t6.alarm_code)}</Descriptions.Item>
                  <Descriptions.Item label={t('eflowFlow.ttInfo.site')}>{fmt(t6.site_name)}</Descriptions.Item>
                  <Descriptions.Item label={t('eflowFlow.ttInfo.ne')}>{fmt(t6.ne_name)}</Descriptions.Item>
                  <Descriptions.Item label={t('eflowFlow.ttInfo.handler')}>{fmt(t6.current_handler)}</Descriptions.Item>
                  <Descriptions.Item label={t('eflowFlow.ttInfo.creator')}>{fmt(t6.creator)}</Descriptions.Item>
                  <Descriptions.Item label={t('eflowFlow.ttInfo.created')}>{t6.created_time ? fmtDateTime(t6.created_time) : '-'}</Descriptions.Item>
                  <Descriptions.Item label={t('eflowFlow.ttInfo.alarmOccur')}>{t6.alarm_occur_time ? fmtDateTime(t6.alarm_occur_time) : '-'}</Descriptions.Item>
                  <Descriptions.Item label={t('eflowFlow.ttInfo.sla')}>{fmt(t6.sla_status)}</Descriptions.Item>
                  <Descriptions.Item label={t('eflowFlow.ttInfo.rootCause')}>{fmt(t6.root_cause)}</Descriptions.Item>
                  <Descriptions.Item label={t('eflowFlow.ttInfo.woNo')}>{fmt(t6.wo_no)}</Descriptions.Item>
                </Descriptions>
              </CardBase>
            </Col>
          </Row>

          {/* ⑩ WO 子流程 */}
          {data.wo_path?.present && (
            <CardBase
              title={t('eflowFlow.wo.title', { wo: fmt(data.wo_path?.wo_no) })}
              extra={
                <Space size={8} wrap>
                  <Tag color="blue">{t('eflowFlow.wo.step', { s: fmt(data.wo_path?.operation_step) })}</Tag>
                  <Tag>{t('eflowFlow.wo.status', { s: fmt(data.wo_path?.status) })}</Tag>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {t('eflowFlow.wo.handler', { s: fmt(data.wo_path?.current_handler) })}
                  </Text>
                </Space>
              }
            >
              <Space wrap size={[0, 8]}>
                {(graph?.nodes || []).filter((n) => n.stage === 'wo').map((n, i, arr) => {
                  const on = woReached.has(n.id)
                  const cur = data.wo_path?.current === n.id
                  return (
                    <Space key={n.id} size={6}>
                      <Tag
                        color={cur ? 'gold' : on ? 'green' : 'default'}
                        style={{ fontSize: 12, padding: '2px 10px' }}
                      >
                        {cur ? <ClockCircleOutlined /> : on ? <CheckCircleFilled /> : null}
                        {' '}{t(nodeLabelKey(n.id))}
                      </Tag>
                      {i < arr.length - 1 && <Text type="secondary">›</Text>}
                    </Space>
                  )
                })}
              </Space>
              {!!data.wo_path?.steps?.length && (
                <div style={{ marginTop: 'var(--wh-space-sm)' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>{t('eflowFlow.wo.details')}</Text>
                  <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {data.wo_path.steps.map((s, i) => (
                      <div key={i} style={{
                        fontSize: 12, color: WH.textMuted,
                        borderLeft: `2px solid ${WH.teal}`, paddingLeft: 8,
                      }}>
                        <Text strong style={{ fontSize: 12 }}>{t(nodeLabelKey(s.key))}</Text>
                        {s.ts ? <span style={{ marginLeft: 8 }}>{fmtDateTime(s.ts)}</span> : null}
                        <div style={{ marginTop: 2, wordBreak: 'break-all' }}>{s.detail}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardBase>
          )}

          {/* ⑪ 关联告警 */}
          <CardBase
            title={t('eflowFlow.alarms.title')}
            extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('eflowFlow.alarms.hint')}</Text>}
          >
            <Table
              rowKey={(r: any) => `${r.table}-${r.id}`}
              columns={alarmColumns as any}
              dataSource={data.alarms || []}
              size="small"
              pagination={{ pageSize: 8 }}
              scroll={{ x: 1000 }}
              locale={{ emptyText: <Empty description={t('eflowFlow.alarms.empty')} image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
            />
          </CardBase>

          {/* ⑫ 其他候选（按告警码查时会命中多单） */}
          {!!data.candidates?.length && (
            <CardBase title={t('eflowFlow.candidates.title')}>
              <Text type="secondary" style={{ fontSize: 12 }}>{t('eflowFlow.candidates.desc')}</Text>
              <div style={{ marginTop: 8 }}>
                <Space wrap>
                  {data.candidates.slice(0, 30).map((c: any, i: number) => (
                    <Link key={i} onClick={() => { setKeyword(c.tt_no); void runQuery(c.tt_no) }}>
                      <Tag color="blue" style={{ cursor: 'pointer' }}>
                        {fmt(c.tt_no)} {c.site_name ? `· ${c.site_name}` : ''}
                      </Tag>
                    </Link>
                  ))}
                </Space>
              </div>
            </CardBase>
          )}

          {/* 告警查询提示：TT 归属说明 */}
          {isAlarmQuery && (
            <Alert type="success" showIcon message={t('eflowFlow.alarmQueryNote')} />
          )}
        </>
      )}
    </div>
  )
}
