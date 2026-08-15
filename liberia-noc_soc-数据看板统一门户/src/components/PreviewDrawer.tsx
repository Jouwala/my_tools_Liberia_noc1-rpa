import React, { useState } from 'react';
import {
  X,
  ExternalLink,
  Maximize2,
  RefreshCw,
  AlertTriangle,
  Copy,
  Check,
  ShieldCheck,
} from 'lucide-react';
import { DashboardItem } from '../types/dashboard';
import { FREQ_LABEL_KEY, useI18n } from '../i18n';
import { resolveUrl } from '../config';

interface PreviewDrawerProps {
  dashboard: DashboardItem | null;
  onClose: () => void;
  onOpenExternal: (d: DashboardItem) => void;
}

export const PreviewDrawer: React.FC<PreviewDrawerProps> = ({
  dashboard,
  onClose,
  onOpenExternal,
}) => {
  const { t } = useI18n();
  const [iframeKey, setIframeKey] = useState(0);
  const [copied, setCopied] = useState(false);
  const [iframeError, setIframeError] = useState(false);

  if (!dashboard) return null;

  const handleCopy = () => {
    navigator.clipboard.writeText(resolveUrl(dashboard));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-black/70 backdrop-blur-sm animate-fadeIn">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl w-full h-[94vh] max-w-7xl flex flex-col overflow-hidden">
        {/* Top Header Bar */}
        <div className="px-5 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between bg-slate-50/80 dark:bg-slate-900/80">
          <div className="flex items-center gap-3 min-w-0">
            <div
              className={`px-2.5 py-1 rounded-md text-xs font-semibold uppercase ${
                dashboard.platform === 'finebi'
                  ? 'bg-indigo-100 dark:bg-indigo-950/80 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800'
                  : dashboard.platform === 'custom'
                  ? 'bg-cyan-100 dark:bg-cyan-950/80 text-cyan-700 dark:text-cyan-300 border border-cyan-200 dark:border-cyan-800'
                  : 'bg-emerald-100 dark:bg-emerald-950/80 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800'
              }`}
            >
              {dashboard.platform === 'finebi'
                ? t('preview.finebi')
                : dashboard.platform === 'custom'
                ? t('preview.custom')
                : t('preview.external')}
            </div>

            <div className="min-w-0">
              <h3 className="font-bold text-slate-900 dark:text-slate-100 text-sm sm:text-base truncate">
                {dashboard.title}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 font-mono truncate hidden sm:block">
                {resolveUrl(dashboard)}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={handleCopy}
              className="p-2 rounded-lg text-slate-500 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-200/60 dark:hover:bg-slate-800 transition-colors text-xs flex items-center gap-1"
              title={t('list.copy')}
            >
              {copied ? (
                <Check className="w-4 h-4 text-emerald-500" />
              ) : (
                <Copy className="w-4 h-4" />
              )}
              <span className="hidden sm:inline">{t('preview.copy')}</span>
            </button>

            <button
              onClick={() => setIframeKey((k) => k + 1)}
              className="p-2 rounded-lg text-slate-500 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-200/60 dark:hover:bg-slate-800 transition-colors"
              title={t('preview.refresh')}
            >
              <RefreshCw className="w-4 h-4" />
            </button>

            <button
              onClick={() => onOpenExternal(dashboard)}
              className="px-3 py-1.5 rounded-lg bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 text-white font-medium text-xs flex items-center gap-1.5 shadow-sm shadow-teal-600/20 transition-all"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              <span>{t('preview.fullscreen')}</span>
            </button>

            <button
              onClick={onClose}
              className="p-2 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-200/60 dark:hover:bg-slate-800 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Notice for cross-origin or intranet */}
        <div className="px-4 py-2 bg-amber-50 dark:bg-amber-950/40 border-b border-amber-200/60 dark:border-amber-900/40 text-xs text-amber-800 dark:text-amber-300 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <span>
              {t('preview.warn')}
            </span>
          </div>
          <button
            onClick={() => onOpenExternal(dashboard)}
            className="font-semibold underline ml-2 shrink-0 hover:text-amber-900 dark:hover:text-amber-200"
          >
            {t('preview.jump')}
          </button>
        </div>

        {/* Main Iframe Canvas */}
        <div className="flex-1 bg-slate-950 relative overflow-hidden">
          <iframe
            key={iframeKey}
            src={resolveUrl(dashboard)}
            title={dashboard.title}
            className="w-full h-full border-none bg-white"
            sandbox="allow-same-origin allow-scripts allow-popups allow-forms allow-downloads"
            onError={() => setIframeError(true)}
          />
        </div>

        {/* Footer info */}
        <div className="px-5 py-2.5 bg-slate-50 dark:bg-slate-900 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
          <div className="flex items-center gap-4">
            <span>{t('preview.dept')}：{dashboard.department}</span>
            <span>{t('preview.owner')}：{dashboard.owner}</span>
            <span>{t('preview.freq')}：{t(FREQ_LABEL_KEY[dashboard.updateFrequency] || dashboard.updateFrequency)}</span>
          </div>
          <div className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>{t('preview.ready')}</span>
          </div>
        </div>
      </div>
    </div>
  );
};
