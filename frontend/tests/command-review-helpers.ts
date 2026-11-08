import { expect, type Locator, type Page } from '@playwright/test'
import { join } from 'node:path'
import { selectOption } from './select-helpers'

async function screenshot(locator: Locator, name: string, host: string, width: number) {
  if (process.env.HEETKIT_REVIEW_IMAGES) {
    await locator.screenshot({ animations: 'disabled', path: join(process.env.HEETKIT_REVIEW_IMAGES, `${name}-${host}-${width}.png`) })
  }
}

export async function reviewCommands(page: Page, host: 'desktop' | 'server', width: number) {
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await nav.getByRole('button', { name: 'Commands', exact: true }).click()
  const custom = page.locator('#custom-commands')
  await custom.getByRole('button', { name: 'New command' }).click()
  await custom.getByLabel('Command name', { exact: true }).fill('welcome')
  await custom.getByLabel('Message', { exact: true }).fill('Welcome, {sender}!')
  await selectOption(custom.getByRole('combobox', { name: 'Permission', exact: true }), 'USER')
  const delivery = custom.getByRole('combobox', { name: 'Send as', exact: true })
  await selectOption(delivery, 'reply')
  await custom.getByRole('button', { name: 'Save command' }).click()
  await page.getByRole('button', { name: 'Dismiss message', exact: true }).click()
  await custom.locator('article').filter({ hasText: '!welcome' }).getByRole('button', { name: 'Edit', exact: true }).click()
  const editor = custom.locator('.custom-command-editor')
  await expect(delivery).toHaveText('Reply to message')
  const name = (await editor.getByLabel('Command name', { exact: true }).boundingBox())!
  const enabled = (await editor.locator('.custom-command-enabled').boundingBox())!
  const permission = (await editor.getByRole('combobox', { name: 'Permission', exact: true }).boundingBox())!
  const response = (await editor.getByRole('combobox', { name: 'Response type', exact: true }).boundingBox())!
  const sendAs = (await delivery.boundingBox())!
  expect(enabled.y).toBeLessThan(name.y)
  const streamField = editor.getByRole('combobox', { name: 'Stream availability', exact: true })
  if (host === 'server') {
    const stream = (await streamField.boundingBox())!
    if (width >= 1280) {
      expect(stream.x).toBe(permission.x)
      expect(stream.width).toBe(permission.width)
      expect(sendAs.x).toBe(response.x)
      expect(sendAs.width).toBe(response.width)
      expect(sendAs.y).toBe(stream.y)
    } else expect(sendAs.y).toBeGreaterThan(stream.y)
  } else {
    await expect(streamField).toHaveCount(0)
    expect(sendAs.x).toBe(permission.x)
    expect(sendAs.width).toBe(permission.width)
  }
  await editor.getByRole('heading').click()
  await screenshot(editor, 'custom-editor', host, width)

  const builtin = page.locator('#builtin-commands .command-card').filter({ hasText: '!ask' }).first()
  await builtin.locator('.accordion-trigger').click()
  const primary = (await builtin.getByLabel('Primary chat name', { exact: true }).boundingBox())!
  const display = (await builtin.getByLabel('Name in UI', { exact: true }).boundingBox())!
  const aliases = (await builtin.getByLabel('Aliases, separated by commas', { exact: true }).boundingBox())!
  const builtinDelivery = builtin.getByRole('combobox', { name: 'Send as', exact: true })
  const builtinSendAs = (await builtinDelivery.boundingBox())!
  if (width >= 1280) {
    expect(builtinSendAs.y).toBe(primary.y)
    expect(aliases.y).toBe(display.y)
    expect(builtinSendAs.x).toBe(aliases.x)
  } else {
    expect(builtinSendAs.y).toBeGreaterThan(primary.y)
    expect(aliases.y).toBeGreaterThan(display.y)
  }
  await expect(builtinDelivery).toHaveText('Mention sender')
  await screenshot(builtin, 'builtin-editor', host, width)
  await selectOption(builtinDelivery, 'reply')
  await builtin.getByRole('button', { name: /^Save( command)?$/ }).click()
  await expect(builtin).toContainText('Saved override')
  await expect(builtinDelivery).toHaveText('Reply to message')
  await page.getByRole('button', { name: 'Dismiss message', exact: true }).click()

  const reactions = page.locator('#chat-reactions')
  const add = async (text: string) => {
    await reactions.getByRole('button', { name: 'New reaction' }).click()
    await reactions.getByLabel('Match text', { exact: true }).fill(text)
    await reactions.getByLabel('Responses', { exact: true }).fill('Welcome to chat!\nGlad you are here!')
    await reactions.getByRole('button', { name: 'Save reaction' }).click()
    await expect(reactions.getByText(text, { exact: true })).toBeVisible()
  }
  await add('hello chat')
  await add('good morning')
  const cards = reactions.locator('article')
  await cards.nth(1).getByRole('button', { name: 'Edit', exact: true }).click()
  await selectOption(reactions.getByRole('combobox', { name: 'Match mode', exact: true }), 'exact')
  await reactions.getByLabel('Probability (%)', { exact: true }).fill('75')
  await reactions.getByLabel('Cooldown (seconds)', { exact: true }).fill('30')
  await reactions.getByRole('checkbox', { name: 'Case sensitive', exact: true }).press('Space')
  await reactions.getByRole('checkbox', { name: 'Enable chat reaction', exact: true }).press('Space')
  await expect(reactions.getByRole('checkbox', { name: 'Case sensitive', exact: true })).toBeChecked()
  await expect(reactions.getByRole('checkbox', { name: 'Enable chat reaction', exact: true })).not.toBeChecked()
  const reactionHeader = reactions.locator('.reaction-editor-heading')
  const moveUp = reactionHeader.getByRole('button', { name: 'Move up' })
  const orderLabel = reactionHeader.getByText('Position 2 of 2', { exact: true })
  const label = (await orderLabel.boundingBox())!
  const button = (await moveUp.boundingBox())!
  if (width >= 1280) expect(Math.abs(label.y + label.height / 2 - button.y - button.height / 2)).toBeLessThan(2)
  await reactionHeader.getByRole('button', { name: 'Help: Reaction order' }).press('Enter')
  await expect(page.getByRole('tooltip')).toContainText('The first eligible reaction responds.')
  await page.keyboard.press('Escape')
  await reactions.getByRole('heading', { name: 'Edit reaction' }).click()
  await screenshot(reactions.locator('form'), 'reaction-editor', host, width)
  await moveUp.click()
  await expect(reactionHeader.getByText('Position 1 of 2', { exact: true })).toBeVisible()
  await expect(cards.first()).toContainText('hello chat')
  await reactions.getByRole('button', { name: 'Save reaction' }).click()
  await expect(cards.first()).toContainText('good morning')
  await expect(cards.first()).toContainText('Disabled')
  await expect(cards.first()).toContainText('Exact')
  await cards.first().getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(reactions.getByLabel('Probability (%)', { exact: true })).toHaveValue('75')
  await expect(reactions.getByLabel('Cooldown (seconds)', { exact: true })).toHaveValue('30')
  await expect(reactions.getByRole('checkbox', { name: 'Case sensitive', exact: true })).toBeChecked()
  await reactions.getByRole('button', { name: 'Remove reaction' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(cards).toHaveCount(1)
  await expect(cards.first()).toContainText('hello chat')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
}

export async function reviewTrend(page: Page, host: 'desktop' | 'server', width: number) {
  await page.getByRole('navigation').getByRole('button', { name: 'Analytics', exact: true }).click()
  await selectOption(page.getByLabel('UTC window', { exact: true }), '1')
  await expect(page.getByRole('img', { name: /Command attempts by UTC hour/ })).toBeVisible()
  const chart = page.locator('.analytics-chart')
  const tooltip = page.getByRole('tooltip')
  const hourPosition = async (hour: number) => {
    await chart.scrollIntoViewIfNeeded()
    const bounds = (await chart.boundingBox())!
    return { x: 35 + (bounds.width - 70) * hour / 23, y: 100 }
  }
  await chart.hover({ position: await hourPosition(10) })
  await expect(tooltip.locator('strong')).toHaveText('8 command attempts')
  await expect(tooltip.locator('span')).toHaveText('10:00 UTC')
  await screenshot(page.locator('.analytics-trend'), 'chart-tooltip', host, width)
  await chart.tap({ position: await hourPosition(11) })
  await expect(tooltip.locator('strong')).toHaveText('0 command attempts')
  await chart.press('ArrowRight')
  await expect(tooltip.locator('strong')).toHaveText('Command attempts unavailable')
  await expect(tooltip.locator('span')).toHaveText('12:00 UTC')
  await chart.press('Escape')
  await expect(tooltip).toHaveCount(0)
  const trend = page.getByLabel('Trend', { exact: true })
  await selectOption(trend, 'ai.input_tokens')
  await chart.tap({ position: await hourPosition(10) })
  await expect(tooltip.locator('strong')).toHaveText('100 reported input tokens')
  await selectOption(trend, 'ai.estimated_usd')
  await page.getByRole('img', { name: /Known spend subtotal.* by UTC hour/ }).tap({ position: await hourPosition(10) })
  await expect(tooltip.locator('strong')).toHaveText('0.0010 USD estimated spend')
}
