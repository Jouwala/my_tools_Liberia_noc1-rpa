import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Card, Tag, Spin, message, Tooltip } from 'antd'
import { LogoutOutlined, LoginOutlined } from '@ant-design/icons'
import { useI18n } from '../i18n'
import api from '../api'

type Portal = {
  key: string
  name: string
  name_en: string
  cred_key: string
  host: string
  port: number
  kind: string
  live: boolean
}

type JobState = 'idle' | 'launching' | 'success' | 'failed' | 'need_manual'
type StatusInfo = { state: JobState; message: string; jobId?: string }

const STATE_COLOR: Record<JobState, string> = {
  idle: 'default',
  launching: 'processing',
  success: 'success',
  failed: 'error',
  need_manual: 'warning',
}

const STATE_TEXT: Record<JobState, string> = {
  idle: '—',
  launching: 'portal.loggingIn',
  success: 'portal.success',
  failed: 'portal.failed',
  need_manual: 'portal.needManual',
}

function mapBackendState(s?: string): JobState {
  switch (s) {
    case 'success': return 'success'
    case 'failed': return 'failed'
    case 'need_manual': return 'need_manual'
    case 'unknown': return 'failed' // 任务丢失/过期：终态，停止轮询并提示
    default: return 'launching'
  }
}

export default function PortalLogin() {
  const { t, locale } = useI18n()
  const [portals, setPortals] = useState<Portal[]>([])
  const [status, setStatus] = useState<Record<string, StatusInfo>>({})
  const [loading, setLoading] = useState(true)
  const timers = useRef<Record<string, number>>({})

  const showMsg = useCallback((type: 'success' | 'error' | 'info', text: string) => {
    message[type](text)
  }, [])

  const fetchPortals = useCallback(async () => {
    try {
      const { data } = await api.get('/portals')
      setPortals(data.portals || [])
    } catch (e) {
      showMsg('error', t('portal.loadError'))
    } finally {
      setLoading(false)
    }
  }, [showMsg, t])

  useEffect(() => {
    fetchPortals()
    return () => {
      Object.values(timers.current).forEach((id) => window.clearInterval(id))
    }
  }, [fetchPortals])

  const pollJob = useCallback((system: string, jobId: string) => {
    if (timers.current[system]) window.clearInterval(timers.current[system])
    const id = window.setInterval(async () => {
      try {
        const { data } = await api.get('/portals/login/status', { params: { job_id: jobId } })
        const st = mapBackendState(data.state)
        setStatus((prev) => ({
          ...prev,
          [system]: { state: st, message: data.message || '', jobId },
        }))
        if (st === 'success' || st === 'failed' || st === 'need_manual') {
          window.clearInterval(id)
          delete timers.current[system]
          fetchPortals()
        }
      } catch {
        window.clearInterval(id)
        delete timers.current[system]
      }
    }, 1500)
    timers.current[system] = id
  }, [fetchPortals])

  const handleLogin = useCallback(async (system: string) => {
    setStatus((prev) => ({ ...prev, [system]: { state: 'launching', message: '' } }))
    try {
      const { data } = await api.post('/portals/login', { system })
      showMsg('info', t('portal.opened'))
      pollJob(system, data.job_id)
    } catch (e: any) {
      showMsg('error', e?.response?.data?.detail || t('portal.loadError'))
      setStatus((prev) => ({ ...prev, [system]: { state: 'failed', message: '' } }))
    }
  }, [pollJob, showMsg, t])

  const handleClose = useCallback(async (system: string) => {
    try {
      await api.post('/portals/close', { system })
      if (timers.current[system]) {
        window.clearInterval(timers.current[system])
        delete timers.current[system]
      }
      showMsg('success', t('portal.closed'))
      fetchPortals()
      setStatus((prev) => ({ ...prev, [system]: { state: 'idle', message: '' } }))
    } catch {
      showMsg('error', t('portal.closeFailed'))
    }
  }, [fetchPortals, showMsg, t])

  return (
    <div style={{ padding: '8px 4px' }}>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ margin: '0 0 4px' }}>{t('portal.title')}</h2>
        <div style={{ color: 'var(--wh-text-secondary, #64748b)', fontSize: 13 }}>
          {t('portal.subtitle')}
        </div>
      </div>

      {loading ? (
        <div style={{ padding: 48, textAlign: 'center' }}><Spin size="large" /></div>
      ) : (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
          {portals.map((p) => {
            const st = status[p.key]?.state || 'idle'
            const stMsg = status[p.key]?.message || ''
            const isLive = p.live || st === 'success' || st === 'need_manual'
            return (
              <Card
                key={p.key}
                style={{ width: 'min(100%, 20rem)' }}
                title={
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span>{locale === 'en' ? p.name_en : p.name}</span>
                    {isLive ? <Tag color="green">Live</Tag> : <Tag>Idle</Tag>}
                  </div>
                }
                actions={[
                  <Tooltip title={t('portal.login')} key="login">
                    <Button
                      type="primary"
                      icon={<LoginOutlined />}
                      loading={st === 'launching'}
                      onClick={() => handleLogin(p.key)}
                      disabled={st === 'launching'}
                    >
                      {t('portal.login')}
                    </Button>
                  </Tooltip>,
                  <Tooltip title={t('portal.close')} key="close">
                    <Button
                      icon={<LogoutOutlined />}
                      onClick={() => handleClose(p.key)}
                      disabled={!isLive}
                    >
                      {t('portal.close')}
                    </Button>
                  </Tooltip>,
                ]}
              >
                <div style={{ fontSize: 13, color: '#64748b', marginBottom: 8 }}>
                  {t('portal.host')}: <code>{p.host}:{p.port}</code>
                </div>
                <Tag color={STATE_COLOR[st]}>{t(STATE_TEXT[st])}</Tag>
                {stMsg && (
                  <div style={{ marginTop: 8, fontSize: 12, color: '#94a3b8', wordBreak: 'break-all' }}>
                    {stMsg}
                  </div>
                )}
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
