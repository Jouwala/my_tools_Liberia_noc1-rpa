import React from 'react';
import {
  Layers,
  Sparkles,
  Cpu,
  MousePointerClick,
  CheckCircle2,
  ExternalLink,
  Shield,
} from 'lucide-react';
import { DashboardItem } from '../types/dashboard';
import { getMyappHost } from '../config';
import { useI18n } from '../i18n';

interface QuickStatsBarProps {
  dashboards: DashboardItem[];
  onQuickFilterPlatform: (platform: 'all' | 'finebi' | 'custom' | 'external') => void;
  activePlatform: string;
  onOpenEnvironment: () => void;
}

export const QuickStatsBar: React.FC<QuickStatsBarProps> = ({
  dashboards,
  onQuickFilterPlatform,
  activePlatform,
  onOpenEnvironment,
}) => {
  const { t } = useI18n();
  const totalCount = dashboards.length;
  const finebiCount = dashboards.filter((d) => d.platform === 'finebi').length;
  const customCount = dashboards.filter((d) => d.platform === 'custom').length;
  const externalCount = dashboards.filter((d) => d.platform === 'external').length;
  const totalClicks = dashboards.reduce((sum, d) => sum + d.clickCount, 0);

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 sm:gap-3 md:gap-4 mb-4 sm:mb-6">
      {/* 1. Total Dashboards */}
      <div
        onClick={() => onQuickFilterPlatform('all')}
        className={`p-3 sm:p-4 rounded-2xl bg-white dark:bg-navy-900 border transition-all cursor-pointer shadow-xs hover:shadow-md ${
          activePlatform === 'all'
            ? 'border-teal-500 ring-2 ring-teal-500/20 bg-teal-50/20 dark:bg-teal-950/20'
            : 'border-slate-200/90 dark:border-slate-800/90 hover:border-slate-300 dark:hover:border-slate-700'
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="text-[10px] sm:text-xs font-semibold text-slate-500 dark:text-slate-400">
            {t('stats.total')}
          </span>
          <div className="p-1.5 sm:p-2 rounded-xl bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-300">
            <Layers className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
          </div>
        </div>
        <div className="mt-1.5 sm:mt-2 flex items-baseline gap-1 sm:gap-2">
          <span className="text-xl sm:text-2xl font-black text-slate-900 dark:text-slate-100 font-mono">
            {totalCount}
          </span>
          <span className="text-[10px] sm:text-xs text-slate-400">{t('stats.totalUnit')}</span>
        </div>
      </div>

      {/* 2. FineBI Portals */}
      <div
        onClick={() => onQuickFilterPlatform('finebi')}
        className={`p-3 sm:p-4 rounded-2xl bg-white dark:bg-navy-900 border transition-all cursor-pointer shadow-xs hover:shadow-md ${
          activePlatform === 'finebi'
            ? 'border-indigo-500 ring-2 ring-indigo-500/20 bg-indigo-50/20 dark:bg-indigo-950/20'
            : 'border-slate-200/90 dark:border-slate-800/90 hover:border-slate-300 dark:hover:border-slate-700'
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="text-[10px] sm:text-xs font-semibold text-slate-500 dark:text-slate-400 flex items-center gap-1 sm:gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-indigo-500" />
            {t('stats.finebi')}
          </span>
          <div className="p-1.5 sm:p-2 rounded-xl bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400">
            <Sparkles className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
          </div>
        </div>
        <div className="mt-1.5 sm:mt-2 flex items-baseline gap-1 sm:gap-2">
          <span className="text-xl sm:text-2xl font-black text-indigo-600 dark:text-indigo-400 font-mono">
            {finebiCount}
          </span>
          <span className="text-[10px] sm:text-xs text-slate-400">{t('stats.finebiUnit')}</span>
        </div>
      </div>

      {/* 3. Custom MyApp */}
      <div
        onClick={() => onQuickFilterPlatform('custom')}
        className={`p-3 sm:p-4 rounded-2xl bg-white dark:bg-navy-900 border transition-all cursor-pointer shadow-xs hover:shadow-md ${
          activePlatform === 'custom'
            ? 'border-cyan-500 ring-2 ring-cyan-500/20 bg-cyan-50/20 dark:bg-cyan-950/20'
            : 'border-slate-200/90 dark:border-slate-800/90 hover:border-slate-300 dark:hover:border-slate-700'
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="text-[10px] sm:text-xs font-semibold text-slate-500 dark:text-slate-400 flex items-center gap-1 sm:gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-500" />
            {t('stats.custom')}
          </span>
          <div className="p-1.5 sm:p-2 rounded-xl bg-cyan-50 dark:bg-cyan-950/60 text-cyan-600 dark:text-cyan-400">
            <Cpu className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
          </div>
        </div>
        <div className="mt-1.5 sm:mt-2 flex items-baseline gap-1 sm:gap-2">
          <span className="text-xl sm:text-2xl font-black text-cyan-600 dark:text-cyan-400 font-mono">
            {customCount}
          </span>
          <span className="text-[10px] sm:text-xs text-slate-400">{t('stats.customUnit')}</span>
        </div>
      </div>

      {/* 4. External Big Screen */}
      <div
        onClick={() => onQuickFilterPlatform('external')}
        className={`p-3 sm:p-4 rounded-2xl bg-white dark:bg-navy-900 border transition-all cursor-pointer shadow-xs hover:shadow-md ${
          activePlatform === 'external'
            ? 'border-[#008B00] ring-2 ring-[#008B00]/20 bg-[#008B00]/10 dark:bg-[#008B00]/10'
            : 'border-slate-200/90 dark:border-slate-800/90 hover:border-slate-300 dark:hover:border-slate-700'
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="text-[10px] sm:text-xs font-semibold text-slate-500 dark:text-slate-400 flex items-center gap-1 sm:gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-[#008B00]" />
            {t('stats.external')}
          </span>
          <div className="p-1.5 sm:p-2 rounded-xl bg-[#008B00]/10 dark:bg-[#008B00]/20 text-[#008B00] dark:text-[#008B00]">
            <ExternalLink className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
          </div>
        </div>
        <div className="mt-1.5 sm:mt-2 flex items-baseline gap-1 sm:gap-2">
          <span className="text-xl sm:text-2xl font-black text-[#008B00] dark:text-[#008B00] font-mono">
            {externalCount}
          </span>
          <span className="text-[10px] sm:text-xs text-slate-400">{t('stats.externalUnit')}</span>
        </div>
      </div>

      {/* 5. Host Status & Total Clicks */}
      <div
        onClick={onOpenEnvironment}
        className="p-3 sm:p-4 rounded-2xl bg-white dark:bg-navy-900 border border-slate-200/90 dark:border-slate-800/90 hover:border-emerald-400 dark:hover:border-emerald-600 transition-all cursor-pointer shadow-xs hover:shadow-md group col-span-2 sm:col-span-1"
      >
        <div className="flex items-center justify-between">
          <span className="text-[10px] sm:text-xs font-semibold text-slate-500 dark:text-slate-400 flex items-center gap-1 sm:gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping" />
            {t('stats.host')}
          </span>
          <div className="p-1.5 sm:p-2 rounded-xl bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 group-hover:scale-105 transition-transform">
            <Shield className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
          </div>
        </div>
        <div className="mt-1.5 sm:mt-2 flex items-baseline justify-between">
          <div>
            <span className="text-xs sm:text-sm font-mono font-bold text-slate-800 dark:text-slate-200">
              {getMyappHost()}
            </span>
            <div className="text-[10px] sm:text-[11px] text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" /> {t('stats.hostOk')}
            </div>
          </div>
          <span className="text-[10px] sm:text-[11px] text-slate-400 group-hover:text-teal-600 transition-colors">
            {t('stats.config')} &rarr;
          </span>
        </div>
      </div>
    </div>
  );
};
