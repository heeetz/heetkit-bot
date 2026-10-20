import { expect, test, type Page } from '@playwright/test'

const archive = Buffer.from('synthetic zip bytes')

async function selectArchive(page: Page, contents = archive) {
  await page.getByLabel('Choose ZIP to import').setInputFiles({
    name: 'portable-settings.zip',
    mimeType: 'application/zip',
    buffer: contents,
  })
}

for (const unsafe of [false, true]) {
  test(`desktop export downloads the ${unsafe ? 'safe fallback' : 'backend'} filename`, async ({ page }) => {
    await page.goto(`/tests/fixture.html?settings${unsafe ? '&configurationUnsafeFilename' : ''}`)
    const downloadPromise = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Export configuration', exact: true }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toBe(unsafe ? 'heetkit-configuration.zip' : 'heetkit-config-1.2.3.zip')
    await expect(page.getByRole('status')).toContainText('Portable configuration exported.')
    expect(await page.evaluate(() => Reflect.get(window, 'configurationTransferCalls'))).toEqual([['export']])
  })
}

for (const outcome of ['saved', 'cancelled'] as const) {
  test(`desktop native export reports ${outcome} without starting a Blob download`, async ({ page }) => {
    await page.addInitScript(() => {
      Object.assign(window, { configurationBlobDownloads: 0 })
      URL.createObjectURL = () => {
        Object.assign(window, { configurationBlobDownloads: Reflect.get(window, 'configurationBlobDownloads') + 1 })
        return 'blob:synthetic'
      }
    })
    const flag = outcome === 'saved' ? 'configurationExportSaved' : 'configurationExportCancelled'
    await page.goto(`/tests/fixture.html?settings&${flag}`)
    await page.getByRole('button', { name: 'Export configuration', exact: true }).click()
    await expect(page.getByRole('status')).toContainText(outcome === 'saved'
      ? 'Portable configuration saved.'
      : 'Configuration export cancelled. No file was saved.')
    expect(await page.evaluate(() => Reflect.get(window, 'configurationBlobDownloads'))).toBe(0)
    expect(await page.evaluate(() => Reflect.get(window, 'configurationTransferCalls'))).toEqual([['export']])
  })
}

test('desktop import previews replacements and cancellation makes no changes', async ({ page }) => {
  await page.goto('/tests/fixture.html?settings')
  const transfer = page.getByRole('region', { name: 'Configuration transfer' })
  await selectArchive(page)
  await expect(transfer.getByRole('heading', { name: 'Import preview' })).toBeVisible()
  await expect(transfer).toContainText('HeetKit 1.2.3 · format 1')
  const customCommands = transfer.getByRole('row').filter({ hasText: 'Custom commands' })
  await expect(customCommands.getByRole('cell').nth(1)).toHaveText('3')
  await expect(customCommands.getByRole('cell').nth(2)).toHaveText('1')
  const personalities = transfer.getByRole('row').filter({ hasText: 'Personalities' })
  await expect(personalities.getByRole('cell').nth(1)).toHaveText('2')
  await expect(personalities.getByRole('cell').nth(2)).toHaveText('4')
  await expect(transfer).toContainText('hello · quote · <script>plain text</script>')
  await expect(transfer.locator('script')).toHaveCount(0)
  await expect(transfer).toContainText('Active command and AI settings will be applied immediately.')
  await expect(transfer).toContainText('Twitch identity, authorization, secrets and private databases.')
  expect(await page.evaluate(() => Reflect.get(window, 'configurationTransferCalls'))).toEqual([
    ['preview', archive.toString('base64')],
  ])
  await transfer.getByRole('button', { name: 'Cancel import', exact: true }).click()
  await expect(transfer.getByRole('heading', { name: 'Import preview' })).toHaveCount(0)
  await expect(transfer.getByRole('status')).toContainText('No settings were changed.')
  expect(await page.evaluate(() => sessionStorage.getItem('configurationImportApplied'))).toBeNull()
})

test('desktop import requires confirmation, sends its preview token and reloads after success', async ({ page }) => {
  await page.goto('/tests/fixture.html?settings')
  await selectArchive(page)
  const confirm = page.getByRole('button', { name: 'Confirm import and reload', exact: true })
  await expect(confirm).toBeVisible()
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
    confirm.click(),
  ])
  expect(await page.evaluate(() => sessionStorage.getItem('configurationImportApplied'))).toBe('1')
  await expect(page.getByRole('heading', { name: 'Configuration transfer' })).toBeVisible()
})

test('desktop import keeps its preview on apply failure and does not reload', async ({ page }) => {
  await page.goto('/tests/fixture.html?settings&configurationImportError')
  await selectArchive(page)
  await page.getByRole('button', { name: 'Confirm import and reload', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Synthetic import failure.')
  await expect(page.getByRole('heading', { name: 'Import preview' })).toBeVisible()
  expect(await page.evaluate(() => sessionStorage.getItem('configurationImportApplied'))).toBeNull()
  const calls = await page.evaluate(() => Reflect.get(window, 'configurationTransferCalls'))
  expect(calls.at(-1)).toEqual(['apply', archive.toString('base64'), 'synthetic-preview-token', true])
})

test('desktop import reports preview failures and blocks archives over 1 MiB before the bridge', async ({ page }) => {
  await page.goto('/tests/fixture.html?settings&configurationPreviewError')
  await selectArchive(page)
  await expect(page.getByRole('alert')).toContainText('Synthetic preview failure.')
  await expect(page.getByRole('heading', { name: 'Import preview' })).toHaveCount(0)

  await page.goto('/tests/fixture.html?settings')
  await selectArchive(page, Buffer.alloc(1024 * 1024 + 1))
  await expect(page.getByRole('alert')).toContainText('must be 1 MiB or smaller')
  expect(await page.evaluate(() => Reflect.get(window, 'configurationTransferCalls'))).toEqual([])
})

test('desktop transfer disables concurrent actions while an archive is being previewed', async ({ page }) => {
  await page.goto('/tests/fixture.html?settings&configurationPreviewDelay')
  const transfer = page.getByRole('region', { name: 'Configuration transfer' })
  const input = transfer.locator('input[type="file"]')
  await input.setInputFiles({ name: 'portable-settings.zip', mimeType: 'application/zip', buffer: archive })
  await expect(page.getByRole('button', { name: 'Export configuration', exact: true })).toBeDisabled()
  await expect(input).toBeDisabled()
  await expect(page.getByText('Checking archive…', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Import preview' })).toBeVisible()
})
