import { expect, test } from '@playwright/test'
import { expectNoOverflow, navigate, selectOption, server, signIn } from './browser-fixture'

test.use({ locale: 'en-US', timezoneId: 'America/Los_Angeles' })

test('Dashboard renders recent commands in local time and switches offline automation to Manual', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  const api = await server(page, {
    mode: 'stream_only', desired_running: false, stream_status: 'offline', last_known_stream_status: 'offline',
  }, { running: false, twitch_connected: false, twitch_connection_state: 'stopped' })
  api.setLogs([{
    id: 1, timestamp: '2026-11-19T12:30:05.000Z', level: 'INFO', source: 'commands',
    message: 'command.terminal', event_kind: 'command.terminal',
    context: { command: 'ping', command_prefix: '!', outcome: 'success', reason: 'confirmed_delivery' },
  }])
  await signIn(page)
  const recent = page.getByRole('article', { name: 'Recent commands' })
  const row = recent.getByRole('row', { name: /!ping/ })
  await expect(row.getByRole('cell', { name: '04:30:05', exact: true })).toBeVisible()
  await expectNoOverflow(page)

  await page.getByRole('button', { name: 'Switch to Manual & disconnect', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Manual', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Connect', exact: true })).toBeEnabled()
  expect(api.calls.find(({ path }) => path === '/v1/ops/stop_bot')).toMatchObject({ method: 'POST', body: {} })
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
  await expect(page.getByRole('heading', { name: 'Stream Only', exact: true })).toBeVisible()

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
  const operation = page.getByRole('article').filter({ has: mode })
  await expect(operation.getByRole('heading', { name: 'Always On' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Reconciling/ })).toBeDisabled()
  api.fail('/v1/ops/set_bot_mode')
  await selectOption(mode, 'manual')
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(operation.getByRole('heading', { name: 'Always On' })).toBeVisible()
  api.fail('')
  await selectOption(mode, 'manual')
  await expect(operation.getByRole('heading', { name: 'Manual' })).toBeVisible()
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
