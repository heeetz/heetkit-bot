import { useState, type FormEvent, type ReactNode } from 'react'
import EditorDialog, { EditorSections } from './EditorDialog'
import { commandEditorCopy as copy } from '../i18n/commands.en'

export interface CommandEditorSection {
  id: keyof typeof copy.sections
  body: ReactNode
}

export default function CommandEditorDialog({ id, title, dirty, busy, error, sections, saveLabel, saveDisabled, onSave, onClose }: {
  id: string
  title: string
  dirty: boolean
  busy: boolean
  error: string
  sections: CommandEditorSection[]
  saveLabel: string
  saveDisabled?: boolean
  onSave: () => void
  onClose: () => void
}) {
  const [section, setSection] = useState<CommandEditorSection['id']>('general')
  const [validationError, setValidationError] = useState('')
  const activeSection = sections.some((item) => item.id === section) ? section : 'general'

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (busy || saveDisabled) return
    // All draft fields stay mounted, including native inputs in inactive sections.
    const invalid = event.currentTarget.querySelector<HTMLInputElement | HTMLTextAreaElement>('input:invalid, textarea:invalid')
    if (invalid) {
      const target = sections.find((item) => invalid.closest(`#${id}-${item.id}`))
      if (target) setSection(target.id)
      setValidationError(invalid.validationMessage)
      requestAnimationFrame(() => invalid.focus())
      return
    }
    setValidationError('')
    onSave()
  }

  return <EditorDialog id={id} title={title} closeLabel={copy.close} dirtyLabel={dirty ? copy.unsaved : undefined}
    busy={busy} error={validationError || error} onClose={onClose}>
    <form className="command-editor-form" noValidate onSubmit={submit} onInput={() => setValidationError('')}>
      <EditorSections id={id} label={copy.sectionsLabel} active={activeSection} onSelect={setSection}
        sections={sections.map(({ id: sectionId, body }) => ({
          id: sectionId, label: copy.sections[sectionId], body: <fieldset disabled={busy}>{body}</fieldset>,
        }))} />
      <div className="command-dialog-footer">
        <button type="button" className="secondary" disabled={busy} onClick={onClose}>{copy.cancel}</button>
        <button type="submit" className="primary" disabled={busy || saveDisabled}>{busy ? copy.saving : saveLabel}</button>
      </div>
    </form>
  </EditorDialog>
}
