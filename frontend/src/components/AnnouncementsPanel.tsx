import { useEffect, useRef, useState } from 'react'
import { type AnnouncementInfo, type AnnouncementInput, type StreamAvailability, waitForBridge } from '../bridge'
import AccordionHeader from './AccordionHeader'
import HelpTip from './HelpTip'
import { Select } from './Select'
import Switch from './Switch'

interface Draft {
  key: string
  id: string | null
  name: string
  enabled: boolean
  message: string
  randomMessages: string
  mode: 'single' | 'random'
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
}

function fromSaved(item: AnnouncementInfo): Draft {
  return { key: item.id, id: item.id, name: item.name, enabled: item.enabled,
    message: item.messages[0] ?? '', randomMessages: item.messages.join('\n'), mode: item.message_mode,
    interval: String(item.interval_seconds), minimum: String(item.min_messages), availability: item.stream_availability }
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
    interval_seconds: interval, min_messages: minimum, stream_availability: draft.availability }
}

function time(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '—'
}

export default function AnnouncementsPanel({ active }: { active: boolean }) {
  const [saved, setSaved] = useState<AnnouncementInfo[] | null>(null)
  const [drafts, setDrafts] = useState<Draft[]>([])
  const baseline = useRef('[]')
  const initialized = useRef(false)
  const saveRevision = useRef(0)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [notice, setNotice] = useState('')
  const dirty = JSON.stringify(drafts) !== baseline.current
  const dirtyRef = useRef(false)
  dirtyRef.current = dirty

  useEffect(() => {
    if (!active) return
    let mounted = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = async () => {
      const revision = saveRevision.current
      try {
        const api = await waitForBridge()
        const result = await api.get_announcements()
        if (!mounted || revision !== saveRevision.current) return
        if (!result.ok || !Array.isArray(result.announcements)) throw new Error(result.error || 'Could not load announcements.')
        setSaved(result.announcements)
        if (!initialized.current || !dirtyRef.current) {
          const next = result.announcements.map(fromSaved)
          initialized.current = true
          baseline.current = JSON.stringify(next)
          setDrafts(next)
        }
        setLoadError('')
      } catch {
        if (mounted && revision === saveRevision.current) setLoadError('Could not refresh announcements. Check the connection and try again.')
      } finally {
        if (mounted) timer = setTimeout(() => void load(), 5000)
      }
    }
    void load()
    return () => { mounted = false; clearTimeout(timer) }
  }, [active])

  function update(key: string, patch: Partial<Draft>) {
    setDrafts((current) => current.map((draft) => draft.key === key ? { ...draft, ...patch } : draft))
    setNotice('')
  }

  async function save() {
    const payload = drafts.map(input)
    if (payload.some((item) => item === null)) {
      setError('Use a name of at most 80 UTF-8 bytes, 1–30 single-line messages of at most 450 UTF-8 bytes, an interval of 60–86400 seconds and a minimum of 0–1000 messages. Names and messages cannot contain control characters.')
      return
    }
    setBusy(true)
    setError('')
    saveRevision.current += 1
    try {
      const api = await waitForBridge()
      const result = await api.save_announcements(payload as AnnouncementInput[])
      if (!result.ok) throw new Error(result.error || 'Could not save announcements.')
      const refreshed = await api.get_announcements()
      if (!refreshed.ok) throw new Error('Announcements were saved, but the updated status could not be loaded. Refresh before editing again.')
      const next = refreshed.announcements.map(fromSaved)
      baseline.current = JSON.stringify(next)
      setDrafts(next)
      setSaved(refreshed.announcements)
      setExpanded({})
      setNotice('Announcements saved.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save announcements.')
    } finally { setBusy(false) }
  }

  return <section className="card command-editor-card announcements-panel" id="announcements" aria-busy={busy}>
    <div className="section-heading">
      <div><h2>Announcements</h2><p className="section-copy">Send scheduled ordinary chat messages.</p></div>
      <button className="primary" disabled={!saved || busy || drafts.length >= 50} onClick={() => {
        const key = crypto.randomUUID()
        setDrafts((current) => [...current, { key, id: null, name: '', enabled: true, message: '', randomMessages: '',
          mode: 'single', interval: '900', minimum: '0', availability: 'anytime' }])
        setExpanded((current) => ({ ...current, [key]: true }))
        setNotice('')
      }}>New announcement</button>
    </div>
    {error && <p className="inline-error" role="alert">{error}</p>}
    {loadError && <p className="inline-error" role="alert">{loadError}</p>}
    {notice && <p role="status">{notice}</p>}
    {saved === null ? <p className="muted">Loading announcements…</p> : <>
      {drafts.length === 0 && <p className="muted">No announcements configured.</p>}
      <div className="announcement-collection">
      <div className="command-list">{drafts.map((draft, index) => {
        const status = saved.find((item) => item.id === draft.id)?.status
        const prefix = `announcement-${draft.key}`
        return <article className="command-card announcement-card" key={draft.key}>
          <AccordionHeader title={<strong>{draft.name || `New announcement ${index + 1}`}</strong>}
            expanded={Boolean(expanded[draft.key])} contentId={`${prefix}-editor`}
            ariaLabel={`Edit announcement ${draft.name || index + 1}`}
            onToggle={() => setExpanded((current) => ({ ...current, [draft.key]: !current[draft.key] }))}
            helpLabel={`Announcement status ${draft.name || index + 1}`}
            help={<span className="announcement-status-details">
              <span>Next run: {status?.next_run_at ? time(status.next_run_at) : 'Waiting for connection or disabled'}</span>
              <span>Last sent: {time(status?.last_sent_at ?? null)}</span>
              <span>Last outcome: {status?.last_outcome ? outcomeLabels[status.last_outcome] ?? status.last_outcome : 'No attempts yet'}</span>
              <span>Eligible messages: {status?.eligible_messages ?? 0}</span>
              {!draft.id && <span>Save to schedule this announcement.</span>}
            </span>}
            badges={<span className={`state-pill ${draft.enabled ? 'enabled' : ''}`}>{draft.enabled ? 'Enabled' : 'Disabled'}</span>} />
          {status?.last_outcome && ['failed', 'not_confirmed', 'cancelled', 'skipped_stream'].includes(status.last_outcome) &&
            <p className={`announcement-outcome ${status.last_outcome === 'skipped_stream' ? 'muted' : 'inline-error'}`} role="status">
              Last outcome: {outcomeLabels[status.last_outcome]}
            </p>}
          {expanded[draft.key] && <fieldset disabled={busy} id={`${prefix}-editor`} className="announcement-editor" aria-label="Announcement settings">
            <div className="announcement-controls">
              <div className="announcement-name-row">
                <label className="form-field" htmlFor={`${prefix}-name`}>Name<input id={`${prefix}-name`} maxLength={80} value={draft.name} onChange={(event) => update(draft.key, { name: event.target.value })} /></label>
                <Switch className="announcement-enable" checked={draft.enabled} ariaLabel="Enable announcement" onCheckedChange={(enabled) => update(draft.key, { enabled })}>{null}</Switch>
              </div>
              <div className="form-field"><div className="custom-field-label"><label htmlFor={`${prefix}-interval`}>Interval (s)</label><HelpTip label="Announcement interval">Choose 60 to 86400 seconds. Startup, reconnect, channel changes and saved edits restart the full interval. Missed checks never create a catch-up backlog.</HelpTip></div>
                <input id={`${prefix}-interval`} type="number" min={60} max={86400} step={1} value={draft.interval} aria-invalid={integer(draft.interval, 60, 86400) === null} onChange={(event) => update(draft.key, { interval: event.target.value })} /></div>
              <div className="form-field"><div className="custom-field-label"><label htmlFor={`${prefix}-minimum`}>Trigger after</label><HelpTip label="Announcement activity">At each interval check, send only if this many eligible incoming messages arrived during this announcement’s current interval. This is a minimum activity condition, not an immediate message-count trigger. Each scheduled check starts a fresh activity window, including skipped checks. Own bot output and replayed events do not count. Zero allows quiet chat.</HelpTip></div>
                <div className="number-with-unit announcement-message-count"><input id={`${prefix}-minimum`} type="number" min={0} max={1000} step={1} value={draft.minimum} aria-invalid={integer(draft.minimum, 0, 1000) === null} onChange={(event) => update(draft.key, { minimum: event.target.value })} /><span aria-hidden="true">messages</span></div></div>
              <div className="form-field"><div className="custom-field-label"><label htmlFor={`${prefix}-availability`}>Works when:</label><HelpTip label="Announcement stream availability">Live only and Offline only require a fresh matching stream observation. Unknown or stale stream status pauses restricted sends on both Desktop and Server.</HelpTip></div>
                <Select id={`${prefix}-availability`} aria-label="Works when:" value={draft.availability} onChange={(availability) => update(draft.key, { availability: availability as StreamAvailability })} options={availabilityOptions} /></div>
              <div className="form-field"><div className="custom-field-label"><label htmlFor={`${prefix}-mode`}>Message selection</label><HelpTip label="Announcement messages">Single sends one plain-text line. Random chooses one of 1 to 30 non-empty lines per interval. Each line allows up to 450 UTF-8 bytes. Template variables are not expanded.</HelpTip></div>
                <Select id={`${prefix}-mode`} aria-label="Message selection" value={draft.mode} onChange={(mode) => update(draft.key, { mode: mode as Draft['mode'] })} options={[{ value: 'single', label: 'Single message' }, { value: 'random', label: 'Random message' }]} /></div>
            </div>
            <div className="form-field announcement-message">
              <textarea id={`${prefix}-message`} aria-label={draft.mode === 'random' ? 'Random messages' : 'Announcement message'} rows={draft.mode === 'random' ? 5 : 3} value={draft.mode === 'random' ? draft.randomMessages : draft.message} onChange={(event) => update(draft.key, draft.mode === 'random' ? { randomMessages: event.target.value } : { message: event.target.value })} />
            </div>
            <div className="announcement-remove"><button className="ghost destructive" onClick={() => { setDrafts((current) => current.filter((item) => item.key !== draft.key)); setNotice('') }}>Remove from draft</button></div>
          </fieldset>}
        </article>
      })}</div>
      <div className="row-actions announcement-actions">
        <HelpTip label="Saving announcements">Save announcements saves the entire collection, including enabled switches and removals, and restarts enabled schedules with a full interval. Cancel discards all unsaved announcement edits. Scheduling status is available from (?) beside each announcement’s name.</HelpTip>
        {dirty && <span className="mini-badge dirty-badge">Unsaved changes</span>}
        <button className="primary" disabled={busy || !dirty} onClick={() => void save()}>Save announcements</button>
        <button className="secondary" disabled={busy || !dirty} onClick={() => { setDrafts(JSON.parse(baseline.current) as Draft[]); setError(''); setNotice(''); setExpanded({}) }}>Cancel</button>
      </div>
      </div>
    </>}
  </section>
}
