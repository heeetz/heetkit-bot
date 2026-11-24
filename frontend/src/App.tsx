import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import SetupChecklist from './components/SetupChecklist'
import {
  type AIProviderSettings,
  type AIStatus,
  type AppStatus,
  type BrowserOperationMode,
  type CredentialInfo,
  type LogEntry,
  type TwitchConnectionSettings,
  getBrowserSetup,
  getBrowserSnapshot,
  isBrowserMode,
  setBrowserOperationMode,
  twitchConnectionLabel,
  waitForBridge,
} from './bridge'
import CommandsPage from './pages/CommandsPage'
import AIPage from './pages/AIPage'
import AnalyticsPage from './pages/AnalyticsPage'
import FiltersPage from './pages/FiltersPage'
import SettingsPage from './pages/SettingsPage'
import AboutPage from './pages/AboutPage'
import FeedbackToast from './components/FeedbackToast'
import LogEventSummary, { logEventClassNames } from './components/LogEventSummary'
import { Select } from './components/Select'
import Switch from './components/Switch'
import HelpTip from './components/HelpTip'
import BrowserSession from './components/BrowserSession'
import DesktopStartup from './components/DesktopStartup'
import Confirmation from './components/Confirmation'
import { RecentCommands, StreamActivity } from './components/DashboardActivity'
import DashboardQuickControls from './components/DashboardQuickControls'
import { restartDesktop } from './desktopRestart'
import useUpdateCheck from './useUpdateCheck'
import LanguageSwitcher from './components/LanguageSwitcher'
import { shell } from './i18n/app'
import { common } from './i18n/common'
import { dashboard } from './i18n/dashboard'
import { logs as logsCatalog } from './i18n/logs'
import { catalogFor, useCatalog, useI18n } from './i18n/core'
import './styles.css'

const sections = ['Dashboard', 'Commands', 'Filters', 'AI', 'Logs', 'Analytics', 'Settings', 'About'] as const
type Section = (typeof sections)[number]

type SubsectionId = keyof typeof shell.en.subsections
const subsections: Partial<Record<Section, SubsectionId[]>> = {
  Commands: ['command-list', 'announcements', 'command-restrictions', 'optout-management', 'advanced-command-reset'],
  AI: ['ai-models', 'ai-behavior', 'ai-playground'],
  Analytics: ['analytics-trends', 'analytics-chatters', 'analytics-breakdown', 'analytics-collection'],
  Settings: ['desktop-settings', 'twitch-settings', 'interface-settings', 'configuration-transfer', 'profile-location-settings'],
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

const browserOperationModeValues: BrowserOperationMode[] = ['always_on', 'stream_only', 'manual', 'disabled']

function Dashboard({ status, aiStatus, onChangeBotState, onChangeAIState, onRefreshAIStatus, onAuthorizeTwitch, onChangeBrowserMode, onNavigate, onOpenUpdate, busy }: {
  status: AppStatus | null
  aiStatus: AIStatus | null
  onChangeBotState: (shouldRun: boolean) => void
  onChangeAIState: (kind: 'enabled' | 'memory', enabled: boolean) => void
  onRefreshAIStatus: () => Promise<void>
  onAuthorizeTwitch: () => void
  onChangeBrowserMode: (mode: BrowserOperationMode) => void
  onNavigate: (section: Extract<Section, 'AI' | 'Analytics' | 'Settings' | 'Logs' | 'Commands'>, targetId?: string) => void
  onOpenUpdate?: () => void
  busy: string
}) {
  const text = useCatalog(dashboard)
  const commonText = useCatalog(common)
  const { fmt, time } = useI18n()
  const operationText = text.operation
  const browserOperationModes = browserOperationModeValues.map((value) => ({ value, label: operationText.modes[value] }))
  const [setup, setSetup] = useState<DashboardSetup | null>(null)
  const [setupError, setSetupError] = useState('')
  const [restartError, setRestartError] = useState('')
  const [restarting, setRestarting] = useState(false)
  const connectionState = status?.twitch_connection_state

  const restartTwitch = async () => {
    setRestartError('')
    setRestarting(true)
    try {
      if (await restartDesktop()) return
    } catch (reason) {
      setRestartError(reason instanceof Error ? reason.message : catalogFor(dashboard).restartFailed)
    }
    setRestarting(false)
  }

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
          throw new Error(twitchResponse.error ?? catalogFor(dashboard).setupUnavailable.twitch)
        }
        if (!credentialResponse.ok || !credentialResponse.credentials) {
          throw new Error(credentialResponse.error ?? catalogFor(dashboard).setupUnavailable.credentials)
        }
        if (!aiResponse.ok || !aiResponse.settings) {
          throw new Error(aiResponse.error ?? catalogFor(dashboard).setupUnavailable.ai)
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
          setSetupError(reason instanceof Error ? reason.message : catalogFor(dashboard).setupUnavailable.any)
        }
      }
    }
    void loadSetup()
    return () => { active = false }
  }, [connectionState])

  const twitchCredential = setup?.credentials.find(
    (credential) => credential.name === 'twitch_client_secret',
  )
  const twitchTargetReady = Boolean(
    setup?.twitch.target_channel.trim() && setup.twitch.target_channel_user_id.trim()
      && setup.twitch.client_id.trim() && setup.twitch.bot_username.trim() && setup.twitch.bot_user_id.trim(),
  )
  const needsTwitchSetup = Boolean(setup && (!twitchTargetReady || !twitchCredential?.configured))
  const aiConfigured = Boolean(setup?.credentials.some((credential) => credential.configured
    && (credential.name === 'gemini_api_key' || credential.name === 'deepseek_api_key' || credential.name === 'openai_api_key')))
  const pendingRestart = !isBrowserMode() && Boolean(setup?.twitch.requires_restart || setup?.twitch.requires_cleanup_restart)
  const pendingReconnect = Boolean(setup?.twitch.requires_reconnect && !pendingRestart && !needsTwitchSetup)
  const needsApply = Boolean(setup?.twitch.requires_restart || setup?.twitch.requires_reconnect)
  const operation = isBrowserMode() ? status?.operation : undefined
  // Server: Stop is a saved manual stop in any mode; Start clears it. Desktop follows the session.
  const botActive = operation
    ? !operation.paused && !operation.error && (operation.mode !== 'manual' || operation.desired_running)
    : Boolean(status?.running)
  const streamStatus = operation?.stream_status === 'unknown' && operation.last_known_stream_status
    ? operation.last_known_stream_status : operation?.stream_status
  const checkedAt = operation?.last_checked_at ? new Date(operation.last_checked_at) : null
  const lifecycleBusy = Boolean(busy) || Boolean(operation?.pending)
  const recovery = status?.twitch_recovery
  const recoveryCause = recovery?.cause && Object.hasOwn(text.recoveryCause, recovery.cause)
    ? text.recoveryCause[recovery.cause as keyof typeof text.recoveryCause] : ''
  const recoveryHint = recovery
    ? fmt(text.recovery, {
      reason: recovery.reason === 'retry_wait' ? text.recoveryReason.retry_wait : recovery.reason === 'sdk_recovery' ? text.recoveryReason.sdk_recovery : text.recoveryReason.connecting,
      cause: recoveryCause, attempt: recovery.attempt, elapsed: recovery.elapsed_seconds,
    }) + (recovery.next_retry_seconds == null ? '' : fmt(text.nextRetry, { seconds: recovery.next_retry_seconds }))
    : ''
  const connectionHint = !status || !setup || needsTwitchSetup || pendingRestart
    ? ''
    : connectionState === 'auth_required'
      ? isBrowserMode()
        ? operation?.mode === 'disabled' ? text.hints.serverAuthDisabled : text.hints.serverAuth
        : status.running ? text.hints.signInBot : text.hints.startToAuthorize
      : recoveryHint ? recoveryHint
      : connectionState === 'connecting'
        ? text.hints.waiting
        : connectionState === 'reconnecting'
          ? isBrowserMode() ? text.hints.serverReconnecting : text.hints.reconnecting
          : connectionState === 'failed'
            ? isBrowserMode()
              ? operation?.mode === 'disabled' ? text.hints.disabled : operation?.mode === 'manual' ? text.hints.manualFailed : text.hints.automaticFailed
              : status.running ? text.hints.runningFailed : text.hints.failed
            : connectionState === 'connected'
              ? ''
              : isBrowserMode()
                ? operation?.mode === 'disabled' ? text.hints.disabled : operation?.paused ? text.hints.paused : operation?.mode === 'manual' ? text.hints.manualReady : text.hints.automaticWaiting
                : text.hints.startToConnect

  return (
    <section className="dashboard-layout">
      <article className="card dashboard-hero" aria-label={text.botSession}>
        <div className="dashboard-session-main">
          <div className="dashboard-session-fields">
            <div className="dashboard-connection">
              <div className="dashboard-label">{text.twitchConnection}</div>
              <h2><span aria-hidden="true" className={`status-dot ${status?.twitch_connected ? 'online' : ''}`} />
                {needsTwitchSetup ? commonText.notConfigured : status ? twitchConnectionLabel(status.twitch_connection_state) : commonText.loading}
              </h2>
              {operation && <div className="dashboard-stream-status">
                <div className="dashboard-label">{operationText.broadcasterStatus}</div>
                <strong><span aria-hidden="true" className={`status-dot ${streamStatus === 'live' ? 'online' : ''}`} />
                  {operationText.stream[streamStatus ?? 'unknown']}
                  {checkedAt && !Number.isNaN(checkedAt.getTime()) && <span className="dashboard-checked">
                    {fmt(operationText.checkedAt, { time: time(checkedAt, { hour: '2-digit', minute: '2-digit' }) })}</span>}
                </strong>
              </div>}
            </div>
            <div><div className="dashboard-label">{text.channel}</div><strong>{status?.channel || setup?.twitch.target_channel || commonText.notConfigured}</strong></div>
            <div><div className="dashboard-label">{text.botAccount}</div><strong>{status?.account || setup?.twitch.bot_username || commonText.notConfigured}</strong></div>
            <div><div className="dashboard-label">{text.sessionUptime}</div><strong className="metric">{status ? formatUptime(status.uptime_seconds) : '—'}</strong></div>
          </div>
          <div className="dashboard-hero-actions">
            {onOpenUpdate && <button type="button" className="secondary dashboard-update" onClick={onOpenUpdate}>{text.updateAvailable}</button>}
            {operation?.mode !== 'disabled' && <button
              className={`dashboard-bot-toggle ${botActive ? 'secondary' : 'primary'}`}
              disabled={!status || lifecycleBusy || (!botActive && (pendingRestart || needsTwitchSetup))}
              onClick={() => onChangeBotState(!botActive)}
            >
              {busy === 'bot' ? commonText.working : operation?.pending ? text.reconciling : botActive ? text.stopBot : text.startBot}
            </button>}
            {operation && <div className="dashboard-mode">
              <Select id="operation-mode" className="dashboard-mode-select" value={operation.mode} aria-label={operationText.label}
                options={browserOperationModes} disabled={busy === 'operation-mode'}
                onChange={(mode) => onChangeBrowserMode(mode as BrowserOperationMode)} />
              <HelpTip label={operationText.label}>
                {operationText.descriptions[operation.mode]} {operationText.pauseNote}
                {operation.mode === 'stream_only' && <> {operationText.streamChecks}</>}
              </HelpTip>
            </div>}
          </div>
        </div>
        {(connectionHint || connectionState === 'failed' || connectionState === 'reconnecting'
          || (connectionState === 'auth_required' && !isBrowserMode())) && <div className="dashboard-connection-actions">
          {connectionHint && <p>{status?.running && connectionState !== 'connected' && <strong>{text.sessionRunning}</strong>}{connectionHint}</p>}
          {connectionState === 'auth_required' && !isBrowserMode() && (
            <button className="primary" disabled={Boolean(busy) || !status?.running || pendingRestart || needsTwitchSetup} onClick={onAuthorizeTwitch}>
              {busy === 'twitch:authorize' ? text.opening : text.authorizeTwitch}
            </button>
          )}
          {(connectionState === 'failed' || connectionState === 'reconnecting') && <button className="secondary" onClick={() => onNavigate('Logs')}>{text.openLogs}</button>}
        </div>}
      </article>
      {setup && <SetupChecklist twitchConfigured={!needsTwitchSetup} twitchAuthorized={Boolean(setup.twitch.saved_bot_authorization)} twitchPending={needsApply} aiConfigured={aiConfigured} onTwitch={() => onNavigate('Settings', 'twitch-settings')} onAI={() => onNavigate('AI', 'ai-models')} />}
      {(needsTwitchSetup || pendingRestart || pendingReconnect || setupError) && (
        <article className="card dashboard-notice setup-card">
          <div>
            <h2>{setupError ? text.notice.attention : pendingRestart ? text.notice.restart : needsTwitchSetup ? text.notice.finish : text.notice.pending}</h2>
            <p>{setupError || (pendingRestart
              ? setup?.twitch.requires_restart ? text.notice.restartIdentity : text.notice.restartCleanup
              : isBrowserMode() ? text.notice.serverSetup
                : needsTwitchSetup ? text.notice.enterSetup
                  : status?.running
                  ? text.notice.reconnect
                  : text.notice.apply)}</p>
            {restartError && <p className="inline-error" role="alert">{restartError}</p>}
          </div>
          <div className="row-actions">
            <button className="secondary" onClick={() => onNavigate('Settings', 'twitch-settings')}>
              {needsTwitchSetup ? text.notice.configure : text.notice.review}
            </button>
            {pendingRestart && <button className="primary" disabled={restarting || Boolean(busy)} onClick={() => void restartTwitch()}>{restarting ? text.notice.restarting : text.notice.restartNow}</button>}
          </div>
        </article>
      )}
      <DashboardQuickControls aiStatus={aiStatus} onAIStatusChanged={onRefreshAIStatus}
        onOpenAISetup={() => onNavigate('AI', 'ai-models')} onOpenRestrictions={() => onNavigate('Commands', 'command-restrictions')} />
      <div className="dashboard-panels">
        <article className="card dashboard-ai-card">
          <div className="dashboard-card-heading">
            <h2>{text.ai.title}</h2>
          </div>
          {aiStatus && !aiStatus.available && <p className="dashboard-ai-summary">{text.ai.unavailable}</p>}
          <div className="dashboard-switches">
            <Switch checked={aiStatus?.enabled ?? false} disabled={!aiStatus || Boolean(busy)}
              ariaLabel={text.ai.enableCommand} onCheckedChange={(enabled) => onChangeAIState('enabled', enabled)}>{text.ai.command}</Switch>
            <Switch checked={aiStatus?.memory_enabled ?? false} disabled={!aiStatus || Boolean(busy)}
              ariaLabel={text.ai.enableMemory} onCheckedChange={(enabled) => onChangeAIState('memory', enabled)}>{text.ai.memory}</Switch>
          </div>
          <div className="dashboard-ai-actions">
            <button className="secondary" onClick={() => onNavigate('AI', 'ai-playground')}>{text.ai.openPlayground}</button>
            <button className="secondary" onClick={() => onNavigate('AI', 'ai-behavior')}>{text.ai.manage}</button>
          </div>
        </article>
        <StreamActivity key={status?.leaderboard_channel_id ?? ''} channel={status?.leaderboard_channel_id}
          onOpenAnalytics={() => onNavigate('Analytics', 'analytics-chatters')} />
      </div>
      <RecentCommands onOpenLogs={() => onNavigate('Logs')} />
    </section>
  )
}

const logLevels = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const

function boundedActivity(entries: LogEntry[]) {
  const retained: LogEntry[] = []
  let bytes = 0
  const encoder = new TextEncoder()
  for (const entry of entries.slice(-500).reverse()) {
    const size = encoder.encode(JSON.stringify(entry)).length
    if (size > 16 * 1024) continue
    if (bytes + size > 1024 * 1024) break
    retained.push(entry)
    bytes += size
  }
  return retained.reverse()
}

function LogsPage() {
  const text = useCatalog(logsCatalog)
  const { fmt, plural, time } = useI18n()
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [level, setLevel] = useState<(typeof logLevels)[number]>('ALL')
  const [search, setSearch] = useState('')
  const [command, setCommand] = useState('')
  const [outcome, setOutcome] = useState('ALL')
  const [source, setSource] = useState('ALL')
  const [since, setSince] = useState('')
  const [until, setUntil] = useState('')
  const [requestId, setRequestId] = useState('')
  const [exportEntries, setExportEntries] = useState<LogEntry[] | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportNotice, setExportNotice] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const [error, setError] = useState('')
  const cursor = useRef(0)
  const bottom = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let active = true
    let initial = true
    let timer = 0
    const refresh = async () => {
      if (isBrowserMode() && document.hidden) {
        timer = window.setTimeout(() => void refresh(), 5000)
        return
      }
      try {
        const api = await waitForBridge()
        if (!active) return
        const response = await api.get_recent_logs(cursor.current, 200, initial)
        if (!active) return
        if (response.ok === false) throw new Error(response.error || catalogFor(logsCatalog).loadFailed)
        const fresh = response.entries.filter((entry) => {
          if (entry.id <= cursor.current) return false
          cursor.current = entry.id
          return true
        })
        cursor.current = Math.max(cursor.current, response.next_after_id ?? 0)
        if (fresh.length) setEntries((current) => boundedActivity([...current, ...fresh]))
        initial = false
        setError('')
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : catalogFor(logsCatalog).loadFailed)
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
      || entry.text?.toLowerCase().includes(normalizedSearch)
      || entry.event_kind?.toLowerCase().includes(normalizedSearch)
      || Object.values(entry.context).some(
        (value) => String(value).toLowerCase().includes(normalizedSearch),
      )
    const matchesCommand = !command || [entry.context.command, entry.context.command_id, entry.context.invoked_name]
      .some((value) => String(value ?? '').toLowerCase().includes(command.trim().toLowerCase().replace(/^!/, '')))
    const timestamp = Date.parse(entry.timestamp)
    return matchesLevel && matchesSearch && matchesCommand
      && (outcome === 'ALL' || entry.context.outcome === outcome)
      && (source === 'ALL' || (entry.context.source ?? entry.source) === source)
      && (!since || timestamp >= Date.parse(since))
      && (!until || timestamp <= Date.parse(until))
      && (!requestId || entry.context.request_id === requestId)
  })

  const filterOptions = (values: string[]) => [{ value: 'ALL', label: text.all },
    ...[...new Set(values)].sort().map((value) => ({ value, label: value.replaceAll('_', ' ') }))]

  const downloadActivity = async () => {
    const snapshot = exportEntries
    setExportEntries(null)
    setExportNotice('')
    setExporting(true)
    try {
      if (!isBrowserMode()) {
        const api = await waitForBridge()
        const result = await api.export_activity((snapshot ?? []).map((entry) => entry.id))
        if (!result.ok) throw new Error(result.error ?? text.exportFailed)
        setExportNotice(result.cancelled ? text.exportCancelled : text.exportSaved)
        return
      }
      const url = URL.createObjectURL(new Blob([JSON.stringify({ exported_at: new Date().toISOString(), entries: snapshot }, null, 2)], { type: 'application/json' }))
      const link = document.createElement('a')
      link.href = url
      link.download = 'heetkit-activity.json'
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      setExportNotice(text.exportDone)
    } catch (reason) {
      setExportNotice(reason instanceof Error ? reason.message : text.exportFailed)
    } finally {
      setExporting(false)
    }
  }

  useEffect(() => {
    if (autoScroll) {
      bottom.current?.scrollIntoView({ block: 'nearest' })
    }
  }, [autoScroll, visibleEntries.length, visibleEntries.at(-1)?.id])

  return (
    <section className="card logs-card">
      <div className="section-heading">
        <div><p className="label">{text.eyebrow}</p><h2>{text.title}</h2></div>
        <div className="row-actions">
          <HelpTip label={text.helpLabel}>
            <ul>{text.help.map((item) => <li key={item}>{item}</li>)}</ul>
          </HelpTip>
          <span className="read-only-badge">{entries.length} / 500</span>
        </div>
      </div>
      <div className="log-toolbar">
        <label>
          {text.level}
          <Select
            value={level}
            onChange={(value) => setLevel(value as typeof level)}
            options={logLevels.map((item) => ({ value: item, label: item === 'ALL' ? text.all : item }))}
          />
        </label>
        <label>{text.command}<input value={command} onChange={(event) => setCommand(event.target.value)} placeholder={text.commandPlaceholder} /></label>
        <label>{text.outcome}<Select value={outcome} onChange={setOutcome} options={filterOptions(entries.flatMap((entry) => entry.context.outcome ? [String(entry.context.outcome)] : []))} /></label>
        <label>{text.source}<Select value={source} onChange={setSource} options={filterOptions(entries.map((entry) => String(entry.context.source ?? entry.source)))} /></label>
        <label>{text.from}<input type="datetime-local" value={since} onChange={(event) => setSince(event.target.value)} /></label>
        <label>{text.until}<input type="datetime-local" value={until} onChange={(event) => setUntil(event.target.value)} /></label>
        <label className="search-field">
          {text.search}
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={text.searchPlaceholder}
          />
        </label>
        <Switch
          className="checkbox-field"
          checked={autoScroll}
          onCheckedChange={setAutoScroll}
        >
          {text.autoScroll}
        </Switch>
        <button className="secondary" disabled={entries.length === 0} aria-describedby="log-action-help" onClick={() => setEntries([])}>{text.clearView}</button>
        <button className="secondary" disabled={exporting || !visibleEntries.length} aria-describedby="log-action-help" onClick={() => setExportEntries([...visibleEntries])}>{text.export}</button>
      </div>
      <p className="log-policy" id="log-action-help">{text.actionHelp}</p>
      {requestId && <p className="log-policy">{fmt(text.linkedRequest, { id: requestId })}<button className="secondary" onClick={() => setRequestId('')}>{text.allRequests}</button></p>}
      {exportEntries && <Confirmation title={text.exportTitle} description={plural(text.exportDescription, exportEntries.length)} onConfirm={() => void downloadActivity()} onCancel={() => setExportEntries(null)} />}
      {exportNotice && <p className="log-policy" role="status">{exportNotice}</p>}
      {error && <div className="inline-error log-error">{error}</div>}
      <div className="log-console">
        {visibleEntries.length === 0 && (
          <p className="log-empty">
            {entries.length === 0
              ? text.emptyNone
              : text.emptyFiltered}
          </p>
        )}
        {visibleEntries.map((entry) => (
          <div className={`log-row ${logEventClassNames(entry.event_kind)}`} key={entry.id}>
            <time dateTime={entry.timestamp}>{time(entry.timestamp)}</time>
            <span className={`log-level level-${entry.level.toLowerCase()}`}>{entry.level}</span>
            <span className="log-source" title={entry.source}>{entry.source}</span>
            <div className="log-message">
              <LogEventSummary entry={entry} />
              <pre className={entry.event_kind && !['WARNING', 'ERROR', 'CRITICAL'].includes(entry.level) ? 'log-raw is-secondary' : 'log-raw'}>
                {entry.message}
              </pre>
              {entry.text !== null && entry.text !== undefined && <pre className="log-raw log-content">{entry.text}</pre>}
              {entry.text_truncated && <p className="inline-error">{text.truncated}</p>}
              <details className="log-details"><summary>{text.details}</summary>
                <dl>{Object.entries(entry.context).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{String(value)}</dd></div>)}</dl>
                {entry.context.request_id && <button className="secondary" onClick={() => {
                  setRequestId(String(entry.context.request_id))
                  setLevel('ALL'); setCommand(''); setOutcome('ALL'); setSource('ALL')
                  setSearch(''); setSince(''); setUntil('')
                }}>{text.related}</button>}
              </details>
            </div>
          </div>
        ))}
        <div ref={bottom} />
      </div>
    </section>
  )
}

function ManagementApp({ windowsDesktop = false }: { windowsDesktop?: boolean }) {
  const [section, setSection] = useState<Section>('Dashboard')
  const [aboutVisited, setAboutVisited] = useState(false)
  const [navigationTarget, setNavigationTarget] = useState<{ id?: string } | null>(null)
  const main = useRef<HTMLElement | null>(null)
  const sidebar = useRef<HTMLElement | null>(null)
  const [status, setStatus] = useState<AppStatus | null>(null)
  const [aiStatus, setAIStatus] = useState<AIStatus | null>(null)
  const [error, setError] = useState('')
  const [actionBusy, setActionBusy] = useState('')
  const updates = useUpdateCheck(windowsDesktop)
  const shellText = useCatalog(shell)
  const commonText = useCatalog(common)
  const dashboardText = useCatalog(dashboard)

  const navigate = (nextSection: Section, targetId?: string) => {
    if (nextSection === 'About') setAboutVisited(true)
    setSection(nextSection)
    setNavigationTarget({ id: targetId })
  }

  useEffect(() => {
    // The Desktop tray opens About when an update is available.
    const onNavigate = (event: Event) => {
      const detail = (event as CustomEvent<{ section?: string; target?: string }>).detail
      if (detail?.section && (sections as readonly string[]).includes(detail.section)) {
        navigate(detail.section as Section, detail.target)
      }
    }
    window.addEventListener('heetkit:navigate', onNavigate)
    return () => window.removeEventListener('heetkit:navigate', onNavigate)
  })

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
          setError(reason instanceof Error ? reason.message : commonText.backendFailed)
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
          setError(reason instanceof Error ? reason.message : commonText.backendFailed)
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
        throw new Error(result.error ?? dashboardText.errors.botState)
      }
      setStatus(await api.get_app_status())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : commonText.backendFailed)
    } finally {
      setActionBusy('')
    }
  }

  const changeBrowserMode = async (mode: BrowserOperationMode) => {
    if (!isBrowserMode()) return
    setError('')
    setActionBusy('operation-mode')
    try {
      const result = await setBrowserOperationMode(mode)
      if (!result.ok) {
        throw new Error(result.error ?? dashboardText.errors.operationMode)
      }
      const api = await waitForBridge()
      setStatus(await api.get_app_status())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : commonText.backendFailed)
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
        throw new Error(result.error ?? dashboardText.errors.aiState)
      }
      setAIStatus(await api.get_ai_status())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : commonText.backendFailed)
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
        throw new Error(result.error ?? dashboardText.errors.authorization)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : dashboardText.errors.authorization)
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
        <div className="brand"><img className="brand-mark" src="./icon.png" alt="" /><div><strong>HeetKit</strong><small>{shellText.tagline}</small></div></div>
        <nav aria-label={shellText.mainNavigation}>
          {sections.map((item) => (
            <div className={`nav-section${item === 'About' ? ' nav-about' : ''}`} key={item}>
              <button
                type="button"
                className={section === item ? 'active' : ''}
                aria-current={section === item ? 'page' : undefined}
                aria-expanded={subsections[item] ? section === item : undefined}
                aria-controls={subsections[item] ? `nav-${item}` : undefined}
                onClick={() => navigate(item)}
              >{shellText.sections[item]}</button>
              {item === 'About' && <LanguageSwitcher />}
              {subsections[item] && (
                <ul className="sidebar-subnav" id={`nav-${item}`} hidden={section !== item}>
                  {subsections[item].filter((child) => !isBrowserMode() || !['desktop-settings', 'profile-location-settings'].includes(child)).map((child) => (
                    <li key={child}>
                      <button
                        type="button"
                        className={navigationTarget?.id === child ? 'active' : ''}
                        aria-current={section === item && navigationTarget?.id === child ? 'location' : undefined}
                        onClick={() => navigate(item, child)}
                      >{shellText.subsections[child]}</button>
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
          <header><h1>{shellText.sections[section]}</h1></header>
          <FeedbackToast error={error} onDismiss={() => setError('')} />
          {section === 'Dashboard' && (
            <Dashboard
              status={status}
              aiStatus={aiStatus}
              busy={actionBusy}
              onChangeBotState={(shouldRun) => void changeBotState(shouldRun)}
              onChangeAIState={(kind, enabled) => void changeAIState(kind, enabled)}
              onRefreshAIStatus={async () => setAIStatus(await (await waitForBridge()).get_ai_status())}
              onAuthorizeTwitch={() => void authorizeTwitch()}
              onChangeBrowserMode={(mode) => void changeBrowserMode(mode)}
              onNavigate={navigate}
              onOpenUpdate={windowsDesktop && updates.result?.update_available ? () => navigate('About', 'desktop-updates') : undefined}
            />
          )}
          <div hidden={section !== 'Commands'}><CommandsPage active={section === 'Commands'} revealCommand={navigationTarget?.id === 'command-editor-ask' ? 'ask' : undefined} onAIEnabledChanged={synchronizeAIEnabled} /></div>
          <div hidden={section !== 'Filters'}><FiltersPage active={section === 'Filters'} /></div>
          <div hidden={section !== 'AI'}><AIPage active={section === 'AI'} onOpenPlayground={() => navigate('AI', 'ai-playground')} onAIEnabledChanged={synchronizeAIEnabled} /></div>
          {section === 'Logs' && <LogsPage />}
          {section === 'Analytics' && <AnalyticsPage leaderboardChannel={status?.leaderboard_channel_id} />}
          <div hidden={section !== 'Settings'}><SettingsPage active={section === 'Settings'} status={status} /></div>
          {aboutVisited && <div hidden={section !== 'About'}><AboutPage updates={updates} /></div>}
        </div>
      </main>
    </div>
  )
}

export default function App() {
  return isBrowserMode() ? <BrowserSession><ManagementApp /></BrowserSession> : (
    <DesktopStartup>{(windows) => <ManagementApp windowsDesktop={windows} />}</DesktopStartup>
  )
}
