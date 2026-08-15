import React from 'react';
import {
  X,
  Sparkles,
  Palette,
  Layout,
  Link2,
  Sliders,
  CheckCircle,
  Lightbulb,
  Monitor,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import { useI18n } from '../i18n';
import { getFinebiHost, getMyappHost } from '../config';

interface DesignGuideModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const DesignGuideModal: React.FC<DesignGuideModalProps> = ({ isOpen, onClose }) => {
  const { t } = useI18n();
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl max-w-4xl w-full max-h-[90vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between bg-gradient-to-r from-teal-50/50 via-white to-cyan-50/50 dark:from-teal-950/20 dark:via-slate-900 dark:to-cyan-950/20">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-gradient-to-r from-teal-600 to-cyan-600 text-white shadow-md shadow-teal-600/20">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-slate-900 dark:text-slate-100 text-lg flex items-center gap-2">
                {t('guide.title')}
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('guide.subtitle')}
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

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 text-sm text-slate-600 dark:text-slate-300">
          {/* Quick Principle Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 rounded-xl bg-gradient-to-br from-indigo-50/80 to-purple-50/30 dark:from-indigo-950/40 dark:to-purple-950/20 border border-indigo-100 dark:border-indigo-900/50">
              <div className="flex items-center gap-2 text-indigo-700 dark:text-indigo-300 font-semibold mb-2">
                <Palette className="w-4 h-4" />
                <span>{t('guide.c1t')}</span>
              </div>
              <p className="text-xs leading-relaxed text-slate-600 dark:text-slate-400">
                {t('guide.c1')}
              </p>
            </div>

            <div className="p-4 rounded-xl bg-gradient-to-br from-cyan-50/80 to-blue-50/30 dark:from-cyan-950/40 dark:to-blue-950/20 border border-cyan-100 dark:border-cyan-900/50">
              <div className="flex items-center gap-2 text-cyan-700 dark:text-cyan-300 font-semibold mb-2">
                <Layout className="w-4 h-4" />
                <span>{t('guide.c2t')}</span>
              </div>
              <p className="text-xs leading-relaxed text-slate-600 dark:text-slate-400">
                {t('guide.c2')}
              </p>
            </div>

            <div className="p-4 rounded-xl bg-gradient-to-br from-emerald-50/80 to-teal-50/30 dark:from-emerald-950/40 dark:to-teal-950/20 border border-emerald-100 dark:border-emerald-900/50">
              <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300 font-semibold mb-2">
                <Zap className="w-4 h-4" />
                <span>{t('guide.c3t')}</span>
              </div>
              <p className="text-xs leading-relaxed text-slate-600 dark:text-slate-400">
                {t('guide.c3')}
              </p>
            </div>
          </div>

          {/* Section 1: Visual Design */}
          <div className="space-y-3">
            <h4 className="font-bold text-slate-900 dark:text-slate-100 text-base flex items-center gap-2">
              <Lightbulb className="w-4 h-4 text-amber-500" />
              {t('guide.s1')}
            </h4>
            <div className="space-y-2 text-xs leading-relaxed">
              <div className="flex items-start gap-2.5">
                <CheckCircle className="w-4 h-4 text-indigo-500 shrink-0 mt-0.5" />
                <div>
                  <strong className="text-slate-800 dark:text-slate-200">{t('guide.s1aT')}</strong>
                  {t('guide.s1a')}
                </div>
              </div>
              <div className="flex items-start gap-2.5">
                <CheckCircle className="w-4 h-4 text-indigo-500 shrink-0 mt-0.5" />
                <div>
                  <strong className="text-slate-800 dark:text-slate-200">{t('guide.s1bT')}</strong>
                  {t('guide.s1b')}
                </div>
              </div>
              <div className="flex items-start gap-2.5">
                <CheckCircle className="w-4 h-4 text-indigo-500 shrink-0 mt-0.5" />
                <div>
                  <strong className="text-slate-800 dark:text-slate-200">{t('guide.s1cT')}</strong>
                  {t('guide.s1c')}
                </div>
              </div>
            </div>
          </div>

          {/* Section 2: Jump & Integration Architecture */}
          <div className="space-y-3">
            <h4 className="font-bold text-slate-900 dark:text-slate-100 text-base flex items-center gap-2">
              <Link2 className="w-4 h-4 text-cyan-500" />
              {t('guide.s2')}
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
              <div className="p-3.5 bg-slate-50 dark:bg-slate-800/60 rounded-xl border border-slate-200/80 dark:border-slate-700/80">
                <div className="font-semibold text-slate-800 dark:text-slate-200 mb-1 flex items-center gap-1.5">
                  <Monitor className="w-3.5 h-3.5 text-indigo-500" />
                  {t('guide.s2aT')}
                </div>
                <p className="text-slate-500 dark:text-slate-400">
                  {t('guide.s2a')}
                </p>
              </div>

              <div className="p-3.5 bg-slate-50 dark:bg-slate-800/60 rounded-xl border border-slate-200/80 dark:border-slate-700/80">
                <div className="font-semibold text-slate-800 dark:text-slate-200 mb-1 flex items-center gap-1.5">
                  <ShieldCheck className="w-3.5 h-3.5 text-cyan-500" />
                  {t('guide.s2bT')}
                </div>
                <p className="text-slate-500 dark:text-slate-400">
                  {t('guide.s2b')}
                </p>
              </div>
            </div>
          </div>

          {/* Section 3: FineBI Specific Tips */}
          <div className="space-y-3">
            <h4 className="font-bold text-slate-900 dark:text-slate-100 text-base flex items-center gap-2">
              <Sliders className="w-4 h-4 text-purple-500" />
              {t('guide.s3')}
            </h4>
            <div className="bg-slate-900 text-slate-200 rounded-xl p-3.5 font-mono text-xs space-y-2 border border-slate-800 overflow-x-auto">
              <div className="text-slate-400">{t('guide.urlNote1')}</div>
              <div className="text-emerald-400">{`http://${getFinebiHost()}/webroot/decision#/directory?activeTab=dec-tabs-homepage`}</div>
              
              <div className="text-slate-400 pt-1">{t('guide.urlNote2')}</div>
              <div className="text-indigo-300">{`http://${getFinebiHost()}/webroot/decision#view/contract-operation-kpis`}</div>
              <div className="text-indigo-300">{`http://${getFinebiHost()}/webroot/decision#view/4g-kpi-daily`}</div>

              <div className="text-slate-400 pt-1">{t('guide.urlNote3')}</div>
              <div className="text-cyan-300">{`http://${getMyappHost()}/myapp/  (Task Manager)`}</div>
              <div className="text-cyan-300">{`http://${getMyappHost()}/myapp/?page=alarm  (Alarm Dashboard)`}</div>
              <div className="text-cyan-300">{`http://${getMyappHost()}/myapp/?page=ttwo  (TT&WO Dashboard)`}</div>
              <div className="text-cyan-300">{`http://${getMyappHost()}/myapp/?page=nur  (NUR - Network Unavailability Rate)`}</div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-3 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-100 dark:border-slate-800 flex justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2 text-xs font-semibold text-white bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 rounded-xl shadow-sm transition-all"
          >
            {t('guide.ok')}
          </button>
        </div>
      </div>
    </div>
  );
};
