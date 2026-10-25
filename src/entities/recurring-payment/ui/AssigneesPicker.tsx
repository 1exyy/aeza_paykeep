import { useId } from 'react'
import type { UserRef } from '../api/recurringApi'
import type { AssigneesValue } from '../model/assignees'
import styles from './AssigneesPicker.module.css'

type Props = {
  users: readonly UserRef[]
  value: AssigneesValue
  onChange: (value: AssigneesValue) => void
  disabled?: boolean
  loading?: boolean
  loadError?: string
  error?: string
}

/** One, several or all users. Only they may press «Оплачено» in Telegram; choosing nobody is allowed. */
export function AssigneesPicker({ users, value, onChange, disabled, loading, loadError, error }: Props) {
  const id = useId()
  const hintId = `${id}-hint`
  const errorId = error ? `${id}-error` : undefined
  const toggleUser = (userId: number, checked: boolean) => onChange({
    assign_all: false,
    assignee_ids: checked ? [...value.assignee_ids, userId] : value.assignee_ids.filter((item) => item !== userId),
  })

  return <fieldset className={styles.group} disabled={disabled} aria-describedby={[hintId, errorId].filter(Boolean).join(' ')}>
    <legend className={styles.legend}>Ответственные</legend>
    <p id={hintId} className={styles.hint}>Их отметят в напоминании, и только они смогут нажать «Оплачено» в Telegram. Можно никого не выбирать.</p>
    <label className={styles.option}>
      <input type="checkbox" checked={value.assign_all} onChange={(event) => onChange({ assign_all: event.target.checked, assignee_ids: [] })} />
      <span>Все пользователи <span className={styles.muted}>(включая добавленных позже)</span></span>
    </label>
    {loading && <p className={styles.hint} role="status">Загружаем пользователей…</p>}
    {loadError && <p className={styles.error} role="alert">{loadError}</p>}
    {!loading && !loadError && users.length === 0 && <p className={styles.hint}>Пользователей пока нет.</p>}
    {users.length > 0 && <ul className={styles.list}>
      {users.map((user) => <li key={user.id}>
        <label className={styles.option}>
          <input
            type="checkbox"
            checked={value.assign_all || value.assignee_ids.includes(user.id)}
            disabled={value.assign_all}
            onChange={(event) => toggleUser(user.id, event.target.checked)}
          />
          <span>{user.login}</span>
        </label>
      </li>)}
    </ul>}
    {error && <p id={errorId} className={styles.error} role="alert">{error}</p>}
  </fieldset>
}
