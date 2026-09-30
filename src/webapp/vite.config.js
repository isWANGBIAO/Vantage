import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import connectionContract from './src/utils/backendConnection.cjs'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const backendProxyTarget = connectionContract.resolveBackendConnection({ env }).baseUrl

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
        '/api/v1': {
          target: backendProxyTarget,
          changeOrigin: true,
          secure: true,
        },
        '/static': {
          target: backendProxyTarget,
          changeOrigin: true,
          secure: true,
        },
      },
    },
  }
})
