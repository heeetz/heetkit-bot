import { expect, test, type Page } from '@playwright/test'
import { selectOption } from './select-helpers'

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
    await expect(models.getByLabel('Primary model', { exact: true })).toBeVisible()
    await expect(models.getByLabel('Fallback model', { exact: true })).toBeVisible()
    await selectOption(models.getByLabel('Primary model', { exact: true }), '__custom_model__')
    await models.getByLabel('Primary model custom model ID', { exact: true }).fill('synthetic-custom')
    await selectOption(language.getByLabel('Response language mode'), 'limited')
    await models.getByRole('button', { name: 'Open Playground' }).click()
    await models.getByRole('button', { name: 'Use current applied settings' }).click()
    expect(await testPrompt(page)).toMatchObject({ model: 'synthetic-primary', language: { mode: 'auto' } })
    await models.getByRole('button', { name: 'Open Playground' }).click()
    await models.getByRole('button', { name: 'Save draft and open Playground' }).click()
    expect(await testPrompt(page)).toMatchObject({ model: 'synthetic-custom', language: { mode: 'auto' } })
    await expect(language.getByLabel('Response language mode')).toHaveAttribute('data-value', 'limited')
    await language.getByRole('button', { name: 'Open Playground' }).click()
    await language.getByRole('button', { name: 'Use current applied settings' }).click()
    expect(await testPrompt(page)).toMatchObject({ language: { mode: 'auto' } })
    await language.getByRole('button', { name: 'Open Playground' }).click()
    await language.getByRole('button', { name: 'Save draft and open Playground' }).click()
    expect(await testPrompt(page)).toMatchObject({ model: 'synthetic-custom', language: { mode: 'limited' } })
    await models.getByRole('button', { name: 'Help: Fallback model', exact: true }).click()
    await expect(page.getByRole('tooltip')).toContainText('Key, network, quota and billing failures do not trigger fallback')
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
    if (id === 'ai-language') await selectOption(editor.getByLabel(field), 'limited')
    else if (id === 'ai-models') {
      await selectOption(editor.getByLabel(field, { exact: true }), 'synthetic-fallback')
      await selectOption(editor.getByLabel('Fallback model', { exact: true }), 'synthetic-primary')
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
  await page.getByRole('button', { name: 'Help: Conversation memory', exact: true }).click()
  await expect(page.getByRole('tooltip')).toContainText('previously stored data is retained')
  await expect(page.getByRole('tooltip')).toContainText('up to five successful exchanges per viewer')
  await expect(page.getByRole('tooltip')).toContainText('broadcaster-only !erase')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Help: AI access', exact: true }).click()
  await expect(page.getByRole('tooltip')).toContainText('does not ban a Twitch user or delete their messages')
  await page.keyboard.press('Escape')
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

for (const width of [1280, 900, 761, 390, 320]) {
  test(`compact AI state and editor rows fit long text and drafts at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/tests/fixture.html?a4Models&aiAvailable')
    await page.evaluate(() => {
      const api = window.pywebview!.api
      const getStatus = api.get_ai_status
      api.get_ai_status = async () => ({ ...await getStatus(), model: 'synthetic-long-model-'.repeat(6) })
      const getPersonalities = api.get_personalities
      api.get_personalities = async () => ({ ...await getPersonalities(), active_personality: 'LongPersonality'.repeat(4) })
    })
    await page.getByRole('button', { name: 'AI', exact: true }).click()
    await expect(page.locator('.ai-layout')).toHaveAttribute('aria-busy', 'false')
    const state = page.locator('#ai-runtime')
    await expect(state.getByRole('heading')).toHaveText(['AI command', 'Conversation memory', 'Gemini', 'Active personality'])
    await expect(state.locator('.ai-state-panel')).toHaveCount(4)
    const panels = await state.locator('.ai-state-panel').all()
    const panelBoxes = await Promise.all(panels.map(async (panel) => (await panel.boundingBox())!))
    const contentWidth = (await page.locator('.page-content').boundingBox())!.width
    const columns = width <= 760 || contentWidth < 480 ? 1 : contentWidth < 1000 ? 2 : 4
    expect(new Set(panelBoxes.map((box) => box.y)).size).toBe(4 / columns)
    for (const panel of panels) {
      expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBeTruthy()
    }
    await state.screenshot({ path: `node_modules/.tmp/a4-state-${width}.png` })

    const language = page.locator('#ai-language')
    await language.locator('.accordion-caret').click()
    await expect(language.locator('.language-policy-status > div')).toHaveCount(1)
    await selectOption(language.getByLabel('Response language mode'), 'limited')
    await expect(language.locator('.language-policy-status > div')).toHaveCount(2)
    await expect(language.locator('.language-policy-status')).toContainText('Draft configuration')
    await language.locator('.language-fields small').first().evaluate((element) => {
      element.textContent = 'A longer explanation can wrap onto several lines without moving the neighboring selector. '.repeat(3)
    })
    const mode = (await language.getByLabel('Response language mode').boundingBox())!
    const fallback = (await language.getByLabel('Fallback language').boundingBox())!
    expect(mode.height).toBe(40)
    expect(fallback.height).toBe(mode.height)
    expect(fallback.width).toBeCloseTo(mode.width, 0)
    if (width > 760 && contentWidth > 620) {
      expect(fallback.y).toBe(mode.y)
      const helpers = await language.locator('.language-fields small').all()
      expect((await helpers[0].boundingBox())!.y).toBe((await helpers[1].boundingBox())!.y)
    } else expect(fallback.y).toBeGreaterThan(mode.y + mode.height)
    await language.screenshot({ path: `node_modules/.tmp/a4-language-${width}.png` })

    const models = page.locator('#ai-models')
    const discover = (await models.getByRole('button', { name: 'Discover models' }).boundingBox())!
    const playground = (await models.getByRole('button', { name: 'Open Playground' }).boundingBox())!
    const save = (await models.getByRole('button', { name: 'Save models', exact: true }).boundingBox())!
    expect(playground.y).toBe(save.y)
    expect(playground.height).toBe(save.height)
    expect(playground.x).toBeLessThan(save.x)
    if (width >= 900) expect(discover.y).toBe(playground.y)
    if (width <= 390) expect(discover.y + discover.height).toBeLessThanOrEqual(playground.y)
    await selectOption(models.getByLabel('Primary model', { exact: true }), 'synthetic-fallback')
    await models.getByRole('button', { name: 'Open Playground' }).click()
    await expect(models.locator('.playground-draft-choice')).toBeVisible()
    await models.screenshot({ path: `node_modules/.tmp/a4-models-${width}.png` })
    await expect(page.locator('#ai-memory').getByRole('checkbox')).not.toBeChecked()
    expect(await page.locator('.ai-layout').evaluate((element) => element.scrollWidth <= element.clientWidth)).toBeTruthy()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}

test('compact memory toggle saves independently and reports failures without changing its value', async ({ page }) => {
  await openAI(page)
  const profile = page.locator('#ai-profile-instructions')
  await profile.locator('textarea').fill('Keep unrelated profile draft')
  const memory = page.locator('#ai-memory').getByRole('checkbox', { name: 'Enable conversation memory' })
  await memory.press('Space')
  await expect(memory).toBeChecked()
  await expect(profile.locator('textarea')).toHaveValue('Keep unrelated profile draft')
  expect(await page.evaluate(() => Reflect.get(window, 'aiCalls'))).toEqual([['set_ai_memory_enabled', true]])
  await openAI(page, 'memorySaveError')
  await page.locator('#ai-memory').getByRole('checkbox').press('Space')
  await expect(page.getByRole('alert')).toContainText('Could not save conversation memory setting.')
  await expect(page.locator('#ai-memory').getByRole('checkbox')).not.toBeChecked()
})

test('compact state displays loading and unavailable Gemini with reachable key management', async ({ page }) => {
  await page.goto('/tests/fixture.html')
  await page.evaluate(() => {
    const api = window.pywebview!.api
    const getStatus = api.get_ai_status
    const pending = new Promise<void>((resolve) => Reflect.set(window, 'releaseAIStatus', resolve))
    api.get_ai_status = async () => { await pending; return getStatus() }
  })
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  const state = page.locator('#ai-runtime')
  await expect(state.locator('.ai-state-panel')).toHaveCount(4)
  await expect(state.getByRole('checkbox', { name: 'Enable conversation memory' })).toBeDisabled()
  await expect(state.getByRole('button', { name: 'Add Gemini key' })).toBeDisabled()
  await expect(state).toContainText('Loading…')
  await page.evaluate(() => Reflect.get(window, 'releaseAIStatus')())
  await expect(page.locator('.ai-layout')).toHaveAttribute('aria-busy', 'false')
  await expect(state).toContainText('Unavailable')
  await expect(state).toContainText('Not selected')
  await state.getByRole('button', { name: 'Add Gemini key' }).click()
  await expect(page.locator('#credential-settings')).toBeInViewport()
})

test('model discovery shares the action row and leaves drafts unsaved', async ({ page }) => {
  await openAI(page)
  await page.evaluate(() => {
    window.pywebview!.api.discover_gemini_models = async () => ({ ok: true, models: ['synthetic-discovered'] })
  })
  const models = page.locator('#ai-models')
  await models.getByRole('button', { name: 'Discover models' }).click()
  await selectOption(models.getByLabel('Primary model', { exact: true }), 'synthetic-discovered')
  await expect(models.getByRole('button', { name: 'Save models', exact: true })).toBeEnabled()
  await expect(models).toContainText('Saved primary model: synthetic-primary')
  expect(await page.evaluate(() => Reflect.get(window, 'aiCalls'))).toEqual([])
})
