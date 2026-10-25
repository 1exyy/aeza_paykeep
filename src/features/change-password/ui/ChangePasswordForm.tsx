import { useState, type FormEvent } from 'react'
import { useBeginTotpMutation, useChangePasswordMutation, useConfirmTotpMutation, useGetMeQuery, type TotpSetup } from '@/entities/session'
import { getSafeErrorMessage } from '@/shared/api'
import { Button, Field } from '@/shared/ui'
import styles from './ChangePasswordForm.module.css'

type Errors = Partial<Record<'current' | 'next' | 'repeat' | 'totp', string>>

function TotpEnrollment() {
  const [begin, { isLoading: isBeginning }] = useBeginTotpMutation()
  const [confirm, { isLoading: isConfirming }] = useConfirmTotpMutation()
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [setup, setSetup] = useState<TotpSetup>()
  const [error, setError] = useState<string>()
  const start = async (event: FormEvent) => {
    event.preventDefault()
    setError(undefined)
    try {
      setSetup(await begin(password).unwrap())
      setPassword('')
    } catch (requestError) {
      setError(getSafeErrorMessage(requestError, 'Не удалось начать привязку.'))
    }
  }
  const finish = async (event: FormEvent) => {
    event.preventDefault()
    setError(undefined)
    try {
      await confirm(code).unwrap()
      setSetup(undefined)
      setCode('')
    } catch (requestError) {
      setError(getSafeErrorMessage(requestError, 'Неверный код или время привязки истекло.'))
    }
  }
  return <div className={styles.form}>
    <h3>Подключите двухфакторную защиту</h3>
    <p>Администратор может сменить пароль только после привязки приложения-аутентификатора.</p>
    {!setup ? <form className={styles.form} onSubmit={(event) => void start(event)}>
      <Field label="Текущий пароль" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
      <Button type="submit" pending={isBeginning} disabled={!password}>Начать привязку</Button>
    </form> : <form className={styles.form} onSubmit={(event) => void finish(event)}>
      <p>Добавьте запись в Google Authenticator, Microsoft Authenticator или другое приложение TOTP. Введите ключ вручную:</p>
      <code className={styles.secret}>{setup.secret}</code>
      <a href={setup.otpauth_uri}>Открыть в приложении-аутентификаторе</a>
      <p>Затем введите шестизначный код. Привязка действует 10 минут.</p>
      {import.meta.env.DEV && import.meta.env.VITE_MOCK_API === 'true' && <p>В демо используйте код 123456.</p>}
      <Field label="Код подтверждения" type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={6} required value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))} />
      <Button type="submit" pending={isConfirming} disabled={!/^\d{6}$/.test(code)}>Подтвердить привязку</Button>
      <Button type="button" variant="secondary" onClick={() => { setSetup(undefined); setCode(''); setError(undefined) }}>Начать заново</Button>
    </form>}
    {error && <p className={styles.error} role="alert">{error}</p>}
  </div>
}

/** Replaces a temporary password (or any password) with the user's own. */
export function ChangePasswordForm({ onChanged }: { onChanged?: () => void }) {
  const { data: user } = useGetMeQuery()
  const [change, { isLoading }] = useChangePasswordMutation()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [errors, setErrors] = useState<Errors>({})
  const [submitError, setSubmitError] = useState<string>()

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitError(undefined)
    const found: Errors = {
      current: current ? undefined : 'Введите текущий пароль',
      next: next.length < 8 || next.length > 128 ? 'Пароль: от 8 до 128 символов' : next === current ? 'Новый пароль должен отличаться от текущего' : undefined,
      repeat: repeat !== next ? 'Пароли не совпадают' : undefined,
      totp: user?.role === 'admin' && !/^\d{6}$/.test(totpCode) ? 'Введите шестизначный код' : undefined,
    }
    setErrors(found)
    if (Object.values(found).some(Boolean)) return
    try {
      await change({ current_password: current, new_password: next, ...(user?.role === 'admin' ? { totp_code: totpCode } : {}) }).unwrap()
      onChanged?.()
    } catch (requestError) {
      setSubmitError(getSafeErrorMessage(requestError, 'Не удалось сменить пароль. Попробуйте ещё раз.'))
    }
  }

  if (user?.role === 'admin' && !user.totp_enabled) return <TotpEnrollment />

  return <form className={styles.form} onSubmit={(event) => void submit(event)} noValidate>
    <Field label="Текущий пароль" type="password" autoComplete="current-password" required value={current} onChange={(event) => setCurrent(event.target.value)} error={errors.current} />
    <Field label="Новый пароль" type="password" autoComplete="new-password" required hint="От 8 до 128 символов" value={next} onChange={(event) => setNext(event.target.value)} error={errors.next} />
    <Field label="Повторите новый пароль" type="password" autoComplete="new-password" required value={repeat} onChange={(event) => setRepeat(event.target.value)} error={errors.repeat} />
    {user?.role === 'admin' && <Field label="Код из приложения-аутентификатора" type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={6} required value={totpCode} onChange={(event) => setTotpCode(event.target.value.replace(/\D/g, ''))} error={errors.totp} />}
    {submitError && <p className={styles.error} role="alert">{submitError}</p>}
    <Button type="submit" pending={isLoading}>Сменить пароль</Button>
  </form>
}
