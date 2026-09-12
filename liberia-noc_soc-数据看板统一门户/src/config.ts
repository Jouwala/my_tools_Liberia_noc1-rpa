// ============================================================================
// 全局环境配置（与 my_app 部署拓扑一致）—— 单一真相源
// ----------------------------------------------------------------------------
// 设计目标：所有"主机/域名"只在此处定义一处，远程 IP 变更时只需改这里（或页面上
// 的「环境配置」弹窗）即可全站生效。每条看板只存"相对路径 rel"，运行时由
// 主机 + rel 拼出完整 URL，因此已持久化到 localStorage 的旧数据也能自动跟随。
//
// 部署拓扑：
//  - FineBI 生产机：192.168.100.19，nginx 80 端口反代
//      /webroot/  → FineBI 决策平台
//  - Data Insight MVP (my_app)：192.168.100.20
//      /myapp/  → vite 7090（Data Insight MVP 前端，base=/myapp/）
//      /api/    → vite 7090 → uvicorn 7038（my_app 后端）
//  - 门户部署到同一台 nginx 时，API 走同源相对路径 /api/tasks 即可；
//    本地 dev（端口 3000）时通过 vite proxy 将 /api 转发到 my_app 主机。
//
// 优先级：localStorage 覆盖  >  VITE_* 环境变量  >  下方硬编码兜底
// ============================================================================

import type { DashboardItem, PlatformType } from './types/dashboard';

// ============================================================================
// 门户「自身」后端 API 前缀（/api/auth/*、/api/portal-default）
// ----------------------------------------------------------------------------
// 必须带应用 base 前缀（/uniplam/api），不能再用绝对路径 /api：
//  门户页面挂在 nginx 的 /uniplam/ 子路径下，前端若请求 /api/auth/login，
//  会命中 nginx 的通用 `location /api/` → my_app 后端 7038；7038 上 GET
//  /api/auth/login 是 SPA 兜底静态页（仅允许 GET），POST 就被回成
//  「405 Method Not Allowed」——这正是其他电脑（走 80 端口 nginx）登录失败的原因。
//  带上 base 前缀后，请求路径 /uniplam/api/... 天然落在 `location /uniplam/`
//  （→ 9267 门户自身服务）里，与 my_app 的 /api/ 彻底不冲突。
// 本地直连 http://localhost:9267/uniplam/ 同样走这个前缀，行为一致。
// ============================================================================
export const PORTAL_API = `${(import.meta.env.BASE_URL || '/').replace(/\/+$/, '')}/api`;

/** 端点配置：仅主机/域名与 API 基址，路径随各看板 rel 携带 */
export interface EnvConfig {
  /** FineBI 决策平台主机（如 192.168.100.19） */
  finebiHost: string;
  /** Data Insight MVP (my_app) 主机（如 192.168.100.20） */
  myappHost: string;
  /** my_app 后端 API 基址：留空=同源（/api/...），跨域时填 http://192.168.100.20 */
  myappApiBase: string;
}

const ENV_STORAGE_KEY = 'noc_portal_env';

/** 硬编码兜底（与历史部署一致） */
const FALLBACK_ENV: EnvConfig = {
  finebiHost: '192.168.100.19',
  myappHost: '192.168.100.20',
  myappApiBase: '',
};

/** 由 VITE_* 环境变量得到的默认值（环境变量缺失时回退到硬编码） */
function defaultEnv(): EnvConfig {
  return {
    finebiHost:
      (import.meta.env.VITE_FINEBI_HOST as string | undefined) || FALLBACK_ENV.finebiHost,
    myappHost:
      (import.meta.env.VITE_MYAPP_HOST as string | undefined) || FALLBACK_ENV.myappHost,
    myappApiBase:
      (import.meta.env.VITE_MYAPP_API_BASE as string | undefined) || FALLBACK_ENV.myappApiBase,
  };
}

// —— 运行时单例（可被页面「环境配置」弹窗改写）——
let currentEnv: EnvConfig = loadEnvConfig();

function loadEnvConfig(): EnvConfig {
  try {
    const raw = localStorage.getItem(ENV_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<EnvConfig>;
      return { ...defaultEnv(), ...parsed };
    }
  } catch (e) {
    console.error('[config] 解析环境配置失败，使用默认配置', e);
  }
  return defaultEnv();
}

/** 读取当前生效的配置副本 */
export function getEnvConfig(): EnvConfig {
  return { ...currentEnv };
}

/** 保存配置到 localStorage 并刷新运行时单例 */
export function saveEnvConfig(cfg: EnvConfig): void {
  currentEnv = {
    finebiHost: (cfg.finebiHost || FALLBACK_ENV.finebiHost).trim(),
    myappHost: (cfg.myappHost || FALLBACK_ENV.myappHost).trim(),
    myappApiBase: (cfg.myappApiBase || '').trim(),
  };
  try {
    localStorage.setItem(ENV_STORAGE_KEY, JSON.stringify(currentEnv));
  } catch (e) {
    console.error('[config] 保存环境配置失败', e);
  }
}

/** 恢复为默认（清除 localStorage 覆盖） */
export function resetEnvConfig(): EnvConfig {
  currentEnv = defaultEnv();
  try {
    localStorage.removeItem(ENV_STORAGE_KEY);
  } catch (e) {
    console.error('[config] 清除环境配置失败', e);
  }
  return { ...currentEnv };
}

// ============================================================================
// 派生地址（始终读取最新 currentEnv）
// ============================================================================

export function getFinebiHost(): string {
  return currentEnv.finebiHost;
}

export function getMyappHost(): string {
  return currentEnv.myappHost;
}

/** FineBI 决策平台入口 */
export function getFinebiHomeUrl(): string {
  return `http://${currentEnv.finebiHost}/webroot/decision#/directory?activeTab=dec-tabs-homepage`;
}

/** Data Insight MVP 前端入口 */
export function getMyappHomeUrl(): string {
  return `http://${currentEnv.myappHost}/myapp/`;
}

/**
 * 拼 my_app 深链（含门户鉴权 token）：`?page=<pageKey>[&t=token][#hash]`。
 * token 取自 uniplam 门户登录态（localStorage liberia_noc_auth_v1），my_app 前端
 * 会用 ?t= 换自己的会话 Cookie 并随即从地址栏抽走。未登录（无 token）则不加 t，
 * 保持原链接 —— my_app 会返回 401 引导登录。彩窗/深链统一走这里，勿直接拼字符串。
 */
export function getMyappLink(pageKey: string, hash = ''): string {
  const token = localStorage.getItem('liberia_noc_auth_v1');
  const tokenParam = token ? `&t=${encodeURIComponent(token)}` : '';
  return `${getMyappHomeUrl()}?page=${pageKey}${tokenParam}${hash ? '#' + hash : ''}`;
}

/** my_app 任务列表接口（Task Manager 实时状态） */
export function getMyappTasksApi(): string {
  return `${currentEnv.myappApiBase || ''}/api/tasks`;
}

// ============================================================================
// 看板 URL 解析（统一由全局主机配置驱动）
// ============================================================================

/**
 * 从完整 URL 提取"相对路径 rel"：去掉 http(s)://host 前缀，保留 path+query+hash。
 * 用于：旧数据迁移、手动编辑看板时自动抽取可跟随主机变化的相对路径。
 */
export function buildRel(platform: PlatformType, url: string): string | undefined {
  if (platform === 'external') return undefined;
  return url.replace(/^https?:\/\/[^/]+/, '');
}

/**
 * 解析看板真实访问地址：
 *  - 带 rel 且非外部平台：用全局主机 + rel 实时拼出（改 IP 即时生效）
 *  - 否则退回 item.url（兼容纯外部大屏 / 历史兜底）
 */
export function resolveUrl(item: DashboardItem): string {
  if (item.rel && item.platform !== 'external') {
    const host = item.platform === 'finebi' ? currentEnv.finebiHost : currentEnv.myappHost;
    const base = `http://${host}${item.rel}`;
    if (item.platform !== 'finebi') {
      const token = localStorage.getItem('liberia_noc_auth_v1');
      if (token) {
        return `${base}${base.includes('?') ? '&' : '?'}t=${encodeURIComponent(token)}`;
      }
    }
    return base;
  }
  return item.url;
}
