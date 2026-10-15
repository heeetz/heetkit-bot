import { expect, test, type Locator, type Page } from '@playwright/test'

async function editorScrolls(page: Page) {
  return page.evaluate(() => Reflect.get(window, 'editorScrolls') as string[])
}

async function expectEditorInView(page: Page, editor: Locator, field: Locator) {
  await expect(field).toBeFocused()
  await expect(field).toBeInViewport()
  const top = (await editor.boundingBox())!.y
  expect(top).toBeGreaterThanOrEqual(0)
  expect(top).toBeLessThan(page.viewportSize()!.height / 2)
  if (page.viewportSize()!.width > 760) {
    expect(await page.locator('main').evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
    expect(await page.evaluate(() => window.scrollY)).toBe(0)
  } else {
    const sidebar = (await page.locator('.sidebar').boundingBox())!
    expect(top).toBeGreaterThanOrEqual(sidebar.y + sidebar.height)
    expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(0)
    expect(await page.locator('main').evaluate((element) => element.scrollTop)).toBe(0)
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    Object.assign(window, { editorScrolls: [], toggleFocusOptions: [] })
    const scrollIntoView = HTMLElement.prototype.scrollIntoView
    HTMLElement.prototype.scrollIntoView = function (options) {
      if (this.matches('.custom-command-editor, .command-card')) {
        Reflect.get(window, 'editorScrolls').push(this.id)
      }
      scrollIntoView.call(this, options)
    }
    const focus = HTMLElement.prototype.focus
    HTMLElement.prototype.focus = function (options) {
      if (this.getAttribute('aria-controls') === 'custom-command-editor') {
        Reflect.get(window, 'toggleFocusOptions').push(options)
      }
      focus.call(this, options)
    }
  })
})

for (const width of [1280, 900, 390, 320]) {
  test(`new and existing editors scroll and focus in the application shell at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 720 })
    await page.goto('/tests/commands.fixture.html?shell&extended')
    await page.getByRole('navigation').getByRole('button', { name: 'Commands', exact: true }).click()
    await expect(page.locator('.commands-layout')).toHaveAttribute('aria-busy', 'false')
    const toggle = page.getByRole('button', { name: 'New command', exact: true })
    // Keyboard activation must hand off focus as well as pointer activation.
    await toggle.focus()
    await toggle.press('Enter')
    const editor = page.locator('.custom-command-editor')
    const name = editor.getByLabel('Command name')
    await expectEditorInView(page, editor, name)
    const wrapper = name.locator('..')
    await expect(wrapper).toHaveCSS('outline-style', 'solid')
    await expect(wrapper).toHaveCSS('outline-width', '2px')
    await expect(wrapper).toHaveCSS('outline-color', 'rgb(243, 244, 246)')
    await expect(wrapper).toHaveCSS('border-color', 'rgb(124, 58, 237)')
    await expect(name).toHaveCSS('outline-style', 'none')
    await expect(name).toHaveCSS('border-width', '0px')
    await page.screenshot({ path: `node_modules/.tmp/command-focus-${width}.png` })
    await page.keyboard.press('Tab')
    const mode = editor.getByLabel('Response type')
    await expect(mode).toBeFocused()
    await expect(mode).toHaveCSS('outline-style', 'solid')
    await expect(wrapper).toHaveCSS('outline-style', 'none')
    await page.keyboard.press('Shift+Tab')
    await expect(name).toBeFocused()
    await editor.getByRole('button', { name: 'Discard and close', exact: true }).click()
    await expect(editor).toHaveCount(0)
    await expect(toggle).toBeFocused()
    await page.locator('.custom-command-row').getByRole('button', { name: 'Edit', exact: true }).click()
    await expectEditorInView(page, editor, name)
    await expect(name).toHaveValue('hello')
    await expect(editor.getByRole('textbox', { name: 'Responses', exact: true })).toHaveValue('Hello, {sender}!\nWelcome, {target}!')
    await expect.poll(() => editorScrolls(page)).toEqual(['custom-command-editor', 'custom-command-editor'])
  })

  test(`built-in editors focus Permission only when opened at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 720 })
    await page.goto('/tests/commands.fixture.html?shell&extended')
    await page.getByRole('navigation').getByRole('button', { name: 'Commands', exact: true }).click()
    await expect(page.locator('.commands-layout')).toHaveAttribute('aria-busy', 'false')
    for (const command of ['fate', 'ask']) {
      const editor = page.locator(`#command-editor-${command}`)
      await editor.getByRole('button', { name: `Edit !${command}`, exact: true }).click()
      const permission = editor.getByRole('combobox', { name: 'Permission', exact: true })
      await expectEditorInView(page, editor, permission)
      await expect(permission).toHaveCSS('outline-style', 'solid')
      await permission.selectOption('VIP')
      await editor.getByRole('button', { name: command === 'ask' ? 'Save' : 'Save command', exact: true }).click()
      await expect(page.getByRole('status')).toContainText(`Saved !${command}`)
      await expect(permission).not.toBeFocused()
      await editor.getByRole('button', { name: `Collapse !${command}`, exact: true }).click()
      await expect(permission).toHaveCount(0)
      await expect.poll(() => editorScrolls(page)).toEqual(command === 'fate' ? ['command-editor-fate'] : ['command-editor-fate', 'command-editor-ask'])
    }
  })
}

test('draft confirmation, typing, controls, save and close do not repeat the editor handoff', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 720 })
  await page.goto('/tests/commands.fixture.html?shell')
  await page.getByRole('navigation').getByRole('button', { name: 'Commands', exact: true }).click()
  await page.getByRole('button', { name: 'New command', exact: true }).click()
  const editor = page.locator('.custom-command-editor')
  const name = editor.getByLabel('Command name')
  await expect(name).toBeFocused()
  await name.fill('draft')
  await editor.getByRole('textbox', { name: 'Message', exact: true }).fill('Keep me')
  const edit = page.locator('.custom-command-row').getByRole('button', { name: 'Edit', exact: true })
  await edit.click()
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(edit).toBeFocused()
  await expect(name).toHaveValue('draft')
  await expect.poll(() => editorScrolls(page)).toEqual(['custom-command-editor'])
  await edit.click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expectEditorInView(page, editor, name)
  await expect(name).toHaveValue('hello')
  await editor.getByLabel('Response type').selectOption('single')
  const message = editor.getByRole('textbox', { name: 'Message', exact: true })
  await message.fill('Saved reply')
  await expect(message).toBeFocused()
  const scrollBefore = await page.locator('main').evaluate((element) => element.scrollTop)
  await message.pressSequentially('!')
  expect(await page.locator('main').evaluate((element) => element.scrollTop)).toBe(scrollBefore)
  await editor.getByRole('button', { name: 'Save command', exact: true }).click()
  await expect(editor).toHaveCount(0)
  await expect(page.getByRole('status')).toContainText('Saved !hello')
  await expect(page.getByRole('button', { name: 'New command', exact: true })).toBeFocused()
  await edit.click()
  await expect(name).toBeFocused()
  await editor.getByRole('button', { name: 'Discard and close', exact: true }).click()
  await expect(editor).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'New command', exact: true })).toBeFocused()
  await expect.poll(() => editorScrolls(page)).toEqual(Array(3).fill('custom-command-editor'))
  expect(await page.evaluate(() => Reflect.get(window, 'toggleFocusOptions'))).toEqual(Array(2).fill({ preventScroll: true }))
})

test('editor opening recalculates the sticky navigation offset after resizing', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 720 })
  await page.goto('/tests/commands.fixture.html?shell')
  await page.getByRole('navigation').getByRole('button', { name: 'Commands', exact: true }).click()
  for (const width of [900, 320, 1280]) {
    await page.setViewportSize({ width, height: 720 })
    await page.getByRole('button', { name: 'New command', exact: true }).click()
    const editor = page.locator('.custom-command-editor')
    await expectEditorInView(page, editor, editor.getByLabel('Command name'))
    await editor.getByRole('button', { name: 'Discard and close', exact: true }).click()
    await expect(editor).toHaveCount(0)
  }
})
