import { useEffect, useState } from 'react'

import {
  type AppSettings,
  type CredentialInfo,
  type CredentialName,
  type TwitchConnectionSettings,
  waitForBridge,
} from '../bridge'

interface SettingsPageProps {
  active: boolean
}

export default function SettingsPage({ active }: SettingsPageProps) {
  const [saved, setSaved] = useState<AppSettings | null>(null)
  const [draft, setDraft] = useState<AppSettings | null>(null)
  const [credentials, setCredentials] = useState<CredentialInfo[]>([])
  const [twitchSaved, setTwitchSaved] = useState<TwitchConnectionSettings | null>(null)
  const [twitchDraft, setTwitchDraft] = useState<TwitchConnectionSettings | null>(null)
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
          setDraft((current) => {
            const dirty = current && saved && JSON.stringify(current) !== JSON.stringify(saved)
            return dirty ? current : response.settings!
          })
          setSaved(response.settings)
          setCredentials(credentialResponse.credentials)
          setTwitchDraft((current) => {
            const dirty = current && twitchSaved
              && (current.target_channel !== twitchSaved.target_channel
                || current.target_channel_user_id !== twitchSaved.target_channel_user_id)
            return dirty ? current : twitchResponse.settings!
          })
          setTwitchSaved(twitchResponse.settings)
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

  const updateDraft = (values: Partial<AppSettings>) => {
    setDraft((current) => current ? { ...current, ...values } : current)
    setNotice('')
  }

  const save = async () => {
    if (!draft) {
      return
    }
    setBusy('settings')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.update_app_settings(
        draft.start_minimized,
        draft.minimize_to_tray,
        draft.close_to_tray,
      )
      if (!result.ok) {
        throw new Error(result.error ?? 'Desktop settings could not be saved.')
      }
      setSaved(draft)
      setNotice('Desktop settings saved.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Desktop settings could not be saved.')
    } finally {
      setBusy('')
    }
  }

  const updateTwitchDraft = (values: Partial<TwitchConnectionSettings>) => {
    setTwitchDraft((current) => current ? { ...current, ...values } : current)
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

  const dirty = Boolean(
    draft && saved && JSON.stringify(draft) !== JSON.stringify(saved),
  )
  const twitchDirty = Boolean(
    twitchDraft && twitchSaved
      && (twitchDraft.target_channel !== twitchSaved.target_channel
        || twitchDraft.target_channel_user_id !== twitchSaved.target_channel_user_id),
  )
  const twitchCredential = credentials.find(
    (credential) => credential.name === 'twitch_client_secret',
  )

  return (
    <div className="settings-layout">
      <section className="card settings-page">
        <div className="section-heading">
          <div>
            <p className="label">DESKTOP APPLICATION</p>
            <h2>Window and tray behavior</h2>
            <p className="section-copy">These settings are local to this computer.</p>
          </div>
          {dirty && <span className="mini-badge dirty-badge">Edited</span>}
        </div>
        {error && <div className="inline-error">{error}</div>}
        {notice && <div className="inline-success">{notice}</div>}
        {!draft ? <p className="muted">Loading desktop settings…</p> : (
          <div className="settings-list">
            <label className="settings-option">
              <input type="checkbox" checked={draft.start_minimized} onChange={(event) => updateDraft({ start_minimized: event.target.checked })} />
              <span><strong>Start minimized</strong><small>Start with the window hidden and the tray icon available. Takes effect on next launch.</small></span>
            </label>
            <label className="settings-option">
              <input type="checkbox" checked={draft.minimize_to_tray} onChange={(event) => updateDraft({ minimize_to_tray: event.target.checked })} />
              <span><strong>Minimize to tray</strong><small>Hide the window when it is minimized while keeping the bot running.</small></span>
            </label>
            <label className="settings-option">
              <input type="checkbox" checked={draft.close_to_tray} onChange={(event) => updateDraft({ close_to_tray: event.target.checked })} />
              <span><strong>Close to tray</strong><small>Hide the window instead of exiting when the close button is used.</small></span>
            </label>
            <div className="settings-actions">
              <button className="primary" disabled={!dirty || Boolean(busy)} onClick={() => void save()}>{busy === 'settings' ? 'Saving…' : 'Save settings'}</button>
            </div>
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
        {!twitchDraft ? <p className="muted">Loading Twitch settingsâ€¦</p> : (
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
              <button className="secondary" disabled={!twitchDirty || Boolean(busy)} onClick={() => void saveTwitch(false)}>{busy === 'twitch:save' ? 'Savingâ€¦' : 'Save for later'}</button>
              <button className="primary" disabled={Boolean(busy)} onClick={() => void saveTwitch(true)}>{busy === 'twitch:reconnect' ? 'Reconnectingâ€¦' : twitchDraft.running ? 'Save & reconnect' : 'Save & apply'}</button>
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
                    onChange={(event) => setCredentialDrafts((current) => ({ ...current, [credential.name]: event.target.value }))}
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
