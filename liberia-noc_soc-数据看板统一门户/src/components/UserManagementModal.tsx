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
  LayoutGrid,
  Database,
} from 'lucide-react';
import { useI18n } from '../i18n';
import { PORTAL_API } from '../config';
import { useAuth, type AuthUser, type Role } from '../auth/AuthContext';
import { TEAM_IDS, TEAM_PORTAL_PATHS } from '../auth/AuthContext';
import { PasswordInput } from './PasswordInput';
import type { DashboardItem } from '../types/dashboard';

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

/** GET /auth/storage 返回：账号、密码哈希与看板权限的实际落盘位置和备份情况 */
interface StorageInfo {
  backend: 'sqlite' | 'json';
  location: string;
  migratedFromJson: boolean;
  writeCount: number;
  lastWriteAt: string | null;
  backups: { name: string; size: number; mtime: string }[];
  maxBackups: number;
  backupDir: string;
}

interface UserManagementModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** 现存分组（规范名，来自全局目录）——页面配置里按分组授权用 */
  groups: string[];
  /** 全部看板卡片（来自全局目录）——页面配置里按卡片授权、落地页选择用 */
  dashboards: DashboardItem[];
  /** 分组名 → 当前语言显示名（英文界面下也显示英文分组名） */
  labelOf: (name: string) => string;
}

/** 与 MsPortal/assets/portal.js、olbrportal/assets/olbr.js 同名函数同一口径：
    后端 storage.location 是服务器绝对路径，整条上屏既泄露部署目录，
    路径里的中文目录名在英文界面下又是漏翻。只留文件名——够判断存在哪个库。 */
function storageNameOf(loc: string) {
  const s = String(loc || '');
  const i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'));
  return i >= 0 ? s.slice(i + 1) : s;
}

export const UserManagementModal: React.FC<UserManagementModalProps> = ({
  isOpen,
  onClose,
  groups,
  dashboards,
  labelOf,
}) => {
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

  /** —— 页面配置（管理员为账号指定登录落地页 + 可见范围白名单）—— */
  /** 正在编辑页面配置的账号 id（空 = 面板收起） */
  const [profileUserId, setProfileUserId] = useState('');
  const [profileLandingView, setProfileLandingView] = useState('');
  const [profileLandingCard, setProfileLandingCard] = useState('');
  /** 是否启用可见范围限制（false = 不限制 → 服务端存 null/null） */
  const [profileRestricted, setProfileRestricted] = useState(false);
  const [profileGroups, setProfileGroups] = useState<string[]>([]);
  const [profileCards, setProfileCards] = useState<string[]>([]);
  /** 团队归属（'' = 未指派）。指派后该账号登录即自动进入对应团队门户，
      且只能进入该门户（其余四个在服务端被拒）。 */
  const [profileTeam, setProfileTeam] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);

  /** 账号与看板权限的落盘位置（SQLite/JSON）与自动备份情况 */
  const [storage, setStorage] = useState<StorageInfo | null>(null);

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

  const loadStorage = useCallback(async () => {
    try {
      const res = await apiFetch(`${PORTAL_API}/auth/storage`);
      const data = (await res.json().catch(() => null)) as { storage?: StorageInfo } | null;
      if (res.ok && data?.storage) setStorage(data.storage);
    } catch {
      // 存储信息拿不到不影响账号管理主流程
    }
  }, [apiFetch]);

  useEffect(() => {
    if (isOpen) {
      void loadUsers();
      void loadRequests();
      void loadStorage();
      setError('');
      setSuccess('');
      setNewUsername('');
      setNewPassword('');
      setNewRole('viewer');
      setResettingId('');
      setResetPwd('');
      setDecidingId('');
      setProfileUserId('');
      setSavingProfile(false);
    }
  }, [isOpen, loadUsers, loadRequests, loadStorage]);

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

  /** 勾选/取消勾选一个白名单项 */
  const toggleIn = (list: string[], value: string) =>
    list.includes(value) ? list.filter((x) => x !== value) : [...list, value];

  /** 展开某账号的页面配置面板：用服务端返回的账号数据回填 */
  const openProfile = (target: AuthUser) => {
    setProfileUserId(target.id);
    setProfileLandingView(target.landing?.view || '');
    setProfileLandingCard(target.landing?.cardId || '');
    setProfileRestricted(target.allowedGroups != null || target.allowedCards != null);
    setProfileGroups(Array.isArray(target.allowedGroups) ? target.allowedGroups : []);
    setProfileCards(Array.isArray(target.allowedCards) ? target.allowedCards : []);
    setProfileTeam(target.team || '');
    setError('');
    setSuccess('');
    // 面板在长列表底部时自动滚进可视区（等这一帧渲染完再滚）
    requestAnimationFrame(() => {
      document
        .querySelector('[data-landing-view]')
        ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
  };

  /** 保存页面配置：不受限 → 两个维度都传 null；受限 → 传勾选结果（空数组 = 什么都看不到） */
  const saveProfile = async (target: AuthUser) => {
    if (savingProfile) return;
    setSavingProfile(true);
    setError('');
    try {
      const landing =
        profileLandingView || profileLandingCard
          ? {
              ...(profileLandingView ? { view: profileLandingView } : {}),
              ...(profileLandingCard ? { cardId: profileLandingCard } : {}),
            }
          : null;
      const res = await apiFetch(`${PORTAL_API}/auth/users/profile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: target.id,
          landing,
          allowedGroups: profileRestricted ? profileGroups : null,
          allowedCards: profileRestricted ? profileCards : null,
          // team：空字符串 = 未指派（传 null 清除）；有值 = 指派到该团队。
          // ⚠️ 与 landing/白名单不同，team 是**独立**的一维：白名单管「看得到哪些看板」，
          //   team 管「进哪个门户」。两者都为空 = 能看全部看板，但登录后停在主门户。
          team: profileTeam || null,
        }),
      });
      const data = (await res.json().catch(() => null)) as {
        user?: AuthUser;
        detail?: string;
      } | null;
      if (!res.ok || !data?.user) {
        setError(data?.detail || `HTTP ${res.status}`);
        return;
      }
      // 以服务端返回的账号为准回填列表，避免界面与实际配置不一致
      const saved = data.user;
      setUsers((prev) => prev.map((x) => (x.id === saved.id ? saved : x)));
      setSuccess(t('um.pagesSaved', { name: target.username }));
      setTimeout(() => setSuccess(''), 3000);
      setProfileUserId('');
    } catch (err) {
      setError(String(err));
    } finally {
      setSavingProfile(false);
    }
  };

  /** 该账号是否已配置页面（按钮高亮用） */
  const hasPageConfig = (u: AuthUser) =>
    !!u.landing || u.allowedGroups != null || u.allowedCards != null || !!u.team;

  /** 页面配置里可选的落地视图（value 与后端 PortalViewMode 对齐） */
  const landingViews: { value: string; label: string }[] = [
    { value: 'grid', label: t('um.viewGrid') },
    { value: 'list', label: t('um.viewList') },
    { value: 'matrix', label: t('um.viewMatrix') },
    { value: 'tasks', label: t('um.viewTasks') },
  ];

  /** 当前正在编辑页面配置的用户（用于底部固定操作栏） */
  const profileUser = users.find((u) => u.id === profileUserId) ?? null;

  const inputClass =
    'px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div className="spatial-modal-surface bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl w-full max-w-[95vw] sm:max-w-2xl max-h-[92vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="px-4 sm:px-6 py-3 sm:py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between shrink-0">
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

        <div className="p-4 sm:p-6 space-y-4 flex-1 min-h-0 overflow-y-auto">
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

          {/* 存储位置：账号、密码哈希、看板权限到底落在哪，管理员能一眼看到 */}
          {storage && (
            <div
              data-storage-strip
              className="px-3 py-2 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-700 flex items-start gap-2 text-[11px] text-slate-500 dark:text-slate-400"
            >
              <Database className="w-3.5 h-3.5 mt-0.5 shrink-0 text-teal-600 dark:text-teal-400" />
              <div className="min-w-0 space-y-0.5">
                <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                  <span className="font-semibold text-slate-700 dark:text-slate-200">
                    {t('um.storage')}
                  </span>
                  <span className="px-1.5 py-0.5 rounded bg-teal-50 dark:bg-teal-950/60 text-teal-700 dark:text-teal-300 font-medium">
                    {storage.backend === 'sqlite' ? t('um.storageSqlite') : t('um.storageJson')}
                  </span>
                  <span>{t('um.backups', { n: storage.backups.length })}</span>
                  {storage.lastWriteAt && (
                    <span>
                      {t('um.lastWrite')} {storage.lastWriteAt.slice(0, 19).replace('T', ' ')}
                    </span>
                  )}
                  {storage.migratedFromJson && (
                    <span className="text-amber-600 dark:text-amber-400">
                      {t('um.migrated')}
                    </span>
                  )}
                </div>
                <div className="font-mono break-all" title={storageNameOf(storage.location)}>
                  {storageNameOf(storage.location)}
                </div>
              </div>
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
              <PasswordInput
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder={t('um.passwordPh')}
                className={`${inputClass} flex-1 min-w-0 pr-10`}
                toggleId="new-user"
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
                                onClick={() =>
                                  profileUserId === u.id ? setProfileUserId('') : openProfile(u)
                                }
                                className={`p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors ${
                                  hasPageConfig(u)
                                    ? 'text-teal-600 dark:text-teal-400'
                                    : 'text-slate-500 hover:text-teal-600 dark:hover:text-teal-400'
                                }`}
                                title={t('um.pages')}
                                data-pages-button
                                data-configured={hasPageConfig(u) ? 'true' : 'false'}
                              >
                                <LayoutGrid className="w-3.5 h-3.5" />
                              </button>
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
                                <PasswordInput
                                  value={resetPwd}
                                  onChange={(e) => setResetPwd(e.target.value)}
                                  placeholder={t('um.passwordPh')}
                                  className={`${inputClass} flex-1 min-w-0 pr-10`}
                                  toggleId="reset-user"
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
                        {profileUserId === u.id && (
                          <tr className="bg-teal-50/40 dark:bg-teal-950/20">
                            <td colSpan={4} className="px-3 sm:px-4 py-3 space-y-3">
                              <div className="flex flex-wrap items-center gap-2">
                                <LayoutGrid className="w-3.5 h-3.5 text-teal-600 dark:text-teal-400 shrink-0" />
                                <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
                                  {t('um.pagesTitle', { name: u.username })}
                                </span>
                                <span className="text-[11px] text-slate-400">
                                  {t('um.pagesSubtitle')}
                                </span>
                              </div>

                              <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                                <span className="text-[11px] text-slate-500 dark:text-slate-400 sm:w-24 shrink-0">
                                  {t('um.landing')}
                                </span>
                                <select
                                  value={profileLandingView}
                                  onChange={(e) => setProfileLandingView(e.target.value)}
                                  data-landing-view
                                  className={`${inputClass} sm:w-40 py-1.5 text-xs`}
                                >
                                  <option value="">{t('um.landingNone')}</option>
                                  {landingViews.map((v) => (
                                    <option key={v.value} value={v.value}>
                                      {v.label}
                                    </option>
                                  ))}
                                </select>
                                <select
                                  value={profileLandingCard}
                                  onChange={(e) => setProfileLandingCard(e.target.value)}
                                  data-landing-card
                                  className={`${inputClass} flex-1 min-w-0 py-1.5 text-xs`}
                                >
                                  <option value="">{t('um.landingNoCard')}</option>
                                  {dashboards.map((d) => (
                                    <option key={d.id} value={d.id}>
                                      {labelOf(d.category)} · {d.title}
                                    </option>
                                  ))}
                                </select>
                              </div>

                              {/* ---- 团队归属（2026-10-29 加）----
                                  与上面「登录后落地」是**两件不同的事**：
                                    · 落地 = 打开门户后的**视图/卡片**（门户自己的界面）
                                    · 团队 = 进**哪个门户**（/v3/fo_portal/ 等）
                                  指派团队后：该账号访问 /v3/olbrportal/ 会自动跳到
                                  对应团队门户，且**只能**进入该门户（其余四个被服务端拒绝）。 */}
                              <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                                <span className="text-[11px] text-slate-500 dark:text-slate-400 sm:w-24 shrink-0">
                                  {t('um.team')}
                                </span>
                                <select
                                  value={profileTeam}
                                  onChange={(e) => setProfileTeam(e.target.value)}
                                  data-team-select
                                  className={`${inputClass} sm:w-56 py-1.5 text-xs`}
                                >
                                  <option value="">{t('um.teamNone')}</option>
                                  {TEAM_IDS.map((tid) => (
                                    <option key={tid} value={tid}>
                                      {t(`um.team.${tid}`)} · {TEAM_PORTAL_PATHS[tid]}
                                    </option>
                                  ))}
                                </select>
                                <span className="text-[11px] text-slate-400">{t('um.teamHint')}</span>
                              </div>

                              <div className="border-t border-slate-200/70 dark:border-slate-700/70 pt-2.5 space-y-2">
                                <label className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300 cursor-pointer">
                                  <input
                                    type="checkbox"
                                    checked={profileRestricted}
                                    onChange={(e) => setProfileRestricted(e.target.checked)}
                                    data-restricted-toggle
                                    className="accent-teal-600"
                                  />
                                  {profileRestricted ? t('um.allowedCustom') : t('um.allowedAll')}
                                </label>

                                {profileRestricted && (
                                  <>
                                    <div className="space-y-1">
                                      <p className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                                        {t('um.allowedGroups')}（{profileGroups.length}/{groups.length}）
                                      </p>
                                      <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto">
                                        {groups.map((g) => {
                                          const on = profileGroups.includes(g);
                                          return (
                                            <button
                                              key={g}
                                              type="button"
                                              aria-pressed={on}
                                              data-allowed-group={g}
                                              onClick={() =>
                                                setProfileGroups((prev) => toggleIn(prev, g))
                                              }
                                              className={`px-2 py-1 rounded-full border text-[11px] transition-colors ${
                                                on
                                                  ? 'bg-teal-600 text-white border-teal-600'
                                                  : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
                                              }`}
                                            >
                                              {labelOf(g)}
                                            </button>
                                          );
                                        })}
                                      </div>
                                    </div>

                                    <div className="space-y-1">
                                      <p className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">
                                        {t('um.allowedCards')}（{profileCards.length}/
                                        {dashboards.length}）
                                      </p>
                                      <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto">
                                        {dashboards.map((d) => {
                                          const on = profileCards.includes(d.id);
                                          return (
                                            <button
                                              key={d.id}
                                              type="button"
                                              aria-pressed={on}
                                              data-allowed-card={d.id}
                                              onClick={() =>
                                                setProfileCards((prev) => toggleIn(prev, d.id))
                                              }
                                              className={`px-2 py-1 rounded-full border text-[11px] transition-colors ${
                                                on
                                                  ? 'bg-cyan-700 text-white border-cyan-700'
                                                  : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
                                              }`}
                                            >
                                              {d.title}
                                            </button>
                                          );
                                        })}
                                      </div>
                                    </div>

                                    {profileGroups.length === 0 && profileCards.length === 0 && (
                                      <p className="text-[11px] text-amber-600 dark:text-amber-400 flex items-center gap-1">
                                        <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                                        {t('um.allowedEmpty')}
                                      </p>
                                    )}
                                  </>
                                )}

                                <p className="text-[11px] text-slate-400">
                                  {t('um.allowedHint')} {t('um.navVisibilityOnly')}
                                </p>
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

        {/* 底部固定操作栏：放在滚动区之外，面板内容再长「保存页面配置」也常驻可见 */}
        {profileUser && (
          <div className="shrink-0 px-4 sm:px-6 py-3 border-t border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/60 flex items-center justify-between gap-3">
            <span className="flex items-center gap-1.5 min-w-0 text-[11px] text-slate-500 dark:text-slate-400">
              <LayoutGrid className="w-3.5 h-3.5 text-teal-600 dark:text-teal-400 shrink-0" />
              <span className="truncate">{t('um.pagesTitle', { name: profileUser.username })}</span>
            </span>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => setProfileUserId('')}
                data-cancel-profile
                className="px-3 py-2 text-xs font-medium text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
              >
                {t('um.pagesCancel')}
              </button>
              <button
                onClick={() => void saveProfile(profileUser)}
                disabled={savingProfile}
                data-save-profile
                className="px-3 py-2 text-xs font-medium text-white bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500 disabled:opacity-50 rounded-lg shadow-sm transition-all flex items-center gap-1.5"
              >
                <Check className="w-3.5 h-3.5" />
                {t('um.pagesSave')}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
