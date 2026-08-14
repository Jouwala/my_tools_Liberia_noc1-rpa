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

interface QuickStatsBarProps {
  dashboards: DashboardItem[];
  onQuickFilterPlatform: (platform: 'all' | 'finebi' | 'custom') => void;
  activePlatform: string;
  onOpenEnvironment: () => void;
}

export const QuickStatsBar: React.FC<QuickStatsBarProps> = ({
  dashboards,
  onQuickFilterPlatform,
  activePlatform,
  onOpenEnvironment,
}) => {
  const totalCount = dashboards.length;
  const finebiCount = dashboards.filter((d) => d.platform === 'finebi').length;
  const customCount = dashboards.filter((d) => d.platform === 'custom').length;
  const totalClicks = dashboards.reduce((sum, d) => sum + d.clickCount, 0);

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-6">
      {/* 1. Total Dashboards */}
      <div
        onClick={() => onQuickFilterPlatform('all')}
        className={`p-4 rounded-2xl bg-white dark:bg-slate-900 border transition-all cursor-pointer shadow-xs hover:shadow-md ${
          activePlatform === 'all'
            ? 'border-indigo-500 ring-2 ring-indigo-500/20 bg-indigo-50/20 dark:bg-indigo-950/20'
            : 'border-slate-200/90 dark:border-slate-800/90 hover:border-slate-300 dark:hover:border-slate-700'
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
            全部聚合看板
          </span>
          <div className="p-2 rounded-xl bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400">
            <Layers className="w-4 h-4" />
          </div>
        </div>
        <div className="mt-2 flex items-baseline gap-2">
          <span className="text-2xl font-black text-slate-900 dark:text-slate-100 font-mono">
            {totalCount}
          </span>
          <span className="text-xs text-slate-400">个报表与大屏</span>
        </div>
      </div>

      {/* 2. FineBI Portals */}
      <div
        onClick={() => onQuickFilterPlatform('finebi')}
        className={`p-4 rounded-2xl bg-white dark:bg-slate-900 border transition-all cursor-pointer shadow-xs hover:shadow-md ${
          activePlatform === 'finebi'
            ? 'border-indigo-500 ring-2 ring-indigo-500/20 bg-indigo-50/20 dark:bg-indigo-950/20'
            : 'border-slate-200/90 dark:border-slate-800/90 hover:border-slate-300 dark:hover:border-slate-700'
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-indigo-500" />
            Liberia Data Portal (FineBI)
          </span>
          <div className="p-2 rounded-xl bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400">
            <Sparkles className="w-4 h-4" />
          </div>
        </div>
        <div className="mt-2 flex items-baseline gap-2">
          <span className="text-2xl font-black text-indigo-600 dark:text-indigo-400 font-mono">
            {finebiCount}
          </span>
          <span className="text-xs text-slate-400">个 MS/FO/BO 报表</span>
        </div>
      </div>

      {/* 3. Custom MyApp */}
      <div
        onClick={() => onQuickFilterPlatform('custom')}
        className={`p-4 rounded-2xl bg-white dark:bg-slate-900 border transition-all cursor-pointer shadow-xs hover:shadow-md ${
          activePlatform === 'custom'
            ? 'border-cyan-500 ring-2 ring-cyan-500/20 bg-cyan-50/20 dark:bg-cyan-950/20'
            : 'border-slate-200/90 dark:border-slate-800/90 hover:border-slate-300 dark:hover:border-slate-700'
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-cyan-500" />
            Data Insight MVP (自研)
          </span>
          <div className="p-2 rounded-xl bg-cyan-50 dark:bg-cyan-950/60 text-cyan-600 dark:text-cyan-400">
            <Cpu className="w-4 h-4" />
          </div>
        </div>
        <div className="mt-2 flex items-baseline gap-2">
          <span className="text-2xl font-black text-cyan-600 dark:text-cyan-400 font-mono">
            {customCount}
          </span>
          <span className="text-xs text-slate-400">个告警/工单/任务大屏</span>
        </div>
      </div>

      {/* 4. Host Status & Total Clicks */}
      <div
        onClick={onOpenEnvironment}
        className="p-4 rounded-2xl bg-white dark:bg-slate-900 border border-slate-200/90 dark:border-slate-800/90 hover:border-emerald-400 dark:hover:border-emerald-600 transition-all cursor-pointer shadow-xs hover:shadow-md group"
      >
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping" />
            局域网主机环境
          </span>
          <div className="p-2 rounded-xl bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 group-hover:scale-105 transition-transform">
            <Shield className="w-4 h-4" />
          </div>
        </div>
        <div className="mt-2 flex items-baseline justify-between">
          <div>
            <span className="text-xs font-mono font-bold text-slate-800 dark:text-slate-200">
              192.168.100.19
            </span>
            <div className="text-[11px] text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" /> 服务正常响应
            </div>
          </div>
          <span className="text-[11px] text-slate-400 group-hover:text-indigo-600 transition-colors">
            配置 &rarr;
          </span>
        </div>
      </div>
    </div>
  );
};
