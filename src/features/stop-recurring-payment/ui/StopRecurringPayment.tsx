import { useState } from 'react'
import { useStopRecurringPaymentMutation } from '@/entities/recurring-payment'
import { getSafeErrorMessage } from '@/shared/api'
import { Button, Dialog } from '@/shared/ui'
import styles from './StopRecurringPayment.module.css'

export function StopRecurringPayment({ id, title, onUncertain }: { id: number; title: string; onUncertain: () => void }) {
  const [open, setOpen] = useState(false)
  const [stop, { isLoading }] = useStopRecurringPaymentMutation()
  const [error, setError] = useState<string>()

  return <Dialog
    trigger={<Button variant="secondary">Прекратить платёж</Button>}
    title="Прекратить регулярный платёж?"
    description={`«${title}»: новые напоминания отправляться не будут. История сохранится. Будущие неоплаченные начисления будут удалены.`}
    open={open}
    onOpenChange={(next) => { if (!isLoading) { setOpen(next); setError(undefined) } }}
    closeLabel="Оставить"
    cancelFirst
  >
    {error && <p className={styles.error} role="alert">{error}</p>}
    <Button variant="danger" pending={isLoading} onClick={async () => {
      setError(undefined)
      try {
        await stop(id).unwrap()
        setOpen(false)
      } catch (requestError) {
        setError(getSafeErrorMessage(requestError, 'Не удалось подтвердить результат. Обновите данные перед повтором.'))
        onUncertain()
      }
    }}>Прекратить платёж</Button>
  </Dialog>
}
