import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const backendProxyTarget = env.VITE_BACKEND_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
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
        },
      },
    },
  }
})
