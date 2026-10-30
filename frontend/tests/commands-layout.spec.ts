import { expect, test, type Locator } from '@playwright/test'
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
    const editor = page.locator('.custom-command-editor')
    const builtin = page.locator('#builtin-commands > .command-list')
    const before = await builtin.innerHTML()
    for (const action of ['create', 'edit']) {
      if (action === 'create') await page.getByRole('button', { name: 'New command', exact: true }).click()
      else await page.locator('.custom-command-row').getByRole('button', { name: 'Edit', exact: true }).click()
      for (const mode of ['single', 'random', 'burst']) {
        await selectOption(editor.getByRole('combobox', { name: 'Response type', exact: true }), mode)
        const fields = [
          editor.locator('.custom-name-input'),
          editor.getByRole('textbox', { name: 'Aliases, separated by commas', exact: true }),
          editor.getByRole('combobox', { name: 'Permission', exact: true }),
          editor.getByRole('combobox', { name: 'Response type', exact: true }),
          editor.getByRole('spinbutton', { name: 'Per-user cooldown (seconds)', exact: true }),
          editor.getByRole('spinbutton', { name: 'Global cooldown (seconds)', exact: true }),
        ]
        const bounds = await Promise.all(fields.map(box))
        if (width === 1280) {
          expect(bounds[0].y).toBe(bounds[1].y)
          expect(bounds[0].width).toBeCloseTo(bounds[1].width, -1)
          for (let index = 2; index < 6; index++) {
            expect(bounds[index].y).toBe(bounds[2].y)
            expect(bounds[index].y).toBeGreaterThan(bounds[0].y + bounds[0].height)
            if (index > 2) expect(bounds[index].x).toBeGreaterThan(bounds[index - 1].x)
          }
        } else {
          for (let index = 1; index < bounds.length; index++) {
            expect(bounds[index].y).toBeGreaterThanOrEqual(bounds[index - 1].y + bounds[index - 1].height)
            expect(bounds[index].width).toBeGreaterThan(170)
          }
        }
        const message = await box(editor.locator('textarea'))
        expect(message.y).toBeGreaterThan(bounds[5].y + bounds[5].height)
        const variables = editor.locator('.custom-variable-help')
        expect((await box(variables)).y).toBeGreaterThan(message.y + message.height)
        await expect(variables).not.toHaveAttribute('open')
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
      await editor.getByRole('button', { name: 'Discard and close', exact: true }).click()
      await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
      await expect(editor).toHaveCount(0)
    }
    expect(await builtin.innerHTML()).toBe(before)
  })
}

test('field help supports touch, keyboard and Escape without changing the draft', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  await page.getByRole('button', { name: 'New command', exact: true }).click()
  const editor = page.locator('.custom-command-editor')
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
  await editor.getByRole('button', { name: 'Discard and close', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('random add and remove controls edit the same response draft and enforce the cap', async ({ page }) => {
  await page.goto('/tests/commands.fixture.html')
  await page.locator('.custom-command-row').getByRole('button', { name: 'Edit', exact: true }).click()
  const editor = page.locator('.custom-command-editor')
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
