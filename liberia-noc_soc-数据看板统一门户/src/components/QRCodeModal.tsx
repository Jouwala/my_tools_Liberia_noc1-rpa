import React, { useState } from 'react';
import { X, Copy, Check, ExternalLink, Smartphone, Wifi, QrCode } from 'lucide-react';
import { DashboardItem } from '../types/dashboard';
import { useI18n } from '../i18n';
import { resolveUrl } from '../config';

interface QRCodeModalProps {
  dashboard: DashboardItem | null;
  onClose: () => void;
}

export const QRCodeModal: React.FC<QRCodeModalProps> = ({ dashboard, onClose }) => {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);

  if (!dashboard) return null;

  const targetUrl = resolveUrl(dashboard);

  const handleCopy = () => {
    navigator.clipboard.writeText(targetUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Generate QR code URL using public QR server or SVG fallback
  const qrCodeUrl = `https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=${encodeURIComponent(targetUrl)}&margin=10`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div className="spatial-modal-surface bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl w-full max-w-[95vw] sm:max-w-md overflow-hidden">
        {/* Header */}
        <div className="px-4 sm:px-6 py-3 sm:py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2 sm:gap-2.5 min-w-0">
            <div className="p-2 rounded-lg bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-300 shrink-0">
              <QrCode className="w-4 h-4 sm:w-5 sm:h-5" />
            </div>
            <div className="min-w-0">
              <h3 className="font-semibold text-slate-900 dark:text-slate-100 text-sm sm:text-base truncate">
                {t('qr.title')}
              </h3>
              <p className="text-[11px] sm:text-xs text-slate-500 dark:text-slate-400 truncate max-w-[180px] sm:max-w-[220px]">
                {dashboard.title}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* QR Display */}
        <div className="p-4 sm:p-6 flex flex-col items-center">
          <div className="p-3 sm:p-4 bg-white rounded-xl shadow-inner border border-slate-200 dark:border-slate-700 flex items-center justify-center">
            <img
              src={qrCodeUrl}
              alt="Dashboard QR Code"
              className="w-40 h-40 sm:w-52 sm:h-52 object-contain"
              onError={(e) => {
                (e.target as HTMLElement).style.display = 'none';
              }}
            />
          </div>

          {/* Intranet Tip */}
          <div className="mt-3 sm:mt-4 flex items-start gap-2 sm:gap-2.5 p-2.5 sm:p-3 bg-amber-50 dark:bg-amber-950/40 border border-amber-200/60 dark:border-amber-900/50 rounded-xl text-[11px] sm:text-xs text-amber-800 dark:text-amber-300 w-full">
            <Wifi className="w-4 h-4 shrink-0 mt-0.5" />
            <div>
              <p className="font-medium">{t('qr.tip')}</p>
              <p className="text-amber-700/90 dark:text-amber-400/90 mt-0.5">
                {t('qr.tipBody')}
              </p>
            </div>
          </div>

          {/* URL Box */}
          <div className="mt-3 sm:mt-4 w-full">
            <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">
              {t('qr.urlLabel')}
            </label>
            <div className="flex items-center gap-2 p-2 rounded-lg bg-slate-50 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700">
              <span className="text-xs font-mono text-slate-700 dark:text-slate-300 truncate flex-1 select-all">
                {targetUrl}
              </span>
              <button
                onClick={handleCopy}
                className="p-1.5 rounded-md hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors shrink-0"
                title={t('list.copy')}
              >
                {copied ? <Check className="w-4 h-4 text-emerald-500" /> : <Copy className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-4 sm:px-6 py-3 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-100 dark:border-slate-800 flex flex-col sm:flex-row justify-between items-center gap-2">
          <span className="text-xs text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
            <Smartphone className="w-3.5 h-3.5" /> {t('qr.support')}
          </span>
          <a
            href={targetUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs font-medium text-teal-600 dark:text-teal-300 hover:text-teal-700 dark:hover:text-teal-200"
          >
            {t('qr.openBrowser')} <ExternalLink className="w-3.5 h-3.5" />
          </a>
        </div>
      </div>
    </div>
  );
};
