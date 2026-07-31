import { fileURLToPath, URL } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// PhotoRestore 前端：Vite + React + vitest（jsdom）
// 开发端口 5175，/api 代理到后端 8030（与 CI/后端端口约定一致）
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5175,
    proxy: {
      '/api': 'http://127.0.0.1:8030',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    include: ['src/**/*.spec.js', 'src/**/*.spec.jsx'],
  },
})
