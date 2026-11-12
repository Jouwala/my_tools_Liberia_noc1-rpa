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
        className={`spatial-stat-card p-3 rounded-lg bg-white dark:bg-navy-900 border transition-colors cursor-pointer ${
          activePlatform === 'all'
            ? 'border-brand-600 ring-2 ring-brand-600/25 bg-brand-50 dark:bg-brand-900/40'
            : 'border-slate-200/90 dark:border-slate-800/90 hover:border-slate-300 dark:hover:border-slate-700'
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="text-[10px] sm:text-xs font-semibold text-slate-500 dark:text-slate-400">
            {t('stats.total')}
          </span>
          <div className="p-1.5 sm:p-2 rounded-lg bg-brand-50 dark:bg-brand-900 text-brand-600 dark:text-brand-300">
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
        className={`spatial-stat-card p-3 rounded-lg bg-white dark:bg-navy-900 border transition-colors cursor-pointer ${
          activePlatform === 'finebi'
            ? 'border-brand-600 ring-2 ring-brand-600/25 bg-brand-50 dark:bg-brand-900/40'
            : 'border-slate-200/90 dark:border-slate-800/90 hover:border-slate-300 dark:hover:border-slate-700'
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="text-[10px] sm:text-xs font-semibold text-slate-500 dark:text-slate-400 flex items-center gap-1 sm:gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-indigo-500" />
            {t('stats.finebi')}
          </span>
          <div className="p-1.5 sm:p-2 rounded-lg bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400">
            <Sparkles className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
          </div>
        </div>
        <div className="mt-1.5 sm:mt-2 flex items-baseline gap-1 sm:gap-2">
          <span className="text-xl sm:text-2xl font-black text-slate-900 dark:text-slate-100 font-mono">
            {finebiCount}
          </span>
          <span className="text-[10px] sm:text-xs text-slate-400">{t('stats.finebiUnit')}</span>
        </div>
      </div>

      {/* 3. Custom MyApp */}
      <div
        onClick={() => onQuickFilterPlatform('custom')}
        className={`spatial-stat-card p-3 rounded-lg bg-white dark:bg-navy-900 border transition-colors cursor-pointer ${
          activePlatform === 'custom'
            ? 'border-brand-600 ring-2 ring-brand-600/25 bg-brand-50 dark:bg-brand-900/40'
            : 'border-slate-200/90 dark:border-slate-800/90 hover:border-slate-300 dark:hover:border-slate-700'
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="text-[10px] sm:text-xs font-semibold text-slate-500 dark:text-slate-400 flex items-center gap-1 sm:gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-brand-600" />
            {t('stats.custom')}
          </span>
          <div className="p-1.5 sm:p-2 rounded-lg bg-brand-50 dark:bg-brand-900 text-brand-600 dark:text-brand-300">
            <Cpu className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
          </div>
        </div>
        <div className="mt-1.5 sm:mt-2 flex items-baseline gap-1 sm:gap-2">
          <span className="text-xl sm:text-2xl font-black text-slate-900 dark:text-slate-100 font-mono">
            {customCount}
          </span>
          <span className="text-[10px] sm:text-xs text-slate-400">{t('stats.customUnit')}</span>
        </div>
      </div>

      {/* 4. External Big Screen */}
      <div
        onClick={() => onQuickFilterPlatform('external')}
        className={`spatial-stat-card p-3 rounded-lg bg-white dark:bg-navy-900 border transition-colors cursor-pointer ${
          activePlatform === 'external'
            ? 'border-brand-600 ring-2 ring-brand-600/25 bg-brand-50 dark:bg-brand-900/40'
            : 'border-slate-200/90 dark:border-slate-800/90 hover:border-slate-300 dark:hover:border-slate-700'
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="text-[10px] sm:text-xs font-semibold text-slate-500 dark:text-slate-400 flex items-center gap-1 sm:gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-[#008B00]" />
            {t('stats.external')}
          </span>
          <div className="p-1.5 sm:p-2 rounded-lg bg-[#008B00]/10 dark:bg-[#008B00]/20 text-[#008B00] dark:text-[#008B00]">
            <ExternalLink className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
          </div>
        </div>
        <div className="mt-1.5 sm:mt-2 flex items-baseline gap-1 sm:gap-2">
          <span className="text-xl sm:text-2xl font-black text-slate-900 dark:text-slate-100 font-mono">
            {externalCount}
          </span>
          <span className="text-[10px] sm:text-xs text-slate-400">{t('stats.externalUnit')}</span>
        </div>
      </div>

      {/* 5. Host Status & Total Clicks */}
      <div
        onClick={onOpenEnvironment}
        className="p-3 rounded-lg bg-white dark:bg-navy-900 border border-slate-200/90 dark:border-slate-800/90 hover:border-brand-600 dark:hover:border-brand-500 transition-colors cursor-pointer group col-span-2 sm:col-span-1"
      >
        <div className="flex items-center justify-between">
          <span className="text-[10px] sm:text-xs font-semibold text-slate-500 dark:text-slate-400 flex items-center gap-1 sm:gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping" />
            {t('stats.host')}
          </span>
          <div className="p-1.5 sm:p-2 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 ">
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
          <span className="text-[10px] sm:text-[11px] text-slate-400 group-hover:text-brand-600 transition-colors">
            {t('stats.config')} &rarr;
          </span>
        </div>
      </div>
    </div>
  );
};
