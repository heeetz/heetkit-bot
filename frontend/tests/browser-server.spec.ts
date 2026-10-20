import { expect, test } from '@playwright/test'
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdir, mkdtemp, readFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { join, resolve } from 'node:path'

for (const host of ['127.0.0.1', '127.0.0.2']) {
  test(`production browser with unrelated cookies signs in and persists edits at ${host}`, async ({ page, context }) => {
    test.setTimeout(60000)
    const repository = resolve(process.cwd(), '..')
    await mkdir(join(repository, 'build'), { recursive: true })
    const profile = await mkdtemp(join(repository, 'build', 'test-b5-browser-'))
    const port = await new Promise<number>((resolvePort, reject) => {
      const socket = createServer()
      socket.once('error', reject)
      socket.listen(0, host, () => {
        const address = socket.address()
        if (!address || typeof address === 'string') return reject(new Error('No test port available.'))
        socket.close((error) => error ? reject(error) : resolvePort(address.port))
      })
    })
    const virtualPython = join(repository, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python')
    const python = process.env.HEETKIT_TEST_PYTHON || (existsSync(virtualPython) ? virtualPython : 'python')
    const child = spawn(python, ['tests/fixtures/management_browser.py', profile, String(port), host], { cwd: repository, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
    let output = ''
    const exited = new Promise<void>((resolveExit) => { child.once('exit', () => resolveExit()) })
    try {
      await new Promise<void>((ready, reject) => {
        const deadline = setTimeout(() => reject(new Error(`Synthetic management server startup timed out: ${output.slice(-1000)}`)), 20000)
        const cleanup = () => clearTimeout(deadline)
        child.once('error', (error) => { cleanup(); reject(error) })
        child.once('exit', (code) => { cleanup(); reject(new Error(`Synthetic management server exited (${code}): ${output.slice(-1000)}`)) })
        child.stderr.on('data', (data: Buffer) => { output += data.toString() })
        child.stdout.on('data', (data: Buffer) => {
          output += data.toString()
          if (output.includes('SYNTHETIC_MANAGEMENT_READY')) { cleanup(); ready() }
        })
      })
      const errors: string[] = []
      page.on('pageerror', (error) => errors.push(error.message))
      // Cookies are scoped to hosts, not ports: simulate another local service.
      await context.addCookies([{ name: 'unrelated', value: 'local-service-cookie', url: `http://${host}:1/` }])
      const url = `http://${host}:${port}/`
      const response = await page.goto(url)
      expect(response?.status()).toBe(200)
      expect(await response!.request().headerValue('cookie')).toContain('unrelated=local-service-cookie')
      expect(response?.headers()['content-security-policy']).toContain("default-src 'none'")
      const loginResponse = page.waitForResponse((reply) => reply.url() === url + 'v1/session')
      await page.getByLabel('Administrator token').fill('synthetic_management_token_' + 'x'.repeat(32))
      await page.getByRole('button', { name: 'Sign in', exact: true }).click()
      expect(await (await loginResponse).request().headerValue('cookie')).toBeNull()
      await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible()
      await page.getByRole('button', { name: 'Filters', exact: true }).click()
      await page.locator('#filters-words .accordion-trigger').click()
      await page.locator('#filters-words textarea').fill('real browser saved rule')
      await page.getByRole('button', { name: 'Save filters', exact: true }).click()
      await expect(page.getByRole('status')).toContainText('Saved filters across restarts.')
      expect(await readFile(join(profile, 'config', 'filters', 'blocked_words.txt'), 'utf8')).toContain('real browser saved rule')
      await page.reload()
      await page.getByLabel('Administrator token').fill('synthetic_management_token_' + 'x'.repeat(32))
      await page.getByRole('button', { name: 'Sign in', exact: true }).click()
      await page.getByRole('button', { name: 'Filters', exact: true }).click()
      await page.locator('#filters-words .accordion-trigger').click()
      await expect(page.locator('#filters-words textarea')).toHaveValue('real browser saved rule')

      await page.getByRole('button', { name: 'Settings', exact: true }).click()
      const transfer = page.getByRole('region', { name: 'Configuration transfer' })
      const downloadPromise = page.waitForEvent('download')
      await transfer.getByRole('button', { name: 'Export configuration', exact: true }).click()
      const download = await downloadPromise
      const downloadPath = await download.path()
      expect(downloadPath).not.toBeNull()
      const exportedArchive = await readFile(downloadPath!)
      expect(exportedArchive.byteLength).toBeGreaterThan(0)
      await transfer.locator('input[type="file"]').setInputFiles({
        name: download.suggestedFilename(), mimeType: 'application/zip', buffer: exportedArchive,
      })
      await expect(transfer.getByRole('heading', { name: 'Import preview' })).toBeVisible()
      await expect(transfer).toContainText('filters')
      await Promise.all([
        page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
        transfer.getByRole('button', { name: 'Confirm import and reload', exact: true }).click(),
      ])
      await expect(page.getByRole('heading', { name: 'Sign in to server' })).toBeVisible()
      await page.getByLabel('Administrator token').fill('synthetic_management_token_' + 'x'.repeat(32))
      await page.getByRole('button', { name: 'Sign in', exact: true }).click()
      await page.getByRole('button', { name: 'Filters', exact: true }).click()
      await page.locator('#filters-words .accordion-trigger').click()
      await expect(page.locator('#filters-words textarea')).toHaveValue('real browser saved rule')
      expect(errors).toEqual([])
      await page.getByRole('button', { name: 'Sign out', exact: true }).click()
      await expect(page.getByRole('heading', { name: 'Sign in to server' })).toBeVisible()
      expect((await context.cookies(url)).find((cookie) => cookie.name === 'unrelated')?.value).toBe('local-service-cookie')
      expect((await context.request.get(url + 'v1/status')).status()).toBe(401)
    } finally {
      child.kill()
      await Promise.race([exited, new Promise<void>((done) => setTimeout(done, 3000))])
    }
  })
}
