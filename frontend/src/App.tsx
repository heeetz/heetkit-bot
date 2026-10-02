import { useEffect, useRef, useState } from 'react'
import {
  type AIStatus,
  type AppStatus,
  type LogEntry,
  waitForBridge,
} from './bridge'
import CommandsPage from './pages/CommandsPage'
import AIPage from './pages/AIPage'
import SettingsPage from './pages/SettingsPage'
import FeedbackToast from './components/FeedbackToast'
import Switch from './components/Switch'
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

function Dashboard({ status, aiStatus, onChangeBotState, onChangeAIState, busy }: {
  status: AppStatus | null
  aiStatus: AIStatus | null
  onChangeBotState: (shouldRun: boolean) => void
  onChangeAIState: (kind: 'enabled' | 'memory', enabled: boolean) => void
  busy: string
}) {
  const statusLabel = status ? (status.running ? 'Running' : 'Stopped') : 'Loading…'
  return (
    <section className="dashboard-layout">
      <article className="card dashboard-hero">
        <div className="dashboard-hero-status">
          <span className={`status-dot ${status?.running ? 'online' : ''}`} />
          <div><p className="label">BOT STATUS</p><h2>{statusLabel}</h2></div>
        </div>
        <button
          className={status?.running ? 'danger' : 'primary'}
          disabled={!status || Boolean(busy)}
          onClick={() => onChangeBotState(!status?.running)}
        >
          {busy === 'bot' ? 'Working…' : status?.running ? 'Stop Bot' : 'Start Bot'}
        </button>
      </article>
      <div className="dashboard-grid">
        <article className="card dashboard-card">
          <p className="label">TWITCH CONNECTION</p>
          <h3 className={status?.twitch_connected ? 'success-text' : ''}>
            {status ? (status.twitch_connected ? 'Connected' : 'Disconnected') : 'Loading…'}
          </h3>
          <p>{status?.running ? 'Connection state from the active bot session.' : 'Start the bot when you are ready to connect.'}</p>
        </article>
        <article className="card dashboard-card">
          <p className="label">ACTIVE CHANNEL</p>
          <h3>{status?.channel ?? '—'}</h3>
          <p>Bot account: {status?.account ?? '—'}</p>
        </article>
        <article className="card dashboard-card">
          <p className="label">SESSION UPTIME</p>
          <h3 className="metric">{status ? formatUptime(status.uptime_seconds) : '—'}</h3>
          <p>Time since the current bot session started.</p>
        </article>
        <article className="card dashboard-card dashboard-ai-card">
          <div className="dashboard-card-heading">
            <div><p className="label">AI RUNTIME</p><h3>{aiStatus?.model ?? 'Loading…'}</h3></div>
            <span className="mini-badge">{aiStatus?.active_personality ?? '—'}</span>
          </div>
          <div className="dashboard-switches">
            <Switch
              checked={aiStatus?.enabled ?? false}
              disabled={!aiStatus || Boolean(busy)}
              ariaLabel="Enable AI command"
              onCheckedChange={(enabled) => onChangeAIState('enabled', enabled)}
            >
              <span><strong>AI command</strong><small>{aiStatus?.enabled ? 'Enabled' : 'Disabled'}</small></span>
            </Switch>
            <Switch
              checked={aiStatus?.memory_enabled ?? false}
              disabled={!aiStatus || Boolean(busy)}
              ariaLabel="Enable conversation memory"
              onCheckedChange={(enabled) => onChangeAIState('memory', enabled)}
            >
              <span><strong>Conversation memory</strong><small>{aiStatus?.memory_enabled ? 'Enabled' : 'Disabled'}</small></span>
            </Switch>
          </div>
        </article>
      </div>
    </section>
  )
}

const logLevels = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const

const eventLabels: Record<string, string> = {
  'chat.incoming': 'CHAT IN',
  'chat.outgoing': 'CHAT OUT',
  'chat.filtered': 'CHAT FILTERED',
  'command.invoke': 'COMMAND',
  'command.cooldown': 'COOLDOWN',
  'twitch.subscribe': 'TWITCH',
  'twitch.connected': 'TWITCH READY',
  'twitch.disconnected': 'TWITCH LOST',
  'twitch.reconnect': 'TWITCH RECONNECT',
  'twitch.start': 'TWITCH START',
  'twitch.stop': 'TWITCH STOP',
  'twitch.shutdown': 'TWITCH STOP',
  'ai.request_config': 'AI CONFIG',
  'ai.request_start': 'AI REQUEST',
  'ai.request_finish': 'AI RESPONSE',
  'ai.fallback': 'AI FALLBACK',
  'ai.failure': 'AI FAILURE',
}

const contextLabels: Record<string, string> = {
  username: 'user',
  command: 'command',
  channel: 'channel',
  retry_after_seconds: 'retry',
  duration_seconds: 'duration',
  model: 'model',
  provider: 'provider',
  setting: 'setting',
  action: 'action',
}

function eventTone(eventKind: string | null) {
  return eventKind?.split('.')[0] ?? 'generic'
}

function eventClassName(eventKind: string | null) {
  return eventKind ? `event-${eventKind.replaceAll('.', '-')}` : ''
}

function eventLabel(eventKind: string | null) {
  if (!eventKind) {
    return ''
  }
  if (eventLabels[eventKind]) {
    return eventLabels[eventKind]
  }
  if (eventKind.startsWith('settings.')) {
    return 'SETTINGS'
  }
  return eventKind.replace('.', ' ').toUpperCase()
}

function formatContextValue(key: string, value: string | number | boolean) {
  if (key === 'username') {
    return `@${value}`
  }
  if (key === 'command') {
    return `!${value}`
  }
  if (key === 'retry_after_seconds' || key === 'duration_seconds') {
    return `${value}s`
  }
  return String(value)
}

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
      || entry.event_kind?.toLowerCase().includes(normalizedSearch)
      || Object.values(entry.context).some(
        (value) => String(value).toLowerCase().includes(normalizedSearch),
      )
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
        <Switch
          className="checkbox-field"
          checked={autoScroll}
          onCheckedChange={setAutoScroll}
        >
          Auto-scroll
        </Switch>
        <button className="secondary" onClick={() => setEntries([])}>Clear view</button>
      </div>
      {error && <div className="inline-error log-error">{error}</div>}
      <div className="log-console">
        {visibleEntries.length === 0 && <p className="log-empty">No matching log entries.</p>}
        {visibleEntries.map((entry) => (
          <div className={`log-row event-${eventTone(entry.event_kind)} ${eventClassName(entry.event_kind)}`} key={entry.id}>
            <time dateTime={entry.timestamp}>{new Date(entry.timestamp).toLocaleTimeString()}</time>
            <span className={`log-level level-${entry.level.toLowerCase()}`}>{entry.level}</span>
            <span className="log-source">{entry.source}</span>
            <div className="log-message">
              {entry.event_kind && (
                <div className="log-event-summary">
                  <span className="log-event-kind">{eventLabel(entry.event_kind)}</span>
                  {Object.entries(entry.context).map(([key, value]) => (
                    <span className="log-context" key={key}>
                      <span>{contextLabels[key] ?? key}</span>
                      {formatContextValue(key, value)}
                    </span>
                  ))}
                </div>
              )}
              <pre>{entry.message}</pre>
            </div>
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
  const [aiStatus, setAIStatus] = useState<AIStatus | null>(null)
  const [error, setError] = useState('')
  const [actionBusy, setActionBusy] = useState('')

  useEffect(() => {
    let active = true
    let timer = 0
    const refresh = async (api: Awaited<ReturnType<typeof waitForBridge>>) => {
      try {
        const [nextStatus, nextAIStatus] = await Promise.all([
          api.get_app_status(),
          api.get_ai_status(),
        ])
        if (active) {
          setStatus(nextStatus)
          setAIStatus(nextAIStatus)
          setError('')
        }
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : 'Backend request failed.')
        }
      } finally {
        if (active) {
          timer = window.setTimeout(() => void refresh(api), 1500)
        }
      }
    }
    const initialize = async () => {
      try {
        const api = await waitForBridge()
        if (active) {
          await refresh(api)
        }
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : 'Backend request failed.')
        }
      }
    }
    void initialize()
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [])

  const changeBotState = async (shouldRun: boolean) => {
    setError('')
    setActionBusy('bot')
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
      setActionBusy('')
    }
  }

  const changeAIState = async (kind: 'enabled' | 'memory', enabled: boolean) => {
    setError('')
    setActionBusy(`ai:${kind}`)
    try {
      const api = await waitForBridge()
      const result = kind === 'enabled'
        ? await api.set_ai_enabled(enabled)
        : await api.set_ai_memory_enabled(enabled)
      if (!result.ok) {
        throw new Error(result.error ?? 'The AI state could not be changed.')
      }
      setAIStatus(await api.get_ai_status())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Backend request failed.')
    } finally {
      setActionBusy('')
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
        {section === 'Dashboard' && (
          <Dashboard
            status={status}
            aiStatus={aiStatus}
            busy={actionBusy}
            onChangeBotState={(shouldRun) => void changeBotState(shouldRun)}
            onChangeAIState={(kind, enabled) => void changeAIState(kind, enabled)}
          />
        )}
        <div hidden={section !== 'Commands'}><CommandsPage active={section === 'Commands'} /></div>
        <div hidden={section !== 'AI'}><AIPage active={section === 'AI'} /></div>
        {section === 'Logs' && <LogsPage />}
        <div hidden={section !== 'Settings'}><SettingsPage active={section === 'Settings'} /></div>
      </main>
    </div>
  )
}
