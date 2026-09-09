import React, { useState } from 'react';
import {
  ExternalLink,
  Star,
  Pin,
  Clock,
  Building,
  QrCode,
  Eye,
  EyeOff,
  Copy,
  Check,
  Edit2,
  Trash2,
} from 'lucide-react';
import { DashboardItem } from '../types/dashboard';
import { DynamicIcon } from './DynamicIcon';
import { resolveUrl } from '../config';
import { FREQ_LABEL_KEY, useI18n } from '../i18n';

interface DashboardListViewProps {
  dashboards: DashboardItem[];
  onOpen: (d: DashboardItem) => void;
  onPreview: (d: DashboardItem) => void;
  onShowQR: (d: DashboardItem) => void;
  onToggleFavorite: (id: string) => void;
  onToggleHidden: (id: string) => void;
  onEdit: (d: DashboardItem) => void;
  onDelete: (id: string) => void;
}

export const DashboardListView: React.FC<DashboardListViewProps> = ({
  dashboards,
  onOpen,
  onPreview,
  onShowQR,
  onToggleFavorite,
  onToggleHidden,
  onEdit,
  onDelete,
}) => {
  const { t } = useI18n();
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const handleCopy = (id: string, url: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(url);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="spatial-panel bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm overflow-hidden">
      <div className="overflow-x-auto wh-table-responsive">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-800 bg-slate-50/80 dark:bg-slate-800/50 text-[10px] sm:text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              <th className="py-3 pl-4 sm:pl-5 pr-2 w-10">{t('list.colFav')}</th>
              <th className="py-3 px-3 sm:px-4 min-w-[200px] sm:min-w-[260px]">{t('list.colName')}</th>
              <th className="py-3 px-3 sm:px-4 min-w-[110px] sm:min-w-[130px]">{t('list.colPlatform')}</th>
              <th className="py-3 px-3 sm:px-4 min-w-[100px] sm:min-w-[120px]">{t('list.colDept')}</th>
              <th className="py-3 px-3 sm:px-4 min-w-[100px] sm:min-w-[110px]">{t('list.colFreq')}</th>
              <th className="py-3 px-3 sm:px-4 min-w-[200px] sm:min-w-[240px]">{t('list.colUrl')}</th>
              <th className="py-3 px-3 sm:px-4 min-w-[80px] sm:min-w-[90px] text-right">{t('list.colClicks')}</th>
              <th className="py-3 pl-3 sm:pl-4 pr-4 sm:pr-6 min-w-[160px] sm:min-w-[180px] text-right">{t('list.colActions')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-[11px] sm:text-xs">
            {dashboards.map((board) => (
              <tr
                key={board.id}
                className={`hover:bg-teal-50/40 dark:hover:bg-navy-800/40 transition-colors group ${
                  board.hidden ? 'opacity-50 saturate-[0.65]' : ''
                }`}
              >
                {/* Favorite Star */}
                <td className="py-3 pl-4 sm:pl-5 pr-2">
                  <button
                    onClick={() => onToggleFavorite(board.id)}
                    className={`transition-colors ${
                      board.isFavorite
                        ? 'text-amber-400 hover:text-amber-500'
                        : 'text-slate-300 dark:text-slate-600 hover:text-amber-400'
                    }`}
                  >
                    <Star
                      className="w-4 h-4"
                      fill={board.isFavorite ? 'currentColor' : 'none'}
                    />
                  </button>
                </td>

                {/* Title & Icon */}
                <td className="py-3 px-3 sm:px-4">
                  <div className="flex items-center gap-2 sm:gap-3">
                    <div className="p-1.5 sm:p-2 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 shrink-0">
                      <DynamicIcon name={board.iconName} className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-1 sm:gap-1.5">
                        <span
                          onClick={() => onOpen(board)}
                          className="font-semibold text-slate-900 dark:text-slate-100 hover:text-teal-600 dark:hover:text-teal-300 cursor-pointer truncate max-w-[200px] sm:max-w-[280px]"
                        >
                          {board.title}
                        </span>
                        {board.isPinned && (
                          <span className="p-0.5 rounded bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300">
                            <Pin className="w-2.5 h-2.5" />
                          </span>
                        )}
                      </div>
                      <p className="text-[10px] sm:text-[11px] text-slate-500 dark:text-slate-400 truncate max-w-[200px] sm:max-w-[280px]">
                        {board.description}
                      </p>
                    </div>
                  </div>
                </td>

                {/* Platform */}
                <td className="py-3 px-3 sm:px-4">
                  <span
                    className={`inline-flex items-center gap-1 px-2 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-[11px] font-medium ${
                      board.platform === 'finebi'
                        ? 'bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800/80'
                        : board.platform === 'custom'
                        ? 'bg-cyan-50 dark:bg-cyan-950/60 text-cyan-700 dark:text-cyan-300 border border-cyan-200 dark:border-cyan-800/80'
                        : 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/80'
                    }`}
                  >
                    {board.platform === 'finebi'
                      ? t('list.platformFinebi')
                      : board.platform === 'custom'
                      ? t('list.platformCustom')
                      : t('list.platformExternal')}
                  </span>
                </td>

                {/* Department & Owner */}
                <td className="py-3 px-3 sm:px-4 text-slate-600 dark:text-slate-300">
                  <div className="font-medium truncate">{board.department}</div>
                  <div className="text-[10px] sm:text-[11px] text-slate-400 truncate">{board.owner}</div>
                </td>

                {/* Update Frequency */}
                <td className="py-3 px-3 sm:px-4 text-slate-500 dark:text-slate-400">
                  <span className="inline-flex items-center gap-1 text-[10px] sm:text-[11px]">
                    <Clock className="w-3 h-3 text-slate-400" />
                    {t(FREQ_LABEL_KEY[board.updateFrequency] || board.updateFrequency)}
                  </span>
                </td>

                {/* URL with Copy */}
                <td className="py-3 px-3 sm:px-4 font-mono text-[10px] sm:text-[11px] text-slate-500 dark:text-slate-400">
                  <div className="flex items-center gap-1 sm:gap-1.5 max-w-[200px] sm:max-w-[240px]">
                    <span className="truncate flex-1">{resolveUrl(board)}</span>
                    <button
                      onClick={(e) => handleCopy(board.id, resolveUrl(board), e)}
                      className="p-1 hover:bg-slate-100 dark:hover:bg-slate-800 rounded text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors shrink-0"
                      title={t('list.copy')}
                    >
                      {copiedId === board.id ? (
                        <Check className="w-3 h-3 text-emerald-500" />
                      ) : (
                        <Copy className="w-3 h-3" />
                      )}
                    </button>
                  </div>
                </td>

                {/* Click Count */}
                <td className="py-3 px-3 sm:px-4 text-right font-medium text-slate-600 dark:text-slate-300">
                  {board.clickCount} {t('list.times')}
                </td>

                {/* Actions */}
                <td className="py-3 pl-3 sm:pl-4 pr-4 sm:pr-6 text-right">
                  <div className="flex items-center justify-end gap-1 sm:gap-1.5">
                    <button
                      onClick={() => onShowQR(board)}
                      className="p-1 sm:p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                      title={t('list.qr')}
                    >
                      <QrCode className="w-3 h-3 sm:w-3.5 sm:h-3.5" />
                    </button>

                    <button
                      onClick={() => onPreview(board)}
                      className="p-1 sm:p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                      title={t('list.preview')}
                    >
                      <Eye className="w-3 h-3 sm:w-3.5 sm:h-3.5" />
                    </button>

                    <button
                      onClick={() => onEdit(board)}
                      className="p-1 sm:p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                      title={t('list.edit')}
                    >
                      <Edit2 className="w-3 h-3 sm:w-3.5 sm:h-3.5" />
                    </button>

                    <button
                      onClick={() => onDelete(board.id)}
                      className="p-1 sm:p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors"
                      title={t('list.delete')}
                    >
                      <Trash2 className="w-3 h-3 sm:w-3.5 sm:h-3.5" />
                    </button>

                    {/* 本机隐藏/恢复：只影响当前浏览器，不影响服务端默认与其他电脑 */}
                    <button
                      onClick={() => onToggleHidden(board.id)}
                      className={`p-1 sm:p-1.5 rounded-lg transition-colors ${
                        board.hidden
                          ? 'text-teal-600 dark:text-teal-400 hover:bg-teal-50 dark:hover:bg-teal-950/40'
                          : 'text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800'
                      }`}
                      title={board.hidden ? t('card.unhide') : t('card.hide')}
                    >
                      {board.hidden ? (
                        <Eye className="w-3 h-3 sm:w-3.5 sm:h-3.5" />
                      ) : (
                        <EyeOff className="w-3 h-3 sm:w-3.5 sm:h-3.5" />
                      )}
                    </button>

                    <button
                      onClick={() => onOpen(board)}
                      className="ml-0 sm:ml-1 px-2 sm:px-3 py-1 sm:py-1.5 rounded-lg bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 text-white font-medium text-[10px] sm:text-xs flex items-center gap-1 transition-all shadow-sm"
                    >
                      <span>{t('list.open')}</span>
                      <ExternalLink className="w-2.5 h-2.5 sm:w-3 sm:h-3" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
