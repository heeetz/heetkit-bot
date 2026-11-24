import { useEffect, useMemo, useRef, useState } from 'react'

import { type CommandRestriction, type CommandRestrictionChoice, type CommandRestrictionInput, waitForBridge } from '../bridge'
import Confirmation from './Confirmation'
import HelpTip from './HelpTip'
import { Select } from './Select'
import { commandsText } from '../i18n/commands'
import { catalogFor, fmt, useCatalog, useI18n } from '../i18n/core'

interface Props {
  active: boolean
  commands: CommandRestrictionChoice[]
}

type ExpiryMode = 'permanent' | 'duration' | 'date'
interface Draft {
  id?: string
  username: string
  allCommands: boolean
  commandIds: string[]
  expiryMode: ExpiryMode
  duration: string
  customDuration: string
  localExpiry: string
  originalExpiry?: string | null
  note: string
  scope: 'channel' | 'global_ai'
  unresolved?: boolean
  channelId?: string | null
}

const MAX_DURATION_SECONDS = 366 * 24 * 60 * 60

function localInputValue(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (!Number.isFinite(date.getTime())) return ''
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function expiryFor(draft: Draft): string | null {
  const text = catalogFor(commandsText).restrictions
  if (draft.expiryMode === 'permanent') return null
  if (draft.expiryMode === 'duration') {
    const seconds = Number(draft.duration === 'custom' ? draft.customDuration : draft.duration)
    if (!Number.isInteger(seconds) || seconds < 60 || seconds > MAX_DURATION_SECONDS) throw new Error(text.durationInvalid)
    return new Date(Date.now() + seconds * 1000).toISOString()
  }
  if (!draft.localExpiry) throw new Error(text.expiryRequired)
  // Editing a note must preserve the original expiry, including its seconds.
  if (draft.id && draft.originalExpiry && draft.localExpiry === localInputValue(draft.originalExpiry)) return draft.originalExpiry
  const date = new Date(draft.localExpiry)
  const seconds = (date.getTime() - Date.now()) / 1000
  if (!Number.isFinite(seconds) || seconds < 60 || seconds > MAX_DURATION_SECONDS) throw new Error(text.expiryInvalid)
  return date.toISOString()
}

function remaining(expiresAt: string, now: number, text: typeof commandsText.en.restrictions): string {
  const seconds = Math.max(0, Math.ceil((new Date(expiresAt).getTime() - now) / 1000))
  if (seconds <= 0) return text.expired
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days) return fmt(text.remainingDays, { days, hours })
  if (hours) return fmt(text.remainingHours, { hours, minutes })
  if (minutes) return fmt(text.remainingMinutes, { minutes, seconds: seconds % 60 })
  return fmt(text.remainingSeconds, { seconds })
}

export default function CommandRestrictions({ active, commands }: Props) {
  const text = useCatalog(commandsText).restrictions
  const { dateTime } = useI18n()
  const durationOptions = [
    { value: '3600', label: text.durations.hour },
    { value: '86400', label: text.durations.day },
    { value: '604800', label: text.durations.week },
    { value: '2592000', label: text.durations.month },
    { value: String(MAX_DURATION_SECONDS), label: text.durations.max },
    { value: 'custom', label: text.durations.custom },
  ]
  const [items, setItems] = useState<CommandRestriction[]>([])
  const [serverCommands, setServerCommands] = useState<CommandRestrictionChoice[] | null>(null)
  const [channelId, setChannelId] = useState<string | null | undefined>(undefined)
  const [draft, setDraft] = useState<Draft | null>(null)
  useRestartDraft('User restrictions', Boolean(draft))
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [removeTarget, setRemoveTarget] = useState<CommandRestriction | null>(null)
  const [now, setNow] = useState(Date.now())
  const pendingChange = useRef(false)
  const loadRevision = useRef(0)
  const panel = useRef<HTMLElement>(null)
  const commandChoices = (serverCommands ?? commands).filter((command) => command.id !== 'optout')
  const catalogRevision = JSON.stringify(commands)
  const commandLabels = useMemo(() => new Map(commandChoices.map((command) => [command.id, command.label])), [commandChoices])

  const load = async () => {
    if (pendingChange.current) return
    const revision = ++loadRevision.current
    try {
      const api = await waitForBridge()
      const result = await api.get_command_restrictions()
      if (revision !== loadRevision.current) return
      if (!result.ok) throw new Error(result.error || text.loadFailed)
      setItems(result.restrictions)
      setServerCommands(result.commands)
      setChannelId(result.channel_id)
      setError('')
    } catch (reason) {
      if (revision !== loadRevision.current) return
      setError(reason instanceof Error ? reason.message : text.loadFailed)
    } finally { if (revision === loadRevision.current) setLoading(false) }
  }

  useEffect(() => {
    if (active) void load()
    return () => { loadRevision.current++ }
  }, [active])
  useEffect(() => {
    // The initial list already owns the backend catalog. Refresh later command
    // mutations without replacing drafts or automatically hiding a load failure.
    if (active && channelId !== undefined && !loading && !error) void load()
  }, [catalogRevision])
  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(Date.now())
      if (active && !draft) void load()
    }, 30_000)
    return () => window.clearInterval(timer)
  }, [active, draft])

  const filtered = items.filter((item) => `${item.username} ${item.twitch_user_id} ${item.channel_id} ${item.note} ${item.scope === 'global_ai' ? 'global AI all profile channels' : 'channel'} ${item.command_ids.map((id) => commandLabels.get(id) ?? id).join(' ')}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
  const newDraft = (): Draft => ({ username: '', allCommands: true, commandIds: [], expiryMode: 'permanent', duration: '86400', customDuration: '3600', localExpiry: '', note: '', scope: 'channel' })
  const edit = (item: CommandRestriction) => {
    setDraft({ id: item.id, username: item.username, allCommands: item.command_ids.length === 0, commandIds: [...item.command_ids], expiryMode: item.expires_at ? 'date' : 'permanent', duration: '86400', customDuration: '3600', localExpiry: localInputValue(item.expires_at), originalExpiry: item.expires_at, note: item.note, scope: item.scope ?? 'channel', channelId: item.channel_id, unresolved: item.identity_state === 'unresolved' || !item.twitch_user_id })
    // The editor opens at the top of the panel; bring it into view from long lists.
    requestAnimationFrame(() => panel.current?.scrollIntoView({ block: 'start' }))
  }
  const save = async () => {
    if (!draft || pendingChange.current) return
    pendingChange.current = true
    loadRevision.current++
    setBusy(true); setError('')
    try {
      const data: CommandRestrictionInput = {
        ...(draft.id ? { id: draft.id } : {}),
        username: draft.id ? draft.username : draft.username.trim().replace(/^@/, ''),
        scope: draft.scope,
        command_ids: draft.scope === 'global_ai' ? ['ask'] : draft.allCommands ? [] : draft.commandIds,
        expires_at: expiryFor(draft),
        note: draft.note,
      }
      if (!draft.id && !data.username) throw new Error(text.usernameRequired)
      if (draft.scope !== 'global_ai' && !draft.allCommands && draft.commandIds.length === 0) throw new Error(text.commandsRequired)
      if (data.note.length > 200) throw new Error(text.noteTooLong)
      if (/[\r\n]/.test(data.note)) throw new Error(text.noteOneLine)
      const result = await (await waitForBridge()).save_command_restriction(data)
      if (!result.ok) throw new Error(result.error || text.saveFailed)
      setItems(result.restrictions); setServerCommands(result.commands); setChannelId(result.channel_id); setDraft(null)
    } catch (reason) { setError(reason instanceof Error ? reason.message : text.saveFailed) }
    finally { pendingChange.current = false; setBusy(false) }
  }
  const remove = async () => {
    if (!removeTarget || pendingChange.current) return
    pendingChange.current = true
    loadRevision.current++
    setBusy(true); setError('')
    try {
      const result = await (await waitForBridge()).remove_command_restriction(removeTarget.id)
      if (!result.ok) throw new Error(result.error || text.removeFailed)
      setItems(result.restrictions); setServerCommands(result.commands); setChannelId(result.channel_id); setRemoveTarget(null)
    } catch (reason) {
      setRemoveTarget(null)
      setError(reason instanceof Error ? reason.message : text.removeFailed)
    }
    finally { pendingChange.current = false; setBusy(false) }
  }

  return <section ref={panel} className="card command-editor-card restriction-panel" id="command-restrictions" aria-labelledby="restriction-title">
    <div className="restriction-heading"><div className="settings-heading-with-help"><h2 id="restriction-title">{text.title}</h2><HelpTip label={text.helpLabel}>{text.help}</HelpTip></div>
      <button type="button" className="primary" disabled={busy || loading || channelId === undefined} onClick={() => { setError(''); setDraft(newDraft()) }}>{text.add}</button>
    </div>
    {channelId === undefined ? <p className="restriction-scope-message">{loading ? text.loadingScope : text.scopeFailed}</p>
      : channelId === null ? <p className="restriction-scope-message">{text.noChannel}</p>
        : <p className="restriction-scope-message">{fmt(text.channelScope, { id: channelId })}</p>}
    {error && <div className="inline-error" role="alert"><span>{error}</span><button type="button" className="secondary" disabled={busy} onClick={() => { setLoading(true); void load() }}>{text.retry}</button></div>}
    {draft && <div className="restriction-editor" aria-label={draft.id ? text.edit : text.add}>
      <h3>{draft.id ? fmt(text.editFor, { name: draft.username }) : text.addUser}</h3>
      <div className="restriction-fields">
      <div className="form-field"><label htmlFor="restriction-username">{text.username}</label><input id="restriction-username" disabled={busy || Boolean(draft.id)} value={draft.username} maxLength={26} placeholder={text.usernamePlaceholder} autoComplete="off" onChange={(event) => setDraft({ ...draft, username: event.target.value })} /><span className="settings-hint">{draft.unresolved ? text.unresolved : draft.id ? text.verified : text.verifyOnSave}</span></div>
<div className="form-field"><label htmlFor="restriction-expiry-mode">{text.expiry}</label><Select id="restriction-expiry-mode" disabled={busy} value={draft.expiryMode} onChange={(value) => setDraft({ ...draft, expiryMode: value as ExpiryMode })} options={[{ value: 'permanent', label: text.permanent }, { value: 'duration', label: text.duration }, { value: 'date', label: text.localDate }]} /></div>
        {draft.expiryMode === 'duration' && <div className="form-field"><label htmlFor="restriction-duration">{text.duration}</label><Select id="restriction-duration" disabled={busy} value={draft.duration} onChange={(value) => setDraft({ ...draft, duration: value })} options={durationOptions} />
          {draft.duration === 'custom' && <label className="restriction-custom-duration">{text.customSeconds}<input aria-label={text.customSecondsInput} disabled={busy} type="number" min={60} max={MAX_DURATION_SECONDS} value={draft.customDuration} onChange={(event) => setDraft({ ...draft, customDuration: event.target.value })} /></label>}</div>}
        {draft.expiryMode === 'date' && <div className="form-field"><label htmlFor="restriction-local-expiry">{text.expiresAt}</label><input id="restriction-local-expiry" disabled={busy} type="datetime-local" value={draft.localExpiry} onChange={(event) => setDraft({ ...draft, localExpiry: event.target.value })} /><span className="settings-hint">{text.expiresHint}</span></div>}
      </div>
      <div className="form-field"><label htmlFor="restriction-note">{text.note} <span className="settings-hint">({draft.note.length}/200)</span></label><input id="restriction-note" aria-describedby="restriction-note-help" disabled={busy} type="text" maxLength={200} value={draft.note} onChange={(event) => setDraft({ ...draft, note: event.target.value })} /><span className="settings-hint" id="restriction-note-help">{text.noteHint}</span></div>
      <div className="restriction-ai-scope">
        <label className="restriction-check"><input type="checkbox" disabled={busy || Boolean(draft.id)} checked={draft.scope === 'global_ai'} onChange={(event) => setDraft({ ...draft, scope: event.target.checked ? 'global_ai' : 'channel', ...(event.target.checked ? { allCommands: false, commandIds: ['ask'] } : {}) })} />{text.globalAI}</label>
        <p className="settings-hint">{draft.scope === 'global_ai' ? text.globalAIHint : fmt(text.appliesTo, { id: (draft.id ? draft.channelId : channelId) ?? text.notConfigured })}{draft.id && text.scopeFixed}</p>
      </div>
      <fieldset className="restriction-commands" disabled={busy || draft.scope === 'global_ai'}><legend>{text.affected}</legend><label className="restriction-check"><input type="checkbox" checked={draft.allCommands} onChange={(event) => setDraft({ ...draft, allCommands: event.target.checked })} />{text.allCommands}</label>
        <div className="restriction-choice-grid">{commandChoices.map((command) => <label className="restriction-check" key={command.id}><input type="checkbox" disabled={busy || draft.allCommands} checked={draft.commandIds.includes(command.id)} onChange={(event) => {
          const ids = event.target.checked ? [...draft.commandIds, command.id] : draft.commandIds.filter((id) => id !== command.id)
          setDraft({ ...draft, commandIds: ids })
        }} />{command.label}</label>)}{draft.commandIds.filter((id) => !commandLabels.has(id)).map((id) => <label className="restriction-check" key={id}><input type="checkbox" disabled={busy || draft.allCommands} checked onChange={() => setDraft({ ...draft, commandIds: draft.commandIds.filter((item) => item !== id) })} />{fmt(text.missingCommand, { id })}</label>)}</div>
      </fieldset>
      <div className="row-actions"><button type="button" className="secondary" disabled={busy} onClick={() => setDraft(null)}>{text.cancel}</button><button type="button" className="primary" disabled={busy || (draft.scope === 'channel' && !draft.id && !channelId)} onClick={() => void save()}>{busy ? text.saving : text.save}</button></div>
    </div>}
    <div className="restriction-toolbar"><div className="form-field"><label htmlFor="restriction-search">{text.search}</label><input id="restriction-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={text.searchPlaceholder} /></div></div>
    {loading ? <p role="status">{text.loading}</p> : filtered.length ? <ul className="restriction-list">{filtered.map((item) => <li className="restriction-row" key={item.id}>
      <div className="restriction-summary"><strong>{item.username}</strong><span> {item.twitch_user_id ? fmt(text.userId, { id: item.twitch_user_id }) : text.identityUnresolved} | {item.scope === 'global_ai' ? text.globalScope : item.channel_id ? fmt(text.channelId, { id: item.channel_id }) : text.channelPending}</span>
        <p>{item.command_ids.length ? item.command_ids.map((id) => commandLabels.get(id) ?? id).join(', ') : text.allCommands}</p>
        <p>{item.expires_at ? <><time dateTime={item.expires_at}>{dateTime(item.expires_at)}</time> · {remaining(item.expires_at, now, text)}</> : text.permanent}</p>
        {item.note && <p className="restriction-note">{item.note}</p>}
      </div><div className="row-actions"><button type="button" className="secondary" disabled={busy} onClick={() => edit(item)}>{item.identity_state === 'unresolved' || !item.twitch_user_id ? text.verifyEdit : text.editButton}</button><button type="button" className="danger" disabled={busy} onClick={() => setRemoveTarget(item)}>{text.remove}</button></div>
    </li>)}</ul> : error ? null : <p>{query ? text.noMatches : text.empty}</p>}
    {removeTarget && <Confirmation title={text.removeTitle} description={fmt(text.removeDescription, { name: removeTarget.username })} danger onCancel={() => { if (!busy) setRemoveTarget(null) }} onConfirm={() => void remove()} />}
  </section>
}
import { useRestartDraft } from '../desktopRestart'
