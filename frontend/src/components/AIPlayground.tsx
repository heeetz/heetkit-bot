import { useEffect, useRef, useState } from 'react'
import { type AIPlaygroundResult, waitForBridge } from '../bridge'

const STATUS_LABELS = {
  pending: 'Waiting for Gemini…',
  success: 'Response',
  input_blocked: 'Input blocked',
  output_blocked: 'Output blocked',
  provider_unavailable: 'Provider unavailable — add a usable Gemini API key in Settings.',
  api_error: 'API error — Gemini could not return a usable response. Check your key, model and quota.',
  timeout: 'Timeout — Gemini did not finish within 60 seconds.',
  cancelled: 'Cancelled',
}

export default function AIPlayground({ active, personality }: { active: boolean; personality: string }) {
  const [prompt, setPrompt] = useState('')
  const [pending, setPending] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [requestId, setRequestId] = useState<string | null>(null)
  const [result, setResult] = useState<AIPlaygroundResult | null>(null)
  const [error, setError] = useState('')
  const currentId = useRef<string | null>(null)
  const submitting = useRef(false)
  const generation = useRef(0)

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
        if (!response.ok || !response.status) throw new Error(response.error ?? 'Could not read the Playground result.')
        if (response.status === 'pending') {
          timer = window.setTimeout(() => void poll(), 500)
          return
        }
        setResult(response)
        setError('')
      } catch {
        if (stopped || currentId.current !== requestId) return
        setError('Could not read the Playground result. Cancellation was requested; try again.')
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
      if (!response.ok || !response.request_id) throw new Error(response.error ?? 'Could not start the Playground request.')
      currentId.current = response.request_id
      setRequestId(response.request_id)
    } catch (reason) {
      if (attempt !== generation.current) return
      setError(reason instanceof Error ? reason.message : 'Could not start the Playground request.')
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
        setError('Could not cancel the request. You can retry cancellation; the request has a 60-second timeout.')
        setCancelling(false)
      }
    }
  }

  return (
    <article className="card ai-playground" id="ai-playground">
      <div className="section-heading">
        <div>
          <p className="label">LOCAL TESTING</p>
          <h2>AI Playground</h2>
          <p className="section-copy">Try a prompt with real Gemini responses. Nothing is sent to Twitch.</p>
        </div>
        <span className="mini-badge">Real API quota</span>
      </div>
      <p className="setting-effect">Testing may consume real Gemini API quota. Uses active filters, the active personality ({personality || 'not selected'}), applied profile instructions and saved model/language settings. Apply or save editor changes first.</p>
      <p className="setting-effect">Each prompt is independent: no viewer memory, chat activity or Twitch command cooldowns. The bot can be stopped and Ask disabled.</p>
      <label className="form-field">
        Playground prompt
        <textarea value={prompt} disabled={pending} placeholder="Enter a prompt to test…" onChange={(event) => {
          setPrompt(event.target.value)
          setResult(null)
          setError('')
        }} />
      </label>
      <div className="row-actions">
        <button className="primary" disabled={pending || !prompt.trim()} onClick={() => void submit()}>{pending ? 'Testing…' : 'Test prompt'}</button>
        {pending && <button className="secondary" disabled={!requestId || cancelling} onClick={() => void cancel()}>{cancelling ? 'Cancelling…' : 'Cancel request'}</button>}
      </div>
      {error && <p role="alert" className="error-text">{error}</p>}
      <div className="playground-result" role="status" aria-live="polite">
        {pending && <p>{cancelling ? 'Cancelling…' : STATUS_LABELS.pending}</p>}
        {result?.status && <>
          <strong>{STATUS_LABELS[result.status]}</strong>
          {result.moderation_source === 'editable_filter' && <p>Editable filter · {result.matched_category}: <code>{result.matched_rule}</code></p>}
          {result.moderation_source === 'filter_timeout' && <p>Editable filter evaluation timed out and blocked the text safely. No matched rule is reported.</p>}
          {result.moderation_source === 'protected_policy' && <p>Protected safety policy. This decision is separate from editable filters; no hidden instructions are shown.</p>}
          {result.status === 'success' && <p className="playground-response">{result.text}</p>}
        </>}
      </div>
    </article>
  )
}
