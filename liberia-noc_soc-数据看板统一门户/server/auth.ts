import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Plugin } from 'vite';

// ============================================================================
// 门户鉴权模块（挂在 vite 服务上的 /api/auth 中间件）
//  - 用户存 <dataDir>/users.json：scrypt 加盐哈希，落盘，原子写（临时文件 + rename）
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
const USERS_FILE = 'users.json';

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

export class AuthStore {
  private users: StoredUser[] = [];
  private requests: RegistrationRequest[] = [];
  private sessions = new Map<string, Session>();
  private failures = new Map<string, { count: number; lockedUntil: number }>();
  private writeQueue: Promise<void> = Promise.resolve();
  private requestWriteQueue: Promise<void> = Promise.resolve();
  private loaded = false;

  constructor(private dataDir: string) {}

  private get usersFile(): string {
    return path.join(this.dataDir, USERS_FILE);
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
  }

  private persist(): void {
    const snapshot = JSON.stringify(this.users, null, 2);
    this.writeQueue = this.writeQueue
      .then(() => {
        const tmp = `${this.usersFile}.tmp`;
        fs.writeFileSync(tmp, snapshot, 'utf-8');
        fs.renameSync(tmp, this.usersFile);
      })
      .catch((e) => console.error('[auth] 写入 users.json 失败：', e));
  }

  private persistRequests(): void {
    const snapshot = JSON.stringify(this.requests, null, 2);
    this.requestWriteQueue = this.requestWriteQueue
      .then(() => {
        const tmp = `${this.requestsFile}.tmp`;
        fs.writeFileSync(tmp, snapshot, 'utf-8');
        fs.renameSync(tmp, this.requestsFile);
      })
      .catch((e) => console.error('[auth] 写入 requests.json 失败：', e));
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

  // —— 账号申请（requests.json）——

  private get requestsFile(): string {
    return path.join(this.dataDir, REQUESTS_FILE);
  }

  ensureLoaded(): void {
    if (this.loaded) return;
    this.loaded = true;
    fs.mkdirSync(this.dataDir, { recursive: true });
    if (fs.existsSync(this.usersFile)) {
      try {
        const parsed = JSON.parse(fs.readFileSync(this.usersFile, 'utf-8')) as StoredUser[];
        if (Array.isArray(parsed)) this.users = parsed;
      } catch (e) {
        console.error('[auth] users.json 解析失败，视为空用户表：', e);
      }
    }
    if (fs.existsSync(this.requestsFile)) {
      try {
        const parsed = JSON.parse(fs.readFileSync(this.requestsFile, 'utf-8')) as RegistrationRequest[];
        if (Array.isArray(parsed)) this.requests = parsed;
      } catch (e) {
        console.error('[auth] requests.json 解析失败，视为空申请表：', e);
      }
    }
    if (this.users.length === 0) this.seedAdmin();
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

  const token = extractBearerToken(req);
  const caller = token ? store.getUserByToken(token) : null;

  try {
    if (method === 'POST' && url === '/login') {
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
