import React, { useState } from 'react';
import {
  ExternalLink,
  Star,
  Pin,
  Clock,
  Building,
  QrCode,
  Eye,
  Copy,
  Check,
  Edit2,
  Trash2,
  TrendingUp,
} from 'lucide-react';
import { DashboardItem } from '../types/dashboard';
import { DynamicIcon } from './DynamicIcon';
import { FREQ_LABEL_KEY, useI18n } from '../i18n';

interface DashboardCardProps {
  dashboard: DashboardItem;
  onOpen: (d: DashboardItem) => void;
  onPreview: (d: DashboardItem) => void;
  onShowQR: (d: DashboardItem) => void;
  onToggleFavorite: (id: string) => void;
  onEdit: (d: DashboardItem) => void;
  onDelete: (id: string) => void;
}

export const DashboardCard: React.FC<DashboardCardProps> = ({
  dashboard,
  onOpen,
  onPreview,
  onShowQR,
  onToggleFavorite,
  onEdit,
  onDelete,
}) => {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(dashboard.url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const getPlatformBadge = () => {
    switch (dashboard.platform) {
      case 'finebi':
        return {
          label: t('card.finebiBadge'),
          bg: 'bg-indigo-500/10 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800/80',
          dot: 'bg-indigo-500',
        };
      case 'custom':
        return {
          label: t('card.customBadge'),
          bg: 'bg-cyan-500/10 text-cyan-700 dark:text-cyan-300 border-cyan-200 dark:border-cyan-800/80',
          dot: 'bg-cyan-500',
        };
      default:
        return {
          label: t('card.externalBadge'),
          bg: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/80',
          dot: 'bg-emerald-500',
        };
    }
  };

  const badge = getPlatformBadge();

  // Accent color map
  const colorStyles: Record<
    DashboardItem['themeColor'],
    { border: string; iconBg: string; text: string; lightBg: string }
  > = {
    indigo: {
      border: 'hover:border-indigo-400 dark:hover:border-indigo-600',
      iconBg: 'bg-indigo-50 dark:bg-indigo-950/70 text-indigo-600 dark:text-indigo-400',
      text: 'text-indigo-600 dark:text-indigo-400',
      lightBg: 'from-indigo-500/5 to-transparent',
    },
    teal: {
      border: 'hover:border-teal-400 dark:hover:border-teal-500',
      iconBg: 'bg-teal-50 dark:bg-teal-950/70 text-teal-600 dark:text-teal-300',
      text: 'text-teal-600 dark:text-teal-300',
      lightBg: 'from-teal-500/5 to-transparent',
    },
    cyan: {
      border: 'hover:border-cyan-400 dark:hover:border-cyan-600',
      iconBg: 'bg-cyan-50 dark:bg-cyan-950/70 text-cyan-600 dark:text-cyan-400',
      text: 'text-cyan-600 dark:text-cyan-400',
      lightBg: 'from-cyan-500/5 to-transparent',
    },
    emerald: {
      border: 'hover:border-emerald-400 dark:hover:border-emerald-600',
      iconBg: 'bg-emerald-50 dark:bg-emerald-950/70 text-emerald-600 dark:text-emerald-400',
      text: 'text-emerald-600 dark:text-emerald-400',
      lightBg: 'from-emerald-500/5 to-transparent',
    },
    purple: {
      border: 'hover:border-purple-400 dark:hover:border-purple-600',
      iconBg: 'bg-purple-50 dark:bg-purple-950/70 text-purple-600 dark:text-purple-400',
      text: 'text-purple-600 dark:text-purple-400',
      lightBg: 'from-purple-500/5 to-transparent',
    },
    amber: {
      border: 'hover:border-amber-400 dark:hover:border-amber-600',
      iconBg: 'bg-amber-50 dark:bg-amber-950/70 text-amber-600 dark:text-amber-400',
      text: 'text-amber-600 dark:text-amber-400',
      lightBg: 'from-amber-500/5 to-transparent',
    },
    rose: {
      border: 'hover:border-rose-400 dark:hover:border-rose-600',
      iconBg: 'bg-rose-50 dark:bg-rose-950/70 text-rose-600 dark:text-rose-400',
      text: 'text-rose-600 dark:text-rose-400',
      lightBg: 'from-rose-500/5 to-transparent',
    },
    blue: {
      border: 'hover:border-blue-400 dark:hover:border-blue-600',
      iconBg: 'bg-blue-50 dark:bg-blue-950/70 text-blue-600 dark:text-blue-400',
      text: 'text-blue-600 dark:text-blue-400',
      lightBg: 'from-blue-500/5 to-transparent',
    },
  };

  const theme = colorStyles[dashboard.themeColor] || colorStyles.indigo;

  return (
    <div
      className={`group relative bg-white dark:bg-slate-900 border border-slate-200/90 dark:border-slate-800/90 rounded-2xl p-5 shadow-sm hover:shadow-xl transition-all duration-300 flex flex-col justify-between overflow-hidden bg-gradient-to-b ${theme.lightBg} ${theme.border}`}
    >
      {/* Top row: Platform Badge & Pin / Star / Actions */}
      <div>
        <div className="flex items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2">
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${badge.bg}`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${badge.dot} animate-pulse`} />
              {badge.label}
            </span>

            {dashboard.isPinned && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-900/60">
                <Pin className="w-2.5 h-2.5" /> {t('card.pinned')}
              </span>
            )}
          </div>

          <div className="flex items-center gap-1">
            <button
              onClick={() => onToggleFavorite(dashboard.id)}
              className={`p-1.5 rounded-lg transition-colors ${
                dashboard.isFavorite
                  ? 'text-amber-400 hover:text-amber-500'
                  : 'text-slate-300 dark:text-slate-600 hover:text-amber-400'
              }`}
              title={dashboard.isFavorite ? t('card.favOn') : t('card.favOff')}
            >
              <Star
                className="w-4 h-4"
                fill={dashboard.isFavorite ? 'currentColor' : 'none'}
              />
            </button>

            <button
              onClick={() => onEdit(dashboard)}
              className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-all"
              title={t('card.edit')}
            >
              <Edit2 className="w-3.5 h-3.5" />
            </button>

            <button
              onClick={() => onDelete(dashboard.id)}
              className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-all"
              title={t('card.delete')}
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Title & Icon */}
        <div className="flex items-start gap-3 mb-2.5">
          <div
            className={`p-3 rounded-xl ${theme.iconBg} shrink-0 transition-transform group-hover:scale-105 shadow-inner`}
          >
            <DynamicIcon name={dashboard.iconName} className="w-5 h-5" />
          </div>

          <div className="min-w-0 flex-1">
            <h3
              onClick={() => onOpen(dashboard)}
              className="font-bold text-slate-900 dark:text-slate-100 text-base leading-snug truncate hover:text-teal-600 dark:hover:text-teal-300 cursor-pointer transition-colors"
              title={dashboard.title}
            >
              {dashboard.title}
            </h3>
            <div className="flex items-center gap-2 mt-1 text-xs text-slate-500 dark:text-slate-400">
              <span className="flex items-center gap-1 font-medium truncate">
                <Building className="w-3 h-3 text-slate-400" />
                {dashboard.department}
              </span>
              <span>·</span>
              <span className="flex items-center gap-1 text-[11px] text-slate-500">
                <Clock className="w-3 h-3 text-slate-400" />
                {t(FREQ_LABEL_KEY[dashboard.updateFrequency] || dashboard.updateFrequency)}
              </span>
            </div>
          </div>
        </div>

        {/* Description */}
        <p className="text-xs text-slate-600 dark:text-slate-400 line-clamp-2 leading-relaxed mb-3.5 min-h-[36px]">
          {dashboard.description}
        </p>

        {/* Tags */}
        <div className="flex flex-wrap gap-1.5 mb-3.5">
          {dashboard.tags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="px-2 py-0.5 rounded-md text-[11px] bg-slate-100 dark:bg-slate-800/80 text-slate-600 dark:text-slate-400"
            >
              #{tag}
            </span>
          ))}
          {dashboard.tags.length > 3 && (
            <span className="px-1.5 py-0.5 rounded-md text-[10px] text-slate-400">
              +{dashboard.tags.length - 3}
            </span>
          )}
        </div>
      </div>

      {/* Bottom Area: URL / Stats & Action Buttons */}
      <div className="pt-3 border-t border-slate-100 dark:border-slate-800/90 space-y-2.5">
        {/* URL Pill with Copy */}
        <div className="flex items-center justify-between text-[11px] bg-slate-50 dark:bg-slate-800/50 px-2.5 py-1.5 rounded-lg border border-slate-200/60 dark:border-slate-700/60">
          <span className="font-mono text-slate-500 dark:text-slate-400 truncate flex-1 mr-2">
            {dashboard.url.replace(/^https?:\/\//, '')}
          </span>
          <button
            onClick={handleCopy}
            className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors shrink-0"
            title={t('card.copyUrl')}
          >
            {copied ? (
              <Check className="w-3.5 h-3.5 text-emerald-500" />
            ) : (
              <Copy className="w-3.5 h-3.5" />
            )}
          </button>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => onShowQR(dashboard)}
            className="p-2 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 transition-colors"
            title={t('card.qr')}
          >
            <QrCode className="w-4 h-4" />
          </button>

          <button
            onClick={() => onPreview(dashboard)}
            className="p-2 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 transition-colors"
            title={t('card.preview')}
          >
            <Eye className="w-4 h-4" />
          </button>

          <button
            onClick={() => onOpen(dashboard)}
            className="flex-1 px-4 py-2 rounded-xl bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 active:scale-[0.98] text-white font-medium text-xs flex items-center justify-center gap-1.5 shadow-sm shadow-teal-600/20 transition-all"
          >
            <span>{t('card.enter')}</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Visit stats */}
        <div className="flex items-center justify-between text-[10px] text-slate-400 px-1 pt-0.5">
          <span className="flex items-center gap-1">
            <TrendingUp className="w-3 h-3 text-slate-400" />
            {t('card.visits', { n: dashboard.clickCount })}
          </span>
          {dashboard.lastVisited && (
            <span>{t('card.last')}: {dashboard.lastVisited.split(' ')[1] || dashboard.lastVisited}</span>
          )}
        </div>
      </div>
    </div>
  );
};
