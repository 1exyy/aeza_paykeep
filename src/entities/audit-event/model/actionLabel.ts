const labels: Record<string, string> = {
  'recurring.create': 'Платёж создан',
  'recurring.update': 'Платёж изменён',
  'recurring.update_assignees': 'Изменены ответственные',
  'recurring.stop': 'Платёж прекращён',
  'occurrence.mark_paid': 'Отмечено «оплачено»',
  'occurrence.mark_unpaid': 'Оплата отменена',
  'occurrence.change_paid_date': 'Исправлена дата оплаты',
  'telegram.paid_button': '«Оплачено» в Telegram',
  'user.telegram_dm_preference_changed': 'Изменены личные уведомления в Telegram',
}

/** Human label of an audit action; unknown actions are shown as is. */
export function auditActionLabel(action: string): string {
  return labels[action] ?? action
}
