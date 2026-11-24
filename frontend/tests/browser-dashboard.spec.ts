import { expect, test } from '@playwright/test'
import { expectNoOverflow, navigate, selectOption, server, signIn } from './browser-fixture'

test.use({ locale: 'en-US', timezoneId: 'America/Los_Angeles' })

test('Dashboard renders recent commands in local time and Stop pauses offline automation without changing the mode', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  const api = await server(page, {
    mode: 'stream_only', desired_running: false, stream_status: 'offline', last_known_stream_status: 'offline',
  }, { running: false, twitch_connected: false, twitch_connection_state: 'stopped' })
  api.setLogs([{
    id: 1, timestamp: '2026-11-19T12:30:05.000Z', level: 'INFO', source: 'commands',
    message: 'command.terminal', event_kind: 'command.terminal',
    context: { command: 'ping', command_prefix: '!', outcome: 'success', reason: 'confirmed_delivery', username: 'synthetic_viewer' },
  }])
  await signIn(page)
  const recent = page.getByRole('article', { name: 'Recent commands' })
  const row = recent.getByRole('row', { name: /!ping/ })
  await expect(row.getByRole('cell', { name: '04:30:05', exact: true })).toBeVisible()
  await expect(row.getByRole('cell', { name: 'synthetic_viewer', exact: true })).toBeVisible()
  await expectNoOverflow(page)

  await page.getByRole('button', { name: 'Stop', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeEnabled()
  await expect(page.getByRole('combobox', { name: 'Operation mode' })).toHaveText('Stream Only')
  expect(api.calls.find(({ path }) => path === '/v1/ops/stop_bot')).toMatchObject({ method: 'POST', body: {} })
  await page.getByRole('button', { name: 'Start', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible()
  await recent.getByRole('button', { name: 'View logs' }).click()
  await expect(page.getByRole('heading', { name: 'Logs', level: 1 })).toBeVisible()
})

test('Dashboard status polls switch from current counts to paused and then to the next broadcast', async ({ page }) => {
  await page.clock.install()
  await server(page)
  let countingEnabled = true
  let live = true
  await page.route('**/v1/ops/get_leaderboards', async (route) => {
    const ranking = {
      started_at: '2026-11-19T12:00:00Z', partial: false, ends_at: null,
      rows: [101, 83, 41, 15].map((messages, index) => ({ place: index + 1, nickname: 'chatter_' + index, messages })),
    }
    await route.fulfill({ json: { ok: true, leaderboards: {
      channel_id: '200', counting_enabled: countingEnabled, connected: true, stream_status: live ? 'live' : 'offline',
      exclusions: [], month: { ...ranking, period: '2026-11' },
      stream: live ? { ...ranking, period: 'stream' } : null,
    } } })
  })
  await signIn(page)
  const activity = page.getByRole('article', { name: 'Stream activity' })
  const first = activity.getByRole('rowheader', { name: 'chatter_0' })
  await expect(first).toBeVisible()
  await expect(activity.getByRole('rowheader')).toHaveCount(3)
  countingEnabled = false
  await page.clock.fastForward(5100)
  await expect(activity.getByText('Counting paused', { exact: true })).toBeVisible()
  await expect(first).toBeVisible()
  live = false
  await page.clock.fastForward(5100)
  await expect(first).toHaveCount(0)
  await activity.getByRole('button', { name: 'View analytics' }).click()
  await expect(page.getByRole('heading', { name: 'Analytics', level: 1 })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Chatters', exact: true })).toHaveAttribute('aria-current', 'location')
})

test('the mode Select commits with Enter and dismisses with Escape', async ({ page }) => {
  const api = await server(page)
  await signIn(page)
  const mode = page.getByRole('combobox', { name: 'Operation mode' })
  const list = page.getByRole('listbox')
  await mode.focus()
  await page.keyboard.press('ArrowDown')
  await expect(list).toBeVisible()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(list).toBeHidden()
  await expect(mode).toHaveText('Stream Only')

  await mode.press('Space')
  await expect(list).toBeVisible()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Escape')
  await expect(list).toBeHidden()
  await expect(mode).toBeFocused()
  await expect(mode).toHaveText('Stream Only')
  expect(api.calls.filter(({ path }) => path === '/v1/ops/set_bot_mode').map(({ body }) => body)).toEqual([{ mode: 'stream_only' }])
})

test('a pending Server operation can be changed to Manual after a failed save', async ({ page }) => {
  const api = await server(page, { stream_status: 'unknown', last_known_stream_status: 'offline', pending: true })
  await signIn(page)
  const mode = page.getByRole('combobox', { name: 'Operation mode' })
  await expect(mode).toHaveText('Always On')
  await expect(page.getByRole('button', { name: /Reconciling/ })).toBeDisabled()
  api.fail('/v1/ops/set_bot_mode')
  await selectOption(mode, 'manual')
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(mode).toHaveText('Always On')
  api.fail('')
  await selectOption(mode, 'manual')
  await expect(mode).toHaveText('Manual')
  expect(api.calls.filter(({ path }) => path === '/v1/ops/set_bot_mode').map(({ body }) => body)).toEqual(Array(2).fill({ mode: 'manual' }))
})

test('a failed Ask write keeps its value and a successful write reaches Commands', async ({ page }) => {
  const api = await server(page)
  await signIn(page)
  const dashboard = page.getByRole('checkbox', { name: 'Enable AI command' })
  await expect(dashboard).toBeChecked()
  api.fail('/v1/ops/set_ai_enabled')
  await dashboard.press('Space')
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(dashboard).toBeChecked()
  api.fail('')
  await dashboard.press('Space')
  await expect(dashboard).not.toBeChecked()
  expect(api.calls.filter(({ path }) => path === '/v1/ops/set_ai_enabled').at(-1)?.body).toEqual({ enabled: false })

  await navigate(page, 'Commands')
  await selectOption(page.getByRole('combobox', { name: 'Status', exact: true }), 'all')
  const command = page.getByRole('checkbox', { name: 'Enable !ask', exact: true })
  await expect(command).not.toBeChecked()
  await command.press('Space')
  await expect(command).toBeChecked()
  await navigate(page, 'Dashboard')
  await expect(dashboard).toBeChecked()
  expect(api.calls.find(({ path }) => path === '/v1/ops/save_builtin_enabled')?.body)
    .toEqual({ command_name: 'ask', enabled: true })
})

test('quick controls save the main model and ignore a user in every command', async ({ page }) => {
  const api = await server(page)
  let saved: unknown = null
  const capabilities = { known: true, thinking_options: [{ value: 'default', label: 'Default' }], search_supported: false, search_reason: '', attribution_required: false }
  await page.route('**/v1/ops/{get,save}_ai_setup', async (route) => {
    if (route.request().url().endsWith('/save_ai_setup')) saved = route.request().postDataJSON().settings
    await route.fulfill({ json: { ok: true, settings: { primary: { provider: 'gemini', model: 'model-a', thinking: 'high', search: true },
      fallback: null, cross_provider_acknowledged: false, max_question_length: 300, max_answer_length: 220, shared_instructions: null, provider_drafts: {} },
    providers: [{ id: 'gemini', label: 'Gemini', credential: null, models: ['model-a', 'model-b'], selected_model: 'model-a', fallback_model: '' }],
    capabilities: { gemini: { 'model-a': capabilities, 'model-b': capabilities } } } })
  })
  await signIn(page)
  const quick = page.getByRole('region', { name: 'Quick controls' })
  await selectOption(quick.getByRole('combobox', { name: 'Main model' }), 'model-b')
  // Unsupported thinking and search fall back so the quick save stays valid.
  await expect.poll(() => saved).toMatchObject({ primary: { provider: 'gemini', model: 'model-b', thinking: 'default', search: false }, fallback: null })
  await quick.getByRole('textbox', { name: 'Ignore user' }).fill('@Synthetic_Viewer')
  await quick.getByRole('button', { name: 'Ignore', exact: true }).click()
  await expect(quick.getByRole('status')).toContainText('synthetic_viewer')
  expect(api.calls.find(({ path }) => path === '/v1/ops/save_command_restriction')?.body)
    .toEqual({ data: { username: 'Synthetic_Viewer', command_ids: [], expires_at: null, note: '' } })
  await quick.getByRole('button', { name: 'Manage ignored users' }).click()
  await expect(page.getByRole('heading', { name: 'Commands', level: 1 })).toBeVisible()
})
