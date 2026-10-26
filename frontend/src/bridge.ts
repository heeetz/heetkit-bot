export interface AppStatus {
  running: boolean
  twitch_connected: boolean
  twitch_connection_state: TwitchConnectionState
  uptime_seconds: number
  channel: string
  account: string
  operation?: BrowserOperation
}

export type BrowserOperationMode = 'always_on' | 'stream_only' | 'manual' | 'disabled'
export type BrowserStreamStatus = 'live' | 'offline' | 'unknown'

export interface BrowserOperation {
  mode: BrowserOperationMode
  desired_running: boolean
  pending: boolean
  stream_status: BrowserStreamStatus
  last_known_stream_status: 'live' | 'offline' | null
  last_checked_at: string | null
  error: null | 'connection_failed'
}

export type TwitchConnectionState =
  | 'stopped'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'auth_required'
  | 'failed'

export function twitchConnectionLabel(state: TwitchConnectionState): string {
  switch (state) {
    case 'stopped': return 'Stopped'
    case 'connecting': return 'Connecting'
    case 'connected': return 'Connected'
    case 'reconnecting': return 'Reconnecting'
    case 'auth_required': return 'Authorization required'
    case 'failed': return 'Connection failed'
  }
}

export function twitchAuthorizationLabel(state: TwitchConnectionState, tokenCacheAvailable: boolean): string {
  if (state === 'connected') return 'Verified for this connection'
  if (state === 'auth_required') return 'Required'
  return tokenCacheAvailable ? 'Not verified (token cache found)' : 'Not verified'
}

export interface CommandInfo {
  name: string
  aliases: string[]
  display_name?: string
  removed?: boolean
  burst_interval_ms?: number
  burst_max_count?: number
  minimum_permission?: string
  identity_editable?: boolean
  help_text?: string
  enabled: boolean
  available: boolean
  unavailable_reason: string | null
  response_pool: {
    responses: string[]
    defaults: string[]
    saved: boolean
    has_saved_override: boolean
    response_mode: 'single' | 'random'
    max_responses: number
  } | null
  permission: string
  stream_availability?: StreamAvailability
  cooldown: {
    per_user_seconds: number
    global_seconds: number
  }
  hidden: boolean
  default_settings: CommandSettings
  saved: boolean
  has_saved_override: boolean
}

export interface CommandSettings {
  enabled: boolean
  removed?: boolean
  aliases?: string[]
  display_name?: string
  burst_interval_ms?: number
  burst_max_count?: number
  permission: string
  stream_availability?: StreamAvailability
  cooldown: {
    per_user_seconds: number
    global_seconds: number
  }
}

export interface CommandSettingsMetadata {
  aliases?: string[]
  display_name?: string
  burst_interval_ms?: number
  burst_max_count?: number
  stream_availability?: StreamAvailability
}

export interface CommandsResponse {
  command_prefix: string
  permissions: string[]
  commands: CommandInfo[]
}

export type CustomResponseMode = 'single' | 'random' | 'burst'

export interface CustomCommandInput {
  id?: string | null
  name: string
  enabled: boolean
  responses: string[]
  permission: string
  per_user_seconds: number
  global_seconds: number
  aliases: string[]
  stream_availability?: StreamAvailability
  response_mode?: CustomResponseMode
  burst_count?: number
  burst_allow_override?: boolean
  burst_interval_ms?: number
}

export interface CustomCommandInfo extends CustomCommandInput {
  id: string
  response_mode: CustomResponseMode
}

export type StreamAvailability = 'anytime' | 'live_only' | 'offline_only'

export interface AnnouncementInput {
  id?: string | null
  name: string
  enabled: boolean
  messages: string[]
  message_mode: 'single' | 'random'
  delivery_mode?: 'regular' | 'highlighted'
  interval_seconds: number
  min_messages: number
  stream_availability: StreamAvailability
}

export interface AnnouncementInfo extends AnnouncementInput {
  id: string
  status: {
    next_run_at: string | null
    last_sent_at: string | null
    last_outcome: string | null
    eligible_messages: number
  }
}

export interface AnnouncementsResponse {
  ok: boolean
  announcements: AnnouncementInfo[]
  error?: string
}

export interface CustomCommandsResponse {
  command_prefix: string
  permissions: string[]
  variables: string[]
  commands: CustomCommandInfo[]
}

export type FilterCategoryName = 'words' | 'phrases' | 'patterns'

export interface FilterEntry {
  value: string
  origin: 'default' | 'local'
  valid: boolean
  error?: string | null
}

export interface FilterCategory {
  rules: FilterEntry[]
  defaults: string[]
  load_error?: string | null
}

export interface FiltersResponse {
  words: FilterCategory
  phrases: FilterCategory
  patterns: FilterCategory
}

export interface FilterInput {
  words: string[]
  phrases: string[]
  patterns: string[]
}

export interface FilterActionResult extends ActionResult {
  invalid_rule?: { category: FilterCategoryName; index: number }
}

export type FilterTestResult =
  | (FilterActionResult & {
    ok: true
    source: 'active' | 'draft'
    decision: 'ALLOW' | 'BLOCK'
    category: FilterCategoryName | null
    rule: string | null
    timed_out: boolean
  })
  | (FilterActionResult & {
    ok: false
    error: string
  })

export interface AIStatus {
  enabled: boolean
  available: boolean
  memory_enabled: boolean
  active_personality: string
  available_personalities: string[]
  model: string
}

export interface BlockedAIUser {
  username: string
  has_user_id: boolean
}

export interface AIUserBlocksResponse extends ActionResult {
  users?: BlockedAIUser[]
}

export interface PersonalityInfo {
  name: string
  prompt: string
  built_in_prompt: string
  is_builtin: boolean
  prompt_saved: boolean
  has_saved_override: boolean
}

export interface PersonalitiesResponse {
  active_personality: string
  active_personality_saved: boolean
  personalities: PersonalityInfo[]
  profile_instructions: string
  profile_instructions_saved: boolean
  protected_shared_instructions: string
}

export interface AppSettings {
  auto_start_bot: boolean
  start_minimized: boolean
  minimize_to_tray: boolean
  close_to_tray: boolean
  tray_available: boolean
}

export interface AppSettingsResponse extends ActionResult {
  settings?: AppSettings
}

export interface ProfileInfo {
  path: string
}

export interface ConfigurationExportResponse extends ActionResult {
  filename?: string
  archive_base64?: string
  saved?: boolean
  cancelled?: boolean
}

export interface ConfigurationImportSection {
  name: string
  incoming_count: number
  current_count: number
  details?: string[]
}

export interface ConfigurationImportPreviewResponse extends ActionResult {
  preview_token?: string
  application_version?: string
  format_version?: number
  sections?: ConfigurationImportSection[]
  effects?: string[]
  preserved?: string[]
}

export interface ConfigurationImportResponse extends ActionResult {
  effects?: string[]
}

export interface TwitchConnectionSettings {
  target_channel: string
  target_channel_user_id: string
  active_channel: string
  active_channel_user_id: string
  presets: TwitchConnectionPreset[]
  selected_preset_id: string | null
  active_preset_id: string | null
  requires_reconnect: boolean
  bot_username: string
  bot_user_id: string
  client_id: string
  requires_restart: boolean
  running: boolean
  connected: boolean
  oauth_token_available: boolean
  oauth_callback_url: string
  management_url?: string
  authorization_mode?: 'paste' | 'redirect'
  authorization_attempt?: 'idle' | 'pending' | 'completed' | 'failed' | 'expired' | 'cancelled'
  has_local_override: boolean
  authorization_status?: 'missing' | 'not_verified' | 'verified' | 'validation_failed'
  authorized_account?: string | null
  setup_complete?: boolean
}

export interface TwitchConnectionPreset {
  id: string
  display_name: string
  target_channel: string
  target_channel_user_id: string
}

export interface TwitchSettingsResponse extends ActionResult {
  settings?: TwitchConnectionSettings
}

export type CredentialName = 'gemini_api_key' | 'deepseek_api_key' | 'openai_api_key' | 'twitch_client_secret'
export type AIProviderId = 'gemini' | 'deepseek' | 'openai'

export interface CredentialInfo {
  name: CredentialName
  label: string
  configured: boolean
  source: 'credential_store' | 'server_file' | 'environment' | 'missing'
  managed?: boolean
  validation_status?: 'not_tested' | 'valid' | 'validation_failed'
  secure_storage_available: boolean
}

export interface CredentialsResponse extends ActionResult {
  credentials?: CredentialInfo[]
}

export interface GeminiModelPreset {
  id: string
  label: string
  description: string
}

export interface AIProviderSettings {
  provider: string
  provider_id?: AIProviderId
  selected_model: string
  fallback_model: string
  presets: GeminiModelPreset[]
  credential: CredentialInfo | null
}

export interface AIProviderSettingsResponse extends ActionResult {
  settings?: AIProviderSettings
  providers?: { id: AIProviderId; label: string }[]
}

export interface AIModelSelection {
  provider: AIProviderId
  model: string
  thinking: string
  search: boolean
}

export interface AISetupSettings {
  primary: AIModelSelection
  fallback: AIModelSelection | null
  cross_provider_acknowledged: boolean
  max_question_length: number
  max_answer_length: number
  shared_instructions: string | null
  provider_drafts: Partial<Record<string, AIModelSelection>>
}

export interface AIModelCapabilities {
  known: boolean
  thinking_options: { value: string; label: string }[]
  search_supported: boolean
  search_reason: string
  attribution_required: boolean
}

export interface AISetupResponse extends ActionResult {
  settings?: AISetupSettings
  providers?: { id: AIProviderId; label: string; credential: CredentialInfo | null; models: string[]; selected_model: string; fallback_model: string }[]
  capabilities?: Record<AIProviderId, Record<string, AIModelCapabilities>>
  default_shared_instructions?: string
  retained_restrictions?: string
}

export type AILanguageMode = 'auto' | 'limited'

export interface AILanguageSettings {
  mode: AILanguageMode
  allowed_languages: string[]
  fallback_language: string
}

export interface AILanguageInfo {
  code: string
  label: string
}

export interface AILanguageSettingsResponse extends ActionResult {
  settings?: AILanguageSettings
  languages?: AILanguageInfo[]
  active_policy?: string
}

export interface AboutInfo {
  application_name: string
  application_subtitle: string
  version: string
  author: string
  author_twitch: string
  repository_url: string
  discord_contact: string
  license_name: string
  license_url: string
  third_party_notices_url: string
}

export interface ModelDiscoveryResponse extends ActionResult {
  provider_id?: AIProviderId
  models?: string[]
}

export interface UpdateCheckResponse extends ActionResult {
  current_version: string
  latest_version?: string
  update_available?: boolean
  release_name?: string
  release_notes?: string
  published_at?: string
}

export interface LogEntry {
  id: number
  timestamp: string
  level: string
  source: string
  message: string
  event_kind: string | null
  context: Record<string, string | number | boolean>
  text?: string | null
  text_truncated?: boolean
}

export interface LogsResponse {
  entries: LogEntry[]
  next_after_id?: number
}

export interface AIPlaygroundResult {
  ok: boolean
  request_id?: string
  status?: 'pending' | 'success' | 'input_blocked' | 'output_blocked' | 'provider_unavailable' | 'api_error' | 'timeout' | 'cancelled' | 'model_unavailable' | 'configuration_error' | 'search_error' | 'search_unavailable' | 'attribution_unavailable' | 'question_too_long'
  text?: string
  moderation_source?: 'editable_filter' | 'filter_timeout' | 'protected_policy' | null
  matched_category?: string | null
  matched_rule?: string | null
  generation?: {
    provider: string
    model: string
    thinking: string
    fallback_used: boolean
    search_enabled: boolean
    search_requested: boolean
    search_used: boolean
    input_tokens?: number | null
    output_tokens?: number | null
  } | null
  error?: string
}

export interface PythonApi {
  get_app_status(): Promise<AppStatus>
  get_about_info(): Promise<AboutInfo>
  check_for_updates(): Promise<UpdateCheckResponse>
  get_commands(): Promise<CommandsResponse>
  get_custom_commands(): Promise<CustomCommandsResponse>
  get_announcements(): Promise<AnnouncementsResponse>
  save_announcements(announcements: AnnouncementInput[]): Promise<ActionResult>
  get_filters(): Promise<FiltersResponse>
  get_ai_status(): Promise<AIStatus>
  get_blocked_ai_users(): Promise<AIUserBlocksResponse>
  block_ai_user(username: string): Promise<AIUserBlocksResponse>
  unblock_ai_user(username: string): Promise<AIUserBlocksResponse>
  start_ai_playground(prompt: string): Promise<AIPlaygroundResult>
  get_ai_playground_result(requestId: string): Promise<AIPlaygroundResult>
  cancel_ai_playground(requestId: string): Promise<AIPlaygroundResult>
  get_personalities(): Promise<PersonalitiesResponse>
  get_recent_logs(after_id?: number, limit?: number): Promise<LogsResponse>
  export_activity(entryIds: number[]): Promise<ActionResult & { saved?: boolean; cancelled?: boolean }>
  apply_command_settings(commandName: string, enabled: boolean, perUserSeconds: number, globalSeconds: number, permission: string, metadata?: CommandSettingsMetadata): Promise<ActionResult>
  save_command_settings(commandName: string, enabled: boolean, perUserSeconds: number, globalSeconds: number, permission: string, metadata?: CommandSettingsMetadata): Promise<ActionResult>
  reset_command_settings(commandName: string): Promise<ActionResult>
  remove_builtin_command(commandName: string): Promise<ActionResult>
  restore_builtin_command(commandName: string): Promise<ActionResult>
  reset_all_builtin_commands(): Promise<ActionResult>
  apply_command_responses(commandName: string, responses: string[]): Promise<ActionResult>
  save_command_responses(commandName: string, responses: string[]): Promise<ActionResult>
  reset_command_responses(commandName: string): Promise<ActionResult>
  save_custom_command(command: CustomCommandInput): Promise<ActionResult>
  delete_custom_command(id: string): Promise<ActionResult>
  apply_filters(payload: FilterInput): Promise<FilterActionResult>
  save_filters(payload: FilterInput): Promise<FilterActionResult>
  test_filters(text: string, source: 'active' | 'draft', payload?: FilterInput | null): Promise<FilterTestResult>
  set_ai_enabled(enabled: boolean): Promise<ActionResult>
  set_ai_memory_enabled(enabled: boolean): Promise<ActionResult>
  apply_personality(personality: string, prompt: string): Promise<ActionResult>
  create_personality(name: string, prompt: string): Promise<ActionResult & { name?: string }>
  rename_personality(oldName: string, newName: string): Promise<ActionResult & { name?: string }>
  delete_personality(name: string): Promise<ActionResult>
  set_active_personality(name: string): Promise<ActionResult>
  save_personality(personality: string, prompt: string): Promise<ActionResult>
  reset_personality(personality: string): Promise<ActionResult>
  apply_profile_instructions(prompt: string): Promise<ActionResult>
  save_profile_instructions(prompt: string): Promise<ActionResult>
  reset_profile_instructions(): Promise<ActionResult>
  get_app_settings(): Promise<AppSettingsResponse>
  get_profile_info(): Promise<ProfileInfo>
  open_profile_folder(): Promise<ActionResult>
  export_configuration(): Promise<ConfigurationExportResponse>
  preview_configuration_import(archiveBase64: string): Promise<ConfigurationImportPreviewResponse>
  apply_configuration_import(archiveBase64: string, previewToken: string, confirmed: boolean): Promise<ConfigurationImportResponse>
  update_app_settings(startMinimized: boolean, minimizeToTray: boolean, closeToTray: boolean, autoStartBot: boolean): Promise<ActionResult>
  get_twitch_settings(): Promise<TwitchSettingsResponse>
  update_twitch_settings(targetChannel: string, targetChannelUserId: string, selectedPresetId?: string | null, clientId?: string, botUsername?: string, botUserId?: string): Promise<ActionResult>
  save_twitch_preset(presetId: string | null, displayName: string, targetChannel: string, targetChannelUserId: string): Promise<TwitchPresetActionResult>
  delete_twitch_preset(presetId: string): Promise<ActionResult>
  reconnect_twitch(): Promise<ActionResult>
  get_credentials(): Promise<CredentialsResponse>
  get_ai_provider_settings(): Promise<AIProviderSettingsResponse>
  get_ai_setup(): Promise<AISetupResponse>
  save_ai_setup(settings: AISetupSettings): Promise<ActionResult>
  get_setup_guide(): Promise<ActionResult & { dismissed?: boolean; ai_skipped?: boolean }>
  save_setup_guide(dismissed: boolean, ai_skipped: boolean): Promise<ActionResult & { dismissed?: boolean; ai_skipped?: boolean }>
  update_ai_provider_settings(selectedModel?: string | null, fallbackModel?: string | null, provider?: AIProviderId): Promise<ActionResult>
  get_ai_language_settings(): Promise<AILanguageSettingsResponse>
  update_ai_language_settings(mode: string, allowedLanguages: string[], fallbackLanguage: string): Promise<ActionResult>
  discover_gemini_models(): Promise<ModelDiscoveryResponse>
  discover_ai_models(provider?: AIProviderId): Promise<ModelDiscoveryResponse>
  replace_credential(name: CredentialName, value: string): Promise<ActionResult>
  remove_credential(name: CredentialName): Promise<ActionResult>
  test_credential(name: CredentialName): Promise<ActionResult>
  update_server_twitch_settings(clientId: string, botUsername: string, botUserId: string, channel: string, channelUserId: string): Promise<ActionResult>
  switch_server_twitch_preset(presetId: string): Promise<ActionResult>
  begin_twitch_authorization(): Promise<TwitchAuthorizationBeginResponse>
  complete_twitch_authorization(callbackUrl: string): Promise<ActionResult>
  cancel_twitch_authorization(): Promise<ActionResult>
  start_bot(): Promise<ActionResult>
  stop_bot(): Promise<ActionResult>
  open_external_link(destination: 'repository' | 'license' | 'third_party_notices' | 'author_twitch' | 'twitch_developer_console' | 'twitch_authorization' | 'releases'): Promise<ActionResult>
}

export interface ActionResult {
  ok: boolean
  changed?: boolean
  requires_reconnect?: boolean
  requires_restart?: boolean
  error?: string
}

export interface TwitchPresetActionResult extends ActionResult {
  preset_id?: string
}

export interface TwitchAuthorizationBeginResponse extends ActionResult {
  url?: string
  expires_in?: number
}

declare global {
  interface Window {
    pywebview?: {
      api: PythonApi
    }
  }
}

let pendingBridge: Promise<PythonApi> | null = null

function readyBridge(): PythonApi | null {
  const api = window.pywebview?.api
  return api && typeof api.get_app_status === 'function' ? api : null
}

export async function waitForBridge(): Promise<PythonApi> {
  if (isBrowserMode()) return browserApi
  const ready = readyBridge()
  if (ready) {
    return ready
  }
  if (pendingBridge) {
    return pendingBridge
  }

  pendingBridge = new Promise((resolve, reject) => {
    const onReady = () => {
      const api = readyBridge()
      if (!api) {
        return
      }
      window.clearTimeout(timeout)
      window.removeEventListener('pywebviewready', onReady)
      resolve(api)
    }
    const timeout = window.setTimeout(
      () => {
        window.removeEventListener('pywebviewready', onReady)
        reject(new Error('The desktop backend did not become available.'))
      },
      8000,
    )
    window.addEventListener('pywebviewready', onReady)
    // Close the gap between the initial readiness check and listener registration.
    onReady()
  })
  try {
    return await pendingBridge
  } catch (error) {
    pendingBridge = null
    throw error
  }
}

// The server marks its own document. A delayed desktop bridge must never select HTTP.
export function isBrowserMode(): boolean {
  return document.querySelector('meta[name="heetkit-transport"]')?.getAttribute('content') === 'http'
}

export interface ManagementSnapshot {
  status: AppStatus
  ai_status: AIStatus
}

export interface ManagementSetup extends ActionResult {
  twitch: TwitchConnectionSettings
  credentials: CredentialInfo[]
  aiProvider: AIProviderSettings
}

import { browserApi, browserRequest } from './httpTransport'

export function setBrowserOperationMode(mode: BrowserOperationMode): Promise<ActionResult> {
  return browserRequest('POST', '/v1/bot/mode', { mode })
}

export function getBrowserSnapshot(): Promise<ManagementSnapshot> {
  return browserRequest('GET', '/v1/snapshot')
}

export function getBrowserSetup(): Promise<ManagementSetup> {
  return browserRequest('GET', '/v1/setup')
}
