import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router'
import { z } from 'zod'
import { getApiErrorCode, getSafeErrorMessage } from '@/shared/api'
import { Button, Field } from '@/shared/ui'
import { useCreateUserMutation } from '../api/userApi'
import { telegramError } from '../model/telegram'
import styles from './CreateUserForm.module.css'

const schema = z.object({
  login: z.string().regex(/^[a-zA-Z0-9._-]{3,32}$/, 'От 3 до 32 символов: латинские буквы, цифры, точка, дефис или подчёркивание'),
  password: z.string().min(8, 'Не менее 8 символов').max(128, 'Не более 128 символов'),
  telegram: z.string().refine((value) => !telegramError(value), 'Укажите @username (5–32 символа: латиница, цифры, _) или числовой ID'),
})

type Values = z.infer<typeof schema>

export function CreateUserForm() {
  const navigate = useNavigate()
  const [create] = useCreateUserMutation()
  const [submitError, setSubmitError] = useState<string>()
  const { register, handleSubmit, setError, clearErrors, setFocus, formState: { errors, isSubmitting } } = useForm<Values>({ defaultValues: { login: '', password: '', telegram: '' } })
  const submit = handleSubmit(async (values) => {
    setSubmitError(undefined)
    clearErrors()
    const parsed = schema.safeParse(values)
    if (!parsed.success) {
      const reported = new Set<string>()
      for (const issue of parsed.error.issues) {
        const field = issue.path[0]
        if ((field === 'login' || field === 'password' || field === 'telegram') && !reported.has(field)) {
          setError(field, { message: issue.message })
          reported.add(field)
        }
      }
      const first = parsed.error.issues[0]?.path[0]
      if (first === 'login' || first === 'password' || first === 'telegram') setFocus(first)
      return
    }
    try {
      const { telegram, ...rest } = parsed.data
      await create(telegram.trim() ? { ...rest, telegram: telegram.trim() } : rest).unwrap()
      navigate('/users', { replace: true })
    } catch (error) {
      const code = getApiErrorCode(error)
      setSubmitError(code === 'login_taken' ? 'Этот логин уже занят.' : code === 'telegram_already_linked' ? 'Этот Telegram уже указан у другого пользователя.' : getSafeErrorMessage(error, 'Не удалось добавить пользователя.'))
    }
  })

  return <form className={styles.form} onSubmit={submit} noValidate>
    <Field label="Логин" autoComplete="off" required {...register('login')} error={errors.login?.message} />
    <Field label="Пароль" type="password" autoComplete="new-password" required {...register('password')} error={errors.password?.message} />
    <Field label="Telegram" autoComplete="off" placeholder="@username или 123456789" hint="Можно указать позже на странице пользователей" {...register('telegram')} error={errors.telegram?.message} />
    {submitError && <p className={styles.error} role="alert">{submitError}</p>}
    <div className={styles.actions}><Button type="submit" pending={isSubmitting}>Добавить пользователя</Button><Button type="button" variant="secondary" onClick={() => navigate('/users')}>Отмена</Button></div>
  </form>
}
