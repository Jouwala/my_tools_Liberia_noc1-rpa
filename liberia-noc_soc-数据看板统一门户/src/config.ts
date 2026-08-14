// ============================================================================
// 全局环境配置（与 my_app 部署拓扑一致）
//  - FineBI 生产机：192.168.100.19，nginx 80 端口反代
//      /webroot/  → FineBI 决策平台
//  - Data Insight MVP (my_app)：192.168.100.20
//      /myapp/  → vite 7090（Data Insight MVP 前端，base=/myapp/）
//      /api/    → vite 7090 → uvicorn 7038（my_app 后端）
//  - 门户部署到同一台 nginx 时，API 走同源相对路径 /api/tasks 即可；
//    本地 dev（端口 3000）时通过 vite proxy 将 /api 转发到 my_app 主机。
// ============================================================================

/** my_app 后端 API 基址：优先环境变量，其次同源相对路径 */
export const MYAPP_API_BASE: string =
  (import.meta.env.VITE_MYAPP_API_BASE as string | undefined) || '';

/** my_app 任务列表接口（Task Manager 实时状态） */
export const MYAPP_TASKS_API = `${MYAPP_API_BASE}/api/tasks`;

/** FineBI 生产主机（FineBI 报表平台固定指向 .19） */
export const FINEBI_HOST = '192.168.100.19';

/** Data Insight MVP 主机（my_app 部署机） */
export const MYAPP_HOST = '192.168.100.20';

/** 默认主机（环境切换弹窗默认源地址，取 my_app 主机） */
export const DEFAULT_HOST = MYAPP_HOST;

/** Data Insight MVP 前端入口 */
export const MYAPP_HOME_URL = `http://${MYAPP_HOST}/myapp/`;

/** FineBI 决策平台入口 */
export const FINEBI_HOME_URL = `http://${FINEBI_HOST}/webroot/decision#/directory?activeTab=dec-tabs-homepage`;
