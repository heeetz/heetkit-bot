import { useEffect, useState } from 'react'
import { waitForBridge } from '../bridge'
import { settingsText } from '../i18n/settings'
import { catalogFor, useCatalog } from '../i18n/core'

const MAX_SECONDS = 60

/** Global pause between bot messages; saves when the value is committed. */
export default function ReplyIntervalSetting() {
  const text = useCatalog(settingsText).replyInterval
  const [saved, setSaved] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    void (async () => {
      try {
        const result = await (await waitForBridge()).get_reply_interval()
        if (!result.ok || typeof result.seconds !== 'number') throw new Error(result.error ?? catalogFor(settingsText).replyInterval.loadFailed)
        setSaved(result.seconds)
        setDraft(String(result.seconds))
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : catalogFor(settingsText).replyInterval.loadFailed)
      }
    })()
  }, [])

  const commit = async () => {
    const seconds = Number(draft)
    if (saved === null || busy || draft.trim() === '' || seconds === saved) {
      if (saved !== null) setDraft(String(saved))
      return
    }
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await (await waitForBridge()).set_reply_interval(seconds)
      if (!result.ok || typeof result.seconds !== 'number') throw new Error(result.error ?? text.saveFailed)
      setSaved(result.seconds)
      setDraft(String(result.seconds))
      setNotice(text.saved)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.saveFailed)
    } finally {
      setBusy(false)
    }
  }

  return <div className="interface-setting">
    <div className="interface-language-copy">
      <h2 id="reply-interval-heading">{text.label}</h2>
      <p className="section-copy">{text.hint}</p>
    </div>
    <div className="form-field reply-interval-field">
      <span className="reply-interval-input">
        <input id="reply-interval" type="number" inputMode="numeric" min={0} max={MAX_SECONDS} step={1}
          aria-labelledby="reply-interval-heading" value={draft} disabled={saved === null || busy}
          onChange={(event) => { setDraft(event.target.value); setNotice('') }}
          onBlur={() => void commit()}
          onKeyDown={(event) => { if (event.key === 'Enter') void commit() }} />
        <span>{text.seconds}</span>
      </span>
      {error && <p className="inline-error" role="alert">{error}</p>}
      {notice && !error && <p className="settings-hint" role="status">{notice}</p>}
    </div>
  </div>
}
