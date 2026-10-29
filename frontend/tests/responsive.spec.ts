import { expect, test, type Locator, type Page } from '@playwright/test'
import { selectOption } from './select-helpers'

type ViewportCase = {
  width: number
  height: number
  query: string
  dashboardStatus: 'Not configured' | 'Stopped' | 'Connected'
  aiAvailable: boolean
}

const viewports: ViewportCase[] = [
  { width: 900, height: 620, query: 'statusDelay', dashboardStatus: 'Not configured', aiAvailable: false },
  { width: 1180, height: 760, query: 'configured&cachedToken&aiAvailable&connection=stopped', dashboardStatus: 'Stopped', aiAvailable: true },
  { width: 1440, height: 900, query: 'configured&cachedToken&connection=connected', dashboardStatus: 'Connected', aiAvailable: false },
  { width: 1920, height: 1080, query: 'configured&cachedToken&aiAvailable&connection=stopped', dashboardStatus: 'Stopped', aiAvailable: true },
  { width: 2560, height: 1440, query: 'configured&cachedToken&aiAvailable&connection=connected', dashboardStatus: 'Connected', aiAvailable: true },
  { width: 761, height: 900, query: 'configured&cachedToken&connection=connected', dashboardStatus: 'Connected', aiAvailable: false },
  { width: 760, height: 900, query: '', dashboardStatus: 'Not configured', aiAvailable: false },
  { width: 390, height: 844, query: 'configured&cachedToken&aiAvailable&connection=stopped', dashboardStatus: 'Stopped', aiAvailable: true },
  { width: 320, height: 800, query: 'configured&cachedToken&connection=connected', dashboardStatus: 'Connected', aiAvailable: false },
]

async function gridColumns(grid: Locator, childSelector: string) {
  return grid.locator(childSelector).evaluateAll((children) => {
    const visible = children
      .map((child) => child.getBoundingClientRect())
      .filter((rect) => rect.width > 0 && rect.height > 0)
    return new Set(visible.map((rect) => Math.round(rect.left * 10) / 10)).size
  })
}

function expectedColumns(viewportWidth: number, contentWidth: number, wideThreshold: number) {
  if (viewportWidth <= 760) return 1
  if (contentWidth >= wideThreshold - 1) return wideThreshold === 1000 ? 4 : 3
  return contentWidth >= 480 - 1 ? 2 : 1
}

async function expectNoHorizontalOverflow(page: Page) {
  const failures = await page.evaluate(() => {
    const visible = (element: Element) => {
      const rect = element.getBoundingClientRect()
      const style = getComputedStyle(element)
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none'
    }
    const messages: string[] = []
    const name = (element: Element) => {
      const html = element as HTMLElement
      return `${element.tagName.toLowerCase()}${html.id ? `#${html.id}` : ''}${html.className && typeof html.className === 'string' ? `.${html.className.trim().replace(/\s+/g, '.')}` : ''}`
    }
    for (const element of document.querySelectorAll<HTMLElement>('main, .page-content, main .card, .feedback-toast')) {
      if (visible(element) && element.scrollWidth > element.clientWidth + 1) {
        messages.push(`${name(element)} scrolls ${element.scrollWidth}/${element.clientWidth}`)
      }
    }
    for (const element of document.querySelectorAll<HTMLElement>('main input, main [role="combobox"], main textarea, main button, main summary')) {
      if (!visible(element) || element.closest('.feedback-toast')) continue
      const container = element.closest<HTMLElement>('.card') ?? element.closest<HTMLElement>('.page-content')
      if (!container) continue
      const bounds = element.getBoundingClientRect()
      const parent = container.getBoundingClientRect()
      if (bounds.left < parent.left - 1 || bounds.right > parent.right + 1) {
        messages.push(`${name(element)} escapes ${name(container)} (${bounds.left}/${bounds.right} vs ${parent.left}/${parent.right})`)
      }
    }
    if (document.documentElement.scrollWidth > window.innerWidth + 1) {
      messages.push(`document scrolls ${document.documentElement.scrollWidth}/${window.innerWidth}`)
    }
    return messages
  })
  expect(failures).toEqual([])
}

async function expectContentAligned(page: Page) {
  const main = (await page.locator('main').boundingBox())!
  const content = (await page.locator('.page-content').boundingBox())!
  const header = (await page.locator('.page-content > header').boundingBox())!
  expect(content.width).toBeLessThanOrEqual(1281)
  expect(header.x).toBeCloseTo(content.x, 0)
  expect(header.width).toBeCloseTo(content.width, 0)
  const leftInset = content.x - main.x
  const rightInset = main.x + main.width - content.x - content.width
  expect(Math.abs(leftInset - rightInset)).toBeLessThanOrEqual(18)
  return content.width
}

test('column and form thresholds handle fractional CSS content widths', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await page.goto('/tests/fixture.html?configured&aiAvailable')
  for (const [width, columns] of [[720, 3], [719.5, 2], [480, 2], [479.5, 1]]) {
    await page.locator('.page-content').evaluate((element, width) => {
      element.style.width = `${width}px`
    }, width)
    expect(await gridColumns(page.locator('.dashboard-grid'), ':scope > .dashboard-card')).toBe(columns)
  }
  await page.getByRole('navigation').getByRole('button', { name: 'AI', exact: true }).click()
  await expect(page.locator('.ai-layout')).toHaveAttribute('aria-busy', 'false')
  for (const [width, columns] of [[1000, 4], [999.5, 2], [480, 2], [479.5, 1]]) {
    await page.locator('.page-content').evaluate((element, width) => {
      element.style.width = `${width}px`
    }, width)
    expect(await gridColumns(page.locator('#ai-runtime'), ':scope > .ai-state-panel')).toBe(columns)
    await expectNoHorizontalOverflow(page)
  }
  const language = page.locator('#ai-language')
  await language.locator('.accordion-caret').click()
  for (const [width, columns] of [[620.5, 2], [620, 1]]) {
    await page.locator('.page-content').evaluate((element, width) => {
      element.style.width = `${width}px`
    }, width)
    expect(await gridColumns(language.locator('.language-fields'), ':scope > label')).toBe(columns)
  }
})

for (const viewport of viewports) {
  test(`content-width layout fits ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await page.goto(`/tests/fixture.html?${viewport.query}`)

    await expect(page.locator('.dashboard-grid > .dashboard-card').first().getByRole('heading')).toHaveText(viewport.dashboardStatus)
    const contentWidth = await expectContentAligned(page)
    expect(await gridColumns(page.locator('.dashboard-grid'), ':scope > .dashboard-card'))
      .toBe(expectedColumns(viewport.width, contentWidth, 720))
    await expectNoHorizontalOverflow(page)
    if ([900, 1440, 2560].includes(viewport.width)) {
      await page.screenshot({ path: `node_modules/.tmp/a5-dashboard-${viewport.width}.png` })
    }

    await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'AI', exact: true }).click()
    const ai = page.locator('.ai-layout')
    await expect(ai).toHaveAttribute('aria-busy', 'false')
    await expect(page.locator('#ai-runtime .ai-state-panel')).toHaveCount(4)
    expect(await gridColumns(page.locator('#ai-runtime'), ':scope > .ai-state-panel'))
      .toBe(expectedColumns(viewport.width, contentWidth, 1000))
    if (viewport.aiAvailable) {
      await expect(page.locator('#ai-runtime')).toContainText('Configured for requests')
    } else {
      await expect(page.locator('#ai-runtime')).toContainText('Unavailable')
      await expect(page.getByRole('button', { name: 'Manage AI setup', exact: true })).toBeVisible()
      await page.getByRole('button', { name: 'Manage AI setup', exact: true }).click()
      await expect(page.locator('#ai-models')).toBeInViewport()
    }

    const language = page.locator('#ai-language')
    await language.locator('.accordion-caret').click()
    const formColumns = await gridColumns(language.locator('.language-fields'), ':scope > label')
    expect(formColumns).toBe(viewport.width <= 760 || contentWidth <= 621 ? 1 : 2)

    const nav = page.getByRole('navigation', { name: 'Main navigation' })
    await nav.getByRole('button', { name: 'AI setup', exact: true }).click()
    const models = page.locator('#ai-models')
    await expect(models.locator('.accordion-trigger')).toHaveAttribute('aria-expanded', 'true')
    await expect(models.getByRole('button', { name: 'Discover primary models', exact: true })).toBeVisible()
    await expect(models.getByRole('button', { name: 'Save AI setup', exact: true })).toBeVisible()
    await expect(nav.getByRole('button', { name: 'Playground', exact: true })).toBeVisible()
    await expect(page.locator('#ai-playground')).toHaveCount(1)
    await expectNoHorizontalOverflow(page)
    if ([900, 1440, 2560].includes(viewport.width)) {
      await page.locator('#ai-runtime').screenshot({ path: `node_modules/.tmp/a5-ai-state-${viewport.width}.png` })
    }
    for (const section of ['Commands', 'Filters', 'Logs', 'Settings', 'About']) {
      await page.getByRole('navigation').getByRole('button', { name: section, exact: true }).click()
      await expect(page.locator('main [aria-busy="true"]:visible')).toHaveCount(0)
      await expectContentAligned(page)
      await expectNoHorizontalOverflow(page)
    }
  })
}

test('two-field settings respond to page content width across the desktop and top-navigation boundary', async ({ page }) => {
  await page.setViewportSize({ width: 1180, height: 760 })
  await page.goto('/tests/fixture.html?configured&cachedToken')
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'Settings', exact: true }).click()
  const twitch = page.locator('#twitch-settings')
  await twitch.locator('.accordion-caret').click()
  await expect(twitch.locator('.twitch-field-pair').first()).toBeVisible()

  for (const width of [1180, 900, 761, 760, 390]) {
    await page.setViewportSize({ width, height: 760 })
    const contentWidth = (await page.locator('.page-content').boundingBox())!.width
    for (const pair of await twitch.locator('.twitch-field-pair').all()) {
      const fields = pair.locator(':scope > .form-field')
      if (await fields.count() < 2) continue
      expect(await gridColumns(pair, ':scope > .form-field')).toBe(width <= 760 || contentWidth <= 621 ? 1 : 2)
    }
    await expectNoHorizontalOverflow(page)
  }
})

test('long model, personality, alias and draft values wrap inside the 761px content boundary', async ({ page }) => {
  await page.setViewportSize({ width: 761, height: 900 })
  await page.goto('/tests/fixture.html?a4Models&aiAvailable&askToggle')
  await page.evaluate(() => {
    const api = window.pywebview!.api
    const getStatus = api.get_ai_status
    api.get_ai_status = async () => ({ ...await getStatus(), model: `model_${'unbroken'.repeat(16)}` })
    const getPersonalities = api.get_personalities
    api.get_personalities = async () => ({ ...await getPersonalities(), active_personality: `personality_${'unbroken'.repeat(12)}` })
    const getCommands = api.get_commands
    api.get_commands = async () => {
      const response = await getCommands()
      response.commands = response.commands.map((command) => command.name === 'ping'
        ? { ...command, aliases: Array.from({ length: 5 }, (_, index) => `alternate_command_${index}_${'x'.repeat(20)}`) }
        : command)
      return response
    }
  })
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await nav.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(page.locator('.ai-layout')).toHaveAttribute('aria-busy', 'false')
  const profile = page.locator('#ai-profile-instructions')
  await profile.locator('.accordion-caret').click()
  await profile.locator('textarea').fill(`draft_${'unbroken'.repeat(30)}`)
  await expect(profile.locator('.dirty-badge')).toHaveText('Edited')
  await expectNoHorizontalOverflow(page)

  await nav.getByRole('button', { name: 'Commands', exact: true }).click()
  const ping = page.locator('#command-editor-ping')
  await expect(ping).toContainText('alternate_command_4')
  await ping.locator('.accordion-caret').click()
  await expect(ping.getByLabel('Aliases, separated by commas')).toHaveValue(/alternate_command_4/)
  await expectNoHorizontalOverflow(page)
})

test('loading and a long error remain contained at the 320px minimum width', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 })
  await page.goto('/tests/fixture.html?statusDelay&languageLoadError')
  await expect(page.locator('.dashboard-hero')).toContainText('Loading…')
  await expectNoHorizontalOverflow(page)
  await expect(page.locator('.dashboard-card').first().getByRole('heading')).toHaveText('Not configured')

  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'AI', exact: true }).click()
  const alert = page.getByRole('alert')
  await expect(alert).toContainText('AI language settings are unavailable.')
  await alert.locator('span').evaluate((element) => {
    element.textContent = `Synthetic_${'unbroken_error'.repeat(24)}`
  })
  await expectNoHorizontalOverflow(page)
})

test('the desktop menu scrolls independently at minimum height and keyboard help stays in the window', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 620 })
  await page.addInitScript(() => {
    const scrollIntoView = HTMLElement.prototype.scrollIntoView
    Object.assign(window, { lastNavigationScroll: '' })
    HTMLElement.prototype.scrollIntoView = function (options) {
      scrollIntoView.call(this, options)
      Reflect.set(window, 'lastNavigationScroll', this.id)
    }
  })
  await page.goto('/tests/fixture.html')
  const sidebar = page.locator('.sidebar')
  const brand = sidebar.locator('.brand')
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await nav.getByRole('button', { name: 'AI', exact: true }).click()
  const brandBefore = (await brand.boundingBox())!
  expect(await nav.evaluate((element) => getComputedStyle(element).overflowY)).toMatch(/auto|scroll/)
  expect(await nav.evaluate((element) => element.scrollHeight)).toBeGreaterThan(await nav.evaluate((element) => element.clientHeight))
  await nav.evaluate((element) => { element.scrollTop = element.scrollHeight })
  expect(await nav.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
  expect((await brand.boundingBox())!.y).toBeCloseTo(brandBefore.y, 0)
  await expect(nav.getByRole('button', { name: 'AI access', exact: true })).toBeInViewport()

  await nav.getByRole('button', { name: 'Profile instructions', exact: true }).click()
  const card = page.locator('#ai-profile-instructions')
  const trigger = card.locator('.accordion-trigger')
  // Complete navigation's automatic expansion and scroll before testing deliberate toggles.
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'lastNavigationScroll'))).toBe('ai-profile-instructions')
  await trigger.focus()
  await expect(trigger).toHaveAttribute('aria-expanded', 'true')
  await trigger.press('Enter')
  await expect(trigger).toHaveAttribute('aria-expanded', 'false')
  await trigger.press('Space')
  await expect(trigger).toHaveAttribute('aria-expanded', 'true')
  const help = card.getByRole('button', { name: 'Help: Profile instructions', exact: true })
  await help.focus()
  const tooltip = page.getByRole('tooltip')
  await expect(tooltip).toBeVisible()
  const bounds = (await tooltip.boundingBox())!
  expect(bounds.x).toBeGreaterThanOrEqual(12)
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(888)
  expect(bounds.y).toBeGreaterThanOrEqual(12)
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(608)
  await help.press('Escape')
  await expect(tooltip).toHaveCount(0)
  await expect(help).toBeFocused()
})

for (const width of [1440, 1180, 900, 390, 320]) {
  test(`AI editor, key and access actions share clean footer rows at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/tests/fixture.html?configured&aiAvailable&a4Models')
    const nav = page.getByRole('navigation')
    await nav.getByRole('button', { name: 'AI', exact: true }).click()
    await expect(page.locator('.ai-layout')).toHaveAttribute('aria-busy', 'false')
    for (const id of ['ai-personalities', 'ai-profile-instructions', 'ai-language']) {
      const card = page.locator(`#${id}`)
      await card.locator('.accordion-caret').click()
      const footer = card.locator('.ai-editor-footer')
      const playground = footer.getByRole('button', { name: 'Open Playground' })
      await expect(playground).toBeVisible()
      if (width >= 1180) {
        const controls = await footer.getByRole('button').all()
        const boxes = await Promise.all(controls.map(async (control) => (await control.boundingBox())!))
        for (let index = 0; index < boxes.length; index++) {
          expect(boxes[index].y).toBeCloseTo(boxes[0].y, 0)
          expect(boxes[index].height).toBeCloseTo(boxes[0].height, 0)
          if (index) expect(boxes[index - 1].x + boxes[index - 1].width).toBeLessThanOrEqual(boxes[index].x)
        }
      }
      await expectNoHorizontalOverflow(page)
      if (width === 1180 || width === 320) {
        await footer.screenshot({ path: `node_modules/.tmp/ui-${id}-footer-${width}.png` })
      }
    }
    const language = page.locator('#ai-language')
    await selectOption(language.getByLabel('Response language mode'), 'limited')
    await expect(language.locator('.ai-editor-footer')).toContainText('Unsaved draft')
    await language.getByRole('button', { name: 'Help: AI response language' }).focus()
    await expect(page.getByRole('tooltip')).toContainText('Prompt guidance cannot perfectly guarantee')
    await page.keyboard.press('Escape')

    const access = page.locator('#ai-blocked-users')
    const settings = access.getByRole('button', { name: 'Edit AI command access and cooldowns' })
    await expect(access.locator('.ai-access-footer')).toContainText('No blocked AI users.')
    expect((await settings.boundingBox())!.y).toBeGreaterThanOrEqual((await access.getByLabel('Twitch username').boundingBox())!.y + 40)
    await expectNoHorizontalOverflow(page)
    if (width === 1180) await access.screenshot({ path: 'node_modules/.tmp/ui-ai-access-1180.png' })

    await nav.getByRole('button', { name: 'AI', exact: true }).click()
    await nav.getByRole('button', { name: 'AI setup', exact: true }).click()
    const key = page.locator('#ai-models')
    const row = key.locator('.ai-connection-row').filter({ has: page.getByLabel('gemini API key', { exact: true }) })
    const input = row.getByLabel('gemini API key', { exact: true })
    await input.fill('synthetic-key-draft')
    if (width >= 1180) {
      const controls = await row.locator('.row-actions').getByRole('button').all()
      const boxes = await Promise.all(controls.map(async (control) => (await control.boundingBox())!))
      for (let index = 0; index < boxes.length; index++) {
        expect(boxes[index].y).toBeCloseTo(boxes[0].y, 0)
        expect(boxes[index].height).toBeCloseTo(boxes[0].height, 0)
        if (index) expect(boxes[index - 1].x + boxes[index - 1].width).toBeLessThanOrEqual(boxes[index].x)
      }
      const inputBox = (await input.boundingBox())!
      expect(inputBox.height).toBeCloseTo(boxes[0].height, 0)
      expect(inputBox.y).toBeCloseTo(boxes[0].y, 0)
    }
    await expectNoHorizontalOverflow(page)
    if (width === 1180 || width === 320) await row.screenshot({ path: `node_modules/.tmp/ui-gemini-key-${width}.png` })
    await key.getByRole('button', { name: 'Help: Provider keys', exact: true }).focus()
    await expect(page.getByRole('tooltip')).toContainText('generation access may differ')
    await page.keyboard.press('Escape')
    await expect(input).toHaveValue('synthetic-key-draft')
  })
}
