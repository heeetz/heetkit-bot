import { expect, test } from '@playwright/test'
import { selectOption } from './select-helpers'

for (const width of [1280, 390, 320]) {
  test(`empty announcements hide the entire footer and new drafts show only example placeholders at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/tests/commands.fixture.html')
    const panel = page.locator('#announcements')
    await expect(panel).toContainText('No announcements configured.')
    await expect(panel.locator('.announcement-collection')).toHaveCount(0)
    await expect(panel.getByRole('button', { name: 'Save announcements', exact: true })).toHaveCount(0)
    await expect(panel.getByRole('button', { name: 'Cancel', exact: true })).toHaveCount(0)
    await expect(panel.getByRole('button', { name: 'Help: Saving announcements', exact: true })).toHaveCount(0)
    await panel.screenshot({ path: `node_modules/.tmp/announcements-empty-${width}.png` })
    await panel.getByRole('button', { name: 'New announcement', exact: true }).click()
    await expect(panel.getByLabel('Name', { exact: true })).toHaveAttribute('placeholder', 'e.g. Community reminder')
    await expect(panel.getByLabel('Name', { exact: true })).toHaveValue('')
    await expect(panel.getByLabel('Announcement message', { exact: true })).toHaveAttribute('placeholder', 'e.g. Join our community: https://example.com')
    await expect(panel.getByLabel('Announcement message', { exact: true })).toHaveValue('')
    await expect(panel.getByRole('button', { name: 'Remove from draft', exact: true })).toHaveCount(0)
    await expect(panel.getByRole('button', { name: 'Delete announcement', exact: true })).toHaveCount(0)
    await expect(panel.getByRole('button', { name: 'Save announcements', exact: true })).toBeVisible()
    await panel.screenshot({ path: `node_modules/.tmp/announcements-new-draft-${width}.png` })
    await selectOption(panel.getByLabel('Message selection', { exact: true }), 'random')
    await expect(panel.getByLabel('Random messages', { exact: true })).toHaveAttribute('placeholder', /community.*\nFollow/)
    await expect(panel.getByLabel('Random messages', { exact: true })).toHaveValue('')
    await panel.getByRole('button', { name: 'Save announcements', exact: true }).click()
    await expect(panel.getByRole('alert')).toContainText('Use a name')
    expect(await page.evaluate(() => Reflect.get(window, 'commandCalls'))).toEqual([])
    await panel.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(panel.locator('.announcement-collection')).toHaveCount(0)
  })
}

test('announcement drafts save random messages and both-host stream restrictions together', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html?announcements')
  const panel = page.locator('#announcements')
  await panel.getByRole('button', { name: 'Help: Announcement status Community', exact: true }).click()
  await expect(page.getByRole('tooltip')).toContainText('Last outcome: Sent')
  await expect(page.getByRole('tooltip')).toContainText('Eligible messages: 2')
  await page.keyboard.press('Escape')
  await panel.getByRole('button', { name: 'Edit announcement Community', exact: true }).click()
  await panel.getByLabel('Name', { exact: true }).fill('Community links')
  await panel.getByLabel('Interval (s)', { exact: true }).fill('1200')
  await selectOption(panel.getByLabel('Message selection', { exact: true }), 'random')
  await panel.getByLabel('Random messages', { exact: true }).fill('  First community link.\n\n Second community link. ')
  await panel.getByLabel('Trigger after', { exact: true }).fill('8')
  await selectOption(panel.getByLabel('Works when:', { exact: true }), 'offline_only')
  await panel.getByRole('button', { name: 'Save announcements', exact: true }).click()
  await expect(panel.getByRole('status')).toContainText('Announcements saved')
  expect(await page.evaluate(() => Reflect.get(window, 'commandCalls'))).toEqual([['save_announcements', [{
    id: '00000000-0000-0000-0000-000000000001', name: 'Community links', enabled: true,
    messages: ['First community link.', 'Second community link.'], message_mode: 'random',
    interval_seconds: 1200, min_messages: 8, stream_availability: 'offline_only',
  }]]])
  await expect(panel.getByRole('button', { name: 'Save announcements', exact: true })).toBeDisabled()
  await panel.getByRole('button', { name: 'Edit announcement Community links', exact: true }).click()
  await expect(panel.getByLabel('Random messages', { exact: true })).toHaveValue('First community link.\nSecond community link.')
  await panel.getByLabel('Enable announcement', { exact: true }).uncheck({ force: true })
  await panel.getByRole('button', { name: 'Save announcements', exact: true }).click()
  await expect(panel.locator('.state-pill')).toHaveText('Disabled')
})

test('cancel discards edits and draft removal without changing the saved collection', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html?announcements')
  const panel = page.locator('#announcements')
  await panel.getByRole('button', { name: 'Edit announcement Community', exact: true }).click()
  await panel.getByLabel('Name', { exact: true }).fill('Changed name')
  await panel.getByRole('button', { name: 'Delete announcement', exact: true }).click()
  await expect(panel).toContainText('All announcements marked for deletion.')
  await panel.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'Edit announcement Community', exact: true })).toBeVisible()
  await panel.getByRole('button', { name: 'New announcement', exact: true }).click()
  await panel.getByLabel('Name', { exact: true }).fill('Draft only')
  await panel.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(panel.locator('.announcement-card')).toHaveCount(1)
  expect(await page.evaluate(() => Reflect.get(window, 'commandCalls'))).toEqual([])
})

test('deleting the last saved announcement can be committed before the empty footer disappears', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html?announcements')
  const panel = page.locator('#announcements')
  await panel.getByRole('button', { name: 'Edit announcement Community', exact: true }).click()
  await panel.getByRole('button', { name: 'Delete announcement', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'Save announcements', exact: true })).toBeEnabled()
  await panel.getByRole('button', { name: 'Save announcements', exact: true }).click()
  await expect(panel).toContainText('No announcements configured.')
  await expect(panel.locator('.announcement-collection')).toHaveCount(0)
  expect(await page.evaluate(() => Reflect.get(window, 'commandCalls'))).toEqual([['save_announcements', []]])
})

test('invalid intervals and oversized UTF-8 messages remain local and show actionable errors', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  const panel = page.locator('#announcements')
  await panel.getByRole('button', { name: 'New announcement', exact: true }).click()
  await panel.getByLabel('Name', { exact: true }).fill('Reminder')
  await panel.getByLabel('Announcement message', { exact: true }).fill('é'.repeat(226))
  await panel.getByLabel('Interval (s)', { exact: true }).fill('59')
  await panel.getByRole('button', { name: 'Save announcements', exact: true }).click()
  await expect(panel.getByRole('alert')).toContainText('450 UTF-8 bytes')
  await expect(panel.getByLabel('Interval (s)', { exact: true })).toHaveAttribute('aria-invalid', 'true')
  expect(await page.evaluate(() => Reflect.get(window, 'commandCalls'))).toEqual([])
  await panel.getByLabel('Interval (s)', { exact: true }).fill('60')
  await panel.getByLabel('Name', { exact: true }).fill('é'.repeat(41))
  await panel.getByLabel('Announcement message', { exact: true }).fill('Single reminder.')
  await panel.getByRole('button', { name: 'Save announcements', exact: true }).click()
  await expect(panel.getByRole('alert')).toContainText('80 UTF-8 bytes')
  expect(await page.evaluate(() => Reflect.get(window, 'commandCalls'))).toEqual([])
  await panel.getByLabel('Name', { exact: true }).fill('Reminder')
  await panel.getByLabel('Announcement message', { exact: true }).fill('Single reminder.')
  await panel.getByRole('button', { name: 'Save announcements', exact: true }).click()
  await expect(panel.getByRole('status')).toContainText('Announcements saved')
})

test('status polling refreshes outcomes while retaining unsaved text', async ({ page }) => {
  await page.clock.install()
  await page.goto('/tests/commands.fixture.html?announcements')
  const panel = page.locator('#announcements')
  await panel.getByRole('button', { name: 'Edit announcement Community', exact: true }).click()
  await panel.getByLabel('Announcement message', { exact: true }).fill('Unsaved reminder.')
  await page.evaluate(() => Reflect.get(window, 'updateAnnouncementStatus')({ last_outcome: 'failed', eligible_messages: 7 }))
  await page.clock.fastForward(5100)
  await expect(panel).toContainText('Last outcome: Send failed')
  await panel.getByRole('button', { name: 'Help: Announcement status Community', exact: true }).click()
  await expect(page.getByRole('tooltip')).toContainText('Eligible messages: 7')
  await page.keyboard.press('Escape')
  await expect(panel.getByLabel('Announcement message', { exact: true })).toHaveValue('Unsaved reminder.')
  await expect(panel.getByText('Unsaved changes', { exact: true })).toBeVisible()
})

test('save failures retain drafts and remain visible after status refresh', async ({ page }) => {
  await page.clock.install()
  await page.goto('/tests/commands.fixture.html?announcements&announcementError')
  const panel = page.locator('#announcements')
  await panel.getByRole('button', { name: 'Edit announcement Community', exact: true }).click()
  await panel.getByLabel('Announcement message', { exact: true }).fill('Retry this reminder.')
  await panel.getByRole('button', { name: 'Save announcements', exact: true }).click()
  await expect(panel.getByRole('alert')).toHaveText('Synthetic announcement save failure.')
  await page.clock.fastForward(5100)
  await expect(panel.getByRole('alert')).toHaveText('Synthetic announcement save failure.')
  await expect(panel.getByLabel('Announcement message', { exact: true })).toHaveValue('Retry this reminder.')
})

for (const width of [1600, 1280, 900, 390, 320]) {
  test(`announcement controls, help and menus stay within the page at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/tests/commands.fixture.html?announcements&shell')
    await page.getByRole('button', { name: 'Commands', exact: true }).click()
    const panel = page.locator('#announcements')
    await panel.getByRole('button', { name: 'Edit announcement Community', exact: true }).click()
    await expect(panel.getByRole('button', { name: 'New announcement', exact: true })).toHaveClass('primary')
    await panel.getByLabel('Name', { exact: true }).fill('Very long announcement name '.repeat(3))
    await panel.getByRole('button', { name: 'Help: Announcement activity', exact: true }).click()
    await expect(page.getByRole('tooltip')).toContainText('fresh activity window')
    await expect(page.getByRole('tooltip')).toContainText('not an immediate message-count trigger')
    await page.keyboard.press('Escape')
    const availability = panel.getByLabel('Works when:', { exact: true })
    await availability.focus()
    await page.keyboard.press('ArrowDown')
    await expect(page.getByRole('listbox')).toBeVisible()
    const menu = (await page.getByRole('listbox').boundingBox())!
    expect(menu.x).toBeGreaterThanOrEqual(0)
    expect(menu.x + menu.width).toBeLessThanOrEqual(width)
    await page.keyboard.press('Escape')
    const name = (await panel.getByLabel('Name', { exact: true }).boundingBox())!
    const enabled = (await panel.getByLabel('Enable announcement', { exact: true }).locator('..').boundingBox())!
    const interval = (await panel.getByLabel('Interval (s)', { exact: true }).boundingBox())!
    const trigger = (await panel.getByLabel('Trigger after', { exact: true }).boundingBox())!
    const message = (await panel.getByLabel('Announcement message', { exact: true }).boundingBox())!
    const worksWhen = (await availability.boundingBox())!
    expect(enabled.x).toBeGreaterThanOrEqual(name.x + name.width)
    if (width >= 1280) {
      expect(message.x).toBeGreaterThan(trigger.x + trigger.width)
      expect(Math.abs(message.y - name.y)).toBeLessThan(12)
      expect(Math.abs(message.y + message.height - worksWhen.y - worksWhen.height)).toBeLessThan(3)
      expect(Math.abs(trigger.y - interval.y)).toBeLessThan(3)
    } else {
      expect(message.y).toBeGreaterThan(worksWhen.y + worksWhen.height)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await panel.screenshot({ path: `node_modules/.tmp/announcements-layout-${width}.png` })
  })
}
