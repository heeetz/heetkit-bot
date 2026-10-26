import { useEffect, useRef, useState } from 'react'
import { type AnnouncementInfo, type AnnouncementInput, type StreamAvailability, waitForBridge } from '../bridge'
import Confirmation from './Confirmation'
import HelpTip from './HelpTip'
import { Select } from './Select'
import Switch from './Switch'

interface Draft {
  id: string | null
  name: string
  enabled: boolean
  message: string
  randomMessages: string
  mode: 'single' | 'random'
  delivery: 'regular' | 'highlighted'
  interval: string
  minimum: string
  availability: StreamAvailability
}

const availabilityOptions = [
  { value: 'anytime', label: 'Anytime' },
  { value: 'live_only', label: 'Live only' },
  { value: 'offline_only', label: 'Offline only' },
]
const outcomeLabels: Record<string, string> = {
  sent: 'Sent', skipped_activity: 'Waiting for chat activity', skipped_stream: 'Waiting for stream availability',
  not_confirmed: 'Delivery not confirmed', failed: 'Send failed', cancelled: 'Send cancelled',
  authorization_required: 'Authorize Twitch again to allow highlighted announcements.',
  permission_denied: 'Twitch denied the announcement. The sending account must be a moderator or the broadcaster.',
}

function fromSaved(item: AnnouncementInfo): Draft {
  return { id: item.id, name: item.name, enabled: item.enabled,
    message: item.messages[0] ?? '', randomMessages: item.messages.join('\n'), mode: item.message_mode,
    delivery: item.delivery_mode ?? 'regular', interval: String(item.interval_seconds),
    minimum: String(item.min_messages), availability: item.stream_availability }
}

function integer(value: string, minimum: number, maximum: number): number | null {
  const number = Number(value)
  return value.trim() && Number.isInteger(number) && number >= minimum && number <= maximum ? number : null
}

function input(draft: Draft): AnnouncementInput | null {
  const interval = integer(draft.interval, 60, 86400)
  const minimum = integer(draft.minimum, 0, 1000)
  const messages = draft.mode === 'random' ? draft.randomMessages.split(/\r?\n/).map((line) => line.trim()).filter(Boolean) : [draft.message.trim()]
  if (!draft.name.trim() || new TextEncoder().encode(draft.name.trim()).length > 80 || /[\x00-\x1f\x7f]/.test(draft.name)
    || interval === null || minimum === null || messages.length < 1 || messages.length > 30
    || messages.some((message) => !message || /[\x00-\x1f\x7f]/.test(message) || new TextEncoder().encode(message).length > 450)) return null
  return { id: draft.id, name: draft.name.trim(), enabled: draft.enabled, messages, message_mode: draft.mode,
    delivery_mode: draft.delivery, interval_seconds: interval, min_messages: minimum, stream_availability: draft.availability }
}

function savedInput(item: AnnouncementInfo): AnnouncementInput {
  return { id: item.id, name: item.name, enabled: item.enabled, messages: item.messages,
    message_mode: item.message_mode, delivery_mode: item.delivery_mode ?? 'regular', interval_seconds: item.interval_seconds,
    min_messages: item.min_messages, stream_availability: item.stream_availability }
}

function time(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '—'
}

function AnnouncementStatus({ item, name }: { item?: AnnouncementInfo; name: string }) {
  const status = item?.status
  return <HelpTip label={`Announcement status ${name}`}><span className="announcement-status-details">
    <span>Next run: {status?.next_run_at ? time(status.next_run_at) : 'Waiting for connection or disabled'}</span>
    <span>Last sent: {time(status?.last_sent_at ?? null)}</span>
    <span>Last outcome: {status?.last_outcome ? outcomeLabels[status.last_outcome] ?? status.last_outcome : 'No attempts yet'}</span>
    <span>Eligible messages: {status?.eligible_messages ?? 0}</span>
    {!item && <span>Save to schedule this announcement.</span>}
  </span></HelpTip>
}

function AnnouncementOutcome({ item }: { item?: AnnouncementInfo }) {
  const outcome = item?.status.last_outcome
  if (!outcome || !['failed', 'not_confirmed', 'cancelled', 'skipped_stream', 'authorization_required', 'permission_denied'].includes(outcome)) return null
  return <p className={`announcement-outcome ${outcome === 'skipped_stream' ? 'muted' : 'inline-error'}`} role="status">
    Last outcome: {outcomeLabels[outcome]}
  </p>
}

export default function AnnouncementsPanel({ active }: { active: boolean }) {
  const [saved, setSaved] = useState<AnnouncementInfo[] | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const baseline = useRef('')
  const revision = useRef(0)
  const writing = useRef(false)
  const [busy, setBusy] = useState(false)
  const [deleting, setDeleting] = useState<AnnouncementInfo | null>(null)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [notice, setNotice] = useState('')
  const dirty = draft !== null && JSON.stringify(draft) !== baseline.current

  useEffect(() => {
    if (!active) return
    let mounted = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = async () => {
      const started = revision.current
      try {
        if (writing.current) return
        const api = await waitForBridge()
        const result = await api.get_announcements()
        if (!mounted || started !== revision.current || writing.current) return
        if (!result.ok || !Array.isArray(result.announcements)) throw new Error('Could not load announcements.')
        setSaved(result.announcements)
        setLoadError('')
      } catch {
        if (mounted && started === revision.current) setLoadError('Could not refresh announcements. Check the connection and try again.')
      } finally {
        if (mounted) timer = setTimeout(() => void load(), 5000)
      }
    }
    void load()
    return () => { mounted = false; clearTimeout(timer) }
  }, [active])

  function edit(next: Draft) {
    baseline.current = next.id ? JSON.stringify(next) : ''
    setDraft(next)
    setNotice('')
    setError('')
  }

  function update(patch: Partial<Draft>) {
    setDraft((current) => current ? { ...current, ...patch } : null)
    setNotice('')
  }

  async function persist(payload: AnnouncementInput[], success: string) {
    writing.current = true
    revision.current += 1
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.save_announcements(payload)
      if (!result.ok) throw new Error(result.error || 'Could not save announcements.')
      // The write has committed. Until fresh IDs load, prevent a retry or a new
      // collection write based on stale rows from duplicating/removing that save.
      setDraft(null)
      setSaved(null)
      const refreshed = await api.get_announcements()
      if (!refreshed.ok) throw new Error('Announcements were saved, but the updated status could not be loaded. Refresh before editing again.')
      setSaved(refreshed.announcements)
      setDraft(null)
      setNotice(success)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save announcements.')
    } finally {
      revision.current += 1
      writing.current = false
      setBusy(false)
    }
  }

  function save() {
    if (!draft || !saved) return
    if (draft.id && !saved.some((item) => item.id === draft.id)) {
      setError('This announcement was removed. Cancel this draft before creating a new announcement.')
      return
    }
    const entry = input(draft)
    if (!entry) {
      setError('Use a name of at most 80 UTF-8 bytes, 1–30 single-line messages of at most 450 UTF-8 bytes, an interval of 60–86400 seconds and a minimum of 0–1000 messages. Names and messages cannot contain control characters.')
      return
    }
    const payload = saved.map((item) => item.id === draft.id ? entry : savedInput(item))
    if (!draft.id) payload.push(entry)
    void persist(payload, 'Announcements saved.')
  }

  const current = saved?.find((item) => item.id === draft?.id)
  const prefix = 'announcement-editor'
  const editor = draft && <article className="command-card announcement-card announcement-editing">
    <div className="announcement-editor-heading"><h3>{draft.name || 'New announcement'}</h3>
      <AnnouncementStatus item={current} name={draft.name || 'New announcement'} />
      <span className={`state-pill ${draft.enabled ? 'enabled' : ''}`}>{draft.enabled ? 'Enabled' : 'Disabled'}</span>
    </div>
    <AnnouncementOutcome item={current} />
    <fieldset disabled={busy} id={prefix} className="announcement-editor" aria-label="Announcement settings">
      <div className="announcement-controls">
        <div className="announcement-name-row">
          <label className="form-field" htmlFor={`${prefix}-name`}>Name<input id={`${prefix}-name`} placeholder="e.g. Community reminder" maxLength={80} value={draft.name} onChange={(event) => update({ name: event.target.value })} /></label>
          <Switch className="announcement-enable" checked={draft.enabled} ariaLabel="Enable announcement" onCheckedChange={(enabled) => update({ enabled })}>{null}</Switch>
        </div>
        <div className="form-field"><div className="custom-field-label"><label htmlFor={`${prefix}-interval`}>Interval (s)</label><HelpTip label="Announcement interval">Choose 60 to 86400 seconds. Startup, reconnect, channel changes and saved edits restart the full interval. Missed checks never create a catch-up backlog.</HelpTip></div>
          <input id={`${prefix}-interval`} type="number" min={60} max={86400} step={1} value={draft.interval} aria-invalid={integer(draft.interval, 60, 86400) === null} onChange={(event) => update({ interval: event.target.value })} /></div>
        <div className="form-field"><div className="custom-field-label"><label htmlFor={`${prefix}-minimum`}>Trigger after</label><HelpTip label="Announcement activity">At each interval check, send only if this many eligible incoming messages arrived during this announcement’s current interval. This is a minimum activity condition, not an immediate message-count trigger. Each scheduled check starts a fresh activity window, including skipped checks. Own bot output and replayed events do not count. Zero allows quiet chat.</HelpTip></div>
          <div className="number-with-unit announcement-message-count"><input id={`${prefix}-minimum`} type="number" min={0} max={1000} step={1} value={draft.minimum} aria-invalid={integer(draft.minimum, 0, 1000) === null} onChange={(event) => update({ minimum: event.target.value })} /><span aria-hidden="true">messages</span></div></div>
        <div className="form-field"><div className="custom-field-label"><label htmlFor={`${prefix}-availability`}>Works when:</label><HelpTip label="Announcement stream availability">Live only and Offline only require a fresh matching stream observation. Unknown or stale stream status pauses restricted sends on both Desktop and Server.</HelpTip></div>
          <Select id={`${prefix}-availability`} aria-label="Works when:" value={draft.availability} onChange={(availability) => update({ availability: availability as StreamAvailability })} options={availabilityOptions} /></div>
        <div className="form-field"><div className="custom-field-label"><label htmlFor={`${prefix}-mode`}>Message selection</label><HelpTip label="Announcement messages">Single sends one plain-text line. Random chooses one of 1 to 30 non-empty lines per interval. Each line allows up to 450 UTF-8 bytes. Template variables are not expanded.</HelpTip></div>
          <Select id={`${prefix}-mode`} aria-label="Message selection" value={draft.mode} onChange={(mode) => update({ mode: mode as Draft['mode'] })} options={[{ value: 'single', label: 'Single message' }, { value: 'random', label: 'Random message' }]} /></div>
      </div>
      <div className="form-field announcement-type"><div className="custom-field-label"><label htmlFor={`${prefix}-delivery`}>Announcement type</label><HelpTip label="Announcement type">Highlighted uses Twitch’s Announcement format in the channel’s accent color. The sending account must be a moderator or the broadcaster. If permission is missing, use Settings → Renew Twitch authorization on Desktop or Connect Twitch on Server. Regular message uses ordinary chat. Highlighted failures never fall back to regular messages. In Shared Chat, highlighted announcements reach every participating channel.</HelpTip></div>
        <Select id={`${prefix}-delivery`} aria-label="Announcement type" value={draft.delivery} onChange={(delivery) => update({ delivery: delivery as Draft['delivery'] })} options={[{ value: 'highlighted', label: 'Highlighted' }, { value: 'regular', label: 'Regular message' }]} /></div>
      <div className="form-field announcement-message">
        <textarea id={`${prefix}-message`} aria-label={draft.mode === 'random' ? 'Random messages' : 'Announcement message'} placeholder={draft.mode === 'random' ? 'Join our community: https://example.com\nFollow for updates and the next stream!' : 'e.g. Join our community: https://example.com'} rows={draft.mode === 'random' ? 5 : 3} value={draft.mode === 'random' ? draft.randomMessages : draft.message} onChange={(event) => update(draft.mode === 'random' ? { randomMessages: event.target.value } : { message: event.target.value })} />
      </div>
      <div className="row-actions announcement-actions">
        <div className="announcement-save-state">
          <HelpTip label="Saving announcements">Save announcements applies this edit and restarts enabled schedules with a full interval. Cancel discards the current draft. Edit, Enable or Disable, and Delete are available on each saved announcement. Scheduling status is available from (?) beside its name.</HelpTip>
          {dirty && <span className="mini-badge dirty-badge">Unsaved changes</span>}
        </div>
        <div className="announcement-save-buttons">
          <button className="primary" disabled={busy || !dirty} onClick={save}>Save announcements</button>
          <button className="secondary" disabled={busy} onClick={() => { setDraft(null); setError(''); setNotice('') }}>Cancel</button>
        </div>
      </div>
    </fieldset>
  </article>

  return <section className="card command-editor-card announcements-panel" id="announcements" aria-busy={busy}>
    <div className="section-heading">
      <div><h2>Announcements</h2><p className="section-copy">Send scheduled highlighted announcements or regular chat messages.</p></div>
      <button className="primary" disabled={!saved || busy || Boolean(draft) || saved.length >= 50} onClick={() => edit({
        id: null, name: '', enabled: true, message: '', randomMessages: '', mode: 'single', delivery: 'highlighted',
        interval: '900', minimum: '0', availability: 'anytime',
      })}>New announcement</button>
    </div>
    {error && <p className="inline-error" role="alert">{error}</p>}
    {loadError && <p className="inline-error" role="alert">{loadError}</p>}
    {notice && <p role="status">{notice}</p>}
    {saved === null ? <p className="muted">Loading announcements…</p> : <>
      {saved.length === 0 && !draft && <p className="muted">No announcements configured.</p>}
      {(saved.length > 0 || draft) && <div className="announcement-collection custom-command-list">
        {draft && (!draft.id || !current) && editor}
        {saved.map((item) => item.id === draft?.id ? <div key={item.id}>{editor}</div> : <article className="custom-command-row announcement-row" key={item.id}>
          <div className="custom-command-summary">
            <div className="custom-command-heading"><strong>{item.name}</strong>
              <span className={`state-pill ${item.enabled ? 'enabled' : ''}`}>{item.enabled ? 'Enabled' : 'Disabled'}</span>
              <span className="mini-badge">{item.delivery_mode === 'highlighted' ? 'Highlighted' : 'Regular message'}</span>
              <AnnouncementStatus item={item} name={item.name} />
            </div>
            <p className="custom-command-response">{item.messages[0]}</p>
            <small className="muted">{item.interval_seconds}s interval{item.message_mode === 'random' ? ` · ${item.messages.length} messages · one chosen at random` : ''}</small>
            <AnnouncementOutcome item={item} />
          </div>
          <div className="row-actions">
            <button className="secondary" disabled={busy || Boolean(draft)} onClick={() => edit(fromSaved(item))}>Edit</button>
            <button className="secondary" disabled={busy || Boolean(draft)} onClick={() => void persist(saved.map((entry) => ({ ...savedInput(entry), ...(entry.id === item.id ? { enabled: !entry.enabled } : {}) })), `${item.name} ${item.enabled ? 'disabled' : 'enabled'}.`)}>{item.enabled ? 'Disable' : 'Enable'}</button>
            <button className="ghost destructive" disabled={busy || Boolean(draft)} onClick={() => setDeleting(item)}>Delete</button>
          </div>
        </article>)}
      </div>}
    </>}
    {deleting && <Confirmation title={`Delete ${deleting.name}?`} description="Permanently delete this announcement. This cannot be undone." danger
      onCancel={() => setDeleting(null)} onConfirm={() => {
        setDeleting(null)
        if (saved) void persist(saved.filter((item) => item.id !== deleting.id).map(savedInput), `Deleted ${deleting.name}.`)
      }} />}
  </section>
}
