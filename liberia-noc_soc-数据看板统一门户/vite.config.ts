import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig, type Plugin} from 'vite';
import {getAuthStore, portalAuthPlugin} from './server/auth';
import {APP_BASE, createPortalDefaultHandler} from './server/portalDefault';

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

// 应用部署子路径 APP_BASE 由 server/portalDefault.ts 导出（dev 与 prod 共用一个定义）。

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

/**
 * portal-default 插件的 vite 适配层。
 * 真正的 GET/POST 逻辑（含 B3 鉴权门）已收敛到 `server/portalDefault.ts`，
 * 与生产入口 `server/index.ts` 共用同一份实现，这里只负责挂载，不再各写一份。
 */
function portalDefaultStorePlugin(): Plugin {
  return {
    name: 'portal-default-store',
    configureServer(server) {
      const handler = createPortalDefaultHandler({ authStore, defaultFile: DEFAULT_FILE });

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
      //  · portal-default.json  门户目录的运行时数据：管理员在页面上点一次"保存为默认"
      //                就写一次，写一次就让所有在线客户端整页刷新一次。它不在模块图里，
      //                src 里是 fetch('/api/portal-default') 取的（见 src/App.tsx），
      //                不是 import，所以不需要热更新。
      //  · MsPortal/  OlrPortal/  olbrportal/   三个静态壳（HTML + 手写 JS），线上由
      //                nginx 直接发静态文件，src/ 里没有任何地方 import 它们。但 root
      //                覆盖了它们，于是每次改动都会让 /uniplam/ 整页刷新：2026-09-21 查
      //                "页面变慢"时，log\portal_dev.log 里刷满了
      //                "page reload MsPortal/assets/*.js" / "page reload MsPortal/_qc*.txt"
      //                ——那些 _qc*.txt 是 QC 脚本在写（MsPortal 下此类临时文件有 160 个
      //                以上），不是人在编辑器里改。代价：不再有"改 MsPortal 资源 → 浏览器
      //                自动刷新"这个便利（它本来也没有 HMR 客户端，靠的就是整页刷新）。
      //  · scripts/  *.py  *.ps1   后端与运维脚本（my_app 迁移脚本、whatsapp 分析服务、
      //                start/stop 脚本），都不在前端模块图里。
      //  · *.bak*  *.xlsx  备份件与数据导出（vite.config.ts_bak_*、portal-default.json.bak_*、
      //                看板清单 xlsx …）。
      //  · _*  .tmp_*  tmp_*.txt  temp_*.txt  seg*.txt  listing.txt  out.txt
      //                仓库根目录与各处的临时件（除下方豁免的模板文件外，其余集中
      //                在 MsPortal/ 里）。
      //  · 豁免：src/_* 与 server/_* 是**真源码**（如 src/pages/_TemplatePage.tsx
      //                新增页面模板），必须参与 HMR，否则改模板看不到效果。
      //                与 .gitignore 的 `!src/_*` / `!server/_*` 是一对，改一个必须改另一个。
      //                注意 vite 的 `ignored` 是 glob 匹配、**不支持 `!` 反选**，
      //                所以这里不能照抄 .gitignore 的写法，只能在 `**/_*` 的位置
      //                直接不写那么宽的规则 —— 故改成逐前缀列举，把源码目录排除在外。
      watch:
        process.env.DISABLE_HMR === 'true'
          ? null
          : {
              ignored: [
                '**/log/**',
                '**/auth-data/**',
                '**/TMP/**',
                '**/dist/**',
                '**/portal-default.json',
                '**/MsPortal/**',
                '**/OlrPortal/**',
                '**/olbrportal/**',
                //  v3/team_portal/ 与 v3/olbrportal/ 同理：手写静态壳，nginx 直接
                //  alias 发它，src/ 里没有 import 它。漏在 watch 清单外的后果是
                //  每次改团队门户的 olbr.js 都会让 /uniplam/ 整页刷新一次
                //  （与 2026-09-21 记录的 MsPortal 同款现象）。
                '**/team_portal/**',
                '**/scripts/**',
                '**/*.py',
                '**/*.ps1',
                '**/*.bak',
                '**/*.bak_*',
                '**/*_bak_*',
                // 快照命名的另外三种写法（`.bak-qc` / `.bak.qc` / `.qcbak`）实测都存在，
                // 漏在这里的后果不是入库而是**每次 QC 改 portal.js 就整页刷新一次**。
                // 与 .gitignore 的同名规则是一对，改一个必须改另一个。
                '**/*.bak-*',
                '**/*.bak.*',
                '**/*bak',
                '**/*.xlsx',
                // 下划线前缀的一次性件：只忽略它们**实际所在**的目录，
                // 不用 `**/_*` —— 那会连同 src/pages/_TemplatePage.tsx 一起忽略掉
                // （vite 的 ignored 不支持 `!` 反选，宽规则没法再捞回来）。
                // 与 .gitignore 的 `_*` + `!src/_*` + `!server/_*` 语义对齐。
                '_*',
                'MsPortal/_*',
                'MsPortal/**/_*',
                'TMP/_*',
                '.tmp_*',
                '**/tmp_*.txt',
                '**/temp_*.txt',
                '**/seg*.txt',
                '**/listing.txt',
                '**/out.txt',
                '**/*.tmp',
                '**/*.old',
              ],
            },
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
