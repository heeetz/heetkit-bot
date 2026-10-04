import { expect, test } from '@playwright/test'

test('clean setup provides the developer action and copies the backend callback', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', { value: {
      writeText: async (value: string) => { Object.assign(window, { copiedCallback: value }) },
    } })
  })
  await page.goto('/tests/fixture.html')
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
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
    for (const [firstLabel, secondLabel] of [
      ['Connection preset', 'Preset name'],
      ['Bot account login', 'Bot account user ID'],
      ['Target channel login', 'Target channel user ID'],
    ]) {
      const first = page.getByRole(firstLabel === 'Connection preset' ? 'combobox' : 'textbox', { name: firstLabel })
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
