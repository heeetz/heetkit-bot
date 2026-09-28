import { useEffect, useState } from 'react'
import {
  type AIStatus,
  type AppStatus,
  type CommandInfo,
  type CommandsResponse,
  waitForBridge,
} from './bridge'
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

function cooldownLabel(command: CommandInfo): string {
  const parts: string[] = []
  if (command.cooldown.per_user_seconds > 0) {
    parts.push(`${command.cooldown.per_user_seconds}s / user`)
  }
  if (command.cooldown.global_seconds > 0) {
    parts.push(`${command.cooldown.global_seconds}s global`)
  }
  return parts.length ? parts.join(' · ') : 'None'
}

function CommandsPage() {
  const [data, setData] = useState<CommandsResponse | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    let timer = 0
    const refresh = async () => {
      try {
        const api = await waitForBridge()
        const response = await api.get_commands()
        if (active) {
          setData(response)
          setError('')
        }
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : 'Could not load commands.')
        }
      } finally {
        if (active) {
          timer = window.setTimeout(() => void refresh(), 3000)
        }
      }
    }
    void refresh()
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [])

  return (
    <section className="card table-card">
      <div className="section-heading">
        <div><p className="label">REGISTERED COMMANDS</p><h2>Effective runtime settings</h2></div>
        <span className="read-only-badge">Read only</span>
      </div>
      {error && <div className="inline-error">{error}</div>}
      {!data ? <p className="muted">Loading command registry…</p> : (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Command</th><th>State</th><th>Permission</th><th>Cooldown</th></tr></thead>
            <tbody>
              {data.commands.map((command) => (
                <tr key={command.name}>
                  <td>
                    <strong>{data.command_prefix}{command.name}</strong>
                    <div className="command-meta">
                      {command.hidden && <span className="mini-badge">Hidden</span>}
                      {command.aliases.length > 0 && <span>Aliases: {command.aliases.map((alias) => `${data.command_prefix}${alias}`).join(', ')}</span>}
                    </div>
                  </td>
                  <td><span className={`state-pill ${command.enabled ? 'enabled' : ''}`}>{command.enabled ? 'Enabled' : 'Disabled'}</span></td>
                  <td>{command.permission.toLowerCase()}</td>
                  <td>{cooldownLabel(command)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function AIPage() {
  const [status, setStatus] = useState<AIStatus | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    let timer = 0
    const refresh = async () => {
      try {
        const api = await waitForBridge()
        const response = await api.get_ai_status()
        if (active) {
          setStatus(response)
          setError('')
        }
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : 'Could not load AI status.')
        }
      } finally {
        if (active) {
          timer = window.setTimeout(() => void refresh(), 2500)
        }
      }
    }
    void refresh()
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [])

  return (
    <>
      {error && <div className="error-banner">{error}</div>}
      <section className="card-grid">
        <article className="card"><p className="label">AI command</p><h3>{status ? (status.enabled ? 'Enabled' : 'Disabled') : 'Loading…'}</h3><p>Backed by the canonical AI command state.</p></article>
        <article className="card"><p className="label">Conversation memory</p><h3>{status ? (status.memory_enabled ? 'Enabled' : 'Disabled') : 'Loading…'}</h3><p>Current process state; no editor is exposed here.</p></article>
        <article className="card"><p className="label">Active personality</p><h3>{status?.active_personality ?? '—'}</h3><p>{status ? `${status.available_personalities.length} built-in personalities available` : 'Loading…'}</p></article>
        <article className="card"><p className="label">Gemini model</p><h3>{status?.model ?? '—'}</h3><p>Configured by the Python backend.</p></article>
      </section>
    </>
  )
}

function Placeholder({ section }: { section: 'Logs' | 'Settings' }) {
  const message = section === 'Logs'
    ? 'Live application logs will appear here in the next Phase 2 slice.'
    : 'Application settings editing is deliberately deferred to Phase 3.'
  return <section className="card empty-state"><p className="label">PHASE 2</p><h2>{section}</h2><p>{message}</p></section>
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
        {error && <div className="error-banner">{error}</div>}
        {section === 'Dashboard' && <Dashboard status={status} busy={actionBusy} onChangeState={(shouldRun) => void changeBotState(shouldRun)} />}
        {section === 'Commands' && <CommandsPage />}
        {section === 'AI' && <AIPage />}
        {(section === 'Logs' || section === 'Settings') && <Placeholder section={section} />}
      </main>
    </div>
  )
}
