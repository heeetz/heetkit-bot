import { useEffect, useRef, useState } from 'react'
import {
  type AppStatus,
  type LogEntry,
  waitForBridge,
} from './bridge'
import CommandsPage from './pages/CommandsPage'
import AIPage from './pages/AIPage'
import SettingsPage from './pages/SettingsPage'
import FeedbackToast from './components/FeedbackToast'
import './styles.css'

const sections = ['Dashboard', 'Commands', 'AI', 'Logs', 'Settings'] as const
type Section = (typeof sections)[number]

function formatUptime(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  return [hours, minutes, seconds]
    .map((part) => part.toString().padStart(2, '0'))
    .join(':')
}

function Dashboard({ status, onChangeState, busy }: {
  status: AppStatus | null
  onChangeState: (shouldRun: boolean) => void
  busy: boolean
}) {
  const statusLabel = status ? (status.running ? 'Running' : 'Stopped') : 'Loading…'
  return (
    <section className="card-grid">
      <article className="card hero-card">
        <div><p className="label">Bot status</p><h2>{statusLabel}</h2></div>
        <span className={`status-dot ${status?.running ? 'online' : ''}`} />
        <button
          className={status?.running ? 'danger' : 'primary'}
          disabled={!status || busy}
          onClick={() => onChangeState(!status?.running)}
        >
          {busy ? 'Working…' : status?.running ? 'Stop Bot' : 'Start Bot'}
        </button>
      </article>
      <article className="card">
        <p className="label">Twitch connection</p>
        <h3 className={status?.twitch_connected ? 'success-text' : ''}>
          {status ? (status.twitch_connected ? 'Connected' : 'Disconnected') : 'Loading…'}
        </h3>
        <p>Bot controls remain available while Twitch is disconnected.</p>
      </article>
      <article className="card">
        <p className="label">Active channel</p>
        <h3>{status?.channel ?? '—'}</h3>
        <p>Bot account: {status?.account ?? '—'}</p>
      </article>
      <article className="card">
        <p className="label">Session uptime</p>
        <h3 className="metric">{status ? formatUptime(status.uptime_seconds) : '—'}</h3>
      </article>
    </section>
  )
}

const logLevels = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const

function LogsPage() {
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [level, setLevel] = useState<(typeof logLevels)[number]>('ALL')
  const [search, setSearch] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const [error, setError] = useState('')
  const cursor = useRef(0)
  const bottom = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let active = true
    let timer = 0
    const refresh = async () => {
      try {
        const api = await waitForBridge()
        const response = await api.get_recent_logs(cursor.current, 200)
        if (active && response.entries.length > 0) {
          cursor.current = response.entries.at(-1)?.id ?? cursor.current
          setEntries((current) => [...current, ...response.entries].slice(-500))
        }
        if (active) {
          setError('')
        }
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : 'Could not load application logs.')
        }
      } finally {
        if (active) {
          timer = window.setTimeout(() => void refresh(), 1000)
        }
      }
    }
    void refresh()
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [])

  const normalizedSearch = search.trim().toLowerCase()
  const visibleEntries = entries.filter((entry) => {
    const matchesLevel = level === 'ALL' || entry.level === level
    const matchesSearch = !normalizedSearch
      || entry.message.toLowerCase().includes(normalizedSearch)
      || entry.source.toLowerCase().includes(normalizedSearch)
    return matchesLevel && matchesSearch
  })

  useEffect(() => {
    if (autoScroll) {
      bottom.current?.scrollIntoView({ block: 'nearest' })
    }
  }, [autoScroll, visibleEntries.length])

  return (
    <section className="card logs-card">
      <div className="section-heading">
        <div><p className="label">LIVE APPLICATION LOGS</p><h2>Recent activity</h2></div>
        <span className="read-only-badge">{entries.length} / 500</span>
      </div>
      <div className="log-toolbar">
        <label>
          Level
          <select value={level} onChange={(event) => setLevel(event.target.value as typeof level)}>
            {logLevels.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
        <label className="search-field">
          Search
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Message or source"
          />
        </label>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(event) => setAutoScroll(event.target.checked)}
          />
          Auto-scroll
        </label>
        <button className="secondary" onClick={() => setEntries([])}>Clear view</button>
      </div>
      {error && <div className="inline-error log-error">{error}</div>}
      <div className="log-console">
        {visibleEntries.length === 0 && <p className="log-empty">No matching log entries.</p>}
        {visibleEntries.map((entry) => (
          <div className="log-row" key={entry.id}>
            <time dateTime={entry.timestamp}>{new Date(entry.timestamp).toLocaleTimeString()}</time>
            <span className={`log-level level-${entry.level.toLowerCase()}`}>{entry.level}</span>
            <span className="log-source">{entry.source}</span>
            <pre>{entry.message}</pre>
          </div>
        ))}
        <div ref={bottom} />
      </div>
    </section>
  )
}

export default function App() {
  const [section, setSection] = useState<Section>('Dashboard')
  const [status, setStatus] = useState<AppStatus | null>(null)
  const [error, setError] = useState('')
  const [actionBusy, setActionBusy] = useState(false)

  useEffect(() => {
    let active = true
    let timer = 0
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
      } finally {
        if (active) {
          timer = window.setTimeout(() => void refresh(), 1500)
        }
      }
    }
    void refresh()
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [])

  const changeBotState = async (shouldRun: boolean) => {
    setError('')
    setActionBusy(true)
    try {
      const api = await waitForBridge()
      const result = shouldRun ? await api.start_bot() : await api.stop_bot()
      if (!result.ok) {
        throw new Error(result.error ?? 'The bot state could not be changed.')
      }
      setStatus(await api.get_app_status())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Backend request failed.')
    } finally {
      setActionBusy(false)
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">TB</span><div><strong>Twitch Bot</strong><small>Desktop control</small></div></div>
        <nav>
          {sections.map((item) => <button key={item} className={section === item ? 'active' : ''} onClick={() => setSection(item)}>{item}</button>)}
        </nav>
      </aside>
      <main>
        <header><div><p className="eyebrow">CONTROL CENTER</p><h1>{section}</h1></div></header>
        <FeedbackToast error={error} onDismiss={() => setError('')} />
        {section === 'Dashboard' && <Dashboard status={status} busy={actionBusy} onChangeState={(shouldRun) => void changeBotState(shouldRun)} />}
        <div hidden={section !== 'Commands'}><CommandsPage active={section === 'Commands'} /></div>
        <div hidden={section !== 'AI'}><AIPage active={section === 'AI'} /></div>
        {section === 'Logs' && <LogsPage />}
        <div hidden={section !== 'Settings'}><SettingsPage active={section === 'Settings'} /></div>
      </main>
    </div>
  )
}
