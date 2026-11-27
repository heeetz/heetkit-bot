import { expect, test } from '@playwright/test'
import type { LogEntry } from '../src/bridge'
import { readFile } from 'node:fs/promises'
import { expectNoOverflow, login, navigate, selectOption, server, signIn } from './browser-fixture'

test('Logs filters fixture activity, shows related events and exports only those entries', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  const api = await server(page)
  api.setLogs([
    { id: 1, timestamp: '2026-10-23T11:00:00Z', level: 'INFO', source: 'synthetic', message: 'command.input',
      event_kind: 'command.input', text: '!ping sample input', context: { request_id: 'ping-1', command: 'ping', outcome: 'received' } },
    { id: 2, timestamp: '2026-10-23T11:00:01Z', level: 'WARNING', source: 'synthetic', message: 'chat.outgoing',
      event_kind: 'chat.outgoing', text: '@viewer PONG', context: { request_id: 'ping-1', command: 'ping', outcome: 'uncertain_send' } },
    { id: 3, timestamp: '2026-10-23T11:00:02Z', level: 'INFO', source: 'synthetic', message: 'command.input',
      event_kind: 'command.input', text: '!other', context: { request_id: 'other-1' } },
  ])
  await signIn(page)
  await navigate(page, 'Logs')
  await expect(page.getByRole('heading', { name: 'Logs', level: 1 })).toBeVisible()
  const command = page.getByText('!ping sample input', { exact: true })
  const reply = page.getByText('@viewer PONG', { exact: true })
  const other = page.getByText('!other', { exact: true })
  await expect(reply).toBeVisible()
  await expect(other).toBeVisible()
  await expectNoOverflow(page)
  await selectOption(page.getByRole('combobox', { name: 'Outcome', exact: true }), 'uncertain_send')
  await expect(command).toHaveCount(0)
  await expect(reply).toBeVisible()
  await page.getByText('Event details', { exact: true }).click()
  await expect(page.getByText('ping-1', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Show related events' }).click()
  await expect(command).toBeVisible()
  await expect(other).toHaveCount(0)

  await page.getByRole('button', { name: /Export filtered/ }).click()
  const download = page.waitForEvent('download')
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm' }).click()
  const exported = JSON.parse(await readFile((await (await download).path())!, 'utf8'))
  expect(exported.entries.map(({ id }: { id: number }) => id)).toEqual([1, 2])
  await page.getByRole('button', { name: /Clear view/ }).click()
  await expect(command).toHaveCount(0)
})

test('status and logs poll at most every five seconds, use cursor and pause while hidden', async ({ page }) => {
  const api = await server(page)
  api.setLogs(Array.from({ length: 450 }, (_, index) => ({
    id: index + 1, timestamp: '2026-11-18T00:00:00Z', source: 'synthetic', level: 'INFO',
    message: 'command.input', event_kind: 'command.input', text: `!activity-${index + 1}`, context: {},
  })))
  await page.clock.install()
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  await expect.poll(() => api.calls.filter((call) => call.path === '/v1/ops/get_snapshot').length).toBeGreaterThan(0)
  const snapshots = api.calls.filter((call) => call.path === '/v1/ops/get_snapshot').length
  // The installed clock also runs in real time, so leave slow runners a margin before the 5 s poll.
  await page.clock.fastForward(4000)
  expect(api.calls.filter((call) => call.path === '/v1/ops/get_snapshot')).toHaveLength(snapshots)
  await page.getByRole('button', { name: 'Logs', exact: true }).click()
  await expect.poll(() => api.calls.filter((call) => call.path === '/v1/ops/get_recent_logs').length).toBe(1)
  await expect(page.getByText('!activity-450', { exact: true })).toBeVisible()
  expect(api.calls.filter((call) => call.path === '/v1/ops/get_recent_logs')[0].body)
    .toEqual({ after_id: 0, limit: 200, snapshot: true })
  await page.clock.fastForward(5100)
  await expect.poll(() => api.calls.filter((call) => call.path === '/v1/ops/get_recent_logs').length).toBe(2)
  expect(api.calls.filter((call) => call.path === '/v1/ops/get_recent_logs').at(-1)?.body).toEqual({ after_id: 450, limit: 200 })
  await page.evaluate(() => Object.defineProperty(document, 'hidden', { value: true, configurable: true }))
  const count = api.calls.length
  await page.clock.fastForward(15000)
  expect(api.calls).toHaveLength(count)
  await page.evaluate(() => Object.defineProperty(document, 'hidden', { value: false, configurable: true }))
  await page.clock.fastForward(5100)
  await expect.poll(() => api.calls.filter((call) => call.path === '/v1/ops/get_recent_logs').length).toBe(3)
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  await page.clock.fastForward(5100)
  const logs = api.calls.filter((call) => call.path === '/v1/ops/get_recent_logs').length
  await page.clock.fastForward(5100)
  expect(api.calls.filter((call) => call.path === '/v1/ops/get_recent_logs')).toHaveLength(logs)
})

test('Server Logs ignores a stale opening request and picks up traffic during the next snapshot', async ({ page }) => {
  await server(page)
  await page.clock.install()
  const pending: (() => void)[] = []
  const requests: unknown[] = []
  const entry = (id: number) => ({
    id, timestamp: '2026-11-18T00:00:00Z', source: 'synthetic', level: 'INFO',
    message: 'command.input', event_kind: 'command.input', text: `!activity-${id}`, context: {},
  })
  let latest: LogEntry[] = []
  await page.route('**/v1/ops/get_recent_logs', async (route) => {
    const request = route.request().postDataJSON()
    const index = requests.push(request)
    if (request.snapshot) await new Promise<void>((resume) => pending.push(resume))
    const entries = request.snapshot ? [entry(index === 1 ? 999 : 410)] : latest
    await route.fulfill({ json: { ok: true, entries, next_after_id: request.snapshot && index === 2 ? 411 : entries.at(-1)?.id } })
  })
  await page.goto('/tests/browser.fixture.html')
  await login(page)
  const logs = page.getByRole('button', { name: 'Logs', exact: true })
  await logs.click()
  await expect.poll(() => pending.length).toBe(1)
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  await logs.click()
  await expect.poll(() => pending.length).toBe(2)
  latest = [entry(412)]
  pending[1]()
  await expect(page.getByText('!activity-410', { exact: true })).toBeVisible()
  expect(requests.slice(0, 2)).toEqual(Array(2).fill({ after_id: 0, limit: 200, snapshot: true }))
  const abandoned = page.waitForResponse('**/v1/ops/get_recent_logs')
  pending[0]()
  await abandoned
  await page.clock.fastForward(5100)
  await expect(page.getByText('!activity-412', { exact: true })).toBeVisible()
  await expect(page.getByText('!activity-999', { exact: true })).toHaveCount(0)
  expect(requests[2]).toEqual({ after_id: 411, limit: 200 })
})

test('the activity view evicts older entries when large payloads cross its display limit', async ({ page }) => {
  const api = await server(page)
  const text = 'é'.repeat(2100)
  api.setLogs(Array.from({ length: 340 }, (_, index) => ({
    id: index + 1, timestamp: '2026-11-18T00:00:00Z', source: 'synthetic', level: 'INFO',
    message: 'synthetic-event-' + (index + 1), event_kind: null, context: {}, text,
  })))
  await signIn(page)
  await navigate(page, 'Logs')
  await expect(page.getByText('synthetic-event-340', { exact: true })).toBeVisible()
  await expect(page.getByText('synthetic-event-1', { exact: true })).toHaveCount(0)
  const events = page.getByText(/^synthetic-event-\d+$/)
  expect(await events.count()).toBeGreaterThan(100)
  expect(await events.count()).toBeLessThan(250)
})
