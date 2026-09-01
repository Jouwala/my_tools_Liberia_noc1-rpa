import React from 'react';
import {
  Search,
  X,
  Star,
  LayoutGrid,
  List,
  Grid,
  ArrowUpDown,
  Filter,
  Layers,
  EyeOff,
  MessageSquareText,
} from 'lucide-react';
import {
  CategoryType,
  PlatformType,
  ViewMode,
  SortOption,
} from '../types/dashboard';
import { CATEGORIES } from '../data/initialDashboards';
import { useI18n, translateCategory } from '../i18n';

interface FilterBarProps {
  selectedCategory: CategoryType;
  onSelectCategory: (cat: CategoryType) => void;
  selectedPlatform: 'all' | PlatformType;
  onSelectPlatform: (platform: 'all' | PlatformType) => void;
  onlyFavorites: boolean;
  onToggleOnlyFavorites: () => void;
  /** 「显示已隐藏」开关：已隐藏的看板仅本机不可见，此开关可临时查看/恢复 */
  showHidden: boolean;
  onToggleShowHidden: () => void;
  hiddenCount: number;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  sortOption: SortOption;
  onSortChange: (sort: SortOption) => void;
  viewMode: ViewMode;
  onViewModeChange: (mode: ViewMode) => void;
  totalFilteredCount: number;
}

export const FilterBar: React.FC<FilterBarProps> = ({
  selectedCategory,
  onSelectCategory,
  selectedPlatform,
  onSelectPlatform,
  onlyFavorites,
  onToggleOnlyFavorites,
  showHidden,
  onToggleShowHidden,
  hiddenCount,
  searchQuery,
  onSearchChange,
  sortOption,
  onSortChange,
  viewMode,
  onViewModeChange,
  totalFilteredCount,
}) => {
  const { t, lang } = useI18n();
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200/90 dark:border-slate-800/90 rounded-2xl p-3 sm:p-4 shadow-sm mb-4 sm:mb-6 space-y-3 sm:space-y-3.5">
      {/* Upper Row: Search & Filters & Layout controls */}
      <div className="flex flex-col lg:flex-row items-stretch lg:items-center justify-between gap-3">
        {/* Search Box */}
        <div className="relative flex-1 max-w-full lg:max-w-md">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={t('filter.searchPh')}
            className="w-full pl-9 pr-8 py-2 rounded-xl bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-xs text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500 transition-all"
          />
          {searchQuery && (
            <button
              onClick={() => onSearchChange('')}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Right side controls: Platform pills, Favorite switch, Sort, View mode */}
        <div className="flex flex-wrap items-center gap-1 sm:gap-1.5">
          {/* Platform Pills */}
          <div className="flex items-center p-1 bg-slate-100 dark:bg-slate-800/80 rounded-xl border border-slate-200/60 dark:border-slate-700/60 text-xs">
            <button
              onClick={() => onSelectPlatform('all')}
              className={`px-2 sm:px-3 py-1 rounded-lg font-medium transition-all ${
                selectedPlatform === 'all'
                  ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 shadow-xs'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
              }`}
            >
              {t('filter.allPlatform')}
            </button>
            <button
              onClick={() => onSelectPlatform('finebi')}
              className={`px-2 sm:px-3 py-1 rounded-lg font-medium transition-all flex items-center gap-1 sm:gap-1.5 ${
                selectedPlatform === 'finebi'
                  ? 'bg-indigo-600 text-white shadow-xs'
                  : 'text-slate-600 dark:text-slate-400 hover:text-indigo-600 dark:hover:text-indigo-400'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-300" />
              FineBI
            </button>
            <button
              onClick={() => onSelectPlatform('custom')}
              className={`px-2 sm:px-3 py-1 rounded-lg font-medium transition-all flex items-center gap-1 sm:gap-1.5 ${
                selectedPlatform === 'custom'
                  ? 'bg-cyan-600 text-white shadow-xs'
                  : 'text-slate-600 dark:text-slate-400 hover:text-cyan-600 dark:hover:text-cyan-400'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-300" />
              {t('filter.custom')}
            </button>
          </div>

          {/* Starred Favorite Toggle */}
          <button
            onClick={onToggleOnlyFavorites}
            className={`px-2.5 sm:px-3 py-1.5 rounded-xl border text-xs font-medium flex items-center gap-1 sm:gap-1.5 transition-all ${
              onlyFavorites
                ? 'border-amber-400 bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 ring-2 ring-amber-400/20'
                : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'
            }`}
          >
            <Star
              className={`w-3.5 h-3.5 ${
                onlyFavorites ? 'fill-amber-400 text-amber-400' : 'text-slate-400'
              }`}
            />
            <span className="hidden sm:inline">{t('filter.favorites')}</span>
          </button>

          {/* 显示已隐藏开关：仅当本机存在已隐藏看板时出现（隐藏仅对本机生效） */}
          {hiddenCount > 0 && (
            <button
              onClick={onToggleShowHidden}
              className={`px-2.5 sm:px-3 py-1.5 rounded-xl border text-xs font-medium flex items-center gap-1 sm:gap-1.5 transition-all ${
                showHidden
                  ? 'border-teal-400 bg-teal-50 dark:bg-teal-950/60 text-teal-700 dark:text-teal-300 ring-2 ring-teal-400/20'
                  : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'
              }`}
              title={t('filter.showHiddenTip')}
            >
              <EyeOff
                className={`w-3.5 h-3.5 ${showHidden ? 'text-teal-500' : 'text-slate-400'}`}
              />
              <span className="hidden sm:inline">
                {t('filter.showHidden')} ({hiddenCount})
              </span>
            </button>
          )}

          {/* Sort Selector */}
          <div className="flex items-center gap-1 sm:gap-1.5 px-1.5 sm:px-2.5 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs">
            <ArrowUpDown className="w-3.5 h-3.5 text-slate-400" />
            <select
              value={sortOption}
              onChange={(e) => onSortChange(e.target.value as SortOption)}
              className="bg-transparent text-slate-700 dark:text-slate-200 font-medium focus:outline-none cursor-pointer"
            >
              <option value="pinned">{t('filter.sortPinned')}</option>
              <option value="popular">{t('filter.sortPopular')}</option>
              <option value="recent">{t('filter.sortRecent')}</option>
              <option value="name">{t('filter.sortName')}</option>
            </select>
          </div>

          {/* WhatsApp @我 待办入口 */}
          <button
            onClick={() => onViewModeChange('tasks')}
            className={`px-2.5 sm:px-3 py-1.5 rounded-xl border text-xs font-medium flex items-center gap-1 sm:gap-1.5 transition-all ${
              viewMode === 'tasks'
                ? 'border-teal-400 bg-teal-50 dark:bg-teal-950/60 text-teal-700 dark:text-teal-300 ring-2 ring-teal-400/20'
                : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'
            }`}
            title={t('filter.viewTasks')}
          >
            <MessageSquareText
              className={`w-3.5 h-3.5 ${viewMode === 'tasks' ? 'text-teal-500' : 'text-slate-400'}`}
            />
            <span className="hidden sm:inline">{t('filter.viewTasks')}</span>
          </button>

          {/* View Mode Toggle */}
          <div className="flex items-center p-1 bg-slate-100 dark:bg-slate-800/80 rounded-xl border border-slate-200/60 dark:border-slate-700/60">
            <button
              onClick={() => onViewModeChange('grid')}
              className={`p-1.5 rounded-lg transition-all ${
                viewMode === 'grid'
                  ? 'bg-white dark:bg-slate-700 text-teal-600 dark:text-teal-300 shadow-xs'
                  : 'text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
              }`}
              title={t('filter.viewGrid')}
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
            <button
              onClick={() => onViewModeChange('list')}
              className={`p-1.5 rounded-lg transition-all ${
                viewMode === 'list'
                  ? 'bg-white dark:bg-slate-700 text-teal-600 dark:text-teal-300 shadow-xs'
                  : 'text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
              }`}
              title={t('filter.viewList')}
            >
              <List className="w-4 h-4" />
            </button>
            <button
              onClick={() => onViewModeChange('matrix')}
              className={`p-1.5 rounded-lg transition-all ${
                viewMode === 'matrix'
                  ? 'bg-white dark:bg-slate-700 text-teal-600 dark:text-teal-300 shadow-xs'
                  : 'text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
              }`}
              title={t('filter.viewMatrix')}
            >
              <Grid className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Lower Row: Category Tabs */}
      <div className="pt-2 sm:pt-3 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between overflow-x-auto gap-2 sm:gap-3 scrollbar-none">
        <div className="flex items-center gap-1 sm:gap-2 shrink-0">
          {CATEGORIES.map((cat) => {
            const active = selectedCategory === cat;
            return (
              <button
                key={cat}
                onClick={() => onSelectCategory(cat)}
                className={`px-3 sm:px-4 py-1.5 sm:py-2 rounded-lg sm:rounded-xl text-xs sm:text-sm font-semibold transition-all duration-200 shrink-0 whitespace-nowrap ${
                  active
                    ? 'bg-gradient-to-r from-teal-600 to-cyan-600 text-white shadow-md shadow-teal-600/25'
                    : 'bg-slate-50 dark:bg-slate-800/60 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-slate-100'
                }`}
              >
                {translateCategory(cat, lang, t)}
              </button>
            );
          })}
        </div>

        <div className="text-xs text-slate-400 shrink-0 font-medium pl-2 whitespace-nowrap">
          {t('filter.result', { n: totalFilteredCount })}
        </div>
      </div>
    </div>
  );
};
