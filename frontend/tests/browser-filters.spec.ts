import { expect, test } from '@playwright/test'
import { expectNoOverflow, navigate, server, signIn } from './browser-fixture'

test('Filters tests active rules, validates a draft and persists corrected rules', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 })
  const api = await server(page)
  await signIn(page)
  await navigate(page, 'Filters')
  await expect(page.getByRole('heading', { name: 'Filters', level: 1 })).toBeVisible()

  const tester = page.locator('#filter-tester')
  await tester.getByRole('textbox').fill('synthetic sample')
  await tester.getByRole('button', { name: 'Test sample' }).click()
  await expect(tester.getByRole('status').getByText('synthetic', { exact: true })).toBeVisible()
  expect(api.calls.find(({ path }) => path === '/v1/filters/test')?.body).toEqual({
    text: 'synthetic sample', source: 'active', payload: null,
  })

  const open = page.getByRole('button', { name: 'Edit filters', exact: true })
  await open.press('Enter')
  const editor = page.getByRole('dialog', { name: 'Edit filters', exact: true })
  const sections = editor.getByRole('navigation', { name: 'Filter sections' })
  const words = editor.getByRole('textbox', { name: 'Blocked words, one rule per line' })
  const patterns = editor.getByRole('textbox', { name: 'Regex patterns, one rule per line' })
  await expect(words).toBeFocused()
  await expect(words).toHaveValue('synthetic')
  await words.fill('new word')
  await sections.getByRole('button', { name: 'Regex patterns' }).press('Space')
  await patterns.fill('[')
  await sections.getByRole('button', { name: 'Blocked words' }).click()
  const save = editor.getByRole('button', { name: 'Save filters', exact: true })
  await save.click()
  await expect(editor.getByRole('alert')).toBeVisible()
  await expect(patterns).toHaveAttribute('aria-invalid', 'true')
  expect(api.calls.find(({ path }) => path === '/v1/filters/save')?.body).toMatchObject({ payload: { patterns: ['['] } })
  await expectNoOverflow(page)

  await patterns.fill('^safe$\n^safe$\n^other$')
  await save.click()
  await expect(editor).toBeHidden()
  await expect(tester.getByRole('status')).toHaveCount(0)
  expect(api.calls.filter(({ path }) => path === '/v1/filters/save').at(-1)?.body).toEqual({
    payload: { words: ['new word'], phrases: [], patterns: ['^safe$', '^safe$', '^other$'] },
  })
  await open.click()
  await expect(words).toHaveValue('new word')
})

test('Filter Tester ignores a result from rules that were replaced during the test', async ({ page }) => {
  await server(page)
  let releaseResult!: () => void
  let started = 0
  const result = new Promise<void>((resolve) => { releaseResult = resolve })
  await page.route('**/v1/filters/test', async (route) => {
    started += 1
    await result
    await route.fulfill({ json: { ok: true, source: 'active', decision: 'BLOCK', category: 'words', rule: 'old word' } })
  })
  await signIn(page)
  await navigate(page, 'Filters')
  const tester = page.locator('#filter-tester')
  const run = tester.getByRole('button', { name: 'Test sample' })
  await tester.getByRole('textbox').fill('old word')
  await run.click()
  await expect(tester.getByRole('button', { name: /Testing/ })).toBeDisabled()
  await expect.poll(() => started).toBe(1)

  await page.getByRole('button', { name: 'Edit filters', exact: true }).click()
  const editor = page.getByRole('dialog', { name: 'Edit filters' })
  await editor.getByRole('textbox', { name: 'Blocked words, one rule per line' }).fill('replacement')
  await editor.getByRole('button', { name: 'Save filters' }).click()
  await expect(editor).toBeHidden()
  const received = page.waitForResponse('**/v1/filters/test')
  releaseResult()
  await received
  await expect(run).toBeEnabled()
  await expect(tester.getByRole('status')).toHaveCount(0)
})

test('Filter Tester reports a regex timeout as a block without a matched rule', async ({ page }) => {
  await server(page)
  await page.route('**/v1/filters/test', (route) => route.fulfill({
    json: { ok: true, source: 'active', decision: 'BLOCK', category: null, rule: null, timed_out: true },
  }))
  await signIn(page)
  await navigate(page, 'Filters')
  const tester = page.locator('#filter-tester')
  await tester.getByRole('textbox').fill('timeout sample')
  await tester.getByRole('button', { name: 'Test sample' }).click()
  await expect(tester.getByRole('status')).toContainText('Regex timeout')
  await expect(tester.getByRole('status')).toContainText('BLOCK')
  await expect(tester.locator('code')).toHaveCount(0)
})

test('the filter editor cancels and then confirms discarding an unsaved draft', async ({ page }) => {
  const api = await server(page)
  await signIn(page)
  await navigate(page, 'Filters')
  const open = page.getByRole('button', { name: 'Edit filters', exact: true })
  const editor = page.getByRole('dialog', { name: 'Edit filters', exact: true })
  const words = editor.getByRole('textbox', { name: 'Blocked words, one rule per line' })
  const discard = page.getByRole('dialog', { name: 'Discard unsaved changes?' })
  await open.press('Enter')
  await words.fill('temporary filter')
  await page.keyboard.press('Escape')
  await discard.getByRole('button', { name: 'Cancel' }).click()
  await expect(words).toHaveValue('temporary filter')
  await editor.getByRole('button', { name: 'Close editor' }).click()
  await discard.getByRole('button', { name: 'Confirm' }).click()
  await expect(editor).toBeHidden()
  await expect(open).toBeFocused()
  await open.press('Enter')
  await expect(words).toHaveValue('synthetic')
  expect(api.calls.some(({ path }) => path === '/v1/filters/save')).toBe(false)
})
