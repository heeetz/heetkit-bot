import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { navigate, server, signIn } from './browser-fixture'

test('transfers an archive through export, cancel, preview and confirmed import', async ({ page }) => {
  await server(page)
  const archive = Buffer.from('synthetic settings archive')
  const archiveBase64 = archive.toString('base64')
  const apply: unknown[] = []
  let previews = 0
  let failApply = true
  await page.route(/\/v1\/ops\/(export_configuration|preview_configuration_import|apply_configuration_import)$/, async (route) => {
    const name = { export_configuration: 'export', preview_configuration_import: 'preview', apply_configuration_import: 'import' }[
      new URL(route.request().url()).pathname.split('/').at(-1)!]
    const body = route.request().postDataJSON()
    if (name === 'export') {
      return route.fulfill({ json: { ok: true, filename: '../unsafe.zip', archive_base64: archiveBase64 } })
    }
    if (name === 'preview') {
      previews += 1
      expect(body).toEqual({ archive_base64: archiveBase64 })
      return route.fulfill({ json: {
        ok: true, preview_token: 'preview-' + previews, application_version: '1.3.0', format_version: 1,
        sections: [{ name: 'Custom commands', incoming_count: 3, current_count: 1, details: ['<script>sample</script>'] }],
      } })
    }
    apply.push(body)
    if (failApply) {
      failApply = false
      return route.fulfill({ json: { ok: false, error: 'Synthetic import failure' } })
    }
    return route.fulfill({ json: { ok: true } })
  })
  await signIn(page)
  await navigate(page, 'Settings')
  const transfer = page.getByRole('region', { name: 'Configuration transfer' })
  const incoming = transfer.getByLabel('Choose ZIP to import')
  const download = page.waitForEvent('download')
  await transfer.getByRole('button', { name: 'Export configuration' }).click()
  const file = await download
  expect(file.suggestedFilename()).toBe('heetkit-configuration.zip')
  expect(await readFile((await file.path())!)).toEqual(archive)

  const upload = (buffer: Buffer) => incoming.setInputFiles({
    name: file.suggestedFilename(), mimeType: 'application/zip', buffer,
  })
  await upload(Buffer.alloc(1024 * 1024 + 1))
  await expect(transfer.getByRole('alert')).toBeVisible()
  expect(previews).toBe(0)

  const preview = transfer.getByRole('heading', { name: 'Import preview' })
  await upload(archive)
  await expect(preview).toBeVisible()
  const commands = transfer.getByRole('row', { name: /Custom commands/ })
  await expect(commands.getByRole('cell', { name: '3', exact: true })).toBeVisible()
  await expect(transfer.getByText('<script>sample</script>', { exact: false })).toBeVisible()
  await expect(transfer.locator('script')).toHaveCount(0)
  await transfer.getByRole('button', { name: 'Cancel import' }).click()
  await expect(preview).toHaveCount(0)
  expect(apply).toEqual([])

  await upload(archive)
  const confirm = transfer.getByRole('button', { name: 'Confirm import and reload' })
  await confirm.click()
  await expect(transfer.getByRole('alert')).toBeVisible()
  await expect(preview).toBeVisible()
  await Promise.all([page.waitForNavigation(), confirm.click()])
  await expect(page.getByRole('heading', { name: 'Sign in to server' })).toBeVisible()
  expect(apply).toEqual(Array(2).fill({ archive_base64: archiveBase64, preview_token: 'preview-2', confirmed: true }))
})
