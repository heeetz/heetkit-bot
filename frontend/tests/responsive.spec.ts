import { expect, test, type Locator, type Page } from '@playwright/test'

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
    for (const element of document.querySelectorAll<HTMLElement>('main input, main select, main textarea, main button, main summary')) {
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

async function expectActionBefore(first: Locator, second: Locator) {
  const firstBox = (await first.boundingBox())!
  const secondBox = (await second.boundingBox())!
  expect(firstBox.y < secondBox.y || (Math.abs(firstBox.y - secondBox.y) < 1 && firstBox.x < secondBox.x)).toBe(true)
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
      await expect(page.getByRole('button', { name: 'Add Gemini key', exact: true })).toBeVisible()
    }

    const language = page.locator('#ai-language')
    await language.locator('.accordion-caret').click()
    const formColumns = await gridColumns(language.locator('.language-fields'), ':scope > label')
    expect(formColumns).toBe(viewport.width <= 760 || contentWidth <= 621 ? 1 : 2)

    const models = page.locator('#ai-models')
    const discover = models.getByRole('button', { name: 'Discover models', exact: true })
    const playground = models.getByRole('button', { name: 'Open Playground', exact: true })
    const save = models.getByRole('button', { name: 'Save models', exact: true })
    await expect(models.getByRole('button')).toHaveText(['Discover models', 'Open Playground', 'Save models'])
    await expectActionBefore(discover, playground)
    await expectActionBefore(playground, save)
    const playgroundBox = (await playground.boundingBox())!
    const saveBox = (await save.boundingBox())!
    expect(playgroundBox.y).toBeCloseTo(saveBox.y, 0)
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
  await expect(nav.getByRole('button', { name: 'Built-in restrictions', exact: true })).toBeInViewport()

  await nav.getByRole('button', { name: 'Profile instructions', exact: true }).click()
  const card = page.locator('#ai-profile-instructions')
  const trigger = card.locator('.accordion-trigger')
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
