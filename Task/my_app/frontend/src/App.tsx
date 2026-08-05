import { useState, lazy, Suspense } from 'react'
import { ConfigProvider, Layout, Menu, theme, Button, Spin } from 'antd'
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
} from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'
import enUS from 'antd/locale/en_US'

import { I18nProvider, useI18n } from './i18n'
import { TaskStatusProvider } from './TaskStatusContext'
import { WH } from './theme'

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

const { Header, Sider, Content } = Layout

type PageKey = 'overview' | 'tables' | 'upload' | 'dashboard' | 'alarm' | 'ttwo' | 'gis' | 'realtime_alarm' | 'packet_loss' | 'archive' | 'sync' | 'warehouse' | 'battery' | 'settings'

function AppContent() {
  const [currentPage, setCurrentPage] = useState<PageKey>('sync')
  const [collapsed, setCollapsed] = useState(false)
  const { t, locale, toggleLocale } = useI18n()

  const menuItems = [
    { key: 'sync', icon: <SyncOutlined />, label: t('nav.sync') },
    { key: 'alarm', icon: <AlertOutlined />, label: t('nav.alarm') },
    { key: 'ttwo', icon: <BarChartOutlined />, label: t('nav.ttwo') },
    { key: 'gis', icon: <GlobalOutlined />, label: t('nav.gis') },
    { key: 'realtime_alarm', icon: <AlertOutlined />, label: t('nav.realtimeAlarm') },
    { key: 'packet_loss', icon: <DisconnectOutlined />, label: t('nav.packetLoss') },
    { key: 'battery', icon: <ThunderboltOutlined />, label: t('nav.battery') },
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
      case 'gis':
        return <GISMap />
      case 'realtime_alarm':
        return <GISMap mode="realtime" />
      case 'packet_loss':
        return <PacketLossDashboard />
      case 'battery':
        return <BatteryDashboard />
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
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#13c2c2',
          colorInfo: '#13c2c2',
          borderRadius: 6,
        },
      }}
    >
      <Layout style={{ minHeight: '100vh', background: '#0a1929' }}>
        <Sider
          collapsible
          collapsed={collapsed}
          onCollapse={setCollapsed}
          theme="dark"
          width={200}
          style={{ background: '#0a1929' }}
        >
          <div style={{
            height: 48,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: WH.teal,
            fontWeight: 'bold',
            fontSize: collapsed ? 14 : 16,
            borderBottom: '1px solid rgba(100,255,218,0.15)',
            background: 'linear-gradient(90deg, #0a1929, #112540)',
          }}>
            {collapsed ? t('app.titleShort') : t('app.title')}
          </div>
          <Menu
            theme="dark"
            mode="inline"
            selectedKeys={[currentPage]}
            items={menuItems}
            onClick={({ key }) => setCurrentPage(key as PageKey)}
            style={{ background: '#0a1929' }}
          />
        </Sider>
        <Layout style={{ background: WH.bg }}>
          <Header style={{
            background: '#0a1929',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid rgba(100,255,218,0.15)',
            boxShadow: '0 2px 12px rgba(0,0,0,0.25)',
          }}>
            <span style={{ fontSize: 16, fontWeight: 600, color: WH.text }}>
              {menuItems.find(m => m.key === currentPage)?.label || t('nav.overview')}
            </span>
            <Button
              size="small"
              icon={<TranslationOutlined />}
              onClick={toggleLocale}
              style={{ color: WH.teal, borderColor: 'rgba(100,255,218,0.35)', background: 'transparent' }}
            >
              {t('lang.switch')}
            </Button>
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
    <I18nProvider>
      <TaskStatusProvider>
        <AppContent />
      </TaskStatusProvider>
    </I18nProvider>
  )
}

export default App
