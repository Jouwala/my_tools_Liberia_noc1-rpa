/**
 * PortalUserMenu.tsx —— 右上角用户信息区（与 uniplam 门户 Navbar 的用户菜单对齐）
 * ============================================================================
 *
 * 背景（2026-10-13）：myapp 从未显示过登录身份。门户 Navbar 右上角有
 * 「用户图标 + 用户名 + 角色徽章 + 下拉菜单」，myapp 需要同样的四项能力：
 * 改密 / 用户管理 / 鉴权开关 / 退出登录。
 *
 * 能力来源：**同源直连门户** `/uniplam/api/auth/*`（见 api.ts 的 portalFetch）。
 * 用户库始终在门户唯一真相源，myapp 不落地任何账号或哈希。
 *
 * 「本机身份」的处理：后端对回环访问直接放行并给占位身份
 * `username=local`（portal_auth.py:_local_session），**不签发门户 token**。
 * 因此本机身份下四项能力全部不可用 —— 这里照实显示 `local` 并加「本机」徽章，
 * 同时禁用菜单项并说明原因，避免用户以为是功能坏了。
 *
 * 组件约定（AGENTS.md 第三节第 3 条）：
 *   - 文案一律 t('key')，i18n.tsx 中英两份；
 *   - 主题取色用 WH 令牌，不写死十六进制；
 *   - 弹窗用 antd Modal（DraggableClickModal 适用于下钻，此处不需要拖拽）。
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Button,
  Dropdown,
  Input,
  Menu,
  Modal,
  Select,
  Spin,
  Switch,
  Tag,
  Tooltip,
  message,
} from 'antd'
import {
  UserOutlined,
  SafetyCertificateOutlined,
  DesktopOutlined,
  LogoutOutlined,
  KeyOutlined,
  TeamOutlined,
  ReloadOutlined,
  CheckOutlined,
  CloseOutlined,
  DeleteOutlined,
  PlusOutlined,
  CaretDownOutlined,
} from '@ant-design/icons'
import { useI18n } from '../i18n'
import { WH } from '../theme'
import {
  readPortalTokenSync,
  portalChangePassword,
  portalListUsers,
  portalCreateUser,
  portalDeleteUser,
  portalResetPassword,
  portalSetUserProfile,
  portalListRegRequests,
  portalApproveRequest,
  portalRejectRequest,
  portalStorageInfo,
  portalGetAuthSwitch,
  portalSetAuthSwitch,
  type PortalUser,
  type PortalRegRequest,
  type PortalSwitchState,
} from '../api'

/** 后端 /api/auth/me 返回的当前身份 */
export interface AuthIdentity {
  username: string
  role: string
}

const NO_TOKEN = 'NO_PORTAL_TOKEN'

/** 门户 token 缺失时给一句可执行的提示（本机身份 / 会话失效两种成因） */
function describeNoToken(t: (k: string) => string, isLocal: boolean) {
  return isLocal ? t('user.localNoToken') : t('user.noPortalToken')
}

/* ==================== 改密弹窗 ==================== */
function ChangePasswordModal({
  open,
  onClose,
  t,
}: {
  open: boolean
  onClose: () => void
  t: (k: string) => string
}) {
  const [cur, setCur] = useState('')
  const [next, setNext] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (next.length < 8) {
      message.error(t('user.pwdTooShort'))
      return
    }
    setBusy(true)
    try {
      await portalChangePassword(cur, next)
      message.success(t('user.pwdChanged'))
      setCur('')
      setNext('')
      onClose()
    } catch (e: any) {
      message.error(e?.detail || e?.message || t('user.opFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      title={t('user.changePassword')}
      onCancel={onClose}
      onOk={() => void submit()}
      confirmLoading={busy}
      okText={t('user.confirm')}
      cancelText={t('user.cancel')}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        <Input.Password
          placeholder={t('user.currentPassword')}
          value={cur}
          autoComplete="current-password"
          onChange={(e) => setCur(e.target.value)}
        />
        <Input.Password
          placeholder={t('user.newPassword')}
          value={next}
          autoComplete="new-password"
          onChange={(e) => setNext(e.target.value)}
        />
        <div style={{ fontSize: '0.75rem', color: 'var(--wh-text-muted)' }}>
          {t('user.pwdHint')}
        </div>
      </div>
    </Modal>
  )
}

/* ==================== 鉴权开关弹窗 ==================== */
function AuthSwitchModal({
  open,
  onClose,
  t,
}: {
  open: boolean
  onClose: () => void
  t: (k: string) => string
}) {
  const [state, setState] = useState<PortalSwitchState | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setState(await portalGetAuthSwitch())
    } catch (e: any) {
      message.error(e?.detail || e?.message || t('user.opFailed'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    if (open) void load()
  }, [open, load])

  const toggle = async (enabled: boolean) => {
    setBusy(true)
    try {
      const r = await portalSetAuthSwitch(enabled)
      message.success(r?.detail || t('user.opOk'))
      await load()
    } catch (e: any) {
      message.error(e?.detail || e?.message || t('user.opFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      title={t('user.authSwitch')}
      onCancel={onClose}
      footer={null}
      width={520}
    >
      {loading || !state ? (
        <div style={{ textAlign: 'center', padding: '2rem 0' }}><Spin /></div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span>{t('user.authSwitchState')}</span>
            <Tag color={state.authEnabled ? 'green' : 'orange'}>
              {state.authEnabled ? t('user.authOn') : t('user.authOff')}
            </Tag>
          </div>
          <div style={{ fontSize: '0.8rem', color: 'var(--wh-text-muted)' }}>
            {t('user.authSwitchSource')}: {state.source}　|　{t('user.authSwitchEnv')}: {state.env}
            {state.envOverride ? `　|　${t('user.authSwitchEnvOverride')}` : ''}
            {state.updatedBy ? `　|　${t('user.authSwitchBy')}: ${state.updatedBy}` : ''}
          </div>
          {!state.authEnabled && (
            <div style={{ color: WH.danger, fontSize: '0.8rem' }}>
              {t('user.authOffWarn')}
            </div>
          )}
          {state.reason && (
            <div style={{ color: WH.danger, fontSize: '0.8rem' }}>{state.reason}</div>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <Switch
              checked={state.authEnabled}
              loading={busy}
              disabled={busy || (state.authEnabled ? !state.canDisable : !state.canEnable)}
              onChange={(v) => void toggle(v)}
            />
            <span style={{ fontSize: '0.8rem', color: 'var(--wh-text-muted)' }}>
              {state.authEnabled ? t('user.authSwitchToOff') : t('user.authSwitchToOn')}
            </span>
          </div>
          {state.authEnabled && !state.canDisable && (
            <div style={{ fontSize: '0.75rem', color: 'var(--wh-text-muted)' }}>
              {t('user.authSwitchNeedRealAdmin')}
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}

/* ==================== 用户管理弹窗 ==================== */
function UserManagementModal({
  open,
  onClose,
  currentUser,
  t,
}: {
  open: boolean
  onClose: () => void
  currentUser: AuthIdentity
  t: (k: string) => string
}) {
  const [users, setUsers] = useState<PortalUser[]>([])
  const [requests, setRequests] = useState<PortalRegRequest[]>([])
  const [storage, setStorage] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // 新建用户
  const [newName, setNewName] = useState('')
  const [newPwd, setNewPwd] = useState('')
  const [newRole, setNewRole] = useState<'admin' | 'viewer'>('viewer')
  const [adding, setAdding] = useState(false)

  // 改他人密码
  const [resetId, setResetId] = useState('')
  const [resetPwd, setResetPwd] = useState('')

  // 权限配置
  const [profileId, setProfileId] = useState('')
  const [landing, setLanding] = useState('')
  const [groups, setGroups] = useState<string[]>([])
  const [cards, setCards] = useState<string[]>([])
  const [savingProfile, setSavingProfile] = useState(false)

  const [approveRoles, setApproveRoles] = useState<Record<string, 'admin' | 'viewer'>>({})
  const [decidingId, setDecidingId] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [u, r] = await Promise.all([portalListUsers(), portalListRegRequests()])
      setUsers(u?.users ?? [])
      setRequests(r?.requests ?? [])
      try {
        const s = await portalStorageInfo()
        setStorage(s?.storage ?? null)
      } catch { /* 存储信息失败不影响主功能 */ }
    } catch (e: any) {
      setError(e?.detail || e?.message || t('user.opFailed'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    if (open) void load()
  }, [open, load])

  const addUser = async () => {
    if (newPwd.length < 8) { message.error(t('user.pwdTooShort')); return }
    setAdding(true)
    try {
      await portalCreateUser(newName.trim(), newPwd, newRole)
      message.success(t('user.userAdded'))
      setNewName(''); setNewPwd(''); setNewRole('viewer')
      await load()
    } catch (e: any) {
      message.error(e?.detail || e?.message || t('user.opFailed'))
    } finally {
      setAdding(false)
    }
  }

  const removeUser = async (id: string) => {
    try {
      await portalDeleteUser(id)
      message.success(t('user.userDeleted'))
      await load()
    } catch (e: any) {
      message.error(e?.detail || e?.message || t('user.opFailed'))
    }
  }

  const doReset = async () => {
    if (resetPwd.length < 8) { message.error(t('user.pwdTooShort')); return }
    try {
      await portalResetPassword(resetId, resetPwd)
      message.success(t('user.pwdReset'))
      setResetId(''); setResetPwd('')
    } catch (e: any) {
      message.error(e?.detail || e?.message || t('user.opFailed'))
    }
  }

  const openProfile = (u: PortalUser) => {
    setProfileId(u.id)
    setLanding(u.landing ?? '')
    setGroups(u.allowedGroups ?? [])
    setCards(u.allowedCards ?? [])
  }

  const saveProfile = async () => {
    setSavingProfile(true)
    try {
      await portalSetUserProfile(profileId, {
        landing: landing || null,
        allowedGroups: groups.length ? groups : null,
        allowedCards: cards.length ? cards : null,
      })
      message.success(t('user.profileSaved'))
      setProfileId('')
      await load()
    } catch (e: any) {
      message.error(e?.detail || e?.message || t('user.opFailed'))
    } finally {
      setSavingProfile(false)
    }
  }

  const decide = async (id: string, approve: boolean) => {
    setDecidingId(id)
    try {
      if (approve) await portalApproveRequest(id, approveRoles[id] ?? 'viewer')
      else await portalRejectRequest(id)
      message.success(t('user.opOk'))
      await load()
    } catch (e: any) {
      message.error(e?.detail || e?.message || t('user.opFailed'))
    } finally {
      setDecidingId('')
    }
  }

  const cellBorder = '1px solid var(--wh-glass-border)'

  return (
    <Modal
      open={open}
      title={t('user.userManagement')}
      onCancel={onClose}
      footer={null}
      width={860}
      styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: '2rem 0' }}><Spin /></div>
      ) : error ? (
        <div style={{ color: WH.danger, padding: '1rem 0' }}>{error}</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {/* 刷新 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => void load()}>
              {t('user.refresh')}
            </Button>
            {storage?.location && (
              <span style={{ fontSize: '0.72rem', color: 'var(--wh-text-muted)' }}>
                {t('user.storageAt')}: {storage.location}
              </span>
            )}
          </div>

          {/* 用户表 */}
          <div>
            <div style={{ fontWeight: 600, marginBottom: '0.5rem' }}>
              {t('user.userList')}（{users.length}）
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                <thead>
                  <tr style={{ textAlign: 'left' }}>
                    <th style={{ padding: '0.4rem', borderBottom: cellBorder }}>{t('user.username')}</th>
                    <th style={{ padding: '0.4rem', borderBottom: cellBorder }}>{t('user.role')}</th>
                    <th style={{ padding: '0.4rem', borderBottom: cellBorder }}>{t('user.mustChange')}</th>
                    <th style={{ padding: '0.4rem', borderBottom: cellBorder }}>{t('user.landing')}</th>
                    <th style={{ padding: '0.4rem', borderBottom: cellBorder }}>{t('user.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id}>
                      <td style={{ padding: '0.4rem', borderBottom: cellBorder }}>{u.username}</td>
                      <td style={{ padding: '0.4rem', borderBottom: cellBorder }}>
                        <Tag color={u.role === 'admin' ? 'violet' : 'default'}>
                          {u.role === 'admin' ? t('user.roleAdmin') : t('user.roleViewer')}
                        </Tag>
                      </td>
                      <td style={{ padding: '0.4rem', borderBottom: cellBorder }}>
                        {u.mustChangePassword ? t('user.yes') : t('user.no')}
                      </td>
                      <td style={{ padding: '0.4rem', borderBottom: cellBorder }}>
                        {u.landing || '—'}
                      </td>
                      <td style={{ padding: '0.4rem', borderBottom: cellBorder }}>
                        <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                          <Button size="small" icon={<KeyOutlined />} onClick={() => { setResetId(u.id); setResetPwd('') }}>
                            {t('user.resetPassword')}
                          </Button>
                          <Button size="small" onClick={() => openProfile(u)}>
                            {t('user.permissions')}
                          </Button>
                          <Button
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            disabled={u.username === currentUser.username}
                            onClick={() => void removeUser(u.id)}
                          >
                            {t('user.delete')}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* 改他人密码 */}
          {resetId && (
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              <Input.Password
                style={{ width: '16rem' }}
                placeholder={t('user.newPassword')}
                value={resetPwd}
                onChange={(e) => setResetPwd(e.target.value)}
              />
              <Button type="primary" size="small" onClick={() => void doReset()}>{t('user.confirm')}</Button>
              <Button size="small" onClick={() => { setResetId(''); setResetPwd('') }}>{t('user.cancel')}</Button>
            </div>
          )}

          {/* 权限配置 */}
          {profileId && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', padding: '0.75rem', border: cellBorder, borderRadius: 'var(--wh-radius-md)' }}>
              <div style={{ fontWeight: 600 }}>{t('user.permissions')}</div>
              <Input
                placeholder={t('user.landingPlaceholder')}
                value={landing}
                onChange={(e) => setLanding(e.target.value)}
              />
              <Select
                mode="tags"
                style={{ width: '100%' }}
                placeholder={t('user.allowedGroups')}
                value={groups}
                onChange={setGroups}
              />
              <Select
                mode="tags"
                style={{ width: '100%' }}
                placeholder={t('user.allowedCards')}
                value={cards}
                onChange={setCards}
              />
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <Button type="primary" size="small" loading={savingProfile} onClick={() => void saveProfile()}>
                  {t('user.save')}
                </Button>
                <Button size="small" onClick={() => setProfileId('')}>{t('user.cancel')}</Button>
              </div>
            </div>
          )}

          {/* 新建用户 */}
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <Input
              style={{ width: '10rem' }}
              placeholder={t('user.username')}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <Input.Password
              style={{ width: '12rem' }}
              placeholder={t('user.password')}
              value={newPwd}
              onChange={(e) => setNewPwd(e.target.value)}
            />
            <Select
              style={{ width: '7rem' }}
              value={newRole}
              onChange={setNewRole}
              options={[
                { value: 'viewer', label: t('user.roleViewer') },
                { value: 'admin', label: t('user.roleAdmin') },
              ]}
            />
            <Button type="primary" size="small" icon={<PlusOutlined />} loading={adding} onClick={() => void addUser()}>
              {t('user.addUser')}
            </Button>
          </div>

          {/* 待审申请 */}
          <div>
            <div style={{ fontWeight: 600, marginBottom: '0.5rem' }}>
              {t('user.pendingRequests')}（{requests.length}）
            </div>
            {requests.length === 0 ? (
              <div style={{ fontSize: '0.8rem', color: 'var(--wh-text-muted)' }}>{t('user.noRequests')}</div>
            ) : (
              requests.map((r) => (
                <div key={r.id} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.4rem', borderBottom: cellBorder, flexWrap: 'wrap' }}>
                  <span style={{ fontWeight: 500, minWidth: '8rem' }}>{r.username}</span>
                  <span style={{ fontSize: '0.72rem', color: 'var(--wh-text-muted)' }}>
                    {r.note || '—'}
                  </span>
                  <Select
                    size="small"
                    style={{ width: '6.5rem' }}
                    value={approveRoles[r.id] ?? 'viewer'}
                    onChange={(v) => setApproveRoles((p) => ({ ...p, [r.id]: v }))}
                    options={[
                      { value: 'viewer', label: t('user.roleViewer') },
                      { value: 'admin', label: t('user.roleAdmin') },
                    ]}
                  />
                  <Button
                    size="small"
                    type="primary"
                    icon={<CheckOutlined />}
                    loading={decidingId === r.id}
                    onClick={() => void decide(r.id, true)}
                  >
                    {t('user.approve')}
                  </Button>
                  <Button
                    size="small"
                    danger
                    icon={<CloseOutlined />}
                    loading={decidingId === r.id}
                    onClick={() => void decide(r.id, false)}
                  >
                    {t('user.reject')}
                  </Button>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </Modal>
  )
}

/* ==================== 右上角用户菜单 ==================== */
export default function PortalUserMenu({
  identity,
  onLogout,
}: {
  identity: AuthIdentity | null
  onLogout: () => void
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [showPwd, setShowPwd] = useState(false)
  const [showUsers, setShowUsers] = useState(false)
  const [showSwitch, setShowSwitch] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const isLocal = identity?.username === 'local'
  const hasPortalToken = !!readPortalTokenSync()
  // 四项能力依赖门户 token；本机身份没有 token，故不可用
  const capable = hasPortalToken
  const isAdmin = identity?.role === 'admin'

  if (!identity) return null

  const run = (fn: () => void) => () => {
    setOpen(false)
    if (!capable) {
      message.warning(describeNoToken(t, isLocal))
      return
    }
    fn()
  }

  return (
    <div ref={ref}>
      {/* 用 antd Dropdown（portal 渲染到 body）而不是自写 absolute 面板：
          Header 有 overflow:hidden 且高仅 56px，absolute 子面板会被裁掉 —— 这是
          下拉"点了不出现"的根因。Dropdown 挂在 body 上，天然不受祖先裁剪影响，
          且自带键盘可达性与外部点击关闭（项目内 TableBrowser.tsx:502 已有同用法）。 */}
      <Dropdown
        open={open}
        onOpenChange={setOpen}
        trigger={['click']}
        placement="bottomRight"
        dropdownRender={() => (
          <div
            style={{
              minWidth: '12rem',
              padding: '0.35rem',
              background: 'var(--wh-glass-panel-solid, var(--wh-glass-panel))',
              border: '1px solid var(--wh-glass-border)',
              borderRadius: 'var(--wh-radius-md)',
              boxShadow: 'var(--wh-shadow-3)',
            }}
          >
            {/* 面板头：当前账号（本机身份额外标注） */}
            <div style={{
              padding: '0.35rem 0.6rem',
              fontSize: '0.7rem',
              color: 'var(--wh-text-muted)',
              borderBottom: '1px solid var(--wh-glass-border)',
              marginBottom: '0.2rem',
            }}>
              {identity!.username}
              {isLocal && ` · ${t('user.localIdentity')}`}
            </div>
            {!capable && (
              <div style={{ padding: '0.3rem 0.6rem 0.45rem', fontSize: '0.68rem', color: WH.danger, lineHeight: 1.5 }}>
                {describeNoToken(t, isLocal)}
              </div>
            )}
            <Menu
              selectable={false}
              items={[
                { key: 'pwd', icon: <KeyOutlined />, label: t('user.changePassword') },
                { key: 'users', icon: <TeamOutlined />, label: t('user.userManagement') },
                { key: 'switch', icon: <SafetyCertificateOutlined />, label: t('user.authSwitch') },
                { type: 'divider' as const },
                { key: 'logout', icon: <LogoutOutlined />, label: t('user.logout'), danger: true },
              ]}
              onClick={({ key }) => {
                if (key === 'logout') { setOpen(false); onLogout(); return }
                run(() => {
                  if (key === 'pwd') setShowPwd(true)
                  else if (key === 'users') setShowUsers(true)
                  else if (key === 'switch') setShowSwitch(true)
                })()
              }}
              style={{
                background: 'transparent',
                border: 'none',
                fontSize: '0.8rem',
              }}
            />
          </div>
        )}
      >
        <Tooltip title={t('user.userTip')}>
          <button
            onClick={() => setOpen(!open)}
            aria-label={t('user.userTip')}
            aria-expanded={open}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.3rem',
              padding: '0.2rem 0.5rem',
              background: 'var(--wh-glass-control)',
              border: '1px solid var(--wh-glass-border)',
              borderRadius: 'var(--wh-radius-md)',
              color: 'var(--wh-text)',
              cursor: 'pointer',
              fontSize: '0.75rem',
              maxWidth: '12rem',
            }}
          >
            <UserOutlined style={{ color: WH.teal }} />
            <span style={{ maxWidth: '6rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {identity!.username}
            </span>
            {isLocal ? (
              <Tag color="blue" style={{ marginInlineEnd: 0, fontSize: '0.65rem', lineHeight: '1.2' }}>
                <DesktopOutlined /> {t('user.localIdentity')}
              </Tag>
            ) : (
              <Tag
                color={isAdmin ? 'violet' : 'default'}
                style={{ marginInlineEnd: 0, fontSize: '0.65rem', lineHeight: '1.2' }}
              >
                {isAdmin ? <SafetyCertificateOutlined /> : null}
                {isAdmin ? t('user.roleAdmin') : t('user.roleViewer')}
              </Tag>
            )}
            {/* 与 olbrportal 的 mp-user-caret 对齐：一个明示可展开的箭头 */}
            <CaretDownOutlined style={{ fontSize: '0.65rem', color: 'var(--wh-text-muted)' }} />
          </button>
        </Tooltip>
      </Dropdown>

      <ChangePasswordModal open={showPwd} onClose={() => setShowPwd(false)} t={t} />
      <UserManagementModal
        open={showUsers}
        onClose={() => setShowUsers(false)}
        currentUser={identity}
        t={t}
      />
      <AuthSwitchModal open={showSwitch} onClose={() => setShowSwitch(false)} t={t} />
    </div>
  )
}
