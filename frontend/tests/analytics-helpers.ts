import { expect, type Page } from '@playwright/test'

export async function mockAnalytics(page: Page, desktop = false) {
  let enabled = true, empty = false, fail = false, unavailable = false, balanceState = 'available'
  let limits = { stored: 100, context: 5 }
  const calls: { path: string; body: Record<string, unknown> }[] = []
  await page.route(/\/(v1|synthetic-analytics)\/(analytics\/|ai\/balance|ai\/memory\/limits)/, async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/synthetic-analytics/', '/v1/')
    const body = route.request().postDataJSON() || {}
    calls.push({ path, body })
    if (fail && path.endsWith('/query')) return route.abort('connectionrefused')
    if (path.endsWith('/configure')) enabled = body.enabled
    if (path.endsWith('/reset')) empty = true
    if (path.endsWith('/limits')) {
      if (route.request().method() === 'POST') limits = body
      return route.fulfill({ json: { ok: true, ...limits } })
    }
    if (path.endsWith('/balance')) return route.fulfill({ json: { ok: true, provider: 'deepseek', state: balanceState,
      balances: balanceState === 'unavailable' ? [] : [{ currency: 'USD', total_balance: '12.34', granted_balance: '2', topped_up_balance: '10.34' }], updated_at: new Date().toISOString() } })
    const metrics = empty ? {} : { 'command.attempts': 8, 'command.success': 2, 'command.error': 1, 'command.skipped': 5,
      'ai.requests': 2, 'ai.attempts': 3, 'ai.input_tokens': 100, 'ai.output_tokens': 20, 'ai.usage_unknown': 1, 'ai.price_missing': 1, 'ai.estimate_incomplete': 1, 'ai.estimated_usd': 0.001 }
    return route.fulfill({ json: { ok: true, days: body.days || 7, start: '2026-10-24', end: '2026-10-30', as_of: '2026-10-30T12:00:00Z', channel_id: unavailable ? null : '200',
      connected: false, retained_users: unavailable ? null : 42, enabled, available: !unavailable, pending: 2, dropped: 1, write_failures: 0,
      metadata: { data_start: '2026-10-28T12:00:00Z' }, price_checked: '2026-10-30', price_basis: 'known subtotal', totals: metrics,
      series: [{ day: '2026-10-24', metrics: {}, coverage_seconds: 0 }, { day: '2026-10-30', metrics, coverage_seconds: 1800 }],
      commands: empty ? [] : [{ name: 'ping', metrics }], providers: empty ? [] : [{ name: 'deepseek/test-model', metrics }] } })
  })
  if (desktop) await page.evaluate(() => {
    const request = async (path: string, body?: object) => (await fetch(`/synthetic-analytics/${path}`, { method: body ? 'POST' : 'GET', ...(body ? { body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } } : {}) })).json()
    Object.assign(window.pywebview!.api, {
      get_analytics: (days: number) => request('analytics/query', { days }),
      configure_analytics: (enabled: boolean) => request('analytics/configure', { enabled }),
      reset_analytics: (confirmed: boolean) => request('analytics/reset', { confirmed }),
      get_ai_balance: (provider: string, refresh: boolean) => request('ai/balance', { provider, refresh }),
      get_ai_memory_limits: () => request('ai/memory/limits'),
      save_ai_memory_limits: (stored: number, context: number) => request('ai/memory/limits', { stored, context }),
    })
  })
  return { calls, setFail: (value: boolean) => { fail = value }, setUnavailable: () => { unavailable = true }, setBalance: (value: string) => { balanceState = value } }
}

export async function analyticsFlow(page: Page, mock: Awaited<ReturnType<typeof mockAnalytics>>, width: number, host: string) {
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await nav.getByRole('button', { name: 'Analytics', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Analytics', exact: true })).toBeVisible()
  await expect(page.locator('.analytics-layout')).toHaveAttribute('aria-busy', 'false')
  await expect(page.getByText('8 attempts', { exact: true })).toBeVisible()
  await expect(page.getByText('42', { exact: true })).toBeVisible()
  await expect(page.getByText(/Partial window/)).toBeVisible()
  await expect(page.getByText(/Disconnected —/)).toBeVisible()
  await expect(page.getByText(/Incomplete — unknown usage/)).toBeVisible()
  const windowSelect = page.getByLabel('UTC window', { exact: true })
  for (const [label, value] of [['Today', 1], ['60 days', 60], ['7 days', 7]] as const) {
    await windowSelect.click(); await page.getByRole('option', { name: label, exact: true }).click()
    await expect.poll(() => mock.calls.filter((call) => call.path.endsWith('/query')).at(-1)?.body.days).toBe(value)
    await expect(page.locator('.analytics-layout')).toHaveAttribute('aria-busy', 'false')
  }
  await windowSelect.focus(); await windowSelect.press('Space'); await page.getByRole('option', { name: '30 days', exact: true }).click()
  await expect.poll(() => mock.calls.filter((call) => call.path.endsWith('/query')).at(-1)?.body.days).toBe(30)
  const trend = page.getByLabel('Trend', { exact: true })
  await trend.focus(); await trend.press('Space'); await page.getByRole('option', { name: 'AI requests', exact: true }).click()
  await expect(page.getByRole('img', { name: /AI requests by UTC day/ })).toBeVisible()
  await page.getByText('Daily values and coverage', { exact: true }).click()
  await expect(page.getByRole('cell', { name: 'Unknown', exact: true }).first()).toBeVisible()
  await page.getByRole('checkbox', { name: 'Collect analytics' }).press('Space')
  await expect(page.getByText(/Collection disabled/)).toBeVisible()
  await page.getByRole('button', { name: 'Refresh balance', exact: true }).click()
  await expect(page.getByText('USD 12.34', { exact: true })).toBeVisible()
  mock.setBalance('stale'); await page.getByRole('button', { name: 'Refresh balance', exact: true }).click()
  await expect(page.getByText(/Stale — last known balance/)).toBeVisible()
  mock.setBalance('unavailable'); await page.getByRole('button', { name: 'Refresh balance', exact: true }).click()
  await expect(page.getByText('USD 12.34', { exact: true })).toHaveCount(0)
  await page.getByLabel('Balance provider', { exact: true }).click(); await page.getByRole('option', { name: 'OpenAI', exact: true }).click()
  await expect(page.getByText(/no supported balance API/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Refresh balance', exact: true })).toBeDisabled()
  await page.locator('main').evaluate((element) => element.scrollTo({ top: 0 }))
  await page.screenshot({ path: `node_modules/.tmp/analytics-${host}-${width}.png`, fullPage: true })
  await page.locator('.analytics-chart').evaluate((element) => element.scrollIntoView({ block: 'center' }))
  await page.locator('.analytics-chart').screenshot({ path: `node_modules/.tmp/analytics-chart-${host}-${width}.png` })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Reset all profile analytics', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toBeFocused()
  await page.keyboard.press('Escape'); await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: 'Reset all profile analytics', exact: true }).click()
  await page.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page.getByText(/No observed activity in this window/)).toBeVisible()
  mock.setFail(true); await page.getByRole('button', { name: 'Refresh analytics', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: /connection|fetch|unavailable/i }).first()).toBeVisible()
  mock.setFail(false); mock.setUnavailable(); await page.getByRole('button', { name: 'Refresh analytics', exact: true }).click()
  await expect(page.getByText(/No configured channel ID/)).toBeVisible()
  await expect(page.getByText(/Analytics storage unavailable/)).toBeVisible()
  await nav.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(page.locator('.ai-layout')).toHaveAttribute('aria-busy', 'false')
  await page.getByLabel('Stored pairs (N)', { exact: true }).fill('3')
  await page.getByLabel('Context pairs (M)', { exact: true }).fill('4')
  await expect(page.getByText(/N must be 1–500/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save memory limits' })).toBeDisabled()
  await page.getByLabel('Context pairs (M)', { exact: true }).fill('2')
  await page.getByRole('button', { name: 'Save memory limits' }).click()
  await expect(page.getByText('Memory limits saved.', { exact: true })).toBeVisible()
  await page.locator('#ai-memory').screenshot({ path: `node_modules/.tmp/memory-${host}-${width}.png` })
  expect(mock.calls.find((call) => call.path.endsWith('/limits') && call.body.stored)).toMatchObject({ body: { stored: 3, context: 2 } })
  await page.getByRole('button', { name: 'Help: Exchange limits', exact: true }).click()
  await expect(page.getByText(/One pair means one question/)).toBeVisible()
}
