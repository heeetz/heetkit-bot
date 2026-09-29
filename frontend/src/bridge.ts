export interface AppStatus {
  running: boolean
  twitch_connected: boolean
  uptime_seconds: number
  channel: string
  account: string
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

export interface AIStatus {
  enabled: boolean
  memory_enabled: boolean
  active_personality: string
  available_personalities: string[]
  model: string
}

export interface LogEntry {
  id: number
  timestamp: string
  level: string
  source: string
  message: string
}

export interface LogsResponse {
  entries: LogEntry[]
}

interface PythonApi {
  get_app_status(): Promise<AppStatus>
  get_commands(): Promise<CommandsResponse>
  get_ai_status(): Promise<AIStatus>
  get_recent_logs(after_id?: number, limit?: number): Promise<LogsResponse>
  apply_command_settings(commandName: string, enabled: boolean, perUserSeconds: number, globalSeconds: number, permission: string): Promise<ActionResult>
  save_command_settings(commandName: string, enabled: boolean, perUserSeconds: number, globalSeconds: number, permission: string): Promise<ActionResult>
  reset_command_settings(commandName: string): Promise<ActionResult>
  start_bot(): Promise<ActionResult>
  stop_bot(): Promise<ActionResult>
}

export interface ActionResult {
  ok: boolean
  changed?: boolean
  error?: string
}

declare global {
  interface Window {
    pywebview?: {
      api: PythonApi
    }
  }
}

let pendingBridge: Promise<PythonApi> | null = null

export async function waitForBridge(): Promise<PythonApi> {
  if (window.pywebview?.api) {
    return window.pywebview.api
  }
  if (pendingBridge) {
    return pendingBridge
  }

  pendingBridge = new Promise((resolve, reject) => {
    const timeout = window.setTimeout(
      () => reject(new Error('The desktop backend did not become available.')),
      8000,
    )
    window.addEventListener(
      'pywebviewready',
      () => {
        window.clearTimeout(timeout)
        if (window.pywebview?.api) {
          resolve(window.pywebview.api)
        } else {
          reject(new Error('The desktop backend bridge is unavailable.'))
        }
      },
      { once: true },
    )
  })
  try {
    return await pendingBridge
  } catch (error) {
    pendingBridge = null
    throw error
  }
}
