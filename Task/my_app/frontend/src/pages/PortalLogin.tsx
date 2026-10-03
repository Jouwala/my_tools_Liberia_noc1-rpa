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
  // 后端标记：该门户在客户端模式下必须「直连上游」（不经反代、无自动填表），
  // 因为其前端把根地址/接口地址写死为上游绝对地址，反代到别的 host 会失效。
  direct?: boolean
}

// 直连上游的门户（后端 spec 里 direct=true 优先；此集合是旧后端/兜底）。
// eFlow：前端把根地址写死为 http://localhost，经同源反代后子页面/接口会打到访问者本机
//        → "当前系统异常，稍后重试"、当前告警列与默认模板查询失败。
// RAIS：前端把 API 根地址写死为 https://10.100.20.9:8766/，登录响应要往该域种 cookie，
//        经反代打开时 fetch 不带 credentials，SSO cookie 种不下来。
// Battery UME：与 eFlow 同为 ZTE UAC 系门户，前端同样写死上游绝对地址。
const DIRECT_PORTALS = new Set(['eflow', 'rais', 'battery_ume'])

const isDirect = (p: Portal) => p.direct === true || DIRECT_PORTALS.has(p.key)
// 客户端模式下能否在访问者本机打开：要么配了 nginx 反代（同源 + 注入填表），要么直连上游
const canClientLogin = (p: Portal) => p.proxy_prefix != null || isDirect(p)

// 访问者的浏览器是否就在 my_app 服务器本机（回环地址）。
// 此时「服务器模式」弹出的浏览器窗口正好落在用户自己桌面上，等价于「本机登录」，
// 而直连门户（eFlow/RAIS）恰恰只能靠服务器端直接鉴权登录（见下方 handleLogin 注释）。
const isOnServerHost = () => {
  const h = window.location.hostname.toLowerCase()
  return h === 'localhost' || h === '127.0.0.1' || h === '::1' || h === '[::1]'
}

type JobState = 'idle' | 'launching' | 'success' | 'failed' | 'need_manual'
type StatusInfo = { state: JobState; message: string; jobId?: string }
type ExtensionResult = { system?: string; ok?: boolean; message?: string }

const PORTAL_EXTENSION_READY_ATTR = 'data-myapp-portal-login-extension'
const PORTAL_EXTENSION_REQUEST_EVENT = 'myapp:portal-client-login'
const PORTAL_EXTENSION_RESULT_EVENT = 'myapp:portal-client-login-result'

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
  // 后端判定：访问者浏览器是否就在 my_app 服务器本机（用于直连门户的登录方式选择）
  const [clientIsLocal, setClientIsLocal] = useState(false)
  // 由受管 Chrome 扩展注入的 bridge 标记。未装扩展时仍保留原来的直连手动登录兜底。
  const [portalExtensionReady, setPortalExtensionReady] = useState(() =>
    document.documentElement.getAttribute(PORTAL_EXTENSION_READY_ATTR) === 'ready')
  // client = 在访问者自己的浏览器里登录（经 nginx 反代 + 注入脚本自动填表）
  // server = 在 my_app 服务器桌面弹浏览器登录（eFlow 走直接鉴权 + CDP 种 cookie）
  //
  // 2026-10-02 改：**默认值从 client 改为 server**（用户要求「Portal Login 要默认是
  // server，其实这个只有 server 在用」）。
  //   · 为什么：这个页面实际只有 RDP 到服务器的运维在用，而 eFlow / RAIS 是「直连门户」，
  //     在 client 模式下**根本无法一键登录**（只能打开登录页让人手输，见
  //     portal.clientOpenedDirect 文案）。默认给 client 会让每次进来都先撞一次这个坑，
  //     还得手动切一下 —— 默认值应当贴合绝大多数真实用法。
  //   · 判定改成「只有明确选过 client 才是 client」：null/非法值/隐私模式抛错一律落
  //     server。**已选过 client 的用户不受影响**（他们的 localStorage 里存着 'client'），
  //     所以这不是把老用户的选择覆盖掉，只是改了「没选过」时的初始值。
  const MODE_KEY = 'myapp_portal_login_mode'
  const [mode, setMode] = useState<'client' | 'server'>(() => {
    try {
      return localStorage.getItem(MODE_KEY) === 'client' ? 'client' : 'server'
    } catch {
      return 'server'
    }
  })
  const changeMode = useCallback((v: 'client' | 'server') => {
    setMode(v)
    try {
      localStorage.setItem(MODE_KEY, v)
    } catch {
      /* 隐私模式等场景忽略 */
    }
  }, [])
  const timers = useRef<Record<string, number>>({})

  const showMsg = useCallback((type: 'success' | 'error' | 'info' | 'warning', text: string) => {
    message[type](text)
  }, [])

  const fetchPortals = useCallback(async () => {
    try {
      const { data } = await api.get('/portals')
      setPortals(data.portals || [])
      // 后端按访问者 IP 判定：浏览器是否就在 my_app 服务器本机
      setClientIsLocal(!!data.client_is_local)
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

  useEffect(() => {
    const onExtensionResult = (event: Event) => {
      let result: ExtensionResult | null = null
      try {
        const raw = (event as CustomEvent<string>).detail
        result = typeof raw === 'string' ? JSON.parse(raw) : null
      } catch {
        return
      }
      if (!result?.system || !isDirect({ key: result.system } as Portal)) return
      setStatus((prev) => ({
        ...prev,
        [result.system!]: result!.ok
          ? { state: 'success', message: result!.message || '' }
          : { state: 'failed', message: result!.message || t('portal.loadError') },
      }))
      if (result.ok) showMsg('success', result.message || t('portal.success'))
      else showMsg('error', result.message || t('portal.loadError'))
    }
    window.addEventListener(PORTAL_EXTENSION_RESULT_EVENT, onExtensionResult)
    return () => window.removeEventListener(PORTAL_EXTENSION_RESULT_EVENT, onExtensionResult)
  }, [showMsg, t])

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
  // 非直连门户经 nginx 反代（同源），登录页会被注入 /api/portals/inject.js 自动填表；
  // 直连门户（后端 direct=true / DIRECT_PORTALS）直接打开上游地址，需手动登录。
  const handleClientLogin = useCallback((p: Portal) => {
    const direct = isDirect(p)
    if (!direct && p.proxy_prefix == null) {
      showMsg('info', t('portal.noClient'))
      return
    }
    // eFlow / RAIS 直连时，由受管扩展在用户自己的 Chrome profile 内种会话 Cookie。
    // 页面只传一次性票据；账号密码和 Cookie 从不放进 DOM 或 URL。
    if (direct && portalExtensionReady) {
      setStatus((prev) => ({ ...prev, [p.key]: { state: 'launching', message: '' } }))
      void api.post('/portals/client-login/ticket', { system: p.key })
        .then(({ data }) => {
          window.dispatchEvent(new CustomEvent(PORTAL_EXTENSION_REQUEST_EVENT, {
            detail: JSON.stringify({
              system: p.key,
              ticket: data.ticket,
              // 扩展必须只向安装时声明的 my_app origin 请求，不接收任意外部地址。
              apiOrigin: window.location.origin,
            }),
          }))
        })
        .catch((e: any) => {
          showMsg('error', e?.response?.data?.detail || t('portal.loadError'))
          setStatus((prev) => ({ ...prev, [p.key]: { state: 'failed', message: '' } }))
        })
      return
    }
    const base = direct
      ? `https://${p.host}:${p.port}`
      : (p.proxy_prefix || '').replace('{HOST}', window.location.hostname)
    const url = `${base}${p.login_uri || ''}`
    // UME 系门户（反代到 808x）历史上出现过 3329008 跨站拒绝，保留 noreferrer 兜底；
    // eFlow 直连上游，同样用 noreferrer 避免门户跨站校验。
    // 注意：noopener / noreferrer 会让 window.open 恒返回 null，无法据此判定"打开失败"。
    const noReferrerPortals = new Set(['zte_ume', 'ccn_ume', 'ipran_ume', 'mw_ume'])
    const features = direct || noReferrerPortals.has(p.key)
      ? 'noreferrer,noopener=no'
      : 'noopener=no'
    const win = window.open(url, '_blank', features)
    // noreferrer 隐含 noopener → 句柄恒为 null，无法据此判定失败，只在未带
    // noreferrer 时把 null 当作"被弹窗拦截"。
    if (!win && !features.includes('noreferrer')) {
      showMsg('warning', t('portal.popupBlocked'))
      return
    }
    showMsg('info', t(direct ? 'portal.clientOpenedDirect' : 'portal.clientOpened'))
    // 未部署扩展时保留直连手动登录兜底，不能把“打开了页面”误报为已登录。
    setStatus((prev) => ({
      ...prev,
      [p.key]: direct
        ? { state: 'need_manual', message: t('portal.clientOpenedDirect') }
        : { state: 'success', message: '' },
    }))
    if (win) win.focus()
  }, [portalExtensionReady, showMsg, t])

  const handleLogin = useCallback(async (system: string, p?: Portal) => {
    // 直连门户（eFlow / RAIS）优先使用受管扩展写入访问者本机 Chrome 会话；
    // 未部署扩展时仍只能直连手工登录。访问者就在服务器本机时，保持原有的
    // 服务器直接鉴权路径，弹出的窗口也正好处于该用户桌面。
    const localDirect = !!p && isDirect(p) && (clientIsLocal || isOnServerHost())
    if (mode === 'client' && p && canClientLogin(p) && !localDirect) {
      handleClientLogin(p)
      return
    }
    setStatus((prev) => ({ ...prev, [system]: { state: 'launching', message: '' } }))
    try {
      const { data } = await api.post('/portals/login', { system })
      showMsg('info', t(localDirect ? 'portal.localDirectServer' : 'portal.opened'))
      pollJob(system, data.job_id)
    } catch (e: any) {
      showMsg('error', e?.response?.data?.detail || t('portal.loadError'))
      setStatus((prev) => ({ ...prev, [system]: { state: 'failed', message: '' } }))
    }
  }, [clientIsLocal, mode, pollJob, showMsg, t])

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
            onChange={(v) => changeMode(v as 'client' | 'server')}
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
            // 客户端直连门户只是「打开了登录页」，没有服务端常驻浏览器 → 不算 Live
            const isLive = p.live || st === 'success' || (st === 'need_manual' && mode === 'server')
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
                      disabled={st === 'launching' || (mode === 'client' && !canClientLogin(p))}
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
                  {isDirect(p) ? (
                    <Tooltip title={t('portal.clientOpenedDirect')}>
                      <Tag color="orange">{t('portal.direct')}</Tag>
                    </Tooltip>
                  ) : p.proxy_prefix == null ? (
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
