import { useLayoutEffect } from 'react'
import { waitForBridge } from './bridge'

// Desktop pages keep their editors mounted when the operator navigates away.
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
  return window.confirm(`Unsaved changes in ${pending.join(', ')} will be lost when HeetKit closes. Select Cancel to go back and save them, or OK to discard them and restart.`)
}

export async function restartDesktop(savedEditor?: string) {
  if (!confirmDesktopRestart(savedEditor)) return false
  const result = await (await waitForBridge()).restart_desktop()
  if (!result.ok) throw new Error(result.error ?? 'HeetKit could not restart.')
  return true
}
