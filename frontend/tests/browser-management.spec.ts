import { expect, test, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import type { AIPlaygroundResult, AnnouncementInfo, AnnouncementInput, CommandInfo, CustomCommandInfo, FilterInput, LogEntry } from '../src/bridge'
import { selectOption } from './select-helpers'

const adminToken = 'a'.repeat(43)
const sessionToken = 's'.repeat(43)
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
  running: boolean
  twitch_connected: boolean
  twitch_connection_state: 'stopped' | 'connecting' | 'connected' | 'reconnecting' | 'auth_required' | 'failed'
}>

async function server(page: Page, operationOverrides: OperationOverrides = {}, statusOverrides: StatusOverrides = {}, aiConfigured = true) {
  const calls: Call[] = []
  let expired = false
  let logs: LogEntry[] = []
  let fail = ''
  let filters: FilterInput = { words: ['synthetic'], phrases: [], patterns: [] }
  let profile = 'Saved instructions'
  let prompt = 'Neutral prompt'
  let customCommands: CustomCommandInfo[] = []
  let commandRestrictions: { id: string; channel_id: string; twitch_user_id: string; username: string; command_ids: string[]; expires_at: string | null; note: string }[] = []
  let announcements: AnnouncementInfo[] = []
  let enabled = true
  let playgroundPending = false
  let playgroundCancelled = false
  let playgroundReadDelay = 0
  let playgroundStatus = 'success'
  let playgroundGeneration: NonNullable<AIPlaygroundResult['generation']> = { provider: 'DeepSeek', model: 'deepseek-v4-pro', thinking: 'high',
    fallback_used: true, search_enabled: true, search_requested: true, search_used: true }
  let oauthBeginResult: object = { ok: true, url: 'https://id.twitch.tv/oauth2/authorize?client_id=synthetic', expires_in: 300 }
  let oauthCompleteResult: object = { ok: true }
  const command: CommandInfo = {
    name: 'ping', primary_name: 'ping', aliases: [], enabled: true, available: true, unavailable_reason: null,
    response_pool: { responses: ['Pong'], defaults: ['Pong'], saved: true, has_saved_override: false, response_mode: 'single', max_responses: 1 },
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
  const status = { running: true, twitch_connected: true, twitch_connection_state: 'connected' as const, uptime_seconds: 10, channel: 'synthetic_channel', account: 'synthetic_bot', ...statusOverrides, operation }
  const ai = () => ({ enabled, available: aiConfigured, memory_enabled: false, active_personality: 'neutral', available_personalities: ['neutral'], model: 'test-model' })
  const aiProvider = { provider: 'Gemini', selected_model: 'test-model', fallback_model: 'test-fallback', presets: [], credential: null }
  let aiSetup = { primary: { provider: 'gemini', model: 'gemini-2.5-flash', thinking: 'default', search: false },
    fallback: null, cross_provider_acknowledged: false, max_question_length: 300, max_answer_length: 220,
    shared_instructions: null, provider_drafts: {} }
  let setupGuide = { dismissed: false, ai_skipped: false }
  const twitch: Record<string, unknown> = { client_id: 'synthetic-client', bot_username: 'synthetic_bot', bot_user_id: '100', target_channel: 'synthetic_channel', target_channel_user_id: '200', active_channel: 'synthetic_channel', requires_restart: false, requires_reconnect: false, oauth_token_available: true, oauth_callback_url: 'http://localhost:8765/oauth/callback', authorization_status: 'verified', authorized_account: 'synthetic_bot', setup_complete: true }
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
    if (path === '/v1/ai/playground/start') {
      playgroundCancelled = false
      result = { ok: true, request_id: 'server-playground', status: 'pending' }
    }
    if (path === '/v1/ai/playground/cancel') playgroundCancelled = true
    if (path === '/v1/ai/playground/result') {
      if (playgroundReadDelay) await new Promise((resolve) => setTimeout(resolve, playgroundReadDelay))
      result = playgroundCancelled ? { ok: true, status: 'cancelled' }
        : playgroundPending ? { ok: true, status: 'pending' }
        : { ok: true, status: playgroundStatus, text: playgroundGeneration.provider === 'OpenAI' ? 'Fresh fact https://example.test/facts' : 'Synthetic server answer <b>plain text</b>', generation: playgroundGeneration }
    }
    if (path === '/v1/snapshot') result = { status, ai_status: ai() }
    if (path === '/v1/status') result = { ...status, operation }
    if (path === '/v1/bot/mode') {
      operation = { ...operation, mode: body!.mode as 'always_on' | 'stream_only' | 'manual' | 'disabled', pending: false }
      status.operation = operation
    }
    if (path === '/v1/bot/stop') {
      operation = { ...operation, mode: 'manual', desired_running: false, pending: false }
      Object.assign(status, { operation, running: false, twitch_connected: false, twitch_connection_state: 'stopped' as const })
    }
    if (path === '/v1/setup') result = { ok: true, twitch, credentials, aiProvider }
    if (path === '/v1/setup/guide') {
      if (request.method() === 'POST') setupGuide = body as typeof setupGuide
      result = { ok: true, ...setupGuide }
    }
    if (path === '/v1/ai/setup') {
      if (request.method() === 'POST') aiSetup = body!.settings as typeof aiSetup
      result = { ok: true, settings: aiSetup, providers: [
        { id: 'gemini', label: 'Google Gemini', credential: credentials[1], models: ['gemini-2.5-flash'], selected_model: 'gemini-2.5-flash', fallback_model: 'gemini-2.5-pro' },
        { id: 'deepseek', label: 'DeepSeek', credential: credentials[2], models: ['deepseek-flash'], selected_model: 'deepseek-flash', fallback_model: 'deepseek-v4-pro' },
        { id: 'openai', label: 'OpenAI', credential: { name: 'openai_api_key', label: 'OpenAI API key', configured: true, source: 'server_file', managed: true }, models: ['gpt-6-luna'], selected_model: 'gpt-6-luna', fallback_model: 'gpt-6.1-sol' },
      ], capabilities: { gemini: { 'gemini-2.5-flash': { known: true, thinking_options: [{ value: 'default', label: 'Provider default' }, { value: 'off', label: 'Off' }], search_supported: true, search_reason: 'Google Suggestions display required', attribution_required: true } },
        deepseek: { 'deepseek-flash': { known: true, thinking_options: [{ value: 'default', label: 'Provider default' }, { value: 'off', label: 'Off' }, { value: 'high', label: 'High' }], search_supported: true, search_reason: 'Bounded provider search', attribution_required: false } },
        openai: { 'gpt-6-luna': { known: true, thinking_options: [{ value: 'default', label: 'Provider default' }, { value: 'none', label: 'None' }, { value: 'low', label: 'Low' }], search_supported: true, search_reason: 'OpenAI Web Search with inline source URLs', attribution_required: false } } },
        default_shared_instructions: 'Shared defaults', retained_restrictions: 'Local request and output checks remain enabled.' }
    }
    if (path === '/v1/ai/models/discover') result = { ok: true, provider_id: body?.provider, models: ['deepseek-flash'] }
    if (path === '/v1/twitch/settings') {
      Object.assign(twitch, {
        client_id: body!.client_id,
        bot_username: body!.bot_username,
        bot_user_id: body!.bot_user_id,
        target_channel: body!.channel,
        target_channel_user_id: body!.channel_user_id,
      })
      result = { ok: true, requires_reconnect: true }
    }
    if (path === '/v1/twitch/authorization/begin') result = oauthBeginResult
    if (path === '/v1/twitch/authorization/complete') result = oauthCompleteResult
    if (path === '/v1/twitch/authorization/cancel') result = { ok: true }
    if (['/v1/credentials/replace', '/v1/credentials/remove', '/v1/credentials/test'].includes(path)) {
      const credential = credentials.find((item) => item.name === body?.name)
      if (!credential) result = { ok: false, error: 'Unknown credential' }
      else if (path.endsWith('/test')) { credential.validation_status = 'valid'; result = { ok: true } }
      else if (!credential.managed) result = { ok: false, error: 'Managed externally' }
      else {
        const configured = path.endsWith('/replace')
        Object.assign(credential, { configured, source: configured ? 'server_file' : 'missing', validation_status: 'not_tested' })
        result = { ok: true, changed: true }
      }
    }
    if (path === '/v1/ai') result = ai()
    if (path === '/v1/ai/enabled') enabled = body!.enabled as boolean
    if (path === '/v1/ai/models') result = { ok: true, settings: aiProvider }
    if (path === '/v1/ai/language') result = { ok: true, settings: { mode: 'auto', allowed_languages: ['en'], fallback_language: 'en' }, languages: [{ code: 'en', label: 'English' }], active_policy: 'Auto' }
    if (path === '/v1/commands') result = { command_prefix: '!', permissions: ['EVERYONE', 'MODERATOR'], commands: [command] }
    if (path === '/v1/commands/save' || path === '/v1/commands/apply') {
      command.cooldown.per_user_seconds = body!.per_user_seconds as number
      const options = body!.options as { primary_name?: string; stream_availability?: CommandInfo['stream_availability'] } | undefined
      if (options?.primary_name) command.primary_name = options.primary_name
      if (options?.stream_availability) command.stream_availability = options.stream_availability
      command.has_saved_override = true
    }
    if (path === '/v1/commands/reset') Object.assign(command, structuredClone(command.default_settings), { has_saved_override: false })
    if (path === '/v1/commands/responses/save' || path === '/v1/commands/responses/apply') command.response_pool!.responses = body!.responses as string[]
    if (path === '/v1/custom-commands') result = { command_prefix: '!', permissions: ['EVERYONE', 'MODERATOR'], variables: ['sender'], commands: customCommands }
    if (path === '/v1/command-restrictions') result = { ok: true, channel_id: '200', commands: [{ id: 'ping', label: '!ping' }], restrictions: commandRestrictions }
    if (path === '/v1/command-restrictions/save') {
      const data = body!.data as { id?: string; username: string; command_ids: string[]; expires_at: string | null; note: string }
      const row = { id: data.id ?? 'http-restriction', channel_id: '200', twitch_user_id: '1234', username: data.id ? 'httpviewer' : data.username, command_ids: data.command_ids, expires_at: data.expires_at, note: data.note }
      commandRestrictions = [...commandRestrictions.filter((item) => item.id !== row.id), row]
      result = { ok: true, channel_id: '200', commands: [{ id: 'ping', label: '!ping' }], restrictions: commandRestrictions }
    }
    if (path === '/v1/command-restrictions/remove') {
      commandRestrictions = commandRestrictions.filter((item) => item.id !== body!.restriction_id)
      result = { ok: true, channel_id: '200', commands: [{ id: 'ping', label: '!ping' }], restrictions: commandRestrictions }
    }
    if (path === '/v1/custom-commands/save') customCommands = [{ ...(body!.command as CustomCommandInfo), id: 'saved-command' }]
    if (path === '/v1/announcements') {
      if (request.method() === 'POST') announcements = (body!.announcements as AnnouncementInput[]).map((item, index) => ({
        ...item, id: item.id ?? `00000000-0000-0000-0000-${String(index + 1).padStart(12, '0')}`,
        status: { next_run_at: null, last_sent_at: null, last_outcome: null, eligible_messages: 0 },
      }))
      result = { ok: true, announcements }
    }
    if (path === '/v1/filters') result = Object.fromEntries(Object.entries(filters).map(([category, values]) => [category, { rules: (values as string[]).map((value: string) => ({ value, origin: 'local', valid: true })), defaults: [] }]))
    if (path === '/v1/filters/save' || path === '/v1/filters/apply') filters = body!.payload as unknown as FilterInput
    if (path === '/v1/ai/instructions/save' || path === '/v1/ai/instructions/apply') profile = body!.prompt as string
    if (path === '/v1/personalities/save' || path === '/v1/personalities/apply') prompt = body!.prompt as string
    if (path === '/v1/personalities') result = { active_personality: 'neutral', active_personality_saved: true, personalities: [{ name: 'neutral', prompt, built_in_prompt: 'Neutral prompt', is_builtin: true, prompt_saved: true, has_saved_override: false }], profile_instructions: profile, profile_instructions_saved: true, protected_shared_instructions: 'Protected policy' }
    if (path === '/v1/blocked-users') result = { ok: true, users: [] }
    if (path === '/v1/logs/recent') result = { ok: true, entries: logs.filter((entry) => entry.id > Number(body?.after_id ?? 0)), next_after_id: 99 }
    if (path === '/v1/about') result = { application_name: 'HeetKit', application_subtitle: 'Twitch bot controls', version: '1.3.0', author: 'heeetz', license_name: 'Apache-2.0' }
    await route.fulfill({ json: result })
  })
  return { calls, setPlayground: (pending: boolean, readDelay = 0, status = 'success', generation = playgroundGeneration) => { playgroundPending = pending; playgroundReadDelay = readDelay; playgroundStatus = status; playgroundGeneration = generation }, setLogs: (entries: LogEntry[]) => { logs = entries }, setTwitch: (values: Record<string, unknown>) => { Object.assign(twitch, values) }, expire: (value = true) => { expired = value }, fail: (path: string) => { fail = path }, setOperation: (values: OperationOverrides) => { operation = { ...operation, ...values }; status.operation = operation }, setOAuthBegin: (result: object) => { oauthBeginResult = result }, setOAuthComplete: (result: object) => { oauthCompleteResult = result } }
}

async function login(page: Page) {
  await page.getByLabel('Administrator token').fill(adminToken)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible()
}

test('Server OpenAI controls and Playground preserve native options, usage and clickable sources', async ({ page }) => {
  const api = await server(page)
  await page.setViewportSize({ width: 390, height: 1000 })
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await page.getByRole('navigation').getByRole('button', { name: 'AI setup', exact: true }).click()
  const setup = page.locator('#ai-models')
  await selectOption(setup.getByLabel('Primary provider'), 'openai')
  await selectOption(setup.getByLabel('Primary thinking'), 'none')
  await setup.getByLabel('Primary internet search', { exact: true }).press('Space')
  await setup.getByRole('button', { name: 'Save AI setup', exact: true }).click()
  await expect(setup).toContainText('AI setup saved')
  expect(api.calls.filter((call) => call.path === '/v1/ai/setup' && call.method === 'POST').at(-1)?.body?.settings).toMatchObject({ primary: { provider: 'openai', model: 'gpt-6-luna', thinking: 'none', search: true } })
  api.setPlayground(false, 0, 'success', { provider: 'OpenAI', model: 'gpt-6-luna', thinking: 'none',
    fallback_used: false, search_enabled: true, search_requested: true, search_used: true,
    input_tokens: 150, output_tokens: 25 })
  await page.getByRole('button', { name: 'Playground', exact: true }).click()
  const playground = page.locator('#ai-playground')
  await playground.getByLabel('Playground prompt').fill('Latest fact?')
  await playground.getByRole('button', { name: 'Test prompt', exact: true }).click()
  await expect(playground.getByRole('status')).toContainText('Provider: OpenAI')
  await expect(playground.getByRole('status')).toContainText('Input tokens: 150')
  await expect(playground.getByRole('link', { name: 'https://example.test/facts' })).toHaveAttribute('href', 'https://example.test/facts')
  await page.screenshot({ path: 'node_modules/.tmp/task11-openai-server-390.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})

test('Server restrictions use the authenticated management endpoints and exact payloads', async ({ page }) => {
  const api = await server(page)
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  await page.getByRole('button', { name: 'Commands', exact: true }).click()
  const panel = page.locator('#command-restrictions')
  await expect(panel.getByText('No active user restrictions.')).toBeVisible()
  await expect(panel).toContainText('New restrictions apply to configured channel ID 200.')
  expect(api.calls.some((call) => call.path === '/v1/command-restrictions' && call.method === 'GET')).toBe(true)
  await panel.getByRole('button', { name: 'Add restriction' }).click()
  await panel.getByLabel('Twitch username').fill('httpviewer')
  await panel.getByRole('button', { name: 'Save restriction' }).click()
  await expect(panel.getByText('httpviewer', { exact: true })).toBeVisible()
  expect(api.calls.find((call) => call.path === '/v1/command-restrictions/save')?.body).toEqual({ data: {
    username: 'httpviewer', command_ids: [], expires_at: null, note: '',
  } })
  await panel.getByRole('button', { name: 'Remove' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Confirm' }).click()
  expect(api.calls.find((call) => call.path === '/v1/command-restrictions/remove')?.body).toEqual({ restriction_id: 'http-restriction' })
})

for (const width of [1280, 390, 320]) {
  test(`Server Playground uses authenticated typed controls and reports effective options at ${width}px`, async ({ page }) => {
    const api = await server(page)
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/tests/browser.fixture.html')
    await login(page)
    await page.getByRole('button', { name: 'AI', exact: true }).click()
    await page.getByRole('button', { name: 'Playground', exact: true }).click()
    const playground = page.locator('#ai-playground')
    await playground.getByLabel('Playground prompt').fill('Latest news?')
    await playground.getByRole('button', { name: 'Test prompt', exact: true }).click()
    await expect(playground.getByRole('status')).toContainText('Synthetic server answer <b>plain text</b>')
    await expect(playground.locator('.playground-response b')).toHaveCount(0)
    await expect(playground.getByRole('status')).toContainText('Provider: DeepSeek · Model: deepseek-v4-pro · Thinking: high · Fallback used · Search/Fetch: Used')
    const start = api.calls.find((call) => call.path === '/v1/ai/playground/start')!
    expect(start.body).toEqual({ prompt: 'Latest news?' })
    expect(start.authorization).toBe(`Bearer ${sessionToken}`)
    expect(api.calls.filter((call) => call.path.startsWith('/v1/ai/playground/')).every((call) => call.method === 'POST')).toBeTruthy()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.screenshot({ path: `node_modules/.tmp/server-playground-${width}.png`, fullPage: true })
    api.setPlayground(true)
    await playground.getByRole('button', { name: 'Test prompt', exact: true }).click()
    await playground.getByRole('button', { name: 'Cancel request', exact: true }).click()
    await expect(playground.getByRole('status')).toContainText('Cancelled')
    expect(api.calls.find((call) => call.path === '/v1/ai/playground/cancel')?.body).toEqual({ request_id: 'server-playground' })
    await playground.getByRole('button', { name: 'Test prompt', exact: true }).click()
    await expect.poll(() => api.calls.filter((call) => call.path === '/v1/ai/playground/start').length).toBe(3)
    await page.getByRole('button', { name: 'Commands', exact: true }).click()
    await expect.poll(() => api.calls.filter((call) => call.path === '/v1/ai/playground/cancel').length).toBe(2)
    await page.getByRole('button', { name: 'AI', exact: true }).click()
    const profile = page.locator('#ai-profile-instructions')
    await profile.locator('.accordion-trigger').click()
    await profile.locator('textarea').fill('Unsaved server draft')
    await profile.getByRole('button', { name: 'Open Playground', exact: true }).click()
    await expect(profile).toContainText('Choose what Playground will use')
    await profile.getByRole('button', { name: 'Use current applied settings' }).click()
    await expect(playground).toContainText('Unsaved editor drafts are not used')
  })
}

for (const end of ['logout', 'expiry']) {
  test(`Server Playground rejects results arriving after ${end}`, async ({ page }) => {
    const api = await server(page)
    api.setPlayground(false, 800)
    await page.goto('/tests/browser.fixture.html')
    await login(page)
    await page.getByRole('button', { name: 'AI', exact: true }).click()
    const playground = page.locator('#ai-playground')
    await playground.getByLabel('Playground prompt').fill('Private operator prompt')
    await playground.getByRole('button', { name: 'Test prompt', exact: true }).click()
    await expect.poll(() => api.calls.some((call) => call.path === '/v1/ai/playground/result')).toBeTruthy()
    if (end === 'logout') await page.getByRole('button', { name: 'Sign out', exact: true }).click()
    else {
      api.expire()
      await page.getByRole('button', { name: 'Commands', exact: true }).click()
    }
    await expect(page.getByLabel('Administrator token')).toBeVisible()
    await expect(playground).toHaveCount(0)
    await page.waitForTimeout(900)
    await expect(page.getByText('Synthetic server answer', { exact: false })).toHaveCount(0)
  })
}

for (const width of [1280, 390, 320]) {
  test(`browser setup guide remains available without AI and has bounded actions at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await server(page, {}, {}, false)
    await page.goto('/tests/browser.fixture.html')
    await login(page)
    const checklist = page.getByRole('article', { name: 'Setup checklist' })
    await expect(checklist.locator('.section-heading p')).toHaveText('Twitch connected · AI optional')
    await expect(checklist).not.toContainText(/unverified|not confirmed/)
    const bounds = (await checklist.boundingBox())!
    for (const action of await checklist.getByRole('button').all()) {
      const box = (await action.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(bounds.x)
      expect(box.x + box.width).toBeLessThanOrEqual(bounds.x + bounds.width)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.screenshot({ path: `node_modules/.tmp/server-setup-guide-${width}.png`, fullPage: true })
    await checklist.getByRole('button', { name: 'Open AI setup' }).click()
    await expect(page.locator('#ai-models')).toBeInViewport()
  })
  test(`browser setup summary disappears with Twitch and an unselected configured provider at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    const api = await server(page)
    const setupLoaded = page.waitForResponse((response) => new URL(response.url()).pathname === '/v1/setup/guide')
    await page.goto('/tests/browser.fixture.html')
    await login(page)
    await setupLoaded
    await expect(page.locator('.dashboard-card').first().getByRole('heading')).toHaveText('Connected')
    await expect(page.getByRole('article', { name: 'Setup checklist' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Resume setup guide' })).toHaveCount(0)
    expect(api.calls.find((call) => call.path === '/v1/setup')?.authorization).toBe(`Bearer ${sessionToken}`)
  })
}

async function invoke(page: Page, method: string, args: unknown[] = []) {
  return page.evaluate(async ({ method, args }) => {
    const modulePath = '/src/bridge.ts'
    const module = await import(modulePath)
    const api = await module.waitForBridge()
    try { return await api[method](...args) } catch (error) { return { error: error instanceof Error ? error.message : 'failed' } }
  }, { method, args })
}

test('Server announcements save highlighted delivery through authenticated fixed routes', async ({ page }) => {
  const api = await server(page)
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  await page.getByRole('button', { name: 'Commands', exact: true }).click()
  const panel = page.locator('#announcements')
  await panel.getByRole('button', { name: 'New announcement', exact: true }).click()
  await panel.getByLabel('Name', { exact: true }).fill('Server reminder')
  await panel.getByLabel('Announcement message', { exact: true }).fill('A scheduled ordinary message.')
  await selectOption(panel.getByLabel('Works when:', { exact: true }), 'live_only')
  await panel.getByRole('button', { name: 'Save announcements', exact: true }).click()
  await expect(panel.getByRole('status')).toContainText('Announcements saved')
  const write = api.calls.find((call) => call.path === '/v1/announcements' && call.method === 'POST')
  expect(write).toMatchObject({ authorization: `Bearer ${sessionToken}`, body: { announcements: [{
    id: null, name: 'Server reminder', enabled: true, messages: ['A scheduled ordinary message.'], message_mode: 'single',
    delivery_mode: 'highlighted', interval_seconds: 900, min_messages: 0, stream_availability: 'live_only',
  }] } })
  expect(api.calls.filter((call) => call.path === '/v1/announcements').every((call) => call.authorization === `Bearer ${sessionToken}`)).toBe(true)
  await panel.getByRole('button', { name: 'Help: Announcement status Server reminder', exact: true }).click()
  await expect(page.getByRole('tooltip')).toContainText('Last outcome: No attempts yet')
})

test('browser login keeps tokens out of storage, URLs and request bodies; reload signs out', async ({ page, context }) => {
  const api = await server(page)
  await context.addCookies([{ name: 'unrelated', value: 'cookie', url: 'http://127.0.0.1:5174' }])
  await page.addInitScript(() => {
    const nativeFetch = window.fetch
    Object.assign(window, { fetchOptions: [] })
    window.fetch = (input, options) => {
      Reflect.get(window, 'fetchOptions').push({ credentials: options?.credentials, redirect: options?.redirect })
      return nativeFetch(input, options)
    }
  })
  await page.goto('/tests/browser.fixture.html')
  expect(api.calls).toEqual([])
  await login(page)
  await expect(page.getByLabel('Administrator token')).toHaveCount(0)
  expect(api.calls[0]).toEqual({ method: 'POST', path: '/v1/session', body: {}, authorization: `Bearer ${adminToken}` })
  expect(api.calls.slice(1).every((call) => call.authorization === `Bearer ${sessionToken}`)).toBe(true)
  expect(api.calls.every((call) => !JSON.stringify(call.body).includes(adminToken) && !JSON.stringify(call.body).includes(sessionToken))).toBe(true)
  expect(page.url()).not.toContain(adminToken)
  expect(await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage }, cookie: document.cookie }))).toEqual({ local: {}, session: {}, cookie: 'unrelated=cookie' })
  expect(await page.evaluate(() => Reflect.get(window, 'fetchOptions').every((options: { credentials: string; redirect: string }) => options.credentials === 'omit' && options.redirect === 'error'))).toBe(true)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Sign in to server' })).toBeVisible()
})

test('browser route payloads use explicit server fields and request failures stay actionable', async ({ page }) => {
  const api = await server(page)
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  await invoke(page, 'save_command_settings', ['ping', true, 3, 4, 'MODERATOR', { aliases: ['pong'], display_name: 'Ping', stream_availability: 'offline_only', unexpected: 'discarded' }])
  expect(api.calls.at(-1)).toMatchObject({ path: '/v1/commands/save', body: { command_name: 'ping', enabled: true, per_user_seconds: 3, global_seconds: 4, permission: 'MODERATOR', options: { aliases: ['pong'], display_name: 'Ping', stream_availability: 'offline_only' } } })
  await invoke(page, 'save_command_responses', ['ping', ['Changed']])
  expect(api.calls.at(-1)?.body).toEqual({ name: 'ping', responses: ['Changed'] })
  await invoke(page, 'rename_personality', ['old', 'new'])
  expect(api.calls.at(-1)?.body).toEqual({ personality: 'old', name: 'new' })
  await invoke(page, 'update_ai_provider_settings', ['primary', 'fallback'])
  expect(api.calls.at(-1)?.body).toEqual({ selected_model: 'primary', fallback_model: 'fallback', provider: 'gemini' })
  await invoke(page, 'update_ai_provider_settings', ['deepseek-flash', 'deepseek-v4-pro', 'deepseek'])
  expect(api.calls.at(-1)?.body).toEqual({ selected_model: 'deepseek-flash', fallback_model: 'deepseek-v4-pro', provider: 'deepseek' })
  await invoke(page, 'update_ai_provider_settings', [null, null, 'gemini'])
  expect(api.calls.at(-1)?.body).toEqual({ selected_model: null, fallback_model: null, provider: 'gemini' })
  await invoke(page, 'discover_ai_models', ['deepseek'])
  expect(api.calls.at(-1)).toMatchObject({ path: '/v1/ai/models/discover', body: { provider: 'deepseek' } })
  await invoke(page, 'discover_gemini_models')
  expect(api.calls.at(-1)?.body).toEqual({ provider: 'gemini' })
  await invoke(page, 'export_configuration')
  expect(api.calls.at(-1)).toMatchObject({ path: '/v1/configuration/export', body: {} })
  await invoke(page, 'preview_configuration_import', ['cG9ydGFibGU='])
  expect(api.calls.at(-1)).toMatchObject({ path: '/v1/configuration/preview', body: { archive_base64: 'cG9ydGFibGU=' } })
  await invoke(page, 'apply_configuration_import', ['cG9ydGFibGU=', 'preview-token', true])
  expect(api.calls.at(-1)).toMatchObject({ path: '/v1/configuration/import', body: {
    archive_base64: 'cG9ydGFibGU=', preview_token: 'preview-token', confirmed: true,
  } })
  await page.evaluate(() => {
    Object.assign(window, { openedLinks: [] })
    window.open = (...args) => { Reflect.get(window, 'openedLinks').push(args); return null }
  })
  await invoke(page, 'open_external_link', ['repository'])
  expect(await page.evaluate(() => Reflect.get(window, 'openedLinks'))).toEqual([['https://github.com/heeetz/twitch-bot', '_blank', 'noopener,noreferrer']])
  const before = api.calls.length
  expect(await invoke(page, 'open_profile_folder')).toMatchObject({ error: expect.stringMatching(/desktop/) })
  expect(api.calls).toHaveLength(before)
  api.fail('/v1/status')
  expect(await invoke(page, 'get_app_status')).toEqual({ error: 'Could not reach the server. Check the connection and retry.' })
  api.fail('')
  expect(await invoke(page, 'get_app_status')).toMatchObject({ running: true })
})

test('browser dashboard exposes operation policy, broadcaster uncertainty and pending lifecycle state', async ({ page }) => {
  const api = await server(page, {
    stream_status: 'unknown', last_known_stream_status: 'offline', pending: true,
  })
  await page.goto('/tests/browser.fixture.html')
  await login(page)

  const operation = page.locator('.dashboard-operation-card')
  await expect(operation.getByRole('heading', { name: 'Always On', exact: true })).toBeVisible()
  await expect(operation).toContainText('Broadcaster statusUnknown')
  await expect(operation).toContainText('Last known statusOffline')
  await expect(operation).toContainText('Broadcaster live status is currently unknown. It is only used for Stream Only')
  await expect(page.getByRole('button', { name: 'Reconciling…', exact: true })).toBeDisabled()

  const mode = page.getByRole('combobox', { name: 'Operation mode', exact: true })
  await expect(mode).toBeEnabled()
  await mode.click()
  await page.getByRole('option', { name: 'Manual', exact: true }).click()
  await expect.poll(() => api.calls.find((call) => call.path === '/v1/bot/mode')?.body).toEqual({ mode: 'manual' })
  await expect(operation.getByRole('heading', { name: 'Manual', exact: true })).toBeVisible()
  await expect(operation).toContainText('Manual mode lets you connect or disconnect')
})

test('offline automatic operation always disconnects and persists Manual before stopping', async ({ page }) => {
  const api = await server(page, {
    mode: 'stream_only', desired_running: false, stream_status: 'offline', last_known_stream_status: 'offline',
  }, { running: false, twitch_connected: false, twitch_connection_state: 'stopped' })
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  await expect(page.getByRole('button', { name: 'Switch to Manual & disconnect', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Switch to Manual & disconnect', exact: true }).click()
  await expect.poll(() => api.calls.find((call) => call.path === '/v1/bot/stop')).toMatchObject({ method: 'POST', body: {} })
  await expect(page.locator('.dashboard-operation-card').getByRole('heading', { name: 'Manual', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Connect', exact: true })).toBeVisible()
})

test('disabled browser operation mode removes connect control and explains how to enable it', async ({ page }) => {
  await server(page, { mode: 'disabled', desired_running: false, stream_status: 'offline', last_known_stream_status: 'offline' })
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  const operation = page.locator('.dashboard-operation-card')
  await expect(operation.getByRole('heading', { name: 'Disabled', exact: true })).toBeVisible()
  await expect(operation).toContainText('Connecting is disabled. Choose Always On, Stream Only or Manual to enable it.')
  await expect(page.getByRole('button', { name: /Connect|Start Bot|Disconnect|Switch to Manual & disconnect/, exact: false })).toHaveCount(0)
})

test('server Commands saves and reopens thirty Random templates and rejects thirty-one', async ({ page }) => {
  const api = await server(page)
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  await page.getByRole('button', { name: 'Commands', exact: true }).click()
  await page.getByRole('button', { name: 'New command', exact: true }).click()
  const editor = page.locator('.custom-command-editor')
  await editor.getByLabel('Command name', { exact: true }).fill('randompool')
  await selectOption(editor.getByLabel('Response type', { exact: true }), 'random')
  const responses = Array.from({ length: 30 }, (_, index) => `Reply ${index} to {sender}`)
  const text = editor.getByRole('textbox', { name: 'Responses', exact: true })
  await text.fill([...responses, 'One too many'].join('\n'))
  await editor.getByRole('button', { name: 'Save command', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('1 to 30 response templates')
  expect(api.calls.filter((call) => call.path === '/v1/custom-commands/save')).toEqual([])
  await text.fill(responses.join('\n'))
  await editor.getByRole('button', { name: 'Save command', exact: true }).click()
  await expect(editor).toHaveCount(0)
  expect(api.calls.find((call) => call.path === '/v1/custom-commands/save')?.body).toMatchObject({
    command: { response_mode: 'random', responses },
  })
  const row = page.locator('.custom-command-row').filter({ has: page.getByText('!randompool', { exact: true }) })
  await row.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(text).toHaveValue(responses.join('\n'))
})

for (const width of [1280, 900, 390, 320]) {
  test(`existing browser pages save server drafts and hide native actions at ${width}px`, async ({ page }) => {
    const api = await server(page)
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/tests/browser.fixture.html')
    await login(page)
    await page.getByRole('button', { name: 'Commands', exact: true }).click()
    const command = page.locator('.command-card').first()
    await command.getByRole('button', { name: 'Edit !ping', exact: true }).click()
    const enabled = command.locator('.command-enabled-toggle')
    const settings = command.locator('.command-fields > label')
    await expect(settings).toHaveCount(4)
    await expect(settings).toHaveText([/Permission/, /Stream availability/, /Per-user cooldown/, /Global cooldown/])
    const enabledBounds = (await enabled.boundingBox())!
    const settingsBounds = await Promise.all(Array.from({ length: 4 }, (_, index) => settings.nth(index).boundingBox()))
    expect(enabledBounds.y + enabledBounds.height).toBeLessThanOrEqual(settingsBounds[0]!.y)
    if (width > 760) {
      expect(settingsBounds[0]!.y).toBeCloseTo(settingsBounds[1]!.y, 0)
      expect(settingsBounds[2]!.y).toBeCloseTo(settingsBounds[3]!.y, 0)
      expect(settingsBounds[2]!.y).toBeGreaterThan(settingsBounds[0]!.y)
      expect(settingsBounds[0]!.x).toBeCloseTo(settingsBounds[2]!.x, 0)
      expect(settingsBounds[1]!.x).toBeCloseTo(settingsBounds[3]!.x, 0)
      for (const bounds of settingsBounds.slice(1)) expect(bounds!.width).toBeCloseTo(settingsBounds[0]!.width, 0)
    } else {
      for (let index = 1; index < settingsBounds.length; index++) {
        expect(settingsBounds[index]!.y).toBeGreaterThan(settingsBounds[index - 1]!.y)
        expect(settingsBounds[index]!.width).toBeCloseTo(settingsBounds[0]!.width, 0)
      }
    }
    const availability = command.getByLabel('Stream availability', { exact: true })
    await expect(availability).toHaveAttribute('data-value', 'live_only')
    await availability.focus()
    await availability.press('End')
    await availability.press('Enter')
    await expect(availability).toBeFocused()
    await expect(availability).toHaveAttribute('data-value', 'offline_only')
    const availabilityBounds = await availability.boundingBox()
    const cooldownBounds = await command.getByLabel('Per-user cooldown').boundingBox()
    expect(availabilityBounds!.x).toBeGreaterThanOrEqual(0)
    expect(availabilityBounds!.x + availabilityBounds!.width).toBeLessThanOrEqual(width)
    expect(Math.abs(availabilityBounds!.width - cooldownBounds!.width)).toBeLessThanOrEqual(2)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await command.getByLabel('Per-user cooldown').fill('7')
    await command.getByLabel('Primary chat name', { exact: true }).fill('servercheck')
    await command.getByRole('button', { name: 'Save command', exact: true }).click()
    await expect.poll(() => api.calls.find((call) => call.path === '/v1/commands/save')?.body?.per_user_seconds).toBe(7)
    expect(api.calls.find((call) => call.path === '/v1/commands/save')?.body).toMatchObject({ command_name: 'ping', options: { primary_name: 'servercheck', stream_availability: 'offline_only' } })
    await expect(command.locator('.command-summary-title strong')).toHaveText('!servercheck')
    await command.getByRole('button', { name: 'Reset settings', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
    await expect(availability).toHaveAttribute('data-value', 'anytime')
    await expect(command.getByLabel('Primary chat name', { exact: true })).toHaveValue('ping')
    await page.getByRole('button', { name: 'New command', exact: true }).click()
    const custom = page.locator('.custom-command-editor')
    await expect(custom.getByLabel('Stream availability', { exact: true })).toHaveAttribute('data-value', 'anytime')
    await custom.getByLabel('Command name', { exact: true }).fill('browser')
    await custom.getByLabel('Message', { exact: true }).fill('Browser reply')
    await selectOption(custom.getByLabel('Stream availability', { exact: true }), 'offline_only')
    await custom.getByRole('button', { name: 'Save command', exact: true }).click()
    await expect.poll(() => api.calls.find((call) => call.path === '/v1/custom-commands/save')?.body).toMatchObject({ command: { stream_availability: 'offline_only' } })
    const customRow = page.locator('.custom-command-row').filter({ hasText: '!browser' })
    await customRow.getByRole('button', { name: 'Edit', exact: true }).click()
    await expect(custom.getByLabel('Stream availability', { exact: true })).toHaveAttribute('data-value', 'offline_only')
    await selectOption(custom.getByLabel('Stream availability', { exact: true }), 'live_only')
    await custom.getByRole('button', { name: 'Discard and close', exact: true }).click()
    await expect(page.getByRole('dialog').getByRole('heading')).toHaveText('Discard unsaved command changes?')
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(custom.getByLabel('Stream availability', { exact: true })).toHaveAttribute('data-value', 'live_only')
    const customBounds = await custom.getByLabel('Stream availability', { exact: true }).boundingBox()
    expect(customBounds!.x).toBeGreaterThanOrEqual(0)
    expect(customBounds!.x + customBounds!.width).toBeLessThanOrEqual(width)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await custom.getByRole('button', { name: 'Save command', exact: true }).click()
    await expect.poll(() => api.calls.filter((call) => call.path === '/v1/custom-commands/save').at(-1)?.body).toMatchObject({ command: { stream_availability: 'live_only' } })
    await page.getByRole('button', { name: 'Filters', exact: true }).click()
    const words = page.locator('#filters-words')
    await words.locator('.accordion-trigger').press('Enter')
    await words.getByRole('textbox').fill('saved browser filter')
    await page.getByRole('button', { name: 'Save filters', exact: true }).click()
    await expect(words.getByRole('textbox')).toHaveValue('saved browser filter')
    await page.getByRole('button', { name: 'AI', exact: true }).click()
    await expect(page.locator('#ai-playground')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Playground', exact: true })).toBeVisible()
    const personality = page.locator('#ai-personalities')
    await personality.locator('.accordion-trigger').press('Enter')
    await personality.getByLabel('Editable prompt').fill('Saved browser personality')
    await personality.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => api.calls.find((call) => call.path === '/v1/personalities/save')?.body).toEqual({ personality: 'neutral', prompt: 'Saved browser personality' })
    const profile = page.locator('#ai-profile-instructions')
    await profile.locator('.accordion-trigger').press('Enter')
    await profile.locator('textarea').fill('Saved browser instructions')
    await profile.getByRole('button', { name: 'Save', exact: true }).click()
    await expect.poll(() => api.calls.find((call) => call.path === '/v1/ai/instructions/save')?.body).toEqual({ prompt: 'Saved browser instructions' })
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Application, account and channel' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Configuration transfer' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Save Twitch settings', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Remove secret', exact: true })).toBeDisabled()
    await expect(page.getByRole('button', { name: /Open profile folder/ })).toHaveCount(0)
    await page.getByRole('button', { name: 'About', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Check for updates', exact: true })).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}

test('server settings edit Twitch identity, manage credentials and complete or cancel OAuth without retaining sensitive drafts', async ({ page }) => {
  const api = await server(page)
  // Delayed provider checks can outlive browser popup activation. Keep an
  // explicit validated link available even when window.open is blocked.
  await page.addInitScript(() => { window.open = () => null })
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Application, account and channel', exact: true })).toBeVisible()

  await page.getByLabel('Client ID').fill('new-client')
  await page.getByLabel('Bot account login').fill('new-bot')
  await page.getByLabel('Bot account user ID').fill('101')
  await page.getByLabel('Target channel login').fill('new-channel')
  await page.getByLabel('Target channel user ID').fill('201')
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Save Twitch settings', exact: true }).click()
  await expect.poll(() => api.calls.find((call) => call.path === '/v1/twitch/settings')?.body).toEqual({
    client_id: 'new-client', bot_username: 'new-bot', bot_user_id: '101', channel: 'new-channel', channel_user_id: '201',
  })
  await expect(page.getByRole('status')).toContainText('current session was stopped')

  const application = page.locator('[aria-labelledby="server-twitch-application-heading"]')
  await expect(application.getByLabel('Client ID')).toHaveValue('new-client')
  await expect(application.locator('.twitch-secret-field .credential-actions')).toBeVisible()

  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await page.getByRole('navigation').getByRole('button', { name: 'AI setup', exact: true }).click()
  const setup = page.locator('#ai-models')
  const gemini = setup.getByLabel('gemini API key', { exact: true })
  await gemini.fill('synthetic-gemini-secret')
  await setup.getByRole('button', { name: 'Connect Google Gemini key', exact: true }).click()
  await expect(gemini).toHaveValue('')
  await expect(setup.locator('.ai-provider-status .state-pill').first()).toHaveText('Configured')
  expect(api.calls.find((call) => call.path === '/v1/credentials/replace')?.body).toEqual({ name: 'gemini_api_key', value: 'synthetic-gemini-secret' })
  await setup.getByRole('button', { name: 'Test Google Gemini connection', exact: true }).click()
  expect(api.calls.find((call) => call.path === '/v1/credentials/test')?.body).toEqual({ name: 'gemini_api_key' })

  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await page.getByRole('button', { name: 'Connect Twitch', exact: true }).click()
  await expect.poll(() => api.calls.find((call) => call.path === '/v1/twitch/authorization/begin')?.body).toEqual({})
  await expect(page.getByRole('link', { name: 'Open Twitch authorization' })).toHaveAttribute('href', 'https://id.twitch.tv/oauth2/authorize?client_id=synthetic')
  await expect(page.getByRole('link', { name: 'Open Twitch authorization' })).toHaveAttribute('rel', 'noopener noreferrer')
  await page.getByLabel('Callback URL', { exact: true }).fill('http://localhost:8765/oauth/callback?code=synthetic&state=synthetic')
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect.poll(() => api.calls.find((call) => call.path === '/v1/twitch/authorization/cancel')?.body).toEqual({})
  await expect(page.getByLabel('Callback URL', { exact: true })).toHaveCount(0)

  await page.getByRole('button', { name: 'Connect Twitch', exact: true }).click()
  await page.getByLabel('Callback URL', { exact: true }).fill('http://localhost:8765/oauth/callback?error=access_denied&state=synthetic')
  api.setOAuthComplete({ ok: false, error: 'Twitch authorization was denied. Try again.' })
  await page.getByRole('button', { name: 'Complete authorization', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Twitch authorization was denied')
  await expect(page.getByLabel('Callback URL', { exact: true })).toHaveValue('')

  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await page.getByRole('navigation').getByRole('button', { name: 'AI setup', exact: true }).click()
  await gemini.fill('sensitive-draft')
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await page.getByRole('navigation').getByRole('button', { name: 'AI setup', exact: true }).click()
  await expect(gemini).toHaveValue('')

  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  api.setOAuthBegin({ ok: true, url: 'http://evil.example/oauth2/authorize', expires_in: 300 })
  await page.getByRole('button', { name: 'Connect Twitch', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('untrusted Twitch authorization URL')
})

for (const width of [1280, 900, 390, 320]) {
  test(`server Twitch settings keep application controls and field pairs aligned at ${width}px`, async ({ page }) => {
    const api = await server(page)
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/tests/browser.fixture.html')
    await login(page)
    await page.getByRole('button', { name: 'Settings', exact: true }).click()

    const twitch = page.locator('#twitch-settings')
    const application = twitch.locator('[aria-labelledby="server-twitch-application-heading"]')
    const secret = application.locator('.twitch-secret-field')
    const clientIdField = application.getByLabel('Client ID')
    const secretInput = secret.getByLabel('Twitch client secret', { exact: true })
    await expect(clientIdField).toBeVisible()
    await expect(secret).toContainText('Twitch client secret')
    await expect(secret.locator('.credential-actions')).toBeVisible()
    const clientIdBounds = (await clientIdField.boundingBox())!
    const secretBounds = (await secretInput.boundingBox())!
    await expect(secretInput).toHaveAttribute('type', 'password')
    await expect(secretInput).toBeDisabled()
    await expect(secret.locator('.twitch-secret-label .state-pill')).toHaveText('Configured')
    if (width >= 900) {
      expect(secretBounds.x).toBeGreaterThan(clientIdBounds.x + clientIdBounds.width)
      expect(secretBounds.y).toBeCloseTo(clientIdBounds.y, 0)
      expect(secretBounds.height).toBeCloseTo(clientIdBounds.height, 0)
    } else {
      expect(secretBounds.y).toBeGreaterThan(clientIdBounds.y + clientIdBounds.height)
      expect(Math.abs(secretBounds.x - clientIdBounds.x)).toBeLessThanOrEqual(1)
    }
    const secretActions = await secret.locator('.credential-actions button').all()
    const secretActionBounds = await Promise.all(secretActions.map(async (button) => (await button.boundingBox())!))
    secretActionBounds.forEach((box) => expect(box.y).toBeGreaterThanOrEqual(secretBounds.y + secretBounds.height))
    await expect(secret.getByRole('button', { name: 'Replace secret', exact: true })).toBeDisabled()

    const pairBoxes: Array<{ first: { x: number; y: number; width: number; height: number }; second: { x: number; y: number; width: number; height: number } }> = []
    for (const [firstLabel, secondLabel] of [
      ['Bot account login', 'Bot account user ID'],
      ['Target channel login', 'Target channel user ID'],
    ]) {
      const first = twitch.getByLabel(firstLabel)
      const second = twitch.getByLabel(secondLabel)
      const firstBounds = (await first.boundingBox())!
      const secondBounds = (await second.boundingBox())!
      pairBoxes.push({ first: firstBounds, second: secondBounds })
      if (width >= 900) {
        expect(Math.abs(firstBounds.y - secondBounds.y)).toBeLessThanOrEqual(1)
        expect(secondBounds.x).toBeGreaterThan(firstBounds.x + firstBounds.width)
        expect(Math.abs(firstBounds.width - secondBounds.width)).toBeLessThanOrEqual(1)
      } else {
        expect(secondBounds.y).toBeGreaterThan(firstBounds.y + firstBounds.height)
        expect(Math.abs(secondBounds.x - firstBounds.x)).toBeLessThanOrEqual(1)
      }
    }
    expect(Math.abs(pairBoxes[0].first.x - pairBoxes[1].first.x)).toBeLessThanOrEqual(1)
    expect(Math.abs(pairBoxes[0].second.x - pairBoxes[1].second.x)).toBeLessThanOrEqual(1)
    expect(Math.abs(pairBoxes[0].first.width - pairBoxes[1].first.width)).toBeLessThanOrEqual(1)
    expect(Math.abs(pairBoxes[0].second.width - pairBoxes[1].second.width)).toBeLessThanOrEqual(1)

    const clientId = `persisted-client-${width}`
    await application.getByLabel('Client ID').fill(clientId)
    const target = twitch.locator('[aria-labelledby="server-twitch-target-heading"]')
    const authorization = twitch.getByRole('heading', { name: 'Authorization, status and save', exact: true }).locator('..')
    const save = authorization.getByRole('button', { name: 'Save Twitch settings', exact: true })
    const targetBounds = (await target.boundingBox())!
    const authorizationBounds = (await authorization.boundingBox())!
    const saveBounds = (await save.boundingBox())!
    expect(saveBounds.y).toBeGreaterThan(targetBounds.y)
    expect(saveBounds.y).toBeGreaterThan(authorizationBounds.y)
    for (const button of await secret.locator('button').all()) {
      const buttonBounds = (await button.boundingBox())!
      expect(buttonBounds.x).toBeGreaterThanOrEqual(secretBounds.x)
      expect(buttonBounds.x + buttonBounds.width).toBeLessThanOrEqual(secretBounds.x + secretBounds.width)
    }
    await save.click()
    await expect.poll(() => api.calls.find((call) => call.path === '/v1/twitch/settings')?.body?.client_id).toBe(clientId)
    await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await expect(page.locator('#twitch-settings').getByLabel('Client ID')).toHaveValue(clientId)

    for (const card of await twitch.locator('.twitch-settings-group').all()) {
      const box = (await card.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(width)
      expect(await card.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    if (width === 1280 || width === 320) await page.screenshot({ path: `node_modules/.tmp/server-settings-${width}.png`, fullPage: true })
  })
}

test('server Twitch settings keep the validation error visible while preserving the draft', async ({ page }) => {
  const api = await server(page)
  await page.setViewportSize({ width: 320, height: 900 })
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  const twitch = page.locator('#twitch-settings')
  const clientId = twitch.getByLabel('Client ID')
  await clientId.fill('')
  await twitch.getByRole('button', { name: 'Save Twitch settings', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Enter the Twitch Client ID')
  await expect(clientId).toHaveValue('')
  const warning = await page.getByRole('alert').boundingBox()
  expect(warning).not.toBeNull()
  expect(warning!.x).toBeGreaterThanOrEqual(0)
  expect(warning!.x + warning!.width).toBeLessThanOrEqual(320)
  expect(api.calls.some((call) => call.path === '/v1/twitch/settings')).toBe(false)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
})

test('401 expiration removes editors and their drafts; failed logout still removes local access', async ({ page }) => {
  const api = await server(page)
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await page.locator('#ai-profile-instructions .accordion-trigger').click()
  await page.locator('#ai-profile-instructions textarea').fill('Private unsaved draft')
  api.expire()
  await invoke(page, 'get_app_status')
  await expect(page.getByRole('heading', { name: 'Sign in to server' })).toBeVisible()
  await expect(page.getByText('Your session expired. Sign in again.')).toBeVisible()
  await expect(page.locator('textarea')).toHaveCount(0)
  api.expire(false)
  await login(page)
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await page.locator('#ai-profile-instructions .accordion-trigger').click()
  await expect(page.locator('#ai-profile-instructions textarea')).toHaveValue('Saved instructions')
  api.fail('/v1/session/logout')
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Sign in to server' })).toBeVisible()
  await expect(page.getByText('Signed out.', { exact: true })).toBeVisible()
  expect(await invoke(page, 'get_app_status')).toEqual({ error: 'Sign in to manage this server.' })
})

test('authenticated operator activity includes replies, outcomes and linked details', async ({ page }) => {
  const api = await server(page)
  api.setLogs([
    { id: 1, timestamp: '2026-10-23T11:00:00Z', level: 'INFO', source: 'synthetic', message: 'command.input outcome=received', event_kind: 'command.input', text: '!ping', context: { request_id: 'shared-request', command: 'ping', source: 'command', outcome: 'received' } },
    { id: 2, timestamp: '2026-10-23T11:00:01Z', level: 'INFO', source: 'synthetic', message: 'chat.outgoing outcome=uncertain_send', event_kind: 'chat.outgoing', text: '@viewer exact reply', context: { request_id: 'shared-request', command: 'ping', source: 'command', outcome: 'uncertain_send' } },
  ])
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  await page.getByRole('button', { name: 'Logs', exact: true }).click()
  await expect(page.locator('.log-row')).toHaveCount(2)
  await expect(page.getByText('@viewer exact reply', { exact: true })).toBeVisible()
  await selectOption(page.getByRole('combobox', { name: 'Outcome', exact: true }), 'uncertain_send')
  await expect(page.locator('.log-row')).toHaveCount(1)
  await page.getByText('Event details', { exact: true }).click()
  await expect(page.locator('.log-details')).toContainText('shared-request')
  await page.getByRole('button', { name: 'Show related events' }).click()
  await expect(page.locator('.log-row')).toHaveCount(2)
  await page.getByRole('button', { name: 'Export filtered…' }).click()
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Confirm', exact: true }).click()
  const download = await downloaded
  const exported = JSON.parse(await readFile((await download.path())!, 'utf-8'))
  expect(exported.entries.map((entry: LogEntry) => entry.id)).toEqual([1, 2])
  expect(api.calls.filter((call) => call.path === '/v1/logs/recent').every((call) => call.authorization === `Bearer ${sessionToken}`)).toBe(true)
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.locator('.log-row')).toHaveCount(0)
})

test('status and logs poll at most every five seconds, use cursor and pause while hidden', async ({ page }) => {
  const api = await server(page)
  await page.clock.install()
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  await expect.poll(() => api.calls.filter((call) => call.path === '/v1/snapshot').length).toBeGreaterThan(0)
  const snapshots = api.calls.filter((call) => call.path === '/v1/snapshot').length
  await page.clock.fastForward(4900)
  expect(api.calls.filter((call) => call.path === '/v1/snapshot')).toHaveLength(snapshots)
  await page.getByRole('button', { name: 'Logs', exact: true }).click()
  await expect(page.getByText('OPERATOR ACTIVITY', { exact: true })).toBeVisible()
  await expect.poll(() => api.calls.filter((call) => call.path === '/v1/logs/recent').length).toBe(1)
  await page.clock.fastForward(5100)
  await expect.poll(() => api.calls.filter((call) => call.path === '/v1/logs/recent').length).toBe(2)
  expect(api.calls.filter((call) => call.path === '/v1/logs/recent').at(-1)?.body).toEqual({ after_id: 99, limit: 200 })
  await page.evaluate(() => Object.defineProperty(document, 'hidden', { value: true, configurable: true }))
  const count = api.calls.length
  await page.clock.fastForward(15000)
  expect(api.calls).toHaveLength(count)
  await page.evaluate(() => Object.defineProperty(document, 'hidden', { value: false, configurable: true }))
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  await page.clock.fastForward(5100)
  const logs = api.calls.filter((call) => call.path === '/v1/logs/recent').length
  await page.clock.fastForward(5100)
  expect(api.calls.filter((call) => call.path === '/v1/logs/recent')).toHaveLength(logs)
})

test('desktop startup waits for delayed pywebviewready without selecting browser transport', async ({ page }) => {
  const requests: string[] = []
  page.on('request', (request) => { if (request.url().includes('/v1/')) requests.push(request.url()) })
  await page.addInitScript(() => {
    window.setTimeout(() => {
      Object.assign(window, { pywebview: { api: {
        get_desktop_startup: async () => ({ state: 'ready' }),
        get_app_status: async () => ({ running: true, twitch_connected: true, twitch_connection_state: 'connected', uptime_seconds: 1, channel: 'test', account: 'bot' }),
        get_ai_status: async () => ({ enabled: false, available: false, memory_enabled: false, active_personality: 'neutral', model: '' }),
        get_twitch_settings: async () => ({ ok: false }),
        get_credentials: async () => ({ ok: false }),
        get_ai_provider_settings: async () => ({ ok: false }),
      } } })
      window.dispatchEvent(new Event('pywebviewready'))
    }, 300)
  })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Running', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Sign in to server' })).toHaveCount(0)
  await expect(page.getByRole('combobox', { name: 'Operation mode', exact: true })).toHaveCount(0)
  expect(requests).toEqual([])
})


for (const origin of ['http://localhost:8765', 'https://server.example-tailnet.ts.net']) {
  test(`callback setup at ${origin} displays fixed URLs and polls only the signed-in attempt`, async ({ page }) => {
    const api = await server(page)
    api.setTwitch({ management_url: origin,
      oauth_callback_url: `${origin}/oauth/callback`,
      authorization_mode: 'redirect', authorization_attempt: 'pending' })
    await page.goto('/tests/browser.fixture.html')
    await login(page)
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await expect(page.locator('code').filter({ hasText: `${origin}/oauth/callback` })).toBeVisible()
    await page.getByRole('button', { name: 'Connect Twitch', exact: true }).click()
    await expect(page.getByRole('status')).toContainText('Return to this signed-in tab')
    await expect(page.getByLabel('Callback URL', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Complete authorization', exact: true })).toHaveCount(0)
    api.setTwitch({ authorization_attempt: 'completed' })
    await expect(page.getByRole('status')).toContainText('Twitch authorization completed')
    await expect(page.getByRole('link', { name: 'Open Twitch authorization' })).toHaveCount(0)
    expect(api.calls.some((call) => call.path === '/v1/twitch/authorization/complete')).toBe(false)
    expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])

    api.setTwitch({ authorization_attempt: 'pending' })
    await page.getByRole('button', { name: 'Connect Twitch', exact: true }).click()
    api.setTwitch({ authorization_attempt: 'failed' })
    await expect(page.getByRole('alert')).toContainText('registered redirect, expected bot account')
    api.setTwitch({ authorization_attempt: 'pending' })
    await page.getByRole('button', { name: 'Connect Twitch', exact: true }).click()
    api.setTwitch({ authorization_attempt: 'expired' })
    await expect(page.getByRole('alert')).toContainText('Authorization expired')
  })
}


test('browser AI setup saves typed selections, explicit fallback consent and shared instructions through HTTP', async ({ page }) => {
  const api = await server(page)
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  const setup = page.locator('#ai-models')
  await setup.locator('.accordion-trigger').click()
  await expect(setup.getByLabel('Primary provider')).toBeVisible()
  await selectOption(setup.getByLabel('Primary provider'), 'deepseek')
  await selectOption(setup.getByLabel('Primary thinking'), 'high')
  await setup.getByLabel('Enable fallback', { exact: true }).press('Space')
  await selectOption(setup.getByLabel('Fallback provider'), 'gemini')
  await selectOption(setup.getByLabel('Fallback model choices'), 'gemini-2.5-flash')
  await selectOption(setup.getByLabel('Fallback thinking'), 'off')
  await expect(setup.getByRole('button', { name: 'Save AI setup' })).toBeDisabled()
  await setup.getByLabel(/I understand that my question/).check()
  const instructions = page.locator('#ai-shared-instructions')
  await instructions.locator('.accordion-trigger').click()
  await instructions.getByLabel('Shared AI instructions', { exact: true }).fill('Owner shared instructions')
  await instructions.getByRole('button', { name: 'Save instructions', exact: true }).click()
  await setup.getByLabel('Maximum question length', { exact: true }).fill('800')
  await setup.getByRole('button', { name: 'Save AI setup' }).click()
  await expect(setup).toContainText('AI setup saved')
  await expect.poll(() => api.calls.filter((call) => call.path === '/v1/ai/setup' && call.method === 'POST').at(-1)?.body).toMatchObject({ settings: {
    primary: { provider: 'deepseek', model: 'deepseek-flash', thinking: 'high', search: false },
    fallback: { provider: 'gemini', thinking: 'off' }, cross_provider_acknowledged: true,
    max_question_length: 800, shared_instructions: 'Owner shared instructions',
  } })
  await setup.getByRole('button', { name: 'Discover primary models' }).click()
  expect(api.calls.filter((call) => call.path === '/v1/ai/models/discover').at(-1)?.body).toEqual({ provider: 'deepseek' })
  expect(await page.evaluate(() => Boolean(window.pywebview))).toBe(false)
})


test('browser Settings sidebar exposes available sections and opens their accordions', async ({ page }) => {
  await server(page)
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await nav.getByRole('button', { name: 'Settings', exact: true }).click()
  const submenu = nav.locator('#nav-Settings')
  await expect(submenu.getByRole('button')).toHaveText(['Twitch connection', 'Configuration transfer'])
  await expect(submenu).not.toContainText('Gemini API key')
  await expect(page.locator('#credential-settings')).toHaveCount(0)
})
