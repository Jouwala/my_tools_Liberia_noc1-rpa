import React, { useCallback, useEffect, useState } from 'react';
import {
  X,
  ShieldCheck,
  ShieldOff,
  ShieldAlert,
  TriangleAlert,
  Users,
  Database,
  RefreshCw,
  Loader2,
  LockKeyhole,
  LockOpen,
} from 'lucide-react';
import { useI18n } from '../i18n';
import { PORTAL_API } from '../config';
import { useAuth } from '../auth/AuthContext';

// ============================================================================
// 鉴权总开关（管理员）
// ----------------------------------------------------------------------------
// 服务端开关真相源：<仓库根>/auth-switch.json（见 server/authSwitch.ts），
// /uniplam/ 与 /myapp/ 共用同一份，切换后最迟 3 秒生效，**无需重启进程**。
//
// 权限不对称：
//  - 关闭鉴权（危险方向）必须持真实管理员登录态；
//  - 开启鉴权（安全方向）放行，避免免登录时无法把鉴权打开。
//
// 本弹窗只切换鉴权开关，**不会**读写用户账号、密码、看板权限与登录会话。
// ============================================================================

interface AuthSwitchStatus {
  authEnabled: boolean;
  mode: 'enforced' | 'bypass';
  source: 'env' | 'file' | 'default' | 'guard';
  env: string;
  envOverride: boolean;
  reason: string | null;
  canDisable: boolean;
  canEnable: boolean;
  realLogin: boolean;
  updatedAt: string | null;
  updatedBy: string | null;
}

interface AuthSwitchModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const AuthSwitchModal: React.FC<AuthSwitchModalProps> = ({ isOpen, onClose }) => {
  const { t } = useI18n();
  const { apiFetch, refreshAuthMode, realLogin } = useAuth();

  const [status, setStatus] = useState<AuthSwitchStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [confirmDisable, setConfirmDisable] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch(`${PORTAL_API}/auth/switch`);
      const data = (await res.json().catch(() => null)) as (AuthSwitchStatus & { detail?: string }) | null;
      if (!res.ok || !data) {
        setError(data?.detail || `HTTP ${res.status}`);
        return;
      }
      setStatus(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [apiFetch]);

  useEffect(() => {
    if (!isOpen) return;
    setConfirmDisable(false);
    setError('');
    setDone('');
    void load();
  }, [isOpen, load]);

  if (!isOpen) return null;

  const apply = async (enabled: boolean) => {
    if (submitting) return;
    setSubmitting(true);
    setError('');
    setDone('');
    try {
      const res = await apiFetch(`${PORTAL_API}/auth/switch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      const data = (await res.json().catch(() => null)) as { detail?: string } | null;
      if (!res.ok) {
        setError(data?.detail || `HTTP ${res.status}`);
        return;
      }
      setDone(data?.detail || t('authSwitch.done'));
      setConfirmDisable(false);
      await refreshAuthMode();
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const enabled = status?.authEnabled ?? true;
  const canDisable = status?.canDisable ?? false;

  const sourceLabel = (): string => {
    switch (status?.source) {
      case 'env':
        return t('authSwitch.sourceEnv');
      case 'file':
        return t('authSwitch.sourceFile');
      case 'guard':
        return t('authSwitch.sourceGuard');
      default:
        return t('authSwitch.sourceDefault');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div className="spatial-modal-surface bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl w-full max-w-[95vw] sm:max-w-lg overflow-hidden max-h-[92vh] flex flex-col">
        {/* Header */}
        <div className="px-4 sm:px-6 py-3 sm:py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2 sm:gap-2.5 min-w-0">
            <div className="p-2 rounded-lg bg-violet-50 dark:bg-violet-950/60 text-violet-600 dark:text-violet-400 shrink-0">
              <ShieldCheck className="w-4 h-4 sm:w-5 sm:h-5" />
            </div>
            <div className="min-w-0">
              <h3 className="font-semibold text-slate-900 dark:text-slate-100 text-sm sm:text-base truncate">
                {t('authSwitch.title')}
              </h3>
              <p className="text-[11px] sm:text-xs text-slate-500 dark:text-slate-400 truncate">
                {t('authSwitch.subtitle')}
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

        {/* Content */}
        <div className="p-4 sm:p-6 space-y-3.5 overflow-y-auto">
          {error && (
            <div className="p-3 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 rounded-xl flex items-start gap-2 text-red-700 dark:text-red-300 text-xs">
              <TriangleAlert className="w-4 h-4 shrink-0 mt-0.5" />
              <span className="break-all">{error}</span>
            </div>
          )}
          {done && (
            <div className="p-3 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900 rounded-xl flex items-start gap-2 text-emerald-700 dark:text-emerald-300 text-xs">
              <ShieldCheck className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{done}</span>
            </div>
          )}

          {/* 当前状态 */}
          <div
            className={`rounded-xl border p-3.5 flex items-start gap-3 ${
              enabled
                ? 'border-emerald-200 dark:border-emerald-900 bg-emerald-50/70 dark:bg-emerald-950/30'
                : 'border-amber-300 dark:border-amber-800 bg-amber-50/80 dark:bg-amber-950/30'
            }`}
          >
            <div
              className={`p-2 rounded-lg shrink-0 ${
                enabled
                  ? 'bg-emerald-100 dark:bg-emerald-900/60 text-emerald-700 dark:text-emerald-300'
                  : 'bg-amber-100 dark:bg-amber-900/60 text-amber-700 dark:text-amber-300'
              }`}
            >
              {enabled ? <LockKeyhole className="w-4 h-4" /> : <LockOpen className="w-4 h-4" />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span
                  className={`text-sm font-semibold ${
                    enabled
                      ? 'text-emerald-800 dark:text-emerald-200'
                      : 'text-amber-800 dark:text-amber-200'
                  }`}
                >
                  {enabled ? t('authSwitch.stateOn') : t('authSwitch.stateOff')}
                </span>
                {loading && <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400" />}
              </div>
              <p className="text-[11px] sm:text-xs text-slate-600 dark:text-slate-400 mt-1 leading-relaxed">
                {enabled ? t('authSwitch.onDesc') : t('authSwitch.offDesc')}
              </p>
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-500 dark:text-slate-500 font-mono">
                <span>env={status?.env ?? '-'}</span>
                <span>source={status?.source ?? '-'}</span>
              </div>
              {status?.updatedAt && (
                <p className="mt-1 text-[10px] text-slate-400 dark:text-slate-500">
                  {t('authSwitch.lastChanged', {
                    who: status.updatedBy || '-',
                    when: status.updatedAt.replace('T', ' ').slice(0, 19),
                  })}
                </p>
              )}
              <p className="mt-1 text-[10px] text-slate-400 dark:text-slate-500 break-all">
                {status?.flagFile ?? ''}
              </p>
            </div>
            <button
              onClick={() => void load()}
              disabled={loading}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-white/70 dark:hover:bg-slate-800 transition-colors shrink-0 disabled:opacity-50"
              title={t('authSwitch.refresh')}
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>

          {/* 关闭鉴权时的醒目提示 */}
          {!enabled && (
            <div className="rounded-xl border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 p-3 flex items-start gap-2">
              <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
              <div className="text-[11px] sm:text-xs text-amber-800 dark:text-amber-200 leading-relaxed">
                <p className="font-semibold mb-0.5">{t('authSwitch.warnTitle')}</p>
                <p>{t('authSwitch.warnBody')}</p>
              </div>
            </div>
          )}

          {status?.envOverride && (
            <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 p-3 text-[11px] sm:text-xs text-slate-600 dark:text-slate-300">
              {t('authSwitch.envOverride')}
            </div>
          )}

          {status?.reason && (
            <div className="rounded-xl border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950/30 p-3 text-[11px] sm:text-xs text-red-700 dark:text-red-300">
              {status.reason}
            </div>
          )}

          {/* 用户数据安全说明（用户信息一定保留） */}
          <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 p-3 space-y-2">
            <div className="flex items-center gap-2 text-[11px] sm:text-xs font-semibold text-slate-700 dark:text-slate-200">
              <Database className="w-3.5 h-3.5 text-slate-400" />
              {t('authSwitch.dataSafeTitle')}
            </div>
            <ul className="space-y-1 text-[11px] sm:text-xs text-slate-600 dark:text-slate-400 leading-relaxed">
              <li className="flex items-start gap-1.5">
                <Users className="w-3 h-3 shrink-0 mt-0.5 text-emerald-500" />
                <span>{t('authSwitch.dataSafeUsers')}</span>
              </li>
              <li className="flex items-start gap-1.5">
                <ShieldCheck className="w-3 h-3 shrink-0 mt-0.5 text-emerald-500" />
                <span>{t('authSwitch.dataSafeSessions')}</span>
              </li>
              <li className="flex items-start gap-1.5">
                <RefreshCw className="w-3 h-3 shrink-0 mt-0.5 text-emerald-500" />
                <span>{t('authSwitch.dataSafeRollback')}</span>
              </li>
            </ul>
          </div>

          {/* 非真实登录提示 */}
          {!realLogin && !enabled && (
            <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 p-3 text-[11px] sm:text-xs text-slate-500 dark:text-slate-400">
              {t('authSwitch.notRealLogin')}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 sm:px-6 py-3 sm:py-4 border-t border-slate-100 dark:border-slate-800 flex flex-wrap items-center justify-end gap-2.5 shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
          >
            {t('authSwitch.close')}
          </button>

          {enabled ? (
            confirmDisable ? (
              <>
                <button
                  type="button"
                  onClick={() => setConfirmDisable(false)}
                  className="px-4 py-2 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
                >
                  {t('modal.cancel')}
                </button>
                <button
                  type="button"
                  onClick={() => void apply(false)}
                  disabled={submitting}
                  className="px-4 py-2 text-xs font-semibold text-white bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg shadow-sm transition-all flex items-center gap-1.5"
                >
                  {submitting ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <ShieldOff className="w-3.5 h-3.5" />
                  )}
                  {t('authSwitch.confirmDisable')}
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => {
                  if (!canDisable) {
                    setError(t('authSwitch.needRealAdmin'));
                    return;
                  }
                  setConfirmDisable(true);
                }}
                className={`px-4 py-2 text-xs font-semibold rounded-lg shadow-sm transition-all flex items-center gap-1.5 ${
                  canDisable
                    ? 'text-white bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500'
                    : 'text-slate-400 dark:text-slate-500 bg-slate-100 dark:bg-slate-800 cursor-not-allowed'
                }`}
              >
                <ShieldOff className="w-3.5 h-3.5" />
                {t('authSwitch.disableBtn')}
              </button>
            )
          ) : (
            <button
              type="button"
              onClick={() => void apply(true)}
              disabled={submitting}
              className="px-4 py-2 text-xs font-semibold text-white bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg shadow-sm shadow-teal-600/20 transition-all flex items-center gap-1.5"
            >
              {submitting ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <ShieldCheck className="w-3.5 h-3.5" />
              )}
              {t('authSwitch.enableBtn')}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
