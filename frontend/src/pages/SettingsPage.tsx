import { InterfaceLanguageSettings } from '../components/LanguageSwitcher'
import { useEffect, useRef, useState } from 'react'

import {
  type AppSettings,
  type AppStatus,
  type CredentialInfo,
  type TwitchConnectionSettings,
  getBrowserSetup,
  isBrowserMode,
  twitchAuthorizationLabel,
  twitchConnectionLabel,
  waitForBridge,
} from '../bridge'
import FeedbackToast from '../components/FeedbackToast'
import Switch from '../components/Switch'
import Accordion from '../components/Accordion'
import ConfigurationTransfer from '../components/ConfigurationTransfer'
import { Select } from '../components/Select'
import HelpTip from '../components/HelpTip'
import TwitchSecretField from '../components/TwitchSecretField'
import TwitchSetupInstructions from '../components/TwitchSetupInstructions'
import { restartDesktop, useRestartDraft } from '../desktopRestart'
import '../components/settings-layout.css'
import { common as commonText } from '../i18n/common'
import { catalogFor, useCatalog, useI18n } from '../i18n/core'
import { settingsText } from '../i18n/settings'

interface SettingsPageProps {
  active: boolean
  status: AppStatus | null
}

export default function SettingsPage(props: SettingsPageProps) {
  return isBrowserMode() ? <ServerSettings active={props.active} status={props.status} /> : <DesktopSettings {...props} />
}

function ServerSettings({ active, status }: { active: boolean; status: AppStatus | null }) {
  const [setup, setSetup] = useState<Awaited<ReturnType<typeof getBrowserSetup>> | null>(null)
  const [twitchDraft, setTwitchDraft] = useState({ clientId: '', botUsername: '', botUserId: '', channel: '', channelUserId: '' })
  const [secretDraft, setSecretDraft] = useState('')
  const [callbackUrl, setCallbackUrl] = useState('')
  const [authorizationExpires, setAuthorizationExpires] = useState<number | null>(null)
  const [authorizationUrl, setAuthorizationUrl] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [retry, setRetry] = useState(0)
  const [selectedPresetId, setSelectedPresetId] = useState('')
  const [presetName, setPresetName] = useState('')
  const draftDirty = useRef(false)
  const mountedRef = useRef(false)
  const all = useCatalog(settingsText)
  const tw = all.twitch
  const text = all.server
  const common = useCatalog(commonText)
  const { fmt, plural } = useI18n()
  const refresh = async (resetDraft = true) => {
    const result = await getBrowserSetup()
    if (!result.ok) throw new Error(result.error ?? catalogFor(settingsText).server.unavailable)
    if (mountedRef.current) {
      setSetup(result)
      if (resetDraft) setTwitchDraft({
        clientId: result.twitch.client_id,
        botUsername: result.twitch.bot_username,
        botUserId: result.twitch.bot_user_id,
        channel: result.twitch.target_channel,
        channelUserId: result.twitch.target_channel_user_id,
      })
      if (resetDraft) {
        draftDirty.current = false
        const preset = result.twitch.presets?.find((item) => item.id === result.twitch.active_preset_id)
        setSelectedPresetId(preset?.id ?? '')
        setPresetName(preset?.display_name ?? '')
      }
      setError('')
    }
  }
  useEffect(() => {
    mountedRef.current = active
    if (!active) {
      setSecretDraft('')
      setCallbackUrl('')
      setAuthorizationExpires(null)
      setAuthorizationUrl('')
      return
    }
    let mounted = true
    void refresh(!draftDirty.current).catch((reason: unknown) => {
      if (mounted && mountedRef.current) setError(reason instanceof Error ? reason.message : catalogFor(settingsText).server.loadFailed)
    })
    return () => { mounted = false; mountedRef.current = false }
  }, [active, retry])
  useEffect(() => {
    if (!active) return
    const frame = window.requestAnimationFrame(() => {
      document.getElementById('twitch-settings')?.dispatchEvent(new CustomEvent('accordion:open', { bubbles: true }))
    })
    return () => window.cancelAnimationFrame(frame)
  }, [active])
  useEffect(() => {
    if (!active || authorizationExpires === null || setup?.twitch.authorization_mode !== 'redirect') return
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const result = await getBrowserSetup()
        if (disposed) return
        const attempt = result.twitch.authorization_attempt
        if (attempt && attempt !== 'pending') {
          setAuthorizationExpires(null)
          setAuthorizationUrl('')
          setSetup(result)
          const current = catalogFor(settingsText).server
          if (attempt === 'completed') {
            setNotice(current.authCompleted)
          } else {
            setError(attempt === 'expired'
              ? current.authExpired
              : current.authIncomplete)
          }
          return
        }
      } catch (reason) {
        if (disposed) return
        setError(reason instanceof Error ? reason.message : catalogFor(settingsText).server.unreachable)
      }
      if (!disposed) timer = setTimeout(() => void poll(), 2500)
    }
    timer = setTimeout(() => void poll(), 1000)
    return () => { disposed = true; clearTimeout(timer) }
  }, [active, authorizationExpires, setup?.twitch.authorization_mode])

  const updateDraft = (field: keyof typeof twitchDraft, value: string) => {
    draftDirty.current = true
    setTwitchDraft((current) => ({ ...current, [field]: value }))
    setError('')
    setNotice('')
  }
  const run = async (label: string, action: () => Promise<void>) => {
    setBusy(label)
    setError('')
    setNotice('')
    try { await action() } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.rejected)
    } finally { setBusy('') }
  }
  const copyBrowserText = async (value: string) => {
    setError('')
    setNotice('')
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value)
      else {
        const input = document.createElement('textarea')
        input.value = value
        input.setAttribute('readonly', '')
        input.style.position = 'fixed'
        input.style.opacity = '0'
        document.body.appendChild(input)
        input.select()
        const copied = document.execCommand('copy')
        input.remove()
        if (!copied) throw new Error(all.desktop.clipboardUnavailable)
      }
      setNotice(all.desktop.callbackCopied)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : all.desktop.callbackCopyFailed)
    }
  }
  const saveTwitch = () => run('twitch:save', async () => {
    if (targetChanged && !window.confirm(text.confirmTarget)) return
    const channel = twitchDraft.channel.trim().replace(/^#/, '')
    const values = { ...twitchDraft, channel }
    if (!values.clientId.trim() || !values.botUsername.trim() || !values.botUserId.trim() || !channel || !values.channelUserId.trim()) {
      throw new Error(text.enterSetup)
    }
    const result = await (await waitForBridge()).update_server_twitch_settings(
      values.clientId.trim(), values.botUsername.trim(), values.botUserId.trim(), channel, values.channelUserId.trim(),
    )
    if (!result.ok) throw new Error(result.error ?? all.desktop.twitchSaveFailed)
    await refresh()
    setNotice(text.saved)
  })
  const selectedPreset = setup?.twitch.presets?.find((item) => item.id === selectedPresetId)
  const targetChanged = Boolean(setup && (twitchDraft.channel !== setup.twitch.target_channel || twitchDraft.channelUserId !== setup.twitch.target_channel_user_id))
  const identityChanged = Boolean(setup && (twitchDraft.clientId !== setup.twitch.client_id || twitchDraft.botUsername !== setup.twitch.bot_username || twitchDraft.botUserId !== setup.twitch.bot_user_id))
  const presetEdited = Boolean(selectedPreset && (presetName !== selectedPreset.display_name || twitchDraft.channel !== selectedPreset.target_channel || twitchDraft.channelUserId !== selectedPreset.target_channel_user_id))
  const selectPreset = (id: string) => {
    if ((presetEdited || (!selectedPreset && (targetChanged || presetName.trim()))) && !window.confirm(text.confirmDiscardPreset)) return
    const preset = setup?.twitch.presets?.find((item) => item.id === id)
    setSelectedPresetId(id)
    draftDirty.current = true
    setPresetName(preset?.display_name ?? '')
    if (preset) setTwitchDraft((current) => ({ ...current, channel: preset.target_channel, channelUserId: preset.target_channel_user_id }))
    setError('')
    setNotice(text.selectionOnly)
  }
  const savePreset = (update: boolean) => run('preset:save', async () => {
    const result = await (await waitForBridge()).save_twitch_preset(update ? selectedPresetId : null, presetName.trim(), twitchDraft.channel.trim(), twitchDraft.channelUserId.trim())
    if (!result.ok) throw new Error(result.error ?? all.desktop.presetSaveFailed)
    await refresh(false)
    setSelectedPresetId(result.preset_id ?? '')
    setNotice(text.presetStored)
  })
  const deletePreset = () => {
    if (!selectedPreset || !window.confirm(text.confirmDeletePreset)) return
    void run('preset:delete', async () => {
      const result = await (await waitForBridge()).delete_twitch_preset(selectedPresetId)
      if (!result.ok) throw new Error(result.error ?? all.desktop.presetDeleteFailed)
      await refresh(false)
      setSelectedPresetId('')
      setPresetName('')
      setNotice(text.presetDeleted)
    })
  }
  const switchPreset = () => {
    if (!selectedPreset || identityChanged || presetEdited) return
    if (!window.confirm(fmt(text.confirmSwitch, { channel: selectedPreset.target_channel }))) return
    void run('preset:switch', async () => {
      const result = await (await waitForBridge()).switch_server_twitch_preset(selectedPresetId)
      if (!result.ok) throw new Error(result.error ?? text.switchFailed)
      await refresh()
      setNotice(text.switched)
    })
  }
  const runSecretAction = (action: 'replace' | 'remove' | 'test') => run(`twitch_client_secret:${action}`, async () => {
    if (action === 'remove' && !window.confirm(text.confirmRemoveSecret)) return
    const value = secretDraft
    setSecretDraft('')
    const credential = setup?.credentials.find((item) => item.name === 'twitch_client_secret')
    if (!credential) throw new Error(text.secretUnavailable)
    if (action !== 'test' && !credential.managed) throw new Error(text.secretExternal)
    if (action === 'replace' && !value.trim()) throw new Error(text.enterSecret)
    const api = await waitForBridge()
    const result = action === 'replace' ? await api.replace_credential('twitch_client_secret', value)
      : action === 'remove' ? await api.remove_credential('twitch_client_secret') : await api.test_credential('twitch_client_secret')
    if (!result.ok) throw new Error(result.error ?? all.desktop.secretFailed)
    await refresh(false)
    setNotice(action === 'test' ? all.desktop.secretPassed : result.changed === false ? all.desktop.secretUnchanged : action === 'remove' ? text.secretRemoved : text.secretSaved)
  })
  const beginAuthorization = () => run('oauth:begin', async () => {
    setAuthorizationUrl('')
    setCallbackUrl('')
    const result = await (await waitForBridge()).begin_twitch_authorization()
    if (!result.ok || !result.url) throw new Error(result.error ?? text.authStartFailed)
    let url: URL
    try { url = new URL(result.url) } catch { throw new Error(text.invalidUrl) }
    if (url.origin !== 'https://id.twitch.tv' || url.username || url.password || url.pathname !== '/oauth2/authorize') {
      throw new Error(text.untrustedUrl)
    }
    if (!mountedRef.current) return
    setAuthorizationUrl(url.toString())
    window.open(url.toString(), '_blank', 'noopener,noreferrer')
    setAuthorizationExpires(result.expires_in ?? 300)
    setNotice(setup?.twitch.authorization_mode === 'redirect'
      ? text.redirectReady
      : text.pasteReady)
  })
  const completeAuthorization = () => {
    const value = callbackUrl.trim()
    setCallbackUrl('')
    setAuthorizationUrl('')
    return run('oauth:complete', async () => {
    if (!value) throw new Error(text.pasteCallback)
    const result = await (await waitForBridge()).complete_twitch_authorization(value)
    if (!result.ok) throw new Error(result.error ?? text.completeFailed)
    setAuthorizationExpires(null)
    await refresh()
    setNotice(text.authCompleted)
    })
  }
  const cancelAuthorization = () => {
    setCallbackUrl('')
    setAuthorizationUrl('')
    return run('oauth:cancel', async () => {
    const result = await (await waitForBridge()).cancel_twitch_authorization()
    if (!result.ok) throw new Error(result.error ?? text.cancelFailed)
    setAuthorizationExpires(null)
    setNotice(text.cancelled)
    })
  }
  const twitchCredential = setup?.credentials.find((credential) => credential.name === 'twitch_client_secret')

  return <div className="settings-layout">
    <FeedbackToast error={error} notice={notice} onDismiss={() => { setError(''); setNotice('') }} />
    <Accordion id="twitch-settings" title={tw.title} helpLabel={tw.helpLabel} description={<ul>{tw.serverHelp.map((item) => <li key={item}>{item}</li>)}</ul>} className="settings-page server-settings-page">
      {!setup ? <><p className="muted">{text.loading}</p>{error && <button className="secondary" onClick={() => setRetry((current) => current + 1)}>{text.retry}</button>}</> : <div className="settings-list twitch-settings-list">
        <section className="twitch-connection-summary" aria-label={tw.statusLabel}>
          <TwitchSetupInstructions compact headingId="server-twitch-setup" host="server" callback={setup.twitch.oauth_callback_url} callbackMode={setup.twitch.authorization_mode} />
          <div className="twitch-status-grid">
            <div><span>{tw.connection}</span><strong className={status?.twitch_connected ? 'status-good' : ''}>{status ? twitchConnectionLabel(status.twitch_connection_state) : setup.twitch.connected ? common.connection.connected : setup.twitch.running ? common.connection.connecting : common.connection.stopped}</strong></div>
            <div><span>{tw.authorization}</span><strong>{setup.twitch.authorization_status === 'verified' ? tw.verified : setup.twitch.authorization_status === 'not_verified' ? tw.notVerified : setup.twitch.authorization_status === 'validation_failed' ? tw.validationFailed : tw.missing}</strong></div>
            <div><span>{tw.authorizedAccount}</span><strong>{setup.twitch.authorized_account || tw.notAuthorized}</strong></div>
            <div><span>{tw.targetChannel}</span><strong>{setup.twitch.active_channel || common.notConfigured}</strong></div>
          </div>
        </section>
        <section className="twitch-settings-group" aria-labelledby="server-twitch-bot-heading">
          <h3 id="server-twitch-bot-heading">{tw.botAccount}</h3>
          <div className="twitch-field-pair">
            <label className="form-field">{tw.botLogin}<input disabled={Boolean(busy)} value={twitchDraft.botUsername} maxLength={25} onChange={(event) => updateDraft('botUsername', event.target.value)} /></label>
            <label className="form-field">{tw.botUserId}<input disabled={Boolean(busy)} inputMode="numeric" value={twitchDraft.botUserId} maxLength={20} onChange={(event) => updateDraft('botUserId', event.target.value)} /></label>
          </div>
        </section>
        <section className="twitch-settings-group" aria-labelledby="server-twitch-target-heading">
          <h3 id="server-twitch-target-heading">{tw.targetChannel}</h3>
          <div className="twitch-target-fields">
            <label className="form-field target-saved-channel">{tw.savedChannel}<Select aria-label={tw.savedChannel} value={selectedPresetId} disabled={Boolean(busy)} onChange={selectPreset} options={[{ value: '', label: tw.newSavedChannel }, ...(setup.twitch.presets ?? []).map((preset) => ({ value: preset.id, label: preset.id === setup.twitch.active_preset_id ? fmt(tw.activePreset, { name: preset.display_name }) : preset.display_name }))]} /></label>
            <div className="target-preset-editor">
              <label className="form-field">{tw.savedChannelName}<input value={presetName} maxLength={80} disabled={Boolean(busy)} onChange={(event) => { draftDirty.current = true; setPresetName(event.target.value) }} /></label>
              <div className="preset-actions">
                <button className="secondary" aria-label={selectedPreset ? tw.updateSavedChannel : tw.saveNewChannel} disabled={Boolean(busy) || !presetName.trim()} onClick={() => void savePreset(Boolean(selectedPreset))}>{selectedPreset ? tw.update : common.save}</button>
                <button className="ghost destructive" aria-label={tw.deleteSavedChannel} disabled={Boolean(busy) || !selectedPreset} onClick={deletePreset}>{common.delete}</button>
              </div>
            </div>
            <label className="form-field target-channel-login">{tw.targetLogin}<input disabled={Boolean(busy)} value={twitchDraft.channel} maxLength={25} onChange={(event) => updateDraft('channel', event.target.value)} /></label>
            <label className="form-field target-channel-id">{tw.targetUserId}<input disabled={Boolean(busy)} inputMode="numeric" value={twitchDraft.channelUserId} maxLength={20} onChange={(event) => updateDraft('channelUserId', event.target.value)} /></label>
          </div>
          <p className="settings-hint">{tw.selectionHint}</p>
          <button className="primary" disabled={Boolean(busy) || !selectedPreset || identityChanged || presetEdited || !targetChanged} onClick={switchPreset}>{tw.switchPreset}</button>
          {identityChanged && <p className="settings-hint">{tw.identityChangedHint}</p>}
          {presetEdited && <p className="settings-hint">{tw.presetEditedHint}</p>}
          {(targetChanged || identityChanged || presetEdited) && <button className="secondary" disabled={Boolean(busy)} onClick={() => { if (window.confirm(text.confirmDiscardPreset)) void run('twitch:discard', () => refresh()) }}>{tw.discardEdits}</button>}
          <p className="target-channel-state"><span>{tw.activeChannel}</span><strong>{setup.twitch.active_channel || common.notConfigured}</strong>{targetChanged && <><span>{tw.draftTarget}</span><strong>{twitchDraft.channel || common.notConfigured}</strong></>}</p>
        </section>
        <Accordion id="twitch-application" title={tw.application} badges={<span className={`state-pill ${twitchCredential?.configured ? 'enabled' : 'unconfigured'}`}>{twitchCredential?.configured ? tw.secretConfigured : tw.secretMissing}</span>} className="twitch-application-disclosure">
          <div className="settings-application-box">
            <div className="settings-application-fields">
              <label className="form-field"><span className="application-field-label">Client ID</span><input disabled={Boolean(busy)} value={twitchDraft.clientId} maxLength={128} onChange={(event) => updateDraft('clientId', event.target.value)} /></label>
              <TwitchSecretField credential={twitchCredential} value={secretDraft} busy={busy} host="server" onChange={setSecretDraft} onAction={(action) => void runSecretAction(action)} />
            </div>
            <div className="settings-application-footer">
              <div className="settings-callback"><div><span>{tw.callbackUrl}</span><code>{setup.twitch.oauth_callback_url || common.unavailable}</code></div><button className="secondary" aria-label={tw.copyCallback} disabled={!setup.twitch.oauth_callback_url} onClick={() => void copyBrowserText(setup.twitch.oauth_callback_url)}>{tw.copy}</button></div>
              <a className="secondary" href="https://dev.twitch.tv/console/apps" target="_blank" rel="noopener noreferrer">{tw.openConsole}</a>
            </div>
          </div>
          {setup.twitch.management_url && <div className="oauth-callback"><span>{tw.managementUrl}</span><code>{setup.twitch.management_url}</code></div>}
        </Accordion>
        <section className="twitch-settings-group twitch-save-section">
          <h3>{tw.saveAndAuthorize}</h3>

          <div className="settings-actions">
            <button className="primary" disabled={Boolean(busy)} onClick={() => void saveTwitch()}>{busy === 'twitch:save' ? common.saving : tw.saveTwitch}</button>
            <button className="primary" disabled={Boolean(busy) || !setup.twitch.client_id} onClick={() => void beginAuthorization()}>{busy === 'oauth:begin' ? tw.opening : tw.connectTwitch}</button>
          </div>
          <p className="settings-hint">{tw.serverIdentityHint}</p>
          {authorizationExpires !== null && <>
            {authorizationUrl && <a className="secondary" href={authorizationUrl} target="_blank" rel="noopener noreferrer">{tw.openAuthorization}</a>}
            <p className="settings-hint">{plural(tw.expires, Math.ceil(authorizationExpires / 60))} {setup.twitch.authorization_mode === 'redirect' ? tw.expiresRedirect : tw.expiresPaste}</p>
            {setup.twitch.authorization_mode !== 'redirect' && <label className="form-field">{tw.callbackField}<input type="password" autoComplete="off" maxLength={16384} value={callbackUrl} onChange={(event) => setCallbackUrl(event.target.value)} placeholder={tw.callbackPlaceholder} /></label>}
            <div className="credential-actions">
              {setup.twitch.authorization_mode !== 'redirect' && <button className="primary" disabled={Boolean(busy) || !callbackUrl.trim()} onClick={() => void completeAuthorization()}>{busy === 'oauth:complete' ? tw.checking : tw.completeAuthorization}</button>}
              <button className="secondary" disabled={Boolean(busy)} onClick={() => void cancelAuthorization()}>{busy === 'oauth:cancel' ? tw.cancelling : common.cancel}</button>
            </div>
          </>}
        </section>

      </div>}
    </Accordion>
    <InterfaceLanguageSettings server />
    <div className="settings-transfer-bottom"><ConfigurationTransfer /></div>
  </div>
}

function DesktopSettings({ active, status }: SettingsPageProps) {
  const [saved, setSaved] = useState<AppSettings | null>(null)
  const [draft, setDraft] = useState<AppSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [twitchCredential, setTwitchCredential] = useState<CredentialInfo>()
  const [twitchSaved, setTwitchSaved] = useState<TwitchConnectionSettings | null>(null)
  const [twitchDraft, setTwitchDraft] = useState<TwitchConnectionSettings | null>(null)
  const [presetName, setPresetName] = useState('')
  const [secretDraft, setSecretDraft] = useState('')
  useEffect(() => { if (!active) setSecretDraft('') }, [active])
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [profilePath, setProfilePath] = useState('')
  const [profileError, setProfileError] = useState('')
  const all = useCatalog(settingsText)
  const tw = all.twitch
  const text = all.desktop
  const common = useCatalog(commonText)
  const { fmt } = useI18n()

  useEffect(() => {
    if (!active) return
    let mounted = true
    const loadProfile = async () => {
      try {
        const api = await waitForBridge()
        const profile = await api.get_profile_info()
        if (!profile.path) throw new Error(catalogFor(settingsText).desktop.profileUnavailable)
        if (mounted) {
          setProfilePath(profile.path)
          setProfileError('')
        }
      } catch (reason) {
        if (mounted) {
          setProfilePath('')
          setProfileError(reason instanceof Error ? reason.message : catalogFor(settingsText).desktop.profileLoadFailed)
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
        const current = catalogFor(settingsText).desktop
        if (!response.ok || !response.settings) {
          throw new Error(response.error ?? current.settingsUnavailable)
        }
        if (!credentialResponse.ok || !credentialResponse.credentials) {
          throw new Error(credentialResponse.error ?? current.credentialsUnavailable)
        }
        if (!twitchResponse.ok || !twitchResponse.settings) {
          throw new Error(twitchResponse.error ?? current.twitchUnavailable)
        }
        if (mounted) {
          setDraft(response.settings)
          setSaved(response.settings)
          setTwitchCredential(credentialResponse.credentials.find((item) => item.name === 'twitch_client_secret'))
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
          setPresetName((current) => {
            const previousName = twitchDraft?.presets.find((preset) => preset.id === twitchDraft.selected_preset_id)?.display_name ?? ''
            return current !== previousName ? current : selectedPreset?.display_name ?? ''
          })
          setError('')
        }
      } catch (reason) {
        if (mounted) {
          setError(reason instanceof Error ? reason.message : catalogFor(settingsText).desktop.loadFailed)
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
        throw new Error(result.error ?? text.saveFailed)
      }
      setSaved(updated)
      setNotice(successMessage)
    } catch (reason) {
      setDraft(previous)
      setError(reason instanceof Error ? reason.message : text.saveFailed)
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
        throw new Error(result.error ?? text.openFailed)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.openFailed)
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
            throw new Error(text.clipboardUnavailable)
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
      if (!result.ok) throw new Error(result.error ?? text.folderFailed)
      setNotice(text.folderOpened)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.folderFailed)
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
      setError(text.presetMissing)
      return
    }
    updateTwitchDraft({
      selected_preset_id: preset.id,
      target_channel: preset.target_channel,
      target_channel_user_id: preset.target_channel_user_id,
    })
    setPresetName(preset.display_name)
    setNotice(text.presetSelected)
  }

  const restartPendingTwitch = async () => {
    setBusy('twitch:restart')
    setError('')
    try {
      if (await restartDesktop()) return
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.restartFailed)
    }
    setBusy('')
  }

  const saveTwitch = async (apply: boolean) => {
    if (!twitchDraft) {
      return
    }
    const channel = twitchDraft.target_channel.trim().replace(/^#/, '')
    const channelUserId = twitchDraft.target_channel_user_id.trim()
    if (!channel || /\s/.test(channel)) {
      setError(text.channelInvalid)
      return
    }
    if (!/^\d+$/.test(channelUserId)) {
      setError(text.channelIdInvalid)
      return
    }
    setBusy(apply ? 'twitch:reconnect' : 'twitch:save')
    setError('')
    setNotice('')
    let restarting = false
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
        throw new Error(savedResult.error ?? text.twitchSaveFailed)
      }
      if (apply && savedResult.requires_restart) {
        setNotice(text.restartToApply)
        setTwitchSaved({ ...twitchDraft, requires_restart: true })
        // Exclude only the draft saved by this action. Other editor state can
        // still be present, including an unsaved channel name or secret.
        restarting = await restartDesktop('Twitch connection')
        if (restarting) return
      }
      let applyError = ''
      if (apply && !savedResult.requires_restart && savedResult.requires_reconnect) {
        const reconnectResult = await api.reconnect_twitch()
        if (!reconnectResult.ok) {
          applyError = reconnectResult.error ?? text.reconnectFailed
        }
      }
      const refreshed = await api.get_twitch_settings()
      if (!refreshed.ok || !refreshed.settings) {
        throw new Error(refreshed.error ?? text.statusRefreshFailed)
      }
      setTwitchSaved(refreshed.settings)
      setTwitchDraft(refreshed.settings)
      const refreshedPreset = refreshed.settings.presets.find(
        (preset) => preset.id === refreshed.settings!.selected_preset_id,
      )
      if (!presetNameDirty) setPresetName(refreshedPreset?.display_name ?? '')
      if (applyError) throw new Error(applyError)
      setNotice(
        savedResult.requires_restart
          ? text.restartToApply
          : apply && savedResult.requires_reconnect
          ? refreshed.settings.running
            ? text.savedRestarted
            : text.savedNextStart
          : savedResult.requires_reconnect
            ? text.savedApplyLater
            : text.saved,
      )
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.twitchSaveFailed)
    } finally {
      if (!restarting) setBusy('')
    }
  }

  const saveTwitchPreset = async () => {
    if (!twitchDraft) {
      return
    }
    const name = presetName.trim()
    if (!name) {
      setError(text.presetNameEmpty)
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
        throw new Error(result.error ?? text.presetSaveFailed)
      }
      const refreshed = await api.get_twitch_settings()
      if (!refreshed.ok || !refreshed.settings) {
        throw new Error(refreshed.error ?? text.refreshFailed)
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
          ? text.channelSavedRestart
          : result.requires_reconnect
          ? refreshed.settings.running
            ? text.channelSavedReconnect
            : text.channelSavedApply
          : text.channelSaved,
      )
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.presetSaveFailed)
    } finally {
      setBusy('')
    }
  }

  const deleteTwitchPreset = async () => {
    if (!twitchDraft?.selected_preset_id) {
      return
    }
    if (!window.confirm(text.confirmDeletePreset)) {
      return
    }
    setBusy('twitch:preset-delete')
    setError('')
    setNotice('')
    try {
      const api = await waitForBridge()
      const result = await api.delete_twitch_preset(twitchDraft.selected_preset_id)
      if (!result.ok) {
        throw new Error(result.error ?? text.presetDeleteFailed)
      }
      const refreshed = await api.get_twitch_settings()
      if (!refreshed.ok || !refreshed.settings) {
        throw new Error(refreshed.error ?? text.refreshFailed)
      }
      setTwitchSaved(refreshed.settings)
      setPresetName('')
      setNotice(text.presetDeleted)
      setTwitchDraft({ ...refreshed.settings, client_id: twitchDraft.client_id,
        bot_username: twitchDraft.bot_username, bot_user_id: twitchDraft.bot_user_id })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.presetDeleteFailed)
    } finally {
      setBusy('')
    }
  }

  const runSecretAction = async (action: 'replace' | 'remove' | 'test', restart = false) => {
    if (action === 'remove' && !window.confirm(restart
      ? text.confirmRemoveRestart
      : text.confirmRemoveLater)) return
    setBusy(`twitch_client_secret:${action}`)
    setError(''); setNotice('')
    let restarting = false
    try {
      const api = await waitForBridge()
      const result = action === 'replace' ? await api.replace_credential('twitch_client_secret', secretDraft)
        : action === 'remove' ? await api.remove_credential('twitch_client_secret') : await api.test_credential('twitch_client_secret')
      if (!result.ok) throw new Error(result.error ?? text.secretFailed)
      if (action !== 'test') {
        if (action === 'replace') setSecretDraft('')
        const response = await api.get_credentials()
        if (!response.ok || !response.credentials) throw new Error(response.error ?? text.secretUnavailable)
        setTwitchCredential(response.credentials.find((item) => item.name === 'twitch_client_secret'))
        const twitchResponse = await api.get_twitch_settings()
        if (!twitchResponse.ok || !twitchResponse.settings) throw new Error(twitchResponse.error ?? text.restartStatusUnavailable)
        setTwitchSaved(twitchResponse.settings)
        setTwitchDraft((current) => current ? { ...current, requires_restart: twitchResponse.settings!.requires_restart, requires_secret_restart: twitchResponse.settings!.requires_secret_restart } : twitchResponse.settings!)
        if (restart && result.changed && result.requires_restart) {
          restarting = await restartDesktop(action === 'replace' ? 'Twitch client secret' : undefined)
          if (restarting) return
        }
      }
      setNotice(action === 'test' ? text.secretPassed : result.changed === false ? text.secretUnchanged : `${action === 'remove' ? text.secretRemoved : text.secretSaved}${result.requires_restart ? text.restartSuffix : ''}`)
    } catch (reason) { setError(reason instanceof Error ? reason.message : text.secretFailed) }
    finally { if (!restarting) setBusy('') }
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
  const pendingRestart = Boolean(twitchSaved?.requires_restart || twitchSaved?.requires_cleanup_restart)
  const draftRequiresRestart = Boolean(twitchDraft && twitchSaved && (
    (twitchSaved.requires_secret_restart ?? twitchSaved.requires_restart) || twitchSaved.requires_cleanup_restart
    || twitchDraft.client_id.trim() !== (twitchSaved.active_client_id ?? twitchSaved.client_id)
    || twitchDraft.bot_username.trim().toLowerCase() !== (twitchSaved.active_bot_username ?? twitchSaved.bot_username)
    || twitchDraft.bot_user_id.trim() !== (twitchSaved.active_bot_user_id ?? twitchSaved.bot_user_id)
  ))
  const presetNameDirty = Boolean(twitchDraft && presetName !== (
    twitchDraft.presets.find((preset) => preset.id === twitchDraft.selected_preset_id)?.display_name ?? ''
  ))
  useRestartDraft('Twitch connection', twitchDirty)
  useRestartDraft('Saved channel name', presetNameDirty)
  useRestartDraft('Twitch client secret', Boolean(secretDraft))
  const draftRequiresReconnect = Boolean(
    twitchDraft
      && (twitchDraft.target_channel.trim().toLowerCase().replace(/^#/, '')
        !== twitchDraft.active_channel.toLowerCase()
        || twitchDraft.target_channel_user_id.trim()
        !== twitchDraft.active_channel_user_id),
  )
  const twitchRunning = status?.running ?? twitchDraft?.running
  const twitchTargetMissing = Boolean(
    twitchDraft
      && (!twitchDraft.target_channel.trim() || !twitchDraft.target_channel_user_id.trim()
        || !twitchDraft.client_id.trim() || !twitchDraft.bot_username.trim() || !twitchDraft.bot_user_id.trim()),
  )
  const twitchAuthorizationStatus = status
    ? twitchAuthorizationLabel(status.twitch_connection_state, twitchDraft?.oauth_token_available ?? false)
    : twitchDraft
      ? twitchAuthorizationLabel(
          twitchDraft.connected ? 'connected' : twitchDraft.running ? 'connecting' : 'stopped',
          twitchDraft.oauth_token_available,
        )
      : common.authorization.notVerified


  return (
    <div className="settings-layout" aria-busy={loading}>
      <FeedbackToast
        error={error}
        notice={notice}
        onDismiss={() => { setError(''); setNotice('') }}
      />
      <section className="card settings-page" id="desktop-settings">
        <div className="section-heading">
          <div>
            <h2>{text.title}</h2>
            <p className="section-copy">{text.intro}</p>
          </div>
          <span className="mini-badge saved-badge">{text.autoSaved}</span>
        </div>
        {!draft ? <p className="muted">{text.loading}</p> : (
          <div className="settings-list desktop-settings-list">
            <Switch className="settings-option" checked={draft.auto_start_bot} disabled={Boolean(busy)} onCheckedChange={(auto_start_bot) => void updateWindowSettings({ auto_start_bot }, text.autoStartSaved)}>
              <span><strong>{text.autoStart}</strong><small>{text.autoStartHint}</small></span>
            </Switch>
            <Switch className="settings-option" checked={draft.start_minimized} disabled={Boolean(busy) || !draft.tray_available} onCheckedChange={(start_minimized) => void updateWindowSettings({ start_minimized }, text.startMinimizedSaved)}>
              <span><strong>{text.startMinimized}</strong><small>{draft.tray_available ? text.nextLaunch : text.trayOnly}</small></span>
            </Switch>
            <Switch className="settings-option" checked={draft.minimize_to_tray} disabled={Boolean(busy) || !draft.tray_available} onCheckedChange={(minimize_to_tray) => void updateWindowSettings({ minimize_to_tray }, text.minimizeSaved)}>
              <span><strong>{text.minimizeToTray}</strong><small>{draft.tray_available ? text.minimizeHint : text.trayOnly}</small></span>
            </Switch>
            <Switch className="settings-option" checked={draft.close_to_tray} disabled={Boolean(busy) || !draft.tray_available} onCheckedChange={(close_to_tray) => void updateWindowSettings({ close_to_tray }, text.closeSaved)}>
              <span><strong>{text.closeToTray}</strong><small>{draft.tray_available ? text.closeHint : text.trayOnly}</small></span>
            </Switch>
          </div>
        )}
      </section>
      <Accordion
        id="twitch-settings"
        title={tw.title}
        helpLabel={tw.helpLabel}
        description={<ul>{tw.desktopHelp.map((item) => <li key={item}>{item}</li>)}</ul>}
        badges={twitchDirty && <span className="mini-badge dirty-badge">{tw.edited}</span>}
        className="settings-page"
      >
        {!twitchDraft ? <p className="muted">{text.loadingTwitch}</p> : (
          <div className="settings-list twitch-settings-list">
            <section className="twitch-connection-summary" aria-label={tw.statusLabel}>
              <TwitchSetupInstructions compact headingId="desktop-twitch-setup" host="desktop" callback={twitchDraft.oauth_callback_url} />
              <div className="twitch-status-grid">
                <div><span>{tw.connection}</span><strong className={status?.twitch_connected ? 'status-good' : ''}>{status ? twitchConnectionLabel(status.twitch_connection_state) : twitchDraft.connected ? common.connection.connected : twitchDraft.running ? common.connection.connecting : common.connection.stopped}</strong></div>
                <div><span>{tw.authorization}</span><strong>{twitchAuthorizationStatus}</strong></div>
                <div><span>{tw.activeBotAccount}</span><strong>{status?.account || common.notConfigured}</strong></div>
                <div><span>{tw.activeChannel}</span><strong title={twitchDraft.active_channel}>{twitchDraft.active_channel || common.notConfigured}</strong></div>
              </div>
            </section>
            <section className="twitch-settings-group" aria-labelledby="twitch-bot-heading">
              <h3 id="twitch-bot-heading">{tw.botAccount}</h3>
              <div className="twitch-field-pair">
                <label className="form-field">
                  <span>{tw.botLogin}</span>
                  <input value={twitchDraft.bot_username} disabled={Boolean(busy)} onChange={(event) => updateTwitchDraft({ bot_username: event.target.value })} placeholder="bot_name" />
                  <small>{tw.botLoginHint}</small>
                </label>
                <label className="form-field">
                  <span>{tw.botUserId}</span>
                  <input inputMode="numeric" value={twitchDraft.bot_user_id} disabled={Boolean(busy)} onChange={(event) => updateTwitchDraft({ bot_user_id: event.target.value })} placeholder="123456789" />
                  <small>{tw.botUserIdHint}</small>
                </label>
              </div>
            </section>
            <section className="twitch-settings-group" aria-labelledby="twitch-target-heading">
              <h3 id="twitch-target-heading">{tw.targetChannel}</h3>
              <div className="twitch-target-fields">
                <label className="form-field target-saved-channel">{tw.savedChannel}<Select aria-label={tw.savedChannel} value={twitchDraft.selected_preset_id ?? ''} onChange={selectTwitchPreset} disabled={Boolean(busy)} options={[{ value: '', label: tw.unsavedTarget }, ...twitchDraft.presets.map((preset) => ({ value: preset.id, label: preset.id === twitchDraft.active_preset_id ? fmt(tw.activePreset, { name: preset.display_name }) : preset.display_name }))]} /></label>
                <div className="target-preset-editor">
                  <label className="form-field">{tw.savedChannelName}<input value={presetName} onChange={(event) => { setPresetName(event.target.value); setError(''); setNotice('') }} placeholder={tw.presetPlaceholder} disabled={Boolean(busy)} /></label>
                  <div className="preset-actions">
                    <button className="secondary" aria-label={twitchDraft.selected_preset_id ? tw.updateSavedChannel : tw.saveChannel} disabled={Boolean(busy) || !presetName.trim()} onClick={() => void saveTwitchPreset()}>{busy === 'twitch:preset-save' ? tw.savingDots : twitchDraft.selected_preset_id ? tw.update : common.save}</button>
                    <button className="ghost destructive" aria-label={tw.deleteSavedChannel} disabled={Boolean(busy) || !twitchDraft.selected_preset_id} onClick={() => void deleteTwitchPreset()}>{busy === 'twitch:preset-delete' ? tw.deletingDots : common.delete}</button>
                  </div>
                </div>
                <label className="form-field target-channel-login">{tw.targetLogin}<input value={twitchDraft.target_channel} disabled={Boolean(busy)} onChange={(event) => updateTwitchDraft({ target_channel: event.target.value })} placeholder="channel_name" /><small>{tw.targetLoginHint}</small></label>
                <label className="form-field target-channel-id">{tw.targetUserId}<input inputMode="numeric" value={twitchDraft.target_channel_user_id} disabled={Boolean(busy)} onChange={(event) => updateTwitchDraft({ target_channel_user_id: event.target.value })} placeholder="123456789" /><small>{tw.targetUserIdHint}</small></label>
              </div>
              <p className="target-channel-state"><span>{tw.activeChannel}</span><strong>{twitchDraft.active_channel || common.notConfigured}</strong>{draftRequiresReconnect && <><span>{tw.draftTarget}</span><strong>{twitchDraft.target_channel || common.notConfigured}</strong></>}</p>
            </section>
            <Accordion id="twitch-application" title={tw.application} badges={twitchCredential && <span className={`state-pill ${twitchCredential.configured ? 'enabled' : 'unconfigured'}`}>{twitchCredential.configured ? tw.secretConfigured : tw.secretMissing}</span>} className="twitch-application-disclosure">
              <div className="settings-application-box">
                <div className="settings-application-fields">
                  <label className="form-field"><span className="application-field-label">Client ID</span><input aria-label={tw.clientIdAria} value={twitchDraft.client_id} disabled={Boolean(busy)} onChange={(event) => updateTwitchDraft({ client_id: event.target.value })} placeholder={tw.clientIdPlaceholder} /></label>
                  <TwitchSecretField credential={twitchCredential} value={secretDraft} busy={busy} host="desktop" onChange={(value) => { setSecretDraft(value); setError(''); setNotice('') }} onAction={(action, restart) => void runSecretAction(action, restart)} />
                </div>
                <div className="settings-application-footer">
                  <div className="settings-callback"><div><span>{tw.callbackUrl}</span><code>{twitchDraft.oauth_callback_url}</code></div><button className="secondary" aria-label={tw.copyCallback} onClick={() => void copyText(twitchDraft.oauth_callback_url, text.callbackCopied, text.callbackCopyFailed)}>{tw.copy}</button></div>
                  <button className="secondary" disabled={Boolean(busy)} onClick={() => void openTwitchLink('twitch_developer_console')}>{tw.openConsole}</button>
                </div>
              </div>
            </Accordion>
            <section className="twitch-settings-group twitch-save-section" aria-labelledby="twitch-actions-heading">
              <h3 id="twitch-actions-heading">{tw.saveAndAuthorize}</h3>
              {pendingRestart && <div className="setup-callout">
                <p>{twitchSaved?.requires_restart ? tw.pendingChanges : tw.cleanupRestart}</p>
                <button className="primary" disabled={Boolean(busy)} onClick={() => void restartPendingTwitch()}>{busy === 'twitch:restart' ? tw.restarting : tw.restartNow}</button>
              </div>}
              {(status?.twitch_connection_state === 'auth_required' || (!twitchTargetMissing && !twitchDraft.requires_restart && twitchCredential?.configured && !twitchDraft.oauth_token_available && !status?.twitch_connected)) && (
                <div className="setup-callout">
                  <div>
                    <strong>{tw.authRequired}</strong>
                    <p>{twitchDraft.requires_restart
                      ? tw.authRestart
                      : status?.running && status.twitch_connection_state === 'auth_required'
                      ? tw.authOpens
                      : tw.authStart}</p>
                  </div>
                  {status?.twitch_connection_state === 'auth_required' && (
                    <button className="primary" disabled={Boolean(busy) || !status.running || twitchDraft.requires_restart} onClick={() => void openTwitchLink('twitch_authorization')}>
                      {busy === 'external:twitch_authorization' ? tw.opening : tw.authorizeTwitch}
                    </button>
                  )}
                </div>
              )}
              <div className="settings-actions">
                {status?.twitch_connected && <button className="secondary" disabled={Boolean(busy) || twitchDraft.requires_restart} onClick={() => void openTwitchLink('twitch_authorization')}>
                  {busy === 'external:twitch_authorization' ? tw.opening : tw.renewAuthorization}
                </button>}
                {status?.twitch_connected && <HelpTip label={tw.permissionsLabel}><ul>{tw.permissions.map((item) => <li key={item}>{item}</li>)}</ul></HelpTip>}
                <button className="secondary" disabled={!twitchDirty || Boolean(busy)} onClick={() => void saveTwitch(false)}>{busy === 'twitch:save' ? common.saving : tw.saveForLater}</button>
                {(!pendingRestart || twitchDirty) && <button className="primary" disabled={Boolean(busy)} onClick={() => void saveTwitch(true)}>{busy === 'twitch:reconnect' ? common.saving : draftRequiresRestart ? tw.saveRestart : twitchRunning ? tw.saveReconnect : tw.saveApply}</button>}
              </div>
              {(draftRequiresRestart || draftRequiresReconnect) && <p className="settings-hint">{draftRequiresRestart
                ? tw.restartHint
                : draftRequiresReconnect
                  ? twitchRunning
                    ? tw.reconnectHint
                    : tw.applyHint
                  : ''}</p>}
            </section>
          </div>
        )}
      </Accordion>

      <InterfaceLanguageSettings />
      <div className="settings-transfer-bottom"><ConfigurationTransfer /></div>

      <section className="card settings-page" id="profile-location-settings" aria-labelledby="profile-location-heading">
        <div className="section-heading">
          <div>
            <h2 id="profile-location-heading">{all.profile.title}</h2>
            <p className="section-copy">{all.profile.warning}</p>
          </div>
        </div>
        <div className="profile-location">
          <span className="label">{all.profile.current}</span>
          {profileError ? <p className="credential-warning" role="alert">{profileError}</p>
            : profilePath ? <code>{profilePath}</code> : <p className="muted">{all.profile.loading}</p>}
          <div className="profile-location-actions">
            <button className="secondary" disabled={!profilePath || Boolean(busy)} onClick={() => void openProfileFolder()}>{busy === 'profile:open' ? tw.opening : all.profile.open}</button>
            <button className="ghost" disabled={!profilePath || Boolean(busy)} onClick={() => void copyText(profilePath, all.profile.copied, all.profile.copyFailed)}>{all.profile.copyPath}</button>
          </div>
        </div>
      </section>
    </div>
  )
}
