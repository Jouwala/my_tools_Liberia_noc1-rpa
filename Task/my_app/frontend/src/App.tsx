import { useState, lazy, Suspense, useEffect, useCallback } from 'react'
import { ConfigProvider, Layout, Menu, theme, Button, Spin, Tooltip } from 'antd'
import {
  DatabaseOutlined,
  AppstoreOutlined,
  UploadOutlined,
  DashboardOutlined,
  GlobalOutlined,
  HistoryOutlined,
  TableOutlined,
  BarChartOutlined,
  TranslationOutlined,
  SyncOutlined,
  AlertOutlined,
  DisconnectOutlined,
  ThunderboltOutlined,
  SettingOutlined,
  AimOutlined,
  FileSearchOutlined,
  LineChartOutlined,
  FundOutlined,
  PieChartOutlined,
  SunOutlined,
  MoonOutlined,
  ExportOutlined,
  SelectOutlined,
  MenuUnfoldOutlined,
  MenuFoldOutlined,
  MailOutlined,
  ApartmentOutlined,
  CloseOutlined,
} from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'
import enUS from 'antd/locale/en_US'

import { I18nProvider, useI18n } from './i18n'
import { TaskStatusProvider } from './TaskStatusContext'
import { ThemeProvider, useTheme, WH, useIsMobile } from './theme'

// 路由级代码分割：每个页面独立成 chunk，按需加载，首屏不再一次性下载全部页面
const TableBrowser = lazy(() => import('./pages/TableBrowser'))
const DataUpload = lazy(() => import('./pages/DataUpload'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const GISMap = lazy(() => import('./pages/GISMap'))
const ArchiveList = lazy(() => import('./pages/ArchiveList'))
const DataSync = lazy(() => import('./pages/DataSync'))
const WarehouseDashboard = lazy(() => import('./pages/WarehouseDashboard'))
const Overview = lazy(() => import('./pages/Overview'))
const TTWODashboard = lazy(() => import('./pages/TTWODashboard'))
const AlarmDashboard = lazy(() => import('./pages/AlarmDashboard'))
const PacketLossDashboard = lazy(() => import('./pages/PacketLossDashboard'))
const BatteryDashboard = lazy(() => import('./pages/BatteryDashboard'))
const Settings = lazy(() => import('./pages/Settings'))
const IpTrace = lazy(() => import('./pages/IpTrace'))
const IncidentOverview = lazy(() => import('./pages/IncidentOverview'))
const NurDashboard = lazy(() => import('./pages/NurDashboard'))
const MsSlaDashboard = lazy(() => import('./pages/MsSlaDashboard'))
const AlarmManagement = lazy(() => import('./pages/AlarmManagement'))
const CxoDashboard = lazy(() => import('./pages/CxoDashboard'))
const EmailReports = lazy(() => import('./pages/EmailReports'))
const MwUmeDashboard = lazy(() => import('./pages/MwUmeDashboard'))

const { Header, Sider, Content } = Layout

type PageKey = 'overview' | 'tables' | 'upload' | 'dashboard' | 'alarm' | 'ttwo' | 'gis' | 'realtime_alarm' | 'packet_loss' | 'archive' | 'sync' | 'warehouse' | 'battery' | 'settings' | 'ip_trace' | 'incident_overview' | 'nur' | 'ms_sla' | 'alarmManagement' | 'cxoDashboard' | 'email_reports' | 'mwUmeTopology'

const VALID_PAGES: PageKey[] = ['overview', 'tables', 'upload', 'dashboard', 'alarm', 'ttwo', 'gis', 'realtime_alarm', 'packet_loss', 'archive', 'sync', 'warehouse', 'battery', 'settings', 'ip_trace', 'incident_overview', 'nur', 'ms_sla', 'alarmManagement', 'cxoDashboard', 'email_reports', 'mwUmeTopology']

function AppContent() {
  // 支持 ?page=xxx 直链定位（右键菜单「在新标签页打开」使用），非法值回退到默认页
  const [currentPage, setCurrentPage] = useState<PageKey>(() => {
    const p = new URLSearchParams(window.location.search).get('page')
    return p && (VALID_PAGES as string[]).includes(p) ? (p as PageKey) : 'sync'
  })
  // 侧边栏默认隐藏（完全收起、不占空间），展开/收起偏好持久化到 localStorage
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      // 默认隐藏：仅当用户曾明确展开（存 '0'）时才展开
      return localStorage.getItem('myapp_sider_collapsed') !== '0'
    } catch { return true }
  })
  const toggleSider = useCallback(() => {
    setCollapsed(prev => {
      const next = !prev
      try { localStorage.setItem('myapp_sider_collapsed', next ? '1' : '0') } catch { /* noop */ }
      return next
    })
  }, [])
  const { t, locale, toggleLocale } = useI18n()
  const { isDark, toggle } = useTheme()
  const isMobile = useIsMobile()

  const menuItems = [
    { key: 'sync', icon: <SyncOutlined />, label: t('nav.sync') },
    { key: 'email_reports', icon: <MailOutlined />, label: t('nav.emailReports') },
    { key: 'alarm', icon: <AlertOutlined />, label: t('nav.alarm') },
    { key: 'ttwo', icon: <BarChartOutlined />, label: t('nav.ttwo') },
    { key: 'nur', icon: <LineChartOutlined />, label: t('nav.nur') },
    { key: 'ms_sla', icon: <FundOutlined />, label: t('nav.msSla') },
    { key: 'cxoDashboard', icon: <PieChartOutlined />, label: t('nav.cxoDashboard') },
    { key: 'mwUmeTopology', icon: <ApartmentOutlined />, label: t('nav.mwUmeTopology') },
    { key: 'gis', icon: <GlobalOutlined />, label: t('nav.gis') },
    { key: 'realtime_alarm', icon: <AlertOutlined />, label: t('nav.realtimeAlarm') },
    { key: 'alarmManagement', icon: <AlertOutlined />, label: t('nav.alarmManagement') },
    { key: 'packet_loss', icon: <DisconnectOutlined />, label: t('nav.packetLoss') },
    { key: 'battery', icon: <ThunderboltOutlined />, label: t('nav.battery') },
    { key: 'ip_trace', icon: <AimOutlined />, label: t('nav.ipTrace') },
    { key: 'incident_overview', icon: <FileSearchOutlined />, label: t('nav.incidentOverview') },
    { key: 'warehouse', icon: <AppstoreOutlined />, label: t('nav.sp') },
    { key: 'overview', icon: <BarChartOutlined />, label: t('nav.overview') },
    { key: 'tables', icon: <TableOutlined />, label: t('nav.tables') },
    { key: 'upload', icon: <UploadOutlined />, label: t('nav.upload') },
    { key: 'archive', icon: <HistoryOutlined />, label: t('nav.archive') },
    { key: 'dashboard', icon: <DashboardOutlined />, label: t('nav.dashboard') },
    { key: 'settings', icon: <SettingOutlined />, label: t('nav.settings') },
  ]

  // ===== 右键菜单（在新标签页打开）=====
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; key: PageKey } | null>(null)
  const [ctxHover, setCtxHover] = useState<'newTab' | 'currentTab' | null>(null)

  const onMenuContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    const el = (e.target as HTMLElement).closest('li[data-menu-id]')
    if (!el) return
    // antd v6 的 data-menu-id 形如 "rc-menu-uuid-<key>"，剥离前缀还原业务 key
    let raw = el.getAttribute('data-menu-id') || ''
    let key = raw.replace(/^rc-menu-uuid-/, '')
    if (!(VALID_PAGES as string[]).includes(key)) {
      // 兜底：按在父级中的索引映射回 menuItems（单层 inline 菜单顺序一致）
      const parent = el.parentElement
      if (parent) {
        const idx = Array.prototype.indexOf.call(parent.children, el)
        key = (menuItems[idx]?.key ?? '') as string
      }
    }
    if (!(VALID_PAGES as string[]).includes(key)) return
    const menuW = 190
    const menuH = 96
    const pad = 8
    const x = Math.min(e.clientX, window.innerWidth - menuW - pad)
    const y = Math.min(e.clientY, window.innerHeight - menuH - pad)
    setCtxMenu({ x: Math.max(pad, x), y: Math.max(pad, y), key: key as PageKey })
  }, [menuItems])

  const closeCtxMenu = useCallback(() => {
    setCtxMenu(null)
    setCtxHover(null)
  }, [])

  const openInNewTab = useCallback((key: PageKey) => {
    // 同源路径 + ?page= 参数，新标签页据此定位页面
    const url = `${window.location.pathname}?page=${key}`
    window.open(url, '_blank', 'noopener')
    closeCtxMenu()
  }, [closeCtxMenu])

  // 页面名同步到浏览器标签标题，便于新标签页识别
  useEffect(() => {
    const label = menuItems.find(m => m.key === currentPage)?.label
    if (label) document.title = `${label} - ${t('app.title')}`
  }, [currentPage, locale])

  const ctxItemBase: React.CSSProperties = {
    padding: 'var(--wh-space-xs) var(--wh-space-sm)',
    borderRadius: 'var(--wh-radius-md)',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    gap: 'var(--wh-space-sm)',
    color: isDark ? '#dbeafe' : '#1e293b',
    fontSize: '0.8125rem',
    userSelect: 'none',
  }

  const renderPage = () => {
    switch (currentPage) {
      case 'sync':
        return <DataSync />
      case 'alarm':
        return <AlarmDashboard />
      case 'ttwo':
        return <TTWODashboard />
      case 'nur':
        return <NurDashboard />
      case 'ms_sla':
        return <MsSlaDashboard />
      case 'alarmManagement':
        return <AlarmManagement />
      case 'cxoDashboard':
        return <CxoDashboard />
      case 'mwUmeTopology':
        return <MwUmeDashboard />
      case 'email_reports':
        return <EmailReports />
      case 'gis':
        return <GISMap />
      case 'realtime_alarm':
        return <GISMap mode="realtime" />
      case 'packet_loss':
        return <PacketLossDashboard />
      case 'battery':
        return <BatteryDashboard />
      case 'ip_trace':
        return <IpTrace />
      case 'incident_overview':
        return <IncidentOverview />
      case 'warehouse':
        return <WarehouseDashboard />
      case 'overview':
        return <Overview />
      case 'tables':
        return <TableBrowser />
      case 'upload':
        return <DataUpload />
      case 'archive':
        return <ArchiveList />
      case 'dashboard':
        return <Dashboard />
      case 'settings':
        return <Settings />
      default:
        return <Overview />
    }
  }

  return (
    <ConfigProvider
      locale={locale === 'zh' ? zhCN : enUS}
      theme={{
        algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
        token: {
          colorPrimary: '#13c2c2',
          colorInfo: '#13c2c2',
          borderRadius: 6,
        },
        components: isDark ? {} : {
          Table: { headerBg: '#f0f5fa', headerColor: '#334155', rowHoverBg: '#e8f4f2' },
        },
      }}
    >
      <Layout style={{ minHeight: '100vh', background: 'var(--wh-page-bg)' }}>
        <Sider
          collapsible
          collapsed={collapsed}
          collapsedWidth={0}
          trigger={null}
          theme={isDark ? 'dark' : 'light'}
          width={'var(--wh-sider-width)' as any}
          style={{
            background: isDark ? '#0a1929' : '#f6fafd',
            borderRight: isDark ? 'none' : '1px solid #d9e6f2',
            // 收起时整体隐藏（含边框），由 Header 汉堡按钮展开
            ...(collapsed ? { borderRight: 'none' } : {}),
            // 移动端：侧边栏作为抽屉浮层，从 Header 下方滑出，不覆盖 Header
            ...(isMobile && !collapsed
              ? {
                  position: 'fixed',
                  left: 0,
                  top: 'var(--wh-header-height)',
                  bottom: 0,
                  width: 'var(--wh-sider-width)',
                  zIndex: 1000,
                  height: 'auto',
                  boxShadow: isDark ? '4px 0 24px rgba(0,0,0,0.45)' : '4px 0 20px rgba(13,94,84,0.18)',
                }
              : {}),
          }}
        >
          <div style={{
            height: 'var(--wh-header-height)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: WH.teal,
            fontWeight: 'bold',
            fontSize: collapsed ? '0.875rem' : '1rem',
            borderBottom: isDark ? '1px solid rgba(100,255,218,0.15)' : '1px solid rgba(13,148,136,0.25)',
            background: isDark ? 'linear-gradient(90deg, #0a1929, #112540)' : 'linear-gradient(90deg, #eef6fb, #e0edf7)',
            position: 'relative',
          }}>
            {collapsed ? t('app.titleShort') : t('app.title')}
            {isMobile && !collapsed && (
              <Button
                type="text"
                aria-label={t('nav.collapse')}
                icon={<CloseOutlined style={{ color: WH.teal, fontSize: '1rem' }} />}
                onClick={() => setCollapsed(true)}
                style={{
                  position: 'absolute',
                  right: 'var(--wh-space-sm)',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  width: '2.25rem',
                  height: '2.25rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              />
            )}
          </div>
          <Menu
            theme={isDark ? 'dark' : 'light'}
            mode="inline"
            selectedKeys={[currentPage]}
            items={menuItems}
            onClick={({ key }) => { setCurrentPage(key as PageKey); closeCtxMenu(); if (isMobile) setCollapsed(true) }}
            onContextMenu={onMenuContextMenu}
            style={{ background: isDark ? '#0a1929' : '#f6fafd' }}
          />
          {/* 右键菜单浮层：全屏透明遮罩负责关闭，菜单本体定位在鼠标处 */}
          {ctxMenu && (
            <>
              <div
                style={{ position: 'fixed', inset: 0, zIndex: 2000 }}
                onClick={closeCtxMenu}
                onContextMenu={(e) => { e.preventDefault(); closeCtxMenu() }}
              />
              <div style={{
                position: 'fixed',
                left: ctxMenu.x,
                top: ctxMenu.y,
                zIndex: 2001,
                minWidth: '10.625rem',
                padding: 'var(--wh-space-xs)',
                background: isDark ? '#0f2744' : '#ffffff',
                border: isDark ? '1px solid rgba(100,255,218,0.25)' : '1px solid #d5e2ef',
                borderRadius: 'var(--wh-radius-md)',
                boxShadow: isDark ? '0 8px 28px rgba(0,0,0,0.55)' : '0 6px 24px rgba(13,94,84,0.16)',
              }}>
                <div
                  style={{
                    ...ctxItemBase,
                    background: ctxHover === 'newTab' ? (isDark ? 'rgba(100,255,218,0.14)' : 'rgba(19,194,194,0.12)') : 'transparent',
                  }}
                  onMouseEnter={() => setCtxHover('newTab')}
                  onMouseLeave={() => setCtxHover(null)}
                  onClick={() => openInNewTab(ctxMenu.key)}
                >
                  <ExportOutlined style={{ color: WH.teal }} />
                  {t('ctx.newTab')}
                </div>
                <div
                  style={{
                    ...ctxItemBase,
                    background: ctxHover === 'currentTab' ? (isDark ? 'rgba(100,255,218,0.14)' : 'rgba(19,194,194,0.12)') : 'transparent',
                  }}
                  onMouseEnter={() => setCtxHover('currentTab')}
                  onMouseLeave={() => setCtxHover(null)}
                  onClick={() => { setCurrentPage(ctxMenu.key); closeCtxMenu() }}
                >
                  <SelectOutlined style={{ color: WH.teal }} />
                  {t('ctx.currentTab')}
                </div>
              </div>
            </>
          )}
        </Sider>
        <Layout style={{ background: WH.bg, flex: 1, minWidth: 0 }}>
          <Header style={{
            background: isDark ? 'linear-gradient(180deg, #0f2744 0%, #0a1929 100%)' : 'linear-gradient(180deg, #ddebf6 0%, #eef4fa 100%)',
            padding: isMobile ? '0 var(--wh-space-sm)' : '0 var(--wh-space-lg)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: isDark ? 'none' : '1px solid #d5e2ef',
            boxShadow: isDark ? '0 2px 12px rgba(0,0,0,0.35)' : '0 2px 10px rgba(13,94,84,0.10)',
            position: 'relative',
            overflow: 'hidden',
            height: 'var(--wh-header-height)',
            flexShrink: 0,
          }}>
            {/* 背景网格纹理 */}
            <div style={{
              position: 'absolute',
              inset: 0,
              backgroundImage: isDark
                ? 'linear-gradient(rgba(100,255,218,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(100,255,218,0.03) 1px, transparent 1px)'
                : 'linear-gradient(rgba(13,148,136,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(13,148,136,0.05) 1px, transparent 1px)',
              backgroundSize: '1.5rem 1.5rem',
              pointerEvents: 'none',
            }} />

            {/* 汉堡按钮：侧边栏默认隐藏，点击展开/收起 */}
            <Button
              type="text"
              className="wh-sider-toggle"
              aria-label={collapsed ? t('nav.expand') : t('nav.collapse')}
              icon={collapsed ? <MenuUnfoldOutlined style={{ color: WH.teal, fontSize: isMobile ? '1.25rem' : '1.0625rem' }} /> : <MenuFoldOutlined style={{ color: WH.teal, fontSize: isMobile ? '1.25rem' : '1.0625rem' }} />}
              onClick={toggleSider}
              style={{
                position: 'absolute',
                left: 'var(--wh-space-sm)',
                top: '50%',
                transform: 'translateY(-50%)',
                zIndex: 10,
                width: isMobile ? '2.75rem' : '2.25rem',
                height: isMobile ? '2.75rem' : '2.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: isMobile ? (isDark ? 'rgba(100,255,218,0.12)' : 'rgba(13,148,136,0.12)') : 'transparent',
                border: isMobile ? `1px solid ${isDark ? 'rgba(100,255,218,0.35)' : 'rgba(13,148,136,0.35)'}` : '1px solid transparent',
                borderRadius: 'var(--wh-radius-md)',
              }}
            />

            {/* 左侧装饰箭头 */}
            <div className="wh-hide-mobile" style={{
              position: 'absolute',
              left: '3.25rem',
              top: '50%',
              transform: 'translateY(-50%)',
              color: isDark ? 'rgba(100,255,218,0.25)' : 'rgba(13,148,136,0.35)',
              fontSize: '1.125rem',
              letterSpacing: '0.25rem',
              userSelect: 'none',
            }}>
              ▶▶
            </div>

            {/* 右侧装饰箭头 */}
            <div className="wh-hide-mobile" style={{
              position: 'absolute',
              right: '10rem',
              top: '50%',
              transform: 'translateY(-50%)',
              color: isDark ? 'rgba(100,255,218,0.25)' : 'rgba(13,148,136,0.35)',
              fontSize: '1.125rem',
              letterSpacing: '0.25rem',
              userSelect: 'none',
            }}>
              ◀
            </div>

            {/* 居中标题 */}
            <div style={{
              flex: 1,
              textAlign: 'center',
              position: 'relative',
              zIndex: 1,
            }}>
              <h1 style={{
                margin: 0,
                fontSize: isMobile ? '1.125rem' : '1.375rem',
                fontWeight: 700,
                color: WH.teal,
                textShadow: isDark
                  ? `0 0 20px var(--wh-teal-40), 0 0 40px var(--wh-teal-20)`
                  : '0 1px 2px rgba(255,255,255,0.6)',
                letterSpacing: '0.125rem',
                lineHeight: 1.2,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                padding: '0 var(--wh-space-sm)',
              }}>
                {menuItems.find(m => m.key === currentPage)?.label || t('nav.overview')}
              </h1>
              {/* 底部发光装饰线 */}
              <div style={{
                width: '7.5rem',
                height: 2,
                margin: 'var(--wh-space-xs) auto 0',
                background: WH.accentGrad,
                boxShadow: isDark ? `0 0 8px var(--wh-teal-53)` : 'none',
                borderRadius: 1,
              }} />
            </div>

            {/* 右上角操作区：主题切换 + 语言切换 */}
            <div style={{ position: 'relative', zIndex: 2, display: 'flex', alignItems: 'center', gap: 'var(--wh-space-sm)' }}>
              <Tooltip title={isDark ? t('theme.toLight') : t('theme.toDark')}>
                <Button
                  size="small"
                  icon={isDark ? <SunOutlined /> : <MoonOutlined />}
                  onClick={toggle}
                  aria-label={isDark ? t('theme.toLight') : t('theme.toDark')}
                  style={{
                    color: WH.teal,
                    borderColor: isDark ? 'rgba(100,255,218,0.35)' : 'rgba(13,148,136,0.45)',
                    background: isDark ? 'transparent' : 'rgba(255,255,255,0.85)',
                  }}
                />
              </Tooltip>
              <Button
                size="small"
                icon={<TranslationOutlined />}
                onClick={toggleLocale}
                style={{
                  color: WH.teal,
                  borderColor: isDark ? 'rgba(100,255,218,0.35)' : 'rgba(13,148,136,0.45)',
                  background: isDark ? 'transparent' : 'rgba(255,255,255,0.85)',
                }}
              >
                <span className="wh-hide-mobile">{t('lang.switch')}</span>
              </Button>
            </div>
          </Header>
          <Content style={{
            margin: 'var(--wh-content-margin)',
            padding: 'var(--wh-content-padding)',
            overflow: 'auto',
            background: 'transparent',
            borderRadius: 'var(--wh-radius-md)',
            display: 'flex',
            flexDirection: 'column',
            minHeight: 0,
          }}>
            <Suspense fallback={
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
                <Spin size="large" />
              </div>
            }>
              {renderPage()}
            </Suspense>
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  )
}

function App() {
  return (
    <ThemeProvider>
      <I18nProvider>
        <TaskStatusProvider>
          <AppContent />
        </TaskStatusProvider>
      </I18nProvider>
    </ThemeProvider>
  )
}

export default App
