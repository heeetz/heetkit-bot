import { useEffect, useMemo, useRef, useState } from 'react'

import { type CommandRestriction, type CommandRestrictionChoice, type CommandRestrictionInput, waitForBridge } from '../bridge'
import Confirmation from './Confirmation'
import HelpTip from './HelpTip'
import { Select } from './Select'

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
}

const MAX_DURATION_SECONDS = 366 * 24 * 60 * 60
const durationOptions = [
  { value: '3600', label: '1 hour' },
  { value: '86400', label: '24 hours' },
  { value: '604800', label: '7 days' },
  { value: '2592000', label: '30 days' },
  { value: String(MAX_DURATION_SECONDS), label: '366 days' },
  { value: 'custom', label: 'Custom duration' },
]

function localInputValue(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (!Number.isFinite(date.getTime())) return ''
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function expiryFor(draft: Draft): string | null {
  if (draft.expiryMode === 'permanent') return null
  if (draft.expiryMode === 'duration') {
    const seconds = Number(draft.duration === 'custom' ? draft.customDuration : draft.duration)
    if (!Number.isInteger(seconds) || seconds < 60 || seconds > MAX_DURATION_SECONDS) throw new Error('Choose a duration from 1 minute to 366 days.')
    return new Date(Date.now() + seconds * 1000).toISOString()
  }
  if (!draft.localExpiry) throw new Error('Choose a local expiry date and time.')
  // Editing a note must preserve the original expiry, including its seconds.
  if (draft.id && draft.originalExpiry && draft.localExpiry === localInputValue(draft.originalExpiry)) return draft.originalExpiry
  const date = new Date(draft.localExpiry)
  const seconds = (date.getTime() - Date.now()) / 1000
  if (!Number.isFinite(seconds) || seconds < 60 || seconds > MAX_DURATION_SECONDS) throw new Error('Expiry must be at least 1 minute away and no more than 366 days away.')
  return date.toISOString()
}

function remaining(expiresAt: string, now: number): string {
  const seconds = Math.max(0, Math.ceil((new Date(expiresAt).getTime() - now) / 1000))
  if (seconds <= 0) return 'Expired'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days) return `${days}d ${hours}h remaining`
  if (hours) return `${hours}h ${minutes}m remaining`
  if (minutes) return `${minutes}m ${seconds % 60}s remaining`
  return `${seconds}s remaining`
}

export default function CommandRestrictions({ active, commands }: Props) {
  const [items, setItems] = useState<CommandRestriction[]>([])
  const [serverCommands, setServerCommands] = useState<CommandRestrictionChoice[] | null>(null)
  const [channelId, setChannelId] = useState<string | null | undefined>(undefined)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [removeTarget, setRemoveTarget] = useState<CommandRestriction | null>(null)
  const [now, setNow] = useState(Date.now())
  const pendingChange = useRef(false)
  const loadRevision = useRef(0)
  const commandChoices = serverCommands ?? commands
  const commandLabels = useMemo(() => new Map(commandChoices.map((command) => [command.id, command.label])), [commandChoices])

  const load = async () => {
    if (pendingChange.current) return
    const revision = ++loadRevision.current
    try {
      const api = await waitForBridge()
      const result = await api.get_command_restrictions()
      if (revision !== loadRevision.current) return
      if (!result.ok) throw new Error(result.error || 'Could not load command restrictions.')
      setItems(result.restrictions)
      setServerCommands(result.commands)
      setChannelId(result.channel_id)
      setError('')
    } catch (reason) {
      if (revision !== loadRevision.current) return
      setError(reason instanceof Error ? reason.message : 'Could not load command restrictions.')
    } finally { if (revision === loadRevision.current) setLoading(false) }
  }

  useEffect(() => {
    if (active) void load()
    return () => { loadRevision.current++ }
  }, [active])
  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(Date.now())
      if (active && !draft) void load()
    }, 30_000)
    return () => window.clearInterval(timer)
  }, [active, draft])

  const filtered = items.filter((item) => `${item.username} ${item.twitch_user_id} ${item.channel_id} ${item.note} ${item.command_ids.map((id) => commandLabels.get(id) ?? id).join(' ')}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))
  const newDraft = (): Draft => ({ username: '', allCommands: true, commandIds: [], expiryMode: 'permanent', duration: '86400', customDuration: '3600', localExpiry: '', note: '' })
  const edit = (item: CommandRestriction) => setDraft({ id: item.id, username: item.username, allCommands: item.command_ids.length === 0, commandIds: [...item.command_ids], expiryMode: item.expires_at ? 'date' : 'permanent', duration: '86400', customDuration: '3600', localExpiry: localInputValue(item.expires_at), originalExpiry: item.expires_at, note: item.note })
  const save = async () => {
    if (!draft || pendingChange.current) return
    pendingChange.current = true
    loadRevision.current++
    setBusy(true); setError('')
    try {
      const data: CommandRestrictionInput = {
        ...(draft.id ? { id: draft.id } : {}),
        username: draft.id ? draft.username : draft.username.trim().replace(/^@/, ''),
        command_ids: draft.allCommands ? [] : draft.commandIds,
        expires_at: expiryFor(draft),
        note: draft.note,
      }
      if (!draft.id && !data.username) throw new Error('Enter a Twitch username. The server resolves its verified identity.')
      if (!draft.allCommands && draft.commandIds.length === 0) throw new Error('Choose at least one command or select all commands.')
      if (data.note.length > 200) throw new Error('Notes can be up to 200 characters.')
      if (/[\r\n]/.test(data.note)) throw new Error('Private notes must be one line.')
      const result = await (await waitForBridge()).save_command_restriction(data)
      if (!result.ok) throw new Error(result.error || 'Could not save this restriction.')
      setItems(result.restrictions); setServerCommands(result.commands); setChannelId(result.channel_id); setDraft(null)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save this restriction.') }
    finally { pendingChange.current = false; setBusy(false) }
  }
  const remove = async () => {
    if (!removeTarget || pendingChange.current) return
    pendingChange.current = true
    loadRevision.current++
    setBusy(true); setError('')
    try {
      const result = await (await waitForBridge()).remove_command_restriction(removeTarget.id)
      if (!result.ok) throw new Error(result.error || 'Could not remove this restriction.')
      setItems(result.restrictions); setServerCommands(result.commands); setChannelId(result.channel_id); setRemoveTarget(null)
    } catch (reason) {
      setRemoveTarget(null)
      setError(reason instanceof Error ? reason.message : 'Could not remove this restriction.')
    }
    finally { pendingChange.current = false; setBusy(false) }
  }

  return <section className="card command-editor-card restriction-panel" id="command-restrictions" aria-labelledby="restriction-title">
    <div className="restriction-heading"><h2 id="restriction-title" className="settings-heading-with-help">User restrictions <HelpTip label="User command restrictions">These are local command controls, not Twitch bans or timeouts. Usernames are resolved by the server to verified Twitch identity; if identity lookup fails, no restriction is created. “All commands” includes ordinary-message reactions. !optout remains available. Global AI blocks are managed separately and still apply.</HelpTip></h2>
      <button type="button" className="primary" disabled={busy || loading || channelId == null} onClick={() => { setError(''); setDraft(newDraft()) }}>Add restriction</button>
    </div>
    <p className="settings-hint">Restrict a verified Twitch user from selected commands or all commands. Private notes stay local to this installation and are not included in command exports.</p>
    {channelId === undefined ? <p className="restriction-scope-message">{loading ? 'Loading configured channel scope…' : 'Configured channel scope could not be loaded. Retry before adding a restriction.'}</p>
      : channelId === null ? <p className="restriction-scope-message">Configure a verified numeric target channel in Settings before adding restrictions. Existing restrictions retain their saved channel scope.</p>
        : <p className="restriction-scope-message">New restrictions apply to configured channel ID {channelId}. Existing restrictions keep their saved channel scope.</p>}
    {error && <div className="inline-error" role="alert"><span>{error}</span><button type="button" className="secondary" disabled={busy} onClick={() => { setLoading(true); void load() }}>Retry</button></div>}
    {draft && <div className="restriction-editor" aria-label={draft.id ? 'Edit restriction' : 'Add restriction'}>
      <h3>{draft.id ? `Edit restriction for ${draft.username}` : 'Add user restriction'}</h3>
      {!draft.id && <div className="form-field"><label htmlFor="restriction-username">Twitch username</label><input id="restriction-username" disabled={busy} value={draft.username} maxLength={26} autoComplete="off" onChange={(event) => setDraft({ ...draft, username: event.target.value })} /><span className="settings-hint">The server resolves the username to a verified numeric Twitch identity.</span></div>}
      {draft.id && <p className="settings-hint">Verified identity and channel scope are fixed for this restriction. Current stored login: <strong>{draft.username}</strong>.</p>}
      <fieldset className="restriction-commands" disabled={busy}><legend>Affected commands</legend><label className="restriction-check"><input type="checkbox" checked={draft.allCommands} onChange={(event) => setDraft({ ...draft, allCommands: event.target.checked })} />All commands, including ordinary-message reactions</label>
        <div className="restriction-choice-grid">{commandChoices.map((command) => <label className="restriction-check" key={command.id}><input type="checkbox" disabled={busy || draft.allCommands} checked={draft.commandIds.includes(command.id)} onChange={(event) => {
          const ids = event.target.checked ? [...draft.commandIds, command.id] : draft.commandIds.filter((id) => id !== command.id)
          setDraft({ ...draft, commandIds: ids })
        }} />{command.label}</label>)}{draft.commandIds.filter((id) => !commandLabels.has(id)).map((id) => <label className="restriction-check" key={id}><input type="checkbox" disabled={busy || draft.allCommands} checked onChange={() => setDraft({ ...draft, commandIds: draft.commandIds.filter((item) => item !== id) })} />{id} (command no longer exists)</label>)}</div>
      </fieldset>
      <div className="restriction-fields"><div className="form-field"><label htmlFor="restriction-expiry-mode">Expiry</label><Select id="restriction-expiry-mode" disabled={busy} value={draft.expiryMode} onChange={(value) => setDraft({ ...draft, expiryMode: value as ExpiryMode })} options={[{ value: 'permanent', label: 'Permanent' }, { value: 'duration', label: 'Duration' }, { value: 'date', label: 'Local date and time' }]} /></div>
        {draft.expiryMode === 'duration' && <div className="form-field"><label htmlFor="restriction-duration">Duration</label><Select id="restriction-duration" disabled={busy} value={draft.duration} onChange={(value) => setDraft({ ...draft, duration: value })} options={durationOptions} />
          {draft.duration === 'custom' && <label className="restriction-custom-duration">Custom seconds (60 to 31,622,400)<input aria-label="Custom duration in seconds" disabled={busy} type="number" min={60} max={MAX_DURATION_SECONDS} value={draft.customDuration} onChange={(event) => setDraft({ ...draft, customDuration: event.target.value })} /></label>}</div>}
        {draft.expiryMode === 'date' && <div className="form-field"><label htmlFor="restriction-local-expiry">Expires at (your local time)</label><input id="restriction-local-expiry" disabled={busy} type="datetime-local" value={draft.localExpiry} onChange={(event) => setDraft({ ...draft, localExpiry: event.target.value })} /><span className="settings-hint">Saved as an absolute UTC expiry, within the next 366 days.</span></div>}
      </div>
      <div className="form-field"><label htmlFor="restriction-note">Private note (one line) <span className="settings-hint">({draft.note.length}/200)</span></label><input id="restriction-note" disabled={busy} type="text" maxLength={200} value={draft.note} onChange={(event) => setDraft({ ...draft, note: event.target.value })} /><span className="settings-hint">Private operator context only; up to 200 characters.</span></div>
      <div className="row-actions"><button type="button" className="secondary" disabled={busy} onClick={() => setDraft(null)}>Cancel</button><button type="button" className="primary" disabled={busy} onClick={() => void save()}>{busy ? 'Saving…' : 'Save restriction'}</button></div>
    </div>}
    <div className="restriction-toolbar"><div className="form-field"><label htmlFor="restriction-search">Search restrictions</label><input id="restriction-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Username, ID, command, note" /></div></div>
    {loading ? <p role="status">Loading restrictions…</p> : filtered.length ? <ul className="restriction-list">{filtered.map((item) => <li className="restriction-row" key={item.id}>
      <div className="restriction-summary"><strong>{item.username}</strong><span> Twitch user ID {item.twitch_user_id} · channel ID {item.channel_id}</span>
        <p>{item.command_ids.length ? item.command_ids.map((id) => commandLabels.get(id) ?? id).join(', ') : 'All commands, including ordinary-message reactions'}</p>
        <p>{item.expires_at ? <><time dateTime={item.expires_at}>{new Date(item.expires_at).toLocaleString()}</time> · {remaining(item.expires_at, now)}</> : 'Permanent'}</p>
        {item.note && <p className="restriction-note">{item.note}</p>}
      </div><div className="row-actions"><button type="button" className="secondary" disabled={busy} onClick={() => edit(item)}>Edit</button><button type="button" className="danger" disabled={busy} onClick={() => setRemoveTarget(item)}>Remove</button></div>
    </li>)}</ul> : error ? null : <p>{query ? 'No restrictions match this search.' : 'No active user restrictions.'}</p>}
    {removeTarget && <Confirmation title="Remove user restriction?" description={`This immediately removes this rule for ${removeTarget.username}. Other active command restrictions or global AI blocks may still apply.`} danger onCancel={() => { if (!busy) setRemoveTarget(null) }} onConfirm={() => void remove()} />}
  </section>
}
