import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import fs from 'fs';
import path from 'path';
import {defineConfig, type Plugin} from 'vite';
import type {IncomingMessage, ServerResponse} from 'node:http';
import {extractBearerToken, getAuthStore, portalAuthPlugin} from './server/auth';
import {isAuthBypass} from './server/authSwitch';

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
//
// 落盘格式 v2：{ version, savedAt, groups: string[], dashboards: DashboardItem[] }
//   groups 是分组名称列表（一等实体，含暂无卡片的空分组）；卡片只存组名 category，
//   因此重命名分组 = 批量改写 category，服务端无需做任何映射，卡片关联天然保持。
//   兼容旧的纯数组格式（旧客户端 POST 数组时仍写数组）。
// ============================================================================

/** 应用部署子路径（nginx 的 /uniplam/ 反代），与下方 base 保持一致 */
const APP_BASE = '/uniplam/';

// 全局默认目录落盘位置；可用环境变量 PORTAL_DEFAULT_FILE 覆盖
// （便于起隔离实例做端到端验证，避免动到线上正在使用的默认目录）。
const DEFAULT_FILE = process.env.PORTAL_DEFAULT_FILE
  ? path.resolve(process.env.PORTAL_DEFAULT_FILE)
  : path.resolve(__dirname, 'portal-default.json');

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

/** 组名归一化：去首尾/折叠空白、丢弃空值与「全部」伪分组、忽略大小写去重（与前端同规则） */
function sanitizeGroupNames(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const item of raw) {
    if (typeof item !== 'string') continue;
    const name = item.replace(/\s+/g, ' ').trim();
    if (!name || name === '全部') continue;
    if (out.some((g) => g.toLowerCase() === name.toLowerCase())) continue;
    out.push(name);
  }
  return out;
}

/** 分组英文标签归一化：key 必须落在现存分组内，value 必须是非空字符串（与前端同规则） */
function sanitizeGroupLabels(raw: unknown, groups: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return out;
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    const name = String(key).replace(/\s+/g, ' ').trim();
    if (!groups.includes(name) || typeof value !== 'string') continue;
    const label = value.replace(/\s+/g, ' ').trim();
    if (!label) continue;
    out[name] = label;
  }
  return out;
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
          // 日常开发免登录模式下（见 server/authSwitch.ts）无 token 也按开发管理员放行，
          // 「只有本机可保存」的约束仍然保留，不随鉴权开关放宽。
          const token = extractBearerToken(req);
          const bypass = isAuthBypass();
          const caller = (token ? authStore.getUserByToken(token) : null) ?? (bypass ? {role: 'admin'} : null);
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
              const legacyArray = Array.isArray(parsed);
              const items = legacyArray
                ? (parsed as unknown[])
                : (parsed as {dashboards?: unknown[]})?.dashboards;
              if (!Array.isArray(items) || items.length === 0) {
                sendJson(400, {detail: 'payload must be a non-empty dashboards array'});
                return;
              }
              // 分组列表：只接受字符串、去空、忽略大小写去重（与 src/utils/groups.ts 同规则）
              const rawGroups = legacyArray ? [] : (parsed as {groups?: unknown})?.groups;
              const groups = sanitizeGroupNames(rawGroups);
              // 分组英文标签：key 必须是现存分组，value 必须是非空字符串
              const rawLabels = legacyArray ? undefined : (parsed as {groupLabels?: unknown})?.groupLabels;
              const groupLabels = sanitizeGroupLabels(rawLabels, groups);
              const savedAt = new Date().toISOString();
              const payload = legacyArray
                ? items
                : {version: 2, savedAt, groups, groupLabels, dashboards: items};
              fs.writeFileSync(DEFAULT_FILE, JSON.stringify(payload, null, 2), 'utf-8');
              sendJson(200, {
                ok: true,
                count: items.length,
                groupCount: groups.length,
                savedAt,
                file: DEFAULT_FILE,
              });
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
      // Do not modify - file watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      // Disable file watching when DISABLE_HMR is true to save CPU during agent edits.
      // 忽略清单（每一项都有具体理由，不是照抄模板）：
      //  · log/        start.bat / stop.bat 与服务自身写的运行日志，不是前端源码；
      //                不忽略的话每写一行日志都会触发一次 HMR 整页刷新。
      //  · auth-data/  用户库（portal-auth.db + WAL/SHM + backups/）。用户管理每次
      //                增删改密都会写这里 —— 它是**被 SQLite 独占锁住的二进制文件**，
      //                让 watcher 去 watch 只有坏处：既会因锁冲突抛 EBUSY 直接打挂
      //                整个 dev server（2026-09-20 实测发生过），又会把每次保存变成
      //                一次无意义的整页刷新。数据库内容不需要热更新。
      //  · TMP/        测试脚本、截图、以及历次 CDP 测试留下的 Chrome user-data-dir。
      //                Chrome 会在自己的 profile 里频繁建/删/锁 .tmp 文件，watcher
      //                踩到就是同一个 EBUSY 崩溃（2026-09-20 实测：TMP/_chrome_compact
      //                下的 VariationsSeed*.tmp 把 9267 打挂，/uniplam/ 与
      //                /MsPortal/ 的用户管理接口一起 502）。TMP 里没有任何前端源码。
      //  · dist/       vite build 产物，只在部署时生成。
      watch:
        process.env.DISABLE_HMR === 'true'
          ? null
          : { ignored: ['**/log/**', '**/auth-data/**', '**/TMP/**', '**/dist/**'] },
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
