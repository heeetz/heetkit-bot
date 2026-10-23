import { expect, test } from '@playwright/test'
import { selectOption } from './select-helpers'
import type { LogEntry } from '../src/bridge'

test.use({ timezoneId: 'UTC' })

for (const width of [1280, 390]) {
  test(`operator activity filters, links, private export and clear at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/tests/fixture.html?configured')
    await page.evaluate(() => {
      window.pywebview!.api.export_activity = async (ids) => {
        document.documentElement.dataset.activityExport = JSON.stringify(ids)
        return { ok: true, saved: true }
      }
      window.pywebview!.api.get_recent_logs = async (after = 0) => ({
        entries: ([
          { id: 1, timestamp: '2026-10-23T11:00:00Z', level: 'INFO', source: 'synthetic', message: 'command.input outcome=received', event_kind: 'command.input', text: '!ping <literal>', context: { command: 'ping', invoked_name: 'p', request_id: 'request-one', source: 'command', outcome: 'received' } },
          { id: 2, timestamp: '2026-10-23T11:01:00Z', level: 'INFO', source: 'synthetic', message: 'ai.result outcome=generated', event_kind: 'ai.result', text: null, context: { command: 'ask', request_id: 'request-two', source: 'playground', outcome: 'generated' } },
          { id: 3, timestamp: '2026-10-23T11:02:00Z', level: 'INFO', source: 'synthetic', message: 'chat.outgoing outcome=uncertain_send', event_kind: 'chat.outgoing', text: '@viewer exact <reply>', context: { command: 'ping', request_id: 'request-one', response_id: 'response-one', source: 'command', outcome: 'uncertain_send' } },
          { id: 4, timestamp: '2026-10-23T11:03:00Z', level: 'WARNING', source: 'synthetic', message: 'command.outcome outcome=cooldown', event_kind: 'command.outcome', text: null, context: { command: 'ping', request_id: 'request-three', source: 'command', outcome: 'cooldown', retry_after_seconds: 12.5 } },
        ] as LogEntry[]).filter((entry) => entry.id > after), next_after_id: 4,
      })
    })
    await page.getByRole('button', { name: 'Logs', exact: true }).click()
    const rows = page.locator('.log-row')
    await expect(rows).toHaveCount(4)
    await expect(page.getByText('!ping <literal>', { exact: true })).toBeVisible()
    await selectOption(page.getByRole('combobox', { name: 'Level', exact: true }), 'WARNING')
    await expect(rows).toHaveCount(1)
    await expect(rows).toContainText('12.50s remaining')
    await selectOption(page.getByRole('combobox', { name: 'Level', exact: true }), 'ALL')
    await page.getByRole('textbox', { name: 'Command', exact: true }).fill('ask')
    await expect(rows).toHaveCount(1)
    await page.getByRole('textbox', { name: 'Command', exact: true }).fill('')
    await selectOption(page.getByRole('combobox', { name: 'Outcome', exact: true }), 'uncertain_send')
    await expect(rows).toHaveCount(1)
    await expect(rows).toContainText('@viewer exact <reply>')
    await selectOption(page.getByRole('combobox', { name: 'Outcome', exact: true }), 'ALL')
    await selectOption(page.getByRole('combobox', { name: 'Source', exact: true }), 'playground')
    await expect(rows).toHaveCount(1)
    await selectOption(page.getByRole('combobox', { name: 'Source', exact: true }), 'ALL')
    await page.getByLabel('From', { exact: true }).fill('2026-10-23T11:02')
    await expect(rows).toHaveCount(2)
    await page.getByLabel('Until', { exact: true }).fill('2026-10-23T11:02')
    await expect(rows).toHaveCount(1)
    await page.getByLabel('From', { exact: true }).fill('')
    await page.getByLabel('Until', { exact: true }).fill('')
    await page.getByRole('textbox', { name: 'Search', exact: true }).fill('<reply>')
    await expect(rows).toHaveCount(1)
    await page.getByRole('textbox', { name: 'Search', exact: true }).fill('')
    await rows.first().getByText('Event details', { exact: true }).click()
    await rows.first().getByRole('button', { name: 'Show related events' }).click()
    await expect(rows).toHaveCount(2)
    await page.getByRole('button', { name: 'Export filtered…' }).click()
    await expect(page.getByRole('dialog')).toContainText('2 filtered events')
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
    await page.getByRole('button', { name: 'Export filtered…' }).click()
    await page.getByRole('button', { name: 'Confirm', exact: true }).click()
    await expect(page.locator('html')).toHaveAttribute('data-activity-export', '[1,3]')
    await expect(page.getByRole('status')).toHaveText('Private activity saved.')
    await page.screenshot({ path: `node_modules/.tmp/activity-${width}.png`, fullPage: true })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.getByRole('button', { name: 'All requests' }).click()
    await expect(rows).toHaveCount(4)
    await page.getByRole('button', { name: 'Clear view' }).click()
    await expect(rows).toHaveCount(0)
    await page.waitForTimeout(1200)
    await expect(rows).toHaveCount(0)
  })
}

for (const textSize of [20, 4096]) {
  test(`operator activity display bounds entries and UTF-8 bytes with ${textSize} byte text`, async ({ page }) => {
    await page.goto('/tests/fixture.html?configured')
    await page.evaluate((size) => {
      window.pywebview!.api.get_recent_logs = async (after = 0) => ({
        entries: after ? [] : Array.from({ length: 600 }, (_, index) => ({
          id: index + 1, timestamp: '2026-10-23T11:00:00Z', level: 'INFO', source: 'synthetic',
          event_kind: 'command.input', message: 'command.input outcome=received', context: {}, text: 'x'.repeat(size),
        })), next_after_id: 600,
      })
    }, textSize)
    await page.getByRole('button', { name: 'Logs', exact: true }).click()
    const rows = page.locator('.log-row')
    await expect(rows.last().locator('.log-content')).toHaveText('x'.repeat(textSize))
    const count = await rows.count()
    if (textSize === 20) expect(count).toBe(500)
    else {
      expect(count).toBeGreaterThan(100)
      expect(count).toBeLessThan(250)
    }
  })
}
