// ============================================================================
// 门户生产入口（Express）—— B1 整改
// ----------------------------------------------------------------------------
// 背景（2026-10-01 实测）：门户 9267 此前跑的是 `npm run dev`，即 Vite dev server。
// 后果：响应里带 `@vite/client` + `react-refresh`；无压缩/无 tree-shake；HMR 端点
// 对外开着；源码映射可读；dev server 非为并发设计；**登录与鉴权中间件全在里面**，
// 一旦 dev server 崩溃即全站掉登录。
//
// 本文件把 vite.config.ts 里那两个插件中间件（portalAuthPlugin + portal-default）
// 原样搬到 Express 上，**复用同一份鉴权实现，不重写、不改鉴权逻辑**。
//
// 为什么可以直接复用 portalAuthPlugin（已核实 server/auth/routes.ts:404-420）：
//   它的 configureServer(server) 只做一件事 —— 对每个挂载点调
//   `server.middlewares.use(mount, handler)`。而 Express 的 app.use 与此同签名
//   （Express 本就是 connect 的超集），所以喂一个"只实现 middlewares.use"的假
//   server 对象即可，零改动接管全部鉴权路由。
//
// 与 vite.config.ts 的关系（2026-10-01 收口，消除重复实现）：
//   - 鉴权路由 portalAuthPlugin：两边都从 ./server/auth 复用同一份。
//   - portal-default 处理：两边都调用 `server/portalDefault.ts` 的
//     createPortalDefaultHandler —— 逻辑只有一处，dev 与 prod 不会再分叉。
//   本文件与 vite.config.ts 各自只保留「挂载点」差异。
//
// 监听地址：**仅 127.0.0.1**。对外一律由本机 nginx（80/443）反代，
// 这同时消除了"门户自己把 9267 暴露到局域网"的面。
// ============================================================================

import express from 'express';
import path from 'path';
import { fileURLToPath } from 'node:url';
import { getAuthStore, portalAuthPlugin } from './auth';
import { APP_BASE, createPortalDefaultHandler } from './portalDefault';

// __dirname 在 ESM 下不存在，用 import.meta.url 还原（package.json 是 "type": "module"）
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// APP_BASE 由 server/portalDefault.ts 导出（dev 与 prod 共用一个定义）
const PORT = Number(process.env.PORT || 9267);
/** 生产服务只绑回环；对外由 nginx 反代 */
const HOST = process.env.PORTAL_HOST || '127.0.0.1';

const DIST = path.resolve(__dirname, '..', 'dist');

// 全局默认目录落盘位置；可用环境变量 PORTAL_DEFAULT_FILE 覆盖
const DEFAULT_FILE = process.env.PORTAL_DEFAULT_FILE
  ? path.resolve(process.env.PORTAL_DEFAULT_FILE)
  : path.resolve(__dirname, '..', 'portal-default.json');

// 鉴权数据目录（含加盐密码哈希，已 .gitignore）；可用 PORTAL_AUTH_DATA_DIR 覆盖
const AUTH_DATA_DIR = process.env.PORTAL_AUTH_DATA_DIR
  ? path.resolve(process.env.PORTAL_AUTH_DATA_DIR)
  : path.resolve(__dirname, '..', 'auth-data');

const authStore = getAuthStore(AUTH_DATA_DIR);

const app = express();
app.disable('x-powered-by');

// —— 复用鉴权插件：喂一个假 vite server，把它注册的中间件转到 Express ——
// vite 的 hook 可能是函数，也可能是 { handler, order } 对象，两种都兜住。
const authPlugin = portalAuthPlugin(authStore, ['/api/auth', `${APP_BASE}api/auth`]);
const hook = (authPlugin as { configureServer?: unknown }).configureServer;
const runtimeHook =
  typeof hook === 'function'
    ? (hook as (s: unknown) => void)
    : (hook as { handler?: (s: unknown) => void } | undefined)?.handler;
runtimeHook?.({
  middlewares: {
    use: (mount: string, handler: express.RequestHandler) =>
      app.use(mount, handler as express.RequestHandler),
  },
});

// —— portal-default：与 vite.config.ts 共用同一份实现（server/portalDefault.ts）——
// GET/POST 的鉴权门（B3）与落盘逻辑都在那里，此处只挂载，避免 dev/prod 行为分叉。
const defaultHandler = createPortalDefaultHandler({ authStore, defaultFile: DEFAULT_FILE });

// 同时挂根路径与 base 前缀路径（与 vite.config.ts 一致）：
//  - /api/portal-default          → 直连 9267（旧路径，兼容保留）
//  - /uniplam/api/portal-default  → 经 nginx /uniplam/ 反代（前端实际使用）
app.use('/api/portal-default', defaultHandler);
app.use(`${APP_BASE}api/portal-default`, defaultHandler);

// —— 静态资源 + SPA 兜底 ——
// 带内容哈希的构建产物可长期缓存；index.html 必须 no-cache，否则前端发布后
// 用户拿到旧入口（本项目 AGENTS.md 已记录过"改了没生效其实是浏览器缓存"的坑）。
app.use(
  APP_BASE,
  express.static(DIST, {
    index: false,
    setHeaders: (res, filePath) => {
      if (/[.-][0-9a-zA-Z_-]{8,}\.(js|css)$/.test(filePath)) {
        res.setHeader('Cache-Control', 'public, max-age=31536000, immutable');
      }
    },
  }),
);
app.get(`${APP_BASE}*`, (_req, res) => {
  res.setHeader('Cache-Control', 'no-cache');
  res.sendFile(path.join(DIST, 'index.html'));
});

app.listen(PORT, HOST, () => {
  console.log(`[portal] 生产服务已启动: http://${HOST}:${PORT}${APP_BASE} (静态目录 ${DIST})`);
});
