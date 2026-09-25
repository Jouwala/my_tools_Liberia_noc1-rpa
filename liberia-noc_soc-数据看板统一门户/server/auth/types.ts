import type { IncomingMessage } from 'node:http';
import type { ServerResponse } from 'node:http';

// ============================================================================
// 门户鉴权模块 —— 类型、常量与纯函数
// ----------------------------------------------------------------------------
// 本文件从原 server/auth.ts 拆分而来（2026-09-25），**不含任何 IO 与状态**：
// 只有类型定义、上限常量、以及可单独断言的纯函数（清洗 / 归一化）。
// 拆分的理由与归属见 docs/auth-module-design.md 第四节阶段 1。
// ============================================================================

export type Role = 'admin' | 'viewer';

/** 门户自身视图（与前端 ViewMode 对齐；服务端只用它做白名单校验） */
export type PortalViewMode = 'grid' | 'list' | 'matrix' | 'tasks';

/** 门户视图白名单：landing.view 必须是这四个之一（见 sanitizeLanding） */
export const PORTAL_VIEW_MODES: readonly PortalViewMode[] = ['grid', 'list', 'matrix', 'tasks'];

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
  /** 登录后落地页（缺省 = 不干预，停在全部看板网格；null 与 undefined 同义） */
  landing?: LandingTarget | null;
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

export interface Session {
  userId: string;
  expiresAt: number;
}

// —— 上限与策略常量（集中一处，避免散落在各文件后被改漏）——
export const REQUESTS_FILE = 'requests.json';
/** 同一 IP 最多同时挂起 5 条申请，全体最多 50 条，防止刷单 */
export const MAX_PENDING_PER_IP = 5;
export const MAX_PENDING_TOTAL = 50;
export const SESSION_TTL_MS = 12 * 60 * 60 * 1000;
export const LOGIN_MAX_FAILURES = 10;
export const LOGIN_LOCK_MS = 60 * 1000;
export const MIN_PASSWORD_LENGTH = 8;
export const USERNAME_PATTERN = /^[a-z0-9_.-]{2,32}$/;
/** 请求体上限：64KB（登录/改密等小载荷足够；超限直接断连） */
export const MAX_BODY_BYTES = 64 * 1024;

/** 白名单数组清洗：丢弃空值、去重、限长，防止脏数据把账号锁成空目录 */
export function sanitizeNames(input: unknown): string[] {
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
export function sanitizeLanding(input: unknown): LandingTarget | undefined {
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

export function toPublic(user: StoredUser): PublicUser {
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
export function toPublicRequest(record: RegistrationRequest): PublicRequest {
  const { passwordHash: _hash, ...rest } = record;
  return rest;
}

// ============================================================================
// HTTP 小工具（原 auth.ts 内联实现，收口到此处供 guard / routes / vite 插件复用）
// ----------------------------------------------------------------------------
// 从 vite.config.ts 的 portal-default 处理器里也有一份 sendJson 副本，
// 阶段 1 一并改为引用这里，消除第二份实现。
// ============================================================================

export function sendJson(res: ServerResponse, status: number, payload: unknown): void {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(payload));
}

export function extractBearerToken(req: IncomingMessage): string | null {
  const header = req.headers.authorization;
  const value = Array.isArray(header) ? header[0] : header;
  if (!value) return null;
  const match = /^Bearer\s+(.+)$/i.exec(value.trim());
  return match ? match[1] : null;
}

export function readBody(req: IncomingMessage, limit = MAX_BODY_BYTES): Promise<string> {
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

export async function readJsonBody(req: IncomingMessage): Promise<Record<string, unknown>> {
  const raw = await readBody(req);
  const parsed = JSON.parse(raw) as unknown;
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('invalid JSON payload');
  }
  return parsed as Record<string, unknown>;
}
