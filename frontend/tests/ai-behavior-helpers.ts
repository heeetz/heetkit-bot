import type { Page } from '@playwright/test'

type AIBehaviorSection = 'Profile instructions' | 'Personalities' | 'Shared instructions' | 'Response languages'

const sectionIds = {
  'Profile instructions': 'ai-profile-instructions',
  Personalities: 'ai-personalities',
  'Shared instructions': 'ai-shared-instructions',
  'Response languages': 'ai-language',
}

export function aiBehaviorDialog(page: Page) {
  return page.getByRole('dialog', { name: 'Edit AI behavior', exact: true })
}

export async function openAIBehaviorSection(page: Page, section: AIBehaviorSection) {
  const dialog = aiBehaviorDialog(page)
  if (await dialog.isVisible()) {
    await dialog.getByRole('navigation', { name: 'AI behavior sections' }).getByRole('button', { name: section, exact: true }).click()
  } else {
    await page.locator('#ai-behavior').getByRole('button', { name: `Edit ${section.toLowerCase()}`, exact: true }).click()
  }
  return dialog.locator(`#${sectionIds[section]}`)
}

export async function closeAIBehavior(page: Page) {
  await aiBehaviorDialog(page).getByRole('button', { name: 'Close editor', exact: true }).click()
}
