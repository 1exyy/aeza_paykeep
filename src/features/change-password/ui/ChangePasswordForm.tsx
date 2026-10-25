import { useState, type FormEvent } from 'react'
import { useChangePasswordMutation } from '@/entities/session'
import { getSafeErrorMessage } from '@/shared/api'
import { Button, Field } from '@/shared/ui'
import styles from './ChangePasswordForm.module.css'

type Errors = Partial<Record<'current' | 'next' | 'repeat', string>>

/** Replaces a temporary password (or any password) with the user's own. */
export function ChangePasswordForm({ onChanged }: { onChanged?: () => void }) {
  const [change, { isLoading }] = useChangePasswordMutation()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [errors, setErrors] = useState<Errors>({})
  const [submitError, setSubmitError] = useState<string>()

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitError(undefined)
    const found: Errors = {
      current: current ? undefined : 'Введите текущий пароль',
      next: next.length < 8 || next.length > 128 ? 'Пароль: от 8 до 128 символов' : next === current ? 'Новый пароль должен отличаться от текущего' : undefined,
      repeat: repeat !== next ? 'Пароли не совпадают' : undefined,
    }
    setErrors(found)
    if (Object.values(found).some(Boolean)) return
    try {
      await change({ current_password: current, new_password: next }).unwrap()
      onChanged?.()
    } catch (requestError) {
      setSubmitError(getSafeErrorMessage(requestError, 'Не удалось сменить пароль. Попробуйте ещё раз.'))
    }
  }

  return <form className={styles.form} onSubmit={(event) => void submit(event)} noValidate>
    <Field label="Текущий пароль" type="password" autoComplete="current-password" required value={current} onChange={(event) => setCurrent(event.target.value)} error={errors.current} />
    <Field label="Новый пароль" type="password" autoComplete="new-password" required hint="От 8 до 128 символов" value={next} onChange={(event) => setNext(event.target.value)} error={errors.next} />
    <Field label="Повторите новый пароль" type="password" autoComplete="new-password" required value={repeat} onChange={(event) => setRepeat(event.target.value)} error={errors.repeat} />
    {submitError && <p className={styles.error} role="alert">{submitError}</p>}
    <Button type="submit" pending={isLoading}>Сменить пароль</Button>
  </form>
}
