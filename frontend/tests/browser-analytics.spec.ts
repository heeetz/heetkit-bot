import { expect, test, type Page } from '@playwright/test'
import { expectNoOverflow, navigate, selectOption, server, signIn } from './browser-fixture'

async function analytics(page: Page) {
  const requests: { path: string; body: Record<string, unknown> }[] = []
  let reset = false
  let failNext = false
  let enabled = true
  let countChat = true
  await page.route(/\/v1\/ops\/(get_analytics|reset_analytics|configure_analytics|configure_leaderboard_counting)$/, async (route) => {
    const path = new URL(route.request().url()).pathname
    const body = route.request().postDataJSON()
    requests.push({ path, body })
    if (path.includes('/configure_')) {
      if (path.endsWith('_leaderboard_counting')) countChat = body.enabled
      else enabled = body.enabled
      return route.fulfill({ json: { ok: true } })
    }
    if (path.endsWith('/reset_analytics')) {
      reset = true
      return route.fulfill({ json: { ok: true } })
    }
    if (failNext) {
      failNext = false
      return route.abort('connectionrefused')
    }
    const days = body.days
    const metrics = reset ? {} : { 'command.attempts': days === 1 ? 3 : 8, 'command.success': 2 }
    return route.fulfill({ json: {
      ok: true, days, start: days === 1 ? '2026-10-30' : '2026-10-24', end: '2026-10-30',
      as_of: '2026-10-30T12:30:00Z', resolution: days === 1 ? 'hour' : 'day', channel_id: '200',
      connected: false, retained_users: 42, enabled, count_chat_messages: countChat, available: true,
      pending: 0, dropped: 0, write_failures: 0, metadata: { data_start: '2026-10-28T12:00:00Z' },
      totals: metrics, series: [{ day: days === 1 ? '2026-10-30T10:00:00+00:00' : '2026-10-30',
        metrics, coverage_seconds: 1800, new_users_coverage_seconds: 1800 }],
      commands: reset ? [] : [{ name: 'ping', label: '!ping', metrics }], providers: [],
    } })
  })
  return { requests, failNextQuery: () => { failNext = true } }
}

test('Analytics loads the command breakdown, changes dates and guards a reset', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  await server(page)
  const api = await analytics(page)
  await signIn(page)
  await navigate(page, 'Analytics')
  await expect(page.getByRole('heading', { name: 'Analytics', level: 1 })).toBeVisible()
  const command = page.getByRole('row', { name: /!ping/ })
  await expect(command.getByRole('cell', { name: '8', exact: true })).toBeVisible()
  await selectOption(page.getByRole('combobox', { name: 'UTC window' }), '1')
  await expect(command.getByRole('cell', { name: '3', exact: true })).toBeVisible()
  expect(api.requests.at(-1)?.body).toEqual({ days: 1 })
  await expectNoOverflow(page)

  const refresh = page.getByRole('button', { name: 'Refresh analytics' })
  api.failNextQuery()
  await refresh.click()
  await expect(page.getByRole('alert')).toBeVisible()
  await refresh.click()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(command).toBeVisible()

  const reset = page.getByRole('button', { name: 'Reset all profile analytics', exact: true })
  const confirmation = page.getByRole('dialog', { name: 'Reset all profile analytics?' })
  await reset.click()
  await confirmation.getByRole('button', { name: 'Cancel' }).click()
  expect(api.requests.some(({ path }) => path.endsWith('/reset_analytics'))).toBe(false)
  await reset.click()
  await confirmation.getByRole('button', { name: 'Confirm' }).click()
  await expect(command).toHaveCount(0)
  expect(api.requests.find(({ path }) => path.endsWith('/reset_analytics'))?.body).toEqual({ confirmed: true })
})

test('leaderboards discard a previous channel response and exclusions cancel, retry and save', async ({ page }) => {
  const api = await server(page, {}, { leaderboard_channel_id: null })
  await analytics(page)
  let releasePrevious!: () => void
  const previous = new Promise<void>((resolve) => { releasePrevious = resolve })
  let channel = '100'
  let previousRequests = 0
  let exclusions = ['otherbot']
  let fail = true
  await page.route('**/v1/ops/get_leaderboards', async (route) => {
    const requestedChannel = channel
    if (requestedChannel === '100') {
      previousRequests += 1
      await previous
    }
    const ranking = {
      period: '2026-11', started_at: '2026-11-01T00:00:00Z', ends_at: null, partial: true,
      rows: [{ place: 1, nickname: 'viewer' + requestedChannel, messages: 34 }],
    }
    await route.fulfill({ json: { ok: true, leaderboards: {
      channel_id: requestedChannel, connected: true, stream_status: 'live', exclusions, month: ranking, stream: ranking,
    } } })
  })
  await page.route('**/v1/ops/save_leaderboard_settings', async (route) => {
    const body = route.request().postDataJSON()
    expect(body).toEqual({ channel_id: '200', exclusions: ['newbot'] })
    if (fail) {
      fail = false
      return route.fulfill({ json: { ok: false, error: 'Synthetic write failure' } })
    }
    exclusions = body.exclusions
    await route.fulfill({ json: { ok: true } })
  })
  await page.clock.install()
  await signIn(page)
  await navigate(page, 'About')
  api.setStatus({ leaderboard_channel_id: '100' })
  const snapshot = page.waitForResponse('**/v1/ops/get_snapshot')
  await page.clock.fastForward(5100)
  await snapshot
  await navigate(page, 'Analytics')
  await expect.poll(() => previousRequests).toBeGreaterThan(0)
  channel = '200'
  api.setStatus({ leaderboard_channel_id: '200' })
  await page.clock.fastForward(5100)
  const stream = page.getByRole('table', { name: 'Stream top 10 chatters' })
  const month = page.getByRole('table', { name: 'Monthly top 10 chatters' })
  await expect(stream.getByRole('rowheader', { name: 'viewer200' })).toBeVisible()
  await expect(month.getByRole('rowheader', { name: 'viewer200' })).toBeVisible()
  const received = page.waitForResponse('**/v1/ops/get_leaderboards')
  releasePrevious()
  await received
  await expect(stream.getByRole('rowheader', { name: 'viewer100' })).toHaveCount(0)
  await expect(month.getByRole('rowheader', { name: 'viewer200' })).toBeVisible()

  const names = page.getByRole('textbox', { name: 'Excluded bot names' })
  await expect(names).toHaveValue('otherbot')
  await names.fill('@NewBot')
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(names).toHaveValue('otherbot')
  await names.fill('@NewBot, newbot')
  const save = page.getByRole('button', { name: 'Save exclusions' })
  await save.click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(names).toHaveValue('@NewBot, newbot')
  await save.click()
  await expect(names).toHaveValue('newbot')
  await expect(save).toBeDisabled()
})

test('analytics collection, chat counting and balance refresh use separate operations', async ({ page }) => {
  await server(page)
  const api = await analytics(page)
  const balances: unknown[] = []
  let available = true
  await page.route('**/v1/ops/get_ai_balance', async (route) => {
    balances.push(route.request().postDataJSON())
    await route.fulfill({ json: {
      ok: true, provider: 'deepseek', state: available ? 'available' : 'unavailable',
      balances: available ? [{ currency: 'USD', total_balance: '12.34', granted_balance: '2', topped_up_balance: '10.34' }] : [],
      updated_at: '2026-11-21T12:00:00Z',
    } })
  })
  await signIn(page)
  await navigate(page, 'Analytics')
  const collect = page.getByRole('checkbox', { name: 'Collect analytics' })
  const count = page.getByRole('checkbox', { name: 'Count chat messages' })
  await expect(collect).toBeChecked()
  await expect(count).toBeChecked()
  await collect.press('Space')
  await expect(collect).not.toBeChecked()
  await expect(count).toBeChecked()
  await count.press('Space')
  await expect(count).not.toBeChecked()
  await collect.press('Space')
  await expect(collect).toBeChecked()
  await expect(count).not.toBeChecked()
  expect(api.requests.filter(({ path }) => path.includes('/configure_')).map(({ path, body }) => [path, body])).toEqual([
    ['/v1/ops/configure_analytics', { enabled: false }],
    ['/v1/ops/configure_leaderboard_counting', { enabled: false }],
    ['/v1/ops/configure_analytics', { enabled: true }],
  ])

  expect(balances).toHaveLength(0)
  const refresh = page.getByRole('button', { name: 'Refresh balance' })
  await refresh.click()
  await expect(page.getByText('USD 12.34', { exact: true })).toBeVisible()
  expect(balances[0]).toEqual({ provider: 'deepseek', refresh: true })
  available = false
  await refresh.click()
  await expect(page.getByText('USD 12.34', { exact: true })).toHaveCount(0)
  await selectOption(page.getByLabel('Balance provider'), 'openai')
  await expect(refresh).toBeDisabled()
})
