import { createRoot } from 'react-dom/client'
import type { CommandInfo, CustomCommandInfo, CustomCommandInput, waitForBridge } from '../src/bridge'
import CommandsPage from '../src/pages/CommandsPage'
import '../src/styles.css'

const defaults = {
  enabled: true, permission: 'USER', cooldown: { per_user_seconds: 0, global_seconds: 15 },
}
const initialResponses: Record<string, string[]> = {
  fate: ['Tomorrow brings a new opportunity.', 'Take a break, then try again.'],
  tg: ['Configure your community link.'],
}
const savedResponses = structuredClone(initialResponses)
const commands: CommandInfo[] = ['fate', 'ping', 'tg'].map((name) => ({
  name, aliases: [], ...structuredClone(defaults), available: true, unavailable_reason: null,
  hidden: false, default_settings: structuredClone(defaults), saved: true, has_saved_override: false,
  response_pool: name === 'ping' ? null : {
    responses: [...initialResponses[name]], defaults: [...initialResponses[name]],
    saved: true, has_saved_override: false,
    response_mode: name === 'tg' ? 'single' : 'random', max_responses: name === 'tg' ? 1 : 1000,
  },
}))
let customCommands: CustomCommandInfo[] = [{
  id: 'synthetic-hello', name: 'hello', enabled: true, responses: ['Hello, {sender}!', 'Welcome, {target}!'],
  permission: 'USER', per_user_seconds: 2, global_seconds: 5, aliases: ['hi'], response_mode: 'random',
}]
const commandCalls: unknown[][] = []
Object.assign(window, { commandCalls })

function settingsAction(action: string, name: string, enabled?: boolean, perUserSeconds?: number, globalSeconds?: number, permission?: string) {
  commandCalls.push([`${action}_command_settings`, name, enabled, perUserSeconds, globalSeconds, permission])
  const command = commands.find((item) => item.name === name)!
  if (action === 'reset') Object.assign(command, structuredClone(command.default_settings))
  else Object.assign(command, { enabled, permission, cooldown: { per_user_seconds: perUserSeconds, global_seconds: globalSeconds } })
  command.saved = action !== 'apply'
  if (action !== 'apply') command.has_saved_override = action === 'save'
  return { ok: true }
}

function responseAction(action: string, name: string, responses?: string[]) {
  commandCalls.push([`${action}_command_responses`, name, responses])
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
  get_app_status: async () => ({
    running: false, twitch_connected: false, twitch_connection_state: 'stopped',
    uptime_seconds: 0, channel: '', account: '',
  }),
  get_commands: async () => ({ command_prefix: '!', permissions: ['USER', 'MODERATOR'], commands: structuredClone(commands) }),
  get_custom_commands: async () => ({
    command_prefix: '!', permissions: ['USER', 'MODERATOR'],
    variables: ['sender', 'target', 'args', 'arg1', 'arg9', 'random_user'], commands: structuredClone(customCommands),
  }),
  apply_command_settings: async (name: string, enabled: boolean, perUser: number, global: number, permission: string) => settingsAction('apply', name, enabled, perUser, global, permission),
  save_command_settings: async (name: string, enabled: boolean, perUser: number, global: number, permission: string) => settingsAction('save', name, enabled, perUser, global, permission),
  reset_command_settings: async (name: string) => settingsAction('reset', name),
  apply_command_responses: async (name: string, responses: string[]) => responseAction('apply', name, responses),
  save_command_responses: async (name: string, responses: string[]) => responseAction('save', name, responses),
  reset_command_responses: async (name: string) => responseAction('reset', name),
  save_custom_command: async (input: CustomCommandInput) => {
    commandCalls.push(['save_custom_command', structuredClone(input)])
    if (new URLSearchParams(window.location.search).has('customError')) {
      return { ok: false, error: 'Response contains an unknown variable.' }
    }
    const command: CustomCommandInfo = {
      ...input, id: input.id ?? 'synthetic-new', response_mode: input.responses.length > 1 ? 'random' : 'single',
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

createRoot(document.getElementById('root')!).render(<main><CommandsPage active /></main>)
