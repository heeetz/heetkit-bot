import { expect, test, type Page } from '@playwright/test'

const names = ['Blocked words', 'Blocked phrases', 'Regex patterns'] as const
type FilterSection = typeof names[number]

function dialog(page: Page) {
  return page.getByRole('dialog', { name: 'Edit filters', exact: true })
}

async function openSection(page: Page, section: FilterSection = 'Blocked words') {
  const editor = dialog(page)
  if (!await editor.isVisible()) await page.getByRole('button', { name: 'Edit filters', exact: true }).click()
  await editor.getByRole('navigation', { name: 'Filter sections' }).getByRole('button', { name: section }).click()
  return editor.getByRole('textbox', { name: `${section}, one rule per line` })
}

function save(page: Page) {
  return dialog(page).getByRole('button', { name: 'Save filters', exact: true }).click()
}

async function calls(page: Page) {
  return page.evaluate(() => Reflect.get(window, 'filterCalls')) as Promise<unknown[][]>
}

test('keyboard opens the shared dialog and confirms discarding edits', async ({ page }) => {
  await page.goto('/tests/filters.fixture.html')
  const open = page.getByRole('button', { name: 'Edit filters', exact: true })
  await expect(dialog(page)).toBeHidden()
  await expect(page.getByRole('button', { name: 'Save filters' })).toHaveCount(0)
  await open.press('Enter')
  const nav = dialog(page).getByRole('navigation', { name: 'Filter sections' })
  await expect(nav.getByRole('button')).toHaveText([...names])
  await expect(dialog(page).getByRole('textbox')).toBeFocused()
  const patterns = nav.getByRole('button', { name: 'Regex patterns' })
  await patterns.press('Space')
  await expect(patterns).toHaveAttribute('aria-current', 'true')
  const regex = dialog(page).getByRole('textbox')
  await expect(regex).toHaveAccessibleDescription(/HeetKit skips blank lines and lines beginning with #/)
  const help = dialog(page).getByRole('button', { name: 'Help: Regex example' })
  await expect(help).toHaveText('Regex example')
  const heading = dialog(page).locator('#filters-patterns .filter-editor-heading')
  const ruleCount = heading.getByText('3 rules', { exact: true })
  const [headingBox, countBox] = await Promise.all([heading.boundingBox(), ruleCount.boundingBox()])
  expect(countBox!.x + countBox!.width).toBeCloseTo(headingBox!.x + headingBox!.width, 0)
  await help.press('Enter')
  await expect(dialog(page).getByRole('tooltip')).toContainText('matches messages that start with the word')
  await page.keyboard.press('Escape')
  await regex.fill('^temporary$')
  await page.keyboard.press('Escape')
  const confirmation = page.getByRole('dialog', { name: 'Discard unsaved changes?' })
  await confirmation.getByRole('button', { name: 'Cancel' }).click()
  await expect(regex).toHaveValue('^temporary$')
  await dialog(page).getByRole('button', { name: 'Close editor' }).click()
  await confirmation.getByRole('button', { name: 'Confirm' }).click()
  await expect(open).toBeFocused()
  await expect(await openSection(page, 'Regex patterns')).toHaveValue('^safe$\n^safe$\n\\burl\\b')
  expect(await calls(page)).toEqual([])
})

test('one save preserves regex order and duplicates and normalizes literal lists', async ({ page }) => {
  await page.goto('/tests/filters.fixture.html')
  const words = await openSection(page)
  const wordText = '  alpha\n\n# ignored comment\nalpha\n beta,one  \n'
  await words.fill(wordText)
  await (await openSection(page, 'Blocked phrases')).fill(' hello, world\n\nphrase, with, commas\n hello, world \n')
  const patterns = await openSection(page, 'Regex patterns')
  await expect(patterns).toHaveValue('^safe$\n^safe$\n\\burl\\b')
  await patterns.fill('^saved$\n\n^safe$\n^safe$\n\\burl\\b')
  await openSection(page)
  await expect(words).toHaveValue(wordText)
  await save(page)
  await expect(dialog(page)).toBeHidden()
  await expect(page.getByRole('status')).toContainText('Filters saved.')
  expect(await calls(page)).toEqual([['save_filters', {
    words: ['alpha', '# ignored comment', 'alpha', 'beta,one'],
    phrases: ['hello, world', 'phrase, with, commas', 'hello, world'],
    patterns: ['^saved$', '^safe$', '^safe$', '\\burl\\b'],
  }]])
  await expect(await openSection(page)).toHaveValue('alpha\nbeta,one')
  await expect(await openSection(page, 'Blocked phrases')).toHaveValue('hello, world\nphrase, with, commas')
  await expect(await openSection(page, 'Regex patterns')).toHaveValue('^saved$\n^safe$\n^safe$\n\\burl\\b')
})

test('save errors leave the dialog and draft available', async ({ page }) => {
  await page.goto('/tests/filters.fixture.html?saveError')
  const words = await openSection(page)
  await words.fill('draft one\n\ndraft, two\n')
  await save(page)
  await expect(dialog(page).getByRole('alert')).toHaveText('Synthetic filter save failed.')
  await expect(words).toHaveValue('draft one\n\ndraft, two\n')
  expect((await calls(page)).map((call) => call[0])).toEqual(['save_filters'])
})

test('invalid regex opens its section and identifies the exact line through blanks and comments', async ({ page }) => {
  await page.goto('/tests/filters.fixture.html')
  const regex = await openSection(page, 'Regex patterns')
  await regex.fill('^valid$\n\n# comment\n[')
  await openSection(page)
  await save(page)
  await expect(dialog(page).getByRole('alert')).toContainText('Invalid regular expression.')
  await expect(regex).toBeVisible()
  await expect(regex).toHaveAttribute('aria-invalid', 'true')
  await expect(dialog(page).locator('#filters-patterns .filter-text-errors')).toHaveText('Line 4: Invalid regular expression.')
  await regex.fill('^valid$\n\n\n# comment\n[')
  await expect(dialog(page).locator('#filters-patterns .filter-text-errors')).toHaveText('Line 5: Invalid regular expression.')
  await regex.fill('^valid$\n^corrected$')
  await expect(regex).toHaveAttribute('aria-invalid', 'false')
  await save(page)
  await expect(dialog(page)).toBeHidden()
})

test('file warnings and rule origins are visible and clearing rules saves empty lists', async ({ page }) => {
  await page.goto('/tests/filters.fixture.html?loadWarning')
  const words = await openSection(page)
  await expect(dialog(page).getByRole('status')).toContainText('synthetic words file is unreadable')
  await expect(dialog(page).locator('#filters-words .filter-default-badge')).toHaveText('1 built-in default')
  await expect(dialog(page).locator('#filters-words .filter-local-badge')).toHaveText('1 local rule')
  await words.fill('')
  await (await openSection(page, 'Blocked phrases')).fill('\n  \n')
  await save(page)
  await expect(dialog(page)).toBeHidden()
  expect((await calls(page))[0]).toMatchObject(['save_filters', { words: [], phrases: [] }])
})

test('Filter Tester sends active rules only and clears the result after a save', async ({ page }) => {
  await page.goto('/tests/filters.fixture.html')
  const tester = page.locator('#filter-tester')
  await expect(tester.getByRole('radio')).toHaveCount(0)
  await tester.getByRole('textbox').fill('blocked pattern')
  await tester.getByRole('button', { name: 'Test sample' }).click()
  await expect(tester.getByRole('status')).toContainText('Regex patterns')
  await expect(tester.locator('code')).toHaveText('^safe$')
  await (await openSection(page)).fill('updated word')
  await save(page)
  await expect(dialog(page)).toBeHidden()
  await expect(tester.getByRole('status')).toHaveCount(0)
  await tester.getByRole('textbox').fill('allowed sample')
  await tester.getByRole('button', { name: 'Test sample' }).click()
  await expect(tester.getByRole('status')).toContainText('ALLOW')
  const recorded = await calls(page)
  expect(recorded.filter(([method]) => method === 'test_filters')).toEqual([
    ['test_filters', 'blocked pattern', 'active', null], ['test_filters', 'allowed sample', 'active', null],
  ])
  expect(recorded.map(([method]) => method)).toEqual(['test_filters', 'save_filters', 'test_filters'])
})

test('Filter Tester shows timeout and failed-request results', async ({ page }) => {
  await page.goto('/tests/filters.fixture.html')
  const tester = page.locator('#filter-tester')
  const sample = tester.getByRole('textbox')
  const button = tester.getByRole('button', { name: 'Test sample' })
  await sample.fill('timeout sample')
  await button.click()
  await expect(tester.getByRole('status')).toContainText('Regex timeout')
  await expect(tester.getByRole('status')).toContainText('BLOCK')
  await expect(tester.locator('code')).toHaveCount(0)
  await sample.fill('reject request')
  await button.click()
  await expect(tester.getByRole('alert')).toHaveText('Synthetic bridge rejection.')
})

test('Filter Tester prevents duplicate submissions and drops a stale result', async ({ page }) => {
  await page.goto('/tests/filters.fixture.html')
  const tester = page.locator('#filter-tester')
  await tester.getByRole('textbox').fill('slow block')
  await tester.getByRole('button', { name: 'Test sample' }).evaluate((button: HTMLButtonElement) => {
    button.click()
    button.click()
  })
  await expect(tester.getByRole('button', { name: 'Testing…' })).toBeDisabled()
  await tester.getByRole('textbox').fill('changed while pending')
  await expect(tester.getByRole('button', { name: 'Test sample' })).toBeEnabled()
  await expect(tester.getByRole('status')).toHaveCount(0)
  expect(await calls(page)).toHaveLength(1)
})

for (const width of [1280, 900, 390, 320]) {
  test(`large rule lists fit the grouped editor at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 620 })
    await page.goto('/tests/filters.fixture.html?large')
    let editorHeight = 0
    for (const [section, count] of [['Blocked words', 80], ['Blocked phrases', 65], ['Regex patterns', 19]] as const) {
      const text = await openSection(page, section)
      const height = (await dialog(page).boundingBox())!.height
      expect(height).toBe(560)
      if (editorHeight) expect(height).toBe(editorHeight)
      editorHeight = height
      await expect(dialog(page).getByRole('textbox')).toHaveCount(1)
      await expect(dialog(page).getByText(`${count} rules`, { exact: true })).toBeVisible()
      await expect(text).toBeInViewport()
      await expect(dialog(page).getByRole('button', { name: 'Save filters' })).toBeInViewport()
    }
    const nav = (await dialog(page).getByRole('navigation').boundingBox())!
    const textbox = (await dialog(page).getByRole('textbox').boundingBox())!
    if (width <= 640) expect(nav.y + nav.height).toBeLessThan(textbox.y)
    else expect(nav.x + nav.width).toBeLessThan(textbox.x)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}
