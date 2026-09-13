import crypto from 'node:crypto';
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Plugin } from 'vite';
import { createAuthPersistence, type AuthPersistence, type StorageInfo } from './authDb';
import { getAuthSwitch, isAuthBypass, setAuthEnabled } from './authSwitch';

// ============================================================================
// 门户鉴权模块（挂在 vite 服务上的 /api/auth 中间件）
//  - 用户/账号申请/看板权限统一由 server/authDb.ts 持久化：
//    默认 SQLite（<dataDir>/portal-auth.db，WAL + 单事务 + 自动滚动备份），
//    老数据首次启动自动从 users.json / requests.json 迁移；
//    无 node:sqlite 时回退 JSON 文件存储（同样带原子写与备份）。
//  - 密码永不存明文：scrypt 加盐哈希（N=16384, r=8, p=1），只存 algorithm$salt$hash。
//  - 会话仅存内存：随机 token，12h 滑动续期，服务重启后需重新登录
//  - 首次启动自动播种 admin（随机密码，控制台打印，强制首次改密）
//  - 登录失败限流：同 IP 连续失败 10 次锁 60s
// ============================================================================

export type Role = 'admin' | 'viewer';

/** 门户自身视图（与前端 ViewMode 对齐；服务端只用它做白名单校验） */
export type PortalViewMode = 'grid' | 'list' | 'matrix' | 'tasks';
const PORTAL_VIEW_MODES: readonly PortalViewMode[] = ['grid', 'list', 'matrix', 'tasks'];

/**
 * 用户级「页面配置」——管理员为每个账号指定「登录后打开哪一页」和「能打开哪些页」。
 *  - landing：登录后落地目标（门户视图 或 指定卡片）
 *  - allowedGroups / allowedCards：可见范围白名单
 *  - 两者同时为 null/undefined 表示不限制（老账号行为完全不变）
 *  - 卡片目录与分组列表都不在服务端存储（它们是全局目录 portal-default.json 的一部分），
 *    因此这里只存「分组规范名 / 卡片 id」，落地与过滤都在前端完成。
 */
export interface LandingTarget {
  /** 门户自身视图；留空 = 不自动切换视图 */
  view?: PortalViewMode;
  /** 目标卡片 id：登录后高亮并滚动到该卡片
   *  （外部页面不自动 window.open —— 非用户手势的弹窗会被浏览器拦截） */
  cardId?: string;
}

export interface StoredUser {
  id: string;
  username: string;
  role: Role;
  passwordHash: string;
  mustChangePassword: boolean;
  createdAt: string;
  /** 登录后落地页（缺省 = 不干预，停在全部看板网格） */
  landing?: LandingTarget;
  /** 可见分组白名单（分组规范名，中文）；null/undefined = 不限制 */
  allowedGroups?: string[] | null;
  /** 可见卡片白名单（DashboardItem.id）；null/undefined = 不限制 */
  allowedCards?: string[] | null;
}

export type PublicUser = Omit<StoredUser, 'passwordHash'>;

/** 页面配置的增量更新载荷：字段缺省 = 不改动该维度；显式传 null = 清除该维度限制 */
export interface PageProfilePatch {
  landing?: LandingTarget | null;
  allowedGroups?: string[] | null;
  allowedCards?: string[] | null;
}

// ============================================================================
// 账号申请（游客自助提交 → 管理员审批）
//  - 申请记录落盘到 <dataDir>/requests.json（原子写）
//  - 申请人自设的密码以 scrypt 哈希暂存，审批通过后直接沿用，管理员看不到明文
//  - 对外返回的记录一律剔除 passwordHash
// ============================================================================
export type RequestStatus = 'pending' | 'approved' | 'rejected';

export interface RegistrationRequest {
  id: string;
  username: string;
  passwordHash: string;
  /** 申请说明（最多 500 字符） */
  note: string;
  status: RequestStatus;
  createdAt: string;
  /** 来源 IP，仅供管理员判断与限流 */
  ip: string;
  decidedAt?: string;
  decidedBy?: string;
}

export type PublicRequest = Omit<RegistrationRequest, 'passwordHash'>;

const REQUESTS_FILE = 'requests.json';
/** 同一 IP 最多同时挂起 5 条申请，全体最多 50 条，防止刷单 */
const MAX_PENDING_PER_IP = 5;
const MAX_PENDING_TOTAL = 50;

interface Session {
  userId: string;
  expiresAt: number;
}

const SESSION_TTL_MS = 12 * 60 * 60 * 1000;
const LOGIN_MAX_FAILURES = 10;
const LOGIN_LOCK_MS = 60 * 1000;
const MIN_PASSWORD_LENGTH = 8;

function hashPassword(password: string): string {
  const salt = crypto.randomBytes(16);
  const hash = crypto.scryptSync(password, salt, 32, { N: 16384, r: 8, p: 1 });
  return `scrypt$${salt.toString('hex')}$${hash.toString('hex')}`;
}

function verifyPassword(password: string, stored: string): boolean {
  const [scheme, saltHex, hashHex] = stored.split('$');
  if (scheme !== 'scrypt' || !saltHex || !hashHex) return false;
  try {
    const expected = Buffer.from(hashHex, 'hex');
    const actual = crypto.scryptSync(password, Buffer.from(saltHex, 'hex'), expected.length, {
      N: 16384,
      r: 8,
      p: 1,
    });
    return actual.length === expected.length && crypto.timingSafeEqual(actual, expected);
  } catch {
    return false;
  }
}

/** 白名单数组清洗：丢弃空值、去重、限长，防止脏数据把账号锁成空目录 */
function sanitizeNames(input: unknown): string[] {
  if (!Array.isArray(input)) return [];
  const out: string[] = [];
  for (const raw of input) {
    const name = String(raw ?? '').trim();
    if (!name || out.includes(name)) continue;
    out.push(name.slice(0, 128));
    if (out.length >= 200) break;
  }
  return out;
}

/** 落地目标清洗：视图名必须合法、cardId 限长；全空视为「不设置」 */
function sanitizeLanding(input: unknown): LandingTarget | undefined {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return undefined;
  const raw = input as { view?: unknown; cardId?: unknown };
  const next: LandingTarget = {};
  if (typeof raw.view === 'string' && (PORTAL_VIEW_MODES as readonly string[]).includes(raw.view)) {
    next.view = raw.view as PortalViewMode;
  }
  const cardId = String(raw.cardId ?? '').trim();
  if (cardId) next.cardId = cardId.slice(0, 64);
  return next.view || next.cardId ? next : undefined;
}

function toPublic(user: StoredUser): PublicUser {
  return {
    id: user.id,
    username: user.username,
    role: user.role,
    mustChangePassword: user.mustChangePassword,
    createdAt: user.createdAt,
    landing: user.landing,
    // 统一归一为 string[] | null：null = 不限制，[] = 什么都不给看（两者语义必须区分开）
    allowedGroups: user.allowedGroups ?? null,
    allowedCards: user.allowedCards ?? null,
  };
}

/** 对外暴露申请记录时剔除密码哈希 */
function toPublicRequest(record: RegistrationRequest): PublicRequest {
  const { passwordHash: _hash, ...rest } = record;
  return rest;
}

// ============================================================================
// 日常开发免登录（共享鉴权总开关，见 server/authSwitch.ts）
// ----------------------------------------------------------------------------
// 当 auth-switch.json 的 authEnabled=false（或 AUTH_ENABLED=0）时，门户侧所有
// 需要登录的接口都按「本地开发管理员」放行，前端据此跳过登录页。
// 开关默认开启鉴权，故本分支不影响现有行为；生产环境由 authSwitch 的生产保护兜底。
// ============================================================================
export const DEV_ADMIN: PublicUser = {
  id: 'dev-admin',
  username: 'dev-admin',
  role: 'admin',
  mustChangePassword: false,
  createdAt: '2026-01-01T00:00:00.000Z',
  landing: null,
  allowedGroups: null,
  allowedCards: null,
};

/** 免登录模式下签发给前端的占位 token（服务端不落库，仅用于前端携带） */
export const DEV_TOKEN = 'dev-bypass';

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
      id: crypto.randomBytes(8).toString('hex'),
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
      id: crypto.randomBytes(8).toString('hex'),
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
  createRegistrationRequest(username: string, password: string, note: string, ip: string): PublicRequest {
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
      id: crypto.randomBytes(8).toString('hex'),
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
      id: crypto.randomBytes(8).toString('hex'),
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
    const token = crypto.randomBytes(32).toString('hex');
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

let singleton: AuthStore | null = null;

export function getAuthStore(dataDir: string): AuthStore {
  if (!singleton) singleton = new AuthStore(dataDir);
  return singleton;
}

export function extractBearerToken(req: IncomingMessage): string | null {
  const header = req.headers.authorization;
  const value = Array.isArray(header) ? header[0] : header;
  if (!value) return null;
  const match = /^Bearer\s+(.+)$/i.exec(value.trim());
  return match ? match[1] : null;
}

function readBody(req: IncomingMessage, limit = 64 * 1024): Promise<string> {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk: Buffer) => {
      body += chunk;
      if (body.length > limit) {
        req.destroy();
        reject(new Error('request body too large'));
      }
    });
    req.on('end', () => resolve(body));
    req.on('error', reject);
  });
}

async function readJsonBody(req: IncomingMessage): Promise<Record<string, unknown>> {
  const raw = await readBody(req);
  const parsed = JSON.parse(raw) as unknown;
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('invalid JSON payload');
  }
  return parsed as Record<string, unknown>;
}

function sendJson(res: ServerResponse, status: number, payload: unknown): void {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(payload));
}

const USERNAME_PATTERN = /^[a-z0-9_.-]{2,32}$/;

async function handleAuthRoute(store: AuthStore, req: IncomingMessage, res: ServerResponse) {
  const method = req.method || 'GET';
  const url = (req.url || '').split('?')[0];

  // 日常开发免登录：开关打开时，未带 token 的请求也按本地开发管理员处理
  const bypass = isAuthBypass();

  const token = extractBearerToken(req);
  // realCaller 只认「真实登录」的会话；caller 在免登录时回退到占位管理员。
  // 涉及「关闭鉴权」这类危险动作时必须用 realCaller，占位身份不算数。
  const realCaller = token ? store.getUserByToken(token) : null;
  const caller = realCaller ?? (bypass ? DEV_ADMIN : null);

  try {
    // —— 鉴权模式探测（公开，前端启动时据此决定是否显示登录页）——
    if (method === 'GET' && url === '/mode') {
      const state = getAuthSwitch();
      sendJson(res, 200, {
        authEnabled: state.authEnabled,
        mode: state.mode,
        source: state.source,
        env: state.env,
      });
      return;
    }

    if (method === 'POST' && url === '/login') {
      // 免登录模式：直接返回开发管理员会话，前端无需知道账号密码
      if (bypass) {
        sendJson(res, 200, { token: DEV_TOKEN, user: DEV_ADMIN });
        return;
      }
      const ip = req.socket.remoteAddress || 'unknown';
      if (store.isLocked(ip)) {
        sendJson(res, 429, { detail: 'too many failed attempts, try again in a minute' });
        return;
      }
      let body: Record<string, unknown>;
      try {
        body = await readJsonBody(req);
      } catch {
        sendJson(res, 400, { detail: 'invalid JSON payload' });
        return;
      }
      const username = String(body.username || '');
      const password = String(body.password || '');
      const user = store.verifyCredentials(username, password);
      if (!user) {
        store.recordFailure(ip);
        sendJson(res, 401, { detail: 'invalid username or password' });
        return;
      }
      store.clearFailures(ip);
      const newToken = store.createSession(user.id);
      sendJson(res, 200, { token: newToken, user: toPublic(user) });
      return;
    }

    // —— 游客可访问：提交账号申请 ——
    if (method === 'POST' && url === '/register-request') {
      const ip = req.socket.remoteAddress || 'unknown';
      let body: Record<string, unknown>;
      try {
        body = await readJsonBody(req);
      } catch {
        sendJson(res, 400, { detail: 'invalid JSON payload' });
        return;
      }
      const username = String(body.username || '');
      const password = String(body.password || '');
      const note = String(body.note || '');
      try {
        const record = store.createRegistrationRequest(username, password, note, ip);
        sendJson(res, 200, { request: record });
      } catch (e) {
        const reason = String((e as Error)?.message);
        const status =
          reason === 'username_taken' || reason === 'request_pending'
            ? 409
            : reason === 'too_many_requests'
              ? 429
              : 400;
        sendJson(res, status, { detail: reason });
      }
      return;
    }

    if (!caller) {
      sendJson(res, 401, { detail: 'authentication required' });
      return;
    }

    // —— 鉴权总开关（管理页按钮）——
    // GET  : 读当前状态 + 当前身份能否关闭/开启
    // POST : { enabled: boolean } 切换开关
    // 权限不对称：关闭鉴权（危险方向）必须持**真实管理员** token；
    // 开启鉴权（安全方向）放行，否则免登录状态下会陷入「没法把鉴权打开」的死结。
    if (url === '/switch') {
      const realAdmin = !!realCaller && realCaller.role === 'admin';
      const state = getAuthSwitch();

      if (method === 'GET') {
        sendJson(res, 200, {
          authEnabled: state.authEnabled,
          mode: state.mode,
          source: state.source,
          env: state.env,
          envOverride: !!state.envOverride,
          reason: state.reason ?? null,
          canDisable: realAdmin,
          canEnable: true,
          /** 当前是否为真实登录（false = 免登录占位身份） */
          realLogin: !!realCaller,
          updatedAt: state.updatedAt ?? null,
          updatedBy: state.updatedBy ?? null,
        });
        return;
      }

      if (method === 'POST') {
        let body: Record<string, unknown>;
        try {
          body = await readJsonBody(req);
        } catch {
          sendJson(res, 400, { detail: 'invalid JSON payload' });
          return;
        }
        if (typeof body.enabled !== 'boolean') {
          sendJson(res, 400, { detail: 'enabled 必须是布尔值' });
          return;
        }
        const enabled = body.enabled;
        if (!enabled && !realAdmin) {
          sendJson(res, 403, {
            detail: '关闭鉴权需要管理员账号登录后操作（免登录占位身份不可用）',
          });
          return;
        }

        const operator = realCaller ? realCaller.username : 'dev-admin(占位身份)';
        const result = setAuthEnabled(enabled, operator);
        if (!result.ok || !result.state) {
          sendJson(res, 409, { detail: result.detail || '切换失败' });
          return;
        }
        const next = result.state;
        console.warn(
          `[auth-switch] ${enabled ? '开启' : '关闭'}鉴权 | 操作者=${operator} 环境=${next.env}`
        );
        sendJson(res, 200, {
          ok: true,
          authEnabled: next.authEnabled,
          mode: next.mode,
          source: next.source,
          env: next.env,
          detail: enabled
            ? '已恢复鉴权：myapp 侧最迟 3 秒内开始要求登录'
            : '已关闭鉴权：myapp 侧最迟 3 秒内开始免登录',
        });
        return;
      }

      sendJson(res, 405, { detail: 'method not allowed' });
      return;
    }

    if (method === 'POST' && url === '/logout') {
      if (token) store.destroySession(token);
      sendJson(res, 200, { ok: true });
      return;
    }

    if (method === 'GET' && url === '/me') {
      sendJson(res, 200, { user: caller });
      return;
    }

    if (method === 'POST' && url === '/change-password') {
      const body = await readJsonBody(req);
      const currentPassword = String(body.currentPassword || '');
      const newPassword = String(body.newPassword || '');
      if (newPassword.length < MIN_PASSWORD_LENGTH) {
        sendJson(res, 400, { detail: `password must be at least ${MIN_PASSWORD_LENGTH} characters` });
        return;
      }
      const verified = store.verifyCredentials(caller.username, currentPassword);
      if (!verified || verified.id !== caller.id) {
        sendJson(res, 401, { detail: 'current password is incorrect' });
        return;
      }
      const updated = store.setPassword(caller.id, newPassword, false);
      if (!updated) {
        sendJson(res, 404, { detail: 'user not found' });
        return;
      }
      store.destroySessionsForUser(caller.id);
      const newToken = store.createSession(caller.id);
      sendJson(res, 200, { token: newToken, user: updated });
      return;
    }

    // —— 以下仅管理员 ——
    if (caller.role !== 'admin') {
      sendJson(res, 403, { detail: 'admin role required' });
      return;
    }

    if (method === 'GET' && url === '/register-requests') {
      sendJson(res, 200, { requests: store.listRequests('pending') });
      return;
    }

    if (method === 'POST' && url === '/register-requests/approve') {
      const body = await readJsonBody(req);
      const id = String(body.id || '');
      const role: Role = body.role === 'admin' ? 'admin' : 'viewer';
      const result = store.approveRegistrationRequest(id, role, caller.username);
      if (!result) {
        sendJson(res, 404, { detail: 'request not found, already handled, or username taken' });
        return;
      }
      sendJson(res, 200, { user: result.user, request: result.request });
      return;
    }

    if (method === 'POST' && url === '/register-requests/reject') {
      const body = await readJsonBody(req);
      const id = String(body.id || '');
      const record = store.rejectRegistrationRequest(id, caller.username);
      if (!record) {
        sendJson(res, 404, { detail: 'request not found or already handled' });
        return;
      }
      sendJson(res, 200, { request: record });
      return;
    }

    if (method === 'GET' && url === '/users') {
      sendJson(res, 200, { users: store.listUsers() });
      return;
    }

    // 账号/密码哈希/看板权限的存储位置与备份情况（管理员在「用户管理」里可见）
    if (method === 'GET' && url === '/storage') {
      sendJson(res, 200, { storage: store.storageInfo() });
      return;
    }

    if (method === 'POST' && url === '/users') {
      const body = await readJsonBody(req);
      const username = String(body.username || '').trim().toLowerCase();
      const password = String(body.password || '');
      const role = body.role === 'admin' ? 'admin' : 'viewer';
      if (!USERNAME_PATTERN.test(username)) {
        sendJson(res, 400, { detail: 'username must be 2-32 chars of a-z 0-9 _ . -' });
        return;
      }
      if (password.length < MIN_PASSWORD_LENGTH) {
        sendJson(res, 400, { detail: `password must be at least ${MIN_PASSWORD_LENGTH} characters` });
        return;
      }
      if (store.findByName(username)) {
        sendJson(res, 409, { detail: 'username already exists' });
        return;
      }
      sendJson(res, 200, { user: store.createUser(username, password, role) });
      return;
    }

    if (method === 'POST' && url === '/users/delete') {
      const body = await readJsonBody(req);
      const id = String(body.id || '');
      const target = store.findById(id);
      if (!target) {
        sendJson(res, 404, { detail: 'user not found' });
        return;
      }
      if (target.id === caller.id) {
        sendJson(res, 400, { detail: 'cannot delete yourself' });
        return;
      }
      if (target.role === 'admin' && store.countAdmins() <= 1) {
        sendJson(res, 400, { detail: 'cannot delete the last admin' });
        return;
      }
      store.deleteUser(id);
      sendJson(res, 200, { ok: true });
      return;
    }

    if (method === 'POST' && url === '/users/reset-password') {
      const body = await readJsonBody(req);
      const id = String(body.id || '');
      const newPassword = String(body.newPassword || '');
      if (newPassword.length < MIN_PASSWORD_LENGTH) {
        sendJson(res, 400, { detail: `password must be at least ${MIN_PASSWORD_LENGTH} characters` });
        return;
      }
      if (!store.findById(id)) {
        sendJson(res, 404, { detail: 'user not found' });
        return;
      }
      store.setPassword(id, newPassword, true);
      store.destroySessionsForUser(id);
      sendJson(res, 200, { ok: true });
      return;
    }

    if (method === 'POST' && url === '/users/profile') {
      const body = await readJsonBody(req);
      const id = String(body.id || '');
      if (!store.findById(id)) {
        sendJson(res, 404, { detail: 'user not found' });
        return;
      }
      const patch: PageProfilePatch = {};
      // landing 传 null（或清洗后为空）表示清除落地页
      if ('landing' in body) patch.landing = sanitizeLanding(body.landing) ?? null;
      if ('allowedGroups' in body) {
        patch.allowedGroups = body.allowedGroups === null ? null : sanitizeNames(body.allowedGroups);
      }
      if ('allowedCards' in body) {
        patch.allowedCards = body.allowedCards === null ? null : sanitizeNames(body.allowedCards);
      }
      const updated = store.setProfile(id, patch);
      if (!updated) {
        sendJson(res, 404, { detail: 'user not found' });
        return;
      }
      sendJson(res, 200, { user: updated });
      return;
    }

    if (method === 'POST' && url === '/users/remap-group') {
      const body = await readJsonBody(req);
      const from = String(body.from || '').trim();
      const to =
        body.to === null || body.to === undefined ? null : String(body.to).trim() || null;
      if (!from) {
        sendJson(res, 400, { detail: 'from is required' });
        return;
      }
      sendJson(res, 200, { affected: store.remapGroup(from, to) });
      return;
    }

    sendJson(res, 404, { detail: 'not found' });
  } catch (e) {
    sendJson(res, 400, { detail: `bad request: ${String(e)}` });
  }
}

export function portalAuthPlugin(store: AuthStore, mountPaths: string[] = ['/api/auth']): Plugin {
  return {
    name: 'portal-auth',
    configureServer(server) {
      store.ensureLoaded();
      // 启动即解析并打印鉴权模式（免登录模式下会在控制台留下醒目记录）
      getAuthSwitch();
      // 每个挂载点都注册一次：既支持直连 dev 服务的 /api/auth，
      // 也支持经 nginx /uniplam/ 反代后的 /uniplam/api/auth。
      for (const mount of mountPaths) {
        server.middlewares.use(mount, (req, res) => {
          void handleAuthRoute(store, req, res);
        });
      }
    },
  };
}
