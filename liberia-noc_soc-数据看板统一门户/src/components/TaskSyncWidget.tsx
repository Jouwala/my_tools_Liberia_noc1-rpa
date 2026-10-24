import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  CheckCircle2,
  RotateCw,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  XCircle,
  WifiOff,
  Mail,
  Search,
  Ticket,
  RadioTower,
  Bot,
} from 'lucide-react';
import { getMyappTasksApi, getMyappLink } from '../config';
import { useI18n } from '../i18n';
import { formatMetric } from '../utils/format';

interface ApiTaskRun {
  success: boolean;
  started_at?: string;
  elapsed_seconds?: number;
}

interface ApiTask {
  task_id: string;
  name?: string;
  name_en?: string;
  name_zh?: string;
  category?: string;
  current_cron?: string;
  enabled?: boolean;
  running?: boolean;
  recent_runs?: ApiTaskRun[];
}

interface TaskItem {
  id: string;
  name: string;
  category: string;
  cron: string;
  enabled: boolean;
  running: boolean;
  lastSuccess: boolean | null;
  lastElapsed: number | null;
}

const FALLBACK_TASKS: TaskItem[] = [
  { id: 'eflow_sync', name: 'eFlow Data Sync', category: 'eflow', cron: '0 * * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 297.3 },
  { id: 'eflow_sync_full', name: 'eFlow Daily Full Sync', category: 'eflow', cron: '0 8 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 478.4 },
  { id: 'eflow_active_alarm', name: 'eFlow Realtime Alarm Sync', category: 'eflow', cron: '*/5 * * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 30.4 },
  { id: 'eflow_history_alarm', name: 'eFlow History Alarm Sync', category: 'eflow', cron: '35 3 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 37.0 },
  { id: 'ran_ume_daily', name: 'RAN UME Daily Report', category: 'ran_ume', cron: '35 4 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 207.3 },
  { id: 'main_kpi_sync', name: 'RAN Main KPI Sync', category: 'main_kpi', cron: '0 4 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 596.3 },
  { id: 'network_kpi_sync', name: 'RAN Network KPI Sync', category: 'network_kpi', cron: '35 5 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 390.4 },
  { id: 'cnn_kpi_sync', name: 'CNN UME KPI Sync', category: 'cnn_kpi', cron: '0 4 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 303.0 },
  { id: 'ipran_kpi_sync', name: 'iPRAN UME KPI Sync', category: 'ipran_kpi', cron: '0 * * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 288.3 },
  { id: 'ms_sla_full', name: 'MS SLA Full Sync', category: 'ms_sla', cron: '30 7 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 587.3 },
  { id: 'packet_loss_sync', name: 'Packet Loss Sync', category: 'packet_loss', cron: '30 6 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 394.7 },
  { id: 'packet_loss_email', name: 'Packet Loss Daily Report Email', category: 'packet_loss', cron: '45 6 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 20.0 },
  { id: 'battery_kpi_sync', name: 'Battery KPI Sync', category: 'battery', cron: '5 * * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 3.0 },
  { id: 'battery_email', name: 'Battery KPI Email', category: 'battery', cron: '0 7,19 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 7.5 },
  { id: 'fw_kpi_sync', name: 'FW Throughput KPI Sync + Chart Email', category: 'fw_kpi', cron: '15 7 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 13.7 },
  { id: 'sp_data_sync', name: 'SP Spare Data Sync', category: 'sp', cron: '0 7 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 11.3 },
  { id: 'sp_report_generate', name: 'SP Report Generate', category: 'kpi_email', cron: '15 5 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 37.6 },
  { id: 'incident_overview_sync', name: 'Incident Overview Data Sync', category: 'incident_overview', cron: '3 * * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 17.2 },
  { id: 'site_outage_screenshot', name: 'Site Outage Screenshot', category: 'site_outage', cron: '0 */1 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 30.5 },
  { id: 'liberia_email_1h', name: 'Liberia Site-Down 1H Report Email', category: 'email', cron: '6 * * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 4.4 },
  { id: 'liberia_email_8h', name: 'Liberia Site-Down 8H Report Email', category: 'email', cron: '7 */8 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 3.5 },
  { id: 'whatsapp_send', name: 'WhatsApp Message Send', category: 'whatsapp', cron: '2 */2 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 74.1 },
  { id: 'kpi_ms_contract', name: 'MS Contract KPIs Daily Report Email', category: 'kpi_email', cron: '30 5 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 3.7 },
  { id: 'kpi_ms_wo_sla', name: 'MS WOs SLA Daily Report Email', category: 'kpi_email', cron: '35 5 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 2.6 },
  { id: 'kpi_ran_availability', name: 'MS Network Availability Daily Report Email', category: 'kpi_email', cron: '20 6 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 7.3 },
  { id: 'kpi_sp_spareparts', name: 'SpareParts Report Email', category: 'kpi_email', cron: '45 5 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 3.2 },
  { id: 'kpi_sp_consumables', name: 'Comsumables Report Email', category: 'kpi_email', cron: '40 6 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 3.3 },
  { id: 'ipran_m6k_chart_email', name: 'IP RAN M6K-FW Chart Email', category: 'email', cron: '15 8 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 5.5 },
  { id: 'ccn_free_rating_chart_email', name: 'CNN Free Rating Chart Email', category: 'email', cron: '45 7 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 4.5 },
  { id: 'email_recovery', name: 'Email Recovery after EWS Restored', category: 'email', cron: '*/20 * * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 2.4 },
  { id: 'mailbox_cleanup', name: 'Mailbox Storage Guard', category: 'mailbox', cron: '0 * * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 7.2 },
  { id: 'cm_data_sync', name: 'RAN CM Cell Data Sync', category: 'cm_data', cron: '30 8 * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 68.9 },
  { id: 'db_freshness_check', name: 'DB Data Freshness Check', category: 'general', cron: '15 * * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 77.0 },
  { id: 'auto_retry_failed', name: 'Failed Task Auto Retry', category: 'general', cron: '*/5 * * * *', enabled: true, running: false, lastSuccess: true, lastElapsed: 0.0 },
];

const REFRESH_INTERVAL = 60_000;

function mapApiTask(t: ApiTask): TaskItem {
  const last = t.recent_runs && t.recent_runs.length > 0 ? t.recent_runs[0] : null;
  return {
    id: t.task_id,
    name: t.name_en || t.name || t.task_id,
    category: t.category || 'general',
    cron: t.current_cron || '',
    enabled: t.enabled !== false,
    running: !!t.running,
    lastSuccess: last ? !!last.success : null,
    lastElapsed: last && typeof last.elapsed_seconds === 'number' ? last.elapsed_seconds : null,
  };
}

export const TaskSyncWidget: React.FC = () => {
  const { t, lang } = useI18n();
  const [isExpanded, setIsExpanded] = useState(false);
  const [tasks, setTasks] = useState<TaskItem[]>(FALLBACK_TASKS);
  const [isLive, setIsLive] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const load = async () => {
      try {
        const res = await fetch(getMyappTasksApi(), {
          signal: controller.signal,
          headers: { 'Accept-Language': lang === 'zh' ? 'zh-CN' : 'en-US' },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        const list: ApiTask[] = Array.isArray(json?.tasks) ? json.tasks : [];
        if (!cancelled && list.length > 0) {
          setTasks(list.map(mapApiTask));
          setIsLive(true);
          setUpdatedAt(new Date());
        }
      } catch {
        if (!cancelled) setIsLive(false);
      }
    };

    // 2026-10-01 修复 B6：原实现无脑每 60s 拉一次 /api/tasks，且响应体大（~77KB），
    // 就绪度检测实测单标签页 10 分钟 212 次请求 ≈ 100MB/小时。改为「仅在标签页可见时
    // 轮询」：隐藏时完全停，重新可见时立刻补一次拉取，避免后台标签页持续空耗带宽。
    load();
    let timer = window.setInterval(load, REFRESH_INTERVAL);
    const onVisibility = () => {
      if (document.hidden) {
        window.clearInterval(timer);
      } else {
        load();
        window.clearInterval(timer);
        timer = window.setInterval(load, REFRESH_INTERVAL);
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [lang]);

  const stats = useMemo(() => {
    const total = tasks.length;
    const running = tasks.filter((t) => t.running).length;
    const failed = tasks.filter((t) => t.lastSuccess === false).length;
    const ok = tasks.filter((t) => t.lastSuccess === true).length;
    return { total, running, failed, ok };
  }, [tasks]);

  const showcase = useMemo(() => {
    const weight = (t: TaskItem) => (t.running ? 0 : t.lastSuccess === false ? 1 : 2);
    return [...tasks].sort((a, b) => weight(a) - weight(b)).slice(0, 8);
  }, [tasks]);

  return (
    <div className="spatial-panel mb-4 sm:mb-6 bg-gradient-to-r from-teal-50 via-white to-cyan-50 text-slate-900 rounded-2xl p-3 sm:p-5 border border-teal-300/50 shadow-sm dark:bg-gradient-to-r dark:from-navy-950 dark:via-navy-900 dark:to-navy-800 dark:text-white dark:border-teal-400/15 dark:shadow-lg dark:shadow-navy-950/40 animate-fadeIn">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2 sm:gap-3 min-w-0">
          <div className="p-2 sm:p-2.5 rounded-xl bg-teal-100 text-teal-600 border border-teal-300/70 dark:bg-teal-400/15 dark:text-teal-300 dark:border-teal-400/30 shrink-0">
            <Activity className="w-4 h-4 sm:w-5 sm:h-5 animate-pulse" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-bold text-sm sm:text-base tracking-tight text-slate-900 dark:text-white flex items-center gap-2">
                {t('task.title')}
              </h3>
              {isLive ? (
                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-700 border border-emerald-300/70 dark:bg-emerald-500/20 dark:text-emerald-300 dark:border-emerald-400/30 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400 animate-pulse" />
                  {t('task.live')}
                  {updatedAt && (
                    <span className="text-emerald-600/70 dark:text-emerald-400/70 font-mono hidden sm:inline">
                      {updatedAt.toLocaleTimeString(lang === 'zh' ? 'zh-CN' : 'en-US', { hour12: false })}
                    </span>
                  )}
                </span>
              ) : (
                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-700 border border-amber-300/70 dark:bg-amber-500/20 dark:text-amber-300 dark:border-amber-400/30 flex items-center gap-1">
                  <WifiOff className="w-2.5 h-2.5" />
                  {t('task.offline')}
                </span>
              )}
            </div>
            <p className="text-[11px] sm:text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              {t('task.desc')}
            </p>
          </div>
        </div>

        {/* Stats Pills + Actions */}
        <div className="flex flex-wrap items-center gap-1 sm:gap-2">
          <div className="flex items-center gap-1 sm:gap-1.5 bg-slate-900/5 dark:bg-white/5 px-1.5 sm:px-3 py-1 sm:py-1.5 rounded-xl border border-slate-300/60 dark:border-white/10 text-xs flex-wrap whitespace-nowrap">
            <span className="text-slate-500 dark:text-slate-400">{t('task.total')}</span>
            <span className="font-mono font-bold text-slate-900 dark:text-white">{stats.total}</span>
            <span className="text-slate-300 dark:text-slate-600">|</span>
            <span className="text-teal-600 dark:text-teal-300 flex items-center gap-1">
              <RotateCw className={`w-3 h-3 ${stats.running > 0 ? 'animate-spin' : ''}`} /> {stats.running} {t('task.running')}
            </span>
            <span className="text-slate-300 dark:text-slate-600">|</span>
            <span className="text-emerald-600 dark:text-emerald-400">{stats.ok} {t('task.ok')}</span>
            <span className="text-slate-300 dark:text-slate-600">|</span>
            <span className={stats.failed > 0 ? 'text-rose-500 dark:text-rose-400 font-bold' : 'text-slate-400 dark:text-slate-500'}>
              {stats.failed} {t('task.failed')}
            </span>
          </div>

          <div className="hidden xl:flex items-center gap-1.5 pl-1 border-l border-slate-200 dark:border-white/10">
            {/* 2026-10-24：经 .20 的 9443 反代到 .27 的 Open WebUI。
                原因：.27:8443 不在 VPN/防火墙放行名单，登录 VPN 后超时；而 .20 在
                名单内且与 .27 同网段直连可达。反代配置见 nginx/conf/portal_ports.conf
                末尾的 9443 server 块（与 8081-8088 同构）。 */}
            <a href="https://192.168.100.20:9443/" target="_blank" rel="noopener noreferrer" title={t('task.ragKnowledgeQa')}
              className="px-2.5 py-1.5 rounded-xl bg-violet-50 hover:bg-violet-100 text-violet-700 dark:bg-violet-950/50 dark:hover:bg-violet-900/60 dark:text-violet-300 text-xs font-medium flex items-center gap-1 transition-colors">
              <Bot className="w-3.5 h-3.5" />{t('task.ragKnowledgeQa')}
            </a>
            <a href={getMyappLink('eflow_qa')} target="_blank" rel="noopener noreferrer" title={t('task.knowledgeSearch')}
              className="px-2.5 py-1.5 rounded-xl bg-cyan-50 hover:bg-cyan-100 text-cyan-700 dark:bg-cyan-950/50 dark:hover:bg-cyan-900/60 dark:text-cyan-300 text-xs font-medium flex items-center gap-1 transition-colors">
              <Search className="w-3.5 h-3.5" />{t('task.knowledgeSearch')}
            </a>
            <a href={getMyappLink('eflow_qa', 'tt-quick-analysis')} target="_blank" rel="noopener noreferrer" title={t('task.ttQuickAnalysis')}
              className="px-2.5 py-1.5 rounded-xl bg-amber-50 hover:bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:hover:bg-amber-900/60 dark:text-amber-300 text-xs font-medium flex items-center gap-1 transition-colors">
              <Ticket className="w-3.5 h-3.5" />{t('task.ttQuickAnalysis')}
            </a>
            <a href={getMyappLink('eflow_qa', 'ran-ume-alarm-analysis')} target="_blank" rel="noopener noreferrer" title={t('task.ranUmeAlarmAnalysis')}
              className="px-2.5 py-1.5 rounded-xl bg-rose-50 hover:bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:hover:bg-rose-900/60 dark:text-rose-300 text-xs font-medium flex items-center gap-1 transition-colors">
              <RadioTower className="w-3.5 h-3.5" />{t('task.ranUmeAlarmAnalysis')}
            </a>
          </div>

          <a
            href={getMyappLink('email_reports')}
            target="_blank"
            rel="noopener noreferrer"
            className="px-1.5 sm:px-3 py-1 sm:py-1.5 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 text-white font-medium text-xs flex items-center gap-1 transition-all shadow-sm shadow-indigo-600/30"
          >
            <Mail className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">{t('task.latestReports')}</span>
          </a>

          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-2 sm:p-1.5 rounded-xl bg-slate-900/5 hover:bg-slate-900/10 text-slate-600 border border-slate-300/60 dark:bg-white/5 dark:hover:bg-white/10 dark:text-slate-300 dark:border-white/10 transition-colors"
            title={isExpanded ? t('task.collapse') : t('task.expand')}
          >
            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>

          <a
            href={getMyappLink('sync')}
            target="_blank"
            rel="noopener noreferrer"
            className="px-2 sm:px-3 py-1 sm:py-1.5 rounded-xl bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 text-white font-medium text-xs flex items-center gap-1 transition-all shadow-sm shadow-teal-600/30"
          >
            <span className="hidden sm:inline">{t('task.bigScreen')}</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        </div>
      </div>

      {/* Expandable Task Cards */}
      {isExpanded && (
        <div className="mt-3 sm:mt-4 pt-3 sm:pt-4 border-t border-slate-200 dark:border-white/10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-3 animate-fadeIn">
          {showcase.map((task) => (
            <div
              key={task.id}
              className="p-2.5 sm:p-3 rounded-xl bg-white/70 border border-slate-200 hover:border-teal-500/50 dark:bg-white/5 dark:border-white/10 dark:hover:border-teal-400/40 flex flex-col justify-between transition-colors"
            >
              <div>
                <div className="flex items-center justify-between mb-1 sm:mb-1.5">
                  <span className="text-[10px] font-semibold px-1.5 sm:px-2 py-0.5 rounded-md bg-teal-100 text-teal-700 border border-teal-300/70 dark:bg-teal-950/80 dark:text-teal-300 dark:border-teal-400/20">
                    {task.category}
                  </span>
                  {task.running ? (
                    <span className="text-[10px] text-teal-600 dark:text-teal-300 font-medium flex items-center gap-1">
                      <RotateCw className="w-2.5 h-2.5 animate-spin" /> {t('task.taskRunning')}
                    </span>
                  ) : task.lastSuccess === false ? (
                    <span className="text-[10px] text-rose-500 dark:text-rose-400 font-medium flex items-center gap-1">
                      <XCircle className="w-2.5 h-2.5" /> {t('task.lastFailed')}
                    </span>
                  ) : (
                    <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1">
                      <CheckCircle2 className="w-2.5 h-2.5" /> {t('task.ready')}
                    </span>
                  )}
                </div>

                <h4 className="font-semibold text-xs text-slate-900 dark:text-white truncate" title={task.name}>
                  {task.name}
                </h4>
                <p className="text-[10px] sm:text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 sm:mt-1 leading-snug font-mono">{task.id}</p>
              </div>

              <div className="mt-2 sm:mt-2.5 pt-1.5 sm:pt-2 border-t border-slate-200/80 dark:border-white/10 text-[10px] text-slate-500 dark:text-slate-400 space-y-0.5">
                <div className="flex items-center justify-between">
                  <span>{t('task.cron')}</span>
                  <span className="font-mono text-slate-700 dark:text-slate-300">{task.cron}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>{t('task.elapsed')}</span>
                  <span className="font-mono text-slate-700 dark:text-slate-300">
                    {formatMetric(task.lastElapsed, { digits: 1, suffix: 's' })}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
