import { useState, type ReactNode } from 'react'
import { getApiErrorCode, getSafeErrorMessage } from '@/shared/api'
import { Button, Field, Select } from '@/shared/ui'
import { useTestNotificationChannelMutation, useUpdateNotificationSettingsMutation } from '../api/settingsApi'
import type { NotificationSettings, NotificationSettingsPatch, SettingsChannel, SmtpSecurity } from '../api/settingsApi'
import { chatIdError, emailError, hostError, portError, recipientsError, splitRecipients, webhookUrlError } from '../model/validation'
import styles from './NotificationSettingsForms.module.css'

type Errors = Record<string, string | undefined>
const securityOptions: { value: SmtpSecurity; label: string }[] = [
  { value: 'starttls', label: 'STARTTLS (порты 587, 2525)' },
  { value: 'ssl', label: 'SSL/TLS (порт 465)' },
  { value: 'none', label: 'Без шифрования' },
]
const isSecurity = (value: string): value is SmtpSecurity => securityOptions.some((option) => option.value === value)

function useSave(settings: NotificationSettings) {
  const [update, { isLoading }] = useUpdateNotificationSettingsMutation()
  const [error, setError] = useState<string>()
  const [saved, setSaved] = useState(false)
  const save = async (patch: Omit<NotificationSettingsPatch, 'expected_version'>) => {
    setError(undefined)
    setSaved(false)
    if (Object.keys(patch).length === 0) return setSaved(true)
    try {
      await update({ ...patch, expected_version: settings.version }).unwrap()
      setSaved(true)
    } catch (requestError) {
      setError(getApiErrorCode(requestError) === 'version_conflict'
        ? 'Настройки уже изменили. Обновите страницу.'
        : getSafeErrorMessage(requestError, 'Не удалось сохранить настройки.'))
    }
  }
  return { save, isLoading, error, saved }
}

function Section({ title, enabled, channel, children, footer }: { title: string; enabled: boolean; channel: SettingsChannel; children: ReactNode; footer: ReactNode }) {
  const [test, { isLoading, data, error, reset }] = useTestNotificationChannelMutation()
  return <section className={styles.section} aria-labelledby={`settings-${channel}`}>
    <div className={styles.header}>
      <h2 id={`settings-${channel}`}>{title}</h2>
      <span className={enabled ? styles.on : styles.off}>{enabled ? 'Включён' : 'Выключен'}</span>
    </div>
    {children}
    <div className={styles.actions}>
      {footer}
      <Button type="button" variant="secondary" pending={isLoading} onClick={() => { reset(); void test(channel) }}>Проверить</Button>
    </div>
    {data && (data.ok
      ? <p className={styles.success} role="status">Тестовое сообщение отправлено.</p>
      : <p className={styles.error} role="alert">Не отправлено: {data.error}</p>)}
    {error && <p className={styles.error} role="alert">{getSafeErrorMessage(error, 'Не удалось выполнить проверку.')}</p>}
    <p className={styles.note}>«Проверить» отправляет тестовое сообщение с сохранёнными настройками.</p>
  </section>
}

function SaveState({ error, saved }: { error?: string; saved: boolean }) {
  if (error) return <p className={styles.error} role="alert">{error}</p>
  return saved ? <p className={styles.success} role="status">Сохранено.</p> : null
}

function TelegramForm({ settings }: { settings: NotificationSettings }) {
  const [chatId, setChatId] = useState(settings.telegram_chat_id)
  const [errors, setErrors] = useState<Errors>({})
  const { save, isLoading, error, saved } = useSave(settings)
  return <Section title="Telegram" enabled={settings.channels.telegram} channel="telegram" footer={<Button pending={isLoading} onClick={() => {
    const problem = chatIdError(chatId)
    setErrors({ chatId: problem })
    if (!problem) void save(chatId.trim() !== settings.telegram_chat_id ? { telegram_chat_id: chatId.trim() } : {})
  }}>Сохранить</Button>}>
    <p className={styles.note}>
      {settings.telegram_bot_configured
        ? `Бот${settings.telegram_bot_username ? ` @${settings.telegram_bot_username}` : ''} подключён. Добавьте его в группу или канал администратором и укажите ID чата.`
        : 'Токен бота не задан: его указывают в TELEGRAM_BOT_TOKEN в .env на сервере.'}
    </p>
    <Field label="ID группы или канала" placeholder="-1001234567890 или @my_channel" hint="Пусто — напоминания только в личные сообщения привязанным пользователям" value={chatId} onChange={(event) => setChatId(event.target.value)} error={errors.chatId} />
    <SaveState error={error} saved={saved} />
  </Section>
}

function EmailForm({ settings }: { settings: NotificationSettings }) {
  const [host, setHost] = useState(settings.smtp_host)
  const [port, setPort] = useState(String(settings.smtp_port))
  const [security, setSecurity] = useState<SmtpSecurity>(settings.smtp_security)
  const [user, setUser] = useState(settings.smtp_user)
  const [password, setPassword] = useState('')
  const [clearPassword, setClearPassword] = useState(false)
  const [from, setFrom] = useState(settings.smtp_from)
  const [recipients, setRecipients] = useState(settings.email_recipients.join(', '))
  const [errors, setErrors] = useState<Errors>({})
  const { save, isLoading, error, saved } = useSave(settings)

  const submit = () => {
    const next: Errors = { host: hostError(host), port: portError(port), from: emailError(from), recipients: recipientsError(recipients) }
    setErrors(next)
    if (Object.values(next).some(Boolean)) return
    const patch: Omit<NotificationSettingsPatch, 'expected_version'> = {}
    if (host.trim() !== settings.smtp_host) patch.smtp_host = host.trim()
    if (Number(port) !== settings.smtp_port) patch.smtp_port = Number(port)
    if (security !== settings.smtp_security) patch.smtp_security = security
    if (user.trim() !== settings.smtp_user) patch.smtp_user = user.trim()
    if (password) patch.smtp_password = password
    else if (clearPassword) patch.smtp_password = ''
    if (from.trim() !== settings.smtp_from) patch.smtp_from = from.trim()
    const list = splitRecipients(recipients)
    if (list.join(',') !== settings.email_recipients.join(',')) patch.email_recipients = list
    void save(patch)
  }

  return <Section title="Почта (SMTP)" enabled={settings.channels.email} channel="email" footer={<Button pending={isLoading} onClick={submit}>Сохранить</Button>}>
    <p className={styles.note}>Письмо-напоминание уходит всем получателям. Канал включается, когда указаны SMTP-сервер и хотя бы один получатель.</p>
    <div className={styles.row}>
      <Field label="SMTP-сервер" placeholder="smtp-relay.brevo.com" value={host} onChange={(event) => setHost(event.target.value)} error={errors.host} />
      <Field label="Порт" inputMode="numeric" value={port} onChange={(event) => setPort(event.target.value)} error={errors.port} />
    </div>
    <Select label="Шифрование" value={security} onValueChange={(value) => { if (isSecurity(value)) setSecurity(value) }} options={securityOptions} />
    <div className={styles.row}>
      <Field label="Логин" autoComplete="off" value={user} onChange={(event) => setUser(event.target.value)} />
      <div className={styles.secret}>
        <Field label="Пароль или SMTP-ключ" type="password" autoComplete="new-password" placeholder={settings.smtp_password_set && !clearPassword ? '•••••••• (задан)' : ''} hint={settings.smtp_password_set ? 'Оставьте пустым, чтобы не менять' : undefined} value={password} onChange={(event) => { setPassword(event.target.value); setClearPassword(false) }} />
        {settings.smtp_password_set && !password && <button type="button" className={styles.linkButton} onClick={() => setClearPassword(!clearPassword)}>{clearPassword ? 'Не удалять пароль' : 'Удалить пароль'}</button>}
      </div>
    </div>
    <Field label="Адрес отправителя" placeholder="billing@example.com" hint="Должен быть подтверждён у почтового сервиса" value={from} onChange={(event) => setFrom(event.target.value)} error={errors.from} />
    <Field label="Получатели" placeholder="admin@example.com, buh@example.com" hint="Через запятую" value={recipients} onChange={(event) => setRecipients(event.target.value)} error={errors.recipients} />
    <SaveState error={error} saved={saved} />
  </Section>
}

function WebhookForm({ settings }: { settings: NotificationSettings }) {
  const [url, setUrl] = useState(settings.webhook_url)
  const [secret, setSecret] = useState('')
  const [clearSecret, setClearSecret] = useState(false)
  const [errors, setErrors] = useState<Errors>({})
  const { save, isLoading, error, saved } = useSave(settings)

  const submit = () => {
    const problem = webhookUrlError(url)
    setErrors({ url: problem })
    if (problem) return
    const patch: Omit<NotificationSettingsPatch, 'expected_version'> = {}
    if (url.trim() !== settings.webhook_url) patch.webhook_url = url.trim()
    if (secret) patch.webhook_secret = secret
    else if (clearSecret) patch.webhook_secret = ''
    void save(patch)
  }

  return <Section title="Webhook" enabled={settings.channels.webhook} channel="webhook" footer={<Button pending={isLoading} onClick={submit}>Сохранить</Button>}>
    <p className={styles.note}>POST с JSON о напоминаниях, оплате и отмене оплаты, создании и прекращении платежа. Подпись — заголовок X-InvoiceKeeper-Signature: sha256=HMAC-SHA256 тела с секретом.</p>
    <Field label="Адрес" placeholder="https://example.com/hook" value={url} onChange={(event) => setUrl(event.target.value)} error={errors.url} />
    <div className={styles.secret}>
      <Field label="Секрет для подписи" type="password" autoComplete="new-password" placeholder={settings.webhook_secret_set && !clearSecret ? '•••••••• (задан)' : ''} hint={settings.webhook_secret_set ? 'Оставьте пустым, чтобы не менять' : 'Любая длинная случайная строка'} value={secret} onChange={(event) => { setSecret(event.target.value); setClearSecret(false) }} />
      {settings.webhook_secret_set && !secret && <button type="button" className={styles.linkButton} onClick={() => setClearSecret(!clearSecret)}>{clearSecret ? 'Не удалять секрет' : 'Удалить секрет'}</button>}
    </div>
    <SaveState error={error} saved={saved} />
  </Section>
}

/** Admin settings of the notification channels. */
export function NotificationSettingsForms({ settings }: { settings: NotificationSettings }) {
  return <div className={styles.sections}>
    <TelegramForm settings={settings} />
    <EmailForm settings={settings} />
    <WebhookForm settings={settings} />
  </div>
}
