const DATE_ONLY = /^\d{4}-(0[1-9]|1[0-2])-([0-2]\d|3[01])$/

export function isDateOnly(value: string): boolean {
  if (!DATE_ONLY.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year!, month! - 1, day))
  return date.getUTCFullYear() === year && date.getUTCMonth() === month! - 1 && date.getUTCDate() === day
}

export function formatDateOnly(value: string): string {
  if (!isDateOnly(value)) throw new Error('Некорректная календарная дата')
  const [year, month, day] = value.split('-')
  return `${day}.${month}.${year}`
}

export function shiftDateOnly(value: string, days: number): string {
  if (!isDateOnly(value) || !Number.isSafeInteger(days)) throw new Error('Некорректная календарная дата')
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year!, month! - 1, day! + days))
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}-${String(date.getUTCDate()).padStart(2, '0')}`
}
