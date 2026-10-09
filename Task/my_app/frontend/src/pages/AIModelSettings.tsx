// Settings「AI 模型」页签：选择本地 / 在线模型、配置具体参数、对比测试
import { useEffect, useState } from 'react'
import {
  Alert, Button, Card, Col, Divider, Input, message, Row, Select, Space, Switch, Typography,
} from 'antd'
import {
  CheckCircleOutlined, DeleteOutlined, LoadingOutlined, PlusOutlined, SaveOutlined,
} from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'
import { WH } from '../theme'

const { Text, Paragraph } = Typography
const { TextArea } = Input

interface AiModelConfig {
  provider: 'local' | 'openwebui' | 'both'
  local_enabled: boolean
  local_model: string
  local_base_url: string
  openwebui_model: string
  openwebui_base_url: string
  openwebui_email: string
  openwebui_password: string
}

interface ChainInfo {
  provider: string
  chain: string
  local_model: string
  openwebui_model: string
  local_base_url: string
  openwebui_base_url: string
}

interface CompareModel {
  provider: 'workbuddy' | 'openwebui'
  model: string
}

interface CompareResult {
  provider: string
  model: string
  ok: boolean
  response: string | null
  error: string | null
  elapsed_ms: number
}

const PROVIDER_OPTIONS = [
  { value: 'both', label_zh: '本地优先 + Open WebUI 备用', label_en: 'Local first + Open WebUI fallback' },
  { value: 'local', label_zh: '仅本地 WorkBuddy', label_en: 'Local WorkBuddy only' },
  { value: 'openwebui', label_zh: '仅 Open WebUI', label_en: 'Open WebUI only' },
]

export default function AIModelSettings() {
  const { locale } = useI18n()
  const zh = locale === 'zh'

  const L = {
    title: zh ? 'AI 模型设置' : 'AI Model Settings',
    subtitle: zh
      ? '配置 TT 分析的 AI 模型来源：本地 WorkBuddy 代理（无需联网）或 Open WebUI 在线模型。保存后下次分析立即生效。'
      : 'Configure AI model source for TT analysis: local WorkBuddy proxy (no internet) or Open WebUI online. Saved changes take effect on next analysis.',
    currentChain: zh ? '当前调用链' : 'Current chain',
    provider: zh ? '模型模式' : 'Provider',
    providerHint: zh ? 'both = 本地优先、Open WebUI 备用；local = 仅本地；openwebui = 仅在线' : 'both = local first + OWU fallback; local = local only; openwebui = online only',
    localSection: zh ? '本地 WorkBuddy 代理' : 'Local WorkBuddy Proxy',
    localEnabled: zh ? '启用本地代理' : 'Enable local proxy',
    localModel: zh ? '本地模型 ID' : 'Local model ID',
    localModelHint: zh ? '如 deepseek-v4.1-flash（需本地 WorkBuddy 代理已启动）' : 'e.g. deepseek-v4.1-flash (requires local WorkBuddy proxy running)',
    localBaseUrl: zh ? '本地代理地址' : 'Local proxy URL',
    localBaseUrlHint: zh ? '默认 http://127.0.0.1:8788/v1' : 'Default: http://127.0.0.1:8788/v1',
    owuSection: zh ? 'Open WebUI 在线模型' : 'Open WebUI Online',
    owuModel: zh ? '模型 ID' : 'Model ID',
    owuModelHint: zh ? '固定 ID 或 auto / auto:pattern 自动选最新版本（支持 agnes-*-flash）' : 'Fixed ID or auto / auto:pattern to auto-select latest version',
    owuBaseUrl: zh ? 'Open WebUI 地址' : 'Open WebUI URL',
    owuBaseUrlHint: zh ? '如 http://192.168.100.27:3000' : 'e.g. http://192.168.100.27:3000',
    owuEmail: zh ? '登录邮箱' : 'Email',
    owuPassword: zh ? '登录密码' : 'Password',
    save: zh ? '保存配置' : 'Save',
    saved: zh ? '配置已保存，下次分析生效' : 'Config saved, effective on next analysis',
    saveFailed: zh ? '保存失败' : 'Save failed',
    loading: zh ? '加载中...' : 'Loading...',
    loadFailed: zh ? '加载配置失败' : 'Failed to load config',
    // 对比测试
    compareTitle: zh ? '模型对比测试' : 'Model Comparison',
    compareHint: zh
      ? '同一问题同时发给多个模型，对比输出质量与响应速度。'
      : 'Send the same prompt to multiple models simultaneously and compare output quality and latency.',
    comparePrompt: zh ? '测试问题' : 'Test Prompt',
    comparePromptPlaceholder: zh
      ? '请输入要测试的问题，例如：VIP 站点告警 9920，关掉 3 个基站，TT 级别应判多少？'
      : 'Enter a question, e.g.: VIP site alarm 9920, 3 sites down, what TT level?',
    compareSystem: zh ? '系统提示（可选）' : 'System Prompt (optional)',
    compareSystemPlaceholder: zh ? '留空则使用默认语言指令' : 'Leave empty to use default language instruction',
    compareModels: zh ? '参测模型' : 'Models to Compare',
    addModel: zh ? '添加模型' : 'Add Model',
    providerWorkbuddy: zh ? '本地 WorkBuddy' : 'Local WorkBuddy',
    providerOpenwebui: zh ? 'Open WebUI' : 'Open WebUI',
    runCompare: zh ? '开始对比' : 'Run Compare',
    comparing: zh ? '对比中...' : 'Comparing...',
    compareFailed: zh ? '对比请求失败' : 'Comparison request failed',
    response: zh ? '回复' : 'Response',
    latency: zh ? '耗时' : 'Latency',
    success: zh ? '成功' : 'OK',
    failed: zh ? '失败' : 'Failed',
    modelLabel: (p: string, m: string) => p === 'workbuddy'
      ? (zh ? `本地 ${m}` : `Local ${m}`)
      : (zh ? `OWU ${m}` : `OWU ${m}`),
  }

  const [cfg, setCfg] = useState<AiModelConfig | null>(null)
  const [chain, setChain] = useState<ChainInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // 表单字段
  const [provider, setProvider] = useState<'local' | 'openwebui' | 'both'>('both')
  const [localEnabled, setLocalEnabled] = useState(true)
  const [localModel, setLocalModel] = useState('')
  const [localBaseUrl, setLocalBaseUrl] = useState('')
  const [owuModel, setOwuModel] = useState('')
  const [owuBaseUrl, setOwuBaseUrl] = useState('')
  const [owuEmail, setOwuEmail] = useState('')
  const [owuPassword, setOwuPassword] = useState('')

  // 对比测试状态
  const [comparePrompt, setComparePrompt] = useState('')
  const [compareSystem, setCompareSystem] = useState('')
  const [compareModels, setCompareModels] = useState<CompareModel[]>([])
  const [compareRunning, setCompareRunning] = useState(false)
  const [compareResults, setCompareResults] = useState<CompareResult[]>([])

  const inputStyle = {
    background: 'rgba(0,0,0,0.3)',
    border: '1px solid rgba(0, 217, 255,0.25)',
    color: WH.text,
  }

  const loadConfig = () => {
    setLoading(true)
    setError('')
    Promise.all([
      api.get('/ai-model-settings'),
      api.get('/ai-model-settings/chain'),
    ])
      .then(([cfgRes, chainRes]) => {
        const c: AiModelConfig = cfgRes.data.config
        setCfg(c)
        setChain(chainRes.data)
        setProvider(c.provider || 'both')
        setLocalEnabled(c.local_enabled !== false)
        setLocalModel(c.local_model || '')
        setLocalBaseUrl(c.local_base_url || '')
        setOwuModel(c.openwebui_model || '')
        setOwuBaseUrl(c.openwebui_base_url || '')
        setOwuEmail(c.openwebui_email || '')
        setOwuPassword(c.openwebui_password || '')
        // 对比测试默认带上当前配置的两个模型
        setCompareModels([
          { provider: 'workbuddy', model: c.local_model || 'deepseek-v4.1-flash' },
          { provider: 'openwebui', model: c.openwebui_model || 'agnes-2.5-flash' },
        ])
      })
      .catch(() => setError(L.loadFailed))
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadConfig() /* eslint-disable-line react-hooks/exhaustive-deps */ }, [])

  const saveConfig = () => {
    setSaving(true)
    const patch = {
      provider,
      local_enabled: localEnabled,
      local_model: localModel.trim(),
      local_base_url: localBaseUrl.trim(),
      openwebui_model: owuModel.trim(),
      openwebui_base_url: owuBaseUrl.trim(),
      openwebui_email: owuEmail.trim(),
      openwebui_password: owuPassword,
    }
    api.put('/ai-model-settings', patch)
      .then(() => {
        message.success(L.saved)
        loadConfig()
      })
      .catch((e) => {
        message.error(L.saveFailed + ': ' + (e?.response?.data?.detail || ''))
        setSaving(false)
      })
  }

  const addCompareModel = () => {
    setCompareModels(prev => [...prev, { provider: 'workbuddy', model: '' }])
  }

  const removeCompareModel = (idx: number) => {
    setCompareModels(prev => prev.filter((_, i) => i !== idx))
  }

  const updateCompareModel = (idx: number, field: keyof CompareModel, value: string) => {
    setCompareModels(prev => prev.map((m, i) => i === idx ? { ...m, [field]: value } : m))
  }

  const runCompare = () => {
    if (!comparePrompt.trim()) {
      message.warning(zh ? '请输入测试问题' : 'Please enter a test prompt')
      return
    }
    const valid = compareModels.filter(m => m.model.trim())
    if (!valid.length) {
      message.warning(zh ? '请至少添加一个模型 ID' : 'Please add at least one model ID')
      return
    }
    setCompareRunning(true)
    setCompareResults([])
    api.post('/ai-model-settings/compare', {
      prompt: comparePrompt.trim(),
      system_prompt: compareSystem.trim(),
      models: valid,
    })
      .then(res => {
        setCompareResults(res.data.results || [])
      })
      .catch(e => {
        message.error(L.compareFailed + ': ' + (e?.response?.data?.detail || e.message || ''))
      })
      .finally(() => setCompareRunning(false))
  }

  const providerLabel = PROVIDER_OPTIONS.find(o => o.value === provider)

  return (
    <div style={{ maxWidth: 'min(100%, 60rem)' }}>
      <Text style={{ color: WH.textMuted, fontSize: '0.8125rem' }}>{L.subtitle}</Text>

      {error && (
        <Alert type="error" message={error} showIcon style={{ marginTop: '0.75rem' }} />
      )}

      {chain && (
        <Card
          size="small"
          style={{ marginTop: '0.75rem', background: 'rgba(0,217,255,0.06)', border: '1px solid rgba(0,217,255,0.2)' }}
          styles={{ body: { padding: '0.625rem 0.875rem' } }}
        >
          <Space>
            <CheckCircleOutlined style={{ color: WH.teal }} />
            <Text style={{ color: WH.text, fontSize: '0.8125rem' }}>{L.currentChain}：</Text>
            <Text style={{ color: WH.teal, fontSize: '0.8125rem', fontWeight: 600 }}>{chain.chain}</Text>
          </Space>
        </Card>
      )}

      {loading ? (
        <Card style={{ marginTop: '0.75rem', background: WH.bg }}><Text style={{ color: WH.textMuted }}>{L.loading}</Text></Card>
      ) : (
        <>
          {/* 模型模式 */}
          <Card
            size="small"
            title={<Text style={{ color: WH.text, fontSize: '0.875rem' }}>{L.provider}</Text>}
            style={{ marginTop: '0.75rem' }}
            styles={{ header: { background: 'var(--wh-page-bg)' }, body: { background: WH.bg } }}
          >
            <Select
              value={provider}
              onChange={(v) => setProvider(v)}
              options={PROVIDER_OPTIONS.map(o => ({ value: o.value, label: zh ? o.label_zh : o.label_en }))}
              style={{ width: 'min(100%, 18.75rem)' }}
            />
            <Text style={{ color: WH.textDim, fontSize: '0.6875rem', display: 'block', marginTop: '0.25rem' }}>
              {L.providerHint}
            </Text>
          </Card>

          {/* 本地代理 */}
          {(provider === 'both' || provider === 'local') && (
            <Card
              size="small"
              title={<Text style={{ color: WH.text, fontSize: '0.875rem' }}>{L.localSection}</Text>}
              style={{ marginTop: '0.5rem' }}
              styles={{ header: { background: 'var(--wh-page-bg)' }, body: { background: WH.bg } }}
            >
              <Row gutter={[16, 12]}>
                <Col xs={24} md={12}>
                  <div style={{ marginBottom: '0.25rem' }}>
                    <Space>
                      <Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{L.localEnabled}</Text>
                      <Switch size="small" checked={localEnabled} onChange={setLocalEnabled} />
                    </Space>
                  </div>
                  <div>
                    <Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{L.localModel}</Text>
                    <Input
                      value={localModel}
                      onChange={(e) => setLocalModel(e.target.value)}
                      placeholder="deepseek-v4.1-flash"
                      style={{ marginTop: '0.25rem', ...inputStyle }}
                    />
                    <Text style={{ color: WH.textDim, fontSize: '0.6875rem' }}>{L.localModelHint}</Text>
                  </div>
                </Col>
                <Col xs={24} md={12}>
                  <div>
                    <Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{L.localBaseUrl}</Text>
                    <Input
                      value={localBaseUrl}
                      onChange={(e) => setLocalBaseUrl(e.target.value)}
                      placeholder="http://127.0.0.1:8788/v1"
                      style={{ marginTop: '0.25rem', ...inputStyle }}
                    />
                    <Text style={{ color: WH.textDim, fontSize: '0.6875rem' }}>{L.localBaseUrlHint}</Text>
                  </div>
                </Col>
              </Row>
            </Card>
          )}

          {/* Open WebUI */}
          {(provider === 'both' || provider === 'openwebui') && (
            <Card
              size="small"
              title={<Text style={{ color: WH.text, fontSize: '0.875rem' }}>{L.owuSection}</Text>}
              style={{ marginTop: '0.5rem' }}
              styles={{ header: { background: 'var(--wh-page-bg)' }, body: { background: WH.bg } }}
            >
              <Row gutter={[16, 12]}>
                <Col xs={24} md={12}>
                  <div style={{ marginBottom: '0.25rem' }}>
                    <Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{L.owuModel}</Text>
                    <Input
                      value={owuModel}
                      onChange={(e) => setOwuModel(e.target.value)}
                      placeholder="agnes-2.5-flash"
                      style={{ marginTop: '0.25rem', ...inputStyle }}
                    />
                    <Text style={{ color: WH.textDim, fontSize: '0.6875rem' }}>{L.owuModelHint}</Text>
                  </div>
                  <div>
                    <Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{L.owuEmail}</Text>
                    <Input
                      value={owuEmail}
                      onChange={(e) => setOwuEmail(e.target.value)}
                      placeholder="admin@example.com"
                      style={{ marginTop: '0.25rem', ...inputStyle }}
                    />
                  </div>
                </Col>
                <Col xs={24} md={12}>
                  <div style={{ marginBottom: '0.25rem' }}>
                    <Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{L.owuBaseUrl}</Text>
                    <Input
                      value={owuBaseUrl}
                      onChange={(e) => setOwuBaseUrl(e.target.value)}
                      placeholder="http://192.168.100.27:3000"
                      style={{ marginTop: '0.25rem', ...inputStyle }}
                    />
                    <Text style={{ color: WH.textDim, fontSize: '0.6875rem' }}>{L.owuBaseUrlHint}</Text>
                  </div>
                  <div>
                    <Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{L.owuPassword}</Text>
                    <Input.Password
                      value={owuPassword}
                      onChange={(e) => setOwuPassword(e.target.value)}
                      placeholder="••••••••"
                      style={{ marginTop: '0.25rem', ...inputStyle }}
                    />
                  </div>
                </Col>
              </Row>
            </Card>
          )}

          <div style={{ marginTop: '0.875rem' }}>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={saveConfig}
              style={{ background: WH.teal, borderColor: WH.teal }}
            >
              {L.save}
            </Button>
          </div>

          {/* ── 模型对比测试 ── */}
          <Divider style={{ margin: '1.5rem 0 0.75rem', borderColor: 'rgba(0,217,255,0.15)' }}>
            <Text style={{ color: WH.teal, fontSize: '0.875rem', fontWeight: 600 }}>
              {L.compareTitle}
            </Text>
          </Divider>
          <Text style={{ color: WH.textMuted, fontSize: '0.8125rem' }}>
            {L.compareHint}
          </Text>

          <Card
            size="small"
            style={{ marginTop: '0.625rem' }}
            styles={{ header: { background: 'var(--wh-page-bg)' }, body: { background: WH.bg } }}
          >
            <Space direction="vertical" style={{ width: '100%' }} size="small">
              <div>
                <Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{L.comparePrompt}</Text>
                <TextArea
                  value={comparePrompt}
                  onChange={e => setComparePrompt(e.target.value)}
                  placeholder={L.comparePromptPlaceholder}
                  rows={3}
                  style={{ marginTop: '0.25rem', ...inputStyle }}
                />
              </div>

              <div>
                <Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{L.compareSystem}</Text>
                <Input
                  value={compareSystem}
                  onChange={e => setCompareSystem(e.target.value)}
                  placeholder={L.compareSystemPlaceholder}
                  style={{ marginTop: '0.25rem', ...inputStyle }}
                />
              </div>

              {/* 模型列表 */}
              <div>
                <Space style={{ marginBottom: '0.375rem' }}>
                  <Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{L.compareModels}</Text>
                  <Button
                    size="small"
                    icon={<PlusOutlined />}
                    onClick={addCompareModel}
                    style={{ color: WH.teal, borderColor: WH.teal }}
                  >
                    {L.addModel}
                  </Button>
                </Space>
                {compareModels.map((m, idx) => (
                  <Row key={idx} gutter={[8, 8]} align="middle" style={{ marginBottom: '0.25rem' }}>
                    <Col xs={24} sm={8}>
                      <Select
                        value={m.provider}
                        onChange={v => updateCompareModel(idx, 'provider', v)}
                        options={[
                          { value: 'workbuddy', label: L.providerWorkbuddy },
                          { value: 'openwebui', label: L.providerOpenwebui },
                        ]}
                        style={{ width: '100%' }}
                      />
                    </Col>
                    <Col xs={20} sm={14}>
                      <Input
                        value={m.model}
                        onChange={e => updateCompareModel(idx, 'model', e.target.value)}
                        placeholder="deepseek-v4.1-flash / agnes-2.5-flash"
                        style={inputStyle}
                      />
                    </Col>
                    <Col xs={4} sm={2}>
                      <Button
                        size="small"
                        danger
                        icon={<DeleteOutlined />}
                        onClick={() => removeCompareModel(idx)}
                      />
                    </Col>
                  </Row>
                ))}
              </div>

              <Button
                type="primary"
                icon={compareRunning ? <LoadingOutlined /> : undefined}
                loading={compareRunning}
                onClick={runCompare}
                style={{ background: WH.teal, borderColor: WH.teal, alignSelf: 'flex-start' }}
              >
                {compareRunning ? L.comparing : L.runCompare}
              </Button>
            </Space>
          </Card>

          {/* 对比结果 */}
          {compareResults.length > 0 && (
            <div style={{ marginTop: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {compareResults.map((r, idx) => (
                <Card
                  key={idx}
                  size="small"
                  style={{
                    border: r.ok
                      ? '1px solid rgba(0,217,255,0.25)'
                      : '1px solid rgba(255,80,80,0.3)',
                    background: r.ok
                      ? 'rgba(0,217,255,0.05)'
                      : 'rgba(255,80,80,0.05)',
                  }}
                  styles={{ header: { background: 'transparent' }, body: { padding: '0.75rem' } }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.375rem' }}>
                    <Space>
                      {r.ok
                        ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
                        : <span style={{ color: '#ff4d4f', fontSize: '1rem' }}>✕</span>}
                      <Text style={{ color: WH.text, fontSize: '0.8125rem', fontWeight: 600 }}>
                        {L.modelLabel(r.provider, r.model)}
                      </Text>
                      <Text style={{ color: r.ok ? '#52c41a' : '#ff4d4f', fontSize: '0.75rem' }}>
                        {r.ok ? `${L.success} · ${r.elapsed_ms}ms` : `${L.failed} · ${r.elapsed_ms}ms`}
                      </Text>
                    </Space>
                  </div>
                  {r.ok && r.response ? (
                    <Paragraph
                      style={{ color: WH.text, fontSize: '0.8125rem', margin: 0, whiteSpace: 'pre-wrap' }}
                      ellipsis={{ rows: 12, expandable: true, symbol: '展开' }}
                    >
                      {r.response}
                    </Paragraph>
                  ) : r.error ? (
                    <Text style={{ color: '#ff7875', fontSize: '0.75rem' }}>{r.error}</Text>
                  ) : null}
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
