import { useEffect, useState } from 'react'
import { Card, Input, Button, Tag, message, Spin, Row, Col, Space } from 'antd'
import { SaveOutlined, ReloadOutlined, UndoOutlined, EditOutlined, CloseOutlined, SearchOutlined } from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'
import { WH, cardStyle } from '../theme'

interface RecipientGroup {
  key: string
  name: string
  to_text: string
  cc_text: string
  source: 'db' | 'default'
  updated_at: string | null
}

export default function EmailRecipientsSettings() {
  const { t } = useI18n()
  const [loading, setLoading] = useState(true)
  const [groups, setGroups] = useState<RecipientGroup[]>([])
  // 每个 key 的表单草稿：{ to, cc }
  const [drafts, setDrafts] = useState<Record<string, { to: string; cc: string }>>({})
  const [savingKey, setSavingKey] = useState<string | null>(null)
  const [resettingKey, setResettingKey] = useState<string | null>(null)
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const res = await api.get('/email-recipients')
      const list: RecipientGroup[] = res.data.recipients || []
      setGroups(list)
      const next: Record<string, { to: string; cc: string }> = {}
      for (const g of list) {
        next[g.key] = { to: g.to_text || '', cc: g.cc_text || '' }
      }
      setDrafts(next)
    } catch (e: any) {
      message.error(t('settings.emailLoadError') + ': ' + (e?.message || e))
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
    return <Tag>{t('settings.sourceDefault')}</Tag>
  }

  const fuzzyMatch = (g: RecipientGroup, q: string) => {
    if (!q) return true
    const needle = q.trim().toLowerCase()
    if (!needle) return true
    const hay = [g.key, g.name, g.to_text, g.cc_text, g.source]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return hay.includes(needle)
  }

  const filtered = groups.filter(g => fuzzyMatch(g, query))

  const save = async (g: RecipientGroup) => {
    const draft = drafts[g.key] || { to: '', cc: '' }
    if (!draft.to.trim() && !draft.cc.trim()) {
      message.warning(t('settings.emailNothingToSave'))
      return
    }
    setSavingKey(g.key)
    try {
      const res = await api.put('/email-recipients', {
        key: g.key,
        to: draft.to || null,
        cc: draft.cc || null,
      })
      message.success(res.data?.message || t('settings.saved'))
      await load()
      setEditingKey(null)
    } catch (e: any) {
      message.error(t('settings.emailSaveFailed') + ': ' + (e?.response?.data?.detail || e?.message || e))
    } finally {
      setSavingKey(null)
    }
  }

  const reset = async (g: RecipientGroup) => {
    setResettingKey(g.key)
    try {
      const res = await api.post('/email-recipients/reset', { key: g.key })
      message.success(res.data?.message || t('settings.resetDone'))
      await load()
      setEditingKey(null)
    } catch (e: any) {
      message.error(t('settings.emailSaveFailed') + ': ' + (e?.response?.data?.detail || e?.message || e))
    } finally {
      setResettingKey(null)
    }
  }

  const edit = (g: RecipientGroup) => {
    setDrafts(prev => ({ ...prev, [g.key]: { to: g.to_text || '', cc: g.cc_text || '' } }))
    setEditingKey(g.key)
  }

  const cancel = (g: RecipientGroup) => {
    setDrafts(prev => ({ ...prev, [g.key]: { to: g.to_text || '', cc: g.cc_text || '' } }))
    setEditingKey(null)
  }

  const readonlyStyle: React.CSSProperties = {
    background: 'rgba(255,255,255,0.05)',
    borderColor: 'rgba(255,255,255,0.10)',
    color: WH.textMuted,
    cursor: 'default',
  }

  const editingStyle: React.CSSProperties = {
    background: WH.cardBg,
    borderColor: WH.teal,
    color: WH.text,
  }

  return (
    <div style={{ padding: 'var(--wh-space-sm) var(--wh-space-xs)' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--wh-space-sm)', marginBottom: '0.75rem' }}>
        <div>
          {/* 页面标题由 App 全局 Header（菜单「系统设置」）+ Tab 标签给出，页内不再重复 */}
          <div style={{ color: WH.textMuted, fontSize: '0.75rem' }}>{t('settings.emailSubtitle')}</div>
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
            const draft = drafts[g.key] || { to: '', cc: '' }
            return (
              <Col xs={24} md={12} key={g.key}>
                <Card
                  size="small"
                  style={cardStyle}
                  title={
                    <span style={{ color: WH.text, display: 'inline-flex', flexWrap: 'wrap', alignItems: 'center', gap: 'var(--wh-space-sm)' }}>
                      {g.name}
                      <span style={{ marginLeft: 'var(--wh-space-sm)' }}>{sourceTag(g.source)}</span>
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
                    <div>
                      <div style={{ color: WH.textMuted, fontSize: '0.75rem', marginBottom: 'var(--wh-space-xs)' }}>{t('settings.toLabel')}</div>
                      <Input.TextArea
                        style={editingKey === g.key ? editingStyle : readonlyStyle}
                        rows={4}
                        value={draft.to}
                        readOnly={editingKey !== g.key}
                        onChange={e =>
                          setDrafts(prev => ({ ...prev, [g.key]: { ...prev[g.key], to: e.target.value } }))
                        }
                        placeholder={editingKey === g.key ? t('settings.toLabel') : ''}
                        autoSize={{ minRows: 3, maxRows: 10 }}
                      />
                    </div>
                    <div>
                      <div style={{ color: WH.textMuted, fontSize: '0.75rem', marginBottom: 'var(--wh-space-xs)' }}>{t('settings.ccLabel')}</div>
                      <Input.TextArea
                        style={editingKey === g.key ? editingStyle : readonlyStyle}
                        rows={3}
                        value={draft.cc}
                        readOnly={editingKey !== g.key}
                        onChange={e =>
                          setDrafts(prev => ({ ...prev, [g.key]: { ...prev[g.key], cc: e.target.value } }))
                        }
                        placeholder={editingKey === g.key ? t('settings.ccLabel') : ''}
                        autoSize={{ minRows: 2, maxRows: 8 }}
                      />
                    </div>
                    <Space>
                      {editingKey === g.key ? (
                        <>
                          <Button
                            type="primary"
                            icon={<SaveOutlined />}
                            loading={savingKey === g.key}
                            onClick={() => save(g)}
                          >
                            {t('settings.save')}
                          </Button>
                          <Button
                            icon={<CloseOutlined />}
                            onClick={() => cancel(g)}
                            disabled={savingKey === g.key}
                          >
                            {t('settings.cancel')}
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button
                            icon={<EditOutlined />}
                            onClick={() => edit(g)}
                          >
                            {t('settings.edit')}
                          </Button>
                          {g.source === 'db' && (
                            <Button
                              icon={<UndoOutlined />}
                              loading={resettingKey === g.key}
                              onClick={() => reset(g)}
                            >
                              {t('settings.resetDefault')}
                            </Button>
                          )}
                        </>
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
