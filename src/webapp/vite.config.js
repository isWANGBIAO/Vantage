import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const backendProxyTarget = env.VITE_BACKEND_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
    base: './',
    plugins: [react()],
    build: {
      chunkSizeWarningLimit: 900,
      rollupOptions: {
        output: {
          manualChunks(id) {
            const pathId = id.replace(/\\/g, '/')

            if (
              pathId.includes('/node_modules/echarts/') ||
              pathId.includes('/node_modules/echarts-for-react/')
            ) {
              return 'charts-vendor'
            }

            if (
              pathId.includes('/node_modules/react-markdown/') ||
              pathId.includes('/node_modules/remark-gfm/') ||
              pathId.includes('/node_modules/mdast-util-') ||
              pathId.includes('/node_modules/micromark') ||
              pathId.includes('/node_modules/unified/') ||
              pathId.includes('/node_modules/remark-')
            ) {
              return 'markdown-vendor'
            }

            return undefined
          },
        },
      },
    },
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
