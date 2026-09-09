import React, { useState, useEffect } from 'react';
import { X, Server, Save, RotateCcw, CheckCircle2, Eye } from 'lucide-react';
import { getEnvConfig, type EnvConfig } from '../config';
import { useI18n } from '../i18n';

interface EndpointSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (cfg: EnvConfig) => void;
}

const EMPTY: EnvConfig = { finebiHost: '', myappHost: '', myappApiBase: '' };

export const EndpointSettingsModal: React.FC<EndpointSettingsModalProps> = ({
  isOpen,
  onClose,
  onSave,
}) => {
  const { t } = useI18n();
  const [draft, setDraft] = useState<EnvConfig>(EMPTY);
  const [successMessage, setSuccessMessage] = useState('');

  useEffect(() => {
    if (isOpen) {
      setDraft(getEnvConfig());
      setSuccessMessage('');
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const update = (key: keyof EnvConfig, value: string) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  const handleApply = (e: React.FormEvent) => {
    e.preventDefault();
    if (!draft.finebiHost.trim() || !draft.myappHost.trim()) return;
    onSave(draft);
    setSuccessMessage(t('eps.saved'));
    setTimeout(() => {
      setSuccessMessage('');
      onClose();
    }, 1600);
  };

  const handleReset = () => {
    setDraft(getEnvConfig());
    onSave({ finebiHost: '192.168.100.19', myappHost: '192.168.100.20', myappApiBase: '' });
    setSuccessMessage(t('eps.saved'));
    setTimeout(() => {
      setSuccessMessage('');
      onClose();
    }, 1600);
  };

  const finebiPreview = `http://${draft.finebiHost || '—'}/webroot/decision#/directory?activeTab=dec-tabs-homepage`;
  const myappPreview = `http://${draft.myappHost || '—'}/myapp/`;
  const apiPreview = `${draft.myappApiBase?.trim() || '(同源)'}/api/tasks`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div className="spatial-modal-surface bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl w-full max-w-[95vw] sm:max-w-lg overflow-hidden">
        {/* Header */}
        <div className="px-4 sm:px-6 py-3 sm:py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2 sm:gap-2.5 min-w-0">
            <div className="p-2 rounded-lg bg-cyan-50 dark:bg-cyan-950/60 text-cyan-600 dark:text-cyan-400 shrink-0">
              <Server className="w-4 h-4 sm:w-5 sm:h-5" />
            </div>
            <div className="min-w-0">
              <h3 className="font-semibold text-slate-900 dark:text-slate-100 text-sm sm:text-base truncate">
                {t('eps.title')}
              </h3>
              <p className="text-[11px] sm:text-xs text-slate-500 dark:text-slate-400 truncate">{t('eps.subtitle')}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <form onSubmit={handleApply} className="p-4 sm:p-6 space-y-3 sm:space-y-4">
          {successMessage ? (
            <div className="p-3 sm:p-4 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900 rounded-xl flex items-center gap-3 text-emerald-700 dark:text-emerald-300 text-sm">
              <CheckCircle2 className="w-5 h-5 shrink-0" />
              <span>{successMessage}</span>
            </div>
          ) : null}

          <div className="space-y-3">
            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
                {t('eps.finebiHost')}
              </label>
              <input
                type="text"
                value={draft.finebiHost}
                onChange={(e) => update('finebiHost', e.target.value)}
                placeholder={t('eps.finebiHostPh')}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
                required
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
                {t('eps.myappHost')}
              </label>
              <input
                type="text"
                value={draft.myappHost}
                onChange={(e) => update('myappHost', e.target.value)}
                placeholder={t('eps.myappHostPh')}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
                required
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
                {t('eps.apiBase')}
              </label>
              <input
                type="text"
                value={draft.myappApiBase}
                onChange={(e) => update('myappApiBase', e.target.value)}
                placeholder={t('eps.apiBasePh')}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
              />
            </div>
          </div>

          {/* Preview */}
          <div className="p-2.5 sm:p-3 bg-slate-50 dark:bg-slate-800/60 rounded-xl border border-slate-200/80 dark:border-slate-700">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-600 dark:text-slate-300 mb-2">
              <Eye className="w-3.5 h-3.5" />
              {t('eps.preview')}
            </div>
            <div className="space-y-1 sm:space-y-1.5 text-[10px] sm:text-[11px] font-mono text-slate-500 dark:text-slate-400 break-all">
              <div>
                <span className="text-slate-400">{t('eps.previewFinebi')}：</span>
                {finebiPreview}
              </div>
              <div>
                <span className="text-slate-400">{t('eps.previewMyapp')}：</span>
                {myappPreview}
              </div>
              <div>
                <span className="text-slate-400">{t('eps.previewApi')}：</span>
                {apiPreview}
              </div>
            </div>
          </div>

          <div className="p-2.5 sm:p-3 bg-amber-50 dark:bg-amber-950/30 rounded-xl border border-amber-200/80 dark:border-amber-900 text-xs text-amber-700 dark:text-amber-300">
            {t('eps.hint')}
          </div>

          {/* Actions */}
          <div className="pt-2 flex flex-col sm:flex-row justify-between gap-2 sm:gap-2.5">
            <button
              type="button"
              onClick={handleReset}
              className="w-full sm:w-auto px-4 py-2 text-xs font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors flex items-center justify-center gap-1.5"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              {t('eps.reset')}
            </button>
            <div className="flex items-center gap-2.5">
              <button
                type="button"
                onClick={onClose}
                className="flex-1 sm:flex-none px-4 py-2 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
              >
                {t('modal.cancel')}
              </button>
              <button
                type="submit"
                disabled={!draft.finebiHost.trim() || !draft.myappHost.trim()}
                className="flex-1 sm:flex-none px-4 py-2 text-xs font-medium text-white bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg shadow-sm shadow-teal-600/20 transition-all flex items-center justify-center gap-1.5"
              >
                <Save className="w-3.5 h-3.5" />
                {t('eps.apply')}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};
