import React, { useState } from 'react';
import { Megaphone, X, ChevronRight, Radio } from 'lucide-react';
import { useI18n } from '../i18n';

export const AnnouncementBanner: React.FC = () => {
  const { t } = useI18n();
  const [isVisible, setIsVisible] = useState(true);

  if (!isVisible) return null;

  return (
    <div className="bg-gradient-to-r from-teal-600 via-cyan-700 to-navy-900 text-white dark:bg-gradient-to-r dark:from-navy-950 dark:via-navy-900 dark:to-teal-900 px-4 py-2 text-xs font-medium shadow-sm transition-all">
      <div className="max-w-7xl mx-auto flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 overflow-hidden">
          <span className="flex items-center gap-1 bg-teal-400/15 border border-teal-400/30 px-2 py-0.5 rounded-full text-[10px] font-semibold tracking-wide shrink-0">
            <Radio className="w-3 h-3 animate-pulse text-teal-300" /> {t('banner.liveBadge')}
          </span>
          <p className="truncate text-teal-50/90">
            {t('banner.text')}
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setIsVisible(false)}
            className="p-1 hover:bg-white/10 rounded-md text-teal-200 hover:text-white transition-colors"
            title={t('banner.close')}
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
};
