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
import WhatsAppTasksView from './components/WhatsAppTasksView';
import { DashboardModal } from './components/DashboardModal';
import { EndpointSettingsModal } from './components/EndpointSettingsModal';
import { PreviewDrawer } from './components/PreviewDrawer';
import { QRCodeModal } from './components/QRCodeModal';
import { DesignGuideModal } from './components/DesignGuideModal';
import { LoginView } from './components/LoginView';
import { ChangePasswordModal } from './components/ChangePasswordModal';
import { UserManagementModal } from './components/UserManagementModal';
import { PORTAL_API, saveEnvConfig, resolveUrl, buildRel, getMyappHost, type EnvConfig } from './config';
import { useI18n, translateDashboard } from './i18n';
import { useAuth } from './auth/AuthContext';
import {
  Layers,
  Plus,
  Compass,
  AlertCircle,
  HelpCircle,
  ExternalLink,
  Lightbulb,
  Loader2,
} from 'lucide-react';

const STORAGE_KEY = 'liberia_noc_dashboards_v5'; // legacy：旧版整目录存储，仅用于一次性迁移个人偏好
const PREFS_KEY = 'liberia_noc_prefs_v1';
const THEME_KEY = 'enterprise_bi_theme_dark';

/** 个人偏好 overlay：按看板 id 记录收藏/置顶/点击数/最近访问/本机隐藏，存在各自浏览器 */
type PrefsMap = Record<
  string,
  Pick<DashboardItem, 'isFavorite' | 'isPinned' | 'clickCount' | 'lastVisited' | 'hidden'>
>;

function loadPrefs(): PrefsMap {
  const raw = localStorage.getItem(PREFS_KEY);
  if (raw) {
    try {
      return JSON.parse(raw) as PrefsMap;
    } catch (e) {
      console.error('Failed to parse saved prefs', e);
    }
  }
  // 一次性迁移：旧版把整个目录存到 STORAGE_KEY，取出其中的个人偏好字段
  const legacy = localStorage.getItem(STORAGE_KEY);
  if (legacy) {
    try {
      const arr = JSON.parse(legacy) as DashboardItem[];
      const prefs: PrefsMap = {};
      arr.forEach((d) => {
        if (d && d.id) {
          prefs[d.id] = {
            isFavorite: !!d.isFavorite,
            isPinned: !!d.isPinned,
            clickCount: d.clickCount || 0,
            lastVisited: d.lastVisited,
            hidden: d.hidden ? true : undefined,
          };
        }
      });
      return prefs;
    } catch (e) {
      console.error('Failed to migrate legacy dashboards', e);
    }
  }
  return {};
}

/** 把个人偏好 overlay 套到目录上（目录条目以服务端默认/内置为准） */
function applyPrefs(items: DashboardItem[], prefs: PrefsMap): DashboardItem[] {
  return items.map((d) => {
    const p = prefs[d.id];
    return p ? { ...d, ...p } : d;
  });
}

/** 目录条目规范化：确保 rel 存在并按当前环境配置重算 url（外部大屏除外），过滤残缺条目 */
function normalizeCatalogItems(items: DashboardItem[]): DashboardItem[] {
  return items
    .filter((d) => d && d.id && d.title && d.url)
    .map((d) => {
      if (d.platform === 'external') return d;
      const rel = d.rel ?? buildRel(d.platform, d.url);
      const next = { ...d, rel };
      return { ...next, url: resolveUrl(next) };
    });
}

/** 剥离个人偏好标记（如本机 hidden），生成可入库/导出的纯净目录条目 */
function stripPersonalFlags(items: DashboardItem[]): DashboardItem[] {
  return items.map((d) => {
    if (!d.hidden) return d;
    const next = { ...d };
    delete next.hidden;
    return next;
  });
}

/**
 * 从服务端加载全局默认目录（本机 localhost:9267 「保存为默认目录」写入的
 * portal-default.json）。未保存过（404）或网络异常时返回 null，由调用方回退到内置目录。
 */
async function fetchServerDefault(): Promise<DashboardItem[] | null> {
  try {
    const res = await fetch(`${PORTAL_API}/portal-default`);
    if (!res.ok) return null;
    const data = (await res.json()) as unknown;
    const items = Array.isArray(data)
      ? (data as DashboardItem[])
      : (data as { dashboards?: DashboardItem[] })?.dashboards;
    return Array.isArray(items) && items.length > 0 ? items : null;
  } catch {
    return null;
  }
}

export default function App() {
  const { t, lang } = useI18n();
  const { status, user, apiFetch, logout } = useAuth();
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

  // —— 目录模型：服务端默认目录（全局统一） + 个人偏好 overlay（各浏览器本地）——
  // 目录（有哪些卡片、标题、链接）以服务端 portal-default.json 为准：只有本机
  // http://localhost:9267/uniplam/ 上的「保存为默认目录」能写入；其他电脑通过
  // IP 访问时加载同一份，不再各自为政。未保存过时回退到内置 INITIAL_DASHBOARDS。
  const [dashboards, setDashboards] = useState<DashboardItem[]>(() =>
    applyPrefs(INITIAL_DASHBOARDS, loadPrefs())
  );

  // 挂载后拉取服务端默认目录覆盖本页（首次渲染先用内置目录避免白屏）
  useEffect(() => {
    let cancelled = false;
    fetchServerDefault().then((items) => {
      if (cancelled || !items) return;
      setDashboards(applyPrefs(normalizeCatalogItems(items), loadPrefs()));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // 只持久化个人偏好；目录本身不再写 localStorage（统一以服务端默认为准）
  useEffect(() => {
    const prefs: PrefsMap = {};
    dashboards.forEach((d) => {
      prefs[d.id] = {
        isFavorite: d.isFavorite,
        isPinned: d.isPinned,
        clickCount: d.clickCount,
        lastVisited: d.lastVisited,
        hidden: d.hidden ? true : undefined,
      };
    });
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  }, [dashboards]);

  const [selectedCategory, setSelectedCategory] = useState<CategoryType>('全部');
  const [selectedPlatform, setSelectedPlatform] = useState<'all' | PlatformType>('all');

  // 处于「WhatsApp @Me Tasks」视图时，看板过滤条件（平台/分类）并不作用于任务列表；
  // 用户点击 All Dashboards 等过滤入口却看不到任何变化，仿佛“失效”。
  // 因此：任何看板过滤操作都自动退出任务视图，切回卡片网格视图。
  const leaveTasksView = () => setViewMode((mode) => (mode === 'tasks' ? 'grid' : mode));
  const handleQuickFilterPlatform = (p: 'all' | PlatformType) => {
    setSelectedPlatform(p);
    leaveTasksView();
  };
  const handleSelectCategory = (cat: CategoryType) => {
    setSelectedCategory(cat);
    leaveTasksView();
  };
  const [onlyFavorites, setOnlyFavorites] = useState(false);
  const [showHidden, setShowHidden] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortOption, setSortOption] = useState<SortOption>('pinned');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [dashboardToEdit, setDashboardToEdit] = useState<DashboardItem | null>(null);
  const [isEndpointModalOpen, setIsEndpointModalOpen] = useState(false);
  const [isDesignGuideModalOpen, setIsDesignGuideModalOpen] = useState(false);
  const [previewDashboard, setPreviewDashboard] = useState<DashboardItem | null>(null);
  const [qrDashboard, setQrDashboard] = useState<DashboardItem | null>(null);
  const [isChangePasswordOpen, setIsChangePasswordOpen] = useState(false);
  const [isUserManagementOpen, setIsUserManagementOpen] = useState(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

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

    window.open(resolveUrl(dashboard), '_blank', 'noopener,noreferrer');
  };

  const handleToggleFavorite = (id: string) => {
    setDashboards((prev) =>
      prev.map((d) => (d.id === id ? { ...d, isFavorite: !d.isFavorite } : d))
    );
  };

  /** 本机隐藏/恢复显示：只写入本浏览器偏好，绝不影响服务端全局默认与其他电脑 */
  const handleToggleHidden = (id: string) => {
    setDashboards((prev) =>
      prev.map((d) => (d.id === id ? { ...d, hidden: !d.hidden } : d))
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

  const handleSaveEnv = (cfg: EnvConfig) => {
    saveEnvConfig(cfg);
    setDashboards((prev) =>
      prev.map((d) => {
        const rel =
          d.rel ?? (d.platform === 'external' ? undefined : buildRel(d.platform, d.url));
        const next = rel ? { ...d, rel } : d;
        return { ...next, url: resolveUrl(next) };
      })
    );
  };

  const handleExportJson = () => {
    // 导出前剥离本机 hidden 标记，避免个人隐藏状态随 JSON 备份/默认目录生成流入其他电脑
    const clean = stripPersonalFlags(dashboards);
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(clean, null, 2));
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

  const handleResetDefaults = async () => {
    if (window.confirm(t('app.confirmReset'))) {
      // 有服务端默认目录则恢复它，否则恢复内置目录
      const serverDefault = await fetchServerDefault();
      setDashboards(
        applyPrefs(
          serverDefault ? normalizeCatalogItems(serverDefault) : INITIAL_DASHBOARDS,
          loadPrefs()
        )
      );
    }
  };

  // 仅「本机（localhost / 127.0.0.1）+ 管理员」可保存全局默认目录；
  // 服务端 POST /api/portal-default 还会再次校验管理员 token 与回环来源。
  const canSaveDefault =
    user?.role === 'admin' &&
    (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1');

  /** 把当前看板目录保存为服务端全局默认（portal-default.json），其他电脑统一加载 */
  const handleSaveDefault = async () => {
    if (!window.confirm(t('app.saveDefaultConfirm'))) return;
    try {
      const res = await apiFetch(`${PORTAL_API}/portal-default`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // 保存前剥离本机 hidden 标记：隐藏是个人偏好，绝不进入服务端全局默认
        body: JSON.stringify(stripPersonalFlags(dashboards)),
      });
      if (res.ok) {
        const data = (await res.json().catch(() => null)) as { count?: number } | null;
        window.alert(t('app.saveDefaultOk', { n: data?.count ?? dashboards.length }));
      } else {
        const err = (await res.json().catch(() => null)) as { detail?: string } | null;
        window.alert(t('app.saveDefaultFail', { msg: err?.detail || `HTTP ${res.status}` }));
      }
    } catch (e) {
      window.alert(t('app.saveDefaultFail', { msg: String(e) }));
    }
  };

  const filteredDashboards = useMemo(() => {
    return dashboards
      .filter((board) => {
        // 本机隐藏的看板默认不显示（打开「显示已隐藏」开关后可见并置灰）
        if (!showHidden && board.hidden) {
          return false;
        }
        if (selectedCategory !== '全部' && board.category !== selectedCategory) {
          return false;
        }
        if (selectedPlatform !== 'all' && board.platform !== selectedPlatform) {
          return false;
        }
        if (onlyFavorites && !board.isFavorite) {
          return false;
        }
        if (searchQuery.trim()) {
          const query = searchQuery.toLowerCase().trim();
          const matchTitle = board.title.toLowerCase().includes(query);
          const matchDesc = board.description.toLowerCase().includes(query);
          const matchUrl = resolveUrl(board).toLowerCase().includes(query);
          const matchDept = board.department.toLowerCase().includes(query);
          const matchOwner = board.owner.toLowerCase().includes(query);
          const matchTags = board.tags.some((t) => t.toLowerCase().includes(query));
          return matchTitle || matchDesc || matchUrl || matchDept || matchOwner || matchTags;
        }
        return true;
      })
      .sort((a, b) => {
        if (sortOption === 'pinned') {
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
  }, [dashboards, selectedCategory, selectedPlatform, onlyFavorites, showHidden, searchQuery, sortOption]);

  const translatedDashboards = useMemo(() => {
    return filteredDashboards.map((d) => translateDashboard(d, lang, t));
  }, [filteredDashboards, lang, t]);

  // —— 鉴权门：未登录只能看到登录页 ——
  if (status === 'loading') {
    return (
      <div className="min-h-screen bg-slate-100/60 dark:bg-navy-950 text-slate-500 dark:text-slate-400 flex flex-col items-center justify-center gap-3 font-sans">
        <Loader2 className="w-6 h-6 animate-spin text-teal-500" />
        <span className="text-xs">{t('app.loading')}</span>
      </div>
    );
  }
  if (status === 'anon' || !user) {
    return <LoginView />;
  }

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
        onOpenEnvironmentModal={() => setIsEndpointModalOpen(true)}
        onOpenDesignGuideModal={() => setIsDesignGuideModalOpen(true)}
        onExportJson={handleExportJson}
        onImportJson={handleImportJson}
        onResetDefaults={handleResetDefaults}
        canSaveDefault={canSaveDefault}
        onSaveDefault={handleSaveDefault}
        user={user}
        onChangePassword={() => setIsChangePasswordOpen(true)}
        onOpenUserManagement={() => setIsUserManagementOpen(true)}
        onLogout={() => void logout()}
      />

      {/* Main Content Area */}
      <main className="flex-1 w-full mx-auto px-3 sm:px-6 lg:px-8 xl:px-10 py-4 sm:py-6">
        {/* Quick Stats & Environment Overview */}
        <QuickStatsBar
          dashboards={dashboards}
          onQuickFilterPlatform={handleQuickFilterPlatform}
          activePlatform={selectedPlatform}
          onOpenEnvironment={() => setIsEndpointModalOpen(true)}
        />

        {/* Realtime Automated Tasks & Synchronization Widget */}
        <TaskSyncWidget />

        {/* Filter Bar */}
        <FilterBar
          selectedCategory={selectedCategory}
          onSelectCategory={handleSelectCategory}
          selectedPlatform={selectedPlatform}
          onSelectPlatform={handleQuickFilterPlatform}
          onlyFavorites={onlyFavorites}
          onToggleOnlyFavorites={() => {
            setOnlyFavorites(!onlyFavorites);
            leaveTasksView();
          }}
          showHidden={showHidden}
          onToggleShowHidden={() => setShowHidden(!showHidden)}
          hiddenCount={dashboards.filter((d) => d.hidden).length}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          sortOption={sortOption}
          onSortChange={setSortOption}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          totalFilteredCount={translatedDashboards.length}
        />

        {/* Main Content Body: Grid, List, Matrix or WhatsApp Tasks */}
        {viewMode === 'tasks' ? (
          <WhatsAppTasksView />
        ) : translatedDashboards.length === 0 ? (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-3xl p-8 sm:p-12 text-center shadow-sm my-6 sm:my-8">
            <div className="w-12 h-12 sm:w-14 sm:h-14 mx-auto rounded-2xl bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-400 flex items-center justify-center mb-3 sm:mb-4">
              <Layers className="w-6 h-6 sm:w-7 sm:h-7" />
            </div>
            <h3 className="text-base sm:text-lg font-bold text-slate-800 dark:text-slate-200 mb-1">
              {t('app.emptyTitle')}
            </h3>
            <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 max-w-md mx-auto mb-4 sm:mb-5">
              {t('app.emptyDesc')}
            </p>
            <div className="flex flex-col sm:flex-row items-center justify-center gap-2 sm:gap-3">
              <button
                onClick={() => {
                  setSelectedCategory('全部');
                  setSelectedPlatform('all');
                  setOnlyFavorites(false);
                  setSearchQuery('');
                }}
                className="w-full sm:w-auto px-4 py-2 text-xs sm:text-sm font-medium rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
              >
                {t('app.emptyReset')}
              </button>
              <button
                onClick={() => {
                  setDashboardToEdit(null);
                  setIsModalOpen(true);
                }}
                className="w-full sm:w-auto px-4 py-2 text-xs sm:text-sm font-semibold rounded-xl bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 text-white shadow-sm transition-all"
              >
                {t('app.emptyAdd')}
              </button>
            </div>
          </div>
        ) : viewMode === 'grid' ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4 sm:gap-5">
            {translatedDashboards.map((dashboard) => (
              <DashboardCard
                key={dashboard.id}
                dashboard={dashboard}
                onOpen={handleOpenDashboard}
                onPreview={(d) => setPreviewDashboard(d)}
                onShowQR={(d) => setQrDashboard(d)}
                onToggleFavorite={handleToggleFavorite}
                onToggleHidden={handleToggleHidden}
                onEdit={(d) => {
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
            onToggleHidden={handleToggleHidden}
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
      <footer className="border-t border-slate-200/90 dark:border-slate-800/90 bg-white/70 dark:bg-slate-900/70 backdrop-blur-md py-3 sm:py-4 mt-8 sm:mt-12 text-xs text-slate-500 dark:text-slate-400">
        <div className="w-full mx-auto px-3 sm:px-6 lg:px-8 xl:px-10 flex flex-col sm:flex-row items-center justify-between gap-2 sm:gap-3">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-700 dark:text-slate-300">
              {t('app.title')}
            </span>
            <span>·</span>
            <span>{t('app.footerCount', { n: dashboards.length })}</span>
          </div>

          <div className="flex items-center gap-3 sm:gap-4">
            <button
              onClick={() => setIsDesignGuideModalOpen(true)}
              className="text-teal-600 dark:text-teal-400 hover:underline flex items-center gap-1 font-medium"
            >
              <Lightbulb className="w-3.5 h-3.5" />
              {t('app.footerGuide')}
            </button>
            <span>·</span>
            <span className="font-mono text-[11px] text-slate-400">
              {t('app.footerHost')}: {getMyappHost()}
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

      <EndpointSettingsModal
        isOpen={isEndpointModalOpen}
        onClose={() => setIsEndpointModalOpen(false)}
        onSave={handleSaveEnv}
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

      {/* Auth: forced password change gate (initial/reset password) */}
      {user.mustChangePassword && (
        <ChangePasswordModal isOpen onClose={() => {}} forced />
      )}

      <ChangePasswordModal
        isOpen={isChangePasswordOpen && !user.mustChangePassword}
        onClose={() => setIsChangePasswordOpen(false)}
      />

      <UserManagementModal
        isOpen={isUserManagementOpen && user.role === 'admin'}
        onClose={() => setIsUserManagementOpen(false)}
      />
    </div>
  );
}
