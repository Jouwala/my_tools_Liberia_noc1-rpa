import { useState, useEffect } from 'react'
import { Card, Button, Tag, Space, List, Spin, message } from 'antd'
import {
  CloudServerOutlined,
  FolderOutlined,
  ClockCircleOutlined,
  ThunderboltOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  FileTextOutlined,
  CodeOutlined,
} from '@ant-design/icons'
import api from '../api'
import { useI18n } from '../i18n'

interface SyncHistoryItem {
  timestamp: string
  success: boolean
  downloaded: number
  db_updated: boolean
  elapsed: number
  error?: string
}

export default function DataSync() {
  const { t } = useI18n()
  const [syncing, setSyncing] = useState(false)
  const [lastSync, setLastSync] = useState<string | null>(null)
  const [history, setHistory] = useState<SyncHistoryItem[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    loadStatus()
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

  const handleSync = async () => {
    setSyncing(true)
    try {
      const res = await api.post('/ftp/sync')
      if (res.data.success) {
        message.success(t('sync.syncSuccess'))
      } else {
        message.error(t('sync.syncFailed'))
      }
      loadStatus()
    } catch {
      message.error(t('sync.syncFailed'))
    } finally {
      setSyncing(false)
    }
  }

  const formatTime = (isoStr: string | null) => {
    if (!isoStr) return null
    return isoStr.replace('T', ' ').substring(0, 19)
  }

  const ftpConfig = [
    { label: t('sync.serverAddress'), value: '192.168.100.19' },
    { label: t('sync.port'), value: '21' },
    { label: t('sync.username'), value: 'FINEBI' },
    { label: t('sync.remotePath'), value: '/webroot/WEB-INF/reportlets/excel' },
  ]

  const scanFolders = [
    '/webroot/WEB-INF/reportlets/excel/Eflow_TT_FB',
    '/webroot/WEB-INF/reportlets/excel/Eflow_WO_FB',
  ]

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
        {/* Left column */}
        <div style={{ flex: 1, minWidth: 400 }}>
          {/* FTP Config */}
          <Card
            title={
              <span>
                <CloudServerOutlined style={{ marginRight: 8 }} />
                {t('sync.ftpConfig')}
              </span>
            }
            size="small"
            style={{ marginBottom: 16 }}
          >
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              {ftpConfig.map(item => (
                <div key={item.label}>
                  <div style={{ color: '#888', fontSize: 12, marginBottom: 4 }}>{item.label}</div>
                  <div style={{ fontSize: 16, fontWeight: 500 }}>{item.value}</div>
                </div>
              ))}
            </div>
          </Card>

          {/* Scan Folders */}
          <Card
            title={
              <span>
                <FolderOutlined style={{ marginRight: 8 }} />
                {t('sync.scanFolders')}
              </span>
            }
            size="small"
            style={{ marginBottom: 16 }}
          >
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {scanFolders.map(f => (
                <li key={f}>
                  <code style={{ color: '#52c41a', background: 'transparent' }}>{f}</code>
                </li>
              ))}
            </ul>
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
            <p style={{ color: '#888', fontSize: 13, margin: '8px 0' }}>
              <em>
                {t('sync.scheduleNote')}{' '}
                <code>{t('sync.scheduleNoteFile')}</code>{' '}
                {t('sync.scheduleNoteEnable')}
              </em>
            </p>
            <div
              style={{
                background: '#1e1e2e',
                borderRadius: 8,
                padding: '12px 16px',
                fontFamily: 'monospace',
                fontSize: 13,
                color: '#cdd6f4',
              }}
            >
              <div>
                <span style={{ color: '#89b4fa' }}>python sync_scheduler.py</span>
                <span style={{ color: '#6c7086', marginLeft: 16 }}># {t('sync.cmdStart')}</span>
              </div>
              <div>
                <span style={{ color: '#89b4fa' }}>python sync_scheduler.py</span>
                <span style={{ color: '#a6e3a1' }}> --once</span>
                <span style={{ color: '#6c7086', marginLeft: 16 }}># {t('sync.cmdOnce')}</span>
              </div>
            </div>
          </Card>
        </div>

        {/* Right column */}
        <div style={{ flex: 1, minWidth: 400 }}>
          {/* Sync Action */}
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
                <Tag color="green">
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
              <List
                dataSource={[...history].reverse()}
                renderItem={(item: SyncHistoryItem) => (
                  <List.Item
                    style={{
                      background: item.success ? 'rgba(82, 196, 26, 0.05)' : 'rgba(255, 77, 79, 0.05)',
                      borderRadius: 8,
                      padding: '12px 16px',
                      marginBottom: 8,
                      border: `1px solid ${item.success ? 'rgba(82, 196, 26, 0.2)' : 'rgba(255, 77, 79, 0.2)'}`,
                    }}
                  >
                    <List.Item.Meta
                      avatar={
                        item.success ? (
                          <CheckCircleFilled style={{ color: '#52c41a', fontSize: 18 }} />
                        ) : (
                          <CloseCircleFilled style={{ color: '#ff4d4f', fontSize: 18 }} />
                        )
                      }
                      title={
                        <span style={{ color: item.success ? '#52c41a' : '#ff4d4f', fontWeight: 600 }}>
                          {formatTime(item.timestamp)}
                        </span>
                      }
                      description={
                        <Space size="small">
                          <Tag color={item.success ? 'green' : 'red'}>
                            {item.success ? t('sync.success') : t('sync.failed')}
                          </Tag>
                          <span style={{ color: '#888', fontSize: 12 }}>
                            {t('sync.downloaded')}: {item.downloaded}
                          </span>
                          {item.db_updated && (
                            <span style={{ color: '#888', fontSize: 12 }}>
                              · {t('sync.dbUpdated')}
                            </span>
                          )}
                          <span style={{ color: '#888', fontSize: 12 }}>
                            · ⏱ {(item.elapsed ?? 0).toFixed(2)}s
                          </span>
                        </Space>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
