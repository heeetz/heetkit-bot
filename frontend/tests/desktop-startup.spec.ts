import { expect, test } from '@playwright/test'
import { navigate, openSection } from './browser-fixture'

test('Desktop waits for the bridge, renders Dashboard and writes through pywebview', async ({ page }) => {
  const httpRequests: string[] = []
  page.on('request', (request) => { if (new URL(request.url()).pathname.startsWith('/v1/')) httpRequests.push(request.url()) })
  await page.goto('/tests/fixture.html?lateBridge&startupDelay')
  await expect(page.getByRole('heading', { name: 'Starting HeetKit' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible()
  const ask = page.getByRole('checkbox', { name: 'Enable AI command', exact: true })
  await expect(ask).not.toBeChecked()
  await ask.press('Space')
  await expect(ask).toBeChecked()
  expect(await page.evaluate(() => Reflect.get(window, 'bridgeCalls'))).toEqual([['set_ai_enabled', true]])
  expect(httpRequests).toEqual([])
})

test('Desktop startup failure exposes an alert and blocks the application', async ({ page }) => {
  await page.goto('/tests/fixture.html?startupFailure')
  await expect(page.getByRole('heading', { name: 'Startup needs attention' })).toBeVisible()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toHaveCount(0)
})

test('Desktop can replace the Twitch secret and relaunch', async ({ page }) => {
  await page.goto('/tests/fixture.html')
  await navigate(page, 'Settings')
  const connection = page.locator('#twitch-settings')
  await openSection(connection.getByRole('button', { name: 'Twitch connection', exact: true }))
  await openSection(connection.getByRole('button', { name: 'Twitch application', exact: true }))
  await connection.getByLabel('Twitch client secret', { exact: true }).fill('synthetic-replacement')
  await expect(connection.getByRole('button', { name: 'Replace secret', exact: true })).toBeEnabled()
  await connection.getByRole('button', { name: 'Replace secret & restart', exact: true }).click()
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'bridgeCalls'))).toEqual([
    ['replace_credential', 'twitch_client_secret', 'synthetic-replacement'], ['restart_desktop'],
  ])
})

test('Desktop opens the profile folder and copies the path from the bridge', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', { value: {
      writeText: async (value: string) => { Reflect.set(window, 'copiedPath', value) },
    } })
  })
  await page.goto('/tests/fixture.html')
  await navigate(page, 'Settings')
  const profile = page.getByRole('region', { name: 'Data & diagnostics' })
  await expect(profile.getByText('C:/Synthetic/HeetKit', { exact: true })).toBeVisible()
  await profile.getByRole('button', { name: 'Open profile folder', exact: true }).click()
  await profile.getByRole('button', { name: 'Copy path', exact: true }).click()
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'bridgeCalls')))
    .toContainEqual(['open_profile_folder'])
  expect(await page.evaluate(() => Reflect.get(window, 'copiedPath'))).toBe('C:/Synthetic/HeetKit')
})
