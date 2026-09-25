import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Plugin } from 'vite';
import { getAuthSwitch, setAuthEnabled } from '../authSwitch';
import { AuthStore } from './store';
import { resolveCaller, isRealAdmin, DEV_ADMIN, DEV_TOKEN } from './guard';
import {
  MIN_PASSWORD_LENGTH,
  USERNAME_PATTERN,
  readJsonBody,
  sanitizeLanding,
  sanitizeNames,
  sendJson,
  toPublic,
  type PageProfilePatch,
  type Role,
} from './types';

// ============================================================================
// 门户鉴权 HTTP 路由（挂在 vite 服务上的 /api/auth 中间件）
// ----------------------------------------------------------------------------
// 只做「解析请求 → 调 store/guard → 回包」，业务规则在 store.ts。
// 鉴权决策一律走 guard.resolveCaller，不在此处内联判断（避免又出第二份副本）。
// ============================================================================

/**
 * 取客户端真实 IP（用于登录限流与申请配额）。
 *
 * 为什么不能直接用 req.socket.remoteAddress：
 *   nginx 在 location /uniplam/ 明确设置了 X-Real-IP（nginx.conf:364），而门户
 *   只读 socket 地址。nginx 与 9267 同机时，**所有经门户访问的用户共用
 *   '127.0.0.1' 这一个桶** —— 任何人连续 10 次登录失败就会把全站登录锁死 60 秒
 *   （LOGIN_MAX_FAILURES=10），MAX_PENDING_PER_IP=5 也同步退化成「全站只能有
 *   5 条待审申请」。这是可被单人触发的拒绝服务，故按前置代理语义取真实 IP。
 *
 * 安全边界：X-Real-IP 只在**直连方是本机回环**时才可信（即确实经由本机 nginx）。
 * 否则客户端可自行伪造该头来绕过限流，故保留 socket 地址作为不可信来源的回退。
 */
export function clientIp(req: IncomingMessage): string {
  const socketIp = req.socket.remoteAddress || 'unknown';
  const loopback = socketIp === '127.0.0.1' || socketIp === '::1' || socketIp === '::ffff:127.0.0.1';
  if (loopback) {
    const real = req.headers['x-real-ip'];
    const value = Array.isArray(real) ? real[0] : real;
    if (value && value.trim()) return value.trim();
    // 回退到 XFF 的第一段（最靠近客户端的那个）
    const xff = req.headers['x-forwarded-for'];
    const chain = Array.isArray(xff) ? xff[0] : xff;
    const first = chain?.split(',')[0]?.trim();
    if (first) return first;
  }
  return socketIp;
}

async function handleAuthRoute(store: AuthStore, req: IncomingMessage, res: ServerResponse) {
  const method = req.method || 'GET';
  const url = (req.url || '').split('?')[0];

  // 调用者解析（含免登录旁路）—— 唯一实现见 guard.ts
  const auth = resolveCaller(req, store);
  const bypass = auth?.bypass ?? false;
  const token = auth?.token ?? null;
  const realCaller = auth?.realCaller ?? null;
  const caller = auth?.caller ?? null;

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
      const ip = clientIp(req);
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
      const ip = clientIp(req);
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
      const realAdmin = auth ? isRealAdmin(auth) : false;
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
