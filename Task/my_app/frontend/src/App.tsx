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
} from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'
import enUS from 'antd/locale/en_US'

import { I18nProvider, useI18n } from './i18n'
import { TaskStatusProvider } from './TaskStatusContext'

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

const { Header, Sider, Content } = Layout

type PageKey = 'overview' | 'tables' | 'upload' | 'dashboard' | 'alarm' | 'ttwo' | 'gis' | 'archive' | 'sync' | 'warehouse'

function AppContent() {
  const [currentPage, setCurrentPage] = useState<PageKey>('sync')
  const [collapsed, setCollapsed] = useState(false)
  const { t, locale, toggleLocale } = useI18n()

  const menuItems = [
    { key: 'sync', icon: <SyncOutlined />, label: t('nav.sync') },
    { key: 'alarm', icon: <AlertOutlined />, label: t('nav.alarm') },
    { key: 'ttwo', icon: <BarChartOutlined />, label: t('nav.ttwo') },
    { key: 'gis', icon: <GlobalOutlined />, label: t('nav.gis') },
    { key: 'warehouse', icon: <AppstoreOutlined />, label: t('nav.sp') },
    { key: 'overview', icon: <BarChartOutlined />, label: t('nav.overview') },
    { key: 'tables', icon: <TableOutlined />, label: t('nav.tables') },
    { key: 'upload', icon: <UploadOutlined />, label: t('nav.upload') },
    { key: 'archive', icon: <HistoryOutlined />, label: t('nav.archive') },
    { key: 'dashboard', icon: <DashboardOutlined />, label: t('nav.dashboard') },
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
          colorPrimary: '#1677ff',
          borderRadius: 6,
        },
      }}
    >
      <Layout style={{ minHeight: '100vh' }}>
        <Sider
          collapsible
          collapsed={collapsed}
          onCollapse={setCollapsed}
          theme="dark"
          width={200}
        >
          <div style={{
            height: 48,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontWeight: 'bold',
            fontSize: collapsed ? 14 : 16,
            borderBottom: '1px solid rgba(255,255,255,0.1)',
          }}>
            {collapsed ? t('app.titleShort') : t('app.title')}
          </div>
          <Menu
            theme="dark"
            mode="inline"
            selectedKeys={[currentPage]}
            items={menuItems}
            onClick={({ key }) => setCurrentPage(key as PageKey)}
          />
        </Sider>
        <Layout>
          <Header style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid #f0f0f0',
          }}>
            <span style={{ fontSize: 16, fontWeight: 500 }}>
              {menuItems.find(m => m.key === currentPage)?.label || t('nav.overview')}
            </span>
            <Button
              size="small"
              icon={<TranslationOutlined />}
              onClick={toggleLocale}
            >
              {t('lang.switch')}
            </Button>
          </Header>
          <Content style={{ margin: 16, padding: 4, overflow: 'auto', background: '#f5f7fa', borderRadius: 8 }}>
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
