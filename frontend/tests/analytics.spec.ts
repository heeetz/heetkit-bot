import { expect, test } from '@playwright/test'
import { analyticsFlow, mockAnalytics } from './analytics-helpers'

for (const width of [1280, 320]) test(`Analytics Desktop windows, charts, privacy controls, balance and memory at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 })
  await page.goto('/tests/fixture.html?a4Models&aiAvailable&askToggle')
  const mock = await mockAnalytics(page, true)
  const names = await page.getByRole('navigation', { name: 'Main navigation' }).locator('.nav-section > button').allTextContents()
  expect(names.indexOf('Analytics')).toBe(names.indexOf('Logs') + 1)
  expect(names.indexOf('Settings')).toBe(names.indexOf('Analytics') + 1)
  await analyticsFlow(page, mock, width, 'desktop')
})

test('leaderboards switch together and ignore a delayed response from the previous channel', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/tests/fixture.html?a4Models&aiAvailable&askToggle')
  await mockAnalytics(page, true)
  let releaseOld!: () => void
  const oldAllowed = new Promise<void>((resolve) => { releaseOld = resolve })
  await page.route('**/synthetic-leaderboards/*', async (route) => {
    const channel = new URL(route.request().url()).pathname.split('/').at(-1)
    if (channel === '100') await oldAllowed
    const ranking = {
      period: '2026-11', started_at: '2026-11-01T00:00:00Z',
      ends_at: null, partial: true, rows: [{ place: 1, nickname: `viewer${channel}`, messages: 12345 }],
    }
    await route.fulfill({ json: { ok: true, leaderboards: { channel_id: channel, connected: true, stream_status: 'live',
      exclusions: [], month: ranking, stream: ranking } } })
  })
  await page.evaluate(() => {
    const api = window.pywebview!.api
    const original = api.get_app_status.bind(api)
    const channel = () => document.documentElement.dataset.leaderboardChannel ?? '100'
    api.get_app_status = async () => ({ ...await original(), leaderboard_channel_id: channel() })
    api.get_leaderboards = async () => (await fetch(`/synthetic-leaderboards/${channel()}`)).json()
  })
  const firstRequest = page.waitForRequest('**/synthetic-leaderboards/100')
  await page.getByRole('button', { name: 'Analytics', exact: true }).click()
  await firstRequest
  await page.evaluate(() => { document.documentElement.dataset.leaderboardChannel = '200' })
  const stream = page.getByRole('table', { name: 'Stream top 10 chatters', exact: true })
  const month = page.getByRole('table', { name: 'Monthly top 10 chatters', exact: true })
  await expect(stream).toContainText('viewer200')
  await expect(month).toContainText('12345')
  const oldResponse = page.waitForResponse('**/synthetic-leaderboards/100')
  releaseOld()
  await oldResponse
  await expect(stream).not.toContainText('viewer100')
  await expect(month).toContainText('viewer200')
  expect(await stream.getByRole('columnheader').allTextContents()).toEqual(['Place', 'Nickname', 'Messages'])
  expect(await page.locator('#analytics-chatters').evaluate((row) => row.previousElementSibling?.className)).toBe('analytics-cards')
  await expect(page.getByText('Times shown in UTC (GMT+0). Monthly reset: 1st at 00:00 UTC.', { exact: true })).toBeVisible()
  expect((await stream.boundingBox())!.x).toBeLessThan((await month.boundingBox())!.x)
  await page.setViewportSize({ width: 390, height: 900 })
  expect((await stream.boundingBox())!.y).toBeLessThan((await month.boundingBox())!.y)
})

test.describe('leaderboard exclusions and UTC display', () => {
  test.use({ timezoneId: 'America/Los_Angeles', locale: 'en-US' })

  test('exclusions stay visible and support cancel, retry and save', async ({ page }) => {
    await page.goto('/tests/fixture.html?configured')
    await mockAnalytics(page, true)
    await page.evaluate(() => {
      const api = window.pywebview!.api
      const appStatus = api.get_app_status
      api.get_app_status = async () => ({ ...await appStatus(), leaderboard_channel_id: '200' })
      let exclusions = ['otherbot']
      let fail = true
      api.get_leaderboards = async () => {
        const period = { period: '2026-07', started_at: '2026-07-01T01:00:00Z', ends_at: null, partial: false, rows: [] }
        return { ok: true, leaderboards: { channel_id: '200', connected: false, stream_status: 'unknown',
          month: period, stream: period, exclusions } }
      }
      api.save_leaderboard_settings = async (channel, names) => {
        if (fail || channel !== '200') {
          fail = false
          return { ok: false, error: 'Could not write exclusions.' }
        }
        exclusions = names
        return { ok: true }
      }
    })
    await page.getByRole('button', { name: 'Analytics', exact: true }).click()
    await page.getByRole('button', { name: 'Chatters', exact: true }).click()
    await expect(page.locator('.leaderboard-period').first()).toContainText('Jul 1, 2026, 1:00 AM')
    const names = page.getByRole('textbox', { name: 'Excluded bot names' })
    await expect(names).toHaveValue('otherbot')
    await names.fill('@NewBot')
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(names).toHaveValue('otherbot')
    await names.fill('@NewBot, newbot')
    const save = page.getByRole('button', { name: 'Save exclusions', exact: true })
    await save.click()
    await expect(page.locator('.leaderboard-exclusions').getByRole('alert')).toHaveText('Could not write exclusions.')
    await save.click()
    await expect(names).toHaveValue('newbot')
    await expect(save).toBeDisabled()
  })
})
