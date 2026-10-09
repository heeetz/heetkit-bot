import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import App from '../src/App'
import AboutPage from '../src/pages/AboutPage'
import FeedbackToast from '../src/components/FeedbackToast'
import SettingsPage from '../src/pages/SettingsPage'
import type {
  AILanguageInfo,
  AILanguageSettings,
  AppStatus,
  PersonalitiesResponse,
  TwitchConnectionSettings,
  waitForBridge,
} from '../src/bridge'

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
let aiStatus = {
  enabled: false, available: false, memory_enabled: false,
  active_personality: 'neutral', available_personalities: ['neutral'], model: '',
}
let personalities: PersonalitiesResponse = {
  active_personality: 'neutral',
  active_personality_saved: true,
  personalities: [{
    name: 'neutral', prompt: 'Synthetic neutral prompt.', built_in_prompt: 'Synthetic neutral prompt.',
    is_builtin: true, prompt_saved: true, has_saved_override: false,
  }],
  profile_instructions: '', profile_instructions_saved: true,
  protected_shared_instructions: 'Synthetic shared instructions.',
}
const languageCatalogue: AILanguageInfo[] = [
  { code: 'en', label: 'English' },
  { code: 'uk', label: 'Ukrainian' },
  { code: 'ru', label: 'Russian' },
  { code: 'de', label: 'German' },
  { code: 'fr', label: 'French' },
]
let languageSettings: AILanguageSettings = {
  mode: 'auto', allowed_languages: ['en', 'uk', 'ru'], fallback_language: 'en',
}
let activeLanguagePolicy = 'Auto — match the incoming language without restrictions.'
const credentials = [
  { name: 'twitch_client_secret', label: 'Twitch client secret', configured, source: configured ? 'credential_store' : 'missing', secure_storage_available: true },
  { name: 'gemini_api_key', label: 'Gemini API key', configured: false, source: 'missing', secure_storage_available: true },
]
const opened: string[] = []
const aiCalls: unknown[][] = []
const playgroundCalls: unknown[][] = []
let playgroundId = 0
let playgroundCancelled = false
let playgroundStartedAt = 0
const updateCalls: unknown[][] = []
Object.assign(window, { opened, aiCalls, updateCalls, playgroundCalls })
window.pywebview = { api: {
  get_app_status: async () => status,
  get_commands: async () => ({ command_prefix: '!', permissions: ['USER'], commands: [] }),
  get_custom_commands: async () => ({ command_prefix: '!', permissions: ['USER'], variables: ['sender'], commands: [] }),
  get_filters: async () => ({
    words: { rules: [], defaults: [] },
    phrases: { rules: [], defaults: [] },
    patterns: { rules: [], defaults: [] },
  }),
  get_recent_logs: async () => ({ entries: [] }),
  get_ai_status: async () => aiStatus,
  start_ai_playground: async (prompt: string) => {
    playgroundCalls.push(['start', prompt])
    if (query.has('playgroundStartDelay')) await new Promise((resolve) => window.setTimeout(resolve, 350))
    if (query.has('playgroundStartError')) return { ok: false, error: 'A Playground request is already running.' }
    playgroundCancelled = false
    playgroundStartedAt = Date.now()
    return { ok: true, request_id: String(++playgroundId), status: 'pending' }
  },
  get_ai_playground_result: async (requestId: string) => {
    if (query.has('playgroundReadError')) throw new Error('Read failed')
    if (playgroundCancelled) return { ok: true, request_id: requestId, status: 'cancelled' }
    if (query.has('playgroundWait') && Date.now() - playgroundStartedAt < 60000) return { ok: true, status: 'pending' }
    return {
      ok: true, request_id: requestId, status: query.get('playgroundStatus') ?? 'success',
      text: 'Synthetic response <strong>plain text</strong>.',
      moderation_source: query.get('playgroundSource'), matched_category: 'phrases', matched_rule: 'synthetic rule',
    }
  },
  cancel_ai_playground: async (requestId: string) => {
    playgroundCalls.push(['cancel', requestId])
    if (query.has('playgroundCancelError') && playgroundCalls.filter((call) => call[0] === 'cancel').length === 1) return { ok: false }
    playgroundCancelled = true
    return { ok: true, status: 'pending' }
  },
  get_personalities: async () => personalities,
  get_app_settings: async () => ({ ok: true, settings: {
    auto_start_bot: authRequired, start_minimized: false, minimize_to_tray: false,
    close_to_tray: false, tray_available: false,
  } }),
  get_profile_info: async () => {
    if (query.has('profileLocationError')) throw new Error('The profile location is unavailable.')
    return { path: query.get('profilePath') ?? 'C:\\Synthetic profiles\\HeetKit' }
  },
  open_profile_folder: async () => {
    opened.push('profile_folder')
    return query.has('folderOpenError') ? { ok: false, error: 'Could not open the profile folder in the system file manager.' } : { ok: true }
  },
  get_twitch_settings: async () => ({ ok: true, settings: twitch }),
  get_credentials: async () => ({ ok: true, credentials }),
  get_ai_provider_settings: async () => ({ ok: true, settings: {
    provider: 'Gemini', selected_model: '', fallback_model: '', presets: [], credential: credentials[1],
  } }),
  get_ai_language_settings: async () => {
    if (query.has('languageLoadError')) return { ok: false, error: 'AI language settings are unavailable.' }
    return { ok: true, settings: languageSettings, languages: languageCatalogue, active_policy: activeLanguagePolicy }
  },
  update_ai_language_settings: async (mode: string, allowedLanguages: string[], fallbackLanguage: string) => {
    aiCalls.push(['update_ai_language_settings', mode, allowedLanguages, fallbackLanguage])
    if (query.has('languageSaveError')) return { ok: false, error: 'AI language settings could not be saved.' }
    if (allowedLanguages.length === 0) return { ok: false, error: 'At least one allowed language is required.' }
    if (!allowedLanguages.includes(fallbackLanguage)) return { ok: false, error: 'Fallback language must be allowed.' }
    languageSettings = {
      mode: mode as AILanguageSettings['mode'],
      allowed_languages: [...allowedLanguages],
      fallback_language: fallbackLanguage,
    }
    const labels = allowedLanguages.map((code) => languageCatalogue.find((language) => language.code === code)?.label ?? code).join(', ')
    activeLanguagePolicy = mode === 'auto'
      ? 'Auto — match the incoming language without restrictions.'
      : `Limited — ${labels}; fallback ${languageCatalogue.find((language) => language.code === fallbackLanguage)?.label ?? fallbackLanguage}.`
    personalities = {
      ...personalities,
      protected_shared_instructions: `Synthetic shared instructions. Active language policy: ${activeLanguagePolicy}`,
    }
    return { ok: true }
  },
  get_about_info: async () => ({
    application_name: 'HeetKit', version: '0.1.0', author: 'heeetz', repository_url: 'https://github.com/heeetz/twitch-bot',
    application_subtitle: 'Desktop control center for Twitch chat', author_twitch: '@heet_ok',
    discord_contact: 'de.tected', license_name: 'Apache-2.0', license_url: 'https://www.apache.org/licenses/LICENSE-2.0',
    third_party_notices_url: 'https://github.com/heeetz/twitch-bot/blob/main/THIRD_PARTY_NOTICES.md',
  }),
  check_for_updates: async () => {
    updateCalls.push(['check_for_updates'])
    const sequence = query.get('updateSequence')?.split(',') ?? []
    const outcome = sequence[updateCalls.length - 1] ?? ''
    if (query.has('updateDelay')) {
      await new Promise((resolve) => window.setTimeout(resolve, Number(query.get('updateDelay')) || 250))
    }
    if (outcome === 'reject' || query.has('updateReject') || query.has('updateRejection')) {
      throw new Error('Update service is unavailable.')
    }
    if (outcome === 'error' || query.has('updateError') || query.has('updateFailure')) {
      return { ok: false, error: 'Could not reach the update service.', current_version: '0.1.0' }
    }
    const newer = outcome === 'newer' || query.has('updateNewer') || query.has('updateAvailable')
    return {
      ok: true,
      current_version: '0.1.0',
      latest_version: newer ? '0.2.0' : '0.1.0',
      update_available: newer,
      release_name: newer ? 'HeetKit 0.2.0' : 'HeetKit 0.1.0',
      release_notes: query.has('notesMarkup')
        ? 'Fixes <strong>markup</strong> & **formatting**.'
        : 'Bug fixes and reliability improvements.',
      published_at: '2026-10-09',
    }
  },
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
  create_personality: async (name: string, prompt: string) => {
    if (query.has('createPersonalityError')) return { ok: false, error: 'Personality could not be created.' }
    const normalizedName = name.trim()
    personalities = {
      ...personalities,
      personalities: [...personalities.personalities, {
        name: normalizedName, prompt, built_in_prompt: '', is_builtin: false,
        prompt_saved: true, has_saved_override: true,
      }],
    }
    aiStatus = { ...aiStatus, available_personalities: personalities.personalities.map((item) => item.name) }
    aiCalls.push(['create_personality', normalizedName, prompt])
    return { ok: true, name: normalizedName }
  },
  rename_personality: async (oldName: string, newName: string) => {
    if (query.has('renamePersonalityError')) return { ok: false, error: 'Personality could not be renamed.' }
    const normalizedName = newName.trim()
    personalities = {
      ...personalities,
      active_personality: personalities.active_personality === oldName ? normalizedName : personalities.active_personality,
      personalities: personalities.personalities.map((item) => item.name === oldName ? { ...item, name: normalizedName } : item),
    }
    aiStatus = {
      ...aiStatus,
      active_personality: aiStatus.active_personality === oldName ? normalizedName : aiStatus.active_personality,
      available_personalities: personalities.personalities.map((item) => item.name),
    }
    aiCalls.push(['rename_personality', oldName, normalizedName])
    return { ok: true, name: normalizedName }
  },
  delete_personality: async (name: string) => {
    if (query.has('deletePersonalityError')) return { ok: false, error: 'Personality could not be deleted.' }
    personalities = {
      ...personalities,
      active_personality: personalities.active_personality === name ? 'neutral' : personalities.active_personality,
      personalities: personalities.personalities.filter((item) => item.name !== name),
    }
    aiStatus = { ...aiStatus, active_personality: personalities.active_personality, available_personalities: personalities.personalities.map((item) => item.name) }
    aiCalls.push(['delete_personality', name])
    return { ok: true }
  },
  set_active_personality: async (name: string) => {
    if (query.has('activePersonalityError')) return { ok: false, error: 'Personality could not be activated.' }
    personalities = { ...personalities, active_personality: name, active_personality_saved: true }
    aiStatus = { ...aiStatus, active_personality: name }
    aiCalls.push(['set_active_personality', name])
    return { ok: true }
  },
  save_personality: async (name: string, prompt: string) => {
    if (query.has('savePersonalityError')) return { ok: false, error: 'Personality could not be saved.' }
    aiCalls.push(['save_personality', name, prompt])
    personalities = {
      ...personalities,
      personalities: personalities.personalities.map((item) => item.name === name ? {
        ...item, prompt, prompt_saved: true, has_saved_override: !item.is_builtin || prompt !== item.built_in_prompt,
      } : item),
    }
    return { ok: true }
  },
  reset_personality: async (name: string) => {
    if (query.has('resetPersonalityError')) return { ok: false, error: 'Personality could not be reset.' }
    aiCalls.push(['reset_personality', name])
    personalities = {
      ...personalities,
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
    : query.has('about') ? <AboutPage />
    : query.has('settings') ? <main><SettingsPage active status={status} /></main> : <App />,
)
