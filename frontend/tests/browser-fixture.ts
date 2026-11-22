import { expect, type Locator, type Page } from '@playwright/test'
import type {
  AIPlaygroundResult, AnnouncementInfo, AnnouncementInput, AppStatus, ChatReaction,
  CommandInfo, CommandRestriction, CustomCommandInfo, FilterInput, LogEntry, OptOutUser,
  PersonalitiesResponse,
} from '../src/bridge'

export const adminToken = 'a'.repeat(43)
export const sessionToken = 's'.repeat(43)
type Call = { method: string; path: string; body: Record<string, unknown> | null; authorization: string | undefined }
type OperationOverrides = Partial<{
  mode: 'always_on' | 'stream_only' | 'manual' | 'disabled'
  desired_running: boolean
  pending: boolean
  stream_status: 'live' | 'offline' | 'unknown'
  last_known_stream_status: 'live' | 'offline' | null
  last_checked_at: string | null
  error: null | 'connection_failed'
}>
type StatusOverrides = Partial<{
  twitch_recovery: AppStatus['twitch_recovery']
  leaderboard_channel_id: AppStatus['leaderboard_channel_id']
  running: boolean
  twitch_connected: boolean
  twitch_connection_state: 'stopped' | 'connecting' | 'connected' | 'reconnecting' | 'auth_required' | 'failed'
}>

export async function server(page: Page, operationOverrides: OperationOverrides = {}, statusOverrides: StatusOverrides = {}, aiConfigured = true) {
  const calls: Call[] = []
  let expired = false
  let logs: LogEntry[] = []
  let fail = ''
  let filters: FilterInput = { words: ['synthetic'], phrases: [], patterns: [] }
  let profile = 'Saved instructions'
  let activePersonality = 'neutral'
  let personalities: PersonalitiesResponse['personalities'] = [{
    name: 'neutral', prompt: 'Neutral prompt', built_in_prompt: 'Neutral prompt',
    is_builtin: true, prompt_saved: true, has_saved_override: false,
  }]
  let reactions: ChatReaction[] = []
  let reactionRevision = 0
  let customCommands: CustomCommandInfo[] = []
  let commandRestrictions: CommandRestriction[] = []
  let optouts: OptOutUser[] = []
  let announcements: AnnouncementInfo[] = []
  let enabled = true, memoryEnabled = false
  let playgroundPending = false
  let playgroundCancelled = false
  let playgroundStatus = 'success'
  let playgroundGeneration: NonNullable<AIPlaygroundResult['generation']> = { provider: 'DeepSeek', model: 'deepseek-v4-pro', thinking: 'high',
    fallback_used: true, search_enabled: true, search_requested: true, search_used: true }
  let oauthBeginResult: object = { ok: true, url: 'https://id.twitch.tv/oauth2/authorize?client_id=synthetic', expires_in: 300 }
  let oauthCompleteResult: object = { ok: true }
  const command: CommandInfo = {
    name: 'ping', primary_name: 'ping', aliases: [], enabled: true, available: true, unavailable_reason: null,
    response_pool: { responses: ['Pong'], defaults: ['Pong'], saved: true, has_saved_override: false, response_mode: 'random', max_responses: 1 },
    permission: 'EVERYONE', stream_availability: 'live_only', cooldown: { per_user_seconds: 1, global_seconds: 0 }, hidden: false,
    default_settings: { primary_name: 'ping', enabled: true, permission: 'EVERYONE', stream_availability: 'anytime', cooldown: { per_user_seconds: 1, global_seconds: 0 } },
    saved: true, has_saved_override: false,
  }
  let operation = {
    mode: 'always_on' as const, desired_running: true, pending: false,
    stream_status: 'live' as const, last_known_stream_status: 'live' as const,
    last_checked_at: '2026-10-20T12:00:00Z', error: null as null | 'connection_failed',
    ...operationOverrides,
  }
  const status = { running: true, twitch_connected: true, twitch_connection_state: 'connected' as const, uptime_seconds: 10, channel: 'synthetic_channel', account: 'synthetic_bot', leaderboard_channel_id: '200', ...statusOverrides, operation }
  const ai = () => ({ provider: 'Google Gemini', enabled, available: aiConfigured, memory_enabled: memoryEnabled, active_personality: activePersonality, available_personalities: personalities.map(({ name }) => name), model: 'test-model' })
  const aiProvider = { provider: 'Gemini', selected_model: 'test-model', fallback_model: 'test-fallback', presets: [], credential: null }
  let aiSetup = { primary: { provider: 'gemini', model: 'gemini-2.5-flash', thinking: 'default', search: false },
    fallback: null, cross_provider_acknowledged: false, max_question_length: 300, max_answer_length: 220,
    shared_instructions: null, provider_drafts: {} }
  let setupGuide = { dismissed: false, ai_skipped: false }
  const twitch: Record<string, unknown> = { client_id: 'synthetic-client', bot_username: 'synthetic_bot', bot_user_id: '100', target_channel: 'synthetic_channel', target_channel_user_id: '200', active_channel: 'synthetic_channel', requires_restart: false, requires_reconnect: false, oauth_token_available: true, saved_bot_authorization: true, oauth_callback_url: 'http://localhost:8765/oauth/callback', authorization_status: 'verified', authorized_account: 'synthetic_bot', setup_complete: true }
  const credentials = [{ name: 'twitch_client_secret', label: 'Twitch client secret', configured: true, source: 'environment', managed: false, validation_status: 'not_tested', secure_storage_available: false }, { name: 'gemini_api_key', label: 'Gemini API key', configured: false, source: 'missing', managed: true, validation_status: 'not_tested', secure_storage_available: false }, { name: 'deepseek_api_key', label: 'DeepSeek API key', configured: aiConfigured, source: aiConfigured ? 'server_file' : 'missing', managed: true, validation_status: 'not_tested', secure_storage_available: false }]
  await page.route('**/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const body = request.postDataJSON() as Record<string, unknown> | null
    calls.push({ method: request.method(), path, body, authorization: request.headers().authorization })
    if (fail === path) return route.abort('connectionrefused')
    if (path === '/v1/session' && request.method() === 'POST') {
      return route.fulfill({ json: request.headers().authorization === `Bearer ${adminToken}`
        ? { ok: true, token: sessionToken, expires_in: 3600 } : { ok: false }, status: request.headers().authorization === `Bearer ${adminToken}` ? 200 : 401 })
    }
    if (expired) return route.fulfill({ status: 401, json: { ok: false } })
    if (path === '/v1/session/logout') return route.fulfill({ json: { ok: true } })
    let result: object = { ok: true }
    if (path === '/v1/ops/start_ai_playground') {
      playgroundCancelled = false
      result = { ok: true, request_id: 'server-playground', status: 'pending' }
    }
    if (path === '/v1/ops/cancel_ai_playground') playgroundCancelled = true
    if (path === '/v1/ops/get_ai_playground_result') {
      result = playgroundCancelled ? { ok: true, status: 'cancelled' }
        : playgroundPending ? { ok: true, status: 'pending' }
        : { ok: true, status: playgroundStatus, text: playgroundGeneration.provider === 'OpenAI' ? 'Fresh fact https://example.test/facts' : 'Synthetic server answer <b>plain text</b>', generation: playgroundGeneration }
    }
    if (path === '/v1/ops/get_snapshot') result = { status, ai_status: ai() }
    if (path === '/v1/ops/get_ai_memory_limits') result = { ok: true, stored: 100, context: 5 }
    if (path === '/v1/ops/get_app_status') result = { ...status, operation }
    if (path === '/v1/ops/set_bot_mode') {
      operation = { ...operation, mode: body!.mode as 'always_on' | 'stream_only' | 'manual' | 'disabled', pending: false }
      status.operation = operation
    }
    if (path === '/v1/ops/stop_bot') {
      operation = { ...operation, mode: 'manual', desired_running: false, pending: false }
      Object.assign(status, { operation, running: false, twitch_connected: false, twitch_connection_state: 'stopped' as const })
    }
    if (path === '/v1/ops/get_management_setup') result = { ok: true, twitch, credentials, aiProvider }
    if (path === '/v1/ops/get_setup_guide' || path === '/v1/ops/save_setup_guide') {
      if (path.endsWith('/save_setup_guide')) setupGuide = body as typeof setupGuide
      result = { ok: true, ...setupGuide }
    }
    if (path === '/v1/ops/get_ai_setup' || path === '/v1/ops/save_ai_setup') {
      if (path.endsWith('/save_ai_setup')) aiSetup = body!.settings as typeof aiSetup
      result = { ok: true, settings: aiSetup, providers: [
        { id: 'gemini', label: 'Google Gemini', credential: credentials[1], models: ['gemini-2.5-flash'], selected_model: 'gemini-2.5-flash', fallback_model: 'gemini-2.5-pro' },
        { id: 'deepseek', label: 'DeepSeek', credential: credentials[2], models: ['deepseek-flash'], selected_model: 'deepseek-flash', fallback_model: 'deepseek-v4-pro' },
        { id: 'openai', label: 'OpenAI', credential: { name: 'openai_api_key', label: 'OpenAI API key', configured: true, source: 'server_file', managed: true }, models: ['gpt-6-luna'], selected_model: 'gpt-6-luna', fallback_model: 'gpt-6.1-sol' },
      ], capabilities: { gemini: { 'gemini-2.5-flash': { known: true, thinking_options: [{ value: 'default', label: 'Provider default' }, { value: 'off', label: 'Off' }], search_supported: true, search_reason: 'Google Suggestions display required', attribution_required: true } },
        deepseek: { 'deepseek-flash': { known: true, thinking_options: [{ value: 'default', label: 'Provider default' }, { value: 'off', label: 'Off' }, { value: 'high', label: 'High' }], search_supported: true, search_reason: 'Bounded provider search', attribution_required: false } },
        openai: { 'gpt-6-luna': { known: true, thinking_options: [{ value: 'default', label: 'Provider default' }, { value: 'none', label: 'None' }, { value: 'low', label: 'Low' }], search_supported: true, search_reason: 'OpenAI Web Search with inline source URLs', attribution_required: false } } },
        default_shared_instructions: 'Shared defaults', retained_restrictions: 'Local request and output checks remain enabled.' }
    }
    if (path === '/v1/ops/discover_ai_models') result = { ok: true, provider_id: body?.provider, models: ['deepseek-flash'] }
    if (path === '/v1/ops/update_server_twitch_settings') {
      Object.assign(twitch, {
        client_id: body!.client_id,
        bot_username: body!.bot_username,
        bot_user_id: body!.bot_user_id,
        target_channel: body!.channel,
        target_channel_user_id: body!.channel_user_id,
      })
      result = { ok: true, requires_reconnect: true }
    }
    if (path === '/v1/ops/begin_twitch_authorization') result = oauthBeginResult
    if (path === '/v1/ops/complete_twitch_authorization') result = oauthCompleteResult
    if (path === '/v1/ops/cancel_twitch_authorization') result = { ok: true }
    if (['/v1/ops/replace_credential', '/v1/ops/remove_credential', '/v1/ops/test_credential'].includes(path)) {
      const credential = credentials.find((item) => item.name === body?.name)
      if (!credential) result = { ok: false, error: 'Unknown credential' }
      else if (path.endsWith('/test_credential')) { credential.validation_status = 'valid'; result = { ok: true } }
      else if (!credential.managed) result = { ok: false, error: 'Managed externally' }
      else {
        const configured = path.endsWith('/replace_credential')
        Object.assign(credential, { configured, source: configured ? 'server_file' : 'missing', validation_status: 'not_tested' })
        result = { ok: true, changed: true }
      }
    }
    if (path === '/v1/ops/get_ai_status') result = ai()
    if (path === '/v1/ops/set_ai_enabled') enabled = body!.enabled as boolean
    if (path === '/v1/ops/set_ai_memory_enabled') memoryEnabled = body!.enabled as boolean
    if (path === '/v1/ops/get_ai_provider_settings') result = { ok: true, settings: aiProvider }
    if (path === '/v1/ops/get_ai_language_settings') result = { ok: true, settings: { mode: 'auto', allowed_languages: ['en'], fallback_language: 'en' }, languages: [{ code: 'en', label: 'English' }], active_policy: 'Auto' }
    if (path === '/v1/ops/get_commands') result = { command_prefix: '!', permissions: ['USER', 'MODERATOR', 'BROADCASTER'], commands: [command, { ...command, name: 'ask', primary_name: 'ask', enabled, response_pool: null }] }
    if (path === '/v1/ops/save_builtin_enabled' && body!.command_name === 'ask') enabled = body!.enabled as boolean
    if (path === '/v1/ops/save_command_settings') {
      const options = body!.options as { display_name?: string }
      command.display_name = options.display_name
      command.has_saved_override = true
    }
    if (path === '/v1/ops/reset_command_settings') {
      command.display_name = undefined
      command.has_saved_override = false
    }
    if (path === '/v1/ops/save_command_responses') {
      command.response_pool!.responses = body!.responses as string[]
    }
    if (path === '/v1/ops/get_custom_commands') result = { command_prefix: '!', permissions: ['EVERYONE', 'MODERATOR', 'USER'], variables: ['sender'], commands: customCommands }
    if (path === '/v1/ops/get_command_restrictions') result = { ok: true, channel_id: '200', commands: [{ id: 'ping', label: '!ping' }, { id: 'ask', label: '!ask' }], restrictions: commandRestrictions }
    if (path === '/v1/ops/save_command_restriction') {
      const data = body!.data as { id?: string; username: string; command_ids: string[]; expires_at: string | null; note: string; scope?: 'channel' | 'global_ai' }
      const row = { scope: data.scope, id: data.id ?? 'http-restriction', channel_id: '200', twitch_user_id: '1234', username: data.id ? 'httpviewer' : data.username, command_ids: data.command_ids, expires_at: data.expires_at, note: data.note }
      commandRestrictions = [...commandRestrictions.filter((item) => item.id !== row.id), row]
      result = { ok: true, channel_id: '200', commands: [{ id: 'ping', label: '!ping' }, { id: 'ask', label: '!ask' }], restrictions: commandRestrictions }
    }
    if (path === '/v1/ops/remove_command_restriction') {
      commandRestrictions = commandRestrictions.filter((item) => item.id !== body!.restriction_id)
      result = { ok: true, channel_id: '200', commands: [{ id: 'ping', label: '!ping' }, { id: 'ask', label: '!ask' }], restrictions: commandRestrictions }
    }
    if (path === '/v1/ops/save_custom_command') {
      const input = body!.command as CustomCommandInfo
      const row = { ...input, id: input.id ?? 'saved-command', saved: true }
      customCommands = [...customCommands.filter((item) => item.id !== row.id), row]
    }
    if (path === '/v1/ops/delete_custom_command') customCommands = customCommands.filter((item) => item.id !== body!.identifier)
    if (path === '/v1/ops/get_message_triggers' || path === '/v1/ops/save_message_triggers') {
      if (path.endsWith('/save_message_triggers')) {
        if (body!.revision !== String(reactionRevision)) return route.fulfill({ json: { ok: false, error: 'Chat reactions changed.' } })
        reactions = body!.triggers as ChatReaction[]
        reactionRevision += 1
      }
      result = { ok: true, triggers: reactions, revision: String(reactionRevision) }
    }
    if (path === '/v1/ops/get_announcements' || path === '/v1/ops/save_announcements') {
      if (path.endsWith('/save_announcements')) announcements = (body!.announcements as AnnouncementInput[]).map((item, index) => ({
        ...item, id: item.id ?? `00000000-0000-0000-0000-${String(index + 1).padStart(12, '0')}`,
        status: { next_run_at: null, last_sent_at: null, last_outcome: null, eligible_messages: 0 },
      }))
      result = { ok: true, announcements }
    }
    if (path === '/v1/ops/get_filters') result = Object.fromEntries(Object.entries(filters).map(([category, values]) => [category, { rules: (values as string[]).map((value: string) => ({ value, origin: 'local', valid: true })), defaults: [] }]))
    if (path === '/v1/ops/test_filters') result = { ok: true, source: 'active', decision: 'BLOCK', category: 'words', rule: filters.words[0], timed_out: false }
    if (path === '/v1/ops/complete_twitch_authorization' && 'ok' in oauthCompleteResult && oauthCompleteResult.ok) {
      Object.assign(twitch, { setup_complete: true, saved_bot_authorization: true, authorization_status: 'verified', authorized_account: twitch.bot_username })
    }
    if (path === '/v1/ops/save_filters') {
      const payload = body!.payload as FilterInput
      const invalid = payload.patterns.indexOf('[')
      if (invalid >= 0) return route.fulfill({ json: {
        ok: false, error: 'Synthetic invalid regex', invalid_rule: { category: 'patterns', index: invalid },
      } })
      filters = payload
    }
    if (path === '/v1/ops/save_profile_instructions' || path === '/v1/ops/apply_profile_instructions') profile = body!.prompt as string
    if (path === '/v1/ops/get_personalities') result = {
      active_personality: activePersonality, active_personality_saved: true, personalities,
      profile_instructions: profile, profile_instructions_saved: true, protected_shared_instructions: 'Protected policy',
    }
    if (path === '/v1/ops/create_personality') {
      const name = body!.name as string
      personalities.push({ name, prompt: body!.prompt as string, built_in_prompt: '',
        is_builtin: false, prompt_saved: true, has_saved_override: true })
      result = { ok: true, name }
    }
    if (path === '/v1/ops/save_personality') {
      personalities = personalities.map((item) => item.name === body!.personality
        ? { ...item, prompt: body!.prompt as string, prompt_saved: true } : item)
    }
    if (path === '/v1/ops/set_active_personality') activePersonality = body!.personality as string
    if (path === '/v1/ops/rename_personality') {
      const name = body!.name as string
      personalities = personalities.map((item) => item.name === body!.personality ? { ...item, name } : item)
      if (activePersonality === body!.personality) activePersonality = name
      result = { ok: true, name }
    }
    if (path === '/v1/ops/delete_personality') {
      personalities = personalities.filter(({ name }) => name !== body!.personality)
      if (activePersonality === body!.personality) activePersonality = 'neutral'
    }
    if (path === '/v1/ops/add_opt_out') optouts.push({ twitch_user_id: '1234', username: String(body!.username), opted_out_at: new Date().toISOString() })
    if (path === '/v1/ops/withdraw_opt_out') optouts = optouts.filter((user) => user.twitch_user_id !== body!.twitch_user_id)
    if (['/v1/ops/get_opt_outs', '/v1/ops/add_opt_out', '/v1/ops/withdraw_opt_out'].includes(path)) result = { ok: true, users: optouts, total: optouts.length, offset: 0, limit: 50 }
    if (path === '/v1/ops/get_blocked_ai_users') result = { ok: true, users: [] }
    if (path === '/v1/ops/get_recent_logs') {
      const entries = logs.filter((entry) => entry.id > Number(body?.after_id ?? 0)).slice(0, body?.snapshot ? 500 : Number(body?.limit ?? 200))
      result = { ok: true, entries, next_after_id: Math.max(99, entries.at(-1)?.id ?? Number(body?.after_id ?? 0)) }
    }
    if (path === '/v1/ops/get_recent_commands') result = { ok: true, entries: logs.filter((entry) => entry.event_kind === 'command.terminal').slice(-5).reverse() }
    if (path === '/v1/ops/get_analytics') result = { ok: false, error: 'Analytics data has no fixture for this test' }
    if (path === '/v1/ops/get_about_info') result = { application_name: 'HeetKit', application_subtitle: 'Twitch bot controls', version: '1.3.0', author: 'heeetz', license_name: 'Apache-2.0' }
    await route.fulfill({ json: result })
  })
  return { calls,
    setPlayground: (pending: boolean, status = 'success', generation = playgroundGeneration) => {
      playgroundPending = pending
      playgroundStatus = status
      playgroundGeneration = generation
    },
    setStatus: (values: StatusOverrides) => { Object.assign(status, values) },
    setLogs: (entries: LogEntry[]) => { logs = entries },
    setTwitch: (values: Record<string, unknown>) => { Object.assign(twitch, values) },
    expire: (value = true) => { expired = value },
    fail: (path: string) => { fail = path },
    setTwitchCredential: (values: Partial<typeof credentials[number]>) => { Object.assign(credentials[0], values) },
    setOAuthBegin: (result: object) => { oauthBeginResult = result },
    setOAuthComplete: (result: object) => { oauthCompleteResult = result },
  }
}

export async function login(page: Page) {
  await page.getByLabel('Administrator token').fill(adminToken)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible()
}

export async function signIn(page: Page) {
  await page.goto('/tests/browser.fixture.html')
  await login(page)
}

export function navigate(page: Page, name: string) {
  return page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name, exact: true }).click()
}

export async function openSection(trigger: Locator) {
  if (await trigger.getAttribute('aria-expanded') !== 'true') await trigger.click()
  await expect(trigger).toHaveAttribute('aria-expanded', 'true')
}

export async function expectNoOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
}

export async function selectOption(control: Locator, value: string) {
  await control.click()
  const page = control.page()
  await page.getByRole('option').and(page.locator('[data-value=' + JSON.stringify(value) + ']')).click()
}

type AIBehaviorSection = 'Profile instructions' | 'Personalities' | 'Shared instructions' | 'Response languages'

const sectionIds = {
  'Profile instructions': 'ai-profile-instructions',
  Personalities: 'ai-personalities',
  'Shared instructions': 'ai-shared-instructions',
  'Response languages': 'ai-language',
}

function aiBehaviorDialog(page: Page) {
  return page.getByRole('dialog', { name: 'Edit AI behavior', exact: true })
}

export async function openAIBehaviorSection(page: Page, section: AIBehaviorSection) {
  const dialog = aiBehaviorDialog(page)
  if (await dialog.isVisible()) {
    await dialog.getByRole('navigation', { name: 'AI behavior sections' }).getByRole('button', { name: section, exact: true }).click()
  } else {
    await page.locator('#ai-behavior').getByRole('button', { name: `Edit ${section.toLowerCase()}`, exact: true }).click()
  }
  return dialog.locator(`#${sectionIds[section]}`)
}

export async function closeAIBehavior(page: Page) {
  await aiBehaviorDialog(page).getByRole('button', { name: 'Close editor', exact: true }).click()
}
