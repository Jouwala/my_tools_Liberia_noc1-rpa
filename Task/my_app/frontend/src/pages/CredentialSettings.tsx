import { useEffect, useState } from 'react'
import { Card, Input, Button, Tag, message, Spin, Row, Col, Space, Modal, Tooltip } from 'antd'
import { SaveOutlined, ApiOutlined, ReloadOutlined, EyeOutlined, InfoCircleOutlined, SearchOutlined } from '@ant-design/icons'
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
  // 2026-10-21：后端下发测试方式与测试目标，界面据此提示「点下去会发生什么」
  test_kind?: string
  test_target?: string
  // 2026-10-22：测试目标的地址来源（file:<配置文件名> / env:<变量名> / static）。
  // 后端与任务读同一份配置，这里把「这地址是哪来的」也展示出来，
  // 免得改了 JSON 却不知道界面上的地址有没有跟着变。
  test_target_source?: string
  test_target_conflicts?: { file: string; host: string; port: number | string | null }[]
}

const WEIXIN_TEST_KIND = 'weixin_push'

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

  // 测试目标地址的来源（2026-10-22）。
  // 只在**有外部来源**时给角标：多数组仍是内置默认，全标一遍会把界面糊住；
  // 内置默认的情况放到 Tooltip 里说明就够了。冲突用橙色提醒。
  const targetBadge = (g: CredentialGroup) => {
    const src = g.test_target_source || ''
    let label = ''
    let color = 'blue'
    if (src.startsWith('file:')) label = src.slice('file:'.length)
    else if (src.startsWith('env:')) label = t('settings.sourceEnv')
    else return null
    if ((g.test_target_conflicts?.length || 0) > 0) color = 'orange'
    return (
      <Tag
        color={color}
        style={{ fontSize: '0.68rem', lineHeight: '1.3', margin: 0, padding: '0 4px' }}
      >
        {label}
      </Tag>
    )
  }

  // Tooltip 里的「来源」一行：把 file:/env:/static 翻译成人话
  const targetSourceText = (g: CredentialGroup) => {
    const src = g.test_target_source || ''
    if (src.startsWith('file:')) return t('settings.testTargetFromFile', { file: src.slice('file:'.length) })
    if (src.startsWith('env:')) return t('settings.testTargetFromEnv', { env: src.slice('env:'.length) })
    return t('settings.testTargetDefault')
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
      // 后端消息里带有账号/主机/服务端版本等定位信息，一律回显，不要只显示"成功/失败"。
      if (d.status === 'ok') {
        message.success(`${t('settings.testOk')} (${d.elapsed}s)${d.message ? '：' + d.message : ''}`, 6)
      } else if (d.status === 'locked') {
        message.warning(d.message, 8)
      } else if (d.status === 'unsupported') {
        message.info(d.message)
      } else {
        message.error(d.message || t('settings.testFail'), 8)
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
          {/* 页面标题由 App 全局 Header（菜单「系统设置」）+ Tab 标签给出，页内不再重复 */}
          <div style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{t('settings.subtitle')}</div>
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
                        <Space size={4}>
                          <Tooltip
                            title={
                              g.test_kind === WEIXIN_TEST_KIND
                                ? t('settings.testWeixinWarn')
                                : g.test_target
                                  ? (
                                    <div>
                                      <div>{`${t('settings.testTarget')}: ${g.test_target}`}</div>
                                      <div style={{ opacity: 0.85 }}>{targetSourceText(g)}</div>
                                      {(g.test_target_conflicts?.length || 0) > 0 && (
                                        <div style={{ marginTop: 2 }}>
                                          {t('settings.testTargetConflict', {
                                            files: (g.test_target_conflicts || [])
                                              .map(c => c.file)
                                              .join(', '),
                                          })}
                                        </div>
                                      )}
                                    </div>
                                  )
                                  : t('settings.test')
                            }
                          >
                            <Button
                              icon={<ApiOutlined />}
                              loading={testingKey === g.key}
                              onClick={() => test(g)}
                            >
                              {t('settings.test')}
                            </Button>
                          </Tooltip>
                          {targetBadge(g)}
                        </Space>
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
