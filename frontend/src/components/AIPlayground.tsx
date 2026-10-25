import { useEffect, useRef, useState } from 'react'
import { type AIPlaygroundResult, waitForBridge } from '../bridge'
import HelpTip from './HelpTip'

function searchOutcome(result: AIPlaygroundResult): string {
  if (result.status === 'search_error') return 'Failed'
  if (result.status === 'search_unavailable') return 'Unavailable on fallback'
  if (result.status === 'attribution_unavailable') return 'Answer withheld: required attribution unavailable'
  if (result.generation?.search_used) return 'Used'
  if (!result.generation?.search_enabled) return 'Off'
  if (!result.generation?.search_requested) return 'Not needed for this prompt'
  return 'Requested; no tool use reported'
}

const STATUS_LABELS = {
  model_unavailable: 'Model unavailable — the configured primary and fallback could not serve this request.',
  configuration_error: 'AI configuration needs attention — check thinking choices, fallback consent and saved connections.',
  search_error: 'Search failed — no verified fresh answer was produced.',
  search_unavailable: 'Fallback search is unavailable — requested search was not silently disabled.',
  attribution_unavailable: 'Required search attribution cannot fit or be displayed in this output. Turn search off or use a compatible configuration.',
  question_too_long: 'Question exceeds the saved character limit.',
  pending: 'Waiting for the AI provider…',
  success: 'Response',
  input_blocked: 'Input blocked',
  output_blocked: 'Output blocked',
  provider_unavailable: 'Provider unavailable — add a usable provider key in AI setup.',
  api_error: 'API error — the AI provider could not return a usable response. Check your key, model and quota.',
  timeout: 'Timeout — the AI provider did not finish within 60 seconds.',
  cancelled: 'Cancelled',
}

export default function AIPlayground({ active, personality, hasDrafts = false }: { active: boolean; personality: string; hasDrafts?: boolean }) {
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
          <p className="label">OPERATOR TESTING</p>
          <h2>AI Playground</h2>
          <p className="section-copy">Try a prompt with real provider responses. Nothing is sent to Twitch.</p>
        </div>
        <span className="mini-badge">Real API quota</span>
      </div>
      <p className="setting-effect">Testing may consume real provider API quota. Uses active filters, the active personality ({personality || 'not selected'}), applied profile instructions and saved primary/fallback, thinking, search and language settings. Apply or save editor changes first.</p>
      <p className="setting-effect">Each prompt is independent: no viewer memory, stream context, chat activity, command permissions or cooldowns. The bot can be stopped and !ask disabled. Success does not prove Twitch delivery.</p>
      <HelpTip label="Playground request lifecycle">One request can run at a time across this application. Cancel or leave the AI page to request cancellation. The slot stays occupied until provider cleanup finishes; late results are discarded. Server results belong to the session that started them. Sign-out, session expiry or eviction and application shutdown cancel that session's work and clear access to its result. Closing a browser tab without signing out relies on the request timeout or session expiry.</HelpTip>
      {hasDrafts && <p className="setting-effect playground-draft-warning">Unsaved editor drafts are not used. Use an editor's Open Playground choices to save or apply that draft first, or test the current applied settings.</p>}
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
          {result.generation && <p className="setting-effect">
            Provider: {result.generation.provider} · Model: {result.generation.model}
            {' · '}Thinking: {result.generation.thinking}
            {' · '}{result.generation.fallback_used ? 'Fallback used' : 'Primary selection'}
            {' · '}Search/Fetch: {searchOutcome(result)}
          </p>}
          {result.moderation_source === 'editable_filter' && <p>Editable filter · {result.matched_category}: <code>{result.matched_rule}</code></p>}
          {result.moderation_source === 'filter_timeout' && <p>Editable filter evaluation timed out and blocked the text safely. No matched rule is reported.</p>}
          {result.moderation_source === 'protected_policy' && <p>Protected safety policy. This decision is separate from editable filters; no hidden instructions are shown.</p>}
          {result.status === 'success' && <p className="playground-response">{result.text}</p>}
        </>}
      </div>
    </article>
  )
}
