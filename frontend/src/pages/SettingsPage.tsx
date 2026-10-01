import { useEffect, useState } from 'react'

import {
  type AIProviderSettings,
  type AppSettings,
  type CredentialInfo,
  type CredentialName,
  type GeminiModelPreset,
  type TwitchConnectionSettings,
  waitForBridge,
} from '../bridge'
import FeedbackToast from '../components/FeedbackToast'
import Switch from '../components/Switch'

interface SettingsPageProps {
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

export default function SettingsPage({ active }: SettingsPageProps) {
  const [saved, setSaved] = useState<AppSettings | null>(null)
  const [draft, setDraft] = useState<AppSettings | null>(null)
  const [credentials, setCredentials] = useState<CredentialInfo[]>([])
  const [twitchSaved, setTwitchSaved] = useState<TwitchConnectionSettings | null>(null)
  const [twitchDraft, setTwitchDraft] = useState<TwitchConnectionSettings | null>(null)
  const [aiSaved, setAiSaved] = useState<AIProviderSettings | null>(null)
  const [aiDraft, setAiDraft] = useState<AIProviderSettings | null>(null)
  const [discoveredModels, setDiscoveredModels] = useState<string[]>([])
  const [credentialDrafts, setCredentialDrafts] = useState<Record<CredentialName, string>>({
    gemini_api_key: '',
    twitch_client_secret: '',
  })
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!active) {
      return
    }
    let mounted = true
    const load = async () => {
      try {
        const api = await waitForBridge()
        const [response, credentialResponse, twitchResponse, aiResponse] = await Promise.all([
          api.get_app_settings(),
          api.get_credentials(),
          api.get_twitch_settings(),
          api.get_ai_provider_settings(),
        ])
        if (!response.ok || !response.settings) {
          throw new Error(response.error ?? 'Desktop settings are unavailable.')
        }
        if (!credentialResponse.ok || !credentialResponse.credentials) {
          throw new Error(credentialResponse.error ?? 'Credential status is unavailable.')
        }
        if (!twitchResponse.ok || !twitchResponse.settings) {
          throw new Error(twitchResponse.error ?? 'Twitch settings are unavailable.')
        }
        if (!aiResponse.ok || !aiResponse.settings) {
          throw new Error(aiResponse.error ?? 'AI provider settings are unavailable.')
        }
        if (mounted) {
          setDraft(response.settings)
          setSaved(response.settings)
          setCredentials(credentialResponse.credentials)
          setTwitchDraft((current) => {
            const dirty = current && twitchSaved
              && (current.target_channel !== twitchSaved.target_channel
                || current.target_channel_user_id !== twitchSaved.target_channel_user_id)
            return dirty ? current : twitchResponse.settings!
          })
          setTwitchSaved(twitchResponse.settings)
          setAiDraft((current) => {
            const dirty = current && aiSaved
              && (current.selected_model !== aiSaved.selected_model
                || current.fallback_model !== aiSaved.fallback_model)
            return dirty ? current : aiResponse.settings!
          })
          setAiSaved(aiResponse.settings)
          setError('')
        }
      } catch (reason) {
        if (mounted) {
          setError(reason instanceof Error ? reason.message : 'Could not load settings.')
        }
      }
    }
    void load()
    return () => { mounted = false }
  }, [active])

  const updateWindowSettings = async (
    values: Partial<AppSettings>,
    successMessage: string,
  ) => {
    if (!draft) {
      return
    }
    const previous = saved ?? draft
    const updated = { ...draft, ...values }
    setDraft(updated)
    setBusy('settings')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.update_app_settings(
        updated.start_minimized,
        updated.minimize_to_tray,
        updated.close_to_tray,
        updated.auto_start_bot,
      )
      if (!result.ok) {
        throw new Error(result.error ?? 'Desktop settings could not be saved.')
      }
      setSaved(updated)
      setNotice(successMessage)
    } catch (reason) {
      setDraft(previous)
      setError(reason instanceof Error ? reason.message : 'Desktop settings could not be saved.')
    } finally {
      setBusy('')
    }
  }

  const updateTwitchDraft = (values: Partial<TwitchConnectionSettings>) => {
    setTwitchDraft((current) => current ? { ...current, ...values } : current)
    setError('')
    setNotice('')
  }

  const saveTwitch = async (reconnect: boolean) => {
    if (!twitchDraft) {
      return
    }
    const channel = twitchDraft.target_channel.trim().replace(/^#/, '')
    const channelUserId = twitchDraft.target_channel_user_id.trim()
    if (!channel || /\s/.test(channel)) {
      setError('Twitch target channel must be a non-empty login name without spaces.')
      return
    }
    if (!/^\d+$/.test(channelUserId)) {
      setError('Twitch channel user ID must contain digits only.')
      return
    }
    setBusy(reconnect ? 'twitch:reconnect' : 'twitch:save')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const savedResult = await api.update_twitch_settings(channel, channelUserId)
      if (!savedResult.ok) {
        throw new Error(savedResult.error ?? 'Twitch settings could not be saved.')
      }
      if (reconnect) {
        const reconnectResult = await api.reconnect_twitch()
        if (!reconnectResult.ok) {
          throw new Error(reconnectResult.error ?? 'Twitch could not reconnect.')
        }
      }
      const refreshed = await api.get_twitch_settings()
      if (!refreshed.ok || !refreshed.settings) {
        throw new Error(refreshed.error ?? 'Twitch status could not be refreshed.')
      }
      setTwitchSaved(refreshed.settings)
      setTwitchDraft(refreshed.settings)
      setNotice(
        reconnect
          ? refreshed.settings.running
            ? 'Twitch settings saved and the connection was restarted.'
            : 'Twitch settings saved and applied for the next bot start.'
          : savedResult.requires_reconnect
            ? 'Twitch settings saved. Reconnect or restart the application to apply them.'
            : 'Twitch settings saved.',
      )
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Twitch settings could not be saved.')
    } finally {
      setBusy('')
    }
  }

  const runCredentialAction = async (
    name: CredentialName,
    action: 'replace' | 'remove' | 'test',
  ) => {
    if (action === 'remove' && !window.confirm('Remove this securely stored credential?')) {
      return
    }
    setBusy(`${name}:${action}`)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = action === 'replace'
        ? await api.replace_credential(name, credentialDrafts[name])
        : action === 'remove'
          ? await api.remove_credential(name)
          : await api.test_credential(name)
      if (!result.ok) {
        throw new Error(result.error ?? 'Credential operation failed.')
      }
      if (action !== 'test') {
        const response = await api.get_credentials()
        if (!response.ok || !response.credentials) {
          throw new Error(response.error ?? 'Credential status is unavailable.')
        }
        setCredentials(response.credentials)
        setCredentialDrafts((current) => ({ ...current, [name]: '' }))
      }
      setNotice(
        action === 'replace'
          ? 'Credential stored securely. Restart the application to use it.'
          : action === 'remove'
            ? 'Secure credential removed. Restart to apply the remaining fallback state.'
            : 'Credential test passed.',
      )
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Credential operation failed.')
    } finally {
      setBusy('')
    }
  }

  const updateAiDraft = (values: Partial<AIProviderSettings>) => {
    setAiDraft((current) => current ? { ...current, ...values } : current)
    setError('')
    setNotice('')
  }

  const saveAiModels = async () => {
    if (!aiDraft) {
      return
    }
    const selectedModel = aiDraft.selected_model.trim()
    const fallbackModel = aiDraft.fallback_model.trim()
    if (!selectedModel || !fallbackModel) {
      setError('Selected and fallback model IDs are required.')
      return
    }
    if (selectedModel === fallbackModel) {
      setError('Selected and fallback models must be different.')
      return
    }
    setBusy('ai:save')
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
      setAiSaved(refreshed.settings)
      setAiDraft(refreshed.settings)
      setNotice('AI model settings saved and active for the next request.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'AI model settings could not be saved.')
    } finally {
      setBusy('')
    }
  }

  const discoverModels = async () => {
    setBusy('ai:discover')
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

  const twitchDirty = Boolean(
    twitchDraft && twitchSaved
      && (twitchDraft.target_channel !== twitchSaved.target_channel
        || twitchDraft.target_channel_user_id !== twitchSaved.target_channel_user_id),
  )
  const twitchCredential = credentials.find(
    (credential) => credential.name === 'twitch_client_secret',
  )
  const aiDirty = Boolean(
    aiDraft && aiSaved
      && (aiDraft.selected_model !== aiSaved.selected_model
        || aiDraft.fallback_model !== aiSaved.fallback_model),
  )
  const geminiCredential = credentials.find(
    (credential) => credential.name === 'gemini_api_key',
  )
    ?? aiDraft?.credential
    ?? null
  return (
    <div className="settings-layout">
      <FeedbackToast
        error={error}
        notice={notice}
        onDismiss={() => { setError(''); setNotice('') }}
      />
      <section className="card settings-page">
        <div className="section-heading">
          <div>
            <p className="label">DESKTOP APPLICATION</p>
            <h2>Startup, window and tray behavior</h2>
            <p className="section-copy">These settings are local to this computer.</p>
          </div>
          <span className="mini-badge saved-badge">Auto-saved</span>
        </div>
        {!draft ? <p className="muted">Loading desktop settings…</p> : (
          <div className="settings-list">
            <Switch className="settings-option" checked={draft.auto_start_bot} disabled={Boolean(busy)} onCheckedChange={(auto_start_bot) => void updateWindowSettings({ auto_start_bot }, 'Automatic bot startup preference saved for the next launch.')}>
              <span><strong>Start bot automatically</strong><small>Saved automatically. Takes effect on the next application launch and is independent of window visibility.</small></span>
            </Switch>
            <Switch className="settings-option" checked={draft.start_minimized} disabled={Boolean(busy)} onCheckedChange={(start_minimized) => void updateWindowSettings({ start_minimized }, 'Start-minimized preference saved for the next launch.')}>
              <span><strong>Start minimized</strong><small>Saved automatically. Takes effect on the next application launch.</small></span>
            </Switch>
            <Switch className="settings-option" checked={draft.minimize_to_tray} disabled={Boolean(busy)} onCheckedChange={(minimize_to_tray) => void updateWindowSettings({ minimize_to_tray }, 'Minimize-to-tray behavior saved and active.')}>
              <span><strong>Minimize to tray</strong><small>Saved automatically and applies immediately when the window is minimized.</small></span>
            </Switch>
            <Switch className="settings-option" checked={draft.close_to_tray} disabled={Boolean(busy)} onCheckedChange={(close_to_tray) => void updateWindowSettings({ close_to_tray }, 'Close-to-tray behavior saved and active.')}>
              <span><strong>Close to tray</strong><small>Saved automatically and applies immediately when the close button is used.</small></span>
            </Switch>
          </div>
        )}
      </section>

      <section className="card settings-page">
        <div className="section-heading">
          <div>
            <p className="label">AI PROVIDER</p>
            <h2>Google Gemini models</h2>
            <p className="section-copy">Choose a model and an unavailable-model fallback. Custom Gemini model IDs are supported.</p>
          </div>
          {aiDirty && <span className="mini-badge dirty-badge">Edited</span>}
        </div>
        {!aiDraft ? <p className="muted">Loading AI provider settings…</p> : (
          <div className="settings-list">
            <div className="ai-provider-status">
              <div><span>Provider</span><strong>{aiDraft.provider}</strong></div>
              <div><span>Credential</span><strong className={geminiCredential?.configured ? 'status-good' : ''}>{geminiCredential?.configured ? 'Configured' : 'Missing'}</strong></div>
            </div>
            <div className="model-fields">
              <ModelSelector
                label="Selected model"
                value={aiDraft.selected_model}
                presets={aiDraft.presets}
                discoveredModels={discoveredModels}
                onChange={(selected_model) => updateAiDraft({ selected_model })}
                help="Saved model changes apply to the next AI request."
              />
              <ModelSelector
                label="Fallback model"
                value={aiDraft.fallback_model}
                presets={aiDraft.presets}
                discoveredModels={discoveredModels}
                onChange={(fallback_model) => updateAiDraft({ fallback_model })}
                help="Used only when the selected model is unavailable or unsupported."
              />
            </div>
            <div className="settings-actions">
              <button className="secondary" disabled={Boolean(busy) || !geminiCredential?.configured} onClick={() => void runCredentialAction('gemini_api_key', 'test')}>{busy === 'gemini_api_key:test' ? 'Testing…' : 'Test credential'}</button>
              <button className="secondary" disabled={Boolean(busy) || !geminiCredential?.configured} onClick={() => void discoverModels()}>{busy === 'ai:discover' ? 'Discovering…' : 'Discover models'}</button>
              <button className="primary" disabled={Boolean(busy) || !aiDirty} onClick={() => void saveAiModels()}>{busy === 'ai:save' ? 'Saving…' : 'Save models'}</button>
            </div>
            <p className="settings-hint">Provider discovery augments the tracked presets. Authentication, network, policy, and rate-limit failures never trigger model fallback.</p>
          </div>
        )}
      </section>

      <section className="card settings-page">
        <div className="section-heading">
          <div>
            <p className="label">TWITCH CONNECTION</p>
            <h2>Channel and account</h2>
            <p className="section-copy">Channel changes are stored locally. Save and reconnect to apply them to a running bot.</p>
          </div>
          {twitchDirty && <span className="mini-badge dirty-badge">Edited</span>}
        </div>
        {!twitchDraft ? <p className="muted">Loading Twitch settings…</p> : (
          <div className="settings-list">
            <div className="twitch-status-grid">
              <div><span>Connection</span><strong className={twitchDraft.connected ? 'status-good' : ''}>{twitchDraft.connected ? 'Connected' : twitchDraft.running ? 'Connecting / authorization required' : 'Stopped'}</strong></div>
              <div><span>Bot account</span><strong>{twitchDraft.bot_username} ({twitchDraft.bot_user_id})</strong></div>
              <div><span>Active channel</span><strong>{twitchDraft.active_channel}</strong></div>
              <div><span>OAuth token cache</span><strong>{twitchDraft.oauth_token_available ? 'Available' : 'Authorization required'}</strong></div>
              <div><span>Client secret</span><strong>{twitchCredential?.configured ? 'Configured' : 'Missing'}</strong></div>
            </div>
            <label className="form-field">
              Target channel login
              <input value={twitchDraft.target_channel} onChange={(event) => updateTwitchDraft({ target_channel: event.target.value })} placeholder="channel_name" />
              <small>Non-secret. Saved in the local application settings file.</small>
            </label>
            <label className="form-field">
              Target channel user ID
              <input inputMode="numeric" value={twitchDraft.target_channel_user_id} onChange={(event) => updateTwitchDraft({ target_channel_user_id: event.target.value })} placeholder="123456789" />
              <small>The numeric Twitch broadcaster ID used for chat subscriptions and API lookups.</small>
            </label>
            <div className="settings-actions">
              <button className="secondary" disabled={!twitchDirty || Boolean(busy)} onClick={() => void saveTwitch(false)}>{busy === 'twitch:save' ? 'Saving…' : 'Save for later'}</button>
              <button className="primary" disabled={Boolean(busy)} onClick={() => void saveTwitch(true)}>{busy === 'twitch:reconnect' ? 'Reconnecting…' : twitchDraft.running ? 'Save & reconnect' : 'Save & apply'}</button>
            </div>
            <p className="settings-hint">Bot identity and OAuth authorization continue to use the existing startup configuration and Twitch flow. Secure credential changes require an application restart.</p>
          </div>
        )}
      </section>

      <section className="card settings-page">
        <div className="section-heading">
          <div>
            <p className="label">SECURE CREDENTIALS</p>
            <h2>Provider credentials</h2>
            <p className="section-copy">Values are stored in Windows Credential Manager and are never displayed. Secure values override the private .env fallback after restart.</p>
          </div>
        </div>
        <div className="credential-list">
          {credentials.map((credential) => {
            const replacing = busy === `${credential.name}:replace`
            const removing = busy === `${credential.name}:remove`
            const testing = busy === `${credential.name}:test`
            const sourceLabel = credential.source === 'credential_store'
              ? 'Stored securely'
              : credential.source === 'environment'
                ? 'Using .env fallback'
                : 'Not configured'
            return (
              <article className="credential-row" key={credential.name}>
                <div className="credential-heading">
                  <div><strong>{credential.label}</strong><small>{sourceLabel}</small></div>
                  <span className={`state-pill ${credential.configured ? 'enabled' : ''}`}>{credential.configured ? 'Configured' : 'Missing'}</span>
                </div>
                {!credential.secure_storage_available && <p className="credential-warning">Windows credential storage is currently unavailable; the .env fallback remains active.</p>}
                <label className="form-field">
                  Replacement value
                  <input
                    type="password"
                    autoComplete="off"
                    value={credentialDrafts[credential.name]}
                    placeholder={credential.configured ? 'Enter a replacement' : 'Enter credential'}
                    onChange={(event) => {
                      setCredentialDrafts((current) => ({ ...current, [credential.name]: event.target.value }))
                      setError('')
                      setNotice('')
                    }}
                  />
                </label>
                <div className="credential-actions">
                  <button className="primary" disabled={Boolean(busy) || !credentialDrafts[credential.name].trim()} onClick={() => void runCredentialAction(credential.name, 'replace')}>{replacing ? 'Saving…' : 'Replace'}</button>
                  <button className="secondary" disabled={Boolean(busy) || !credential.configured} onClick={() => void runCredentialAction(credential.name, 'test')}>{testing ? 'Testing…' : 'Test'}</button>
                  <button className="danger" disabled={Boolean(busy) || credential.source !== 'credential_store'} onClick={() => void runCredentialAction(credential.name, 'remove')}>{removing ? 'Removing…' : 'Remove secure value'}</button>
                </div>
              </article>
            )
          })}
        </div>
      </section>
    </div>
  )
}
