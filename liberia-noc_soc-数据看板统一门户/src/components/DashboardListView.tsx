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
} from 'lucide-react';
import { DashboardItem } from '../types/dashboard';
import { DynamicIcon } from './DynamicIcon';

interface DashboardListViewProps {
  dashboards: DashboardItem[];
  onOpen: (d: DashboardItem) => void;
  onPreview: (d: DashboardItem) => void;
  onShowQR: (d: DashboardItem) => void;
  onToggleFavorite: (id: string) => void;
  onEdit: (d: DashboardItem) => void;
  onDelete: (id: string) => void;
}

export const DashboardListView: React.FC<DashboardListViewProps> = ({
  dashboards,
  onOpen,
  onPreview,
  onShowQR,
  onToggleFavorite,
  onEdit,
  onDelete,
}) => {
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const handleCopy = (id: string, url: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(url);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-sm overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-800 bg-slate-50/80 dark:bg-slate-800/50 text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              <th className="py-3.5 pl-5 pr-2 w-10">收藏</th>
              <th className="py-3.5 px-4 min-w-[260px]">看板名称 / 业务属性</th>
              <th className="py-3.5 px-4 min-w-[130px]">所属平台</th>
              <th className="py-3.5 px-4 min-w-[120px]">部门 / 负责人</th>
              <th className="py-3.5 px-4 min-w-[110px]">更新频次</th>
              <th className="py-3.5 px-4 min-w-[240px]">目标访问地址 (URL)</th>
              <th className="py-3.5 px-4 min-w-[90px] text-right">热度</th>
              <th className="py-3.5 pl-4 pr-6 min-w-[180px] text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-xs">
            {dashboards.map((board) => (
              <tr
                key={board.id}
                className="hover:bg-indigo-50/30 dark:hover:bg-slate-800/40 transition-colors group"
              >
                {/* Favorite Star */}
                <td className="py-3.5 pl-5 pr-2">
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
                <td className="py-3.5 px-4">
                  <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 shrink-0">
                      <DynamicIcon name={board.iconName} className="w-4 h-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span
                          onClick={() => onOpen(board)}
                          className="font-semibold text-slate-900 dark:text-slate-100 hover:text-indigo-600 dark:hover:text-indigo-400 cursor-pointer truncate max-w-[280px]"
                        >
                          {board.title}
                        </span>
                        {board.isPinned && (
                          <span className="p-0.5 rounded bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300">
                            <Pin className="w-2.5 h-2.5" />
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-slate-500 dark:text-slate-400 truncate max-w-[280px]">
                        {board.description}
                      </p>
                    </div>
                  </div>
                </td>

                {/* Platform */}
                <td className="py-3.5 px-4">
                  <span
                    className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium ${
                      board.platform === 'finebi'
                        ? 'bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800/80'
                        : board.platform === 'custom'
                        ? 'bg-cyan-50 dark:bg-cyan-950/60 text-cyan-700 dark:text-cyan-300 border border-cyan-200 dark:border-cyan-800/80'
                        : 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/80'
                    }`}
                  >
                    {board.platform === 'finebi'
                      ? 'FineBI 平台'
                      : board.platform === 'custom'
                      ? '自研系统'
                      : '外部大屏'}
                  </span>
                </td>

                {/* Department & Owner */}
                <td className="py-3.5 px-4 text-slate-600 dark:text-slate-300">
                  <div className="font-medium truncate">{board.department}</div>
                  <div className="text-[11px] text-slate-400 truncate">{board.owner}</div>
                </td>

                {/* Update Frequency */}
                <td className="py-3.5 px-4 text-slate-500 dark:text-slate-400">
                  <span className="inline-flex items-center gap-1 text-[11px]">
                    <Clock className="w-3 h-3 text-slate-400" />
                    {board.updateFrequency}
                  </span>
                </td>

                {/* URL with Copy */}
                <td className="py-3.5 px-4 font-mono text-[11px] text-slate-500 dark:text-slate-400">
                  <div className="flex items-center gap-1.5 max-w-[240px]">
                    <span className="truncate flex-1">{board.url}</span>
                    <button
                      onClick={(e) => handleCopy(board.id, board.url, e)}
                      className="p-1 hover:bg-slate-100 dark:hover:bg-slate-800 rounded text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors shrink-0"
                      title="复制链接"
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
                <td className="py-3.5 px-4 text-right font-medium text-slate-600 dark:text-slate-300">
                  {board.clickCount} 次
                </td>

                {/* Actions */}
                <td className="py-3.5 pl-4 pr-6 text-right">
                  <div className="flex items-center justify-end gap-1.5">
                    <button
                      onClick={() => onShowQR(board)}
                      className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                      title="扫码"
                    >
                      <QrCode className="w-3.5 h-3.5" />
                    </button>

                    <button
                      onClick={() => onPreview(board)}
                      className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                      title="预览"
                    >
                      <Eye className="w-3.5 h-3.5" />
                    </button>

                    <button
                      onClick={() => onEdit(board)}
                      className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                      title="编辑"
                    >
                      <Edit2 className="w-3.5 h-3.5" />
                    </button>

                    <button
                      onClick={() => onDelete(board.id)}
                      className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors"
                      title="删除"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>

                    <button
                      onClick={() => onOpen(board)}
                      className="ml-1 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-medium text-xs flex items-center gap-1 transition-all shadow-sm"
                    >
                      <span>打开</span>
                      <ExternalLink className="w-3 h-3" />
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
