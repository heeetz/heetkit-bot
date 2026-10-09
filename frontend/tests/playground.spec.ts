import { expect, test } from '@playwright/test'

test('local Playground uses the prompt only and presents quota, active settings and plain text', async ({ page }) => {
  await page.goto('/tests/fixture.html')
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await page.getByRole('button', { name: 'Playground', exact: true }).click()
  const playground = page.locator('.ai-playground')
  await expect(playground).toContainText('Testing may consume real Gemini API quota')
  await expect(playground).toContainText('active personality (neutral)')
  await expect(playground).toContainText('no viewer memory, chat activity or Twitch command cooldowns')
  await expect(playground.getByRole('button', { name: 'Test prompt' })).toBeDisabled()
  await page.locator('.personality-editor textarea').fill('unsaved personality draft')
  await playground.getByLabel('Playground prompt').fill('Tell me a story')
  await playground.getByRole('button', { name: 'Test prompt' }).click()
  await expect(playground.getByRole('status')).toContainText('Synthetic response <strong>plain text</strong>.')
  await expect(playground.locator('.playground-response strong')).toHaveCount(0)
  const calls = await page.evaluate(() => (window as unknown as { playgroundCalls: unknown[][] }).playgroundCalls)
  expect(calls).toEqual([['start', 'Tell me a story']])
  await playground.getByLabel('Playground prompt').fill('Another prompt')
  await expect(playground.getByRole('status')).toBeEmpty()
  await page.screenshot({ path: 'node_modules/.tmp/playground-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Playground', exact: true }).click()
  await page.screenshot({ path: 'node_modules/.tmp/playground-narrow.png' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
})

for (const [status, label] of [
  ['input_blocked', 'Input blocked'], ['output_blocked', 'Output blocked'],
  ['provider_unavailable', 'Provider unavailable'], ['api_error', 'API error'],
  ['timeout', 'Timeout'], ['cancelled', 'Cancelled'],
]) {
  test(`Playground clearly reports ${status} without showing response content`, async ({ page }) => {
    await page.goto(`/tests/fixture.html?playgroundStatus=${status}`)
    await page.getByRole('button', { name: 'AI', exact: true }).click()
    const playground = page.locator('.ai-playground')
    await playground.getByLabel('Playground prompt').fill('Sample prompt')
    await playground.getByRole('button', { name: 'Test prompt' }).click()
    await expect(playground.getByRole('status')).toContainText(label)
    await expect(playground.getByRole('status')).not.toContainText('Synthetic response')
  })
}

for (const [source, label] of [
  ['editable_filter', 'Editable filter · phrases: synthetic rule'],
  ['protected_policy', 'Protected safety policy. This decision is separate from editable filters'],
  ['filter_timeout', 'No matched rule is reported'],
]) {
  test(`Playground identifies ${source}`, async ({ page }) => {
    await page.goto(`/tests/fixture.html?playgroundStatus=output_blocked&playgroundSource=${source}`)
    await page.getByRole('button', { name: 'AI', exact: true }).click()
    const playground = page.locator('.ai-playground')
    await playground.getByLabel('Playground prompt').fill('Sample prompt')
    await playground.getByRole('button', { name: 'Test prompt' }).click()
    await expect(playground.getByRole('status')).toContainText(label)
    if (source !== 'editable_filter') await expect(playground.locator('code')).toHaveCount(0)
  })
}

test('duplicate clicks are prevented throughout submission and cancellation', async ({ page }) => {
  await page.goto('/tests/fixture.html?playgroundStartDelay&playgroundWait')
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  const playground = page.locator('.ai-playground')
  await playground.getByLabel('Playground prompt').fill('Sample prompt')
  await playground.getByRole('button', { name: 'Test prompt' }).evaluate((button: HTMLButtonElement) => { button.click(); button.click() })
  await expect(playground.getByRole('button', { name: 'Testing…' })).toBeDisabled()
  await expect(playground.getByLabel('Playground prompt')).toBeDisabled()
  await expect(playground.getByRole('button', { name: 'Cancel request' })).toBeEnabled()
  await playground.getByRole('button', { name: 'Cancel request' }).click()
  await expect(playground.getByRole('status')).toContainText('Cancelled')
  await expect(playground.getByRole('button', { name: 'Test prompt' })).toBeEnabled()
  expect(await page.evaluate(() => (window as unknown as { playgroundCalls: unknown[][] }).playgroundCalls)).toEqual([
    ['start', 'Sample prompt'], ['cancel', '1'],
  ])
})

for (const delayedStart of [false, true]) {
  test(`leaving AI cancels requests and suppresses stale results (delayed start: ${delayedStart})`, async ({ page }) => {
    await page.goto(`/tests/fixture.html?playgroundWait${delayedStart ? '&playgroundStartDelay' : ''}`)
    await page.getByRole('button', { name: 'AI', exact: true }).click()
    const playground = page.locator('.ai-playground')
    await playground.getByLabel('Playground prompt').fill('Sample prompt')
    await playground.getByRole('button', { name: 'Test prompt' }).click()
    await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
    await expect.poll(async () => page.evaluate(() => (window as unknown as { playgroundCalls: unknown[][] }).playgroundCalls)).toEqual([
      ['start', 'Sample prompt'], ['cancel', '1'],
    ])
    await page.getByRole('button', { name: 'AI', exact: true }).click()
    await expect(playground.getByRole('status')).toBeEmpty()
    await expect(playground.getByRole('button', { name: 'Test prompt' })).toBeEnabled()
  })
}

test('start and polling failures retain prompt and permit retry', async ({ page }) => {
  for (const mode of ['playgroundStartError', 'playgroundReadError']) {
    await page.goto(`/tests/fixture.html?${mode}`)
    await page.getByRole('button', { name: 'AI', exact: true }).click()
    const playground = page.locator('.ai-playground')
    await playground.getByLabel('Playground prompt').fill('Keep this prompt')
    await playground.getByRole('button', { name: 'Test prompt' }).click()
    await expect(playground.getByRole('alert')).toBeVisible()
    await expect(playground.getByLabel('Playground prompt')).toHaveValue('Keep this prompt')
    await expect(playground.getByRole('button', { name: 'Test prompt' })).toBeEnabled()
  }
})

test('failed cancellation supports retry while request stays pending', async ({ page }) => {
  await page.goto('/tests/fixture.html?playgroundWait&playgroundCancelError')
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  const playground = page.locator('.ai-playground')
  await playground.getByLabel('Playground prompt').fill('Sample prompt')
  await playground.getByRole('button', { name: 'Test prompt' }).click()
  await playground.getByRole('button', { name: 'Cancel request' }).click()
  await expect(playground.getByRole('alert')).toContainText('Could not cancel')
  await expect(playground.getByRole('button', { name: 'Testing…' })).toBeDisabled()
  await playground.getByRole('button', { name: 'Cancel request' }).click()
  await expect(playground.getByRole('status')).toContainText('Cancelled')
  await expect(playground.getByRole('alert')).toHaveCount(0)
})
