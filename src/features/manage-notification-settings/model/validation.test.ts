import { describe, expect, it } from 'vitest'
import { chatIdError, hostError, portError, recipientsError, splitRecipients, webhookUrlError } from './validation'

describe('notification settings validation', () => {
  it('splits and deduplicates recipients', () => {
    expect(splitRecipients('a@example.com, b@example.com;a@example.com\nc@example.com')).toEqual(['a@example.com', 'b@example.com', 'c@example.com'])
    expect(recipientsError('a@example.com, nope')).toBe('Некорректный адрес: nope')
  })

  it('checks chat id, host, port and webhook url', () => {
    expect(chatIdError('-1004331177965')).toBeUndefined()
    expect(chatIdError('@my_channel')).toBeUndefined()
    expect(chatIdError('chat')).toBeTypeOf('string')
    expect(hostError('smtp-relay.brevo.com')).toBeUndefined()
    expect(hostError('bad host')).toBeTypeOf('string')
    expect(portError('2525')).toBeUndefined()
    expect(portError('0')).toBeTypeOf('string')
    expect(webhookUrlError('https://example.com/hook')).toBeUndefined()
    expect(webhookUrlError('http://example.com/hook')).toBeTypeOf('string')
  })
})
