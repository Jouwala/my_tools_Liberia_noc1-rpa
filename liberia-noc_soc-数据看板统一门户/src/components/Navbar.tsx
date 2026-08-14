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
} from 'lucide-react';

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
  return (
    <header className="sticky top-0 z-40 bg-white/90 dark:bg-slate-900/90 backdrop-blur-md border-b border-slate-200/90 dark:border-slate-800/90">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between gap-4">
        {/* Left: Brand / Logo */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 via-indigo-700 to-cyan-500 flex items-center justify-center text-white shadow-md shadow-indigo-500/20 shrink-0">
            <Layers className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-extrabold text-slate-900 dark:text-slate-100 text-base sm:text-lg tracking-tight">
                Liberia NOC/SOC 数据看板统一门户
              </h1>
              <span className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-50 dark:bg-indigo-950/80 text-indigo-700 dark:text-indigo-300 border border-indigo-200/80 dark:border-indigo-800/80">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                FineBI & Data Insight
              </span>
            </div>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 hidden sm:block">
              Liberia Data Portal (FineBI) · Data Insight MVP (自研系统) · 统一调度直通
            </p>
          </div>
        </div>

        {/* Right Action Controls */}
        <div className="flex items-center gap-2 sm:gap-2.5">
          {/* Design Guide Trigger */}
          <button
            onClick={onOpenDesignGuideModal}
            className="hidden md:flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-indigo-200 dark:border-indigo-800/80 bg-indigo-50/60 dark:bg-indigo-950/40 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 text-xs font-semibold transition-all shadow-2xs"
          >
            <Lightbulb className="w-3.5 h-3.5 text-amber-500" />
            <span>设计与美化方案</span>
          </button>

          {/* Environment Setting */}
          <button
            onClick={onOpenEnvironmentModal}
            className="flex items-center gap-1.5 px-2.5 sm:px-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs font-medium transition-colors"
            title="配置服务器 IP / 域名环境"
          >
            <Server className="w-3.5 h-3.5 text-slate-400" />
            <span className="hidden sm:inline">环境配置</span>
          </button>

          {/* Export / Backup dropdown or buttons */}
          <div className="hidden lg:flex items-center gap-1 border-l border-r border-slate-200 dark:border-slate-800 px-2">
            <button
              onClick={onExportJson}
              className="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-xs"
              title="导出配置 JSON 备份"
            >
              <Download className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={onImportJson}
              className="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-xs"
              title="导入配置 JSON 文件"
            >
              <Upload className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={onResetDefaults}
              className="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-xs"
              title="恢复初始默认看板"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Dark Mode Switcher */}
          <button
            onClick={onToggleDarkMode}
            className="p-2 rounded-xl border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            title={darkMode ? '切换为浅色日间模式' : '切换为深色夜间模式'}
          >
            {darkMode ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4" />}
          </button>

          {/* Add Board Primary Button */}
          <button
            onClick={onOpenAddModal}
            className="px-3.5 sm:px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-700 active:scale-[0.98] text-white font-semibold text-xs flex items-center gap-1.5 shadow-sm shadow-indigo-600/25 transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>添加看板</span>
          </button>
        </div>
      </div>
    </header>
  );
};
