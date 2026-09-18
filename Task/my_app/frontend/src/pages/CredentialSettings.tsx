import { useEffect, useState } from 'react'
import { Card, Input, Button, Tag, message, Spin, Row, Col, Space, Typography, Modal, Tooltip } from 'antd'
import { SaveOutlined, ApiOutlined, KeyOutlined, ReloadOutlined, EyeOutlined, InfoCircleOutlined, SearchOutlined } from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'
import { WH, cardStyle } from '../theme'

interface CredentialGroup {
  key: string
  name: string
  username: string
  secret_masked: string
  source: 'db' | 'default' | 'env'
  updated_at: string | null
  usage: string
  username_label: string
  secret_label: string
  has_username: boolean
  testable: boolean
}

export default function CredentialSettings() {
  const { t } = useI18n()
  const [loading, setLoading] = useState(true)
  const [groups, setGroups] = useState<CredentialGroup[]>([])
  // 每个 key 的表单草稿：{ username, secret }
  const [drafts, setDrafts] = useState<Record<string, { username: string; secret: string }>>({})
  const [savingKey, setSavingKey] = useState<string | null>(null)
  const [testingKey, setTestingKey] = useState<string | null>(null)
  const [revealData, setRevealData] = useState<{ name: string; username: string; secret: string } | null>(null)
  const [query, setQuery] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const res = await api.get('/credentials')
      const list: CredentialGroup[] = res.data.credentials || []
      setGroups(list)
      const next: Record<string, { username: string; secret: string }> = {}
      for (const g of list) {
        next[g.key] = { username: g.username || '', secret: '' }
      }
      setDrafts(next)
    } catch (e: any) {
      message.error(t('settings.loadError') + ': ' + (e?.message || e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const sourceTag = (source: string) => {
    if (source === 'db') return <Tag color="green">{t('settings.sourceDb')}</Tag>
    if (source === 'env') return <Tag color="purple">{t('settings.sourceEnv')}</Tag>
    return <Tag>{t('settings.sourceDefault')}</Tag>
  }

  const fuzzyMatch = (g: CredentialGroup, q: string) => {
    if (!q) return true
    const needle = q.trim().toLowerCase()
    if (!needle) return true
    const hay = [g.key, g.name, g.username, g.usage, g.username_label, g.secret_label]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return hay.includes(needle)
  }

  const filtered = groups.filter(g => fuzzyMatch(g, query))

  const save = async (g: CredentialGroup) => {
    const draft = drafts[g.key] || { username: '', secret: '' }
    if (!draft.username && !draft.secret) {
      message.warning(t('settings.nothingToSave'))
      return
    }
    setSavingKey(g.key)
    try {
      const res = await api.put('/credentials', {
        key: g.key,
        username: draft.username || null,
        secret: draft.secret || null,
      })
      message.success(res.data?.message || t('settings.saved'))
      await load()
    } catch (e: any) {
      message.error(t('settings.saveFailed') + ': ' + (e?.response?.data?.detail || e?.message || e))
    } finally {
      setSavingKey(null)
    }
  }

  const test = async (g: CredentialGroup) => {
    setTestingKey(g.key)
    try {
      const res = await api.post('/credentials/test', { key: g.key })
      const d = res.data || {}
      if (d.status === 'ok') {
        message.success(`${t('settings.testOk')} (${d.elapsed}s)`)
      } else if (d.status === 'unsupported') {
        message.info(d.message)
      } else {
        message.error(d.message || t('settings.testFail'))
      }
    } catch (e: any) {
      message.error(t('settings.testFail') + ': ' + (e?.response?.data?.detail || e?.message || e))
    } finally {
      setTestingKey(null)
    }
  }

  const reveal = async (g: CredentialGroup) => {
    try {
      const res = await api.get(`/credentials/${g.key}/reveal`)
      setRevealData({
        name: g.name,
        username: res.data?.username || '',
        secret: res.data?.secret || '',
      })
    } catch (e: any) {
      message.error(t('settings.loadError') + ': ' + (e?.response?.data?.detail || e?.message || e))
    }
  }

  const inputStyle: React.CSSProperties = {
    background: 'rgba(8, 18, 44,0.6)',
    borderColor: 'rgba(0, 217, 255,0.25)',
    color: WH.text,
  }

  return (
    <div style={{ padding: 'var(--wh-space-sm) var(--wh-space-xs)' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--wh-space-sm)', marginBottom: '0.75rem' }}>
        <div>
          <Typography.Title level={4} style={{ color: WH.text, margin: 0 }}>
            <KeyOutlined style={{ color: WH.teal, marginRight: 'var(--wh-space-sm)' }} />
            {t('settings.title')}
          </Typography.Title>
          <div style={{ color: WH.textMuted, fontSize: '0.75rem', marginTop: 'var(--wh-space-xs)' }}>{t('settings.subtitle')}</div>
        </div>
        <Button icon={<ReloadOutlined />} onClick={load}>{t('settings.refresh')}</Button>
      </div>

      {!loading && (
        <Input
          allowClear
          prefix={<SearchOutlined style={{ color: WH.textDim }} />}
          placeholder={t('settings.searchPlaceholder')}
          value={query}
          onChange={e => setQuery(e.target.value)}
          style={{ marginBottom: '0.75rem', background: WH.cardBg, borderColor: WH.teal, color: WH.text }}
        />
      )}

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '5rem' }}>
          <Spin size="large" />
        </div>
      ) : filtered.length === 0 ? (
        <div style={{ textAlign: 'center', color: WH.textMuted, padding: '3.75rem' }}>{t('settings.noMatch')}</div>
      ) : (
        <Row gutter={[16, 16]}>
          {filtered.map(g => {
            const draft = drafts[g.key] || { username: '', secret: '' }
            return (
              <Col xs={24} md={12} key={g.key}>
                <Card
                  size="small"
                  style={cardStyle}
                  title={
                    <span style={{ color: WH.text, display: 'inline-flex', flexWrap: 'wrap', alignItems: 'center', gap: 'var(--wh-space-sm)' }}>
                      {g.name}
                      <span style={{ marginLeft: 'var(--wh-space-sm)' }}>{sourceTag(g.source)}</span>
                      {g.usage && (
                        <Tooltip title={g.usage}>
                          <InfoCircleOutlined style={{ color: WH.textDim, cursor: 'help' }} />
                        </Tooltip>
                      )}
                    </span>
                  }
                  extra={
                    g.updated_at ? (
                      <span style={{ color: WH.textDim, fontSize: '0.75rem' }}>
                        {t('settings.updatedAt')}: {g.updated_at}
                      </span>
                    ) : null
                  }
                >
                  <Space direction="vertical" style={{ width: '100%', gap: '0.625rem' }}>
                    {g.has_username && (
                      <div>
                        <div style={{ color: WH.textMuted, fontSize: '0.75rem', marginBottom: 'var(--wh-space-xs)' }}>{g.username_label}</div>
                        <Input
                          style={inputStyle}
                          value={draft.username}
                          onChange={e =>
                            setDrafts(prev => ({ ...prev, [g.key]: { ...prev[g.key], username: e.target.value } }))
                          }
                          placeholder={g.username_label}
                          autoComplete="off"
                        />
                      </div>
                    )}
                    <div>
                      <div style={{ color: WH.textMuted, fontSize: '0.75rem', marginBottom: 'var(--wh-space-xs)' }}>
                        {g.secret_label}
                        {g.secret_masked && (
                          <span style={{ marginLeft: 'var(--wh-space-sm)', color: WH.textDim }}>
                            ({t('settings.current')}: {g.secret_masked})
                          </span>
                        )}
                      </div>
                      <Input.Password
                        style={inputStyle}
                        value={draft.secret}
                        onChange={e =>
                          setDrafts(prev => ({ ...prev, [g.key]: { ...prev[g.key], secret: e.target.value } }))
                        }
                        placeholder={t('settings.secretPlaceholder')}
                        autoComplete="new-password"
                      />
                    </div>
                    <Space>
                      <Button
                        type="primary"
                        icon={<SaveOutlined />}
                        loading={savingKey === g.key}
                        onClick={() => save(g)}
                      >
                        {t('settings.save')}
                      </Button>
                      {g.testable && (
                        <Button
                          icon={<ApiOutlined />}
                          loading={testingKey === g.key}
                          onClick={() => test(g)}
                        >
                          {t('settings.test')}
                        </Button>
                      )}
                      <Button icon={<EyeOutlined />} onClick={() => reveal(g)}>
                        {t('settings.reveal')}
                      </Button>
                    </Space>
                  </Space>
                </Card>
              </Col>
            )
          })}
        </Row>
      )}

      <Modal
        title={`${t('settings.reveal')} - ${revealData?.name || ''}`}
        open={!!revealData}
        onCancel={() => setRevealData(null)}
        footer={null}
      >
        {revealData && (
          <Space direction="vertical" style={{ width: '100%', gap: 'var(--wh-space-sm)' }}>
            <div>
              <div style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{t('settings.revealUser')}</div>
              <Input value={revealData.username} readOnly onFocus={e => e.target.select()} />
            </div>
            <div>
              <div style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{t('settings.revealSecret')}</div>
              <Input.Password value={revealData.secret} readOnly visibilityToggle onFocus={e => e.target.select()} />
            </div>
          </Space>
        )}
      </Modal>
    </div>
  )
}
