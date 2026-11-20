import { expect, test } from '@playwright/test'

test('Dashboard shows UTC terminal outcomes and the current stream counts', async ({ page }) => {
  await page.setViewportSize({ width: 1180, height: 760 })
  // Install before load so the leaderboard poll timer is fake and runFor() reliably fires it.
  await page.clock.install()
  await page.goto('/tests/fixture.html?configured&authorized&aiAvailable&connection=connected')
  await page.getByRole('navigation').getByRole('button', { name: 'About', exact: true }).click()
  await page.evaluate(() => {
    const api = window.pywebview!.api
    const status = api.get_app_status
    api.get_app_status = async () => ({ ...await status(), leaderboard_channel_id: '200' })
    const outcomes = [
      ['weather', 'success', 'confirmed_delivery', ''],
      ['ask', 'skipped', 'filters', 'output_filter'],
      ['forecast', 'skipped', 'cooldown', ''],
      ['promo', 'uncertain', 'uncertain_delivery', ''],
      ['ping', 'error', 'delivery_failed', ''],
    ]
    const entries = outcomes.map(([command, outcome, reason, stage], index) => ({
      id: 5 - index, timestamp: `2026-11-19T12:30:0${5 - index}.000Z`, level: 'INFO',
      source: 'commands', message: 'command.terminal', event_kind: 'command.terminal',
      context: { command, command_prefix: '#', outcome, reason, stage },
    }))
    api.get_recent_commands = async () => ({ entries })
    api.get_recent_logs = async (after = 0) => ({ entries: after ? [] : [...entries].reverse(), next_after_id: 5 })
    let counting = true
    let finished = false
    Reflect.set(window, 'setDashboardStream', (enabled: boolean, ended: boolean) => { counting = enabled; finished = ended })
    const stream = { period: 'stream', started_at: '2026-11-19T12:00:00Z', partial: false,
      rows: [101, 83, 41, 15].map((messages, index) => ({ place: index + 1, nickname: `chatter_${index}`, messages })) }
    api.get_leaderboards = async () => ({ ok: true, leaderboards: {
      channel_id: '200', counting_enabled: counting, connected: true,
      stream_status: finished ? 'offline' : 'live', exclusions: [],
      month: { ...stream, ends_at: '2026-12-01T00:00:00Z' },
      stream: { ...stream, ends_at: finished ? '2026-11-19T13:00:00Z' : null },
    } })
  })
  const dashboard = page.getByRole('navigation').getByRole('button', { name: 'Dashboard', exact: true })
  await dashboard.click()
  const recent = page.getByRole('article', { name: 'Recent commands' })
  await expect(recent.getByRole('columnheader', { name: 'Time (UTC)' })).toBeVisible()
  await expect(recent.locator('tbody tr')).toHaveText([
    '12:30:05#weatherSent', '12:30:04#askOutput filtered', '12:30:03#forecastCooldown',
    '12:30:02#promoDelivery uncertain', '12:30:01#pingError',
  ])
  await expect(recent.getByText('Cooldown', { exact: true })).toHaveAttribute('class', /^dashboard-outcome\s*$/)
  const activity = page.getByRole('article', { name: 'Stream activity' })
  await expect(activity.getByRole('columnheader', { name: 'Messages' })).toBeVisible()
  await expect(activity.locator('tbody tr')).toHaveText(['chatter_0101', 'chatter_183', 'chatter_241'])
  const bars = await activity.locator('.dashboard-chatter-meter > span > span').evaluateAll((elements) =>
    elements.map((element) => parseFloat((element as HTMLElement).style.width)))
  for (const [index, count] of [101, 83, 41].entries()) expect(bars[index]).toBeCloseTo(count / 101 * 100, 3)

  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => Reflect.get(window, 'setDashboardStream')(false, false))
  await page.clock.runFor(5000)
  await expect(activity.getByText('Counting paused', { exact: true })).toBeVisible()
  await expect(activity.getByRole('rowheader')).toHaveCount(3)
  await page.evaluate(() => Reflect.get(window, 'setDashboardStream')(true, true))
  await page.clock.runFor(5000)
  await expect(activity.getByText('No current broadcast results.')).toBeVisible()
  await recent.getByRole('button', { name: 'View logs' }).click()
  await expect(page.getByRole('heading', { name: 'Logs', exact: true, level: 1 })).toBeVisible()
  await expect(page.getByText('Output filtered', { exact: true })).toBeVisible()
  await dashboard.click()
  await page.getByRole('button', { name: 'Open Playground', exact: true }).click()
  await expect(page.locator('#ai-playground')).toBeInViewport()
  await dashboard.click()
  await activity.getByRole('button', { name: 'View analytics' }).click()
  await expect(page.getByRole('heading', { name: 'Analytics', exact: true, level: 1 })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Chatters', exact: true })).toHaveAttribute('aria-current', 'location')
})
