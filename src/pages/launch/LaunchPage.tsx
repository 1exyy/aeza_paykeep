import styles from './LaunchPage.module.css'

export function LaunchPage() {
  return (
    <main className={styles.page}>
      <img className={styles.brand} src="/brand/aeza-paykeep.svg" alt="Aéza PayKeep" />
      <section className={styles.content}>
        <p className={styles.eyebrow}>Aéza PayKeep</p>
        <h1>Вход в Aéza PayKeep пока недоступен</h1>
        <p>Подключение к серверу готовится. Данные платежей недоступны.</p>
      </section>
    </main>
  )
}
