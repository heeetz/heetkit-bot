import { type FormEvent, type ReactNode, useEffect, useState } from 'react'
import { type DesktopStartupStatus, waitForBridge } from '../bridge'
import HelpTip from './HelpTip'

export default function DesktopStartup({ children }: { children: (windows: boolean) => ReactNode }) {
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

  if (status.state === 'ready') return children(status.windows === true)
  return <main className="browser-login desktop-startup">
    <section className="card" aria-labelledby="startup-title" aria-busy={busy}>
      <div className="brand"><strong>HeetKit</strong></div>
      <h1 id="startup-title">{status.state === 'failed' ? 'Startup needs attention' : status.state === 'starting' ? 'Starting HeetKit' : 'Choose a channel for existing history'}</h1>
      {status.state === 'starting' && <p role="status">Waiting for Desktop startup…</p>}
      {status.state === 'mapping_required' && <>
        <p>Some viewer activity and AI history was saved without a channel. Choose the Twitch channel that all of that history belongs to.</p>
        <form onSubmit={(event) => void submit(event)}>
          <label className="form-field" htmlFor="legacy-channel-id">Numeric Twitch channel ID
            <input id="legacy-channel-id" inputMode="numeric" autoComplete="off" spellCheck={false} maxLength={32}
              value={channelId} disabled={busy} onChange={(event) => { setChannelId(event.target.value); setConfirmed(false) }} />
          </label>
          <p>Verify the numeric channel ID in Twitch before confirming. Your choice assigns all history saved without a channel to that channel.</p>
          {status.suggested_channel_id && <p className="muted">Current target channel: {status.suggested_channel || 'channel'} ({status.suggested_channel_id}).</p>}
          <label className="startup-confirmation"><input type="checkbox" checked={confirmed} disabled={busy}
            onChange={(event) => setConfirmed(event.target.checked)} />I confirm this channel for all unscoped history.</label>
          <p>HeetKit verifies a recovery backup before upgrading the database.{' '}
            <HelpTip label="Backup and retention">The private recovery backup expires after seven days. History already assigned to a channel keeps that channel and its original dates. Existing retention and opt-out rules still apply.</HelpTip>
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
