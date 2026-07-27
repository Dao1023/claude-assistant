import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 开发模式把 /api 代理到 FastAPI(端口 5174)
      '/api': {
        target: 'http://127.0.0.1:5174',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
