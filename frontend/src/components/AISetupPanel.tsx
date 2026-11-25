import { useEffect, useRef, useState } from 'react'
import { type AIModelSelection, type AIProviderId, type AISetupResponse, type AISetupSettings, isBrowserMode, waitForBridge } from '../bridge'
import Switch from './Switch'
import HelpTip from './HelpTip'
import Accordion from './Accordion'
import AIBehaviorSection from './AIBehaviorSection'
import { Select } from './Select'
import { createPortal } from 'react-dom'
import './ai-setup.css'
import { aiText } from '../i18n/ai'
import { catalogFor, useCatalog, useI18n } from '../i18n/core'

export default function AISetupPanel({ active, onDirtyChange, onSaved, instructionsTarget, discardInstructions, onInstructionsDirtyChange, onInstructionsBusyChange }: {
  instructionsTarget: HTMLElement | null
  discardInstructions: number
  active: boolean
  onDirtyChange: (dirty: boolean) => void
  onInstructionsDirtyChange: (dirty: boolean) => void
  onInstructionsBusyChange: (busy: boolean) => void
  onSaved?: () => void
}) {
  const [data, setData] = useState<AISetupResponse | null>(null)
  const [saved, setSaved] = useState<AISetupSettings | null>(null)
  const [draft, setDraft] = useState<AISetupSettings | null>(null)
  const [keys, setKeys] = useState<Partial<Record<AIProviderId, string>>>({})
  const [instructions, setInstructions] = useState<string | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [instructionsError, setInstructionsError] = useState('')
  const [instructionsNotice, setInstructionsNotice] = useState('')
  const [discoveries, setDiscoveries] = useState<Partial<Record<AIProviderId, string[]>>>({})
  const [discoveryState, setDiscoveryState] = useState<Partial<Record<AIProviderId, string>>>({})
  const [customUrl, setCustomUrl] = useState<string | null>(null)
  const text = useCatalog(aiText).setup
  const { fmt } = useI18n()
  const generation = useRef({ gemini: 0, deepseek: 0, openai: 0, custom: 0 })
  const mounted = useRef(true)
  const lastFallback = useRef<AIModelSelection | null>(null)
  const dirty = Boolean(draft && saved && JSON.stringify(draft) !== JSON.stringify(saved))
  const instructionsDirty = Boolean(saved && instructions !== saved.shared_instructions)
  useEffect(() => { onDirtyChange(dirty) }, [dirty, onDirtyChange])
  useEffect(() => { onInstructionsDirtyChange(instructionsDirty) }, [instructionsDirty, onInstructionsDirtyChange])
  useEffect(() => { onInstructionsBusyChange(busy === 'instructions') }, [busy, onInstructionsBusyChange])
  useEffect(() => {
    setInstructions(saved?.shared_instructions ?? null)
    setInstructionsError('')
    setInstructionsNotice('')
  }, [discardInstructions])
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; for (const provider of Object.keys(generation.current) as AIProviderId[]) generation.current[provider]++ }
  }, [])
  useEffect(() => {
    if (!active) {
      setKeys({})
      setCustomUrl(null)
      for (const provider of Object.keys(generation.current) as AIProviderId[]) generation.current[provider]++
    }
  }, [active])
  const load = async (replaceDraft = false) => {
    const result = await (await waitForBridge()).get_ai_setup()
    if (!result.ok || !result.settings) throw new Error(result.error || catalogFor(aiText).setup.unavailable)
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
    const reportError = name === 'instructions' ? setInstructionsError : setError
    const clearNotice = name === 'instructions' ? setInstructionsNotice : setNotice
    setBusy(name); reportError(''); clearNotice('')
    try { await action() } catch (reason) { reportError(reason instanceof Error ? reason.message : catalogFor(aiText).setup.failed) }
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
    if (action === 'remove' && !window.confirm(fmt(text.confirmRemove, { provider, inUse: inUse ? text.inUse : '' }))) return
    const operation = run(`${provider}:${action}`, async () => {
      generation.current[provider]++
      setDiscoveries((current) => ({ ...current, [provider]: [] }))
      setDiscoveryState((current) => ({ ...current, [provider]: '' }))
      const api = await waitForBridge()
      const result = action === 'replace' ? await api.replace_credential(`${provider}_api_key`, keys[provider] ?? '')
        : action === 'remove' ? await api.remove_credential(`${provider}_api_key`) : await api.test_credential(`${provider}_api_key`)
      if (!result.ok) throw new Error(result.error || text.credentialFailed)
      await load()
      onSaved?.()
      setKeys((current) => ({ ...current, [provider]: '' }))
      setNotice(action === 'test' ? text.testPassed : action === 'remove' ? text.keyRemoved : text.keySavedNotice)
    })
    void operation.finally(() => setKeys((current) => ({ ...current, [provider]: '' })))
  }
  const discover = (provider: AIProviderId, testing = false) => void run(`discover:${provider}`, async () => {
    const version = generation.current[provider]
    const result = await (await waitForBridge()).discover_ai_models(provider)
    if (!mounted.current || generation.current[provider] !== version) return
    if (!result.ok || !result.models) {
      setDiscoveryState((current) => ({ ...current, [provider]: text.discoveryError }))
      throw new Error(result.error || text.discoveryFailed)
    }
    const models = result.models
    setDiscoveries((current) => ({ ...current, [provider]: models }))
    setDiscoveryState((current) => ({ ...current, [provider]: models.length ? text.modelsAvailable : text.noModels }))
    setNotice(testing ? fmt(text.custom.testPassed, { count: models.length }) : text.discovered)
  })
  const providerLabel = (provider: { id: AIProviderId; label: string }) => provider.id === 'custom' ? text.custom.label : provider.label
  // The custom provider needs only an address; its key is optional.
  const connected = (provider?: { id: AIProviderId; credential: { configured: boolean } | null; base_url?: string | null }) =>
    provider?.id === 'custom' ? Boolean(provider.base_url) : Boolean(provider?.credential?.configured)
  const customAction = (action: 'save' | 'remove', url = '') => {
    const inUse = draft?.primary.provider === 'custom' || saved?.primary.provider === 'custom'
    if (action === 'remove' && !window.confirm(fmt(text.custom.confirmRemove, { inUse: inUse ? text.inUse : '' }))) return
    const operation = run(`custom:${action}`, async () => {
      generation.current.custom++
      setDiscoveries((current) => ({ ...current, custom: [] }))
      setDiscoveryState((current) => ({ ...current, custom: '' }))
      const api = await waitForBridge()
      const result = action === 'save' ? await api.save_custom_ai_connection(url, keys.custom ?? '')
        : await api.remove_custom_ai_connection()
      if (!result.ok) throw new Error(result.error || text.credentialFailed)
      await load()
      onSaved?.()
      setCustomUrl(null)
      setNotice(action === 'remove' ? text.custom.removed : 'key_removed' in result && result.key_removed ? text.custom.keyCleared : text.custom.saved)
    })
    void operation.finally(() => setKeys((current) => ({ ...current, custom: '' })))
  }
  const modelCard = (slot: 'primary' | 'fallback') => {
    const selection = draft?.[slot]
    if (!selection) return null
    const labels = text.slots[slot]
    const info = data?.providers?.find((item) => item.id === selection.provider)
    const capabilities = data?.capabilities?.[selection.provider]?.[selection.model]
    const thinking = capabilities?.thinking_options ?? [{ value: 'default', label: text.providerDefault }]
    const staleThinking = !thinking.some((option) => option.value === selection.thinking)
    const models = Array.from(new Set([...(info?.models ?? []), ...(discoveries[selection.provider] ?? [])]))
    return <div className="ai-setup-model-fields">
      <div className="ai-model-selectors">
        <label className="form-field">{text.provider}<Select aria-label={labels.provider} value={selection.provider} disabled={Boolean(busy)} onChange={(value) => switchProvider(slot, value as AIProviderId)} options={data?.providers?.filter((provider) => slot === 'primary' || provider.id !== 'custom').map((provider) => ({ value: provider.id, label: providerLabel(provider) })) ?? []} /></label>
        <label className="form-field">{text.model}<Select aria-label={labels.modelChoices} searchable value={selection.model} disabled={Boolean(busy)} onChange={(model) => select(slot, { model })} options={Array.from(new Set([selection.model, ...models])).filter(Boolean).map((model) => ({ value: model, label: model }))} /></label>
        <label className="form-field">{text.thinkingEffort}<Select aria-label={labels.thinking} value={selection.thinking} disabled={Boolean(busy)} onChange={(value) => select(slot, { thinking: value })} options={[...(staleThinking ? [{ value: selection.thinking, label: fmt(text.unsupportedChoice, { value: selection.thinking }) }] : []), ...thinking]} /></label>
        <div className="ai-search-control"><Switch checked={selection.search} ariaLabel={labels.search} disabled={Boolean(busy) || !capabilities?.search_supported} onCheckedChange={(search) => select(slot, { search })}>{selection.search ? text.searchOn : text.searchOff}</Switch></div>
      </div>
      <div className="ai-model-configuration-row">
        <div className="ai-discovery-action"><button className="secondary" aria-label={labels.discover} disabled={Boolean(busy) || !connected(info)} onClick={() => discover(selection.provider)}>{text.discoverModels}</button></div>
        <label className="form-field ai-manual-model">{text.manualModel}<input aria-label={labels.model} value={selection.model} maxLength={200} disabled={Boolean(busy)} onChange={(event) => select(slot, { model: event.target.value })} /></label>
      </div>
      {(busy === `discover:${selection.provider}` || discoveryState[selection.provider]) && <p className="settings-hint" role="status">{busy === `discover:${selection.provider}` ? text.loadingModels : discoveryState[selection.provider]}</p>}
      {!connected(info) && <p role="alert">{text.connectProvider}</p>}
      {staleThinking && <p role="alert">{text.chooseThinking}</p>}
      {selection.search && capabilities?.attribution_required ? <p className="ai-search-warning" role="alert">{text.geminiSearch}</p> : !capabilities?.search_supported && <p className="settings-hint">{text.searchUnavailable}</p>}
      {selection.search && !capabilities?.search_supported && <button className="secondary" onClick={() => select(slot, { search: false })}>{text.searchOffButton}</button>}
    </div>
  }

  const customInfo = data?.providers?.find((provider) => provider.id === 'custom')
  const serverHost = isBrowserMode()
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
    if (!result.ok) throw new Error(result.error || text.sharedFailed)
    const settings = await load()
    if (!settings) return
    setDraft((current) => current ? { ...current, shared_instructions: settings.shared_instructions } : current)
    setInstructions(settings.shared_instructions)
    onSaved?.()
    setInstructionsNotice(text.sharedSaved)
  })
  return <>
    <Accordion id="ai-models" title={text.title} className="ai-setup-panel" badges={dirty && <span className="mini-badge dirty-badge">{text.edited}</span>}>
      {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      {!draft ? <p>{text.loading}</p> : <>
        <section aria-label={text.providers} className="ai-connections"><div className="ai-section-title"><h3>{text.providers}</h3></div>
          {data?.providers?.filter((provider) => provider.id !== 'custom').map((provider) => <div className="ai-connection-row" key={provider.id}>
            <div className="ai-provider-status"><strong>{provider.label}</strong><span className={`state-pill ${provider.credential?.configured ? 'enabled' : 'unconfigured'}`}>{provider.credential?.configured ? provider.credential.source === 'environment' ? text.keyProvided : text.keySaved : text.noKey}</span></div>
            <label className="form-field ai-key-field"><span>{fmt(text.apiKey, { provider: provider.label })}</span><input type="password" aria-label={fmt(text.apiKey, { provider: provider.id })} autoComplete="off" maxLength={8192} disabled={Boolean(busy) || provider.credential?.managed === false} placeholder={provider.credential?.managed === false ? text.managedExternally : provider.credential?.configured ? text.replacementKey : text.enterKey} value={keys[provider.id] ?? ''} onChange={(event) => setKeys((current) => ({ ...current, [provider.id]: event.target.value }))} /></label>
            <div className="row-actions"><button className="primary" aria-label={fmt(provider.credential?.configured ? text.replaceProviderKey : text.connectProviderKey, { provider: provider.label })} disabled={Boolean(busy) || !keys[provider.id]?.trim() || provider.credential?.managed === false} onClick={() => credentialAction(provider.id, 'replace')}>{provider.credential?.configured ? text.replaceKey : text.connectKey}</button>
              <button className="secondary" aria-label={fmt(text.testProvider, { provider: provider.label })} disabled={Boolean(busy) || !provider.credential?.configured} onClick={() => credentialAction(provider.id, 'test')}>{text.testConnection}</button>
              <button className="ghost destructive" aria-label={fmt(text.removeProviderKey, { provider: provider.label })} disabled={Boolean(busy) || !provider.credential?.configured || provider.credential?.managed === false || provider.credential?.source === 'environment'} onClick={() => credentialAction(provider.id, 'remove')}>{text.removeKey}</button></div>
          </div>)}
          {customInfo && <div className="ai-connection-row ai-custom-connection">
            <div className="ai-provider-status"><strong>{text.custom.label}</strong><HelpTip label={text.custom.helpLabel}><ul><li>{text.custom.tip1}</li><li>{serverHost ? text.custom.serverTip2 : text.custom.tip2}</li><li>{serverHost ? text.custom.serverTip3 : text.custom.tip3}</li><li>{text.custom.tip4}</li></ul></HelpTip><span className={`state-pill ${customInfo.base_url ? 'enabled' : 'unconfigured'}`}>{!customInfo.base_url ? text.custom.notSetUp : customInfo.credential?.configured ? text.custom.addressAndKey : text.custom.addressSaved}</span></div>
            <div className="ai-custom-fields">
              <label className="form-field ai-key-field"><span>{text.custom.baseUrl}</span><input aria-label={text.custom.baseUrl} type="url" inputMode="url" autoComplete="off" spellCheck={false} maxLength={2048} disabled={Boolean(busy)} placeholder={serverHost ? text.custom.serverUrlPlaceholder : text.custom.urlPlaceholder} value={customUrl ?? customInfo.base_url ?? ''} onChange={(event) => setCustomUrl(event.target.value)} /></label>
              <label className="form-field ai-key-field"><span>{text.custom.keyField}</span><input type="password" aria-label={text.custom.apiKey} autoComplete="off" maxLength={8192} disabled={Boolean(busy)} placeholder={customInfo.credential?.configured ? text.replacementKey : text.custom.keyOptional} value={keys.custom ?? ''} onChange={(event) => setKeys((current) => ({ ...current, custom: event.target.value }))} /></label>
            </div>
            <div className="row-actions"><button className="primary" aria-label={text.custom.saveLabel} disabled={Boolean(busy) || !(customUrl ?? customInfo.base_url ?? '').trim() || ((customUrl ?? customInfo.base_url ?? '').trim() === (customInfo.base_url ?? '') && !keys.custom?.trim())} onClick={() => customAction('save', (customUrl ?? customInfo.base_url ?? '').trim())}>{text.custom.save}</button>
              <button className="secondary" aria-label={text.custom.testLabel} disabled={Boolean(busy) || !customInfo.base_url} onClick={() => discover('custom', true)}>{text.testConnection}</button>
              <button className="ghost destructive" aria-label={text.custom.removeLabel} disabled={Boolean(busy) || !customInfo.base_url} onClick={() => customAction('remove')}>{text.custom.remove}</button></div>
          </div>}
        </section>
        <section className="ai-models-section" aria-label={text.models}><h3>{text.models}</h3><div className="ai-setup-cards"><section className="ai-model-card"><div className="ai-section-title"><h3>{text.primaryModel}</h3></div>{modelCard('primary')}</section>
          <section className="ai-model-card"><div className="ai-section-title"><h3>{text.fallbackModel}</h3>
            <Switch checked={Boolean(draft.fallback)} ariaLabel={text.enableFallback} disabled={Boolean(busy)} onCheckedChange={toggleFallback}>{text.enableFallback}</Switch></div>
            {modelCard('fallback')}
          </section></div>
        {crossProvider && <label className="ai-routing-consent"><input type="checkbox" checked={draft.cross_provider_acknowledged} disabled={Boolean(busy)} onChange={(event) => change({ cross_provider_acknowledged: event.target.checked })} /> {fmt(text.crossConsent, { provider: draft.fallback!.provider })}</label>}
        <section className="ai-setup-lengths" aria-label={text.characterLimits}>
          <label className="form-field">{text.inputLimit}<input aria-label={text.maxQuestion} type="number" min={1} max={4000} disabled={Boolean(busy)} value={draft.max_question_length} onChange={(event) => change({ max_question_length: Number(event.target.value) })} /></label>
          <label className="form-field">{text.replyLimit}<input aria-label={text.maxAnswer} type="number" min={1} max={450} disabled={Boolean(busy)} value={draft.max_answer_length} onChange={(event) => change({ max_answer_length: Number(event.target.value) })} /></label>
          <div className="ai-setup-actions">
            <div className="ai-save-status">{dirty && <span role="status">{text.unsaved}</span>}</div>
            <div className="row-actions">
              <button className="secondary" disabled={Boolean(busy) || !dirty} onClick={() => { setDraft(saved); setError(''); setNotice(text.cancelled) }}>{text.cancelEdits}</button>
              <button className="primary" disabled={Boolean(busy) || !dirty || Boolean(crossProvider && !draft.cross_provider_acknowledged)} onClick={() => void run('save', async () => { const result = await (await waitForBridge()).save_ai_setup(draft); if (!result.ok) throw new Error(result.error || text.rejected); const settings = await load(); if (!settings) return; setDraft(settings); lastFallback.current = settings.fallback; onSaved?.(); setNotice(text.saved) })}>{text.save}</button>
            </div>
          </div>
        </section>
        </section>
      </>}
    </Accordion>
    {instructionsTarget && createPortal(<AIBehaviorSection id="ai-shared-instructions" title={text.sharedTitle} helpLabel={text.placeholdersLabel} className="ai-shared-instructions" badges={instructionsDirty && <span className="mini-badge dirty-badge">{text.edited}</span>} description={<ul><li><code>{'{current_datetime}'}</code>: {text.placeholders.datetime}</li><li><code>{'{ai_max_response_length}'}</code>: {text.placeholders.length}</li><li><code>{'{response_language_instruction}'}</code>: {text.placeholders.language}</li></ul>}
      footer={saved && <div className="editor-footer ai-editor-footer">
        <div className="row-actions">
          <button className="secondary" disabled={Boolean(busy) || !instructionsDirty} onClick={() => setInstructions(saved.shared_instructions)}>{text.cancelInstructions}</button>
          <button className="primary" disabled={Boolean(busy) || !instructionsDirty} onClick={saveInstructions}>{text.saveInstructions}</button>
          <button className="ghost" disabled={Boolean(busy)} onClick={() => setInstructions(null)}>{text.restoreDefault}</button>
        </div>
      </div>}>
      {instructionsError && <p role="alert">{instructionsError}</p>}{instructionsNotice && <p role="status">{instructionsNotice}</p>}
      {!saved ? <p>{error || text.loadingShared}</p> : <>
        <label className="form-field">{text.sharedField}<textarea aria-label={text.sharedField} rows={12} maxLength={20000} disabled={Boolean(busy)} value={instructions ?? data?.default_shared_instructions ?? ''} onChange={(event) => setInstructions(event.target.value)} /></label>
        <p className="settings-hint">{text.sharedHint}</p>
      </>}
    </AIBehaviorSection>, instructionsTarget)}
  </>
}
