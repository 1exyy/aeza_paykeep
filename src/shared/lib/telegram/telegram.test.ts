import { afterEach, expect, it, vi } from 'vitest'
import { bindTelegramBackButton, initializeTelegramShell, isTelegramLaunch } from './telegram'

afterEach(() => {
  window.Telegram = undefined
  for (const name of ['--app-safe-top', '--app-safe-bottom', '--app-safe-left', '--app-safe-right', '--app-viewport-height']) {
    document.documentElement.style.removeProperty(name)
  }
})

it('не выдаёт браузерный запуск за авторизованную среду Telegram', () => {
  const ready = vi.fn()
  window.Telegram = { WebApp: { initData: '', ready } }
  expect(isTelegramLaunch()).toBe(false)
  initializeTelegramShell()()
  expect(ready).not.toHaveBeenCalled()
})

it('обновляет геометрию и снимает подписки при размонтировании', () => {
  const callbacks = new Map<string, () => void>()
  const ready = vi.fn()
  const expand = vi.fn()
  const offEvent = vi.fn((event: string) => callbacks.delete(event))
  const app = {
    initData: 'контекст запуска для теста', ready, expand,
    viewportHeight: 600,
    safeAreaInset: { top: 20, bottom: 10 },
    contentSafeAreaInset: { top: 12, bottom: 15 },
    isVersionAtLeast: () => true,
    onEvent: (event: string, callback: () => void) => callbacks.set(event, callback),
    offEvent,
  }
  window.Telegram = { WebApp: app }

  const cleanup = initializeTelegramShell()
  expect(isTelegramLaunch()).toBe(true)
  expect(ready).toHaveBeenCalledOnce()
  expect(expand).toHaveBeenCalledOnce()
  expect(document.documentElement.style.getPropertyValue('--app-safe-top')).toBe('20px')
  expect(document.documentElement.style.getPropertyValue('--app-safe-bottom')).toBe('15px')
  expect(document.documentElement.style.getPropertyValue('--app-viewport-height')).toBe('600px')
  expect(callbacks.size).toBe(3)

  app.safeAreaInset.top = 24
  callbacks.get('safeAreaChanged')?.()
  expect(document.documentElement.style.getPropertyValue('--app-safe-top')).toBe('24px')

  cleanup()
  expect(offEvent).toHaveBeenCalledTimes(3)
  expect(callbacks.size).toBe(0)
  expect(document.documentElement.style.getPropertyValue('--app-safe-top')).toBe('')
})

it('показывает BackButton только в поддерживаемом Telegram и снимает обработчик', () => {
  const onBack = vi.fn()
  const show = vi.fn()
  const hide = vi.fn()
  const onClick = vi.fn()
  const offClick = vi.fn()
  window.Telegram = { WebApp: {
    initData: 'только тестовый контекст',
    isVersionAtLeast: (version) => version === '6.1',
    BackButton: { show, hide, onClick, offClick },
  } }

  const cleanup = bindTelegramBackButton(onBack)
  expect(onClick).toHaveBeenCalledWith(onBack)
  expect(show).toHaveBeenCalledOnce()
  cleanup()
  expect(offClick).toHaveBeenCalledWith(onBack)
  expect(hide).toHaveBeenCalledOnce()

  window.Telegram = { WebApp: { initData: '', BackButton: { show } } }
  bindTelegramBackButton(onBack)()
  expect(show).toHaveBeenCalledOnce()
})
