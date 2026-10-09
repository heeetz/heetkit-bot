import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const scrollIntoView = HTMLElement.prototype.scrollIntoView
    Object.assign(window, { navigationScrolls: [] })
    HTMLElement.prototype.scrollIntoView = function (options) {
      Reflect.get(window, 'navigationScrolls').push({
        id: this.id,
        hidden: Boolean(this.closest('[hidden]')),
        loading: Boolean(this.closest('[aria-busy="true"]')),
      })
      scrollIntoView.call(this, options)
    }
  })
  await page.goto('/tests/fixture.html')
})

test('the selected top-level page alone expands its submenu, and repeated clicks keep it open', async ({ page }) => {
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await expect(nav.locator('.sidebar-subnav:visible')).toHaveCount(0)
  for (const name of ['Commands', 'Filters', 'AI', 'Settings', 'Dashboard', 'Logs', 'About']) {
    const parent = nav.getByRole('button', { name, exact: true })
    await parent.click()
    await expect(page.getByRole('heading', { name, exact: true, level: 1 })).toBeVisible()
    await expect(parent).toHaveAttribute('aria-current', 'page')
    const hasChildren = ['Commands', 'Filters', 'AI', 'Settings'].includes(name)
    await expect(nav.locator('.sidebar-subnav:visible')).toHaveCount(hasChildren ? 1 : 0)
    await expect(nav.locator('button[aria-expanded="true"]')).toHaveCount(hasChildren ? 1 : 0)
    if (hasChildren) {
      await expect(nav.locator(`#nav-${name}`)).toBeVisible()
      await parent.click()
      await expect(parent).toHaveAttribute('aria-expanded', 'true')
    } else {
      await expect(parent).not.toHaveAttribute('aria-expanded')
    }
  }
})

const destinations = [
  { section: 'Commands', children: [['Your commands', 'custom-commands'], ['Built-in commands', 'builtin-commands']] },
  { section: 'Filters', children: [['Blocked words', 'filters-words'], ['Blocked phrases', 'filters-phrases'], ['Regex patterns', 'filters-patterns']] },
  { section: 'AI', children: [
    ['Runtime', 'ai-runtime'], ['Models and fallback', 'ai-models'], ['Response language', 'ai-language'],
    ['Personalities', 'ai-personalities'], ['Profile instructions', 'ai-profile-instructions'], ['Shared instructions', 'ai-shared-instructions'],
  ] },
  { section: 'Settings', children: [
    ['Desktop behavior', 'desktop-settings'], ['Twitch connection', 'twitch-settings'],
    ['Credentials', 'credential-settings'], ['Data & diagnostics', 'profile-location-settings'],
  ] },
]

for (const { section, children } of destinations) {
  test(`${section} child controls scroll to their real subsections and keep the parent open`, async ({ page }) => {
    const nav = page.getByRole('navigation', { name: 'Main navigation' })
    const parent = nav.getByRole('button', { name: section, exact: true })
    await parent.click()
    for (const [label, id] of children) {
      const child = nav.getByRole('button', { name: label, exact: true })
      await child.click()
      await expect(child).toHaveAttribute('aria-current', 'location')
      await expect(parent).toHaveAttribute('aria-expanded', 'true')
      await expect(nav.locator('.sidebar-subnav:visible')).toHaveCount(1)
      await expect.poll(() => page.evaluate(() => Reflect.get(window, 'navigationScrolls').at(-1))).toEqual({ id, hidden: false, loading: false })
      await expect(page.locator(`#${id}`)).toBeInViewport()
    }
  })
}

test('same-page navigation scrolls again, while a parent click returns to the page top', async ({ page }) => {
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await nav.getByRole('button', { name: 'AI', exact: true }).click()
  const child = nav.getByRole('button', { name: 'Profile instructions', exact: true })
  await child.click()
  await expect(page.locator('#ai-profile-instructions')).toBeInViewport()
  await page.locator('main').evaluate((element) => element.scrollTo({ top: 0 }))
  await expect(page.locator('#ai-profile-instructions')).not.toBeInViewport()
  await child.click()
  await expect(page.locator('#ai-profile-instructions')).toBeInViewport()
  await expect(child).toBeFocused()
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'navigationScrolls').filter((entry: { id: string }) => entry.id === 'ai-profile-instructions').length)).toBe(2)
  await nav.getByRole('button', { name: 'AI', exact: true }).click()
  await expect.poll(() => page.locator('main').evaluate((element) => element.scrollTop)).toBe(0)
  await expect(child).not.toHaveAttribute('aria-current')
  await expect(nav.locator('#nav-AI')).toBeVisible()
})

test('existing cross-page setup actions expand Settings and scroll only after it is visible', async ({ page }) => {
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await page.getByRole('button', { name: 'Configure Twitch', exact: true }).click()
  await expect(nav.locator('#nav-Settings')).toBeVisible()
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'navigationScrolls').at(-1))).toEqual({ id: 'twitch-settings', hidden: false, loading: false })
  await nav.getByRole('button', { name: 'AI', exact: true }).click()
  await page.getByRole('button', { name: 'Add Gemini key', exact: true }).click()
  await expect(nav.locator('#nav-AI')).toBeHidden()
  await expect(nav.locator('#nav-Settings')).toBeVisible()
  await expect(nav.getByRole('button', { name: 'Credentials', exact: true })).toHaveAttribute('aria-current', 'location')
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'navigationScrolls').at(-1))).toEqual({ id: 'credential-settings', hidden: false, loading: false })
  await expect(page.locator('#credential-settings')).toBeInViewport()
})

test('a filter child selected during first load scrolls when its anchor appears', async ({ page }) => {
  await page.evaluate(() => {
    const api = window.pywebview!.api
    const getFilters = api.get_filters
    api.get_filters = () => new Promise((resolve) => {
      Object.assign(window, { releaseFilters: async () => resolve(await getFilters()) })
    })
  })
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await nav.getByRole('button', { name: 'Filters', exact: true }).click()
  await nav.getByRole('button', { name: 'Regex patterns', exact: true }).click()
  await expect(page.locator('#filters-patterns')).toHaveCount(0)
  expect(await page.evaluate(() => Reflect.get(window, 'navigationScrolls'))).toEqual([])
  await page.evaluate(() => Reflect.get(window, 'releaseFilters')())
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'navigationScrolls').at(-1))).toEqual({ id: 'filters-patterns', hidden: false, loading: false })
  await expect(page.locator('#filters-patterns')).toBeInViewport()
})

test('delayed AI content is awaited and pending scroll is cancelled when another page is selected', async ({ page }) => {
  await page.evaluate(() => {
    const api = window.pywebview!.api
    const getPersonalities = api.get_personalities
    api.get_personalities = () => new Promise((resolve) => {
      Object.assign(window, { releaseAI: async () => resolve(await getPersonalities()) })
    })
  })
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await nav.getByRole('button', { name: 'AI', exact: true }).click()
  await nav.getByRole('button', { name: 'Profile instructions', exact: true }).click()
  expect(await page.evaluate(() => Reflect.get(window, 'navigationScrolls'))).toEqual([])
  await page.evaluate(() => Reflect.get(window, 'releaseAI')())
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'navigationScrolls').length)).toBe(1)
  await expect(page.locator('#ai-profile-instructions')).toBeInViewport()

  // Start another first-load navigation, then leave before its content arrives.
  await page.evaluate(() => {
    const api = window.pywebview!.api
    const getFilters = api.get_filters
    api.get_filters = () => new Promise((resolve) => {
      Object.assign(window, { releaseFilters: async () => resolve(await getFilters()) })
    })
  })
  await nav.getByRole('button', { name: 'Filters', exact: true }).click()
  await nav.getByRole('button', { name: 'Blocked words', exact: true }).click()
  await nav.getByRole('button', { name: 'About', exact: true }).click()
  await page.evaluate(() => Reflect.get(window, 'releaseFilters')())
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  expect(await page.evaluate(() => Reflect.get(window, 'navigationScrolls'))).toEqual([{ id: 'ai-profile-instructions', hidden: false, loading: false }])
  await expect(nav.locator('.sidebar-subnav:visible')).toHaveCount(0)
})

test('parents and children work with Space, Enter, Tab and visible keyboard focus', async ({ page }) => {
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  const parent = nav.getByRole('button', { name: 'AI', exact: true })
  await parent.focus()
  await parent.press('Space')
  await expect(parent).toHaveAttribute('aria-expanded', 'true')
  await page.keyboard.press('Tab')
  const child = nav.getByRole('button', { name: 'Runtime', exact: true })
  await expect(child).toBeFocused()
  await expect(child).toHaveCSS('outline-style', 'solid')
  await child.press('Enter')
  await expect(child).toHaveAttribute('aria-current', 'location')
  await expect(parent).toHaveAttribute('aria-expanded', 'true')
  await page.keyboard.press('Tab')
  const playground = nav.getByRole('button', { name: 'Playground', exact: true })
  await expect(playground).toBeFocused()
  await playground.press('Enter')
  await expect(playground).toHaveAttribute('aria-current', 'location')
  await expect(page.locator('#ai-playground')).toBeInViewport()
})

test('dismissing a load error does not block navigation to the existing page cards', async ({ page }) => {
  await page.goto('/tests/fixture.html?languageLoadError')
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await nav.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('AI language settings are unavailable.')
  await page.getByRole('alert').getByRole('button', { name: 'Dismiss message' }).click()
  await expect(page.locator('.ai-layout')).toHaveAttribute('aria-busy', 'false')
  await nav.getByRole('button', { name: 'Profile instructions', exact: true }).click()
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'navigationScrolls').at(-1))).toEqual({ id: 'ai-profile-instructions', hidden: false, loading: false })
  await expect(page.locator('#ai-profile-instructions')).toBeInViewport()
})

for (const width of [1280, 390]) {
  test(`expanded navigation fits the existing layout at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const nav = page.getByRole('navigation', { name: 'Main navigation' })
    await nav.getByRole('button', { name: 'AI', exact: true }).click()
    await nav.getByRole('button', { name: 'Profile instructions', exact: true }).click()
    await expect(page.locator('#ai-profile-instructions')).toBeInViewport()
    if (width < 761) {
      const sidebarBounds = (await page.locator('.sidebar').boundingBox())!
      await expect.poll(async () => (await page.locator('#ai-profile-instructions').boundingBox())!.y).toBeGreaterThanOrEqual(sidebarBounds.y + sidebarBounds.height)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}
