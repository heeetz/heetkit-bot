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
