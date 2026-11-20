import { expect, test, type Page } from '@playwright/test'
import { openEditorSection } from './command-editor-helpers'
import { selectOption } from './select-helpers'

async function navigate(page: Page, name: string) {
  await page.getByRole('navigation').getByRole('button', { name, exact: true }).click()
}

async function toggleOn(page: Page, entry: string) {
  await navigate(page, entry)
  if (entry === 'Commands') {
    await selectOption(page.getByRole('combobox', { name: 'Status', exact: true }), 'all')
  }
  return page.getByRole('checkbox', { name: entry === 'Commands' ? 'Enable !ask' : 'Enable AI command', exact: true })
}

for (const width of [1280, 390]) {
  for (const entry of ['Dashboard', 'Commands']) {
    test(`${entry} saves Ask immediately and synchronizes all views at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await page.goto('/tests/fixture.html?askToggle')
      const toggle = await toggleOn(page, entry)
      await expect(toggle).not.toBeChecked()
      await toggle.press('Space')
      await expect(toggle).toBeChecked()
      await expect(toggle).toBeEnabled()
      if (entry === 'Commands') await page.getByRole('button', { name: 'Dismiss message', exact: true }).click()
      for (const view of ['Dashboard', 'AI', 'Commands']) {
        await navigate(page, view)
        if (view === 'Commands') await selectOption(page.getByRole('combobox', { name: 'Status', exact: true }), 'all')
        if (view === 'AI') {
          await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).toHaveCount(0)
          await expect(page.locator('.ai-runtime-values')).toContainText('Enabled')
        } else await expect(page.getByRole('checkbox', { name: view === 'Commands' ? 'Enable !ask' : 'Enable AI command', exact: true })).toBeChecked()
      }
      expect(await page.evaluate(() => Reflect.get(window, 'aiCalls'))).toEqual([entry === 'Commands' ? ['save_builtin_enabled', 'ask', true] : ['set_ai_enabled', true]])
      // A browser reload exercises presentation startup; Python tests cover a real state reload.
      await page.reload()
      await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).toBeChecked()
    })
  }
}

for (const entry of ['Dashboard', 'Commands']) {
  test(`${entry} reports a save failure and retains the saved value`, async ({ page }) => {
    await page.goto('/tests/fixture.html?askToggle&askSaveError')
    const toggle = await toggleOn(page, entry)
    await toggle.press('Space')
    await expect(page.getByRole('alert')).toContainText('Could not save AI command enabled setting.')
    await expect(toggle).not.toBeChecked()
    await expect(toggle).toBeEnabled()
    for (const view of ['Dashboard', 'AI', 'Commands']) {
      await navigate(page, view)
      if (view === 'Commands') await selectOption(page.getByRole('combobox', { name: 'Status', exact: true }), 'all')
      if (view === 'AI') {
        await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).toHaveCount(0)
        await expect(page.locator('.ai-runtime-values')).toContainText('Disabled')
      } else await expect(page.getByRole('checkbox', { name: view === 'Commands' ? 'Enable !ask' : 'Enable AI command', exact: true })).not.toBeChecked()
    }
    await page.reload()
    await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).not.toBeChecked()
  })
}

test('editing Ask saves its draft enabled state together with permissions and cooldowns', async ({ page }) => {
  await page.goto('/tests/fixture.html?askToggle')
  await toggleOn(page, 'Commands')
  await page.getByRole('button', { name: 'Edit !ask', exact: true }).click()
  const ask = page.locator('#command-editor-ask')
  await openEditorSection(ask, 'Access & aliases')
  await selectOption(ask.getByRole('combobox', { name: 'Permission', exact: true }), 'VIP')
  await openEditorSection(ask, 'General')
  await ask.getByLabel('Global cooldown (seconds)', { exact: true }).fill('42')
  await ask.getByRole('checkbox', { name: 'Enable !ask' }).press('Space')
  await expect(ask.getByRole('checkbox')).toBeChecked()
  expect(await page.evaluate(() => Reflect.get(window, 'aiCalls'))).toEqual([])
  await ask.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(ask).toHaveCount(0)
  expect(await page.evaluate(() => Reflect.get(window, 'aiCalls'))).toEqual([['save_command_settings', 'ask', true, 3, 42, 'VIP']])
  await navigate(page, 'Dashboard')
  await expect(page.getByRole('checkbox', { name: 'Enable AI command', exact: true })).toBeChecked()
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
