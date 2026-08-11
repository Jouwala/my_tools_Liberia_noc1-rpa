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
    // 本机环境存在 safe-delete 钩子，会拦截 Vite 的 prepare-out-dir 清空动作导致构建中断。
    // 关闭自动清空，改由构建脚本/人工清理 dist/assets（旧 chunk 带 hash，覆盖写不影响正确性）。
    emptyOutDir: false,
    // 提升单包体积告警阈值，避免 2.9MB 单包在构建日志刷红
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
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
