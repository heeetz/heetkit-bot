import { useEffect, useRef, useState } from 'react'
import { type AIPlaygroundResult, waitForBridge } from '../bridge'
import HelpTip from './HelpTip'
import { aiText } from '../i18n/ai'
import { catalogFor, useCatalog, useI18n } from '../i18n/core'

function linkedResponse(text: string) {
  return text.split(/(https?:\/\/[^\s<>]+)/g).map((part, index) => {
    if (!/^https?:\/\//.test(part)) return part
    try {
      const url = new URL(part)
      if (!url.username && !url.password) return <a key={index} href={url.href} target="_blank" rel="noopener noreferrer">{part}</a>
    } catch { /* Invalid URLs remain plain text. */ }
    return part
  })
}

function searchOutcome(result: AIPlaygroundResult, text: typeof aiText.en.playground.search): string {
  if (result.status === 'search_error') return text.failed
  if (result.status === 'search_unavailable') return text.offOnFallback
  if (result.status === 'attribution_unavailable' || (result.status === 'output_blocked' && result.generation?.search_used)) {
    return text.withheld
  }
  if (result.generation?.search_used) return text.used
  if (!result.generation?.search_enabled) return text.off
  if (result.status === 'success') return text.unused
  return result.generation.search_requested ? text.unconfirmed : text.unavailable
}

export default function AIPlayground({ active, hasDrafts = false }: { active: boolean; hasDrafts?: boolean }) {
  const [prompt, setPrompt] = useState('')
  const [pending, setPending] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [requestId, setRequestId] = useState<string | null>(null)
  const [result, setResult] = useState<AIPlaygroundResult | null>(null)
  const [error, setError] = useState('')
  const currentId = useRef<string | null>(null)
  const submitting = useRef(false)
  const generation = useRef(0)
  const text = useCatalog(aiText).playground
  const { fmt } = useI18n()

  useEffect(() => {
    return () => {
      generation.current += 1
      submitting.current = false
      const id = currentId.current
      currentId.current = null
      setRequestId(null)
      setPending(false)
      setCancelling(false)
      if (id) void waitForBridge().then((api) => api.cancel_ai_playground(id)).catch(() => {})
    }
  }, [active])

  useEffect(() => {
    if (!requestId || !active) return
    let stopped = false
    let timer: number | undefined
    const poll = async () => {
      try {
        const api = await waitForBridge()
        const response = await api.get_ai_playground_result(requestId)
        if (stopped || currentId.current !== requestId) return
        if (!response.ok || !response.status) throw new Error(response.error ?? catalogFor(aiText).playground.readFailed)
        if (response.status === 'pending') {
          timer = window.setTimeout(() => void poll(), 500)
          return
        }
        setResult(response)
        setError('')
      } catch {
        if (stopped || currentId.current !== requestId) return
        setError(catalogFor(aiText).playground.readRetry)
        void waitForBridge().then((api) => api.cancel_ai_playground(requestId)).catch(() => {})
      }
      if (!stopped && currentId.current === requestId) {
        currentId.current = null
        submitting.current = false
        setRequestId(null)
        setPending(false)
        setCancelling(false)
      }
    }
    void poll()
    return () => { stopped = true; window.clearTimeout(timer) }
  }, [requestId, active])

  const submit = async () => {
    if (submitting.current || !active || !prompt.trim()) return
    submitting.current = true
    const attempt = ++generation.current
    setPending(true)
    setResult(null)
    setError('')
    try {
      const api = await waitForBridge()
      const response = await api.start_ai_playground(prompt)
      if (attempt !== generation.current) {
        if (response.ok && response.request_id) await api.cancel_ai_playground(response.request_id)
        return
      }
      if (!response.ok || !response.request_id) throw new Error(response.error ?? text.startFailed)
      currentId.current = response.request_id
      setRequestId(response.request_id)
    } catch (reason) {
      if (attempt !== generation.current) return
      setError(reason instanceof Error ? reason.message : text.startFailed)
      setPending(false)
      submitting.current = false
    }
  }

  const cancel = async () => {
    const id = currentId.current
    if (!id || cancelling) return
    setCancelling(true)
    try {
      const api = await waitForBridge()
      const response = await api.cancel_ai_playground(id)
      if (!response.ok) throw new Error()
    } catch {
      if (currentId.current === id) {
        setError(text.cancelFailed)
        setCancelling(false)
      }
    }
  }

  return (
    <article className="card ai-playground" id="ai-playground">
      <div className="section-heading">
        <div>
          <h2>{text.title}</h2>
          <p className="section-copy">{text.copy}</p>
        </div>
        <HelpTip label={text.helpLabel}>
          <ul>{text.help.map((item) => <li key={item}>{item}</li>)}</ul>
        </HelpTip>
      </div>
      {hasDrafts && <p className="setting-effect playground-draft-warning">{text.draftWarning}</p>}
      <label className="form-field">
        {text.prompt}
        <textarea value={prompt} disabled={pending} placeholder={text.placeholder} onChange={(event) => {
          setPrompt(event.target.value)
          setResult(null)
          setError('')
        }} />
      </label>
      <div className="row-actions">
        <button className="primary" disabled={pending || !prompt.trim()} onClick={() => void submit()}>{pending ? text.testing : text.test}</button>
        {pending && <button className="secondary" disabled={!requestId || cancelling} onClick={() => void cancel()}>{cancelling ? text.cancelling : text.cancel}</button>}
      </div>
      {error && <p role="alert" className="error-text">{error}</p>}
      <div className="playground-result" role="status" aria-live="polite">
        {pending && <p>{cancelling ? text.cancelling : text.status.pending}</p>}
        {result?.status && <>
          <strong>{result.status === 'attribution_unavailable' && result.generation?.provider === 'Google Gemini'
            ? text.geminiWithheld
            : text.status[result.status]}</strong>
          {result.generation && <p className="setting-effect">
            {fmt(text.providerModel, { provider: result.generation.provider, model: result.generation.model })}
            {' · '}{fmt(text.thinking, { value: result.generation.thinking })}
            {' · '}{result.generation.fallback_used ? text.fallbackUsed : text.primarySelection}
            {' · '}{fmt(text.searchFetch, { value: searchOutcome(result, text.search) })}
            {result.generation.input_tokens != null && <>{' · '}{fmt(text.inputTokens, { count: String(result.generation.input_tokens) })}</>}
            {result.generation.output_tokens != null && <>{' · '}{fmt(text.outputTokens, { count: String(result.generation.output_tokens) })}</>}
          </p>}
          {result.moderation_source === 'editable_filter' && <p>{fmt(text.editableFilter, { category: result.matched_category ?? '' })}<code>{result.matched_rule}</code></p>}
          {result.moderation_source === 'filter_timeout' && <p>{text.filterTimeout}</p>}
          {result.moderation_source === 'protected_policy' && <p>{text.protectedPolicy}</p>}
          {result.status === 'success' && <p className="playground-response">{linkedResponse(result.text ?? '')}</p>}
        </>}
      </div>
    </article>
  )
}
