import { expect, test } from '@playwright/test'

test('connected Desktop can explicitly renew Twitch announcement permission', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured')
  await page.evaluate(() => Reflect.get(window, 'setFixtureStatus')({ running: true, twitch_connected: true, twitch_connection_state: 'connected' }))
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  const twitch = page.locator('#twitch-settings')
  await twitch.locator('.accordion-trigger').first().press('Enter')
  await expect(page.getByRole('button', { name: 'Renew Twitch authorization', exact: true })).toBeVisible()
  expect(await page.evaluate(() => Reflect.get(window, 'opened'))).toEqual([])
  await page.getByRole('button', { name: 'Renew Twitch authorization', exact: true }).click()
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'opened'))).toEqual(['twitch_authorization'])
})

for (const width of [1280, 390, 320]) {
  test(`desktop Settings grouping, always-visible secret draft and ordering at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/tests/fixture.html')
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    const twitch = page.locator('#twitch-settings')
    await twitch.locator('.accordion-trigger').first().press('Enter')
    await expect(twitch.getByRole('heading', { level: 3 })).toHaveText(['Bot account', 'Target channel', 'Save and authorize'])
    await expect(twitch.getByLabel('Saved channel', { exact: true })).toBeVisible()
    const connectionSummary = twitch.locator('.twitch-connection-summary')
    const statusGrid = connectionSummary.locator('.twitch-status-grid')
    await expect(statusGrid.locator(':scope > div')).toHaveCount(4)
    const setupGuide = connectionSummary.getByRole('button', { name: 'Setup guide', exact: true })
    await expect(setupGuide).toBeVisible()
    const summaryStructure = await setupGuide.evaluate((guide) => {
      const summary = guide.closest('.twitch-connection-summary')!
      const grid = summary.querySelector('.twitch-status-grid')!
      const directChild = (element: Element) => {
        let child = element
        while (child.parentElement && child.parentElement !== summary) child = child.parentElement
        return child
      }
      return { gridIsChild: grid.parentElement === summary, guideIsSeparateChild: directChild(guide) !== grid && directChild(guide).parentElement === summary }
    })
    expect(summaryStructure).toEqual({ gridIsChild: true, guideIsSeparateChild: true })
    const saveSection = twitch.locator('.twitch-save-section')
    await expect(saveSection.getByRole('heading')).toHaveText('Save and authorize')
    const saveActions = saveSection.locator('.settings-actions')
    const saveHeading = saveSection.getByRole('heading')
    const saveLater = saveActions.getByRole('button', { name: 'Save for later', exact: true })
    const applyOrRestart = saveActions.getByRole('button', { name: /^Save & (?:apply|restart|reconnect)$/ })
    await expect(saveLater).toBeVisible()
    await expect(applyOrRestart).toBeVisible()
    const headingBox = (await saveHeading.boundingBox())!
    const actionsBox = (await saveActions.boundingBox())!
    if (width > 760) {
      expect(Math.abs(headingBox.y + headingBox.height / 2 - actionsBox.y - actionsBox.height / 2)).toBeLessThanOrEqual(1)
      expect(actionsBox.x).toBeGreaterThan(headingBox.x + headingBox.width)
    } else {
      expect(actionsBox.y).toBeGreaterThanOrEqual(headingBox.y + headingBox.height)
      expect(Math.abs(actionsBox.x - headingBox.x)).toBeLessThanOrEqual(1)
    }
    const ids = ['desktop-settings', 'twitch-settings', 'configuration-transfer', 'profile-location-settings']
    expect(await page.evaluate((targets) => targets.every((id, index) => index === targets.length - 1 || Boolean(document.getElementById(id)!.compareDocumentPosition(document.getElementById(targets[index + 1])!) & Node.DOCUMENT_POSITION_FOLLOWING)), ids)).toBe(true)
    const app = page.locator('#twitch-application')
    await app.locator('.accordion-trigger').click()
    const clientId = app.getByLabel(/client ID/i)
    const secret = app.getByLabel('Twitch client secret', { exact: true })
    await expect(secret).toHaveAttribute('type', 'password')
    await expect(secret).toHaveValue('')
    await expect(app.locator('.accordion-badges .state-pill')).toHaveText('Secret missing')
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
    await expect(app.locator('.accordion-badges .state-pill')).toHaveText('Secret configured')
    await expect(app.getByRole('button', { name: 'Replace secret', exact: true })).toBeVisible()
    await expect(app.getByRole('button', { name: 'Save secret', exact: true })).toHaveCount(0)
    await expect(app.getByRole('button', { name: 'Cancel replacement', exact: true })).toHaveCount(0)
    await expect(app.getByRole('button', { name: 'Test saved secret', exact: true })).toBeVisible()
    await expect(app.locator('input[type=password]')).toHaveCount(1)
    const consoleLink = app.getByRole('button', { name: 'Open Twitch Developer Console', exact: true })
    const callback = app.locator('.settings-callback')
    const callbackCopy = callback.getByRole('button', { name: 'Copy OAuth callback URL', exact: true })
    await expect(callback).toContainText('OAuth callback URL')
    await expect(callbackCopy).toBeVisible()
    await app.locator('.secret-actions-menu summary').click()
    const secretMenu = app.locator('.secret-actions-menu')
    const summaryBox = (await secretMenu.locator('summary').boundingBox())!
    const menuBox = (await secretMenu.boundingBox())!
    const removeBox = (await secretMenu.getByRole('button', { name: 'Remove secret', exact: true }).boundingBox())!
    const callbackBox = (await callback.boundingBox())!
    expect(menuBox.height).toBeGreaterThan(summaryBox.height)
    expect(removeBox.y).toBeGreaterThanOrEqual(summaryBox.y + summaryBox.height)
    const overlaps = (first: NonNullable<typeof menuBox>, second: NonNullable<typeof callbackBox>) =>
      first.x < second.x + second.width && first.x + first.width > second.x &&
      first.y < second.y + second.height && first.y + first.height > second.y
    expect(overlaps(menuBox, callbackBox)).toBe(false)
    await app.locator('.secret-actions-menu summary').click()
    if (width >= 760) {
      expect((await callback.boundingBox())!.x).toBeLessThan((await consoleLink.boundingBox())!.x)
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
  await twitch.locator('.accordion-trigger').first().press('Enter')
  await twitch.getByLabel('Target channel login').fill('draft-channel')
  page.once('dialog', async (dialog) => { expect(dialog.message()).toContain('Existing OAuth tokens are retained'); await dialog.accept() })
  const secretActions = twitch.locator('.secret-actions-menu')
  await twitch.locator('#twitch-application .accordion-trigger').press('Enter')
  await secretActions.locator('summary').click()
  await secretActions.getByRole('button', { name: 'Remove secret', exact: true }).click()
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'credentialCalls'))).toEqual([['remove', 'twitch_client_secret']])
  await expect(twitch.getByLabel('Target channel login')).toHaveValue('draft-channel')
  await expect(twitch.getByRole('button', { name: 'Restart now', exact: true })).toBeVisible()
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
  await twitch.locator('.accordion-trigger').first().press('Enter')
  await twitch.locator('#twitch-application .accordion-trigger').press('Enter')
  await expect(twitch.locator('.secret-actions-menu')).toHaveCount(0)
  await expect(twitch.getByRole('button', { name: 'Remove secret', exact: true })).toHaveCount(0)
  const secret = twitch.getByLabel('Twitch client secret', { exact: true })
  await expect(secret).toBeEnabled()
  await expect(twitch.getByRole('button', { name: 'Replace secret', exact: true })).toBeVisible()
  await expect(twitch.getByText('Secret changes save immediately.', { exact: false })).toHaveCount(0)
  await twitch.getByRole('button', { name: 'Help: Twitch client secret', exact: true }).focus()
  await expect(page.getByRole('tooltip')).toContainText('overrides the environment fallback')
  await page.keyboard.press('Escape')
  await secret.fill('synthetic-secure-override')
  await twitch.getByRole('button', { name: 'Replace secret', exact: true }).click()
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'credentialCalls'))).toEqual([['replace', 'twitch_client_secret']])
})
