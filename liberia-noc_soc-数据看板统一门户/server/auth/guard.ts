import type { IncomingMessage } from 'node:http';
import { isAuthBypass } from '../authSwitch';
import { extractBearerToken, type PublicUser } from './types';
import type { AuthStore } from './store';

// ============================================================================
// 鉴权守卫 —— 新端点复用的**唯一入口**
// ----------------------------------------------------------------------------
// 为什么不是 Express 中间件：门户后端是 vite 的 connect 中间件，
// `server.middlewares.use(path, (req, res) => ...)` 的处理器**没有 `next()`**
// （见 vite.config.ts:176 与 auth.ts 的 portalAuthPlugin），所以守卫只能是
// 「显式解析 + 调用方自己回包」，不能写成 `(req,res,next)` 形态。
//
// 本模块是「调用者是谁」这个决策的**单一实现**。此前有两份副本：
//   1. server/auth.ts 的路由内联判断（用 DEV_ADMIN 整体对象）
//   2. vite.config.ts 的 portal-default 处理器（现场造 {role:'admin'}）
// 两份的免登录旁路写法还不一致。阶段 1 全部改为调用本模块。
//
// 语义（与拆分前完全一致，属纯重构不得改行为）：
//   - realCaller：只认「真实登录」的会话，免登录占位身份不算；
//   - caller    ：免登录模式下回退为 DEV_ADMIN，其余情况无 token 即 null。
//   - 涉及「关闭鉴权」这类危险动作必须用 realCaller。
// ============================================================================

// ============================================================================
// 日常开发免登录（共享鉴权总开关，见 ../authSwitch）
// ----------------------------------------------------------------------------
// 当 auth-switch.json 的 authEnabled=false（或 AUTH_ENABLED=0）时，门户侧所有
// 需要登录的接口都按「本地开发管理员」放行，前端据此跳过登录页。
// 开关默认开启鉴权，故本分支不影响现有行为；生产环境由 authSwitch 的生产保护兜底。
//
// 占位身份的**唯一定义处**：拆分前 auth.ts 用完整对象、vite.config.ts 现场造
// {role:'admin'}，两处不一致；现统一引用这里。
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

/** 返回值的 role 一定是 'admin' | 'viewer'（PublicUser 的 role 类型） */
export interface Caller {
  /** 视角上的调用者：免登录模式下为 DEV_ADMIN，否则为真实会话用户 */
  caller: PublicUser;
  /** 仅真实登录的会话；免登录占位身份时为 null */
  realCaller: PublicUser | null;
  /** 当前是否处于免登录旁路模式 */
  bypass: boolean;
  /** 当前请求携带的 token（未携带为 null） */
  token: string | null;
}

/**
 * 解析调用者。未登录且非免登录模式时返回 null（调用方负责回 401）。
 *
 * @example
 *   const c = resolveCaller(req, store);
 *   if (!c) return sendJson(res, 401, { detail: 'authentication required' });
 *   if (c.caller.role !== 'admin') return sendJson(res, 403, { detail: 'admin role required' });
 *   // 危险动作要求真实登录：if (!c.realCaller) return sendJson(res, 403, {...});
 */
export function resolveCaller(req: IncomingMessage, store: AuthStore): Caller | null {
  const bypass = isAuthBypass();
  const token = extractBearerToken(req);
  const realCaller = token ? store.getUserByToken(token) : null;
  const caller = realCaller ?? (bypass ? DEV_ADMIN : null);
  if (!caller) return null;
  return { caller, realCaller, bypass, token };
}

/**
 * 当前调用者是否为**真实**管理员（免登录占位身份不算）。
 * 用于「关闭鉴权」等危险动作 —— 占位身份不得执行。
 */
export function isRealAdmin(c: Caller): boolean {
  return !!c.realCaller && c.realCaller.role === 'admin';
}
