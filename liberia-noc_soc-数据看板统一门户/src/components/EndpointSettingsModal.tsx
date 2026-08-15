import React, { useState, useEffect } from 'react';
import { X, Server, Save, RotateCcw, CheckCircle2, Eye } from 'lucide-react';
import { getEnvConfig, type EnvConfig } from '../config';
import { useI18n } from '../i18n';

interface EndpointSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** 保存回调：由父组件负责持久化并重新应用到全部看板 */
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

  // 每次打开时从当前生效配置回填
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
    setDraft(getEnvConfig()); // 仅本地复位为当前默认值展示；真正复位请在保存逻辑中清除覆盖
    onSave({ finebiHost: '192.168.100.19', myappHost: '192.168.100.20', myappApiBase: '' });
    setSuccessMessage(t('eps.saved'));
    setTimeout(() => {
      setSuccessMessage('');
      onClose();
    }, 1600);
  };

  // 预览（基于草稿值即时拼接）
  const finebiPreview = `http://${draft.finebiHost || '—'}/webroot/decision#/directory?activeTab=dec-tabs-homepage`;
  const myappPreview = `http://${draft.myappHost || '—'}/myapp/`;
  const apiPreview = `${draft.myappApiBase?.trim() || '(同源)'}/api/tasks`;

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
                {t('eps.title')}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">{t('eps.subtitle')}</p>
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

          {/* 预览 */}
          <div className="p-3 bg-slate-50 dark:bg-slate-800/60 rounded-xl border border-slate-200/80 dark:border-slate-700">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-600 dark:text-slate-300 mb-2">
              <Eye className="w-3.5 h-3.5" />
              {t('eps.preview')}
            </div>
            <div className="space-y-1.5 text-[11px] font-mono text-slate-500 dark:text-slate-400 break-all">
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

          <div className="p-3 bg-amber-50 dark:bg-amber-950/30 rounded-xl border border-amber-200/80 dark:border-amber-900 text-xs text-amber-700 dark:text-amber-300">
            {t('eps.hint')}
          </div>

          {/* Actions */}
          <div className="pt-2 flex justify-between gap-2.5">
            <button
              type="button"
              onClick={handleReset}
              className="px-4 py-2 text-xs font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors flex items-center gap-1.5"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              {t('eps.reset')}
            </button>
            <div className="flex items-center gap-2.5">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
              >
                {t('modal.cancel')}
              </button>
              <button
                type="submit"
                disabled={!draft.finebiHost.trim() || !draft.myappHost.trim()}
                className="px-4 py-2 text-xs font-medium text-white bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg shadow-sm shadow-teal-600/20 transition-all flex items-center gap-1.5"
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
