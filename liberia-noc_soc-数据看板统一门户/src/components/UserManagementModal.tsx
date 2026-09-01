import React, { useState, useEffect, useCallback } from 'react';
import {
  X,
  Users,
  UserPlus,
  Trash2,
  KeyRound,
  Check,
  AlertCircle,
  CheckCircle2,
  ShieldCheck,
  Inbox,
  UserCheck,
  UserX,
} from 'lucide-react';
import { useI18n } from '../i18n';
import { PORTAL_API } from '../config';
import { useAuth, type AuthUser, type Role } from '../auth/AuthContext';

/** 账号申请记录（后端 /auth/register-requests 返回结构，已剔除密码哈希） */
interface AccessRequest {
  id: string;
  username: string;
  note: string;
  status: 'pending' | 'approved' | 'rejected';
  createdAt: string;
  ip: string;
  decidedAt?: string;
  decidedBy?: string;
}

interface UserManagementModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const UserManagementModal: React.FC<UserManagementModalProps> = ({ isOpen, onClose }) => {
  const { t } = useI18n();
  const { user: currentUser, apiFetch } = useAuth();
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // 新增用户表单
  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState<Role>('viewer');
  const [adding, setAdding] = useState(false);

  // 行内重置密码
  const [resettingId, setResettingId] = useState('');
  const [resetPwd, setResetPwd] = useState('');

  // 待审批的账号申请
  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [requestsLoading, setRequestsLoading] = useState(false);
  const [decidingId, setDecidingId] = useState('');
  /** 每条申请行内选择的批准角色 */
  const [approveRoles, setApproveRoles] = useState<Record<string, Role>>({});

  const loadRequests = useCallback(async () => {
    setRequestsLoading(true);
    try {
      const res = await apiFetch(`${PORTAL_API}/auth/register-requests`);
      const data = (await res.json().catch(() => null)) as { requests?: AccessRequest[] } | null;
      if (res.ok) setRequests(data?.requests || []);
    } catch {
      // 申请列表加载失败不阻塞用户管理主流程
    } finally {
      setRequestsLoading(false);
    }
  }, [apiFetch]);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch(`${PORTAL_API}/auth/users`);
      const data = (await res.json().catch(() => null)) as {
        users?: AuthUser[];
        detail?: string;
      } | null;
      if (!res.ok) {
        setError(data?.detail || `HTTP ${res.status}`);
        return;
      }
      setUsers(data?.users || []);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [apiFetch]);

  useEffect(() => {
    if (isOpen) {
      void loadUsers();
      void loadRequests();
      setError('');
      setSuccess('');
      setNewUsername('');
      setNewPassword('');
      setNewRole('viewer');
      setResettingId('');
      setResetPwd('');
      setDecidingId('');
    }
  }, [isOpen, loadUsers, loadRequests]);

  if (!isOpen) return null;

  /** 批准 / 驳回：handler 为实际调用的后端动作 */
  const handleDecide = async (
    target: AccessRequest,
    action: 'approve' | 'reject',
    handler: () => Promise<{ ok: boolean; detail?: string }>
  ) => {
    if (
      !window.confirm(
        action === 'approve'
          ? t('ar.approveConfirm', { name: target.username })
          : t('ar.rejectConfirm', { name: target.username })
      )
    ) {
      return;
    }
    setError('');
    setSuccess('');
    setDecidingId(target.id);
    try {
      const result = await handler();
      if (!result.ok) {
        setError(result.detail || t('ar.notFound'));
        return;
      }
      setSuccess(
        action === 'approve'
          ? t('ar.approved', { name: target.username })
          : t('ar.rejected', { name: target.username })
      );
      setTimeout(() => setSuccess(''), 3000);
      await loadRequests();
      if (action === 'approve') await loadUsers();
    } catch (err) {
      setError(String(err));
    } finally {
      setDecidingId('');
    }
  };

  const approve = (target: AccessRequest) =>
    handleDecide(target, 'approve', async () => {
      const res = await apiFetch(`${PORTAL_API}/auth/register-requests/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: target.id, role: approveRoles[target.id] || 'viewer' }),
      });
      const data = (await res.json().catch(() => null)) as { detail?: string } | null;
      return { ok: res.ok, detail: data?.detail };
    });

  const reject = (target: AccessRequest) =>
    handleDecide(target, 'reject', async () => {
      const res = await apiFetch(`${PORTAL_API}/auth/register-requests/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: target.id }),
      });
      const data = (await res.json().catch(() => null)) as { detail?: string } | null;
      return { ok: res.ok, detail: data?.detail };
    });

  const adminCount = users.filter((u) => u.role === 'admin').length;

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (adding) return;
    setError('');
    setSuccess('');
    if (newPassword.length < 8) {
      setError(t('um.pwdTooShort'));
      return;
    }
    setAdding(true);
    try {
      const res = await apiFetch(`${PORTAL_API}/auth/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: newUsername, password: newPassword, role: newRole }),
      });
      const data = (await res.json().catch(() => null)) as { detail?: string } | null;
      if (!res.ok) {
        setError(
          res.status === 409
            ? t('um.duplicate')
            : res.status === 400
              ? t('um.invalidInput')
              : data?.detail || `HTTP ${res.status}`
        );
        return;
      }
      setNewUsername('');
      setNewPassword('');
      setNewRole('viewer');
      setSuccess(t('um.added'));
      setTimeout(() => setSuccess(''), 2000);
      await loadUsers();
    } catch (err) {
      setError(String(err));
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (target: AuthUser) => {
    if (!window.confirm(t('um.confirmDelete', { name: target.username }))) return;
    setError('');
    try {
      const res = await apiFetch(`${PORTAL_API}/auth/users/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: target.id }),
      });
      const data = (await res.json().catch(() => null)) as { detail?: string } | null;
      if (!res.ok) {
        setError(
          data?.detail === 'cannot delete yourself'
            ? t('um.selfDelete')
            : data?.detail === 'cannot delete the last admin'
              ? t('um.lastAdmin')
              : data?.detail || `HTTP ${res.status}`
        );
        return;
      }
      await loadUsers();
    } catch (err) {
      setError(String(err));
    }
  };

  const handleResetPassword = async (target: AuthUser) => {
    if (resetPwd.length < 8) {
      setError(t('um.pwdTooShort'));
      return;
    }
    setError('');
    try {
      const res = await apiFetch(`${PORTAL_API}/auth/users/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: target.id, newPassword: resetPwd }),
      });
      const data = (await res.json().catch(() => null)) as { detail?: string } | null;
      if (!res.ok) {
        setError(data?.detail || `HTTP ${res.status}`);
        return;
      }
      setResettingId('');
      setResetPwd('');
      setSuccess(t('um.resetOk', { name: target.username }));
      setTimeout(() => setSuccess(''), 2000);
      await loadUsers();
    } catch (err) {
      setError(String(err));
    }
  };

  const inputClass =
    'px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl w-full max-w-[95vw] sm:max-w-2xl overflow-hidden">
        {/* Header */}
        <div className="px-4 sm:px-6 py-3 sm:py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2 sm:gap-2.5 min-w-0">
            <div className="p-2 rounded-lg bg-violet-50 dark:bg-violet-950/60 text-violet-600 dark:text-violet-400 shrink-0">
              <Users className="w-4 h-4 sm:w-5 sm:h-5" />
            </div>
            <div className="min-w-0">
              <h3 className="font-semibold text-slate-900 dark:text-slate-100 text-sm sm:text-base truncate">
                {t('um.title')}
              </h3>
              <p className="text-[11px] sm:text-xs text-slate-500 dark:text-slate-400 truncate">
                {t('um.subtitle')}
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

        <div className="p-4 sm:p-6 space-y-4">
          {success && (
            <div className="p-3 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900 rounded-xl flex items-center gap-3 text-emerald-700 dark:text-emerald-300 text-sm">
              <CheckCircle2 className="w-5 h-5 shrink-0" />
              <span>{success}</span>
            </div>
          )}

          {error && (
            <div className="p-3 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 rounded-xl flex items-start gap-2 text-red-700 dark:text-red-300 text-xs">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {/* 待审批的账号申请 */}
          <div className="border border-amber-200/70 dark:border-amber-900/60 rounded-xl overflow-hidden">
            <div className="px-3 sm:px-4 py-2.5 bg-amber-50/70 dark:bg-amber-950/30 flex items-center gap-2 border-b border-amber-200/70 dark:border-amber-900/60">
              <Inbox className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
              <span className="text-xs font-semibold text-amber-800 dark:text-amber-300">
                {t('ar.pendingTitle')}
              </span>
              {requests.length > 0 && (
                <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-500 text-white">
                  {requests.length}
                </span>
              )}
              {requestsLoading && (
                <span className="text-[11px] text-amber-700/70 dark:text-amber-400/70">
                  {t('um.loading')}
                </span>
              )}
            </div>

            {requests.length === 0 ? (
              <div className="px-3 sm:px-4 py-5 text-center text-xs text-slate-400 dark:text-slate-500">
                {t('ar.pendingEmpty')}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-50 dark:bg-slate-800/60 text-slate-500 dark:text-slate-400">
                    <tr>
                      <th className="px-3 sm:px-4 py-2 font-semibold">{t('ar.colApplicant')}</th>
                      <th className="px-3 sm:px-4 py-2 font-semibold">{t('ar.colNote')}</th>
                      <th className="px-3 sm:px-4 py-2 font-semibold hidden sm:table-cell">
                        {t('ar.colTime')}
                      </th>
                      <th className="px-3 sm:px-4 py-2 font-semibold hidden md:table-cell">
                        {t('ar.colIp')}
                      </th>
                      <th className="px-3 sm:px-4 py-2 font-semibold text-right">
                        {t('um.colActions')}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {requests.map((r) => (
                      <tr key={r.id} className="text-slate-700 dark:text-slate-300">
                        <td className="px-3 sm:px-4 py-2 font-medium whitespace-nowrap">
                          {r.username}
                        </td>
                        <td className="px-3 sm:px-4 py-2 text-slate-500 dark:text-slate-400 max-w-[220px] truncate">
                          {r.note || '—'}
                        </td>
                        <td className="px-3 sm:px-4 py-2 hidden sm:table-cell text-slate-400 font-mono text-[11px] whitespace-nowrap">
                          {r.createdAt.slice(0, 19).replace('T', ' ')}
                        </td>
                        <td className="px-3 sm:px-4 py-2 hidden md:table-cell text-slate-400 font-mono text-[11px]">
                          {r.ip}
                        </td>
                        <td className="px-3 sm:px-4 py-2">
                          <div className="flex items-center justify-end gap-1.5">
                            <select
                              value={approveRoles[r.id] || 'viewer'}
                              onChange={(e) =>
                                setApproveRoles((prev) => ({
                                  ...prev,
                                  [r.id]: e.target.value as Role,
                                }))
                              }
                              className="px-2 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-[11px] text-slate-700 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-teal-500"
                            >
                              <option value="viewer">{t('um.roleViewer')}</option>
                              <option value="admin">{t('um.roleAdmin')}</option>
                            </select>
                            <button
                              onClick={() => approve(r)}
                              disabled={decidingId === r.id}
                              className="px-2.5 py-1.5 text-[11px] font-medium text-white bg-teal-600 hover:bg-teal-500 disabled:opacity-50 rounded-lg transition-colors flex items-center gap-1"
                            >
                              <UserCheck className="w-3.5 h-3.5" />
                              {t('ar.approve')}
                            </button>
                            <button
                              onClick={() => reject(r)}
                              disabled={decidingId === r.id}
                              className="px-2.5 py-1.5 text-[11px] font-medium text-red-600 dark:text-red-400 border border-red-200 dark:border-red-900 hover:bg-red-50 dark:hover:bg-red-950/40 disabled:opacity-50 rounded-lg transition-colors flex items-center gap-1"
                            >
                              <UserX className="w-3.5 h-3.5" />
                              {t('ar.reject')}
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Add User Form */}
          <form
            onSubmit={handleAdd}
            className="p-3 sm:p-4 bg-slate-50 dark:bg-slate-800/60 rounded-xl border border-slate-200/80 dark:border-slate-700 space-y-2.5"
          >
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-600 dark:text-slate-300">
              <UserPlus className="w-3.5 h-3.5" />
              {t('um.addTitle')}
            </div>
            <div className="flex flex-col sm:flex-row gap-2">
              <input
                type="text"
                value={newUsername}
                onChange={(e) => setNewUsername(e.target.value)}
                placeholder={t('um.usernamePh')}
                className={`${inputClass} flex-1 min-w-0`}
                required
              />
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder={t('um.passwordPh')}
                className={`${inputClass} flex-1 min-w-0`}
                required
              />
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value as Role)}
                className={`${inputClass} sm:w-32`}
              >
                <option value="viewer">{t('um.roleViewer')}</option>
                <option value="admin">{t('um.roleAdmin')}</option>
              </select>
              <button
                type="submit"
                disabled={adding || !newUsername.trim() || !newPassword}
                className="px-4 py-2 text-xs font-medium text-white bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg shadow-sm shadow-teal-600/20 transition-all flex items-center justify-center gap-1.5"
              >
                <UserPlus className="w-3.5 h-3.5" />
                {t('um.add')}
              </button>
            </div>
          </form>

          {/* User List */}
          <div className="border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
            <table className="w-full text-left text-xs sm:text-sm">
              <thead className="bg-slate-50 dark:bg-slate-800/60 text-slate-500 dark:text-slate-400">
                <tr>
                  <th className="px-3 sm:px-4 py-2.5 font-semibold">{t('um.colUser')}</th>
                  <th className="px-3 sm:px-4 py-2.5 font-semibold">{t('um.colRole')}</th>
                  <th className="px-3 sm:px-4 py-2.5 font-semibold hidden sm:table-cell">
                    {t('um.colCreated')}
                  </th>
                  <th className="px-3 sm:px-4 py-2.5 font-semibold text-right">{t('um.colActions')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {loading && users.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-slate-400">
                      {t('um.loading')}
                    </td>
                  </tr>
                ) : (
                  users.map((u) => {
                    const isSelf = currentUser?.id === u.id;
                    const isLastAdmin = u.role === 'admin' && adminCount <= 1;
                    const deleteBlocked = isSelf || isLastAdmin;
                    return (
                      <React.Fragment key={u.id}>
                        <tr className="text-slate-700 dark:text-slate-300">
                          <td className="px-3 sm:px-4 py-2.5 font-medium">
                            {u.username}
                            {isSelf && (
                              <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full bg-teal-50 dark:bg-teal-950/80 text-teal-600 dark:text-teal-400 border border-teal-200 dark:border-teal-800">
                                {t('um.self')}
                              </span>
                            )}
                          </td>
                          <td className="px-3 sm:px-4 py-2.5">
                            <span
                              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${
                                u.role === 'admin'
                                  ? 'bg-violet-50 dark:bg-violet-950/80 text-violet-700 dark:text-violet-300 border-violet-200 dark:border-violet-800'
                                  : 'bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700'
                              }`}
                            >
                              {u.role === 'admin' && <ShieldCheck className="w-3 h-3" />}
                              {u.role === 'admin' ? t('um.roleAdmin') : t('um.roleViewer')}
                            </span>
                          </td>
                          <td className="px-3 sm:px-4 py-2.5 hidden sm:table-cell text-slate-400 font-mono text-[11px]">
                            {u.createdAt.slice(0, 19).replace('T', ' ')}
                          </td>
                          <td className="px-3 sm:px-4 py-2.5">
                            <div className="flex items-center justify-end gap-1">
                              <button
                                onClick={() => {
                                  setResettingId(resettingId === u.id ? '' : u.id);
                                  setResetPwd('');
                                  setError('');
                                }}
                                className="p-1.5 rounded-lg text-slate-500 hover:text-amber-600 dark:hover:text-amber-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                                title={t('um.reset')}
                              >
                                <KeyRound className="w-3.5 h-3.5" />
                              </button>
                              <button
                                onClick={() => handleDelete(u)}
                                disabled={deleteBlocked}
                                title={
                                  deleteBlocked
                                    ? isSelf
                                      ? t('um.selfDelete')
                                      : t('um.lastAdmin')
                                    : t('um.delete')
                                }
                                className="p-1.5 rounded-lg text-slate-500 hover:text-red-600 dark:hover:text-red-400 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent transition-colors"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          </td>
                        </tr>
                        {resettingId === u.id && (
                          <tr className="bg-amber-50/50 dark:bg-amber-950/20">
                            <td colSpan={4} className="px-3 sm:px-4 py-2.5">
                              <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                                <span className="text-xs text-slate-600 dark:text-slate-300 shrink-0">
                                  {t('um.resetHint', { name: u.username })}
                                </span>
                                <input
                                  type="password"
                                  value={resetPwd}
                                  onChange={(e) => setResetPwd(e.target.value)}
                                  placeholder={t('um.passwordPh')}
                                  className={`${inputClass} flex-1 min-w-0`}
                                />
                                <button
                                  onClick={() => handleResetPassword(u)}
                                  disabled={!resetPwd}
                                  className="px-3 py-2 text-xs font-medium text-white bg-amber-600 hover:bg-amber-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors flex items-center justify-center gap-1.5"
                                >
                                  <Check className="w-3.5 h-3.5" />
                                  {t('um.resetConfirm')}
                                </button>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};
