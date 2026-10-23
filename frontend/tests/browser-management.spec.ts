import { expect, test, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import type { CommandInfo, CustomCommandInfo, FilterInput, LogEntry } from '../src/bridge'
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

async function server(page: Page, operationOverrides: OperationOverrides = {}, statusOverrides: StatusOverrides = {}) {
  const calls: Call[] = []
  let expired = false
  let logs: LogEntry[] = []
  let fail = ''
  let filters: FilterInput = { words: ['synthetic'], phrases: [], patterns: [] }
  let profile = 'Saved instructions'
  let prompt = 'Neutral prompt'
  let customCommands: CustomCommandInfo[] = []
  let enabled = true
  let oauthBeginResult: object = { ok: true, url: 'https://id.twitch.tv/oauth2/authorize?client_id=synthetic', expires_in: 300 }
  let oauthCompleteResult: object = { ok: true }
  const command: CommandInfo = {
    name: 'ping', aliases: [], enabled: true, available: true, unavailable_reason: null,
    response_pool: { responses: ['Pong'], defaults: ['Pong'], saved: true, has_saved_override: false, response_mode: 'single', max_responses: 1 },
    permission: 'EVERYONE', stream_availability: 'live_only', cooldown: { per_user_seconds: 1, global_seconds: 0 }, hidden: false,
    default_settings: { enabled: true, permission: 'EVERYONE', stream_availability: 'anytime', cooldown: { per_user_seconds: 1, global_seconds: 0 } },
    saved: true, has_saved_override: false,
  }
  let operation = {
    mode: 'always_on' as const, desired_running: true, pending: false,
    stream_status: 'live' as const, last_known_stream_status: 'live' as const,
    last_checked_at: '2026-10-20T12:00:00Z', error: null as null | 'connection_failed',
    ...operationOverrides,
  }
  const status = { running: true, twitch_connected: true, twitch_connection_state: 'connected' as const, uptime_seconds: 10, channel: 'synthetic_channel', account: 'synthetic_bot', ...statusOverrides, operation }
  const ai = () => ({ enabled, available: true, memory_enabled: false, active_personality: 'neutral', available_personalities: ['neutral'], model: 'test-model' })
  const aiProvider = { provider: 'Gemini', selected_model: 'test-model', fallback_model: 'test-fallback', presets: [], credential: null }
  const twitch: Record<string, unknown> = { client_id: 'synthetic-client', bot_username: 'synthetic_bot', bot_user_id: '100', target_channel: 'synthetic_channel', target_channel_user_id: '200', active_channel: 'synthetic_channel', requires_restart: false, requires_reconnect: false, oauth_token_available: true, oauth_callback_url: 'http://localhost:8765/oauth/callback', authorization_status: 'verified', authorized_account: 'synthetic_bot', setup_complete: true }
  const credentials = [{ name: 'twitch_client_secret', label: 'Twitch client secret', configured: true, source: 'environment', managed: false, validation_status: 'not_tested', secure_storage_available: false }, { name: 'gemini_api_key', label: 'Gemini API key', configured: false, source: 'missing', managed: true, validation_status: 'not_tested', secure_storage_available: false }]
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
    if (path === '/v1/credentials/replace' || path === '/v1/credentials/remove' || path === '/v1/credentials/test') result = { ok: true }
    if (path === '/v1/ai') result = ai()
    if (path === '/v1/ai/enabled') enabled = body!.enabled as boolean
    if (path === '/v1/ai/models') result = { ok: true, settings: aiProvider }
    if (path === '/v1/ai/language') result = { ok: true, settings: { mode: 'auto', allowed_languages: ['en'], fallback_language: 'en' }, languages: [{ code: 'en', label: 'English' }], active_policy: 'Auto' }
    if (path === '/v1/commands') result = { command_prefix: '!', permissions: ['EVERYONE', 'MODERATOR'], commands: [command] }
    if (path === '/v1/commands/save' || path === '/v1/commands/apply') {
      command.cooldown.per_user_seconds = body!.per_user_seconds as number
      const options = body!.options as { stream_availability?: CommandInfo['stream_availability'] } | undefined
      if (options?.stream_availability) command.stream_availability = options.stream_availability
      command.has_saved_override = true
    }
    if (path === '/v1/commands/reset') Object.assign(command, structuredClone(command.default_settings), { has_saved_override: false })
    if (path === '/v1/commands/responses/save' || path === '/v1/commands/responses/apply') command.response_pool!.responses = body!.responses as string[]
    if (path === '/v1/custom-commands') result = { command_prefix: '!', permissions: ['EVERYONE', 'MODERATOR'], variables: ['sender'], commands: customCommands }
    if (path === '/v1/custom-commands/save') customCommands = [{ ...(body!.command as CustomCommandInfo), id: 'saved-command' }]
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
  return { calls, setLogs: (entries: LogEntry[]) => { logs = entries }, setTwitch: (values: Record<string, unknown>) => { Object.assign(twitch, values) }, expire: (value = true) => { expired = value }, fail: (path: string) => { fail = path }, setOperation: (values: OperationOverrides) => { operation = { ...operation, ...values }; status.operation = operation }, setOAuthBegin: (result: object) => { oauthBeginResult = result }, setOAuthComplete: (result: object) => { oauthCompleteResult = result } }
}

async function login(page: Page) {
  await page.getByLabel('Administrator token').fill(adminToken)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible()
}

async function invoke(page: Page, method: string, args: unknown[] = []) {
  return page.evaluate(async ({ method, args }) => {
    const modulePath = '/src/bridge.ts'
    const module = await import(modulePath)
    const api = await module.waitForBridge()
    try { return await api[method](...args) } catch (error) { return { error: error instanceof Error ? error.message : 'failed' } }
  }, { method, args })
}

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
  expect(api.calls.at(-1)?.body).toEqual({ selected_model: 'primary', fallback_model: 'fallback' })
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
  await editor.getByLabel('Command name').fill('randompool')
  await selectOption(editor.getByLabel('Response type'), 'random')
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
    await command.getByRole('button', { name: 'Save command', exact: true }).click()
    await expect.poll(() => api.calls.find((call) => call.path === '/v1/commands/save')?.body?.per_user_seconds).toBe(7)
    expect(api.calls.find((call) => call.path === '/v1/commands/save')?.body).toMatchObject({ options: { stream_availability: 'offline_only' } })
    await command.getByRole('button', { name: 'Reset settings', exact: true }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
    await expect(availability).toHaveAttribute('data-value', 'anytime')
    await page.getByRole('button', { name: 'New command', exact: true }).click()
    const custom = page.locator('.custom-command-editor')
    await expect(custom.getByLabel('Stream availability', { exact: true })).toHaveAttribute('data-value', 'anytime')
    await custom.getByLabel('Command name').fill('browser')
    await custom.getByLabel('Message', { exact: true }).fill('Browser reply')
    await selectOption(custom.getByLabel('Stream availability', { exact: true }), 'offline_only')
    await custom.getByRole('button', { name: 'Save command', exact: true }).click()
    await expect.poll(() => api.calls.find((call) => call.path === '/v1/custom-commands/save')?.body).toMatchObject({ command: { stream_availability: 'offline_only' } })
    const customRow = page.locator('.custom-command-row').filter({ hasText: '!browser' })
    await customRow.getByRole('button', { name: 'Edit', exact: true }).click()
    await expect(custom.getByLabel('Stream availability', { exact: true })).toHaveAttribute('data-value', 'offline_only')
    await selectOption(custom.getByLabel('Stream availability', { exact: true }), 'live_only')
    await page.getByRole('button', { name: 'Discard draft', exact: true }).click()
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
    await expect(page.locator('#ai-playground')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Open Playground', exact: true })).toHaveCount(0)
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
    await page.getByRole('button', { name: 'Add Gemini key', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Server configuration' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Configuration transfer' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Save Twitch settings', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Remove', exact: true }).first()).toBeDisabled()
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
  await expect(page.getByRole('heading', { name: 'Server configuration', exact: true })).toBeVisible()

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
  await expect(application.locator('.server-twitch-secret-row .credential-actions')).toBeVisible()

  const credentials = page.getByRole('heading', { name: 'Server credentials' }).locator('..')
  await expect(credentials.getByRole('button', { name: 'Remove', exact: true }).first()).toBeDisabled()
  const gemini = page.locator('.credential-row').filter({ hasText: 'Gemini API key' })
  await gemini.getByLabel('New value').fill('synthetic-gemini-secret')
  await gemini.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(gemini.getByLabel('New value')).toHaveValue('')
  expect(api.calls.find((call) => call.path === '/v1/credentials/replace')?.body).toEqual({ name: 'gemini_api_key', value: 'synthetic-gemini-secret' })

  await page.getByRole('button', { name: 'Connect Twitch', exact: true }).click()
  await expect.poll(() => api.calls.find((call) => call.path === '/v1/twitch/authorization/begin')?.body).toEqual({})
  await expect(page.getByRole('link', { name: 'Open Twitch authorization' })).toHaveAttribute('href', 'https://id.twitch.tv/oauth2/authorize?client_id=synthetic')
  await expect(page.getByRole('link', { name: 'Open Twitch authorization' })).toHaveAttribute('rel', 'noopener noreferrer')
  await page.getByLabel('Callback URL').fill('http://localhost:8765/oauth/callback?code=synthetic&state=synthetic')
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect.poll(() => api.calls.find((call) => call.path === '/v1/twitch/authorization/cancel')?.body).toEqual({})
  await expect(page.getByLabel('Callback URL')).toHaveCount(0)

  await page.getByRole('button', { name: 'Connect Twitch', exact: true }).click()
  await page.getByLabel('Callback URL').fill('http://localhost:8765/oauth/callback?error=access_denied&state=synthetic')
  api.setOAuthComplete({ ok: false, error: 'Twitch authorization was denied. Try again.' })
  await page.getByRole('button', { name: 'Complete authorization', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Twitch authorization was denied')
  await expect(page.getByLabel('Callback URL')).toHaveValue('')

  await gemini.getByLabel('New value').fill('sensitive-draft')
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  const refreshedGemini = page.locator('.credential-row').filter({ hasText: 'Gemini API key' })
  await expect(refreshedGemini.getByLabel('New value')).toHaveValue('')

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
    const secret = application.locator('.server-twitch-secret-row .credential-row')
    const clientIdField = application.getByLabel('Client ID')
    await expect(clientIdField).toBeVisible()
    await expect(secret).toContainText('Twitch client secret')
    await expect(secret.locator('.credential-actions')).toBeVisible()
    const clientIdBounds = (await clientIdField.boundingBox())!
    const secretBounds = (await secret.boundingBox())!
    expect(secretBounds.y).toBeGreaterThan(clientIdBounds.y + clientIdBounds.height)
    const secretInputBounds = (await secret.locator('input').boundingBox())!
    const secretActionsBounds = (await secret.locator('.credential-actions').boundingBox())!
    expect(Math.abs(secretInputBounds.x - clientIdBounds.x)).toBeLessThanOrEqual(1)
    expect(Math.abs(secretInputBounds.width - clientIdBounds.width)).toBeLessThanOrEqual(1)
    expect(secretActionsBounds.y - secretInputBounds.y - secretInputBounds.height).toBeGreaterThanOrEqual(12)

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
    const save = target.getByRole('button', { name: 'Save Twitch settings', exact: true })
    const authorization = twitch.getByRole('heading', { name: 'Authorization and status', exact: true }).locator('..')
    const targetBounds = (await target.boundingBox())!
    const authorizationBounds = (await authorization.boundingBox())!
    const saveBounds = (await save.boundingBox())!
    expect(saveBounds.y).toBeGreaterThan(targetBounds.y)
    expect(saveBounds.y).toBeLessThan(authorizationBounds.y)
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
    await expect(page.getByLabel('Callback URL')).toHaveCount(0)
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
