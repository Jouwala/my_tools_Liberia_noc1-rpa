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
} from 'lucide-react';
import { useI18n } from '../i18n';

interface NavbarProps {
  darkMode: boolean;
  onToggleDarkMode: () => void;
  onOpenAddModal: () => void;
  onOpenEnvironmentModal: () => void;
  onOpenDesignGuideModal: () => void;
  onExportJson: () => void;
  onImportJson: () => void;
  onResetDefaults: () => void;
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
}) => {
  const { t, lang, setLang } = useI18n();
  const [mobileMenuOpen, setMobileMenuOpen] = React.useState(false);

  const toggleMobileMenu = () => setMobileMenuOpen(!mobileMenuOpen);

  return (
    <header className="sticky top-0 z-40 bg-white/90 dark:bg-navy-900/90 backdrop-blur-md border-b border-slate-200/90 dark:border-navy-800/90">
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
