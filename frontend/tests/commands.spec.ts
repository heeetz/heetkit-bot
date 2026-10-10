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
  await expect(page.locator('.command-summary-title strong')).toHaveText(['!fate', '!ping', '!tg'])
  await page.getByRole('button', { name: 'New command', exact: true }).click()
  const editor = page.locator('.custom-command-editor')
  const list = page.locator('.custom-command-list')
  await expect(editor).toBeVisible()
  await expect(editor.getByLabel('Response mode')).toHaveValue('single')
  await expect(editor.getByRole('textbox', { name: 'Message', exact: true })).toBeVisible()
  await expect(editor.getByLabel('Default repeat count')).toHaveCount(0)
  await expect(editor.getByLabel('Allow argument count override')).toHaveCount(0)
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
  await expect(editor.getByLabel('Response mode')).toHaveValue('random')
  await expect(editor.locator('textarea')).toHaveValue('Hello, {sender}!\nWelcome, {target}!')
  expect((await editor.boundingBox())!.y).toBeLessThan((await list.boundingBox())!.y)
})

test('built-in fate is exposed and forecast is absent', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  await expect(page.getByText('!fate', { exact: true })).toBeVisible()
  await expect(page.getByText('!forecast', { exact: true })).toHaveCount(0)
})

test('new and existing custom commands save lines, commas, variables and settings', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  await page.getByRole('button', { name: 'New command', exact: true }).click()
  const editor = page.locator('.custom-command-editor')
  await editor.getByLabel('Command name').fill('greet')
  await editor.getByLabel('Aliases, separated by commas').fill('greeting, welcome')
  await editor.getByRole('combobox', { name: 'Permission', exact: true }).selectOption('MODERATOR')
  await editor.getByLabel('Response mode').selectOption('random')
  await editor.getByLabel('Per-user cooldown (seconds)').fill('3')
  await editor.getByLabel('Global cooldown (seconds)').fill('7')
  await editor.locator('textarea').fill('  Hello, {sender}!\n\n Welcome, {arg9}! \n  ')
  await editor.getByRole('button', { name: 'Save command', exact: true }).click()
  await expect(editor).toHaveCount(0)
  expect((await calls(page))[0]).toEqual(['save_custom_command', {
    id: null, name: 'greet', enabled: true, responses: ['Hello, {sender}!', 'Welcome, {arg9}!'],
    permission: 'MODERATOR', per_user_seconds: 3, global_seconds: 7, aliases: ['greeting', 'welcome'],
    response_mode: 'random',
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
    response_mode: 'random',
  })
})

test('Single sends one configured message and mode changes retain response drafts', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  await page.getByRole('button', { name: 'New command', exact: true }).click()
  const editor = page.locator('.custom-command-editor')
  await editor.getByLabel('Command name').fill('greet')
  await editor.getByRole('textbox', { name: 'Message', exact: true }).fill('Hello, {sender}! Join us, {target}.')
  await expect(editor.locator('.custom-mode-example')).toContainText('!greet sends this message once.')
  await editor.getByRole('button', { name: 'Save command', exact: true }).click()
  await expect(editor).toHaveCount(0)
  expect((await calls(page))[0][1]).toMatchObject({
    response_mode: 'single', responses: ['Hello, {sender}! Join us, {target}.'], permission: 'USER',
  })
  expect((await calls(page))[0][1]).not.toHaveProperty('burst_count')
  const row = page.locator('.custom-command-row').filter({ has: page.getByText('!greet', { exact: true }) })
  await row.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(editor.getByLabel('Response mode')).toHaveValue('single')
  await expect(editor.getByRole('textbox', { name: 'Message', exact: true })).toHaveValue('Hello, {sender}! Join us, {target}.')
  await editor.getByLabel('Response mode').selectOption('random')
  await editor.getByRole('textbox', { name: 'Responses', exact: true }).fill('First, {sender}.\nSecond, {target}.')
  await editor.getByLabel('Response mode').selectOption('burst')
  await expect(editor.getByRole('textbox', { name: 'Message', exact: true })).toHaveValue('Hello, {sender}! Join us, {target}.')
  await editor.getByLabel('Response mode').selectOption('random')
  await expect(editor.getByRole('textbox', { name: 'Responses', exact: true })).toHaveValue('First, {sender}.\nSecond, {target}.')
  await expect(editor.getByLabel('Default repeat count')).toHaveCount(0)
  await expect(editor.getByLabel('Allow argument count override')).toHaveCount(0)
})

test('Burst requires moderators and preserves count override, aliases and cooldowns through edit and toggle', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  await page.getByRole('button', { name: 'New command', exact: true }).click()
  const editor = page.locator('.custom-command-editor')
  await editor.getByLabel('Command name').fill('promo')
  await editor.getByLabel('Aliases, separated by commas').fill('discord, join')
  await editor.getByLabel('Per-user cooldown (seconds)').fill('3')
  await editor.getByLabel('Global cooldown (seconds)').fill('7')
  await editor.getByRole('textbox', { name: 'Message', exact: true }).fill('Join us, {sender}: example.com for {target}')
  await editor.getByLabel('Response mode').selectOption('burst')
  const permission = editor.getByRole('combobox', { name: 'Permission', exact: true })
  await expect(permission).toHaveValue('MODERATOR')
  await expect(permission.locator('option')).toHaveText(['moderator', 'broadcaster'])
  await expect(editor.getByLabel('Default repeat count')).toHaveValue('1')
  await expect(editor.getByRole('textbox', { name: 'Responses', exact: true })).toHaveCount(0)
  await editor.getByLabel('Default repeat count').fill('5')
  await editor.getByText('Allow argument count override', { exact: true }).click()
  await expect(editor.getByLabel('Allow argument count override')).toBeChecked()
  await expect(editor.locator('.custom-mode-example')).toContainText('!promo sends this message 5 times concurrently')
  await expect(editor.locator('.custom-burst-controls')).toContainText('!promo 10 sends 10 copies')
  await expect(editor.locator('.custom-burst-controls')).toContainText('target can follow')
  await editor.getByRole('button', { name: 'Save command', exact: true }).click()
  await expect(editor).toHaveCount(0)
  const expected = {
    name: 'promo', responses: ['Join us, {sender}: example.com for {target}'],
    response_mode: 'burst', burst_count: 5, burst_allow_override: true, permission: 'MODERATOR',
    aliases: ['discord', 'join'], per_user_seconds: 3, global_seconds: 7,
  }
  expect((await calls(page))[0][1]).toMatchObject(expected)
  const row = page.locator('.custom-command-row').filter({ has: page.getByText('!promo', { exact: true }) })
  await expect(row.getByText('Burst · 5 copies', { exact: true })).toBeVisible()
  await row.getByRole('button', { name: 'Disable', exact: true }).click()
  await expect(row.getByRole('button', { name: 'Enable', exact: true })).toBeVisible()
  expect((await calls(page))[1][1]).toMatchObject({ ...expected, enabled: false })
  await row.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(editor.getByLabel('Response mode')).toHaveValue('burst')
  await expect(editor.getByLabel('Default repeat count')).toHaveValue('5')
  await expect(editor.getByLabel('Allow argument count override')).toBeChecked()
  await expect(editor.getByLabel('Aliases, separated by commas')).toHaveValue('discord, join')
  await editor.getByLabel('Default repeat count').fill('10')
  await permission.selectOption('BROADCASTER')
  await editor.getByText('Allow argument count override', { exact: true }).click()
  await editor.getByRole('button', { name: 'Save command', exact: true }).click()
  await expect(editor).toHaveCount(0)
  expect((await calls(page))[2][1]).toMatchObject({ ...expected, burst_count: 10, burst_allow_override: false, permission: 'BROADCASTER', enabled: false })
  await row.getByRole('button', { name: 'Enable', exact: true }).click()
  await expect(row.getByRole('button', { name: 'Disable', exact: true })).toBeVisible()
  expect((await calls(page))[3][1]).toMatchObject({ ...expected, burst_count: 10, burst_allow_override: false, permission: 'BROADCASTER', enabled: true })
})

test('invalid Burst counts and too many Random templates never save', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  await page.getByRole('button', { name: 'New command', exact: true }).click()
  const editor = page.locator('.custom-command-editor')
  await editor.getByLabel('Command name').fill('promo')
  await editor.getByRole('textbox', { name: 'Message', exact: true }).fill('Join, {sender}!')
  await editor.getByLabel('Response mode').selectOption('burst')
  const count = editor.getByLabel('Default repeat count')
  const save = editor.getByRole('button', { name: 'Save command', exact: true })
  for (const invalid of ['0', '11', '1.5', '-1', '']) {
    await count.fill(invalid)
    await expect(count).toHaveAttribute('aria-invalid', 'true')
    await expect(save).toBeDisabled()
  }
  expect(await calls(page)).toEqual([])
  for (const valid of ['1', '10']) {
    await count.fill(valid)
    await expect(count).toHaveAttribute('aria-invalid', 'false')
    await expect(save).toBeEnabled()
  }
  await editor.getByLabel('Response mode').selectOption('random')
  await editor.getByRole('textbox', { name: 'Responses', exact: true }).fill(Array.from({ length: 11 }, (_, index) => `Response ${index}`).join('\n'))
  await save.click()
  await expect(page.getByRole('alert')).toContainText('1 to 10 response templates')
  expect(await calls(page)).toEqual([])
})

test('Single and Burst retain drafts when the backend rejects multiline messages', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  await page.getByRole('button', { name: 'New command', exact: true }).click()
  const editor = page.locator('.custom-command-editor')
  await editor.getByLabel('Command name').fill('promo')
  for (const mode of ['single', 'burst']) {
    await editor.getByLabel('Response mode').selectOption(mode)
    const message = editor.getByRole('textbox', { name: 'Message', exact: true })
    await message.fill('Hello, {sender}!\nJoin us, {target}.')
    await editor.getByRole('button', { name: 'Save command', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('single-line messages')
    await expect(editor).toBeVisible()
    await expect(message).toHaveValue('Hello, {sender}!\nJoin us, {target}.')
    await expect(page.getByText('!promo', { exact: true })).toHaveCount(0)
  }
  expect((await calls(page)).map((call: unknown[]) => call[0])).toEqual(['save_custom_command', 'save_custom_command'])
})

test('common variable help stays visible and positional arguments are collapsed', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  await page.getByRole('button', { name: 'New command', exact: true }).click()
  const help = page.locator('.custom-variable-help')
  await expect(help.locator(':scope > .custom-variable-list code')).toHaveText(['{sender}', '{target}', '{args}', '{random_user}'])
  await expect(help.getByText('User who invoked the command.', { exact: true })).toBeVisible()
  await expect(help.getByText('{arg1}', { exact: true })).toBeHidden()
  await expect(help.getByText('{arg9}', { exact: true })).toBeHidden()
  await help.getByText('Advanced variables', { exact: true }).click()
  await expect(help.getByText('{arg1}', { exact: true })).toBeVisible()
  await expect(help.getByText('{arg9}', { exact: true })).toBeVisible()
  await expect(help.locator('details code')).toHaveCount(9)
  await help.getByText('Advanced variables', { exact: true }).click()
  await expect(help.getByText('{arg1}', { exact: true })).toBeHidden()
})

test('existing Random toggle and confirmed delete retain CRUD behavior', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  const row = page.locator('.custom-command-row')
  await row.getByRole('button', { name: 'Disable', exact: true }).click()
  await expect(row.getByRole('button', { name: 'Enable', exact: true })).toBeVisible()
  expect((await calls(page))[0][1]).toMatchObject({
    id: 'synthetic-hello', name: 'hello', enabled: false, response_mode: 'random',
    responses: ['Hello, {sender}!', 'Welcome, {target}!'], aliases: ['hi'],
    permission: 'USER', per_user_seconds: 2, global_seconds: 5,
  })
  expect((await calls(page))[0][1]).not.toHaveProperty('burst_count')
  page.once('dialog', (dialog) => dialog.dismiss())
  await row.getByRole('button', { name: 'Delete', exact: true }).click()
  expect((await calls(page)).filter((call: unknown[]) => call[0] === 'delete_custom_command')).toHaveLength(0)
  page.once('dialog', (dialog) => dialog.accept())
  await row.getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(row).toHaveCount(0)
  await expect(page.getByText('No custom commands yet', { exact: true })).toBeVisible()
  expect((await calls(page))[1]).toEqual(['delete_custom_command', 'synthetic-hello'])
})

test('fate response Apply Save Reset preserves independent settings drafts', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  const card = await expandCommand(page, 'fate')
  const responses = card.locator('.command-response-editor')
  const settings = card.locator('.command-action-footer')
  await expect(responses.locator('textarea')).toHaveCount(1)
  await expect(responses.getByRole('button', { name: 'Apply', exact: true })).toBeDisabled()
  await card.getByRole('combobox').selectOption('MODERATOR')
  await responses.locator('textarea').fill('  Tomorrow, try again.\n\nTake a break, {literal}.\n ')
  await responses.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(responses.getByText('Runtime only', { exact: true })).toBeVisible()
  await expect(card.getByRole('combobox')).toHaveValue('MODERATOR')
  expect((await calls(page))[0]).toEqual(['apply_command_responses', 'fate', ['Tomorrow, try again.', 'Take a break, {literal}.']])
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
  const fate = await expandCommand(page, 'fate')
  const fateResponses = fate.locator('.command-response-editor')
  await fateResponses.locator('textarea').fill('Different forecast')
  await fateResponses.getByRole('button', { name: 'Save', exact: true }).click()
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
  await expect(fateResponses.locator('textarea')).toHaveValue('Different forecast')
})

test('response limits and backend failures retain editable drafts', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html?responseError')
  const fate = await expandCommand(page, 'fate')
  const responses = fate.locator('.command-response-editor')
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
    const fate = await expandCommand(page, 'fate')
    await page.getByRole('button', { name: 'New command', exact: true }).click()
    for (const container of [fate.locator('.command-response-editor'), page.locator('.custom-command-editor')]) {
      const textarea = container.locator('textarea')
      const bounds = (await textarea.boundingBox())!
      const containerBounds = (await container.boundingBox())!
      expect(bounds.height).toBeLessThan(220)
      expect(bounds.x).toBeGreaterThanOrEqual(containerBounds.x)
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(containerBounds.x + containerBounds.width)
    }
    const editor = page.locator('.custom-command-editor')
    for (const mode of ['random', 'burst']) {
      await editor.getByLabel('Response mode').selectOption(mode)
      const bounds = (await editor.locator('textarea').boundingBox())!
      const editorBounds = (await editor.boundingBox())!
      expect(bounds.height).toBeLessThan(220)
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(editorBounds.x + editorBounds.width)
    }
    await editor.getByText('Advanced variables', { exact: true }).click()
    await expect(editor.getByText('{arg9}', { exact: true })).toBeVisible()
    const viewportWidth = page.viewportSize()!.width
    for (const control of await editor.locator('input:not(.switch-input), select, textarea, summary').all()) {
      const bounds = (await control.boundingBox())!
      expect(bounds.x).toBeGreaterThanOrEqual(0)
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(viewportWidth)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewportWidth)
    if (width === 1280) await page.screenshot({ path: 'node_modules/.tmp/commands-wide.png', fullPage: true })
    else await page.screenshot({ path: 'node_modules/.tmp/commands-narrow.png', fullPage: true })
  })
}
