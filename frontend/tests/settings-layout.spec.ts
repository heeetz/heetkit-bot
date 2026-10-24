import { expect, test } from '@playwright/test'

for (const width of [1280, 390, 320]) {
  test(`desktop Settings grouping, always-visible secret draft and ordering at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/tests/fixture.html')
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    const twitch = page.locator('#twitch-settings')
    await twitch.locator('.accordion-trigger').click()
    await expect(twitch.locator('.twitch-settings-group > h3')).toHaveText([/application/i, 'Saved channels', 'Bot account', 'Target channel', 'Authorization, status and save'])
    const ids = ['desktop-settings', 'twitch-settings', 'configuration-transfer', 'profile-location-settings']
    expect(await page.evaluate((targets) => targets.every((id, index) => index === targets.length - 1 || Boolean(document.getElementById(id)!.compareDocumentPosition(document.getElementById(targets[index + 1])!) & Node.DOCUMENT_POSITION_FOLLOWING)), ids)).toBe(true)
    const app = twitch.locator('[aria-labelledby="twitch-application-heading"]')
    const clientId = app.getByLabel(/client ID/i)
    const secret = app.getByLabel('Twitch client secret', { exact: true })
    await expect(secret).toHaveAttribute('type', 'password')
    await expect(secret).toHaveValue('')
    await expect(app.locator('.twitch-secret-label .state-pill')).toHaveText('Unconfigured')
    const clientBox = (await clientId.boundingBox())!
    const secretBox = (await secret.boundingBox())!
    if (width >= 760) expect(Math.abs(clientBox.y - secretBox.y)).toBeLessThanOrEqual(2)
    else expect(secretBox.y).toBeGreaterThan(clientBox.y)
    expect(clientBox.height).toBeCloseTo(secretBox.height, 0)
    const actions = app.locator('.credential-actions')
    const firstAction = (await actions.getByRole('button', { name: 'Add secret', exact: true }).boundingBox())!
    expect(firstAction.y).toBeGreaterThanOrEqual(secretBox.y + secretBox.height)
    await expect(app.getByRole('button', { name: 'Add secret', exact: true })).toBeDisabled()
    await secret.fill('synthetic-new-secret')
    await expect(app.getByRole('button', { name: 'Add secret', exact: true })).toBeEnabled()
    await app.getByRole('button', { name: 'Add secret', exact: true }).click()
    await expect(secret).toHaveValue('')
    await expect.poll(() => page.evaluate(() => Reflect.get(window, 'credentialCalls'))).toEqual([['replace', 'twitch_client_secret']])
    await expect(app.locator('.twitch-secret-label .state-pill')).toHaveText('Configured')
    await expect(app.getByRole('button', { name: 'Replace secret', exact: true })).toBeVisible()
    await expect(app.getByRole('button', { name: 'Save secret', exact: true })).toHaveCount(0)
    await expect(app.getByRole('button', { name: 'Cancel replacement', exact: true })).toHaveCount(0)
    await expect(app.locator('input[type=password]')).toHaveCount(1)
    const consoleLink = app.getByRole('button', { name: 'Open Twitch Developer Console', exact: true })
    const callback = app.locator('.settings-callback')
    const callbackCopy = callback.getByRole('button', { name: 'Copy OAuth callback URL', exact: true })
    await expect(callback).toContainText('OAuth callback URL')
    await expect(callbackCopy).toBeVisible()
    if (width >= 760) {
      expect((await consoleLink.boundingBox())!.x).toBeLessThan((await callback.boundingBox())!.x)
      expect((await callbackCopy.boundingBox())!.x).toBeGreaterThan((await callback.locator('code').boundingBox())!.x)
    }
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
  const secret = twitch.getByLabel('Twitch client secret', { exact: true })
  await expect(secret).toBeEnabled()
  await expect(twitch.getByRole('button', { name: 'Replace secret', exact: true })).toBeVisible()
  await twitch.getByRole('button', { name: 'Help: Twitch client secret', exact: true }).focus()
  await expect(page.getByRole('tooltip')).toContainText('overrides the environment fallback')
  await page.keyboard.press('Escape')
  await secret.fill('synthetic-secure-override')
  await twitch.getByRole('button', { name: 'Replace secret', exact: true }).click()
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'credentialCalls'))).toEqual([['replace', 'twitch_client_secret']])
})
