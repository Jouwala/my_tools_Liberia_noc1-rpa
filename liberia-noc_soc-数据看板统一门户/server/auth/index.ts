// ============================================================================
// 门户鉴权模块 —— 对外出口
// ----------------------------------------------------------------------------
// 2026-09-25 由单文件 server/auth.ts（928 行，越过本项目 500 行红线）拆分而来。
// 拆分属**纯结构重构，行为零变化**；设计与归属见 docs/auth-module-design.md 第四节。
//
//   types.ts     类型、常量、纯函数（无 IO、无状态）
//   password.ts  scrypt 哈希与校验
//   store.ts     AuthStore：用户 / 申请 / 会话 / 限流
//   guard.ts     resolveCaller —— 鉴权决策的唯一实现（含免登录旁路）
//   routes.ts    HTTP 路由分发 + vite 插件挂载
//
// 本入口保留原 server/auth.ts 的导出面，故既有的
//   import { extractBearerToken, getAuthStore, portalAuthPlugin } from './server/auth'
// 无需改动（vite.config.ts 即为此种用法）。
// ============================================================================

export { AuthStore, getAuthStore, type AuthStore as AuthStoreType } from './store';
export {
  resolveCaller,
  isRealAdmin,
  DEV_ADMIN,
  DEV_TOKEN,
  type Caller,
} from './guard';
export { portalAuthPlugin, clientIp } from './routes';
export { hashPassword, verifyPassword } from './password';

export {
  extractBearerToken,
  readJsonBody,
  readSessionToken,
  parseCookies,
  sendJson,
  setSessionCookie,
  clearSessionCookie,
  sanitizeNames,
  sanitizeLanding,
  sanitizeTeam,
  teamPortalPath,
  toPublic,
  toPublicRequest,
  PORTAL_VIEW_MODES,
  TEAM_IDS,
  TEAM_PORTAL_PATHS,
  SESSION_COOKIE_NAME,
  MAX_PENDING_PER_IP,
  MAX_PENDING_TOTAL,
  SESSION_TTL_MS,
  LOGIN_MAX_FAILURES,
  LOGIN_LOCK_MS,
  MIN_PASSWORD_LENGTH,
  USERNAME_PATTERN,
  type Role,
  type PortalViewMode,
  type LandingTarget,
  type TeamId,
  type StoredUser,
  type PublicUser,
  type PageProfilePatch,
  type RegistrationRequest,
  type PublicRequest,
  type RequestStatus,
  type Session,
} from './types';
