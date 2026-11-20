import { type FormEvent, type ReactNode, useEffect, useState } from 'react'
import { type DesktopStartupStatus, waitForBridge } from '../bridge'
import HelpTip from './HelpTip'
import { shell } from '../i18n/app'
import { catalogFor, useCatalog, useI18n } from '../i18n/core'
import { loadDesktopLanguage } from '../i18n/language'

export default function DesktopStartup({ children }: { children: (windows: boolean) => ReactNode }) {
  const text = useCatalog(shell).startup
  const { fmt } = useI18n()
  const [status, setStatus] = useState<DesktopStartupStatus>({ state: 'starting' })
  const [channelId, setChannelId] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    void waitForBridge().then(async (api) => {
      await loadDesktopLanguage(api)
      const next = await api.get_desktop_startup()
      if (active) {
        setStatus(next)
        setChannelId(next.suggested_channel_id ?? '')
      }
    }).catch(() => {
      if (active) setStatus({ state: 'failed', error: catalogFor(shell).startup.unavailable })
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
      if (!result.ok) setError(result.error ?? text.notCompleted)
    } catch {
      setError(text.interrupted)
      setStatus({ state: 'failed' })
    } finally { setBusy(false) }
  }

  const cancel = async () => {
    setError('')
    try {
      const result = await (await waitForBridge()).cancel_desktop_startup()
      if (!result.ok) setError(result.error ?? text.closeToExit)
    } catch { setError(text.closeToExit) }
  }

  if (status.state === 'ready') return children(status.windows === true)
  return <main className="browser-login desktop-startup">
    <section className="card" aria-labelledby="startup-title" aria-busy={busy}>
      <div className="brand"><strong>HeetKit</strong></div>
      <h1 id="startup-title">{status.state === 'failed' ? text.titleFailed : status.state === 'starting' ? text.titleStarting : text.titleMapping}</h1>
      {status.state === 'starting' && <p role="status">{text.waiting}</p>}
      {status.state === 'mapping_required' && <>
        <p>{text.mappingIntro}</p>
        <form onSubmit={(event) => void submit(event)}>
          <label className="form-field" htmlFor="legacy-channel-id">{text.channelId}
            <input id="legacy-channel-id" inputMode="numeric" autoComplete="off" spellCheck={false} maxLength={32}
              value={channelId} disabled={busy} onChange={(event) => { setChannelId(event.target.value); setConfirmed(false) }} />
          </label>
          <p>{text.verify}</p>
          {status.suggested_channel_id && <p className="muted">{fmt(text.currentTarget, { channel: status.suggested_channel || text.channelFallback, id: status.suggested_channel_id })}</p>}
          <label className="startup-confirmation"><input type="checkbox" checked={confirmed} disabled={busy}
            onChange={(event) => setConfirmed(event.target.checked)} />{text.confirmLabel}</label>
          <p>{text.backupNote}{' '}
            <HelpTip label={text.backupHelp}><ul>{text.backupItems.map((item) => <li key={item}>{item}</li>)}</ul></HelpTip>
          </p>
          <div className="row-actions"><button className="secondary" type="button" disabled={busy} onClick={() => void cancel()}>{text.cancelExit}</button>
            <button className="primary" type="submit" disabled={busy || !confirmed || !/^[0-9]{1,32}$/.test(channelId)}>{busy ? text.upgrading : text.confirm}</button></div>
        </form>
      </>}
      {(status.error || error) && <p className="inline-error" role="alert">{error || status.error}</p>}
      {status.state === 'failed' && <button type="button" className="secondary" onClick={() => void cancel()}>{text.exit}</button>}
    </section>
  </main>
}
