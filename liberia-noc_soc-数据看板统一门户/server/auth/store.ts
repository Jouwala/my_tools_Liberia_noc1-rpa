import crypto from 'node:crypto';
import { createAuthPersistence, type AuthPersistence, type StorageInfo } from '../authDb';
import { hashPassword, verifyPassword, newId, newSessionToken } from './password';
import {
  LOGIN_LOCK_MS,
  LOGIN_MAX_FAILURES,
  MAX_PENDING_PER_IP,
  MAX_PENDING_TOTAL,
  MIN_PASSWORD_LENGTH,
  SESSION_TTL_MS,
  USERNAME_PATTERN,
  toPublic,
  toPublicRequest,
  sanitizeLanding,
  sanitizeNames,
  type PageProfilePatch,
  type PublicRequest,
  type PublicUser,
  type RegistrationRequest,
  type RequestStatus,
  type Role,
  type Session,
  type StoredUser,
} from './types';

// ============================================================================
// 账号与会话状态（AuthStore）
// ----------------------------------------------------------------------------
//  - 用户/账号申请/看板权限统一由 ../authDb 持久化：默认 SQLite
//    （<dataDir>/portal-auth.db，WAL + 单事务 + 自动滚动备份），老数据首次启动
//    自动从 users.json / requests.json 迁移；无 node:sqlite 时回退 JSON 文件存储。
//  - 会话仅存内存：随机 token，12h 滑动续期，服务重启后需重新登录
//  - 首次启动自动播种 admin（随机密码，控制台打印，强制首次改密）
//  - 登录失败限流：同来源连续失败 10 次锁 60s
//
// 本文件只有状态与业务规则，不含 HTTP 分发（那是 routes.ts）与调用者解析（guard.ts）。
// ============================================================================

export class AuthStore {
  private users: StoredUser[] = [];
  private requests: RegistrationRequest[] = [];
  private sessions = new Map<string, Session>();
  private failures = new Map<string, { count: number; lockedUntil: number }>();
  private persistence: AuthPersistence | null = null;
  private loaded = false;

  constructor(private dataDir: string) {}

  /** 持久化实例（惰性创建，避免模块加载时就产生磁盘 IO） */
  private getPersistence(): AuthPersistence {
    if (!this.persistence) this.persistence = createAuthPersistence(this.dataDir);
    return this.persistence;
  }

  private seedAdmin(): void {
    const password = crypto.randomBytes(9).toString('base64url');
    const admin: StoredUser = {
      id: newId(),
      username: 'admin',
      role: 'admin',
      passwordHash: hashPassword(password),
      mustChangePassword: true,
      createdAt: new Date().toISOString(),
    };
    this.users.push(admin);
    this.persist();
    console.warn(
      `[auth] 已创建初始管理员：用户名 admin，初始密码 ${password} —— 首次登录会强制修改密码，请立即修改并妥善保管！`
    );
    console.warn(`[auth] 账号与看板权限的存储位置：${this.storageInfo().location}`);
  }

  /** 写回存储（SQLite 事务 / JSON 原子写）；出错必须打日志，绝不静默吞掉 */
  private persist(): void {
    try {
      this.getPersistence().saveUsers(this.users);
    } catch (e) {
      console.error('[auth] 保存用户数据失败：', e);
    }
  }

  private persistRequests(): void {
    try {
      this.getPersistence().saveRequests(this.requests);
    } catch (e) {
      console.error('[auth] 保存账号申请失败：', e);
    }
  }

  /** 供前端「用户管理」展示：账号/密码哈希/看板权限到底存在哪、有多少备份 */
  storageInfo(): StorageInfo {
    return this.getPersistence().info();
  }

  listUsers(): PublicUser[] {
    this.ensureLoaded();
    return this.users.map(toPublic);
  }

  findById(id: string): StoredUser | undefined {
    this.ensureLoaded();
    return this.users.find((u) => u.id === id);
  }

  findByName(username: string): StoredUser | undefined {
    this.ensureLoaded();
    const name = username.trim().toLowerCase();
    return this.users.find((u) => u.username === name);
  }

  verifyCredentials(username: string, password: string): StoredUser | null {
    const user = this.findByName(username);
    if (!user || !verifyPassword(password, user.passwordHash)) return null;
    return user;
  }

  createUser(username: string, password: string, role: Role): PublicUser {
    this.ensureLoaded();
    const user: StoredUser = {
      id: newId(),
      username: username.trim().toLowerCase(),
      role,
      passwordHash: hashPassword(password),
      mustChangePassword: true,
      createdAt: new Date().toISOString(),
    };
    this.users.push(user);
    this.persist();
    return toPublic(user);
  }

  deleteUser(id: string): boolean {
    this.ensureLoaded();
    const before = this.users.length;
    this.users = this.users.filter((u) => u.id !== id);
    if (this.users.length === before) return false;
    this.destroySessionsForUser(id);
    this.persist();
    return true;
  }

  /** 重置/修改密码；重置他人密码时强制其下次登录改密 */
  setPassword(id: string, password: string, mustChange: boolean): PublicUser | null {
    this.ensureLoaded();
    const user = this.users.find((u) => u.id === id);
    if (!user) return null;
    user.passwordHash = hashPassword(password);
    user.mustChangePassword = mustChange;
    this.persist();
    return toPublic(user);
  }

  /**
   * 更新账号的「页面配置」（落地页 + 可见范围白名单）。
   * 只处理显式传入的字段：缺省 = 不改；显式传 null = 清除该维度限制。
   */
  setProfile(id: string, patch: PageProfilePatch): PublicUser | null {
    this.ensureLoaded();
    const user = this.users.find((u) => u.id === id);
    if (!user) return null;
    if (patch.landing !== undefined) {
      user.landing = patch.landing ? sanitizeLanding(patch.landing) : undefined;
    }
    if (patch.allowedGroups !== undefined) {
      user.allowedGroups = patch.allowedGroups === null ? null : sanitizeNames(patch.allowedGroups);
    }
    if (patch.allowedCards !== undefined) {
      user.allowedCards = patch.allowedCards === null ? null : sanitizeNames(patch.allowedCards);
    }
    this.persist();
    return toPublic(user);
  }

  /**
   * 分组改名/删除后迁移各账号白名单里的旧组名（跨文件一致性）。
   *  - to 传新组名 → 白名单中的 from 替换为 to
   *  - to 为 null（分组被删除）→ 从白名单移除 from（取最小权限，避免顺带放开其他分组的看板）
   * 返回受影响账号数，供前端提示管理员；不迁移会导致被授权账号登录后看到空目录。
   */
  remapGroup(from: string, to: string | null): number {
    this.ensureLoaded();
    let affected = 0;
    for (const user of this.users) {
      if (!Array.isArray(user.allowedGroups) || !user.allowedGroups.includes(from)) continue;
      const next = user.allowedGroups.filter((g) => g !== from);
      if (to && !next.includes(to)) next.push(to);
      user.allowedGroups = next;
      affected += 1;
    }
    if (affected > 0) this.persist();
    return affected;
  }

  countAdmins(): number {
    this.ensureLoaded();
    return this.users.filter((u) => u.role === 'admin').length;
  }

  // —— 账号申请（与账号同库：SQLite 的 registration_requests 表 / JSON 的 requests.json）——

  ensureLoaded(): void {
    if (this.loaded) return;
    this.loaded = true;
    const snapshot = this.getPersistence().load();
    this.users = snapshot.users;
    this.requests = snapshot.requests;
    // 只有「此前确实不存在任何数据文件」时才播种初始 admin。
    // 旧实现是在 users.json 解析失败时也走这条路 —— 会用一个全新 admin 覆盖整个账号表。
    if (this.users.length === 0 && snapshot.fresh) this.seedAdmin();
  }

  /** 提交申请；失败时抛 Error，message 为机器可读的原因码 */
  createRegistrationRequest(
    username: string,
    password: string,
    note: string,
    ip: string
  ): PublicRequest {
    this.ensureLoaded();
    const name = username.trim().toLowerCase();
    if (!USERNAME_PATTERN.test(name)) throw new Error('invalid_username');
    if (password.length < MIN_PASSWORD_LENGTH) throw new Error('password_too_short');
    if (this.users.some((u) => u.username === name)) throw new Error('username_taken');
    if (this.requests.some((r) => r.username === name && r.status === 'pending')) {
      throw new Error('request_pending');
    }
    const pending = this.requests.filter((r) => r.status === 'pending');
    if (pending.length >= MAX_PENDING_TOTAL) throw new Error('too_many_requests');
    if (pending.filter((r) => r.ip === ip).length >= MAX_PENDING_PER_IP) {
      throw new Error('too_many_requests');
    }
    const record: RegistrationRequest = {
      id: newId(),
      username: name,
      passwordHash: hashPassword(password),
      note: note.slice(0, 500),
      status: 'pending',
      createdAt: new Date().toISOString(),
      ip,
    };
    this.requests.push(record);
    this.persistRequests();
    console.warn(`[auth] 新账号申请：${name}（来自 ${ip}），等待管理员审批`);
    return toPublicRequest(record);
  }

  listRequests(status?: RequestStatus): PublicRequest[] {
    this.ensureLoaded();
    const list = status ? this.requests.filter((r) => r.status === status) : this.requests;
    return list.map(toPublicRequest).sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
  }

  countPendingRequests(): number {
    this.ensureLoaded();
    return this.requests.filter((r) => r.status === 'pending').length;
  }

  /** 批准：用申请时暂存的密码哈希直接建号（管理员全程看不到明文密码） */
  approveRegistrationRequest(
    id: string,
    role: Role,
    byUsername: string
  ): { user: PublicUser; request: PublicRequest } | null {
    this.ensureLoaded();
    const record = this.requests.find((r) => r.id === id && r.status === 'pending');
    if (!record) return null;
    if (this.users.some((u) => u.username === record.username)) return null;
    const user: StoredUser = {
      id: newId(),
      username: record.username,
      role,
      passwordHash: record.passwordHash,
      mustChangePassword: true,
      createdAt: new Date().toISOString(),
    };
    this.users.push(user);
    record.status = 'approved';
    record.decidedAt = user.createdAt;
    record.decidedBy = byUsername;
    this.persist();
    this.persistRequests();
    console.warn(`[auth] 账号申请已批准：${record.username}（审批人 ${byUsername}，角色 ${role}）`);
    return { user: toPublic(user), request: toPublicRequest(record) };
  }

  /** 驳回：仅标记状态，不建号 */
  rejectRegistrationRequest(id: string, byUsername: string): PublicRequest | null {
    this.ensureLoaded();
    const record = this.requests.find((r) => r.id === id && r.status === 'pending');
    if (!record) return null;
    record.status = 'rejected';
    record.decidedAt = new Date().toISOString();
    record.decidedBy = byUsername;
    this.persistRequests();
    return toPublicRequest(record);
  }

  // —— 会话（内存）——

  createSession(userId: string): string {
    this.purgeExpiredSessions();
    const token = newSessionToken();
    this.sessions.set(token, { userId, expiresAt: Date.now() + SESSION_TTL_MS });
    return token;
  }

  /** 校验 token 并滑动续期；无效/过期返回 null */
  getUserByToken(token: string): PublicUser | null {
    this.ensureLoaded();
    const session = this.sessions.get(token);
    if (!session) return null;
    if (session.expiresAt < Date.now()) {
      this.sessions.delete(token);
      return null;
    }
    const user = this.users.find((u) => u.id === session.userId);
    if (!user) {
      this.sessions.delete(token);
      return null;
    }
    session.expiresAt = Date.now() + SESSION_TTL_MS;
    return toPublic(user);
  }

  destroySession(token: string): void {
    this.sessions.delete(token);
  }

  destroySessionsForUser(userId: string): void {
    for (const [token, session] of this.sessions) {
      if (session.userId === userId) this.sessions.delete(token);
    }
  }

  private purgeExpiredSessions(): void {
    const now = Date.now();
    for (const [token, session] of this.sessions) {
      if (session.expiresAt < now) this.sessions.delete(token);
    }
  }

  // —— 登录失败限流（按来源 IP，内存）——

  isLocked(ip: string): boolean {
    const record = this.failures.get(ip);
    return !!record && record.lockedUntil > Date.now();
  }

  recordFailure(ip: string): void {
    const record = this.failures.get(ip) || { count: 0, lockedUntil: 0 };
    record.count += 1;
    if (record.count >= LOGIN_MAX_FAILURES) {
      record.lockedUntil = Date.now() + LOGIN_LOCK_MS;
      record.count = 0;
    }
    this.failures.set(ip, record);
  }

  clearFailures(ip: string): void {
    this.failures.delete(ip);
  }
}

// —— 单例（进程内唯一，供 vite 插件与各端点共享同一份状态）——
let singleton: AuthStore | null = null;

export function getAuthStore(dataDir: string): AuthStore {
  if (!singleton) singleton = new AuthStore(dataDir);
  return singleton;
}
