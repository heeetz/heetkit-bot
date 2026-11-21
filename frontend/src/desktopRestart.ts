import { useLayoutEffect } from 'react'
import { waitForBridge } from './bridge'
import { aboutText } from './i18n/about'
import { catalogFor, fmt } from './i18n/core'

// Desktop pages keep their editors mounted when the operator navigates away.
// Editor names are stable English ids; the prompt shows them in the UI language.
const unsavedEditors = new Set<string>()

export function useRestartDraft(editor: string, dirty: boolean) {
  useLayoutEffect(() => {
    if (!dirty) return
    unsavedEditors.add(editor)
    return () => { unsavedEditors.delete(editor) }
  }, [editor, dirty])
}

export function confirmDesktopRestart(savedEditor?: string) {
  const pending = [...unsavedEditors].filter((editor) => editor !== savedEditor)
  if (!pending.length) return true
  const text = catalogFor(aboutText).restart
  const names: Record<string, string> = text.editors
  return window.confirm(fmt(text.prompt, { editors: pending.map((editor) => names[editor] ?? editor).join(', ') }))
}

export async function restartDesktop(savedEditor?: string) {
  if (!confirmDesktopRestart(savedEditor)) return false
  const result = await (await waitForBridge()).restart_desktop()
  if (!result.ok) throw new Error(result.error ?? catalogFor(aboutText).restart.failed)
  return true
}
