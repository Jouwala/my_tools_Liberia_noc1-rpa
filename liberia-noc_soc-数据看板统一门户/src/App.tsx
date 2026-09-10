import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import {
  CATEGORY_ALL,
  CategoryType,
  DashboardItem,
  PlatformType,
  SortOption,
  ViewMode,
} from './types/dashboard';
import { DEFAULT_GROUPS, INITIAL_DASHBOARDS } from './data/initialDashboards';
import {
  addGroup,
  deleteGroup,
  deriveGroups,
  dropGroupLabel,
  groupDisplayName,
  renameGroup,
  renameGroupLabel,
  reorderGroups,
  sanitizeGroupLabels,
  sanitizeGroups,
  setGroupLabel,
  type GroupLabels,
  type GroupReorderResult,
} from './utils/groups';
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
import { GroupManagerModal, type GroupOpFeedback } from './components/GroupManagerModal';
import { PORTAL_API, saveEnvConfig, resolveUrl, buildRel, getMyappHost, type EnvConfig } from './config';
import { useI18n, translateDashboard, translateCategory } from './i18n';
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
  Move,
  Check,
  RotateCcw,
} from 'lucide-react';

const STORAGE_KEY = 'liberia_noc_dashboards_v5'; // legacy：旧版整目录存储，仅用于一次性迁移个人偏好
const PREFS_KEY = 'liberia_noc_prefs_v1';
const THEME_KEY = 'enterprise_bi_theme_dark';
const LAYOUT_ORDER_KEY = 'liberia_noc_layout_order_v1';

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

function applySavedOrder(items: DashboardItem[]): DashboardItem[] {
  try {
    const saved = JSON.parse(localStorage.getItem(LAYOUT_ORDER_KEY) || '[]') as string[];
    if (!Array.isArray(saved) || saved.length === 0) return items;
    const rank = new Map(saved.map((id, index) => [id, index]));
    return [...items].sort((a, b) => (rank.get(a.id) ?? Number.MAX_SAFE_INTEGER) - (rank.get(b.id) ?? Number.MAX_SAFE_INTEGER));
  } catch {
    return items;
  }
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

/** 服务端全局默认目录：看板列表 + 分组列表 + 分组英文标签
 *  （groups 为 null 表示旧版纯数组格式，需从卡片 category 推导） */
interface ServerCatalog {
  dashboards: DashboardItem[];
  groups: string[] | null;
  groupLabels: GroupLabels;
}

/**
 * 从服务端加载全局默认目录（本机 localhost:9267 「保存为默认目录」写入的
 * portal-default.json）。未保存过（404）或网络异常时返回 null，由调用方回退到内置目录。
 * 兼容两种格式：旧版纯 DashboardItem[] 数组 / 新版 { version, groups, dashboards } 对象。
 */
async function fetchServerDefault(): Promise<ServerCatalog | null> {
  try {
    const res = await fetch(`${PORTAL_API}/portal-default`);
    if (!res.ok) return null;
    const data = (await res.json()) as unknown;
    const items = Array.isArray(data)
      ? (data as DashboardItem[])
      : (data as { dashboards?: DashboardItem[] })?.dashboards;
    if (!Array.isArray(items) || items.length === 0) return null;
    const rawGroups = Array.isArray(data) ? null : (data as { groups?: unknown })?.groups;
    const groups = rawGroups == null ? null : sanitizeGroups(rawGroups);
    const rawLabels = Array.isArray(data) ? undefined : (data as { groupLabels?: unknown })?.groupLabels;
    return {
      dashboards: items,
      groups,
      // 标签表以「最终生效的分组列表」为准过滤，防止改名/删组后残留脏键
      groupLabels: sanitizeGroupLabels(rawLabels, groups ?? deriveGroups(items, DEFAULT_GROUPS)),
    };
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
    applySavedOrder(applyPrefs(INITIAL_DASHBOARDS, loadPrefs()))
  );

  // 分组列表（组名是一等实体，可新增/重命名/删除；卡片只存组名 category）。
  // 与目录同源：随服务端 portal-default.json 的 groups 字段全局下发。
  const [groups, setGroups] = useState<string[]>(() =>
    deriveGroups(INITIAL_DASHBOARDS, DEFAULT_GROUPS)
  );

  // 分组英文标签（key = 分组规范名）。内置分组的英文名仍在 i18n 字典里，
  // 这里只存「运行时新增/改名」的分组标签，避免两处真相源打架。
  const [groupLabels, setGroupLabels] = useState<GroupLabels>({});

  // 挂载后拉取服务端默认目录覆盖本页（首次渲染先用内置目录避免白屏）
  useEffect(() => {
    let cancelled = false;
    fetchServerDefault().then((catalog) => {
      if (cancelled || !catalog) return;
      setDashboards(
        applySavedOrder(applyPrefs(normalizeCatalogItems(catalog.dashboards), loadPrefs()))
      );
      const nextGroups = deriveGroups(catalog.dashboards, catalog.groups ?? DEFAULT_GROUPS);
      setGroups(nextGroups);
      setGroupLabels(sanitizeGroupLabels(catalog.groupLabels, nextGroups));
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

  const [selectedCategory, setSelectedCategory] = useState<CategoryType>(CATEGORY_ALL);
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

  // 当前选中的分组被重命名/删除后，自动回到「全部」，避免停留在不存在的分组上看到空列表
  useEffect(() => {
    if (selectedCategory !== CATEGORY_ALL && !groups.includes(selectedCategory)) {
      setSelectedCategory(CATEGORY_ALL);
    }
  }, [groups, selectedCategory]);
  const [onlyFavorites, setOnlyFavorites] = useState(false);
  const [showHidden, setShowHidden] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortOption, setSortOption] = useState<SortOption>('pinned');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');
  const [isLayoutEditing, setIsLayoutEditing] = useState(false);
  const [hasCustomLayout, setHasCustomLayout] = useState(() => localStorage.getItem(LAYOUT_ORDER_KEY) !== null);
  const [draggedDashboardId, setDraggedDashboardId] = useState<string | null>(null);

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [dashboardToEdit, setDashboardToEdit] = useState<DashboardItem | null>(null);
  const [isEndpointModalOpen, setIsEndpointModalOpen] = useState(false);
  const [isDesignGuideModalOpen, setIsDesignGuideModalOpen] = useState(false);
  const [previewDashboard, setPreviewDashboard] = useState<DashboardItem | null>(null);
  const [qrDashboard, setQrDashboard] = useState<DashboardItem | null>(null);
  const [isChangePasswordOpen, setIsChangePasswordOpen] = useState(false);
  const [isUserManagementOpen, setIsUserManagementOpen] = useState(false);
  const [isGroupManagerOpen, setIsGroupManagerOpen] = useState(false);

  // —— 登录后落地页（管理员在「用户管理 → 页面配置」里为账号指定）——
  // 会话确认后执行一次：先切视图，再定位目标卡片（滚动过去并高亮）。
  // 外部页面不自动 window.open —— 非用户手势的弹窗会被浏览器拦截，
  // 因此只做定位与提示，由用户自己点击进入。
  const landingAppliedRef = useRef<string | null>(null);
  const [highlightedId, setHighlightedId] = useState<string | null>(null);

  useEffect(() => {
    if (status !== 'authed' || !user) return;
    const target = user.landing;
    if (!target || (!target.view && !target.cardId)) return;
    // 同一账号 + 同一目标只应用一次（否则用户手动切视图后会被反复拉回）
    const key = `${user.id}:${target.view || ''}:${target.cardId || ''}`;
    if (landingAppliedRef.current === key) return;
    landingAppliedRef.current = key;
    if (target.view) setViewMode(target.view);
    if (target.cardId && dashboards.some((d) => d.id === target.cardId)) {
      setSelectedCategory(CATEGORY_ALL);
      setSelectedPlatform('all');
      setOnlyFavorites(false);
      setShowHidden(false);
      setSearchQuery('');
      setHighlightedId(target.cardId);
      window.setTimeout(() => {
        document
          .querySelector(`[data-dashboard-id="${target.cardId}"]`)
          ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 300);
    }
  }, [status, user, dashboards]);

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

  const persistLayoutOrder = (items: DashboardItem[]) => {
    localStorage.setItem(LAYOUT_ORDER_KEY, JSON.stringify(items.map((item) => item.id)));
  };

  const handleCardDrop = (targetId: string) => {
    if (!draggedDashboardId || draggedDashboardId === targetId) return;
    setDashboards((prev) => {
      const next = [...prev];
      const from = next.findIndex((item) => item.id === draggedDashboardId);
      const to = next.findIndex((item) => item.id === targetId);
      if (from < 0 || to < 0) return prev;
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      persistLayoutOrder(next);
      setHasCustomLayout(true);
      return next;
    });
    setDraggedDashboardId(null);
  };

  const handleResetLayout = () => {
    localStorage.removeItem(LAYOUT_ORDER_KEY);
    setHasCustomLayout(false);
    setDashboards((prev) => [...prev].sort((a, b) => {
      if (a.isPinned !== b.isPinned) return a.isPinned ? -1 : 1;
      return b.clickCount - a.clickCount;
    }));
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
    // 兜底：卡片选中的分组若尚未登记（如从旧 JSON 导入），补进分组列表
    setGroups((prev) => (prev.includes(item.category) ? prev : [...prev, item.category]));
  };

  // —— 分组管理（新增 / 重命名 / 删除）——
  // 重命名与删除都会就地改写受影响卡片的 category，卡片与分组的关联随组名一起走，
  // 不会出现「卡片挂在已不存在的分组上」而在任何分组视图里都看不到的情况。

  /**
   * 分组改名/删除后，同步迁移各账号「页面配置」里的旧组名。
   * 不迁的后果：被授权的账号白名单里挂着已不存在的组名 → 登录后看到空目录。
   * 迁移失败不阻塞本地分组操作（管理员下次保存页面配置时会重新对齐）。
   */
  const remapGroupAccess = (from: string, to: string | null) => {
    if (user?.role !== 'admin') return;
    void apiFetch(`${PORTAL_API}/auth/users/remap-group`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from, to }),
    }).catch(() => undefined);
  };

  const handleAddGroup = (name: string, enLabel = ''): GroupOpFeedback => {
    const result = addGroup(groups, name, dashboards);
    if (result.ok) {
      setGroups(result.groups);
      const added = result.groups[result.groups.length - 1];
      setGroupLabels((prev) => setGroupLabel(prev, added, enLabel));
    }
    return { ok: result.ok, error: result.error, moved: result.moved };
  };

  const handleRenameGroup = (oldName: string, newName: string, enLabel = ''): GroupOpFeedback => {
    const result = renameGroup(groups, dashboards, oldName, newName);
    if (result.ok) {
      setGroups(result.groups);
      setDashboards(result.dashboards);
      // 标签随组名一起搬移：旧键删除、新键写入，中英文界面同时生效
      setGroupLabels((prev) =>
        renameGroupLabel(prev, oldName, newName.trim() || oldName, enLabel)
      );
      // 各账号页面配置里的旧组名同步换成新组名
      remapGroupAccess(oldName, newName.trim() || oldName);
    }
    return { ok: result.ok, error: result.error, moved: result.moved };
  };

  const handleDeleteGroup = (name: string): GroupOpFeedback => {
    const result = deleteGroup(groups, dashboards, name);
    if (result.ok) {
      setGroups(result.groups);
      setDashboards(result.dashboards);
      setGroupLabels((prev) => dropGroupLabel(prev, name));
      // 分组被删除：从各账号白名单里摘掉该组名（取最小权限，不顺手放开兜底分组）
      remapGroupAccess(name, null);
    }
    return { ok: result.ok, error: result.error, moved: result.moved, fallback: result.fallback };
  };

  // —— 分组排序：只改 groups 数组顺序，不动任何卡片 ——
  // 顺序是全局目录的一部分（FilterBar Tab / 矩阵分组块 / 卡片编辑弹窗下拉都按它渲染），
  // 与其他分组操作一样：本机立即生效，「保存为默认目录」后下发到所有电脑。
  const handleReorderGroup = (from: number, to: number): GroupReorderResult => {
    const result = reorderGroups(groups, from, to);
    if (result.ok) setGroups(result.groups);
    return result;
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
    // v2 结构：连同分组列表一起导出，空分组（暂无卡片的组）也不丢
    const payload = {
      version: 2,
      exportedAt: new Date().toISOString(),
      groups,
      groupLabels,
      dashboards: clean,
    };
    const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(payload, null, 2));
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
        const parsed = JSON.parse(event.target?.result as string) as unknown;
        // 兼容两种导入格式：v2 对象 { groups, dashboards } 与旧版纯数组
        const items = Array.isArray(parsed)
          ? (parsed as DashboardItem[])
          : ((parsed as { dashboards?: DashboardItem[] })?.dashboards as DashboardItem[] | undefined);
        if (Array.isArray(items)) {
          const rawGroups = Array.isArray(parsed)
            ? undefined
            : (parsed as { groups?: unknown }).groups;
          const rawLabels = Array.isArray(parsed)
            ? undefined
            : (parsed as { groupLabels?: unknown }).groupLabels;
          // 文件里带了分组列表就用它（空分组也保留），否则用内置默认分组兜底
          const seeds = Array.isArray(rawGroups) ? sanitizeGroups(rawGroups) : DEFAULT_GROUPS;
          const nextGroups = deriveGroups(items, seeds);
          setDashboards(items);
          setGroups(nextGroups);
          setGroupLabels(sanitizeGroupLabels(rawLabels, nextGroups));
          alert(t('app.importOk', { n: items.length }));
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
      // 有服务端默认目录则恢复它，否则恢复内置目录；分组同步恢复
      const serverDefault = await fetchServerDefault();
      if (serverDefault) {
        const nextGroups = deriveGroups(serverDefault.dashboards, serverDefault.groups ?? DEFAULT_GROUPS);
        setDashboards(applyPrefs(normalizeCatalogItems(serverDefault.dashboards), loadPrefs()));
        setGroups(nextGroups);
        setGroupLabels(sanitizeGroupLabels(serverDefault.groupLabels, nextGroups));
      } else {
        setDashboards(applyPrefs(INITIAL_DASHBOARDS, loadPrefs()));
        setGroups(deriveGroups(INITIAL_DASHBOARDS, DEFAULT_GROUPS));
        setGroupLabels({});
      }
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
        // v2 结构：分组列表与看板一起落盘，重命名/新增的分组随之全局生效
        body: JSON.stringify({
          version: 2,
          savedAt: new Date().toISOString(),
          groups,
          groupLabels,
          dashboards: stripPersonalFlags(dashboards),
        }),
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

  // —— 页面级可见范围（管理员在「用户管理 → 页面配置」里按账号下发）——
  // allowedGroups / allowedCards 同时为 null = 不限制（老账号行为完全不变）；
  // 只要配置了任一维度就按白名单裁剪：命中分组或命中卡片即可见。
  // 注意：这是「导航可见性」，不是访问控制——被裁剪的看板仍可通过直链访问。
  const accessRestricted = user?.allowedGroups != null || user?.allowedCards != null;
  const allowedGroups = user?.allowedGroups;
  const allowedCards = user?.allowedCards;
  const canSeeDashboard = useCallback(
    (item: DashboardItem) => {
      if (!accessRestricted) return true;
      if (allowedGroups?.includes(item.category)) return true;
      if (allowedCards?.includes(item.id)) return true;
      return false;
    },
    [accessRestricted, allowedGroups, allowedCards]
  );

  const filteredDashboards = useMemo(() => {
    return dashboards
      .filter((board) => {
        // 页面可见范围白名单（管理员按账号配置）
        if (!canSeeDashboard(board)) {
          return false;
        }
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
        if (isLayoutEditing || hasCustomLayout) return 0;
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
  }, [dashboards, selectedCategory, selectedPlatform, onlyFavorites, showHidden, searchQuery, sortOption, isLayoutEditing, hasCustomLayout, canSeeDashboard]);

  // 分组名按当前语言取显示值：zh 用规范名；en 先查运行时标签，再查内置 i18n 字典。
  // 这样「重命名」中英文一起生效，不会出现英文界面显示中文分组名。
  const labelOf = useCallback(
    (name: string) =>
      groupDisplayName(name, lang, groupLabels, (n) => translateCategory(n, lang, t)),
    [lang, groupLabels, t]
  );
  /** 英文名（供分组管理弹窗回填编辑框） */
  const labelOfEn = useCallback(
    (name: string) => groupDisplayName(name, 'en', groupLabels, (n) => translateCategory(n, 'en', t)),
    [groupLabels, t]
  );

  // 卡片的 category 也必须走 labelOf：translateDashboard 只会查内置 cat.* 字典，
  // 重命名/新增的自定义分组名查不到会回退成中文，导致英文界面下矩阵视图标题仍是中文。
  const translatedDashboards = useMemo(() => {
    return filteredDashboards.map((d) => ({
      ...translateDashboard(d, lang, t),
      category: labelOf(d.category),
    }));
  }, [filteredDashboards, lang, t, labelOf]);

  // 矩阵视图按分组渲染，分组名与 translatedDashboards.category 必须同源（都走 labelOf）
  const translatedGroups = useMemo(() => groups.map(labelOf), [groups, labelOf]);

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
    <div className="app-spatial-root min-h-screen bg-slate-100/60 dark:bg-navy-950 text-slate-900 dark:text-slate-100 flex flex-col font-sans transition-colors duration-200">
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
          groups={groups}
          labelOf={labelOf}
          onManageGroups={() => setIsGroupManagerOpen(true)}
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
          onSortChange={(sort) => {
            setSortOption(sort);
            localStorage.removeItem(LAYOUT_ORDER_KEY);
            setHasCustomLayout(false);
          }}
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
          <section className="dashboard-layout-shell">
            <div className="layout-toolbar liquid-glass-panel">
              <div>
                <p className="layout-toolbar-title">空间布局</p>
                <p className="layout-toolbar-hint">{isLayoutEditing ? '拖动卡片到目标位置，布局会自动保存在当前浏览器' : '开启后可自由调整卡片顺序'}</p>
              </div>
              <div className="flex items-center gap-2">
                {isLayoutEditing && (
                  <button onClick={handleResetLayout} className="layout-secondary-button">
                    <RotateCcw className="w-3.5 h-3.5" />恢复默认
                  </button>
                )}
                <button
                  onClick={() => { setIsLayoutEditing((value) => !value); setDraggedDashboardId(null); }}
                  className={`layout-edit-button ${isLayoutEditing ? 'is-active' : ''}`}
                >
                  {isLayoutEditing ? <Check className="w-4 h-4" /> : <Move className="w-4 h-4" />}
                  {isLayoutEditing ? '完成布局' : '编辑布局'}
                </button>
              </div>
            </div>
            <div className={`dashboard-grid ${isLayoutEditing ? 'is-editing' : ''}`}>
            {translatedDashboards.map((dashboard) => (
              <div
                key={dashboard.id}
                data-dashboard-id={dashboard.id}
                draggable={isLayoutEditing}
                onDragStart={() => setDraggedDashboardId(dashboard.id)}
                onDragOver={(event) => { if (isLayoutEditing) event.preventDefault(); }}
                onDrop={() => handleCardDrop(dashboard.id)}
                onDragEnd={() => setDraggedDashboardId(null)}
                className={`dashboard-grid-item ${draggedDashboardId === dashboard.id ? 'is-dragging' : ''} ${
                  highlightedId === dashboard.id
                    ? 'rounded-3xl ring-2 ring-teal-500/70 ring-offset-2 ring-offset-transparent'
                    : ''
                }`}
              >
              <DashboardCard
                dashboard={dashboard}
                isLayoutEditing={isLayoutEditing}
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
              </div>
            ))}
            </div>
          </section>
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
            groups={translatedGroups}
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
        groups={groups}
        labelOf={labelOf}
      />

      <GroupManagerModal
        isOpen={isGroupManagerOpen}
        onClose={() => setIsGroupManagerOpen(false)}
        groups={groups}
        dashboards={dashboards}
        onAdd={handleAddGroup}
        onRename={handleRenameGroup}
        onDelete={handleDeleteGroup}
        onReorder={handleReorderGroup}
        labelOfEn={labelOfEn}
        canSaveDefault={canSaveDefault}
        onSaveDefault={() => void handleSaveDefault()}
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
        groups={groups}
        dashboards={dashboards}
        labelOf={labelOf}
      />
    </div>
  );
}
