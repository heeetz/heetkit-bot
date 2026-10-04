import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-04T12:00:00Z') })
  await page.clock.pauseAt(new Date('2026-10-04T12:00:01Z'))
})

for (const error of [false, true]) {
  test(`${error ? 'error' : 'success'} expires after ten seconds despite callback changes`, async ({ page }) => {
    await page.goto(`/tests/fixture.html?toast${error ? '&error' : ''}`)
    const toast = page.getByRole(error ? 'alert' : 'status')
    await expect(toast).toHaveAttribute('aria-live', error ? 'assertive' : 'polite')
    for (let render = 0; render < 9; render++) {
      await page.clock.runFor(1000)
      await page.getByRole('button', { name: /Rerender/ }).click()
    }
    await page.clock.runFor(999)
    await expect(toast).toBeVisible()
    await page.clock.runFor(1)
    await expect(toast).toHaveCount(0)
  })
}

test('a changed displayed message gets a fresh ten seconds', async ({ page }) => {
  await page.goto('/tests/fixture.html?toast')
  await expect(page.getByRole('status')).toBeVisible()
  await page.clock.runFor(6000)
  await page.getByRole('button', { name: 'Change error' }).click()
  await expect(page.getByRole('alert')).toHaveText(/Changed error/)
  await page.clock.runFor(9999)
  await expect(page.getByRole('alert')).toBeVisible()
  await page.clock.runFor(1)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('a hidden notice changing does not prolong the displayed error', async ({ page }) => {
  await page.goto('/tests/fixture.html?toast&error')
  await expect(page.getByRole('alert')).toBeVisible()
  await page.clock.runFor(6000)
  await page.getByRole('button', { name: 'Change notice' }).click()
  await page.clock.runFor(4000)
  await expect(page.locator('.feedback-toast')).toHaveCount(0)
})

test('manual close still dismisses feedback immediately', async ({ page }) => {
  await page.goto('/tests/fixture.html?toast')
  await page.getByRole('button', { name: 'Dismiss message' }).click()
  await expect(page.locator('.feedback-toast')).toHaveCount(0)
})
