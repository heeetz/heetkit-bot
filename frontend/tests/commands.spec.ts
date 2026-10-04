import { expect, test, type Page } from '@playwright/test'

async function expandCommand(page: Page, name: string) {
  const card = page.locator('.command-card').filter({ has: page.getByText(`!${name}`, { exact: true }) })
  await card.getByRole('button', { name: /Show settings/ }).click()
  return card
}

async function calls(page: Page) {
  return page.evaluate(() => Reflect.get(window, 'commandCalls'))
}

test('creator and existing-command editor appear above the list with compact templates', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  await expect(page.locator('.command-summary-title strong')).toHaveText(['!forecast', '!ping', '!tg'])
  await page.getByRole('button', { name: 'New command', exact: true }).click()
  const editor = page.locator('.custom-command-editor')
  const list = page.locator('.custom-command-list')
  await expect(editor).toBeVisible()
  await expect(page.locator('.custom-command-editor + .custom-command-list')).toHaveCount(1)
  expect((await editor.boundingBox())!.y + (await editor.boundingBox())!.height).toBeLessThan((await list.boundingBox())!.y)
  const templates = editor.locator('textarea')
  await expect(templates).toHaveCount(1)
  await templates.fill('Hello, {sender}!')
  await templates.press('End')
  await templates.press('Enter')
  await expect(templates).toHaveValue('Hello, {sender}!\n')
  await templates.press('Enter')
  await templates.pressSequentially('Welcome, {target}!')
  await expect(templates).toHaveValue('Hello, {sender}!\n\nWelcome, {target}!')
  await editor.getByRole('button', { name: 'Cancel', exact: true }).click()
  await list.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(editor.locator('textarea')).toHaveValue('Hello, {sender}!\nWelcome, {target}!')
  expect((await editor.boundingBox())!.y).toBeLessThan((await list.boundingBox())!.y)
})

test('new and existing custom commands save lines, commas, variables and settings', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  await page.getByRole('button', { name: 'New command', exact: true }).click()
  const editor = page.locator('.custom-command-editor')
  await editor.getByLabel('Command name').fill('greet')
  await editor.getByLabel('Aliases, separated by commas').fill('greeting, welcome')
  await editor.getByRole('combobox').selectOption('MODERATOR')
  await editor.getByLabel('Per-user cooldown (seconds)').fill('3')
  await editor.getByLabel('Global cooldown (seconds)').fill('7')
  await editor.locator('textarea').fill('  Hello, {sender}!\n\n Welcome, {arg9}! \n  ')
  await editor.getByRole('button', { name: 'Save command', exact: true }).click()
  await expect(editor).toHaveCount(0)
  expect((await calls(page))[0]).toEqual(['save_custom_command', {
    id: null, name: 'greet', enabled: true, responses: ['Hello, {sender}!', 'Welcome, {arg9}!'],
    permission: 'MODERATOR', per_user_seconds: 3, global_seconds: 7, aliases: ['greeting', 'welcome'],
  }])
  const row = page.locator('.custom-command-row').filter({ has: page.getByText('!greet', { exact: true }) })
  await expect(row.getByText('Random response', { exact: true })).toBeVisible()
  await row.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(editor.locator('textarea')).toHaveValue('Hello, {sender}!\nWelcome, {arg9}!')
  await editor.locator('textarea').fill('Updated, {args}!\n\nHi, {random_user}!')
  await editor.getByRole('button', { name: 'Save command', exact: true }).click()
  await expect(editor).toHaveCount(0)
  expect((await calls(page))[1][1]).toMatchObject({
    id: 'synthetic-new', responses: ['Updated, {args}!', 'Hi, {random_user}!'],
    aliases: ['greeting', 'welcome'], permission: 'MODERATOR', per_user_seconds: 3, global_seconds: 7,
  })
})

test('forecast response Apply Save Reset preserves independent settings drafts', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  const card = await expandCommand(page, 'forecast')
  const responses = card.locator('.command-response-editor')
  const settings = card.locator('.command-action-footer')
  await expect(responses.locator('textarea')).toHaveCount(1)
  await expect(responses.getByRole('button', { name: 'Apply', exact: true })).toBeDisabled()
  await card.getByRole('combobox').selectOption('MODERATOR')
  await responses.locator('textarea').fill('  Tomorrow, try again.\n\nTake a break, {literal}.\n ')
  await responses.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(responses.getByText('Runtime only', { exact: true })).toBeVisible()
  await expect(card.getByRole('combobox')).toHaveValue('MODERATOR')
  expect((await calls(page))[0]).toEqual(['apply_command_responses', 'forecast', ['Tomorrow, try again.', 'Take a break, {literal}.']])
  await responses.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(responses.getByText('Saved override', { exact: true })).toBeVisible()
  await expect(responses.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
  await responses.locator('textarea').fill('Draft, retained.\nAnother draft.')
  await settings.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(responses.locator('textarea')).toHaveValue('Draft, retained.\nAnother draft.')
  await expect(card.getByRole('combobox')).toHaveValue('MODERATOR')
  page.once('dialog', (dialog) => dialog.dismiss())
  await responses.getByRole('button', { name: 'Reset', exact: true }).click()
  expect((await calls(page)).filter((call: unknown[]) => call[0] === 'reset_command_responses')).toHaveLength(0)
  page.once('dialog', (dialog) => dialog.accept())
  await responses.getByRole('button', { name: 'Reset', exact: true }).click()
  await expect(responses.locator('textarea')).toHaveValue('Tomorrow brings a new opportunity.\nTake a break, then try again.')
  await expect(card.getByRole('combobox')).toHaveValue('MODERATOR')
})

test('tg edits one entire message with independent response actions and draft retention', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  const tg = await expandCommand(page, 'tg')
  const tgResponses = tg.locator('.command-response-editor')
  await tgResponses.locator('textarea').fill(' Community, https://example.test\nJoin us! ')
  const forecast = await expandCommand(page, 'forecast')
  const forecastResponses = forecast.locator('.command-response-editor')
  await forecastResponses.locator('textarea').fill('Different forecast')
  await forecastResponses.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(tgResponses.locator('textarea')).toHaveValue(' Community, https://example.test\nJoin us! ')
  await tgResponses.getByRole('button', { name: 'Apply', exact: true }).click()
  expect((await calls(page))[1]).toEqual(['apply_command_responses', 'tg', [' Community, https://example.test\nJoin us! ']])
  await expect(page.getByRole('status')).toContainText('!tg')
  await tgResponses.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(tgResponses.getByText('Saved override', { exact: true })).toBeVisible()
  await tgResponses.locator('textarea').fill(' \n ')
  await expect(tgResponses.getByRole('button', { name: 'Apply', exact: true })).toBeDisabled()
  await expect(tgResponses.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
  page.once('dialog', (dialog) => dialog.accept())
  await tgResponses.getByRole('button', { name: 'Reset', exact: true }).click()
  await expect(tgResponses.locator('textarea')).toHaveValue('Configure your community link.')
  await expect(forecastResponses.locator('textarea')).toHaveValue('Different forecast')
})

test('response limits and backend failures retain editable drafts', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html?responseError')
  const forecast = await expandCommand(page, 'forecast')
  const responses = forecast.locator('.command-response-editor')
  await responses.locator('textarea').fill('\n  \n')
  await expect(responses.getByRole('button', { name: 'Apply', exact: true })).toBeDisabled()
  await expect(responses.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()
  await responses.locator('textarea').fill('A response, preserved.')
  await responses.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText(/Synthetic response save failure/)
  await expect(responses.locator('textarea')).toHaveValue('A response, preserved.')
  await page.goto('/tests/commands.fixture.html?customError')
  await page.locator('.custom-command-list').getByRole('button', { name: 'Edit', exact: true }).click()
  const editor = page.locator('.custom-command-editor')
  await editor.locator('textarea').fill('Unknown, {invalid}!')
  await editor.getByRole('button', { name: 'Save command', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText(/unknown variable/)
  await expect(editor.locator('textarea')).toHaveValue('Unknown, {invalid}!')
})

for (const width of [1280, 390]) {
  test(`multiline editors stay compact inside their cards at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/tests/commands.fixture.html')
    const forecast = await expandCommand(page, 'forecast')
    await page.getByRole('button', { name: 'New command', exact: true }).click()
    for (const container of [forecast.locator('.command-response-editor'), page.locator('.custom-command-editor')]) {
      const textarea = container.locator('textarea')
      const bounds = (await textarea.boundingBox())!
      const containerBounds = (await container.boundingBox())!
      expect(bounds.height).toBeLessThan(220)
      expect(bounds.x).toBeGreaterThanOrEqual(containerBounds.x)
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(containerBounds.x + containerBounds.width)
    }
    if (width === 1280) await page.screenshot({ path: 'node_modules/.tmp/commands-wide.png', fullPage: true })
    else await page.screenshot({ path: 'node_modules/.tmp/commands-narrow.png', fullPage: true })
  })
}
