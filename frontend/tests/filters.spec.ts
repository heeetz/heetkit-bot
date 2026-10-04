import { expect, test, type Locator, type Page } from '@playwright/test'

function card(page: Page, category: 'words' | 'phrases' | 'patterns') {
  return page.locator(`.filter-category-card[data-category="${category}"]`)
}

async function expand(page: Page, category: 'words' | 'phrases' | 'patterns') {
  const target = card(page, category)
  const summary = target.locator('.filter-category-summary')
  if (await summary.getAttribute('aria-expanded') === 'false') await summary.press('Enter')
  await expect(summary).toHaveAttribute('aria-expanded', 'true')
  return target
}

async function calls(page: Page) {
  return page.evaluate(() => Reflect.get(window, 'filterCalls')) as Promise<unknown[][]>
}

function details(target: Locator) {
  return target.locator('.filter-category-details')
}

test('filter sections start collapsed with effective counts and expand from the keyboard', async ({ page }) => {
  await page.goto('/tests/filters.fixture.html')
  for (const [category, count] of [['words', '2'], ['phrases', '2'], ['patterns', '3']] as const) {
    const target = card(page, category)
    const summary = target.locator('.filter-category-summary')
    await expect(summary).toHaveAttribute('aria-expanded', 'false')
    await expect(summary.locator('.read-only-badge')).toHaveText(`${count} rules`)
    await expect(details(target)).toBeHidden()
  }
  const words = card(page, 'words')
  await words.locator('.filter-category-summary').focus()
  await words.locator('.filter-category-summary').press('Enter')
  await expect(words.locator('.filter-category-summary')).toHaveAttribute('aria-expanded', 'true')
  await expect(details(words)).toBeVisible()
  await words.locator('.filter-category-summary').press('Space')
  await expect(words.locator('.filter-category-summary')).toHaveAttribute('aria-expanded', 'false')
})

test('multiline drafts preserve raw text while Apply sends trimmed lines and Save reloads backend normalization', async ({ page }) => {
  await page.goto('/tests/filters.fixture.html')
  const words = await expand(page, 'words')
  const phrases = await expand(page, 'phrases')
  const patterns = await expand(page, 'patterns')
  const wordEditor = words.getByRole('textbox', { name: 'Blocked words, one rule per line' })
  await wordEditor.fill('alpha')
  await wordEditor.press('End')
  await wordEditor.press('Enter')
  await wordEditor.press('Enter')
  await wordEditor.pressSequentially('beta,one')
  await expect(wordEditor).toHaveValue('alpha\n\nbeta,one')
  const wordText = '  alpha\n\n# ignored comment\nalpha\n beta,one  \n'
  const phraseText = ' hello, world\n\nphrase, with, commas\n hello, world \n'
  await words.getByRole('textbox', { name: 'Blocked words, one rule per line' }).fill(wordText)
  await phrases.getByRole('textbox', { name: 'Blocked phrases, one rule per line' }).fill(phraseText)
  await words.locator('.filter-category-summary').click()
  await expand(page, 'words')
  await expect(wordEditor).toHaveValue(wordText)
  await expect(words.locator('.filter-category-summary .read-only-badge')).toHaveText('2 rules')
  const patternInputs = patterns.locator('input')
  await patternInputs.nth(0).fill('^saved$')
  await page.getByRole('button', { name: 'Apply for session', exact: true }).click()
  await expect(words.getByRole('textbox', { name: 'Blocked words, one rule per line' })).toHaveValue(wordText)
  await expect(phrases.getByRole('textbox', { name: 'Blocked phrases, one rule per line' })).toHaveValue(phraseText)
  expect((await calls(page))[0]).toEqual(['apply_filters', {
    words: ['alpha', '# ignored comment', 'alpha', 'beta,one'],
    phrases: ['hello, world', 'phrase, with, commas', 'hello, world'],
    patterns: ['^saved$', '^safe$', '\\burl\\b'],
  }])

  await page.getByRole('button', { name: 'Save filters', exact: true }).click()
  await expect(words.getByRole('textbox', { name: 'Blocked words, one rule per line' })).toHaveValue('alpha\nbeta,one')
  await expect(phrases.getByRole('textbox', { name: 'Blocked phrases, one rule per line' })).toHaveValue('hello, world\nphrase, with, commas')
  await expect(patterns.locator('input')).toHaveCount(3)
  await expect(patterns.locator('input').nth(0)).toHaveValue('^saved$')
  await expect(patterns.locator('input').nth(1)).toHaveValue('^safe$')
  await expect(patterns.locator('input').nth(2)).toHaveValue('\\burl\\b')
  expect((await calls(page))[1]).toEqual((await calls(page))[0].map((value, index) => index === 0 ? 'save_filters' : value))
})

test('Save errors keep the multiline draft and Apply and Save remain separate actions', async ({ page }) => {
  await page.goto('/tests/filters.fixture.html?saveError')
  const words = await expand(page, 'words')
  const draft = 'draft one\n\ndraft, two\n'
  await words.getByRole('textbox', { name: 'Blocked words, one rule per line' }).fill(draft)
  await page.getByRole('button', { name: 'Apply for session', exact: true }).click()
  await expect(words.getByRole('textbox', { name: 'Blocked words, one rule per line' })).toHaveValue(draft)
  await page.getByRole('button', { name: 'Save filters', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Synthetic filter save failed.')
  await expect(words.getByRole('textbox', { name: 'Blocked words, one rule per line' })).toHaveValue(draft)
  expect((await calls(page)).map((call) => call[0])).toEqual(['apply_filters', 'save_filters'])
})

test('backend invalid_rule maps past blanks to the exact regex and opens its collapsed category', async ({ page }) => {
  await page.goto('/tests/filters.fixture.html')
  const patterns = await expand(page, 'patterns')
  await patterns.getByRole('button', { name: 'Add rule', exact: true }).click()
  await patterns.getByRole('button', { name: 'Add rule', exact: true }).click()
  const inputs = patterns.locator('input')
  await inputs.nth(1).fill('')
  await inputs.nth(2).fill('[')
  await patterns.locator('.filter-category-summary').press('Space')
  await expect(patterns.locator('.filter-category-summary')).toHaveAttribute('aria-expanded', 'false')
  await page.getByRole('button', { name: 'Save filters', exact: true }).click()
  await expect(patterns.locator('.filter-category-summary')).toHaveAttribute('aria-expanded', 'true')
  await expect(inputs.nth(2)).toHaveAttribute('aria-invalid', 'true')
  await expect(patterns.locator('.filter-rule-error')).toContainText('Invalid regular expression.')
  await expect(page.getByRole('alert')).toContainText('Invalid regular expression.')
})

test('default and local ownership plus file warning remain visible, and no reset action is introduced', async ({ page }) => {
  await page.goto('/tests/filters.fixture.html?loadWarning')
  const words = card(page, 'words')
  await expect(words.getByText('File warning', { exact: true })).toBeVisible()
  await expand(page, 'words')
  await expect(words.locator('.filter-load-warning')).toContainText('synthetic words file is unreadable')
  const phrases = await expand(page, 'phrases')
  await expect(phrases.locator('.filter-text-meta')).toContainText(/Built-in default.*line 1/i)
  await expect(phrases.locator('.filter-text-meta')).toContainText(/Local rule/i)
  const patterns = await expand(page, 'patterns')
  await expect(patterns.locator('.filter-default-badge')).toHaveCount(2)
  await expect(patterns.locator('.filter-local-badge')).toHaveCount(1)
  await phrases.getByRole('textbox').fill('local phrase\nphrase, with, commas')
  await expect(phrases.locator('.filter-default-badge')).toHaveText('0 built-in defaults')
  await expect(phrases.locator('.filter-local-badge')).toHaveText('2 local rules')
  await expect(page.getByRole('button', { name: /Reset/i })).toHaveCount(0)
})

test('invalid multiline text opens its category and identifies the draft line past blanks and comments', async ({ page }) => {
  await page.goto('/tests/filters.fixture.html')
  const words = await expand(page, 'words')
  const editor = words.getByRole('textbox')
  await editor.fill('first\n\n# ignored comment\nbroken\ufffd\nlast')
  await words.locator('.filter-category-summary').click()
  await page.getByRole('button', { name: 'Save filters', exact: true }).click()
  await expect(words.locator('.filter-category-summary')).toHaveAttribute('aria-expanded', 'true')
  await expect(editor).toHaveAttribute('aria-invalid', 'true')
  await expect(words.locator('.filter-text-errors')).toHaveText('Line 4: Rule contains invalid text.')
  await editor.fill('first\n\n\n# ignored comment\nbroken\ufffd\nlast')
  await expect(words.locator('.filter-text-errors')).toHaveText('Line 5: Rule contains invalid text.')
  await editor.fill('first\n\n# ignored comment\ncorrected\nlast')
  await expect(editor).toHaveAttribute('aria-invalid', 'false')
  await page.getByRole('button', { name: 'Save filters', exact: true }).click()
  await expect(editor).toHaveValue('first\ncorrected\nlast')
})

test('clearing both multiline text categories sends empty rule lists', async ({ page }) => {
  await page.goto('/tests/filters.fixture.html')
  const words = await expand(page, 'words')
  const phrases = await expand(page, 'phrases')
  await words.getByRole('textbox', { name: 'Blocked words, one rule per line' }).fill('')
  await phrases.getByRole('textbox', { name: 'Blocked phrases, one rule per line' }).fill('\n  \n')
  await page.getByRole('button', { name: 'Apply for session', exact: true }).click()
  expect((await calls(page))[0]).toMatchObject(['apply_filters', { words: [], phrases: [] }])
  await expect(words.getByRole('textbox', { name: 'Blocked words, one rule per line' })).toHaveValue('')
  await expect(phrases.getByRole('textbox', { name: 'Blocked phrases, one rule per line' })).toHaveValue('\n  \n')
})

for (const width of [1280, 390]) {
  test(`large multiline editors stay compact inside their cards at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto('/tests/filters.fixture.html?large')
    const words = await expand(page, 'words')
    const phrases = await expand(page, 'phrases')
    await expect(words.locator('textarea')).toHaveCount(1)
    await expect(phrases.locator('textarea')).toHaveCount(1)
    await expect(words.locator('.filter-rule-row')).toHaveCount(0)
    await expect(phrases.locator('.filter-rule-row')).toHaveCount(0)
    await expect(words.locator('.filter-category-summary .read-only-badge')).toHaveText('80 rules')
    await expect(phrases.locator('.filter-category-summary .read-only-badge')).toHaveText('65 rules')
    for (const container of [words.locator('.filter-text-editor'), phrases.locator('.filter-text-editor')]) {
      const textarea = container.getByRole('textbox')
      const bounds = (await textarea.boundingBox())!
      const containerBounds = (await container.boundingBox())!
      expect(bounds.height).toBeLessThan(260)
      expect(bounds.x).toBeGreaterThanOrEqual(containerBounds.x)
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(containerBounds.x + containerBounds.width + 1)
    }
    await page.screenshot({ path: `node_modules/.tmp/filters-${width}.png`, fullPage: true })
  })
}
