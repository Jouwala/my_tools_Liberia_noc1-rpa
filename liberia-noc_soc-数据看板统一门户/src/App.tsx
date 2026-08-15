import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  CategoryType,
  DashboardItem,
  PlatformType,
  SortOption,
  ViewMode,
} from './types/dashboard';
import { INITIAL_DASHBOARDS } from './data/initialDashboards';
import { Navbar } from './components/Navbar';
import { AnnouncementBanner } from './components/AnnouncementBanner';
import { QuickStatsBar } from './components/QuickStatsBar';
import { TaskSyncWidget } from './components/TaskSyncWidget';
import { FilterBar } from './components/FilterBar';
import { DashboardCard } from './components/DashboardCard';
import { DashboardListView } from './components/DashboardListView';
import { DashboardMatrixView } from './components/DashboardMatrixView';
import { DashboardModal } from './components/DashboardModal';
import { EnvironmentModal } from './components/EnvironmentModal';
import { PreviewDrawer } from './components/PreviewDrawer';
import { QRCodeModal } from './components/QRCodeModal';
import { DesignGuideModal } from './components/DesignGuideModal';
import { DEFAULT_HOST } from './config';
import { useI18n, translateDashboard } from './i18n';
import {
  Layers,
  Plus,
  Compass,
  AlertCircle,
  HelpCircle,
  ExternalLink,
  Lightbulb,
} from 'lucide-react';

// v3：看板目录按 my_app 真实页面重新填充，旧版本缓存需要失效重读
const STORAGE_KEY = 'liberia_noc_dashboards_v3';
const THEME_KEY = 'enterprise_bi_theme_dark';

export default function App() {
  const { t, lang } = useI18n();
  // 1. Theme State (Dark / Light)，默认深色 NOC 值班风格（对齐 Data Insight MVP）
  const [darkMode, setDarkMode] = useState<boolean>(() => {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved !== null) {
      return saved === 'true';
    }
    return true;
  });

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
    localStorage.setItem(THEME_KEY, String(darkMode));
  }, [darkMode]);

  // 2. Dashboards Data
  const [dashboards, setDashboards] = useState<DashboardItem[]>(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      try {
        return JSON.parse(saved);
      } catch (e) {
        console.error('Failed to parse saved dashboards', e);
      }
    }
    return INITIAL_DASHBOARDS;
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(dashboards));
  }, [dashboards]);

  // 3. Filter & View States
  const [selectedCategory, setSelectedCategory] = useState<CategoryType>('全部');
  const [selectedPlatform, setSelectedPlatform] = useState<'all' | PlatformType>('all');
  const [onlyFavorites, setOnlyFavorites] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortOption, setSortOption] = useState<SortOption>('pinned');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');

  // 4. Modals State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [dashboardToEdit, setDashboardToEdit] = useState<DashboardItem | null>(null);
  const [isEnvironmentModalOpen, setIsEnvironmentModalOpen] = useState(false);
  const [isDesignGuideModalOpen, setIsDesignGuideModalOpen] = useState(false);
  const [previewDashboard, setPreviewDashboard] = useState<DashboardItem | null>(null);
  const [qrDashboard, setQrDashboard] = useState<DashboardItem | null>(null);

  // File input ref for import JSON
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // 5. Actions
  const handleOpenDashboard = (dashboard: DashboardItem) => {
    const now = new Date();
    const formatted = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(
      now.getDate()
    ).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(
      now.getMinutes()
    ).padStart(2, '0')}`;

    setDashboards((prev) =>
      prev.map((d) =>
        d.id === dashboard.id
          ? {
              ...d,
              clickCount: d.clickCount + 1,
              lastVisited: formatted,
            }
          : d
      )
    );

    window.open(dashboard.url, '_blank', 'noopener,noreferrer');
  };

  const handleToggleFavorite = (id: string) => {
    setDashboards((prev) =>
      prev.map((d) => (d.id === id ? { ...d, isFavorite: !d.isFavorite } : d))
    );
  };

  const handleDeleteDashboard = (id: string) => {
    if (window.confirm(t('app.confirmDelete'))) {
      setDashboards((prev) => prev.filter((d) => d.id !== id));
    }
  };

  const handleSaveDashboard = (item: DashboardItem) => {
    setDashboards((prev) => {
      const exists = prev.some((d) => d.id === item.id);
      if (exists) {
        return prev.map((d) => (d.id === item.id ? item : d));
      }
      return [item, ...prev];
    });
  };

  const handleBatchUpdateUrls = (oldHost: string, newHost: string) => {
    setDashboards((prev) =>
      prev.map((d) => ({
        ...d,
        url: d.url.replace(oldHost, newHost),
      }))
    );
  };

  const handleExportJson = () => {
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(dashboards, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', dataStr);
    downloadAnchor.setAttribute('download', `enterprise-bi-dashboards-${Date.now()}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  const handleImportJson = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const parsed = JSON.parse(event.target?.result as string);
        if (Array.isArray(parsed)) {
          setDashboards(parsed);
          alert(t('app.importOk', { n: parsed.length }));
        }
      } catch (err) {
        alert(t('app.importErr'));
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  const handleResetDefaults = () => {
    if (window.confirm(t('app.confirmReset'))) {
      setDashboards(INITIAL_DASHBOARDS);
    }
  };

  // 6. Filter & Sort Computation
  const filteredDashboards = useMemo(() => {
    return dashboards
      .filter((board) => {
        // Category filter
        if (selectedCategory !== '全部' && board.category !== selectedCategory) {
          return false;
        }
        // Platform filter
        if (selectedPlatform !== 'all' && board.platform !== selectedPlatform) {
          return false;
        }
        // Favorites filter
        if (onlyFavorites && !board.isFavorite) {
          return false;
        }
        // Search filter
        if (searchQuery.trim()) {
          const query = searchQuery.toLowerCase().trim();
          const matchTitle = board.title.toLowerCase().includes(query);
          const matchDesc = board.description.toLowerCase().includes(query);
          const matchUrl = board.url.toLowerCase().includes(query);
          const matchDept = board.department.toLowerCase().includes(query);
          const matchOwner = board.owner.toLowerCase().includes(query);
          const matchTags = board.tags.some((t) => t.toLowerCase().includes(query));
          return matchTitle || matchDesc || matchUrl || matchDept || matchOwner || matchTags;
        }
        return true;
      })
      .sort((a, b) => {
        if (sortOption === 'pinned') {
          // Pinned first, then favorites, then clicks
          if (a.isPinned !== b.isPinned) return a.isPinned ? -1 : 1;
          if (a.isFavorite !== b.isFavorite) return a.isFavorite ? -1 : 1;
          return b.clickCount - a.clickCount;
        }
        if (sortOption === 'popular') {
          return b.clickCount - a.clickCount;
        }
        if (sortOption === 'recent') {
          const timeA = a.lastVisited ? new Date(a.lastVisited).getTime() : 0;
          const timeB = b.lastVisited ? new Date(b.lastVisited).getTime() : 0;
          return timeB - timeA;
        }
        if (sortOption === 'name') {
          return a.title.localeCompare(b.title, 'zh-CN');
        }
        return 0;
      });
  }, [dashboards, selectedCategory, selectedPlatform, onlyFavorites, searchQuery, sortOption]);

  // Translate dashboards for display (keep original in state for storage)
  const translatedDashboards = useMemo(() => {
    return filteredDashboards.map((d) => translateDashboard(d, lang, t));
  }, [filteredDashboards, lang, t]);

  return (
    <div className="min-h-screen bg-slate-100/60 dark:bg-navy-950 text-slate-900 dark:text-slate-100 flex flex-col font-sans transition-colors duration-200">
      {/* Hidden File Input for JSON import */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        accept=".json"
        className="hidden"
      />

      {/* Top Banner */}
      <AnnouncementBanner />

      {/* Main Navbar */}
      <Navbar
        darkMode={darkMode}
        onToggleDarkMode={() => setDarkMode(!darkMode)}
        onOpenAddModal={() => {
          setDashboardToEdit(null);
          setIsModalOpen(true);
        }}
        onOpenEnvironmentModal={() => setIsEnvironmentModalOpen(true)}
        onOpenDesignGuideModal={() => setIsDesignGuideModalOpen(true)}
        onExportJson={handleExportJson}
        onImportJson={handleImportJson}
        onResetDefaults={handleResetDefaults}
      />

      {/* Main Content Area */}
      <main className="flex-1 w-full mx-auto px-4 sm:px-6 lg:px-8 xl:px-10 py-6">
        {/* Quick Stats & Environment Overview */}
        <QuickStatsBar
          dashboards={dashboards}
          onQuickFilterPlatform={(p) => setSelectedPlatform(p)}
          activePlatform={selectedPlatform}
          onOpenEnvironment={() => setIsEnvironmentModalOpen(true)}
        />

        {/* Realtime Automated Tasks & Synchronization Widget */}
        <TaskSyncWidget />

        {/* Filter Bar */}
        <FilterBar
          selectedCategory={selectedCategory}
          onSelectCategory={setSelectedCategory}
          selectedPlatform={selectedPlatform}
          onSelectPlatform={setSelectedPlatform}
          onlyFavorites={onlyFavorites}
          onToggleOnlyFavorites={() => setOnlyFavorites(!onlyFavorites)}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          sortOption={sortOption}
          onSortChange={setSortOption}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          totalFilteredCount={translatedDashboards.length}
        />

        {/* Main Content Body: Grid, List or Matrix */}
        {translatedDashboards.length === 0 ? (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-3xl p-12 text-center shadow-sm my-8">
            <div className="w-14 h-14 mx-auto rounded-2xl bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-400 flex items-center justify-center mb-4">
              <Layers className="w-7 h-7" />
            </div>
            <h3 className="text-base font-bold text-slate-800 dark:text-slate-200 mb-1">
              {t('app.emptyTitle')}
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 max-w-md mx-auto mb-5">
              {t('app.emptyDesc')}
            </p>
            <div className="flex items-center justify-center gap-3">
              <button
                onClick={() => {
                  setSelectedCategory('全部');
                  setSelectedPlatform('all');
                  setOnlyFavorites(false);
                  setSearchQuery('');
                }}
                className="px-4 py-2 text-xs font-medium rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
              >
                {t('app.emptyReset')}
              </button>
              <button
                onClick={() => {
                  setDashboardToEdit(null);
                  setIsModalOpen(true);
                }}
                className="px-4 py-2 text-xs font-semibold rounded-xl bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 text-white shadow-sm transition-all"
              >
                {t('app.emptyAdd')}
              </button>
            </div>
          </div>
        ) : viewMode === 'grid' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-5">
            {translatedDashboards.map((dashboard) => (
              <DashboardCard
                key={dashboard.id}
                dashboard={dashboard}
                onOpen={handleOpenDashboard}
                onPreview={(d) => setPreviewDashboard(d)}
                onShowQR={(d) => setQrDashboard(d)}
                onToggleFavorite={handleToggleFavorite}
                onEdit={(d) => {
                  // Find original dashboard for editing
                  const original = dashboards.find((orig) => orig.id === d.id);
                  if (original) {
                    setDashboardToEdit(original);
                    setIsModalOpen(true);
                  }
                }}
                onDelete={handleDeleteDashboard}
              />
            ))}
          </div>
        ) : viewMode === 'list' ? (
          <DashboardListView
            dashboards={translatedDashboards}
            onOpen={handleOpenDashboard}
            onPreview={(d) => setPreviewDashboard(d)}
            onShowQR={(d) => setQrDashboard(d)}
            onToggleFavorite={handleToggleFavorite}
            onEdit={(d) => {
              const original = dashboards.find((orig) => orig.id === d.id);
              if (original) {
                setDashboardToEdit(original);
                setIsModalOpen(true);
              }
            }}
            onDelete={handleDeleteDashboard}
          />
        ) : (
          <DashboardMatrixView
            dashboards={translatedDashboards}
            onOpen={handleOpenDashboard}
            onPreview={(d) => setPreviewDashboard(d)}
            onShowQR={(d) => setQrDashboard(d)}
            onToggleFavorite={handleToggleFavorite}
          />
        )}
      </main>

      {/* Bottom Sticky Quick Footer */}
      <footer className="border-t border-slate-200/90 dark:border-slate-800/90 bg-white/70 dark:bg-slate-900/70 backdrop-blur-md py-4 mt-12 text-xs text-slate-500 dark:text-slate-400">
        <div className="w-full mx-auto px-4 sm:px-6 lg:px-8 xl:px-10 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-700 dark:text-slate-300">
              {t('app.title')}
            </span>
            <span>·</span>
            <span>{t('app.footerCount', { n: dashboards.length })}</span>
          </div>

          <div className="flex items-center gap-4">
            <button
              onClick={() => setIsDesignGuideModalOpen(true)}
              className="text-teal-600 dark:text-teal-400 hover:underline flex items-center gap-1 font-medium"
            >
              <Lightbulb className="w-3.5 h-3.5" />
              {t('app.footerGuide')}
            </button>
            <span>·</span>
            <span className="font-mono text-[11px] text-slate-400">
              {t('app.footerHost')}: {DEFAULT_HOST}
            </span>
          </div>
        </div>
      </footer>

      {/* Modals & Drawers */}
      <DashboardModal
        isOpen={isModalOpen}
        onClose={() => {
          setIsModalOpen(false);
          setDashboardToEdit(null);
        }}
        dashboardToEdit={dashboardToEdit}
        onSave={handleSaveDashboard}
      />

      <EnvironmentModal
        isOpen={isEnvironmentModalOpen}
        onClose={() => setIsEnvironmentModalOpen(false)}
        dashboards={dashboards}
        onBatchUpdateUrls={handleBatchUpdateUrls}
      />

      <DesignGuideModal
        isOpen={isDesignGuideModalOpen}
        onClose={() => setIsDesignGuideModalOpen(false)}
      />

      <PreviewDrawer
        dashboard={previewDashboard}
        onClose={() => setPreviewDashboard(null)}
        onOpenExternal={handleOpenDashboard}
      />

      <QRCodeModal dashboard={qrDashboard} onClose={() => setQrDashboard(null)} />
    </div>
  );
}
