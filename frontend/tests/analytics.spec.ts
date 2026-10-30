import { expect, test } from '@playwright/test'
import { analyticsFlow, mockAnalytics } from './analytics-helpers'

for (const width of [1280, 320]) test(`Analytics Desktop windows, charts, privacy controls, balance and memory at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 })
  await page.goto('/tests/fixture.html?a4Models&aiAvailable&askToggle')
  const mock = await mockAnalytics(page, true)
  const names = await page.getByRole('navigation', { name: 'Main navigation' }).locator('.nav-section > button').allTextContents()
  expect(names.indexOf('Analytics')).toBe(names.indexOf('Logs') + 1)
  expect(names.indexOf('Settings')).toBe(names.indexOf('Analytics') + 1)
  await analyticsFlow(page, mock, width, 'desktop')
})
