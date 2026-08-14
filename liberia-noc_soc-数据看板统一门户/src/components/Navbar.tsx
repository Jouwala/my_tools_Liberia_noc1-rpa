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
  return (
    <header className="sticky top-0 z-40 bg-white/90 dark:bg-navy-900/90 backdrop-blur-md border-b border-slate-200/90 dark:border-navy-800/90">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
        {/* Left: Brand / Logo */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-teal-500 via-cyan-500 to-sky-400 flex items-center justify-center text-white shadow-md shadow-teal-500/25 shrink-0">
            <Layers className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-extrabold text-slate-900 dark:text-slate-100 text-base sm:text-lg tracking-tight">
                {t('app.title')}
              </h1>
              <span className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-teal-50 dark:bg-teal-950/80 text-teal-700 dark:text-teal-300 border border-teal-200/80 dark:border-teal-800/80">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                FineBI & Data Insight
              </span>
            </div>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 hidden sm:block">
              {t('nav.subtitle')}
            </p>
          </div>
        </div>

        {/* Right Action Controls */}
        <div className="flex items-center gap-2 sm:gap-2.5">
          {/* Design Guide Trigger */}
          <button
            onClick={onOpenDesignGuideModal}
            className="hidden md:flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-teal-200 dark:border-teal-800/80 bg-teal-50/60 dark:bg-teal-950/40 hover:bg-teal-100 dark:hover:bg-teal-900/50 text-teal-700 dark:text-teal-300 text-xs font-semibold transition-all shadow-2xs"
          >
            <Lightbulb className="w-3.5 h-3.5 text-amber-500" />
            <span>{t('nav.designGuide')}</span>
          </button>

          {/* Environment Setting */}
          <button
            onClick={onOpenEnvironmentModal}
            className="flex items-center gap-1.5 px-2.5 sm:px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs font-medium transition-colors"
            title={t('nav.envTip')}
          >
            <Server className="w-3.5 h-3.5 text-slate-400" />
            <span className="hidden sm:inline">{t('nav.envConfig')}</span>
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
            className="px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors flex items-center gap-1.5"
            title={t('nav.langTip')}
          >
            <Languages className="w-4 h-4" />
            <span className="text-xs font-bold">{lang === 'zh' ? 'EN' : '中文'}</span>
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
            className="px-3.5 sm:px-4 py-2 rounded-xl bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 active:scale-[0.98] text-white font-semibold text-xs flex items-center gap-1.5 shadow-sm shadow-teal-600/25 transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>{t('nav.addBoard')}</span>
          </button>
        </div>
      </div>
    </header>
  );
};
