import { Component, type ReactNode } from 'react'
import { Button } from '@/shared/ui'
import styles from './AppErrorBoundary.module.css'

type Props = { children: ReactNode }
type State = { failed: boolean }

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  render() {
    if (this.state.failed) {
      return <main className={styles.page}>
        <section className={styles.card} role="alert">
          <h1>Не удалось открыть приложение</h1>
          <p>Попробуйте загрузить его снова.</p>
          <Button onClick={() => window.location.reload()}>Повторить</Button>
        </section>
      </main>
    }

    return this.props.children
  }
}
