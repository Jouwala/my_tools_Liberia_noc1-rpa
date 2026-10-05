/* ============================================================================
 * DataAgentBar —— TableBrowser 内嵌的「只读 NL2SQL」入口
 * ----------------------------------------------------------------------------
 * 定位：探索性副驾。**不参与任何定时报表/看板数字的产出**。
 * 决策依据与风险清单见 docs/DATA_AGENT_EVALUATION.md。
 *
 * 三条必须保留的交互设计（都是「让用户能核对」这一条推出来的）：
 *   1. **展示实际执行的 SQL**，且可编辑后重跑 —— LLM 会写出「语法正确、语义错误」的
 *      SQL，这无法自动消除，唯一诚实的做法是把 SQL 摊开给用户看。
 *   2. **展示行数与截断标记** —— 达到 LIMIT 说明结果不完整，必须显式暴露，
 *      不能让用户把「前 200 行」当成「全部」（沿用项目下钻截断的既有约定）。
 *   3. **API key 只存 localStorage、只随请求体发送** —— 服务端不落盘、不写日志，
 *      与 incident_ai_service.py 的既有安全约定一致。
 *
 * 卡片/主题/文案一律走项目统一入口（components/cards、WH 令牌、t() 双字典）。
 * ========================================================================== */
import { useState } from 'react'
import { Button, Input, Select, Table, Alert, Space, Typography, Tag, message, Segmented, Tooltip } from 'antd'
import {
  PlayCircleOutlined, ReloadOutlined, SettingOutlined, DownloadOutlined, CodeOutlined,
} from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'
import { CardBase } from '../components/cards'
import { WH } from '../theme'
import { exportAoaReport } from '../utils/excelReport'

const { TextArea } = Input

/** AI provider 列表：与 backend/services/incident_ai_service.py 的 PROVIDERS 保持一致 */
const PROVIDERS = [
  'openai', 'deepseek', 'qianwen', 'glm-coding', 'doubao', 'agnes', 'gemini',
]

/** 不支持 NL2SQL 的 provider：gemini 走 generateContent 协议，与本功能的
 *  OpenAI 兼容调用不同构（见 backend/services/nl2sql_service.py:_call_provider）。
 *  在界面上直接标注，避免用户选完才发现必然失败 —— 后端也会返回同样的中文原因。 */
const NL2SQL_UNSUPPORTED = ['gemini']

/** API key 只存本机浏览器，不落服务端 */
const KEY_STORAGE = 'myapp-data-agent-provider'
const KEY_PREFIX = 'myapp-data-agent-key-'
/** 自定义 base URL 同样只存本机浏览器，按 provider 分别记忆 */
const BASEURL_PREFIX = 'myapp-data-agent-baseurl-'

interface Row {
  [k: string]: unknown
}

/** 工作模式：
 *  - `ai`     = 自然语言问数（需要 API key）
 *  - `manual` = 直接写 SQL（**不需要** key，不经过 AI）
 *  手动模式是 2026-10-05 新增：此前「手写 SQL」只能靠 AI 先跑一次、
 *  再在结果里改 SQL 重跑 —— 想直接写 SQL 的人被迫先配一个 key。 */
type Mode = 'ai' | 'manual'

export default function DataAgentBar() {
  const { t } = useI18n()
  const [mode, setMode] = useState<Mode>('ai')
  const [question, setQuestion] = useState('')
  const [provider, setProvider] = useState<string>(
    () => localStorage.getItem(KEY_STORAGE) || 'deepseek',
  )
  const [apiKey, setApiKey] = useState<string>(
    () => localStorage.getItem(KEY_PREFIX + (localStorage.getItem(KEY_STORAGE) || 'deepseek')) || '',
  )
  const [model, setModel] = useState('')
  /** 自定义推理端点（自建/代理模型）。留空 = 用后端按 provider 内置的默认端点 ——
   *  这正是「不填也能用」的原因，故默认折叠，不打扰常规用户。 */
  const [baseUrl, setBaseUrl] = useState<string>(
    () => localStorage.getItem(BASEURL_PREFIX + (localStorage.getItem(KEY_STORAGE) || 'deepseek')) || '',
  )
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sql, setSql] = useState('')
  const [rows, setRows] = useState<Row[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [rowCount, setRowCount] = useState(0)
  const [truncated, setTruncated] = useState(false)

  const onProviderChange = (p: string) => {
    setProvider(p)
    localStorage.setItem(KEY_STORAGE, p)
    setApiKey(localStorage.getItem(KEY_PREFIX + p) || '')
    setBaseUrl(localStorage.getItem(BASEURL_PREFIX + p) || '')
  }

  const onKeyChange = (k: string) => {
    setApiKey(k)
    // 仅本机保存，便于下次免输入；服务端不留存
    localStorage.setItem(KEY_PREFIX + provider, k)
  }

  const onBaseUrlChange = (u: string) => {
    setBaseUrl(u)
    localStorage.setItem(BASEURL_PREFIX + provider, u)
  }

  const applyResult = (d: any) => {
    setSql(d.sql || '')
    setColumns(d.columns || [])
    setRows(d.rows || [])
    setRowCount(d.row_count ?? (d.rows || []).length)
    setTruncated(!!d.truncated)
  }

  const run = async (payload: Record<string, unknown>) => {
    setLoading(true)
    setError('')
    try {
      const { data } = await api.post('/data-agent/ask', {
        provider, api_key: apiKey, model, base_url: baseUrl.trim(), run: true, ...payload,
      })
      applyResult(data)
    } catch (e: any) {
      const msg = e?.response?.data?.error || e?.message || String(e)
      setError(msg)
      setRows([])
      setColumns([])
      setRowCount(0)
    } finally {
      setLoading(false)
    }
  }

  const onAsk = () => {
    if (!question.trim()) {
      message.warning(t('dataAgent.needQuestion'))
      return
    }
    // 缺 key 时后端会回「缺少 API key」，但那是英文语境的转述；
    // 这里给一句明确的中文指引，直接告诉用户该做什么。
    if (!apiKey.trim()) {
      message.warning(t('dataAgent.needKeyHint'))
      setError(t('dataAgent.needKeyHint'))
      return
    }
    run({ question })
  }

  /* 手改 SQL 重跑：不复用模型的生成结果，但**仍走服务端护栏**
     —— 用户改出 DROP 也会被后端拒绝，前端不做也不信任校验。 */
  const onRerun = () => {
    if (!sql.trim()) return
    run({ question, sql })
  }

  /* 手动模式执行：直接把输入的 SQL 交给同一端点。
     复用 `run` 而不是另写一份请求 —— 护栏、截断标记、错误处理的语义必须一致，
     两条路径若各写一套，迟早出现「AI 模式拦住了 DROP、手动模式没拦住」。 */
  const onRunManual = () => {
    if (!sql.trim()) {
      message.warning(t('dataAgent.needQuestion'))
      return
    }
    run({ question: '', sql })
  }

  /* 导出当前结果。
     刻意**不**做「重新查询全量再导出」：结果已被服务端 LIMIT 截断时，
     拿到的就只有这一批，导出一个「看起来是全量」的文件是更坏的行为。
     故此处只导出已返回的行；触顶时行数旁会显示「已达上限」标签说明这一点。 */
  const onExport = async () => {
    if (!rows.length || !columns.length) {
      message.warning(t('dataAgent.exportEmpty'))
      return
    }
    await exportAoaReport({
      filename: `data_agent_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '')}`,
      sheetName: 'query_result',
      title: t('dataAgent.title'),
      subtitle: sql,
      header: columns,
      rows: rows.map((r) => columns.map((c) => {
        const v = r[c]
        // null/undefined 导出为空单元格，与界面上的 '—' 区分开：
        // 表格里 '—' 是「给人看的占位」，Excel 里应是真空值，便于排序/筛选。
        return v === null || v === undefined ? null : (v as never)
      })),
    })
    message.success(t('dataAgent.exported', { n: rows.length }))
  }

  const tableColumns = columns.map((c) => ({
    title: c,
    dataIndex: c,
    key: c,
    ellipsis: true,
    render: (v: unknown) => (v === null || v === undefined ? '—' : String(v)),
  }))

  return (
    <CardBase
      title={t('dataAgent.title')}
      extra={
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {t('dataAgent.readonlyHint')}
        </Typography.Text>
      }
    >
      <Space direction="vertical" style={{ width: '100%' }} size="small">
        {/* 模式切换：手动模式不碰 AI，故 provider/key/模型整组在手动模式下隐藏 ——
            留着会让人以为「不填 key 也能跑 AI」，也会让手动模式看起来仍然依赖 AI。 */}
        <Segmented
          value={mode}
          onChange={(v) => {
            setMode(v as Mode)
            // 切换模式时清掉错误，避免 AI 的报错残留在手动模式里误导用户
            setError('')
          }}
          size="small"
          options={[
            { value: 'ai', label: t('dataAgent.mode.ai') },
            { value: 'manual', label: t('dataAgent.mode.manual'), icon: <CodeOutlined /> },
          ]}
        />

        {mode === 'ai' && (
          <>
            <Space wrap>
              <Select
                value={provider}
                onChange={onProviderChange}
                options={PROVIDERS.map((p) => ({
                  value: p,
                  label: NL2SQL_UNSUPPORTED.includes(p)
                    ? `${p}（${t('dataAgent.nl2sqlUnsupported')}）`
                    : p,
                }))}
                style={{ width: NL2SQL_UNSUPPORTED.includes(provider) ? 230 : 140 }}
                size="small"
              />
              <Input.Password
                value={apiKey}
                onChange={(e) => onKeyChange(e.target.value)}
                placeholder={t('dataAgent.apiKeyPlaceholder')}
                status={!apiKey.trim() ? 'warning' : undefined}
                style={{ width: 260 }}
                size="small"
              />
              <Input
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={t('dataAgent.modelPlaceholder')}
                style={{ width: 170 }}
                size="small"
              />
              <Button
                size="small"
                type="text"
                icon={<SettingOutlined />}
                onClick={() => setAdvancedOpen((v) => !v)}
              >
                {t('dataAgent.advanced')}
              </Button>
            </Space>

            {/* 高级：自定义推理端点。留空即用后端按 provider 内置的默认地址 ——
                 「没有 base URL 输入框」曾经是这里最容易误解的地方，故显式说明。 */}
            {advancedOpen && (
              <Space wrap align="center">
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {t('dataAgent.baseUrlLabel')}
                </Typography.Text>
                <Input
                  value={baseUrl}
                  onChange={(e) => onBaseUrlChange(e.target.value)}
                  placeholder={t('dataAgent.baseUrlPlaceholder')}
                  style={{ width: 420 }}
                  size="small"
                  allowClear
                />
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {t('dataAgent.baseUrlHint')}
                </Typography.Text>
              </Space>
            )}

            {/* 缺 key 是初次使用最常撞到的失败，直接给出可操作指引，而不是等报错 */}
            {!apiKey.trim() && (
              <Alert type="info" showIcon message={t('dataAgent.needKeyHint')} />
            )}

            <TextArea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={t('dataAgent.questionPlaceholder')}
              autoSize={{ minRows: 2, maxRows: 4 }}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault()
                  onAsk()
                }
              }}
            />

            <Space>
              <Button
                type="primary"
                size="small"
                icon={<PlayCircleOutlined />}
                loading={loading}
                onClick={onAsk}
              >
                {t('dataAgent.ask')}
              </Button>
              <Button
                size="small"
                icon={<ReloadOutlined />}
                disabled={!sql.trim()}
                loading={loading}
                onClick={onRerun}
              >
                {t('dataAgent.rerun')}
              </Button>
            </Space>
          </>
        )}

        {mode === 'manual' && (
          <>
            <Alert type="info" showIcon message={t('dataAgent.manualHint')} />
            <TextArea
              value={sql}
              onChange={(e) => setSql(e.target.value)}
              placeholder={t('dataAgent.manualPlaceholder')}
              autoSize={{ minRows: 4, maxRows: 12 }}
              style={{ fontFamily: 'monospace', fontSize: 12 }}
              onPressEnter={(e) => {
                // Ctrl/Cmd+Enter 执行：SQL 天然多行，回车必须是换行
                if (e.ctrlKey || e.metaKey) {
                  e.preventDefault()
                  onRunManual()
                }
              }}
            />
            <Space wrap>
              <Button
                type="primary"
                size="small"
                icon={<PlayCircleOutlined />}
                loading={loading}
                onClick={onRunManual}
              >
                {t('dataAgent.manualRun')}
              </Button>
              <Tooltip title={sql}>
                <Button
                  size="small"
                  type="link"
                  style={{ padding: 0 }}
                  onClick={() =>
                    setSql('SELECT * FROM eflow_tt WHERE alarm_clear_time < created_time')
                  }
                >
                  {t('dataAgent.manualExample')}
                </Button>
              </Tooltip>
            </Space>
          </>
        )}

        {error && (
          <Alert type="error" showIcon message={t('dataAgent.failed')} description={error} />
        )}

        {/* AI 模式下 SQL 展示在输入框下方（由模型生成、可编辑）；
            手动模式下 SQL 本身就是输入框，不再重复渲染一块只读文本。 */}
        {mode === 'ai' && sql && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <Typography.Text strong style={{ fontSize: 12 }}>
                {t('dataAgent.generatedSql')}
              </Typography.Text>
              <Tag color="blue">{t('dataAgent.editable')}</Tag>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {t('dataAgent.rowCount', { n: rowCount })}
              </Typography.Text>
            </div>
            <TextArea
              value={sql}
              onChange={(e) => setSql(e.target.value)}
              autoSize={{ minRows: 3, maxRows: 10 }}
              style={{ fontFamily: 'monospace', fontSize: 12 }}
            />
          </div>
        )}

        {/* 结果元信息 + 导出（AI 模式下元信息在 SQL 块里，导出按钮同样可用）。
            截断提示（2026-10-05 移除）：上限放宽到 5 万行后，正常查询不会再碰到，
            常驻告警条反而成了噪声。但「拿到的可能不是全量」这个事实不能消失 ——
            故改为**只在真的触顶时**，把一句极简说明挂在行数旁边（不弹告警条、不占版面）。 */}
        {columns.length > 0 && (
          <Space wrap align="center">
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {t('dataAgent.rowCount', { n: rowCount })}
            </Typography.Text>
            {truncated && (
              <Tooltip title={t('dataAgent.truncatedTip', { n: rowCount })}>
                <Tag color="orange" style={{ marginInlineEnd: 0 }}>
                  {t('dataAgent.capped')}
                </Tag>
              </Tooltip>
            )}
            <Button size="small" icon={<DownloadOutlined />} onClick={onExport}>
              {t('dataAgent.export')}
            </Button>
          </Space>
        )}

        {columns.length > 0 && (
          <Table
            size="small"
            rowKey={(_, i) => String(i)}
            columns={tableColumns as any}
            dataSource={rows}
            pagination={{ pageSize: 20, size: 'small', showSizeChanger: false }}
            scroll={{ x: 'max-content' }}
            style={{ background: WH.cardBg }}
          />
        )}

        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {mode === 'ai' ? t('dataAgent.disclaimer') : t('dataAgent.manualHint')}
        </Typography.Text>
      </Space>
    </CardBase>
  )
}
