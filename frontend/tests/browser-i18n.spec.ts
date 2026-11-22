import { expect, test } from '@playwright/test'
import { readdir, readFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'
import { navigate, server, signIn } from './browser-fixture'

const i18nRoot = resolve(process.cwd(), 'src/i18n')
const infrastructure = new Set(['core.ts', 'language.ts', 'errors.ts'])
const placeholder = /\{(\w+)\}/g

test('code-only backend errors and update reasons render in every language', async ({ page }) => {
  await server(page)
  await page.goto('/tests/browser.fixture.html')
  const results = await page.evaluate(async () => {
    const errorsPath = '/src/i18n/errors.ts'
    const corePath = '/src/i18n/core.ts'
    const catalogPath = '/src/i18n/backendErrors.ts'
    const { localizeResult } = await import(errorsPath)
    const { applyLanguage, fmt } = await import(corePath)
    const { backendErrors, validationFields } = await import(catalogPath)
    return ['en', 'uk', 'ru'].map(language => {
      applyLanguage(language)
      const code = 'custom_commands.command_name_alias_already_exists'
      const reason = 'webview_host.publisher_verification_unavailable_install_update_manually'
      const result = localizeResult({
        ok: false, error_code: code, error_params: { name: 'synthetic' },
        automatic_update_reason_code: reason,
        nested: [{ error_code: code, error_params: { name: 'nested' } }],
        validation: { error_code: 'validation.type', error_params: { field: 'enabled', expected: 'boolean' } },
      })
      return {
        error: result.error, expected: fmt(backendErrors[language][code], { name: 'synthetic' }),
        reason: result.automatic_update_reason, expectedReason: backendErrors[language][reason],
        validation: result.validation.error,
        expectedValidation: fmt(backendErrors[language]['validation.type'], {
          field: validationFields[language]['fields.enabled'], expected: validationFields[language]['types.boolean'],
        }),
        nested: result.nested[0].error, expectedNested: fmt(backendErrors[language][code], { name: 'nested' }),
      }
    })
  })
  for (const result of results) {
    expect(result.error).toBe(result.expected)
    expect(result.reason).toBe(result.expectedReason)
    expect(result.nested).toBe(result.expectedNested)
    expect(result.validation).toBe(result.expectedValidation)
  }
})

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

test('switching the Server language preserves a settings draft and persists across reload', async ({ page }) => {
  await server(page)
  await signIn(page)
  await navigate(page, 'Settings')
  await page.getByLabel('Target channel login', { exact: true }).fill('unsaved_channel')
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('combobox', { name: 'Interface language' }).click()
  await page.getByRole('option', { name: 'Українська', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Налаштування', level: 1 })).toBeVisible()
  await expect(page.getByLabel('Логін каналу', { exact: true })).toHaveValue('unsaved_channel')
  expect(await page.evaluate(() => localStorage.getItem('heetkit.ui-language'))).toBe('uk')
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Вхід на сервер' })).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('lang', 'uk')
})
