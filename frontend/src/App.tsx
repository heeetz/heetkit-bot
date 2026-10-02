import { useEffect, useRef, useState } from 'react'
import {
  type AIProviderSettings,
  type AIStatus,
  type AppStatus,
  type CredentialInfo,
  type LogEntry,
  type TwitchConnectionSettings,
  waitForBridge,
} from './bridge'
import CommandsPage from './pages/CommandsPage'
import AIPage from './pages/AIPage'
import SettingsPage from './pages/SettingsPage'
import FeedbackToast from './components/FeedbackToast'
import LogEventSummary, { logEventClassNames } from './components/LogEventSummary'
import Switch from './components/Switch'
import './styles.css'

const sections = ['Dashboard', 'Commands', 'AI', 'Logs', 'Settings'] as const
type Section = (typeof sections)[number]

interface DashboardSetup {
  twitch: TwitchConnectionSettings
  credentials: CredentialInfo[]
  aiProvider: AIProviderSettings
}

interface SetupTask {
  title: string
  description: string
  action: string
  section: Extract<Section, 'AI' | 'Settings'>
  targetId?: string
}

function formatUptime(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  return [hours, minutes, seconds]
    .map((part) => part.toString().padStart(2, '0'))
    .join(':')
}

function Dashboard({ status, aiStatus, onChangeBotState, onChangeAIState, onNavigate, busy }: {
  status: AppStatus | null
  aiStatus: AIStatus | null
  onChangeBotState: (shouldRun: boolean) => void
  onChangeAIState: (kind: 'enabled' | 'memory', enabled: boolean) => void
  onNavigate: (section: Extract<Section, 'AI' | 'Settings'>, targetId?: string) => void
  busy: string
}) {
  const [setup, setSetup] = useState<DashboardSetup | null>(null)
  const [setupError, setSetupError] = useState('')

  useEffect(() => {
    let active = true
    const loadSetup = async () => {
      try {
        const api = await waitForBridge()
        const [twitchResponse, credentialResponse, aiResponse] = await Promise.all([
          api.get_twitch_settings(),
          api.get_credentials(),
          api.get_ai_provider_settings(),
        ])
        if (!twitchResponse.ok || !twitchResponse.settings) {
          throw new Error(twitchResponse.error ?? 'Twitch setup status is unavailable.')
        }
        if (!credentialResponse.ok || !credentialResponse.credentials) {
          throw new Error(credentialResponse.error ?? 'Credential status is unavailable.')
        }
        if (!aiResponse.ok || !aiResponse.settings) {
          throw new Error(aiResponse.error ?? 'AI setup status is unavailable.')
        }
        if (active) {
          setSetup({
            twitch: twitchResponse.settings,
            credentials: credentialResponse.credentials,
            aiProvider: aiResponse.settings,
          })
          setSetupError('')
        }
      } catch (reason) {
        if (active) {
          setSetupError(reason instanceof Error ? reason.message : 'Setup status is unavailable.')
        }
      }
    }
    void loadSetup()
    return () => { active = false }
  }, [])

  const statusLabel = status ? (status.running ? 'Running' : 'Stopped') : 'Loading…'
  const setupTasks: SetupTask[] = []
  if (setup) {
    const twitchCredential = setup.credentials.find(
      (credential) => credential.name === 'twitch_client_secret',
    )
    const twitchTargetReady = Boolean(
      setup.twitch.target_channel.trim() && setup.twitch.target_channel_user_id.trim(),
    )
    if (!twitchTargetReady || !twitchCredential?.configured) {
      setupTasks.push({
        title: 'Configure Twitch',
        description: 'Add the target channel and Twitch client secret before starting the bot.',
        action: 'Configure Twitch',
        section: 'Settings',
        targetId: 'twitch-settings',
      })
    } else if (!setup.twitch.oauth_token_available) {
      setupTasks.push({
        title: 'Authorize Twitch',
        description: 'Start the bot to complete Twitch authorization, or review the connection settings first.',
        action: 'Review Twitch',
        section: 'Settings',
        targetId: 'twitch-settings',
      })
    }
    if (!setup.aiProvider.credential?.configured) {
      setupTasks.push({
        title: 'Add a Gemini API key',
        description: 'AI chat needs a Gemini credential stored securely on this computer.',
        action: 'Add Gemini key',
        section: 'Settings',
        targetId: 'credential-settings',
      })
    } else if (!setup.aiProvider.selected_model.trim()) {
      setupTasks.push({
        title: 'Choose an AI model',
        description: 'Select the Gemini model used for the next AI request.',
        action: 'Open AI settings',
        section: 'AI',
      })
    }
    if (aiStatus && aiStatus.available_personalities.length === 0) {
      setupTasks.push({
        title: 'No AI personalities available',
        description: 'The built-in personality list is unavailable. Open AI to review its status.',
        action: 'Open AI settings',
        section: 'AI',
      })
    }
  }

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
      {(setupTasks.length > 0 || setupError) && (
        <article className="card setup-card">
          <div className="section-heading">
            <div>
              <p className="label">GET READY</p>
              <h2>{setupError ? 'Setup status needs attention' : 'Finish setup'}</h2>
              <p className="section-copy">
                {setupError
                  ? 'Some setup details could not be loaded. Open Settings to review the configuration.'
                  : 'Complete these steps, then start the bot from the control above.'}
              </p>
            </div>
            {!setupError && <span className="mini-badge runtime-badge">{setupTasks.length} remaining</span>}
          </div>
          {setupError ? (
            <button className="secondary" onClick={() => onNavigate('Settings')}>Open Settings</button>
          ) : (
            <div className="setup-list">
              {setupTasks.map((task) => (
                <div className="setup-item" key={task.title}>
                  <div><strong>{task.title}</strong><p>{task.description}</p></div>
                  <button className="secondary" onClick={() => onNavigate(task.section, task.targetId)}>{task.action}</button>
                </div>
              ))}
            </div>
          )}
        </article>
      )}
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
          <h3>{status?.channel || setup?.twitch.target_channel || 'Not configured'}</h3>
          <p>Bot account: {status?.account || setup?.twitch.bot_username || 'Not configured'}</p>
        </article>
        <article className="card dashboard-card">
          <p className="label">SESSION UPTIME</p>
          <h3 className="metric">{status ? formatUptime(status.uptime_seconds) : '—'}</h3>
          <p>Time since the current bot session started.</p>
        </article>
        <article className="card dashboard-card dashboard-ai-card">
          <div className="dashboard-card-heading">
            <div><p className="label">AI RUNTIME</p><h3>{aiStatus?.model || setup?.aiProvider.selected_model || 'Not configured'}</h3></div>
            <span className="mini-badge">{aiStatus?.active_personality || 'Not selected'}</span>
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
        {visibleEntries.length === 0 && (
          <p className="log-empty">
            {entries.length === 0
              ? 'No application activity yet. Start the bot to see connection, command, and chat events.'
              : 'No log entries match the current level and search filters.'}
          </p>
        )}
        {visibleEntries.map((entry) => (
          <div className={`log-row ${logEventClassNames(entry.event_kind)}`} key={entry.id}>
            <time dateTime={entry.timestamp}>{new Date(entry.timestamp).toLocaleTimeString()}</time>
            <span className={`log-level level-${entry.level.toLowerCase()}`}>{entry.level}</span>
            <span className="log-source" title={entry.source}>{entry.source}</span>
            <div className="log-message">
              <LogEventSummary entry={entry} />
              <pre className={entry.event_kind && !['WARNING', 'ERROR', 'CRITICAL'].includes(entry.level) ? 'log-raw is-secondary' : 'log-raw'}>
                {entry.message}
              </pre>
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

  const navigate = (nextSection: Section, targetId?: string) => {
    setSection(nextSection)
    window.requestAnimationFrame(() => {
      if (targetId) {
        document.getElementById(targetId)?.scrollIntoView({ block: 'start' })
      } else {
        document.querySelector('main')?.scrollTo({ top: 0 })
        window.scrollTo({ top: 0 })
      }
    })
  }

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
          {sections.map((item) => <button key={item} className={section === item ? 'active' : ''} onClick={() => navigate(item)}>{item}</button>)}
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
            onNavigate={navigate}
          />
        )}
        <div hidden={section !== 'Commands'}><CommandsPage active={section === 'Commands'} /></div>
        <div hidden={section !== 'AI'}><AIPage active={section === 'AI'} onOpenSettings={() => navigate('Settings', 'credential-settings')} /></div>
        {section === 'Logs' && <LogsPage />}
        <div hidden={section !== 'Settings'}><SettingsPage active={section === 'Settings'} /></div>
      </main>
    </div>
  )
}
