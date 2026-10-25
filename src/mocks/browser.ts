import { setupWorker } from 'msw/browser'
import { handlers } from './handlers'

export async function startDemoWorker() {
  const worker = setupWorker(...handlers)
  await worker.start({ serviceWorker: { url: '/mockServiceWorker.js' }, onUnhandledFrame: 'bypass', quiet: true })
}
