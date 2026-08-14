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
} from 'lucide-react';
import {
  CategoryType,
  PlatformType,
  ViewMode,
  SortOption,
} from '../types/dashboard';
import { CATEGORIES } from '../data/initialDashboards';

interface FilterBarProps {
  selectedCategory: CategoryType;
  onSelectCategory: (cat: CategoryType) => void;
  selectedPlatform: 'all' | PlatformType;
  onSelectPlatform: (platform: 'all' | PlatformType) => void;
  onlyFavorites: boolean;
  onToggleOnlyFavorites: () => void;
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
  searchQuery,
  onSearchChange,
  sortOption,
  onSortChange,
  viewMode,
  onViewModeChange,
  totalFilteredCount,
}) => {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200/90 dark:border-slate-800/90 rounded-2xl p-4 shadow-sm mb-6 space-y-3.5">
      {/* Upper Row: Search & Filters & Layout controls */}
      <div className="flex flex-col lg:flex-row items-stretch lg:items-center justify-between gap-3">
        {/* Search Box */}
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="搜索看板名称、功能描述、URL、部门或标签..."
            className="w-full pl-9 pr-8 py-2 rounded-xl bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-xs text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition-all"
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
        <div className="flex flex-wrap items-center gap-2">
          {/* Platform Pills */}
          <div className="flex items-center p-1 bg-slate-100 dark:bg-slate-800/80 rounded-xl border border-slate-200/60 dark:border-slate-700/60 text-xs">
            <button
              onClick={() => onSelectPlatform('all')}
              className={`px-3 py-1 rounded-lg font-medium transition-all ${
                selectedPlatform === 'all'
                  ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 shadow-xs'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
              }`}
            >
              全部平台
            </button>
            <button
              onClick={() => onSelectPlatform('finebi')}
              className={`px-3 py-1 rounded-lg font-medium transition-all flex items-center gap-1.5 ${
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
              className={`px-3 py-1 rounded-lg font-medium transition-all flex items-center gap-1.5 ${
                selectedPlatform === 'custom'
                  ? 'bg-cyan-600 text-white shadow-xs'
                  : 'text-slate-600 dark:text-slate-400 hover:text-cyan-600 dark:hover:text-cyan-400'
              }`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-300" />
              自研系统
            </button>
          </div>

          {/* Starred Favorite Toggle */}
          <button
            onClick={onToggleOnlyFavorites}
            className={`px-3 py-1.5 rounded-xl border text-xs font-medium flex items-center gap-1.5 transition-all ${
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
            <span>已收藏</span>
          </button>

          {/* Sort Selector */}
          <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs">
            <ArrowUpDown className="w-3.5 h-3.5 text-slate-400" />
            <select
              value={sortOption}
              onChange={(e) => onSortChange(e.target.value as SortOption)}
              className="bg-transparent text-slate-700 dark:text-slate-200 font-medium focus:outline-none cursor-pointer"
            >
              <option value="pinned">推荐与置顶优先</option>
              <option value="popular">访问热度最高</option>
              <option value="recent">最近访问优先</option>
              <option value="name">看板名称排序</option>
            </select>
          </div>

          {/* View Mode Toggle */}
          <div className="flex items-center p-1 bg-slate-100 dark:bg-slate-800/80 rounded-xl border border-slate-200/60 dark:border-slate-700/60">
            <button
              onClick={() => onViewModeChange('grid')}
              className={`p-1.5 rounded-lg transition-all ${
                viewMode === 'grid'
                  ? 'bg-white dark:bg-slate-700 text-indigo-600 dark:text-indigo-400 shadow-xs'
                  : 'text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
              }`}
              title="卡片网格视图"
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
            <button
              onClick={() => onViewModeChange('list')}
              className={`p-1.5 rounded-lg transition-all ${
                viewMode === 'list'
                  ? 'bg-white dark:bg-slate-700 text-indigo-600 dark:text-indigo-400 shadow-xs'
                  : 'text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
              }`}
              title="表格清单视图"
            >
              <List className="w-4 h-4" />
            </button>
            <button
              onClick={() => onViewModeChange('matrix')}
              className={`p-1.5 rounded-lg transition-all ${
                viewMode === 'matrix'
                  ? 'bg-white dark:bg-slate-700 text-indigo-600 dark:text-indigo-400 shadow-xs'
                  : 'text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'
              }`}
              title="业务分类矩阵"
            >
              <Grid className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Lower Row: Category Tabs */}
      <div className="pt-2 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between overflow-x-auto gap-2 scrollbar-none">
        <div className="flex items-center gap-1.5 shrink-0">
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() => onSelectCategory(cat)}
              className={`px-3 py-1.5 rounded-xl text-xs font-medium transition-all shrink-0 ${
                selectedCategory === cat
                  ? 'bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 font-semibold shadow-xs'
                  : 'bg-slate-50 dark:bg-slate-800/60 text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        <div className="text-[11px] text-slate-400 shrink-0 font-medium pl-2">
          共筛选出 <strong className="text-slate-700 dark:text-slate-200 font-mono">{totalFilteredCount}</strong> 个看板
        </div>
      </div>
    </div>
  );
};
