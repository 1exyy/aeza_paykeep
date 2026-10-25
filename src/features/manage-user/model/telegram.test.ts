import { describe, expect, it } from 'vitest'
import { telegramError, telegramLabel } from './telegram'

describe('telegram field', () => {
  it('accepts username, id and empty', () => {
    expect(telegramError('@anna_tg')).toBeUndefined()
    expect(telegramError('anna_tg')).toBeUndefined()
    expect(telegramError('123456789')).toBeUndefined()
    expect(telegramError('')).toBeUndefined()
    expect(telegramError('@ab')).toBeTypeOf('string')
  })

  it('describes the link state', () => {
    expect(telegramLabel({ telegram_linked: false, telegram_username: 'anna_tg' })).toBe('@anna_tg — ждём /start в боте')
    expect(telegramLabel({ telegram_linked: true, telegram_username: 'anna_tg', telegram_user_id: 1 })).toBe('@anna_tg — привязан')
    expect(telegramLabel({ telegram_linked: false })).toBe('не указан')
  })
})
