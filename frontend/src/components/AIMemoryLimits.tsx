import { useEffect, useState } from 'react'
import { waitForBridge } from '../bridge'
import HelpTip from './HelpTip'

export default function AIMemoryLimits({ active }: { active: boolean }) {
  const [saved, setSaved] = useState<[number, number] | null>(null)
  const [stored, setStored] = useState('')
  const [context, setContext] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  useEffect(() => {
    if (!active || saved) return
    let current = true
    void (async () => {
      try {
        const result = await (await waitForBridge()).get_ai_memory_limits()
        if (!result.ok) throw new Error(result.error || 'Memory limits unavailable.')
        if (current) { setSaved([result.stored, result.context]); setStored(String(result.stored)); setContext(String(result.context)) }
      } catch { if (current) setError('Could not load memory limits. Reopen AI to retry.') }
    })()
    return () => { current = false }
  }, [active, saved])
  const n = Number(stored), m = Number(context)
  const valid = /^\d+$/.test(stored) && /^\d+$/.test(context) && n >= 1 && n <= 500 && m >= 1 && m <= 50 && m <= n
  const dirty = saved && (n !== saved[0] || m !== saved[1])
  return <form className="memory-limits" onSubmit={(event) => {
    event.preventDefault()
    if (!valid) return
    setBusy(true); setError(''); setNotice('')
    void (async () => {
      try {
        const result = await (await waitForBridge()).save_ai_memory_limits(n, m)
        if (!result.ok) throw new Error(result.error || 'Could not save memory limits.')
        setSaved([n, m]); setNotice('Memory limits saved.')
      } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save memory limits.') }
      finally { setBusy(false) }
    })()
  }}>
    <div className="ai-state-heading"><strong>Exchange limits</strong><HelpTip label="Exchange limits">One pair means one question and its successful answer. N caps stored pairs per viewer per channel; M caps pairs sent as model context. The count cap and 60-day expiry both apply. Saving a lower N immediately prunes older pairs, including recovery copies. Turning memory off stops use and storage; these saved limits still apply when re-enabled.</HelpTip></div>
    <label className="form-field">Stored pairs (N)<input type="number" min="1" max="500" step="1" value={stored} disabled={!saved || busy} onChange={(e) => { setStored(e.target.value); setNotice('') }} /></label>
    <label className="form-field">Context pairs (M)<input type="number" min="1" max="50" step="1" value={context} disabled={!saved || busy} onChange={(e) => { setContext(e.target.value); setNotice('') }} /></label>
    {saved && !valid && <p className="inline-error" role="alert">N must be 1–500; M must be 1–50 and no greater than N.</p>}
    <p className="muted">Saving a lower N permanently removes older pairs. Stored pairs also expire after 60 days.</p>
    <div className="editor-actions"><button className="primary" disabled={!dirty || !valid || busy}>Save memory limits</button><button type="button" className="secondary" disabled={!dirty || busy} onClick={() => { setStored(String(saved![0])); setContext(String(saved![1])); setError(''); setNotice('') }}>Cancel</button></div>
    {error && <p role="alert" className="inline-error">{error}</p>}{notice && <p role="status">{notice}</p>}
  </form>
}
