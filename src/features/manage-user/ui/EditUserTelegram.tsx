import { useState } from 'react'
import type { User } from '@/entities/session'
import { getApiErrorCode, getSafeErrorMessage } from '@/shared/api'
import { Button, Dialog, Field } from '@/shared/ui'
import { useUpdateUserMutation } from '../api/userApi'
import { telegramError } from '../model/telegram'

const initialOf = (user: User) => user.telegram_username ? `@${user.telegram_username}` : user.telegram_user_id ? String(user.telegram_user_id) : ''

/** Admin sets or clears the user's Telegram (@username or numeric ID). */
export function EditUserTelegram({ user, onUncertain }: { user: User; onUncertain: () => void }) {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState(() => initialOf(user))
  const [error, setError] = useState<string>()
  const [update, { isLoading }] = useUpdateUserMutation()
  return <Dialog
    trigger={<Button variant="secondary">Telegram</Button>}
    title={`Telegram пользователя ${user.login}`}
    description="@username или числовой ID. По username тег в напоминаниях работает сразу, а кнопка «Оплачено» и личные сообщения — после того, как человек напишет боту /start. Пустое поле — отвязать."
    open={open}
    onOpenChange={(next) => {
      if (isLoading) return
      setOpen(next)
      setError(undefined)
      if (next) setValue(initialOf(user))
    }}
    closeLabel="Отмена"
  >
    <Field label="Telegram" autoComplete="off" placeholder="@username или 123456789" value={value} onChange={(event) => setValue(event.target.value)} error={error} />
    <Button pending={isLoading} onClick={async () => {
      const problem = telegramError(value)
      if (problem) return setError(problem)
      setError(undefined)
      try {
        await update({ id: user.id, telegram: value.trim() || null }).unwrap()
        setOpen(false)
      } catch (requestError) {
        setError(getApiErrorCode(requestError) === 'telegram_already_linked'
          ? 'Этот Telegram уже указан у другого пользователя.'
          : getSafeErrorMessage(requestError, 'Не удалось сохранить Telegram.'))
        onUncertain()
      }
    }}>Сохранить</Button>
  </Dialog>
}
