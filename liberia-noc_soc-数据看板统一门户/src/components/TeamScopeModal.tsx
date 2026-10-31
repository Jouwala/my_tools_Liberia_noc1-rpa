import React, { useCallback, useEffect, useState } from 'react';
import { X, Save, RotateCcw, Grid3x3, Info } from 'lucide-react';
import { useI18n } from '../i18n';
import { PORTAL_API } from '../config';
import { useAuth } from '../auth/AuthContext';
import { TEAM_IDS, TEAM_PORTAL_PATHS, type TeamId } from '../auth/AuthContext';

/** 域 → 子键 → 团队 id 列表（与服务端 server/teamScopeDb.ts 的 TeamScopeMatrix 同形） */
type ScopeMatrix = Record<string, Record<string, TeamId[]>>;

/** 域的展示信息 */
interface ScopeDomain {
  key: string;
  zh: string;
  en: string;
}

/** 每个域下的项 */
interface ScopeItem {
  key: string;
  zh: string;
  en: string;
}

/** GET /auth/team-scope/admin 的返回 */
interface ScopeAdminData {
  matrix: ScopeMatrix;
  domains: ScopeDomain[];
  items: Record<string, ScopeItem[]>;
  info: { updatedAt: string | null; updatedBy: string | null; editable: boolean };
}

interface TeamScopeModalProps {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * 团队可见性矩阵编辑器（2026-10-30 加）
 * ----------------------------------------------------------------------------
 * 管理员在这里勾选「哪个团队能看到哪些内容」。勾选结果落进服务端数据库
 * （portal-auth.db 的 team_scope 表），团队门户运行时按它过滤。
 *
 * 为什么要有这个界面（此前没有）
 * --------------------------------
 * 可见性矩阵原先只能改 `v3/team_portal/scope-map.json` 这个仓库里的静态文件，
 * 改完还要跑生成脚本、并且必须改到**服务器的文件系统上**才生效。
 * 结果是：
 *   · 管理员（非开发者）根本改不了；
 *   · 生产机上改了文件，下次谁跑一次生成脚本就把手改覆盖掉；
 *   · 「谁在什么时候改了哪个团队的可见范围」无迹可查。
 *
 * 现在数据库是运行时的真相源，静态文件退化为**默认模板**（首次启动时播种）。
 *
 * ⚠️ 保存后**必须刷新团队门户页面**才生效 —— 团队门户在页面加载时取一次矩阵，
 *   没有做轮询（那是刻意的：可见性变更属于低频操作，不值得每秒问一次服务端）。
 */
export const TeamScopeModal: React.FC<TeamScopeModalProps> = ({ isOpen, onClose }) => {
  const { t, lang } = useI18n();
  const { apiFetch } = useAuth();
  const [data, setData] = useState<ScopeAdminData | null>(null);
  const [matrix, setMatrix] = useState<ScopeMatrix>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [dirty, setDirty] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch(`${PORTAL_API}/auth/team-scope/admin`);
      const payload = (await res.json().catch(() => null)) as ScopeAdminData | null;
      if (!res.ok || !payload) {
        setError(t('ts.loadFailed'));
        return;
      }
      setData(payload);
      setMatrix(payload.matrix ?? {});
      setDirty(false);
    } catch {
      setError(t('ts.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [apiFetch, t]);

  useEffect(() => {
    if (isOpen) void load();
  }, [isOpen, load]);

  /** 勾选/取消某团队对某项的可见性 */
  const toggle = (domKey: string, subKey: string, team: TeamId) => {
    setMatrix((prev) => {
      const dom = { ...(prev[domKey] ?? {}) };
      const cur = dom[subKey] ?? [];
      const next = cur.includes(team) ? cur.filter((t) => t !== team) : [...cur, team];
      dom[subKey] = next;
      return { ...prev, [domKey]: dom };
    });
    setDirty(true);
    setSuccess('');
  };

  /** 某域对某团队是否全选 —— 用于「整域全选/全不选」的快捷按钮 */
  const isDomainFull = (domKey: string, team: TeamId, itemKeys: string[]) =>
    itemKeys.length > 0 && itemKeys.every((k) => (matrix[domKey]?.[k] ?? []).includes(team));

  const setDomain = (domKey: string, team: TeamId, itemKeys: string[], on: boolean) => {
    setMatrix((prev) => {
      const dom = { ...(prev[domKey] ?? {}) };
      for (const k of itemKeys) {
        const cur = dom[k] ?? [];
        dom[k] = on ? Array.from(new Set([...cur, team])) : cur.filter((t) => t !== team);
      }
      return { ...prev, [domKey]: dom };
    });
    setDirty(true);
    setSuccess('');
  };

  const save = async () => {
    setSaving(true);
    setError('');
    setSuccess('');
    try {
      const res = await apiFetch(`${PORTAL_API}/auth/team-scope`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ matrix }),
      });
      const payload = (await res.json().catch(() => null)) as
        | { ok?: boolean; detail?: string; matrix?: ScopeMatrix }
        | null;
      if (!res.ok || !payload?.ok) {
        setError(payload?.detail || t('ts.saveFailed'));
        return;
      }
      setMatrix(payload.matrix ?? matrix);
      setDirty(false);
      setSuccess(t('ts.saved'));
    } catch {
      setError(t('ts.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  const label = (zh: string, en: string) => (lang === 'en' ? en : zh);

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      aria-label={t('ts.title')}
      onClick={onClose}
    >
      <div
        className="w-full max-w-6xl max-h-[90vh] flex flex-col bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 标题栏 */}
        <div className="flex items-center justify-between gap-3 px-5 py-3.5 border-b border-slate-200 dark:border-slate-700 shrink-0">
          <div className="flex items-center gap-2.5 min-w-0">
            <Grid3x3 className="w-4 h-4 text-violet-500 shrink-0" />
            <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate">
              {t('ts.title')}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800 dark:hover:text-slate-200 transition-colors"
            aria-label={t('ts.close')}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* 说明条 */}
        <div className="flex items-start gap-2 px-5 py-2.5 bg-slate-50 dark:bg-slate-800/60 border-b border-slate-200 dark:border-slate-700 shrink-0">
          <Info className="w-3.5 h-3.5 text-slate-400 mt-0.5 shrink-0" />
          <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed">
            {t('ts.hint')}
          </p>
        </div>

        {/* 内容 */}
        <div className="flex-1 overflow-auto p-4">
          {loading ? (
            <div className="text-center py-12 text-xs text-slate-400">{t('ts.loading')}</div>
          ) : !data ? (
            <div className="text-center py-12 text-xs text-rose-500">{error || t('ts.loadFailed')}</div>
          ) : (
            <table className="w-full border-separate border-spacing-0 text-[11px]">
              <thead>
                <tr>
                  <th className="text-left font-semibold text-slate-600 dark:text-slate-300 py-2 pr-3 w-[38%] sticky top-0 bg-white dark:bg-slate-900 z-10">
                    {t('ts.content')}
                  </th>
                  {TEAM_IDS.map((tid) => (
                    <th
                      key={tid}
                      className="text-center font-semibold text-slate-600 dark:text-slate-300 py-2 px-1 sticky top-0 bg-white dark:bg-slate-900 z-10"
                    >
                      <div
                        className="truncate"
                        title={`${t(`um.team.${tid}`)} ${TEAM_PORTAL_PATHS[tid]}`}
                      >
                        {t(`um.team.${tid}`)}
                      </div>
                      <div className="text-[9px] font-normal text-slate-400 truncate">
                        {TEAM_PORTAL_PATHS[tid]}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.domains.map((dom) => {
                  const items = data.items[dom.key] ?? [];
                  if (!items.length) return null;
                  const itemKeys = items.map((i) => i.key);
                  return (
                    <React.Fragment key={dom.key}>
                      {/* 域标题行 */}
                      <tr className="bg-slate-50 dark:bg-slate-800/60">
                        <td
                          className="py-2 pr-3 font-semibold text-slate-700 dark:text-slate-200"
                          colSpan={1}
                        >
                          {label(dom.zh, dom.en)}
                          <span className="ml-2 text-[9px] font-normal text-slate-400">
                            {dom.key}
                          </span>
                        </td>
                        {TEAM_IDS.map((tid) => {
                          const full = isDomainFull(dom.key, tid, itemKeys);
                          return (
                            <td key={tid} className="py-1 px-1 text-center">
                              <button
                                onClick={() => setDomain(dom.key, tid, itemKeys, !full)}
                                title={
                                  full
                                    ? t('ts.clearTeam', { team: t(`um.team.${tid}`) })
                                    : t('ts.selectTeam', { team: t(`um.team.${tid}`) })
                                }
                                className="px-1.5 py-0.5 rounded text-[9px] border border-slate-300 dark:border-slate-600 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                              >
                                {full ? '−' : '+'}
                              </button>
                            </td>
                          );
                        })}
                      </tr>
                      {/* 域内的项 */}
                      {items.map((item) => (
                        <tr
                          key={item.key}
                          className="border-t border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/40"
                        >
                          <td className="py-1.5 pr-3 pl-3 text-slate-600 dark:text-slate-300">
                            <span>{label(item.zh, item.en)}</span>
                            <span className="ml-1.5 text-[9px] text-slate-400">{item.key}</span>
                          </td>
                          {TEAM_IDS.map((tid) => {
                            const on = (matrix[dom.key]?.[item.key] ?? []).includes(tid);
                            return (
                              <td key={tid} className="py-1.5 px-1 text-center">
                                <input
                                  type="checkbox"
                                  checked={on}
                                  onChange={() => toggle(dom.key, item.key, tid)}
                                  aria-label={`${label(item.zh, item.en)} · ${t(`um.team.${tid}`)}`}
                                  className="w-3.5 h-3.5 accent-violet-500 cursor-pointer"
                                />
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* 底部：状态 + 操作 */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 border-t border-slate-200 dark:border-slate-700 shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            {error && <span className="text-[11px] text-rose-500 truncate">{error}</span>}
            {success && <span className="text-[11px] text-emerald-600 dark:text-emerald-400">{success}</span>}
            {data?.info.updatedAt && (
              <span className="text-[10px] text-slate-400 truncate">
                {t('ts.updatedAt', {
                  at: new Date(data.info.updatedAt).toLocaleString(),
                  by: data.info.updatedBy ?? '-',
                })}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => void load()}
              disabled={loading || saving}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <RotateCcw className="w-3 h-3" />
              {t('ts.reload')}
            </button>
            <button
              onClick={() => void save()}
              disabled={!dirty || saving}
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-[11px] font-medium bg-violet-600 hover:bg-violet-700 text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Save className="w-3 h-3" />
              {saving ? t('ts.saving') : t('ts.save')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
