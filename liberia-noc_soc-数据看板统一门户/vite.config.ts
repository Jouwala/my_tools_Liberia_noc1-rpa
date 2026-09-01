import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import fs from 'fs';
import path from 'path';
import {defineConfig, type Plugin} from 'vite';
import type {IncomingMessage, ServerResponse} from 'node:http';
import {extractBearerToken, getAuthStore, portalAuthPlugin} from './server/auth';

// ============================================================================
// 门户默认目录（portal-default.json）服务端持久化
// ----------------------------------------------------------------------------
// 需求：只有在本机 http://localhost:9267/uniplam/ 上编辑并点「保存为默认目录」
// 的看板目录，才写入服务端 portal-default.json 作为全局默认；其他电脑通过
// http://192.168.100.20:9267/uniplam/ 访问时统一加载这份默认目录，而不是各自
// localStorage 里的旧状态。
//
//  - GET  /api/portal-default  → 任何已登录用户可读（返回已保存目录；未保存时 404）
//  - POST /api/portal-default  → 需管理员登录态（Bearer token），且仅允许回环地址 +
//    Host 为 localhost/127.0.0.1（即只有本机管理员能把当前目录保存为默认），其他一律 401/403。
// ============================================================================

/** 应用部署子路径（nginx 的 /uniplam/ 反代），与下方 base 保持一致 */
const APP_BASE = '/uniplam/';

const DEFAULT_FILE = path.resolve(__dirname, 'portal-default.json');

// 鉴权数据目录（users.json 等），已加入 .gitignore；
// 可用环境变量 PORTAL_AUTH_DATA_DIR 覆盖（如测试实例与生产数据隔离）。
const AUTH_DATA_DIR = process.env.PORTAL_AUTH_DATA_DIR
  ? path.resolve(process.env.PORTAL_AUTH_DATA_DIR)
  : path.resolve(__dirname, 'auth-data');
const authStore = getAuthStore(AUTH_DATA_DIR);

const LOOPBACK_ADDRESSES = new Set(['127.0.0.1', '::1', '::ffff:127.0.0.1']);

/** 是否来自本机的请求（回环 IP + localhost/127.0.0.1 Host 头双重校验，端口不限） */
function isLocalhostSaveRequest(req: {socket?: {remoteAddress?: string}; headers: Record<string, string | string[] | undefined>}): boolean {
  const remote = req.socket?.remoteAddress || '';
  if (!LOOPBACK_ADDRESSES.has(remote)) return false;
  const host = String(req.headers.host || '').replace(/:\d+$/, '');
  return host === 'localhost' || host === '127.0.0.1';
}

function portalDefaultStorePlugin(): Plugin {
  return {
    name: 'portal-default-store',
    configureServer(server) {
      const handler = (req: IncomingMessage, res: ServerResponse) => {
        const sendJson = (status: number, payload: unknown) => {
          res.statusCode = status;
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(JSON.stringify(payload));
        };

        if (req.method === 'GET') {
          try {
            if (fs.existsSync(DEFAULT_FILE)) {
              res.setHeader('Content-Type', 'application/json; charset=utf-8');
              res.end(fs.readFileSync(DEFAULT_FILE, 'utf-8'));
            } else {
              sendJson(404, {detail: 'portal default catalog not saved yet'});
            }
          } catch (e) {
            sendJson(500, {detail: `read portal-default.json failed: ${String(e)}`});
          }
          return;
        }

        if (req.method === 'POST') {
          // 鉴权门：必须携带有效管理员会话（前端 apiFetch 自动注入 Bearer token）
          const token = extractBearerToken(req);
          const caller = token ? authStore.getUserByToken(token) : null;
          if (!caller) {
            sendJson(401, {detail: '请先登录后再保存默认目录'});
            return;
          }
          if (caller.role !== 'admin') {
            sendJson(403, {detail: '仅管理员可保存默认目录'});
            return;
          }
          if (!isLocalhostSaveRequest(req)) {
            sendJson(403, {detail: '只有 http://localhost:9267/uniplam/ 允许保存默认目录'});
            return;
          }
          let body = '';
          req.on('data', (chunk) => {
            body += chunk;
            // 防御超大请求体（目录 JSON 正常几百 KB 以内）
            if (body.length > 8 * 1024 * 1024) {
              req.destroy();
            }
          });
          req.on('end', () => {
            try {
              const parsed = JSON.parse(body) as unknown;
              const items = Array.isArray(parsed)
                ? parsed
                : (parsed as {dashboards?: unknown[]})?.dashboards;
              if (!Array.isArray(items) || items.length === 0) {
                sendJson(400, {detail: 'payload must be a non-empty dashboards array'});
                return;
              }
              fs.writeFileSync(DEFAULT_FILE, JSON.stringify(items, null, 2), 'utf-8');
              sendJson(200, {ok: true, count: items.length, savedAt: new Date().toISOString(), file: DEFAULT_FILE});
            } catch (e) {
              sendJson(400, {detail: `invalid JSON payload: ${String(e)}`});
            }
          });
          return;
        }

        sendJson(405, {detail: 'method not allowed'});
      };

      // 同时挂在根路径与 base 前缀路径：
      //  - /api/portal-default          → 直连 9267 时（旧路径，兼容保留）
      //  - /uniplam/api/portal-default  → 经 nginx /uniplam/ 反代时（前端实际使用）
      server.middlewares.use('/api/portal-default', handler);
      server.middlewares.use(`${APP_BASE}api/portal-default`, handler);
    },
  };
}

export default defineConfig(() => {
  return {
    // 门户通过 nginx 子路径 /uniplam/ 访问，构建产物的资源引用必须带此前缀，
    // 否则 dist 中 src="/assets/..." 在 nginx 反代时会去根路径找 JS/CSS 导致 404。
    base: APP_BASE,
    plugins: [
      react(),
      tailwindcss(),
      // 门户自身鉴权接口同样两条路径都挂，避免经 nginx 时被通用 /api/ 规则
      // 抢到 my_app 后端（7038 上该路径只有 GET，POST 会回 405）。
      portalAuthPlugin(authStore, ['/api/auth', `${APP_BASE}api/auth`]),
      portalDefaultStorePlugin(),
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modifyâfile watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      // Disable file watching when DISABLE_HMR is true to save CPU during agent edits.
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
      // 本地 dev 时将 /api 代理到 my_app 后端主机（与 nginx /api/ → my_app 后端 7038 拓扑一致），
      // 供 TaskSyncWidget 实时拉取 /api/tasks。
      // 注意：/api/portal-default 与 /api/auth 分别由上方两个插件的中间件直接处理，
      // 不会落入此代理。
      proxy: {
        '/api': {
          target: 'http://192.168.100.20',
          changeOrigin: true,
        },
      },
    },
  };
});
