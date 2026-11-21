import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from '../src/App'
import type { AppStatus, CredentialInfo, PythonApi, TwitchConnectionSettings } from '../src/bridge'

const query = new URLSearchParams(window.location.search)
const status: AppStatus = {
  running: false, twitch_connected: false, twitch_connection_state: 'stopped',
  uptime_seconds: 0, channel: 'testchannel', account: 'testbot',
}
const twitch: TwitchConnectionSettings = {
  client_id: 'synthetic-client', bot_username: 'testbot', bot_user_id: '100',
  active_client_id: 'synthetic-client', active_bot_username: 'testbot', active_bot_user_id: '100',
  target_channel: 'testchannel', target_channel_user_id: '200', active_channel: 'testchannel',
  active_channel_user_id: '200', presets: [], selected_preset_id: null, active_preset_id: null,
  running: false, connected: false, oauth_token_available: true, saved_bot_authorization: true,
  oauth_callback_url: 'http://localhost:4343/oauth/callback', has_local_override: false,
  requires_restart: false, requires_reconnect: false,
}
const credentials: CredentialInfo[] = [{ name: 'twitch_client_secret', label: 'Twitch client secret', configured: true, source: 'credential_store', secure_storage_available: true }]
const updateCalls: unknown[][] = []
const bridgeCalls: unknown[][] = []
const opened: string[] = []
let aiEnabled = false
let verificationFailed = false
Object.assign(window, { updateCalls, bridgeCalls, opened })

const api: Partial<PythonApi> = {
  get_desktop_startup: async () => {
    if (query.has('startupFailure')) throw new Error('Synthetic startup failure')
    if (query.has('startupDelay')) await new Promise((resolve) => setTimeout(resolve, 800))
    return { state: 'ready', windows: !query.has('manualUpdate') }
  },
  get_interface_language: async () => ({ ok: true, language: 'en' }),
  get_app_status: async () => status,
  get_twitch_settings: async () => ({ ok: true, settings: structuredClone(twitch) }),
  get_credentials: async () => ({ ok: true, credentials }),
  replace_credential: async (name, value) => {
    bridgeCalls.push(['replace_credential', name, value])
    twitch.requires_restart = twitch.requires_secret_restart = true
    return { ok: true, changed: true, requires_restart: true }
  },
  restart_desktop: async () => { bridgeCalls.push(['restart_desktop']); return { ok: true } },
  get_app_settings: async () => ({ ok: true, settings: {
    auto_start_bot: false, start_minimized: false, minimize_to_tray: false, close_to_tray: false, tray_available: false,
  } }),
  get_profile_info: async () => ({ path: 'C:/Synthetic/HeetKit' }),
  open_profile_folder: async () => { bridgeCalls.push(['open_profile_folder']); return { ok: true } },
  get_setup_guide: async () => ({ ok: true, ai_skipped: false, dismissed: false }),
  get_ai_provider_settings: async () => ({ ok: true, settings: { provider: 'Gemini', selected_model: 'test-model', fallback_model: '', credential: null, presets: [] } }),
  get_ai_status: async () => ({
    enabled: aiEnabled, available: true, memory_enabled: false,
    active_personality: 'neutral', available_personalities: ['neutral'], model: 'test-model',
  }),
  get_recent_commands: async () => ({ entries: [] }),
  set_ai_enabled: async (value: boolean) => {
    bridgeCalls.push(['set_ai_enabled', value])
    aiEnabled = value
    return { ok: true }
  },
  get_about_info: async () => ({
    application_name: 'HeetKit', application_subtitle: 'Twitch bot controls', version: '0.1.0',
    author: 'heeetz', author_twitch: '@heet_ok', discord_contact: 'de.tected', license_name: 'Apache-2.0',
    repository_url: 'https://github.com/heeetz/heetkit-bot', license_url: 'https://www.apache.org/licenses/LICENSE-2.0',
    third_party_notices_url: 'https://github.com/heeetz/heetkit-bot/blob/main/THIRD_PARTY_NOTICES.md',
  }),
  check_for_updates: async () => {
    updateCalls.push(['check_for_updates'])
    if (query.has('failStartupCheck') && updateCalls.length === 1) throw new Error('Synthetic update service failure')
    return {
      ok: true, current_version: '0.1.0', latest_version: '0.2.0',
      update_available: true, automatic_update: !query.has('portable'),
      release_notes: 'Fixes <strong>markup</strong>.',
    }
  },
  prepare_desktop_update: async (version: string) => {
    updateCalls.push(['prepare', version])
    await new Promise<void>((resolve) => Reflect.set(window, 'finishUpdateDownload', resolve))
    if (query.has('failVerification') && !verificationFailed) {
      verificationFailed = true
      return { ok: false, error: 'Synthetic installer verification failure' }
    }
    return { ok: true }
  },
  get_desktop_update_progress: async () => ({ phase: 'downloading', downloaded: 30, total: 60 }),
  finish_desktop_update: async (version: string) => { updateCalls.push(['finish', version]); return { ok: true } },
  open_external_link: async (destination: string) => { opened.push(destination); return { ok: true } },
}

const bridge = { api: api as PythonApi }
if (query.has('lateBridge')) {
  window.setTimeout(() => {
    window.pywebview = bridge
    window.dispatchEvent(new Event('pywebviewready'))
  }, 300)
} else {
  window.pywebview = bridge
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
