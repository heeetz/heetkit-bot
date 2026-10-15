import { expect, test, type Page } from '@playwright/test'
import { selectOption } from './select-helpers'

async function openModels(page: Page) {
  await page.goto('/tests/fixture.html?a4Models&aiAvailable')
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(page.locator('.ai-layout')).toHaveAttribute('aria-busy', 'false')
  const models = page.locator('#ai-models')
  await models.scrollIntoViewIfNeeded()
  return models
}

for (const width of [1280, 1180, 900, 390, 320]) {
  test(`primary and fallback are directly accessible and compact at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const models = await openModels(page)
    const primary = models.getByRole('combobox', { name: 'Primary model', exact: true })
    const fallback = models.getByRole('combobox', { name: 'Fallback model', exact: true })
    await expect(primary).toBeVisible()
    await expect(fallback).toBeVisible()
    await expect(models.locator('details')).toHaveCount(0)
    await expect(models.getByRole('textbox')).toHaveCount(0)
    const left = (await primary.boundingBox())!
    const right = (await fallback.boundingBox())!
    expect(Math.abs(left.width - right.width)).toBeLessThan(1)
    if (width >= 1180) {
      expect(left.y).toBe(right.y)
      expect(left.x + left.width).toBeLessThan(right.x)
    } else if (width <= 390) {
      expect(left.x).toBe(right.x)
      expect(right.y - left.y).toBeLessThan(90)
      expect(right.y).toBeGreaterThan(left.y)
    }
    await models.screenshot({ path: `node_modules/.tmp/models-clean-${width}.png` })
    await fallback.click()
    const menu = page.getByRole('listbox')
    await expect(menu).toBeVisible()
    const bounds = (await menu.boundingBox())!
    expect(bounds.x).toBeGreaterThanOrEqual(8)
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width - 8)
    expect(bounds.y).toBeGreaterThanOrEqual(8)
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(892)
    await page.screenshot({ path: `node_modules/.tmp/models-dropdown-${width}.png` })
    await fallback.press('Escape')
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}

test('custom IDs, required/different validation and explicit save retain their semantics', async ({ page }) => {
  const models = await openModels(page)
  const primary = models.getByRole('combobox', { name: 'Primary model', exact: true })
  const fallback = models.getByRole('combobox', { name: 'Fallback model', exact: true })
  const save = models.getByRole('button', { name: 'Save models', exact: true })
  await selectOption(primary, 'synthetic-fallback')
  await save.click()
  await expect(page.getByRole('alert')).toContainText('Selected and fallback models must be different.')
  await selectOption(primary, '__custom_model__')
  await save.click()
  await expect(page.getByRole('alert')).toContainText('Selected and fallback model IDs are required.')
  await models.getByRole('textbox', { name: 'Primary model custom model ID' }).fill('  custom-primary  ')
  await selectOption(fallback, '__custom_model__')
  await models.getByRole('textbox', { name: 'Fallback model custom model ID' }).fill('  custom-fallback  ')
  expect(await page.evaluate(() => Reflect.get(window, 'aiCalls'))).toEqual([])
  await save.click()
  await expect(page.locator('.feedback-toast[role="status"]')).toContainText('AI model settings saved and active')
  await expect(save).toBeDisabled()
  await expect(models.getByRole('textbox', { name: 'Primary model custom model ID' })).toHaveValue('custom-primary')
  await expect(models.getByRole('textbox', { name: 'Fallback model custom model ID' })).toHaveValue('custom-fallback')
  expect(await page.evaluate(() => Reflect.get(window, 'aiCalls'))).toEqual([['update_ai_provider_settings', 'custom-primary', 'custom-fallback']])
  await page.getByRole('button', { name: 'Settings', exact: true }).click()
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(models.getByRole('textbox', { name: 'Fallback model custom model ID' })).toHaveValue('custom-fallback')
})

test('discovery populates both dropdowns without saving and reports failures without losing a draft', async ({ page }) => {
  const models = await openModels(page)
  await page.evaluate(() => {
    window.pywebview!.api.discover_gemini_models = async () => ({ ok: true, models: ['synthetic-discovered'] })
  })
  const discover = models.getByRole('button', { name: 'Discover models', exact: true })
  await discover.click()
  await selectOption(models.getByRole('combobox', { name: 'Primary model', exact: true }), 'synthetic-discovered')
  const fallback = models.getByRole('combobox', { name: 'Fallback model', exact: true })
  await fallback.click()
  await expect(page.getByRole('option', { name: 'synthetic-discovered', exact: true })).toBeVisible()
  await fallback.press('Escape')
  await page.evaluate(() => {
    window.pywebview!.api.discover_gemini_models = async () => ({ ok: false, error: 'Synthetic discovery failure' })
  })
  await discover.click()
  await expect(page.getByRole('alert')).toContainText('Synthetic discovery failure')
  await expect(models.getByRole('combobox', { name: 'Primary model', exact: true })).toHaveAttribute('data-value', 'synthetic-discovered')
  expect(await page.evaluate(() => Reflect.get(window, 'aiCalls'))).toEqual([])
})

test('a menu closes when switching away from a mounted application page', async ({ page }) => {
  const models = await openModels(page)
  await models.getByRole('combobox', { name: 'Primary model', exact: true }).click()
  await page.getByRole('button', { name: 'Commands', exact: true }).click()
  await expect(page.getByRole('listbox')).toHaveCount(0)
})
