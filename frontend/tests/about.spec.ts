import { expect, test } from '@playwright/test'

test('Windows checks once at startup and only hands off a verified installer', async ({ page }) => {
  await page.goto('/tests/fixture.html?failVerification')
  await page.getByRole('button', { name: 'About', exact: true }).click()
  const card = page.getByRole('article', { name: 'Check for updates' })
  const install = card.getByRole('button', { name: 'Update & restart' })
  const calls = () => page.evaluate(() => Reflect.get(window, 'updateCalls'))
  await expect(install).toBeEnabled()
  expect(await calls()).toEqual([['check_for_updates']])
  await expect(card.getByText('Fixes <strong>markup</strong>.')).toBeVisible()
  await expect(card.getByText('markup', { exact: true })).toHaveCount(0)

  await install.evaluate((button: HTMLButtonElement) => { button.click(); button.click() })
  const download = card.getByRole('progressbar', { name: 'Installer download' })
  await expect(download).toBeVisible()
  await page.evaluate(() => Reflect.get(window, 'finishUpdateDownload')())
  await expect(card.getByRole('alert')).toBeVisible()
  await expect(install).toBeEnabled()
  expect(await calls()).toEqual([['check_for_updates'], ['prepare', '0.2.0']])

  await install.click()
  await expect(download).toBeVisible()
  await page.evaluate(() => Reflect.get(window, 'finishUpdateDownload')())
  await expect.poll(calls).toEqual([
    ['check_for_updates'], ['prepare', '0.2.0'], ['prepare', '0.2.0'], ['finish', '0.2.0'],
  ])
})

test('a quiet Windows startup check failure allows a manual retry', async ({ page }) => {
  await page.goto('/tests/fixture.html?failStartupCheck')
  await page.getByRole('button', { name: 'About', exact: true }).click()
  const card = page.getByRole('article', { name: 'Check for updates' })
  const calls = () => page.evaluate(() => Reflect.get(window, 'updateCalls'))
  await expect.poll(calls).toEqual([['check_for_updates']])
  await expect(card.getByRole('alert')).toHaveCount(0)
  await card.getByRole('button', { name: 'Check for updates', exact: true }).click()
  await expect(card.getByRole('button', { name: 'Update & restart' })).toBeEnabled()
  expect(await calls()).toEqual([['check_for_updates'], ['check_for_updates']])
})

test('portable Desktop opens release downloads after a manual check', async ({ page }) => {
  await page.goto('/tests/fixture.html?manualUpdate&portable')
  await page.getByRole('button', { name: 'About', exact: true }).click()
  const card = page.getByRole('article', { name: 'Check for updates' })
  const calls = () => page.evaluate(() => Reflect.get(window, 'updateCalls'))
  expect(await calls()).toEqual([])
  await card.getByRole('button', { name: 'Check for updates', exact: true }).click()
  await expect(card.getByRole('button', { name: 'Check again' })).toBeEnabled()
  await expect(card.getByRole('button', { name: 'Update & restart' })).toHaveCount(0)
  await card.getByRole('button', { name: 'Open release / downloads' }).click()
  await expect.poll(() => page.evaluate(() => Reflect.get(window, 'opened'))).toEqual(['releases'])
})

test('canceling an update restart preserves an unsaved Settings draft', async ({ page }) => {
  await page.goto('/tests/fixture.html')
  const navigation = page.getByRole('navigation', { name: 'Main navigation' })
  await navigation.getByRole('button', { name: 'Settings', exact: true }).click()
  const twitch = page.getByRole('main').getByRole('button', { name: 'Twitch connection', exact: true })
  if (await twitch.getAttribute('aria-expanded') !== 'true') await twitch.click()
  const channel = page.getByLabel('Target channel login')
  await channel.fill('unsaved_channel')
  await navigation.getByRole('button', { name: 'About', exact: true }).click()
  const install = page.getByRole('button', { name: 'Update & restart' })
  await install.click()
  await expect(page.getByRole('progressbar', { name: 'Installer download' })).toBeVisible()
  const prompt = page.waitForEvent('dialog')
  // Resolving the synthetic download opens the synchronous browser confirmation.
  const finish = page.evaluate(() => { queueMicrotask(() => Reflect.get(window, 'finishUpdateDownload')()) })
  const dialog = await prompt
  await dialog.dismiss()
  await finish
  await expect(install).toBeEnabled()
  expect(await page.evaluate(() => Reflect.get(window, 'updateCalls'))).toEqual([
    ['check_for_updates'], ['prepare', '0.2.0'],
  ])
  await navigation.getByRole('button', { name: 'Settings', exact: true }).click()
  await expect(channel).toHaveValue('unsaved_channel')
})
