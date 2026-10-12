import { expect, test, type Page } from '@playwright/test'

async function openTwitchSettings(page: Page) {
  const trigger = page.locator('#twitch-settings .accordion-trigger')
  if (await trigger.getAttribute('aria-expanded') !== 'true') await trigger.click()
}

for (const width of [1280, 900, 390, 320]) {
  test(`Settings accordions preserve Twitch and credential drafts at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/tests/fixture.html')
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    const twitch = page.locator('#twitch-settings')
    const credentials = page.locator('#credential-settings')
    for (const section of [twitch, credentials]) {
      const trigger = section.locator('.accordion-trigger')
      const content = section.locator('.accordion-content')
      await expect(trigger).toHaveAttribute('aria-expanded', 'false')
      await expect(trigger).toHaveAttribute('aria-controls', `${await section.getAttribute('id')}-content`)
      await expect(content).toBeHidden()
      await trigger.press('Enter')
      await expect(trigger).toHaveAttribute('aria-expanded', 'true')
      const field = section === twitch
        ? twitch.getByLabel('Target channel login')
        : credentials.getByLabel('New value', { exact: true })
      const draft = section === twitch ? 'unsaved_channel' : 'synthetic-credential-draft'
      await field.fill(draft)
      await trigger.press('Space')
      await expect(content).toBeHidden()
      await expect(trigger).toBeFocused()
      await trigger.press('Enter')
      await expect(field).toHaveValue(draft)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.screenshot({ path: `node_modules/.tmp/settings-accordion-${width}.png`, fullPage: true })
  })
}

test('clean setup provides the developer action and copies the backend callback', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', { value: {
      writeText: async (value: string) => { Object.assign(window, { copiedCallback: value }) },
    } })
  })
  await page.goto('/tests/fixture.html')
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await openTwitchSettings(page)
  const application = page.locator('.twitch-application-setup')
  await expect(application.getByLabel('Twitch application client ID')).toBeVisible()
  await application.getByRole('button', { name: 'Open Twitch Developer Console' }).click()
  expect(await page.evaluate(() => Reflect.get(window, 'opened'))).toEqual(['twitch_developer_console'])
  await expect(application.locator('code')).toHaveText('http://localhost:4343/oauth/callback')
  await application.getByRole('button', { name: 'Copy OAuth callback URL' }).click()
  expect(await page.evaluate(() => Reflect.get(window, 'copiedCallback'))).toBe('http://localhost:4343/oauth/callback')
  await expect(page.getByRole('status')).toHaveText(/OAuth callback URL copied/)
  await expect(page.getByRole('button', { name: 'Authorize Twitch', exact: true })).toHaveCount(0)
  await expect(page.getByText('Complete Twitch setup', { exact: true })).toBeVisible()
})

test('starting a configured bot exposes a manual authorization action on Dashboard', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured')
  await expect(page.getByRole('button', { name: 'Authorize Twitch', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Start Bot', exact: true }).click()
  const authorize = page.getByRole('button', { name: 'Authorize Twitch', exact: true })
  await expect(authorize).toBeEnabled()
  expect(await page.evaluate(() => Reflect.get(window, 'opened'))).toEqual([])
  await authorize.click()
  expect(await page.evaluate(() => Reflect.get(window, 'opened'))).toEqual(['twitch_authorization'])
})

for (const permitted of [true, false]) {
  test(`callback copy handles legacy clipboard ${permitted ? 'success' : 'failure'}`, async ({ page }) => {
    await page.addInitScript((canCopy) => {
      Object.defineProperty(navigator, 'clipboard', { value: undefined })
      document.execCommand = () => {
        Object.assign(window, { copiedCallback: document.querySelector('textarea')?.value })
        return canCopy
      }
    }, permitted)
    await page.goto('/tests/fixture.html?settings')
    await openTwitchSettings(page)
    const copy = page.getByRole('button', { name: 'Copy OAuth callback URL' })
    await copy.click()
    expect(await page.evaluate(() => Reflect.get(window, 'copiedCallback'))).toBe('http://localhost:4343/oauth/callback')
    await expect(page.locator('textarea')).toHaveCount(0)
    await expect(copy).toBeFocused()
    await expect(page.getByRole(permitted ? 'status' : 'alert')).toHaveText(
      permitted ? /OAuth callback URL copied/ : /Clipboard access is unavailable/,
    )
  })
}

test('auto-start authorization stays manual, including with a stale token cache', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured&auth&cachedToken')
  await expect(page.getByRole('button', { name: 'Authorize Twitch', exact: true })).toBeEnabled()
  expect(await page.evaluate(() => Reflect.get(window, 'opened'))).toEqual([])
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await openTwitchSettings(page)
  await expect(page.locator('.twitch-status-grid > div').filter({ hasText: 'Twitch authorization' })).toHaveText('Twitch authorizationRequired')
  await page.getByRole('button', { name: 'Authorize Twitch', exact: true }).click()
  expect(await page.evaluate(() => Reflect.get(window, 'opened'))).toEqual(['twitch_authorization'])
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  await page.getByRole('button', { name: 'Stop Bot', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Authorize Twitch', exact: true })).toBeDisabled()
})

test('browser opening failures retain accessible error feedback', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured&auth&openError')
  await page.getByRole('button', { name: 'Authorize Twitch', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText(/Could not open the external link/)
})

for (const width of [1280, 900, 761, 760, 390, 320]) {
  test(`Twitch field pairs align responsively at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/tests/fixture.html?settings')
    await openTwitchSettings(page)
    for (const [firstLabel, secondLabel] of [
      ['Saved channel', 'Saved channel name'],
      ['Bot account login', 'Bot account user ID'],
      ['Target channel login', 'Target channel user ID'],
    ]) {
      const first = page.getByRole(firstLabel === 'Saved channel' ? 'combobox' : 'textbox', { name: firstLabel === 'Saved channel' ? /^Saved channel/ : firstLabel })
      const second = page.getByRole('textbox', { name: secondLabel })
      await expect(second).toBeVisible()
      const firstBounds = (await first.boundingBox())!
      const secondBounds = (await second.boundingBox())!
      if (width > 760) {
        expect(Math.abs(firstBounds.y - secondBounds.y)).toBeLessThanOrEqual(1)
        expect(secondBounds.x).toBeGreaterThan(firstBounds.x + firstBounds.width)
      } else {
        expect(secondBounds.y).toBeGreaterThan(firstBounds.y + firstBounds.height)
        expect(secondBounds.x).toBe(firstBounds.x)
      }
      for (const field of [first, second]) {
        // Helper text must not stretch the input's grid row.
        expect((await field.boundingBox())!.height).toBeLessThan(50)
      }
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}

for (const width of [1280, 390]) {
  test(`Dashboard separates session, authorization, connection loss and AI at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/tests/fixture.html?configured&cachedToken&aiAvailable')
    const connection = page.locator('.dashboard-card').filter({ has: page.locator('.label', { hasText: 'TWITCH CONNECTION' }) })
    const hero = page.locator('.dashboard-hero')
    await expect(hero).toContainText('BOT SESSION')
    await expect(hero.getByRole('heading')).toHaveText('Stopped')
    await expect(connection).toContainText('Authorization: Not verified (token cache found)')
    await expect(connection).toContainText('Next step: Select Start Bot')
    await expect(page.locator('.dashboard-ai-card')).toContainText('AI availability: Configured for requests')
    await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).not.toBeChecked()
    await expect(page.locator('.dashboard-ai-card')).toContainText('Filter Tester works while stopped')

    await page.getByRole('button', { name: 'Start Bot', exact: true }).click()
    await expect(hero.getByRole('heading')).toHaveText('Running')
    await expect(connection.getByRole('heading')).toHaveText('Authorization required')
    await expect(connection).toContainText('Authorization: Required')
    // An existing token-cache file cannot suppress the required setup action.
    await expect(page.locator('.setup-list')).toContainText('Authorize Twitch')
    await expect(connection.getByRole('button', { name: 'Authorize Twitch', exact: true })).toBeEnabled()

    for (const [state, label, authorization, action] of [
      ['connecting', 'Connecting', 'Not verified (token cache found)', 'Wait for Twitch'],
      ['connected', 'Connected', 'Verified for this connection', 'No connection action is required'],
      ['reconnecting', 'Reconnecting', 'Not verified (token cache found)', 'Connection lost'],
      ['connected', 'Connected', 'Verified for this connection', 'No connection action is required'],
      ['failed', 'Connection failed', 'Not verified (token cache found)', 'Check Logs'],
      ['stopped', 'Stopped', 'Not verified (token cache found)', 'Select Start Bot'],
    ]) {
      await page.evaluate((next) => Reflect.get(window, 'setFixtureStatus')({
        running: !['failed', 'stopped'].includes(next), twitch_connected: next === 'connected', twitch_connection_state: next,
      }), state)
      await expect(connection.getByRole('heading')).toHaveText(label)
      await expect(connection).toContainText(`Authorization: ${authorization}`)
      await expect(connection).toContainText(action)
      await expect(hero.getByRole('heading')).toHaveText(['failed', 'stopped'].includes(state) ? 'Stopped' : 'Running')
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    }
    await page.screenshot({ path: `node_modules/.tmp/a3-dashboard-${width}.png`, fullPage: true })
  })

  test(`Settings groups secure values and explains effects before saves at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/tests/fixture.html?configured')
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await openTwitchSettings(page)
    const twitchSection = page.locator('#twitch-settings')
    const geminiSection = page.locator('#credential-settings')
    await geminiSection.locator('.accordion-trigger').click()
    await expect(twitchSection).toContainText('Twitch client secret')
    await expect(geminiSection).not.toContainText('Twitch client secret')
    await expect(twitchSection).toContainText('Client ID, bot identity or Client Secret changes require an application restart')
    await expect(twitchSection).toContainText('Saved channels share the bot account and Twitch authorization')
    await expect(twitchSection.getByRole('button', { name: 'Replace secret', exact: true })).toBeVisible()
    await expect(geminiSection.getByRole('button', { name: 'Add key', exact: true })).toBeDisabled()
    await geminiSection.getByLabel('New value', { exact: true }).fill('synthetic-key')
    await geminiSection.getByRole('button', { name: 'Add key', exact: true }).click()
    await expect(geminiSection.getByLabel('Replacement value', { exact: true })).toHaveValue('')
    await expect(geminiSection.getByRole('button', { name: 'Replace key', exact: true })).toBeDisabled()
    await expect(page.getByRole('status')).toContainText('applied to AI features')
    await expect(twitchSection.getByRole('button', { name: 'Save & apply', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
    await expect(page.locator('.dashboard-ai-card')).toContainText('AI availability: Configured for requests')
    await expect(page.locator('.setup-list')).not.toContainText('Add a Gemini API key')
    await expect(page.getByRole('button', { name: 'Start Bot', exact: true })).toBeEnabled()
    expect(await page.evaluate(() => Reflect.get(window, 'credentialCalls'))).toEqual([['replace', 'gemini_api_key']])
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}

test('secret changes retain Twitch drafts and require restart across Settings and Dashboard', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured&auth')
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await openTwitchSettings(page)
  const twitchSection = page.locator('#twitch-settings')
  await twitchSection.getByLabel('Target channel login').fill('unsaved_channel')
  await twitchSection.getByLabel('Replacement value', { exact: true }).fill('synthetic-secret')
  await twitchSection.getByRole('button', { name: 'Replace secret', exact: true }).click()
  await expect(twitchSection.getByLabel('Target channel login')).toHaveValue('unsaved_channel')
  await expect(twitchSection.getByLabel('Replacement value', { exact: true })).toHaveValue('')
  await expect(twitchSection.getByRole('button', { name: 'Authorize Twitch', exact: true })).toBeDisabled()
  await expect(twitchSection.getByRole('button', { name: 'Save (restart required)', exact: true })).toBeVisible()
  await twitchSection.getByLabel('Saved channel name', { exact: true }).fill('After restart')
  await twitchSection.getByRole('button', { name: 'Save channel', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Restart the application to apply pending Twitch setup')
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  await expect(page.locator('.setup-list')).toContainText('Restart to apply Twitch setup')
  await expect(page.locator('.dashboard-card').first()).toContainText('Next step: Restart the application')
  await expect(page.getByRole('button', { name: 'Stop Bot', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Authorize Twitch', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Stop Bot', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Start Bot', exact: true })).toBeDisabled()
})

test('failed key storage keeps the entered draft and missing state', async ({ page }) => {
  await page.goto('/tests/fixture.html?credentialSaveError')
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  const geminiSection = page.locator('#credential-settings')
  await geminiSection.locator('.accordion-trigger').click()
  await geminiSection.getByLabel('New value', { exact: true }).fill('synthetic-key')
  await geminiSection.getByRole('button', { name: 'Add key', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Could not store the credential securely')
  await expect(geminiSection.getByLabel('New value', { exact: true })).toHaveValue('synthetic-key')
  await expect(geminiSection.locator('.state-pill')).toHaveText('Missing')
})

for (const running of [false, true]) {
  test(`saved channels preserve shared identity and ${running ? 'reconnect' : 'apply without starting'} only when requested`, async ({ page }) => {
    await page.goto(`/tests/fixture.html?configured${running ? '&connection=connected&cachedToken' : ''}`)
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await openTwitchSettings(page)
    const twitchSection = page.locator('#twitch-settings')
    await twitchSection.getByLabel('Target channel login').fill('otherchannel')
    await twitchSection.getByLabel('Target channel user ID').fill('300')
    await twitchSection.getByLabel('Saved channel name', { exact: true }).fill('Other channel')
    await twitchSection.getByRole('button', { name: 'Save channel', exact: true }).click()
    await expect(page.getByRole('status')).toContainText(running ? 'Save & reconnect' : 'Save & apply')
    await expect(twitchSection.getByRole('combobox', { name: /^Saved channel/ })).toHaveValue('synthetic-1')
    await expect(twitchSection.getByLabel('Bot account login')).toHaveValue('testbot')
    await expect(twitchSection.getByLabel('Twitch application client ID')).toHaveValue('synthetic-client')
    await expect(twitchSection.locator('.twitch-status-grid > div').filter({ hasText: 'Active target' })).toContainText('testchannel')
    expect(await page.evaluate(() => Reflect.get(window, 'twitchCalls'))).toEqual([['save_channel', 'synthetic-1']])
    await twitchSection.getByRole('button', { name: running ? 'Save & reconnect' : 'Save & apply', exact: true }).click()
    await expect(twitchSection.locator('.twitch-status-grid > div').filter({ hasText: 'Active target' })).toContainText('otherchannel')
    expect(await page.evaluate(() => Reflect.get(window, 'credentialCalls'))).toEqual([])
    expect(await page.evaluate(() => Reflect.get(window, 'twitchCalls')).then((calls) => calls.at(-1))).toEqual(['reconnect'])
    await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
    await expect(page.locator('.dashboard-hero').getByRole('heading')).toHaveText(running ? 'Running' : 'Stopped')
  })
}

test('identity changes explain restart before saving and do not reconnect', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured&connection=connected')
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await openTwitchSettings(page)
  const twitchSection = page.locator('#twitch-settings')
  await twitchSection.getByLabel('Twitch application client ID').fill('other-client')
  await twitchSection.getByRole('button', { name: 'Save & reconnect', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Restart the application')
  expect(await page.evaluate(() => Reflect.get(window, 'twitchCalls')).then((calls) => calls.map((call: string[]) => call[0]))).toEqual(['save'])
  await expect(twitchSection.getByRole('button', { name: 'Save (restart required)', exact: true })).toBeVisible()
})
