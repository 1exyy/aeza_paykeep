type TelegramEvent = 'viewportChanged' | 'safeAreaChanged' | 'contentSafeAreaChanged'
type Insets = { top?: number; bottom?: number; left?: number; right?: number }
type TelegramBackButton = {
  show?: () => void
  hide?: () => void
  onClick?: (callback: () => void) => void
  offClick?: (callback: () => void) => void
}

type TelegramWebApp = {
  initData?: string
  ready?: () => void
  expand?: () => void
  isVersionAtLeast?: (version: string) => boolean
  onEvent?: (event: TelegramEvent, callback: () => void) => void
  offEvent?: (event: TelegramEvent, callback: () => void) => void
  viewportHeight?: number
  safeAreaInset?: Insets
  contentSafeAreaInset?: Insets
  BackButton?: TelegramBackButton
  openLink?: (url: string) => void
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp }
  }
}

export function getTelegramWebApp(): TelegramWebApp | undefined {
  return typeof window === 'undefined' ? undefined : window.Telegram?.WebApp
}

export function isTelegramLaunch(): boolean {
  // Контекст запуска не является подтверждением личности или роли.
  return Boolean(getTelegramWebApp()?.initData)
}

export function openExternalLink(url: string): boolean {
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return false
    const app = getTelegramWebApp()
    if (app?.initData && app.isVersionAtLeast?.('6.1') === true && app.openLink) app.openLink(parsed.href)
    else window.open(parsed.href, '_blank', 'noopener,noreferrer')
    return true
  } catch {
    return false
  }
}

export function bindTelegramBackButton(onBack: () => void): () => void {
  const app = getTelegramWebApp()
  const button = app?.BackButton
  if (!app?.initData || app.isVersionAtLeast?.('6.1') !== true ||
      !button?.show || !button.hide || !button.onClick || !button.offClick) return () => {}

  button.onClick(onBack)
  button.show()
  return () => {
    button.offClick?.(onBack)
    button.hide?.()
  }
}

const events: TelegramEvent[] = ['viewportChanged', 'safeAreaChanged', 'contentSafeAreaChanged']
const sides = ['top', 'bottom', 'left', 'right'] as const

function usableInset(value: number | undefined): number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : 0
}

export function initializeTelegramShell(): () => void {
  const app = getTelegramWebApp()
  if (!app?.initData) return () => {}

  const root = document.documentElement
  const updateGeometry = () => {
    for (const side of sides) {
      // Берём больший отступ: safeArea и contentSafeArea могут перекрывать друг друга.
      const inset = Math.max(usableInset(app.safeAreaInset?.[side]), usableInset(app.contentSafeAreaInset?.[side]))
      root.style.setProperty(`--app-safe-${side}`, `${inset}px`)
    }
    if (typeof app.viewportHeight === 'number' && Number.isFinite(app.viewportHeight) && app.viewportHeight > 0) {
      root.style.setProperty('--app-viewport-height', `${app.viewportHeight}px`)
    }
  }

  updateGeometry()
  app.ready?.()
  app.expand?.()

  const subscribed = app.onEvent && app.offEvent
    ? events.filter((event) => event === 'viewportChanged' || app.isVersionAtLeast?.('8.0') === true)
    : []
  for (const event of subscribed) app.onEvent?.(event, updateGeometry)

  return () => {
    for (const event of subscribed) app.offEvent?.(event, updateGeometry)
    for (const side of sides) root.style.removeProperty(`--app-safe-${side}`)
    root.style.removeProperty('--app-viewport-height')
  }
}
