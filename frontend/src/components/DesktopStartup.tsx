import { type FormEvent, type ReactNode, useEffect, useState } from 'react'
import { type DesktopStartupStatus, waitForBridge } from '../bridge'
import HelpTip from './HelpTip'

export default function DesktopStartup({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<DesktopStartupStatus>({ state: 'starting' })
  const [channelId, setChannelId] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    void waitForBridge().then(async (api) => {
      const next = await api.get_desktop_startup()
      if (active) {
        setStatus(next)
        setChannelId(next.suggested_channel_id ?? '')
      }
    }).catch(() => {
      if (active) setStatus({ state: 'failed', error: 'Desktop startup is unavailable. Close HeetKit and review the startup error, then retry.' })
    })
    return () => { active = false }
  }, [])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || !confirmed || !/^[0-9]{1,32}$/.test(channelId)) return
    setBusy(true)
    setError('')
    try {
      const api = await waitForBridge()
      const result = await api.confirm_legacy_channel(channelId, confirmed)
      const next = await api.get_desktop_startup()
      setStatus(!result.ok && next.state === 'starting' ? { state: 'failed' } : next)
      if (!result.ok) setError(result.error ?? 'Startup did not complete. Close HeetKit and review the startup error.')
    } catch {
      setError('Startup confirmation was interrupted. Close HeetKit and review the saved channel choice before retrying.')
      setStatus({ state: 'failed' })
    } finally { setBusy(false) }
  }

  const cancel = async () => {
    setError('')
    try {
      const result = await (await waitForBridge()).cancel_desktop_startup()
      if (!result.ok) setError(result.error ?? 'Close the Desktop window to exit.')
    } catch { setError('Close the Desktop window to exit.') }
  }

  if (status.state === 'ready') return children
  return <main className="browser-login desktop-startup">
    <section className="card" aria-labelledby="startup-title" aria-busy={busy}>
      <div className="brand"><strong>HeetKit</strong></div>
      <h1 id="startup-title">{status.state === 'failed' ? 'Startup needs attention' : status.state === 'starting' ? 'Starting HeetKit' : 'Choose a channel for existing history'}</h1>
      {status.state === 'starting' && <p role="status">Waiting for Desktop startup…</p>}
      {status.state === 'mapping_required' && <>
        <p>Existing presence and AI history has no channel. Choose the channel that all unscoped history belongs to before continuing.</p>
        <form onSubmit={(event) => void submit(event)}>
          <label className="form-field" htmlFor="legacy-channel-id">Numeric Twitch channel ID
            <input id="legacy-channel-id" inputMode="numeric" autoComplete="off" spellCheck={false} maxLength={32}
              value={channelId} disabled={busy} onChange={(event) => { setChannelId(event.target.value); setConfirmed(false) }} />
          </label>
          {status.suggested_channel_id && <p className="muted">Configured target: {status.suggested_channel || 'channel'} ({status.suggested_channel_id}). This suggestion does not verify where older history came from.</p>}
          <label className="startup-confirmation"><input type="checkbox" checked={confirmed} disabled={busy}
            onChange={(event) => setConfirmed(event.target.checked)} />I confirm this channel for all unscoped history.</label>
          <p>HeetKit saves this choice for this profile, verifies a recovery backup, then upgrades the database.
            <HelpTip label="History migration">Verify the numeric channel ID with Twitch before confirming. This is your attribution choice, not verified historical provenance. Already-scoped rows keep their channels and original dates. Existing retention and opt-out rules apply. The private recovery snapshot expires seven days after creation. Cancel leaves the channel choice unsaved.</HelpTip>
          </p>
          <div className="row-actions"><button className="secondary" type="button" disabled={busy} onClick={() => void cancel()}>Cancel and exit</button>
            <button className="primary" type="submit" disabled={busy || !confirmed || !/^[0-9]{1,32}$/.test(channelId)}>{busy ? 'Upgrading history…' : 'Confirm channel and continue'}</button></div>
        </form>
      </>}
      {(status.error || error) && <p className="inline-error" role="alert">{error || status.error}</p>}
      {status.state === 'failed' && <button type="button" className="secondary" onClick={() => void cancel()}>Exit HeetKit</button>}
    </section>
  </main>
}
