import React, { useCallback, useEffect, useRef, useState } from 'react';
import { MessageSquareText, RefreshCw, FileText, Check, X as XIcon, Paperclip } from 'lucide-react';
import { useI18n } from '../i18n';

const API_BASE =
  (import.meta.env.VITE_WA_API_BASE as string | undefined)?.replace(/\/+$/, '') ||
  'http://localhost:9268';

type Priority = 'urgent' | 'followup' | 'fyi';

interface AttachmentMeta {
  id: number;
  filename: string;
  mime: string;
  size: number;
}

interface WaTask {
  id: number;
  group_name: string | null;
  requester: string | null;
  message_time: string | null;
  site_name: string | null;
  site_id: string | null;
  tt_id: string | null;
  alarm_name: string | null;
  issue: string | null;
  action_required: string | null;
  deadline: string | null;
  priority: Priority;
  status: 'pending' | 'done' | 'dismissed';
  source: string;
  my_result: string;
  attachments: AttachmentMeta[];
  created_at: string;
  updated_at: string;
}

// 固定输出格式：9 个字段、顺序不变；未找到的照常显示标签、值留空
const FIXED_FIELDS: { label: string; get: (t: WaTask) => string | null | undefined }[] = [
  { label: 'Requester', get: (t) => t.requester },
  { label: 'MessageTime', get: (t) => t.message_time },
  { label: 'SiteID', get: (t) => t.site_id },
  { label: 'SiteName', get: (t) => t.site_name },
  { label: 'TT_ID', get: (t) => t.tt_id },
  { label: 'Alarm_Name', get: (t) => t.alarm_name },
  { label: 'Group', get: (t) => t.group_name },
  { label: 'Issue', get: (t) => t.issue },
  { label: 'Deadline', get: (t) => t.deadline },
];

const PRIORITY_META: Record<Priority, { key: string; cls: string }> = {
  urgent: { key: 'wa.urgent', cls: 'bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-900' },
  followup: { key: 'wa.followup', cls: 'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-900' },
  fyi: { key: 'wa.fyi', cls: 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-900' },
};

function ResultEditor({
  task,
  onChanged,
}: {
  task: WaTask;
  onChanged: (t: WaTask) => void;
}) {
  const { t } = useI18n();
  const [text, setText] = useState(task.my_result || '');
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const save = async () => {
    setSaving(true);
    try {
      await fetch(`${API_BASE}/api/tasks/${task.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ my_result: text }),
      });
      onChanged({ ...task, my_result: text });
    } finally {
      setSaving(false);
    }
  };

  const upload = async (files: FileList) => {
    setUploading(true);
    try {
      let updated: WaTask = { ...task, attachments: [...(task.attachments || [])] };
      for (const f of Array.from(files)) {
        const dataBase64 = await new Promise<string>((resolve, reject) => {
          const r = new FileReader();
          r.onload = () => resolve(String(r.result).split(',')[1] || '');
          r.onerror = () => reject(r.error);
          r.readAsDataURL(f);
        });
        const res = await fetch(`${API_BASE}/api/tasks/${task.id}/attachments`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename: f.name, mime: f.type, dataBase64 }),
        });
        const data = await res.json();
        if (data.attachment) updated.attachments.push(data.attachment);
      }
      onChanged(updated);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const removeAttachment = async (attId: number) => {
    try {
      await fetch(`${API_BASE}/api/attachments/${attId}`, { method: 'DELETE' });
      onChanged({
        ...task,
        attachments: (task.attachments || []).filter((a) => a.id !== attId),
      });
    } catch {
      /* 离线时保持现状 */
    }
  };

  return (
    <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-800 space-y-2">
      <div className="text-[11px] font-semibold text-slate-400">{t('wa.myResult')}</div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
        placeholder={t('wa.myResult')}
        className="w-full text-xs p-2 rounded-lg bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-teal-500 resize-y"
      />
      <div className="flex items-center gap-2">
        <button
          onClick={save}
          disabled={saving}
          className="px-2.5 py-1 text-[11px] font-medium rounded-lg bg-teal-50 dark:bg-teal-950/40 text-teal-700 dark:text-teal-300 hover:bg-teal-100 dark:hover:bg-teal-900/40 transition-colors disabled:opacity-50"
        >
          {t('wa.saveResult')}
        </button>
        <button
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-lg bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors disabled:opacity-50"
        >
          <Paperclip className="w-3 h-3" />
          {uploading ? '…' : t('wa.attach')}
        </button>
        <input
          ref={fileRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => e.target.files && e.target.files.length && upload(e.target.files)}
        />
      </div>
      {(task.attachments || []).length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {task.attachments.map((a) => (
            <span key={a.id} className="relative group inline-flex">
              {a.mime.startsWith('image/') ? (
                <a
                  href={`${API_BASE}/api/attachments/${a.id}`}
                  target="_blank"
                  rel="noreferrer"
                  title={a.filename}
                >
                  <img
                    src={`${API_BASE}/api/attachments/${a.id}`}
                    alt={a.filename}
                    className="w-14 h-14 object-cover rounded-lg border border-slate-200 dark:border-slate-700"
                  />
                </a>
              ) : (
                <a
                  href={`${API_BASE}/api/attachments/${a.id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-[11px] text-teal-600 dark:text-teal-400 hover:underline max-w-full"
                >
                  <FileText className="w-3 h-3 shrink-0" />
                  <span className="truncate max-w-[10rem]">{a.filename}</span>
                </a>
              )}
              <button
                onClick={() => removeAttachment(a.id)}
                title={t('wa.removeAttach')}
                className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-rose-500 text-white items-center justify-center hidden group-hover:flex"
              >
                <XIcon className="w-2.5 h-2.5" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function WhatsAppTasksView() {
  const { t } = useI18n();
  const [tasks, setTasks] = useState<WaTask[]>([]);
  const [report, setReport] = useState<{ report_date: string; markdown: string; created_at: string } | null>(null);
  const [showReport, setShowReport] = useState(false);
  const [offline, setOffline] = useState(false);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'done'>('all');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [tasksRes, reportRes] = await Promise.all([
        fetch(`${API_BASE}/api/tasks`),
        fetch(`${API_BASE}/api/reports/latest`),
      ]);
      const tasksData = await tasksRes.json();
      const reportData = await reportRes.json();
      setTasks(
        (tasksData.tasks || []).filter((tk: WaTask) => tk.status !== 'dismissed')
      );
      setReport(reportData.report || null);
      setOffline(false);
    } catch {
      setOffline(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const patchStatus = async (id: number, status: 'done' | 'dismissed') => {
    try {
      await fetch(`${API_BASE}/api/tasks/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      setTasks((prev) =>
        status === 'dismissed'
          ? prev.filter((tk) => tk.id !== id)
          : prev.map((tk) => (tk.id === id ? { ...tk, status } : tk))
      );
    } catch {
      setOffline(true);
    }
  };

  const generateReport = async () => {
    setGenerating(true);
    try {
      const res = await fetch(`${API_BASE}/api/report/generate`, { method: 'POST' });
      const data = await res.json();
      if (data.markdown) {
        setReport({ report_date: data.report_date, markdown: data.markdown, created_at: '' });
        setShowReport(true);
      }
    } catch {
      setOffline(true);
    } finally {
      setGenerating(false);
    }
  };

  const groups: Priority[] = ['urgent', 'followup', 'fyi'];

  const visibleTasks = tasks.filter((tk) =>
    statusFilter === 'all' ? true : statusFilter === 'done' ? tk.status === 'done' : tk.status !== 'done'
  );
  const FILTERS: { key: 'all' | 'active' | 'done'; label: string; count: number }[] = [
    { key: 'all', label: t('wa.filterAll'), count: tasks.length },
    { key: 'active', label: t('wa.filterActive'), count: tasks.filter((tk) => tk.status !== 'done').length },
    { key: 'done', label: t('wa.filterDone'), count: tasks.filter((tk) => tk.status === 'done').length },
  ];

  return (
    <div className="space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-2xl bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-400 flex items-center justify-center">
            <MessageSquareText className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-bold text-slate-800 dark:text-slate-100">{t('wa.title')}</h2>
            <p className="text-xs text-slate-500 dark:text-slate-400">{t('wa.subtitle')}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            {t('wa.refresh')}
          </button>
          <button
            onClick={generateReport}
            disabled={generating || offline}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-xl bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 text-white transition-all disabled:opacity-50"
          >
            <FileText className="w-3.5 h-3.5" />
            {t('wa.genReport')}
          </button>
        </div>
      </div>

      {!offline && tasks.length > 0 && (
        <div className="flex items-center gap-1 w-fit rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-0.5">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setStatusFilter(f.key)}
              className={`px-2.5 py-1 text-[11px] font-medium rounded-lg transition-colors ${
                statusFilter === f.key
                  ? 'bg-teal-50 dark:bg-teal-950/40 text-teal-700 dark:text-teal-300'
                  : 'text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800'
              }`}
            >
              {f.label}（{f.count}）
            </button>
          ))}
        </div>
      )}

      {offline && (
        <div className="rounded-2xl border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/40 p-4 text-sm">
          <div className="font-semibold text-amber-800 dark:text-amber-200">{t('wa.offline')}</div>
          <div className="text-xs text-amber-700 dark:text-amber-300 mt-1">{t('wa.offlineHint')}</div>
        </div>
      )}

      {showReport && report && (
        <details open className="rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
          <summary className="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">
            {t('wa.latestReport')}（{report.report_date}）
          </summary>
          <pre className="mt-3 text-xs leading-relaxed whitespace-pre-wrap text-slate-600 dark:text-slate-300 max-h-96 overflow-auto">
            {report.markdown}
          </pre>
        </details>
      )}

      {!offline && !loading && tasks.length === 0 && (
        <div className="rounded-3xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-10 text-center text-sm text-slate-500 dark:text-slate-400">
          {t('wa.empty')}
        </div>
      )}

      {!offline && !loading && tasks.length > 0 && visibleTasks.length === 0 && (
        <div className="rounded-3xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-10 text-center text-sm text-slate-500 dark:text-slate-400">
          {t('wa.emptyFilter')}
        </div>
      )}

      {groups.map((g) => {
        const list = visibleTasks.filter((tk) => tk.priority === g);
        if (!list.length) return null;
        const meta = PRIORITY_META[g];
        return (
          <div key={g}>
            <h3 className="text-sm font-bold text-slate-700 dark:text-slate-200 mb-2">
              {t(meta.key)}（{list.length}）
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {list.map((tk) => (
                <div
                  key={tk.id}
                  className={`rounded-2xl border p-4 bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 ${
                    tk.status === 'done' ? 'opacity-60' : ''
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <span
                      className={`text-xs font-bold ${
                        tk.status === 'done' ? 'line-through' : ''
                      } text-slate-800 dark:text-slate-100`}
                    >
                      {[tk.site_name, tk.site_id].filter(Boolean).join(' / ') || '—'}
                    </span>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold ${meta.cls}`}>
                      {t(meta.key)}
                    </span>
                  </div>
                  <dl className="text-xs space-y-1 text-slate-600 dark:text-slate-300">
                    {FIXED_FIELDS.map(({ label, get }) => (
                      <div key={label}>
                        <dt className="inline text-slate-400">{label}: </dt>
                        <dd className="inline break-all">{get(tk) || ''}</dd>
                      </div>
                    ))}
                  </dl>
                  <ResultEditor
                    task={tk}
                    onChanged={(updated) =>
                      setTasks((prev) => prev.map((x) => (x.id === updated.id ? updated : x)))
                    }
                  />
                  {tk.status !== 'done' && (
                    <div className="flex gap-2 mt-3">
                      <button
                        onClick={() => patchStatus(tk.id, 'done')}
                        className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-lg bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-900/40 transition-colors"
                      >
                        <Check className="w-3 h-3" /> {t('wa.markDone')}
                      </button>
                      <button
                        onClick={() => patchStatus(tk.id, 'dismissed')}
                        className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-lg bg-slate-50 dark:bg-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                      >
                        <XIcon className="w-3 h-3" /> {t('wa.dismiss')}
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
