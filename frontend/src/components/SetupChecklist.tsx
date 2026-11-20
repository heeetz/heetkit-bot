import { useEffect, useState } from 'react'
import { waitForBridge } from '../bridge'
import { dashboard } from '../i18n/dashboard'
import { useCatalog, useI18n } from '../i18n/core'

export default function SetupChecklist({ twitchConfigured, twitchAuthorized, twitchPending, aiConfigured, onTwitch, onAI }: {
  twitchConfigured: boolean; twitchAuthorized: boolean; twitchPending: boolean; aiConfigured: boolean
  onTwitch: () => void; onAI: () => void
}) {
  const text = useCatalog(dashboard).setup
  const { fmt } = useI18n()
  const [preferences, setPreferences] = useState<{ dismissed?: boolean; ai_skipped?: boolean } | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let current = true
    void waitForBridge().then((api) => api.get_setup_guide()).then((response) => {
      if (current && response.ok) setPreferences(response)
    }).catch(() => {})
    return () => { current = false }
  }, [])

  const twitchComplete = twitchConfigured && twitchAuthorized && !twitchPending
  if (!preferences || (twitchComplete && (aiConfigured || preferences.ai_skipped))) return null
  const open = expanded || !preferences.dismissed
  const twitchStatus = !twitchConfigured ? text.twitchStatus.configure
    : twitchPending ? text.twitchStatus.pending : twitchAuthorized ? text.twitchStatus.authorized : text.twitchStatus.authorize
  const save = async (dismissed: boolean, aiSkipped: boolean) => {
    setSaving(true)
    setError('')
    try {
      const response = await (await waitForBridge()).save_setup_guide(dismissed, aiSkipped)
      if (!response.ok) throw new Error(response.error || text.saveFailed)
      setPreferences(response)
      setExpanded(false)
    } catch (reason) {
      const detail = reason instanceof Error ? reason.message : text.saveFailed
      setError(fmt(dismissed ? text.retryDismiss : text.retrySkip, { detail }))
    } finally {
      setSaving(false)
    }
  }

  return <article className="card setup-checklist" aria-label={text.label}>
    <div className="section-heading">
      <div><h2>{open ? text.gettingStarted : text.summary}</h2>
        <p>{twitchStatus}{!preferences.ai_skipped && (aiConfigured ? text.aiStatus.configured : text.aiStatus.optional)}</p>
      </div>
      <button className="secondary" disabled={saving} onClick={() => open ? void save(true, Boolean(preferences.ai_skipped)) : setExpanded(true)}>{open ? text.dismiss : text.resume}</button>
    </div>
    {error && <p className="inline-error" role="alert">{error}</p>}
    {open && <ol>
      <li><div className="setup-guide-step">
        <p><strong>{text.connectTwitch}</strong>{text.required}{twitchComplete ? text.twitchDone
          : twitchPending ? text.twitchPending
          : twitchConfigured ? text.twitchAuthorize
          : text.twitchSave}</p>
        <div className="row-actions"><button className="secondary" onClick={onTwitch}>{text.openTwitch}</button></div>
      </div></li>
      {!preferences.ai_skipped && <li><div className="setup-guide-step">
        <p><strong>{text.setUpAI}</strong>{text.optional}{aiConfigured ? text.aiDone : text.aiConnect}</p>
        <div className="row-actions">
          {!aiConfigured && <button className="ghost" disabled={saving} onClick={() => void save(false, true)}>{text.skipAI}</button>}
          <button className="secondary" onClick={onAI}>{text.openAI}</button>
        </div>
      </div></li>}
    </ol>}
  </article>
}
