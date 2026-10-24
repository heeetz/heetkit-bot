import { expect, test } from '@playwright/test'

for (const width of [1280, 390, 320]) {
  test(`desktop Settings grouping, masked replacement and ordering at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/tests/fixture.html?configured')
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    const twitch = page.locator('#twitch-settings')
    await twitch.locator('.accordion-trigger').click()
    await expect(twitch.locator('.twitch-settings-group > h3')).toHaveText([/Application/, 'Saved channels', 'Bot account', 'Target channel', 'Authorization, status and save'])
    const ids = ['desktop-settings', 'twitch-settings', 'credential-settings', 'configuration-transfer', 'profile-location-settings']
    expect(await page.evaluate((targets) => targets.every((id, index) => index === targets.length - 1 || Boolean(document.getElementById(id)!.compareDocumentPosition(document.getElementById(targets[index + 1])!) & Node.DOCUMENT_POSITION_FOLLOWING)), ids)).toBe(true)
    const app = twitch.locator('[aria-labelledby="twitch-application-heading"]')
    await expect(app.locator('input[type=password]')).toHaveCount(0)
    await app.getByRole('button', { name: 'Replace secret', exact: true }).click()
    const secret = app.getByLabel('Replacement value', { exact: true })
    await expect(secret).toHaveAttribute('type', 'password')
    await secret.fill('synthetic-new-secret')
    await app.getByRole('button', { name: 'Cancel replacement' }).click()
    expect(await page.evaluate(() => Reflect.get(window, 'credentialCalls'))).toEqual([])
    await expect(app.locator('input[type=password]')).toHaveCount(0)
    await app.scrollIntoViewIfNeeded()
    await page.screenshot({ path: `node_modules/.tmp/task6-settings-${width}.png` })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}

test('removing the desktop secret uses the secure operation and preserves target drafts', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured')
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  const twitch = page.locator('#twitch-settings')
  await twitch.locator('.accordion-trigger').click()
  await twitch.getByLabel('Target channel login').fill('draft-channel')
  page.once('dialog', async (dialog) => { expect(dialog.message()).toContain('Existing OAuth tokens are retained'); await dialog.accept() })
  await twitch.getByRole('button', { name: 'Remove secret', exact: true }).click()
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'credentialCalls'))).toEqual([['remove', 'twitch_client_secret']])
  await expect(twitch.getByLabel('Target channel login')).toHaveValue('draft-channel')
  await expect(twitch).toContainText('Restart the application')
})

for (const width of [1920, 1280, 390, 320]) {
  test(`Logs search retains a usable width at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/tests/fixture.html?configured')
    await page.getByRole('button', { name: 'Logs', exact: true }).click()
    const search = page.getByPlaceholder('Message or source')
    const bounds = (await search.boundingBox())!
    expect(bounds.width).toBeGreaterThanOrEqual(width >= 1280 ? 250 : 210)
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}


test('desktop environment fallback still permits a secure override', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured')
  await page.evaluate(() => {
    const getCredentials = window.pywebview!.api.get_credentials
    window.pywebview!.api.get_credentials = async () => {
      const response = await getCredentials()
      return { ...response, credentials: response.credentials!.map((credential) => credential.name === 'twitch_client_secret' ? { ...credential, source: 'environment' as const } : credential) }
    }
  })
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  const twitch = page.locator('#twitch-settings')
  await twitch.locator('.accordion-trigger').click()
  await expect(twitch.getByRole('button', { name: 'Remove secret', exact: true })).toBeDisabled()
  await twitch.getByRole('button', { name: 'Replace secret', exact: true }).click()
  await expect(twitch.getByLabel('Replacement value', { exact: true })).toBeEnabled()
  await expect(twitch).toContainText('overrides the environment fallback')
})
