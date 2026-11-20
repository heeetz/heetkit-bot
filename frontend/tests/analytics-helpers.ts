import { expect, type Page } from '@playwright/test'

export async function mockAnalytics(page: Page, desktop = false) {
  let enabled = true, empty = false, fail = false, unavailable = false, balanceState = 'available'
  let inventoryChanged = false, counting = true
  let limits = { stored: 100, context: 5 }
  const calls: { path: string; body: Record<string, unknown> }[] = []
  await page.route(/\/(v1|synthetic-analytics)\/(analytics\/|leaderboards\/configure|ai\/balance|ai\/memory\/limits)/, async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/synthetic-analytics/', '/v1/')
    const body = route.request().postDataJSON() || {}
    calls.push({ path, body })
    if (fail && path.endsWith('/query')) return route.abort('connectionrefused')
    if (path === '/v1/analytics/configure') enabled = body.enabled
    if (path === '/v1/leaderboards/configure') {
      counting = body.enabled
      return route.fulfill({ json: { ok: true } })
    }
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
      connected: false, retained_users: unavailable ? null : 42, enabled, count_chat_messages: counting, available: !unavailable, pending: 2, dropped: 1, write_failures: 0,
      metadata: { data_start: '2026-10-28T12:00:00Z' }, price_checked: '2026-10-30', price_basis: 'known subtotal', totals: metrics,
      series: body.days === 1 ? Array.from({ length: 24 }, (_, hour) => ({ day: `2026-10-30T${String(hour).padStart(2, '0')}:00:00+00:00`, metrics: hour === 10 ? { ...metrics, 'users.new': 2 } : hour === 11 ? { 'connection.seconds': 3600 } : {}, coverage_seconds: hour === 10 || hour === 11 ? 3600 : 0, new_users_coverage_seconds: hour === 10 || hour === 11 ? 3600 : 0 })) : [{ day: '2026-10-24', metrics: {}, coverage_seconds: 0, new_users_coverage_seconds: 0 }, { day: '2026-10-30', metrics, coverage_seconds: 1800, new_users_coverage_seconds: 1800 }],
      commands: [...Array.from({ length: 15 }, (_, i) => ({
        name: i ? `custom:synthetic-${i}` : 'ping',
        label: i === 14 || (inventoryChanged && i === 3) ? `Deleted or unavailable command (custom:synthetic-${i})` : inventoryChanged && i === 2 ? '!renamed' : i === 1 ? '!long-command-name-'.repeat(8) : i === 13 ? '!disabled-zero' : i ? `!custom${i}` : '!ping',
        metrics: empty || i === 13 ? {} : { ...metrics, 'command.attempts': i === 0 ? 8 : i <= 2 ? 4 : 1 },
      })).filter((row) => !row.label.startsWith('Deleted or unavailable')),
      ...(inventoryChanged ? [{ name: 'custom:new', label: '!new-command', metrics: {} }] : [])]
        .sort((a, b) => ((b.metrics as Record<string, number>)['command.attempts'] || 0) - ((a.metrics as Record<string, number>)['command.attempts'] || 0) || a.label.localeCompare(b.label) || a.name.localeCompare(b.name)),
      providers: empty ? [] : [{ name: 'deepseek/test-model', metrics }] } })
  })
  if (desktop) await page.evaluate(() => {
    const request = async (path: string, body?: object) => (await fetch(`/synthetic-analytics/${path}`, { method: body ? 'POST' : 'GET', ...(body ? { body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } } : {}) })).json()
    const appStatus = window.pywebview!.api.get_app_status
    Object.assign(window.pywebview!.api, {
      get_app_status: async () => ({ ...await appStatus(), leaderboard_channel_id: null }),
      get_analytics: (days: number) => request('analytics/query', { days }),
      configure_analytics: (enabled: boolean) => request('analytics/configure', { enabled }),
      configure_leaderboard_counting: (enabled: boolean) => request('leaderboards/configure', { enabled }),
      reset_analytics: (confirmed: boolean) => request('analytics/reset', { confirmed }),
      get_ai_balance: (provider: string, refresh: boolean) => request('ai/balance', { provider, refresh }),
      get_ai_memory_limits: () => request('ai/memory/limits'),
      save_ai_memory_limits: (stored: number, context: number) => request('ai/memory/limits', { stored, context }),
    })
  })
  return { calls, changeInventory: () => { inventoryChanged = true }, setFail: (value: boolean) => { fail = value }, setUnavailable: () => { unavailable = true }, setBalance: (value: string) => { balanceState = value } }
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
  await nav.getByRole('button', { name: 'Trends', exact: true }).click()
  await expect(page.locator('#analytics-trends')).toBeInViewport()
  for (const [label, id, heading] of [
    ['Chatters', 'analytics-chatters', 'Stream top 10 chatters'],
    ['Breakdown', 'analytics-breakdown', 'Commands breakdown'],
    ['Collection', 'analytics-collection', 'Collection & coverage'],
  ]) {
    const shortcut = nav.getByRole('button', { name: label, exact: true })
    await shortcut.click()
    await expect(shortcut).toHaveAttribute('aria-current', 'location')
    const target = page.locator(`#${id}`).getByRole('heading', { name: heading, exact: true })
    await expect(target).toBeInViewport()
    expect((await target.boundingBox())!.y).toBeGreaterThanOrEqual(0)
  }
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
  await expect(commands.getByRole('row')).toHaveCount(15)
  await expect(commands).toContainText('!ping')
  expect(await commands.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true)
  if (width >= 1280) expect(await commands.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true)
  await commands.focus(); await commands.press('End')
  await expect.poll(() => commands.evaluate((el) => el.scrollTop)).toBeGreaterThan(0)
  const headerTop = await commands.locator('thead').evaluate((el) => el.querySelector('th')!.getBoundingClientRect().top)
  expect(Math.abs(headerTop - (await commands.boundingBox())!.y)).toBeLessThan(2)
  await commands.evaluate((el) => { el.scrollTop = 0 })
  await page.locator('.analytics-cards').screenshot({ path: `node_modules/.tmp/analytics-cards-${host}-${width}.png` })
  await expect(commands.getByRole('button')).toHaveCount(0)
  await expect(commands.locator('tbody tr').first()).toContainText('!ping')
  await expect(commands.locator('tbody tr').last()).toHaveText('!disabled-zero0000')
  await page.getByRole('button', { name: 'Help: How attempts are counted', exact: true }).click()
  await expect(page.getByRole('tooltip')).toContainText('Zero means HeetKit recorded no attempts')
  await page.keyboard.press('Escape')
  mock.changeInventory()
  await page.getByRole('button', { name: 'Refresh analytics', exact: true }).click()
  await expect(commands.getByRole('row')).toHaveCount(15)
  await expect(commands).toContainText('!renamed')
  await expect(commands).not.toContainText('Deleted or unavailable command')
  await expect(commands.locator('tbody tr').last()).toHaveText('!new-command0000')
  const coverage = page.locator('.analytics-coverage')
  const details = coverage.locator('details')
  const collect = coverage.getByRole('checkbox', { name: 'Collect analytics' })
  const countMessages = coverage.getByRole('checkbox', { name: 'Count chat messages' })
  const reset = coverage.getByRole('button', { name: 'Reset all profile analytics', exact: true })
  await expect(details).not.toHaveAttribute('open', '')
  await expect(collect).toBeChecked()
  await expect(countMessages).toBeChecked()
  await expect(details.getByText('Data since', { exact: true })).toBeHidden()
  await expect(coverage.getByText('Partial coverage', { exact: true })).toBeVisible()
  await expect(coverage.getByRole('alert').filter({ hasText: 'Possible data loss' })).toHaveText('Possible data loss')
  await expect(reset).toBeVisible()
  const groups = await coverage.locator('.analytics-coverage-zones > *').evaluateAll((items) => items.map((el) => {
    const r = el.getBoundingClientRect()
    return { left: r.left, right: r.right, top: r.top, bottom: r.bottom }
  }))
  if (width >= 1280) {
    expect(groups[0].right).toBeLessThan(groups[1].left)
  } else {
    expect(groups[0].bottom).toBeLessThan(groups[1].top)
  }
  const assertFooterSeparation = async () => {
    const detailBox = await details.boundingBox()
    const resetBox = await reset.boundingBox()
    expect(detailBox).not.toBeNull()
    expect(resetBox).not.toBeNull()
    if (Math.abs(resetBox!.y - detailBox!.y) <= 2) {
      expect(resetBox!.x).toBeGreaterThanOrEqual(detailBox!.x + detailBox!.width + 12)
    } else {
      expect(resetBox!.y).toBeGreaterThanOrEqual(detailBox!.y + detailBox!.height + 8)
      expect(resetBox!.x).toBeGreaterThanOrEqual(detailBox!.x)
    }
  }
  await assertFooterSeparation()
  await coverage.getByText('Collection details', { exact: true }).click()
  await expect(details.getByText('Pending updates', { exact: true })).toBeVisible()
  await expect(details.getByText('Data since', { exact: true })).toBeVisible()
  await expect(details.getByText('2026-10-28 12:00:00 UTC', { exact: true })).toBeVisible()
  await expect(details.getByText('Disconnected · Coverage gap', { exact: true })).toBeVisible()
  await expect(details.getByText('Dropped updates', { exact: true })).toBeVisible()
  await expect(details.getByText('Write failures', { exact: true })).toBeVisible()
  await assertFooterSeparation()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await details.screenshot({ path: `node_modules/.tmp/analytics-details-${host}-${width}.png` })
  await coverage.getByText('Collection details', { exact: true }).click()
  await expect(details.getByText('Disconnected · Coverage gap', { exact: true })).toBeHidden()
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
  await page.getByRole('button', { name: 'Help: Who counts', exact: true }).click()
  await expect(page.getByText(/A viewer can count again/)).toBeVisible()
  await page.keyboard.press('Escape')
  await collect.press('Space')
  await expect(collect).not.toBeChecked()
  await expect(countMessages).toBeChecked()
  await expect(coverage.getByText(/Collection paused/)).toBeVisible()
  await countMessages.press('Space')
  await expect(countMessages).not.toBeChecked()
  await expect(collect).not.toBeChecked()
  await collect.press('Space')
  await expect(collect).toBeChecked()
  await expect(countMessages).not.toBeChecked()
  await countMessages.press('Space')
  await expect(countMessages).toBeChecked()
  await expect(collect).toBeChecked()
  expect(mock.calls.filter((call) => call.path === '/v1/leaderboards/configure').map((call) => call.body)).toEqual([
    { enabled: false }, { enabled: true },
  ])
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
  await page.locator('#analytics-breakdown').screenshot({ path: `node_modules/.tmp/analytics-breakdowns-${host}-${width}.png` })
  await page.locator('.analytics-coverage').screenshot({ path: `node_modules/.tmp/analytics-coverage-${host}-${width}.png` })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('button', { name: 'Reset all profile analytics', exact: true }).click()
  const resetDialog = page.getByRole('dialog', { name: 'Reset all profile analytics?' })
  await expect(resetDialog).toContainText('Permanently clear aggregate totals for every channel and Playground in this profile, including pending updates. Personal AI memory, presence and opt-outs are unchanged. Operator-managed backups are separate copies.')
  await expect(resetDialog.getByRole('button', { name: 'Cancel', exact: true })).toBeFocused()
  await page.keyboard.press('Escape'); await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.getByRole('button', { name: 'Reset all profile analytics', exact: true }).click()
  await page.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(page.getByText(/No observed activity in this window/)).toBeVisible()
  mock.setFail(true); await page.getByRole('button', { name: 'Refresh analytics', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: /connection|fetch|unavailable/i }).first()).toBeVisible()
  mock.setFail(false); mock.setUnavailable(); await page.getByRole('button', { name: 'Refresh analytics', exact: true }).click()
  await expect(coverage.locator('[role="status"]')).toContainText('No configured channel ID.')
  await expect(page.getByText(/Analytics storage unavailable/)).toBeVisible()
  await expect(commands.locator('tbody tr').first().getByRole('cell', { name: 'Unavailable', exact: true })).toHaveCount(4)
  await expect(details).not.toHaveAttribute('open', '')
  await page.getByLabel('Balance provider', { exact: true }).click(); await page.getByRole('option', { name: 'DeepSeek', exact: true }).click()
  mock.setBalance('available'); await page.getByRole('button', { name: 'Refresh balance', exact: true }).click()
  await expect(page.getByText('USD 12.34', { exact: true })).toBeVisible()
  await nav.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(page.locator('.ai-layout')).toHaveAttribute('aria-busy', 'false')
  const behavior = page.locator('#ai-behavior')
  await expect(behavior.getByRole('heading')).toHaveText('AI behavior')
  await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).toHaveCount(0)
  await behavior.screenshot({ path: `node_modules/.tmp/ai-state-${host}-${width}.png` })
  const memoryPanel = page.getByRole('form', { name: 'Conversation memory' })
  const memory = page.getByRole('checkbox', { name: 'Enable conversation memory', exact: true })
  const checked = await memory.isChecked()
  await memory.press('Space'); await expect(memory).toBeChecked({ checked: !checked })
  await page.getByLabel('Stored pairs', { exact: true }).fill('20')
  await memoryPanel.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByLabel('Stored pairs', { exact: true })).toHaveValue('100')
  await page.getByLabel('Stored pairs', { exact: true }).fill('3')
  await page.getByLabel('Pairs in context', { exact: true }).fill('4')
  await expect(page.getByText(/N must be 1–500/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save memory limits' })).toBeDisabled()
  await page.getByLabel('Pairs in context', { exact: true }).fill('2')
  await page.getByRole('button', { name: 'Save memory limits' }).click()
  await expect(page.getByText('Memory limits saved.', { exact: true })).toBeVisible()
  await page.locator('#ai-memory').screenshot({ path: `node_modules/.tmp/memory-${host}-${width}.png` })
  expect(mock.calls.find((call) => call.path.endsWith('/limits') && call.body.stored)).toMatchObject({ body: { stored: 3, context: 2 } })
  await page.getByRole('button', { name: 'Help: How memory works', exact: true }).click()
  await expect(page.getByText(/A pair is one question and its successful answer/)).toBeVisible()
}
