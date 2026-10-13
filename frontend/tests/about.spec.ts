import { expect, test } from '@playwright/test'

test('About shows HeetKit details in the requested order and routes the author Twitch button safely', async ({ page }) => {
  await page.goto('/tests/fixture.html?about')

  const about = page.locator('.about-card')
  await expect(about.locator('h2')).toHaveText('HeetKit')
  await expect(about.locator('.section-copy')).toHaveText('Desktop control center for Twitch chat')
  await expect(about.locator('.about-details dt')).toHaveText(['Created by', 'Twitch', 'Discord', 'License'])
  await expect(about).toContainText('heeetz')
  await expect(about).toContainText('@heet_ok')
  await expect(about).toContainText('de.tected')
  await expect(about).toContainText('Apache-2.0')
  await expect(about).toContainText('Not affiliated with or endorsed by Twitch.')

  await about.getByRole('button', { name: 'Open Twitch profile @heet_ok' }).click()
  expect(await page.evaluate(() => Reflect.get(window, 'opened'))).toEqual(['author_twitch'])

  await expect(page.locator('.about-links-card')).toContainText('GitHub repository')
  await expect(page.locator('.about-links-card')).toContainText('Apache-2.0 license')
  await expect(page.locator('.about-links-card')).toContainText('Third-party notices')
  await expect(page.locator('.about-links-card')).not.toContainText('@heet_ok')
})

test('About details use four, two, and one columns across responsive widths', async ({ page }) => {
  for (const [width, expectedColumns] of [[1360, 4], [1000, 2], [600, 1]] as const) {
    await page.setViewportSize({ width, height: 800 })
    await page.goto('/tests/fixture.html?about')
    const columns = await page.locator('.about-details').evaluate((element) => {
      const value = getComputedStyle(element).gridTemplateColumns
      return value.split(' ').filter(Boolean).length
    })
    expect(columns, `expected ${expectedColumns} columns at ${width}px`).toBe(expectedColumns)
  }
})

test('About does not check automatically and checks the latest stable release on demand', async ({ page }) => {
  await page.goto('/tests/fixture.html?about')
  const card = page.locator('.update-card')

  await expect(card).toContainText('Current version')
  await expect(card).toContainText('0.1.0')
  expect(await page.evaluate(() => Reflect.get(window, 'updateCalls'))).toEqual([])

  await card.getByRole('button', { name: 'Check for updates', exact: true }).click()
  await expect(card).toContainText('You are up to date')
  await expect(card).toContainText('Latest version')
  expect(await page.evaluate(() => Reflect.get(window, 'updateCalls'))).toEqual([['check_for_updates']])

  await card.getByRole('button', { name: /Open release \/ downloads/ }).click()
  expect(await page.evaluate(() => Reflect.get(window, 'opened'))).toContain('releases')
})

test('App navigation does not trigger an update check', async ({ page }) => {
  await page.goto('/tests/fixture.html')
  await page.getByRole('button', { name: 'About', exact: true }).click()
  await expect(page.locator('.update-card')).toBeVisible()
  await page.waitForTimeout(100)
  expect(await page.evaluate(() => Reflect.get(window, 'updateCalls'))).toEqual([])
})

test('About shows the current and newer release states with plain-text notes', async ({ page }) => {
  await page.goto('/tests/fixture.html?about&updateNewer&notesMarkup')
  const card = page.locator('.update-card')
  await card.getByRole('button', { name: 'Check for updates', exact: true }).click()

  await expect(card).toContainText('Update available')
  await expect(card).toContainText('Latest version')
  await expect(card).toContainText('0.2.0')
  const notes = card.locator('.update-notes')
  await expect(notes).toHaveText('Fixes <strong>markup</strong> & **formatting**.')
  await expect(notes.locator('strong')).toHaveCount(0)
})

test('About prevents duplicate checks while busy', async ({ page }) => {
  await page.goto('/tests/fixture.html?about&updateDelay=250')
  const card = page.locator('.update-card')
  const check = card.getByRole('button', { name: 'Check for updates', exact: true })
  await check.click()
  const busyCheck = card.getByRole('button', { name: 'Checking…' })
  await expect(busyCheck).toBeDisabled()
  expect(await page.evaluate(() => Reflect.get(window, 'updateCalls'))).toEqual([['check_for_updates']])
  await expect(card.getByRole('button', { name: 'Check again' })).toBeEnabled()
})

test('About clears stale results and exposes retry after a failed or rejected check', async ({ page }) => {
  await page.goto('/tests/fixture.html?about&updateSequence=newer,error,current')
  const card = page.locator('.update-card')
  const check = card.getByRole('button', { name: 'Check for updates', exact: true })
  await check.click()
  await expect(card).toContainText('Update available')

  await card.getByRole('button', { name: 'Check again' }).click()
  await expect(card.getByRole('alert')).toContainText('Could not reach the update service.')
  await expect(card.locator('.update-result')).toHaveCount(0)
  await expect(card.getByRole('button', { name: 'Check again' })).toBeEnabled()
  await card.getByRole('button', { name: 'Open release / downloads' }).click()
  expect(await page.evaluate(() => Reflect.get(window, 'opened'))).toContain('releases')
  await card.getByRole('button', { name: 'Check again' }).click()
  await expect(card).toContainText('You are up to date')
  await expect(card.getByRole('alert')).toHaveCount(0)
  await expect(card.getByRole('button', { name: /Open release \/ downloads/ })).toBeEnabled()

  await page.goto('/tests/fixture.html?about&updateReject')
  const rejectedCard = page.locator('.update-card')
  await rejectedCard.getByRole('button', { name: 'Check for updates', exact: true }).click()
  await expect(rejectedCard.getByRole('alert')).toContainText('Update service is unavailable.')
})

test('About update actions lead compact version boxes and wrap within their card', async ({ page }) => {
  for (const width of [1180, 900, 390, 320]) {
    await page.setViewportSize({ width, height: 800 })
    await page.goto('/tests/fixture.html?configured&updateNewer')
    await page.getByRole('navigation').getByRole('button', { name: 'About', exact: true }).click()
    const card = page.locator('.update-card')
    const check = card.getByRole('button', { name: 'Check for updates', exact: true })
    const downloads = card.getByRole('button', { name: 'Open release / downloads' })
    const version = card.locator('.update-summary > div').first()
    if (width >= 900) {
      const boxes = await Promise.all([check, downloads, version].map(async (item) => (await item.boundingBox())!))
      expect(boxes[0].x + boxes[0].width).toBeLessThanOrEqual(boxes[1].x)
      expect(boxes[1].x + boxes[1].width).toBeLessThanOrEqual(boxes[2].x)
      for (const box of boxes) expect(box.y + box.height / 2).toBeCloseTo(boxes[0].y + boxes[0].height / 2, 0)
    }
    await check.click()
    await expect(card.locator('.update-summary > div')).toHaveCount(2)
    for (const item of await card.locator('.update-summary > div, .update-actions button').all()) {
      const box = (await item.boundingBox())!
      const parent = (await card.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(parent.x)
      expect(box.x + box.width).toBeLessThanOrEqual(parent.x + parent.width)
      if (await item.evaluate((element) => element.parentElement?.classList.contains('update-summary'))) {
        expect(box.width).toBeLessThanOrEqual(220)
      }
    }
    expect(await card.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
    if (width === 1180 || width === 320) await card.screenshot({ path: `node_modules/.tmp/ui-update-${width}.png` })
    const help = card.getByRole('button', { name: 'Help: Check for updates' })
    await help.focus()
    await expect(page.getByRole('tooltip')).toContainText('Nothing is downloaded or installed automatically')
    await help.press('Escape')
  }
})

test('A release browser failure leaves manual checking and About links usable', async ({ page }) => {
  await page.goto('/tests/fixture.html?about&openError')
  const card = page.locator('.update-card')
  await card.getByRole('button', { name: 'Open release / downloads' }).click()
  await expect(page.getByRole('alert')).toContainText('Could not open the external link.')
  await expect(card.getByRole('button', { name: 'Open release / downloads' })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'GitHub repository' })).toBeEnabled()
  await card.getByRole('button', { name: 'Check for updates', exact: true }).click()
  await expect(card).toContainText('You are up to date')
})
