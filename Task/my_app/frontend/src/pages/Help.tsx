import { useMemo, useState } from 'react'
import { Card, Collapse, Tag, Typography, Button, Space, Divider, Tabs, Table, Input, Select, Tooltip, theme as antdTheme } from 'antd'
import type { ReactNode } from 'react'
import {
  SyncOutlined,
  MailOutlined,
  AlertOutlined,
  BarChartOutlined,
  BookOutlined,
  LineChartOutlined,
  FundOutlined,
  PieChartOutlined,
  ApartmentOutlined,
  FieldTimeOutlined,
  GlobalOutlined,
  DisconnectOutlined,
  ThunderboltOutlined,
  AimOutlined,
  FileSearchOutlined,
  AppstoreOutlined,
  TableOutlined,
  UploadOutlined,
  HistoryOutlined,
  DashboardOutlined,
  SettingOutlined,
  LoginOutlined,
  QuestionCircleOutlined,
  RocketOutlined,
  ToolOutlined,
  ArrowRightOutlined,
  BulbOutlined,
  DatabaseOutlined,
  FundViewOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
  ControlOutlined,
  ExperimentOutlined,
  DeleteOutlined,
  DownloadOutlined,
  PrinterOutlined,
} from '@ant-design/icons'
import { useI18n } from '../i18n'
import { WH, cardStyle, useTheme } from '../theme'
import { PAGE_LIST, NAV_KEY_MAP, CATEGORIES, PAGE_DOCS, COMMON, OPS } from './helpContent'
import { TASK_DOCS, WORKER_GROUP_INFO } from './helpTaskDocs'
import { buildHelpMarkdown } from '../helpMarkdown'

const { Text, Title, Paragraph } = Typography

/* ==================== 帮助页 ====================
 * 全站使用帮助（4 页签）：平台简介 / 任务管理详解（44 个任务的工作流脚本、
 * 数据流与维护要点）/ 页面指南 / 运维与排障。
 * 文案数据在 helpContent.ts 与 helpTaskDocs.ts（与 helpMarkdown.ts 导出器同源）；
 * 依据 docs/manual/ 与 backend/task_registry.py 整理，改数据两端自动同步。
 * 页面本身无需自动刷新（AR_PAGE_DEFAULTS 固定 help=0）。
 * ================================================ */

/** 页面 key → 图标（与 App.tsx menuItems 保持一致） */
const PAGE_ICONS: Record<string, ReactNode> = {
  sync: <SyncOutlined />,
  email_reports: <MailOutlined />,
  alarm: <AlertOutlined />,
  ttwo: <BarChartOutlined />,
  eflow_qa: <BookOutlined />,
  nur: <LineChartOutlined />,
  ms_sla: <FundOutlined />,
  cxoDashboard: <PieChartOutlined />,
  mwUmeTopology: <ApartmentOutlined />,
  mwRealTime: <FieldTimeOutlined />,
  gis: <GlobalOutlined />,
  realtime_alarm: <AlertOutlined />,
  alarmManagement: <AlertOutlined />,
  packet_loss: <DisconnectOutlined />,
  battery: <ThunderboltOutlined />,
  ip_trace: <AimOutlined />,
  incident_overview: <FileSearchOutlined />,
  warehouse: <AppstoreOutlined />,
  overview: <BarChartOutlined />,
  tables: <TableOutlined />,
  upload: <UploadOutlined />,
  archive: <HistoryOutlined />,
  dashboard: <DashboardOutlined />,
  settings: <SettingOutlined />,
  portalLogin: <LoginOutlined />,
}

const GROUP_TAG_COLOR: Record<string, string> = { u: 'orange', n: 'geekblue', v: 'magenta', m: 'cyan', c: 'purple' }

/** 帮助页渲染用的页面条目（PAGE_LIST 条目 + 图标） */
interface PageMeta { key: string; iframe?: boolean }

/** 跳转直链（与 App 右键菜单「在新标签页打开」行为一致） */
function pageUrl(key: string): string {
  return `${window.location.pathname}?page=${key}`
}

/** 下载文本文件（导出 Markdown / 手册 HTML 用） */
function downloadText(filename: string, content: string, mime = 'text/markdown;charset=utf-8') {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** 手册页地址（manual.html 与站点同目录发布：/myapp/manual.html） */
function manualUrl(): string {
  const p = window.location.pathname
  return `${p.endsWith('/') ? p : p + '/'}manual.html`
}

/** 下载整本手册 HTML（fetch 站点上的 manual.html 再存盘；失败时退化为直接打开） */
async function downloadManual() {
  try {
    const res = await fetch(manualUrl())
    if (!res.ok) throw new Error(String(res.status))
    const html = await res.text()
    downloadText(`myapp-manual-${new Date().toISOString().slice(0, 10)}.html`, html, 'text/html;charset=utf-8')
  } catch {
    window.open(manualUrl(), '_blank', 'noopener')
  }
}

export default function Help() {
  const { t, locale } = useI18n()
  const { isDark } = useTheme()
  const { token } = antdTheme.useToken()
  const docs = PAGE_DOCS[locale]
  const common = COMMON[locale]
  const ops = OPS[locale]
  const isZh = locale === 'zh'
  // 主题感知的分隔线/虚线（浅色下用带透明度的青色，深色下跟随 antd token）
  const hairline = isDark ? token.colorBorderSecondary : 'rgba(13,148,136,0.25)'
  const dividerColor = isDark ? token.colorBorderSecondary : 'rgba(13,148,136,0.4)'

  /* ===== 任务清单表：搜索 + 分组过滤 + 行展开 ===== */
  const [taskSearch, setTaskSearch] = useState('')
  const [taskGroup, setTaskGroup] = useState<string>('all')

  const filteredTasks = useMemo(() => {
    const kw = taskSearch.trim().toLowerCase()
    return TASK_DOCS.filter(td => {
      if (taskGroup !== 'all' && td.group !== taskGroup) return false
      if (!kw) return true
      const td1 = td[locale]
      const hay = `${td.id} ${td1.name} ${td1.desc} ${td.script}`.toLowerCase()
      return hay.includes(kw)
    })
  }, [taskSearch, taskGroup, locale])

  const taskColumns = [
    {
      title: ops.taskCols.task,
      key: 'task',
      width: 260,
      render: (_: unknown, td: (typeof TASK_DOCS)[number]) => {
        const txt = td[locale]
        return (
          <Space size={6} direction="vertical" style={{ gap: 2 }}>
            <Text strong style={{ fontSize: '0.85rem' }}>{txt.name}</Text>
            <Tag style={{ fontSize: 11, lineHeight: '16px', padding: '0 6px', marginInlineEnd: 0, fontFamily: 'monospace' }}>{td.id}</Tag>
          </Space>
        )
      },
    },
    {
      title: ops.taskCols.cron,
      key: 'cron',
      width: 130,
      render: (_: unknown, td: (typeof TASK_DOCS)[number]) => (
        <Text code style={{ fontSize: 11 }}>{td.cron}</Text>
      ),
    },
    {
      title: ops.taskCols.group,
      key: 'group',
      width: 70,
      render: (_: unknown, td: (typeof TASK_DOCS)[number]) => (
        <Tag color={GROUP_TAG_COLOR[td.group]} style={{ marginInlineEnd: 0 }}>{td.group}</Tag>
      ),
    },
    {
      title: ops.taskCols.script,
      key: 'script',
      ellipsis: true,
      render: (_: unknown, td: (typeof TASK_DOCS)[number]) => (
        <Text type="secondary" style={{ fontSize: 11, fontFamily: 'monospace' }}>{td.script}</Text>
      ),
    },
  ]

  const taskTable = (
    <>
      <Space wrap style={{ marginBottom: 12 }}>
        <Input
          allowClear
          prefix={<SearchOutlined style={{ color: token.colorTextTertiary }} />}
          placeholder={ops.searchPlaceholder}
          value={taskSearch}
          onChange={e => setTaskSearch(e.target.value)}
          style={{ width: 280 }}
        />
        <Select
          value={taskGroup}
          onChange={setTaskGroup}
          style={{ width: 180 }}
          options={[
            { value: 'all', label: ops.allGroups },
            ...Object.keys(WORKER_GROUP_INFO).map(g => ({ value: g, label: `${isZh ? '组' : 'Group'} ${g}` })),
          ]}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>
          {isZh ? `${filteredTasks.length} / ${TASK_DOCS.length} 个任务 · ` : `${filteredTasks.length} / ${TASK_DOCS.length} tasks · `}{ops.expandHint}
        </Text>
      </Space>
      <Table
        size="small"
        rowKey="id"
        columns={taskColumns}
        dataSource={filteredTasks}
        pagination={{ pageSize: 10, showSizeChanger: true, showTotal: n => (isZh ? `共 ${n} 个任务` : `${n} tasks`) }}
        expandable={{
          expandedRowRender: (td: (typeof TASK_DOCS)[number]) => {
            const txt = td[locale]
            return (
              <div style={{ display: 'flex', gap: 'var(--wh-space-lg)', flexWrap: 'wrap' }}>
                <div style={{ flex: 1, minWidth: 280 }}>
                  <Paragraph style={{ margin: '0 0 6px', fontSize: '0.8125rem' }}>{txt.desc}</Paragraph>
                  <Text strong style={{ fontSize: 12, color: WH.teal }}>{ops.flowLabel}</Text>
                  <ul style={{ margin: '4px 0 0', paddingLeft: '1.1rem', fontSize: '0.8125rem', lineHeight: 1.8 }}>
                    {txt.flow.map((f, i) => <li key={i}><Text type="secondary">{f}</Text></li>)}
                  </ul>
                </div>
                <div style={{ flex: 1, minWidth: 280 }}>
                  <Text strong style={{ fontSize: 12, color: WH.teal }}>{ops.maintainLabel}</Text>
                  <ul style={{ margin: '4px 0 0', paddingLeft: '1.1rem', fontSize: '0.8125rem', lineHeight: 1.8 }}>
                    {txt.maintain.map((m, i) => <li key={i}><Text type="secondary">{m}</Text></li>)}
                  </ul>
                </div>
              </div>
            )
          },
          rowExpandable: () => true,
        }}
      />
    </>
  )

  /* ===== 各 Tab 内容 ===== */

  const introTab = (
    <>
      <Card style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }} styles={{ body: { padding: 'var(--wh-space-md)' } }}>
        <Space direction="vertical" size="small" style={{ width: '100%' }}>
          {common.intro.map((p, i) => (
            <Paragraph key={i} style={{ margin: 0, lineHeight: 1.8 }}>{p}</Paragraph>
          ))}
        </Space>
      </Card>
      <div style={{ display: 'flex', gap: 'var(--wh-space-md)', flexWrap: 'wrap', marginBottom: 'var(--wh-space-md)' }}>
        <Card size="small" title={isZh ? '它做什么' : 'What it does'} style={{ ...cardStyle, flex: 1, minWidth: 300 }}>
          <ul style={{ margin: 0, paddingLeft: '1.1rem', fontSize: '0.8125rem', lineHeight: 1.9 }}>
            {common.caps.do.map((c, i) => <li key={i}><Text type="secondary">{c}</Text></li>)}
          </ul>
        </Card>
        <Card size="small" title={isZh ? '它不做什么（能力边界）' : 'What it does NOT do (boundaries)'} style={{ ...cardStyle, flex: 1, minWidth: 300 }}>
          <ul style={{ margin: 0, paddingLeft: '1.1rem', fontSize: '0.8125rem', lineHeight: 1.9 }}>
            {common.caps.dont.map((c, i) => <li key={i}><Text type="secondary">{c}</Text></li>)}
          </ul>
        </Card>
      </div>
      <Card style={cardStyle} styles={{ body: { padding: 'var(--wh-space-md)' } }}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {common.tips.map(tip => (
            <div key={tip.title} style={{ display: 'flex', gap: 'var(--wh-space-sm)', alignItems: 'flex-start' }}>
              <BulbOutlined style={{ color: WH.teal, fontSize: '1rem', marginTop: 4, flexShrink: 0 }} />
              <div>
                <Text strong>{tip.title}</Text>
                <br />
                <Text type="secondary" style={{ fontSize: '0.8125rem', lineHeight: 1.7 }}>{tip.body}</Text>
              </div>
            </div>
          ))}
        </Space>
      </Card>
    </>
  )

  const tasksTab = (
    <>
      {/* 任务的一生 */}
      <Divider orientationMargin={0} style={{ borderColor: dividerColor }}>
        <Space size={8}><SyncOutlined style={{ color: WH.teal }} /><Text strong>{isZh ? '一条任务的一生' : 'Lifecycle of a task'}</Text></Space>
      </Divider>
      <Card style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }} styles={{ body: { padding: 'var(--wh-space-md)' } }}>
        <Space direction="vertical" size="small" style={{ width: '100%' }}>
          {ops.lifecycle.map(s => (
            <div key={s.title}>
              <Text strong style={{ fontSize: '0.85rem' }}>{s.title}</Text>
              <br />
              <Text type="secondary" style={{ fontSize: '0.8125rem', lineHeight: 1.7 }}>{s.body}</Text>
            </div>
          ))}
        </Space>
      </Card>

      {/* Worker 分组 */}
      <Divider orientationMargin={0} style={{ borderColor: dividerColor }}>
        <Space size={8}><ApartmentOutlined style={{ color: WH.teal }} /><Text strong>{isZh ? 'Worker 分组：组内串行、组间并行' : 'Worker groups: serial within, parallel across'}</Text></Space>
      </Divider>
      <Card style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }} styles={{ body: { padding: 'var(--wh-space-sm)' } }}>
        {Object.entries(WORKER_GROUP_INFO).map(([g, info]) => (
          <div key={g} style={{ display: 'flex', gap: 'var(--wh-space-sm)', alignItems: 'flex-start', padding: '4px 0' }}>
            <Tag color={GROUP_TAG_COLOR[g]} style={{ flexShrink: 0, marginInlineEnd: 0 }}>{isZh ? '组' : 'Group'} {g}</Tag>
            <Text type="secondary" style={{ fontSize: '0.8125rem', lineHeight: 1.7 }}>{locale === 'zh' ? info.zh : info.en}</Text>
          </div>
        ))}
        <Paragraph type="secondary" style={{ margin: '8px 0 0', fontSize: 12 }}>
          {isZh
            ? '⚠️ 新增任务必须同时登记进 worker_watchdog.py 的 GROUP_TASK_MAP——只写 TASK_SPECS 不分组 = 任务入队后永远 pending。这是本项目已发生过四次的事故模式。'
            : '⚠️ New tasks MUST also be registered in GROUP_TASK_MAP in worker_watchdog.py — declaring them only in TASK_SPECS leaves them pending forever. This accident happened four times in this project.'}
        </Paragraph>
      </Card>

      {/* 完整任务清单 */}
      <Divider orientationMargin={0} style={{ borderColor: dividerColor }}>
        <Space size={8}><AppstoreOutlined style={{ color: WH.teal }} /><Text strong>{isZh ? `全量任务清单（${TASK_DOCS.length} 个，含工作流脚本与数据流）` : `Full task catalog (${TASK_DOCS.length}, with workflow scripts & data flows)`}</Text></Space>
      </Divider>
      <Card style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }} styles={{ body: { padding: 'var(--wh-space-md)' } }}>
        {taskTable}
      </Card>

      {/* 可靠性机制 */}
      <Divider orientationMargin={0} style={{ borderColor: dividerColor }}>
        <Space size={8}><ExperimentOutlined style={{ color: WH.teal }} /><Text strong>{isZh ? '可靠性机制（超时/重试/自愈）' : 'Reliability mechanisms (timeouts / retry / self-healing)'}</Text></Space>
      </Divider>
      <Card style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }} styles={{ body: { padding: 'var(--wh-space-md)' } }}>
        {ops.mechanisms.map(m => (
          <div key={m.name} style={{ display: 'flex', gap: 'var(--wh-space-sm)', alignItems: 'flex-start', padding: '4px 0' }}>
            <Tag color="geekblue" style={{ flexShrink: 0, marginInlineEnd: 0, minWidth: 96, textAlign: 'center' }}>{m.name}</Tag>
            <Text type="secondary" style={{ fontSize: '0.8125rem', lineHeight: 1.7 }}>{m.body}</Text>
          </div>
        ))}
      </Card>

      {/* 如何维护 */}
      <Divider orientationMargin={0} style={{ borderColor: dividerColor }}>
        <Space size={8}><ToolOutlined style={{ color: WH.teal }} /><Text strong>{isZh ? '任务维护指南' : 'How to maintain tasks'}</Text></Space>
      </Divider>
      <Card style={cardStyle} styles={{ body: { padding: 'var(--wh-space-md)' } }}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {ops.maintain.map(m => (
            <div key={m.title} style={{ display: 'flex', gap: 'var(--wh-space-sm)', alignItems: 'flex-start' }}>
              <ToolOutlined style={{ color: WH.teal, fontSize: '0.875rem', marginTop: 4, flexShrink: 0 }} />
              <div>
                <Text strong>{m.title}</Text>
                <br />
                <Text type="secondary" style={{ fontSize: '0.8125rem', lineHeight: 1.7 }}>{m.body}</Text>
              </div>
            </div>
          ))}
        </Space>
      </Card>

      {/* 上游不可用表现 */}
      <Divider orientationMargin={0} style={{ borderColor: dividerColor }}>
        <Space size={8}><AlertOutlined style={{ color: WH.teal }} /><Text strong>{isZh ? '上游不可用时怎么表现' : 'When upstreams go down'}</Text></Space>
      </Divider>
      <Card style={cardStyle} styles={{ body: { padding: 'var(--wh-space-sm)' } }}>
        <div style={{ display: 'flex', fontWeight: 600, fontSize: '0.8125rem', padding: '6px 8px', borderBottom: `1px solid ${hairline}`, gap: 12 }}>
          <span style={{ flex: 1.1 }}>{ops.upstreamCols[0]}</span>
          <span style={{ flex: 1 }}>{ops.upstreamCols[1]}</span>
          <span style={{ flex: 1.3 }}>{ops.upstreamCols[2]}</span>
        </div>
        {ops.upstreamDown.map(r => (
          <div key={r.sys} style={{ display: 'flex', fontSize: '0.8125rem', padding: '6px 8px', borderBottom: `1px dashed ${hairline}`, gap: 12 }}>
            <span style={{ flex: 1.1 }}><Text strong>{r.sys}</Text></span>
            <span style={{ flex: 1 }}><Text type="secondary">{r.symptom}</Text></span>
            <span style={{ flex: 1.3 }}><Text type="secondary">{r.heal}</Text></span>
          </div>
        ))}
      </Card>
    </>
  )

  const renderPageItem = (meta: { key: string; iframe?: boolean }) => {
    const doc = docs[meta.key]
    if (!doc) return null
    const name = t(NAV_KEY_MAP[meta.key] || meta.key)
    return (
      <div
        key={meta.key}
        style={{
          padding: 'var(--wh-space-sm) var(--wh-space-md)',
          borderBottom: `1px dashed ${hairline}`,
          display: 'flex',
          gap: 'var(--wh-space-sm)',
          alignItems: 'flex-start',
        }}
      >
        <span style={{ color: WH.teal, fontSize: '1rem', marginTop: 2, flexShrink: 0 }}>{PAGE_ICONS[meta.key]}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Space size={6} wrap>
            <Text strong style={{ fontSize: '0.9rem' }}>{name}</Text>
            <Tag style={{ fontSize: 11, lineHeight: '16px', padding: '0 6px', marginInlineEnd: 0 }}>{meta.key}</Tag>
            {meta.iframe && (
              <Tag color="geekblue" style={{ fontSize: 11, lineHeight: '16px', padding: '0 6px', marginInlineEnd: 0 }}>
                iframe
              </Tag>
            )}
          </Space>
          <Paragraph style={{ margin: '4px 0 6px', fontSize: '0.8125rem', lineHeight: 1.7 }}>
            <Text type="secondary">{doc.desc}</Text>
          </Paragraph>
          <ul style={{ margin: 0, paddingLeft: '1.1rem', fontSize: '0.8125rem', lineHeight: 1.8 }}>
            {doc.usage.map((u, i) => <li key={i}><Text type="secondary">{u}</Text></li>)}
          </ul>
          <Button
            type="link"
            size="small"
            style={{ padding: 0, marginTop: 4, height: 'auto' }}
            icon={<ArrowRightOutlined />}
            onClick={() => window.open(pageUrl(meta.key), '_blank', 'noopener')}
          >
            {isZh ? '打开此页' : 'Open page'}
          </Button>
        </div>
      </div>
    )
  }

  const categoryItems = CATEGORIES.map(cat => {
    const pages = cat.pages
      .map(k => PAGE_LIST.find(p => p.key === k))
      .filter((p): p is PageMeta => !!p)
      .map(renderPageItem)
    return {
      key: cat.id,
      label: (
        <Space size={8}>
          <span style={{ color: WH.teal }}>{cat.id === 'tasks' ? <DatabaseOutlined /> : cat.id === 'boards' ? <FundViewOutlined /> : cat.id === 'analysis' ? <ToolOutlined /> : <SafetyCertificateOutlined />}</span>
          <Text strong>{common.categories[cat.id]}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>({pages.length})</Text>
        </Space>
      ),
      children: <div>{pages}</div>,
    }
  })

  const pagesTab = (
    <Collapse
      items={categoryItems}
      defaultActiveKey={['tasks']}
      style={{ background: WH.cardBg, border: WH.cardBorder, borderRadius: 'var(--wh-radius-lg)' }}
    />
  )

  const opsTab = (
    <>
      {/* 进程与端口 */}
      <Divider orientationMargin={0} style={{ borderColor: dividerColor }}>
        <Space size={8}><ControlOutlined style={{ color: WH.teal }} /><Text strong>{isZh ? '进程与端口速查' : 'Processes & ports'}</Text></Space>
      </Divider>
      <Card style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }} styles={{ body: { padding: 'var(--wh-space-sm)' } }}>
        <div style={{ display: 'flex', fontWeight: 600, fontSize: '0.8125rem', padding: '6px 8px', borderBottom: `1px solid ${hairline}`, gap: 12 }}>
          <span style={{ width: 110 }}>{ops.portCols[0]}</span>
          <span style={{ flex: 1.4 }}>{ops.portCols[1]}</span>
          <span style={{ flex: 1 }}>{ops.portCols[2]}</span>
        </div>
        {ops.ports.map(r => (
          <div key={r.port + r.proc} style={{ display: 'flex', fontSize: '0.8125rem', padding: '6px 8px', borderBottom: `1px dashed ${hairline}`, gap: 12 }}>
            <span style={{ width: 110 }}><Text code style={{ fontSize: 11 }}>{r.port}</Text></span>
            <span style={{ flex: 1.4 }}><Text>{r.proc}</Text></span>
            <span style={{ flex: 1 }}><Text type="secondary">{r.guard}</Text></span>
          </div>
        ))}
      </Card>

      {/* 日常巡检 */}
      <Divider orientationMargin={0} style={{ borderColor: dividerColor }}>
        <Space size={8}><RocketOutlined style={{ color: WH.teal }} /><Text strong>{isZh ? '日常巡检（5 分钟）' : 'Daily inspection (5 minutes)'}</Text></Space>
      </Divider>
      <Card style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }} styles={{ body: { padding: 'var(--wh-space-md)' } }}>
        <ul style={{ margin: 0, paddingLeft: '1.1rem', fontSize: '0.8125rem', lineHeight: 2 }}>
          {ops.inspect.map((s, i) => <li key={i}><Text type="secondary">{s}</Text></li>)}
        </ul>
      </Card>

      {/* 日志 */}
      <Divider orientationMargin={0} style={{ borderColor: dividerColor }}>
        <Space size={8}><FileSearchOutlined style={{ color: WH.teal }} /><Text strong>{isZh ? '日志速查（排障首选 worker_runtime*.log）' : 'Log files (start with worker_runtime*.log)'}</Text></Space>
      </Divider>
      <Card style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }} styles={{ body: { padding: 'var(--wh-space-sm)' } }}>
        {ops.logs.map(l => (
          <div key={l.file} style={{ display: 'flex', gap: 'var(--wh-space-sm)', padding: '5px 8px', borderBottom: `1px dashed ${hairline}`, alignItems: 'flex-start' }}>
            <Text code style={{ fontSize: 11, flexShrink: 0, maxWidth: 340 }}>{l.file}</Text>
            <Text type="secondary" style={{ fontSize: '0.8125rem', lineHeight: 1.7 }}>{l.body}</Text>
          </div>
        ))}
        <Paragraph type="secondary" style={{ margin: '8px 0 0', fontSize: 12 }}>
          {isZh ? '⚠️ 全仓库没有日志轮转，log/ 只会一直涨，需人工定期清理；部分日志报错原文含账号，外发前先扫一遍。' : '⚠️ There is no log rotation — log/ grows forever and needs manual cleanup; some error lines contain account names, scan before sharing.'}
        </Paragraph>
      </Card>

      {/* 备份 */}
      <Divider orientationMargin={0} style={{ borderColor: dividerColor }}>
        <Space size={8}><SafetyCertificateOutlined style={{ color: WH.teal }} /><Text strong>{isZh ? '备份（三处都要备，缺一不完整）' : 'Backup (all three, incomplete otherwise)'}</Text></Space>
      </Divider>
      <Card style={{ ...cardStyle, marginBottom: 'var(--wh-space-md)' }} styles={{ body: { padding: 'var(--wh-space-md)' } }}>
        <Space direction="vertical" size="small" style={{ width: '100%' }}>
          {ops.backup.map(b => (
            <div key={b.obj}>
              <Text strong style={{ fontSize: '0.85rem' }}>{b.obj}</Text>
              <br />
              <Text type="secondary" style={{ fontSize: '0.8125rem', lineHeight: 1.7 }}>{b.body}</Text>
            </div>
          ))}
        </Space>
      </Card>

      {/* 清理 */}
      <Divider orientationMargin={0} style={{ borderColor: dividerColor }}>
        <Space size={8}><DeleteOutlined style={{ color: WH.teal }} /><Text strong>{isZh ? '定期清理：什么能删、什么别动' : 'Cleanup: what to delete, what to keep'}</Text></Space>
      </Divider>
      <div style={{ display: 'flex', gap: 'var(--wh-space-md)', flexWrap: 'wrap', marginBottom: 'var(--wh-space-md)' }}>
        <Card size="small" title={isZh ? '可以清理' : 'Safe to clean'} style={{ ...cardStyle, flex: 1, minWidth: 300 }}>
          <ul style={{ margin: 0, paddingLeft: '1.1rem', fontSize: '0.8125rem', lineHeight: 1.9 }}>
            {ops.cleanupSafe.map((c, i) => <li key={i}><Text type="secondary">{c}</Text></li>)}
          </ul>
        </Card>
        <Card size="small" title={isZh ? '不要动' : 'Do NOT touch'} style={{ ...cardStyle, flex: 1, minWidth: 300 }}>
          <ul style={{ margin: 0, paddingLeft: '1.1rem', fontSize: '0.8125rem', lineHeight: 1.9 }}>
            {ops.cleanupKeep.map((c, i) => <li key={i}><Text type="secondary">{c}</Text></li>)}
          </ul>
        </Card>
      </div>

      {/* 配置与凭据 */}
      <Divider orientationMargin={0} style={{ borderColor: dividerColor }}>
        <Space size={8}><SettingOutlined style={{ color: WH.teal }} /><Text strong>{isZh ? '配置与凭据' : 'Configuration & credentials'}</Text></Space>
      </Divider>
      <Card style={cardStyle} styles={{ body: { padding: 'var(--wh-space-md)' } }}>
        <Paragraph style={{ margin: '0 0 8px', fontSize: '0.8125rem', lineHeight: 1.8 }}>{ops.configPriority}</Paragraph>
        <ul style={{ margin: 0, paddingLeft: '1.1rem', fontSize: '0.8125rem', lineHeight: 1.9 }}>
          {ops.credentialNote.map((c, i) => <li key={i}><Text type="secondary">{c}</Text></li>)}
        </ul>
      </Card>
    </>
  )

  const faqTab = (
    <Collapse
      items={common.faq.map((f, i) => ({
        key: String(i),
        label: <Text strong>{f.q}</Text>,
        children: <Paragraph style={{ margin: 0, fontSize: '0.8125rem', lineHeight: 1.8 }}>{f.a}</Paragraph>,
      }))}
      style={{ background: WH.cardBg, border: WH.cardBorder, borderRadius: 'var(--wh-radius-lg)' }}
    />
  )

  /** 导出当前语言的帮助为 Markdown 文件（与 docs/manual/15-user-help.md 同源） */
  const exportMarkdown = () => {
    const md = buildHelpMarkdown(locale)
    const date = new Date().toISOString().slice(0, 10)
    downloadText(`myapp-help-${locale}-${date}.md`, md)
  }

  return (
    <div style={{ maxWidth: 1180, margin: '0 auto' }}>
      {/* 页头 */}
      <div style={{ textAlign: 'center', padding: 'var(--wh-space-md) 0' }}>
        <QuestionCircleOutlined style={{ fontSize: '2rem', color: WH.teal }} />
        <Title level={3} style={{ margin: '8px 0 4px', color: WH.teal }}>
          {isZh ? '使用帮助' : 'Help & Guide'}
        </Title>
        <Text type="secondary" style={{ fontSize: '0.8125rem' }}>
          {isZh
            ? '平台功能描述与使用指南 — 内容依据项目文档 docs/manual/（总览、任务系统、数据层、集成、运维）整理'
            : 'Platform features & usage — compiled from the project docs under docs/manual/ (overview, task system, data layer, integrations, operations)'}
        </Text>
        <div style={{ marginTop: 'var(--wh-space-sm)' }}>
          <Space size={8} wrap style={{ justifyContent: 'center' }}>
            <Tooltip title={isZh ? '下载当前语言的帮助全文（Markdown），与 docs/manual/15-user-help.md 同源' : 'Download the full help in the current language (Markdown), same source as docs/manual/15-user-help.md'}>
              <Button size="small" icon={<DownloadOutlined />} onClick={exportMarkdown}>
                {isZh ? '导出 Markdown' : 'Export Markdown'}
              </Button>
            </Tooltip>
            <Tooltip title={isZh ? '调起浏览器打印，可选「另存为 PDF」' : 'Open the browser print dialog (save as PDF available)'}>
              <Button size="small" icon={<PrinterOutlined />} onClick={() => window.print()}>
                {isZh ? '打印 / PDF' : 'Print / PDF'}
              </Button>
            </Tooltip>
            <Tooltip title={isZh ? '打开整本项目手册（13 章，含封面/目录，浏览器打印即可另存为 PDF）' : 'Open the full project manual (13 chapters); print it in the browser to save as PDF'}>
              <Button size="small" icon={<BookOutlined />} onClick={() => window.open(manualUrl(), '_blank', 'noopener')}>
                {isZh ? '完整手册' : 'Full Manual'}
              </Button>
            </Tooltip>
            <Tooltip title={isZh ? '把整本手册下载为单个 HTML 文件（离线查看 / 分发）' : 'Download the full manual as a single HTML file (offline viewing / sharing)'}>
              <Button size="small" icon={<DownloadOutlined />} onClick={downloadManual}>
                {isZh ? '下载手册 HTML' : 'Download Manual HTML'}
              </Button>
            </Tooltip>
          </Space>
        </div>
      </div>

      <Tabs
        defaultActiveKey="intro"
        size="large"
        items={[
          { key: 'intro', label: ops.tabs.intro, children: introTab },
          { key: 'tasks', label: ops.tabs.tasks, children: tasksTab },
          { key: 'pages', label: ops.tabs.pages, children: pagesTab },
          { key: 'ops', label: ops.tabs.ops, children: opsTab },
          { key: 'faq', label: isZh ? '常见问题' : 'FAQ', children: faqTab },
        ]}
      />

      <Paragraph type="secondary" style={{ fontSize: 12, textAlign: 'center', marginTop: 'var(--wh-space-lg)' }}>
        {isZh
          ? '更多细节参见项目文档：docs/manual/（01 总览与术语表 · 04 任务系统 · 11 功能页手册 · 13 运维手册 · 14 外部系统与数据流）。本页可导出 Markdown，仓库内同源文档为 docs/manual/15-user-help.md；整本手册网页版见 /myapp/manual.html。'
          : 'See the project docs for more: docs/manual/ (01 overview & glossary · 04 task system · 11 feature guide · 13 operations · 14 integrations & data flows). This page exports to Markdown; the repo copy is docs/manual/15-user-help.md; the full manual web edition lives at /myapp/manual.html.'}
      </Paragraph>
    </div>
  )
}

