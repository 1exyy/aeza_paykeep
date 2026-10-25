import { useState } from 'react'
import { getSafeErrorMessage } from '@/shared/api'
import { Button, Dialog } from '@/shared/ui'
import { useDeleteUserMutation } from '../api/userApi'
import styles from './DeleteUser.module.css'

export function DeleteUser({ id, login, onUncertain }: { id: number; login: string; onUncertain: () => void }) {
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string>()
  const [remove, { isLoading }] = useDeleteUserMutation()
  return <Dialog
    trigger={<Button variant="secondary">Удалить пользователя</Button>}
    title="Удалить пользователя?"
    description={`Учётная запись «${login}» больше не сможет войти. История действий сохранится.`}
    open={open}
    onOpenChange={(next) => { if (!isLoading) { setOpen(next); setError(undefined) } }}
    closeLabel="Оставить"
    cancelFirst
  >
    {error && <p className={styles.error} role="alert">{error}</p>}
    <Button variant="danger" pending={isLoading} onClick={async () => {
      setError(undefined)
      try {
        await remove(id).unwrap()
        setOpen(false)
      } catch (requestError) {
        setError(getSafeErrorMessage(requestError, 'Не удалось подтвердить удаление. Обновите список перед повтором.'))
        onUncertain()
      }
    }}>Удалить пользователя</Button>
  </Dialog>
}
