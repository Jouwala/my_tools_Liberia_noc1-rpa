import React from 'react';
import {
  Sparkles,
  Plus,
  Server,
  Download,
  Upload,
  Moon,
  Sun,
  Lightbulb,
  Compass,
  Layers,
  RotateCcw,
  Languages,
  Menu,
  X,
  SaveAll,
  UserCircle,
  ChevronDown,
  KeyRound,
  LogOut,
  ShieldCheck,
  Users,
} from 'lucide-react';
import { useI18n } from '../i18n';
import { PORTAL_API } from '../config';
import { useAuth, type AuthUser } from '../auth/AuthContext';

interface NavbarProps {
  darkMode: boolean;
  onToggleDarkMode: () => void;
  onOpenAddModal: () => void;
  onOpenEnvironmentModal: () => void;
  onOpenDesignGuideModal: () => void;
  onExportJson: () => void;
  onImportJson: () => void;
  onResetDefaults: () => void;
  /** 仅本机（localhost / 127.0.0.1）访问且为管理员时为 true，控制「保存为默认目录」按钮显示 */
  canSaveDefault: boolean;
  onSaveDefault: () => void;
  /** 当前登录用户（登录门之后必存在） */
  user: AuthUser;
  onChangePassword: () => void;
  /** 仅 admin 展示用户管理入口 */
  onOpenUserManagement: () => void;
  onLogout: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  darkMode,
  onToggleDarkMode,
  onOpenAddModal,
  onOpenEnvironmentModal,
  onOpenDesignGuideModal,
  onExportJson,
  onImportJson,
  onResetDefaults,
  canSaveDefault,
  onSaveDefault,
  user,
  onChangePassword,
  onOpenUserManagement,
  onLogout,
}) => {
  const { t, lang, setLang } = useI18n();
  const [mobileMenuOpen, setMobileMenuOpen] = React.useState(false);
  const [userMenuOpen, setUserMenuOpen] = React.useState(false);
  const userMenuRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    if (!userMenuOpen) return;
    const onClickOutside = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, [userMenuOpen]);

  const toggleMobileMenu = () => setMobileMenuOpen(!mobileMenuOpen);
  const isAdmin = user.role === 'admin';

  /** 待审批的账号申请数：管理员菜单上挂红点，避免申请被忽略 */
  const { apiFetch } = useAuth();
  const [pendingRequests, setPendingRequests] = React.useState(0);

  React.useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    const load = async () => {
      try {
        const res = await apiFetch(`${PORTAL_API}/auth/register-requests`);
        if (!res.ok) return;
        const data = (await res.json().catch(() => null)) as { requests?: unknown[] } | null;
        if (!cancelled) setPendingRequests(Array.isArray(data?.requests) ? data.requests.length : 0);
      } catch {
        // 拉取失败不影响导航条
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 60000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [isAdmin, apiFetch]);

  /** 用户菜单：桌面下拉与移动折叠菜单共用的条目 */
  const userMenuItems = (onNavigate: () => void) => (
    <>
      <button
        onClick={() => { onChangePassword(); onNavigate(); }}
        className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs font-medium transition-colors"
      >
        <KeyRound className="w-4 h-4 text-amber-500" />
        <span>{t('nav.changePassword')}</span>
      </button>
      {isAdmin && (
        <button
          onClick={() => { onOpenUserManagement(); onNavigate(); }}
          className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs font-medium transition-colors"
        >
          <Users className="w-4 h-4 text-violet-500" />
          <span>{t('nav.userManagement')}</span>
          {pendingRequests > 0 && (
            <span
              className="ml-auto px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-500 text-white"
              title={t('ar.pendingTitle')}
            >
              {pendingRequests}
            </span>
          )}
        </button>
      )}
      <button
        onClick={() => { setUserMenuOpen(false); onNavigate(); onLogout(); }}
        className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl border border-red-200 dark:border-red-900/80 hover:bg-red-50 dark:hover:bg-red-950/40 text-red-600 dark:text-red-400 text-xs font-medium transition-colors"
      >
        <LogOut className="w-4 h-4" />
        <span>{t('nav.logout')}</span>
      </button>
    </>
  );

  return (
    <header className="spatial-navbar sticky top-0 z-40 bg-white/90 dark:bg-navy-900/90 backdrop-blur-md border-b border-slate-200/90 dark:border-navy-800/90">
      <div className="w-full mx-auto px-3 sm:px-6 lg:px-8 xl:px-10 min-h-14 sm:h-16 flex items-center justify-between gap-2 sm:gap-4 flex-wrap sm:flex-nowrap">
        {/* Left: Brand / Logo */}
        <div className="flex items-center gap-2 sm:gap-3 shrink-0">
          <div className="w-8 h-8 sm:w-10 sm:h-10 rounded-xl bg-gradient-to-tr from-teal-500 via-cyan-500 to-sky-400 flex items-center justify-center text-white shadow-md shadow-teal-500/25 shrink-0">
            <Layers className="w-4 h-4 sm:w-5 sm:h-5" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1 sm:gap-2">
              <h1 className="font-extrabold text-slate-900 dark:text-slate-100 text-sm sm:text-base lg:text-lg tracking-tight truncate max-w-[180px] sm:max-w-none">
                {t('app.title')}
              </h1>
              <span className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-teal-50 dark:bg-teal-950/80 text-teal-700 dark:text-teal-300 border border-teal-200/80 dark:border-teal-800/80 shrink-0">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                FineBI & Data Insight
              </span>
            </div>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 hidden lg:block">
              {t('nav.subtitle')}
            </p>
          </div>
        </div>

        {/* Right Action Controls - Desktop */}
        <div className="hidden md:flex items-center gap-1 sm:gap-1.5 shrink-0">
          {/* Design Guide Trigger */}
          <button
            onClick={onOpenDesignGuideModal}
            className="hidden lg:flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-teal-200 dark:border-teal-800/80 bg-teal-50/60 dark:bg-teal-950/40 hover:bg-teal-100 dark:hover:bg-teal-900/50 text-teal-700 dark:text-teal-300 text-xs font-semibold transition-all shadow-2xs"
          >
            <Lightbulb className="w-3.5 h-3.5 text-amber-500" />
            <span>{t('nav.designGuide')}</span>
          </button>

          {/* Save as Default（仅本机 localhost 显示）：当前目录存为服务端全局默认 */}
          {canSaveDefault && (
            <button
              onClick={onSaveDefault}
              className="hidden lg:flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-emerald-200 dark:border-emerald-800/80 bg-emerald-50/60 dark:bg-emerald-950/40 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300 text-xs font-semibold transition-all shadow-2xs"
              title={t('nav.saveDefaultTip')}
            >
              <SaveAll className="w-3.5 h-3.5" />
              <span>{t('nav.saveDefault')}</span>
            </button>
          )}

          {/* Environment Setting */}
          <button
            onClick={onOpenEnvironmentModal}
            className="flex items-center gap-1.5 px-2 sm:px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs font-medium transition-colors"
            title={t('nav.envTip')}
          >
            <Server className="w-3.5 h-3.5 text-slate-400" />
            <span className="hidden xl:inline">{t('nav.envConfig')}</span>
          </button>

          {/* Export / Backup dropdown or buttons */}
          <div className="hidden lg:flex items-center gap-1 border-l border-r border-slate-200 dark:border-slate-800 px-2">
            <button
              onClick={onExportJson}
              className="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-xs"
              title={t('nav.exportTip')}
            >
              <Download className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={onImportJson}
              className="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-xs"
              title={t('nav.importTip')}
            >
              <Upload className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={onResetDefaults}
              className="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-xs"
              title={t('nav.resetTip')}
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Language Switcher */}
          <button
            onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
            className="px-2 sm:px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors flex items-center gap-1 sm:gap-1.5"
            title={t('nav.langTip')}
          >
            <Languages className="w-4 h-4" />
            <span className="text-xs font-bold hidden sm:inline">{lang === 'zh' ? 'EN' : '中文'}</span>
          </button>

          {/* Dark Mode Switcher */}
          <button
            onClick={onToggleDarkMode}
            className="p-2 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            title={darkMode ? t('nav.lightTip') : t('nav.darkTip')}
          >
            {darkMode ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4" />}
          </button>

          {/* Add Board Primary Button */}
          <button
            onClick={onOpenAddModal}
            className="px-2.5 sm:px-3.5 lg:px-4 py-1.5 sm:py-2 rounded-xl bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 active:scale-[0.98] text-white font-semibold text-xs flex items-center gap-1 sm:gap-1.5 shadow-sm shadow-teal-600/25 transition-all"
          >
            <Plus className="w-4 h-4" />
            <span className="hidden sm:inline">{t('nav.addBoard')}</span>
          </button>

          {/* User Menu */}
          <div className="relative" ref={userMenuRef}>
            <button
              onClick={() => setUserMenuOpen(!userMenuOpen)}
              className="flex items-center gap-1.5 px-2 sm:px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs font-medium transition-colors"
              title={t('nav.userTip')}
            >
              <UserCircle className="w-4 h-4 text-slate-400" />
              <span className="hidden lg:inline max-w-24 truncate">{user.username}</span>
              {isAdmin ? (
                <span className="hidden sm:inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-violet-50 dark:bg-violet-950/80 text-violet-700 dark:text-violet-300 border border-violet-200 dark:border-violet-800">
                  <ShieldCheck className="w-2.5 h-2.5" />
                  {t('nav.roleAdmin')}
                </span>
              ) : (
                <span className="hidden sm:inline-flex px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-slate-50 dark:bg-slate-800 text-slate-500 dark:text-slate-400 border border-slate-200 dark:border-slate-700">
                  {t('nav.roleViewer')}
                </span>
              )}
              <ChevronDown className={`w-3.5 h-3.5 text-slate-400 transition-transform ${userMenuOpen ? 'rotate-180' : ''}`} />
            </button>
            {userMenuOpen && (
              <div className="absolute right-0 top-full mt-2 w-52 p-1.5 space-y-1.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-xl z-50 animate-fadeIn">
                <div className="px-3 py-1.5 text-[11px] text-slate-400 truncate">{user.username}</div>
                {userMenuItems(() => setUserMenuOpen(false))}
              </div>
            )}
          </div>
        </div>

        {/* Mobile: Hamburger + Add Button */}
        <div className="flex md:hidden items-center gap-2 shrink-0">
          {/* Add Board Button - always visible on mobile */}
          <button
            onClick={onOpenAddModal}
            className="px-3 py-1.5 rounded-xl bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 text-white font-semibold text-xs flex items-center gap-1 shadow-sm shadow-teal-600/25 transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>{t('nav.addBoard')}</span>
          </button>

          {/* Mobile Menu Toggle */}
          <button
            onClick={toggleMobileMenu}
            className="p-2 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            title={mobileMenuOpen ? 'Close menu' : 'Open menu'}
          >
            {mobileMenuOpen ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Mobile Expanded Menu */}
      {mobileMenuOpen && (
        <div className="md:hidden border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-navy-900 px-4 py-3 space-y-2 animate-fadeIn">
          {/* Current User */}
          <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800">
            <UserCircle className="w-4 h-4 text-slate-400" />
            <span className="text-xs font-semibold text-slate-700 dark:text-slate-300 truncate">
              {user.username}
            </span>
            <span className="ml-auto text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-violet-50 dark:bg-violet-950/80 text-violet-700 dark:text-violet-300 border border-violet-200 dark:border-violet-800">
              {isAdmin ? t('nav.roleAdmin') : t('nav.roleViewer')}
            </span>
          </div>

          {/* User Actions */}
          {userMenuItems(() => setMobileMenuOpen(false))}

          {/* Design Guide */}
          <button
            onClick={() => { onOpenDesignGuideModal(); setMobileMenuOpen(false); }}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl border border-teal-200 dark:border-teal-800/80 bg-teal-50/60 dark:bg-teal-950/40 hover:bg-teal-100 dark:hover:bg-teal-900/50 text-teal-700 dark:text-teal-300 text-xs font-semibold transition-all"
          >
            <Lightbulb className="w-4 h-4 text-amber-500" />
            <span>{t('nav.designGuide')}</span>
          </button>

          {/* Environment Setting */}
          <button
            onClick={() => { onOpenEnvironmentModal(); setMobileMenuOpen(false); }}
            className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs font-medium transition-colors"
          >
            <Server className="w-4 h-4 text-slate-400" />
            <span>{t('nav.envConfig')}</span>
          </button>

          {/* Save as Default（仅本机 localhost 显示） */}
          {canSaveDefault && (
            <button
              onClick={() => { onSaveDefault(); setMobileMenuOpen(false); }}
              className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl border border-emerald-200 dark:border-emerald-800/80 bg-emerald-50/60 dark:bg-emerald-950/40 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300 text-xs font-semibold transition-all"
            >
              <SaveAll className="w-4 h-4" />
              <span>{t('nav.saveDefault')}</span>
            </button>
          )}

          {/* Export / Import / Reset */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => { onExportJson(); setMobileMenuOpen(false); }}
              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 text-xs transition-colors"
              title={t('nav.exportTip')}
            >
              <Download className="w-4 h-4" />
              <span>{t('nav.exportTip')}</span>
            </button>
            <button
              onClick={() => { onImportJson(); setMobileMenuOpen(false); }}
              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 text-xs transition-colors"
              title={t('nav.importTip')}
            >
              <Upload className="w-4 h-4" />
              <span>{t('nav.importTip')}</span>
            </button>
          </div>

          <button
            onClick={() => { onResetDefaults(); setMobileMenuOpen(false); }}
            className="w-full flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 text-xs transition-colors"
            title={t('nav.resetTip')}
          >
            <RotateCcw className="w-4 h-4" />
            <span>{t('nav.resetTip')}</span>
          </button>

          {/* Language & Dark Mode */}
          <div className="flex items-center gap-2 pt-1 border-t border-slate-100 dark:border-slate-800">
            <button
              onClick={() => { setLang(lang === 'zh' ? 'en' : 'zh'); setMobileMenuOpen(false); }}
              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-xs font-bold"
              title={t('nav.langTip')}
            >
              <Languages className="w-4 h-4" />
              <span>{lang === 'zh' ? 'EN' : '中文'}</span>
            </button>
            <button
              onClick={() => { onToggleDarkMode(); setMobileMenuOpen(false); }}
              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-xs"
              title={darkMode ? t('nav.lightTip') : t('nav.darkTip')}
            >
              {darkMode ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4" />}
              <span>{darkMode ? t('nav.lightTip') : t('nav.darkTip')}</span>
            </button>
          </div>
        </div>
      )}
    </header>
  );
};
