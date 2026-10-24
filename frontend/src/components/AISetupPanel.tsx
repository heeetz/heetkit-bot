import { useEffect, useRef, useState } from 'react'
import { type AIModelSelection, type AIProviderId, type AISetupResponse, type AISetupSettings, waitForBridge } from '../bridge'
import Switch from './Switch'
import './ai-setup.css'

export default function AISetupPanel({ active, onDirtyChange, onSaved }: { active: boolean; onDirtyChange: (dirty: boolean) => void; onSaved?: () => void }) {
  const [data, setData] = useState<AISetupResponse | null>(null)
  const [saved, setSaved] = useState<AISetupSettings | null>(null)
  const [draft, setDraft] = useState<AISetupSettings | null>(null)
  const [keyProvider, setKeyProvider] = useState<AIProviderId | null>(null)
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [discoveries, setDiscoveries] = useState<Partial<Record<AIProviderId, string[]>>>({})
  const [discoveryState, setDiscoveryState] = useState<Partial<Record<AIProviderId, string>>>({})
  const generation = useRef({ gemini: 0, deepseek: 0 })
  const mounted = useRef(true)
  const lastFallback = useRef<AIModelSelection | null>(null)
  const dirty = Boolean(draft && saved && JSON.stringify(draft) !== JSON.stringify(saved))
  useEffect(() => { onDirtyChange(dirty) }, [dirty, onDirtyChange])
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; generation.current.gemini++; generation.current.deepseek++ }
  }, [])
  useEffect(() => {
    if (!active) {
      setKey(''); setKeyProvider(null)
      generation.current.gemini++; generation.current.deepseek++
    }
  }, [active])
  const load = async (replaceDraft = false) => {
    const result = await (await waitForBridge()).get_ai_setup()
    if (!result.ok || !result.settings) throw new Error(result.error || 'AI setup is unavailable.')
    if (!mounted.current) return
    setData(result)
    setSaved(result.settings)
    if (replaceDraft) { setDraft(result.settings); lastFallback.current = result.settings.fallback }
  }
  useEffect(() => {
    if (active && !data) void load(true).catch((reason: Error) => setError(reason.message))
  }, [active, data])
  const run = async (name: string, action: () => Promise<void>) => {
    setBusy(name); setError(''); setNotice('')
    try { await action() } catch (reason) { setError(reason instanceof Error ? reason.message : 'AI setup failed.') }
    finally { if (mounted.current) { setBusy(''); setKey('') } }
  }
  const change = (patch: Partial<AISetupSettings>) => setDraft((current) => current ? { ...current, ...patch } : current)
  const select = (slot: 'primary' | 'fallback', patch: Partial<AIModelSelection>) => {
    setDraft((current) => {
      if (!current || !current[slot]) return current
      const next = { ...current[slot]!, ...patch }
      const providerDrafts = { ...current.provider_drafts, [`${slot}:${next.provider}`]: next }
      return { ...current, [slot]: next, provider_drafts: providerDrafts,
        cross_provider_acknowledged: patch.provider ? false : current.cross_provider_acknowledged }
    })
  }
  const switchProvider = (slot: 'primary' | 'fallback', provider: AIProviderId) => {
    if (!draft || !data) return
    const info = data.providers?.find((item) => item.id === provider)
    const remembered = draft.provider_drafts[`${slot}:${provider}`] ?? draft.provider_drafts[provider]
    const next = remembered ?? { provider, model: (slot === 'fallback' ? info?.fallback_model : info?.selected_model) ?? '', thinking: provider === 'deepseek' ? 'off' : 'default', search: false }
    setDraft({ ...draft, [slot]: next, cross_provider_acknowledged: false,
      provider_drafts: { ...draft.provider_drafts, [`${slot}:${draft[slot]!.provider}`]: draft[slot]!, [`${slot}:${provider}`]: next } })
  }
  const credentialAction = (provider: AIProviderId, action: 'replace' | 'remove' | 'test') => {
    const inUse = draft?.primary.provider === provider || draft?.fallback?.provider === provider
      || saved?.primary.provider === provider || saved?.fallback?.provider === provider
    if (action === 'remove' && !window.confirm(`Remove the ${provider} key? ${inUse ? 'This provider is in use; its requests will be unavailable. ' : ''}Saved model choices stay unchanged. Credential removal is immediate and Cancel cannot undo it.`)) return
    void run(`${provider}:${action}`, async () => {
      generation.current[provider]++
      setDiscoveries((current) => ({ ...current, [provider]: [] }))
      setDiscoveryState((current) => ({ ...current, [provider]: 'Unknown after credential change' }))
      const api = await waitForBridge()
      const result = action === 'replace' ? await api.replace_credential(`${provider}_api_key`, key)
        : action === 'remove' ? await api.remove_credential(`${provider}_api_key`) : await api.test_credential(`${provider}_api_key`)
      if (!result.ok) throw new Error(result.error || 'Credential operation failed.')
      await load()
      onSaved?.()
      setKeyProvider(null)
      setNotice(action === 'test' ? 'Credential test completed. Discovery and generation access may differ.' : 'Credential change saved immediately. Model and instruction drafts were kept.')
    })
  }
  const discover = (provider: AIProviderId) => void run(`discover:${provider}`, async () => {
    const version = generation.current[provider]
    const result = await (await waitForBridge()).discover_ai_models(provider)
    if (!mounted.current || generation.current[provider] !== version) return
    if (!result.ok || !result.models) {
      setDiscoveryState((current) => ({ ...current, [provider]: 'Error; saved choices retained' }))
      throw new Error(result.error || 'Model discovery failed.')
    }
    setDiscoveries((current) => ({ ...current, [provider]: result.models }))
    setDiscoveryState((current) => ({ ...current, [provider]: 'Available model IDs; generation and tool access remain unverified' }))
    setNotice('Models discovered. Your selections were retained.')
  })
  const modelCard = (slot: 'primary' | 'fallback') => {
    const selection = draft?.[slot]
    if (!selection) return null
    const name = slot === 'primary' ? 'Primary' : 'Fallback'
    const info = data?.providers?.find((item) => item.id === selection.provider)
    const capabilities = data?.capabilities?.[selection.provider]?.[selection.model]
    const thinking = capabilities?.thinking_options ?? [{ value: 'default', label: 'Provider default' }]
    const staleThinking = !thinking.some((option) => option.value === selection.thinking)
    const models = Array.from(new Set([...(info?.models ?? []), ...(discoveries[selection.provider] ?? [])]))
    return <div className="ai-setup-model-fields">
      <label className="form-field">{name} provider<select aria-label={`${name} provider`} value={selection.provider} disabled={Boolean(busy)} onChange={(event) => switchProvider(slot, event.target.value as AIProviderId)}>
        {data?.providers?.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}{provider.credential?.configured ? ' — connected' : ' — unavailable'}</option>)}
      </select></label>
      {!info?.credential?.configured && <button className="secondary" onClick={() => { setKeyProvider(selection.provider); setKey('') }}>Connect provider</button>}
      <label className="form-field">{name} model<input aria-label={`${name} model`} list={`${slot}-model-choices`} value={selection.model} maxLength={200} disabled={Boolean(busy)} onChange={(event) => select(slot, { model: event.target.value })} />
        <datalist id={`${slot}-model-choices`}>{models.map((model) => <option key={model} value={model} />)}</datalist>
        <small>Type to search known/discovered IDs or enter a manual ID.</small>
      </label>
      <button className="secondary" disabled={Boolean(busy) || !info?.credential?.configured} onClick={() => discover(selection.provider)}>Discover {name.toLowerCase()} models</button>
      <p className="settings-hint" role="status">{!info?.credential?.configured ? 'Unavailable: connect this provider' : discoveryState[selection.provider] ?? 'Configured; generation access unknown'}. {capabilities?.known ? 'Documented capabilities' : 'Unknown model capabilities: provider default only; search unavailable'}.</p>
      <label className="form-field">{name} thinking<select aria-label={`${name} thinking`} value={selection.thinking} disabled={Boolean(busy)} onChange={(event) => select(slot, { thinking: event.target.value })}>
        {staleThinking && <option value={selection.thinking}>Unsupported saved choice: {selection.thinking}</option>}
        {thinking.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select></label>
      {staleThinking && <p role="alert">Choose a supported thinking option explicitly. No automatic effort increase will be saved.</p>}
      <Switch checked={selection.search} ariaLabel={`${name} internet search`} disabled={Boolean(busy) || !capabilities?.search_supported} onCheckedChange={(search) => select(slot, { search })}>Internet search {selection.search ? 'On' : 'Off'}</Switch>
      <p className="settings-hint">{capabilities?.search_reason ?? 'Search is unavailable for this model/API.'}</p>
      {selection.search && capabilities?.attribution_required && <p role="alert">Google grounded answers cannot be delivered to Twitch because its required Search Suggestions cannot be displayed there. Turn search off for ordinary Twitch answers.</p>}
      {selection.search && !capabilities?.search_supported && <button className="secondary" onClick={() => select(slot, { search: false })}>Turn unsupported search off</button>}
    </div>
  }
  const crossProvider = draft?.fallback && draft.fallback.provider !== draft.primary.provider
  const toggleFallback = (enabled: boolean) => {
    if (!draft) return
    if (!enabled) {
      lastFallback.current = draft.fallback
      const provider_drafts = draft.fallback ? { ...draft.provider_drafts, [`fallback:${draft.fallback.provider}`]: draft.fallback } : draft.provider_drafts
      change({ fallback: null, cross_provider_acknowledged: false, provider_drafts })
    } else {
      const provider = draft.primary.provider
      change({ fallback: lastFallback.current ?? draft.provider_drafts[`fallback:${provider}`] ?? {
        provider, model: data?.providers?.find((item) => item.id === provider)?.fallback_model ?? '',
        thinking: provider === 'deepseek' ? 'off' : 'default', search: false,
      }, cross_provider_acknowledged: false })
    }
  }
  return <article className="card ai-setup-panel" id="ai-models" aria-busy={Boolean(busy)}>
    <h2>AI setup</h2>
    <p className="section-copy">1 Choose provider → 2 Connect/test key → 3 Discover and choose primary model → 4 Configure primary → 5 Choose fallback and Save. AI is optional.</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!draft ? <p>Loading AI setup…</p> : <>
      <section aria-label="Connected providers"><h3>Connected providers</h3>
        {data?.providers?.map((provider) => <div className="ai-connection-row" key={provider.id}>
          <div><strong>{provider.label}</strong><p>{provider.credential?.configured ? 'Configured' : 'Unavailable'} · Key source: {provider.credential?.source ?? 'none'} · {provider.credential?.validation_status ?? 'unknown'}</p></div>
          <div className="row-actions"><button className="secondary" disabled={Boolean(busy) || provider.credential?.managed === false} onClick={() => { setKeyProvider(provider.id); setKey('') }}>{provider.credential?.configured ? 'Replace' : 'Connect'} {provider.label}</button>
            <button className="secondary" disabled={Boolean(busy) || !provider.credential?.configured} onClick={() => credentialAction(provider.id, 'test')}>Test {provider.label}</button>
            <button className="ghost destructive" disabled={Boolean(busy) || !provider.credential?.configured || provider.credential?.managed === false} onClick={() => credentialAction(provider.id, 'remove')}>Remove {provider.label}</button></div>
        </div>)}
        {keyProvider && <div className="ai-key-editor"><label className="form-field">{keyProvider} API key<input type="password" aria-label={`${keyProvider} API key`} autoComplete="off" value={key} onChange={(event) => setKey(event.target.value)} /></label>
          <p>Saving a key is immediate. Cancel model edits does not undo credential changes. External keys are managed on the host.</p>
          <div className="row-actions"><button className="primary" disabled={Boolean(busy) || !key.trim()} onClick={() => credentialAction(keyProvider, 'replace')}>Save connection</button><button className="secondary" onClick={() => { setKeyProvider(null); setKey('') }}>Cancel key entry</button></div>
        </div>}
      </section>
      <div className="ai-setup-cards"><section className="ai-model-card"><h3>Primary model</h3>{modelCard('primary')}</section>
        <section className="ai-model-card"><details><summary>Fallback model · {draft.fallback ? `${draft.fallback.provider} / ${draft.fallback.model} · ${draft.fallback.thinking} · search ${draft.fallback.search ? 'On' : 'Off'}` : 'Disabled'}</summary>
          <p>One fallback, only after model-unavailable (404). No fallback for credential, quota, billing, refusal or parameter errors. One total deadline. Requested search is never silently disabled.</p>
          <label><input type="checkbox" checked={Boolean(draft.fallback)} onChange={(event) => toggleFallback(event.target.checked)} /> Enable fallback</label>
          {modelCard('fallback')}
        </details></section></div>
      {crossProvider && <label className="ai-routing-consent"><input type="checkbox" checked={draft.cross_provider_acknowledged} onChange={(event) => change({ cross_provider_acknowledged: event.target.checked })} /> I understand that my question, instructions and permitted conversation memory may be sent to {draft.fallback!.provider} when fallback is used.</label>}
      <details className="ai-instructions-editor"><summary>Shared instructions and length limits</summary>
        <div className="ai-setup-lengths"><label className="form-field">Maximum question length (characters, 1–4000; default 300)<input aria-label="Maximum question length" type="number" min={1} max={4000} value={draft.max_question_length} onChange={(event) => change({ max_question_length: Number(event.target.value) })} /></label>
          <label className="form-field">Maximum answer length (characters, 1–450; default 220)<input aria-label="Maximum answer length" type="number" min={1} max={450} value={draft.max_answer_length} onChange={(event) => change({ max_answer_length: Number(event.target.value) })} /></label></div>
        <p>Only the current question counts toward its limit; an overlong question is rejected. Token/thinking budgets are separate. The mention and Unicode encoding must fit Twitch’s outgoing envelope; answers are never split.</p>
        <label className="form-field">Shared AI instructions<textarea aria-label="Shared AI instructions" rows={12} maxLength={20000} value={draft.shared_instructions ?? data?.default_shared_instructions ?? ''} onChange={(event) => change({ shared_instructions: event.target.value })} /></label>
        <p>Edits replace the shipped shared text for this profile. Empty deliberately removes it. Personality and profile instructions remain separate. Placeholders: {'{current_datetime}'}, {'{ai_max_response_length}'}, {'{response_language_instruction}'}.</p>
        <button className="secondary" onClick={() => change({ shared_instructions: null })}>Reset shared instructions to defaults</button>
        <p className="settings-hint">{data?.retained_restrictions}</p>
      </details>
      <p className="settings-hint">Thinking and search can add provider charges. Search On permits bounded calls when relevant; it does not promise every answer searches. Search failures are not treated as fresh verification. Source attribution must fit the answer limit.</p>
      <div className="editor-footer"><span role="status">{dirty ? 'Unsaved AI setup; saved settings still apply.' : 'Saved AI setup.'}</span><div className="row-actions">
        <button className="secondary" disabled={Boolean(busy) || !dirty} onClick={() => { setDraft(saved); setError(''); setNotice('Model and instruction drafts cancelled. Saved credentials are unchanged.') }}>Cancel AI edits</button>
        <button className="primary" disabled={Boolean(busy) || !dirty || Boolean(crossProvider && !draft.cross_provider_acknowledged)} onClick={() => void run('save', async () => { const result = await (await waitForBridge()).save_ai_setup(draft); if (!result.ok) throw new Error(result.error || 'AI setup was rejected. Check model options and lengths.'); await load(true); onSaved?.(); setNotice('AI setup saved. Subsequent requests use these settings.') })}>Save AI setup</button>
      </div></div>
    </>}
  </article>
}
