export interface AppStatus {
  running: boolean
  twitch_connected: boolean
  twitch_connection_state: TwitchConnectionState
  uptime_seconds: number
  channel: string
  account: string
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

export interface CommandInfo {
  name: string
  aliases: string[]
  enabled: boolean
  permission: string
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
  permission: string
  cooldown: {
    per_user_seconds: number
    global_seconds: number
  }
}

export interface CommandsResponse {
  command_prefix: string
  permissions: string[]
  commands: CommandInfo[]
}

export interface CustomCommandInput {
  id?: string | null
  name: string
  enabled: boolean
  responses: string[]
  permission: string
  per_user_seconds: number
  global_seconds: number
  aliases: string[]
}

export interface CustomCommandInfo extends CustomCommandInput {
  id: string
  response_mode: 'single' | 'random'
}

export interface CustomCommandsResponse {
  command_prefix: string
  permissions: string[]
  variables: string[]
  commands: CustomCommandInfo[]
}

export interface AIStatus {
  enabled: boolean
  memory_enabled: boolean
  active_personality: string
  available_personalities: string[]
  model: string
}

export interface PersonalityInfo {
  name: string
  prompt: string
  built_in_prompt: string
  prompt_saved: boolean
  has_saved_override: boolean
}

export interface PersonalitiesResponse {
  active_personality: string
  active_personality_saved: boolean
  personalities: PersonalityInfo[]
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
  running: boolean
  connected: boolean
  oauth_token_available: boolean
  has_local_override: boolean
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

export type CredentialName = 'gemini_api_key' | 'twitch_client_secret'

export interface CredentialInfo {
  name: CredentialName
  label: string
  configured: boolean
  source: 'credential_store' | 'environment' | 'missing'
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
  selected_model: string
  fallback_model: string
  presets: GeminiModelPreset[]
  credential: CredentialInfo | null
}

export interface AIProviderSettingsResponse extends ActionResult {
  settings?: AIProviderSettings
}

export interface ModelDiscoveryResponse extends ActionResult {
  models?: string[]
}

export interface LogEntry {
  id: number
  timestamp: string
  level: string
  source: string
  message: string
  event_kind: string | null
  context: Record<string, string | number | boolean>
}

export interface LogsResponse {
  entries: LogEntry[]
}

interface PythonApi {
  get_app_status(): Promise<AppStatus>
  get_commands(): Promise<CommandsResponse>
  get_custom_commands(): Promise<CustomCommandsResponse>
  get_ai_status(): Promise<AIStatus>
  get_personalities(): Promise<PersonalitiesResponse>
  get_recent_logs(after_id?: number, limit?: number): Promise<LogsResponse>
  apply_command_settings(commandName: string, enabled: boolean, perUserSeconds: number, globalSeconds: number, permission: string): Promise<ActionResult>
  save_command_settings(commandName: string, enabled: boolean, perUserSeconds: number, globalSeconds: number, permission: string): Promise<ActionResult>
  reset_command_settings(commandName: string): Promise<ActionResult>
  save_custom_command(command: CustomCommandInput): Promise<ActionResult>
  delete_custom_command(id: string): Promise<ActionResult>
  set_ai_enabled(enabled: boolean): Promise<ActionResult>
  set_ai_memory_enabled(enabled: boolean): Promise<ActionResult>
  apply_personality(personality: string, prompt: string): Promise<ActionResult>
  save_personality(personality: string, prompt: string): Promise<ActionResult>
  reset_personality(personality: string): Promise<ActionResult>
  get_app_settings(): Promise<AppSettingsResponse>
  update_app_settings(startMinimized: boolean, minimizeToTray: boolean, closeToTray: boolean, autoStartBot: boolean): Promise<ActionResult>
  get_twitch_settings(): Promise<TwitchSettingsResponse>
  update_twitch_settings(targetChannel: string, targetChannelUserId: string, selectedPresetId?: string | null): Promise<ActionResult>
  save_twitch_preset(presetId: string | null, displayName: string, targetChannel: string, targetChannelUserId: string): Promise<TwitchPresetActionResult>
  delete_twitch_preset(presetId: string): Promise<ActionResult>
  reconnect_twitch(): Promise<ActionResult>
  get_credentials(): Promise<CredentialsResponse>
  get_ai_provider_settings(): Promise<AIProviderSettingsResponse>
  update_ai_provider_settings(selectedModel: string, fallbackModel: string): Promise<ActionResult>
  discover_gemini_models(): Promise<ModelDiscoveryResponse>
  replace_credential(name: CredentialName, value: string): Promise<ActionResult>
  remove_credential(name: CredentialName): Promise<ActionResult>
  test_credential(name: CredentialName): Promise<ActionResult>
  start_bot(): Promise<ActionResult>
  stop_bot(): Promise<ActionResult>
}

export interface ActionResult {
  ok: boolean
  changed?: boolean
  requires_reconnect?: boolean
  error?: string
}

export interface TwitchPresetActionResult extends ActionResult {
  preset_id?: string
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
