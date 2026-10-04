import { expect, test } from '@playwright/test'

const profilePath = `C:\\Synthetic profiles\\日本語 & data\\${'long-profile-name'.repeat(12)}`

for (const width of [1280, 390]) {
  test(`profile location displays, opens and copies the exact backend path at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', { value: {
        writeText: async (value: string) => { Object.assign(window, { copiedPath: value }) },
      } })
    })
    await page.goto(`/tests/fixture.html?settings&profilePath=${encodeURIComponent(profilePath)}`)
    const section = page.getByRole('region', { name: 'Data & diagnostics' })
    await expect(section.locator('code')).toHaveText(profilePath)
    await expect(section).toContainText('private authentication and application data. Do not share it.')
    const copy = section.getByRole('button', { name: 'Copy path', exact: true })
    await copy.click()
    expect(await page.evaluate(() => Reflect.get(window, 'copiedPath'))).toBe(profilePath)
    await expect(page.getByRole('status')).toContainText('Profile path copied.')
    await section.getByRole('button', { name: 'Open profile folder', exact: true }).click()
    expect(await page.evaluate(() => Reflect.get(window, 'opened'))).toEqual(['profile_folder'])
    await expect(page.getByRole('status')).toContainText('Profile folder opened.')
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
    await section.screenshot({ path: `node_modules/.tmp/profile-location-${width}.png` })
  })
}

for (const permitted of [true, false]) {
  test(`profile path copy handles legacy clipboard ${permitted ? 'success' : 'failure'}`, async ({ page }) => {
    await page.addInitScript((canCopy) => {
      Object.defineProperty(navigator, 'clipboard', { value: undefined })
      document.execCommand = () => {
        Object.assign(window, { copiedPath: document.querySelector('textarea')?.value })
        return canCopy
      }
    }, permitted)
    await page.goto(`/tests/fixture.html?settings&profilePath=${encodeURIComponent(profilePath)}`)
    const copy = page.getByRole('button', { name: 'Copy path', exact: true })
    await copy.click()
    expect(await page.evaluate(() => Reflect.get(window, 'copiedPath'))).toBe(profilePath)
    await expect(page.locator('textarea')).toHaveCount(0)
    await expect(copy).toBeFocused()
    await expect(page.getByRole(permitted ? 'status' : 'alert')).toContainText(
      permitted ? 'Profile path copied.' : 'Clipboard access is unavailable.',
    )
  })
}

test('file manager and clipboard failures keep the displayed path and allow retry', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', { value: {
      writeText: async () => { throw new Error('Clipboard permission denied.') },
    } })
  })
  await page.goto('/tests/fixture.html?settings&folderOpenError')
  const section = page.getByRole('region', { name: 'Data & diagnostics' })
  const open = section.getByRole('button', { name: 'Open profile folder', exact: true })
  await open.click()
  await expect(page.getByRole('alert')).toContainText('Could not open the profile folder in the system file manager.')
  await expect(open).toBeEnabled()
  await section.getByRole('button', { name: 'Copy path', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Clipboard permission denied.')
  await expect(section.locator('code')).toHaveText('C:\\Synthetic profiles\\TwitchBot')
})

test('an unavailable profile location disables actions while other Settings sections load', async ({ page }) => {
  await page.goto('/tests/fixture.html?settings&profileLocationError')
  const section = page.getByRole('region', { name: 'Data & diagnostics' })
  await expect(section.getByRole('alert')).toContainText('The profile location is unavailable.')
  await expect(section.getByRole('button', { name: 'Open profile folder', exact: true })).toBeDisabled()
  await expect(section.getByRole('button', { name: 'Copy path', exact: true })).toBeDisabled()
  await expect(page.getByLabel('Twitch application client ID')).toBeVisible()
  await expect(page.getByRole('checkbox', { name: /Start bot automatically/ })).toBeVisible()
})
