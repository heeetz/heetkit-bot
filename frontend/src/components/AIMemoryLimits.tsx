import { useEffect, useState, type ReactNode } from 'react'
import { waitForBridge } from '../bridge'
import HelpTip from './HelpTip'
import { aiText } from '../i18n/ai'
import { common as commonText } from '../i18n/common'
import { catalogFor, useCatalog } from '../i18n/core'

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
  const text = useCatalog(aiText).memory
  const common = useCatalog(commonText)

  useEffect(() => {
    if (!active || saved) return
    let current = true
    void (async () => {
      try {
        const result = await (await waitForBridge()).get_ai_memory_limits()
        if (!result.ok) throw new Error(result.error || catalogFor(aiText).memory.unavailable)
        if (current) {
          setSaved([result.stored, result.context])
          setStored(String(result.stored))
          setContext(String(result.context))
          setError('')
        }
      } catch {
        if (current) setError(catalogFor(aiText).memory.loadFailed)
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
      if (!result.ok) throw new Error(result.error || text.saveFailed)
      setSaved([n, m])
      setNotice(text.saved)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.saveFailed)
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
              <h2 id="ai-memory-title">{text.title}</h2>
              <HelpTip label={text.helpLabel} className="memory-limits-help">
                <ul>{text.help.map((item) => <li key={item}>{item}</li>)}</ul>
              </HelpTip>
            </div>
            <p className="memory-limits-hint">{text.hint}</p>
          </div>
        </div>
        <div className="memory-limits-controls">
          <div className="memory-limit-fields">
            <label className="form-field">{text.storedField}<input aria-label={text.storedAria} type="number" min="1" max="500" step="1" value={stored} disabled={!saved || busy} onChange={(event) => { setStored(event.target.value); setNotice('') }} /></label>
            <label className="form-field">{text.contextField}<input aria-label={text.contextAria} type="number" min="1" max="50" step="1" value={context} disabled={!saved || busy} onChange={(event) => { setContext(event.target.value); setNotice('') }} /></label>
          </div>
          <div className="memory-limits-toggle">{toggle}</div>
      </div>
      </div>
      {(dirty || error || notice) && <div className="memory-limits-feedback">
        {saved && !valid && <p className="inline-error" role="alert">{text.invalid}</p>}
        {error && <p role="alert" className="inline-error">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        {dirty && <div className="memory-limits-actions">
          {loweringStoredLimit && <p className="settings-hint" id="ai-memory-prune-warning">{text.pruneWarning}</p>}
          <div className="row-actions">
            <button type="button" className="secondary" disabled={busy} onClick={resetDraft}>{common.cancel}</button>
            <button type="submit" className="primary" aria-describedby={loweringStoredLimit ? 'ai-memory-prune-warning' : undefined} disabled={!valid || busy}>{text.save}</button>
          </div>
        </div>}
      </div>}
    </form>
  )
}
