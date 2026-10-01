import { useEffect, useState } from 'react'

import {
  type AIProviderSettings,
  type AIStatus,
  type GeminiModelPreset,
  type PersonalityInfo,
  type PersonalitiesResponse,
  waitForBridge,
} from '../bridge'
import FeedbackToast from '../components/FeedbackToast'
import Switch from '../components/Switch'

interface AIPageProps {
  active: boolean
}

const CUSTOM_MODEL_VALUE = '__custom_model__'

function ModelSelector({
  label,
  value,
  presets,
  discoveredModels,
  onChange,
  help,
}: {
  label: string
  value: string
  presets: GeminiModelPreset[]
  discoveredModels: string[]
  onChange: (value: string) => void
  help: string
}) {
  const presetById = new Map(presets.map((preset) => [preset.id, preset]))
  const choices = Array.from(new Set([
    ...presets.map((preset) => preset.id),
    ...discoveredModels,
  ]))
  const usesCustomValue = !choices.includes(value)

  return (
    <div className="model-selector">
      <label className="form-field">
        {label}
        <select
          value={usesCustomValue ? CUSTOM_MODEL_VALUE : value}
          onChange={(event) => onChange(
            event.target.value === CUSTOM_MODEL_VALUE ? '' : event.target.value,
          )}
        >
          {choices.map((model) => (
            <option key={model} value={model}>
              {presetById.has(model) ? `${presetById.get(model)!.label} — ${model}` : model}
            </option>
          ))}
          <option value={CUSTOM_MODEL_VALUE}>Custom model ID…</option>
        </select>
        <small>{help}</small>
      </label>
      {usesCustomValue && (
        <label className="form-field custom-model-field">
          Custom model ID
          <input
            value={value}
            placeholder="gemini-model-id"
            onChange={(event) => onChange(event.target.value)}
          />
        </label>
      )}
    </div>
  )
}

export default function AIPage({ active }: AIPageProps) {
  const [status, setStatus] = useState<AIStatus | null>(null)
  const [data, setData] = useState<PersonalitiesResponse | null>(null)
  const [selected, setSelected] = useState('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [providerSaved, setProviderSaved] = useState<AIProviderSettings | null>(null)
  const [providerDraft, setProviderDraft] = useState<AIProviderSettings | null>(null)
  const [discoveredModels, setDiscoveredModels] = useState<string[]>([])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const mergeData = (response: PersonalitiesResponse, completedPersonality = '') => {
    setDrafts((currentDrafts) => Object.fromEntries(response.personalities.map((personality) => {
      const previous = data?.personalities.find((item) => item.name === personality.name)
      const currentDraft = currentDrafts[personality.name]
      const keepDraft = personality.name !== completedPersonality
        && previous
        && currentDraft !== undefined
        && currentDraft !== previous.prompt
      return [personality.name, keepDraft ? currentDraft : personality.prompt]
    })))
    setData(response)
    setSelected((current) => current || response.active_personality)
  }

  const refresh = async (completedPersonality = '') => {
    const api = await waitForBridge()
    const [nextStatus, response] = await Promise.all([
      api.get_ai_status(),
      api.get_personalities(),
    ])
    setStatus(nextStatus)
    mergeData(response, completedPersonality)
  }

  useEffect(() => {
    if (!active) {
      return
    }
    let current = true
    const load = async () => {
      try {
        const api = await waitForBridge()
        const [nextStatus, response, providerResponse] = await Promise.all([
          api.get_ai_status(),
          api.get_personalities(),
          api.get_ai_provider_settings(),
        ])
        if (!providerResponse.ok || !providerResponse.settings) {
          throw new Error(providerResponse.error ?? 'AI provider settings are unavailable.')
        }
        if (current) {
          setStatus(nextStatus)
          mergeData(response)
          setProviderDraft((current) => {
            const dirty = current && providerSaved
              && (current.selected_model !== providerSaved.selected_model
                || current.fallback_model !== providerSaved.fallback_model)
            return dirty ? current : providerResponse.settings!
          })
          setProviderSaved(providerResponse.settings)
          setError('')
        }
      } catch (reason) {
        if (current) {
          setError(reason instanceof Error ? reason.message : 'Could not load AI settings.')
        }
      }
    }
    void load()
    return () => { current = false }
  }, [active])

  const changeToggle = async (kind: 'enabled' | 'memory', enabled: boolean) => {
    setBusy(kind)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = kind === 'enabled'
        ? await api.set_ai_enabled(enabled)
        : await api.set_ai_memory_enabled(enabled)
      if (!result.ok) {
        throw new Error(result.error ?? 'AI setting could not be changed.')
      }
      setStatus(await api.get_ai_status())
      setNotice(kind === 'enabled' ? 'AI command state updated.' : 'AI memory state updated.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'AI setting could not be changed.')
    } finally {
      setBusy('')
    }
  }

  const updateProviderDraft = (values: Partial<AIProviderSettings>) => {
    setProviderDraft((current) => current ? { ...current, ...values } : current)
    setError('')
    setNotice('')
  }

  const saveProviderModels = async () => {
    if (!providerDraft) {
      return
    }
    const selectedModel = providerDraft.selected_model.trim()
    const fallbackModel = providerDraft.fallback_model.trim()
    if (!selectedModel || !fallbackModel) {
      setError('Selected and fallback model IDs are required.')
      return
    }
    if (selectedModel === fallbackModel) {
      setError('Selected and fallback models must be different.')
      return
    }
    setBusy('provider:save')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.update_ai_provider_settings(selectedModel, fallbackModel)
      if (!result.ok) {
        throw new Error(result.error ?? 'AI model settings could not be saved.')
      }
      const refreshed = await api.get_ai_provider_settings()
      if (!refreshed.ok || !refreshed.settings) {
        throw new Error(refreshed.error ?? 'AI provider settings could not be refreshed.')
      }
      setProviderSaved(refreshed.settings)
      setProviderDraft(refreshed.settings)
      setStatus(await api.get_ai_status())
      setNotice('AI model settings saved and active for the next request.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'AI model settings could not be saved.')
    } finally {
      setBusy('')
    }
  }

  const discoverModels = async () => {
    setBusy('provider:discover')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.discover_gemini_models()
      if (!result.ok || !result.models) {
        throw new Error(result.error ?? 'Gemini models could not be discovered.')
      }
      setDiscoveredModels(result.models)
      setNotice(`Discovered ${result.models.length} compatible Gemini model${result.models.length === 1 ? '' : 's'}.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Gemini models could not be discovered.')
    } finally {
      setBusy('')
    }
  }

  const testGeminiCredential = async () => {
    setBusy('provider:test')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.test_credential('gemini_api_key')
      if (!result.ok) {
        throw new Error(result.error ?? 'Gemini credential test failed.')
      }
      setNotice('Gemini credential test passed.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Gemini credential test failed.')
    } finally {
      setBusy('')
    }
  }

  const runPersonalityAction = async (action: 'apply' | 'save' | 'reset') => {
    const personality = data?.personalities.find((item) => item.name === selected)
    const prompt = drafts[selected]
    if (!personality || prompt === undefined) {
      return
    }
    if (action === 'reset' && !window.confirm(`Reset ${selected} to its built-in prompt?`)) {
      return
    }
    setBusy(action)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = action === 'apply'
        ? await api.apply_personality(selected, prompt)
        : action === 'save'
          ? await api.save_personality(selected, prompt)
          : await api.reset_personality(selected)
      if (!result.ok) {
        throw new Error(result.error ?? 'Personality could not be updated.')
      }
      await refresh(selected)
      setNotice(action === 'apply'
        ? `Applied ${selected} for this session.`
        : action === 'save'
          ? `Saved ${selected} and made it the active personality.`
          : `Restored the built-in ${selected} prompt.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Personality could not be updated.')
    } finally {
      setBusy('')
    }
  }

  const personality: PersonalityInfo | undefined = data?.personalities.find(
    (item) => item.name === selected,
  )
  const prompt = selected ? (drafts[selected] ?? personality?.prompt ?? '') : ''
  const dirty = personality ? prompt !== personality.prompt : false
  const isActive = data?.active_personality === selected
  const canReset = Boolean(
    personality
      && (dirty || personality.has_saved_override || personality.prompt !== personality.built_in_prompt),
  )
  const providerDirty = Boolean(
    providerDraft && providerSaved
      && (providerDraft.selected_model !== providerSaved.selected_model
        || providerDraft.fallback_model !== providerSaved.fallback_model),
  )

  return (
    <section className="ai-layout">
      <FeedbackToast
        error={error}
        notice={notice}
        onDismiss={() => { setError(''); setNotice('') }}
      />
      <div className="ai-status-grid">
        <article className="card compact-card">
          <p className="label">AI command</p>
          <Switch
            className="settings-toggle"
            checked={status?.enabled ?? false}
            disabled={!status || Boolean(busy)}
            ariaLabel="Enable AI command"
            onCheckedChange={(enabled) => void changeToggle('enabled', enabled)}
          >
            <span>{status?.enabled ? 'Enabled' : 'Disabled'}</span>
          </Switch>
          <p className="setting-effect">Applies immediately for this session. Save the Ask command on the Commands page to persist it.</p>
        </article>
        <article className="card compact-card">
          <p className="label">Conversation memory</p>
          <Switch
            className="settings-toggle"
            checked={status?.memory_enabled ?? false}
            disabled={!status || Boolean(busy)}
            ariaLabel="Enable conversation memory"
            onCheckedChange={(enabled) => void changeToggle('memory', enabled)}
          >
            <span>{status?.memory_enabled ? 'Enabled' : 'Disabled'}</span>
          </Switch>
          <p className="setting-effect">Applies immediately and is saved across restarts.</p>
        </article>
        <article className="card compact-card">
          <p className="label">Gemini model</p>
          <strong>{status?.model ?? '—'}</strong>
        </article>
        <article className="card compact-card">
          <p className="label">Active personality</p>
          <strong>{data?.active_personality ?? '—'}</strong>
        </article>
      </div>
      <article className="card ai-provider-card">
        <div className="section-heading">
          <div>
            <p className="label">GEMINI PROVIDER</p>
            <h2>Models and fallback</h2>
            <p className="section-copy">Choose the model used for AI requests and its unavailable-model fallback.</p>
          </div>
          {providerDirty && <span className="mini-badge dirty-badge">Edited</span>}
        </div>
        {!providerDraft ? <p className="muted">Loading AI provider settings…</p> : (
          <div className="settings-list">
            <div className="ai-provider-status">
              <div><span>Provider</span><strong>{providerDraft.provider}</strong></div>
              <div><span>Credential</span><strong className={providerDraft.credential?.configured ? 'status-good' : ''}>{providerDraft.credential?.configured ? 'Configured' : 'Missing'}</strong></div>
            </div>
            <div className="model-fields">
              <ModelSelector
                label="Selected model"
                value={providerDraft.selected_model}
                presets={providerDraft.presets}
                discoveredModels={discoveredModels}
                onChange={(selected_model) => updateProviderDraft({ selected_model })}
                help="Saved model changes apply to the next AI request."
              />
              <ModelSelector
                label="Fallback model"
                value={providerDraft.fallback_model}
                presets={providerDraft.presets}
                discoveredModels={discoveredModels}
                onChange={(fallback_model) => updateProviderDraft({ fallback_model })}
                help="Used only when the selected model is unavailable or unsupported."
              />
            </div>
            <div className="settings-actions">
              <button className="secondary" disabled={Boolean(busy) || !providerDraft.credential?.configured} onClick={() => void testGeminiCredential()}>{busy === 'provider:test' ? 'Testing…' : 'Test credential'}</button>
              <button className="secondary" disabled={Boolean(busy) || !providerDraft.credential?.configured} onClick={() => void discoverModels()}>{busy === 'provider:discover' ? 'Discovering…' : 'Discover models'}</button>
              <button className="primary" disabled={Boolean(busy) || !providerDirty} onClick={() => void saveProviderModels()}>{busy === 'provider:save' ? 'Saving…' : 'Save models'}</button>
            </div>
            <p className="settings-hint">Manage the Gemini API key in Settings. Authentication, network, policy, and rate-limit failures never trigger model fallback.</p>
          </div>
        )}
      </article>
      <article className="card personality-editor">
        <div className="section-heading">
          <div>
            <p className="label">PERSONALITY EDITOR</p>
            <h2>Personality-specific prompt</h2>
            <p className="section-copy">Core shared instructions stay protected in Python.</p>
          </div>
          <div className="personality-badges">
            {isActive && <span className="mini-badge saved-badge">Active</span>}
            {personality?.has_saved_override && <span className="mini-badge saved-badge">Saved override</span>}
            {data && !data.active_personality_saved && isActive && <span className="mini-badge runtime-badge">Runtime only</span>}
            {dirty && <span className="mini-badge dirty-badge">Edited</span>}
          </div>
        </div>
        <label className="form-field personality-select">
          Personality
          <select value={selected} onChange={(event) => { setSelected(event.target.value); setError(''); setNotice('') }}>
            {data?.personalities.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
          </select>
        </label>
        <label className="form-field">
          Editable prompt
          <textarea
            value={prompt}
            maxLength={50000}
            disabled={!personality}
            onChange={(event) => {
              setDrafts((current) => ({ ...current, [selected]: event.target.value }))
              setError('')
              setNotice('')
            }}
          />
        </label>
        <div className="editor-footer">
          <span className="muted">{prompt.length.toLocaleString()} / 50,000 characters</span>
          <div className="row-actions">
            <button className="secondary" disabled={!personality || Boolean(busy) || (!dirty && isActive)} onClick={() => void runPersonalityAction('apply')}>Apply</button>
            <button className="primary" disabled={!personality || Boolean(busy) || (!dirty && personality.prompt_saved && isActive && data?.active_personality_saved)} onClick={() => void runPersonalityAction('save')}>Save</button>
            <button className="ghost" disabled={!personality || Boolean(busy) || !canReset} onClick={() => void runPersonalityAction('reset')}>Reset</button>
          </div>
        </div>
      </article>
    </section>
  )
}
