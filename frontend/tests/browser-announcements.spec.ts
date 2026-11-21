import { expect, test } from '@playwright/test'
import { navigate, selectOption, server, sessionToken, signIn } from './browser-fixture'

test('schedules, changes, disables and deletes an announcement with confirmation', async ({ page }) => {
  const api = await server(page)
  await signIn(page)
  await navigate(page, 'Commands')
  const panel = page.locator('#announcements')
  const writes = () => api.calls.filter(({ method, path }) => method === 'POST' && path === '/v1/ops/save_announcements')
  const save = panel.getByRole('button', { name: 'Save announcements', exact: true })
  await panel.getByRole('button', { name: 'New announcement', exact: true }).click()
  await panel.getByLabel('Name', { exact: true }).fill('Community links')
  await panel.getByLabel('Announcement message', { exact: true }).fill('First community link.')
  await panel.getByLabel('Interval (s)', { exact: true }).fill('0')
  await save.click()
  await expect(panel.getByRole('alert')).toBeVisible()
  expect(writes()).toHaveLength(0)

  await panel.getByLabel('Interval (s)', { exact: true }).fill('900')
  await selectOption(panel.getByLabel('Announcement type', { exact: true }), 'regular')
  await save.click()
  const row = panel.getByRole('row', { name: /Community links/ })
  const edit = row.getByRole('button', { name: 'Edit', exact: true })
  await expect(edit).toBeVisible()
  expect(writes()[0]).toMatchObject({ authorization: 'Bearer ' + sessionToken, body: {
    announcements: [{ id: null, delivery_mode: 'regular', messages: ['First community link.'] }],
  } })

  await edit.click()
  await selectOption(panel.getByLabel('Announcement type', { exact: true }), 'highlighted')
  await selectOption(panel.getByLabel('Message selection', { exact: true }), 'random')
  await panel.getByLabel('Random messages', { exact: true }).fill('First community link.\n\n Second community link.')
  await selectOption(panel.getByLabel('Stream availability', { exact: true }), 'live_only')
  await save.click()
  await expect(edit).toBeVisible()
  expect(writes()[1]?.body).toMatchObject({ announcements: [{
    id: expect.any(String), message_mode: 'random', delivery_mode: 'highlighted',
    messages: ['First community link.', 'Second community link.'], stream_availability: 'live_only',
  }] })

  const enabled = row.getByLabel('Enable Community links', { exact: true })
  await enabled.press('Space')
  await expect.poll(() => writes()[2]?.body).toMatchObject({ announcements: [{ enabled: false }] })
  await expect(enabled).not.toBeChecked()

  const remove = row.getByRole('button', { name: 'Delete', exact: true })
  const confirmation = page.getByRole('dialog')
  await remove.click()
  await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click()
  expect(writes()).toHaveLength(3)
  await remove.click()
  await confirmation.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(row).toHaveCount(0)
  expect(writes().at(-1)?.body).toEqual({ announcements: [] })
})

test('a committed announcement cannot be duplicated while its new ID is unavailable', async ({ page }) => {
  await page.clock.install()
  const api = await server(page)
  let allowRead = true
  await page.route(/\/v1\/ops\/(get|save)_announcements$/, async (route) => {
    if (route.request().url().endsWith('/save_announcements')) {
      allowRead = false
    } else if (!allowRead) {
      return route.fulfill({ json: { ok: false, announcements: [] } })
    }
    await route.fallback()
  })
  await signIn(page)
  await navigate(page, 'Commands')
  const panel = page.locator('#announcements')
  const create = panel.getByRole('button', { name: 'New announcement' })
  const save = panel.getByRole('button', { name: 'Save announcements' })
  await create.click()
  await panel.getByLabel('Name', { exact: true }).fill('Saved reminder')
  await panel.getByLabel('Announcement message').fill('Already committed')
  await save.click()
  await expect(panel.getByRole('alert')).toBeVisible()
  await expect(save).toHaveCount(0)
  await expect(create).toBeDisabled()
  allowRead = true
  await page.clock.fastForward(5100)
  await expect(create).toBeEnabled()
  await expect(panel.getByRole('row', { name: /Saved reminder/ })).toBeVisible()
  expect(api.calls.filter(({ path, method }) => path === '/v1/ops/save_announcements' && method === 'POST')).toHaveLength(1)
})

test('a row removed during editing keeps its draft cancellable and blocks a stale write', async ({ page }) => {
  await page.clock.install()
  const api = await server(page)
  await signIn(page)
  await navigate(page, 'Commands')
  const panel = page.locator('#announcements')
  await panel.getByRole('button', { name: 'New announcement' }).click()
  const name = panel.getByLabel('Name', { exact: true })
  const save = panel.getByRole('button', { name: 'Save announcements' })
  await name.fill('Reminder')
  await panel.getByLabel('Announcement message').fill('Synthetic reminder')
  await save.click()
  const row = panel.getByRole('row', { name: /Reminder/ })
  await row.getByRole('button', { name: 'Edit' }).click()
  await name.fill('Unsaved draft')
  await page.route('**/v1/ops/get_announcements', async (route) => {
    await route.fulfill({ json: { ok: true, announcements: [] } })
  })
  const refresh = page.waitForResponse('**/v1/ops/get_announcements')
  await page.clock.fastForward(5100)
  await refresh
  await expect(name).toHaveValue('Unsaved draft')
  await save.click()
  await expect(panel.getByRole('alert')).toBeVisible()
  await panel.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(row).toHaveCount(0)
  expect(api.calls.filter(({ method, path }) => method === 'POST' && path === '/v1/ops/save_announcements')).toHaveLength(1)
})
