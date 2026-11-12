import React, { useState } from 'react';
import { Megaphone, X, ChevronRight, Radio } from 'lucide-react';
import { useI18n } from '../i18n';

export const AnnouncementBanner: React.FC = () => {
  const { t } = useI18n();
  const [isVisible, setIsVisible] = useState(true);

  if (!isVisible) return null;

  return (
    <div className="spatial-banner text-white px-3 sm:px-4 py-1.5 sm:py-2 text-[11px] sm:text-xs font-medium">
      <div className="w-full mx-auto flex items-center justify-between gap-2 sm:gap-3">
        <div className="flex items-center gap-1.5 sm:gap-2 overflow-hidden min-w-0">
          <span className="flex items-center gap-1 bg-white/15 border border-white/30 px-1.5 sm:px-2 py-0.5 rounded-full text-[9px] sm:text-[10px] font-semibold tracking-wide shrink-0">
            <Radio className="w-3 h-3 animate-pulse text-white" /> {t('banner.liveBadge')}
          </span>
          <p className="truncate text-white/90">
            {t('banner.text')}
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setIsVisible(false)}
            className="p-1 hover:bg-white/10 rounded-md text-white/80 hover:text-white transition-colors"
            title={t('banner.close')}
          >
            <X className="w-3 h-3 sm:w-3.5 sm:h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
};
