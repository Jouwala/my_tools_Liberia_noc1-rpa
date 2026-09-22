import React, { useState } from 'react';
import { X, BookOpen, Copy, Check } from 'lucide-react';
import { useI18n } from '../i18n';
import { DynamicIcon } from './DynamicIcon';

interface DocsIndexModalProps {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * 文档索引弹窗 —— 工作区 8 份体系文档（编号 01-08）的两列导航。
 *
 * 版式来源：需求图（左列 01/03/05/07，右列 02/04/06/08），
 * 骨架照抄同目录的 DesignGuideModal.tsx，保持门户弹窗风格一致。
 *
 * 说明：docs/*.md 目前**没有可访问 URL**（门户部署后 nginx 只服务 dist/，
 * 不服务仓库里的 md 文件），因此条目点击行为是**复制路径**而不是开新标签 ——
 * 做成链接会是死链。若将来 docs/ 随构建发布，再把这里换成 <a target="_blank">。
 */

/** 单条文档条目：编号 + lucide 图标名 + 文件名 + 一句话说明的 i18n 键后缀 */
interface DocEntry {
  no: string;
  icon: string;
  /** i18n 键后缀：docs.<key>T = 文件名，docs.<key> = 说明 */
  key: string;
  /** 相对仓库根的路径，供复制 */
  path: string;
}

/**
 * 左右两列的顺序即需求图上的视觉顺序：
 * 左列 01 / 03 / 05 / 07，右列 02 / 04 / 06 / 08。
 * 图标名对应图上的：机器人头像 / 清单 / 架构节点图 / 终端符号 / 调色板 / 文档页 / 用户头像 / 立方体。
 */
const LEFT_COLUMN: DocEntry[] = [
  { no: '01', icon: 'Bot', key: 'agents', path: 'AGENTS.md' },
  { no: '03', icon: 'ListChecks', key: 'todo', path: 'TODO.md' },
  { no: '05', icon: 'Network', key: 'architecture', path: 'architecture.md' },
  { no: '07', icon: 'Terminal', key: 'development', path: 'development.md' },
];

const RIGHT_COLUMN: DocEntry[] = [
  { no: '02', icon: 'Palette', key: 'design', path: 'DESIGN.md' },
  { no: '04', icon: 'FileText', key: 'overview', path: 'project-overview.md' },
  { no: '06', icon: 'UserRound', key: 'userguide', path: 'user-guide.md' },
  { no: '08', icon: 'Box', key: 'componentapi', path: 'component-api.md' },
];

export const DocsIndexModal: React.FC<DocsIndexModalProps> = ({ isOpen, onClose }) => {
  const { t } = useI18n();
  /* 复制反馈：记录刚复制的那条编号，1.5s 后清掉。用于给"已复制"的即时反馈。 */
  const [copied, setCopied] = useState<string | null>(null);

  if (!isOpen) return null;

  const copyPath = (entry: DocEntry) => {
    const text = `${entry.path}`;
    /* navigator.clipboard 在 http（非 https）下可能不可用，降级到 execCommand，
       失败则忽略 —— 复制只是便利功能，不该让弹窗报错。 */
    const done = () => {
      setCopied(entry.no);
      window.setTimeout(() => setCopied(null), 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(fallback);
    } else {
      fallback();
    }
    function fallback() {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        done();
      } catch {
        /* 复制不可用：静默忽略 */
      }
    }
  };

  const renderCard = (entry: DocEntry) => {
    const isCopied = copied === entry.no;
    return (
      <button
        key={entry.no}
        type="button"
        onClick={() => copyPath(entry)}
        title={t('docs.copyHint')}
        className="group relative overflow-hidden text-left bg-white dark:bg-slate-900 rounded-xl border border-slate-200/80 dark:border-slate-800 hover:border-teal-300 dark:hover:border-teal-800 shadow-[0_1px_2px_rgba(15,23,42,0.04)] hover:shadow-lg hover:-translate-y-0.5 transition-all duration-200 flex items-start gap-3 p-3.5 pl-4"
      >
        {/* 左侧 3px 竖条：与 QC 卡同一套状态语义（此处仅作品牌点缀） */}
        <span className="absolute left-0 top-0 h-full w-[3px] bg-teal-500"></span>

        <span className="p-2 rounded-lg bg-teal-50 text-teal-600 dark:bg-teal-950/40 dark:text-teal-400 shrink-0 transition-colors group-hover:bg-teal-100 dark:group-hover:bg-teal-900/40">
          <DynamicIcon name={entry.icon} className="w-4 h-4" />
        </span>

        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="text-[11px] font-mono font-bold text-slate-400 dark:text-slate-500">
              {entry.no}
            </span>
            <span className="text-[13px] font-semibold text-slate-800 dark:text-slate-100 truncate">
              {t(`docs.${entry.key}T`)}
            </span>
            <span className="ml-auto shrink-0 text-slate-300 dark:text-slate-600">
              {isCopied
                ? <Check className="w-3.5 h-3.5 text-emerald-500" />
                : <Copy className="w-3.5 h-3.5 opacity-0 group-hover:opacity-100 transition-opacity" />}
            </span>
          </span>
          <span className="block text-[11px] leading-tight mt-1 text-slate-500 dark:text-slate-400">
            {isCopied ? t('docs.copied') : t(`docs.${entry.key}`)}
          </span>
        </span>
      </button>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div className="spatial-modal-surface bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl max-w-4xl w-full max-h-[90vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between bg-gradient-to-r from-teal-50/50 via-white to-cyan-50/50 dark:from-teal-950/20 dark:via-slate-900 dark:to-cyan-950/20">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-gradient-to-r from-teal-600 to-cyan-600 text-white shadow-md shadow-teal-600/20">
              <BookOpen className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-slate-900 dark:text-slate-100 text-lg">
                {t('docs.title')}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('docs.subtitle')}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label={t('docs.close')}
            title={t('docs.close')}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* 两列：左 01/03/05/07，右 02/04/06/08（对齐需求图） */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="space-y-3">{LEFT_COLUMN.map(renderCard)}</div>
            <div className="space-y-3">{RIGHT_COLUMN.map(renderCard)}</div>
          </div>

          {/* 阅读顺序提示：编号是视觉顺序，实际阅读另有路径 */}
          <p className="text-[11px] leading-relaxed text-slate-400 dark:text-slate-500">
            {t('docs.orderNote')}
          </p>
        </div>

        {/* Footer：底部标语 + 关闭 */}
        <div className="px-6 py-3 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between gap-3">
          <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">
            {t('docs.slogan')}
          </span>
          <button
            onClick={onClose}
            className="px-5 py-2 text-xs font-semibold text-white bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 rounded-xl shadow-sm transition-all shrink-0"
          >
            {t('docs.ok')}
          </button>
        </div>
      </div>
    </div>
  );
};
