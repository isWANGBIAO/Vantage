import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backendProxyTarget = process.env.VITE_BACKEND_PROXY_TARGET || 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: backendProxyTarget,
        changeOrigin: true,
        secure: false,
      },
      '/static': {
        target: backendProxyTarget,
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
