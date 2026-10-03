// ============================================================================
// portal-default 处理器 —— dev（vite）与 prod（Express）共用的**唯一实现**
// ----------------------------------------------------------------------------
// 背景（2026-10-01 重构）：B1 把门户从 dev server 切到 Express 生产入口后，
// `vite.config.ts` 与 `server/index.ts` 各自复制了一份 portal-default 逻辑
// （sanitizeGroupNames / sanitizeGroupLabels / GET 鉴权门 / POST 落盘）。
// 两份实现的漂移风险很高（改一处忘另一处 → dev 与 prod 行为分叉）。
// 本模块把逻辑收敛到一处，两端都只做「挂载」，不再各写一份。
//
// 端点语义（与 2026-09-25 收口后的行为完全一致，属纯重构）：
//   GET  /api/portal-default  → 任何已登录用户可读；未登录 401；未保存 404
//   POST /api/portal-default  → 管理员 + 回环来源才可写；否则 401/403
//  其他方法 → 405
//
// 为什么签名用 node 原生 IncomingMessage/ServerResponse：
//   vite 的 connect 中间件与 Express 的 req/res 都是 node 原生的子类，
//   用原生类型即可同时满足两端，无需为框架各写一份适配。
// ============================================================================

import fs from 'node:fs';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { resolveCaller, sendJson, type AuthStoreType } from './auth';

/** 应用部署子路径（与 vite base、nginx /uniplam/ 反代一致） */
export const APP_BASE = '/uniplam/';

const LOOPBACK_ADDRESSES = new Set(['127.0.0.1', '::1', '::ffff:127.0.0.1']);

/**
 * 是否来自本机的保存请求（回环 IP + localhost/127.0.0.1 Host 头双重校验，端口不限）。
 * 「只有本机管理员能把当前目录保存为全局默认」这条约束靠它兜底。
 */
export function isLocalhostSaveRequest(req: {
  socket?: { remoteAddress?: string };
  headers: Record<string, string | string[] | undefined>;
}): boolean {
  const remote = req.socket?.remoteAddress || '';
  if (!LOOPBACK_ADDRESSES.has(remote)) return false;
  const host = String(req.headers.host || '').replace(/:\d+$/, '');
  return host === 'localhost' || host === '127.0.0.1';
}

/**
 * 组名归一化：去首尾/折叠空白、丢弃空值与「全部」伪分组、忽略大小写去重。
 * 与前端 `src/utils/groups.ts` 的 `sanitizeGroups` 同规则（这里保持独立实现，
 * 因为前端模块是 ESM/浏览器侧；两处规则必须一起改，已在 groups.test.ts 与
 * portalDefault.test.ts 各自锁死）。
 */
export function sanitizeGroupNames(raw: unknown): string[] {
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

/** 分组英文标签归一化：key 必须落在现存分组内，value 必须是非空字符串。 */
export function sanitizeGroupLabels(
  raw: unknown,
  groups: string[]
): Record<string, string> {
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

/** 解析 POST 载荷为落盘对象；非法/空返回 null（调用方回 400）。 */
export function parsePortalDefaultPayload(
  body: string,
  savedAt: string
): { payload: unknown; count: number; groupCount: number } | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return null;
  }
  const legacyArray = Array.isArray(parsed);
  const items = legacyArray
    ? (parsed as unknown[])
    : (parsed as { dashboards?: unknown[] })?.dashboards;
  if (!Array.isArray(items) || items.length === 0) return null;

  if (legacyArray) {
    return { payload: items, count: items.length, groupCount: 0 };
  }

  const groups = sanitizeGroupNames((parsed as { groups?: unknown })?.groups);
  const groupLabels = sanitizeGroupLabels(
    (parsed as { groupLabels?: unknown })?.groupLabels,
    groups
  );
  const payload = { version: 2, savedAt, groups, groupLabels, dashboards: items };
  return { payload, count: items.length, groupCount: groups.length };
}

/** 处理器依赖：鉴权存储 + 落盘文件路径。 */
export interface PortalDefaultDeps {
  authStore: AuthStoreType;
  defaultFile: string;
}

/**
 * 创建 portal-default 的 node 原生请求处理器。
 * 返回值可直接交给 `server.middlewares.use(path, handler)`（vite/connect）
 * 或 `app.use(path, handler)`（Express，req/res 为其子类）。
 */
export function createPortalDefaultHandler(
  deps: PortalDefaultDeps
): (req: IncomingMessage, res: ServerResponse) => void {
  const { authStore, defaultFile } = deps;

  return (req, res) => {
    const reply = (status: number, payload: unknown) => sendJson(res, status, payload);

    if (req.method === 'GET') {
      // 鉴权门（B3）：任何已登录用户可读；未登录一律 401。
      // 免登录开发模式下 resolveCaller 会按开发管理员放行，本机调试不受影响。
      const auth = resolveCaller(req, authStore);
      if (!auth) {
        reply(401, { detail: '请先登录后再读取默认目录' });
        return;
      }
      try {
        if (fs.existsSync(defaultFile)) {
          res.setHeader('Content-Type', 'application/json; charset=utf-8');
          res.end(fs.readFileSync(defaultFile, 'utf-8'));
        } else {
          reply(404, { detail: 'portal default catalog not saved yet' });
        }
      } catch (e) {
        reply(500, { detail: `read portal-default.json failed: ${String(e)}` });
      }
      return;
    }

    if (req.method === 'POST') {
      // 鉴权门：必须携带有效管理员会话；且仅回环来源可保存。
      const auth = resolveCaller(req, authStore);
      if (!auth) {
        reply(401, { detail: '请先登录后再保存默认目录' });
        return;
      }
      if (auth.caller.role !== 'admin') {
        reply(403, { detail: '仅管理员可保存默认目录' });
        return;
      }
      if (!isLocalhostSaveRequest(req)) {
        reply(403, { detail: '只有 http://localhost:9267/uniplam/ 允许保存默认目录' });
        return;
      }
      let body = '';
      req.on('data', (chunk: Buffer) => {
        body += chunk;
        // 防御超大请求体（目录 JSON 正常几百 KB 以内）
        if (body.length > 8 * 1024 * 1024) {
          req.destroy();
        }
      });
      req.on('end', () => {
        const savedAt = new Date().toISOString();
        const parsed = parsePortalDefaultPayload(body, savedAt);
        if (!parsed) {
          reply(400, { detail: 'payload must be a non-empty dashboards array' });
          return;
        }
        try {
          fs.writeFileSync(defaultFile, JSON.stringify(parsed.payload, null, 2), 'utf-8');
          reply(200, {
            ok: true,
            count: parsed.count,
            groupCount: parsed.groupCount,
            savedAt,
            file: defaultFile,
          });
        } catch (e) {
          reply(400, { detail: `invalid JSON payload: ${String(e)}` });
        }
      });
      return;
    }

    reply(405, { detail: 'method not allowed' });
  };
}
