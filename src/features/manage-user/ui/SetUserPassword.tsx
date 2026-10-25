import { useState } from 'react'
import type { User } from '@/entities/session'
import { getSafeErrorMessage } from '@/shared/api'
import { Button, Dialog, Field } from '@/shared/ui'
import { useUpdateUserMutation } from '../api/userApi'

/** The admin sets a temporary password; the member replaces it at the next login. */
export function SetUserPassword({ user, onUncertain }: { user: User; onUncertain: () => void }) {
  const [open, setOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState<string>()
  const [done, setDone] = useState(false)
  const [update, { isLoading }] = useUpdateUserMutation()
  return <Dialog
    trigger={<Button variant="secondary">Сменить пароль</Button>}
    title={`Новый пароль для ${user.login}`}
    description="Это временный пароль: при следующем входе пользователь задаст свой. Все его сессии завершатся."
    open={open}
    onOpenChange={(next) => {
      if (isLoading) return
      setOpen(next)
      setError(undefined)
      setDone(false)
      setPassword('')
      setRepeat('')
    }}
    closeLabel={done ? 'Закрыть' : 'Отмена'}
  >
    {done ? <p role="status">Пароль изменён. Передайте его пользователю.</p> : <>
      <Field label="Новый пароль" type="password" autoComplete="new-password" hint="От 8 до 128 символов" value={password} onChange={(event) => setPassword(event.target.value)} />
      <Field label="Повторите пароль" type="password" autoComplete="new-password" value={repeat} onChange={(event) => setRepeat(event.target.value)} error={error} />
      <Button pending={isLoading} onClick={async () => {
        if (password.length < 8 || password.length > 128) return setError('Пароль: от 8 до 128 символов')
        if (password !== repeat) return setError('Пароли не совпадают')
        setError(undefined)
        try {
          await update({ id: user.id, password }).unwrap()
          setDone(true)
        } catch (requestError) {
          setError(getSafeErrorMessage(requestError, 'Не удалось сменить пароль.'))
          onUncertain()
        }
      }}>Сменить пароль</Button>
    </>}
  </Dialog>
}
