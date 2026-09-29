import { useEffect, useState } from 'react'

import { type AppSettings, waitForBridge } from '../bridge'

interface SettingsPageProps {
  active: boolean
}

export default function SettingsPage({ active }: SettingsPageProps) {
  const [saved, setSaved] = useState<AppSettings | null>(null)
  const [draft, setDraft] = useState<AppSettings | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!active) {
      return
    }
    let mounted = true
    const load = async () => {
      try {
        const api = await waitForBridge()
        const response = await api.get_app_settings()
        if (!response.ok || !response.settings) {
          throw new Error(response.error ?? 'Desktop settings are unavailable.')
        }
        if (mounted) {
          setDraft((current) => {
            const dirty = current && saved && JSON.stringify(current) !== JSON.stringify(saved)
            return dirty ? current : response.settings!
          })
          setSaved(response.settings)
          setError('')
        }
      } catch (reason) {
        if (mounted) {
          setError(reason instanceof Error ? reason.message : 'Could not load desktop settings.')
        }
      }
    }
    void load()
    return () => { mounted = false }
  }, [active])

  const updateDraft = (values: Partial<AppSettings>) => {
    setDraft((current) => current ? { ...current, ...values } : current)
    setNotice('')
  }

  const save = async () => {
    if (!draft) {
      return
    }
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.update_app_settings(
        draft.start_minimized,
        draft.minimize_to_tray,
        draft.close_to_tray,
      )
      if (!result.ok) {
        throw new Error(result.error ?? 'Desktop settings could not be saved.')
      }
      setSaved(draft)
      setNotice('Desktop settings saved.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Desktop settings could not be saved.')
    } finally {
      setBusy(false)
    }
  }

  const dirty = Boolean(
    draft && saved && JSON.stringify(draft) !== JSON.stringify(saved),
  )

  return (
    <section className="card settings-page">
      <div className="section-heading">
        <div>
          <p className="label">DESKTOP APPLICATION</p>
          <h2>Window and tray behavior</h2>
          <p className="section-copy">These settings are local to this computer.</p>
        </div>
        {dirty && <span className="mini-badge dirty-badge">Edited</span>}
      </div>
      {error && <div className="inline-error">{error}</div>}
      {notice && <div className="inline-success">{notice}</div>}
      {!draft ? <p className="muted">Loading desktop settings…</p> : (
        <div className="settings-list">
          <label className="settings-option">
            <input type="checkbox" checked={draft.start_minimized} onChange={(event) => updateDraft({ start_minimized: event.target.checked })} />
            <span><strong>Start minimized</strong><small>Start with the window hidden and the tray icon available. Takes effect on next launch.</small></span>
          </label>
          <label className="settings-option">
            <input type="checkbox" checked={draft.minimize_to_tray} onChange={(event) => updateDraft({ minimize_to_tray: event.target.checked })} />
            <span><strong>Minimize to tray</strong><small>Hide the window when it is minimized while keeping the bot running.</small></span>
          </label>
          <label className="settings-option">
            <input type="checkbox" checked={draft.close_to_tray} onChange={(event) => updateDraft({ close_to_tray: event.target.checked })} />
            <span><strong>Close to tray</strong><small>Hide the window instead of exiting when the close button is used.</small></span>
          </label>
          <div className="settings-actions">
            <button className="primary" disabled={!dirty || busy} onClick={() => void save()}>{busy ? 'Saving…' : 'Save settings'}</button>
          </div>
        </div>
      )}
    </section>
  )
}
