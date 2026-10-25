import { useState } from 'react'
import { PaymentCard } from '@/entities/payment-occurrence'
import { LoginForm } from '@/features/login'
import { AccessDeniedState, Button, Dialog, EmptyState, ErrorState, Field, LoadingState } from '@/shared/ui'
import { SummaryPanel } from '@/widgets/summary'
import styles from './DevUiPage.module.css'

export function DevUiPage() {
  const [presses, setPresses] = useState(0)
  const [loginNotice, setLoginNotice] = useState('')

  return <main className={styles.page}>
    <header><p className={styles.label}>Только для разработки</p><h1>Общие компоненты</h1><p>Здесь проверяется оформление. Данные платежей и вход не имитируются.</p></header>
    <section aria-labelledby="actions"><h2 id="actions">Действия</h2><div className={styles.row}><Button onClick={() => setPresses((value) => value + 1)}>Проверить кнопку</Button><Button variant="secondary" onClick={() => setPresses(0)}>Сбросить счётчик</Button></div><p role="status">Нажатий: {presses}</p></section>
    <section aria-labelledby="fields"><h2 id="fields">Поля</h2><div className={styles.fields}><Field label="Пример поля" hint="Подпись всегда видна над полем" placeholder="Введите текст" /><Field label="Поле с ошибкой" defaultValue="Пример" error="Проверьте введённое значение" /><Field label="Недоступное поле" disabled defaultValue="Значение" /></div></section>
    <section aria-labelledby="login-preview"><h2 id="login-preview">Форма входа — только оформление</h2><p>Проверяются поля и правила ввода. Авторизация не выполняется, данные никуда не отправляются.</p><LoginForm onSubmit={async () => setLoginNotice('Форма проверена. Запрос не отправлялся.')} />{loginNotice && <p role="status">{loginNotice}</p>}</section>
    <section aria-labelledby="dialogs"><h2 id="dialogs">Диалог</h2><Dialog trigger={<Button variant="secondary">Открыть диалог</Button>} title="Пример диалога" description="Проверьте фокус, переход по Tab и закрытие по Escape."><Field label="Поле в диалоге" placeholder="Введите текст" /></Dialog></section>
    <section aria-labelledby="summary-preview"><h2 id="summary-preview">Пример сводки</h2><p>Вымышленные суммы и подпись зоны только для проверки вёрстки.</p><SummaryPanel periodLabel="Октябрь 2026" timezoneLabel="Тестовая зона" totalsByCurrency={{ RUB: { accrued: '1300.00', paid: '1000.00', unpaid: '300.00', overdue: '100.00' }, USD: { accrued: '150.00', paid: '0.00', unpaid: '150.00', overdue: '50.00' }, EUR: { accrued: '0.00', paid: '0.00', unpaid: '0.00', overdue: '0.00' } }} /></section>
    <section aria-labelledby="cards"><h2 id="cards">Карточки платежей за период</h2><p>Вымышленные примеры только для проверки вёрстки. Серверные данные не загружаются.</p><div className={styles.cards}>
      <PaymentCard title="Очень длинное название регулярного платежа для проверки переноса на узком экране" amount="12345678901234567890.12" currency="RUB" dueDate="2026-11-30" status="unpaid" />
      <PaymentCard title="Хранилище" amount="1000.00" currency="USD" dueDate="2026-09-30" status="overdue" />
      <PaymentCard title="Хранилище" amount="1000.00" currency="USD" dueDate="2026-08-31" paidDate="2026-09-02" status="paid-late" />
      <PaymentCard title="Подписка" amount="20.00" currency="EUR" dueDate="2026-10-10" paidDate="2026-10-10" status="paid" />
    </div></section>
    <section aria-labelledby="states"><h2 id="states">Состояния</h2><div className={styles.grid}><LoadingState /><EmptyState title="Нет данных" description="Пустое состояние после успешного ответа сервера." /><ErrorState title="Не удалось загрузить данные" /><AccessDeniedState /></div></section>
  </main>
}
