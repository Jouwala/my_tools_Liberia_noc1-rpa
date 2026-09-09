import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Card, Tag, Spin, message, Tooltip, Segmented } from 'antd'
import { LogoutOutlined, LoginOutlined, DesktopOutlined, GlobalOutlined } from '@ant-design/icons'
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
  // 客户端本机登录（nginx 反代）：null = 未配置；"" = 按门户原生根路径反代
  proxy_prefix?: string | null
  login_uri?: string
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
  // client = 在访问者自己的浏览器里登录（经 nginx 反代 + 注入脚本自动填表）
  // server = 老行为：在 my_app 服务器桌面弹浏览器登录
  const [mode, setMode] = useState<'client' | 'server'>('client')
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

  // 客户端本机登录：在访问者自己的浏览器中打开门户。
  // eFlow 不走 my_app 反代，必须直连原始地址；其他 UME 使用独立反代端口。
  const handleClientLogin = useCallback((p: Portal) => {
    const base = p.key === 'eflow'
      ? `https://${p.host}:${p.port}`
      : (p.proxy_prefix || '').replace('{HOST}', window.location.hostname)
    if (p.key !== 'eflow' && p.proxy_prefix == null) {
      showMsg('info', t('portal.noClient'))
      return
    }
    const url = `${base}${p.login_uri || ''}`
    // UME OAuth2 门户会拒绝从 /myapp/ 带来的 Origin/Referer（3329008）。
    // eFlow 直连原始地址，也必须用 noreferrer；它不走 nginx 代理。
    const noReferrerPortals = new Set(['zte_ume', 'ccn_ume', 'ipran_ume', 'mw_ume', 'eflow'])
    const features = noReferrerPortals.has(p.key) ? 'noopener,noreferrer' : 'noopener=no'
    const win = window.open(url, '_blank', features)
    if (!win) {
      showMsg('error', t('portal.loadError'))
      return
    }
    showMsg('info', t('portal.clientOpened'))
    setStatus((prev) => ({ ...prev, [p.key]: { state: 'success', message: '' } }))
  }, [showMsg, t])

  const handleLogin = useCallback(async (system: string, p?: Portal) => {
    if (mode === 'client' && p && (p.key === 'eflow' || p.proxy_prefix != null)) {
      handleClientLogin(p)
      return
    }
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
        <div style={{ color: 'var(--wh-text-secondary, #64748b)', fontSize: 13, marginBottom: 10 }}>
          {t('portal.subtitle')}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, color: 'var(--wh-text-secondary, #64748b)' }}>
            {t('portal.mode')}:
          </span>
          <Segmented
            value={mode}
            onChange={(v) => setMode(v as 'client' | 'server')}
            options={[
              { value: 'client', icon: <GlobalOutlined />, label: t('portal.modeClient') },
              { value: 'server', icon: <DesktopOutlined />, label: t('portal.modeServer') },
            ]}
          />
          <span style={{ fontSize: 12, color: '#94a3b8' }}>
            {mode === 'client' ? t('portal.modeClientTip') : t('portal.modeServerTip')}
          </span>
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
                      onClick={() => handleLogin(p.key, p)}
                      disabled={st === 'launching' || (mode === 'client' && p.proxy_prefix == null)}
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
                <div style={{ marginBottom: 8 }}>
                  {p.proxy_prefix == null ? (
                    <Tooltip title={t('portal.noClient')}>
                      <Tag color="default">{t('portal.notProxied')}</Tag>
                    </Tooltip>
                  ) : (
                    <Tag color="blue">{t('portal.modeClient')}</Tag>
                  )}
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
