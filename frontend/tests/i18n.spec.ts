import { expect, test, type Page } from '@playwright/test'
import { readdir, readFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'

const i18nRoot = resolve(process.cwd(), 'src/i18n')
const infrastructure = new Set(['core.ts', 'language.ts', 'errors.ts'])
const placeholder = /\{(\w+)\}/g

type Node = string | readonly string[] | Record<string, unknown>

function placeholders(value: string): string[] {
  return [...value.matchAll(placeholder)].map((match) => match[1]).sort()
}

function isPlural(value: unknown): value is { one: string; other: string; few?: string; many?: string } {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
    && typeof (value as { one?: unknown }).one === 'string' && typeof (value as { other?: unknown }).other === 'string'
}

function compare(path: string, english: Node, translated: unknown, language: string, problems: string[]) {
  if (typeof english === 'string') {
    if (typeof translated !== 'string' || !translated.trim()) { problems.push(`${language} ${path}: missing text`); return }
    if (placeholders(english).join() !== placeholders(translated).join()) problems.push(`${language} ${path}: placeholders differ`)
    if (/<\/?[a-z][^>]*>/i.test(translated)) problems.push(`${language} ${path}: HTML in catalog`)
    if (language === 'ru' && /[ёЁ]/.test(translated)) problems.push(`ru ${path}: uses ё`)
    return
  }
  if (Array.isArray(english)) {
    if (!Array.isArray(translated) || translated.length !== english.length) { problems.push(`${language} ${path}: list length differs`); return }
    english.forEach((item, index) => compare(`${path}[${index}]`, item, translated[index], language, problems))
    return
  }
  if (isPlural(english)) {
    if (!isPlural(translated)) { problems.push(`${language} ${path}: plural forms missing`); return }
    const expected = new Set(Object.values(english).flatMap((form) => placeholders(String(form))))
    for (const form of language === 'en' ? ['one', 'other'] : ['one', 'few', 'many', 'other'] as const) {
      const text = (translated as Record<string, unknown>)[form]
      if (typeof text !== 'string' || !text.trim()) { problems.push(`${language} ${path}.${form}: missing plural form`); continue }
      for (const name of placeholders(text)) if (!expected.has(name)) problems.push(`${language} ${path}.${form}: unknown {${name}}`)
    }
    return
  }
  if (!translated || typeof translated !== 'object') { problems.push(`${language} ${path}: missing group`); return }
  const englishKeys = Object.keys(english).sort()
  const translatedKeys = Object.keys(translated).sort()
  if (englishKeys.join() !== translatedKeys.join()) problems.push(`${language} ${path}: keys differ`)
  for (const key of englishKeys) compare(path ? `${path}.${key}` : key, (english as Record<string, unknown>)[key] as Node, (translated as Record<string, unknown>)[key], language, problems)
}

test('every catalog has the same keys, placeholders and plural forms in en, uk and ru', async () => {
  const files = (await readdir(i18nRoot)).filter((name) => name.endsWith('.ts') && !infrastructure.has(name))
  expect(files.length).toBeGreaterThan(5)
  const problems: string[] = []
  let catalogs = 0
  for (const file of files) {
    const module = await import(pathToFileURL(join(i18nRoot, file)).href) as Record<string, unknown>
    for (const [name, value] of Object.entries(module)) {
      const catalog = value as { en?: Node; uk?: unknown; ru?: unknown }
      if (!catalog || typeof catalog !== 'object' || !catalog.en || !catalog.uk || !catalog.ru) continue
      catalogs += 1
      for (const language of ['uk', 'ru'] as const) compare(`${file}:${name}`, catalog.en, catalog[language], language, problems)
    }
  }
  expect(catalogs).toBeGreaterThanOrEqual(files.length - files.filter((file) => file.endsWith('.en.ts')).length)
  expect(problems).toEqual([])
})

test('converted components keep user-visible text in catalogs', async () => {
  // Literal JSX text or text attributes in a component are a regression; data, ids and
  // technical tokens are allowed. Reviewed exceptions live here with a reason.
  const allowed = new Map<string, string>([
    ['HeetKit', 'product name'], ['EN', 'language code'], ['UA', 'language code'], ['RU', 'language code'],
    ['×', 'close glyph'], ['✓', 'check glyph'], ['—', 'empty value'], ['·', 'separator'], ['/', 'separator'],
    ['!ask', 'command name'], ['!help', 'command name'], ['/mod bot_login', 'Twitch chat command'], ['bot_login', 'placeholder token'],
    ['bot_name', 'Twitch login example'], ['channel_name', 'Twitch login example'], ['Client ID', 'Twitch term kept in English'],
    ['^hello\\b', 'regex example'],
  ])
  const sources: string[] = []
  const walk = async (directory: string) => {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name)
      if (entry.isDirectory()) await walk(path)
      else if (entry.name.endsWith('.tsx')) sources.push(path)
    }
  }
  await walk(resolve(process.cwd(), 'src'))
  const problems: string[] = []
  const attributes = new Set(['aria-label', 'title', 'placeholder', 'alt', 'label', 'description', 'helpLabel'])
  const visible = (text: string) => /[A-Za-z]{2,}/.test(text) && !allowed.has(text)
  for (const path of sources) {
    const source = ts.createSourceFile(path, await readFile(path, 'utf-8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
    const relative = path.slice(process.cwd().length + 1)
    const visit = (node: ts.Node) => {
      if (ts.isJsxText(node)) {
        const text = node.getText().replace(/\s+/g, ' ').trim()
        if (text && visible(text)) problems.push(`${relative}: text "${text.slice(0, 60)}"`)
      } else if (ts.isJsxAttribute(node) && node.initializer && ts.isStringLiteral(node.initializer)) {
        const name = node.name.getText()
        if (attributes.has(name) && visible(node.initializer.text)) problems.push(`${relative}: ${name}="${node.initializer.text.slice(0, 60)}"`)
      }
      ts.forEachChild(node, visit)
    }
    visit(source)
  }
  expect(problems).toEqual([])
})

async function openDesktop(page: Page, query = '') {
  await page.goto(`/tests/fixture.html?configured&authorized&aiAvailable&connection=connected${query}`)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
}

const switcher = (page: Page) => page.getByRole('navigation').locator('.language-switcher').getByRole('combobox')

async function pickLanguage(page: Page, name: string) {
  await switcher(page).click()
  await page.getByRole('option', { name, exact: true }).click()
}

test('Desktop switches language in place, keeps edits and restores the saved choice', async ({ page }) => {
  await page.setViewportSize({ width: 1180, height: 760 })
  await openDesktop(page)
  const nav = page.getByRole('navigation')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await nav.getByRole('button', { name: 'Logs', exact: true }).click()
  const search = page.getByRole('textbox', { name: 'Search' })
  await search.fill('synthetic draft')

  await expect(switcher(page)).toHaveText('EN')
  await pickLanguage(page, 'Українська')
  await expect(page.locator('html')).toHaveAttribute('lang', 'uk')
  await expect(switcher(page)).toHaveText('UA')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Логи')
  await expect(nav.getByRole('button', { name: 'Про програму', exact: true })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Пошук' })).toHaveValue('synthetic draft')
  expect(await page.evaluate(() => Reflect.get(window, 'languageCalls'))).toEqual(['uk'])

  // Keyboard: open the menu, move to Русский and choose it.
  await switcher(page).focus()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(switcher(page)).toHaveText('RU')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Логи')
  await expect(nav.getByRole('button', { name: 'Настройки', exact: true })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Поиск' })).toHaveValue('synthetic draft')

  await page.reload()
  await expect(nav.getByRole('button', { name: 'Главная', exact: true })).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('lang', 'ru')
  await nav.getByRole('button', { name: 'Настройки', exact: true }).click()
  const card = page.locator('#interface-settings')
  await expect(card.getByRole('heading', { name: 'Язык интерфейса' })).toBeVisible()
  await card.getByRole('combobox', { name: 'Язык интерфейса' }).click()
  await page.getByRole('option', { name: 'English' }).click()
  await expect(nav.getByRole('button', { name: 'Settings', exact: true })).toBeVisible()
  expect(await page.evaluate(() => sessionStorage.getItem('uiLanguage'))).toBe('en')
})

test('backend errors with a code appear in the selected language', async ({ page }) => {
  await openDesktop(page, '&askToggle&askSaveError')
  await pickLanguage(page, 'Українська')
  await page.getByRole('checkbox', { name: 'Увімкнути команду AI' }).press('Space')
  await expect(page.getByRole('alert')).toContainText('Не вдалося зберегти стан команди AI.')
})

test('a failed Desktop save keeps the new language and says it was not saved', async ({ page }) => {
  await openDesktop(page, '&languageSaveError')
  await page.getByRole('navigation').getByRole('button', { name: 'Settings', exact: true }).click()
  await page.locator('#interface-settings').getByRole('combobox', { name: 'Interface language' }).click()
  await page.getByRole('option', { name: 'Русский' }).click()
  await expect(page.locator('#interface-settings').getByRole('alert')).toHaveText('Язык изменен, но HeetKit не смог его сохранить. После перезапуска он сбросится.')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Настройки')
})

for (const language of ['uk', 'ru'] as const) {
  for (const width of [1180, 390]) {
    test(`${language} navigation and Dashboard fit at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 })
      await page.addInitScript((value) => sessionStorage.setItem('uiLanguage', value), language)
      await openDesktop(page)
      await expect(page.locator('html')).toHaveAttribute('lang', language)
      const nav = page.getByRole('navigation')
      await expect(nav.getByRole('button', { name: language === 'uk' ? 'Головна' : 'Главная', exact: true })).toBeVisible()
      await expect(switcher(page)).toBeVisible()
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow).toBeLessThanOrEqual(0)
      if (width > 760) {
        // About and the switcher share one row without widening the navigation.
        const about = await nav.getByRole('button', { name: language === 'uk' ? 'Про програму' : 'О программе', exact: true }).boundingBox()
        const group = await switcher(page).boundingBox()
        const sidebar = await page.locator('.sidebar').boundingBox()
        expect(about && group && sidebar).toBeTruthy()
        expect(Math.abs(about!.y + about!.height / 2 - (group!.y + group!.height / 2))).toBeLessThan(4)
        expect(group!.x + group!.width).toBeLessThanOrEqual(sidebar!.x + sidebar!.width)
        expect(sidebar!.width).toBe(230)
        // The About label is shown in full, not cut with an ellipsis.
        expect(await page.locator('.nav-about > button').evaluate((button) => button.scrollWidth <= button.clientWidth)).toBe(true)
      }
    })
  }
}

test('Server sign-in uses the language saved in this browser', async ({ page }) => {
  await page.goto('/tests/browser.fixture.html')
  await expect(page.getByRole('heading', { name: 'Sign in to server' })).toBeVisible()
  await page.getByRole('combobox', { name: 'Interface language' }).click()
  await page.getByRole('option', { name: 'Українська', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Вхід на сервер' })).toBeVisible()
  await expect(page.getByLabel('Токен адміністратора')).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('heetkit.ui-language'))).toBe('uk')
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Вхід на сервер' })).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('lang', 'uk')
})
