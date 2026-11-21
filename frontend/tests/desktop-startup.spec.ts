import { expect, test } from '@playwright/test'

test('shows progress until the Desktop bridge is ready', async ({ page }) => {
  await page.goto('/tests/fixture.html?startupDelay')
  await expect(page.getByRole('heading', { name: 'Starting HeetKit' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible()
})

test('bridge startup failure leaves an actionable message and blocks the application', async ({ page }) => {
  await page.goto('/tests/fixture.html?startupFailure')
  await expect(page.getByRole('heading', { name: 'Startup needs attention' })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('Close HeetKit and review the startup error')
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toHaveCount(0)
})
