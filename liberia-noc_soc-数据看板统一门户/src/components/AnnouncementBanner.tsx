import React, { useState } from 'react';
import { Megaphone, X, ChevronRight, Radio } from 'lucide-react';

export const AnnouncementBanner: React.FC = () => {
  const [isVisible, setIsVisible] = useState(true);

  if (!isVisible) return null;

  return (
    <div className="bg-gradient-to-r from-indigo-600 via-indigo-700 to-cyan-700 text-white px-4 py-2 text-xs font-medium shadow-sm transition-all">
      <div className="max-w-7xl mx-auto flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 overflow-hidden">
          <span className="flex items-center gap-1 bg-white/20 px-2 py-0.5 rounded-full text-[10px] font-semibold tracking-wide shrink-0">
            <Radio className="w-3 h-3 animate-pulse text-cyan-200" /> NOC/SOC 实时同步
          </span>
          <p className="truncate text-indigo-50">
            【Liberia Data Portal & Data Insight MVP】FineBI 报表决策中心与自研系统 ZTE eFlow API、FM 活动告警及 2G/3G/4G 性能指标保持分钟级同步，支持内网直通与移动巡检。
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setIsVisible(false)}
            className="p-1 hover:bg-white/20 rounded-md text-indigo-100 hover:text-white transition-colors"
            title="关闭公告"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
};
