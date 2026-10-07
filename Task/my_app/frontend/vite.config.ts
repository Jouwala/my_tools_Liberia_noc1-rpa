import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

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
