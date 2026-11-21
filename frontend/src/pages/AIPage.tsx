import { Fragment, useEffect, useState, type ReactNode } from 'react'

import {
  type AILanguageInfo,
  type AILanguageMode,
  type AILanguageSettings,
  type AIStatus,
  type PersonalityInfo,
  type PersonalitiesResponse,
  waitForBridge,
} from '../bridge'
import FeedbackToast from '../components/FeedbackToast'
import Switch from '../components/Switch'
import AIPlayground from '../components/AIPlayground'
import AISetupPanel from '../components/AISetupPanel'
import AIBehaviorSection from '../components/AIBehaviorSection'
import Confirmation from '../components/Confirmation'
import EditorDialog, { EditorSections } from '../components/EditorDialog'
import HelpTip from '../components/HelpTip'
import AIMemoryLimits from '../components/AIMemoryLimits'
import { Select } from '../components/Select'
import { useRestartDraft } from '../desktopRestart'
import { aiText } from '../i18n/ai'
import { common as commonText } from '../i18n/common'
import { catalogFor, useCatalog, useI18n } from '../i18n/core'

interface AIPageProps {
  active: boolean
  onOpenPlayground: () => void
  onAIEnabledChanged?: (enabled: boolean) => void
}

type AIBehaviorSectionId = 'profile' | 'personalities' | 'shared' | 'languages'

const DEFAULT_LIMITED_LANGUAGES = ['en', 'uk', 'ru']

function sameLanguageSettings(left: AILanguageSettings, right: AILanguageSettings): boolean {
  return left.mode === right.mode
    && left.fallback_language === right.fallback_language
    && left.allowed_languages.length === right.allowed_languages.length
    && left.allowed_languages.every((code, index) => code === right.allowed_languages[index])
}

function languageSettingsLabel(
  settings: AILanguageSettings,
  labelFor: (code: string) => string,
  text: typeof aiText.en.language,
  fmt: (template: string, params?: Record<string, string | number>) => string,
): string {
  if (settings.mode === 'auto') {
    return text.autoSummary
  }
  const allowed = settings.allowed_languages.map(labelFor).join(', ') || text.noneSelected
  return fmt(text.limitedSummary, { allowed, fallback: labelFor(settings.fallback_language) })
}

/** Fill {name} placeholders with React nodes, keeping the surrounding text. */
function rich(template: string, values: Record<string, ReactNode>): ReactNode[] {
  return template.split(/\{(\w+)\}/g).map((part, index) => index % 2
    ? <Fragment key={index}>{values[part] ?? `{${part}}`}</Fragment>
    : part)
}

/** Response language names: English keeps the backend label; uk/ru use Intl names. */
function languageName(code: string, label: string | undefined, language: string, locale: string): string {
  if (language !== 'en') {
    try {
      const name = new Intl.DisplayNames([locale], { type: 'language' }).of(code)
      if (name && name !== code) return name.charAt(0).toLocaleUpperCase(locale) + name.slice(1)
    } catch { /* Unknown codes keep the backend label. */ }
  }
  return label ?? code
}

export default function AIPage({ active, onOpenPlayground, onAIEnabledChanged }: AIPageProps) {
  const [status, setStatus] = useState<AIStatus | null>(null)
  const [data, setData] = useState<PersonalitiesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [profileDraft, setProfileDraft] = useState('')
  const [setupDirty, setSetupDirty] = useState(false)
  const [instructionsTarget, setInstructionsTarget] = useState<HTMLDivElement | null>(null)
  const [instructionsDirty, setInstructionsDirty] = useState(false)
  const [instructionsBusy, setInstructionsBusy] = useState(false)
  const [memoryDirty, setMemoryDirty] = useState(false)
  const [discardVersion, setDiscardVersion] = useState(0)
  const [behaviorSection, setBehaviorSection] = useState<AIBehaviorSectionId | null>(null)
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const [languageSaved, setLanguageSaved] = useState<AILanguageSettings | null>(null)
  const [languageDraft, setLanguageDraft] = useState<AILanguageSettings | null>(null)
  const [languageCatalogue, setLanguageCatalogue] = useState<AILanguageInfo[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [createName, setCreateName] = useState('')
  const [createPrompt, setCreatePrompt] = useState('')
  const [renameOpen, setRenameOpen] = useState(false)
  const [renameName, setRenameName] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [playgroundSource, setPlaygroundSource] = useState<'personality' | 'profile' | 'language' | null>(null)
  const text = useCatalog(aiText)
  const common = useCatalog(commonText)
  const { fmt, number, language: uiLanguage, locale } = useI18n()
  const labelFor = (code: string) => languageName(code, languageCatalogue.find((item) => item.code === code)?.label, uiLanguage, locale)

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
        const [nextStatus, response, languageResponse] = await Promise.all([
          api.get_ai_status(),
          api.get_personalities(),
          api.get_ai_language_settings(),
        ])
        if (!languageResponse.ok || !languageResponse.settings) {
          throw new Error(languageResponse.error ?? catalogFor(aiText).page.languageUnavailable)
        }
        if (current) {
          setStatus(nextStatus)
          mergeData(response)
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
          setError(reason instanceof Error ? reason.message : catalogFor(aiText).page.loadFailed)
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
        throw new Error(result.error ?? text.page.toggleFailed)
      }
      const nextStatus = await api.get_ai_status()
      setStatus(nextStatus)
      onAIEnabledChanged?.(nextStatus.enabled)
      setNotice(kind === 'enabled' ? text.page.enabledSaved : text.page.memorySaved)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.page.toggleFailed)
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
      setError(text.language.needsLanguage)
      return false
    }
    if (languageDraft.mode === 'limited' && !allowedLanguages.includes(languageDraft.fallback_language)) {
      setError(text.language.fallbackAllowed)
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
        throw new Error(result.error ?? text.language.saveFailed)
      }
      const refreshed = await api.get_ai_language_settings()
      if (!refreshed.ok || !refreshed.settings) {
        throw new Error(refreshed.error ?? text.language.refreshFailed)
      }
      setLanguageCatalogue(refreshed.languages ?? languageCatalogue)
      setLanguageSaved(refreshed.settings)
      setLanguageDraft(refreshed.settings)
      await refresh()
      setNotice(text.language.savedNotice)
      return true
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.language.saveFailed)
      return false
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
      || !window.confirm(fmt(text.personality.confirmReset, { name: selected })))) {
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
        throw new Error(result.error ?? text.personality.updateFailed)
      }
      await refresh(action === 'reset' ? selected : '')
      setNotice(fmt(action === 'active'
        ? text.personality.setActiveDone
        : action === 'save'
          ? text.personality.saved
          : text.personality.restored, { name: selected }))
      return true
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.personality.updateFailed)
      return false
    } finally {
      setBusy('')
    }
  }

  const createPersonality = async () => {
    const normalizedName = createName.trim()
    if (normalizedName.length < 1 || normalizedName.length > 64) {
      setError(text.personality.nameLength)
      return
    }
    setBusy('create')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.create_personality(normalizedName, createPrompt)
      if (!result.ok) {
        throw new Error(result.error ?? text.personality.createFailed)
      }
      const createdName = result.name ?? normalizedName
      await refresh('', false)
      setSelected(createdName)
      setCreateName('')
      setCreatePrompt('')
      setCreateOpen(false)
      setNotice(fmt(text.personality.created, { name: createdName }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.personality.createFailed)
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
      setError(text.personality.nameLength)
      return
    }
    if (normalizedName === selected) {
      setError(text.personality.chooseDifferent)
      return
    }
    setBusy('rename')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.rename_personality(selected, normalizedName)
      if (!result.ok) {
        throw new Error(result.error ?? text.personality.renameFailed)
      }
      const renamedName = result.name ?? normalizedName
      const draft = drafts[selected]
      const refreshed = await refresh('', false, draft === undefined ? {} : { [renamedName]: draft })
      setSelected(refreshed.personalities.some((item) => item.name === renamedName) ? renamedName : selected)
      setRenameName('')
      setRenameOpen(false)
      setNotice(fmt(text.personality.renamed, { from: selected, to: renamedName }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.personality.renameFailed)
    } finally {
      setBusy('')
    }
  }

  const deletePersonality = async () => {
    const personality = data?.personalities.find((item) => item.name === selected)
    if (!personality || personality.is_builtin
      || !window.confirm(fmt(text.personality.confirmDelete, { name: selected }))) {
      return
    }
    setBusy('delete')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.delete_personality(selected)
      if (!result.ok) {
        throw new Error(result.error ?? text.personality.deleteFailed)
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
      setNotice(fmt(text.personality.deleted, { name: deletedName }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.personality.deleteFailed)
    } finally {
      setBusy('')
    }
  }

  const runProfileAction = async (action: 'apply' | 'save' | 'reset') => {
    if (!data) {
      return false
    }
    if (action === 'reset' && !window.confirm(text.profile.confirmReset)) {
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
        throw new Error(result.error ?? text.profile.updateFailed)
      }
      await refresh('', true)
      setNotice(action === 'apply'
        ? text.profile.applied
        : action === 'save'
          ? text.profile.savedNotice
          : text.profile.resetNotice)
      return true
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.profile.updateFailed)
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
  const languageDirty = Boolean(
    languageDraft && languageSaved && !sameLanguageSettings(languageDraft, languageSaved),
  )
  const languageValidation = languageDraft?.mode === 'limited'
    ? languageDraft.allowed_languages.length === 0
      ? text.language.needsLanguage
      : !languageDraft.allowed_languages.includes(languageDraft.fallback_language)
        ? text.language.fallbackAllowed
        : ''
    : ''

  const behaviorDirty = Boolean(profileDirty || instructionsDirty || languageDirty
    || data?.personalities.some((item) => drafts[item.name] !== undefined && drafts[item.name] !== item.prompt)
    || (createOpen && (createName || createPrompt))
    || (renameOpen && renameName !== selected))
  const hasDrafts = setupDirty || behaviorDirty || memoryDirty
  const behaviorBusy = Boolean(busy) || instructionsBusy

  const closeBehavior = () => {
    if (behaviorBusy) return
    if (behaviorDirty) {
      setConfirmDiscard(true)
      return
    }
    setBehaviorSection(null)
    setCreateOpen(false)
    setRenameOpen(false)
    setPlaygroundSource(null)
    setError('')
    setNotice('')
  }

  const discardBehavior = () => {
    setDrafts(Object.fromEntries(data?.personalities.map((item) => [item.name, item.prompt]) ?? []))
    setProfileDraft(data?.profile_instructions ?? '')
    setLanguageDraft(languageSaved)
    setCreateName('')
    setCreatePrompt('')
    setRenameName('')
    setDiscardVersion((count) => count + 1)
    setConfirmDiscard(false)
    setBehaviorSection(null)
    setCreateOpen(false)
    setRenameOpen(false)
    setPlaygroundSource(null)
    setError('')
    setNotice('')
  }

  useRestartDraft('AI', hasDrafts)

  const openPlayground = () => {
    setBehaviorSection(null)
    setPlaygroundSource(null)
    onOpenPlayground()
  }

  const saveForPlayground = async (source: NonNullable<typeof playgroundSource>, apply = false) => {
    const succeeded = source === 'personality' ? await runPersonalityAction('save')
      : source === 'profile' ? await runProfileAction(apply ? 'apply' : 'save')
        : await saveLanguageSettings()
    if (succeeded) openPlayground()
  }

  const playgroundButton = (source: NonNullable<typeof playgroundSource>, needsChoice: boolean) => (
    <button className="secondary" disabled={loading || Boolean(busy)} onClick={() => needsChoice ? setPlaygroundSource(source) : openPlayground()}>{text.playgroundChoice.openPlayground}</button>
  )

  const playgroundChoice = (source: NonNullable<typeof playgroundSource>) => (
    playgroundSource === source ? <div className="setup-callout playground-draft-choice">
        <div>
          <strong>{text.playgroundChoice.title}</strong>
          <p>{text.playgroundChoice.keptDrafts}</p>
          {source === 'personality' && <p>{fmt(text.playgroundChoice.personality, { active: data?.active_personality || text.playgroundChoice.theActivePersonality, selected })}</p>}
          {source === 'profile' && <p>{text.playgroundChoice.profile}</p>}
          <div className="row-actions">
            {(source !== 'personality' || dirty || !personality?.prompt_saved) && <button className="primary" disabled={Boolean(busy) || (source === 'language' && Boolean(languageValidation))} onClick={() => void saveForPlayground(source)}>{source === 'profile' && !profileDirty ? text.playgroundChoice.saveAppliedInstructions : source === 'personality' && !dirty ? text.playgroundChoice.saveAppliedPrompt : text.playgroundChoice.saveDraft}</button>}
            {source === 'profile' && profileDirty && <button className="secondary" disabled={Boolean(busy)} onClick={() => void saveForPlayground(source, true)}>{text.playgroundChoice.applyDraft}</button>}
            <button className="secondary" disabled={Boolean(busy)} onClick={openPlayground}>{text.playgroundChoice.useApplied}</button>
            <button className="ghost" disabled={Boolean(busy)} onClick={() => setPlaygroundSource(null)}>{common.cancel}</button>
          </div>
        </div>
      </div> : null
  )

  const personalityEditor = (
    <AIBehaviorSection
      id="ai-personalities"
      title={text.personality.title}
      helpLabel={text.personality.helpLabel}
      description={<ul>{text.personality.help.map((item) => <li key={item}>{item}</li>)}</ul>}
      badges={(
        <span className="personality-badges">
          {personality && <span className="mini-badge">{personality.is_builtin ? text.personality.builtIn : text.personality.custom}</span>}
          {isActive && <span className="mini-badge saved-badge">{text.personality.active}</span>}
          {personality?.has_saved_override && <span className="mini-badge saved-badge">{text.personality.savedOverride}</span>}
          {data && !data.active_personality_saved && isActive && <span className="mini-badge runtime-badge">{text.personality.runtimeOnly}</span>}
          {dirty && <span className="mini-badge dirty-badge">{text.personality.edited}</span>}
        </span>
      )}
      className="personality-editor"
      footer={!createOpen && data?.personalities.length !== 0 && (
        playgroundChoice('personality') ?? (
          <div className="editor-footer ai-editor-footer">
            <div className="ai-editor-leading">
              {playgroundButton('personality', dirty || !isActive || !Boolean(personality?.prompt_saved))}
              <span className="muted">{fmt(text.personality.characters, { count: number(prompt.length), max: number(50000) })}</span>
            </div>
            <div className="row-actions">
              <button className="secondary" disabled={!personality || Boolean(busy) || (isActive && Boolean(data?.active_personality_saved))} onClick={() => void runPersonalityAction('active')}>{busy === 'active' ? text.personality.settingActive : text.personality.setActive}</button>
              <button className="primary" disabled={!personality || Boolean(busy) || (!dirty && personality.prompt_saved)} onClick={() => void runPersonalityAction('save')}>{busy === 'save' ? common.saving : common.save}</button>
              <button className="ghost" disabled={!personality || Boolean(busy) || !canReset} onClick={() => void runPersonalityAction('reset')}>{busy === 'reset' ? text.personality.resetting : text.personality.reset}</button>
            </div>
          </div>
        )
      )}
    >
      {data && data.personalities.length === 0 ? (
        <div className="empty-state-inline">
          <strong>{text.personality.noneTitle}</strong>
          <p>{text.personality.noneText}</p>
        </div>
      ) : (
        <>
          <div className="personality-toolbar">
            <label className="form-field personality-select">
              {text.personality.personality}
              <Select value={selected} onChange={(value) => {
                setSelected(value)
                setRenameOpen(false)
                setError('')
                setNotice('')
              }} options={data?.personalities.map((item) => ({ value: item.name, label: item.name })) ?? []} />
            </label>
            <div className="row-actions personality-management-actions">
              <button className="secondary" disabled={Boolean(busy)} onClick={() => {
                setCreateOpen((current) => !current)
                setRenameOpen(false)
                setError('')
                setNotice('')
              }}>{createOpen ? text.personality.cancelNew : text.personality.newPersonality}</button>
              <button className="secondary" disabled={!personality || personality.is_builtin || Boolean(busy)} onClick={() => {
                setRenameOpen((current) => !current)
                setRenameName(selected)
                setCreateOpen(false)
                setError('')
                setNotice('')
              }}>{renameOpen ? text.personality.cancelRename : text.personality.rename}</button>
              <button className="ghost destructive" disabled={!personality || personality.is_builtin || Boolean(busy)} onClick={() => void deletePersonality()}>{common.delete}</button>
            </div>
          </div>
          {createOpen && (
            <div className="personality-inline-form">
              <div className="section-heading">
                <div>
                  <h3>{text.personality.newPersonality}</h3>
                  <p className="section-copy">{text.personality.newHint}</p>
                </div>
              </div>
              <div className="personality-inline-fields">
                <label className="form-field">
                  {text.personality.name}
                  <input
                    value={createName}
                    maxLength={64}
                    placeholder={text.personality.namePlaceholder}
                    onChange={(event) => { setCreateName(event.target.value); setError(''); setNotice('') }}
                  />
                </label>
                <label className="form-field">
                  {text.personality.prompt}
                  <textarea
                    value={createPrompt}
                    maxLength={50000}
                    onChange={(event) => { setCreatePrompt(event.target.value); setError(''); setNotice('') }}
                  />
                </label>
              </div>
              <div className="row-actions">
                <button className="primary" disabled={Boolean(busy)} onClick={() => void createPersonality()}>{text.personality.create}</button>
              </div>
            </div>
          )}
          {renameOpen && personality && !personality.is_builtin && (
            <div className="personality-rename-form">
              <label className="form-field">
                {text.personality.newName}
                <input
                  value={renameName}
                  maxLength={64}
                  onChange={(event) => { setRenameName(event.target.value); setError(''); setNotice('') }}
                />
              </label>
              <div className="row-actions">
                <button className="primary" disabled={Boolean(busy)} onClick={() => void renamePersonality()}>{text.personality.rename}</button>
              </div>
            </div>
          )}
          {!createOpen && <>
          <p className="setting-effect">{rich(text.personality.editing, { selected: <strong>{selected}</strong>, active: <strong>{data?.active_personality || text.playgroundChoice.theActivePersonality}</strong> })}</p>
          <p className="setting-effect">{dirty ? text.personality.unsavedDraft : personality?.prompt_saved ? text.personality.promptSaved : text.personality.promptRuntime}</p>
          <label className="form-field">
            {text.personality.editablePrompt}
            <textarea
              data-editor-focus
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
          </>}
        </>
      )}
    </AIBehaviorSection>
  )

  const profileEditor = (
    <AIBehaviorSection
      id="ai-profile-instructions"
      title={text.profile.title}
      helpLabel={text.profile.helpLabel}
      description={text.profile.help}
      badges={(
        <span className="personality-badges">
          {data?.profile_instructions_saved && <span className="mini-badge saved-badge">{text.profile.saved}</span>}
          {data && !data.profile_instructions_saved && <span className="mini-badge runtime-badge">{text.personality.runtimeOnly}</span>}
          {profileDirty && <span className="mini-badge dirty-badge">{text.personality.edited}</span>}
        </span>
      )}
      className="profile-instructions-editor"
      footer={playgroundChoice('profile') ?? (
        <div className="editor-footer ai-editor-footer">
          <div className="ai-editor-leading">
            {playgroundButton('profile', profileDirty || !Boolean(data?.profile_instructions_saved))}
            <span className="muted">{fmt(text.personality.characters, { count: number(profileValue.length), max: number(50000) })}</span>
          </div>
          <div className="row-actions">
            <button className="secondary" disabled={!data || Boolean(busy) || !profileDirty} onClick={() => void runProfileAction('apply')}>{busy === 'profile:apply' ? text.profile.applying : text.profile.apply}</button>
            <button className="primary" disabled={!data || Boolean(busy) || (!profileDirty && Boolean(data.profile_instructions_saved))} onClick={() => void runProfileAction('save')}>{busy === 'profile:save' ? common.saving : common.save}</button>
            <button className="ghost" disabled={!data || Boolean(busy) || !profileCanReset} onClick={() => void runProfileAction('reset')}>{busy === 'profile:reset' ? text.personality.resetting : text.personality.reset}</button>
          </div>
        </div>
      )}
    >
      <p className="setting-effect">{data?.profile_instructions_saved ? text.profile.savedEffect : text.profile.runtimeEffect} {profileDirty && text.profile.draftEffect}</p>
      <label className="form-field">
        {text.profile.field}
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
    </AIBehaviorSection>
  )

  const languageEditor = (
    <AIBehaviorSection
      id="ai-language"
      title={text.language.title}
      helpLabel={text.language.helpLabel}
      description={<ul>{text.language.help.map((item) => <li key={item}>{item}</li>)}</ul>}
      badges={(
        <span className="personality-badges">
          {languageSaved && <span className="mini-badge saved-badge">{text.language.savedPolicy}</span>}
          {languageDirty && <span className="mini-badge dirty-badge">{text.personality.edited}</span>}
        </span>
      )}
      className="ai-language-card"
      footer={languageDraft && languageSaved && (
        playgroundChoice('language') ?? (
          <div className="editor-footer ai-editor-footer">
            {languageDirty && <span className="muted">{text.language.unsavedDraft}</span>}
            <div className="row-actions">
              {playgroundButton('language', languageDirty)}
              <button className="primary" disabled={Boolean(busy) || !languageDirty || Boolean(languageValidation)} onClick={() => void saveLanguageSettings()}>{busy === 'language:save' ? common.saving : text.language.save}</button>
            </div>
          </div>
        )
      )}
    >
      {!languageDraft || !languageSaved ? <p className="muted">{text.language.loading}</p> : (
        <div className="settings-list">
          <div className={`language-policy-status${languageDirty ? ' has-draft' : ''}`}>
            <div>
              <span>{text.language.activePolicy}</span>
              <strong>{languageSettingsLabel(languageSaved, labelFor, text.language, fmt)}</strong>
            </div>
            {languageDirty && <div>
              <span>{text.language.draftConfiguration}</span>
              <strong>{languageSettingsLabel(languageDraft, labelFor, text.language, fmt)}</strong>
            </div>}
          </div>
          <div className="language-fields">
            <label className="form-field">
              <span>{text.language.mode}</span>
              <Select
                aria-label={text.language.mode}
                value={languageDraft.mode}
                disabled={Boolean(busy)}
                onChange={(mode) => updateLanguageDraft({ mode: mode as AILanguageMode })}
                options={[{ value: 'auto', label: text.language.auto }, { value: 'limited', label: text.language.limited }]}
              />
              <small>{text.language.modeHint}</small>
            </label>
            <label className="form-field">
              <span>{text.language.fallback}</span>
              <Select
                aria-label={text.language.fallback}
                value={languageDraft.fallback_language}
                disabled={Boolean(busy) || languageDraft.mode !== 'limited'}
                onChange={(fallback_language) => updateLanguageDraft({ fallback_language })}
                options={languageCatalogue
                  .filter((language) => languageDraft.allowed_languages.includes(language.code)
                    || language.code === languageDraft.fallback_language)
                  .map((language) => ({ value: language.code, label: labelFor(language.code) }))}
              />
              <small>{text.language.fallbackHint}</small>
            </label>
          </div>
          <fieldset className="language-picker" disabled={Boolean(busy) || languageDraft.mode !== 'limited'}>
            <legend>{text.language.allowed}</legend>
            <div className="language-options">
              {languageCatalogue.map((language) => (
                <label className="language-option" key={language.code}>
                  <input
                    type="checkbox"
                    aria-label={labelFor(language.code)}
                    checked={languageDraft.allowed_languages.includes(language.code)}
                    onChange={(event) => updateLanguageDraft({
                      allowed_languages: event.target.checked
                        ? [...languageDraft.allowed_languages, language.code]
                        : languageDraft.allowed_languages.filter((code) => code !== language.code),
                    })}
                  />
                  <span>{labelFor(language.code)}</span>
                  <code>{language.code}</code>
                </label>
              ))}
            </div>
          </fieldset>
          {languageValidation && <p className="language-validation" role="status">{languageValidation}</p>}
        </div>
      )}
    </AIBehaviorSection>
  )

  const behaviorSections = [
    { id: 'personalities', label: text.sections.personalities, edit: text.sections.editPersonalities, body: personalityEditor },
    { id: 'profile', label: text.sections.profile, edit: text.sections.editProfile, body: profileEditor },
    { id: 'shared', label: text.sections.shared, edit: text.sections.editShared, body: <div ref={setInstructionsTarget} className="ai-editor-slot" /> },
    { id: 'languages', label: text.sections.languages, edit: text.sections.editLanguages, body: languageEditor },
  ] satisfies { id: AIBehaviorSectionId; label: string; edit: string; body: ReactNode }[]

  const unavailable = loading ? common.loading : common.unavailable
  const memoryStatus = status ? status.memory_enabled ? common.enabled : common.disabled : unavailable

  return (
    <section className="ai-layout" aria-busy={loading}>
      <FeedbackToast error={behaviorSection ? '' : error} notice={behaviorSection ? '' : notice}
        onDismiss={() => { setError(''); setNotice('') }} />
      <div className="ai-page-status" aria-label={text.page.commandStatus}>
        <p><strong>!ask</strong><span className={status?.enabled ? 'status-good' : ''}>{status ? status.enabled ? common.enabled : common.disabled : unavailable}</span></p>
        <button className="secondary" type="button" onClick={onOpenPlayground}>{text.page.goToPlayground}</button>
      </div>
      <AISetupPanel instructionsTarget={instructionsTarget} discardInstructions={discardVersion}
        onInstructionsDirtyChange={setInstructionsDirty} onInstructionsBusyChange={setInstructionsBusy}
        active={active} onDirtyChange={setSetupDirty}
        onSaved={() => { void refresh().catch(() => setError(text.page.setupSavedRefreshFailed)) }} />
      <article className="card ai-behavior-card" id="ai-behavior">
        <div className="ai-behavior-heading">
          <h2>{text.page.behavior}</h2>
          {behaviorDirty && <span className="mini-badge dirty-badge">{common.unsavedChanges}</span>}
        </div>
        <div className="ai-behavior-overview">
          <div className="ai-behavior-summary">
            <dl className="ai-runtime-values">
              <dt>{text.page.activePersonality}</dt><dd>{data ? data.active_personality || common.notSelected : unavailable}</dd>
              <dt>{text.page.responseLanguage}</dt><dd>{languageSaved ? languageSaved.mode === 'auto' ? text.page.auto : languageSettingsLabel(languageSaved, labelFor, text.language, fmt) : unavailable}</dd>
              <dt>{text.page.conversationMemory}</dt><dd>{memoryStatus}</dd>
              <dt>{text.page.aiCommand}</dt><dd>{status ? status.enabled ? common.enabled : common.disabled : unavailable}</dd>
            </dl>
            {status?.enabled && !status.available && <p className="ai-behavior-status">{text.page.providerUnavailable}</p>}
          </div>
          <div className="ai-behavior-shortcuts">
            {behaviorSections.map(({ id, edit }) => (
              <button key={id} type="button" className="secondary" aria-haspopup="dialog"
                disabled={loading || behaviorBusy} onClick={() => {
                  setError('')
                  setNotice('')
                  setBehaviorSection(id)
                }}>{edit}</button>
            ))}
          </div>
        </div>
      </article>
      <AIMemoryLimits active={active} onDirty={setMemoryDirty} toggle={
          <Switch className="settings-toggle" checked={status?.memory_enabled ?? false} disabled={!status || Boolean(busy)}
            ariaLabel={text.page.enableMemory} onCheckedChange={(enabled) => void changeToggle('memory', enabled)}>
            <span>{memoryStatus}</span>
          </Switch>
        } />
      <AIPlayground active={active} hasDrafts={hasDrafts} />
      {active && behaviorSection && <EditorDialog id="ai-behavior-editor" title={text.page.editBehavior}
        closeLabel={text.page.closeEditor} dirtyLabel={behaviorDirty ? common.unsavedChanges : undefined}
        busy={behaviorBusy} error={error} onClose={closeBehavior} className="ai-behavior-dialog">
        <EditorSections id="ai-behavior-editor" label={text.page.behaviorSections} active={behaviorSection} onSelect={setBehaviorSection}
          sections={behaviorSections} />
        {notice && <p className="ai-behavior-notice" role="status">{notice}</p>}
      </EditorDialog>}
      {confirmDiscard && <Confirmation title={text.page.discardTitle}
        description={text.page.discardDescription} danger
        onConfirm={discardBehavior} onCancel={() => setConfirmDiscard(false)} />}
    </section>
  )
}
