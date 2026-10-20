import type { ActionResult, CommandSettingsMetadata, PythonApi } from './bridge'

type SessionState = { authenticated: boolean; message: string }
let sessionToken = ''
let sessionState: SessionState = { authenticated: false, message: '' }
let sessionGeneration = 0
let expiryTimer = 0
const listeners = new Set<() => void>()
const activeRequests = new Set<AbortController>()
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{43,128}$/

export const getBrowserSession = () => sessionState
export const subscribeBrowserSession = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function browserConnectionSecure(): boolean {
  const hostname = location.hostname
  const ipv4Loopback = /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(hostname)
    && hostname.split('.').every((part) => Number(part) <= 255)
  return location.protocol === 'https:' || (location.protocol === 'http:'
    && (ipv4Loopback || ['localhost', '[::1]', '::1'].includes(hostname)))
}

function clearSession(message = '') {
  sessionToken = ''
  sessionGeneration += 1
  window.clearTimeout(expiryTimer)
  for (const controller of activeRequests) controller.abort()
  sessionState = { authenticated: false, message }
  for (const listener of listeners) listener()
}

async function request<T>(method: 'GET' | 'POST', path: string, token: string, payload?: object): Promise<T> {
  if (!browserConnectionSecure()) throw new Error('Open this panel using HTTPS or a loopback address.')
  const controller = new AbortController()
  activeRequests.add(controller)
  const timer = window.setTimeout(() => controller.abort(), 30000)
  try {
    const response = await fetch(path, {
      method, credentials: 'omit', redirect: 'error', cache: 'no-store', referrerPolicy: 'no-referrer',
      signal: controller.signal,
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}`,
        ...(method === 'POST' ? { 'Content-Type': 'application/json' } : {}) },
      ...(method === 'POST' ? { body: JSON.stringify(payload ?? {}) } : {}),
    })
    if (response.status === 401) {
      if (token === sessionToken && token) clearSession('Your session expired. Sign in again.')
      throw new Error('Authentication required. Check the token and sign in again.')
    }
    if (response.status >= 500) throw new Error('The server is unavailable. Check the connection and retry.')
    if (response.status === 429) throw new Error('Too many requests. Wait a moment and retry.')
    if (response.status === 403) throw new Error('The server refused this connection. Check the server access settings.')
    if (response.headers.get('Content-Type')?.split(';')[0].trim() !== 'application/json'
      || Number(response.headers.get('Content-Length')) > 2 * 1024 * 1024) {
      throw new Error('The server returned an invalid response. Retry after checking the server.')
    }
    let data: unknown
    try {
      const raw = await response.text()
      if (raw.length > 2 * 1024 * 1024) throw new Error()
      data = JSON.parse(raw)
    } catch {
      throw new Error('The server returned an invalid response. Retry after checking the server.')
    }
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      throw new Error('The server returned an invalid response. Retry after checking the server.')
    }
    if (!response.ok && (data as ActionResult).ok !== false) {
      throw new Error('The request failed. Check the server and retry.')
    }
    return data as T
  } catch (error) {
    if (controller.signal.aborted || error instanceof TypeError) {
      throw new Error('Could not reach the server. Check the connection and retry.')
    }
    throw error
  } finally {
    window.clearTimeout(timer)
    activeRequests.delete(controller)
  }
}

export async function loginBrowserSession(adminToken: string): Promise<void> {
  if (!TOKEN_PATTERN.test(adminToken)) throw new Error('Enter the configured administrator token (43–128 URL-safe characters).')
  const generation = sessionGeneration
  const result = await request<{ ok: boolean; token?: string; expires_in?: number }>('POST', '/v1/session', adminToken, {})
  if (generation !== sessionGeneration) return
  if (!result.ok || !result.token || !TOKEN_PATTERN.test(result.token)
    || !Number.isFinite(result.expires_in) || result.expires_in! <= 0 || result.expires_in! > 3600) {
    throw new Error('Sign in failed. Check the server and retry.')
  }
  sessionToken = result.token
  sessionState = { authenticated: true, message: '' }
  expiryTimer = window.setTimeout(() => clearSession('Your session expired. Sign in again.'), result.expires_in! * 1000)
  for (const listener of listeners) listener()
}

export async function logoutBrowserSession(): Promise<void> {
  const token = sessionToken
  clearSession('Signed out.')
  if (token) {
    try { await request('POST', '/v1/session/logout', token, {}) } catch { /* Local access is already cleared. */ }
  }
}

export async function browserRequest<T>(method: 'GET' | 'POST', path: string, payload?: object): Promise<T> {
  const token = sessionToken
  if (!token) throw new Error('Sign in to manage this server.')
  const result = await request<T>(method, path, token, payload)
  // A response that arrives after logout/expiry must not restore private page state.
  if (!sessionToken || sessionToken !== token) throw new Error('Your session ended. Sign in again.')
  return result
}

const read = <T>(path: string) => browserRequest<T>('GET', path)
const write = <T = ActionResult>(path: string, payload: object = {}) => browserRequest<T>('POST', path, payload)
const unsupported = async (): Promise<never> => { throw new Error('This action is available in the desktop application only. Configure this setting on the server.') }
const commandPayload = (command_name: string, enabled: boolean, per_user_seconds: number, global_seconds: number, permission: string, options?: CommandSettingsMetadata) => ({
  command_name, enabled, per_user_seconds, global_seconds, permission,
  ...(options ? { options: { aliases: options.aliases, display_name: options.display_name,
    burst_interval_ms: options.burst_interval_ms, burst_max_count: options.burst_max_count } } : {}),
})

// Fixed methods and named payloads only: no HTTP access to arbitrary bridge names.
export const browserApi: PythonApi = {
  get_app_status: () => read('/v1/status'),
  get_about_info: () => read('/v1/about'),
  get_commands: () => read('/v1/commands'),
  get_custom_commands: () => read('/v1/custom-commands'),
  get_filters: () => read('/v1/filters'),
  get_ai_status: () => read('/v1/ai'),
  get_blocked_ai_users: () => read('/v1/blocked-users'),
  block_ai_user: async (username) => {
    const result = await write('/v1/blocked-users/block', { username })
    return result.ok ? read('/v1/blocked-users') : result
  },
  unblock_ai_user: (username) => write('/v1/blocked-users/unblock', { username }),
  get_personalities: () => read('/v1/personalities'),
  get_recent_logs: (after_id = 0, limit = 100) => write('/v1/logs/recent', { after_id, limit }),
  export_configuration: () => write('/v1/configuration/export'),
  preview_configuration_import: (archive_base64) => write('/v1/configuration/preview', { archive_base64 }),
  apply_configuration_import: (archive_base64, preview_token, confirmed) => write('/v1/configuration/import', { archive_base64, preview_token, confirmed }),
  apply_command_settings: (...args) => write('/v1/commands/apply', commandPayload(...args)),
  save_command_settings: (...args) => write('/v1/commands/save', commandPayload(...args)),
  reset_command_settings: (command_name) => write('/v1/commands/reset', { command_name }),
  remove_builtin_command: (command_name) => write('/v1/commands/remove', { command_name }),
  restore_builtin_command: (command_name) => write('/v1/commands/restore', { command_name }),
  reset_all_builtin_commands: () => write('/v1/commands/reset-all'),
  apply_command_responses: (name, responses) => write('/v1/commands/responses/apply', { name, responses }),
  save_command_responses: (name, responses) => write('/v1/commands/responses/save', { name, responses }),
  reset_command_responses: (name) => write('/v1/commands/responses/reset', { name }),
  save_custom_command: (command) => write('/v1/custom-commands/save', { command: {
    id: command.id, name: command.name, enabled: command.enabled, responses: command.responses,
    permission: command.permission, per_user_seconds: command.per_user_seconds, global_seconds: command.global_seconds,
    aliases: command.aliases, response_mode: command.response_mode, burst_count: command.burst_count,
    burst_allow_override: command.burst_allow_override, burst_interval_ms: command.burst_interval_ms,
  } }),
  delete_custom_command: (identifier) => write('/v1/custom-commands/delete', { identifier }),
  apply_filters: (payload) => write('/v1/filters/apply', { payload: { words: payload.words, phrases: payload.phrases, patterns: payload.patterns } }),
  save_filters: (payload) => write('/v1/filters/save', { payload: { words: payload.words, phrases: payload.phrases, patterns: payload.patterns } }),
  test_filters: (text, source, payload = null) => write('/v1/filters/test', { text, source,
    payload: payload ? { words: payload.words, phrases: payload.phrases, patterns: payload.patterns } : null }),
  set_ai_enabled: (enabled) => write('/v1/ai/enabled', { enabled }),
  set_ai_memory_enabled: (enabled) => write('/v1/ai/memory', { enabled }),
  apply_personality: (personality, prompt) => write('/v1/personalities/apply', { personality, prompt }),
  create_personality: (name, prompt) => write('/v1/personalities/create', { name, prompt }),
  rename_personality: (personality, name) => write('/v1/personalities/rename', { personality, name }),
  delete_personality: (personality) => write('/v1/personalities/delete', { personality }),
  set_active_personality: (personality) => write('/v1/personalities/activate', { personality }),
  save_personality: (personality, prompt) => write('/v1/personalities/save', { personality, prompt }),
  reset_personality: (personality) => write('/v1/personalities/reset', { personality }),
  apply_profile_instructions: (prompt) => write('/v1/ai/instructions/apply', { prompt }),
  save_profile_instructions: (prompt) => write('/v1/ai/instructions/save', { prompt }),
  reset_profile_instructions: () => write('/v1/ai/instructions/reset'),
  get_ai_provider_settings: () => read('/v1/ai/models'),
  update_ai_provider_settings: (selected_model, fallback_model) => write('/v1/ai/models', { selected_model, fallback_model }),
  get_ai_language_settings: () => read('/v1/ai/language'),
  update_ai_language_settings: (mode, allowed_languages, fallback_language) => write('/v1/ai/language', { mode, allowed_languages, fallback_language }),
  discover_gemini_models: () => write('/v1/ai/models/discover'),
  start_bot: () => write('/v1/bot/start'),
  stop_bot: () => write('/v1/bot/stop'),
  check_for_updates: unsupported, start_ai_playground: unsupported,
  get_ai_playground_result: unsupported, cancel_ai_playground: unsupported,
  get_app_settings: unsupported, get_profile_info: unsupported, open_profile_folder: unsupported,
  update_app_settings: unsupported, get_twitch_settings: unsupported, update_twitch_settings: unsupported,
  save_twitch_preset: unsupported, delete_twitch_preset: unsupported, reconnect_twitch: unsupported,
  get_credentials: unsupported, replace_credential: unsupported, remove_credential: unsupported, test_credential: unsupported,
  open_external_link: async (destination) => {
    const links: Partial<Record<typeof destination, string>> = {
      repository: 'https://github.com/heeetz/twitch-bot',
      license: 'https://github.com/heeetz/twitch-bot/blob/main/LICENSE',
      third_party_notices: 'https://github.com/heeetz/twitch-bot/blob/main/THIRD_PARTY_NOTICES.md',
      author_twitch: 'https://www.twitch.tv/heet_ok',
      releases: 'https://github.com/heeetz/twitch-bot/releases',
    }
    const url = links[destination]
    if (!url) return unsupported()
    window.open(url, '_blank', 'noopener,noreferrer')
    return { ok: true }
  },
}
