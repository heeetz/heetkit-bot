import { useEffect, useState } from 'react'
import { waitForBridge } from '../bridge'

export default function SetupChecklist({ twitchConfigured, twitchConnected, aiConfigured, onTwitch, onAI }: {
  twitchConfigured: boolean; twitchConnected: boolean; aiConfigured: boolean; onTwitch: () => void; onAI: () => void
}) {
  const [preferences, setPreferences] = useState<{ dismissed?: boolean; ai_skipped?: boolean } | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let current = true
    void waitForBridge().then((api) => api.get_setup_guide()).then((response) => { if (current && response.ok) setPreferences(response) }).catch(() => {})
    return () => { current = false }
  }, [])
  if (!preferences) return null
  const complete = twitchConfigured && (aiConfigured || preferences.ai_skipped)
  const open = expanded || (!preferences.dismissed && !complete)
  const save = async (dismissed: boolean, ai_skipped: boolean) => {
    try {
      const response = await (await waitForBridge()).save_setup_guide(dismissed, ai_skipped)
      if (!response.ok) throw new Error(response.error || 'Setup guidance could not be saved.')
      setPreferences(response); setExpanded(false); setError('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Setup guidance could not be saved.') }
  }
  return <article className="card setup-checklist" aria-label="Setup checklist">
    <div className="section-heading"><div><h2>{open ? 'Getting started' : 'Setup summary'}</h2><p>Twitch {twitchConnected ? 'connected and authorized' : twitchConfigured ? 'configured; authorization not confirmed this session' : 'needs configuration'} · AI {aiConfigured ? 'configured; generation access unverified' : preferences.ai_skipped ? 'skipped (optional)' : 'optional'}</p></div>
      <button className="secondary" onClick={() => open ? void save(true, Boolean(preferences.ai_skipped)) : setExpanded(true)}>{open ? 'Dismiss setup guide' : 'Resume setup guide'}</button></div>
    {error && <p role="alert">{error}</p>}
    {open && <ol><li><strong>Connect Twitch</strong> (required for chat). {twitchConnected ? 'Connected.' : twitchConfigured ? 'Configured. Start or authorize from Dashboard to connect.' : 'Save your Twitch settings and authorize your account.'}<button className="secondary" onClick={onTwitch}>Open Twitch setup</button></li>
      <li><strong>Set up AI</strong> (optional). Configure it whenever you like.<div className="row-actions"><button className="secondary" onClick={onAI}>Open AI setup</button><button className="ghost" onClick={() => void save(false, true)}>Skip AI for now</button></div></li>
      <li><strong>Ready to start</strong>. {twitchConfigured ? 'Use the Dashboard session controls. Configured and connected are separate states.' : 'Complete Twitch setup before starting chat. AI is optional.'}</li></ol>}
  </article>
}
