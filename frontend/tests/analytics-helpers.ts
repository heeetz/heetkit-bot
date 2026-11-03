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
    return route.fulfill({ json: { ok: true, days: body.days || 7, start: '2026-10-24', end: '2026-10-30', as_of: '2026-10-30T12:30:00Z', resolution: body.days === 1 ? 'hour' : 'day', channel_id: unavailable ? null : '200',
      connected: false, retained_users: unavailable ? null : 42, enabled, available: !unavailable, pending: 2, dropped: 1, write_failures: 0,
      metadata: { data_start: '2026-10-28T12:00:00Z' }, price_checked: '2026-10-30', price_basis: 'known subtotal', totals: metrics,
      series: body.days === 1 ? Array.from({ length: 24 }, (_, hour) => ({ day: `2026-10-30T${String(hour).padStart(2, '0')}:00:00+00:00`, metrics: hour === 10 ? { ...metrics, 'users.new': 2 } : hour === 11 ? { 'connection.seconds': 3600 } : {}, coverage_seconds: hour === 10 || hour === 11 ? 3600 : 0, new_users_coverage_seconds: hour === 10 || hour === 11 ? 3600 : 0 })) : [{ day: '2026-10-24', metrics: {}, coverage_seconds: 0, new_users_coverage_seconds: 0 }, { day: '2026-10-30', metrics, coverage_seconds: 1800, new_users_coverage_seconds: 1800 }],
      commands: empty ? [] : Array.from({ length: 15 }, (_, i) => ({ name: i ? `custom:synthetic-${i}` : 'ping', label: i === 14 ? 'Deleted or unavailable command' : i === 1 ? '!long-command-name-'.repeat(8) : i ? `!custom${i}` : '!ping', metrics })), providers: empty ? [] : [{ name: 'deepseek/test-model', metrics }] } })
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
  const about = nav.getByRole('button', { name: 'About', exact: true })
  await about.focus(); await about.press('Enter')
  await expect(about).toHaveAttribute('aria-current', 'page')
  await expect(page.getByRole('heading', { name: 'About', level: 1, exact: true })).toBeVisible()
  if (width >= 1280) {
    const navBox = (await nav.boundingBox())!, aboutBox = (await about.boundingBox())!
    expect(Math.abs(navBox.y + navBox.height - aboutBox.y - aboutBox.height)).toBeLessThan(8)
    await page.setViewportSize({ width, height: 300 })
    await nav.getByRole('button', { name: 'AI', exact: true }).click()
    expect(await nav.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true)
    await about.focus(); await about.press('Enter')
    await expect(about).toBeInViewport()
    await expect(about).toHaveAttribute('aria-current', 'page')
    await page.setViewportSize({ width, height: 1000 })
  } else await expect(about).toBeInViewport()
  await nav.getByRole('button', { name: 'Analytics', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Analytics', exact: true })).toBeVisible()
  await expect(page.locator('.analytics-layout')).toHaveAttribute('aria-busy', 'false')
  await expect(page.getByText('8 attempts', { exact: true })).toBeVisible()
  await expect(page.getByText('42', { exact: true })).toBeVisible()
  await expect(page.locator('.analytics-cards > article')).toHaveCount(4)
  await expect(page.locator('.analytics-cards h2')).toHaveText(['Commands', 'Retained users now', 'AI usage', 'Provider balance'])
  await expect(page.getByRole('heading', { name: 'AI spend estimate', exact: true })).toHaveCount(0)
  const positions = await page.locator('.analytics-trend, .analytics-cards, .analytics-breakdowns, .analytics-coverage').evaluateAll((items) => items.map((el) => el.getBoundingClientRect().top))
  expect(positions).toEqual([...positions].sort((a, b) => a - b))
  const commands = page.getByRole('region', { name: 'Commands breakdown, scroll for more rows', exact: true })
  await expect(commands.getByRole('row')).toHaveCount(16)
  await expect(commands).toContainText('!ping')
  expect(await commands.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true)
  await commands.focus(); await commands.press('End')
  expect(await commands.evaluate((el) => el.scrollTop)).toBeGreaterThan(0)
  const headerTop = await commands.locator('thead').evaluate((el) => el.querySelector('th')!.getBoundingClientRect().top)
  expect(Math.abs(headerTop - (await commands.boundingBox())!.y)).toBeLessThan(2)
  await commands.evaluate((el) => { el.scrollTop = 0 })
  await page.locator('.analytics-cards').screenshot({ path: `node_modules/.tmp/analytics-cards-${host}-${width}.png` })
  await expect(page.getByText(/Partial window/)).toBeVisible()
  await expect(page.getByText(/Disconnected —/)).toBeVisible()
  await expect(page.getByText(/Incomplete — unknown usage/)).toBeVisible()
  const windowSelect = page.getByLabel('UTC window', { exact: true })
  for (const [label, value] of [['Today', 1], ['60 days', 60], ['7 days', 7]] as const) {
    await windowSelect.click(); await page.getByRole('option', { name: label, exact: true }).click()
    await expect.poll(() => mock.calls.filter((call) => call.path.endsWith('/query')).at(-1)?.body.days).toBe(value)
    await expect(page.locator('.analytics-layout')).toHaveAttribute('aria-busy', 'false')
    if (value === 1) {
      await expect(page.getByRole('img', { name: /Command attempts by UTC hour/ })).toBeVisible()
      await page.getByText('Hourly values and coverage', { exact: true }).click()
      await expect(page.getByRole('region', { name: 'Trend values and coverage' }).getByRole('row')).toHaveCount(25)
      await expect(page.getByRole('cell', { name: 'Future hour', exact: true })).toHaveCount(11)
      await expect(page.getByRole('region', { name: 'Trend values and coverage' }).getByRole('cell', { name: '0', exact: true })).toHaveCount(1)
      await page.locator('.analytics-chart').screenshot({ path: `node_modules/.tmp/analytics-hourly-${host}-${width}.png` })
    }
  }
  expect(mock.calls.filter((call) => call.path.endsWith('/balance'))).toHaveLength(0)
  await windowSelect.scrollIntoViewIfNeeded(); await windowSelect.focus(); await windowSelect.press('Space'); await page.getByRole('option', { name: '30 days', exact: true }).click()
  await expect.poll(() => mock.calls.filter((call) => call.path.endsWith('/query')).at(-1)?.body.days).toBe(30)
  await expect(page.locator('.analytics-layout')).toHaveAttribute('aria-busy', 'false')
  const trend = page.getByLabel('Trend', { exact: true })
  await page.locator('main').evaluate((element) => element.scrollTo({ top: 0 })); await trend.focus(); await trend.press('Space'); await page.getByRole('option', { name: 'AI requests', exact: true }).click()
  await expect(page.getByRole('img', { name: /AI requests by UTC day/ })).toBeVisible()
  await page.getByText('Daily values and coverage', { exact: true }).click()
  await expect(page.getByRole('cell', { name: 'Unknown', exact: true }).first()).toBeVisible()
  await trend.click(); await page.getByRole('option', { name: 'Newly observed users', exact: true }).click()
  await page.getByRole('button', { name: 'Help: Newly observed users', exact: true }).click()
  await expect(page.getByText(/A viewer can count again/)).toBeVisible()
  await page.keyboard.press('Escape')
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
  await page.locator('.analytics-breakdowns').screenshot({ path: `node_modules/.tmp/analytics-breakdowns-${host}-${width}.png` })
  await page.locator('.analytics-coverage').screenshot({ path: `node_modules/.tmp/analytics-coverage-${host}-${width}.png` })
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
  await page.getByLabel('Balance provider', { exact: true }).click(); await page.getByRole('option', { name: 'DeepSeek', exact: true }).click()
  mock.setBalance('available'); await page.getByRole('button', { name: 'Refresh balance', exact: true }).click()
  await expect(page.getByText('USD 12.34', { exact: true })).toBeVisible()
  await nav.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(page.locator('.ai-layout')).toHaveAttribute('aria-busy', 'false')
  await expect(page.locator('#ai-runtime > article')).toHaveCount(2)
  await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).toHaveCount(0)
  await page.locator('#ai-runtime').screenshot({ path: `node_modules/.tmp/ai-state-${host}-${width}.png` })
  if (width >= 1280) {
    const left = (await page.locator('#ai-runtime > article').first().boundingBox())!
    const right = (await page.locator('#ai-memory').boundingBox())!
    expect(left.y).toBe(right.y)
    expect(right.width / left.width).toBeGreaterThan(1.9)
  }
  const memory = page.getByRole('checkbox', { name: 'Enable conversation memory', exact: true })
  const checked = await memory.isChecked()
  await memory.press('Space'); await expect(memory).toBeChecked({ checked: !checked })
  await page.getByLabel('Stored pairs (N)', { exact: true }).fill('20')
  await page.locator('.memory-limits').getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByLabel('Stored pairs (N)', { exact: true })).toHaveValue('100')
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
