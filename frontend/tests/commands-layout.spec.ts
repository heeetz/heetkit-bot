import { expect, test, type Locator } from '@playwright/test'
import { createEntry, openEditorSection } from './command-editor-helpers'
import { selectOption } from './select-helpers'

async function box(control: Locator) {
  const bounds = await control.boundingBox()
  expect(bounds).not.toBeNull()
  return bounds!
}

for (const width of [1280, 390, 320]) {
  test(`custom create and edit follow the sketch in every mode at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/tests/commands.fixture.html?shell')
    await page.getByRole('navigation').getByRole('button', { name: 'Commands', exact: true }).click()
    const editor = page.locator('#custom-command-editor')
    for (const action of ['create', 'edit']) {
      if (action === 'create') await createEntry(page, 'custom')
      else await page.getByRole('button', { name: 'Edit !hello', exact: true }).click()
      for (const mode of ['single', 'random', 'burst']) {
        await selectOption(editor.getByRole('combobox', { name: 'Response type', exact: true }), mode)
        // Selecting a response type can scroll the fixed-height panel. Measure the layout from its top.
        await editor.locator('.command-dialog-panels').evaluate((panel) => { panel.scrollTop = 0 })
        const name = await box(editor.locator('.custom-name-input'))
        const enabled = await box(editor.locator('.custom-command-enabled'))
        const navigation = await box(editor.getByRole('navigation', { name: 'Editor sections' }))
        expect(name.x + name.width).toBeLessThan(enabled.x)
        expect(Math.abs(name.y + name.height / 2 - enabled.y - enabled.height / 2)).toBeLessThanOrEqual(2)
        if (width === 1280) expect(navigation.x + navigation.width).toBeLessThan(name.x)
        else expect(navigation.y + navigation.height).toBeLessThan(name.y)
        const message = await box(editor.locator('textarea'))
        const cooldown = await box(editor.getByRole('spinbutton', { name: 'Per-user cooldown (seconds)', exact: true }))
        expect(message.y + message.height).toBeLessThan(cooldown.y)
        const variables = editor.locator('.custom-variable-help')
        await expect(variables).not.toHaveAttribute('open')
        const alias = editor.getByRole('textbox', { name: 'Aliases, separated by commas', exact: true })
        await expect(alias).toBeHidden()
        await openEditorSection(editor, 'Access & aliases')
        await expect(alias).toBeVisible()
        await expect(editor.getByRole('combobox', { name: 'Permission', exact: true })).toBeVisible()
        const conditions = editor.getByRole('button', { name: 'Conditions', exact: true })
        if (mode === 'burst') {
          await conditions.click()
          await expect(editor.getByLabel('Default repeat count', { exact: true })).toBeVisible()
        } else await expect(conditions).toHaveCount(0)
        await openEditorSection(editor, 'General')
        await expect(editor.getByRole('heading')).toHaveCount(1)
        await expect(page.getByRole('button', { name: 'Discard draft', exact: true })).toHaveCount(0)
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
        for (const control of await editor.locator('input:not(.switch-input), textarea, button, summary').all()) {
          if (!await control.isVisible()) continue
          const bounds = await box(control)
          expect(bounds.x).toBeGreaterThanOrEqual(0)
          expect(bounds.x + bounds.width).toBeLessThanOrEqual(width)
        }
        if (mode === 'single') {
          await page.locator('main').evaluate((element) => { element.scrollTop = 0 })
          await page.screenshot({ path: `node_modules/.tmp/task8-${action}-${width}.png`, fullPage: width < 1280 })
        }
      }
      await editor.getByRole('button', { name: 'Cancel', exact: true }).click()
      await page.getByRole('dialog', { name: 'Discard unsaved changes?' }).getByRole('button', { name: 'Confirm', exact: true }).click()
      await expect(editor).toHaveCount(0)
    }
  })
}

test('field help supports touch, keyboard and Escape without changing the draft', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  await createEntry(page, 'custom')
  const editor = page.locator('#custom-command-editor')
  const help = editor.getByRole('button', { name: 'Help: Command name', exact: true })
  await help.dispatchEvent('pointerdown', { pointerType: 'touch' })
  await help.click()
  await expect(page.getByRole('tooltip')).toContainText('40 characters')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('tooltip')).toHaveCount(0)
  await expect(help).toBeFocused()
  await help.press('Enter')
  await expect(page.getByRole('tooltip')).toBeVisible()
  await help.press('Escape')
  await expect(help).toBeFocused()
  await editor.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('random add and remove controls edit the same response draft and enforce the cap', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  await page.getByRole('button', { name: 'Edit !hello', exact: true }).click()
  const editor = page.locator('#custom-command-editor')
  const text = editor.getByRole('textbox', { name: 'Responses', exact: true })
  await editor.getByRole('button', { name: 'Add response', exact: true }).click()
  await expect(text).toBeFocused()
  await text.pressSequentially('Third, {sender}!')
  await expect(editor.locator('.custom-random-actions')).toContainText('3 / 30 responses')
  await editor.getByRole('button', { name: 'Remove last response', exact: true }).click()
  await expect(text).toHaveValue('Hello, {sender}!\nWelcome, {target}!')
  await text.fill(Array.from({ length: 30 }, (_, index) => `Reply ${index}`).join('\n'))
  await expect(editor.getByRole('button', { name: 'Add response', exact: true })).toBeDisabled()
  await editor.getByRole('button', { name: 'Save command', exact: true }).click()
  await expect(editor).toHaveCount(0)
})
