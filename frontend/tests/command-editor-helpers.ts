import type { Locator, Page } from '@playwright/test'
import { selectOption } from './select-helpers'

export async function createEntry(page: Page, type: 'custom' | 'reaction') {
  await selectOption(page.getByRole('combobox', { name: 'Create', exact: true }), type)
}

export async function openEditorSection(editor: Locator, name: string) {
  await editor.getByRole('navigation', { name: 'Editor sections', exact: true })
    .getByRole('button', { name, exact: true }).click()
}
