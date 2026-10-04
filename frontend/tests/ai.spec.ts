import { expect, test } from '@playwright/test'

test('profile actions preserve personality drafts and expose state', async ({ page }) => {
  await page.goto('/tests/fixture.html')
  await page.getByRole('button', { name: 'AI', exact: true }).click()

  const personality = page.locator('.personality-editor')
  const profile = page.locator('.profile-instructions-editor')
  const protectedInstructions = page.locator('.protected-instructions-card')
  await expect(profile.locator('textarea')).toHaveValue('')
  await expect(protectedInstructions).not.toHaveAttribute('open', '')

  await personality.locator('textarea').fill('personality draft')
  await profile.locator('textarea').fill('profile draft')
  await personality.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(profile.locator('textarea')).toHaveValue('profile draft')

  await personality.locator('textarea').fill('another personality draft')
  await profile.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(personality.locator('textarea')).toHaveValue('another personality draft')
  await expect(profile.getByText('Runtime only', { exact: true })).toBeVisible()

  await profile.locator('textarea').fill('saved profile draft')
  await personality.locator('textarea').fill('saved personality draft')
  await profile.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(profile.locator('textarea')).toHaveValue('saved profile draft')
  await expect(personality.locator('textarea')).toHaveValue('saved personality draft')
  await expect(profile.getByText('Saved', { exact: true })).toBeVisible()

  page.once('dialog', (dialog) => { void dialog.accept() })
  await profile.getByRole('button', { name: 'Reset', exact: true }).click()
  await expect(profile.locator('textarea')).toHaveValue('')
  await expect(personality.locator('textarea')).toHaveValue('saved personality draft')

  await protectedInstructions.locator('summary').click()
  await expect(protectedInstructions.locator('textarea')).toHaveValue('Synthetic shared instructions.')
  await expect(protectedInstructions.locator('textarea')).toHaveAttribute('readonly', '')
})

test('failed profile action retains its draft', async ({ page }) => {
  await page.goto('/tests/fixture.html?profileError')
  await page.getByRole('button', { name: 'AI', exact: true }).click()

  const profile = page.locator('.profile-instructions-editor')
  await profile.locator('textarea').fill('keep this after failure')
  await profile.getByRole('button', { name: 'Apply', exact: true }).click()
  await expect(profile.locator('textarea')).toHaveValue('keep this after failure')
  await expect(page.getByRole('alert').locator('span')).toHaveText('Profile instructions could not be updated.')
})
