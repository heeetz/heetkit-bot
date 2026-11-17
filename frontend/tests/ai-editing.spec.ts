import { expect, test, type Page } from '@playwright/test'
import { aiBehaviorDialog, openAIBehaviorSection, closeAIBehavior } from './ai-behavior-helpers'
import { selectOption } from './select-helpers'

async function openAI(page: Page, query = '') {
  await page.goto(`/tests/fixture.html?a4Models&aiAvailable&askToggle&${query}`)
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(page.locator('.ai-layout')).toHaveAttribute('aria-busy', 'false')
  await page.locator('#ai-models .accordion-trigger').click()
  await page.locator('#ai-models .ai-manual-model summary').first().click()
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
    await openAIBehaviorSection(page, 'Personalities')
    await personality.getByRole('button', { name: 'New personality', exact: true }).click()
    await personality.getByLabel('Name', { exact: true }).fill('Inactive helper')
    await personality.getByLabel('Prompt', { exact: true }).fill('Saved inactive prompt')
    await personality.getByRole('button', { name: 'Create', exact: true }).click()
    await personality.getByLabel('Editable prompt').fill('Inactive draft')
    await openAIBehaviorSection(page, 'Profile instructions')
    await profile.locator('textarea').fill('Unrelated profile draft')
    await openAIBehaviorSection(page, 'Personalities')
    await personality.getByRole('button', { name: 'Open Playground' }).click()
    await expect(personality.locator('.playground-draft-choice')).toContainText('Saving Inactive helper does not activate it')
    await personality.getByRole('button', { name: 'Use current applied settings' }).click()
    expect(await testPrompt(page)).toMatchObject({ personality: 'neutral', personalityPrompt: 'Synthetic neutral prompt.', profile: '' })
    await expect(page.locator('.playground-draft-warning')).toBeVisible()
    await openAIBehaviorSection(page, 'Personalities')
    await expect(personality.getByLabel('Editable prompt')).toHaveValue('Inactive draft')
    await personality.getByRole('button', { name: 'Open Playground' }).click()
    await personality.getByRole('button', { name: 'Save draft and open Playground' }).click()
    expect(await testPrompt(page)).toMatchObject({ personality: 'neutral', profile: '' })
    await openAIBehaviorSection(page, 'Profile instructions')
    await expect(profile.locator('textarea')).toHaveValue('Unrelated profile draft')
    await expect(personality.getByText('Active', { exact: true })).toBeHidden()
    await openAIBehaviorSection(page, 'Personalities')
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
      await openAIBehaviorSection(page, 'Personalities')
      await personality.getByLabel('Editable prompt').fill('Keep personality draft')
      await openAIBehaviorSection(page, 'Profile instructions')
      await profile.locator('textarea').fill('Profile draft')
      await profile.getByRole('button', { name: 'Open Playground' }).click()
      await profile.getByRole('button', { name: action === 'current' ? 'Use current applied settings' : action === 'apply' ? 'Apply draft and open Playground' : 'Save draft and open Playground' }).click()
      expect(await testPrompt(page)).toMatchObject({ profile: action === 'current' ? '' : 'Profile draft', personalityPrompt: 'Synthetic neutral prompt.' })
      await openAIBehaviorSection(page, 'Personalities')
      await expect(personality.getByLabel('Editable prompt')).toHaveValue('Keep personality draft')
      await openAIBehaviorSection(page, 'Profile instructions')
      await expect(profile.locator('textarea')).toHaveValue('Profile draft')
      expect(await page.evaluate(() => Reflect.get(window, 'aiCalls'))).toEqual(action === 'current' ? [] : [[`${action}_profile_instructions`, 'Profile draft']])
      if (action === 'apply') {
        await expect(profile.getByText('Runtime only', { exact: true })).toBeVisible()
        await profile.getByRole('button', { name: 'Open Playground' }).click()
        await profile.getByRole('button', { name: 'Save applied instructions and open Playground' }).click()
        await openAIBehaviorSection(page, 'Profile instructions')
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
    await models.getByLabel('Primary model', { exact: true }).fill('synthetic-custom')
    await openAIBehaviorSection(page, 'Response languages')
    await selectOption(language.getByLabel('Response language mode'), 'limited')
    await language.getByRole('button', { name: 'Open Playground' }).click()
    await language.getByRole('button', { name: 'Use current applied settings' }).click()
    expect(await testPrompt(page)).toMatchObject({ model: 'synthetic-primary', language: { mode: 'auto' } })
    await expect(page.locator('.playground-draft-warning')).toBeVisible()
    await models.getByRole('button', { name: 'Save AI setup', exact: true }).click()
    await expect(models).toContainText('AI setup saved')
    expect(await testPrompt(page)).toMatchObject({ model: 'synthetic-custom', language: { mode: 'auto' } })
    await openAIBehaviorSection(page, 'Response languages')
    await expect(language.getByLabel('Response language mode')).toHaveAttribute('data-value', 'limited')
    await language.getByRole('button', { name: 'Open Playground' }).click()
    await language.getByRole('button', { name: 'Use current applied settings' }).click()
    expect(await testPrompt(page)).toMatchObject({ language: { mode: 'auto' } })
    await openAIBehaviorSection(page, 'Response languages')
    await language.getByRole('button', { name: 'Open Playground' }).click()
    await language.getByRole('button', { name: 'Save draft and open Playground' }).click()
    expect(await testPrompt(page)).toMatchObject({ model: 'synthetic-custom', language: { mode: 'limited' } })

  })

  test(`AI drafts survive Commands navigation and canceling a command edit at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await openAI(page)
    const profile = page.locator('#ai-profile-instructions')
    await openAIBehaviorSection(page, 'Profile instructions')
    await profile.locator('textarea').fill('Keep profile draft')
    await profile.getByRole('button', { name: 'Open Playground' }).click()
    await profile.getByRole('button', { name: 'Use current applied settings' }).click()
    const settingsNav = page.getByRole('navigation', { name: 'Main navigation' })
    await settingsNav.getByRole('button', { name: 'Settings', exact: true }).click()
    await expect(settingsNav.locator('#nav-Settings')).not.toContainText('Gemini API key')
    await expect(page.locator('#credential-settings')).toHaveCount(0)
    await page.getByRole('button', { name: 'AI', exact: true }).click()
    await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'AI setup', exact: true }).click()
    await expect(page.locator('#ai-models')).toBeInViewport()
    await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'Playground', exact: true }).click()
    await expect(page.locator('#ai-playground')).toBeInViewport()
    await expect(page.locator('.playground-draft-warning')).toBeVisible()
    await settingsNav.getByRole('button', { name: 'Commands', exact: true }).click()
    await selectOption(page.getByRole('combobox', { name: 'Status', exact: true }), 'all')
    const ask = page.locator('#command-editor-ask')
    await page.getByRole('button', { name: 'Edit !ask', exact: true }).click()
    await expect(ask).toBeInViewport()
    await ask.getByLabel('Per-user cooldown', { exact: true }).fill('9')
    await ask.getByRole('button', { name: 'Close editor' }).click()
    await page.getByRole('dialog', { name: 'Discard unsaved changes?' }).getByRole('button', { name: 'Confirm' }).click()
    await page.getByRole('button', { name: 'AI', exact: true }).click()
    await openAIBehaviorSection(page, 'Profile instructions')
    await expect(profile.locator('textarea')).toHaveValue('Keep profile draft')
    await closeAIBehavior(page)
    await page.getByRole('dialog', { name: 'Discard unsaved AI behavior changes?' }).getByRole('button', { name: 'Confirm' }).click()
    await settingsNav.getByRole('button', { name: 'Commands', exact: true }).click()
    await page.getByRole('button', { name: 'Edit !ask', exact: true }).click()
    await expect(ask.getByLabel('Per-user cooldown', { exact: true })).not.toHaveValue('9')
  })
}

const editorSections = { 'ai-personalities': 'Personalities', 'ai-profile-instructions': 'Profile instructions', 'ai-language': 'Response languages' } as const

for (const [id, failure, field] of [
  ['ai-personalities', 'savePersonalityError', 'Editable prompt'],
  ['ai-profile-instructions', 'profileError', 'Profile instructions'],
  ['ai-language', 'languageSaveError', 'Response language mode'],
]) {
  test(`failed ${id} save keeps the draft choice and does not open Playground`, async ({ page }) => {
    await openAI(page, failure)
    const editor = await openAIBehaviorSection(page, editorSections[id as keyof typeof editorSections])
    if (id === 'ai-language') await selectOption(editor.getByLabel(field), 'limited')
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
  await expect(playground).toContainText('The bot can be stopped and the AI command disabled')
  await expect(playground).toContainText('Success does not prove Twitch delivery')
  await expect(playground).toContainText('real provider API quota')
  const memory = page.getByRole('form', { name: 'Conversation memory' })
  await memory.getByRole('button', { name: 'Help: Conversation memory', exact: true }).click()
  await expect(page.getByRole('tooltip')).toContainText('Previously stored pairs remain subject to count limits and 60-day expiry')
  await expect(page.getByRole('tooltip')).toContainText('Playground never reads or stores viewer memory')
  await expect(page.getByRole('tooltip')).toContainText('clears AI memory for a known viewer in that channel')
  await page.keyboard.press('Escape')
  await page.getByRole('navigation').getByRole('button', { name: 'Commands', exact: true }).click()
  await page.getByRole('button', { name: 'Help: User command restrictions', exact: true }).click()
  await expect(page.getByRole('tooltip')).toContainText('not Twitch bans or timeouts')
  await page.keyboard.press('Escape')
  await page.getByRole('navigation').getByRole('button', { name: 'AI', exact: true }).click()
  expect(await testPrompt(page)).toMatchObject({ personality: 'neutral' })
})

test('draft choices fit the supported 320px layout', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 })
  await openAI(page)
  const profile = page.locator('#ai-profile-instructions')
  await openAIBehaviorSection(page, 'Profile instructions')
  await profile.locator('textarea').fill('Draft instructions')
  await profile.getByRole('button', { name: 'Open Playground' }).click()
  await expect(profile.getByRole('button', { name: 'Apply draft and open Playground' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
  await page.screenshot({ path: 'node_modules/.tmp/a4-draft-choice-320.png', fullPage: true })
})

test('Commands navigation reaches recovery when Ask is removed', async ({ page }) => {
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
  await page.getByRole('navigation').getByRole('button', { name: 'Commands', exact: true }).click()
  await selectOption(page.getByRole('combobox', { name: 'Status', exact: true }), 'disabled')
  await expect(page.getByRole('checkbox', { name: 'Enable !ask', exact: true })).not.toBeChecked()
  await page.getByRole('button', { name: 'Edit !ask', exact: true }).click()
  await expect(page.locator('#command-editor-ask')).toBeInViewport()
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
    const state = page.locator('#ai-behavior')
    await expect(state.getByRole('heading')).toHaveText('AI behavior')
    const shortcuts = state.locator('.ai-behavior-shortcuts')
    const values = state.locator('.ai-runtime-values')
    const linksBox = (await shortcuts.boundingBox())!
    const valuesBox = (await values.boundingBox())!
    const contentWidth = (await page.locator('.page-content').boundingBox())!.width
    if (contentWidth > 620) expect(linksBox.x).toBeGreaterThan(valuesBox.x + valuesBox.width)
    else expect(linksBox.y).toBeGreaterThan(valuesBox.y + valuesBox.height)
    const memory = page.getByRole('form', { name: 'Conversation memory' })
    const memoryBox = (await memory.boundingBox())!
    const stateBox = (await state.boundingBox())!
    expect(memoryBox.y).toBeGreaterThan(stateBox.y + stateBox.height)
    const fields = (await memory.locator('.memory-limit-fields').boundingBox())!
    const toggle = (await memory.locator('.memory-limits-toggle').boundingBox())!
    if (contentWidth > 620) {
      const controls = (await memory.locator('.memory-limits-controls').boundingBox())!
      expect(controls.x).toBeCloseTo(linksBox.x, 0)
      expect(toggle.x).toBeGreaterThan(fields.x + fields.width)
    } else expect(fields.y).toBeGreaterThan(toggle.y)
    expect(await state.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBeTruthy()
    await state.screenshot({ path: `node_modules/.tmp/a4-state-${width}.png` })

    const language = page.locator('#ai-language')
    await openAIBehaviorSection(page, 'Response languages')
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
    if ((await language.boundingBox())!.width > 620) {
      expect(fallback.y).toBe(mode.y)
      const helpers = await language.locator('.language-fields small').all()
      expect((await helpers[0].boundingBox())!.y).toBe((await helpers[1].boundingBox())!.y)
    } else expect(fallback.y).toBeGreaterThan(mode.y + mode.height)
    await language.screenshot({ path: `node_modules/.tmp/a4-language-${width}.png` })

    await closeAIBehavior(page)
    await page.getByRole('dialog', { name: 'Discard unsaved AI behavior changes?' }).getByRole('button', { name: 'Confirm' }).click()
    const models = page.locator('#ai-models')
    await models.locator('.accordion-trigger').click()
    await models.locator('.ai-manual-model summary').first().click()
    await expect(models.getByRole('button', { name: 'Discover primary models' })).toBeVisible()
    await models.getByLabel('Primary model', { exact: true }).fill('synthetic-draft')
    await expect(models).toContainText('Unsaved AI setup')
    await models.screenshot({ path: `node_modules/.tmp/a4-models-${width}.png` })
    await expect(state.locator('dt:has-text("Conversation memory") + dd')).toHaveText('Disabled')
    expect(await page.locator('.ai-layout').evaluate((element) => element.scrollWidth <= element.clientWidth)).toBeTruthy()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}

test('memory toggle saves independently and reports failures without changing its value', async ({ page }) => {
  await openAI(page)
  const memory = page.getByRole('form', { name: 'Conversation memory' })
  const toggle = memory.getByRole('checkbox', { name: 'Enable conversation memory' })
  const stored = memory.getByLabel('Stored pairs (N)')
  await stored.fill('24')
  await toggle.press('Space')
  await expect(toggle).toBeChecked()
  await expect(stored).toHaveValue('24')
  expect(await page.evaluate(() => Reflect.get(window, 'aiCalls'))).toEqual([['set_ai_memory_enabled', true]])

  await openAI(page, 'memorySaveError')
  await toggle.press('Space')
  await expect(page.getByRole('alert')).toContainText('Could not save conversation memory setting.')
  await expect(toggle).not.toBeChecked()
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
  const state = page.locator('#ai-behavior')
  await expect(state.getByRole('heading')).toHaveText('AI behavior')
  await expect(page.getByRole('checkbox', { name: 'Enable conversation memory' })).toBeDisabled()
  await expect(state).toContainText('Loading…')
  await page.evaluate(() => Reflect.get(window, 'releaseAIStatus')())
  await expect(page.locator('.ai-layout')).toHaveAttribute('aria-busy', 'false')
  await expect(state).toContainText('Active personality')
  await page.getByRole('navigation').getByRole('button', { name: 'AI setup', exact: true }).click()
  await expect(page.locator('#ai-models')).toBeInViewport()
})

test('model discovery stays inside selection and leaves drafts unsaved', async ({ page }) => {
  await openAI(page)
  const models = page.locator('#ai-models')
  await models.getByRole('button', { name: 'Discover primary models' }).click()
  await models.getByLabel('Primary model', { exact: true }).fill('gemini-discovered-model')
  await expect(models.getByRole('button', { name: 'Save AI setup', exact: true })).toBeEnabled()
  await expect(models).toContainText('Unsaved AI setup')
  expect(await page.evaluate(() => Reflect.get(window, 'aiCalls'))).toEqual([])
})

test('AI behavior keeps drafts between sections and discards only editor changes', async ({ page }) => {
  await openAI(page)
  const model = page.locator('#ai-models').getByLabel('Primary model', { exact: true })
  await model.fill('keep-setup-draft')
  const memory = page.getByRole('form', { name: 'Conversation memory' })
  const stored = memory.getByLabel('Stored pairs (N)')
  await stored.fill('24')
  const open = page.getByRole('button', { name: 'Edit personalities', exact: true })
  await open.click()
  const tabs = aiBehaviorDialog(page).getByRole('navigation', { name: 'AI behavior sections' }).getByRole('button')
  await expect(tabs).toHaveText(['Personalities', 'Profile instructions', 'Shared instructions', 'Response languages'])
  await expect(tabs.first()).toHaveAttribute('aria-current', 'true')
  const profile = await openAIBehaviorSection(page, 'Profile instructions')
  await profile.locator('textarea').fill('Temporary profile text')
  const personality = await openAIBehaviorSection(page, 'Personalities')
  await personality.getByLabel('Editable prompt').fill('Temporary personality')
  const shared = await openAIBehaviorSection(page, 'Shared instructions')
  await shared.getByLabel('Shared AI instructions').fill('Temporary shared instructions')
  const languages = await openAIBehaviorSection(page, 'Response languages')
  await selectOption(languages.getByLabel('Response language mode'), 'limited')
  await openAIBehaviorSection(page, 'Profile instructions')
  await expect(profile.locator('textarea')).toHaveValue('Temporary profile text')

  await page.keyboard.press('Escape')
  const confirmDiscard = page.getByRole('dialog', { name: 'Discard unsaved AI behavior changes?' })
  await confirmDiscard.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(profile.locator('textarea')).toHaveValue('Temporary profile text')
  await page.mouse.click(3, 3)
  await confirmDiscard.getByRole('button', { name: 'Confirm', exact: true }).click()
  await expect(aiBehaviorDialog(page)).toBeHidden()
  await expect(open).toBeFocused()
  await expect(model).toHaveValue('keep-setup-draft')
  await expect(stored).toHaveValue('24')

  await openAIBehaviorSection(page, 'Profile instructions')
  await expect(profile.locator('textarea')).toHaveValue('')
  await openAIBehaviorSection(page, 'Personalities')
  await expect(personality.getByLabel('Editable prompt')).toHaveValue('Synthetic neutral prompt.')
  await openAIBehaviorSection(page, 'Shared instructions')
  await expect(shared.getByLabel('Shared AI instructions')).not.toHaveValue('Temporary shared instructions')
  await openAIBehaviorSection(page, 'Response languages')
  await expect(languages.getByLabel('Response language mode')).toHaveAttribute('data-value', 'auto')
  await closeAIBehavior(page)
  await expect(page.getByRole('button', { name: 'Edit profile instructions', exact: true })).toBeFocused()
})

for (const width of [1280, 390, 320]) {
  test(`AI behavior fits short sections and fixes the Save row while fields scroll at ${width}px`, async ({ page }) => {
    const height = 760
    await page.setViewportSize({ width, height })
    await openAI(page)
    const profile = await openAIBehaviorSection(page, 'Profile instructions')
    const dialog = aiBehaviorDialog(page)
    const profileBox = (await dialog.boundingBox())!
    expect(profileBox.height).toBeGreaterThanOrEqual(360)
    expect(profileBox.height).toBeLessThan(height - 28)
    const sections = dialog.getByRole('navigation', { name: 'AI behavior sections' })
    const sectionBox = (await sections.boundingBox())!
    const fieldsBox = (await profile.locator('.ai-behavior-fields').boundingBox())!
    if (width > 640) expect(sectionBox.x + sectionBox.width).toBeLessThanOrEqual(fieldsBox.x)
    else expect(sectionBox.y + sectionBox.height).toBeLessThanOrEqual(fieldsBox.y)

    const languages = await openAIBehaviorSection(page, 'Response languages')
    const languageBox = (await dialog.boundingBox())!
    expect(languageBox.height).toBeGreaterThanOrEqual(profileBox.height)
    expect(languageBox.height).toBeLessThanOrEqual(height - 28)
    await page.setViewportSize({ width, height: 480 })
    const save = languages.getByRole('button', { name: 'Save language settings' })
    const fields = languages.locator('.ai-behavior-fields')
    const footer = (await save.boundingBox())!
    await fields.evaluate((element) => { element.scrollTop = element.scrollHeight })
    expect(await fields.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
    expect((await save.boundingBox())!.y).toBe(footer.y)
    await expect(save).toBeInViewport()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  })
}
