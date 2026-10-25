/** Client check of the admin Telegram field; the server normalizes it again. */
export function telegramError(value: string): string | undefined {
  const text = value.trim()
  if (!text || /^\d{1,19}$/.test(text)) return undefined
  return /^@?[a-zA-Z][a-zA-Z0-9_]{4,31}$/.test(text) ? undefined : 'Укажите @username (5–32 символа: латиница, цифры, _) или числовой ID'
}

export function telegramLabel(user: { telegram_linked: boolean; telegram_username?: string | null; telegram_user_id?: number | null }): string {
  if (user.telegram_username && user.telegram_linked) return `@${user.telegram_username} — привязан`
  if (user.telegram_username) return `@${user.telegram_username} — ждём /start в боте`
  if (user.telegram_linked) return user.telegram_user_id ? `ID ${user.telegram_user_id} — привязан` : 'привязан'
  return 'не указан'
}
