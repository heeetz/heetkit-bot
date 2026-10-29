import { expect, test } from '@playwright/test'

for (const width of [1280, 390, 320]) {
  test(`legacy mapping requires explicit confirmation and fits at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/tests/fixture.html?legacyMapping&migrationDelay')
    await expect(page.getByRole('heading', { name: 'Choose a channel for existing history' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toHaveCount(0)
    const channel = page.getByRole('textbox', { name: 'Numeric Twitch channel ID' })
    const confirm = page.getByRole('button', { name: 'Confirm channel and continue' })
    const consent = page.getByRole('checkbox', { name: 'I confirm this channel for all unscoped history.' })
    await expect(channel).toHaveValue('200')
    await expect(consent).not.toBeChecked()
    await expect(confirm).toBeDisabled()
    await channel.press('Enter')
    expect(await page.evaluate(() => (window as unknown as { startupCalls: unknown[] }).startupCalls)).toEqual([])
    await channel.fill('nickname')
    await consent.check()
    await expect(confirm).toBeDisabled()
    await channel.fill('300')
    await expect(consent).not.toBeChecked()
    await consent.check()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.screenshot({ path: `node_modules/.tmp/desktop-startup-${width}.png`, fullPage: true })
    await confirm.click()
    await expect(page.getByRole('button', { name: 'Upgrading history…' })).toBeDisabled()
    await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible()
    expect(await page.evaluate(() => (window as unknown as { startupCalls: unknown[] }).startupCalls)).toEqual([['confirm', '300', true]])
  })
}

test('missing suggestion accepts manual ID; Cancel never saves a mapping', async ({ page }) => {
  await page.goto('/tests/fixture.html?legacyMapping&noSuggestedChannel')
  await expect(page.getByRole('textbox', { name: 'Numeric Twitch channel ID' })).toHaveValue('')
  await page.getByRole('button', { name: 'Cancel and exit' }).click()
  expect(await page.evaluate(() => (window as unknown as { startupCalls: unknown[] }).startupCalls)).toEqual([['cancel']])
})

test('failed migration leaves an actionable error and blocks the application', async ({ page }) => {
  await page.goto('/tests/fixture.html?legacyMapping&migrationFailure')
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Confirm channel and continue' }).click()
  await expect(page.getByRole('heading', { name: 'Startup needs attention' })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('Keep the database and recovery copies')
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Confirm channel and continue' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Exit HeetKit' }).click()
  expect(await page.evaluate(() => (window as unknown as { startupCalls: unknown[] }).startupCalls)).toEqual([['confirm', '200', true], ['cancel']])
})
