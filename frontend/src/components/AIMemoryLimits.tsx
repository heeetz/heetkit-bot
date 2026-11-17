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
      <div className="memory-limits-intro">
        <div className="memory-limits-heading">
          <h2 id="ai-memory-title">Conversation memory</h2>
          <HelpTip label="Conversation memory">The switch saves immediately. Turning memory off stops use and storage. Previously stored pairs remain subject to count limits and 60-day expiry. One pair means one question and its successful answer. N caps stored pairs per viewer per channel. M caps pairs sent as model context. Saving a lower N immediately prunes older pairs, including recovery copies. Playground never reads or stores viewer memory. The erasure command in Administrative commands clears AI memory for a known viewer in that channel.</HelpTip>
        </div>
        <p className="muted">Use earlier exchanges in AI chat replies.</p>
      </div>
      <div className="memory-limits-controls">
        <div className="memory-limit-fields">
          <label className="form-field">Stored pairs (N)<input type="number" min="1" max="500" step="1" value={stored} disabled={!saved || busy} onChange={(event) => { setStored(event.target.value); setNotice('') }} /></label>
          <label className="form-field">Context pairs (M)<input type="number" min="1" max="50" step="1" value={context} disabled={!saved || busy} onChange={(event) => { setContext(event.target.value); setNotice('') }} /></label>
        </div>
        <div className="memory-limits-toggle">{toggle}</div>
      </div>
      {(dirty || error || notice) && <div className="memory-limits-feedback">
        {saved && !valid && <p className="inline-error" role="alert">N must be 1–500. M must be 1–50 and no greater than N.</p>}
        {error && <p role="alert" className="inline-error">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        {dirty && <div className="memory-limits-actions">
          <p className="muted">Saving a lower N permanently removes older pairs.</p>
          <div className="row-actions">
            <button type="button" className="secondary" disabled={busy} onClick={resetDraft}>Cancel</button>
            <button type="submit" className="primary" disabled={!valid || busy}>Save memory limits</button>
          </div>
        </div>}
      </div>}
    </form>
  )
}
