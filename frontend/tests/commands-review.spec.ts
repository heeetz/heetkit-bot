import { test } from '@playwright/test'
import { mockAnalytics } from './analytics-helpers'
import { reviewCommands, reviewTrend } from './command-review-helpers'

test.use({ hasTouch: true })
for (const width of [1600, 390]) test(`Commands and Analytics Desktop design review at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1200 })
  await page.goto('/tests/commands.fixture.html?shell&extended')
  await mockAnalytics(page, true)
  await reviewCommands(page, 'desktop', width)
  await reviewTrend(page, 'desktop', width)
})
