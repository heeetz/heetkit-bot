import { useEffect, useState } from 'react'
import { type AppStatus, waitForBridge } from './bridge'
import './styles.css'

const sections = ['Dashboard', 'Commands', 'AI', 'Logs', 'Settings'] as const
type Section = (typeof sections)[number]

export default function App() {
  const [section, setSection] = useState<Section>('Dashboard')
  const [status, setStatus] = useState<AppStatus | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const refresh = async () => {
      try {
        const api = await waitForBridge()
        const nextStatus = await api.get_app_status()
        if (active) {
          setStatus(nextStatus)
          setError('')
        }
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : 'Backend request failed.')
        }
      }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 1500)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [])

  const changeBotState = async (shouldRun: boolean) => {
    setError('')
    try {
      const api = await waitForBridge()
      const result = shouldRun ? await api.start_bot() : await api.stop_bot()
      if (!result.ok) {
        throw new Error(result.error ?? 'The bot state could not be changed.')
      }
      setStatus(await api.get_app_status())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Backend request failed.')
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">TB</span>
          <div><strong>Twitch Bot</strong><small>Desktop control</small></div>
        </div>
        <nav>
          {sections.map((item) => (
            <button key={item} className={section === item ? 'active' : ''} onClick={() => setSection(item)}>
              {item}
            </button>
          ))}
        </nav>
      </aside>
      <main>
        <header><div><p className="eyebrow">CONTROL CENTER</p><h1>{section}</h1></div></header>
        {error && <div className="error-banner">{error}</div>}
        {section === 'Dashboard' ? (
          <section className="card-grid">
            <article className="card hero-card">
              <div><p className="label">Bot status</p><h2>{status?.running ? 'Running' : 'Stopped'}</h2></div>
              <span className={`status-dot ${status?.running ? 'online' : ''}`} />
              <button className={status?.running ? 'danger' : 'primary'} onClick={() => void changeBotState(!status?.running)}>
                {status?.running ? 'Stop Bot' : 'Start Bot'}
              </button>
            </article>
            <article className="card"><p className="label">Channel</p><h3>{status?.channel ?? '—'}</h3><p>{status?.account ?? '—'}</p></article>
            <article className="card"><p className="label">Session uptime</p><h3>{status ? `${status.uptime_seconds}s` : '—'}</h3></article>
          </section>
        ) : (
          <section className="card empty-state">
            <p className="label">PHASE 2</p>
            <h2>{section} is being connected</h2>
            <p>This section will use the same Python application state as the bot.</p>
          </section>
        )}
      </main>
    </div>
  )
}
