import React, { useState } from 'react';
import {
  Activity,
  CheckCircle2,
  Clock,
  Play,
  RotateCw,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  Server,
  Layers,
} from 'lucide-react';

export const TaskSyncWidget: React.FC = () => {
  const [isExpanded, setIsExpanded] = useState(false);

  const tasks = [
    {
      name: 'eFlow Daily Full Sync',
      type: 'ZTE eFlow API',
      schedule: 'Daily 08:00',
      nextRun: '2026-08-15 08:00 AM (in ~17h)',
      lastRun: '2026-08-14 08:03:27',
      duration: '478.4s',
      status: 'idle',
      desc: 'eFlow daily full backfill sync (full window), refresh reports',
    },
    {
      name: 'eFlow Data Sync',
      type: 'ZTE eFlow API',
      schedule: 'Every hour at :0',
      nextRun: '2026-08-14 04:00:00 PM (in ~1h)',
      lastRun: '2026-08-14 14:00:01',
      duration: '283.9s',
      status: 'running',
      desc: 'Fetch TT/WO/CR/PM/Site/Person data from ZTE eFlow API',
    },
    {
      name: 'eFlow Realtime Alarm Sync',
      type: 'ZTE eFlow API',
      schedule: 'Every hour at :*/5',
      nextRun: '2026-08-14 03:05:00 PM (in ~5m)',
      lastRun: '2026-08-14 14:55:01',
      duration: '30.4s',
      status: 'running',
      desc: 'Fetch realtime alarms from eFlow FM Active API, save to CSV + SQLite',
    },
    {
      name: 'Incident Overview Data Sync',
      type: 'Incident Sync',
      schedule: 'Every hour at :3',
      nextRun: '2026-08-14 03:03:00 PM (in ~3m)',
      lastRun: '2026-08-14 14:10:01',
      duration: '0.1s',
      status: 'idle',
      desc: 'Hourly on-the-hour: pull incident_overview.xlsx from remote FineBI FTP',
    },
  ];

  return (
    <div className="mb-6 bg-gradient-to-r from-slate-900 via-slate-900 to-indigo-950 text-white rounded-2xl p-4 sm:p-5 border border-slate-800 shadow-lg">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-cyan-500/20 text-cyan-400 border border-cyan-500/30">
            <Activity className="w-5 h-5 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-bold text-sm sm:text-base tracking-tight text-white flex items-center gap-2">
                Data Insight 自动化任务调度中心 (Task Manager)
              </h3>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                运行中
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              实时同步 ZTE eFlow API 工单、FM 活动告警与 FineBI 报表数据源
            </p>
          </div>
        </div>

        {/* Stats Pills */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 bg-slate-800/80 px-3 py-1.5 rounded-xl border border-slate-700/60 text-xs">
            <span className="text-slate-400">全部:</span>
            <span className="font-mono font-bold text-white">34</span>
            <span className="text-slate-600">|</span>
            <span className="text-cyan-400 flex items-center gap-1">
              <RotateCw className="w-3 h-3 animate-spin" /> 5 运行中
            </span>
            <span className="text-slate-600">|</span>
            <span className="text-emerald-400">29 已完成</span>
            <span className="text-slate-600">|</span>
            <span className="text-rose-400">0 失败</span>
          </div>

          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
            title={isExpanded ? '收起任务明细' : '展开关键调度任务'}
          >
            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>

          <a
            href="http://192.168.100.19/myapp/"
            target="_blank"
            rel="noopener noreferrer"
            className="px-3 py-1.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-medium text-xs flex items-center gap-1 transition-all shadow-sm shadow-cyan-600/20"
          >
            <span>任务调度大屏</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        </div>
      </div>

      {/* Expandable Task Cards */}
      {isExpanded && (
        <div className="mt-4 pt-4 border-t border-slate-800/80 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 animate-fadeIn">
          {tasks.map((task, idx) => (
            <div
              key={idx}
              className="p-3 rounded-xl bg-slate-800/60 border border-slate-700/60 flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] font-semibold px-2 py-0.5 rounded-md bg-cyan-950 text-cyan-300 border border-cyan-800/60">
                    {task.type}
                  </span>
                  {task.status === 'running' ? (
                    <span className="text-[10px] text-cyan-400 font-medium flex items-center gap-1">
                      <RotateCw className="w-2.5 h-2.5 animate-spin" /> 执行中
                    </span>
                  ) : (
                    <span className="text-[10px] text-emerald-400 font-medium flex items-center gap-1">
                      <CheckCircle2 className="w-2.5 h-2.5" /> 就绪
                    </span>
                  )}
                </div>

                <h4 className="font-semibold text-xs text-white truncate" title={task.name}>
                  {task.name}
                </h4>
                <p className="text-[11px] text-slate-400 line-clamp-2 mt-1 leading-snug">
                  {task.desc}
                </p>
              </div>

              <div className="mt-2.5 pt-2 border-t border-slate-700/50 text-[10px] text-slate-400 space-y-0.5">
                <div className="flex items-center justify-between">
                  <span>调度周期:</span>
                  <span className="font-mono text-slate-300">{task.schedule}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>上次执行:</span>
                  <span className="font-mono text-slate-300">{task.duration}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
