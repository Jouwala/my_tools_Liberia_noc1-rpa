import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// ---------------------------------------------------------------------------
// 页面级 chunk 名单：App.tsx 里所有 lazy(() => import('./pages/XXX')) 的页面名。
//
// 用途（下方 modulePreload.resolveDependencies）：动态 import 一个页面时，vite 会
// 把它的 **依赖闭包** 全部作为 <link rel=modulepreload> 一起下发。rolldown 会把
// 共享业务模块合并进「第一个引用它的页面 chunk」，于是某页面的闭包里可能混进
// **别的页面** 的入口 chunk（历史上 GISMap 的闭包里就挂着 ArchiveList / DataSync /
// WarehouseDashboard / SpReport / ComReport 等一长串）。结果：进一个页面要下载
// 一堆用不上的代码。这里按名单把「别的页面的入口 chunk」从 preload 列表里剔除。
//
// ⚠ 只剔除 preload（提前下载），**不改动模块图**：真正需要的静态依赖仍由浏览器
//   按 ESM 语义加载，不会缺模块；最坏情况只是少了一点提前量，不会白屏。
// ⚠ 名单从 App.tsx 现读，新增/改名页面无需维护第二份清单。
// ---------------------------------------------------------------------------
const PAGE_CHUNK_NAMES: Set<string> = (() => {
  const names = new Set<string>()
  try {
    const src = readFileSync(fileURLToPath(new URL('./src/App.tsx', import.meta.url)), 'utf8')
    const re = /lazy\(\(\)\s*=>\s*import\(['"]\.\/pages\/([^'"]+)['"]\)\)/g
    let m: RegExpExecArray | null
    while ((m = re.exec(src))) names.add(m[1].split('/')[0])
  } catch {
    // 读不到（如从别的目录构建）就退化成不过滤，不影响构建成功
  }
  return names
})()

/** `assets/GISMap-DJIQUQjl.js` -> `GISMap`；`assets/leaflet-vh-t_kPv.css` -> `leaflet-vh` */
const chunkBaseName = (f: string): string =>
  (f.split('/').pop() || '').replace(/-[A-Za-z0-9_-]{6,}\.(js|css)$/, '')

export default defineConfig({
  // 让前端资源从 /myapp/ 子路径加载，配合 nginx 的 location /myapp/ 反代
  base: '/myapp/',
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 7090,
    proxy: {
      '/api': {
        target: 'http://localhost:7038',
        changeOrigin: true,
      },
      // 经 nginx 的 /myapp/ 反代(不剥前缀)后，前端会以 /myapp/api 调接口
      '/myapp/api': {
        target: 'http://localhost:7038',
        changeOrigin: true,
      },
    },
  },
  // 生产模式（vite preview，托管 dist 构建产物）：
  // 浏览器加载压缩分包 JS（antd/echarts/leaflet/vendor），内存占用远低于 dev 模式，
  // 避免 vite dev server 直出未打包源码导致的浏览器标签页 Out of Memory 崩溃。
  // 注意：改前端源码后需先 `npm run build` 再 preview，否则页面停留在旧构建。
  preview: {
    host: '0.0.0.0',
    port: 7090,
    strictPort: true,
    // 隧道访问时 vite 按 Host 头拦外部域名（实测 403 "Blocked request. This host ... is not allowed"）。
    // 不要用 cloudflared --http-host-header localhost 绕过：nginx 的 proxy_cookie_domain 用 $host 改写
    // 门户 Cookie，Host 一旦变成 localhost，Cookie 就落到 Domain=localhost，eFlow/UME 登录直接失效。
    // 命名隧道上线后，把自己的域后缀也加进来，例如 '.example.com'。
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      '/api': {
        target: 'http://localhost:7038',
        changeOrigin: true,
      },
      '/myapp/api': {
        target: 'http://localhost:7038',
        changeOrigin: true,
      },
    },
  },
  build: {
    // 输出目录放在工作区监视树之外（my_app 的兄弟目录 _fe_dist）：
    // 本机 IDE（QoderCN/WorkBuddy）的文件监视器以「只读共享」持有 frontend/dist、
    // frontend/dist2 下 public 复制产物（alarm-management.html 等）的句柄，导致
    // vite 覆盖写 public->outDir 时 EPERM、构建失败；../_fe_dist 会被解析到 my_app 内，
    // 仍受监视，故用绝对路径放到 my_app 之上（D:/01_RPA/Task/_fe_dist）。preview 自动
    // 服务 build.outDir，URL（/myapp/）与用户无感。start.bat 用 `npm run preview` 读取此 outDir。
    // 远程开发机（非应用服务器，如 .27）构建时须设 FE_DIST_OUT 指向共享盘上的服务器 dist，
    // 例：FE_DIST_OUT=Y:/Task/_fe_dist vite build —— 否则绝对路径会落到本机 D 盘、服务器不更新。
    outDir: process.env.FE_DIST_OUT || 'D:/01_RPA/Task/_fe_dist',
    // 本机环境存在 safe-delete 钩子，会拦截 Vite 的 prepare-out-dir 清空动作导致构建中断。
    // 关闭自动清空，改由 `npm run prune:fe` 显式清理（旧 chunk 带 hash，覆盖写不影响正确性）。
    //
    // ⚠️ 2026-10-07 补记：上面这句话此前只写了「改由构建脚本/人工清理」，而 package.json
    // 的 build 里**从来没有这一步**、也没有对应脚本，于是产物只增不减 —— 实测 assets 积到
    // 14108 个文件 / 322.8 MB（单个 chunk 的陈旧副本多达 226 份）。已补 scripts/prune-fe-dist.mjs
    // 兑现该承诺：从 index.html 入口做**传递闭包**算出本次构建真正需要的文件，其余删除；
    // 默认干跑，加 --apply 才删。它不替代 emptyOutDir（本行仍需保持 false），只是收尾。
    emptyOutDir: false,
    // 提升单包体积告警阈值，避免 2.9MB 单包在构建日志刷红
    chunkSizeWarningLimit: 1200,
    // 2026-10-29 首屏提速：裁剪动态 import 的 preload 列表（见文件头 PAGE_CHUNK_NAMES
    // 注释）。只动 preload、不动模块图；入口 HTML（hostType=html）的依赖原样保留。
    modulePreload: {
      resolveDependencies(filename, deps, { hostType }) {
        if (hostType !== 'js') return deps
        const self = chunkBaseName(filename)
        const kept = deps.filter(d => {
          const base = chunkBaseName(d)
          const isOtherPage = base && PAGE_CHUNK_NAMES.has(base) && base !== self
          return !isOtherPage
        })
        if (kept.length !== deps.length) {
          console.log(`[modulePreload] ${filename}: ${deps.length} -> ${kept.length} (剔除 ${deps.length - kept.length})`)
        }
        return kept
      },
    },
    rollupOptions: {
      output: {
        // 【循环分包修复·勿删】rolldown 默认把 ESM/CJS 互操作 runtime helper 合并进
        // 第一个共享业务分包（src/api.ts → api-*.js），而 api 分包本身要 import vendor(axios)，
        // vendor → react-vendor → antd 又反过来从 api 分包 import 这些 helper，
        // 于是分包图出现环 antd ↔ api ↔ vendor。浏览器按深度优先执行时 antd 先跑，
        // 此时 api 分包的 helper 变量还没赋值（var 提升为 undefined），
        // 报 "Uncaught TypeError: t is not a function"（antd-*.js:1:52）→ 整站白屏。
        // strictExecutionOrder 会让 rolldown 把 runtime helper 单独拆成无依赖的
        // rolldown-runtime-*.js 叶子分包，并按 import 顺序注入初始化，分包图无环。
        // 代价约 +100KB(≈2%) 的初始化包装代码。可用
        // `node TMP/checkgraph.mjs <dist>` 校验产物分包图无环后再上线。
        strictExecutionOrder: true,
        // 按依赖拆分 vendor 分包：浏览器可并行下载 + 长缓存，首屏不必一次性拉全部
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return
          if (id.includes('echarts') || id.includes('zrender')) return 'echarts'
          if (id.includes('leaflet')) return 'leaflet'
          if (id.includes('@ant-design/icons')) return 'antd-icons'
          if (id.includes('/antd/') || id.includes('/rc-')) return 'antd'
          if (id.includes('react-dom') || id.includes('/react/') || id.includes('react')) return 'react-vendor'
          if (id.includes('dayjs') || id.includes('moment')) return 'date-lib'
          return 'vendor'
        },
      },
    },
  },
})
