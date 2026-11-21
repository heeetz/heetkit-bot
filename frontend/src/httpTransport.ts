import { shell } from './i18n/app'
import { catalogFor } from './i18n/core'
import type { ActionResult, OptOutsResponse, CommandRestrictionsResponse, CommandSettingsMetadata, PythonApi } from './bridge'

const transport = () => catalogFor(shell).transport

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
  if (!browserConnectionSecure()) throw new Error(transport().insecure)
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
      if (token === sessionToken && token) clearSession('expired')
      throw new Error(transport().authRequired)
    }
    if (response.status >= 500) throw new Error(transport().serverUnavailable)
    if (response.status === 429) throw new Error(transport().tooManyRequests)
    if (response.status === 403) throw new Error(transport().refused)
    const responseLimit = (path === '/v1/ops/get_message_triggers' ? 3 : 2) * 1024 * 1024
    if (response.headers.get('Content-Type')?.split(';')[0].trim() !== 'application/json'
      || Number(response.headers.get('Content-Length')) > responseLimit) {
      throw new Error(transport().invalidResponse)
    }
    let data: unknown
    try {
      const raw = await response.text()
      if (raw.length > responseLimit) throw new Error()
      data = JSON.parse(raw)
    } catch {
      throw new Error(transport().invalidResponse)
    }
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      throw new Error(transport().invalidResponse)
    }
    if (!response.ok && (data as ActionResult).ok !== false) {
      throw new Error(transport().requestFailed)
    }
    return data as T
  } catch (error) {
    if (controller.signal.aborted || error instanceof TypeError) {
      throw new Error(transport().unreachable)
    }
    throw error
  } finally {
    window.clearTimeout(timer)
    activeRequests.delete(controller)
  }
}

export async function loginBrowserSession(adminToken: string): Promise<void> {
  if (!TOKEN_PATTERN.test(adminToken)) throw new Error(transport().invalidToken)
  const generation = sessionGeneration
  const result = await request<{ ok: boolean; token?: string; expires_in?: number }>('POST', '/v1/session', adminToken, {})
  if (generation !== sessionGeneration) return
  if (!result.ok || !result.token || !TOKEN_PATTERN.test(result.token)
    || !Number.isFinite(result.expires_in) || result.expires_in! <= 0 || result.expires_in! > 3600) {
    throw new Error(transport().signInFailed)
  }
  sessionToken = result.token
  sessionState = { authenticated: true, message: '' }
  expiryTimer = window.setTimeout(() => clearSession('expired'), result.expires_in! * 1000)
  for (const listener of listeners) listener()
}

export async function logoutBrowserSession(): Promise<void> {
  const token = sessionToken
  clearSession('signed_out')
  if (token) {
    try { await request('POST', '/v1/session/logout', token, {}) } catch { /* Local access is already cleared. */ }
  }
}

export async function browserRequest<T>(method: 'GET' | 'POST', path: string, payload?: object): Promise<T> {
  const token = sessionToken
  if (!token) throw new Error(transport().signInRequired)
  const result = await request<T>(method, path, token, payload)
  // A response that arrives after logout/expiry must not restore private page state.
  if (!sessionToken || sessionToken !== token) throw new Error(transport().sessionEnded)
  return result
}

// Every panel operation is one POST /v1/ops/<name> with named arguments.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const call = <T = any>(name: string, args: object = {}) => browserRequest<T>('POST', `/v1/ops/${name}`, args)
const unsupported = async (): Promise<never> => { throw new Error(transport().desktopOnly) }
const commandPayload = (command_name: string, enabled: boolean, per_user_seconds: number, global_seconds: number, permission: string, options?: CommandSettingsMetadata) => ({
  command_name, enabled, per_user_seconds, global_seconds, permission,
  ...(options ? { options: { primary_name: options.primary_name, aliases: options.aliases, display_name: options.display_name,
    burst_interval_ms: options.burst_interval_ms, burst_max_count: options.burst_max_count,
    entry_limit: options.entry_limit, chat_template: options.chat_template,
    send_as: options.send_as, stream_availability: options.stream_availability } } : {}),
})

// Fixed methods and named payloads only: no HTTP access to arbitrary bridge names.
export const browserApi: PythonApi = {
  get_desktop_startup: async () => ({ state: 'ready' }),
  // Server keeps the UI language in this browser (localStorage), not on the server.
  get_interface_language: async () => ({ ok: true }),
  set_interface_language: async () => ({ ok: true }),
  get_app_status: () => call('get_app_status'),
  get_about_info: () => call('get_about_info'),
  get_commands: () => call('get_commands'),
  get_custom_commands: () => call('get_custom_commands'),
  get_opt_outs: (query = '', offset = 0, limit = 50) => call('get_opt_outs', { query, offset, limit }),
  add_opt_out: (username) => call('add_opt_out', { username }),
  withdraw_opt_out: (twitch_user_id, confirmed) => call('withdraw_opt_out', { twitch_user_id, confirmed }),
  get_command_restrictions: () => call('get_command_restrictions'),
  save_command_restriction: (data) => call('save_command_restriction', { data }),
  remove_command_restriction: (restriction_id) => call('remove_command_restriction', { restriction_id }),
  get_message_triggers: () => call('get_message_triggers'),
  save_message_triggers: (triggers, revision) => call('save_message_triggers', { triggers, revision }),
  get_announcements: () => call('get_announcements'),
  save_announcements: (announcements) => call('save_announcements', { announcements }),
  get_filters: () => call('get_filters'),
  get_ai_status: () => call('get_ai_status'),
  get_analytics: (days = 7) => call('get_analytics', { days }),
  get_leaderboards: () => call('get_leaderboards', {}),
  save_leaderboard_settings: (channel_id, exclusions) => call('save_leaderboard_settings', { channel_id, exclusions }),
  configure_analytics: (enabled) => call('configure_analytics', { enabled }),
  configure_leaderboard_counting: (enabled) => call('configure_leaderboard_counting', { enabled }),
  reset_analytics: (confirmed) => call('reset_analytics', { confirmed }),
  get_ai_balance: (provider, refresh = false) => call('get_ai_balance', { provider, refresh }),
  get_ai_memory_limits: () => call('get_ai_memory_limits'),
  save_ai_memory_limits: (stored, context) => call('save_ai_memory_limits', { stored, context }),
  get_blocked_ai_users: () => call('get_blocked_ai_users'),
  block_ai_user: (username) => call('block_ai_user', { username }),
  unblock_ai_user: (username) => call('unblock_ai_user', { username }),
  get_personalities: () => call('get_personalities'),
  get_recent_logs: (after_id = 0, limit = 100, snapshot = false) => call('get_recent_logs', { after_id, limit, ...(snapshot ? { snapshot } : {}) }),
  get_recent_commands: () => call('get_recent_commands'),
  export_activity: unsupported,
  export_configuration: () => call('export_configuration'),
  preview_configuration_import: (archive_base64) => call('preview_configuration_import', { archive_base64 }),
  apply_configuration_import: (archive_base64, preview_token, confirmed) => call('apply_configuration_import', { archive_base64, preview_token, confirmed }),
  apply_command_settings: (...args) => call('apply_command_settings', commandPayload(...args)),
  save_command_settings: (...args) => call('save_command_settings', commandPayload(...args)),
  reset_command_settings: (command_name, preserve_enabled) => call('reset_command_settings', { command_name, preserve_enabled }),
  remove_builtin_command: (command_name) => call('remove_builtin_command', { command_name }),
  restore_builtin_command: (command_name) => call('restore_builtin_command', { command_name }),
  save_builtin_enabled: (command_name, enabled) => call('save_builtin_enabled', { command_name, enabled }),
  reset_all_builtin_commands: (preserve_enabled) => call('reset_all_builtin_commands', { preserve_enabled }),
  apply_command_responses: (name, responses) => call('apply_command_responses', { name, responses }),
  save_command_responses: (name, responses) => call('save_command_responses', { name, responses }),
  reset_command_responses: (name) => call('reset_command_responses', { name }),
  save_custom_command: (command) => call('save_custom_command', { command: {
    id: command.id, name: command.name, enabled: command.enabled, responses: command.responses,
    permission: command.permission, per_user_seconds: command.per_user_seconds, global_seconds: command.global_seconds,
    aliases: command.aliases, response_mode: command.response_mode, burst_count: command.burst_count,
    burst_allow_override: command.burst_allow_override, burst_interval_ms: command.burst_interval_ms,
    stream_availability: command.stream_availability, send_as: command.send_as,
  } }),
  delete_custom_command: (identifier) => call('delete_custom_command', { identifier }),
  apply_filters: (payload) => call('apply_filters', { payload: { words: payload.words, phrases: payload.phrases, patterns: payload.patterns } }),
  save_filters: (payload) => call('save_filters', { payload: { words: payload.words, phrases: payload.phrases, patterns: payload.patterns } }),
  test_filters: (text, source, payload = null) => call('test_filters', { text, source,
    payload: payload ? { words: payload.words, phrases: payload.phrases, patterns: payload.patterns } : null }),
  set_ai_enabled: (enabled) => call('set_ai_enabled', { enabled }),
  set_ai_memory_enabled: (enabled) => call('set_ai_memory_enabled', { enabled }),
  apply_personality: (personality, prompt) => call('apply_personality', { personality, prompt }),
  create_personality: (name, prompt) => call('create_personality', { name, prompt }),
  rename_personality: (personality, name) => call('rename_personality', { personality, name }),
  delete_personality: (personality) => call('delete_personality', { personality }),
  set_active_personality: (personality) => call('set_active_personality', { personality }),
  save_personality: (personality, prompt) => call('save_personality', { personality, prompt }),
  reset_personality: (personality) => call('reset_personality', { personality }),
  apply_profile_instructions: (prompt) => call('apply_profile_instructions', { prompt }),
  save_profile_instructions: (prompt) => call('save_profile_instructions', { prompt }),
  reset_profile_instructions: () => call('reset_profile_instructions'),
  get_ai_provider_settings: () => call('get_ai_provider_settings'),
  get_ai_setup: () => call('get_ai_setup'),
  save_ai_setup: (settings) => call('save_ai_setup', { settings }),
  get_setup_guide: () => call('get_setup_guide'),
  save_setup_guide: (dismissed, ai_skipped) => call('save_setup_guide', { dismissed, ai_skipped }),
  get_ai_language_settings: () => call('get_ai_language_settings'),
  update_ai_language_settings: (mode, allowed_languages, fallback_language) => call('update_ai_language_settings', { mode, allowed_languages, fallback_language }),
  discover_ai_models: (provider) => call('discover_ai_models', { provider }),
  start_bot: () => call('start_bot'),
  stop_bot: () => call('stop_bot'),
  check_for_updates: unsupported,
  prepare_desktop_update: unsupported,
  get_desktop_update_progress: unsupported,
  finish_desktop_update: unsupported,
  restart_desktop: unsupported,
  start_ai_playground: (prompt) => call('start_ai_playground', { prompt }),
  get_ai_playground_result: (request_id) => call('get_ai_playground_result', { request_id }),
  cancel_ai_playground: (request_id) => call('cancel_ai_playground', { request_id }),
  get_app_settings: unsupported, get_profile_info: unsupported, open_profile_folder: unsupported,
  update_app_settings: unsupported, get_twitch_settings: unsupported, update_twitch_settings: unsupported,
  save_twitch_preset: (preset_id, display_name, channel, channel_user_id) => call('save_twitch_preset', { preset_id, display_name, channel, channel_user_id }),
  delete_twitch_preset: (preset_id) => call('delete_twitch_preset', { preset_id }),
  switch_server_twitch_preset: (preset_id) => call('switch_server_twitch_preset', { preset_id }),
  reconnect_twitch: unsupported,
  get_credentials: unsupported,
  replace_credential: (name, value) => call('replace_credential', { name, value }),
  remove_credential: (name) => call('remove_credential', { name }),
  test_credential: (name) => call('test_credential', { name }),
  update_server_twitch_settings: (client_id, bot_username, bot_user_id, channel, channel_user_id) => call('update_server_twitch_settings', {
    client_id, bot_username, bot_user_id, channel, channel_user_id,
  }),
  begin_twitch_authorization: () => call('begin_twitch_authorization'),
  complete_twitch_authorization: (callback_url) => call('complete_twitch_authorization', { callback_url }),
  cancel_twitch_authorization: () => call('cancel_twitch_authorization'),
  open_external_link: async (destination) => {
    const links: Partial<Record<typeof destination, string>> = {
      repository: 'https://github.com/heeetz/heetkit-bot',
      license: 'https://github.com/heeetz/heetkit-bot/blob/main/LICENSE',
      third_party_notices: 'https://github.com/heeetz/heetkit-bot/blob/main/THIRD_PARTY_NOTICES.md',
      author_twitch: 'https://www.twitch.tv/heet_ok',
      releases: 'https://github.com/heeetz/heetkit-bot/releases',
    }
    const url = links[destination]
    if (!url) return unsupported()
    window.open(url, '_blank', 'noopener,noreferrer')
    return { ok: true }
  },
}
