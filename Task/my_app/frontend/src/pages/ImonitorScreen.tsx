import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, Space, Spin, Tooltip, Typography } from 'antd'
import {
  ReloadOutlined,
  LoginOutlined,
  ExportOutlined,
  FullscreenOutlined,
  FullscreenExitOutlined,
} from '@ant-design/icons'
import { useI18n } from '../i18n'

/**
 * UME iMonitor 大屏（guard-imonitor-iui）嵌入页
 * =============================================================================
 * 目标：把 `https://172.17.208.1:28808/iui/guard-imonitor-iui/#/screen/screen-view?screen_id=1`
 * 原样搬进 myapp（`?page=imonitor`），并自动用 em-portal 账号（credential_store
 * key=`ume_in`，即 10172755）完成鉴权 —— 与 `?page=vmaxCxoDashboard` 同属
 * 「原版页面嵌入」这一类，只是这个页面**必须登录**，且不能直连上游。
 *
 * 为什么不直接把上游 URL 塞进 iframe
 * -----------------------------------------------------------------------------
 * 1) **同源**：浏览器要带着门户会话 Cookie 才能打开大屏，而 Cookie 只能由门户
 *    自己种下。myapp(80) 与门户(172.17.208.1:28808) 不同源，既种不了也读不了。
 *    因此走仓库既有的「门户独立端口反代」方案：nginx 8088 → 上游（见
 *    nginx/portal_ume_in_8088.conf），iframe 指向 `//<host>:8088/...`，
 *    于是「打开大屏」与「登录门户」变成同源，Cookie 天然可用。
 * 2) **自动登录**：反代在登录页注入 `/api/portals/inject.js?system=ume_in`
 *    （backend/services/portal_login_service.build_inject_js），自动填账号密码并点
 *    登录按钮，会话 Cookie 落在**访问者自己的浏览器**里 —— 不需要用户做任何事。
 * 3) **两个上游「拦路虎」**（都在 nginx 里处理，实测确诊，详见该 conf 注释）：
 *    · 上游带 `Content-Security-Policy: frame-ancestors 'self'` → iframe 直接被
 *      浏览器拦死（chrome-error 页）。故反代必须摘掉 CSP/XFO。
 *    · 门户登录页内联 frame-bust `top.location = self.location;` → 登录页一旦被
 *      嵌进 iframe，会把**整个 myapp 标签页**导航到登录页、冲掉 myapp 外壳。
 *      反代用 sub_filter 把它改成 no-op，登录全过程留在 iframe 内。
 *
 * 登录时序（首次访问 / 会话过期时自动发生，无需用户干预）
 * -----------------------------------------------------------------------------
 *   iframe 载入大屏 → SPA 调 /api/guard-imonitor-service/v1/largescreen/screen
 *   → 401 → SPA 自己跳到 `/api/oauth2/v1/authorize?redirect_uri=/iui/guard-imonitor-iui/`
 *   → 注入脚本填表并提交（并 postMessage 通知本页）
 *   → login_rsa 成功 → 门户把浏览器送到 `redirect_uri` 的**根路径**
 *   → 本页收到 postMessage 后把 iframe 重新指回带 hash 的 screen 深链
 *
 * ⚠️ 最后一步不能省：门户登录成功只回落到 `redirect_uri` 根路径，`#/screen/screen-view?screen_id=1`
 *    这段 hash 路由在跳转中必然丢失，不重指的话用户看到的是大屏的默认首页而不是 screen_id=1。
 *    这也是 inject.js 里新增那条 `myapp-portal-autologin` postMessage 的唯一用途。
 *
 * 自动刷新：本页注册在 App.tsx 的 AR_SOFT_REFRESH_PAGES 里 —— 到点时外壳广播
 * `myapp-refresh` 而不是重挂载本组件（重挂载会整页闪白），由本组件在 iframe 内
 * 原地重载大屏（见下方 onMessage）。
 * =============================================================================
 */

/** 门户反代端口：必须与 nginx/portal_ume_in_8088.conf 及 portal_login_service.PROXY_PREFIXES 一致 */
const PORTAL_PORT = 8088
/** 大屏 SPA 的根路径（门户的 redirect_uri / pathname 口径） */
const SCREEN_PATH = '/iui/guard-imonitor-iui/'
/** 目标大屏路由：screen_id=1 */
const SCREEN_HASH = '#/screen/screen-view?screen_id=1'
/** 登录提交后等待门户完成跳转再重指 iframe 的时长（毫秒） */
const RELOGIN_SETTLE_MS = 3000
/**
 * 单次挂载内允许的「自动重新登录 + 重指」次数上限。
 * 正常情况下 1 次就够（实测：3.0s 401 → 3.0s 注入脚本提交 → 6.1s 重指后大屏 200）。
 * 但**实测约半数运行会出现第二轮**：第一轮 login_rsa 已 200，3 秒后重指过去大屏接口
 * 仍返回 401（门户侧会话尚未落定 / 同账号并发会话互顶），SPA 于是又跳一次登录页、
 * 注入脚本再提交一次、再发一条 postMessage —— 第二轮就成功了（约 9s 出图）。
 * 这个自愈循环必须有上限：异常情况下不能无限重试，否则会把门户会话额度打满。
 * 达到上限后工具条的手动「刷新 / 重新登录」会重新武装（见 manualReload/manualRelogin）。
 */
const MAX_AUTO_RELOGIN = 4

/**
 * 反代基址：跟随访问者打开 myapp 用的主机名。
 * 不能写死 127.0.0.1 —— 远程同事访问 `http://192.168.100.20/myapp/` 时，
 * 127.0.0.1:8088 指的是**他自己**那台机器，必然打不开。
 * （与 PROXY_PREFIXES 里 `//{HOST}:8088` 的 `{HOST}` 是同一个口径。）
 */
function portalBase(): string {
  return `${window.location.protocol}//${window.location.hostname}:${PORTAL_PORT}`
}

/** 大屏 URL（cacheBust 用来强制 iframe 重新拉取，避免 SPA 导航复用旧文档） */
function screenUrl(cacheBust: number): string {
  return `${portalBase()}${SCREEN_PATH}?_=${cacheBust}${SCREEN_HASH}`
}

/**
 * 门户登录入口（同源反代）。redirect_uri 指到大屏根路径：登录成功后门户会落到
 * 大屏 SPA，本页收到 postMessage 后再把它拉回 screen_id=1 的深链。
 */
function portalLoginUrl(): string {
  const q = new URLSearchParams({
    scope: 'user.login',
    response_type: 'code',
    redirect_uri: SCREEN_PATH,
  })
  return `${portalBase()}/api/oauth2/v1/authorize?${q.toString()}`
}

export default function ImonitorScreen() {
  const { t } = useI18n()
  const frameRef = useRef<HTMLIFrameElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  // 首次 src 在挂载时定死：每次挂载换一个戳，保证切页面回来时重新拉取
  const [src, setSrc] = useState<string>(() => screenUrl(Date.now()))
  const [loading, setLoading] = useState(true)
  const [fullscreen, setFullscreen] = useState(false)
  /** 登录流程进行中：期间不要被自动刷新的「重指」打断 */
  const loggingIn = useRef(false)
  /** 已自动重指次数（见 MAX_AUTO_RELOGIN） */
  const autoRelogin = useRef(0)
  /** 待执行的重指定时器（重复的 postMessage 只保留最后一次） */
  const resetTimer = useRef<number | null>(null)

  /** 重新指向大屏（带新的 cacheBust，等价于在 iframe 内硬刷新） */
  const reloadScreen = useCallback(() => {
    loggingIn.current = false
    setLoading(true)
    setSrc(screenUrl(Date.now()))
  }, [])

  /** 强制重新登录：直接打开门户登录页，注入脚本会自动填表并提交 */
  const relogin = useCallback(() => {
    loggingIn.current = true
    setLoading(true)
    setSrc(portalLoginUrl())
  }, [])

  /** 用户手动操作：重新武装自动重登次数（否则重试上限用完后手动刷新也救不回来） */
  const manualReload = useCallback(() => {
    autoRelogin.current = 0
    reloadScreen()
  }, [reloadScreen])

  const manualRelogin = useCallback(() => {
    autoRelogin.current = 0
    relogin()
  }, [relogin])

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      const d = e.data
      if (!d || typeof d !== 'object') return

      // ① 注入脚本报告「登录已提交」：等门户跳转落定后把 iframe 拉回 screen 深链
      //    （门户登录成功只会回落到 redirect_uri 根路径，hash 路由必然丢失）
      if (d.__type === 'myapp-portal-autologin' && d.system === 'ume_in') {
        if (autoRelogin.current >= MAX_AUTO_RELOGIN) return
        loggingIn.current = true
        // 一轮登录只会提交一次（inject.js 点完就 clearInterval），但门户可能在一轮里
        // 加载两次登录页；重复到达时只保留最后一次定时器，避免叠加多次重指。
        if (resetTimer.current !== null) window.clearTimeout(resetTimer.current)
        resetTimer.current = window.setTimeout(() => {
          resetTimer.current = null
          autoRelogin.current += 1
          reloadScreen()
        }, RELOGIN_SETTLE_MS)
        return
      }

      // ② 外壳的软刷新协议（App.tsx performAutoRefresh 广播）：原地重载大屏。
      //    登录进行中时跳过，避免把登录页/跳转中的文档打断。
      if (d.__type === 'myapp-refresh') {
        if (loggingIn.current) return
        setLoading(true)
        setSrc(screenUrl(Date.now()))
      }
    }
    window.addEventListener('message', onMessage)
    return () => {
      window.removeEventListener('message', onMessage)
      if (resetTimer.current !== null) window.clearTimeout(resetTimer.current)
    }
  }, [reloadScreen])

  // 元素级全屏状态跟随浏览器（用户按 Esc 退出时按钮要跟着回到「进入全屏」）
  useEffect(() => {
    const onFsChange = () => setFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onFsChange)
    return () => document.removeEventListener('fullscreenchange', onFsChange)
  }, [])

  const toggleFullscreen = useCallback(() => {
    const el = wrapRef.current
    if (!el) return
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => { /* 用户手势缺失等场景忽略 */ })
    } else {
      el.requestFullscreen().catch(() => { /* 浏览器拒绝时忽略 */ })
    }
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, gap: 'var(--wh-space-xs)' }}>
      {/* 工具条：大屏本身没有「重新登录」入口（会话过期后 SPA 会自己跳登录页，
          但用户可能想主动刷新会话），这里补上；同时给出「在新窗口打开门户」的出口。 */}
      <div
        style={{
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 'var(--wh-space-sm)',
          flexWrap: 'wrap',
        }}
      >
        <Typography.Text
          type="secondary"
          style={{ fontSize: 12, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        >
          {t('imonitor.tip')}
        </Typography.Text>
        <Space size={4} wrap>
          <Tooltip title={t('imonitor.refreshTip')}>
            <Button size="small" icon={<ReloadOutlined />} onClick={manualReload}>
              {t('imonitor.refresh')}
            </Button>
          </Tooltip>
          <Tooltip title={t('imonitor.reloginTip')}>
            <Button size="small" icon={<LoginOutlined />} onClick={manualRelogin}>
              {t('imonitor.relogin')}
            </Button>
          </Tooltip>
          <Tooltip title={t('imonitor.openTip')}>
            <Button
              size="small"
              icon={<ExportOutlined />}
              onClick={() => window.open(`${portalBase()}${SCREEN_PATH}${SCREEN_HASH}`, '_blank', 'noopener=no')}
            >
              {t('imonitor.open')}
            </Button>
          </Tooltip>
          <Tooltip title={fullscreen ? t('imonitor.exitFullscreen') : t('imonitor.fullscreen')}>
            <Button
              size="small"
              icon={fullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
              onClick={toggleFullscreen}
            />
          </Tooltip>
        </Space>
      </div>

      <div
        ref={wrapRef}
        style={{
          position: 'relative',
          flex: 1,
          minHeight: 0,
          width: '100%',
          borderRadius: 'var(--wh-radius-md)',
          overflow: 'hidden',
          background: 'var(--wh-page-bg)',
        }}
      >
        {loading && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 'var(--wh-space-sm)',
              background: 'var(--wh-page-bg)',
              zIndex: 1,
            }}
          >
            <Spin size="large" />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {t('imonitor.loading')}
            </Typography.Text>
          </div>
        )}
        <iframe
          ref={frameRef}
          src={src}
          title={t('nav.imonitor')}
          onLoad={() => setLoading(false)}
          allowFullScreen
          // 大屏内可能用到剪贴板 / 全屏；摄像头麦克风一律不给
          allow="fullscreen; clipboard-read; clipboard-write"
          /**
           * sandbox 是这里最关键的一道保险：门户**不止**在登录页内联了 frame-bust，
           * 其 JS 里还有两处会去操作顶层窗口（实测定位）：
           *   · login.min.js    : `top!=self&&(top.location=self.location)`（同一段被压缩成两份）
           *   · security.min.js : 登录成功后 `top ? redirectToUrl(top.location, home) : …`，
           *                       即把**顶层窗口**重定向到 home；另有 `top.location.reload()`。
           * 这些都在 iframe 内运行、拿不到父页面 DOM，但**导航顶层窗口**是跨源允许的操作
           * —— 只靠 nginx 改内联脚本挡不住。Chrome 仅在「无用户激活」时拦截它
           * （控制台报 "Unsafe attempt to initiate navigation for frame"），
           * 一旦用户刚点过 myapp（激活窗口约 5 秒），登录页就可能把整个 myapp 标签页
           * 换成大屏。加上 sandbox（**不含** allow-top-navigation）后，浏览器直接禁止
           * 该 iframe 导航顶层，任何浏览器/任何激活状态下 myapp 外壳都不会被冲掉。
           * allow-same-origin 必须给：门户要靠它读写自己的 Cookie / localStorage 维持会话；
           * allow-forms 给登录表单提交；allow-popups 给门户内的「新窗口打开」。
           * （与父页面跨源，故 iframe 无法自行摘掉 sandbox。）
           */
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads allow-modals"
          style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
        />
      </div>
    </div>
  )
}
