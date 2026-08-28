import { useEffect, useState } from 'react'
import { Card, Input, Button, message, Spin, Typography, Alert, Tag, Divider } from 'antd'
import { SaveOutlined, ApiOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'
import { WH, cardStyle } from '../theme'

export default function RemoteHostSettings() {
  const { t } = useI18n()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [host, setHost] = useState('')
  const [current, setCurrent] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const res = await api.get('/settings/remote-host')
      const h = res.data?.remote_host || ''
      setCurrent(h)
      setHost(h)
    } catch (e: any) {
      message.error(t('settings.remoteHostLoadError') + ': ' + (e?.message || e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const save = async () => {
    const v = host.trim()
    if (!v) {
      message.warning(t('settings.remoteHostInvalid'))
      return
    }
    setSaving(true)
    try {
      const res = await api.put('/settings/remote-host', { host: v })
      setCurrent(res.data?.remote_host || v)
      message.success(t('settings.remoteHostSaved'))
      await load()
    } catch (e: any) {
      message.error(
        t('settings.remoteHostSaveFailed') +
          ': ' +
          (e?.response?.data?.detail || e?.message || e),
      )
    } finally {
      setSaving(false)
    }
  }

  const testConnection = async () => {
    const v = host.trim()
    if (!v) {
      message.warning(t('settings.remoteHostInvalid'))
      return
    }
    setTesting(true)
    setResult(null)
    try {
      const res = await api.post('/settings/test-connection', { host: v })
      setResult(res.data)
    } catch (e: any) {
      message.error(
        t('settings.testError') +
          ': ' +
          (e?.response?.data?.detail || e?.message || e),
      )
    } finally {
      setTesting(false)
    }
  }

  const inputStyle: React.CSSProperties = {
    background: WH.cardBg,
    borderColor: WH.teal,
    color: WH.text,
  }

  const renderProbe = (label: string, p: any) => {
    if (!p) return null
    const ok = p.reachable
    const color = ok ? 'green' : 'red'
    return (
      <div
        style={{
          border: `1px solid ${WH.cardBorder}`,
          borderRadius: 'var(--wh-radius-md)',
          padding: '0.625rem 0.75rem',
          background: WH.cardBg,
        }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 'var(--wh-space-sm)', marginBottom: '0.375rem' }}>
          <Tag color={color}>{ok ? t('settings.reachable') : t('settings.notReachable')}</Tag>
          <Typography.Text strong style={{ color: WH.text }}>
            {label} · {p.host}:{p.port}
          </Typography.Text>
          {p.latency_ms != null && (
            <Typography.Text style={{ color: WH.textMuted, fontSize: '0.75rem' }}>
              {p.latency_ms} ms
            </Typography.Text>
          )}
        </div>
        {label === 'FTP' ? (
          <div style={{ fontSize: '0.75rem', color: WH.textMuted, lineHeight: 1.6 }}>
            {p.banner && (
              <div>
                {t('settings.banner')}: <code>{p.banner}</code>
              </div>
            )}
            {ok &&
              (p.authenticated ? (
                <Tag color="green" style={{ marginTop: 'var(--wh-space-xs)' }}>
                  {t('settings.authenticated')}
                </Tag>
              ) : (
                <Tag color="orange" style={{ marginTop: 'var(--wh-space-xs)' }}>
                  {t('settings.authFailed')}
                  {p.auth_error ? `: ${p.auth_error}` : ''}
                </Tag>
              ))}
          </div>
        ) : (
          <div style={{ fontSize: '0.75rem', color: WH.textMuted, lineHeight: 1.6 }}>
            {p.status != null && (
              <div>
                {t('settings.statusCode')}: <code>{p.status}</code>
                {p.path ? ` (${p.path})` : ''}
              </div>
            )}
            {p.body && (
              <div style={{ marginTop: '0.125rem' }}>
                {t('settings.response')}: <code>{p.body}</code>
              </div>
            )}
          </div>
        )}
        {!ok && p.error && (
          <div style={{ fontSize: '0.75rem', color: '#cf1322', marginTop: 'var(--wh-space-xs)' }}>⚠ {p.error}</div>
        )}
      </div>
    )
  }

  return (
    <div style={{ padding: 'var(--wh-space-sm) var(--wh-space-xs)' }}>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 'var(--wh-space-sm)',
          marginBottom: '0.75rem',
        }}
      >
        <div>
          <Typography.Title level={4} style={{ color: WH.text, margin: 0 }}>
            <ApiOutlined style={{ color: WH.teal, marginRight: 'var(--wh-space-sm)' }} />
            {t('settings.remoteHostTitle')}
          </Typography.Title>
          <div style={{ color: WH.textMuted, fontSize: '0.75rem', marginTop: 'var(--wh-space-xs)' }}>
            {t('settings.remoteHostSubtitle')}
          </div>
        </div>
        <Button icon={<ReloadOutlined />} onClick={load}>
          {t('settings.refresh')}
        </Button>
      </div>

      <Card size="small" style={cardStyle}>
        <Spin spinning={loading}>
          <div style={{ marginBottom: '0.75rem', color: WH.textMuted, fontSize: '0.8125rem' }}>
            {t('settings.remoteHostCurrent')}:{' '}
            <code style={{ color: WH.teal }}>{current || '-'}</code>
          </div>
          <div style={{ marginBottom: '0.375rem', color: WH.textMuted, fontSize: '0.75rem' }}>
            {t('settings.remoteHostLabel')}
          </div>
          <Input
            style={inputStyle}
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder={t('settings.remoteHostPlaceholder')}
            allowClear
          />
          <div style={{ marginTop: '0.75rem', display: 'flex', flexWrap: 'wrap', gap: 'var(--wh-space-md)' }}>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={save}
            >
              {t('settings.remoteHostSave')}
            </Button>
            <Button
              icon={<ThunderboltOutlined />}
              loading={testing}
              onClick={testConnection}
            >
              {t('settings.testConnection')}
            </Button>
          </div>
          {result && (
            <div style={{ marginTop: 'var(--wh-space-md)' }}>
              <Divider style={{ margin: 'var(--wh-space-sm) 0', borderColor: WH.cardBorder }} />
              <Typography.Text style={{ color: WH.text, fontWeight: 600 }}>
                {t('settings.testResult')}：{result.host}
              </Typography.Text>
              <div style={{ marginTop: 'var(--wh-space-sm)', display: 'flex', flexDirection: 'column', gap: '0.625rem' }}>
                {renderProbe('FTP', result.ftp)}
                {renderProbe('API', result.api)}
              </div>
            </div>
          )}
          <Alert
            style={{ marginTop: 'var(--wh-space-md)' }}
            type="info"
            showIcon
            message={t('settings.remoteHostNote')}
          />
        </Spin>
      </Card>
    </div>
  )
}
