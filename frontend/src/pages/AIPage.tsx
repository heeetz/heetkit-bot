import { useEffect, useState } from 'react'

import {
  type AILanguageInfo,
  type AILanguageMode,
  type AILanguageSettings,
  type AIProviderSettings,
  type AIStatus,
  type GeminiModelPreset,
  type PersonalityInfo,
  type PersonalitiesResponse,
  waitForBridge,
} from '../bridge'
import FeedbackToast from '../components/FeedbackToast'
import Switch from '../components/Switch'
import AIPlayground from '../components/AIPlayground'
import BlockedAIUsers from '../components/BlockedAIUsers'
import Accordion from '../components/Accordion'
import HelpTip from '../components/HelpTip'

interface AIPageProps {
  active: boolean
  onOpenSettings: () => void
  onOpenPlayground: () => void
  onOpenAsk: () => void
  onAIEnabledChanged?: (enabled: boolean) => void
}

const CUSTOM_MODEL_VALUE = '__custom_model__'
const DEFAULT_LIMITED_LANGUAGES = ['en', 'uk', 'ru']

function sameLanguageSettings(left: AILanguageSettings, right: AILanguageSettings): boolean {
  return left.mode === right.mode
    && left.fallback_language === right.fallback_language
    && left.allowed_languages.length === right.allowed_languages.length
    && left.allowed_languages.every((code, index) => code === right.allowed_languages[index])
}

function languageSettingsLabel(
  settings: AILanguageSettings,
  languages: AILanguageInfo[],
): string {
  if (settings.mode === 'auto') {
    return 'Auto — match the incoming language without restrictions.'
  }
  const labelFor = (code: string) => languages.find((language) => language.code === code)?.label ?? code
  const allowed = settings.allowed_languages.map(labelFor).join(', ') || 'No languages selected'
  return `Limited — ${allowed}; fallback ${labelFor(settings.fallback_language)}.`
}

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
          aria-label={label}
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
        <details className="custom-model-options">
          <summary>Custom model ID (advanced): {value || 'not set'}</summary>
        <label className="form-field custom-model-field">
          Custom model ID
          <input
            value={value}
            placeholder="gemini-model-id"
            onChange={(event) => onChange(event.target.value)}
          />
        </label>
        </details>
      )}
    </div>
  )
}

export default function AIPage({ active, onOpenSettings, onOpenPlayground, onOpenAsk, onAIEnabledChanged }: AIPageProps) {
  const [status, setStatus] = useState<AIStatus | null>(null)
  const [data, setData] = useState<PersonalitiesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [profileDraft, setProfileDraft] = useState('')
  const [providerSaved, setProviderSaved] = useState<AIProviderSettings | null>(null)
  const [providerDraft, setProviderDraft] = useState<AIProviderSettings | null>(null)
  const [languageSaved, setLanguageSaved] = useState<AILanguageSettings | null>(null)
  const [languageDraft, setLanguageDraft] = useState<AILanguageSettings | null>(null)
  const [languageCatalogue, setLanguageCatalogue] = useState<AILanguageInfo[]>([])
  const [discoveredModels, setDiscoveredModels] = useState<string[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [createName, setCreateName] = useState('')
  const [createPrompt, setCreatePrompt] = useState('')
  const [renameOpen, setRenameOpen] = useState(false)
  const [renameName, setRenameName] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [playgroundSource, setPlaygroundSource] = useState<'personality' | 'profile' | 'language' | 'models' | null>(null)

  const mergeData = (
    response: PersonalitiesResponse,
    completedPersonality = '',
    completedProfile = false,
    draftOverrides: Record<string, string> = {},
  ) => {
    setDrafts((currentDrafts) => Object.fromEntries(response.personalities.map((personality) => {
      const previous = data?.personalities.find((item) => item.name === personality.name)
      const hasOverride = Object.prototype.hasOwnProperty.call(draftOverrides, personality.name)
      const currentDraft = hasOverride ? draftOverrides[personality.name] : currentDrafts[personality.name]
      const keepDraft = hasOverride || (
        personality.name !== completedPersonality
        && previous
        && currentDraft !== undefined
        && currentDraft !== previous.prompt
      )
      return [personality.name, keepDraft ? currentDraft : personality.prompt]
    })))
    setProfileDraft((currentDraft) => {
      const previous = data?.profile_instructions
      const keepDraft = !completedProfile
        && previous !== undefined
        && currentDraft !== previous
      return keepDraft ? currentDraft : response.profile_instructions
    })
    setData(response)
    setSelected((current) => response.personalities.some((item) => item.name === current)
      ? current : response.active_personality)
  }

  const refresh = async (
    completedPersonality = '',
    completedProfile = false,
    draftOverrides: Record<string, string> = {},
  ): Promise<PersonalitiesResponse> => {
    const api = await waitForBridge()
    const [nextStatus, response] = await Promise.all([
      api.get_ai_status(),
      api.get_personalities(),
    ])
    setStatus(nextStatus)
    mergeData(response, completedPersonality, completedProfile, draftOverrides)
    return response
  }

  useEffect(() => {
    if (!active) {
      return
    }
    let current = true
    setLoading(true)
    const load = async () => {
      try {
        const api = await waitForBridge()
        const [nextStatus, response, providerResponse, languageResponse] = await Promise.all([
          api.get_ai_status(),
          api.get_personalities(),
          api.get_ai_provider_settings(),
          api.get_ai_language_settings(),
        ])
        if (!providerResponse.ok || !providerResponse.settings) {
          throw new Error(providerResponse.error ?? 'AI provider settings are unavailable.')
        }
        if (!languageResponse.ok || !languageResponse.settings) {
          throw new Error(languageResponse.error ?? 'AI language settings are unavailable.')
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
          setLanguageCatalogue(languageResponse.languages ?? [])
          setLanguageDraft((draft) => {
            const dirty = Boolean(draft && languageSaved && !sameLanguageSettings(draft, languageSaved))
            return dirty ? draft : languageResponse.settings!
          })
          setLanguageSaved(languageResponse.settings)
          setError('')
        }
      } catch (reason) {
        if (current) {
          setError(reason instanceof Error ? reason.message : 'Could not load AI settings.')
        }
      } finally {
        if (current) setLoading(false)
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
      const nextStatus = await api.get_ai_status()
      setStatus(nextStatus)
      onAIEnabledChanged?.(nextStatus.enabled)
      setNotice(kind === 'enabled' ? 'AI command enabled setting saved.' : 'AI memory state updated.')
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
      return false
    }
    const selectedModel = providerDraft.selected_model.trim()
    const fallbackModel = providerDraft.fallback_model.trim()
    if (!selectedModel || !fallbackModel) {
      setError('Selected and fallback model IDs are required.')
      return false
    }
    if (selectedModel === fallbackModel) {
      setError('Selected and fallback models must be different.')
      return false
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
      return true
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'AI model settings could not be saved.')
      return false
    } finally {
      setBusy('')
    }
  }

  const updateLanguageDraft = (values: Partial<AILanguageSettings>) => {
    setLanguageDraft((current) => {
      if (!current) {
        return current
      }
      const next = { ...current, ...values }
      if (values.mode === 'limited' && next.allowed_languages.length === 0) {
        const defaults = DEFAULT_LIMITED_LANGUAGES.filter((code) => languageCatalogue.some((language) => language.code === code))
        next.allowed_languages = defaults.length > 0 ? defaults : languageCatalogue.slice(0, 3).map((language) => language.code)
        next.fallback_language = next.allowed_languages.includes('en') ? 'en' : (next.allowed_languages[0] ?? '')
      }
      if (values.mode === 'auto') {
        if (next.allowed_languages.length === 0) {
          const savedLanguages = languageSaved?.allowed_languages ?? []
          const defaults = DEFAULT_LIMITED_LANGUAGES.filter((code) => languageCatalogue.some((language) => language.code === code))
          next.allowed_languages = savedLanguages.length > 0
            ? savedLanguages
            : (defaults.length > 0 ? defaults : languageCatalogue.slice(0, 3).map((language) => language.code))
        }
        if (!next.allowed_languages.includes(next.fallback_language)) {
          next.fallback_language = next.allowed_languages.includes('en')
            ? 'en'
            : (next.allowed_languages[0] ?? '')
        }
      }
      return next
    })
    setError('')
    setNotice('')
  }

  const saveLanguageSettings = async () => {
    if (!languageDraft) {
      return false
    }
    const allowedLanguages = Array.from(new Set(languageDraft.allowed_languages))
    if (languageDraft.mode === 'limited' && allowedLanguages.length === 0) {
      setError('Limited mode requires at least one allowed language.')
      return false
    }
    if (languageDraft.mode === 'limited' && !allowedLanguages.includes(languageDraft.fallback_language)) {
      setError('The fallback language must be one of the allowed languages.')
      return false
    }
    setBusy('language:save')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.update_ai_language_settings(
        languageDraft.mode,
        allowedLanguages,
        languageDraft.fallback_language,
      )
      if (!result.ok) {
        throw new Error(result.error ?? 'AI language settings could not be saved.')
      }
      const refreshed = await api.get_ai_language_settings()
      if (!refreshed.ok || !refreshed.settings) {
        throw new Error(refreshed.error ?? 'AI language settings could not be refreshed.')
      }
      setLanguageCatalogue(refreshed.languages ?? languageCatalogue)
      setLanguageSaved(refreshed.settings)
      setLanguageDraft(refreshed.settings)
      await refresh()
      setNotice('AI language settings saved and active for the next request.')
      return true
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'AI language settings could not be saved.')
      return false
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

  const runPersonalityAction = async (action: 'save' | 'reset' | 'active') => {
    const personality = data?.personalities.find((item) => item.name === selected)
    const prompt = drafts[selected]
    if (!personality || prompt === undefined) {
      return false
    }
    if (action === 'reset' && (!personality.is_builtin
      || !window.confirm(`Reset ${selected} to its built-in prompt?`))) {
      return false
    }
    setBusy(action)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = action === 'save'
        ? await api.save_personality(selected, prompt)
        : action === 'active'
          ? await api.set_active_personality(selected)
          : await api.reset_personality(selected)
      if (!result.ok) {
        throw new Error(result.error ?? 'Personality could not be updated.')
      }
      await refresh(action === 'reset' ? selected : '')
      setNotice(action === 'active'
        ? `Set ${selected} as the active personality.`
        : action === 'save'
          ? `Saved ${selected}.`
          : `Restored the built-in ${selected} prompt.`)
      return true
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Personality could not be updated.')
      return false
    } finally {
      setBusy('')
    }
  }

  const createPersonality = async () => {
    const normalizedName = createName.trim()
    if (normalizedName.length < 1 || normalizedName.length > 64) {
      setError('Personality names must be 1–64 characters after trimming.')
      return
    }
    setBusy('create')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.create_personality(normalizedName, createPrompt)
      if (!result.ok) {
        throw new Error(result.error ?? 'Personality could not be created.')
      }
      const createdName = result.name ?? normalizedName
      await refresh('', false)
      setSelected(createdName)
      setCreateName('')
      setCreatePrompt('')
      setCreateOpen(false)
      setNotice(`Created ${createdName}.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Personality could not be created.')
    } finally {
      setBusy('')
    }
  }

  const renamePersonality = async () => {
    const personality = data?.personalities.find((item) => item.name === selected)
    const normalizedName = renameName.trim()
    if (!personality || personality.is_builtin) {
      return
    }
    if (normalizedName.length < 1 || normalizedName.length > 64) {
      setError('Personality names must be 1–64 characters after trimming.')
      return
    }
    if (normalizedName === selected) {
      setError('Choose a different personality name.')
      return
    }
    setBusy('rename')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.rename_personality(selected, normalizedName)
      if (!result.ok) {
        throw new Error(result.error ?? 'Personality could not be renamed.')
      }
      const renamedName = result.name ?? normalizedName
      const draft = drafts[selected]
      const refreshed = await refresh('', false, draft === undefined ? {} : { [renamedName]: draft })
      setSelected(refreshed.personalities.some((item) => item.name === renamedName) ? renamedName : selected)
      setRenameName('')
      setRenameOpen(false)
      setNotice(`Renamed ${selected} to ${renamedName}.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Personality could not be renamed.')
    } finally {
      setBusy('')
    }
  }

  const deletePersonality = async () => {
    const personality = data?.personalities.find((item) => item.name === selected)
    if (!personality || personality.is_builtin
      || !window.confirm(`Delete the custom personality ${selected}?`)) {
      return
    }
    setBusy('delete')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.delete_personality(selected)
      if (!result.ok) {
        throw new Error(result.error ?? 'Personality could not be deleted.')
      }
      const deletedName = selected
      const refreshed = await refresh()
      const nextSelected = refreshed.personalities.some((item) => item.name === deletedName)
        ? deletedName
        : refreshed.active_personality || refreshed.personalities[0]?.name || ''
      setSelected(nextSelected)
      setRenameOpen(false)
      setDrafts((current) => {
        const next = { ...current }
        delete next[deletedName]
        return next
      })
      setNotice(`Deleted ${deletedName}.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Personality could not be deleted.')
    } finally {
      setBusy('')
    }
  }

  const runProfileAction = async (action: 'apply' | 'save' | 'reset') => {
    if (!data) {
      return false
    }
    if (action === 'reset' && !window.confirm('Reset profile instructions to empty?')) {
      return false
    }
    setBusy(`profile:${action}`)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = action === 'apply'
        ? await api.apply_profile_instructions(profileDraft)
        : action === 'save'
          ? await api.save_profile_instructions(profileDraft)
          : await api.reset_profile_instructions()
      if (!result.ok) {
        throw new Error(result.error ?? 'Profile instructions could not be updated.')
      }
      await refresh('', true)
      setNotice(action === 'apply'
        ? 'Applied profile instructions for this session.'
        : action === 'save'
          ? 'Saved profile instructions.'
          : 'Reset profile instructions to empty.')
      return true
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Profile instructions could not be updated.')
      return false
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
      && personality.is_builtin
      && (dirty || personality.has_saved_override || personality.prompt !== personality.built_in_prompt),
  )
  const profileValue = data ? profileDraft : ''
  const profileDirty = data ? profileValue !== data.profile_instructions : false
  const profileCanReset = Boolean(
    data && (profileDirty || !data.profile_instructions_saved || profileValue.length > 0),
  )
  const providerDirty = Boolean(
    providerDraft && providerSaved
      && (providerDraft.selected_model !== providerSaved.selected_model
        || providerDraft.fallback_model !== providerSaved.fallback_model),
  )
  const languageDirty = Boolean(
    languageDraft && languageSaved && !sameLanguageSettings(languageDraft, languageSaved),
  )
  const languageValidation = languageDraft?.mode === 'limited'
    ? languageDraft.allowed_languages.length === 0
      ? 'Limited mode requires at least one allowed language.'
      : !languageDraft.allowed_languages.includes(languageDraft.fallback_language)
        ? 'The fallback language must be one of the allowed languages.'
        : ''
    : ''

  const hasDrafts = Boolean(profileDirty || providerDirty || languageDirty
    || data?.personalities.some((item) => drafts[item.name] !== undefined && drafts[item.name] !== item.prompt)
    || (createOpen && (createName || createPrompt)))

  const openPlayground = () => {
    setPlaygroundSource(null)
    onOpenPlayground()
  }

  const saveForPlayground = async (source: NonNullable<typeof playgroundSource>, apply = false) => {
    const succeeded = source === 'personality' ? await runPersonalityAction('save')
      : source === 'profile' ? await runProfileAction(apply ? 'apply' : 'save')
        : source === 'language' ? await saveLanguageSettings() : await saveProviderModels()
    if (succeeded) openPlayground()
  }

  const playgroundButton = (source: NonNullable<typeof playgroundSource>, needsChoice: boolean) => (
    <button className="secondary" disabled={loading || Boolean(busy)} onClick={() => needsChoice ? setPlaygroundSource(source) : openPlayground()}>Open Playground</button>
  )

  const playgroundChoice = (source: NonNullable<typeof playgroundSource>) => (
    playgroundSource === source && <div className="setup-callout playground-draft-choice">
        <div>
          <strong>Choose what Playground will use</strong>
          <p>Other editor drafts are kept and are never used automatically.</p>
          {source === 'personality' && <p>Playground uses {data?.active_personality || 'the active personality'}. Saving {selected} does not activate it; use Set active separately to test an inactive personality.</p>}
          {source === 'profile' && <p>Apply uses this draft for the current session. Save also keeps it across restarts.</p>}
          <div className="row-actions">
            {(source !== 'personality' || dirty || !personality?.prompt_saved) && <button className="primary" disabled={Boolean(busy) || (source === 'language' && Boolean(languageValidation))} onClick={() => void saveForPlayground(source)}>Save {source === 'profile' && !profileDirty ? 'applied instructions' : source === 'personality' && !dirty ? 'applied prompt' : 'draft'} and open Playground</button>}
            {source === 'profile' && profileDirty && <button className="secondary" disabled={Boolean(busy)} onClick={() => void saveForPlayground(source, true)}>Apply draft and open Playground</button>}
            <button className="secondary" disabled={Boolean(busy)} onClick={openPlayground}>Use current applied settings</button>
            <button className="ghost" disabled={Boolean(busy)} onClick={() => setPlaygroundSource(null)}>Cancel</button>
          </div>
        </div>
      </div>
  )

  return (
    <section className="ai-layout" aria-busy={loading}>
      <FeedbackToast
        error={error}
        notice={notice}
        onDismiss={() => { setError(''); setNotice('') }}
      />
      <div className="ai-status-grid" id="ai-runtime">
        <article className="card ai-state-panel">
          <div className="ai-state-heading">
            <h2>AI command</h2>
            <HelpTip label="AI command">Saved immediately across restarts. Dashboard, AI and Commands share this !ask setting. If Gemini is unavailable, the enabled preference is retained; add a usable API key to enable replies.</HelpTip>
          </div>
          <Switch
            className="settings-toggle"
            checked={status?.enabled ?? false}
            disabled={!status || Boolean(busy)}
            ariaLabel="Enable AI command"
            onCheckedChange={(enabled) => void changeToggle('enabled', enabled)}
          >
            <span>{status ? status.enabled ? 'Enabled' : 'Disabled' : 'Loading…'}</span>
          </Switch>
        </article>
        <article className="card ai-state-panel" id="ai-memory">
          <div className="ai-state-heading">
            <h2>Conversation memory</h2>
            <HelpTip label="Conversation memory">Saved immediately. Turning memory off stops subsequent use and storage; previously stored data is retained. !ask uses up to five successful exchanges per viewer. Playground never reads or stores viewer memory. The broadcaster-only !erase username command clears AI memory for a known viewer; it does not delete chat or activity records.</HelpTip>
          </div>
          <Switch className="settings-toggle" checked={status?.memory_enabled ?? false} disabled={!status || Boolean(busy)} ariaLabel="Enable conversation memory" onCheckedChange={(enabled) => void changeToggle('memory', enabled)}>
            <span>{status ? status.memory_enabled ? 'Enabled' : 'Disabled' : 'Loading…'}</span>
          </Switch>
        </article>
        <article className="card ai-state-panel">
          <div className="ai-state-heading ai-gemini-heading">
            <h2>Gemini</h2>
            <div className="ai-state-actions">
              <HelpTip label="Gemini">Gemini is optional. Manage the API key in Settings and use Test credential to validate access. A valid key does not prove model availability or quota; test generation separately in Playground.</HelpTip>
              <button className="secondary" disabled={loading} aria-label={providerSaved?.credential?.configured ? 'Manage Gemini key' : 'Add Gemini key'} onClick={onOpenSettings}>Manage</button>
            </div>
          </div>
          <span className="ai-availability">{status ? status.available ? 'Configured for requests' : 'Unavailable' : 'Loading…'}</span>
          <span className="ai-model-label">Active model</span>
          <strong>{status ? status.model || 'Not selected' : 'Loading…'}</strong>
        </article>
        <article className="card ai-state-panel">
          <div className="ai-state-heading"><h2>Active personality</h2></div>
          <strong>{data ? data.active_personality || 'Not selected' : 'Loading…'}</strong>
        </article>
      </div>
      <AIPlayground active={active} personality={data?.active_personality ?? ''} hasDrafts={hasDrafts} />
      <Accordion
        id="ai-personalities"
        title="Personality-specific prompt"
        description="Save this personality independently of profile instructions. Set active selects its applied prompt and does not save an editor draft."
        badges={(
          <span className="personality-badges">
            {personality && <span className="mini-badge">{personality.is_builtin ? 'Built-in' : 'Custom'}</span>}
            {isActive && <span className="mini-badge saved-badge">Active</span>}
            {personality?.has_saved_override && <span className="mini-badge saved-badge">Saved override</span>}
            {data && !data.active_personality_saved && isActive && <span className="mini-badge runtime-badge">Runtime only</span>}
            {dirty && <span className="mini-badge dirty-badge">Edited</span>}
          </span>
        )}
        className="personality-editor"
      >
        {data && data.personalities.length === 0 ? (
          <div className="empty-state-inline">
            <strong>No personalities are available</strong>
            <p>The built-in personality resources could not be loaded. Check Logs for details.</p>
          </div>
        ) : (
          <>
            <div className="personality-toolbar">
              <label className="form-field personality-select">
                Personality
                <select value={selected} onChange={(event) => {
                  setSelected(event.target.value)
                  setRenameOpen(false)
                  setError('')
                  setNotice('')
                }}>
                  {data?.personalities.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
                </select>
              </label>
              <div className="row-actions personality-management-actions">
                <button className="secondary" disabled={Boolean(busy)} onClick={() => {
                  setCreateOpen((current) => !current)
                  setRenameOpen(false)
                  setError('')
                  setNotice('')
                }}>{createOpen ? 'Cancel new personality' : 'New personality'}</button>
                <button className="secondary" disabled={!personality || personality.is_builtin || Boolean(busy)} onClick={() => {
                  setRenameOpen((current) => !current)
                  setRenameName(selected)
                  setCreateOpen(false)
                  setError('')
                  setNotice('')
                }}>{renameOpen ? 'Cancel rename' : 'Rename'}</button>
                <button className="ghost destructive" disabled={!personality || personality.is_builtin || Boolean(busy)} onClick={() => void deletePersonality()}>Delete</button>
              </div>
            </div>
            {createOpen && (
              <div className="personality-inline-form">
                <div className="section-heading">
                  <div>
                    <h3>New personality</h3>
                    <p className="section-copy">Create a custom personality without making it active.</p>
                  </div>
                </div>
                <div className="personality-inline-fields">
                  <label className="form-field">
                    Name
                    <input
                      value={createName}
                      maxLength={64}
                      placeholder="e.g. Concise helper"
                      onChange={(event) => { setCreateName(event.target.value); setError(''); setNotice('') }}
                    />
                  </label>
                  <label className="form-field">
                    Prompt
                    <textarea
                      value={createPrompt}
                      maxLength={50000}
                      onChange={(event) => { setCreatePrompt(event.target.value); setError(''); setNotice('') }}
                    />
                  </label>
                </div>
                <div className="row-actions">
                  <button className="primary" disabled={Boolean(busy)} onClick={() => void createPersonality()}>Create</button>
                </div>
              </div>
            )}
            {renameOpen && personality && !personality.is_builtin && (
              <div className="personality-rename-form">
                <label className="form-field">
                  New name
                  <input
                    value={renameName}
                    maxLength={64}
                    onChange={(event) => { setRenameName(event.target.value); setError(''); setNotice('') }}
                  />
                </label>
                <div className="row-actions">
                  <button className="primary" disabled={Boolean(busy)} onClick={() => void renamePersonality()}>Rename</button>
                </div>
              </div>
            )}
            {!createOpen && <>
            <p className="setting-effect">Editing <strong>{selected}</strong>; Playground uses <strong>{data?.active_personality || 'the active personality'}</strong>. Saving an inactive personality does not activate it.</p>
            <p className="setting-effect">{dirty ? 'Unsaved prompt draft; it is not used by AI requests.' : personality?.prompt_saved ? 'Prompt saved across restarts.' : 'Prompt applied for this session; not saved across restarts.'}</p>
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
            <div className="editor-footer ai-editor-footer">
              <div className="ai-editor-leading">
                {playgroundButton('personality', dirty || !isActive || !Boolean(personality?.prompt_saved))}
                <span className="muted">{prompt.length.toLocaleString()} / 50,000 characters</span>
              </div>
              <div className="row-actions">
                <button className="secondary" disabled={!personality || Boolean(busy) || (isActive && Boolean(data?.active_personality_saved))} onClick={() => void runPersonalityAction('active')}>{busy === 'active' ? 'Setting active…' : 'Set active'}</button>
                <button className="primary" disabled={!personality || Boolean(busy) || (!dirty && personality.prompt_saved)} onClick={() => void runPersonalityAction('save')}>{busy === 'save' ? 'Saving…' : 'Save'}</button>
                <button className="ghost" disabled={!personality || Boolean(busy) || !canReset} onClick={() => void runPersonalityAction('reset')}>{busy === 'reset' ? 'Resetting…' : 'Reset'}</button>
              </div>
            </div>
            {playgroundChoice('personality')}
            </>}
          </>
        )}
      </Accordion>
      <Accordion
        id="ai-profile-instructions"
        title="Profile instructions"
        description="Applies to every personality and follows the protected shared policy."
        badges={(
          <span className="personality-badges">
            {data?.profile_instructions_saved && <span className="mini-badge saved-badge">Saved</span>}
            {data && !data.profile_instructions_saved && <span className="mini-badge runtime-badge">Runtime only</span>}
            {profileDirty && <span className="mini-badge dirty-badge">Edited</span>}
          </span>
        )}
        className="profile-instructions-editor"
      >
        <p className="setting-effect">{data?.profile_instructions_saved ? 'Applied instructions are saved across restarts.' : 'Instructions applied for this session only; Save keeps them across restarts.'} {profileDirty && 'This unsaved editor draft is not applied. Apply or Save it explicitly before testing.'}</p>
        <label className="form-field">
          Profile instructions
          <textarea
            value={profileValue}
            maxLength={50000}
            disabled={!data}
            onChange={(event) => {
              setProfileDraft(event.target.value)
              setError('')
              setNotice('')
            }}
          />
        </label>
        <div className="editor-footer ai-editor-footer">
          <div className="ai-editor-leading">
            {playgroundButton('profile', profileDirty || !Boolean(data?.profile_instructions_saved))}
            <span className="muted">{profileValue.length.toLocaleString()} / 50,000 characters</span>
          </div>
          <div className="row-actions">
            <button className="secondary" disabled={!data || Boolean(busy) || !profileDirty} onClick={() => void runProfileAction('apply')}>{busy === 'profile:apply' ? 'Applying…' : 'Apply'}</button>
            <button className="primary" disabled={!data || Boolean(busy) || (!profileDirty && Boolean(data.profile_instructions_saved))} onClick={() => void runProfileAction('save')}>{busy === 'profile:save' ? 'Saving…' : 'Save'}</button>
            <button className="ghost" disabled={!data || Boolean(busy) || !profileCanReset} onClick={() => void runProfileAction('reset')}>{busy === 'profile:reset' ? 'Resetting…' : 'Reset'}</button>
          </div>
        </div>
        {playgroundChoice('profile')}
      </Accordion>
      <Accordion
        id="ai-language"
        title="AI response language"
        description="Auto follows the incoming language; Limited uses this profile's allowed languages and fallback. Saved changes apply to the next AI request. Prompt guidance cannot perfectly guarantee a response language. In Limited mode, clear brief input uses its language; mixed or code-switched input uses the clear majority; uncertain, tied, unsupported, emoji-only and code-only input uses the saved fallback. Playground uses the saved policy until you explicitly save a draft."
        badges={(
          <span className="personality-badges">
            {languageSaved && <span className="mini-badge saved-badge">Saved active policy</span>}
            {languageDirty && <span className="mini-badge dirty-badge">Edited</span>}
          </span>
        )}
        className="ai-language-card"
      >
        {!languageDraft || !languageSaved ? <p className="muted">Loading response language settings…</p> : (
          <div className="settings-list">
            <div className={`language-policy-status${languageDirty ? ' has-draft' : ''}`}>
              <div>
                <span>Active policy</span>
                <strong>{languageSettingsLabel(languageSaved, languageCatalogue)}</strong>
              </div>
              {languageDirty && <div>
                <span>Draft configuration</span>
                <strong>{languageSettingsLabel(languageDraft, languageCatalogue)}</strong>
              </div>}
            </div>
            <div className="language-fields">
              <label className="form-field">
                <span>Response language mode</span>
                <select
                  aria-label="Response language mode"
                  value={languageDraft.mode}
                  disabled={Boolean(busy)}
                  onChange={(event) => updateLanguageDraft({ mode: event.target.value as AILanguageMode })}
                >
                  <option value="auto">Auto</option>
                  <option value="limited">Limited</option>
                </select>
                <small>Auto follows the user without language restrictions. Limited uses the allowed set below.</small>
              </label>
              <label className="form-field">
                <span>Fallback language</span>
                <select
                  aria-label="Fallback language"
                  value={languageDraft.fallback_language}
                  disabled={Boolean(busy) || languageDraft.mode !== 'limited'}
                  onChange={(event) => updateLanguageDraft({ fallback_language: event.target.value })}
                >
                  {languageCatalogue
                    .filter((language) => languageDraft.allowed_languages.includes(language.code)
                      || language.code === languageDraft.fallback_language)
                    .map((language) => <option key={language.code} value={language.code}>{language.label}</option>)}
                </select>
                <small>Used when Limited mode cannot identify an allowed response language.</small>
              </label>
            </div>
            <fieldset className="language-picker" disabled={Boolean(busy) || languageDraft.mode !== 'limited'}>
              <legend>Allowed languages</legend>
              <div className="language-options">
                {languageCatalogue.map((language) => (
                  <label className="language-option" key={language.code}>
                    <input
                      type="checkbox"
                      aria-label={language.label}
                      checked={languageDraft.allowed_languages.includes(language.code)}
                      onChange={(event) => updateLanguageDraft({
                        allowed_languages: event.target.checked
                          ? [...languageDraft.allowed_languages, language.code]
                          : languageDraft.allowed_languages.filter((code) => code !== language.code),
                      })}
                    />
                    <span>{language.label}</span>
                    <code>{language.code}</code>
                  </label>
                ))}
              </div>
            </fieldset>
            {languageValidation && <p className="language-validation" role="status">{languageValidation}</p>}
            <div className="editor-footer ai-editor-footer">
              <span className="muted">{languageDirty ? 'Unsaved draft; saved policy applies.' : 'Saved and applied.'}</span>
              <div className="row-actions">
                {playgroundButton('language', languageDirty)}
                <button className="primary" disabled={Boolean(busy) || !languageDirty || Boolean(languageValidation)} onClick={() => void saveLanguageSettings()}>{busy === 'language:save' ? 'Saving…' : 'Save language settings'}</button>
              </div>
            </div>
            {playgroundChoice('language')}
          </div>
        )}
      </Accordion>
      <article className="card ai-provider-card" id="ai-models">
        <div className="section-heading">
          <div>
            <h2>Models and fallback</h2>
            <p className="section-copy">Choose the model used for AI requests and its unavailable-model fallback.</p>
          </div>
          {providerDirty && <span className="mini-badge dirty-badge">Edited</span>}
        </div>
        {!providerDraft ? <p className="muted">Loading AI provider settings…</p> : (
          <div className="settings-list">
            <p className="model-policy-status">Saved primary model: <strong>{providerSaved?.selected_model || 'Not selected'}</strong>. {providerDirty ? 'Unsaved model draft; Playground keeps using the saved models.' : 'Changes apply after Save models.'}</p>
              <ModelSelector
                label="Primary model"
                value={providerDraft.selected_model}
                presets={providerDraft.presets}
                discoveredModels={discoveredModels}
                onChange={(selected_model) => updateProviderDraft({ selected_model })}
                help="Used for AI requests."
              />
            <details className="model-advanced">
              <summary>Advanced model options</summary>
              <ModelSelector
                label="Fallback model"
                value={providerDraft.fallback_model}
                presets={providerDraft.presets}
                discoveredModels={discoveredModels}
                onChange={(fallback_model) => updateProviderDraft({ fallback_model })}
                help="Used only after the primary model returns 404. Key, network, quota and billing failures do not trigger fallback."
              />
            </details>
            <div className="model-action-row">
              <div className="model-action-group">
                <button className="secondary" disabled={Boolean(busy) || !providerDraft.credential?.configured} onClick={() => void discoverModels()}>{busy === 'provider:discover' ? 'Discovering…' : 'Discover models'}</button>
              </div>
              <div className="model-action-group model-save-actions">
                {playgroundButton('models', providerDirty)}
                <button className="primary" disabled={Boolean(busy) || !providerDirty} onClick={() => void saveProviderModels()}>{busy === 'provider:save' ? 'Saving…' : 'Save models'}</button>
              </div>
            </div>
            {playgroundChoice('models')}
          </div>
        )}
      </article>
      <BlockedAIUsers active={active} onOpenAsk={onOpenAsk} />
      <details className="card protected-instructions-card" id="ai-shared-instructions">
        <summary className="protected-instructions-summary">
          <div>
            <h2>Built-in restrictions</h2>
            <p className="section-copy">These instructions are managed by the application and cannot be edited here.</p>
          </div>
          <span className="mini-badge">Application-owned</span>
        </summary>
        <div className="protected-instructions-details">
          <label className="form-field">
            Shared instructions
            <textarea
              value={data?.protected_shared_instructions ?? ''}
              readOnly
              aria-label="Protected shared instructions"
            />
          </label>
        </div>
      </details>
    </section>
  )
}
