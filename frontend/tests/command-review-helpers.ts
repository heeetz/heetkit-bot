import { expect, type Locator, type Page } from '@playwright/test'
import { join } from 'node:path'
import { createEntry, openEditorSection } from './command-editor-helpers'
import { selectOption } from './select-helpers'

async function screenshot(locator: Locator, name: string, host: string, width: number) {
  if (process.env.HEETKIT_REVIEW_IMAGES) {
    await locator.screenshot({ animations: 'disabled', path: join(process.env.HEETKIT_REVIEW_IMAGES, `${name}-${host}-${width}.png`) })
  }
}

export async function reviewCommands(page: Page, host: 'desktop' | 'server', width: number) {
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await nav.getByRole('button', { name: 'Commands', exact: true }).click()
  await createEntry(page, 'custom')
  const custom = page.locator('#custom-command-editor')
  await custom.getByLabel('Command name', { exact: true }).fill('welcome')
  await custom.getByLabel('Message', { exact: true }).fill('Welcome, {sender}!')
  await openEditorSection(custom, 'Access & aliases')
  await selectOption(custom.getByRole('combobox', { name: 'Permission', exact: true }), 'USER')
  await openEditorSection(custom, 'General')
  const delivery = custom.getByRole('combobox', { name: 'Send as', exact: true })
  await selectOption(delivery, 'reply')
  await custom.getByRole('button', { name: 'Save command' }).click()
  await page.getByRole('button', { name: 'Dismiss message', exact: true }).click()
  await page.getByRole('button', { name: 'Edit !welcome', exact: true }).click()
  const editor = custom
  await expect(delivery).toHaveText('Reply to message')
  const name = (await editor.getByLabel('Command name', { exact: true }).boundingBox())!
  const enabled = (await editor.locator('.custom-command-enabled').boundingBox())!
  expect(enabled.x).toBeGreaterThan(name.x + name.width)
  await screenshot(editor, 'custom-editor', host, width)
  await openEditorSection(editor, 'Access & aliases')
  await expect(editor.getByRole('combobox', { name: 'Permission', exact: true })).toBeVisible()
  if (host === 'server') {
    await openEditorSection(editor, 'Conditions')
    await expect(editor.getByRole('combobox', { name: 'Stream availability', exact: true })).toBeVisible()
  } else await expect(editor.getByRole('button', { name: 'Conditions', exact: true })).toHaveCount(0)

  await editor.getByRole('button', { name: 'Close editor' }).click()
  await page.getByRole('button', { name: 'Edit !ask', exact: true }).click()
  const builtin = page.locator('#command-editor-ask')
  await expect(builtin.getByLabel('Primary chat name', { exact: true })).toBeVisible()
  const builtinDelivery = builtin.getByRole('combobox', { name: 'Send as', exact: true })
  await openEditorSection(builtin, 'Access & aliases')
  await expect(builtin.getByLabel('Name in UI', { exact: true })).toBeVisible()
  await expect(builtin.getByLabel('Aliases, separated by commas', { exact: true })).toBeVisible()
  await openEditorSection(builtin, 'General')
  await expect(builtinDelivery).toHaveText('Mention sender')
  await screenshot(builtin, 'builtin-editor', host, width)
  await selectOption(builtinDelivery, 'reply')
  await builtin.getByRole('button', { name: /^Save( command)?$/ }).click()
  await page.getByRole('button', { name: 'Edit !ask', exact: true }).click()
  await expect(builtinDelivery).toHaveText('Reply to message')
  await builtin.getByRole('button', { name: 'Close editor' }).click()

  const reactions = page.locator('#chat-reaction-editor')
  const add = async (text: string) => {
    await createEntry(page, 'reaction')
    await reactions.getByLabel('Match text', { exact: true }).fill(text)
    await reactions.getByLabel('Responses', { exact: true }).fill('Welcome to chat!\nGlad you are here!')
    await reactions.getByRole('button', { name: 'Save reaction' }).click()
    await expect(page.getByRole('button', { name: `Edit ${text}`, exact: true })).toBeVisible()
  }
  await add('hello chat')
  await add('good morning')
  await page.getByRole('button', { name: 'Edit good morning', exact: true }).click()
  await openEditorSection(reactions, 'Matching & priority')
  await selectOption(reactions.getByRole('combobox', { name: 'Match mode', exact: true }), 'exact')
  await reactions.getByLabel('Probability (%)', { exact: true }).fill('75')
  await reactions.getByLabel('Cooldown (seconds)', { exact: true }).fill('30')
  await reactions.getByRole('checkbox', { name: 'Case sensitive', exact: true }).press('Space')
  await openEditorSection(reactions, 'General')
  await reactions.getByRole('checkbox', { name: 'Enable chat reaction', exact: true }).press('Space')
  await openEditorSection(reactions, 'Matching & priority')
  const mode = (await reactions.getByRole('combobox', { name: 'Match mode' }).boundingBox())!
  const caseControl = (await reactions.locator('.reaction-case').boundingBox())!
  expect(caseControl.x).toBeGreaterThan(mode.x + mode.width)
  for (const field of ['Match mode', 'Case sensitivity', 'Probability (%)', 'Cooldown (seconds)']) {
    await expect(reactions.getByText(field, { exact: true })).toBeVisible()
  }
  await expect(reactions.getByRole('button', { name: /Help:/ })).toHaveCount(0)
  const priority = reactions.locator('.reaction-order')
  await expect(priority.getByText('Priority 2 of 2', { exact: true })).toBeVisible()
  await screenshot(reactions, 'reaction-editor', host, width)
  await priority.getByRole('button', { name: 'Move up' }).click()
  await expect(priority.getByText('Priority 1 of 2', { exact: true })).toBeVisible()
  await reactions.getByRole('button', { name: 'Save reaction' }).click()
  await selectOption(page.getByRole('combobox', { name: 'Status', exact: true }), 'disabled')
  await page.getByRole('button', { name: 'Edit good morning', exact: true }).click()
  await openEditorSection(reactions, 'Matching & priority')
  await expect(reactions.getByText('Priority 1 of 2', { exact: true })).toBeVisible()
  await expect(reactions.getByLabel('Probability (%)', { exact: true })).toHaveValue('75')
  await expect(reactions.getByLabel('Cooldown (seconds)', { exact: true })).toHaveValue('30')
  await expect(reactions.getByRole('checkbox', { name: 'Case sensitive', exact: true })).toBeChecked()
  await reactions.getByRole('button', { name: 'Close editor' }).click()
  await page.getByRole('button', { name: 'Delete good morning', exact: true }).click()
  await page.getByRole('dialog', { name: 'Delete chat reaction?' }).getByRole('button', { name: 'Confirm' }).click()
  await expect(page.getByRole('button', { name: 'Edit good morning', exact: true })).toHaveCount(0)
  await selectOption(page.getByRole('combobox', { name: 'Status', exact: true }), 'active')
  await expect(page.getByRole('button', { name: 'Edit hello chat', exact: true })).toBeVisible()
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
