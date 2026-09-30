import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import connectionContract from './src/utils/backendConnection.cjs'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const canonicalConnection = env.VANTAGE_BACKEND_URL || env.VANTAGE_BACKEND_HOST || env.VANTAGE_BACKEND_PORT
  const backendProxyTarget = connectionContract.resolveBackendConnection({
    env,
    baseUrl: canonicalConnection ? undefined : env.VITE_BACKEND_PROXY_TARGET || env.VITE_BACKEND_BASE_URL,
  }).baseUrl

  return {
    base: './',
    plugins: [react()],
    define: {
      // Canonical connection settings configure the same-origin proxy and must
      // not be overridden by a stale legacy renderer URL from a .env file.
      'import.meta.env.VITE_BACKEND_BASE_URL': JSON.stringify(canonicalConnection ? '' : env.VITE_BACKEND_BASE_URL || ''),
    },
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
