import { useEffect, useRef, useState } from 'react'
import { type AIConnectionInfo, type AIModelSelection, type AIProviderId, type AIProviderType, type AISetupResponse, type AISetupSettings, isBrowserMode, providerType, waitForBridge } from '../bridge'
import Switch from './Switch'
import HelpTip from './HelpTip'
import Accordion from './Accordion'
import AIBehaviorSection from './AIBehaviorSection'
import EditorDialog from './EditorDialog'
import { Select } from './Select'
import { createPortal } from 'react-dom'
import './ai-setup.css'
import { aiText } from '../i18n/ai'
import { catalogFor, useCatalog, useI18n } from '../i18n/core'

const PROVIDER_TYPES: AIProviderType[] = ['gemini', 'deepseek', 'openai', 'custom']
type ProviderEditor = { connection?: AIConnectionInfo; type: AIProviderType; label: string; key: string; url: string; privateNetwork: boolean }

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
  const [editor, setEditor] = useState<ProviderEditor | null>(null)
  const [editorError, setEditorError] = useState('')
  const [instructions, setInstructions] = useState<string | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [instructionsError, setInstructionsError] = useState('')
  const [instructionsNotice, setInstructionsNotice] = useState('')
  const [discoveries, setDiscoveries] = useState<Partial<Record<AIProviderId, string[]>>>({})
  const [discoveryState, setDiscoveryState] = useState<Partial<Record<AIProviderId, string>>>({})
  const text = useCatalog(aiText).setup
  const { fmt } = useI18n()
  const generation = useRef<Record<AIProviderId, number>>({})
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
    return () => { mounted.current = false; for (const provider of Object.keys(generation.current)) generation.current[provider]++ }
  }, [])
  useEffect(() => {
    if (!active) {
      // An unsent key never outlives the page.
      setEditor(null)
      for (const provider of Object.keys(generation.current)) generation.current[provider]++
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
    const next = remembered ?? { provider, model: (slot === 'fallback' ? info?.fallback_model : info?.selected_model) ?? '', thinking: providerType(provider) === 'deepseek' ? 'off' : 'default', search: false }
    setDraft({ ...draft, [slot]: next, cross_provider_acknowledged: false,
      provider_drafts: { ...draft.provider_drafts, [`${slot}:${draft[slot]!.provider}`]: draft[slot]!, [`${slot}:${provider}`]: next } })
  }
  const discover = (provider: AIProviderId, testing = false) => void run(`discover:${provider}`, async () => {
    const version = generation.current[provider] ?? 0
    const result = await (await waitForBridge()).discover_ai_models(provider)
    if (!mounted.current || (generation.current[provider] ?? 0) !== version) return
    if (!result.ok || !result.models) {
      setDiscoveryState((current) => ({ ...current, [provider]: text.discoveryError }))
      throw new Error(result.error || text.discoveryFailed)
    }
    const models = result.models
    setDiscoveries((current) => ({ ...current, [provider]: models }))
    setDiscoveryState((current) => ({ ...current, [provider]: models.length ? text.modelsAvailable : text.noModels }))
    setNotice(testing ? fmt(text.testPassed, { count: models.length }) : text.discovered)
  })
  const typeLabels: Record<AIProviderType, string> = { gemini: 'Google Gemini', deepseek: 'DeepSeek', openai: 'OpenAI', custom: text.custom.label }
  const providers = data?.providers ?? []
  // Unnamed copies of one type are numbered in list order: "DeepSeek", "DeepSeek 2".
  const providerName = (id: AIProviderId) => {
    const connection = providers.find((item) => item.id === id)
    if (connection?.label) return connection.label
    const sameType = providers.filter((item) => item.type === providerType(id))
    const position = sameType.findIndex((item) => item.id === id)
    return typeLabels[providerType(id)] + (position > 0 ? ` ${position + 1}` : '')
  }
  // The custom provider needs only an address; its key is optional.
  const connected = (provider?: AIConnectionInfo) =>
    provider?.type === 'custom' ? Boolean(provider.base_url) : Boolean(provider?.credential?.configured)
  const inUse = (provider: AIProviderId) => [draft?.primary, draft?.fallback, saved?.primary, saved?.fallback].some((item) => item?.provider === provider)
  const forget = (provider: AIProviderId) => {
    generation.current[provider] = (generation.current[provider] ?? 0) + 1
    setDiscoveries((current) => ({ ...current, [provider]: [] }))
    setDiscoveryState((current) => ({ ...current, [provider]: '' }))
  }
  const openEditor = (type: AIProviderType, connection?: AIConnectionInfo) => {
    setEditorError('')
    setEditor({ connection, type, label: connection?.label ?? '', key: '', url: connection?.base_url ?? '', privateNetwork: connection?.private_network ?? false })
  }
  const saveProvider = () => {
    if (!editor) return
    setBusy('provider'); setEditorError(''); setNotice(''); setError('')
    void (async () => {
      try {
        const id = editor.connection?.id
        if (id) forget(id)
        const custom = editor.type === 'custom'
        const result = await (await waitForBridge()).save_ai_connection({
          ...(id ? { connection_id: id } : { provider: editor.type }), label: editor.label.trim(), api_key: editor.key,
          ...(custom ? { base_url: editor.url.trim(), private_network: editor.privateNetwork } : {}),
        })
        if (!result.ok) throw new Error(result.error || text.credentialFailed)
        await load()
        onSaved?.()
        if (!mounted.current) return
        setEditor(null)
        setNotice(result.key_removed ? text.custom.keyCleared : id ? text.providerSaved : text.providerAdded)
      } catch (reason) {
        // A rejected key is not kept in the form.
        if (mounted.current) { setEditorError(reason instanceof Error ? reason.message : text.credentialFailed); setEditor((current) => current && { ...current, key: '' }) }
      } finally {
        if (mounted.current) setBusy('')
      }
    })()
  }
  const removeProvider = (connection: AIConnectionInfo) => {
    if (!window.confirm(fmt(text.confirmRemove, { provider: providerName(connection.id), inUse: inUse(connection.id) ? text.inUse : '' }))) return
    void run(`${connection.id}:remove`, async () => {
      forget(connection.id)
      const result = await (await waitForBridge()).remove_ai_connection(connection.id)
      if (!result.ok) throw new Error(result.error || text.credentialFailed)
      await load()
      onSaved?.()
      setNotice(text.providerRemoved)
    })
  }
  const providerStatus = (provider: AIConnectionInfo) => provider.type === 'custom'
    ? (!provider.base_url ? text.custom.notSetUp : provider.credential?.configured ? text.custom.addressAndKey : text.custom.addressSaved)
    : !provider.credential?.configured ? text.noKey : provider.credential.source === 'environment' ? text.keyProvided : text.keySaved
  const modelCard = (slot: 'primary' | 'fallback') => {
    const selection = draft?.[slot]
    if (!selection) return null
    const labels = text.slots[slot]
    const info = data?.providers?.find((item) => item.id === selection.provider)
    const capabilities = data?.capabilities?.[providerType(selection.provider)]?.[selection.model]
    const thinking = capabilities?.thinking_options ?? [{ value: 'default', label: text.providerDefault }]
    const staleThinking = !thinking.some((option) => option.value === selection.thinking)
    const models = Array.from(new Set([...(info?.models ?? []), ...(discoveries[selection.provider] ?? [])]))
    return <div className="ai-setup-model-fields">
      <div className="ai-model-selectors">
        <label className="form-field">{text.provider}<Select aria-label={labels.provider} value={selection.provider} disabled={Boolean(busy)} onChange={(value) => switchProvider(slot, value as AIProviderId)} options={providers.filter((provider) => slot === 'primary' || provider.type !== 'custom').map((provider) => ({ value: provider.id, label: providerName(provider.id) }))} /></label>
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

  const serverHost = isBrowserMode()
  // Consent covers another company; another key of the same provider needs none.
  const crossProvider = draft?.fallback && providerType(draft.fallback.provider) !== providerType(draft.primary.provider)
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
        thinking: providerType(provider) === 'deepseek' ? 'off' : 'default', search: false,
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
        <section aria-label={text.providers} className="ai-connections">
          <div className="ai-section-title ai-providers-heading"><h3>{text.providers}</h3>
            <HelpTip label={text.providersHelp}><ul><li>{text.providersTip1}</li><li>{text.providersTip2}</li></ul></HelpTip>
            <Select className="ai-add-provider" aria-label={text.addProvider} value="" valueLabel={text.addProvider} disabled={Boolean(busy) || providers.length >= (data?.max_providers ?? 20)}
              options={PROVIDER_TYPES.map((type) => ({ value: type, label: typeLabels[type] }))} onChange={(type) => openEditor(type as AIProviderType)} />
          </div>
          {!providers.length && <p className="settings-hint">{text.noProviders}</p>}
          {providers.map((provider) => {
            const name = providerName(provider.id)
            return <div className="ai-connection-row" key={provider.id}>
              <div className="ai-provider-status"><strong>{name}</strong>{provider.label && <span className="ai-provider-type">{typeLabels[provider.type]}</span>}
                <span className={`state-pill ${connected(provider) ? 'enabled' : 'unconfigured'}`}>{providerStatus(provider)}</span></div>
              <div className="row-actions">
                <button className="secondary" aria-label={fmt(text.testProvider, { provider: name })} disabled={Boolean(busy) || !connected(provider)} onClick={() => discover(provider.id, true)}>{text.testConnection}</button>
                <button className="secondary" aria-label={fmt(text.editProvider, { provider: name })} disabled={Boolean(busy)} onClick={() => openEditor(provider.type, provider)}>{text.edit}</button>
                <button className="ghost destructive" aria-label={fmt(text.removeProvider, { provider: name })} disabled={Boolean(busy) || provider.credential?.managed === false} onClick={() => removeProvider(provider)}>{text.remove}</button>
              </div>
            </div>
          })}
        </section>
        <section className="ai-models-section" aria-label={text.models}><h3>{text.models}</h3><div className="ai-setup-cards"><section className="ai-model-card"><div className="ai-section-title"><h3>{text.primaryModel}</h3></div>{modelCard('primary')}</section>
          <section className="ai-model-card"><div className="ai-section-title"><h3>{text.fallbackModel}</h3>
            <Switch checked={Boolean(draft.fallback)} ariaLabel={text.enableFallback} disabled={Boolean(busy)} onCheckedChange={toggleFallback}>{text.enableFallback}</Switch></div>
            {modelCard('fallback')}
          </section></div>
        {crossProvider && <label className="ai-routing-consent"><input type="checkbox" checked={draft.cross_provider_acknowledged} disabled={Boolean(busy)} onChange={(event) => change({ cross_provider_acknowledged: event.target.checked })} /> {fmt(text.crossConsent, { provider: providerName(draft.fallback!.provider) })}</label>}
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
    {editor && (() => {
      const custom = editor.type === 'custom'
      const credential = editor.connection?.credential
      const managed = credential?.managed !== false
      const privateAllowed = data?.private_networks_allowed !== false
      const title = editor.connection ? providerName(editor.connection.id) : fmt(text.addTitle, { provider: typeLabels[editor.type] })
      const canSave = custom ? Boolean(editor.url.trim()) : Boolean(editor.connection || editor.key.trim())
      return <EditorDialog id="ai-provider-editor" className="ai-provider-dialog" title={title} closeLabel={text.close} busy={busy === 'provider'} error={editorError} onClose={() => setEditor(null)}>
        <div className="command-dialog-panels ai-provider-fields">
          <label className="form-field">{text.name}<input data-editor-focus aria-label={text.name} maxLength={40} autoComplete="off" disabled={busy === 'provider'} placeholder={typeLabels[editor.type]} value={editor.label} onChange={(event) => setEditor({ ...editor, label: event.target.value })} /></label>
          {custom && <label className="form-field"><span className="ai-field-label">{text.custom.baseUrl}<HelpTip label={text.custom.helpLabel}><ul><li>{text.custom.tip1}</li><li>{serverHost ? text.custom.serverTip3 : text.custom.tip3}</li><li>{text.custom.tip4}</li></ul></HelpTip></span>
            <input aria-label={text.custom.baseUrl} type="url" inputMode="url" autoComplete="off" spellCheck={false} maxLength={2048} disabled={busy === 'provider'} placeholder={serverHost ? text.custom.serverUrlPlaceholder : text.custom.urlPlaceholder} value={editor.url} onChange={(event) => setEditor({ ...editor, url: event.target.value })} /></label>}
          <label className="form-field">{custom ? text.custom.keyField : text.apiKey}<input type="password" aria-label={text.apiKey} autoComplete="off" maxLength={8192} disabled={busy === 'provider' || !managed}
            placeholder={!managed ? text.managedExternally : credential?.configured ? text.replacementKey : custom ? text.custom.keyOptional : text.enterKey} value={editor.key} onChange={(event) => setEditor({ ...editor, key: event.target.value })} /></label>
          {custom && <div className="ai-private-network">
            <Switch checked={editor.privateNetwork} ariaLabel={text.custom.privateNetwork} disabled={busy === 'provider' || (!privateAllowed && !editor.privateNetwork)} onCheckedChange={(privateNetwork) => setEditor({ ...editor, privateNetwork })}>{text.custom.privateNetwork}</Switch>
            <HelpTip label={text.custom.privateNetworkHelp}><ul>{(serverHost ? text.custom.serverPrivateTip : text.custom.privateTip).map((item) => <li key={item}>{item}</li>)}</ul></HelpTip>
          </div>}
          {custom && !privateAllowed && <p className="settings-hint">{text.custom.privateOff}</p>}
        </div>
        <div className="command-dialog-footer">
          <button className="secondary" disabled={busy === 'provider'} onClick={() => setEditor(null)}>{text.cancelProvider}</button>
          <button className="primary" disabled={busy === 'provider' || !canSave} onClick={saveProvider}>{editor.connection ? text.saveProvider : text.addProviderButton}</button>
        </div>
      </EditorDialog>
    })()}
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
