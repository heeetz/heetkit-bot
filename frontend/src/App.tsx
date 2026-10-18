import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  type AIProviderSettings,
  type AIStatus,
  type AppStatus,
  type CredentialInfo,
  type LogEntry,
  type TwitchConnectionSettings,
  getBrowserSetup,
  getBrowserSnapshot,
  isBrowserMode,
  twitchAuthorizationLabel,
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
import { Select } from './components/Select'
import Switch from './components/Switch'
import HelpTip from './components/HelpTip'
import BrowserSession from './components/BrowserSession'
import './styles.css'

const sections = ['Dashboard', 'Commands', 'Filters', 'AI', 'Logs', 'Settings', 'About'] as const
type Section = (typeof sections)[number]

const subsections: Partial<Record<Section, { label: string; targetId: string }[]>> = {
  Commands: [
    { label: 'Your commands', targetId: 'custom-commands' },
    { label: 'Built-in commands', targetId: 'builtin-commands' },
    { label: 'Removed commands', targetId: 'removed-commands' },
    { label: 'Administrative commands', targetId: 'administrative-commands' },
    { label: 'Advanced: reset all built-ins', targetId: 'advanced-command-reset' },
  ],
  Filters: [
    { label: 'Filter Tester', targetId: 'filter-tester' },
    { label: 'Blocked words', targetId: 'filters-words' },
    { label: 'Blocked phrases', targetId: 'filters-phrases' },
    { label: 'Regex patterns', targetId: 'filters-patterns' },
  ],
  AI: [
    { label: 'State', targetId: 'ai-runtime' },
    { label: 'Playground', targetId: 'ai-playground' },
    { label: 'Personalities', targetId: 'ai-personalities' },
    { label: 'Profile instructions', targetId: 'ai-profile-instructions' },
    { label: 'Response language', targetId: 'ai-language' },
    { label: 'Models', targetId: 'ai-models' },
    { label: 'AI access', targetId: 'ai-blocked-users' },
    { label: 'Built-in restrictions', targetId: 'ai-shared-instructions' },
  ],
  Settings: [
    { label: 'Twitch connection', targetId: 'twitch-settings' },
    { label: 'Gemini API key', targetId: 'credential-settings' },
    { label: 'Desktop behavior', targetId: 'desktop-settings' },
    { label: 'Data & diagnostics', targetId: 'profile-location-settings' },
  ],
}

interface DashboardSetup {
  twitch: TwitchConnectionSettings
  credentials: CredentialInfo[]
  aiProvider: AIProviderSettings
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
  onNavigate: (section: Extract<Section, 'AI' | 'Settings' | 'Logs'>, targetId?: string) => void
  busy: string
}) {
  const [setup, setSetup] = useState<DashboardSetup | null>(null)
  const [setupError, setSetupError] = useState('')

  useEffect(() => {
    let active = true
    const loadSetup = async () => {
      try {
        const api = await waitForBridge()
        const serverSetup = isBrowserMode() ? await getBrowserSetup() : null
        const [twitchResponse, credentialResponse, aiResponse] = serverSetup ? [
          { ok: serverSetup.ok, settings: serverSetup.twitch },
          { ok: serverSetup.ok, credentials: serverSetup.credentials },
          { ok: serverSetup.ok, settings: serverSetup.aiProvider },
        ] : await Promise.all([
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
  const twitchCredential = setup?.credentials.find(
    (credential) => credential.name === 'twitch_client_secret',
  )
  const twitchTargetReady = Boolean(
    setup?.twitch.target_channel.trim() && setup.twitch.target_channel_user_id.trim()
      && setup.twitch.client_id.trim() && setup.twitch.bot_username.trim() && setup.twitch.bot_user_id.trim(),
  )
  const needsTwitchSetup = Boolean(setup && (!twitchTargetReady || !twitchCredential?.configured))
  const pendingRestart = Boolean(setup?.twitch.requires_restart)
  const pendingReconnect = Boolean(setup?.twitch.requires_reconnect && !pendingRestart && !needsTwitchSetup)
  const connectionState = status?.twitch_connection_state
  const connectionHint = !status || !setup || needsTwitchSetup || pendingRestart
    ? ''
    : connectionState === 'auth_required'
      ? isBrowserMode() ? 'Authorize the configured bot account on the server, then restart the bot.' : status.running
        ? 'Sign in as the configured bot account.'
        : 'Start Bot again to authorize Twitch.'
      : connectionState === 'connecting'
        ? 'Waiting for Twitch…'
        : connectionState === 'reconnecting'
          ? 'Connection lost. Reconnecting automatically.'
          : connectionState === 'failed'
            ? status.running ? 'Check Logs, then stop and start the bot.' : 'Check Logs, then Start Bot again.'
            : connectionState === 'connected'
              ? ''
              : 'Start Bot to connect.'

  return (
    <section className="dashboard-layout">
      <article className="card dashboard-hero">
        <div className="dashboard-hero-status">
          <span className={`status-dot ${status?.running ? 'online' : ''}`} />
          <div>
            <div className="dashboard-label">Bot session<HelpTip label="Bot session">Running means the bot session has started. It can still be waiting for authorization or reconnecting. Connected below confirms Twitch chat readiness.</HelpTip></div>
            <h2>{statusLabel}</h2>
          </div>
        </div>
        <button
          className={status?.running ? 'secondary' : 'primary'}
          disabled={!status || Boolean(busy) || (!status.running && (pendingRestart || needsTwitchSetup))}
          onClick={() => onChangeBotState(!status?.running)}
        >
          {busy === 'bot' ? 'Working…' : status?.running ? 'Stop Bot' : 'Start Bot'}
        </button>
      </article>
      {(needsTwitchSetup || pendingRestart || pendingReconnect || setupError) && (
        <article className="card dashboard-notice setup-card">
          <div>
            <h2>{setupError ? 'Setup status needs attention' : needsTwitchSetup ? 'Finish Twitch setup' : pendingRestart ? 'Restart to apply Twitch setup' : 'Channel change pending'}</h2>
            <p>{setupError || (isBrowserMode() ? 'Configure Twitch identity, authorization and credentials on the server, then restart it to apply changes.' : needsTwitchSetup
              ? 'Save the client ID, bot account, channel and client secret in Settings, then restart the application.'
              : pendingRestart
                ? 'Restart the application to apply the saved client ID, bot identity or secret.'
                : status?.running
                  ? 'Use Save & reconnect in Settings to switch the running bot to the saved channel.'
                  : 'Use Save & apply in Settings to switch to the saved channel.')}</p>
          </div>
          <button className="secondary" onClick={() => onNavigate('Settings', 'twitch-settings')}>
            {needsTwitchSetup ? 'Configure Twitch' : 'Review Twitch setup'}
          </button>
        </article>
      )}
      <div className="dashboard-grid">
        <article className="card dashboard-card">
          <div className="dashboard-label">Twitch connection<HelpTip label="Twitch connection">{status && setup ? `Authorization: ${twitchAuthorizationLabel(status.twitch_connection_state, setup.twitch.oauth_token_available)}. ` : ''}Saved tokens are checked when connecting. A token cache alone does not confirm authorization. Gemini is optional and is not needed for Twitch commands.</HelpTip></div>
          <h3 className={status?.twitch_connected ? 'success-text' : ''}>
            {needsTwitchSetup ? 'Not configured' : status ? twitchConnectionLabel(status.twitch_connection_state) : 'Loading…'}
          </h3>
          {connectionHint && <p>{connectionHint}</p>}
          {connectionState === 'auth_required' && !isBrowserMode() && (
            <button className="primary" disabled={Boolean(busy) || !status?.running || pendingRestart || needsTwitchSetup} onClick={onAuthorizeTwitch}>
              {busy === 'twitch:authorize' ? 'Opening…' : 'Authorize Twitch'}
            </button>
          )}
          {(connectionState === 'failed' || connectionState === 'reconnecting') && <button className="secondary" onClick={() => onNavigate('Logs')}>Open Logs</button>}
        </article>
        <article className="card dashboard-card">
          <div className="dashboard-label">Channel · Bot account</div>
          <h3>{status?.channel || setup?.twitch.target_channel || 'Not configured'}</h3>
          <p>Bot: {status?.account || setup?.twitch.bot_username || 'Not configured'}</p>
        </article>
        <article className="card dashboard-card">
          <div className="dashboard-label">Session uptime<HelpTip label="Session uptime">Time since the current bot session started, including time spent waiting for authorization or reconnecting.</HelpTip></div>
          <h3 className="metric">{status ? formatUptime(status.uptime_seconds) : '—'}</h3>
        </article>
      </div>
      <article className="card dashboard-ai-card">
        <div className="dashboard-card-heading">
          <div className="dashboard-label">AI controls<HelpTip label="AI controls">Gemini is optional; other Twitch commands work without it. The AI command switch saves immediately across restarts and is shared with AI and Commands. Filter Tester works while stopped. AI Playground also works while stopped with Gemini configured. Turning memory off stops new storage and use without erasing previous exchanges.</HelpTip></div>
          <button className="secondary" onClick={() => onNavigate('AI', 'ai-runtime')}>Manage AI</button>
        </div>
        <div className="dashboard-ai-summary">
          <span>{aiStatus ? aiStatus.available ? aiStatus.model || setup?.aiProvider.selected_model || 'Model not selected' : 'AI unavailable' : 'Loading…'}</span>
          {aiStatus?.available && <span>Personality: {aiStatus.active_personality || 'Not selected'}</span>}
        </div>
        <div className="dashboard-switches">
          <Switch
            checked={aiStatus?.enabled ?? false}
            disabled={!aiStatus || Boolean(busy)}
            ariaLabel="Enable AI command"
            onCheckedChange={(enabled) => onChangeAIState('enabled', enabled)}
          >
            <span><strong>AI command</strong><small>{aiStatus ? aiStatus.enabled ? 'Enabled' : 'Disabled' : 'Loading…'}</small></span>
          </Switch>
          <Switch
            checked={aiStatus?.memory_enabled ?? false}
            disabled={!aiStatus || Boolean(busy)}
            ariaLabel="Enable conversation memory"
            onCheckedChange={(enabled) => onChangeAIState('memory', enabled)}
          >
            <span><strong>Conversation memory</strong><small>{aiStatus ? aiStatus.memory_enabled ? 'Enabled' : 'Disabled' : 'Loading…'}</small></span>
          </Switch>
        </div>
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
      if (isBrowserMode() && document.hidden) {
        timer = window.setTimeout(() => void refresh(), 5000)
        return
      }
      try {
        const api = await waitForBridge()
        if (!active) return
        const response = await api.get_recent_logs(cursor.current, 200)
        if (active && response.next_after_id !== undefined) cursor.current = response.next_after_id
        if (active && response.entries.length > 0) {
          cursor.current = Math.max(cursor.current, response.entries.at(-1)?.id ?? 0)
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
          timer = window.setTimeout(() => void refresh(), isBrowserMode() ? 5000 : 1000)
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
        <div><p className="label">{isBrowserMode() ? 'SERVER LIFECYCLE LOGS' : 'LIVE APPLICATION LOGS'}</p><h2>Recent activity</h2></div>
        <span className="read-only-badge">{entries.length} / 500</span>
      </div>
      <div className="log-toolbar">
        <label>
          Level
          <Select
            value={level}
            onChange={(value) => setLevel(value as typeof level)}
            options={logLevels.map((item) => ({ value: item, label: item }))}
          />
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

function ManagementApp() {
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
      const details = target.closest<HTMLDetailsElement>('details')
      if (details && !details.open) {
        details.open = true
        return
      }
      const accordion = target.closest<HTMLElement>('[data-accordion-id]')
      if (accordion && accordion.dataset.accordionOpen !== 'true') {
        accordion.dispatchEvent(new CustomEvent('accordion:open', { bubbles: true }))
        return
      }
      observer.disconnect()
      main.current.style.setProperty('--sidebar-height', `${sidebar.current?.getBoundingClientRect().height ?? 0}px`)
      target.scrollIntoView({ block: 'start' })
    }
    const scheduleScroll = () => {
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(scroll)
    }
    if (navigationTarget.id) {
      observer.observe(main.current, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['aria-busy', 'data-accordion-open', 'hidden', 'open'],
      })
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
      if (isBrowserMode() && document.hidden) {
        timer = window.setTimeout(() => void refresh(api), 5000)
        return
      }
      try {
        const snapshot = isBrowserMode() ? await getBrowserSnapshot() : null
        const [nextStatus, nextAIStatus] = snapshot ? [snapshot.status, snapshot.ai_status] : await Promise.all([
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
          timer = window.setTimeout(() => void refresh(api), isBrowserMode() ? 5000 : 1500)
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

  const synchronizeAIEnabled = (enabled: boolean) => {
    setAIStatus((current) => current ? { ...current, enabled } : current)
  }

  return (
    <div className="app-shell">
      <aside className="sidebar" ref={sidebar}>
        <div className="brand"><img className="brand-mark" src="./icon.png" alt="" /><div><strong>HeetKit</strong><small>Twitch bot controls</small></div></div>
        <nav aria-label="Main navigation">
          {sections.map((item) => (
            <div className="nav-section" key={item}>
              <button
                type="button"
                className={section === item ? 'active' : ''}
                aria-current={section === item ? 'page' : undefined}
                aria-expanded={subsections[item] && !(isBrowserMode() && item === 'Settings') ? section === item : undefined}
                aria-controls={subsections[item] && !(isBrowserMode() && item === 'Settings') ? `nav-${item}` : undefined}
                onClick={() => navigate(item)}
              >{item}</button>
              {subsections[item] && !(isBrowserMode() && item === 'Settings') && (
                <ul className="sidebar-subnav" id={`nav-${item}`} hidden={section !== item}>
                  {subsections[item].filter((child) => !isBrowserMode() || child.targetId !== 'ai-playground').map((child) => (
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
        <div className="page-content">
          <header><h1>{section}</h1></header>
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
          <div hidden={section !== 'Commands'}><CommandsPage active={section === 'Commands'} revealCommand={navigationTarget?.id === 'command-editor-ask' ? 'ask' : undefined} onAIEnabledChanged={synchronizeAIEnabled} /></div>
          <div hidden={section !== 'Filters'}><FiltersPage active={section === 'Filters'} /></div>
          <div hidden={section !== 'AI'}><AIPage active={section === 'AI'} onOpenSettings={() => navigate('Settings', isBrowserMode() ? 'twitch-settings' : 'credential-settings')} onOpenPlayground={() => navigate('AI', 'ai-playground')} onOpenAsk={() => navigate('Commands', 'command-editor-ask')} onAIEnabledChanged={synchronizeAIEnabled} /></div>
          {section === 'Logs' && <LogsPage />}
          <div hidden={section !== 'Settings'}><SettingsPage active={section === 'Settings'} status={status} onReturnToAI={() => navigate('AI', 'ai-playground')} /></div>
          {section === 'About' && <AboutPage />}
        </div>
      </main>
    </div>
  )
}

export default function App() {
  return isBrowserMode() ? <BrowserSession><ManagementApp /></BrowserSession> : <ManagementApp />
}
