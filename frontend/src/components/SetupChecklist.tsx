import { useEffect, useState } from 'react'
import { waitForBridge } from '../bridge'

export default function SetupChecklist({ twitchConfigured, twitchAuthorized, twitchPending, aiConfigured, onTwitch, onAI }: {
  twitchConfigured: boolean; twitchAuthorized: boolean; twitchPending: boolean; aiConfigured: boolean
  onTwitch: () => void; onAI: () => void
}) {
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
  const twitchStatus = !twitchConfigured ? 'needs configuration'
    : twitchPending ? 'changes pending' : twitchAuthorized ? 'authorized' : 'needs authorization'
  const save = async (dismissed: boolean, aiSkipped: boolean) => {
    setSaving(true)
    setError('')
    try {
      const response = await (await waitForBridge()).save_setup_guide(dismissed, aiSkipped)
      if (!response.ok) throw new Error(response.error || 'Setup guidance could not be saved.')
      setPreferences(response)
      setExpanded(false)
    } catch (reason) {
      const detail = reason instanceof Error ? reason.message : 'Setup guidance could not be saved.'
      setError(`${detail} Select ${dismissed ? 'Dismiss setup guide' : 'Skip AI for now'} to retry.`)
    } finally {
      setSaving(false)
    }
  }

  return <article className="card setup-checklist" aria-label="Setup checklist">
    <div className="section-heading">
      <div><h2>{open ? 'Getting started' : 'Setup summary'}</h2>
        <p>Twitch {twitchStatus}{!preferences.ai_skipped && ` · AI ${aiConfigured ? 'configured' : 'optional'}`}</p>
      </div>
      <button className="secondary" disabled={saving} onClick={() => open ? void save(true, Boolean(preferences.ai_skipped)) : setExpanded(true)}>{open ? 'Dismiss setup guide' : 'Resume setup guide'}</button>
    </div>
    {error && <p className="inline-error" role="alert">{error}</p>}
    {open && <ol>
      <li><div className="setup-guide-step">
        <p><strong>Connect Twitch</strong> (required for chat). {twitchComplete ? 'Authorized. Use the Dashboard session controls to connect.'
          : twitchPending ? 'Apply the saved Twitch changes before connecting.'
          : twitchConfigured ? 'Authorize the bot account to finish Twitch setup.'
          : 'Save your Twitch settings, then authorize the bot account.'}</p>
        <div className="row-actions"><button className="secondary" onClick={onTwitch}>Open Twitch setup</button></div>
      </div></li>
      {!preferences.ai_skipped && <li><div className="setup-guide-step">
        <p><strong>Set up AI</strong> (optional). {aiConfigured ? 'Configured. Manage providers and models in AI setup.' : 'Connect an AI provider to answer questions in chat.'}</p>
        <div className="row-actions">
          {!aiConfigured && <button className="ghost" disabled={saving} onClick={() => void save(false, true)}>Skip AI for now</button>}
          <button className="secondary" onClick={onAI}>Open AI setup</button>
        </div>
      </div></li>}
    </ol>}
  </article>
}
