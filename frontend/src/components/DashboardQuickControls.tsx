import { useEffect, useState } from 'react'
import { type AISetupResponse, type AIStatus, waitForBridge } from '../bridge'
import { Select } from './Select'
import { common } from '../i18n/common'
import { dashboard } from '../i18n/dashboard'
import { catalogFor, useCatalog, useI18n } from '../i18n/core'

type Setup = Required<Pick<AISetupResponse, 'settings' | 'providers' | 'capabilities'>>

/** Thin row of everyday controls: personality, main model and a quick bot-side ignore. */
export default function DashboardQuickControls({ aiStatus, onAIStatusChanged, onOpenAISetup, onOpenRestrictions }: {
  aiStatus: AIStatus | null
  onAIStatusChanged: () => Promise<void>
  onOpenAISetup: () => void
  onOpenRestrictions: () => void
}) {
  const text = useCatalog(dashboard).quick
  const commonText = useCatalog(common)
  const { fmt } = useI18n()
  const [setup, setSetup] = useState<Setup | null>(null)
  const [busy, setBusy] = useState('')
  const [modelError, setModelError] = useState('')
  const [personalityError, setPersonalityError] = useState('')
  const [username, setUsername] = useState('')
  const [ignoreNotice, setIgnoreNotice] = useState('')
  const [ignoreError, setIgnoreError] = useState('')

  const loadSetup = async () => {
    const result = await (await waitForBridge()).get_ai_setup()
    if (!result.ok || !result.settings || !result.providers || !result.capabilities) {
      throw new Error(result.error ?? catalogFor(dashboard).quick.modelUnavailable)
    }
    setSetup({ settings: result.settings, providers: result.providers, capabilities: result.capabilities })
  }

  useEffect(() => {
    void loadSetup().catch(() => setSetup(null))
  }, [aiStatus?.model])

  const primary = setup?.settings.primary
  const provider = setup?.providers.find((item) => item.id === primary?.provider)
  const models = provider ? [...new Set([...(primary?.model ? [primary.model] : []), ...provider.models])] : []

  const changePersonality = async (name: string) => {
    setBusy('personality')
    setPersonalityError('')
    try {
      const result = await (await waitForBridge()).set_active_personality(name)
      if (!result.ok) throw new Error(result.error ?? text.personalityFailed)
      await onAIStatusChanged()
    } catch (reason) {
      setPersonalityError(reason instanceof Error ? reason.message : text.personalityFailed)
    } finally {
      setBusy('')
    }
  }

  const changeModel = async (model: string) => {
    if (!setup || !primary) return
    setBusy('model')
    setModelError('')
    // Keep thinking and search only when the new model supports them.
    const capabilities = setup.capabilities[primary.provider]?.[model]
    const thinkingOptions = capabilities?.thinking_options.map((option) => option.value) ?? []
    const thinking = !capabilities?.known || thinkingOptions.includes(primary.thinking)
      ? primary.thinking : thinkingOptions.includes('default') ? 'default' : thinkingOptions[0] ?? primary.thinking
    try {
      const api = await waitForBridge()
      const result = await api.save_ai_setup({ ...setup.settings,
        primary: { ...primary, model, thinking, search: primary.search && Boolean(capabilities?.search_supported ?? true) } })
      if (!result.ok) throw new Error(result.error ?? text.modelFailed)
      await loadSetup()
      await onAIStatusChanged()
    } catch (reason) {
      setModelError(reason instanceof Error ? reason.message : text.modelFailed)
    } finally {
      setBusy('')
    }
  }

  const ignoreUser = async () => {
    const login = username.trim().replace(/^@/, '')
    if (!login || busy) return
    setBusy('ignore')
    setIgnoreError('')
    setIgnoreNotice('')
    try {
      const result = await (await waitForBridge()).save_command_restriction({ username: login, command_ids: [], expires_at: null, note: '' })
      if (!result.ok) throw new Error(result.error ?? text.ignoreFailed)
      setIgnoreNotice(fmt(text.ignored, { name: login.toLowerCase() }))
      setUsername('')
    } catch (reason) {
      setIgnoreError(reason instanceof Error ? reason.message : text.ignoreFailed)
    } finally {
      setBusy('')
    }
  }

  const personalities = aiStatus?.available_personalities ?? []
  return (
    <section className="card dashboard-quick" aria-label={text.label}>
      <div className="dashboard-quick-item">
        <label className="dashboard-label" htmlFor="dashboard-personality">{text.personality}</label>
        <Select id="dashboard-personality" aria-label={text.personality} value={aiStatus?.active_personality ?? ''}
          placeholder={aiStatus ? commonText.notSelected : commonText.loading}
          disabled={!aiStatus || !personalities.length || Boolean(busy)}
          options={personalities.map((name) => ({ value: name, label: name }))}
          onChange={(name) => void changePersonality(name)} />
        {personalityError && <p className="inline-error" role="alert">{personalityError}</p>}
      </div>
      <div className="dashboard-quick-item">
        <label className="dashboard-label" htmlFor="dashboard-model">{text.model}</label>
        <Select id="dashboard-model" aria-label={text.model} value={primary?.model ?? ''} searchable={models.length > 8}
          placeholder={setup ? text.modelNotSelected : commonText.loading}
          disabled={!setup || !models.length || Boolean(busy)}
          options={models.map((model) => ({ value: model, label: model }))}
          onChange={(model) => void changeModel(model)} />
        {modelError && <p className="inline-error" role="alert">{modelError}{' '}
          <button type="button" className="dashboard-link" onClick={onOpenAISetup}>{text.openAISetup}</button></p>}
      </div>
      <form className="dashboard-quick-item dashboard-quick-ignore" onSubmit={(event) => { event.preventDefault(); void ignoreUser() }}>
        <label className="dashboard-label" htmlFor="dashboard-ignore">{text.ignore}</label>
        <div className="dashboard-quick-ignore-row">
          <input id="dashboard-ignore" value={username} placeholder={text.ignorePlaceholder} autoComplete="off" spellCheck={false}
            maxLength={26} disabled={busy === 'ignore'} onChange={(event) => { setUsername(event.target.value); setIgnoreNotice(''); setIgnoreError('') }} />
          <button type="submit" className="secondary" disabled={!username.trim() || Boolean(busy)}>
            {busy === 'ignore' ? commonText.working : text.ignoreAction}
          </button>
        </div>
        {ignoreError && <p className="inline-error" role="alert">{ignoreError}</p>}
        {ignoreNotice && <p className="dashboard-quick-note" role="status">{ignoreNotice}{' '}
          <button type="button" className="dashboard-link" onClick={onOpenRestrictions}>{text.manageIgnored}</button></p>}
      </form>
    </section>
  )
}
