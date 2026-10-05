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
