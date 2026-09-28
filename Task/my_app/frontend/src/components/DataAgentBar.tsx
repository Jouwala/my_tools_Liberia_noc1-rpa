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
import { Button, Input, Select, Table, Alert, Space, Typography, Tag, message } from 'antd'
import { PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'
import { CardBase } from '../components/cards'
import { WH } from '../theme'

const { TextArea } = Input

/** AI provider 列表：与 backend/services/incident_ai_service.py 的 PROVIDERS 保持一致 */
const PROVIDERS = [
  'openai', 'deepseek', 'qianwen', 'glm-coding', 'doubao', 'agnes', 'gemini',
]

/** API key 只存本机浏览器，不落服务端 */
const KEY_STORAGE = 'myapp-data-agent-provider'
const KEY_PREFIX = 'myapp-data-agent-key-'

interface Row {
  [k: string]: unknown
}

export default function DataAgentBar() {
  const { t } = useI18n()
  const [question, setQuestion] = useState('')
  const [provider, setProvider] = useState<string>(
    () => localStorage.getItem(KEY_STORAGE) || 'deepseek',
  )
  const [apiKey, setApiKey] = useState<string>(
    () => localStorage.getItem(KEY_PREFIX + (localStorage.getItem(KEY_STORAGE) || 'deepseek')) || '',
  )
  const [model, setModel] = useState('')
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
  }

  const onKeyChange = (k: string) => {
    setApiKey(k)
    // 仅本机保存，便于下次免输入；服务端不留存
    localStorage.setItem(KEY_PREFIX + provider, k)
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
        provider, api_key: apiKey, model, run: true, ...payload,
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
    run({ question })
  }

  /* 手改 SQL 重跑：不复用模型的生成结果，但**仍走服务端护栏**
     —— 用户改出 DROP 也会被后端拒绝，前端不做也不信任校验。 */
  const onRerun = () => {
    if (!sql.trim()) return
    run({ question, sql })
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
        <Space wrap>
          <Select
            value={provider}
            onChange={onProviderChange}
            options={PROVIDERS.map((p) => ({ value: p, label: p }))}
            style={{ width: 140 }}
            size="small"
          />
          <Input.Password
            value={apiKey}
            onChange={(e) => onKeyChange(e.target.value)}
            placeholder={t('dataAgent.apiKeyPlaceholder')}
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
        </Space>

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

        {error && (
          <Alert type="error" showIcon message={t('dataAgent.failed')} description={error} />
        )}

        {sql && (
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

        {truncated && (
          <Alert
            type="warning"
            showIcon
            message={t('dataAgent.truncated', { n: rowCount })}
          />
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
          {t('dataAgent.disclaimer')}
        </Typography.Text>
      </Space>
    </CardBase>
  )
}
