import { expect, test, type Page } from '@playwright/test'

async function openTwitchSettings(page: Page) {
  const trigger = page.locator('#twitch-settings .accordion-trigger')
  // The independent Help button can cover the header's center; click its expand caret.
  if (await trigger.getAttribute('aria-expanded') !== 'true') await trigger.locator('.accordion-caret').click()
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
    const connection = page.locator('.dashboard-card').first()
    const hero = page.locator('.dashboard-hero')
    await expect(hero).toContainText('Bot session')
    await expect(hero.getByRole('heading')).toHaveText('Stopped')
    await expect(connection).toContainText('Start Bot to connect')
    await connection.getByRole('button', { name: 'Help: Twitch connection', exact: true }).focus()
    await expect(page.getByRole('tooltip')).toContainText('Authorization: Not verified (token cache found)')
    await page.keyboard.press('Escape')
    await expect(page.locator('.dashboard-ai-card')).toContainText('synthetic-model')
    await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).not.toBeChecked()
    await page.getByRole('button', { name: 'Help: AI controls', exact: true }).focus()
    await expect(page.getByRole('tooltip')).toContainText('Filter Tester works while stopped')
    await page.keyboard.press('Escape')

    await page.getByRole('button', { name: 'Start Bot', exact: true }).click()
    await expect(hero.getByRole('heading')).toHaveText('Running')
    await expect(connection.getByRole('heading')).toHaveText('Authorization required')
    // An existing token-cache file cannot suppress the required setup action.
    await expect(page.locator('.setup-card')).toHaveCount(0)
    await expect(connection.getByRole('button', { name: 'Authorize Twitch', exact: true })).toBeEnabled()

    for (const [state, label, action] of [
      ['connecting', 'Connecting', 'Waiting for Twitch'],
      ['connected', 'Connected', ''],
      ['reconnecting', 'Reconnecting', 'Connection lost'],
      ['connected', 'Connected', ''],
      ['failed', 'Connection failed', 'Check Logs'],
      ['stopped', 'Stopped', 'Start Bot to connect'],
    ]) {
      await page.evaluate((next) => Reflect.get(window, 'setFixtureStatus')({
        running: !['failed', 'stopped'].includes(next), twitch_connected: next === 'connected', twitch_connection_state: next,
      }), state)
      await expect(connection.getByRole('heading')).toHaveText(label)
      if (action) await expect(connection).toContainText(action)
      else {
        await expect(connection.locator('p')).toHaveCount(0)
        await expect(connection).not.toContainText('Authorization:')
      }
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
    await geminiSection.locator('.accordion-trigger').press('Enter')
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
    await expect(page.locator('.dashboard-ai-card')).toContainText('Model not selected')
    await expect(page.locator('.setup-card')).toHaveCount(0)
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
  await expect(page.locator('.setup-card')).toContainText('Restart to apply Twitch setup')
  await expect(page.locator('.dashboard-card').first()).not.toContainText('Restart the application')
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

for (const connection of ['stopped', 'connected']) {
  test(`configured Dashboard ${connection} fits the default window with three small panels`, async ({ page }) => {
    await page.setViewportSize({ width: 1180, height: 760 })
    await page.goto(`/tests/fixture.html?configured&cachedToken&aiAvailable&connection=${connection}`)
    await expect(page.locator('.dashboard-card').first().getByRole('heading')).toHaveText(connection === 'connected' ? 'Connected' : 'Stopped')
    const cards = await page.locator('.dashboard-grid > .dashboard-card').all()
    expect(cards).toHaveLength(3)
    const boxes = await Promise.all(cards.map((card) => card.boundingBox()))
    for (const box of boxes) {
      expect(box!.y).toBe(boxes[0]!.y)
      expect(box!.height).toBeGreaterThanOrEqual(72)
      expect(box!.height).toBeLessThanOrEqual(96)
    }
    const main = page.locator('main')
    expect(await main.evaluate((element) => element.scrollHeight <= element.clientHeight)).toBe(true)
    await expect(page.locator('.dashboard-ai-card')).toBeInViewport({ ratio: 1 })
    await expect(page.locator('.setup-card')).toHaveCount(0)
    await page.screenshot({ path: `node_modules/.tmp/dashboard-default-${connection}.png` })
  })
}

for (const width of [900, 390, 320]) {
  test(`Dashboard wraps long status text and keeps actions inside panels at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 760 })
    await page.goto('/tests/fixture.html?configured&auth&aiAvailable')
    await page.evaluate(() => Reflect.get(window, 'setFixtureStatus')({ channel: 'a_very_long_channel_name_that_must_wrap_without_clipping', account: 'another_long_bot_account_name_for_layout' }))
    await expect(page.locator('.dashboard-card').nth(1)).toContainText('a_very_long_channel')
    for (const card of await page.locator('.dashboard-layout .card').all()) {
      const box = (await card.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(width)
      expect(await card.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
      for (const button of await card.getByRole('button').all()) {
        const action = (await button.boundingBox())!
        expect(action.x).toBeGreaterThanOrEqual(box.x)
        expect(action.x + action.width).toBeLessThanOrEqual(box.x + box.width)
      }
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.screenshot({ path: `node_modules/.tmp/dashboard-narrow-${width}.png`, fullPage: true })
  })
}

test('fresh Dashboard shows one required setup step and no optional Gemini setup list', async ({ page }) => {
  await page.goto('/tests/fixture.html')
  const notice = page.locator('.dashboard-notice')
  await expect(notice.getByRole('heading')).toHaveText('Finish Twitch setup')
  await expect(notice.getByRole('button')).toHaveText('Configure Twitch')
  await expect(page.locator('.setup-card')).toHaveCount(1)
  await expect(page.locator('.dashboard-card').first().getByRole('heading')).toHaveText('Not configured')
  await expect(page.getByRole('button', { name: 'Start Bot', exact: true })).toBeDisabled()
  await expect(page.locator('.dashboard-layout')).not.toContainText('Add a Gemini')
  await notice.getByRole('button').click()
  await expect(page.locator('#twitch-settings .accordion-trigger')).toHaveAttribute('aria-expanded', 'true')
  await expect(page.locator('#twitch-settings')).toBeInViewport()
})

test('commands-only Dashboard stays quiet about optional Gemini and links to AI controls', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured&cachedToken&connection=connected')
  await expect(page.locator('.dashboard-card').first().getByRole('heading')).toHaveText('Connected')
  await expect(page.locator('.setup-card')).toHaveCount(0)
  await expect(page.locator('.dashboard-layout')).not.toContainText('Gemini')
  await expect(page.locator('.dashboard-ai-card')).toContainText('AI unavailable')
  await page.getByRole('button', { name: 'Manage AI', exact: true }).click()
  await expect(page.locator('#ai-runtime')).toBeInViewport()
})

for (const running of [false, true]) {
  test(`pending channel change remains distinct while ${running ? 'connected' : 'stopped'}`, async ({ page }) => {
    await page.goto(`/tests/fixture.html?configured&reconnectRequired&connection=${running ? 'connected' : 'stopped'}`)
    const notice = page.locator('.dashboard-notice')
    await expect(notice.getByRole('heading')).toHaveText('Channel change pending')
    await expect(notice).toContainText(running ? 'Save & reconnect' : 'Save & apply')
    await expect(page.locator('.dashboard-card').first().getByRole('heading')).toHaveText(running ? 'Connected' : 'Stopped')
    await expect(page.getByRole('button', { name: running ? 'Stop Bot' : 'Start Bot', exact: true })).toBeEnabled()
  })
}

test('Dashboard exposes connection failure recovery and setup loading errors', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured&connection=failed')
  const connection = page.locator('.dashboard-card').first()
  await expect(connection).toContainText('Check Logs, then Start Bot again')
  await connection.getByRole('button', { name: 'Open Logs', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Logs', exact: true, level: 1 })).toBeVisible()
  await page.goto('/tests/fixture.html?configured&setupError')
  await expect(page.locator('.dashboard-notice')).toContainText('Synthetic Twitch setup load failure')
  await page.locator('.dashboard-notice').getByRole('button').click()
  await expect(page.locator('#twitch-settings .accordion-trigger')).toHaveAttribute('aria-expanded', 'true')
})

test('Dashboard loading keeps session actions and AI controls disabled', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured&statusDelay')
  await expect(page.locator('.dashboard-hero').getByRole('heading')).toHaveText('Loading…')
  await expect(page.getByRole('button', { name: 'Start Bot', exact: true })).toBeDisabled()
  await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).toBeDisabled()
  await expect(page.locator('.dashboard-hero').getByRole('heading')).toHaveText('Stopped')
  await expect(page.getByRole('button', { name: 'Start Bot', exact: true })).toBeEnabled()
})

for (const fails of [false, true]) {
  test(`Dashboard memory switch ${fails ? 'retains its saved state on failure' : 'saves while stopped'}`, async ({ page }) => {
    await page.goto(`/tests/fixture.html?configured${fails ? '&memorySaveError' : ''}`)
    const memory = page.getByRole('checkbox', { name: 'Enable conversation memory', exact: true })
    await expect(memory).not.toBeChecked()
    await memory.press('Space')
    if (fails) {
      await expect(page.getByRole('alert')).toContainText('Could not save conversation memory setting')
      await expect(memory).not.toBeChecked()
    } else await expect(memory).toBeChecked()
    expect(await page.evaluate(() => Reflect.get(window, 'aiCalls'))).toEqual([['set_ai_memory_enabled', true]])
  })
}
