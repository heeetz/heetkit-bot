import { useEffect, useRef, useState } from 'react'
import { type AIModelSelection, type AIProviderId, type AISetupResponse, type AISetupSettings, waitForBridge } from '../bridge'
import Switch from './Switch'
import Accordion from './Accordion'
import HelpTip from './HelpTip'
import { Select } from './Select'
import { createPortal } from 'react-dom'
import './ai-setup.css'

export default function AISetupPanel({ active, onDirtyChange, onSaved, instructionsTarget }: { instructionsTarget: HTMLElement | null; active: boolean; onDirtyChange: (dirty: boolean) => void; onSaved?: () => void }) {
  const [data, setData] = useState<AISetupResponse | null>(null)
  const [saved, setSaved] = useState<AISetupSettings | null>(null)
  const [draft, setDraft] = useState<AISetupSettings | null>(null)
  const [keys, setKeys] = useState<Partial<Record<AIProviderId, string>>>({})
  const [instructions, setInstructions] = useState<string | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [discoveries, setDiscoveries] = useState<Partial<Record<AIProviderId, string[]>>>({})
  const [discoveryState, setDiscoveryState] = useState<Partial<Record<AIProviderId, string>>>({})
  const generation = useRef({ gemini: 0, deepseek: 0 })
  const mounted = useRef(true)
  const lastFallback = useRef<AIModelSelection | null>(null)
  const dirty = Boolean(draft && saved && JSON.stringify(draft) !== JSON.stringify(saved))
  const instructionsDirty = Boolean(saved && instructions !== saved.shared_instructions)
  useEffect(() => { onDirtyChange(dirty || instructionsDirty) }, [dirty, instructionsDirty, onDirtyChange])
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; generation.current.gemini++; generation.current.deepseek++ }
  }, [])
  useEffect(() => {
    if (!active) {
      setKeys({})
      generation.current.gemini++; generation.current.deepseek++
    }
  }, [active])
  const load = async (replaceDraft = false) => {
    const result = await (await waitForBridge()).get_ai_setup()
    if (!result.ok || !result.settings) throw new Error(result.error || 'AI setup is unavailable.')
    if (!mounted.current) return
    setData(result)
    setSaved(result.settings)
    if (replaceDraft) { setDraft(result.settings); setInstructions(result.settings.shared_instructions); lastFallback.current = result.settings.fallback }
    return result.settings
  }
  useEffect(() => {
    if (active && !data) void load(true).catch((reason: Error) => setError(reason.message))
  }, [active, data])
  const run = async (name: string, action: () => Promise<void>) => {
    setBusy(name); setError(''); setNotice('')
    try { await action() } catch (reason) { setError(reason instanceof Error ? reason.message : 'AI setup failed.') }
    finally { if (mounted.current) { setBusy('') } }
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
    const operation = run(`${provider}:${action}`, async () => {
      generation.current[provider]++
      setDiscoveries((current) => ({ ...current, [provider]: [] }))
      setDiscoveryState((current) => ({ ...current, [provider]: 'Unknown after credential change' }))
      const api = await waitForBridge()
      const result = action === 'replace' ? await api.replace_credential(`${provider}_api_key`, keys[provider] ?? '')
        : action === 'remove' ? await api.remove_credential(`${provider}_api_key`) : await api.test_credential(`${provider}_api_key`)
      if (!result.ok) throw new Error(result.error || 'Credential operation failed.')
      await load()
      onSaved?.()
      setKeys((current) => ({ ...current, [provider]: '' }))
      setNotice(action === 'test' ? 'Credential test completed. Discovery and generation access may differ.' : 'Credential change saved immediately. Model and instruction drafts were kept.')
    })
    void operation.finally(() => setKeys((current) => ({ ...current, [provider]: '' })))
  }
  const discover = (provider: AIProviderId) => void run(`discover:${provider}`, async () => {
    const version = generation.current[provider]
    const result = await (await waitForBridge()).discover_ai_models(provider)
    if (!mounted.current || generation.current[provider] !== version) return
    if (!result.ok || !result.models) {
      setDiscoveryState((current) => ({ ...current, [provider]: 'Error; saved choices retained' }))
      throw new Error(result.error || 'Model discovery failed.')
    }
    const models = result.models
    setDiscoveries((current) => ({ ...current, [provider]: models }))
    setDiscoveryState((current) => ({ ...current, [provider]: models.length ? 'Available model IDs; generation and tool access remain unverified' : 'No models returned; saved choices retained' }))
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
      <div className="ai-model-selectors">
        <label className="form-field">Provider<Select aria-label={`${name} provider`} value={selection.provider} disabled={Boolean(busy)} onChange={(value) => switchProvider(slot, value as AIProviderId)} options={data?.providers?.map((provider) => ({ value: provider.id, label: provider.label })) ?? []} /></label>
        <label className="form-field">Model<Select aria-label={`${name} model choices`} searchable value={selection.model} disabled={Boolean(busy)} onChange={(model) => select(slot, { model })} options={Array.from(new Set([selection.model, ...models])).filter(Boolean).map((model) => ({ value: model, label: model }))} /></label>
        <label className="form-field">Thinking effort<Select aria-label={`${name} thinking`} value={selection.thinking} disabled={Boolean(busy)} onChange={(value) => select(slot, { thinking: value })} options={[...(staleThinking ? [{ value: selection.thinking, label: `Unsupported saved choice: ${selection.thinking}` }] : []), ...thinking]} /></label>
      </div>
      {!info?.credential?.configured && <p role="alert">Unavailable: connect this provider in Connected providers above.</p>}
      {staleThinking && <p role="alert">Choose a supported thinking option explicitly. No automatic effort increase will be saved.</p>}
      <Switch checked={selection.search} ariaLabel={`${name} internet search`} disabled={Boolean(busy) || !capabilities?.search_supported} onCheckedChange={(search) => select(slot, { search })}>Internet search {selection.search ? 'On' : 'Off'}</Switch>
      <p className="settings-hint">{capabilities?.search_reason ?? 'Search is unavailable for this model/API.'}</p>
      {selection.search && capabilities?.attribution_required && <p role="alert">Google grounded answers cannot be delivered to Twitch because its required Search Suggestions cannot be displayed there. Turn search off for ordinary Twitch answers.</p>}
      {selection.search && !capabilities?.search_supported && <button className="secondary" onClick={() => select(slot, { search: false })}>Turn unsupported search off</button>}
      <div className="ai-discovery-action"><button className="secondary" disabled={Boolean(busy) || !info?.credential?.configured} onClick={() => discover(selection.provider)}>Discover {name.toLowerCase()} models</button><span className="settings-hint">{info?.label}</span><HelpTip label={`${name} model discovery`}>Discovery lists this provider's available IDs; it does not verify generation or tool access. Unknown model IDs support provider default only, with search unavailable.</HelpTip></div>
      <p className="settings-hint" role="status">{busy === `discover:${selection.provider}` ? 'Loading models...' : discoveryState[selection.provider] ?? 'Generation access unknown.'}</p>
      <details className="ai-manual-model"><summary>Manual model ID</summary><label className="form-field">{name} model<input aria-label={`${name} model`} value={selection.model} maxLength={200} disabled={Boolean(busy)} onChange={(event) => select(slot, { model: event.target.value })} /></label></details>
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
  const saveInstructions = () => void run('instructions', async () => {
    if (!saved) return
    const result = await (await waitForBridge()).save_ai_setup({ ...saved, shared_instructions: instructions })
    if (!result.ok) throw new Error(result.error || 'Shared instructions could not be saved.')
    const settings = await load()
    if (!settings) return
    setDraft((current) => current ? { ...current, shared_instructions: settings.shared_instructions } : current)
    setInstructions(settings.shared_instructions)
    onSaved?.()
    setNotice('Shared instructions saved. Model and length drafts were kept.')
  })
  return <>
    <Accordion id="ai-models" title="AI setup" className="ai-setup-panel" description="Connect provider keys immediately, then choose primary/fallback models and character limits. Save AI setup applies the non-secret draft; Cancel cannot undo credential changes." badges={dirty && <span className="mini-badge dirty-badge">Edited</span>}>
      {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      {!draft ? <p>Loading AI setup...</p> : <>
        <section aria-label="Connected providers" className="ai-connections"><div className="ai-section-title"><h3>Connected providers</h3><HelpTip label="Provider keys">Keys are never read back. Connect/Replace/Remove apply immediately and are independent of Save AI setup. Test connection checks credentials; model discovery and real generation access may differ.</HelpTip></div>
          {data?.providers?.map((provider) => <div className="ai-connection-row" key={provider.id}>
            <div><strong>{provider.label}</strong><p className="settings-hint">{provider.credential?.configured ? 'Configured' : 'Unavailable'} | {provider.credential?.source ?? 'none'} | {provider.credential?.validation_status ?? 'unknown'}</p>{provider.credential?.managed === false && <p className="settings-hint">Managed externally; change the host environment or secret file.</p>}</div>
            <label className="form-field ai-key-field"><span>{provider.label} API key</span><input type="password" aria-label={`${provider.id} API key`} autoComplete="off" maxLength={8192} disabled={Boolean(busy) || provider.credential?.managed === false} placeholder={provider.credential?.configured ? 'Enter replacement key' : 'Enter API key'} value={keys[provider.id] ?? ''} onChange={(event) => setKeys((current) => ({ ...current, [provider.id]: event.target.value }))} /></label>
            <div className="row-actions"><button className="primary" aria-label={`${provider.credential?.configured ? 'Replace' : 'Connect'} ${provider.label} key`} disabled={Boolean(busy) || !keys[provider.id]?.trim() || provider.credential?.managed === false} onClick={() => credentialAction(provider.id, 'replace')}>{provider.credential?.configured ? 'Replace key' : 'Connect key'}</button>
              <button className="secondary" aria-label={`Test ${provider.label} connection`} disabled={Boolean(busy) || !provider.credential?.configured} onClick={() => credentialAction(provider.id, 'test')}>Test connection</button>
              <button className="ghost destructive" aria-label={`Remove ${provider.label} key`} disabled={Boolean(busy) || !provider.credential?.configured || provider.credential?.managed === false} onClick={() => credentialAction(provider.id, 'remove')}>Remove key</button></div>
          </div>)}
        </section>
        <div className="ai-setup-cards"><section className="ai-model-card"><div className="ai-section-title"><h3>Primary model</h3></div>{modelCard('primary')}</section>
          <section className="ai-model-card"><div className="ai-section-title"><h3>Fallback model</h3><HelpTip label="Fallback model">One fallback is attempted only after an initial model-unavailable (404) response, within the same deadline. Credential, quota, billing, refusal and parameter errors do not trigger fallback. Requested search is never silently disabled.</HelpTip>
            <Switch checked={Boolean(draft.fallback)} ariaLabel="Enable fallback" disabled={Boolean(busy)} onCheckedChange={toggleFallback}>Enable fallback</Switch></div>
            {modelCard('fallback')}
          </section></div>
        {crossProvider && <label className="ai-routing-consent"><input type="checkbox" checked={draft.cross_provider_acknowledged} disabled={Boolean(busy)} onChange={(event) => change({ cross_provider_acknowledged: event.target.checked })} /> I understand that my question, instructions and permitted conversation memory may be sent to {draft.fallback!.provider} when fallback is used.</label>}
        <section className="ai-setup-lengths" aria-label="Character limits">
          <label className="form-field">Input length limit<input aria-label="Maximum question length" type="number" min={1} max={4000} disabled={Boolean(busy)} value={draft.max_question_length} onChange={(event) => change({ max_question_length: Number(event.target.value) })} /></label>
          <label className="form-field">Output length limit<input aria-label="Maximum answer length" type="number" min={1} max={450} disabled={Boolean(busy)} value={draft.max_answer_length} onChange={(event) => change({ max_answer_length: Number(event.target.value) })} /></label>
          <HelpTip label="Character limits">Question: 1-4000 characters (default 300), counting only the current trimmed question. Overlong questions are rejected. Answer: 1-450 (default 220). Mention and Unicode encoding must fit Twitch's outgoing envelope; answers are never split. Token/thinking budgets are separate.</HelpTip>
        </section>
        <p className="settings-hint">Thinking and search can add provider charges. Required sources must fit the answer limit.</p>
        <div className="editor-footer"><span role="status">{dirty ? 'Unsaved AI setup; saved settings still apply.' : 'Saved AI setup.'}</span><div className="row-actions">
          <button className="secondary" disabled={Boolean(busy) || !dirty} onClick={() => { setDraft(saved); setError(''); setNotice('Model and length drafts cancelled. Saved credentials are unchanged.') }}>Cancel AI edits</button>
          <button className="primary" disabled={Boolean(busy) || !dirty || Boolean(crossProvider && !draft.cross_provider_acknowledged)} onClick={() => void run('save', async () => { const result = await (await waitForBridge()).save_ai_setup(draft); if (!result.ok) throw new Error(result.error || 'AI setup was rejected. Check model options and lengths.'); const settings = await load(); if (!settings) return; setDraft(settings); lastFallback.current = settings.fallback; onSaved?.(); setNotice('AI setup saved. Subsequent requests use these settings.') })}>Save AI setup</button>
        </div></div>
      </>}
    </Accordion>
    {instructionsTarget && createPortal(<Accordion id="ai-shared-instructions" title="Shared instructions" className="ai-shared-instructions" badges={instructionsDirty && <span className="mini-badge dirty-badge">Edited</span>} description="Shared text is separate from personality and profile instructions. Save instructions applies only this editor; model and length drafts stay unchanged. Empty deliberately removes the shared text. Restore defaults changes the draft. Placeholders: {current_datetime}, {ai_max_response_length}, {response_language_instruction}.">
      {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      {!saved ? <p>Loading shared instructions...</p> : <>
        <label className="form-field">Shared AI instructions<textarea aria-label="Shared AI instructions" rows={12} maxLength={20000} disabled={Boolean(busy)} value={instructions ?? data?.default_shared_instructions ?? ''} onChange={(event) => setInstructions(event.target.value)} /></label>
        <p className="settings-hint">{data?.retained_restrictions}</p>
        <div className="editor-footer"><button className="secondary" disabled={Boolean(busy)} onClick={() => setInstructions(null)}>Restore default instructions</button><div className="row-actions"><button className="secondary" disabled={Boolean(busy) || !instructionsDirty} onClick={() => setInstructions(saved.shared_instructions)}>Cancel instruction edits</button><button className="primary" disabled={Boolean(busy) || !instructionsDirty} onClick={saveInstructions}>Save instructions</button></div></div>
      </>}
    </Accordion>, instructionsTarget)}
  </>
}
