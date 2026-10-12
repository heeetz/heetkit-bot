import { useEffect, useState } from 'react'

import {
  type AppSettings,
  type AppStatus,
  type CredentialInfo,
  type CredentialName,
  type TwitchConnectionSettings,
  twitchAuthorizationLabel,
  twitchConnectionLabel,
  waitForBridge,
} from '../bridge'
import FeedbackToast from '../components/FeedbackToast'
import Switch from '../components/Switch'
import Accordion from '../components/Accordion'

interface SettingsPageProps {
  active: boolean
  status: AppStatus | null
  onReturnToAI?: () => void
}

export default function SettingsPage({ active, status, onReturnToAI }: SettingsPageProps) {
  const [saved, setSaved] = useState<AppSettings | null>(null)
  const [draft, setDraft] = useState<AppSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [credentials, setCredentials] = useState<CredentialInfo[]>([])
  const [twitchSaved, setTwitchSaved] = useState<TwitchConnectionSettings | null>(null)
  const [twitchDraft, setTwitchDraft] = useState<TwitchConnectionSettings | null>(null)
  const [presetName, setPresetName] = useState('')
  const [credentialDrafts, setCredentialDrafts] = useState<Record<CredentialName, string>>({
    gemini_api_key: '',
    twitch_client_secret: '',
  })
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [profilePath, setProfilePath] = useState('')
  const [profileError, setProfileError] = useState('')

  useEffect(() => {
    if (!active) return
    let mounted = true
    const loadProfile = async () => {
      try {
        const api = await waitForBridge()
        const profile = await api.get_profile_info()
        if (!profile.path) throw new Error('The profile location is unavailable.')
        if (mounted) {
          setProfilePath(profile.path)
          setProfileError('')
        }
      } catch (reason) {
        if (mounted) {
          setProfilePath('')
          setProfileError(reason instanceof Error ? reason.message : 'Could not load the profile location.')
        }
      }
    }
    void loadProfile()
    return () => { mounted = false }
  }, [active])

  useEffect(() => {
    if (!active) {
      return
    }
    let mounted = true
    setLoading(true)
    const load = async () => {
      try {
        const api = await waitForBridge()
        const [response, credentialResponse, twitchResponse] = await Promise.all([
          api.get_app_settings(),
          api.get_credentials(),
          api.get_twitch_settings(),
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
        if (mounted) {
          setDraft(response.settings)
          setSaved(response.settings)
          setCredentials(credentialResponse.credentials)
          setTwitchDraft((current) => {
            const dirty = current && twitchSaved
              && (current.target_channel !== twitchSaved.target_channel
                || current.target_channel_user_id !== twitchSaved.target_channel_user_id
                || current.client_id !== twitchSaved.client_id
                || current.bot_username !== twitchSaved.bot_username
                || current.bot_user_id !== twitchSaved.bot_user_id)
            return dirty ? current : twitchResponse.settings!
          })
          setTwitchSaved(twitchResponse.settings)
          const selectedPreset = twitchResponse.settings.presets.find(
            (preset) => preset.id === twitchResponse.settings!.selected_preset_id,
          )
          setPresetName(selectedPreset?.display_name ?? '')
          setError('')
        }
      } catch (reason) {
        if (mounted) {
          setError(reason instanceof Error ? reason.message : 'Could not load settings.')
        }
      } finally {
        if (mounted) setLoading(false)
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

  const openTwitchLink = async (destination: 'twitch_developer_console' | 'twitch_authorization') => {
    setBusy(`external:${destination}`)
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.open_external_link(destination)
      if (!result.ok) {
        throw new Error(result.error ?? 'Could not open the Twitch page.')
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not open the Twitch page.')
    } finally {
      setBusy('')
    }
  }

  const copyText = async (value: string, successMessage: string, failureMessage: string) => {
    setError('')
    setNotice('')
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value)
      } else {
        const previousFocus = document.activeElement
        const input = document.createElement('textarea')
        input.value = value
        input.setAttribute('readonly', '')
        input.style.position = 'fixed'
        input.style.opacity = '0'
        document.body.appendChild(input)
        try {
          input.select()
          if (!document.execCommand('copy')) {
            throw new Error('Clipboard access is unavailable.')
          }
        } finally {
          input.remove()
          if (previousFocus instanceof HTMLElement) {
            previousFocus.focus()
          }
        }
      }
      setNotice(successMessage)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : failureMessage)
    }
  }

  const openProfileFolder = async () => {
    setBusy('profile:open')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.open_profile_folder()
      if (!result.ok) throw new Error(result.error ?? 'Could not open the profile folder.')
      setNotice('Profile folder opened.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not open the profile folder.')
    } finally {
      setBusy('')
    }
  }

  const selectTwitchPreset = (presetId: string) => {
    if (!twitchDraft) {
      return
    }
    if (!presetId) {
      updateTwitchDraft({ selected_preset_id: null })
      setPresetName('')
      return
    }
    const preset = twitchDraft.presets.find((item) => item.id === presetId)
    if (!preset) {
      setError('The selected saved channel is no longer available.')
      return
    }
    updateTwitchDraft({
      selected_preset_id: preset.id,
      target_channel: preset.target_channel,
      target_channel_user_id: preset.target_channel_user_id,
    })
    setPresetName(preset.display_name)
    setNotice('Saved channel selected. Save for later, or use Save & reconnect while running / Save & apply while stopped.')
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
      const selectedPreset = twitchDraft.presets.find(
        (preset) => preset.id === twitchDraft.selected_preset_id,
      )
      const selectedPresetId = selectedPreset
        && selectedPreset.target_channel === channel.toLowerCase()
        && selectedPreset.target_channel_user_id === channelUserId
        ? selectedPreset.id
        : null
      const savedResult = await api.update_twitch_settings(
        channel,
        channelUserId,
        selectedPresetId,
        twitchDraft.client_id,
        twitchDraft.bot_username,
        twitchDraft.bot_user_id,
      )
      if (!savedResult.ok) {
        throw new Error(savedResult.error ?? 'Twitch settings could not be saved.')
      }
      if (reconnect && !savedResult.requires_restart) {
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
      const refreshedPreset = refreshed.settings.presets.find(
        (preset) => preset.id === refreshed.settings!.selected_preset_id,
      )
      setPresetName(refreshedPreset?.display_name ?? '')
      setNotice(
        savedResult.requires_restart
          ? 'Twitch setup saved. Restart the application to apply the client ID, bot identity or secret, then Start Bot and authorize Twitch if prompted.'
          : reconnect
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

  const saveTwitchPreset = async () => {
    if (!twitchDraft) {
      return
    }
    const name = presetName.trim()
    if (!name) {
      setError('Saved channel name must not be empty.')
      return
    }
    setBusy('twitch:preset-save')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.save_twitch_preset(
        twitchDraft.selected_preset_id,
        name,
        twitchDraft.target_channel,
        twitchDraft.target_channel_user_id,
      )
      if (!result.ok) {
        throw new Error(result.error ?? 'Saved channel could not be saved.')
      }
      const refreshed = await api.get_twitch_settings()
      if (!refreshed.ok || !refreshed.settings) {
        throw new Error(refreshed.error ?? 'Twitch settings could not be refreshed.')
      }
      setTwitchSaved(refreshed.settings)
      const refreshedPreset = refreshed.settings.presets.find(
        (preset) => preset.id === result.preset_id,
      )
      setTwitchDraft({ ...refreshed.settings, client_id: twitchDraft.client_id,
        bot_username: twitchDraft.bot_username, bot_user_id: twitchDraft.bot_user_id })
      setPresetName(refreshedPreset?.display_name ?? name)
      setNotice(
        refreshed.settings.requires_restart
          ? 'Channel saved. Restart the application to apply pending Twitch setup before connecting.'
          : result.requires_reconnect
          ? refreshed.settings.running
            ? 'Channel saved. Use Save & reconnect to switch the running bot.'
            : 'Channel saved. Use Save & apply to use this target on the next bot start.'
          : 'Channel saved and selected.',
      )
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Saved channel could not be saved.')
    } finally {
      setBusy('')
    }
  }

  const deleteTwitchPreset = async () => {
    if (!twitchDraft?.selected_preset_id) {
      return
    }
    if (!window.confirm('Delete this saved channel? The active connection will not be changed.')) {
      return
    }
    setBusy('twitch:preset-delete')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.delete_twitch_preset(twitchDraft.selected_preset_id)
      if (!result.ok) {
        throw new Error(result.error ?? 'Saved channel could not be deleted.')
      }
      const refreshed = await api.get_twitch_settings()
      if (!refreshed.ok || !refreshed.settings) {
        throw new Error(refreshed.error ?? 'Twitch settings could not be refreshed.')
      }
      setTwitchSaved(refreshed.settings)
      setPresetName('')
      setNotice('Saved channel deleted. The target channel was left unchanged.')
      setTwitchDraft({ ...refreshed.settings, client_id: twitchDraft.client_id,
        bot_username: twitchDraft.bot_username, bot_user_id: twitchDraft.bot_user_id })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Saved channel could not be deleted.')
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
        if (name === 'twitch_client_secret') {
          const twitchResponse = await api.get_twitch_settings()
          if (!twitchResponse.ok || !twitchResponse.settings) {
            throw new Error(twitchResponse.error ?? 'Twitch restart status is unavailable.')
          }
          setTwitchSaved(twitchResponse.settings)
          setTwitchDraft((current) => current
            ? { ...current, requires_restart: twitchResponse.settings!.requires_restart }
            : twitchResponse.settings!)
        }
      }
      setNotice(
        action === 'replace'
          ? name === 'gemini_api_key' ? 'Gemini credential stored securely and applied to AI features.' : 'Credential stored securely. Restart the application to use it.'
          : action === 'remove'
            ? name === 'gemini_api_key' ? 'Gemini secure value removed. Any configured fallback now applies.' : 'Secure credential removed. Restart to apply the remaining fallback state.'
            : 'Credential test passed.',
      )
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Credential operation failed.')
    } finally {
      setBusy('')
    }
  }

  const twitchDirty = Boolean(
    twitchDraft && twitchSaved
      && (twitchDraft.target_channel !== twitchSaved.target_channel
        || twitchDraft.target_channel_user_id !== twitchSaved.target_channel_user_id
        || twitchDraft.client_id !== twitchSaved.client_id
        || twitchDraft.bot_username !== twitchSaved.bot_username
        || twitchDraft.bot_user_id !== twitchSaved.bot_user_id
        || twitchDraft.selected_preset_id !== twitchSaved.selected_preset_id),
  )
  const activePreset = twitchDraft?.presets.find(
    (preset) => preset.id === twitchDraft.active_preset_id,
  )
  const draftRequiresReconnect = Boolean(
    twitchDraft
      && (twitchDraft.target_channel.trim().toLowerCase().replace(/^#/, '')
        !== twitchDraft.active_channel.toLowerCase()
        || twitchDraft.target_channel_user_id.trim()
        !== twitchDraft.active_channel_user_id),
  )
  const twitchCredential = credentials.find(
    (credential) => credential.name === 'twitch_client_secret',
  )
  const twitchTargetMissing = Boolean(
    twitchDraft
      && (!twitchDraft.target_channel.trim() || !twitchDraft.target_channel_user_id.trim()
        || !twitchDraft.client_id.trim() || !twitchDraft.bot_username.trim() || !twitchDraft.bot_user_id.trim()),
  )
  const geminiCredential = credentials.find(
    (credential) => credential.name === 'gemini_api_key',
  )
  const twitchAuthorizationStatus = status
    ? twitchAuthorizationLabel(status.twitch_connection_state, twitchDraft?.oauth_token_available ?? false)
    : twitchDraft
      ? twitchAuthorizationLabel(
          twitchDraft.connected ? 'connected' : twitchDraft.running ? 'connecting' : 'stopped',
          twitchDraft.oauth_token_available,
        )
      : 'Not verified'

  const renderCredentialRow = (
    credential: CredentialInfo | undefined,
    absentActionLabel: string,
    presentActionLabel: string,
  ) => {
    if (!credential) {
      return (
        <div className="empty-state-inline">
          <strong>Credential status is unavailable</strong>
          <p>Check Logs for details.</p>
        </div>
      )
    }
    const replacing = busy === `${credential.name}:replace`
    const removing = busy === `${credential.name}:remove`
    const testing = busy === `${credential.name}:test`
    const sourceLabel = credential.source === 'credential_store'
      ? 'Stored securely'
      : credential.source === 'environment'
        ? 'Using process environment'
        : 'Not configured'
    return (
      <article className="credential-row" key={credential.name}>
        <div className="credential-heading">
          <div><strong>{credential.label}</strong><small>{sourceLabel}</small></div>
          <span className={`state-pill ${credential.configured ? 'enabled' : ''}`}>{credential.configured ? 'Configured' : 'Missing'}</span>
        </div>
        {!credential.secure_storage_available && <p className="credential-warning">OS keyring storage is unavailable; an advanced process environment fallback is active when configured.</p>}
        <label className="form-field">
          {credential.configured ? 'Replacement value' : 'New value'}
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
          <button className="primary" disabled={Boolean(busy) || !credentialDrafts[credential.name].trim()} onClick={() => void runCredentialAction(credential.name, 'replace')}>
            {replacing ? 'Saving…' : credential.configured ? presentActionLabel : absentActionLabel}
          </button>
          <button className="secondary" disabled={Boolean(busy) || !credential.configured} onClick={() => void runCredentialAction(credential.name, 'test')}>{testing ? 'Testing…' : credential.name === 'gemini_api_key' ? 'Test credential' : 'Test'}</button>
          <button className="danger" disabled={Boolean(busy) || credential.source !== 'credential_store'} onClick={() => void runCredentialAction(credential.name, 'remove')}>{removing ? 'Removing…' : 'Remove secure value'}</button>
        </div>
      </article>
    )
  }

  return (
    <div className="settings-layout" aria-busy={loading}>
      <FeedbackToast
        error={error}
        notice={notice}
        onDismiss={() => { setError(''); setNotice('') }}
      />
      <Accordion
        id="twitch-settings"
        eyebrow="TWITCH CONNECTION"
        title="Application, account and channel"
        description="Complete the initial Twitch setup here, then use saved channels when you need to switch targets."
        badges={twitchDirty && <span className="mini-badge dirty-badge">Edited</span>}
        className="settings-page"
      >
        {!twitchDraft ? <p className="muted">Loading Twitch settings…</p> : (
          <div className="settings-list twitch-settings-list">
            <section className="twitch-settings-group" aria-labelledby="twitch-application-heading">
              <h3 id="twitch-application-heading">Twitch application</h3>
              {(twitchTargetMissing || !twitchCredential?.configured) && (
                <div className="setup-callout">
                  <div>
                    <strong>Complete Twitch setup</strong>
                    <p>Create a Twitch Developer Application and register the callback URL below. Save the non-secret application, bot and target settings and add the Client Secret. Then restart the application, select Start Bot, and authorize the configured bot account when prompted.</p>
                  </div>
                </div>
              )}
              <p className="settings-hint">Before saving, note that Client ID, bot identity or Client Secret changes require an application restart. Target channel changes require reconnect.</p>
              <div className="twitch-application-setup">
                <label className="form-field">
                  Twitch application client ID
                  <input value={twitchDraft.client_id} onChange={(event) => updateTwitchDraft({ client_id: event.target.value })} placeholder="Client ID from the Twitch Developer Console" />
                  <small>From your Twitch Developer Application.</small>
                </label>
                <button className="secondary" disabled={Boolean(busy)} onClick={() => void openTwitchLink('twitch_developer_console')}>Open Twitch Developer Console</button>
                <div className="oauth-callback">
                  <span>Register this OAuth callback URL in your application:</span>
                  <div>
                    <code>{twitchDraft.oauth_callback_url}</code>
                    <button className="ghost" aria-label="Copy OAuth callback URL" onClick={() => void copyText(twitchDraft.oauth_callback_url, 'OAuth callback URL copied.', 'Could not copy the callback URL.')}>Copy</button>
                  </div>
                </div>
                <div className="credential-list">
                  {renderCredentialRow(twitchCredential, 'Add secret', 'Replace secret')}
                </div>
              </div>
            </section>
            <section className="twitch-settings-group" aria-labelledby="twitch-bot-heading">
              <h3 id="twitch-bot-heading">Bot account</h3>
              <div className="twitch-field-pair">
                <label className="form-field">
                  <span>Bot account login</span>
                  <input value={twitchDraft.bot_username} onChange={(event) => updateTwitchDraft({ bot_username: event.target.value })} placeholder="bot_name" />
                  <small>The account you will authorize in Twitch.</small>
                </label>
                <label className="form-field">
                  <span>Bot account user ID</span>
                  <input inputMode="numeric" value={twitchDraft.bot_user_id} onChange={(event) => updateTwitchDraft({ bot_user_id: event.target.value })} placeholder="123456789" />
                  <small>The numeric Twitch ID for the bot login.</small>
                </label>
              </div>
            </section>
            <section className="twitch-settings-group" aria-labelledby="twitch-target-heading">
              <h3 id="twitch-target-heading">Target channel</h3>
              <div className="twitch-field-pair">
                <label className="form-field">
                  <span>Target channel login</span>
                  <input value={twitchDraft.target_channel} onChange={(event) => updateTwitchDraft({ target_channel: event.target.value })} placeholder="channel_name" />
                  <small>Non-secret. Saved on this computer.</small>
                </label>
                <label className="form-field">
                  <span>Target channel user ID</span>
                  <input inputMode="numeric" value={twitchDraft.target_channel_user_id} onChange={(event) => updateTwitchDraft({ target_channel_user_id: event.target.value })} placeholder="123456789" />
                  <small>The numeric Twitch broadcaster ID used for chat subscriptions and API lookups.</small>
                </label>
              </div>
            </section>
            <section className="twitch-settings-group" aria-labelledby="twitch-preset-heading">
              <h3 id="twitch-preset-heading">Saved channels</h3>
              <p className="settings-hint">Saved channels share the bot account and Twitch authorization above. Use them to switch channels after initial setup: Save &amp; reconnect while running, or Save &amp; apply while stopped.</p>
              <div className="preset-editor twitch-field-pair">
                <label className="form-field">
                  <span>Saved channel</span>
                  <select value={twitchDraft.selected_preset_id ?? ''} onChange={(event) => selectTwitchPreset(event.target.value)} disabled={Boolean(busy)}>
                    <option value="">Unsaved target</option>
                    {twitchDraft.presets.map((preset) => (
                      <option value={preset.id} key={preset.id}>
                        {preset.display_name}{preset.id === twitchDraft.active_preset_id ? ' (active)' : ''}
                      </option>
                    ))}
                  </select>
                  <small>Only target-channel details are stored. Credentials and OAuth tokens stay shared.</small>
                </label>
                <label className="form-field">
                  <span>Saved channel name</span>
                  <input value={presetName} onChange={(event) => { setPresetName(event.target.value); setError(''); setNotice('') }} placeholder="Personal test" disabled={Boolean(busy)} />
                </label>
                <div className="preset-actions">
                  <button className="secondary" disabled={Boolean(busy) || !presetName.trim()} onClick={() => void saveTwitchPreset()}>{busy === 'twitch:preset-save' ? 'Saving...' : twitchDraft.selected_preset_id ? 'Update saved channel' : 'Save channel'}</button>
                  <button className="ghost" disabled={Boolean(busy) || !twitchDraft.selected_preset_id} onClick={() => void deleteTwitchPreset()}>{busy === 'twitch:preset-delete' ? 'Deleting...' : 'Delete saved channel'}</button>
                </div>
              </div>
            </section>
            <section className="twitch-settings-group" aria-labelledby="twitch-actions-heading">
              <h3 id="twitch-actions-heading">Authorization, status and save</h3>
              <div className="twitch-status-grid">
                <div><span>Connection</span><strong className={status?.twitch_connected ? 'status-good' : ''}>{status ? twitchConnectionLabel(status.twitch_connection_state) : twitchDraft.connected ? 'Connected' : twitchDraft.running ? 'Connecting' : 'Stopped'}</strong></div>
                <div><span>Active bot account</span><strong>{status?.account || 'Not configured'}</strong></div>
                <div><span>Active target</span><strong>{activePreset ? `${activePreset.display_name} (${twitchDraft.active_channel})` : twitchDraft.active_channel || 'Not configured'}</strong></div>
                <div><span>Twitch authorization</span><strong>{twitchAuthorizationStatus}</strong></div>
                <div><span>Client secret</span><strong>{twitchCredential?.configured ? 'Configured' : 'Missing'}</strong></div>
              </div>
              {twitchDraft.requires_restart && <p className="settings-hint">A saved Client ID, bot identity or Client Secret change is pending. Restart the application before connecting.</p>}
              {(status?.twitch_connection_state === 'auth_required' || (!twitchTargetMissing && !twitchDraft.requires_restart && twitchCredential?.configured && !twitchDraft.oauth_token_available && !status?.twitch_connected)) && (
                <div className="setup-callout">
                  <div>
                    <strong>Twitch authorization required</strong>
                    <p>{twitchDraft.requires_restart
                      ? 'Restart the application to apply pending Twitch setup before starting and authorizing the bot.'
                      : status?.running && status.twitch_connection_state === 'auth_required'
                      ? 'Authorize Twitch opens in your browser. Sign in as the configured bot account.'
                      : 'Start Bot from Dashboard, then choose Authorize Twitch here or on Dashboard. Sign in as the configured bot account.'}</p>
                  </div>
                  {status?.twitch_connection_state === 'auth_required' && (
                    <button className="primary" disabled={Boolean(busy) || !status.running || twitchDraft.requires_restart} onClick={() => void openTwitchLink('twitch_authorization')}>
                      {busy === 'external:twitch_authorization' ? 'Opening…' : 'Authorize Twitch'}
                    </button>
                  )}
                </div>
              )}
              <div className="settings-actions">
                <button className="secondary" disabled={!twitchDirty || Boolean(busy)} onClick={() => void saveTwitch(false)}>{busy === 'twitch:save' ? 'Saving…' : 'Save for later'}</button>
                <button className="primary" disabled={Boolean(busy)} onClick={() => void saveTwitch(true)}>{busy === 'twitch:reconnect' ? 'Saving…' : twitchDraft.requires_restart ? 'Save (restart required)' : twitchDraft.running ? 'Save & reconnect' : 'Save & apply'}</button>
              </div>
              <p className="settings-hint">{twitchDraft.requires_restart
                ? 'Pending Twitch setup requires an application restart before connecting.'
                : draftRequiresReconnect
                  ? twitchDraft.running
                    ? 'The selected target differs from the active connection. Use Save & reconnect to switch.'
                    : 'The selected target differs from the applied target. Use Save & apply for the next bot start.'
                  : 'This target matches the applied target.'} Saved channels reuse the configured bot identity and authorization.</p>
            </section>
          </div>
        )}
      </Accordion>

      <Accordion
        id="credential-settings"
        eyebrow="OPTIONAL AI"
        title="Gemini API key"
        description="The key is stored in the system keyring and is never displayed. Gemini is optional and key changes apply immediately."
        className="settings-page"
      >
        {!draft ? <p className="muted">Loading credential status…</p> : (
          <div className="credential-list">
            {renderCredentialRow(geminiCredential, 'Add key', 'Replace key')}
            <p className="setting-effect">Test credential validates the stored key without generating a reply. Use AI Playground separately to test real generation with your saved settings and applied instructions.</p>
            {onReturnToAI && <div className="row-actions"><button className="secondary" onClick={onReturnToAI}>Return to AI Playground</button></div>}
          </div>
        )}
      </Accordion>

      <section className="card settings-page" id="desktop-settings">
        <div className="section-heading">
          <div>
            <p className="label">DESKTOP BEHAVIOR</p>
            <h2>Startup, window and tray behavior</h2>
            <p className="section-copy">These settings are local to this computer.</p>
          </div>
          <span className="mini-badge saved-badge">Auto-saved</span>
        </div>
        {!draft ? <p className="muted">Loading desktop settings…</p> : (
          <div className="settings-list desktop-settings-list">
            <Switch className="settings-option" checked={draft.auto_start_bot} disabled={Boolean(busy)} onCheckedChange={(auto_start_bot) => void updateWindowSettings({ auto_start_bot }, 'Automatic bot startup preference saved for the next launch.')}>
              <span><strong>Start bot automatically</strong><small>Saved automatically. Takes effect on the next application launch and is independent of window visibility.</small></span>
            </Switch>
            <Switch className="settings-option" checked={draft.start_minimized} disabled={Boolean(busy) || !draft.tray_available} onCheckedChange={(start_minimized) => void updateWindowSettings({ start_minimized }, 'Start-minimized preference saved for the next launch.')}>
              <span><strong>Start minimized</strong><small>{draft.tray_available ? 'Saved automatically. Takes effect on the next application launch.' : 'Available when the Windows system tray is supported.'}</small></span>
            </Switch>
            <Switch className="settings-option" checked={draft.minimize_to_tray} disabled={Boolean(busy) || !draft.tray_available} onCheckedChange={(minimize_to_tray) => void updateWindowSettings({ minimize_to_tray }, 'Minimize-to-tray behavior saved and active.')}>
              <span><strong>Minimize to tray</strong><small>{draft.tray_available ? 'Saved automatically and applies immediately when the window is minimized.' : 'Available when the Windows system tray is supported.'}</small></span>
            </Switch>
            <Switch className="settings-option" checked={draft.close_to_tray} disabled={Boolean(busy) || !draft.tray_available} onCheckedChange={(close_to_tray) => void updateWindowSettings({ close_to_tray }, 'Close-to-tray behavior saved and active.')}>
              <span><strong>Close to tray</strong><small>{draft.tray_available ? 'Saved automatically and applies immediately when the close button is used.' : 'Available when the Windows system tray is supported.'}</small></span>
            </Switch>
          </div>
        )}
      </section>

      <section className="card settings-page" id="profile-location-settings" aria-labelledby="profile-location-heading">
        <div className="section-heading">
          <div>
            <h2 id="profile-location-heading">Data &amp; diagnostics</h2>
            <p className="section-copy">This folder may contain private authentication and application data. Do not share it.</p>
          </div>
        </div>
        <div className="profile-location">
          <span className="label">CURRENT PROFILE FOLDER</span>
          {profileError ? <p className="credential-warning" role="alert">{profileError}</p>
            : profilePath ? <code>{profilePath}</code> : <p className="muted">Loading profile location…</p>}
          <div className="profile-location-actions">
            <button className="secondary" disabled={!profilePath || Boolean(busy)} onClick={() => void openProfileFolder()}>{busy === 'profile:open' ? 'Opening…' : 'Open profile folder'}</button>
            <button className="ghost" disabled={!profilePath || Boolean(busy)} onClick={() => void copyText(profilePath, 'Profile path copied.', 'Could not copy the profile path.')}>Copy path</button>
          </div>
        </div>
      </section>
    </div>
  )
}
