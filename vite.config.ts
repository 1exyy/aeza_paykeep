import { fileURLToPath, URL } from 'node:url'
import { readFile } from 'node:fs/promises'
import { defineConfig, loadEnv } from 'vite'
import type { Plugin } from 'vite'
import react from '@vitejs/plugin-react'

function demoWorkerPlugin(): Plugin {
  const workerPath = fileURLToPath(new URL('./node_modules/msw/lib/mockServiceWorker.js', import.meta.url))
  return {
    name: 'demo-msw-worker',
    configureServer(server) {
      server.middlewares.use('/mockServiceWorker.js', async (_request, response, next) => {
        try {
          response.setHeader('Content-Type', 'application/javascript; charset=utf-8')
          response.setHeader('Cache-Control', 'no-store')
          response.end(await readFile(workerPath))
        } catch (error) {
          next(error)
        }
      })
    },
  }
}

export default defineConfig(({ command, mode }) => {
  const { DEV_API_PROXY_TARGET, VITE_MOCK_API } = loadEnv(mode, process.cwd(), '')
  const demoMode = command === 'serve' && VITE_MOCK_API === 'true'
  if (demoMode && DEV_API_PROXY_TARGET) throw new Error('Demo MSW и DEV_API_PROXY_TARGET нельзя использовать одновременно')

  return {
    plugins: [react(), ...(demoMode ? [demoWorkerPlugin()] : [])],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: command === 'serve' && DEV_API_PROXY_TARGET
      ? { proxy: { '/api': { target: DEV_API_PROXY_TARGET, changeOrigin: true } } }
      : undefined,
  }
})
