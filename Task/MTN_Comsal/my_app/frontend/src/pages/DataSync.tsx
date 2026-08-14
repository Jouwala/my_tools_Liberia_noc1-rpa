import { useState, useEffect } from 'react'
import { Card, Button, Tag, Space, Spin, message, Input, InputNumber, Form, Select } from 'antd'
import {
  CloudServerOutlined,
  ClockCircleOutlined,
  ThunderboltOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  FileTextOutlined,
  SaveOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'

interface SyncHistoryItem {
  timestamp: string
  success: boolean
  downloaded: number
  db_updated: boolean
  elapsed: number
  errors?: string[]
}

interface SyncConfig {
  server: string
  port: number
  username: string
  password: string
  password_masked?: string
  has_password?: boolean
  protocol: string
  tt_remote_dir: string
  site_list_remote_dir: string
  site_list_filename: string
}

export default function DataSync() {
  const { t } = useI18n()
  const [syncing, setSyncing] = useState(false)
  const [lastSync, setLastSync] = useState<string | null>(null)
  const [history, setHistory] = useState<SyncHistoryItem[]>([])
  const [loading, setLoading] = useState(false)
  const [config, setConfig] = useState<SyncConfig | null>(null)
  const [configLoading, setConfigLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()

  useEffect(() => {
    loadStatus()
    loadConfig()
  }, [])

  const loadStatus = () => {
    setLoading(true)
    api.get('/ftp/status')
      .then(res => {
        const hist = res.data.history || []
        setHistory(hist)
        const last = [...hist].reverse().find((h: SyncHistoryItem) => h.success)
        setLastSync(last?.timestamp || null)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  const loadConfig = () => {
    setConfigLoading(true)
    api.get('/ftp/config')
      .then(res => {
        setConfig(res.data)
        form.setFieldsValue({
          server: res.data.server,
          port: res.data.port,
          username: res.data.username,
          password: '',
          protocol: res.data.protocol || 'sftp',
          tt_remote_dir: res.data.tt_remote_dir,
          site_list_remote_dir: res.data.site_list_remote_dir,
          site_list_filename: res.data.site_list_filename,
        })
      })
      .catch(() => {})
      .finally(() => setConfigLoading(false))
  }

  const handleSaveConfig = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const params: Record<string, any> = {
        server: values.server,
        port: values.port,
        username: values.username,
        protocol: values.protocol,
        tt_remote_dir: values.tt_remote_dir,
        site_list_remote_dir: values.site_list_remote_dir,
        site_list_filename: values.site_list_filename,
      }
      if (values.password) {
        params.password = values.password
      }
      const searchParams = new URLSearchParams()
      Object.entries(params).forEach(([k, v]) => searchParams.append(k, String(v)))
      const res = await api.post(`/ftp/config?${searchParams.toString()}`)
      if (res.data.success) {
        message.success('Configuration saved')
        setConfig(res.data.config)
        form.setFieldsValue({ password: '' })
      } else {
        message.error(res.data.error || 'Save failed')
      }
    } catch {
      message.error('Save failed')
    } finally {
      setSaving(false)
    }
  }

  const handleSync = async () => {
    setSyncing(true)
    try {
      const res = await api.post('/ftp/sync')
      if (res.data.success) {
        message.success(`Sync complete: ${res.data.downloaded} file(s) downloaded`)
      } else {
        const errs = res.data.errors?.join('; ') || 'Unknown error'
        message.error(`Sync failed: ${errs}`)
      }
      loadStatus()
    } catch {
      message.error('Sync failed')
    } finally {
      setSyncing(false)
    }
  }

  const formatTime = (isoStr: string | null) => {
    if (!isoStr) return null
    return isoStr.replace('T', ' ').substring(0, 19)
  }

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontSize: 24, fontWeight: 600 }}>
          <ThunderboltOutlined style={{ marginRight: 8, color: '#1677ff' }} />
          {t('sync.title')}
        </h2>
        <p style={{ color: '#888', margin: '8px 0 0', fontSize: 14 }}>
          {t('sync.subtitle')}
        </p>
      </div>

      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
        {/* Left column - Config */}
        <div style={{ flex: 1, minWidth: 400 }}>
          <Card
            title={
              <span>
                <CloudServerOutlined style={{ marginRight: 8 }} />
                Sync Configuration
              </span>
            }
            size="small"
            style={{ marginBottom: 16 }}
            extra={
              <Space>
                <Button size="small" icon={<ReloadOutlined />} onClick={loadConfig}>
                  Reload
                </Button>
                <Button
                  size="small"
                  type="primary"
                  icon={<SaveOutlined />}
                  loading={saving}
                  onClick={handleSaveConfig}
                >
                  Save
                </Button>
              </Space>
            }
          >
            {configLoading ? (
              <Spin size="small" />
            ) : (
              <Form form={form} layout="vertical" size="small">
                {/* Protocol + Server */}
                <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: 16 }}>
                  <Form.Item label="Protocol" name="protocol">
                    <Select options={[
                      { value: 'sftp', label: 'SFTP' },
                      { value: 'ftp', label: 'FTP' },
                    ]} />
                  </Form.Item>
                  <Form.Item label="Server Address" name="server" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                </div>

                {/* Port + Username */}
                <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: 16 }}>
                  <Form.Item label="Port" name="port" rules={[{ required: true }]}>
                    <InputNumber min={1} max={65535} style={{ width: '100%' }} />
                  </Form.Item>
                  <Form.Item label="Username" name="username" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                </div>

                {/* Password */}
                <Form.Item
                  label="Password"
                  name="password"
                  extra={config?.has_password ? `Current: ${config?.password_masked}` : 'Not set'}
                >
                  <Input.Password placeholder={config?.has_password ? '(unchanged)' : 'Enter password'} />
                </Form.Item>

                {/* TT Remote Dir */}
                <Form.Item label="TT Remote Directory" name="tt_remote_dir" rules={[{ required: true }]}>
                  <Input />
                </Form.Item>

                {/* SiteList Remote Dir + Filename */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 200px', gap: 16 }}>
                  <Form.Item label="SiteList Remote Directory" name="site_list_remote_dir">
                    <Input />
                  </Form.Item>
                  <Form.Item label="SiteList Filename" name="site_list_filename">
                    <Input />
                  </Form.Item>
                </div>
              </Form>
            )}
          </Card>

          {/* Schedule */}
          <Card
            title={
              <span>
                <ClockCircleOutlined style={{ marginRight: 8 }} />
                {t('sync.schedule')}
              </span>
            }
            size="small"
            style={{ marginBottom: 16 }}
          >
            <div style={{ marginBottom: 12 }}>
              <span style={{ fontWeight: 500 }}>{t('sync.schedule')}:</span>{' '}
              <Tag color="green">{t('sync.scheduleDesc')}</Tag>
            </div>
          </Card>
        </div>

        {/* Right column - Sync */}
        <div style={{ flex: 1, minWidth: 400 }}>
          <Card size="small" style={{ marginBottom: 16 }}>
            <Space size="large" align="center" wrap>
              <Button
                type="primary"
                size="large"
                icon={<ThunderboltOutlined />}
                onClick={handleSync}
                loading={syncing}
                style={{ minWidth: 160 }}
              >
                {syncing ? t('sync.syncing') : t('sync.syncNow')}
              </Button>
              <div>
                <span style={{ fontWeight: 500 }}>{t('sync.lastSync')}:</span>{' '}
                <Tag color={lastSync ? 'green' : 'default'}>
                  {lastSync ? formatTime(lastSync) : t('sync.noHistory')}
                </Tag>
              </div>
            </Space>
          </Card>

          {/* Sync Log */}
          <Card
            title={
              <span>
                <FileTextOutlined style={{ marginRight: 8 }} />
                {t('sync.syncLog')}
              </span>
            }
            size="small"
          >
            {loading ? (
              <Spin size="small" />
            ) : history.length === 0 ? (
              <div style={{ textAlign: 'center', color: '#999', padding: 20 }}>
                {t('sync.noHistory')}
              </div>
            ) : (
              <div>
                {[...history].reverse().map((item: SyncHistoryItem, idx: number) => (
                  <div
                    key={idx}
                    style={{
                      background: item.success ? 'rgba(82, 196, 26, 0.05)' : 'rgba(255, 77, 79, 0.05)',
                      borderRadius: 8,
                      padding: '12px 16px',
                      marginBottom: 8,
                      border: `1px solid ${item.success ? 'rgba(82, 196, 26, 0.2)' : 'rgba(255, 77, 79, 0.2)'}`,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      {item.success ? (
                        <CheckCircleFilled style={{ color: '#52c41a', fontSize: 18 }} />
                      ) : (
                        <CloseCircleFilled style={{ color: '#ff4d4f', fontSize: 18 }} />
                      )}
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, color: item.success ? '#52c41a' : '#ff4d4f' }}>
                          {formatTime(item.timestamp)}
                        </div>
                        <Space size="small" style={{ marginTop: 4 }}>
                          <Tag color={item.success ? 'green' : 'red'}>
                            {item.success ? t('sync.success') : t('sync.failed')}
                          </Tag>
                          <span style={{ color: '#888', fontSize: 12 }}>
                            Files: {item.downloaded}
                          </span>
                          {item.db_updated && (
                            <span style={{ color: '#888', fontSize: 12 }}>· DB updated</span>
                          )}
                          <span style={{ color: '#888', fontSize: 12 }}>
                            · ⏱ {(item.elapsed ?? 0).toFixed(2)}s
                          </span>
                        </Space>
                        {item.errors && item.errors.length > 0 && (
                          <div style={{ color: '#ff4d4f', fontSize: 12, marginTop: 4 }}>
                            {item.errors.join('; ')}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
