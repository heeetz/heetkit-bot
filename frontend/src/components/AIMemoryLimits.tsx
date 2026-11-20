import { useEffect, useState, type ReactNode } from 'react'
import { waitForBridge } from '../bridge'
import HelpTip from './HelpTip'

export default function AIMemoryLimits({ active, toggle, onDirty }: {
  active: boolean
  toggle: ReactNode
  onDirty: (dirty: boolean) => void
}) {
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
        if (current) {
          setSaved([result.stored, result.context])
          setStored(String(result.stored))
          setContext(String(result.context))
          setError('')
        }
      } catch {
        if (current) setError('Could not load memory limits. Reopen AI to retry.')
      }
    })()
    return () => { current = false }
  }, [active, saved])

  const resetDraft = () => {
    if (saved) {
      setStored(String(saved[0]))
      setContext(String(saved[1]))
      setError('')
    }
    setNotice('')
  }

  const n = Number(stored), m = Number(context)
  const valid = /^\d+$/.test(stored) && /^\d+$/.test(context) && n >= 1 && n <= 500 && m >= 1 && m <= 50 && m <= n
  const dirty = Boolean(saved && (!valid || n !== saved[0] || m !== saved[1]))
  const loweringStoredLimit = Boolean(saved && valid && n < saved[0])
  useEffect(() => { onDirty(dirty) }, [dirty, onDirty])

  const save = async () => {
    if (!valid || !dirty || busy) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await (await waitForBridge()).save_ai_memory_limits(n, m)
      if (!result.ok) throw new Error(result.error || 'Could not save memory limits.')
      setSaved([n, m])
      setNotice('Memory limits saved.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save memory limits.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form id="ai-memory" className="card memory-limits" aria-labelledby="ai-memory-title"
      onSubmit={(event) => { event.preventDefault(); void save() }}>
      <div className="memory-limits-layout">
        <div className="memory-limits-intro">
          <div className="memory-limits-heading">
            <div className="memory-limits-title">
              <h2 id="ai-memory-title">Conversation memory</h2>
              <HelpTip label="How memory works" className="memory-limits-help">
                <p>A pair is one question and its successful answer. HeetKit keeps pairs for up to 60 days, within the stored-pair limit (N) for each viewer and channel.</p>
                <p>Context pairs (M) sets how many exchanges to send with the next AI request, up to N. For example, setting M to 2 sends up to the last 2 exchanges.</p>
                <p>The switch saves immediately. Turning memory off stops saving and using exchanges. HeetKit keeps previously saved exchanges.</p>
                <p>Playground never reads or stores viewer memory. The erase command clears AI memory for a known viewer in that channel.</p>
              </HelpTip>
            </div>
            <p className="memory-limits-hint">Use earlier exchanges in AI chat replies.</p>
          </div>
        </div>
        <div className="memory-limits-controls">
          <div className="memory-limit-fields">
            <label className="form-field">Stored pairs (N)<input aria-label="Stored pairs" type="number" min="1" max="500" step="1" value={stored} disabled={!saved || busy} onChange={(event) => { setStored(event.target.value); setNotice('') }} /></label>
            <label className="form-field">Context pairs (M)<input aria-label="Pairs in context" type="number" min="1" max="50" step="1" value={context} disabled={!saved || busy} onChange={(event) => { setContext(event.target.value); setNotice('') }} /></label>
          </div>
          <div className="memory-limits-toggle">{toggle}</div>
      </div>
      </div>
      {(dirty || error || notice) && <div className="memory-limits-feedback">
        {saved && !valid && <p className="inline-error" role="alert">N must be 1–500. M must be 1–50 and no greater than N.</p>}
        {error && <p role="alert" className="inline-error">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        {dirty && <div className="memory-limits-actions">
          {loweringStoredLimit && <p className="settings-hint" id="ai-memory-prune-warning">Saving this lower limit can permanently delete older pairs, including recovery copies.</p>}
          <div className="row-actions">
            <button type="button" className="secondary" disabled={busy} onClick={resetDraft}>Cancel</button>
            <button type="submit" className="primary" aria-describedby={loweringStoredLimit ? 'ai-memory-prune-warning' : undefined} disabled={!valid || busy}>Save memory limits</button>
          </div>
        </div>}
      </div>}
    </form>
  )
}
