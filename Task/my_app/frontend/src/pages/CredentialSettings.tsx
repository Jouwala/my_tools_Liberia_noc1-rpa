import { useEffect, useState } from 'react'
import { Card, Input, Button, Tag, message, Spin, Row, Col, Space, Typography } from 'antd'
import { SaveOutlined, ApiOutlined, KeyOutlined, ReloadOutlined } from '@ant-design/icons'
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

  const inputStyle: React.CSSProperties = {
    background: 'rgba(10,25,41,0.6)',
    borderColor: 'rgba(100,255,218,0.25)',
    color: WH.text,
  }

  return (
    <div style={{ padding: '8px 4px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <Typography.Title level={4} style={{ color: WH.text, margin: 0 }}>
            <KeyOutlined style={{ color: WH.teal, marginRight: 8 }} />
            {t('settings.title')}
          </Typography.Title>
          <div style={{ color: WH.textMuted, fontSize: 12, marginTop: 4 }}>{t('settings.subtitle')}</div>
        </div>
        <Button icon={<ReloadOutlined />} onClick={load}>{t('settings.refresh')}</Button>
      </div>

      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
          <Spin size="large" />
        </div>
      ) : (
        <Row gutter={[16, 16]}>
          {groups.map(g => {
            const draft = drafts[g.key] || { username: '', secret: '' }
            return (
              <Col xs={24} md={12} key={g.key}>
                <Card
                  size="small"
                  style={cardStyle}
                  title={
                    <span style={{ color: WH.text }}>
                      {g.name}
                      <span style={{ marginLeft: 8 }}>{sourceTag(g.source)}</span>
                    </span>
                  }
                  extra={
                    g.updated_at ? (
                      <span style={{ color: WH.textDim, fontSize: 12 }}>
                        {t('settings.updatedAt')}: {g.updated_at}
                      </span>
                    ) : null
                  }
                >
                  <Space direction="vertical" style={{ width: '100%' }} size={10}>
                    {g.has_username && (
                      <div>
                        <div style={{ color: WH.textMuted, fontSize: 12, marginBottom: 4 }}>{g.username_label}</div>
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
                      <div style={{ color: WH.textMuted, fontSize: 12, marginBottom: 4 }}>
                        {g.secret_label}
                        {g.secret_masked && (
                          <span style={{ marginLeft: 8, color: WH.textDim }}>
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
                    </Space>
                  </Space>
                </Card>
              </Col>
            )
          })}
        </Row>
      )}
    </div>
  )
}
