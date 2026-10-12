import { expect, test, type Page } from '@playwright/test'

async function openAI(page: Page, query = '') {
  await page.goto(`/tests/fixture.html?a4Models&aiAvailable&askToggle&${query}`)
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(page.locator('.ai-layout')).toHaveAttribute('aria-busy', 'false')
  for (const id of ['ai-personalities', 'ai-profile-instructions', 'ai-language']) {
    await page.locator(`#${id} .accordion-trigger`).click()
  }
}

async function testPrompt(page: Page) {
  const playground = page.locator('#ai-playground')
  await playground.getByLabel('Playground prompt').fill('Synthetic prompt')
  await playground.getByRole('button', { name: 'Test prompt', exact: true }).click()
  await expect(playground.getByRole('status')).toContainText('Response')
  return page.evaluate(() => Reflect.get(window, 'playgroundSettings').at(-1))
}

for (const width of [1280, 390]) {
  test(`inactive personality saves and Playground choices preserve other drafts at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openAI(page)
    const personality = page.locator('#ai-personalities')
    const profile = page.locator('#ai-profile-instructions')
    await personality.getByRole('button', { name: 'New personality', exact: true }).click()
    await personality.getByLabel('Name', { exact: true }).fill('Inactive helper')
    await personality.getByLabel('Prompt', { exact: true }).fill('Saved inactive prompt')
    await personality.getByRole('button', { name: 'Create', exact: true }).click()
    await personality.getByLabel('Editable prompt').fill('Inactive draft')
    await profile.locator('textarea').fill('Unrelated profile draft')
    await personality.getByRole('button', { name: 'Open Playground' }).click()
    await expect(personality.locator('.playground-draft-choice')).toContainText('Saving Inactive helper does not activate it')
    await personality.getByRole('button', { name: 'Use current applied settings' }).click()
    expect(await testPrompt(page)).toMatchObject({ personality: 'neutral', personalityPrompt: 'Synthetic neutral prompt.', profile: '' })
    await expect(personality.getByLabel('Editable prompt')).toHaveValue('Inactive draft')
    await expect(page.locator('.playground-draft-warning')).toBeVisible()
    await personality.getByRole('button', { name: 'Open Playground' }).click()
    await personality.getByRole('button', { name: 'Save draft and open Playground' }).click()
    expect(await testPrompt(page)).toMatchObject({ personality: 'neutral', profile: '' })
    await expect(profile.locator('textarea')).toHaveValue('Unrelated profile draft')
    await expect(personality.getByText('Active', { exact: true })).toBeHidden()
    await personality.getByRole('button', { name: 'Set active', exact: true }).click()
    await personality.getByRole('button', { name: 'Open Playground' }).click()
    expect(await testPrompt(page)).toMatchObject({ personality: 'Inactive helper', personalityPrompt: 'Inactive draft', profile: '' })
    expect(await page.evaluate(() => Reflect.get(window, 'aiCalls'))).toEqual([
      ['create_personality', 'Inactive helper', 'Saved inactive prompt'],
      ['save_personality', 'Inactive helper', 'Inactive draft'], ['set_active_personality', 'Inactive helper'],
    ])
  })

  for (const action of ['current', 'apply', 'save']) {
    test(`profile ${action} choice uses explicit instructions and preserves personality draft at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await openAI(page)
      const personality = page.locator('#ai-personalities')
      const profile = page.locator('#ai-profile-instructions')
      await personality.getByLabel('Editable prompt').fill('Keep personality draft')
      await profile.locator('textarea').fill('Profile draft')
      await profile.getByRole('button', { name: 'Open Playground' }).click()
      await profile.getByRole('button', { name: action === 'current' ? 'Use current applied settings' : action === 'apply' ? 'Apply draft and open Playground' : 'Save draft and open Playground' }).click()
      expect(await testPrompt(page)).toMatchObject({ profile: action === 'current' ? '' : 'Profile draft', personalityPrompt: 'Synthetic neutral prompt.' })
      await expect(personality.getByLabel('Editable prompt')).toHaveValue('Keep personality draft')
      await expect(profile.locator('textarea')).toHaveValue('Profile draft')
      expect(await page.evaluate(() => Reflect.get(window, 'aiCalls'))).toEqual(action === 'current' ? [] : [[`${action}_profile_instructions`, 'Profile draft']])
      if (action === 'apply') {
        await expect(profile.getByText('Runtime only', { exact: true })).toBeVisible()
        await profile.getByRole('button', { name: 'Open Playground' }).click()
        await profile.getByRole('button', { name: 'Save applied instructions and open Playground' }).click()
        await expect(profile.getByText('Saved', { exact: true })).toBeVisible()
      }
    })
  }

  test(`model and language drafts require explicit saves at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openAI(page)
    const models = page.locator('#ai-models')
    const language = page.locator('#ai-language')
    await expect(models.getByLabel('Primary model')).toBeVisible()
    await expect(models.getByLabel('Fallback model', { exact: true })).toBeHidden()
    await models.getByLabel('Primary model').selectOption('__custom_model__')
    await models.locator('.custom-model-options summary').click()
    await models.getByLabel('Custom model ID', { exact: true }).fill('synthetic-custom')
    await language.getByLabel('Response language mode').selectOption('limited')
    await models.getByRole('button', { name: 'Open Playground' }).click()
    await models.getByRole('button', { name: 'Use current applied settings' }).click()
    expect(await testPrompt(page)).toMatchObject({ model: 'synthetic-primary', language: { mode: 'auto' } })
    await models.getByRole('button', { name: 'Open Playground' }).click()
    await models.getByRole('button', { name: 'Save draft and open Playground' }).click()
    expect(await testPrompt(page)).toMatchObject({ model: 'synthetic-custom', language: { mode: 'auto' } })
    await expect(language.getByLabel('Response language mode')).toHaveValue('limited')
    await language.getByRole('button', { name: 'Open Playground' }).click()
    await language.getByRole('button', { name: 'Use current applied settings' }).click()
    expect(await testPrompt(page)).toMatchObject({ language: { mode: 'auto' } })
    await language.getByRole('button', { name: 'Open Playground' }).click()
    await language.getByRole('button', { name: 'Save draft and open Playground' }).click()
    expect(await testPrompt(page)).toMatchObject({ model: 'synthetic-custom', language: { mode: 'limited' } })
    await models.locator('.model-advanced summary').click()
    await expect(models).toContainText('Key, network, quota and billing failures do not trigger fallback')
    await expect(models.getByRole('button', { name: 'Test credential' })).toHaveCount(0)
  })

  test(`Settings return and !ask editor links retain drafts at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openAI(page)
    const profile = page.locator('#ai-profile-instructions')
    await profile.locator('textarea').fill('Keep profile draft')
    await page.getByRole('button', { name: 'Manage Gemini key' }).click()
    const key = page.locator('#credential-settings')
    await expect(key).toBeInViewport()
    await key.getByRole('button', { name: 'Test credential' }).click()
    expect(await page.evaluate(() => Reflect.get(window, 'playgroundCalls'))).toEqual([])
    await key.getByRole('button', { name: 'Return to AI Playground' }).click()
    await expect(page.locator('#ai-playground')).toBeInViewport()
    await expect(profile.locator('textarea')).toHaveValue('Keep profile draft')
    await page.getByRole('button', { name: 'Edit !ask access and cooldowns' }).click()
    const ask = page.locator('#command-editor-ask')
    await expect(ask).toBeInViewport()
    await expect(ask.getByRole('button', { name: 'Collapse !ask', exact: true })).toBeVisible()
    await ask.getByLabel('Per-user cooldown').fill('9')
    await page.getByRole('button', { name: 'AI', exact: true }).click()
    await expect(profile.locator('textarea')).toHaveValue('Keep profile draft')
    await page.getByRole('button', { name: 'Edit !ask access and cooldowns' }).click()
    await expect(ask.getByLabel('Per-user cooldown')).toHaveValue('9')
  })
}

for (const [id, failure, field] of [
  ['ai-personalities', 'savePersonalityError', 'Editable prompt'],
  ['ai-profile-instructions', 'profileError', 'Profile instructions'],
  ['ai-language', 'languageSaveError', 'Response language mode'],
  ['ai-models', 'modelSaveError', 'Primary model'],
]) {
  test(`failed ${id} save keeps the draft choice and does not open Playground`, async ({ page }) => {
    await openAI(page, failure)
    const editor = page.locator(`#${id}`)
    if (id === 'ai-language') await editor.getByLabel(field).selectOption('limited')
    else if (id === 'ai-models') {
      await editor.getByLabel(field).selectOption('synthetic-fallback')
      await editor.locator('.model-advanced summary').click()
      await editor.getByLabel('Fallback model', { exact: true }).selectOption('synthetic-primary')
    }
    else await editor.getByRole('textbox', { name: field, exact: true }).fill('Retain failed draft')
    await editor.getByRole('button', { name: 'Open Playground' }).click()
    await editor.getByRole('button', { name: 'Save draft and open Playground' }).click()
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(editor.locator('.playground-draft-choice')).toBeVisible()
    expect(await page.evaluate(() => Reflect.get(window, 'playgroundCalls'))).toEqual([])
    if (id === 'ai-personalities' || id === 'ai-profile-instructions') await expect(editor.locator('textarea')).toHaveValue('Retain failed draft')
    await editor.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(editor.locator('.playground-draft-choice')).toHaveCount(0)
  })
}

test('AI scope and memory/access explanations remain available while stopped', async ({ page }) => {
  await openAI(page)
  const playground = page.locator('#ai-playground')
  await expect(playground).toContainText('no viewer memory, stream context, chat activity, command permissions or cooldowns')
  await expect(playground).toContainText('The bot can be stopped and !ask disabled')
  await expect(playground).toContainText('Success does not prove Twitch delivery')
  await expect(playground).toContainText('real Gemini API quota')
  await expect(page.locator('#ai-memory')).toContainText('previously stored data is retained')
  await expect(page.locator('#ai-memory')).toContainText('up to five successful exchanges per viewer')
  await expect(page.locator('#ai-memory')).toContainText('broadcaster-only !erase')
  await expect(page.locator('#ai-blocked-users')).toContainText('does not ban a Twitch user or delete their messages')
  expect(await testPrompt(page)).toMatchObject({ personality: 'neutral' })
})

test('draft choices fit the supported 320px layout', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 })
  await openAI(page)
  const profile = page.locator('#ai-profile-instructions')
  await profile.locator('textarea').fill('Draft instructions')
  await profile.getByRole('button', { name: 'Open Playground' }).click()
  await expect(profile.getByRole('button', { name: 'Apply draft and open Playground' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
  await page.screenshot({ path: 'node_modules/.tmp/a4-draft-choice-320.png', fullPage: true })
})

test('the !ask access link reaches recovery when the command is removed', async ({ page }) => {
  await openAI(page)
  await page.evaluate(() => {
    const api = window.pywebview!.api
    const getCommands = api.get_commands
    api.get_commands = async () => {
      const response = await getCommands()
      response.commands = response.commands.map((command) => command.name === 'ask' ? { ...command, removed: true, enabled: false } : command)
      return response
    }
  })
  await page.getByRole('button', { name: 'Edit !ask access and cooldowns' }).click()
  const ask = page.locator('#command-editor-ask')
  await expect(ask).toBeInViewport()
  await expect(ask).toContainText('Removed')
  await expect(ask.getByRole('button', { name: 'Restore defaults and enable' })).toBeVisible()
})
