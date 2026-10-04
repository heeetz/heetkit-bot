import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import App from '../src/App'
import FeedbackToast from '../src/components/FeedbackToast'
import SettingsPage from '../src/pages/SettingsPage'
import type { AppStatus, PersonalitiesResponse, TwitchConnectionSettings, waitForBridge } from '../src/bridge'

const query = new URLSearchParams(window.location.search)
const configured = query.has('configured')
const authRequired = query.has('auth')
const twitch: TwitchConnectionSettings = {
  client_id: configured ? 'synthetic-client' : '',
  bot_username: configured ? 'testbot' : '',
  bot_user_id: configured ? '100' : '',
  target_channel: configured ? 'testchannel' : '',
  target_channel_user_id: configured ? '200' : '',
  active_channel: configured ? 'testchannel' : '',
  active_channel_user_id: configured ? '200' : '',
  presets: [], selected_preset_id: null, active_preset_id: null,
  requires_restart: false, requires_reconnect: false,
  running: authRequired, connected: false,
  oauth_token_available: query.has('cachedToken'),
  oauth_callback_url: 'http://localhost:4343/oauth/callback',
  has_local_override: false,
}
let status: AppStatus = {
  running: authRequired, twitch_connected: false,
  twitch_connection_state: authRequired ? 'auth_required' : 'stopped',
  uptime_seconds: 0, channel: twitch.active_channel, account: twitch.bot_username,
}
const aiStatus = {
  enabled: false, available: false, memory_enabled: false,
  active_personality: 'Friendly', available_personalities: ['Friendly'], model: '',
}
let personalities: PersonalitiesResponse = {
  active_personality: 'Friendly',
  active_personality_saved: true,
  personalities: [{
    name: 'Friendly', prompt: 'Built-in friendly prompt.', built_in_prompt: 'Built-in friendly prompt.',
    prompt_saved: true, has_saved_override: false,
  }],
  profile_instructions: '', profile_instructions_saved: true,
  protected_shared_instructions: 'Synthetic shared instructions.',
}
const credentials = [
  { name: 'twitch_client_secret', label: 'Twitch client secret', configured, source: configured ? 'credential_store' : 'missing', secure_storage_available: true },
  { name: 'gemini_api_key', label: 'Gemini API key', configured: false, source: 'missing', secure_storage_available: true },
]
const opened: string[] = []
const aiCalls: unknown[][] = []
Object.assign(window, { opened, aiCalls })
window.pywebview = { api: {
  get_app_status: async () => status,
  get_ai_status: async () => aiStatus,
  get_personalities: async () => personalities,
  get_app_settings: async () => ({ ok: true, settings: {
    auto_start_bot: authRequired, start_minimized: false, minimize_to_tray: false,
    close_to_tray: false, tray_available: false,
  } }),
  get_twitch_settings: async () => ({ ok: true, settings: twitch }),
  get_credentials: async () => ({ ok: true, credentials }),
  get_ai_provider_settings: async () => ({ ok: true, settings: {
    provider: 'Gemini', selected_model: '', fallback_model: '', presets: [], credential: credentials[1],
  } }),
  start_bot: async () => {
    status = { ...status, running: true, twitch_connection_state: 'auth_required' }
    return { ok: true }
  },
  stop_bot: async () => {
    status = { ...status, running: false }
    return { ok: true }
  },
  apply_personality: async (name: string, prompt: string) => {
    aiCalls.push(['apply_personality', name, prompt])
    personalities = {
      ...personalities,
      active_personality: name,
      personalities: personalities.personalities.map((item) => item.name === name ? {
        ...item, prompt, prompt_saved: false,
      } : item),
    }
    return { ok: true }
  },
  save_personality: async (name: string, prompt: string) => {
    aiCalls.push(['save_personality', name, prompt])
    personalities = {
      ...personalities,
      active_personality: name,
      active_personality_saved: true,
      personalities: personalities.personalities.map((item) => item.name === name ? {
        ...item, prompt, prompt_saved: true, has_saved_override: prompt !== item.built_in_prompt,
      } : item),
    }
    return { ok: true }
  },
  reset_personality: async (name: string) => {
    aiCalls.push(['reset_personality', name])
    personalities = {
      ...personalities,
      active_personality: name,
      personalities: personalities.personalities.map((item) => item.name === name ? {
        ...item, prompt: item.built_in_prompt, prompt_saved: true, has_saved_override: false,
      } : item),
    }
    return { ok: true }
  },
  apply_profile_instructions: async (prompt: string) => {
    aiCalls.push(['apply_profile_instructions', prompt])
    if (query.has('profileError')) return { ok: false, error: 'Profile instructions could not be updated.' }
    personalities = { ...personalities, profile_instructions: prompt, profile_instructions_saved: false }
    return { ok: true }
  },
  save_profile_instructions: async (prompt: string) => {
    aiCalls.push(['save_profile_instructions', prompt])
    if (query.has('profileError')) return { ok: false, error: 'Profile instructions could not be saved.' }
    personalities = { ...personalities, profile_instructions: prompt, profile_instructions_saved: true }
    return { ok: true }
  },
  reset_profile_instructions: async () => {
    aiCalls.push(['reset_profile_instructions'])
    if (query.has('profileError')) return { ok: false, error: 'Profile instructions could not be reset.' }
    personalities = { ...personalities, profile_instructions: '', profile_instructions_saved: true }
    return { ok: true }
  },
  open_external_link: async (destination: string) => {
    opened.push(destination)
    return query.has('openError') ? { ok: false, error: 'Could not open the external link.' } : { ok: true }
  },
} as unknown as Awaited<ReturnType<typeof waitForBridge>> }

function ToastFixture() {
  const [error, setError] = useState(query.has('error') ? 'Initial error' : '')
  const [notice, setNotice] = useState(query.has('error') ? '' : 'Initial success')
  const [renders, setRenders] = useState(0)
  return <>
    <FeedbackToast error={error} notice={notice} onDismiss={() => { setError(''); setNotice('') }} />
    <button onClick={() => setRenders(renders + 1)}>Rerender {renders}</button>
    <button onClick={() => setNotice('Changed success')}>Change notice</button>
    <button onClick={() => setError('Changed error')}>Change error</button>
  </>
}

createRoot(document.getElementById('root')!).render(
  query.has('toast') ? <ToastFixture />
    : query.has('settings') ? <main><SettingsPage active status={status} /></main> : <App />,
)
