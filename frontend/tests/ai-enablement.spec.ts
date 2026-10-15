import { expect, test, type Page } from '@playwright/test'
import { selectOption } from './select-helpers'

async function navigate(page: Page, name: string) {
  await page.getByRole('navigation').getByRole('button', { name, exact: true }).click()
}

async function toggleOn(page: Page, entry: string) {
  await navigate(page, entry)
  if (entry === 'Commands') {
    await page.getByRole('button', { name: 'Edit !ask', exact: true }).click()
  }
  return page.getByRole('checkbox', { name: entry === 'Commands' ? 'Enable !ask' : 'Enable AI command', exact: true })
}

for (const width of [1280, 390]) {
  for (const entry of ['Dashboard', 'AI', 'Commands']) {
    test(`${entry} saves Ask immediately and synchronizes all views at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await page.goto('/tests/fixture.html?askToggle')
      const toggle = await toggleOn(page, entry)
      await expect(toggle).not.toBeChecked()
      await toggle.press('Space')
      await expect(toggle).toBeChecked()
      await expect(toggle).toBeEnabled()
      for (const view of ['Dashboard', 'AI', 'Commands']) {
        await navigate(page, view)
        if (view === 'Commands') {
          const edit = page.getByRole('button', { name: 'Edit !ask', exact: true })
          if (await edit.isVisible()) await edit.click()
        }
        await expect(page.getByRole('checkbox', { name: view === 'Commands' ? 'Enable !ask' : 'Enable AI command', exact: true })).toBeChecked()
      }
      expect(await page.evaluate(() => Reflect.get(window, 'aiCalls'))).toEqual([['set_ai_enabled', true]])
      // A browser reload exercises presentation startup; Python tests cover a real state reload.
      await page.reload()
      await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).toBeChecked()
    })
  }
}

for (const entry of ['Dashboard', 'AI', 'Commands']) {
  test(`${entry} reports a save failure and retains the saved value`, async ({ page }) => {
    await page.goto('/tests/fixture.html?askToggle&askSaveError')
    const toggle = await toggleOn(page, entry)
    await toggle.press('Space')
    await expect(page.getByRole('alert')).toContainText('Could not save AI command enabled setting.')
    await expect(toggle).not.toBeChecked()
    await expect(toggle).toBeEnabled()
    for (const view of ['Dashboard', 'AI', 'Commands']) {
      await navigate(page, view)
      if (view === 'Commands') {
        const edit = page.getByRole('button', { name: 'Edit !ask', exact: true })
        if (await edit.isVisible()) await edit.click()
      }
      await expect(page.getByRole('checkbox', { name: view === 'Commands' ? 'Enable !ask' : 'Enable AI command', exact: true })).not.toBeChecked()
    }
    await page.reload()
    await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).not.toBeChecked()
  })
}

test('Ask toggles preserve unrelated drafts and keep permissions/cooldowns explicitly saved', async ({ page }) => {
  await page.goto('/tests/fixture.html?askToggle')
  await toggleOn(page, 'Commands')
  const ask = page.locator('#command-details-ask')
  await selectOption(ask.getByRole('combobox'), 'VIP')
  await ask.getByLabel('Global cooldown').fill('42')
  await page.getByRole('button', { name: 'Edit !ping', exact: true }).click()
  const ping = page.locator('#command-details-ping')
  await ping.getByLabel('Per-user cooldown').fill('19')
  await ping.getByRole('checkbox', { name: 'Enable !ping', exact: true }).press('Space')

  await ask.getByRole('checkbox').press('Space')
  await expect(ask.getByRole('checkbox')).toBeChecked()
  await expect(ask.getByRole('combobox')).toHaveAttribute('data-value', 'VIP')
  await expect(ask.getByLabel('Global cooldown')).toHaveValue('42')
  await expect(ping.getByLabel('Per-user cooldown')).toHaveValue('19')
  await expect(ping.getByRole('checkbox')).not.toBeChecked()
  const stored = await page.evaluate(() => window.pywebview!.api.get_commands())
  expect(stored.commands[0]).toMatchObject({ enabled: true, permission: 'USER', cooldown: { global_seconds: 15 } })
  expect(stored.commands[1]).toMatchObject({ enabled: true, cooldown: { per_user_seconds: 3 } })

  await navigate(page, 'AI')
  const personality = page.locator('#ai-personalities')
  await personality.locator('.accordion-trigger').click()
  await personality.locator('textarea').fill('Keep this personality draft')
  await page.getByRole('checkbox', { name: 'Enable AI command', exact: true }).press('Space')
  await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).not.toBeChecked()
  await expect(personality.locator('textarea')).toHaveValue('Keep this personality draft')
  await navigate(page, 'Dashboard')
  await page.getByRole('checkbox', { name: 'Enable AI command', exact: true }).press('Space')
  await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).toBeChecked()
  await navigate(page, 'Commands')
  await expect(ask.getByRole('checkbox')).toBeChecked()
  await expect(ask.getByRole('combobox')).toHaveAttribute('data-value', 'VIP')
  await expect(ask.getByLabel('Global cooldown')).toHaveValue('42')

  // Change it elsewhere while the Commands draft is dirty; Save must use the new enabled value.
  await navigate(page, 'Dashboard')
  await page.getByRole('checkbox', { name: 'Enable AI command', exact: true }).press('Space')
  await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).not.toBeChecked()
  await navigate(page, 'Commands')
  await expect(ask.getByRole('checkbox')).not.toBeChecked()
  await expect(ask.getByRole('combobox')).toHaveAttribute('data-value', 'VIP')
  await expect(ping.getByLabel('Per-user cooldown')).toHaveValue('19')
  await expect(ping.getByRole('checkbox')).not.toBeChecked()
  await ask.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Saved !ask.')
  expect((await page.evaluate(() => Reflect.get(window, 'aiCalls'))).at(-1)).toEqual(['save_command_settings', 'ask', false, 3, 42, 'VIP'])
  await navigate(page, 'AI')
  await expect(personality.locator('textarea')).toHaveValue('Keep this personality draft')
})

test('the enabled value is unchanged while its save is pending', async ({ page }) => {
  await page.goto('/tests/fixture.html?askToggle&askSaveDelay')
  const toggle = await toggleOn(page, 'Commands')
  await toggle.press('Space')
  await expect(toggle).toBeDisabled()
  await expect(toggle).not.toBeChecked()
  await expect(toggle).toBeChecked()
  await expect(toggle).toBeEnabled()
})
