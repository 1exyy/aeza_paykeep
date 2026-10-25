import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Button, Field } from '@/shared/ui'
import { readLastTeam, saveLastTeam } from '../model/lastTeam'
import styles from './LoginForm.module.css'

const loginSchema = z.object({
  team: z.string().trim().max(64, 'Не более 64 символов'),
  login: z.string().min(1, 'Введите логин').max(64, 'Не более 64 символов'),
  password: z.string().min(1, 'Введите пароль').max(128, 'Не более 128 символов'),
})

export type LoginValues = z.infer<typeof loginSchema>
const fields = ['team', 'login', 'password'] as const
const isField = (value: unknown): value is (typeof fields)[number] => fields.some((field) => field === value)

type Props = {
  onSubmit: (values: LoginValues) => Promise<void>
  submitError?: string
}

export function LoginForm({ onSubmit, submitError }: Props) {
  const [localError, setLocalError] = useState<string>()
  const { register, handleSubmit, setError, clearErrors, formState: { errors, isSubmitting } } = useForm<LoginValues>({
    defaultValues: { team: readLastTeam(), login: '', password: '' },
  })

  const submit = handleSubmit(async (values) => {
    clearErrors()
    setLocalError(undefined)
    const parsed = loginSchema.safeParse(values)
    if (!parsed.success) {
      const reported = new Set<string>()
      for (const issue of parsed.error.issues) {
        const field = issue.path[0]
        if (isField(field) && !reported.has(field)) {
          setError(field, { message: issue.message })
          reported.add(field)
        }
      }
      return
    }
    try {
      await onSubmit(parsed.data)
      saveLastTeam(parsed.data.team)
    } catch {
      setLocalError('Не удалось выполнить вход. Попробуйте ещё раз.')
    }
  })

  return <form className={styles.form} onSubmit={submit} noValidate>
    <Field label="Команда" autoComplete="organization" hint="Название вашей команды. Супервайзер оставляет поле пустым" {...register('team')} error={errors.team?.message} />
    <Field label="Логин" autoComplete="username" required {...register('login')} error={errors.login?.message} />
    <Field label="Пароль" type="password" autoComplete="current-password" required {...register('password')} error={errors.password?.message} />
    {(submitError || localError) && <p className={styles.error} role="alert">{submitError || localError}</p>}
    <Button type="submit" pending={isSubmitting}>Войти</Button>
  </form>
}
