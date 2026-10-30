import { expect, test } from '@playwright/test'

test('AI Access is consolidated into Commands and Playground stays available', async ({ page }) => {
  await page.goto('/tests/fixture.html')
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(page.locator('#ai-blocked-users')).toHaveCount(0)
  await expect(page.getByRole('navigation').getByRole('button', { name: 'AI access', exact: true })).toHaveCount(0)
  const playground = page.locator('.ai-playground')
  await playground.getByLabel('Playground prompt').fill('Explain plants')
  await playground.getByRole('button', { name: 'Test prompt' }).click()
  await expect(playground.getByRole('status')).toContainText('Synthetic response')
  await page.getByRole('navigation').getByRole('button', { name: 'Commands', exact: true }).click()
  await page.getByRole('navigation').getByRole('button', { name: 'User restrictions', exact: true }).click()
  await expect(page.locator('#command-restrictions')).toBeInViewport()
})
