import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  type AIProviderSettings,
  type AIStatus,
  type AppStatus,
  type CredentialInfo,
  type LogEntry,
  type TwitchConnectionSettings,
  twitchConnectionLabel,
  waitForBridge,
} from './bridge'
import CommandsPage from './pages/CommandsPage'
import AIPage from './pages/AIPage'
import FiltersPage from './pages/FiltersPage'
import SettingsPage from './pages/SettingsPage'
import AboutPage from './pages/AboutPage'
import FeedbackToast from './components/FeedbackToast'
import LogEventSummary, { logEventClassNames } from './components/LogEventSummary'
import Switch from './components/Switch'
import './styles.css'

const sections = ['Dashboard', 'Commands', 'Filters', 'AI', 'Logs', 'Settings', 'About'] as const
type Section = (typeof sections)[number]

const subsections: Partial<Record<Section, { label: string; targetId: string }[]>> = {
  Commands: [
    { label: 'Your commands', targetId: 'custom-commands' },
    { label: 'Built-in commands', targetId: 'builtin-commands' },
  ],
  Filters: [
    { label: 'Blocked words', targetId: 'filters-words' },
    { label: 'Blocked phrases', targetId: 'filters-phrases' },
    { label: 'Regex patterns', targetId: 'filters-patterns' },
  ],
  AI: [
    { label: 'Runtime', targetId: 'ai-runtime' },
    { label: 'Models and fallback', targetId: 'ai-models' },
    { label: 'Response language', targetId: 'ai-language' },
    { label: 'Personalities', targetId: 'ai-personalities' },
    { label: 'Profile instructions', targetId: 'ai-profile-instructions' },
    { label: 'Shared instructions', targetId: 'ai-shared-instructions' },
  ],
  Settings: [
    { label: 'Desktop behavior', targetId: 'desktop-settings' },
    { label: 'Twitch connection', targetId: 'twitch-settings' },
    { label: 'Credentials', targetId: 'credential-settings' },
    { label: 'Data & diagnostics', targetId: 'profile-location-settings' },
  ],
}

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
  optional?: boolean
}

function formatUptime(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  return [hours, minutes, seconds]
    .map((part) => part.toString().padStart(2, '0'))
    .join(':')
}

function Dashboard({ status, aiStatus, onChangeBotState, onChangeAIState, onAuthorizeTwitch, onNavigate, busy }: {
  status: AppStatus | null
  aiStatus: AIStatus | null
  onChangeBotState: (shouldRun: boolean) => void
  onChangeAIState: (kind: 'enabled' | 'memory', enabled: boolean) => void
  onAuthorizeTwitch: () => void
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
      setup.twitch.target_channel.trim() && setup.twitch.target_channel_user_id.trim()
        && setup.twitch.client_id.trim() && setup.twitch.bot_username.trim() && setup.twitch.bot_user_id.trim(),
    )
    if (!twitchTargetReady || !twitchCredential?.configured) {
      setupTasks.push({
        title: 'Configure Twitch',
        description: 'Add the Twitch client ID, bot identity, target channel and client secret in Settings, then restart.',
        action: 'Configure Twitch',
        section: 'Settings',
        targetId: 'twitch-settings',
      })
    } else if (setup.twitch.requires_restart) {
      setupTasks.push({
        title: 'Restart to apply Twitch setup',
        description: 'The saved client ID or bot identity is pending. Restart the application before connecting.',
        action: 'Review setup',
        section: 'Settings',
        targetId: 'twitch-settings',
      })
    } else if (!setup.twitch.oauth_token_available && !status?.twitch_connected) {
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
        description: 'Optional: add a Gemini credential to enable AI replies. Other bot commands work without it.',
        optional: true,
        action: 'Add Gemini key',
        section: 'Settings',
        targetId: 'credential-settings',
      })
    } else if (!setup.aiProvider.selected_model.trim()) {
      setupTasks.push({
        title: 'Choose an AI model',
        optional: true,
        description: 'Select the Gemini model used for the next AI request.',
        action: 'Open AI settings',
        section: 'AI',
      })
    }
    if (aiStatus && aiStatus.available_personalities.length === 0) {
      setupTasks.push({
        title: 'No AI personalities available',
        optional: true,
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
              <h2>{setupError ? 'Setup status needs attention' : setupTasks.some((task) => !task.optional) ? 'Finish Twitch setup' : 'Optional AI setup'}</h2>
              <p className="section-copy">
                {setupError
                  ? 'Some setup details could not be loaded. Open Settings to review the configuration.'
                  : 'Twitch setup is required to connect. Gemini is optional and enables AI features.'}
              </p>
            </div>
            {!setupError && <span className="mini-badge runtime-badge">{setupTasks.filter((task) => !task.optional).length} required · {setupTasks.filter((task) => task.optional).length} optional</span>}
          </div>
          {setupError ? (
            <button className="secondary" onClick={() => onNavigate('Settings')}>Open Settings</button>
          ) : (
            <div className="setup-list">
              {setupTasks.map((task) => (
                <div className="setup-item" key={task.title}>
                  <div><strong>{task.title}</strong> <span className="mini-badge">{task.optional ? 'Optional' : 'Required for Twitch'}</span><p>{task.description}</p></div>
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
            {status ? twitchConnectionLabel(status.twitch_connection_state) : 'Loading…'}
          </h3>
          <p>{status?.twitch_connection_state === 'reconnecting'
            ? 'TwitchIO is restoring the chat connection automatically.'
            : status?.twitch_connection_state === 'auth_required'
              ? status.running
                ? 'Authorize the configured bot account in your browser.'
                : 'Start Bot again, then authorize the configured bot account.'
              : status?.twitch_connection_state === 'failed'
                ? 'The session stopped. Check Logs, then start the bot again.'
                : status?.running
                  ? 'Connection state from the active bot session.'
                  : 'Start the bot when you are ready to connect.'}</p>
          {status?.twitch_connection_state === 'auth_required' && (
            <button className="primary" disabled={Boolean(busy) || !status.running} onClick={onAuthorizeTwitch}>
              {busy === 'twitch:authorize' ? 'Opening…' : 'Authorize Twitch'}
            </button>
          )}
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
              <span><strong>AI command</strong><small>{!aiStatus?.available ? 'Unavailable · Gemini optional' : aiStatus?.enabled ? 'Enabled' : 'Disabled'}</small></span>
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
  const [navigationTarget, setNavigationTarget] = useState<{ id?: string } | null>(null)
  const main = useRef<HTMLElement | null>(null)
  const sidebar = useRef<HTMLElement | null>(null)
  const [status, setStatus] = useState<AppStatus | null>(null)
  const [aiStatus, setAIStatus] = useState<AIStatus | null>(null)
  const [error, setError] = useState('')
  const [actionBusy, setActionBusy] = useState('')

  const navigate = (nextSection: Section, targetId?: string) => {
    setSection(nextSection)
    setNavigationTarget({ id: targetId })
  }

  useLayoutEffect(() => {
    if (!navigationTarget || !main.current) return
    let frame = 0
    const observer = new MutationObserver(() => scheduleScroll())
    const scroll = () => {
      if (!navigationTarget.id) {
        main.current?.scrollTo({ top: 0 })
        window.scrollTo({ top: 0 })
        return
      }
      const target = document.getElementById(navigationTarget.id)
      // Editor pages stay mounted while hidden; loaded content can also move anchors.
      if (!target || !main.current?.contains(target)
        || target.closest('[hidden], [aria-busy="true"]') || !target.getClientRects().length) return
      observer.disconnect()
      main.current.style.setProperty('--sidebar-height', `${sidebar.current?.getBoundingClientRect().height ?? 0}px`)
      target.scrollIntoView({ block: 'start' })
    }
    const scheduleScroll = () => {
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(scroll)
    }
    if (navigationTarget.id) {
      observer.observe(main.current, { childList: true, subtree: true, attributes: true, attributeFilter: ['aria-busy'] })
    }
    scheduleScroll()
    return () => {
      observer.disconnect()
      window.cancelAnimationFrame(frame)
    }
  }, [section, navigationTarget])

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

  const authorizeTwitch = async () => {
    setError('')
    setActionBusy('twitch:authorize')
    try {
      const api = await waitForBridge()
      const result = await api.open_external_link('twitch_authorization')
      if (!result.ok) {
        throw new Error(result.error ?? 'Could not open Twitch authorization.')
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not open Twitch authorization.')
    } finally {
      setActionBusy('')
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar" ref={sidebar}>
        <div className="brand"><img className="brand-mark" src="./icon.png" alt="" /><div><strong>HeetKit</strong><small>Desktop control center for Twitch chat</small></div></div>
        <nav aria-label="Main navigation">
          {sections.map((item) => (
            <div className="nav-section" key={item}>
              <button
                type="button"
                className={section === item ? 'active' : ''}
                aria-current={section === item ? 'page' : undefined}
                aria-expanded={subsections[item] ? section === item : undefined}
                aria-controls={subsections[item] ? `nav-${item}` : undefined}
                onClick={() => navigate(item)}
              >{item}</button>
              {subsections[item] && (
                <ul className="sidebar-subnav" id={`nav-${item}`} hidden={section !== item}>
                  {subsections[item].map((child) => (
                    <li key={child.targetId}>
                      <button
                        type="button"
                        className={navigationTarget?.id === child.targetId ? 'active' : ''}
                        aria-current={section === item && navigationTarget?.id === child.targetId ? 'location' : undefined}
                        onClick={() => navigate(item, child.targetId)}
                      >{child.label}</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </nav>
      </aside>
      <main ref={main}>
        <header><div><p className="eyebrow">CONTROL CENTER</p><h1>{section}</h1></div></header>
        <FeedbackToast error={error} onDismiss={() => setError('')} />
        {section === 'Dashboard' && (
          <Dashboard
            status={status}
            aiStatus={aiStatus}
            busy={actionBusy}
            onChangeBotState={(shouldRun) => void changeBotState(shouldRun)}
            onChangeAIState={(kind, enabled) => void changeAIState(kind, enabled)}
            onAuthorizeTwitch={() => void authorizeTwitch()}
            onNavigate={navigate}
          />
        )}
        <div hidden={section !== 'Commands'}><CommandsPage active={section === 'Commands'} /></div>
        <div hidden={section !== 'Filters'}><FiltersPage active={section === 'Filters'} /></div>
        <div hidden={section !== 'AI'}><AIPage active={section === 'AI'} onOpenSettings={() => navigate('Settings', 'credential-settings')} /></div>
        {section === 'Logs' && <LogsPage />}
        <div hidden={section !== 'Settings'}><SettingsPage active={section === 'Settings'} status={status} /></div>
        {section === 'About' && <AboutPage />}
      </main>
    </div>
  )
}
