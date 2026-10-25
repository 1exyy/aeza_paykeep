const emailPattern = /^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$/
const hostPattern = /^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$/
const chatPattern = /^(-?\d{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$/

export function splitRecipients(value: string): string[] {
  return [...new Set(value.split(/[,;\s]+/).map((part) => part.trim()).filter(Boolean))]
}

export function chatIdError(value: string): string | undefined {
  return value.trim() && !chatPattern.test(value.trim()) ? 'Число (у групп и каналов начинается с -100) или @имя_канала' : undefined
}

export function hostError(value: string): string | undefined {
  return value.trim() && !hostPattern.test(value.trim()) ? 'Например, smtp-relay.brevo.com' : undefined
}

export function portError(value: string): string | undefined {
  const port = Number(value)
  return /^\d{1,5}$/.test(value.trim()) && port >= 1 && port <= 65535 ? undefined : 'Порт от 1 до 65535'
}

export function emailError(value: string): string | undefined {
  return value.trim() && !emailPattern.test(value.trim()) ? 'Например, billing@example.com' : undefined
}

export function recipientsError(value: string): string | undefined {
  const bad = splitRecipients(value).find((address) => !emailPattern.test(address))
  return bad ? `Некорректный адрес: ${bad}` : undefined
}

export function webhookUrlError(value: string): string | undefined {
  const text = value.trim()
  if (!text) return undefined
  try {
    return new URL(text).protocol === 'https:' ? undefined : 'Адрес должен начинаться с https://'
  } catch {
    return 'Укажите адрес вида https://example.com/hook'
  }
}
