import { useState, lazy, Suspense } from 'react'
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
  SunOutlined,
  MoonOutlined,
} from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'
import enUS from 'antd/locale/en_US'

import { I18nProvider, useI18n } from './i18n'
import { TaskStatusProvider } from './TaskStatusContext'
import { ThemeProvider, useTheme, WH } from './theme'

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
const CredentialSettings = lazy(() => import('./pages/CredentialSettings'))
const IpTrace = lazy(() => import('./pages/IpTrace'))
const IncidentOverview = lazy(() => import('./pages/IncidentOverview'))
const NurDashboard = lazy(() => import('./pages/NurDashboard'))
const MsSlaDashboard = lazy(() => import('./pages/MsSlaDashboard'))

const { Header, Sider, Content } = Layout

type PageKey = 'overview' | 'tables' | 'upload' | 'dashboard' | 'alarm' | 'ttwo' | 'gis' | 'realtime_alarm' | 'packet_loss' | 'archive' | 'sync' | 'warehouse' | 'battery' | 'settings' | 'ip_trace' | 'incident_overview' | 'nur' | 'ms_sla'

function AppContent() {
  const [currentPage, setCurrentPage] = useState<PageKey>('sync')
  const [collapsed, setCollapsed] = useState(false)
  const { t, locale, toggleLocale } = useI18n()
  const { isDark, toggle } = useTheme()

  const menuItems = [
    { key: 'sync', icon: <SyncOutlined />, label: t('nav.sync') },
    { key: 'alarm', icon: <AlertOutlined />, label: t('nav.alarm') },
    { key: 'ttwo', icon: <BarChartOutlined />, label: t('nav.ttwo') },
    { key: 'nur', icon: <LineChartOutlined />, label: t('nav.nur') },
    { key: 'ms_sla', icon: <FundOutlined />, label: t('nav.msSla') },
    { key: 'gis', icon: <GlobalOutlined />, label: t('nav.gis') },
    { key: 'realtime_alarm', icon: <AlertOutlined />, label: t('nav.realtimeAlarm') },
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
        return <CredentialSettings />
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
          onCollapse={setCollapsed}
          theme={isDark ? 'dark' : 'light'}
          width={200}
          style={{ background: isDark ? '#0a1929' : '#f6fafd', borderRight: isDark ? 'none' : '1px solid #d9e6f2' }}
        >
          <div style={{
            height: 48,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: WH.teal,
            fontWeight: 'bold',
            fontSize: collapsed ? 14 : 16,
            borderBottom: isDark ? '1px solid rgba(100,255,218,0.15)' : '1px solid rgba(13,148,136,0.25)',
            background: isDark ? 'linear-gradient(90deg, #0a1929, #112540)' : 'linear-gradient(90deg, #eef6fb, #e0edf7)',
          }}>
            {collapsed ? t('app.titleShort') : t('app.title')}
          </div>
          <Menu
            theme={isDark ? 'dark' : 'light'}
            mode="inline"
            selectedKeys={[currentPage]}
            items={menuItems}
            onClick={({ key }) => setCurrentPage(key as PageKey)}
            style={{ background: isDark ? '#0a1929' : '#f6fafd' }}
          />
        </Sider>
        <Layout style={{ background: WH.bg }}>
          <Header style={{
            background: isDark ? 'linear-gradient(180deg, #0f2744 0%, #0a1929 100%)' : 'linear-gradient(180deg, #ddebf6 0%, #eef4fa 100%)',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: isDark ? 'none' : '1px solid #d5e2ef',
            boxShadow: isDark ? '0 2px 12px rgba(0,0,0,0.35)' : '0 2px 10px rgba(13,94,84,0.10)',
            position: 'relative',
            overflow: 'hidden',
            height: 56,
          }}>
            {/* 背景网格纹理 */}
            <div style={{
              position: 'absolute',
              inset: 0,
              backgroundImage: isDark
                ? 'linear-gradient(rgba(100,255,218,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(100,255,218,0.03) 1px, transparent 1px)'
                : 'linear-gradient(rgba(13,148,136,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(13,148,136,0.05) 1px, transparent 1px)',
              backgroundSize: '24px 24px',
              pointerEvents: 'none',
            }} />

            {/* 左侧装饰箭头 */}
            <div style={{
              position: 'absolute',
              left: 20,
              top: '50%',
              transform: 'translateY(-50%)',
              color: isDark ? 'rgba(100,255,218,0.25)' : 'rgba(13,148,136,0.35)',
              fontSize: 18,
              letterSpacing: 4,
              userSelect: 'none',
            }}>
              ▶▶
            </div>

            {/* 右侧装饰箭头 */}
            <div style={{
              position: 'absolute',
              right: 160,
              top: '50%',
              transform: 'translateY(-50%)',
              color: isDark ? 'rgba(100,255,218,0.25)' : 'rgba(13,148,136,0.35)',
              fontSize: 18,
              letterSpacing: 4,
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
                fontSize: 22,
                fontWeight: 700,
                color: WH.teal,
                textShadow: isDark
                  ? `0 0 20px var(--wh-teal-40), 0 0 40px var(--wh-teal-20)`
                  : '0 1px 2px rgba(255,255,255,0.6)',
                letterSpacing: 2,
                lineHeight: 1.2,
              }}>
                {menuItems.find(m => m.key === currentPage)?.label || t('nav.overview')}
              </h1>
              {/* 底部发光装饰线 */}
              <div style={{
                width: 120,
                height: 2,
                margin: '4px auto 0',
                background: WH.accentGrad,
                boxShadow: isDark ? `0 0 8px var(--wh-teal-53)` : 'none',
                borderRadius: 1,
              }} />
            </div>

            {/* 右上角操作区：主题切换 + 语言切换 */}
            <div style={{ position: 'relative', zIndex: 2, display: 'flex', alignItems: 'center', gap: 8 }}>
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
                {t('lang.switch')}
              </Button>
            </div>
          </Header>
          <Content style={{ margin: 16, padding: 4, overflow: 'auto', background: 'transparent', borderRadius: 8 }}>
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
