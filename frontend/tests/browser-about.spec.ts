import { expect, test } from '@playwright/test'
import { navigate, server, signIn } from './browser-fixture'

test('Server About shows application details and opens the project repository safely', async ({ page }) => {
  await page.addInitScript(() => {
    window.open = (...args) => { Reflect.set(window, 'openedLink', args); return null }
  })
  const api = await server(page)
  await signIn(page)
  await navigate(page, 'About')
  await expect(page.getByRole('heading', { name: 'About', level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'HeetKit', level: 2 })).toBeVisible()
  await expect(page.getByText('1.3.0', { exact: false })).toBeVisible()
  expect(api.calls.some(({ path }) => path === '/v1/ops/get_about_info')).toBe(true)
  await expect(page.getByRole('button', { name: 'Check for updates' })).toHaveCount(0)
  await page.getByRole('button', { name: /GitHub repository/ }).click()
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'openedLink'))).toEqual([
    'https://github.com/heeetz/heetkit-bot', '_blank', 'noopener,noreferrer',
  ])
})
