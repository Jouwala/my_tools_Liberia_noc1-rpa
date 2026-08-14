import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

export default defineConfig(() => {
  return {
    // 门户通过 nginx 子路径 /uniplam/ 访问，构建产物的资源引用必须带此前缀，
    // 否则 dist 中 src="/assets/..." 在 nginx 反代时会去根路径找 JS/CSS 导致 404。
    base: '/uniplam/',
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modifyâfile watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      // Disable file watching when DISABLE_HMR is true to save CPU during agent edits.
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
      // 本地 dev 时将 /api 代理到 my_app 后端主机（与 nginx /api/ → my_app 后端 7038 拓扑一致），
      // 供 TaskSyncWidget 实时拉取 /api/tasks。
      proxy: {
        '/api': {
          target: 'http://192.168.100.20',
          changeOrigin: true,
        },
      },
    },
  };
});
