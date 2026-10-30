import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Plugin } from 'vite';
import { getAuthSwitch, setAuthEnabled } from '../authSwitch';
import { AuthStore } from './store';
import { resolveCaller, isRealAdmin, DEV_ADMIN, DEV_TOKEN } from './guard';
import {
  MIN_PASSWORD_LENGTH,
  SESSION_TTL_MS,
  USERNAME_PATTERN,
  readJsonBody,
  readSessionToken,
  sanitizeLanding,
  sanitizeNames,
  sanitizeTeam,
  sendJson,
  setSessionCookie,
  clearSessionCookie,
  teamPortalPath,
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
      /* 同时种下 Cookie 副本：团队门户的服务端访问控制（nginx auth_request）
         靠它判断「这个人属于哪个团队」—— 浏览器直接访问 URL 时不会带
         localStorage 里的 token，只有 Cookie 能跟请求一起到服务端。
         详见 types.ts 的 SESSION_COOKIE_NAME 一节。 */
      setSessionCookie(res, newToken, SESSION_TTL_MS / 1000);
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

    /* --------------------------------------------------------------- 团队 --
     * 团队门户的访问控制（2026-10-29 加）。三个端点：
     *   GET  /team         —— 前端用：我是谁、属于哪个团队、该去哪
     *   GET  /team-gate    —— nginx auth_request 用：这个团队我能不能进
     *   GET  /team-landing —— nginx 用：/v3/olbrportal/ 该 302 到哪
     *
     * ⚠️⚠️ **下面两个 nginx 端点必须在「未登录就 401」那道闸门之前**
     *   （即在 `if (!caller)` 之前），原因有两条，都很要紧：
     *
     *   ① nginx 的 auth_request **子请求不带 Authorization 头** —— 它只带
     *      原始请求的 Cookie。resolveCaller 只认 Authorization 头，所以
     *      在闸门之后的话，caller 恒为 null → 一律 401 → 「已登录但团队不对」
     *      与「压根没登录」被混成同一个结果，nginx 只能一律拒绝，
     *      用户看不到「你没权限」和「请先登录」的区别。
     *      故这两个端点**自己**用 readSessionToken() 解析身份
     *      （Authorization 头优先、Cookie 其次）。
     *
     *   ② /team-landing 的语义是「无团队归属 → 200 放行；未登录 → 也 200 放行」，
     *      若被闸门拦成 401，nginx 会把它当成拒绝 → 主门户对未登录用户也 401，
     *      那就把「主门户是公开入口」这个既有行为改掉了（回归事故）。
     * ------------------------------------------------------------------ */

    /* nginx auth_request 的判定端点。
     * nginx 侧配置：
     *     auth_request /uniplam/api/auth/team-gate/fo;
     *     error_page 401 = @team_unauthorized;
     *     error_page 403 = @team_forbidden;
     *
     * ⚠️⚠️ **为什么用路径参数（/team-gate/fo）而不是查询参数（?team=fo）**
     *   —— 这是本机 2026-10-29 实测踩出来的坑，不是风格偏好：
     *   nginx 的 `auth_request` 指令里写的 URI 会被当成**内部子请求的 URI**，
     *   其中出现的 `?` **不会被当作查询串分隔符**，而是被转义进路径里。
     *   实测（独立 nginx 实例 + 回显上游）上游收到的是：
     *       auth_request /probe?team=fo  →  上游看到 url = "/probe%3Fteam=fo"
     *   也就是说 `?` 变成了 `%3F`，**后端拿不到 team 参数**。
     *   于是后端只能返回 400（缺参数）→ nginx 把非 2xx 当作拒绝 →
     *   「合法用户访问自己的团队门户」被误判成 401。
     *   改成路径形式后，nginx 子请求的 URI 就是干净的 /team-gate/fo，
     *   后端从路径末段取团队 id —— 实测通过。
     *
     * 判定规则（fail-closed）：
     *   · 没有身份            → 401（未登录）→ nginx 回 401，页面引导登录
     *   · 有身份但没有 team   → 403（未分配团队）→ 一律不放行
     *   · team 与请求的不一致 → 403（不是该团队成员）
     *   · 完全一致            → 200（放行）
     *
     * auth_request 只关心「2xx = 放行、401/403 = 拒绝」，
     * 故不必回传业务结论头；nginx 用 error_page 区分两种拒绝。
     *
     * ⚠️ 免登录旁路（开发模式）下没有真实会话（Cookie 里没有 token）→ 401，
     *   团队门户进不去。这是刻意的：免登录是「跳过登录」，不是「变成某个团队的人」。
     *   要在免登录模式下调试团队门户，正确做法是给测试账号配好 team。
   */
    if (method === 'GET' && url.startsWith('/team-gate/')) {
      /* 团队 id 从路径末段取（sanitizeTeam 会把认不得的值变成 undefined） */
      const wanted = sanitizeTeam(url.slice('/team-gate/'.length).replace(/\/+$/, ''));
      if (!wanted) {
        // 没带团队段（或非法）→ 无法判定，一律拒绝（不给「默认放行」的口子）
        sendJson(res, 400, { detail: 'team path segment is required' });
        return;
      }
      // 自己解析身份：Authorization 头优先（脚本场景），Cookie 其次（页面导航场景）
      const token = readSessionToken(req);
      const user = token ? store.getUserByToken(token) : null;
      if (!user) {
        sendJson(res, 401, { detail: 'authentication required' });
        return;
      }
      if (!user.team) {
        sendJson(res, 403, { detail: 'account is not assigned to a team' });
        return;
      }
      if (user.team !== wanted) {
        sendJson(res, 403, { detail: 'account belongs to a different team' });
        return;
      }
      sendJson(res, 200, { ok: true, team: wanted, username: user.username });
      return;
    }

    /* nginx 用：/v3/olbrportal/ 该 302 到哪个团队门户。
     *
     * 语义（**与 auth_request 的协议约定**，本机 2026-10-29 实测确定）：
     *   auth_request 里，上游返回 2xx = 放行；401/403 = 拒绝。
     *   nginx 侧配的是 `error_page 403 = @team_landing_redirect`，
     *   所以本端点**必须**在「有团队归属、要跳走」时返回 **403**，
     *   并用响应头 X-Team-Landing 带上目标路径 —— nginx 收到 403 才进
     *   named location 做 302。
     *   · 有团队归属 → **403** + X-Team-Landing: /v3/fo_portal/  → nginx 302 跳转
     *   · 无团队归属 → **200**（无该头）→ nginx 正常放行主门户
     *   · 未登录     → **200**（无该头）→ 同上，主门户是公开入口
     *
     * ⚠️ 为什么「有归属」要用 403 这个看起来反直觉的状态码：
     *   auth_request 没有「拒绝但带信息」的第三种状态，只有 2xx/非 2xx。
     *   而我们要表达的是「**别在这里服务，去那边**」—— 用 403 触发
     *   error_page → named location → 302，是这套机制里唯一能做到
     *   「按响应头内容跳转」的写法。（若返回 2xx，nginx 会直接放行，
     *   根本不会去看响应头。）
     *
     * 为什么不让 nginx 直接读 Cookie 自己判断：
     *   Cookie 里放的是**会话 token**，不是团队 id —— 团队归属是**库里的属性**，
     *   管理员随时能改。若把团队 id 也写进 Cookie，管理员改了归属、而用户的
     *   旧 Cookie 还在，nginx 就会按**过期的**团队 id 放行 —— 那正是权限事故。
     *   所以 nginx 必须回源问服务端「这个人现在属于哪个团队」。
     */
    if (method === 'GET' && url === '/team-landing') {
      const token = readSessionToken(req);
      const user = token ? store.getUserByToken(token) : null;
      const team = user?.team ?? null;
      const path = teamPortalPath(team);
      if (path) {
        res.setHeader('X-Team-Landing', path);
        // 403 = 请 nginx 跳到 X-Team-Landing 指的地方（见上面的协议约定）
        sendJson(res, 403, { team, landing: path });
        return;
      }
      // 无团队归属 / 未登录 → 200 → nginx 正常放行主门户
      sendJson(res, 200, { team: null, landing: null });
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
      /* 一起清掉 Cookie 副本：否则会话 token 虽然在服务端失效了，
         浏览器仍带着一个「看起来有身份」的 Cookie 去访问团队门户 ——
         虽然服务端会 401，但那会让每次登出后都留下一条无意义的 401 日志。
         登出后 Cookie 与 localStorage 两处都清干净，状态才是一致的。 */
      clearSessionCookie(res);
      sendJson(res, 200, { ok: true });
      return;
    }

    if (method === 'GET' && url === '/me') {
      sendJson(res, 200, { user: caller });
      return;
    }

    /* /team（前端用）：回答「我是谁、属于哪个团队、该去哪」。
     * 放在这里（已过 caller 检查）是因为它需要真实登录身份 ——
     * 免登录占位身份没有团队归属，返回 null 即可。 */
    if (method === 'GET' && url === '/team') {
      const team = caller?.team ?? null;
      sendJson(res, 200, {
        team,
        portal: teamPortalPath(team),
        user: caller ? { id: caller.id, username: caller.username, role: caller.role } : null,
      });
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
      /* team：null = 清除团队归属（回到「不跳转」）；合法 id = 指派。
         传认不得的值一律当「未指派」（不静默保留旧值）。 */
      if ('team' in body) {
        patch.team = body.team === null ? null : (sanitizeTeam(body.team) ?? null);
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
