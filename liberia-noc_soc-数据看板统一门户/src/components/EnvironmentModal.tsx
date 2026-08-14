import React, { useState } from 'react';
import { X, Server, ArrowRight, RefreshCw, CheckCircle2, ShieldAlert } from 'lucide-react';
import { DashboardItem } from '../types/dashboard';
import { DEFAULT_HOST } from '../config';
import { useI18n } from '../i18n';

interface EnvironmentModalProps {
  isOpen: boolean;
  onClose: () => void;
  dashboards: DashboardItem[];
  onBatchUpdateUrls: (oldHost: string, newHost: string) => void;
}

export const EnvironmentModal: React.FC<EnvironmentModalProps> = ({
  isOpen,
  onClose,
  dashboards,
  onBatchUpdateUrls,
}) => {
  const { t } = useI18n();
  const [sourceHost, setSourceHost] = useState(DEFAULT_HOST);
  const [targetHost, setTargetHost] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  if (!isOpen) return null;

  // Count matching dashboards
  const matchCount = dashboards.filter((d) => d.url.includes(sourceHost)).length;

  const handleApply = (e: React.FormEvent) => {
    e.preventDefault();
    if (!sourceHost || !targetHost) return;
    onBatchUpdateUrls(sourceHost, targetHost);
    setSuccessMessage(t('env.success', { n: matchCount, host: targetHost }));
    setTimeout(() => {
      setSuccessMessage('');
      onClose();
    }, 1800);
  };

  const presetEnvs = [
    { label: t('env.presetProd'), host: DEFAULT_HOST },
    { label: t('env.presetDev'), host: `${DEFAULT_HOST}:7090` },
    { label: t('env.presetLocal'), host: '127.0.0.1' },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl max-w-lg w-full overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-cyan-50 dark:bg-cyan-950/60 text-cyan-600 dark:text-cyan-400">
              <Server className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-semibold text-slate-900 dark:text-slate-100 text-base">
                {t('env.title')}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('env.subtitle')}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <form onSubmit={handleApply} className="p-6 space-y-4">
          {successMessage ? (
            <div className="p-4 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900 rounded-xl flex items-center gap-3 text-emerald-700 dark:text-emerald-300 text-sm">
              <CheckCircle2 className="w-5 h-5 shrink-0" />
              <span>{successMessage}</span>
            </div>
          ) : null}

          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
              {t('env.presets')}
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {presetEnvs.map((preset) => (
                <button
                  type="button"
                  key={preset.host}
                  onClick={() => setTargetHost(preset.host)}
                  className={`p-2.5 rounded-xl text-left border text-xs transition-all ${
                    targetHost === preset.host
                      ? 'border-teal-500 bg-teal-50/70 dark:bg-teal-950/50 text-teal-700 dark:text-teal-300 font-medium ring-2 ring-teal-500/20'
                      : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600 bg-slate-50/50 dark:bg-slate-800/40 text-slate-700 dark:text-slate-300'
                  }`}
                >
                  <div className="font-medium truncate">{preset.label}</div>
                  <div className="font-mono text-slate-500 dark:text-slate-400 text-[11px] mt-0.5">
                    {preset.host}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="pt-2 border-t border-slate-100 dark:border-slate-800">
            <div className="flex items-center gap-3">
              <div className="flex-1">
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                  {t('env.source')}
                </label>
                <input
                  type="text"
                  value={sourceHost}
                  onChange={(e) => setSourceHost(e.target.value)}
                  placeholder={t('env.sourcePh')}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
                  required
                />
              </div>

              <div className="mt-5 text-slate-400">
                <ArrowRight className="w-4 h-4" />
              </div>

              <div className="flex-1">
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
                  {t('env.target')}
                </label>
                <input
                  type="text"
                  value={targetHost}
                  onChange={(e) => setTargetHost(e.target.value)}
                  placeholder={t('env.targetPh')}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-xs font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
                  required
                />
              </div>
            </div>

            <div className="mt-3 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
              <span>{t('env.match')}</span>
              <span className="font-semibold text-teal-600 dark:text-teal-300">
                {matchCount} {t('env.matchUnit')}
              </span>
            </div>
          </div>

          <div className="p-3 bg-slate-50 dark:bg-slate-800/60 rounded-xl border border-slate-200/80 dark:border-slate-700 text-xs text-slate-600 dark:text-slate-400 flex items-start gap-2">
            <ShieldAlert className="w-4 h-4 text-cyan-600 shrink-0 mt-0.5" />
            <p>
              {t('env.hint')}
            </p>
          </div>

          {/* Actions */}
          <div className="pt-2 flex justify-end gap-2.5">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
            >
              {t('modal.cancel')}
            </button>
            <button
              type="submit"
              disabled={!targetHost || matchCount === 0}
              className="px-4 py-2 text-xs font-medium text-white bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg shadow-sm shadow-teal-600/20 transition-all flex items-center gap-1.5"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              {t('env.apply')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
