import { expect, test, type Page } from '@playwright/test'

for (const width of [1280, 900, 390, 320]) {
  test(`incomplete setup guide has clear status and aligned actions at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/tests/fixture.html?configured')
    const checklist = page.getByRole('article', { name: 'Setup checklist' })
    await expect(checklist.locator('.section-heading p')).toHaveText('Twitch needs authorization · AI optional')
    await expect(checklist).not.toContainText(/unverified|not confirmed/)
    await expect(checklist.getByRole('button', { name: 'Skip AI for now' })).toBeVisible()
    const skip = (await checklist.getByRole('button', { name: 'Skip AI for now' }).boundingBox())!
    const open = (await checklist.getByRole('button', { name: 'Open AI setup' }).boundingBox())!
    expect(Math.abs(skip.y - open.y) <= 1 ? skip.x < open.x : skip.y < open.y).toBe(true)
    const steps = checklist.locator('.setup-guide-step')
    const bounds = (await checklist.boundingBox())!
    const actions = []
    for (const step of await steps.all()) {
      const text = (await step.locator('p').boundingBox())!
      const action = (await step.locator('.row-actions').boundingBox())!
      expect(action.x).toBeGreaterThanOrEqual(bounds.x)
      expect(action.x + action.width).toBeLessThanOrEqual(bounds.x + bounds.width)
      if (width <= 900) {
        expect(action.y).toBeGreaterThanOrEqual(text.y + text.height)
        expect(action.x).toBe(text.x)
      } else {
        expect(Math.abs(action.y + action.height / 2 - text.y - text.height / 2)).toBeLessThanOrEqual(1)
      }
      actions.push(action)
    }
    if (width > 900) expect(actions[0].x + actions[0].width).toBe(actions[1].x + actions[1].width)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.screenshot({ path: `node_modules/.tmp/setup-guide-${width}.png`, fullPage: true })
    await checklist.getByRole('button', { name: 'Dismiss setup guide' }).click()
    await page.reload()
    await expect(checklist.getByRole('heading')).toHaveText('Setup summary')
  })
}

for (const width of [1280, 900, 390, 320]) {
  for (const provider of ['aiAvailable', 'multipleProviders']) {
    test(`configured Dashboard hides the setup summary with ${provider === 'aiAvailable' ? 'Gemini' : 'only unselected DeepSeek'} at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 })
      await page.goto(`/tests/fixture.html?configured&authorized&${provider}`)
      await expect(page.getByRole('article', { name: 'Bot session' })).toContainText('Start Bot to connect.')
      await expect(page.locator('.dashboard-hero')).toContainText('Stopped')
      await expect(page.getByRole('article', { name: 'Setup checklist' })).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Resume setup guide' })).toHaveCount(0)
      if (provider === 'multipleProviders') await expect(page.locator('.dashboard-ai-card')).toContainText('AI unavailable')
      await page.reload()
      await expect(page.getByRole('article', { name: 'Bot session' })).toContainText('Start Bot to connect.')
      await expect(page.getByRole('article', { name: 'Setup checklist' })).toHaveCount(0)
    })
  }
}

test('skip removes the optional step, survives returning and reloading, and hides the guide on completion', async ({ page }) => {
  await page.goto('/tests/fixture.html?aiAvailable')
  const checklist = page.getByRole('article', { name: 'Setup checklist' })
  await expect(checklist).toContainText('Twitch needs configuration · AI configured')
  await page.goto('/tests/fixture.html?configured&cachedToken')
  await expect(checklist.getByRole('button', { name: 'Skip AI for now' })).toBeVisible()
  await checklist.getByRole('button', { name: 'Skip AI for now' }).click()
  await expect(checklist.locator('.section-heading p')).toHaveText('Twitch needs authorization')
  await expect(checklist.getByRole('button', { name: 'Open AI setup' })).toHaveCount(0)
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'AI', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  await expect(checklist.locator('.section-heading p')).toHaveText('Twitch needs authorization')
  await page.reload()
  await expect(checklist.locator('.section-heading p')).toHaveText('Twitch needs authorization')
  for (const pending of ['restartRequired', 'reconnectRequired']) {
    await page.goto(`/tests/fixture.html?configured&authorized&${pending}`)
    await expect(checklist.locator('.section-heading p')).toHaveText('Twitch changes pending')
  }
  for (const state of ['stopped', 'reconnecting', 'failed']) {
    await page.goto(`/tests/fixture.html?configured&authorized&connection=${state}`)
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
    await expect(checklist).toHaveCount(0)
  }
})

test('failed Skip AI save keeps the guidance and permits retry', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured')
  await page.evaluate(() => {
    const api = window.pywebview!.api
    const save = api.save_setup_guide
    api.save_setup_guide = async (...args) => {
      api.save_setup_guide = save
      return { ok: false, error: 'Profile is read-only.' }
    }
  })
  const checklist = page.getByRole('article', { name: 'Setup checklist' })
  const skip = checklist.getByRole('button', { name: 'Skip AI for now' })
  await skip.click()
  await expect(checklist.getByRole('alert')).toHaveText('Profile is read-only. Select Skip AI for now to retry.')
  await expect(skip).toBeEnabled()
  await skip.click()
  await expect(skip).toHaveCount(0)
  await expect(checklist.getByRole('alert')).toHaveCount(0)
})

test('setup summary follows saved provider keys when returning to Dashboard', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured&authorized&multipleProviders')
  const checklist = page.getByRole('article', { name: 'Setup checklist' })
  await expect(page.getByRole('article', { name: 'Bot session' })).toContainText('Start Bot to connect.')
  await expect(checklist).toHaveCount(0)
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await page.evaluate(() => window.pywebview!.api.remove_credential('deepseek_api_key'))
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  await expect(checklist).toHaveCount(0)
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await page.evaluate(() => window.pywebview!.api.remove_credential('openai_api_key'))
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  await expect(checklist).toContainText('AI optional')
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await page.evaluate(() => window.pywebview!.api.replace_credential('gemini_api_key', 'synthetic-key'))
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  await expect(page.getByRole('article', { name: 'Bot session' })).toContainText('Start Bot to connect.')
  await expect(checklist).toHaveCount(0)
})

async function openTwitchSettings(page: Page) {
  const trigger = page.locator('#twitch-settings > .accordion-header > .accordion-trigger')
  // The independent Help button can cover the header's center; click its expand caret.
  if (await trigger.getAttribute('aria-expanded') !== 'true') await trigger.locator('.accordion-caret').click()
  const application = page.locator('#twitch-application > .accordion-header > .accordion-trigger')
  if (await application.getAttribute('aria-expanded') !== 'true') await application.click()
}

for (const width of [1280, 900, 390, 320]) {
  test(`Settings accordion preserves Twitch drafts at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/tests/fixture.html')
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    const twitch = page.locator('#twitch-settings')
    const trigger = twitch.locator(':scope > .accordion-header > .accordion-trigger')
    const content = twitch.locator(':scope > .accordion-content')
    await expect(trigger).toHaveAttribute('aria-expanded', 'false')
    await expect(trigger).toHaveAttribute('aria-controls', 'twitch-settings-content')
    await expect(content).toBeHidden()
    await trigger.press('Enter')
    await expect(trigger).toHaveAttribute('aria-expanded', 'true')
    const field = twitch.getByLabel('Target channel login')
    await field.fill('unsaved_channel')
    await trigger.press('Space')
    await expect(content).toBeHidden()
    await expect(trigger).toBeFocused()
    await trigger.press('Enter')
    await expect(field).toHaveValue('unsaved_channel')
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
  const application = page.locator('.settings-application-box')
  await expect(application.getByLabel('Twitch application client ID')).toBeVisible()
  await application.getByRole('button', { name: 'Open Twitch Developer Console' }).click()
  expect(await page.evaluate(() => Reflect.get(window, 'opened'))).toEqual(['twitch_developer_console'])
  await expect(application.locator('code')).toHaveText('http://localhost:4343/oauth/callback')
  await application.getByRole('button', { name: 'Copy OAuth callback URL' }).click()
  expect(await page.evaluate(() => Reflect.get(window, 'copiedCallback'))).toBe('http://localhost:4343/oauth/callback')
  await expect(page.getByRole('status')).toHaveText(/OAuth callback URL copied/)
  await expect(page.getByRole('button', { name: 'Authorize Twitch', exact: true })).toHaveCount(0)
  await expect(page.locator('#twitch-application .accordion-badges .state-pill')).toHaveText('Secret missing')
  await expect(application.getByRole('button', { name: 'Add secret', exact: true })).toBeDisabled()
})

for (const width of [1280, 390]) test(`Twitch instructions preserve the Desktop draft and keyboard focus at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 })
  await page.goto('/tests/fixture.html?settings')
  await openTwitchSettings(page)
  const heading = page.getByRole('heading', { name: 'Twitch application' })
  const field = page.getByLabel('Twitch application client ID')
  await field.fill('draft-client')
  const open = page.getByRole('button', { name: 'Setup guide', exact: true })
  expect((await open.boundingBox())!.x).toBeGreaterThan((await heading.boundingBox())!.x)
  await open.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Twitch setup instructions' })
  await expect(dialog.locator('[data-editor-focus]')).toBeFocused()
  await expect(dialog).toContainText('Confidential')
  await expect(dialog).toContainText('http://localhost:4343/oauth/callback')
  await expect(dialog).toContainText('Add secret & restart')
  await expect(dialog).toContainText('/mod bot_login')
  await page.keyboard.press('Tab')
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(open).toBeFocused()
  await expect(field).toHaveValue('draft-client')
  await open.click()
  await page.mouse.click(2, 2)
  await expect(dialog).toHaveCount(0)
  await expect(open).toBeFocused()
  await open.click()
  await dialog.getByRole('button', { name: 'Close setup instructions' }).click()
  await expect(field).toHaveValue('draft-client')
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
  await expect(page.locator('.twitch-status-grid > div').filter({ hasText: /^Authorization/ })).toHaveText('AuthorizationRequired')
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
    const savedChannel = page.getByRole('combobox', { name: 'Saved channel', exact: true })
    const editor = page.locator('#twitch-settings .target-preset-editor')
    const savedBounds = (await savedChannel.boundingBox())!
    const editorBounds = (await editor.boundingBox())!
    const name = page.getByLabel('Saved channel name', { exact: true })
    const save = page.getByRole('button', { name: 'Save channel', exact: true })
    const remove = page.getByRole('button', { name: 'Delete saved channel', exact: true })
    await expect(name).toBeVisible()
    await expect(save).toBeVisible()
    await expect(remove).toBeVisible()
    const nameBounds = (await name.boundingBox())!
    const saveBounds = (await save.boundingBox())!
    const removeBounds = (await remove.boundingBox())!
    if (width > 760) {
      expect(Math.abs(savedBounds.y - nameBounds.y)).toBeLessThanOrEqual(1)
      expect(editorBounds.x).toBeGreaterThan(savedBounds.x + savedBounds.width)
      expect(Math.abs(savedBounds.width - editorBounds.width)).toBeLessThanOrEqual(2)
      expect(Math.abs(nameBounds.width - saveBounds.width * 2)).toBeLessThanOrEqual(2)
      expect(Math.abs(saveBounds.width - removeBounds.width)).toBeLessThanOrEqual(2)
    } else {
      expect(editorBounds.y).toBeGreaterThan(savedBounds.y + savedBounds.height)
      expect(Math.abs(editorBounds.x - savedBounds.x)).toBeLessThanOrEqual(1)
    }
    if (width <= 480) {
      expect(Math.abs(nameBounds.width - editorBounds.width)).toBeLessThanOrEqual(2)
      expect(saveBounds.y).toBeGreaterThan(nameBounds.y + nameBounds.height)
      expect(Math.abs(saveBounds.y - removeBounds.y)).toBeLessThanOrEqual(1)
    } else {
      expect(Math.abs(nameBounds.y - saveBounds.y)).toBeLessThanOrEqual(1)
      expect(Math.abs(saveBounds.y - removeBounds.y)).toBeLessThanOrEqual(1)
    }
    for (const [firstLabel, secondLabel] of [
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
    const connection = page.getByRole('article', { name: 'Bot session' })
    await expect(connection.getByRole('heading')).toHaveText('Stopped')
    await expect(connection).toContainText('Start Bot to connect')
    await connection.getByRole('button', { name: 'Help: Bot session', exact: true }).focus()
    await expect(page.getByRole('tooltip')).toContainText('Authorization: Not verified (token cache found)')
    await page.keyboard.press('Escape')
    await expect(page.locator('.dashboard-ai-card')).toContainText('synthetic-model')
    await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).not.toBeChecked()

    await page.getByRole('button', { name: 'Start Bot', exact: true }).click()
    await expect(connection).toContainText('Session running.')
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
      await expect(connection.getByRole('button', { name: ['failed', 'stopped'].includes(state) ? 'Start Bot' : 'Stop Bot', exact: true })).toBeEnabled()
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
    await expect(twitchSection).toContainText('Twitch client secret')
    await expect(page.locator('#credential-settings')).toHaveCount(0)
    await expect(page.locator('#nav-Settings')).not.toContainText('Gemini API key')
    const help = page.getByRole('button', { name: 'Help: Twitch connection', exact: true })
    await help.focus()
    const tooltip = page.getByRole('tooltip')
    await expect(tooltip).toContainText('Saved channels share the bot account and authorization')
    await page.keyboard.press('Escape')
    await expect(twitchSection.getByRole('button', { name: 'Replace secret', exact: true })).toBeVisible()
    await expect(twitchSection.getByRole('button', { name: 'Save & apply', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
    await expect(page.locator('.dashboard-ai-card')).toContainText('AI unavailable')
    await expect(page.locator('.setup-card')).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Start Bot', exact: true })).toBeEnabled()
    expect(await page.evaluate(() => Reflect.get(window, 'credentialCalls'))).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}

test('secret changes retain Twitch drafts and require restart across Settings and Dashboard', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured&auth')
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await openTwitchSettings(page)
  const twitchSection = page.locator('#twitch-settings')
  await twitchSection.getByLabel('Target channel login').fill('unsaved_channel')
  await twitchSection.getByLabel('Twitch client secret', { exact: true }).fill('synthetic-secret')
  await twitchSection.getByRole('button', { name: 'Replace secret', exact: true }).click()
  await expect(twitchSection.getByLabel('Target channel login')).toHaveValue('unsaved_channel')
  await expect(twitchSection.getByLabel('Twitch client secret', { exact: true })).toHaveValue('')
  await expect(twitchSection.getByRole('button', { name: 'Authorize Twitch', exact: true })).toBeDisabled()
  await expect(twitchSection.getByRole('button', { name: 'Save & restart', exact: true })).toBeVisible()
  await twitchSection.getByLabel('Saved channel name', { exact: true }).fill('After restart')
  await twitchSection.getByRole('button', { name: 'Save channel', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Restart the application to apply pending Twitch setup')
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  await expect(page.locator('.setup-card')).toContainText('Restart to apply Twitch setup')
  await expect(page.getByRole('article', { name: 'Bot session' })).not.toContainText('Restart the application')
  await expect(page.getByRole('button', { name: 'Stop Bot', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Authorize Twitch', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Stop Bot', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Start Bot', exact: true })).toBeDisabled()
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
    await expect(twitchSection.getByRole('combobox', { name: /^Saved channel/ })).toHaveAttribute('data-value', 'synthetic-1')
    await expect(twitchSection.getByLabel('Bot account login')).toHaveValue('testbot')
    await expect(twitchSection.getByLabel('Twitch application client ID')).toHaveValue('synthetic-client')
    await expect(twitchSection.locator('.twitch-status-grid > div').filter({ hasText: 'Active channel' })).toContainText('testchannel')
    expect(await page.evaluate(() => Reflect.get(window, 'twitchCalls'))).toEqual([['save_channel', 'synthetic-1']])
    await twitchSection.getByRole('button', { name: running ? 'Save & reconnect' : 'Save & apply', exact: true }).click()
    await expect(twitchSection.locator('.twitch-status-grid > div').filter({ hasText: 'Active channel' })).toContainText('otherchannel')
    expect(await page.evaluate(() => Reflect.get(window, 'credentialCalls'))).toEqual([])
    expect(await page.evaluate(() => Reflect.get(window, 'twitchCalls')).then((calls) => calls.at(-1))).toEqual(['reconnect'])
    await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
    await expect(page.getByRole('article', { name: 'Bot session' }).getByRole('heading')).toHaveText(running ? 'Connecting' : 'Stopped')
  })
}

test('identity changes explain restart before saving and do not reconnect', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured&connection=connected')
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await openTwitchSettings(page)
  const twitchSection = page.locator('#twitch-settings')
  await twitchSection.getByLabel('Twitch application client ID').fill('other-client')
  await twitchSection.getByRole('button', { name: 'Save & restart', exact: true }).click()
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'twitchCalls').map((call: string[]) => call[0]))).toEqual(['save', 'restart'])
})

for (const connection of ['stopped', 'connected']) {
  test(`configured Dashboard ${connection} fits the default window`, async ({ page }) => {
    await page.setViewportSize({ width: 1180, height: 760 })
    await page.goto(`/tests/fixture.html?configured&cachedToken&authorized&aiAvailable&connection=${connection}`)
    const session = page.getByRole('article', { name: 'Bot session' })
    await expect(session.getByRole('heading')).toHaveText(connection === 'connected' ? 'Connected' : 'Stopped')
    await expect(page.getByRole('article', { name: 'Setup checklist' })).toHaveCount(0)
    for (const label of ['Channel', 'Bot account', 'Session uptime']) await expect(session.getByText(label, { exact: true })).toBeVisible()
    const strip = (await session.boundingBox())!
    const commands = (await page.getByRole('article', { name: 'Recent commands' }).boundingBox())!
    const ai = (await page.getByRole('heading', { name: 'AI controls', exact: true }).boundingBox())!
    const activity = (await page.getByRole('heading', { name: 'Stream activity', exact: true }).boundingBox())!
    expect(commands.y).toBeGreaterThan(strip.y + strip.height)
    expect(ai.y).toBeGreaterThan(commands.y + commands.height)
    expect(Math.abs(ai.y - activity.y)).toBeLessThanOrEqual(1)
    expect(ai.x).toBeLessThan(activity.x)
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
    await expect(page.getByRole('article', { name: 'Bot session' })).toContainText('a_very_long_channel')
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
  await expect(page.getByRole('article', { name: 'Bot session' }).getByRole('heading')).toHaveText('Not configured')
  await expect(page.getByRole('button', { name: 'Start Bot', exact: true })).toBeDisabled()
  await expect(page.locator('.dashboard-layout')).not.toContainText('Add a Gemini')
  await notice.getByRole('button').click()
  await expect(page.locator('#twitch-settings > .accordion-header > .accordion-trigger')).toHaveAttribute('aria-expanded', 'true')
  await expect(page.locator('#twitch-settings')).toBeInViewport()
})

test('commands-only Dashboard stays quiet about optional Gemini and links to AI controls', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured&cachedToken&connection=connected')
  await expect(page.getByRole('article', { name: 'Bot session' }).getByRole('heading')).toHaveText('Connected')
  await expect(page.locator('.setup-card')).toHaveCount(0)
  await expect(page.locator('.dashboard-layout')).not.toContainText('Gemini')
  await expect(page.locator('.dashboard-ai-card')).toContainText('AI unavailable')
  await page.getByRole('button', { name: 'Manage AI', exact: true }).click()
  await expect(page.locator('#ai-behavior')).toBeInViewport()
})

for (const running of [false, true]) {
  test(`pending channel change remains distinct while ${running ? 'connected' : 'stopped'}`, async ({ page }) => {
    await page.goto(`/tests/fixture.html?configured&reconnectRequired&connection=${running ? 'connected' : 'stopped'}`)
    const notice = page.locator('.dashboard-notice')
    await expect(notice.getByRole('heading')).toHaveText('Channel change pending')
    await expect(notice).toContainText(running ? 'Save & reconnect' : 'Save & apply')
    await expect(page.getByRole('article', { name: 'Bot session' }).getByRole('heading')).toHaveText(running ? 'Connected' : 'Stopped')
    await expect(page.getByRole('button', { name: running ? 'Stop Bot' : 'Start Bot', exact: true })).toBeEnabled()
  })
}

test('Dashboard exposes connection failure recovery and setup loading errors', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured&connection=failed')
  const connection = page.getByRole('article', { name: 'Bot session' })
  await expect(connection).toContainText('Check Logs, then Start Bot again')
  await connection.getByRole('button', { name: 'Open Logs', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Logs', exact: true, level: 1 })).toBeVisible()
  await page.goto('/tests/fixture.html?configured&setupError')
  await expect(page.locator('.dashboard-notice')).toContainText('Synthetic Twitch setup load failure')
  await page.locator('.dashboard-notice').getByRole('button').click()
  await expect(page.locator('#twitch-settings > .accordion-header > .accordion-trigger')).toHaveAttribute('aria-expanded', 'true')
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


for (const width of [1280, 320]) {
  test(`desktop recovery progress stays actionable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/tests/fixture.html?configured&connection=reconnecting&cachedToken')
    await page.evaluate(() => Reflect.get(window, 'setFixtureStatus')({
      twitch_recovery: { reason: 'retry_wait', attempt: 4, elapsed_seconds: 156, next_retry_seconds: 20 },
    }))
    const card = page.getByRole('article', { name: 'Bot session' })
    await expect(card).toContainText('Recovery: waiting to retry. Attempt 4, 156s elapsed. Next retry in 20s.')
    await expect(page.getByRole('button', { name: 'Stop Bot', exact: true })).toBeEnabled()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await page.screenshot({ path: `node_modules/.tmp/recovery-desktop-${width}.png`, fullPage: true })
    await page.evaluate(() => Reflect.get(window, 'setFixtureStatus')({
      twitch_recovery: null, twitch_connection_state: 'connected', twitch_connected: true,
    }))
    await expect(card).not.toContainText('Recovery:')
    await expect(card).toContainText('Connected')
  })
}

for (const running of [false, true]) {
  test(`reopened Desktop preserves a ${running ? 'running' : 'stopped'} Twitch session intent`, async ({ page }) => {
    await page.goto(`/tests/fixture.html?configured&relaunchFixture${running ? '&connection=connected' : ''}`)
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await openTwitchSettings(page)
    await page.getByLabel('Bot account login').fill('differentbot')
    await page.getByRole('button', { name: 'Save & restart', exact: true }).click()
    await expect(page.getByRole('article', { name: 'Bot session' }).getByRole('heading')).toHaveText(running ? 'Authorization required' : 'Stopped')
    if (!running) {
      await expect(page.getByRole('button', { name: 'Authorize Twitch' })).toHaveCount(0)
      await page.getByRole('button', { name: 'Start Bot' }).click()
    }
    await expect(page.getByRole('button', { name: 'Authorize Twitch' })).toBeEnabled()
  })
}

test('saved pending identity applies from Dashboard and a cancelled restart keeps other drafts', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured')
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await openTwitchSettings(page)
  await page.getByLabel('Twitch application client ID').fill('changed-client')
  await page.getByRole('button', { name: 'Save for later' }).click()
  await expect(page.getByRole('button', { name: 'Restart now' })).toBeVisible()
  await page.getByLabel('Target channel login').fill('unsaved_channel')
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  const restart = page.locator('.setup-card').getByRole('button', { name: 'Restart now' })
  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('Twitch connection')
    await dialog.dismiss()
  })
  await restart.click()
  expect(await page.evaluate(() => Reflect.get(window, 'twitchCalls').map((call: string[]) => call[0]))).toEqual(['save'])
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await expect(page.getByLabel('Target channel login')).toHaveValue('unsaved_channel')
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  page.once('dialog', (dialog) => dialog.accept())
  await restart.click()
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'twitchCalls').at(-1))).toEqual(['restart', false])
})

test('failed identity save leaves HeetKit running', async ({ page }) => {
  await page.goto('/tests/fixture.html?configured&twitchSaveError')
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await openTwitchSettings(page)
  await page.getByLabel('Bot account login').fill('differentbot')
  await page.getByRole('button', { name: 'Save & restart', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Twitch settings could not be saved')
  expect(await page.evaluate(() => Reflect.get(window, 'twitchCalls').map((call: string[]) => call[0]))).toEqual(['save'])
})

for (const action of ['add', 'replace', 'remove', 'test', 'failed', 'unchanged']) {
  test(`Desktop secret ${action} requests a restart only for an applied change`, async ({ page }) => {
    const query = action === 'add' ? '' : action === 'failed' ? '?configured&credentialSaveError' : action === 'unchanged' ? '?configured&credentialUnchanged' : '?configured'
    await page.goto(`/tests/fixture.html${query}`)
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    await openTwitchSettings(page)
    if (action === 'test') {
      await page.getByRole('button', { name: 'Test saved secret', exact: true }).click()
      await expect(page.getByRole('status')).toContainText('validation passed')
    } else if (action === 'remove') {
      page.once('dialog', (dialog) => dialog.accept())
      const secretActions = page.locator('#twitch-settings .secret-actions-menu')
      await secretActions.locator('summary').click()
      await secretActions.getByRole('button', { name: 'Remove secret & restart' }).click()
    } else {
      await page.getByLabel('Twitch client secret', { exact: true }).fill('synthetic-secret')
      await page.getByRole('button', { name: action === 'add' ? 'Add secret & restart' : 'Replace secret & restart' }).click()
    }
    if (['add', 'replace', 'remove'].includes(action)) {
      await expect.poll(() => page.evaluate(() => Reflect.get(window, 'twitchCalls'))).toEqual([['restart', false]])
    } else {
      if (action === 'failed') await expect(page.getByRole('alert')).toContainText('Could not store the credential')
      if (action === 'unchanged') await expect(page.getByRole('status')).toContainText('Client secret unchanged')
      expect(await page.evaluate(() => Reflect.get(window, 'twitchCalls'))).toEqual([])
    }
  })
}
