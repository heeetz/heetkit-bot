import { expect, test } from '@playwright/test'
import { selectOption } from './select-helpers'

test.beforeEach(async ({ page }) => { await page.goto('/tests/select.fixture.html') })

test('keyboard previews skip disabled options; Enter commits and Escape cancels', async ({ page }) => {
  const control = page.getByRole('combobox', { name: 'Example selection' })
  await control.focus()
  await control.press('ArrowDown')
  await expect(control).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByRole('option', { name: 'Alpha', exact: true })).toHaveAttribute('aria-selected', 'true')
  await control.press('ArrowDown')
  const charlie = page.getByRole('option', { name: 'Charlie', exact: true })
  await expect(control).toHaveAttribute('aria-activedescendant', (await charlie.getAttribute('id'))!)
  await expect(page.getByLabel('Committed value')).toHaveText('alpha')
  await control.press('Enter')
  await expect(control).toBeFocused()
  await expect(page.getByLabel('Committed value')).toHaveText('charlie')
  await control.press('Space')
  await control.press('ArrowDown')
  await control.press('Escape')
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await expect(control).toHaveAttribute('data-value', 'charlie')
  await expect(control).toBeFocused()
})

test('Home, End and typeahead navigate a scrolling list without scrolling the panel', async ({ page }) => {
  const control = page.getByRole('combobox', { name: 'Example selection' })
  await control.press('End')
  await expect(page.getByRole('option', { name: 'Model 40' })).toBeInViewport()
  expect(await page.locator('#clipping-panel').evaluate((element) => element.scrollTop)).toBe(0)
  await control.press('Home')
  await expect(page.getByRole('option', { name: 'Alpha', exact: true })).toBeInViewport()
  await control.press('c')
  await control.press('Enter')
  await expect(control).toHaveAttribute('data-value', 'charlie')
  await control.press('Home')
  await control.press('Space')
  await expect(control).toHaveAttribute('data-value', 'alpha')
})

test('pointer selection preserves focus; disabled options cannot commit', async ({ page }) => {
  const control = page.getByRole('combobox', { name: 'Example selection' })
  await control.click()
  const unavailable = page.getByRole('option', { name: 'Bravo (unavailable)' })
  await expect(unavailable).toBeDisabled()
  const bounds = (await unavailable.boundingBox())!
  await page.mouse.click(bounds.x + 10, bounds.y + 10)
  await expect(control).toHaveAttribute('data-value', 'alpha')
  await expect(control).toHaveAttribute('aria-expanded', 'true')
  await page.getByRole('option', { name: 'Charlie', exact: true }).click()
  await expect(control).toBeFocused()
  await expect(control).toHaveAttribute('data-value', 'charlie')
  await expect(page.getByRole('combobox', { name: 'Disabled selection', exact: true })).toBeDisabled()
})

test('Tab and outside click dismiss previews and allow normal focus movement', async ({ page }) => {
  const control = page.getByRole('combobox', { name: 'Example selection' })
  const outside = page.getByRole('button', { name: 'Toggle disabled' })
  await control.click()
  await control.press('ArrowDown')
  await control.press('Tab')
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await expect(outside).toBeFocused()
  await expect(control).toHaveAttribute('data-value', 'alpha')
  await control.click()
  await page.mouse.click(500, 50)
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await outside.click()
  await expect(page.getByRole('listbox')).toHaveCount(0)
  await expect(control).toBeDisabled()
  await expect(outside).toBeFocused()
})

test('menus disappear when a mounted parent hides and empty lists remain dismissible', async ({ page }) => {
  const control = page.getByRole('combobox', { name: 'Example selection' })
  await control.click()
  await page.locator('#clipping-panel').evaluate((element) => { (element as HTMLElement).hidden = true })
  await expect(page.getByRole('listbox')).toHaveCount(0)
  const empty = page.getByRole('combobox', { name: 'Empty selection' })
  await empty.click()
  await expect(page.getByRole('listbox')).toContainText('No options available')
  await empty.press('Escape')
  await expect(empty).toBeFocused()
})

for (const width of [1280, 390, 320]) {
  test(`portalled options avoid clipping, follow scroll and fit a short ${width}px viewport`, async ({ page }) => {
    await page.setViewportSize({ width, height: 400 })
    const control = page.getByRole('combobox', { name: 'Example selection' })
    await control.click()
    const menu = page.getByRole('listbox')
    const panel = (await page.locator('#clipping-panel').boundingBox())!
    const first = (await menu.boundingBox())!
    expect(first.y + first.height).toBeGreaterThan(panel.y + panel.height)
    expect(first.x).toBeGreaterThanOrEqual(8)
    expect(first.x + first.width).toBeLessThanOrEqual(width - 8)
    expect(first.y + first.height).toBeLessThanOrEqual(392)
    const hit = await menu.evaluate((element) => { const r = element.getBoundingClientRect(); return element.contains(document.elementFromPoint(r.x + 10, r.bottom - 10)) })
    expect(hit).toBeTruthy()
    await page.locator('#clipping-panel').evaluate((element) => { element.scrollTop = 12 })
    await expect.poll(async () => Math.round((await menu.boundingBox())!.y)).toBe(Math.round(first.y - 12))
    await control.press('End')
    await expect(page.getByRole('option', { name: 'Model 40' })).toBeInViewport()
    await control.press('Escape')
    await page.setViewportSize({ width, height: 220 })
    await control.click()
    const short = (await menu.boundingBox())!
    expect(short.y).toBeGreaterThanOrEqual(8)
    expect(short.y + short.height).toBeLessThanOrEqual(212)
    await page.screenshot({ path: `node_modules/.tmp/select-${width}.png` })
  })
}

test('visible selection helper commits exactly one value', async ({ page }) => {
  const control = page.getByRole('combobox', { name: 'Example selection' })
  await selectOption(control, 'model-39')
  await expect(control).toHaveAttribute('data-value', 'model-39')
})

test('a menu closes when its trigger scrolls fully behind a clipping ancestor', async ({ page }) => {
  const panel = page.locator('#clipping-panel')
  await panel.evaluate((element) => { (element as HTMLElement).style.marginTop = '180px' })
  await page.getByRole('combobox', { name: 'Example selection' }).click()
  await expect(page.getByRole('listbox')).toBeVisible()
  await panel.evaluate((element) => { element.scrollTop = 100 })
  await expect(page.getByRole('listbox')).toHaveCount(0)
})
