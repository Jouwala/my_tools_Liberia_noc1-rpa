import React from 'react';
import { ExternalLink, Star, Eye, QrCode } from 'lucide-react';
import { DashboardItem, CategoryType } from '../types/dashboard';
import { CATEGORIES } from '../data/initialDashboards';
import { DynamicIcon } from './DynamicIcon';
import { FREQ_LABEL_KEY, useI18n } from '../i18n';

interface DashboardMatrixViewProps {
  dashboards: DashboardItem[];
  onOpen: (d: DashboardItem) => void;
  onPreview: (d: DashboardItem) => void;
  onShowQR: (d: DashboardItem) => void;
  onToggleFavorite: (id: string) => void;
}

export const DashboardMatrixView: React.FC<DashboardMatrixViewProps> = ({
  dashboards,
  onOpen,
  onPreview,
  onShowQR,
  onToggleFavorite,
}) => {
  const { t } = useI18n();
  const activeCategories = CATEGORIES.filter((c) => c !== '全部');

  return (
    <div className="space-y-6">
      {activeCategories.map((category) => {
        const items = dashboards.filter((d) => d.category === category);
        if (items.length === 0) return null;

        return (
          <div
            key={category}
            className="spatial-panel bg-white dark:bg-slate-900 border border-slate-200/90 dark:border-slate-800/90 rounded-2xl p-5 shadow-sm"
          >
            {/* Category Header */}
            <div className="flex items-center justify-between pb-3 mb-4 border-b border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2.5">
                <span className="w-2.5 h-2.5 rounded-full bg-teal-500 dark:bg-teal-400" />
                <h3 className="font-bold text-slate-900 dark:text-slate-100 text-base">
                  {category}
                </h3>
                <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-[11px] font-medium text-slate-600 dark:text-slate-400">
                  {items.length} {t('matrix.boards')}
                </span>
              </div>
            </div>

            {/* Matrix Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-3.5">
              {items.map((board) => (
                <div
                  key={board.id}
                  className="p-3.5 rounded-xl border border-slate-200/70 dark:border-slate-800/70 bg-slate-50/50 dark:bg-slate-800/30 hover:bg-white dark:hover:bg-slate-800/80 hover:border-teal-300 dark:hover:border-teal-700 transition-all group flex flex-col justify-between"
                >
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span
                        className={`text-[10px] font-semibold px-2 py-0.5 rounded-md ${
                          board.platform === 'finebi'
                            ? 'bg-indigo-100 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                            : 'bg-cyan-100 dark:bg-cyan-950 text-cyan-700 dark:text-cyan-300'
                        }`}
                      >
                        {board.platform === 'finebi' ? 'FineBI' : t('list.platformCustom')}
                      </span>

                      <button
                        onClick={() => onToggleFavorite(board.id)}
                        className={`transition-colors ${
                          board.isFavorite
                            ? 'text-amber-400'
                            : 'text-slate-300 dark:text-slate-600 hover:text-amber-400'
                        }`}
                      >
                        <Star
                          className="w-3.5 h-3.5"
                          fill={board.isFavorite ? 'currentColor' : 'none'}
                        />
                      </button>
                    </div>

                    <div className="flex items-start gap-2.5">
                      <div className="p-2 rounded-lg bg-white dark:bg-slate-800 border border-slate-200/80 dark:border-slate-700 shadow-xs text-slate-700 dark:text-slate-300 shrink-0">
                        <DynamicIcon name={board.iconName} className="w-4 h-4" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <h4
                          onClick={() => onOpen(board)}
                          className="font-semibold text-slate-900 dark:text-slate-100 text-xs truncate hover:text-teal-600 dark:hover:text-teal-300 cursor-pointer"
                        >
                          {board.title}
                        </h4>
                        <p className="text-[11px] text-slate-500 dark:text-slate-400 line-clamp-1 mt-0.5">
                          {board.description}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="mt-3 pt-2 border-t border-slate-100 dark:border-slate-800/60 flex items-center justify-between text-[11px]">
                    <span className="text-slate-400 text-[10px]">
                      {board.department} · {t(FREQ_LABEL_KEY[board.updateFrequency] || board.updateFrequency)}
                    </span>

                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => onShowQR(board)}
                        className="p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                        title={t('list.qr')}
                      >
                        <QrCode className="w-3 h-3" />
                      </button>
                      <button
                        onClick={() => onPreview(board)}
                        className="p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                        title={t('list.preview')}
                      >
                        <Eye className="w-3 h-3" />
                      </button>
                      <button
                        onClick={() => onOpen(board)}
                        className="px-2 py-0.5 rounded bg-teal-600 hover:bg-teal-500 text-white font-medium text-[10px] flex items-center gap-0.5 transition-colors"
                      >
                        {t('list.open')} <ExternalLink className="w-2.5 h-2.5" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
};
