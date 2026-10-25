import { useState } from 'react'
import { getApiErrorCode, getSafeErrorMessage } from '@/shared/api'
import { Button, Dialog } from '@/shared/ui'
import { useApproveApplicationMutation, useRejectApplicationMutation } from '../api/applicationsApi'
import type { ApplicationDecision, TeamApplication } from '../api/applicationsApi'
import styles from './ApplicationCard.module.css'

const security = { starttls: 'STARTTLS', ssl: 'SSL/TLS', none: 'без шифрования' } as const
const when = (value: string) => value.slice(0, 16).replace('T', ' ')

function applicantLabel(item: TeamApplication): string {
  const { username, name, telegram_id } = item.applicant
  return [name, username ? `@${username}` : null, `ID ${telegram_id}`].filter(Boolean).join(' · ')
}

/** One application: details, and for a new one «Принять» / «Отклонить». */
export function ApplicationCard({ item }: { item: TeamApplication }) {
  const [approve, approving] = useApproveApplicationMutation()
  const [reject, rejecting] = useRejectApplicationMutation()
  const [approveOpen, setApproveOpen] = useState(false)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string>()
  const [decision, setDecision] = useState<ApplicationDecision>()

  const failed = (requestError: unknown, fallback: string) => {
    const code = getApiErrorCode(requestError)
    setError(code === 'team_name_taken' ? 'Команда с таким названием уже есть — отклоните заявку с причиной.' : code === 'application_decided' ? 'По заявке уже принято решение. Обновите список.' : getSafeErrorMessage(requestError, fallback))
  }

  return <article className={styles.card}>
    <h2>{item.team_name}</h2>
    <dl>
      <div><dt>Админ</dt><dd>{item.admin_login}</dd></div>
      <div><dt>Заявитель</dt><dd>{applicantLabel(item)}</dd></div>
      <div><dt>Чат напоминаний</dt><dd>{item.telegram_chat_id}</dd></div>
      <div><dt>Почта</dt><dd>{item.smtp ? `${item.smtp.host}:${item.smtp.port}, ${security[item.smtp.security]}; получатели: ${item.smtp.recipients.join(', ')}` : 'не указана'}</dd></div>
      <div><dt>Подана</dt><dd>{when(item.created_at)}</dd></div>
      {item.decided_at && <div><dt>Решение</dt><dd>{item.status === 'approved' ? 'Принята' : 'Отклонена'} {when(item.decided_at)}{item.decided_by ? ` — ${item.decided_by}` : ''}</dd></div>}
      {item.reject_reason && <div><dt>Причина отказа</dt><dd>{item.reject_reason}</dd></div>}
    </dl>

    {decision && (decision.notified
      ? <p className={styles.result} role="status">{decision.application.status === 'approved' ? 'Команда создана. Данные для входа отправлены заявителю в Telegram.' : 'Заявка отклонена. Заявитель получил причину в Telegram.'}</p>
      : <p className={styles.result} role="status">{decision.application.status === 'approved'
        ? <>Команда создана, но бот заявок не смог написать заявителю. Передайте данные сами: команда «{decision.application.team_name}», логин {decision.application.admin_login}, временный пароль <span className={styles.password}>{decision.temp_password}</span>. Пароль больше не покажется.</>
        : 'Заявка отклонена, но бот заявок не смог сообщить об этом заявителю.'}</p>)}
    {error && <p className={styles.error} role="alert">{error}</p>}

    {item.status === 'pending' && !decision && <div className={styles.actions}>
      <Dialog
        trigger={<Button>Принять</Button>}
        title={`Создать команду «${item.team_name}»?`}
        description={`Будет создан администратор ${item.admin_login} с временным паролем; бот заявок пришлёт заявителю данные для входа.`}
        open={approveOpen}
        onOpenChange={(next) => { if (!approving.isLoading) { setApproveOpen(next); setError(undefined) } }}
        closeLabel="Отмена"
        cancelFirst
      >
        <Button pending={approving.isLoading} onClick={async () => {
          setError(undefined)
          try {
            setDecision(await approve(item.id).unwrap())
            setApproveOpen(false)
          } catch (requestError) {
            setApproveOpen(false)
            failed(requestError, 'Не удалось принять заявку.')
          }
        }}>Создать команду</Button>
      </Dialog>
      <Dialog
        trigger={<Button variant="secondary">Отклонить</Button>}
        title="Отклонить заявку?"
        description="Причину увидит заявитель в Telegram."
        open={rejectOpen}
        onOpenChange={(next) => { if (!rejecting.isLoading) { setRejectOpen(next); setError(undefined) } }}
        closeLabel="Отмена"
        cancelFirst
      >
        <label htmlFor={`reason-${item.id}`}>Причина</label>
        <textarea id={`reason-${item.id}`} className={styles.reason} maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} />
        <Button variant="danger" pending={rejecting.isLoading} onClick={async () => {
          if (!reason.trim()) return setError('Укажите причину отказа')
          setError(undefined)
          try {
            setDecision(await reject({ id: item.id, reason: reason.trim() }).unwrap())
            setRejectOpen(false)
          } catch (requestError) {
            failed(requestError, 'Не удалось отклонить заявку.')
          }
        }}>Отклонить</Button>
      </Dialog>
    </div>}
  </article>
}
