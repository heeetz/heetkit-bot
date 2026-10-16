import { expect, test } from '@playwright/test'
import { selectOption } from './select-helpers'

for (const width of [1280, 390]) {
  test(`Logs level dropdown filters existing entries at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/tests/fixture.html?configured')
    await page.evaluate(() => {
      let delivered = false
      window.pywebview!.api.get_recent_logs = async () => {
        if (delivered) return { entries: [] }
        delivered = true
        return { entries: ['INFO', 'ERROR'].map((level, index) => ({
          id: index + 1, timestamp: '12:00:00', level, source: 'synthetic', message: `Synthetic ${level} activity`, event_kind: null, context: {},
        })) }
      }
    })
    await page.getByRole('button', { name: 'Logs', exact: true }).click()
    await expect(page.locator('.log-row')).toHaveCount(2)
    const level = page.getByRole('combobox', { name: 'Level' })
    await selectOption(level, 'ERROR')
    await expect(page.locator('.log-row')).toHaveCount(1)
    await expect(page.locator('.log-row')).toContainText('Synthetic ERROR activity')
    await selectOption(level, 'ALL')
    await expect(page.locator('.log-row')).toHaveCount(2)
    await level.click()
    await page.screenshot({ path: `node_modules/.tmp/logs-dropdown-${width}.png` })
    await level.press('Escape')
  })

  test(`Settings channel selection remains a draft until explicitly saved at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/tests/fixture.html?configured')
    await page.evaluate(() => {
      const getSettings = window.pywebview!.api.get_twitch_settings
      window.pywebview!.api.get_twitch_settings = async () => {
        const response = await getSettings()
        return { ...response, settings: { ...response.settings!, presets: [
          { id: 'alternate', display_name: 'Alternate channel', target_channel: 'otherchannel', target_channel_user_id: '300' },
        ] } }
      }
    })
    await page.getByRole('button', { name: 'Settings', exact: true }).click()
    const twitch = page.locator('#twitch-settings')
    await twitch.locator('.accordion-caret').click()
    await selectOption(twitch.getByRole('combobox', { name: /^Saved channel/ }), 'alternate')
    await expect(twitch.getByLabel('Target channel login')).toHaveValue('otherchannel')
    await expect(twitch.getByLabel('Target channel user ID')).toHaveValue('300')
    await expect(twitch.getByLabel('Bot account login')).toHaveValue('testbot')
    expect(await page.evaluate(() => Reflect.get(window, 'twitchCalls'))).toEqual([])
    await twitch.getByRole('button', { name: 'Save for later', exact: true }).click()
    expect(await page.evaluate(() => Reflect.get(window, 'twitchCalls'))).toEqual([
      ['save', 'otherchannel', '300', 'alternate', 'synthetic-client', 'testbot', '100'],
    ])
  })
}

for (const width of [1280, 320]) {
  test(`personality toolbar and menu stay readable after short-name selection at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/tests/fixture.html?configured&aiAvailable')
    await page.evaluate(() => {
      const getPersonalities = window.pywebview!.api.get_personalities
      window.pywebview!.api.get_personalities = async () => {
        const response = await getPersonalities()
        return { ...response, active_personality: 'A', personalities: ['A', 'go', 'rapper', 'A longer personality name'].map((name) => ({ ...response.personalities[0], name })) }
      }
    })
    await page.getByRole('button', { name: 'AI', exact: true }).click()
    const personality = page.locator('#ai-personalities')
    await personality.locator('.accordion-caret').click()
    const control = personality.getByRole('combobox', { name: 'Personality', exact: true })
    const initialWidth = (await control.boundingBox())!.width
    expect(initialWidth).toBeGreaterThanOrEqual(240)
    for (const value of ['go', 'A longer personality name', 'A']) {
      await selectOption(control, value)
      expect((await control.boundingBox())!.width).toBe(initialWidth)
    }
    await control.click()
    const menu = page.getByRole('listbox')
    await expect(menu).toBeVisible()
    const bounds = (await menu.boundingBox())!
    expect(bounds.width).toBeGreaterThanOrEqual(initialWidth)
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width - 8)
    expect((await page.getByRole('option', { name: 'rapper', exact: true }).locator('span:first-child').boundingBox())!.height).toBe(20)
    await page.screenshot({ path: `node_modules/.tmp/personality-width-${width}.png` })
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}
