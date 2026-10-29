import { createRoot } from 'react-dom/client'
import App from '../src/App'
import type { AnnouncementInfo, AnnouncementInput, CommandInfo, CommandSettingsMetadata, CustomCommandInfo, CustomCommandInput, waitForBridge } from '../src/bridge'
import CommandsPage from '../src/pages/CommandsPage'
import '../src/styles.css'

const defaults = {
  enabled: true, permission: 'USER', cooldown: { per_user_seconds: 0, global_seconds: 15 },
  removed: false, display_name: '', aliases: [], burst_interval_ms: 0, burst_max_count: 10,
}
const initialResponses: Record<string, string[]> = {
  fate: ['Tomorrow brings a new opportunity.', 'Take a break, then try again.'],
  tg: ['Configure your community link.'],
}
const savedResponses = structuredClone(initialResponses)
const commands: CommandInfo[] = ['fate', 'ping', 'tg'].map((name) => ({
  name, ...structuredClone(defaults), primary_name: name, permission: name === 'tg' ? 'MODERATOR' : 'USER', available: true, unavailable_reason: null,
  minimum_permission: name === 'tg' ? 'MODERATOR' : 'USER', identity_editable: true,
  hidden: false, default_settings: { ...structuredClone(defaults), primary_name: name }, saved: true, has_saved_override: false,
  response_pool: name === 'ping' ? null : {
    responses: [...initialResponses[name]], defaults: [...initialResponses[name]],
    saved: true, has_saved_override: false,
    response_mode: name === 'tg' ? 'single' : 'random', max_responses: name === 'tg' ? 1 : 1000,
  },
}))
if (new URLSearchParams(window.location.search).has('extended')) {
  for (const name of ['ask', 'weather', 'erase']) {
    const minimum = name === 'erase' ? 'BROADCASTER' : 'USER'
    commands.push({
      name, ...structuredClone(defaults), primary_name: name, permission: minimum, available: true,
      unavailable_reason: null, hidden: name === 'erase', identity_editable: true,
      minimum_permission: minimum, response_pool: null,
      default_settings: { ...structuredClone(defaults), primary_name: name, permission: minimum }, saved: true, has_saved_override: false,
    })
  }
}
commands.find((command) => command.name === 'tg')!.default_settings.permission = 'MODERATOR'
if (new URLSearchParams(window.location.search).has('legacyBurstMax')) {
  const tg = commands.find((command) => command.name === 'tg')!
  delete tg.burst_max_count
}
let customCommands: CustomCommandInfo[] = [{
  id: 'synthetic-hello', name: 'hello', enabled: true, responses: ['Hello, {sender}!', 'Welcome, {target}!'],
  permission: 'USER', per_user_seconds: 2, global_seconds: 5, aliases: ['hi'], response_mode: 'random',
}]
const commandCalls: unknown[][] = []
Object.assign(window, { commandCalls })
let announcements: AnnouncementInfo[] = new URLSearchParams(window.location.search).has('announcements') ? [{
  id: '00000000-0000-0000-0000-000000000001', name: 'Community', enabled: true,
  messages: ['Visit our community.'], message_mode: 'single', interval_seconds: 900, min_messages: 3, stream_availability: 'live_only',
  status: { next_run_at: '2026-10-25T12:15:00Z', last_sent_at: '2026-10-25T12:00:00Z', last_outcome: 'sent', eligible_messages: 2 },
}] : []
Object.assign(window, { updateAnnouncementStatus: (status: Partial<AnnouncementInfo['status']>) => {
  announcements = announcements.map((item) => ({ ...item, status: { ...item.status, ...status } }))
} })

function settingsAction(action: string, name: string, enabled?: boolean, perUserSeconds?: number, globalSeconds?: number, permission?: string, metadata?: CommandSettingsMetadata) {
  commandCalls.push([`${action}_command_settings`, name, enabled, perUserSeconds, globalSeconds, permission, ...(metadata ? [structuredClone(metadata)] : [])])
  if (new URLSearchParams(window.location.search).has('settingsError')) return { ok: false, error: 'Synthetic settings save failure.' }
  const names = [metadata?.primary_name, ...(metadata?.aliases ?? [])].filter((value): value is string => value !== undefined).map((value) => value.trim().replace(/^!+/, '').toLowerCase())
  if (names.some((value) => !value || value.length > 40 || /[\s!{}]/.test(value)) || new Set(names).size !== names.length) return { ok: false, error: 'Invalid or duplicate command name.' }
  if (names.some((value) => commands.some((command) => command.name !== name && [command.name, command.primary_name, ...command.aliases].includes(value)) || customCommands.some((command) => [command.name, ...command.aliases].includes(value)))) {
    return { ok: false, error: 'Command name or alias is already in use.' }
  }
  const command = commands.find((item) => item.name === name)!
  if (action === 'reset') Object.assign(command, structuredClone(command.default_settings))
  else Object.assign(command, { enabled, permission, ...metadata, cooldown: { per_user_seconds: perUserSeconds, global_seconds: globalSeconds } })
  command.saved = action !== 'apply'
  if (action !== 'apply') command.has_saved_override = action === 'save'
  return { ok: true }
}

function factoryAction(action: 'remove' | 'restore' | 'resetAll', name?: string) {
  commandCalls.push([action === 'resetAll' ? 'reset_all_builtin_commands' : `${action}_builtin_command`, ...(name ? [name] : [])])
  if (new URLSearchParams(window.location.search).has('factoryError')) return { ok: false, error: 'Synthetic factory save failure.' }
  const responseError = action === 'resetAll' && new URLSearchParams(window.location.search).has('factoryResponseError')
  for (const command of commands.filter((command) => !name || command.name === name)) {
    if (action === 'remove') {
      command.removed = true
      command.enabled = false
      command.has_saved_override = true
    } else {
      Object.assign(command, structuredClone(command.default_settings))
      command.saved = true
      command.has_saved_override = false
      if (action === 'resetAll' && !responseError && command.response_pool) {
        Object.assign(command.response_pool, { responses: [...command.response_pool.defaults], saved: true, has_saved_override: false })
        savedResponses[command.name] = [...command.response_pool.defaults]
      }
    }
  }
  if (responseError) return { ok: false, error: 'Factory command settings were restored, but responses could not be restored.' }
  return { ok: true }
}

function responseAction(action: string, name: string, responses?: string[]) {
  commandCalls.push([`${action}_command_responses`, name, responses])
  if (new URLSearchParams(window.location.search).has('responseThrow')) throw new Error('Synthetic response bridge failure.')
  if (new URLSearchParams(window.location.search).has('responseError')) {
    return { ok: false, error: 'Synthetic response save failure.' }
  }
  const pool = commands.find((item) => item.name === name)!.response_pool!
  pool.responses = action === 'reset' ? [...pool.defaults] : [...responses!]
  if (action !== 'apply') savedResponses[name] = [...pool.responses]
  pool.saved = JSON.stringify(pool.responses) === JSON.stringify(savedResponses[name])
  if (action !== 'apply') pool.has_saved_override = action === 'save'
  return { ok: true }
}

window.pywebview = { api: {
  get_desktop_startup: async () => ({ state: 'ready' }),
  confirm_legacy_channel: async () => ({ ok: false }),
  cancel_desktop_startup: async () => ({ ok: true }),
  get_announcements: async () => ({ ok: true, announcements: structuredClone(announcements) }),
  save_announcements: async (input: AnnouncementInput[]) => {
    commandCalls.push(['save_announcements', structuredClone(input)])
    if (new URLSearchParams(window.location.search).has('announcementError')) return { ok: false, error: 'Synthetic announcement save failure.' }
    announcements = input.map((item, index) => ({ ...item, id: item.id ?? `00000000-0000-0000-0000-${String(index + 2).padStart(12, '0')}`,
      status: { next_run_at: null, last_sent_at: null, last_outcome: null, eligible_messages: 0 } }))
    return { ok: true }
  },
  get_app_status: async () => ({
    running: false, twitch_connected: false, twitch_connection_state: 'stopped',
    uptime_seconds: 0, channel: '', account: '',
  }),
  get_ai_status: async () => ({
    enabled: false, available: false, memory_enabled: false,
    active_personality: 'neutral', available_personalities: ['neutral'], model: '',
  }),
  get_commands: async () => ({ command_prefix: '!', permissions: ['USER', 'SUBSCRIBER', 'VIP', 'MODERATOR', 'BROADCASTER'], commands: structuredClone(commands) }),
  get_custom_commands: async () => ({
    command_prefix: '!', permissions: ['USER', 'MODERATOR', 'BROADCASTER'],
    variables: ['sender', 'target', 'args', ...Array.from({ length: 9 }, (_, index) => `arg${index + 1}`), 'random_user'], commands: structuredClone(customCommands),
  }),
  apply_command_settings: async (name: string, enabled: boolean, perUser: number, global: number, permission: string, metadata?: CommandSettingsMetadata) => settingsAction('apply', name, enabled, perUser, global, permission, metadata),
  save_command_settings: async (name: string, enabled: boolean, perUser: number, global: number, permission: string, metadata?: CommandSettingsMetadata) => settingsAction('save', name, enabled, perUser, global, permission, metadata),
  reset_command_settings: async (name: string) => settingsAction('reset', name),
  remove_builtin_command: async (name: string) => factoryAction('remove', name),
  restore_builtin_command: async (name: string) => factoryAction('restore', name),
  reset_all_builtin_commands: async () => factoryAction('resetAll'),
  apply_command_responses: async (name: string, responses: string[]) => responseAction('apply', name, responses),
  save_command_responses: async (name: string, responses: string[]) => responseAction('save', name, responses),
  reset_command_responses: async (name: string) => responseAction('reset', name),
  save_custom_command: async (input: CustomCommandInput) => {
    commandCalls.push(['save_custom_command', structuredClone(input)])
    if (input.responses.some((response) => /[\r\n]/.test(response))) {
      return { ok: false, error: 'Response templates must be single-line messages.' }
    }
    if (new URLSearchParams(window.location.search).has('customError')) {
      return { ok: false, error: 'Response contains an unknown variable.' }
    }
    const command: CustomCommandInfo = {
      ...input, id: input.id ?? 'synthetic-new', response_mode: input.response_mode ?? (input.responses.length > 1 ? 'random' : 'single'),
    }
    customCommands = [...customCommands.filter((item) => item.id !== command.id), command]
    return { ok: true }
  },
  delete_custom_command: async (id: string) => {
    commandCalls.push(['delete_custom_command', id])
    customCommands = customCommands.filter((item) => item.id !== id)
    return { ok: true }
  },
} as unknown as Awaited<ReturnType<typeof waitForBridge>> }

createRoot(document.getElementById('root')!).render(
  new URLSearchParams(window.location.search).has('shell')
    ? <App /> : <main><CommandsPage active /></main>,
)
